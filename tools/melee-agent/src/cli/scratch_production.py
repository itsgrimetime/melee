"""Production scratch creation from a worktree function.

Implements ``melee-agent scratch create <func> --production``: build a scratch
payload directly from the worktree (no local decomp.me server) and create it on
https://decomp.me using stored production credentials.
"""

import asyncio
from pathlib import Path

import httpx
import typer

from ._common import (
    PRODUCTION_DECOMP_ME,
    console,
    db_upsert_function,
    db_upsert_scratch,
    get_compiler_for_source,
)
from .sync._helpers import create_and_claim_production_scratch, load_production_cookies
from .sync.auth import get_production_user_agent

# Name of the decomp.me preset to label production scratches with.
MELEE_PRESET_NAME = "Super Smash Bros. Melee"

# decomp.me "Super Smash Bros. Melee" compiler flags, verified against real
# production preset-63 scratches. This is the preset's flags WITHOUT -DM2CTX:
# the decompctx.py context we send contains real (non-M2CTX) types, and -DM2CTX
# would flip the header `#if defined(__MWERKS__) && !defined(M2CTX)` branches to
# m2c stub types (UNK_T -> long) that the sibling function bodies in the context
# then fail to type-check against. (-fp hard == -fp hardware in mwcc.)
PRODUCTION_COMPILER_FLAGS = (
    "-O4,p -nodefaults -proc gekko -fp hard -Cpp_exceptions off -enum int -fp_contract on -inline auto"
)


def build_production_create_data(
    *,
    name: str,
    target_asm: str,
    context: str,
    source_code: str,
    compiler: str,
    flags: str = PRODUCTION_COMPILER_FLAGS,
    preset: int | None = None,
) -> dict:
    """Build the /api/scratch POST body for a production scratch (pure).

    When ``preset`` is given it labels the scratch with that decomp.me preset
    (e.g. the Melee preset) while still sending explicit ``compiler_flags`` so
    the preset's own ``-DM2CTX`` default does not override them.
    """
    data = {
        "name": name,
        "target_asm": target_asm,
        "context": context,
        "compiler": compiler,
        "compiler_flags": flags,
        "diff_label": name,
        "source_code": source_code,
        "platform": "gc_wii",
        "diff_flags": [],
    }
    if preset is not None:
        data["preset"] = preset
    return data


def _seed_source_from_repo(name: str, file_path: str, melee_root: Path) -> str:
    """Return the function's current C from src/, or a stub if not found."""
    from src.commit.update import _extract_function_from_code

    src_path = melee_root / "src" / file_path
    if src_path.exists():
        extracted = _extract_function_from_code(src_path.read_text(encoding="utf-8"), name)
        if extracted:
            return extracted
    return "// TODO: Decompile this function\n"


def _owner_is_account(owner) -> bool:
    """True only if `owner` is a real (non-anonymous) decomp.me account.

    decomp.me returns owner as None (unclaimed) or a user dict with an
    `is_anonymous` flag. A claim made without a logged-in session yields an
    anonymous owner, which does NOT satisfy "owned by the user's account".
    """
    return bool(owner) and not owner.get("is_anonymous", False)


def _make_production_client(cookies: dict) -> httpx.AsyncClient:
    """Build an httpx client configured for production (cf_clearance + sessionid + UA)."""
    jar = httpx.Cookies()
    jar.set("cf_clearance", cookies["cf_clearance"], domain="decomp.me")
    if cookies.get("sessionid"):
        jar.set("sessionid", cookies["sessionid"], domain="decomp.me")
    return httpx.AsyncClient(
        base_url=PRODUCTION_DECOMP_ME,
        timeout=60.0,
        cookies=jar,
        headers={"User-Agent": get_production_user_agent(), "Accept": "application/json"},
        follow_redirects=True,
    )


async def _resolve_melee_preset_id(client) -> int | None:
    """Look up the decomp.me Melee preset id (gc_wii) by name, or None if absent."""
    url = "/api/preset?page_size=100"
    try:
        while url:
            r = await client.get(url)
            if r.status_code != 200:
                return None
            d = r.json()
            for p in d.get("results", []):
                if p.get("platform") == "gc_wii" and p.get("name") == MELEE_PRESET_NAME:
                    return p.get("id")
            url = d.get("next")
    except Exception:
        return None
    return None


async def _preflight_auth(cookies: dict) -> None:
    """Cheap authenticated probe before the expensive build. Exit on 403."""
    ua = get_production_user_agent()
    if any(bot in ua.lower() for bot in ("python-requests", "curl/", "httpx")):
        console.print(
            "[yellow]Stored User-Agent looks like a bot; ownership may fail. "
            "Re-run 'melee-agent sync auth'.[/yellow]"
        )
    async with _make_production_client(cookies) as client:
        try:
            resp = await client.get("/api/user")
        except Exception as e:
            console.print(f"[red]Could not reach production: {e}[/red]")
            raise typer.Exit(1)
    if resp.status_code == 403:
        console.print("[red]Production auth failed (403): cf_clearance expired or invalid[/red]")
        console.print("[dim]Run 'melee-agent sync auth' to refresh[/dim]")
        raise typer.Exit(1)
    if cookies.get("sessionid"):
        try:
            user = resp.json()
        except Exception:
            user = {}
        if user.get("is_anonymous", False):
            console.print(
                "[yellow]Note: your stored sessionid is anonymous/expired — the scratch "
                "will NOT be owned by your account. Re-run 'melee-agent sync auth' with a "
                "fresh sessionid (logged into decomp.me) for account ownership.[/yellow]"
            )


async def _create_claim_record(create_data: dict, func_name: str, cookies: dict) -> None:
    from src.client import DecompMeAPIError, DecompMeAuthError

    from .scratch import _save_scratch_token

    async with _make_production_client(cookies) as client:
        # Label the scratch with the Melee preset (kept separate from compiler_flags
        # so the preset's -DM2CTX default does not clobber our explicit flags).
        if "preset" not in create_data:
            preset_id = await _resolve_melee_preset_id(client)
            if preset_id is not None:
                create_data["preset"] = preset_id
            else:
                console.print("[yellow]Could not resolve the Melee preset id; creating without preset label.[/yellow]")
        try:
            result = await create_and_claim_production_scratch(client, create_data)
        except DecompMeAuthError:
            console.print(
                "[red]Create blocked (403): cf_clearance expired. Run 'melee-agent sync auth'.[/red]"
            )
            raise typer.Exit(1)
        except DecompMeAPIError as e:
            console.print(f"[red]Create failed: {e}[/red]")
            raise typer.Exit(1)

        slug = result.slug
        console.print(f"[green]Created scratch:[/green] {PRODUCTION_DECOMP_ME}/scratch/{slug}")

        if result.claim_token:
            _save_scratch_token(slug, result.claim_token)

        owned_by_account = False
        try:
            verify = await client.get(f"/api/scratch/{slug}")
            if verify.status_code == 200:
                owned_by_account = _owner_is_account(verify.json().get("owner"))
        except Exception:
            pass

        if not owned_by_account:
            console.print(
                "[yellow]Warning: scratch is NOT owned by your account (it is anonymous "
                "or unclaimed). Your stored sessionid is likely expired or not logged in. "
                "Re-run 'melee-agent sync auth' with a fresh sessionid, then "
                f"'melee-agent sync fix-ownership --function {func_name}'.[/yellow]"
            )

        db_upsert_scratch(slug, "production", PRODUCTION_DECOMP_ME, function_name=func_name)
        db_upsert_function(func_name, production_scratch_slug=slug, status="in_progress")


def run_production_create(
    function_name: str,
    melee_root: Path,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    """Create a scratch on production decomp.me from a worktree function."""
    from src.extractor import extract_function

    from .scratch import _build_stripped_context

    cookies = load_production_cookies()
    if not cookies.get("cf_clearance"):
        console.print("[red]No cf_clearance cookie configured[/red]")
        console.print("[dim]Run 'melee-agent sync auth' first[/dim]")
        raise typer.Exit(1)

    # Cheap auth probe BEFORE the expensive build.
    asyncio.run(_preflight_auth(cookies))

    # Idempotency: don't create duplicate prod scratches for the same function.
    if not force:
        from src.db import get_db

        existing = None
        try:
            with get_db().connection() as conn:
                row = conn.execute(
                    "SELECT production_scratch_slug FROM functions WHERE function_name = ?",
                    (function_name,),
                ).fetchone()
                existing = row["production_scratch_slug"] if row else None
        except Exception:
            existing = None
        if existing:
            console.print(f"[yellow]{function_name} already has a production scratch:[/yellow]")
            console.print(f"  {PRODUCTION_DECOMP_ME}/scratch/{existing}")
            console.print("[dim]Use --force to create another[/dim]")
            raise typer.Exit(0)

    func = asyncio.run(extract_function(melee_root, function_name))
    if func is None:
        console.print(f"[red]Function '{function_name}' not found[/red]")
        raise typer.Exit(1)
    if not func.asm:
        console.print(f"[red]No target ASM for {function_name} — build first.[/red]")
        console.print(
            "[dim]Run: python configure.py && ninja  "
            "(or in a fresh worktree: python tools/worktree-doctor.py --fix)[/dim]"
        )
        raise typer.Exit(1)

    context = _build_stripped_context(function_name, func, melee_root, None)
    source_code = _seed_source_from_repo(func.name, func.file_path, melee_root)
    if source_code.startswith("// TODO"):
        console.print(f"[yellow]No repo C found for {function_name}; seeding stub[/yellow]")
    compiler = get_compiler_for_source(func.file_path, melee_root)
    console.print(f"[dim]Using compiler: {compiler}[/dim]")

    create_data = build_production_create_data(
        name=func.name,
        target_asm=func.asm,
        context=context,
        source_code=source_code,
        compiler=compiler,
    )

    if dry_run:
        console.print("[cyan]DRY RUN — not creating[/cyan]")
        console.print(f"  Target: {PRODUCTION_DECOMP_ME}/api/scratch")
        console.print(
            f"  name={create_data['name']} compiler={create_data['compiler']} "
            f"platform={create_data['platform']}"
        )
        console.print(f"  flags={create_data['compiler_flags']}")
        console.print(f"  preset={MELEE_PRESET_NAME!r} (id resolved at create)")
        console.print(
            f"  sizes: source={len(create_data['source_code'])} "
            f"context={len(create_data['context'])} target_asm={len(create_data['target_asm'])}"
        )
        return

    asyncio.run(_create_claim_record(create_data, func.name, cookies))
