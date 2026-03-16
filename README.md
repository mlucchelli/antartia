# AItartica

An autonomous AI agent built for Antarctic field expeditions. Runs entirely on-device — no cloud dependency for inference — and orchestrates GPS tracking, photo analysis, weather monitoring, knowledge accumulation, and live publishing to an expedition website through a recursive tool-chaining loop driven by a local LLM.

Built for the MV Ortelius Antarctic expedition, March–April 2026.

---

## What it does

AItartica sits in a terminal on expedition hardware (laptop, NUC) and acts as an intelligent field assistant. An iPhone sends GPS coordinates via HTTP every hour. Photos dropped into an inbox folder are automatically preprocessed, described by a vision model, scored for significance, and selectively published. Weather is fetched four times daily. At 21:00 local time, the agent writes and publishes a daily reflection. Every 12 hours it analyzes the expedition route and publishes a navigation snapshot.

The agent doesn't just retrieve data — it **reasons over it**. Ask about today's route and it chains `analyze_route` → `get_route_analysis` → `send_message` in a single turn. Ask it to scan the inbox and it runs the full pipeline — preprocessing, vision+scoring in one model call, upload queueing — streaming each step to the terminal.

---

## Architecture

### Recursive tool chaining

Every user message triggers an LLM call that returns a list of actions. Non-final actions are executed and their results appended to the context. The LLM is re-invoked. This repeats until `finish` — up to `max_chain_depth = 6`. The LLM decides what to fetch and in what order.

```
User: "what happened today?"
  → LLM → [get_logs, get_photos, get_weather]
  → results appended
  → LLM → [send_message, finish]
```

### Execution semaphore

One asyncio lock coordinates three concurrent subsystems:

```
idle → user_typing → llm_running → idle
idle → task_running → idle
HTTP server: always running, never locked
```

The CLI holds the lock from prompt display through the final `finish`. The scheduler runs only when idle. The HTTP server never touches the lock — GPS coordinates are always stored immediately.

### Photo pipeline

Photos dropped into `data/photos/inbox/` go through:

1. **Preprocessing** — EXIF correction, resize (longest side 640–800px), SHA-256 fingerprint. Original never modified.
2. **Vision + scoring** — Single model call to `qwen2.5vl:3b`: returns description, `significance_score` (0.0–1.0), `agent_quote` (≤10 words, only if score ≥ 0.8), and `tags`. One Ollama call, one JSON response.
3. **Upload queue** — Photos scoring ≥ 0.75 are flagged as remote candidates and automatically queued for upload to the expedition website.

```
inbox/photo.jpg
  → resize → vision_preview/photo_preview.jpg
  → qwen2.5vl:3b → {description, score: 0.82, quote: "Ice remembers everything.", tags: ["iceberg"]}
  → score ≥ 0.75 → queued for upload
  → original → processed/photo.jpg
```

### Remote sync with retry

All pushes to the expedition API go through `RemoteSyncService`. On failure, items are queued in `sync_queue` with up to 100 retries — the scheduler retries on every tick. Photos are stored as multipart metadata; JSON payloads are stored inline. The agent never loses data due to connectivity failures.

### Scheduled routines

| Time | Action |
|------|--------|
| Every 60s | Retry pending sync queue items |
| 3h, 9h, 15h, 21h Argentina | Fetch weather from Open-Meteo |
| 9h, 21h Argentina | Route analysis → auto-publish navigation snapshot, route, weather, progress |
| 21h Argentina | Daily reflection → auto-publish |

### Knowledge base

Local ChromaDB stores semantic embeddings of expedition documents (itinerary, species guides, ship specs, location descriptions). Embedded via `nomic-embed-text` through Ollama. `search_knowledge` retrieves the top-5 relevant chunks. The agent adds new knowledge freely during the expedition — species observations, site notes, crew information.

### Timezone

All timestamps stored in UTC. All date filtering uses Argentina timezone (UTC-3, no DST) via `src/agent/utils/tz.py`. SQL queries use UTC range bounds (`WHERE col >= ? AND col < ?`) computed from Argentina-day boundaries. The agent sees Argentina local time in its system prompt.

---

## Stack

| Layer | Technology |
|-------|------------|
| Chat LLM | `qwen3.5:9b` via Ollama |
| Vision + scoring | `qwen2.5vl:3b` via Ollama (merged single call) |
| Embeddings | `nomic-embed-text` via Ollama |
| Vector store | ChromaDB (embedded, no server) |
| Database | SQLite via `aiosqlite` |
| HTTP client | `httpx` (async) |
| Image processing | Pillow |
| Terminal UI | Rich |
| Config | Pydantic v2 + JSON |
| Weather API | Open-Meteo ECMWF IFS (polar-tuned) |

Everything runs offline except weather fetching and remote publishing. No dedicated GPU required — Apple Silicon unified memory handles all three models simultaneously with `keep_alive=-1` (models stay loaded permanently).

---

## Project structure

```
src/agent/
├── __main__.py                  — Entry: CLI + HTTP server + scheduler (concurrent tasks)
├── config/loader.py             — Pydantic config; sensitive values from env
├── utils/tz.py                  — Timezone source of truth: AGENT_TZ, today_arg(), day_utc_bounds()
├── cli/app.py                   — Terminal UI: scroll area, spinner, status bar
├── db/
│   ├── database.py              — aiosqlite + migrations (ALTER TABLE pattern)
│   ├── locations_repo.py        — GPS locations
│   ├── photos_repo.py           — Photos + vision results + upload state
│   ├── weather_repo.py          — Weather snapshots
│   ├── tasks_repo.py            — Task queue (FIFO, DB-backed)
│   ├── messages_repo.py         — Agent messages
│   ├── activity_logs_repo.py    — Auto-logged tool calls
│   ├── reflections_repo.py      — Daily reflections (unique per date)
│   ├── sync_queue_repo.py       — Remote sync retry queue
│   ├── token_usage_repo.py      — LLM token accounting
│   └── route_analyses_repo.py   — Navigation analysis snapshots
├── http/server.py               — asyncio HTTP: POST /locations (GPS from iPhone)
├── llm/
│   ├── ollama.py                — Chat client (structured output)
│   ├── ollama_vision.py         — Vision client (base64 → JSON description+score+quote+tags)
│   └── prompt_builder.py        — System prompt builder (injects Argentina local time)
├── models/actions.py            — All action types (Pydantic)
├── runtime/
│   ├── runtime.py               — Recursive chaining loop + tool dispatch + auto-logging
│   ├── scheduler.py             — 60s tick: weather + reflection + route + sync retry
│   ├── semaphore.py             — ExecutionSemaphore (4 states)
│   ├── task_runner.py           — Dispatches all task types to services
│   └── parser.py                — ACTION_REGISTRY
└── services/
    ├── photo_service.py         — Full photo pipeline (scan → preprocess → vision → move → queue)
    ├── image_preprocessing.py   — EXIF correction + resize
    ├── weather_service.py       — Open-Meteo fetch + DB persistence
    ├── knowledge_service.py     — ChromaDB index + search
    ├── distance_service.py      — Haversine total distance from GPS points
    ├── reflection_service.py    — Daily reflection: gathers data → LLM → saves + publishes
    ├── route_analysis_service.py— Bearing + speed + wind + nearest landing sites
    └── remote_sync_service.py   — push() + push_photo() + retry_pending()

configs/
└── expedition_config.json       — All agent config (personality, actions, prompts, schedules)

data/
├── photos/inbox/                — Drop photos here
├── photos/processed/            — Originals after processing
├── photos/vision_preview/       — Resized JPEG previews (sent to vision model + uploaded)
├── knowledge/inbox/             — Drop .txt/.md expedition documents here
├── knowledge/processed/         — Documents after indexing
└── antartia.db                  — SQLite database
```

---

## Available actions

| Action | Trigger | Description |
|--------|---------|-------------|
| `get_latest_locations` | Manual | Fetch most recent GPS positions |
| `get_locations_by_date` | Manual | GPS positions for a specific day (Argentina date) |
| `get_photos` | Manual | Photo records with vision descriptions and scores |
| `get_weather` | Manual / Scheduled | Live weather fetch + store snapshot |
| `get_distance` | Manual | Total distance traveled today or on a given date |
| `get_logs` | Manual | Activity log entries for a time range |
| `get_token_usage` | Manual | LLM token usage breakdown by call type |
| `get_reflections` | Manual | Daily reflections (by date or recent N) |
| `get_route_analysis` | Manual | Cached route analysis (by date or latest) |
| `analyze_route` | Manual / Scheduled | Navigation analysis: bearing, speed, wind, nearest sites |
| `scan_photo_inbox` | Manual | Scan inbox and run full pipeline on all new photos |
| `add_location` | Manual | Manually insert a GPS coordinate (GPS fallback) |
| `search_knowledge` | Manual | Semantic search over expedition knowledge base |
| `index_knowledge` | Manual | Re-index all documents in the knowledge folder |
| `add_knowledge` | Manual | Add a free-text observation to the knowledge base |
| `clear_knowledge` | Manual | Wipe the knowledge base |
| `create_task` | Manual | Queue a background task for the scheduler |
| `publish_reflection` | Manual / Scheduled | Write and publish daily reflection |
| `publish_daily_progress` | Manual / Scheduled | Aggregate totals and publish to expedition site |
| `publish_route_analysis` | Manual / Scheduled | Publish navigation snapshot |
| `publish_route_snapshot` | Manual / Scheduled | Publish full GeoJSON GPS track |
| `publish_weather_snapshot` | Manual / Scheduled | Publish latest weather reading |
| `upload_image` | Manual / Auto | Upload a remote-candidate photo with tags and optional quote |
| `comment` | Manual | Post a short live dispatch to the expedition website |
| `send_message` | Chain | Display text to user (non-terminal) |
| `finish` | Chain | Terminate the chain (required in every response) |

---

## Setup

### 1. Install Ollama

Download from [ollama.com](https://ollama.com). Verify it's running:

```bash
ollama list
```

### 2. Pull models

```bash
ollama pull qwen3.5:9b        # Chat LLM — ~6 GB
ollama pull qwen2.5vl:3b      # Vision + scoring — ~2 GB
ollama pull nomic-embed-text  # Embeddings — ~300 MB
```

### 3. Clone and install

```bash
git clone https://github.com/mlucchelli/antartia.git
cd antartia
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env with your paths and keys
```

Required env vars:

```env
DB_PATH=./data/antartia.db
OLLAMA_URL=http://localhost:11434
PHOTO_INBOX_DIR=./data/photos/inbox
PHOTO_PROCESSED_DIR=./data/photos/processed
PHOTO_PREVIEW_DIR=./data/photos/vision_preview
VISION_MAX_DIM=800
VISION_MIN_DIM=640
KNOWLEDGE_CHROMA_DIR=./data/knowledge_db
KNOWLEDGE_INBOX_DIR=./data/knowledge/inbox
KNOWLEDGE_PROCESSED_DIR=./data/knowledge/processed
HTTP_HOST=0.0.0.0
HTTP_PORT=8080
SCHEDULER_TICK_SECONDS=60
AGENT_TIMEZONE=America/Argentina/Buenos_Aires

# Expedition website (optional)
SERVER_HOST=https://your-railway-app.railway.app
REMOTE_SYNC_API_KEY=your_key_here
```

### 5. Create data directories

```bash
mkdir -p data/photos/inbox data/photos/processed data/photos/vision_preview
mkdir -p data/knowledge/inbox data/knowledge/processed data/knowledge_db
```

### 6. Run

```bash
./start_agent.sh
```

This pre-loads all three models into memory with `keep_alive=-1` (permanent — no cold-start delays) then starts the agent. The HTTP server and scheduler start automatically.

---

## Tools

### Convert HEIC photos to JPEG

iPhone photos are shot in HEIC by default. Use `tools/heic_to_jpg.py` to convert them before dropping into the inbox (or the agent handles HEIC directly if `pillow-heif` is installed).

```bash
# Convert a single file
python tools/heic_to_jpg.py photo.heic

# Convert all HEIC files in a directory
python tools/heic_to_jpg.py data/photos/inbox/

# Convert to a specific output directory
python tools/heic_to_jpg.py data/photos/inbox/ -o data/photos/converted/

# Custom JPEG quality (default 95)
python tools/heic_to_jpg.py data/photos/inbox/ -q 90

# Convert and delete originals
python tools/heic_to_jpg.py data/photos/inbox/ --delete-originals
```

Images are saved at full original resolution. Resizing happens later inside the photo pipeline.

---

## License

MIT
