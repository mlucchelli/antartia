# Manual Test Plan

Tests for each planned commit. Run these in order to verify each commit before moving on.

---

## Commit 7 — DB layer ✓

```bash
# Initialize DB and verify all 6 tables exist
python -c "
import asyncio
from agent.db.database import Database
async def main():
    async with Database('./data/expedition.db') as db:
        print('DB initialized')
asyncio.run(main())
"

sqlite3 data/expedition.db ".tables"
# Expected: agent_messages  locations  photos  sessions  tasks  weather_snapshots

# Insert and retrieve a location record
python -c "
import asyncio
from agent.db.database import Database
from agent.db.locations_repo import LocationsRepository
from datetime import datetime, timezone
async def main():
    async with Database('./data/expedition.db') as db:
        repo = LocationsRepository(db)
        loc = await repo.insert(-62.1, -58.4, datetime.now(timezone.utc))
        print('Inserted:', loc)
        rows = await repo.get_latest(limit=1)
        print('Fetched:', rows)
asyncio.run(main())
"
```

---

## Commit 8 — Models

```bash
# Verify all new Pydantic models instantiate correctly
python -c "
from agent.models.location import LocationRecord
from agent.models.task import TaskRecord
from agent.models.photo import PhotoRecord
from datetime import datetime, timezone
now = datetime.now(timezone.utc)

loc = LocationRecord(latitude=-62.1, longitude=-58.4, recorded_at=now, received_at=now)
task = TaskRecord(type='fetch_weather', payload={}, status='pending', priority=1, created_at=now)
photo = PhotoRecord(file_path='data/photos/inbox/test.jpg', file_name='test.jpg', folder='inbox', discovered_at=now)
print('LocationRecord OK:', loc.latitude)
print('TaskRecord OK:', task.type)
print('PhotoRecord OK:', photo.file_name)
"
```

---

## Commit 9 — HTTP server

```bash
# Terminal 1 — start agent
python -m agent --config configs/expedition_config.json

# Terminal 2 — send a GPS location
curl -s -X POST http://localhost:8080/locations \
  -H "Content-Type: application/json" \
  -d '{"latitude": -62.1, "longitude": -58.4, "recorded_at": "2026-03-07T10:15:00Z"}' \
  && echo "OK"
# Expected: HTTP 200, "OK" printed

# Verify location was saved and task was created
sqlite3 data/expedition.db "SELECT latitude, longitude, recorded_at FROM locations ORDER BY id DESC LIMIT 1;"
sqlite3 data/expedition.db "SELECT type, status FROM tasks WHERE type='process_location' ORDER BY id DESC LIMIT 1;"
# Expected: one location row + one process_location task with status=pending
```

---

## Commit 10 — ExecutionSemaphore + Scheduler

```bash
# Start agent and observe the status bar
python -m agent --config configs/expedition_config.json
# Expected in status bar: "scheduler: next Xs"
# Every 5 seconds you should see a scheduler tick in the scroll area (dim log line)

# Manually inject a pending task and watch the scheduler pick it up within 5s
sqlite3 data/expedition.db \
  "INSERT INTO tasks (type, payload, status, priority, created_at) \
   VALUES ('fetch_weather', '{}', 'pending', 1, datetime('now'));"

# Expected:
# - Input row changes to: ⠹ task: fetch_weather — step 1/...
# - Steps stream to scroll area in real time
# - Input row restores to ❯ when done
sqlite3 data/expedition.db "SELECT type, status, executed_at FROM tasks ORDER BY id DESC LIMIT 1;"
# Expected: status=completed
```

---

## Commit 11 — Recursive runtime chaining

```bash
python -m agent --config configs/expedition_config.json --debug

# Type a question that requires multiple tool calls:
❯ What were today's locations and what is the current weather?

# Expected in scroll area (--debug shows each LLM pass):
#   executing: get_locations_by_date
#   [tool result appended]
#   executing: get_weather
#   [tool result appended]
#   executing: send_message
#   Agent: <summary combining both results>

# Verify chain depth never exceeded 6 (check logs for "max depth" warning)
# Also test a simple question that resolves in one pass:
❯ Hello
# Expected: single LLM pass → send_message directly
```

---

## Commit 12 — TaskRunner + CLI task progress

```bash
python -m agent --config configs/expedition_config.json

# Inject several task types and verify each runs and streams output:
sqlite3 data/expedition.db \
  "INSERT INTO tasks (type, payload, status, priority, created_at) \
   VALUES ('fetch_weather', '{}', 'pending', 1, datetime('now'));"
# Watch: input row disabled, step-by-step lines appear in scroll area, input restores

# Send a GPS point to trigger process_location task:
curl -s -X POST http://localhost:8080/locations \
  -H "Content-Type: application/json" \
  -d '{"latitude": -62.2, "longitude": -58.5, "recorded_at": "2026-03-07T11:00:00Z"}'
# Watch: process_location task executes within 5s via scheduler

# Verify completed tasks in DB
sqlite3 data/expedition.db "SELECT type, status FROM tasks ORDER BY id DESC LIMIT 5;"
```

---

## Commit 13 — ImagePreprocessingService + OllamaClient

```bash
# First: make sure Ollama is running with qwen2.5-vl pulled
ollama list  # should show qwen2.5-vl

# Put any photo in the inbox
cp /path/to/photo.jpg data/photos/inbox/test.jpg

# Test preprocessing standalone
python -c "
from pathlib import Path
from agent.config.loader import Config
from agent.services.photo_service import ImagePreprocessingService
config = Config.load('configs/expedition_config.json')
svc = ImagePreprocessingService(config.image_preprocessing)
result = svc.process(Path('data/photos/inbox/test.jpg'), Path('data/photos/vision_preview'))
print('Original:', result.original_width, 'x', result.original_height)
print('Preview:', result.preview_width, 'x', result.preview_height)
print('Preview path:', result.preview_path)
"
# Expected: preview file exists, longest side between 1280-1600px

ls data/photos/vision_preview/

# Test Ollama vision call
python -c "
import asyncio
from agent.llm.ollama import OllamaClient
async def main():
    client = OllamaClient('http://localhost:11434', 'qwen2.5-vl')
    desc = await client.describe_image(
        'data/photos/vision_preview/test_preview.jpg',
        'Describe this image in detail.'
    )
    print('Description:', desc[:200])
asyncio.run(main())
"
```

---

## Commit 14 — PhotoService full pipeline

```bash
# Requires Ollama running with qwen2.5-vl

# Drop a photo in inbox
cp /path/to/photo.jpg data/photos/inbox/

# Start agent and trigger inbox scan via chat
python -m agent --config configs/expedition_config.json

❯ scan the photo inbox
# Expected:
#   executing: scan_photo_inbox
#   Agent: "Found 1 new file, queued for processing"

# Watch scheduler pick up and run process_photo task (within 5s):
# Input row: ⠹ task: process_photo — step 3/7: running vision...
# Each step streams to scroll area

# Verify results
sqlite3 data/expedition.db \
  "SELECT file_name, vision_status, significance_score, is_remote_candidate FROM photos;"
# Expected: vision_status=completed, score 0.0-1.0, is_remote_candidate = 0 or 1

ls data/photos/processed/     # original should be here
ls data/photos/vision_preview/ # preview JPEG should be here
```

---

## Commit 15 — WeatherService

```bash
python -m agent --config configs/expedition_config.json

❯ what is the current weather at base camp?
# Expected: LLM chains get_weather → Open-Meteo API call → send_message with weather info
# Scroll area shows: executing: get_weather

# Verify snapshot saved to DB
sqlite3 data/expedition.db \
  "SELECT temperature, wind_speed, condition, recorded_at FROM weather_snapshots ORDER BY id DESC LIMIT 1;"
# Expected: one row with real weather data
```

---

## Commit 16 — All 12 actions + expedition_config.json

```bash
python -m agent --config configs/expedition_config.json

# Test each of the 11 tool actions:
❯ show me the latest GPS locations
# executing: get_latest_locations → data or "no locations yet"

❯ what locations were recorded on 2026-03-07?
# executing: get_locations_by_date

❯ show me the processed photos
# executing: get_photos

❯ what is the weather right now?
# executing: get_weather

❯ create a task to fetch the weather
# executing: create_task → confirm in DB:
sqlite3 data/expedition.db "SELECT type, status FROM tasks ORDER BY id DESC LIMIT 1;"

❯ scan the inbox for new photos
# executing: scan_photo_inbox

# Publish actions — will return "failed" or "no remote sync" gracefully until commit 17:
❯ publish today's expedition progress
# executing: publish_daily_progress → graceful error

❯ update the route map
# executing: publish_route_snapshot → graceful error

❯ upload the best photo
# executing: upload_image → graceful error

❯ post an agent message to the website
# executing: publish_agent_message → graceful error

❯ publish the latest weather snapshot
# executing: publish_weather_snapshot → graceful error
```

---

## Commit 17 — RemoteSyncService

```bash
# Option A — use a local mock server to simulate Railway
python -m http.server 9999 &
# Temporarily set expedition_config.json remote_sync.base_url to http://localhost:9999

python -m agent --config configs/expedition_config.json

❯ publish today's expedition progress
# Expected: POST to http://localhost:9999/daily-progress (will get 501 from mock but request fires)

# Option B — if Railway app is deployed
# Set REMOTE_SYNC_API_KEY in .env and correct base_url in config, then:
❯ publish today's expedition progress
# Expected: Agent confirms "published successfully"

❯ update the route map
# Expected: Agent confirms route GeoJSON published

# Verify DB upload flags for photos:
sqlite3 data/expedition.db \
  "SELECT file_name, remote_uploaded, remote_uploaded_at, remote_url FROM photos WHERE is_remote_candidate=1;"
```
