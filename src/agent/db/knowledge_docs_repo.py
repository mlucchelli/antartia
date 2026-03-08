from __future__ import annotations

from datetime import datetime, timezone

from agent.db.database import Database


class KnowledgeDocsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(self, file_name: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        async with self._db.conn.execute(
            """
            INSERT INTO knowledge_docs (file_name, status, created_at)
            VALUES (?, 'pending', ?)
            ON CONFLICT(file_name) DO UPDATE SET status='pending', error=NULL, created_at=?
            """,
            (file_name, now, now),
        ) as cur:
            row_id = cur.lastrowid
        await self._db.conn.commit()
        return {"id": row_id, "file_name": file_name, "status": "pending"}

    async def mark_indexed(self, file_name: str, chunk_count: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            """
            UPDATE knowledge_docs
            SET status='indexed', chunk_count=?, indexed_at=?, error=NULL
            WHERE file_name=?
            """,
            (chunk_count, now, file_name),
        )
        await self._db.conn.commit()

    async def mark_failed(self, file_name: str, error: str) -> None:
        await self._db.conn.execute(
            "UPDATE knowledge_docs SET status='failed', error=? WHERE file_name=?",
            (error, file_name),
        )
        await self._db.conn.commit()

    async def clear_all(self) -> None:
        await self._db.conn.execute("DELETE FROM knowledge_docs")
        await self._db.conn.commit()

    async def get_all(self, status: str | None = None) -> list[dict]:
        if status:
            async with self._db.conn.execute(
                "SELECT * FROM knowledge_docs WHERE status=? ORDER BY created_at DESC",
                (status,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self._db.conn.execute(
                "SELECT * FROM knowledge_docs ORDER BY created_at DESC"
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]
