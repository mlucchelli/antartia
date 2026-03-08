from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

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

    log_file = Path(args.config).parent.parent / "data" / "agent.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
        handlers=[
            logging.FileHandler(log_file),
        ],
    )
    # Silence noisy HTTP transport logs
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = Config.load(args.config)
    store = FileStateStore("session_states")

    if args.test:
        llm = TestLLM()
    elif config.agent.provider == "openrouter":
        from agent.llm.openrouter import OpenRouterClient

        llm = OpenRouterClient(config)
    else:
        from agent.llm.ollama import OllamaClient

        llm = OllamaClient(config)

    cli = CLI(config=config, debug=args.debug)

    if args.session:
        asyncio.run(_run(config, store, llm, cli, session_id=args.session))
    else:
        asyncio.run(_run(config, store, llm, cli))


async def _run(config, store, llm, cli, session_id: str | None = None) -> None:
    from agent.db.database import Database
    from agent.http.server import start_http_server
    from agent.runtime.scheduler import Scheduler
    from agent.runtime.semaphore import ExecutionSemaphore
    from agent.runtime.task_runner import TaskRunner

    async with Database(config.db.path) as db:
        semaphore = ExecutionSemaphore()
        runtime = Runtime(config, store, llm, output=cli, db=db)

        task_runner = TaskRunner(config, db, output=cli)
        scheduler = Scheduler(config, db, semaphore)
        scheduler.set_task_runner(task_runner)

        http_server = await start_http_server(config, db, output=cli)

        scheduler_task = asyncio.create_task(scheduler.run(), name="scheduler")

        try:
            if session_id:
                await _resume(cli, runtime, session_id)
            else:
                await cli.run(runtime, semaphore=semaphore, db=db)
        finally:
            scheduler_task.cancel()
            http_server.close()
            await http_server.wait_closed()


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
