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
    )
    if args.command == "cleanup":
        result = artifacts.cleanup_artifacts(report.candidates, apply=args.apply)
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


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "artifacts":
        return _artifacts_main(arguments[1:])

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
