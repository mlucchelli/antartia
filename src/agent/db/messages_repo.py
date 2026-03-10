from __future__ import annotations

from datetime import datetime, timezone

from agent.db.database import Database


class MessagesRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(self, session_id: str, role: str, content: str) -> dict:
        timestamp = datetime.now(timezone.utc).isoformat()
        async with self._db.conn.execute(
            """INSERT INTO agent_messages (session_id, role, content, timestamp)
               VALUES (?, ?, ?, ?)""",
            (session_id, role, content, timestamp),
        ) as cur:
            row_id = cur.lastrowid
        await self._db.conn.commit()
        return {"id": row_id, "session_id": session_id, "role": role,
                "content": content, "timestamp": timestamp}

    async def get_by_id(self, message_id: int) -> dict | None:
        async with self._db.conn.execute(
            "SELECT * FROM agent_messages WHERE id = ?", (message_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_today(self, session_id: str | None = None) -> list[dict]:
        today = datetime.now(timezone.utc).date().isoformat()
        return await self.get_by_date(today, session_id=session_id)

    async def get_by_date(self, date: str, session_id: str | None = None) -> list[dict]:
        if session_id:
            async with self._db.conn.execute(
                """SELECT * FROM agent_messages
                   WHERE date(timestamp) = ? AND session_id = ?
                   ORDER BY timestamp ASC""",
                (date, session_id),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self._db.conn.execute(
                "SELECT * FROM agent_messages WHERE date(timestamp) = ? ORDER BY timestamp ASC",
                (date,),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def mark_published(self, message_id: int) -> None:
        published_at = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            "UPDATE agent_messages SET published = 1, published_at = ? WHERE id = ?",
            (published_at, message_id),
        )
        await self._db.conn.commit()
