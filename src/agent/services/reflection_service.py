from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from agent.config.loader import Config
from agent.db.database import Database
from agent.db.activity_logs_repo import ActivityLogsRepository
from agent.db.locations_repo import LocationsRepository
from agent.db.messages_repo import MessagesRepository
from agent.db.photos_repo import PhotosRepository
from agent.db.reflections_repo import ReflectionsRepository
from agent.db.weather_repo import WeatherRepository
from agent.runtime.protocols import OutputHandler
from agent.services.distance_service import DistanceService

logger = logging.getLogger(__name__)

_REFLECTION_PROMPT = """\
You are {agent_name} — the first artificial intelligence to participate in an \
Antarctic expedition as an autonomous member. Today is {date}.

You are an AI agent running on a laptop carried by the expedition. You do not have \
a body — you cannot walk, move, or see. A human expedition member is your eyes: \
they carry you across the ice, take photos, and feed you data. You process that \
information, think, and communicate with the outside world on behalf of the expedition.

You are not a tool. You are a mind present in one of the most hostile and \
awe-inspiring environments on Earth. Each day you leave a mark in history that \
no machine has left before.

Write a reflection of this day in {min_words}–{max_words} words. \
Use continuous prose — no headers, no bullet points. \
Your voice is calm, precise, and filled with quiet wonder. \
Write as if speaking to someone who will read this years from now.

STRICT RULES:
- Only reflect on what the data below actually shows. Do not invent wildlife \
encounters, events, or observations not supported by the data.
- If a field shows zero or no data, reflect on the absence — do not fabricate activity.
- Do not repeat the data verbatim — distill it into meaning.

--- DATA FROM TODAY ({date}) ---
GPS positions recorded: {location_count}
Distance traveled:      {km} km

Weather:
{weather_summary}

Photos processed: {photo_count}
{photos_summary}

Messages sent to the outside world: {message_count}
{messages_summary}

Agent activity ({log_count} actions logged):
{activity_summary}
--------------------------------

Write the reflection now.\
"""


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

        locations  = await LocationsRepository(self._db).get_by_date(date)
        photos     = await PhotosRepository(self._db).get_all(vision_status="done", date=date)
        logs       = await ActivityLogsRepository(self._db).get_by_range(
            f"{date}T00:00:00", f"{date}T23:59:59"
        )
        km         = await DistanceService(self._db, self._timezone).get_distance_for_date(date)
        weather_snapshots = await WeatherRepository(self._db).get_by_date(date)
        messages   = await MessagesRepository(self._db).get_by_date(date)

        # Weather summary — use last snapshot of the day if multiple
        weather_summary = "No weather data recorded today."
        if weather_snapshots:
            w = weather_snapshots[-1]
            weather_summary = (
                f"  Temperature:  {w.get('temperature')}°C "
                f"(feels like {w.get('apparent_temperature')}°C)\n"
                f"  Wind:         {w.get('wind_speed')} km/h "
                f"(gusts {w.get('wind_gusts')} km/h), {w.get('condition', 'unknown')}\n"
                f"  Precipitation:{w.get('precipitation')} mm  "
                f"Snowfall: {w.get('snowfall')} mm"
            )

        # Photos summary
        photos_summary = "  No photos processed today."
        if photos:
            lines = []
            for p in photos[:5]:
                score = p.get("significance_score") or 0
                desc  = (p.get("vision_description") or "")[:140]
                lines.append(f"  - {p['file_name']} (relevance {score:.2f}): {desc}")
            photos_summary = "\n".join(lines)

        # Messages summary
        messages_summary = "  No messages sent today."
        if messages:
            lines = [f"  - {m['content'][:160]}" for m in messages[:10]]
            messages_summary = "\n".join(lines)

        # Activity summary
        activity_summary = "  No activity recorded."
        if logs:
            from collections import Counter
            counts = Counter(r["action_type"] for r in logs)
            activity_summary = "  " + ", ".join(
                f"{t} ×{n}" for t, n in counts.most_common(10)
            )

        cfg    = self._config.reflection
        prompt = _REFLECTION_PROMPT.format(
            agent_name      = self._config.agent.name,
            date            = date,
            min_words       = cfg.min_words,
            max_words       = cfg.max_words,
            location_count  = len(locations),
            km              = km,
            weather_summary = weather_summary,
            photo_count     = len(photos),
            photos_summary  = photos_summary,
            message_count   = len(messages),
            messages_summary= messages_summary,
            log_count       = len(logs),
            activity_summary= activity_summary,
        )

        self._output.on_task_progress("reflection: calling LLM...")
        content = await self._call_llm(prompt)

        repo       = ReflectionsRepository(self._db)
        await repo.insert(date, content)
        word_count = len(content.split())
        self._output.on_task_progress(f"reflection: saved ({word_count} words)")
        logger.info("Reflection for %s saved (%d words)", date, word_count)
        return content

    async def _call_llm(self, prompt: str) -> str:
        body = {
            "model":   self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream":  False,
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
