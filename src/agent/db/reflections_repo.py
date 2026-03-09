from __future__ import annotations

from datetime import datetime, timezone

from agent.db.database import Database


class ReflectionsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(self, date: str, content: str) -> dict:
        word_count = len(content.split())
        created_at = datetime.now(timezone.utc).isoformat()
        async with self._db.conn.execute(
            """INSERT INTO reflections (date, content, word_count, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET content=excluded.content,
               word_count=excluded.word_count, created_at=excluded.created_at""",
            (date, content, word_count, created_at),
        ) as cur:
            row_id = cur.lastrowid
        await self._db.conn.commit()
        return {"id": row_id, "date": date, "content": content,
                "word_count": word_count, "created_at": created_at}

    async def get_by_date(self, date: str) -> dict | None:
        async with self._db.conn.execute(
            "SELECT * FROM reflections WHERE date = ?", (date,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_recent(self, limit: int = 7) -> list[dict]:
        async with self._db.conn.execute(
            "SELECT * FROM reflections ORDER BY date DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
