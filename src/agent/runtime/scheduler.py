from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent.config.loader import Config
from agent.db.database import Database
from agent.db.reflections_repo import ReflectionsRepository
from agent.db.tasks_repo import TasksRepository
from agent.runtime.semaphore import ExecutionSemaphore

if TYPE_CHECKING:
    from agent.runtime.task_runner import TaskRunner

logger = logging.getLogger(__name__)


class Scheduler:
    """
    5-second tick loop. Generates due weather tasks and picks up any
    pending task for execution via TaskRunner (injected after construction).
    Skips the tick entirely when the semaphore is held.
    """

    def __init__(self, config: Config, db: Database, semaphore: ExecutionSemaphore) -> None:
        self._config = config
        self._db = db
        self._semaphore = semaphore
        self._task_runner: object | None = None  # set after construction to avoid circular import
        self._last_weather_hour: int | None = None
        self._last_reflection_date: str | None = None
        self._last_route_analysis_hour: int | None = None

    def set_task_runner(self, runner: "TaskRunner") -> None:
        self._task_runner = runner

    async def run(self) -> None:
        interval = self._config.scheduler.tick_interval_seconds
        logger.info("Scheduler started — tick every %ss", interval)
        while True:
            await asyncio.sleep(interval)
            await self._tick()

    async def _tick(self) -> None:
        if not self._semaphore.is_available_for_tasks:
            logger.info("Scheduler tick — skipped (semaphore: %s)", self._semaphore.state.value)
            return

        logger.info("Scheduler tick — semaphore: %s", self._semaphore.state.value)
        tasks_repo = TasksRepository(self._db)
        await self._generate_due_tasks(tasks_repo)

        # retry any queued sync items
        from agent.services.remote_sync_service import RemoteSyncService
        await RemoteSyncService(self._config, db=self._db).retry_pending()

        task = await tasks_repo.claim_next()
        if task is None:
            logger.info("Scheduler tick — no pending tasks")
            return

        logger.info("Scheduler: claiming task id=%s type=%s", task["id"], task["type"])

        if self._task_runner is None:
            logger.warning("Scheduler: no task runner set, releasing task %s", task["id"])
            await tasks_repo.fail(task["id"], "no task runner configured")
            return

        await self._semaphore.acquire_task()
        try:
            await self._task_runner.execute(task)  # type: ignore[union-attr]
        except Exception as exc:
            logger.exception("Task %s failed: %s", task["id"], exc)
            await tasks_repo.fail(task["id"], str(exc))
        finally:
            self._semaphore.release()

    async def _already_queued(self, task_type: str, since_utc: str) -> bool:
        """Return True if a task of this type was already created at or after since_utc."""
        async with self._db.conn.execute(
            "SELECT 1 FROM tasks WHERE type=? AND created_at >= ? LIMIT 1",
            (task_type, since_utc),
        ) as cur:
            return await cur.fetchone() is not None

    async def _generate_due_tasks(self, tasks_repo: TasksRepository) -> None:
        """Insert scheduled tasks when due, skipping if already queued this window."""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(self._config.agent.timezone)
        now_local = datetime.now(tz=tz)
        current_hour_local = now_local.hour
        hour_start = now_local.replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
        today_str = now_local.strftime("%Y-%m-%d")
        day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()

        # fetch_weather
        if current_hour_local in self._config.weather.schedule_hours and current_hour_local != self._last_weather_hour:
            self._last_weather_hour = current_hour_local
            if not await self._already_queued("fetch_weather", hour_start):
                await tasks_repo.insert("fetch_weather", {}, source="scheduler")
                logger.info("Scheduler: queued fetch_weather for local hour %s", current_hour_local)
            else:
                logger.info("Scheduler: fetch_weather already queued for hour %s — skipping", current_hour_local)

        # create_reflection — once per day
        if current_hour_local >= self._config.reflection.hour_local and self._last_reflection_date != today_str:
            self._last_reflection_date = today_str
            existing = await ReflectionsRepository(self._db).get_by_date(today_str)
            if not existing and not await self._already_queued("create_reflection", day_start):
                await tasks_repo.insert("create_reflection", {"date": today_str}, source="scheduler")
                logger.info("Scheduler: queued create_reflection for %s", today_str)
            else:
                logger.info("Scheduler: create_reflection for %s already handled — skipping", today_str)

        # analyze_route
        cfg_ra = self._config.route_analysis
        if current_hour_local in cfg_ra.schedule_hours and current_hour_local != self._last_route_analysis_hour:
            self._last_route_analysis_hour = current_hour_local
            if not await self._already_queued("analyze_route", hour_start):
                await tasks_repo.insert("analyze_route", {"hours": cfg_ra.window_hours}, source="scheduler")
                logger.info("Scheduler: queued analyze_route (window=%sh) at local hour %s",
                            cfg_ra.window_hours, current_hour_local)
            else:
                logger.info("Scheduler: analyze_route already queued for hour %s — skipping", current_hour_local)
