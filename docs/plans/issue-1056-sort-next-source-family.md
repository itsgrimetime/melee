# Fix #1056 Plan: Sort Next Source Family After Broader Natural Rewrite Exhaustion

## Scope

Issue #1056 is for `source-model-synthesis` on `mnDiagram_SortNamesByKOs`.
The current artifacts prove that the post-cross-TU broader natural-C rewrite
layer was scored and exhausted, but the tool now reports a final no-modeled
family:

- current terminal family:
  `sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite`
- current terminal reason:
  `sort-post-cross-tu-broader-natural-c-rewrite-exhausted/protected-targets-not-jointly-preserved`
- best retained row:
  `post-meta-sort-post-cross-tu-broader-natural-rewrite-nested-text-total-decision`
- best row result: IG44->r25 preserved, IG34 absent/null, `normalized_diff_lines=22`
- structural guard rejection:
  `inline-boundary-toolchain-artifact`

The requested fix is not another run of
`sort-post-cross-tu-broader-natural-c-rewrite`. Add a bounded next
source-hypothesis layer that starts from the low-drift broader-natural seed and
models the comparison decision/inline-boundary source shape.

Do not change production or tests in this plan/design pass. This document is
the persisted implementation spec.

## Reviewed Files And Artifacts

Implementation reviewed:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`
- `/Users/mike/code/melee/src/melee/mn/mndiagram.c`

Tests reviewed:

- `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_allocator_ceiling.py`

Issue artifacts reviewed:

- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1054_1055_rerun/sort_broader_natural_rewrite_from_allocator/source_model_sort_broader_natural_scored.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1054_1055_rerun/sort_frontiers_after_broader_natural/sort_allocator_after_broader_natural.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1054_1055_rerun/sort_frontiers_after_broader_natural/sort_frontiers_after_broader_natural.json`

Capability audit:

```bash
melee-agent capabilities search source-model-synthesis
```

Result: existing source-model synthesis and source scoring commands are present.
This issue needs a new modeled family inside the existing command surface, not a
new CLI/tool.

## Root Cause

`post_meta_source_family_synthesis.py` already has an ordered Sort source-model
chain through:

- `sort-post-cross-tu-selection-swap-source-hypothesis`
- `sort-post-cross-tu-broader-natural-c-rewrite`

The broader-natural generator is correctly bounded. It emits four candidates:

- `post-meta-sort-post-cross-tu-broader-natural-rewrite-full-region-predicate-owner`
- `post-meta-sort-post-cross-tu-broader-natural-rewrite-selected-candidate-lifetime-pack`
- `post-meta-sort-post-cross-tu-broader-natural-rewrite-dst-owner-predicate-emission`
- `post-meta-sort-post-cross-tu-broader-natural-rewrite-nested-text-total-decision`

The best row is `nested-text-total-decision`, which preserves IG44 but loses
IG34 and is rejected as an `inline-boundary-toolchain-artifact`. That is useful
evidence: the next layer should not widen natural comparison rewrites again. It
should test whether the missing source assumption is a comparison decision
boundary/helper boundary seeded from that low-drift row.

The implementation gap is that broader-natural exhaustion is treated as final:

- `SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_FAMILY`
  currently means no further modeled Sort family.
- `generate_source_family_candidates()` has
  `_should_generate_sort_post_cross_tu_broader_natural_rewrite()` but no later
  Sort stage.
- `_terminal_next_unsupported_source_model()` and
  `_terminal_next_unsupported_source_family()` return the broader-natural final
  model/family when this dimension is attempted.
- `retained_frontier_triage.py` ranks broader natural as the latest Sort stage,
  then allocator reports "No modeled retained-frontier source-actionable lanes
  remain."

Existing helper/data-layout and TU helper-boundary layers are not sufficient
because they were run before this low-drift broader-natural seed existed. The
new layer must be post-broader-natural, seed-aware, and bounded to comparison
decision boundaries so it does not reopen old helper/data-layout, cross-TU, or
natural-rewrite families.

## Proposed New Source Family

Add a new Sort dimension after broader natural rewrite exhaustion:

- dimension:
  `sort-post-broader-natural-inline-boundary-source-hypothesis`
- candidate prefix:
  `post-meta-sort-post-broader-natural-inline-boundary-`
- terminal reason:
  `sort-post-broader-natural-inline-boundary-source-hypothesis-exhausted/protected-targets-not-jointly-preserved`
- terminal blocker:
  `sort-post-broader-natural-inline-boundary-source-hypothesis/protected-targets-not-jointly-preserved`
- source-region pattern blocker:
  `sort-post-broader-natural-inline-boundary-source-hypothesis/source-patterns-not-found`
- final terminal family:
  `sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis`

Final model text:

```text
Sort post-broader-natural inline-boundary source-hypothesis synthesis exhausted
bounded comparison decision/helper-boundary probes seeded from the lower-drift
broader-natural row without jointly preserving IG34/IG44 under the structural
guard. No further modeled source-actionable Sort family remains after this
post-broader-natural inline-boundary layer.
```

Required source components:

- `sort-post-broader-natural-seed-low-drift-retention`
- `sort-post-broader-natural-comparison-helper-boundary`
- `sort-post-broader-natural-text-total-owner`
- `sort-post-broader-natural-decision-return-shape`
- `sort-post-broader-natural-emission-owner-coupling`

Required source patterns/evidence:

- broader-natural terminal sentinel:
  `sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite`
- exhausted dimension:
  `sort-post-cross-tu-broader-natural-c-rewrite`
- retained scored seed with source hunks and pcdump path
- seed target score preserves exactly one protected target, preferably IG44->r25
- seed structural guard classification is `inline-boundary-toolchain-artifact`
- seed drift is lower-drift enough to be useful, suggested cap:
  `normalized_diff_lines <= 24` for the primary seed, fallback cap `<= 30`

## Candidate Set

Generate at most five full-unit candidates. Each candidate is seeded from
`post-meta-sort-post-cross-tu-broader-natural-rewrite-nested-text-total-decision`
when available; otherwise use the best broader-natural retained row ranked by
target hits, structural-guard classification, and normalized diff lines.

Candidate IDs:

1. `post-meta-sort-post-broader-natural-inline-boundary-nested-decision-helper`
   - Extract the nested text/total decision into a `static inline int` helper.
   - The caller keeps `selected_name` and `candidate_name` locals, calls the
     helper, then updates `max_idx`.

2. `post-meta-sort-post-broader-natural-inline-boundary-helper-local-text-total`
   - Helper receives `selected_name`, `candidate_name`, and `totals`.
   - Helper owns both `GetNameText` calls and `totals[...]` loads.

3. `post-meta-sort-post-broader-natural-inline-boundary-preloaded-text-helper`
   - Caller owns `selected_text`, `candidate_text`, `selected_total`, and
     `candidate_total`.
   - Helper only owns the boolean decision shape.

4. `post-meta-sort-post-broader-natural-inline-boundary-decision-return-local`
   - Helper or inline decision returns into an explicit `int candidate_better`
     local before `if (candidate_better != 0) max_idx = j;`.
   - This tests whether IG34 needs a return/local lifetime rather than another
     expression rewrite.

5. `post-meta-sort-post-broader-natural-inline-boundary-helper-dst-emission-owner`
   - Combine the best nested-decision helper boundary with the existing local
     `dst` emission owner spelling, without regenerating the broader natural
     predicate/emission family.

Every candidate must include:

- `dimension_id == "sort-post-broader-natural-inline-boundary-source-hypothesis"`
- `validation_metadata.post_broader_natural_inline_boundary_source_hypothesis == True`
- `requires_full_unit_source == True`
- `requires_structural_guard == True`
- `requires_target_score_validation == True`
- `score_function == mnDiagram_8023FC28`
- `required_preserved_assignments == ["IG34->r27", "IG44->r25"]`
- `seed_candidate_id`
- `seed_source_retained`
- `seed_pcdump_path`
- `seed_structural_guard`
- `seed_target_score`
- `source_hunks`
- `source_components`
- score command hint containing `--full-unit-source --checkdiff-guard`

## Implementation Plan

### 1. Add constants and profile wiring

File:
`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add constants near the broader-natural constants:

- `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION`
- `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_FAMILY`
- `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_MODEL`
- `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_TERMINAL_REASON`
- `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_TERMINAL_BLOCKER`
- `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_SOURCE_REGION_PATTERN_BLOCKER`
- `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_CANDIDATE_PREFIX`
- component and required-pattern tuples

Add the new dimension after
`SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION` in the Sort profile
dimension order.

### 2. Add stage detector and seed selection

File:
`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add:

- `_should_generate_sort_post_broader_natural_inline_boundary_source_hypothesis(context, *, continue_after_final_source_family=False)`
- `_sort_post_broader_natural_inline_boundary_terminal_sentinel(context)`
- `_sort_post_broader_natural_inline_boundary_seed_rows(context)`
- `_sort_post_broader_natural_inline_boundary_seed_rank_key(row)`
- `_is_sort_post_broader_natural_inline_boundary_row(row)`

The stage detector should require:

- Sort function and GPR profile
- explicit `continue_after_final_source_family=True`
- the broader-natural final sentinel in either `context.current_ceiling` or
  `context.next_unsupported_source_family`
- broader-natural exhausted dimension evidence
- retained scored seed evidence with source hunks/source file and pcdump
- best seed is a one-hit protected-target row and has
  `inline-boundary-toolchain-artifact` structural guard classification

Default generation must remain unchanged: without the continuation flag,
existing no-modeled broader-natural terminal artifacts should still produce no
new candidates.

### 3. Add candidate materializer

File:
`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add:

- `_sort_post_broader_natural_inline_boundary_source_hypothesis_spec(...)`
- `_sort_post_broader_natural_inline_boundary_source_hypothesis_specs()`
- `_sort_post_broader_natural_inline_boundary_source_hypothesis_candidates(...)`
- `_post_broader_natural_inline_boundary_patcher(...)`
- helper patchers for the five candidate shapes above

Wire this stage into `generate_source_family_candidates()`:

- compute `sort_post_broader_natural_inline_boundary_only` before the broader
  natural flag can fall through to old families;
- suppress all old Sort local/natural/semantic/full-selection/cross-TU families
  when this flag is active;
- append only the new candidates and return.

### 4. Terminalize zero-candidate and all-scored exhausted states

File:
`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add zero-candidate blocker support:

- `_sort_post_broader_natural_inline_boundary_zero_candidate_generation_blockers(...)`
- include the pattern blocker in `_zero_candidate_generation_blockers()`
- include it in `_should_terminalize_zero_candidate_generation()`
- map it in `_zero_candidate_terminal_metadata()`

Update scored terminal helpers:

- `_terminal_next_unsupported_source_model()`
- `_terminal_next_unsupported_source_family()`
- `_sort_post_broader_natural_inline_boundary_terminal_attempt(...)`
- terminal reason/blocker selection in `classify_source_family_scores()`
- source-family continuation terminal preservation if needed

The new layer terminalizes only when all generated candidates are scored and no
candidate jointly preserves IG34->r27 and IG44->r25 with accepted structural
guard. One-hit rows should be retained in `retained_scored_probes` for the next
allocator/retained-frontiers proof.

### 5. Retained-frontier triage ordering

File:
`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`

Add the new dimension after
`_SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION`:

- `_SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION`
- `_SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_MODEL`
- `_SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_FAMILY`

Update:

- `_SORT_SOURCE_FAMILY_DIMENSIONS`
- `_SORT_FALLBACK_DEFERRED_SOURCE_FAMILY_DIMENSIONS`
- `_source_model_proof_stage_rank()` so new stage outranks broader natural
- `_source_model_synthesis_profile()` Sort `candidate_prefixes`,
  `family_prefixes`, and `strategy_tokens`
- `_fallback_source_model_dimensions()`
- `_dimension_from_candidate_id()`
- any terminal group/proof selection helper that currently treats broader
  natural as the final Sort source-model stage

Expected behavior:

- A broader-natural terminal proof remains the best current proof until a
  post-broader inline-boundary terminal/actionable artifact exists.
- A post-broader inline-boundary terminal proof supersedes stale broader-natural
  terminal artifacts.
- Allocator still reads `current_ceiling` from retained-frontiers; no primary
  allocator logic change is expected.

### 6. CLI/capability discoverability

File:
`/Users/mike/code/melee/tools/melee-agent/src/cli/capabilities.py`

Add search aliases for:

- `sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite`
- `sort-post-broader-natural-inline-boundary-source-hypothesis`
- `sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis`

They should point to:

- `debug search source-model-synthesis`
- `debug search retained-frontiers`

No new command is needed.

## Regression Tests

### File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add constants in the test file:

- `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION`
- `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_FAMILY`
- `SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_TERMINAL_REASON`

Add fixtures:

- `_sort_post_broader_natural_inline_boundary_context(tmp_path)`
  built from the existing broader-natural terminal helper or a new direct
  terminal fixture containing a `nested-text-total-decision` retained seed.
- `_sort_post_broader_natural_inline_boundary_terminal_payload(tmp_path)`
  for retained-frontiers tests.

New tests:

1. `test_sort_post_broader_natural_terminal_context_generates_no_old_probes`
   - Context is broader-natural terminal.
   - `generate_source_family_candidates(..., include_source=True)` returns `[]`.
   - This preserves default no-rerun behavior.

2. `test_sort_post_broader_natural_continuation_generates_only_inline_boundary_dimension`
   - Same context with `continue_after_final_source_family=True`.
   - Candidates are non-empty.
   - Candidate dimensions are exactly
     `sort-post-broader-natural-inline-boundary-source-hypothesis`.
   - No candidates from old local, natural, semantic, full-selection,
     post-cross-TU selection-swap, or broader-natural dimensions.

3. `test_sort_post_broader_natural_inline_boundary_candidates_require_seed_and_full_unit_scoring`
   - Assert every candidate has source hunks/components.
   - Assert validation metadata fields listed in the candidate contract.
   - Assert the seed candidate ID ends with `nested-text-total-decision` when
     that seed is present.
   - Assert command hint contains `--full-unit-source` and `--checkdiff-guard`.

4. `test_sort_post_broader_natural_inline_boundary_classifier_requires_joint_targets`
   - IG34-only score terminalizes with the new terminal reason.
   - IG44-only score terminalizes with the new terminal reason and records
     `required-assignment-not-preserved:IG34->r27`.
   - Joint IG34+IG44 accepted score is actionable and retains `source_retained`,
     `pcdump_path`, `target_score`, and `source_hunks`.

5. `test_sort_post_broader_natural_inline_boundary_zero_candidates_terminalize_with_seed_evidence`
   - Build generated payload with no candidates and continuation flag.
   - Assert `status == "terminal"`.
   - Assert `next_unsupported_source_family` is
     `sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis`.
   - Assert retained seed rows, source hunks, and pcdump path survive into
     `source_model_proof.source_family_synthesis`.

6. Update
   `test_sort_post_cross_tu_broader_natural_rewrite_classifies_seed_loss_and_joint_hit`
   only if future broader-natural terminal output is changed to point directly
   at the new dimension. If compatibility keeps the existing broader-natural
   no-modeled sentinel, add a new test instead of changing this one.

### File: `/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py`

Add tests:

1. `test_retained_frontier_prefers_post_broader_natural_inline_boundary_terminal_over_broader_natural`
   - Write stale broader-natural terminal artifact.
   - Write newer post-broader inline-boundary terminal artifact.
   - Run `triage_retained_frontiers(...)`.
   - Assert selected terminal proof next family is
     `sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis`.

2. `test_retained_frontier_keeps_broader_natural_terminal_until_post_broader_artifact_exists`
   - Use only broader-natural terminal artifact.
   - Assert selected proof remains the broader-natural terminal sentinel.
   - This prevents triage from inventing the next layer before source-model
     synthesis has emitted evidence.

3. `test_retained_frontier_normalizes_post_broader_inline_boundary_dimension_from_candidate_prefix`
   - Minimal terminal artifact with only candidate IDs starting
     `post-meta-sort-post-broader-natural-inline-boundary-`.
   - Assert dimension inference returns
     `sort-post-broader-natural-inline-boundary-source-hypothesis`.

### File: `/Users/mike/code/melee/tools/melee-agent/tests/test_allocator_ceiling.py`

Add allocator-level coverage:

1. `test_allocator_ceiling_current_ceiling_uses_post_broader_inline_boundary_terminal`
   - Build retained-frontiers output from the two terminal artifacts above.
   - Pass it into `classify_allocator_ceiling(...)`.
   - Assert:
     - `status == "practical-ceiling"`
     - `terminal_reason == "retained-frontiers-all-known-frontiers-exhausted/current-source-shape-ceiling"`
     - `current_ceiling.next_unsupported_source_family == "sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis"`
     - allocator `next_steps` names that same family.

## Command Smokes

Run focused tests:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  -k "post_broader_natural or broader_natural_rewrite"

PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_retained_frontier_triage.py \
  -k "post_broader_natural or broader_natural"

PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_allocator_ceiling.py \
  -k "post_broader_natural or broader_natural"
```

Run affected suites:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  tools/melee-agent/tests/test_retained_frontier_triage.py \
  tools/melee-agent/tests/test_allocator_ceiling.py
```

Default replay against the issue artifacts should not regenerate old probes:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1054_1055_rerun/sort_frontiers_after_broader_natural/sort_allocator_after_broader_natural.json \
  --retained-frontiers-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1054_1055_rerun/sort_frontiers_after_broader_natural/sort_frontiers_after_broader_natural.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --max-per-dimension 10 \
  --no-score \
  --json
```

Expected default:

- `status=terminal` or zero-candidate terminal-compatible payload
- no local/natural/semantic/broader-natural probes generated
- current broader-natural sentinel remains visible

Opt-in generation check:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1054_1055_rerun/sort_frontiers_after_broader_natural/sort_allocator_after_broader_natural.json \
  --retained-frontiers-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1054_1055_rerun/sort_frontiers_after_broader_natural/sort_frontiers_after_broader_natural.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --write-probes /Users/mike/code/melee/build/diagnostics/issue_1056_sort_post_broader_inline_boundary/probes \
  --max-per-dimension 8 \
  --continue-after-final-source-family \
  --no-score \
  --json
```

Expected opt-in:

- generated candidates are only
  `sort-post-broader-natural-inline-boundary-source-hypothesis`
- candidate IDs start with
  `post-meta-sort-post-broader-natural-inline-boundary-`
- metadata references the `nested-text-total-decision` seed when available

Full scoring check:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1054_1055_rerun/sort_frontiers_after_broader_natural/sort_allocator_after_broader_natural.json \
  --retained-frontiers-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1054_1055_rerun/sort_frontiers_after_broader_natural/sort_frontiers_after_broader_natural.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --target /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_958_rerun/sort_target_from_diff_live.json \
  --cflags-from /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --write-probes /Users/mike/code/melee/build/diagnostics/issue_1056_sort_post_broader_inline_boundary/probes \
  --max-per-dimension 8 \
  --continue-after-final-source-family \
  --score \
  --json
```

Retained-frontiers and allocator consumption check after scoring:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent python -m src.cli debug search retained-frontiers \
  --function mnDiagram_SortNamesByKOs \
  --artifact /Users/mike/code/melee/build/diagnostics/issue_1056_sort_post_broader_inline_boundary/source_model_sort_post_broader_inline_boundary_scored.json \
  --json > /Users/mike/code/melee/build/diagnostics/issue_1056_sort_post_broader_inline_boundary/retained_frontiers.json

PYTHONPATH=tools/melee-agent python -m src.cli debug solve allocator-ceiling \
  --function mnDiagram_SortNamesByKOs \
  --retained-frontiers-json /Users/mike/code/melee/build/diagnostics/issue_1056_sort_post_broader_inline_boundary/retained_frontiers.json \
  --json
```

## Risks And Boundaries

- Do not weaken the structural guard. The new family should generate better
  source hypotheses, not make `inline-boundary-toolchain-artifact` actionable.
- Do not rerun closed families. Candidate dimensions must not include old local,
  natural, semantic, full-selection, cross-TU, post-cross-TU selection-swap, or
  broader-natural dimensions.
- Keep the candidate count small. Five candidates are enough for this layer.
- Preserve compatibility with existing broader-natural terminal artifacts by
  treating
  `sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite`
  as the trigger sentinel for the explicit continuation.
- Only allocator rendering should change if it already displays the selected
  source family; allocator classification should continue to consume
  retained-frontiers `terminal_proof`.
