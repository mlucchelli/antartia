from __future__ import annotations

import json
import logging
from typing import Any

from agent.config.loader import Config
from agent.db.database import Database
from agent.db.locations_repo import LocationsRepository
from agent.db.messages_repo import MessagesRepository
from agent.db.photos_repo import PhotosRepository
from agent.db.tasks_repo import TasksRepository, VALID_TASK_TYPES
from agent.db.weather_repo import WeatherRepository
from agent.llm.client import LLMClient
from agent.llm.prompt_builder import PromptBuilder
from agent.models.actions import FinishAction, SendMessageAction, ToolAction
from agent.runtime.parser import ActionParser
from agent.runtime.protocols import OutputHandler
from agent.state.store import StateStore

logger = logging.getLogger(__name__)

RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "agent_response",
        "strict": False,
        "schema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "payload": {"type": "object"},
                        },
                        "required": ["type"],
                    },
                },
            },
            "required": ["actions"],
            "additionalProperties": False,
        },
    },
}


class Runtime:
    def __init__(
        self,
        config: Config,
        state_store: StateStore,
        llm_client: LLMClient,
        output: OutputHandler,
        db: Database | None = None,
    ) -> None:
        self._config = config
        self._store = state_store
        self._llm = llm_client
        self._prompt_builder = PromptBuilder(config)
        self._parser = ActionParser()
        self._output = output
        self._db = db

    async def start_session(self, session_id: str | None = None) -> str:
        state = await self._store.create(session_id)
        greeting = self._config.agent.greeting
        state.add_message("assistant", greeting)
        await self._store.save(state)
        self._output.on_state_update(state.model_dump())
        self._output.display(greeting)
        return state.session_id

    async def end_session(self, session_id: str) -> None:
        await self._store.delete(session_id)

    async def process_message(self, session_id: str, user_message: str) -> None:
        state = await self._store.get(session_id)
        system_prompt = self._prompt_builder.build(state)
        state.add_message("user", user_message)

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for msg in state.messages:
            messages.append({"role": msg.role, "content": msg.content})

        self._output.on_system_prompt(system_prompt)

        max_depth = self._config.runtime.max_chain_depth

        for depth in range(max_depth):
            self._output.on_llm_start(depth)
            response = await self._llm.ainvoke(messages, RESPONSE_FORMAT)
            self._output.on_llm_response(response)

            raw_actions = self._extract_actions(response)
            actions = self._parser.parse(raw_actions)

            # Execute all actions in order
            finish = False
            did_something = False
            for action in actions:
                self._output.on_action_start(action.type)
                if isinstance(action, FinishAction):
                    finish = True
                    did_something = True
                elif isinstance(action, SendMessageAction):
                    result = await action.execute(state)
                    self._output.on_state_update(state.model_dump())
                    if result:
                        self._output.display(result)
                    did_something = True
                elif isinstance(action, ToolAction):
                    tool_result = await self._dispatch_tool(action.type, action.payload)
                    messages.append({
                        "role": "tool",
                        "content": f"[{action.type} result]: {tool_result}",
                    })
                    did_something = True

            if finish:
                await self._store.save(state)
                return

            if not did_something:
                logger.warning("No actionable response at depth %d — stopping", depth)
                break

        # Max depth reached or no valid actions — force a fallback
        logger.warning("Chain ended without finish — sending fallback")
        fallback = "I've completed the requested operations."
        state.add_message("assistant", fallback)
        await self._store.save(state)
        self._output.display(fallback)

    def _extract_actions(self, response: dict) -> list[dict]:
        raw = response.get("actions")
        if not isinstance(raw, list):
            logger.warning("LLM response missing or invalid 'actions': %s", response)
            return []
        return raw

    # ── Tool dispatch ─────────────────────────────────────────────────────────

    async def _dispatch_tool(self, action_type: str, payload: dict) -> str:
        try:
            match action_type:
                case "get_latest_locations":
                    return await self._tool_get_latest_locations(payload)
                case "get_locations_by_date":
                    return await self._tool_get_locations_by_date(payload)
                case "get_photos":
                    return await self._tool_get_photos(payload)
                case "get_weather":
                    return await self._tool_get_weather(payload)
                case "create_task":
                    return await self._tool_create_task(payload)
                case "scan_photo_inbox":
                    return await self._tool_scan_photo_inbox(payload)
                case "publish_daily_progress":
                    return await self._tool_publish_daily_progress(payload)
                case "publish_route_snapshot":
                    return await self._tool_publish_route_snapshot(payload)
                case "upload_image":
                    return await self._tool_upload_image(payload)
                case "publish_agent_message":
                    return await self._tool_publish_agent_message(payload)
                case "publish_weather_snapshot":
                    return await self._tool_publish_weather_snapshot(payload)
                case _:
                    return f"unknown tool: {action_type}"
        except Exception as exc:
            logger.exception("Tool %s failed: %s", action_type, exc)
            return f"error executing {action_type}: {exc}"

    def _require_db(self) -> Database:
        if self._db is None:
            raise RuntimeError("DB not configured")
        return self._db

    async def _tool_get_latest_locations(self, payload: dict) -> str:
        repo = LocationsRepository(self._require_db())
        limit = int(payload.get("limit", 10))
        rows = await repo.get_latest(limit)
        if not rows:
            return "no locations recorded yet"
        return json.dumps(rows, default=str)

    async def _tool_get_locations_by_date(self, payload: dict) -> str:
        date = payload.get("date")
        if not date:
            return "error: date is required (YYYY-MM-DD)"
        repo = LocationsRepository(self._require_db())
        rows = await repo.get_by_date(date)
        if not rows:
            return f"no locations recorded on {date}"
        return json.dumps(rows, default=str)

    async def _tool_get_photos(self, payload: dict) -> str:
        repo = PhotosRepository(self._require_db())
        rows = await repo.get_all(
            vision_status=payload.get("vision_status"),
            is_remote_candidate=payload.get("is_remote_candidate"),
            date=payload.get("date"),
        )
        if not rows:
            return "no photos found"
        return json.dumps(rows, default=str)

    async def _tool_get_weather(self, payload: dict) -> str:
        from agent.services.weather_service import WeatherService
        lat = payload.get("latitude")
        lon = payload.get("longitude")
        svc = WeatherService(self._config, self._require_db())
        snapshot = await svc.fetch_and_store(lat, lon)
        return json.dumps(snapshot, default=str)

    async def _tool_create_task(self, payload: dict) -> str:
        task_type = payload.get("type")
        if not task_type:
            return "error: task type is required"
        if task_type not in VALID_TASK_TYPES:
            return f"error: unknown task type '{task_type}'. Valid: {sorted(VALID_TASK_TYPES)}"
        repo = TasksRepository(self._require_db())
        task_payload = payload.get("payload", {})
        task = await repo.insert(task_type, task_payload)
        return f"task created: id={task['id']} type={task_type}"

    async def _tool_scan_photo_inbox(self, payload: dict) -> str:
        from agent.services.photo_service import PhotoService

        db = self._require_db()
        svc = PhotoService(self._config, db, self._output)
        new_count = await svc.scan_inbox()

        # Process all pending photos (newly discovered + any left from previous scans)
        pending = await PhotosRepository(db).get_all(vision_status="pending")
        for photo in pending:
            await svc.process_photo(photo["id"])

        total = len(pending)
        if new_count == 0 and total == 0:
            return "inbox is empty — no new or pending photos found"
        return f"scanned inbox: {new_count} new, {total} processed"

    async def _tool_publish_daily_progress(self, payload: dict) -> str:
        # Full implementation in RemoteSyncService (commit 18)
        return "publish_daily_progress not yet implemented"

    async def _tool_publish_route_snapshot(self, payload: dict) -> str:
        return "publish_route_snapshot not yet implemented"

    async def _tool_upload_image(self, payload: dict) -> str:
        return "upload_image not yet implemented"

    async def _tool_publish_agent_message(self, payload: dict) -> str:
        content = payload.get("content")
        if not content:
            return "error: content is required"
        repo = MessagesRepository(self._require_db())
        # Store message locally; remote publish in RemoteSyncService (commit 18)
        msg = await repo.insert("system", "assistant", content)
        return f"message saved locally (id={msg['id']}) — remote publish not yet implemented"

    async def _tool_publish_weather_snapshot(self, payload: dict) -> str:
        return "publish_weather_snapshot not yet implemented"
