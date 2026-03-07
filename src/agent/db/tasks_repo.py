from __future__ import annotations

import json
from datetime import datetime, timezone

from agent.db.database import Database

VALID_TASK_TYPES = {
    "process_location",
    "scan_photo_inbox",
    "process_photo",
    "fetch_weather",
    "publish_daily_progress",
    "publish_route_snapshot",
    "upload_image",
    "publish_agent_message",
    "publish_weather_snapshot",
}


class TasksRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(self, type: str, payload: dict, priority: int = 1) -> dict:
        created_at = datetime.now(timezone.utc).isoformat()
        async with self._db.conn.execute(
            """INSERT INTO tasks (type, payload, status, priority, created_at)
               VALUES (?, ?, 'pending', ?, ?)""",
            (type, json.dumps(payload), priority, created_at),
        ) as cur:
            row_id = cur.lastrowid
        await self._db.conn.commit()
        return {"id": row_id, "type": type, "payload": payload,
                "status": "pending", "priority": priority, "created_at": created_at}

    async def claim_next(self) -> dict | None:
        """Atomically claim the highest-priority pending task."""
        async with self._db.conn.execute(
            """SELECT * FROM tasks WHERE status = 'pending'
               ORDER BY priority DESC, created_at ASC LIMIT 1"""
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        started_at = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            "UPDATE tasks SET status = 'running', started_at = ? WHERE id = ? AND status = 'pending'",
            (started_at, row["id"]),
        )
        await self._db.conn.commit()
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        result["started_at"] = started_at
        result["status"] = "running"
        return result

    async def complete(self, task_id: int) -> None:
        executed_at = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            "UPDATE tasks SET status = 'completed', executed_at = ? WHERE id = ?",
            (executed_at, task_id),
        )
        await self._db.conn.commit()

    async def fail(self, task_id: int, error_message: str) -> None:
        executed_at = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            "UPDATE tasks SET status = 'failed', executed_at = ?, error_message = ? WHERE id = ?",
            (executed_at, error_message, task_id),
        )
        await self._db.conn.commit()

    async def count_pending(self) -> int:
        async with self._db.conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'pending'"
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def get_recent(self, limit: int = 10) -> list[dict]:
        async with self._db.conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            result.append(d)
        return result
