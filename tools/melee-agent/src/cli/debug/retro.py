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
                 out_dir: Path, table: Path) -> DumpOutcome:
    """Invoke the gdb-side launcher; map its result to an exit code.
    (Full wiring lands in the live phase; this is the single seam tests mock.)"""
    raise NotImplementedError  # implemented in the live phase (P1)


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
):
    """Dump retail compiler internals for FN in SRC."""
    if phases not in ("all", "frontend", "backend"):
        typer.secho("invalid --phases", fg="red", err=True)
        raise typer.Exit(2)
    _ensure_setup()
    unit = Path(src).with_suffix("").as_posix().replace("/", "_")
    out_dir = out or (_REPO / "build" / "mwcc_retro" / unit / fn)
    out_dir.mkdir(parents=True, exist_ok=True)
    table = TABLES_DIR / ("gc_125n.json" if compiler == "1.2.5n" else "gc_11.json")
    outcome = _launch_dump(src=src, fn=fn, phases=phases, compiler=compiler,
                           out_dir=out_dir, table=table)
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
