# struct verify v2 - Implementation Plan

> Required workflow: use test-driven development for each behavior change and
> ask an independent Codex subagent to review the spec/plan before production
> code changes. Do not request human design feedback during this automation.

Spec: `docs/superpowers/specs/2026-06-06-struct-verify-v2-design.md`
Issue: #439

Scope note: this plan is partial progress toward #439. It must not resolve #439
unless a later phase also implements the full stop condition from the issue:
minimal dataflow plus byte-correct layout proposal/repad/reorder coverage for
previously warn-skipped functions.

## Phase 1 - Pure helper tests

- [ ] Add tests for unique base-register inference from
  `offset_discrepancies`.
- [ ] Add tests for ambiguous/no-base outcomes.
- [ ] Add tests for explicit `--base-offset` normalization of `cur_disp` and
  `ref_disp`.
- [ ] Add tests for auto interior-offset inference when exactly one layout
  offset maps all current displacements.
- [ ] Add tests for ambiguous interior candidates producing diagnostics instead
  of findings.

## Phase 2 - CLI regression tests

- [ ] Add a `struct verify` CLI test that monkeypatches `checkdiff` JSON and
  confirms a single-base function works without `--base`.
- [ ] Add a CLI test that passes `--base-offset` and verifies normalized JSON
  fields.
- [ ] Extend the help test to cover `--base-offset`, `--base-offset-map`, and
  `--apply`.

## Phase 3 - Guarded apply tests

- [ ] Add a pure test for a top-level padding insertion on a temporary header.
- [ ] Add tests that nested/indexed fields and negative deltas return
  `not_applicable`.
- [ ] Add a test that failed post-edit verification restores the original header.
- [ ] Add a test that duplicate field names in other structs are ignored by
  struct-scoped declaration matching.

## Phase 4 - Implementation

- [ ] Extend `tools/melee-agent/src/cli/struct.py` with base resolution,
  base-offset parsing, interior normalization, and apply helpers.
- [ ] Add a small header-location helper in
  `tools/melee-agent/src/common/struct_layout.py`.
- [ ] Add struct-scoped declaration-span matching before any header edit.
- [ ] Preserve the existing aggregation API by adding extra keys to finding
  dicts, not replacing v1 keys.
- [ ] Keep dry-run reporting the default.

## Phase 5 - Verification and partial landing

- [ ] Run focused `struct verify` tests.
- [ ] Run `py_compile` for touched Python modules.
- [ ] Run command-level help smoke checks.
- [ ] Commit the spec, plan, tests, and implementation together.
- [ ] Leave #439 open unless the broader issue stop condition is also met.
