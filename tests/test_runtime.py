from __future__ import annotations

import pytest

from agent.config.loader import Config
from agent.runtime.runtime import Runtime
from agent.state.store import MemoryStateStore


class FakeLLM:
    """Fake LLM that returns preconfigured responses."""

    def __init__(self, responses: list[dict] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[tuple[list[dict], dict]] = []

    def enqueue(self, response: dict) -> None:
        self._responses.append(response)

    async def ainvoke(self, messages: list[dict], response_format: dict) -> dict:
        self.calls.append((messages, response_format))
        if self._responses:
            return self._responses.pop(0)
        return {"actions": []}


class FakeOutput:
    """Fake OutputHandler that records calls."""

    def __init__(self) -> None:
        self.action_starts: list[str] = []
        self.displayed: list[str] = []

    def on_llm_response(self, response: dict) -> None:
        pass

    def on_system_prompt(self, prompt: str) -> None:
        pass

    def on_state_update(self, state: dict) -> None:
        pass

    def on_action_start(self, action_type: str) -> None:
        self.action_starts.append(action_type)

    def display(self, content: str) -> None:
        self.displayed.append(content)


def _load_config() -> Config:
    return Config.load("configs/example_config.json")


@pytest.fixture
def store() -> MemoryStateStore:
    return MemoryStateStore()


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def output() -> FakeOutput:
    return FakeOutput()


@pytest.fixture
def runtime(store: MemoryStateStore, llm: FakeLLM, output: FakeOutput) -> Runtime:
    return Runtime(_load_config(), store, llm, output)


@pytest.mark.asyncio
async def test_start_session(runtime: Runtime, store: MemoryStateStore) -> None:
    sid = await runtime.start_session()
    state = await store.get(sid)
    assert state.session_id == sid


@pytest.mark.asyncio
async def test_end_session(runtime: Runtime, store: MemoryStateStore) -> None:
    sid = await runtime.start_session()
    await runtime.end_session(sid)
    with pytest.raises(KeyError):
        await store.get(sid)


@pytest.mark.asyncio
async def test_process_message_saves_user_message(
    runtime: Runtime, store: MemoryStateStore, llm: FakeLLM
) -> None:
    sid = await runtime.start_session()
    await runtime.process_message(sid, "Hello")

    state = await store.get(sid)
    # greeting (assistant) + user message
    assert len(state.messages) == 2
    assert state.messages[0].role == "assistant"  # greeting
    assert state.messages[1].role == "user"
    assert state.messages[1].content == "Hello"


@pytest.mark.asyncio
async def test_process_message_calls_llm(
    runtime: Runtime, llm: FakeLLM
) -> None:
    sid = await runtime.start_session()
    await runtime.process_message(sid, "Hi")

    assert len(llm.calls) == 1
    messages, response_format = llm.calls[0]
    # system prompt + user message
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "Hi"
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True


@pytest.mark.asyncio
async def test_process_message_executes_send_message(
    runtime: Runtime, store: MemoryStateStore, llm: FakeLLM, output: FakeOutput
) -> None:
    llm.enqueue({"actions": [{"type": "send_message", "payload": {"content": "Hey there!"}}]})
    sid = await runtime.start_session()
    await runtime.process_message(sid, "Hi")

    assert output.action_starts == ["send_message"]
    # greeting + LLM response
    assert output.displayed[0] == _load_config().agent.greeting
    assert output.displayed[1] == "Hey there!"

    state = await store.get(sid)
    # greeting + user + assistant
    assert len(state.messages) == 3
    assert state.messages[0].role == "assistant"  # greeting
    assert state.messages[1].role == "user"
    assert state.messages[2].role == "assistant"
    assert state.messages[2].content == "Hey there!"


@pytest.mark.asyncio
async def test_process_message_executes_collect_field(
    runtime: Runtime, store: MemoryStateStore, llm: FakeLLM, output: FakeOutput
) -> None:
    llm.enqueue({
        "actions": [
            {"type": "collect_field", "payload": {"field": "email", "value": "a@b.com", "confidence": 0.9}},
        ]
    })
    sid = await runtime.start_session()
    await runtime.process_message(sid, "my email is a@b.com")

    state = await store.get(sid)
    assert "email" in state.collected_fields
    assert state.collected_fields["email"].value == "a@b.com"
    # only greeting displayed (collect_field returns None)
    assert len(output.displayed) == 1


@pytest.mark.asyncio
async def test_process_message_executes_escalate(
    runtime: Runtime, store: MemoryStateStore, llm: FakeLLM, output: FakeOutput
) -> None:
    llm.enqueue({"actions": [{"type": "escalate", "payload": {"reason": "user angry"}}]})
    sid = await runtime.start_session()
    await runtime.process_message(sid, "I want a human!")

    state = await store.get(sid)
    assert state.escalated is True
    assert state.escalation_reason == "user angry"
    # escalate action doesn't display — the LLM sends a message before escalating
    assert len(output.displayed) == 1  # only greeting


@pytest.mark.asyncio
async def test_process_message_multiple_actions(
    runtime: Runtime, store: MemoryStateStore, llm: FakeLLM, output: FakeOutput
) -> None:
    llm.enqueue({
        "actions": [
            {"type": "collect_field", "payload": {"field": "name", "value": "Alice", "confidence": 0.95}},
            {"type": "send_message", "payload": {"content": "Thanks Alice!"}},
        ]
    })
    sid = await runtime.start_session()
    await runtime.process_message(sid, "I'm Alice")

    assert output.action_starts == ["collect_field", "send_message"]
    # greeting + "Thanks Alice!"
    assert output.displayed[0] == _load_config().agent.greeting
    assert output.displayed[1] == "Thanks Alice!"

    state = await store.get(sid)
    assert "name" in state.collected_fields


@pytest.mark.asyncio
async def test_process_message_empty_actions(
    runtime: Runtime, store: MemoryStateStore, llm: FakeLLM, output: FakeOutput
) -> None:
    llm.enqueue({"actions": []})
    sid = await runtime.start_session()
    await runtime.process_message(sid, "Hello")

    assert output.action_starts == []
    # only greeting displayed
    assert len(output.displayed) == 1


@pytest.mark.asyncio
async def test_process_message_missing_actions_key(
    runtime: Runtime, llm: FakeLLM, output: FakeOutput
) -> None:
    llm.enqueue({"oops": "no actions"})
    sid = await runtime.start_session()
    await runtime.process_message(sid, "Hello")

    assert output.action_starts == []
    # only greeting displayed
    assert len(output.displayed) == 1


@pytest.mark.asyncio
async def test_collect_field_rejected_below_confidence(
    runtime: Runtime, store: MemoryStateStore, llm: FakeLLM, output: FakeOutput
) -> None:
    # example_config has confidence_threshold=0.7; 0.4 is below it
    llm.enqueue({
        "actions": [
            {"type": "collect_field", "payload": {"field": "email", "value": "a@b.com", "confidence": 0.4}},
        ]
    })
    sid = await runtime.start_session()
    await runtime.process_message(sid, "maybe a@b.com")

    state = await store.get(sid)
    assert "email" not in state.collected_fields
    # rejection message is displayed
    assert any("rejected" in msg for msg in output.displayed)


@pytest.mark.asyncio
async def test_state_persisted_after_processing(
    runtime: Runtime, store: MemoryStateStore, llm: FakeLLM
) -> None:
    llm.enqueue({
        "actions": [
            {"type": "update_state", "payload": {"total_attempts": 5, "steps": None}},
        ]
    })
    sid = await runtime.start_session()
    await runtime.process_message(sid, "test")

    state = await store.get(sid)
    assert state.total_attempts == 5
