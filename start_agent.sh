#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load OLLAMA_URL from .env if present
if [ -f .env ]; then
    OLLAMA_URL=$(grep '^OLLAMA_URL=' .env | cut -d '=' -f2- | tr -d '"' | tr -d "'")
fi
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"

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
    curl -sf "$OLLAMA_URL/api/generate" \
        -d "{\"model\":\"$model\",\"keep_alive\":-1,\"prompt\":\"\"}" \
        > /dev/null
    echo "ready"
}

echo "Pre-loading models:"
load_model "qwen3.5:9b"
load_model "qwen2.5vl:7b"
load_model "nomic-embed-text"

# ── Activate venv if present ──────────────────────────────────────────────────
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

# ── Start agent ───────────────────────────────────────────────────────────────
echo ""
echo "Starting Antartia..."
echo ""
exec python -m agent --config "$CONFIG"
