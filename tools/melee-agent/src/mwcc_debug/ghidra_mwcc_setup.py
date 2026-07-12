"""Bounded setup and validation for the exact MWCC 1.2.5n Ghidra project."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.cli.ghidra.detect import detect_ghidra_install

from .diff_capture import _run_with_process_group_timeout

EXPECTED_COMPILER_SHA256 = "ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c"
PROJECT_NAME = "mwcceppc"
PROGRAM_PATH = "/mwcceppc.exe"
RESULT_SCHEMA = "mwcc-ghidra-setup.v1"
_STATUS_PREFIX = "MWCC_AUDIT_STATUS "
_PROJECT_SUFFIXES = (".gpr", ".rep", ".lock")


class MwccGhidraSetupError(RuntimeError):
    """Stable setup failure with structured diagnostic details."""

    def __init__(self, reason: str, details: Mapping[str, Any] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.details = dict(details or {})


@dataclass(frozen=True)
class MwccGhidraSetupResult:
    status: str
    ghidra_install: Path
    headless_path: Path
    native_decompiler_path: Path | None
    compiler_path: Path
    compiler_sha256: str
    project_dir: Path
    project_name: str
    program_path: str
    function_count: int
    elapsed_seconds: float
    quarantined_paths: tuple[Path, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RESULT_SCHEMA,
            "status": self.status,
            "ghidra_install": str(self.ghidra_install),
            "headless_path": str(self.headless_path),
            "native_decompiler_path": (
                None if self.native_decompiler_path is None else str(self.native_decompiler_path)
            ),
            "compiler_path": str(self.compiler_path),
            "compiler_sha256": self.compiler_sha256,
            "project_dir": str(self.project_dir),
            "project_name": self.project_name,
            "program_path": self.program_path,
            "function_count": self.function_count,
            "elapsed_seconds": self.elapsed_seconds,
            "quarantined_paths": [str(path) for path in self.quarantined_paths],
        }


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_executable(path: Path, reason: str, details: Mapping[str, Any]) -> None:
    if not path.is_file() or not os.access(path, os.X_OK):
        raise MwccGhidraSetupError(reason, details)


def _native_decompiler(install: Path) -> Path | None:
    if platform.system() != "Darwin":
        return None
    host_arch = platform.machine().lower()
    directories = {
        "arm64": "mac_arm_64",
        "aarch64": "mac_arm_64",
        "x86_64": "mac_x86_64",
        "amd64": "mac_x86_64",
    }
    directory = directories.get(host_arch)
    if directory is None:
        raise MwccGhidraSetupError(
            "unsupported-host-architecture",
            {"host_arch": host_arch, "platform": "Darwin"},
        )
    native = install / "Ghidra/Features/Decompiler/os" / directory / "decompile"
    _require_executable(
        native,
        "missing-native-decompiler",
        {"host_arch": host_arch, "path": str(native)},
    )
    return native


def _combined_output(process: subprocess.CompletedProcess[str]) -> str:
    return f"{process.stdout or ''}\n{process.stderr or ''}".strip()


def _run_headless(
    cmd: list[str],
    *,
    phase: str,
    melee_root: Path,
    wall_timeout: int,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    try:
        process = runner(cmd, cwd=melee_root, timeout=wall_timeout)
    except subprocess.TimeoutExpired as error:
        raise MwccGhidraSetupError(
            "ghidra-process-timeout",
            {"phase": phase, "timeout": wall_timeout},
        ) from error
    except OSError as error:
        raise MwccGhidraSetupError(
            "ghidra-process-failed",
            {"phase": phase, "error": str(error)},
        ) from error

    output = _combined_output(process)
    lowered = output.lower()
    fatal_reason = next(
        (
            reason
            for marker, reason in (
                ("analysis timed out", "ghidra-analysis-timeout"),
                ("analysis cancelled", "ghidra-analysis-cancelled"),
                ("analysis canceled", "ghidra-analysis-cancelled"),
                ("processing cancelled", "ghidra-analysis-cancelled"),
                ("processing canceled", "ghidra-analysis-cancelled"),
                ("abort due to headless analyzer error", "ghidra-headless-abort"),
            )
            if marker in lowered
        ),
        None,
    )
    if fatal_reason is not None:
        raise MwccGhidraSetupError(fatal_reason, {"phase": phase, "output": output})
    if process.returncode != 0:
        raise MwccGhidraSetupError(
            "ghidra-process-failed",
            {"phase": phase, "returncode": process.returncode, "output": output},
        )
    return process


def _parse_status(process: subprocess.CompletedProcess[str]) -> int:
    markers = [
        line.partition(_STATUS_PREFIX)[2]
        for line in _combined_output(process).splitlines()
        if _STATUS_PREFIX in line
    ]
    if len(markers) != 1:
        raise MwccGhidraSetupError("invalid-status-marker", {"count": len(markers)})
    try:
        payload = json.loads(markers[0])
    except (TypeError, ValueError) as error:
        raise MwccGhidraSetupError("invalid-status-marker") from error
    if not isinstance(payload, dict) or set(payload) != {"sha256", "function_count"}:
        raise MwccGhidraSetupError("invalid-status-marker")
    sha256 = payload["sha256"]
    function_count = payload["function_count"]
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise MwccGhidraSetupError("invalid-status-marker")
    if sha256.lower() != EXPECTED_COMPILER_SHA256:
        raise MwccGhidraSetupError(
            "status-sha256-mismatch",
            {"actual": sha256.lower(), "expected": EXPECTED_COMPILER_SHA256},
        )
    if not isinstance(function_count, int) or isinstance(function_count, bool) or function_count <= 0:
        raise MwccGhidraSetupError("empty-status-functions", {"function_count": function_count})
    return function_count


def _canonical_project_artifacts(project_dir: Path) -> tuple[Path, ...]:
    return tuple(project_dir / f"{PROJECT_NAME}{suffix}" for suffix in _PROJECT_SUFFIXES)


def _validate_project(
    *,
    headless: Path,
    project_dir: Path,
    status_script: Path,
    melee_root: Path,
    wall_timeout: int,
    runner: Runner,
) -> int:
    process = _run_headless(
        [
            str(headless),
            str(project_dir),
            PROJECT_NAME,
            "-process",
            PROGRAM_PATH.removeprefix("/"),
            "-noanalysis",
            "-scriptPath",
            str(status_script.parent),
            "-postScript",
            status_script.name,
            EXPECTED_COMPILER_SHA256,
        ],
        phase="validation",
        melee_root=melee_root,
        wall_timeout=wall_timeout,
        runner=runner,
    )
    return _parse_status(process)


def _import_project(
    *,
    headless: Path,
    project_dir: Path,
    compiler: Path,
    analysis_timeout: int,
    melee_root: Path,
    wall_timeout: int,
    runner: Runner,
) -> None:
    _run_headless(
        [
            str(headless),
            str(project_dir),
            PROJECT_NAME,
            "-import",
            str(compiler),
            "-analysisTimeoutPerFile",
            str(analysis_timeout),
        ],
        phase="import",
        melee_root=melee_root,
        wall_timeout=wall_timeout,
        runner=runner,
    )


def _quarantine_project(
    artifacts: tuple[Path, ...],
    *,
    now: Callable[[], datetime],
) -> tuple[Path, ...]:
    stamp = now().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    present = tuple(path for path in artifacts if path.exists())
    destinations = tuple(Path(f"{path}.invalid-{stamp}") for path in present)
    collision = next((path for path in destinations if path.exists()), None)
    if collision is not None:
        raise MwccGhidraSetupError("repair-destination-exists", {"path": str(collision)})
    try:
        for source, destination in zip(present, destinations, strict=True):
            os.replace(source, destination)
    except OSError as error:
        raise MwccGhidraSetupError("project-quarantine-failed", {"error": str(error)}) from error
    return destinations


def setup_mwcc_ghidra(
    *,
    melee_root: Path,
    project_dir: Path,
    analysis_timeout: int,
    wall_timeout: int,
    repair: bool,
    detect_install: Callable[[], Path | None] = detect_ghidra_install,
    runner: Runner = _run_with_process_group_timeout,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> MwccGhidraSetupResult:
    """Create or validate the exact compiler project under bounded subprocesses."""

    started = time.monotonic()
    if (
        not isinstance(melee_root, Path)
        or not isinstance(project_dir, Path)
        or not isinstance(analysis_timeout, int)
        or isinstance(analysis_timeout, bool)
        or analysis_timeout <= 0
        or not isinstance(wall_timeout, int)
        or isinstance(wall_timeout, bool)
        or wall_timeout <= 0
        or not isinstance(repair, bool)
    ):
        raise MwccGhidraSetupError("invalid-setup-input")

    install = detect_install()
    if install is None:
        raise MwccGhidraSetupError("ghidra-not-found")
    install = Path(install)
    headless = install / "support/analyzeHeadless"
    _require_executable(headless, "missing-headless-launcher", {"path": str(headless)})
    native = _native_decompiler(install)

    compiler = melee_root / "build/compilers/GC/1.2.5n/mwcceppc.exe"
    if not compiler.is_file():
        raise MwccGhidraSetupError("missing-compiler", {"path": str(compiler)})
    status_script = melee_root / "tools/mwcc_debug/scripts/MwccAuditStatus.java"
    if not status_script.is_file():
        raise MwccGhidraSetupError("missing-status-script", {"path": str(status_script)})
    compiler_sha256 = _sha256_file(compiler)
    if compiler_sha256 != EXPECTED_COMPILER_SHA256:
        raise MwccGhidraSetupError(
            "compiler-sha256-mismatch",
            {
                "actual": compiler_sha256,
                "expected": EXPECTED_COMPILER_SHA256,
                "path": str(compiler),
            },
        )

    try:
        project_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise MwccGhidraSetupError("project-directory-failed", {"error": str(error)}) from error
    artifacts = _canonical_project_artifacts(project_dir)
    existing = any(path.exists() for path in artifacts)
    quarantined: tuple[Path, ...] = ()

    if existing:
        try:
            function_count = _validate_project(
                headless=headless,
                project_dir=project_dir,
                status_script=status_script,
                melee_root=melee_root,
                wall_timeout=wall_timeout,
                runner=runner,
            )
        except MwccGhidraSetupError as error:
            if not repair:
                raise MwccGhidraSetupError(
                    "invalid-existing-project",
                    {"cause": error.reason, "cause_details": error.details},
                ) from error
            quarantined = _quarantine_project(artifacts, now=now)
        else:
            return MwccGhidraSetupResult(
                status="ready",
                ghidra_install=install,
                headless_path=headless,
                native_decompiler_path=native,
                compiler_path=compiler,
                compiler_sha256=compiler_sha256,
                project_dir=project_dir,
                project_name=PROJECT_NAME,
                program_path=PROGRAM_PATH,
                function_count=function_count,
                elapsed_seconds=time.monotonic() - started,
                quarantined_paths=(),
            )

    _import_project(
        headless=headless,
        project_dir=project_dir,
        compiler=compiler,
        analysis_timeout=analysis_timeout,
        melee_root=melee_root,
        wall_timeout=wall_timeout,
        runner=runner,
    )
    function_count = _validate_project(
        headless=headless,
        project_dir=project_dir,
        status_script=status_script,
        melee_root=melee_root,
        wall_timeout=wall_timeout,
        runner=runner,
    )
    return MwccGhidraSetupResult(
        status="repaired" if quarantined else "imported",
        ghidra_install=install,
        headless_path=headless,
        native_decompiler_path=native,
        compiler_path=compiler,
        compiler_sha256=compiler_sha256,
        project_dir=project_dir,
        project_name=PROJECT_NAME,
        program_path=PROGRAM_PATH,
        function_count=function_count,
        elapsed_seconds=time.monotonic() - started,
        quarantined_paths=quarantined,
    )
