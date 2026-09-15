"""`melee-agent layout` — TU data-layout auditing."""
from __future__ import annotations

from pathlib import Path

import typer

from ..mwcc_debug.dtk_objdump import find_melee_root  # dtk_objdump.py:69
from ..layout.audit import audit_tu
from ..layout.report import render_json, render_text

layout_app = typer.Typer(help="Audit TU data layout (sections/symbols) vs target")


@layout_app.callback()
def _layout_root() -> None:
    """TU data-layout auditing subcommands."""


@layout_app.command("audit")
def audit_cmd(
    file: Path = typer.Argument(..., help="Path to the TU .c file (relative to CWD)"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    root: Path = typer.Option(None, "--root", help="Repo root (default: auto-detect)"),
    check_binding: bool = typer.Option(False, "--check-binding",
                                       help="Also report STB binding mismatches"),
) -> None:
    """Report data-layout discrepancies for a TU's .c file."""
    c = Path(file)
    if not c.is_absolute():
        c = (Path.cwd() / c).resolve()  # relative paths are CWD-relative
    if not c.exists():
        typer.echo(f"error: file not found: {c}", err=True)
        raise typer.Exit(2)
    repo = Path(root).resolve() if root else find_melee_root()
    res = audit_tu(repo, c, check_binding=check_binding)
    typer.echo(render_json(res) if json_out else render_text(res))
    # A successful audit exits 0 even when discrepancies are found — findings are
    # normal output, not an error. (Reserving nonzero for usage errors also keeps
    # the CLI's failure-report footer from firing on the common "found" case.)
    raise typer.Exit(0)
