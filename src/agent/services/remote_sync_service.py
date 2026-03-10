from __future__ import annotations

import json
import logging

import httpx

from agent.config.loader import Config

logger = logging.getLogger(__name__)


class RemoteSyncService:
    def __init__(self, config: Config) -> None:
        self._base_url = config.remote_sync.base_url
        self._api_key  = config.remote_sync.api_key

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def push(self, path: str, payload: dict) -> dict:
        """POST JSON payload. Returns {"ok": True} or {"ok": False, "error": str}."""
        headers = {**self._headers(), "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(f"{self._base_url}{path}", json=payload, headers=headers)
                r.raise_for_status()
            return {"ok": True}
        except Exception as exc:
            logger.error("RemoteSyncService.push %s failed: %s", path, exc)
            return {"ok": False, "error": str(exc)}

    async def push_photo(self, file_path: str, file_name: str, metadata: dict) -> dict:
        """Multipart POST for /api/photos. Returns {"ok": True} or {"ok": False, "error": str}."""
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
            return {"ok": True}
        except Exception as exc:
            logger.error("RemoteSyncService.push_photo %s failed: %s", file_name, exc)
            return {"ok": False, "error": str(exc)}
