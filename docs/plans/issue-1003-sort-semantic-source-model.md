# Fix #1003: Sort Semantic Algorithm-Shape Source-Model Synthesis

## Context

Issue #1003 is a follow-up to #1001 for `mnDiagram_SortNamesByKOs`. The current
`debug search source-model-synthesis` lane generates and scores the retained
Sort source-family probes plus the bounded natural rewrite set, then correctly
terminalizes when those generated candidates do not produce the dual
`IG34->r27` and `IG44->r25` result.

The issue artifacts named in #1003 were not present in this checkout under
`/Users/mike/code/melee/build/diagnostics/mndiagram_1000_1001_rerun/`, so this
plan is based on the current source, tests, #991/#1001 plans, and the described
score facts.

Relevant implementation today:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
- `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_allocator_ceiling.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_capabilities.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/golden/debug_cli_help/debug__search__source-model-synthesis.txt`

## Root Cause

`post_meta_source_family_synthesis.py` has two Sort synthesis layers:

1. Older retained local patchers from `_candidate_patcher_specs()`:
   `sort-init-indexed-write`, `sort-indexed-byte-cache`,
   `sort-call-return-copy-local`, and `sort-swap-slot-lvalue`.
2. The #1001 bounded natural rewrite patchers from
   `_sort_natural_rewrite_patcher_specs()`:
   `sort-natural-init-selection-coupling`, `sort-natural-selection-state`,
   `sort-natural-selected-emission`, and `sort-natural-region-combination`.

The #1001 terminal next model now says the missing lane is an unmodeled semantic
sort algorithm shape outside the bounded natural rewrite generator:

`Sort natural-region rewrite synthesis exhausted bounded initialization, selection-state, comparison, and selected-emission rewrites; the next unsupported source model is an unmodeled semantic sort algorithm shape outside the bounded natural rewrite generator.`

But `generate_source_family_candidates()` only calls:

- `_candidate_patcher_specs(context.function)`
- `_sort_natural_rewrite_source_candidates(...)`
- `_draw_expression_lifetime_source_candidates(...)`

There is no third Sort generator for broader semantic algorithm shapes. The
existing natural patchers are local source replacements that preserve the same
selection-sort skeleton: initialize names/totals, outer `i`, inner `j`, update
`max_idx`, then shift selected value into `dst[i]`. That explains the observed
plateau:

- `post-meta-source-family-sort-init-indexed-write-name-total-locals` gets
  `IG34->r27` but misses `IG44` as `r31`.
- `post-meta-sort-natural-rewrite-sort-natural-selection-state-split-guard-total-state`
  gets `IG44->r25` but misses `IG34` as `r22`.
- Initialization/selection coupling and selected-emission variants are too
  narrow to change ownership across the whole algorithm.

Allocator-ceiling and retained-frontier aggregation are doing the right thing:
they report the next unsupported model. The feature gap is candidate synthesis.

## Design

Add a new gated semantic Sort lane in
`post_meta_source_family_synthesis.py`, not in allocator-ceiling.

### 1. Add Semantic Sort Constants and Profile Coverage

Add:

- `SORT_SEMANTIC_ALGORITHM_DIMENSIONS`
- `SORT_SEMANTIC_ALGORITHM_EXHAUSTED_NEXT_MODEL`

Suggested dimensions:

- `sort-semantic-loop-ownership`
- `sort-semantic-selection-condition-staging`
- `sort-semantic-selected-name-extraction`
- `sort-semantic-shift-emission-loop`
- `sort-semantic-max-idx-lifetime`
- `sort-semantic-text-total-cache-boundary`
- `sort-semantic-array-pointer-ownership`
- `sort-semantic-region-combination`

Append these dimensions to the Sort profile's `dimensions` tuple after
`SORT_NATURAL_REWRITE_DIMENSIONS`.

Update the Sort profile summary only enough to say the generator now covers
retained, natural-region, and semantic algorithm-shape variants. Keep the
existing proof kind and retained-frontiers-compatible family IDs unchanged.

### 2. Gate Only on the #1003 Next-Unsupported Model

Add `_should_generate_sort_semantic_algorithm_shapes(context)`.

Return true when:

- `context.function == SORT_FUNCTION`, and
- `next_unsupported_source_model` or `current_ceiling.next_unsupported_source_model`
  contains semantic evidence such as:
  - `semantic sort algorithm shape`
  - `unmodeled semantic sort algorithm shape`
  - `outside the bounded natural rewrite generator`

Also allow a fallback evidence gate only when the current ceiling contains every
`SORT_NATURAL_REWRITE_DIMENSIONS` value and a terminal source-model proof marker.
Do not trigger on the older `broader natural C sort rewrite` text; that belongs
to the #1001 lane.

### 3. Generate Source-Actionable Semantic Candidates

Add `_sort_semantic_algorithm_patcher_specs()` and
`_sort_semantic_algorithm_source_candidates(...)`, modeled after
`_sort_natural_rewrite_source_candidates(...)`.

Use the existing `SourceFamilyCandidate` contract:

- `candidate_id`
- `dimension_id`
- `equivalence_class`
- `variant_id`
- `strategy`
- `rationale`
- `expected_effect`
- `source_hunks`
- `source_components`
- `validation_metadata`
- `target_assignments`

Set metadata:

- `semantic_algorithm_shape: True`
- `natural_rewrite: True` only if downstream consumers currently key on this
  for score-source routing; otherwise prefer the new semantic flag.
- `requires_target_score_validation: True`
- `score_function: context.source_function or context.function`
- `source_components`
- `score_source_command_hint`

Candidate IDs should be stable and grep-friendly, for example:

- `post-meta-sort-semantic-loop-ownership-inner-owned-best`
- `post-meta-sort-semantic-loop-ownership-prefix-insertion`
- `post-meta-sort-semantic-condition-staged-visible-j`
- `post-meta-sort-semantic-condition-staged-totals-first`
- `post-meta-sort-semantic-selected-name-before-inner`
- `post-meta-sort-semantic-selected-name-after-inner`
- `post-meta-sort-semantic-shift-counted-for`
- `post-meta-sort-semantic-shift-pointer-walk`
- `post-meta-sort-semantic-max-idx-reset-after-emit`
- `post-meta-sort-semantic-max-idx-consumed-as-shift-cursor`
- `post-meta-sort-semantic-cache-text-across-inner`
- `post-meta-sort-semantic-cache-total-and-text`
- `post-meta-sort-semantic-owner-dst-local-only`
- `post-meta-sort-semantic-owner-assets-local-only`
- a small bounded set of combinations that pair one condition-staging variant
  with one shift/emission or selected-name timing variant.

Keep the default `--max-per-dimension` limit effective. The issue asks for the
next bounded semantic lane, not an unbounded permuter.

### 4. Prefer Whole-Function Semantic Rewrites Over Micro-Probes

The new patchers should replace larger coherent regions in
`mnDiagram_8023FC28`, not individual expression snippets. Treat each candidate
as a natural C algorithm shape:

- Alternate outer/inner loop ownership:
  - keep outer `i` but make the selected name/score state owned by the outer
    loop rather than only by the comparison expression.
  - test a prefix-insertion form where the inner loop scans and records a
    selected name value, then emission consumes that value.
- Selection condition staging:
  - stage `j_name`, `j_text`, `j_total`, `max_name`, `max_text`, and
    `max_total` in explicit blocks before the condition.
  - include a variant that tests visibility before totals, and one that
    computes totals before visibility.
- Selected-name extraction timing:
  - extract selected byte immediately after the inner scan.
  - extract selected byte before entering the inner scan and update it when
    `max_idx` changes.
- Shift/emission loop structure:
  - counted backward `for` loop.
  - pointer walk that preserves a separate `insert` cursor.
  - consume `max_idx` as the shift cursor versus preserve it and use a
    `move_idx` local.
- `max_idx` lifetime reset/consumption:
  - preserve `max_idx` until after `dst[i] = selected_name`.
  - consume it during shifting and write with a separate `insert_idx`.
- Totals/name text caching across loop boundaries:
  - carry `best_name`, `best_total`, and `best_text` across the inner loop.
  - carry only `best_name` and reload text/total at comparison sites.
- Array/pointer ownership:
  - use `dst` consistently for sorted names.
  - use `assets->sorted_names` consistently.
  - use `mnDiagram_804A076C.sorted_names` only for comparison reads where the
    current retained source does.

Implementation detail: use targeted text patchers initially, as the current
module does, but factor the shared full-region replacement into helpers so
future AST or transform-corpus adapters can feed the same candidate builder.

### 5. Deduping and Structural Guard Handling

Reuse the existing source hash and normalized hunk signature dedupe. Semantic
variants can easily collapse to the same source after patching; duplicate
source should not inflate terminal proof.

Update `_can_terminalize_structural_guard_exhaustion()` so Sort structural
guard terminalization is allowed for either:

- rows in `SORT_NATURAL_REWRITE_DIMENSIONS`, or
- rows in `SORT_SEMANTIC_ALGORITHM_DIMENSIONS`.

Keep all existing safety requirements:

- no score errors
- no unjoined score rows
- no metadata mismatches
- all generated candidates scored
- blockers are only `structural-guard-not-accepted`

### 6. Terminal Proof for Exhausted Semantic Lane

Update `_terminal_next_unsupported_source_model(...)` so:

- if semantic dimensions were attempted and exhausted, the next unsupported
  model becomes `SORT_SEMANTIC_ALGORITHM_EXHAUSTED_NEXT_MODEL`, for example:
  `Sort semantic algorithm-shape synthesis exhausted bounded loop ownership, selection condition staging, selected-name extraction timing, shift/emission loop structure, max_idx lifetime, text/total cache-boundary, and array/pointer ownership variants without improving the IG34->r27 plus IG44->r25 dual-target state.`
- if only natural dimensions were attempted, keep the current #1001 next model.

Make sure the terminal proof retains:

- `post_ceiling_source_family_discovery.retained_scored_probes`
- `source_model_proof.source_family_synthesis.retained_scored_probes`
- `target_score`
- `structural_guard`
- `source_components`
- `source_hunks_by_candidate`
- `transform_corpus_adapter_outcomes`

### 7. CLI Behavior

No new CLI command is needed. Continue using:

```bash
melee-agent debug search source-model-synthesis \
  -f mnDiagram_SortNamesByKOs \
  --meta-ceiling-json <semantic-next-model-or-retained-frontiers-json> \
  --source-file src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/source-model-synthesis/sort-semantic \
  --target <target-json> \
  --score \
  --json
```

Only add a CLI option if candidate volume needs explicit control beyond the
existing `--max-per-dimension`. If added, prefer:

- `--semantic-sort/--no-semantic-sort`, default auto-gated

If that option is added, update help golden files and capability text.

## Regression Tests

Add or update tests in
`/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`.

### New Constants

Add:

```python
SEMANTIC_SORT_DIMENSIONS = {
    "sort-semantic-loop-ownership",
    "sort-semantic-selection-condition-staging",
    "sort-semantic-selected-name-extraction",
    "sort-semantic-shift-emission-loop",
    "sort-semantic-max-idx-lifetime",
    "sort-semantic-text-total-cache-boundary",
    "sort-semantic-array-pointer-ownership",
    "sort-semantic-region-combination",
}
```

### `test_sort_semantic_algorithm_shapes_are_gated_by_semantic_next_model`

Use `_sort_context_without_broad_natural_evidence()` or a new helper that
contains natural dimensions as already exhausted but no semantic next-model
text.

Assert:

- no `sort-semantic-*` candidates are generated without semantic next-model
  evidence.
- replacing `next_unsupported_source_model` with the #1003 text generates
  `SEMANTIC_SORT_DIMENSIONS`.
- `NATURAL_SORT_DIMENSIONS` still use the older gate and are not required for
  a direct semantic-next-model payload.

### `test_sort_semantic_algorithm_shapes_generate_source_actionable_components`

Generate with `_sort_source()`, semantic context, `max_per_dimension=4`,
`include_source=True`.

Assert:

- candidate IDs include at least:
  - `post-meta-sort-semantic-loop-ownership-inner-owned-best`
  - `post-meta-sort-semantic-condition-staged-visible-j`
  - `post-meta-sort-semantic-shift-counted-for`
  - one `post-meta-sort-semantic-region-combination-*`
- every semantic row has non-empty `source_hunks`.
- every semantic row has `target_assignments == ["IG34->r27", "IG44->r25"]`.
- every semantic row has `validation_metadata["semantic_algorithm_shape"] is True`.
- every semantic row has `validation_metadata["score_function"] == SORT_SOURCE_FUNCTION`.
- every semantic row has `source_components` and those components are copied
  into `validation_metadata["source_components"]`.
- generated source still contains `void mnDiagram_8023FC28(void)`.

### `test_sort_semantic_candidates_are_deduped_and_limited_per_dimension`

Generate with `max_per_dimension=1`.

Assert:

- each `sort-semantic-*` dimension has at most one candidate.
- candidate IDs are unique.
- normalized hunk signatures are unique for semantic rows.

### `test_sort_semantic_score_rows_rank_dual_target_progress`

Write candidates with `write_source_family_candidates`.

Build synthetic scores with `_score(row)` and one semantic candidate scored as
`actual34=27, actual44=25`.

Assert:

- `classify_source_family_scores(...)["status"] == "actionable"`.
- `best_candidate["candidate_id"]` is that semantic candidate.
- `best_candidate["target_matched"] == 2`.
- `best_candidate["target_score"]["virtuals"]["34"]["matched"] is True`.
- `best_candidate["target_score"]["virtuals"]["44"]["matched"] is True`.

### `test_sort_semantic_structural_rejections_terminalize_with_blockers`

Use only semantic candidates or all candidates from a semantic context.

Score all generated semantic rows with `_score(row, accepted=False)`.

Assert:

- status is `terminal`, not `blocked`.
- blockers include only `structural-guard-not-accepted`.
- exhausted dimensions include `SEMANTIC_SORT_DIMENSIONS`.
- terminal `next_unsupported_source_model` is the new semantic-exhausted text,
  not the #1001 natural-rewrite text.
- retained scored probes include `target_score`, `structural_guard`, and
  `source_components`.

### `test_sort_semantic_terminal_proof_triage_consumable`

Persist the terminal payload from the previous test to `tmp_path`.

Run:

```python
triage_retained_frontiers(
    repo_root=tmp_path,
    functions=[SORT_FUNCTION],
    artifacts=[artifact],
)
```

Assert:

- triage status is `all-known-frontiers-exhausted`.
- a terminal frontier with `family_id == "post-ceiling-source-model-proof"`
  exists.
- `frontier["source_model_proof"]["source_family_synthesis"]["status"] == "synthesis-exhausted"`.
- `attempted_targets == {"34": 27, "44": 25}`.
- `retained_scored_probes` includes semantic candidates.

### `test_sort_semantic_source_components_survive_terminal_outputs`

Mirror existing `test_sort_natural_source_components_survive_terminal_outputs`
but select a `sort-semantic-*` row.

Assert source components survive:

- raw candidate
- `_score_row`
- `_compact_score_row`
- terminal `retained_scored_probes`
- terminal `source_hunks_by_candidate`

## Allocator-Ceiling Tests

Update
`/Users/mike/code/melee/tools/melee-agent/tests/test_allocator_ceiling.py`
only if allocator-ceiling text or classification needs to distinguish the new
semantic-exhausted next model. Add:

### `test_allocator_ceiling_retained_frontiers_lists_sort_semantic_exhausted_model`

Create a retained-frontiers-compatible source-model proof with:

- `function: mnDiagram_SortNamesByKOs`
- semantic exhausted dimensions
- `next_unsupported_source_model` equal to
  `SORT_SEMANTIC_ALGORITHM_EXHAUSTED_NEXT_MODEL`

Assert `classify_allocator_ceiling(...)` preserves that text in the current
ceiling and rendered text. If existing allocator-ceiling pass-through already
handles this generically, this test can be skipped.

## CLI and Capability Tests

Only needed if a new CLI option is added.

Update:

- `/Users/mike/code/melee/tools/melee-agent/tests/golden/debug_cli_help/debug__search__source-model-synthesis.txt`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_capabilities.py`

Add or adjust assertions so `debug search source-model-synthesis` documents the
semantic Sort lane or `--semantic-sort/--no-semantic-sort`.

If no CLI option is added, keep these files unchanged.

## Verification Commands

Focused unit tests:

```bash
PYTHONPATH=tools/melee-agent pytest --no-cov \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  -q
```

If allocator-ceiling text/classification changes:

```bash
PYTHONPATH=tools/melee-agent pytest --no-cov \
  tools/melee-agent/tests/test_allocator_ceiling.py \
  -q
```

If CLI help/capability changes:

```bash
PYTHONPATH=tools/melee-agent pytest --no-cov \
  tools/melee-agent/tests/test_capabilities.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  -q
```

Static sanity:

```bash
python -m py_compile \
  tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py \
  tools/melee-agent/src/search/cli/__init__.py \
  tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py
```

Live smoke once a #1003-like input artifact is available:

```bash
melee-agent debug search source-model-synthesis \
  -f mnDiagram_SortNamesByKOs \
  --meta-ceiling-json build/diagnostics/mndiagram_1000_1001_rerun/retained_frontiers/sort_allocator_ceiling_after_1001.json \
  --retained-frontiers-json build/diagnostics/mndiagram_1000_1001_rerun/retained_frontiers/sort_frontiers_after_1001.json \
  --source-file src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/mndiagram_1003/source_model/sort_semantic \
  --target <target-json> \
  --score \
  --json > build/diagnostics/mndiagram_1003/source_model/sort_semantic_scored.json
```

Expected live-smoke outcomes:

- all generated semantic candidates join to score rows, or status is
  `incomplete` with explicit missing candidate IDs.
- actionable if any candidate improves the dual target state.
- terminal only when all generated semantic variants are scored, no score
  errors exist, no unjoined rows exist, and no retained candidate improves
  `IG34->r27` plus `IG44->r25`.

## Non-Goals

- Do not change allocator-ceiling to generate candidates.
- Do not special-case score facts from the missing issue artifacts.
- Do not weaken terminalization safety to hide score-source errors or missing
  candidate joins.
- Do not add unbounded permutation or random search under
  `source-model-synthesis`.
- Do not edit `src/melee/mn/mndiagram.c` as part of this tooling fix.
