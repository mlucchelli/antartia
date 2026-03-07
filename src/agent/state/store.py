from __future__ import annotations

import uuid
from typing import Protocol

from agent.models.state import ConversationState


class StateStore(Protocol):
    async def create(self, session_id: str | None = None) -> ConversationState: ...
    async def get(self, session_id: str) -> ConversationState: ...
    async def save(self, state: ConversationState) -> None: ...
    async def delete(self, session_id: str) -> None: ...


class MemoryStateStore:
    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}

    async def create(self, session_id: str | None = None) -> ConversationState:
        sid = session_id or uuid.uuid4().hex
        if sid in self._states:
            raise ValueError(f"Session already exists: {sid}")
        state = ConversationState(session_id=sid)
        self._states[sid] = state.model_copy(deep=True)
        return state

    async def get(self, session_id: str) -> ConversationState:
        try:
            return self._states[session_id].model_copy(deep=True)
        except KeyError:
            raise KeyError(f"Session not found: {session_id}")

    async def save(self, state: ConversationState) -> None:
        self._states[state.session_id] = state.model_copy(deep=True)

    async def delete(self, session_id: str) -> None:
        try:
            del self._states[session_id]
        except KeyError:
            raise KeyError(f"Session not found: {session_id}")
