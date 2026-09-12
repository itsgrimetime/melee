# Issue 888: Expression-Preserving Structural Repair From Fresh Digitf Frontier

## Scope

Issue #888 continues the `mnDiagram_DrawCellNumber` tooling lane after #887.
The source frontier is:

```text
/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_manual_rowf_matrix/candidates/m04_digitf_local_callarg.c
```

The goal is source-actionable output starting from that C source:

- ranked retained `.c` probes or source hunks;
- `expression_score.matched == expression_score.targeted == 6`;
- `target_score.matched >= 5`;
- `structural_guard.normalized_diff_lines < 30`;
- or a terminal summary that names the inline-boundary/opcode drift that cannot
  be repaired while preserving the top-level fresh `digitf` callarg shape.

This is not a request to edit `src/melee/mn/mndiagram.c`.

## Audit Note

`melee-agent capabilities search` was skipped during the initial planning pass
because that pass was intentionally read-only around shared issue state. The
implementation pass later ran the normal audit command after claiming the issue
and confirmed that the existing `debug search plan-transforms` plus
`debug target score-source` workflow is the right home for this work.

Relevant existing capabilities are already present:

- `debug search plan-transforms`
- `debug target score-source`
- `debug mutate lifetime-layout`
- `debug suggest protected-expression-reconcile`
- `debug suggest expression-interferer-repair`

No new top-level command is justified.

## Evidence Read

Artifacts inspected:

- `m04_digitf_local_callarg.json`: `target_score=5/6`,
  `expression_score=6/6`, false positives `0`, `normalized_diff_lines=30`,
  `opcode_similarity=0.8092485549132948`.
- manual rowf matrix:
  - all `expression_score=6/6` callarg-local variants remain at 30 or 32
    normalized lines.
  - the sub-30 direct-callarg candidate `m08_rowf_dead_direct_callarg` reaches
    18 normalized lines but drops to `expression_score=4/6`; V33 and V35 are
    `missing-expression`.
- `mndiagram_draw_887_callarg_local_structural_repair_m04_digitf`:
  - generated count/product variants keep 6/6 at 30 or 32.
  - block-scoped fresh local drops to 4/6 with one false-positive virtual-ID
    hit.
  - one earlier demotion probe failed validation with "function
    'mnDiagram_DrawCellNumber' not in compiled pcdump"; #887 fixed the demoted
    declaration position, so #888 should treat this as validation evidence to
    rerun, not as a final source conclusion.
- `mndiagram_draw_887_manual_loop_local_digitf`:
  - loop-local `digitf` before load: 4/6, 30 lines, false positives `1`.
  - loop-local `digitf` after load: 4/6, 30 lines, false positives `1`.
  - loop-local `digitf` after `HSD_JObjAddAnimAll`: 4/6, 18 lines, false
    positives `1`.
- `mndiagram_draw_887_m04_coloring_register_steering`:
  - many candidates retain 5/6 raw target and 6/6 expression, but all observed
    expression-preserving candidates stay at 30 normalized lines.

The key false-positive pattern is visible in the sub-30 loop-local candidate:
raw `target_score` still reports 5/6, but expression scoring reports
`expression_score=4/6` and `false_positive_virtual_id_hit_count=1`. V33 maps to
the expected raw virtual neighborhood but has the wrong physical register by
expression identity; V35 also misses.

## Root Cause

The remaining gap is not scoring, command discovery, or family registration.
`callarg_local_structural_repair` already exists, but the current fresh-existing
`digitf` branch is too shallow:

- it only rotates product/count order;
- demotes the top-level fresh local into a loop-local declaration;
- wraps the call segment in a block;
- and then returns a maximum of four anchors before the orchestrator budget can
  explore a wider frontier.

Those variants do not cover the observed structural lever: the position of
`digitf = (f32) digit` relative to `HSD_JObjLoadJoint`,
`HSD_JObjAddAnimAll`, and `HSD_JObjReqAnimAll`. Manual probes show that moving
the assignment after `HSD_JObjAddAnimAll` can reach 18 normalized lines, but
that exact shape loses the protected `fsubs` anchors. The tooling needs to
generate that family systematically and report the expression regression as a
false-positive raw target improvement.

The reusable class is:

> A top-level fresh FPR callarg local preserves protected expression anchors and
> improves raw target hits, but structural improvements require call-segment
> scheduling that tends to demote or reassign the fresh local in ways that
> sever protected FPR expression identity.

## Approaches Considered

### Approach 1: Add a new one-off source probe command

A command dedicated to `mnDiagram_DrawCellNumber` could read
`m04_digitf_local_callarg.c`, emit the manual loop-local variants, score them,
and print a report.

Pros:

- fastest to prototype for this one frontier;
- output can be tailored exactly to #888.

Cons:

- duplicates `plan-transforms`, `score-source`, and validation-summary plumbing;
- violates the audit-first direction because existing transform-corpus
  machinery already does the orchestration;
- less reusable for the same expression-anchored FPR source-shape class.

Reject.

### Approach 2: Extend `callarg_local_structural_repair` and its validation summary

Keep the existing transform-corpus family and add a fresh-`digitf` frontier
inside `register_steering.py`. Let `debug search plan-transforms` write probes
and optionally validate them with `debug target score-source`. Extend
`_summarize_transform_validations` so it names the stop-condition evidence.

Pros:

- reuses the existing exact-span mutator, source-file aliasing, probe writing,
  validation command template, and JSON output;
- keeps the change scoped to the existing family;
- can produce either retained `.c` candidates or an explicit terminal summary;
- directly addresses raw target-score false positives.

Cons:

- requires careful bounded generation so the family does not become a broad C
  scheduler;
- terminal-summary logic must be precise enough not to claim success from raw
  virtual-ID hits.

Choose this approach.

### Approach 3: Add terminal-summary/reporting only

Do not generate new probes. Summarize existing m04, manual loop-local, and
coloring-register scores as terminal evidence.

Pros:

- lowest implementation risk;
- useful if the source class is already exhausted.

Cons:

- does not satisfy the source-actionable output requirement unless the manual
  artifacts are accepted as the full bounded set;
- does not make future agents able to regenerate the frontier from source.

Reject for v1. Keep the richer terminal report as part of Approach 2.

## Proposed Design

Extend the existing `callarg_local_structural_repair` family. Do not add a new
CLI command or a new mutator key.

### Generator Changes

In `tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`,
extend `_iter_callarg_local_structural_repair_anchors` for
`callarg_local_kind == "fresh-existing"`.

Current inputs already identify:

- `digit_count = mn_GetDigitCount(...)`;
- column product and handoff;
- row cast and row scale;
- row adjusted owner;
- loop digit assignment;
- existing fresh callarg assignment, for example `digitf = (f32) digit;`;
- `HSD_JObjReqAnimAll(jobj, digitf)`;
- loop boundaries.

Add bounded strategies:

- `fresh-local-decl-demote-to-loop` also represents the before-load schedule:
  declaration at loop top, assignment immediately after
  `digit = mn_GetDigitAt(...)`, before `HSD_JObjLoadJoint`; attach
  `digit_assignment_schedule = "before-load"` metadata rather than emitting a
  duplicate materialized probe with identical source text.
- `fresh-local-call-schedule-after-load`: declaration at loop top, assignment
  after `HSD_JObjLoadJoint`, before `HSD_JObjAddAnimAll`.
- `fresh-local-call-schedule-after-add`: declaration at loop top, assignment
  after `HSD_JObjAddAnimAll`, before `HSD_JObjReqAnimAll`.
- `fresh-local-callarg-handoff-top`: keep `digitf = (f32) digit` early, add a
  narrow `digit_call_fpr` handoff before the request call, and call with the
  handoff local. The handoff declaration must be placed in a top-level
  declaration-safe region, not immediately before an executable statement.
- `fresh-local-callarg-handoff-block`: keep `digitf = (f32) digit` early, add a
  block-scoped handoff local around only the request call, with the declaration
  at the top of that block.

Keep existing strategies:

- `continue-existing-fresh-callarg-local`
- `fresh-local-product-count-order-swap`
- `fresh-local-decl-demote-to-loop`
- `fresh-local-block-scope-equivalent`

Remove or relax the internal `anchors[:4]` truncation so the orchestrator's
`max_per_family` budget controls output. If a hard internal cap remains, make
it explicit, at least 12, and report `budget_limited` through the existing
family diagnostic path.

### Safety Rules

The matcher should continue to reject:

- preprocessor directives in the candidate body;
- multiple ambiguous `HSD_JObjReqAnimAll` calls;
- address-taken callarg locals;
- duplicate matching callarg assignments;
- callarg locals used after the loop when demotion or block scoping would
  change lifetime;
- intervening statements with unknown side effects for handoff insertion.

Handoff variants are only allowed when the new handoff identifier is unused in
the blanked source text.

Do not emit dead keepalive direct-callarg variants in v1. Existing evidence
shows direct-callarg structural wins can be expression false positives or
missing-expression cases; v1 should report that instead of generating unnatural
dead-local source.

### Validation Summary Changes

In `tools/melee-agent/src/search/cli/__init__.py`, extend
`_summarize_transform_validations` for `callarg_local_structural_repair`.

Add a compact field, for example:

```json
"callarg_local_frontier_summary": {
  "threshold_normalized_diff_lines": 30,
  "best_expression_preserving": {...},
  "best_structural": {...},
  "raw_target_false_progress": [...],
  "stop_condition_met": false,
  "terminal_blockers": [...]
}
```

`best_expression_preserving` requires:

- `expression_score.matched == expression_score.targeted`;
- targeted count at least 6 for this issue;
- `false_positive_virtual_id_hit_count == 0`.

`best_structural` ranks by lower `structural_guard.normalized_diff_lines`, then
higher `opcode_similarity`, then expression count.

`raw_target_false_progress` should include candidates where raw `target_score`
improves or stays at least 5/6 while expression scoring either regresses or has
false-positive virtual-ID hits.

Terminal blockers should be data driven:

- `structural-ceiling-with-protected-anchors`: at least one 6/6 expression
  candidate exists, but the best normalized line count is `>= 30`.
- `sub30-candidates-lost-protected-anchors`: at least one candidate has
  `normalized_diff_lines < 30`, but none preserves all expression anchors.
- `raw-target-progress-expression-regressed`: raw target-score progress is
  explained by expression regression or false-positive virtual-ID hits.
- `inline-boundary-opcode-drift`: copy compact `classification_primary`,
  `normalized_diff_lines`, `opcode_similarity`, `line_delta`, and `hunk_count`
  from the best expression-preserving structural guard.

The summary should mark success when any validated family candidate has:

- expression preserved as above;
- `target_score.matched >= 5`;
- `structural_guard.normalized_diff_lines < 30`;
- no false-positive virtual-ID hits.

It should not require `structural_guard.accepted == true`, because the issue
stop condition is specifically `< 30`, not full checkdiff acceptance.

## Integration Points

Likely production files:

- `tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`
  - add fresh-`digitf` schedule and handoff strategies;
  - remove or raise the internal four-anchor cap;
  - expand diagnostics with generated strategies and skipped strategy reasons.
- `tools/melee-agent/src/search/cli/__init__.py`
  - add helpers for expression preservation, normalized line extraction,
    opcode similarity extraction, false-positive raw target progress, and the
    callarg-local frontier summary.
- `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
  - update catalog notes so the existing family documents fresh-`digitf`
    schedule and handoff variants.

Likely test files:

- `tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py`
- `tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py`
- `tools/melee-agent/tests/test_source_transform_catalog.py`

No changes are expected in:

- `tools/melee-agent/src/search/directed/mutators.py`
- `tools/melee-agent/src/search/directed/transform_corpus/registry.py`
- `src/melee/mn/mndiagram.c`

Those files should only change if tests prove the current exact-span mutator or
family metadata is insufficient.

## Stop Condition Verification

For the real `m04_digitf_local_callarg.c` frontier, run
`debug search plan-transforms` with `--transform-family
callarg_local_structural_repair`, `--write-probes`, `--validate-command`, and
`--validate-all`.

Accept success only if `validation_summary.callarg_local_frontier_summary`
reports a candidate with:

- `expression_score.matched == 6`;
- `expression_score.targeted == 6`;
- `false_positive_virtual_id_hit_count == 0`;
- `target_score.matched >= 5`;
- `structural_guard.normalized_diff_lines < 30`.

If no candidate qualifies, accept a terminal report only if it identifies:

- best 6/6 expression-preserving candidate and its normalized line count;
- best sub-30 structural candidate and its expression loss;
- raw target-score false positives, if any;
- inline-boundary structural guard fields from the best preserving candidate.

## Non-Goals

- Do not add a top-level command.
- Do not change `debug target score-source` scoring semantics.
- Do not edit `src/melee/mn/mndiagram.c`.
- Do not record issue-state, attempts ledger, or capability audit logs when
  `.config/decomp-me` is off limits.
- Do not generate unnatural dead-local direct-callarg keepalive source in v1.
