from __future__ import annotations

from datetime import datetime, timezone

from agent.db.database import Database


class SyncQueueRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def enqueue(self, path: str, payload_json: str, max_attempts: int = 100) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        async with self._db.conn.execute(
            """INSERT INTO sync_queue (path, payload_json, max_attempts, created_at)
               VALUES (?, ?, ?, ?)""",
            (path, payload_json, max_attempts, created_at),
        ) as cur:
            row_id = cur.lastrowid
        await self._db.conn.commit()
        return row_id

    async def get_pending(self) -> list[dict]:
        async with self._db.conn.execute(
            """SELECT * FROM sync_queue
               WHERE status = 'pending' AND attempts < max_attempts
               ORDER BY created_at ASC"""
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def mark_sent(self, item_id: int) -> None:
        await self._db.conn.execute(
            "UPDATE sync_queue SET status='sent', last_attempt_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), item_id),
        )
        await self._db.conn.commit()

    async def record_attempt(self, item_id: int, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            """UPDATE sync_queue
               SET attempts = attempts + 1,
                   last_error = ?,
                   last_attempt_at = ?,
                   status = CASE WHEN attempts + 1 >= max_attempts THEN 'failed' ELSE 'pending' END
               WHERE id = ?""",
            (error, now, item_id),
        )
        await self._db.conn.commit()

    async def count_pending(self) -> int:
        async with self._db.conn.execute(
            "SELECT COUNT(*) FROM sync_queue WHERE status='pending' AND attempts < max_attempts"
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0
