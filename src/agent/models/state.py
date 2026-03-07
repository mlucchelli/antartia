from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Message(BaseModel):
    role: str
    content: str
    timestamp: datetime = Field(default_factory=_now)


class FieldData(BaseModel):
    value: Any
    confidence: float
    validation_status: str = "valid"
    collected_at: datetime = Field(default_factory=_now)


class StepInfo(BaseModel):
    step_key: str
    status: str = "pending"


class ConversationState(BaseModel):
    session_id: str
    started_at: datetime = Field(default_factory=_now)
    last_activity: datetime = Field(default_factory=_now)
    messages: list[Message] = Field(default_factory=list)
    collected_fields: dict[str, FieldData] = Field(default_factory=dict)
    total_attempts: int = 0
    escalated: bool = False
    escalation_reason: str | None = None
    steps: list[StepInfo] = Field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        self.messages.append(Message(role=role, content=content))
        self.last_activity = _now()

    def collect_field(self, field: str, value: Any, confidence: float) -> None:
        self.collected_fields[field] = FieldData(value=value, confidence=confidence)
        self.last_activity = _now()

    def set_escalation(self, reason: str) -> None:
        self.escalated = True
        self.escalation_reason = reason
        self.last_activity = _now()
