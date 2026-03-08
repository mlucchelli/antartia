from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from agent.config.loader import Config

VERSION = "0.0.1"

_MASCOT_LINES = [
    "  ╱|、",
    " (˚ˎ 。7",
    "  |、˜〵",
    "  じしˍ,)ノ",
]

if TYPE_CHECKING:
    from agent.db.database import Database
    from agent.runtime.runtime import Runtime
    from agent.runtime.semaphore import ExecutionSemaphore


def _is_real_terminal() -> bool:
    try:
        os.get_terminal_size()
        return True
    except OSError:
        return False


class CLI:
    """Implements OutputHandler and runs the chat loop.

    Terminal layout (when TTY is available):
        Rows 1..(N-3)  — scroll area: chat messages, tool results, task progress
        Row  N-2        — rule separator
        Row  N-1        — input line (❯) OR spinner (during semaphore hold)
        Row  N          — status bar: session | tasks pending | tokens
    """

    def __init__(self, config: Config, debug: bool = False) -> None:
        self._config = config
        self._console = Console()
        self._debug = debug
        self._last_state: dict | None = None
        self._session_id: str = ""
        self._total_tokens: int = 0
        self._has_tty = _is_real_terminal()
        self._weather: dict | None = None
        self._last_location: dict | None = None

    # -- Banner ------------------------------------------------------------

    _INFO_COL = 20

    def _render_banner(self) -> None:
        info_lines = [
            f"[bold white]agent1[/bold white] [dim]v{VERSION} — nosoul[/dim]",
            f"[dim]{self._config.agent.model}[/dim]",
            f"[bold bright_magenta]{self._config.agent.name}[/bold bright_magenta]",
        ]

        for i, mascot_line in enumerate(_MASCOT_LINES):
            self._console.print(f"[cyan]{mascot_line}[/cyan]", end="")
            if i < len(info_lines):
                self._write(f"\033[{self._INFO_COL}G")
                self._console.print(info_lines[i])
            else:
                self._console.print()

        self._console.print()

    # -- OutputHandler callbacks -------------------------------------------

    def on_system_prompt(self, prompt: str) -> None:
        if self._debug:
            self._console.print(Panel(
                prompt, title="DEBUG system prompt", border_style="magenta", style="dim",
            ))

    def on_llm_response(self, response: dict) -> None:
        usage = response.pop("_usage", {})
        self._total_tokens += usage.get("total_tokens", 0)
        self._render_status_bar()

        if self._debug:
            raw = json.dumps(response, indent=2)
            self._console.print(Panel(
                raw, title="DEBUG LLM response", border_style="yellow", style="dim",
            ))

    def on_state_update(self, state: dict) -> None:
        self._last_state = state
        self._render_status_bar()

    def on_llm_start(self, depth: int) -> None:
        if depth == 0:
            self._console.print("  [dim cyan]▸ reasoning...[/dim cyan]")
        else:
            self._console.print(f"  [dim cyan]▸ reasoning... ({depth})[/dim cyan]")

    def on_action_start(self, action_type: str) -> None:
        self._console.print(f"  [dim]executing: {action_type}[/dim]")

    def on_task_progress(self, message: str) -> None:
        self._console.print(f"  [dim cyan]⟳ {escape(message)}[/dim cyan]")

    def display(self, content: str) -> None:
        if self._debug and self._last_state:
            raw = json.dumps(self._last_state, indent=2, default=str)
            self._console.print(Panel(
                raw, title="DEBUG state", border_style="cyan", style="dim",
            ))

        name = self._config.agent.name
        self._console.print(f"[bold blue]{name}:[/bold blue] {escape(content)}")

    # -- Terminal helpers --------------------------------------------------

    def _write(self, seq: str) -> None:
        self._console.file.write(seq)
        self._console.file.flush()

    def _rows(self) -> int:
        return os.get_terminal_size().lines

    # -- Status bar (row N) ------------------------------------------------

    async def refresh_expedition_status(self, db: "Database") -> None:
        from agent.db.locations_repo import LocationsRepository
        from agent.db.weather_repo import WeatherRepository
        locs = await LocationsRepository(db).get_latest(limit=1)
        self._last_location = locs[0] if locs else None
        self._weather = await WeatherRepository(db).get_latest()
        self._render_status_bar()

    def _build_status_text(self) -> Text:
        sep = " [dim]\u2502[/dim] "
        parts: list[str] = [f"session: {self._session_id}"]

        if self._last_location:
            lat = self._last_location["latitude"]
            lon = self._last_location["longitude"]
            parts.append(f"[cyan]{lat:.3f}, {lon:.3f}[/cyan]")

        if self._weather:
            w = self._weather
            temp = f"{w['temperature']}°C (feels {w['apparent_temperature']}°C)"
            condition = (w.get("condition") or "").lower()
            if "snow" in condition:
                precip = " ❄"
            elif any(x in condition for x in ("rain", "drizzle", "shower")):
                precip = " 🌧"
            else:
                precip = ""
            parts.append(f"[white]{temp}{precip}[/white]")

        parts.append(f"tokens: {self._total_tokens:,}")
        return Text.from_markup(sep.join(parts))

    def _render_status_bar(self) -> None:
        if not self._has_tty:
            return
        rows = self._rows()
        self._write(f"\033[s\033[{rows};1H\033[2K")
        self._console.print(self._build_status_text(), style="dim", end="")
        self._write("\033[u")

    # -- Fixed input line (row N-1) ----------------------------------------

    def get_user_input(self) -> str | None:
        try:
            return self._console.input("[bold yellow]❯ [/bold yellow]")
        except (EOFError, KeyboardInterrupt):
            return None

    _SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    @asynccontextmanager
    async def _thinking(self, label: str = "Thinking..."):
        """Animated spinner on the input row while inside the context."""
        if not self._has_tty:
            self._console.print(f"[dim]{label}[/dim]")
            yield
            return

        async def _spin() -> None:
            frames = self._SPINNER_FRAMES
            i = 0
            while True:
                rows = self._rows()
                self._write(f"\033[s\033[{rows - 1};1H\033[2K")
                self._console.print(
                    f"[bold yellow]❯ [/bold yellow][dim]{frames[i]} {label}[/dim]",
                    end="",
                )
                self._write("\033[u")
                i = (i + 1) % len(frames)
                await asyncio.sleep(0.08)

        task = asyncio.create_task(_spin())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _render_input_area(self) -> None:
        if not self._has_tty:
            return
        rows = self._rows()
        self._write(f"\033[s\033[{rows - 2};1H\033[2K")
        self._console.rule(style="dim")
        self._write(f"\033[{rows - 1};1H\033[2K")
        self._write("\033[u")

    async def _get_input_async(self) -> str | None:
        """Non-blocking input — ANSI setup on main thread, blocking input() in executor."""
        if not self._has_tty:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.get_user_input)

        rows = self._rows()
        self._write("\0337")
        self._render_input_area()
        self._write(f"\033[{rows - 1};1H\033[2K")
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._console.input("[bold yellow]❯ [/bold yellow]"),
            )
        except (EOFError, KeyboardInterrupt):
            result = None
        self._write(f"\033[{rows - 1};1H\033[2K\0338")
        return result

    # -- Terminal setup/teardown -------------------------------------------

    def _setup_terminal(self) -> None:
        if not self._has_tty:
            return
        rows = self._rows()
        self._write("\033[2J")
        self._write(f"\033[1;{rows - 3}r")
        self._write("\033[1;1H")

    def _teardown_terminal(self) -> None:
        if not self._has_tty:
            return
        self._write("\033[r")
        rows = self._rows()
        self._write(f"\033[{rows};1H\n")

    # -- Main loop ---------------------------------------------------------

    async def run(
        self,
        runtime: Runtime,
        semaphore: ExecutionSemaphore | None = None,
        db: "Database | None" = None,
        status_refresh_interval: int = 300,
    ) -> None:
        self._setup_terminal()
        self._render_banner()
        self._session_id = await runtime.start_session()
        if db:
            await self.refresh_expedition_status(db)
        else:
            self._render_status_bar()

        async def _status_loop() -> None:
            while True:
                await asyncio.sleep(status_refresh_interval)
                if db:
                    await self.refresh_expedition_status(db)

        status_task = asyncio.create_task(_status_loop(), name="status-refresh")

        try:
            while True:
                # Wait for any running background task to finish, then acquire the lock
                if semaphore:
                    if not semaphore.is_idle:
                        async with self._thinking("Background task running..."):
                            await semaphore.acquire_typing()
                    else:
                        await semaphore.acquire_typing()

                user_input = await self._get_input_async()

                if user_input is None or user_input.strip().lower() in ("quit", "exit"):
                    if semaphore:
                        semaphore.release()
                    break

                if not user_input.strip():
                    if semaphore:
                        semaphore.release()
                    continue

                # Transition lock to llm_running — keep holding it
                if semaphore:
                    semaphore.transition_to_llm()

                self._console.print(f"[bold yellow]❯ [/bold yellow]{user_input}")
                async with self._thinking():
                    await runtime.process_message(self._session_id, user_input)

                if db:
                    await self.refresh_expedition_status(db)

                if semaphore:
                    semaphore.release()

        finally:
            status_task.cancel()
            self._teardown_terminal()
            self._console.print("[dim]Goodbye![/dim]")
