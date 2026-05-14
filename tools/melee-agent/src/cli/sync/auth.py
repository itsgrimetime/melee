"""Auth-related sync commands: auth, status, clear."""

from typing import Annotated, Optional

import typer

from .._common import (
    PRODUCTION_COOKIES_FILE,
    PRODUCTION_DECOMP_ME,
    console,
)
from ._helpers import load_production_cookies, save_production_cookies


def _prompt_cf_clearance() -> tuple[str, str]:
    """Prompt user for cf_clearance cookie and User-Agent.

    Returns:
        Tuple of (cf_clearance, user_agent)
    """
    console.print("\n[bold cyan]Cloudflare Authentication Required[/bold cyan]")
    console.print("The production decomp.me site requires a cf_clearance cookie.")
    console.print("\n[bold]To get this cookie:[/bold]")
    console.print("1. Open https://decomp.me in your browser")
    console.print("2. Complete the Cloudflare challenge if prompted")
    console.print("3. Open DevTools (F12) -> Application -> Cookies -> decomp.me")
    console.print("4. Copy the value of 'cf_clearance'")
    console.print("\n[bold yellow]Important:[/bold yellow] You will also need your browser's User-Agent.")
    console.print("To get it: Open DevTools -> Console -> type: navigator.userAgent\n")

    cf_clearance = typer.prompt("Enter cf_clearance cookie value")
    user_agent = typer.prompt(
        "Enter your browser's User-Agent",
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0",
    )
    return cf_clearance.strip(), user_agent.strip()


DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0"


def get_production_user_agent() -> str:
    """Get the stored User-Agent for production requests, or the default."""
    cookies = load_production_cookies()
    return cookies.get("user_agent", DEFAULT_USER_AGENT)


def status_command():
    """Check cf_clearance cookie status and test connection to production."""
    cookies = load_production_cookies()

    if not cookies.get("cf_clearance"):
        console.print("[yellow]No cf_clearance cookie cached[/yellow]")
        console.print("[dim]Run 'melee-agent sync auth' to configure[/dim]")
        return

    console.print("[green]cf_clearance cookie cached[/green]")
    console.print(f"[dim]Cookie file: {PRODUCTION_COOKIES_FILE}[/dim]")

    user_agent = cookies.get("user_agent", DEFAULT_USER_AGENT)
    if "user_agent" not in cookies:
        console.print("[yellow]No User-Agent stored - using default (may not work)[/yellow]")
        console.print("[dim]Run 'melee-agent sync auth' again to set User-Agent[/dim]")

    console.print("\n[dim]Testing connection to production...[/dim]")
    import httpx

    try:
        with httpx.Client(
            cookies={"cf_clearance": cookies["cf_clearance"]},
            headers={
                "User-Agent": user_agent,
            },
            follow_redirects=True,
            timeout=10.0,
        ) as client:
            resp = client.get(f"{PRODUCTION_DECOMP_ME}/api/compiler")
            if resp.status_code == 200:
                console.print("[green]Successfully connected to production decomp.me[/green]")
            elif resp.status_code == 403:
                console.print("[red]cf_clearance cookie expired or invalid[/red]")
                console.print("[dim]Run 'melee-agent sync auth' to refresh[/dim]")
            else:
                console.print(f"[yellow]Unexpected response: {resp.status_code}[/yellow]")
    except Exception as e:
        console.print(f"[red]Connection failed: {e}[/red]")


def auth_command(
    cf_clearance: Annotated[str | None, typer.Option("--cf-clearance", help="cf_clearance cookie value")] = None,
    user_agent: Annotated[str | None, typer.Option("--user-agent", help="Browser User-Agent (must match browser used to get cf_clearance)")] = None,
    session_id: Annotated[
        str | None, typer.Option("--session-id", help="sessionid cookie for authenticated uploads")
    ] = None,
):
    """Configure authentication for production decomp.me."""
    cookies = load_production_cookies()

    if cf_clearance:
        cookies["cf_clearance"] = cf_clearance.strip()
        if user_agent:
            cookies["user_agent"] = user_agent.strip()
        elif not cookies.get("user_agent"):
            console.print("[yellow]Warning: No User-Agent provided. cf_clearance may not work.[/yellow]")
            console.print("[dim]Use --user-agent to specify, or run without --cf-clearance to use interactive mode[/dim]")
    else:
        cf_val, ua_val = _prompt_cf_clearance()
        cookies["cf_clearance"] = cf_val
        cookies["user_agent"] = ua_val

    if session_id:
        cookies["sessionid"] = session_id.strip()
    elif not cookies.get("sessionid"):
        if typer.confirm("Do you want to add a sessionid cookie? (allows uploads under your account)"):
            console.print("\n[bold]To get your sessionid:[/bold]")
            console.print("1. Log into https://decomp.me with GitHub")
            console.print("2. Open DevTools -> Application -> Cookies -> decomp.me")
            console.print("3. Copy the value of 'sessionid'\n")
            cookies["sessionid"] = typer.prompt("Enter sessionid cookie value").strip()

    save_production_cookies(cookies)
    console.print(f"\n[green]Cookies saved to {PRODUCTION_COOKIES_FILE}[/green]")
    status_command()


def clear_command():
    """Clear cached production cookies."""
    if PRODUCTION_COOKIES_FILE.exists():
        PRODUCTION_COOKIES_FILE.unlink()
        console.print("[green]Cleared cached cookies[/green]")
    else:
        console.print("[yellow]No cached cookies to clear[/yellow]")
