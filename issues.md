# Known Issues — fix when touching the relevant area

## CRITICAL

### C1 — on_llm_response mutates caller's dict
**File**: `src/agent/cli/app.py:90`
**Problem**: `response.pop("_usage", {})` mutates the dict passed by Runtime. If response is referenced elsewhere, second call won't have `_usage`.
**Fix**: Use `.get()` instead of `.pop()`, strip `_usage` in the caller (OllamaClient) before returning.

### C2 — Semaphore: no timeout on held lock
**File**: `src/agent/runtime/semaphore.py`
**Problem**: If LLM call hangs indefinitely, the asyncio lock is held forever. Scheduler and any new input are blocked permanently.
**Fix**: Add timeout to `acquire_typing()` or a watchdog task that releases after N seconds.

### C3 — FileStateStore: no concurrent write protection
**File**: `src/agent/state/file_store.py`
**Problem**: Two concurrent `save()` calls for the same session will write simultaneously and corrupt the JSON file.
**Fix**: Add asyncio.Lock per session_id, or use atomic write (write to temp file, rename).

### C4 — HTTP server: manual HTTP parsing is brittle
**File**: `src/agent/http/server.py`
**Problem**: Headers parsed via string splits. Breaks with malformed requests, multiple spaces, missing Content-Length, or slow clients sending partial headers (no read timeout).
**Fix**: Add read timeout via `asyncio.wait_for()`. Consider `aiohttp` if dependencies allow.

---

## IMPORTANT

### I1 — WeatherRepository.insert() has 12 parameters
**File**: `src/agent/db/weather_repo.py:13`
**Problem**: 12 positional args — easy to pass in wrong order, hard to call.
**Fix when touching weather_repo**: Create `WeatherSnapshot` dataclass, pass single object.

### I2 — condition = "code None" when weather_code is None
**File**: `src/agent/services/weather_service.py:70`
**Problem**: `_WMO_CONDITIONS.get(weather_code, f"code {weather_code}")` — if `weather_code` is None, stores "code None" in DB.
**Fix**: `condition = _WMO_CONDITIONS.get(weather_code) if weather_code is not None else None`

### I3 — Task payloads are untyped dicts
**File**: `src/agent/runtime/task_runner.py`
**Problem**: Each handler does `payload.get("field")` with no validation. Wrong payload silently fails.
**Fix when touching task_runner**: Create Pydantic models per task type (`ProcessLocationPayload`, `ProcessPhotoPayload`, etc.).

### I4 — Scheduler._task_runner set via post-hoc setter
**File**: `src/agent/runtime/scheduler.py:30,33`
**Problem**: `set_task_runner()` must be called after construction or execution silently fails. Fragile wiring.
**Fix**: Resolve circular import (move TaskRunner import inside method or restructure modules) and require runner in `__init__`.

### I5 — Scheduler schedule_hours assumed UTC but undocumented
**File**: `src/agent/runtime/scheduler.py:70`
**Problem**: `datetime.now(timezone.utc).hour` compared to `schedule_hours` from config. If user sets hours in local time, tasks run at wrong times.
**Fix**: Document that `schedule_hours` is UTC, or add timezone field to WeatherConfig.

### I6 — WeatherRepository.insert() returns reconstructed dict, not DB row
**File**: `src/agent/db/weather_repo.py:44`
**Problem**: Returns manually built dict. If schema adds computed/default columns, return value is stale.
**Fix**: Do `SELECT * FROM weather_snapshots WHERE id = ?` after insert and return that row.

### I7 — shutil imported inside function
**File**: `src/agent/services/image_preprocessing.py:55`
**Problem**: `import shutil` inside `process()` method, only on the copy-optimization path.
**Fix**: Move to top of file.

### I8 — Runtime._dispatch_tool catches all exceptions, returns error string
**File**: `src/agent/runtime/runtime.py`
**Problem**: Tool failures look like normal results to the LLM. No visual distinction in CLI.
**Fix when touching runtime**: Add `on_tool_error(tool_name, error)` to OutputHandler, or at minimum print in a distinct style in CLI.

### I9 — Action parser silently drops unknown action types
**File**: `src/agent/runtime/parser.py:47`
**Problem**: LLM hallucinated action name → logged warning → dropped silently. User gets incomplete response.
**Fix**: Surface unknown actions in CLI via `on_action_start` with an "unknown" style, or fail the chain.

### I10 — _run() and _resume() in __main__.py lack type hints
**File**: `src/agent/__main__.py:73,103`
**Problem**: Parameters untyped.
**Fix**: Add full type annotations.

---

## MINOR

### M1 — Spinner frame delay is a magic number
**File**: `src/agent/cli/app.py:210`
**Fix**: `SPINNER_FRAME_DELAY = 0.08` constant at module level.

### M2 — OllamaClient timeout hardcoded at 120s
**File**: `src/agent/llm/ollama.py:54`
**Fix**: Add `llm_timeout_seconds` to AgentConfig.

### M3 — PromptBuilder uses naive string .replace()
**File**: `src/agent/llm/prompt_builder.py`
**Problem**: If a placeholder value contains another placeholder pattern, it gets double-substituted.
**Fix**: Use `string.Template` or ensure values are sanitized before substitution.

### M4 — LocationsRepository.insert() doesn't validate coordinate ranges
**File**: `src/agent/db/locations_repo.py:12`
**Fix when touching**: Validate lat in [-90, 90], lon in [-180, 180].

### M5 — HTTP handler returns non-standard response body
**File**: `src/agent/http/server.py:82`
**Problem**: Returns `{"status": "ok", "location_id": N}` — `status: "ok"` is redundant (HTTP 200 conveys that).
**Fix**: Return just `{"location_id": N}` or the full location object.
