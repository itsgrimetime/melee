"""Local wibo lane safety checks for mwcc_debug pcdump runs."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class LocalWiboProcess:
    pid: int
    ppid: int
    stat: str
    elapsed: str
    command: str
    source_rel: str | None

    @property
    def uninterruptible(self) -> bool:
        return "U" in self.stat

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LocalLaneGuardResult:
    unsafe: bool
    processes: list[LocalWiboProcess]


def _source_from_command(command: str) -> str | None:
    try:
        argv = shlex.split(command)
    except ValueError:
        argv = command.split()
    for idx, item in enumerate(argv[:-1]):
        if item == "-c":
            return _normalize_source_rel(argv[idx + 1])
    return None


def _normalize_source_rel(source: str | None) -> str | None:
    if source is None:
        return None
    value = source.strip().replace("\\", "/")
    if not value:
        return None
    try:
        path = Path(value)
    except TypeError:
        return value
    if path.is_absolute():
        parts = path.parts
        if "src" in parts:
            src_index = parts.index("src")
            value = "/".join(parts[src_index:])
        else:
            value = path.as_posix()
    while value.startswith("./"):
        value = value[2:]
    return value


def _source_aliases(source: str) -> set[str]:
    normalized = _normalize_source_rel(source)
    if normalized is None:
        return set()
    aliases = {normalized}
    if normalized.startswith("src/"):
        aliases.add(normalized.removeprefix("src/"))
    else:
        aliases.add(f"src/{normalized}")
    return aliases


def parse_wibo_processes(text: str) -> list[LocalWiboProcess]:
    processes: list[LocalWiboProcess] = []
    for raw in text.splitlines():
        parts = raw.strip().split(None, 4)
        if len(parts) != 5:
            continue
        pid_s, ppid_s, stat, elapsed, command = parts
        lowered = command.lower()
        if "wibo" not in lowered or "mwcceppc" not in lowered:
            continue
        try:
            pid = int(pid_s)
            ppid = int(ppid_s)
        except ValueError:
            continue
        processes.append(
            LocalWiboProcess(
                pid=pid,
                ppid=ppid,
                stat=stat,
                elapsed=elapsed,
                command=command,
                source_rel=_source_from_command(command),
            )
        )
    return processes


def scan_local_wibo_processes(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[LocalWiboProcess]:
    try:
        proc = runner(
            ["ps", "-axo", "pid=,ppid=,stat=,etime=,command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, TypeError):
        return []
    if proc.returncode != 0:
        return []
    return parse_wibo_processes(proc.stdout)


def allow_unsafe_local_pcdump(env: dict[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    for name in (
        "MWCC_DEBUG_ALLOW_UNSAFE_LOCAL_PCDUMP",
        "MWCC_DEBUG_ALLOW_UNSAFE_LOCAL",
    ):
        raw = values.get(name, "")
        if raw.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def guard_local_pcdump_lane(
    *,
    source_rel: str,
    function: str | None,
    processes: Iterable[LocalWiboProcess] | None = None,
    allow_unsafe: bool = False,
) -> LocalLaneGuardResult:
    if allow_unsafe:
        return LocalLaneGuardResult(unsafe=False, processes=[])
    aliases = _source_aliases(source_rel)
    if not aliases:
        return LocalLaneGuardResult(unsafe=False, processes=[])
    observed = (
        list(processes)
        if processes is not None
        else scan_local_wibo_processes()
    )
    unsafe = [
        process
        for process in observed
        if process.uninterruptible
        and process.source_rel is not None
        and _normalize_source_rel(process.source_rel) in aliases
    ]
    return LocalLaneGuardResult(unsafe=bool(unsafe), processes=unsafe)


def format_unsafe_processes(processes: Iterable[LocalWiboProcess]) -> str:
    lines = []
    for process in processes:
        command = process.command
        if len(command) > 220:
            command = f"{command[:217]}..."
        lines.append(
            "pid={pid} ppid={ppid} stat={stat} elapsed={elapsed} "
            "source={source} command={command}".format(
                pid=process.pid,
                ppid=process.ppid,
                stat=process.stat,
                elapsed=process.elapsed,
                source=process.source_rel or "unknown",
                command=command,
            )
        )
    return "\n".join(lines)


def format_unsafe_lane_message(
    *,
    source_rel: str,
    function: str | None,
    processes: Iterable[LocalWiboProcess],
) -> str:
    function_detail = f" for {function}" if function else ""
    return (
        f"unsafe local pcdump lane{function_detail}: existing uninterruptible "
        f"wibo process(es) are already compiling {source_rel}. macOS cannot "
        "reap these from user space; refusing to launch another local dump.\n"
        f"{format_unsafe_processes(processes)}\n"
        "Set MWCC_DEBUG_ALLOW_UNSAFE_LOCAL_PCDUMP=1 only if you intentionally "
        "want to launch another local wibo process for this source."
    )
