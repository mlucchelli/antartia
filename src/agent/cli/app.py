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
    from agent.runtime.runtime import Runtime


def _is_real_terminal() -> bool:
    try:
        os.get_terminal_size()
        return True
    except OSError:
        return False


class CLI:
    """Implements OutputHandler and runs the chat loop.

    Terminal layout (when TTY is available):
        Rows 1..(N-2)  — scroll area: chat messages, actions, thinking
        Row  N-1        — input line (fixed): > user types here
        Row  N          — status bar (fixed): session, step, fields, tokens
    """

    def __init__(self, config: Config, debug: bool = False) -> None:
        self._config = config
        self._console = Console()
        self._debug = debug
        self._fields = [(f.name, f.display_name) for f in config.fields]
        self._last_state: dict | None = None
        self._session_id: str = ""
        self._total_tokens: int = 0
        self._has_tty = _is_real_terminal()

    # -- Banner ------------------------------------------------------------

    _INFO_COL = 20  # fixed column where info text starts

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

    def on_action_start(self, action_type: str) -> None:
        self._console.print(f"  [dim]executing: {action_type}[/dim]")

    def display(self, content: str) -> None:
        # Debug: show final state once, right before the agent message
        if self._debug and self._last_state:
            summary = {
                "collected_fields": self._last_state.get("collected_fields", {}),
                "steps": self._last_state.get("steps", []),
                "total_attempts": self._last_state.get("total_attempts", 0),
                "escalated": self._last_state.get("escalated", False),
                "escalation_reason": self._last_state.get("escalation_reason"),
            }
            raw = json.dumps(summary, indent=2, default=str)
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

    def _build_status_text(self) -> Text:
        parts: list[str] = []
        parts.append(f"session: {self._session_id}")

        if self._last_state:
            steps = self._last_state.get("steps", [])
            current = next(
                (s["step_key"] for s in steps if s["status"] == "in_progress"),
                None,
            ) or next(
                (s["step_key"] for s in reversed(steps) if s["status"] != "pending"),
                "\u2014",
            )
            parts.append(f"step: {current}")

        collected = set()
        if self._last_state:
            collected = set(self._last_state.get("collected_fields", {}).keys())

        field_parts = []
        for name, display in self._fields:
            marker = "[green]\u2713[/green]" if name in collected else "[dim]\u2026[/dim]"
            field_parts.append(f"{display} {marker}")
        parts.append(" | ".join(field_parts))

        parts.append(f"tokens: {self._total_tokens:,}")
        return Text.from_markup(" [dim]\u2502[/dim] ".join(parts))

    def _render_status_bar(self) -> None:
        """Write status bar on the last terminal row (uses ANSI save/restore)."""
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
    async def _thinking(self):
        """Animated spinner on the input row while inside the context."""
        if not self._has_tty:
            self._console.print("[dim]Thinking...[/dim]")
            yield
            return

        async def _spin() -> None:
            frames = self._SPINNER_FRAMES
            i = 0
            while True:
                rows = self._rows()
                self._write(f"\033[s\033[{rows - 1};1H\033[2K")
                self._console.print(
                    f"[bold yellow]❯ [/bold yellow][dim]{frames[i]} Thinking...[/dim]",
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
        """Draw rule separator on row N-2 and clear input row N-1."""
        if not self._has_tty:
            return
        rows = self._rows()
        self._write(f"\033[s\033[{rows - 2};1H\033[2K")
        self._console.rule(style="dim")
        self._write(f"\033[{rows - 1};1H\033[2K")
        self._write("\033[u")

    def _get_input(self) -> str | None:
        """Move cursor to input row, get input, then return cursor to scroll area."""
        if not self._has_tty:
            return self.get_user_input()

        rows = self._rows()
        # Save scroll area cursor (DEC), draw input area, move to input row
        self._write("\0337")
        self._render_input_area()
        self._write(f"\033[{rows - 1};1H\033[2K")
        try:
            result = self._console.input("[bold yellow]❯ [/bold yellow]")
        except (EOFError, KeyboardInterrupt):
            result = None

        # Clear input row, restore scroll area cursor (DEC)
        self._write(f"\033[{rows - 1};1H\033[2K\0338")
        return result

    # -- Terminal setup/teardown -------------------------------------------

    def _setup_terminal(self) -> None:
        """Set scroll region to rows 1..(N-3), leaving N-2, N-1 and N fixed.

        Row N-2: rule separator
        Row N-1: input prompt
        Row N:   status bar
        """
        if not self._has_tty:
            return
        rows = self._rows()
        self._write("\033[2J")                # clear screen
        self._write(f"\033[1;{rows - 3}r")    # scroll region
        self._write("\033[1;1H")              # cursor to top of scroll area

    def _teardown_terminal(self) -> None:
        if not self._has_tty:
            return
        self._write("\033[r")                 # reset scroll region
        rows = self._rows()
        self._write(f"\033[{rows};1H\n")      # cursor to bottom

    # -- Main loop ---------------------------------------------------------

    async def run(self, runtime: Runtime) -> None:
        self._setup_terminal()
        self._render_banner()
        self._session_id = await runtime.start_session()  # greeting prints in scroll area
        self._render_status_bar()

        try:
            while True:
                user_input = self._get_input()
                if user_input is None or user_input.strip().lower() in ("quit", "exit"):
                    break
                if not user_input.strip():
                    continue

                # Echo user message in scroll area, animate spinner while processing
                self._console.print(f"[bold yellow]❯ [/bold yellow]{user_input}")
                async with self._thinking():
                    await runtime.process_message(self._session_id, user_input)
        finally:
            self._teardown_terminal()
            self._console.print("[dim]Goodbye![/dim]")
