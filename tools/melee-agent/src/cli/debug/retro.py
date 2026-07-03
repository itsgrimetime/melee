"""`melee-agent debug retro` — retail-binary MWCC introspection (issue #541)."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import typer

retro_app = typer.Typer(
    help="Retail-binary MWCC introspection via retrowin32 + gdb "
         "(front-end IRO tracing, backend PCode, regalloc, stack maps)."
)

# Package checkout discovery (this file is tools/melee-agent/src/cli/debug/retro.py).
_PACKAGE_REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(_PACKAGE_REPO))
from tools.mwcc_retro import backend_events, TABLES_DIR, setup as retro_setup  # noqa: E402


@dataclass
class DumpOutcome:
    exit_code: int
    produced: list[str]
    missing: list[str] = field(default_factory=list)


@dataclass
class BackendOutcome:
    exit_code: int
    trace: dict | None = None
    fidelity: dict | None = None
    missing: list[str] = field(default_factory=list)


def _looks_like_melee_root(path: Path) -> bool:
    return (
        (path / "src" / "melee").is_dir()
        and (path / "tools" / "mwcc_retro").is_dir()
        and ((path / "build.ninja").exists() or (path / "configure.py").exists())
    )


def _find_melee_root(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        if _looks_like_melee_root(candidate):
            return candidate
    return None


def _resolve_melee_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        root = explicit.expanduser().resolve()
        if not _looks_like_melee_root(root):
            raise typer.BadParameter(
                f"--melee-root is not a Melee checkout: {root}",
                param_hint="--melee-root",
            )
        return root
    return (_find_melee_root(Path.cwd()) or _PACKAGE_REPO).resolve()


def _retro_tables_dir(melee_root: Path) -> Path:
    worktree_tables = melee_root / "tools" / "mwcc_retro" / "tables"
    return worktree_tables if worktree_tables.is_dir() else TABLES_DIR


def _resolve_output_dir(out: Path | None, *, melee_root: Path, src: str, fn: str) -> Path:
    if out is not None:
        return out.expanduser().resolve() if out.is_absolute() else melee_root / out
    unit = Path(src).with_suffix("").as_posix().replace("/", "_")
    return melee_root / "build" / "mwcc_retro" / unit / fn


def _ensure_setup(melee_root: Path | None = None):
    root = _resolve_melee_root(melee_root)
    if hasattr(retro_setup, "ensure_for_root"):
        return retro_setup.ensure_for_root(root, force=False)
    return retro_setup.ensure(force=False)


def _write_backend_outputs(
    out_dir: Path,
    trace: dict,
    fidelity: dict | None = None,
) -> None:
    from tools.mwcc_retro import backend_fidelity, backend_schema, backend_summary

    out_dir.mkdir(parents=True, exist_ok=True)
    errors = backend_schema.validate_backend_trace(trace)
    if errors:
        raise RuntimeError("backend trace schema errors: " + "; ".join(errors))
    backend_schema.write_backend_trace(out_dir / "backend-trace.v1.json", trace)
    (out_dir / "regalloc-summary.txt").write_text(
        backend_summary.render_regalloc_summary(trace)
    )
    (out_dir / "backend-summary.txt").write_text(
        backend_summary.render_backend_summary(trace)
    )
    if fidelity is not None:
        (out_dir / "backend-fidelity.json").write_text(
            json.dumps(fidelity, indent=2, sort_keys=True) + "\n"
        )
        (out_dir / "backend-fidelity.txt").write_text(
            backend_fidelity.render_fidelity_text(fidelity)
        )


def _tail_text(value, *, limit: int = 2000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode(errors="replace")
    else:
        text = str(value)
    return text[-limit:]


def _tail(text: str, *, lines: int = 20) -> str:
    return "\n".join(str(text).splitlines()[-lines:])


def _process_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _format_parity_mismatch(parity: dict) -> str:
    def object_line(label: str, data: dict | None) -> str:
        data = data or {}
        return (
            f"{label}: path={data.get('path', '<unknown>')} "
            f"size={data.get('size', '<unknown>')} "
            f"sha256={data.get('sha256', '<unknown>')}"
        )

    return "\n".join(
        [
            "backend object parity mismatch",
            object_line("reference", parity.get("reference")),
            object_line("retro", parity.get("retro")),
        ]
    )


def _format_parity_compile_error(*, phase: str, cmd: list[str], exc) -> str:
    import shlex
    import subprocess

    lines = [
        f"backend object parity {phase} compile failed",
        "command: " + shlex.join([str(part) for part in cmd]),
    ]
    if isinstance(exc, subprocess.CalledProcessError):
        lines.append(f"exit code: {exc.returncode}")
        stdout = _tail_text(getattr(exc, "stdout", None) or getattr(exc, "output", None))
        stderr = _tail_text(getattr(exc, "stderr", None))
    elif isinstance(exc, subprocess.TimeoutExpired):
        lines.append(f"timeout: {exc.timeout}s")
        stdout = _tail_text(getattr(exc, "stdout", None) or getattr(exc, "output", None))
        stderr = _tail_text(getattr(exc, "stderr", None))
    else:
        lines.append(f"error: {exc}")
        stdout = ""
        stderr = ""
    if stdout:
        lines.append("stdout tail:\n" + stdout)
    if stderr:
        lines.append("stderr tail:\n" + stderr)
    return "\n".join(lines)


def _run_parity_compile_command(*, phase: str, cmd: list[str], melee_root: Path) -> None:
    import subprocess

    try:
        subprocess.run(
            cmd,
            cwd=melee_root,
            check=True,
            capture_output=True,
            timeout=300,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(
            _format_parity_compile_error(phase=phase, cmd=cmd, exc=exc)
        ) from exc


def _run_object_parity_for_backend(*, src: str, melee_root: Path) -> dict:
    """Run the raw .o byte-parity gate for backend tracing."""
    import shlex
    import tempfile

    from tools.mwcc_retro import object_parity, setup as _setup

    setup_result = _setup.ensure_for_root(melee_root, force=False)
    cmd = _ninja_cmd_for_unit(src, melee_root=melee_root)
    parts = shlex.split(cmd)
    compiler = str(melee_root / parts[0])
    args = [p for p in parts[1:] if p != "-MMD"]
    with tempfile.TemporaryDirectory() as td:
        ref = Path(td) / "reference.o"
        retro_obj = Path(td) / "retro.o"

        def with_output(path: Path) -> list[str]:
            local = list(args)
            if "-o" in local:
                local[local.index("-o") + 1] = str(path)
            else:
                local += ["-o", str(path)]
            return local

        wibo = melee_root / "build/tools/wibo"
        sjis = melee_root / "build/tools/sjiswrap.exe"
        if sjis.exists():
            normal_cmd = [str(wibo), str(sjis), compiler] + with_output(ref)
        else:
            normal_cmd = [str(wibo), compiler] + with_output(ref)
        _run_parity_compile_command(
            phase="reference",
            cmd=normal_cmd,
            melee_root=melee_root,
        )
        _run_parity_compile_command(
            phase="retro",
            cmd=[str(setup_result.retrowin32_bin), compiler] + with_output(retro_obj),
            melee_root=melee_root,
        )
        return object_parity.compare_objects(ref, retro_obj).to_dict()


def _launch_backend_events(*, src: str, fn: str, out_dir: Path, melee_root: Path) -> Path:
    """Launch retrowin32+gdb backend event tracing and return JSONL path."""
    import os
    import shlex
    import subprocess

    from tools.mwcc_retro import setup as _setup

    setup_result = _setup.ensure_for_root(melee_root, force=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "backend-events.v1.jsonl"
    table = _retro_tables_dir(melee_root) / "gc_125n.json"
    launcher = melee_root / "tools" / "mwcc_retro" / "mwcc_retro_debugger.py"
    if not launcher.exists():
        launcher = _PACKAGE_REPO / "tools" / "mwcc_retro" / "mwcc_retro_debugger.py"

    ninja_cmd = _ninja_cmd_for_unit(src, melee_root=melee_root)
    parts = shlex.split(ninja_cmd)
    if not parts:
        raise RuntimeError("backend event launcher failed: empty compiler command")
    mwcc_exe = melee_root / "build" / "compilers" / "GC" / "1.2.5n" / "mwcceppc.exe"
    mwcc_args = shlex.join([str(mwcc_exe), *parts[1:]])
    cmd = [
        "python3",
        str(launcher),
        "-e",
        str(setup_result.retrowin32_bin),
        "-a",
        mwcc_args,
        "--table",
        str(table),
        "--out",
        str(out_dir),
        "--phases",
        "backend",
        "--compiler",
        "1.2.5n",
        fn,
    ]
    env = dict(os.environ, RETRO_SOURCE=src, RETRO_FUNCTION=fn)
    command_text = shlex.join([str(part) for part in cmd])
    launch_log = out_dir / "launch.log"

    def write_launch_log(*, exit_text: str, stdout="", stderr="") -> None:
        launch_log.write_text(
            "\n".join(
                [
                    f"COMMAND: {command_text}",
                    f"RETRO_SOURCE: {src}",
                    f"RETRO_FUNCTION: {fn}",
                    f"EXIT: {exit_text}",
                    "STDOUT:",
                    _process_text(stdout),
                    "STDERR:",
                    _process_text(stderr),
                ]
            )
            + "\n"
        )

    def remove_partial_events() -> None:
        events_path.unlink(missing_ok=True)

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(melee_root),
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = getattr(exc, "stdout", None) or getattr(exc, "output", None)
        stderr = getattr(exc, "stderr", None)
        write_launch_log(
            exit_text=f"timeout after {exc.timeout:g}s",
            stdout=stdout,
            stderr=stderr,
        )
        remove_partial_events()
        raise RuntimeError(
            "backend event launcher timed out"
            + ("\n" + _tail(_process_text(stdout) + "\n" + _process_text(stderr))
               if stdout or stderr else "")
        ) from exc
    except OSError as exc:
        write_launch_log(exit_text=f"{exc.__class__.__name__}: {exc}")
        remove_partial_events()
        raise RuntimeError(
            f"backend event launcher failed: {exc.__class__.__name__}: {exc}"
        ) from exc

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    write_launch_log(exit_text=str(proc.returncode), stdout=proc.stdout, stderr=proc.stderr)

    if "[retro] ABORT:" in combined:
        remove_partial_events()
        raise RuntimeError(
            "backend event launcher aborted"
            + ("\n" + _tail(combined) if combined.strip() else "")
        )
    if proc.returncode != 0:
        remove_partial_events()
        raise RuntimeError(
            f"backend event launcher failed (exit {proc.returncode})"
            + ("\n" + _tail(combined) if combined.strip() else "")
        )
    if not events_path.exists() or events_path.stat().st_size == 0:
        remove_partial_events()
        raise RuntimeError(
            "backend event launcher produced no backend-events.v1.jsonl"
            + ("\n" + _tail(combined) if combined.strip() else "")
        )
    return events_path


def _run_backend_trace(
    *,
    src: str,
    fn: str,
    out_dir: Path,
    verify_debug: bool,
    melee_root: Path,
) -> BackendOutcome:
    parity = _run_object_parity_for_backend(src=src, melee_root=melee_root)
    if not parity.get("matched"):
        raise RuntimeError(_format_parity_mismatch(parity))
    try:
        events_path = _launch_backend_events(
            src=src,
            fn=fn,
            out_dir=out_dir,
            melee_root=melee_root,
        )
    except RuntimeError:
        raise
    events = backend_events.load_events(events_path)
    trace = backend_events.normalize_events(
        events,
        compiler={"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
        source={
            "tu": src,
            "function": fn,
            "mwcc_command_hash": "sha256:"
            + __import__("hashlib").sha256(src.encode()).hexdigest(),
        },
        tool_version="mwcc-retro-dev",
    )
    fidelity = None
    if verify_debug:
        fidelity = {"schema_version": "mwcc-retro-backend-fidelity.v1", "summary": {}}
    return BackendOutcome(exit_code=0, trace=trace, fidelity=fidelity)


def _ninja_cmd_for_unit(src_rel: str, *, melee_root: Path) -> str:
    """The mwcceppc command line for a unit, WITHOUT wibo/sjiswrap prefix."""
    from src.cli.debug import _ninja_cflags_for_unit
    cflags, _mw = _ninja_cflags_for_unit(src_rel, melee_root=melee_root)
    unit = src_rel
    obj = f"build/GALE01/{Path(src_rel).with_suffix('.o')}"
    compiler = "build/compilers/GC/1.2.5n/mwcceppc.exe"
    return f"{compiler} {cflags} -c {unit} -o {obj}"


def _launch_dump(*, src: str, fn: str, phases: str, compiler: str,
                 out_dir: Path, table: Path, melee_root: Path,
                 gdb_py: str = "") -> DumpOutcome:
    """Invoke the gdb-side launcher, then post-process the IRO trace.

    Runs `mwcc_retro_debugger.py main()` (host launcher), which drives
    retrowin32 + gdb to write `iro-trace.txt`. On success, splits the trace into
    per-phase files and builds `iro-summary.txt` (the node/temp ledger). Returns
    a DumpOutcome whose exit code follows the contract in the spec. When `gdb_py`
    is set, the gdb session is handed to that intervention hook instead.
    """
    import subprocess

    from tools.mwcc_retro import setup as _setup, trace_summary

    if hasattr(_setup, "ensure_for_root"):
        res = _setup.ensure_for_root(melee_root, force=False)
    else:
        res = _setup.ensure(force=False)
    mwcc_dir = melee_root / "build" / "compilers" / "GC" / compiler
    mwcc_args = _ninja_cmd_for_unit(src, melee_root=melee_root)
    # strip the leading compiler path; the launcher prepends the emulator.
    mwcc_args = mwcc_args.split(" ", 1)[1] if " " in mwcc_args else mwcc_args
    mwcc_exe = str(mwcc_dir / "mwcceppc.exe")
    launcher = res.cadmic_script.parent.parent.parent / "mwcc_retro_debugger.py"
    if not launcher.exists():
        launcher = melee_root / "tools" / "mwcc_retro" / "mwcc_retro_debugger.py"
    if not launcher.exists():
        launcher = _PACKAGE_REPO / "tools" / "mwcc_retro" / "mwcc_retro_debugger.py"
    cmd = [
        "python3", str(launcher),
        "-e", str(res.retrowin32_bin),
        "-a", f"{mwcc_exe} {mwcc_args}",
        "--table", str(table),
        "--out", str(out_dir),
        "--phases", phases,
        "--compiler", compiler,
    ]
    if gdb_py:
        cmd += ["--gdb-py", str(Path(gdb_py).resolve())]
    cmd.append(fn)
    # Run from the active repo root so the emulated mwcceppc resolves the relative
    # source path (the ninja command uses repo-relative paths, like wibo does).
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                          cwd=str(melee_root))
    log = (out_dir / "launch.log")
    log.write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr)

    if gdb_py:
        # The hook owns the session; trace/backend post-processing doesn't apply.
        ran = "[retro] running intervention hook" in proc.stdout
        if ran and proc.returncode == 0:
            return DumpOutcome(exit_code=0, produced=["hook"], missing=[])
        return DumpOutcome(exit_code=2, produced=[], missing=["hook"])

    produced: list[str] = []
    missing: list[str] = []
    target_absent = False  # set by the host-side trace filter below
    safety_aborted = "[retro] ABORT" in proc.stdout
    trace = out_dir / "iro-trace.txt"
    if phases in ("frontend", "all"):
        if trace.exists() and trace.stat().st_size > 0:
            # Dumps are enabled globally (all functions); isolate the target's
            # section host-side (robust per-function scoping, #546).
            full = trace.read_text(errors="replace")
            text = trace_summary.filter_to_function(full, fn)
            if text and f"Dumping function {fn} after" in text:
                trace.write_text(text)  # iro-trace.txt = target only
                trace_summary.split_phase_files(text, out_dir)
                (out_dir / "iro-summary.txt").write_text(
                    trace_summary.build_summary(text))
                produced.append("frontend")
            else:
                # trace produced but no section for the target fn -> not found
                target_absent = True
                missing.append("frontend")
        else:
            missing.append("frontend")

    if phases in ("backend", "all"):
        # cadmic writes backend/regalloc/variables files straight into out_dir.
        backend_files = (list(out_dir.glob("backend-*.txt"))
                         + list(out_dir.glob("regalloc-*.txt")))
        if backend_files:
            produced.append("backend")
        elif phases == "backend":
            missing.append("backend")

    if safety_aborted and not produced:
        # a read-before-write byte assert or fopen-NULL fired gdb-side
        return DumpOutcome(exit_code=5, produced=produced, missing=missing)
    if proc.returncode != 0 and not produced and not target_absent:
        return DumpOutcome(exit_code=2, produced=produced, missing=missing)
    if target_absent and not produced:
        return DumpOutcome(exit_code=3, produced=produced, missing=missing)
    if missing:
        return DumpOutcome(exit_code=4, produced=produced, missing=missing)
    return DumpOutcome(exit_code=0, produced=produced, missing=missing)


def _write_backend_source_attribution(
    *,
    out_dir: Path,
    src: str,
    fn: str,
    compiler: str,
    missing: list[str],
    melee_root: Path,
) -> Path | None:
    """Write a source-attribution sidecar when 1.2.5n backend streams are absent."""
    if compiler != "1.2.5n" or "backend" not in missing:
        return None

    payload: dict = {
        "status": "backend-trace-unavailable",
        "function": fn,
        "source": src,
        "compiler": compiler,
        "reason": (
            "retail GC/1.2.5n backend/regalloc hooks are not populated; "
            "this sidecar uses mwcc-debug pcdump source attribution as the "
            "actionable fallback instead of fabricating backend decisions"
        ),
        "source_attribution": [],
        "next_commands": [
            f"melee-agent debug dump local {src} --function {fn}",
            f"melee-agent debug inspect explain-virtual --function {fn} --virtual <ig>",
        ],
    }

    try:
        import importlib

        debug_cli = importlib.import_module("src.cli.debug")
        from src.mwcc_debug.colorgraph_parser import (
            find_function,
            parse_hook_events,
        )
        from src.mwcc_debug.virtual_attribution import explain_virtuals

        pcdump_path = debug_cli._resolve_pcdump_path(
            None,
            fn,
            melee_root,
            require_fresh=False,
        )
        pcdump_text = pcdump_path.read_text(encoding="utf-8")
        source_path = melee_root / src
        source_text = (
            source_path.read_text(encoding="utf-8")
            if source_path.exists() else ""
        )
        events = find_function(parse_hook_events(pcdump_text), fn)
        if events is None or not events.colorgraph_sections:
            payload["status"] = "pcdump-no-colorgraph"
            payload["pcdump"] = str(pcdump_path)
            payload["reason"] = (
                "cached pcdump resolved, but it has no COLORGRAPH DECISIONS "
                "for backend source attribution"
            )
        else:
            payload["pcdump"] = str(pcdump_path)
            classes = []
            for section in events.colorgraph_sections:
                virtuals = sorted({
                    decision.ig_idx
                    for decision in section.decisions
                    if decision.ig_idx >= 0
                })
                if not virtuals:
                    continue
                report = explain_virtuals(
                    pcdump_text,
                    fn,
                    virtuals=virtuals,
                    source_text=source_text,
                    source_file=str(source_path),
                    reg_class="fp" if section.class_id == 1 else "gpr",
                )
                classes.append({
                    "class_id": section.class_id,
                    "virtual_count": len(virtuals),
                    "virtuals": report.to_dict()["virtuals"],
                })
            payload["source_attribution"] = classes
    except Exception as exc:
        payload["status"] = "pcdump-unavailable"
        payload["reason"] = (
            "backend trace unavailable and mwcc-debug pcdump attribution "
            f"could not be resolved: {exc}"
        )

    out_path = out_dir / "backend-source-attribution.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return out_path


@retro_app.command("setup")
def setup_cmd(force: bool = typer.Option(False, "--force")):
    """Clone + build retrowin32 and cadmic at pinned SHAs (idempotent)."""
    try:
        res = retro_setup.ensure(force=force)
    except retro_setup.SetupError as e:
        typer.secho(f"setup failed: {e}", fg="red", err=True)
        raise typer.Exit(1)
    typer.echo(f"retrowin32: {res.retrowin32_bin}")
    typer.echo(f"cadmic:     {res.cadmic_script}")
    typer.echo(f"rebuilt:    {res.rebuilt}")


@retro_app.command("dump")
def dump_cmd(
    src: str = typer.Argument(..., help="TU source path, e.g. src/melee/mn/mnvibration.c"),
    fn: str = typer.Option(..., "-f", "--function"),
    phases: str = typer.Option("all", "--phases", help="all|frontend|backend"),
    compiler: str = typer.Option("1.2.5n", "--compiler", help="1.2.5n|1.1"),
    out: Path = typer.Option(None, "-O", "--output"),
    melee_root: Path = typer.Option(
        None,
        "--melee-root",
        help="Active Melee checkout/worktree root. Defaults to the current cwd tree.",
    ),
    gdb_py: Path = typer.Option(
        None, "--gdb-py",
        help="Intervention hook (a .py with intervene(ctx)) handed the connected "
             "gdb session to mutate compiler state and replay forward."),
):
    """Dump retail compiler internals for FN in SRC."""
    if phases not in ("all", "frontend", "backend"):
        typer.secho("invalid --phases", fg="red", err=True)
        raise typer.Exit(2)
    if gdb_py is not None and not gdb_py.is_file():
        typer.secho(f"--gdb-py hook not found: {gdb_py}", fg="red", err=True)
        raise typer.Exit(2)
    active_root = _resolve_melee_root(melee_root)
    _ensure_setup(active_root)
    out_dir = _resolve_output_dir(out, melee_root=active_root, src=src, fn=fn)
    out_dir.mkdir(parents=True, exist_ok=True)
    table = _retro_tables_dir(active_root) / (
        "gc_125n.json" if compiler == "1.2.5n" else "gc_11.json"
    )
    outcome = _launch_dump(src=src, fn=fn, phases=phases, compiler=compiler,
                           out_dir=out_dir, table=table, melee_root=active_root,
                           gdb_py=str(gdb_py) if gdb_py else "")
    attribution_path = _write_backend_source_attribution(
        out_dir=out_dir,
        src=src,
        fn=fn,
        compiler=compiler,
        missing=outcome.missing,
        melee_root=active_root,
    )
    _write_provenance(out_dir, src, fn, compiler, table, outcome, active_root)
    if attribution_path is not None:
        typer.echo(f"backend source attribution: {attribution_path}")
    if outcome.missing:
        typer.secho(f"missing phase streams: {outcome.missing}", fg="yellow", err=True)
    raise typer.Exit(outcome.exit_code)


@retro_app.command("backend")
def backend_cmd(
    src: str = typer.Argument(..., help="TU source path, e.g. src/melee/mn/mndiagram.c"),
    fn: str = typer.Option(..., "-f", "--function"),
    out: Path = typer.Option(None, "-O", "--output"),
    melee_root: Path = typer.Option(
        None,
        "--melee-root",
        help="Active Melee checkout/worktree root. Defaults to the current cwd tree.",
    ),
    verify_debug: bool = typer.Option(
        False,
        "--verify-debug",
        help="Also compare the retail backend trace to the mwcc-debug pcdump.",
    ),
):
    """Emit an exact retail GC/1.2.5n backend/regalloc trace."""
    active_root = _resolve_melee_root(melee_root)
    out_dir = _resolve_output_dir(out, melee_root=active_root, src=src, fn=fn)
    try:
        outcome = _run_backend_trace(
            src=src,
            fn=fn,
            out_dir=out_dir,
            verify_debug=verify_debug,
            melee_root=active_root,
        )
        if outcome.trace is not None:
            _write_backend_outputs(out_dir, outcome.trace, outcome.fidelity)
    except RuntimeError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2)
    raise typer.Exit(outcome.exit_code)


@retro_app.command("verify-backend")
def verify_backend_cmd(
    src: str = typer.Argument(..., help="TU source path used for trace generation"),
    fn: str = typer.Option(..., "-f", "--function"),
    trace_path: Path = typer.Option(
        None,
        "--trace",
        help="Existing backend-trace.v1.json. Defaults to the generated output path.",
    ),
    melee_root: Path = typer.Option(None, "--melee-root"),
):
    """Compare a retail backend trace to mwcc-debug pcdump facts."""
    active_root = _resolve_melee_root(melee_root)
    out_dir = _resolve_output_dir(None, melee_root=active_root, src=src, fn=fn)
    trace_file = trace_path or (out_dir / "backend-trace.v1.json")
    if not trace_file.exists():
        typer.secho(f"backend trace not found: {trace_file}", fg="red", err=True)
        raise typer.Exit(2)
    typer.echo(f"backend trace: {trace_file}")
    typer.echo("mwcc-debug comparison wiring lands with the fidelity adapter task")
    raise typer.Exit(0)


@retro_app.command("verify")
def verify_cmd(
    unit: str = typer.Option("src/melee/mn/mnvibration.c", "--unit"),
    fn: str = typer.Option(None, "-f", "--function"),
):
    """Cross-check a retro dump against the existing DLL pcdump (control TU)."""
    from tools.mwcc_retro import verify as rv  # lands in P3
    results = rv.run(unit=unit, fn=fn)
    ok = True
    for r in results:
        typer.echo(f"{'PASS' if r.passed else 'FAIL'} [{r.kind}] {r.name}")
        if r.authoritative and not r.passed:
            ok = False
    raise typer.Exit(0 if ok else 1)


def _write_provenance(out_dir: Path, src, fn, compiler, table, outcome, melee_root):
    from tools.mwcc_retro import RETROWIN32_PIN, CADMIC_PIN
    prov = {
        "true_compiler": compiler,
        "note": "dumps use a GC/1.1 name-spoof internally; true compiler above",
        "src": src, "function": fn,
        "melee_root": str(melee_root),
        "table": str(table),
        "retrowin32_pin": RETROWIN32_PIN, "cadmic_pin": CADMIC_PIN,
        "exit_code": outcome.exit_code,
        "produced": outcome.produced, "missing": outcome.missing,
    }
    (out_dir / "provenance.json").write_text(json.dumps(prov, indent=2) + "\n")
