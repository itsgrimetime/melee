"""CLI wrapper for taxonomy harvest sweeps."""

from __future__ import annotations

import json
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path

import typer

from src.harvest import HarnessRunner, ValidatorRunner, run_harvest

from ._common import DEFAULT_MELEE_ROOT


HARVEST_RUNNER: HarnessRunner | None = None
HARVEST_VALIDATOR: ValidatorRunner | None = None


def _queue_path(repo_root: Path, taxonomy_dir: Path | None, work_bucket: str) -> Path:
    if taxonomy_dir is not None:
        return taxonomy_dir / f"{work_bucket}.tsv"
    return repo_root / "build" / "function-taxonomy" / "queues" / f"{work_bucket}.tsv"


def _default_ledger_path(repo_root: Path, work_bucket: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    harvest_dir = repo_root / "build" / "harvest"
    path = harvest_dir / f"{work_bucket}-{timestamp}.json"
    if not path.exists():
        return path
    for index in range(1, 1000):
        path = harvest_dir / f"{work_bucket}-{timestamp}-{index:03d}.json"
        if not path.exists():
            return path
    raise RuntimeError(f"could not allocate unique ledger path in {harvest_dir}")


def _format_counts(counts: object) -> str:
    if not isinstance(counts, dict) or not counts:
        return "none"
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts))


def _print_text_summary(ledger: dict, ledger_path: Path) -> None:
    summary = ledger.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}

    typer.echo(f"ledger: {ledger_path}")
    typer.echo(
        "rows: "
        f"total={summary.get('total_rows', 0)} "
        f"processed={summary.get('processed', 0)}"
    )
    typer.echo(f"status counts: {_format_counts(summary.get('by_status'))}")
    typer.echo(f"harness counts: {_format_counts(summary.get('by_harness'))}")
    blocker_counts = summary.get("by_blocker")
    if isinstance(blocker_counts, dict) and blocker_counts:
        typer.echo(f"blocker counts: {_format_counts(blocker_counts)}")


def harvest_cmd(
    work_bucket: str,
    apply: bool = typer.Option(False, "--apply"),
    min_match: float = typer.Option(0.0, "--min-match"),
    limit: int | None = typer.Option(None, "--limit"),
    taxonomy_dir: Path | None = typer.Option(None, "--taxonomy-dir"),
    ledger: Path | None = typer.Option(None, "--ledger"),
    target_map: Path | None = typer.Option(None, "--target-map"),
    max_probes: int = typer.Option(8, "--max-probes"),
    timeout: int = typer.Option(120, "--timeout"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Run a registered harvest harness across a taxonomy work bucket."""
    repo_root = DEFAULT_MELEE_ROOT
    queue = _queue_path(repo_root, taxonomy_dir, work_bucket)
    if not queue.exists():
        typer.echo(f"harvest queue is missing: {queue}", err=True)
        raise typer.Exit(2)

    ledger_path = ledger if ledger is not None else _default_ledger_path(repo_root, work_bucket)
    kwargs = {}
    if HARVEST_RUNNER is not None:
        kwargs["runner"] = HARVEST_RUNNER
    if HARVEST_VALIDATOR is not None:
        kwargs["validator"] = HARVEST_VALIDATOR

    try:
        ledger_data = run_harvest(
            work_bucket,
            repo_root=repo_root,
            queue_path=queue,
            min_match=min_match,
            limit=limit,
            target_map_path=target_map,
            ledger_path=ledger_path,
            apply=apply,
            timeout=timeout,
            max_probes=max_probes,
            **kwargs,
        )
    except (OSError, JSONDecodeError, ValueError) as exc:
        typer.echo(f"harvest input error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if json_out:
        typer.echo(json.dumps(ledger_data, indent=2, sort_keys=True))
        return

    _print_text_summary(ledger_data, ledger_path)
