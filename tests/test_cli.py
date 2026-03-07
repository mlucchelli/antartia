from __future__ import annotations

import pytest

from agent.cli.app import CLI
from agent.config.loader import Config
from agent.runtime.runtime import Runtime
from agent.state.store import MemoryStateStore


class FakeLLM:
    def __init__(self) -> None:
        self._responses: list[dict] = []

    def enqueue(self, response: dict) -> None:
        self._responses.append(response)

    async def ainvoke(self, messages: list[dict], response_format: dict) -> dict:
        if self._responses:
            return self._responses.pop(0)
        return {"actions": []}


def _load_config() -> Config:
    return Config.load("configs/example_config.json")


def _make_runtime(
    llm: FakeLLM, cli: CLI
) -> tuple[Runtime, MemoryStateStore]:
    config = _load_config()
    store = MemoryStateStore()
    runtime = Runtime(config, store, llm, output=cli)
    return runtime, store


def test_cli_implements_output_handler() -> None:
    cli = CLI(config=_load_config())
    assert callable(cli.on_action_start)
    assert callable(cli.display)


@pytest.mark.asyncio
async def test_greeting_displayed_on_start() -> None:
    config = _load_config()
    cli = CLI(config=config)
    llm = FakeLLM()

    displayed: list[str] = []
    cli.display = lambda content: displayed.append(content)  # type: ignore[assignment]
    cli.get_user_input = lambda: None  # type: ignore[assignment]

    runtime, store = _make_runtime(llm, cli)
    await cli.run(runtime)

    assert any("Hello! I'm here to help" in d for d in displayed)


@pytest.mark.asyncio
async def test_greeting_in_state_history() -> None:
    config = _load_config()
    cli = CLI(config=config)
    llm = FakeLLM()

    cli.display = lambda content: None  # type: ignore[assignment]
    cli.get_user_input = lambda: None  # type: ignore[assignment]

    runtime, store = _make_runtime(llm, cli)
    await cli.run(runtime)

    # Session persists (no explicit end_session call)
    assert len(store._states) == 1
    # Greeting is in the session's message history
    state = list(store._states.values())[0]
    assert any(m.role == "assistant" for m in state.messages)


@pytest.mark.asyncio
async def test_multi_turn_conversation() -> None:
    config = _load_config()
    cli = CLI(config=config)
    llm = FakeLLM()

    llm.enqueue({"actions": [{"type": "send_message", "payload": {"content": "What's your name?"}}]})
    llm.enqueue({"actions": [{"type": "send_message", "payload": {"content": "Nice to meet you!"}}]})

    displayed: list[str] = []
    cli.display = lambda content: displayed.append(content)  # type: ignore[assignment]

    inputs = iter(["Alice", "Bob", "quit"])
    cli.get_user_input = lambda: next(inputs)  # type: ignore[assignment]

    runtime, _ = _make_runtime(llm, cli)
    await cli.run(runtime)

    # Greeting + 2 LLM responses
    assert len(displayed) == 3
    assert "Hello! I'm here to help" in displayed[0]  # greeting
    assert "What's your name?" in displayed[1]
    assert "Nice to meet you!" in displayed[2]


@pytest.mark.asyncio
async def test_empty_input_skipped() -> None:
    config = _load_config()
    cli = CLI(config=config)
    llm = FakeLLM()

    llm.enqueue({"actions": [{"type": "send_message", "payload": {"content": "Got it"}}]})

    displayed: list[str] = []
    cli.display = lambda content: displayed.append(content)  # type: ignore[assignment]

    inputs = iter(["", "  ", "hello", "exit"])
    cli.get_user_input = lambda: next(inputs)  # type: ignore[assignment]

    runtime, _ = _make_runtime(llm, cli)
    await cli.run(runtime)

    # Greeting + 1 response (empty inputs skipped, only "hello" processed)
    assert len(displayed) == 2


@pytest.mark.asyncio
async def test_quit_exits() -> None:
    config = _load_config()
    cli = CLI(config=config)
    llm = FakeLLM()

    cli.display = lambda content: None  # type: ignore[assignment]

    inputs = iter(["quit"])
    cli.get_user_input = lambda: next(inputs)  # type: ignore[assignment]

    runtime, _ = _make_runtime(llm, cli)
    await cli.run(runtime)  # should not hang


@pytest.mark.asyncio
async def test_exit_exits() -> None:
    config = _load_config()
    cli = CLI(config=config)
    llm = FakeLLM()

    cli.display = lambda content: None  # type: ignore[assignment]

    inputs = iter(["exit"])
    cli.get_user_input = lambda: next(inputs)  # type: ignore[assignment]

    runtime, _ = _make_runtime(llm, cli)
    await cli.run(runtime)  # should not hang


@pytest.mark.asyncio
async def test_ctrl_c_exits() -> None:
    config = _load_config()
    cli = CLI(config=config)
    llm = FakeLLM()

    cli.display = lambda content: None  # type: ignore[assignment]
    cli.get_user_input = lambda: None  # type: ignore[assignment]

    runtime, _ = _make_runtime(llm, cli)
    await cli.run(runtime)  # should not hang
