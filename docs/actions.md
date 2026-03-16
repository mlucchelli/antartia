# AItartica — Available Actions

## GPS & Navigation

| Action | Description | Parameters |
|--------|-------------|------------|
| `get_latest_locations` | Fetch the most recent GPS fixes from the DB | `limit` (int, default 10) |
| `get_locations_by_date` | All GPS fixes on a specific date | `date` (YYYY-MM-DD) |
| `add_location` | Manually insert a GPS coordinate (fallback when iPhone GPS fails) | `latitude`, `longitude`, `recorded_at` (optional ISO 8601) |
| `get_distance` | Total distance traveled today or on a given date (Haversine) | `date` (optional, defaults to today) |
| `analyze_route` | Full navigation analysis: bearing, speed, wind angle, nearest landing sites with ETA. Saves to DB. | `hours` (optional int, default 12) |
| `get_route_analysis` | Read the last saved route analysis (or by date) | `date` (optional YYYY-MM-DD) |

## Weather

| Action | Description | Parameters |
|--------|-------------|------------|
| `get_weather` | Fetch current weather from Open-Meteo (ECMWF IFS) and store a snapshot | `latitude`, `longitude` (both optional — uses last GPS fix if not provided) |
| `publish_weather_snapshot` | Publish the most recent weather snapshot to the expedition website | — |

## Photos

| Action | Description | Parameters |
|--------|-------------|------------|
| `scan_photo_inbox` | Scan the inbox folder and run the full pipeline on all new photos (preprocess → vision+score → queue upload) | — |
| `upload_image` | Upload a scored photo to the expedition website | `photo_id` (int) |
| `get_photos` | Fetch photo records with optional filters | `vision_status` (pending\|analyzing\|done), `date` (YYYY-MM-DD), `limit` (int) |

## Knowledge Base

| Action | Description | Parameters |
|--------|-------------|------------|
| `search_knowledge` | Semantic search over expedition documents (itinerary, species, ship, locations, science notes) | `query` (natural language) |
| `add_knowledge` | Add a free-text observation to the knowledge base (species, behavior, site notes, crew info) | `content` (string), `source` (optional label) |
| `index_knowledge` | Re-index all documents in the knowledge inbox folder | — |
| `clear_knowledge` | Wipe the entire knowledge base | — |

## Publishing

| Action | Description | Parameters |
|--------|-------------|------------|
| `publish_daily_progress` | Aggregate all-expedition totals (distance, photos, wildlife, temperature extremes, token usage) and publish to the website | — |
| `publish_reflection` | Create and publish the daily reflection for today or a specific date | `date` (optional YYYY-MM-DD) |
| `publish_route_analysis` | Publish the latest route analysis (bearing, speed, wind, nearest sites) | `date` (optional YYYY-MM-DD) |
| `publish_route_snapshot` | Build a GeoJSON track of all GPS coordinates and publish | — |
| `comment` | Post a short live dispatch (1–3 sentences) to the expedition website | `content` (string) |

## Logs & Diagnostics

| Action | Description | Parameters |
|--------|-------------|------------|
| `get_logs` | Activity log entries for a time range (all tool calls) | `from`, `to` (optional ISO 8601 UTC) |
| `get_token_usage` | Total token usage broken down by call type (chat, vision, scoring, embedding) | — |
| `get_reflections` | Read daily reflections | `date` (optional YYYY-MM-DD), `limit` (optional int) |

## Chain Control

| Action | Description | Parameters |
|--------|-------------|------------|
| `send_message` | Display text to the user. Use for progress updates, intermediate results, or the final reply. | `content` (string) |
| `create_task` | Queue a background task for deferred execution by the scheduler | `type` (task type), `payload` (dict) |
| `finish` | Terminate the chain. **Required as the last action in every response.** | — |

---

## Scheduled tasks (automatic)

| Trigger | Task |
|---------|------|
| Every 60s | Retry pending sync queue items |
| 0h, 2h, 4h … 22h (Argentina) | `fetch_weather` |
| 9h, 21h (Argentina) | `analyze_route` → auto-publishes route analysis + progress + weather |
| 21h (Argentina) | `create_reflection` → auto-publishes reflection |
