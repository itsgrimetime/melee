"""`debug artifacts ...` — retained diagnostic evidence reporting and pruning."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ...mwcc_debug.artifacts import (
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_MAX_TOTAL_BYTES,
    ArtifactReport,
    PrunePlan,
    SkippedRun,
    prune_runs,
    report_runs,
)

artifacts_app = typer.Typer(
    help="Inspect and safely prune retained diagnostic evidence."
)


def _skipped_payload(skipped: tuple[SkippedRun, ...]) -> list[dict[str, str]]:
    return [
        {"path": str(item.path), "reason": item.reason}
        for item in skipped
    ]


def _report_payload(report: ArtifactReport) -> dict[str, object]:
    return {
        "artifact_root": str(report.artifact_root),
        "completed_runs": report.completed_runs,
        "active_runs": report.active_runs,
        "completed_bytes": report.completed_bytes,
        "cache_bytes": report.cache_bytes,
        "runs": [
            {
                "path": str(run.run_dir),
                "state": run.state,
                "created_at": run.created_at,
                "finished_at": run.finished_at,
                "evidence_bytes": run.evidence_bytes,
            }
            for run in report.runs
        ],
        "skipped": _skipped_payload(report.skipped),
    }


def _prune_payload(
    plan: PrunePlan,
    *,
    max_age_days: float,
    max_total_bytes: int,
    apply: bool,
) -> dict[str, object]:
    return {
        "mode": "apply" if apply else "dry-run",
        "max_age_days": max_age_days,
        "max_total_bytes": max_total_bytes,
        "planned_run_dirs": [str(path) for path in plan.planned_run_dirs],
        "removed_run_dirs": [str(path) for path in plan.removed_run_dirs],
        "reclaimed_bytes": plan.reclaimed_bytes,
        "skipped": _skipped_payload(plan.skipped),
    }


def _emit_skipped(skipped: tuple[SkippedRun, ...]) -> None:
    if not skipped:
        return
    typer.echo("Skipped:")
    for item in skipped:
        typer.echo(f"  {item.path}: {item.reason}")


@artifacts_app.command("report")
def artifacts_report(
    artifact_root: Path | None = typer.Option(
        None,
        "--artifact-root",
        help="Artifact root, relative to the Melee root unless absolute.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON.",
    ),
) -> None:
    """Report retained diagnostic evidence without modifying it."""
    from src.cli.debug import DEFAULT_MELEE_ROOT

    report = report_runs(DEFAULT_MELEE_ROOT, artifact_root=artifact_root)
    if json_out:
        typer.echo(json.dumps(_report_payload(report), indent=2, sort_keys=True))
        return

    typer.echo(f"Artifact root: {report.artifact_root}")
    typer.echo(f"Completed runs: {report.completed_runs}")
    typer.echo(f"Active runs: {report.active_runs}")
    typer.echo(f"Completed evidence bytes: {report.completed_bytes}")
    typer.echo(f"MWCC debug cache bytes: {report.cache_bytes}")
    if report.runs:
        typer.echo("Runs:")
        for run in report.runs:
            finished_at = run.finished_at or "active"
            typer.echo(
                f"  {run.state}: {run.evidence_bytes} bytes, "
                f"finished {finished_at}, {run.run_dir}"
            )
    _emit_skipped(report.skipped)


@artifacts_app.command("prune")
def artifacts_prune(
    artifact_root: Path | None = typer.Option(
        None,
        "--artifact-root",
        help="Artifact root, relative to the Melee root unless absolute.",
    ),
    max_age_days: float = typer.Option(
        DEFAULT_MAX_AGE_DAYS,
        "--max-age-days",
        min=0,
        help="Remove terminal runs older than this many days.",
    ),
    max_total_bytes: int = typer.Option(
        DEFAULT_MAX_TOTAL_BYTES,
        "--max-total-bytes",
        min=0,
        help="Maximum retained evidence bytes after pruning.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Delete the planned run directories.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON.",
    ),
) -> None:
    """Preview, or explicitly apply, conservative artifact-run pruning."""
    from src.cli.debug import DEFAULT_MELEE_ROOT

    plan = prune_runs(
        DEFAULT_MELEE_ROOT,
        artifact_root=artifact_root,
        max_age_days=max_age_days,
        max_total_bytes=max_total_bytes,
        apply=apply,
    )
    if json_out:
        typer.echo(
            json.dumps(
                _prune_payload(
                    plan,
                    max_age_days=max_age_days,
                    max_total_bytes=max_total_bytes,
                    apply=apply,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return

    mode = "apply" if apply else "dry-run"
    typer.echo(f"Prune mode: {mode}")
    typer.echo(f"Planned run directories: {len(plan.planned_run_dirs)}")
    for run_dir in plan.planned_run_dirs:
        typer.echo(f"  {run_dir}")
    typer.echo(f"Removed run directories: {len(plan.removed_run_dirs)}")
    for run_dir in plan.removed_run_dirs:
        typer.echo(f"  {run_dir}")
    typer.echo(f"Reclaimed evidence bytes: {plan.reclaimed_bytes}")
    _emit_skipped(plan.skipped)
