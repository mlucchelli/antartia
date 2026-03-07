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
        wind_speed: float | None,
        wind_direction: float | None,
        condition: str | None,
        raw: dict,
    ) -> dict:
        recorded_at = datetime.now(timezone.utc).isoformat()
        async with self._db.conn.execute(
            """INSERT INTO weather_snapshots
               (latitude, longitude, temperature, wind_speed, wind_direction, condition, raw_json, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (latitude, longitude, temperature, wind_speed, wind_direction,
             condition, json.dumps(raw), recorded_at),
        ) as cur:
            row_id = cur.lastrowid
        await self._db.conn.commit()
        return {"id": row_id, "latitude": latitude, "longitude": longitude,
                "temperature": temperature, "wind_speed": wind_speed,
                "wind_direction": wind_direction, "condition": condition,
                "recorded_at": recorded_at}

    async def get_latest(self) -> dict | None:
        async with self._db.conn.execute(
            "SELECT * FROM weather_snapshots ORDER BY recorded_at DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_today(self) -> list[dict]:
        today = datetime.now(timezone.utc).date().isoformat()
        async with self._db.conn.execute(
            "SELECT * FROM weather_snapshots WHERE date(recorded_at) = ? ORDER BY recorded_at ASC",
            (today,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
