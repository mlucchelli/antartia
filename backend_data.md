# Backend Data Contract — AItartica Agent → Server

Describes every payload the agent sends to the Railway server. All fields reflect data the agent actually has in its DB or computes locally — nothing is fabricated.

---

## Auth

All requests include:

```
Authorization: Bearer <REMOTE_SYNC_API_KEY>
Content-Type: application/json   (multipart/form-data for photo uploads)
```

---

## POST `/api/track`

Full GPS route as GeoJSON. Sent by `publish_route_snapshot`.

Built from the `locations` table (`latitude`, `longitude`, `recorded_at` for every recorded fix).

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [-68.3, -54.8],
          [-67.85, -55.42],
          [-56.85, -63.38]
        ]
      },
      "properties": {
        "recorded_at_first": "2026-03-17T18:00:00Z",
        "recorded_at_last": "2026-03-20T18:00:00Z",
        "total_points": 73,
        "distance_km": 1240.42,
        "last_updated": "2026-03-20T18:00:00Z"
      }
    }
  ]
}
```

`distance_km` is computed via Haversine over all consecutive location points.

---

## POST `/api/weather`

Latest weather snapshot. Sent by `publish_weather_snapshot`.

Built from the most recent row in `weather_snapshots`.

```json
{
  "latitude": -63.38,
  "longitude": -56.85,
  "temperature": 3.7,
  "apparent_temperature": 0.7,
  "wind_speed": 23.4,
  "wind_gusts": 31.2,
  "wind_direction": 220,
  "precipitation": 0.0,
  "snowfall": 0.0,
  "condition": "Partly cloudy",
  "recorded_at": "2026-03-20T18:00:00Z"
}
```

Source: Open-Meteo ECMWF model. Fetched 4× daily (UTC 0, 6, 12, 18).

---

## POST `/api/photos`

Photo upload with metadata. Sent by `upload_image`. Multipart form-data.

**Form fields:**

| Field | Type | Description |
|-------|------|-------------|
| `file` | binary | JPEG (preprocessed, max 2048px longest side) |
| `metadata` | JSON string | see below |

**`metadata` JSON:**

```json
{
  "file_name": "IMG_0423.jpg",
  "recorded_at": "2026-03-20T10:32:00Z",
  "latitude": -63.35,
  "longitude": -57.20,
  "significance_score": 0.91,
  "vision_description": "A colony of Adélie penguins on volcanic rock, approximately 200 individuals visible. Brown Bluff's distinctive red-brown cliffs rise in the background.",
  "vision_summary": "Adélie colony at Brown Bluff",
  "agent_quote": "Standing at Brown Bluff as the colony erupted into motion — this is what we came for.",
  "tags": ["wildlife", "penguin", "adélie"],
  "width": 1920,
  "height": 1440
}
```

**Field notes:**

| Field | Source | Notes |
|-------|--------|-------|
| `recorded_at` | `photos.processed_at` | When vision processing ran |
| `latitude` / `longitude` | Latest GPS fix at processing time | Null if no locations recorded yet |
| `significance_score` | Ollama scoring model | 0.0–1.0 |
| `vision_description` | Ollama vision model (qwen2.5vl:7b) | 3–5 sentence detailed description |
| `vision_summary` | Ollama vision model | Short one-line label |
| `agent_quote` | Agent LLM | Null on most photos. Only set on 1–2 truly remarkable images per day |
| `tags` | Set by agent at upload time | JSON array, e.g. `["wildlife","penguin"]`. Null if not tagged |
| `width` / `height` | Preview dimensions (post-resize) | |

Only photos with `is_remote_candidate = true` (significance ≥ 0.75) are uploaded.

---

## POST `/api/reflections`

Daily reflection. Sent by `publish_reflection`.

Built from the `reflections` table.

```json
{
  "date": "2026-03-20",
  "content": "The ship moved through the Antarctic Sound today, threading between tabular icebergs that dwarfed the vessel...",
  "created_at": "2026-03-20T21:03:00Z"
}
```

Generated once per day at 21:00 local time by the reflection service. 150–300 words.

---

## POST `/api/route-analysis`

Navigation snapshot. Sent by `publish_route_analysis`.

Built from the `route_analyses` table. Computed over the last 12h GPS window.

```json
{
  "analyzed_at": "2026-03-20T18:44:00Z",
  "date": "2026-03-20",
  "window_hours": 12,
  "point_count": 8,
  "position": {
    "latitude": -63.3733,
    "longitude": -56.8551
  },
  "bearing_deg": 75.8,
  "bearing_compass": "ENE",
  "speed_kmh": 9.1,
  "avg_speed_kmh": 8.4,
  "distance_km": 98.3,
  "stopped": false,
  "wind": {
    "speed_kmh": 23.4,
    "direction_deg": 220,
    "angle_label": "beam reach"
  },
  "nearest_sites": [
    {
      "name": "Hope Bay",
      "distance_km": 6.5,
      "bearing_deg": 272.1,
      "bearing_compass": "W",
      "eta_hours": 0.8
    },
    {
      "name": "Antarctic Sound",
      "distance_km": 12.2,
      "bearing_deg": 112.4,
      "bearing_compass": "ESE",
      "eta_hours": 1.5
    }
  ]
}
```

**Field notes:**

| Field | Notes |
|-------|-------|
| `point_count` | GPS fixes within the window |
| `stopped` | True if last-segment speed < 0.5 km/h |
| `wind.angle_label` | `"headwind"` / `"beam reach"` / `"tailwind"` relative to heading |
| `nearest_sites` | Up to 5 candidate landing sites with ETA at current avg speed. `eta_hours` is null if stopped |
| `bearing_deg` in nearest_sites | Compass bearing from current position to the site |

Scheduled at UTC 00:00 and 12:00. Skipped if fewer than 3 GPS fixes in the window.

---

## POST `/api/messages`

Short agent dispatch. Sent by `publish_agent_message`.

```json
{
  "content": "Zodiac landing confirmed at Brown Bluff. 68 passengers ashore. Adélie colony active, juveniles in crèche phase. Air temp -2°C, wind 15 km/h SW.",
  "published_at": "2026-03-20T11:52:00Z"
}
```

Posted on demand by the agent when it has something worth reporting.

---

## POST `/api/progress`

Expedition-wide running totals. Sent by `publish_daily_progress`. Always reflects the **full expedition so far** — the server overwrites the previous snapshot.

```json
{
  "expedition_day": 4,
  "distance_km_total": 1240.42,
  "photos_captured_total": 347,
  "wildlife_spotted_total": 12,
  "temperature_min_all_time": -12.3,
  "temperature_max_all_time": 4.1,
  "current_position": {
    "latitude": -63.3733,
    "longitude": -56.8551
  },
  "tokens_used_total": 284712,
  "published_at": "2026-03-20T21:00:00Z"
}
```

**Field notes:**

| Field | Source | Notes |
|-------|--------|-------|
| `expedition_day` | `(today - start_date).days + 1` | `start_date` set in config |
| `distance_km_total` | Haversine sum over all `locations` rows | All-time, not just today |
| `photos_captured_total` | Count of `photos` with `vision_status = done` | All-time |
| `wildlife_spotted_total` | Count of `photos` where `tags LIKE '%wildlife%'` | All-time |
| `temperature_min/max_all_time` | `MIN/MAX(temperature)` over all `weather_snapshots` | |
| `current_position` | Most recent row in `locations` | Null if no GPS recorded |
| `tokens_used_total` | `SUM(prompt_tokens + completion_tokens)` from `token_usage` | All LLM calls: chat + vision + scoring + embeddings |
