from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from agent.config.loader import Config
from agent.db.database import Database
from agent.db.activity_logs_repo import ActivityLogsRepository
from agent.db.locations_repo import LocationsRepository
from agent.db.photos_repo import PhotosRepository
from agent.db.reflections_repo import ReflectionsRepository
from agent.db.weather_repo import WeatherRepository
from agent.runtime.protocols import OutputHandler
from agent.services.distance_service import DistanceService

logger = logging.getLogger(__name__)

_REFLECTION_PROMPT = """\
You are {agent_name} — the AI mind of an Antarctic expedition. Today is {date}.

Reflect on the day's events in {min_words}–{max_words} words, in your voice: \
calm, precise, and filled with quiet wonder. Write continuous prose — no headers, \
no bullet points. Focus on what mattered most today.

DATA FROM TODAY
---------------
GPS track: {location_count} position(s) recorded
Distance traveled: {km} km

Weather: {weather_summary}

Photos processed: {photo_count}
{photos_summary}

Activity ({log_count} tool calls):
{activity_summary}
---------------

Write the reflection now."""


class ReflectionService:
    def __init__(self, config: Config, db: Database, output: OutputHandler) -> None:
        self._config = config
        self._db = db
        self._output = output
        self._ollama_url = config.photo_pipeline.ollama_url
        self._model = config.agent.model
        self._timezone = config.agent.timezone

    def _today(self, date_str: str | None = None) -> str:
        if date_str:
            return date_str
        return datetime.now(tz=ZoneInfo(self._timezone)).strftime("%Y-%m-%d")

    async def create_daily_reflection(self, date_str: str | None = None) -> str:
        date = self._today(date_str)
        self._output.on_task_progress(f"reflection: gathering data for {date}")

        # Gather data
        locations = await LocationsRepository(self._db).get_by_date(date)
        latest_weather = await WeatherRepository(self._db).get_latest()
        photos_today = await PhotosRepository(self._db).get_all(vision_status="done", date=date)
        logs = await ActivityLogsRepository(self._db).get_by_range(
            f"{date}T00:00:00", f"{date}T23:59:59"
        )
        km = await DistanceService(self._db, self._timezone).get_distance_for_date(date)

        # Format summaries
        weather_summary = "no data"
        if latest_weather:
            w = latest_weather
            weather_summary = (
                f"{w.get('temperature')}°C (feels {w.get('apparent_temperature')}°C), "
                f"wind {w.get('wind_speed')} km/h, {w.get('condition', 'unknown')}"
            )

        photos_summary = "none"
        if photos_today:
            lines = []
            for p in photos_today[:5]:
                score = p.get("significance_score") or 0
                desc = (p.get("vision_description") or "")[:120]
                lines.append(f"- {p['file_name']} (score {score:.2f}): {desc}")
            photos_summary = "\n".join(lines)

        activity_summary = "none"
        if logs:
            types = [r["action_type"] for r in logs]
            from collections import Counter
            counts = Counter(types)
            activity_summary = ", ".join(f"{t}×{n}" for t, n in counts.most_common(8))

        cfg = self._config.reflection
        prompt = _REFLECTION_PROMPT.format(
            agent_name=self._config.agent.name,
            date=date,
            min_words=cfg.min_words,
            max_words=cfg.max_words,
            location_count=len(locations),
            km=km,
            weather_summary=weather_summary,
            photo_count=len(photos_today),
            photos_summary=photos_summary,
            log_count=len(logs),
            activity_summary=activity_summary,
        )

        self._output.on_task_progress("reflection: calling LLM...")
        content = await self._call_llm(prompt)

        repo = ReflectionsRepository(self._db)
        await repo.insert(date, content)
        word_count = len(content.split())
        self._output.on_task_progress(f"reflection: saved ({word_count} words)")
        logger.info("Reflection for %s saved (%d words)", date, word_count)
        return content

    async def _call_llm(self, prompt: str) -> str:
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.8},
            "keep_alive": -1,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._ollama_url}/api/chat",
                json=body,
                timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
            )
            resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
