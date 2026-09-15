# Issue 885: Callarg-Local Structural Repair Implementation Plan

## Goal

Add a reusable tooling lane for protected expression anchors where the
structurally better source uses a direct FPR call argument, but the protected
expression frontier needs a source-visible callarg local/reuse to keep pcode
FPR anchors alive.

This plan is design-only. Do not implement production code until it has had
independent review.

## Current Frontier

Issue #885 is already claimed by `codex-issue-resolver-fd86`; do not force-take
the claim.

Observed artifacts:

- `mndiagram_draw_885_protected_expression_reconcile_scored.json`
  - best preserving: `reconcile-h001-h002`, `expression_score=6/6`,
    `normalized_diff_lines=32`.
  - best structural: `reconcile-h004`, `expression_score=4/6`,
    `normalized_diff_lines=18`, both `fsubs` anchors are
    `missing-expression`.
- `mndiagram_draw_885_reconcile_h004_plan_fpr.json`
  - existing pcode-only FPR fsubs/callarg probes scored at 4/6 or worse.
- `mndiagram_draw_885_h004_expression_interferer_repair.json`
  - expression-interferer generated row/product candidates, but none crossed
    the frontier. `row-scaled-adj-direct-owner` is incoherent and still 4/6.

Root cause: generation lacks a composite callarg-local-preserving structural
repair. Existing lanes either recombine raw frontiers, rewrite a call site too
locally, or explore row/product ownership without preserving the digit callarg
local that protects the two `fsubs` expression anchors.

## Files Likely Touched

Production:

- `tools/melee-agent/src/search/directed/transform_corpus/registry.py`
- `tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`
- `tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py`
- `tools/melee-agent/src/search/directed/mutators.py`
- `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- `tools/melee-agent/src/search/cli/__init__.py`
- Optional after scored reconciliation smoke:
  `tools/melee-agent/src/mwcc_debug/protected_expression_reconciliation.py`
- Optional after first smoke: `tools/melee-agent/src/mwcc_debug/expression_interferer_repair.py`
- Optional only for JSON plumbing: `tools/melee-agent/src/cli/debug/__init__.py`

Tests:

- `tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py`
- `tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py`
- `tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py`
- `tools/melee-agent/tests/search/directed/test_mutators.py`
- `tools/melee-agent/tests/test_source_transform_catalog.py`
- `tools/melee-agent/tests/search/test_cli_smoke.py` or an adjacent
  `plan-transforms` CLI test for `candidate_path` and validation summary.

## Implementation Tasks

### 1. Add failing registry and mutator tests

Add tests before production changes:

- `test_callarg_local_structural_repair_metadata_is_executable`
  - family id: `callarg_local_structural_repair`;
  - mutator key: `steer_callarg_local_preserving_structural_repair`;
  - semantic risk: medium;
  - supported force class: FPR/class 1.

- `test_steer_callarg_local_preserving_structural_repair_validates_exact_span`
  - `apply_mutator()` returns the replacement when the source span matches;
  - returns `None` for a stale span.

Expected pre-implementation result: failing family/mutator lookup.

### 2. Add transform-corpus source-shape tests

Use a compact fixture based on the h004 body:

```c
digit_count = mn_GetDigitCount(value);
col_offset_product_fpr = y_spacing * col_cast_owner_fpr;
col_offset = col_offset_product_fpr;
rowf = (f32) row;
row_offset *= rowf;
row_offset_adj_owner_fpr = row_offset - 0.4f;
row_offset_adj = row_offset_adj_owner_fpr;

for (i = 0; i < digit_count; i++) {
    digit = mn_GetDigitAt(value, i);
    rowf = (f32) digit;
    HSD_JObjReqAnimAll(jobj, (f32) digit);
}
```

Tests should assert generated probes include coherent source variants:

- `retain-existing-rowf-callarg-h004-order`:
  - `rowf = (f32) digit;`
  - `HSD_JObjReqAnimAll(jobj, rowf);`
  - product/count order remains h004-like.

- `fresh-loop-callarg-local`:
  - introduces `f32 digit_frame_fpr;`;
  - assigns `digit_frame_fpr = (f32) digit;`;
  - calls `HSD_JObjReqAnimAll(jobj, digit_frame_fpr);`.

- `block-scoped-callarg-local`:
  - wraps only the request call in a block;
  - does not move unrelated translate calls into the block.

- negative cases:
  - address-taken `rowf` rejects;
  - preprocessor directives inside span reject;
  - multiple ambiguous `HSD_JObjReqAnimAll` calls reject or emit a diagnostic
    without a probe;
  - no duplicate `f32` declarations.

Expected pre-implementation result: no `callarg_local_structural_repair` probes.

### 3. Implement family metadata and mutator dispatch

In `registry.py`, add `TransformFamily`:

- `family_id="callarg_local_structural_repair"`
- `mutator_keys=("steer_callarg_local_preserving_structural_repair",)`
- keywords: `callarg`, `call-argument`, `protected-expression`, `fpr`,
  `HSD_JObjReqAnimAll`, `digit`, `rowf`, `structural`.

In `mutators.py`, add the exact-span mutator as a thin wrapper around
`_replace_validated_span`.

In the force-class support map in `orchestrator.py`, allow class `1`.

### 4. Implement exact matcher and candidate generation

In `register_steering.py`:

- Add a private dataclass or dictionary model for the protected callarg span:
  - digit count statement;
  - product definition and handoff;
  - rowf row-cast statement;
  - row scaling and row adjusted owner;
  - loop digit assignment;
  - optional digit callarg assignment;
  - `HSD_JObjReqAnimAll` call statement.

- Add `_iter_callarg_local_structural_anchors(...)` that emits `Anchor`
  instances with:
  - `mutator_key="steer_callarg_local_preserving_structural_repair"`;
  - exact source span and replacement text;
  - payload fields: `strategy`, `call_arg_local`, `call_arg_operand`,
    `product_order`, `digit_count_order`, `uses_fresh_local`.

- Add diagnostics:
  - `hsd_jobj_req_anim_all_calls`;
  - `candidate_callarg_spans`;
  - `accepted_anchor_count`;
  - `generated_strategies`;
  - `rejection_reasons`.

Keep generation bounded. Start with at most four candidate strategies per
matched region.

In `orchestrator.py`:

- import `_iter_callarg_local_structural_anchors`;
- add class-1/FPR support for `callarg_local_structural_repair`;
- add a small diagnostic helper with call counts, accepted anchor count,
  generated strategies, and rejection reasons;
- dispatch anchors with existing `apply_mutator` and whole-file span wrapping.

### 5. Wire catalog and summaries

In `source_transform_catalog.py`:

- Add the family to the plan-transform catalog entry.
- Include it in relevant FPR force-phys technique lists.
- Keep this file metadata-only; do not implement validation behavior here.

In `src/search/cli/__init__.py`, extend `_summarize_transform_validations` with
validation-summary blocker:

```text
exhausted-callarg-local-structural-repair
```

The blocker should trigger when all generated/scored candidates for the family
either:

- keep `expression_score=6/6` but remain at or above the structural ceiling; or
- improve structure but still lose protected expression anchors.

### 6. Optional expression-interferer source generation mirror

After transform-corpus tests pass, run the real artifact smoke below. If the
main agent workflow still relies on `debug suggest expression-interferer-repair`
for probe files, mirror the same candidate strategies in
`expression_interferer_repair.py` by adding source-generation candidates rather
than duplicating the full matcher. The transform-corpus family should remain the
source of reusable production behavior.

## Command-Level Smoke Checks

Run from `/Users/mike/code/melee`.

### Static CLI/help checks

```bash
melee-agent capabilities search "callarg local protected expression structural repair"
melee-agent debug search plan-transforms --help >/tmp/issue885-plan-transforms-help.txt
melee-agent debug suggest protected-expression-reconcile --help >/tmp/issue885-reconcile-help.txt
melee-agent debug suggest expression-interferer-repair --help >/tmp/issue885-expression-help.txt
```

### Focused tests

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  -q
```

### Real artifact probe generation

Use the h004 source from the diagnostics, because it is the structurally best
frontier that lost the two protected `fsubs` anchors:

```bash
rm -rf build/diagnostics/issue885_callarg_local_structural_repair
mkdir -p build/diagnostics/issue885_callarg_local_structural_repair

melee-agent debug search plan-transforms \
  --function mnDiagram_DrawCellNumber \
  --unit melee/mn/mndiagram \
  --force-phys 1:33:26,1:35:26,1:40:28,1:41:29,1:42:29,1:43:29 \
  --source-file /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_885_protected_expression_reconcile/reconcile-h004.c \
  --transform-family callarg_local_structural_repair \
  --max-per-family 8 \
  --write-probes build/diagnostics/issue885_callarg_local_structural_repair/probes \
  --json \
  > build/diagnostics/issue885_callarg_local_structural_repair/plan_transforms.json

jq '.probes[] | select(.family_id=="callarg_local_structural_repair") | {probe_id, mutator_key, payload, candidate_path}' \
  build/diagnostics/issue885_callarg_local_structural_repair/plan_transforms.json
```

Expected:

- at least one probe uses `HSD_JObjReqAnimAll(jobj, rowf)` or a fresh
  `digit_frame_fpr` local;
- no generated source duplicates row scaling;
- diagnostics list accepted strategies and any rejected unsafe spans.
- JSON probes include `candidate_path`; transform-corpus probes are not
  required to carry embedded `score_source` hints.

### Real artifact scoring

Use the same target and expression baseline files referenced by the existing
score-source hints in the #885 JSON. The exact paths can be extracted from the
artifact payloads if not already in the working shell:

```bash
jq -r '.best_structural_candidate.score_source.command' \
  /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_885_protected_expression_reconcile_scored.json
```

For each generated probe, run the equivalent `debug target score-source` command
with the real `--target`, `--expression-baseline`, and `--expression-source`
paths from the issue artifacts:

```bash
melee-agent debug target score-source <generated-probe.c> \
  -f mnDiagram_DrawCellNumber \
  --cflags-from src/melee/mn/mndiagram.c \
  --target <target.json> \
  --expression-baseline <baseline.pcdump.txt> \
  --expression-source <baseline-source.c> \
  --expression-reg-class fpr \
  --checkdiff-guard \
  --json \
  > build/diagnostics/issue885_callarg_local_structural_repair/<probe-id>.score.json
```

Acceptance target:

- best case: `expression_score.matched == 6`,
  `structural_guard.normalized_diff_lines < 32`;
- stronger case: approach h004's `normalized_diff_lines=18`;
- terminal case: summary reports why every local-preserving candidate remains at
  30+ normalized lines and which anchors/spans make that unavoidable.

### Reconciliation rerun

After scoring, pass generated score JSONs back into the existing reconciler:

```bash
melee-agent debug suggest protected-expression-reconcile \
  --expression-source /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_883_six_hit_expression_repair/digit-guard-product-before-count.c \
  --expression-score-json <six-hit-expression-score.json> \
  --structural-source /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_885_protected_expression_reconcile/reconcile-h004.c \
  --structural-score-json <h004-score.json> \
  -f mnDiagram_DrawCellNumber \
  --source-function mnDiagram_DrawCellNumber \
  --candidate-score-json <comma-separated-generated-score-jsons> \
  --max-normalized-diff-lines 30 \
  --json \
  > build/diagnostics/issue885_callarg_local_structural_repair/reconcile_with_callarg_local.json
```

Expected:

- generated candidates are not dropped as unrelated;
- best preserving/structural summaries mention the new family or strategy;
- terminal blockers distinguish local-preserving structural ceiling from
  anchor-regressing direct-callarg candidates.

## Review Checklist

- The family is discoverable through `melee-agent capabilities search`.
- The matcher never edits outside the requested function body.
- Every generated probe is exact-span validated.
- The first implementation emits bounded candidate count by default.
- Unsafe spans produce diagnostics rather than malformed source.
- No changes are made to `src/melee/mn/mndiagram.c`.
- No install refresh, issue resolution, staging, or commit happens in the
  planning/first implementation pass unless explicitly requested later.

## Risks

- The compiler may genuinely couple callarg-local preservation to the 30+ line
  inline-boundary drift. In that case the correct output is a terminal summary,
  not more probe volume.
- Reusing `rowf` may be structurally worse because it also owns row scaling.
  Fresh loop-local and block-scoped variants are important to test separately.
- `debug search plan-transforms` has a public repeatable `--transform-family`
  flag in this checkout; keep the implementation on that existing route rather
  than adding another CLI.
