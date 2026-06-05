"""PcdumpLocalBackend: compile a candidate AND emit the mwcc-debug pcdump in
one invocation.

This backend is the "pcdump-local" mode used by the directed scorer.  It
shells out to ``python -m src.cli debug dump local`` (the same path that
``mwcc-debug dump local`` takes) which compiles the TU, retains the .o, AND
writes the structured pcdump — all in a single subprocess.

Restore-on-every-path contract (mirrors RealLocalCompiler in adapters.py):
  1. Acquire repo-wide build lock.
  2. Save original TU .c bytes (and pre-existing .o bytes if any).
  3. Write candidate source to TU .c.
  4. Run the subprocess.
  5. In a ``finally``, ALWAYS restore TU .c (and prior .o if it existed).

Temp-file ownership: ``obj_tmp`` and ``pcdump_tmp`` are created by this
backend and their paths are returned to the caller via CandidateArtifact
fields.  The caller (directed scorer / scheduler) owns their lifetime.  The
backend does NOT delete them on success.  On compile failure the paths are set
to None in the returned artifact.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from src.search.adapters import _acquire_repo_build_lock
from src.search.artifact import (
    CandidateArtifact,
    CompileSpec,
    Provenance,
    compute_candidate_id,
)
from src.search.types import BackendCaps, SourceVariant, TargetSpec


class PcdumpLocalBackend:
    """Compile a source variant and emit the mwcc-debug pcdump in one shot.

    Args:
        melee_root:  Absolute path to the melee repo root.
        unit:        Relative unit path (e.g. "melee/gr/gricemt") — no "src/"
                     prefix, no ".c" suffix.
        target:      TargetSpec describing the function being matched.
        store:       Object with ``put_source(text: str) -> Path``.
        compile_spec_factory:
                     Callable(SourceVariant) -> CompileSpec; builds the
                     CompileSpec for a given variant (injected so callers
                     supply toolchain fingerprints, cflags hashes, etc.).
        runner:      Callable with ``subprocess.run`` signature.  Injectable
                     for tests; defaults to ``subprocess.run``.
    """

    def __init__(
        self,
        *,
        melee_root: Path,
        unit: str,
        target: TargetSpec,
        store: Any,
        compile_spec_factory: Callable[[SourceVariant], CompileSpec],
        runner: Callable = subprocess.run,
    ) -> None:
        self._melee_root = Path(melee_root)
        self._unit = unit
        self._target = target
        self._store = store
        self._compile_spec_factory = compile_spec_factory
        self._runner = runner

    # ------------------------------------------------------------------
    # BackendCaps
    # ------------------------------------------------------------------

    def capabilities(self) -> BackendCaps:
        return BackendCaps("local", 1, True)

    # ------------------------------------------------------------------
    # Compile
    # ------------------------------------------------------------------

    def compile(
        self,
        variant: SourceVariant,
        *,
        want_pcdump: bool = False,
    ) -> CandidateArtifact:
        """Compile *variant* under the repo build lock and return an artifact.

        The TU .c is always restored (and any pre-existing .o) in a finally
        block, even when the subprocess fails or raises.
        """
        source_text: str = variant.source_text
        tu_c = self._melee_root / "src" / f"{self._unit}.c"

        # Create caller-owned temp files.  We close the OS file descriptors
        # immediately; the paths are managed by the caller after we return.
        obj_fd, obj_tmp_str = tempfile.mkstemp(suffix=".o", prefix="pcdump_be_")
        os.close(obj_fd)
        pcdump_fd, pcdump_tmp_str = tempfile.mkstemp(
            suffix=".pcdump.txt", prefix="pcdump_be_"
        )
        os.close(pcdump_fd)
        obj_tmp = Path(obj_tmp_str)
        pcdump_tmp = Path(pcdump_tmp_str)

        proc: Any = None

        with _acquire_repo_build_lock(self._melee_root):
            # Save originals.
            original_c: bytes = tu_c.read_bytes() if tu_c.exists() else b""
            try:
                # Write candidate source.
                tu_c.write_text(source_text, encoding="utf-8")

                argv = [
                    sys.executable,
                    "-m",
                    "src.cli",
                    "debug",
                    "dump",
                    "local",
                    str(tu_c),
                    "--function",
                    self._target.function,
                    "--output",
                    str(pcdump_tmp),
                    "--keep-obj",
                    str(obj_tmp),
                    "--no-cache-sync",
                ]
                proc = self._runner(
                    argv,
                    cwd=self._melee_root / "tools" / "melee-agent",
                    capture_output=True,
                    text=True,
                )
            finally:
                # Always restore the TU .c on every path.
                if original_c:
                    tu_c.write_bytes(original_c)
                else:
                    tu_c.unlink(missing_ok=True)

        # Determine success.
        ok = (
            proc is not None
            and proc.returncode == 0
            and obj_tmp.exists()
            and obj_tmp.stat().st_size > 0
            and pcdump_tmp.exists()
        )
        status = "ok" if ok else "compile_failed"
        object_path = obj_tmp if ok else None
        pcdump_path = pcdump_tmp if ok else None

        # Build artifact metadata.
        source_hash = hashlib.sha256(source_text.encode()).hexdigest()[:32]
        source_blob = self._store.put_source(source_text)
        spec = self._compile_spec_factory(variant)
        cid = compute_candidate_id(spec, source_hash)
        prov = variant.provenance or Provenance("directed", None, None, "", {})

        stderr_combined = ""
        if proc is not None:
            stderr_combined = (proc.stderr or "") + (proc.stdout or "")

        return CandidateArtifact(
            candidate_id=cid,
            source_hash=source_hash,
            source_blob=source_blob,
            compile_spec=spec,
            object_path=object_path,
            producer_score=None,
            byte_score=None,
            directed_score=None,
            pcdump_path=pcdump_path,
            compiler_stderr=stderr_combined,
            provenance=prov,
            status=status,
        )
