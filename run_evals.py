#!/usr/bin/env python3
"""
AItartica eval runner — LLM-as-judge evaluation against the golden dataset.

Agent:  Ollama (production model, local)
Judge:  OpenRouter / GPT-4o-mini (requires OPENROUTER_API_KEY in .env)

Usage:
  python run_evals.py                             # all cases
  python run_evals.py --category navigation       # filter by category
  python run_evals.py --id 1 5 15                 # specific IDs
  python run_evals.py --limit 5                   # first N cases
  python run_evals.py --verbose                   # show agent responses
  python run_evals.py --json > results.json       # JSON output
  python run_evals.py --concurrency 3             # parallel cases
  python run_evals.py --judge-model openai/gpt-4o # stronger judge
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from eval.reporter import print_results
from eval.runner import (
    DEFAULT_JUDGE_MODEL,
    build_agent_system_prompt,
    load_golden_dataset,
    run_case,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s — %(message)s")

console = Console()

VERDICT_STYLE = {"PASS": "bold green", "PARTIAL": "bold yellow", "FAIL": "bold red"}
VERDICT_ICON  = {"PASS": "✅", "PARTIAL": "⚠️ ", "FAIL": "❌"}


def load_config(path: str = "configs/expedition_config.json") -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AItartica eval runner — LLM-as-judge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--category", metavar="CAT",
                   help="filter by category")
    p.add_argument("--id", nargs="+", type=int, metavar="N",
                   help="run specific case IDs")
    p.add_argument("--limit", type=int, default=0, metavar="N",
                   help="max cases to run (0 = all)")
    p.add_argument("--verbose", action="store_true",
                   help="show agent response per case")
    p.add_argument("--json", action="store_true",
                   help="output results as JSON")
    p.add_argument("--agent-model", default="",
                   help="Ollama model (default: from config)")
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL,
                   help="OpenRouter judge model (default: $EVAL_JUDGE_MODEL or openai/gpt-4o-mini)")
    p.add_argument("--dataset", default="data/evals/datasets/golden_dataset.csv",
                   help="path to golden dataset CSV")
    p.add_argument("--concurrency", type=int, default=1,
                   help="parallel cases (default: 1)")
    return p.parse_args()


def _make_layout(progress: Progress, live_table: Table) -> Group:
    """Combine progress bar + live results table into one renderable."""
    return Group(live_table, progress)


async def main() -> None:
    args = parse_args()

    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not openrouter_api_key:
        console.print("[bold red]❌  OPENROUTER_API_KEY not set.[/] Add it to .env or export it.")
        sys.exit(1)

    config     = load_config()
    ollama_url  = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    agent_model = args.agent_model or config["agent"]["model"]

    run_id    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    runs_dir  = Path("data/evals/runs")
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_file  = runs_dir / f"{run_id}.json"

    dataset = load_golden_dataset(args.dataset)
    if args.id:
        id_set  = {str(i) for i in args.id}
        dataset = [r for r in dataset if r["id"] in id_set]
    if args.category:
        dataset = [r for r in dataset if r["category"] == args.category]
    if args.limit:
        dataset = dataset[: args.limit]

    if not dataset:
        console.print("[yellow]No cases match the given filters.[/]")
        sys.exit(0)

    system_prompt = build_agent_system_prompt(config)
    total         = len(dataset)

    if args.json:
        # Silent run, JSON output only
        sem     = asyncio.Semaphore(args.concurrency)
        results = await asyncio.gather(*[
            _run_silent(row, system_prompt, ollama_url, agent_model,
                        openrouter_api_key, args.judge_model, sem)
            for row in dataset
        ])
        results = sorted(results, key=lambda r: int(r["id"]))
        _save_run(run_file, run_id, results, agent_model, args.judge_model, args.dataset)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return

    # ── Header ────────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel.fit(
        f"[bold cyan]ANTARTIA EVAL[/]  ·  [white]{total} case(s)[/]\n"
        f"[dim]agent[/]  [cyan]→[/] Ollama / [white]{agent_model}[/]\n"
        f"[dim]judge[/]  [cyan]→[/] OpenRouter / [white]{args.judge_model}[/]\n"
        f"[dim]run  [/]  [cyan]→[/] [dim]{run_id}[/]",
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print()

    # ── Live progress ─────────────────────────────────────────────────────────
    progress = Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=24, style="cyan", complete_style="green"),
        TimeElapsedColumn(),
        transient=False,
    )
    task_id = progress.add_task("[cyan]running evals…", total=total)

    # Live results table (grows as cases complete)
    live_table = Table(
        show_header=True,
        header_style="bold dim",
        border_style="dim",
        box=None,
        pad_edge=False,
        show_edge=False,
        padding=(0, 1),
    )
    live_table.add_column("#",        width=3,  style="dim")
    live_table.add_column("cat",      width=14, style="dim cyan")
    live_table.add_column("input",    width=52, no_wrap=True)
    live_table.add_column("tools",    width=5,  justify="right")
    live_table.add_column("output",   width=6,  justify="right")
    live_table.add_column("persona",  width=7,  justify="right")
    live_table.add_column("verdict",  width=9)
    live_table.add_column("notes",    style="dim", no_wrap=True)

    results: list[dict] = []
    live_counts: dict[str, int] = {"PASS": 0, "PARTIAL": 0, "FAIL": 0}
    lock = asyncio.Lock()

    def _score_style(v: int) -> str:
        return "green" if v >= 7 else "yellow" if v >= 4 else "red"

    def _counts_label() -> str:
        done = sum(live_counts.values())
        return (
            f"[green]{live_counts['PASS']}✅[/] "
            f"[yellow]{live_counts['PARTIAL']}⚠️ [/] "
            f"[red]{live_counts['FAIL']}❌[/]  "
            f"[dim]{done}/{total}[/]"
        )

    async def run_one(row: dict) -> dict:
        result = await run_case(
            row=row,
            system_prompt=system_prompt,
            ollama_url=ollama_url,
            agent_model=agent_model,
            openrouter_api_key=openrouter_api_key,
            judge_model=args.judge_model,
        )
        async with lock:
            results.append(result)
            verdict  = result.get("verdict", "FAIL")
            live_counts[verdict] = live_counts.get(verdict, 0) + 1
            ts       = result.get("tool_sequence", 0)
            oq       = result.get("output_quality", 0)
            ps       = result.get("persona", 0)
            mn       = " ⛔" if result.get("must_not_violated") else ""
            inp      = row["input"][:50] + ("…" if len(row["input"]) > 50 else "")
            notes    = (result.get("notes") or "")[:45]

            live_table.add_row(
                f"[dim]{row['id']}[/]",
                row["category"],
                inp,
                f"[{_score_style(ts)}]{ts}[/]",
                f"[{_score_style(oq)}]{oq}[/]",
                f"[{_score_style(ps)}]{ps}[/]",
                Text(f"{VERDICT_ICON[verdict]} {verdict}{mn}",
                     style=VERDICT_STYLE.get(verdict, "")),
                notes,
            )
            progress.advance(task_id)
            progress.update(task_id, description=f"[cyan]running evals…[/]  {_counts_label()}")
        return result

    sem = asyncio.Semaphore(args.concurrency)

    async def run_with_sem(row: dict) -> dict:
        async with sem:
            return await run_one(row)

    with Live(_make_layout(progress, live_table), console=console,
              refresh_per_second=8, vertical_overflow="visible"):
        await asyncio.gather(*[run_with_sem(r) for r in dataset])

    results = sorted(results, key=lambda r: int(r["id"]))
    _save_run(run_file, run_id, results, agent_model, args.judge_model, args.dataset)
    console.print(f"\n[dim]run saved →[/] [cyan]{run_file}[/]")

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print()
    print_results(results, show_responses=args.verbose, console=console)


def _save_run(
    run_file: Path,
    run_id: str,
    results: list[dict],
    agent_model: str,
    judge_model: str,
    dataset_path: str,
) -> None:
    counts = {"PASS": 0, "PARTIAL": 0, "FAIL": 0}
    for r in results:
        counts[r.get("verdict", "FAIL")] += 1
    total = len(results)
    avg = lambda key: sum(r.get(key, 0) for r in results) / total if total else 0

    payload = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_model": agent_model,
        "judge_model": judge_model,
        "dataset": dataset_path,
        "total": total,
        "counts": counts,
        "averages": {
            "tool_sequence": round(avg("tool_sequence"), 2),
            "output_quality": round(avg("output_quality"), 2),
            "persona": round(avg("persona"), 2),
            "overall": round((avg("tool_sequence") + avg("output_quality") + avg("persona")) / 3, 2),
        },
        "results": results,
    }
    run_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


async def _run_silent(row, system_prompt, ollama_url, agent_model,
                      api_key, judge_model, sem) -> dict:
    async with sem:
        return await run_case(
            row=row,
            system_prompt=system_prompt,
            ollama_url=ollama_url,
            agent_model=agent_model,
            openrouter_api_key=api_key,
            judge_model=judge_model,
        )


if __name__ == "__main__":
    asyncio.run(main())
