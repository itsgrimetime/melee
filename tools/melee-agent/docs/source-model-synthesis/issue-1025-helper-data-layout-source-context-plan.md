# Issue 1025: post-whole-function helper/data-layout source-context handoff

Working repo reviewed: `/Users/mike/code/melee`

Production files were not edited. The only write intended by this review is this plan file.

## Evidence reviewed

- `melee-agent capabilities search "post whole function helper data layout source context generator source-model-synthesis Sort"` returned only broad existing tools (`debug search source-model-synthesis`, `debug target score-source`, `layout audit`, retained search commands), not a specific post-whole-function helper/data-layout handoff generator.
- The exact rerun artifacts named in the issue are not present in this checkout:
  - `build/diagnostics/mndiagram_1024_rerun/...`
  - `build/diagnostics/mndiagram_989_rerun/...`
  - `sort_source_model_whole_function_scored.json`
  - `sort_frontiers_after_whole_function.json`
  - `sort_allocator_after_whole_function.json`
  - `terminal_from_scores.json`
- Present #1024 artifacts:
  - `build/diagnostics/issue_1024_whole_function/generated.json`
  - `build/diagnostics/issue_1024_global_smoke/generated.json`
  - both generate exactly five candidates, all in `sort-whole-function-control-data-flow-rewrite`:
    - `post-meta-sort-whole-function-source-owner-unified`
    - `post-meta-sort-whole-function-selected-record-carried`
    - `post-meta-sort-whole-function-selected-name-total-carried`
    - `post-meta-sort-whole-function-shift-emission-indexed`
    - `post-meta-sort-whole-function-prefix-insertion-rebuild`
- Source reviewed:
  - `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
  - `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
  - `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`
  - `/Users/mike/code/melee/tools/melee-agent/src/inline_leverage/boundary_variants.py`
  - `/Users/mike/code/melee/src/melee/mn/mndiagram.c`
  - `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`
- Focused tests run:
  - `python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k "whole_function_control_data_flow or allocator_ceiling_prefers_full_selection" -q`
  - Result: `5 passed, 92 deselected`.
- One-off ranking repro against current code:
  - stale full-selection proof priority: `(6, 2, 1, 1)`
  - newer whole-function-exhausted proof priority: `(1, 2, 1, 1)`
  - This proves the current retained-frontier ranking can prefer older full-selection text over the newer helper/data-layout handoff proof.

## Root cause

`post_meta_source_family_synthesis.py` already defines the next unsupported family after #1024:

- model: `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_MODEL`
- family: `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_FAMILY = "sort-helper-extraction-data-layout-or-cross-function-rewrite"`

But that family is only a string handoff. It is not a real synthesis dimension, has no generator, no zero-candidate blocker, no terminal-safe classifier path, and no downstream retained-frontier ranking stage.

The direct consequence is twofold:

1. Directly feeding the whole-function proof back into `source-model-synthesis` has no executable helper/data-layout/cross-function layer to materialize.
2. `retained_frontier_triage._source_model_proof_stage_rank()` ranks the older full-selection handoff (`sort-whole-function-control-data-flow-rewrite`) as stage 6, but ranks the newer whole-function exhausted helper/data-layout proof as generic stage 1. That is the specific regression that lets retained-frontiers and allocator-ceiling outputs preserve older full-selection text instead of the newest unsupported source model.

There is a secondary classifier gap: `classify_source_family_scores()` can terminalize required-assignment exhaustion for full-selection and whole-function dimensions, but not for the proposed helper/data-layout dimension. Even if candidates existed and all scored 0/2, the current code would tend to block rather than emit the terminal proof requested by #1025.

## Decision

Materialize bounded candidates first. Do not immediately terminally prove the helper/data-layout layer exhausted.

Reason: the evidence only closes the whole-function body-rewrite layer and the existing `mnDiagram_SumNameKOs` helper boundary. It does not close other same-TU helper extraction, data-layout overlay/accessor, or cross-function source-context variants around `mnDiagram_8023FC28`. The source has concrete untested context levers:

- helper extraction around the Sort comparison predicate using `GetNameText` plus `totals`;
- helper extraction around selected-name shift/emission;
- source-level data-layout/accessor variants for `mnDiagram_804A0750_t`, `mnDiagram_804A076C_t`, and `mnDiagram_Assets`;
- same-TU source-context rewrites that insert static inline helpers outside the function body while scoring `mnDiagram_8023FC28`.

The stop condition should be: generate a bounded set, score every candidate with target-score and structural guard evidence, then either return ranked actionable retained C candidates/source hunks or emit a terminal proof naming this helper/data-layout/cross-function family as exhausted.

## Production changes to make

### 1. Add an executable post-whole-function source-context family

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add constants:

- `SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION = "sort-helper-extraction-data-layout-or-cross-function-rewrite"`
- `SORT_HELPER_DATA_LAYOUT_CONTEXT_COMPONENTS`
- `SORT_HELPER_DATA_LAYOUT_CONTEXT_REQUIRED_SOURCE_PATTERNS`
- `SORT_HELPER_DATA_LAYOUT_CONTEXT_SOURCE_REGION_PATTERN_BLOCKER`
- `SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_MODEL`
- optionally `SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_FAMILY`, if the terminal proof should name a final unmodeled TU/data-symbol layer rather than leave `next_unsupported_source_family` absent.

Add the new dimension to `_PROFILES[SORT_FUNCTION]["dimensions"]`.

Add trigger logic:

- `_should_generate_sort_helper_data_layout_context(context)`
- Trigger when:
  - `context.next_unsupported_source_model` or nested proof text equals/contains `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_MODEL`, or
  - nested `next_unsupported_source_family` equals `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_FAMILY`.
- Suppress when this new dimension is already exhausted in `context.current_ceiling`, or when the next model/family is the new terminal exhausted model/family.

Add candidate generation:

- `_sort_helper_data_layout_context_source_candidates(...)`
- It should edit full source text, not just `mnDiagram_8023FC28`, because this layer must be able to insert static inline helpers and change file-local data-layout source context.
- It should be called from `generate_source_family_candidates()` after the whole-function generator.
- When this family is triggered, skip older local/full-selection/whole-function families so direct handoff cannot regenerate the older full-selection family.

Initial bounded variants should include at least:

- `post-meta-sort-source-context-comparison-helper`
  - Insert a static inline helper before `mnDiagram_8023FC28` that owns the candidate/max name text and total comparison, then call it from the inner loop.
- `post-meta-sort-source-context-comparison-helper-split-text-total`
  - Similar helper family but with text checks and KO total comparison split into helper-local temporaries.
- `post-meta-sort-source-context-shift-emission-helper`
  - Insert a static inline helper that performs selected-name extraction plus backward emission, then call it from the `if (max_idx != i)` block.
- `post-meta-sort-source-context-sorted-names-accessor`
  - Insert a static inline accessor returning the sorted names pointer from the `mnDiagram_804A0750`/`mnDiagram_Assets` overlay, then use that owner in init, selection, and emission.
- `post-meta-sort-source-context-layout-overlay-local`
  - Use a bounded alternate file-local overlay/accessor spelling for the `sorted_fighters` + `sorted_names` layout without changing production data symbols.

Each candidate must carry:

- `dimension_id = SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION`
- `required_preserved_assignments = ["IG34->r27", "IG44->r25"]`
- `requires_target_score_validation = True`
- `requires_structural_guard = True`
- `score_function = context.source_function or context.function`
- source hunks over the full source, including helper/type/accessor insertions.
- source components distinguishing helper extraction, data layout, and cross-function context.

### 2. Make this family terminal-safe after real scores

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Extend:

- `_can_terminalize_structural_guard_exhaustion()`
- `_can_terminalize_required_assignment_exhaustion()`
- `_terminal_next_unsupported_source_model()`
- `_full_selection_swap_next_hint()` (rename to a more general stage-next-hint helper if useful)

Required behavior:

- If any candidate in `SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION` is structurally accepted and jointly satisfies IG34->r27 and IG44->r25, return `status: actionable` with ranked candidates/source hunks.
- If all bounded candidates are real-scored and none jointly satisfy both assignments, emit `status: terminal`.
- Terminal proof must include:
  - attempted/exhausted dimension `sort-helper-extraction-data-layout-or-cross-function-rewrite`;
  - scored candidate ids;
  - retained scored probes with target-score virtuals and pcdump paths when available;
  - source hunks/components by candidate;
  - `next_unsupported_source_model` naming helper extraction/data layout/cross-function source context exhaustion;
  - structural guard blockers and protected-target blockers where applicable.

### 3. Preserve the newest proof in retained-frontiers

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`

Add constants matching the synthesis file:

- `_SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION`
- `_SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_MODEL`
- `_SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_FAMILY`
- `_SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION`
- `_SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_MODEL`

Update:

- `_SORT_SOURCE_FAMILY_DIMENSIONS`
- `_source_model_synthesis_profile()` candidate prefixes/family prefixes/strategy tokens:
  - include `post-meta-sort-whole-function-`
  - include `post-meta-sort-source-context-`
  - include `helper-data-layout`, `source-context`, `cross-function`, `whole-function`.
- `_fallback_source_model_dimensions()`
- `_dimension_from_candidate_id()`
- `_source_model_next_unsupported_source_model()`
- `_source_model_proof_stage_rank()`

Stage ranking should be monotonic:

- local/legacy source families < natural rewrite < semantic < protected-loss init-lifetime < full-selection/swap < whole-function control/data-flow < helper/data-layout/cross-function.

The direct regression to prevent:

- stale full-selection proof must not outrank a whole-function exhausted proof whose next family is `sort-helper-extraction-data-layout-or-cross-function-rewrite`.
- if the helper/data-layout layer is later terminal, that terminal proof must outrank the whole-function handoff too.

### 4. Improve allocator-ceiling propagation/rendering

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`

The primary allocator fix should come from retained-frontier ranking, because `classify_allocator_ceiling()` already sets `current_ceiling` from `retained_meta["terminal_proof"]`.

Still update rendering/next steps so the newest family is visible:

- In `_next_steps()`, when retained meta is terminal, include `next_unsupported_source_family` alongside `next_unsupported_source_model`.
- In `_extend_retained_frontiers_meta_ceiling()`, render `next_unsupported_source_family` and summarize `next_unsupported_source_spans` if present.
- Do not hard-code the older full-selection text anywhere in allocator next steps.

## Regression tests

File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add tests near the existing whole-function tests.

1. `test_sort_helper_data_layout_context_generation_from_whole_function_terminal`
   - Build a terminal whole-function payload using existing helpers.
   - Normalize it into context.
   - Run `generate_source_family_candidates()`.
   - Assert candidates are only in `SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION`.
   - Assert candidate ids include comparison helper, shift helper, and layout/accessor variants.
   - Assert source hunks include full-source insertions before `mnDiagram_8023FC28`.
   - Assert validation metadata requires IG34->r27 and IG44->r25 plus structural guard.

2. `test_sort_helper_data_layout_context_classifier_requires_joint_targets`
   - Score one candidate with only IG34 matched: terminal, protected targets not jointly preserved.
   - Score one candidate with both IG34 and IG44 matched and structural guard accepted: actionable.
   - Score one candidate with both matched but structural guard rejected: terminal with structural guard blocker.

3. `test_sort_helper_data_layout_context_exhaustion_terminalizes`
   - Score all bounded helper/data-layout candidates as 0/2 or 1/2 but never 2/2.
   - Assert terminal proof names the helper/data-layout/cross-function dimension in attempted/exhausted dimensions.
   - Assert `next_unsupported_source_model` is the new helper/data-layout exhausted model and does not regress to full-selection or whole-function text.
   - Assert retained scored probes and source hunks/components are retained.

4. `test_cli_source_model_synthesis_writes_helper_data_layout_context_probes`
   - Feed a whole-function terminal JSON to CLI `source-model-synthesis`.
   - Assert probe files are written and include helper/accessor insertions outside `mnDiagram_8023FC28`.

5. `test_allocator_ceiling_prefers_whole_function_handoff_over_stale_full_selection`
   - Mirror the existing stale-continuation test.
   - Provide two artifacts:
     - stale full-selection terminal proof;
     - newer whole-function terminal proof with `next_unsupported_source_family = sort-helper-extraction-data-layout-or-cross-function-rewrite`.
   - Run `triage_retained_frontiers()` then `classify_allocator_ceiling()`.
   - Assert `current_ceiling["next_unsupported_source_model"]` equals the whole-function exhausted helper/data-layout handoff model.
   - Assert `current_ceiling["next_unsupported_source_family"]` equals `sort-helper-extraction-data-layout-or-cross-function-rewrite`.
   - Assert allocator `next_steps` mention the helper/data-layout family, not the older full-selection/swap source model.

6. `test_retained_frontier_normalizes_helper_data_layout_source_context_dimensions`
   - Use minimal score/candidate rows with `post-meta-sort-source-context-*` ids.
   - Assert retained-frontier synthesis infers the new dimension and computes the correct next model/family.

## Command-level smoke checks

Before implementation:

```bash
melee-agent capabilities search "post whole function helper data layout source context generator source-model-synthesis Sort"
```

Focused unit tests:

```bash
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  -k "helper_data_layout or whole_function_control_data_flow or allocator_ceiling_prefers" \
  -q
```

No-score CLI generation smoke:

```bash
melee-agent debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json build/diagnostics/mndiagram_1024_rerun/source_model_whole_function/sort_source_model_whole_function_scored.json \
  --source-file src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/issue_1025_helper_data_layout/probes \
  --max-per-dimension 10 \
  --no-score \
  --json
```

Expected no-score result after implementation:

- `status: generated`
- candidate dimension only `sort-helper-extraction-data-layout-or-cross-function-rewrite`
- generated `.c` probes contain static inline helper/accessor or layout-source-context hunks.

Live scoring smoke when target JSON is available:

```bash
melee-agent debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json build/diagnostics/mndiagram_1024_rerun/source_model_whole_function/sort_source_model_whole_function_scored.json \
  --source-file src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/issue_1025_helper_data_layout/probes \
  --target <target.json> \
  --cflags-from src/melee/mn/mndiagram.c \
  --score \
  --checkdiff-guard \
  --json > build/diagnostics/issue_1025_helper_data_layout/sort_source_context_scored.json
```

Post-classification smoke:

```bash
melee-agent debug solve retained-frontiers \
  --function mnDiagram_SortNamesByKOs \
  --artifact build/diagnostics/issue_1025_helper_data_layout/sort_source_context_scored.json \
  --json > build/diagnostics/issue_1025_helper_data_layout/retained_frontiers.json
```

```bash
melee-agent debug solve allocator-ceiling \
  --function mnDiagram_SortNamesByKOs \
  --evidence build/diagnostics/issue_1025_helper_data_layout/retained_frontiers.json \
  --json > build/diagnostics/issue_1025_helper_data_layout/allocator_ceiling.json
```

Expected allocator smoke result:

- `current_ceiling.next_unsupported_source_model` preserves the newest helper/data-layout/cross-function model.
- `current_ceiling.next_unsupported_source_family` is not the older full-selection/whole-function family unless the helper/data-layout layer has not yet been scored.

General build/test smoke after production code changes:

```bash
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -q
python configure.py && ninja
```

## Implementation order

1. Add constants/profile dimension/gating in `post_meta_source_family_synthesis.py`.
2. Add bounded helper/data-layout/cross-function candidate generation.
3. Extend classification and terminal proof next-hint logic.
4. Update retained-frontier stage ranking and normalization.
5. Update allocator rendering/next steps.
6. Add regression tests.
7. Run focused tests, then the broader test/build smoke.

## Acceptance criteria

- Direct source-model synthesis from a whole-function exhausted proof no longer regenerates older full-selection candidates.
- It either emits ranked helper/data-layout/cross-function candidates or a scored terminal proof for that exact family.
- Retained-frontiers and allocator-ceiling preserve the newest whole-function -> helper/data-layout handoff over stale full-selection artifacts.
- A future terminal helper/data-layout proof supersedes the whole-function handoff in ranking.
- Candidate/terminal artifacts retain source hunks, source components, pcdump paths, structural guard status, and IG34/IG44 target-score evidence.
