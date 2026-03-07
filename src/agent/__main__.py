from __future__ import annotations

import argparse
import asyncio
import logging

from agent.cli.app import CLI
from agent.config.loader import Config
from agent.runtime.runtime import Runtime
from agent.state.file_store import FileStateStore


class TestLLM:
    """Test LLM that returns canned responses for conversation flow testing."""

    async def ainvoke(self, messages: list[dict], response_format: dict) -> dict:
        # Find the last user message
        last_user = ""
        for msg in reversed(messages):
            if msg["role"] == "user":
                last_user = msg["content"]
                break

        return {
            "actions": [
                {
                    "type": "send_message",
                    "payload": {"content": f"[test] I heard: {last_user}"},
                }
            ]
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Conversational Agent")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--test", action="store_true", help="Use test LLM (no API calls)")
    parser.add_argument("--debug", action="store_true", help="Show raw LLM responses")
    parser.add_argument("--session", default=None, help="Resume existing session by ID")
    args = parser.parse_args()

    # Silence noisy HTTP transport logs
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = Config.load(args.config)
    store = FileStateStore("session_states")

    if args.test:
        llm = TestLLM()
    else:
        from agent.llm.openrouter import OpenRouterClient

        llm = OpenRouterClient(config)

    cli = CLI(config=config, debug=args.debug)
    runtime = Runtime(config, store, llm, output=cli)

    if args.session:
        asyncio.run(_resume(cli, runtime, args.session))
    else:
        asyncio.run(cli.run(runtime))


async def _resume(cli: CLI, runtime: Runtime, session_id: str) -> None:
    """Resume an existing session — skip start_session, go straight to chat loop."""
    cli._session_id = session_id
    state = await runtime._store.get(session_id)

    cli._setup_terminal()
    cli._render_banner()
    cli.on_state_update(state.model_dump())

    # Show last assistant message for context
    for msg in reversed(state.messages):
        if msg.role == "assistant":
            cli.display(msg.content)
            break

    cli._render_status_bar()

    try:
        while True:
            user_input = cli._get_input()
            if user_input is None or user_input.strip().lower() in ("quit", "exit"):
                break
            if not user_input.strip():
                continue

            cli._console.print(f"[bold yellow]❯ [/bold yellow]{user_input}")
            async with cli._thinking():
                await runtime.process_message(session_id, user_input)
    finally:
        cli._teardown_terminal()
        cli._console.print("[dim]Goodbye![/dim]")


if __name__ == "__main__":
    main()
