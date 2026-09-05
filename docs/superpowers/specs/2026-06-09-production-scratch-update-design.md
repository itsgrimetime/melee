# Update an existing production scratch in place

- **Date:** 2026-06-09
- **Status:** Designed (approved). Companion to
  [`2026-06-07-production-scratch-create-design.md`](2026-06-07-production-scratch-create-design.md).
- **Component:** `melee-agent scratch create --production`

## Problem

`melee-agent scratch create <func> --production` creates a scratch on production
`https://decomp.me` from the worktree. It is idempotent: if a production scratch
already exists for the function it refuses and points at `--force`:

```
mnDiagram_InputProc already has a production scratch:
  https://decomp.me/scratch/LlxRu
Use --force to create another
```

`--force` only ever **creates another** scratch. There is no way to push fresh
repo state to the *existing* production scratch in place. The user wants to
update `LlxRu`, not spawn a duplicate.

## Current state (audit findings)

- `scratch update <slug> <file>` ([`cli/scratch/__init__.py:574`](../../../tools/melee-agent/src/cli/scratch/__init__.py))
  PATCHes in place via `DecompMeAPIClient.update_scratch()` → `PATCH /api/scratch/{slug}`,
  but it defaults to `get_local_api_url()` and builds cookies from the **per-agent
  local** `cookies.json` (+ env), not the production store. Pointed at production
  it would 403. No `--production` path exists.
- `sync production --force` ([`cli/sync/production.py`](../../../tools/melee-agent/src/cli/sync/production.py))
  **always creates** (`create_and_claim_production_scratch`); `--force` re-creates
  rather than PATCHing. It is also coupled to a running local server. Not a fit.
- `update_scratch(slug, ScratchUpdate(...))` → `PATCH /api/scratch/{slug}` is a
  **general** primitive; `ScratchUpdate` carries `source_code`, `context`,
  `compiler_flags`, etc. ([`client/api.py:353`](../../../tools/melee-agent/src/client/api.py),
  [`client/models.py:176`](../../../tools/melee-agent/src/client/models.py)).
- The production *create* path
  ([`cli/scratch_production.py`](../../../tools/melee-agent/src/cli/scratch_production.py))
  already has every building block the update needs: `_make_production_client`
  (cf_clearance + sessionid + production UA), `_preflight_auth`, `_owner_is_account`,
  `_seed_source_from_repo`, `_build_stripped_context`, and the DB idempotency
  lookup on `functions.production_scratch_slug`. It deliberately uses a **raw httpx
  client** rather than `DecompMeAPIClient` because the latter cannot be pointed at
  the production cookie store.

### Key insight

The update is the create path minus `target_asm` (immutable on an existing
scratch) and minus the POST/claim: resolve the existing slug from the DB, build
the same `source_code` + `context` from the worktree, then `PATCH` it with the
production client already in use for create. The compile endpoint
(`GET /api/scratch/{slug}/compile`, which also saves the score) gives match-%
confirmation, mirroring local `scratch update`.

## Design

### Command surface

Add an `--update` flag to `scratch create` (the production entry point):

```
melee-agent scratch create <func> --production --update [--no-context] [--no-compile] [--dry-run]
```

`--update` PATCHes the existing production scratch in place. No new scratch is
created; `--force` is not involved.

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--update` | off | PATCH the existing prod scratch instead of creating. Production-only. |
| `--no-context` | (refresh on) | Push `source_code` only; leave the scratch's context untouched. |
| `--no-compile` | (compile on) | Skip the post-PATCH compile + match-% report. |
| `--dry-run` | off | Resolve target + build payload, print plan + sizes, do not PATCH. |

### Behavior (`run_production_update`)

A new sibling of `run_production_create` in `cli/scratch_production.py`:

1. **Auth:** `load_production_cookies()`; require `cf_clearance` (else point at
   `sync auth`). Run `_preflight_auth(cookies)` — same cf_clearance / anonymous-
   sessionid checks the create path uses.
2. **Resolve target slug** from the DB (`functions.production_scratch_slug` for
   `<func>`) — the *same* lookup the create idempotency check performs.
   - **No row / no slug → strict error** (exit 1): *"No production scratch for
     `<func>`; run without `--update` to create one."* (`--update` means "I know
     one exists" — no upsert.)
3. **Verify the target still exists and is yours:** `GET /api/scratch/{slug}`.
   - `404` → error: the recorded scratch no longer exists on production; run
     without `--update` to create a new one. (Stale DB slug.)
   - owner is anonymous / unclaimed (`not _owner_is_account(owner)`) → stop early
     (exit 1) with guidance: re-run `sync auth` with a fresh logged-in sessionid,
     then `sync fix-ownership --function <func>`. (A PATCH would 403 anyway; fail
     before the expensive build.)
4. **Build payload from the worktree** (`extract_function` → `func`; error if the
   function is not found in the repo, same as create):
   - `source_code` = `_seed_source_from_repo(func.name, func.file_path, melee_root)`.
     If it returns the `// TODO` stub, warn (we are about to overwrite a real
     scratch with a stub) but proceed — symmetric with create's stub warning.
   - `context` = `_build_stripped_context(func_name, func, melee_root, None)`,
     unless `--no-context`.
   - `target_asm` is **not** sent (immutable). `compiler` / `compiler_flags` are
     **not** changed — the scratch keeps its creation-time compiler config.
5. **`--dry-run`:** print `PATCH {PRODUCTION_DECOMP_ME}/api/scratch/{slug}`, which
   fields will be sent, and their byte sizes. Return without writing.
6. **PATCH:** `_patch_production_scratch(client, slug, payload)` →
   `rate_limited_request(client, "patch", f"/api/scratch/{slug}", json=payload)`.
   - `403` → auth/ownership error with the same `sync auth` / `sync fix-ownership`
     guidance.
   - other non-2xx → `DecompMeAPIError`-style message + exit 1.
7. **Compile + report** (unless `--no-compile`):
   `_compile_production_scratch(client, slug)` →
   `rate_limited_request(client, "get", f"/api/scratch/{slug}/compile")`, parse the
   JSON into `CompilationResult`, compute match-% (`100` when `current_score == 0`,
   else `(1 - current/max) * 100`), print it. On non-200, warn that the PATCH
   succeeded but the compile could not be read (non-fatal).
8. **Record state:** on a successful compile, `db_record_match_score` /
   `db_upsert_scratch(slug, "production", ..., match_percent=...)` /
   `db_upsert_function(func, production_scratch_slug=slug)` — keep the DB's
   production match-% current, mirroring the create + local-update paths.

### Guard rails (in `scratch_create`, before dispatch)

- `--update` **without** `--production` → error pointing at plain `scratch update`
  (the local-server path). Exit 1.
- `--update` **with** `--force` → mutually exclusive (one modifies, one creates).
  Exit 1.
- When `production and update`, route to `run_production_update(...)`; otherwise
  the existing `run_production_create(...)` path is unchanged.
- `--decompile/-d` is irrelevant to update (we pull from the repo, not m2c); it is
  ignored on the update path.

### Code shape

- `cli/scratch_production.py`: add `run_production_update(function_name, melee_root,
  *, refresh_context=True, compile_after=True, dry_run=False)` plus two small
  helpers `_patch_production_scratch` and `_compile_production_scratch`. Reuse all
  existing create helpers. Factor the DB slug lookup the create idempotency check
  inlines into a shared `_existing_production_slug(function_name)` so create and
  update resolve it identically.
- `cli/scratch/__init__.py`: add `--update`, `--no-context`, `--no-compile` options
  to `scratch_create`; add the two guard-rail checks; route to the new function.

## Testing

Unit tests (mock the production httpx client + DB), mirroring create's test style:

1. **Guard rails:** `--update` without `--production` errors; `--update` + `--force`
   errors.
2. **Missing scratch:** `--update` with no `production_scratch_slug` in the DB →
   strict error, no HTTP call.
3. **Stale slug:** DB slug present but `GET /api/scratch/{slug}` → 404 → error.
4. **Ownership block:** owner anonymous → early exit, no PATCH issued.
5. **Dry-run:** builds payload, prints plan + sizes, issues no PATCH.
6. **Happy path:** owned scratch → PATCH carries `source_code` + `context` (and
   omits both `target_asm` and, with `--no-context`, `context`) → compile parsed →
   match-% reported → DB updated.
7. **`--no-compile`:** PATCH issued, no `/compile` GET.

## Out of scope

- Updating `target_asm`, `compiler`, or `compiler_flags` of an existing scratch.
- Upsert (create-on-missing) — `--update` is strict by design.
- A by-slug or by-explicit-file update on production (use the worktree as the
  source of truth, by function name, symmetric with create).
