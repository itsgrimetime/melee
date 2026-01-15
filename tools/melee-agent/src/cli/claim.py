"""Claim commands - manage function claims for parallel agents."""

import json
import os
import time
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.table import Table

from ._common import (
    AGENT_ID,
    console,
    db_add_claim,
    db_release_claim,
    DEFAULT_MELEE_ROOT,
)
from .utils import file_lock, load_json_with_expiry


def _lookup_source_file(function_name: str) -> str | None:
    """Look up the source file for a function from the extractor.

    This allows auto-detection of the source file without requiring
    the --source-file flag.

    Args:
        function_name: Name of the function to look up

    Returns:
        Source file path (e.g., "melee/lb/lbcollision.c") or None if not found.
    """
    try:
        from src.extractor import FunctionExtractor
        extractor = FunctionExtractor(DEFAULT_MELEE_ROOT)
        func_info = extractor.extract_function(function_name)
        if func_info and func_info.file_path:
            return func_info.file_path
    except Exception:
        pass  # Silently fail - auto-detection is optional
    return None

# Claims are SHARED and ephemeral (3-hour expiry) - ok in /tmp
DECOMP_CLAIMS_FILE = os.environ.get("DECOMP_CLAIMS_FILE", "/tmp/decomp_claims.json")
DECOMP_CLAIM_TIMEOUT = int(os.environ.get("DECOMP_CLAIM_TIMEOUT", "10800"))  # 3 hours


claim_app = typer.Typer(help="Manage function claims for parallel agents")


def _load_claims() -> dict[str, Any]:
    """Load claims from file, removing stale entries."""
    return load_json_with_expiry(
        Path(DECOMP_CLAIMS_FILE),
        timeout_seconds=DECOMP_CLAIM_TIMEOUT,
        timestamp_field="timestamp",
    )


def _save_claims(claims: dict[str, Any]) -> None:
    """Save claims to file.

    Note: Caller must already hold the lock on the claims file.
    This function writes directly without acquiring a lock to avoid deadlock.
    """
    path = Path(DECOMP_CLAIMS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(claims, f, indent=2)


@claim_app.command("add")
def claim_add(
    function_name: Annotated[str, typer.Argument(help="Function name to claim")],
    agent_id: Annotated[
        str, typer.Option("--agent-id", help="Agent identifier")
    ] = AGENT_ID,
    source_file: Annotated[
        str | None, typer.Option("--source-file", "-f", "--source", help="Source file path (for tracking)")
    ] = None,
    output_json: Annotated[
        bool, typer.Option("--json", help="Output as JSON")
    ] = False,
):
    """Claim a function to prevent other agents from working on it."""
    # Auto-detect source file if not provided
    if not source_file:
        source_file = _lookup_source_file(function_name)
        if source_file and not output_json:
            console.print(f"[dim]Auto-detected source file: {source_file}[/dim]")

    claims_path = Path(DECOMP_CLAIMS_FILE)
    lock_path = claims_path.with_suffix(".json.lock")

    try:
        with file_lock(lock_path, exclusive=True):
            claims = _load_claims()

            if function_name in claims:
                existing = claims[function_name]
                existing_agent = existing.get("agent_id", "unknown")
                age_mins = (time.time() - existing["timestamp"]) / 60
                is_self = existing_agent == agent_id
                if output_json:
                    print(json.dumps({"success": False, "error": "already_claimed", "by": existing_agent, "age_mins": age_mins, "is_self": is_self}))
                else:
                    if is_self:
                        console.print(f"[yellow]Already claimed by you ({agent_id}) {age_mins:.0f}m ago - claim still active[/yellow]")
                    else:
                        console.print(f"[red]CLAIMED BY ANOTHER AGENT: {existing_agent} ({age_mins:.0f}m ago)[/red]")
                        console.print(f"[red]DO NOT WORK ON THIS FUNCTION - pick a different one[/red]")
                raise typer.Exit(1)

            claims[function_name] = {
                "agent_id": agent_id,
                "timestamp": time.time(),
                "source_file": source_file,
            }
            _save_claims(claims)

            # Also write to state database (non-blocking)
            db_add_claim(function_name, agent_id)

            if output_json:
                result = {"success": True, "function": function_name}
                if source_file:
                    result["source_file"] = source_file
                print(json.dumps(result))
            else:
                console.print(f"[green]Claimed:[/green] {function_name}")
                if source_file:
                    console.print(f"[dim]Source file:[/dim] {source_file}")
    except TimeoutError as e:
        if output_json:
            print(json.dumps({"success": False, "error": "lock_timeout", "message": str(e)}))
        else:
            console.print(f"[red]Lock timeout: {e}[/red]")
            console.print("[yellow]Try again in a few seconds, or check for stuck processes.[/yellow]")
        raise typer.Exit(1)


def _release_claim(function_name: str) -> bool:
    """Internal function to release a claim.

    Args:
        function_name: Function to release

    Returns:
        True if claim was released, False if not claimed
    """
    claims_path = Path(DECOMP_CLAIMS_FILE)
    if not claims_path.exists():
        # Also release from DB even if JSON doesn't exist
        db_release_claim(function_name)
        return False

    lock_path = claims_path.with_suffix(".json.lock")

    with file_lock(lock_path, exclusive=True):
        claims = _load_claims()

        if function_name not in claims:
            # Also release from DB even if not in JSON
            db_release_claim(function_name)
            return False

        del claims[function_name]
        _save_claims(claims)

        # Also release from state database (non-blocking)
        db_release_claim(function_name)

        return True


@claim_app.command("release")
def claim_release(
    function_name: Annotated[str, typer.Argument(help="Function name to release")],
    output_json: Annotated[
        bool, typer.Option("--json", help="Output as JSON")
    ] = False,
):
    """Release a claimed function."""
    try:
        released = _release_claim(function_name)
    except TimeoutError as e:
        if output_json:
            print(json.dumps({"success": False, "error": "lock_timeout", "message": str(e)}))
        else:
            console.print(f"[red]Lock timeout: {e}[/red]")
            console.print("[yellow]Try again in a few seconds, or check for stuck processes.[/yellow]")
        raise typer.Exit(1)

    if not released:
        if output_json:
            print(json.dumps({"success": False, "error": "not_claimed"}))
        else:
            console.print(f"[yellow]Function was not claimed[/yellow]")
        return

    if output_json:
        print(json.dumps({"success": True, "function": function_name}))
    else:
        console.print(f"[green]Released:[/green] {function_name}")


@claim_app.command("list")
def claim_list(
    output_json: Annotated[
        bool, typer.Option("--json", help="Output as JSON")
    ] = False,
):
    """List all currently claimed functions."""
    claims = _load_claims()

    if output_json:
        print(json.dumps(claims, indent=2))
    else:
        if not claims:
            console.print("[dim]No functions currently claimed[/dim]")
            return

        table = Table(title="Claimed Functions")
        table.add_column("Function", style="cyan")
        table.add_column("Agent")
        table.add_column("Age", justify="right")
        table.add_column("Remaining", justify="right")

        now = time.time()
        for name, info in sorted(claims.items()):
            age_mins = (now - info["timestamp"]) / 60
            remaining_mins = (DECOMP_CLAIM_TIMEOUT / 60) - age_mins
            table.add_row(
                name,
                info.get("agent_id", "?"),
                f"{age_mins:.0f}m",
                f"{remaining_mins:.0f}m"
            )

        console.print(table)
