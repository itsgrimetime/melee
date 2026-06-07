# Production scratch creation from a worktree function

- **Date:** 2026-06-07
- **Status:** Approved (design); revised after grounded multi-lens review
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
   That file already exists on this machine with exactly those three keys and a
   real Firefox UA.

2. **`melee-agent sync production`** ([`cli/sync/production.py`](../../../tools/melee-agent/src/cli/sync/production.py))
   already `POST`s a scratch to `https://decomp.me/api/scratch` using the
   production cookies + matching UA + sessionid + rate-limited transport, and
   claims ownership via the returned `claim_token`. **But it is coupled to a
   running local server**: it fetches the source/context from a *local scratch*
   and exports the target ASM from the local server
   (`export_scratch(target_only=True)` → decomp.me's own disassembled
   `target.s`). With no local server, this path is dead-ended.

3. **`melee-agent scratch create <func>`** ([`cli/scratch.py:153`](../../../tools/melee-agent/src/cli/scratch.py))
   already builds the *entire* scratch payload **directly from the worktree** —
   extracts the target ASM via `extract_function` (`func.asm`), `ninja`-builds
   the per-file `.ctx` context (worktree-aware), strips the function definition
   from the context, detects the compiler — then `POST`s via
   `DecompMeAPIClient.create_scratch()`. It targets `get_local_api_url()` and
   pulls auth from the per-agent `cookies_<id>.json` store, **not** the
   production cookie store.

### Key insight (and its one caveat)

A production scratch needs **no local server**: `scratch create` already builds
the whole payload from the worktree, so `--production` only has to swap the
**destination + auth** and reuse the payload-building.

**Caveat — target ASM format is unverified for production.** `func.asm` is the
worktree's **raw DTK disassembly** (`.include "macros.inc"`, `.fn`/`.endfn`,
`.sym`, `/* addr addr bytes */` comments, `.L_xxxx` labels). Every *proven*
production sync used decomp.me's **own exported `target.s`**, a different format.
The local self-hosted create path *does* submit raw DTK (`scratch.py:292`) and it
worked there, but the self-hosted instance's gc_wii assembler/objdiff config is
not proven identical to production's. So "reuse payload-building unchanged" holds
for *everything except confirming production's gc_wii platform accepts DTK as
`target_asm`.* See **Target-ASM verification gate** below.

### The gap

- `scratch create` calls `get_local_api_url()` **unconditionally** at
  [`scratch.py:170`](../../../tools/melee-agent/src/cli/scratch.py) *before* any
  branching; that helper raises `typer.Exit(1)` ("Could not find local decomp.me
  server") when no local server responds — i.e. the command would abort on the
  exact machine `--production` targets.
- `DecompMeAPIClient` ([`client/api.py:154`](../../../tools/melee-agent/src/client/api.py))
  loads auth from the per-agent `cookies_<id>.json` store (none exist), sends a
  **hardcoded** UA, an `X-API-Client: melee-agent` self-hosted-only header, and
  *persists* server-set `sessionid`/`cf_clearance` back into the per-agent store
  on every create/claim — which would clobber the stored production `sessionid`.
- `scratch create` records DB state as `instance="local"` / `local_scratch_slug`.

## Goals

- `melee-agent scratch create <func> --production` creates a scratch on
  `https://decomp.me` from the current worktree, no local server required.
- Authenticate with stored production credentials and **claim** the scratch so it
  is **owned by the user's decomp.me account** (verified, not assumed).
- Seed the source with the function's **current repo C** (stub fallback).
- Record the result as a production scratch in the state DB.
- Robust against Cloudflare/`403`, rate-limit/`429`, and unbuilt worktrees.

## Non-goals

- Making the entire `DecompMeAPIClient` production-aware (compile/get/etc.
  against production). `--production` is create-only.
- Server-side m2c auto-decompile against production.
- Maintaining the local↔production `slug_map` for the from-worktree path (there
  is no local slug to map).

## Design

### Interface

```
melee-agent scratch create <function_name> --production [--force] [--dry-run]
```

- `--production` forces the destination to `https://decomp.me`
  (`PRODUCTION_DECOMP_ME`) and **skips local-URL detection entirely** (does not
  call `get_local_api_url()`); `--api-url`/`DECOMP_API_BASE` are ignored.
- `--force` allows creating a new prod scratch even when the state DB already has
  a `production_scratch_slug` for this function (default: warn + print existing
  URL + exit without creating a duplicate).
- `--dry-run` performs extraction + context build + payload assembly, then prints
  the target URL + payload summary (name, compiler, flags, source/context/asm
  sizes) **without** `POST`/claim/DB writes. (Note: it still runs
  `extract_function` and the ninja `.ctx` build, so it requires a built
  worktree; it is not a zero-cost seam — see Testing.)
- `--decompile/-d` is **ignored** under `--production` (source is seeded from
  repo C, not m2c). If the user passes `-d`/`--api-url` explicitly with
  `--production`, print a one-line notice that they are ignored.

### Components / units

**Unit A — shared production create+claim helper**
in [`cli/sync/_helpers.py`](../../../tools/melee-agent/src/cli/sync/_helpers.py):

```
async def create_and_claim_production_scratch(prod_client, create_data: dict)
    -> ProductionCreateResult        # (slug, claim_token, claimed: bool)
async def claim_production_scratch(prod_client, slug, token) -> bool   # sub-callable
```

- `create_and_claim_production_scratch`: `POST /api/scratch` via
  `rate_limited_request`; on `201/200` parse `slug` + `claim_token`; if
  `claim_token`, call `claim_production_scratch`. Returns
  `(slug, claim_token, claimed)`.
- `claim_production_scratch`: `POST /api/scratch/{slug}/claim` with body
  `{"token": token}` via `rate_limited_request`; success is HTTP `200` **and**
  response `success == true` (warn otherwise). Returns the bool. (Carved out so
  the claim half is reusable; [`fix_ownership.py`](../../../tools/melee-agent/src/cli/sync/fix_ownership.py)
  uses the same fork-then-claim-with-`{"token": …}` pattern and is a potential
  future consumer.)
- **Errors:** raise a **distinct** `DecompMeAuthError` (subclass of
  `DecompMeAPIError`) on `403`; raise `DecompMeAPIError` on other non-2xx with
  truncated body. `429` is handled by `rate_limited_request` backoff.
- No CSRF token is sent or required — decomp.me disables CSRF for the API
  (`CsrfViewMiddleware` commented out + `disable_csrf`, honored by DRF
  `SessionAuthentication`). **Do not add csrftoken handling.**

**Helper-extraction boundary (refactor of `sync production`).** Only three things
**move** into Unit A: the `POST /api/scratch` ([production.py:386](../../../tools/melee-agent/src/cli/sync/production.py)),
the `201/200` slug parse (389–393), and the claim `POST` (395–416). Everything
else **stays** in `production_command` and runs unchanged around the call:
the pre-search/link-existing block, `dry_run`, `slug_map`, `db_record_sync`,
`db_upsert_scratch`/`db_upsert_function`, `synced[]`, `results` bookkeeping
(418–452), and the failure branches. **Break-on-403 must be preserved:** the
current code `break`s the batch on a create `403` (453–456); after refactor the
caller must `except DecompMeAuthError: … break` so a dead cf_clearance still
stops the batch (the generic `except Exception` at 462–464 keeps `continue`-ing
on ordinary create failures).

**Unit B — pure payload builder**
`build_production_create_data(func, context, source_code, compiler, flags) -> dict`
in `cli/scratch.py` (or a small `cli/scratch_production.py`). No I/O, no network —
fully unit-testable. Produces:
`{name, target_asm, context, compiler, compiler_flags, diff_label, source_code,
platform, diff_flags}` with `platform="gc_wii"` and `diff_flags=[]` set
**explicitly** (matching the proven `sync production` payload at
[production.py:179](../../../tools/melee-agent/src/cli/sync/production.py); the
prod path POSTs a raw dict, so `ScratchCreate`'s field defaults never apply —
omitting `platform` would rely on server-side defaulting, which we avoid by being
explicit). `compiler_flags` reuses the existing local-create default string
([scratch.py:295](../../../tools/melee-agent/src/cli/scratch.py)):
`-O4,p -nodefaults -fp hard -Cpp_exceptions off -enum int -fp_contract on -inline auto`
(note: differs from CLAUDE.md canonical — `-fp hard` not `-fp hardware`, no
`-proc gekko`; reused for consistency with local create since there is no source
scratch to copy flags from — see Open caveats).

**Unit C — `--production` branch in `scratch_create`**
([`cli/scratch.py`](../../../tools/melee-agent/src/cli/scratch.py)). Orchestrates,
reusing existing steps where noted:

0. **Destination:** make [`scratch.py:170`](../../../tools/melee-agent/src/cli/scratch.py)
   conditional — `api_url = PRODUCTION_DECOMP_ME if production else (api_url or
   get_local_api_url())` — so `--production` never triggers local detection.
1. **Auth preflight (before the expensive build):** `load_production_cookies()`;
   if no `cf_clearance` → error → `melee-agent sync auth`; exit. Then a **cheap
   authenticated probe** `GET /api/user` with the *same* prod client config
   (cf_clearance + sessionid + stored UA); on `403` fail fast with the right
   remediation (cf_clearance vs sessionid). Also sanity-check the stored UA is a
   real browser UA (a `python-requests`/`curl` signature makes the server treat
   the session as a throwaway bot → ownership silently fails).
2. **Idempotency:** unless `--force`, check the state DB for an existing
   `production_scratch_slug` for this function; if present, print its URL and exit
   (no duplicate).
3. **Extract + ASM guard:** `extract_function`; **if `not func.asm` → error**
   ("No target ASM for `<func>` — build first: `python configure.py && ninja`,
   or `python tools/worktree-doctor.py --fix` in a fresh worktree") and exit. Do
   **not** POST a null/empty `target_asm`.
4. **Context:** reuse the existing `ninja` `.ctx` build (worktree-aware) +
   function-definition strip. (A fresh worktree may need a build / `orig/GALE01`
   via worktree-doctor first; surface that on ninja failure.)
5. **Source seed:** read `melee_root / "src" / func.file_path` **directly**
   (use the authoritative `func.file_path`; do *not* re-resolve via
   `get_file_path_from_function`, which does a slower full-tree rglob and can
   disagree for file-local statics). Extract with `_extract_function_from_code`
   ([commit/update.py:75](../../../tools/melee-agent/src/commit/update.py));
   `None` → `// TODO: Decompile this function\n` stub + warn.
6. **Compiler:** reuse `get_compiler_for_source`.
7. **Payload:** `build_production_create_data(...)` (Unit B).
8. **Prod client:** `httpx.AsyncClient(base_url=PRODUCTION_DECOMP_ME)` with
   cookies `cf_clearance` + `sessionid`, headers `User-Agent =
   get_production_user_agent()` + `Accept: application/json`,
   `follow_redirects=True`, `timeout≈60s`. **No `X-API-Client` header.**
9. **Create + claim:** Unit A. Persist the `claim_token` via
   `_save_scratch_token(slug, token)` so a later re-claim is possible.
10. **Verify ownership:** `GET /api/scratch/{slug}`; if `owner` is `None`, warn
    loudly (scratch created but **not** owned — sessionid likely expired;
    re-run `sync auth`, then `melee-agent sync fix-ownership --function <func>`).
11. **DB bookkeeping:** `db_upsert_scratch(slug, instance="production",
    base_url=PRODUCTION_DECOMP_ME, function_name=...)` and
    `db_upsert_function(func, production_scratch_slug=slug,
    status="in_progress")` (status added for symmetry with local create). Print
    `https://decomp.me/scratch/<slug>`.

The default (local) branch is unchanged.

### Target-ASM verification gate

Because raw-DTK acceptance on production's gc_wii platform is unverified, the
implementation plan must **empirically confirm it before relying on it**:

1. First real run: create one `--production` scratch for a known function and
   confirm production returns a scratch whose compile yields a *score* (i.e. it
   assembled the DTK `target_asm`), not an assembler error.
2. **If production rejects DTK** (e.g. unknown `.fn`/`macros.inc`), convert
   `func.asm` with the existing
   [`convert_dtk_disasm_to_objdump`](../../../tools/melee-agent/src/mwcc_debug/dtk_objdump.py)
   (`dtk_objdump.py:25`) and submit the objdump-style text instead; make Unit B
   take the converted ASM. This is a contingency, scoped but not built unless the
   gate fails.

### Ownership (corrected)

A newly created scratch is **always created unowned/claimable**; sending
`sessionid` at create time does **not** confer ownership. Ownership is granted
**only** by the claim step (`owner` = profile resolved from the `sessionid`
session). Therefore **the claim is mandatory**, the UA must be a real browser UA
(bot UAs make profile resolution fail silently), and success must be *verified*
(step 10). `fix_ownership.py` exists precisely because this create+claim flow has
historically left scratches unowned; the claim-session-replacement WORKAROUND in
[`api.py:338`](../../../tools/melee-agent/src/client/api.py) applies to the
*anonymous self-hosted* flow, not the logged-in production case (so create-only
correctly does **not** persist the returned session).

### Error handling

| Condition | Behavior |
|-----------|----------|
| No `cf_clearance` in prod cookies | Error → run `melee-agent sync auth`; exit |
| Preflight `GET /api/user` 403 | Fail fast (before build): cf_clearance/sessionid expired → `sync auth`; exit |
| UA looks like a bot (curl/requests) | Warn: ownership will fail; fix UA via `sync auth` |
| DB already has `production_scratch_slug` (no `--force`) | Print existing URL; exit without duplicate |
| `not func.asm` (unbuilt worktree) | Error: build first (`ninja` / `worktree-doctor --fix`); do **not** POST |
| ninja `.ctx` build fails | Existing exit path; hint `worktree-doctor --fix` for fresh worktrees |
| Function has no repo C | Seed `// TODO` stub + warning; still create |
| Create-path `403` | `DecompMeAuthError`: Cloudflare/cf_clearance expired → `sync auth`; exit |
| Claim-path `403` / `success=false` / owner `None` | Loud warning: created but **not owned** → `sync auth` then `sync fix-ownership --function <func>` |
| `429` | `rate_limited_request` exponential backoff |

## Testing

- **Unit B (pure):** `build_production_create_data` from fixtures — asserts field
  names/values, explicit `platform="gc_wii"`, repo-C seeding vs stub fallback. No
  ninja, no network.
- **Unit A (mock transport):** a **new** `httpx.MockTransport` harness (none
  exists today — `tests/test_client.py` is live-backend-or-skip, `test_scratch.py`
  is pure model/regex). Cover: create→claim happy path returns
  `(slug, token, claimed=True)`; create `403` raises `DecompMeAuthError`;
  claim `success=false` → `claimed=False`; `429`-then-`201` succeeds via backoff.
- **Regression (new):** a `sync production` test asserting the refactor is
  behavior-identical, specifically **a create-path `403` still `break`s the
  batch** (does not continue hammering with a dead cookie).
- **Manual gate:** the Target-ASM verification gate above (one real prod create,
  confirm a score).

## Open caveats (disclosed, not blocking)

- **compiler_flags** reuse the local-create default (`-fp hard`, no `-proc
  gekko`), which diverges from CLAUDE.md canonical. Acceptable for parity with
  local create; if produced scratches must reproduce melee's exact build codegen,
  a follow-up can derive flags from the build config per TU.
- **Idempotency** is DB-based (`production_scratch_slug`) + `--force`; a
  create-201-then-claim-fail still leaves one unowned scratch (mitigated by the
  loud warning + saved claim_token + `fix-ownership`).
- **Latency:** `rate_limited_request` sleeps ~1s after each call, so create+claim
  adds ~2s — fine for an interactive single create.

## Out of scope / future

- Production compile/get/permuter via the same auth.
- Updating an existing production scratch's source from the worktree
  (`scratch sync-from-repo --production`).
- DTK→objdump conversion is built **only if** the verification gate fails.
