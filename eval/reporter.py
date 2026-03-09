"""Terminal reporter for eval results — Rich edition."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

VERDICT_ICON  = {"PASS": "✅", "PARTIAL": "⚠️ ", "FAIL": "❌"}
VERDICT_STYLE = {"PASS": "bold green", "PARTIAL": "bold yellow", "FAIL": "bold red"}


def _score_style(v: int) -> str:
    return "green" if v >= 7 else "yellow" if v >= 4 else "red"


def _score_bar(score: int, width: int = 10) -> Text:
    filled = round(score / 10 * width)
    bar = "█" * filled + "░" * (width - filled)
    style = _score_style(score)
    t = Text()
    t.append(bar, style=style)
    t.append(f"  {score}/10", style="dim")
    return t


def _truncate(s: str, n: int = 60) -> str:
    s = s.replace("\n", " ").strip()
    return s[:n] + "…" if len(s) > n else s


def print_results(
    results: list[dict],
    show_responses: bool = False,
    console: Console | None = None,
) -> None:
    con = console or Console()
    total = len(results)
    if total == 0:
        con.print("[yellow]No results.[/]")
        return

    counts: dict[str, int] = defaultdict(int)
    cat_results: dict[str, list[dict]] = defaultdict(list)
    avg_tools = avg_output = avg_persona = 0.0

    for r in results:
        counts[r["verdict"]] += 1
        cat_results[r["category"]].append(r)
        avg_tools  += r.get("tool_sequence", 0)
        avg_output += r.get("output_quality", 0)
        avg_persona += r.get("persona", 0)

    avg_tools   /= total
    avg_output  /= total
    avg_persona /= total
    avg_overall  = (avg_tools + avg_output + avg_persona) / 3

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Summary panel ─────────────────────────────────────────────────────────
    pass_pct    = counts["PASS"]    / total * 100
    partial_pct = counts["PARTIAL"] / total * 100
    fail_pct    = counts["FAIL"]    / total * 100

    summary = Text()
    summary.append(f"✅ PASS     {counts['PASS']:>3}/{total}  ({pass_pct:.0f}%)\n", style="bold green")
    summary.append(f"⚠️  PARTIAL  {counts['PARTIAL']:>3}/{total}  ({partial_pct:.0f}%)\n", style="bold yellow")
    summary.append(f"❌ FAIL     {counts['FAIL']:>3}/{total}  ({fail_pct:.0f}%)\n", style="bold red")

    con.print()
    con.print(Panel(
        summary,
        title=f"[bold cyan]RESULTS[/]  [dim]·[/]  [white]{total} cases  ·  {now}[/]",
        border_style="cyan",
        padding=(0, 2),
    ))

    # ── Score averages ─────────────────────────────────────────────────────────
    score_table = Table.grid(padding=(0, 2))
    score_table.add_column(width=16, style="dim")
    score_table.add_column()
    score_table.add_row("tool_sequence",  _score_bar(round(avg_tools)))
    score_table.add_row("output_quality", _score_bar(round(avg_output)))
    score_table.add_row("persona",        _score_bar(round(avg_persona)))
    score_table.add_row("─" * 14,         Text("─" * 16, style="dim"))
    score_table.add_row("overall",        _score_bar(round(avg_overall)))

    con.print(Panel(
        score_table,
        title="[bold cyan]SCORES[/]",
        border_style="dim",
        padding=(0, 2),
    ))

    # ── Per-category breakdown ─────────────────────────────────────────────────
    for category, rows in sorted(cat_results.items()):
        cat_pass = sum(1 for r in rows if r["verdict"] == "PASS")
        cat_avg  = sum(
            (r.get("tool_sequence", 0) + r.get("output_quality", 0) + r.get("persona", 0)) / 3
            for r in rows
        ) / len(rows)

        if cat_pass == len(rows):
            cat_style = "bold green"
        elif cat_avg >= 5:
            cat_style = "bold yellow"
        else:
            cat_style = "bold red"

        cat_table = Table(
            show_header=False,
            box=None,
            pad_edge=False,
            padding=(0, 1),
        )
        cat_table.add_column(width=3,  style="dim")      # icon
        cat_table.add_column(width=4,  style="dim")      # id
        cat_table.add_column(width=62, no_wrap=True)     # input
        cat_table.add_column(width=6,  justify="right")  # tools
        cat_table.add_column(width=7,  justify="right")  # output
        cat_table.add_column(width=8,  justify="right")  # persona
        cat_table.add_column()                           # notes

        for r in rows:
            verdict = r["verdict"]
            icon    = VERDICT_ICON.get(verdict, "?")
            vstyle  = VERDICT_STYLE.get(verdict, "")
            ts      = r.get("tool_sequence", 0)
            oq      = r.get("output_quality", 0)
            ps      = r.get("persona", 0)
            mn      = " ⛔" if r.get("must_not_violated") else ""
            notes   = _truncate(r.get("notes", ""), 50)
            inp     = _truncate(r["input"], 60)

            if show_responses:
                resp = _truncate(r.get("agent_response", ""), 120)
                notes_full = f"{notes}  [dim]agent: {resp}[/dim]" if notes else f"[dim]agent: {resp}[/dim]"
            else:
                notes_full = notes

            cat_table.add_row(
                Text(icon, style=vstyle),
                f"#{r['id']}",
                Text(inp, style="dim"),
                Text(f"[{_score_style(ts)}]{ts}[/]"),
                Text(f"[{_score_style(oq)}]{oq}[/]"),
                Text(f"[{_score_style(ps)}]{ps}[/]"),
                Text(f"{notes_full}{mn}", style="dim"),
            )

        con.print(Panel(
            cat_table,
            title=f"[{cat_style}]{category.upper()}[/]  "
                  f"[dim]{cat_pass}/{len(rows)} pass  ·  avg {cat_avg:.1f}/10[/]",
            border_style="dim",
            padding=(0, 1),
        ))

    con.print()
