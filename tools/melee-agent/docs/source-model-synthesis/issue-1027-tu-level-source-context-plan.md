# Issue #1027: materialize Sort TU-level source-context family

## Scope and constraints

Plan only. Do not edit production or test files during the planning step.

Implementation must preserve unrelated local work:

- Start with `git status --short` in `/Users/mike/code/melee`.
- If any listed implementation file is already dirty, inspect it before editing and preserve unrelated hunks.
- Use `apply_patch` for manual edits.
- Do not modify issue artifacts under `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/...`; use them only as read-only fixtures/smoke inputs.
- Keep generated smoke output under an ignored build or temp directory, and do not commit diagnostics.

## Evidence reviewed

Read-only artifacts from the issue:

- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1026_rerun/source_model_helper_data_context/sort_source_model_helper_data_context_scored.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1026_rerun/source_model_tu_symbol_context/sort_source_model_tu_symbol_context_scored.json`
- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1026_rerun/retained_frontiers_after_helper_data_context/sort_allocator_after_helper_data_context.json`

Confirmed behavior from `/Users/mike/code/melee` with repo-local CLI:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1026_rerun/retained_frontiers_after_helper_data_context/sort_allocator_after_helper_data_context.json \
  --source-file src/melee/mn/mndiagram.c \
  --max-per-dimension 10 \
  --no-score \
  --json
```

The result is `status: generated`, `candidate_count: 0`, no `generation_blockers`, no `terminal_summary`, and no `next_unsupported_source_model` or `next_unsupported_source_family`. Its dimensions stop at `sort-helper-extraction-data-layout-or-cross-function-rewrite`.

The prior helper/data-layout scored artifact is terminal and valid:

- `candidate_count: 3`, `score_count: 3`
- all rows have `score_error: null`
- best rows still fail the protected target pair
- terminal next family is `sort-tu-data-symbol-helper-boundary-source-context`

Source locations reviewed:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`
- `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`
- `/Users/mike/code/melee/src/melee/mn/mndiagram.c`

Capability audit:

`melee-agent capabilities search "TU-level data-symbol helper-boundary cross-function source-context source-model-synthesis sort candidates terminal proof"` reports no existing TU-level materializer. The closest reusable commands are scoring/triage/search helpers.

## Root cause

`post_meta_source_family_synthesis.py` names the next unsupported family but never models it.

Specific gaps:

1. The Sort profile dimensions end at `SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION`; there is no dimension for `sort-tu-data-symbol-helper-boundary-source-context`.
2. `generate_source_family_candidates()` calls candidate lanes for older Sort families, whole-function rewrites, and helper/data-layout context, but has no TU-level data-symbol/helper-boundary/cross-function source-context lane after helper/data-layout exhaustion.
3. `_zero_candidate_generation_blockers()` has no blocker for the named TU family, so zero generated candidates are treated as a normal generated payload.
4. `build_generated_source_family_payload()` never terminalizes a no-score zero-candidate artifact, even when the active context names a concrete unsupported source family.
5. `_terminal_next_unsupported_source_model()`, `_full_selection_swap_next_hint()`, and `_source_model_terminal_exhaustion()` only encode the chain through full-selection, whole-function, and helper/data-layout. They cannot emit a terminal proof for the new TU family.
6. `retained_frontier_triage.py` has its own Sort source-model dimension/prefix profile that also stops at helper/data/layout. A new terminal proof could be partially normalized but the family would not be first-class downstream.

The source split that motivates the new family is in `/Users/mike/code/melee/src/melee/mn/mndiagram.c`:

- TU data symbols and overlays are declared at lines 31-77.
- `mnDiagram_GetNameByIndex()` reads `mnDiagram_804A076C.sorted_names`.
- `mnDiagram_8023FC28()` initializes through an `mnDiagram_Assets*` overlay and `dst`, but comparison still reads `mnDiagram_804A076C.sorted_names` directly.
- The previous helper/data-layout lane only inserted local helpers/accessors around the Sort function. It did not rewrite TU-level data-symbol ownership or cross-function accessors.

## Implementation plan

### 1. Add the new Sort source-family constants

Edit `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`.

Add constants next to the existing helper/data-layout constants:

- `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION = "sort-tu-data-symbol-helper-boundary-source-context"`
- `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_COMPONENTS = ("sort-tu-data-symbol", "sort-helper-boundary", "sort-cross-function-source-context")`
- `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_REQUIRED_SOURCE_PATTERNS`, with strings covering:
  - TU-level overlay/accessor for `mnDiagram_804A0750` plus `mnDiagram_804A076C`
  - helper or accessor outside `mnDiagram_8023FC28`
  - at least one source hunk outside the Sort helper body
  - full-unit source scoring against `mnDiagram_8023FC28`
- `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_SOURCE_REGION_PATTERN_BLOCKER = "sort-tu-data-symbol-helper-boundary-source-context-not-materialized"`
- `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_MODEL`, e.g.:
  `Sort TU-level data-symbol/helper-boundary/cross-function source-context synthesis exhausted bounded storage-overlay, shared accessor, and helper-boundary source shapes without jointly recovering IG34/IG44. The next unsupported source span/family is an unmodeled whole-TU data declaration or nonlocal source-ownership rewrite outside the bounded Sort TU source-context model.`
- `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY = "sort-unbounded-tu-data-ownership-source-context"`

Update `_PROFILES[SORT_FUNCTION]["dimensions"]` to append the new dimension after `SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION`.

### 2. Add trigger and exhaustion predicates

In `post_meta_source_family_synthesis.py`, add helpers near `_should_generate_sort_helper_data_layout_context()`:

- `_should_generate_sort_tu_data_symbol_helper_boundary_context(context: MetaCeilingContext) -> bool`
- `_sort_tu_data_symbol_helper_boundary_context_exhausted(context: MetaCeilingContext) -> bool`
- `_sort_tu_data_symbol_helper_boundary_context_active_terminal(context: MetaCeilingContext) -> bool`

Trigger when:

- `context.function == SORT_FUNCTION`
- current context is not already exhausted for the new dimension
- any nested `next_unsupported_source_family` equals `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION`
- or any nested/current `next_unsupported_source_model` contains all of `TU-level`, `data-symbol`, `helper-boundary`, and `cross-function source-context`

Do not trigger the older helper/data-layout lane once the new TU family is active. Keep `_sort_helper_data_layout_context_exhausted()` returning true for the current issue context.

Important ordering correction from independent review: replace the existing
early return at `generate_source_family_candidates()` line 566
(`_sort_helper_data_layout_context_active_terminal(context)`) instead of
layering the TU lane after it. The current helper terminal predicate fires for
`next_unsupported_source_family == "sort-tu-data-symbol-helper-boundary-source-context"`,
which is exactly when this issue needs to generate the new family. Implementation
should compute a `sort_tu_source_context_only`/active flag before older Sort
lanes, skip older specs/helper/data-layout generation when that flag is true,
and append the TU lane so it is the only generated family. A terminal
short-circuit is only appropriate after the new TU family itself is exhausted.

### 3. Materialize bounded full-TU candidates

In `generate_source_family_candidates()`, after `_sort_helper_data_layout_context_source_candidates(...)`, append a call to a new lane:

- `_sort_tu_data_symbol_helper_boundary_context_source_candidates(...)`

Use the same dedupe and `per_dimension` mechanics as helper/data/layout.

Add spec and patcher helpers near the helper/data-layout implementation:

- `_sort_tu_data_symbol_helper_boundary_context_patcher_specs()`
- `_sort_tu_data_symbol_helper_boundary_context_spec(...)`
- `_tu_data_symbol_helper_boundary_context_patcher(variant: str)`
- `_sort_tu_data_symbol_helper_boundary_context_source_candidates(...)`

All generated candidates must set validation metadata:

- `dimension_id: SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION`
- `equivalence_class: SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION`
- `tu_data_symbol_helper_boundary_source_context_model: True`
- `semantic_algorithm_shape: True`
- `requires_target_score_validation: True`
- `requires_full_unit_source: True`
- `requires_structural_guard: True`
- `score_function: context.source_function or context.function`
- `source_components` for the relevant TU data-symbol/helper-boundary/cross-function parts
- `required_preserved_assignments: ["IG34->r27", "IG44->r25"]`
- `required_source_patterns: list(SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_REQUIRED_SOURCE_PATTERNS)`

Candidate IDs and bounded source shapes:

1. `post-meta-sort-tu-source-context-storage-overlay-accessor`
   - Insert before `mnDiagram_8023FC28()`:
     - `typedef struct mnDiagram_PostMetaSortTUStorage { mnDiagram_804A0750_t fighters; mnDiagram_804A076C_t names; } mnDiagram_PostMetaSortTUStorage;`
     - `static inline mnDiagram_PostMetaSortTUStorage* mnDiagram_PostMetaSortTUStorageRef(void) { return (mnDiagram_PostMetaSortTUStorage*) &mnDiagram_804A0750; }`
   - In `mnDiagram_8023FC28()`, introduce `mnDiagram_PostMetaSortTUStorage* sort_storage = mnDiagram_PostMetaSortTUStorageRef();`
   - Route `dst` and comparison reads through `sort_storage->names.sorted_names`.
   - Preserve the existing shift/emission pointer shape using `&sort_storage->fighters.sorted_fighters[max_idx]` plus `sizeof(mnDiagram_804A0750_t)`.

2. `post-meta-sort-tu-source-context-shared-name-accessor`
   - Insert `static inline u8* mnDiagram_PostMetaSortNamesBase(void)` returning `mnDiagram_804A076C.sorted_names`.
   - Define or at least declare this helper before `mnDiagram_GetNameByIndex()` because that caller appears earlier in the TU than `mnDiagram_8023FC28()`. Prefer inserting the helper immediately before `mnDiagram_GetNameByIndex()` so generated C is valid without relying on implicit declarations.
   - Rewrite `mnDiagram_GetNameByIndex()` to return `mnDiagram_PostMetaSortNamesBase()[idx]`, creating an explicit cross-function TU hunk.
   - Rewrite the Sort target function's initialization, comparison, and emission reads through a local `u8* sorted_names = mnDiagram_PostMetaSortNamesBase();`.

3. `post-meta-sort-tu-source-context-comparison-helper-data-symbol`
   - Insert a TU-level helper such as `mnDiagram_PostMetaSortCandidateBetterTU(u32* totals, int max_idx, int j)` that obtains the shared names base internally and performs the existing predicate.
   - Replace the comparison condition in `mnDiagram_8023FC28()` with the helper call.
   - This is intentionally different from the old helper/data-layout comparison helper because the helper owns the TU data-symbol access boundary instead of receiving only local operands.

4. `post-meta-sort-tu-source-context-storage-shift-helper`
   - Insert the TU storage overlay accessor from candidate 1.
   - Insert `mnDiagram_PostMetaSortShiftEmitTU(mnDiagram_PostMetaSortTUStorage* sort_storage, u8* dst, int i, int max_idx)`.
   - Replace the existing max-index shift/emission block with that helper call.
   - This tests a helper boundary coupled to the TU storage model rather than the previous local `mnDiagram_Assets*` model.

Implement patchers with structured string helpers already present in the module where possible:

- Reuse `_insert_before_sort_function(...)`
- Reuse `_replace_sort_comparison_condition(...)`
- Reuse `_source_hunks(...)` and `_normalized_hunk_signature(...)`
- Add small purpose-built replacements for exact source snippets in `mnDiagram_GetNameByIndex()` and `mnDiagram_8023FC28()`

If a required source snippet is absent, return `None`; the zero-candidate blocker path below will make that auditable.

### 4. Add zero-candidate blocker and terminal proof path

In `post_meta_source_family_synthesis.py`, extend `_zero_candidate_generation_blockers()` with:

- `_sort_tu_data_symbol_helper_boundary_context_zero_candidate_generation_blockers(dimensions, context)`

The new blocker should return a row when the new family should generate but its dimension has `candidate_count == 0`:

```python
{
    "dimension_id": SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION,
    "reason": SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_SOURCE_REGION_PATTERN_BLOCKER,
    "required_patterns": list(SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_REQUIRED_SOURCE_PATTERNS),
    "source_function": context.source_function,
    "function": context.function,
    "trigger_next_unsupported_source_model": context.next_unsupported_source_model,
    "trigger_next_unsupported_source_family": SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION,
}
```

Update `build_generated_source_family_payload()` so that a no-score run with zero candidates and terminal-generation blockers does not return a bare generated artifact. Add a helper such as:

- `_should_terminalize_zero_candidate_generation(context, generation_blockers) -> bool`
- `_build_zero_candidate_source_family_terminal_proof(context, generated_dimensions, generation_blockers) -> dict[str, Any]`

For #1027, this helper should emit:

- `status: "terminal"`
- `kind: profile["proof_kind"]`
- `family_id: profile["proof_family_id"]`
- `terminal_reason: profile["terminal_reason"]`
- `candidate_count: 0`
- `scored_count: 0`
- `terminal_summary`
- `source_model_proof.source_family_synthesis.status: "synthesis-exhausted"`
- `attempted_equivalence_classes` containing the new dimension
- `blocked_dimensions` and `unmaterialized_dimensions` containing the new dimension row with the blocker
- `generation_blockers`
- `next_unsupported_source_model: SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_MODEL`
- `next_unsupported_source_family: SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY`

Keep this path narrow. It should only terminalize dimensions explicitly marked as terminal-safe source-family materialization blockers, not any arbitrary no-candidate generated artifact.

### 5. Extend terminal classification and next-family hints

In `post_meta_source_family_synthesis.py`:

- Add the new dimension to `_can_terminalize_structural_guard_exhaustion(...)` for Sort.
- Add the new dimension to `_can_terminalize_required_assignment_exhaustion(...)` for Sort.
- Update `_terminal_next_unsupported_source_model(...)` so attempts for the new dimension return `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_MODEL`.
- Rename `_full_selection_swap_next_hint(...)` to a more general internal helper, or minimally add a first branch for the new dimension:
  - select the best ranked row for `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION`
  - return `next_unsupported_source_family: SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY`
  - include `next_unsupported_source_spans` from the best row's `source_components` and `source_hunks`
- Update `_source_model_terminal_exhaustion(...)` terminal cases to include the new dimension/model/family.

### 6. Keep retained-frontier normalization in sync

Edit `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`.

Add the new dimension constant near `_SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION`.

Update:

- `_SORT_SOURCE_FAMILY_DIMENSIONS` to append the new dimension.
- `_SORT_FALLBACK_DEFERRED_SOURCE_FAMILY_DIMENSIONS` to include the new dimension.
- `_source_model_proof_stage_rank()` so the new TU dimension/model/family ranks after helper/data-layout. Add both a direct dimension/family branch and a fallback for the new exhausted next model/family; otherwise stale helper/data-layout proofs can outrank the new terminal proof.
- `_source_model_synthesis_profile(... Sort ...)`:
  - `candidate_prefixes`: add `post-meta-sort-tu-source-context-`
  - `family_prefixes`: add `sort-tu-data-symbol`, `sort_tu_data_symbol`, `sort-helper-boundary`, `sort_helper_boundary`
  - `strategy_tokens`: add `tu-source-context`, `tu_source_context`, `tu-data-symbol`, `tu_data_symbol`, `helper-boundary`, `helper_boundary`

If regression tests show allocator next-step rendering drops the new next family, make the smallest necessary edit in `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py` to preserve/display `next_unsupported_source_family`. Based on review, allocator already reads this from retained meta terminal proofs, so no planned allocator edit unless tests fail.

## Regression tests

Primary test file:

- `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add or update these tests.

### 1. Replace the old "no next candidates" expectation

Existing test:

- `test_retained_frontier_normalizes_helper_data_layout_source_context_dimensions`

Replace the final assertion:

```python
assert next_candidates == []
```

with assertions that the new family is first-class:

- `next_candidates` is non-empty
- all next candidates have `dimension_id == synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION`
- candidate IDs include at least `post-meta-sort-tu-source-context-storage-overlay-accessor` and `post-meta-sort-tu-source-context-shared-name-accessor`
- all candidates carry `requires_full_unit_source`, `requires_structural_guard`, and `required_preserved_assignments == ["IG34->r27", "IG44->r25"]`

### 2. Candidate generation from helper/data-layout terminal

Add `test_sort_tu_source_context_generation_from_helper_data_layout_terminal`.

Fixture setup:

- Reuse `_sort_helper_data_layout_context(tmp_path)` to create the helper/data-layout context.
- Generate helper/data-layout candidates and classify them terminal with `_score(candidate, actual34=27, actual44=22, accepted=True)`.
- Normalize the resulting terminal payload through retained-frontiers/allocator or directly through `normalize_meta_ceiling_context([terminal], ...)`, matching the production path used by the existing helper tests.
- Run `generate_source_family_candidates(_sort_source(), next_context, max_per_dimension=10, include_source=True)`.

Assertions:

- only the new dimension is generated
- `candidate_count >= 3`
- source hunks are present
- at least one candidate has a source hunk outside `mnDiagram_8023FC28()` such as `mnDiagram_GetNameByIndex()`
- component IDs include `sort-tu-data-symbol`, `sort-helper-boundary`, and `sort-cross-function-source-context` across the candidate set
- candidate source text contains the inserted TU helper/accessor before `void mnDiagram_8023FC28(void)`
- the shared-name-accessor candidate defines `mnDiagram_PostMetaSortNamesBase` before `mnDiagram_GetNameByIndex`, catching invalid helper declaration order without needing a full compiler run in this unit test

### 3. TU family scoring exhaustion terminalizes

Add `test_sort_tu_source_context_exhaustion_terminalizes`.

Fixture setup:

- Generate the new TU candidates from the helper/data-layout terminal context.
- Score all candidates with no joint target preservation, for example `_score(candidate, actual34=24, actual44=27, accepted=True)` or another zero-progress pair.

Assertions:

- `classify_source_family_scores(...)["status"] == "terminal"`
- `next_unsupported_source_model == synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_MODEL`
- `next_unsupported_source_family == synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY`
- `exhausted_dimensions` includes the new dimension
- `source_model_proof.source_family_synthesis.attempted_equivalence_classes` includes the new dimension
- terminal blockers include `protected-targets-not-jointly-preserved`
- retained scored probes include all generated candidate IDs

### 4. Zero-candidate no-score path emits terminal proof

Add `test_sort_tu_source_context_zero_candidate_generation_terminalizes`.

Fixture setup:

- Build a context whose current ceiling names `sort-tu-data-symbol-helper-boundary-source-context`.
- Call `build_generated_source_family_payload([], context)`.

Assertions:

- payload status is `terminal`, not `generated`
- `candidate_count == 0`
- `terminal_summary` exists
- `generation_blockers[0]["reason"] == synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_SOURCE_REGION_PATTERN_BLOCKER`
- `generated_family_dimensions` or `dimensions` includes the new dimension with `status == "blocked"`
- `source_model_proof.source_family_synthesis.unmaterialized_dimensions` includes the new dimension
- payload carries `next_unsupported_source_model` and `next_unsupported_source_family`

This test prevents a repeat of the issue even if future source snippets stop matching.

### 5. CLI writes TU-level probes

Add `test_cli_source_model_synthesis_writes_tu_source_context_probes`.

Fixture setup:

- Write the helper/data-layout terminal payload to `tmp_path / "sort-helper-data-layout-terminal.json"`.
- Write `_sort_source()` to `tmp_path / "sort.c"`.
- Invoke `search_app`:

```python
CliRunner().invoke(
    search_app,
    [
        "source-model-synthesis",
        "--function", SORT_FUNCTION,
        "--meta-ceiling-json", str(meta),
        "--source-file", str(source),
        "--write-probes", str(output),
        "--max-per-dimension", "10",
        "--no-score",
        "--json",
    ],
)
```

Assertions:

- exit code is `0`
- `status == "generated"`
- `candidate_count >= 3`
- dimensions include the new family with candidate count > 0
- all returned `candidate_path` files exist
- at least one written file contains `mnDiagram_PostMetaSortTUStorage`
- at least one written file contains `mnDiagram_PostMetaSortNamesBase`
- the written shared-name-accessor file has `mnDiagram_PostMetaSortNamesBase` before `mnDiagram_GetNameByIndex`

### 6. Retained-frontier and allocator consume the new terminal proof

Add `test_retained_frontier_normalizes_tu_source_context_terminal_proof`.

Fixture setup:

- Generate and terminalize the new TU candidates as in test 3.
- Write the terminal payload to a tmp artifact.
- Run `triage_retained_frontiers(repo_root=tmp_path, functions=[SORT_FUNCTION], artifacts=[artifact])`.
- Run `classify_allocator_ceiling([triaged], function=SORT_FUNCTION)`.

Assertions:

- retained terminal proof preserves the new `attempted_equivalence_classes`
- retained terminal proof preserves `next_unsupported_source_model` and `next_unsupported_source_family`
- allocator result is `practical-ceiling`
- allocator `current_ceiling.source_family_synthesis.attempted_equivalence_classes` includes the new dimension
- allocator next steps mention the new next unsupported source family

## Smoke checks

Run targeted tests first:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  -k 'tu_source_context or helper_data_layout_source_context'
```

Run downstream-focused tests:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  -k 'retained_frontier_normalizes_tu_source_context_terminal_proof or retained_frontier_normalizes_helper_data_layout_source_context_dimensions or allocator_ceiling_prefers'
```

Run compile checks:

```bash
PYTHONPATH=tools/melee-agent python -m py_compile \
  tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py \
  tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py \
  tools/melee-agent/src/mwcc_debug/allocator_ceiling.py \
  tools/melee-agent/src/search/cli/__init__.py \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py
```

Run the full source-family synthesis test file:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py
```

Re-run the issue reproducer from `/Users/mike/code/melee`:

```bash
rm -rf build/diagnostics/issue_1027_tu_source_context
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1026_rerun/retained_frontiers_after_helper_data_context/sort_allocator_after_helper_data_context.json \
  --source-file src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/issue_1027_tu_source_context \
  --max-per-dimension 10 \
  --no-score \
  --json > build/diagnostics/issue_1027_tu_source_context/sort_tu_source_context_generated.json
```

Expected for the reproducer:

```bash
jq '{status, candidate_count, tu_dimensions: [.dimensions[] | select(.dimension_id == "sort-tu-data-symbol-helper-boundary-source-context")]}' \
  build/diagnostics/issue_1027_tu_source_context/sort_tu_source_context_generated.json
```

Expected output properties:

- `status == "generated"`
- `candidate_count > 0`
- the TU dimension row exists and has `candidate_count > 0`
- generated `.c` probes exist in `build/diagnostics/issue_1027_tu_source_context`

Optional real-score smoke, if the issue target artifact remains available:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1026_rerun/retained_frontiers_after_helper_data_context/sort_allocator_after_helper_data_context.json \
  --source-file src/melee/mn/mndiagram.c \
  --target /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_958_rerun/sort_target_from_diff_live.json \
  --cflags-from src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/issue_1027_tu_source_context_scored \
  --max-per-dimension 10 \
  --score \
  --checkdiff-guard \
  --json > build/diagnostics/issue_1027_tu_source_context_scored/sort_tu_source_context_scored.json
```

The scored result may be `actionable` if a candidate improves both protected targets, or `terminal` if all bounded TU-level candidates score no joint improvement. It must not be `generated` with `candidate_count: 0`, and it must not omit terminal proof fields when terminal.

## Acceptance criteria

- The source-model-synthesis no-score run from the #1027 allocator no longer emits `status=generated, candidate_count=0`.
- Normal `mndiagram.c` source produces bounded retained full-TU candidates under `sort-tu-data-symbol-helper-boundary-source-context`.
- If the TU family cannot be materialized, the payload is terminal and names a next unsupported model/family.
- Terminal scoring of the TU family preserves source hunks, source components, retained scored probes, attempted dimensions, and next unsupported model/family.
- Retained-frontiers and allocator-ceiling consume the new terminal proof without falling back to stale helper/data-layout evidence.
