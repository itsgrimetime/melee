#!/usr/bin/env python3
"""Thin entrypoint — delegates to the worktree_doctor package.

This file exists for backward compatibility with CLI invocations
(python tools/worktree-doctor.py --fix) and tests that load this
module via spec_from_file_location.
"""

import sys
from pathlib import Path

# Make the package importable. Resolve symlinks so the wrapper works even
# when symlinked from another location (e.g., PR worktree tests).
_sys_path_entry = str(Path(__file__).resolve().parent)
if _sys_path_entry not in sys.path:
    sys.path.insert(0, _sys_path_entry)

from worktree_doctor import *  # noqa: E402, F403 — re-export all public symbols
from worktree_doctor import main as _main  # noqa: E402

# Expose sub-modules and stdlib modules that tests monkeypatch.
import worktree_doctor.utils as utils  # noqa: E402
import worktree_doctor.doctor as doctor  # noqa: E402
import worktree_doctor.checks as checks  # noqa: E402
import worktree_doctor.banner as banner  # noqa: E402
import subprocess  # noqa: E402
import shutil  # noqa: E402
import platform  # noqa: E402
import os  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_main())
