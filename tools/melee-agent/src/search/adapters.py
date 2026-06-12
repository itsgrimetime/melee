"""Adapter seams (Protocols) + concrete implementations that wire real
melee-agent internals into the search substrate.

Seam protocols are stable contracts.  Concrete classes (Real*) are the live
wiring discovered in Task-9 discovery; see task notes for exact signatures.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol

from src.search.types import TargetSpec


# ---------------------------------------------------------------------------
# Repo-wide compile lock
# ---------------------------------------------------------------------------

@contextmanager
def _acquire_repo_build_lock(
    melee_root: Path, *, label: str = "search compile"
) -> Iterator[None]:
    """Acquire the SAME repo-wide lock used by tools/checkdiff.py and
    ``cli/debug.py:_acquire_checkdiff_repo_lock``.

    Replicated here (rather than imported from cli/) to avoid a
    search/mwcc_debug -> cli layering dependency; the lock path scheme is
    identical so it serialises against checkdiff/source-scoring runs that
    mutate the same build tree.
    """
    if os.environ.get("CHECKDIFF_NO_LOCK"):
        yield
        return
    try:
        import fcntl
    except ImportError:
        yield
        return

    lock_dir = Path(tempfile.gettempdir()) / "melee-checkdiff-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(str(melee_root.resolve()).encode()).hexdigest()[:12]
    lock_path = lock_dir / f"repo.{digest}.lock"
    lock_file = lock_path.open("w")
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"waiting for repo-wide {label} lock", file=sys.stderr)
            start = time.monotonic()
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            print(
                f"acquired {label} lock after {time.monotonic() - start:.1f}s",
                file=sys.stderr,
            )
        yield
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


# ---------------------------------------------------------------------------
# Seam Protocols (stable contract)
# ---------------------------------------------------------------------------

class ByteScorer(Protocol):
    def byte_distance(self, obj_path: Path, target: TargetSpec) -> int:
        ...


class LocalCompiler(Protocol):
    def compile(self, source_text: str, target: TargetSpec) -> tuple[Path | None, str]:
        ...


class RemotePermuterClient(Protocol):
    def submit(self, base_dir: Path, function: str, remote: str) -> str:
        ...

    def fetch(self, job_id: str) -> list[tuple[Path, float]]:
        ...

    def status(self, job_id: str) -> str:
        ...

    def stop(self, job_id: str) -> None:
        ...


class CheckdiffVerifier(Protocol):
    def is_match(self, function: str, obj_path: Path) -> bool:
        ...


# ---------------------------------------------------------------------------
# Concrete implementations
# ---------------------------------------------------------------------------

# Pattern for decomp-permuter output directories: output-SCORE-N/
_OUTPUT_DIR_RE = re.compile(r"^output-(?P<score>-?\d+(?:\.\d+)?)-\d+$")


class RealLocalCompiler:
    """Compile a source variant by writing it to the TU source path and
    running ninja.

    Strategy: the LocalCompiler Protocol requires (obj_path | None, stderr).
    The real compile path is:
      1. Acquire the repo-wide build lock (serialise vs other agents).
      2. Save the original TU .c AND the original build .o bytes.
      3. Replace the TU .c with the candidate source.
      4. Run `ninja build/GALE01/src/<unit>.o`.
      5. Copy the resulting .o to a caller-owned temp path.
      6. In a finally, restore BOTH the TU .c and the build .o so the repo
         tree is never left out of sync with a search candidate.

    This mirrors how the convergence loop and mwcc-debug iterate on TUs.
    """

    def __init__(self, melee_root: Path) -> None:
        self._melee_root = Path(melee_root)

    def compile(self, source_text: str, target: TargetSpec) -> tuple[Path | None, str]:
        unit = target.unit  # e.g. "melee/gr/quatlib"
        unit_src = self._melee_root / "src" / f"{unit}.c"
        obj_rel = f"build/GALE01/src/{unit}.o"
        obj_abs = self._melee_root / obj_rel

        if not unit_src.exists():
            return None, f"unit source not found: {unit_src}"

        with _acquire_repo_build_lock(self._melee_root):
            original_c = unit_src.read_bytes()
            original_o = obj_abs.read_bytes() if obj_abs.exists() else None
            try:
                unit_src.write_text(source_text, encoding="utf-8")
                proc = subprocess.run(
                    ["ninja", obj_rel],
                    cwd=self._melee_root,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                stderr = proc.stderr + proc.stdout
                if proc.returncode != 0:
                    return None, stderr
                if not obj_abs.exists():
                    return None, f"ninja succeeded but .o not found: {obj_abs}\n{stderr}"
                # Copy to a caller-owned temp path (securely created).
                fd, dest = tempfile.mkstemp(suffix=".o", prefix="search_compile_")
                os.close(fd)
                shutil.copy2(obj_abs, dest)
                return Path(dest), stderr
            except subprocess.TimeoutExpired:
                return None, "ninja timed out"
            finally:
                # Restore the repo tree on EVERY path: TU .c first, then the
                # build .o (write back the original bytes, or remove the
                # candidate .o if there was no prior object).
                unit_src.write_bytes(original_c)
                if original_o is not None:
                    obj_abs.write_bytes(original_o)
                else:
                    obj_abs.unlink(missing_ok=True)


class RealByteScorer:
    """Compute byte_distance between a candidate .o and the expected .o.

    Strategy: extract the raw bytes of the .text section from both objects
    using pyelftools, then count the number of differing 4-byte words (PPC
    instructions are 4 bytes).  Falls back to whole-file byte diff if section
    extraction fails.

    Lower is better; 0 means byte-identical .text sections.
    """

    def byte_distance(self, obj_path: Path, target: TargetSpec) -> int:
        expected = target.expected_obj
        candidate_bytes = _extract_text_bytes(obj_path)
        expected_bytes = _extract_text_bytes(expected)
        if candidate_bytes is None or expected_bytes is None:
            # Fall back: raw file diff
            candidate_bytes = obj_path.read_bytes() if obj_path.exists() else b""
            expected_bytes = expected.read_bytes() if expected.exists() else b""
        return _word_distance(candidate_bytes, expected_bytes)


def _extract_text_bytes(obj_path: Path) -> bytes | None:
    """Return the raw bytes of the .text section, or None on failure."""
    try:
        from elftools.elf.elffile import ELFFile  # type: ignore[import]
        with obj_path.open("rb") as f:
            elf = ELFFile(f)
            sec = elf.get_section_by_name(".text")
            if sec is None:
                return None
            return sec.data()
    except Exception:
        return None


def _word_distance(a: bytes, b: bytes) -> int:
    """Count differing 4-byte words between two byte sequences."""
    max_len = max(len(a), len(b))
    # Pad both to a multiple of 4
    a = a.ljust(max_len, b"\x00")
    b = b.ljust(max_len, b"\x00")
    count = 0
    for i in range(0, max_len, 4):
        if a[i:i+4] != b[i:i+4]:
            count += 1
    return count


class RealRemotePermuterClient:
    """Wire permuter_remote.submit_job / fetch_job / status_job / stop_job.

    Signature discoveries (Task-9):
    - submit_job(function, target: RemoteTarget, local_perm_dir, ...) -> RemoteJob
    - fetch_job(job: RemoteJob, ...) -> Path  (fetch_dest directory)
    - status_job(job: RemoteJob, ...) -> RemoteStatus  (.state: str)
    - stop_job(job: RemoteJob, ...) -> CommandResult

    The Protocol expects string job_ids.  This adapter stores RemoteJob objects
    keyed by job_id and exposes the string ID externally.

    fetch() returns list[(source_path, score)] by globbing output-SCORE-N/source.c
    under the returned fetch_dest directory.
    """

    def __init__(self, melee_root: Path) -> None:
        self._melee_root = Path(melee_root)
        self._jobs: dict[str, object] = {}  # job_id -> RemoteJob
        self._job_errors: dict[str, str] = {}

    def submit(self, base_dir: Path, function: str, remote: str) -> str:
        from src.mwcc_debug.permuter_remote import load_targets, submit_job

        targets = load_targets()
        if remote not in targets:
            raise ValueError(
                f"remote {remote!r} not found in permuter config; "
                f"available: {list(targets)}"
            )
        target = targets[remote]
        job = submit_job(
            function=function,
            target=target,
            local_perm_dir=base_dir,
            local_melee_root=self._melee_root,
        )
        self._jobs[job.job_id] = job
        return job.job_id

    def fetch(self, job_id: str) -> list[tuple[Path, float]]:
        from src.mwcc_debug.permuter_remote import fetch_job

        job = self._jobs.get(job_id)
        if job is None:
            return []
        fetch_dest: Path = fetch_job(job)
        results: list[tuple[Path, float]] = []
        for source_c in sorted(fetch_dest.glob("output-*/source.c")):
            dir_name = source_c.parent.name
            m = _OUTPUT_DIR_RE.match(dir_name)
            score = float(m.group("score")) if m else float("-inf")
            results.append((source_c, score))
        if not results:
            failure = _summarize_permuter_failure(fetch_dest / "remote-run" / "permuter.log")
            if failure:
                self._job_errors[job_id] = failure
        return results

    def status(self, job_id: str) -> str:
        from src.mwcc_debug.permuter_remote import status_job

        job = self._jobs.get(job_id)
        if job is None:
            return "failed"
        if job_id in self._job_errors:
            return f"failed:{self._job_errors[job_id]}"
        result = status_job(job)
        state = result.state
        # Map permuter tmux states onto the ProducerStatus Literal
        # ("running" | "drained" | "failed"); any unexpected/unknown state
        # is reported as "failed" so downstream never sees an off-contract value.
        if state == "active":
            return "running"
        if state == "stopped":
            return "drained"
        return "failed"

    def stop(self, job_id: str) -> None:
        from src.mwcc_debug.permuter_remote import stop_job

        job = self._jobs.get(job_id)
        if job is not None:
            stop_job(job)


def _summarize_permuter_failure(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    try:
        lines = log_path.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    needles = (
        "fatal error",
        "returned non-zero exit status",
        "traceback",
        "error:",
    )
    for index, line in enumerate(lines):
        if any(needle in line.lower() for needle in needles):
            window = [line.strip()]
            for follow in lines[index + 1:index + 3]:
                stripped = follow.strip()
                if stripped:
                    window.append(stripped)
            return " | ".join(window)
    return ""


class RealCheckdiffVerifier:
    """Wire checkdiff_checker.CheckdiffChecker to the CheckdiffVerifier Protocol.

    CheckdiffChecker.__init__(function, melee_root, build_obj_path) requires a
    build_obj_path (injectable so tests never clobber the shared build tree).
    Here we derive it from report.json via unit lookup.
    """

    def __init__(self, melee_root: Path) -> None:
        self._melee_root = Path(melee_root)

    def is_match(self, function: str, obj_path: Path) -> bool:
        build_obj_path = self._resolve_build_obj(function)
        if build_obj_path is None:
            return False
        from src.mwcc_debug.checkdiff_checker import CheckdiffChecker
        checker = CheckdiffChecker(
            function=function,
            melee_root=self._melee_root,
            build_obj_path=build_obj_path,
        )
        # Verification copies the candidate .o into the SHARED build tree and
        # runs checkdiff, so it MUST hold the same repo-wide lock as the
        # compile path (adapters.py RealLocalCompiler) — otherwise a
        # concurrent agent's build can race the swap (spec §3.1: "scheduler
        # owns the lock + restore").
        #
        # Deferred: CheckdiffChecker does its own .convbak swap+restore, so we
        # do not also route through ArtifactStore.stage_for_verify here
        # (consolidating the two restore mechanisms would need invasive
        # changes to the shared CheckdiffChecker). The lock is the must-fix;
        # the restore-dedup is the nice-to-have and is left for a follow-up.
        with _acquire_repo_build_lock(self._melee_root, label="search verify"):
            return checker.is_clean(obj_path)

    def _resolve_build_obj(self, function: str) -> Path | None:
        import json
        report = self._melee_root / "build" / "GALE01" / "report.json"
        if not report.exists():
            return None
        data = json.loads(report.read_text())
        for unit in data.get("units", []):
            for fn in unit.get("functions", []):
                if fn.get("name") == function:
                    unit_name = unit.get("name", "").removeprefix("main/")
                    return (
                        self._melee_root
                        / "build"
                        / "GALE01"
                        / "src"
                        / f"{unit_name}.o"
                    )
        return None


# ---------------------------------------------------------------------------
# Dry-run stubs (used by CLI --dry-compiler flag)
# ---------------------------------------------------------------------------

class _DryLocalCompiler:
    """Write a stub .o (zeroed bytes) so the pipeline can score it."""

    def compile(self, source_text: str, target: TargetSpec) -> tuple[Path | None, str]:
        fd, dest = tempfile.mkstemp(suffix=".o", prefix="dry_compile_")
        os.close(fd)
        Path(dest).write_bytes(b"\x00" * 4)  # 1 word stub
        return Path(dest), ""


class _DryByteScorer:
    """Always returns a nonzero distance (stub .o never matches)."""

    def byte_distance(self, obj_path: Path, target: TargetSpec) -> int:
        return 1  # nonzero — no spurious "match" in dry runs


class _DryCheckdiffVerifier:
    """Never matches (dry run)."""

    def is_match(self, function: str, obj_path: Path) -> bool:
        return False
