"""melee-agent capabilities — a discoverable, queryable index of existing CLI
commands and skills, so agents stop rebuilding tools that already exist.

`search` and `show` introspect the LIVE Typer tree (never stale); `generate`
writes the auto-loaded brief and the full inventory doc.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import typer


@dataclass
class Capability:
    kind: str                       # "command" | "skill"
    name: str                       # e.g. "debug target score-source" or "ghidra"
    summary: str                    # one-line description
    invoke: str                     # how to run it
    group: str = ""                 # top-level group for commands; "" for skills
    keywords: list[str] = field(default_factory=list)


# CRITICAL (verified): Typer sub-apps are lazily-populated TyperGroups — walking
# `.commands` directly yields only 3 leaves. Use the lazy-safe list_commands(ctx)
# + get_command(ctx, name) API (yields the real 215 leaves) and skip hidden cmds
# (the `issues` alias, `debug inspect ceiling`, etc.).
def _walk_click(cmd, ctx, prefix: str = ""):
    """Yield (full_name, click_command) for every VISIBLE leaf command."""
    import click

    try:
        names = cmd.list_commands(ctx)
    except Exception:
        names = list(getattr(cmd, "commands", {}).keys())
    for name in sorted(names):
        sub = cmd.get_command(ctx, name)
        if sub is None or getattr(sub, "hidden", False):
            continue
        full = f"{prefix}{name}"
        if isinstance(sub, click.Group):
            yield from _walk_click(sub, ctx, prefix=f"{full} ")
        else:
            yield full, sub


def _help_text(click_cmd) -> str:
    """short_help -> first line of help/docstring -> ''. Typer folds the command
    callback docstring into `.help`, so get_short_help_str covers the chain."""
    try:
        short = click_cmd.get_short_help_str(limit=100)
    except Exception:
        short = ""
    if short:
        return short.strip()
    if click_cmd.help:
        return click_cmd.help.strip().splitlines()[0].strip()
    return ""


def command_capabilities(root_app=None) -> list[Capability]:
    """Introspect the LIVE root Typer app into a flat list of command capabilities.
    `root_app` is injectable for tests; defaults to the real CLI app."""
    import typer.main
    import click

    if root_app is None:
        from src.cli import app as root_app  # lazy import avoids circular import

    root = typer.main.get_command(root_app)
    ctx = click.Context(root, info_name="melee-agent")
    caps: list[Capability] = []
    for full_name, cmd in _walk_click(root, ctx):
        group = full_name.split(" ", 1)[0]
        caps.append(
            Capability(
                kind="command",
                name=full_name,
                summary=_help_text(cmd),
                invoke=f"melee-agent {full_name}",
                group=group,
                keywords=full_name.replace("-", " ").split(),
            )
        )
    return caps

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
