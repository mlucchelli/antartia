from __future__ import annotations

from datetime import datetime, timezone

from agent.db.database import Database


class PhotosRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(self, file_path: str, file_name: str, folder: str) -> dict:
        discovered_at = datetime.now(timezone.utc).isoformat()
        async with self._db.conn.execute(
            """INSERT INTO photos (file_path, file_name, folder, discovered_at)
               VALUES (?, ?, ?, ?)""",
            (file_path, file_name, folder, discovered_at),
        ) as cur:
            row_id = cur.lastrowid
        await self._db.conn.commit()
        return await self.get_by_id(row_id)

    async def get_by_id(self, photo_id: int) -> dict | None:
        async with self._db.conn.execute(
            "SELECT * FROM photos WHERE id = ?", (photo_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_by_path(self, file_path: str) -> dict | None:
        async with self._db.conn.execute(
            "SELECT * FROM photos WHERE file_path = ?", (file_path,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_all(
        self,
        vision_status: str | None = None,
        is_remote_candidate: bool | None = None,
        date: str | None = None,
    ) -> list[dict]:
        conditions: list[str] = []
        params: list = []
        if vision_status is not None:
            conditions.append("vision_status = ?")
            params.append(vision_status)
        if is_remote_candidate is not None:
            conditions.append("is_remote_candidate = ?")
            params.append(1 if is_remote_candidate else 0)
        if date is not None:
            conditions.append("date(discovered_at) = ?")
            params.append(date)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        async with self._db.conn.execute(
            f"SELECT * FROM photos {where} ORDER BY discovered_at DESC", params
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update(self, photo_id: int, **fields) -> None:
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [photo_id]
        await self._db.conn.execute(
            f"UPDATE photos SET {set_clause} WHERE id = ?", values
        )
        await self._db.conn.commit()

    async def count_uploaded_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        async with self._db.conn.execute(
            "SELECT COUNT(*) FROM photos WHERE remote_uploaded = 1 AND date(remote_uploaded_at) = ?",
            (today,),
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0
