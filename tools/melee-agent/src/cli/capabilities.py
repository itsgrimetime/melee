"""melee-agent capabilities — a discoverable, queryable index of existing CLI
commands and skills, so agents stop rebuilding tools that already exist.

`search` and `show` introspect the LIVE Typer tree (never stale); `generate`
writes the auto-loaded brief and the full inventory doc.
"""
from __future__ import annotations

import typer

capabilities_app = typer.Typer(
    help="Discover existing CLI commands and skills before building new ones.",
    no_args_is_help=True,
)


@capabilities_app.command("search")
def search(task: str = typer.Argument(..., help="What you are trying to do.")) -> None:
    """Find existing commands/skills matching a task description."""
    typer.echo(f"(not yet implemented) search: {task}")


@capabilities_app.command("show")
def show(group: str = typer.Argument(None, help="Command group or skill to detail.")) -> None:
    """Show full detail for a group (or everything)."""
    typer.echo("(not yet implemented) show")


@capabilities_app.command("generate")
def generate() -> None:
    """Regenerate the capability brief and full inventory doc."""
    typer.echo("(not yet implemented) generate")
