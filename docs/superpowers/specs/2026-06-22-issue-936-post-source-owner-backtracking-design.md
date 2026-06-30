# Issue 936: Post Source-Owner Backtracking Design

## Context

Issue #935 made retained Case-C window-order continuation carry the IG34
copy/coalesce-product probe from select-order JSON into `plan-transforms`.
The matcher then scored that exact retained candidate and found it negative:
IG34 stayed at r29 and IG44 moved to r27. The current allocator-ceiling output
therefore reports `residual-case-c-source-repair-exhausted`, but the tooling
does not yet provide a bounded next step after the first attributed source
owner is exhausted.

The fresh select-order payload already contains the data needed for a bounded
backtracking step. For IG34, rank 2 materialized the current indexed-byte owner:

`sorted_names_totals_idx_probe = mnDiagram_804A076C.sorted_names[(max_idx)];`

Later ranked indexed-byte candidates were rejected only because the default
window-order continuation lane permits one ranked indexed-byte materialization
per target. That is correct for the first continuation, but too strict after a
negative score proves the current owner path is exhausted.

## Approaches

1. Add a new CLI command for post-exhaustion backtracking.

   This would make the workflow explicit, but it would duplicate
   `plan-transforms` source resolution, probe writing, validation, JSON
   summaries, and ledger handling.

2. Extend the existing window-order continuation family to emit later ranked
   candidates when `--max-per-family` is greater than one.

   This is small, but it changes the default family semantics and can make the
   first continuation lane noisier for agents that only want the top source
   owner.

3. Add an opt-in transform family under `debug search plan-transforms`.

   This keeps the CLI surface stable, reuses source resolution and remote
   validation, keeps the #935 continuation lane unchanged, and gives matchers a
   clear family to invoke after allocator-ceiling reports current-owner
   exhaustion.

Approach 3 is the chosen design.

## Design

Add a transform family named
`retained_gpr_case_c_post_source_owner_backtrack`. The family is available only
when `--select-order-json` is provided, just like the retained window-order and
target-live-range continuations. It is included in the default select-order
family set after the first continuation lanes, and can also be requested
directly with `--transform-family`.

The family reuses `plan_window_order_source_probes`, but asks it to materialize
more than one ranked indexed-byte candidate per target. Default behavior stays
unchanged: existing callers still get one ranked indexed-byte materialization
per target. The post-exhaustion family calls the planner with a higher
per-target limit and then filters out the first safe ranked indexed-byte
candidate for each target, because that is the current source-owner lane that
has already been scored negative.

The remaining probes become ranked alternate source-owner/frontier candidates.
Their payloads preserve:

- target/protected force-phys split
- original source attribution and copy-product chain metadata
- `post_source_owner_backtrack` metadata with candidate rank, span text, and
  skipped current-owner labels
- the normal `target_score` evidence when `--validate-command` is used

If no alternate probe can be emitted, the family reports an explicit terminal
blocker:

- `no-alternate-source-owner` when the planner has evidence but no later safe
  source-owner candidate
- `post-source-owner-exhausted` when all selected alternates are no-ops,
  duplicates, or budget-starved

## Non-Goals

- Do not invent a separate remote-scoring mechanism. Existing
  `--validate-command` remains the scoring path.
- Do not claim a source match. This feature only provides bounded alternate
  candidates with evidence or an explicit terminal blocker.
- Do not change the current #935 window-order continuation output for agents
  that request only the first retained source-owner handoff.
