#!/usr/bin/env python3
"""Thin entrypoint — delegates to the worktree_doctor package.

This file exists for backward compatibility with CLI invocations
(python tools/worktree-doctor.py --fix) and tests that load this
module via spec_from_file_location.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

# Make the package importable. Resolve symlinks so the wrapper works even
# when symlinked from another location (e.g., PR worktree tests).
_sys_path_entry = str(Path(__file__).resolve().parent)
if _sys_path_entry not in sys.path:
    sys.path.insert(0, _sys_path_entry)

import os  # noqa: E402, F401
import platform  # noqa: E402, F401
import shutil  # noqa: E402, F401
import subprocess  # noqa: E402, F401

# Expose sub-modules and stdlib modules that tests monkeypatch.
import worktree_doctor as _worktree_doctor  # noqa: E402
import worktree_doctor.banner as banner  # noqa: E402, F401
import worktree_doctor.checks as checks  # noqa: E402, F401
import worktree_doctor.doctor as doctor  # noqa: E402, F401
import worktree_doctor.utils as utils  # noqa: E402, F401
from worktree_doctor import *  # noqa: E402, F403 — re-export all public symbols
from worktree_doctor import main as _main  # noqa: E402


def _bind_current_repo_root() -> None:
    """Keep a symlinked wrapper scoped to its invoking Git worktree."""
    root = utils.detect_repo_root()
    globals()["ROOT"] = root
    _worktree_doctor.ROOT = root
    utils.ROOT = root


_bind_current_repo_root()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the package entrypoint while retaining the legacy script import API."""
    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
