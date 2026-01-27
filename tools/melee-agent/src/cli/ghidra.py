"""Ghidra integration for decompilation analysis.

This module provides an alternative decompiler view using Ghidra, complementing
the primary m2c-based workflow. Useful for cross-references, type propagation,
and getting a second opinion on tricky functions.

Prerequisites:
    1. Install Ghidra 12.0+ from https://ghidra-sre.org
    2. Set GHIDRA_INSTALL_DIR environment variable
    3. Install GameCube loader: https://github.com/Cuyler36/Ghidra-GameCube-Loader
    4. pip install pyghidra (or add to optional deps)

Setup:
    melee-agent ghidra setup  # Creates Ghidra project from DOL
"""

import os
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from ._common import console, get_agent_melee_root

ghidra_app = typer.Typer(help="Ghidra decompilation tools (alternative to m2c)")

# Lazy-load pyghidra to avoid import errors when not installed
_ghidra_initialized = False
_flat_api = None
_program = None


def _check_ghidra_prereqs() -> tuple[bool, str]:
    """Check if Ghidra prerequisites are met."""
    ghidra_dir = os.environ.get("GHIDRA_INSTALL_DIR")
    if not ghidra_dir:
        return False, "GHIDRA_INSTALL_DIR environment variable not set"

    ghidra_path = Path(ghidra_dir)
    if not ghidra_path.exists():
        return False, f"Ghidra directory not found: {ghidra_dir}"

    # Check for pyghidra
    try:
        import pyghidra
        return True, f"Ghidra: {ghidra_dir}"
    except ImportError:
        return False, "pyghidra not installed. Run: pip install pyghidra"


def _init_ghidra(project_path: Path | None = None):
    """Initialize Ghidra in headless mode."""
    global _ghidra_initialized, _flat_api, _program

    if _ghidra_initialized:
        return True

    ok, msg = _check_ghidra_prereqs()
    if not ok:
        console.print(f"[red]Ghidra setup error:[/red] {msg}")
        return False

    console.print("[dim]Initializing Ghidra (this may take a moment)...[/dim]")

    try:
        import pyghidra
        pyghidra.start()
        _ghidra_initialized = True
        console.print("[green]Ghidra initialized[/green]")
        return True
    except Exception as e:
        console.print(f"[red]Failed to initialize Ghidra:[/red] {e}")
        return False


def _get_project_path() -> Path:
    """Get the default Ghidra project path for this repo."""
    # Check common locations
    candidates = [
        get_agent_melee_root() / ".ghidra_project",
        Path("/tmp/ghidra_melee"),  # Fallback temp location
    ]
    for path in candidates:
        if (path / "melee.gpr").exists():
            return path
    return candidates[0]  # Default


def _get_dol_path() -> Path:
    """Get the DOL binary path."""
    melee_root = get_agent_melee_root()
    # Common locations for the DOL (check multiple potential roots)
    roots_to_check = [melee_root, Path("/Users/mike/code/melee")]
    candidates = []
    for root in roots_to_check:
        candidates.extend([
            root / "baserom.dol",
            root / "orig" / "GALE01" / "sys" / "main.dol",
            root / "build" / "GALE01" / "main.dol",
        ])
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]  # Return first as default even if missing


@ghidra_app.command("status")
def ghidra_status():
    """Check Ghidra installation and project status."""
    ok, msg = _check_ghidra_prereqs()

    if ok:
        console.print(f"[green]✓[/green] {msg}")
    else:
        console.print(f"[red]✗[/red] {msg}")
        console.print("\n[bold]Setup Instructions:[/bold]")
        console.print("""
1. Download Ghidra 12.0+ from https://ghidra-sre.org
2. Extract and set environment variable:
   [cyan]export GHIDRA_INSTALL_DIR=/path/to/ghidra_12.0_PUBLIC[/cyan]

3. Install pyghidra:
   [cyan]pip install pyghidra[/cyan]

4. Install GameCube loader extension:
   - Download from https://github.com/Cuyler36/Ghidra-GameCube-Loader/releases
   - In Ghidra: File → Install Extensions → + → select ZIP
   - Restart Ghidra

5. Create project:
   [cyan]melee-agent ghidra setup[/cyan]
""")
        return

    # Check project status
    project_path = _get_project_path()
    if project_path.exists():
        console.print(f"[green]✓[/green] Ghidra project: {project_path}")
    else:
        console.print(f"[yellow]![/yellow] No Ghidra project. Run: [cyan]melee-agent ghidra setup[/cyan]")

    # Check DOL
    dol_path = _get_dol_path()
    if dol_path.exists():
        console.print(f"[green]✓[/green] DOL binary: {dol_path}")
    else:
        console.print(f"[yellow]![/yellow] DOL not found at: {dol_path}")


@ghidra_app.command("setup")
def ghidra_setup(
    project: Annotated[Path | None, typer.Option("--project", "-p", help="Path to existing Ghidra project (.gpr file)")] = None,
):
    """Link an existing Ghidra project for decompilation queries.

    The GameCube DOL loader has a bug that prevents headless import.
    You must import the DOL via Ghidra GUI first, then link the project here.

    Steps:
        1. Open Ghidra GUI
        2. File → New Project → Non-Shared Project
        3. Set location to: .ghidra_project/ in repo root
        4. Set name to: melee
        5. File → Import File → select orig/GALE01/sys/main.dol
        6. Let analysis complete (takes several minutes)
        7. Close Ghidra
        8. Run: melee-agent ghidra setup

    Or link an existing project:
        melee-agent ghidra setup --project /path/to/project.gpr
    """
    project_path = _get_project_path()

    if project:
        # Link to existing project
        if not project.exists():
            console.print(f"[red]Project not found:[/red] {project}")
            raise typer.Exit(1)

        # Copy or symlink the project
        import shutil
        if project_path.exists():
            shutil.rmtree(project_path)
        project_path.mkdir(parents=True, exist_ok=True)

        # The .gpr file and .rep directory should be siblings
        gpr_file = project if project.suffix == ".gpr" else None
        if gpr_file:
            proj_name = gpr_file.stem
            proj_dir = gpr_file.parent
            rep_dir = proj_dir / f"{proj_name}.rep"

            if rep_dir.exists():
                # Symlink both
                (project_path / gpr_file.name).symlink_to(gpr_file)
                (project_path / rep_dir.name).symlink_to(rep_dir)
                console.print(f"[green]✓[/green] Linked project: {gpr_file}")
            else:
                console.print(f"[red]Project .rep directory not found:[/red] {rep_dir}")
                raise typer.Exit(1)
        return

    # Check for expected project location
    expected_gpr = project_path / "melee.gpr"
    if expected_gpr.exists():
        console.print(f"[green]✓[/green] Project found: {expected_gpr}")
        console.print("[dim]Ready for decompilation queries[/dim]")
        return

    # Show setup instructions
    dol = _get_dol_path()
    console.print("[yellow]No Ghidra project found.[/yellow]")
    console.print("\n[bold]Manual Setup Required:[/bold]")
    console.print("""
The GameCube DOL loader cannot run in headless mode (GUI dialog bug).
You must import the DOL via Ghidra GUI first:

[cyan]1.[/cyan] Open Ghidra GUI:
   [dim]ghidra &[/dim]

[cyan]2.[/cyan] Create new project:
   File → New Project → Non-Shared Project
   Location: [green]{project_path}[/green]
   Name: [green]melee[/green]

[cyan]3.[/cyan] Import DOL:
   File → Import File
   Select: [green]{dol}[/green]
   Click OK on loader options

[cyan]4.[/cyan] Wait for analysis (5-10 minutes)

[cyan]5.[/cyan] Close Ghidra, then run:
   [green]melee-agent ghidra setup[/green]
""".format(project_path=project_path, dol=dol))


@ghidra_app.command("decompile")
def ghidra_decompile(
    address: Annotated[str, typer.Argument(help="Function address (e.g., 0x80243A3C or 80243A3C)")],
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw C without formatting")] = False,
):
    """Decompile a function using Ghidra's decompiler.

    Provides an alternative view to m2c. Useful for:
    - Getting a second opinion on complex control flow
    - Seeing Ghidra's type inference
    - Understanding high-level structure

    Examples:
        melee-agent ghidra decompile 0x80243A3C
        melee-agent ghidra decompile 80243A3C --raw
    """
    if not _init_ghidra():
        raise typer.Exit(1)

    # Normalize address
    addr_str = address.lower().replace("0x", "")
    try:
        addr_int = int(addr_str, 16)
    except ValueError:
        console.print(f"[red]Invalid address:[/red] {address}")
        raise typer.Exit(1)

    import pyghidra

    project_path = _get_project_path()
    if not project_path.exists():
        console.print("[red]No Ghidra project. Run:[/red] melee-agent ghidra setup")
        raise typer.Exit(1)

    try:
        import pyghidra
        from ghidra.util.task import TaskMonitor
        from ghidra.app.decompiler import DecompInterface

        with pyghidra.open_project(str(project_path), "melee") as project:
            # Get the program
            project_data = project.getProjectData()
            root_folder = project_data.getRootFolder()
            files = list(root_folder.getFiles())

            if not files:
                console.print("[red]No programs in project[/red]")
                raise typer.Exit(1)

            domain_file = files[0]
            program = domain_file.getDomainObject(project, False, False, TaskMonitor.DUMMY)

            try:
                # Get address and function
                addr_factory = program.getAddressFactory()
                addr = addr_factory.getAddress(f"0x{addr_int:08x}")

                func_mgr = program.getFunctionManager()
                func = func_mgr.getFunctionContaining(addr)

                if not func:
                    console.print(f"[yellow]No function at 0x{addr_int:08X}[/yellow]")
                    console.print("[dim]Try running analysis or check the address[/dim]")
                    raise typer.Exit(1)

                # Decompile
                decomp = DecompInterface()
                decomp.openProgram(program)

                results = decomp.decompileFunction(func, 60, TaskMonitor.DUMMY)

                if not results.decompileCompleted():
                    console.print(f"[red]Decompilation failed:[/red] {results.getErrorMessage()}")
                    raise typer.Exit(1)

                decompiled = results.getDecompiledFunction()
                c_code = decompiled.getC()

                func_name = func.getName()
                func_addr = func.getEntryPoint()

                if raw:
                    print(c_code)
                else:
                    console.print(f"\n[bold cyan]{func_name}[/bold cyan] @ [dim]0x{func_addr}[/dim]\n")
                    syntax = Syntax(c_code, "c", theme="monokai", line_numbers=True)
                    console.print(syntax)

            finally:
                program.release(project)

    except Exception as e:
        console.print(f"[red]Decompilation error:[/red] {e}")
        raise typer.Exit(1)


@ghidra_app.command("xrefs")
def ghidra_xrefs(
    address: Annotated[str, typer.Argument(help="Address to find references to/from")],
    direction: Annotated[str, typer.Option("--dir", "-d", help="'to' (callers) or 'from' (callees)")] = "to",
):
    """Find cross-references to or from an address.

    Useful for understanding call graphs:
    - 'to': Find all functions that call this address (callers)
    - 'from': Find all functions called from this address (callees)

    Examples:
        melee-agent ghidra xrefs 0x80243A3C          # Who calls this?
        melee-agent ghidra xrefs 0x80243A3C --dir from  # What does this call?
    """
    if not _init_ghidra():
        raise typer.Exit(1)

    # Normalize address
    addr_str = address.lower().replace("0x", "")
    try:
        addr_int = int(addr_str, 16)
    except ValueError:
        console.print(f"[red]Invalid address:[/red] {address}")
        raise typer.Exit(1)

    if direction not in ("to", "from"):
        console.print(f"[red]Invalid direction:[/red] {direction} (use 'to' or 'from')")
        raise typer.Exit(1)

    import pyghidra

    project_path = _get_project_path()
    if not project_path.exists():
        console.print("[red]No Ghidra project. Run:[/red] melee-agent ghidra setup")
        raise typer.Exit(1)

    try:
        with pyghidra.open_project(str(project_path), "melee") as project:
            programs = list(project.getRootFolder().getFiles())
            if not programs:
                console.print("[red]No programs in project[/red]")
                raise typer.Exit(1)

            domain_file = programs[0]
            program = domain_file.getDomainObject()

            try:
                addr_factory = program.getAddressFactory()
                addr = addr_factory.getAddress(f"0x{addr_int:08x}")

                func_mgr = program.getFunctionManager()
                ref_mgr = program.getReferenceManager()

                func = func_mgr.getFunctionContaining(addr)
                func_name = func.getName() if func else f"0x{addr_int:08X}"

                table = Table(title=f"References {'to' if direction == 'to' else 'from'} {func_name}")
                table.add_column("Address", style="cyan")
                table.add_column("Function", style="yellow")
                table.add_column("Type", style="dim")

                if direction == "to":
                    # Find references TO this address
                    refs = ref_mgr.getReferencesTo(addr)
                    for ref in refs:
                        from_addr = ref.getFromAddress()
                        from_func = func_mgr.getFunctionContaining(from_addr)
                        from_name = from_func.getName() if from_func else "unknown"
                        ref_type = str(ref.getReferenceType())
                        table.add_row(f"0x{from_addr}", from_name, ref_type)
                else:
                    # Find references FROM this function
                    if func:
                        body = func.getBody()
                        addr_iter = body.getAddresses(True)
                        seen = set()
                        while addr_iter.hasNext():
                            cur_addr = addr_iter.next()
                            refs = ref_mgr.getReferencesFrom(cur_addr)
                            for ref in refs:
                                to_addr = ref.getToAddress()
                                to_func = func_mgr.getFunctionContaining(to_addr)
                                if to_func:
                                    to_name = to_func.getName()
                                    if to_name not in seen:
                                        seen.add(to_name)
                                        ref_type = str(ref.getReferenceType())
                                        table.add_row(f"0x{to_addr}", to_name, ref_type)

                console.print(table)

            finally:
                program.release(project)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@ghidra_app.command("strings")
def ghidra_strings(
    address: Annotated[str | None, typer.Argument(help="Function address to search in")] = None,
    pattern: Annotated[str | None, typer.Option("--pattern", "-p", help="Search for strings matching pattern")] = None,
):
    """Find string references in a function or search all strings.

    Examples:
        melee-agent ghidra strings 0x80243A3C  # Strings referenced by function
        melee-agent ghidra strings --pattern "error"  # Search all strings
    """
    if not _init_ghidra():
        raise typer.Exit(1)

    import pyghidra

    project_path = _get_project_path()
    if not project_path.exists():
        console.print("[red]No Ghidra project. Run:[/red] melee-agent ghidra setup")
        raise typer.Exit(1)

    try:
        with pyghidra.open_project(str(project_path), "melee") as project:
            programs = list(project.getRootFolder().getFiles())
            if not programs:
                console.print("[red]No programs in project[/red]")
                raise typer.Exit(1)

            domain_file = programs[0]
            program = domain_file.getDomainObject()

            try:
                addr_factory = program.getAddressFactory()
                func_mgr = program.getFunctionManager()
                ref_mgr = program.getReferenceManager()
                listing = program.getListing()

                if address:
                    # Find strings referenced by a specific function
                    addr_str = address.lower().replace("0x", "")
                    addr_int = int(addr_str, 16)
                    addr = addr_factory.getAddress(f"0x{addr_int:08x}")

                    func = func_mgr.getFunctionContaining(addr)
                    if not func:
                        console.print(f"[yellow]No function at 0x{addr_int:08X}[/yellow]")
                        raise typer.Exit(1)

                    table = Table(title=f"Strings in {func.getName()}")
                    table.add_column("Address", style="cyan")
                    table.add_column("String", style="green")

                    body = func.getBody()
                    addr_iter = body.getAddresses(True)
                    seen = set()

                    while addr_iter.hasNext():
                        cur_addr = addr_iter.next()
                        refs = ref_mgr.getReferencesFrom(cur_addr)
                        for ref in refs:
                            to_addr = ref.getToAddress()
                            data = listing.getDataAt(to_addr)
                            if data and data.hasStringValue():
                                str_val = str(data.getValue())
                                if str_val not in seen:
                                    seen.add(str_val)
                                    table.add_row(f"0x{to_addr}", str_val[:80])

                    console.print(table)

                elif pattern:
                    # Search all strings for pattern
                    import re
                    regex = re.compile(pattern, re.IGNORECASE)

                    table = Table(title=f"Strings matching '{pattern}'")
                    table.add_column("Address", style="cyan")
                    table.add_column("String", style="green")

                    # Iterate through defined strings
                    data_iter = listing.getDefinedData(True)
                    count = 0
                    max_results = 50

                    for data in data_iter:
                        if count >= max_results:
                            break
                        if data.hasStringValue():
                            str_val = str(data.getValue())
                            if regex.search(str_val):
                                table.add_row(f"0x{data.getAddress()}", str_val[:80])
                                count += 1

                    console.print(table)
                    if count >= max_results:
                        console.print(f"[dim]Showing first {max_results} results[/dim]")
                else:
                    console.print("[yellow]Specify an address or --pattern[/yellow]")

            finally:
                program.release(project)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@ghidra_app.command("func")
def ghidra_func(
    address: Annotated[str, typer.Argument(help="Address to get function info")],
):
    """Get function metadata from Ghidra.

    Shows function name, signature, calling convention, and basic stats.

    Examples:
        melee-agent ghidra func 0x80243A3C
    """
    if not _init_ghidra():
        raise typer.Exit(1)

    # Normalize address
    addr_str = address.lower().replace("0x", "")
    try:
        addr_int = int(addr_str, 16)
    except ValueError:
        console.print(f"[red]Invalid address:[/red] {address}")
        raise typer.Exit(1)

    import pyghidra

    project_path = _get_project_path()
    if not project_path.exists():
        console.print("[red]No Ghidra project. Run:[/red] melee-agent ghidra setup")
        raise typer.Exit(1)

    try:
        with pyghidra.open_project(str(project_path), "melee") as project:
            programs = list(project.getRootFolder().getFiles())
            if not programs:
                console.print("[red]No programs in project[/red]")
                raise typer.Exit(1)

            domain_file = programs[0]
            program = domain_file.getDomainObject()

            try:
                addr_factory = program.getAddressFactory()
                addr = addr_factory.getAddress(f"0x{addr_int:08x}")

                func_mgr = program.getFunctionManager()
                func = func_mgr.getFunctionContaining(addr)

                if not func:
                    console.print(f"[yellow]No function at 0x{addr_int:08X}[/yellow]")
                    raise typer.Exit(1)

                # Gather info
                name = func.getName()
                entry = func.getEntryPoint()
                sig = func.getSignature()
                calling_conv = func.getCallingConventionName()
                body = func.getBody()
                size = body.getNumAddresses()

                # Parameter info
                params = func.getParameters()
                param_info = []
                for p in params:
                    param_info.append(f"{p.getDataType().getName()} {p.getName()}")

                ret_type = func.getReturnType()

                console.print(f"\n[bold cyan]{name}[/bold cyan]")
                console.print(f"  Entry: [yellow]0x{entry}[/yellow]")
                console.print(f"  Size: {size} bytes")
                console.print(f"  Calling convention: {calling_conv}")
                console.print(f"  Return type: [green]{ret_type.getName()}[/green]")

                if param_info:
                    console.print(f"  Parameters:")
                    for p in param_info:
                        console.print(f"    - [cyan]{p}[/cyan]")
                else:
                    console.print("  Parameters: (none)")

                console.print(f"\n  Signature: [green]{sig}[/green]")

            finally:
                program.release(project)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
