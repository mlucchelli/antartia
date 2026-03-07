from __future__ import annotations

import logging

from agent.models.actions import (
    Action,
    CollectFieldAction,
    EscalateAction,
    SendMessageAction,
    UpdateStateAction,
)

logger = logging.getLogger(__name__)

ACTION_REGISTRY: dict[str, type[Action]] = {
    "send_message": SendMessageAction,
    "collect_field": CollectFieldAction,
    "update_state": UpdateStateAction,
    "escalate": EscalateAction,
}


class ActionParser:
    def __init__(self, confidence_threshold: float = 0.0) -> None:
        self._confidence_threshold = confidence_threshold

    def parse(self, raw_actions: list[dict]) -> list[Action]:
        actions: list[Action] = []
        for raw in raw_actions:
            action_type = raw.get("type")
            if action_type not in ACTION_REGISTRY:
                logger.warning("Unknown action type: %s — skipping", action_type)
                continue
            cls = ACTION_REGISTRY[action_type]
            if action_type == "collect_field":
                action = CollectFieldAction.model_validate(
                    {**raw, "confidence_threshold": self._confidence_threshold}
                )
            else:
                action = cls.model_validate(raw)
            actions.append(action)
        return actions
