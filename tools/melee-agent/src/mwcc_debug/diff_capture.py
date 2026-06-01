"""Input resolution and pcdump capture for `melee-agent debug inspect diff`."""
from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


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
    import json

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


def read_or_compile_input(
    diff_input: DiffInput,
    *,
    function: str,
    melee_root: Path,
    timeout: int,
) -> str:
    if diff_input.kind == "pcdump":
        return diff_input.path.read_text(encoding="utf-8", errors="replace")
    return compile_source_variant(
        diff_input,
        function=function,
        melee_root=melee_root,
        timeout=timeout,
    )


def compile_source_variant(
    diff_input: DiffInput,
    *,
    function: str,
    melee_root: Path,
    timeout: int,
) -> str:
    with tempfile.TemporaryDirectory(prefix="mwcc_diff_") as td:
        out_path = Path(td) / f"{diff_input.label.lower()}.pcdump.txt"
        with _source_path_for_compile(diff_input, function=function, melee_root=melee_root) as compile_path:
            cmd = [
                "python",
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
                function,
            ]
            try:
                proc = _run_with_process_group_timeout(
                    cmd,
                    cwd=melee_root / "tools" / "melee-agent",
                    timeout=timeout,
                    env=_env_with_child_hang_timeout(timeout),
                )
            except subprocess.TimeoutExpired as exc:
                raise CompileFailure(
                    side=diff_input.label,
                    command=cmd,
                    stdout=exc.stdout or "",
                    stderr=(exc.stderr or "") + f"\ndump local timed out after {timeout}s",
                    returncode=124,
                ) from exc
        if proc.returncode != 0:
            raise CompileFailure(
                side=diff_input.label,
                command=cmd,
                stdout=proc.stdout,
                stderr=proc.stderr,
                returncode=proc.returncode,
            )
        if not out_path.exists():
            raise CompileFailure(
                side=diff_input.label,
                command=cmd,
                stdout=proc.stdout,
                stderr=proc.stderr + "\ndump local completed without writing output",
                returncode=4,
            )
        return out_path.read_text(encoding="utf-8", errors="replace")


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
        yield diff_input.path
        return

    unit = _find_unit_for_function(function, melee_root)
    target = melee_root / "src" / f"{unit}.c"
    original = target.read_bytes()
    replacement = diff_input.path.read_bytes()
    try:
        target.write_bytes(replacement)
        yield target
    finally:
        target.write_bytes(original)


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
        raise subprocess.TimeoutExpired(
            cmd=cmd,
            timeout=timeout,
            output=getattr(exc, "output", None),
            stderr=getattr(exc, "stderr", None),
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
