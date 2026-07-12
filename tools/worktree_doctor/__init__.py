"""Check and optionally repair local agent workflow prerequisites.

Package layout:
  doctor.py   — Doctor class, CheckResult, local-exclude helpers
  utils.py    — Platform detection, process helpers, entrypoint checks
  checks.py   — Knowledge-source and staleness check functions
  banner.py   — Banner line and tooling-status helpers

Public API re-exported from sub-modules for backward compatibility with
callers that import from the old monolithic worktree-doctor.py.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .utils import ROOT, detect_repo_root as detect_repo_root  # noqa: E402 — ROOT computed in utils

# ── constants ────────────────────────────────────────────────────────────────

TOOLING_FILES = [
    "tools/checkdiff.py",
    "tools/decomp.py",
    "tools/mwcc_debug/.gitignore",
    "tools/mwcc_debug/Makefile",
    "tools/mwcc_debug/README.md",
    "tools/mwcc_debug/UPSTREAM",
    "tools/mwcc_debug/build_macos.sh",
    "tools/mwcc_debug/build_wibo.sh",
    "tools/mwcc_debug/mwcc_debug.c",
    "tools/mwcc_debug/mwcc_debug.def",
    "tools/mwcc_debug/patch_mwcceppc_for_wibo.py",
    "tools/mwcc_debug/scripts/ghidra_query_coalesce_pipeline.py",
    "tools/mwcc_debug/scripts/ghidra_query_diagnostic.py",
    "tools/mwcc_debug/scripts/setup_ghidra.sh",
    "tools/mwcc_debug/smoke_test.c",
    "tools/mwcc_debug/smoke_test.sh",
    "tools/mwcc_debug/wibo-dllmain.patch",
    "tools/mwcc_debug/win/run_pcdump.ps1",
    "tools/workflow/status.sh",
    "tools/workflow/create-pr.sh",
    "tools/workflow/mwcc-inspect.sh",
    "tools/workflow/update-pr.sh",
    "tools/workflow/pr-worktree.sh",
]

DOL_CANDIDATES = [
    Path.home() / "code" / "melee" / "orig" / "GALE01" / "sys" / "main.dol",
    Path.home() / ".config" / "decomp-me" / "orig" / "GALE01" / "main.dol",
]

DISCORD_SEARCH_CANDIDATES = [
    Path("/Users/mike/code/discord-archive-mcp/.venv/bin/discord-search"),
]

STALE_GRACE_SECONDS = 1.0
REPORT_REFRESH_FIX = "run: python configure.py && ninja build/GALE01/report.json"
REPORT_REFRESH_TIMEOUT_SECONDS = 300
WIBO_DOWNLOAD_TAG = "1.0.0"
DTK_DOWNLOAD_TAG = "v1.8.3"

COMPILE_RULES = {"mwcc", "mwcc_sjis", "mwcc_extab", "mwcc_sjis_extab", "as"}

# ── public API re-exports ────────────────────────────────────────────────────

from .doctor import (  # noqa: E402, F401
    CheckResult,
    Doctor,
    TRACKED_TOOLING_EXCLUDE_PATTERNS,
    blocked_tracked_tooling_exclude_patterns,
    collect_local_exclude_warnings,
    has_tracked_path_under,
    local_exclude_path,
    remove_blocked_tracked_tooling_excludes,
)
from .utils import (  # noqa: E402, F401
    build_table_typer,
    collect_melee_agent_distribution_warnings,
    collect_melee_agent_entrypoint_warnings,
    detect_macho_arch,
    entrypoint_uses_worktree_launcher,
    install_base_dol,
    is_stale_melee_agent_entrypoint,
    redownload_dtk,
    refresh_report_json,
    reinstall_repo_melee_agent,
    rel_to_root,
    resolve_melee_agent_module_path,
    restore_from_master,
    run_cmd,
    run_git,
)
from .checks import (  # noqa: E402, F401
    collect_knowledge_source_warnings,
    collect_stale_state_warnings,
    newest_relevant_input,
    parse_compile_edges,
    repair_ninja_deps_if_corrupt,
    resolve_discord_search,
    stale_compile_edges,
)
from .banner import (  # noqa: E402, F401
    BANNER_TOOL_NAMES,
    banner_line,
    collect_banner_tooling_status,
)
from .assets import (  # noqa: E402, F401
    ASSET_PATHS,
    CACHE_SCHEMA_VERSION,
    AssetResult,
    default_cache_root,
    hydrate_shared_assets,
    inspect_hydrated_assets,
    seed_shared_assets,
)

# Re-export detect_repo_root so tests that access module.ROOT and
# module.detect_repo_root both work without extra imports.
# noqa: F811 — re-export of the same name already imported above


def _artifact_candidate_payload(candidate) -> dict[str, object]:
    age_seconds = (
        None
        if candidate.newest_mtime is None
        else max(0.0, time.time() - candidate.newest_mtime)
    )
    return {
        "worktree": str(candidate.worktree),
        "root": str(candidate.root),
        "kind": candidate.kind,
        "size_bytes": candidate.size_bytes,
        "newest_mtime": candidate.newest_mtime,
        "age_seconds": age_seconds,
        "eligible": candidate.eligible,
        "skip_reasons": list(candidate.skip_reasons),
    }


def _artifact_payload(report, result, *, mode: str, min_age_days: float, min_bytes: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": mode,
        "thresholds": {
            "min_age_days": min_age_days,
            "min_bytes": min_bytes,
        },
        "worktrees": [str(worktree) for worktree in report.worktrees],
        "candidates": [_artifact_candidate_payload(candidate) for candidate in report.candidates],
        "planned": [str(root) for root in result.planned],
        "removed": [str(root) for root in result.removed],
        "reclaimed_bytes": result.reclaimed_bytes,
        "skipped": [
            {"root": str(skip.root), "reason": skip.reason}
            for skip in result.skipped
        ],
    }


def _print_artifact_payload(payload: dict[str, object]) -> None:
    print(f"mode: {payload['mode']}")
    thresholds = payload["thresholds"]
    assert isinstance(thresholds, dict)
    print(
        "thresholds: "
        f"min_age_days={thresholds['min_age_days']} min_bytes={thresholds['min_bytes']}"
    )
    for candidate in payload["candidates"]:
        assert isinstance(candidate, dict)
        age = candidate["age_seconds"]
        age_text = "unknown" if age is None else f"{age:.0f}s"
        reasons = candidate["skip_reasons"]
        assert isinstance(reasons, list)
        reason_text = ",".join(reasons) if reasons else "-"
        eligibility = "eligible" if candidate["eligible"] else "ineligible"
        print(
            f"worktree={candidate['worktree']} candidate={candidate['root']} "
            f"bytes={candidate['size_bytes']} age={age_text} "
            f"eligibility={eligibility} reasons={reason_text}"
        )
    print(
        "cleanup: "
        f"planned={len(payload['planned'])} removed={len(payload['removed'])} "
        f"reclaimed_bytes={payload['reclaimed_bytes']} skipped={len(payload['skipped'])}"
    )
    for skipped in payload["skipped"]:
        assert isinstance(skipped, dict)
        print(f"skipped: root={skipped['root']} reason={skipped['reason']}")


def _artifacts_main(argv: Sequence[str]) -> int:
    from . import artifacts

    parser = argparse.ArgumentParser(
        prog=f"{Path(sys.argv[0]).name} artifacts",
        description="Report and clean ignored worktree artifacts",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("report", "cleanup"):
        command = commands.add_parser(name)
        command.add_argument(
            "--scan-root",
            action="append",
            type=Path,
            default=[],
            metavar="PATH",
            help="Also inspect Git worktrees discovered beneath PATH",
        )
        command.add_argument(
            "--min-age-days",
            type=float,
            default=artifacts.DEFAULT_MIN_AGE_DAYS,
            help="Minimum newest-file age required for cleanup eligibility (default: %(default)s)",
        )
        command.add_argument(
            "--min-bytes",
            type=int,
            default=artifacts.DEFAULT_MIN_BYTES,
            help="Minimum artifact size required for cleanup eligibility (default: %(default)s)",
        )
        command.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
        if name == "cleanup":
            command.add_argument(
                "--apply",
                action="store_true",
                help="Actually remove only revalidated eligible candidates",
            )

    args = parser.parse_args(argv)
    if args.min_age_days < 0:
        parser.error("--min-age-days must be non-negative")
    if args.min_bytes < 0:
        parser.error("--min-bytes must be non-negative")

    worktrees = artifacts.discover_worktrees(ROOT, scan_roots=args.scan_root)
    report = artifacts.inspect_artifacts(
        worktrees,
        min_age_days=args.min_age_days,
        min_bytes=args.min_bytes,
        protected_worktrees=(ROOT,),
    )
    if args.command == "cleanup":
        result = artifacts.cleanup_artifacts(
            report.candidates,
            apply=args.apply,
            protected_worktrees=(ROOT,),
        )
        mode = "cleanup" if args.apply else "dry-run"
    else:
        result = artifacts.CleanupResult((), (), 0, ())
        mode = "report"
    payload = _artifact_payload(
        report,
        result,
        mode=mode,
        min_age_days=args.min_age_days,
        min_bytes=args.min_bytes,
    )
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        _print_artifact_payload(payload)
    return 0


def _print_asset_result(result: AssetResult) -> None:
    print(f"status: {result.status}")
    print(f"cache_root: {result.cache_root}")
    print(f"linked: {len(result.linked)}")
    for linked in result.linked:
        print(f"  {linked}")
    print(f"skipped: {len(result.skipped)}")
    for skipped in result.skipped:
        print(f"  {skipped}")


def _assets_main(argv: Sequence[str]) -> int:
    from . import assets

    parser = argparse.ArgumentParser(
        prog=f"{Path(sys.argv[0]).name} assets",
        description="Seed and hydrate immutable shared worktree assets",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed")
    seed.add_argument("--source", required=True, type=Path, metavar="PATH")
    seed.add_argument("--cache-root", type=Path, metavar="PATH")
    hydrate = commands.add_parser("hydrate")
    hydrate.add_argument("--asset-source", type=Path, metavar="PATH")
    hydrate.add_argument("--cache-root", type=Path, metavar="PATH")
    args = parser.parse_args(argv)

    cache_root = args.cache_root or assets.default_cache_root()
    if args.command == "seed":
        result = assets.seed_shared_assets(args.source, cache_root)
    else:
        result = assets.hydrate_shared_assets(
            ROOT,
            cache_root,
            asset_source=args.asset_source,
        )
    _print_asset_result(result)
    return 0 if result.status in {
        "seeded",
        "cache-exists",
        "hydrated",
        "cache-missing",
        "no-assets",
    } else 1


def _worktree_record_payload(record, *, inspected_at: float) -> dict[str, object]:
    idle_seconds = (
        None
        if record.last_activity is None
        else inspected_at - record.last_activity
    )
    return {
        "path": str(record.path),
        "head": record.head,
        "branch": record.branch,
        "estimated_disk_bytes": record.estimated_disk_bytes,
        "last_activity": record.last_activity,
        "idle_seconds": idle_seconds,
        "dirty": record.dirty,
        "active_pids": list(record.active_pids),
        "merged_into_master": record.merged_into_master,
        "ignored_path_count": len(record.ignored_entries),
        "unapproved_ignored_paths": [
            str(path) for path in record.unapproved_ignored_paths
        ],
        "eligible": record.eligible,
        "skip_reasons": list(record.skip_reasons),
    }


def _worktrees_payload(report, result, *, mode: str) -> dict[str, object]:
    authoritative_report = (
        result.authoritative_report
        if result is not None and result.authoritative_report is not None
        else report
    )
    records = sorted(
        authoritative_report.records,
        key=lambda record: str(record.canonical_path),
    )
    if result is None:
        planned = ()
        removed = ()
        skipped = ()
        errors = [
            {"reason": reason, "detail": "initial inspection failed"}
            for reason in report.global_errors
        ]
    else:
        planned = result.planned
        removed = result.removed
        skipped = result.skipped
        errors = [
            {"reason": error.reason, "detail": error.detail}
            for error in result.errors
        ]
    return {
        "schema_version": 1,
        "resource": "worktrees",
        "mode": mode,
        "thresholds": {"min_idle_hours": authoritative_report.min_idle_hours},
        "repository": {
            "root": str(authoritative_report.repo_root),
            "common_git_dir": str(authoritative_report.common_git_dir),
            "current_worktree": str(authoritative_report.current_worktree),
        },
        "worktrees": [
            _worktree_record_payload(
                record, inspected_at=authoritative_report.inspected_at
            )
            for record in records
        ],
        "planned": [
            {
                "path": str(candidate.path),
                "branch": candidate.branch,
                "head": candidate.head,
                "estimated_disk_bytes": candidate.estimated_disk_bytes,
                "last_activity": candidate.last_activity,
            }
            for candidate in planned
        ],
        "removed": [
            {
                "path": str(removal.path),
                "branch": removal.branch,
                "head": removal.head,
                "branch_head_after": removal.branch_head_after,
                "estimated_reclaimed_bytes": removal.estimated_reclaimed_bytes,
            }
            for removal in removed
        ],
        "skipped": [
            {
                "path": str(skip.path),
                "branch": skip.branch,
                "head": skip.head,
                "phase": skip.phase,
                "reason": skip.reason,
            }
            for skip in skipped
        ],
        "errors": errors,
        "summary": {
            "eligible_count": sum(record.eligible for record in records),
            "estimated_planned_bytes": sum(
                candidate.estimated_disk_bytes for candidate in planned
            ),
            "removed_count": len(removed),
            "estimated_reclaimed_bytes": sum(
                removal.estimated_reclaimed_bytes for removal in removed
            ),
        },
    }


def _format_worktree_value(value: object) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _escape_worktree_text(value: object) -> str:
    rendered = json.dumps(str(value), ensure_ascii=True)
    return rendered[1:-1]


def _format_worktree_list(values: Sequence[object]) -> str:
    return json.dumps(
        list(values), ensure_ascii=True, separators=(",", ":")
    )


def _print_worktrees_payload(payload: dict[str, object]) -> None:
    print(f"mode: {payload['mode']}")
    thresholds = payload["thresholds"]
    repository = payload["repository"]
    assert isinstance(thresholds, dict)
    assert isinstance(repository, dict)
    print(f"thresholds: min_idle_hours={thresholds['min_idle_hours']}")
    print(
        "repository: "
        f"root={_escape_worktree_text(repository['root'])} "
        f"common_git_dir={_escape_worktree_text(repository['common_git_dir'])} "
        f"current_worktree={_escape_worktree_text(repository['current_worktree'])}"
    )
    for record in payload["worktrees"]:
        assert isinstance(record, dict)
        reasons = record["skip_reasons"]
        assert isinstance(reasons, list)
        reason_text = ",".join(_escape_worktree_text(reason) for reason in reasons) or "-"
        eligibility = "eligible" if record["eligible"] else "ineligible"
        branch = (
            _escape_worktree_text(record["branch"])
            if record["branch"] is not None
            else "-"
        )
        active_pids = record["active_pids"]
        unapproved = record["unapproved_ignored_paths"]
        assert isinstance(active_pids, list)
        assert isinstance(unapproved, list)
        print(
            f"worktree={_escape_worktree_text(record['path'])} branch={branch} "
            f"head={_escape_worktree_text(str(record['head'])[:12])} "
            f"estimated_disk_bytes={record['estimated_disk_bytes']} "
            f"last_activity={_format_worktree_value(record['last_activity'])} "
            f"idle_seconds={_format_worktree_value(record['idle_seconds'])} "
            f"dirty={_format_worktree_value(record['dirty'])} "
            f"active_pids={_format_worktree_list(active_pids)} "
            f"merged_into_master={_format_worktree_value(record['merged_into_master'])} "
            f"ignored_path_count={record['ignored_path_count']} "
            f"unapproved_ignored_path_count={len(unapproved)} "
            f"unapproved_ignored_paths={_format_worktree_list(unapproved[:20])} "
            f"eligibility={eligibility} reasons={reason_text}"
        )
    for candidate in payload["planned"]:
        assert isinstance(candidate, dict)
        print(
            f"planned: path={_escape_worktree_text(candidate['path'])} "
            f"branch={_escape_worktree_text(candidate['branch'])} "
            f"head={_escape_worktree_text(str(candidate['head'])[:12])} "
            f"estimated_disk_bytes={candidate['estimated_disk_bytes']} "
            f"last_activity={_format_worktree_value(candidate['last_activity'])}"
        )
    for removal in payload["removed"]:
        assert isinstance(removal, dict)
        print(
            f"removed: path={_escape_worktree_text(removal['path'])} "
            f"branch={_escape_worktree_text(removal['branch'])} "
            f"head={_escape_worktree_text(str(removal['head'])[:12])} "
            f"branch_head_after={_escape_worktree_text(removal['branch_head_after'])} "
            f"estimated_reclaimed_bytes={removal['estimated_reclaimed_bytes']}"
        )
    for skip in payload["skipped"]:
        assert isinstance(skip, dict)
        print(
            f"skipped: path={_escape_worktree_text(skip['path'])} "
            f"branch={_escape_worktree_text(skip['branch'])} "
            f"head={_escape_worktree_text(str(skip['head'])[:12])} "
            f"phase={_escape_worktree_text(skip['phase'])} "
            f"reason={_escape_worktree_text(skip['reason'])}"
        )
    for error in payload["errors"]:
        assert isinstance(error, dict)
        print(
            f"error: reason={_escape_worktree_text(error['reason'])} "
            f"detail={_escape_worktree_text(error['detail'])}"
        )
    summary = payload["summary"]
    assert isinstance(summary, dict)
    print(
        "summary: "
        f"eligible_count={summary['eligible_count']} "
        f"estimated_planned_bytes={summary['estimated_planned_bytes']} "
        f"removed_count={summary['removed_count']} "
        f"estimated_reclaimed_bytes={summary['estimated_reclaimed_bytes']}"
    )


def _worktrees_status(payload: dict[str, object], *, mode: str) -> int:
    errors = payload["errors"]
    skipped = payload["skipped"]
    planned = payload["planned"]
    removed = payload["removed"]
    assert isinstance(errors, list)
    assert isinstance(skipped, list)
    assert isinstance(planned, list)
    assert isinstance(removed, list)
    if mode != "apply":
        return 1 if errors else 0
    if errors and not planned and not removed:
        return 1
    if errors or skipped or len(removed) != len(planned):
        return 2
    return 0


def _worktrees_main(argv: Sequence[str]) -> int:
    from . import worktrees

    parser = argparse.ArgumentParser(
        prog=f"{Path(sys.argv[0]).name} worktrees",
        description="Report and safely retire idle agent worktrees",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("report", "retire"):
        command = commands.add_parser(name)
        command.add_argument(
            "--min-idle-hours",
            type=float,
            default=24.0,
            help="Minimum worktree idle time required for eligibility (default: %(default)s)",
        )
        command.add_argument(
            "--json", action="store_true", help="Emit machine-readable JSON"
        )
        if name == "retire":
            command.add_argument(
                "--apply",
                action="store_true",
                help="Retire freshly revalidated eligible worktrees",
            )
    args = parser.parse_args(argv)
    if args.min_idle_hours < 0 or not math.isfinite(args.min_idle_hours):
        parser.error("--min-idle-hours must be finite and non-negative")

    mode = "apply" if args.command == "retire" and args.apply else (
        "dry-run" if args.command == "retire" else "report"
    )
    try:
        report = worktrees.inspect_worktrees(
            ROOT,
            current_worktree=ROOT,
            min_idle_hours=args.min_idle_hours,
        )
    except worktrees.WorktreeParseError as error:
        report = worktrees.WorktreeReport(
            repo_root=ROOT,
            common_git_dir=ROOT / ".git",
            current_worktree=ROOT,
            min_idle_hours=args.min_idle_hours,
            inspected_at=time.time(),
            records=(),
            global_errors=(),
        )
        result = worktrees.RetirementResult(
            planned=(),
            removed=(),
            skipped=(),
            errors=(
                worktrees.RetirementError(
                    reason="worktree-porcelain-invalid", detail=str(error)
                ),
            ),
            authoritative_report=report,
        )
    else:
        if args.command == "report":
            result = None
        else:
            result = worktrees.retire_worktrees(report, apply=args.apply)

    payload = _worktrees_payload(report, result, mode=mode)
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        _print_worktrees_payload(payload)
    return _worktrees_status(payload, mode=mode)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "worktrees":
        return _worktrees_main(arguments[1:])
    if arguments and arguments[0] == "artifacts":
        return _artifacts_main(arguments[1:])
    if arguments and arguments[0] == "assets":
        return _assets_main(arguments[1:])

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="Apply safe local bootstrap fixes")
    parser.add_argument(
        "--banner",
        action="store_true",
        help="Print a single-line worktree/branch/tooling status and exit 0",
    )
    args = parser.parse_args(arguments)
    if args.banner:
        print(banner_line(ROOT))
        return 0
    return Doctor(fix=args.fix).run()
