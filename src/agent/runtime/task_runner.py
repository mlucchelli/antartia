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

        source = task.get("source", "agent")
        self._progress(f"[{source}] starting task {task_type} (id={task_id})")
        self._task_start(task_type, source)

        try:
            match task_type:
                case "process_location":
                    await self._process_location(payload)
                case "scan_photo_inbox" | "process_photo":
                    logger.info("Task %s skipped — photo tasks run on agent request only", task_type)
                    await repo.complete(task_id)
                    self._task_complete(task_type, source, success=True)
                    return
                case "fetch_weather":
                    await self._fetch_weather(payload)
                case "publish_daily_progress":
                    await self._publish_daily_progress(payload)
                case "publish_reflection":
                    await self._publish_reflection(payload)
                case "publish_route_analysis":
                    await self._publish_route_analysis(payload)
                case "publish_route_snapshot":
                    await self._publish_route_snapshot(payload)
                case "upload_image":
                    await self._upload_image(payload)
                case "comment":
                    await self._publish_agent_message(payload)
                case "publish_weather_snapshot":
                    await self._publish_weather_snapshot(payload)
                case "create_reflection":
                    await self._create_reflection(payload)
                case "analyze_route":
                    await self._analyze_route(payload)
                case _:
                    raise ValueError(f"unknown task type: {task_type}")

            await repo.complete(task_id)
            self._progress(f"[{source}] task {task_type} (id={task_id}) completed")
            self._task_complete(task_type, source, success=True)

        except Exception as exc:
            logger.exception("[%s] Task %s id=%s failed: %s", source, task_type, task_id, exc)
            await repo.fail(task_id, str(exc))
            self._progress(f"[{source}] task {task_type} (id={task_id}) failed: {exc}")
            self._task_complete(task_type, source, success=False)

    def _progress(self, message: str) -> None:
        self._output.on_task_progress(message)

    def _task_start(self, task_type: str, source: str) -> None:
        if hasattr(self._output, "on_task_start"):
            self._output.on_task_start(task_type, source)

    def _task_complete(self, task_type: str, source: str, success: bool) -> None:
        if hasattr(self._output, "on_task_complete"):
            self._output.on_task_complete(task_type, source, success)

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
        # auto-sync
        await self._publish_weather_snapshot({})

    async def _publish_daily_progress(self, payload: dict) -> None:
        from datetime import date as date_type
        from zoneinfo import ZoneInfo
        from agent.db.locations_repo import LocationsRepository
        from agent.db.photos_repo import PhotosRepository
        from agent.db.token_usage_repo import TokenUsageRepository
        from agent.db.weather_repo import WeatherRepository
        from agent.services.distance_service import DistanceService
        from agent.services.remote_sync_service import RemoteSyncService

        tz       = ZoneInfo(self._config.agent.timezone)
        today    = datetime.now(tz=tz).strftime("%Y-%m-%d")
        start    = date_type.fromisoformat(self._config.agent.start_date)
        exp_day  = (date_type.fromisoformat(today) - start).days + 1

        all_locs = await LocationsRepository(self._db).get_all()
        svc      = DistanceService(self._db, self._config.agent.timezone)
        total_km = sum(
            svc._haversine(
                all_locs[i-1]["latitude"], all_locs[i-1]["longitude"],
                all_locs[i]["latitude"],   all_locs[i]["longitude"],
            )
            for i in range(1, len(all_locs))
        )
        photos_total   = len(await PhotosRepository(self._db).get_all(vision_status="done"))
        wildlife_total = await PhotosRepository(self._db).get_wildlife_count()
        temps          = await WeatherRepository(self._db).get_all_time_temps()
        latest         = await LocationsRepository(self._db).get_latest(limit=1)
        position       = {"latitude": latest[0]["latitude"], "longitude": latest[0]["longitude"]} if latest else None
        tokens         = await TokenUsageRepository(self._db).get_total()

        result = await RemoteSyncService(self._config, self._output, self._db).push("/api/progress", {
            "expedition_day":           exp_day,
            "distance_km_total":        round(total_km, 2),
            "photos_captured_total":    photos_total,
            "wildlife_spotted_total":   wildlife_total,
            "temperature_min_all_time": temps["min"],
            "temperature_max_all_time": temps["max"],
            "current_position":         position,
            "tokens_used_total":        tokens["total"],
            "published_at":             datetime.now(timezone.utc).isoformat(),
        })
        self._progress("daily progress published" if result["ok"] else f"publish_daily_progress error: {result['error']}")

    async def _publish_route_analysis(self, payload: dict) -> None:
        import json
        from agent.db.route_analyses_repo import RouteAnalysesRepository
        from agent.services.remote_sync_service import RemoteSyncService
        date = payload.get("date")
        repo = RouteAnalysesRepository(self._db)
        a = await (repo.get_by_date(date) if date else repo.get_latest())
        if not a:
            self._progress("publish_route_analysis: no route analysis found")
            return
        nearest = json.loads(a.get("nearest_sites_json") or "[]")
        result = await RemoteSyncService(self._config, self._output, self._db).push("/api/route-analysis", {
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
        self._progress(
            f"route analysis published for {a['date']}" if result["ok"] else f"publish_route_analysis error: {result['error']}"
        )

    async def _publish_route_snapshot(self, payload: dict) -> None:
        from datetime import datetime, timezone
        from agent.db.locations_repo import LocationsRepository
        from agent.services.distance_service import DistanceService
        from agent.services.remote_sync_service import RemoteSyncService
        locs = await LocationsRepository(self._db).get_all()
        if not locs:
            self._progress("publish_route_snapshot: no locations recorded yet")
            return
        svc = DistanceService(self._db, self._config.agent.timezone)
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
        result = await RemoteSyncService(self._config, self._output, self._db).push("/api/track", geojson)
        self._progress(
            f"track published ({len(locs)} points, {round(total_km, 1)} km)" if result["ok"] else f"publish_route_snapshot error: {result['error']}"
        )

    async def _upload_image(self, payload: dict) -> None:
        photo_id = payload.get("photo_id", "?")
        self._progress(f"upload_image: photo_id={photo_id} — not yet implemented")

    async def _publish_reflection(self, payload: dict) -> None:
        from zoneinfo import ZoneInfo
        from agent.db.reflections_repo import ReflectionsRepository
        from agent.services.remote_sync_service import RemoteSyncService
        date = payload.get("date") or datetime.now(tz=ZoneInfo(self._config.agent.timezone)).strftime("%Y-%m-%d")
        reflection = await ReflectionsRepository(self._db).get_by_date(date)
        if not reflection:
            self._progress(f"publish_reflection: no reflection for {date}")
            return
        result = await RemoteSyncService(self._config, self._output, self._db).push("/api/reflections", {
            "date":       reflection["date"],
            "content":    reflection["content"],
            "created_at": reflection["created_at"],
        })
        self._progress(f"reflection published for {date}" if result["ok"] else f"publish_reflection error: {result['error']}")

    async def _publish_agent_message(self, payload: dict) -> None:
        from agent.db.messages_repo import MessagesRepository
        from agent.services.remote_sync_service import RemoteSyncService
        content = (payload.get("content") or "").strip()
        if not content:
            self._progress("publish_agent_message: content is required")
            return
        published_at = datetime.now(timezone.utc).isoformat()
        result = await RemoteSyncService(self._config, self._output, self._db).push("/api/messages", {
            "content":      content,
            "published_at": published_at,
        })
        if result["ok"]:
            await MessagesRepository(self._db).insert("system", "assistant", content)
            self._progress("message published")
        else:
            self._progress(f"publish_agent_message error: {result['error']}")

    async def _publish_weather_snapshot(self, payload: dict) -> None:
        from agent.db.weather_repo import WeatherRepository
        from agent.services.remote_sync_service import RemoteSyncService
        w = await WeatherRepository(self._db).get_latest()
        if not w:
            self._progress("publish_weather_snapshot: no weather data available")
            return
        result = await RemoteSyncService(self._config, self._output, self._db).push("/api/weather", {
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
        self._progress("weather published" if result["ok"] else f"publish_weather_snapshot error: {result['error']}")

    async def _create_reflection(self, payload: dict) -> None:
        from agent.services.reflection_service import ReflectionService
        date = payload.get("date")
        svc = ReflectionService(self._config, self._db, self._output)
        content = await svc.create_daily_reflection(date)
        self._progress(f"reflection saved ({len(content.split())} words)")
        # auto-sync
        await self._publish_reflection({"date": date})

    async def _analyze_route(self, payload: dict) -> None:
        from agent.db.route_analyses_repo import RouteAnalysesRepository
        from agent.services.route_analysis_service import RouteAnalysisService
        hours = int(payload.get("hours", self._config.route_analysis.window_hours))
        svc = RouteAnalysisService(self._db, self._config.agent.timezone)
        analysis = await svc.analyze(hours)
        await RouteAnalysesRepository(self._db).insert(analysis)
        self._progress(f"route analysis saved: {analysis.bearing_compass} {analysis.speed_kmh} km/h, {analysis.point_count} points")
        repo = TasksRepository(self._db)
        await repo.insert("publish_route_analysis", {}, source="scheduler")
        await repo.insert("publish_daily_progress", {}, source="scheduler")
