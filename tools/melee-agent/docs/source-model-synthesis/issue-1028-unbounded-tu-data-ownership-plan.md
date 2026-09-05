# Issue #1028 Plan: Materialize Sort Unbounded TU Data-Ownership Source Context

## Scope and Constraints

Issue #1028 is a tooling/source-model synthesis bug in `/Users/mike/code/melee`, not a production decompilation edit. The implementation should modify only tooling, tests, and design/spec documentation. Do not change `src/melee/mn/mndiagram.c` or production game source while fixing the issue.

Before implementation, re-run the repo-required capability audit:

```bash
cd /Users/mike/code/melee
melee-agent capabilities search "source-model-synthesis unbounded TU data ownership source context"
```

The current result points at existing source mutation/scoring tools (`debug mutate name-magic-source-declarations`, `debug target score-source`, and source-context commands). That supports extending the existing `source-model-synthesis` path instead of adding a new CLI.

## Root Cause

The named next family is emitted downstream but not represented upstream in the generator.

Observed synthetic reproduction, using existing test helpers only:

```json
{
  "context_next_family": "sort-unbounded-tu-data-ownership-source-context",
  "candidate_count": 0,
  "payload_status": "generated",
  "payload_candidate_count": 0,
  "represented_dimensions": [],
  "has_terminal_summary": false
}
```

The relevant code path is:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
  - Constants define `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY = "sort-unbounded-tu-data-ownership-source-context"`.
  - `_PROFILES[SORT_FUNCTION]["dimensions"]` stops at `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION`; there is no dimension for the named unbounded family.
  - `generate_source_family_candidates(...)` computes `sort_tu_source_context_only = _should_generate_sort_tu_data_symbol_helper_boundary_context(context)`, then immediately returns `[]` if `_sort_tu_data_symbol_helper_boundary_context_active_terminal(context)` is true.
  - `_sort_tu_data_symbol_helper_boundary_context_active_terminal(...)` returns true when the current proof has `next_unsupported_source_family == "sort-unbounded-tu-data-ownership-source-context"`.
  - `_zero_candidate_generation_blockers(...)` has no unbounded-family blocker, and `_should_terminalize_zero_candidate_generation(...)` only terminalizes the prior bounded TU helper-boundary family blocker.
  - `build_generated_source_family_payload([], context)` therefore emits a non-terminal generated payload with zero candidates and no dimension rows for the current family.

Downstream pieces are coherent for the handoff but not for the next generator:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
  - Defines the same next family and ranks TU helper-boundary exhaustion as the latest Sort stage.
  - Does not define a stage after unbounded TU data ownership.
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`
  - Reports the next unsupported source family from retained-frontier terminal proofs.
  - Does not know how to distinguish "ready to synthesize unbounded TU data ownership" from "unbounded TU data ownership has itself been tried/exhausted".

So the actual bug is not just "candidate_count is zero"; it is a broken state-machine transition. One stage names `sort-unbounded-tu-data-ownership-source-context`, but the synthesis profile, generation gates, zero-candidate terminalization, retained-frontier priority, and allocator next-step model do not materialize or close that stage.

## Desired Behavior

When the current ceiling names `sort-unbounded-tu-data-ownership-source-context`, `source-model-synthesis` must do one of two things:

1. Materialize retained full-TU C candidates/source hunks for that family, with score commands that use full-unit source scoring against `mnDiagram_8023FC28` and require IG34->r27 plus IG44->r25 preservation.
2. If the local source does not match the expected source spans, emit a terminal proof for `sort-unbounded-tu-data-ownership-source-context`, not `status: generated` with zero candidates.

The implementation should prefer option 1 for the current `mndiagram.c` shape.

## Tests First

Add failing tests before implementation in `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`.

1. Add `test_sort_unbounded_tu_data_ownership_generation_from_tu_terminal`.

   Build a terminal TU context from existing helpers:

   - `context = _sort_tu_source_context(tmp_path)`
   - generate bounded TU candidates
   - classify them with synthetic non-joint-preserving scores, mirroring issue #1028 (`actual34=24` or `25`, `actual44=31` or `None`, accepted structural guard as appropriate)
   - normalize the resulting terminal payload back into a new context
   - call `generate_source_family_candidates(_sort_source(), next_context, max_per_dimension=10, include_source=True)`

   Assert:

   - candidates are non-empty;
   - every candidate has `dimension_id == SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION`;
   - candidate IDs use a new stable prefix such as `post-meta-sort-unbounded-tu-data-ownership-`;
   - every candidate has `validation_metadata.requires_full_unit_source is True`;
   - every candidate has `validation_metadata.requires_structural_guard is True`;
   - every candidate has `required_preserved_assignments == ["IG34->r27", "IG44->r25"]`;
   - every generated `score_command` includes `--full-unit-source`, `--function mnDiagram_8023FC28`, and `--checkdiff-guard`;
   - at least one candidate modifies or introduces a whole-TU declaration/source-ownership hunk before `void mnDiagram_8023FC28(void)`;
   - `source_components` include `sort-whole-tu-data-declaration`, `sort-tu-data-ownership`, and `sort-nonlocal-source-ownership`.

2. Add `test_cli_source_model_synthesis_writes_unbounded_tu_data_ownership_probes`.

   Use `CliRunner` with a synthetic terminal JSON created from the prior bounded TU terminal. Invoke:

   ```bash
   melee-agent debug search source-model-synthesis \
     --function mnDiagram_SortNamesByKOs \
     --meta-ceiling-json <tu-terminal.json> \
     --source-file <sort.c> \
     --write-probes <out> \
     --max-per-dimension 10 \
     --no-score \
     --json
   ```

   Assert:

   - exit code is `0`;
   - `status == "generated"`;
   - `candidate_count > 0`;
   - the unbounded dimension row has `candidate_count > 0`;
   - each candidate path exists;
   - `score_command` contains `--full-unit-source`;
   - generated source text contains a whole-TU data ownership spelling, not only a function-body rewrite.

3. Add `test_sort_unbounded_tu_data_ownership_exhaustion_terminalizes`.

   Score all unbounded candidates with synthetic target scores that preserve no joint improvement, matching issue #1028's evidence:

   - one row may have IG34 actual r25 and IG44 absent/null;
   - one row may have IG34 actual r24 and IG44 absent/null;
   - one row may have IG34 actual r24 and IG44 r31.

   Assert:

   - `classify_source_family_scores(...)["status"] == "terminal"`;
   - `next_unsupported_source_family` is a new family after this stage, not the same unbounded family;
   - `exhausted_dimensions` includes `SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION`;
   - `source_model_proof.source_family_synthesis.attempted_equivalence_classes` includes the unbounded dimension;
   - `retained_scored_probes` are present;
   - `terminal_blockers` include `protected-targets-not-jointly-preserved`.

4. Add `test_sort_unbounded_tu_data_ownership_zero_candidate_generation_terminalizes`.

   Use a source string with the Sort function present but without the expected TU data declaration/source span patterns. Build a context that names the unbounded family, first call `generate_source_family_candidates(bad_source, context, ...)`, and assert it returns `[]`. Then call `build_generated_source_family_payload([], context)`.

   This matters because `build_generated_source_family_payload(...)` does not receive source text; zero-candidate blockers are derived from the active context/profile dimensions. The test must prove that the candidate lane genuinely generated nothing for the malformed source before asserting terminalization.

   Assert:

   - `status == "terminal"`;
   - `candidate_count == 0`;
   - `dimensions` contains the unbounded dimension with `status == "blocked"`;
   - `generation_blockers[0].reason` equals a new blocker such as `sort-unbounded-tu-data-ownership-source-context-not-materialized`;
   - `terminal_summary` and `source_model_proof.source_family_synthesis` exist;
   - `next_unsupported_source_family` names the next unsupported source model after unbounded TU ownership.

5. Extend full-unit scoring guard coverage.

   In the existing source-context full-unit blocker tests, include the unbounded dimension in the expected protected set or add a new unbounded-specific version. This should validate that scoring a candidate that defines or rewrites whole-TU declarations without `--full-unit-source` remains `blocked` with `source-context-scored-without-full-unit-source`.

6. Add retained-frontier and allocator coherence tests.

   In `/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py`, add or extend a test that triages an unbounded TU data-ownership terminal proof and asserts:

   - the terminal proof preserves `next_unsupported_source_family`;
   - `source_family_synthesis.attempted_equivalence_classes` includes the unbounded dimension;
   - stale earlier TU helper-boundary proofs do not outrank the new unbounded proof.

   In `/Users/mike/code/melee/tools/melee-agent/tests/test_allocator_ceiling.py` or the source synthesis test that already calls `classify_allocator_ceiling`, assert:

   - allocator status remains `practical-ceiling`;
   - `current_ceiling.next_unsupported_source_family` is the post-unbounded family;
   - next steps mention the post-unbounded family, not the already-exhausted bounded TU helper-boundary family.

7. CLI smoke checks after implementation:

   ```bash
   cd /Users/mike/code/melee
   python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k 'unbounded_tu_data_ownership or tu_source_context or source_context_helper_definition'
   python -m pytest tools/melee-agent/tests/test_retained_frontier_triage.py -k 'source_model or unbounded_tu_data_ownership or tu_source_context'
   python -m pytest tools/melee-agent/tests/test_allocator_ceiling.py -k 'source_model or unbounded_tu_data_ownership or tu_source_context'
   python -m pytest tools/melee-agent/tests/search/test_cli_smoke.py -k source_model_synthesis
   ```

   If the actual issue artifacts are available in the implementing worktree, run:

   ```bash
   melee-agent debug search source-model-synthesis \
     --function mnDiagram_SortNamesByKOs \
     --meta-ceiling-json build/diagnostics/mndiagram_1027_rerun/retained_frontiers_after_tu_symbol_context/sort_allocator_after_tu_symbol_context.json \
     --source-file src/melee/mn/mndiagram.c \
     --write-probes build/diagnostics/mndiagram_1028/source_model_unbounded_tu_data_ownership \
     --max-per-dimension 10 \
     --no-score \
     --json
   ```

   Expected smoke result: `status=generated`, `candidate_count>0`, dimension includes `sort-unbounded-tu-data-ownership-source-context`, and every candidate score command includes `--full-unit-source`.

## Implementation Plan

### 1. Add the unbounded family model constants

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add constants near the existing TU helper-boundary constants:

- `SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION = "sort-unbounded-tu-data-ownership-source-context"`
- `SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_COMPONENTS`, for example:
  - `sort-whole-tu-data-declaration`
  - `sort-tu-data-ownership`
  - `sort-nonlocal-source-ownership`
  - `sort-cross-function-source-context`
- `SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_REQUIRED_SOURCE_PATTERNS`, for example:
  - whole-TU declaration or typedef ownership spanning `mnDiagram_804A0750` and `mnDiagram_804A076C`;
  - nonlocal accessor/owner used outside `mnDiagram_8023FC28`;
  - full-unit source scoring against `mnDiagram_8023FC28`;
  - source hunk before the Sort function or near shared TU data declarations.
- `SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_SOURCE_REGION_PATTERN_BLOCKER = "sort-unbounded-tu-data-ownership-source-context-not-materialized"`
- `SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_MODEL`, with clear terminal text:
  "Sort unbounded TU data-ownership source-context synthesis exhausted retained full-TU data declaration, ownership overlay, and nonlocal accessor rewrites without jointly recovering IG34/IG44. The next unsupported source span/family is an unmodeled cross-TU symbol/linkage or compiler data-section ownership model outside retained full-TU source-context synthesis."
- `SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_FAMILY = "sort-cross-tu-symbol-linkage-or-data-section-ownership-source-context"` or a similarly explicit post-unbounded family.

Add the new dimension to `_PROFILES[SORT_FUNCTION]["dimensions"]` after `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION`.

### 2. Fix the generator state transition

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Change `generate_source_family_candidates(...)` to recognize the new stage before returning for the bounded TU terminal:

- compute `sort_unbounded_tu_data_ownership_only = _should_generate_sort_unbounded_tu_data_ownership_context(context)`;
- only let `_sort_tu_data_symbol_helper_boundary_context_active_terminal(context)` return `[]` when `sort_unbounded_tu_data_ownership_only` is false;
- include `sort_unbounded_tu_data_ownership_only` in the "skip earlier patcher specs" condition so the generator does not also emit legacy local/natural/semantic candidates;
- append `_sort_unbounded_tu_data_ownership_context_source_candidates(...)` after `_sort_tu_data_symbol_helper_boundary_context_source_candidates(...)`.

Add:

```python
def _should_generate_sort_unbounded_tu_data_ownership_context(context: MetaCeilingContext) -> bool:
    ...
```

It should return true when:

- `context.function == SORT_FUNCTION`;
- the unbounded dimension has not already been exhausted;
- `next_unsupported_source_family` anywhere in `context.current_ceiling` equals `SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION`, or the next-model text contains the issue markers: `whole-TU data declaration`, `nonlocal source-ownership`, and `bounded Sort TU source-context model`.

Add:

```python
def _sort_unbounded_tu_data_ownership_context_exhausted(context: MetaCeilingContext) -> bool:
    ...
```

Mirror `_sort_tu_data_symbol_helper_boundary_context_exhausted(...)`, but check the new dimension, exhausted next model, and exhausted next family.

### 3. Materialize retained full-TU candidates

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add:

- `_sort_unbounded_tu_data_ownership_context_patcher_specs()`
- `_sort_unbounded_tu_data_ownership_context_spec(...)`
- `_sort_unbounded_tu_data_ownership_context_source_candidates(...)`
- patchers that operate on `source_text` and the located Sort function span, similar to `_sort_tu_data_symbol_helper_boundary_context_source_candidates(...)`.

Candidate design should be bounded and deterministic, despite the family name:

1. `whole-tu-storage-owner-declaration`
   - Introduce a file-local whole-TU owner typedef/inline accessor before the existing Sort function, based on the real adjacent globals:
     - `mnDiagram_804A0750_t mnDiagram_804A0750;`
     - `mnDiagram_804A076C_t mnDiagram_804A076C;`
   - Route Sort through the owner accessor for sorted names, preserving full-unit source context.

2. `nonlocal-name-accessor-ownership`
   - Introduce a nonlocal accessor near `mnDiagram_GetNameByIndex` and use it from both `mnDiagram_GetNameByIndex` and `mnDiagram_8023FC28`, so the ownership rewrite is actually nonlocal.

3. `data-declaration-overlay-owner`
   - Model the adjacent data declarations as one owner/overlay declaration in source context, but only in retained candidate files. Do not alter production declarations.
   - Do not remove or rename the existing `mnDiagram_804A0750_t`, `mnDiagram_804A076C_t`, `mnDiagram_804A0750`, or `mnDiagram_804A076C` symbols unless every full-TU reference is also updated and verified. Prefer unique `mnDiagram_PostMeta...` overlay types/accessors and compatible aliases so generated retained C remains valid with existing helper functions such as `mnDiagram_GetFighterByIndex()` and `mnDiagram_GetNameByIndex()`.

4. Optional if easy and still bounded: `owner-qualified-shift-helper`
   - Combine the whole-TU owner accessor with the existing shift helper pattern to test the exact issue family: data ownership plus nonlocal source ownership.

Each candidate must set validation metadata:

- `dimension_id`: `SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION`
- `unbounded_tu_data_ownership_source_context_model`: true
- `requires_target_score_validation`: true
- `requires_full_unit_source`: true
- `requires_structural_guard`: true
- `score_function`: `context.source_function or context.function`
- `required_preserved_assignments`: `["IG34->r27", "IG44->r25"]`
- `required_source_patterns`: the new required pattern list
- `source_components`: the new component list

Do not hand-roll a separate output writer. Reuse `SourceFamilyCandidate`, `_source_hunks`, `_normalized_hunk_signature`, `write_source_family_candidates(...)`, and `_score_command_hint(...)` so output JSON and score commands stay consistent with earlier families.

### 4. Terminalize zero-candidate unbounded generation

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Extend `_zero_candidate_generation_blockers(...)` with:

```python
*_sort_unbounded_tu_data_ownership_context_zero_candidate_generation_blockers(dimensions, context)
```

The blocker should mirror the bounded TU helper-boundary blocker but use the new dimension, reason, required patterns, source function, trigger model, and trigger family.

Update `_should_terminalize_zero_candidate_generation(...)` to terminalize both:

- existing `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_SOURCE_REGION_PATTERN_BLOCKER`;
- new `SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_SOURCE_REGION_PATTERN_BLOCKER`.

Generalize `_build_zero_candidate_source_family_terminal_proof(...)` instead of hard-coding the bounded TU family. Either:

- add parameters/derive from the blocker dimension to select attempted dimension, next model, and next family; or
- introduce `_build_zero_candidate_terminal_for_sort_source_context(...)` with a table mapping blocker reason to terminal metadata.

Expected change: zero-candidate unbounded runs emit `status: terminal`, `terminal_summary`, `source_model_proof`, and a blocked dimension row for `sort-unbounded-tu-data-ownership-source-context`.

### 5. Classify scored unbounded candidates coherently

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Update:

- `_FULL_UNIT_REQUIRED_SOURCE_CONTEXT_DIMENSIONS` to include `SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION`.
- `_can_terminalize_structural_guard_exhaustion(...)` attempted-dimension set to include the new dimension.
- `_can_terminalize_required_assignment_exhaustion(...)` required dimensions tuple to include the new dimension.
- `_terminal_next_unsupported_source_model(...)` so attempted unbounded dimension returns the new exhausted next model before the bounded TU helper-boundary check.
- `_full_selection_swap_next_hint(...)` or rename/generalize it to handle the unbounded dimension and emit `next_unsupported_source_family` plus `next_unsupported_source_spans`.

Important ordering: check the unbounded dimension before `SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION`, otherwise an artifact that carries both prior and current dimensions can regress to the stale bounded next family.

### 6. Retained-frontier triage stage ordering

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`

Add matching constants for:

- `_SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION`
- exhausted next model
- exhausted next family

Update:

- `_SORT_SOURCE_FAMILY_DIMENSIONS`
- `_SORT_FALLBACK_DEFERRED_SOURCE_FAMILY_DIMENSIONS`
- `_source_model_proof_stage_rank(...)` so unbounded TU exhaustion ranks above bounded TU helper-boundary exhaustion.
- any next-model derivation function that currently returns `_SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_MODEL` as the latest Sort stage. Add an unbounded check before the bounded TU check.
- any source-family dimension extraction/prefix helpers if candidate IDs or dimension labels are filtered by known prefixes. In particular, update `_dimension_from_candidate_id(...)` and profile token/prefix lists so the new `post-meta-sort-unbounded-tu-data-ownership-` candidate prefix maps to the unbounded dimension instead of being treated as generic Sort source-model evidence.

Goal: a retained-frontiers aggregate containing both the #1027 bounded TU proof and a new #1028 unbounded proof must select the #1028 proof as current ceiling.

### 6a. Real source declaration-order guard

Add at least one regression that uses the real `/Users/mike/code/melee/src/melee/mn/mndiagram.c` text, or a fixture that preserves its relevant declaration order:

- `mnDiagram_804A0750_t` and `mnDiagram_804A076C_t` definitions;
- globals `mnDiagram_804A0750` and `mnDiagram_804A076C`;
- `mnDiagram_GetFighterByIndex()` / `mnDiagram_GetNameByIndex()`;
- `mnDiagram_8023FC28()`.

Assert generated unbounded candidates keep helper/accessor declarations before first use and do not produce duplicate/conflicting definitions of the existing TU symbols. This catches invalid full-TU C that a simplified `_sort_source()` fixture may miss.

### 7. Allocator ceiling next steps

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`

Allocator behavior already echoes `terminal_proof.next_unsupported_source_family` in next steps. Still add constants/recognition if tests expose stale behavior:

- include the new dimension/family in any retained-meta current-ceiling summarization if the code ranks or filters source families locally;
- ensure `current_ceiling.next_unsupported_source_family` is the post-unbounded family after unbounded terminalization;
- ensure next steps no longer tell the user to run the already-exhausted `sort-unbounded-tu-data-ownership-source-context` family.

### 8. CLI help/spec design text

Add a short design note, for example:

File: `/Users/mike/code/melee/docs/plans/issue-1028-unbounded-tu-data-ownership.md`

Content:

- State-machine progression:
  `sort-tu-data-symbol-helper-boundary-source-context` -> `sort-unbounded-tu-data-ownership-source-context` -> `sort-cross-tu-symbol-linkage-or-data-section-ownership-source-context`.
- Contract: every source-context candidate that changes declarations/helpers outside `mnDiagram_8023FC28` must be scored with `--full-unit-source`.
- Contract: zero-candidate generation for a named current family is invalid; it must either materialize candidates or emit a terminal source-model proof naming the next unsupported family.
- Contract: retained-frontier and allocator artifacts must rank newer source-model families over stale previous-family proofs.

This is useful project documentation and prevents the #1027 -> #1028 handoff from being rediscovered later.

## Full-Unit Scoring and Retained-Frontier Coherence

Keep scoring semantics unchanged:

- Candidate paths should be retained full-TU source files.
- Score target remains `mnDiagram_8023FC28`.
- `score_source_candidates(...)` should automatically pass `--full-unit-source` via `_candidate_requires_full_unit_source(...)`.
- `write_source_family_candidates(...)` should preserve `score_command` and `validation_metadata.score_source_command_hint`.
- `classify_source_family_scores(...)` should still refuse helper/declaration candidates scored without full-unit source.

Keep retained-frontier/allocator semantics coherent:

- Generated unbounded candidates are not a practical ceiling until scored.
- Scored no-joint-progress unbounded candidates terminalize the current family and advance `next_unsupported_source_family`.
- Zero-candidate unbounded generation terminalizes only when source-region pattern blockers explain why no candidates could be materialized.
- Older #1027 bounded TU helper-boundary terminal proofs must not outrank a newer #1028 unbounded terminal proof.

## Validation Commands

After implementation:

```bash
cd /Users/mike/code/melee
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k 'unbounded_tu_data_ownership or tu_source_context or source_context_helper_definition'
python -m pytest tools/melee-agent/tests/test_retained_frontier_triage.py -k 'source_model or unbounded_tu_data_ownership or tu_source_context'
python -m pytest tools/melee-agent/tests/test_allocator_ceiling.py -k 'source_model or unbounded_tu_data_ownership or tu_source_context'
python -m pytest tools/melee-agent/tests/search/test_cli_smoke.py -k source_model_synthesis
```

If issue artifacts are restored, run the no-score CLI smoke first and verify candidate materialization:

```bash
melee-agent debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json build/diagnostics/mndiagram_1027_rerun/retained_frontiers_after_tu_symbol_context/sort_allocator_after_tu_symbol_context.json \
  --source-file src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/mndiagram_1028/source_model_unbounded_tu_data_ownership \
  --max-per-dimension 10 \
  --no-score \
  --json
```

Then run live scoring only after the generated payload looks correct:

```bash
melee-agent debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json build/diagnostics/mndiagram_1027_rerun/retained_frontiers_after_tu_symbol_context/sort_allocator_after_tu_symbol_context.json \
  --source-file src/melee/mn/mndiagram.c \
  --target <target-json-for-mnDiagram_8023FC28> \
  --cflags-from src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/mndiagram_1028/source_model_unbounded_tu_data_ownership_scored_sources \
  --max-per-dimension 10 \
  --score \
  --json
```

Stop condition: the family either produces a ranked actionable candidate that jointly preserves IG34->r27 and IG44->r25, or emits a terminal proof for `sort-unbounded-tu-data-ownership-source-context` naming the next unsupported source family.
