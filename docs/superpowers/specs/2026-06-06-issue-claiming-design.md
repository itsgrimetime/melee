# Cooperative Issue Claiming — Design

**Date:** 2026-06-06
**Status:** Approved (design)
**Component:** `melee-agent issue` (shared tooling issue queue)

## Problem

The shared tooling issue queue (`melee-agent issue list`, backed by the
`tool_issues` table in `~/.config/decomp-me/agent_state.db`) has only two
states: `open` and `resolved`. With multiple parallel agents now draining the
queue, two agents can independently pick the same open issue and implement it
twice — wasted, conflicting work.

We need a **simple but effective** way for an agent to signal "I am working on
this" before it starts, visible to other agents, so they pick something else.

## Goals

- An agent can atomically claim an open issue; a concurrent claim by another
  agent fails loudly.
- Other agents can see who claimed what, and can filter the list to only
  grabbable (unclaimed) work.
- Recovery from an abandoned claim is a single explicit command (no silent
  permanent lock).

## Non-goals

- **No TTL / auto-expiry.** Claims are released manually (or cleared on
  resolve). Decided explicitly — keeps the schema and semantics minimal. The
  crashed-agent recovery path is `release --force` / `claim --force`, not a
  timer.
- No assignment/queueing, priorities, or per-agent work limits.
- No change to the `report` / `note` / `resolve` / `campaign-report` surface
  beyond clearing the claim on resolve.

## Decisions (from brainstorming)

1. **Manual release only** — no expiry columns, no heartbeat.
2. **Claimed-by-others stay visible**, annotated with the owner; a new
   `--available` filter narrows `list` to unclaimed open issues.

## Approach: claim as orthogonal columns, not a new status

`tool_issues.status` is a SQLite `CHECK(status IN ('open','resolved'))`. SQLite
cannot `ALTER` a `CHECK`, so introducing a `'claimed'` *status* value would
require dropping and recreating the table (as migration `1 → 2` had to do for
the `functions` table). It would also conflate *assignment* ("who is working
on it") with *lifecycle* ("is it done") — a claimed issue is still
fundamentally **open**.

Instead, claiming is modeled as two nullable columns orthogonal to `status`,
mirroring the existing function-claim pattern (`claims` table +
`add_claim`/`release_claim`):

```sql
ALTER TABLE tool_issues ADD COLUMN claimed_by TEXT;
ALTER TABLE tool_issues ADD COLUMN claimed_at REAL;
```

Both are additive `ALTER TABLE … ADD COLUMN` statements — no table recreate.

**Claimed predicate:** an issue is "claimed" iff `claimed_by IS NOT NULL` and
`status = 'open'`. Claims are advisory/cooperative: they do not hard-lock the
row; `--force` always provides an override.

*Rejected alternative — new `status` value:* heavier recreate migration, worse
semantics (loses the open-vs-claimed distinction; `list --status open` would
stop showing in-flight work). Not chosen.

## Schema migration

How the runner works (`_init_schema` / `_run_migrations` in `db/__init__.py`):
a **fresh** DB executes the canonical `SCHEMA_SQL` once and stamps
`schema_version = SCHEMA_VERSION` (migrations are **not** run); an **existing**
DB applies `migrations[v]` for each `v` in `range(current_version,
SCHEMA_VERSION)`. This dictates exactly which DDL gets the new columns:

- `SCHEMA_VERSION`: `9 → 10`.
- **Canonical `CREATE TABLE tool_issues` in `SCHEMA_SQL` (near line 172):** ADD
  the two columns here. This is the only DDL a fresh DB ever sees.
  ```sql
  claimed_by TEXT,
  claimed_at REAL,
  ```
- **New migration entry keyed `9`** in `get_migrations()`:
  ```sql
  ALTER TABLE tool_issues ADD COLUMN claimed_by TEXT;
  ALTER TABLE tool_issues ADD COLUMN claimed_at REAL;
  ```
- **Do NOT touch the version-8 migration's embedded `CREATE TABLE IF NOT EXISTS
  tool_issues` (near line 796).** It is the frozen v9 shape. On the 8 → 10
  upgrade path the runner executes `migrations[8]` (this embedded create,
  *without* the claim columns) and then `migrations[9]` (the `ALTER`s); if the
  embedded create already had the columns, the `ALTER ADD COLUMN` would fail
  with a duplicate-column error. Leaving it frozen makes 8→10 and 9→10 both
  land on the same final shape.
- No index needed; claim lookups are by primary key `id`, or full-table scans
  already bounded by the existing `LIMIT`.
- `INITIAL_META` needs **no** edit — its `schema_version` entry derives from
  `str(SCHEMA_VERSION)` dynamically (`schema.py:350`). Bumping `SCHEMA_VERSION`
  is sufficient; do not hardcode the version anywhere else.

## Concurrency / locking (must-handle)

The claim must be race-safe against two agents claiming the same issue at once.
The relevant infrastructure, verified in `db/__init__.py`:

- `connection()` (`:83-100`) opens the thread-local connection in autocommit
  (`isolation_level=None`), WAL mode, `foreign_keys=ON` — **but sets no
  `busy_timeout`.**
- `transaction()` (`:102-112`) wraps the body in `BEGIN IMMEDIATE … COMMIT`.

`BEGIN IMMEDIATE` takes the database write lock at `BEGIN` time, so a
read-then-write inside the transaction (SELECT current claim → decide → UPDATE)
**is** serializable: once a writer holds the lock, no other writer can have
committed between its `BEGIN` and its `SELECT` (WAL snapshot + exclusive write
lock). There is no lost-update once a writer is in.

**The real hazard** is the *loser* of the race: with no `busy_timeout`, a second
concurrent `BEGIN IMMEDIATE` fails immediately with
`sqlite3.OperationalError: database is locked` instead of blocking. That would
surface to the agent as a stack trace / exit 1 — **not** the intended
`ValueError("already claimed … use --force")` / exit 2. So "concurrent claim
fails loudly" is only met by accident, with the wrong error.

**Fix (required):** set `PRAGMA busy_timeout = 5000` in `connection()` right
after the WAL pragma. The loser then blocks until the winner commits, re-reads
under its own `BEGIN IMMEDIATE`, sees the claim, and returns the correct
`ValueError`. This is a one-line, globally-beneficial change (every writer in
this DB currently shares the same latent gap — `add_claim` (`:167`) included, so
it is *not* a clean correctness precedent to copy without this). Claim/release
transactions are tiny, so 5 s is ample headroom and effectively never reached.

Defense-in-depth (optional, low priority): the CLI may also translate a residual
`OperationalError` into a clean "issue queue is busy, retry" message, but with
`busy_timeout` set this path is not expected to trigger.

## DB methods (`StateDB`, beside the other `*_tool_issue` methods)

Same return/raise conventions as `note_tool_issue` / `resolve_tool_issue`:
return the updated issue dict, `None` if the issue id does not exist, raise
`ValueError` for invalid state transitions.

All three keep the `log_audit(...)` call **inside** the `with self.transaction()`
block (as `report`/`resolve`/`note` already do — `log_audit` reuses the same
thread-local connection, so it commits atomically with the row change). Use
entity_type **`tool_issue`** (never `claim`, which is the separate
function-claim namespace queried by `v_active_claims`).

### `claim_tool_issue(issue_id, agent_id, force=False) -> dict | None`

Single `with self.transaction()` block (serializable per Concurrency above):
- issue not found → `None`.
- `status != 'open'` → `ValueError("cannot claim resolved issue #<id>")`.
- already `claimed_by` a **different** agent and not `force` →
  `ValueError("issue #<id> already claimed by <agent>; use --force to take over")`.
- otherwise set `claimed_by = agent_id`, `claimed_at = now`, `updated_at = now`.
  Same-agent re-claim is an idempotent refresh of `claimed_at`.
- `log_audit("tool_issue", id, "claimed", agent_id=agent_id, old_value=<prev row>,
  new_value=<new row>)`. The `old_value` MUST capture the prior `claimed_by` so a
  `--force` takeover records who was displaced.

### `release_tool_issue(issue_id, agent_id, force=False) -> dict | None`

- issue not found → `None`.
- not claimed (`claimed_by IS NULL`) → `ValueError("issue #<id> is not claimed")`.
- claimed by a **different** agent and not `force` →
  `ValueError("issue #<id> claimed by <agent>; use --force to release")`.
- otherwise clear `claimed_by`/`claimed_at`, set `updated_at = now`.
- `log_audit("tool_issue", id, "released", agent_id=agent_id,
  old_value=<prev row>, new_value=<new row>)` (records the displaced owner on
  `--force`).

A `release` guard on `claimed_by IS NULL` alone is sufficient and consistent
with the claimed-predicate: resolved rows are *always* `claimed_by IS NULL`
(resolve clears the claim, below), and no resolved row can carry a stale claim
because the feature is new — so release-on-resolved naturally hits the "not
claimed" path. No separate `status` check is needed in `release`.

### `resolve_tool_issue` (modify existing)

On resolve, also clear `claimed_by`/`claimed_at` (a resolved issue is never
"claimed"). This is the authoritative invariant: `status='resolved'` ⇒
`claimed_by IS NULL`. No signature change.

### `note_tool_issue` (no change, but pin behavior)

`note` is **not** ownership-gated and works on a claimed issue (a claimed issue
is still `open`, and `note_tool_issue` only rejects `status='resolved'`). Any
agent may add a note to an issue claimed by someone else. State and test this so
the behavior is intentional rather than incidental.

`_decode_tool_issue_row` needs no change — it is `dict(row)` plus functions
parsing, so the two new columns flow through automatically into every returned
dict and into every `--json` payload (including `campaign-report`). This is
additive; verified that the existing tests assert individual keys, not
whole-dict equality, so the extra keys do not break them — re-confirm during
implementation.

## CLI (`issue_app` in `src/cli/issue.py`)

Error handling must follow **`note_command`'s** pattern, not `resolve_command`'s:
wrap the DB call in `try/except ValueError` → red + `raise typer.Exit(2)`.
(`resolve_command` has no such wrapper because `resolve_tool_issue` never raises;
`claim`/`release` *do* raise, so the `note` pattern is the correct model.)

### `melee-agent issue claim <id> [--force] [--agent-id] [--json]`

Resolves `agent_id` via the existing `_get_agent_id()` when omitted. On success
prints `Claimed issue #<id> (<agent>)`. On `ValueError` prints red and exits 2.
`None` → "Issue not found" exit 1. `--json` echoes the updated issue.

### `melee-agent issue release <id> [--force] [--agent-id] [--json]`

Symmetric to claim; prints `Released issue #<id>`.

**Agent-id caveat:** `_get_agent_id()` (`api.py:17-40`) always returns a string,
but with neither `DECOMP_AGENT_ID` nor `TERM_SESSION_ID` set it falls back to a
**per-process `pid<pid>`** that changes every CLI invocation. In that
environment same-agent idempotent re-claim and non-owner detection are
meaningless (each call looks like a new agent). Claiming is only reliable when a
stable `DECOMP_AGENT_ID`/`TERM_SESSION_ID` is set — which is the parallel-agent
case this feature targets. Tests MUST pass explicit `--agent-id` (as the
existing issue tests do) rather than rely on the fallback.

### `issue list` (modify)

- New **Claimed** column rendering `claimed_by` or `-`. To keep the now-7-column
  table readable, trim `Summary`/`Functions` `max_width` (e.g. Summary 48,
  Functions 22) or accept wrapping. The `--json` path is unaffected (raw dict).
- New boolean flag spelled `--available` (alias `--unclaimed`) → maps to a new
  `unclaimed_only: bool = False` param on `list_tool_issues`, appended to the
  query as `AND claimed_by IS NULL`. DB-level (not CLI post-filter) so `--json`
  and the table render identically. **Interaction with `--status`:**
  `unclaimed_only` simply ANDs onto whatever status filter is active (default
  `open`). `--status resolved --available` is harmless — resolved rows are always
  NULL-claim, so it just returns resolved issues.
- Default `list` is unchanged except for the new column (claimed-by-others stay
  visible, annotated).

### `issue show` (modify)

When `claimed_by` is set, print `Claimed by: <agent>` (and a human-readable
`claimed_at` timestamp, formatted like `note`'s stamp).

## Workflow this enables

```
melee-agent issue list --available     # see only grabbable open issues
melee-agent issue claim <id>           # atomically take it (fails if taken)
# ... work ...
melee-agent issue resolve <id> --note  # auto-clears the claim
#   or
melee-agent issue release <id>         # give it back without resolving
```

Recovery for a crashed/abandoned claim (no TTL):
`melee-agent issue release <id> --force` or `melee-agent issue claim <id> --force`.

## Testing (`tools/melee-agent/tests/test_issues.py`)

Extend the existing `CliRunner` + `reset_db()` + `get_db(tmp_path/"state.db")`
pattern:

All tests pass explicit `--agent-id` (per the agent-id caveat above).

1. **claim then list** — claim shows owner in `list` table output and in `--json`.
2. **conflict** — second agent's `claim` fails (exit 2), message names the
   owner and mentions `--force`.
3. **force takeover** — `claim --force` by a second agent succeeds, `claimed_by`
   updates; assert the audit row's `old_value` records the displaced owner.
4. **`--available` filter** — hides issues claimed by others, shows unclaimed;
   assert `--available` returns the same rows in `--json` and table mode, and
   that *default* `list` still shows claimed-by-others (FIXED decision #2).
5. **release** — clears the claim; releasing an unclaimed issue errors;
   non-owner release errors without `--force`, succeeds with it.
6. **resolve clears claim** — resolving a claimed issue nulls `claimed_by`
   (asserts the `status='resolved' ⇒ claimed_by IS NULL` invariant).
7. **cannot claim resolved** — claiming a resolved issue errors.
8. **note on claimed issue** — a *different* agent can `note` a claimed (open)
   issue successfully (locks in the not-ownership-gated behavior).
9. **migration upgrade (MANDATORY)** — DB-level: build a real v9 DB (set
   `db_meta.schema_version = '9'` with a `tool_issues` table lacking the claim
   columns, or reuse the v8 path), instantiate `StateDB` to trigger
   `_run_migrations`, and assert: the two columns now exist and are NULL on a
   pre-existing row, **and** `PRAGMA table_info(tool_issues)` is identical
   between a freshly-created (`SCHEMA_SQL`) DB and the migrated DB. This is the
   highest-risk change and is not optional. Follow the `StateDB(tmp_path/…)`
   DB-level pattern already used in `tests/test_db.py`.

Real cross-process concurrency is not deterministically reproducible in the
single-threaded `CliRunner` harness; test #2 covers the logical conflict path,
and correctness under genuine contention rests on the `busy_timeout` fix
(Concurrency section). Note that in the plan.

## Files touched

- `tools/melee-agent/src/db/schema.py` — bump `SCHEMA_VERSION` to 10, add
  migration `9` (two `ALTER`s), add the two columns to the **canonical**
  `CREATE TABLE` only (leave the migration-8 embedded create frozen).
- `tools/melee-agent/src/db/__init__.py` — add `PRAGMA busy_timeout = 5000` to
  `connection()`; add `claim_tool_issue` / `release_tool_issue`; modify
  `resolve_tool_issue` (clear claim); add `unclaimed_only` param to
  `list_tool_issues`.
- `tools/melee-agent/src/cli/issue.py` — `claim` + `release` commands (note-style
  error handling), `list` column + `--available/--unclaimed`, `show` annotation.
- `tools/melee-agent/tests/test_issues.py` — new tests (incl. mandatory
  migration test; may live in `tests/test_db.py` if that better matches the
  DB-level harness).
- `CLAUDE.md` — add `issue claim` / `issue release` / `issue list --available`
  to the Tooling Feedback command list, with a one-line note on the
  `release --force` recovery path (no TTL).
