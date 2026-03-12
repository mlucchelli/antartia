from __future__ import annotations

import asyncio
import json
import os
import readline  # noqa: F401 — enables arrow-key navigation in input()
from contextlib import asynccontextmanager
from datetime import datetime
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
        self._verbose = os.environ.get("ANTARTIA_VERBOSE", "0") == "1"
        self._last_state: dict | None = None
        self._session_id: str = ""
        self._total_tokens: int = 0
        self._has_tty = _is_real_terminal()
        self._weather: dict | None = None
        self._last_location: dict | None = None
        self._location_updated_at: str | None = None
        self._last_task: dict | None = None    # {type, source, success, at}
        self._running_task: dict | None = None  # {type, source} while executing
        self._semaphore: "ExecutionSemaphore | None" = None
        self._today_km: float | None = None
        self._db: "Database | None" = None
        self._readline_active: bool = False  # True only during _get_input_async
        self._sending: bool = False          # True while RemoteSyncService is pushing
        self._sync_count: int = 0            # network requests sent today (from DB)
        self._scroll_row: int = 1           # next row to print in scroll region
        self._task_spinner: "asyncio.Task[None] | None" = None

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
        # 4 mascot lines + 1 blank line printed = cursor now at row 6
        self._scroll_row = len(_MASCOT_LINES) + 2

    # -- OutputHandler callbacks -------------------------------------------

    def on_system_prompt(self, prompt: str) -> None:
        if self._debug:
            self._console.print(Panel(
                prompt, title="DEBUG system prompt", border_style="magenta", style="dim",
            ))

    def on_llm_response(self, response: dict) -> None:
        # token counting is handled via on_tokens_used() from runtime._log_tokens()
        response.pop("_usage", None)
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
            self._print_to_scroll("  [dim cyan]▸ reasoning...[/dim cyan]")
        else:
            self._print_to_scroll(f"  [dim cyan]▸ reasoning... ({depth})[/dim cyan]")

    def on_vision_start(self, filename: str) -> None:
        self._print_to_scroll(f"  [dim magenta]◈ analyzing {filename}[/dim magenta]")

    def on_action_start(self, action_type: str) -> None:
        # Always show tool calls; hide send_message/finish noise
        if action_type in ("send_message", "finish"):
            return
        self._print_to_scroll(f"  [dim]⟳ {action_type}[/dim]")

    def _print_to_scroll(self, markup: str) -> None:
        """Print into the scroll region using explicit row tracking.

        Always positions the cursor using _scroll_row so we never depend on
        terminal save-slot state (ANSI \033[s and DEC \0337 share a slot in
        most terminals, causing clobbering when _render_status_bar fires during
        readline).

        readline case: inject above the prompt via N-3 jump + DEC save/restore.
        All other cases: explicit absolute positioning at _scroll_row.
        """
        if not self._has_tty:
            self._console.print(markup)
            return

        rows = self._rows()
        if self._readline_active:
            # Cursor is at N-1 (readline); inject at bottom of scroll area.
            self._write("\0337")
            self._write(f"\033[{rows - 3};1H")
            self._console.print(markup)
            self._write("\0338")
            self._scroll_row = rows - 3  # scroll region has now scrolled
        else:
            row = min(self._scroll_row, rows - 3)
            # Measure actual rendered height before printing (handles multi-line responses)
            with self._console.capture() as cap:
                self._console.print(markup)
            line_count = max(1, cap.get().count("\n"))
            self._write(f"\033[{row};1H")
            self._console.print(markup)
            self._scroll_row = min(self._scroll_row + line_count, rows - 3)

    def on_task_progress(self, message: str) -> None:
        if not self._verbose:
            return
        self._print_to_scroll(f"  [dim cyan]⟳ {escape(message)}[/dim cyan]")

    def on_task_start(self, task_type: str, source: str) -> None:
        self._running_task = {"type": task_type, "source": source}
        self._render_status_bar()
        if self._has_tty:
            try:
                self._task_spinner = asyncio.get_running_loop().create_task(
                    self._run_task_spinner(task_type)
                )
            except RuntimeError:
                pass

    def on_tokens_used(self, count: int) -> None:
        self._total_tokens += count
        self._render_status_bar()

    def on_sync_start(self) -> None:
        self._sending = True
        self._render_status_bar()

    def on_sync_end(self) -> None:
        self._sending = False
        if self._db:
            import asyncio
            loop = asyncio.get_event_loop()
            loop.create_task(self._refresh_sync_count())
        else:
            self._sync_count += 1
            self._render_status_bar()

    async def _refresh_sync_count(self) -> None:
        from agent.db.activity_logs_repo import ActivityLogsRepository
        self._sync_count = await ActivityLogsRepository(self._db).get_network_count_today()
        self._render_status_bar()

    def on_task_complete(self, task_type: str, source: str, success: bool) -> None:
        if self._task_spinner:
            self._task_spinner.cancel()
            self._task_spinner = None
        self._running_task = None
        self._last_task = {
            "type": task_type,
            "source": source,
            "success": success,
            "at": datetime.now().strftime("%H:%M"),
        }
        # Refresh distance + render after release() changes the semaphore state
        try:
            loop = asyncio.get_running_loop()
            if self._db:
                loop.create_task(self._refresh_distance())
            else:
                loop.call_soon(self._render_status_bar)
        except RuntimeError:
            self._render_status_bar()

    def update_location(self, latitude: float, longitude: float) -> None:
        self._last_location = {"latitude": latitude, "longitude": longitude}
        self._location_updated_at = datetime.now().strftime("%d-%m-%y %H:%M")
        self._render_status_bar()
        if self._db:
            try:
                asyncio.get_running_loop().create_task(self._refresh_distance())
            except RuntimeError:
                pass

    async def _refresh_distance(self) -> None:
        if self._db is None:
            return
        from agent.services.distance_service import DistanceService
        self._today_km = await DistanceService(self._db, self._config.agent.timezone).get_today_distance()
        self._render_status_bar()

    def display(self, content: str) -> None:
        name = self._config.agent.name
        self._print_to_scroll(f"[bold blue]{name}:[/bold blue] {escape(content)}")

    # -- Terminal helpers --------------------------------------------------

    def _write(self, seq: str) -> None:
        self._console.file.write(seq)
        self._console.file.flush()

    def _rows(self) -> int:
        return os.get_terminal_size().lines

    # -- Status bar (row N) ------------------------------------------------

    async def refresh_expedition_status(self, db: "Database") -> None:
        from agent.db.locations_repo import LocationsRepository
        from agent.db.tasks_repo import TasksRepository
        from agent.db.token_usage_repo import TokenUsageRepository
        from agent.db.weather_repo import WeatherRepository

        locs = await LocationsRepository(db).get_latest(limit=1)
        self._last_location = locs[0] if locs else None
        self._weather = await WeatherRepository(db).get_latest()

        last = await TasksRepository(db).get_last_executed()
        if last:
            self._last_task = {
                "type": last["type"],
                "source": last.get("source", "agent"),
                "success": last["status"] == "completed",
                "at": (last.get("executed_at") or "")[:16].replace("T", " ")[11:16],
            }

        totals = await TokenUsageRepository(db).get_total()
        self._total_tokens = totals["total"]

        try:
            from agent.services.distance_service import DistanceService
            self._today_km = await DistanceService(db, self._config.agent.timezone).get_today_distance()
        except Exception:
            self._today_km = 0.0

        from agent.db.activity_logs_repo import ActivityLogsRepository
        self._sync_count = await ActivityLogsRepository(db).get_network_count_today()

        self._render_status_bar()

    def _build_status_text(self) -> Text:
        sep = " [dim]\u2502[/dim] "
        parts: list[str] = [f"session: {self._session_id}"]

        if self._last_location:
            lat = self._last_location["latitude"]
            lon = self._last_location["longitude"]
            loc_str = f"[cyan]{lat:.3f}, {lon:.3f}[/cyan]"
            if self._location_updated_at:
                loc_str += f" [dim]at: {self._location_updated_at}[/dim]"
            parts.append(loc_str)

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

        if self._semaphore:
            state = self._semaphore.state.value
            if state == "idle":
                parts.append("[dim]idle[/dim]")
            elif state == "user_typing":
                parts.append("[dim]typing[/dim]")
            elif state == "llm_running":
                parts.append("[cyan]llm_running[/cyan]")
            elif state == "task_running":
                parts.append("[yellow]task_running[/yellow]")

        if self._running_task:
            t = self._running_task
            parts.append(f"[yellow]⟳ {t['type']} [{t['source']}][/yellow]")
        elif self._last_task:
            t = self._last_task
            icon = "✓" if t["success"] else "✗"
            color = "green" if t["success"] else "red"
            parts.append(
                f"[{color}]{icon}[/{color}] [dim]{t['type']} [{t['source']}] {t['at']}[/dim]"
            )

        if self._today_km is not None:
            parts.append(f"[dim]↗ {self._today_km} km[/dim]")

        net = f"⬆ {self._sync_count}"
        if self._sending:
            parts.append(f"[green]{net}[/green]")
        else:
            parts.append(f"[dim]{net}[/dim]")

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

    async def _run_task_spinner(self, label: str) -> None:
        """Background spinner for scheduled tasks — same row as _thinking."""
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

    def _render_input_area(self) -> None:
        if not self._has_tty:
            return
        rows = self._rows()
        self._write(f"\033[s\033[{rows - 2};1H\033[2K")
        self._console.rule(style="dim")
        self._write(f"\033[{rows - 1};1H\033[2K")
        self._write("\033[u")

    async def _get_input_async(self) -> str | None:
        """Non-blocking readline input. Semaphore stays idle during the wait;
        acquire_typing() is called by the main loop only after non-empty input."""
        if not self._has_tty:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.get_user_input)

        rows = self._rows()
        saved_scroll_row = self._scroll_row   # save in Python — no terminal save slot
        self._render_input_area()
        self._write(f"\033[{rows - 1};1H\033[2K")

        self._readline_active = True
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._console.input("[bold yellow]❯ [/bold yellow]"),
            )
        except (EOFError, KeyboardInterrupt):
            result = None
        finally:
            self._readline_active = False

        self._write(f"\033[{rows - 1};1H\033[2K")
        self._write(f"\033[{saved_scroll_row};1H")  # explicit restore — immune to slot clobbering
        self._scroll_row = saved_scroll_row
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
        self._semaphore = semaphore
        self._db = db
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
                # Wait for any running task/LLM to finish (without acquiring typing lock)
                if semaphore and not semaphore.is_idle:
                    async with self._thinking("Task running..."):
                        while not semaphore.is_idle:
                            await asyncio.sleep(0.1)
                self._render_status_bar()

                user_input = await self._get_input_async()

                if user_input is None or user_input.strip().lower() in ("quit", "exit"):
                    break

                if not user_input.strip():
                    continue

                # Acquire lock and transition to llm_running
                # acquire_typing waits if a task is running, then sets user_typing
                if semaphore:
                    await semaphore.acquire_typing()
                    await semaphore.transition_to_llm()
                    self._render_status_bar()

                self._print_to_scroll(f"[bold yellow]❯ [/bold yellow]{escape(user_input)}")
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
