# Production Scratch Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `melee-agent scratch create <func> --production` to create a scratch on https://decomp.me directly from a worktree function, with no local decomp.me server.

**Architecture:** Reuse the existing `scratch create` worktree payload-building (ASM via `extract_function`, ninja `.ctx` context, compiler detection). Seed source from the function's current repo C. POST + claim on production via stored credentials (`cf_clearance` + `sessionid` + matching UA). Extract a shared create+claim helper used by both the new path and the refactored `sync production`.

**Tech Stack:** Python, Typer, httpx (async), respx (httpx test mocking), pytest (`asyncio_mode = "auto"`), SQLite state DB.

**Spec:** [docs/superpowers/specs/2026-06-07-production-scratch-create-design.md](../specs/2026-06-07-production-scratch-create-design.md)

**All commands run from:** `/Users/mike/code/melee/.claude/worktrees/serene-wing-372f24/tools/melee-agent`
(this worktree's own `tools/melee-agent`; do NOT cd to the main checkout). Tests use `-o addopts=""` to skip the coverage plugin for speed.

---

## File map

| File | Change | Responsibility |
|------|--------|----------------|
| `src/client/api.py` | Modify | Add `DecompMeAuthError(DecompMeAPIError)` |
| `src/client/__init__.py` | Modify | Export `DecompMeAuthError` |
| `src/cli/sync/_helpers.py` | Modify | Add `ProductionCreateResult`, `claim_production_scratch`, `create_and_claim_production_scratch` |
| `src/cli/sync/production.py` | Modify | Refactor create+claim to use the helper; keep break-on-403 |
| `src/cli/scratch.py` | Modify | Extract `_build_stripped_context`; add `--production/--force/--dry-run` branch |
| `src/cli/scratch_production.py` | Create | Pure payload builder + repo-source seed + prod client + preflight + `run_production_create` |
| `tests/test_client_auth_error.py` | Create | `DecompMeAuthError` is a `DecompMeAPIError` |
| `tests/test_sync_helpers_production.py` | Create | respx tests for the create+claim helper |
| `tests/test_sync_production_break_on_403.py` | Create | Regression: a 403 stops the batch |
| `tests/test_scratch_production.py` | Create | Pure builder, repo seed, no-auth exit, `--production` flag present |

---

## Task 1: Typed auth error

**Files:**
- Modify: `src/client/api.py` (after the `DecompMeAPIError` class, ~line 82-85)
- Modify: `src/client/__init__.py` (imports + `__all__`)
- Test: `tests/test_client_auth_error.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_client_auth_error.py`:

```python
"""DecompMeAuthError must be a DecompMeAPIError subclass so callers can either
catch it specifically (to stop a batch on a dead cookie) or fall through to the
generic API-error handler."""

from src.client import DecompMeAPIError, DecompMeAuthError


def test_auth_error_is_api_error_subclass():
    assert issubclass(DecompMeAuthError, DecompMeAPIError)


def test_auth_error_instance_is_api_error():
    err = DecompMeAuthError("403")
    assert isinstance(err, DecompMeAPIError)
    assert str(err) == "403"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_client_auth_error.py -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'DecompMeAuthError'`

- [ ] **Step 3: Add the exception class**

In `src/client/api.py`, immediately after the `DecompMeAPIError` class definition (the `pass` body around line 85), add:

```python
class DecompMeAuthError(DecompMeAPIError):
    """Raised when production rejects authentication (403 / Cloudflare challenge /
    expired cf_clearance). Distinct so a batch caller can stop on it while
    continuing past ordinary create failures."""

    pass
```

- [ ] **Step 4: Export it**

In `src/client/__init__.py`, change the api import (currently `from .api import DecompMeAPIClient, DecompMeAPIError`) to:

```python
from .api import DecompMeAPIClient, DecompMeAPIError, DecompMeAuthError
```

and add `"DecompMeAuthError",` to the `__all__` list (next to `"DecompMeAPIError",`).

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_client_auth_error.py -o addopts="" -q`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/client/api.py src/client/__init__.py tests/test_client_auth_error.py
git commit -m "feat(client): add DecompMeAuthError for production 403 handling"
```

---

## Task 2: Shared production create+claim helper

**Files:**
- Modify: `src/cli/sync/_helpers.py`
- Test: `tests/test_sync_helpers_production.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sync_helpers_production.py`:

```python
"""Tests for the shared production create+claim helper (respx-mocked httpx)."""

import httpx
import pytest
import respx

from src.client import DecompMeAPIError, DecompMeAuthError
from src.cli.sync._helpers import (
    ProductionCreateResult,
    claim_production_scratch,
    create_and_claim_production_scratch,
)

PAYLOAD = {"name": "fn_1", "target_asm": "x", "context": "", "compiler": "mwcc_233_163n"}


@pytest.fixture(autouse=True)
def _no_rate_limit_sleep(monkeypatch):
    # rate_limited_request sleeps ~1s after each request; zero it for tests.
    monkeypatch.setattr("src.cli.sync._helpers.RATE_LIMIT_DELAY", 0.0)


@respx.mock
async def test_create_and_claim_happy():
    respx.post("https://decomp.me/api/scratch").mock(
        return_value=httpx.Response(201, json={"slug": "abc123", "claim_token": "tok"})
    )
    respx.post("https://decomp.me/api/scratch/abc123/claim").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        result = await create_and_claim_production_scratch(client, PAYLOAD)
    assert isinstance(result, ProductionCreateResult)
    assert result.slug == "abc123"
    assert result.claim_token == "tok"
    assert result.claimed is True


@respx.mock
async def test_create_403_raises_auth_error():
    respx.post("https://decomp.me/api/scratch").mock(return_value=httpx.Response(403, text="blocked"))
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        with pytest.raises(DecompMeAuthError):
            await create_and_claim_production_scratch(client, PAYLOAD)


@respx.mock
async def test_create_500_raises_api_error():
    respx.post("https://decomp.me/api/scratch").mock(return_value=httpx.Response(500, text="boom"))
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        with pytest.raises(DecompMeAPIError):
            await create_and_claim_production_scratch(client, PAYLOAD)


@respx.mock
async def test_claim_failure_returns_not_claimed():
    respx.post("https://decomp.me/api/scratch").mock(
        return_value=httpx.Response(201, json={"slug": "abc123", "claim_token": "tok"})
    )
    respx.post("https://decomp.me/api/scratch/abc123/claim").mock(
        return_value=httpx.Response(200, json={"success": False})
    )
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        result = await create_and_claim_production_scratch(client, PAYLOAD)
    assert result.slug == "abc123"
    assert result.claimed is False


@respx.mock
async def test_no_claim_token_means_not_claimed():
    respx.post("https://decomp.me/api/scratch").mock(
        return_value=httpx.Response(201, json={"slug": "abc123", "claim_token": None})
    )
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        result = await create_and_claim_production_scratch(client, PAYLOAD)
    assert result.claimed is False


@respx.mock
async def test_429_then_201_succeeds_via_backoff():
    respx.post("https://decomp.me/api/scratch").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(201, json={"slug": "abc123", "claim_token": None}),
        ]
    )
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        result = await create_and_claim_production_scratch(client, PAYLOAD)
    assert result.slug == "abc123"


@respx.mock
async def test_claim_production_scratch_helper():
    respx.post("https://decomp.me/api/scratch/s1/claim").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        assert await claim_production_scratch(client, "s1", "tok") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sync_helpers_production.py -o addopts="" -q`
Expected: FAIL with `ImportError: cannot import name 'ProductionCreateResult'`

- [ ] **Step 3: Add the helper**

In `src/cli/sync/_helpers.py`, add `from dataclasses import dataclass` to the imports at the top, and append at the end of the file:

```python
from dataclasses import dataclass

from src.client import DecompMeAPIError, DecompMeAuthError


@dataclass
class ProductionCreateResult:
    """Outcome of creating + claiming a production scratch."""

    slug: str
    claim_token: str | None
    claimed: bool


async def claim_production_scratch(prod_client, slug: str, token: str) -> bool:
    """Claim ownership of a production scratch. Returns True iff ownership took.

    Claim failure is non-fatal (the scratch still exists, claimable later), so
    this returns False rather than raising.
    """
    resp = await rate_limited_request(
        prod_client, "post", f"/api/scratch/{slug}/claim", json={"token": token}
    )
    if resp.status_code == 200:
        try:
            return bool(resp.json().get("success"))
        except Exception:
            return False
    return False


async def create_and_claim_production_scratch(prod_client, create_data: dict) -> ProductionCreateResult:
    """POST a scratch to production and claim it.

    Raises ``DecompMeAuthError`` on 403 (Cloudflare / expired cf_clearance) so a
    batch caller can stop; raises ``DecompMeAPIError`` on other non-2xx. Claim
    failures are reported via ``ProductionCreateResult.claimed`` (not raised).
    """
    resp = await rate_limited_request(prod_client, "post", "/api/scratch", json=create_data)
    if resp.status_code == 403:
        raise DecompMeAuthError(f"Production create blocked (403): {resp.text[:200]}")
    if resp.status_code not in (200, 201):
        raise DecompMeAPIError(f"Production create failed: {resp.status_code} - {resp.text[:200]}")

    data = resp.json()
    slug = data.get("slug")
    token = data.get("claim_token")
    claimed = False
    if token:
        claimed = await claim_production_scratch(prod_client, slug, token)
    return ProductionCreateResult(slug=slug, claim_token=token, claimed=claimed)
```

(The `dataclass`/`DecompMeAPIError` imports may be placed with the other top-of-file imports instead of inline — either is fine as long as they resolve.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sync_helpers_production.py -o addopts="" -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cli/sync/_helpers.py tests/test_sync_helpers_production.py
git commit -m "feat(sync): shared production create+claim helper"
```

---

## Task 3: Refactor `sync production` onto the helper (preserve break-on-403)

**Files:**
- Modify: `src/cli/sync/production.py`
- Test: `tests/test_sync_production_break_on_403.py`

- [ ] **Step 1: Write the failing regression test**

Create `tests/test_sync_production_break_on_403.py`:

```python
"""Regression: a create-path 403 must STOP the batch (not keep hammering
production with a known-bad cf_clearance). Locks the behavior across the
helper-extraction refactor."""

from src.client import DecompMeAuthError


class _FakeLocalScratch:
    name = "fn_1"
    compiler = "mwcc_233_163n"
    platform = "gc_wii"
    compiler_flags = "-O4,p"
    diff_flags: list = []
    # Long, non-placeholder body so the prod sync uses it directly (no repo refresh).
    source_code = "void fn_1(void) { int x = 0; (void)x; /* real-looking body padding */ }"
    context = ""
    diff_label = "fn_1"


class _FakeLocalClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get_scratch(self, slug):
        return _FakeLocalScratch()

    async def export_scratch(self, slug, target_only=False):
        raise RuntimeError("no export in test")  # caught -> target_asm=""


class _FakeResp:
    status_code = 200

    def json(self):
        return {"results": []}


async def _fake_rate_limited_request(client, method, url, **kwargs):
    return _FakeResp()


def test_403_stops_the_batch(tmp_path, monkeypatch):
    from src.db import StateDB, reset_db
    import src.cli.sync.production as prod

    reset_db()
    db = StateDB(tmp_path / "t.db")
    db.upsert_function("fn_1", local_scratch_slug="l1", match_percent=50.0)
    db.upsert_function("fn_2", local_scratch_slug="l2", match_percent=40.0)

    calls = {"create": 0}

    async def _fake_create_and_claim(prod_client, create_data):
        calls["create"] += 1
        raise DecompMeAuthError("403")

    # Keep the test hermetic: synced_scratches.json is written next to this path.
    monkeypatch.setattr(prod, "PRODUCTION_COOKIES_FILE", tmp_path / "production_cookies.json")
    monkeypatch.setattr("src.db.get_db", lambda *a, **k: db)
    monkeypatch.setattr(prod, "load_production_cookies", lambda: {"cf_clearance": "x", "sessionid": "y"})
    monkeypatch.setattr(prod, "rate_limited_request", _fake_rate_limited_request)
    monkeypatch.setattr(prod, "create_and_claim_production_scratch", _fake_create_and_claim)
    monkeypatch.setattr("src.client.DecompMeAPIClient", _FakeLocalClient)

    prod.production_command(
        melee_root=tmp_path,
        local_url="http://localhost:8000",
        min_match=0.0,
        limit=10,
        dry_run=False,
        force=False,
        function=None,
        slug=None,
    )

    # Two functions queued, but the first 403 must break the loop.
    assert calls["create"] == 1

    db.close()
    reset_db()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sync_production_break_on_403.py -o addopts="" -q`
Expected: FAIL — `AttributeError: ... has no attribute 'create_and_claim_production_scratch'` (production.py does not import it yet).

- [ ] **Step 3: Add imports to production.py**

In `src/cli/sync/production.py`, change the helper import (currently `from ._helpers import load_production_cookies, rate_limited_request`) to:

```python
from ._helpers import (
    create_and_claim_production_scratch,
    load_production_cookies,
    rate_limited_request,
)
```

and add near the other imports at the top:

```python
from src.client import DecompMeAPIError, DecompMeAuthError
```

- [ ] **Step 4: Replace the inline create+claim block with the helper**

Find this block (the create POST through the final `else` that handles non-2xx — currently around lines 385-460, beginning with `console.print("[dim]  Creating scratch on production...[/dim]")`):

```python
                        console.print("[dim]  Creating scratch on production...[/dim]")
                        resp = await rate_limited_request(prod_client, "post", "/api/scratch", json=create_data)
                        console.print(f"[dim]  Create complete (status {resp.status_code})[/dim]")

                        if resp.status_code == 201 or resp.status_code == 200:
                            prod_data = resp.json()
                            prod_slug = prod_data.get("slug", "unknown")
                            claim_token = prod_data.get("claim_token")
                            console.print(f"[green]  Created: {PRODUCTION_DECOMP_ME}/scratch/{prod_slug}[/green]")

                            # Claim ownership of the scratch
                            if claim_token:
                                console.print("[dim]  Claiming ownership...[/dim]")
                                try:
                                    claim_resp = await rate_limited_request(
                                        prod_client,
                                        "post",
                                        f"/api/scratch/{prod_slug}/claim",
                                        json={"token": claim_token},
                                    )
                                    if claim_resp.status_code == 200:
                                        claim_result = claim_resp.json()
                                        if claim_result.get("success"):
                                            console.print("[green]  Ownership claimed[/green]")
                                        else:
                                            console.print("[yellow]  Claim returned success=false[/yellow]")
                                    else:
                                        console.print(f"[yellow]  Claim failed: {claim_resp.status_code}[/yellow]")
                                except Exception as claim_err:
                                    console.print(f"[yellow]  Claim error: {claim_err}[/yellow]")
                            else:
                                console.print("[yellow]  No claim_token returned, scratch will be anonymous[/yellow]")

                            # Update slug map
                            current_slug_map = load_slug_map()
                            current_slug_map[prod_slug] = {
                                "local_slug": local_slug,
                                "function": func_name,
                                "match_percent": match_pct,
                                "synced_at": time.time(),
                            }
                            save_slug_map(current_slug_map)

                            # Update state database
                            db_record_sync(local_slug, prod_slug, func_name)
                            db_upsert_scratch(
                                prod_slug,
                                "production",
                                PRODUCTION_DECOMP_ME,
                                function_name=func_name,
                                match_percent=match_pct,
                            )
                            db_upsert_function(func_name, production_scratch_slug=prod_slug)

                            synced[local_slug] = {
                                "production_slug": prod_slug,
                                "function": func_name,
                                "match_percent": match_pct,
                                "timestamp": time.time(),
                            }
                            results["success"] += 1
                            results["details"].append(
                                {
                                    "function": func_name,
                                    "local_slug": local_slug,
                                    "production_slug": prod_slug,
                                }
                            )
                        elif resp.status_code == 403:
                            console.print("[red]  Failed: Cloudflare blocked (cf_clearance expired?)[/red]")
                            results["failed"] += 1
                            break
                        else:
                            error_text = resp.text[:200]
                            console.print(f"[red]  Failed: {resp.status_code} - {error_text}[/red]")
                            results["failed"] += 1
```

Replace it entirely with:

```python
                        console.print("[dim]  Creating scratch on production...[/dim]")
                        try:
                            create_result = await create_and_claim_production_scratch(
                                prod_client, create_data
                            )
                        except DecompMeAuthError:
                            console.print("[red]  Failed: Cloudflare blocked (cf_clearance expired?)[/red]")
                            results["failed"] += 1
                            break
                        except DecompMeAPIError as create_err:
                            console.print(f"[red]  Failed: {create_err}[/red]")
                            results["failed"] += 1
                            continue

                        prod_slug = create_result.slug
                        claim_token = create_result.claim_token
                        console.print(f"[green]  Created: {PRODUCTION_DECOMP_ME}/scratch/{prod_slug}[/green]")
                        if claim_token and create_result.claimed:
                            console.print("[green]  Ownership claimed[/green]")
                        elif claim_token:
                            console.print("[yellow]  Claim did not confirm ownership[/yellow]")
                        else:
                            console.print("[yellow]  No claim_token returned, scratch will be anonymous[/yellow]")

                        # Update slug map
                        current_slug_map = load_slug_map()
                        current_slug_map[prod_slug] = {
                            "local_slug": local_slug,
                            "function": func_name,
                            "match_percent": match_pct,
                            "synced_at": time.time(),
                        }
                        save_slug_map(current_slug_map)

                        # Update state database
                        db_record_sync(local_slug, prod_slug, func_name)
                        db_upsert_scratch(
                            prod_slug,
                            "production",
                            PRODUCTION_DECOMP_ME,
                            function_name=func_name,
                            match_percent=match_pct,
                        )
                        db_upsert_function(func_name, production_scratch_slug=prod_slug)

                        synced[local_slug] = {
                            "production_slug": prod_slug,
                            "function": func_name,
                            "match_percent": match_pct,
                            "timestamp": time.time(),
                        }
                        results["success"] += 1
                        results["details"].append(
                            {
                                "function": func_name,
                                "local_slug": local_slug,
                                "production_slug": prod_slug,
                            }
                        )
```

Note: the success-bookkeeping is now dedented one level (it is no longer inside `if status == 201`). The outer per-function `try: ... except Exception` (which wraps the local fetch/export) stays intact and continues to `continue` on unexpected errors.

- [ ] **Step 5: Run regression test to verify it passes**

Run: `python -m pytest tests/test_sync_production_break_on_403.py -o addopts="" -q`
Expected: PASS (1 passed)

- [ ] **Step 6: Commit**

```bash
git add src/cli/sync/production.py tests/test_sync_production_break_on_403.py
git commit -m "refactor(sync): production uses shared create+claim helper; keep break-on-403"
```

---

## Task 4: Extract `_build_stripped_context` in scratch.py

**Files:**
- Modify: `src/cli/scratch.py`
- Test: (covered by the existing suite import + Task 7 flag test; this is a pure move)

- [ ] **Step 1: Add the extracted helper**

In `src/cli/scratch.py`, add this module-level function just above `scratch_create` (the `@scratch_app.command("create")` decorator, ~line 153):

```python
def _build_stripped_context(function_name, func, melee_root, context_file):
    """Build the per-file .ctx context via ninja and strip the target function's
    definition (keeping its declaration) to avoid redefinition errors.

    Shared by the local `scratch create` path and the `--production` path.
    Returns the stripped context string. Exits (typer.Exit) on build failure.
    """
    import subprocess

    ctx_path = context_file or _get_context_file(source_file=func.file_path)

    # Build the context file - need relative path from melee_root
    try:
        ctx_relative = ctx_path.relative_to(melee_root)
        ninja_cwd = melee_root
    except ValueError:
        # ctx_path might be in a worktree; run ninja from that worktree root.
        parts = ctx_path.parts
        ninja_cwd = None
        for i, part in enumerate(parts):
            if part == "build" and i > 0:
                ninja_cwd = Path(*parts[:i])
                ctx_relative = Path(*parts[i:])
                break
        if ninja_cwd is None:
            console.print(f"[red]Cannot determine ninja target for: {ctx_path}[/red]")
            raise typer.Exit(1)

    try:
        result = subprocess.run(
            ["ninja", str(ctx_relative)],
            cwd=ninja_cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            console.print("[red]Failed to build context file:[/red]")
            console.print(result.stderr or result.stdout)
            console.print("[dim]Fresh worktree? Try: python tools/worktree-doctor.py --fix[/dim]")
            raise typer.Exit(1)
        if "no work to do" not in result.stdout.lower():
            console.print("[green]Built context file[/green]")
    except subprocess.TimeoutExpired:
        console.print("[red]Timeout building context file[/red]")
        raise typer.Exit(1)
    except FileNotFoundError:
        console.print("[red]ninja not found - please install it[/red]")
        raise typer.Exit(1)

    if not ctx_path.exists():
        console.print(f"[red]Context file not found after build: {ctx_path}[/red]")
        raise typer.Exit(1)

    melee_context = ctx_path.read_text()
    console.print(f"[dim]Loaded {len(melee_context):,} bytes of context from {ctx_path.name}[/dim]")

    # Strip function definition (but keep declaration) to avoid redefinition errors
    if function_name in melee_context:
        lines = melee_context.split("\n")
        filtered = []
        in_func = False
        depth = 0
        for line in lines:
            if not in_func and function_name in line and "(" in line:
                s = line.strip()
                if s.startswith("//") or s.startswith("if") or s.startswith("while"):
                    filtered.append(line)
                    continue
                if s.endswith(";"):
                    filtered.append(line)
                    continue
                in_func = True
                depth = line.count("{") - line.count("}")
                filtered.append(f"// {function_name} definition stripped")
                if "{" not in line:
                    depth = 0
                elif depth <= 0:
                    in_func = False
                continue
            if in_func:
                depth += line.count("{") - line.count("}")
                if depth <= 0:
                    in_func = False
                continue
            filtered.append(line)
        melee_context = "\n".join(filtered)
        console.print(f"[dim]Stripped {function_name} definition from context[/dim]")

    return melee_context
```

- [ ] **Step 2: Replace the inline context-building in `scratch_create` with a call**

In `scratch_create`, find the inline region that builds + strips the context — it starts at the `# Get context file using the function's source file path` comment (~line 180, the line **above** `ctx_path = context_file or _get_context_file(source_file=func.file_path)`) and ends at the `console.print(f"[dim]Stripped {function_name} definition from context[/dim]")` line (~line 267). Include that leading comment in the replaced region so no orphan comment is left. Replace that entire region with:

```python
    # Build + strip the per-file context (worktree-aware).
    melee_context = _build_stripped_context(function_name, func, melee_root, context_file)
```

Leave everything after it (`compiler = get_compiler_for_source(...)` and the `async def create():` block) unchanged.

- [ ] **Step 3: Verify nothing broke (import + full existing suite)**

Run: `python -c "import src.cli.scratch"`
Expected: no output, no error.

Run: `python -m pytest tests/test_scratch.py tests/test_cli.py -o addopts="" -q`
Expected: PASS (same counts as before the change).

- [ ] **Step 4: Commit**

```bash
git add src/cli/scratch.py
git commit -m "refactor(scratch): extract _build_stripped_context for reuse"
```

---

## Task 5: Pure payload builder + repo-source seed

**Files:**
- Create: `src/cli/scratch_production.py`
- Test: `tests/test_scratch_production.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scratch_production.py`:

```python
"""Tests for the production scratch-create building blocks (pure / no network)."""

import pytest

from src.cli.scratch_production import (
    PRODUCTION_COMPILER_FLAGS,
    build_production_create_data,
    _seed_source_from_repo,
)


def test_build_payload_fields():
    data = build_production_create_data(
        name="fn_1",
        target_asm="/* asm */\nblr",
        context="struct X {};",
        source_code="void fn_1(void) {}",
        compiler="mwcc_233_163n",
    )
    assert data["name"] == "fn_1"
    assert data["diff_label"] == "fn_1"
    assert data["target_asm"] == "/* asm */\nblr"
    assert data["context"] == "struct X {};"
    assert data["source_code"] == "void fn_1(void) {}"
    assert data["compiler"] == "mwcc_233_163n"
    assert data["platform"] == "gc_wii"
    assert data["diff_flags"] == []
    assert data["compiler_flags"] == PRODUCTION_COMPILER_FLAGS


def test_build_payload_flags_override():
    data = build_production_create_data(
        name="f", target_asm="x", context="", source_code="", compiler="c", flags="-O0"
    )
    assert data["compiler_flags"] == "-O0"


def test_seed_source_extracts_from_repo(tmp_path):
    src = tmp_path / "src" / "melee" / "mn"
    src.mkdir(parents=True)
    (src / "mnfoo.c").write_text(
        "#include <x.h>\n\nvoid mnFoo(int a) {\n    return;\n}\n\nvoid other(void) {}\n"
    )
    out = _seed_source_from_repo("mnFoo", "melee/mn/mnfoo.c", tmp_path)
    assert "mnFoo" in out
    assert out.strip().startswith("void mnFoo")
    assert "other" not in out


def test_seed_source_stub_when_missing(tmp_path):
    out = _seed_source_from_repo("mnFoo", "melee/mn/missing.c", tmp_path)
    assert out == "// TODO: Decompile this function\n"


def test_seed_source_stub_when_function_absent(tmp_path):
    src = tmp_path / "src" / "melee" / "mn"
    src.mkdir(parents=True)
    (src / "mnfoo.c").write_text("void somethingElse(void) {}\n")
    out = _seed_source_from_repo("mnFoo", "melee/mn/mnfoo.c", tmp_path)
    assert out == "// TODO: Decompile this function\n"


def test_compiler_flags_constant():
    assert PRODUCTION_COMPILER_FLAGS.startswith("-O4,p")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scratch_production.py -o addopts="" -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.cli.scratch_production'`

- [ ] **Step 3: Create the module with the pure pieces**

Create `src/cli/scratch_production.py`:

```python
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

# Matches the local `scratch create` default. Diverges from CLAUDE.md canonical
# (-fp hard not -fp hardware, no -proc gekko); reused for parity with local
# create since there is no source scratch to copy flags from.
PRODUCTION_COMPILER_FLAGS = (
    "-O4,p -nodefaults -fp hard -Cpp_exceptions off -enum int -fp_contract on -inline auto"
)


def build_production_create_data(
    *,
    name: str,
    target_asm: str,
    context: str,
    source_code: str,
    compiler: str,
    flags: str = PRODUCTION_COMPILER_FLAGS,
) -> dict:
    """Build the /api/scratch POST body for a production scratch (pure)."""
    return {
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


def _seed_source_from_repo(name: str, file_path: str, melee_root: Path) -> str:
    """Return the function's current C from src/, or a stub if not found."""
    from src.commit.update import _extract_function_from_code

    src_path = melee_root / "src" / file_path
    if src_path.exists():
        extracted = _extract_function_from_code(src_path.read_text(encoding="utf-8"), name)
        if extracted:
            return extracted
    return "// TODO: Decompile this function\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scratch_production.py -o addopts="" -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cli/scratch_production.py tests/test_scratch_production.py
git commit -m "feat(scratch): pure production payload builder + repo-source seed"
```

---

## Task 6: Prod client, preflight, and orchestration

**Files:**
- Modify: `src/cli/scratch_production.py`
- Test: `tests/test_scratch_production.py` (add the no-auth exit test)

- [ ] **Step 1: Write the failing test (no-auth fast exit)**

Append to `tests/test_scratch_production.py`:

```python
def test_run_production_create_exits_without_cf_clearance(tmp_path, monkeypatch):
    import typer

    import src.cli.scratch_production as sp

    # No cf_clearance configured -> must exit before any network/build.
    monkeypatch.setattr(sp, "load_production_cookies", lambda: {})
    with pytest.raises(typer.Exit):
        sp.run_production_create("fn_1", tmp_path, force=False, dry_run=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scratch_production.py::test_run_production_create_exits_without_cf_clearance -o addopts="" -q`
Expected: FAIL — `AttributeError: module 'src.cli.scratch_production' has no attribute 'run_production_create'`

- [ ] **Step 3: Add the client, preflight, and orchestrator**

Append to `src/cli/scratch_production.py`:

```python
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


async def _create_claim_record(create_data: dict, func_name: str, cookies: dict) -> None:
    from src.client import DecompMeAPIError, DecompMeAuthError

    from .scratch import _save_scratch_token

    async with _make_production_client(cookies) as client:
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

        owned = result.claimed
        if owned:
            try:
                verify = await client.get(f"/api/scratch/{slug}")
                if verify.status_code == 200 and verify.json().get("owner") is None:
                    owned = False
            except Exception:
                pass

        if not owned:
            console.print(
                "[yellow]Warning: scratch created but NOT owned (sessionid may be expired). "
                "Re-run 'melee-agent sync auth', then "
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
        console.print(
            f"  sizes: source={len(create_data['source_code'])} "
            f"context={len(create_data['context'])} target_asm={len(create_data['target_asm'])}"
        )
        return

    asyncio.run(_create_claim_record(create_data, func.name, cookies))
```

- [ ] **Step 4: Run the no-auth test to verify it passes**

Run: `python -m pytest tests/test_scratch_production.py -o addopts="" -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cli/scratch_production.py tests/test_scratch_production.py
git commit -m "feat(scratch): production create orchestration (preflight, idempotency, claim+verify)"
```

---

## Task 7: Wire `--production` into `scratch create`

**Files:**
- Modify: `src/cli/scratch.py` (the `scratch_create` command signature + top of body)
- Test: `tests/test_scratch_production.py` (add a flag-presence test)

- [ ] **Step 1: Write the failing test (flag is wired)**

Append to `tests/test_scratch_production.py`:

```python
def test_production_flag_present_in_help():
    from typer.testing import CliRunner

    from src.cli.scratch import scratch_app

    runner = CliRunner()
    result = runner.invoke(scratch_app, ["create", "--help"])
    assert result.exit_code == 0
    assert "--production" in result.output
    assert "--dry-run" in result.output
    assert "--force" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scratch_production.py::test_production_flag_present_in_help -o addopts="" -q`
Expected: FAIL — `--production` not in output.

- [ ] **Step 3: Add the options to `scratch_create`**

In `src/cli/scratch.py`, in the `scratch_create` signature, after the `auto_decompile` parameter add:

```python
    production: Annotated[
        bool, typer.Option("--production", help="Create on production decomp.me instead of the local server")
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="With --production: create even if a production scratch already exists"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="With --production: build and show the payload without creating"),
    ] = False,
```

- [ ] **Step 4: Branch before local-URL detection**

In `scratch_create`, the body currently begins with:

```python
    api_url = api_url or get_local_api_url()
    from src.client import DecompMeAPIClient
```

Insert the production branch immediately **before** the `api_url = api_url or get_local_api_url()` line:

```python
    if production:
        if api_url:
            console.print("[dim]--api-url ignored with --production[/dim]")
        from .scratch_production import run_production_create

        run_production_create(function_name, melee_root, force=force, dry_run=dry_run)
        return

    api_url = api_url or get_local_api_url()
    from src.client import DecompMeAPIClient
```

- [ ] **Step 5: Run the flag test + import smoke**

Run: `python -m pytest tests/test_scratch_production.py -o addopts="" -q`
Expected: PASS (8 passed)

Run: `python -c "import src.cli.scratch, src.cli.scratch_production"`
Expected: no error (confirms no circular-import problem; the cross-imports are lazy/inside functions).

- [ ] **Step 6: Commit**

```bash
git add src/cli/scratch.py tests/test_scratch_production.py
git commit -m "feat(scratch): --production/--force/--dry-run on scratch create"
```

---

## Task 8: Full suite + manual target-ASM verification gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full melee-agent test suite**

Run: `python -m pytest tests/ -o addopts="" -q`
Expected: All tests pass (live-backend tests may `skip`; no failures). Investigate any failure before proceeding.

- [ ] **Step 2: Dry-run against a real, built function (no network create)**

Pick a function in a built worktree (build `build/GALE01/asm` must be populated; if empty, run `python configure.py && ninja` first, or `python tools/worktree-doctor.py --fix` in a fresh worktree).

Run: `melee-agent scratch create <some_known_function> --production --dry-run`
Expected: prints the target URL and payload summary with non-zero `source`, `context`, and **non-zero `target_asm`** sizes. (If `target_asm` errors with "build first", build the worktree.)

- [ ] **Step 3: MANUAL GATE — confirm production accepts the DTK target ASM**

This is the one assumption the unit tests cannot cover (see spec "Target-ASM verification gate"). Requires `melee-agent sync auth` configured.

Run: `melee-agent scratch create <some_known_function> --production`
Then open the printed `https://decomp.me/scratch/<slug>` URL and confirm:
- the scratch **compiles** and shows a **score/diff** (production's gc_wii assembler accepted the DTK `target_asm`), and
- the scratch is **owned** by your account (no "created but NOT owned" warning).

**If production rejects the DTK ASM** (assembler error, no score): implement the conversion contingency — in `run_production_create`, convert before building the payload:

```python
    from src.mwcc_debug.dtk_objdump import convert_dtk_disasm_to_objdump

    target_asm = convert_dtk_disasm_to_objdump(func.asm)
```

and pass `target_asm=target_asm` to `build_production_create_data`. Add a unit test feeding a small DTK snippet through `convert_dtk_disasm_to_objdump` and asserting the `.fn`/`.include` directives are gone. Re-run the gate.

- [ ] **Step 4: Final commit (if the gate required the conversion change)**

```bash
git add src/cli/scratch_production.py tests/test_scratch_production.py
git commit -m "fix(scratch): convert DTK target ASM for production assembler"
```

---

## Self-review notes (for the implementer)

- **Spec coverage:** Task 1 = `DecompMeAuthError`; Task 2 = Unit A helper; Task 3 = `sync production` refactor + break-on-403 regression; Task 4 = `_build_stripped_context` reuse; Task 5 = pure `build_production_create_data` + repo seed; Task 6 = prod client, `_preflight_auth`, idempotency, ownership verify, DB bookkeeping; Task 7 = `--production/--force/--dry-run` wiring (skips `get_local_api_url`); Task 8 = full suite + the target-ASM verification gate (+ DTK→objdump contingency).
- **Type/name consistency:** `ProductionCreateResult(slug, claim_token, claimed)` is produced in Task 2 and consumed in Tasks 3 & 6. `build_production_create_data(*, name, target_asm, context, source_code, compiler, flags)` is defined in Task 5 and called in Task 6. `_build_stripped_context(function_name, func, melee_root, context_file)` is defined in Task 4 and called in Task 6. `run_production_create(function_name, melee_root, force, dry_run)` defined in Task 6, called in Task 7.
- **No network in unit tests:** Tasks 1-7 are fully offline (respx + monkeypatch). Only Task 8 step 3 touches production, by design.
