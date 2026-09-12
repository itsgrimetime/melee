# Issue 1116: Control-Flow Shape Retained Probes

## Root Cause

`debug suggest control-flow-shape` identified concrete `fn_80247510` source-shape families (`pointer-base-call-loop`/call-hoist, `pointer-walk-loop`, and `loop-init`) but the follow-up `debug mutate control-flow-shape-search` path only delegated to generic source scanners. When those generic scanners found no exact source pattern, the tooling collapsed all families into a bare `no-control-flow-shape-probes` blocker.

That left the matcher without either retained scored C probes or a concrete terminal proof for why each suggested source family could not be materialized.

## Plan

- Extend the existing control-flow-shape workflow, not a new broad search CLI.
- Add suggestion-aware materialization that returns per-family `family_results`, bounded retained `LifetimeLayoutProbe`s, and `terminal_proof` records.
- Materialize reusable probe families for:
  - call-hoist evidence, including retained call-site probes plus terminal proof for unsafe true pre-loop hoists;
  - pointer-walk/indexed member-array loops, including index-table and member-array probes;
  - loop-init/loop-peel suggestions, including init-outside-for and renamed block-local counter probes.
- Preserve `family_id`, `suggestion_kind`, `source_hunks`, retained source, retained pcdump, compact checkdiff, and baseline deltas through `debug mutate control-flow-shape-search`.
- Keep target scoring optional; #1116 has no target register map, so the default success path is retained candidates with checkdiff/baseline deltas or terminal proof per family.

## Verification

Regression coverage should include the reusable materializer, suggestion annotation, CLI JSON family output, terminal-only output, baseline deltas, and the help snapshot for the new options.

Reporter smoke should use the supplied `fn_80247510_current_checkdiff.json` baseline artifact because the reporter worktree was dirty during investigation.
