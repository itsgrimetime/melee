# Issue 1041 Plan: Post-all-known Draw Source Hypothesis

## Scope

Plan issue #1041 for `/Users/mike/code/melee` at commit `6d59b086b`.
This is a planning-only pass. Do not edit production code while planning.

Issue target:

- Tool family: `source-model-synthesis`, `retained-frontiers`, `allocator-ceiling`
- Function: `mnDiagram_DrawCellNumber`
- Relevant source alias: `mnDiagram_80241E78`
- Artifact root inspected: `/Users/mike/.codex/worktrees/eeff/melee`
- Existing terminal artifacts:
  - `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1040_rerun/draw_after_post_whole_family_source_model/source_model_after_post_whole_family_noscore.json`
  - `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1040_rerun/draw_frontiers_after_post_whole_suppression/draw_frontiers_after_1040_suppression.json`
  - `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1040_rerun/draw_frontiers_after_post_whole_suppression/draw_allocator_after_1040_suppression.json`

Important local environment note:

`PYTHONPATH` currently imports `/Users/mike/.codex/worktrees/eeff/melee/tools/melee-agent` before `/Users/mike/code/melee/tools/melee-agent`. Smoke commands for this issue must set:

```bash
export PYTHONPATH=/Users/mike/code/melee/tools/melee-agent
```

or prefix the command with `PYTHONPATH=/Users/mike/code/melee/tools/melee-agent`, otherwise the command surface may be stale and omit `debug search source-model-synthesis`, `debug search retained-frontiers`, and `debug solve allocator-ceiling`.

## Root Cause

#1040 fixed the duplicate-loop behavior. The current #1041 gap is different: Draw reaches a valid terminal proof for the modeled whole-function FPR family, then the pipeline has no modeled source-actionable stage after that family.

The hard stop is in:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
  - `generate_source_family_candidates`
  - `_draw_post_source_context_whole_function_exhausted`
  - `_draw_post_source_context_whole_function_stage_active`
  - `_draw_post_source_context_whole_function_candidates`
  - `_build_zero_candidate_source_family_terminal_proof`
  - `build_terminal_source_family_proof`
  - `_draw_post_source_context_whole_function_retained_terminal_evidence`
  - `_draw_post_source_context_whole_function_specs`

`generate_source_family_candidates` returns `[]` when `_draw_post_source_context_whole_function_exhausted(context)` is true. That is correct for suppressing #1040's repeated whole-function family, but it also prevents a next source-hypothesis family from consuming retained/allocator evidence after all known frontiers are exhausted.

The Draw profile and ranking code know no later Draw dimension:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
  - `_PROFILES[DRAW_FUNCTION]["dimensions"]`
  - current Draw dimensions stop at `DRAW_POST_SOURCE_CONTEXT_DIMENSION`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
  - Draw retained source-family constants
  - `_source_model_proof_stage_rank`
  - `triage_retained_frontiers`
  - `synthesize_retained_frontier_meta_ceiling`

The discovery layer names the unsupported family, but does not synthesize candidates:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_source_context_discovery.py`
  - `PostSourceContextFprCeilingNextDimensionDiscovery.discover`
  - `_draw_post_source_context_stage`
  - `_has_post_whole_function_stage`
  - `_normalize_retained_evidence`

After retained-frontiers aggregates the terminal evidence, allocator-ceiling can only report the practical ceiling:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`
  - `classify_allocator_ceiling`
  - `_retained_frontiers_meta_ceiling`
  - `_retained_meta_rank`
  - `_post_source_context_discovery_meta`
  - `_post_source_context_next_dimension_from_retained_meta`
  - `_next_steps`
  - `_extend_retained_frontiers_meta_ceiling`

There is also a presentation/ranking wrinkle in the inspected artifacts. The final source-model artifact correctly reports:

- `terminal_reason`: `draw-post-source-context-whole-function-fpr-source-model-exhausted/no-floor-improvement`
- `best_candidate_id`: `draw-post-source-context-whole-function-joint-data-owner-with-loop-object`
- `best_target_matched`: `1/3`
- `best_expression_matched`: `1/3`
- `next_unsupported_source_family`: `draw-no-modeled-source-actionable-family-after-post-source-context-whole-function-fpr-source-model`

But the retained-frontiers and allocator artifacts can still surface the older post-source-context unsupported-family hint:

- `draw-next-unsupported-source-dimension-after-loop-body-callsite-and-object-base-lifetime-source-context`

instead of a newer post-all-known handoff. That happens because no stage exists after the final whole-function sentinel to outrank both the stale discovery proof and the final no-modeled-family proof.

## Evidence Summary

Source-model artifact:

- `status`: `terminal`
- `candidate_count`: `0`
- `generated_candidate_count`: `6`
- `scored_candidate_count`: `6`
- Six retained whole-function candidates were scored as evidence only:
  - `draw-post-source-context-whole-function-data-jobjs-parent-and-loop-object-owners`
  - `draw-post-source-context-whole-function-base-spacing-owner-record`
  - `draw-post-source-context-whole-function-joint-data-owner-with-loop-object`
  - `draw-post-source-context-whole-function-animation-callarg-translate-owner`
  - `draw-post-source-context-whole-function-parent-addchild-translate-owner`
  - `draw-post-source-context-whole-function-whole-function-combined-low-risk`
- Best retained whole-function row remained `1/3` target and `1/3` expression.
- `next_unsupported_source_spans` include the exhausted whole-function span and earlier source-context spans around the preloop object/base/data region, loop-body callsite interaction, and retained-baseline backtracking source context.

Retained-frontiers artifact:

- `status`: `all-known-frontiers-exhausted`
- `next_frontier`: `null`
- `meta_ceiling.status`: `terminal-current-source-shape-ceiling`
- `meta_ceiling.terminal_reason`: `retained-frontiers-all-known-frontiers-exhausted/current-source-shape-ceiling`
- `terminal_proof.reason`: `no-modeled-source-actionable-frontiers-remain`
- `closed_families` include `post-ceiling-source-model-proof` and `post-source-context-fpr-ceiling-next-dimension`

Allocator artifact:

- `status`: `practical-ceiling`
- `terminal_reason`: `retained-frontiers-all-known-frontiers-exhausted/current-source-shape-ceiling`
- `current_ceiling.reason`: `no-modeled-source-actionable-frontiers-remain`
- `current_ceiling.exhausted_dimensions`: `["draw-post-source-context-whole-function-fpr-source-model"]`
- `source_shape_exhausted`: `true`
- `missing_evidence`: `[]`

This is a feature gap, not a failed loop guard.

## Desired New Capability

Add a reusable Draw-specific source-model stage after all known Draw retained frontiers are exhausted:

- Proposed dimension id: `draw-post-all-known-frontiers-source-context-hypothesis`
- Proposed family id: `draw-post-all-known-source-context-hypothesis`
- Proposed proof model: `Draw post-all-known source-context hypothesis after whole-function FPR ceiling`

The stage should activate only after the whole-function FPR family is terminal and retained-frontiers reports no actionable known frontier. It should generate bounded, semantically valid C candidates that are broader than the already modeled expression, source-context, whole-function, and lower-hill families.

Candidate output must remain source-actionable:

- ranked retained C source candidates
- `source_hunks`
- `pcdump` or retained pcdump references where available
- `target_score`
- `expression_score`
- structural guard result
- terminal summaries with explicit unsupported source dimensions if the bounded stage does not improve the floor

Stop condition:

- If a candidate improves target score, expression score, or accepted structural guard over the retained floor, retained-frontiers should surface it as an actionable next lane.
- If all bounded candidates fail to improve, source-model-synthesis should emit a terminal proof for `draw-post-all-known-frontiers-source-context-hypothesis` with retained evidence and an explicit remaining unsupported source model.

## Implementation Approaches

### Approach 1: Add a First-class Post-all-known Source-model Stage

Implement a new Draw dimension inside `post_meta_source_family_synthesis.py`, then teach retained-frontiers and allocator-ceiling to rank and render it.

Candidate families should be bounded and artifact-driven. Suggested first batch:

1. Recombine top retained source-context and whole-function evidence:
   - Start from the best structurally accepted older source-context rows, especially the loop digit object/local row.
   - Overlay the minimal whole-function hunk that gave the best retained target/expression floor, especially `joint-data-owner-with-loop-object`.
   - Bound to the top N rows by target/expression score and structural guard.

2. Broaden source-context ownership without changing CFG:
   - Preloop object/base/data ownership variants around the source-context span near line 2564.
   - Joint data owner lifetime variants.
   - Parent/add-child and translate call argument ownership variants.
   - Keep the loop structure and call order identical unless a candidate explicitly declares a structural hypothesis.

3. Full-unit source-context/helper candidates:
   - Small static inline helpers or local accessors for repeated `data->jobjs`/joint-data access.
   - File-local type/layout overlays only when required to express the broader source context.
   - These candidates must mark scoring metadata so `score-source` uses `--full-unit-source`.

Exact files/functions to change:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
  - Add constants:
    - `DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION`
    - `DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_FAMILY`
    - `DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_MODEL`
    - `DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_TERMINAL_REASON`
    - `DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_NO_FLOOR_BLOCKER`
  - Add the new dimension to `_PROFILES[DRAW_FUNCTION]["dimensions"]`.
  - Add stage predicates:
    - `_draw_post_all_known_source_context_requested`
    - `_draw_post_all_known_source_context_exhausted`
    - `_draw_post_all_known_source_context_stage_active`
  - Change `generate_source_family_candidates` so a terminal whole-function stage does not immediately return `[]` when the post-all-known stage is active.
  - Add candidate generation:
    - `_draw_post_all_known_source_context_candidates`
    - `_draw_post_all_known_source_context_specs`
    - helper patch/build functions for each bounded source shape
  - Add terminal evidence:
    - `_draw_post_all_known_source_context_retained_terminal_evidence`
    - `_draw_post_all_known_source_context_terminal_next_hint`
  - Update:
    - `build_generated_source_family_payload`
    - `_zero_candidate_generation_blockers`
    - `_build_zero_candidate_source_family_terminal_proof`
    - `build_terminal_source_family_proof`
    - any summary/normalization helpers that enumerate Draw dimensions

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
  - Add the new Draw dimension/family constants.
  - Extend `_source_model_proof_stage_rank` so post-all-known ranks above the whole-function terminal stage.
  - Ensure `synthesize_retained_frontier_meta_ceiling` can surface a post-all-known actionable lane and terminal proof.
  - Ensure stale post-source-context unsupported hints are suppressed when the new post-all-known proof is present.

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`
  - Extend `_retained_meta_rank` or the retained-meta selection path so post-all-known proofs outrank stale discovery proofs.
  - Extend `_next_steps` and `_extend_retained_frontiers_meta_ceiling` to render the new family, candidate score, pcdump, source hunk, and remaining unsupported dimensions.
  - Prevent the old "run retained-frontiers with explicit post-source-context-next-dimension JSON" next step from being emitted when a post-all-known proof already exists.

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_source_context_discovery.py`
  - Prefer no behavioral change unless the new stage needs shared constants.
  - If constants are shared, add the new names but keep discovery's role as a handoff/diagnostic layer, not a candidate generator.

- `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`
  - Verify `source-model-synthesis` already passes through scoring metadata for full-unit candidates.
  - If the metadata is missing, update the score command construction so post-all-known full-unit candidates use `debug target score-source --full-unit-source`.

- `/Users/mike/code/melee/tools/melee-agent/src/cli/capabilities.py`
  - Add search aliases such as "draw post all known source hypothesis" and "post all known retained frontier" pointing to `debug search source-model-synthesis`, `debug search retained-frontiers`, and `debug solve allocator-ceiling`.

Tradeoffs:

- Pros: Directly satisfies the governance requirement with first-class ranked candidates, scores, hunks, pcdumps, and terminal proofs.
- Pros: Reuses the existing source-model-synthesis scoring and retained-frontiers pipeline.
- Pros: Fixes allocator-ceiling presentation by giving it a higher-ranked post-whole-function proof to render.
- Cons: Adds another Draw-specific stage to an already large module.
- Cons: Stage predicates must be strict to avoid reintroducing #1040 loops or generating post-all-known candidates before whole-function evidence is truly exhausted.

Recommendation: choose this approach.

### Approach 2: Separate Post-all-known Synthesis Command

Add a new command/module, for example:

- `debug search post-all-known-source-hypothesis`
- module: `src/mwcc_debug/post_all_known_source_hypothesis.py`

The command would consume source-model, retained-frontiers, allocator-ceiling, and source files directly, then emit a retained-frontiers-compatible source-model proof.

Tradeoffs:

- Pros: Cleaner isolation from the large source-model-synthesis module.
- Pros: Easier to prototype and test against the issue artifacts.
- Cons: Duplicates candidate writing, scoring, terminal proof, and retained-frontiers compatibility logic.
- Cons: Requires additional integration so retained-frontiers and allocator-ceiling treat this output as first-class.
- Cons: The user workflow now has another command instead of extending the existing source-model-synthesis path.

This is reasonable only if Approach 1 becomes too invasive.

### Approach 3: Diagnostic-only Meta-frontier in Retained-frontiers/Allocator-ceiling

Do not generate new C candidates. Instead, have retained-frontiers or allocator-ceiling synthesize a ranked "meta frontier" from the terminal proof, source spans, and existing retained hunks.

Tradeoffs:

- Pros: Smallest code change.
- Pros: Useful for human diagnosis.
- Cons: Does not satisfy the source-actionable governance requirement because there are no newly generated retained C candidates, pcdumps, or fresh target/expression scores.
- Cons: Leaves source-model-synthesis unable to advance after all known frontiers are exhausted.

Not recommended for #1041. It can be a fallback diagnostic if source generation is deferred.

## Recommended Implementation Detail

Implement Approach 1.

Activation predicate:

The new stage should activate when all of the following are true:

- Function is `mnDiagram_DrawCellNumber` or source alias `mnDiagram_80241E78`.
- The retained/meta context proves `DRAW_POST_SOURCE_CONTEXT_DIMENSION` is exhausted, terminal, or suppressed by the whole-function terminal proof.
- Retained-frontiers meta status is either:
  - `terminal-current-source-shape-ceiling`, or
  - an aggregate whose terminal proof reason is `no-modeled-source-actionable-frontiers-remain`.
- The current source-model proof or allocator current ceiling contains either:
  - `draw-post-source-context-whole-function-fpr-source-model-exhausted/no-floor-improvement`, or
  - `draw-no-modeled-source-actionable-family-after-post-source-context-whole-function-fpr-source-model`.
- The new `DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION` is not already terminal or exhausted.

The predicate should not activate for the earlier post-source-context discovery stage before the six whole-function candidates have been scored.

Candidate bounds:

- Default `max_per_dimension` should continue to cap the output.
- First implementation should generate roughly 6 to 10 candidates.
- Every candidate should include:
  - stable candidate id
  - dimension id
  - family id
  - source hunk summary
  - baseline retained floors
  - required target score validation
  - required expression score validation
  - required structural guard validation
  - score command metadata
  - `requires_full_unit_source` where helper/type/data context outside the target function is present

Candidate families should be ordered conservatively:

1. Low-risk recombinations that keep CFG and call order stable.
2. Wider local source-context lifetime/ownership variants.
3. Full-unit helper/type/layout variants.

Terminal proof:

If all bounded candidates score no better than the retained floors, emit a terminal proof with:

- `terminal_reason`: `draw-post-all-known-frontiers-source-context-hypothesis-exhausted/no-floor-improvement`
- `terminal_blocker`: `draw-post-all-known-frontiers-source-context-hypothesis/no-target-or-real-expression-floor-improvement`
- `exhausted_dimensions` including the new dimension
- `candidate_scores`
- `retained_scored_probes`
- `source_hunks_by_candidate`
- `pcdump_by_candidate` or pcdump references where present
- `terminal_summary.best_candidate_id`
- `terminal_summary.best_target_matched`
- `terminal_summary.best_expression_matched`
- `next_unsupported_source_family` naming the dimensions still missing beyond bounded post-all-known source-context synthesis

## Regression Tests

Add focused tests rather than large artifact fixtures.

### Source-model Synthesis

File:

- `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Tests:

1. `test_draw_post_all_known_generates_candidates_after_whole_function_terminal`
   - Build a compact context equivalent to the inspected #1040 retained/allocator terminal.
   - Call `generate_source_family_candidates` with Draw source text.
   - Assert candidates are non-empty.
   - Assert every candidate uses `DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION`.
   - Assert no six whole-function candidate ids are regenerated.
   - Assert source hunks and validation metadata are present.

2. `test_draw_post_all_known_terminal_proof_preserves_evidence`
   - Feed mocked score rows where no candidate beats the `1/3` target and `1/3` expression floors.
   - Call `classify_source_family_scores` or the terminal proof builder used by the CLI.
   - Assert terminal status, new exhausted dimension, best candidate summary, retained scored probes, source hunks, and next unsupported source model.

3. `test_cli_source_model_synthesis_writes_draw_post_all_known_probes`
   - Use a tmp fixture based on the inspected retained-frontiers/allocator terminal shape.
   - Invoke the Typer app with:
     - `debug search source-model-synthesis`
     - `--function mnDiagram_DrawCellNumber`
     - `--meta-ceiling-json <allocator fixture>`
     - `--retained-frontiers-json <retained fixture>`
     - `--source-file <tmp mndiagram.c>`
     - `--write-probes <tmp probes>`
     - `--max-per-dimension 10`
     - `--no-score`
     - `--json`
   - Assert JSON status is generated, candidate count is bounded and positive, and candidate files are written.

### Retained-frontiers

File:

- `/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py`

Tests:

1. `test_draw_post_all_known_actionable_lane_outranks_stale_post_source_context_hint`
   - Provide terminal old discovery proof, whole-function terminal proof, and one post-all-known scored candidate with improved structural guard or score.
   - Assert `status == "actionable"` and `next_frontier` points at the post-all-known candidate.

2. `test_draw_post_all_known_terminal_outranks_stale_unsupported_family`
   - Provide old post-source-context discovery proof plus new post-all-known terminal proof.
   - Assert meta terminal proof uses the new family/model and does not expose `draw-next-unsupported-source-dimension-after-loop-body-callsite-and-object-base-lifetime-source-context` as the current next family.

### Allocator-ceiling

File:

- `/Users/mike/code/melee/tools/melee-agent/tests/test_allocator_ceiling.py`

Tests:

1. `test_allocator_ceiling_draw_post_all_known_actionable`
   - Feed retained-frontiers aggregate containing a post-all-known actionable lane.
   - Assert `status == "actionable"`.
   - Assert next steps include candidate id, score summary, source hunk, and pcdump reference.

2. `test_allocator_ceiling_draw_post_all_known_terminal_suppresses_stale_discovery`
   - Feed retained-frontiers aggregate containing old discovery proof, whole-function terminal proof, and new post-all-known terminal proof.
   - Assert `status == "practical-ceiling"`.
   - Assert `current_ceiling` is the post-all-known terminal proof.
   - Assert next steps do not ask to rerun only the old post-source-context next-dimension handoff.

### Post-source-context Discovery

File:

- `/Users/mike/code/melee/tools/melee-agent/tests/test_post_source_context_discovery.py`

Tests:

1. Keep existing #1040 behavior:
   - Whole-function terminal should not repeat the whole-function dimension.
   - Discovery may still emit unsupported-source-family as a handoff when no post-all-known synthesis artifact exists.

2. If shared constants are added, assert discovery output remains backward compatible and does not claim source-actionable candidates by itself.

### Capabilities

File:

- `/Users/mike/code/melee/tools/melee-agent/tests/test_capabilities.py`

Tests:

- Add queries for "draw post all known source hypothesis" and "post all known retained frontier".
- Assert they return the existing workflow commands.

## Smoke Checks

Run from `/Users/mike/code/melee` with the main checkout first on `PYTHONPATH`.

```bash
cd /Users/mike/code/melee
export PYTHONPATH=/Users/mike/code/melee/tools/melee-agent
```

Command exposure:

```bash
melee-agent debug search source-model-synthesis --help
melee-agent debug search retained-frontiers --help
melee-agent debug solve allocator-ceiling --help
melee-agent capabilities search "draw post all known source hypothesis"
```

Focused tests:

```bash
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k 'draw_post_all_known or post_source_context_whole'
python -m pytest tools/melee-agent/tests/test_retained_frontier_triage.py -k 'draw and post_all_known'
python -m pytest tools/melee-agent/tests/test_allocator_ceiling.py -k 'draw and post_all_known'
python -m pytest tools/melee-agent/tests/test_post_source_context_discovery.py -k 'draw and post_whole'
python -m pytest tools/melee-agent/tests/test_capabilities.py -k 'post_all_known or source_model_synthesis or retained_frontiers'
```

Generate post-all-known probes from the issue artifacts:

```bash
melee-agent debug search source-model-synthesis \
  --function mnDiagram_DrawCellNumber \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1040_rerun/draw_frontiers_after_post_whole_suppression/draw_allocator_after_1040_suppression.json \
  --retained-frontiers-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1040_rerun/draw_frontiers_after_post_whole_suppression/draw_frontiers_after_1040_suppression.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --write-probes /tmp/issue1041-draw-post-all-known-probes \
  --max-per-dimension 10 \
  --include-source \
  --no-score \
  --json > /tmp/issue1041-source-model-noscore.json
```

Expected:

- exit 0
- `status` is generated/actionable rather than terminal zero-candidate
- `candidate_count > 0`
- no regenerated `draw-post-source-context-whole-function-*` candidate ids
- all generated candidates use `draw-post-all-known-frontiers-source-context-hypothesis`
- probe `.c` files exist in `/tmp/issue1041-draw-post-all-known-probes`

Score a generated candidate using the emitted score command or directly with `score-source`. Use a target JSON derived for `mnDiagram_DrawCellNumber`; if the source-model payload emits candidate `score_command` entries, prefer those exact commands.

Template:

```bash
melee-agent debug target score-source /tmp/issue1041-draw-post-all-known-probes/<candidate>.c \
  --function mnDiagram_DrawCellNumber \
  --target <draw-target.json> \
  --cflags-from src/melee/mn/mndiagram.c \
  --expression-baseline <draw-baseline-pcdump.txt> \
  --expression-source src/melee/mn/mndiagram.c \
  --checkdiff-guard \
  --full-unit-source \
  --retain-pcdump \
  --remote-fallback \
  --json > /tmp/issue1041-one-score.json
```

Classify scored output through source-model-synthesis:

```bash
melee-agent debug search source-model-synthesis \
  --function mnDiagram_DrawCellNumber \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1040_rerun/draw_frontiers_after_post_whole_suppression/draw_allocator_after_1040_suppression.json \
  --retained-frontiers-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1040_rerun/draw_frontiers_after_post_whole_suppression/draw_frontiers_after_1040_suppression.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --score-json /tmp/issue1041-one-score.json \
  --no-score \
  --json > /tmp/issue1041-source-model-scored.json
```

Retained-frontiers aggregation:

```bash
melee-agent debug search retained-frontiers \
  --function mnDiagram_DrawCellNumber \
  --artifact /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1040_rerun/draw_frontiers_after_post_whole_suppression/draw_frontiers_after_1040_suppression.json \
  --artifact /tmp/issue1041-source-model-scored.json \
  --json > /tmp/issue1041-retained-frontiers.json
```

Allocator-ceiling aggregation:

```bash
melee-agent debug solve allocator-ceiling \
  --function mnDiagram_DrawCellNumber \
  --evidence /tmp/issue1041-retained-frontiers.json \
  --json > /tmp/issue1041-allocator-ceiling.json
```

Expected retained/allocator behavior:

- If any candidate improves target score, expression score, or structural guard, retained-frontiers reports an actionable post-all-known lane and allocator-ceiling reports actionable.
- If none improve, retained-frontiers reports all-known exhausted with the new post-all-known terminal proof, and allocator-ceiling reports practical ceiling with that proof as `current_ceiling`.
- Neither output should resurrect the stale post-source-context family as the current next step when the new post-all-known proof exists.

Loop/suppression smoke:

```bash
melee-agent debug search source-model-synthesis \
  --function mnDiagram_DrawCellNumber \
  --meta-ceiling-json /tmp/issue1041-source-model-scored.json \
  --retained-frontiers-json /tmp/issue1041-retained-frontiers.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --write-probes /tmp/issue1041-repeat-check \
  --max-per-dimension 10 \
  --no-score \
  --json > /tmp/issue1041-repeat-source-model.json
```

Expected:

- If post-all-known is already terminal, this emits a bounded terminal proof and no duplicate post-all-known candidates.
- It must not regenerate the six exhausted whole-function candidates.

Full build is not necessary for the tool-only change, but run it if production source was touched by accident or if tests exercise source patching against the tree:

```bash
python configure.py
ninja
```

## Risks

- The largest risk is reintroducing #1040-style loops. The new stage must only activate after whole-function terminal evidence exists, and must terminal-suppress itself after its own bounded candidates are exhausted.
- Stale proof ranking can hide the new work. Retained-frontiers and allocator-ceiling must rank the new post-all-known proof above old post-source-context discovery artifacts.
- Full-unit candidates may require `--full-unit-source`; otherwise score-source/checkdiff guard can silently evaluate the wrong shape.
- Candidate patchers could accidentally change CFG or call order. Keep the first candidate set conservative and require structural guard metadata.
- Large real artifacts should not be copied into unit tests. Build compact fixtures that preserve the relevant proof shape and add one manual smoke against the real artifact paths above.
- The current shell environment can import the artifact worktree's `tools/melee-agent` first. Keep the `PYTHONPATH` guard in smoke commands and test documentation.

## Acceptance Criteria

- Source-model-synthesis produces bounded post-all-known Draw candidates from the #1040 terminal retained/allocator artifacts.
- Retained-frontiers ranks those candidates as actionable when they improve score or structural guard.
- If no candidate improves, retained-frontiers and allocator-ceiling emit a terminal proof for the new post-all-known dimension, not a stale post-source-context unsupported family.
- Allocator-ceiling next steps include source-actionable candidate details or a precise terminal proof of the unsupported dimensions still missing.
- Existing #1040 suppression remains intact: the six whole-function candidates are not regenerated after whole-function exhaustion.
