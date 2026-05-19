#!/usr/bin/env python3
"""Run decomp-permuter with mwcc-debug score blended into objdiff scoring.

This is the Tier 2 permuter integration entry point: per-iteration, blend
the standard objdiff byte-distance score with `melee-agent debug score`
(IGNode-distance from the pcdump). The latter is much more meaningful
for register-cascade stuck cases where byte distance flatlines but
graph-coloring distance still varies.

Mechanism:
1. Monkey-patch `Compiler.compile` to also capture the candidate `.c` path
   (permuter discards it; we need it for our scoring).
2. Monkey-patch `Scorer.score` to:
   - Run original objdiff scoring (byte distance + hash for caching).
   - If MWCC_DEBUG_TARGET + MWCC_DEBUG_FN + MWCC_DEBUG_UNIT are set:
     stage the candidate inside `nonmatchings/`, call
     `melee-agent debug score-source --cflags-from <unit>`, blend.
   - Otherwise pass through objdiff score.

Env vars:
    MELEE_PERMUTER_ROOT   where decomp-permuter is checked out
                          (default: ~/code/decomp-permuter)
    MWCC_DEBUG_TARGET     path to target spec (from debug derive-target)
    MWCC_DEBUG_FN         function name to score
    MWCC_DEBUG_UNIT       source file path (e.g. src/melee/mn/mnvibration.c)
                          used for cflags resolution
    MWCC_DEBUG_BLEND      weight α for mwcc score (default 0.1)
    MELEE_ROOT            melee repo root (default: ~/code/melee)

Usage: invoked by `melee-agent debug permute -f <fn>`. Can also be run
directly:

    MELEE_PERMUTER_ROOT=~/code/decomp-permuter \
    MELEE_ROOT=~/code/melee \
    MWCC_DEBUG_TARGET=/tmp/target.json \
    MWCC_DEBUG_FN=fn_xyz \
    MWCC_DEBUG_UNIT=src/melee/path/file.c \
    python permute_with_mwcc.py nonmatchings/fn_xyz [permuter args...]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path


_thread_local = threading.local()


def _o_to_c_map() -> dict:
    """Per-thread map from o_file → c_file path. Populated by
    patched Compiler.compile, consumed by patched Scorer.score."""
    if not hasattr(_thread_local, "o_to_c"):
        _thread_local.o_to_c = {}
    return _thread_local.o_to_c


def _resolve_permuter_root() -> Path:
    env = os.environ.get("MELEE_PERMUTER_ROOT")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p
    for cand in [
        Path("~/code/decomp-permuter").expanduser(),
        Path("~/code/melee-harness/decomp-permuter").expanduser(),
    ]:
        if cand.exists():
            return cand
    raise SystemExit(
        "decomp-permuter not found. Set MELEE_PERMUTER_ROOT or clone "
        "to ~/code/decomp-permuter."
    )


def _melee_root() -> Path:
    return Path(
        os.environ.get("MELEE_ROOT", os.path.expanduser("~/code/melee"))
    )


def _score_candidate(c_file: str) -> int:
    """Run `melee-agent debug score-source` on a candidate.

    Stages the candidate inside `nonmatchings/.permuter_score_<pid>_<tid>.c`
    (git-ignored, parallel-safe via PID+TID) so mwcc finds project headers
    via the relative include paths.

    Returns 0 on success-perfect, larger ints for worse matches, and a
    large penalty if scoring fails entirely.
    """
    target = os.environ.get("MWCC_DEBUG_TARGET")
    fn = os.environ.get("MWCC_DEBUG_FN")
    unit = os.environ.get("MWCC_DEBUG_UNIT")
    if not target or not fn or not unit:
        return 0  # not configured

    melee_root = _melee_root()
    pid = os.getpid()
    tid = threading.get_ident()
    stage_rel = Path("nonmatchings") / f".permuter_score_{pid}_{tid}.c"
    stage_abs = melee_root / stage_rel

    try:
        stage_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(c_file, stage_abs)

        cmd = [
            "python", "-m", "src.cli", "debug", "score-source",
            str(stage_rel),
            "-f", fn,
            "-t", target,
            "--cflags-from", unit,
            "--quiet",
        ]
        result = subprocess.run(
            cmd,
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        score_str = result.stdout.strip()
        try:
            return int(score_str)
        except ValueError:
            if result.stderr:
                print(
                    f"[permute_with_mwcc] score-source failed: "
                    f"{result.stderr.strip()}",
                    file=sys.stderr,
                )
            return 1_000_000  # penalty
    except subprocess.TimeoutExpired:
        return 1_000_000  # timeout penalty
    finally:
        try:
            stage_abs.unlink(missing_ok=True)
        except Exception:
            pass


def patch_permuter_scorer(permuter_root: Path, blend: float) -> None:
    sys.path.insert(0, str(permuter_root))

    from src.compiler import Compiler  # type: ignore[import-not-found]
    from src.scorer import Scorer  # type: ignore[import-not-found]

    original_compile = Compiler.compile
    original_score = Scorer.score

    def patched_compile(self, source, *, show_errors=False):
        # Save the source to a predictable path we can recover later.
        # Original Compiler.compile creates its own NamedTemporaryFile;
        # we keep a parallel copy keyed by the resulting o_file.
        import tempfile
        cand_c = (
            Path(tempfile.gettempdir())
            / f"permuter_mwcc_cand_{os.getpid()}_{threading.get_ident()}.c"
        )
        cand_c.write_text(source)

        o_file = original_compile(self, source, show_errors=show_errors)
        if o_file is not None:
            _o_to_c_map()[o_file] = str(cand_c)
        return o_file

    def patched_score(self, cand_o):
        base_score, base_hash = original_score(self, cand_o)
        if cand_o is None:
            return base_score, base_hash

        c_file = _o_to_c_map().pop(cand_o, None)
        if c_file is None or not Path(c_file).exists():
            return base_score, base_hash

        try:
            mwcc_score = _score_candidate(c_file)
        except Exception as e:
            print(
                f"[permute_with_mwcc] scoring error: {e}", file=sys.stderr
            )
            return base_score, base_hash
        finally:
            try:
                Path(c_file).unlink(missing_ok=True)
            except Exception:
                pass

        blended = int(base_score + blend * mwcc_score)
        return blended, base_hash

    Compiler.compile = patched_compile  # type: ignore[assignment]
    Scorer.score = patched_score  # type: ignore[assignment]


def main() -> int:
    permuter_root = _resolve_permuter_root()
    blend = float(os.environ.get("MWCC_DEBUG_BLEND", "0.1"))

    patch_permuter_scorer(permuter_root, blend)

    target = os.environ.get("MWCC_DEBUG_TARGET")
    fn = os.environ.get("MWCC_DEBUG_FN")
    unit = os.environ.get("MWCC_DEBUG_UNIT")
    if target and fn and unit:
        print(
            f"[permute_with_mwcc] active: fn={fn} unit={unit} "
            f"blend={blend}",
            file=sys.stderr,
        )
    else:
        print(
            "[permute_with_mwcc] MWCC_DEBUG_TARGET/FN/UNIT not all set "
            "— running stock permuter (no mwcc-debug blending).",
            file=sys.stderr,
        )

    sys.argv[0] = str(permuter_root / "permuter.py")
    from src.main import main as permuter_main  # type: ignore[import-not-found]
    return permuter_main() or 0


if __name__ == "__main__":
    sys.exit(main())
