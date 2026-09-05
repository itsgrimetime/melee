# Terminal Attempt Taxonomy Design

> **SUPERSEDED — feature removed 2026-06-07.** This design described an overlay
> that demoted functions the attempt ledger marked as source-ceiling /
> tooling-blocked / diagnostic-only / manual-review. That overlay has been made
> inert (`load_terminal_attempt_evidence` returns nothing; rows are never
> demoted) because the ledger must never tell agents a function is a dead end.
> Kept for historical design context only.

## Problem

Function taxonomy queues currently describe only the latest static checkdiff
classification. They can keep advertising executable lanes such as
`pcdump-proof-needed`, `current-tools-indexed-pointer`, `structural-rebuild`, or
manual inline guidance after the attempt ledger has already recorded terminal
evidence for the same function. That sends harvest campaigns back into rows that
are known to be source ceilings, tooling blockers, diagnostic-only PAD_STACK
evidence, or manual-review cases.

Issue #507 names these concrete failures:

- `mnDiagram_OnFrame`: pcdump-proof-needed remains visible after
  allocator-target-conflict evidence.
- `mnDiagram_8023FA6C` and `mnDiagram2_GetRankedName`:
  current-tools-indexed-pointer remains visible after
  no-safe-materialized-pointer and move-on evidence.
- `fn_802461BC`: structural/opseq lanes remain visible after cleanup-loop probes
  tied or regressed and the ledger records source-ceiling.
- `mnDiagram_802427B4`: generator/manual-inline lanes remain visible after
  repeated PAD_STACK-only and neutral helper evidence.

## Design

Add a shared terminal attempt evidence layer under `tools/melee-agent/src`. It
loads the attempt ledger, finds the latest active terminal evidence for each
function, and returns an overlay that can be applied to taxonomy rows. The
overlay preserves `work_bucket`, `primary`, and `subcategory` so existing queue
filenames and bucket summaries remain stable. It rewrites only actionability
metadata:

- `source_actionability`: `source-ceiling`, `tooling-blocked`,
  `diagnostic-only`, or `manual-review`.
- `headline_tool`: `attempt-ledger`.
- `next_command`: `melee-agent attempts show <function> --no-measure-current`.
- `actionability_reason`: short explanation that includes the ledger blocker
  and the original advertised lane.
- `terminal_attempt_*` fields: status, blocker, actionability, attempt index,
  timestamp, move-on state, stale check, and original lane metadata.

Terminal evidence is active when it appears after the latest retained or
progress attempt, or when the ledger currently recommends move-on. Known blocker
mapping:

- `allocator-target-conflict`, `allocator-force-vector-no-match`,
  `no-safe-materialized-pointer`, malformed candidate, and unsupported tool
  blockers map to `tooling-blocked`.
- `source-ceiling`, negative role-shape probes, no-improvement search results,
  and repeated tied/regressed no-source-retained probes map to
  `source-ceiling`.
- PAD_STACK-only diagnostic evidence maps to `diagnostic-only`.
- Move-on evidence without a specific mapped blocker maps to `manual-review`.

Freshness is conservative and is evaluated at the point the row is overlaid. If
an attempt records comparable tooling metadata such as `tool_sha256`,
`row_tool_sha256`, `tooling_sha256`, or a tooling commit and the current value
for the same key differs, the evidence is marked stale and does not rewrite the
row. Fingerprint keys are never compared across categories: `tool_sha256`
compares only with current `tool_sha256`, while `row_tool_sha256` compares only
with current `row_tool_sha256`. Harvest passes the keyed fingerprint map that it
already computes for rebucket fingerprints; inventory passes a keyed helper
fingerprint for rows where per-row tool metadata is unavailable. If no
comparable tooling metadata exists, the evidence remains active and the row
records `terminal_attempt_stale_check=no-tooling-fingerprint`.

## Integration

Inventory generation applies the overlay after checkdiff classification and
before writing `taxonomy.records.*` and queue TSVs. Queue and CSV columns include
the `terminal_attempt_*` fields so previews can explain why a row is no longer
executable.

Harvest preview and loading apply the same overlay to raw queue rows after
existing harvest-ledger source-actionability rebuckets and before filtering,
sampling, or applying `limit`. This protects stale or ad-hoc queue files that
were generated before the taxonomy overlay existed. Active terminal rows are
excluded by default from `load_queue_rows` and `preview_harvest_queue`, with an
`include_terminal_attempts` option for diagnostics. Previews expose suppressed
counts and terminal facets so users can tell whether rows were excluded because
of terminal evidence.

`select_harness` treats `source-ceiling`, `tooling-blocked`, `manual-review`,
and active terminal-attempt `diagnostic-only` rows as non-executable. A
diagnostic row produced by other harvest rebucket logic can keep its existing
behavior; terminal overlay rows are identified by `terminal_attempt_status`.

## Testing

Regression tests cover three layers:

- Shared terminal evidence helper classifies move-on, known blockers,
  post-progress terminal evidence, stale tooling metadata, and no-fingerprint
  legacy evidence.
- Inventory generation writes terminal columns and rewrites executable lanes
  for functions with active terminal ledger evidence.
- Harvest preview/load applies the overlay to stale queue TSVs, excludes active
  terminal rows before filters and limits, reports terminal counts/facets, can
  include terminal rows for diagnostics without selecting a harness, and keeps a
  row eligible when comparable attempt tooling metadata is stale against the
  current row/tool fingerprint.

## Non-Goals

This change does not reshape taxonomy bucket names, add new queue files, mutate
attempt ledger records, or infer exact human intent from every free-form note.
It only recognizes the terminal blocker patterns needed by issue #507 and keeps
the mapper easy to extend.
