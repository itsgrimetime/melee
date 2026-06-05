"""CLI wrapper for taxonomy harvest sweeps."""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path

import typer

from src.harvest import (
    HarnessRunner,
    HarvestFilters,
    ValidatorRunner,
    preview_harvest_queue,
    run_harvest,
    summarize_harvest_ledgers,
)

from ._common import DEFAULT_MELEE_ROOT

HARVEST_RUNNER: HarnessRunner | None = None
HARVEST_VALIDATOR: ValidatorRunner | None = None


def _queue_path(repo_root: Path, taxonomy_dir: Path | None, work_bucket: str) -> Path:
    if taxonomy_dir is not None:
        direct = taxonomy_dir / f"{work_bucket}.tsv"
        nested = taxonomy_dir / "queues" / f"{work_bucket}.tsv"
        if direct.exists():
            return direct
        if nested.exists() or (taxonomy_dir / "queues").is_dir():
            return nested
        return direct
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


def _split_csv_values(values: list[str]) -> tuple[str, ...]:
    parsed = []
    for raw in values:
        parsed.extend(part.strip() for part in raw.split(",") if part.strip())
    return tuple(dict.fromkeys(parsed))


def _parse_harvest_filters(
    where: list[str],
    exclude_source_actionability: list[str],
) -> HarvestFilters | None:
    where_map: dict[str, list[str]] = {}
    for raw in where:
        if "=" not in raw:
            raise ValueError("--where must use FIELD=VALUE")
        field_name, value = raw.split("=", 1)
        field_name = field_name.strip()
        value = value.strip()
        if not field_name or not value:
            raise ValueError("--where must use FIELD=VALUE")
        where_map.setdefault(field_name, []).append(value)
    filters = HarvestFilters(
        where={
            field_name: tuple(dict.fromkeys(values))
            for field_name, values in where_map.items()
        },
        exclude_source_actionability=_split_csv_values(
            exclude_source_actionability
        ),
    )
    return filters if filters.is_active() else None


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


def _expand_ledger_args(args: list[str]) -> list[Path]:
    if not args:
        raise ValueError("at least one harvest ledger path is required")
    paths: list[Path] = []
    for raw in args:
        if raw.startswith("-"):
            raise ValueError(f"unknown summarize option: {raw}")
        expanded = os.path.expanduser(raw)
        matches = sorted(glob.glob(expanded)) if glob.has_magic(expanded) else [expanded]
        if not matches:
            raise ValueError(f"harvest ledger not found: {raw}")
        paths.extend(Path(match) for match in matches)
    return paths


def _format_items(values: object, *, limit: int = 8) -> str:
    if not isinstance(values, list) or not values:
        return "none"
    head = [str(value) for value in values[:limit]]
    suffix = "" if len(values) <= limit else f", +{len(values) - limit} more"
    return ", ".join(head) + suffix


def _format_preview_filters(filters: object) -> str:
    if not isinstance(filters, dict) or not filters:
        return "none"
    parts: list[str] = []
    where = filters.get("where")
    if isinstance(where, dict):
        for field_name in sorted(where):
            values = where[field_name]
            if isinstance(values, list):
                parts.append(f"where {field_name}={','.join(map(str, values))}")
    excludes = filters.get("exclude_source_actionability")
    if isinstance(excludes, list) and excludes:
        parts.append(
            "exclude_source_actionability="
            f"{','.join(str(value) for value in excludes)}"
        )
    return "; ".join(parts) if parts else "none"


def _format_preview_facet_entries(entries: object) -> str:
    if not isinstance(entries, list) or not entries:
        return "none"
    formatted: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        formatted.append(f"{entry.get('value')}={entry.get('count')}")
    return ", ".join(formatted) if formatted else "none"


def _print_harvest_preview(preview: dict[str, object]) -> None:
    counts = preview.get("counts")
    if not isinstance(counts, dict):
        counts = {}
    typer.echo(f"preview: {preview.get('work_bucket')}")
    typer.echo(f"queue: {preview.get('taxonomy_queue')}")
    typer.echo(
        "rows: "
        f"queue={counts.get('queue_rows', 0)} "
        f"eligible={counts.get('eligible_rows', 0)} "
        f"matching={counts.get('matching_rows', 0)} "
        f"would_process={counts.get('would_process_rows', 0)}"
    )
    typer.echo(f"filters: {_format_preview_filters(preview.get('filters'))}")
    facets = preview.get("facets")
    if isinstance(facets, dict):
        typer.echo(f"facets ({preview.get('facet_source')}):")
        for field_name in sorted(facets):
            typer.echo(
                "  "
                f"{field_name}: "
                f"{_format_preview_facet_entries(facets[field_name])}"
            )
    near_miss = preview.get("near_miss_facets")
    if counts.get("matching_rows", 0) == 0 and isinstance(near_miss, dict):
        typer.echo("near misses:")
        for field_name in sorted(near_miss):
            typer.echo(
                "  "
                f"{field_name}: "
                f"{_format_preview_facet_entries(near_miss[field_name])}"
            )
    sample = preview.get("sample")
    typer.echo("sample:")
    if not isinstance(sample, list) or not sample:
        typer.echo("  none")
        return
    for row in sample:
        if not isinstance(row, dict):
            continue
        match = row.get("match_percent")
        function = row.get("function")
        parts = [
            f"  {function}",
            f"{match}%",
            f"harness={row.get('harness')}",
            f"headline_tool={row.get('headline_tool')}",
        ]
        next_command = row.get("next_command")
        frame_next_command = row.get("frame_next_command")
        if next_command:
            parts.append(f"next_command={next_command}")
        if frame_next_command:
            parts.append(f"frame_next_command={frame_next_command}")
        typer.echo(" ".join(str(part) for part in parts))


def _print_harvest_roi_summary(summary: dict[str, object]) -> None:
    typer.echo(f"ledgers: {summary.get('ledger_count', 0)}")
    typer.echo(f"rows: total={summary.get('total_rows', 0)}")
    typer.echo(f"status counts: {_format_counts(summary.get('by_status'))}")
    typer.echo(f"bucket counts: {_format_counts(summary.get('by_work_bucket'))}")
    typer.echo(f"harness counts: {_format_counts(summary.get('by_harness'))}")
    blocker_counts = summary.get("by_blocker")
    if isinstance(blocker_counts, dict) and blocker_counts:
        typer.echo(f"blocker counts: {_format_counts(blocker_counts)}")
    typer.echo(
        "retained source functions: "
        f"{_format_items(summary.get('retained_source_functions'))}"
    )
    repeated = summary.get("repeated_blockers")
    if isinstance(repeated, list) and repeated:
        typer.echo("repeated blockers:")
        for blocker in repeated:
            if not isinstance(blocker, dict):
                continue
            typer.echo(
                "  "
                f"{blocker.get('blocker')} "
                f"count={blocker.get('count')} "
                f"functions={_format_items(blocker.get('functions'), limit=5)}"
            )
    typer.echo(f"suggested impact: impact={summary.get('suggested_impact')}")


def harvest_cmd(
    ctx: typer.Context,
    work_bucket: str,
    apply: bool = typer.Option(False, "--apply"),
    compose: bool = typer.Option(False, "--compose"),
    min_match: float = typer.Option(0.0, "--min-match"),
    limit: int | None = typer.Option(None, "--limit"),
    taxonomy_dir: Path | None = typer.Option(None, "--taxonomy-dir"),
    ledger: Path | None = typer.Option(None, "--ledger"),
    target_map: Path | None = typer.Option(None, "--target-map"),
    max_probes: int = typer.Option(8, "--max-probes"),
    timeout: int = typer.Option(120, "--timeout"),
    where: list[str] = typer.Option([], "--where"),
    exclude_source_actionability: list[str] = typer.Option(
        [],
        "--exclude-source-actionability",
    ),
    preview: bool = typer.Option(False, "--preview"),
    preview_sample: int = typer.Option(10, "--preview-sample"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Run a registered harvest harness across a taxonomy work bucket."""
    repo_root = DEFAULT_MELEE_ROOT
    if work_bucket == "summarize":
        try:
            ledger_paths = _expand_ledger_args(list(ctx.args))
            summary = summarize_harvest_ledgers(ledger_paths)
        except (OSError, JSONDecodeError, ValueError) as exc:
            typer.echo(f"harvest summary input error: {exc}", err=True)
            raise typer.Exit(2) from exc

        if json_out:
            typer.echo(json.dumps(summary, indent=2, sort_keys=True))
            return
        _print_harvest_roi_summary(summary)
        return

    if ctx.args:
        typer.echo(f"unexpected harvest arguments: {' '.join(ctx.args)}", err=True)
        raise typer.Exit(2)

    queue = _queue_path(repo_root, taxonomy_dir, work_bucket)
    if not queue.exists():
        typer.echo(f"harvest queue is missing: {queue}", err=True)
        raise typer.Exit(2)

    kwargs = {}
    if HARVEST_RUNNER is not None:
        kwargs["runner"] = HARVEST_RUNNER
    if HARVEST_VALIDATOR is not None:
        kwargs["validator"] = HARVEST_VALIDATOR

    try:
        filters = _parse_harvest_filters(where, exclude_source_actionability)
        if preview:
            preview_data = preview_harvest_queue(
                queue,
                work_bucket=work_bucket,
                repo_root=repo_root,
                min_match=min_match,
                limit=limit,
                target_map_path=target_map,
                filters=filters,
                sample_limit=preview_sample,
            )
            if json_out:
                typer.echo(json.dumps(preview_data, indent=2, sort_keys=True))
                return
            _print_harvest_preview(preview_data)
            return
        ledger_path = (
            ledger if ledger is not None else _default_ledger_path(repo_root, work_bucket)
        )
        if filters is not None and filters.is_active():
            preview_data = preview_harvest_queue(
                queue,
                work_bucket=work_bucket,
                repo_root=repo_root,
                min_match=min_match,
                limit=limit,
                target_map_path=target_map,
                filters=filters,
                sample_limit=0,
            )
            if preview_data["counts"]["matching_rows"] == 0:
                raise ValueError(
                    "filters matched zero rows; run with --preview to inspect "
                    "current queue facets"
                )
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_data = run_harvest(
            work_bucket,
            repo_root=repo_root,
            queue_path=queue,
            min_match=min_match,
            limit=limit,
            target_map_path=target_map,
            ledger_path=ledger_path,
            apply=apply,
            compose=compose,
            timeout=timeout,
            max_probes=max_probes,
            filters=filters,
            **kwargs,
        )
    except (OSError, JSONDecodeError, ValueError) as exc:
        typer.echo(f"harvest input error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if json_out:
        typer.echo(json.dumps(ledger_data, indent=2, sort_keys=True))
        return

    _print_text_summary(ledger_data, ledger_path)
