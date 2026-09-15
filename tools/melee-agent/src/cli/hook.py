"""Hook commands - Git hook management and commit validation."""

import stat
from pathlib import Path
from typing import Annotated

import typer

from ._common import DEFAULT_MELEE_ROOT, console

hook_app = typer.Typer(help="Git hook management and commit validation")


@hook_app.command("validate")
def hook_validate(
    fix: Annotated[bool, typer.Option("--fix", help="Attempt to fix issues automatically")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show all warnings")] = False,
    skip_regressions: Annotated[
        bool, typer.Option("--skip-regressions", help="Skip build and regression check (faster)")
    ] = False,
):
    """Validate staged changes against project guidelines.

    All checks are ERRORS that block commits (based on doldecomp/melee PR feedback):

    Code Style:
    - TRUE/FALSE instead of true/false (lowercase required)
    - Float literals missing F suffix (1.0 should be 1.0F)
    - Lowercase hex literals (0xabc should be 0xABC)
    - clang-format would make changes

    Type/Struct Issues:
    - Raw pointer arithmetic for struct access (use M2C_FIELD)

    Symbol Issues:
    - New extern declarations (include proper headers instead)
    - Descriptive symbol renamed to address-based name
    - New functions need symbols.txt update

    Build Issues:
    - Implicit function declarations (uses clang)
    - Header signatures don't match implementations
    - Merge conflict markers in code
    - Match regressions (runs ninja by default)

    File Issues:
    - Forbidden files modified (.gitkeep files, orig/ placeholders)

    PR/Commit Issues:
    - Local scratch URLs in commits (must use production decomp.me URLs)
    """
    from src.hooks.validate_commit import CommitValidator

    validator = CommitValidator(melee_root=DEFAULT_MELEE_ROOT)
    errors, warnings, _check_results = validator.run(skip_regressions=skip_regressions)

    if warnings and verbose:
        console.print("\n[yellow]Warnings:[/yellow]")
        for w in warnings:
            console.print(f"  ⚠ {w}")

    if errors:
        console.print("\n[red]Errors (must fix before commit):[/red]")
        for e in errors:
            console.print(f"  ✗ {e}")

        if fix:
            console.print("\n[cyan]Attempting fixes...[/cyan]")
            console.print("  Auto-fix not yet implemented")

        console.print(f"\n[red]Validation failed: {len(errors)} error(s)[/red]")
        raise typer.Exit(1)

    if warnings:
        console.print(f"\n[yellow]{len(warnings)} warning(s)[/yellow]")
        if not verbose:
            console.print("  [dim]Run with --verbose to see details[/dim]")

    console.print("\n[green]✓ Validation passed[/green]")


@hook_app.command("install")
def hook_install(
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing hooks")] = False,
):
    """Install git pre-commit hooks for validation.

    Installs a pre-commit hook that runs validation on staged changes.
    """
    # Use the melee repo root (melee-agent is a subdirectory, not a separate repo)
    project_root = DEFAULT_MELEE_ROOT
    melee_agent_dir = project_root / "tools" / "melee-agent"

    hooks_dir = project_root / ".git" / "hooks"
    pre_commit = hooks_dir / "pre-commit"

    hook_content = f'''#!/bin/sh
# Pre-commit hook for melee decompilation
# Installed by: melee-agent hook install

# Capture the worktree root before changing directories
WORKTREE_ROOT="$(git rev-parse --show-toplevel)"

cd "{melee_agent_dir}"

# Run validation with a 5-minute timeout
python -m src.hooks.validate_commit --worktree "$WORKTREE_ROOT" --timeout 300

EXIT_CODE=$?

# Clean up any stray ninja processes on timeout (exit code 124)
if [ $EXIT_CODE -eq 124 ]; then
    pkill -f "ninja.*GALE01" 2>/dev/null || true
fi

exit $EXIT_CODE
'''

    if pre_commit.exists() and not force:
        console.print(f"[yellow]Pre-commit hook already exists at {pre_commit}[/yellow]")
        console.print("[dim]Use --force to overwrite[/dim]")
        raise typer.Exit(1)

    pre_commit.write_text(hook_content)
    pre_commit.chmod(pre_commit.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    console.print(f"[green]✓ Installed pre-commit hook at {pre_commit}[/green]")


@hook_app.command("uninstall")
def hook_uninstall():
    """Remove git pre-commit hooks installed by melee-agent."""
    project_root = DEFAULT_MELEE_ROOT

    pre_commit = project_root / ".git" / "hooks" / "pre-commit"
    if pre_commit.exists():
        content = pre_commit.read_text()
        if "melee-agent" in content or "validate_commit" in content:
            pre_commit.unlink()
            console.print("[green]✓ Removed pre-commit hook[/green]")
        else:
            console.print("[yellow]Pre-commit hook exists but wasn't installed by melee-agent[/yellow]")
    else:
        console.print("[yellow]No pre-commit hook found[/yellow]")
