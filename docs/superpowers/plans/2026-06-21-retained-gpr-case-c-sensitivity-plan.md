# Retained GPR Case-C Sensitivity Plan

## Issue

Issue #927 requested a reusable retained-source sensitivity lane for
`mnDiagram_SortNamesByKOs` after the narrower pcode-only GPR copy-product
Case-C probes and #925/#926 recombination evidence all stayed flat.

The actionable gap was not another duplicate report. The matcher needed a
bounded way to generate source-visible retained Case-C perturbations around the
low-confidence `dst_iter` clue, then validate and summarize whether any probe
moved `target_score.virtuals` or first-divergence evidence.

## Scope

Add a transform-corpus family, `retained_gpr_case_c_sensitivity_search`, routed
for mndiagram Class-0 force-phys plans. The family reuses the existing Case-C
GPR parser and emits retained-source cursor/store ownership probes:

- store through the low-confidence retained local
- loop through the low-confidence retained local
- bridge owner initialization through the low-confidence retained local

Each probe carries `source_hunks` and a `first_divergence_objective` payload so
remote score-source validation output can be ranked and explained by the
existing `plan-transforms --validate-command` lane.

## Validation Contract

`plan-transforms` validation summaries should:

- preserve `target_score`, `first_divergence`, and
  `first_divergence_movement` payloads when validators emit them
- rank retained Case-C sensitivity candidates by `target_score.virtuals` and
  first-divergence movement
- emit `exhausted-retained-gpr-case-c-sensitivity-search` plus
  `flat-retained-case-c-sensitivity-exhausted` when all scored probes stay flat

## Verification

Focused tests cover:

- probe materialization on the retained Sort cursor/store pattern
- family metadata and mndiagram force-phys routing
- source transform catalog and capability discoverability
- CLI validation-summary terminal blocker behavior

Command smoke should run `debug search plan-transforms` against the retained
Sort source from issue #927 with
`--transform-family retained_gpr_case_c_sensitivity_search`, confirming three
probes are emitted and flat validation produces the retained Case-C terminal
blocker.
