import pytest
from pydantic import ValidationError

from agent.models.actions import (
    CollectFieldAction,
    EscalateAction,
    SendMessageAction,
    UpdateStateAction,
)
from agent.runtime.parser import ActionParser


@pytest.fixture
def parser() -> ActionParser:
    return ActionParser(confidence_threshold=0.7)


def test_parse_send_message(parser: ActionParser) -> None:
    raw = [{"type": "send_message", "payload": {"content": "Hello!"}}]
    actions = parser.parse(raw)
    assert len(actions) == 1
    assert isinstance(actions[0], SendMessageAction)
    assert actions[0].payload == {"content": "Hello!"}


def test_parse_collect_field(parser: ActionParser) -> None:
    raw = [{"type": "collect_field", "payload": {"field": "email", "value": "a@b.com", "confidence": 0.9}}]
    actions = parser.parse(raw)
    assert len(actions) == 1
    assert isinstance(actions[0], CollectFieldAction)
    assert actions[0].confidence_threshold == 0.7


def test_parse_collect_field_injects_threshold() -> None:
    parser = ActionParser(confidence_threshold=0.9)
    raw = [{"type": "collect_field", "payload": {"field": "name", "value": "Alice", "confidence": 0.8}}]
    actions = parser.parse(raw)
    assert actions[0].confidence_threshold == 0.9


def test_parse_update_state(parser: ActionParser) -> None:
    raw = [{"type": "update_state", "payload": {"total_attempts": 2, "steps": None}}]
    actions = parser.parse(raw)
    assert len(actions) == 1
    assert isinstance(actions[0], UpdateStateAction)


def test_parse_escalate(parser: ActionParser) -> None:
    raw = [{"type": "escalate", "payload": {"reason": "user frustrated"}}]
    actions = parser.parse(raw)
    assert len(actions) == 1
    assert isinstance(actions[0], EscalateAction)


def test_parse_multiple_actions(parser: ActionParser) -> None:
    raw = [
        {"type": "collect_field", "payload": {"field": "name", "value": "Alice", "confidence": 0.95}},
        {"type": "send_message", "payload": {"content": "Got it!"}},
    ]
    actions = parser.parse(raw)
    assert len(actions) == 2
    assert isinstance(actions[0], CollectFieldAction)
    assert isinstance(actions[1], SendMessageAction)


def test_unknown_action_type_skipped(parser: ActionParser) -> None:
    raw = [
        {"type": "unknown_action", "payload": {}},
        {"type": "send_message", "payload": {"content": "Hi"}},
    ]
    actions = parser.parse(raw)
    assert len(actions) == 1
    assert isinstance(actions[0], SendMessageAction)


def test_missing_payload_raises_validation_error(parser: ActionParser) -> None:
    raw = [{"type": "send_message"}]  # missing payload
    with pytest.raises(ValidationError):
        parser.parse(raw)
