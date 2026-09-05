# Fix Plan: Issue #1002 Draw Terminal Proof Handoff

## Problem

`source-model-synthesis` now generates and scores adapted Draw expression-lifetime candidates, but `classify_source_family_scores` refuses to terminalize the scored artifact when any score row has a rejected structural guard. The result is `status=blocked`, `reason=score-rows-not-terminal-safe`, even when:

- every generated candidate has a joined score row,
- there are no score metadata mismatches,
- there are no unjoined score rows,
- there are no missing score candidate ids,
- all adapted probes have zero target progress against IG32/IG37/IG46, and
- the only blocker is structural-guard rejection.

That prevents retained-frontiers and allocator-ceiling from consuming the scored Draw adapted-expression result as terminal evidence, so the workflow repeats the old `draw-coupled-post-meta-fpr-expression-lifetime` unsupported boundary instead of recording a completed source-model handoff.

## Root Cause

The decision point is `tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`.

`classify_source_family_scores` builds joined rows at lines 733-755, collects rejected structural guards at lines 781-791, and then treats any blocker as non-terminal unless `_can_terminalize_sort_natural_structural_exhaustion` returns true at lines 800-823. That helper is Sort-only by construction at lines 835-850:

- it returns false for any function other than `mnDiagram_SortNamesByKOs`;
- it only checks `SORT_NATURAL_REWRITE_DIMENSIONS`;
- it only accepts `structural-guard-not-accepted` blockers.

Draw adapted expression-lifetime probes satisfy the same terminal-safety conditions as the Sort natural rewrite exception, but there is no Draw/FPR equivalent helper. Consequently, the observed Draw artifact can be fully scored and still fail terminal proof handoff solely because the structural guard blocker is not whitelisted for Draw adapted expression-lifetime dimensions.

The terminal proof builder already has most of the required downstream shape. `build_terminal_source_family_proof` emits:

- top-level terminal proof with Draw profile kind `post-ceiling-fpr-expression-source-model-synthesis-proof`;
- `terminal_summary`;
- `post_ceiling_source_family_discovery`;
- `source_model_proof`;
- `source_model_proof.source_family_synthesis`;
- `candidate_scores`;
- `retained_scored_probes`;
- `exhausted_dimensions`;
- `unsupported_source_expression_class`;
- `next_unsupported_source_model`.

`retained_frontier_triage.py` already recognizes `post-ceiling-fpr-expression-source-model-synthesis-proof` and `post-ceiling-source-model-proof`, and `allocator_ceiling.py` already treats retained-frontiers meta-ceiling terminals as practical ceilings. The missing piece is not a new downstream consumer; it is allowing the scored Draw adapted-expression rows to become a terminal proof, while preserving enough blocker metadata for the proof to be auditable.

## Implementation Plan

1. Replace the Sort-specific terminalization gate with a generic structural-exhaustion helper.

   In `tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`, replace `_can_terminalize_sort_natural_structural_exhaustion` with a helper such as `_can_terminalize_structural_guard_exhaustion(context, score_rows, blockers)`.

   Rules:

   - reject unless blocker reasons are exactly a subset of `{"structural-guard-not-accepted"}`;
   - reject if any score row has `score_error`;
   - reject if no rows were joined;
   - for Sort, preserve current behavior by allowing rows that include any `SORT_NATURAL_REWRITE_DIMENSIONS`;
   - for Draw, allow only `context.function == DRAW_FUNCTION`, `context.register_class == "fpr"`, and rows that include at least one adapted expression-lifetime dimension or candidate marker:
     - `dimension_id` starts with `draw-expression-lifetime-`, or
     - `adapted_from_expression_interferer` is true, or
     - `validation_metadata.adapted_from_expression_interferer` is true.

   Keep the existing generic blocked behavior for legacy Draw dimensions and other functions.

2. Keep no-progress terminalization strict.

   The Draw terminalization path should only produce a terminal proof when no candidate is actionable. Existing code already returns `status=actionable` before blocker handling if a row has progress, structural guard accepted, and no score error. Do not weaken that. For Draw rows with structural-guard rejection and target progress, keep them in `risky_candidates`, but allow terminalization only when all blockers are structural guard rejections and no accepted actionable row exists.

3. Preserve structural guard blocker evidence in retained proof surfaces.

   `classify_source_family_scores` currently attaches `blockers` at top level when the Sort exception terminalizes. Keep that for Draw. Also add terminal proof preservation so downstream artifacts carry the blocker without needing the raw classifier envelope:

   - include `terminal_blockers` or `structural_guard_blockers` in the top-level terminal payload;
   - include the same blocker summary in `source_model_proof.source_family_synthesis`;
   - include the blocker summary in `post_ceiling_source_family_discovery`;
   - include blocker details per score row in `_retained_scored_probe`, ideally using existing row fields:
     - `structural_guard`;
     - `structural_guard_accepted`;
     - `score_error`;
     - `target_score`;
     - `expression_score`;
     - `classification`.

   The issue specifically requires preserving joined `target_score` rows, structural guard blockers, adapted dimension metadata, and next unsupported source model. `target_score` and dimension ids already flow through compact rows; verify and extend only where missing.

4. Preserve adapted dimension metadata.

   Ensure compact retained rows include the adapted provenance already present on candidates/score rows:

   - `adapted_from_expression_interferer`;
   - `requires_expression_score_validation`;
   - `origin_family`;
   - `origin_mutator`;
   - `origin_probe_id`;
   - `source_components`;
   - `validation_metadata` fields needed to audit the adapted dimension.

   If `_compact_score_row` already carries some of these, avoid duplicating shapes. If it does not, extend `_compact_score_row` and `_retained_scored_probe` narrowly for these fields.

5. Make terminal proof semantics explicit for zero-progress Draw adapted probes.

   For Draw structural exhaustion, the terminal proof should state:

   - `status: terminal`;
   - `kind: post-ceiling-fpr-expression-source-model-synthesis-proof`;
   - `terminal_reason: post-ceiling-fpr-expression-source-model-synthesis-exhausted`;
   - `unsupported_source_expression_class: draw-coupled-post-meta-fpr-expression-lifetime`;
   - `next_unsupported_source_model: Draw coupled post-meta FPR expression lifetime/materialization across col_offset product, row_offset fsubs, and digit-animation fsubs/callarg temp.`

   This preserves the explicit next unsupported source model when all adapted expression-lifetime probes remain 0/3. It also gives retained-frontiers a terminal proof instead of a blocked score artifact. If product direction later decides that this adapted dimension set is complete enough to advance past `draw-coupled-post-meta-fpr-expression-lifetime`, that should be represented by changing the Draw profile/default next-model text or adding a successor unsupported model, not by dropping terminal proof evidence.

6. Do not change retained-frontier or allocator-ceiling behavior unless tests expose a real ingestion gap.

   Based on review, `retained_frontier_triage.py` already recognizes the FPR expression synthesis proof and normalizes source-model proof metadata, while `allocator_ceiling.py` already promotes retained-frontiers terminal meta-ceiling to `status=practical-ceiling`. The implementation should primarily change source-model synthesis. Downstream edits should be limited to preserving newly added proof fields through normalization if a regression test proves they are stripped.

## Regression Tests

Add or update these exact tests.

1. `tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

   Add `test_draw_adapted_structural_guard_rejections_terminalize_with_blockers`.

   Test shape:

   - build `context = _draw_context()`;
   - generate and write candidates from `_draw_source()` with `max_per_dimension=1`;
   - filter to adapted expression-lifetime candidates where `dimension_id.startswith("draw-expression-lifetime-")`;
   - assert the filtered set is non-empty;
   - score only those candidates with `_draw_score(row, accepted=False)`;
   - call `classify_source_family_scores(adapted, scores, context)`;
   - assert:
     - `payload["status"] == "terminal"`;
     - `payload["reason"]` is absent or not `score-rows-not-terminal-safe`;
     - `payload["blockers"][0]["reason"] == "structural-guard-not-accepted"`;
     - `payload["score_count"] == len(adapted)`;
     - `payload["joined_score_count"] == len(adapted)`;
     - `payload["missing_score_candidate_ids"] == []`;
     - `payload["metadata_mismatches"] == []`;
     - every retained scored probe has `target_score`;
     - every retained scored probe preserves adapted provenance;
     - exhausted dimensions include every adapted `dimension_id`;
     - `payload["unsupported_source_expression_class"] == DRAW_COUPLED_UNSUPPORTED_CLASS`;
     - `payload["next_unsupported_source_model"] == DRAW_COUPLED_UNSUPPORTED_MODEL`.

2. `tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

   Add `test_draw_adapted_structural_guard_terminal_proof_triage_consumable`.

   Test shape:

   - reuse the terminal payload from the prior scenario;
   - write it to `tmp_path / "draw-adapted-terminal.json"`;
   - call `triage_retained_frontiers(repo_root=tmp_path, functions=[DRAW_FUNCTION], artifacts=[artifact])`;
   - assert:
     - overall status is `all-known-frontiers-exhausted`;
     - terminal frontiers contain `family_id == "post-ceiling-source-model-proof"`;
     - the terminal proof kind is `post-ceiling-fpr-expression-source-model-synthesis-proof`;
     - `attempted_targets == {"32": 28, "37": 26, "46": 26}`;
     - `source_model_proof.source_family_synthesis.retained_scored_probes` is non-empty;
     - each retained scored probe still has `target_score`;
     - `source_model_proof.source_family_synthesis` exposes structural guard blockers or terminal blockers;
     - retained meta-ceiling has `status == "terminal-current-source-shape-ceiling"`.

3. `tools/melee-agent/tests/test_allocator_ceiling.py`

   Add `test_allocator_ceiling_accepts_draw_adapted_source_model_terminal_proof`.

   Test shape:

   - construct a retained-frontiers aggregate containing one terminal frontier with:
     - `function: mnDiagram_DrawCellNumber`;
     - `family_id: post-ceiling-source-model-proof`;
     - `kind: post-ceiling-fpr-expression-source-model-synthesis-proof`;
     - `terminal: True`;
     - `terminal_reason: post-ceiling-fpr-expression-source-model-synthesis-exhausted`;
     - `attempted_targets/final_force_phys: {"32": 28, "37": 26, "46": 26}`;
     - `source_model_proof.source_family_synthesis.retained_scored_probes` with five adapted zero-progress rows, including `target_score` and structural guard rejection metadata;
     - `unsupported_source_expression_class: DRAW_COUPLED_UNSUPPORTED_CLASS`;
     - `next_unsupported_source_model: DRAW_COUPLED_UNSUPPORTED_MODEL`.
   - call `classify_allocator_ceiling([aggregate], function="mnDiagram_DrawCellNumber")`;
   - assert:
     - `result["status"] == "practical-ceiling"`;
     - `result["terminal_reason"] == "retained-frontiers-all-known-frontiers-exhausted/current-source-shape-ceiling"`;
     - `result["source_shape_exhausted"] is True`;
     - `result["current_ceiling"]["unsupported_source_expression_class"] == DRAW_COUPLED_UNSUPPORTED_CLASS`;
     - retained scored probes and blocker metadata are still visible under `current_ceiling["source_model_proof"]["source_family_synthesis"]`;
     - rendered text includes `draw-coupled-post-meta-fpr-expression-lifetime`.

4. `tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

   Update the existing `test_rejected_structural_guard_blocks_terminal_proof` only if needed to make the non-Draw/non-natural guard behavior explicit. It should continue to assert that legacy Sort-only generated candidates without broad natural evidence remain blocked with `score-rows-not-terminal-safe`. This protects against accidentally making all structural guard failures terminal-safe.

5. Optional artifact fixture test if the cited diagnostics become available.

   If the four issue artifacts are restored under `build/diagnostics/mndiagram_1000_1001_rerun`, add a non-default fixture or local regression that loads `source_model_unscored.json` and `source_model_scored.json` and asserts terminalization. Do not make the main test suite depend on build diagnostics existing; keep normal pytest coverage synthetic and deterministic.

## Verification Commands

Run focused tests:

```bash
cd /Users/mike/code/melee
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k 'draw_adapted_structural_guard or rejected_structural_guard_blocks_terminal_proof'
python -m pytest tools/melee-agent/tests/test_allocator_ceiling.py -k 'draw_adapted_source_model_terminal_proof or draw_meta_ceiling_preserves_expression_source_class'
python -m pytest tools/melee-agent/tests/test_retained_frontier_triage.py -k 'source_model_terminal_proof or draw'
```

Run the broader mwcc-debug regression slice:

```bash
cd /Users/mike/code/melee
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py tools/melee-agent/tests/test_retained_frontier_triage.py tools/melee-agent/tests/test_allocator_ceiling.py
```

If code changes touch CLI output or help text, also run:

```bash
cd /Users/mike/code/melee
python -m pytest tools/melee-agent/tests/test_mwcc_debug_docs_cli_reorg.py tools/melee-agent/tests/test_capabilities.py
```

## Expected Outcome

The same scored Draw adapted expression-lifetime artifact that currently returns `score-rows-not-terminal-safe` should instead return a retained-frontier-consumable terminal proof. It should keep the joined `target_score` evidence, record structural guard rejection as the terminal blocker, preserve adapted expression-lifetime dimensions/provenance, and flow through retained-frontiers into allocator-ceiling as a practical current-source-shape ceiling.
