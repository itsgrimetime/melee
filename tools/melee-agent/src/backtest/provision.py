# tools/melee-agent/src/backtest/provision.py
from __future__ import annotations
import subprocess, sys
from pathlib import Path


class ProvisionError(RuntimeError):
    pass


def _run(runner, cmd, *, cwd=None, step):
    p = runner(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise ProvisionError(f"{step} failed (rc={p.returncode}): {(p.stderr or p.stdout)[-300:]}")
    return p


def provision_worktree(workdir: str, *, main_repo: str, runner=subprocess.run) -> None:
    """Make `workdir` (a checkout at the target commit) buildable, using main's
    known-good toolchain — no worktree-doctor download/purge. See plan Global Constraints.

    ⚠️ NOT VERIFIED WORKING on arm64 macOS (2026-06-26). The `ninja build/GALE01/report.json`
    step still fails on toolchain provisioning in fresh historical worktrees: the build
    re-triggers `gc-wii-binutils`/`objdiff-cli` downloads (flaky), and `build/tools/wibo`
    fails to exec (`rc=126 'cannot execute binary file'`) whether the x86_64 Mach-O is
    copied (breaks code signature) OR symlinked from main (ninja still won't exec it).
    Every approach tried — copy, symlink, worktree-doctor --fix, empty-repo fetch — hit
    this wall; only the original main checkout builds cleanly. Reconstructing the per-commit
    toolchain at arbitrary historical commits on this host is an unresolved build-environment
    problem; this is expected to work on Linux/CI (native-ELF toolchain, stable downloads),
    or needs dedicated build-system work. The recipe below is correct in structure; the
    blocker is the host toolchain, not this code."""
    wt = Path(workdir)
    # 1) bootstrap fork tooling (older commits lack tools/checkdiff.py & worktree-doctor.py)
    _run(runner, ["git", "-C", str(wt), "checkout", "master", "--", "tools"], step="bootstrap-tools")
    # 2) provision main's known-good toolchain by SYMLINK, not copy. COPYING an x86_64
    #    Mach-O (e.g. wibo) breaks its code signature so it won't exec via Rosetta
    #    ("/bin/sh: build/tools/wibo: cannot execute binary file"); a symlink points at
    #    the same signed inode main runs. Per-entry symlinks into a real dir, so any
    #    build-time download lands in the worktree, never main's tree.
    (wt / "build").mkdir(parents=True, exist_ok=True)
    for d in ("tools", "binutils", "compilers"):
        src = Path(main_repo) / "build" / d
        dst = wt / "build" / d
        if not src.exists():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        for entry in src.iterdir():
            link = dst / entry.name
            if not link.exists():
                link.symlink_to(entry)
    # 3) symlink the ground-truth DOL
    dol = wt / "orig" / "GALE01" / "sys" / "main.dol"
    dol.parent.mkdir(parents=True, exist_ok=True)
    if not dol.is_symlink():
        dol.symlink_to(str(Path(main_repo) / "orig" / "GALE01" / "sys" / "main.dol"))
    # 4) configure (won't purge the Mach-O wibo) + 5) generate report.json before checkdiff
    _run(runner, [sys.executable, "configure.py"], cwd=str(wt), step="configure")
    _run(runner, ["ninja", "build/GALE01/report.json"], cwd=str(wt), step="ninja-report")
