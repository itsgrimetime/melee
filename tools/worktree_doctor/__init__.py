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
import os
from pathlib import Path

from .utils import detect_repo_root, ROOT  # noqa: E402 — ROOT computed in utils

# ── constants ────────────────────────────────────────────────────────────────

TOOLING_FILES = [
    "tools/checkdiff.py",
    "tools/decomp.py",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="Apply safe local bootstrap fixes")
    parser.add_argument(
        "--banner",
        action="store_true",
        help="Print a single-line worktree/branch/tooling status and exit 0",
    )
    args = parser.parse_args()
    if args.banner:
        print(banner_line(ROOT))
        return 0
    return Doctor(fix=args.fix).run()
