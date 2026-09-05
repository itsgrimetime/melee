# Issues #1111/#1112 Sort Continuation and Frontier Handoff Plan

## Root Cause

Two Sort tooling reports share a retained full-unit evidence contract boundary.

Issue #1111 is a source-model continuation routing bug. The whole-function Sort
continuation correctly names
`sort-helper-extraction-data-layout-or-cross-function-rewrite` as the active
next family, but the payload also carries zero-candidate
`continuation-exhausted` placeholder rows for later families. The helper/data
layout generator currently treats that placeholder as real exhaustion and
falls back to older Sort families.

Issue #1112 is a direct score artifact handoff bug. `debug target score-source
--json` emits `score`, `target_score`, `full_unit_source`, retained pcdump, and
guard data, but omits function/source/candidate identity. Allocator validation
therefore rejects those artifacts as unscoped, and retained-frontier triage
cannot infer the residual IG44-hit lane.

## Implementation Scope

1. Preserve the active helper/data-layout next family when normalizing Sort
   continuations. Empty placeholder exhaustion rows must not close the active
   `next_unsupported_source_family`; real scored/materialized exhaustion still
   closes that family.
2. Add consistent scope fields to all `score-source --json` payloads:
   `function`, `score_function`, `source_file`, `c_file`, `cflags_from`,
   `source_retained`, and best-effort `candidate_id`.
3. Backfill the same fields when `score_retained_source_rows()` consumes older
   scorer output that lacks them.
4. Teach retained-frontier triage to recognize scoped direct Sort score-source
   artifacts as residual evidence, including exact dimension inference for
   `post-meta-source-family-sort-swap-slot-lvalue-*` and
   `post-meta-sort-semantic-recombine-*` candidates.
5. Keep allocator function-scope validation strict. Scoped direct score-source
   artifacts should pass because they now contain `function`; unscoped artifacts
   must still fail.

## Regression Coverage

Add focused tests for:

- A reporter-shaped terminal continuation that names helper/data-layout while
  carrying zero-candidate placeholder exhaustion rows. It should generate only
  helper/data-layout candidates.
- `score-source --json` success/failure payloads carrying the new scope fields.
- Retained scorer backfill preserving function/source/candidate/dimension
  identity when stdout contains only the old minimal score-source payload.
- Scoped direct Sort score-source artifacts becoming retained residual evidence,
  while loose unscoped score-source JSON remains ignored/rejected.

## Non-Goals

- Do not loosen allocator validation for arbitrary unscoped JSON.
- Do not treat a one-hit direct score-source artifact as a terminal proof by
  itself.
- Do not reopen older Sort families after a terminal proof has named a deeper
  next family.
