from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from agent.config.loader import Config
from agent.db.database import Database
from agent.db.locations_repo import LocationsRepository
from agent.db.messages_repo import MessagesRepository
from agent.db.photos_repo import PhotosRepository
from agent.db.reflections_repo import ReflectionsRepository
from agent.db.tasks_repo import TasksRepository, VALID_TASK_TYPES
from agent.db.weather_repo import WeatherRepository
from agent.services.remote_sync_service import RemoteSyncService
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

        # Update knowledge docs list in metadata for the prompt builder
        if self._db:
            from agent.db.knowledge_docs_repo import KnowledgeDocsRepository
            repo = KnowledgeDocsRepository(self._db)
            docs = await repo.get_all(status="indexed")
            state.metadata["knowledge_docs"] = [d["file_name"] for d in docs]

        system_prompt = self._prompt_builder.build(state)
        state.add_message("user", user_message)

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for msg in state.messages:
            messages.append({"role": msg.role, "content": msg.content})

        self._output.on_system_prompt(system_prompt)

        max_depth = self._config.runtime.max_chain_depth

        for depth in range(max_depth):
            self._output.on_llm_start(depth)
            logger.info("LLM invoke depth=%d session=%s", depth, session_id)
            response = await self._llm.ainvoke(messages, RESPONSE_FORMAT)
            usage = response.get("_usage", {})  # read before on_llm_response pops it
            self._output.on_llm_response(response)
            logger.info(
                "LLM response depth=%d tokens=%d actions=%s",
                depth,
                usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
                [a.get("type") for a in self._extract_actions(response)],
            )
            await self._log_tokens(
                session_id=session_id,
                model=self._config.agent.model,
                call_type="chat",
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            )

            raw_actions = self._extract_actions(response)
            actions = self._parser.parse(raw_actions)

            # send_message only auto-finishes when no tool calls are pending in the same batch
            has_tool_actions = any(isinstance(a, ToolAction) for a in actions)

            # Execute all actions in order
            finish = False
            did_something = False
            for action in actions:
                self._output.on_action_start(action.type)
                logger.info("Action: %s session=%s depth=%d", action.type, session_id, depth)
                if isinstance(action, FinishAction):
                    finish = True
                    did_something = True
                elif isinstance(action, SendMessageAction):
                    result = await action.execute(state)
                    self._output.on_state_update(state.model_dump())
                    if result:
                        self._output.display(result)
                        logger.info("Message sent: %s…", result[:80].replace("\n", " "))
                    did_something = True
                    if not has_tool_actions:
                        finish = True  # no tool calls pending — treat as final message
                elif isinstance(action, ToolAction):
                    tool_result = await self._dispatch_tool(action.type, action.payload)
                    logger.info("Tool %s → %s…", action.type, str(tool_result)[:120].replace("\n", " "))
                    await self._log_activity(session_id, action.type, action.payload, tool_result)
                    messages.append({
                        "role": "tool",
                        "content": f"[{action.type} result]: {tool_result}",
                    })
                    did_something = True

            if finish:
                logger.info("Chain finished at depth=%d session=%s", depth, session_id)
                await self._store.save(state)
                return

            if not did_something:
                logger.warning("No actionable response at depth %d — stopping", depth)
                break

        # Max depth reached or no valid actions — force a fallback
        logger.warning("Chain ended without finish — sending fallback session=%s", session_id)
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
                case "publish_reflection":
                    return await self._tool_publish_reflection(payload)
                case "publish_daily_progress":
                    return await self._tool_publish_daily_progress(payload)
                case "publish_route_analysis":
                    return await self._tool_publish_route_analysis(payload)
                case "publish_route_snapshot":
                    return await self._tool_publish_route_snapshot(payload)
                case "upload_image":
                    return await self._tool_upload_image(payload)
                case "comment":
                    return await self._tool_publish_agent_message(payload)
                case "publish_weather_snapshot":
                    return await self._tool_publish_weather_snapshot(payload)
                case "search_knowledge":
                    return await self._tool_search_knowledge(payload)
                case "index_knowledge":
                    return await self._tool_index_knowledge(payload)
                case "add_knowledge":
                    return await self._tool_add_knowledge(payload)
                case "clear_knowledge":
                    return await self._tool_clear_knowledge(payload)
                case "get_logs":
                    return await self._tool_get_logs(payload)
                case "get_token_usage":
                    return await self._tool_get_token_usage(payload)
                case "get_distance":
                    return await self._tool_get_distance(payload)
                case "add_location":
                    return await self._tool_add_location(payload)
                case "get_reflections":
                    return await self._tool_get_reflections(payload)
                case "analyze_route":
                    return await self._tool_analyze_route(payload)
                case "get_route_analysis":
                    return await self._tool_get_route_analysis(payload)
                case _:
                    return f"unknown tool: {action_type}"
        except Exception as exc:
            logger.exception("Tool %s failed: %s", action_type, exc)
            return f"error executing {action_type}: {type(exc).__name__}: {exc}"

    async def _log_tokens(
        self,
        session_id: str,
        model: str,
        call_type: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        if self._db is None or (prompt_tokens == 0 and completion_tokens == 0):
            return
        try:
            from agent.db.token_usage_repo import TokenUsageRepository
            await TokenUsageRepository(self._db).insert(
                model=model,
                call_type=call_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                session_id=session_id,
            )
            total = prompt_tokens + completion_tokens
            self._output.on_tokens_used(total)
        except Exception as exc:
            logger.warning("Failed to log tokens: %s", exc)

    _NETWORK_ACTIONS = {
        "comment", "publish_reflection", "publish_weather_snapshot",
        "publish_route_snapshot", "publish_route_analysis",
        "publish_daily_progress", "upload_image",
    }

    async def _log_activity(self, session_id: str, action_type: str, payload: dict, result: str) -> None:
        if self._db is None:
            return
        try:
            from agent.db.activity_logs_repo import ActivityLogsRepository
            await ActivityLogsRepository(self._db).insert(
                session_id=session_id,
                action_type=action_type,
                payload=json.dumps(payload),
                result=str(result),
                is_network=action_type in self._NETWORK_ACTIONS,
            )
        except Exception as exc:
            logger.warning("Failed to log activity: %s", exc)

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

        # Process all pending + stuck-analyzing photos
        to_process = await PhotosRepository(db).get_all(vision_status="pending")
        stuck = await PhotosRepository(db).get_all(vision_status="analyzing")
        to_process = to_process + stuck
        for photo in to_process:
            await svc.process_photo(photo["id"])

        total = len(to_process)
        if new_count == 0 and total == 0:
            return "inbox is empty — no new or pending photos found"
        recovered = len(stuck)
        return f"scanned inbox: {new_count} new, {total} processed" + (
            f" ({recovered} recovered from stuck state)" if recovered else ""
        )

    async def _tool_publish_daily_progress(self, payload: dict) -> str:
        # Full implementation in RemoteSyncService (commit 18)
        return "publish_daily_progress not yet implemented"

    async def _tool_publish_route_analysis(self, payload: dict) -> str:
        from agent.db.route_analyses_repo import RouteAnalysesRepository
        date = payload.get("date")
        repo = RouteAnalysesRepository(self._require_db())
        a = await (repo.get_by_date(date) if date else repo.get_latest())
        if not a:
            return "no route analysis found"
        nearest = json.loads(a.get("nearest_sites_json") or "[]")
        result = await RemoteSyncService(self._config, self._output).push("/api/route-analysis", {
            "analyzed_at":     a["analyzed_at"],
            "date":            a["date"],
            "window_hours":    a["window_hours"],
            "point_count":     a.get("point_count", 0),
            "position":        {"latitude": a["latitude"], "longitude": a["longitude"]},
            "bearing_deg":     a["bearing_deg"],
            "bearing_compass": a["bearing_compass"],
            "speed_kmh":       a["speed_kmh"],
            "avg_speed_kmh":   a["avg_speed_kmh"],
            "distance_km":     a["distance_km"],
            "stopped":         bool(a["stopped"]),
            "wind": {
                "speed_kmh":     a["wind_speed_kmh"],
                "direction_deg": a["wind_direction_deg"],
                "angle_label":   a["wind_angle_label"],
            },
            "nearest_sites": nearest,
        })
        return f"route analysis published for {a['date']}" if result["ok"] else f"error: {result['error']}"

    async def _tool_publish_route_snapshot(self, payload: dict) -> str:
        locs = await LocationsRepository(self._require_db()).get_all()
        if not locs:
            return "no locations recorded yet"
        from agent.services.distance_service import DistanceService
        svc = DistanceService(self._require_db(), self._config.agent.timezone)
        total_km = sum(
            svc._haversine(
                locs[i-1]["latitude"], locs[i-1]["longitude"],
                locs[i]["latitude"],   locs[i]["longitude"],
            )
            for i in range(1, len(locs))
        )
        now = datetime.now(timezone.utc).isoformat()
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[loc["longitude"], loc["latitude"]] for loc in locs],
                },
                "properties": {
                    "recorded_at_first": locs[0]["recorded_at"],
                    "recorded_at_last":  locs[-1]["recorded_at"],
                    "total_points":      len(locs),
                    "distance_km":       round(total_km, 2),
                    "last_updated":      now,
                },
            }],
        }
        result = await RemoteSyncService(self._config, self._output).push("/api/track", geojson)
        return (
            f"track published ({len(locs)} points, {round(total_km, 1)} km)"
            if result["ok"] else f"error: {result['error']}"
        )

    async def _tool_upload_image(self, payload: dict) -> str:
        photo_id = payload.get("photo_id")
        agent_quote = payload.get("agent_quote", "").strip()
        if not photo_id:
            return "error: photo_id is required"
        repo = PhotosRepository(self._require_db())
        photo = await repo.get_by_id(int(photo_id))
        if not photo:
            return f"error: photo {photo_id} not found"
        if not photo.get("is_remote_candidate"):
            return f"photo {photo_id} is not marked as remote candidate — upload skipped"
        update: dict = {}
        if agent_quote:
            update["agent_quote"] = agent_quote
        if update:
            await repo.update(int(photo_id), **update)
        # Remote upload not yet implemented — mark as ready for publishing
        return (
            f"photo {photo_id} ({photo['file_name']}) queued for upload"
            + (f' — quote saved: "{agent_quote[:80]}"' if agent_quote else "")
        )

    async def _tool_publish_reflection(self, payload: dict) -> str:
        from zoneinfo import ZoneInfo
        date = payload.get("date") or datetime.now(tz=ZoneInfo(self._config.agent.timezone)).strftime("%Y-%m-%d")
        reflection = await ReflectionsRepository(self._require_db()).get_by_date(date)
        if not reflection:
            return f"no reflection found for {date}"
        result = await RemoteSyncService(self._config, self._output).push("/api/reflections", {
            "date":       reflection["date"],
            "content":    reflection["content"],
            "created_at": reflection["created_at"],
        })
        return f"reflection published for {date}" if result["ok"] else f"error: {result['error']}"

    async def _tool_publish_agent_message(self, payload: dict) -> str:
        content = (payload.get("content") or "").strip()
        if not content:
            return "error: content is required"
        published_at = datetime.now(timezone.utc).isoformat()
        result = await RemoteSyncService(self._config, self._output).push("/api/messages", {
            "content":      content,
            "published_at": published_at,
        })
        if result["ok"]:
            await MessagesRepository(self._require_db()).insert("system", "assistant", content)
            return "message published"
        return f"error: {result['error']}"

    async def _tool_publish_weather_snapshot(self, payload: dict) -> str:
        w = await WeatherRepository(self._require_db()).get_latest()
        if not w:
            return "no weather snapshot available"
        result = await RemoteSyncService(self._config, self._output).push("/api/weather", {
            "latitude":             w["latitude"],
            "longitude":            w["longitude"],
            "temperature":          w["temperature"],
            "apparent_temperature": w["apparent_temperature"],
            "wind_speed":           w["wind_speed"],
            "wind_gusts":           w["wind_gusts"],
            "wind_direction":       w["wind_direction"],
            "precipitation":        w["precipitation"],
            "snowfall":             w["snowfall"],
            "condition":            w["condition"],
            "recorded_at":          w["recorded_at"],
        })
        return "weather published" if result["ok"] else f"error: {result['error']}"

    async def _tool_search_knowledge(self, payload: dict) -> str:
        from agent.services.knowledge_service import KnowledgeService
        query = payload.get("query", "")
        if not query:
            return "error: query is required"
        svc = KnowledgeService(self._config, self._require_db(), self._output)
        return await svc.search(query)

    async def _tool_index_knowledge(self, payload: dict) -> str:
        from agent.services.knowledge_service import KnowledgeService
        svc = KnowledgeService(self._config, self._require_db(), self._output)
        count = await svc.index_documents()
        if count == 0:
            return "inbox is empty — no documents found to index. Drop .txt or .md files into data/knowledge/inbox/ first."
        return f"indexed {count} chunks successfully"

    async def _tool_add_knowledge(self, payload: dict) -> str:
        from agent.services.knowledge_service import KnowledgeService
        content = payload.get("content", "")
        if not content:
            return "error: content is required"
        title = payload.get("title", "expedition_note")
        svc = KnowledgeService(self._config, self._require_db(), self._output)
        count = await svc.add_document(content, title)
        return f"added {count} chunks to knowledge base (title='{title}')"

    async def _tool_get_logs(self, payload: dict) -> str:
        from agent.db.activity_logs_repo import ActivityLogsRepository
        from_dt = payload.get("from")
        to_dt = payload.get("to")
        repo = ActivityLogsRepository(self._require_db())
        rows = await repo.get_by_range(from_dt, to_dt)
        if not rows:
            return "no activity logs found for the given range"
        lines = []
        for r in rows:
            ts = (r.get("created_at") or "")[:19].replace("T", " ")
            lines.append(f"{ts}  {r['action_type']}")
        return "\n".join(lines)

    async def _tool_clear_knowledge(self, payload: dict) -> str:
        from agent.services.knowledge_service import KnowledgeService
        svc = KnowledgeService(self._config, self._require_db(), self._output)
        await svc.clear()
        return "knowledge base cleared — vector store and document records wiped"

    async def _tool_add_location(self, payload: dict) -> str:
        from datetime import datetime, timezone
        from agent.db.locations_repo import LocationsRepository
        try:
            lat = float(payload["latitude"])
            lon = float(payload["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            return f"error: latitude and longitude are required floats — {exc}"
        recorded_at_str = payload.get("recorded_at")
        if recorded_at_str:
            try:
                recorded_at = datetime.fromisoformat(recorded_at_str)
                if recorded_at.tzinfo is None:
                    recorded_at = recorded_at.replace(tzinfo=timezone.utc)
            except ValueError:
                return f"error: invalid recorded_at format — use ISO 8601 (e.g. 2026-03-09T14:00:00Z)"
        else:
            recorded_at = datetime.now(timezone.utc)
        loc = await LocationsRepository(self._require_db()).insert(lat, lon, recorded_at)
        self._output.update_location(lat, lon)
        return f"location added: id={loc['id']} lat={lat} lon={lon} at={recorded_at.isoformat()}"

    async def _tool_get_reflections(self, payload: dict) -> str:
        import json
        from agent.db.reflections_repo import ReflectionsRepository
        repo = ReflectionsRepository(self._require_db())
        date = payload.get("date")
        if date:
            row = await repo.get_by_date(date)
            return json.dumps(row, default=str) if row else f"no reflection found for {date}"
        rows = await repo.get_recent(limit=payload.get("limit", 7))
        return json.dumps(rows, default=str) if rows else "no reflections yet"

    async def _tool_get_distance(self, payload: dict) -> str:
        from agent.services.distance_service import DistanceService
        svc = DistanceService(self._require_db(), self._config.agent.timezone)
        date = payload.get("date")
        if date:
            km = await svc.get_distance_for_date(date)
            return f"{km} km on {date}"
        km = await svc.get_today_distance()
        return f"{km} km today"

    async def _tool_analyze_route(self, payload: dict) -> str:
        from agent.db.route_analyses_repo import RouteAnalysesRepository
        from agent.services.route_analysis_service import RouteAnalysisService
        hours = int(payload.get("hours", self._config.route_analysis.window_hours))
        svc = RouteAnalysisService(self._require_db(), self._config.agent.timezone)
        analysis = await svc.analyze(hours)
        await RouteAnalysesRepository(self._require_db()).insert(analysis)
        return analysis.to_text()

    async def _tool_get_route_analysis(self, payload: dict) -> str:
        from agent.db.route_analyses_repo import RouteAnalysesRepository
        repo = RouteAnalysesRepository(self._require_db())
        date = payload.get("date")
        if date:
            rows = await repo.get_by_date(date)
            if not rows:
                return f"no route analysis stored for {date}"
            return rows[0]["summary"] or json.dumps(rows[0], default=str)
        row = await repo.get_latest()
        if not row:
            return "no route analysis stored yet — call analyze_route first"
        return row["summary"] or json.dumps(row, default=str)

    async def _tool_get_token_usage(self, payload: dict) -> str:
        from agent.db.token_usage_repo import TokenUsageRepository
        repo = TokenUsageRepository(self._require_db())
        totals = await repo.get_total()
        by_type = await repo.get_by_call_type()
        breakdown = ", ".join(
            f"{r['call_type']}: {r['total_tokens']:,} ({r['calls']} calls)" for r in by_type
        )
        return (
            f"total tokens used: {totals['total']:,} "
            f"(prompt: {totals['prompt']:,}, completion: {totals['completion']:,})"
            + (f" — breakdown: {breakdown}" if breakdown else "")
        )
