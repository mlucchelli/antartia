from __future__ import annotations

import uuid
from pathlib import Path

from agent.models.state import ConversationState


class FileStateStore:
    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    async def create(self, session_id: str | None = None) -> ConversationState:
        sid = session_id or uuid.uuid4().hex
        path = self._path(sid)
        if path.exists():
            raise ValueError(f"Session already exists: {sid}")
        state = ConversationState(session_id=sid)
        path.write_text(state.model_dump_json(indent=2))
        return state

    async def get(self, session_id: str) -> ConversationState:
        path = self._path(session_id)
        if not path.exists():
            raise KeyError(f"Session not found: {session_id}")
        return ConversationState.model_validate_json(path.read_text())

    async def save(self, state: ConversationState) -> None:
        path = self._path(state.session_id)
        path.write_text(state.model_dump_json(indent=2))

    async def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        if not path.exists():
            raise KeyError(f"Session not found: {session_id}")
        path.unlink()
