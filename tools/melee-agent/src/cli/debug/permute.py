"""`debug permute ...` — run, verify, and triage decomp-permuter candidates.

Carved out of cli/debug/__init__.py. Contains the permute_app Typer instance,
the nested remote_app Typer instance, all permute/remote command handlers,
and their permute-only private helpers.

Shared helpers (module-level names that tests patch on the cli.debug package)
still live in cli/debug/__init__.py.  They are reached via call-time (deferred)
``from src.cli.debug import ...`` imports inside the function bodies — a
load-time import would create a cycle (__init__ imports this module) and would
also break ``monkeypatch.setattr(debug_cli, ...)`` semantics, since the patched
name must resolve against __init__ at call time.
"""
from __future__ import annotations

import dataclasses
import difflib
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
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Iterable, Mapping, NoReturn, Optional

import typer


if TYPE_CHECKING:  # annotation-only; the runtime objects live in cli.debug
    from src.cli.debug import _DumpSetupCheck  # noqa: F401
from ...mwcc_debug import (
    analyze_function,
    find_function,
    parse_hook_events,
    parse_pcdump,
    score_function,
    suggest,
)
from ...mwcc_debug import candidate_audit
from ...mwcc_debug import cache as pcdump_cache
from ...mwcc_debug import permuter_remote
from ...mwcc_debug.diff_capture import (
    _run_with_process_group_timeout,
)
from ...mwcc_debug.source_patch import (
    find_function as find_source_function,
    transfer_candidate,
)

permute_app = typer.Typer(
    help="Run, verify, and triage decomp-permuter candidates."
)
remote_app = typer.Typer(
    help="Run decomp-permuter jobs on configured SSH remotes."
)
permute_app.add_typer(remote_app, name="remote")

__all__ = [
    "_CFLAGS_LINE_RE",
    "_FIRST_DIAGNOSTIC_RE",
    "_PERMUTER_DEFAULT_PRESERVE_MACROS",
    "_SIMPLIFY_SCORER_COMPILE_MARKER",
    "_build_simplify_order_compile_sh",
    "_candidate_expression_entries",
    "_canonical_c_for_format_merge",
    "_debug_dump_local_refresh_command",
    "_derive_expression_anchors",
    "_expression_anchor_signature",
    "_expression_anchors_from_spec",
    "_expression_reg_class_from_spec",
    "_expression_signature_key",
    "_expression_source_summary",
    "_expression_virtuals_for_function",
    "_format_permuter_candidate_audit_diagnostic",
    "_format_permuter_placeholder_diagnostic",
    "_format_permuter_placeholder_summary",
    "_get_match_pct_with_report_retry",
    "_is_resume_skippable_candidate_status",
    "_merge3_function",
    "_normalize_expression_text",
    "_normalize_first_def_operands",
    "_parse_force_coalesce_pairs",
    "_parse_force_coalesce_virtual",
    "_permuter_candidate_score",
    "_permuter_doctor_checks",
    "_permuter_placeholder_hits",
    "_portable_path_for_base",
    "_print_remote_ps_entries",
    "_read_permuter_candidate_status",
    "_recheck_transferred_candidate_match",
    "_remote_error",
    "_remote_load_targets",
    "_remote_log_status_for_triage",
    "_remote_read_job",
    "_remote_score_with_iteration",
    "_remote_status_job_for_triage",
    "_remote_stream_runner",
    "_render_force_phys_target_yaml",
    "_sort_permuter_candidate_paths",
    "_target_virtuals_from_spec",
    "_write_permuter_candidate_status",
    "permute_app",
    "remote_app",
    "verify_perm",
]


def _signal_process_group(proc: subprocess.Popen[Any], sig: int) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    except PermissionError:
        pgid = proc.pid
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return
    except PermissionError:
        if sig == signal.SIGKILL:
            proc.kill()
        else:
            proc.terminate()


class _LocalPermuterInterrupted(BaseException):
    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


def _terminate_local_permuter_group(
    proc: subprocess.Popen[Any],
    *,
    sigterm_sent: bool = False,
) -> None:
    if not sigterm_sent:
        _signal_process_group(proc, signal.SIGTERM)
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    _signal_process_group(proc, signal.SIGKILL)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _run_local_permuter(
    cmd: list[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
) -> int:
    proc = subprocess.Popen(
        cmd,
        env=dict(env),
        cwd=cwd,
        start_new_session=True,
    )
    signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        signals.append(signal.SIGHUP)
    previous_handlers: dict[int, Any] = {}
    termination_requested = False
    termination_finished = False

    def request_termination() -> None:
        nonlocal termination_requested
        if termination_requested:
            return
        termination_requested = True
        _signal_process_group(proc, signal.SIGTERM)

    def finish_termination() -> None:
        nonlocal termination_finished
        if termination_finished:
            return
        termination_finished = True
        _terminate_local_permuter_group(
            proc,
            sigterm_sent=termination_requested,
        )

    def _handler(signum: int, _frame: Any) -> NoReturn:
        request_termination()
        raise _LocalPermuterInterrupted(signum)

    for signum in signals:
        previous_handlers[signum] = signal.signal(signum, _handler)
    try:
        try:
            return proc.wait()
        except _LocalPermuterInterrupted as exc:
            finish_termination()
            raise SystemExit(128 + exc.signum)
        finally:
            if proc.poll() is None:
                finish_termination()
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


_PERMUTER_DEFAULT_PRESERVE_MACROS = (
    r"PAD_STACK|FORCE_PAD_STACK(?:_[0-9]+)?|PERM_.*"
)
































































def _permuter_doctor_checks(
    function: str,
    *,
    perm_root: Path,
    melee_root: Path,
) -> tuple[list[tuple[str, bool, str]], Path]:
    from src.cli.debug import _resolve_permuter_function_dir  # noqa: PLC0415
    fn_dir = _resolve_permuter_function_dir(
        function,
        perm_root=perm_root,
        melee_root=melee_root,
    )
    checks: list[tuple[str, bool, str]] = []
    checks.append((
        "perm-root",
        perm_root.exists(),
        str(perm_root) if perm_root.exists() else f"missing: {perm_root}",
    ))
    checks.append((
        "function dir",
        fn_dir.exists(),
        str(fn_dir) if fn_dir.exists() else f"missing: {fn_dir}",
    ))
    for label, filename in (
        ("base.c", "base.c"),
        ("compile.sh", "compile.sh"),
        ("target.o", "target.o"),
        ("settings.toml", "settings.toml"),
    ):
        path = fn_dir / filename
        checks.append((
            label,
            path.exists(),
            str(path) if path.exists() else f"missing: {path}",
        ))
    return checks, fn_dir


@permute_app.command(name="doctor")
def permute_doctor(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to inspect"),
    ],
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit check results as JSON."),
    ] = False,
) -> None:
    """Validate local decomp-permuter paths before run/config/verify."""
    from src.cli.debug import DEFAULT_MELEE_ROOT  # noqa: PLC0415
    from src.cli.debug import _permuter_import_hint  # noqa: PLC0415
    melee_root = DEFAULT_MELEE_ROOT
    checks, fn_dir = _permuter_doctor_checks(
        function,
        perm_root=perm_root,
        melee_root=melee_root,
    )
    failures = [check for check in checks if not check[1]]
    if json_out:
        print(json.dumps({
            "function": function,
            "perm_root": str(perm_root),
            "function_dir": str(fn_dir),
            "ok": not failures,
            "checks": [
                {"label": label, "ok": ok, "detail": detail}
                for label, ok, detail in checks
            ],
        }, indent=2))
        if failures:
            raise typer.Exit(2)
        return

    for label, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}\t{label}\t{detail}")
    if failures:
        print()
        print(_permuter_import_hint(
            function,
            perm_root=perm_root,
            melee_root=melee_root,
        ))
        raise typer.Exit(2)
    print("OK\tready for `melee-agent debug permute run`")


@permute_app.command(name="bootstrap")
def permute_bootstrap(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to import"),
    ],
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            "--annotated-source-file",
            help=(
                "Import this edited source instead of the repo TU. The file is "
                "temporarily staged over the real TU so decomp-permuter still "
                "uses the correct Melee build settings."
            ),
        ),
    ] = None,
    melee_root: Annotated[
        Optional[Path],
        typer.Option(
            "--melee-root",
            help=(
                "Melee repo/worktree root. Defaults to MELEE_ROOT, "
                "--source-file/cwd detection, then the installed package repo."
            ),
        ),
    ] = None,
    preserve_macros: Annotated[
        str,
        typer.Option(
            "--preserve-macros",
            help=(
                "Regex of source macros decomp-permuter should keep in base.c. "
                "Use an empty string to disable."
            ),
        ),
    ] = _PERMUTER_DEFAULT_PRESERVE_MACROS,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite stock settings.toml if present."),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit action summary as JSON."),
    ] = False,
) -> None:
    """Bootstrap a decomp-permuter function dir from the current repo source."""
    from src.cli.debug import _bootstrap_permuter_dir  # noqa: PLC0415
    payload = _bootstrap_permuter_dir(
        function,
        perm_root=perm_root,
        source_file=source_file,
        melee_root=melee_root,
        preserve_macros=preserve_macros,
        force=force,
    )
    if json_out:
        print(json.dumps(payload, indent=2))
        return

    src_path = Path(payload["import_source"])
    fn_dir = Path(payload["function_dir"])
    asm_path = Path(payload["asm"])
    fix_result = payload["fix_compile"]
    settings_action = payload["settings"]["action"]
    print(f"Wrote/imported {fn_dir}")
    print(f"  source: {src_path}")
    if payload["source"] != payload["import_source"]:
        print(f"  annotated source: {payload['source']}")
    print(f"  preserve macros: {payload['preserve_macros']}")
    print(
        "  PERM macros: "
        f"source={'yes' if payload['source_contains_perm_macros'] else 'no'}, "
        f"base={'yes' if payload['base_contains_perm_macros'] else 'no'}"
    )
    print(f"  base.o: {payload['base_object_status']}")
    print(f"  target asm: {asm_path}")
    print(
        f"  compile.sh: {fix_result['action']}"
        + (f" ({fix_result['reason']})" if fix_result["reason"] else "")
    )
    print(f"  settings.toml: {settings_action}")
    if payload["randomize_funcs"] is not None:
        print(f"  randomize_funcs: {', '.join(payload['randomize_funcs'])}")
    elif payload["recommended_randomize_funcs"] is not None:
        print(
            "  randomize_funcs: existing settings kept; recommended "
            + ", ".join(payload["recommended_randomize_funcs"])
        )
    print()
    print("Next:")
    rel_dir = fn_dir.relative_to(perm_root) if perm_root in fn_dir.parents else fn_dir
    print(f"  cd {perm_root}")
    print(f"  ./permuter.py {rel_dir}")


def _remote_error(exc: Exception) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(2)


def _remote_load_targets() -> dict[str, permuter_remote.RemoteTarget]:
    return permuter_remote.load_targets(permuter_remote.CONFIG_PATH)


def _remote_read_job(job_id: str) -> permuter_remote.RemoteJob:
    return permuter_remote.read_job(job_id, permuter_remote.JOBS_DIR)


def _remote_cleanup_after_fetch(job: permuter_remote.RemoteJob) -> str | None:
    try:
        permuter_remote.cleanup_remote_run_dir(job)
    except permuter_remote.RemoteJobError as exc:
        return str(exc)
    return None


def _print_remote_cleanup_after_fetch(
    job: permuter_remote.RemoteJob,
    warning: str | None,
) -> None:
    if warning:
        typer.echo(
            f"Remote cleanup warning for {job.job_id}: {warning}",
            err=True,
        )
        return
    print(f"Deleted remote run dir: {job.remote_run_dir}", flush=True)


def _remote_stream_runner(
    argv: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> permuter_remote.CommandResult:
    completed = subprocess.run(argv, cwd=cwd)
    result = permuter_remote.CommandResult(
        returncode=completed.returncode,
        stdout="",
        stderr="",
    )
    if check and result.returncode != 0:
        raise permuter_remote.RemoteJobError(
            f"Command failed ({result.returncode}): {shlex.join(argv)}"
        )
    return result


@remote_app.command(name="targets")
def remote_targets() -> None:
    """List configured remote permuter targets."""
    try:
        targets = _remote_load_targets()
    except permuter_remote.RemoteConfigError as exc:
        _remote_error(exc)

    for target in targets.values():
        print(
            f"{target.name}\t{target.ssh}\t{target.remote_perm_root}\t"
            f"{target.remote_melee_root}\t{target.threads}"
        )


@remote_app.command(name="doctor")
def remote_doctor(
    target_name: Annotated[
        str,
        typer.Option("--target", help="Configured remote target name."),
    ],
    function: Annotated[
        Optional[str],
        typer.Option("--function", "-f", help="Also check this local permuter function dir."),
    ] = None,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help=(
                "Root containing nonmatchings/<function>. If this is a matcher "
                "worktree, repair resolves the decomp-permuter code checkout "
                "from $MELEE_DECOMP_PERMUTER_ROOT or ~/code/decomp-permuter."
            ),
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    repair: Annotated[
        bool,
        typer.Option("--repair", help="Bootstrap/repair project-owned remote tooling before checking."),
    ] = False,
) -> None:
    """Check whether a remote target is ready to run decomp-permuter."""
    from src.cli.debug import DEFAULT_MELEE_ROOT  # noqa: PLC0415
    from src.cli.debug import (  # noqa: PLC0415
        _resolve_decomp_permuter_root,
        _resolve_permuter_function_dir,
    )
    try:
        targets = _remote_load_targets()
        target = targets.get(target_name)
        if target is None:
            available = ", ".join(sorted(targets)) or "(none)"
            raise permuter_remote.RemoteConfigError(
                f"Remote permuter target not found: {target_name}\n"
                f"Available targets: {available}"
            )
        local_perm_dir = None
        if function is not None:
            local_perm_dir = _resolve_permuter_function_dir(
                function,
                perm_root=perm_root,
                melee_root=DEFAULT_MELEE_ROOT,
            )
        if repair:
            repair_perm_root = _resolve_decomp_permuter_root(perm_root)
            repair_report = permuter_remote.repair_target(
                target,
                local_melee_root=DEFAULT_MELEE_ROOT,
                local_perm_root=repair_perm_root,
                function=function,
                local_perm_dir=local_perm_dir,
            )
            for action in repair_report.actions:
                print(f"REPAIR\t{action}")
        report = permuter_remote.doctor_target(
            target,
            local_perm_dir=local_perm_dir,
        )
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        _remote_error(exc)

    for check in report.checks:
        status = "PASS" if check.ok else "FAIL"
        requirement = "required" if check.required else "optional"
        detail = f" - {check.detail}" if check.detail else ""
        print(f"{status}\t{check.name}\t{requirement}{detail}")
    if not report.ok:
        raise typer.Exit(2)


@remote_app.command(name="submit")
def remote_submit(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function to run remotely."),
    ],
    target_name: Annotated[
        str,
        typer.Option("--target", help="Configured remote target name."),
    ],
    threads: Annotated[
        Optional[int],
        typer.Option("--threads", "-j", help="Override target thread count."),
    ] = None,
    mode: Annotated[
        str,
        typer.Option("--mode", help="Remote permuter mode."),
    ] = "stock",
    perm_root: Annotated[
        Path,
        typer.Option("--perm-root", help="Root of decomp-permuter clone."),
    ] = Path("~/code/decomp-permuter").expanduser(),
) -> None:
    """Submit a local decomp-permuter function directory to a remote target."""
    from src.cli.debug import DEFAULT_MELEE_ROOT  # noqa: PLC0415
    from src.cli.debug import (  # noqa: PLC0415
        _permuter_import_hint,
        _resolve_decomp_permuter_root,
        _resolve_permuter_function_dir,
    )
    melee_root = DEFAULT_MELEE_ROOT
    perm_dir = _resolve_permuter_function_dir(
        function, perm_root=perm_root, melee_root=melee_root)
    if not perm_dir.exists():
        typer.echo(
            f"{perm_dir} not found.\n"
            + _permuter_import_hint(
                function,
                perm_root=perm_root,
                melee_root=melee_root,
            ),
            err=True,
        )
        raise typer.Exit(2)

    targets: dict[str, permuter_remote.RemoteTarget] = {}
    target: permuter_remote.RemoteTarget | None = None
    try:
        targets = _remote_load_targets()
        target = targets.get(target_name)
        if target is None:
            available = ", ".join(sorted(targets)) or "(none)"
            raise permuter_remote.RemoteConfigError(
                f"Remote permuter target not found: {target_name}\n"
                f"Available targets: {available}"
            )
        job = permuter_remote.submit_job(
            function=function,
            target=target,
            local_perm_dir=perm_dir,
            jobs_dir=permuter_remote.JOBS_DIR,
            threads=threads,
            mode=mode,
            local_melee_root=melee_root,
            local_perm_root=_resolve_decomp_permuter_root(perm_root),
        )
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        if (
            isinstance(exc, permuter_remote.RemoteJobError)
            and target is not None
            and "remote preflight failed" in str(exc)
        ):
            suggestions = permuter_remote.suggest_ready_targets(
                targets,
                failed_target_name=target.name,
                local_perm_dir=perm_dir,
            )
            if suggestions:
                retry = suggestions[0]
                exc = permuter_remote.RemoteJobError(
                    f"{exc}\n"
                    f"Healthy configured target(s): {', '.join(suggestions)}\n"
                    f"Retry with --target {retry}."
                )
        _remote_error(exc)

    print(f"Job: {job.job_id}")
    print(f"Remote path: {job.remote_perm_dir}")
    print(f"Log path: {job.remote_run_dir}/permuter.log")


@remote_app.command(name="list")
def remote_list(
    active: Annotated[
        bool,
        typer.Option("--active", help="Show only jobs with active tmux sessions."),
    ] = False,
    dead: Annotated[
        bool,
        typer.Option("--dead", help="Show only jobs with stopped/missing tmux sessions."),
    ] = False,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Per-host SSH probe timeout in seconds."),
    ] = 10.0,
    prune_dead: Annotated[
        bool,
        typer.Option("--prune-dead", help="Delete metadata for dead jobs."),
    ] = False,
) -> None:
    """List local remote permuter job metadata with live active/dead status."""
    if active and dead:
        typer.echo("--active and --dead are mutually exclusive", err=True)
        raise typer.Exit(2)

    try:
        jobs = permuter_remote.list_jobs(permuter_remote.JOBS_DIR)
    except permuter_remote.RemoteJobError as exc:
        _remote_error(exc)

    if not jobs:
        live_entries: list[permuter_remote.RemotePsEntry] = []
        if not dead:
            try:
                live_entries = permuter_remote.remote_ps(
                    _remote_load_targets(),
                    timeout=timeout,
                )
            except permuter_remote.RemoteConfigError:
                live_entries = []
        if live_entries:
            print("No local remote permuter job metadata found, but live tmux sessions exist.")
            print("LIVE REMOTE SESSIONS WITHOUT LOCAL METADATA")
            _print_remote_ps_entries(live_entries)
            print()
            print("Use `melee-agent debug permute remote ps` for the live occupancy view.")
        else:
            print("No remote permuter jobs found.")
        return

    if prune_dead:
        pruned = permuter_remote.prune_dead_jobs(
            jobs, dry_run=False,
            jobs_dir=permuter_remote.JOBS_DIR,
            timeout=timeout,
        )
        if pruned:
            print(f"Pruned {len(pruned)} dead job metadata file(s):")
            for jid in pruned:
                print(f"  {jid}")
        else:
            print("No dead job metadata to prune.")
        return

    # Probe which are active with one SSH call per host instead of one per job.
    active_map = permuter_remote.probe_jobs_active_batched(jobs, timeout=timeout)

    header_printed = False
    for job in jobs:
        is_active = active_map.get(job.job_id, False)
        state = "active" if is_active else "dead"
        if active and not is_active:
            continue
        if dead and is_active:
            continue
        if not header_printed:
            print(f"{'STATE':<8} {'JOB_ID':<50} {'FUNCTION':<35} {'TARGET':<10} {'THREADS':<8} {'CREATED'}")
            header_printed = True
        print(
            f"{state:<8} {job.job_id:<50} {job.function:<35} "
            f"{job.target:<10} {job.threads:<8} {job.created_at}"
        )


def _remote_score_with_iteration(
    score: float | None,
    iteration: int | None,
    *,
    compact: bool = False,
) -> str:
    if score is None or iteration is None:
        return "-"
    separator = "@" if compact else " @iter"
    return f"{permuter_remote.format_score(score)}{separator}{iteration}"


@remote_app.command(name="status")
def remote_status(
    job_id: Annotated[str, typer.Argument(help="Remote permuter job id.")],
    stale_hours: Annotated[
        float,
        typer.Option(
            "--stale-hours",
            help="Recommend stopping active jobs older than this many wall hours.",
        ),
    ] = 24.0,
    idle_hours: Annotated[
        float,
        typer.Option(
            "--idle-hours",
            help="Recommend stopping active jobs whose log is idle this many hours.",
        ),
    ] = 12.0,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Per remote status/log probe timeout in seconds."),
    ] = 15.0,
) -> None:
    """Show remote permuter job activity and stale cleanup guidance."""
    try:
        job = _remote_read_job(job_id)
        status = _remote_status_job_for_triage(job, timeout=timeout)
        log_status = _remote_log_status_for_triage(job, timeout=timeout)
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        _remote_error(exc)

    print(f"{status.job_id}: {status.state}")
    now = permuter_remote.utcnow()
    try:
        created_at = permuter_remote.parse_timestamp(job.created_at)
    except ValueError:
        created_at = None
    if created_at is not None:
        wall_age_h = max(0.0, (now - created_at).total_seconds() / 3600.0)
        print(f"wall age: {wall_age_h:.1f}h")
    else:
        wall_age_h = None
        print(f"wall age: unknown ({job.created_at})")
    print(f"function: {job.function}")
    print(f"target: {job.target} ({job.ssh})")
    print(f"remote path: {job.remote_perm_dir}")
    if log_status.exists and log_status.modified_at is not None:
        idle_h = max(0.0, (now - log_status.modified_at).total_seconds() / 3600.0)
        print(f"log idle: {idle_h:.1f}h")
    else:
        idle_h = None
        detail = f" - {log_status.detail}" if log_status.detail else ""
        print(f"log idle: unknown{detail}")
    if log_status.global_best_score is not None:
        print(
            "best (global-min): "
            + _remote_score_with_iteration(
                log_status.global_best_score,
                log_status.global_best_iteration,
            )
        )
        if log_status.latest_score is not None:
            print(
                "latest: "
                + _remote_score_with_iteration(
                    log_status.latest_score,
                    log_status.latest_iteration,
                )
            )
        print(f"match: {'yes' if log_status.match_found else 'no'}")
        print(f"output candidate: {'yes' if log_status.output_candidate_saved else 'no'}")
        print(f"verdict: {log_status.verdict}")
    elif log_status.best_score:
        print(f"best score: {log_status.best_score}")
    reasons: list[str] = []
    if status.state == "active":
        if wall_age_h is not None and wall_age_h >= stale_hours:
            reasons.append(f"wall age >= {stale_hours:g}h")
        if idle_h is not None and idle_h >= idle_hours:
            reasons.append(f"log idle >= {idle_hours:g}h")
    if reasons:
        print(f"recommendation: stop ({'; '.join(reasons)})")
        print(f"cleanup: melee-agent debug permute remote stop {job.job_id}")
    elif status.state == "active":
        print("recommendation: keep")
    else:
        print("recommendation: stopped")
    if status.detail:
        typer.echo(status.detail, err=True)


@remote_app.command(name="triage")
def remote_triage(
    function: Annotated[
        Optional[str],
        typer.Option("--function", "-f", help="Only summarize jobs for this function."),
    ] = None,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Per-job remote status/log probe timeout in seconds."),
    ] = 30.0,
) -> None:
    """Summarize all local remote permuter jobs for convergence triage."""
    try:
        jobs = permuter_remote.list_jobs(permuter_remote.JOBS_DIR)
    except permuter_remote.RemoteJobError as exc:
        _remote_error(exc)
    if function is not None:
        jobs = [job for job in jobs if job.function == function]

    print("fn\tjob\tstate\titers\tglobal-min\tlatest\tmatch\toutput\tverdict")
    for job in jobs:
        typer.echo(f"[remote-triage] probing {job.job_id}", err=True)
        status = _remote_status_job_for_triage(job, timeout=timeout)
        log_status = _remote_log_status_for_triage(job, timeout=timeout)
        iters = (
            str(log_status.latest_iteration)
            if log_status.latest_iteration is not None
            else str(log_status.iteration_count) if log_status.iteration_count else "-"
        )
        global_min = _remote_score_with_iteration(
            log_status.global_best_score,
            log_status.global_best_iteration,
            compact=True,
        )
        latest = _remote_score_with_iteration(
            log_status.latest_score,
            log_status.latest_iteration,
            compact=True,
        )
        print(
            f"{job.function}\t{job.job_id}\t{status.state}\t{iters}\t"
            f"{global_min}\t{latest}\t"
            f"{'yes' if log_status.match_found else 'no'}\t"
            f"{'yes' if log_status.output_candidate_saved else 'no'}\t"
            f"{log_status.verdict}"
        )
        if status.detail:
            typer.echo(f"{job.job_id}: {status.detail}", err=True)
        if log_status.detail:
            typer.echo(f"{job.job_id}: {log_status.detail}", err=True)


def _remote_status_job_for_triage(
    job: permuter_remote.RemoteJob,
    *,
    timeout: float,
) -> permuter_remote.RemoteStatus:
    try:
        return permuter_remote.status_job(job, timeout=timeout)
    except TypeError as exc:
        if "timeout" not in str(exc):
            raise
        return permuter_remote.status_job(job)


def _remote_log_status_for_triage(
    job: permuter_remote.RemoteJob,
    *,
    timeout: float,
) -> permuter_remote.RemoteLogStatus:
    try:
        return permuter_remote.remote_log_status(job, timeout=timeout)
    except TypeError as exc:
        if "timeout" not in str(exc):
            raise
        return permuter_remote.remote_log_status(job)


@remote_app.command(name="fetch")
def remote_fetch(
    job_id: Annotated[
        Optional[str],
        typer.Argument(help="Remote permuter job id. Omit when using --all."),
    ] = None,
    all_jobs: Annotated[
        bool,
        typer.Option("--all", help="Fetch all jobs (optionally filtered by --function/--target)."),
    ] = False,
    function: Annotated[
        Optional[str],
        typer.Option("--function", "-f", help="Only fetch jobs for this function."),
    ] = None,
    target: Annotated[
        Optional[str],
        typer.Option("--target", "-t", help="Only fetch jobs on this target."),
    ] = None,
    triage: Annotated[
        bool,
        typer.Option("--triage", help="Print the follow-up triage command."),
    ] = False,
    delete_remote: Annotated[
        bool,
        typer.Option(
            "--delete-remote",
            help=(
                "Delete each fetched stopped job's remote run directory after "
                "a successful fetch."
            ),
        ),
    ] = False,
) -> None:
    """Fetch remote permuter outputs into the local permuter directory."""
    try:
        if all_jobs:
            jobs = permuter_remote.list_jobs(permuter_remote.JOBS_DIR)
            fetched_jobs: list[tuple[permuter_remote.RemoteJob, Path]] = []

            def before_fetch(
                job: permuter_remote.RemoteJob,
                index: int,
                total: int,
            ) -> None:
                print(
                    f"Fetching {index}/{total}: {job.job_id} "
                    f"({job.function} on {job.target})",
                    flush=True,
                )

            def after_fetch(
                job: permuter_remote.RemoteJob,
                path: Path,
                index: int,
                total: int,
            ) -> None:
                del index, total
                fetched_jobs.append((job, path))
                print(f"Fetched: {path}", flush=True)

            def after_cleanup(
                job: permuter_remote.RemoteJob,
                warning: str | None,
                index: int,
                total: int,
            ) -> None:
                del index, total
                _print_remote_cleanup_after_fetch(job, warning)

            fetched = permuter_remote.fetch_all_jobs(
                jobs,
                function_filter=function,
                target_filter=target,
                before_fetch=before_fetch,
                after_fetch=after_fetch,
                delete_remote=delete_remote,
                after_cleanup=after_cleanup,
            )
            if not fetched_jobs:
                for path in fetched:
                    print(f"Fetched: {path}")
            if triage:
                for job, path in fetched_jobs:
                    print(
                        "Triage manually with: "
                        f"melee-agent debug permute triage {shlex.quote(str(path))} "
                        f"--function {shlex.quote(job.function)}"
                    )
            print(f"\nFetched {len(fetched)} job(s).")
            return

        if job_id is None:
            typer.echo(
                "Either JOB_ID or --all is required. "
                "Use --all to fetch all jobs.",
                err=True,
            )
            raise typer.Exit(2)

        job = _remote_read_job(job_id)
        fetched = permuter_remote.fetch_job(job)
        cleanup_warning = _remote_cleanup_after_fetch(job) if delete_remote else None
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        _remote_error(exc)

    print(f"Fetched: {fetched}")
    if delete_remote:
        _print_remote_cleanup_after_fetch(job, cleanup_warning)
    if triage:
        print(
            "Triage manually with: "
            f"melee-agent debug permute triage {shlex.quote(str(fetched))} "
            f"--function {shlex.quote(job.function)}"
        )


@remote_app.command(name="tail")
def remote_tail(
    job_id: Annotated[str, typer.Argument(help="Remote permuter job id.")],
    lines: Annotated[
        int,
        typer.Option("--lines", "-n", help="Number of log lines to print."),
    ] = 80,
    follow: Annotated[
        bool,
        typer.Option(
            "--follow/--no-follow",
            help="Keep streaming the remote permuter log after the snapshot.",
        ),
    ] = False,
) -> None:
    """Print a remote permuter job log snapshot."""
    try:
        job = _remote_read_job(job_id)
        result = permuter_remote.tail_job(
            job,
            runner=_remote_stream_runner if follow else permuter_remote.run_command,
            lines=lines,
            follow=follow,
        )
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        _remote_error(exc)

    if result.stdout:
        stdout = (
            result.stdout if follow
            else permuter_remote.sanitize_log_tail(result.stdout, lines=lines)
        )
        typer.echo(stdout, nl=False)
    if result.stderr:
        typer.echo(result.stderr, err=True, nl=False)
    if result.returncode != 0:
        raise typer.Exit(2)


@permute_app.command(name="local-orphans")
def permute_local_orphans() -> None:
    """Detect orphaned local wibo/MWCC compile processes."""
    orphans = permuter_remote.detect_orphaned_wibo_processes()
    if not orphans:
        print("No orphaned local wibo/MWCC processes detected.")
        return
    print("Orphaned local wibo/MWCC processes:")
    for proc in orphans:
        state_note = (
            " uninterruptible; kill may not work, restart host if it blocks builds"
            if "U" in proc.stat
            else ""
        )
        print(
            f"PID={proc.pid}\tPPID={proc.ppid}\tSTAT={proc.stat}\t"
            f"ELAPSED={proc.elapsed}{state_note}"
        )
        print(f"  {proc.command}")
    raise typer.Exit(1)


@remote_app.command(name="stop")
def remote_stop(
    job_id: Annotated[str, typer.Argument(help="Remote permuter job id.")],
) -> None:
    """Stop a remote permuter tmux session."""
    try:
        job = _remote_read_job(job_id)
        result = permuter_remote.stop_job(job)
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        _remote_error(exc)

    if result.returncode == 0:
        print("Stopped")
        return
    if result.stderr:
        typer.echo(result.stderr, err=True, nl=False)
    raise typer.Exit(2)


# ── remote ps ────────────────────────────────────────────────────────────────


@remote_app.command(name="ps")
def remote_ps(
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Per-target SSH probe timeout in seconds."),
    ] = 15.0,
) -> None:
    """Dashboard of active remote permuter sessions across all coders."""
    try:
        targets = _remote_load_targets()
    except permuter_remote.RemoteConfigError as exc:
        _remote_error(exc)

    entries = permuter_remote.remote_ps(targets, timeout=timeout)
    if not entries:
        print("No active remote permuter sessions found.")
        return

    _print_remote_ps_entries(entries)


def _print_remote_ps_entries(entries: list[permuter_remote.RemotePsEntry]) -> None:
    print(f"{'TARGET':<10} {'FUNCTION':<35} {'JOB_ID':<45} {'BEST':>8} {'ITERS':>8} {'AGE':>8} {'VERDICT':<12} FLAGS")
    print("-" * 140)
    for e in entries:
        flags = ""
        if e.match_flag:
            flags += "M"
        if e.plateau_flag:
            flags += "P"
        print(
            f"{e.target:<10} {e.function:<35} {e.job_id:<45} "
            f"{e.best_score or '-':>8} {e.iterations:>8} {e.age:>8} "
            f"{e.verdict:<12} {flags}"
        )


# ── remote reap ──────────────────────────────────────────────────────────────


@remote_app.command(name="reap")
def remote_reap(
    function: Annotated[
        Optional[str],
        typer.Option("--function", "-f", help="Only reap jobs for this function."),
    ] = None,
    job_id: Annotated[
        Optional[str],
        typer.Option("--job-id", help="Only reap this specific job."),
    ] = None,
    idle_hours: Annotated[
        float,
        typer.Option("--idle-hours", help="Hours of log inactivity before plateau is reapable."),
    ] = 6.0,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Per-job remote probe timeout in seconds."),
    ] = 30.0,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Show what would be reaped without stopping."),
    ] = True,
) -> None:
    """Stop remote permuter jobs that are byte-matched or plateaued."""
    try:
        targets = _remote_load_targets()
        jobs = permuter_remote.list_jobs(permuter_remote.JOBS_DIR)
    except (permuter_remote.RemoteConfigError, permuter_remote.RemoteJobError) as exc:
        _remote_error(exc)

    if function is not None:
        jobs = [j for j in jobs if j.function == function]
    if job_id is not None:
        jobs = [j for j in jobs if j.job_id == job_id]

    if not jobs:
        print("No matching jobs found.")
        return

    actions = permuter_remote.remote_reap(
        targets,
        jobs,
        timeout=timeout,
        dry_run=dry_run,
        function_filter=function,
        job_id_filter=job_id,
        idle_hours_threshold=idle_hours,
    )
    for a in actions:
        print(f"{a.action:>12}  {a.job_id}  {a.function}  {a.target}  ({a.reason})")

    stopped = [a for a in actions if a.action == "stopped"]
    would_stop = [a for a in actions if a.action == "would-stop"]
    if dry_run:
        print(f"\nDry run: {len(would_stop)} job(s) would be stopped. "
              f"Re-run with --no-dry-run to execute.")
    else:
        print(f"\nStopped {len(stopped)} job(s).")


# ── remote prune ─────────────────────────────────────────────────────────────


@remote_app.command(name="prune")
def remote_prune(
    older_than_days: Annotated[
        int,
        typer.Option("--older-than", help="Only prune remote-runs dirs older than this many days."),
    ] = 14,
    target: Annotated[
        Optional[str],
        typer.Option("--target", "-t", help="Only prune on this target."),
    ] = None,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="SSH probe timeout in seconds."),
    ] = 30.0,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Show what would be deleted without executing."),
    ] = True,
) -> None:
    """Delete stale remote-runs directories on remote coders.

    Directories whose corresponding tmux session is still active are NEVER
    deleted, even if they are older than the cutoff.
    """
    try:
        targets = _remote_load_targets()
    except permuter_remote.RemoteConfigError as exc:
        _remote_error(exc)

    actions = permuter_remote.remote_prune(
        targets,
        timeout=timeout,
        dry_run=dry_run,
        older_than_days=older_than_days,
        target_filter=target,
    )
    for a in actions:
        print(f"{a.action:>12}  {a.target:<10}  {a.remote_dir}  ({a.reason})")

    deleted = [a for a in actions if a.action == "deleted"]
    would_delete = [a for a in actions if a.action == "would-delete"]
    if dry_run:
        print(f"\nDry run: {len(would_delete)} dir(s) would be deleted. "
              f"Re-run with --no-dry-run to execute.")
    else:
        print(f"\nDeleted {len(deleted)} dir(s).")


def _parse_force_coalesce_virtual(raw: str) -> tuple[int, int | None]:
    stripped = raw.strip()
    class_id = None
    if stripped.lower().startswith("r"):
        stripped = stripped[1:]
        class_id = 0
    elif stripped.lower().startswith("f"):
        stripped = stripped[1:]
        class_id = 1
    try:
        value = int(stripped)
    except ValueError as exc:
        raise typer.BadParameter(
            f"invalid --force-coalesce virtual {raw!r}; expected virt/root "
            "number or register token like r46/f46"
        ) from exc
    if value < 0:
        raise typer.BadParameter(
            f"invalid --force-coalesce virtual {raw!r}; expected non-negative"
        )
    return value, class_id




def _parse_force_coalesce_pairs(force_coalesce: str) -> list[tuple[int, int]]:
    from src.cli.debug import _parse_force_coalesce_pair_specs  # noqa: PLC0415
    return [
        (left, right)
        for left, right, _class_id in _parse_force_coalesce_pair_specs(
            force_coalesce
        )
    ]






_FIRST_DIAGNOSTIC_RE = re.compile(
    # GCC/Clang/MWCC standard: "path/to/file.c:42:7: error: ..."
    # Allow Windows-style backslashes in paths (wibo translates these).
    r"^(?P<path>[^\s:][^\s:]*?):(?P<line>\d+)(?::(?P<col>\d+))?:\s*"
    r"(?P<level>error|fatal|warning|note):\s*(?P<msg>.+)$"
)


















def _debug_dump_local_refresh_command(
    source_path: Path,
    melee_root: Path,
    function: Optional[str],
) -> str:
    try:
        source_arg = str(source_path.relative_to(melee_root))
    except ValueError:
        source_arg = str(source_path)
    command = f"melee-agent debug dump local {shlex.quote(source_arg)}"
    if function:
        command += f" --function {shlex.quote(function)}"
    return command








def _merge3_function(
    base_fn: str,
    candidate_fn: str,
    current_fn: str,
) -> tuple[str, list[tuple[int, str]]]:
    """3-way merge wrapper delegating to source_patch.merge3_function.

    Returns (merged_text, conflicts) where conflicts is a list of
    (approx_line_number, description) pairs. Empty conflicts = clean merge.
    """
    from ...mwcc_debug.source_patch import merge3_function
    return merge3_function(base_fn, candidate_fn, current_fn)




def _permuter_placeholder_hits(text: str) -> list[tuple[str, int]]:
    return candidate_audit.placeholder_hits(text)


def _format_permuter_placeholder_summary(hits: list[tuple[str, int]]) -> str:
    return ", ".join(
        f"'{placeholder}' ({count} occurrence{'s' if count != 1 else ''})"
        for placeholder, count in hits
    )


def _format_permuter_placeholder_diagnostic(
    hits: list[tuple[str, int]],
    *,
    command: str,
    candidate: Optional[Path] = None,
) -> str:
    summary = _format_permuter_placeholder_summary(hits)
    message = (
        f"[{command}] ABORT: permuter placeholder(s) detected in "
        f"candidate source: {summary}. These are unresolved AST "
        f"placeholders from decomp-permuter's randomizer that should "
        f"never reach real source. The candidate is corrupt; do not apply."
    )
    if candidate is not None:
        message += f" Candidate: {candidate}"
    return message


def _format_permuter_candidate_audit_diagnostic(
    report: candidate_audit.CandidateAudit,
    *,
    command: str,
    candidate: Optional[Path] = None,
) -> str:
    placeholder_hits = [
        (risk.name or "", risk.count or 0)
        for risk in report.risks
        if risk.kind == "placeholder-leak" and risk.name
    ]
    if placeholder_hits and all(risk.kind == "placeholder-leak" for risk in report.risks):
        return _format_permuter_placeholder_diagnostic(
            placeholder_hits,
            command=command,
            candidate=candidate,
        )
    return candidate_audit.format_candidate_audit_diagnostic(
        report,
        command=command,
        candidate=candidate,
    )


def _write_permuter_candidate_status(
    candidate: Path,
    *,
    status: str,
    function: str,
    first_diag: Optional[str] = None,
    risks: tuple[candidate_audit.SourceRisk, ...] = (),
    match_pct: Optional[float] = None,
    delta: Optional[float] = None,
    semantic_risk_bucket: Optional[str] = None,
    source: str,
    extra: Optional[dict] = None,
) -> None:
    try:
        candidate_audit.write_candidate_status(
            candidate,
            status=status,
            function=function,
            first_diag=first_diag,
            risks=risks,
            match_pct=match_pct,
            delta=delta,
            semantic_risk_bucket=semantic_risk_bucket,
            source=source,
            extra=extra,
        )
    except OSError:
        pass


def _read_permuter_candidate_status(candidate: Path) -> Optional[dict]:
    try:
        payload = json.loads(
            candidate_audit.status_sidecar_path(candidate).read_text()
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _is_resume_skippable_candidate_status(payload: dict) -> bool:
    status = payload.get("status")
    source = payload.get("source")
    if source == "triage":
        return status is not None
    # Fetch-time source audit already proves these candidates cannot transfer
    # and triage would just rewrite the same terminal sidecar.
    return source == "fetch" and status in {
        "corrupt-candidate",
        "read-failed",
        "unsafe-candidate",
    }


def _permuter_candidate_score(candidate: Path) -> float:
    match = re.match(
        r"^output-(?P<score>-?\d+(?:\.\d+)?)-\d+$",
        candidate.parent.name,
    )
    if not match:
        return float("-inf")
    try:
        return float(match.group("score"))
    except ValueError:
        return float("-inf")


def _sort_permuter_candidate_paths(
    candidates: list[Path],
    *,
    order: str,
) -> list[Path]:
    if order == "name":
        return sorted(candidates, key=lambda path: path.parent.name)
    if order == "newest":
        return sorted(
            candidates,
            key=lambda path: (
                path.parent.stat().st_mtime,
                path.stat().st_mtime,
                path.parent.name,
            ),
            reverse=True,
        )
    if order == "score-desc":
        return sorted(
            candidates,
            key=lambda path: (_permuter_candidate_score(path), path.parent.name),
            reverse=True,
        )
    if order == "score-asc":
        return sorted(
            candidates,
            key=lambda path: (_permuter_candidate_score(path), path.parent.name),
        )
    raise ValueError(
        f"invalid --order {order!r}; expected name, newest, score-desc, or score-asc"
    )


@permute_app.command(name="candidate-audit")
def candidate_audit_summary(
    root: Annotated[
        Path,
        typer.Argument(
            help="Directory containing permuter output-*/source.c candidates.",
        ),
    ],
    function: Annotated[
        Optional[str],
        typer.Option("--function", "-f", help="Function name for status sidecars"),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the full candidate_audit.json payload."),
    ] = False,
) -> None:
    """Audit permuter candidates and print a compact status summary."""
    if not root.is_dir():
        typer.echo(f"not a directory: {root}", err=True)
        raise typer.Exit(2)

    summary = candidate_audit.audit_candidate_tree(root, function=function)
    if as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    print(f"Candidate audit: {root}")
    if function:
        print(f"Function: {function}")
    print(f"Candidates: {summary['total']}")

    print("By status:")
    for status, count in summary["by_status"].items():
        print(f"  {status}: {count}")

    print("By semantic risk:")
    for bucket, count in summary["by_semantic_risk_bucket"].items():
        print(f"  {bucket}: {count}")

    print(f"Wrote: {root / 'candidate_audit.json'}")


def _canonical_c_for_format_merge(text: str) -> str:
    """Return C text with comments/formatting removed, preserving literals."""
    out: list[str] = []
    i = 0
    n = len(text)
    quote: Optional[str] = None
    while i < n:
        ch = text[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            if text[i + 1] == "/":
                i += 2
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                i += 2
                while i + 1 < n and not (
                    text[i] == "*" and text[i + 1] == "/"
                ):
                    i += 1
                i = min(n, i + 2)
                continue
        if ch.isspace():
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)




@permute_app.command(name="verify")
def verify_perm(
    candidate: Annotated[
        Path,
        typer.Argument(
            help="Path to permuter candidate source (.c file with the "
                 "mutated function). Typically output-NNNN-N/source.c "
                 "from decomp-permuter.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to transfer"),
    ],
    keep: Annotated[
        bool,
        typer.Option(
            "--keep",
            help="If the transfer improves match%, leave the patched source "
                 "in place. By default we always revert (dry-run semantics).",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="When --keep is set, allow overwriting manual edits that "
                 "diverge from the permuter's base.c. Without --force, "
                 "debug permute verify aborts if applying the candidate would silently "
                 "revert commits you made after importing the permuter baseline. "
                 "Has no effect without --keep.",
        ),
    ] = False,
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum improvement (in percentage points) to consider "
                 "the candidate a win. Default 0.05 — small enough to catch "
                 "+0.05-0.09% chain wins permuter often produces, but not "
                 "so small that build-noise registers as a hit.",
        ),
    ] = 0.05,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit verification result as JSON."),
    ] = False,
    keep_failed: Annotated[
        bool,
        typer.Option(
            "--keep-failed",
            help="On compile failure, preserve the failing patched source "
                 "at a temp path (printed in the error message) instead "
                 "of reverting silently. Useful when the candidate is "
                 "promising but the transfer needs manual repair.",
        ),
    ] = False,
    force_schedule: Annotated[
        Optional[str],
        typer.Option(
            "--force-schedule",
            help="Compile the transferred candidate through `debug dump local` "
                 "with this MWCC schedule override before measuring match%. "
                 "Format matches `debug dump local --force-schedule`, e.g. "
                 "'lwz:0x74>0x70'.",
        ),
    ] = None,
    force_schedule_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-schedule-fn",
            help="Scope --force-schedule to a function. Defaults to the "
                 "verified --function when --force-schedule is set.",
        ),
    ] = None,
    candidate_timeout: Annotated[
        float,
        typer.Option(
            "--candidate-timeout",
            help="Build/report timeout in seconds for the transferred "
                 "candidate (0 disables).",
        ),
    ] = 120.0,
) -> None:
    """Tier 7a: apply a permuter candidate to the real source and verify.

    The permuter preprocesses its base.c (macro expansion, header merging),
    so a winning candidate doesn't always transfer cleanly. This command:

      1. Extracts the target function from the candidate source
      2. Patches it into the real source tree
      3. Runs `ninja <obj>` to rebuild
      4. Reads the fresh fuzzy_match_percent from report.json
      5. Reports the delta vs. pre-patch baseline

    By default the patched source is REVERTED at the end regardless of
    outcome — pass --keep to leave a winning transfer applied.

    Safe-keep behaviour: when --keep is set and a permuter base.c is found
    (candidate.parent.parent/base.c), debug permute verify performs a 3-way merge
    instead of a full replace — it applies the *diff* from base.c to the
    candidate onto the current real source.  If the merge conflicts (e.g.
    you edited the same lines the permuter mutated), the command aborts
    without writing anything.  Pass --force to fall back to a full replace
    when a merge conflict is detected.
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT  # noqa: PLC0415
    from src.cli.debug import (  # noqa: PLC0415
        _extract_ninja_error,
        _failure_diagnostic_or_fallback,
        _get_match_pct,
        _merge_permuter_keep_candidate,
        _refresh_match_pct_after_successful_build,
        _run_command_with_optional_timeout,
        _run_ninja_with_no_diag_retry,
        _timeout_message,
    )
    from src.cli.debug import (_find_unit_for_function, _validate_force_schedule)  # noqa: PLC0415
    melee_root = DEFAULT_MELEE_ROOT
    if not candidate.exists():
        typer.echo(f"candidate not found: {candidate}", err=True)
        raise typer.Exit(2)

    # Locate the real source file via report.json.
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function not found in report.json: {function}\n"
            f"(report.json may be stale; try `ninja build/GALE01/report.json`)",
            err=True,
        )
        raise typer.Exit(2)
    # checkdiff convention: unit paths are relative to src/
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        typer.echo(f"target source not found: {target_path}", err=True)
        raise typer.Exit(2)

    # Baseline match%.
    baseline_pct = _get_match_pct(function, melee_root)
    if not json_out:
        print(f"Function:       {function}")
        print(f"Real source:    {target_path}")
        print(f"Candidate:      {candidate}")
        print(f"Baseline match: {baseline_pct:.2f}%" if baseline_pct is not None
              else "Baseline match: (unknown)")

    candidate_text = candidate.read_text()
    target_text = target_path.read_text()
    if force_schedule:
        force_schedule = _validate_force_schedule(force_schedule)
        if force_schedule_fn is None:
            force_schedule_fn = function
    if force_schedule_fn:
        if any(c in force_schedule_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-schedule-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
    compile_timeout = None if candidate_timeout <= 0 else candidate_timeout

    base_text_for_audit = candidate_audit.read_candidate_base_text(candidate.parent)
    if base_text_for_audit is None:
        base_text_for_audit = target_text
    audit_report = candidate_audit.audit_candidate_source(
        candidate_text,
        base_text=base_text_for_audit,
    )
    source_risks = candidate_audit.risks_to_dicts(audit_report.risks)
    semantic_risk_bucket = audit_report.semantic_risk_bucket
    if audit_report.should_reject:
        diagnostic = _format_permuter_candidate_audit_diagnostic(
            audit_report,
            command="verify-perm",
            candidate=candidate,
        )
        _write_permuter_candidate_status(
            candidate,
            status=audit_report.status,
            function=function,
            first_diag=diagnostic,
            risks=audit_report.risks,
            semantic_risk_bucket=semantic_risk_bucket,
            source="verify",
        )
        if json_out:
            print(json.dumps({
                "success": False,
                "status": audit_report.status,
                "semantic_risk_bucket": semantic_risk_bucket,
                "reason": audit_report.risks[0].kind if audit_report.risks else None,
                "placeholders": [
                    {"name": name, "count": count}
                    for name, count in _permuter_placeholder_hits(candidate_text)
                ],
                "source_risks": source_risks,
                "message": diagnostic,
                "candidate": str(candidate),
            }, indent=2))
        else:
            typer.echo(f"\n{diagnostic}", err=True)
        raise typer.Exit(7)
    if audit_report.risks and not json_out:
        print(
            _format_permuter_candidate_audit_diagnostic(
                audit_report,
                command="verify-perm",
                candidate=candidate,
            ),
            file=sys.stderr,
        )

    # Locate which side the function is missing in for a clearer message.
    from ...mwcc_debug.source_patch import find_function as _find_fn
    cand_span = _find_fn(candidate_text, function)
    target_span = _find_fn(target_text, function)
    if cand_span is None and target_span is None:
        typer.echo(
            f"function '{function}' not found in EITHER candidate or target.\n"
            f"  Candidate: {candidate}\n"
            f"  Target:    {target_path}\n"
            f"Maybe the function name is misspelled, or both sources were "
            f"renamed.",
            err=True,
        )
        raise typer.Exit(3)
    if cand_span is None:
        typer.echo(
            f"function '{function}' is in target but NOT in candidate.\n"
            f"  Candidate: {candidate}\n"
            f"This usually means the permuter mutated a different function "
            f"in the same TU. Check the candidate source manually:\n"
            f"  grep -n '^[A-Za-z_][A-Za-z_0-9 *]*(' {candidate}",
            err=True,
        )
        raise typer.Exit(3)
    if target_span is None:
        typer.echo(
            f"function '{function}' is in candidate but NOT in target.\n"
            f"  Target: {target_path}\n"
            f"This usually means the function was renamed in the real tree, "
            f"or doesn't exist yet. Verify with:\n"
            f"  grep -n '{function}' {target_path}",
            err=True,
        )
        raise typer.Exit(3)
    # --- 3-way merge / divergence check (when --keep is set) ---
    # When --keep is set, a full replacement of the function body silently
    # discards any manual edits made AFTER the permuter's base.c was created.
    # To prevent this:
    #   1. If base.c exists (candidate.parent.parent/base.c), perform a 3-way
    #      merge: apply the diff (base → candidate) to the current real source.
    #      Conflicts abort (require --force for unsafe full-replace).
    #   2. If base.c doesn't exist but the candidate's function differs from
    #      the current real source's function at lines NOT covered by the
    #      permutation, warn loudly and require --force to proceed.
    _merge_result: Optional[str] = None  # merged target text (if 3-way used)
    _merge_strategy: str = "full-replace"
    if keep:
        base_c_path = candidate.parent.parent / "base.c"
        if base_c_path.exists():
            from ...mwcc_debug.source_patch import (
                extract_function as _extract_fn,
                replace_function as _replace_fn,
            )
            base_text = base_c_path.read_text()
            base_fn = _extract_fn(base_text, function)
            cand_fn = _extract_fn(candidate_text, function)
            real_fn = _extract_fn(target_text, function)
            if base_fn is not None and cand_fn is not None and real_fn is not None:
                merged_fn, _merge_strategy, conflicts = (
                    _merge_permuter_keep_candidate(
                        base_fn,
                        cand_fn,
                        real_fn,
                        force=force,
                    )
                )
                if conflicts and not force:
                    # Show which lines conflict so the user knows what to fix
                    conflict_preview = "\n".join(
                        f"  line ~{ln}: {txt!r}" for ln, txt in conflicts[:8]
                    )
                    if len(conflicts) > 8:
                        conflict_preview += f"\n  ... and {len(conflicts) - 8} more"
                    typer.echo(
                        f"\n[verify-perm] ABORTED — 3-way merge conflict detected.\n"
                        f"The candidate mutates {len(conflicts)} line(s) that you "
                        f"also edited manually since the permuter baseline was "
                        f"imported. Applying the full candidate would silently "
                        f"revert those edits.\n\n"
                        f"Conflicting lines (candidate vs your edits):\n"
                        f"{conflict_preview}\n\n"
                        f"Options:\n"
                        f"  1. Re-import the permuter baseline:\n"
                        f"     cd ~/code/decomp-permuter && "
                        f"./import.py <c_file> <target.s> --function {function}\n"
                        f"  2. Apply just the diff manually from:\n"
                        f"     {base_c_path}\n"
                        f"  3. Pass --force to do a full replace (DISCARDS your "
                        f"manual edits in the function body).",
                        err=True,
                    )
                    raise typer.Exit(6)
                _merge_result = _replace_fn(target_text, function, merged_fn)
                if not json_out:
                    if conflicts:
                        print(
                            f"[verify-perm] WARNING: {len(conflicts)} merge conflict(s) "
                            f"resolved by taking candidate version (--force)."
                        )
                    elif _merge_strategy == "format-normalized-replace":
                        print(
                            f"[verify-perm] current source differs from "
                            f"permuter base only by formatting; applying "
                            f"candidate function."
                        )
                    else:
                        print(
                            f"[verify-perm] 3-way merge: applying permuter diff "
                            f"(base→candidate) onto current source."
                        )
            # else: can't extract from base — fall through to full replace
    # --- end merge logic ---

    orig = transfer_candidate(candidate_text, target_path, function)
    if orig is None:
        # Shouldn't happen if both spans are found, but defensive
        typer.echo(
            f"unexpected error: both sides have the function but transfer "
            f"failed. Please report this with the candidate path.",
            err=True,
        )
        raise typer.Exit(3)

    # If 3-way merge produced a result, overwrite the naive full-replace.
    if _merge_result is not None:
        # Belt-and-suspenders: check merged text for placeholder leaks too.
        # The pre-candidate check above covers regions touched by the permuter,
        # but the merge might theoretically introduce a placeholder from the
        # base side in a region outside the target function.
        _merged_ph_hits = _permuter_placeholder_hits(_merge_result)
        if _merged_ph_hits:
            diagnostic = _format_permuter_placeholder_diagnostic(
                _merged_ph_hits,
                command="verify-perm",
            )
            target_path.write_text(orig)
            typer.echo(
                f"\n{diagnostic}\n"
                f"The merged result is corrupt; aborting without writing.",
                err=True,
            )
            raise typer.Exit(7)
        target_path.write_text(_merge_result)

    leave_patched_source = False
    forced_dump_path: Optional[Path] = None
    try:
        # Build the affected .o. checkdiff convention: report.json's unit
        # name doesn't include the "src/" prefix; ninja target does.
        obj_path = f"build/GALE01/src/{unit}.o"
        if not json_out:
            if force_schedule:
                build_label = "debug dump local --force-schedule"
                print(f"\nForce-schedule rebuilding {obj_path}...")
            else:
                build_label = f"ninja {obj_path}"
                print(f"\nRebuilding {obj_path}...")
        if force_schedule:
            fd, tmp_dump = tempfile.mkstemp(
                prefix=f"verify-perm-force-schedule-{function}-",
                suffix=".pcdump.txt",
            )
            os.close(fd)
            forced_dump_path = Path(tmp_dump)
            build_cmd = [
                "python",
                "-m",
                "src.cli",
                "debug",
                "dump",
                "local",
                str(target_path),
                "--output",
                str(forced_dump_path),
                "--no-cache-sync",
                "--function",
                function,
                "--keep-obj",
                obj_path,
                "--force-schedule",
                force_schedule,
            ]
            if force_schedule_fn:
                build_cmd.extend(["--force-schedule-fn", force_schedule_fn])
            build_result = _run_command_with_optional_timeout(
                build_cmd,
                cwd=melee_root / "tools" / "melee-agent",
                timeout=compile_timeout,
            )
            build_label = "debug dump local --force-schedule"
        else:
            build_cmd = ["ninja", obj_path]
            build_result, _retried_build = _run_ninja_with_no_diag_retry(
                build_cmd,
                melee_root,
                timeout=compile_timeout,
            )
            build_label = f"ninja {obj_path}"
        if build_result.returncode != 0:
            build_status = (
                "build-timeout"
                if build_result.returncode == 124
                else "build-failed"
            )
            # Preserve the failing patched source if requested. We use
            # `tempfile.mkstemp` so the path is unique per call — agents
            # can re-run `debug permute verify --keep-failed` for multiple
            # candidates without trampling on each other's saved sources.
            failed_path: Optional[Path] = None
            if keep_failed:
                fd, tmp_path = tempfile.mkstemp(
                    prefix=f"verify-perm-failed-{function}-",
                    suffix=".c",
                )
                try:
                    with os.fdopen(fd, "w") as fh:
                        fh.write(target_path.read_text())
                    failed_path = Path(tmp_path)
                except Exception:
                    # If saving fails we still want the revert to happen.
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    failed_path = None
            err = _extract_ninja_error(build_result.stdout, build_result.stderr)
            first_diag = _failure_diagnostic_or_fallback(
                build_result.stdout,
                build_result.stderr,
                fallback=(
                    _timeout_message(build_cmd, compile_timeout)
                    if build_status == "build-timeout"
                    else (
                        f"{build_label} failed with exit "
                        f"{build_result.returncode} and emitted no compiler "
                        f"diagnostic"
                    )
                ),
            )
            source_reverted = False
            try:
                target_path.write_text(orig)
                source_reverted = target_path.read_text() == orig
            except Exception:
                source_reverted = False
            if json_out:
                _write_permuter_candidate_status(
                    candidate,
                    status=build_status,
                    function=function,
                    first_diag=first_diag,
                    risks=audit_report.risks,
                    semantic_risk_bucket="repo-invalid",
                    source="verify",
                    extra={
                        "returncode": build_result.returncode,
                        "timeout_seconds": compile_timeout,
                    },
                )
                print(json.dumps({
                    "function": function,
                    "candidate": str(candidate),
                    "success": False,
                    "status": build_status,
                    "semantic_risk_bucket": "repo-invalid",
                    "baseline_pct": baseline_pct,
                    "returncode": build_result.returncode,
                    "timeout_seconds": compile_timeout,
                    "first_diag": first_diag,
                    "error": err,
                    "failed_path": str(failed_path) if failed_path else None,
                    "source_reverted": source_reverted,
                    "source_risks": source_risks,
                }, indent=2))
                raise typer.Exit(4)
            _write_permuter_candidate_status(
                candidate,
                status=build_status,
                function=function,
                first_diag=first_diag,
                risks=audit_report.risks,
                semantic_risk_bucket="repo-invalid",
                source="verify",
                extra={
                    "returncode": build_result.returncode,
                    "timeout_seconds": compile_timeout,
                },
            )
            extra_lines: list[str] = []
            if first_diag:
                extra_lines.append(f"First diagnostic: {first_diag}")
            if failed_path is not None:
                extra_lines.append(
                    f"Failing source preserved at: {failed_path}"
                )
            elif keep_failed:
                extra_lines.append(
                    "(--keep-failed requested but the save step itself "
                    "failed; source was reverted.)"
                )
            extras_str = ("\n" + "\n".join(extra_lines)) if extra_lines else ""
            failure_label = (
                "timed out"
                if build_status == "build-timeout"
                else f"failed (exit {build_result.returncode})"
            )
            typer.echo(
                f"{build_label} {failure_label}. Relevant output:\n"
                f"{err}{extras_str}\n\n"
                f"Source reverted. The candidate doesn't compile in the real "
                f"tree — typical causes:\n"
                f"  - Permuter's base.c had macros expanded that the real "
                f"tree relies on via #include\n"
                f"  - Missing helper declarations\n"
                f"  - Type mismatches in unrelated decls that the candidate "
                f"introduced\n"
                f"For the full unfiltered ninja output, re-run with the "
                f"`{' '.join(build_cmd)}` command directly.",
                err=True,
            )
            raise typer.Exit(4)

        new_pct, report_diag = _refresh_match_pct_after_successful_build(
            unit,
            function,
            melee_root,
            fast_report=bool(force_schedule),
            timeout=compile_timeout,
        )
        if new_pct is None:
            if json_out:
                _write_permuter_candidate_status(
                    candidate,
                    status="report-read-failed",
                    function=function,
                    first_diag=(
                        report_diag
                        or "could not read fresh match% after build"
                    ),
                    risks=audit_report.risks,
                    semantic_risk_bucket="repo-invalid",
                    source="verify",
                )
                print(json.dumps({
                    "function": function,
                    "candidate": str(candidate),
                    "success": False,
                    "status": "report-read-failed",
                    "semantic_risk_bucket": "repo-invalid",
                    "baseline_pct": baseline_pct,
                    "first_diag": (
                        report_diag
                        or "could not read fresh match% after build"
                    ),
                    "source_reverted": True,
                    "source_risks": source_risks,
                }, indent=2))
            else:
                print(
                    report_diag or "Could not read fresh match% after build.",
                    file=sys.stderr,
                )
            target_path.write_text(orig)
            raise typer.Exit(5)

        delta = new_pct - (baseline_pct or 0.0)
        # Use epsilon to tolerate float-precision noise — e.g., 91.64-91.59
        # is 0.04999999... due to IEEE rounding even though both inputs
        # display as 2-decimal numbers. Without the epsilon a real
        # +0.05 win at threshold 0.05 gets silently dropped.
        improved = delta >= threshold - 1e-9
        kept = improved and keep
        leave_patched_source = kept

        if json_out:
            _write_permuter_candidate_status(
                candidate,
                status="ok",
                function=function,
                risks=audit_report.risks,
                match_pct=new_pct,
                delta=delta,
                semantic_risk_bucket=semantic_risk_bucket,
                source="verify",
                extra={"improved": improved, "kept": kept},
            )
            print(json.dumps({
                "function": function,
                "candidate": str(candidate),
                "status": "ok",
                "semantic_risk_bucket": semantic_risk_bucket,
                "baseline_pct": baseline_pct,
                "new_pct": new_pct,
                "delta": delta,
                "threshold": threshold,
                "improved": improved,
                "kept": kept,
                "source_risks": source_risks,
            }, indent=2))
        else:
            _write_permuter_candidate_status(
                candidate,
                status="ok",
                function=function,
                risks=audit_report.risks,
                match_pct=new_pct,
                delta=delta,
                semantic_risk_bucket=semantic_risk_bucket,
                source="verify",
                extra={"improved": improved, "kept": kept},
            )
            print(f"\nNew match:      {new_pct:.2f}%")
            print(f"Delta:          {delta:+.2f}%")

            if kept:
                print(f"\nCandidate improved match by ≥{threshold:.2f}% — leaving "
                      f"patched source in place ({target_path}).")
            elif improved:
                print(f"\nCandidate improved match by ≥{threshold:.2f}% but "
                      f"--keep was not set — reverting. Re-run with --keep to "
                      f"commit the change.")
            else:
                print(f"\nCandidate did not improve by ≥{threshold:.2f}% — "
                      f"reverting.")

        if not kept:
            target_path.write_text(orig)
            # Rebuild to restore prior state in report.json
            _run_ninja_with_no_diag_retry(
                ["ninja", obj_path, "build/GALE01/report.json"],
                melee_root,
                timeout=compile_timeout,
            )
    finally:
        # Always restore the source unless this invocation intentionally kept
        # an improving candidate. This also covers typer.Exit/SystemExit paths.
        if not leave_patched_source:
            try:
                if target_path.read_text() != orig:
                    target_path.write_text(orig)
            except Exception:
                pass
        if forced_dump_path is not None:
            try:
                forced_dump_path.unlink()
            except OSError:
                pass
















def _get_match_pct_with_report_retry(
    function: str,
    melee_root: Path,
    *,
    attempts: int = 3,
    delay_seconds: float = 0.05,
) -> tuple[Optional[float], Optional[str]]:
    """Read match percent, retrying transient partial report.json reads."""
    from src.cli.debug import _get_match_pct  # noqa: PLC0415
    last_error: Optional[BaseException] = None
    report_path = melee_root / "build" / "GALE01" / "report.json"
    for attempt in range(1, attempts + 1):
        try:
            return _get_match_pct(function, melee_root), None
        except (json.JSONDecodeError, OSError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(delay_seconds)
    if last_error is None:
        return None, None
    return (
        None,
        f"could not read {report_path} after {attempts} attempts: "
        f"{type(last_error).__name__}: {last_error}",
    )




def _recheck_transferred_candidate_match(
    candidate_text: str,
    target_path: Path,
    function: str,
    unit: str,
    melee_root: Path,
    original_source: str,
    *,
    timeout: float | None = None,
) -> tuple[Optional[float], Optional[str]]:
    """Re-measure a candidate from clean source using function-only transfer."""
    from src.cli.debug import (  # noqa: PLC0415
        _failure_diagnostic_or_fallback,
        _refresh_match_pct_after_successful_build,
        _run_ninja_with_no_diag_retry,
    )
    obj_path = f"build/GALE01/src/{unit}.o"
    target_path.write_text(original_source)
    if transfer_candidate(candidate_text, target_path, function) is None:
        return None, "function not in candidate during transfer recheck"
    try:
        build_result, retried_build = _run_ninja_with_no_diag_retry(
            ["ninja", obj_path],
            melee_root,
            timeout=timeout,
        )
        if build_result.returncode != 0:
            return None, _failure_diagnostic_or_fallback(
                build_result.stdout,
                build_result.stderr,
                fallback=(
                    f"ninja {obj_path} failed during transfer recheck "
                    f"with exit {build_result.returncode}"
                    + (" after retry" if retried_build else "")
                    + " and emitted no compiler diagnostic"
                ),
            )
        return _refresh_match_pct_after_successful_build(
            unit,
            function,
            melee_root,
            timeout=timeout,
        )
    finally:
        target_path.write_text(original_source)


@permute_app.command(name="triage")
def triage_perm(
    perm_dir: Annotated[
        Path,
        typer.Argument(
            help="Directory containing permuter output subdirs "
                 "(output-NNNN-N/) each with a source.c.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to verify"),
    ],
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            help="Stop after evaluating this many candidates "
                 "(0 = no limit).",
        ),
    ] = 0,
    top_k: Annotated[
        int,
        typer.Option(
            "--top",
            help="Show the top K results in the summary.",
        ),
    ] = 5,
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum improvement (percentage points) to consider a "
                 "win. Default 0.05 — catches the +0.05-0.09% chain "
                 "wins that hide at the previous 0.10 default.",
        ),
    ] = 0.05,
    apply_best: Annotated[
        bool,
        typer.Option(
            "--apply-best",
            help="If the best transferring candidate clears --threshold, "
                 "leave it applied. Default reverts at the end.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit results as JSON."),
    ] = False,
    keep_failed: Annotated[
        bool,
        typer.Option(
            "--keep-failed",
            help="For each compile failure, preserve the failing patched "
                 "source at a unique temp path (paths printed alongside "
                 "the BUILD FAILED status). Lets you re-attempt promising "
                 "candidates with targeted fixes instead of re-running "
                 "permuter.",
        ),
    ] = False,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            "--skip-status-json",
            help="Skip candidates with terminal status sidecars before "
                 "applying --max-candidates.",
        ),
    ] = False,
    order: Annotated[
        str,
        typer.Option(
            "--order",
            help="Candidate traversal order: name, newest, score-desc, or "
                 "score-asc. Ordering is applied before resume filtering and "
                 "--max-candidates.",
        ),
    ] = "name",
    candidate_timeout: Annotated[
        float,
        typer.Option(
            "--candidate-timeout",
            help="Per-candidate build/report timeout in seconds (0 disables).",
        ),
    ] = 120.0,
) -> None:
    """Tier 7e: batch-triage decomp-permuter output candidates.

    The matching agent's session noted that many permuter "winners"
    (score=N where N < baseline) don't transfer to the real source tree
    because permuter preprocesses base.c (header merging, macro
    expansion). This command iterates each `output-*/source.c` in a
    permuter run, applies the candidate to the real tree via the same
    transfer logic as `debug permute verify`, runs `ninja` + reads
    fuzzy_match_percent, and produces a ranked list of which candidates
    actually improve real-tree match%.

    Per-candidate cost: ~5-10 seconds (one ninja + report.json). With
    permuter generating ~100 winning candidates per session, total
    triage time is typically a few minutes.

    Designed as the v1 of permuter integration. v2 would be a permuter
    `--external-scorer` patch that calls our scoring per-iteration
    instead of per-winner.
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT  # noqa: PLC0415
    from src.cli.debug import (  # noqa: PLC0415
        _failure_diagnostic_or_fallback,
        _get_match_pct,
        _refresh_match_pct_after_successful_build,
        _run_ninja_with_no_diag_retry,
    )
    from src.cli.debug import _find_unit_for_function  # noqa: PLC0415
    melee_root = DEFAULT_MELEE_ROOT
    if not perm_dir.is_dir():
        typer.echo(f"not a directory: {perm_dir}", err=True)
        raise typer.Exit(2)

    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"function not found in report.json: {function}", err=True)
        raise typer.Exit(2)
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        typer.echo(f"target source not found: {target_path}", err=True)
        raise typer.Exit(2)

    # Locate candidate sources. Try the common permuter layouts:
    #   <perm-dir>/output-NNNN-N/source.c     (default)
    #   <perm-dir>/<anything>/source.c
    candidate_paths: list[Path] = []
    for entry in sorted(perm_dir.iterdir()):
        if not entry.is_dir():
            continue
        src = entry / "source.c"
        if src.exists():
            candidate_paths.append(src)
    if not candidate_paths:
        # Fallback: maybe the perm-dir itself is one output (no subdirs)
        direct_src = perm_dir / "source.c"
        if direct_src.exists():
            candidate_paths = [direct_src]
    if not candidate_paths:
        typer.echo(
            f"no candidate sources found under {perm_dir}\n"
            f"(expected output-NNNN-N/source.c or source.c)",
            err=True,
        )
        raise typer.Exit(3)
    try:
        candidate_paths = _sort_permuter_candidate_paths(
            candidate_paths,
            order=order,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)
    skipped_candidates: list[dict] = []
    if resume:
        pending: list[Path] = []
        for candidate in candidate_paths:
            status_payload = _read_permuter_candidate_status(candidate)
            if (
                status_payload is not None
                and _is_resume_skippable_candidate_status(status_payload)
            ):
                skipped_candidates.append({
                    "path": str(candidate),
                    "status": status_payload.get("status"),
                    "semantic_risk_bucket": status_payload.get(
                        "semantic_risk_bucket"
                    ),
                    "source": status_payload.get("source"),
                })
                continue
            pending.append(candidate)
        candidate_paths = pending
    if max_candidates > 0 and len(candidate_paths) > max_candidates:
        candidate_paths = candidate_paths[:max_candidates]

    compile_timeout = None if candidate_timeout <= 0 else candidate_timeout
    baseline = _get_match_pct(function, melee_root) or 0.0
    if not json_out:
        print(f"Function: {function}")
        print(f"Target:   {target_path}")
        print(f"Baseline: {baseline:.2f}%")
        print(f"Candidates: {len(candidate_paths)}")
        if resume:
            print(f"Skipped: {len(skipped_candidates)}")
        print()

    orig = target_path.read_text()
    base_text = candidate_audit.read_candidate_base_text(perm_dir)

    @dataclasses.dataclass
    class Result:
        path: Path
        match_pct: Optional[float]
        delta: Optional[float]
        status: str  # ok/no-function/build-failed/corrupt-candidate/nonreproducible
        semantic_risk_bucket: str
        first_diag: Optional[str] = None  # set on build-failed/corrupt-candidate
        kept_failed_path: Optional[Path] = None  # set with --keep-failed
        source_risks: tuple[candidate_audit.SourceRisk, ...] = ()

    obj_path = f"build/GALE01/src/{unit}.o"
    results: list[Result] = []
    best: Optional[Result] = None

    def emit_progress(message: str) -> None:
        if json_out:
            typer.echo(f"[triage] {message}", err=True)
        else:
            print(message)

    try:
        for i, cand in enumerate(candidate_paths, 1):
            cand_text = cand.read_text()
            audit_report = candidate_audit.audit_candidate_source(
                cand_text,
                base_text=base_text,
            )
            if audit_report.should_reject:
                first_diag = _format_permuter_candidate_audit_diagnostic(
                    audit_report,
                    command="triage-perm",
                    candidate=cand,
                )
                _write_permuter_candidate_status(
                    cand,
                    status=audit_report.status,
                    function=function,
                    first_diag=first_diag,
                    risks=audit_report.risks,
                    semantic_risk_bucket=audit_report.semantic_risk_bucket,
                    source="triage",
                )
                results.append(Result(
                    path=cand, match_pct=None, delta=None,
                    status=audit_report.status,
                    semantic_risk_bucket=audit_report.semantic_risk_bucket,
                    first_diag=first_diag,
                    source_risks=audit_report.risks,
                ))
                if not json_out:
                    print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                          f"{audit_report.status.upper()}")
                    print(f"    first error: {first_diag}")
                continue
            orig_again = transfer_candidate(cand_text, target_path, function)
            if orig_again is None:
                _write_permuter_candidate_status(
                    cand,
                    status="no-function",
                    function=function,
                    risks=audit_report.risks,
                    semantic_risk_bucket="repo-invalid",
                    source="triage",
                )
                results.append(Result(path=cand, match_pct=None,
                                      delta=None, status="no-function",
                                      semantic_risk_bucket="repo-invalid",
                                      source_risks=audit_report.risks))
                if not json_out:
                    print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                          f"function not in candidate")
                continue
            # Inline the build so we can capture the first diagnostic
            # (instead of using _build_and_match, which discards stderr).
            emit_progress(
                f"[{i}/{len(candidate_paths)}] {cand.parent.name}: "
                f"building {obj_path} from {cand}"
            )
            r_build, retried_build = _run_ninja_with_no_diag_retry(
                ["ninja", obj_path],
                melee_root,
                timeout=compile_timeout,
            )
            if r_build.returncode != 0:
                first_diag = _failure_diagnostic_or_fallback(
                    r_build.stdout,
                    r_build.stderr,
                    fallback=(
                        f"ninja {obj_path} failed with exit "
                        f"{r_build.returncode}"
                        + (
                            " after retry"
                            if retried_build
                            else ""
                        )
                        + " and emitted no compiler diagnostic"
                    ),
                )
                kept_path: Optional[Path] = None
                if keep_failed:
                    try:
                        fd, tmp_path = tempfile.mkstemp(
                            prefix=(
                                f"triage-perm-failed-{function}-"
                                f"{cand.parent.name}-"
                            ),
                            suffix=".c",
                        )
                        with os.fdopen(fd, "w") as fh:
                            fh.write(target_path.read_text())
                        kept_path = Path(tmp_path)
                    except Exception:
                        kept_path = None
                # Always revert to original before next iter
                target_path.write_text(orig)
                _write_permuter_candidate_status(
                    cand,
                    status="build-failed",
                    function=function,
                    first_diag=first_diag,
                    risks=audit_report.risks,
                    semantic_risk_bucket="repo-invalid",
                    source="triage",
                    extra={"retried_build": retried_build},
                )
                results.append(Result(
                    path=cand, match_pct=None, delta=None,
                    status="build-failed",
                    semantic_risk_bucket="repo-invalid",
                    first_diag=first_diag,
                    kept_failed_path=kept_path,
                    source_risks=audit_report.risks,
                ))
                if not json_out:
                    parts = [
                        f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                        f"BUILD FAILED"
                    ]
                    parts.append(f"    first error: {first_diag}")
                    if kept_path is not None:
                        parts.append(f"    kept at: {kept_path}")
                    print("\n".join(parts))
                continue
            # Build succeeded — refresh report without rebuilding the object
            # a second time. Rebuilding here made triage vulnerable to
            # transient no-diagnostic failures after an already-good compile.
            pct, report_diag = _refresh_match_pct_after_successful_build(
                unit,
                function,
                melee_root,
                timeout=compile_timeout,
            )
            # Always revert to original before next iter
            target_path.write_text(orig)
            if pct is None:
                _write_permuter_candidate_status(
                    cand,
                    status="build-failed",
                    function=function,
                    first_diag=report_diag,
                    risks=audit_report.risks,
                    semantic_risk_bucket="repo-invalid",
                    source="triage",
                )
                results.append(Result(path=cand, match_pct=None,
                                      delta=None, status="build-failed",
                                      semantic_risk_bucket="repo-invalid",
                                      first_diag=report_diag,
                                      source_risks=audit_report.risks))
                if not json_out:
                    print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                          f"BUILD FAILED (report.json regen)")
                    if report_diag:
                        print(f"    first error: {report_diag}")
                continue
            delta = pct - baseline
            if delta >= threshold - 1e-9:
                recheck_pct, recheck_diag = _recheck_transferred_candidate_match(
                    cand_text,
                    target_path,
                    function,
                    unit,
                    melee_root,
                    orig,
                    timeout=compile_timeout,
                )
                if recheck_pct is None:
                    _write_permuter_candidate_status(
                        cand,
                        status="nonreproducible",
                        function=function,
                        first_diag=(
                            recheck_diag
                            or "transfer recheck failed without diagnostic"
                        ),
                        risks=audit_report.risks,
                        semantic_risk_bucket="repo-invalid",
                        source="triage",
                    )
                    results.append(Result(
                        path=cand,
                        match_pct=None,
                        delta=None,
                        status="nonreproducible",
                        semantic_risk_bucket="repo-invalid",
                        first_diag=(
                            recheck_diag
                            or "transfer recheck failed without diagnostic"
                        ),
                        source_risks=audit_report.risks,
                    ))
                    if not json_out:
                        print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                              f"NONREPRODUCIBLE")
                        if recheck_diag:
                            print(f"    first error: {recheck_diag}")
                    continue
                if abs(recheck_pct - pct) > 1e-6:
                    recheck_delta = recheck_pct - baseline
                    diag = (
                        f"transfer recheck produced {recheck_pct:.6f}% "
                        f"(delta={recheck_delta:+.6f}%) after initial triage "
                        f"reported {pct:.6f}% (delta={delta:+.6f}%)"
                    )
                    _write_permuter_candidate_status(
                        cand,
                        status="nonreproducible",
                        function=function,
                        first_diag=diag,
                        risks=audit_report.risks,
                        match_pct=recheck_pct,
                        delta=recheck_delta,
                        semantic_risk_bucket="repo-invalid",
                        source="triage",
                    )
                    results.append(Result(
                        path=cand,
                        match_pct=recheck_pct,
                        delta=recheck_delta,
                        status="nonreproducible",
                        semantic_risk_bucket="repo-invalid",
                        first_diag=diag,
                        source_risks=audit_report.risks,
                    ))
                    if not json_out:
                        print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                              f"NONREPRODUCIBLE")
                        print(f"    first error: {diag}")
                    continue
                pct = recheck_pct
                delta = pct - baseline
            _write_permuter_candidate_status(
                cand,
                status="ok",
                function=function,
                risks=audit_report.risks,
                match_pct=pct,
                delta=delta,
                semantic_risk_bucket=audit_report.semantic_risk_bucket,
                source="triage",
            )
            res = Result(
                path=cand, match_pct=pct, delta=delta, status="ok",
                semantic_risk_bucket=audit_report.semantic_risk_bucket,
                source_risks=audit_report.risks,
            )
            results.append(res)
            tag = ""
            # epsilon: float-precision tolerance so +0.05 wins at
            # threshold 0.05 don't silently drop.
            if delta >= threshold - 1e-9:
                tag = "  WIN"
                if best is None or pct > best.match_pct:
                    best = res
            elif delta < 0:
                tag = "  (worse)"
            if not json_out:
                print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                      f"{pct:.2f}%  delta={delta:+.2f}%{tag}")
    finally:
        target_path.write_text(orig)
        _run_ninja_with_no_diag_retry(
            ["ninja", obj_path, "build/GALE01/report.json"],
            melee_root,
            timeout=compile_timeout,
        )

    # Sort results: highest match% first, then by directory name as tiebreak
    ok_results = [r for r in results if r.status == "ok"]
    ok_results.sort(key=lambda r: (-(r.match_pct or 0), str(r.path)))

    if json_out:
        print(json.dumps({
            "function": function,
            "baseline_pct": baseline,
            "best_pct": best.match_pct if best else None,
            "best_path": str(best.path) if best else None,
            "skipped_count": len(skipped_candidates),
            "skipped_candidates": skipped_candidates,
            "results": [{
                "path": str(r.path),
                "match_pct": r.match_pct,
                "delta": r.delta,
                "status": r.status,
                "semantic_risk_bucket": r.semantic_risk_bucket,
                "first_diag": r.first_diag,
                "kept_failed_path": (
                    str(r.kept_failed_path)
                    if r.kept_failed_path else None
                ),
                "source_risks": candidate_audit.risks_to_dicts(r.source_risks),
            } for r in results],
        }, indent=2))
        return

    print()
    print("=" * 70)
    print(f"Top {min(top_k, len(ok_results))} candidates by real-tree match%:")
    print("=" * 70)
    for r in ok_results[:top_k]:
        marker = "WIN" if r.delta >= threshold - 1e-9 else "    "
        print(f"  {marker}  {r.match_pct:.2f}%  ({r.delta:+.2f}%)  "
              f"{r.path.parent.name}/source.c")

    n_wins = sum(1 for r in ok_results if r.delta >= threshold - 1e-9)
    n_build_failed = sum(1 for r in results if r.status == "build-failed")
    n_no_fn = sum(1 for r in results if r.status == "no-function")
    n_corrupt = sum(1 for r in results if r.status == "corrupt-candidate")
    n_unsafe = sum(1 for r in results if r.status == "unsafe-candidate")
    n_nonrepro = sum(1 for r in results if r.status == "nonreproducible")
    print()
    print(f"Summary: {n_wins} winners (≥{threshold:.2f}% over baseline), "
          f"{n_build_failed} build failures, {n_no_fn} missing function, "
          f"{n_corrupt} corrupt candidates, {n_unsafe} unsafe candidates, "
          f"{n_nonrepro} nonreproducible")

    if apply_best and best is not None and best.delta >= threshold - 1e-9:
        cand_text = best.path.read_text()
        transfer_candidate(cand_text, target_path, function)
        subprocess.run(
            ["ninja", f"build/GALE01/src/{unit}.o",
             "build/GALE01/report.json"],
            cwd=melee_root, capture_output=True,
        )
        print()
        print(f"Applied best candidate ({best.path.parent.name}) to "
              f"{target_path}. Verify with `git diff`.")






































































































# ---------------------------------------------------------------------------
# setup-simplify-order-scorer: end-to-end campaign setup
# ---------------------------------------------------------------------------


# Sentinel marker line we drop at the top of a wrapped compile.sh so future
# invocations can detect "already wrapped" without parsing the body.
_SIMPLIFY_SCORER_COMPILE_MARKER = (
    "# Wrapped by melee-agent debug permute setup-simplify-order-scorer"
)


def _render_force_phys_target_yaml(
    *,
    function: str,
    class_id: int,
    baseline_dump: Path | str,
    force_phys: Mapping[int, int],
    coalesce_preservation: bool = True,
) -> str:
    lines = [
        "# Generated by melee-agent debug permute setup-simplify-order-scorer",
        "# objective: force-phys",
        f"function: {function}",
        f"class_id: {class_id}",
        f"baseline_dump: {baseline_dump}",
        "force_phys:",
    ]
    for ig_idx, phys in sorted(force_phys.items()):
        lines.append(f"  {ig_idx}: {phys}")
    if not coalesce_preservation:
        lines.append("coalesce_preservation: false")
    return "\n".join(lines) + "\n"


_BOOTSTRAP_METADATA_NAME = "melee_agent_bootstrap.json"


def _portable_path_for_base(path: Path, base: Path) -> Path | str:
    try:
        return path.relative_to(base)
    except ValueError:
        return path


def _repo_relative_path(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _read_bootstrap_full_unit_source(perm_dir: Path, function: str) -> Path | None:
    metadata_path = perm_dir / _BOOTSTRAP_METADATA_NAME
    if not metadata_path.exists():
        return None
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("function") not in {None, function}:
        return None
    if (
        data.get("candidate_source_context") != "full-unit"
        and data.get("source_staged") is not True
        and data.get("full_unit_source") is not True
    ):
        return None
    raw_source = data.get("source")
    if not isinstance(raw_source, str) or not raw_source:
        return None
    return Path(raw_source).expanduser()


def _validate_full_unit_source(path: Path, function: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise typer.BadParameter(f"full-unit source file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if find_source_function(text, function) is None:
        typer.echo(
            f"full-unit source file does not contain function {function!r}: {path}",
            err=True,
        )
        raise typer.Exit(2)
    return path


def _build_simplify_order_compile_sh(
    *,
    wibo_path: Path,
    debug_compiler: Path,
    project_root: Path,
    cflags: str,
    full_unit_source: Path | None = None,
    function: str | None = None,
    full_unit_source_expr: str | None = None,
    stage_path: str = "nonmatchings/.permuter_stage_$$.c",
    remote_portable: bool = False,
) -> str:
    """Generate a compile.sh that produces .o + sibling pcdump per call.

    Permuter invokes compile.sh with positional args ``$1 = source.c`` and
    ``$3 = out.o`` (with ``-o`` in slot ``$2``). The wrapped script:

      1. Stages the .c into ``nonmatchings/.permuter_stage_$$.c`` (the
         existing mwcc+wibo macOS-path-assertion workaround, see
         fix_perm_compile.py).
      2. Sets ``MWCC_DEBUG_PCDUMP_PATH=<out.o>.pcdump.txt`` so the
         patched DLL writes the pcdump sidecar next to the .o.
      3. Invokes wibo + mwcceppc_debug with the unit's normal cflags.

    The pcdump-sidecar convention is the contract that
    ``debug target score-simplify-order`` consumes — it reads
    ``<o>.pcdump.txt`` to compute the score, no recompile.
    """
    from ...mwcc_debug.fix_perm_compile import render_wibo_resolution

    wibo_lines = render_wibo_resolution(wibo_path)
    if full_unit_source is None:
        stage_lines = [
            "cp \"$INPUT_ABS\" \"$STAGE\"",
        ]
    else:
        if not function:
            raise ValueError("function is required with full_unit_source")
        source_expr = (
            full_unit_source_expr
            if full_unit_source_expr is not None
            else shlex.quote(str(full_unit_source))
        )
        stage_lines = [
            f"MELEE_FULL_UNIT_SOURCE={source_expr}",
            f"MELEE_TARGET_FUNCTION={shlex.quote(function)}",
            "PYTHON_BIN=\"${PYTHON:-python3}\"",
            (
                "PYTHONPATH=\"tools/melee-agent${PYTHONPATH:+:$PYTHONPATH}\" "
                "\"$PYTHON_BIN\" - "
                "\"$MELEE_FULL_UNIT_SOURCE\" \"$INPUT_ABS\" "
                "\"$MELEE_TARGET_FUNCTION\" \"$STAGE\" <<'PY'"
            ),
            "import sys",
            "from pathlib import Path",
            "from src.mwcc_debug.source_patch import (",
            "    find_function,",
            "    find_function_definitions,",
            "    replace_function,",
            ")",
            "unit_arg, candidate_arg, function_name, stage_arg = sys.argv[1:5]",
            "unit_path = Path(unit_arg)",
            "candidate_path = Path(candidate_arg)",
            "stage_path = Path(stage_arg)",
            "unit_text = unit_path.read_text(encoding='utf-8')",
            "candidate_text = candidate_path.read_text(encoding='utf-8')",
            "patched = unit_text",
            "replaced = []",
            "for span in find_function_definitions(candidate_text):",
            "    candidate_fn = candidate_text[span.sig_start:span.full_end]",
            "    next_patched = replace_function(patched, span.name, candidate_fn)",
            "    if next_patched is None:",
            "        continue",
            "    patched = next_patched",
            "    replaced.append(span.name)",
            "if function_name not in replaced:",
            "    if find_function(candidate_text, function_name) is None:",
            "        raise SystemExit(f'candidate source lacks {function_name}')",
            "    raise SystemExit(f'full-unit source lacks {function_name}')",
            "stage_path.write_text(patched, encoding='utf-8')",
            "PY",
        ]

    if remote_portable:
        cd_line = 'cd "${MELEE_ROOT:?MELEE_ROOT must be set}"'
        compiler = (
            '"${MWCC_DEBUG_COMPILER:-$MELEE_ROOT/build/compilers/GC/1.2.5n/'
            'mwcceppc_debug.exe}"'
        )
    else:
        cd_line = f"cd {shlex.quote(str(project_root))}"
        compiler = shlex.quote(str(debug_compiler))

    return "\n".join([
        "#!/usr/bin/env bash",
        _SIMPLIFY_SCORER_COMPILE_MARKER,
        "set -e",
        "PERM_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
        "INPUT_ABS=\"$(realpath \"$1\")\"",
        "OUTPUT_ABS=\"$(realpath \"$3\")\"",
        cd_line,
        *wibo_lines,
        f"STAGE=\"{stage_path}\"",
        "mkdir -p \"$(dirname \"$STAGE\")\"",
        *stage_lines,
        "trap 'rm -f \"$STAGE\"' EXIT",
        "# Deposit the pcdump as a sibling of the .o so",
        "# `debug target score-simplify-order` finds it via the fast path.",
        "export MWCC_DEBUG_PCDUMP_PATH=\"${OUTPUT_ABS}.pcdump.txt\"",
        f'"$WIBO" {compiler} {cflags} -c "$STAGE" -o "$OUTPUT_ABS"',
        "",
    ])




@permute_app.command(name="setup-simplify-order-scorer")
def setup_simplify_order_scorer(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to set up the simplify-order scorer for "
                 "(required). Must match the function name inside the "
                 "perm dir's base.c.",
        ),
    ],
    want_first: Annotated[
        Optional[str],
        typer.Option(
            "--want-first",
            help="Target simplify-order prefix, comma-separated ig_idx "
                 "values. E.g. '42,32' means we want ig_idx 42 to be the "
                 "first simplification target and 32 to be the second. "
                 "Mutually exclusive with --want-late.",
        ),
    ] = None,
    want_late: Annotated[
        Optional[str],
        typer.Option(
            "--want-late",
            help=(
                "Target ig_idx sequence at the END of simplify order, "
                "comma-separated (e.g., '46,44'). Mutually exclusive with "
                "--want-first. Use for high-volatile target physicals "
                "(r10-r12) per deferred-debt #20 Phase 3."
            ),
        ),
    ] = None,
    class_id: Annotated[
        int,
        typer.Option(
            "--class",
            help="Register class to score against. 0 = GPR (default), "
                 "1 = FPR.",
        ),
    ] = 0,
    baseline_dump: Annotated[
        Optional[Path],
        typer.Option(
            "--baseline-dump",
            help="Path to a pre-search pcdump.txt for the function. If "
                 "omitted, the command will fail with instructions on "
                 "how to generate one via `debug dump local`.",
        ),
    ] = None,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    timeout_seconds: Annotated[
        float,
        typer.Option(
            "--scorer-timeout",
            help="Per-candidate scorer timeout in seconds (passed through "
                 "to permuter's [scorer].timeout_seconds).",
        ),
    ] = 5.0,
    scorer_mode: Annotated[
        str,
        typer.Option(
            "--scorer-mode",
            help=(
                "Permuter scorer objective: simplify-order (default) or "
                "force-phys. force-phys scores candidate pcdumps by whether "
                "target ig_idx values receive their requested physical regs."
            ),
        ),
    ] = "simplify-order",
    bootstrap: Annotated[
        bool,
        typer.Option(
            "--bootstrap",
            help="If the permuter function dir is missing, create it first "
                 "with `debug permute bootstrap` semantics before wiring "
                 "the simplify-order scorer.",
        ),
    ] = False,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            "--annotated-source-file",
            help=(
                "Retained/full-unit source used for bootstrap or candidate "
                "staging. When set, candidate .c files are spliced back into "
                "this source before MWCC debug compiles the pcdump sidecar."
            ),
        ),
    ] = None,
    auto_baseline_dump: Annotated[
        bool,
        typer.Option(
            "--auto-baseline-dump",
            help="Generate <perm-dir>/baseline.pcdump.txt with "
                 "`debug dump local` when --baseline-dump is omitted.",
        ),
    ] = False,
    melee_agent_bin: Annotated[
        str,
        typer.Option(
            "--melee-agent",
            help="Command to invoke melee-agent. Default 'melee-agent' "
                 "assumes the wrapper is on $PATH. Override for testing "
                 "or non-standard installs.",
        ),
    ] = "melee-agent",
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help=(
                "Optional force-phys mapping (comma-separated ig_idx:phys pairs, "
                "e.g. '34:31,37:30,32:29'). Captured into target.yaml for the "
                "pre-flight polarity check. Pass the same mapping you used in "
                "--force-phys when proving the function's force allocation."
            ),
        ),
    ] = None,
    no_coalesce_preservation: Annotated[
        bool,
        typer.Option(
            "--no-coalesce-preservation",
            help=(
                "Disable the coalesce-preservation constraint in the scorer. "
                "By default (when --force-phys is provided), candidates that "
                "coalesce any force_phys key ig_idx into another root are "
                "rejected as structurally infeasible. Pass this flag to opt "
                "out — useful for diagnostic runs or when the target tolerates "
                "coalescing."
            ),
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite existing simplify_order_target.yaml / "
                 "settings.toml / compile.sh without prompting. Use when "
                 "you've already set up a campaign and want to retarget.",
        ),
    ] = False,
) -> None:
    """Wire decomp-permuter to save candidates that improve simplify-order.

    Configures the perm dir at ``<perm_root>/nonmatchings/<function>/`` to
    use our lex-encoded simplify-order + precolor scorer in place of the
    built-in objdiff scorer. Writes three files:

      1. ``simplify_order_target.yaml`` — the target spec (function,
         simplify_order_target, class_id, baseline_dump).
      2. ``settings.toml`` — adds a ``[scorer]`` section pointing at
         ``melee-agent debug target score-simplify-order``. Preserves
         existing weight_overrides via the permuter_config builder.
      3. ``compile.sh`` — wrapped to use mwcc_debug + emit a pcdump
         sidecar next to each candidate .o. The score-simplify-order
         command reads that sidecar via the fast path.

    Requires the companion decomp-permuter [scorer] interface patch
    (commit 81378ff on the decomp-permuter side).

    Next step after running this command: ``./permuter.py <perm_dir>``
    will produce candidates in ``<perm_dir>/output-*/``. The score is
    the integer printed by score-simplify-order — lower is better,
    0 = perfect prefix hit with no precolor disturbance.
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT  # noqa: PLC0415
    from src.cli.debug import (  # noqa: PLC0415
        _bootstrap_permuter_dir,
        _cflags_with_same_tu_include_dir,
        _detect_existing_compile_sh_project_root,
        _extract_cflags_from_compile_sh,
        _find_compiler_dir,
        _find_wibo,
        _ninja_cflags_for_unit,
    )
    from src.cli.debug import _find_unit_for_function  # noqa: PLC0415
    from ...mwcc_debug.permuter_config import (
        ScorerConfig,
        SettingsTomlSpec,
        build_spec,
        parse_existing_overrides,
        render_settings_toml,
        render_simplify_order_target_yaml,
        write_settings_toml,
    )

    # ----------------------------------------------------------------
    # Validate inputs
    # ----------------------------------------------------------------

    perm_dir = perm_root / "nonmatchings" / function
    if not perm_dir.is_dir():
        if bootstrap:
            _bootstrap_permuter_dir(
                function,
                perm_root=perm_root,
                source_file=source_file,
                melee_root=None,
                preserve_macros=_PERMUTER_DEFAULT_PRESERVE_MACROS,
                force=force,
            )
            perm_dir = perm_root / "nonmatchings" / function
        if not perm_dir.is_dir():
            typer.echo(
                f"perm dir not found: {perm_dir}\n"
                f"Expected layout: <perm_root>/nonmatchings/<function>/\n"
                f"Create one first with:\n"
                f"  melee-agent extract get {function} --create-scratch\n"
                f"or by running decomp-permuter's import.py.",
                err=True,
            )
            raise typer.Exit(2)

    if baseline_dump is None and auto_baseline_dump:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is None:
            typer.echo(
                f"could not find {function!r} in report.json. "
                "Rebuild report.json and retry.",
                err=True,
            )
            raise typer.Exit(2)
        src_path = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
        if not src_path.exists():
            typer.echo(f"source not found: {src_path}", err=True)
            raise typer.Exit(2)
        baseline_dump = perm_dir / "baseline.pcdump.txt"
        if force or not baseline_dump.exists():
            baseline_dump.parent.mkdir(parents=True, exist_ok=True)
            dump_cmd = [
                sys.executable,
                "-m",
                "src.cli",
                "debug",
                "dump",
                "local",
                str(src_path),
                "--output",
                str(baseline_dump),
                "--function",
                function,
                "--no-cache-sync",
            ]
            dump_proc = subprocess.run(
                dump_cmd,
                cwd=DEFAULT_MELEE_ROOT / "tools" / "melee-agent",
                capture_output=True,
                text=True,
            )
            if dump_proc.returncode != 0:
                typer.echo(dump_proc.stderr or dump_proc.stdout, err=True)
                raise typer.Exit(dump_proc.returncode or 1)

    if scorer_mode not in {"simplify-order", "force-phys"}:
        typer.echo(
            "error: --scorer-mode must be one of: simplify-order, force-phys",
            err=True,
        )
        raise typer.Exit(code=2)
    force_phys_mode = scorer_mode == "force-phys"

    if want_first is not None and want_late is not None:
        typer.echo(
            "error: --want-first and --want-late are mutually exclusive",
            err=True,
        )
        raise typer.Exit(code=2)
    if not force_phys_mode and want_first is None and want_late is None:
        typer.echo(
            "error: must specify exactly one of --want-first or --want-late",
            err=True,
        )
        raise typer.Exit(code=2)
    if force_phys_mode and (want_first is not None or want_late is not None):
        typer.echo(
            "error: --scorer-mode force-phys does not use --want-first/--want-late",
            err=True,
        )
        raise typer.Exit(code=2)

    parsed_targets: tuple[int, ...] = ()
    parsed_targets_late: tuple[int, ...] = ()
    if want_first is not None:
        try:
            parsed_targets = tuple(
                int(s.strip()) for s in want_first.split(",") if s.strip()
            )
        except ValueError:
            typer.echo(
                f"--want-first must be a comma-separated list of integers; "
                f"got {want_first!r}",
                err=True,
            )
            raise typer.Exit(2)
        if not parsed_targets:
            typer.echo(
                "--want-first must contain at least one ig_idx value", err=True
            )
            raise typer.Exit(2)
    if want_late is not None:
        try:
            parsed_targets_late = tuple(
                int(s.strip()) for s in want_late.split(",") if s.strip()
            )
        except ValueError:
            typer.echo(
                f"--want-late must be a comma-separated list of integers; "
                f"got {want_late!r}",
                err=True,
            )
            raise typer.Exit(2)
        if not parsed_targets_late:
            typer.echo(
                "--want-late must contain at least one ig_idx value", err=True
            )
            raise typer.Exit(2)

    if baseline_dump is None:
        typer.echo(
            "--baseline-dump is required.\n"
            "Generate one via:\n"
            f"  melee-agent debug dump local <c_file_for_{function}>\n"
            "Then re-run this command with `--baseline-dump <path>`.",
            err=True,
        )
        raise typer.Exit(2)
    baseline_dump = baseline_dump.expanduser().resolve()
    if not baseline_dump.exists():
        typer.echo(
            f"--baseline-dump {baseline_dump} does not exist", err=True
        )
        raise typer.Exit(2)

    # Pre-flight: ensure the requested function is actually in the
    # baseline so we don't write a broken spec.
    baseline_text = baseline_dump.read_text(encoding="utf-8")
    if function not in baseline_text:
        typer.echo(
            f"baseline dump {baseline_dump} does not appear to contain "
            f"function {function!r}. Check the dump or regenerate it.",
            err=True,
        )
        raise typer.Exit(2)

    # ----------------------------------------------------------------
    # Locate the debug compiler + wibo for the wrapper compile.sh
    # ----------------------------------------------------------------

    from ...mwcc_debug.fix_perm_compile import validate_wibo_path

    try:
        wibo_path = validate_wibo_path(_find_wibo())
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)
    debug_compiler = _find_compiler_dir() / "mwcceppc_debug.exe"
    if not debug_compiler.exists():
        typer.echo(
            f"patched compiler not found: {debug_compiler}. "
            f"Run `melee-agent debug dump setup` first.",
            err=True,
        )
        raise typer.Exit(2)

    # ----------------------------------------------------------------
    # Resolve cflags for the wrapper compile.sh.
    # Strategy: read the existing compile.sh in the perm dir and rip
    # the cflags off its mwcc invocation. This way we preserve whatever
    # weird flags the perm dir was set up with (e.g. extra -i paths).
    # ----------------------------------------------------------------

    existing_compile_sh = perm_dir / "compile.sh"
    if not existing_compile_sh.exists():
        typer.echo(
            f"perm dir {perm_dir} lacks compile.sh — was the function "
            f"imported correctly? Run import.py first.",
            err=True,
        )
        raise typer.Exit(2)
    existing_compile_text = existing_compile_sh.read_text(encoding="utf-8")
    full_unit_source = (
        source_file.expanduser() if source_file is not None
        else _read_bootstrap_full_unit_source(perm_dir, function)
    )
    if full_unit_source is not None:
        full_unit_source = _validate_full_unit_source(full_unit_source, function)

    # Refuse to clobber an already-wrapped compile.sh unless --force.
    # The marker indicates a previous run of this command, in which
    # case re-running is intentional only when --force is passed.
    if (
        _SIMPLIFY_SCORER_COMPILE_MARKER in existing_compile_text
        and not force
    ):
        typer.echo(
            f"compile.sh already wrapped by setup-simplify-order-scorer. "
            f"Pass --force to re-wrap.",
            err=True,
        )
        raise typer.Exit(2)

    project_root_str = _detect_existing_compile_sh_project_root(
        existing_compile_text
    )
    if project_root_str is None:
        typer.echo(
            f"could not parse `cd <project_root>` line from "
            f"{existing_compile_sh}. The compile.sh doesn't match the "
            f"expected import.py/fix-compile shape — bail out and "
            f"inspect manually.",
            err=True,
        )
        raise typer.Exit(2)
    project_root = Path(project_root_str)

    cflags = _extract_cflags_from_compile_sh(existing_compile_text)
    if cflags is None:
        typer.echo(
            f"could not extract cflags from {existing_compile_sh}. "
            f"Expected a mwcceppc.exe (or wibo+mwcceppc.exe) invocation "
            f"with standard flags. Bail out and inspect manually.",
            err=True,
        )
        raise typer.Exit(2)

    baseline_dump_for_spec_path = baseline_dump
    full_unit_source_expr: str | None = None
    full_unit_stage_path = "nonmatchings/.permuter_stage_$$.c"
    remote_portable_compile = False
    if full_unit_source is not None:
        staged_baseline = perm_dir / "baseline.pcdump.txt"
        if baseline_dump.resolve() != staged_baseline.resolve():
            shutil.copy2(baseline_dump, staged_baseline)
        baseline_dump_for_spec_path = staged_baseline

        source_rel = _repo_relative_path(full_unit_source, DEFAULT_MELEE_ROOT)
        if source_rel is not None and source_rel.startswith("src/"):
            cflags, _mw_version = _ninja_cflags_for_unit(
                source_rel, melee_root=DEFAULT_MELEE_ROOT
            )
            cflags = _cflags_with_same_tu_include_dir(cflags, source_rel)
            full_unit_source_expr = (
                '"${MELEE_ROOT:?MELEE_ROOT must be set}/'
                f'{source_rel}"'
            )
            full_unit_stage_path = (
                f"{Path(source_rel).parent.as_posix()}/.permuter_stage_$$.c"
            )
            remote_portable_compile = True
        else:
            retained_copy = perm_dir / "full-unit.c"
            if full_unit_source.resolve() != retained_copy.resolve():
                shutil.copy2(full_unit_source, retained_copy)
            full_unit_source = retained_copy
            full_unit_source_expr = '"$PERM_DIR/full-unit.c"'
            remote_portable_compile = True

    # ----------------------------------------------------------------
    # Parse optional --force-phys mapping for the polarity check.
    # ----------------------------------------------------------------

    parsed_force_phys: dict[int, int] = {}
    if force_phys is not None:
        for pair in force_phys.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if ":" not in pair:
                typer.echo(
                    f"error: --force-phys entry '{pair}' must be IG_IDX:PHYS_REG",
                    err=True,
                )
                raise typer.Exit(code=2)
            ig_str, phys_str = pair.split(":", 1)
            try:
                ig_idx = int(ig_str.strip())
                phys = int(phys_str.strip())
            except ValueError:
                typer.echo(
                    f"error: --force-phys entry '{pair}' must be IG_IDX:PHYS_REG "
                    f"with integer values",
                    err=True,
                )
                raise typer.Exit(code=2)
            parsed_force_phys[ig_idx] = phys
    if force_phys_mode and not parsed_force_phys:
        typer.echo(
            "error: --scorer-mode force-phys requires --force-phys IG:PHYS entries",
            err=True,
        )
        raise typer.Exit(code=2)

    # ----------------------------------------------------------------
    # Write simplify_order_target.yaml
    # ----------------------------------------------------------------

    spec_path = perm_dir / "simplify_order_target.yaml"
    if spec_path.exists() and not force:
        typer.echo(
            f"{spec_path} already exists. Pass --force to overwrite.",
            err=True,
        )
        raise typer.Exit(2)

    coalesce_preservation = not no_coalesce_preservation
    baseline_dump_for_spec = _portable_path_for_base(
        baseline_dump_for_spec_path, perm_dir
    )
    if force_phys_mode:
        spec_yaml = _render_force_phys_target_yaml(
            function=function,
            class_id=class_id,
            baseline_dump=baseline_dump_for_spec,
            force_phys=parsed_force_phys,
            coalesce_preservation=coalesce_preservation,
        )
    else:
        spec_yaml = render_simplify_order_target_yaml(
            function=function,
            simplify_order_target=parsed_targets,
            simplify_order_target_late=parsed_targets_late,
            class_id=class_id,
            baseline_dump=baseline_dump_for_spec,
            force_phys=parsed_force_phys or None,
            coalesce_preservation=coalesce_preservation,
        )
    spec_path.write_text(spec_yaml, encoding="utf-8")

    # ----------------------------------------------------------------
    # Update settings.toml (preserve existing weight_overrides)
    # ----------------------------------------------------------------

    settings_path = perm_dir / "settings.toml"
    existing_overrides: dict[str, float] = {}
    if settings_path.exists():
        existing_overrides = parse_existing_overrides(
            settings_path.read_text(encoding="utf-8")
        )

    # Build the scorer command: a fully-quoted invocation of
    # `melee-agent debug target score-simplify-order` with --function
    # and --target pre-baked. Permuter appends the .o path as argv[N].
    scorer_command_name = (
        "score-force-phys" if force_phys_mode else "score-simplify-order"
    )
    scorer_target = _portable_path_for_base(spec_path, perm_root)
    scorer_command = " ".join(
        shlex.quote(s) for s in [
            melee_agent_bin,
            "debug",
            "target",
            scorer_command_name,
            "--function",
            function,
            "--target",
            str(scorer_target),
        ]
    )

    scorer_cfg = ScorerConfig(
        command=scorer_command,
        timeout_seconds=timeout_seconds,
    )

    new_spec = build_spec(
        function,
        pattern=None,
        existing_overrides=existing_overrides,
        merge=True,
        scorer=scorer_cfg,
    )
    write_settings_toml(new_spec, settings_path)

    # ----------------------------------------------------------------
    # Replace compile.sh with the wrapped version
    # ----------------------------------------------------------------

    new_compile = _build_simplify_order_compile_sh(
        wibo_path=wibo_path,
        debug_compiler=debug_compiler,
        project_root=project_root,
        cflags=cflags,
        full_unit_source=full_unit_source,
        function=function,
        full_unit_source_expr=full_unit_source_expr,
        stage_path=full_unit_stage_path,
        remote_portable=remote_portable_compile,
    )
    existing_compile_sh.write_text(new_compile, encoding="utf-8")
    existing_compile_sh.chmod(0o755)

    # ----------------------------------------------------------------
    # Final summary + next-step instructions
    # ----------------------------------------------------------------

    typer.echo(f"Wrote {spec_path}")
    typer.echo(f"Wrote {settings_path}")
    typer.echo(f"Wrote {existing_compile_sh}")
    typer.echo("")
    typer.echo("Setup complete. Next:")
    typer.echo(f"  cd {perm_root}")
    typer.echo(f"  ./permuter.py nonmatchings/{function}")
    typer.echo("")
    typer.echo(
        (
            "Candidates that improve force-phys assignment will be saved to "
            if force_phys_mode
            else "Candidates that improve simplify-order will be saved to "
        ) + f"{perm_dir}/output-*/."
    )


_CFLAGS_LINE_RE = re.compile(
    # Match a line containing mwcceppc(_debug)?.exe (possibly via wibo or wine)
    # and capture everything between the .exe and either "$INPUT" or "-c".
    r"mwcceppc(?:_debug)?\.exe\s+(.*?)(?:\s+-c\b|\s+\"\$INPUT\"|\s+\$INPUT\b)"
)




@permute_app.command(name="config")
def gen_permuter_config(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to generate permuter config for (required).",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    pattern: Annotated[
        Optional[str],
        typer.Option(
            "--pattern", "-p",
            help="Override pattern auto-detection. Use a name from "
                 "`debug util patterns` (e.g. decl-order, alias-split).",
        ),
    ] = None,
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec (YAML or JSON, from `debug target derive`). "
                 "Auto-detection needs this to identify wrong virtuals. "
                 "Without it, falls back to stock settings unless "
                 "--pattern is provided.",
        ),
    ] = None,
    out: Annotated[
        Optional[Path],
        typer.Option(
            "--out", "-o",
            help="Output path. Default: "
                 "<perm-root>/nonmatchings/<function>/settings.toml",
        ),
    ] = None,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    print_only: Annotated[
        bool,
        typer.Option(
            "--print",
            help="Print rendered TOML to stdout instead of writing.",
        ),
    ] = False,
    merge: Annotated[
        bool,
        typer.Option(
            "--merge",
            help="Preserve existing [weight_overrides] keys not touched "
                 "by the pattern profile. Default: overwrite.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Generate config even for skip-marked patterns "
                 "(e.g. param-iter-ceiling). Use only if you know why.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit a JSON summary of the action."),
    ] = False,
) -> None:
    """Generate a decomp-permuter settings.toml tuned for the detected pattern.

    Pairs with `debug permute triage` to close the integration loop: this
    command BIASES which mutations permuter prefers based on mwcc-debug's
    pattern detection, then debug permute triage filters out base.c-vs-real-tree
    drift on the resulting winners.

    For patterns with no useful permuter weighting profile yet
    (for example, param-iter-ceiling), this command refuses to generate
    a config and points at the evidence-gathering workflow. Use
    `--force` to override.

    For `decl-order` specifically, you should ALSO run
    `debug mutate decl-orders` first — it's deterministic and
    ~100x faster than letting permuter rediscover decl-order rounds.
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT  # noqa: PLC0415
    from src.cli.debug import (  # noqa: PLC0415
        _abort_function_not_in_dump,
        _find_wibo,
        _permuter_import_hint,
        _resolve_pcdump_path,
        _resolve_permuter_function_dir,
    )
    from src.cli.debug import _load_target_spec  # noqa: PLC0415
    from ...mwcc_debug.patterns import (
        PATTERNS,
        get_pattern,
        patterns_for_category,
    )
    from ...mwcc_debug.permuter_config import (
        PatternSkippedError,
        build_spec,
        parse_existing_overrides,
        render_settings_toml,
        write_settings_toml,
    )

    melee_root = DEFAULT_MELEE_ROOT

    # Determine the pattern
    detected_via: str = ""
    selected: Optional = None  # type: ignore[type-arg]
    if pattern is not None:
        # Explicit pattern — skip pcdump resolution entirely. Useful when
        # the function isn't yet in report.json (e.g. setting up permuter
        # for a newly-imported function).
        selected = get_pattern(pattern)
        if selected is None:
            typer.echo(
                f"unknown pattern: {pattern!r}. "
                f"Run `melee-agent debug util patterns` to list.",
                err=True,
            )
            raise typer.Exit(2)
        detected_via = "--pattern flag"
    else:
        # Auto-detect via guide/suggest infrastructure
        pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
        text = pcdump_path.read_text()
        fns = parse_pcdump(text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is None:
            _abort_function_not_in_dump(function, [f.name for f in fns])
        events_list = parse_hook_events(text)
        events = find_function(events_list, function)
        if target is not None:
            target_spec = _load_target_spec(target)
        else:
            target_spec = {"virtuals": {}}
        result = score_function(fn, target_spec, events=events)
        suggestions = suggest(fn, result, events=events)

        # Walk suggestions in severity order. For each, find the best-fit
        # pattern. Prefer permuter_skip patterns when they match — those
        # need a different workflow message.
        for s in suggestions:
            candidates = patterns_for_category(s.category)
            # Prefer skip-marked patterns (they're more specific signals)
            skip_candidates = [p for p in candidates if p.permuter_skip]
            if skip_candidates:
                selected = skip_candidates[0]
                detected_via = (
                    f"suggestion category={s.category!r} (severity={s.severity})"
                )
                break
            # Otherwise pick the first pattern with weights
            for p in candidates:
                if p.permuter_weights:
                    selected = p
                    detected_via = (
                        f"suggestion category={s.category!r} "
                        f"(severity={s.severity})"
                    )
                    break
            if selected is not None:
                break

        if selected is None and suggestions:
            # Suggestions exist but no pattern has weights for any category
            detected_via = "no pattern matched any suggestion category"

    # Resolve output path
    if out is None:
        if not perm_root.exists():
            typer.echo(
                f"--perm-root {perm_root} does not exist. "
                f"Clone decomp-permuter there or pass --out explicitly.",
                err=True,
            )
            raise typer.Exit(2)
        fn_dir = _resolve_permuter_function_dir(
            function, perm_root=perm_root, melee_root=melee_root)
        if not fn_dir.exists() and not print_only:
            typer.echo(
                f"{fn_dir} does not exist.\n"
                + _permuter_import_hint(
                    function,
                    perm_root=perm_root,
                    melee_root=melee_root,
                ),
                err=True,
            )
            raise typer.Exit(2)
        out = fn_dir / "settings.toml"

    # Read existing overrides if present (for --merge)
    existing_overrides: dict[str, float] = {}
    if out.exists() and merge:
        existing_overrides = parse_existing_overrides(out.read_text())

    # Build the spec
    try:
        spec = build_spec(
            function,
            selected,
            existing_overrides=existing_overrides,
            merge=merge,
            force=force,
        )
    except PatternSkippedError:
        # No useful permuter weighting profile — print guidance instead of writing.
        assert selected is not None
        if json_out:
            print(json.dumps({
                "function": function,
                "pattern": selected.name,
                "detected_via": detected_via,
                "action": "skipped",
                "reason": "permuter_skip=True (requires Tier 6 evidence workflow)",
            }, indent=2))
            raise typer.Exit(1)
        typer.echo(
            f"Pattern: {selected.name} "
            f"(detected via {detected_via})",
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "This is a Tier 6 allocator-order mismatch with no current "
            "permuter weight profile. The parameter virtual gets a low "
            "ig_idx by C semantics, and locals win the top callee-saves "
            "under the observed simplify order.",
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "Recommended: confirm via `debug target match-iter-first -f "
            f"{function}` and record the result as allocator-order evidence. "
            "If the target is reached, use source-shape search; otherwise "
            "mark it unresolved by current heuristics.",
            err=True,
        )
        typer.echo(
            "Pass --force to debug permute config if you want a config "
            "anyway (no permuter_weights will be applied).",
            err=True,
        )
        raise typer.Exit(1)

    # Render
    rendered = render_settings_toml(spec)

    if print_only:
        if json_out:
            print(json.dumps({
                "function": function,
                "pattern": spec.pattern_name,
                "detected_via": detected_via,
                "action": "printed",
                "overrides": spec.weight_overrides,
                "toml": rendered,
            }, indent=2))
            return
        print(rendered, end="")
        return

    write_settings_toml(spec, out)

    # Side-effect: fix the compile.sh for macOS+wine if it has the
    # known import.py path-handling bug. Quiet if not applicable;
    # one-liner note if a fix was applied.
    from ...mwcc_debug.fix_perm_compile import FixResult, fix_perm_dir
    config_wibo = _find_wibo()
    if config_wibo is None:
        compile_fix = FixResult(
            path=out.parent / "compile.sh",
            action="skipped",
            reason="custom wibo executable not found",
        )
    else:
        compile_fix = fix_perm_dir(out.parent, wibo_path=config_wibo)

    if json_out:
        print(json.dumps({
            "function": function,
            "pattern": spec.pattern_name,
            "detected_via": detected_via,
            "action": "wrote",
            "path": str(out),
            "overrides": spec.weight_overrides,
            "compile_sh_fix": {
                "action": compile_fix.action,
                "reason": compile_fix.reason,
            },
        }, indent=2))
        return

    if spec.pattern_name:
        print(f"Pattern: {spec.pattern_name} (detected via {detected_via})")
        if spec.weight_overrides:
            print(f"Weight overrides:")
            for key in sorted(spec.weight_overrides):
                print(f"  {key} = {spec.weight_overrides[key]}")
    else:
        print(f"No pattern detected ({detected_via or 'no suggestions'}). "
              f"Wrote stock settings.")
    print(f"Wrote: {out}")
    if compile_fix.action == "fixed":
        print(
            f"Also fixed: {compile_fix.path.name} "
            f"(macOS+wine path handling)"
        )
    print()

    # Tail recommendation
    if spec.pattern_name == "decl-order":
        print(
            "Tip: for decl-order specifically, try the deterministic "
            "search first — it's ~100x faster than letting permuter "
            "rediscover decl-order rounds:"
        )
        print(
            f"  melee-agent debug mutate decl-orders "
            f"-f {function} --keep-best"
        )
        print(
            "If that doesn't find a win, fall back to permuter with "
            "this config."
        )
    else:
        rel_dir = out.parent.relative_to(perm_root) \
            if perm_root in out.parents else out.parent
        print(f"Run: cd {perm_root} && ./permuter.py {rel_dir}")


@permute_app.command(name="fix-compile")
def fix_perm_compile(
    target: Annotated[
        Path,
        typer.Argument(
            help="Path to either a nonmatchings/<fn>/ directory or a "
                 "compile.sh file directly.",
        ),
    ],
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Fix decomp-permuter's `compile.sh` for macOS+wine compatibility.

    The compile.sh generated by `import.py` passes an absolute mac path
    to mwcc via wine, which fails with an OS_PATHSEP assertion. This
    command rewrites it to stage the candidate as a relative path
    inside `nonmatchings/.permuter_stage_$$.c` (git-ignored,
    parallel-safe), which mwcc accepts.

    Idempotent: re-running on an already-fixed file is a no-op.

    Pass either the function's permuter dir (e.g.
    `~/code/decomp-permuter/nonmatchings/fn_xyz`) or the compile.sh
    directly.
    """
    from ...mwcc_debug.fix_perm_compile import (
        fix_compile_sh,
        fix_perm_dir,
    )

    if not target.exists():
        typer.echo(f"target not found: {target}", err=True)
        raise typer.Exit(2)

    try:
        if target.is_dir():
            result = fix_perm_dir(target)
        else:
            result = fix_compile_sh(target)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)

    if json_out:
        print(json.dumps({
            "path": str(result.path),
            "action": result.action,
            "reason": result.reason,
        }, indent=2))
        if result.action in ("skipped", "not-applicable"):
            raise typer.Exit(1)
        return

    icons = {
        "fixed": "[ok]",
        "already-fixed": "[--]",
        "not-applicable": "[!!]",
        "skipped": "[!!]",
    }
    icon = icons.get(result.action, "[??]")
    print(f"{icon} {result.path}")
    print(f"   {result.action}: {result.reason}")
    if result.action == "fixed":
        print()
        print("Now permuter's compile.sh will:")
        print("  1. Stage the candidate as nonmatchings/.permuter_stage_$$.c")
        print("  2. Pass that relative path to mwcc (avoids OS_PATHSEP)")
        print("  3. Clean up the stage file on exit")
    if result.action in ("skipped", "not-applicable"):
        raise typer.Exit(1)






















def _target_virtuals_from_spec(target_spec: Mapping[str, Any]) -> dict[int, int]:
    raw = target_spec.get("virtuals", {})
    virtuals: dict[int, int] = {}
    if not isinstance(raw, Mapping):
        return virtuals
    for virtual, phys in raw.items():
        try:
            virtuals[int(virtual)] = int(phys)
        except (TypeError, ValueError):
            continue
    return virtuals


def _normalize_expression_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_first_def_operands(operands: object) -> str:
    text = _normalize_expression_text(operands)
    if not text:
        return ""
    parts = [part.strip() for part in text.split(",")]
    if parts and re.fullmatch(r"[fr]\d+", parts[0]):
        parts[0] = "<dst>"
    return ",".join(parts)


def _expression_anchor_signature(source: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(source, Mapping):
        return None
    kind = str(source.get("kind") or "")
    expression = _normalize_expression_text(source.get("expression"))
    name = source.get("name")
    if kind == "local" and expression:
        return {
            "kind": "source-expression",
            "source_kind": kind,
            "name": str(name or ""),
            "expression": expression,
        }
    first_def = source.get("first_def")
    if isinstance(first_def, Mapping):
        opcode = _normalize_expression_text(first_def.get("opcode")).lower()
        operands = _normalize_first_def_operands(first_def.get("operands"))
        if opcode or operands:
            return {
                "kind": "first-def",
                "source_kind": kind,
                "opcode": opcode,
                "operands": operands,
            }
    if expression:
        return {
            "kind": "expression",
            "source_kind": kind,
            "name": str(name or ""),
            "expression": expression,
        }
    if name is not None:
        return {
            "kind": "name",
            "source_kind": kind,
            "name": str(name),
        }
    return None


def _expression_signature_key(signature: Mapping[str, Any]) -> str:
    return json.dumps(signature, sort_keys=True, separators=(",", ":"))


def _expression_source_summary(source: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(source, Mapping):
        return None
    summary: dict[str, Any] = {}
    for key in (
        "kind",
        "confidence",
        "name",
        "type",
        "source_file",
        "source_line",
        "source_col",
        "expression",
        "call_symbol",
    ):
        value = source.get(key)
        if value is not None:
            summary[key] = value
    first_def = source.get("first_def")
    if isinstance(first_def, Mapping):
        summary["first_def"] = {
            key: first_def.get(key)
            for key in ("pass_name", "block_idx", "instr_idx", "opcode", "operands")
            if first_def.get(key) is not None
        }
    return summary or None


def _expression_reg_class_from_spec(
    target_spec: Mapping[str, Any],
    requested: str | None,
) -> str:
    raw = requested or target_spec.get("expression_register_class")
    normalized = str(raw or "fpr").strip().lower()
    if normalized in {"f", "float", "floating"}:
        return "fpr"
    if normalized in {"r", "gpr", "int", "integer"}:
        return "gpr"
    return normalized


def _expression_virtuals_for_function(fn: Any, reg_class: str) -> list[int]:
    reg_kind = "f" if reg_class == "fpr" else "r"
    virtuals: set[int] = set()
    for info in analyze_function(fn):
        if getattr(info, "reg_kind", None) == reg_kind:
            virtuals.add(int(info.virtual))
    return sorted(virtuals)


def _expression_anchors_from_spec(
    target_spec: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw = target_spec.get("expression_anchors")
    items: Iterable[tuple[Any, Any]]
    if isinstance(raw, Mapping):
        items = raw.items()
    elif isinstance(raw, list):
        items = [(None, item) for item in raw]
    else:
        return []

    target_virtuals = _target_virtuals_from_spec(target_spec)
    anchors: list[dict[str, Any]] = []
    for raw_key, item in items:
        if not isinstance(item, Mapping):
            continue
        signature = item.get("signature")
        if not isinstance(signature, Mapping):
            continue
        try:
            baseline_value = item.get("baseline_virtual", item.get("virtual"))
            if baseline_value is None:
                baseline_value = raw_key
            baseline_virtual = int(
                baseline_value
            )
            expected_value = item.get("expected", item.get("target_reg"))
            if expected_value is None:
                expected_value = target_virtuals[baseline_virtual]
            expected = int(expected_value)
        except (TypeError, ValueError):
            continue
        anchors.append({
            "baseline_virtual": baseline_virtual,
            "expected": expected,
            "signature": dict(signature),
            "baseline_source": item.get("baseline_source"),
        })
    return anchors


def _derive_expression_anchors(
    *,
    target_spec: Mapping[str, Any],
    baseline_pcdump_text: str,
    function: str,
    source_text: str | None,
    source_file: str | None,
    reg_class: str,
) -> list[dict[str, Any]]:
    from ...mwcc_debug.virtual_attribution import explain_virtuals

    target_virtuals = _target_virtuals_from_spec(target_spec)
    if not target_virtuals:
        return []
    report = explain_virtuals(
        baseline_pcdump_text,
        function,
        virtuals=sorted(target_virtuals),
        source_text=source_text,
        source_file=source_file,
        reg_class=reg_class,
    )

    anchors: list[dict[str, Any]] = []
    for entry in report.to_dict().get("virtuals", []):
        if not isinstance(entry, Mapping):
            continue
        try:
            virtual = int(entry.get("virtual"))
        except (TypeError, ValueError):
            continue
        if virtual not in target_virtuals:
            continue
        source = entry.get("source")
        signature = _expression_anchor_signature(
            source if isinstance(source, Mapping) else None
        )
        if signature is None:
            continue
        anchors.append({
            "baseline_virtual": virtual,
            "expected": target_virtuals[virtual],
            "signature": signature,
            "baseline_source": _expression_source_summary(
                source if isinstance(source, Mapping) else None
            ),
        })
    return anchors


def _candidate_expression_entries(
    *,
    pcdump_text: str,
    function: str,
    fn: Any,
    source_text: str | None,
    source_file: str | None,
    reg_class: str,
) -> dict[str, list[dict[str, Any]]]:
    from ...mwcc_debug.virtual_attribution import explain_virtuals

    virtuals = _expression_virtuals_for_function(fn, reg_class)
    if not virtuals:
        return {}
    report = explain_virtuals(
        pcdump_text,
        function,
        virtuals=virtuals,
        source_text=source_text,
        source_file=source_file,
        reg_class=reg_class,
    )
    by_signature: dict[str, list[dict[str, Any]]] = {}
    for entry in report.to_dict().get("virtuals", []):
        if not isinstance(entry, Mapping):
            continue
        source = entry.get("source")
        signature = _expression_anchor_signature(
            source if isinstance(source, Mapping) else None
        )
        if signature is None:
            continue
        key = _expression_signature_key(signature)
        by_signature.setdefault(key, []).append({
            "virtual": entry.get("virtual"),
            "actual": entry.get("assigned_reg"),
            "signature": signature,
            "source": _expression_source_summary(
                source if isinstance(source, Mapping) else None
            ),
        })
    return by_signature






@permute_app.command(name="run")
def permute(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to permute (required).",
        ),
    ],
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec for mwcc-debug scoring. Auto-derived from "
                 "current pcdump if omitted.",
        ),
    ] = None,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    blend: Annotated[
        float,
        typer.Option(
            "--blend",
            help="Weight α applied to mwcc-debug score when blending "
                 "with objdiff bytes. Final = bytes + α * mwcc.",
        ),
    ] = 0.1,
    threads: Annotated[
        int,
        typer.Option(
            "-j", "--threads",
            help="Permuter parallelism. score-source now uses unique "
                 "per-PID pcdump filenames so parallel threads no longer "
                 "race; safe to raise above 1.",
        ),
    ] = 1,
    extra: Annotated[
        Optional[list[str]],
        typer.Argument(
            help="Extra args passed through to permuter.py.",
        ),
    ] = None,
) -> None:
    """Tier 2: run decomp-permuter with mwcc-debug score blended in.

    Per-iteration, permuter scores candidates by combining objdiff
    byte-distance with `melee-agent debug target score-source` (IGNode-distance
    from pcdump). Byte distance stays primary; the mwcc signal breaks
    ties between byte-equivalent candidates — useful for register-cascade
    stuck cases where the byte scorer can't distinguish many mutations.

    Prerequisites:
    - Run `melee-agent debug dump setup` (one-time).
    - `<perm-root>/nonmatchings/<function>/` exists with base.c, target.o,
      compile.sh. Create via `decomp-permuter/import.py`.
    - `melee-agent debug permute fix-compile <perm_dir>` if compile.sh was
      generated on macOS (auto-applied by debug permute config).

    Default is single-threaded for safety. score-source now emits
    per-PID pcdump filenames so parallel threads no longer race on a
    shared pcdump.txt — raise `-j` above 1 if you want concurrency.

    Passing flags through to permuter.py: Typer will try to consume any
    leading `--<name>` tokens as options of `permute` itself. Use `--`
    to separate. Examples:

        # WRONG — Typer rejects --best-only as an unknown option
        melee-agent debug permute run -f my_fn --best-only

        # RIGHT — `--` ends `permute run`'s own options; everything after
        # is forwarded to permuter.py
        melee-agent debug permute run -f my_fn -- --best-only
        melee-agent debug permute run -f my_fn -j 4 -- --best-only --seed 0

    Note: stdout is set to line-buffering so that piping through `tail -N`
    shows live progress instead of buffering until the permuter exits.
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT  # noqa: PLC0415
    from src.cli.debug import (  # noqa: PLC0415
        _abort_function_not_in_dump,
        _find_compiler_dir,
        _find_wibo,
        _ninja_cflags_for_unit,
        _permuter_import_hint,
        _resolve_decomp_permuter_root,
        _resolve_permuter_function_dir,
    )
    from src.cli.debug import _find_unit_for_function  # noqa: PLC0415
    # Force line-buffering on stdout so progress output is visible when
    # the command is piped (e.g. `melee-agent debug permute run ... | tail -20`).
    # Without this, Python's stdio buffering holds all output until the
    # process exits — which never happens naturally for the permuter.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

    melee_root = DEFAULT_MELEE_ROOT
    perm_dir = _resolve_permuter_function_dir(
        function, perm_root=perm_root, melee_root=melee_root)

    if not perm_dir.exists():
        typer.echo(
            f"{perm_dir} not found.\n"
            + _permuter_import_hint(
                function,
                perm_root=perm_root,
                melee_root=melee_root,
            ),
            err=True,
        )
        raise typer.Exit(2)

    # Resolve TU for cflags
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"could not find {function!r} in report.json. "
            f"Rebuild via `ninja build/GALE01/report.json`.",
            err=True,
        )
        raise typer.Exit(3)
    unit_c = f"src/{unit}.c"

    # Derive target if not given
    if target is None:
        target = melee_root / "build" / "mwcc_debug_cache" / \
            f"{unit}_target.json"
        target.parent.mkdir(parents=True, exist_ok=True)

        cache_p = pcdump_cache.cache_path(melee_root, unit)
        if not cache_p.exists():
            print(
                f"[..] no cached pcdump for {unit}; "
                f"generating via debug dump local..."
            )
            wibo_p = _find_wibo()
            cc_p = _find_compiler_dir() / "mwcceppc_debug.exe"
            if wibo_p is None or not wibo_p.exists() or not cc_p.exists():
                typer.echo(
                    "wibo or patched compiler missing. Run "
                    "`melee-agent debug dump setup` first.",
                    err=True,
                )
                raise typer.Exit(4)
            cflags, _ = _ninja_cflags_for_unit(unit_c)
            pcd_path = melee_root / "pcdump.txt"
            if pcd_path.exists():
                pcd_path.unlink()
            subprocess.run(
                [str(wibo_p), str(cc_p)]
                + shlex.split(cflags)
                + ["-c", unit_c, "-o", "/tmp/permute_init.o"],
                cwd=melee_root,
                check=True,
            )
            pcdump_cache.ensure_cache_dir(melee_root)
            pcd_path.rename(cache_p)
            print(f"[ok] pcdump → {cache_p}")

        from ...mwcc_debug import derive_target_from_function
        text = cache_p.read_text()
        fns = parse_pcdump(text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is None:
            _abort_function_not_in_dump(function, [f.name for f in fns])
        spec = derive_target_from_function(fn)
        target.write_text(json.dumps(spec, indent=2))
        print(f"[ok] derived target → {target}")
    else:
        print(f"[ok] using target: {target}")

    # Locate the wrapper script
    wrapper = (
        melee_root / "tools" / "melee-agent" / "scripts"
        / "permute_with_mwcc.py"
    )
    if not wrapper.exists():
        typer.echo(f"wrapper not found: {wrapper}", err=True)
        raise typer.Exit(4)

    # Build env
    env = os.environ.copy()
    permuter_code_root = _resolve_decomp_permuter_root(perm_root)
    env["MELEE_PERMUTER_ROOT"] = str(permuter_code_root)
    env["MELEE_ROOT"] = str(melee_root)
    env["MWCC_DEBUG_TARGET"] = str(target)
    env["MWCC_DEBUG_FN"] = function
    env["MWCC_DEBUG_UNIT"] = unit_c
    env["MWCC_DEBUG_BLEND"] = str(blend)

    cmd = ["python", str(wrapper), str(perm_dir), "-j", str(threads)]
    if extra:
        cmd.extend(extra)

    print(f"[ok] launching permuter (blend={blend} threads={threads})...")
    print(f"  {' '.join(cmd)}")
    print()

    returncode = _run_local_permuter(cmd, env=env, cwd=permuter_code_root)
    raise typer.Exit(returncode)
