"""Banner/tooling-status helpers for worktree-doctor."""

from __future__ import annotations

import shutil
from pathlib import Path

from . import TOOLING_FILES
from .utils import run_git


BANNER_TOOL_NAMES = {
    "tools/checkdiff.py": "checkdiff",
    "tools/decomp.py": "decomp",
    "tools/workflow/status.sh": "workflow",
    "tools/workflow/create-pr.sh": "workflow",
    "tools/workflow/update-pr.sh": "workflow",
    "tools/workflow/pr-worktree.sh": "workflow",
}


def collect_banner_tooling_status(root: Path) -> tuple[str, list[str]]:
    """Derive banner-level tooling status from existence checks.

    Returns ("ok"|"partial"|"broken", missing_short_names). "broken" means a
    core tool (checkdiff.py) is absent; "partial" means some non-core tooling
    is missing.
    """
    missing: list[str] = []
    seen: set[str] = set()
    for rel_path in TOOLING_FILES:
        if (root / rel_path).exists():
            continue
        name = BANNER_TOOL_NAMES.get(rel_path, rel_path)
        if name not in seen:
            missing.append(name)
            seen.add(name)

    if shutil.which("melee-agent") is None and "melee-agent" not in seen:
        missing.append("melee-agent")
        seen.add("melee-agent")

    if not missing:
        return "ok", []
    if not (root / "tools" / "checkdiff.py").exists():
        return "broken", missing
    return "partial", missing


def banner_line(root: Path) -> str:
    branch = run_git(["branch", "--show-current"], allow_fail=True).strip()
    head = run_git(["rev-parse", "--short", "HEAD"], allow_fail=True).strip() or "?"
    branch_str = branch if branch else f"detached@{head}"

    status, missing = collect_banner_tooling_status(root)
    if status == "ok":
        tooling_str = "ok"
    elif status == "broken":
        tooling_str = "broken"
    else:
        tooling_str = f"partial:{','.join(missing)}"

    return f"WORKTREE {root} | BRANCH {branch_str} | TOOLING {tooling_str}"
