"""`debug dump ...` — pcdump collection and local mwcc_debug setup command group.

Carved out of cli/debug/__init__.py. This module contains the 5 dump command
handlers (remote, setup, doctor, restore-object-report, local) and their
group-private helpers.

Shared helpers (and module-level names the tests patch on the cli.debug
package) still live in cli/debug/__init__.py. They are reached via call-time
(deferred) ``from src.cli.debug import ...`` imports inside the function
bodies -- a load-time import would create a cycle (__init__ imports this
module) and would also break ``monkeypatch.setattr(debug_cli, ...)``
semantics, since the patched name must resolve against __init__ at call time.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import (
    Annotated,
    Any,
    Callable,
    Mapping,
    Optional,
)

import typer

from ...mwcc_debug import local_safety
from ...mwcc_debug import cache as pcdump_cache
from ...mwcc_debug import (
    parse_pcdump,
    slice_pcdump_to_function,
)
from ...mwcc_debug.temp_scratch import (
    reaped_scratch_root as mwcc_debug_scratch_root,
)

dump_app = typer.Typer(
    help="Collect pcdumps and manage local mwcc_debug setup."
)

__all__ = [
    '_DumpSetupCheck',
    '_FORCE_PHYS_CLASS_NAMES',
    '_REMOTE_STAGE_SOURCE_STDIN_MAX_BYTES',
    '_RemotePcdumpResult',
    '_build_local_wibo',
    '_check_dll_is_pe',
    '_check_mwcc_debug_dll_features',
    '_check_mwcc_debug_dll_freshness',
    '_check_path',
    '_cmd_set_env',
    '_communicate_remote_pcdump',
    '_compiled_source_snapshot_still_current',
    '_count_function_defs',
    '_debug_dump_local_wibo_runtime_failure',
    '_decode_remote_stream',
    '_dll_needs_rebuild',
    '_force_object_delta_baseline_env',
    '_format_smoke_process_output',
    '_infer_remote_unit_source',
    '_local_dump_setup_checks',
    '_make_expensive_restore_result',
    '_ninja_dry_run_planned_steps',
    '_normalize_force_coalesce',
    '_path_newer_than',
    '_pcdump_local_missing_diff_target_hint',
    '_print_local_dump_setup_checks',
    '_raise_pcdump_local_watchdog_exit',
    '_remote_pcdump_timeout_env_value',
    '_remote_pcdump_timeout_seconds',
    '_remote_retained_source_blocker_payload',
    '_remote_retained_source_blocker_sidecar_path',
    '_remote_retained_source_dependency_context_evidence',
    '_remote_stage_source_via_scp',
    '_remote_staging_ack_confirmed',
    '_remote_staging_ack_error',
    '_resolve_remote_pcdump_branch',
    '_restore_object_report_cmd_for_unit',
    '_validate_force_no_cse',
    '_validate_force_no_cse_fn',
    '_validate_force_remat',
    '_verify_force_coalesce_object_delta',
    '_write_remote_retained_source_blocker_sidecar',
    'pcdump',
    'pcdump_local',
    'restore_object_report',
    'setup_doctor',
    'setup_local',
]


@dataclasses.dataclass
class _RemotePcdumpResult:
    returncode: int
    stdout: str
    stderr: str
    cmd: list[str]
    host: str
    source_rel: str
    compile_source_rel: str
    staged_source: str | None = None
    bytes_written: int = 0
    stage_source_sha256: str | None = None
    staging_ack_confirmed: bool | None = None
    staging_transport: str | None = None
    remote_stage_source: str | None = None



_REMOTE_STAGE_SOURCE_STDIN_MAX_BYTES = 64 * 1024



def _resolve_remote_pcdump_branch(branch: str | None) -> str | None:
    """Resolve and validate the branch passed through to remote cmd.exe."""
    from src.cli.debug import DEFAULT_MELEE_ROOT  # noqa: E402
    if branch is None:
        try:
            r = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=DEFAULT_MELEE_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode == 0:
                branch = r.stdout.strip() or None
        except Exception:
            branch = None
    if branch is not None and any(c in branch for c in '"\'; \t&|<>'):
        raise typer.BadParameter(
            f"branch name must not contain shell metacharacters: {branch!r}"
        )
    return branch



def _remote_pcdump_timeout_env_value(timeout: int | float) -> str:
    try:
        timeout_f = float(timeout)
    except (TypeError, ValueError):
        timeout_f = 60.0
    timeout_i = int(timeout_f)
    if timeout_i < timeout_f:
        timeout_i += 1
    return str(max(1, timeout_i))



def _infer_remote_unit_source(
    source_rel: str,
    *,
    function: str | None,
    melee_root: Path,
) -> str:
    from src.cli.debug import _find_unit_for_function, find_function_definitions  # noqa: E402
    if source_rel.startswith("src/"):
        return source_rel

    if function:
        unit = _find_unit_for_function(function, melee_root)
        if unit is not None:
            return f"src/{unit}.c"
        raise typer.BadParameter(
            f"could not infer --unit-source for function {function!r}; "
            "pass --unit-source src/<unit>.c"
        )

    source_path = melee_root / source_rel
    try:
        source_text = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise typer.BadParameter(
            f"could not read retained source for unit inference: {source_path}: {exc}; "
            "pass --unit-source src/<unit>.c"
        ) from exc

    report_units: dict[str, list[str]] = {}
    for span in find_function_definitions(source_text):
        unit = _find_unit_for_function(span.name, melee_root)
        if unit is None:
            continue
        report_units.setdefault(f"src/{unit}.c", []).append(span.name)

    if len(report_units) == 1:
        return next(iter(report_units))
    if not report_units:
        raise typer.BadParameter(
            "could not infer --unit-source from retained source: no "
            "report-backed function definitions were found; pass "
            "--unit-source src/<unit>.c"
        )
    details = ", ".join(
        f"{unit} ({', '.join(names)})"
        for unit, names in sorted(report_units.items())
    )
    raise typer.BadParameter(
        "could not infer --unit-source unambiguously: retained source "
        f"contains report-backed functions from multiple units: {details}; "
        "pass --unit-source src/<unit>.c"
    )



def _decode_remote_stream(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode(errors="replace")



def _remote_staging_ack_error(
    *,
    expected_sha256: str | None,
    stderr_text: str,
    stage_source_label: str | None,
    remote_script: str,
) -> str | None:
    if expected_sha256 is None:
        return None
    if _remote_staging_ack_confirmed(
        expected_sha256=expected_sha256,
        stderr_text=stderr_text,
    ):
        return None
    label = stage_source_label or "<stdin>"
    return (
        "remote retained-source staging did not confirm staged source "
        f"sha256={expected_sha256} for {label}; remote helper {remote_script} "
        "may be stale or missing retained-source staging support"
    )



def _remote_staging_ack_confirmed(
    *,
    expected_sha256: str | None,
    stderr_text: str,
) -> bool:
    if expected_sha256 is None:
        return False
    return f"sha256={expected_sha256}" in stderr_text.lower()



def _remote_retained_source_dependency_context_evidence(
    stderr_text: str,
) -> bool:
    lowered = stderr_text.lower()
    return any(
        marker in lowered
        for marker in (
            "redeclared",
            "conflicting declaration",
            "conflicting types",
            "previous declaration",
            "previously declared",
            "undeclared identifier",
            "undefined identifier",
            "unknown type",
            "cannot open include",
            "no such file or directory",
            "not found",
        )
    )



def _remote_retained_source_blocker_sidecar_path(
    out_path_for_msg: str,
) -> Path | None:
    if out_path_for_msg == "stdout":
        return None
    return Path(f"{out_path_for_msg}.blocker.json")



def _remote_retained_source_blocker_payload(
    remote_result: _RemotePcdumpResult,
    *,
    function: str | None,
    branch: str | None,
    timeout: int | float,
    out_path_for_msg: str,
    sidecar_path: Path | None,
    melee_root: Path,
) -> dict[str, Any]:
    from src.cli.debug import _remote_pcdump_local_head, _remote_retained_source_terminal_blocker  # noqa: E402
    terminal_blocker = _remote_retained_source_terminal_blocker(remote_result)
    payload: dict[str, Any] = {
        "status": "blocked",
        "tool": "mwcc-debug",
        "command": "debug dump remote",
        "terminal_blocker": terminal_blocker,
        "returncode": remote_result.returncode,
        "host": remote_result.host,
        "source": remote_result.source_rel,
        "compile_source": remote_result.compile_source_rel,
        "staged_source": remote_result.staged_source,
        "stage_source_sha256": remote_result.stage_source_sha256,
        "staging_ack_confirmed": remote_result.staging_ack_confirmed,
        "staging_transport": remote_result.staging_transport,
        "remote_stage_source": remote_result.remote_stage_source,
        "branch": branch,
        "function": function,
        "output": out_path_for_msg,
        "stderr_tail": (remote_result.stderr or "")[-4000:],
    }
    if remote_result.stdout:
        payload["stdout_tail"] = remote_result.stdout[-4000:]
    if remote_result.returncode == 124:
        payload["timeout_seconds"] = float(timeout)
    if sidecar_path is not None:
        payload["blocker_json"] = str(sidecar_path)
    if terminal_blocker == "remote-retained-source-dependency-context-mismatch":
        required_files = [
            remote_result.compile_source_rel,
            remote_result.staged_source,
        ]
        payload["dependency_context"] = {
            "kind": "detached-or-local dependency context",
            "required_files": [item for item in required_files if item],
            "local_head": _remote_pcdump_local_head(melee_root),
            "requested_branch": branch,
            "message": (
                "The retained source was staged successfully, but the remote "
                "checkout did not contain compatible same-TU declarations or "
                "other local dependency context needed to compile it."
            ),
        }
        payload["next_steps"] = [
            "Push a branch containing the local dependency context and rerun "
            "`debug dump remote --branch <remote-ref>`.",
            "Use `debug dump local` after `debug dump doctor --repair` when "
            "the local pcdump lane is safe.",
            "If neither path is available, treat this as a dependency-context "
            "blocker rather than filing a generic remote command failure.",
        ]
    return {key: value for key, value in payload.items() if value is not None}



def _write_remote_retained_source_blocker_sidecar(
    payload: Mapping[str, Any],
    sidecar_path: Path | None,
) -> None:
    if sidecar_path is None:
        return
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )



def _remote_pcdump_timeout_seconds(timeout: int | float) -> float | None:
    try:
        timeout_f = float(timeout)
    except (TypeError, ValueError):
        return 60.0
    if timeout_f <= 0:
        return None
    return max(0.1, timeout_f)



def _remote_stage_source_via_scp(
    *,
    host: str,
    source_path: Path,
    timeout: int | float,
) -> tuple[str | None, str, int]:
    from src.cli.debug import _timeout_message  # noqa: E402
    remote_name = f"mwcc_debug_stage_{uuid.uuid4().hex}.c"
    cmd = ["scp", "-q", str(source_path), f"{host}:{remote_name}"]
    timeout_seconds = _remote_pcdump_timeout_seconds(timeout)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stderr_text = _decode_remote_stream(exc.stderr)
        if stderr_text and not stderr_text.endswith("\n"):
            stderr_text += "\n"
        stderr_text += "scp source staging timed out before remote compile\n"
        stderr_text += _timeout_message(cmd, timeout_seconds)
        return remote_name, stderr_text, 124
    stderr_text = _decode_remote_stream(proc.stderr)
    stdout_text = _decode_remote_stream(proc.stdout)
    if stdout_text:
        stderr_text = f"{stderr_text.rstrip()}\n{stdout_text}" if stderr_text else stdout_text
    return remote_name, stderr_text, int(proc.returncode or 0)



def _communicate_remote_pcdump(
    proc: subprocess.Popen[Any],
    *,
    ssh_cmd: list[str],
    input_bytes: bytes | None,
    timeout: int | float,
) -> tuple[bytes | str | None, bytes | str | None, int]:
    from src.cli.debug import _timeout_message  # noqa: E402
    timeout_seconds = _remote_pcdump_timeout_seconds(timeout)
    try:
        try:
            stdout_data, stderr_data = proc.communicate(
                input=input_bytes,
                timeout=timeout_seconds,
            )
        except TypeError as exc:
            if "timeout" not in str(exc):
                raise
            stdout_data, stderr_data = proc.communicate(input=input_bytes)
        return stdout_data, stderr_data, int(proc.returncode or 0)
    except BrokenPipeError as exc:
        stdout_data, stderr_data = proc.communicate()
        stderr_text = f"{exc}\n{_decode_remote_stream(stderr_data)}"
        return stdout_data, stderr_text, int(proc.returncode or 1)
    except subprocess.TimeoutExpired as exc:
        try:
            proc.kill()
        except OSError:
            pass
        stdout_data: bytes | str | None
        stderr_data: bytes | str | None
        try:
            stdout_data, stderr_data = proc.communicate(timeout=5)
        except Exception:
            stdout_data = exc.output
            stderr_data = exc.stderr
        stderr_text = _decode_remote_stream(stderr_data)
        timeout_text = _timeout_message(ssh_cmd, timeout_seconds)
        if stderr_text and not stderr_text.endswith("\n"):
            stderr_text += "\n"
        stderr_text += timeout_text
        return stdout_data, stderr_text, 124



@dump_app.command("remote")
def pcdump(
    c_file: Annotated[
        str,
        typer.Argument(help="Path to a .c file in the melee repo"),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Output path for the dump. Default: cache it under "
                 "build/mwcc_debug_cache/<unit>.txt so follow-up commands "
                 "can auto-resolve it. Use '-' to force stdout instead.",
        ),
    ] = None,
    unit_source: Annotated[
        Optional[str],
        typer.Option(
            "--unit-source",
            "--cflags-from",
            help=(
                "Compile retained/probe source through this real same-TU "
                "src/... file on the remote. Non-src sources are streamed "
                "over SSH stdin and staged into the unit for the duration "
                "of the remote pcdump run."
            ),
        ),
    ] = None,
    function: Annotated[
        Optional[str],
        typer.Option(
            "--function", "-f",
            help=(
                "Function name used to infer --unit-source for retained "
                "remote sources when --unit-source is omitted."
            ),
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout", "-t",
            help="Per-compile timeout in seconds (passed to remote)",
        ),
    ] = 60,
    host: Annotated[
        str,
        typer.Option(
            help="SSH host alias for the Windows debug machine",
            envvar="MWCC_DEBUG_HOST",
        ),
    ] = "nzxt-local",
    remote_script: Annotated[
        str,
        typer.Option(
            help="Path to run_pcdump.ps1 on the remote host",
            envvar="MWCC_DEBUG_REMOTE_SCRIPT",
        ),
    ] = r"C:\Users\mikes\code\mwcc_debug\run_pcdump.ps1",
    no_pull: Annotated[
        bool,
        typer.Option(
            "--no-pull",
            help="Skip 'git pull' on the remote side (test stale code)",
        ),
    ] = False,
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help="Tier 5: bias the allocator. Format 'virtIdx:physReg[,...]' "
                 "or 'class:virtIdx:physReg[,...]' (class: gpr, fp, fpr, int). "
                 "E.g. '36:31' or 'gpr:36:31'. Class-scoped entries are "
                 "passed through to the DLL and only apply to that register "
                 "class. "
                 "EXPERIMENTAL — may produce broken code if interferences "
                 "are violated.",
        ),
    ] = None,
    force_phys_iter: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys-iter",
            help="Tier 5: bias by colorgraph iter position "
                 "(class:iter:phys[,...]). Use for nodes that lack an "
                 "addressable ig_idx. EXPERIMENTAL.",
        ),
    ] = None,
    force_phys_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys-fn",
            help="Scope --force-phys and --force-phys-iter to one function. "
                 "EXPERIMENTAL.",
        ),
    ] = None,
    branch: Annotated[
        Optional[str],
        typer.Option(
            "--branch",
            help="Compile against this branch on the remote. If omitted, "
                 "auto-detects from the local repo's current branch. The "
                 "remote maintains a worktree per branch so concurrent "
                 "pcdumps on different branches don't clobber each other.",
            envvar="MWCC_DEBUG_BRANCH",
        ),
    ] = None,
    force_iter_first: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first",
            help="Tier 6: reorder the simplification list so named virtuals "
                 "are popped first by colorgraph. Format 'virtIdx[,virtIdx]*'. "
                 "E.g. '32' promotes virtual r32 to the head of the "
                 "simplification stack — it gets first crack at the top-down "
                 "callee-save dispense (r31). Addresses the param-iter-ceiling "
                 "pattern. EXPERIMENTAL — produces DLL-patched binary, NOT "
                 "what real MWCC would emit from any C source.",
        ),
    ] = None,
    force_iter_first_class: Annotated[
        Optional[int],
        typer.Option(
            "--force-iter-first-class",
            help=(
                "Scope --force-iter-first IG indices to one register class "
                "(0=GPR, 1=FPR). Use when the same ig_idx exists in multiple "
                "classes and an FPR/GPR-only hypothesis must avoid disturbing "
                "the other allocator pass."
            ),
        ),
    ] = None,
    force_iter_first_iter: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first-iter",
            help=(
                "Tier 6: reorder simplification list by class and current "
                "iteration position. Format 'class:iter[,class:iter]*'. "
                "Useful for split/spill nodes that lack a stable ig_idx."
            ),
        ),
    ] = None,
    force_iter_first_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first-fn",
            help="Scope --force-iter-first to one function in the TU. Other "
                 "functions compile with their natural simplification order.",
        ),
    ] = None,
    force_select_order: Annotated[
        Optional[str],
        typer.Option(
            "--force-select-order",
            help="Tier 6: explicit alias for --force-iter-first when testing "
                 "allocator selection order. Format 'virtIdx[,virtIdx]*'; "
                 "the first listed node gets first selection priority.",
        ),
    ] = None,
    force_select_order_class: Annotated[
        Optional[int],
        typer.Option(
            "--force-select-order-class",
            help="Scope --force-select-order IG indices to one register class "
                 "(0=GPR, 1=FPR).",
        ),
    ] = None,
    force_select_order_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-select-order-fn",
            help="Scope --force-select-order to one function in the TU.",
        ),
    ] = None,
    force_coalesce: Annotated[
        Optional[str],
        typer.Option(
            "--force-coalesce",
            help="Tier 6: override the conservative coalescer. Format "
                 "'virt=root[,virt=root]*'. E.g. '42=38' forces virtual 42 "
                 "to coalesce into 38; '42=42' un-coalesces 42 back to its "
                 "own root. EXPERIMENTAL.",
        ),
    ] = None,
    force_coalesce_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-coalesce-fn",
            help="Scope --force-coalesce to a single function name in "
                 "the TU. Other functions compile naturally. EXPERIMENTAL.",
        ),
    ] = None,
    force_coalesce_class: Annotated[
        Optional[int],
        typer.Option(
            "--force-coalesce-class",
            help=(
                "Scope --force-coalesce virtual indices to one register class "
                "(0=GPR, 1=FPR)."
            ),
        ),
    ] = None,
    force_remat: Annotated[
        Optional[str],
        typer.Option(
            "--force-remat",
            help="Tier 7: DIAGNOSTIC-ONLY rematerialization operand-slot bias. "
                 "Format 'class:ig=copy|literal[,...]'. Sets or clears the "
                 "observed remat alternate operand selector for a chosen IG "
                 "node after coloring.",
        ),
    ] = None,
    force_remat_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-remat-fn",
            help="Scope --force-remat to a single function name in the TU. "
                 "Other functions compile naturally. EXPERIMENTAL.",
        ),
    ] = None,
    force_schedule: Annotated[
        Optional[str],
        typer.Option(
            "--force-schedule",
            help="Tier 7: pin adjacent same-base load order after MWCC's "
                 "instruction scheduler. Format 'op:beforeOffset>afterOffset"
                 "[,...]'. E.g. 'lwz:0x74>0x70' forces a same-base lwz pair "
                 "at offsets 0x70/0x74 to appear 0x74 first. EXPERIMENTAL.",
        ),
    ] = None,
    force_schedule_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-schedule-fn",
            help="Scope --force-schedule to a single function name in the TU. "
                 "Other functions compile naturally. EXPERIMENTAL.",
        ),
    ] = None,
    force_no_cse: Annotated[
        Optional[str],
        typer.Option(
            "--force-no-cse",
            help="Tier 8: veto selected IRO CommonSubs replacements. Format "
                 "'node[=with][,node[=with]]*'; 'iro:' prefixes and 0x hex "
                 "are accepted and normalized. E.g. 'iro:439=431' skips "
                 "only the replacement logged as 'Replacing common sub at "
                 "439 with 431'. Use --trace-cse first to discover node IDs. "
                 "DIAGNOSTIC-ONLY.",
        ),
    ] = None,
    force_no_cse_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-no-cse-fn",
            help="Scope --force-no-cse to a single function name in the TU. "
                 "Recommended because IRO node IDs are per function/pass.",
        ),
    ] = None,
    trace_cse: Annotated[
        bool,
        typer.Option(
            "--trace-cse",
            help="Trace IRO CommonSubs replacement node IDs without vetoing "
                 "them. Emits 'IRO_CommonSub: replaced node N with M' lines "
                 "so --force-no-cse can be targeted. DIAGNOSTIC-ONLY.",
        ),
    ] = False,
    trace_cse_fn: Annotated[
        Optional[str],
        typer.Option(
            "--trace-cse-fn",
            help="Scope --trace-cse to a single function name in the TU. "
                 "Recommended because IRO node IDs are per function/pass.",
        ),
    ] = None,
):
    """Dump MWCC's internal IR + codegen for a TU and emit pcdump.txt to stdout.

    Compiles the given .c file on a remote Windows host under the mwcc_debug
    patched lmgr326b.dll, which unlocks MWCC's normally-disabled `debuglisting`
    output. The dump shows per-function basic-block structure, every pass of
    the IR optimizer with virtual registers, and the AFTER REGISTER COLORING
    pass with physical-register assignments — useful when diagnosing
    register-allocation mismatches that mismatch-db / opseq / ghidra haven't
    explained.

    On success, the raw pcdump.txt is written to the cache at
    build/mwcc_debug_cache/<unit>.txt by default. Use --output PATH for
    a custom location, or --output - for stdout. Follow-up commands like
    `debug inspect analyze -f FN` auto-resolve the cached pcdump by TU.
    All diagnostics go to stderr. Exit code matches the remote compile's
    exit code (0 = success).

    Setup: see docs/mwcc-debug.md. Requires SSH access to a Windows machine
    that has run_pcdump.ps1 and the patched lmgr326b.dll installed.
    """
    from src.cli.debug import (  # noqa: E402
        DEFAULT_MELEE_ROOT,
        _normalize_force_phys,
        _resolve_src_relative,
        _run_remote_pcdump,
        _score_source_should_stage_through_unit,
        _validate_force_schedule,
        mwcc_debug_scratch_path,
    )
    src_rel = _resolve_src_relative(c_file)
    compile_source_rel = (
        _resolve_src_relative(unit_source, label="unit source")
        if unit_source is not None
        else _infer_remote_unit_source(
            src_rel,
            function=function,
            melee_root=DEFAULT_MELEE_ROOT,
        )
    )
    stage_source_path: Path | None = None
    if compile_source_rel != src_rel:
        if not _score_source_should_stage_through_unit(
            source_rel=src_rel,
            cflags_unit_rel=compile_source_rel,
        ):
            raise typer.BadParameter(
                "remote retained-source staging requires a non-src source "
                "compiled through a src/... --unit-source"
            )
        stage_source_path = DEFAULT_MELEE_ROOT / src_rel

    branch = _resolve_remote_pcdump_branch(branch)

    # Build diagnostic env assignments. The shared remote helper adds the
    # timeout, branch, no-pull, stdin-staging env, and PowerShell invocation.
    cmd_parts: list[str] = []
    if force_phys:
        # Reject embedded quotes/spaces to keep the cmd-line safe, then
        # normalize (strips optional class prefix, emits ambiguity warning).
        if any(c in force_phys for c in '"\'; \t'):
            raise typer.BadParameter(
                "--force-phys must not contain quotes, semicolons, or whitespace"
            )
        force_phys_dll, fp_warnings = _normalize_force_phys(force_phys)
        for w in fp_warnings:
            print(w, file=sys.stderr)
        cmd_parts.append(_cmd_set_env("MWCC_DEBUG_FORCE_PHYS", force_phys_dll))
    if force_phys_iter:
        if any(c in force_phys_iter for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-phys-iter must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(_cmd_set_env(
            "MWCC_DEBUG_FORCE_PHYS_ITER",
            force_phys_iter,
        ))
    if force_phys_fn:
        if any(c in force_phys_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-phys-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(_cmd_set_env(
            "MWCC_DEBUG_FORCE_PHYS_FUNCTION",
            force_phys_fn,
        ))
    if force_iter_first and force_select_order:
        raise typer.BadParameter(
            "--force-select-order and --force-iter-first target the same "
            "selection-order hook; use one spelling per run"
        )
    iter_first_value = force_iter_first or force_select_order
    iter_first_class = (
        force_iter_first_class
        if force_iter_first is not None
        else force_select_order_class
    )
    iter_first_fn = force_iter_first_fn or force_select_order_fn

    if iter_first_value:
        if any(c in iter_first_value for c in '"\'; \t'):
            raise typer.BadParameter(
                "--force-iter-first/--force-select-order must not contain quotes, semicolons, "
                "or whitespace"
            )
        cmd_parts.append(_cmd_set_env(
            "MWCC_DEBUG_FORCE_ITER_FIRST",
            iter_first_value,
        ))
    if iter_first_class is not None:
        if not iter_first_value:
            raise typer.BadParameter(
                "--force-iter-first-class/--force-select-order-class requires "
                "--force-iter-first or --force-select-order"
            )
        cmd_parts.append(_cmd_set_env(
            "MWCC_DEBUG_FORCE_ITER_FIRST_CLASS",
            str(iter_first_class),
        ))
    if force_iter_first_iter:
        if any(c in force_iter_first_iter for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-iter-first-iter must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(_cmd_set_env(
            "MWCC_DEBUG_FORCE_ITER_FIRST_ITER",
            force_iter_first_iter,
        ))
    if iter_first_fn:
        if any(c in iter_first_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-iter-first-fn/--force-select-order-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(
            _cmd_set_env(
                "MWCC_DEBUG_FORCE_ITER_FIRST_FUNCTION",
                iter_first_fn,
            )
        )
    if force_coalesce:
        force_coalesce, force_coalesce_class = _normalize_force_coalesce(
            force_coalesce,
            force_coalesce_class=force_coalesce_class,
        )
        if any(c in force_coalesce for c in '"\'; \t'):
            raise typer.BadParameter(
                "--force-coalesce must not contain quotes, semicolons, "
                "or whitespace"
            )
        cmd_parts.append(_cmd_set_env(
            "MWCC_DEBUG_FORCE_COALESCE",
            force_coalesce,
        ))
    if force_coalesce_fn:
        if any(c in force_coalesce_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-coalesce-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(
            _cmd_set_env(
                "MWCC_DEBUG_FORCE_COALESCE_FUNCTION",
                force_coalesce_fn,
            )
        )
    if force_coalesce_class is not None:
        if force_coalesce_class not in {0, 1}:
            raise typer.BadParameter("--force-coalesce-class must be 0 or 1")
        if not force_coalesce:
            raise typer.BadParameter(
                "--force-coalesce-class requires --force-coalesce"
            )
        cmd_parts.append(
            _cmd_set_env(
                "MWCC_DEBUG_FORCE_COALESCE_CLASS",
                str(force_coalesce_class),
            )
        )
    if force_remat:
        force_remat = _validate_force_remat(force_remat)
        cmd_parts.append(_cmd_set_env("MWCC_DEBUG_FORCE_REMAT", force_remat))
    if force_remat_fn:
        if any(c in force_remat_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-remat-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(
            _cmd_set_env(
                "MWCC_DEBUG_FORCE_REMAT_FUNCTION",
                force_remat_fn,
            )
        )
    if force_schedule:
        force_schedule = _validate_force_schedule(force_schedule)
        cmd_parts.append(_cmd_set_env("MWCC_DEBUG_FORCE_SCHEDULE", force_schedule))
    if force_schedule_fn:
        if any(c in force_schedule_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-schedule-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(
            _cmd_set_env(
                "MWCC_DEBUG_FORCE_SCHEDULE_FUNCTION",
                force_schedule_fn,
            )
        )
    if force_no_cse:
        force_no_cse = _validate_force_no_cse(force_no_cse)
        cmd_parts.append(_cmd_set_env("MWCC_DEBUG_FORCE_NO_CSE", force_no_cse))
    if force_no_cse_fn:
        force_no_cse_fn = _validate_force_no_cse_fn(force_no_cse_fn)
        cmd_parts.append(
            _cmd_set_env(
                "MWCC_DEBUG_FORCE_NO_CSE_FUNCTION",
                force_no_cse_fn,
            )
        )
    if trace_cse:
        cmd_parts.append(_cmd_set_env("MWCC_DEBUG_TRACE_CSE", "1"))
    if trace_cse_fn:
        trace_cse_fn = _validate_force_no_cse_fn(
            trace_cse_fn,
            option="--trace-cse-fn",
        )
        cmd_parts.append(
            _cmd_set_env(
                "MWCC_DEBUG_TRACE_CSE_FUNCTION",
                trace_cse_fn,
            )
        )
    remote_any_forced = any([
        force_phys, force_phys_iter, force_phys_fn,
        iter_first_value, iter_first_class, force_iter_first_iter, iter_first_fn,
        force_coalesce, force_coalesce_fn,
        force_remat, force_remat_fn,
        force_schedule, force_schedule_fn,
        force_no_cse, force_no_cse_fn,
        trace_cse, trace_cse_fn,
    ])
    remote_diagnostic_run = remote_any_forced or stage_source_path is not None

    branch_label = (f" branch={branch}"
                    if branch and branch not in ("master", "main") else "")
    stage_label = (
        f" staged={src_rel}" if stage_source_path is not None else ""
    )
    print(
        f"[mwcc_debug] ssh {host} run_pcdump.ps1 "
        f"{compile_source_rel}{branch_label}{stage_label}",
        file=sys.stderr,
    )

    # Decide where stdout goes. Default behavior changed in H2: if no
    # --output is given, save to the project pcdump cache instead of
    # stdout. This lets follow-up `debug inspect analyze`,
    # `debug inspect guide`, or `debug target score-dump` find the
    # dump automatically without the agent threading file paths.
    # Explicit `--output -` forces stdout (old default).
    use_cache = output is None
    cache_write_tmp: Optional[Path] = None
    if str(output) == "-":
        stdout_dest = sys.stdout.buffer
        out_path_for_msg = "stdout"
        cache_path_used: Optional[Path] = None
    elif use_cache and not remote_diagnostic_run:
        # Strip the `src/` prefix and `.c` suffix to get the unit key.
        unit = compile_source_rel
        if unit.startswith("src/"):
            unit = unit[len("src/"):]
        if unit.endswith(".c"):
            unit = unit[:-2]
        pcdump_cache.ensure_cache_dir(DEFAULT_MELEE_ROOT)
        cache_path_used = pcdump_cache.cache_path(DEFAULT_MELEE_ROOT, unit)
        cache_path_used.parent.mkdir(parents=True, exist_ok=True)
        cache_fd, cache_tmp_name = tempfile.mkstemp(
            prefix=f".{cache_path_used.name}.",
            suffix=".tmp",
            dir=cache_path_used.parent,
        )
        cache_write_tmp = Path(cache_tmp_name)
        stdout_dest = os.fdopen(cache_fd, "wb")
        out_path_for_msg = str(cache_path_used)
    else:
        cache_path_used = None
        if use_cache and remote_diagnostic_run:
            output = mwcc_debug_scratch_path(
                "pcdump_remote_staged" if stage_source_path is not None
                else "pcdump_remote_forced",
                suffix=".txt",
            )
            output.parent.mkdir(parents=True, exist_ok=True)
        stdout_dest = open(output, "wb")
        out_path_for_msg = str(output)

    try:
        remote_result = _run_remote_pcdump(
            source_rel=src_rel,
            compile_source_rel=compile_source_rel,
            host=host,
            remote_script=remote_script,
            timeout=timeout,
            branch=branch,
            no_pull=no_pull,
            stage_source_path=stage_source_path,
            stage_source_label=src_rel if stage_source_path is not None else None,
            extra_env_parts=cmd_parts,
            stream_stdout_to=stdout_dest,
            forward_stderr=True,
        )
        total = remote_result.bytes_written
        exit_code = remote_result.returncode
    finally:
        if str(output) != "-":
            stdout_dest.close()
        if cache_write_tmp is not None and (
            "exit_code" not in locals() or exit_code != 0
        ):
            cache_write_tmp.unlink(missing_ok=True)

    if exit_code == 0:
        if cache_write_tmp is not None:
            cache_write_tmp.replace(cache_path_used)
        print(
            f"[mwcc_debug] wrote {total} bytes to {out_path_for_msg}",
            file=sys.stderr,
        )
        if cache_path_used is not None:
            # Write the content-hash sidecar so follow-up commands can
            # detect freshness by content rather than mtime.  Commands
            # like enumerate-decl-orders and tier3-search restore the
            # source after patching, updating mtime even when unchanged;
            # the sidecar avoids false "stale" warnings after restore.
            try:
                src_file = DEFAULT_MELEE_ROOT / compile_source_rel
                pcdump_cache.write_hash_sidecar(cache_path_used, src_file)
            except OSError:
                pass  # sidecar is best-effort; fall back to mtime on next lookup
            print(
                f"[mwcc_debug] cached — follow-up commands "
                f"(`inspect analyze`, `inspect guide`, "
                f"`target score-dump`, etc.) will auto-resolve "
                f"this dump by function name.",
                file=sys.stderr,
            )
        elif use_cache and remote_diagnostic_run:
            print(
                "[mwcc_debug] diagnostic run — skipping cache sync to avoid "
                f"contaminating baseline. Dump at: {out_path_for_msg}",
                file=sys.stderr,
            )
    else:
        print(
            f"[mwcc_debug] remote exited {exit_code}; {total} bytes captured",
            file=sys.stderr,
        )
        if remote_result.staged_source is not None:
            blocker_sidecar = _remote_retained_source_blocker_sidecar_path(
                out_path_for_msg
            )
            blocker_payload = _remote_retained_source_blocker_payload(
                remote_result,
                function=function,
                branch=branch,
                timeout=timeout,
                out_path_for_msg=out_path_for_msg,
                sidecar_path=blocker_sidecar,
                melee_root=DEFAULT_MELEE_ROOT,
            )
            try:
                _write_remote_retained_source_blocker_sidecar(
                    blocker_payload,
                    blocker_sidecar,
                )
            except OSError as exc:
                print(
                    f"[mwcc_debug] failed to write retained-source blocker "
                    f"json: {exc}",
                    file=sys.stderr,
                )
            else:
                if blocker_sidecar is not None:
                    print(
                        f"[mwcc_debug] retained-source blocker json: "
                        f"{blocker_sidecar}",
                        file=sys.stderr,
                    )
            print(json.dumps(blocker_payload, sort_keys=True), file=sys.stderr)
        if cache_path_used is not None:
            print(
                f"[mwcc_debug] cache not updated: {cache_path_used}",
                file=sys.stderr,
            )

    raise typer.Exit(code=exit_code)


_FORCE_PHYS_CLASS_NAMES = {
    "gpr": 0,
    "int": 0,
    "r": 0,
    "class0": 0,
    "fp": 1,
    "fpr": 1,
    "f": 1,
    "class1": 1,
}
"""Recognized class-prefix names for the ``class:ig_idx:phys`` form.

``gpr`` / ``int`` → GPR class; ``fp`` / ``fpr`` → FP class.
Numeric class IDs are also accepted and passed through to the DLL.
"""



def _validate_force_remat(raw: str, *, option: str = "--force-remat") -> str:
    if any(c in raw for c in '"\'; \t\r\n&|<>^'):
        raise typer.BadParameter(
            f"{option} must not contain quotes, semicolons, whitespace, "
            "or shell metacharacters"
        )
    if not re.fullmatch(r"\d+:\d+=(?:copy|literal)(?:,\d+:\d+=(?:copy|literal))*", raw):
        raise typer.BadParameter(
            f"{option} expects 'class:ig=copy|literal[,class:ig=copy|literal]*'"
        )
    return raw



def _validate_force_no_cse(raw: str, *, option: str = "--force-no-cse") -> str:
    """Normalize force-no-CSE node specs for the DLL."""
    from src.cli.debug import _parse_force_no_cse_node  # noqa: E402
    if not raw:
        raise typer.BadParameter(
            f"{option} requires at least one node or node=with entry"
        )
    if any(c in raw for c in '"\'; \t\r\n&|<>^'):
        raise typer.BadParameter(
            f"{option} must not contain quotes, semicolons, whitespace, "
            "or shell metacharacters"
        )
    out: list[str] = []
    for entry in raw.split(","):
        if not entry:
            raise typer.BadParameter(f"{option} contains an empty entry")
        if entry.count("=") > 1:
            raise typer.BadParameter(
                f"{option} entry {entry!r} is invalid. Expected node or "
                "node=with"
            )
        if "=" in entry:
            at_raw, with_raw = entry.split("=", 1)
            at_node = _parse_force_no_cse_node(at_raw, option=option)
            with_node = _parse_force_no_cse_node(with_raw, option=option)
            out.append(f"{at_node}={with_node}")
        else:
            at_node = _parse_force_no_cse_node(entry, option=option)
            out.append(str(at_node))
    return ",".join(out)



def _validate_force_no_cse_fn(
    raw: str,
    *,
    option: str = "--force-no-cse-fn",
) -> str:
    if any(c in raw for c in '"\'; \t&|<>'):
        raise typer.BadParameter(
            f"{option} must not contain quotes, semicolons, whitespace, "
            "or shell metacharacters"
        )
    if len(raw.encode("utf-8")) >= 256:
        raise typer.BadParameter(
            f"{option} must fit in mwcc_debug's 255-byte function-name "
            "scope buffer"
        )
    return raw



def _cmd_set_env(name: str, value: str) -> str:
    """Build a cmd.exe env assignment without leaking separator whitespace."""
    if any(c in value for c in '"\r\n'):
        raise typer.BadParameter(
            f"{name} value must not contain quotes or newlines"
        )
    return f'set "{name}={value}"'



def _count_function_defs(source: str) -> int:
    """Coarse count of function definitions in a C TU. Used as a safety
    heuristic for the --force-coalesce / --force-phys multi-fn guard:
    when N>=2, force-* without -fn is risky enough to refuse.

    Heuristic: count lines that look like `<retval> <name>(...)` at the
    top of the file (column 0), excluding obvious non-definitions
    (statements, declarations ending in `;`). Strings + comments are
    stripped first. Not exact — `static inline` definitions and
    K&R prototypes can over- or under-count — but good enough for a
    "are there multiple functions in this TU" gate.
    """
    # Strip strings + comments crudely (newline-preserving)
    cleaned = re.sub(r'/\*.*?\*/', '', source, flags=re.DOTALL)
    cleaned = re.sub(r'//[^\n]*', '', cleaned)
    cleaned = re.sub(r'"[^"\n]*"', '""', cleaned)
    # Function-definition heuristic: at column 0, a line that has
    # `name(...)` followed (eventually) by `{` not `;`. Count by
    # searching for `^<type-or-attr-tokens>+<name>(...)` followed by
    # `{` somewhere within a few hundred chars (allows multiline
    # parameter lists).
    pattern = re.compile(
        r'^[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^)]*\)\s*'
        r'(?:[A-Za-z_]\w*\s*)*\{',
        re.MULTILINE,
    )
    return len(pattern.findall(cleaned))



def _normalize_force_coalesce(
    force_coalesce: str,
    *,
    force_coalesce_class: int | None = None,
) -> tuple[str, int | None]:
    from src.cli.debug import _parse_force_coalesce_pair_specs  # noqa: E402
    if force_coalesce_class is not None and force_coalesce_class not in {0, 1}:
        raise typer.BadParameter("--force-coalesce-class must be 0 or 1")
    specs = _parse_force_coalesce_pair_specs(force_coalesce)
    inferred_classes = {
        class_id for _left, _right, class_id in specs if class_id is not None
    }
    if len(inferred_classes) > 1:
        raise typer.BadParameter(
            "--force-coalesce cannot mix GPR and FPR pairs in one override"
        )
    inferred_class = next(iter(inferred_classes), None)
    if (
        force_coalesce_class is not None
        and inferred_class is not None
        and force_coalesce_class != inferred_class
    ):
        raise typer.BadParameter(
            "--force-coalesce-class conflicts with prefixed --force-coalesce pair"
        )
    class_id = (
        force_coalesce_class
        if force_coalesce_class is not None
        else inferred_class
    )
    normalized = ",".join(f"{left}={right}" for left, right, _class_id in specs)
    return normalized, class_id



def _debug_dump_local_wibo_runtime_failure(stderr: str) -> str | None:
    from src.cli.debug import _WIBO_MISSING_IMPORT_RE  # noqa: E402
    match = _WIBO_MISSING_IMPORT_RE.search(stderr)
    if match is None:
        return None
    import_name = match.group("import")
    dll_name = match.group("dll")
    return (
        "[debug dump local] local wibo aborted before producing a pcdump: "
        f"missing Windows import {import_name} from {dll_name}. This usually "
        "means the local wibo/debug compiler setup is stale or incompatible. "
        "Run `melee-agent debug dump doctor --repair` (or rerun "
        "`melee-agent debug dump setup`) and retry; use `debug dump remote` "
        "while local wibo is unavailable."
    )



def _build_local_wibo() -> Optional[Path]:
    """Build the vendored wibo via tools/mwcc_debug/build_wibo.sh.

    Returns the built path or None on failure.
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT  # noqa: PLC0415

    build_script = (
        DEFAULT_MELEE_ROOT / "tools" / "mwcc_debug" / "build_wibo.sh"
    )
    if not build_script.exists():
        return None
    try:
        subprocess.run(
            [str(build_script)],
            cwd=build_script.parent,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    out = build_script.parent / "bin" / "wibo"
    return out if out.exists() else None



@dataclasses.dataclass(frozen=True)
class _DumpSetupCheck:
    label: str
    ok: bool
    detail: str



def _check_path(label: str, path: Path, *, executable: bool = False) -> _DumpSetupCheck:
    if not path.exists():
        return _DumpSetupCheck(label, False, f"missing: {path}")
    if executable and not os.access(path, os.X_OK):
        return _DumpSetupCheck(label, False, f"not executable: {path}")
    return _DumpSetupCheck(label, True, str(path))



def _check_dll_is_pe(label: str, path: Path) -> _DumpSetupCheck:
    """Sanity-check a deployed DLL is a real PE binary, not a corrupted stub.

    Freshness checks are mtime-only, so an 8-byte garbage file (e.g. from an
    interrupted copy or a corrupt-DLL experiment) PASSES doctor while making
    every dump SIGABRT. Verified failure mode 2026-06-10."""
    if not path.exists():
        return _DumpSetupCheck(label, False, f"missing: {path}")
    try:
        size = path.stat().st_size
        magic = path.open("rb").read(2)
    except OSError as exc:
        return _DumpSetupCheck(label, False, f"unreadable: {path} ({exc})")
    if size < 4096 or magic != b"MZ":
        return _DumpSetupCheck(
            label, False,
            f"not a PE DLL ({size} bytes, magic={magic!r}): {path} — "
            f"redeploy via `debug dump setup --rebuild-dll`")
    return _DumpSetupCheck(label, True, f"{path} ({size} bytes, MZ)")



def _check_mwcc_debug_dll_features(label: str, path: Path) -> _DumpSetupCheck:
    from src.cli.debug import (  # noqa: E402
        _MWCC_DEBUG_DLL_FEATURE_PREFIX,
        _MWCC_DEBUG_LEGACY_HOOK_STRINGS,
        _MWCC_DEBUG_REQUIRED_DLL_FEATURES,
    )
    if not path.exists():
        return _DumpSetupCheck(label, False, f"missing: {path}")
    try:
        text = path.read_bytes().decode("latin-1", errors="ignore")
    except OSError as exc:
        return _DumpSetupCheck(label, False, f"unreadable: {path} ({exc})")
    marker = text.find(_MWCC_DEBUG_DLL_FEATURE_PREFIX)
    if marker < 0:
        missing_legacy = [
            probe
            for probe in _MWCC_DEBUG_LEGACY_HOOK_STRINGS
            if probe not in text
        ]
        if not missing_legacy:
            return _DumpSetupCheck(
                label,
                True,
                (
                    f"{path} (legacy hook strings; lacks "
                    f"{_MWCC_DEBUG_DLL_FEATURE_PREFIX} manifest, so exact "
                    "feature version is unknown — rebuild/redeploy when you "
                    "need newly-added hooks)"
                ),
            )
        return _DumpSetupCheck(
            label,
            False,
            (
                f"{path} lacks {_MWCC_DEBUG_DLL_FEATURE_PREFIX} manifest; "
                f"legacy hook probes missing {', '.join(missing_legacy[:4])}"
                + (
                    f" (+{len(missing_legacy) - 4} more)"
                    if len(missing_legacy) > 4
                    else ""
                )
                + "; "
                "rebuild/redeploy via `debug dump setup --rebuild-dll`"
            ),
        )
    manifest = text[marker: marker + 512]
    missing = [
        feature
        for feature in _MWCC_DEBUG_REQUIRED_DLL_FEATURES
        if feature not in manifest
    ]
    if missing:
        return _DumpSetupCheck(
            label,
            False,
            (
                f"{path} feature manifest is missing {', '.join(missing)}; "
                "rebuild/redeploy via `debug dump setup --rebuild-dll`"
            ),
        )
    version = manifest.split(";", 1)[0]
    return _DumpSetupCheck(label, True, f"{path} ({version})")



def _format_smoke_process_output(result: Any) -> str:
    output = "\n".join(
        part.strip()
        for part in (getattr(result, "stdout", ""), getattr(result, "stderr", ""))
        if part and part.strip()
    )
    if not output:
        return ""
    lines = output.splitlines()
    tail = "\n".join(lines[-8:])
    return f"; output:\n{tail}"



def _path_newer_than(left: Path, right: Path) -> bool:
    return left.stat().st_mtime_ns > right.stat().st_mtime_ns



def _dll_needs_rebuild(dll_path: Path, source_path: Path) -> bool:
    if not dll_path.exists():
        return True
    if not source_path.exists():
        return False
    return _path_newer_than(source_path, dll_path)



def _check_mwcc_debug_dll_freshness(
    tools_dir: Path,
    compiler_dir: Path,
) -> _DumpSetupCheck:
    source = tools_dir / "mwcc_debug.c"
    built_dll = tools_dir / "MWDBG326.dll"
    deployed_dll = compiler_dir / "MWDBG326.dll"
    missing = [p for p in (source, built_dll, deployed_dll) if not p.exists()]
    if missing:
        missing_s = ", ".join(str(p) for p in missing)
        return _DumpSetupCheck(
            "mwcc_debug DLL freshness",
            False,
            f"missing freshness input: {missing_s}",
        )

    stale: list[str] = []
    if _path_newer_than(source, built_dll):
        stale.append(f"{source} is newer than DLL {built_dll}")
    if _path_newer_than(source, deployed_dll):
        stale.append(f"{source} is newer than deployed DLL {deployed_dll}")
    elif _path_newer_than(built_dll, deployed_dll):
        stale.append(f"{built_dll} is newer than deployed DLL {deployed_dll}")
    if stale:
        return _DumpSetupCheck(
            "mwcc_debug DLL freshness",
            False,
            "; ".join(stale),
        )
    return _DumpSetupCheck(
        "mwcc_debug DLL freshness",
        True,
        f"{built_dll} and {deployed_dll} are current for {source}",
    )



def _local_dump_setup_checks() -> list[_DumpSetupCheck]:
    from src.cli.debug import DEFAULT_MELEE_ROOT, _find_compiler_dir, _find_wibo  # noqa: E402
    melee_root = DEFAULT_MELEE_ROOT
    compiler_dir = _find_compiler_dir()
    tools_dir = melee_root / "tools" / "mwcc_debug"
    wibo = _find_wibo()
    checks = [
        (
            _DumpSetupCheck(
                "wibo",
                False,
                "missing: set $MWCC_DEBUG_WIBO or build vendored wibo",
            )
            if wibo is None
            else _check_path("wibo", wibo, executable=True)
        ),
        _check_path("compiler directory", compiler_dir),
        _check_path("stock compiler", compiler_dir / "mwcceppc.exe"),
        _check_path("patched compiler", compiler_dir / "mwcceppc_debug.exe"),
        _check_path("mwcc_debug DLL source", tools_dir / "MWDBG326.dll"),
        _check_path("deployed DLL", compiler_dir / "MWDBG326.dll"),
        _check_dll_is_pe("deployed DLL integrity", compiler_dir / "MWDBG326.dll"),
        _check_mwcc_debug_dll_features(
            "mwcc_debug DLL features",
            compiler_dir / "MWDBG326.dll",
        ),
        _check_path("mwcc_debug C source", tools_dir / "mwcc_debug.c"),
        _check_mwcc_debug_dll_freshness(tools_dir, compiler_dir),
        _check_path("wibo build script", tools_dir / "build_wibo.sh"),
        _check_path("DLL build script", tools_dir / "build_macos.sh"),
        _check_path("compiler patcher", tools_dir / "patch_mwcceppc_for_wibo.py"),
    ]
    return checks



def _print_local_dump_setup_checks(checks: list[_DumpSetupCheck]) -> None:
    for check in checks:
        status = "PASS" if check.ok else "FAIL"
        print(f"{status}\t{check.label}\t{check.detail}")



def _force_object_delta_baseline_env(
    env: Mapping[str, str],
    pcdump_name: str,
) -> dict[str, str]:
    baseline_env = dict(env)
    baseline_env.pop("MWCC_DEBUG_FORCE_COALESCE", None)
    baseline_env.pop("MWCC_DEBUG_FORCE_COALESCE_FUNCTION", None)
    baseline_env.pop("MWCC_DEBUG_FORCE_COALESCE_CLASS", None)
    baseline_env["MWCC_DEBUG_PCDUMP_PATH"] = pcdump_name
    return baseline_env



def _verify_force_coalesce_object_delta(
    *,
    args: list[str],
    env: Mapping[str, str],
    obj_target: Path,
    melee_root: Path,
    scratch_root: Path,
    timeout: float,
) -> None:
    from src.cli.debug import mwcc_debug_scratch_path  # noqa: E402
    baseline_obj = mwcc_debug_scratch_path(
        "pcdump_local_force_delta",
        suffix=".natural.o",
        root=scratch_root,
    )
    baseline_pcdump = mwcc_debug_scratch_path(
        "pcdump_force_delta",
        suffix=".txt",
        root=scratch_root,
    )
    baseline_args = [*args]
    try:
        output_flag_index = len(baseline_args) - 1 - baseline_args[::-1].index("-o")
    except ValueError:
        typer.echo(
            "[debug dump local] force-coalesce object delta check could not "
            "locate the compiler -o argument.",
            err=True,
        )
        raise typer.Exit(5)
    if output_flag_index + 1 >= len(baseline_args):
        typer.echo(
            "[debug dump local] force-coalesce object delta check found a "
            "compiler -o argument without an object path.",
            err=True,
        )
        raise typer.Exit(5)
    baseline_args[output_flag_index + 1] = str(baseline_obj)
    baseline_env = _force_object_delta_baseline_env(env, str(baseline_pcdump))

    try:
        proc = subprocess.run(
            baseline_args,
            cwd=melee_root,
            env=baseline_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        typer.echo(
            "[debug dump local] force-coalesce object delta check timed out "
            f"after {timeout:g}s while compiling the coalesce-off baseline object.",
            err=True,
        )
        raise typer.Exit(5) from exc
    finally:
        try:
            baseline_pcdump.unlink()
        except OSError:
            pass

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        typer.echo(
            "[debug dump local] force-coalesce object delta check could not "
            f"compile the coalesce-off baseline object (exit {proc.returncode})"
            + (f": {detail}" if detail else ""),
            err=True,
        )
        raise typer.Exit(5)
    if not baseline_obj.exists():
        typer.echo(
            "[debug dump local] force-coalesce object delta check could not "
            f"find coalesce-off baseline object at {baseline_obj}.",
            err=True,
        )
        raise typer.Exit(5)

    forced_bytes = obj_target.read_bytes()
    baseline_bytes = baseline_obj.read_bytes()
    forced_hash = hashlib.sha256(forced_bytes).hexdigest()[:16]
    baseline_hash = hashlib.sha256(baseline_bytes).hexdigest()[:16]
    if forced_bytes == baseline_bytes:
        typer.echo(
            "[debug dump local] force-coalesce object delta check failed: "
            "forced .o is byte-identical to the coalesce-off baseline "
            f"(sha256={forced_hash}). Hook engagement did not change emitted "
            "code for this source/pair.",
            err=True,
        )
        raise typer.Exit(5)
    typer.echo(
        "[debug dump local] force-coalesce object delta verified: forced .o "
        f"differs from coalesce-off baseline (forced sha256={forced_hash}, "
        f"baseline sha256={baseline_hash}).",
        err=True,
    )



@dump_app.command(name="setup")
def setup_local(
    rebuild_dll: Annotated[
        bool,
        typer.Option(
            "--rebuild-dll",
            help="Rebuild the mwcc_debug DLL via build_macos.sh even if "
                 "it already exists.",
        ),
    ] = False,
) -> None:
    """One-time setup for local mwcc_debug pcdump (macOS+wibo).

    Steps:
    1. Verify wibo binary is available (built via melee-harness).
    2. Build the mwcc_debug DLL via tools/mwcc_debug/build_macos.sh
       if not already present.
    3. Patch a copy of mwcceppc.exe to import MWDBG326.dll instead
       of LMGR326B.dll (lives next to the stock compiler as
       mwcceppc_debug.exe; stock compiler untouched).
    4. Copy the DLL into the compiler dir so wibo finds it.

    After setup, `melee-agent debug dump local <c_file>` works.

    Wibo dependency: this command expects Luke Champine's patched wibo
    at <melee>/../melee-harness/bin/wibo (or path in $MWCC_DEBUG_WIBO).
    Clone melee-harness adjacent to melee and build via its setup.sh.
    """
    from src.cli.debug import (  # noqa: E402
        DEFAULT_MELEE_ROOT,
        _build_local_dll,
        _find_compiler_dir,
        _find_wibo,
        _smoke_mwcc_debug_compiler,
    )
    melee_root = DEFAULT_MELEE_ROOT
    compiler_dir = _find_compiler_dir()

    # 1. Locate wibo, or build it
    wibo = _find_wibo()
    if wibo is None:
        print("[..] wibo not found; building via build_wibo.sh...")
        wibo = _build_local_wibo()
        if wibo is None:
            typer.echo(
                "wibo build failed. See tools/mwcc_debug/build_wibo.sh.\n"
                "Alternatives: set $MWCC_DEBUG_WIBO=<path-to-wibo-binary>.",
                err=True,
            )
            raise typer.Exit(2)
    print(f"[ok] wibo: {wibo}")

    # 2. Build the DLL if needed
    dll_c_source = melee_root / "tools" / "mwcc_debug" / "mwcc_debug.c"
    dll_src = melee_root / "tools" / "mwcc_debug" / "MWDBG326.dll"
    dll_is_stale = _dll_needs_rebuild(dll_src, dll_c_source)
    if rebuild_dll or dll_is_stale:
        if rebuild_dll:
            reason = "--rebuild-dll requested"
        elif dll_src.exists():
            reason = "mwcc_debug.c is newer than MWDBG326.dll"
        else:
            reason = "MWDBG326.dll is missing"
        print(f"[..] building mwcc_debug DLL via build_macos.sh ({reason})...")
        built = _build_local_dll()
        if built is None or not built.exists():
            typer.echo(
                "DLL build failed. Check tools/mwcc_debug/build_macos.sh.",
                err=True,
            )
            raise typer.Exit(3)
        dll_src = built
    print(f"[ok] DLL:  {dll_src}")

    # 3. Patch the compiler if needed
    stock_compiler = compiler_dir / "mwcceppc.exe"
    debug_compiler = compiler_dir / "mwcceppc_debug.exe"
    patcher = melee_root / "tools" / "mwcc_debug" / "patch_mwcceppc_for_wibo.py"

    if not stock_compiler.exists():
        typer.echo(
            f"stock compiler not found: {stock_compiler}. "
            f"Run `python configure.py` first to download it.",
            err=True,
        )
        raise typer.Exit(4)
    if not patcher.exists():
        typer.echo(
            f"patcher script not found: {patcher}. "
            f"Pull latest tools/mwcc_debug/.",
            err=True,
        )
        raise typer.Exit(5)

    print(f"[..] patching {stock_compiler.name} -> {debug_compiler.name}...")
    try:
        subprocess.run(
            [
                "python3", str(patcher),
                str(stock_compiler), str(debug_compiler),
                "--dll", str(dll_src),
            ],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        typer.echo(f"patcher failed: {e}", err=True)
        raise typer.Exit(6)
    print(f"[ok] compiler patched: {debug_compiler}")
    print(f"[ok] DLL deployed:     {compiler_dir / 'MWDBG326.dll'}")
    smoke = _smoke_mwcc_debug_compiler(wibo, compiler_dir)
    if not smoke.ok:
        typer.echo(f"pcdump smoke failed: {smoke.detail}", err=True)
        raise typer.Exit(7)
    print(f"[ok] pcdump smoke:    {smoke.detail}")
    print()
    print("Setup complete. Try:")
    print("  melee-agent debug dump local src/melee/mn/mnvibration.c")



@dump_app.command(name="doctor")
def setup_doctor(
    repair: Annotated[
        bool,
        typer.Option(
            "--repair",
            help="Run `debug dump setup` when required checks are missing, "
                 "then report the post-setup state.",
        ),
    ] = False,
) -> None:
    """Diagnose local mwcc_debug setup before dump/inspect workflows fail."""
    checks = _local_dump_setup_checks()
    failures = [check for check in checks if not check.ok]

    if failures and repair:
        print("REPAIR\tRunning: melee-agent debug dump setup")
        setup_local(rebuild_dll=False)
        checks = _local_dump_setup_checks()
        failures = [check for check in checks if not check.ok]

    _print_local_dump_setup_checks(checks)
    if failures:
        print("NEXT\tRun: melee-agent debug dump setup")
        print("NEXT\tOr retry doctor with: melee-agent debug dump doctor --repair")
        raise typer.Exit(2)

    print("OK\tready for `melee-agent debug dump local`")



def _raise_pcdump_local_watchdog_exit(killed_by_watchdog: bool) -> None:
    if killed_by_watchdog:
        raise typer.Exit(124)



def _compiled_source_snapshot_still_current(
    src_path: Path,
    compiled_digest: Optional[str],
    *,
    settle_seconds: Optional[float] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[bool, Optional[str]]:
    from src.cli.debug import _cache_settle_seconds  # noqa: E402
    if compiled_digest is None:
        return True, None
    seconds = _cache_settle_seconds() if settle_seconds is None else settle_seconds
    if seconds > 0:
        sleep_fn(seconds)
    try:
        current_digest = pcdump_cache.source_digest(src_path)
    except OSError:
        return False, None
    return current_digest == compiled_digest, current_digest



def _restore_object_report_cmd_for_unit(unit: str) -> list[str]:
    return [
        "ninja",
        f"build/GALE01/src/{unit}.o",
        "build/GALE01/report.json",
    ]



def _ninja_dry_run_planned_steps(output: str) -> int:
    total_steps = 0
    fallback_steps = 0
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "ninja: no work to do.":
            continue
        match = re.match(r"^\[(\d+)/(\d+)\]", stripped)
        if match:
            total_steps = max(total_steps, int(match.group(2)))
        else:
            fallback_steps += 1
    return total_steps or fallback_steps



def _make_expensive_restore_result(
    cmd: list[str],
    *,
    planned_steps: int,
    max_steps: int,
    dry_run_output: str = "",
) -> subprocess.CompletedProcess[str]:
    preview_lines = [
        line.strip()
        for line in dry_run_output.splitlines()
        if line.strip()
    ][:8]
    preview = "\n".join(f"  {line}" for line in preview_lines)
    stderr = (
        f"[restore] refusing to launch restore: ninja dry-run would run "
        f"{planned_steps} ninja step(s), above "
        f"MWCC_DEBUG_RESTORE_MAX_STEPS={max_steps}.\n"
        f"This can expand into a large rebuild. Re-run with "
        f"`melee-agent debug dump restore-object-report <source.c> --force` "
        f"or raise MWCC_DEBUG_RESTORE_MAX_STEPS if you intentionally want "
        f"to launch it.\n"
        f"[restore] If worktree-doctor reports `build/GALE01/report.json "
        f"is older than build.ninja`, ninja must treat report generation as "
        f"stale and may fan out through many compile edges. There is no "
        f"metadata-only repair for that generated report/object state; run "
        f"`python configure.py` first if build metadata changed, then retry "
        f"the managed restore."
    )
    if preview:
        stderr += f"\n[restore] dry-run preview:\n{preview}"
    return subprocess.CompletedProcess(cmd, 125, "", stderr)



def _pcdump_local_missing_diff_target_hint(
    function: str,
    *,
    src_rel: str,
    explicit: bool,
) -> str:
    if explicit:
        return (
            f"[diff] target function {function!r} is not in report.json. "
            f"Check the spelling, run `ninja build/GALE01/report.json` if "
            f"the report is stale, or pass `--function <function_name>` for "
            f"a report-backed function in {src_rel}."
        )
    return (
        f"[diff] inferred target function {function!r} from the first "
        f"function definition in {src_rel}, but it is not in report.json. "
        f"The first function may be a static inline helper. Re-run with "
        f"`--function <function_name>` for the non-inline function you want "
        f"to compare."
    )



@dump_app.command(name="restore-object-report")
def restore_object_report(
    c_file: Annotated[
        str,
        typer.Argument(
            help="Path to the .c file whose object/report state should be restored.",
        ),
    ],
    timeout: Annotated[
        Optional[float],
        typer.Option(
            "--timeout",
            help="Restore timeout in seconds. Defaults to "
                 "MWCC_DEBUG_RESTORE_TIMEOUT, then MWCC_DEBUG_HANG_TIMEOUT, "
                 "then 180.",
        ),
    ] = None,
    max_steps: Annotated[
        Optional[int],
        typer.Option(
            "--max-steps",
            help="Maximum ninja dry-run steps allowed before refusing to "
                 "launch restore. Defaults to MWCC_DEBUG_RESTORE_MAX_STEPS "
                 "(64).",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Run even when the dry-run plan exceeds --max-steps.",
        ),
    ] = False,
) -> None:
    """Safely restore one source's object and build report.

    This is the managed cleanup path used by match-iter-first --auto-verify.
    It previews the ninja plan first, refuses unexpectedly large rebuilds by
    default, and runs the restore in an owned process group with a timeout.
    """
    from src.cli.debug import (  # noqa: E402
        DEFAULT_MELEE_ROOT,
        _resolve_auto_verify_restore_max_steps,
        _resolve_auto_verify_restore_timeout,
        _resolve_src_relative,
        _restore_object_report_for_unit,
    )
    melee_root = DEFAULT_MELEE_ROOT
    src_rel = _resolve_src_relative(c_file)
    unit = src_rel[:-2].removeprefix("src/")
    if timeout is None:
        timeout_s, timeout_source = _resolve_auto_verify_restore_timeout()
    else:
        timeout_s, timeout_source = timeout, "--timeout"
    max_step_count = (
        max_steps
        if max_steps is not None
        else _resolve_auto_verify_restore_max_steps()
    )
    print(
        f"[restore] timeout: {timeout_s:g}s ({timeout_source})",
        file=sys.stderr,
    )
    print(
        f"[restore] max dry-run steps: {max_step_count}",
        file=sys.stderr,
    )
    proc, planned_steps = _restore_object_report_for_unit(
        unit=unit,
        melee_root=melee_root,
        timeout_s=timeout_s,
        max_steps=max_step_count,
        force=force,
    )
    print(
        f"[restore] planned ninja steps: {planned_steps}",
        file=sys.stderr,
    )
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        typer.echo(proc.stderr, err=True)
    if proc.returncode != 0:
        raise typer.Exit(proc.returncode)


@dump_app.command(name="local")
def pcdump_local(
    c_file: Annotated[
        Optional[str],
        typer.Argument(
            help=(
                "Path to a .c file in the melee repo. If omitted, --function "
                "is resolved through report.json and that function's source "
                "TU is refreshed."
            ),
        ),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Output path for the dump. Default: cache it under "
                 "build/mwcc_debug_cache/<unit>.txt. Use '-' for stdout.",
        ),
    ] = None,
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help="Tier 5: allocator bias by function/class-scoped ig_idx. Format "
                 "'virtIdx:physReg[,...]' or 'class:virtIdx:physReg[,...]'. "
                 "Class-scoped entries are passed through to the DLL and only "
                 "apply to that register class. Logs are written into the "
                 "pcdump; application logs are captured there. By default "
                 "applies to every function in the TU — scope with "
                 "--force-phys-fn on multi-function TUs because the same "
                 "ig_idx values can appear in unrelated functions. "
                 "Accepts up to 1024 entries; overflow is a hard pcdump "
                 "error, not a silent partial apply; logs do not appear on "
                 "CLI stderr. "
                 "DIAGNOSTIC-ONLY: uses the patched debug compiler and does "
                 "not affect production ninja builds.",
        ),
    ] = None,
    force_phys_iter: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys-iter",
            help="Tier 5: allocator bias by colorgraph iteration "
                 "position (class:iter:phys[,...]). Use when "
                 "--force-phys can't target a node by ig_idx (rare, "
                 "but happens for split/spill nodes created post-IG-"
                 "build). E.g. '0:0:31' = class 0 (GPR), iter 0, "
                 "force to r31. Accepts up to 1024 entries. Logs are written "
                 "into the pcdump; application logs are captured there. "
                 "DIAGNOSTIC-ONLY: uses "
                 "the patched debug "
                 "compiler and does not affect production ninja builds.",
        ),
    ] = None,
    force_phys_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys-fn",
            help="Scope --force-phys and --force-phys-iter to a "
                 "single function name (mirrors --force-coalesce-fn).",
        ),
    ] = None,
    force_iter_first: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first",
            help="Tier 6: reorder simplification list. By default this "
                 "applies to every function in the TU; scope with "
                 "--force-iter-first-fn on multi-function TUs. "
                 "DIAGNOSTIC-ONLY: uses the patched debug compiler and does "
                 "not affect production ninja builds.",
        ),
    ] = None,
    force_iter_first_class: Annotated[
        Optional[int],
        typer.Option(
            "--force-iter-first-class",
            help=(
                "Scope --force-iter-first IG indices to one register class "
                "(0=GPR, 1=FPR), preventing an FPR-only probe from reordering "
                "same-numbered GPR nodes or vice versa."
            ),
        ),
    ] = None,
    force_iter_first_iter: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first-iter",
            help=(
                "Tier 6: reorder simplification list by class and current "
                "iteration position. Format 'class:iter[,class:iter]*'. "
                "Useful for split/spill nodes that lack a stable ig_idx."
            ),
        ),
    ] = None,
    force_iter_first_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first-fn",
            help="Scope --force-iter-first to a single function name. "
                 "Other functions in the same TU compile with their "
                 "natural simplification order. E.g. "
                 "'--force-iter-first-fn mnVibration_80247510 "
                 "--force-iter-first 151,48'.",
        ),
    ] = None,
    force_select_order: Annotated[
        Optional[str],
        typer.Option(
            "--force-select-order",
            help="Tier 6: explicit alias for --force-iter-first when testing "
                 "allocator selection order. Format 'virtIdx[,virtIdx]*'; "
                 "the first listed node gets first selection priority. "
                 "DIAGNOSTIC-ONLY: uses the patched debug compiler and does "
                 "not affect production ninja builds.",
        ),
    ] = None,
    force_select_order_class: Annotated[
        Optional[int],
        typer.Option(
            "--force-select-order-class",
            help=(
                "Scope --force-select-order IG indices to one register class "
                "(0=GPR, 1=FPR), matching --force-iter-first-class."
            ),
        ),
    ] = None,
    force_select_order_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-select-order-fn",
            help="Scope --force-select-order to a single function name. "
                 "Other functions in the same TU compile with their "
                 "natural selection order.",
        ),
    ] = None,
    force_coalesce: Annotated[
        Optional[str],
        typer.Option(
            "--force-coalesce",
            help="Tier 6: override the conservative coalescer's union-find "
                 "decisions. Format 'virt=root[,virt=root]*'. E.g. '42=38' "
                 "forces virtual 42 to coalesce into virtual 38; '42=42' "
                 "un-coalesces 42 back to its own root. By default applies "
                 "to EVERY coalesce invocation in the TU (out-of-bounds "
                 "pairs are silently skipped). For multi-function TUs "
                 "where one function's overrides would corrupt others, "
                 "scope with --force-coalesce-fn. EXPERIMENTAL — forcing "
                 "two interfering virtuals to coalesce produces "
                 "incorrect code. DIAGNOSTIC-ONLY: uses the patched debug "
                 "compiler and does not affect production ninja builds. "
                 "When combined with --keep-obj, also compiles a coalesce-off "
                 "baseline and fails if the forced object is byte-identical.",
        ),
    ] = None,
    force_coalesce_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-coalesce-fn",
            help="Scope --force-coalesce to a single function name. "
                 "When set, overrides only apply when the currently-"
                 "compiling function (captured by mwcc_debug's debuglisting "
                 "hook) matches the given name exactly. Other functions in "
                 "the same TU compile naturally — prevents one function's "
                 "experimental overrides from corrupting earlier or later "
                 "functions. E.g. '--force-coalesce-fn mnVibration_802474C4 "
                 "--force-coalesce 32=87'.",
        ),
    ] = None,
    force_coalesce_class: Annotated[
        Optional[int],
        typer.Option(
            "--force-coalesce-class",
            help=(
                "Scope --force-coalesce virtual indices to one register class "
                "(0=GPR, 1=FPR)."
            ),
        ),
    ] = None,
    force_remat: Annotated[
        Optional[str],
        typer.Option(
            "--force-remat",
            help="Tier 7: rematerialization operand-slot bias. Format "
                 "'class:ig=copy|literal[,...]'. Sets or clears the observed "
                 "alternate remat operand selector for a chosen IG node after "
                 "coloring. By default applies globally — scope with "
                 "--force-remat-fn. DIAGNOSTIC-ONLY: uses the patched debug "
                 "compiler and does not affect production ninja builds.",
        ),
    ] = None,
    force_remat_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-remat-fn",
            help="Scope --force-remat to a single function name. Other "
                 "functions in the same TU compile with their natural "
                 "rematerialization choices.",
        ),
    ] = None,
    force_schedule: Annotated[
        Optional[str],
        typer.Option(
            "--force-schedule",
            help="Tier 7: pin adjacent or one-instruction-straddled "
                 "same-base load order after MWCC instruction scheduling. "
                 "Format 'op:beforeOffset>afterOffset[,...]'. E.g. "
                 "'lwz:0x74>0x70' forces a same-base lwz pair at offsets "
                 "0x70/0x74 to emit 0x74 first. Non-load code-offset "
                 "windows are explain-only via `debug inspect "
                 "explain-schedule --checkdiff-json`. By default applies "
                 "globally — scope with --force-schedule-fn. "
                 "DIAGNOSTIC-ONLY: uses the patched debug compiler and does "
                 "not affect production ninja builds.",
        ),
    ] = None,
    force_schedule_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-schedule-fn",
            help="Scope --force-schedule to a single function name. Other "
                 "functions in the same TU compile with their natural "
                 "schedule.",
        ),
    ] = None,
    force_no_cse: Annotated[
        Optional[str],
        typer.Option(
            "--force-no-cse",
            help="Tier 8: veto selected front-end IRO CommonSubs replacements. "
                 "Format 'node[=with][,node[=with]]*'; 'iro:' prefixes and "
                 "0x hex are accepted and normalized. Use --trace-cse first "
                 "to discover the replacement node IDs. By default applies "
                 "globally — scope with --force-no-cse-fn. DIAGNOSTIC-ONLY.",
        ),
    ] = None,
    force_no_cse_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-no-cse-fn",
            help="Scope --force-no-cse to a single function name. Other "
                 "functions in the same TU compile with their natural CSE.",
        ),
    ] = None,
    trace_cse: Annotated[
        bool,
        typer.Option(
            "--trace-cse",
            help="Trace IRO CommonSubs replacement node IDs without vetoing "
                 "them. Emits 'IRO_CommonSub: replaced node N with M' lines "
                 "so --force-no-cse can be targeted. Uses --function as the "
                 "default scope when present. DIAGNOSTIC-ONLY.",
        ),
    ] = False,
    trace_cse_fn: Annotated[
        Optional[str],
        typer.Option(
            "--trace-cse-fn",
            help="Scope --trace-cse to a single function name. Overrides the "
                 "--function default scope when both are present.",
        ),
    ] = None,
    wibo: Annotated[
        Optional[Path],
        typer.Option(
            "--wibo",
            help="Path to wibo binary. Default: auto-resolve from "
                 "$MWCC_DEBUG_WIBO or ../melee-harness/bin/wibo.",
        ),
    ] = None,
    keep_obj: Annotated[
        Optional[Path],
        typer.Option(
            "--keep-obj",
            help="Preserve the compiled .o at this path instead of "
                 "discarding it. The default behavior is to discard, "
                 "but for force-coalesce / force-phys hypothesis "
                 "testing the .o is exactly what you need to feed into "
                 "objdiff/checkdiff. Path can be absolute or relative "
                 "to the melee root.",
        ),
    ] = None,
    diff: Annotated[
        bool,
        typer.Option(
            "--diff",
            help="After compile, run objdiff against the production "
                 "target.o for the function (or whole TU). Saves a "
                 "round-trip when you want to know 'does this "
                 "force-coalesce reach the target?' in one shot. "
                 "Implies --keep-obj (uses a temp path if --keep-obj "
                 "not given).",
        ),
    ] = False,
    force_frame_from_diff: Annotated[
        bool,
        typer.Option(
            "--force-frame-from-diff",
            "--force-no-home-from-diff",
            help=(
                "DIAGNOSTIC-ONLY: with --diff, run a preflight checkdiff JSON "
                "pass, derive stack-frame immediates and anonymous literal "
                "renames from the paired current/target asm, patch the "
                "temporary .o, then run the final checkdiff. Useful for "
                "proving held-FP/no-home frame hypotheses without changing C "
                "source."
            ),
        ),
    ] = False,
    function: Annotated[
        Optional[str],
        typer.Option(
            "--function", "-f",
            help="Function name to use as the --diff target. When "
                 "omitted, defaults to the value of --force-iter-first-fn / "
                 "--force-select-order-fn / --force-phys-fn / "
                 "--force-coalesce-fn / --force-remat-fn (in that order) "
                 "if any is set; "
                 "otherwise falls back to the first "
                 "function found in the source file. Use this option "
                 "when working on a non-first function in a multi-function "
                 "TU so --diff compares the right function.",
        ),
    ] = None,
    unit_source: Annotated[
        Optional[str],
        typer.Option(
            "--unit-source",
            help=(
                "Use this real same-TU source file's build.ninja flags and "
                "object/cache identity while compiling C_FILE. This lets "
                "`build/mwcc_debug_cache/probes/.../*.c` probe files compile "
                "with the original TU settings without registering their own "
                "ninja edge. Probe runs leave the baseline cache unchanged."
            ),
        ),
    ] = None,
    no_cache_sync: Annotated[
        bool,
        typer.Option(
            "--no-cache-sync",
            help="Do not update the canonical pcdump cache. Use for "
                 "temporary source experiments that should not become the "
                 "baseline for follow-up diagnostics.",
        ),
    ] = False,
    checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--checkdiff-timeout",
            help="Timeout in seconds for the integrated --diff checkdiff run.",
        ),
    ] = 60.0,
) -> None:
    """Local mwcc_debug pcdump (macOS+wibo+Zig-built DLL, no SSH).

    Compiles the given .c file locally via wibo + the patched
    mwcceppc_debug.exe. Produces the same pcdump.txt our SSH-based
    `debug dump remote` produces, in ~1 second vs ~30 seconds.

    Requires one-time setup: run `melee-agent debug dump setup`
    first to patch the compiler and deploy the DLL.

    Env-var hooks (--force-phys, --force-iter-first, --force-coalesce,
    --force-remat, --force-schedule, --force-no-cse, and their
    function-scope variants) pass through to the DLL.

    Use --keep-obj PATH to preserve the compiled .o for downstream
    inspection (objdiff/checkdiff/etc.). Use --diff to run an integrated
    objdiff against the target — answers "does this match?" in one go.
    """
    from src.cli.debug import (  # noqa: E402
        DEFAULT_MELEE_ROOT,
        _acquire_checkdiff_repo_lock,
        _cflags_with_same_tu_include_dir,
        _checkdiff_env_for_locked_child,
        _emit_function_not_in_dump,
        _find_compiler_dir,
        _find_unit_for_function,
        _find_wibo,
        _kill_debug_dump_local_process_tree,
        _ninja_cflags_for_unit,
        _normalize_force_phys,
        _register_class_name_from_id,
        _reject_unsafe_force_coalesce,
        _resolve_src_relative,
        _validate_force_schedule,
        mwcc_debug_scratch_path,
    )
    melee_root = DEFAULT_MELEE_ROOT
    if c_file is None:
        if function is None:
            typer.echo(
                "missing C_FILE. Pass a source path, or pass --function so "
                "debug dump local can resolve the function's source TU.",
                err=True,
            )
            raise typer.Exit(2)
        unit = _find_unit_for_function(function, melee_root)
        if unit is None:
            typer.echo(
                f"function '{function}' not found in report.json; pass the "
                "source path explicitly or regenerate report.json.",
                err=True,
            )
            raise typer.Exit(2)
        c_file = f"src/{unit}.c"
    src_rel = _resolve_src_relative(c_file)
    unit_src_rel = (
        _resolve_src_relative(unit_source, label="unit source")
        if unit_source is not None
        else src_rel
    )
    same_tu_probe = unit_src_rel != src_rel
    lane_guard = local_safety.guard_local_pcdump_lane(
        source_rel=src_rel,
        function=function,
        allow_unsafe=local_safety.allow_unsafe_local_pcdump(),
    )
    if lane_guard.unsafe:
        typer.echo(
            local_safety.format_unsafe_lane_message(
                source_rel=src_rel,
                function=function,
                processes=lane_guard.processes,
            ),
            err=True,
        )
        raise typer.Exit(125)

    if force_frame_from_diff and not diff:
        typer.echo(
            "--force-frame-from-diff requires --diff so it can derive patches "
            "from paired checkdiff asm.",
            err=True,
        )
        raise typer.Exit(2)

    # Resolve wibo
    wibo_path = wibo or _find_wibo()
    if wibo_path is None or not wibo_path.exists():
        typer.echo(
            "wibo binary not found. Run `melee-agent debug dump doctor` "
            "to diagnose, then `melee-agent debug dump setup`, or set "
            "$MWCC_DEBUG_WIBO.",
            err=True,
        )
        raise typer.Exit(2)

    compiler_dir = _find_compiler_dir()
    debug_compiler = compiler_dir / "mwcceppc_debug.exe"
    if not debug_compiler.exists():
        typer.echo(
            f"patched compiler not found: {debug_compiler}. "
            f"Run `melee-agent debug dump doctor` to diagnose, then "
            f"`melee-agent debug dump setup`.",
            err=True,
        )
        raise typer.Exit(2)

    # Extract cflags from build.ninja. Probe files can borrow settings from
    # their real same-TU source via --unit-source.
    cflags, _mw_version = _ninja_cflags_for_unit(unit_src_rel)
    if same_tu_probe:
        cflags = _cflags_with_same_tu_include_dir(cflags, unit_src_rel)

    # Construct compile command. The patched DLL reads MWCC_DEBUG_PCDUMP_PATH for
    # its output filename. Keep transient dumps in the managed scratch root so a
    # watchdog-killed parent cannot leave untracked pcdump_*.txt files in the
    # repo root.
    scratch_root = mwcc_debug_scratch_root()
    pcdump_path = mwcc_debug_scratch_path(
        "pcdump_local",
        suffix=".txt",
        root=scratch_root,
    )
    if pcdump_path.exists():
        pcdump_path.unlink()

    # Resolve where the .o lands. Default: discard via managed scratch. When the
    # agent wants to inspect/diff the output, --keep-obj routes it to a
    # specific path. --diff implies keeping (a temp path if no --keep-obj
    # was given) so we have something to diff against.
    if keep_obj is not None:
        obj_target = keep_obj if keep_obj.is_absolute() else (melee_root / keep_obj)
        obj_target.parent.mkdir(parents=True, exist_ok=True)
        obj_out = str(obj_target)
        discard_obj_after = False
    elif diff:
        obj_target = mwcc_debug_scratch_path(
            "pcdump_local_keep",
            suffix=".o",
            root=scratch_root,
        )
        obj_out = str(obj_target)
        discard_obj_after = True  # remove after diff if not user-requested
    else:
        obj_target = mwcc_debug_scratch_path(
            "pcdump_local_discard",
            suffix=".o",
            root=scratch_root,
        )
        obj_out = str(obj_target)
        discard_obj_after = True

    # Args: cflags split + source + output.
    args = (
        [str(wibo_path), str(debug_compiler)]
        + shlex.split(cflags)
        + ["-c", src_rel, "-o", obj_out]
    )
    src_path_for_cache = melee_root / src_rel
    try:
        compiled_source_digest = pcdump_cache.source_digest(src_path_for_cache)
    except OSError:
        compiled_source_digest = None

    # Set env vars for our DLL's hooks
    env = os.environ.copy()
    env["MWCC_DEBUG_PCDUMP_PATH"] = str(pcdump_path)
    if force_phys:
        # Normalize: strip optional class prefix (gpr:N:M → N:M), emit
        # ambiguity warning when bare form is used.
        force_phys_dll, fp_warnings = _normalize_force_phys(force_phys)
        for w in fp_warnings:
            print(w, file=sys.stderr)
        env["MWCC_DEBUG_FORCE_PHYS"] = force_phys_dll
    if force_phys_iter:
        env["MWCC_DEBUG_FORCE_PHYS_ITER"] = force_phys_iter
    if force_phys_fn:
        env["MWCC_DEBUG_FORCE_PHYS_FUNCTION"] = force_phys_fn
    if force_iter_first and force_select_order:
        raise typer.BadParameter(
            "--force-select-order and --force-iter-first target the same "
            "selection-order hook; use one spelling per run"
        )
    iter_first_value = force_iter_first or force_select_order
    iter_first_class = (
        force_iter_first_class
        if force_iter_first is not None
        else force_select_order_class
    )
    iter_first_fn = force_iter_first_fn or force_select_order_fn

    if iter_first_value:
        env["MWCC_DEBUG_FORCE_ITER_FIRST"] = iter_first_value
    if iter_first_class is not None:
        if not iter_first_value:
            raise typer.BadParameter(
                "--force-iter-first-class/--force-select-order-class requires "
                "--force-iter-first or --force-select-order"
            )
        env["MWCC_DEBUG_FORCE_ITER_FIRST_CLASS"] = str(iter_first_class)
    if force_iter_first_iter:
        if any(c in force_iter_first_iter for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-iter-first-iter must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        env["MWCC_DEBUG_FORCE_ITER_FIRST_ITER"] = force_iter_first_iter
    if iter_first_fn:
        env["MWCC_DEBUG_FORCE_ITER_FIRST_FUNCTION"] = iter_first_fn
    if force_coalesce:
        force_coalesce, force_coalesce_class = _normalize_force_coalesce(
            force_coalesce,
            force_coalesce_class=force_coalesce_class,
        )
        env["MWCC_DEBUG_FORCE_COALESCE"] = force_coalesce
    if force_coalesce_fn:
        env["MWCC_DEBUG_FORCE_COALESCE_FUNCTION"] = force_coalesce_fn
    if force_coalesce_class is not None:
        if force_coalesce_class not in {0, 1}:
            raise typer.BadParameter("--force-coalesce-class must be 0 or 1")
        if not force_coalesce:
            raise typer.BadParameter(
                "--force-coalesce-class requires --force-coalesce"
            )
        env["MWCC_DEBUG_FORCE_COALESCE_CLASS"] = str(force_coalesce_class)
    if force_remat:
        env["MWCC_DEBUG_FORCE_REMAT"] = _validate_force_remat(force_remat)
    if force_remat_fn:
        if any(c in force_remat_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-remat-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        env["MWCC_DEBUG_FORCE_REMAT_FUNCTION"] = force_remat_fn
    if force_schedule:
        env["MWCC_DEBUG_FORCE_SCHEDULE"] = _validate_force_schedule(force_schedule)
    if force_schedule_fn:
        env["MWCC_DEBUG_FORCE_SCHEDULE_FUNCTION"] = force_schedule_fn
    if force_no_cse:
        env["MWCC_DEBUG_FORCE_NO_CSE"] = _validate_force_no_cse(force_no_cse)
    if force_no_cse_fn:
        force_no_cse_fn = _validate_force_no_cse_fn(force_no_cse_fn)
        env["MWCC_DEBUG_FORCE_NO_CSE_FUNCTION"] = force_no_cse_fn
    if trace_cse and trace_cse_fn is None and function:
        trace_cse_fn = function
    if trace_cse:
        env["MWCC_DEBUG_TRACE_CSE"] = "1"
    if trace_cse_fn:
        trace_cse_fn = _validate_force_no_cse_fn(
            trace_cse_fn,
            option="--trace-cse-fn",
        )
        env["MWCC_DEBUG_TRACE_CSE_FUNCTION"] = trace_cse_fn

    # Safety guard: --force-coalesce without --force-coalesce-fn on a
    # multi-function TU is a known wibo-hanger. Virtual indices are
    # per-function; if the spec happens to be in-bounds for an unintended
    # function, the resulting compile can drive that function's state
    # into pathology and lock the wibo process in UE state (immune to
    # SIGKILL). Detect heuristically by counting function definitions
    # in the .c file and refuse the run with a clear error.
    # Distinguish "not provided" (None) from "explicit empty opt-out" (""):
    # the guard only fires on None.
    if force_coalesce and force_coalesce_fn is None:
        src_path = melee_root / src_rel
        if src_path.exists():
            n_fns = _count_function_defs(src_path.read_text())
            if n_fns >= 2:
                typer.echo(
                    f"refusing --force-coalesce without --force-coalesce-fn "
                    f"on a multi-function TU ({src_rel} has ~{n_fns} "
                    f"function definitions).\n"
                    f"Virtual indices are per-function; an override aimed at "
                    f"one function can corrupt others and may hang the wibo "
                    f"compile process in UE state.\n"
                    f"Re-run with `--force-coalesce-fn <function_name>` to "
                    f"scope the override. Pass `--force-coalesce-fn ''` to "
                    f"explicitly opt out of this check (NOT RECOMMENDED).",
                    err=True,
                )
                raise typer.Exit(2)
    # Same guard for --force-phys: same per-function issue, same wibo
    # risk if a per-function-class override happens to fit elsewhere.
    if (force_phys or force_phys_iter) and force_phys_fn is None:
        src_path = melee_root / src_rel
        if src_path.exists():
            n_fns = _count_function_defs(src_path.read_text())
            if n_fns >= 2:
                typer.echo(
                    f"refusing --force-phys/--force-phys-iter without "
                    f"--force-phys-fn on a multi-function TU "
                    f"({src_rel} has ~{n_fns} function definitions).\n"
                    f"Same per-function-virtual hazard as --force-coalesce. "
                    f"Re-run with `--force-phys-fn <function_name>` to scope. "
                    f"Pass `--force-phys-fn ''` to opt out (NOT RECOMMENDED).",
                    err=True,
                )
                raise typer.Exit(2)
    if force_remat and force_remat_fn is None:
        src_path = melee_root / src_rel
        if src_path.exists():
            n_fns = _count_function_defs(src_path.read_text())
            if n_fns >= 2:
                typer.echo(
                    f"refusing --force-remat without --force-remat-fn on a "
                    f"multi-function TU ({src_rel} has ~{n_fns} function "
                    f"definitions).\n"
                    f"Virtual indices are per-function; an override aimed at "
                    f"one function can perturb another function's remat "
                    f"records.\n"
                    f"Re-run with `--force-remat-fn <function_name>` to scope. "
                    f"Pass `--force-remat-fn ''` to opt out (NOT RECOMMENDED).",
                    err=True,
                )
                raise typer.Exit(2)
    if force_no_cse and force_no_cse_fn is None:
        src_path = melee_root / src_rel
        if src_path.exists():
            n_fns = _count_function_defs(src_path.read_text())
            if n_fns >= 2:
                typer.echo(
                    f"refusing --force-no-cse without --force-no-cse-fn on a "
                    f"multi-function TU ({src_rel} has ~{n_fns} function "
                    f"definitions).\n"
                    f"IRO node IDs are per-function/pass; an override aimed "
                    f"at one function can skip an unrelated CSE replacement "
                    f"in another function.\n"
                    f"Re-run with `--force-no-cse-fn <function_name>` to "
                    f"scope. Pass `--force-no-cse-fn ''` to opt out "
                    f"(NOT RECOMMENDED).",
                    err=True,
                )
                raise typer.Exit(2)

    if force_coalesce:
        if force_coalesce_fn == "":
            coalesce_preflight_function = None
        else:
            coalesce_preflight_function = force_coalesce_fn or function
        if coalesce_preflight_function:
            _reject_unsafe_force_coalesce(
                force_coalesce=force_coalesce,
                function=coalesce_preflight_function,
                melee_root=melee_root,
                register_class=(
                    _register_class_name_from_id(force_coalesce_class) or "gpr"
                ),
            )

    # Use Popen + a no-progress watchdog so a hung wibo (UE state from a
    # force-coalesce edge case, etc.) doesn't burn the full default
    # timeout. The watchdog kills the subprocess group after N seconds
    # without any progress on stdout/stderr or the pcdump output file.
    # We can't actually kill a wibo that's pinned in UE state (immune
    # to SIGKILL — only a host reboot reaps it), but we can stop OUR
    # process from waiting and stop accumulating new compile attempts
    # behind it.
    WATCHDOG_TIMEOUT_S = float(os.environ.get(
        "MWCC_DEBUG_HANG_TIMEOUT", "45"))
    try:
        proc_handle = subprocess.Popen(
            args,
            cwd=melee_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,  # own pgrp for clean kill
        )
    except FileNotFoundError as e:
        typer.echo(f"failed to invoke wibo: {e}", err=True)
        raise typer.Exit(3)

    import select
    out_buf: list[str] = []
    err_buf: list[str] = []
    last_progress = time.time()
    pcdump_progress_marker: tuple[int, int] | None = None
    killed_by_watchdog = False
    wibo_runtime_failure_message: str | None = None
    watchdog_lane_guard: local_safety.LocalLaneGuardResult | None = None
    while True:
        if proc_handle.poll() is not None:
            # Drain remaining output
            remaining_out, remaining_err = proc_handle.communicate()
            if remaining_out:
                out_buf.append(remaining_out)
            if remaining_err:
                err_buf.append(remaining_err)
            break
        # Wait for output (up to 1s at a time so we can check watchdog).
        ready, _, _ = select.select(
            [proc_handle.stdout, proc_handle.stderr], [], [], 1.0,
        )
        for stream in ready:
            chunk = stream.readline()
            if chunk:
                if stream is proc_handle.stdout:
                    out_buf.append(chunk)
                else:
                    err_buf.append(chunk)
                    wibo_runtime_failure_message = (
                        _debug_dump_local_wibo_runtime_failure("".join(err_buf))
                    )
                last_progress = time.time()
        if wibo_runtime_failure_message is not None:
            _kill_debug_dump_local_process_tree(proc_handle)
            try:
                remaining_out, remaining_err = proc_handle.communicate(timeout=2)
                if remaining_out:
                    out_buf.append(remaining_out)
                if remaining_err:
                    err_buf.append(remaining_err)
            except subprocess.TimeoutExpired:
                pass
            break
        try:
            pcdump_stat = pcdump_path.stat()
        except OSError:
            pcdump_marker = None
        else:
            pcdump_marker = (pcdump_stat.st_size, pcdump_stat.st_mtime_ns)
        if pcdump_marker is not None and pcdump_marker != pcdump_progress_marker:
            pcdump_progress_marker = pcdump_marker
            last_progress = time.time()
        if time.time() - last_progress > WATCHDOG_TIMEOUT_S:
            killed_by_watchdog = True
            _kill_debug_dump_local_process_tree(proc_handle)
            # Drain whatever the OS still hands back (proc may be UE)
            try:
                remaining_out, remaining_err = proc_handle.communicate(timeout=2)
                if remaining_out:
                    out_buf.append(remaining_out)
                if remaining_err:
                    err_buf.append(remaining_err)
            except subprocess.TimeoutExpired:
                # wibo is in UE state — can't reap. Move on.
                pass
            watchdog_lane_guard = local_safety.guard_local_pcdump_lane(
                source_rel=src_rel,
                function=function,
                allow_unsafe=False,
            )
            break

    # Shim into the old proc.stderr/stdout/returncode contract so the
    # rest of the function works unchanged.
    class _ProcShim:
        def __init__(self, rc, out, err):
            self.returncode = rc
            self.stdout = out
            self.stderr = err
    proc = _ProcShim(
        rc=(
            124
            if killed_by_watchdog
            else (proc_handle.returncode if proc_handle.returncode is not None else 124)
        ),
        out="".join(out_buf),
        err="".join(err_buf),
    )

    if wibo_runtime_failure_message is not None:
        typer.echo(wibo_runtime_failure_message, err=True)
        if proc.stderr.strip():
            typer.echo(proc.stderr.strip(), err=True)
        raise typer.Exit(126)

    if killed_by_watchdog:
        hang_msg = (
            f"[debug dump local] no compile progress for "
            f"{WATCHDOG_TIMEOUT_S:.0f}s — likely wibo hang (UE state). "
            f"Subprocess kill requested; check `ps aux | grep wibo` for zombie. "
            f"Override via MWCC_DEBUG_HANG_TIMEOUT=<seconds>."
        )
        if watchdog_lane_guard is not None and watchdog_lane_guard.unsafe:
            hang_msg += (
                "\n[debug dump local] unsafe local pcdump lane now has "
                "unreaped uninterruptible wibo process(es):\n"
                f"{local_safety.format_unsafe_processes(watchdog_lane_guard.processes)}"
            )
        if force_coalesce:
            hang_msg += (
                f"\n[debug dump local] --force-coalesce '{force_coalesce}' was "
                f"active. Possible causes for the hang:\n"
                f"  - Invalid pair: one or both virtuals are not in this "
                f"function's IGNode set (wrong function scoped by "
                f"--force-coalesce-fn, or index out of range).\n"
                f"  - Interfering pair: the two virtuals have a live-range "
                f"conflict — run `debug inspect analyze -f <fn>` and look for "
                f"'interferers:' near the relevant ig_idx to check "
                f"interference edges.\n"
                f"  - DLL crash in the coalesce hook (rare): check stderr "
                f"above for exception traces.\n"
                f"  Next: try a different pair, or run `debug inspect analyze -f <fn>` "
                f"and search the output for 'interferers:' near each ig_idx "
                f"to find a non-interfering candidate."
            )
        typer.echo(hang_msg, err=True)

    if proc.returncode != 0:
        # Compile failed — surface stderr but keep going if pcdump.txt
        # got produced (mwcc sometimes errors after emitting partial dump).
        #
        # Filter out MWCC's "User break, cancelled..." noise: that message
        # fires from MWCC's interrupt handler during late-cleanup paths
        # (post-listing, post-flush). It does NOT indicate the dump is
        # bad — pcdump.txt is already written by the time this fires.
        # Echoing it makes successful runs look like errors. We only echo
        # stderr if there are non-noise lines left AND the dump is missing.
        filtered = "\n".join(
            line for line in proc.stderr.splitlines()
            if "User break" not in line
            and "cancelled..." not in line
        ).strip()
        if filtered:
            typer.echo(filtered, err=True)
        if not pcdump_path.exists():
            raise typer.Exit(proc.returncode)

    if not pcdump_path.exists():
        typer.echo("compile completed but no pcdump.txt was emitted", err=True)
        raise typer.Exit(4)

    pcdump_text_cache: str | None = None

    def _read_pcdump_text() -> str:
        nonlocal pcdump_text_cache
        if pcdump_text_cache is None:
            pcdump_text_cache = pcdump_path.read_text()
        return pcdump_text_cache

    function_missing_exit_code: int | None = None
    if function:
        available_names = [fn.name for fn in parse_pcdump(_read_pcdump_text())]
        if function not in available_names:
            _emit_function_not_in_dump(
                function,
                available_names,
                hint=(
                    "Hint: `debug dump local --function` only validates "
                    "functions emitted by the compiled source. Check that the "
                    "function is defined in this TU, or regenerate the source "
                    "context before running downstream inspect commands."
                ),
            )
            function_missing_exit_code = 3

    def _user_output_pcdump_text() -> str:
        text = _read_pcdump_text()
        if function and function_missing_exit_code is None:
            scoped = slice_pcdump_to_function(text, function)
            if scoped:
                return scoped
        return text

    def _write_user_output_pcdump(path: Path) -> None:
        if function and function_missing_exit_code is None:
            path.write_text(_user_output_pcdump_text())
            pcdump_path.unlink()
        else:
            pcdump_path.rename(path)

    # Warn early if --keep-obj was requested but the compiler didn't emit
    # an object (e.g. a forced coalesce hung the wibo process mid-compile).
    if keep_obj is not None and not obj_target.exists():
        typer.echo(
            f"[debug dump local] --keep-obj requested but no object was produced "
            f"(compile likely failed mid-way). Check pcdump for clues.",
            err=True,
        )
    if (
        force_coalesce
        and keep_obj is not None
        and obj_target.exists()
        and function_missing_exit_code is None
    ):
        _verify_force_coalesce_object_delta(
            args=args,
            env=env,
            obj_target=obj_target,
            melee_root=melee_root,
            scratch_root=scratch_root,
            timeout=WATCHDOG_TIMEOUT_S,
        )

    # Run objdiff if --diff was requested. The integrated check
    # answers "did this compile reach the target?" without the agent
    # having to manually re-run objdiff-cli. We invoke checkdiff in
    # --no-build mode so it uses the .o we just produced.
    diff_failure_exit_code: int | None = None
    if diff and function_missing_exit_code is None:
        if not obj_target.exists():
            typer.echo(
                f"--diff requested but .o not produced at {obj_target}; "
                f"compile likely failed (see error above).",
                err=True,
            )
            diff_failure_exit_code = 4
        else:
            # checkdiff finds the function by name across all .o files
            # the build emits; the simplest contract is to copy our .o
            # into the build path that checkdiff expects, then call it.
            unit_for_o = unit_src_rel[:-2].removeprefix("src/")  # melee/mn/foo
            build_o = melee_root / "build" / "GALE01" / "src" / f"{unit_for_o}.o"
            with _acquire_checkdiff_repo_lock(melee_root):
                build_o_existed = build_o.exists()
                saved_o: Optional[bytes] = None
                if build_o_existed:
                    saved_o = build_o.read_bytes()
                try:
                    build_o.parent.mkdir(parents=True, exist_ok=True)
                    build_o.write_bytes(obj_target.read_bytes())
                    print(f"[diff] running checkdiff against {build_o}...",
                          file=sys.stderr)
                    # Resolve the function name for --diff.
                    # Priority: explicit --function > --force-phys-fn >
                    # --force-coalesce-fn > --force-remat-fn >
                    # --force-schedule-fn >
                    # first function found in source.
                    src_path = melee_root / src_rel
                    explicit_diff_target = any([
                        function,
                        force_iter_first_fn,
                        force_select_order_fn,
                        force_phys_fn,
                        force_coalesce_fn,
                        force_remat_fn,
                        force_schedule_fn,
                        force_no_cse_fn,
                        trace_cse_fn,
                    ])
                    fn_to_diff = (
                        function
                        or force_iter_first_fn
                        or force_select_order_fn
                        or force_phys_fn
                        or force_coalesce_fn
                        or force_remat_fn
                        or force_schedule_fn
                        or force_no_cse_fn
                        or trace_cse_fn
                        or None
                    )
                    if fn_to_diff is None and src_path.exists():
                        src_text = src_path.read_text()
                        # First function definition; coarse heuristic
                        m = re.search(
                            r'^[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^)]*\)\s*'
                            r'(?:[A-Za-z_]\w*\s*)*\{',
                            src_text, re.MULTILINE,
                        )
                        if m:
                            fn_to_diff = m.group(1)
                    if fn_to_diff is None:
                        print(
                            "[diff] could not find a function name to diff; "
                            "use checkdiff manually.", file=sys.stderr,
                        )
                    elif _find_unit_for_function(fn_to_diff, melee_root) is None:
                        print(
                            _pcdump_local_missing_diff_target_hint(
                                fn_to_diff,
                                src_rel=unit_src_rel,
                                explicit=explicit_diff_target,
                            ),
                            file=sys.stderr,
                        )
                    else:
                        print(
                            f"[diff] target function: {fn_to_diff}",
                            file=sys.stderr,
                        )
                        checkdiff_env = _checkdiff_env_for_locked_child(
                            disable_fingerprint=bool(
                                force_iter_first_fn
                                or force_select_order_fn
                                or force_phys_fn
                                or force_coalesce_fn
                                or force_remat_fn
                                or force_schedule_fn
                                or force_no_cse_fn
                                or trace_cse
                                or trace_cse_fn
                                or force_frame_from_diff
                            )
                        )
                        if force_frame_from_diff:
                            try:
                                force_json_proc = subprocess.run(
                                    ["python", "tools/checkdiff.py", fn_to_diff,
                                     "--format", "json", "--no-build"],
                                    cwd=melee_root,
                                    timeout=checkdiff_timeout,
                                    env=checkdiff_env,
                                    capture_output=True,
                                    text=True,
                                )
                                if not force_json_proc.stdout.strip():
                                    if force_json_proc.stderr:
                                        print(force_json_proc.stderr, file=sys.stderr)
                                    print(
                                        "[force-frame] checkdiff JSON preflight "
                                        "produced no JSON; final diff will run "
                                        "without object patching.",
                                        file=sys.stderr,
                                    )
                                else:
                                    from ...mwcc_debug.force_frame import (
                                        ForceFramePatchError,
                                        apply_force_frame_patch_plan,
                                        derive_force_frame_patch_plan,
                                    )

                                    payload = json.loads(force_json_proc.stdout)
                                    plan = derive_force_frame_patch_plan(payload)
                                    if plan.is_empty:
                                        print(
                                            "[force-frame] no eligible "
                                            "stack-frame immediates or "
                                            "anonymous literal renames found; "
                                            "final diff will run unchanged.",
                                            file=sys.stderr,
                                        )
                                    else:
                                        result = apply_force_frame_patch_plan(
                                            build_o,
                                            fn_to_diff,
                                            plan,
                                        )
                                        obj_target.write_bytes(build_o.read_bytes())
                                        print(
                                            "[force-frame] applied "
                                            f"{result.byte_patches_applied} "
                                            "stack-frame immediate patch(es) "
                                            f"and {len(result.symbol_renames)} "
                                            "literal rename(s) before final "
                                            "checkdiff.",
                                            file=sys.stderr,
                                        )
                            except subprocess.TimeoutExpired:
                                print(
                                    f"[force-frame] checkdiff JSON preflight "
                                    f"timed out after {checkdiff_timeout:g}s; "
                                    "final diff will run without object "
                                    "patching.",
                                    file=sys.stderr,
                                )
                            except (
                                ForceFramePatchError,
                                json.JSONDecodeError,
                                OSError,
                                subprocess.CalledProcessError,
                            ) as exc:
                                print(
                                    f"[force-frame] could not apply "
                                    f"diff-derived object patch: {exc}; final "
                                    "diff will run unchanged.",
                                    file=sys.stderr,
                                )
                        try:
                            diff_proc = subprocess.run(
                                ["python", "tools/checkdiff.py", fn_to_diff,
                                 "--format", "plain", "--no-build"],
                                cwd=melee_root,
                                timeout=checkdiff_timeout,
                                env=checkdiff_env,
                            )
                            if diff_proc.returncode == 0:
                                print("[diff] MATCH — function bytes are identical.")
                        except subprocess.TimeoutExpired:
                            print(
                                f"[diff] checkdiff timed out after "
                                f"{checkdiff_timeout:g}s; rerun manually or raise "
                                f"--checkdiff-timeout.",
                                file=sys.stderr,
                            )
                finally:
                    if build_o_existed and saved_o is not None:
                        build_o.write_bytes(saved_o)
                    elif not build_o_existed and build_o.exists():
                        try:
                            build_o.unlink()
                        except OSError:
                            pass

    # Clean up the .o if it was temp-allocated (and not requested by user)
    if discard_obj_after:
        try:
            os.unlink(obj_out)
        except OSError:
            pass

    # Determine whether ANY force-* override was active this run.
    # Forced pcdumps contain experimental allocator decisions that should
    # NOT overwrite the shared baseline cache — downstream commands that
    # auto-resolve via the cache would silently read forced data as if it
    # were the natural allocation, producing misleading diagnostics.
    any_forced = any([
        force_phys, force_phys_iter, force_phys_fn,
        force_iter_first, force_iter_first_fn,
        force_select_order, force_select_order_fn,
        force_coalesce, force_coalesce_fn,
        force_remat, force_remat_fn,
        force_schedule, force_schedule_fn,
        force_no_cse, force_no_cse_fn,
        trace_cse, trace_cse_fn,
        force_frame_from_diff,
    ])
    if any_forced:
        print(
            "[debug dump local] diagnostic overrides are DIAGNOSTIC-ONLY: "
            "they use mwcceppc_debug.exe and do not affect production "
            "ninja builds. Treat matches as hypotheses, not shippable "
            "source results.",
            file=sys.stderr,
        )

    def _finish_pcdump_local_run() -> None:
        _raise_pcdump_local_watchdog_exit(killed_by_watchdog)
        if function_missing_exit_code is not None:
            raise typer.Exit(function_missing_exit_code)
        if diff_failure_exit_code is not None:
            raise typer.Exit(diff_failure_exit_code)

    # Place output
    if str(output) == "-":
        sys.stdout.write(_user_output_pcdump_text())
        pcdump_path.unlink()
        _finish_pcdump_local_run()
        return

    skip_cache_sync = any_forced or no_cache_sync or same_tu_probe

    # Resolve the canonical cache location for this TU so we can ALWAYS
    # update it — even when --output specifies a different path.
    # Without this, downstream commands (analyze, var-to-virtual, guide)
    # auto-resolve via the cache and silently read stale data.
    # EXCEPTION: forced runs skip the cache entirely (see any_forced above).
    unit = unit_src_rel[:-2].removeprefix("src/")  # melee/mn/mnvibration
    pcdump_cache.ensure_cache_dir(melee_root)
    cache_target = pcdump_cache.cache_path(melee_root, unit)
    cache_skip_reason: Optional[str] = None
    if same_tu_probe:
        cache_skip_reason = (
            f"same-TU probe {src_rel} compiled with build settings from "
            f"{unit_src_rel}"
        )
    elif function_missing_exit_code is not None:
        skip_cache_sync = True
        cache_skip_reason = (
            f"requested function {function!r} was not emitted in pcdump"
        )
    elif killed_by_watchdog:
        skip_cache_sync = True
        cache_skip_reason = "watchdog timed out local dump"
    elif not skip_cache_sync:
        source_current, _current_digest = _compiled_source_snapshot_still_current(
            src_path_for_cache,
            compiled_source_digest,
        )
        if not source_current:
            skip_cache_sync = True
            cache_skip_reason = (
                "source changed or restored after the compiled snapshot"
            )

    if output is None:
        if skip_cache_sync:
            # Forced/no-cache run — write to a temp path and skip cache sync.
            prefix = (
                "unstable-source" if cache_skip_reason
                else "forced" if any_forced
                else "nocache"
            )
            output = mwcc_debug_scratch_path(
                f"pcdump_{prefix}",
                suffix=".txt",
                root=scratch_root,
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            _write_user_output_pcdump(output)
            os.utime(output, None)
            if cache_skip_reason:
                print(
                    f"[debug dump local] {cache_skip_reason}; leaving "
                    f"baseline cache unchanged. Dump at: {output}",
                    file=sys.stderr,
                )
            elif any_forced:
                print(
                    f"[debug dump local] diagnostic run — skipping cache sync to avoid "
                    f"contaminating baseline. Dump at: {output}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[debug dump local] --no-cache-sync — leaving baseline cache "
                    f"unchanged. Dump at: {output}",
                    file=sys.stderr,
                )
        else:
            # No --output → cache is the destination, no extra copy needed.
            output = cache_target
            output.parent.mkdir(parents=True, exist_ok=True)
            pcdump_path.rename(output)
            # Touch mtime to now: Path.rename() preserves the source file's
            # creation time (the pcdump temp was created at compile start, so
            # its mtime predates any edits the user made during the compile).
            # Without this, the mtime-based staleness check fires immediately
            # after a refresh because src_mtime > cache_mtime.  The content-
            # hash sidecar (written below) supersedes mtime for freshness, but
            # os.utime() is kept for backward compat with callers that don't
            # have a sidecar yet.
            os.utime(output, None)
            # Write the content-hash sidecar for the canonical cache target.
            try:
                if compiled_source_digest is not None:
                    pcdump_cache.write_hash_sidecar_digest(
                        output, compiled_source_digest
                    )
                else:
                    pcdump_cache.write_hash_sidecar(output, src_path_for_cache)
            except OSError:
                pass  # best-effort; mtime fallback still applies
    else:
        # --output specified: write there.
        output.parent.mkdir(parents=True, exist_ok=True)
        full_pcdump_text = _read_pcdump_text()
        _write_user_output_pcdump(output)
        os.utime(output, None)  # same mtime fix as above
        if skip_cache_sync:
            # Forced run — don't mirror the experimental pcdump into the
            # shared cache; it would be treated as baseline by follow-up cmds.
            if cache_skip_reason:
                print(
                    f"[debug dump local] {cache_skip_reason}; leaving "
                    f"baseline cache unchanged.",
                    file=sys.stderr,
                )
            elif any_forced:
                print(
                    f"[debug dump local] diagnostic run — skipping cache sync to avoid "
                    f"contaminating baseline.",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[debug dump local] --no-cache-sync — leaving baseline cache "
                    f"unchanged.",
                    file=sys.stderr,
                )
        else:
            # Mirror to cache (best-effort; same content) so downstream
            # auto-resolve doesn't read a stale dump.
            try:
                cache_target.parent.mkdir(parents=True, exist_ok=True)
                cache_target.write_text(full_pcdump_text)
                # Write hash sidecar for the mirrored cache file.
                try:
                    if compiled_source_digest is not None:
                        pcdump_cache.write_hash_sidecar_digest(
                            cache_target, compiled_source_digest
                        )
                    else:
                        pcdump_cache.write_hash_sidecar(
                            cache_target, src_path_for_cache
                        )
                except OSError:
                    pass  # best-effort
                if cache_target != output:
                    print(
                        f"wrote: {output} (also synced to cache {cache_target})",
                        file=sys.stderr,
                    )
            except OSError as e:
                print(
                    f"wrote: {output} (cache mirror failed: {e})",
                    file=sys.stderr,
                )
                _finish_pcdump_local_run()
                return
            _finish_pcdump_local_run()
            return

    print(f"wrote: {output}", file=sys.stderr)
    _finish_pcdump_local_run()



