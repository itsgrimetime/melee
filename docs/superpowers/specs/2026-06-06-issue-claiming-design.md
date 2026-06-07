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

## DB methods (`StateDB`, beside the other `*_tool_issue` methods)

Same return/raise conventions as `note_tool_issue` / `resolve_tool_issue`:
return the updated issue dict, `None` if the issue id does not exist, raise
`ValueError` for invalid state transitions.

### `claim_tool_issue(issue_id, agent_id, force=False) -> dict | None`

Atomic within `transaction()`:
- issue not found → `None`.
- `status != 'open'` → `ValueError("cannot claim resolved issue #<id>")`.
- already `claimed_by` a **different** agent and not `force` →
  `ValueError("issue #<id> already claimed by <agent>; use --force to take over")`.
- otherwise set `claimed_by = agent_id`, `claimed_at = now`, `updated_at = now`.
  Same-agent re-claim is an idempotent refresh of `claimed_at`.
- `log_audit("tool_issue", id, "claimed", ...)`.

### `release_tool_issue(issue_id, agent_id, force=False) -> dict | None`

- issue not found → `None`.
- not claimed (`claimed_by IS NULL`) → `ValueError("issue #<id> is not claimed")`.
- claimed by a **different** agent and not `force` →
  `ValueError("issue #<id> claimed by <agent>; use --force to release")`.
- otherwise clear `claimed_by`/`claimed_at`, set `updated_at = now`.
- `log_audit("tool_issue", id, "released", ...)`.

### `resolve_tool_issue` (modify existing)

On resolve, also clear `claimed_by`/`claimed_at` (a resolved issue is never
"claimed"). No signature change.

`_decode_tool_issue_row` needs no change — it is `dict(row)` plus functions
parsing, so the two new columns flow through automatically.

## CLI (`issue_app` in `src/cli/issue.py`)

### `melee-agent issue claim <id> [--force] [--agent-id] [--json]`

Resolves `agent_id` via the existing `_get_agent_id()` when omitted. On success
prints `Claimed issue #<id> (<agent>)`. On `ValueError` prints red and exits 2,
mirroring `note`/`resolve`. `None` → "Issue not found" exit 1.

### `melee-agent issue release <id> [--force] [--agent-id] [--json]`

Symmetric to claim; prints `Released issue #<id>`.

### `issue list` (modify)

- New **Claimed** column rendering `claimed_by` or `-`.
- New `--available` / `--unclaimed` boolean flag → only open issues with
  `claimed_by IS NULL`. Implemented **at the DB level** as a new
  `unclaimed_only: bool = False` param on `list_tool_issues`, appended to the
  query as `AND claimed_by IS NULL`. DB-level (not CLI post-filter) so `--json`
  and the table render identically.
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

1. **claim then list** — claim shows owner in `list` output and in `--json`.
2. **conflict** — second agent's `claim` fails (exit 2), message names the
   owner and mentions `--force`.
3. **force takeover** — `claim --force` by a second agent succeeds, `claimed_by`
   updates.
4. **`--available` filter** — hides issues claimed by others, shows unclaimed.
5. **release** — clears the claim; releasing an unclaimed issue errors;
   non-owner release errors without `--force`, succeeds with it.
6. **resolve clears claim** — resolving a claimed issue nulls `claimed_by`.
7. **cannot claim resolved** — claiming a resolved issue errors.

Plus a DB-level migration test (optional): an existing v9 DB upgrades to v10
and gains the two columns with NULL defaults on existing rows.

## Files touched

- `tools/melee-agent/src/db/schema.py` — bump `SCHEMA_VERSION` to 10, add
  migration `9` (two `ALTER`s), add the two columns to the **canonical**
  `CREATE TABLE` only (leave the migration-8 embedded create frozen).
- `tools/melee-agent/src/db/__init__.py` — `claim_tool_issue`,
  `release_tool_issue`, `resolve_tool_issue` (clear claim).
- `tools/melee-agent/src/cli/issue.py` — `claim` + `release` commands, `list`
  column + `--available`, `show` annotation.
- `tools/melee-agent/tests/test_issues.py` — new tests.
- `CLAUDE.md` — add `issue claim` / `issue release` / `issue list --available`
  to the Tooling Feedback command list.
