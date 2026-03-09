from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent.config.loader import Config
from agent.db.database import Database
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

    async def _generate_due_tasks(self, tasks_repo: TasksRepository) -> None:
        """Insert scheduled tasks when due."""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(self._config.agent.timezone)
        now_local = datetime.now(tz=tz)
        now_utc = datetime.now(timezone.utc)

        # fetch_weather — keyed by UTC hour
        current_hour_utc = now_utc.hour
        if current_hour_utc in self._config.weather.schedule_hours and current_hour_utc != self._last_weather_hour:
            self._last_weather_hour = current_hour_utc
            await tasks_repo.insert("fetch_weather", {}, source="scheduler")
            logger.info("Scheduler: queued fetch_weather for UTC hour %s", current_hour_utc)

        # create_reflection — once per day at configured local hour
        today_str = now_local.strftime("%Y-%m-%d")
        if (now_local.hour >= self._config.reflection.hour_local
                and self._last_reflection_date != today_str):
            self._last_reflection_date = today_str
            await tasks_repo.insert("create_reflection", {"date": today_str}, source="scheduler")
            logger.info("Scheduler: queued create_reflection for %s", today_str)
