# tools/melee-agent/src/backtest/sandbox.py
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def __getattr__(name: str):
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class LeakError(RuntimeError):
    """Raised when the answer commit is reachable inside a 'blind' sandbox."""


def _git(repo: str, args: list, check=True):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=check)


def assert_commit_absent(repo: str, c_sha: str) -> None:
    cat = subprocess.run(["git", "-C", repo, "cat-file", "-e", f"{c_sha}^{{commit}}"],
                         capture_output=True, text=True)
    if cat.returncode == 0:
        raise LeakError(f"answer commit {c_sha} is present in sandbox object store")
    revs = subprocess.run(["git", "-C", repo, "rev-list", "--all"],
                          capture_output=True, text=True).stdout
    if c_sha in revs.splitlines():
        raise LeakError(f"answer commit {c_sha} is reachable from a ref in sandbox")


def build_sandbox(*, main_repo: str, c_sha: str, cprev_sha: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    _git(str(dest), ["init", "-q"])
    _git(str(dest), ["remote", "add", "origin", f"file://{main_repo}"])
    _git(str(dest), ["fetch", "-q", "--depth", "1", "origin", cprev_sha])
    _git(str(dest), ["checkout", "-q", "FETCH_HEAD"])
    # provision_worktree bootstraps tools/ from master; the ref must resolve (does not reach C)
    _git(str(dest), ["fetch", "-q", "--depth", "1", "origin", "master:refs/heads/master"], check=False)
    assert_commit_absent(str(dest), c_sha)
    from .provision import provision_worktree
    provision_worktree(str(dest), main_repo=main_repo)
    return dest


def teardown_sandbox(dest: Path) -> None:
    shutil.rmtree(dest, ignore_errors=True)
