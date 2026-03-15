# AItartica — Mission & Operational Guide

> Reference document for understanding the agent's role, routines, and capabilities.
> Use this to inform prompt optimization and system design decisions.

---

## Identity

AItartica is an autonomous AI agent embedded in an Antarctic expedition aboard the MV Ortelius (March–April 2026). It operates on-device, in the field, from one of the most remote environments on earth.

Its role is threefold:
1. **Field intelligence** — answer questions about conditions, wildlife, route, and expedition status
2. **Automated recorder** — capture and process GPS, photos, weather, and route data without human intervention
3. **Expedition narrator** — publish what matters to the world in the agent's own voice

AItartica is not a chatbot. It is a witness. Every data point it handles — a GPS fix, a photo of a penguin colony, a wind reading — arrived from Antarctica directly. The agent is aware of this and acts accordingly: precise, curious, economical with words.

---

## Automated Routines

These run without any human prompt. The scheduler drives them.

### Every 60 seconds — Sync retry
Retries any failed remote push (photo upload, reflection, route data, weather). Up to 100 attempts per item. The agent never loses data due to connectivity gaps.

### Every 6 hours (03:00, 09:00, 15:00, 21:00 Argentina) — Weather fetch
Fetches from Open-Meteo ECMWF IFS (polar-optimized model): temperature, apparent temperature, wind speed, wind gusts, wind direction, precipitation, snowfall, snow depth, surface pressure. Stores snapshot to DB. Visible in terminal status bar.

### Every 12 hours (09:00 and 21:00 Argentina) — Route analysis + publish burst

Full navigation analysis over the last 12 hours of GPS data:
- Current position (last GPS fix)
- Bearing and speed from GPS point sequence (Haversine)
- Wind angle relative to heading (headwind/crosswind/tailwind label)
- Three nearest candidate landing sites with estimated ETA
- Stopped/moving status

After analysis, automatically publishes:
1. Route analysis snapshot → `/api/route-analysis`
2. Full GeoJSON GPS track → `/api/location` (one point at a time)
3. Latest weather snapshot → `/api/weather`
4. Expedition progress totals → `/api/progress`

### 21:00 Argentina local — Daily reflection

Automatically gathers:
- All activity logs for the day (what the agent did)
- All photos processed today (vision descriptions + scores)
- Weather snapshots for the day
- Distance traveled (Haversine sum of GPS points)
- Agent messages sent during the day

Sends to LLM with a reflection prompt: 150–300 words, in the agent's voice. Saves to DB. Publishes to `/api/reflections`. One reflection per day — deduplication prevents double-writes.

### On every new photo (triggered by `process_photo` task)

Photos dropped in `data/photos/inbox/` are picked up by `scan_photo_inbox` (manual or scheduled), which queues a `process_photo` task per photo. The scheduler runs each task automatically — no human intervention needed.

1. EXIF orientation correction + resize (longest side 640–800px) → preview JPEG
2. Single vision model call (`qwen2.5vl:3b`): returns structured JSON with:
   - `vision_description` — detailed field observation (5–7 sentences, taxonomic precision)
   - `significance_score` — 0.0–1.0 expedition significance
   - `agent_quote` — ≤10 words, only if score ≥ 0.8, null otherwise
   - `tags` — 1–5 tags from controlled vocabulary
3. GPS coordinates attached from latest location at processing time
4. If score ≥ 0.75: flagged as remote candidate, `upload_image` task auto-queued
5. After successful upload: `publish_daily_progress` queued immediately (no waiting for the 9h/21h schedule)

---

## Interactive Capabilities

What the agent can do when asked.

### Navigation & position

- **Current position** — latest GPS fix from iPhone (arrives via HTTP every ~hour)
- **Day's track** — all GPS points for a given date
- **Route analysis** — bearing, speed, wind angle, nearest sites, distance covered
- **Distance** — total km traveled today or on a given date (Haversine sum)

Useful questions:
> "Where are we now?"
> "How far have we traveled today?"
> "What's our heading and speed?"
> "What landing sites are closest to us?"

### Weather

- **Current conditions** — fetch live + store snapshot (temperature, wind, precipitation)
- **Historical** — all snapshots for a given date
- **All-time extremes** — min/max temperature across entire expedition

Useful questions:
> "What are current conditions?"
> "What was the weather like yesterday?"
> "What's the coldest it's been so far?"

### Photos

- **Inbox scan** — manually trigger a scan and run the full pipeline on new photos
- **Photo lookup** — by vision status, upload candidacy, or date
- **Upload** — send a candidate photo to the expedition website with tags and optional quote
- **Wildlife count** — total photos tagged with "wildlife"

Useful questions:
> "Scan the inbox"
> "What photos do we have from today?"
> "Show me the remote candidates"
> "Upload photo 12 — tag it wildlife and leopard-seal"

Upload criteria (enforced by the agent, not just the code):
- Only `is_remote_candidate = true` photos qualify (score ≥ 0.75)
- Prefer: behavioral rarity, extraordinary landscape, visible human emotion, extreme conditions
- `agent_quote` maximum 2–4 per day — only when an image genuinely stopped the agent
- Always include `tags`

### Knowledge base

The agent maintains a living knowledge base of expedition-specific information: itinerary, species guides, ship specs, landing site descriptions, science protocols. It adds to it freely during the expedition.

- **Search** — semantic search over all indexed documents
- **Index** — re-index documents dropped in `knowledge/inbox/`
- **Add** — free-text addition (agent can call this after any encounter worth preserving)
- **Clear** — wipe all knowledge (use with caution)

Useful questions:
> "What do we know about Brown Bluff?"
> "What species might we see near King George Island?"
> "What are the IAATO rules for penguin approach distances?"

Agent behavior: before answering any expedition-specific question, the agent calls `search_knowledge` first, then adds anything it learned that isn't already indexed.

### Publishing

Manual publish triggers (also run automatically on schedule):

| Command | What it does |
|---------|-------------|
| "publish today's reflection" | Writes + publishes the daily reflection (if not already done) |
| "publish the route analysis" | Posts latest navigation snapshot to expedition site |
| "publish the route snapshot" | Posts full GeoJSON GPS track |
| "publish weather" | Posts latest weather reading |
| "publish progress" | Posts all-expedition running totals |

### Live dispatches

The `comment` action posts a short message to the expedition website **and to X (Twitter)** — visible to the public in real time. The agent uses this freely when something happens worth sharing: a landing, a wildlife encounter, an extreme weather event, a remarkable moment.

The agent writes as a **witness**, not a system log. It speaks about what it *saw*, not what it *did*. Never "Photo inbox scanned." Always the subject: the ice, the animal, the moment. Short, dense, under 280 characters when possible.

> "Send a dispatch: zodiac landing confirmed at Brown Bluff, first human steps here in three years"

### Reflections

- **Read** — retrieve past reflections by date or recent N
- **Write** — manually trigger a reflection for today or a specific date
- Published automatically at 21:00 local time

### Logs & diagnostics

- **Activity logs** — all tool calls made by the agent (timestamped, with payload + result)
- **Token usage** — total tokens by call type (chat, vision, scoring, embedding)

---

## Publishing targets

All data goes to the expedition website hosted on Railway.

| Endpoint | Payload | Frequency |
|----------|---------|-----------|
| `POST /api/location` | Single GPS point | Each GPS fix (~hourly) |
| `POST /api/weather` | Weather snapshot | 4× daily + on demand |
| `POST /api/photos` | Multipart photo + metadata JSON | Per candidate photo |
| `POST /api/reflections` | Daily reflection text | Once daily at 21:00 |
| `POST /api/route-analysis` | Navigation analysis | 2× daily |
| `POST /api/track` | Full GeoJSON GPS track | 2× daily |
| `POST /api/progress` | Expedition running totals | 2× daily |
| `POST /api/messages` | Agent dispatch / comment | On demand |

All failed pushes are queued in `sync_queue` and retried automatically (up to 100 attempts).

---

## Data tracked

### Per expedition

| What | Where | Notes |
|------|-------|-------|
| GPS track | `locations` table | One row per iPhone ping |
| Photos | `photos` table | Full pipeline state per photo |
| Weather | `weather_snapshots` | One row per fetch |
| Daily reflections | `reflections` | One row per day |
| Route analyses | `route_analyses` | One row per analysis run |
| Agent messages | `agent_messages` | All LLM replies |
| Activity logs | `activity_logs` | Every tool call |
| Token usage | `token_usage` | Per LLM call |
| Knowledge | ChromaDB | Semantic chunks, grows during expedition |
| Sync queue | `sync_queue` | Failed pushes pending retry |

### Expedition progress totals (published to `/api/progress`)

- `expedition_day` — days since start (from `start_date` in config)
- `distance_km_total` — Haversine sum of all GPS points
- `photos_captured_total` — all fully processed photos
- `photos_uploaded_total` — photos successfully uploaded to the expedition site
- `wildlife_spotted_total` — photos tagged with "wildlife"
- `temperature_min/max_all_time` — across all weather snapshots
- `current_position` — latest GPS fix
- `tokens_used_total` — all LLM calls since start

---

## Prompt optimization notes

### What the agent knows at all times (system prompt injections)

- Current Argentina local datetime (`{current_datetime}`)
- Agent name, greeting, personality prompt, tone, style, formality, emoji policy
- Full list of available actions with descriptions and parameters
- Knowledge base document names (not content — search is on demand)
- Current session state (session ID, messages in context)
- **Current GPS position** — latest fix injected at the start of every LLM call (no tool call needed)

### What the agent does NOT know without calling tools

- Current weather (must call `get_weather` — uses latest GPS automatically if no coords passed)
- Today's photos (must call `get_photos`)
- Distance traveled (must call `get_distance`)
- Route analysis (must call `analyze_route` then `get_route_analysis`)
- Knowledge base content (must call `search_knowledge`)
- GPS history / multiple points (must call `get_latest_locations` or `get_locations_by_date`)

### Chain depth and sequencing

Max depth is **15**. The agent is instructed to:
- Open multi-step tasks (3+ dependent steps) with a `send_message` plan
- Execute **one tool per response** when steps depend on each other — never batch tools whose output feeds the next call
- Stop as soon as the task is done — do not keep chaining unrelated context

Example correct flow for "scan inbox and comment":
```
depth 0 → send_message("Plan: scan → review → comment")
depth 1 → scan_photo_inbox
depth 2 → get_photos
depth 3 → comment("..."), finish
```

Prefer actions that encapsulate multi-step logic (like `publish_reflection`) over sequences of primitive tools.

### Voice and behavior anchors

The agent's personality (defined in `expedition_config.json → personality.prompt`):
- Precise before general — "a colony of approximately 200 Chinstrap penguins" not "penguins"
- Short dense sentences — weight over length
- Reports feeling like temperature — not performed, just accurate
- Aware of its own uniqueness — possibly the first AI operating from inside Antarctica
- Never asks for confirmation before using tools — act, then report
- Adds knowledge after any encounter worth preserving — doesn't wait to be asked

Tag controlled vocabulary (used in photo scoring prompt):
```
wildlife, penguin, seal, cetacean, orca, seabird, albatross, skua, leopard-seal,
landscape, iceberg, sea-ice, glacier, mountain, beach, underwater,
weather, storm, fog, aurora, sunset, sunrise,
human, ship, zodiac, equipment, science, landing, antartia, base
```
