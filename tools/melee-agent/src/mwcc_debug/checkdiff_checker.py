"""Driver-owned ASM_MATCHED verdict: copy the editor's recompiled .o into the
unit's build path, run ``tools/checkdiff.py --no-build`` (diffs the .o as-is,
no ninja), and report whether it matches the target — then restore the original
.o.

``build_obj_path`` is injectable so tests never touch the shared build/GALE01
tree (a concurrent agent builds there).  The editor supplies the .o ARTIFACT;
this class renders the VERDICT — the trust boundary the loop depends on.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


class CheckdiffChecker:
    """Driver-owned checkdiff verdict (ASM_MATCHED signal).

    Workflow:
    1. Save the unit's build .o.
    2. Copy ``obj_path`` into the build .o location.
    3. Run ``tools/checkdiff.py FN --format json --no-build`` in a
       fingerprint-free env so the check does NOT record to the shared attempts
       DB.
    4. Verdict = exit 0 (effective-match, relocation/operand-tolerant — the
       signal the codebase trusts, not strict byte-identity).
    5. Restore the original .o in a ``finally`` block (always, even on error).

    ``build_obj_path`` is injectable; tests pass a tmp_path .o so no shared
    build/GALE01 tree is ever touched.
    """

    def __init__(self, function: str, melee_root: Path, build_obj_path: Path):
        self.function = function
        self.melee_root = Path(melee_root)
        self.build_obj_path = Path(build_obj_path)

    def is_clean(self, obj_path: Optional[Path]) -> bool:
        """Return True iff checkdiff reports ASM_MATCHED for ``obj_path``."""
        if obj_path is None:
            return False
        obj_path = Path(obj_path)
        if not obj_path.exists():
            return False                      # editor produced no readable .o -> not clean
        had = self.build_obj_path.exists()
        saved: Optional[Path] = None
        if had:
            saved = self.build_obj_path.with_suffix(self.build_obj_path.suffix + ".convbak")
            shutil.copy2(self.build_obj_path, saved)
        try:
            self.build_obj_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(obj_path, self.build_obj_path)
            proc = subprocess.run(
                ["python", "tools/checkdiff.py", self.function, "--format", "json", "--no-build"],
                cwd=self.melee_root,
                capture_output=True,
                text=True,
                timeout=120,
                env=_checkdiff_env(),
            )
            if proc.returncode == 0:
                # checkdiff exit 0 == effective match
                return True
            if proc.returncode == 1 and proc.stdout:
                # mismatch; confirm via JSON when present (belt-and-suspenders)
                try:
                    return bool(json.loads(proc.stdout).get("match", False))
                except json.JSONDecodeError:
                    return False
            return False  # any other exit / no output -> not clean
        finally:
            if had and saved is not None:
                shutil.move(str(saved), str(self.build_obj_path))   # restore original
            elif not had:
                self.build_obj_path.unlink(missing_ok=True)         # we created it; clean up


def _checkdiff_env() -> dict:
    """Return an env dict that disables build-fingerprint dedup.

    Mirrors ``cli/debug.py:_checkdiff_env_without_fingerprint`` which SETS
    ``CHECKDIFF_NO_FINGERPRINT="1"`` — it does NOT pop one.  We do NOT import
    from cli/ to avoid a cli→mwcc_debug layering dependency.
    """
    env = os.environ.copy()
    env["CHECKDIFF_NO_FINGERPRINT"] = "1"
    return env
