#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load vars from .env if present
if [ -f .env ]; then
    OLLAMA_URL=$(grep '^OLLAMA_URL=' .env | cut -d '=' -f2- | tr -d '"' | tr -d "'")
    KNOWLEDGE_CHROMA_DIR=$(grep '^KNOWLEDGE_CHROMA_DIR=' .env | cut -d '=' -f2- | tr -d '"' | tr -d "'")
    KNOWLEDGE_INBOX_DIR=$(grep '^KNOWLEDGE_INBOX_DIR=' .env | cut -d '=' -f2- | tr -d '"' | tr -d "'")
    KNOWLEDGE_PROCESSED_DIR=$(grep '^KNOWLEDGE_PROCESSED_DIR=' .env | cut -d '=' -f2- | tr -d '"' | tr -d "'")
fi
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
KNOWLEDGE_CHROMA_DIR="${KNOWLEDGE_CHROMA_DIR:-./data/knowledge_db}"
KNOWLEDGE_INBOX_DIR="${KNOWLEDGE_INBOX_DIR:-./data/knowledge/inbox}"
KNOWLEDGE_PROCESSED_DIR="${KNOWLEDGE_PROCESSED_DIR:-./data/knowledge/processed}"

CONFIG="${1:-configs/expedition_config.json}"

# ── Check Ollama is running ────────────────────────────────────────────────────
echo "Checking Ollama..."
if ! curl -sf "$OLLAMA_URL/api/tags" > /dev/null; then
    echo "Error: Ollama is not running at $OLLAMA_URL"
    echo "Start it with: ollama serve"
    exit 1
fi

# ── Pre-load models (keep_alive=-1 = never unload) ────────────────────────────
load_model() {
    local model="$1"
    echo -n "  Loading $model ... "
    response=$(curl -s -w "%{http_code}" "$OLLAMA_URL/api/generate" \
        -d "{\"model\":\"$model\",\"keep_alive\":-1,\"prompt\":\"\"}" \
        -o /dev/null)
    if [ "$response" != "200" ]; then
        echo "not found (HTTP $response)"
        echo "  Run: ollama pull $model"
        exit 1
    fi
    echo "ready"
}

echo "Pre-loading models:"
load_model "qwen3.5:9b"
load_model "qwen2.5vl:3b"

# Embedding models use /api/embed, not /api/generate
echo -n "  Loading nomic-embed-text ... "
embed_response=$(curl -s -w "%{http_code}" "$OLLAMA_URL/api/embed" \
    -d '{"model":"nomic-embed-text","input":[""],"keep_alive":-1}' \
    -o /dev/null)
if [ "$embed_response" != "200" ]; then
    echo "not found (HTTP $embed_response)"
    echo "  Run: ollama pull nomic-embed-text"
    exit 1
fi
echo "ready"

# ── Activate venv if present ──────────────────────────────────────────────────
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

# ── Ensure data directories exist ─────────────────────────────────────────────
mkdir -p data/photos/inbox data/photos/processed data/photos/vision_preview
mkdir -p "$KNOWLEDGE_INBOX_DIR" "$KNOWLEDGE_PROCESSED_DIR" "$KNOWLEDGE_CHROMA_DIR"

# ── Start agent ───────────────────────────────────────────────────────────────
echo ""
echo "Starting Antartia..."
echo ""
exec python -m agent --config "$CONFIG" "${@:2}"
