# Issue 1024 Plan: Whole-Function Sort Control/Data-Flow Source Model

## Scope

Issue #1024 asks for the next `source-model-synthesis` layer for `mnDiagram_SortNamesByKOs` after #1023 exhausted the bounded full selection/swap source family. This plan is for implementation in `/Users/mike/code/melee` on current `master`; it does not implement production changes.

Primary function/source mapping:

- Public issue function: `mnDiagram_SortNamesByKOs`
- Source function emitted in `/Users/mike/code/melee/src/melee/mn/mndiagram.c`: `mnDiagram_8023FC28`
- Target assignments: `IG34->r27`, `IG44->r25`

Artifacts reviewed and relied on:

- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1023_rerun/source_model_full_selection_swap/sort_source_model_full_selection_swap_scored.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1023_rerun/retained_frontiers_after_full_selection_swap/sort_frontiers_after_full_selection_swap.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1023_rerun/retained_frontiers_after_full_selection_swap/sort_allocator_after_full_selection_swap.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1023_rerun/control_flow_shape/sort_control_flow_suggest.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1023_rerun/control_flow_shape/sort_control_flow_shape_search.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1023_rerun/control_flow_shape/target_scores/control-flow-pointer-walk-loop-induction-0_target_score.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1023_rerun/control_flow_shape/target_scores/control-flow-pointer-walk-loop-end-pointer-0_target_score.json`

Audit-first check already run from `/Users/mike/code/melee`:

```bash
melee-agent capabilities search "whole-function control data flow source model synthesis source-model-synthesis selection swap exhaustion"
```

Relevant existing capabilities found: `debug search source-model-synthesis`, `debug search source-family-continuation`, `debug target score-source`, `debug suggest control-flow-shape`, and `debug mutate control-flow-shape-search`. No existing capability materializes the requested whole-function Sort control/data-flow family.

## Current Master: Already Present

`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py` already contains the post-meta Sort synthesis stack through the #1023 layer:

- Sort constants and aliases: `SORT_FUNCTION = "mnDiagram_SortNamesByKOs"`, `SORT_SOURCE_FUNCTION = "mnDiagram_8023FC28"`, `SORT_SOURCE_FILE = "src/melee/mn/mndiagram.c"`, `SORT_FORCE_PHYS = {"34": 27, "44": 25}`.
- A bounded full-selection/swap dimension: `SORT_FULL_SELECTION_SWAP_DIMENSION = "sort-full-selection-swap-source-structure"`.
- A terminal next-family marker: `SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY = "sort-whole-function-control-data-flow-rewrite"`.
- Five generated full-selection/swap candidates:
  - `post-meta-sort-full-selection-full-selection-swap-carried-combined`
  - `post-meta-sort-full-selection-full-selection-loop-carried-state`
  - `post-meta-sort-full-selection-full-comparison-state-latched`
  - `post-meta-sort-full-selection-full-selected-name-stable-local`
  - `post-meta-sort-full-selection-full-swap-emission-pointer-walk`
- Joint-target classification through `classify_source_family_scores`; a candidate with both `IG34->r27` and `IG44->r25` plus an accepted structural guard becomes actionable.
- Terminal proof propagation through `build_source_family_continuation_payload`, retained-frontier triage, and allocator-ceiling classification.

`/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py` already exposes the correct public command surface:

- `melee-agent debug search source-model-synthesis`
- `--meta-ceiling-json`
- `--write-probes`
- `--score`
- `--score-json`
- `--target`
- `--cflags-from`
- `--checkdiff-guard`
- `--expression-baseline`

`/Users/mike/code/melee/tools/melee-agent/src/cli/debug/target.py` and `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/scoring.py` already support the real score-source target format needed here:

```json
{
  "function": "mnDiagram_SortNamesByKOs",
  "virtuals": {
    "34": 27,
    "44": 25
  }
}
```

Existing regression coverage in `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py` already covers the handoff up to this point:

- `_sort_full_selection_swap_context`
- `_sort_full_selection_swap_terminal_payload`
- `test_sort_full_selection_swap_generation_from_terminal_next_model`
- `test_sort_full_selection_swap_classifier_names_next_source_family`
- `test_sort_full_selection_swap_terminal_continuation_preserves_next_family`
- `test_allocator_ceiling_prefers_full_selection_exhaustion_over_stale_continuation`

## Current Master: Missing

There is no generator, dimension, transform family, or CLI behavior that consumes `sort-whole-function-control-data-flow-rewrite` and emits source-actionable candidates. The #1023 layer names the next unsupported family, but that family is metadata only.

Specifically missing:

- No `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION` or equivalent dimension in `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`.
- No `_should_generate_sort_whole_function_control_data_flow(...)` trigger that recognizes #1023's terminal family.
- No source patcher that spans the entire `mnDiagram_8023FC28` function body, including declarations, initialization, selection, comparison state, selected-name state, and swap/shift emission.
- No terminal proof for exhaustion of the whole-function family. If the next family is later exhausted, the proof must name a new unsupported span/family instead of looping back to `sort-whole-function-control-data-flow-rewrite`.
- No transform-corpus or catalog entry with this family name in:
  - `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus/registry.py`
  - `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py`
  - `/Users/mike/code/melee/docs/source-transform-catalog.md`

## Root Cause

The failure is not that the full-selection/swap family needs more candidates. The #1023 artifact shows that layer has reached its designed boundary:

- `sort_source_model_full_selection_swap_scored.json` is `status: terminal`.
- `candidate_count=32`, `score_count=32`.
- The exhausted dimensions include the original local Sort dimensions, natural Sort dimensions, semantic Sort dimensions, and `sort-full-selection-swap-source-structure`.
- The terminal blockers are structural-guard rejection and protected targets not jointly preserved.
- The best candidates remain one-hit only; none jointly preserve `IG34->r27` and `IG44->r25`.
- `next_unsupported_source_family` is already `sort-whole-function-control-data-flow-rewrite`.

The implementation root cause is a missing escalation layer. Current full-selection/swap synthesis still uses bounded region replacement around the selection/swap algorithm. It can rewrite comparison state and swap emission, but it cannot change the complete function-level source ownership and lifetime graph:

- locals and declaration order at function entry,
- initialization loop ownership of `dst`, `dst_iter`, `tp`, and `totals`,
- source owner choice between `mnDiagram_804A0750`, `mnDiagram_804A076C`, `assets`, `dst`, and local source pointers,
- whether selected name, selected total, and selected text are carried as explicit values or repeatedly reloaded,
- whether selection and shift are coupled through `max_idx` or separated by a selected-name value,
- whether output emission is a shift-after-selection model or a prefix insertion/rebuild model.

The generic control-flow tools do not solve this because they are local shape mutators, not source-model escalators. The reviewed control-flow artifacts confirm this:

- `sort_control_flow_shape_search.json` generated six pointer-walk probes.
- Two probes built and scored, but both were `0/2`:
  - induction probe: `IG34=r25`, `IG44=0`
  - end-pointer probe: `IG34=r30`, `IG44=r3`
- Four probes failed because the target function was not emitted in the pcdump.

That means issue #1024 should add a bounded whole-function candidate family to `source-model-synthesis`, not extend `debug mutate control-flow-shape-search` with more local probes.

## Test-First Plan

Add failing tests before production changes where practical.

### 1. Source-Family Generation Regression

File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add a helper:

```python
def _sort_whole_function_control_data_flow_context(tmp_path: Path):
    return normalize_meta_ceiling_context(
        [_sort_full_selection_swap_terminal_payload()],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )
```

Add `test_sort_whole_function_control_data_flow_generation_from_full_selection_terminal`:

- Build context from `_sort_full_selection_swap_terminal_payload()`.
- Call `generate_source_family_candidates(_sort_source(), context, include_source=True, max_per_dimension=10)`.
- Assert candidates exist with dimension `synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION`.
- Assert every whole-function candidate has:
  - non-empty `source_hunks`,
  - `validation_metadata["whole_function_control_data_flow_source_model"] is True`,
  - `validation_metadata["semantic_algorithm_shape"] is True`,
  - joint target requirements for `IG34->r27` and `IG44->r25`,
  - source components spanning initialization, selection, selected-name/total state, source-owner flow, and swap/emission.
- Assert the candidate source still contains `void mnDiagram_8023FC28(void)` or the configured `--source-function` alias.

Expected candidate IDs to lock down the initial bounded family:

- `post-meta-sort-whole-function-source-owner-unified`
- `post-meta-sort-whole-function-selected-record-carried`
- `post-meta-sort-whole-function-selected-name-total-carried`
- `post-meta-sort-whole-function-shift-emission-indexed`
- `post-meta-sort-whole-function-prefix-insertion-rebuild`

The exact names may be adjusted during implementation, but the test should make the family explicit and bounded.

### 2. Zero-Candidate Blocker Regression

File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add `test_sort_whole_function_control_data_flow_zero_candidates_report_blocker`:

- Mutate `_sort_source()` so the function signature or required init/selection pattern is absent.
- Generate candidates with the whole-function context.
- Assert no whole-function candidates.
- Assert `build_generated_source_family_payload(...)` includes a blocked dimension:
  - dimension id: `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION`
  - blocker reason: `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_SOURCE_REGION_PATTERN_BLOCKER`
  - required patterns list covers function signature, init loop, outer loop, inner comparison, and shift/emission region.

### 3. Joint-Target Classifier Regression

File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add `test_sort_whole_function_control_data_flow_classifier_requires_joint_targets`:

- Generate one whole-function candidate.
- Classify synthetic score rows with existing `_score(...)` helper:
  - `actual34=27, actual44=22, accepted=True` -> terminal/protected-targets-not-jointly-preserved.
  - `actual34=24, actual44=25, accepted=True` -> terminal/protected-targets-not-jointly-preserved.
  - `actual34=27, actual44=25, accepted=False` -> terminal/structural-guard-not-accepted.
  - `actual34=27, actual44=25, accepted=True` -> actionable.
- Assert the actionable row retains `source_hunks` and source components for the whole-function family.

### 4. Whole-Family Exhaustion Proof Regression

File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add `test_sort_whole_function_control_data_flow_exhaustion_names_next_family`:

- Classify all whole-function candidates with synthetic `0/2` or `1/2` scores.
- Assert `payload["status"] == "terminal"`.
- Assert `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION` is in attempted/exhausted equivalence classes.
- Assert `payload["next_unsupported_source_family"]` is not `sort-whole-function-control-data-flow-rewrite`.
- Assert the next unsupported model names a concrete next layer, for example helper extraction/data layout/cross-function context outside `mnDiagram_8023FC28`.

This prevents the new layer from becoming another terminal-only loop.

### 5. CLI Generation Regression

File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add `test_cli_source_model_synthesis_writes_whole_function_sort_probes`:

- Write `_sort_full_selection_swap_terminal_payload()` to `tmp_path / "sort-full-selection-terminal.json"`.
- Write `_sort_source()` to `tmp_path / "sort.c"`.
- Run `CliRunner().invoke(search_app, ["source-model-synthesis", "--function", SORT_FUNCTION, "--meta-ceiling-json", str(meta), "--source-file", str(source), "--write-probes", str(out_dir), "--json"])`.
- Assert:
  - exit code 0,
  - `payload["status"] == "generated"`,
  - candidate count > 0,
  - at least one candidate has dimension `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION`,
  - candidate files exist,
  - candidate source preserves the requested source function.

### 6. Optional Catalog/Registry Regression

Only add these tests if the implementation includes transform-corpus/catalog discoverability for the new family.

Files:

- `/Users/mike/code/melee/tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_source_transform_catalog.py`

Tests:

- `test_default_corpus_names_required_transform_families` includes a discoverable family id, preferably `sort_whole_function_control_data_flow_rewrite` if the transform-corpus registry uses underscore ids.
- Sort-specific plan tests show `plan_transform_experiments(function="mnDiagram_SortNamesByKOs", ...)` includes the family only for SortNames.
- Catalog tests assert docs mention `source-model-synthesis`, `sort-whole-function-control-data-flow-rewrite`, and the target pair `IG34/IG44`.

## Production Change Plan

### 1. Add the Whole-Function Dimension

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add constants near the existing full-selection/swap constants:

- `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION = "sort-whole-function-control-data-flow-rewrite"`
- `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_COMPONENTS`
- `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_REQUIRED_SOURCE_PATTERNS`
- `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_SOURCE_REGION_PATTERN_BLOCKER`
- `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_MODEL`
- `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_FAMILY`

The exhausted next model should be explicit and non-circular, for example:

```text
Sort whole-function control/data-flow source-model synthesis exhausted bounded function-body rewrites spanning initialization, source-owner flow, selection state, selected-name/total state, and swap/emission without jointly recovering IG34/IG44. The next unsupported source span/family is helper extraction, data layout, or cross-function source-context rewrite outside the bounded mnDiagram_8023FC28 function-body model.
```

The next family can be:

```text
sort-helper-extraction-data-layout-or-cross-function-rewrite
```

### 2. Trigger Generation From the #1023 Terminal Artifact

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add `_should_generate_sort_whole_function_control_data_flow(context)`:

- Return true only for `mnDiagram_SortNamesByKOs`.
- Recognize `context.next_unsupported_source_family == SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY` when present.
- Also recognize `context.next_unsupported_source_model == SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_MODEL`.
- Fall back to searching `context.current_ceiling["source_model_proof"]` and nested `source_family_synthesis` for the same family/model, because retained-frontier/allocator artifacts may carry the data at different levels.

Update the Sort profile/dimension generation order so this new dimension runs after `SORT_FULL_SELECTION_SWAP_DIMENSION`, not alongside earlier local/natural/semantic dimensions.

### 3. Implement Function-Body Source Candidate Generation

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add `_sort_whole_function_control_data_flow_source_candidates(...)`.

This family should replace the full `mnDiagram_8023FC28` function body, not just the selection/swap region. Use the existing source-function alias machinery so `--source-function mnDiagram_SortNamesByKOs` still works in tests and CLI.

Candidate rules:

- Keep candidates bounded and deterministic, initially 5-8 variants.
- Each candidate must be source-actionable C, not a descriptive hint.
- Each candidate must preserve semantics unless explicitly marked high-risk in `validation_metadata`.
- Each candidate must retain target requirements for both `IG34->r27` and `IG44->r25`.
- Each candidate must include source hunks spanning the replaced function body and source components that identify the rewritten sub-flows.
- Each candidate should include enough metadata for score-source handoff and pcdump review.

Initial candidate shapes:

1. `source-owner-unified`
   - Introduce local `u8* sorted_names = mnDiagram_804A076C.sorted_names;` and use it consistently through selection and shift.
   - Goal: move source-owner lifetime out of repeated global field loads.

2. `selected-record-carried`
   - Carry `selected_name`, `selected_total`, and `selected_text` through the inner loop instead of reloading all state from `sorted_names[max_idx]`.
   - Goal: change the virtual lifetimes that currently separate the IG34 and IG44 wins.

3. `selected-name-total-carried`
   - Similar to selected-record, but keep text checks late and totals early.
   - Goal: explore the data-flow split between `GetNameText` and `mnDiagram_SumNameKOs`.

4. `shift-emission-indexed`
   - Replace the pointer-offset `assets->sorted_fighters` plus `sizeof(mnDiagram_804A0750_t)` emission with a natural indexed shift over `dst`/`sorted_names`.
   - Goal: move emission ownership from pointer arithmetic to array indexing while preserving the same bytes.

5. `prefix-insertion-rebuild`
   - Model the whole operation as building the sorted prefix by insertion, with careful null-name/tie behavior.
   - Mark semantic risk high unless manually reviewed, because this changes the algorithm shape most strongly.

Implementation detail:

- Prefer existing patch/hunk helpers in `post_meta_source_family_synthesis.py` over ad hoc string slicing.
- If a helper cannot safely find the exact function body, return zero candidates and emit the new source-region blocker.
- Do not add a new CLI or standalone script.

### 4. Add Zero-Candidate Blockers

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add `_sort_whole_function_control_data_flow_zero_candidate_generation_blockers(...)` and wire it into `build_generated_source_family_payload(...)`/dimension payload generation the same way full-selection/swap blockers are reported.

Blocker payload should include:

- required function name/source function,
- required init loop pattern,
- required outer selection loop,
- required inner comparison region,
- required shift/emission region,
- current next unsupported family/model that triggered the dimension.

### 5. Classify Whole-Family Exhaustion Correctly

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Extend the terminalization helpers that currently special-case full-selection/swap:

- `_can_terminalize_structural_guard_exhaustion(...)`
- `_can_terminalize_required_assignment_exhaustion(...)`
- `_terminal_next_unsupported_source_model(...)`
- any helper that builds `next_unsupported_source_spans`
- any helper that fills `source_model_proof["source_family_synthesis"]`

Required behavior:

- If a whole-function candidate jointly hits `IG34->r27` and `IG44->r25` and the structural guard is accepted, status is actionable.
- If all whole-function candidates are scored and none jointly hit both targets with an accepted guard, status is terminal.
- Terminal proof includes the whole-function dimension in attempted/exhausted equivalence classes.
- Terminal proof names `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_MODEL` and `SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_FAMILY`, not the same family that was just attempted.

### 6. Preserve Score-Source Evidence

File: `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`

Likely minimal changes only. Verify `source-model-synthesis` still:

- writes candidate files,
- scores generated candidates with `debug target score-source`,
- retains pcdump paths when score-source JSON includes them,
- forwards structural guard evidence,
- accepts offline `--score-json`,
- includes `score_command`/handoff hints when enough target data exists.

If the new candidates need additional context fields, add them to the generated payload rather than creating a separate command.

### 7. Optional Discoverability Updates

Only do this if the team wants the family discoverable through transform-corpus/capability search in addition to `source-model-synthesis`.

Files:

- `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus/registry.py`
- `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py`
- `/Users/mike/code/melee/docs/source-transform-catalog.md`
- `/Users/mike/code/melee/tools/melee-agent/src/cli/capabilities.py` if capabilities metadata is maintained there for this command/family.

Recommended stance:

- Keep source generation in `post_meta_source_family_synthesis.py`.
- Add catalog/docs language that `debug search source-model-synthesis` owns this whole-function family.
- Avoid duplicating candidate materialization in transform-corpus unless another workflow truly needs it; duplicate hard-coded candidates would become a maintenance risk.

## CLI Smoke Checks

Run from `/Users/mike/code/melee`.

### 1. Capability Search Still Finds the Path

```bash
melee-agent capabilities search "whole-function Sort control data flow source model"
```

Expected: `debug search source-model-synthesis` is the primary result or explicitly mentions the new whole-function Sort family.

### 2. Generate Whole-Function Probes Without Scoring

```bash
rm -rf build/diagnostics/issue_1024_whole_function
melee-agent debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1023_rerun/source_model_full_selection_swap/sort_source_model_full_selection_swap_scored.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --source-function mnDiagram_8023FC28 \
  --write-probes build/diagnostics/issue_1024_whole_function/probes \
  --max-per-dimension 8 \
  --no-score \
  --json > build/diagnostics/issue_1024_whole_function/generated.json
```

Expected:

- `generated.json` has `status: "generated"`.
- `candidate_count > 0`.
- At least one candidate has `dimension_id: "sort-whole-function-control-data-flow-rewrite"`.
- Probe files contain `void mnDiagram_8023FC28(void)`.

### 3. Create the Target Spec

```bash
mkdir -p build/diagnostics/issue_1024_whole_function
cat > build/diagnostics/issue_1024_whole_function/sort_ig34_ig44_target.json <<'JSON'
{
  "function": "mnDiagram_SortNamesByKOs",
  "virtuals": {
    "34": 27,
    "44": 25
  }
}
JSON
```

### 4. Live Score the Family

```bash
melee-agent debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1023_rerun/source_model_full_selection_swap/sort_source_model_full_selection_swap_scored.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --source-function mnDiagram_8023FC28 \
  --write-probes build/diagnostics/issue_1024_whole_function/scored \
  --max-per-dimension 8 \
  --score \
  --target build/diagnostics/issue_1024_whole_function/sort_ig34_ig44_target.json \
  --cflags-from /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --checkdiff-guard \
  --timeout 120 \
  --json > build/diagnostics/issue_1024_whole_function/scored.json
```

Expected:

- Each buildable candidate has `target_score`, `structural_guard`, and retained pcdump evidence.
- If any candidate hits both `IG34->r27` and `IG44->r25` with accepted structural guard, output is actionable and includes the retained candidate path.
- If the family is exhausted, output is terminal and names a next unsupported family other than `sort-whole-function-control-data-flow-rewrite`.

### 5. Direct Score-Source Spot Check

Pick one generated candidate and run:

```bash
melee-agent debug target score-source \
  build/diagnostics/issue_1024_whole_function/scored/<candidate>.c \
  --function mnDiagram_SortNamesByKOs \
  --target build/diagnostics/issue_1024_whole_function/sort_ig34_ig44_target.json \
  --cflags-from /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --checkdiff-guard \
  --retain-pcdump \
  --json
```

Expected: JSON includes `target_score.virtuals.34`, `target_score.virtuals.44`, `structural_guard`, and `pcdump_path`.

## Test Commands

Run focused tests first:

```bash
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k "full_selection or whole_function"
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k "source_model_synthesis and cli"
python -m pytest tools/melee-agent/tests/search/test_cli_smoke.py -k "source_model_synthesis"
```

If catalog/registry discoverability is changed:

```bash
python -m pytest tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py -k "SortNames or whole_function or default_corpus"
python -m pytest tools/melee-agent/tests/test_source_transform_catalog.py
```

Before handing off:

```bash
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py tools/melee-agent/tests/search/test_cli_smoke.py
```

Do not run a full `python configure.py && ninja` unless production source under `/Users/mike/code/melee/src/melee/` changes. This feature should be tooling-only.

## Risks and Guardrails

- Whole-function C rewrites can accidentally change semantics. Keep the family bounded, tag semantic risk, and require score-source plus structural guard before marking anything actionable.
- Some candidate shapes may compile but fail to emit `mnDiagram_8023FC28`/`mnDiagram_SortNamesByKOs`, matching the four failed generic control-flow probes. Treat missing function emission as per-candidate negative evidence and keep scoring the rest.
- Do not rely on register-score hits alone. A candidate must also pass the structural guard, because target-score can improve while the source is structurally wrong.
- Do not loop the terminal proof. If this new family exhausts, the next unsupported family must be different and must name the next source span honestly.
- Avoid duplicating the same hard-coded candidate family in both `post_meta_source_family_synthesis.py` and transform-corpus materializers. If discoverability is needed, document or delegate instead of copying generation logic.
- Keep candidate output source-actionable. The output should be retained C files and source hunks that a decompilation agent can inspect or transplant, not just strategy descriptions.
- Preserve unrelated local work. Current `/Users/mike/code/melee` is on `master` and ahead of `origin/master`; do not reset, rebase, or clean.
- Because `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1023_rerun` is an external worktree artifact directory, tests should use synthetic fixtures; live smoke can reference the artifact path directly.

## Completion Criteria

The issue is handled when:

- Feeding the #1023 terminal artifact to `debug search source-model-synthesis` generates ranked whole-function Sort control/data-flow candidates.
- Candidates are emitted as retained C files with source hunks and source components.
- Live scoring uses real `debug target score-source` target_score for `IG34->r27` and `IG44->r25`.
- Structural guard and retained pcdump evidence are included for scored candidates.
- A jointly preserved candidate becomes actionable, or a terminal proof names a concrete next unsupported source family after bounded whole-function exhaustion.
