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

# Repo root discovery (this file is tools/melee-agent/src/cli/debug/retro.py).
_REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(_REPO))
from tools.mwcc_retro import TABLES_DIR, setup as retro_setup  # noqa: E402


@dataclass
class DumpOutcome:
    exit_code: int
    produced: list[str]
    missing: list[str] = field(default_factory=list)


def _ensure_setup():
    return retro_setup.ensure(force=False)


def _ninja_cmd_for_unit(src_rel: str) -> str:
    """The mwcceppc command line for a unit, WITHOUT wibo/sjiswrap prefix."""
    from src.cli.debug import _ninja_cflags_for_unit
    cflags, _mw = _ninja_cflags_for_unit(src_rel)
    unit = src_rel
    obj = f"build/GALE01/{Path(src_rel).with_suffix('.o')}"
    compiler = "build/compilers/GC/1.2.5n/mwcceppc.exe"
    return f"{compiler} {cflags} -c {unit} -o {obj}"


def _launch_dump(*, src: str, fn: str, phases: str, compiler: str,
                 out_dir: Path, table: Path, gdb_py: str = "") -> DumpOutcome:
    """Invoke the gdb-side launcher, then post-process the IRO trace.

    Runs `mwcc_retro_debugger.py main()` (host launcher), which drives
    retrowin32 + gdb to write `iro-trace.txt`. On success, splits the trace into
    per-phase files and builds `iro-summary.txt` (the node/temp ledger). Returns
    a DumpOutcome whose exit code follows the contract in the spec. When `gdb_py`
    is set, the gdb session is handed to that intervention hook instead.
    """
    import subprocess

    from tools.mwcc_retro import setup as _setup, trace_summary

    res = _setup.ensure(force=False)
    mwcc_dir = _REPO / "build" / "compilers" / "GC" / compiler
    mwcc_args = _ninja_cmd_for_unit(src)
    # strip the leading compiler path; the launcher prepends the emulator.
    mwcc_args = mwcc_args.split(" ", 1)[1] if " " in mwcc_args else mwcc_args
    mwcc_exe = str(mwcc_dir / "mwcceppc.exe")
    launcher = res.cadmic_script.parent.parent.parent / "mwcc_retro_debugger.py"
    if not launcher.exists():
        launcher = _REPO / "tools" / "mwcc_retro" / "mwcc_retro_debugger.py"
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
    # Run from the repo root so the emulated mwcceppc resolves the relative
    # source path (the ninja command uses repo-relative paths, like wibo does).
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                          cwd=str(_REPO))
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
    _ensure_setup()
    unit = Path(src).with_suffix("").as_posix().replace("/", "_")
    out_dir = out or (_REPO / "build" / "mwcc_retro" / unit / fn)
    out_dir.mkdir(parents=True, exist_ok=True)
    table = TABLES_DIR / ("gc_125n.json" if compiler == "1.2.5n" else "gc_11.json")
    outcome = _launch_dump(src=src, fn=fn, phases=phases, compiler=compiler,
                           out_dir=out_dir, table=table,
                           gdb_py=str(gdb_py) if gdb_py else "")
    _write_provenance(out_dir, src, fn, compiler, table, outcome)
    if outcome.missing:
        typer.secho(f"missing phase streams: {outcome.missing}", fg="yellow", err=True)
    raise typer.Exit(outcome.exit_code)


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


def _write_provenance(out_dir: Path, src, fn, compiler, table, outcome):
    from tools.mwcc_retro import RETROWIN32_PIN, CADMIC_PIN
    prov = {
        "true_compiler": compiler,
        "note": "dumps use a GC/1.1 name-spoof internally; true compiler above",
        "src": src, "function": fn,
        "table": str(table),
        "retrowin32_pin": RETROWIN32_PIN, "cadmic_pin": CADMIC_PIN,
        "exit_code": outcome.exit_code,
        "produced": outcome.produced, "missing": outcome.missing,
    }
    (out_dir / "provenance.json").write_text(json.dumps(prov, indent=2) + "\n")
