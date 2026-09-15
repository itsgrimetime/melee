# Issue #1109 Plan: materialize Sort full-selection/swap source model

## Scope

Target issue: `#1109 Sort full-selection/swap source model is named but not materialized`

Do not change decompiled repo source. This is a `melee-agent` tooling fix for `mnDiagram_SortNamesByKOs` source-model synthesis.

Primary code under review:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
- `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/source_candidate_scoring.py`
- `/Users/mike/code/melee/tools/melee-agent/src/cli/debug/__init__.py`
- `/Users/mike/code/melee/tools/melee-agent/src/cli/debug/target.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Reporter artifacts reviewed from `/Users/mike/.codex/worktrees/eeff/melee`:

- `build/diagnostics/mndiagram_1108_rerun_allocator_concrete_only.json`
- `build/diagnostics/mndiagram_1108_rerun_source_model_full_selection_swap/result.json`
- `build/diagnostics/mndiagram_1108_rerun_source_model_full_selection_swap/source_family_continuation.json`
- `build/diagnostics/mndiagram_1108_rerun_source_model_full_selection_swap/probes/post-meta-sort-semantic-recombine-28f0d4f55a71.c`
- `build/diagnostics/mndiagram_1108_rerun_source_model_full_selection_swap/probes/post-meta-sort-semantic-recombine-28f0d4f55a71.pcdump.txt`
- `build/diagnostics/mndiagram_1108_rerun_source_model_full_selection_swap/semantic_ig34_repair/result.json`

## Root Cause

The tool already names `SORT_FULL_SELECTION_SWAP_DIMENSION = "sort-full-selection-swap-source-structure"` and has a `_sort_full_selection_swap_source_candidates` hook, but the hook only works on the pristine Sort algorithm region.

The failing reporter baseline is not pristine. The source passed to `source-model-synthesis` is a retained protected-loss seed with:

- a public `mnDiagram_SortNamesByKOs` source function instead of only `mnDiagram_8023FC28`
- `mnDiagram_PostMetaSortUnboundedNamesOwner()` helper ownership for `sorted_names`
- an outer pointer loop using `ll_probe_iter_0 < ll_probe_end_0` rather than `for (i = 0; i < 0x78; i++)`
- retained probe locals such as `target_repair_live_range_ig39_probe` and `target_repair_index_ig44_max_idx_probe`
- emission through `*ll_probe_iter_0 = temp` or pointer-derived destinations

`_full_selection_swap_patcher()` calls `_replace_sort_algorithm_region()`, which uses one exact canonical source block. That block does not match the retained seed, so every full-selection patcher returns `None`. This produces the observed zero-candidate blocker:

`sort-full-selection-swap-source-model-not-materialized`

There is a second blocking symptom. Because full-selection is currently additive instead of a staged/exclusive family, `generate_source_family_candidates()` still emits older init/swap subfamily probes and semantic recombines. The old subfamily probes inherit the retained helper function but do not set `requires_full_unit_source`, so live scoring rejects them with:

`candidate source defines helper function(s) outside mnDiagram_SortNamesByKOs`

`classify_source_family_scores()` correctly refuses to terminalize score rows with `score_error`, so the final status becomes:

`blocked / score-rows-not-terminal-safe`

That is why continuation can only report a blocked full-selection dimension rather than a populated terminal proof.

## Desired Behavior

When allocator/source-model context names `sort-full-selection-swap-source-structure`, `source-model-synthesis` should:

1. Generate bounded retained C probes for the full selection/swap region, not only smaller init/swap subfamilies.
2. Generate from the retained seed shape used by the reporter, including pointer-loop and helper-owned source variants.
3. Score those candidates with `target_score`, retained `.c`, and retained `.pcdump.txt`.
4. Return `actionable` if any candidate jointly hits `IG34->r27` and `IG44->r25`.
5. Otherwise terminalize the full-selection family and hand off to `sort-whole-function-control-data-flow-rewrite` without `score-rows-not-terminal-safe`.

## Implementation Plan

### 1. Make full-selection/swap a staged generator

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Change `generate_source_family_candidates`:

- Add a `sort_full_selection_swap_only` boolean after the existing post-inline/post-cross-TU checks and before generic Sort patcher selection.
- Set it when `_should_generate_sort_full_selection_swap(context)` is true and no later Sort stage is active.
- Include it in the `specs = [] if (...) else _candidate_patcher_specs(...)` suppression list.
- Add an early return branch after `_sort_full_selection_swap_source_candidates(...)` so this stage emits only full-selection candidates.
- Keep the existing zero-candidate blocker path so missing source spans still produce the explicit required-pattern diagnostic.

This prevents legacy subfamily score errors from blocking the full-selection proof.

### 2. Replace exact block matching with a retained-region matcher

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Change `_full_selection_swap_patcher` to call a new helper:

- Add `_replace_sort_full_selection_swap_region(function_text: str, replacement: str) -> str | None`.
- First try the existing `_replace_sort_algorithm_region` for the pristine fixture path.
- Then match the retained protected-loss/source-model seed shape with brace-aware region replacement.

Add helper functions:

- `_find_sort_full_selection_swap_region(function_text: str) -> tuple[int, int] | None`
- `_find_enclosing_sort_pointer_loop_region(function_text: str) -> tuple[int, int] | None`
- `_balanced_block_end(text: str, open_brace_index: int) -> int | None`
- `_sort_full_selection_region_semantic_checks(region: str) -> bool`

The semantic checks should require the real Sort structure rather than exact formatting:

- `max_idx = i`
- inner `for (j = i + 1; j < 0x78; j++)`
- `GetNameText`
- `totals[...]`
- `max_idx = j`
- `if (max_idx != i)`
- `while (max_idx > i)` or a counted backward shift
- final write through `dst[i]`, `*ll_probe_iter_0`, or an explicit insertion pointer

For the retained reporter shape, replace the whole local pointer-loop block:

```c
{
    u8* ll_probe_iter_0 = common_source_r39_probe;
    u8* ll_probe_end_0 = dst + 0x78;
    for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++) {
        ...
    }
}
```

with the generated full-selection region. This avoids leaving stale `ll_probe_iter_0` cursor writes inside the replacement.

### 3. Preserve full-unit scoring for retained helper-bearing probes

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

In `_sort_full_selection_swap_source_candidates`, add validation metadata:

- `requires_full_unit_source: True`
- `requires_structural_guard: True`
- `source_model_layer_dimension_id: SORT_FULL_SELECTION_SWAP_DIMENSION`
- `required_source_patterns: list(SORT_FULL_SELECTION_SWAP_REQUIRED_SOURCE_PATTERNS)`
- existing `required_preserved_assignments: ["IG34->r27", "IG44->r25"]`

Also add `requires_full_unit_source=True` on the candidate dict if needed for direct consumers.

Add `SORT_FULL_SELECTION_SWAP_DIMENSION` to `_FULL_UNIT_REQUIRED_SOURCE_CONTEXT_DIMENSIONS`, or rename that set to cover staged full-source-model dimensions. This makes accidental offline/non-full-unit score rows diagnose as a full-unit scoring misuse instead of an opaque `score-row-error`.

The scoring plumbing already supports this:

- `_candidate_requires_full_unit_source`
- `_score_command_hint`
- `score_source_candidates`
- `source_candidate_scoring._score_source_command`
- `debug target score-source --full-unit-source`

### 4. Keep terminal classification strict but reachable

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

No broad relaxation is needed. After the generation/scoring fixes, existing functions should terminalize full-selection exhaustion:

- `_can_terminalize_required_assignment_exhaustion`
- `_can_terminalize_structural_guard_exhaustion`
- `_terminal_next_unsupported_source_model`
- `_terminal_next_unsupported_source_family`
- `_full_selection_swap_next_hint`
- `_classified_full_selection_swap_terminal_exhaustion`

Only adjust these if the new full-selection rows are not included in `attempted_equivalence_classes`, `exhausted_dimensions`, `source_hunks_by_candidate`, or `retained_scored_probes`.

Do not terminalize rows with compile errors. The fix is to avoid those errors through staged generation and full-unit scoring.

### 5. Capability alias

File: `/Users/mike/code/melee/tools/melee-agent/src/cli/capabilities.py`

Add search aliases for:

- `sort full selection swap source model`
- `sort-full-selection-swap-source-structure`
- `full selection swap source structure`

Each should route to `debug search source-model-synthesis`.

Update `/Users/mike/code/melee/tools/melee-agent/tests/test_capabilities.py` accordingly.

## Regression Tests

Add tests in `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`.

1. `test_sort_full_selection_swap_generation_from_retained_pointer_seed`
   - Add a fixture source based on `_sort_protected_loss_seed_source()` but with the reporter shape:
     - `mnDiagram_PostMetaSortUnboundedNamesOwner`
     - `u8* sorted_names = mnDiagram_PostMetaSortUnboundedNamesOwner();`
     - `common_source_r39_probe`
     - `ll_probe_iter_0` outer loop
     - `target_repair_live_range_ig39_probe`
     - `target_repair_index_ig44_max_idx_probe`
   - Use `_sort_full_selection_swap_context()`.
   - Assert full-selection candidates are generated and have non-empty `source_hunks`.
   - Assert each full-selection candidate has `requires_full_unit_source`.
   - Assert generated source retains the public Sort function and helper context.

2. `test_sort_full_selection_swap_stage_suppresses_legacy_subfamilies`
   - Same context and retained pointer seed.
   - Assert emitted dimensions are only `sort-full-selection-swap-source-structure` for Sort source candidates in this stage.
   - Assert no `sort-init-indexed-write` or `sort-swap-slot-lvalue` candidates are emitted.

3. `test_sort_full_selection_swap_retained_seed_classifier_terminalizes_without_score_row_errors`
   - Generate retained pointer-seed full-selection candidates.
   - Score with fake payloads that have no `score_error`, accepted structural guard, and one protected miss.
   - Assert status is `terminal`.
   - Assert `next_unsupported_source_model == SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_MODEL`.
   - Assert `next_unsupported_source_family == SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY`.
   - Assert `reason != "score-rows-not-terminal-safe"`.
   - Assert retained score rows include `source_hunks` and `requires_full_unit_source`.

4. `test_cli_source_model_synthesis_writes_full_selection_retained_probes`
   - Use `CliRunner` with `source-model-synthesis --no-score --write-probes`.
   - Input meta: `_sort_full_selection_swap_context()` serialized.
   - Source: retained pointer seed fixture.
   - Assert written candidate paths exist.
   - Assert candidate IDs include the five `post-meta-sort-full-selection-*` variants.
   - Assert score command hints include `--full-unit-source`.

5. `test_cli_source_model_synthesis_scores_full_selection_retained_probes`
   - Monkeypatch `score_source_candidates` to assert every scored full-selection candidate has `requires_full_unit_source`.
   - Return fake retained pcdump paths and one-hit target scores.
   - Assert CLI status is terminal or actionable, not blocked.
   - Assert output contains retained `.c` and `.pcdump.txt` paths for full-selection candidates.

Update capability tests for the new aliases.

## Verification Commands

Run focused tests:

```bash
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k 'full_selection_swap'
python -m pytest tools/melee-agent/tests/test_capabilities.py -k 'full_selection or source_model_synthesis'
python -m pytest tools/melee-agent/tests/test_transform_corpus_full_unit_scoring.py
```

Then rerun the reporter workflow from `/Users/mike/code/melee` or the reporter worktree:

```bash
melee-agent debug search source-model-synthesis \
  -f mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1108_rerun_allocator_concrete_only.json \
  --source-file /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1107_rerun/sort_target_live_range/recombine/combine-ig34_live-ig44_alias-16c6b8d83a.c \
  --target /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1103_rerun/sort_common_subexpr_bridge/target_ig34_ig44.json \
  --write-probes /tmp/issue-1109-full-selection-probes \
  --max-per-dimension 5 \
  --score \
  --checkdiff-guard \
  --continue-after-final-source-family \
  --json
```

Expected verification outcome:

- `generated_family_dimensions` has generated or scored full-selection candidates.
- No full-selection blocker with `sort-full-selection-swap-source-model-not-materialized`.
- No top-level `reason: score-rows-not-terminal-safe`.
- Each full-selection scored row has `target_score`, retained `source_retained`, and retained `pcdump_path`.
- Stop condition is satisfied if any row hits `IG34->r27` and `IG44->r25`; otherwise a populated terminal proof names `sort-whole-function-control-data-flow-rewrite`.

## Non-goals

- Do not change `src/melee/mn/mndiagram.c`.
- Do not loosen score-row terminal safety for compile errors.
- Do not treat unscored or missing-score candidates as terminal evidence.
- Do not add unbounded source generation. Keep candidate count controlled by `--max-per-dimension`.

## Key Risks

- The new retained-region matcher can become too broad. Mitigate with semantic checks and brace-balanced replacement, and keep the pristine exact matcher as the first path.
- Full-unit scoring is slower and touches the real compile unit during guard checks. It already has restore/lock handling, but focused CLI tests should assert `--full-unit-source` is present.
- The full-selection generated source may compile but fail the structural guard because it intentionally rewrites a larger region. That is acceptable if it terminalizes with retained proof instead of blocking.
- Making full-selection staged/exclusive reduces simultaneous old-subfamily diagnostics in this mode. That is intentional for #1109 because the allocator has already named the next whole-family source model.
