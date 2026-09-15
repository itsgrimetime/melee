# Issue #1058 Plan: Sort needs next source family after post-broader inline-boundary exhaustion

## Scope

Planning only. Do not edit production code as part of this task.

Repo reviewed: `/Users/mike/code/melee`

Issue artifacts reviewed:

- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1056_1057_rerun/sort_post_broader_inline_boundary/source_model_sort_post_broader_inline_scored.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1056_1057_rerun/sort_frontiers_after_post_broader_inline/sort_allocator_after_post_broader_inline.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1056_1057_rerun/sort_source_family_continuation_after_post_broader_inline/source_family_continuation_after_post_broader_inline.json`

Primary code reviewed:

- `tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
- `tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
- `tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`
- `tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`
- `tools/melee-agent/tests/test_retained_frontier_triage.py`
- `tools/melee-agent/tests/test_allocator_ceiling.py`

## Current diagnostics

The post-broader inline-boundary source-model artifact is terminal:

- `status`: `terminal`
- `terminal_reason`: `sort-post-broader-natural-inline-boundary-source-hypothesis-exhausted/protected-targets-not-jointly-preserved`
- `next_unsupported_source_family`: `sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis`
- attempted dimension: `sort-post-broader-natural-inline-boundary-source-hypothesis`
- generated/scored candidates: 5

The five consumed candidates are:

- `post-meta-sort-post-broader-natural-inline-boundary-nested-decision-helper`
- `post-meta-sort-post-broader-natural-inline-boundary-helper-local-text-total`
- `post-meta-sort-post-broader-natural-inline-boundary-preloaded-text-helper`
- `post-meta-sort-post-broader-natural-inline-boundary-decision-return-local`
- `post-meta-sort-post-broader-natural-inline-boundary-helper-dst-emission-owner`

The best row is `decision-return-local`: it preserves IG44->r25 but misses IG34, with IG34 landing at r4. The rest are structural rejects or lose both protected targets. The source-family continuation artifact then includes the same five inline-boundary candidates as exhausted continuation candidates, so the pipeline has no distinct next source-hypothesis layer to hand to the matcher.

Allocator diagnostics correctly surface the inline-boundary terminal as the current ceiling:

- `status`: `practical-ceiling`
- `source_shape_exhausted`: `true`
- current ceiling family: `sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis`
- next steps only say no modeled retained-frontier source-actionable lanes remain.

## Root Cause

`post_meta_source_family_synthesis.py` has a modeled Sort ladder through:

1. legacy source-family dimensions
2. natural rewrite
3. semantic algorithm
4. full selection/swap
5. whole-function control/data-flow
6. helper/data-layout
7. TU data-symbol/helper-boundary
8. unbounded TU data ownership
9. cross-TU linkage
10. post-cross-TU selection/swap source hypothesis
11. post-cross-TU broader natural C rewrite
12. post-broader-natural inline-boundary source hypothesis

The ladder stops at the inline-boundary family. The terminal constants explicitly say no modeled source-actionable Sort family remains:

- `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_FAMILY`
- `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_MODEL`

That is now stale. The artifacts prove the inline-boundary family was consumed, not that all useful source hypotheses were consumed.

The current generator has a continuation flag, but it only knows how to continue from the previous broader-natural terminal into the inline-boundary family:

- `_should_generate_sort_post_broader_natural_inline_boundary_source_hypothesis(...)`
- `_sort_post_broader_natural_inline_boundary_source_hypothesis_candidates(...)`

There is no analogous `should_generate`/candidate family for the terminal family after inline-boundary exhaustion. As a result, the continuation layer can only re-emit or re-summarize already-consumed inline-boundary probes instead of producing a new source family.

`retained_frontier_triage.py` and `allocator_ceiling.py` are mostly doing the right thing: they preserve and rank the inline-boundary terminal. Their missing piece is only awareness of a new successor dimension/family once production synthesis grows one.

## Smallest Complete Design

Add one bounded Sort source-hypothesis layer after inline-boundary exhaustion:

### New dimension

Use a name that makes the ordering and non-duplication obvious:

```text
sort-post-inline-boundary-selection-emission-source-shape
```

Suggested constants in `post_meta_source_family_synthesis.py`:

```python
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION = (
    "sort-post-inline-boundary-selection-emission-source-shape"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_CANDIDATE_PREFIX = (
    "post-meta-sort-post-inline-boundary-selection-emission-"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_REASON = (
    "sort-post-inline-boundary-selection-emission-source-shape-exhausted/"
    "protected-targets-not-jointly-preserved"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_BLOCKER = (
    "sort-post-inline-boundary-selection-emission-source-shape/"
    "protected-targets-not-jointly-preserved"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_SOURCE_REGION_PATTERN_BLOCKER = (
    "sort-post-inline-boundary-selection-emission-source-shape/source-patterns-not-found"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-post-inline-boundary-selection-emission-source-shape"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_MODEL = (
    "Sort post-inline-boundary selection/emission source-shape synthesis exhausted "
    "bounded selected-name carry, selected total/text lifetime, and selected-name "
    "emission-owner probes seeded from the retained post-broader inline-boundary "
    "one-hit row without jointly preserving IG34/IG44 under the structural guard. "
    "No further modeled source-actionable Sort family remains after this "
    "post-inline-boundary selection/emission layer."
)
```

This is intentionally not another helper-boundary family. The consumed layer already tested comparison decision/helper-boundary shapes. The next layer should keep the best helper/decision shape as a seed and vary the selected-name and emission ownership around it.

### Candidate variants

Seed from the best inline-boundary row, especially the one-hit IG44 row:

- `decision-return-local` currently preserves IG44 and loses IG34. It should be the primary seed.
- Preserve seed metadata: `seed_candidate_id`, `seed_source_retained`, `seed_pcdump_path`, `seed_target_score`, `seed_structural_guard`, `seed_one_hit_targets`, `seed_source_hunks`, `seed_source_components`, `ranked_seed_candidates`.

Generate 3-5 bounded candidates under the new prefix. Keep `max_per_dimension` behavior identical to existing families.

Proposed variants:

1. `helper-selected-name-carried`
   - Keep the post-broader helper/decision boundary.
   - Introduce a selected-name local before the inner loop.
   - On helper success, update both `max_idx` and selected-name.
   - Tests whether the selected-name lifetime, not the comparison helper itself, owns the missing IG34 pressure.

2. `helper-selected-total-carried`
   - Carry selected-name plus selected total/text across the inner loop.
   - Candidate name/text/total remains per-iteration.
   - Tests whether selected comparison state must survive the loop while the helper remains a source boundary.

3. `helper-emission-cursor-owner`
   - Leave comparison helper shape intact.
   - Rewrite the swap/emission block to use a local selected name and explicit `dst + max_idx` insertion cursor.
   - Avoid replaying `helper-dst-emission-owner`; this variant is post-helper and should be based on the retained helper seed, not a fresh comparison helper probe.

4. `helper-selected-state-emission-coupled`
   - Combine selected-name carry with explicit selected-name emission cursor.
   - This is the bounded coupled variant if the isolated lifetime or emission-owner variants are insufficient.

Optional fifth variant if needed after implementation details are clear:

5. `helper-latched-decision-selected-name`
   - Retain `candidate_better` from the consumed `decision-return-local` seed, but assign/update selected-name in the same guarded block.
   - Only include if it produces a distinct hunk from the first four variants.

### Generator integration

In `generate_source_family_candidates(...)`:

1. Compute `sort_post_inline_boundary_selection_emission_only` before `sort_post_broader_natural_inline_boundary_only`.
2. If active, suppress all prior Sort dimensions and generate only the new dimension.
3. Add an early terminal guard after this family is exhausted, analogous to the existing post-cross-TU and inline-boundary guards.

Pseudo-flow:

```python
sort_post_inline_boundary_selection_emission_only = (
    _should_generate_sort_post_inline_boundary_selection_emission_source_shape(
        context,
        continue_after_final_source_family=continue_after_final_source_family,
    )
)
sort_post_broader_natural_inline_boundary_only = (
    not sort_post_inline_boundary_selection_emission_only
    and _should_generate_sort_post_broader_natural_inline_boundary_source_hypothesis(...)
)
```

Trigger rules:

- function is `mnDiagram_SortNamesByKOs`
- register class is `gpr`
- `continue_after_final_source_family=True`
- current proof/family/model contains the inline-boundary final family/model
- inline-boundary dimension evidence exists in attempted/exhausted dimensions
- seed rows exist from `candidate_scores` or `retained_scored_probes`
- at least one seed has source evidence and preserves exactly one protected target, preferably IG44

Add helpers mirroring the existing naming pattern:

- `_should_generate_sort_post_inline_boundary_selection_emission_source_shape`
- `_sort_post_inline_boundary_selection_emission_ready_terminal`
- `_sort_post_inline_boundary_selection_emission_terminal_sentinel`
- `_sort_post_inline_boundary_selection_emission_dimension_evidence`
- `_sort_post_inline_boundary_selection_emission_seed_rows`
- `_is_sort_post_inline_boundary_selection_emission_seed_row`
- `_sort_post_inline_boundary_selection_emission_seed_rank_key`
- `_sort_post_inline_boundary_selection_emission_source_shape_specs`
- `_sort_post_inline_boundary_selection_emission_source_shape_candidates`
- one patcher family that starts from `_sort_lower_drift_seed_source_text(seed, context) or source_text`

The seed selector should rank:

1. IG44 one-hit rows first.
2. structurally accepted/toolchain-artifact rows before broad structural rejects.
3. lower normalized diff first.
4. target-progress rows before no-hit rows.
5. deterministic candidate_id tiebreak.

### Terminal and zero-candidate handling

Wire the new dimension into the existing terminal machinery:

- `_PROFILES[SORT_FUNCTION]["dimensions"]`
- `_source_model_synthesis_profile(function)`:
  - dimensions
  - candidate prefixes
  - family prefixes
  - strategy tokens
- `_source_model_next_unsupported_source_model`
- `_terminal_next_unsupported_source_model`
- `_terminal_next_unsupported_source_family`
- `_zero_candidate_terminal_metadata`
- `_should_terminalize_zero_candidate_generation`
- `_sort_post_inline_boundary_selection_emission_zero_candidate_generation_blockers`
- terminal proof retention in `_build_zero_candidate_source_family_terminal_proof`

For scored exhaustion, the proof should say:

- attempted/exhausted dimension: `sort-post-inline-boundary-selection-emission-source-shape`
- next unsupported family/model: the new final family/model
- terminal blocker: `sort-post-inline-boundary-selection-emission-source-shape/protected-targets-not-jointly-preserved`

For zero generation, emit a terminal proof with:

- source-region blocker: `sort-post-inline-boundary-selection-emission-source-shape/source-patterns-not-found`
- required evidence:
  - inline-boundary final no-modeled-source sentinel
  - inline-boundary exhausted dimension evidence
  - retained inline-boundary source seed with source hunks and pcdump path
  - one-hit protected-target row from the consumed inline-boundary layer

### Retained-frontier triage integration

Add matching constants in `retained_frontier_triage.py`:

- `_SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION`
- final family/model strings

Update:

- `_SORT_SOURCE_FAMILY_DIMENSIONS`
- `_SORT_FALLBACK_DEFERRED_SOURCE_FAMILY_DIMENSIONS`
- `_dimension_from_candidate_id`
- `_source_model_synthesis_profile` candidate/family/strategy tokens
- `_source_model_next_unsupported_source_model`
- source-model proof priority/ranking so this new terminal ranks above the inline-boundary terminal. Inline-boundary currently ranks at stage 14, so make this stage 15.
- terminal proof normalization paths that copy `next_unsupported_source_family`, `next_unsupported_source_model`, `next_unsupported_source_dimension`, spans, and terminal blockers from synthesis to the top-level source-model proof.

Do not demote or suppress the existing inline-boundary terminal. It remains the current ceiling until the new source-model-synthesis artifact exists.

### Allocator ceiling integration

Allocator can already render generic next unsupported source model/family. Add a small Sort-specific recognition only if needed for clarity:

- If current proof mentions the new dimension or final family, add a next step like:
  - `Post-inline-boundary selection/emission source-shape synthesis is terminal for the current modeled Sort lane.`
- Ensure `classify_allocator_ceiling(...)` selects the new terminal over stale inline-boundary artifacts by relying on the retained-frontier rank update.

## Regression Tests To Write First

### `tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

1. `test_sort_post_broader_inline_boundary_terminal_context_generates_no_old_probes`
   - Build a context from an inline-boundary terminal payload.
   - Call `generate_source_family_candidates(..., continue_after_final_source_family=False)`.
   - Assert `[]`.

2. `test_sort_post_broader_inline_boundary_continuation_generates_selection_emission_only`
   - Same context, but with `continue_after_final_source_family=True`.
   - Assert candidates are generated.
   - Assert all `dimension_id == SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION`.
   - Assert no candidate ids start with `post-meta-sort-post-broader-natural-inline-boundary-`.
   - Assert all candidate ids start with `post-meta-sort-post-inline-boundary-selection-emission-`.
   - Assert source components include selected-name carry and emission-owner components.
   - Assert score command includes `--full-unit-source` and `--checkdiff-guard`.

3. `test_sort_post_inline_boundary_selection_emission_terminal_payload_sets_final_family`
   - Use generated candidates and synthetic score rows that do not jointly preserve IG34/IG44.
   - Call the terminal/classifier path used by existing post-cross-TU tests.
   - Assert terminal reason, exhausted dimension, next family/model, and terminal blockers use the new constants.

4. `test_sort_post_inline_boundary_selection_emission_zero_generation_terminalizes_with_pattern_blocker`
   - Use an inline-boundary terminal context with source text that lacks the expected Sort selection/swap region.
   - Assert zero generation terminal payload has the new dimension and source-region pattern blocker.

5. `test_cli_source_model_synthesis_writes_post_inline_boundary_selection_emission_probes`
   - Similar to the existing CLI tests for helper-data-layout and TU source context.
   - Input meta: inline-boundary terminal payload.
   - Command args include `--continue-after-final-source-family`, `--write-probes`, `--max-per-dimension 10`, `--no-score`, `--json`.
   - Assert generated files exist and contain retained helper/decision seed plus selected-name/emission ownership changes.

### `tools/melee-agent/tests/test_retained_frontier_triage.py`

6. `test_retained_frontier_prefers_post_inline_boundary_selection_emission_terminal_over_inline_boundary`
   - Provide stale inline-boundary terminal and new post-inline-boundary selection/emission terminal artifacts.
   - Assert meta ceiling terminal proof uses the new family.

7. `test_retained_frontier_normalizes_post_inline_boundary_selection_emission_dimension_from_candidate_prefix`
   - Artifact omits dimension but uses the new candidate prefix.
   - Assert synthesis attempted classes include the new dimension, not the old inline-boundary dimension.

8. `test_retained_frontier_keeps_inline_boundary_terminal_until_post_inline_artifact_exists`
   - Existing behavior should remain: with only inline-boundary terminal, the current family is still `sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis`.

### `tools/melee-agent/tests/test_allocator_ceiling.py`

9. `test_allocator_ceiling_current_ceiling_uses_post_inline_boundary_selection_emission_terminal`
   - Feed retained-frontiers output containing both inline-boundary terminal and new terminal.
   - Assert `current_ceiling["next_unsupported_source_family"]` is the new final family.
   - Assert next steps mention the new terminal/family.

10. Keep existing inline-boundary allocator test passing:
   - `test_allocator_ceiling_current_ceiling_uses_post_broader_inline_boundary_terminal`

## Command-Level Smoke Checks

After production changes:

```bash
cd /Users/mike/code/melee
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k "post_broader or post_inline or inline_boundary or selection_emission"
python -m pytest tools/melee-agent/tests/test_retained_frontier_triage.py -k "post_broader or post_inline or inline_boundary or selection_emission"
python -m pytest tools/melee-agent/tests/test_allocator_ceiling.py -k "post_broader or post_inline or inline_boundary or selection_emission"
```

Generate the new probes from the real issue artifact:

```bash
cd /Users/mike/code/melee
melee-agent debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1056_1057_rerun/sort_post_broader_inline_boundary/source_model_sort_post_broader_inline_scored.json \
  --source-file src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/issue_1058/post_inline_selection_emission_probes \
  --max-per-dimension 10 \
  --continue-after-final-source-family \
  --no-score \
  --json
```

Expected smoke assertions:

- output `status` is `generated`
- `candidate_count` is greater than zero
- all generated candidate ids start with `post-meta-sort-post-inline-boundary-selection-emission-`
- no generated candidate ids start with `post-meta-sort-post-broader-natural-inline-boundary-`
- every candidate has `dimension_id == sort-post-inline-boundary-selection-emission-source-shape`

Then run retained-frontier and allocator smoke using the newly generated/scored artifact once scoring is enabled:

```bash
melee-agent debug search retained-frontiers \
  --function mnDiagram_SortNamesByKOs \
  --artifact /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1056_1057_rerun/sort_post_broader_inline_boundary/source_model_sort_post_broader_inline_scored.json \
  --artifact build/diagnostics/issue_1058/post_inline_selection_emission_scored.json \
  --json > build/diagnostics/issue_1058/retained_frontiers_after_post_inline.json

melee-agent debug target allocator-ceiling \
  --function mnDiagram_SortNamesByKOs \
  --artifact build/diagnostics/issue_1058/retained_frontiers_after_post_inline.json \
  --json
```

Expected allocator smoke:

- before the new scored artifact exists, current ceiling remains the inline-boundary terminal
- after the new scored terminal exists, current ceiling becomes `sort-no-modeled-source-actionable-family-after-post-inline-boundary-selection-emission-source-shape`

## Implementation Notes

- Do not reuse the consumed inline-boundary prefix for the new probes. Prefix separation is the easiest regression guard.
- Do not treat free-text mentions of `inline-boundary` as enough to generate the old layer once the inline-boundary final family is present.
- Keep `continue_after_final_source_family` as the explicit gate for post-terminal generation.
- Preserve `source_hunks`, `source_components`, and seed paths in candidate metadata; retained-frontier triage relies on this metadata to make the next artifact actionable.
- Follow existing Sort post-cross-TU and Draw post-stack-clean patterns: terminalize zero-generation only when the exact post-terminal source layer is active, and rank the newer terminal over stale prior terminals.
