# Production scratch creation from a worktree function

- **Date:** 2026-06-07
- **Status:** Approved (design)
- **Component:** `melee-agent scratch` / `melee-agent sync`

## Problem

The decomp tooling can create scratches on a *local, self-hosted* decomp.me
instance, but that instance is no longer hosted. We want to create a scratch on
**production** `https://decomp.me` directly **from a specific function in the
current worktree**, with no local decomp.me server in the loop.

Authentication against production already works (`cf_clearance`, `sessionid`, and
a matching browser `User-Agent` are stored by `melee-agent sync auth` in
`~/.config/decomp-me/production_cookies.json`). What is missing is a
worktree → production *create* path.

## Current state (audit findings)

Two cookie stores, two code paths exist today:

1. **`melee-agent sync auth`** ([`cli/sync/auth.py`](../../../tools/melee-agent/src/cli/sync/auth.py))
   writes `cf_clearance` + `user_agent` + `sessionid` to
   `~/.config/decomp-me/production_cookies.json` (`PRODUCTION_COOKIES_FILE`).
   That file already exists on this machine and contains all three keys.

2. **`melee-agent sync production`** ([`cli/sync/production.py`](../../../tools/melee-agent/src/cli/sync/production.py))
   already `POST`s a scratch to `https://decomp.me/api/scratch` using the
   production cookies + matching UA + rate-limited transport, and claims
   ownership via the returned `claim_token`. **But it is coupled to a running
   local server**: it fetches the source/context from a *local scratch* and
   exports the target ASM from the local server. With no local server, this path
   is dead-ended.

3. **`melee-agent scratch create <func>`** ([`cli/scratch.py:153`](../../../tools/melee-agent/src/cli/scratch.py))
   already builds the *entire* scratch payload **directly from the worktree** —
   extracts the target ASM via `extract_function` (`func.asm`), `ninja`-builds
   the per-file `.ctx` context (worktree-aware), strips the function definition
   from the context, detects the compiler — then `POST`s via
   `DecompMeAPIClient.create_scratch()`. It targets `get_local_api_url()` and
   pulls auth from the per-agent `cookies_<id>.json` store, **not** the
   production cookie store.

### Key insight

A production scratch needs **no local server**. The target ASM that
`sync production` laboriously exports from a local scratch is exactly the
`func.asm` that `scratch create` already extracts from the worktree build.
Therefore `--production` only has to swap the **destination + auth**; all of the
existing payload-building is reused unchanged.

### The gap

- `DecompMeAPIClient` ([`client/api.py:154`](../../../tools/melee-agent/src/client/api.py))
  loads auth from the per-agent `cookies_<id>.json` store (none exist), sends a
  **hardcoded** `User-Agent` (Cloudflare binds `cf_clearance` to the exact UA),
  and sends an `X-API-Client: melee-agent` header that is a self-hosted-only
  affordance. It also *persists* server-set `sessionid`/`cf_clearance` back into
  the per-agent store on every create/claim — which would clobber the stored
  production `sessionid` if reused for prod.
- `scratch create` records DB state as `instance="local"` /
  `local_scratch_slug`.

## Goals

- `melee-agent scratch create <func> --production` creates a scratch on
  `https://decomp.me` from the current worktree, no local server required.
- Authenticate with the stored production credentials; create the scratch under
  the user's decomp.me account (owned, claimed).
- Seed the source with the function's **current repo C** (fall back to a stub if
  the function has no C yet).
- Record the result as a production scratch in the state DB.
- Robust against Cloudflare/`403` and rate-limit/`429`.

## Non-goals

- Making the entire `DecompMeAPIClient` production-aware (compile/get/etc.
  against production). Out of scope; `--production` is create-only.
- Pre-search/dedupe against existing production scratches (`create` implies
  intent to create; `sync production` keeps its own link-existing behavior).
- Server-side m2c auto-decompile against production.
- Maintaining the local↔production `slug_map` for the from-worktree path (there
  is no local slug to map).

## Design

### Interface

```
melee-agent scratch create <function_name> --production [--dry-run]
```

- `--production` forces the destination to `https://decomp.me`
  (`PRODUCTION_DECOMP_ME`), ignoring `--api-url` and `DECOMP_API_BASE`.
- `--dry-run` prints the target URL + a payload summary (name, compiler, flags,
  source/context/asm sizes) and exits without `POST`ing. Also the test seam.
- Existing flags (`--melee-root`, `--context`) still apply. `--decompile/-d` is
  **ignored** in production mode (source is seeded from the repo, not m2c).

### Components / units

**Unit A — shared production create+claim helper**
`create_and_claim_production_scratch(prod_client, create_data) -> (slug, claim_token)`
in [`cli/sync/_helpers.py`](../../../tools/melee-agent/src/cli/sync/_helpers.py).

- Input: an `httpx.AsyncClient` already configured for production (base_url,
  cookies, UA, redirects) and a `create_data` dict.
- Behavior: `POST /api/scratch` via `rate_limited_request`; on `201/200`, read
  `slug` + `claim_token`; if `claim_token` present, `POST
  /api/scratch/{slug}/claim` via `rate_limited_request`. Returns
  `(slug, claim_token)`.
- Errors: raises a typed error on `403` (Cloudflare/expired) and on other
  non-2xx with the truncated response body; `429` is handled by
  `rate_limited_request` backoff.
- **Depends on:** `rate_limited_request` (already in `_helpers.py`).

This block is extracted from the current inline implementation in
`production.py` (~lines 386–416). **`sync production` is refactored to call this
helper**, with identical behavior (it keeps its own pre-search/link-existing,
slug_map, and DB bookkeeping around the call).

**Unit B — `--production` branch in `scratch_create`**
([`cli/scratch.py`](../../../tools/melee-agent/src/cli/scratch.py)).

Reuses the existing, unchanged steps: `extract_function`, `ninja` `.ctx` build
(worktree-aware), function-definition strip, `get_compiler_for_source`.

Production-specific steps:

1. **Auth preflight:** `load_production_cookies()`; if no `cf_clearance`, print a
   clear error pointing to `melee-agent sync auth` and exit.
2. **Source seed:** resolve the function's file via
   `get_file_path_from_function` ([`commit/configure.py:125`](../../../tools/melee-agent/src/commit/configure.py)),
   read `src/<file>`, extract with `_extract_function_from_code`
   ([`commit/update.py:75`](../../../tools/melee-agent/src/commit/update.py)).
   If extraction yields nothing, fall back to `// TODO: Decompile this
   function\n` and warn. No server-side m2c.
3. **Build prod client:** `httpx.AsyncClient(base_url=PRODUCTION_DECOMP_ME)` with
   cookies `cf_clearance` (+ `sessionid` for account ownership), headers
   `User-Agent = get_production_user_agent()` and `Accept: application/json`,
   `follow_redirects=True`, `timeout≈60s`. **No `X-API-Client` header.**
4. **Build `create_data`:**
   `name=func.name`, `target_asm=func.asm`, `context=<built ctx>`,
   `compiler=<detected>`, `compiler_flags=<existing default string>`,
   `diff_label=func.name`, `source_code=<repo C or stub>`. **`platform` is
   omitted** — `ScratchCreate` defaults it to the compiler's platform
   (matching the local `scratch create` behavior); avoids a hardcoded value
   drifting from the compiler's platform key.
5. Call **Unit A**, print `https://decomp.me/scratch/<slug>`.
6. **DB bookkeeping:** `db_upsert_scratch(slug, instance="production",
   base_url=PRODUCTION_DECOMP_ME, function_name=...)` and
   `db_upsert_function(func, production_scratch_slug=slug)`.

The default (local) branch is unchanged.

### Data flow

```
extract_function(worktree, func) ──► func.asm, func.file_path
ninja build .ctx ──► context ──► strip func def ──► context
get_file_path_from_function + _extract_function_from_code ──► repo C (or stub)
get_compiler_for_source ──► compiler id
        │
        ▼
create_data {name, target_asm, context, compiler, compiler_flags,
             diff_label, source_code}   # platform derived from compiler
        │
        ▼ (httpx prod client: cf_clearance + sessionid + matching UA)
create_and_claim_production_scratch ──► POST /api/scratch ──► claim
        │
        ▼
print prod URL; db_upsert_scratch(instance="production"); db_upsert_function
```

### Ownership

The stored `sessionid` is sent, so the scratch is created under the user's
GitHub-linked decomp.me account and claimed via `claim_token` — owned and shown
on the profile. (decomp.me scratches are public regardless.)

### Error handling

| Condition | Behavior |
|-----------|----------|
| No `cf_clearance` in prod cookies | Error → run `melee-agent sync auth`; exit non-zero |
| `403` from production | Error: Cloudflare blocked / `cf_clearance` expired → re-run `sync auth`; exit non-zero |
| `429` | `rate_limited_request` exponential backoff (existing) |
| Function not found in worktree | Existing error path (`scratch create`) |
| Function has no repo C | Seed `// TODO` stub + warning; still create |
| Claim fails | Warn; scratch still created (anonymous-but-claimable) |

## Testing

- **Unit (Unit A):** mocked httpx transport — create→claim happy path returns
  `(slug, token)`; `403` raises typed error; `429`-then-`201` succeeds via
  backoff. Mirrors [`tests/test_client.py`](../../../tools/melee-agent/tests/test_client.py).
- **Unit (Unit B):** `--dry-run` builds the expected `create_data` from a fixture
  worktree/source — asserts repo-C seeding and the stub fallback, asserts the
  target URL is production, asserts no network call. Mirrors
  [`tests/test_scratch.py`](../../../tools/melee-agent/tests/test_scratch.py).
- **Regression:** existing `sync production` tests (if any) still pass after the
  helper extraction; otherwise add one covering the refactored call.

## Out of scope / future

- Production compile/get/permuter via the same auth (would require a
  production-aware client or session adapter).
- Dedupe-before-create for the worktree path.
- Updating an existing production scratch's source from the worktree
  (`scratch sync-from-repo --production`).
