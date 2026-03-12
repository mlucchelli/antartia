from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx

from agent.config.loader import Config

if TYPE_CHECKING:
    from agent.db.database import Database
    from agent.runtime.protocols import OutputHandler

logger = logging.getLogger(__name__)


class RemoteSyncService:
    def __init__(
        self,
        config: Config,
        output: "OutputHandler | None" = None,
        db: "Database | None" = None,
    ) -> None:
        self._base_url = config.remote_sync.base_url
        self._api_key  = config.remote_sync.api_key
        self._output   = output
        self._db       = db

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _notify_start(self) -> None:
        if self._output:
            try:
                self._output.on_sync_start()
            except Exception:
                pass

    def _notify_end(self) -> None:
        if self._output:
            try:
                self._output.on_sync_end()
            except Exception:
                pass

    async def push(self, path: str, payload: dict) -> dict:
        """POST JSON payload. On failure queues for retry if DB available.
        Returns {"ok": True}, {"ok": True, "queued": True}, or {"ok": False, "error": str}.
        """
        headers = {**self._headers(), "Content-Type": "application/json"}
        self._notify_start()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(f"{self._base_url}{path}", json=payload, headers=headers)
                r.raise_for_status()
            logger.info("sync OK  %s", path)
            return {"ok": True}
        except Exception as exc:
            error = str(exc)
            logger.warning("sync FAIL %s — %s", path, error)
            if self._db:
                await self._enqueue(path, payload, error)
                return {"ok": True, "queued": True}
            return {"ok": False, "error": error}
        finally:
            self._notify_end()

    async def push_photo(self, file_path: str, file_name: str, metadata: dict) -> dict:
        """Multipart POST for /api/photos. On failure queues for retry if DB available."""
        self._notify_start()
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            files = {"file": (file_name, file_bytes, "image/jpeg")}
            data  = {"metadata": json.dumps(metadata, ensure_ascii=False)}
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    f"{self._base_url}/api/photos",
                    headers=self._headers(),
                    files=files,
                    data=data,
                )
                r.raise_for_status()
            file_url = r.json().get("file_url")
            logger.info("sync OK  /api/photos (%s) → %s", file_name, file_url)
            return {"ok": True, "file_url": file_url}
        except httpx.HTTPStatusError as exc:
            error = str(exc)
            body = exc.response.text[:500] if exc.response.text else "(empty)"
            logger.warning("sync FAIL /api/photos (%s) — %s | response body: %s", file_name, error, body)
            if self._db:
                await self._enqueue_photo(file_path, file_name, metadata, error)
                return {"ok": True, "queued": True}
            return {"ok": False, "error": error}
        except Exception as exc:
            error = str(exc)
            logger.warning("sync FAIL /api/photos (%s) — %s", file_name, error)
            if self._db:
                await self._enqueue_photo(file_path, file_name, metadata, error)
                return {"ok": True, "queued": True}
            return {"ok": False, "error": error}
        finally:
            self._notify_end()

    async def _enqueue_photo(self, file_path: str, file_name: str, metadata: dict, error: str) -> None:
        from agent.db.sync_queue_repo import SyncQueueRepository
        repo = SyncQueueRepository(self._db)
        metadata_json = json.dumps({"file_name": file_name, **metadata}, ensure_ascii=False)
        item_id = await repo.enqueue_photo(file_path, file_name, metadata_json)
        await repo.record_attempt(item_id, error)
        pending = await repo.count_pending()
        logger.warning("sync queued photo %s (id=%s) — %d item(s) pending retry", file_name, item_id, pending)

    async def retry_pending(self) -> None:
        """Retry all pending queued items. Called by the scheduler each tick."""
        if not self._db:
            return
        from agent.db.sync_queue_repo import SyncQueueRepository
        repo = SyncQueueRepository(self._db)
        pending = await repo.get_pending()
        if not pending:
            return
        logger.info("sync retry — %d pending item(s)", len(pending))
        json_headers = {**self._headers(), "Content-Type": "application/json"}
        for item in pending:
            path    = item["path"]
            attempt = item["attempts"] + 1
            try:
                if item.get("type") == "photo":
                    meta = json.loads(item["payload_json"])
                    file_name = meta.get("file_name") or item["file_path"].split("/")[-1]
                    with open(item["file_path"], "rb") as f:
                        file_bytes = f.read()
                    files = {"file": (file_name, file_bytes, "image/jpeg")}
                    data  = {"metadata": json.dumps(meta, ensure_ascii=False)}
                    async with httpx.AsyncClient(timeout=60) as client:
                        r = await client.post(
                            f"{self._base_url}/api/photos",
                            headers=self._headers(),
                            files=files,
                            data=data,
                        )
                        r.raise_for_status()
                else:
                    payload = json.loads(item["payload_json"])
                    async with httpx.AsyncClient(timeout=30) as client:
                        r = await client.post(f"{self._base_url}{path}", json=payload, headers=json_headers)
                        r.raise_for_status()
                await repo.mark_sent(item["id"])
                logger.info("sync retry OK  %s (attempt %d)", path, attempt)
                if item.get("type") == "photo" and self._db:
                    from agent.db.tasks_repo import TasksRepository
                    await TasksRepository(self._db).insert("publish_daily_progress", {}, source="sync_retry")
            except httpx.HTTPStatusError as exc:
                error = str(exc)
                body = exc.response.text[:500] if exc.response.text else "(empty)"
                await repo.record_attempt(item["id"], error)
                remaining = item["max_attempts"] - attempt
                if remaining > 0:
                    logger.warning("sync retry FAIL %s (attempt %d, %d left) — %s | response body: %s", path, attempt, remaining, error, body)
                else:
                    logger.error("sync retry GIVE UP %s after %d attempts — %s | response body: %s", path, attempt, error, body)
            except Exception as exc:
                error = str(exc)
                await repo.record_attempt(item["id"], error)
                remaining = item["max_attempts"] - attempt
                if remaining > 0:
                    logger.warning("sync retry FAIL %s (attempt %d, %d left) — %s", path, attempt, remaining, error)
                else:
                    logger.error("sync retry GIVE UP %s after %d attempts — %s", path, attempt, error)

    async def _enqueue(self, path: str, payload: dict, error: str) -> None:
        from agent.db.sync_queue_repo import SyncQueueRepository
        repo = SyncQueueRepository(self._db)
        item_id = await repo.enqueue(path, json.dumps(payload, ensure_ascii=False))
        await repo.record_attempt(item_id, error)
        pending = await repo.count_pending()
        logger.warning("sync queued %s (id=%s) — %d item(s) pending retry", path, item_id, pending)
