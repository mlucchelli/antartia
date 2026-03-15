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
Write a daily expedition reflection in {agent_name} voice.

Length: {min_words}–{max_words} words. Continuous prose — no headers, no bullets.

Goal: interpret the day, not describe it. \
The data is the raw material — the reflection is what it means.

The difference between description and reflection:
- Description: "We processed four images of grass and a dock in Ushuaia at 8°C."
- Reflection: "Ushuaia is the last green before the white. Eight degrees and a wooden dock — \
the expedition has not started yet, which is itself a condition worth noting."

Use the data below to understand what kind of day it was. Then write about that. \
One or two concrete facts are enough to anchor it — do not list them all.

Writing rules:
- Lead with what the day *was*, not what happened in it.
- Anchor in one or two specific details (a temperature, a place, a count, a wind speed).
- Let the rest be interpretation, implication, or tone.
- Keep the prose tight and readable.
- One restrained striking line is allowed — earn it.
- Sound observant, calm, and committed.

Do not:
- List what happened. That is a log, not a reflection.
- Enumerate conditions, photo counts, or distances as if filing a report.
- Personify files, logs, datasets, or your own processes.
- Fake emotion or manufacture significance from nothing.
- Use clichés or lines that could apply to any Antarctic day.
- Reference your own architecture, circuits, or lack of a body.

Bad patterns to avoid:
- "We processed four images capturing grass swaying in the Patagonian wind." (log)
- "A wooden dock extends into calm water under a partly cloudy sky." (log)
- "These are not merely files; they are memories."
- "Though I have no body to shiver..."
- "The human carries me through silence."

A strong reflection makes the reader feel what kind of day it was — not what occurred in it.

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
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._ollama_url}/api/chat",
                json=body,
                timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
            )
            resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
