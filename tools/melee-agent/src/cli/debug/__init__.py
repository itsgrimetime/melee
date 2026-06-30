"""Debug commands - introspect MWCC compiler internals via remote Windows host.

The MWCC compiler's verbose-debug code path crashes under macOS+wibo+Rosetta but
works natively on Windows. This subcommand bridges that gap: it SSHs into the
configured Windows host and runs the mwcc_debug DLL hook there, streaming the
resulting pcdump.txt back over SSH.

See docs/mwcc-debug.md for one-time setup of the Windows side.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import dataclasses
import difflib
import hashlib
import itertools
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Callable, Iterable, Iterator, Mapping, NoReturn, Optional

import typer

from .._common import DEFAULT_MELEE_ROOT, console
from ...mwcc_debug import (
    FunctionEvents,
    analyze_function,
    derive_target_from_function,
    find_function,
    format_suggestions,
    parse_hook_events,
    parse_pcdump,
    score_function,
    simulate_function,
    slice_pcdump_to_function,
    suggest,
)
from ...mwcc_debug import candidate_audit
from ...mwcc_debug import cache as pcdump_cache
from ...mwcc_debug import local_safety
from ...mwcc_debug import permuter_remote
from ...mwcc_debug.cast_audit import (
    audit_function_casts,
    crossref_with_asm,
    detect_signedness_mismatches,
    find_call_sites,
)
from ...mwcc_debug.patterns import (
    PATTERNS,
    list_patterns,
)
from ...mwcc_debug.pressure_explorer import HELPER_INLINE_LIFETIME_OPERATORS
from ...mwcc_debug.source_patch import (
    build_decl_order_candidates_for_scope,
    explain_decl_reorder_skip,
    extract_function,
    find_function as find_source_function,
    find_function_definitions,
    get_decl_names_by_scope,
    reorder_decls_in_function_scope,
    transfer_candidate,
)
from ...mwcc_debug.asm_parser import (
    AsmInstruction,
    extract_function as asm_extract_function,
    find_first_def as asm_find_first_def,
    parse_prologue_end as asm_parse_prologue_end,
)
from ...mwcc_debug.iter_match import (
    MatchResult,
    instr_signature,
    match_virtual_for_expected_def,
)
from ...mwcc_debug.diff_capture import (
    CompileFailure,
    _env_with_child_hang_timeout,
    _kill_process_tree,
    _run_with_process_group_timeout,
    read_inspect_input_if_available,
    read_or_compile_input,
    resolve_diff_input,
)
from ...mwcc_debug.diff_report import (
    compare_function_dumps,
    render_text_report,
)
from ...mwcc_debug.temp_scratch import mkdtemp as mwcc_debug_mkdtemp
from ...mwcc_debug.temp_scratch import reaped_scratch_root as mwcc_debug_scratch_root
from ...mwcc_debug.temp_scratch import scratch_path as mwcc_debug_scratch_path
from ...mwcc_debug.frame_reservations import (
    analyze_frame_from_asm_text,
    analyze_frame_from_function,
    analyze_frame_reservations,
    evaluate_frame_transform_probe_results,
    evaluate_stack_home_probe_results,
)
from ...mwcc_debug.frame_taxonomy import classify_frame_taxonomy
from ...mwcc_debug.signature_audit import (
    audit_signature_call_type,
    validate_signature_patches,
)
from ...mwcc_debug.value_numbering import detect_divide_rematerialization_ceiling




def _compute_melee_root() -> Path:
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if _looks_like_melee_root(candidate):
            return candidate
    return DEFAULT_MELEE_ROOT



































def _read_control_flow_shape_checkdiff_payload(
    *,
    function: str,
    melee_root: Path,
    checkdiff_json: Path | None,
    checkdiff_timeout: float,
    no_build: bool,
) -> tuple[dict, str]:
    if checkdiff_json is not None:
        try:
            payload = json.loads(checkdiff_json.read_text())
        except json.JSONDecodeError as exc:
            typer.echo(
                f"checkdiff JSON could not be parsed: {exc}",
                err=True,
            )
            raise typer.Exit(2) from exc
        except OSError as exc:
            typer.echo(f"checkdiff JSON could not be read: {exc}", err=True)
            raise typer.Exit(2) from exc
        if not isinstance(payload, dict):
            typer.echo("checkdiff JSON root was not an object", err=True)
            raise typer.Exit(2)
        return payload, str(checkdiff_json)

    cmd = [
        "python",
        str(melee_root / "tools" / "checkdiff.py"),
        function,
        "--format",
        "json",
        "--no-fingerprint",
    ]
    if no_build:
        cmd.append("--no-build")

    try:
        proc = subprocess.run(
            cmd,
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=checkdiff_timeout,
            env=_checkdiff_env_without_fingerprint(),
        )
    except subprocess.TimeoutExpired as exc:
        typer.echo(
            f"checkdiff timed out after {checkdiff_timeout:g}s",
            err=True,
        )
        raise typer.Exit(3) from exc
    except OSError as exc:
        typer.echo(f"failed to run checkdiff: {exc}", err=True)
        raise typer.Exit(3) from exc

    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        if proc.stderr:
            typer.echo(proc.stderr.rstrip(), err=True)
        if proc.stdout:
            typer.echo(proc.stdout.rstrip(), err=True)
        raise typer.Exit(proc.returncode or 3)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        if proc.stderr:
            typer.echo(proc.stderr.rstrip(), err=True)
        typer.echo(f"checkdiff did not emit JSON: {exc}", err=True)
        raise typer.Exit(3) from exc
    if not isinstance(payload, dict):
        typer.echo("checkdiff JSON root was not an object", err=True)
        raise typer.Exit(3)
    return payload, "checkdiff"


def _checkdiff_asm_lines(payload: dict, key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(
        isinstance(line, str) for line in value
    ):
        typer.echo(f"checkdiff JSON did not include {key} lines", err=True)
        raise typer.Exit(2)
    return value







@dataclasses.dataclass(frozen=True)
class _ForceVectorEntry:
    raw: str
    kind: str
    ig_idx: int | None = None
    phys: int | None = None
    root: int | None = None
    class_id: int | None = None
    iter_idx: int | None = None

    def to_payload(self) -> dict:
        payload: dict = {"raw": self.raw, "kind": self.kind}
        for key in ("ig_idx", "phys", "root", "class_id", "iter_idx"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return payload






























def _checkdiff_env_without_fingerprint() -> dict[str, str]:
    env = os.environ.copy()
    env["CHECKDIFF_NO_FINGERPRINT"] = "1"
    return env




@contextmanager
def _acquire_checkdiff_repo_lock(
    melee_root: Path,
    *,
    label: str = "checkdiff build/report",
    timeout: float | None = None,
):
    """Acquire the same repo-wide lock used by tools/checkdiff.py."""
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
            while True:
                elapsed = time.monotonic() - start
                if timeout is not None and elapsed >= timeout:
                    raise TimeoutError(
                        f"timed out waiting for repo-wide {label} lock "
                        f"after {timeout:g}s: {lock_path}"
                    )
                sleep_for = 0.1
                if timeout is not None:
                    sleep_for = max(0.01, min(sleep_for, timeout - elapsed))
                time.sleep(sleep_for)
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    continue
            elapsed = time.monotonic() - start
            print(f"acquired {label} lock after {elapsed:.1f}s", file=sys.stderr)
        yield
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()






debug_app = typer.Typer(
    help="MWCC debugging workflow for dumps, inspection, target scoring, "
         "source suggestions, focused mutations, and permuter triage."
)
# Re-export the shared, non-monkeypatched helpers carved into _common.py so the
# names stay bound in this package namespace (keeps __init__'s own remaining
# code, sibling modules' deferred `from src.cli.debug import <name>` imports,
# and any `debug_cli.<name>` attribute access resolving).
from src.cli.debug._common import *  # noqa: E402,F401,F403
from src.cli.debug.suggest import suggest_app as _suggest_app  # noqa: E402
from src.cli.debug.suggest import *  # noqa: E402,F401,F403
from src.cli.debug.permute import permute_app as _permute_app  # noqa: E402
from src.cli.debug.permute import *  # noqa: E402,F401,F403
from src.cli.debug.dump import dump_app as _dump_app  # noqa: E402
from src.cli.debug.solve import solve_app as _solve_app  # noqa: E402
from src.cli.debug.util import util_app as _util_app  # noqa: E402
from src.cli.debug.intervene import intervene_app as _intervene_app  # noqa: E402
from src.cli.debug.intervene import *  # noqa: E402,F401,F403
from src.cli.debug.target import target_app as _target_app  # noqa: E402

# `measure` is a small group whose only command lives in this module (see
# measure_inline_leverage_cmd below), so it is defined here rather than carved
# into a sibling module.
measure_app = typer.Typer(
    help="Run source-shape measurement harnesses over matched functions."
)

debug_app.add_typer(_dump_app, name="dump")
from src.cli.debug.inspect import inspect_app as _inspect_app  # noqa: E402
debug_app.add_typer(_inspect_app, name="inspect")
from src.cli.debug.inspect import *  # noqa: E402,F401,F403
debug_app.add_typer(_target_app, name="target")
debug_app.add_typer(_suggest_app, name="suggest")
from src.cli.debug.mutate import mutate_app as _mutate_app  # noqa: E402
debug_app.add_typer(_mutate_app, name="mutate")
from src.cli.debug.mutate import *  # noqa: E402,F401,F403
debug_app.add_typer(_intervene_app, name="intervene")
debug_app.add_typer(_permute_app, name="permute")
debug_app.add_typer(_util_app, name="util")
debug_app.add_typer(_solve_app, name="solve")
debug_app.add_typer(measure_app, name="measure")


from src.search.cli import search_app as _search_app  # noqa: E402
debug_app.add_typer(_search_app, name="search")

from src.cli.debug.retro import retro_app as _retro_app  # noqa: E402
debug_app.add_typer(_retro_app, name="retro")
from src.cli.debug.solve import *  # noqa: E402,F401,F403
from src.cli.debug.dump import *  # noqa: E402,F401,F403  (re-export for monkeypatch/direct-import compat)
from src.cli.debug.util import *  # noqa: E402,F401,F403
from src.cli.debug.target import *  # noqa: E402,F401,F403

# Top-level `debug` commands (registered directly on debug_app, not under a
# subgroup). Defined as plain functions in select_order.py; re-apply the
# decorators here, preserving name/hidden flag and the original registration
# order so the `debug --help` command surface stays byte-identical.
from src.cli.debug.select_order import (  # noqa: E402
    suggest_schedule_source_compat,
    debug_diff_schedule,
    debug_coalesce_search_cmd,
    debug_select_order_search_cmd,
)
debug_app.command(name="suggest-schedule-source", hidden=True)(
    suggest_schedule_source_compat
)
debug_app.command(name="diff-schedule")(debug_diff_schedule)
debug_app.command(name="coalesce-search")(debug_coalesce_search_cmd)
debug_app.command(name="select-order-search")(debug_select_order_search_cmd)
from src.cli.debug.select_order import *  # noqa: E402,F401,F403


@measure_app.command(name="inline-leverage")
def measure_inline_leverage_cmd(
    module: Annotated[
        Optional[str],
        typer.Option(
            "--module",
            help="Module prefix to sample from report.json, e.g. mn.",
        ),
    ] = None,
    file_path: Annotated[
        Optional[Path],
        typer.Option(
            "--file",
            help="One source TU. First slice requires --function with --file.",
        ),
    ] = None,
    function: Annotated[
        Optional[str],
        typer.Option(
            "--function",
            "-f",
            help="One function. Bypasses the fuzzy==100 corpus filter.",
        ),
    ] = None,
    all_modules: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Explicit opt-in to scan across report.json units.",
        ),
    ] = False,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            help="Maximum matched functions to inspect before pair limiting.",
        ),
    ] = 20,
    max_pairs: Annotated[
        Optional[int],
        typer.Option(
            "--max-pairs",
            help="Maximum (function, inline) pairs to emit.",
        ),
    ] = None,
    epsilon: Annotated[
        float,
        typer.Option(
            "--epsilon",
            help="Fuzzy delta threshold separating fuzzy_only from neutral.",
        ),
    ] = 0.05,
    run_id: Annotated[
        Optional[str],
        typer.Option("--run-id", help="Ledger/report run label."),
    ] = None,
    db_path: Annotated[
        Optional[Path],
        typer.Option(
            "--db",
            help="Optional SQLite ledger path for retained evidence.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Detect/de-inline candidates without compiling variants.",
        ),
    ] = False,
    checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--checkdiff-timeout",
            help="Timeout in seconds for each checkdiff scoring run.",
        ),
    ] = 600.0,
    evidence_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--evidence-dir",
            help="Optional directory for retained source/checkdiff evidence.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Measure whether real inline boundaries are structural codegen levers."""
    if limit <= 0:
        raise typer.BadParameter("--limit must be positive")
    if max_pairs is not None and max_pairs <= 0:
        raise typer.BadParameter("--max-pairs must be positive")

    from ...inline_leverage.run import render_text, run_inline_leverage

    melee_root = _compute_melee_root()

    def _run() -> dict:
        return run_inline_leverage(
            melee_root=melee_root,
            module=module,
            function=function,
            file_path=file_path,
            all_modules=all_modules,
            limit=limit,
            max_pairs=max_pairs,
            run_id=run_id,
            dry_run=dry_run,
            epsilon=epsilon,
            db_path=db_path,
            checkdiff_timeout=checkdiff_timeout,
            evidence_dir=evidence_dir,
        )

    try:
        if dry_run:
            report = _run()
        else:
            with _acquire_checkdiff_repo_lock(
                melee_root,
                label="inline-leverage measurement",
            ):
                report = _run()
    except Exception as exc:
        typer.echo(f"inline-leverage failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(2) from exc

    if json_out:
        typer.echo(json.dumps(report, indent=2, sort_keys=True))
    else:
        typer.echo(render_text(report))


def _resolve_src_relative(c_file: str, *, label: str = "source file") -> str:
    """Resolve a .c file path to one relative to the melee repo root.

    Accepts:
      - Absolute path: /Users/mike/code/melee/src/melee/lb/lbarq.c
      - Repo-relative: src/melee/lb/lbarq.c
      - CWD-relative when run from inside repo

    Returns the path with forward slashes (POSIX style — easier for remote PS).
    """
    repo = DEFAULT_MELEE_ROOT.resolve()
    raw_path = Path(c_file).expanduser()
    if raw_path.is_absolute():
        candidates = [raw_path.resolve()]
    else:
        candidates = [
            (Path.cwd() / raw_path).resolve(),
            (repo / raw_path).resolve(),
        ]

    seen: set[Path] = set()
    first_existing_non_repo: Path | None = None
    first_existing_wrong_suffix: Path | None = None
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        if not p.exists():
            continue
        try:
            rel = p.relative_to(repo)
        except ValueError:
            if first_existing_non_repo is None:
                first_existing_non_repo = p
            continue
        if p.suffix != ".c":
            if first_existing_wrong_suffix is None:
                first_existing_wrong_suffix = p
            continue
        return str(rel).replace("\\", "/")

    tried = ", ".join(str(path) for path in seen)
    cwd = Path.cwd().resolve()
    if first_existing_non_repo is not None:
        raise typer.BadParameter(
            f"{label} is outside the melee repo: {first_existing_non_repo}; "
            f"cwd={cwd}; repo={repo}; tried: {tried}"
        )
    if first_existing_wrong_suffix is not None:
        raise typer.BadParameter(
            f"{label} must be a .c file, got: {first_existing_wrong_suffix}; "
            f"cwd={cwd}; repo={repo}; tried: {tried}"
        )
    raise typer.BadParameter(
        f"{label} not found for {c_file!r}; cwd={cwd}; repo={repo}; tried: {tried}"
    )






def _remote_pcdump_local_head(melee_root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=melee_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _run_remote_pcdump(
    *,
    source_rel: str,
    compile_source_rel: str,
    host: str,
    remote_script: str,
    timeout: int | float,
    branch: str | None = None,
    no_pull: bool = False,
    stage_source_path: Path | None = None,
    stage_source_label: str | None = None,
    extra_env_parts: Iterable[str] = (),
    stream_stdout_to: Any | None = None,
    forward_stderr: bool = False,
) -> _RemotePcdumpResult:
    """Run the remote PowerShell pcdump script, optionally staging stdin source."""
    branch = _resolve_remote_pcdump_branch(branch)
    cmd_parts = [
        _cmd_set_env(
            "MWCC_DEBUG_TIMEOUT_SECS",
            _remote_pcdump_timeout_env_value(timeout),
        )
    ]
    if no_pull:
        cmd_parts.append(_cmd_set_env("MWCC_DEBUG_NO_PULL", "1"))
    if branch and branch not in ("master", "main"):
        cmd_parts.append(_cmd_set_env("MWCC_DEBUG_BRANCH", branch))
    cmd_parts.extend(extra_env_parts)

    stage_source_bytes: bytes | None = None
    stage_stdin_bytes: bytes | None = None
    stage_source_sha256: str | None = None
    staging_transport: str | None = None
    remote_stage_source: str | None = None
    if stage_source_path is not None:
        stage_source_bytes = stage_source_path.read_bytes()
        stage_source_sha256 = hashlib.sha256(stage_source_bytes).hexdigest()
        stage_source_label = stage_source_label or source_rel
        if len(stage_source_bytes) > _REMOTE_STAGE_SOURCE_STDIN_MAX_BYTES:
            staging_transport = "scp"
            remote_stage_source, upload_stderr, upload_rc = _remote_stage_source_via_scp(
                host=host,
                source_path=stage_source_path,
                timeout=timeout,
            )
            if upload_rc != 0:
                return _RemotePcdumpResult(
                    returncode=upload_rc,
                    stdout="",
                    stderr=upload_stderr,
                    cmd=[
                        "scp",
                        str(stage_source_path),
                        f"{host}:{remote_stage_source or '<remote-stage-source>'}",
                    ],
                    host=host,
                    source_rel=source_rel,
                    compile_source_rel=compile_source_rel,
                    staged_source=stage_source_label,
                    bytes_written=0,
                    stage_source_sha256=stage_source_sha256,
                    staging_ack_confirmed=False,
                    staging_transport=staging_transport,
                    remote_stage_source=remote_stage_source,
                )
            cmd_parts.append(
                _cmd_set_env("MWCC_DEBUG_STAGE_SOURCE_FILE", remote_stage_source)
            )
            cmd_parts.append(_cmd_set_env("MWCC_DEBUG_STAGE_SOURCE_DELETE", "1"))
        else:
            staging_transport = "stdin"
            stage_stdin_bytes = stage_source_bytes
            cmd_parts.append(_cmd_set_env("MWCC_DEBUG_STAGE_SOURCE_STDIN", "1"))
        cmd_parts.append(
            _cmd_set_env("MWCC_DEBUG_STAGE_SOURCE_LABEL", stage_source_label)
        )

    cmd_parts.append(
        f"powershell -NoProfile -ExecutionPolicy Bypass "
        f"-File {remote_script} {compile_source_rel}"
    )
    remote_cmd = " && ".join(cmd_parts)
    ssh_cmd = ["ssh", host, remote_cmd]

    capture_staged_stream_stderr = (
        stage_source_path is not None and stream_stdout_to is not None
    )
    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": (
            subprocess.PIPE
            if capture_staged_stream_stderr or not forward_stderr
            else sys.stderr
        ),
    }
    if stage_stdin_bytes is not None:
        popen_kwargs["stdin"] = subprocess.PIPE

    proc = subprocess.Popen(ssh_cmd, **popen_kwargs)
    stderr_text = ""

    if stream_stdout_to is None:
        stdout_data, stderr_data, returncode = _communicate_remote_pcdump(
            proc,
            ssh_cmd=ssh_cmd,
            input_bytes=stage_stdin_bytes,
            timeout=timeout,
        )
        stderr_text += _decode_remote_stream(stderr_data)
        staging_ack_confirmed = (
            _remote_staging_ack_confirmed(
                expected_sha256=stage_source_sha256,
                stderr_text=stderr_text,
            )
            if stage_source_sha256 is not None
            else None
        )
        ack_error = (
            _remote_staging_ack_error(
                expected_sha256=stage_source_sha256,
                stderr_text=stderr_text,
                stage_source_label=stage_source_label,
                remote_script=remote_script,
            )
            if returncode == 0
            else None
        )
        if ack_error is not None:
            stderr_text = f"{stderr_text.rstrip()}\n{ack_error}\n"
            returncode = 66
            staging_ack_confirmed = False
        return _RemotePcdumpResult(
            returncode=returncode,
            stdout=_decode_remote_stream(stdout_data),
            stderr=stderr_text,
            cmd=ssh_cmd,
            host=host,
            source_rel=source_rel,
            compile_source_rel=compile_source_rel,
            staged_source=stage_source_label if stage_source_path is not None else None,
            bytes_written=len(stdout_data or b""),
            stage_source_sha256=stage_source_sha256,
            staging_ack_confirmed=staging_ack_confirmed,
            staging_transport=staging_transport,
            remote_stage_source=remote_stage_source,
        )

    stdout_data, stderr_data, returncode = _communicate_remote_pcdump(
        proc,
        ssh_cmd=ssh_cmd,
        input_bytes=stage_stdin_bytes,
        timeout=timeout,
    )
    stderr_text += _decode_remote_stream(stderr_data)
    staging_ack_confirmed = (
        _remote_staging_ack_confirmed(
            expected_sha256=stage_source_sha256,
            stderr_text=stderr_text,
        )
        if stage_source_sha256 is not None
        else None
    )
    ack_error = (
        _remote_staging_ack_error(
            expected_sha256=stage_source_sha256,
            stderr_text=stderr_text,
            stage_source_label=stage_source_label,
            remote_script=remote_script,
        )
        if returncode == 0
        else None
    )
    if ack_error is not None:
        stderr_text = f"{stderr_text.rstrip()}\n{ack_error}\n"
        returncode = 66
        stdout_data = b""
        staging_ack_confirmed = False
    stdout_bytes = (
        stdout_data.encode()
        if isinstance(stdout_data, str)
        else (stdout_data or b"")
    )
    if stdout_data and returncode == 0:
        stream_stdout_to.write(stdout_bytes)
    if forward_stderr and stderr_text:
        print(stderr_text, file=sys.stderr, end="")
    return _RemotePcdumpResult(
        returncode=returncode,
        stdout="",
        stderr=stderr_text,
        cmd=ssh_cmd,
        host=host,
        source_rel=source_rel,
        compile_source_rel=compile_source_rel,
        staged_source=stage_source_label if stage_source_path is not None else None,
        bytes_written=len(stdout_bytes) if returncode == 0 else 0,
        stage_source_sha256=stage_source_sha256,
        staging_ack_confirmed=staging_ack_confirmed,
        staging_transport=staging_transport,
        remote_stage_source=remote_stage_source,
    )










# PowerPC EABI register conventions for GPR. The first 8 args go in r3..r10;
# return value is in r3. Floats use f1..f13 / f1 return. We only annotate
# the GPR convention here — most matching investigations are GPR-bound.
























def _load_target_spec(path: Path) -> dict:
    """Load a target spec from YAML or JSON.

    Both are accepted; JSON is a strict subset so we can fall back to it
    when PyYAML isn't installed. The spec shape is documented in
    src/mwcc_debug/scoring.py.

    Validates the basic shape of the loaded spec and emits a helpful
    error if it's malformed.
    """
    if not path.exists():
        typer.echo(f"target spec file not found: {path}", err=True)
        typer.echo(
            "Generate one with `melee-agent debug target derive -f FN`.",
            err=True,
        )
        raise typer.Exit(2)
    text = path.read_text()
    try:
        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except ImportError:
                typer.echo(
                    f"PyYAML not installed but target file {path.name} "
                    f"has YAML extension.\n"
                    f"Either `pip install PyYAML` or convert the file to "
                    f"JSON (use `debug target derive --format json` "
                    f"to regenerate).",
                    err=True,
                )
                raise typer.Exit(2)
            spec = yaml.safe_load(text)
        else:
            spec = json.loads(text)
    except json.JSONDecodeError as e:
        typer.echo(
            f"failed to parse {path} as JSON: {e}\n"
            f"Expected shape:\n"
            f'  {{ "function": "fn_name", "virtuals": {{"32": 26, ...}} }}',
            err=True,
        )
        raise typer.Exit(2)
    except Exception as e:
        typer.echo(f"failed to parse target spec {path}: {e}", err=True)
        raise typer.Exit(2)

    # Basic shape validation
    if not isinstance(spec, dict):
        typer.echo(
            f"target spec {path} must be an object/dict at top level, "
            f"got {type(spec).__name__}.",
            err=True,
        )
        raise typer.Exit(2)
    if "virtuals" not in spec:
        typer.echo(
            f"target spec {path} is missing the 'virtuals' key.\n"
            f"Expected shape:\n"
            f'  {{ "function": "fn_name", "virtuals": {{"32": 26, ...}} }}\n'
            f"Generate a valid one with `melee-agent debug target derive "
            f"-f FN`.",
            err=True,
        )
        raise typer.Exit(2)
    return spec















def _read_frame_reservation_current_asm(
    function: str,
    *,
    melee_root: Path,
) -> str | None:
    proc = subprocess.run(
        [
            sys.executable,
            "tools/checkdiff.py",
            function,
            "--format",
            "json",
            "--no-build",
        ],
        cwd=melee_root,
        capture_output=True,
        text=True,
        env=_checkdiff_env_without_fingerprint(),
    )
    if proc.returncode not in (0, 1):
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    current_asm = payload.get("current_asm")
    if not isinstance(current_asm, list) or not all(
        isinstance(line, str) for line in current_asm
    ):
        return None
    return "\n".join(current_asm)


def _read_frame_reservation_source_current_asm(
    source_file: Path,
    *,
    function: str,
    melee_root: Path,
    timeout: float | None,
) -> str | None:
    score = _score_source_candidate_real_tree(
        source_file,
        function=function,
        melee_root=melee_root,
        timeout=timeout,
        include_stack_slot=True,
    )
    payload = getattr(score, "checkdiff_payload", None)
    if not isinstance(payload, Mapping):
        return None
    current_asm = payload.get("current_asm")
    if not isinstance(current_asm, list) or not all(
        isinstance(line, str) for line in current_asm
    ):
        return None
    return "\n".join(current_asm)








































def _detect_frame_residual_hint(
    function: str,
    *,
    unit: str | None,
    melee_root: Path,
    pcdump_path: Path,
) -> dict | None:
    try:
        pcdump_text = pcdump_path.read_text()
        names = _resolve_frame_function_names(function, pcdump_text, melee_root)
        if names is None:
            return None
        expected_text = _read_frame_reservation_expected_asm(
            names.report_function,
            expected_asm=None,
            no_expected=False,
            melee_root=melee_root,
        )
        current_text = (
            _read_frame_reservation_current_asm(
                names.report_function,
                melee_root=melee_root,
            )
            if _pcdump_has_symbolic_stack_homes(pcdump_text)
            else None
        )
        report = analyze_frame_reservations(
            pcdump_text,
            names.pcdump_function,
            expected_asm_text=expected_text,
            current_asm_text=current_text,
            display_function=function,
        )
        _attach_frame_function_aliases(report, names)
    except Exception:
        return None
    return _frame_residual_hint_from_report(report, unit=unit)






def _read_signature_checkdiff_payload(
    *,
    function: str,
    melee_root: Path,
    checkdiff_json: Path | None,
    checkdiff_timeout: float,
    no_build: bool,
) -> tuple[dict, str]:
    if checkdiff_json is not None:
        try:
            payload = json.loads(checkdiff_json.read_text())
        except json.JSONDecodeError as exc:
            typer.echo(
                f"checkdiff JSON could not be parsed: {exc}",
                err=True,
            )
            raise typer.Exit(2) from exc
        except OSError as exc:
            typer.echo(f"checkdiff JSON could not be read: {exc}", err=True)
            raise typer.Exit(2) from exc
        if not isinstance(payload, dict):
            typer.echo("checkdiff JSON root was not an object", err=True)
            raise typer.Exit(2)
        _validate_signature_checkdiff_function(payload, function)
        return payload, str(checkdiff_json)

    cmd = [
        sys.executable,
        str(melee_root / "tools" / "checkdiff.py"),
        function,
        "--format",
        "json",
        "--no-fingerprint",
    ]
    if no_build:
        cmd.append("--no-build")
    try:
        proc = subprocess.run(
            cmd,
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=checkdiff_timeout,
            env=_checkdiff_env_without_fingerprint(),
        )
    except subprocess.TimeoutExpired as exc:
        typer.echo(
            f"checkdiff timed out after {checkdiff_timeout:g}s",
            err=True,
        )
        raise typer.Exit(3) from exc
    except OSError as exc:
        typer.echo(f"failed to run checkdiff: {exc}", err=True)
        raise typer.Exit(3) from exc
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        if proc.stderr:
            typer.echo(proc.stderr.rstrip(), err=True)
        if proc.stdout:
            typer.echo(proc.stdout.rstrip(), err=True)
        raise typer.Exit(proc.returncode or 3)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        if proc.stderr:
            typer.echo(proc.stderr.rstrip(), err=True)
        typer.echo(f"checkdiff did not emit JSON: {exc}", err=True)
        raise typer.Exit(3) from exc
    if not isinstance(payload, dict):
        typer.echo("checkdiff JSON root was not an object", err=True)
        raise typer.Exit(3)
    _validate_signature_checkdiff_function(payload, function)
    return payload, "checkdiff"




def _run_signature_candidate_checkdiff_many(
    *,
    functions: list[str],
    candidate_source: str,
    source_path: Path,
    unit: str,
    melee_root: Path,
    timeout: float,
    rebuild_source: bool = False,
) -> dict[str, dict]:
    if not functions:
        raise RuntimeError("candidate checkdiff requires at least one function")
    if rebuild_source:
        return _run_signature_candidate_checkdiff_many_rebuild(
            functions=functions,
            candidate_source=candidate_source,
            source_path=source_path,
            unit=unit,
            melee_root=melee_root,
            timeout=timeout,
        )
    primary_function = functions[0]
    probe_dir = (
        melee_root
        / "build"
        / "mwcc_debug_cache"
        / "probes"
        / "signature_audit"
    )
    probe_dir.mkdir(parents=True, exist_ok=True)
    safe_function = re.sub(r"[^A-Za-z0-9_.-]+", "_", primary_function)
    stamp = f"{os.getpid()}.{int(time.time() * 1000)}"
    probe_path = probe_dir / f"{safe_function}.{stamp}.c"
    probe_obj = probe_dir / f"{safe_function}.{stamp}.o"
    probe_pcdump = probe_dir / f"{safe_function}.{stamp}.pcdump.txt"
    probe_path.write_text(candidate_source)

    cli_cwd = melee_root / "tools" / "melee-agent"
    if not cli_cwd.exists():
        cli_cwd = melee_root
    dump_cmd = [
        sys.executable,
        "-m",
        "src.cli",
        "debug",
        "dump",
        "local",
        str(probe_path),
        "--function",
        primary_function,
        "--unit-source",
        str(source_path),
        "--keep-obj",
        str(probe_obj),
        "--no-cache-sync",
        "--output",
        str(probe_pcdump),
    ]
    dump_proc = subprocess.run(
        dump_cmd,
        cwd=cli_cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_checkdiff_env_for_locked_child(disable_fingerprint=True),
    )
    if dump_proc.returncode != 0:
        detail = (dump_proc.stderr or dump_proc.stdout or "").strip()
        raise RuntimeError(
            f"candidate compile failed with exit {dump_proc.returncode}"
            + (f": {detail}" if detail else "")
        )
    if not probe_obj.exists():
        raise RuntimeError(f"candidate compile did not produce object: {probe_obj}")

    unit_for_o = unit[:-2] if unit.endswith(".c") else unit
    unit_for_o = unit_for_o.removeprefix("src/")
    build_obj = melee_root / "build" / "GALE01" / "src" / f"{unit_for_o}.o"
    payloads: dict[str, dict] = {}
    with _acquire_checkdiff_repo_lock(
        melee_root,
        label="signature-audit validation",
    ):
        build_obj_existed = build_obj.exists()
        saved_obj = build_obj.read_bytes() if build_obj_existed else None
        try:
            build_obj.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(probe_obj, build_obj)
            for function in functions:
                checkdiff_proc = subprocess.run(
                    [
                        sys.executable,
                        str(melee_root / "tools" / "checkdiff.py"),
                        function,
                        "--format",
                        "json",
                        "--no-build",
                    ],
                    cwd=melee_root,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=_checkdiff_env_for_locked_child(disable_fingerprint=True),
                )
                if (
                    checkdiff_proc.returncode not in (0, 1)
                    or not checkdiff_proc.stdout.strip()
                ):
                    detail = (
                        checkdiff_proc.stderr
                        or checkdiff_proc.stdout
                        or ""
                    ).strip()
                    raise RuntimeError(
                        "candidate checkdiff failed for "
                        f"{function} with exit {checkdiff_proc.returncode}"
                        + (f": {detail}" if detail else "")
                    )
                try:
                    payload = json.loads(checkdiff_proc.stdout)
                except json.JSONDecodeError as exc:
                    detail = (
                        checkdiff_proc.stderr
                        or checkdiff_proc.stdout
                        or str(exc)
                    ).strip()
                    raise RuntimeError(
                        "candidate checkdiff emitted non-json for "
                        f"{function}: {detail}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise RuntimeError(
                        "candidate checkdiff JSON root was not an object "
                        f"for {function}"
                    )
                payloads[function] = payload
        finally:
            if build_obj_existed and saved_obj is not None:
                build_obj.write_bytes(saved_obj)
            elif not build_obj_existed and build_obj.exists():
                build_obj.unlink()

    return payloads






def _signature_sibling_functions(
    *,
    function: str,
    source_text: str,
    explicit_siblings: list[str],
    report: Any | None = None,
    limit: int = 8,
) -> list[str]:
    known: list[str] = []
    if function in {"mnDiagram2_UpdateHeader", "mnDiagram2_Create"}:
        for sibling in ("mnDiagram2_GetRankedName", "mnDiagram2_GetRankedFighter"):
            if find_source_function(source_text, sibling) is not None:
                known.append(sibling)
    inferred: list[str] = []
    helper_names = _signature_report_return_width_helpers(report)
    if helper_names:
        helper_patterns = [
            re.compile(rf"\b{re.escape(helper)}\s*\(") for helper in sorted(helper_names)
        ]
        for span in find_function_definitions(source_text):
            if span.name == function:
                continue
            body = source_text[span.body_open : span.body_close]
            if any(pattern.search(body) for pattern in helper_patterns):
                inferred.append(span.name)
    functions: list[str] = []
    seen = {function}
    for sibling in [*explicit_siblings, *inferred, *known]:
        if sibling in seen:
            continue
        functions.append(sibling)
        seen.add(sibling)
        if len(functions) >= limit:
            break
    return functions




def _find_unit_for_function(func_name: str, melee_root: Path) -> Optional[str]:
    """Locate the unit (source path without .c) containing func_name via
    report.json. Mirrors tools/checkdiff.py's find_unit_for_function."""
    report_path = melee_root / "build" / "GALE01" / "report.json"
    if not report_path.exists():
        return None
    target_addr = _fn_addr_from_name(func_name)
    with report_path.open("r") as f:
        for unit in json.load(f).get("units", []):
            for function in unit.get("functions", []):
                if function.get("name") == func_name:
                    return unit.get("name", "").removeprefix("main/")
                if (
                    target_addr is not None
                    and _report_function_virtual_address(function) == target_addr
                ):
                    return unit.get("name", "").removeprefix("main/")
    return None




@dataclasses.dataclass(frozen=True)
class _FrameFunctionNames:
    requested: str
    report_function: str
    pcdump_function: str
    aliases: tuple[str, ...]


































def _reg_class_from_virtual_token(token: Optional[str]) -> Optional[str]:
    if token is None:
        return None
    stripped = token.strip().lower()
    if stripped.startswith("r"):
        return "gpr"
    if stripped.startswith("f"):
        return "fpr"
    return None






















def _pressure_class_id(register_class: str | None) -> int:
    normalized = (register_class or "gpr").strip().lower()
    if normalized in {"1", "f", "fp", "fpr", "float", "floating"}:
        return 1
    return 0
















































































_ACTIVE_SOURCE_RESTORES: dict[Path, list[str]] = {}
_SOURCE_RESTORE_SIGNAL_HANDLERS: dict[int, object] = {}
















class _SelectOrderCommandSourceRestore:
    def __init__(self, path: Path | None, *, melee_root: Path):
        self.path = path if path is not None and path.exists() else None
        self.melee_root = melee_root
        self.original = self.path.read_bytes() if self.path is not None else None
        self._registered_active_restore = False
        if self.path is not None and self.original is not None:
            try:
                _register_active_source_restore(self.path, self.original.decode("utf-8"))
                self._registered_active_restore = True
            except UnicodeDecodeError:
                pass

    def restore(self) -> None:
        if self.path is None or self.original is None:
            return
        try:
            current = self.path.read_bytes() if self.path.exists() else None
        except Exception:
            current = None
        if current == self.original:
            return
        _restore_source_bytes_snapshot(
            self.path,
            self.original,
            melee_root=self.melee_root,
        )

    def close(self) -> None:
        try:
            self.restore()
        finally:
            if self._registered_active_restore and self.path is not None:
                _unregister_active_source_restore(self.path)
                self._registered_active_restore = False

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass






def _write_select_order_timeout_ledger(
    path: Path,
    ledger: Mapping[str, Any],
    *,
    timed_out: bool,
    timeout_error: str | None,
) -> None:
    payload = _select_order_json_safe(dict(ledger))
    if not isinstance(payload, dict):
        payload = {"value": payload}
    payload["timed_out"] = timed_out
    payload["timeout_error"] = timeout_error
    if timed_out and payload.get("stop_condition") is None:
        payload["stop_condition"] = "timeout"
    if timed_out:
        payload["partial"] = True
    else:
        payload.setdefault("partial", False)
    path.write_text(json.dumps(payload, indent=2))


def _select_order_public_variants(variants: Iterable[Mapping[str, Any]]) -> list[Any]:
    public: list[Any] = []
    for variant in variants:
        item = dict(variant)
        item.pop("_pcdump_key", None)
        item.pop("_checkdiff_payload", None)
        public.append(_select_order_json_safe(item))
    return public


















@dataclasses.dataclass(frozen=True)
class _SourceCandidateRealScore:
    match_percent: float | None
    match_percent_error: str | None
    stack_slot_localizer: dict | None = None
    stack_slot_error: str | None = None
    checkdiff_payload: dict | None = None
    structural_guard: dict | None = None
    structural_guard_error: str | None = None


@dataclasses.dataclass(frozen=True)
class _NameMagicWholeSourceScore:
    match_percent: float | None
    match_percent_error: str | None
    no_name_magic_match: bool | None
    checkdiff_payload: dict | None = None










def _kill_debug_dump_local_process_tree(proc_handle: subprocess.Popen[str]) -> None:
    _kill_process_tree(proc_handle.pid, proc_handle)


















def _run_checkdiff_no_name_magic_json(
    function: str,
    *,
    melee_root: Path,
    timeout: float | None,
    no_build: bool = False,
) -> tuple[dict | None, str | None]:
    cmd = [
        sys.executable,
        "tools/checkdiff.py",
        function,
        "--format",
        "json",
        "--no-name-magic",
    ]
    if no_build:
        cmd.append("--no-build")
    try:
        proc = subprocess.run(
            cmd,
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_checkdiff_env_without_fingerprint(),
        )
    except subprocess.TimeoutExpired:
        return None, "checkdiff --no-name-magic timed out"
    except Exception as exc:
        return None, f"checkdiff --no-name-magic failed: {exc}"
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        detail = (proc.stderr or proc.stdout or str(exc)).strip()
        return None, f"checkdiff --no-name-magic emitted non-json: {detail}"
    if proc.returncode not in (0, 1):
        detail = (proc.stderr or proc.stdout or "").strip()
        return None, (
            f"checkdiff --no-name-magic exited {proc.returncode}"
            + (f": {detail}" if detail else "")
        )
    return payload, None




def _name_magic_object_evidence(
    unit: str,
    melee_root: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    current_obj = melee_root / "build" / "GALE01" / "src" / f"{unit}.o"
    if not current_obj.exists():
        return None, "current-object-missing"
    target_obj = melee_root / "build" / "GALE01" / "obj" / f"{unit}.o"
    if not target_obj.exists():
        return None, "target-object-missing"

    from ...mwcc_debug.o_rewriter import (
        find_all_anonymous_sdata2_symbols,
        suggest_name_magic_map,
    )

    symbols = find_all_anonymous_sdata2_symbols(current_obj)
    duplicate_counts: dict[tuple[int, int], int] = {}
    for symbol in symbols:
        duplicate_counts[(symbol.size, symbol.value)] = (
            duplicate_counts.get((symbol.size, symbol.value), 0) + 1
        )

    anonymous_sdata2: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        rendered = _name_magic_decode_anonymous_symbol(symbol)
        if duplicate_counts.get((symbol.size, symbol.value), 0) > 1:
            rendered["ambiguous"] = True
        anonymous_sdata2[symbol.name] = rendered

    _all_symbols, suggested = suggest_name_magic_map(current_obj, target_obj)
    suggestions: list[dict[str, Any]] = []
    for symbol, target in suggested:
        suggestion = _name_magic_decode_anonymous_symbol(symbol)
        suggestion["target"] = target
        suggestions.append(suggestion)

    return (
        {
            "anonymous_sdata2": anonymous_sdata2,
            "name_magic_suggestions": suggestions,
        },
        None,
    )




def _score_source_candidate_real_tree(
    path: Path,
    *,
    function: str,
    melee_root: Path,
    timeout: float | None = None,
    deadline: float | None = None,
    status: Callable[[str], None] | None = None,
    include_stack_slot: bool = False,
    include_structural_guard: bool = False,
    full_unit_source: bool = False,
) -> _SourceCandidateRealScore:
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        return _SourceCandidateRealScore(
            None,
            f"function not found in report.json: {function}",
        )
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        return _SourceCandidateRealScore(
            None,
            f"target source not found: {target_path}",
        )
    if status is not None:
        status("waiting for source-scoring lock")
    lock_timeout, deadline_error = _timeout_before_deadline(
        deadline,
        timeout,
        "waiting for source-scoring lock",
    )
    if deadline_error is not None:
        return _SourceCandidateRealScore(None, deadline_error)
    with _acquire_source_score_repo_lock(melee_root, timeout=lock_timeout):
        if status is not None:
            status("source-scoring lock acquired")
        candidate_text = path.read_text()
        original = target_path.read_text()
        if full_unit_source:
            if find_source_function(candidate_text, function) is None:
                return _SourceCandidateRealScore(
                    None,
                    f"function not found in candidate source: {path}",
                )
        else:
            external_helpers = _new_external_function_definitions(
                candidate_text,
                original,
                function=function,
            )
            if external_helpers:
                helper_list = ", ".join(external_helpers)
                return _SourceCandidateRealScore(
                    None,
                    (
                        f"candidate source defines helper function(s) outside "
                        f"{function}: {helper_list}. Source candidate scoring only "
                        f"transfers {function} into {target_path.relative_to(melee_root)}, "
                        "so those definitions would be dropped before the real-tree "
                        "build. Inline the helper into the target function or apply "
                        "the helper to the real source file before scoring."
                    ),
                )
        obj_path = f"build/GALE01/src/{unit}.o"
        fresh_cache_path = _fresh_pcdump_cache_path_for_restore(
            unit=unit,
            melee_root=melee_root,
        )
        _register_active_source_restore(target_path, original)
        result: tuple[float | None, str | None] = (None, None)
        restore_error: str | None = None
        cleanup_error: str | None = None
        applied = False
        try:
            if status is not None:
                status(f"applying candidate to src/{unit}.c")
            if full_unit_source:
                target_path.write_text(candidate_text)
            elif transfer_candidate(candidate_text, target_path, function) is None:
                result = (None, f"function not found in candidate source: {path}")
                return _SourceCandidateRealScore(*result)
            applied = True
            if status is not None:
                status(f"building {obj_path}")
            build_timeout, deadline_error = _timeout_before_deadline(
                deadline,
                timeout,
                f"building {obj_path}",
            )
            if deadline_error is not None:
                result = (None, deadline_error)
                return _SourceCandidateRealScore(*result)
            build_result, retried = _run_ninja_with_no_diag_retry(
                ["ninja", obj_path],
                melee_root,
                timeout=build_timeout,
            )
            if build_result.returncode != 0:
                result = (None, _failure_diagnostic_or_fallback(
                    build_result.stdout,
                    build_result.stderr,
                    fallback=(
                        f"ninja {obj_path} failed with exit {build_result.returncode}"
                        + (" after retry" if retried else "")
                    ),
                ))
                return _SourceCandidateRealScore(*result)
            if status is not None:
                status("build complete; refreshing report.json")
            refresh_timeout, deadline_error = _timeout_before_deadline(
                deadline,
                timeout,
                "refreshing report.json",
            )
            if deadline_error is not None:
                result = (None, deadline_error)
                return _SourceCandidateRealScore(*result)
            result = _refresh_match_pct_after_successful_build(
                unit,
                function,
                melee_root,
                timeout=refresh_timeout,
                deadline=deadline,
            )
            stack_slot_localizer = None
            stack_slot_error = None
            checkdiff_payload = None
            structural_guard = None
            structural_guard_error = None
            if include_stack_slot or include_structural_guard:
                if status is not None:
                    status(
                        "running checkdiff structural guard"
                        if include_structural_guard
                        else "running checkdiff stack-slot localizer"
                    )
                stack_timeout, deadline_error = _timeout_before_deadline(
                    deadline,
                    timeout,
                    (
                        "running checkdiff structural guard"
                        if include_structural_guard
                        else "running checkdiff stack-slot localizer"
                    ),
                )
                if deadline_error is not None:
                    if include_stack_slot:
                        stack_slot_error = deadline_error
                    if include_structural_guard:
                        structural_guard_error = deadline_error
                    stack_timeout = 0.0
                else:
                    checkdiff_payload, checkdiff_error = _run_checkdiff_json(
                        function,
                        melee_root=melee_root,
                        timeout=stack_timeout,
                        no_build=True,
                        label=(
                            "checkdiff structural guard"
                            if include_structural_guard
                            else "checkdiff stack-slot analysis"
                        ),
                    )
                    if include_stack_slot:
                        stack_slot_error = checkdiff_error
                    if include_structural_guard:
                        structural_guard_error = checkdiff_error
                if include_structural_guard and checkdiff_payload is not None:
                    structural_guard = _shape_guard_from_checkdiff_payload(
                        checkdiff_payload
                    )
                if checkdiff_payload is not None:
                    stack_slot_localizer = _find_stack_slot_localizer_in_json(
                        checkdiff_payload
                    )
            if status is not None:
                status("match-percent refresh complete")
            return _SourceCandidateRealScore(
                result[0],
                result[1],
                stack_slot_localizer,
                stack_slot_error,
                checkdiff_payload,
                structural_guard,
                structural_guard_error,
            )
        finally:
            if applied:
                if status is not None:
                    status("restoring source")
                restore_error = _restore_source_snapshot(target_path, original)
                if restore_error is None:
                    _preserve_pcdump_cache_freshness_after_restore(
                        cache_path=fresh_cache_path,
                        source_path=target_path,
                        original=original,
                    )
            _unregister_active_source_restore(target_path)
            if restore_error:
                print(f"[source-restore] {restore_error}", file=sys.stderr)
            elif applied:
                try:
                    if status is not None:
                        status(
                            f"cleanup rebuild {obj_path} build/GALE01/report.json"
                        )
                    cleanup_timeout, deadline_error = _timeout_before_deadline(
                        deadline,
                        timeout,
                        f"cleanup rebuild {obj_path} build/GALE01/report.json",
                    )
                    if deadline_error is not None:
                        cleanup_error = deadline_error
                        cleanup_timeout = 0.0
                    else:
                        cleanup_result = _run_command_with_optional_timeout(
                            ["ninja", obj_path, "build/GALE01/report.json"],
                            cwd=melee_root,
                            timeout=cleanup_timeout,
                        )
                        if cleanup_result.returncode != 0:
                            cleanup_error = _failure_diagnostic_or_fallback(
                                cleanup_result.stdout,
                                cleanup_result.stderr,
                                fallback=(
                                    "failed to rebuild object/report after source "
                                    f"restore: ninja {obj_path} "
                                    f"build/GALE01/report.json exited "
                                    f"{cleanup_result.returncode}"
                                ),
                            )
                except subprocess.TimeoutExpired:
                    cleanup_error = (
                        f"timed out restoring object/report after source restore: "
                        f"ninja {obj_path} build/GALE01/report.json"
                    )
                except Exception:
                    cleanup_error = (
                        "failed to rebuild object/report after source restore"
                    )
                if cleanup_error is None and status is not None:
                    status("cleanup rebuild complete")
            if restore_error:
                raise RuntimeError(restore_error)
            if cleanup_error:
                raise RuntimeError(cleanup_error)


def _score_whole_source_candidate_no_name_magic(
    path: Path,
    *,
    function: str,
    melee_root: Path,
    header_path: Path | None = None,
    header_target: Path | None = None,
    timeout: float | None = None,
    status: Callable[[str], None] | None = None,
) -> _NameMagicWholeSourceScore:
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        return _NameMagicWholeSourceScore(
            None,
            f"function not found in report.json: {function}",
            None,
        )
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        return _NameMagicWholeSourceScore(
            None,
            f"target source not found: {target_path}",
            None,
        )
    if status is not None:
        status("waiting for source-scoring lock")
    with _acquire_source_score_repo_lock(melee_root):
        if status is not None:
            status("source-scoring lock acquired")
        candidate_text = path.read_text(encoding="utf-8", errors="replace")
        original = target_path.read_text(encoding="utf-8", errors="replace")
        target_header_path: Path | None = None
        candidate_header_text: str | None = None
        original_header: str | None = None
        if header_path is not None:
            target_header_path = header_target or target_path.with_suffix(".h")
            if not target_header_path.exists():
                return _NameMagicWholeSourceScore(
                    None,
                    f"target header not found: {target_header_path}",
                    None,
                )
            candidate_header_text = header_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
            original_header = target_header_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        obj_path = f"build/GALE01/src/{unit}.o"
        fresh_cache_path = _fresh_pcdump_cache_path_for_restore(
            unit=unit,
            melee_root=melee_root,
        )
        _register_active_source_restore(target_path, original)
        if target_header_path is not None and original_header is not None:
            _register_active_source_restore(target_header_path, original_header)
        applied = False
        header_applied = False
        restore_error: str | None = None
        cleanup_error: str | None = None
        try:
            if (
                target_header_path is not None
                and candidate_header_text is not None
            ):
                if status is not None:
                    status(f"applying header candidate to {target_header_path}")
                target_header_path.write_text(candidate_header_text, encoding="utf-8")
                header_applied = True
            if status is not None:
                status(f"applying whole-file candidate to src/{unit}.c")
            target_path.write_text(candidate_text, encoding="utf-8")
            applied = True
            if status is not None:
                status(f"building {obj_path}")
            build_result, retried = _run_ninja_with_no_diag_retry(
                ["ninja", obj_path],
                melee_root,
                timeout=timeout,
            )
            if build_result.returncode != 0:
                return _NameMagicWholeSourceScore(
                    None,
                    _failure_diagnostic_or_fallback(
                        build_result.stdout,
                        build_result.stderr,
                        fallback=(
                            f"ninja {obj_path} failed with exit "
                            f"{build_result.returncode}"
                            + (" after retry" if retried else "")
                        ),
                    ),
                    None,
                )
            if status is not None:
                status("build complete; refreshing report.json")
            match_percent, match_error = _refresh_match_pct_after_successful_build(
                unit,
                function,
                melee_root,
                timeout=timeout,
            )
            if match_error is not None:
                return _NameMagicWholeSourceScore(
                    match_percent,
                    match_error,
                    None,
                )
            if status is not None:
                status("running checkdiff --no-name-magic")
            checkdiff_payload, checkdiff_error = _run_checkdiff_no_name_magic_json(
                function,
                melee_root=melee_root,
                timeout=timeout,
                no_build=True,
            )
            if checkdiff_error is not None:
                return _NameMagicWholeSourceScore(
                    match_percent,
                    checkdiff_error,
                    None,
                    checkdiff_payload,
                )
            return _NameMagicWholeSourceScore(
                match_percent,
                None,
                (
                    checkdiff_payload.get("match") is True
                    if checkdiff_payload is not None
                    else None
                ),
                checkdiff_payload,
            )
        finally:
            if applied:
                if status is not None:
                    status("restoring source")
                restore_error = _restore_source_snapshot(target_path, original)
                if restore_error is None:
                    _preserve_pcdump_cache_freshness_after_restore(
                        cache_path=fresh_cache_path,
                        source_path=target_path,
                        original=original,
                    )
            if (
                header_applied
                and target_header_path is not None
                and original_header is not None
            ):
                if status is not None:
                    status("restoring header")
                header_restore_error = _restore_source_snapshot(
                    target_header_path,
                    original_header,
                )
                if header_restore_error:
                    restore_error = (
                        f"{restore_error}; {header_restore_error}"
                        if restore_error
                        else header_restore_error
                    )
            _unregister_active_source_restore(target_path)
            if target_header_path is not None:
                _unregister_active_source_restore(target_header_path)
            if restore_error:
                print(f"[source-restore] {restore_error}", file=sys.stderr)
            elif applied or header_applied:
                try:
                    if status is not None:
                        status(
                            f"cleanup rebuild {obj_path} build/GALE01/report.json"
                        )
                    cleanup_result = subprocess.run(
                        ["ninja", obj_path, "build/GALE01/report.json"],
                        cwd=melee_root,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )
                    if cleanup_result.returncode != 0:
                        cleanup_error = _failure_diagnostic_or_fallback(
                            cleanup_result.stdout,
                            cleanup_result.stderr,
                            fallback=(
                                "failed to rebuild object/report after source "
                                f"restore: ninja {obj_path} "
                                f"build/GALE01/report.json exited "
                                f"{cleanup_result.returncode}"
                            ),
                        )
                except subprocess.TimeoutExpired:
                    cleanup_error = (
                        f"timed out restoring object/report after source restore: "
                        f"ninja {obj_path} build/GALE01/report.json"
                    )
                except Exception:
                    cleanup_error = (
                        "failed to rebuild object/report after source restore"
                    )
                if cleanup_error is None and status is not None:
                    status("cleanup rebuild complete")
            if restore_error:
                raise RuntimeError(restore_error)
            if cleanup_error:
                raise RuntimeError(cleanup_error)








def _select_order_source_score(
    path: Path,
    *,
    function: str,
    melee_root: Path,
    timeout: float | None = None,
    deadline: float | None = None,
    status: Callable[[str], None] | None = None,
    include_structural_guard: bool = False,
    full_unit_source: bool = False,
) -> _SourceCandidateRealScore:
    match_percent_fn = globals().get("_select_order_source_match_percent")
    original_match_percent_fn = globals().get(
        "_ORIGINAL_SELECT_ORDER_SOURCE_MATCH_PERCENT"
    )
    if (
        callable(match_percent_fn)
        and original_match_percent_fn is not None
        and match_percent_fn is not original_match_percent_fn
    ):
        match_percent, match_percent_error = match_percent_fn(
            path,
            function=function,
            melee_root=melee_root,
            timeout=timeout,
            status=status,
            full_unit_source=full_unit_source,
        )
        return _SourceCandidateRealScore(match_percent, match_percent_error)
    score_kwargs = dict(
        path=path,
        function=function,
        melee_root=melee_root,
        timeout=timeout,
        deadline=deadline,
        status=status,
        include_structural_guard=include_structural_guard,
    )
    if full_unit_source:
        score_kwargs["full_unit_source"] = True
    return _score_source_candidate_real_tree(**score_kwargs)


def _select_order_source_match_percent(
    path: Path,
    *,
    function: str,
    melee_root: Path,
    timeout: float | None = None,
    status: Callable[[str], None] | None = None,
    full_unit_source: bool = False,
) -> tuple[float | None, str | None]:
    score_kwargs = dict(
        path=path,
        function=function,
        melee_root=melee_root,
        timeout=timeout,
        status=status,
    )
    if full_unit_source:
        score_kwargs["full_unit_source"] = True
    score = _score_source_candidate_real_tree(**score_kwargs)
    return score.match_percent, score.match_percent_error


_ORIGINAL_SELECT_ORDER_SOURCE_MATCH_PERCENT = _select_order_source_match_percent




















def _select_order_source_hunk_crossover_probes(
    *,
    base_source: str,
    seed_sources: list[Mapping[str, Any]],
    function: str,
    max_probes: int,
) -> list[Any]:
    from ...mwcc_debug.pressure_explorer import LifetimeLayoutProbe

    max_probes = max(0, int(max_probes))
    if max_probes <= 0 or len(seed_sources) < 2:
        return []
    base_function = extract_function(base_source, function)
    if base_function is None:
        return []
    base_lines = base_function.splitlines(keepends=True)
    records: list[dict[str, Any]] = []

    for seed_index, seed in enumerate(seed_sources):
        seed_source = seed.get("source_text")
        if not isinstance(seed_source, str):
            continue
        seed_function = extract_function(seed_source, function)
        if seed_function is None or seed_function == base_function:
            continue
        seed_lines = seed_function.splitlines(keepends=True)
        matcher = difflib.SequenceMatcher(
            None,
            base_lines,
            seed_lines,
            autojunk=False,
        )
        hunks: list[dict[str, Any]] = []
        for hunk_index, (tag, i1, i2, j1, j2) in enumerate(matcher.get_opcodes()):
            if tag == "equal":
                continue
            if not _select_order_source_hunk_has_statement(
                [*base_lines[i1:i2], *seed_lines[j1:j2]]
            ):
                continue
            hunks.append({
                "hunk_index": hunk_index,
                "diff_tag": tag,
                "base_start": i1,
                "base_end": i2,
                "candidate_start": j1,
                "candidate_end": j2,
                "replacement": seed_lines[j1:j2],
                "base_line_range": [i1 + 1, i2],
                "candidate_line_range": [j1 + 1, j2],
                "base_hunk": "".join(base_lines[i1:i2]),
                "candidate_hunk": "".join(seed_lines[j1:j2]),
            })
        if not hunks:
            continue
        protected = {
            str(ig_idx): int(phys)
            for ig_idx, phys in dict(seed.get("protected_hits") or {}).items()
            if str(ig_idx).lstrip("-").isdigit()
        }
        records.append({
            "index": seed_index,
            "label": str(seed.get("label") or f"seed-{seed_index}"),
            "hunks": hunks,
            "protected_hits": protected,
            "components": [
                component
                for hunk in hunks
                for component in _select_order_source_hunk_line_components(
                    seed_label=str(seed.get("label") or f"seed-{seed_index}"),
                    protected_hits=protected,
                    hunk=hunk,
                    base_lines=base_lines,
                )
            ],
        })

    if len(records) < 2:
        return []

    def apply_hunks(hunks: list[dict[str, Any]]) -> str | None:
        ordered = sorted(hunks, key=lambda item: (item["base_start"], item["base_end"]))
        patched: list[str] = []
        cursor = 0
        last_end = -1
        for hunk in ordered:
            start = int(hunk["base_start"])
            end = int(hunk["base_end"])
            if start < last_end:
                return None
            patched.extend(base_lines[cursor:start])
            patched.extend(hunk["replacement"])
            cursor = end
            last_end = end
        patched.extend(base_lines[cursor:])
        return "".join(patched)

    probes: list[Any] = []
    seen: set[str] = set()
    for recipient in records:
        recipient_hunks = list(recipient["hunks"])
        for donor in records:
            if donor["index"] == recipient["index"]:
                continue
            for donor_hunk in donor["hunks"]:
                if any(
                    not (
                        donor_hunk["base_end"] <= recipient_hunk["base_start"]
                        or donor_hunk["base_start"] >= recipient_hunk["base_end"]
                    )
                    for recipient_hunk in recipient_hunks
                ):
                    continue
                patched_function = apply_hunks([*recipient_hunks, donor_hunk])
                if patched_function is None or patched_function == base_function:
                    continue
                patched_function = (
                    _select_order_dedupe_duplicate_local_declarations(
                        patched_function,
                    )
                )
                patched_source = _select_order_replace_function_text(
                    base_source,
                    function,
                    patched_function,
                )
                if patched_source is None:
                    continue
                digest = hashlib.sha256(patched_source.encode("utf-8")).hexdigest()[:16]
                if digest in seen:
                    continue
                seen.add(digest)
                protected = dict(recipient["protected_hits"])
                protected.update(donor["protected_hits"])
                probes.append(LifetimeLayoutProbe(
                    label=(
                        "source-hunk-crossover-"
                        f"{_select_order_safe_label(recipient['label'])}-"
                        f"{_select_order_safe_label(donor['label'])}-"
                        f"{donor_hunk['hunk_index']}"
                    ),
                    operator="source-hunk-crossover",
                    description=(
                        "Combine non-overlapping source hunks from retained "
                        "select-order neighborhoods."
                    ),
                    source_text=patched_source,
                    provenance={
                        "kind": "source-hunk-crossover",
                        "repair_action": "cross-neighborhood-crossover",
                        "recipient_label": recipient["label"],
                        "donor_label": donor["label"],
                        "recipient_hunks": recipient_hunks,
                        "donor_hunks": [donor_hunk],
                        "protected_force_phys_hits": protected,
                    },
                ))
                if len(probes) >= max_probes:
                    return probes
    components = [
        component
        for record in records
        for component in record.get("components", [])
    ]
    atomized_index = 0
    max_depth = min(3, len(components))
    for depth in range(2, max_depth + 1):
        for combo in itertools.combinations(components, depth):
            source_labels = {
                str(component["source_label"])
                for component in combo
            }
            if len(source_labels) < 2:
                continue
            if any(
                _select_order_source_components_overlap(left, right)
                for idx, left in enumerate(combo)
                for right in combo[idx + 1:]
            ):
                continue
            protected = _select_order_merge_protected_hits(combo)
            if protected is None:
                continue
            patched_function = apply_hunks(list(combo))
            if patched_function is None or patched_function == base_function:
                continue
            patched_function = _select_order_dedupe_duplicate_local_declarations(
                patched_function,
            )
            patched_source = _select_order_replace_function_text(
                base_source,
                function,
                patched_function,
            )
            if patched_source is None:
                continue
            digest = hashlib.sha256(patched_source.encode("utf-8")).hexdigest()[:16]
            if digest in seen:
                continue
            seen.add(digest)
            atomized_index += 1
            probes.append(LifetimeLayoutProbe(
                label=(
                    "source-hunk-crossover-atomized-"
                    f"d{depth}-{atomized_index}"
                ),
                operator="source-hunk-crossover",
                description=(
                    "Combine non-overlapping atomized source components from "
                    "retained select-order neighborhoods."
                ),
                source_text=patched_source,
                provenance={
                    "kind": "source-hunk-crossover",
                    "repair_action": "cross-neighborhood-atomized-crossover",
                    "component_depth": depth,
                    "component_labels": sorted(source_labels),
                    "source_components": [
                        _select_order_component_provenance(component)
                        for component in combo
                    ],
                    "protected_force_phys_hits": protected,
                },
            ))
            if len(probes) >= max_probes:
                return probes
    return probes


def _select_order_subtractive_source_hunk_repair_probes(
    *,
    base_source: str,
    downhill_source: str,
    function: str,
    protected_hits: Mapping[int | str, int],
    max_probes: int,
) -> list[Any]:
    from ...mwcc_debug.pressure_explorer import LifetimeLayoutProbe

    max_probes = max(0, int(max_probes))
    if max_probes <= 0:
        return []
    base_function = extract_function(base_source, function) or base_source
    downhill_function = extract_function(downhill_source, function) or downhill_source
    if base_function == downhill_function:
        return []

    protected = {
        str(ig_idx): int(phys)
        for ig_idx, phys in protected_hits.items()
        if str(ig_idx).lstrip("-").isdigit()
    }
    base_lines = base_function.splitlines(keepends=True)
    downhill_lines = downhill_function.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(
        None,
        base_lines,
        downhill_lines,
        autojunk=False,
    )
    probes: list[Any] = []
    seen: set[str] = set()

    def add_probe(
        *,
        label: str,
        operator: str,
        description: str,
        patched_function: str,
        provenance: dict[str, Any],
    ) -> None:
        if len(probes) >= max_probes:
            return
        patched_source = downhill_source.replace(
            downhill_function,
            patched_function,
            1,
        )
        if patched_source == downhill_source:
            return
        digest = hashlib.sha256(patched_source.encode("utf-8")).hexdigest()[:16]
        if digest in seen:
            return
        seen.add(digest)
        probes.append(LifetimeLayoutProbe(
            label=label,
            operator=operator,
            description=description,
            source_text=patched_source,
            provenance={
                "kind": operator,
                "protected_force_phys_hits": protected,
                **provenance,
            },
        ))

    changed_hunks: list[tuple[int, str, int, int, int, int]] = []
    for index, (tag, i1, i2, j1, j2) in enumerate(matcher.get_opcodes()):
        if tag == "equal":
            continue
        if not _select_order_source_hunk_has_statement(
            [*base_lines[i1:i2], *downhill_lines[j1:j2]]
        ):
            continue
        changed_hunks.append((index, tag, i1, i2, j1, j2))
        base_count = i2 - i1
        candidate_count = j2 - j1
        if (
            tag == "replace"
            and base_count > 0
            and candidate_count > base_count
            and candidate_count % base_count == 0
        ):
            candidate_stride = candidate_count // base_count
            for sub_index in range(base_count):
                base_start = i1 + sub_index
                cand_start = j1 + (sub_index * candidate_stride)
                cand_end = cand_start + candidate_stride
                patched_lines = (
                    downhill_lines[:cand_start]
                    + base_lines[base_start:base_start + 1]
                    + downhill_lines[cand_end:]
                )
                add_probe(
                    label=f"source-hunk-revert-{index}-{sub_index}",
                    operator="source-hunk-subtractive-repair",
                    description=(
                        "Revert one downhill source sub-hunk while preserving "
                        "the rest of the candidate source chain."
                    ),
                    patched_function="".join(patched_lines),
                    provenance={
                        "repair_action": "revert-hunk",
                        "hunk_index": index,
                        "sub_hunk_index": sub_index,
                        "diff_tag": tag,
                        "base_line_range": [base_start + 1, base_start + 1],
                        "candidate_line_range": [cand_start + 1, cand_end],
                        "base_hunk": base_lines[base_start],
                        "candidate_hunk": "".join(downhill_lines[cand_start:cand_end]),
                    },
                )
                if len(probes) >= max_probes:
                    return probes
        patched_lines = downhill_lines[:j1] + base_lines[i1:i2] + downhill_lines[j2:]
        add_probe(
            label=f"source-hunk-revert-{index}",
            operator="source-hunk-subtractive-repair",
            description=(
                "Revert one downhill source hunk while preserving the rest "
                "of the candidate source chain."
            ),
            patched_function="".join(patched_lines),
            provenance={
                "repair_action": "revert-hunk",
                "hunk_index": index,
                "diff_tag": tag,
                "base_line_range": [i1 + 1, i2],
                "candidate_line_range": [j1 + 1, j2],
                "base_hunk": "".join(base_lines[i1:i2]),
                "candidate_hunk": "".join(downhill_lines[j1:j2]),
            },
        )
        if len(probes) >= max_probes:
            return probes

    type_pairs = (("u8", "int"), ("int", "u8"))
    for index, _tag, _i1, _i2, j1, j2 in changed_hunks:
        for line_index in range(j1, j2):
            line = downhill_lines[line_index]
            for from_type, to_type in type_pairs:
                pattern = re.compile(
                    rf"(?P<prefix>\b){re.escape(from_type)}"
                    r"(?P<suffix>\s+[A-Za-z_]\w*\s*=)"
                )
                match = pattern.search(line)
                if match is None:
                    continue
                patched_line = (
                    line[:match.start()]
                    + match.group("prefix")
                    + to_type
                    + match.group("suffix")
                    + line[match.end():]
                )
                patched_lines = list(downhill_lines)
                patched_lines[line_index] = patched_line
                add_probe(
                    label=f"source-hunk-type-{from_type}-to-{to_type}-{index}",
                    operator="source-hunk-type-variant",
                    description=(
                        "Vary the declaration type inside a downhill source "
                        "hunk without changing the rest of the candidate."
                    ),
                    patched_function="".join(patched_lines),
                    provenance={
                        "repair_action": "type-variant",
                        "hunk_index": index,
                        "candidate_line": line_index + 1,
                        "from_type": from_type,
                        "to_type": to_type,
                        "candidate_hunk": "".join(downhill_lines[j1:j2]),
                    },
                )
                if len(probes) >= max_probes:
                    return probes
    return probes










def _select_order_candidate_residual_first_divergence(
    *,
    variant: dict,
    candidate_pcdump: str,
    function: str,
    class_id: int,
    force_phys: Mapping[int, int],
    source_retained: str | None = None,
) -> dict:
    from ...mwcc_debug import first_divergence as fd

    try:
        events = parse_hook_events(candidate_pcdump)
        fev = find_function(events, function)
        if fev is None:
            return {
                "status": "abstain",
                "reason": f"function {function!r} not found in candidate pcdump",
                "candidate_label": variant.get("label"),
                "rank": variant.get("rank"),
                "class_id": class_id,
                "force_phys": {str(k): v for k, v in sorted(force_phys.items())},
                "source_retained": source_retained,
            }
        target = fd.TargetColoring(class_id=class_id, force_phys=dict(force_phys))
        report = fd.analyze_first_divergence(fev, target)
    except Exception as exc:
        return {
            "status": "abstain",
            "reason": f"{type(exc).__name__}: {exc}",
            "candidate_label": variant.get("label"),
            "rank": variant.get("rank"),
            "class_id": class_id,
            "force_phys": {str(k): v for k, v in sorted(force_phys.items())},
            "source_retained": source_retained,
        }

    source_text = ""
    if source_retained:
        retained_path = Path(source_retained)
        if retained_path.exists():
            try:
                source_text = retained_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception:
                source_text = ""
    pre_pass = None
    try:
        fn = next(
            (item for item in parse_pcdump(candidate_pcdump) if item.name == function),
            None,
        )
        if fn is not None:
            pre_pass = fn.last_precolor_pass()
    except Exception:
        pre_pass = None
    try:
        source_ideas = fd.attach_source_ideas(
            report.fact,
            source_text,
            function,
            pre_pass,
        )
    except Exception:
        source_ideas = None

    fact = report.fact
    source_payload = _select_order_source_idea_payload(source_ideas)
    source_idea_list = (
        source_payload.get("ideas") if isinstance(source_payload, dict) else None
    ) or []
    next_source_lever = (
        source_idea_list[0]
        if source_idea_list
        else getattr(fact, "local_target", None)
    )
    objective = variant.get("objective") or {}
    return {
        "status": "ok",
        "candidate_label": variant.get("label"),
        "rank": variant.get("rank"),
        "class_id": class_id,
        "force_phys": {str(k): v for k, v in sorted(force_phys.items())},
        "source_retained": source_retained,
        "objective": objective,
        "opcode_shape_preserved": objective.get("opcode_shape_preserved"),
        "frame_delta": objective.get("frame_delta"),
        "next_source_lever": next_source_lever,
        "first_divergence": {
            "candidate_label": variant.get("label"),
            "rank": variant.get("rank"),
            "case": getattr(fact.case, "value", str(fact.case)),
            "ig_idx": fact.ig_idx,
            "iter_idx": fact.iter_idx,
            "baseline_reg": fact.baseline_reg,
            "target_reg": fact.target_reg,
            "coalesced_nodes": list(fact.coalesced_nodes),
            "coalesced_root": fact.coalesced_root,
            "coalesced_root_phys": fact.coalesced_root_phys,
            "blocker_ig": fact.blocker_ig,
            "blocker_dependency": fact.blocker_dependency,
            "working_mask": (
                sorted(fact.working_mask)
                if fact.working_mask is not None else None
            ),
            "cap_hit": fact.cap_hit,
            "earlier_unmapped_warning": fact.earlier_unmapped_warning,
            "local_target": fact.local_target,
        },
        "source_ideas": source_payload,
    }
























































def _select_order_guard_repair_candidate_summary(
    variant: Mapping[str, Any],
) -> dict[str, Any] | None:
    if variant.get("status") != "ok":
        return None
    objective = variant.get("objective")
    guard = variant.get("structural_guard")
    if not isinstance(objective, Mapping) or not isinstance(guard, Mapping):
        return None
    if guard.get("accepted") is not False:
        return None
    hit_count = objective.get("force_phys_satisfied_count")
    if not isinstance(hit_count, int) or hit_count <= 0:
        return None
    normalized_diff_lines = guard.get("normalized_diff_lines")
    frame_delta = guard.get("frame_delta")
    if frame_delta is None:
        frame_delta = objective.get("frame_delta")
    return {
        "label": variant.get("label"),
        "rank": variant.get("rank"),
        "path": variant.get("path"),
        "source_retained": variant.get("source_retained"),
        "chain": list(variant.get("chain") or []),
        "match_percent": objective.get("match_percent"),
        "force_phys_satisfied_count": hit_count,
        "force_phys_distance": objective.get("force_phys_distance"),
        "achieved_registers": _select_order_force_phys_hit_registers(variant),
        "missing_registers": _select_order_force_phys_missing_registers(objective),
        "mismatched_registers": (
            _select_order_force_phys_mismatched_registers(objective)
        ),
        "guard": dict(guard),
        "checkdiff_drift": _select_order_checkdiff_drift_summary(
            variant.get("_checkdiff_payload")
        ),
        "normalized_diff_lines": normalized_diff_lines,
        "opcode_similarity": guard.get("opcode_similarity"),
        "frame_delta": frame_delta,
        "source_hunk": variant.get("source_hunk"),
        "probe": variant.get("probe"),
        "spill_delta": _select_order_spill_delta(variant),
        "saved_register_delta": _select_order_saved_register_delta(variant),
    }














































def _select_order_materializable_targeted_interference_delta(
    plan: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    return _select_order_materialized_targeted_interference_delta(plan)




























































































def _select_order_guard_repair_reconciliation_frontier_entry(
    variant: Mapping[str, Any],
    *,
    function: str | None,
    class_id: int,
    candidate_source: str,
    force_phys: Mapping[int, int],
    protected_hits: Mapping[str, int],
    complement_targets: Mapping[str, Mapping[str, Any]],
    repair_seed_label: str,
    depth: int,
    window_order_source_attributions: (
        Mapping[int, Any] | Mapping[str, Any] | None
    ) = None,
    window_order_probe_diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    protected_complement = _select_order_guard_repair_entry_protected_complement(
        variant,
        force_phys=force_phys,
        protected_hits=protected_hits,
        complement_targets=complement_targets,
    )
    if protected_complement is None:
        return None
    candidate = protected_complement.get("candidate")
    if not isinstance(candidate, Mapping):
        return None
    if int(candidate.get("complement_hit_count") or 0) <= 0:
        return None
    lost_protected = candidate.get("lost_protected_registers")
    if not isinstance(lost_protected, Mapping) or not lost_protected:
        return None
    achieved_hits = _select_order_force_phys_hit_registers(variant)
    if not achieved_hits:
        return None
    result_summary = _select_order_guard_repair_result_summary(variant)
    if result_summary is None:
        return None
    next_targets = _select_order_complement_target_summary(
        force_phys=force_phys,
        seed_candidate=result_summary,
        protected_registers=achieved_hits,
    )
    if not next_targets:
        return None
    candidate_targets = candidate.get("complement_targets")
    hit_complement_targets = {
        str(ig_idx): dict(target)
        for ig_idx, target in (
            candidate_targets.items()
            if isinstance(candidate_targets, Mapping) else []
        )
        if isinstance(target, Mapping) and target.get("status") == "hit"
    }
    targeted_targets = dict(hit_complement_targets)
    for ig_idx, expected in dict(lost_protected or {}).items():
        targeted_targets[str(ig_idx)] = {
            "expected": expected,
            "actual": candidate.get("achieved_registers", {}).get(str(ig_idx))
            if isinstance(candidate.get("achieved_registers"), Mapping)
            else None,
            "status": "lost-protected",
        }
    complement_source_diagnostics = _select_order_complement_source_diagnostics(
        complement_targets=targeted_targets,
        window_order_source_attributions=window_order_source_attributions,
        window_order_probe_diagnostics=window_order_probe_diagnostics,
    )
    targeted_interference_plan = _select_order_targeted_interference_transform_plan(
        function=function,
        class_id=class_id,
        candidate=candidate,
        protected_registers=protected_hits,
        complement_targets=targeted_targets,
        complement_source_diagnostics=complement_source_diagnostics,
    )
    preserved_original = {
        str(ig_idx): int(phys)
        for ig_idx, phys in protected_hits.items()
        if achieved_hits.get(str(ig_idx)) == int(phys)
    }
    label = str(variant.get("label") or "")
    metadata = {
        "source_label": label,
        "repair_seed_label": repair_seed_label,
        "source_retained": variant.get("source_retained") or variant.get("path"),
        "chain": list(variant.get("chain") or []),
        "depth_promoted_from": depth,
        "depth_promoted_to": depth + 1,
        "selection_reason": (
            "complement-hit candidate lost protected force-phys hits; "
            "promote it as a reconciliation seed"
        ),
        "original_protected_force_phys_hits": dict(protected_hits),
        "preserved_original_protected_hits": preserved_original,
        "lost_protected_registers": dict(lost_protected),
        "hit_complement_targets": hit_complement_targets,
        "achieved_force_phys_hits": dict(achieved_hits),
        "protected_force_phys_hits": dict(achieved_hits),
        "protected_complement_targets": next_targets,
        "candidate": dict(candidate),
    }
    if targeted_interference_plan is not None:
        metadata["targeted_interference_source_transforms"] = (
            targeted_interference_plan
        )
    return {
        "frontier": {
            "label": label,
            "repair_seed_label": repair_seed_label,
            "source_text": candidate_source,
            "chain": list(variant.get("chain") or []),
            "protected_hits": achieved_hits,
            "protected_complement_targets": next_targets,
            "reconciliation_seed": metadata,
            "targeted_interference_source_transforms": (
                targeted_interference_plan
            ),
        },
        "ledger": metadata,
    }


def _select_order_guard_repair_summary(
    ranked_variants: list[dict],
    *,
    force_phys: Mapping[int, int],
    target_orders: list[tuple[int, int]] | None = None,
    max_lanes: int = 4,
    max_candidates_per_lane: int = 3,
    guard_repair_ledger: object | None = None,
    function: str | None = None,
    class_id: int = 0,
    window_order_source_attributions: (
        Mapping[int, Any] | Mapping[str, Any] | None
    ) = None,
    window_order_probe_diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not force_phys:
        return {"status": "not-requested", "lanes": []}

    lanes_by_kind: dict[str, list[dict[str, Any]]] = {}
    repair_candidates: list[dict[str, Any]] = []
    seed_candidates: list[dict[str, Any]] = []
    seed_count = 0
    for variant in ranked_variants:
        repair_candidate = _select_order_guard_repair_result_summary(variant)
        if repair_candidate is not None:
            repair_candidates.append(repair_candidate)
        candidate = _select_order_guard_repair_candidate_summary(variant)
        if candidate is None:
            continue
        objective = variant.get("objective")
        guard = variant.get("structural_guard")
        if not isinstance(objective, Mapping) or not isinstance(guard, Mapping):
            continue
        kind = _select_order_guard_repair_kind(guard, objective)
        lanes_by_kind.setdefault(kind, []).append(candidate)
        seed_candidates.append(candidate)
        seed_count += 1

    lanes: list[dict[str, Any]] = []
    for kind, candidates in lanes_by_kind.items():
        candidates.sort(key=_select_order_guard_repair_candidate_sort_key)
        lane_candidates = candidates[:max_candidates_per_lane]
        best = lane_candidates[0] if lane_candidates else {}
        lanes.append({
            "kind": kind,
            "guard_class": kind,
            "seed_count": len(candidates),
            "best_force_phys_satisfied_count": best.get(
                "force_phys_satisfied_count"
            ),
            "best_force_phys_distance": best.get("force_phys_distance"),
            "best_match_percent": best.get("match_percent"),
            "repair_action": _select_order_guard_repair_action(kind),
            "inline_boundary_drift": (
                _select_order_inline_boundary_drift_summary(
                    best,
                    function=function,
                    force_phys=force_phys,
                    target_orders=target_orders,
                )
                if kind == "inline-boundary-toolchain-artifact" else None
            ),
            "candidates": lane_candidates,
        })
    lanes.sort(
        key=lambda lane: _select_order_guard_repair_candidate_sort_key(
            {
                "force_phys_satisfied_count": lane.get(
                    "best_force_phys_satisfied_count"
                ),
                "force_phys_distance": lane.get("best_force_phys_distance"),
                "match_percent": lane.get("best_match_percent"),
            }
        )
    )
    lanes = lanes[:max_lanes]

    def _repair_preserves_protected(candidate: Mapping[str, Any]) -> bool:
        protected_count = candidate.get("protected_register_count")
        preserved_count = candidate.get("protected_preserved_count")
        if protected_count is None and preserved_count is None:
            return True
        return protected_count == preserved_count

    repair_found = any(
        candidate.get("guard_accepted") is True
        and candidate.get("force_phys_satisfied_count", 0) > 0
        and _repair_preserves_protected(candidate)
        for candidate in repair_candidates
    )
    summary = {
        "status": (
            "repair-found"
            if repair_found
            else ("needs-repair" if lanes else "no-guarded-allocator-hit")
        ),
        "seed_count": seed_count,
        "repair_entry_count": len(repair_candidates),
        "repair_candidates": repair_candidates[:8],
        "lanes": lanes,
    }
    downhill_complement = _select_order_downhill_complement_summary(
        seed_candidates,
        repair_candidates,
    )
    if downhill_complement is not None:
        summary["downhill_complement"] = downhill_complement
    protected_complement = _select_order_protected_complement_summary(
        seed_candidates,
        repair_candidates,
        force_phys=force_phys,
        function=function,
        class_id=class_id,
        window_order_source_attributions=window_order_source_attributions,
        window_order_probe_diagnostics=window_order_probe_diagnostics,
        guard_repair_ledger=guard_repair_ledger,
    )
    if protected_complement is not None:
        summary["protected_complement_repair"] = protected_complement
    protected_plateau = _select_order_protected_structural_plateau_summary(
        seed_candidates,
        repair_candidates,
        force_phys=force_phys,
        guard_repair_ledger=guard_repair_ledger,
    )
    if protected_plateau is not None:
        summary["protected_structural_plateau"] = protected_plateau
    if guard_repair_ledger is not None:
        summary["guard_repair_ledger"] = str(guard_repair_ledger)
    return summary




















































def _select_order_source_bridge_summary(
    *,
    ranked_variants: list[Mapping[str, Any]],
    force_phys: Mapping[int, int],
    window_order_fallback: Mapping[str, Any] | None,
    window_order_source_attributions: Mapping[int, Any] | Mapping[str, Any],
    window_order_probe_diagnostics: Mapping[str, Any],
    diagnostic_buckets: Mapping[str, list[Mapping[str, Any]]],
    function: str | None = None,
    base_source_path: Path | str | None = None,
    campaign_dir: Path | str | None = None,
) -> dict[str, Any]:
    fallback_pcdump_path = (
        window_order_fallback.get("pcdump_path")
        or window_order_fallback.get("pcdump")
        if isinstance(window_order_fallback, Mapping)
        else None
    )
    fallback_pcdump_source = (
        window_order_fallback.get("pcdump_source")
        if isinstance(window_order_fallback, Mapping)
        else None
    )
    fallback_target_source = (
        window_order_fallback.get("target_source")
        if isinstance(window_order_fallback, Mapping)
        else None
    )
    if not force_phys:
        return {
            "status": "not-requested",
            "dominant_blocker": None,
            "leads": [],
            "blocker_classes": [],
            "ranked_actions": [],
            "window_order_fallback_pcdump_path": fallback_pcdump_path,
            "window_order_fallback_pcdump_source": fallback_pcdump_source,
            "window_order_fallback_target_source": fallback_target_source,
        }

    leads = _select_order_source_bridge_leads(
        window_order_fallback=window_order_fallback,
        window_order_source_attributions=window_order_source_attributions,
        window_order_probe_diagnostics=window_order_probe_diagnostics,
    )
    listed_source_probes = int(
        window_order_probe_diagnostics.get("listed_source_probes") or 0
    )
    terminal_owner_probe_summary = _select_order_terminal_owner_probe_summary(
        leads
    )
    def accepted_exact(variant: Mapping[str, Any]) -> bool:
        if variant.get("status") != "ok":
            return False
        objective = variant.get("objective")
        if not isinstance(objective, Mapping):
            return False
        if objective.get("force_phys_satisfied") is not True:
            return False
        guard = variant.get("structural_guard")
        return not isinstance(guard, Mapping) or guard.get("accepted") is not False

    has_exact = any(accepted_exact(variant) for variant in ranked_variants)
    target_order_actionability = _select_order_target_order_actionability(
        ranked_variants=ranked_variants,
        force_phys=force_phys,
        diagnostic_buckets=diagnostic_buckets,
    )
    blocker_classes: set[str] = set()
    variant_summaries: list[dict[str, Any]] = []
    for variant in ranked_variants:
        blockers = _select_order_source_bridge_blocker_classes(variant)
        blocker_classes.update(blockers)
        variant_summary = {
            "label": variant.get("label"),
            "rank": variant.get("rank"),
            "operator": variant.get("operator"),
            "path": variant.get("path"),
            "source_retained": variant.get("source_retained"),
            "pcdump_path": _select_order_variant_pcdump_path(variant),
            "blocker_classes": sorted(blockers),
            "registers": _select_order_source_bridge_variant_registers(variant),
            "guard": variant.get("structural_guard"),
        }
        target_score = _select_order_variant_target_score(variant)
        if target_score is not None:
            variant_summary["target_score"] = target_score
        variant_summaries.append(variant_summary)

    if target_order_actionability["all_baseline_satisfied"] and not (
        target_order_actionability["force_phys_hits"]
    ):
        blocker_classes.add("support-order-targets-already-satisfied")

    if has_exact:
        status = "resolved"
        dominant = "resolved"
    elif "support-order-targets-already-satisfied" in blocker_classes:
        status = "blocked"
        dominant = "support-order-targets-already-satisfied"
    elif (
        leads
        and listed_source_probes == 0
        and isinstance(terminal_owner_probe_summary, Mapping)
        and terminal_owner_probe_summary.get("materialized_candidates") == 0
    ):
        status = "blocked"
        owner_terminal_blocker = terminal_owner_probe_summary.get(
            "terminal_blocker"
        )
        dominant = (
            owner_terminal_blocker
            if isinstance(owner_terminal_blocker, str)
            else "ranked-owner-candidates-not-materializable"
        )
    elif leads and listed_source_probes == 0:
        status = "blocked"
        dominant = "window-order-leads-not-materialized"
    elif listed_source_probes > 0:
        status = "blocked"
        dominant = "source-probes-exhausted"
    elif not leads and blocker_classes <= {"wrong-register"}:
        status = "blocked"
        dominant = "terminal-allocator-ceiling"
    else:
        status = "blocked"
        dominant = _select_order_source_bridge_dominant_nonterminal_blocker(
            blocker_classes
        )

    actions: list[dict[str, Any]] = []
    for lead in leads:
        if lead.get("source_actionable"):
            action = {
                "kind": "try-window-order-source-move",
                "target_ig": lead.get("target_ig"),
                "source": lead.get("source"),
                "order_move": lead.get("order_move"),
                "probe_labels": list(lead.get("materialized_probe_labels") or []),
                "source_diff": lead.get("source_diff"),
            }
            probe_diag = lead.get("source_probe_diagnostic")
            if isinstance(probe_diag, Mapping):
                synthetic_probe = probe_diag.get("synthetic_source_probe")
                if isinstance(synthetic_probe, Mapping):
                    action["synthetic_source_probe"] = dict(synthetic_probe)
                synthetic_candidates = probe_diag.get("synthetic_source_candidates")
                if isinstance(synthetic_candidates, list):
                    action["synthetic_source_candidates"] = [
                        dict(item)
                        for item in synthetic_candidates
                        if isinstance(item, Mapping)
                    ]
                ranked_local = probe_diag.get(
                    "materialized_ranked_source_owner_candidates"
                )
                if isinstance(ranked_local, list):
                    action["materialized_ranked_source_owner_candidates"] = [
                        dict(item)
                        for item in ranked_local
                        if isinstance(item, Mapping)
                    ]
                ranked_indexed = probe_diag.get(
                    "materialized_ranked_indexed_byte_source_candidates"
                )
                if not isinstance(ranked_indexed, list) and isinstance(
                    synthetic_probe,
                    Mapping,
                ):
                    ranked_indexed = synthetic_probe.get(
                        "materialized_ranked_indexed_byte_source_candidates"
                    )
                if isinstance(ranked_indexed, list):
                    action["materialized_ranked_indexed_byte_source_candidates"] = [
                        dict(item)
                        for item in ranked_indexed
                        if isinstance(item, Mapping)
                    ]
                field_load = probe_diag.get("field_load_source_candidate")
                if isinstance(field_load, Mapping):
                    action["field_load_source_candidate"] = dict(field_load)
                field_load_candidates = probe_diag.get(
                    "materialized_field_load_source_candidates"
                )
                if isinstance(field_load_candidates, list):
                    action["materialized_field_load_source_candidates"] = [
                        dict(item)
                        for item in field_load_candidates
                        if isinstance(item, Mapping)
                    ]
                field_load_summary = probe_diag.get(
                    "field_load_materialization_summary"
                )
                if isinstance(field_load_summary, Mapping):
                    action["field_load_materialization_summary"] = dict(
                        field_load_summary
                    )
                source_hunks = probe_diag.get("source_hunks")
                if isinstance(source_hunks, list):
                    action["source_hunks"] = [
                        dict(item) if isinstance(item, Mapping) else item
                        for item in source_hunks
                    ]
            actions.append(action)
        elif lead.get("source_attributed"):
            actions.append({
                "kind": "inspect-window-order-source-mobility",
                "target_ig": lead.get("target_ig"),
                "source": lead.get("source"),
                "order_move": lead.get("order_move"),
                "terminal_blocker": lead.get("terminal_blocker"),
                "source_probe_diagnostic": lead.get("source_probe_diagnostic"),
                "reason": (
                    "window-order fallback lead has a source attribution, "
                    "but no safe window-order source probe materialized"
                ),
            })
    for blocker in sorted(blocker_classes):
        actions.append(_select_order_source_bridge_action_for_blocker(blocker))
    if dominant == "support-order-targets-already-satisfied":
        actions.insert(
            0,
            _select_order_already_satisfied_support_order_action(
                target_order_actionability
            ),
        )
    terminal_next_lane = _select_order_source_bridge_terminal_next_lane(
        ranked_variants=ranked_variants,
        leads=leads,
        force_phys=force_phys,
        function=function,
        base_source_path=base_source_path,
        campaign_dir=campaign_dir,
    )

    return {
        "status": status,
        "dominant_blocker": dominant,
        "leads": leads,
        "source_probe_diagnostics": dict(window_order_probe_diagnostics),
        "listed_source_probes": listed_source_probes,
        "source_attributed_leads": window_order_probe_diagnostics.get(
            "source_attributed_leads"
        ),
        "terminal_owner_probe_summary": terminal_owner_probe_summary,
        "diagnostic_bucket_counts": {
            key: len(value)
            for key, value in diagnostic_buckets.items()
        },
        "blocker_classes": sorted(blocker_classes),
        "target_order_actionability": target_order_actionability,
        "ranked_actions": actions,
        "terminal_next_lane": terminal_next_lane,
        "window_order_fallback_pcdump_path": fallback_pcdump_path,
        "window_order_fallback_pcdump_source": fallback_pcdump_source,
        "window_order_fallback_target_source": fallback_target_source,
        "variants": variant_summaries[:8],
    }














def _select_order_terminal_exhaustion_summary(
    *,
    ranked_variants: list[Mapping[str, Any]],
    force_phys: Mapping[int, int],
    blocker_targets: Iterable[int] | None,
    diagnostic_buckets: Mapping[str, list[Mapping[str, Any]]],
    source_bridge_summary: Mapping[str, Any] | None,
    timed_out: bool,
    class_id: int | None = None,
) -> dict[str, Any] | None:
    targets = _select_order_int_mapping(force_phys)
    if timed_out or not targets or not isinstance(source_bridge_summary, Mapping):
        return None
    if source_bridge_summary.get("status") != "blocked":
        return None

    for variant in ranked_variants:
        if variant.get("status") != "ok":
            continue
        objective = variant.get("objective")
        if isinstance(objective, Mapping) and (
            objective.get("force_phys_satisfied") is True
        ):
            return None

    normalized_blockers: set[int] = set()
    for target in blocker_targets or targets.keys():
        if isinstance(target, bool):
            continue
        if isinstance(target, int):
            candidate = target
        elif isinstance(target, str) and target.lstrip("-").isdigit():
            candidate = int(target)
        else:
            continue
        if candidate in targets:
            normalized_blockers.add(candidate)
    if not normalized_blockers:
        normalized_blockers = set(targets)
    empty_blockers = [
        target
        for target in sorted(normalized_blockers)
        if not diagnostic_buckets.get(f"force-phys-hit-{target}")
    ]
    if not empty_blockers:
        return None

    dominant_blocker = source_bridge_summary.get("dominant_blocker")
    dominant = (
        dominant_blocker if isinstance(dominant_blocker, str) else None
    ) or "source-probes-exhausted"
    blocker_classes = _select_order_terminal_summary_blocker_classes(
        dominant_blocker=dominant,
        source_bridge_summary=source_bridge_summary,
        class_id=class_id,
    )
    if "support-order-targets-already-satisfied" in blocker_classes:
        terminal_blocker = "support-order-targets-already-satisfied"
    elif "transform-family-exhausted" in blocker_classes:
        terminal_blocker = "transform-family-exhausted"
    elif "current-source-shape-allocator-ceiling" in blocker_classes:
        terminal_blocker = "current-source-shape-allocator-ceiling"
    else:
        terminal_blocker = dominant

    terminal_next_lane = source_bridge_summary.get("terminal_next_lane")
    actions = (
        terminal_next_lane.get("actions")
        if isinstance(terminal_next_lane, Mapping) else []
    )
    recombine_suggested = any(
        isinstance(action, Mapping)
        and action.get("kind") == "try-retained-variant-recombine"
        for action in (actions if isinstance(actions, list) else [])
    )
    next_source_levers = [
        "target-aware-live-range-anchor",
        "target-aware-interference-shape",
    ]
    if recombine_suggested:
        next_source_levers.insert(0, "manual-subhunk-recombine")

    best_retained = _select_order_terminal_summary_best_retained_variants(
        ranked_variants
    )
    target_score = next(
        (
            candidate.get("target_score")
            for candidate in best_retained
            if isinstance(candidate.get("target_score"), Mapping)
        ),
        None,
    )
    summary: dict[str, Any] = {
        "status": "blocked",
        "kind": (
            "degree-zero-fpr-case-c-source-exhaustion"
            if class_id == 1
            else "select-order-source-exhaustion"
        ),
        "dominant_blocker": dominant,
        "blocker_classes": blocker_classes,
        "terminal_blocker": terminal_blocker,
        "force_phys_targets": {
            str(key): targets[key] for key in sorted(targets)
        },
        "blocker_targets": empty_blockers,
        "diagnostic_bucket_counts": {
            key: len(value)
            for key, value in diagnostic_buckets.items()
        },
        "best_retained_variants": best_retained,
        "next_source_lever_classes": next_source_levers,
        "recombine_status": (
            "unverified" if recombine_suggested else "not-suggested"
        ),
    }
    if isinstance(target_score, Mapping):
        summary["target_score"] = dict(target_score)
    return summary


def _select_order_refresh_window_order_probe_diagnostics(
    diagnostics: Mapping[str, Any],
    variants: list[Mapping[str, Any]],
) -> dict[str, Any]:
    refreshed = dict(diagnostics)
    labels: set[str] = set()
    attempted_labels: set[str] = set()
    for variant in variants:
        probe = variant.get("probe")
        if not isinstance(probe, Mapping):
            continue
        if probe.get("operator") != "window-order-source-steering":
            continue
        label = variant.get("label") or probe.get("label")
        if isinstance(label, str):
            attempted_labels.add(label)
        if variant.get("status") != "ok":
            continue
        if not isinstance(variant.get("source_retained"), str):
            continue
        if _select_order_variant_pcdump_path(variant) is None:
            continue
        if _select_order_variant_target_score(variant) is None:
            continue
        if isinstance(label, str):
            labels.add(label)
    if attempted_labels:
        refreshed["attempted_window_order_source_probes"] = len(attempted_labels)
        refreshed["attempted_window_order_source_probe_labels"] = sorted(
            attempted_labels
        )
    if labels:
        refreshed["listed_source_probes"] = max(
            int(refreshed.get("listed_source_probes") or 0),
            len(attempted_labels) or len(labels),
        )
        refreshed["scored_window_order_source_probes"] = len(labels)
        refreshed["scored_window_order_source_probe_labels"] = sorted(labels)
        lead_diagnostics = refreshed.get("lead_diagnostics")
        if isinstance(lead_diagnostics, list):
            updated_leads: list[dict[str, Any]] = []
            for item in lead_diagnostics:
                if not isinstance(item, Mapping):
                    continue
                lead = dict(item)
                materialized = [
                    label for label in lead.get("materialized_probe_labels") or []
                    if isinstance(label, str)
                ]
                scored = sorted(label for label in materialized if label in labels)
                if scored:
                    lead["scored_probe_labels"] = scored
                updated_leads.append(lead)
            refreshed["lead_diagnostics"] = updated_leads
    else:
        refreshed.setdefault("scored_window_order_source_probes", 0)
        refreshed.setdefault("scored_window_order_source_probe_labels", [])
    return refreshed




def _select_order_diagnostic_buckets(
    ranked_variants: list[dict],
    *,
    force_phys: Mapping[int, int],
    function: str | None = None,
    global_top: list[Mapping[str, Any]] | None = None,
    max_per_bucket: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    if not force_phys:
        return {}

    standard_keys = [
        "global-top",
        "best-exact-distance",
        "best-one-target-hits",
        "best-opcode-frame-preserving",
        "best-frame-preserving-only",
        *[f"force-phys-hit-{ig_idx}" for ig_idx in sorted(force_phys)],
    ]
    buckets: dict[str, list[dict[str, Any]]] = {
        key: [] for key in standard_keys
    }

    def add(bucket: str, variant: Mapping[str, Any]) -> None:
        entries = buckets.setdefault(bucket, [])
        label = variant.get("label")
        if any(entry.get("label") == label for entry in entries):
            return
        if len(entries) >= max_per_bucket:
            return
        objective = variant.get("objective")
        probe = variant.get("probe")
        entry = {
            "label": label,
            "rank": variant.get("rank"),
            "chain": list(variant.get("chain") or []),
            "path": variant.get("path"),
            "source_retained": variant.get("source_retained"),
            "probe": dict(probe) if isinstance(probe, Mapping) else None,
            "source_hunk": _select_order_variant_source_hunk(
                variant,
                function=function,
            ),
            "force_phys_satisfied_count": (
                objective.get("force_phys_satisfied_count")
                if isinstance(objective, Mapping) else None
            ),
            "force_phys_distance": (
                objective.get("force_phys_distance")
                if isinstance(objective, Mapping) else None
            ),
            "opcode_shape_preserved": (
                objective.get("opcode_shape_preserved")
                if isinstance(objective, Mapping) else None
            ),
            "frame_delta": (
                objective.get("frame_delta")
                if isinstance(objective, Mapping) else None
            ),
        }
        target_score = _select_order_variant_target_score(variant)
        if target_score is not None:
            entry["target_score"] = target_score
        entries.append(entry)

    for variant in global_top or []:
        add("global-top", variant)
    for variant in ranked_variants:
        if variant.get("status") != "ok":
            continue
        objective = variant.get("objective")
        if not isinstance(objective, Mapping):
            continue
        if objective.get("force_phys_distance") == 0:
            add("best-exact-distance", variant)
        hits = _select_order_force_phys_hits(variant)
        if len(hits) == 1:
            add("best-one-target-hits", variant)
        if objective.get("opcode_shape_preserved") is True and (
            _select_order_frame_preserved(objective)
        ):
            add("best-opcode-frame-preserving", variant)
        elif _select_order_frame_preserved(objective):
            add("best-frame-preserving-only", variant)
        for ig_idx in sorted(hits):
            add(f"force-phys-hit-{ig_idx}", variant)

    return buckets










def _select_order_source_attributions_for_leads(
    *,
    pcdump_text: str,
    function: str,
    class_id: int,
    source_text: str | None,
    source_file: str | None,
    fallback: Mapping[str, Any] | None,
    extra_virtuals: Iterable[int] = (),
) -> dict[int, Any]:
    if source_text is None:
        return {}
    leads = fallback.get("leads") if isinstance(fallback, Mapping) else []
    if not isinstance(leads, list):
        leads = []
    virtuals: list[int] = []
    for lead in leads:
        if not isinstance(lead, Mapping):
            continue
        try:
            virtuals.append(int(lead["target_ig"]))
        except (KeyError, TypeError, ValueError):
            continue
    for virtual in extra_virtuals:
        if isinstance(virtual, bool):
            continue
        try:
            virtuals.append(int(virtual))
        except (TypeError, ValueError):
            continue
    if not virtuals:
        return {}
    reg_class = "fpr" if class_id == 1 else "gpr"
    try:
        from ...mwcc_debug.virtual_attribution import explain_virtuals
        from ...search.solver import probe as solver_probe

        def load_attrs(requested_virtuals: list[int]) -> dict[int, Any]:
            unique_virtuals = tuple(dict.fromkeys(requested_virtuals))
            report = explain_virtuals(
                pcdump_text,
                function,
                virtuals=unique_virtuals,
                source_text=source_text,
                source_file=source_file,
                reg_class=reg_class,
            )
            out: dict[int, Any] = {}
            for target_ig in unique_virtuals:
                source = solver_probe.source_attr_of(report, target_ig)
                if source is not None:
                    out[target_ig] = source
            return out

        attrs = load_attrs(virtuals)
        operand_virtuals: list[int] = []
        for source in attrs.values():
            source_dict = _solve_source_attribution_dict(source) or {}
            if source_dict.get("kind") not in {
                "implicit-temp",
                "fpr-temp",
                "copy/coalesce-product",
            }:
                continue
            operand_virtuals.extend(
                _select_order_virtual_operands_from_expression(
                    source_dict.get("expression")
                )
            )
        new_operands = [
            virtual for virtual in operand_virtuals
            if virtual not in set(virtuals)
        ]
        if new_operands:
            virtuals.extend(new_operands)
            try:
                attrs = load_attrs(virtuals)
            except Exception:
                return attrs
        return attrs
    except Exception:
        return {}


def _select_order_augmented_window_order_leads(
    fallback_leads: object,
    *,
    force_phys: Mapping[int, int] | Mapping[str, int],
    class_id: int,
    source_attributions: Mapping[int, Any] | Mapping[str, Any],
    priority_targets: Iterable[int] = (),
) -> list[dict[str, Any]]:
    leads = (
        [
            dict(lead)
            for lead in fallback_leads
            if isinstance(lead, Mapping)
        ]
        if isinstance(fallback_leads, list)
        else []
    )
    present_targets = {
        int(lead["target_ig"])
        for lead in leads
        if not isinstance(lead.get("target_ig"), bool)
        and str(lead.get("target_ig", "")).lstrip("-").isdigit()
    }
    reg_prefix = "f" if class_id == 1 else "r"
    for target_ig, target_reg in sorted(
        _select_order_int_mapping(force_phys).items()
    ):
        if target_ig in present_targets:
            continue
        source = _solve_source_attribution_dict(
            _select_order_source_attr_for_ig(source_attributions, target_ig)
        )
        if not source or source.get("kind") not in {"implicit-temp", "fpr-temp"}:
            continue
        leads.append({
            "target_ig": target_ig,
            "observed_reg": None,
            "predicted_reg": None,
            "perturbed_reg": target_reg,
            "order_move": ["before", "force-phys"],
            "degree": None,
            "move_distance": None,
            "already_target": False,
            "checkdiff_target_reg": target_reg,
            "checkdiff_target_reg_name": f"{reg_prefix}{target_reg}",
            "source": "force-phys-attributed-temp",
            "reason": (
                "force-phys target has synthetic source attribution but was "
                "absent from window-order fallback leads"
            ),
        })
        present_targets.add(target_ig)
    priority_order = {
        int(target_ig): index
        for index, target_ig in enumerate(priority_targets)
        if not isinstance(target_ig, bool)
    }
    if priority_order:
        def lead_priority(lead: Mapping[str, Any]) -> tuple[int, int]:
            raw_target = lead.get("target_ig")
            try:
                target_ig = int(raw_target)
            except (TypeError, ValueError):
                return (1, len(priority_order))
            if target_ig in priority_order:
                return (0, priority_order[target_ig])
            return (1, len(priority_order))

        leads.sort(key=lead_priority)
    return leads

































def _register_tiebreak_window_order_fallback(
    *,
    function: str,
    class_id: int,
    max_leads: int = 5,
    pcdump_path: Path | None = None,
    pcdump_text: str | None = None,
    allow_auto_pcdump: bool = True,
    pcdump_source: str | None = None,
    force_phys: Mapping[int, int] | Mapping[str, int] | None = None,
) -> dict:
    from ...mwcc_debug import tiebreak as tb

    try:
        resolved_pcdump_path: Path | None = None
        if pcdump_text is None:
            if pcdump_path is not None:
                resolved_pcdump_path = _resolve_pcdump_path(
                    pcdump_path,
                    function,
                    DEFAULT_MELEE_ROOT,
                )
            elif allow_auto_pcdump:
                resolved_pcdump_path = _resolve_pcdump_path(
                    None,
                    function,
                    DEFAULT_MELEE_ROOT,
                )
                pcdump_source = pcdump_source or "auto-cache"
            else:
                return {
                    "ran": False,
                    "reason": (
                        "window-order fallback requires a pcdump; auto cache "
                        "resolution is disabled for this retained-artifact "
                        "planning run"
                    ),
                    "pcdump": None,
                    "pcdump_path": None,
                    "pcdump_source": "unavailable",
                    "target_source": None,
                    "leads": [],
                }
            pcdump_text = resolved_pcdump_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        else:
            resolved_pcdump_path = pcdump_path
        if pcdump_source is None:
            if resolved_pcdump_path is None:
                pcdump_source = "provided-text"
            else:
                pcdump_source = "command-baseline"
        ig = tb.load_ig(
            pcdump_text,
            function,
            class_id=class_id,
            fallback_first=False,
        )
        if ig is None:
            return {
                "ran": False,
                "reason": f"no class {class_id} COLORGRAPH section",
                "leads": [],
            }
        g1 = tb.validate_g1(ig, function)
        truncated = sum(1 for node in ig.nodes.values() if node.incomplete)
        if g1.rate < 1.0 or truncated:
            return {
                "ran": False,
                "reason": "G1 imperfect or truncated; what-ifs untrustworthy",
                "g1_rate": g1.rate,
                "truncated_nodes": truncated,
                "leads": [],
            }

        fns = parse_pcdump(pcdump_text)
        fn = next((item for item in fns if item.name == function), None)
        if fn is None or fn.last_precolor_pass() is None:
            return {
                "ran": False,
                "reason": "pre-coloring pass missing",
                "leads": [],
            }
        events_fn = find_function(parse_hook_events(pcdump_text), function)
        explicit_force_phys = _select_order_int_mapping(force_phys or {})
        if explicit_force_phys:
            vector_targets = _register_tiebreak_force_phys_vector_targets(
                ig,
                explicit_force_phys,
                class_id=class_id,
            )
            checkdiff_source = None
            desired_regs: set[int] = set()
            target_source = "explicit-force-phys"
        else:
            checkdiff_payload, checkdiff_source = _read_force_phys_checkdiff_payload(
                function=function,
                melee_root=DEFAULT_MELEE_ROOT,
                checkdiff_json=None,
                checkdiff_timeout=60.0,
            )
            target_asm = _checkdiff_asm_lines(checkdiff_payload, "target_asm")
            current_asm = _checkdiff_asm_lines(checkdiff_payload, "current_asm")
            vector = _derive_force_phys_from_register_diff_lines(
                target_asm,
                current_asm,
                fn.last_precolor_pass(),
                events_fn,
            )
            vector_targets = list(vector.get("targets", []))
            classification = checkdiff_payload.get("classification")
            desired_regs = _register_window_rotation_desired_regs(
                classification,
                class_id=class_id,
            )
            target_source = "checkdiff"
        if not desired_regs and class_id == 0:
            desired_regs = set(range(23, 32))
        leads = _register_tiebreak_order_flip_leads(
            tb,
            ig,
            vector_targets=vector_targets,
            desired_regs=desired_regs,
            max_leads=max_leads,
        )
        return {
            "ran": True,
            "reason": (
                "window-order fallback leads found"
                if leads else "no window-order fallback lead found"
            ),
            "g1_rate": g1.rate,
            "truncated_nodes": truncated,
            "pcdump": (
                str(resolved_pcdump_path)
                if resolved_pcdump_path is not None
                else None
            ),
            "pcdump_path": (
                str(resolved_pcdump_path)
                if resolved_pcdump_path is not None
                else None
            ),
            "pcdump_source": pcdump_source,
            "target_source": target_source,
            "checkdiff_source": checkdiff_source,
            "desired_regs": sorted(desired_regs),
            "leads": leads,
        }
    except Exception as exc:
        return {
            "ran": False,
            "reason": str(exc),
            "leads": [],
        }






def _run_solve_coloring(*, function: str, class_id: int, pcdump,
                        max_perturb: int, frontier: int, kinds: list,
                        experimental_kinds: list, catalog_dir,
                        force_vector_probes: bool = False,
                        force_vector_timeout: float | None = None,
                        retain_force_vector_pcdumps: bool = False,
                        allow_unreachable_order: bool = False):
    """Live collaborator wiring for solve_coloring. Monkeypatched in unit
    tests; exercised at the Task-18 pilots."""
    from src.mwcc_debug import tiebreak as tb
    from src.mwcc_debug.order_target_derive import REGISTER_ONLY_PRIMARIES
    from src.mwcc_debug.virtual_attribution import explain_virtuals
    from src.search.solver import probe as solver_probe
    from src.search.solver.enumerate import (
        EnumConfig, enumerate_with_escalation, implicated_nodes,
        normalize_kinds,
    )
    from src.search.solver.realize import assemble_realized, load_catalog
    from src.search.solver.solve import Preconditions, SolveResult, solve_coloring
    from src.search.solver.validity import passes_1_5_filter
    from src.search.solver.win_fixture import is_register_only_admission

    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    pcdump_text = pcdump_path.read_text(encoding="utf-8")
    tu_c = melee_root / "src" / f"{unit}.c" if unit else None
    source_text = tu_c.read_text(encoding="utf-8") if tu_c and tu_c.exists() else ""

    # #619: admission keys on the COMPUTED direct-evidence register-only
    # property, not the checkdiff PRIMARY label (8024227C is `register-allocation`
    # yet a provable pure permutation). The gate reuses win_fixture's T10d
    # direct-evidence verdict over the SAME masked normalization the live
    # checkdiff classification uses; the label stays a fast-path hint.
    normalize_fn = _load_checkdiff_normalized_structural_lines(melee_root)

    def _register_only_gate(primary, target_asm, current_asm):
        return is_register_only_admission(
            primary, target_asm, current_asm,
            normalized_structural_lines=normalize_fn)

    inputs = _collect_order_target_inputs(
        function=function, unit=unit, class_id=class_id,
        melee_root=melee_root, checkdiff_timeout=120.0,
        register_only_gate=_register_only_gate,
        force_vector_probes=force_vector_probes,
        force_vector_timeout=force_vector_timeout,
        retain_force_vector_pcdumps=retain_force_vector_pcdumps,
        # #705 enabled the not-register-only node-set-delta fallback for FPR
        # (class 1); #714 extends it to GPR (class 0) so structurally-different-
        # virtual GPR residuals that are not register-only (e.g.
        # mnDiagram_80242C0C) also emit a worksheet instead of a bare abstain.
        node_set_delta_fallback=(class_id in (0, 1)))
    phys_target = {int(k): int(v) for k, v in inputs.phys_target.items()}
    try:
        normalized_kinds = normalize_kinds(kinds)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--kinds") from exc
    order_only = normalized_kinds == ("order",)
    ig = tb.load_ig(pcdump_text, function, class_id=class_id)
    g1 = tb.validate_g1(ig, function) if ig else None
    truncated = bool(ig and any(n.incomplete for n in ig.nodes.values()))

    report = None
    conflict_igs = {
        ig_idx
        for conflict in inputs.phys_conflicts
        for ig_idx in [_solve_conflict_ig_idx(conflict)]
        if ig_idx is not None
    }
    report_igs = set(phys_target) | conflict_igs
    if ig is not None and report_igs:
        impl = implicated_nodes(ig, phys_target) | report_igs
        report = explain_virtuals(
            pcdump_text, function, virtuals=sorted(impl),
            source_text=source_text,
            source_file=str(tu_c) if tu_c is not None else None,
            reg_class="fp" if class_id == 1 else "gpr")
    node_set_delta = _derive_node_set_delta_payload(
        function=function,
        class_id=class_id,
        ig=ig,
        phys_target=phys_target,
        phys_conflicts=list(inputs.phys_conflicts),
        report=report,
        coupled_residual=getattr(inputs, "coupled_residual", None),
    )
    solver_diagnostics = _solve_force_vector_diagnostics(
        class_id=class_id,
        phys_target=phys_target,
        force_vector_probe=getattr(inputs, "force_vector_probe", None),
        natural_pcdump=(
            Path(getattr(inputs, "natural_pcdump"))
            if getattr(inputs, "natural_pcdump", None)
            else pcdump_path
        ),
    )

    def preconditions_fn(**k):
        # #619: register_only is the COMPUTED direct-evidence verdict the gate
        # recorded; fall back to the label only if the gate was bypassed
        # (direct_evidence_register_only is None).
        computed = inputs.direct_evidence_register_only
        register_only = (computed if computed is not None
                         else inputs.checkdiff_primary in REGISTER_ONLY_PRIMARIES)
        force_phys_collision = bool(inputs.phys_conflicts)
        forced_clean = bool(getattr(inputs, "forced_class_clean", False))
        recoverable_order_collision = order_only and (
            force_phys_collision
            or (allow_unreachable_order and bool(phys_target) and not forced_clean)
        )
        return Preconditions(
            register_only=register_only,
            reachable=forced_clean and not force_phys_collision,
            g1_rate=(g1.rate if g1 else 0.0),
            phys_target=phys_target,
            g1_truncated=truncated,
            force_phys_collision=force_phys_collision,
            recoverable_order_collision=recoverable_order_collision,
            node_set_delta=node_set_delta,
            solver_diagnostics=solver_diagnostics)

    def enumerate_fn(**k):
        cfg = EnumConfig(frontier=frontier, kinds=normalized_kinds)
        return enumerate_with_escalation(
            ig, phys_target, config=cfg, filter_fn=passes_1_5_filter,
            probe_ctx_fn=_solver_probe_ctx_factory(ig, report, phys_target),
            actionable_fn=lambda hit: hit.get("actionable", False))

    def realize_fn(*, enum_out, **k):
        return assemble_realized(
            enum_out, phys_target=phys_target,
            catalog=load_catalog(catalog_dir),
            source_lookup=lambda ig_idx: solver_probe.source_object_of(report,
                                                                       ig_idx))

    # kinds/experimental_kinds: the advertised default is the full default set;
    # a non-default --kinds restricts enumeration (see the plan's note).
    return solve_coloring(function=function, class_id=class_id,
                          preconditions_fn=preconditions_fn,
                          enumerate_fn=enumerate_fn, realize_fn=realize_fn,
                          max_perturb=max_perturb, frontier=frontier)


def _node_set_split_compile_signature(
    path: Path,
    *,
    label: str,
    function: str,
    class_id: int,
    melee_root: Path,
    timeout: int,
    unit_source: Path | None = None,
    full_unit_source: bool = False,
):
    """Compile a source variant and return its allocator signature."""
    compiled = _node_set_split_compile_signature_and_pcdump(
        path,
        label=label,
        function=function,
        class_id=class_id,
        melee_root=melee_root,
        timeout=timeout,
        unit_source=unit_source,
        full_unit_source=full_unit_source,
    )
    if isinstance(compiled, tuple) and len(compiled) == 2:
        signature, _pcdump_text = compiled
        return signature
    return compiled




def _node_set_split_signature_from_pcdump_text(
    pcdump_text: str,
    *,
    function: str,
    class_id: int,
):
    from ...mwcc_debug.simplify_search import baseline_signature

    events = find_function(parse_hook_events(pcdump_text), function)
    if events is None:
        raise ValueError(f"compiled pcdump has no events for {function}")
    return baseline_signature(events, class_id=class_id)


def _score_node_set_split_candidate(
    patch,
    *,
    function: str,
    source_path: Path,
    baseline_pct: float | None,
    melee_root: Path,
    timeout: float | None,
    temp_dir: Path,
    deadline: float | None = None,
    full_unit_source: bool = False,
):
    """Score a node-set split patch against the real tree and restore it."""
    from ...mwcc_debug.source_shape import CandidateScore

    candidate_path = temp_dir / f"{_safe_filename(patch.candidate_id)}.c"
    try:
        candidate_path.write_text(patch.patched_source, encoding="utf-8")
        score = _score_source_candidate_real_tree(
            candidate_path,
            function=function,
            melee_root=melee_root,
            timeout=timeout,
            deadline=deadline,
            status=None,
            full_unit_source=full_unit_source,
        )
    except Exception as exc:
        return CandidateScore(
            patch.candidate_id,
            compile_ok=False,
            checkdiff_pct=None,
            checkdiff_delta=None,
            pcdump_score_delta=None,
            diagnostics_path=None,
            status="score-failed",
            score_reason=str(exc),
        )

    match_percent = score.match_percent
    if match_percent is None:
        return CandidateScore(
            patch.candidate_id,
            compile_ok=False,
            checkdiff_pct=None,
            checkdiff_delta=None,
            pcdump_score_delta=None,
            diagnostics_path=None,
            status="build-failed",
            score_reason=score.match_percent_error,
        )
    delta = None if baseline_pct is None else match_percent - baseline_pct
    return CandidateScore(
        patch.candidate_id,
        compile_ok=True,
        checkdiff_pct=match_percent,
        checkdiff_delta=delta,
        pcdump_score_delta=None,
        diagnostics_path=None,
        status="scored",
        score_reason=score.match_percent_error,
        checkdiff_baseline_pct=baseline_pct,
    )






def _fresh_node_set_split_source_baseline_pct(
    *,
    source_path: Path,
    unit: str,
    function: str,
    melee_root: Path,
    timeout: float | None = None,
    deadline: float | None = None,
    compile_unit_source: Path,
) -> tuple[float | None, str | None]:
    if _same_filesystem_path(source_path, compile_unit_source):
        return _fresh_node_set_split_baseline_pct(
            unit=unit,
            function=function,
            melee_root=melee_root,
            timeout=timeout,
            deadline=deadline,
        )
    try:
        score = _score_source_candidate_real_tree(
            source_path,
            function=function,
            melee_root=melee_root,
            timeout=timeout,
            deadline=deadline,
            status=None,
            full_unit_source=True,
        )
    except Exception as exc:
        return None, str(exc)
    return score.match_percent, score.match_percent_error


def _apply_node_set_split_patch(
    patch,
    *,
    function: str,
    unit: str,
    source_path: Path,
    melee_root: Path,
    timeout: float | None,
    deadline: float | None = None,
    full_unit_source: bool = False,
) -> tuple[float | None, str | None]:
    """Apply one verified patch to the real source and leave it built."""
    with _acquire_source_score_repo_lock(melee_root):
        original = source_path.read_text(encoding="utf-8")
        if full_unit_source:
            if find_source_function(patch.patched_source, function) is None:
                return None, f"function not found in candidate source: {function}"
            source_path.write_text(patch.patched_source, encoding="utf-8")
        elif transfer_candidate(patch.patched_source, source_path, function) is None:
            return None, f"function not found in candidate source: {function}"

        obj_path = f"build/GALE01/src/{unit}.o"
        keep_patched_source = False
        applied_pct: float | None = None
        apply_error: str | None = None
        try:
            build_timeout, deadline_error = _timeout_before_deadline(
                deadline,
                timeout,
                f"building {obj_path}",
            )
            if deadline_error is not None:
                apply_error = deadline_error
            else:
                build_result, retried = _run_ninja_with_no_diag_retry(
                    ["ninja", obj_path],
                    melee_root,
                    timeout=build_timeout,
                )
                if build_result.returncode != 0:
                    apply_error = _failure_diagnostic_or_fallback(
                        build_result.stdout,
                        build_result.stderr,
                        fallback=(
                            f"ninja {obj_path} failed with exit "
                            f"{build_result.returncode}"
                            + (" after retry" if retried else "")
                        ),
                    )
                else:
                    refresh_timeout, deadline_error = _timeout_before_deadline(
                        deadline,
                        timeout,
                        "refreshing report.json",
                    )
                    if deadline_error is not None:
                        apply_error = deadline_error
                    else:
                        applied_pct, diagnostic = (
                            _refresh_match_pct_after_successful_build(
                                unit,
                                function,
                                melee_root=melee_root,
                                timeout=refresh_timeout,
                                deadline=deadline,
                            )
                        )
                        if applied_pct is None:
                            apply_error = diagnostic
                        else:
                            keep_patched_source = True
        except Exception as exc:
            apply_error = str(exc)
        finally:
            if (
                not keep_patched_source
                and source_path.read_text(encoding="utf-8") != original
            ):
                source_path.write_text(original, encoding="utf-8")
                restore_timeout, deadline_error = _timeout_before_deadline(
                    deadline,
                    timeout,
                    "restoring object/report after failed node-set-split apply",
                )
                if deadline_error is not None:
                    restore_diag = deadline_error
                    restore_proc = None
                else:
                    restore_proc, _planned_steps = _restore_object_report_for_unit(
                        unit=unit,
                        melee_root=melee_root,
                        timeout_s=float(restore_timeout or 0.0),
                        max_steps=64,
                        force=False,
                    )
                    restore_diag = None
                if restore_proc is not None and restore_proc.returncode != 0:
                    restore_diag = _failure_diagnostic_or_fallback(
                        restore_proc.stdout,
                        restore_proc.stderr,
                        fallback=(
                            "failed to restore object/report after failed "
                            "node-set-split apply"
                        ),
                    )
                if restore_diag is not None:
                    if apply_error:
                        apply_error = f"{apply_error}\nrestore failed: {restore_diag}"
                    else:
                        apply_error = f"restore failed: {restore_diag}"
        return applied_pct, apply_error










def _node_set_split_steering_children(
    patch,
    *,
    function: str,
    unit: str,
    coupled_requests: list[Any] | None,
    seen_sources: set[str],
    objective: Mapping[str, Any] | None = None,
    max_per_family: int = 2,
):
    """Generate one bounded coloring-steering layer on top of a split patch."""
    if (
        coupled_requests is None
        or "+steer-" in patch.candidate_id
        or "+target-color-" in patch.candidate_id
    ):
        return []
    force_phys = _node_set_split_force_phys_from_requests(coupled_requests)
    if not force_phys:
        return []

    from ...mwcc_debug.source_shape import CandidatePatch
    from ...mwcc_debug.pressure_explorer import generate_lifetime_layout_probes
    from ...mwcc_debug.diff_capture import function_pcdump_aliases
    from ...search.directed import transform_corpus

    children = []
    lead_target_orders: list[tuple[int, int]] = []
    if isinstance(objective, Mapping):
        for lead in objective.get("target_color_select_order_leads") or []:
            if not isinstance(lead, Mapping):
                continue
            target_order = lead.get("target_order")
            if (
                isinstance(target_order, list)
                and len(target_order) == 2
                and all(isinstance(item, int) for item in target_order)
            ):
                pair = (int(target_order[0]), int(target_order[1]))
                if pair not in lead_target_orders:
                    lead_target_orders.append(pair)

    if lead_target_orders:
        probes = generate_lifetime_layout_probes(
            patch.patched_source,
            function,
            max_probes=max(max_per_family, min(max_per_family * 4, 16)),
        )
        for probe_index, probe in enumerate(probes):
            candidate_text = getattr(probe, "source_text", None)
            if not candidate_text or candidate_text == patch.patched_source:
                continue
            if candidate_text in seen_sources:
                continue
            seen_sources.add(candidate_text)
            lead_first, lead_second = lead_target_orders[
                probe_index % len(lead_target_orders)
            ]
            probe_label = getattr(probe, "label", "probe")
            operator = getattr(probe, "operator", "unknown")
            order_label = f"r{lead_first}<r{lead_second}"
            order_fragment = _safe_filename(order_label)
            candidate_id = (
                f"{patch.candidate_id}+target-color-{order_fragment}-"
                f"{_safe_filename(str(probe_label))}"
            )
            children.append(
                CandidatePatch(
                    candidate_id=candidate_id,
                    patched_source=candidate_text,
                    summary=(
                        f"{patch.summary}; target-color select-order "
                        f"{order_label} via {operator}"
                    ),
                    touched_ranges=((0, len(patch.patched_source)),),
                    hunk=_node_set_split_source_hunk(
                        patch.patched_source,
                        candidate_text,
                        candidate_id,
                    ),
                )
            )
            if len(children) >= max_per_family:
                return children

    target_names = _node_set_split_request_var_names(coupled_requests)
    probe_budget = max(max_per_family, min(max_per_family * 8, 32))
    probes = transform_corpus.generate_transform_probes(
        patch.patched_source,
        function=function,
        unit=unit,
        force_phys=force_phys,
        function_aliases=function_pcdump_aliases(function, _compute_melee_root()),
        families=("coloring_register_steering",),
        max_per_family=probe_budget,
        node_set_delta=None,
    )
    for probe in probes:
        candidate_text = getattr(probe, "candidate_text", None)
        if not candidate_text or candidate_text == patch.patched_source:
            continue
        if not _node_set_split_probe_mentions_target(
            probe,
            source_text=patch.patched_source,
            candidate_text=candidate_text,
            target_names=target_names,
        ):
            continue
        if candidate_text in seen_sources:
            continue
        seen_sources.add(candidate_text)
        probe_id = getattr(probe, "probe_id", "probe")
        mutator_key = getattr(probe, "mutator_key", "unknown")
        candidate_id = f"{patch.candidate_id}+steer-{probe_id}"
        children.append(
            CandidatePatch(
                candidate_id=candidate_id,
                patched_source=candidate_text,
                summary=(
                    f"{patch.summary}; coloring steering {mutator_key} "
                    f"after wrong-register split"
                ),
                touched_ranges=((0, len(patch.patched_source)),),
                hunk=_node_set_split_source_hunk(
                    patch.patched_source,
                    candidate_text,
                    candidate_id,
                ),
            )
        )
        if len(children) >= max_per_family:
            break
    return children












def _probe_requires_full_unit_source(probe: Any) -> bool:
    if isinstance(probe, Mapping):
        provenance = probe.get("provenance")
        if not isinstance(provenance, Mapping):
            provenance = probe
    else:
        provenance = getattr(probe, "provenance", None)
    if not isinstance(provenance, Mapping):
        return False
    if bool(provenance.get("requires_full_unit_source")):
        return True
    payload = provenance.get("payload")
    return isinstance(payload, Mapping) and bool(
        payload.get("requires_full_unit_source")
    )




def _append_transform_corpus_probes(
    probes: list[Any],
    *,
    source_text: str | None,
    function: str,
    unit: str | None,
    include: bool,
    families: list[str] | None,
    force_phys: str | None,
    max_probes: int,
    default_families: tuple[str, ...] = (),
    node_set_delta: Mapping[str, Any] | None = None,
) -> list[Any]:
    enabled = include or bool(families) or node_set_delta is not None
    if not enabled:
        return probes

    from ...search.directed.transform_corpus import generate_transform_probes
    from ...mwcc_debug.diff_capture import function_pcdump_aliases
    from ...search.directed.transform_probe_adapter import (
        TransformProbeConfigError,
        adapted_transform_lifetime_probes,
        normalize_transform_families,
        parse_transform_force_phys,
    )

    try:
        requested_families = normalize_transform_families(families)
        if not requested_families and default_families:
            requested_families = normalize_transform_families(default_families)
        force_map = parse_transform_force_phys(force_phys)
    except TransformProbeConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if source_text is None or len(probes) >= max_probes:
        return probes

    generated = generate_transform_probes(
        source_text,
        function=function,
        unit=unit or "unknown",
        force_phys=force_map,
        function_aliases=function_pcdump_aliases(function, _compute_melee_root()),
        families=requested_families,
        max_per_family=max(1, max_probes),
        node_set_delta=node_set_delta,
    )
    remaining = max(0, max_probes - len(probes))
    probes.extend(adapted_transform_lifetime_probes(
        generated,
        families=requested_families,
        max_probes=remaining,
    ))
    return probes








@dataclasses.dataclass(frozen=True)
class _PointerLocalDecl:
    name: str
    type_text: str
    initializer: str | None
    line_no: int


@dataclasses.dataclass(frozen=True)
class _PointerResetUse:
    from_local: str
    to_local: str
    from_type: str
    to_type: str
    base_expr: str | None
    line_start: int
    line_end: int
    line_no: int
    indent: str
    reset_text: str
    for_start: int | None = None
    for_header_start: int | None = None
    for_header_end: int | None = None
    for_close: int | None = None
    for_text: str | None = None


def _coalesce_find_matching(
    source: str,
    open_idx: int,
    *,
    open_char: str,
    close_char: str,
) -> int | None:
    depth = 0
    idx = open_idx
    while idx < len(source):
        char = source[idx]
        nxt = source[idx + 1] if idx + 1 < len(source) else ""
        if char == "/" and nxt == "/":
            newline = source.find("\n", idx + 2)
            if newline < 0:
                return None
            idx = newline + 1
            continue
        if char == "/" and nxt == "*":
            end = source.find("*/", idx + 2)
            if end < 0:
                return None
            idx = end + 2
            continue
        if char in {"'", '"'}:
            quote = char
            idx += 1
            escaped = False
            while idx < len(source):
                current = source[idx]
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    idx += 1
                    break
                idx += 1
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return idx
        idx += 1
    return None






def _coalesce_safe_pointer_base_expr(expr: str | None) -> str | None:
    if expr is None:
        return None
    expr = expr.strip()
    if not expr:
        return None
    if any(token in expr for token in ("++", "--", "?", ",", ";")):
        return None
    if re.search(r"(?<![=!<>])=(?!=)", expr):
        return None
    if re.search(r"\b[A-Za-z_]\w*\s*\(", expr):
        return None
    return expr


def _coalesce_pointer_reset_source_hunk(
    source: str,
    *,
    start: int,
    end: int,
    replacement: str,
) -> dict[str, Any]:
    return {
        "line_start": _coalesce_line_no(source, start),
        "line_end": _coalesce_line_no(source, max(start, end - 1)),
        "original": source[start:end],
        "replacement": replacement,
    }


def _coalesce_replace_source_hunk(
    source: str,
    *,
    start: int,
    end: int,
    replacement: str,
) -> str:
    return source[:start] + replacement + source[end:]


def _coalesce_pointer_local_decls(
    source: str,
    *,
    body_start: int,
    body_end: int,
) -> dict[str, _PointerLocalDecl]:
    body = source[body_start:body_end]
    decls: dict[str, _PointerLocalDecl] = {}
    decl_re = re.compile(
        r"(?m)^(?P<indent>[ \t]*)"
        r"(?P<type>(?:const\s+|volatile\s+|static\s+|register\s+)*"
        r"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w*)"
        r"(?:\s+[A-Za-z_]\w*)*\s*\*+)\s*"
        r"(?P<name>[A-Za-z_]\w*)\s*"
        r"(?:=\s*(?P<init>[^;\n]+))?\s*;\s*$"
    )
    for match in decl_re.finditer(body):
        type_text = re.sub(r"\s+", " ", match.group("type")).strip()
        type_text = re.sub(r"\s*\*\s*", "*", type_text)
        name = match.group("name")
        decls[name] = _PointerLocalDecl(
            name=name,
            type_text=type_text,
            initializer=(
                None if match.group("init") is None else match.group("init").strip()
            ),
            line_no=_coalesce_line_no(source, body_start + match.start()),
        )
    return decls


def _coalesce_next_for_after_reset(
    source: str,
    *,
    body_end: int,
    reset_end: int,
    to_local: str,
) -> tuple[int, int, int, int, str] | None:
    cursor = reset_end
    skipped_setup = 0
    while cursor < body_end:
        line_start = cursor
        line_end = source.find("\n", line_start, body_end)
        if line_end < 0:
            line_end = body_end
        line = source[line_start:line_end]
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            cursor = min(line_end + 1, body_end)
            continue
        setup_match = re.fullmatch(
            r"(?P<lhs>[A-Za-z_]\w*)\s*=\s*[^;]+;",
            stripped,
        )
        if setup_match is not None and not re.search(
            rf"\b{re.escape(to_local)}\b",
            stripped,
        ):
            skipped_setup += 1
            if skipped_setup > 3:
                return None
            cursor = min(line_end + 1, body_end)
            continue
        if not re.match(r"[ \t]*for\s*\(", line):
            return None
        open_paren = source.find("(", line_start, body_end)
        if open_paren < 0:
            return None
        close_paren = _coalesce_find_matching(
            source,
            open_paren,
            open_char="(",
            close_char=")",
        )
        if close_paren is None or close_paren > body_end:
            return None
        header = source[open_paren + 1:close_paren]
        if re.search(rf"\b{re.escape(to_local)}\s*(?:\+\+|\+=\s*1)", header) is None:
            return None
        open_brace = source.find("{", close_paren, body_end)
        if open_brace < 0:
            return None
        close_brace = _coalesce_find_matching(
            source,
            open_brace,
            open_char="{",
            close_char="}",
        )
        if close_brace is None or close_brace > body_end:
            return None
        return line_start, open_paren + 1, close_paren, close_brace, header
    return None


def _coalesce_for_header_can_reset_pointer(
    source: str,
    *,
    for_start: int,
    for_close: int,
) -> bool:
    loop_text = source[for_start:for_close + 1]
    if re.search(r"(?m)^[ \t]*#", loop_text):
        return False
    if re.search(r"\b(?:continue|goto)\s*;", loop_text):
        return False
    if re.search(r"(?m)^[ \t]*[A-Za-z_]\w*\s*:", loop_text):
        return False
    return True


def _coalesce_split_for_clauses(header: str) -> list[str] | None:
    clauses: list[str] = []
    start = 0
    depth = 0
    for idx, char in enumerate(header):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            clauses.append(header[start:idx])
            start = idx + 1
    clauses.append(header[start:])
    if len(clauses) != 3:
        return None
    return clauses


def _copy_survived_source_local_pair(
    trace_target: Mapping[str, Any],
) -> tuple[str | None, str | None, str | None, str | None]:
    from_operand = trace_target.get("from_operand")
    to_operand = trace_target.get("to_operand")
    if not isinstance(from_operand, Mapping):
        from_operand = {}
    if not isinstance(to_operand, Mapping):
        to_operand = {}
    return (
        _coalesce_simple_identifier(from_operand.get("source_local")),
        _coalesce_simple_identifier(to_operand.get("source_local")),
        (
            str(from_operand.get("source_type")).strip()
            if isinstance(from_operand.get("source_type"), str)
            else None
        ),
        (
            str(to_operand.get("source_type")).strip()
            if isinstance(to_operand.get("source_type"), str)
            else None
        ),
    )


def _find_copy_survived_pointer_resets(
    source_text: str,
    function: str,
    trace_target: Mapping[str, Any],
) -> list[_PointerResetUse]:
    if trace_target.get("register_class") not in {None, "gpr"}:
        return []
    span = _coalesce_find_function_body_span(source_text, function)
    if span is None:
        return []
    body_start, body_end = span
    body = source_text[body_start:body_end]
    decls = _coalesce_pointer_local_decls(
        source_text,
        body_start=body_start,
        body_end=body_end,
    )
    target_from, target_to, target_from_type, target_to_type = (
        _copy_survived_source_local_pair(trace_target)
    )
    reset_re = re.compile(
        r"(?m)^(?P<indent>[ \t]*)"
        r"(?P<to>[A-Za-z_]\w*)\s*=\s*(?P<from>[A-Za-z_]\w*)\s*;\s*$"
    )
    resets: list[_PointerResetUse] = []
    for match in reset_re.finditer(body):
        from_local = match.group("from")
        to_local = match.group("to")
        if target_from is not None and from_local != target_from:
            continue
        if target_to is not None and to_local != target_to:
            continue
        from_decl = decls.get(from_local)
        to_decl = decls.get(to_local)
        if from_decl is None and target_from_type is None:
            continue
        if to_decl is None and target_to_type is None:
            continue
        from_type = target_from_type or (from_decl.type_text if from_decl else None)
        to_type = target_to_type or (to_decl.type_text if to_decl else None)
        if not from_type or not to_type or "*" not in from_type or "*" not in to_type:
            continue
        abs_start = body_start + match.start()
        abs_end = body_start + match.end()
        if abs_end < len(source_text) and source_text[abs_end] == "\n":
            abs_end += 1
        base_expr = _coalesce_safe_pointer_base_expr(
            None if from_decl is None else from_decl.initializer
        )
        next_for = _coalesce_next_for_after_reset(
            source_text,
            body_end=body_end,
            reset_end=abs_end,
            to_local=to_local,
        )
        resets.append(_PointerResetUse(
            from_local=from_local,
            to_local=to_local,
            from_type=from_type,
            to_type=to_type,
            base_expr=base_expr,
            line_start=abs_start,
            line_end=abs_end,
            line_no=_coalesce_line_no(source_text, abs_start),
            indent=match.group("indent"),
            reset_text=source_text[abs_start:abs_end],
            for_start=None if next_for is None else next_for[0],
            for_header_start=None if next_for is None else next_for[1],
            for_header_end=None if next_for is None else next_for[2],
            for_close=None if next_for is None else next_for[3],
            for_text=None if next_for is None else next_for[4],
        ))
    explicit_target = target_from is not None or target_to is not None
    if explicit_target:
        return resets
    # Keep earlier and later resets visible under small budgets by preserving
    # source order and round-robining variants across resets in the generator.
    return resets


def _copy_survived_pointer_reset_provenance(
    use: _PointerResetUse,
    variant: str,
    source_hunk: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "kind": "copy-survived-pointer-reset",
        "variant": variant,
        "from_local": use.from_local,
        "to_local": use.to_local,
        "from_type": use.from_type,
        "to_type": use.to_type,
        "base_expr": use.base_expr,
        "line": use.line_no,
        "source_hunk": dict(source_hunk),
    }


def _copy_survived_pointer_reset_variants(
    source_text: str,
    use: _PointerResetUse,
    *,
    index: int,
) -> list[Any]:
    from ...mwcc_debug.pressure_explorer import LifetimeLayoutProbe

    variants: list[LifetimeLayoutProbe] = []

    def append_probe(
        *,
        variant: str,
        description: str,
        start: int,
        end: int,
        replacement: str,
    ) -> None:
        hunk = _coalesce_pointer_reset_source_hunk(
            source_text,
            start=start,
            end=end,
            replacement=replacement,
        )
        variants.append(LifetimeLayoutProbe(
            label=f"copy-survived-pointer-reset-{variant}-{index}",
            operator="copy-survived-pointer-reset",
            description=description,
            source_text=_coalesce_replace_source_hunk(
                source_text,
                start=start,
                end=end,
                replacement=replacement,
            ),
            provenance=_copy_survived_pointer_reset_provenance(use, variant, hunk),
        ))

    if use.base_expr is not None:
        append_probe(
            variant="direct-base",
            description=(
                f"Reset `{use.to_local}` directly from base `{use.base_expr}` "
                f"instead of copying `{use.from_local}`."
            ),
            start=use.line_start,
            end=use.line_end,
            replacement=f"{use.indent}{use.to_local} = {use.base_expr};\n",
        )

    alias_name = "ll_probe_iter_0"
    append_probe(
        variant="fresh-alias",
        description=(
            f"Introduce `{alias_name}` between `{use.from_local}` and "
            f"`{use.to_local}` at the pointer reset."
        ),
        start=use.line_start,
        end=use.line_end,
        replacement=(
            f"{use.indent}{use.from_type} {alias_name} = {use.from_local};\n"
            f"{use.indent}{use.to_local} = {alias_name};\n"
        ),
    )

    append_probe(
        variant="block-split",
        description=(
            f"Split the `{use.from_local}` -> `{use.to_local}` reset through "
            "a scoped pointer alias."
        ),
        start=use.line_start,
        end=use.line_end,
        replacement=(
            f"{use.indent}{{\n"
            f"{use.indent}    {use.from_type} {alias_name} = {use.from_local};\n"
            f"{use.indent}    {use.to_local} = {alias_name};\n"
            f"{use.indent}}}\n"
        ),
    )

    if (
        use.for_start is not None
        and use.for_header_start is not None
        and use.for_header_end is not None
        and use.for_close is not None
        and use.for_text is not None
        and _coalesce_for_header_can_reset_pointer(
            source_text,
            for_start=use.for_start,
            for_close=use.for_close,
        )
    ):
        clauses = _coalesce_split_for_clauses(use.for_text)
        if clauses is not None:
            reset_expr = (
                f"{use.to_local} = {use.base_expr or use.from_local}"
            )
            init = clauses[0].strip()
            clauses[0] = f"{init}, {reset_expr}" if init else reset_expr
            replacement = (
                source_text[use.line_end:use.for_header_start]
                + "; ".join(clause.strip() for clause in clauses)
            )
            append_probe(
                variant="for-init",
                description=(
                    f"Move the `{use.to_local}` reset into the following "
                    "pointer-walk loop initializer."
                ),
                start=use.line_start,
                end=use.for_header_end,
                replacement=replacement,
            )

    return variants




def _coalesce_assigned_regs_from_pcdump(
    pcdump_text: str,
    function: str,
    *,
    class_id: int,
) -> dict[int, int]:
    try:
        events = find_function(parse_hook_events(pcdump_text), function)
    except Exception:
        return {}
    if events is None:
        return {}
    matching = [
        section for section in events.colorgraph_sections
        if section.class_id == class_id
    ]
    if not matching:
        return {}
    return {
        decision.ig_idx: decision.assigned_reg
        for decision in matching[-1].decisions
        if decision.ig_idx >= 0
    }




# ---------------------------------------------------------------------------
# Helpers that physically live here (NOT in inspect.py) because tests patch
# them via ``monkeypatch.setattr(debug_cli, "_h", ...)`` AND they are called
# from inside inspect.py command handlers. Keeping the definition in __init__
# ensures the patch (which rebinds the name in this namespace) reaches the
# inspect.py call sites, which reach these via call-time deferred import.
# ---------------------------------------------------------------------------
def _derive_force_phys_from_register_diff_lines(
    target_asm: list[str],
    current_asm: list[str],
    pre_pass,
    events: FunctionEvents | None,
) -> dict:
    target_instructions: list[AsmInstruction] = []
    target_by_line: dict[int, tuple[int, AsmInstruction]] = {}
    target_entries: list[tuple[int, int, AsmInstruction, str]] = []
    for line_index, line in enumerate(target_asm):
        instruction = _parse_checkdiff_asm_instruction(line)
        if instruction is None:
            continue
        target_by_line[line_index] = (len(target_instructions), instruction)
        target_entries.append((
            line_index,
            len(target_instructions),
            instruction,
            line,
        ))
        target_instructions.append(instruction)

    current_entries: list[tuple[int, int, AsmInstruction, str]] = []
    for line_index, line in enumerate(current_asm):
        instruction = _parse_checkdiff_asm_instruction(line)
        if instruction is None:
            continue
        current_entries.append((
            line_index,
            len(current_entries),
            instruction,
            line,
        ))

    prologue_end = asm_parse_prologue_end(target_instructions)
    target_frame_size = _checkdiff_frame_size(target_asm)
    current_frame_size = _checkdiff_frame_size(current_asm)
    frame_delta = (
        target_frame_size - current_frame_size
        if target_frame_size is not None and current_frame_size is not None
        else None
    )
    current_stack_delta = frame_delta or 0
    use_frame_alignment = current_stack_delta != 0
    paired_lines: list[
        tuple[int, str, str, AsmInstruction, AsmInstruction, int]
    ] = []

    if use_frame_alignment:
        unused_current = list(current_entries)
        for (
            target_line_index,
            target_instruction_index,
            target_instruction,
            target_line,
        ) in target_entries:
            target_sig = _checkdiff_instruction_signature(target_instruction)
            ranked: list[
                tuple[int, int, str, AsmInstruction, int]
            ] = []
            for current_pos, (
                current_line_index,
                current_instruction_index,
                current_instruction,
                current_line,
            ) in enumerate(unused_current):
                current_sig = _checkdiff_instruction_signature(
                    current_instruction,
                    stack_delta=current_stack_delta,
                )
                if current_sig != target_sig:
                    continue
                ranked.append((
                    abs(current_instruction_index - target_instruction_index),
                    current_pos,
                    current_line,
                    current_instruction,
                    current_instruction_index,
                ))
            if not ranked:
                continue
            (
                _distance,
                current_pos,
                current_line,
                current_instruction,
                _current_instruction_index,
            ) = sorted(ranked, key=lambda item: (item[0], item[1]))[0]
            unused_current.pop(current_pos)
            paired_lines.append((
                target_line_index,
                target_line,
                current_line,
                target_instruction,
                current_instruction,
                target_instruction_index,
            ))
    else:
        for line_index, (target_line, current_line) in enumerate(
            zip(target_asm, current_asm)
        ):
            target_instruction = _parse_checkdiff_asm_instruction(target_line)
            current_instruction = _parse_checkdiff_asm_instruction(current_line)
            if target_instruction is None or current_instruction is None:
                continue
            target_position = target_by_line.get(line_index)
            if target_position is None:
                continue
            instruction_index, _ = target_position
            paired_lines.append((
                line_index,
                target_line,
                current_line,
                target_instruction,
                current_instruction,
                instruction_index,
            ))

    target_order: list[tuple[int, str, int, int]] = []
    target_data: dict[tuple[int, str, int, int], dict] = {}
    conflicts: list[dict] = []

    for (
        line_index,
        target_line,
        current_line,
        target_instruction,
        current_instruction,
        instruction_index,
    ) in paired_lines:
        if target_line == current_line:
            continue
        if _checkdiff_instruction_signature(
            target_instruction,
        ) != _checkdiff_instruction_signature(
            current_instruction,
            stack_delta=current_stack_delta,
        ):
            continue
        target_dest = _asm_instruction_destination(target_instruction)
        current_dest = _asm_instruction_destination(current_instruction)
        if target_dest is None or target_dest == current_dest:
            continue
        kind, phys = target_dest
        class_id = _match_iter_first_class_id(kind)
        if class_id is None:
            continue
        if instruction_index < prologue_end:
            continue
        current_kind, current_phys = current_dest
        if current_kind != kind:
            continue
        match = _match_virtual_for_register_diff(
            expected_ist=target_instruction,
            expected_position=instruction_index - prologue_end,
            pre_pass=pre_pass,
            reg_kind=kind,
            current_phys=current_phys,
            events=events,
        )
        if match is None:
            continue

        conflict_key = (class_id, kind, match.ig_idx)
        existing_for_ig = [
            key for key in target_order
            if key[:3] == conflict_key and key[3] != phys
        ]
        if existing_for_ig:
            conflicts.append({
                "class_id": class_id,
                "kind": kind,
                "ig_idx": match.ig_idx,
                "existing_phys": existing_for_ig[0][3],
                "conflicting_phys": phys,
                "line_index": line_index,
                "target_asm": target_line,
                "current_asm": current_line,
            })
            continue

        key = (class_id, kind, match.ig_idx, phys)
        if key not in target_data:
            current_reg = _current_colorgraph_reg(
                events,
                class_id=class_id,
                ig_idx=match.ig_idx,
            )
            force_phys_entry = f"{class_id}:{match.ig_idx}:{phys}"
            force_vector_entry = (
                f"class{class_id}:ig{match.ig_idx}:phys={kind}{phys}"
            )
            target_data[key] = {
                "class_id": class_id,
                "kind": kind,
                "ig_idx": match.ig_idx,
                "target_reg": phys,
                "target_reg_name": f"{kind}{phys}",
                "current_reg": current_reg,
                "current_reg_name": (
                    f"{kind}{current_reg}"
                    if isinstance(current_reg, int) else None
                ),
                "already_target": (
                    current_reg == phys if isinstance(current_reg, int) else None
                ),
                "force_phys_entry": force_phys_entry,
                "force_vector_entry": force_vector_entry,
                "occurrences": [],
            }
            target_order.append(key)
        target_data[key]["occurrences"].append({
            "line_index": line_index,
            "target_asm": target_line,
            "current_asm": current_line,
            "opcode": target_instruction.opcode,
            "operands": target_instruction.operands,
            "instruction_index": match.instruction_index,
            "confidence": match.confidence,
        })

    targets: list[dict] = []
    for key in target_order:
        target = dict(target_data[key])
        occurrences = target["occurrences"]
        target["occurrence_count"] = len(occurrences)
        occurrence_confidences = {
            item["confidence"] for item in occurrences
        }
        if "ambiguous" in occurrence_confidences:
            target["confidence"] = "ambiguous"
        elif "current-reg" in occurrence_confidences:
            target["confidence"] = "current-reg"
        else:
            target["confidence"] = "exact"
        targets.append(target)

    conflict_keys = {
        (
            int(conflict["class_id"]),
            str(conflict["kind"]),
            int(conflict["ig_idx"]),
        )
        for conflict in conflicts
    }
    for target in targets:
        conflict_key = (
            int(target["class_id"]),
            str(target["kind"]),
            int(target["ig_idx"]),
        )
        target["force_vector_runnable"] = conflict_key not in conflict_keys

    runnable_targets = [
        target for target in targets if target["force_vector_runnable"]
    ]
    actionability = _target_vector_actionability(targets)

    return {
        "force_phys": {
            str(target["ig_idx"]): target["target_reg"]
            for target in runnable_targets
        },
        "force_phys_csv": ",".join(
            target["force_phys_entry"] for target in runnable_targets
        ),
        "force_vector": ",".join(
            target["force_vector_entry"] for target in runnable_targets
        ),
        "targets": targets,
        "conflicts": conflicts,
        "register_only_target_count": sum(
            target["occurrence_count"] for target in targets
        ),
        "actionability": actionability,
        "force_vector_recommended": (
            actionability.get("status") not in {
                "already-satisfied",
                "no-runnable-targets",
            }
        ),
        "frame_alignment": {
            "target_frame_size": target_frame_size,
            "current_frame_size": current_frame_size,
            "frame_delta": frame_delta,
            "applied": use_frame_alignment,
        },
    }


def _run_force_vector_auto_verify(
    *,
    src_path: Path,
    function: str,
    entries: list[_ForceVectorEntry],
    melee_root: Path,
    checkdiff_timeout: float = 60.0,
    run_diagnostic_probes: bool = True,
    per_probe_timeout_s: Optional[float] = None,
    env: Optional[dict[str, str]] = None,
    retain_pcdumps: bool = False,
    retain_dir: Path | None = None,
) -> dict:
    """#620: `per_probe_timeout_s` bounds EACH probe build (union + diagnostics)
    with a wall-clock watchdog. `checkdiff_timeout` is only the build budget
    INSIDE the child dump; it does not stop a hung mwcc/wibo process, so without
    a per-probe wall timeout the union build can stall indefinitely. On timeout
    the runner SIGKILLs the child (rc=124) and the probe is recorded
    inconclusive; the loop continues to the next probe rather than hanging."""
    groups = _force_vector_probe_groups(
        entries,
        include_diagnostic_probes=run_diagnostic_probes,
    )
    payload: dict = {
        "entries": [entry.to_payload() for entry in entries],
        "probe_count": len(groups),
        "probes": [],
    }
    child_env = _env_with_current_melee_agent_package(env)
    for label, group_entries, ordinal in groups:
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip(".-")
        output_path = (
            src_path.parent
            / f".{function}.force-vector.{safe_label}.{os.getpid()}.{int(time.time() * 1000)}.pcdump.txt"
        )
        cmd = _build_force_vector_auto_verify_cmd(
            src_path=src_path,
            function=function,
            entries=group_entries,
            output_path=output_path,
            checkdiff_timeout=checkdiff_timeout,
        )
        proc = _run_auto_verify_command_with_status(
            cmd,
            cwd=melee_root,
            status_label=f"force-vector {label}",
            timeout_s=per_probe_timeout_s,
            env=child_env,
        )
        probe = _force_vector_probe_payload(
            label=label,
            entries=group_entries,
            proc=proc,
            output_path=output_path,
            ordinal=ordinal,
        )
        retain_probe = (
            retain_pcdumps
            and label == "union"
            and probe.get("status") == "match"
            and output_path.exists()
        )
        if retain_probe:
            retained_path = output_path
            if retain_dir is not None:
                retain_dir.mkdir(parents=True, exist_ok=True)
                retained_path = retain_dir / output_path.name.lstrip(".")
                try:
                    shutil.move(str(output_path), str(retained_path))
                except OSError:
                    retained_path = output_path
            probe["pcdump"] = str(retained_path)
            probe["forced_pcdump"] = str(retained_path)
            probe["retained_pcdump"] = True
        else:
            probe.pop("pcdump", None)
            probe.pop("forced_pcdump", None)
            probe["retained_pcdump"] = False
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
        probe["timeout_seconds"] = per_probe_timeout_s
        probe["status_label"] = f"force-vector {label}"
        probe["command"] = " ".join(shlex.quote(part) for part in cmd)
        if label == "union":
            payload["union"] = probe
        else:
            payload["probes"].append(probe)
    return payload


def _package_melee_root() -> Path:
    package_path = Path(__file__).resolve()
    for parent in package_path.parents:
        if (
            (parent / "config" / "GALE01").exists()
            and (parent / "tools" / "checkdiff.py").exists()
        ):
            return parent
    for parent in package_path.parents:
        if _looks_like_melee_root(parent):
            return parent
    # src/cli/debug/__init__.py -> debug -> cli -> src -> melee-agent -> tools -> repo root
    return package_path.parents[5]


def _checkdiff_script_path(melee_root: Path) -> Path:
    """Return the authoritative checkdiff script while preserving target cwd.

    Matcher worktrees can carry stale fork-tooling overlays. Running the
    installed package's copy of checkdiff keeps classifier logic current while
    subprocess cwd still points at the worktree whose objects are being diffed.
    """
    package_checkdiff = _package_melee_root() / "tools" / "checkdiff.py"
    if package_checkdiff.exists():
        return package_checkdiff
    return melee_root / "tools" / "checkdiff.py"


def _select_order_variant_source_hunk(
    variant: Mapping[str, Any],
    *,
    function: str | None,
) -> str | None:
    if not function:
        return None
    source_path = variant.get("source_retained") or variant.get("path")
    if not isinstance(source_path, str) or not source_path.endswith(".c"):
        return None
    try:
        path = Path(source_path)
        if not path.exists():
            return None
        return _compact_source_hunk_for_function(
            path.read_text(encoding="utf-8", errors="replace"),
            function,
        )
    except OSError:
        return None



# ---------------------------------------------------------------------------
# Shared / monkeypatched helpers moved back from permute.py.
#
# These helpers are either called from sibling debug-CLI modules (dump, target,
# inspect, mutate, suggest, util, retro, intervene) or monkeypatched in tests via
# ``monkeypatch.setattr(debug_cli, ...)``. Their definitions must live in this
# package __init__ so that (a) cross-module deferred imports
# ``from src.cli.debug import _h`` resolve to a single shared object, and (b) test
# patches on the cli.debug package are visible to every call-site. permute.py
# reaches them via call-time deferred imports inside each consuming function body.
# ---------------------------------------------------------------------------

def _resolve_permuter_function_dir(
    function: str,
    *,
    perm_root: Path,
    melee_root: Path,
) -> Path:
    """Find a decomp-permuter function dir in either supported location."""
    perm_dir = perm_root / "nonmatchings" / function
    if perm_dir.exists():
        return perm_dir

    worktree_dir = melee_root / "nonmatchings" / function
    if worktree_dir.exists():
        return worktree_dir

    return perm_dir


def _resolve_decomp_permuter_root(requested_root: Path) -> Path:
    """Resolve the checkout that provides decomp-permuter's Python modules.

    `--perm-root` is also used to locate candidate trees, and some matcher
    worktrees carry `nonmatchings/<fn>` without being decomp-permuter clones.
    Running the blended wrapper with such a tree on PYTHONPATH shadows the real
    package and fails with `ModuleNotFoundError: src.compiler`.
    """
    from src.cli.debug import _looks_like_decomp_permuter_root  # noqa: PLC0415
    requested_root = requested_root.expanduser()
    if _looks_like_decomp_permuter_root(requested_root):
        return requested_root

    candidates: list[Path] = []
    env_root = os.environ.get("MELEE_DECOMP_PERMUTER_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.extend([
        Path("~/code/decomp-permuter").expanduser(),
        Path("~/code/melee-harness/decomp-permuter").expanduser(),
    ])
    for candidate in candidates:
        if candidate != requested_root and _looks_like_decomp_permuter_root(candidate):
            return candidate

    raise typer.BadParameter(
        f"{requested_root} does not look like a decomp-permuter checkout "
        "(missing permuter.py or src/compiler.py). Pass a decomp-permuter "
        "checkout via --perm-root, or set MELEE_DECOMP_PERMUTER_ROOT while "
        "using a separate matcher worktree for nonmatchings."
    )


def _bootstrap_permuter_dir(
    function: str,
    *,
    perm_root: Path,
    source_file: Optional[Path],
    melee_root: Optional[Path],
    preserve_macros: str,
    force: bool,
) -> dict:
    """Bootstrap a decomp-permuter function dir and return action metadata."""
    from src.cli.debug import (_acquire_checkdiff_repo_lock, _bootstrap_dependency_context, _detect_new_permuter_import_dir, _find_unit_for_function, _inject_bootstrap_same_tu_inlined_callees, _permuter_import_dirs, _promote_permuter_import_dir, _read_bootstrap_source_file, _read_bootstrap_target_asm, _resolve_bootstrap_melee_root, _sanitize_bootstrap_assert_macros, _source_contains_perm_macros, _staged_permuter_import_source, _tmp_asm_path_for_function)  # noqa: PLC0415
    from ...mwcc_debug.fix_perm_compile import fix_perm_dir
    from ...mwcc_debug.permuter_config import (
        build_spec,
        repair_bootstrap_settings_toml,
        write_settings_toml,
    )

    melee_root = _resolve_bootstrap_melee_root(
        function,
        source_file=source_file,
        melee_root=melee_root,
    )
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"could not find {function!r} in report.json. "
            "Rebuild report.json and retry.",
            err=True,
        )
        raise typer.Exit(2)
    src_path = melee_root / "src" / f"{unit}.c"
    if not src_path.exists():
        typer.echo(f"source not found: {src_path}", err=True)
        raise typer.Exit(2)
    if not perm_root.exists():
        typer.echo(f"--perm-root does not exist: {perm_root}", err=True)
        raise typer.Exit(2)
    import_py = perm_root / "import.py"
    if not import_py.exists():
        typer.echo(f"decomp-permuter import.py not found: {import_py}", err=True)
        raise typer.Exit(2)

    before_import_dirs = _permuter_import_dirs(
        function,
        perm_root=perm_root,
        melee_root=melee_root,
    )
    destination_settings_existed = (
        perm_root / "nonmatchings" / function / "settings.toml"
    ).exists()
    asm_path = _tmp_asm_path_for_function(function)
    extract_cmd = [
        "melee-agent",
        "extract",
        "get",
        function,
        "--full",
        "--output",
        str(asm_path),
    ]
    extract_proc = subprocess.run(
        extract_cmd,
        cwd=melee_root,
        capture_output=True,
        text=True,
    )
    if extract_proc.returncode != 0:
        typer.echo(extract_proc.stderr or extract_proc.stdout, err=True)
        raise typer.Exit(extract_proc.returncode or 1)

    python_bin = perm_root / ".venv" / "bin" / "python"
    if not python_bin.exists():
        python_bin = Path(sys.executable)
    requested_source = source_file.expanduser() if source_file is not None else src_path
    source_text = (
        _read_bootstrap_source_file(requested_source, function)
        if source_file is not None else src_path.read_text(encoding="utf-8")
    )
    source_contains_perm_macros = _source_contains_perm_macros(source_text)
    with _acquire_checkdiff_repo_lock(
        melee_root,
        label="permuter bootstrap source staging",
    ):
        with _staged_permuter_import_source(src_path, source_file) as (
            import_source,
            source_staged,
        ):
            import_cmd = [
                str(python_bin),
                str(import_py),
                str(import_source),
                str(asm_path),
                "--function",
                function,
            ]
            if preserve_macros is not None:
                import_cmd.extend(["--preserve-macros", preserve_macros])
            import_proc = subprocess.run(
                import_cmd,
                cwd=perm_root,
                capture_output=True,
                text=True,
            )
    if import_proc.returncode != 0:
        typer.echo(import_proc.stderr or import_proc.stdout, err=True)
        raise typer.Exit(import_proc.returncode or 1)

    imported_dir = _detect_new_permuter_import_dir(
        function,
        before_import_dirs,
        perm_root=perm_root,
        melee_root=melee_root,
    )
    if imported_dir is None:
        imported_dir = _resolve_permuter_function_dir(
            function,
            perm_root=perm_root,
            melee_root=melee_root,
        )
    fn_dir = _promote_permuter_import_dir(
        imported_dir,
        function=function,
        perm_root=perm_root,
        keep_existing_settings=not force,
    )
    if not fn_dir.exists():
        typer.echo(
            f"import.py completed but function dir was not found: {fn_dir}",
            err=True,
        )
        raise typer.Exit(1)

    injected_inline_callees: list[str] = []
    invalidated_base_object = False
    sanitized_assert_macros = False
    base_path = fn_dir / "base.c"
    if base_path.exists():
        target_asm_text = _read_bootstrap_target_asm(fn_dir, melee_root)
        source_for_inline = source_text
        dependency_text = _bootstrap_dependency_context(
            source_for_inline,
            source_path=requested_source,
            melee_root=melee_root,
        )
        patched_base, injected_inline_callees = (
            _inject_bootstrap_same_tu_inlined_callees(
                base_path.read_text(encoding="utf-8"),
                source_for_inline,
                function,
                target_asm_text,
                dependency_text=dependency_text,
            )
        )
        patched_base, sanitized_assert_macros = (
            _sanitize_bootstrap_assert_macros(patched_base)
        )
        if injected_inline_callees or sanitized_assert_macros:
            base_path.write_text(patched_base, encoding="utf-8")
            stale_base_o = fn_dir / "base.o"
            if stale_base_o.exists():
                stale_base_o.unlink()
                invalidated_base_object = True

    base_o_path = fn_dir / "base.o"
    base_text_before_fix = (
        base_path.read_text(encoding="utf-8") if base_path.exists() else None
    )
    fix_result = fix_perm_dir(fn_dir)
    if base_text_before_fix is not None and base_path.exists():
        base_text_after_fix = base_path.read_text(encoding="utf-8")
        if base_text_after_fix != base_text_before_fix and base_o_path.exists():
            base_o_path.unlink()
            invalidated_base_object = True

    base_contains_perm_macros = (
        _source_contains_perm_macros(base_path.read_text(encoding="utf-8"))
        if base_path.exists() else False
    )
    if invalidated_base_object:
        base_object_status = "invalidated-after-base-patch"
    elif base_o_path.exists():
        base_object_status = "present"
    else:
        base_object_status = "absent"

    settings_path = fn_dir / "settings.toml"
    recommended_randomize_funcs = (
        [function, *injected_inline_callees] if injected_inline_callees else None
    )
    randomize_funcs: list[str] | None = None
    randomize_funcs_status = "not-needed"
    settings_action = "kept"
    if force or not destination_settings_existed:
        write_settings_toml(
            build_spec(
                function,
                pattern=None,
                randomize_funcs=recommended_randomize_funcs,
            ),
            settings_path,
        )
        settings_action = "written"
        randomize_funcs = recommended_randomize_funcs
        if randomize_funcs is not None:
            randomize_funcs_status = "written"
    elif settings_path.exists():
        repair = repair_bootstrap_settings_toml(
            settings_path.read_text(encoding="utf-8"),
            function,
        )
        randomize_funcs = repair.randomize_funcs
        if repair.changed:
            settings_path.write_text(repair.text, encoding="utf-8")
            settings_action = "repaired"
        if randomize_funcs is not None:
            randomize_funcs_status = "existing"
        elif recommended_randomize_funcs is not None:
            randomize_funcs_status = "existing-settings-kept"

    return {
        "function": function,
        "unit": unit,
        "source": str(requested_source),
        "import_source": str(src_path),
        "source_staged": source_staged,
        "preserve_macros": preserve_macros,
        "source_contains_perm_macros": source_contains_perm_macros,
        "base_contains_perm_macros": base_contains_perm_macros,
        "base_object_status": base_object_status,
        "asm": str(asm_path),
        "perm_root": str(perm_root),
        "function_dir": str(fn_dir),
        "extract_command": extract_cmd,
        "import_command": import_cmd,
        "fix_compile": {
            "path": str(fix_result.path),
            "action": fix_result.action,
            "reason": fix_result.reason,
        },
        "injected_inline_callees": injected_inline_callees,
        "sanitized_assert_macros": sanitized_assert_macros,
        "invalidated_base_object": invalidated_base_object,
        "randomize_funcs": randomize_funcs,
        "recommended_randomize_funcs": recommended_randomize_funcs,
        "randomize_funcs_status": randomize_funcs_status,
        "settings": {
            "path": str(settings_path),
            "action": settings_action,
        },
    }


def _permuter_import_hint(
    function: str,
    *,
    perm_root: Path,
    melee_root: Path,
    unit: Optional[str] = None,
) -> str:
    from src.cli.debug import _find_unit_for_function  # noqa: PLC0415
    unit = unit or _find_unit_for_function(function, melee_root)
    if unit is None:
        return (
            "Run `melee-agent debug permute bootstrap` first. Could not locate the "
            f"source unit for {function!r}; regenerate report.json and retry."
        )

    perm_dir = _resolve_permuter_function_dir(
        function, perm_root=perm_root, melee_root=melee_root)
    return "\n".join([
        "Bootstrap the decomp-permuter function dir first:",
        f"  melee-agent debug permute bootstrap -f {shlex.quote(function)} "
        f"--perm-root {shlex.quote(str(perm_root))}",
        "  # bootstrap extracts target asm, invokes import.py, fixes compile.sh, "
        "and writes stock settings.toml.",
        f"  melee-agent debug permute fix-compile {shlex.quote(str(perm_dir))}",
    ])




def _force_coalesce_preflight_report(
    *,
    function: str,
    pair: tuple[int, int],
    pcdump_text: str,
    source_text: str,
    register_class: str = "gpr",
):
    from ...mwcc_debug.suggest_coalesce import run

    return run(
        function=function,
        pair=pair,
        register_class=register_class,
        pcdump_text=pcdump_text,
        source_text=source_text,
    )


def _reject_unsafe_force_coalesce(
    *,
    force_coalesce: str,
    function: str,
    melee_root: Path,
    register_class: str = "gpr",
) -> None:
    from src.cli.debug import _find_unit_for_function  # noqa: PLC0415
    pairs = _parse_force_coalesce_pairs(force_coalesce)
    pairs = [(lhs, rhs) for lhs, rhs in pairs if lhs != rhs]
    if not pairs:
        return

    unit = _find_unit_for_function(function, melee_root)
    source_text = ""
    if unit is not None:
        src_path = melee_root / "src" / f"{unit}.c"
        if src_path.exists():
            source_text = src_path.read_text()

    try:
        pcdump_path = _resolve_pcdump_path(
            None, function, melee_root, require_fresh=True,
        )
    except typer.Exit:
        dump_hint = (
            f"src/{unit}.c" if unit is not None else "<source.c>"
        )
        typer.echo(
            "[debug dump local] refusing --force-coalesce: fresh cached pcdump "
            f"required for {function}. Run `melee-agent debug dump local "
            f"{dump_hint}` without force options first, then retry the scoped "
            "force-coalesce.",
            err=True,
        )
        raise typer.Exit(2)

    pcdump_text = pcdump_path.read_text()
    unsafe: list[tuple[int, int, list[str]]] = []
    reg_prefix = "f" if register_class == "fpr" else "r"
    for pair in pairs:
        try:
            report = _force_coalesce_preflight_report(
                function=function,
                pair=pair,
                pcdump_text=pcdump_text,
                source_text=source_text,
                register_class=register_class,
            )
        except Exception as exc:
            typer.echo(
                f"[debug dump local] force-coalesce preflight skipped for "
                f"{reg_prefix}{pair[0]}={reg_prefix}{pair[1]}: "
                f"{type(exc).__name__}: {exc}",
                err=True,
            )
            continue
        preflight = report.pairs[0].preflight if report.pairs else None
        if preflight is not None and not preflight.safe:
            unsafe.append((pair[0], pair[1], list(preflight.reasons)))

    if not unsafe:
        return

    typer.echo(
        "[debug dump local] refusing unsafe --force-coalesce before invoking "
        "wibo. Use `debug suggest coalesce` for source-shape leads instead.",
        err=True,
    )
    for lhs, rhs, reasons in unsafe:
        typer.echo(f"  {reg_prefix}{lhs}={reg_prefix}{rhs}:", err=True)
        for reason in reasons:
            typer.echo(f"    - {reason}", err=True)
    raise typer.Exit(2)


def _extract_first_diagnostic(stdout: str, stderr: str) -> Optional[str]:
    """Find the first compiler diagnostic with `filename:line: error:` shape.

    This is the actual informative diagnostic — distinct from the caret
    pointer line that follows it. ninja/wibo output often interleaves
    progress lines around it, so we scan the full combined output and
    return the first match. Returns None if no such line is found.

    Handles MWCC's `# Error: …` block format too: when stderr looks like
    a multi-line `# File:` / `# Line:` / `# Error:` block, synthesize a
    `path:line: error: msg` line so callers see one usable diagnostic.
    """
    lines = (stdout + "\n" + stderr).splitlines()
    # First pass: standard `filename:line: error:` shape.
    for line in lines:
        m = _FIRST_DIAGNOSTIC_RE.match(line.strip())
        if m and m.group("level").lower() in ("error", "fatal"):
            return line.strip()

    # Second pass: MWCC's pretty-printed multi-line diagnostic block.
    # Look for `# File:` followed (within a few lines) by `# Line:` and
    # `# Error:` markers.
    path: Optional[str] = None
    lineno: Optional[str] = None
    for raw in lines:
        s = raw.strip()
        m = re.match(r"#\s*File:\s*(.*)$", s)
        if m:
            path = m.group(1).strip() or None
            continue
        m = re.match(r"#\s*Line:\s*(.*)$", s)
        if m:
            lineno = m.group(1).strip() or None
            continue
        m = re.match(r"#\s*Error:\s*(.*)$", s)
        if m:
            msg = m.group(1).strip()
            if msg:
                if not any(ch.isalnum() for ch in msg):
                    continue
                p = path or "(unknown)"
                ln = lineno or "?"
                return f"{p}:{ln}: error: {msg}"
    return None


def _extract_ninja_error(stdout: str, stderr: str, max_lines: int = 8) -> str:
    """Pull the relevant error lines out of a ninja failure dump.

    ninja's full output is mostly progress lines (`[N/M] ...`) that
    aren't useful. The actual error lives in lines containing 'error:',
    'FAILED:', or compiler diagnostics. Return at most `max_lines`.

    To make sure the first informative diagnostic isn't trimmed away by
    `max_lines` when there are many warnings, the result is prefixed
    with the first `filename:line: error:` diagnostic we find.
    """
    lines = (stdout + "\n" + stderr).splitlines()
    relevant_indexes: list[int] = []
    for idx, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        if any(marker in s.lower() for marker in (
            "error:", "failed:", "fatal:", "warning:",
            "undefined reference", "implicit declaration",
            "no such file", "cannot find",
        )):
            relevant_indexes.append(idx)
        elif s.startswith(("/", "src/", "include/", "tools/")) and ":" in s:
            # File:line:col-style references — likely the diagnostic location
            relevant_indexes.append(idx)
        elif re.match(r"#\s*(File|Line|Code|Error):", s):
            relevant_indexes.append(idx)
    context_indexes: set[int] = set(relevant_indexes)
    for idx in relevant_indexes:
        stripped = lines[idx].strip()
        if stripped.startswith("#"):
            for nearby in range(max(0, idx - 4), min(len(lines), idx + 3)):
                if lines[nearby].strip():
                    context_indexes.add(nearby)
        for nearby in range(idx + 1, min(len(lines), idx + 5)):
            nearby_stripped = lines[nearby].strip()
            if not nearby_stripped:
                continue
            if re.match(r"^\[\d+/\d+\]", nearby_stripped):
                break
            context_indexes.add(nearby)
    relevant = [lines[idx] for idx in sorted(context_indexes)]
    if not relevant:
        # Fall back to last few non-empty stderr lines
        tail_stderr = [l for l in stderr.splitlines() if l.strip()][-max_lines:]
        relevant = tail_stderr or ["(no error lines captured)"]

    # Promote the first FULL diagnostic (filename:line: error: …) to the
    # top of the result, so it isn't lost when many warnings precede the
    # real error and we hit max_lines. If we already have it in relevant,
    # this just guarantees ordering.
    first_diag = _extract_first_diagnostic(stdout, stderr)
    trimmed = relevant[:max_lines]
    if first_diag and first_diag not in trimmed:
        trimmed = [first_diag, *trimmed[: max_lines - 1]]
    return "\n".join(trimmed)


_WIBO_MISSING_IMPORT_RE = re.compile(
    r"wibo:\s*call reached missing import\s+"
    r"(?P<import>[A-Za-z_][A-Za-z_0-9]*)\s+from\s+"
    r"(?P<dll>[A-Za-z_][A-Za-z_0-9]*)",
    re.IGNORECASE,
)










def _resolve_pcdump_path(
    pcdump: Optional[Path],
    function: Optional[str],
    melee_root: Path = DEFAULT_MELEE_ROOT,
    *,
    require_fresh: bool = False,
) -> Path:
    """Resolve a pcdump path for a consumer command.

    Resolution order:
      1. If `pcdump` is given AND exists → use it.
      2. Else if `function` is given → look up its TU, check the cache.
         - If cache is fresh (or `require_fresh=False` and stale): use it.
         - If cache is missing or stale: raise typer.Exit with a clear hint.
      3. Else: raise typer.Exit asking for either path or function.

    The cache stale-vs-fresh logic: `require_fresh=False` lets the agent
    work with a slightly stale dump (useful when they just edited source
    but want to inspect what the OLD compile produced). `require_fresh=
    True` is for commands that NEED matching dump+source (e.g. ones that
    correlate per-line source positions).
    """
    from src.cli.debug import _find_unit_for_function  # noqa: PLC0415
    if pcdump is not None and pcdump.exists():
        return pcdump
    if pcdump is not None:
        # User specified a path but it doesn't exist
        typer.echo(f"pcdump not found: {pcdump}", err=True)
        raise typer.Exit(2)
    # Auto-resolve via function → TU → cache
    if function is None:
        typer.echo(
            "no pcdump path provided and no --function given.\n"
            "Either pass the pcdump path positionally, or pass --function "
            "and we'll auto-resolve via the cache.",
            err=True,
        )
        raise typer.Exit(2)
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        # Suggest similar names from report.json
        try:
            report_path = melee_root / "build" / "GALE01" / "report.json"
            if report_path.exists():
                with report_path.open() as f:
                    rdata = json.load(f)
                all_names = [fn.get("name") for u in rdata.get("units", [])
                             for fn in u.get("functions", []) if fn.get("name")]
                suggestions = _suggest_similar_functions(function, all_names)
            else:
                suggestions = []
        except Exception:
            suggestions = []
        msg = f"function '{function}' not found in report.json.\n"
        if suggestions:
            msg += "\nDid you mean one of these?\n"
            for s in suggestions:
                msg += f"  - {s}\n"
        msg += "\nTry `ninja build/GALE01/report.json` to regenerate, then retry."
        typer.echo(msg, err=True)
        raise typer.Exit(2)
    entry = pcdump_cache.lookup(melee_root, unit)
    if entry is None:
        cache_p = pcdump_cache.cache_path(melee_root, unit)
        src_p = pcdump_cache.source_path(melee_root, unit)
        local_cmd = _debug_dump_local_refresh_command(src_p, melee_root, function)
        typer.echo(
            f"no cached pcdump for {unit} (function lives in {src_p}).\n"
            f"Generate one with:\n"
            f"  {local_cmd}\n"
            f"or, if local dump support is unavailable:\n"
            f"  melee-agent debug dump remote {src_p.relative_to(melee_root)}\n"
            f"(it will be cached to {cache_p.relative_to(melee_root)})",
            err=True,
        )
        raise typer.Exit(3)
    if not entry.fresh and require_fresh:
        local_cmd = _debug_dump_local_refresh_command(
            entry.source_path, melee_root, function,
        )
        typer.echo(
            f"cached pcdump is stale (source modified since cache).\n"
            f"  Source: {entry.source_path}\n"
            f"  Cache:  {entry.path}\n"
            f"Regenerate with:\n"
            f"  {local_cmd}\n"
            f"or, if local dump support is unavailable:\n"
            f"  melee-agent debug dump remote {entry.source_path.relative_to(melee_root)}\n"
            f"If the command explicitly supports stale allocator facts, "
            f"retry with --allow-stale-pcdump.",
            err=True,
        )
        raise typer.Exit(4)
    if not entry.fresh:
        # Non-fatal — warn but use the stale cache.
        import datetime
        src_ts = datetime.datetime.fromtimestamp(
            entry.source_path.stat().st_mtime
        ).strftime("%H:%M:%S.%f")[:12]
        cache_ts = datetime.datetime.fromtimestamp(
            entry.path.stat().st_mtime
        ).strftime("%H:%M:%S.%f")[:12]
        local_cmd = _debug_dump_local_refresh_command(
            entry.source_path, melee_root, function,
        )
        typer.echo(
            f"[mwcc_debug] using stale cached pcdump "
            f"({entry.source_path.name} modified since cache; "
            f"src={src_ts} cache={cache_ts}). "
            f"Refresh with `{local_cmd}`.",
            err=True,
        )
    return entry.path




def _get_match_pct(func_name: str, melee_root: Path) -> Optional[float]:
    """Read the function's fuzzy_match_percent from report.json."""
    report_path = melee_root / "build" / "GALE01" / "report.json"
    if not report_path.exists():
        return None
    with report_path.open("r") as f:
        for unit in json.load(f).get("units", []):
            for function in unit.get("functions", []):
                if function.get("name") == func_name:
                    return function.get("fuzzy_match_percent")
    return None


_PERMUTER_PLACEHOLDERS = candidate_audit.PERMUTER_PLACEHOLDERS


def _merge_permuter_keep_candidate(
    base_fn: str,
    candidate_fn: str,
    current_fn: str,
    *,
    force: bool,
) -> tuple[str, str, list[tuple[int, str]]]:
    """Merge base->candidate into current for `verify --keep`.

    The first pass is the regular line-oriented 3-way merge. If that reports
    conflicts solely because the real source was reformatted after import, the
    canonical base/current functions still match; in that case taking the
    candidate is safe because there are no semantic current-side edits to
    preserve.
    """
    merged_fn, conflicts = _merge3_function(base_fn, candidate_fn, current_fn)
    if conflicts and not force:
        if (
            _canonical_c_for_format_merge(base_fn)
            == _canonical_c_for_format_merge(current_fn)
        ):
            return candidate_fn, "format-normalized-replace", []
    strategy = "3-way-merge" if not conflicts else "3-way-merge-forced"
    return merged_fn, strategy, conflicts


def _build_and_match(
    unit: str,
    function: str,
    melee_root: Path,
    *,
    fast_report: bool = True,
) -> Optional[float]:
    """Rebuild a unit's .o and return the function's fuzzy_match_percent.

    Two paths to regenerate the per-function score after building:

      fast_report=True (default): call `objdiff-cli report generate`
        directly. Skips ninja's dependency-graph traversal and avoids
        re-checking unrelated files. Same metric (fuzzy_match_percent)
        as the slow path. Typical speedup: ~0.7sec vs ~2-3sec.

      fast_report=False: run `ninja build/GALE01/report.json` (slow
        path). Use this when ninja's full dependency reasoning is
        needed — e.g. after a configure change.

    Returns None on build failure.
    """
    pct, _diagnostic = _build_and_match_with_diagnostic(
        unit,
        function,
        melee_root,
        fast_report=fast_report,
    )
    return pct


def _build_and_match_with_diagnostic(
    unit: str,
    function: str,
    melee_root: Path,
    *,
    fast_report: bool = True,
    timeout: float | None = None,
    deadline: float | None = None,
) -> tuple[Optional[float], Optional[str]]:
    """Rebuild a unit and return match percent plus failure diagnostic."""
    obj_path = f"build/GALE01/src/{unit}.o"
    build_timeout, deadline_error = _timeout_before_deadline(
        deadline,
        timeout,
        f"building {obj_path}",
    )
    if deadline_error is not None:
        return None, deadline_error
    r, _retried = _run_ninja_with_no_diag_retry(
        ["ninja", obj_path],
        melee_root,
        timeout=build_timeout,
    )
    if r.returncode != 0:
        return None, _extract_first_diagnostic(
            r.stdout,
            r.stderr,
        ) or _failure_diagnostic_or_fallback(
            r.stdout,
            r.stderr,
            fallback=f"ninja {obj_path} failed with exit {r.returncode}",
        )

    pct, _diagnostic = _refresh_match_pct_after_successful_build(
        unit,
        function,
        melee_root,
        fast_report=fast_report,
        timeout=timeout,
        deadline=deadline,
    )
    return pct, _diagnostic


def _run_command_with_optional_timeout(
    cmd: list[str],
    *,
    cwd: Path,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command, killing its process tree when a timeout is supplied."""
    try:
        if timeout is not None:
            return _run_with_process_group_timeout(
                cmd,
                cwd=cwd,
                timeout=timeout,
                env=env,
            )
        return subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return subprocess.CompletedProcess(
            cmd,
            124,
            stdout,
            (stderr + "\n" + _timeout_message(cmd, timeout)).strip(),
        )


def _run_ninja_with_no_diag_retry(
    cmd: list[str],
    melee_root: Path,
    *,
    timeout: float | None = None,
) -> tuple[subprocess.CompletedProcess[str], bool]:
    """Run a ninja command, retrying once if it fails without diagnostics."""
    def _run_once() -> subprocess.CompletedProcess[str]:
        return _run_command_with_optional_timeout(
            cmd,
            cwd=melee_root,
            timeout=timeout,
        )

    result = _run_once()
    if result.returncode == 0:
        return result, False
    if result.returncode == 124:
        return result, False
    if _extract_first_diagnostic(result.stdout, result.stderr) is not None:
        return result, False
    retry = _run_once()
    return retry, True






def _failure_diagnostic_or_fallback(
    stdout: str,
    stderr: str,
    *,
    fallback: str,
) -> str:
    first_diag = _extract_first_diagnostic(stdout, stderr)
    diagnostic = _extract_ninja_error(stdout, stderr, max_lines=8)
    if first_diag:
        if diagnostic and diagnostic != "(no error lines captured)":
            return diagnostic
        return first_diag
    if diagnostic and diagnostic != "(no error lines captured)":
        return diagnostic
    return fallback


def _refresh_match_pct_after_successful_build(
    unit: str,
    function: str,
    melee_root: Path,
    *,
    fast_report: bool = True,
    timeout: float | None = None,
    deadline: float | None = None,
) -> tuple[Optional[float], Optional[str]]:
    """Regenerate report.json after an object build and read match percent."""
    objdiff_bin = melee_root / "build" / "tools" / "objdiff-cli"
    if fast_report and objdiff_bin.exists():
        report_path = melee_root / "build" / "GALE01" / "report.json"
        cmd = [
            str(objdiff_bin),
            "report",
            "generate",
            "-o",
            str(report_path),
            "-f",
            "json",
        ]
        report_timeout, deadline_error = _timeout_before_deadline(
            deadline,
            timeout,
            "refreshing report.json",
        )
        if deadline_error is not None:
            return None, deadline_error
        try:
            r = subprocess.run(
                cmd,
                cwd=melee_root,
                capture_output=True,
                text=True,
                timeout=report_timeout,
            )
        except subprocess.TimeoutExpired:
            return None, _timeout_message(cmd, report_timeout)
        if r.returncode != 0:
            return None, _failure_diagnostic_or_fallback(
                r.stdout,
                r.stderr,
                fallback=(
                    f"objdiff report generation failed with exit "
                    f"{r.returncode}"
                ),
            )
        pct, read_diag = _get_match_pct_with_report_retry(
            function,
            melee_root,
        )
        if read_diag:
            return None, read_diag
        if pct is None:
            return None, f"report.json did not contain match percent for {function}"
        return pct, None

    # Slow path: full ninja regen.
    cmd = ["ninja", "build/GALE01/report.json"]
    report_timeout, deadline_error = _timeout_before_deadline(
        deadline,
        timeout,
        "refreshing report.json",
    )
    if deadline_error is not None:
        return None, deadline_error
    try:
        r = subprocess.run(
            cmd,
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=report_timeout,
        )
    except subprocess.TimeoutExpired:
        return None, _timeout_message(cmd, report_timeout)
    if r.returncode != 0:
        return None, _failure_diagnostic_or_fallback(
            r.stdout,
            r.stderr,
            fallback=f"report.json regeneration failed with exit {r.returncode}",
        )
    pct, read_diag = _get_match_pct_with_report_retry(function, melee_root)
    if read_diag:
        return None, read_diag
    if pct is None:
        return None, f"report.json did not contain match percent for {function}"
    return pct, None


_POINTER_REASSOC_CALL_ARG_INDEX: dict[str, int] = {
    "memcpy": 0,
    "memset": 0,
    "fn_803AC3F8": 1,
}


def _detect_existing_compile_sh_project_root(text: str) -> Optional[str]:
    """Pull the `cd <project_root>` line out of an existing compile.sh.

    Returns the path string (the part after `cd `) or None if not found.
    We do this because permuter's import.py + our prior fix_perm_compile
    encode the project root into compile.sh, and we want to preserve it
    when generating a fresh wrapper.
    """
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("cd "):
            return s[len("cd "):].strip()
    return None


def _extract_cflags_from_compile_sh(text: str) -> Optional[str]:
    """Rip the mwcc cflags out of a compile.sh body.

    The expected line shape is one of::

        wine ... mwcceppc.exe <flags...> -c "$INPUT" -o "$OUTPUT"
        wibo ... mwcceppc.exe <flags...> -c "$INPUT" -o "$OUTPUT"
        ... mwcceppc.exe <flags...> "$INPUT" -o "$OUTPUT"

    We pull out <flags...> as a single shlex-joinable string so we can
    re-emit them inside the new wrapper. If the compile.sh doesn't
    match any of these shapes, returns None.
    """
    m = _CFLAGS_LINE_RE.search(text)
    if not m:
        return None
    return m.group(1).strip()


def _find_wibo() -> Optional[Path]:
    """Locate the patched wibo binary. Resolution order:

    1. $MWCC_DEBUG_WIBO env var
    2. <melee_root>/tools/mwcc_debug/bin/wibo (vendored — built by build_wibo.sh)
    3. <melee_root>/../melee-harness/bin/wibo (adjacent harness checkout)
    4. ~/code/melee-harness/bin/wibo
    """
    import os as _os
    env = _os.environ.get("MWCC_DEBUG_WIBO")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    candidates = [
        DEFAULT_MELEE_ROOT / "tools" / "mwcc_debug" / "bin" / "wibo",
        DEFAULT_MELEE_ROOT.parent / "melee-harness" / "bin" / "wibo",
        Path("~/code/melee-harness/bin/wibo").expanduser(),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _find_compiler_dir() -> Path:
    """Path to the GC/1.2.5n compiler directory."""
    return DEFAULT_MELEE_ROOT / "build" / "compilers" / "GC" / "1.2.5n"


def _build_local_dll() -> Optional[Path]:
    """Build the mwcc_debug DLL via tools/mwcc_debug/build_macos.sh.
    Returns the built DLL path or None on failure.
    """
    build_script = (
        DEFAULT_MELEE_ROOT / "tools" / "mwcc_debug" / "build_macos.sh"
    )
    if not build_script.exists():
        return None
    try:
        proc = subprocess.run(
            [str(build_script)],
            cwd=build_script.parent,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, end="")
        if exc.stderr:
            typer.echo(exc.stderr, err=True)
        return None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        typer.echo(proc.stderr, err=True)
    built = build_script.parent / "MWDBG326.dll"
    if built.exists():
        return built
    import_name_dll = build_script.parent / "lmgr326b.dll"
    if import_name_dll.exists():
        shutil.copy2(import_name_dll, built)
        print(
            f"[ok] using alternate DLL output {import_name_dll.name} "
            f"as {built.name}"
        )
        return built
    return built


_MWCC_DEBUG_DLL_FEATURE_PREFIX = "MWCC_DEBUG_FEATURES:"


_MWCC_DEBUG_REQUIRED_DLL_FEATURES = (
    "pcdump-path",
    "function-scope-force-phys",
    "force-phys-iter",
    "force-phys-overflow-error",
    "force-iter-first-overflow-error",
    "force-coalesce-class",
    "force-remat",
    "force-interfere",
    "force-schedule",
    "force-no-cse",
    "trace-cse",
)


_MWCC_DEBUG_LEGACY_HOOK_STRINGS = (
    "MWCC_DEBUG_PCDUMP_PATH",
    "MWCC_DEBUG_FORCE_PHYS_FUNCTION",
    "MWCC_DEBUG_FORCE_PHYS_ITER",
    "MWCC_DEBUG_FORCE_ITER_FIRST_FUNCTION",
    "MWCC_DEBUG_FORCE_COALESCE",
    "MWCC_DEBUG_FORCE_COALESCE_FUNCTION",
    "MWCC_DEBUG_FORCE_COALESCE_CLASS",
    "[FORCE_COALESCE]",
    "MWCC_DEBUG_FORCE_REMAT",
    "MWCC_DEBUG_FORCE_REMAT_FUNCTION",
    "[FORCE_REMAT]",
    "MWCC_DEBUG_FORCE_INTERFERE",
    "MWCC_DEBUG_FORCE_INTERFERE_FUNCTION",
    "[FORCE_INTERFERE]",
    "MWCC_DEBUG_FORCE_SCHEDULE",
    "MWCC_DEBUG_FORCE_SCHEDULE_FUNCTION",
    "[FORCE_SCHEDULE]",
    "MWCC_DEBUG_TRACE_CSE",
    "MWCC_DEBUG_TRACE_CSE_FUNCTION",
    "IRO_CommonSub: replaced node",
)


def _smoke_mwcc_debug_compiler(
    wibo: Path,
    compiler_dir: Path,
    *,
    timeout: float = 30.0,
) -> _DumpSetupCheck:
    from src.cli.debug import (_DumpSetupCheck, _format_smoke_process_output)  # noqa: PLC0415
    debug_compiler = compiler_dir / "mwcceppc_debug.exe"
    if not debug_compiler.exists():
        return _DumpSetupCheck(
            "mwcc_debug pcdump smoke",
            False,
            f"missing patched compiler: {debug_compiler}",
        )
    with tempfile.TemporaryDirectory(prefix="mwcc-debug-smoke-") as tmp:
        tmpdir = Path(tmp)
        source = tmpdir / "smoke_test.c"
        obj = tmpdir / "smoke_test.o"
        pcdump = tmpdir / "pcdump.txt"
        source.write_text("int smoke_test(int x) { return x + 1; }\n")
        env = os.environ.copy()
        env["MWCC_DEBUG_PCDUMP_PATH"] = str(pcdump)
        cmd = [
            str(wibo),
            str(debug_compiler),
            "-c",
            "-O4,p",
            "-proc",
            "gekko",
            "-enum",
            "int",
            "-fp",
            "hardware",
            "-o",
            str(obj),
            str(source),
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=tmpdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _DumpSetupCheck(
                "mwcc_debug pcdump smoke",
                False,
                f"timed out after {timeout:g}s running patched compiler",
            )
        if result.returncode != 0:
            return _DumpSetupCheck(
                "mwcc_debug pcdump smoke",
                False,
                f"patched compiler exited {result.returncode}"
                f"{_format_smoke_process_output(result)}",
            )
        try:
            size = pcdump.stat().st_size
        except OSError:
            size = 0
        if size <= 0:
            return _DumpSetupCheck(
                "mwcc_debug pcdump smoke",
                False,
                f"pcdump.txt missing or empty at {pcdump}"
                f"{_format_smoke_process_output(result)}",
            )
        return _DumpSetupCheck(
            "mwcc_debug pcdump smoke",
            True,
            f"pcdump smoke produced {size} bytes",
        )


def _ninja_cflags_for_unit(src_rel: str, melee_root: Path | None = None) -> tuple[str, str]:
    """Extract (cflags, mw_version) for a source from build.ninja.

    Mirrors melee-harness/tools/mwcc_dump.py's find_build_block.
    Raises typer.Exit if the source has no build block.
    """
    import re as _re
    root = melee_root or DEFAULT_MELEE_ROOT
    build_ninja = root / "build.ninja"
    try:
        text = build_ninja.read_text()
    except FileNotFoundError:
        typer.echo(
            f"build.ninja missing: {build_ninja}\n"
            f"Run `python configure.py` from the repo root, then retry "
            f"`debug dump local`.",
            err=True,
        )
        raise typer.Exit(2)
    text = text.replace("$\n", " ")  # unfold ninja line continuations
    obj = f"build/GALE01/{src_rel[:-2]}.o"
    blocks = _re.split(r"^build ", text, flags=_re.M)
    for b in blocks:
        if b.startswith(f"{obj}:") or b.startswith(f"{obj} :"):
            cflags = _re.search(r"\bcflags = (.*)", b).group(1).strip()
            mw = _re.search(r"\bmw_version = (\S+)", b).group(1).strip()
            return cflags, mw
    typer.echo(
        f"no build block for {obj} in build.ninja. "
        f"Run `python configure.py && ninja build/GALE01/report.json` "
        f"first to ensure the source is registered.",
        err=True,
    )
    raise typer.Exit(2)


def _cache_settle_seconds(env: Optional[Mapping[str, str]] = None) -> float:
    values = env if env is not None else os.environ
    raw = values.get("MWCC_DEBUG_CACHE_SETTLE_SECONDS", "0.25")
    try:
        seconds = float(raw)
    except ValueError:
        return 0.25
    return max(0.0, seconds)


def _run_auto_verify_command_with_status(
    cmd: list[str],
    *,
    cwd: Path,
    status_label: str,
    phase: str = "testing",
    status_interval_s: float = 10.0,
    timeout_s: Optional[float] = None,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    if phase == "testing":
        print(f"[auto-verify] testing {status_label}", file=sys.stderr)
    else:
        print(f"[auto-verify] {phase}: {status_label}", file=sys.stderr)
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    started = time.time()
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=status_interval_s)
            return subprocess.CompletedProcess(
                cmd,
                proc.returncode,
                stdout,
                stderr,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.time() - started
            if timeout_s is not None and elapsed >= timeout_s:
                import signal as _signal
                timeout_msg = (
                    f"[auto-verify] {phase} timed out after "
                    f"{timeout_s:g}s ({status_label})"
                )
                print(timeout_msg, file=sys.stderr)
                try:
                    os.killpg(os.getpgid(proc.pid), _signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    stdout, stderr = proc.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    stdout, stderr = "", ""
                stderr = (stderr or "")
                if stderr and not stderr.endswith("\n"):
                    stderr += "\n"
                stderr += timeout_msg
                return subprocess.CompletedProcess(cmd, 124, stdout, stderr)
            print(
                f"[auto-verify] still running after {elapsed:.0f}s "
                f"({phase}: {status_label})",
                file=sys.stderr,
            )




def _score_expression_anchors(
    *,
    target_spec: Mapping[str, Any],
    target_details: Mapping[str, Any],
    pcdump_text: str,
    function: str,
    fn: Any,
    candidate_source_text: str | None,
    candidate_source_file: str | None,
    baseline_pcdump_text: str | None,
    baseline_source_text: str | None,
    baseline_source_file: str | None,
    reg_class: str | None = None,
) -> dict[str, Any] | None:
    normalized_reg_class = _expression_reg_class_from_spec(target_spec, reg_class)
    anchors = _expression_anchors_from_spec(target_spec)
    derived_from_baseline = False
    if not anchors and baseline_pcdump_text:
        anchors = _derive_expression_anchors(
            target_spec=target_spec,
            baseline_pcdump_text=baseline_pcdump_text,
            function=function,
            source_text=baseline_source_text,
            source_file=baseline_source_file,
            reg_class=normalized_reg_class,
        )
        derived_from_baseline = True
    if not anchors:
        return None

    candidates = _candidate_expression_entries(
        pcdump_text=pcdump_text,
        function=function,
        fn=fn,
        source_text=candidate_source_text,
        source_file=candidate_source_file,
        reg_class=normalized_reg_class,
    )
    raw_virtuals = target_details.get("virtuals")
    if not isinstance(raw_virtuals, Mapping):
        raw_virtuals = {}

    matched = 0
    moved = 0
    false_positive_virtual_id_hits: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}
    for anchor in anchors:
        baseline_virtual = int(anchor["baseline_virtual"])
        expected = int(anchor["expected"])
        signature = anchor["signature"]
        signature_key = _expression_signature_key(signature)
        matches = candidates.get(signature_key, [])
        raw_detail = raw_virtuals.get(str(baseline_virtual))
        raw_actual = raw_detail.get("actual") if isinstance(raw_detail, Mapping) else None
        raw_matched = bool(raw_detail.get("matched")) if isinstance(raw_detail, Mapping) else False

        entry: dict[str, Any] = {
            "baseline_virtual": baseline_virtual,
            "expected": expected,
            "signature": signature,
            "baseline_source": anchor.get("baseline_source"),
            "virtual_id_actual": raw_actual,
            "virtual_id_matched": raw_matched,
        }
        if not matches:
            entry.update({
                "status": "missing-expression",
                "candidate_virtual": None,
                "actual": None,
                "matched": False,
            })
        elif len(matches) > 1:
            entry.update({
                "status": "ambiguous-expression",
                "candidate_virtual": None,
                "actual": None,
                "matched": False,
                "candidates": matches,
            })
        else:
            candidate = matches[0]
            try:
                candidate_virtual = int(candidate.get("virtual"))
            except (TypeError, ValueError):
                candidate_virtual = None
            try:
                actual = int(candidate.get("actual"))
            except (TypeError, ValueError):
                actual = None
            is_match = actual == expected
            if is_match:
                matched += 1
            if candidate_virtual is not None and candidate_virtual != baseline_virtual:
                moved += 1
            entry.update({
                "status": "ok",
                "candidate_virtual": candidate_virtual,
                "actual": actual,
                "matched": is_match,
                "renumbered": (
                    candidate_virtual is not None
                    and candidate_virtual != baseline_virtual
                ),
                "candidate_source": candidate.get("source"),
            })
        false_positive = raw_matched and not bool(entry["matched"])
        entry["virtual_id_false_positive"] = false_positive
        if false_positive:
            false_positive_virtual_id_hits.append({
                "baseline_virtual": baseline_virtual,
                "expected": expected,
                "virtual_id_actual": raw_actual,
                "candidate_virtual": entry.get("candidate_virtual"),
                "actual": entry.get("actual"),
                "signature": signature,
            })
        details[str(baseline_virtual)] = entry

    targeted = len(anchors)
    return {
        "register_class": normalized_reg_class,
        "derived_from_baseline": derived_from_baseline,
        "matched": matched,
        "targeted": targeted,
        "virtual_distance": targeted - matched,
        "renumbered": moved,
        "false_positive_virtual_id_hit_count": len(false_positive_virtual_id_hits),
        "false_positive_virtual_id_hits": false_positive_virtual_id_hits,
        "virtuals": details,
    }
