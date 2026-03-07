from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from agent.models.state import ConversationState, StepInfo


class Action(BaseModel, ABC):
    type: str
    payload: dict

    @abstractmethod
    async def execute(self, state: ConversationState) -> str | None: ...


class SendMessagePayload(BaseModel):
    content: str


class SendMessageAction(Action):
    type: str = "send_message"

    async def execute(self, state: ConversationState) -> str | None:
        p = SendMessagePayload.model_validate(self.payload)
        state.add_message("assistant", p.content)
        return p.content


class CollectFieldPayload(BaseModel):
    field: str
    value: str
    confidence: float


class CollectFieldAction(Action):
    type: str = "collect_field"
    confidence_threshold: float = 0.0

    async def execute(self, state: ConversationState) -> str | None:
        p = CollectFieldPayload.model_validate(self.payload)
        if p.confidence < self.confidence_threshold:
            return f"[rejected: {p.field} confidence {p.confidence:.0%} below threshold]"
        state.collect_field(p.field, p.value, p.confidence)
        return None


class UpdateStatePayload(BaseModel):
    steps: list[StepInfo] | None = None
    total_attempts: int | None = None


class UpdateStateAction(Action):
    type: str = "update_state"

    async def execute(self, state: ConversationState) -> str | None:
        p = UpdateStatePayload.model_validate(self.payload)
        if p.steps is not None:
            state.steps = p.steps
        if p.total_attempts is not None:
            state.total_attempts = p.total_attempts
        return None


class EscalatePayload(BaseModel):
    reason: str


class EscalateAction(Action):
    type: str = "escalate"

    async def execute(self, state: ConversationState) -> str | None:
        p = EscalatePayload.model_validate(self.payload)
        state.set_escalation(p.reason)
        return None
