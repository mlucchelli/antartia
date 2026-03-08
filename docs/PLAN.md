# Engineering Plan — Antartia

> Detailed plan lives at [`plan.md`](../plan.md) in the project root.
> This document summarises the architecture and engineering decisions for reference.

---

## What we're building

An autonomous AI field agent for an Antarctic expedition. It runs on-device (MacBook, no GPU required), coordinates GPS tracking, weather monitoring, photo analysis, and expedition publishing — all driven by a local LLM through recursive tool chaining.

---

## Core engineering constraints

- **Fully offline inference** — Ollama serves all models locally. No cloud API needed during field operation (weather fetch and remote publish are the only network calls).
- **Single asyncio event loop** — CLI, HTTP server, and scheduler all share one loop. No threads except the blocking input executor.
- **One lock, three subsystems** — `ExecutionSemaphore` wraps a single `asyncio.Lock`. CLI holds it from prompt to reply. Scheduler acquires it between turns. HTTP server never touches it.
- **SQLite, no ORM** — `aiosqlite` with raw SQL. Six repos, one connection, WAL mode.
- **All paths from env** — No hardcoded paths or URLs in code. Everything via `.env`.

---

## Commit history

| #  | Description                                                                  | Status   |
|----|------------------------------------------------------------------------------|----------|
| 1  | Project setup, core models, config loader, schemas                           | Done     |
| 2  | StateStore, OutputHandler, ActionParser, PromptBuilder                       | Done     |
| 3  | Runtime orchestrator                                                         | Done     |
| 4  | CLI with terminal layout, spinner, status bar                                | Done     |
| 5  | OpenRouter LLM client + system prompt + debug mode                           | Done     |
| 6  | FileStateStore + enhanced CLI                                                | Done     |
| 7  | DB layer: aiosqlite + 6 table repos                                          | Done     |
| 8  | Models: LocationRecord, TaskRecord, PhotoRecord                              | Done     |
| 9  | Expedition config + remove legacy conversational configs                     | Done     |
| 10 | HTTP server: POST /locations → GPS insert + task queue                       | Done     |
| 11 | ExecutionSemaphore + Scheduler (60s tick)                                    | Done     |
| 12 | Semaphore redesign + FIFO tasks + async CLI input + recursive chaining       | Done     |
| 13 | TaskRunner: all task types + CLI task progress                               | Done     |
| 14 | OllamaClient + .env loading + full wiring in __main__.py                     | Done     |
| 15 | WeatherService: Open-Meteo ECMWF + DB persistence                           | Done     |
| 16 | CLI status bar: GPS + weather + precipitation + auto-refresh                 | Done     |
| 17 | ImagePreprocessingService + OllamaVisionClient (description + summary)       | Done     |
| 18 | PhotoService: scan inbox → preprocess → vision → score → move                | Done     |
| 19 | Embedding pipeline: ChromaDB + nomic-embed-text + search_knowledge action    | Next     |
| 20 | RemoteSyncService: Railway API publishing                                    | Planned  |
| 21 | Tests + documentation                                                        | Planned  |

---

## Semaphore state machine

```
idle
 ├─→ acquire_typing() → user_typing → [Enter] → transition_to_llm() → llm_running → release() → idle
 └─→ acquire_task()   → task_running                                              → release() → idle

HTTP server: never acquires the semaphore
```

The CLI holds the lock for the **entire user interaction cycle** — from showing `❯` to displaying the agent's reply. The scheduler gets exactly one opportunity to run between turns.

---

## Photo pipeline

```
inbox/photo.jpg
  → ImagePreprocessingService   EXIF correction + resize (640–800px longest side) + SHA-256
  → OllamaVisionClient          qwen2.5vl:7b → {description, summary}
  → _score_significance()       Ollama text call → {"significance_score": 0.0–1.0}
  → PhotosRepository.update()   vision_description, score, is_remote_candidate
  → shutil.move()               photo.jpg → processed/photo.jpg
```

Original never modified. Significance threshold: 0.75. Below threshold: archived only.

---

## Knowledge base pipeline (commit 19)

```
data/knowledge/*.txt|*.md
  → KnowledgeService.index_documents()   chunk (~500 chars) → embed via nomic-embed-text → ChromaDB upsert
  → KnowledgeService.search(query)       embed query → top-5 chunks → injected as tool result
```

ChromaDB persistent at `data/knowledge_db/`. No server required. Embeddings via Ollama `/api/embed`.

---

## Tool dispatch architecture

The Runtime's `_dispatch_tool()` is the single entry point for all LLM tool calls. Each case either:
- Queries the DB directly (locations, photos, weather)
- Instantiates a service and delegates (PhotoService, WeatherService, KnowledgeService)
- Creates a DB record (create_task)
- Returns a stub for not-yet-implemented features (remote publish)

Tool results are returned as strings and appended to the message context as `{"role": "tool", "content": "[action result]: ..."}` before the next LLM invocation.

---

## Environment variables

| Variable | Description |
|---|---|
| `DB_PATH` | SQLite database path |
| `PHOTO_INBOX_DIR` | Inbox directory for new photos |
| `PHOTO_PROCESSED_DIR` | Move originals here after processing |
| `PHOTO_PREVIEW_DIR` | JPEG previews for vision input |
| `OLLAMA_URL` | Ollama base URL |
| `VISION_MAX_DIM` | Max dimension for vision preview |
| `VISION_MIN_DIM` | Min dimension for vision preview |
| `HTTP_HOST` | HTTP server bind address |
| `HTTP_PORT` | HTTP server port |
| `SCHEDULER_TICK_SECONDS` | Scheduler tick interval |
| `KNOWLEDGE_CHROMA_DIR` | ChromaDB storage path |
| `KNOWLEDGE_SOURCE_DIR` | Knowledge document source directory |
| `REMOTE_SYNC_BASE_URL` | Railway expedition website URL |
| `REMOTE_SYNC_API_KEY` | Railway API key |
| `OPENROUTER_API_KEY` | OpenRouter key (optional, for cloud LLM) |
