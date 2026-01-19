"""
CLI interface for the Melee Decomp Agent tooling.

This package provides a modular CLI structure with separate modules for each
command group: extract, scratch, commit, docker, sync, pr, audit, hook, struct,
stub, state, analytics, setup, and mismatch.

Usage:
    python -m src.cli <command>
    melee-agent <command>
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (gitignored, contains local config like DECOMP_API_BASE)
load_dotenv(Path(__file__).parent.parent.parent / ".env")

import typer

from ..mismatch_db.cli import mismatch_app

# Import common utilities for backward compatibility
from ._common import (
    DEFAULT_MELEE_ROOT,
    console,
)
from .analytics import analytics_app
from .audit import audit_app
from .commit import commit_app
from .compilers import list_compilers
from .docker import docker_app

# Import sub-apps from modules
from .extract import extract_app
from .hook import hook_app
from .pr import pr_app
from .scratch import scratch_app
from .setup import setup_app
from .state import state_app
from .struct import struct_app
from .stub import stub_app
from .sync import sync_app

# Create main app
app = typer.Typer(
    name="melee-agent",
    help="Agent tooling for contributing to the Melee decompilation project",
)

# Register sub-apps
app.add_typer(extract_app, name="extract")
app.add_typer(scratch_app, name="scratch")
app.add_typer(commit_app, name="commit")
app.add_typer(docker_app, name="docker")
app.add_typer(sync_app, name="sync")
app.add_typer(pr_app, name="pr")
app.add_typer(audit_app, name="audit")
app.add_typer(hook_app, name="hook")
app.add_typer(struct_app, name="struct")
app.add_typer(stub_app, name="stub")
app.add_typer(state_app, name="state")
app.add_typer(analytics_app, name="analytics")
app.add_typer(setup_app, name="setup")
app.add_typer(mismatch_app, name="mismatch")

# Register standalone commands
app.command("compilers")(list_compilers)


def main():
    """Entry point for the CLI."""
    if os.environ.get("CLAUDE_CODE_REMOTE", "").lower() == "true":
        console.print(
            "[yellow]Warning:[/yellow] melee-agent commands are not supported in remote environments.\n"
            "The decomp.me server and related services are only accessible from local machines.",
            style="yellow",
        )
        raise SystemExit(1)
    app()


if __name__ == "__main__":
    main()
