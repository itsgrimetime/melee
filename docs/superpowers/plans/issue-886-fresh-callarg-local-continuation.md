# Issue 886: Fresh Callarg-Local Continuation Implementation Plan

## Goal

Make `callarg_local_structural_repair` continue from an expression-good fresh
digit callarg local in `mnDiagram_DrawCellNumber`, specifically the
`digitf = (f32) digit; HSD_JObjReqAnimAll(jobj, digitf);` frontier, and make
validation summaries expose raw target-score false progress.

This plan is for implementation after independent review. Do not edit
production code during planning.

## Current Evidence

Artifacts reviewed:

- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_manual_rowf_matrix/scores/m04_digitf_local_callarg.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_manual_rowf_matrix/candidates/m04_digitf_local_callarg.c`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_callarg_local_structural_repair/scores/callarg_local_structural_repair@0.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_callarg_local_structural_repair/scores/callarg_local_structural_repair@1.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_callarg_local_structural_repair_h001h002/scores/callarg_local_structural_repair@0.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_callarg_local_structural_repair_h001h002/scores/callarg_local_structural_repair@1.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_callarg_local_structural_repair_m04_digitf.json`

Observed facts:

- `m04_digitf_local_callarg.c` uses separate `rowf` and `digitf` locals.
- Its score is raw `target_score=5/6`, but `expression_score=6/6` with no false
  positive virtual-id hits.
- Existing generated `callarg_local_structural_repair` probes use
  `digit_frame_fpr` and regress to `expression_score=4/6`, despite raw
  `target_score=5/6`.
- Running the family on the `digitf` source resolves the target function but
  emits zero probes with `source-pattern-not-found`.

Root cause:

- `register_steering.py` assumes the row-scale local and callarg local are the
  same (`rowf_local == callarg_local`).
- The family has introduce-local behavior for issue #885 but no continuation
  state for an already materialized fresh callarg local.
- Validation summaries already carry expression scores, but terminal reporting
  does not explicitly call out raw target-score false progress in this family.

## Implementation Rules

- Use subagent-driven implementation after this plan is reviewed.
- Preserve unrelated dirty files in `/Users/mike/code/melee`.
- Do not stage, commit, resolve issue #886, refresh installs, or touch
  `/Users/mike/.config/decomp-me`.
- Add regression tests before or with production changes.
- No new top-level CLI command is planned, so the AGENTS audit-first rule for
  new commands/tools is not triggered.

## Files To Touch

Production:

- `tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`
- `tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py`
- `tools/melee-agent/src/search/cli/__init__.py`

Conditional production:

- `tools/melee-agent/src/search/directed/transform_corpus/registry.py`
  - update metadata text only if needed.
- `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
  - update catalog text/tests only if registry wording changes.
- `tools/melee-agent/src/search/directed/mutators.py`
  - avoid touching unless a new mutator key is chosen; exact-span replacement
    should be enough.

Tests:

- `tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py`
- `tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py`
- `tools/melee-agent/tests/search/test_cli_smoke.py`
- `tools/melee-agent/tests/test_source_transform_catalog.py`
- Conditional:
  `tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py`
  only if registry metadata changes.

## Step 1: Add Failing Fresh-Local Matcher Tests

In `test_register_steering.py`, add a compact fixture modeled on
`m04_digitf_local_callarg.c`:

```c
f32 rowf;
f32 digitf;
f32 col_offset;
f32 col_offset_product_fpr;
f32 row_offset;
f32 row_offset_adj;
f32 row_offset_adj_owner_fpr;

col_offset_product_fpr = y_spacing * col_cast_owner_fpr;
col_offset = col_offset_product_fpr;
digit_count = mn_GetDigitCount(value);
rowf = (f32) row;
row_offset *= rowf;
row_offset_adj_owner_fpr = row_offset - 0.4f;
row_offset_adj = row_offset_adj_owner_fpr;

for (i = 0; i < digit_count; i++) {
    digit = mn_GetDigitAt(value, i);
    digitf = (f32) digit;
    HSD_JObjReqAnimAll(jobj, digitf);
}
```

Tests:

- `test_callarg_local_structural_repair_continues_from_existing_fresh_local`
  - calls `generate_transform_probes(..., families=("callarg_local_structural_repair",))`;
  - asserts at least one family probe is emitted;
  - asserts a default continuation preserves `digitf = (f32) digit;` and
    `HSD_JObjReqAnimAll(jobj, digitf);`;
  - asserts the default continuation does not introduce `digit_frame_fpr`.
- `test_callarg_local_structural_repair_separates_rowf_and_callarg_local`
  - asserts payload has `rowf_local="rowf"`, `call_arg_local="digitf"`, and
    `call_arg_local_kind="fresh-existing"`.
- Negative cases:
  - `sink(&digitf);` rejects;
  - `digitf` used after the loop rejects declaration-demotion strategies;
  - two dominating `(f32) digit` assignments before the call reject with an
    ambiguity diagnostic;
  - multiple `HSD_JObjReqAnimAll` calls still reject as ambiguous.

Expected pre-fix result: no probes, or generic `source-pattern-not-found`.

## Step 2: Extend The Case Model And Matcher

In `register_steering.py`:

1. Extend `_RegisterSteeringCallargLocalStructuralCase`:
   - keep `rowf_local`;
   - keep `callarg_local`;
   - add `callarg_local_kind`;
   - add any offsets needed to identify declaration position and loop extent.

2. Update `_iter_callarg_local_structural_cases`:
   - remove the hard `rowf_local != callarg_local` rejection;
   - accept a separate existing FPR local if `_find_existing_digit_callarg_assignment`
     proves it dominates `HSD_JObjReqAnimAll`;
   - require the callarg assignment RHS to cast the same digit operand used by
     `mn_GetDigitAt`;
   - reject address-taken, assigned-between, or used-after unsafe shapes;
   - remove the global `_identifier_mentions(searchable, "digit_frame_fpr")`
     early return. Name collisions should suppress only variants that need that
     exact fresh name.

3. Preserve existing issue #885 behavior:
   - inline/direct callarg sources should still generate `fresh-loop-callarg-local`
     and `block-scoped-callarg-local`;
   - rowf-reuse sources should still be supported.

## Step 3: Add Fresh-Local Continuation Strategies

In `_iter_callarg_local_structural_repair_anchors`, emit bounded strategies for
`callarg_local_kind="fresh-existing"`:

- `continue-existing-fresh-callarg-local`
  - exact-span rewrite that preserves the existing callarg assignment/call while
    normalizing only the matched structural span if the rewrite is non-noop.
- `fresh-local-product-count-order-swap`
  - swap the digit-count statement with the product/handoff pair when neither
    side reads/writes the other.
- `fresh-local-decl-demote-to-loop`
  - move the fresh callarg local declaration into the loop immediately before
    the assignment when the local is not used outside the loop.
- `fresh-local-block-scope-equivalent`
  - emit a block-scoped equivalent as an exploratory probe, but keep existing
    local preservation as the preferred/default strategy.

Payload fields for all fresh-local continuation probes:

- `strategy`;
- `rowf_local`;
- `call_arg_local`;
- `call_arg_local_kind`;
- `call_arg_operand`;
- `product_order`;
- `digit_count_order`;
- `preserves_existing_callarg_local`;
- `uses_fresh_local`;
- `source_regions`.

Keep the family bounded to a small number of probes, preferably no more than
four fresh-local continuation probes per matched region.

## Step 4: Improve Orchestrator Diagnostics

In `orchestrator.py`, update `_basic_callarg_local_structural_diagnostics` and
the family stat payload:

- report `rowf_locals`;
- report `call_arg_locals`;
- report `call_arg_local_kinds`;
- report `has_existing_fresh_callarg_local`;
- report `generated_strategies`;
- use specific rejection reasons:
  - `separate-callarg-local-not-supported` should disappear after the fix;
  - `fresh-callarg-local-continuation-unavailable`;
  - `ambiguous-callarg-assignment`;
  - `callarg-local-address-taken`;
  - `callarg-local-used-after-loop`.

Add `test_orchestrator.py` coverage asserting that the fresh-local fixture
reports resolved diagnostics and does not collapse to generic
`source-pattern-not-found`.

## Step 5: Improve Validation Summary For False Progress

In `tools/melee-agent/src/search/cli/__init__.py`:

- keep ranking by `expression_score` when present;
- ensure `false_positive_virtual_id_hit_count` survives into
  `ranked_guarded_partials` evidence;
- for `callarg_local_structural_repair`, add a terminal blocker/note when every
  raw target-score improvement either:
  - has `expression_score.matched < expression_score.targeted`; or
  - has `false_positive_virtual_id_hit_count > 0`.

Suggested summary token:

```text
raw-target-progress-expression-regressed
```

Add or extend `test_source_transform_catalog.py` coverage with two validation
results matching the #886 shape:

- raw `target_score.matched=5/6`, expression `4/6`, false positive count `1`;
- retained fresh-local raw `5/6`, expression `6/6`, false positive count `0`.

Assert the retained fresh-local result ranks ahead of the raw false-positive
result.

## Step 6: CLI Smoke Test

In `test_cli_smoke.py`, add a `plan-transforms` smoke with the fresh-local
fixture:

```bash
melee-agent debug search plan-transforms \
  --function mnDiagram_DrawCellNumber \
  --unit melee/mn/mndiagram \
  --force-phys 1:33:26,1:35:26,1:40:28,1:41:29,1:42:29,1:43:29 \
  --source-file <tmp fresh-local source> \
  --transform-family callarg_local_structural_repair \
  --max-per-family 8 \
  --write-probes <tmp probes> \
  --json
```

Assertions:

- at least one `callarg_local_structural_repair` probe;
- every `candidate_path` exists;
- at least one candidate preserves `HSD_JObjReqAnimAll(jobj, digitf);`;
- family diagnostics include `has_existing_fresh_callarg_local=true`.

## Focused Test Command

Run from `/Users/mike/code/melee`:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q
```

If registry/catalog metadata changes, include:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q
```

## Real Artifact Smoke

Use a disposable diagnostics directory under the worktree. Do not write to
`/Users/mike/.config/decomp-me`.

```bash
rm -rf build/diagnostics/issue886_fresh_callarg_local_continuation
mkdir -p build/diagnostics/issue886_fresh_callarg_local_continuation

melee-agent debug search plan-transforms \
  --function mnDiagram_DrawCellNumber \
  --unit melee/mn/mndiagram \
  --force-phys 1:33:26,1:35:26,1:40:28,1:41:29,1:42:29,1:43:29 \
  --source-file /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_manual_rowf_matrix/candidates/m04_digitf_local_callarg.c \
  --transform-family callarg_local_structural_repair \
  --max-per-family 8 \
  --write-probes build/diagnostics/issue886_fresh_callarg_local_continuation/probes \
  --json \
  > build/diagnostics/issue886_fresh_callarg_local_continuation/plan_transforms.json

jq '.family_diagnostics[] | select(.family_id=="callarg_local_structural_repair")' \
  build/diagnostics/issue886_fresh_callarg_local_continuation/plan_transforms.json

jq '.probes[] | select(.family_id=="callarg_local_structural_repair") | {probe_id, payload, candidate_path}' \
  build/diagnostics/issue886_fresh_callarg_local_continuation/plan_transforms.json
```

Expected:

- `materialized_count > 0`;
- diagnostics show `call_arg_local=digitf` and
  `has_existing_fresh_callarg_local=true`;
- at least one candidate preserves the existing `digitf` callarg local;
- no default continuation candidate hard-codes `digit_frame_fpr`.

Then score the generated candidates with the same expression baseline used for
the issue #886 artifacts. Accept a candidate only if:

- `expression_score.matched == expression_score.targeted == 6`;
- `false_positive_virtual_id_hit_count == 0`;
- structure improves versus the retained `m04_digitf_local_callarg` frontier.

## Handoff Notes For Subagent Implementation

Use one implementation subagent after plan review. The prompt should require the
subagent to:

- read this plan and the design spec;
- add the failing regression tests first;
- implement only the files listed above;
- preserve unrelated dirty files;
- run the focused tests and the real artifact smoke;
- report exact changed files and command output summaries;
- avoid staging, committing, resolving issue #886, refreshing installs, or
  touching `/Users/mike/.config/decomp-me`.

Independent review notes to preserve during implementation:

- Fresh-existing continuation strategies must emit non-noop `replacement_text`;
  the exact-span mutator intentionally rejects unchanged spans.
- Zero-probe diagnostics for fresh-local cases need scanner or case-state data,
  not only emitted anchor payloads, because emitted anchors are empty in the
  failure mode.
- A `digitf` use after the loop should suppress declaration-demotion and
  block-scope strategies, but should not automatically reject a preserve-existing
  continuation unless the use creates a real semantic hazard.
- Existing `digit_frame_fpr` collision behavior should become variant-specific:
  suppress only generated variants that require that exact name, not the entire
  family.
