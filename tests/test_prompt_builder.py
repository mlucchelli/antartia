import json

from agent.config.loader import Config
from agent.llm.prompt_builder import PromptBuilder
from agent.models.state import ConversationState


def _load_config() -> Config:
    return Config.load("configs/example_config.json")


def _make_state(session_id: str = "test-session") -> ConversationState:
    return ConversationState(session_id=session_id)


def test_all_placeholders_replaced() -> None:
    config = _load_config()
    builder = PromptBuilder(config)
    state = _make_state()

    prompt = builder.build(state)

    # No unresolved placeholders should remain
    assert "{agent.name}" not in prompt
    assert "{personality.tone}" not in prompt
    assert "{personality.style}" not in prompt
    assert "{personality.formality}" not in prompt
    assert "{personality.emoji_usage}" not in prompt
    assert "{fields}" not in prompt
    assert "{actions}" not in prompt
    assert "{agent.greeting}" not in prompt
    assert "{personality.prompt}" not in prompt
    assert "{steps}" not in prompt

    # Actual values present
    assert "Customer Service Agent" in prompt
    assert "friendly" in prompt
    assert "conversational" in prompt


def test_state_context_appended() -> None:
    config = _load_config()
    builder = PromptBuilder(config)
    state = _make_state(session_id="sess-42")
    state.collect_field("email", "a@b.com", 0.9)

    prompt = builder.build(state)

    assert "sess-42" in prompt
    assert "a@b.com" in prompt
    assert "Escalated: False" in prompt


def test_state_context_reflects_escalation() -> None:
    config = _load_config()
    builder = PromptBuilder(config)
    state = _make_state()
    state.set_escalation("user frustrated")

    prompt = builder.build(state)

    assert "Escalated: True" in prompt


def test_fields_json_in_prompt() -> None:
    config = _load_config()
    builder = PromptBuilder(config)
    state = _make_state()

    prompt = builder.build(state)

    # The prompt should contain field names from config
    assert '"name"' in prompt
    assert '"email"' in prompt
    assert '"phone"' in prompt
    assert '"address"' in prompt


def test_actions_json_in_prompt() -> None:
    config = _load_config()
    builder = PromptBuilder(config)
    state = _make_state()

    prompt = builder.build(state)

    assert '"send_message"' in prompt
    assert '"collect_field"' in prompt
    assert '"escalate"' in prompt


def test_dynamic_sections_appended() -> None:
    config = _load_config()
    builder = PromptBuilder(config)
    state = _make_state()

    prompt = builder.build(state)

    assert "emoji_usage is true" in prompt
    assert "validation patterns" in prompt
    assert "escalation triggers" in prompt


def test_greeting_instructions_in_prompt() -> None:
    config = _load_config()
    builder = PromptBuilder(config)
    state = _make_state()

    prompt = builder.build(state)

    assert "Hello! I'm here to help" in prompt
    assert "NOT** greet again" in prompt


def test_personality_prompt_in_prompt() -> None:
    config = _load_config()
    builder = PromptBuilder(config)
    state = _make_state()

    prompt = builder.build(state)

    assert "warm and approachable" in prompt


def test_steps_in_prompt() -> None:
    config = _load_config()
    builder = PromptBuilder(config)
    state = _make_state()
    from agent.models.state import StepInfo
    state.steps = [
        StepInfo(step_key="greeting", status="completed"),
        StepInfo(step_key="collect_name", status="in_progress"),
        StepInfo(step_key="collect_email", status="pending"),
    ]

    prompt = builder.build(state)

    assert "greeting: completed" in prompt
    assert "collect_name: in_progress" in prompt
    assert "collect_email: pending" in prompt
    assert "update_state" in prompt
