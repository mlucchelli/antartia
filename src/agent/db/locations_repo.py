from __future__ import annotations

from datetime import datetime, timezone

from agent.db.database import Database


class LocationsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(self, latitude: float, longitude: float, recorded_at: datetime) -> dict:
        received_at = datetime.now(timezone.utc).isoformat()
        async with self._db.conn.execute(
            "INSERT INTO locations (latitude, longitude, recorded_at, received_at) VALUES (?, ?, ?, ?)",
            (latitude, longitude, recorded_at.isoformat(), received_at),
        ) as cur:
            row_id = cur.lastrowid
        await self._db.conn.commit()
        return {"id": row_id, "latitude": latitude, "longitude": longitude,
                "recorded_at": recorded_at.isoformat(), "received_at": received_at}

    async def get_latest(self, limit: int = 10) -> list[dict]:
        async with self._db.conn.execute(
            "SELECT * FROM locations ORDER BY recorded_at DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_by_date(self, date: str) -> list[dict]:
        """date: YYYY-MM-DD"""
        async with self._db.conn.execute(
            "SELECT * FROM locations WHERE date(recorded_at) = ? ORDER BY recorded_at ASC",
            (date,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_all(self) -> list[dict]:
        async with self._db.conn.execute(
            "SELECT * FROM locations ORDER BY recorded_at ASC"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
