"""Match history tracking utilities.

Provides utilities for tracking match score progression over time.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import typer
from rich import box
from rich.table import Table
from src.client.api import _get_agent_id

from ._common import console
from .utils import file_lock, load_json_safe

# Config directory
DECOMP_CONFIG_DIR = Path.home() / ".config" / "decomp-me"
DECOMP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Get agent ID for file isolation
AGENT_ID = _get_agent_id()

# Match history file (per-agent for isolation)
_history_suffix = f"_{AGENT_ID}" if AGENT_ID else ""
MATCH_HISTORY_FILE = DECOMP_CONFIG_DIR / f"match_history{_history_suffix}.json"

attempts_app = typer.Typer(help="Track decomp attempts, blockers, and stalled work")

DEFAULT_STALL_THRESHOLD = 10
VALID_OUTCOMES = {"improved", "matched", "neutral", "regressed", "reverted", "blocked"}
PROGRESS_OUTCOMES = {"improved", "matched"}
REGISTER_CLASSIFICATIONS = {"register-allocation", "register-only", "register-only-mismatch", "register-only mismatch"}


# =============================================================================
# Match History Tracking
# =============================================================================


def load_match_history() -> dict:
    """Load match history for all scratches.

    Returns dict of slug -> list of {score, max_score, match_pct, timestamp}
    """
    if not MATCH_HISTORY_FILE.exists():
        return {}
    try:
        with open(MATCH_HISTORY_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_match_history(data: dict) -> None:
    """Save match history."""
    MATCH_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MATCH_HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)


def record_match_score(slug: str, score: int, max_score: int) -> dict:
    """Record a new match score for a scratch.

    Args:
        slug: Scratch slug
        score: Current diff score (0 = perfect match)
        max_score: Maximum possible score

    Returns:
        History entry that was added
    """
    history = load_match_history()
    if slug not in history:
        history[slug] = []

    match_pct = 100.0 if score == 0 else (1.0 - score / max_score) * 100 if max_score > 0 else 0.0

    entry = {
        "score": score,
        "max_score": max_score,
        "match_pct": round(match_pct, 1),
        "timestamp": time.time(),
    }

    # Only record if score changed from last entry
    if history[slug]:
        last = history[slug][-1]
        if last["score"] == score and last["max_score"] == max_score:
            return entry  # No change, don't record duplicate

    history[slug].append(entry)

    # Keep only last 50 entries per scratch
    if len(history[slug]) > 50:
        history[slug] = history[slug][-50:]

    save_match_history(history)
    return entry


def get_match_history(slug: str) -> list:
    """Get match history for a scratch.

    Returns list of {score, max_score, match_pct, timestamp}
    """
    history = load_match_history()
    return history.get(slug, [])


def format_match_history(slug: str, max_entries: int = 10) -> str:
    """Format match history as a compact string for display.

    Shows progression like: "0% → 45% → 71.5% → 100%"
    """
    history = get_match_history(slug)
    if not history:
        return ""

    # Get unique match percentages (dedupe consecutive same values)
    pcts = []
    last_pct = None
    for entry in history[-max_entries:]:
        pct = entry["match_pct"]
        if pct != last_pct:
            pcts.append(pct)
            last_pct = pct

    if len(pcts) <= 1:
        return ""

    return " → ".join(f"{p}%" for p in pcts)


# =============================================================================
# Source-Level Attempt Ledger
# =============================================================================


def attempt_ledger_path(path: Path | None = None) -> Path:
    """Resolve the attempt ledger path."""
    if path is not None:
        return path
    if override := os.environ.get("DECOMP_ATTEMPT_LEDGER_FILE"):
        return Path(override).expanduser()
    return DECOMP_CONFIG_DIR / "attempt_ledger.json"


def _lock_path(path: Path) -> Path:
    if path.suffix:
        return path.with_suffix(path.suffix + ".lock")
    return path.with_name(path.name + ".lock")


def _empty_ledger() -> dict[str, Any]:
    return {"version": 1, "functions": {}}


def _normalize_ledger(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return _empty_ledger()
    if not isinstance(data.get("functions"), dict):
        data["functions"] = {}
    data.setdefault("version", 1)
    return data


def load_attempt_ledger(path: Path | None = None) -> dict[str, Any]:
    """Load the attempt ledger, returning an empty ledger on missing/corrupt data."""
    return _normalize_ledger(load_json_safe(attempt_ledger_path(path)))


def _write_ledger_unlocked(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _new_function_entry(function_name: str) -> dict[str, Any]:
    now = time.time()
    return {
        "function": function_name,
        "best_match_percent": None,
        "no_progress_count": 0,
        "register_only_no_progress_count": 0,
        "move_on_recommended": False,
        "move_on_reason": "",
        "recommendation": "",
        "suspected_blocker": "",
        "attempts": [],
        "created_at": now,
        "updated_at": now,
    }


def _summarize_entry(entry: dict[str, Any], threshold: int = DEFAULT_STALL_THRESHOLD) -> dict[str, Any]:
    attempts = entry.get("attempts", [])
    retained_improvements = sum(1 for attempt in attempts if attempt.get("retained"))
    recent_blockers = [
        attempt["blocker"]
        for attempt in attempts[-5:]
        if isinstance(attempt, dict) and attempt.get("blocker")
    ]
    move_on = _move_on_state(entry, threshold)
    return {
        "exists": True,
        "function": entry.get("function"),
        "best_match_percent": entry.get("best_match_percent"),
        "attempt_count": len(attempts),
        "no_progress_count": entry.get("no_progress_count", 0),
        "register_only_no_progress_count": entry.get("register_only_no_progress_count", 0),
        "stall_threshold": threshold,
        "move_on_recommended": move_on["recommended"],
        "move_on_reason": move_on["reason"],
        "recommendation": move_on["recommendation"],
        "suspected_blocker": entry.get("suspected_blocker", ""),
        "retained_improvements": retained_improvements,
        "recent_blockers": recent_blockers,
        "attempts": attempts,
        "updated_at": entry.get("updated_at"),
    }


def summarize_attempts(
    function_name: str,
    *,
    threshold: int = DEFAULT_STALL_THRESHOLD,
    path: Path | None = None,
) -> dict[str, Any]:
    """Summarize tracked attempts for one function."""
    ledger = load_attempt_ledger(path)
    entry = ledger["functions"].get(function_name)
    if not entry:
        return {
            "exists": False,
            "function": function_name,
            "best_match_percent": None,
            "attempt_count": 0,
            "no_progress_count": 0,
            "register_only_no_progress_count": 0,
            "stall_threshold": threshold,
            "move_on_recommended": False,
            "move_on_reason": "",
            "recommendation": "",
            "suspected_blocker": "",
            "retained_improvements": 0,
            "recent_blockers": [],
            "attempts": [],
            "updated_at": None,
        }
    return _summarize_entry(entry, threshold)


def _validate_outcome(outcome: str) -> str:
    normalized = outcome.strip().lower()
    if normalized not in VALID_OUTCOMES:
        raise ValueError(f"outcome must be one of: {', '.join(sorted(VALID_OUTCOMES))}")
    return normalized


def _is_register_classification(classification: str) -> bool:
    return classification.strip().lower() in REGISTER_CLASSIFICATIONS


def _move_on_state(entry: dict[str, Any], threshold: int) -> dict[str, Any]:
    if entry.get("register_only_no_progress_count", 0) >= threshold:
        return {
            "recommended": True,
            "reason": "repeated register-allocation mismatch attempts",
            "recommendation": "Move to a fresh function or TU; keep the current notes and return only with new source evidence.",
        }
    if entry.get("no_progress_count", 0) >= threshold:
        return {
            "recommended": True,
            "reason": "repeated no-progress attempts",
            "recommendation": "Move to a fresh function or TU; preserve the blocker and retained edits first.",
        }
    return {"recommended": False, "reason": "", "recommendation": ""}


def record_attempt(
    function_name: str,
    *,
    match_percent: float,
    outcome: str,
    note: str = "",
    classification: str = "",
    blocker: str = "",
    retained: bool = False,
    threshold: int = DEFAULT_STALL_THRESHOLD,
    path: Path | None = None,
) -> dict[str, Any]:
    """Record one source-level attempt and return the updated summary."""
    if match_percent < 0 or match_percent > 100:
        raise ValueError("match_percent must be between 0 and 100")
    if threshold < 1:
        raise ValueError("threshold must be at least 1")

    normalized_outcome = _validate_outcome(outcome)
    ledger_path = attempt_ledger_path(path)

    with file_lock(_lock_path(ledger_path), exclusive=True):
        ledger = _normalize_ledger(load_json_safe(ledger_path))
        functions = ledger["functions"]
        entry = functions.setdefault(function_name, _new_function_entry(function_name))

        previous_best = entry.get("best_match_percent")
        rounded_match = round(match_percent, 1)
        improved_score = previous_best is None or rounded_match > previous_best
        if improved_score:
            entry["best_match_percent"] = rounded_match

        made_progress = normalized_outcome in PROGRESS_OUTCOMES or retained or improved_score
        if made_progress:
            entry["no_progress_count"] = 0
            entry["register_only_no_progress_count"] = 0
        else:
            entry["no_progress_count"] = entry.get("no_progress_count", 0) + 1
            if _is_register_classification(classification):
                entry["register_only_no_progress_count"] = entry.get("register_only_no_progress_count", 0) + 1
            else:
                entry["register_only_no_progress_count"] = 0

        if blocker:
            entry["suspected_blocker"] = blocker

        attempt = {
            "index": len(entry.get("attempts", [])) + 1,
            "timestamp": time.time(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "agent_id": AGENT_ID,
            "worktree": str(Path.cwd()),
            "match_percent": rounded_match,
            "outcome": normalized_outcome,
            "classification": classification,
            "blocker": blocker,
            "retained": retained,
            "note": note,
        }
        entry.setdefault("attempts", []).append(attempt)
        move_on = _move_on_state(entry, threshold)
        entry["move_on_recommended"] = move_on["recommended"]
        entry["move_on_reason"] = move_on["reason"]
        entry["recommendation"] = move_on["recommendation"]
        entry["updated_at"] = time.time()
        ledger["updated_at"] = entry["updated_at"]

        _write_ledger_unlocked(ledger_path, ledger)
        return _summarize_entry(entry, threshold)


@attempts_app.command("record")
def attempts_record(
    function_name: Annotated[str, typer.Argument(help="Function name being attempted")],
    match_percent: Annotated[float, typer.Option("--match", help="Current match percentage")] = 0.0,
    outcome: Annotated[
        str,
        typer.Option(
            "--outcome",
            help="Attempt outcome: improved, matched, neutral, regressed, reverted, blocked",
        ),
    ] = "neutral",
    note: Annotated[str, typer.Option("--note", help="Short source-level note for this attempt")] = "",
    classification: Annotated[
        str,
        typer.Option("--classification", help="Diff classification, such as register-allocation or stack-layout"),
    ] = "",
    blocker: Annotated[str, typer.Option("--blocker", help="Suspected blocker or uncertainty")] = "",
    retained: Annotated[bool, typer.Option("--retained", help="Mark this as a retained source improvement")] = False,
    threshold: Annotated[
        int,
        typer.Option("--threshold", help="No-progress attempts before recommending move-on"),
    ] = DEFAULT_STALL_THRESHOLD,
    output_json: Annotated[bool, typer.Option("--json", help="Output updated summary as JSON")] = False,
):
    """Record one attempt independent of scratch score history."""
    try:
        summary = record_attempt(
            function_name,
            match_percent=match_percent,
            outcome=outcome,
            note=note,
            classification=classification,
            blocker=blocker,
            retained=retained,
            threshold=threshold,
        )
    except ValueError as exc:
        if output_json:
            print(json.dumps({"success": False, "error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if output_json:
        print(json.dumps(summary, indent=2))
        return

    best = summary["best_match_percent"]
    console.print(f"[green]Recorded attempt[/green] for [bold]{function_name}[/bold]")
    console.print(f"Best match: {best:.1f}%" if best is not None else "Best match: n/a")
    console.print(f"No-progress streak: {summary['no_progress_count']} / {threshold}")
    if summary["move_on_recommended"]:
        console.print(f"[yellow]Move-on recommended[/yellow]: {summary['recommendation']}")


@attempts_app.command("show")
def attempts_show(
    function_name: Annotated[str, typer.Argument(help="Function name to inspect")],
    threshold: Annotated[
        int,
        typer.Option("--threshold", help="No-progress attempts before recommending move-on"),
    ] = DEFAULT_STALL_THRESHOLD,
    output_json: Annotated[bool, typer.Option("--json", help="Output summary as JSON")] = False,
):
    """Show attempt history for one function."""
    summary = summarize_attempts(function_name, threshold=threshold)

    if output_json:
        print(json.dumps(summary, indent=2))
        return

    if not summary["exists"]:
        console.print(f"[yellow]No attempts recorded for {function_name}[/yellow]")
        return

    table = Table(title=f"Attempts: {function_name}", box=box.SIMPLE)
    table.add_column("#", justify="right")
    table.add_column("Match", justify="right")
    table.add_column("Outcome")
    table.add_column("Class")
    table.add_column("Blocker")
    table.add_column("Note")

    for attempt in summary["attempts"][-20:]:
        table.add_row(
            str(attempt.get("index", "")),
            f"{attempt.get('match_percent', 0):.1f}%",
            attempt.get("outcome", ""),
            attempt.get("classification", ""),
            attempt.get("blocker", ""),
            attempt.get("note", ""),
        )

    console.print(table)
    console.print(f"Best match: {summary['best_match_percent']:.1f}%")
    console.print(f"No-progress streak: {summary['no_progress_count']} / {threshold}")
    if summary["move_on_recommended"]:
        console.print(f"[yellow]Move-on recommended[/yellow]: {summary['recommendation']}")


@attempts_app.command("list")
def attempts_list(
    output_json: Annotated[bool, typer.Option("--json", help="Output tracked functions as JSON")] = False,
):
    """List functions with tracked attempts."""
    ledger = load_attempt_ledger()
    functions = sorted(
        ledger["functions"].values(),
        key=lambda entry: entry.get("updated_at", 0),
        reverse=True,
    )

    summaries = [_summarize_entry(entry) for entry in functions]
    if output_json:
        print(json.dumps(summaries, indent=2))
        return

    if not summaries:
        console.print("[yellow]No attempts recorded[/yellow]")
        return

    table = Table(title="Tracked Decomp Attempts", box=box.SIMPLE)
    table.add_column("Function")
    table.add_column("Best", justify="right")
    table.add_column("Attempts", justify="right")
    table.add_column("Stalled", justify="right")
    table.add_column("Blocker")

    for summary in summaries:
        best = summary["best_match_percent"]
        table.add_row(
            summary["function"],
            f"{best:.1f}%" if best is not None else "-",
            str(summary["attempt_count"]),
            str(summary["no_progress_count"]),
            summary["suspected_blocker"],
        )

    console.print(table)
