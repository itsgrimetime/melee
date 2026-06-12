"""Vendor + build retrowin32 and cadmic/mwcc-debugger at pinned SHAs.

Idempotent. Returns a SetupResult; raises SetupError (naming the failing step)
on unrecoverable failure. STOP CONDITION: pinned SHA unfetchable or cargo build
fails after one clean retry.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import (CADMIC_PIN, CADMIC_REPO, RETROWIN32_BRANCH, RETROWIN32_PIN,
               RETROWIN32_REPO, VENDOR_DIR)


class SetupError(RuntimeError):
    pass


@dataclass
class SetupResult:
    retrowin32_bin: Path
    cadmic_script: Path
    rebuilt: bool


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise SetupError(f"command failed ({' '.join(cmd)}):\n{p.stdout}\n{p.stderr}")
    return p.stdout


def _clone_pinned(repo: str, branch: str | None, pin: str, dest: Path) -> None:
    if dest.exists():
        head = _run(["git", "-C", str(dest), "rev-parse", "HEAD"]).strip()
        if head == pin:
            return
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["git", "clone"]
    if branch:
        args += ["-b", branch]
    args += [repo, str(dest)]
    _run(args)
    _run(["git", "-C", str(dest), "checkout", pin])
    head = _run(["git", "-C", str(dest), "rev-parse", "HEAD"]).strip()
    if head != pin:
        raise SetupError(f"{repo}: HEAD {head} != pin {pin} (pin unfetchable?)")


def _cargo_target_dir(repo_dir: Path) -> Path:
    """Resolve cargo's real target directory for repo_dir.

    Cannot assume `repo_dir/target`: the melee repo's .cargo/config.toml sets
    `[build] target-dir = "build/cargo"`, which redirects every cargo build
    under the tree. Ask cargo directly; fall back to repo_dir/target.
    """
    import json
    try:
        out = _run(["cargo", "metadata", "--no-deps", "--format-version", "1"],
                   cwd=repo_dir)
        td = json.loads(out).get("target_directory")
        if td:
            return Path(td)
    except (SetupError, json.JSONDecodeError, KeyError):
        pass
    return repo_dir / "target"


def _retrowin32_binary(repo_dir: Path) -> Path:
    return _cargo_target_dir(repo_dir) / "lto" / "retrowin32"


def ensure(force: bool = False) -> SetupResult:
    rw_dir = VENDOR_DIR / "retrowin32"
    cad_dir = VENDOR_DIR / "mwcc-debugger"
    if force and VENDOR_DIR.exists():
        shutil.rmtree(VENDOR_DIR)
    _clone_pinned(RETROWIN32_REPO, RETROWIN32_BRANCH, RETROWIN32_PIN, rw_dir)
    _clone_pinned(CADMIC_REPO, None, CADMIC_PIN, cad_dir)
    binp = _retrowin32_binary(rw_dir)
    rebuilt = False
    if force or not binp.exists():
        try:
            _run(["cargo", "build", "-p", "retrowin32", "-F",
                  "x86-unicorn", "--profile", "lto"], cwd=rw_dir)
        except SetupError:
            _run(["cargo", "clean"], cwd=rw_dir)
            _run(["cargo", "build", "-p", "retrowin32", "-F",
                  "x86-unicorn", "--profile", "lto"], cwd=rw_dir)
        rebuilt = True
    if not binp.exists():
        raise SetupError(f"retrowin32 binary missing after build: {binp}")
    cad_script = cad_dir / "mwcc_debugger.py"
    if not cad_script.exists():
        raise SetupError(f"cadmic script missing: {cad_script}")
    return SetupResult(retrowin32_bin=binp, cadmic_script=cad_script, rebuilt=rebuilt)
