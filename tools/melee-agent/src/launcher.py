"""Worktree-resolving console launcher for melee-agent.

The installed console script is global, but this project is commonly used from
many concurrent git worktrees. Resolve the caller's worktree at invocation time
so `melee-agent` imports the CLI from the current checkout instead of whichever
worktree last ran `pip install -e`.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys


PRINT_IMPORT_PATH_ENV = "MELEE_AGENT_PRINT_SRC_CLI"


def _git_toplevel(cwd: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    if not text:
        return None
    return Path(text)


def _repo_local_package_root(cwd: Path) -> Path | None:
    root = _git_toplevel(cwd)
    if root is None:
        return None
    candidate = root / "tools" / "melee-agent"
    if (candidate / "src" / "cli").is_dir() or (candidate / "src" / "cli.py").is_file():
        return candidate.resolve()
    return None


def _installed_package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _clear_imported_src_package() -> None:
    for name in list(sys.modules):
        if name == "src" or name.startswith("src."):
            sys.modules.pop(name, None)


def _prepend_repo_package_root(package_root: Path) -> None:
    local = str(package_root)
    sys.path[:] = [entry for entry in sys.path if entry != local]
    sys.path.insert(0, local)
    _clear_imported_src_package()


def _load_cli_from_cwd():
    local_package_root = _repo_local_package_root(Path.cwd())
    installed_package_root = _installed_package_root()
    if local_package_root is not None and local_package_root != installed_package_root:
        print(
            "WARNING: melee-agent installed package is "
            f"{installed_package_root}; using repo-local package {local_package_root}",
            file=sys.stderr,
        )
        _prepend_repo_package_root(local_package_root)
    return importlib.import_module("src.cli")


def main() -> int | None:
    cli = _load_cli_from_cwd()
    if os.environ.get(PRINT_IMPORT_PATH_ENV):
        print(Path(cli.__file__).resolve())
        return 0
    return cli.main()
