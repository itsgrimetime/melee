"""melee-agent capabilities — a discoverable, queryable index of existing CLI
commands and skills, so agents stop rebuilding tools that already exist.

`search` and `show` introspect the LIVE Typer tree (never stale); `generate`
writes the auto-loaded brief and the full inventory doc.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

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
    except Exception as exc:
        import sys
        print(f"capabilities: list_commands failed ({exc}); falling back to .commands", file=sys.stderr)
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
        short = click_cmd.get_short_help_str(limit=200)
    except Exception:
        short = ""
    if short:
        return short.strip()
    if click_cmd.help:
        lines = click_cmd.help.strip().splitlines()
        return lines[0].strip() if lines else ""
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
                # keywords = command-path tokens only (search ranks help text separately)
                keywords=full_name.replace("-", " ").split(),
            )
        )
    return caps

def parse_skill(skill_md: Path) -> Capability:
    """Parse a SKILL.md into a Capability. Uses YAML frontmatter when present,
    else falls back to the H1 title and first prose paragraph (3 repo skills
    have no frontmatter)."""
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    dir_name = skill_md.parent.name
    name = dir_name
    desc = ""

    if text.lstrip().startswith("---"):
        body_start = text.find("---") + 3
        end = text.find("\n---", body_start)
        if end != -1:
            import yaml

            try:
                meta = yaml.safe_load(text[body_start:end]) or {}
            except yaml.YAMLError:
                meta = {}
            name = str(meta.get("name") or dir_name).strip() or dir_name
            desc = str(meta.get("description") or "").strip()

    if not desc:
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("---"):
                continue
            desc = s
            break

    return Capability(
        kind="skill",
        name=name,
        summary=desc,
        invoke=f"/{dir_name}",
        keywords=[dir_name] + dir_name.replace("-", " ").split(),
    )


def skill_capabilities(repo_root: Path) -> list[Capability]:
    skills_dir = repo_root / ".claude" / "skills"
    caps: list[Capability] = []
    if not skills_dir.is_dir():
        return caps
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        caps.append(parse_skill(skill_md))
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
