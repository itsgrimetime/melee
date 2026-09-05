from __future__ import annotations

import subprocess
from typing import Callable, Optional


def resolve_function_unit(report: dict, function: str) -> Optional[tuple[str, str]]:
    """Map a function name to (unit_name, src .c path) using build/GALE01/report.json.

    This mirrors tools/checkdiff.py:find_unit_for_function — authoritative, unlike
    symbols.txt (address-only) or splits.txt (range lookups mis-attribute).
    """
    for unit in report.get("units", []):
        for fn in unit.get("functions", []):
            if fn.get("name") == function:
                name = unit["name"]
                return name, "src/" + name.removeprefix("main/") + ".c"
    return None


GitRunner = Callable[[list], str]


def default_git_runner(repo_root: str) -> GitRunner:
    def run(args: list) -> str:
        return subprocess.run(
            ["git", "-C", repo_root, *args],
            check=True, capture_output=True, text=True,
        ).stdout
    return run


def find_match_commit(git_runner: GitRunner, function: str, file: str) -> Optional[str]:
    """Newest commit that changed the symbol in its file (pickaxe). None if none."""
    out = git_runner(["log", "--pretty=%H", "-S", function, "--", file]).strip()
    return out.splitlines()[0].strip() if out else None


def parent_sha(git_runner: GitRunner, sha: str) -> str:
    return git_runner(["rev-parse", f"{sha}~1"]).strip()


def commit_author_is_us(git_runner: GitRunner, sha: str, *, me: str = "itsgrimetime") -> bool:
    return git_runner(["log", "-1", "--pretty=%an", sha]).strip().lower() == me.lower()
