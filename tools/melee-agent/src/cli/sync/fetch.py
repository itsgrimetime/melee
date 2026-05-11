"""Fetch scratch from production decomp.me."""

import asyncio
from typing import Annotated

import typer

from .._common import (
    PRODUCTION_DECOMP_ME,
    console,
)
from ._helpers import load_production_cookies, rate_limited_request
from .auth import get_production_user_agent


def _extract_text(text_data) -> str:
    """Extract text from diff text data (can be string or list of spans)."""
    if isinstance(text_data, str):
        return text_data
    if isinstance(text_data, list):
        return "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in text_data)
    return str(text_data) if text_data else ""


def _format_diff_output(diff_output: dict, max_lines: int = 0) -> None:
    """Format and print the instruction diff from production API response."""
    rows = diff_output.get("rows", [])
    if not rows:
        console.print("[dim]No diff rows available[/dim]")
        return

    console.print("\n[bold]Instruction Diff:[/bold] (target | current)\n")

    diff_count = 0
    shown = 0

    for row in rows:
        base = row.get("base", {})
        current = row.get("current", {})

        base_text = ""
        curr_text = ""

        if base and "text" in base:
            base_text = _extract_text(base["text"])
        if current and "text" in current:
            curr_text = _extract_text(current["text"])

        # Truncate long lines
        base_display = base_text[:60].ljust(60) if base_text else " " * 60
        curr_display = curr_text[:60] if curr_text else ""

        # Check if there's a difference
        has_diff = base_text.strip() != curr_text.strip()
        if has_diff:
            diff_count += 1
            console.print(f"[red]{base_display}[/red] | [green]{curr_display}[/green]")
        else:
            console.print(f"[dim]{base_display} | {curr_display}[/dim]")

        shown += 1
        if max_lines and shown >= max_lines:
            remaining = len(rows) - shown
            if remaining > 0:
                console.print(f"[dim]... {remaining} more rows[/dim]")
            break

    console.print(f"\n[bold]Total differences:[/bold] {diff_count}")


def fetch_command(
    slug: Annotated[str, typer.Argument(help="Scratch slug to fetch (e.g., PSlZi)")],
    diff: Annotated[bool, typer.Option("--diff", "-d", help="Show the current diff")] = False,
    context: Annotated[bool, typer.Option("--context", "-c", help="Show the context")] = False,
    source: Annotated[bool, typer.Option("--source", "-s", help="Show the source code")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Fetch a scratch from production decomp.me.

    Requires cf_clearance cookie. Run 'melee-agent sync auth' first if not configured.

    Examples:
        melee-agent sync fetch PSlZi
        melee-agent sync fetch PSlZi --diff
        melee-agent sync fetch PSlZi --source --context
    """
    prod_cookies = load_production_cookies()
    if not prod_cookies.get("cf_clearance"):
        console.print("[red]No cf_clearance cookie configured[/red]")
        console.print("[dim]Run 'melee-agent sync auth' first[/dim]")
        raise typer.Exit(1)

    async def do_fetch():
        import httpx

        prod_cookies_obj = httpx.Cookies()
        prod_cookies_obj.set("cf_clearance", prod_cookies["cf_clearance"], domain="decomp.me")
        if prod_cookies.get("sessionid"):
            prod_cookies_obj.set("sessionid", prod_cookies["sessionid"], domain="decomp.me")

        async with httpx.AsyncClient(
            base_url=PRODUCTION_DECOMP_ME,
            timeout=60.0,
            cookies=prod_cookies_obj,
            headers={
                "User-Agent": get_production_user_agent(),
                "Accept": "application/json",
            },
            follow_redirects=True,
        ) as client:
            # Fetch scratch data
            console.print(f"[dim]Fetching scratch {slug} from production...[/dim]")
            resp = await rate_limited_request(client, "get", f"/api/scratch/{slug}")

            if resp.status_code == 403:
                console.print("[red]403 Forbidden - cf_clearance may have expired[/red]")
                console.print("[dim]Run 'melee-agent sync auth' to refresh[/dim]")
                raise typer.Exit(1)
            elif resp.status_code == 404:
                console.print(f"[red]Scratch {slug} not found[/red]")
                raise typer.Exit(1)
            elif resp.status_code != 200:
                console.print(f"[red]Failed to fetch scratch: {resp.status_code}[/red]")
                console.print(f"[dim]{resp.text[:500]}[/dim]")
                raise typer.Exit(1)

            data = resp.json()

            if json_output:
                import json
                console.print(json.dumps(data, indent=2))
                return data

            # Display scratch info
            name = data.get("name", "Unknown")
            score = data.get("score", -1)
            max_score = data.get("max_score", -1)
            compiler = data.get("compiler", "Unknown")
            platform = data.get("platform", "Unknown")
            owner = data.get("owner")
            owner_name = owner.get("username", "anonymous") if owner else "anonymous"

            if max_score > 0:
                match_pct = (1 - score / max_score) * 100
                match_str = f"{match_pct:.1f}%"
            else:
                match_str = "N/A"

            console.print(f"\n[bold cyan]{name}[/bold cyan]")
            console.print(f"  URL: {PRODUCTION_DECOMP_ME}/scratch/{slug}")
            console.print(f"  Match: {match_str} (score={score}, max={max_score})")
            console.print(f"  Compiler: {compiler} ({platform})")
            console.print(f"  Owner: {owner_name}")

            source_code = data.get("source_code", "")
            context_code = data.get("context", "")

            console.print(f"  Source: {len(source_code):,} bytes")
            console.print(f"  Context: {len(context_code):,} bytes")

            # Show source if requested
            if source:
                console.print("\n[bold]Source Code:[/bold]")
                console.print(source_code)

            # Show context if requested
            if context:
                console.print("\n[bold]Context:[/bold]")
                # Truncate if very long
                if len(context_code) > 10000:
                    console.print(context_code[:10000])
                    console.print(f"\n[dim]... truncated ({len(context_code):,} bytes total)[/dim]")
                else:
                    console.print(context_code)

            # Compile and show diff if requested
            if diff:
                console.print("\n[dim]Compiling to get diff...[/dim]")
                compile_resp = await rate_limited_request(
                    client,
                    "post",
                    f"/api/scratch/{slug}/compile",
                    json={},
                )

                if compile_resp.status_code == 200:
                    compile_data = compile_resp.json()
                    diff_output = compile_data.get("diff_output")

                    if diff_output:
                        # Show updated score
                        current_score = diff_output.get("current_score", 0)
                        max_score_val = diff_output.get("max_score", 0)
                        if max_score_val > 0:
                            new_match_pct = (1 - current_score / max_score_val) * 100
                            console.print(f"[bold]Match: {new_match_pct:.1f}%[/bold] (score={current_score}/{max_score_val})")
                        _format_diff_output(diff_output, max_lines=50)
                    else:
                        console.print("[yellow]No diff output available[/yellow]")
                else:
                    console.print(f"[red]Compile failed: {compile_resp.status_code}[/red]")

            return data

    return asyncio.run(do_fetch())
