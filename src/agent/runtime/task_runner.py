from __future__ import annotations

import logging
from datetime import datetime, timezone

from agent.config.loader import Config
from agent.db.database import Database
from agent.db.locations_repo import LocationsRepository
from agent.db.tasks_repo import TasksRepository
from agent.runtime.protocols import OutputHandler

logger = logging.getLogger(__name__)


class TaskRunner:
    """
    Executes background tasks claimed by the Scheduler.
    Streams progress messages to the OutputHandler (visible in the scroll area).
    Services not yet built (weather, photo, remote sync) are stubbed.
    """

    def __init__(self, config: Config, db: Database, output: OutputHandler) -> None:
        self._config = config
        self._db = db
        self._output = output

    async def execute(self, task: dict) -> None:
        task_id = task["id"]
        task_type = task["type"]
        payload = task["payload"]
        repo = TasksRepository(self._db)

        self._progress(f"starting task {task_type} (id={task_id})")

        try:
            match task_type:
                case "process_location":
                    await self._process_location(payload)
                case "scan_photo_inbox":
                    await self._scan_photo_inbox(payload)
                case "process_photo":
                    await self._process_photo(payload)
                case "fetch_weather":
                    await self._fetch_weather(payload)
                case "publish_daily_progress":
                    await self._publish_daily_progress(payload)
                case "publish_route_snapshot":
                    await self._publish_route_snapshot(payload)
                case "upload_image":
                    await self._upload_image(payload)
                case "publish_agent_message":
                    await self._publish_agent_message(payload)
                case "publish_weather_snapshot":
                    await self._publish_weather_snapshot(payload)
                case _:
                    raise ValueError(f"unknown task type: {task_type}")

            await repo.complete(task_id)
            self._progress(f"task {task_type} (id={task_id}) completed")

        except Exception as exc:
            logger.exception("Task %s id=%s failed: %s", task_type, task_id, exc)
            await repo.fail(task_id, str(exc))
            self._progress(f"task {task_type} (id={task_id}) failed: {exc}")

    def _progress(self, message: str) -> None:
        self._output.on_task_progress(message)

    # ── Task handlers ─────────────────────────────────────────────────────────

    async def _process_location(self, payload: dict) -> None:
        location_id = payload.get("location_id")
        self._progress(f"process_location: location_id={location_id}")
        repo = LocationsRepository(self._db)
        rows = await repo.get_latest(limit=1)
        if rows:
            loc = rows[0]
            self._progress(
                f"location recorded: lat={loc['latitude']} lon={loc['longitude']} "
                f"at {loc['recorded_at']}"
            )

    async def _scan_photo_inbox(self, payload: dict) -> None:
        from agent.services.photo_service import PhotoService

        svc = PhotoService(self._config, self._db, self._output)
        count = await svc.scan_inbox()
        self._progress(f"scan_photo_inbox: queued {count} new photo(s) for processing")

    async def _process_photo(self, payload: dict) -> None:
        from agent.services.photo_service import PhotoService

        photo_id = payload.get("photo_id")
        if photo_id is None:
            raise ValueError("process_photo task missing photo_id in payload")

        svc = PhotoService(self._config, self._db, self._output)
        await svc.process_photo(int(photo_id))

    async def _fetch_weather(self, payload: dict) -> None:
        from agent.services.weather_service import WeatherService

        lat = payload.get("latitude")
        lon = payload.get("longitude")
        svc = WeatherService(self._config, self._db)
        s = await svc.fetch_and_store(lat, lon)
        self._progress(
            f"weather: {s['temperature']}°C (feels {s['apparent_temperature']}°C) · "
            f"wind {s['wind_speed']} km/h gusts {s['wind_gusts']} km/h · "
            f"snow depth {s['snow_depth']}m · {s['condition']}"
        )

    async def _publish_daily_progress(self, payload: dict) -> None:
        self._progress("publish_daily_progress: not yet implemented")

    async def _publish_route_snapshot(self, payload: dict) -> None:
        self._progress("publish_route_snapshot: not yet implemented")

    async def _upload_image(self, payload: dict) -> None:
        photo_id = payload.get("photo_id", "?")
        self._progress(f"upload_image: photo_id={photo_id} — not yet implemented")

    async def _publish_agent_message(self, payload: dict) -> None:
        self._progress("publish_agent_message: not yet implemented")

    async def _publish_weather_snapshot(self, payload: dict) -> None:
        self._progress("publish_weather_snapshot: not yet implemented")
