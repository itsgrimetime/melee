"""Remote decomp-permuter target config and job metadata helpers."""

from __future__ import annotations

import json
import math
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import tempfile
import tomllib
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple

from . import candidate_audit
from .permuter_config import DEFAULT_OBJDUMP_COMMAND

CONFIG_PATH = Path.home() / ".config" / "decomp-me" / "permuter-remotes.toml"
JOBS_DIR = Path.home() / ".config" / "decomp-me" / "permuter-jobs"

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
        completed = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        result = CommandResult(
            returncode=124,
            stdout=exc.stdout or "",
            stderr=(
                exc.stderr or ""
                or f"timed out after {timeout:g}s running {shlex.join(argv)}"
            ),
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


def detect_orphaned_wibo_processes(
    runner: Callable[[list[str]], CommandResult] = run_command,
) -> list[OrphanedWiboProcess]:
    """Find orphaned local wibo/MWCC processes that likely need operator action."""
    result = runner(
        ["ps", "-axo", "pid=,ppid=,stat=,etime=,command="],
        check=False,
    )
    if result.returncode != 0:
        return []
    orphans: list[OrphanedWiboProcess] = []
    for raw in result.stdout.splitlines():
        parts = raw.strip().split(None, 4)
        if len(parts) != 5:
            continue
        pid_s, ppid_s, stat, elapsed, command = parts
        command_lower = command.lower()
        if "wibo" not in command_lower or "mwcceppc" not in command_lower:
            continue
        try:
            pid = int(pid_s)
            ppid = int(ppid_s)
        except ValueError:
            continue
        if ppid != 1:
            continue
        orphans.append(OrphanedWiboProcess(
            pid=pid,
            ppid=ppid,
            stat=stat,
            elapsed=elapsed,
            command=command,
        ))
    return orphans


def fetch_job(
    job: RemoteJob,
    runner: Callable[..., CommandResult] = run_command,
    dest: Path | None = None,
) -> Path:
    """Fetch remote permuter outputs for a job into a local run directory."""
    fetch_dest = dest if dest is not None else Path(job.local_perm_dir) / "remote-runs" / job.job_id
    remote_run_dest = fetch_dest / "remote-run"
    fetch_dest.mkdir(parents=True, exist_ok=True)
    remote_run_dest.mkdir(parents=True, exist_ok=True)
    seed_prefix = f"nonmatchings/{job.function}"
    seed_files = [
        "base.c",
        "base.o",
        "compile.sh",
        "settings.toml",
        "target.o",
        "target.s",
    ]
    runner(
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
        ]
    )
    runner(
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
        ]
    )
    candidate_audit.audit_candidate_tree(fetch_dest, function=job.function)
    return fetch_dest


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
        scorer_checks, scorer_info = _doctor_local_scorer(local_perm_dir)
        checks.extend(scorer_checks)
        objdump_checks, objdump_info = _doctor_local_objdump(local_perm_dir, target=target)
        checks.extend(objdump_checks)

    script = _remote_doctor_script(
        target,
        scorer_info=scorer_info,
        objdump_info=objdump_info,
    )
    result = runner(["ssh", target.ssh, _remote_sh(script)], check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "ssh command failed"
        checks.append(DoctorCheck("remote ssh", False, detail))
    else:
        checks.extend(_parse_remote_doctor_output(
            result.stdout,
            expect_scorer=scorer_info is not None,
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

    with _staged_remote_perm_dir(local_perm_dir, target=target) as submit_perm_dir:
        _validate_remote_ready_perm_dir(submit_perm_dir)
        preflight = doctor_target(target, local_perm_dir=submit_perm_dir, runner=runner)
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
            preflight = doctor_target(target, local_perm_dir=submit_perm_dir, runner=runner)
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
        except Exception:
            _remove_job_metadata_best_effort(job_path)
            raise
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
        ]
    )


def _remote_sh(script: str) -> str:
    """Run a POSIX script through sh even if the login shell is fish/zsh."""
    return f"sh -lc {shlex.quote(script)}"


def _remote_doctor_script(
    target: RemoteTarget,
    scorer_info: ScorerCommandInfo | None = None,
    objdump_info: ObjdumpCommandInfo | None = None,
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
        lines.extend(_remote_scorer_doctor_lines(scorer_info))
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


def _remote_scorer_doctor_lines(scorer_info: ScorerCommandInfo) -> list[str]:
    lines = [
        'if grep -q "class CustomCommandScorer" "$perm_root/src/scorer.py" 2>/dev/null && grep -q "scorer_settings" "$perm_root/src/main.py" 2>/dev/null; then emit remote-custom-scorer ok "$perm_root"; else emit remote-custom-scorer fail "CustomCommandScorer missing in remote decomp-permuter"; fi',
        f"scorer_executable={shlex.quote(scorer_info.executable)}",
        'if test "${scorer_executable#/}" != "$scorer_executable"; then scorer_resolved="$scorer_executable"; else scorer_resolved="$(command -v "$scorer_executable" 2>/dev/null)"; fi',
        'if test -n "$scorer_resolved" && test -x "$scorer_resolved"; then scorer_tmp=/tmp/melee-remote-doctor-scorer.$$; (cd "$perm_root" && "$scorer_resolved" debug target score-simplify-order --help) >"$scorer_tmp" 2>&1; scorer_rc=$?; scorer_out=$(head -40 "$scorer_tmp"); if test "$scorer_rc" -eq 0; then emit remote-scorer-command ok "$scorer_resolved debug target score-simplify-order --help"; grep -q -- "--strict-polarity" "$scorer_tmp" && emit remote-scorer-schema ok "strict-polarity scorer schema supported" || emit remote-scorer-schema fail "stale score-simplify-order help; missing --strict-polarity"; else emit remote-scorer-command fail "$scorer_out"; emit remote-scorer-schema fail "score-simplify-order --help failed"; fi; rm -f "$scorer_tmp"; else emit remote-scorer-command fail "$scorer_executable not found or not executable"; emit remote-scorer-schema fail "$scorer_executable not found or not executable"; fi',
    ]
    if scorer_info.target_path is not None:
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
            rewritten = _rewrite_settings_toml_for_remote(text, target=target)
            if rewritten != text:
                settings_toml.write_text(rewritten)
        yield staged


def _validate_remote_ready_perm_dir(local_perm_dir: Path) -> None:
    leaks = _find_local_path_leaks(local_perm_dir)
    if leaks:
        path, needle = leaks[0]
        raise RemoteJobError(
            f"local permuter dir is not remote-ready: {path} contains local-only path "
            f"{needle!r}; regenerate or fix it for the remote root"
        )


_MWCC_EXE_RE = re.compile(r"mwcceppc(?:_debug)?\.exe(?P<rest>.*)$")


def _rewrite_compile_sh_for_remote(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if (
            stripped.startswith("cd ")
            and not stripped.startswith('cd "$MELEE_ROOT"')
            and not stripped.startswith('cd "${MELEE_ROOT')
            and ("/Users/" in stripped or stripped.startswith("cd /"))
        ):
            out.append('cd "${MELEE_ROOT:?MELEE_ROOT must be set}"')
            continue

        if "mwcceppc" in line and ".exe" in line:
            match = _MWCC_EXE_RE.search(line)
            if match is not None:
                indent = line[: len(line) - len(line.lstrip())]
                rest = match.group("rest")
                out.append(
                    indent
                    + '"${MWCC_DEBUG_WIBO:-$MELEE_ROOT/tools/mwcc_debug/bin/wibo}" '
                    + '"${MWCC_DEBUG_COMPILER:-$MELEE_ROOT/build/compilers/GC/1.2.5n/mwcceppc_debug.exe}"'
                    + rest
                )
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


def _rewrite_settings_toml_for_remote(
    text: str,
    *,
    target: RemoteTarget | None = None,
) -> str:
    """Ensure remote jobs use a project-provided scorer disassembler."""
    lines = text.splitlines()
    out: list[str] = []
    found = False
    command = _remote_objdump_command(DEFAULT_OBJDUMP_COMMAND, target)
    for line in lines:
        match = _OBJDUMP_SETTING_RE.match(line)
        if match is not None:
            out.append(f'{match.group(1)}"{command}"')
            found = True
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
        if name == "compile.sh" and target is not None:
            text = _rewrite_compile_sh_for_remote(text)
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


def _doctor_local_scorer(local_perm_dir: Path) -> tuple[list[DoctorCheck], ScorerCommandInfo | None]:
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
            checks.append(DoctorCheck(
                "local scorer target path",
                False,
                (
                    f"relative --target {info.target_path!r}; remote submit "
                    "runs from the remote permuter root"
                ),
            ))
        else:
            checks.append(DoctorCheck("local scorer target path", True, info.target_path))

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
        "remote-scorer-target": "remote scorer target",
    }
    objdump_labels = {
        "remote-objdump-command": "remote objdump command",
    }
    known_labels = {**labels, **scorer_labels, **objdump_labels}
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
) -> list[Path]:
    """Fetch remote outputs for all (or filtered) jobs."""
    fetched: list[Path] = []
    for job in jobs:
        if function_filter is not None and job.function != function_filter:
            continue
        if target_filter is not None and job.target != target_filter:
            continue
        fetched.append(fetch_job(job, runner=runner))
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
    active_map = probe_jobs_active(jobs, runner=runner, timeout=timeout)
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
