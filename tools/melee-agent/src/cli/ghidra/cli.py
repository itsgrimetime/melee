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

from .._common import console, DECOMP_CONFIG_DIR, get_agent_melee_root, get_base_dol_path
from .cache import CACHE_DB_PATH, build_from_project
from .detect import detect_ghidra_install
from .project import ghidra_project_dir, GHIDRA_PROJECT_NAME, is_project_populated

ghidra_app = typer.Typer(help="Ghidra decompilation tools (alternative to m2c)")

# Lazy-load pyghidra to avoid import errors when not installed
_ghidra_initialized = False
_flat_api = None
_program = None


def _check_ghidra_prereqs() -> tuple[bool, str]:
    """Check if Ghidra prerequisites are met."""
    install = detect_ghidra_install()
    if install is None:
        env_val = os.environ.get("GHIDRA_INSTALL_DIR")
        if env_val:
            return False, (
                f"GHIDRA_INSTALL_DIR={env_val} is not a valid Ghidra install "
                f"(no application.properties). Unset it or point at the libexec dir."
            )
        return False, (
            "Ghidra not found. Install via 'brew install ghidra' or set "
            "GHIDRA_INSTALL_DIR to the directory containing application.properties."
        )

    # Ensure pyghidra finds the install via env var
    os.environ["GHIDRA_INSTALL_DIR"] = str(install)

    try:
        import pyghidra  # noqa: F401
        return True, f"Ghidra: {install}"
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
    """Get the canonical Ghidra project directory."""
    return ghidra_project_dir()


def _get_dol_path() -> Path:
    """Resolve the DOL binary.

    Prefers the central config location (~/.config/decomp-me/orig/...),
    then falls back to the canonical melee repo root's orig/ tree.
    Worktrees usually do NOT have orig/ populated (gitignored).
    """
    central = get_base_dol_path()
    if central is not None:
        return central

    melee_root = get_agent_melee_root()
    for candidate in (
        melee_root / "orig" / "GALE01" / "sys" / "main.dol",
        melee_root / "baserom.dol",
        melee_root / "build" / "GALE01" / "main.dol",
    ):
        if candidate.exists():
            return candidate

    # Return first candidate so the error message points somewhere useful
    return melee_root / "orig" / "GALE01" / "sys" / "main.dol"


@ghidra_app.command("status")
def ghidra_status():
    """Check Ghidra installation, project, and DOL availability."""
    rows: list[tuple[str, str, str]] = []  # (state, label, detail)

    # Install
    install = detect_ghidra_install()
    if install is not None:
        rows.append(("ok", "Ghidra install", str(install)))
        os.environ["GHIDRA_INSTALL_DIR"] = str(install)
    else:
        rows.append((
            "fail", "Ghidra install",
            "not found — install with 'brew install ghidra' or download from ghidra-sre.org"
        ))

    # pyghidra
    try:
        import pyghidra
        rows.append(("ok", "pyghidra", getattr(pyghidra, "__version__", "installed")))
    except ImportError:
        rows.append(("fail", "pyghidra", "not installed — run 'pip install pyghidra'"))

    # DOL
    dol = _get_dol_path()
    if dol.exists():
        rows.append(("ok", "DOL binary", str(dol)))
    else:
        rows.append(("fail", "DOL binary", f"not found at {dol}"))

    # Project
    project_path = _get_project_path()
    gpr = project_path / f"{GHIDRA_PROJECT_NAME}.gpr"
    if gpr.exists():
        if is_project_populated(project_path):
            rows.append(("ok", "Ghidra project", f"{project_path} (populated)"))
        else:
            rows.append((
                "warn", "Ghidra project",
                f"{project_path} (empty — DOL not imported; run 'melee-agent ghidra setup')"
            ))
    else:
        rows.append((
            "warn", "Ghidra project",
            f"missing at {project_path} — run 'melee-agent ghidra setup'"
        ))

    # Cache (will be populated in Phase 2)
    cache_db = DECOMP_CONFIG_DIR / "ghidra.db"
    if cache_db.exists():
        size_mb = cache_db.stat().st_size / 1024 / 1024
        rows.append(("ok", "Cache DB", f"{cache_db} ({size_mb:.1f} MB)"))
    else:
        rows.append((
            "warn", "Cache DB",
            "not built — run 'melee-agent ghidra cache-build' for fast xrefs/strings"
        ))

    for state, label, detail in rows:
        icon = {"ok": "[green]✓[/green]", "warn": "[yellow]![/yellow]", "fail": "[red]✗[/red]"}[state]
        console.print(f"{icon} [bold]{label}[/bold]: {detail}")


@ghidra_app.command("setup")
def ghidra_setup():
    """Guide one-time Ghidra project creation (manual GUI import).

    The GameCubeLoader has a headless-mode bug (DOLProgramBuilder pops an
    OptionDialog) so the initial DOL import must happen via the Ghidra GUI.
    This command:
      1. Ensures the project directory exists
      2. Prints exact GUI steps to follow
      3. Validates the result
    """
    install = detect_ghidra_install()
    if install is None:
        console.print("[red]Ghidra install not found.[/red] Run 'brew install ghidra' first.")
        raise typer.Exit(1)

    dol = _get_dol_path()
    if not dol.exists():
        console.print(f"[red]DOL not found at {dol}.[/red]")
        console.print("Place the GALE01 main.dol at ~/.config/decomp-me/orig/GALE01/main.dol")
        raise typer.Exit(1)

    project_path = _get_project_path()
    project_path.mkdir(parents=True, exist_ok=True)

    expected_gpr = project_path / f"{GHIDRA_PROJECT_NAME}.gpr"

    if expected_gpr.exists() and is_project_populated(project_path):
        console.print(f"[green]✓[/green] Project already populated: {expected_gpr}")
        return

    ghidra_run = install.parent / "bin" / "ghidraRun"
    if not ghidra_run.exists():
        # Homebrew exposes ghidraRun at /opt/homebrew/bin/ghidraRun
        ghidra_run = Path("/opt/homebrew/bin/ghidraRun")

    console.print(Panel.fit(
        f"""[bold]One-time Ghidra setup required[/bold]

The GameCubeLoader has a headless-mode bug, so the initial DOL
import must be done via the Ghidra GUI.

[cyan]1.[/cyan] Launch Ghidra:
   [dim]{ghidra_run} &[/dim]

[cyan]2.[/cyan] Create the project:
   File → New Project → Non-Shared Project
   Location: [green]{project_path}[/green]
   Name:     [green]{GHIDRA_PROJECT_NAME}[/green]

[cyan]3.[/cyan] Import the DOL:
   File → Import File → [green]{dol}[/green]
   Loader: [green]Nintendo GameCube/Wii Binary[/green] (the GameCubeLoader extension)
   Click [green]OK[/green] on the loader options dialog.

[cyan]4.[/cyan] Wait for analysis to complete (5-10 minutes).

[cyan]5.[/cyan] Close Ghidra, then re-run this command to validate:
   [green]melee-agent ghidra setup[/green]
""",
        title="Manual Step Required",
    ))


@ghidra_app.command("cache-build")
def ghidra_cache_build(
    force: bool = typer.Option(False, "--force", "-f", help="Rebuild even if cache exists"),
):
    """Build the SQLite cache from the Ghidra project (one-time, ~minutes).

    Agents then query xrefs/strings/func against the cache without
    starting Ghidra each time.
    """
    if CACHE_DB_PATH.exists() and not force:
        console.print(
            f"[yellow]Cache already exists at {CACHE_DB_PATH}.[/yellow] "
            f"Use --force to rebuild."
        )
        raise typer.Exit(0)

    if not _init_ghidra():
        raise typer.Exit(1)

    project_path = _get_project_path()
    if not is_project_populated(project_path):
        console.print(
            f"[red]Project at {project_path} is not populated.[/red] "
            f"Run 'melee-agent ghidra setup' first."
        )
        raise typer.Exit(1)

    console.print(f"[dim]Building cache at {CACHE_DB_PATH} (this may take a few minutes)...[/dim]")
    counts = build_from_project(CACHE_DB_PATH, project_path, GHIDRA_PROJECT_NAME)
    console.print(
        f"[green]✓[/green] Cache built: "
        f"{counts['functions']} functions, "
        f"{counts['xrefs']} xrefs, "
        f"{counts['strings']} strings"
    )


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

        with pyghidra.open_project(str(project_path), GHIDRA_PROJECT_NAME) as project:
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
    """Find callers (--dir to) or callees (--dir from) via the cache.

    Examples:
        melee-agent ghidra xrefs 0x80243A3C            # who calls this
        melee-agent ghidra xrefs 0x80243A3C --dir from # what does this call
    """
    from .cache import CACHE_DB_PATH, get_callers, get_callees, get_function

    if not CACHE_DB_PATH.exists():
        console.print(
            "[red]Cache not built.[/red] Run [cyan]melee-agent ghidra cache-build[/cyan]."
        )
        raise typer.Exit(1)

    addr_str = address.lower().replace("0x", "")
    try:
        addr_int = int(addr_str, 16)
    except ValueError:
        console.print(f"[red]Invalid address:[/red] {address}")
        raise typer.Exit(1)

    if direction not in ("to", "from"):
        console.print(f"[red]Invalid direction:[/red] {direction} (use 'to' or 'from')")
        raise typer.Exit(1)

    func = get_function(CACHE_DB_PATH, addr_int)
    label = func["name"] if func else f"0x{addr_int:08X}"
    title = f"References {'to' if direction == 'to' else 'from'} {label}"

    table = Table(title=title)
    table.add_column("Address", style="cyan")
    table.add_column("Function", style="yellow")
    table.add_column("Type", style="dim")

    if direction == "to":
        for row in get_callers(CACHE_DB_PATH, addr_int):
            table.add_row(
                f"0x{row['from_addr']:08X}",
                row["from_function"],
                row["ref_type"],
            )
    else:
        if func is None:
            console.print(f"[yellow]No function at 0x{addr_int:08X}[/yellow]")
            raise typer.Exit(1)
        for row in get_callees(CACHE_DB_PATH, func["addr"]):
            table.add_row(
                f"0x{row['to_function_addr']:08X}",
                row["to_function"],
                row["ref_type"],
            )

    console.print(table)


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
        from ghidra.util.task import TaskMonitor

        with pyghidra.open_project(str(project_path), GHIDRA_PROJECT_NAME) as project:
            programs = list(project.getProjectData().getRootFolder().getFiles())
            if not programs:
                console.print("[red]No programs in project[/red]")
                raise typer.Exit(1)

            domain_file = programs[0]
            program = domain_file.getDomainObject(project, False, False, TaskMonitor.DUMMY)

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
        from ghidra.util.task import TaskMonitor

        with pyghidra.open_project(str(project_path), GHIDRA_PROJECT_NAME) as project:
            programs = list(project.getProjectData().getRootFolder().getFiles())
            if not programs:
                console.print("[red]No programs in project[/red]")
                raise typer.Exit(1)

            domain_file = programs[0]
            program = domain_file.getDomainObject(project, False, False, TaskMonitor.DUMMY)

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
