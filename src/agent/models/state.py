from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Message(BaseModel):
    role: str
    content: str
    timestamp: datetime = Field(default_factory=_now)


class ConversationState(BaseModel):
    session_id: str
    started_at: datetime = Field(default_factory=_now)
    last_activity: datetime = Field(default_factory=_now)
    messages: list[Message] = Field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        self.messages.append(Message(role=role, content=content))
        self.last_activity = _now()
