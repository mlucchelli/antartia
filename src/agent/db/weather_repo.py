from __future__ import annotations

import json
from datetime import datetime, timezone

from agent.db.database import Database


class WeatherRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        latitude: float,
        longitude: float,
        temperature: float | None,
        apparent_temperature: float | None,
        wind_speed: float | None,
        wind_gusts: float | None,
        wind_direction: float | None,
        precipitation: float | None,
        snowfall: float | None,
        snow_depth: float | None,
        surface_pressure: float | None,
        condition: str | None,
        raw: dict,
    ) -> dict:
        recorded_at = datetime.now(timezone.utc).isoformat()
        async with self._db.conn.execute(
            """INSERT INTO weather_snapshots
               (latitude, longitude, temperature, apparent_temperature,
                wind_speed, wind_gusts, wind_direction,
                precipitation, snowfall, snow_depth, surface_pressure,
                condition, raw_json, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (latitude, longitude, temperature, apparent_temperature,
             wind_speed, wind_gusts, wind_direction,
             precipitation, snowfall, snow_depth, surface_pressure,
             condition, json.dumps(raw), recorded_at),
        ) as cur:
            row_id = cur.lastrowid
        await self._db.conn.commit()
        return {
            "id": row_id,
            "latitude": latitude,
            "longitude": longitude,
            "temperature": temperature,
            "apparent_temperature": apparent_temperature,
            "wind_speed": wind_speed,
            "wind_gusts": wind_gusts,
            "wind_direction": wind_direction,
            "precipitation": precipitation,
            "snowfall": snowfall,
            "snow_depth": snow_depth,
            "surface_pressure": surface_pressure,
            "condition": condition,
            "recorded_at": recorded_at,
        }

    async def get_by_id(self, weather_id: int) -> dict | None:
        async with self._db.conn.execute(
            "SELECT * FROM weather_snapshots WHERE id = ?", (weather_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_latest(self) -> dict | None:
        async with self._db.conn.execute(
            "SELECT * FROM weather_snapshots ORDER BY recorded_at DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_all_time_temps(self) -> dict:
        """Return all-time MIN and MAX temperature across all weather snapshots."""
        async with self._db.conn.execute(
            "SELECT MIN(temperature), MAX(temperature) FROM weather_snapshots"
        ) as cur:
            row = await cur.fetchone()
        return {"min": row[0], "max": row[1]}

    async def get_today(self) -> list[dict]:
        today = datetime.now(timezone.utc).date().isoformat()
        return await self.get_by_date(today)

    async def get_by_date(self, date: str) -> list[dict]:
        async with self._db.conn.execute(
            "SELECT * FROM weather_snapshots WHERE date(recorded_at) = ? ORDER BY recorded_at ASC",
            (date,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
