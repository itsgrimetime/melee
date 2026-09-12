# Issue 1088: Sort Next Family After Broader Natural C Rewrite Ceiling

## Goal

Prevent `mnDiagram_SortNamesByKOs` from looping back into `sort-post-cross-tu-broader-natural-c-rewrite` after that source family has exhausted. The intended next source-actionable family is:

`sort-post-broader-natural-inline-boundary-source-hypothesis`

If that family also exhausts, the terminal proof must advance to:

`sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis`

## Investigation Summary

Relevant artifact directory:

`/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1086_1087_rerun/sort_broader_natural_c/`

Reviewed artifacts:

- `source_model_scored.json`
- `source_family_continuation.json`
- `retained_frontiers.json`
- `allocator_ceiling.json`
- generated broader-natural candidate `.c` files and `.pcdump.txt` files

Reviewed code:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`
- `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`
- `/Users/mike/code/melee/tools/melee-agent/src/cli/capabilities.py`

Reviewed focused tests:

- `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_allocator_ceiling.py`

Capability audit:

`melee-agent capabilities search "retained frontier source model allocator ceiling next unsupported source family"`

This confirmed existing commands already cover the workflow, especially `debug search source-model-synthesis`, `debug search retained-frontiers`, and `debug solve allocator-ceiling`. No new CLI should be added for this issue.

## Artifact Findings

`source_model_scored.json` is already the correct broader-natural terminal artifact:

- `status`: `terminal`
- `kind`: `post-meta-ceiling-gpr-source-family-synthesis-proof`
- `terminal_reason`: `sort-post-cross-tu-broader-natural-c-rewrite-exhausted/protected-targets-not-jointly-preserved`
- `next_unsupported_source_family`: `sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite`
- `attempted_equivalence_classes`: `["sort-post-cross-tu-broader-natural-c-rewrite"]`
- `candidate_count`: `4`

The best broader-natural candidates are one-hit states. They preserve IG44 but not IG34:

- `post-meta-sort-post-cross-tu-broader-natural-rewrite-nested-text-total-decision`: IG44 to `r25`, IG34 absent or null, `normalized_diff_lines` 22, structural guard rejected as `inline-boundary-toolchain-artifact`.
- `post-meta-sort-post-cross-tu-broader-natural-rewrite-dst-owner-predicate-emission`: IG44 to `r25`, IG34 actual 0, `normalized_diff_lines` 36, structural guard rejected.

`source_family_continuation.json` is also terminal:

- `terminal_reason`: `post-meta-gpr-one-hit-source-family-continuation-exhausted/protected-structural-ceiling`
- It has no complementary IG34 one-hit parent, because the retained one-hit parents are IG44-only.

The current code can already advance when the standalone broader-natural terminal proof is used. This command generates the expected post-broader inline-boundary candidates:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1086_1087_rerun/sort_broader_natural_c/source_model_scored.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --max-per-dimension 10 \
  --continue-after-final-source-family \
  --no-score --json
```

Observed current result:

- `status`: `generated`
- `candidate_count`: `5`
- only generated dimension: `sort-post-broader-natural-inline-boundary-source-hypothesis`

The loop appears when the retained aggregate is used. This command currently regenerates the four broader-natural candidates instead of advancing:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1086_1087_rerun/sort_broader_natural_c/retained_frontiers.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --max-per-dimension 10 \
  --continue-after-final-source-family \
  --no-score --json
```

Observed current result:

- `status`: `generated`
- `candidate_count`: `4`
- only generated dimension: `sort-post-cross-tu-broader-natural-c-rewrite`
- normalized context next family: `sort-no-modeled-source-actionable-family-after-post-cross-tu-selection-swap-source-hypothesis`

The same regression occurs when `allocator_ceiling.json` is provided together with `retained_frontiers.json`.

## Root Cause

The candidate generator is not the primary fault. The post-broader inline-boundary family exists, has seed harvesting, has candidate materialization, and works against the standalone `source_model_scored.json`.

The failure is context arbitration for retained aggregate inputs.

`retained_frontiers.json` contains the correct broader-natural terminal proof in `meta_ceiling.terminal_proof`, but it also contains older `terminal_frontiers[].source_model_proof` entries. One stale source-model proof declares:

- `next_unsupported_source_family`: `sort-no-modeled-source-actionable-family-after-post-cross-tu-selection-swap-source-hypothesis`
- `next_unsupported_source_model`: selection/swap final model
- `attempted_equivalence_classes`: includes `sort-post-inline-boundary-selection-emission-source-shape`

In `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`, `_meta_ceiling_sections()` gathers both the selected retained proof and stale terminal-frontier proofs. `_meta_ceiling_source_model_stage_rank()` then gives high stage rank to proofs containing later Sort dimensions in `attempted_equivalence_classes` or `dimension_ids`.

That means the stale terminal frontier is promoted because it mentions `sort-post-inline-boundary-selection-emission-source-shape`, even though its explicit `next_unsupported_source_family` and `next_unsupported_source_model` are older selection/swap finals. The normalized context becomes internally inconsistent and points back to the family after selection/swap, so `generate_source_family_candidates()` reruns `sort-post-cross-tu-broader-natural-c-rewrite`.

The core rule that is missing:

When a Sort proof has an explicit direct terminal family/model/reason, attempted dimensions from that same proof must not upgrade it beyond the direct terminal family/model it declares. Dimension-only ranking should only be used when no direct Sort terminal family/model/reason is present, or when the dimension is consistent with that direct terminal.

Secondary issues found during review:

1. `build_generated_source_family_payload()` has branches for post-inline and broader-natural generated dimensions, but no equivalent explicit branch for `sort-post-broader-natural-inline-boundary-source-hypothesis`. This can make no-score or zero-candidate reporting fall back to the broader-natural family instead of terminalizing the post-broader family.
2. `_stale_sort_broader_natural_next_model()` checks for the string `"broader natural C sort rewrite"`, while the current model text is `"broader natural C rewrite"`. That can leave stale model text in promotion paths.

## Implementation Plan

### 1. Fix source-model Sort proof stage ranking

File:

`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Functions to change:

- `_meta_ceiling_source_model_stage_rank()`
- Add a small helper near the existing Sort terminal helpers, for example `_sort_direct_source_model_stage_rank(proof: Mapping[str, Any]) -> tuple[int, str] | None`.

Intended logic:

1. Compute a direct Sort terminal stage from explicit proof fields before looking at attempted dimensions:
   - `next_unsupported_source_family`
   - `next_unsupported_source_model`
   - `terminal_reason`
   - `exhausted_source_dimension`
   - selected `source_family_synthesis.next_unsupported_source_family`, if present and consistent
2. Recognize these direct stages, preserving the existing relative order:
   - post-inline selection/emission final family or terminal reason: highest Sort terminal stage.
   - post-broader inline-boundary final family or terminal reason: above broader-natural.
   - broader-natural final family or terminal reason: above selection/swap.
   - selection/swap final family or terminal reason: below broader-natural.
3. If a proof has a direct Sort terminal stage, cap that proof at the direct stage unless attempted dimensions are consistent with the same stage.
4. If a proof has no direct Sort terminal family/model/reason, keep the existing dimension-only stage behavior so older synthetic artifacts still rank correctly.
5. Preserve the existing evidence-count and tie-break behavior within the same direct stage.

Expected effect for the issue artifact:

- The stale terminal frontier with explicit selection/swap next family and attempted post-inline dimension ranks as selection/swap, not post-inline.
- The selected `meta_ceiling.terminal_proof` with explicit broader-natural next family ranks as broader-natural.
- `normalize_meta_ceiling_context()` keeps the broader-natural terminal proof as current context.
- `generate_source_family_candidates(..., continue_after_final_source_family=True)` advances to `sort-post-broader-natural-inline-boundary-source-hypothesis`.

### 2. Add retained-frontier rank parity

File:

`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`

Functions to change:

- `_source_model_proof_stage_rank()`
- Add the same direct Sort terminal-stage guard used by source-model normalization, either as a local helper or by factoring shared constants if that can be done without creating import cycles.

Intended logic:

1. Do not let stale terminal-frontier attempted dimensions outrank an explicit older `next_unsupported_source_family` or `next_unsupported_source_model`.
2. Continue allowing clean direct post-broader and post-inline terminal proofs to outrank broader-natural and selection/swap proofs.
3. Preserve current behavior for non-Sort functions and Sort proofs without direct terminal family/model fields.

This is defensive. The reviewed retained artifact already exposes the correct broader-natural proof in `meta_ceiling.terminal_proof`, but retained triage should not be able to produce the same stale mixed-stage aggregate again.

### 3. Add the missing post-broader generated-payload branch

File:

`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Functions to change:

- `build_generated_source_family_payload()`
- Use the existing helpers:
  - `_should_generate_sort_post_broader_natural_inline_boundary_source_hypothesis()`
  - `_sort_post_broader_natural_inline_boundary_source_family_dimension_rows()`
  - `_sort_post_broader_natural_inline_boundary_source_family_synthetic_dimension_row()`
  - existing terminal constants for `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_*`

Intended logic:

Insert a branch after the post-inline selection/emission branch and before the broader-natural branch:

```python
elif _should_generate_sort_post_broader_natural_inline_boundary_source_hypothesis(
    function_name=function_name,
    current_ceiling=current_ceiling,
    context=context,
    source_text=source_text,
    source_file=source_file,
    continue_after_final_source_family=continue_after_final_source_family,
):
    dimensions = _sort_post_broader_natural_inline_boundary_source_family_dimension_rows(
        rows,
        context=context,
    )
    if not dimensions:
        dimensions = [
            _sort_post_broader_natural_inline_boundary_source_family_synthetic_dimension_row(
                context=context,
                source_file=source_file,
            )
        ]
```

The exact helper signatures should match the existing functions. The important behavior is:

- If post-broader candidates exist, generated payloads report only the post-broader dimension.
- If no candidates exist but the broader-natural terminal sentinel and seed evidence exist, the generated payload terminalizes post-broader, not broader-natural.
- The terminal proof advances to `sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis` when no post-broader source patterns can be emitted.

### 4. Fix stale broader-natural model detection

File:

`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Function to change:

- `_stale_sort_broader_natural_next_model()`

Intended logic:

Replace the brittle substring check with a constant-based comparison where possible:

- Treat `SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_MODEL` as stale when the post-inline final family is authoritative.
- Keep compatibility with the old text `"broader natural C sort rewrite"` if any historical artifact still contains it.
- Also match the current text `"broader natural C rewrite"`.

This prevents promotion code from retaining the broader-natural model string after a later Sort family has become authoritative.

### 5. Keep allocator behavior focused on consuming corrected proofs

File:

`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`

Expected production change:

No allocator logic change is expected unless regression tests expose a separate stale-proof selection path inside allocator ceiling classification.

Validation focus:

- `allocator_ceiling.py` should consume the corrected retained/source-model proof without reporting a next step that reruns `sort-post-cross-tu-broader-natural-c-rewrite`.
- If the allocator receives a post-broader terminal proof, it should report the post-broader terminal family as the current source-shape ceiling.

## Regression Tests

### Source-model synthesis tests

File:

`/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add a synthetic retained aggregate helper:

`_sort_broader_terminal_retained_aggregate_with_stale_terminal_frontier(tmp_path)`

The fixture should include:

- `functions[0].meta_ceiling.terminal_proof`: a broader-natural terminal payload equivalent to the issue artifact.
- `terminal_frontiers[0].source_model_proof`: a stale proof with explicit selection/swap final `next_unsupported_source_family` and `next_unsupported_source_model`, but with attempted dimensions containing `sort-post-inline-boundary-selection-emission-source-shape`.
- Enough `candidate_scores`, `source_hunks`, and `pcdump_path` evidence to resemble the stale artifact and exercise rank tie-breakers.

Add tests:

1. `test_sort_retained_aggregate_prefers_broader_terminal_over_stale_attempted_dimension`
   - Call `normalize_meta_ceiling_context()` on the synthetic aggregate.
   - Assert the normalized context uses `sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite`.
   - Assert it does not regress to `sort-no-modeled-source-actionable-family-after-post-cross-tu-selection-swap-source-hypothesis`.

2. `test_sort_retained_aggregate_continuation_generates_post_broader_not_broader_again`
   - Call `generate_source_family_candidates()` or the public CLI-facing payload builder with `continue_after_final_source_family=True`.
   - Assert all generated candidates have dimension `sort-post-broader-natural-inline-boundary-source-hypothesis`.
   - Assert no candidate has dimension `sort-post-cross-tu-broader-natural-c-rewrite`.
   - Assert the expected five candidate ids are emitted:
     - `post-meta-sort-post-broader-natural-inline-boundary-nested-decision-helper`
     - `post-meta-sort-post-broader-natural-inline-boundary-helper-local-text-total`
     - `post-meta-sort-post-broader-natural-inline-boundary-preloaded-text-helper`
     - `post-meta-sort-post-broader-natural-inline-boundary-decision-return-local`
     - `post-meta-sort-post-broader-natural-inline-boundary-helper-dst-emission-owner`

3. `test_sort_retained_aggregate_without_continuation_does_not_repeat_broader_natural`
   - Use the same aggregate without `continue_after_final_source_family`.
   - Assert broader-natural candidates are not regenerated.
   - Assert terminal output still reports broader-natural final as the current closed source family.

4. `test_sort_post_broader_zero_candidate_payload_terminalizes_post_broader`
   - Use a broader-natural terminal context with seed evidence.
   - Provide source text that intentionally lacks required post-broader source patterns.
   - Call `build_generated_source_family_payload()`.
   - Assert the payload terminalizes `sort-post-broader-natural-inline-boundary-source-hypothesis`, not `sort-post-cross-tu-broader-natural-c-rewrite`.
   - Assert `next_unsupported_source_family` advances to `sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis`.

5. `test_sort_mixed_stage_terminal_frontier_rank_is_capped_by_direct_next_family`
   - Directly compare normalized results or, if private helper testing is acceptable in this file, compare `_meta_ceiling_source_model_stage_rank()` output.
   - Stale proof: direct selection/swap final plus attempted post-inline dimension.
   - Current proof: direct broader-natural final.
   - Assert stale proof ranks below broader-natural.
   - Add a dimension-only proof with no direct family/model and assert it retains existing dimension-only rank behavior.

### Retained-frontier tests

File:

`/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py`

Add tests:

1. `test_retained_frontier_sort_stage_rank_does_not_upgrade_stale_terminal_by_attempted_dimension`
   - Build two source-model proofs:
     - stale selection/swap direct terminal with attempted post-inline dimension.
     - broader-natural direct terminal.
   - Exercise retained-frontier triage selection.
   - Assert the broader-natural direct terminal is retained as the current proof.

2. `test_retained_frontier_sort_post_broader_still_wins_when_direct`
   - Preserve coverage for the intended later state.
   - A clean direct post-broader terminal proof should outrank broader-natural and selection/swap proofs.

### Allocator ceiling tests

File:

`/Users/mike/code/melee/tools/melee-agent/tests/test_allocator_ceiling.py`

Add tests:

1. `test_allocator_ceiling_consumes_retained_broader_terminal_with_stale_frontier`
   - Feed a retained aggregate shaped like the issue artifact.
   - Assert allocator status remains `practical-ceiling` or the expected current-source-shape terminal status.
   - Assert current ceiling next family is `sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite`, not selection/swap.
   - Assert next steps do not ask to rerun broader-natural when continuation is requested.

2. `test_allocator_ceiling_reports_post_broader_terminal_after_post_broader_exhaustion`
   - Feed a post-broader terminal proof.
   - Assert the reported terminal family is `sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis`.

## Smoke Checks

Run focused tests:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  -k "broader_natural or post_broader or stale_terminal_frontier"

PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_retained_frontier_triage.py \
  -k "broader_natural or post_broader or stale_terminal_frontier"

PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_allocator_ceiling.py \
  -k "broader_natural or post_broader or stale_terminal_frontier"
```

Run full affected suites:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  tools/melee-agent/tests/test_retained_frontier_triage.py \
  tools/melee-agent/tests/test_allocator_ceiling.py
```

Replay the real issue artifact against the retained aggregate:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1086_1087_rerun/sort_broader_natural_c/retained_frontiers.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --max-per-dimension 10 \
  --continue-after-final-source-family \
  --no-score --json
```

Expected:

- `status`: `generated`
- `candidate_count`: `5`
- every candidate dimension is `sort-post-broader-natural-inline-boundary-source-hypothesis`
- no candidate dimension is `sort-post-cross-tu-broader-natural-c-rewrite`

Replay with allocator plus retained frontiers:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1086_1087_rerun/sort_broader_natural_c/allocator_ceiling.json \
  --retained-frontiers-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1086_1087_rerun/sort_broader_natural_c/retained_frontiers.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --max-per-dimension 10 \
  --continue-after-final-source-family \
  --no-score --json
```

Expected:

- same five post-broader candidates
- no broader-natural regeneration

Replay without continuation:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1086_1087_rerun/sort_broader_natural_c/retained_frontiers.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --max-per-dimension 10 \
  --no-score --json
```

Expected:

- no regenerated `sort-post-cross-tu-broader-natural-c-rewrite` candidates
- terminal/current-source-shape output still names the broader-natural final family as the closed current source family

Capability smoke checks:

```bash
cd /Users/mike/code/melee
melee-agent capabilities search "sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite"
melee-agent capabilities search "sort-post-broader-natural-inline-boundary-source-hypothesis"
```

## Acceptance Criteria

1. The real `retained_frontiers.json` artifact no longer causes `source-model-synthesis --continue-after-final-source-family` to emit any `sort-post-cross-tu-broader-natural-c-rewrite` candidates.
2. The same retained artifact emits only `sort-post-broader-natural-inline-boundary-source-hypothesis` candidates when continuation is requested.
3. Normalized retained context does not promote stale terminal-frontier attempted dimensions above that proof's explicit direct next family/model.
4. If post-broader candidate generation has no source patterns, the generated payload terminalizes post-broader and reports `sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis`.
5. Allocator ceiling output does not tell the matcher to rerun broader-natural after broader-natural exhaustion.
6. Existing clean post-broader and post-inline terminal proofs still outrank broader-natural proofs.

## Non-Changes

- Do not add a new CLI command.
- Do not modify `mnDiagram_SortNamesByKOs` source for this issue.
- Do not change scoring thresholds for the existing broader-natural candidates.
- Do not mask the retained-frontier stale proof by deleting it from artifacts. The fix should make stage selection robust when stale mixed-stage proofs are present.

