"""Remote decomp-permuter target config and job metadata helpers."""

from __future__ import annotations

import json
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


def run_command(argv: list[str], cwd: Path | None = None, check: bool = True) -> CommandResult:
    """Run a local command, returning captured output."""
    completed = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
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
) -> RemoteStatus:
    """Inspect whether the remote tmux session for a job is still active."""
    script = (
        f"tmux has-session -t {shlex.quote(job.tmux_session)} 2>/dev/null "
        "&& printf active || printf stopped"
    )
    result = runner(
        [
            "ssh",
            job.ssh,
            _remote_sh(script),
        ],
        check=False,
    )
    if result.returncode not in (0, 1):
        return RemoteStatus(job_id=job.job_id, state="unknown", detail=result.stderr.strip())
    return RemoteStatus(job_id=job.job_id, state=result.stdout.strip() or "unknown")


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
    follow_flag = " -f" if follow else ""
    return runner(
        [
            "ssh",
            job.ssh,
            _remote_sh(
                f"tail -n {lines}{follow_flag} "
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
        if not preflight.ok:
            failed = [
                f"{check.name}: {check.detail}"
                for check in preflight.checks
                if check.required and not check.ok
            ]
            detail = "; ".join(failed[:5])
            if len(failed) > 5:
                detail += f"; +{len(failed) - 5} more"
            raise RemoteJobError(
                f"remote preflight failed for {target.name}: {detail}"
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
    for line in stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        key, status, detail = parts
        if key not in known_labels:
            continue
        seen.add(key)
        checks.append(DoctorCheck(known_labels[key], status == "ok", detail))
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
