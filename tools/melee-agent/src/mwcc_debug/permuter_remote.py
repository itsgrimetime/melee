"""Remote decomp-permuter target config and job metadata helpers."""

from __future__ import annotations

import inspect
import json
import math
import os
import posixpath
import re
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import tomllib
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple

from . import candidate_audit
from .diff_capture import _run_with_process_group_timeout
from .permuter_config import DEFAULT_OBJDUMP_COMMAND

CONFIG_PATH = Path.home() / ".config" / "decomp-me" / "permuter-remotes.toml"
JOBS_DIR = Path.home() / ".config" / "decomp-me" / "permuter-jobs"
DEFAULT_REMOTE_DOCTOR_TIMEOUT = 60.0

CONFIG_EXAMPLE = """
[target.coder64]
ssh = "coder.coder64"
remote_melee_root = "/home/coder/melee"
remote_perm_root = "/home/coder/decomp-permuter"
threads = 64
session_prefix = "melee-perm"
""".strip()


class RemoteConfigError(RuntimeError):
    """Raised when remote permuter target config cannot be loaded."""


class RemoteJobError(RuntimeError):
    """Raised when remote permuter job metadata cannot be read or written."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class RemoteTarget:
    name: str
    ssh: str
    remote_melee_root: str
    remote_perm_root: str
    threads: int
    session_prefix: str


@dataclass(frozen=True)
class RemoteJob:
    job_id: str
    function: str
    target: str
    ssh: str
    remote_perm_dir: str
    remote_run_dir: str
    local_perm_dir: str
    tmux_session: str
    threads: int
    mode: str
    created_at: str


@dataclass(frozen=True)
class RemoteStatus:
    job_id: str
    state: str
    detail: str = ""


@dataclass(frozen=True)
class PermuterLogSummary:
    latest_iteration: int | None = None
    latest_score: float | None = None
    latest_errors: int | None = None
    global_best_iteration: int | None = None
    global_best_score: float | None = None
    global_best_errors: int | None = None
    iteration_count: int = 0
    match_found: bool = False
    output_candidate_saved: bool = False
    verdict: str = "unknown"


@dataclass(frozen=True)
class RemoteLogStatus:
    exists: bool
    modified_at: datetime | None = None
    best_score: str | None = None
    detail: str = ""
    latest_iteration: int | None = None
    latest_score: float | None = None
    latest_errors: int | None = None
    global_best_iteration: int | None = None
    global_best_score: float | None = None
    global_best_errors: int | None = None
    iteration_count: int = 0
    match_found: bool = False
    output_candidate_saved: bool = False
    verdict: str = "unknown"


@dataclass(frozen=True)
class OrphanedWiboProcess:
    pid: int
    ppid: int
    stat: str
    elapsed: str
    command: str


@dataclass(frozen=True)
class OrphanedPermuterProcess:
    pid: int
    ppid: int
    pgid: int
    stat: str
    elapsed: str
    birth_identity: str
    command: str
    cwd: Path
    kind: str


@dataclass(frozen=True)
class OrphanCleanupReport:
    terminated_pids: tuple[int, ...]
    surviving_pids: tuple[int, ...]
    skipped_groups: dict[int, str]


@dataclass(frozen=True)
class _ProcessSnapshot:
    pid: int
    ppid: int
    pgid: int
    stat: str
    elapsed: str
    birth_identity: str | None
    command: str


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True


@dataclass(frozen=True)
class DoctorReport:
    target: str
    checks: list[DoctorCheck]

    @property
    def ok(self) -> bool:
        return all(check.ok or not check.required for check in self.checks)


@dataclass(frozen=True)
class RepairReport:
    target: str
    actions: list[str]


Runner = Callable[[list[str]], CommandResult]


class ScorerCommandInfo(NamedTuple):
    command: str
    executable: str
    target_path: str | None


class ObjdumpCommandInfo(NamedTuple):
    command: str
    executable: str
    target_path: str | None


PYTHON_DEPS = [
    "httpx>=0.27.0",
    "pydantic>=2.0",
    "typer>=0.12.0",
    "rich>=13.0",
    "pyyaml>=6.0",
    "toml>=0.10.2",
    "anthropic>=0.40.0",
    "python-dotenv>=1.0.0",
    "pyelftools>=0.31",
    "tree-sitter>=0.23.0",
    "tree-sitter-c>=0.23.0",
]
DTK_TAG = "v1.8.3"
FUNCTION_HISTORY_EXCLUDES = [
    "remote-runs",
    "remote-runs/***",
    "output-*",
    "output-*/***",
]


def run_command(
    argv: list[str],
    cwd: Path | None = None,
    check: bool = True,
    timeout: float | None = None,
) -> CommandResult:
    """Run a local command, returning captured output."""
    try:
        if timeout is None:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
            )
        else:
            completed = _run_with_process_group_timeout(
                argv,
                cwd=cwd or Path.cwd(),
                timeout=timeout,
            )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        timeout_message = f"timed out after {timeout:g}s running {shlex.join(argv)}"
        if timeout_message not in stderr:
            stderr = f"{timeout_message}\n{stderr}" if stderr else timeout_message
        result = CommandResult(
            returncode=124,
            stdout=stdout,
            stderr=stderr,
        )
        if check:
            raise RemoteJobError(result.stderr)
        return result
    result = CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        detail = f": {stderr}" if stderr else ""
        raise RemoteJobError(f"Command failed ({result.returncode}): {shlex.join(argv)}{detail}")
    return result


def _runner_accepts_timeout(runner: Callable[..., CommandResult]) -> bool:
    try:
        parameters = inspect.signature(runner).parameters.values()
    except (TypeError, ValueError):
        return runner is run_command
    return any(
        parameter.name == "timeout"
        or parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def _run_bounded_command(
    runner: Callable[..., CommandResult],
    argv: list[str],
    *,
    check: bool,
    timeout: float,
) -> CommandResult:
    if _runner_accepts_timeout(runner):
        return runner(argv, check=check, timeout=timeout)
    return runner(argv, check=check)


def load_targets(config_path: Path = CONFIG_PATH) -> dict[str, RemoteTarget]:
    """Load configured remote permuter targets from TOML."""
    if not config_path.exists():
        raise RemoteConfigError(
            f"Remote permuter config not found: {config_path}\n\n"
            f"Example config:\n{CONFIG_EXAMPLE}\n"
        )

    try:
        config = tomllib.loads(config_path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise RemoteConfigError(f"Invalid remote permuter TOML in {config_path}: {exc}") from exc

    target_configs = config.get("target")
    if not isinstance(target_configs, dict) or not target_configs:
        raise RemoteConfigError(
            f"Remote permuter config {config_path} must define at least one [target.<name>] table.\n\n"
            f"Example config:\n{CONFIG_EXAMPLE}\n"
        )

    targets: dict[str, RemoteTarget] = {}
    for name, values in target_configs.items():
        if not isinstance(values, dict):
            raise RemoteConfigError(f"Target {name!r} in {config_path} must be a TOML table.")

        missing = [
            key
            for key in ("ssh", "remote_melee_root", "remote_perm_root")
            if key not in values
        ]
        if missing:
            raise RemoteConfigError(
                f"Target {name!r} in {config_path} is missing required keys: {', '.join(missing)}"
            )

        targets[name] = RemoteTarget(
            name=name,
            ssh=_expect_str(config_path, name, values, "ssh"),
            remote_melee_root=_strip_remote_root(_expect_str(config_path, name, values, "remote_melee_root")),
            remote_perm_root=_strip_remote_root(_expect_str(config_path, name, values, "remote_perm_root")),
            threads=_coerce_threads(config_path, name, values.get("threads")),
            session_prefix=_expect_optional_str(values, "session_prefix", "melee-perm"),
        )

    return targets


def write_job(job: RemoteJob, jobs_dir: Path = JOBS_DIR) -> Path:
    """Write a remote permuter job metadata file, refusing overwrites."""
    jobs_dir.mkdir(parents=True, exist_ok=True)
    path = jobs_dir / f"{job.job_id}.json"
    if path.exists():
        raise RemoteJobError(f"Remote permuter job metadata already exists: {path}")

    path.write_text(json.dumps(asdict(job), indent=2) + "\n")
    return path


def read_job(job_id: str, jobs_dir: Path = JOBS_DIR) -> RemoteJob:
    """Read one remote permuter job metadata file."""
    path = jobs_dir / f"{job_id}.json"
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("metadata root is not an object")
        return RemoteJob(**data)
    except FileNotFoundError as exc:
        raise RemoteJobError(f"Remote permuter job metadata not found: {path}") from exc
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RemoteJobError(f"Invalid remote permuter job metadata in {path}: {exc}") from exc


def list_jobs(jobs_dir: Path = JOBS_DIR) -> list[RemoteJob]:
    """List readable remote permuter jobs, ignoring malformed metadata files."""
    if not jobs_dir.exists():
        return []

    jobs: list[RemoteJob] = []
    for path in sorted(jobs_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                jobs.append(RemoteJob(**data))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return jobs


def status_job(
    job: RemoteJob,
    runner: Callable[..., CommandResult] = run_command,
    timeout: float | None = None,
) -> RemoteStatus:
    """Inspect whether the remote tmux session for a job is still active."""
    script = (
        f"tmux has-session -t {shlex.quote(job.tmux_session)} 2>/dev/null "
        "&& printf active || printf stopped"
    )
    kwargs: dict[str, Any] = {"check": False}
    if timeout is not None:
        kwargs["timeout"] = timeout
    result = runner(["ssh", job.ssh, _remote_sh(script)], **kwargs)
    if result.returncode not in (0, 1):
        return RemoteStatus(job_id=job.job_id, state="unknown", detail=result.stderr.strip())
    return RemoteStatus(job_id=job.job_id, state=result.stdout.strip() or "unknown")


def parse_timestamp(value: str) -> datetime:
    """Parse a job timestamp as a naive datetime for age reporting."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def utcnow() -> datetime:
    """Current time hook for tests."""
    return datetime.utcnow().replace(microsecond=0)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_ITERATION_SCORE_RE = re.compile(
    r"\biteration\s+(?P<iteration>\d+),\s*"
    r"(?P<errors>\d+)\s+errors?,\s*"
    r"score\s*=\s*(?P<score>inf|[-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_OUTPUT_CANDIDATE_RE = re.compile(r"\b(?:wrote to .*|[\w./-]*/)?output-[^\s/]+", re.IGNORECASE)


def format_score(score: float | None) -> str:
    """Format decomp-permuter scores compactly for status output."""
    if score is None:
        return "-"
    if math.isinf(score):
        return "inf"
    numeric = float(score)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:g}"


def _parse_score(raw_score: str) -> float:
    if raw_score.lower() == "inf":
        return math.inf
    return float(raw_score)


def _classify_log_summary(
    *,
    match_found: bool,
    iteration_count: int,
    global_best_score: float | None,
    latest_score: float | None,
    record_improvements: int,
    best_occurrences: int,
) -> str:
    if match_found:
        return "match"
    if iteration_count == 0 or global_best_score is None:
        return "unknown"
    if math.isinf(global_best_score):
        return "unknown"
    if record_improvements > 0:
        return "descending"
    if (
        (latest_score is not None and latest_score == global_best_score)
        or best_occurrences > 1
    ):
        return "plateau"
    return "ceiling"


def parse_permuter_log_summary(
    text: str,
    *,
    has_output_candidate: bool = False,
) -> PermuterLogSummary:
    """Parse a full decomp-permuter log into global-min/latest status."""
    normalized = _ANSI_RE.sub("", text).replace("\r", "\n").replace("\b", "")
    latest_iteration: int | None = None
    latest_score: float | None = None
    latest_errors: int | None = None
    global_best_iteration: int | None = None
    global_best_score: float | None = None
    global_best_errors: int | None = None
    iteration_count = 0
    match_found = False
    record_improvements = 0
    best_occurrences = 0

    for match in _ITERATION_SCORE_RE.finditer(normalized):
        iteration_count += 1
        iteration = int(match.group("iteration"))
        errors = int(match.group("errors"))
        score = _parse_score(match.group("score"))
        latest_iteration = iteration
        latest_score = score
        latest_errors = errors
        if score == 0:
            match_found = True
        if global_best_score is None or score < global_best_score:
            if global_best_score is not None:
                record_improvements += 1
            global_best_iteration = iteration
            global_best_score = score
            global_best_errors = errors
            best_occurrences = 1
        elif score == global_best_score:
            best_occurrences += 1

    output_candidate_saved = (
        has_output_candidate
        or bool(_OUTPUT_CANDIDATE_RE.search(normalized))
    )
    verdict = _classify_log_summary(
        match_found=match_found,
        iteration_count=iteration_count,
        global_best_score=global_best_score,
        latest_score=latest_score,
        record_improvements=record_improvements,
        best_occurrences=best_occurrences,
    )
    return PermuterLogSummary(
        latest_iteration=latest_iteration,
        latest_score=latest_score,
        latest_errors=latest_errors,
        global_best_iteration=global_best_iteration,
        global_best_score=global_best_score,
        global_best_errors=global_best_errors,
        iteration_count=iteration_count,
        match_found=match_found,
        output_candidate_saved=output_candidate_saved,
        verdict=verdict,
    )


def remote_log_status(
    job: RemoteJob,
    runner: Callable[..., CommandResult] = run_command,
    timeout: float | None = None,
) -> RemoteLogStatus:
    """Read remote log metadata and full-log score summary for a job."""
    log_path = f"{job.remote_run_dir}/permuter.log"
    perm_path = job.remote_perm_dir
    script = (
        f"log={shlex.quote(log_path)}; "
        f"perm={shlex.quote(perm_path)}; "
        "if [ ! -f \"$log\" ]; then printf 'exists\t0\n'; exit 0; fi; "
        "printf 'exists\t1\n'; "
        "printf 'mtime\t'; "
        "(stat -c %Y \"$log\" 2>/dev/null || stat -f %m \"$log\" 2>/dev/null || printf 0); "
        "printf '\n'; "
        "printf 'has_output\t'; "
        "if [ -f \"$perm/best.c\" ] || "
        "find \"$perm\" -maxdepth 1 -type d -name 'output-*' -print -quit 2>/dev/null | "
        "grep -q .; then printf '1'; else printf '0'; fi; "
        "printf '\n'; "
        "printf 'log_begin\n'; "
        "cat \"$log\""
    )
    kwargs: dict[str, Any] = {"check": False}
    if timeout is not None:
        kwargs["timeout"] = timeout
    result = runner(["ssh", job.ssh, _remote_sh(script)], **kwargs)
    if result.returncode != 0:
        return RemoteLogStatus(
            exists=False,
            detail=result.stderr.strip() or result.stdout.strip(),
        )
    header, sep, log_text = result.stdout.partition("log_begin\n")
    fields: dict[str, str] = {}
    for line in header.splitlines():
        if "\t" not in line:
            continue
        key, value = line.split("\t", 1)
        fields[key] = value
    exists = fields.get("exists") == "1"
    modified_at = None
    raw_mtime = fields.get("mtime")
    if raw_mtime:
        try:
            modified_at = datetime.fromtimestamp(int(raw_mtime))
        except ValueError:
            modified_at = None
    if not exists:
        return RemoteLogStatus(exists=False, modified_at=modified_at)
    summary = parse_permuter_log_summary(
        log_text if sep else "",
        has_output_candidate=fields.get("has_output") == "1",
    )
    best = None
    if summary.global_best_score is not None:
        best = (
            f"{format_score(summary.global_best_score)} "
            f"@iter{summary.global_best_iteration}"
        )
    return RemoteLogStatus(
        exists=True,
        modified_at=modified_at,
        best_score=best,
        latest_iteration=summary.latest_iteration,
        latest_score=summary.latest_score,
        latest_errors=summary.latest_errors,
        global_best_iteration=summary.global_best_iteration,
        global_best_score=summary.global_best_score,
        global_best_errors=summary.global_best_errors,
        iteration_count=summary.iteration_count,
        match_found=summary.match_found,
        output_candidate_saved=summary.output_candidate_saved,
        verdict=summary.verdict,
    )


def sanitize_log_tail(text: str, *, lines: int) -> str:
    """Turn CR progress streams into bounded logical lines."""
    logical = text.replace("\r", "\n")
    cleaned_lines: list[str] = []
    for line in logical.splitlines():
        # Progress streams may include backspaces; dropping them is enough for
        # readable bounded status output and avoids trying to emulate a TTY.
        line = line.replace("\b", "")
        if line.strip():
            cleaned_lines.append(line)
    if lines > 0:
        cleaned_lines = cleaned_lines[-lines:]
    if not cleaned_lines:
        return ""
    return "\n".join(cleaned_lines) + "\n"


_RESOURCE_TRACKER_RE = re.compile(
    r"(?:^|\s)(?:\S*/)?python(?:\d+(?:\.\d+)*)?\s+-c\s+['\"]?"
    r"from multiprocessing\.resource_tracker import main;main\(\d+\)"
    r"['\"]?\s*$"
)
_SPAWN_WORKER_RE = re.compile(
    r"(?:^|\s)(?:\S*/)?python(?:\d+(?:\.\d+)*)?\s+-c\s+['\"]?"
    r"from multiprocessing\.spawn import spawn_main;\s*spawn_main\([^\r\n]*\)"
    r"['\"]?\s+--multiprocessing-fork\s*$"
)


def _python_process_kind(command: str) -> str | None:
    if _RESOURCE_TRACKER_RE.search(command):
        return "python-resource-tracker"
    if _SPAWN_WORKER_RE.search(command):
        return "python-spawn-worker"
    return None


def _is_legacy_wibo_command(command: str) -> bool:
    command_lower = command.lower()
    return "wibo" in command_lower and "mwcceppc" in command_lower


def _parse_birth_identity(tokens: list[str]) -> str | None:
    if len(tokens) != 5:
        return None
    weekday, month, day, clock, year = tokens
    if weekday not in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}:
        return None
    if month not in {
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    }:
        return None
    if not day.isdigit() or not 1 <= int(day) <= 31:
        return None
    clock_match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})", clock)
    if clock_match is None:
        return None
    hour, minute, second = (int(value) for value in clock_match.groups())
    if hour > 23 or minute > 59 or second > 60:
        return None
    if not re.fullmatch(r"\d{4}", year):
        return None
    return " ".join(tokens)


def _read_process_table(
    runner: Callable[..., CommandResult],
) -> list[_ProcessSnapshot] | None:
    try:
        result = runner(
            [
                "env", "LC_ALL=C", "ps", "-axo",
                "pid=,ppid=,pgid=,stat=,etime=,lstart=,command=",
            ],
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    processes: list[_ProcessSnapshot] = []
    for raw in result.stdout.splitlines():
        parts = raw.strip().split(None, 10)
        if len(parts) < 10:
            continue
        pid_s, ppid_s, pgid_s, stat, elapsed = parts[:5]
        birth_identity = _parse_birth_identity(parts[5:10])
        command = parts[10] if len(parts) == 11 else ""
        try:
            pid = int(pid_s)
            ppid = int(ppid_s)
            pgid = int(pgid_s)
        except ValueError:
            continue
        processes.append(_ProcessSnapshot(
            pid=pid,
            ppid=ppid,
            pgid=pgid,
            stat=stat,
            elapsed=elapsed,
            birth_identity=birth_identity,
            command=command,
        ))
    return processes


def _resolve_process_cwd(
    pid: int,
    runner: Callable[..., CommandResult],
) -> Path | None:
    proc_cwd = Path(f"/proc/{pid}/cwd")
    if proc_cwd.exists():
        try:
            return proc_cwd.resolve(strict=True)
        except (OSError, RuntimeError):
            return None
    try:
        result = runner(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    cwd_text = next(
        (line[1:] for line in result.stdout.splitlines() if line.startswith("n")),
        None,
    )
    if not cwd_text:
        return None
    try:
        return Path(cwd_text).resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _classify_orphaned_permuter_processes(
    processes: list[_ProcessSnapshot],
    *,
    perm_root: Path,
    runner: Callable[..., CommandResult],
    current_pgid: int,
) -> dict[int, OrphanedPermuterProcess]:
    found: dict[int, OrphanedPermuterProcess] = {}
    for proc in processes:
        kind = _python_process_kind(proc.command)
        if (
            kind is None
            or proc.birth_identity is None
            or proc.ppid != 1
            or proc.pgid <= 1
            or proc.pgid == current_pgid
        ):
            continue
        cwd = _resolve_process_cwd(proc.pid, runner)
        if cwd is None or not _is_within(cwd, perm_root):
            continue
        found[proc.pid] = OrphanedPermuterProcess(
            pid=proc.pid,
            ppid=proc.ppid,
            pgid=proc.pgid,
            stat=proc.stat,
            elapsed=proc.elapsed,
            birth_identity=proc.birth_identity,
            command=proc.command,
            cwd=cwd,
            kind=kind,
        )
    return found


def detect_orphaned_permuter_processes(
    *,
    perm_root: Path = Path("~/code/decomp-permuter"),
    runner: Callable[..., CommandResult] = run_command,
    current_pgid: int | None = None,
) -> list[OrphanedPermuterProcess]:
    """Find only proven abandoned compiler and multiprocessing helpers."""
    try:
        resolved_root = perm_root.expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return []
    processes = _read_process_table(runner)
    if processes is None:
        return []
    pgid = os.getpgrp() if current_pgid is None else current_pgid
    return list(_classify_orphaned_permuter_processes(
        processes,
        perm_root=resolved_root,
        runner=runner,
        current_pgid=pgid,
    ).values())


def detect_orphaned_wibo_processes(
    runner: Callable[..., CommandResult] = run_command,
) -> list[OrphanedWiboProcess]:
    """Compatibility report for PPID-1 wibo/MWCC processes."""
    processes = _read_process_table(runner)
    if processes is None:
        return []
    return [
        OrphanedWiboProcess(
            pid=proc.pid,
            ppid=proc.ppid,
            stat=proc.stat,
            elapsed=proc.elapsed,
            command=proc.command,
        )
        for proc in processes
        if proc.ppid == 1 and _is_legacy_wibo_command(proc.command)
    ]


def terminate_orphaned_permuter_processes(
    candidates: list[OrphanedPermuterProcess],
    *,
    perm_root: Path,
    runner: Callable[..., CommandResult] = run_command,
    killpg: Callable[[int, int], None] = os.killpg,
    current_pgid: int | None = None,
    grace_seconds: float = 2.0,
) -> OrphanCleanupReport:
    """Revalidate and terminate safe, homogeneous orphan process groups."""
    try:
        resolved_root = perm_root.expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return OrphanCleanupReport(
            terminated_pids=(),
            surviving_pids=tuple(sorted(proc.pid for proc in candidates)),
            skipped_groups={proc.pgid: "permuter root could not be resolved" for proc in candidates},
        )
    own_pgid = os.getpgrp() if current_pgid is None else current_pgid
    original_by_group: dict[int, list[OrphanedPermuterProcess]] = {}
    for candidate in candidates:
        original_by_group.setdefault(candidate.pgid, []).append(candidate)

    terminated: set[int] = set()
    survivors: set[int] = set()
    skipped: dict[int, str] = {}
    for pgid, originals in sorted(original_by_group.items()):
        if pgid <= 1 or pgid == own_pgid:
            skipped[pgid] = "unsafe process group"
            survivors.update(proc.pid for proc in originals)
            continue
        processes = _read_process_table(runner)
        if processes is None:
            skipped[pgid] = "could not re-scan process table"
            survivors.update(proc.pid for proc in originals)
            continue
        members = [proc for proc in processes if proc.pgid == pgid]
        if not members:
            terminated.update(proc.pid for proc in originals)
            continue
        recognized = _classify_orphaned_permuter_processes(
            members,
            perm_root=resolved_root,
            runner=runner,
            current_pgid=own_pgid,
        )
        if any(member.pid not in recognized for member in members):
            birth_mismatch = any(
                member.pid == original.pid
                and member.birth_identity != original.birth_identity
                for member in members
                for original in originals
            )
            skipped[pgid] = (
                "candidate birth identity changed before SIGTERM"
                if birth_mismatch
                else "process group contains an unrecognized member"
            )
            survivors.update(proc.pid for proc in originals)
            continue
        changed = False
        birth_changed_before_term = False
        for original in originals:
            current = recognized.get(original.pid)
            if (
                current is not None
                and current.birth_identity != original.birth_identity
            ):
                birth_changed_before_term = True
            if current is None or (
                current.pgid != original.pgid
                or current.birth_identity != original.birth_identity
                or current.command != original.command
                or current.cwd != original.cwd
                or current.kind != original.kind
            ):
                changed = True
                break
        if changed:
            skipped[pgid] = (
                "candidate birth identity changed before SIGTERM"
                if birth_changed_before_term
                else "candidate changed during PID reuse revalidation"
            )
            survivors.update(proc.pid for proc in originals)
            continue
        if any("U" in member.stat for member in members):
            skipped[pgid] = "uninterruptible process; restart the host"
            survivors.update(member.pid for member in members)
            continue
        try:
            killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            terminated.update(member.pid for member in members)
            continue
        except PermissionError:
            skipped[pgid] = "permission denied while signaling process group"
            survivors.update(member.pid for member in members)
            continue
        time.sleep(max(0.0, grace_seconds))
        remaining = _read_process_table(runner)
        if remaining is None:
            skipped[pgid] = "could not verify termination"
            survivors.update(member.pid for member in members)
            continue
        live = [proc for proc in remaining if proc.pgid == pgid]
        if live:
            birth_changed = any(
                proc.pid in recognized
                and proc.birth_identity != recognized[proc.pid].birth_identity
                for proc in live
            )
            live_recognized = _classify_orphaned_permuter_processes(
                live,
                perm_root=resolved_root,
                runner=runner,
                current_pgid=own_pgid,
            )
            group_changed = any(
                proc.pid not in live_recognized
                or proc.pid not in recognized
                or live_recognized[proc.pid].birth_identity
                != recognized[proc.pid].birth_identity
                or live_recognized[proc.pid].command != recognized[proc.pid].command
                or live_recognized[proc.pid].cwd != recognized[proc.pid].cwd
                or live_recognized[proc.pid].kind != recognized[proc.pid].kind
                for proc in live
            )
            if group_changed:
                skipped[pgid] = (
                    "process birth identity changed before SIGKILL"
                    if birth_changed
                    else "process group changed before SIGKILL revalidation"
                )
                survivors.update(proc.pid for proc in live)
                terminated.update(
                    proc.pid for proc in members if proc.pid not in survivors
                )
                continue
            try:
                killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                live = []
            except PermissionError:
                skipped[pgid] = "permission denied while escalating process group"
                survivors.update(proc.pid for proc in live)
                continue
            if live:
                time.sleep(min(max(0.0, grace_seconds), 0.1))
                final = _read_process_table(runner)
                if final is None:
                    survivors.update(proc.pid for proc in live)
                else:
                    live = [proc for proc in final if proc.pgid == pgid]
        survivors.update(proc.pid for proc in live)
        terminated.update(proc.pid for proc in members if proc.pid not in survivors)
    return OrphanCleanupReport(
        terminated_pids=tuple(sorted(terminated)),
        surviving_pids=tuple(sorted(survivors)),
        skipped_groups=skipped,
    )


def _local_fetch_identity(job: RemoteJob) -> Any:
    from . import local_remote_runs  # noqa: PLC0415

    return local_remote_runs.RemoteRunIdentity(**asdict(job))


def _prepare_local_fetch_destination(job: RemoteJob, fetch_dest: Path) -> None:
    from . import local_remote_runs  # noqa: PLC0415

    identity = _local_fetch_identity(job)
    function_dir = Path(job.local_perm_dir).expanduser()
    if not function_dir.is_absolute():
        raise RemoteJobError("remote fetch destination requires an absolute local permuter path")
    function_dir = function_dir.absolute()
    expected = function_dir / "remote-runs" / job.job_id
    if fetch_dest.expanduser().absolute() != expected:
        raise RemoteJobError(
            f"remote fetch destination is outside the owned job path: {fetch_dest}"
        )
    if function_dir.name != job.function or function_dir.parent.name != "nonmatchings":
        raise RemoteJobError("remote fetch destination is outside nonmatchings ownership")
    perm_root = function_dir.parent.parent
    try:
        perm_root.mkdir(parents=True, exist_ok=True)
        for owner in (
            perm_root,
            function_dir.parent,
            function_dir,
            function_dir / "remote-runs",
            expected,
        ):
            try:
                owner_stat = owner.lstat()
            except FileNotFoundError:
                owner.mkdir(mode=0o700)
                owner_stat = owner.lstat()
            if owner.is_symlink() or not stat.S_ISDIR(owner_stat.st_mode):
                raise RemoteJobError(f"unsafe remote fetch destination owner: {owner}")
        _, detail = local_remote_runs._manifest_owned_run_root(expected, identity)
        if detail:
            raise RemoteJobError(f"unsafe remote fetch destination: {detail}")
    except RemoteJobError:
        raise
    except OSError as exc:
        raise RemoteJobError(f"unable to prepare remote fetch destination: {exc}") from exc


def _mark_local_fetch_failure(
    fetch_dest: Path,
    *,
    job: RemoteJob,
    label: str,
    detail: str,
) -> str:
    from . import local_remote_runs  # noqa: PLC0415

    state, state_detail = local_remote_runs.local_fetch_warning_state(
        fetch_dest,
        identity=_local_fetch_identity(job),
    )
    if state == "regular":
        return ""
    if state == "unsafe":
        return state_detail or "unsafe existing remote fetch warning"
    try:
        _write_remote_fetch_warning(
            fetch_dest,
            job=job,
            remote_status=RemoteStatus(job.job_id, "unknown", detail),
            rsync_failures=[{
                "command": label,
                "returncode": -1,
                "stderr": detail,
            }],
        )
    except (OSError, RemoteJobError) as exc:
        return str(exc)
    return ""


def fetch_job(
    job: RemoteJob,
    runner: Callable[..., CommandResult] = run_command,
    dest: Path | None = None,
) -> Path:
    """Fetch remote permuter outputs for a job into a local run directory."""
    fetch_dest = dest if dest is not None else Path(job.local_perm_dir) / "remote-runs" / job.job_id
    remote_run_dest = fetch_dest / "remote-run"
    _prepare_local_fetch_destination(job, fetch_dest)
    try:
        remote_run_dest.mkdir(mode=0o700)
    except FileExistsError:
        try:
            remote_stat = remote_run_dest.lstat()
        except OSError as exc:
            raise RemoteJobError(f"unsafe remote metadata destination: {exc}") from exc
        if remote_run_dest.is_symlink() or not stat.S_ISDIR(remote_stat.st_mode):
            raise RemoteJobError(f"unsafe remote metadata destination: {remote_run_dest}")
    seed_prefix = f"nonmatchings/{job.function}"
    seed_files = [
        "base.c",
        "base.o",
        "compile.sh",
        "settings.toml",
        "target.o",
        "target.s",
    ]
    fetch_commands = [
        [
            "rsync",
            "-az",
            "--include",
            "output-*/***",
            "--include",
            "best.c",
            "--include",
            "*.log",
            "--exclude",
            "*",
            f"{job.ssh}:{job.remote_perm_dir}/",
            f"{fetch_dest}/",
        ],
        [
            "rsync",
            "-az",
            "--prune-empty-dirs",
            "--include",
            "metadata.json",
            "--include",
            "*.log",
            "--include",
            "nonmatchings/",
            "--include",
            f"{seed_prefix}/",
            *[
                item
                for name in seed_files
                for item in ("--include", f"{seed_prefix}/{name}")
            ],
            "--exclude",
            "nonmatchings/***",
            "--exclude",
            "*",
            f"{job.ssh}:{job.remote_run_dir}/",
            f"{remote_run_dest}/",
        ],
    ]
    rsync_failures: list[dict[str, Any]] = []
    for command in fetch_commands:
        result = runner(command, check=False)
        if result.returncode != 0:
            rsync_failures.append(_remote_fetch_rsync_failure(command, result))
    remote_status: RemoteStatus | None = None
    active_failure_detail: str | None = None
    if rsync_failures:
        remote_status = status_job(job, runner=runner)
        _write_remote_fetch_warning(
            fetch_dest,
            job=job,
            remote_status=remote_status,
            rsync_failures=rsync_failures,
        )
        if remote_status.state == "active":
            active_failure_detail = _format_remote_fetch_failure_detail(
                remote_status,
                rsync_failures,
            )
    try:
        audit_summary = candidate_audit.audit_candidate_tree(
            fetch_dest,
            function=job.function,
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        warning_failure = _mark_local_fetch_failure(
            fetch_dest,
            job=job,
            label="local candidate audit",
            detail=detail,
        )
        warning_detail = (
            f"; warning update failed: {warning_failure}"
            if warning_failure
            else ""
        )
        raise RemoteJobError(
            f"remote fetch candidate audit failed for {job.job_id}: "
            f"{detail}{warning_detail}"
        ) from exc

    from . import local_remote_runs  # noqa: PLC0415

    manifest_result = local_remote_runs.write_local_fetch_manifest(
        fetch_dest,
        identity=_local_fetch_identity(job),
        state="partial" if rsync_failures else "complete",
        candidate_audit=audit_summary,
    )
    if not manifest_result.ok:
        detail = manifest_result.detail or manifest_result.status
        warning_failure = _mark_local_fetch_failure(
            fetch_dest,
            job=job,
            label="local fetch manifest",
            detail=detail,
        )
        warning_detail = (
            f"; warning update failed: {warning_failure}"
            if warning_failure
            else ""
        )
        raise RemoteJobError(
            f"remote fetch manifest publication failed for {job.job_id}: "
            f"{detail}{warning_detail}"
        )
    if not rsync_failures:
        _clear_remote_fetch_warning(fetch_dest, job=job)
    if active_failure_detail is not None:
        raise RemoteJobError(
            f"remote fetch failed for active job {job.job_id}: {active_failure_detail}"
        )
    return fetch_dest


def _remote_fetch_rsync_failure(
    command: list[str],
    result: CommandResult,
) -> dict[str, Any]:
    failure: dict[str, Any] = {
        "command": shlex.join(command),
        "returncode": result.returncode,
    }
    if result.stdout.strip():
        failure["stdout"] = _truncate_middle(result.stdout.strip(), 1200)
    if result.stderr.strip():
        failure["stderr"] = _truncate_middle(result.stderr.strip(), 1200)
    return failure


def _write_remote_fetch_warning(
    fetch_dest: Path,
    *,
    job: RemoteJob,
    remote_status: RemoteStatus,
    rsync_failures: list[dict[str, Any]],
) -> None:
    payload: dict[str, Any] = {
        "status": "partial",
        "job_id": job.job_id,
        "function": job.function,
        "target": job.target,
        "remote_status": remote_status.state,
        "remote_run_dir": job.remote_run_dir,
        "remote_perm_dir": job.remote_perm_dir,
        "rsync_failures": rsync_failures,
        "message": (
            "Remote fetch preserved available local artifacts, but one or "
            "more rsync passes failed. For stopped or unknown jobs this is "
            "treated as a partial fetch so triage can continue."
        ),
    }
    if remote_status.detail:
        payload["remote_status_detail"] = remote_status.detail
    from . import local_remote_runs  # noqa: PLC0415

    written, detail = local_remote_runs.write_local_fetch_warning(
        fetch_dest,
        identity=_local_fetch_identity(job),
        payload=payload,
    )
    if not written:
        raise RemoteJobError(f"remote fetch warning publication failed: {detail}")


def _clear_remote_fetch_warning(fetch_dest: Path, *, job: RemoteJob) -> None:
    from . import local_remote_runs  # noqa: PLC0415

    cleared, detail = local_remote_runs.clear_local_fetch_warning(
        fetch_dest,
        identity=_local_fetch_identity(job),
    )
    if not cleared:
        raise RemoteJobError(f"remote fetch warning clear failed: {detail}")


def _format_remote_fetch_failure_detail(
    remote_status: RemoteStatus,
    rsync_failures: list[dict[str, Any]],
) -> str:
    failure_text = "; ".join(
        _compact_submit_failure_text(
            str(failure.get("stderr") or failure.get("stdout") or failure)
        )
        for failure in rsync_failures
    )
    detail = f"remote status {remote_status.state!r}"
    if remote_status.detail:
        detail += f" ({remote_status.detail})"
    if failure_text:
        detail += f"; {failure_text}"
    return detail


def tail_job(
    job: RemoteJob,
    runner: Callable[..., CommandResult] | None = None,
    lines: int = 80,
    follow: bool = False,
    max_bytes: int = 65536,
) -> CommandResult:
    """Read a remote job's permuter log, following only when requested."""
    if follow and runner is None:
        raise RemoteJobError(
            "tail_job requires an explicit streaming runner; "
            "tail -f must not use the capturing default runner"
        )
    if runner is None:
        runner = run_command
    if isinstance(lines, bool) or not isinstance(lines, int) or lines < 1:
        raise RemoteJobError("tail lines must be a positive integer")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1024:
        raise RemoteJobError("tail max_bytes must be an integer >= 1024")
    if follow:
        tail_cmd = f"tail -n {lines} -f"
    else:
        tail_cmd = f"tail -c {max_bytes}"
    return runner(
        [
            "ssh",
            job.ssh,
            _remote_sh(
                f"{tail_cmd} "
                f"{shlex.quote(job.remote_run_dir)}/permuter.log"
            ),
        ],
        check=False,
    )


def stop_job(
    job: RemoteJob,
    runner: Callable[..., CommandResult] = run_command,
) -> CommandResult:
    """Stop a remote job's tmux session."""
    return runner(
        [
            "ssh",
            job.ssh,
            _remote_sh(
                f"tmux kill-session -t {shlex.quote(job.tmux_session)}"
            ),
        ],
        check=False,
    )


def doctor_target(
    target: RemoteTarget,
    local_perm_dir: Path | None = None,
    runner: Callable[..., CommandResult] = run_command,
    require_remote_scorer_target: bool = True,
    timeout: float = DEFAULT_REMOTE_DOCTOR_TIMEOUT,
) -> DoctorReport:
    """Run read-only checks for a remote permuter target."""
    checks: list[DoctorCheck] = [
        DoctorCheck(
            "config target roots",
            _looks_persistent_root(target.remote_melee_root)
            and _looks_persistent_root(target.remote_perm_root),
            (
                f"melee={target.remote_melee_root} "
                f"permuter={target.remote_perm_root}"
            ),
        ),
        DoctorCheck(
            "config threads",
            not isinstance(target.threads, bool) and target.threads > 0,
            str(target.threads),
        ),
    ]
    scorer_info: ScorerCommandInfo | None = None
    objdump_info: ObjdumpCommandInfo | None = None
    if local_perm_dir is not None:
        checks.extend(_doctor_local_perm_dir(local_perm_dir, target=target))
        scorer_checks, scorer_info = _doctor_local_scorer(
            local_perm_dir,
            target=target,
        )
        checks.extend(scorer_checks)
        objdump_checks, objdump_info = _doctor_local_objdump(local_perm_dir, target=target)
        checks.extend(objdump_checks)

    script = _remote_doctor_script(
        target,
        scorer_info=scorer_info,
        objdump_info=objdump_info,
        require_remote_scorer_target=require_remote_scorer_target,
    )
    if timeout <= 0:
        checks.append(DoctorCheck(
            "remote ssh",
            False,
            "doctor timeout must be positive",
        ))
        return DoctorReport(target=target.name, checks=checks)
    result = _run_bounded_command(
        runner,
        ["ssh", target.ssh, _remote_sh(script)],
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "ssh command failed"
        checks.append(DoctorCheck("remote ssh", False, detail))
    else:
        checks.extend(_parse_remote_doctor_output(
            result.stdout,
            expect_scorer=scorer_info is not None,
            expect_remote_scorer_target=(
                require_remote_scorer_target
                and scorer_info is not None
                and scorer_info.target_path is not None
            ),
            expect_objdump=objdump_info is not None,
        ))

    return DoctorReport(target=target.name, checks=checks)


def suggest_ready_targets(
    targets: Mapping[str, RemoteTarget],
    *,
    failed_target_name: str,
    local_perm_dir: Path | None = None,
    runner: Callable[..., CommandResult] = run_command,
    limit: int = 3,
) -> list[str]:
    """Return configured sibling targets whose doctor checks currently pass."""
    ready: list[str] = []
    for name in sorted(targets):
        if name == failed_target_name:
            continue
        try:
            report = doctor_target(
                targets[name],
                local_perm_dir=local_perm_dir,
                runner=runner,
            )
        except RemoteJobError:
            continue
        if report.ok:
            ready.append(name)
            if len(ready) >= limit:
                break
    return ready


def repair_target(
    target: RemoteTarget,
    *,
    local_melee_root: Path,
    local_perm_root: Path,
    function: str | None = None,
    local_perm_dir: Path | None = None,
    runner: Callable[..., CommandResult] = run_command,
) -> RepairReport:
    """Bootstrap project-owned remote tooling and user-site Python deps."""
    local_melee_root = local_melee_root.expanduser()
    local_perm_root = local_perm_root.expanduser()
    _require_dir(local_melee_root / "tools" / "melee-agent", "local melee-agent tools")
    _require_dir(local_melee_root / "tools" / "mwcc_debug", "local mwcc_debug tools")
    _require_dir(local_melee_root / "tools" / "mwcc_retro", "local mwcc_retro tools")
    _require_file(_remote_compiler_file(local_melee_root, "mwcceppc_debug.exe"), "local debug compiler")
    _require_file(_remote_compiler_file(local_melee_root, "MWDBG326.dll"), "local debug compiler DLL")
    _require_dir(local_perm_root, "local decomp-permuter root")

    actions: list[str] = []
    runner(
        [
            "ssh",
            target.ssh,
            _remote_sh(
                "mkdir -p "
                f"{shlex.quote(target.remote_melee_root)} "
                f"{shlex.quote(target.remote_perm_root)} "
                f"{shlex.quote(target.remote_melee_root + '/tools')} "
                f"{shlex.quote(target.remote_melee_root + '/build/tools')} "
                f"{shlex.quote(target.remote_melee_root + '/build/compilers/GC/1.2.5n')}"
            ),
        ],
        check=True,
    )
    actions.append("created remote project directories")

    runner([
        "rsync",
        "-az",
        "--delete",
        f"{local_melee_root / 'tools' / 'melee-agent'}/",
        f"{target.ssh}:{target.remote_melee_root}/tools/melee-agent/",
    ])
    actions.append("synced tools/melee-agent")

    runner([
        "rsync",
        "-az",
        "--delete",
        f"{local_melee_root / 'tools' / 'mwcc_debug'}/",
        f"{target.ssh}:{target.remote_melee_root}/tools/mwcc_debug/",
    ])
    actions.append("synced tools/mwcc_debug")

    runner([
        "rsync",
        "-az",
        "--delete",
        f"{local_melee_root / 'tools' / 'mwcc_retro'}/",
        f"{target.ssh}:{target.remote_melee_root}/tools/mwcc_retro/",
    ])
    actions.append("synced tools/mwcc_retro")

    runner([
        "rsync",
        "-az",
        str(_remote_compiler_file(local_melee_root, "mwcceppc_debug.exe")),
        str(_remote_compiler_file(local_melee_root, "MWDBG326.dll")),
        f"{target.ssh}:{target.remote_melee_root}/build/compilers/GC/1.2.5n/",
    ])
    actions.append("synced MWCC debug compiler")

    runner([
        "rsync",
        "-az",
        "--delete",
        "--exclude",
        ".git",
        "--exclude",
        ".venv",
        "--exclude",
        "__pycache__",
        "--exclude",
        "*.pyc",
        "--exclude",
        "remote-runs",
        "--exclude",
        "remote-runs/***",
        "--exclude",
        "nonmatchings",
        "--exclude",
        "nonmatchings/***",
        "--exclude",
        "output-*",
        "--exclude",
        "output-*/***",
        f"{local_perm_root}/",
        f"{target.ssh}:{target.remote_perm_root}/",
    ])
    actions.append("synced decomp-permuter")

    if function is not None and local_perm_dir is not None:
        _require_dir(local_perm_dir, "local permuter function dir")
        scorer_info = _doctor_local_scorer(local_perm_dir)[1]
        remote_function_dir = _remote_function_dir(target, function, scorer_info)
        _validate_remote_repair_path(target, remote_function_dir)
        runner([
            "ssh",
            target.ssh,
            _remote_sh(
                f"rm -rf {shlex.quote(remote_function_dir)} && "
                f"mkdir -p {shlex.quote(remote_function_dir)}"
            ),
        ])
        actions.append(f"reset remote function dir {function}")
        runner([
            "rsync",
            "-az",
            "--delete",
            *[
                item
                for pattern in FUNCTION_HISTORY_EXCLUDES
                for item in ("--exclude", pattern)
            ],
            f"{local_perm_dir}/",
            f"{target.ssh}:{remote_function_dir}/",
        ])
        actions.append(f"synced function dir {function}")

    runner(["ssh", target.ssh, _remote_sh(_remote_repair_bootstrap_script(target))])
    actions.append("installed remote python dependencies")
    actions.append("refreshed remote Linux wibo")
    actions.append("refreshed remote Linux dtk")
    actions.append("refreshed remote melee-agent wrapper")

    return RepairReport(target=target.name, actions=actions)


def submit_job(
    function: str,
    target: RemoteTarget,
    local_perm_dir: Path,
    jobs_dir: Path = JOBS_DIR,
    threads: int | None = None,
    mode: str = "stock",
    runner: Callable[..., CommandResult] = run_command,
    now: Callable[[], str] | None = None,
    local_melee_root: Path | None = None,
    local_perm_root: Path | None = None,
    auto_repair: bool = True,
) -> RemoteJob:
    """Copy a local permuter directory to a remote target and start it in tmux."""
    if mode != "stock":
        raise RemoteJobError("Remote permuter submit currently only supports stock mode.")
    if not local_perm_dir.is_dir():
        raise RemoteJobError(f"local permuter dir not found: {local_perm_dir}")
    created_at = now() if now is not None else datetime.now().replace(microsecond=0).isoformat()
    job_id = _job_id(function, target.name, created_at)
    effective_threads = threads if threads is not None else target.threads
    if isinstance(effective_threads, bool) or effective_threads < 1:
        raise RemoteJobError("Remote permuter submit requires a positive integer thread count.")

    remote_run_dir = f"{target.remote_perm_root}/remote-runs/{job_id}"
    remote_perm_dir = f"{remote_run_dir}/nonmatchings/{function}"
    tmux_session = f"{target.session_prefix}-{job_id}"
    job = RemoteJob(
        job_id=job_id,
        function=function,
        target=target.name,
        ssh=target.ssh,
        remote_perm_dir=remote_perm_dir,
        remote_run_dir=remote_run_dir,
        local_perm_dir=str(local_perm_dir),
        tmux_session=tmux_session,
        threads=effective_threads,
        mode=mode,
        created_at=created_at,
    )
    if (jobs_dir / f"{job.job_id}.json").exists():
        raise RemoteJobError(
            f"Remote permuter job metadata already exists: "
            f"{jobs_dir / f'{job.job_id}.json'}"
        )

    with _staged_remote_perm_dir(
        local_perm_dir,
        target=target,
        remote_perm_dir=remote_perm_dir,
    ) as submit_perm_dir:
        _validate_remote_ready_perm_dir(submit_perm_dir)
        preflight = doctor_target(
            target,
            local_perm_dir=submit_perm_dir,
            runner=runner,
            require_remote_scorer_target=False,
        )
        if (
            not preflight.ok
            and auto_repair
            and _preflight_can_be_repaired(preflight)
        ):
            try:
                repair_target(
                    target,
                    local_melee_root=_resolve_auto_repair_melee_root(local_melee_root),
                    local_perm_root=_resolve_auto_repair_perm_root(
                        local_perm_root,
                        local_perm_dir,
                    ),
                    runner=runner,
                )
            except RemoteJobError as exc:
                raise RemoteJobError(
                    f"remote preflight failed for {target.name}: "
                    f"{_preflight_failure_detail(preflight)}; "
                    f"auto-repair failed: {exc}"
                ) from exc
            preflight = doctor_target(
                target,
                local_perm_dir=submit_perm_dir,
                runner=runner,
                require_remote_scorer_target=False,
            )
        if not preflight.ok:
            raise RemoteJobError(
                f"remote preflight failed for {target.name}: "
                f"{_preflight_failure_detail(preflight)}"
            )

        job_path = write_job(job, jobs_dir=jobs_dir)
        try:
            runner(
                [
                    "rsync",
                    "-az",
                    "--delete",
                    "--rsync-path",
                    f"mkdir -p {shlex.quote(remote_perm_dir)} && rsync",
                    f"{submit_perm_dir}/",
                    f"{target.ssh}:{remote_perm_dir}/",
                ],
                check=True,
            )
            runner(
                ["ssh", target.ssh, _remote_sh(_remote_submit_script(job, target))],
                check=True,
            )
        except Exception as exc:
            _remove_job_metadata_best_effort(job_path)
            cleanup_detail = _cleanup_remote_run_dir_best_effort(
                job,
                target,
                runner=runner,
            )
            raise RemoteJobError(
                _format_submit_not_started_error(
                    job,
                    exc,
                    cleanup_detail=cleanup_detail,
                )
            ) from exc
        return job


def _job_id(function: str, target: str, created_at: str) -> str:
    timestamp = datetime.fromisoformat(created_at).strftime("%Y%m%d-%H%M%S")
    return f"{function}-{target}-{timestamp}"


def _remote_compiler_file(local_melee_root: Path, name: str) -> Path:
    return local_melee_root / "build" / "compilers" / "GC" / "1.2.5n" / name


def _require_dir(path: Path, label: str) -> None:
    if not path.is_dir():
        raise RemoteJobError(f"{label} not found: {path}")


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise RemoteJobError(f"{label} not found: {path}")


def _remote_function_dir(
    target: RemoteTarget,
    function: str,
    scorer_info: ScorerCommandInfo | None,
) -> str:
    if scorer_info is not None and scorer_info.target_path is not None:
        target_path = scorer_info.target_path
        if target_path.startswith("/"):
            return posixpath.dirname(target_path)
    return f"{target.remote_perm_root}/nonmatchings/{function}"


def _validate_remote_repair_path(target: RemoteTarget, remote_path: str) -> None:
    root = target.remote_perm_root.rstrip("/")
    if remote_path == root or not remote_path.startswith(root + "/"):
        raise RemoteJobError(
            f"refusing to repair path outside remote permuter root: {remote_path}"
        )


def _remote_repair_bootstrap_script(target: RemoteTarget) -> str:
    melee_agent_root = f"{target.remote_melee_root}/tools/melee-agent"
    wibo_path = f"{target.remote_melee_root}/tools/mwcc_debug/bin/wibo"
    dtk_path = f"{target.remote_melee_root}/build/tools/dtk"
    deps = " ".join(shlex.quote(dep) for dep in PYTHON_DEPS)
    wrapper_static_lines = [
        "#!/bin/sh",
        f"cd {shlex.quote(melee_agent_root)}",
        f"export PYTHONPATH={shlex.quote(melee_agent_root)}",
    ]
    wrapper_printf_args = " ".join(shlex.quote(line) for line in wrapper_static_lines)
    return "\n".join([
        "set -eu",
        f"melee_agent_root={shlex.quote(melee_agent_root)}",
        f"wibo_path={shlex.quote(wibo_path)}",
        f"dtk_path={shlex.quote(dtk_path)}",
        'if command -v python3.11 >/dev/null 2>&1; then py_path="$(command -v python3.11)"; '
        "elif command -v python3 >/dev/null 2>&1 && python3 - <<'PY' >/dev/null 2>&1\n"
        "import sys\n"
        "raise SystemExit(0 if sys.version_info >= (3, 11) else 1)\n"
        "PY\n"
        'then py_path="$(command -v python3)"; else echo "python >=3.11 missing" >&2; exit 1; fi',
        f'"$py_path" -m pip install --user {deps}',
        'mkdir -p "$(dirname "$wibo_path")" "$(dirname "$dtk_path")" "$HOME/.local/bin"',
        'if ! test -x "$wibo_path" || ! "$wibo_path" --version >/dev/null 2>&1; then '
        'curl -fsSL --retry 4 --connect-timeout 20 '
        '-o "$wibo_path" '
        'https://github.com/decompals/wibo/releases/download/1.0.0/wibo-x86_64; '
        'chmod +x "$wibo_path"; fi',
        'dtk_arch="$(uname -m)"; case "$dtk_arch" in x86_64|amd64) dtk_arch=x86_64 ;; aarch64|arm64) dtk_arch=aarch64 ;; *) echo "unsupported dtk architecture: $dtk_arch" >&2; exit 1 ;; esac',
        'if ! test -x "$dtk_path" || ! "$dtk_path" --version >/dev/null 2>&1; then '
        'curl -fsSL --retry 4 --connect-timeout 20 '
        '-o "$dtk_path" '
        f'https://github.com/encounter/decomp-toolkit/releases/download/{DTK_TAG}/dtk-linux-$dtk_arch; '
        'chmod +x "$dtk_path"; fi',
        f"printf '%s\\n' {wrapper_printf_args} "
        '"exec \\"$py_path\\" -m src.cli \\"\\$@\\"" '
        '> "$HOME/.local/bin/melee-agent"',
        'chmod +x "$HOME/.local/bin/melee-agent"',
    ])


def _remote_submit_script(job: RemoteJob, target: RemoteTarget) -> str:
    metadata = json.dumps(asdict(job), indent=2)
    perm_rel = f"remote-runs/{job.job_id}/nonmatchings/{job.function}"
    return "\n".join(
        [
            "set -eu",
            f"remote_perm_root={shlex.quote(target.remote_perm_root)}",
            f"remote_melee_root={shlex.quote(target.remote_melee_root)}",
            f"remote_perm_dir={shlex.quote(job.remote_perm_dir)}",
            f"remote_run_dir={shlex.quote(job.remote_run_dir)}",
            f"tmux_session={shlex.quote(job.tmux_session)}",
            'test -d "$remote_perm_root"',
            'test -d "$remote_melee_root"',
            "command -v tmux >/dev/null 2>&1",
            'if command -v python3.11 >/dev/null 2>&1; then remote_py="$(command -v python3.11)"; '
            'elif command -v python3 >/dev/null 2>&1 && python3 - <<\'PY\' >/dev/null 2>&1\n'
            "import sys\n"
            "raise SystemExit(0 if sys.version_info >= (3, 11) else 1)\n"
            "PY\n"
            'then remote_py="$(command -v python3)"; else echo "python >=3.11 missing" >&2; exit 1; fi',
            "export remote_py",
            'mkdir -p "$remote_run_dir"',
            f"printf '%s\\n' {shlex.quote(metadata)} > \"$remote_run_dir/metadata.json\"",
            (
                'tmux new-session -d -s "$tmux_session" '
                f'"cd \\"$remote_perm_root\\" && MELEE_ROOT=\\"$remote_melee_root\\" '
                f'\\"$remote_py\\" ./permuter.py {shlex.quote(perm_rel)} '
                f'-j {job.threads} > \\"$remote_run_dir/permuter.log\\" 2>&1"'
            ),
            "sleep 1",
            'if ! tmux has-session -t "$tmux_session" 2>/dev/null; then',
            '  echo "tmux session exited immediately: $tmux_session" >&2',
            '  if test -s "$remote_run_dir/permuter.log"; then',
            '    echo "last permuter.log lines:" >&2',
            '    tail -n 80 "$remote_run_dir/permuter.log" >&2 || true',
            "  else",
            '    echo "permuter.log missing or empty: $remote_run_dir/permuter.log" >&2',
            "  fi",
            "  exit 1",
            "fi",
        ]
    )


def _remote_cleanup_run_dir_script(job: RemoteJob, remote_runs_root: str) -> str:
    return "\n".join([
        "set -eu",
        f"remote_run_dir={shlex.quote(job.remote_run_dir)}",
        f"remote_runs_root={shlex.quote(remote_runs_root.rstrip('/'))}",
        'case "$remote_run_dir" in',
        '  "$remote_runs_root"/*) rm -rf -- "$remote_run_dir" ;;',
        '  *) echo "refusing to clean path outside remote-runs: $remote_run_dir" >&2; exit 2 ;;',
        "esac",
    ])


def _remote_runs_root_from_job(job: RemoteJob) -> str:
    run_dir = job.remote_run_dir.rstrip("/")
    marker = "/remote-runs/"
    if marker not in run_dir:
        raise RemoteJobError(
            f"refusing to clean path outside remote-runs: {job.remote_run_dir}"
        )
    root, leaf = run_dir.split(marker, 1)
    if not root or not leaf:
        raise RemoteJobError(
            f"refusing to clean path outside remote-runs: {job.remote_run_dir}"
        )
    return f"{root}/remote-runs"


def cleanup_remote_run_dir(
    job: RemoteJob,
    runner: Callable[..., CommandResult] = run_command,
) -> None:
    """Delete a fetched job's remote run directory from its remote coder."""
    remote_runs_root = _remote_runs_root_from_job(job)
    status = status_job(job, runner=runner, timeout=10.0)
    if status.state == "active":
        raise RemoteJobError(
            f"remote job {job.job_id} is still active; refusing to delete "
            f"{job.remote_run_dir}"
        )
    if status.state != "stopped":
        detail = f": {status.detail}" if status.detail else ""
        raise RemoteJobError(
            f"remote job {job.job_id} status is {status.state!r}{detail}; "
            f"refusing to delete {job.remote_run_dir}"
        )
    result = runner(
        ["ssh", job.ssh, _remote_sh(_remote_cleanup_run_dir_script(job, remote_runs_root))],
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RemoteJobError(
            f"remote run dir cleanup failed: {_compact_submit_failure_text(detail)}"
        )


def cleanup_remote_run_dir_best_effort(
    job: RemoteJob,
    runner: Callable[..., CommandResult] = run_command,
) -> str | None:
    """Delete a remote run directory, returning a warning string on failure."""
    try:
        cleanup_remote_run_dir(job, runner=runner)
    except Exception as exc:
        return f"remote run dir cleanup failed: {_compact_submit_failure_detail(exc)}"
    return None


def _cleanup_remote_run_dir_best_effort(
    job: RemoteJob,
    target: RemoteTarget,
    *,
    runner: Callable[..., CommandResult],
) -> str | None:
    remote_root = target.remote_perm_root.rstrip("/")
    remote_runs_root = f"{remote_root}/remote-runs"
    try:
        result = runner(
            ["ssh", target.ssh, _remote_sh(_remote_cleanup_run_dir_script(job, remote_runs_root))],
            check=False,
        )
    except Exception as exc:
        return f"remote run dir cleanup failed: {_compact_submit_failure_detail(exc)}"
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        return f"remote run dir cleanup failed: {_compact_submit_failure_text(detail)}"
    return None


def _compact_submit_failure_text(text: str) -> str:
    raw = text.strip()
    if not raw:
        return "no detail"
    interesting = []
    markers = (
        "error",
        "failed",
        "timeout",
        "timed out",
        "denied",
        "not found",
        "no such",
        "tmux session exited",
    )
    for line in raw.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in markers):
            interesting.append(line.strip())
    lines = interesting[-6:] if interesting else raw.splitlines()[-6:]
    compact = "\n".join(_truncate_middle(line, 360) for line in lines if line.strip())
    return compact or _truncate_middle(raw, 720)


def _compact_submit_failure_detail(exc: object) -> str:
    return _compact_submit_failure_text(str(exc))


def _truncate_middle(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    keep = max(1, (limit - 15) // 2)
    return f"{text[:keep]} ... [truncated] ... {text[-keep:]}"


def _format_submit_not_started_error(
    job: RemoteJob,
    exc: object,
    *,
    cleanup_detail: str | None,
) -> str:
    cleanup = (
        f"Remote run dir cleanup warning: {cleanup_detail}"
        if cleanup_detail
        else "Best-effort remote run dir cleanup was issued."
    )
    return "\n".join([
        f"JOB NOT STARTED: remote permuter submit failed for {job.job_id}.",
        "Local job metadata was rolled back; no live tmux session was confirmed.",
        cleanup,
        f"Remote run dir: {job.remote_run_dir}",
        "It is safe to retry the submit after the transient remote error clears.",
        "Failure detail:",
        _compact_submit_failure_detail(exc),
    ])


def _remote_sh(script: str) -> str:
    """Run a POSIX script through sh even if the login shell is fish/zsh."""
    return f"sh -lc {shlex.quote(script)}"


def _remote_doctor_script(
    target: RemoteTarget,
    scorer_info: ScorerCommandInfo | None = None,
    objdump_info: ObjdumpCommandInfo | None = None,
    require_remote_scorer_target: bool = True,
) -> str:
    melee_root = shlex.quote(target.remote_melee_root)
    perm_root = shlex.quote(target.remote_perm_root)
    lines = [
        "set +e",
        "emit() { printf '%s\\t%s\\t%s\\n' \"$1\" \"$2\" \"$3\"; }",
        f"melee_root={melee_root}",
        f"perm_root={perm_root}",
        "command -v sh >/dev/null 2>&1 && emit remote-sh ok sh || emit remote-sh fail 'sh missing'",
        "command -v rsync >/dev/null 2>&1 && emit remote-rsync ok \"$(command -v rsync)\" || emit remote-rsync fail 'rsync missing'",
        "command -v tmux >/dev/null 2>&1 && emit remote-tmux ok \"$(command -v tmux)\" || emit remote-tmux fail 'tmux missing'",
        'if command -v python3.11 >/dev/null 2>&1; then doctor_py="$(command -v python3.11)"; '
        'elif command -v python3 >/dev/null 2>&1 && python3 - <<\'PY\' >/dev/null 2>&1\n'
        "import sys\n"
        "raise SystemExit(0 if sys.version_info >= (3, 11) else 1)\n"
        "PY\n"
        'then doctor_py="$(command -v python3)"; else doctor_py=""; fi',
        'test -n "$doctor_py" && emit remote-python3 ok "$doctor_py" || emit remote-python3 fail "python >=3.11 missing"',
        'test -d "$melee_root" && emit remote-melee-root ok "$melee_root" || emit remote-melee-root fail "$melee_root missing"',
        'test -d "$perm_root" && emit remote-perm-root ok "$perm_root" || emit remote-perm-root fail "$perm_root missing"',
        'test -x "$perm_root/permuter.py" && emit remote-permuter-py ok "$perm_root/permuter.py" || emit remote-permuter-py fail "$perm_root/permuter.py missing or not executable"',
        'test -f "$melee_root/build/compilers/GC/1.2.5n/mwcceppc_debug.exe" && emit remote-mwcc ok "$melee_root/build/compilers/GC/1.2.5n/mwcceppc_debug.exe" || emit remote-mwcc fail "$melee_root/build/compilers/GC/1.2.5n/mwcceppc_debug.exe missing"',
        'test -x "$melee_root/tools/mwcc_debug/bin/wibo" && emit remote-wibo ok "$melee_root/tools/mwcc_debug/bin/wibo" || emit remote-wibo fail "$melee_root/tools/mwcc_debug/bin/wibo missing or not executable"',
        'if test -x "$melee_root/tools/melee-agent/.venv/bin/melee-agent"; then emit remote-melee-agent ok "$melee_root/tools/melee-agent/.venv/bin/melee-agent"; elif command -v melee-agent >/dev/null 2>&1; then emit remote-melee-agent ok "$(command -v melee-agent)"; elif test -x "$HOME/.local/bin/melee-agent"; then emit remote-melee-agent ok "$HOME/.local/bin/melee-agent"; else emit remote-melee-agent fail "melee-agent missing"; fi',
        'if test -n "$doctor_py"; then "$doctor_py" - <<\'PY\' >/tmp/melee-remote-doctor-python.$$ 2>&1\nimport toml\nprint("toml ok")\nPY\nrc=$?; out=$(cat /tmp/melee-remote-doctor-python.$$); rm -f /tmp/melee-remote-doctor-python.$$; test "$rc" -eq 0 && emit remote-python3-toml ok "$out" || emit remote-python3-toml fail "$out"; else emit remote-python3-toml fail "python >=3.11 missing"; fi',
    ]
    if objdump_info is not None:
        lines.extend(_remote_objdump_doctor_lines(objdump_info))
    if scorer_info is not None:
        lines.extend(
            _remote_scorer_doctor_lines(
                scorer_info,
                require_target=require_remote_scorer_target,
            )
        )
    return "\n".join(lines)


def _remote_objdump_doctor_lines(objdump_info: ObjdumpCommandInfo) -> list[str]:
    return [
        f"objdump_command={shlex.quote(objdump_info.command)}",
        f"objdump_executable={shlex.quote(objdump_info.executable)}",
        f"objdump_probe={shlex.quote(objdump_info.target_path or '')}",
        'if test "${objdump_executable#/}" != "$objdump_executable"; then objdump_resolved="$objdump_executable"; elif test "$objdump_executable" = "melee-agent" && test -x "$melee_root/tools/melee-agent/.venv/bin/melee-agent"; then objdump_resolved="$melee_root/tools/melee-agent/.venv/bin/melee-agent"; elif command -v "$objdump_executable" >/dev/null 2>&1; then objdump_resolved="$(command -v "$objdump_executable")"; elif test "$objdump_executable" = "melee-agent" && test -x "$HOME/.local/bin/melee-agent"; then objdump_resolved="$HOME/.local/bin/melee-agent"; else objdump_resolved=""; fi',
        'objdump_run_command="$objdump_command"; if test "$objdump_executable" = "melee-agent" && test -n "$objdump_resolved"; then objdump_run_command="$objdump_resolved${objdump_command#melee-agent}"; fi',
        'if test -n "$objdump_resolved" && test -x "$objdump_resolved"; then objdump_tmp=/tmp/melee-remote-doctor-objdump.$$; if printf "%s" "$objdump_command" | grep -q "dtk-objdump" && ! test -x "$melee_root/build/tools/dtk"; then emit remote-objdump-command fail "$melee_root/build/tools/dtk missing or not executable"; elif printf "%s" "$objdump_command" | grep -q "dtk-objdump" && test -n "$objdump_probe"; then MELEE_ROOT="$melee_root" sh -c "$objdump_run_command \\"$objdump_probe\\"" >"$objdump_tmp" 2>&1; objdump_rc=$?; objdump_out=$(head -40 "$objdump_tmp" | tr "\\n" "|" | sed "s/|$//"); test -n "$objdump_out" || objdump_out="<no stdout/stderr>"; objdump_detail="rc=$objdump_rc command=$objdump_run_command target=$objdump_probe stdout_stderr=$objdump_out"; if test "$objdump_rc" -eq 0; then emit remote-objdump-command ok "MELEE_ROOT=$melee_root $objdump_run_command $objdump_probe"; elif grep -q "object file not found" "$objdump_tmp"; then emit remote-objdump-command ok "MELEE_ROOT=$melee_root $objdump_run_command $objdump_probe (root ok; object missing)"; else emit remote-objdump-command fail "$objdump_detail"; fi; elif sh -c "$objdump_run_command --help" >"$objdump_tmp" 2>&1; then emit remote-objdump-command ok "$objdump_run_command --help"; else objdump_rc=$?; objdump_out=$(head -40 "$objdump_tmp" | tr "\\n" "|" | sed "s/|$//"); test -n "$objdump_out" || objdump_out="<no stdout/stderr>"; emit remote-objdump-command fail "rc=$objdump_rc command=$objdump_run_command --help stdout_stderr=$objdump_out"; fi; rm -f "$objdump_tmp"; else emit remote-objdump-command fail "$objdump_executable not found or not executable"; fi',
    ]


def _scorer_probe_schema(scorer_info: ScorerCommandInfo) -> tuple[str, str, str]:
    try:
        argv = shlex.split(scorer_info.command)
    except ValueError:
        return "score-simplify-order", "--strict-polarity", "strict-polarity scorer schema supported"
    command = "score-simplify-order"
    for index, arg in enumerate(argv[:-1]):
        if arg == "target" and index > 0 and argv[index - 1] == "debug":
            command = argv[index + 1]
            break
    if command == "score-force-phys":
        return command, "--breakdown", "force-phys scorer schema supported"
    return command, "--strict-polarity", "strict-polarity scorer schema supported"


def _remote_scorer_doctor_lines(
    scorer_info: ScorerCommandInfo,
    *,
    require_target: bool = True,
) -> list[str]:
    scorer_command, schema_flag, schema_ok_detail = _scorer_probe_schema(scorer_info)
    lines = [
        'if grep -q "class CustomCommandScorer" "$perm_root/src/scorer.py" 2>/dev/null && grep -q "scorer_settings" "$perm_root/src/main.py" 2>/dev/null; then emit remote-custom-scorer ok "$perm_root"; else emit remote-custom-scorer fail "CustomCommandScorer missing in remote decomp-permuter"; fi',
        f"scorer_executable={shlex.quote(scorer_info.executable)}",
        f"scorer_command={shlex.quote(scorer_command)}",
        f"scorer_schema_flag={shlex.quote(schema_flag)}",
        f"scorer_schema_ok_detail={shlex.quote(schema_ok_detail)}",
        'if test "${scorer_executable#/}" != "$scorer_executable"; then scorer_resolved="$scorer_executable"; elif test "$scorer_executable" = "melee-agent" && test -x "$melee_root/tools/melee-agent/.venv/bin/melee-agent"; then scorer_resolved="$melee_root/tools/melee-agent/.venv/bin/melee-agent"; elif command -v "$scorer_executable" >/dev/null 2>&1; then scorer_resolved="$(command -v "$scorer_executable")"; elif test "$scorer_executable" = "melee-agent" && test -x "$HOME/.local/bin/melee-agent"; then scorer_resolved="$HOME/.local/bin/melee-agent"; else scorer_resolved=""; fi',
        'if test -n "$scorer_resolved" && test -x "$scorer_resolved"; then scorer_tmp=/tmp/melee-remote-doctor-scorer.$$; (cd "$perm_root" && "$scorer_resolved" debug target "$scorer_command" --help) >"$scorer_tmp" 2>&1; scorer_rc=$?; scorer_out=$(head -40 "$scorer_tmp"); if test "$scorer_rc" -eq 0; then emit remote-scorer-command ok "$scorer_resolved debug target $scorer_command --help"; grep -q -- "$scorer_schema_flag" "$scorer_tmp" && emit remote-scorer-schema ok "$scorer_schema_ok_detail" || emit remote-scorer-schema fail "stale $scorer_command help; missing $scorer_schema_flag"; else emit remote-scorer-command fail "$scorer_out"; emit remote-scorer-schema fail "$scorer_command --help failed"; fi; rm -f "$scorer_tmp"; else emit remote-scorer-command fail "$scorer_executable not found or not executable"; emit remote-scorer-schema fail "$scorer_executable not found or not executable"; fi',
    ]
    if require_target and scorer_info.target_path is not None:
        lines.extend([
            f"scorer_target={shlex.quote(scorer_info.target_path)}",
            'test -f "$scorer_target" && emit remote-scorer-target ok "$scorer_target" || emit remote-scorer-target fail "$scorer_target missing on remote"',
        ])
    return lines


@contextmanager
def _staged_remote_perm_dir(
    local_perm_dir: Path,
    *,
    target: RemoteTarget | None = None,
    remote_perm_dir: str | None = None,
) -> Any:
    with tempfile.TemporaryDirectory(prefix="melee_remote_perm_") as td:
        staged = Path(td) / local_perm_dir.name
        shutil.copytree(
            local_perm_dir,
            staged,
            symlinks=True,
            ignore=shutil.ignore_patterns("remote-runs", "output-*"),
        )
        compile_sh = staged / "compile.sh"
        if compile_sh.exists():
            text = compile_sh.read_text()
            rewritten = _rewrite_compile_sh_for_remote(text)
            if rewritten != text:
                compile_sh.write_text(rewritten)
                compile_sh.chmod(0o755)
        settings_toml = staged / "settings.toml"
        if settings_toml.exists():
            text = settings_toml.read_text()
            rewritten = _rewrite_settings_toml_for_remote(
                text,
                target=target,
                remote_perm_dir=remote_perm_dir,
            )
            if rewritten != text:
                settings_toml.write_text(rewritten)
        for yaml_path in [*staged.glob("*.yaml"), *staged.glob("*.yml")]:
            text = yaml_path.read_text()
            rewritten = _rewrite_target_yaml_for_remote(
                text,
                target=target,
                remote_perm_dir=remote_perm_dir,
            )
            if rewritten != text:
                yaml_path.write_text(rewritten)
        yield staged


def _validate_remote_ready_perm_dir(local_perm_dir: Path) -> None:
    leaks = _find_local_path_leaks(local_perm_dir)
    if leaks:
        path, needle = leaks[0]
        raise RemoteJobError(
            f"local permuter dir is not remote-ready: {path} contains local-only path "
            f"{needle!r}; regenerate or fix it for the remote root"
        )


_MWCC_EXE_TOKEN_RE = re.compile(r"(?:^|/)mwcceppc(?:_debug)?\.exe$")


def _shell_word_spans(line: str) -> list[tuple[int, int, str]]:
    """Return shell words with source spans while respecting basic quoting."""
    spans: list[tuple[int, int, str]] = []
    index = 0
    while index < len(line):
        while index < len(line) and line[index].isspace():
            index += 1
        if index >= len(line):
            break
        start = index
        quote: str | None = None
        while index < len(line):
            char = line[index]
            if char == "\\" and quote != "'":
                index = min(index + 2, len(line))
                continue
            if char in {"'", '"'}:
                if quote is None:
                    quote = char
                elif quote == char:
                    quote = None
                index += 1
                continue
            if char.isspace() and quote is None:
                break
            index += 1
        raw = line[start:index]
        try:
            parsed = shlex.split(raw, posix=True)
        except ValueError:
            return []
        if len(parsed) != 1:
            return []
        spans.append((start, index, parsed[0]))
    return spans


def _host_wibo_fallback_condition(line: str) -> bool:
    """Return whether *line* is the generated absolute baked-wibo branch."""
    try:
        words = shlex.split(line.strip(), posix=True)
    except ValueError:
        return False
    return (
        len(words) >= 7
        and words[:3] == ["elif", "[[", "-f"]
        and Path(words[3]).is_absolute()
        and words[4:6] == ["&&", "-x"]
        and words[6] == words[3]
    )


def _remote_compile_command(line: str, *, wibo: str) -> str | None:
    """Replace a local compiler prefix while preserving the original suffix."""
    for _start, end, word in _shell_word_spans(line):
        if "MWCC_DEBUG_COMPILER" in word:
            return None
        if _MWCC_EXE_TOKEN_RE.search(word):
            indent = line[: len(line) - len(line.lstrip())]
            compiler = (
                '"${MWCC_DEBUG_COMPILER:-$MELEE_ROOT/build/compilers/GC/'
                '1.2.5n/mwcceppc_debug.exe}"'
            )
            return f"{indent}{wibo} {compiler}{line[end:]}"
    return None


def _rewrite_compile_sh_for_remote(text: str) -> str:
    out: list[str] = []
    has_wibo_preflight = 'WIBO=""' in text
    skip_baked_assignment = False
    for line in text.splitlines():
        if skip_baked_assignment:
            skip_baked_assignment = False
            if line.strip().startswith('WIBO="/'):
                continue
        # A setup wrapper may carry the generator host's absolute custom-wibo
        # fallback.  The remote MELEE_ROOT/current-checkout candidates precede
        # it, so omit only that host-local branch from the staged copy.
        if _host_wibo_fallback_condition(line):
            skip_baked_assignment = True
            continue
        stripped = line.strip()
        try:
            shell_words = shlex.split(stripped, posix=True)
        except ValueError:
            shell_words = []
        if (
            len(shell_words) >= 2
            and shell_words[0] == "cd"
            and Path(shell_words[1]).is_absolute()
        ):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(indent + 'cd "${MELEE_ROOT:?MELEE_ROOT must be set}"')
            continue

        if "mwcceppc" in line and ".exe" in line:
            wibo = (
                '"$WIBO"'
                if has_wibo_preflight
                else '"${MWCC_DEBUG_WIBO:-$MELEE_ROOT/tools/mwcc_debug/bin/wibo}"'
            )
            rewritten = _remote_compile_command(line, wibo=wibo)
            if rewritten is not None:
                out.append(rewritten)
                continue

        out.append(line)

    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + suffix


_OBJDUMP_SETTING_RE = re.compile(r'^(\s*objdump_command\s*=\s*)".*"\s*$')


def _remote_dtk_objdump_command(target: RemoteTarget) -> str:
    argv = [
        *shlex.split(DEFAULT_OBJDUMP_COMMAND),
        "--melee-root",
        target.remote_melee_root,
        "--object-root",
        target.remote_perm_root,
    ]
    return shlex.join(argv)


def _remote_objdump_command(command: str, target: RemoteTarget | None) -> str:
    if target is None:
        return command
    try:
        argv = shlex.split(command)
    except ValueError:
        return command
    if (
        len(argv) >= 4
        and argv[:4] == ["melee-agent", "debug", "target", "dtk-objdump"]
        and "--melee-root" not in argv
    ):
        return _remote_dtk_objdump_command(target)
    return command


def _remote_perm_path(
    path: str,
    target: RemoteTarget | None,
    *,
    remote_perm_dir: str | None = None,
) -> str:
    if target is None:
        return path
    if not path:
        return path
    if remote_perm_dir is not None:
        remote_perm_dir = remote_perm_dir.rstrip("/")
        if path == remote_perm_dir or path.startswith(remote_perm_dir + "/"):
            return path
        function = posixpath.basename(remote_perm_dir)
        parts = [part for part in path.split("/") if part and part != "."]
        if "nonmatchings" in parts:
            index = parts.index("nonmatchings")
            if index + 1 < len(parts) and parts[index + 1] == function:
                suffix = parts[index + 2:]
                return (
                    posixpath.join(remote_perm_dir, *suffix)
                    if suffix
                    else remote_perm_dir
                )
        elif not path.startswith("/"):
            return posixpath.normpath(posixpath.join(remote_perm_dir, path))
    if path.startswith(target.remote_perm_root + "/"):
        return path
    if path.startswith("/"):
        parts = Path(path).parts
        if "nonmatchings" in parts:
            index = parts.index("nonmatchings")
            rel = posixpath.join(*parts[index:])
            return posixpath.join(target.remote_perm_root, rel)
        return path
    return posixpath.normpath(posixpath.join(target.remote_perm_root, path))


def _rewrite_scorer_command_for_remote(
    command: str,
    target: RemoteTarget | None,
    *,
    remote_perm_dir: str | None = None,
) -> str:
    if target is None:
        return command
    try:
        argv = shlex.split(command)
    except ValueError:
        return command
    changed = False
    for index, arg in enumerate(argv):
        if arg == "--target" and index + 1 < len(argv):
            remote_path = _remote_perm_path(
                argv[index + 1],
                target,
                remote_perm_dir=remote_perm_dir,
            )
            if remote_path != argv[index + 1]:
                argv[index + 1] = remote_path
                changed = True
            break
        if arg.startswith("--target="):
            value = arg.split("=", 1)[1]
            remote_path = _remote_perm_path(
                value,
                target,
                remote_perm_dir=remote_perm_dir,
            )
            if remote_path != value:
                argv[index] = f"--target={remote_path}"
                changed = True
            break
    return shlex.join(argv) if changed else command


def _rewrite_target_yaml_for_remote(
    text: str,
    *,
    target: RemoteTarget | None = None,
    remote_perm_dir: str | None = None,
) -> str:
    if target is None:
        return text
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if stripped.startswith("baseline_dump:"):
            value = stripped.split(":", 1)[1].strip()
            quote = ""
            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value[0] in {"'", '"'}
            ):
                quote = value[0]
                value = value[1:-1]
            remote_path = _remote_perm_path(
                value,
                target,
                remote_perm_dir=remote_perm_dir,
            )
            rendered = f"{quote}{remote_path}{quote}" if quote else remote_path
            out.append(f"{indent}baseline_dump: {rendered}")
        else:
            out.append(line)
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + suffix


def _rewrite_settings_toml_for_remote(
    text: str,
    *,
    target: RemoteTarget | None = None,
    remote_perm_dir: str | None = None,
) -> str:
    """Ensure remote jobs use a project-provided scorer disassembler."""
    lines = text.splitlines()
    out: list[str] = []
    found = False
    command = _remote_objdump_command(DEFAULT_OBJDUMP_COMMAND, target)
    in_scorer = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_scorer = stripped == "[scorer]"
        match = _OBJDUMP_SETTING_RE.match(line)
        if match is not None:
            out.append(f'{match.group(1)}"{command}"')
            found = True
        elif (
            in_scorer
            and "=" in stripped
            and stripped.split("=", 1)[0].strip() == "command"
        ):
            prefix, sep, raw_value = line.partition("=")
            value = raw_value.strip()
            if (
                sep
                and len(value) >= 2
                and value[0] == value[-1]
                and value[0] in {"'", '"'}
            ):
                scorer_command = value[1:-1]
                rewritten = _rewrite_scorer_command_for_remote(
                    scorer_command,
                    target,
                    remote_perm_dir=remote_perm_dir,
                )
                out.append(f'{prefix}{sep} "{rewritten}"')
            else:
                out.append(line)
        else:
            out.append(line)
    if not found:
        setting = f'objdump_command = "{command}"'
        section_index = next(
            (idx for idx, line in enumerate(out) if line.lstrip().startswith("[")),
            None,
        )
        if section_index is None:
            if out and out[-1].strip():
                out.append("")
            out.append(setting)
        else:
            insert = [setting, ""]
            out[section_index:section_index] = insert
    suffix = "\n" if text.endswith("\n") or not text else ""
    return "\n".join(out) + suffix


def _compile_runner_check(path: Path) -> DoctorCheck | None:
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except UnicodeDecodeError as exc:
        return DoctorCheck("local compile runner", False, str(exc))
    rewritten = _rewrite_compile_sh_for_remote(text)
    if rewritten != text:
        if "MWCC_DEBUG_WIBO" in rewritten and "mwcceppc_debug.exe" in rewritten:
            return DoctorCheck(
                "local compile runner",
                True,
                "compile.sh will be staged with remote Linux wibo",
            )
        if "wine " in rewritten or "\twine " in rewritten:
            return DoctorCheck(
                "local compile runner",
                False,
                "compile.sh still requires wine after remote rewrite",
            )
    return None


def _find_local_path_leaks(
    local_perm_dir: Path,
    *,
    target: RemoteTarget | None = None,
) -> list[tuple[Path, str]]:
    forbidden = ["/Users/"]
    local_root = _infer_local_root()
    if local_root is not None:
        forbidden.append(str(local_root))
        forbidden.append(str(local_root.resolve()))

    leaks: list[tuple[Path, str]] = []
    names = ["compile.sh", "settings.toml"]
    names.extend(path.name for path in sorted(local_perm_dir.glob("*.yaml")))
    names.extend(path.name for path in sorted(local_perm_dir.glob("*.yml")))
    for name in dict.fromkeys(names):
        path = local_perm_dir / name
        if not path.exists():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError as exc:
            raise RemoteJobError(f"Unable to inspect remote permuter file {path}: {exc}") from exc
        if target is not None:
            if name == "compile.sh":
                text = _rewrite_compile_sh_for_remote(text)
            elif name == "settings.toml":
                text = _rewrite_settings_toml_for_remote(text, target=target)
            elif name.endswith((".yaml", ".yml")):
                text = _rewrite_target_yaml_for_remote(text, target=target)
        for needle in dict.fromkeys(forbidden):
            if needle and needle in text:
                leaks.append((path, needle))
                break
    return leaks


def _doctor_local_perm_dir(
    local_perm_dir: Path,
    *,
    target: RemoteTarget | None = None,
) -> list[DoctorCheck]:
    checks = [
        DoctorCheck("local perm dir", local_perm_dir.is_dir(), str(local_perm_dir)),
    ]
    if not local_perm_dir.is_dir():
        return checks

    for name in ("compile.sh", "settings.toml"):
        path = local_perm_dir / name
        checks.append(DoctorCheck(f"local {name}", path.exists(), str(path)))
        if name == "compile.sh":
            runner_check = _compile_runner_check(path)
            if runner_check is not None:
                checks.append(runner_check)

    try:
        leaks = _find_local_path_leaks(local_perm_dir, target=target)
    except RemoteJobError as exc:
        checks.append(DoctorCheck("local path leaks", False, str(exc)))
        return checks
    if leaks:
        detail = "; ".join(f"{path}: {needle}" for path, needle in leaks[:3])
        if len(leaks) > 3:
            detail += f"; +{len(leaks) - 3} more"
        checks.append(DoctorCheck("local path leaks", False, detail))
    else:
        checks.append(DoctorCheck("local path leaks", True, "no local-only paths found"))
    return checks


def _doctor_local_scorer(
    local_perm_dir: Path,
    *,
    target: RemoteTarget | None = None,
) -> tuple[list[DoctorCheck], ScorerCommandInfo | None]:
    settings_path = local_perm_dir / "settings.toml"
    if not settings_path.exists():
        return [], None
    try:
        settings = tomllib.loads(settings_path.read_text())
    except tomllib.TOMLDecodeError as exc:
        return [DoctorCheck("local settings.toml parse", False, str(exc))], None

    scorer = settings.get("scorer")
    if scorer is None:
        return [], None
    if not isinstance(scorer, dict):
        return [DoctorCheck("local custom scorer", False, "[scorer] must be a TOML table")], None

    command = scorer.get("command")
    if not isinstance(command, str) or not command.strip():
        return [DoctorCheck("local custom scorer", False, "[scorer].command missing")], None

    checks: list[DoctorCheck] = [DoctorCheck("local custom scorer", True, command)]
    try:
        info = _parse_scorer_command(command)
    except ValueError as exc:
        return [*checks, DoctorCheck("local custom scorer command", False, str(exc))], None

    if info.target_path is not None:
        target_path = Path(info.target_path)
        if not target_path.is_absolute():
            if target is None:
                checks.append(DoctorCheck(
                    "local scorer target path",
                    False,
                    f"relative --target {info.target_path!r}",
                ))
            else:
                remote_path = _remote_perm_path(info.target_path, target)
                checks.append(DoctorCheck(
                    "local scorer target path",
                    True,
                    remote_path,
                ))
                info = ScorerCommandInfo(
                    command=info.command,
                    executable=info.executable,
                    target_path=remote_path,
                )
        else:
            remote_path = _remote_perm_path(info.target_path, target)
            checks.append(DoctorCheck("local scorer target path", True, remote_path))
            info = ScorerCommandInfo(
                command=info.command,
                executable=info.executable,
                target_path=remote_path,
            )

    return checks, info


def _doctor_local_objdump(
    local_perm_dir: Path,
    *,
    target: RemoteTarget | None = None,
) -> tuple[list[DoctorCheck], ObjdumpCommandInfo | None]:
    settings_path = local_perm_dir / "settings.toml"
    if not settings_path.exists():
        return [], None
    try:
        settings = tomllib.loads(settings_path.read_text())
    except tomllib.TOMLDecodeError:
        return [], None

    command = settings.get("objdump_command")
    if command is None:
        return [], None
    if not isinstance(command, str) or not command.strip():
        return [DoctorCheck("local objdump command", False, "objdump_command missing")], None
    if target is not None:
        command = _remote_objdump_command(DEFAULT_OBJDUMP_COMMAND, target)
    else:
        command = _remote_objdump_command(command, target)
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return [DoctorCheck("local objdump command", False, str(exc))], None
    if not argv:
        return [DoctorCheck("local objdump command", False, "empty objdump_command")], None
    target_path = None
    if target is not None:
        target_path = f"{target.remote_perm_root}/nonmatchings/{local_perm_dir.name}/target.o"
    return [
        DoctorCheck("local objdump command", True, command),
    ], ObjdumpCommandInfo(command=command, executable=argv[0], target_path=target_path)


def _parse_scorer_command(command: str) -> ScorerCommandInfo:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ValueError(f"unable to parse scorer command: {exc}") from exc
    if not argv:
        raise ValueError("empty scorer command")

    target_path: str | None = None
    for index, arg in enumerate(argv):
        if arg == "--target" and index + 1 < len(argv):
            target_path = argv[index + 1]
            break
        if arg.startswith("--target="):
            target_path = arg.split("=", 1)[1]
            break

    return ScorerCommandInfo(
        command=command,
        executable=argv[0],
        target_path=target_path,
    )


def _looks_persistent_root(path: str) -> bool:
    return bool(path) and not path.startswith("/tmp/codex-remote-perm-")


def _preflight_failure_detail(report: DoctorReport) -> str:
    failed = [
        f"{check.name}: {check.detail}"
        for check in report.checks
        if check.required and not check.ok
    ]
    detail = "; ".join(failed[:5])
    if len(failed) > 5:
        detail += f"; +{len(failed) - 5} more"
    return detail


def _preflight_can_be_repaired(report: DoctorReport) -> bool:
    repairable = {
        "remote melee root",
        "remote permuter root",
        "remote permuter.py",
        "remote MWCC compiler",
        "remote Linux wibo",
        "remote melee-agent",
        "remote python3 toml",
        "remote custom scorer",
        "remote scorer command",
        "remote scorer schema",
    }
    return any(
        check.required and not check.ok and check.name in repairable
        for check in report.checks
    )


def _resolve_auto_repair_melee_root(local_melee_root: Path | None) -> Path:
    if local_melee_root is not None:
        return local_melee_root
    inferred = _infer_local_root()
    if inferred is None:
        raise RemoteJobError("unable to infer local Melee root for remote auto-repair")
    return inferred


def _resolve_auto_repair_perm_root(
    local_perm_root: Path | None,
    local_perm_dir: Path,
) -> Path:
    if local_perm_root is not None:
        return local_perm_root
    env_root = os.environ.get("MELEE_DECOMP_PERMUTER_ROOT")
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root).expanduser())
    if local_perm_dir.parent.name == "nonmatchings":
        candidates.append(local_perm_dir.parent.parent)
    candidates.extend([
        Path("~/code/decomp-permuter").expanduser(),
        Path("~/code/melee-harness/decomp-permuter").expanduser(),
    ])
    for candidate in candidates:
        if _looks_like_decomp_permuter_root(candidate):
            return candidate
    raise RemoteJobError(
        "unable to infer decomp-permuter checkout for remote auto-repair; "
        "set MELEE_DECOMP_PERMUTER_ROOT or run remote doctor --repair"
    )


def _looks_like_decomp_permuter_root(path: Path) -> bool:
    return (path / "permuter.py").is_file() and (path / "src").is_dir()


def _parse_remote_doctor_output(
    stdout: str,
    *,
    expect_scorer: bool = False,
    expect_remote_scorer_target: bool = False,
    expect_objdump: bool = False,
) -> list[DoctorCheck]:
    labels = {
        "remote-sh": "remote sh",
        "remote-rsync": "remote rsync",
        "remote-tmux": "remote tmux",
        "remote-python3": "remote python3",
        "remote-melee-root": "remote melee root",
        "remote-perm-root": "remote permuter root",
        "remote-permuter-py": "remote permuter.py",
        "remote-mwcc": "remote MWCC compiler",
        "remote-wibo": "remote Linux wibo",
        "remote-melee-agent": "remote melee-agent",
        "remote-python3-toml": "remote python3 toml",
    }
    scorer_labels = {
        "remote-custom-scorer": "remote custom scorer",
        "remote-scorer-command": "remote scorer command",
        "remote-scorer-schema": "remote scorer schema",
    }
    scorer_target_labels = {
        "remote-scorer-target": "remote scorer target",
    }
    objdump_labels = {
        "remote-objdump-command": "remote objdump command",
    }
    known_labels = {
        **labels,
        **scorer_labels,
        **scorer_target_labels,
        **objdump_labels,
    }
    checks: list[DoctorCheck] = []
    seen: set[str] = set()
    last_check_idx: int | None = None
    for line in stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            if last_check_idx is not None:
                previous = checks[last_check_idx]
                detail = f"{previous.detail}\n{line}" if previous.detail else line
                checks[last_check_idx] = DoctorCheck(
                    previous.name,
                    previous.ok,
                    detail,
                    previous.required,
                )
            continue
        key, status, detail = parts
        if key not in known_labels:
            last_check_idx = None
            continue
        seen.add(key)
        checks.append(DoctorCheck(known_labels[key], status == "ok", detail))
        last_check_idx = len(checks) - 1
    expected_labels = dict(labels)
    if expect_scorer:
        expected_labels.update(scorer_labels)
    if expect_remote_scorer_target:
        expected_labels.update(scorer_target_labels)
    if expect_objdump:
        expected_labels.update(objdump_labels)
    for key, label in expected_labels.items():
        if key not in seen:
            checks.append(DoctorCheck(label, False, "no result returned"))
    return checks


def _infer_local_root() -> Path | None:
    cwd = Path.cwd()
    candidates = [cwd, *cwd.parents]
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return cwd


def _remove_job_metadata_best_effort(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _strip_remote_root(value: str) -> str:
    stripped = value.rstrip("/")
    return stripped or "/"


def _expect_str(config_path: Path, target: str, values: dict[str, Any], key: str) -> str:
    value = values[key]
    if not isinstance(value, str) or not value:
        raise RemoteConfigError(f"Target {target!r} in {config_path} has invalid string value for {key!r}.")
    return value


def _expect_optional_str(values: dict[str, Any], key: str, default: str) -> str:
    value = values.get(key, default)
    if not isinstance(value, str) or not value:
        raise RemoteConfigError(f"Invalid string value for {key!r}.")
    return value


def _coerce_threads(config_path: Path, target: str, value: object) -> int:
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RemoteConfigError(f"Target {target!r} in {config_path} has invalid positive integer value for 'threads'.")
    return value


# ── remote ps / dashboard ────────────────────────────────────────────────────

@dataclass(frozen=True)
class RemotePsEntry:
    """Single row in the ``remote ps`` dashboard."""
    target: str
    session_name: str
    job_id: str
    function: str
    best_score: str | None
    iterations: str
    age: str
    verdict: str
    plateau_flag: bool = False
    match_flag: bool = False


def _parse_tmux_session_name(session_name: str, prefix: str) -> str | None:
    """Extract job_id from a tmux session name like ``melee-perm-fn_TARGET-20260608-120000``."""
    if not session_name.startswith(prefix):
        return None
    return session_name[len(prefix):]


def _parse_ps_log_tail(text: str) -> tuple[str | None, str, str, bool, bool]:
    """Quick-parse the last ~8KB of a permuter log for PS dashboard fields."""
    summary = parse_permuter_log_summary(text[-8192:] if len(text) > 8192 else text)
    best = None
    if summary.global_best_score is not None:
        best = format_score(summary.global_best_score)
    iters = str(summary.latest_iteration) if summary.latest_iteration is not None else (
        str(summary.iteration_count) if summary.iteration_count else "-"
    )
    verdict = summary.verdict
    plateau = verdict == "plateau"
    match = summary.match_found
    return best, iters, verdict, plateau, match


def remote_ps(
    targets: Mapping[str, RemoteTarget],
    runner: Callable[..., CommandResult] = run_command,
    timeout: float = 15.0,
) -> list[RemotePsEntry]:
    """Collect a dashboard of active remote permuter sessions across all targets.

    Probes targets in parallel, then reads logs in parallel within each target.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    entries: list[RemotePsEntry] = []

    def _probe_target(target: RemoteTarget) -> list[RemotePsEntry]:
        target_entries: list[RemotePsEntry] = []
        # One SSH call to list all tmux sessions matching the prefix
        result = runner(
            ["ssh", target.ssh, _remote_sh(
                f"tmux list-sessions -F '#{{session_name}}|#{{session_created}}' "
                f"2>/dev/null | grep '^{target.session_prefix}' || true"
            )],
            check=False,
            timeout=timeout,
        )
        if result.returncode not in (0, 1) or not result.stdout.strip():
            return target_entries

        # Collect session info for all active sessions
        sessions: list[dict[str, str]] = []
        for line in result.stdout.strip().splitlines():
            if "|" not in line:
                continue
            session_name, created_raw = line.split("|", 1)
            job_id = _parse_tmux_session_name(session_name, target.session_prefix + "-")
            if job_id is None:
                continue
            try:
                created_ts = int(created_raw)
                age_seconds = int(datetime.now().timestamp()) - created_ts
                hours = age_seconds // 3600
                minutes = (age_seconds % 3600) // 60
                age = f"{hours}h{minutes:02d}m" if hours > 0 else f"{minutes}m"
            except (ValueError, OSError):
                age = "?"
            sessions.append({"job_id": job_id, "session_name": session_name, "age": age})

        if not sessions:
            return target_entries

        # Read logs in parallel for all active sessions on this target
        log_results: dict[str, tuple[str, str, str, bool, bool]] = {}

        def _read_log(session: dict[str, str]) -> None:
            job_id = session["job_id"]
            run_dir = f"{target.remote_perm_root}/remote-runs/{job_id}"
            log_result = runner(
                ["ssh", target.ssh, _remote_sh(
                    f"tail -c 8192 {shlex.quote(run_dir)}/permuter.log 2>/dev/null || true"
                )],
                check=False,
                timeout=timeout,
            )
            log_results[job_id] = _parse_ps_log_tail(log_result.stdout)

        with ThreadPoolExecutor(max_workers=min(len(sessions), 16)) as ex:
            futures = {ex.submit(_read_log, s): s for s in sessions}
            for future in as_completed(futures):
                future.result()

        for session in sessions:
            job_id = session["job_id"]
            best_score, iterations, verdict, plateau, match = log_results.get(
                job_id, (None, "-", "unknown", False, False)
            )
            function = "-".join(job_id.split("-")[:-2]) if job_id.count("-") >= 2 else job_id
            target_entries.append(RemotePsEntry(
                target=target.name,
                session_name=session["session_name"],
                job_id=job_id,
                function=function,
                best_score=best_score,
                iterations=iterations,
                age=session["age"],
                verdict=verdict,
                plateau_flag=plateau,
                match_flag=match,
            ))
        return target_entries

    # Probe targets in parallel
    target_list = sorted(targets.values(), key=lambda t: t.name)
    with ThreadPoolExecutor(max_workers=min(len(target_list), 8)) as ex:
        futures = {ex.submit(_probe_target, t): t.name for t in target_list}
        for future in as_completed(futures):
            entries.extend(future.result())

    return entries


# ── remote reap (auto-stop byte-matched / plateaued) ─────────────────────────

@dataclass(frozen=True)
class ReapAction:
    job_id: str
    function: str
    target: str
    action: str  # "stopped" | "would-stop" | "skipped"
    reason: str


def _job_is_done(log_status: RemoteLogStatus, idle_hours_threshold: float = 6.0) -> tuple[bool, str]:
    """Return (should_stop, reason) for a single job based on its log status."""
    if log_status.match_found:
        return True, "byte-matched (score 0)"
    if log_status.verdict == "plateau":
        now = utcnow()
        if log_status.modified_at is not None:
            idle_h = (now - log_status.modified_at).total_seconds() / 3600.0
            if idle_h >= idle_hours_threshold:
                return True, f"plateaued, log idle {idle_h:.1f}h"
    if log_status.verdict == "ceiling":
        now = utcnow()
        if log_status.modified_at is not None:
            idle_h = (now - log_status.modified_at).total_seconds() / 3600.0
            if idle_h >= idle_hours_threshold * 2:
                return True, f"ceiling (no improvement), log idle {idle_h:.1f}h"
    return False, ""


def _batch_active_sessions(
    targets: Mapping[str, RemoteTarget],
    jobs: list[RemoteJob],
    *,
    runner: Callable[..., CommandResult] = run_command,
    timeout: float = 30.0,
) -> dict[str, bool]:
    """Probe which jobs are active using one SSH call per target.

    Returns dict mapping job_id -> is_active. Much faster than per-job probing
    when there are many dead jobs.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Group jobs by target
    jobs_by_target: dict[str, list[RemoteJob]] = {}
    for job in jobs:
        jobs_by_target.setdefault(job.target, []).append(job)

    active: dict[str, bool] = {}

    def _probe_target(target_name: str) -> None:
        target = targets.get(target_name)
        if target is None:
            for job in jobs_by_target[target_name]:
                active[job.job_id] = False
            return
        # One SSH call to list all tmux sessions matching the prefix
        result = runner(
            ["ssh", target.ssh, _remote_sh(
                f"tmux list-sessions -F '#{{session_name}}' "
                f"2>/dev/null | grep '^{target.session_prefix}' || true"
            )],
            check=False,
            timeout=timeout,
        )
        active_sessions: set[str] = set()
        if result.stdout.strip():
            for name in result.stdout.strip().splitlines():
                active_sessions.add(name.strip())
        for job in jobs_by_target[target_name]:
            active[job.job_id] = job.tmux_session in active_sessions

    # Probe targets in parallel (typically only 2-3 coders)
    with ThreadPoolExecutor(max_workers=min(len(jobs_by_target), 8)) as ex:
        futures = {ex.submit(_probe_target, t): t for t in jobs_by_target}
        for future in as_completed(futures):
            future.result()  # propagate any exception

    return active


def remote_reap(
    targets: Mapping[str, RemoteTarget],
    jobs: list[RemoteJob],
    *,
    runner: Callable[..., CommandResult] = run_command,
    timeout: float = 30.0,
    dry_run: bool = True,
    function_filter: str | None = None,
    job_id_filter: str | None = None,
    idle_hours_threshold: float = 6.0,
) -> list[ReapAction]:
    """Stop remote permuter jobs that are byte-matched or plateaued.

    Probes active sessions in batch (one SSH call per target), then
    reads logs in parallel only for active jobs. Returns a list of
    actions taken (or that would be taken in dry-run mode).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Filter jobs
    candidates: list[RemoteJob] = []
    for job in jobs:
        if function_filter is not None and job.function != function_filter:
            continue
        if job_id_filter is not None and job.job_id != job_id_filter:
            continue
        candidates.append(job)

    if not candidates:
        return []

    # Phase 1: batch-probe active sessions (one SSH call per target)
    active_map = _batch_active_sessions(
        targets, candidates, runner=runner, timeout=timeout,
    )

    # Separate active from dead
    active_jobs: list[RemoteJob] = []
    actions: list[ReapAction] = []
    for job in candidates:
        if active_map.get(job.job_id, False):
            active_jobs.append(job)
        else:
            actions.append(ReapAction(
                job_id=job.job_id,
                function=job.function,
                target=job.target,
                action="skipped",
                reason="already stopped",
            ))

    if not active_jobs:
        return actions

    # Phase 2: probe logs in parallel for active jobs
    reap_results: dict[str, ReapAction] = {}

    def _probe_job(job: RemoteJob) -> None:
        log_status = remote_log_status(job, runner=runner, timeout=timeout)
        should_stop, reason = _job_is_done(log_status, idle_hours_threshold)
        if should_stop:
            if dry_run:
                reap_results[job.job_id] = ReapAction(
                    job_id=job.job_id,
                    function=job.function,
                    target=job.target,
                    action="would-stop",
                    reason=reason,
                )
            else:
                stop_result = stop_job(job, runner=runner)
                if stop_result.returncode == 0:
                    reap_results[job.job_id] = ReapAction(
                        job_id=job.job_id,
                        function=job.function,
                        target=job.target,
                        action="stopped",
                        reason=reason,
                    )
                else:
                    reap_results[job.job_id] = ReapAction(
                        job_id=job.job_id,
                        function=job.function,
                        target=job.target,
                        action="skipped",
                        reason=f"stop failed: {stop_result.stderr.strip() or stop_result.stdout.strip()}",
                    )
        else:
            reap_results[job.job_id] = ReapAction(
                job_id=job.job_id,
                function=job.function,
                target=job.target,
                action="skipped",
                reason=f"still descending (verdict={log_status.verdict})",
            )

    with ThreadPoolExecutor(max_workers=min(len(active_jobs), 16)) as ex:
        futures = {ex.submit(_probe_job, job): job for job in active_jobs}
        for future in as_completed(futures):
            future.result()

    # Append in original order
    for job in candidates:
        if job.job_id in reap_results:
            actions.append(reap_results[job.job_id])

    return actions


# ── remote prune (delete stale remote-runs disk dirs) ────────────────────────

@dataclass(frozen=True)
class PruneAction:
    target: str
    remote_dir: str
    action: str  # "deleted" | "would-delete" | "skipped"
    reason: str


def remote_prune(
    targets: Mapping[str, RemoteTarget],
    *,
    runner: Callable[..., CommandResult] = run_command,
    timeout: float = 30.0,
    dry_run: bool = True,
    older_than_days: int = 14,
    target_filter: str | None = None,
) -> list[PruneAction]:
    """Delete stale remote-runs directories on remote coders.

    NEVER deletes directories whose job is currently active in tmux.
    Only deletes dirs older than ``older_than_days``.
    """
    actions: list[PruneAction] = []
    now = utcnow()

    for target in sorted(targets.values(), key=lambda t: t.name):
        if target_filter is not None and target.name != target_filter:
            continue

        # Get active tmux session names
        active_result = runner(
            ["ssh", target.ssh, _remote_sh(
                f"tmux list-sessions -F '#{{session_name}}' "
                f"2>/dev/null | grep '^{target.session_prefix}' || true"
            )],
            check=False,
            timeout=timeout,
        )
        active_sessions: set[str] = set()
        if active_result.stdout.strip():
            for name in active_result.stdout.strip().splitlines():
                active_sessions.add(name.strip())

        # List remote-runs directories
        runs_dir = f"{target.remote_perm_root}/remote-runs"
        list_result = runner(
            ["ssh", target.ssh, _remote_sh(
                f"if [ -d {shlex.quote(runs_dir)} ]; then "
                f"find {shlex.quote(runs_dir)} -maxdepth 1 -type d "
                f"-printf '%f|%T@\\n' 2>/dev/null || "
                f"ls -1d {shlex.quote(runs_dir)}/*/ 2>/dev/null | "
                f"while read d; do "
                f"bn=$(basename \"$d\"); "
                f"ts=$(stat -c %Y \"$d\" 2>/dev/null || stat -f %m \"$d\" 2>/dev/null || echo 0); "
                f"printf '%s|%s\\n' \"$bn\" \"$ts\"; "
                f"done; "
                f"fi"
            )],
            check=False,
            timeout=timeout,
        )
        if list_result.returncode != 0 or not list_result.stdout.strip():
            continue

        for line in list_result.stdout.strip().splitlines():
            if "|" not in line:
                continue
            dir_name, ts_raw = line.split("|", 1)
            try:
                mtime_ts = int(float(ts_raw))
                mtime = datetime.fromtimestamp(mtime_ts)
                age_days = (now - mtime).total_seconds() / 86400.0
            except (ValueError, OSError):
                age_days = 0

            if age_days < older_than_days:
                continue

            # Resolve tmux session name for this dir
            tmux_name = f"{target.session_prefix}-{dir_name}"
            if tmux_name in active_sessions:
                actions.append(PruneAction(
                    target=target.name,
                    remote_dir=f"{runs_dir}/{dir_name}",
                    action="skipped",
                    reason=f"active tmux session, {age_days:.0f}d old",
                ))
                continue

            remote_path = f"{runs_dir}/{dir_name}"
            if dry_run:
                actions.append(PruneAction(
                    target=target.name,
                    remote_dir=remote_path,
                    action="would-delete",
                    reason=f"stale ({age_days:.0f}d old)",
                ))
            else:
                rm_result = runner(
                    ["ssh", target.ssh, _remote_sh(
                        f"rm -rf {shlex.quote(remote_path)}"
                    )],
                    check=False,
                    timeout=timeout,
                )
                if rm_result.returncode == 0:
                    actions.append(PruneAction(
                        target=target.name,
                        remote_dir=remote_path,
                        action="deleted",
                        reason=f"stale ({age_days:.0f}d old)",
                    ))
                else:
                    actions.append(PruneAction(
                        target=target.name,
                        remote_dir=remote_path,
                        action="skipped",
                        reason=f"rm failed: {rm_result.stderr.strip() or rm_result.stdout.strip()}",
                    ))
    return actions


# ── fetch --all ───────────────────────────────────────────────────────────────

def fetch_all_jobs(
    jobs: list[RemoteJob],
    runner: Callable[..., CommandResult] = run_command,
    function_filter: str | None = None,
    target_filter: str | None = None,
    before_fetch: Callable[[RemoteJob, int, int], None] | None = None,
    after_fetch: Callable[[RemoteJob, Path, int, int], None] | None = None,
    delete_remote: bool = False,
    after_cleanup: Callable[[RemoteJob, str | None, int, int], None] | None = None,
) -> list[Path]:
    """Fetch remote outputs for all (or filtered) jobs."""
    selected_jobs = [
        job
        for job in jobs
        if (function_filter is None or job.function == function_filter)
        and (target_filter is None or job.target == target_filter)
    ]
    fetched: list[Path] = []
    total = len(selected_jobs)
    for index, job in enumerate(selected_jobs, 1):
        if before_fetch is not None:
            before_fetch(job, index, total)
        fetched_path = fetch_job(job, runner=runner)
        fetched.append(fetched_path)
        if after_fetch is not None:
            after_fetch(job, fetched_path, index, total)
        if delete_remote:
            warning = cleanup_remote_run_dir_best_effort(job, runner=runner)
            if after_cleanup is not None:
                after_cleanup(job, warning, index, total)
    return fetched


# ── dead metadata pruning ─────────────────────────────────────────────────────

def probe_jobs_active(
    jobs: list[RemoteJob],
    runner: Callable[..., CommandResult] = run_command,
    timeout: float = 10.0,
) -> dict[str, bool]:
    """Probe which jobs are currently active on their remote targets.

    Returns a dict mapping job_id -> is_active.
    """
    result: dict[str, bool] = {}
    for job in jobs:
        status = status_job(job, runner=runner, timeout=timeout)
        result[job.job_id] = status.state == "active"
    return result


def probe_jobs_active_batched(
    jobs: list[RemoteJob],
    runner: Callable[..., CommandResult] = run_command,
    timeout: float = 10.0,
) -> dict[str, bool]:
    """Probe active remote jobs with one tmux session query per SSH host."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    jobs_by_ssh: dict[str, list[RemoteJob]] = {}
    for job in jobs:
        jobs_by_ssh.setdefault(job.ssh, []).append(job)
    if not jobs_by_ssh:
        return {}

    def probe_host(ssh: str, host_jobs: list[RemoteJob]) -> dict[str, bool]:
        script = "tmux list-sessions -F '#{session_name}' 2>/dev/null || true"
        result = runner(
            ["ssh", ssh, _remote_sh(script)],
            check=False,
            timeout=timeout,
        )
        active_sessions = {
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
        }
        return {
            job.job_id: job.tmux_session in active_sessions
            for job in host_jobs
        }

    active: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=min(len(jobs_by_ssh), 8)) as executor:
        futures = [
            executor.submit(probe_host, ssh, host_jobs)
            for ssh, host_jobs in jobs_by_ssh.items()
        ]
        for future in as_completed(futures):
            active.update(future.result())
    return active


def prune_dead_jobs(
    jobs: list[RemoteJob],
    runner: Callable[..., CommandResult] = run_command,
    timeout: float = 10.0,
    dry_run: bool = True,
    jobs_dir: Path = JOBS_DIR,
) -> list[str]:
    """Delete metadata files for jobs whose remote sessions are dead.

    Returns the list of pruned (or would-prune) job_ids.
    """
    active_map = probe_jobs_active_batched(jobs, runner=runner, timeout=timeout)
    pruned: list[str] = []
    for job in jobs:
        if not active_map.get(job.job_id, False):
            if dry_run:
                pruned.append(job.job_id)
            else:
                metadata_path = jobs_dir / f"{job.job_id}.json"
                try:
                    metadata_path.unlink()
                    pruned.append(job.job_id)
                except OSError:
                    pass
    return pruned
