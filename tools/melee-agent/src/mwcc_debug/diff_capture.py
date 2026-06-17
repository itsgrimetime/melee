"""Input resolution and pcdump capture for `melee-agent debug inspect diff`."""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import cache as pcdump_cache
from . import local_safety
from .source_patch import transfer_candidate
from .temp_scratch import temporary_directory


@dataclass(frozen=True)
class DiffInput:
    label: str
    token: str
    kind: str
    path: Path


@dataclass
class CompileFailure(Exception):
    side: str
    command: list[str]
    stdout: str
    stderr: str
    returncode: int

    def __str__(self) -> str:
        return (
            f"{self.side} failed to compile with exit {self.returncode}\n"
            f"command: {' '.join(self.command)}\n"
            f"{self.stderr or self.stdout}"
        )


def resolve_diff_input(
    side: str,
    token: str,
    *,
    function: str | None,
    melee_root: Path,
) -> DiffInput:
    path = Path(token).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    if path.exists() and path.suffix == ".txt":
        return DiffInput(label=side, token=token, kind="pcdump", path=path)
    if path.exists() and path.suffix == ".c":
        return DiffInput(label=side, token=token, kind="source", path=path)
    if path.exists():
        raise ValueError(f"{side}: expected a .c source or .txt pcdump, got {path}")
    raise ValueError(
        f"{side}: {token!r} is not an existing file. "
        "scratch slug inputs are not supported by mwcc-debug inspect diff; "
        "export the scratch source to a .c file and retry."
    )


def _find_unit_for_function(function: str, melee_root: Path) -> str:
    report_path = melee_root / "build" / "GALE01" / "report.json"
    if not report_path.exists():
        raise ValueError(
            f"cannot resolve base TU for {function}: {report_path} is missing; "
            "run `python configure.py && ninja build/GALE01/report.json`"
        )
    data = json.loads(report_path.read_text())
    for unit in data.get("units", []):
        for fn in unit.get("functions", []):
            if fn.get("name") == function:
                return unit.get("name", "").removeprefix("main/")
    raise ValueError(f"cannot resolve base TU for {function}: function not in report.json")


def _parse_virtual_address(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text, 0)
        except ValueError:
            return None
    return None


def _function_virtual_address(fn: dict) -> int | None:
    metadata = fn.get("metadata")
    if isinstance(metadata, dict):
        parsed = _parse_virtual_address(metadata.get("virtual_address"))
        if parsed is not None:
            return parsed
    return _parse_virtual_address(fn.get("virtual_address"))


def _dedupe_strings(values: Iterator[str] | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return tuple(result)


def function_pcdump_aliases(function: str, melee_root: Path) -> tuple[str, ...]:
    """Return alternate pcdump names for *function* from report metadata.

    Source-level tools sometimes use a friendly report name while the local
    mwcc pcdump still names the function by address. Keep this helper
    best-effort: missing or stale reports should not make callers fail before
    they try the requested name.
    """
    report_path = melee_root / "build" / "GALE01" / "report.json"
    if not report_path.exists():
        return ()
    try:
        data = json.loads(report_path.read_text())
    except (OSError, json.JSONDecodeError):
        return ()
    target_address: int | None = None
    same_address_names: list[str] = []
    for unit in data.get("units", []):
        functions = unit.get("functions", [])
        if not isinstance(functions, list):
            continue
        for fn in functions:
            if not isinstance(fn, dict) or fn.get("name") != function:
                continue
            target_address = _function_virtual_address(fn)
            break
        if target_address is not None:
            for fn in functions:
                if not isinstance(fn, dict):
                    continue
                name = fn.get("name")
                if (
                    isinstance(name, str)
                    and name != function
                    and _function_virtual_address(fn) == target_address
                ):
                    same_address_names.append(name)
            break
    if target_address is None:
        return ()
    aliases = [*same_address_names, f"fn_{target_address:08X}"]
    if "_" in function and not function.startswith("fn_"):
        aliases.append(f"{function.split('_', 1)[0]}_{target_address:08X}")
    return _dedupe_strings(alias for alias in aliases if alias != function)


def read_or_compile_input(
    diff_input: DiffInput,
    *,
    function: str,
    melee_root: Path,
    timeout: int,
    function_aliases: tuple[str, ...] = (),
) -> str:
    if diff_input.kind == "pcdump":
        return diff_input.path.read_text(encoding="utf-8", errors="replace")
    return compile_source_variant(
        diff_input,
        function=function,
        melee_root=melee_root,
        timeout=timeout,
        function_aliases=function_aliases,
    )


def compile_source_variant(
    diff_input: DiffInput,
    *,
    function: str,
    melee_root: Path,
    timeout: int,
    unit_source: Path | None = None,
    function_aliases: tuple[str, ...] = (),
) -> str:
    with temporary_directory(prefix="mwcc_diff_") as td:
        out_path = Path(td) / f"{diff_input.label.lower()}.pcdump.txt"
        if unit_source is None:
            source_context = _source_path_for_compile(
                diff_input,
                function=function,
                melee_root=melee_root,
            )
            unit_source_path = None
        else:
            source_context = nullcontext(diff_input.path)
            unit_source_path = unit_source
            if not unit_source_path.is_absolute():
                unit_source_path = melee_root / unit_source_path
            unit_source_path = unit_source_path.resolve()
        dump_functions = _dedupe_strings((
            function,
            *function_aliases,
            *function_pcdump_aliases(function, melee_root),
        ))
        failures: list[CompileFailure] = []
        with source_context as compile_path:
            for dump_function in dump_functions:
                try:
                    out_path.unlink()
                except FileNotFoundError:
                    pass
                cmd = [
                    sys.executable,
                    "-m",
                    "src.cli",
                    "debug",
                    "dump",
                    "local",
                    str(compile_path),
                    "--output",
                    str(out_path),
                    "--no-cache-sync",
                    "--function",
                    dump_function,
                ]
                if unit_source_path is not None:
                    cmd.extend(["--unit-source", str(unit_source_path)])
                try:
                    proc = _run_with_process_group_timeout(
                        cmd,
                        cwd=melee_root,
                        timeout=timeout,
                        env=_env_with_child_hang_timeout(timeout),
                    )
                except subprocess.TimeoutExpired as exc:
                    raise CompileFailure(
                        side=diff_input.label,
                        command=cmd,
                        stdout=exc.stdout or "",
                        stderr=(
                            (exc.stderr or "")
                            + f"\ndump local timed out after {timeout}s"
                        ),
                        returncode=124,
                    ) from exc
                if proc.returncode == 0 and out_path.exists():
                    return out_path.read_text(encoding="utf-8", errors="replace")
                if proc.returncode == 0:
                    failure = CompileFailure(
                        side=diff_input.label,
                        command=cmd,
                        stdout=proc.stdout,
                        stderr=proc.stderr + "\ndump local completed without writing output",
                        returncode=4,
                    )
                    failures.append(failure)
                    raise failure
                failure = CompileFailure(
                    side=diff_input.label,
                    command=cmd,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    returncode=proc.returncode,
                )
                failures.append(failure)
                if not _dump_local_missing_pcdump_function(proc, dump_function):
                    raise failure
        if failures:
            raise _combined_compile_failure(diff_input.label, failures)
        raise CompileFailure(
            side=diff_input.label,
            command=[],
            stdout="",
            stderr="dump local had no function names to try",
            returncode=4,
        )


def _dump_local_missing_pcdump_function(
    proc: subprocess.CompletedProcess[str],
    dump_function: str,
) -> bool:
    if proc.returncode != 3:
        return False
    text = f"{proc.stderr}\n{proc.stdout}".lower()
    if "not found in pcdump" in text:
        return True
    return (
        "function" in text
        and dump_function.lower() in text
        and "not found" in text
    )


def _combined_compile_failure(
    side: str,
    failures: list[CompileFailure],
) -> CompileFailure:
    last = failures[-1]
    attempted = [
        failure.command[failure.command.index("--function") + 1]
        for failure in failures
        if "--function" in failure.command
    ]
    details = []
    for failure, attempted_function in zip(failures, attempted, strict=False):
        output = (failure.stderr or failure.stdout).strip()
        details.append(f"[{attempted_function}] rc={failure.returncode}\n{output}")
    return CompileFailure(
        side=side,
        command=last.command,
        stdout=last.stdout,
        stderr=(
            "dump local could not find a pcdump function; "
            f"attempted: {', '.join(attempted)}\n" + "\n".join(details)
        ),
        returncode=last.returncode,
    )


def _fresh_pcdump_cache_path_for_restore(
    *,
    melee_root: Path,
    unit: str | None,
) -> Path | None:
    if unit is None:
        return None
    entry = pcdump_cache.lookup(melee_root, unit)
    if entry is None or not entry.fresh:
        return None
    return entry.path


def _preserve_pcdump_cache_freshness_after_restore(
    *,
    cache_path: Path | None,
    source_path: Path,
    original: bytes,
) -> None:
    if cache_path is None:
        return
    try:
        if source_path.read_bytes() != original:
            return
        pcdump_cache.write_hash_sidecar(cache_path, source_path)
    except OSError:
        pass


def _env_with_child_hang_timeout(timeout: int) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("MWCC_DEBUG_HANG_TIMEOUT")
    child_timeout = _child_hang_timeout_before_parent(timeout)
    if existing is not None:
        try:
            existing_float = float(existing)
        except ValueError:
            existing_float = 0.0
        if existing_float > 0:
            child_timeout = min(child_timeout, existing_float)
    env["MWCC_DEBUG_HANG_TIMEOUT"] = f"{child_timeout:g}"
    return env


def _child_hang_timeout_before_parent(timeout: int) -> float:
    if timeout <= 1:
        return max(0.1, float(timeout) * 0.5)
    grace = min(10.0, max(1.0, float(timeout) * 0.1))
    return max(1.0, float(timeout) - grace)


@contextmanager
def _source_path_for_compile(
    diff_input: DiffInput,
    *,
    function: str,
    melee_root: Path,
) -> Iterator[Path]:
    try:
        rel = diff_input.path.resolve().relative_to(melee_root.resolve())
    except ValueError:
        rel = None
    if rel is not None and str(rel).startswith("src/"):
        unit = str(rel).removeprefix("src/").removesuffix(".c")
        original = diff_input.path.read_bytes()
        fresh_cache_path = _fresh_pcdump_cache_path_for_restore(
            melee_root=melee_root,
            unit=unit,
        )
        try:
            yield diff_input.path
        finally:
            diff_input.path.write_bytes(original)
            _preserve_pcdump_cache_freshness_after_restore(
                cache_path=fresh_cache_path,
                source_path=diff_input.path,
                original=original,
            )
        return

    unit = _find_unit_for_function(function, melee_root)
    target = melee_root / "src" / f"{unit}.c"
    original = target.read_bytes()
    fresh_cache_path = _fresh_pcdump_cache_path_for_restore(
        melee_root=melee_root,
        unit=unit,
    )
    candidate_text = diff_input.path.read_text(encoding="utf-8", errors="replace")
    try:
        if transfer_candidate(candidate_text, target, function) is None:
            raise ValueError(
                f"{diff_input.label}: target function {function} not found in "
                f"candidate source {diff_input.path} or target source {target}"
            )
        yield target
    finally:
        target.write_bytes(original)
        _preserve_pcdump_cache_freshness_after_restore(
            cache_path=fresh_cache_path,
            source_path=target,
            original=original,
        )


def read_inspect_input_if_available(
    diff_input: DiffInput,
    *,
    function: str,
    melee_root: Path,
    timeout: int,
    output_path: Path | None = None,
) -> str | None:
    if diff_input.kind != "source":
        return None
    out_path = output_path or _default_inspect_output_path(
        diff_input,
        function=function,
        melee_root=melee_root,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "tools/workflow/mwcc-inspect.sh",
        "--function",
        function,
        "--output",
        str(out_path),
        str(diff_input.path),
    ]
    print(
        f"[mwcc-debug] {diff_input.label}: running {' '.join(cmd)} "
        f"(timeout {timeout}s)",
        file=sys.stderr,
    )
    try:
        proc = _run_with_process_group_timeout(
            cmd,
            cwd=melee_root,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(
            f"[mwcc-debug] {diff_input.label}: mwcc-inspect timed out "
            f"after {timeout}s; killed process group",
            file=sys.stderr,
        )
        return None
    if proc.returncode != 0:
        return None
    if not out_path.exists():
        return None
    return out_path.read_text(encoding="utf-8", errors="replace")


def _default_inspect_output_path(
    diff_input: DiffInput,
    *,
    function: str,
    melee_root: Path,
) -> Path:
    try:
        rel = diff_input.path.resolve().relative_to(melee_root.resolve())
    except ValueError:
        rel = None
    if rel is not None and str(rel).startswith("src/"):
        return melee_root / "build" / "mwcc_inspect" / f"{diff_input.path.stem}.txt"

    digest_source = f"{function}\0{diff_input.path.resolve()}".encode(
        "utf-8",
        errors="replace",
    )
    digest = hashlib.sha256(digest_source).hexdigest()[:12]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", diff_input.path.stem).strip(".-") or "source"
    label = re.sub(r"[^A-Za-z0-9_.-]+", "-", diff_input.label.lower()).strip(".-") or "input"
    return (
        melee_root
        / "build"
        / "mwcc_inspect"
        / "candidates"
        / f"{label}-{stem}-{digest}.txt"
    )


def _run_with_process_group_timeout(
    cmd: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    result: dict[str, object] = {}

    def _communicate() -> None:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            result["stdout"] = stdout
            result["stderr"] = stderr
        except BaseException as exc:  # communicate can raise TimeoutExpired.
            result["exc"] = exc

    thread = threading.Thread(target=_communicate, daemon=True)
    thread.start()
    thread.join(timeout)

    if thread.is_alive() or isinstance(result.get("exc"), subprocess.TimeoutExpired):
        exc = result.get("exc")
        _kill_process_tree(proc.pid, proc)
        for pipe in (getattr(proc, "stdout", None), getattr(proc, "stderr", None)):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if thread.is_alive():
            thread.join(1)
        stderr = getattr(exc, "stderr", None)
        survivor_note = _unreaped_wibo_timeout_note()
        if survivor_note:
            stderr_text = "" if stderr is None else str(stderr)
            if stderr_text and not stderr_text.endswith("\n"):
                stderr_text += "\n"
            stderr = stderr_text + survivor_note
        raise subprocess.TimeoutExpired(
            cmd=cmd,
            timeout=timeout,
            output=getattr(exc, "output", None),
            stderr=stderr,
        ) from exc

    if "exc" in result:
        raise result["exc"]  # type: ignore[misc]

    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    return subprocess.CompletedProcess(
        cmd,
        proc.returncode,
        str(stdout),
        str(stderr),
    )


def _unreaped_wibo_timeout_note() -> str:
    processes = [
        process
        for process in local_safety.scan_local_wibo_processes()
        if process.uninterruptible
    ]
    if not processes:
        return ""
    return (
        "unreaped uninterruptible wibo process(es) remain after timeout; "
        "local pcdump lanes for these sources should be treated as unsafe:\n"
        f"{local_safety.format_unsafe_processes(processes)}"
    )


def _kill_process_tree(root_pid: int, proc: subprocess.Popen[str]) -> None:
    pids = _descendant_pids(root_pid)
    pids.append(root_pid)
    killed_pgids: set[int] = set()
    for pid in pids:
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            if pid != root_pid:
                continue
            pgid = pid
        except PermissionError:
            pgid = pid
        if pgid in killed_pgids:
            continue
        killed_pgids.add(pgid)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            if pid == root_pid:
                proc.kill()


def _descendant_pids(root_pid: int) -> list[int]:
    try:
        result = subprocess.run(
            ["pgrep", "-P", str(root_pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError, TypeError):
        return []
    children: list[int] = []
    for line in result.stdout.splitlines():
        try:
            child = int(line.strip())
        except ValueError:
            continue
        children.extend(_descendant_pids(child))
        children.append(child)
    return children
