# Fix Plan: Issue #1030 source-family continuation must trust real recombine scores

## Issue

`debug search source-family-continuation` can report Sort semantic recombine rows as actionable 2/2 using an estimated `target_score`, even when a real `debug search combine` artifact for the same parent pair has already scored the materialized recombine and shown that it does not jointly preserve IG34->r27 and IG44->r25.

The concrete failure reproduces with:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-family-continuation \
  --source-model-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1029_rerun/source_model_cross_tu_symbol_linkage/sort_source_model_cross_tu_symbol_linkage_scored.json \
  --artifact /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1029_rerun/cross_tu_onehit_recombine_original_ids/sort_cross_tu_onehit_recombine_original_ids.json \
  --function mnDiagram_SortNamesByKOs \
  --json
```

Current observed behavior from `/Users/mike/code/melee`:

- `status=actionable`, `terminal=false`
- `continuation.route=sort-semantic-dual-target-recombine`
- `real_score_authority` is absent
- `continuation_artifacts` contains `["sort-semantic-dual-target-recombine", "artifact"]`
- the real combine artifact is treated as `unrecognized-continuation-artifact`
- `semantic_recombine.status=actionable`
- estimated candidates such as `post-meta-sort-semantic-recombine-f32343df6df2` remain `accepted=true`, `target_matched=2`, `target_score.estimated=true`, and have no `source_retained`

The referenced real combine artifact has top-level `combinations` only, not `protected_structural_synthesis`. Its scored rows disprove the estimated 2/2 recombines:

- `name-total-locals + max-text-copy`: real `target_score.matched=0/2`, IG34 absent, IG44=r3
- `name-total-locals + byte-cache`: real `target_score.matched=1/2`, only IG44->r25
- `name-total-locals + cached-text-inputs`: real `target_score.matched=1/2`, only IG44->r25
- remaining pairs are skipped for overlapping source hunks

## Root Cause

The source-family continuation path already has a partial real-score override, but it only handles two artifact shapes.

Primary files reviewed:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
- `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/search/test_cli_smoke.py`

Specific root cause:

1. `build_source_family_continuation_payload()` builds estimated Sort semantic recombine candidates from one-hit source-model rows via `_sort_semantic_recombine_summary()`.
2. `_sort_semantic_recombine_candidate()` marks non-overlapping estimates as `accepted=true` and creates an estimated `target_score` with `matched=2`, `estimated=true`, and `structural_guard.estimated=true`.
3. `_apply_sort_recombine_real_score_authority()` is supposed to replace or supersede those estimates with real evidence.
4. `_continuation_artifact_summary()` only calls `_combine_continuation_summary()` when the artifact has `protected_structural_synthesis`.
5. The #1030 real artifact is a normal raw `debug search combine` JSON with top-level `combinations` and no `protected_structural_synthesis`, so `_continuation_artifact_summary()` returns `kind="artifact"`, `status="unrecognized"`.
6. `_real_combine_candidate_indexes()` only indexes summaries with `kind in {"protected-structural-synthesis", "score-source"}`. Therefore the real top-level `combinations` rows are never correlated by candidate id or parent pair.
7. Because real rows are invisible to source-family continuation, the estimated candidates remain accepted and get promoted into retained-frontier/allocator handoff as source-actionable despite having no retained source and despite real scoring disproving them.

Retained-frontier triage already has a separate cross-TU raw combine negative-evidence path in `retained_frontier_triage.py` (`_is_sort_cross_tu_recombine_artifact()`, `_sort_cross_tu_recombine_summary()`, `_sort_cross_tu_recombine_frontier()`). That is why retained-frontier can later say all known frontiers are exhausted while the continuation artifact still says actionable. The fix should align source-family continuation with the same real raw-combine evidence, not add a final-output filter.

## Intended Fix

### 1. Normalize raw `debug search combine` artifacts in source-family continuation

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add a raw-combine detector and summary path near `_continuation_artifact_summary()`:

- Add `_is_raw_search_combine_artifact(artifact)`:
  - returns true when `artifact["combinations"]` is a non-empty list and rows contain `parents` or `candidate_id`/`status`
  - should not require `protected_structural_synthesis`
  - should be conservative enough not to classify unrelated artifacts with a random `combinations` key

- In `_continuation_artifact_summary()`:
  - keep the existing `protected_structural_synthesis` branch first
  - then add:
    ```python
    if _is_raw_search_combine_artifact(artifact):
        return _raw_combine_continuation_summary(artifact, context=context)
    ```

- Add `_raw_combine_continuation_summary(artifact, *, context)`:
  - reuse `_combine_raw_combination_indexes()`, `_combine_candidate_details_by_id()`, `_matching_combine_raw_row()`, and `_combine_candidate_summary()`
  - build `ranked_candidates` from top-level `combinations` with `status == "ok"`
  - preserve real fields from each combination: `target_score`, `structural_guard`, `path`/`source_retained`, `pcdump_path`, `parents`, `applied_hunks`, `score_result.parsed_json`
  - include skipped pairs from `status == "skipped"`
  - emit a stable summary shape:
    ```python
    {
      "kind": "search-combine",
      "status": "terminal" | "actionable" | "blocked",
      "ranked_candidates": ...,
      "terminal_blockers": ...,
      "score_coverage": {
        "ok_combinations": ...,
        "skipped_combinations": ...,
        "evaluable_combinations": ...,
        "joint_preserving_combinations": ...
      },
      "skipped_pairs": ...,
    }
    ```
  - synthesize terminal blockers when real scoring disproves the estimated route:
    - `one-hit-recombine-protected-targets-not-jointly-preserved` when no scored ok row preserves all protected targets
    - `recombine-overlapping-source-hunks` when skipped rows contain overlap reasons
    - include candidate blockers from `_continuation_candidate_blockers()` such as `structural-guard-not-accepted` and `protected-targets-not-jointly-preserved`
  - do not require `--protect-assignment` summaries; use `target_score.virtuals` and `context.force_phys` as the authoritative protected target map

### 2. Let real raw-combine summaries supersede semantic estimates

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Update `_apply_sort_recombine_real_score_authority()` and `_real_combine_candidate_indexes()`:

- Introduce a small helper or constant for real combine summary kinds:
  ```python
  _REAL_COMBINE_SUMMARY_KINDS = {"protected-structural-synthesis", "search-combine"}
  ```

- In `_apply_sort_recombine_real_score_authority()`:
  - call `_inherit_sort_recombine_source_context()` for `search-combine` as well as `protected-structural-synthesis`
  - index raw combine candidates via `_real_combine_candidate_indexes()`

- In `_real_combine_candidate_indexes()`:
  - include `kind == "search-combine"`
  - continue to include `score-source`
  - continue excluding `SORT_SEMANTIC_PROTECTED_LOSS_REPAIR_DIMENSION` for protected-loss repair rows
  - index by:
    - candidate aliases from `_sort_recombine_candidate_identity_aliases()`
    - parent pair keys from `_sort_recombine_candidate_pair_keys()`

This is enough for #1030 because the source-model rows and combine rows share original parent ids such as:

- `post-meta-source-family-sort-init-indexed-write-name-total-locals`
- `post-meta-source-family-sort-call-return-copy-local-max-text-copy`
- `post-meta-source-family-sort-indexed-byte-cache-byte-cache`
- `post-meta-source-family-sort-indexed-byte-cache-cached-text-inputs`

### 3. Require real scored evidence before accepting Sort semantic 2/2 recombines

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Do not leave estimated Sort semantic recombine rows accepted after continuation processing unless there is real scored evidence for that candidate.

Orchestrator review amendment: this is an intentional behavior change required
by the issue governance. Estimated semantic recombine rows may still be emitted
as auditable proposals, but they must not be counted as accepted retained-source
continuations. When no real combine artifact was supplied, the command should
surface a blocked/needs-real-score state with `no-scored-recombine-evidence`
rather than a terminal real-score-negative state. When a real combine artifact
was supplied, same-parent real negatives supersede estimates and missing same
candidate real rows are suppressed as unscored under the real combine attempt.

Implementation detail:

- Track whether any real semantic recombine evidence was supplied:
  - `real_by_id` or `real_by_pair` is non-empty
  - or a `search-combine` summary exists with ok/skipped combinations

- For each `SORT_SEMANTIC_RECOMBINE_DIMENSION` candidate:
  - if a matching real candidate preserves all protected targets and has structural guard accepted, call `_apply_real_combine_score()` and keep it accepted only if it has a retained source route (`source_retained`, `path`, `source_hunks`, or `source_route`)
  - if a matching real candidate does not preserve all targets, call `_supersede_estimated_sort_recombine()`
  - if real combine evidence was supplied but this estimated candidate has no matching real row, mark it not accepted with:
    - `recommendation="reject"` or `recommendation="score-required"`
    - blocker `no-scored-recombine-evidence`
    - `structural_guard.accepted=false`
    - `structural_guard.status="real-score-required"`
  - if no real combine evidence was supplied, estimated 2/2 rows should not be counted as accepted source-actionable hits. They may remain as candidate proposals, but they must carry `no-scored-recombine-evidence` and must not drive top-level `status=actionable`.

After this pass:

- `semantic_recombine.status` should be:
  - `actionable` only when at least one candidate has real scored `target_score`, real retained source evidence, and all protected targets preserved
  - `terminal` when real combine evidence was supplied and all candidates are real-negative, skipped, or unscored under a terminal combine summary
  - `blocked`/needs evidence when only estimated candidates exist and no real score artifact was supplied

- `target_score_estimate` can remain for auditability, but accepted candidates must use real `target_score`.
- `target_score.estimated=true` must never be the score behind an accepted 2/2 continuation candidate.
- `source_retained` should be present on any accepted source-actionable semantic recombine candidate.

### 4. Publish terminal real-score-negative evidence into continuation payload

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

When real raw combine evidence disproves all estimated semantic recombines:

- top-level payload should become:
  - `status="terminal"`
  - `terminal=true`
  - `continuation=None`
  - `real_score_authority="semantic-recombine-real-score"`
  - `suppressed_estimated_candidate_ids=[...]`
  - `terminal_blockers` includes:
    - `real-score-protected-loss`
    - `one-hit-recombine-protected-targets-not-jointly-preserved`
    - `recombine-overlapping-source-hunks` when applicable
    - `no-scored-recombine-evidence` for estimated candidates with no real row

- nested `source_model_proof.source_family_synthesis` should carry the same semantic recombine terminal evidence so retained-frontier triage and allocator ceiling see the same terminal state.

- `target_hits` and `protected_hits` must be derived from the best real scored candidate, not an estimated candidate.

This fixes the inconsistent handoff: retained-frontier/allocator should no longer see an actionable estimated semantic recombine frontier when real recombine rows have already disproved it.

### 5. Keep retained-frontier triage behavior, but add guard coverage

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`

No large production change should be necessary there. Existing logic already:

- promotes actionable semantic recombine lanes only from `semantic_recombine.status == "actionable"`
- closes estimated/stale continuations when a concrete protected-loss terminal exists
- has a raw cross-TU recombine terminal path

Only adjust retained-frontier code if tests reveal that terminal continuation payloads with `real_score_authority="semantic-recombine-real-score"` are not suppressing estimated semantic lanes. If needed, extend `_frontier_estimated_or_stale_continuation()` or `_frontier_concrete_protected_loss_terminal()` to treat semantic-recombine real-score terminal evidence as suppressing estimated semantic recombine continuations, not just protected-loss-negative evidence.

## Regression Tests

### `tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add tests around `build_source_family_continuation_payload()`.

1. `test_sort_raw_combine_scores_supersede_estimated_semantic_recombine_original_ids`

Fixture shape:

- classified/source-model rows include:
  - `post-meta-source-family-sort-init-indexed-write-name-total-locals` hitting only IG34->r27
  - `post-meta-source-family-sort-call-return-copy-local-max-text-copy` hitting only IG44->r25
  - `post-meta-source-family-sort-indexed-byte-cache-byte-cache` hitting only IG44->r25
  - `post-meta-source-family-sort-indexed-byte-cache-cached-text-inputs` hitting only IG44->r25
  - optionally `post-meta-source-family-sort-call-return-copy-local-j-text-copy` to verify unscored estimates are not accepted
- raw combine artifact has no `protected_structural_synthesis`
- top-level `combinations` mirror #1030:
  - max-text-copy real score 0/2
  - byte-cache real score 1/2
  - cached-text-inputs real score 1/2
  - overlap skipped rows

Assertions:

- no `unrecognized-continuation-artifact` blocker
- `continuation_artifacts` includes `kind="search-combine"`
- `payload["status"] == "terminal"`
- `payload["terminal"] is True`
- `payload["continuation"] is None`
- `payload["real_score_authority"] == "semantic-recombine-real-score"`
- `semantic_recombine.status == "terminal"`
- no semantic recombine candidate remains accepted with `target_score.estimated=true`
- scored candidates have `real_score_superseded_by`
- unscored estimated candidates carry `no-scored-recombine-evidence` and are not accepted
- terminal blockers include real-score negative evidence

Why it prevents recurrence:

This is the exact artifact-shape bug: raw top-level combine rows must supersede estimated semantic recombines even without a `protected_structural_synthesis` section.

2. `test_sort_raw_combine_joint_hit_keeps_semantic_recombine_actionable_with_retained_source`

Fixture shape:

- same source-model rows
- raw combine artifact with one top-level ok combination whose real `target_score` has IG34->r27 and IG44->r25, `structural_guard.accepted=true`, and `path`/`continuation.source_retained`

Assertions:

- `payload["status"] == "actionable"`
- `payload["continuation"]["route"] == "sort-semantic-dual-target-recombine"`
- accepted candidate has `source_retained`
- accepted candidate has real `target_score`, not estimated
- `target_score_estimate` is retained only as an audit field

Why it prevents recurrence:

It preserves the positive path required by governance: source-family continuation can still report actionable 2/2, but only from real scored retained source evidence.

3. Update existing estimated-only tests

Existing test to revisit:

- `test_sort_semantic_nonoverlapping_continuation_is_actionable`

Change it so estimated-only semantic recombine rows are not considered final source-actionable 2/2. Expected result should become either:

- blocked/needs-real-score evidence with `no-scored-recombine-evidence`, or
- an actionable "score this recombine" proposal that does not set `accepted=true`, does not set `target_hits/protected_hits` as all true, and does not use `continuation.route=sort-semantic-dual-target-recombine` as a retained source handoff.

The exact expected status should match the implementation choice, but the invariant must be explicit: estimated `target_score` cannot be the basis for accepted 2/2.

### `tools/melee-agent/tests/test_retained_frontier_triage.py`

Add or extend a retained-frontier handoff test:

1. `test_retained_frontiers_raw_combine_real_negative_closes_estimated_semantic_recombine`

Fixture:

- write a continuation payload produced by the new raw-combine-negative test
- include a stale/estimated semantic recombine frontier if needed to model the current inconsistent handoff

Assertions:

- `triage_retained_frontiers()` returns no actionable semantic recombine frontier
- status is `all-known-frontiers-exhausted` when no other frontier remains
- meta ceiling terminal proof includes real recombine negative evidence
- allocator classification does not suggest "retained-frontier source hunk" for semantic recombine

Why it prevents recurrence:

It verifies the downstream handoff semantics, not just the source-family continuation JSON.

### `tools/melee-agent/tests/search/test_cli_smoke.py`

Add a CLI smoke for the command path:

- create temp source-model JSON and raw combine JSON with top-level `combinations`
- invoke `search_app` command `source-family-continuation`
- assert JSON output has no `unrecognized-continuation-artifact`, is terminal for the negative case, and suppresses estimated accepted semantic recombine rows

Why it prevents recurrence:

The bug is command/artifact-shape dependent. A direct builder test is necessary but not sufficient.

## Smoke Checks After Implementation

Run targeted tests:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  -k "semantic_recombine or source_family_continuation" -q
```

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_retained_frontier_triage.py \
  -k "semantic_recombine or cross_tu_recombine or real_negative" -q
```

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  -k "source_family_continuation or search_combine" -q
```

Compile touched modules:

```bash
PYTHONPATH=tools/melee-agent python -m compileall -q \
  tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py \
  tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py \
  tools/melee-agent/src/search/cli/__init__.py
```

Run the real #1030 artifact smoke:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-family-continuation \
  --source-model-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1029_rerun/source_model_cross_tu_symbol_linkage/sort_source_model_cross_tu_symbol_linkage_scored.json \
  --artifact /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1029_rerun/cross_tu_onehit_recombine_original_ids/sort_cross_tu_onehit_recombine_original_ids.json \
  --function mnDiagram_SortNamesByKOs \
  --json > /tmp/issue1030-source-family-continuation-fixed.json
```

Then verify:

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path("/tmp/issue1030-source-family-continuation-fixed.json")
payload = json.loads(p.read_text())
semantic = payload.get("semantic_recombine") or {}
accepted_estimates = [
    row for row in semantic.get("ranked_candidates", [])
    if row.get("accepted") is True
    and isinstance(row.get("target_score"), dict)
    and row["target_score"].get("estimated") is True
]
assert payload["status"] == "terminal", payload["status"]
assert payload.get("terminal") is True
assert payload.get("continuation") is None
assert payload.get("real_score_authority") == "semantic-recombine-real-score"
assert not accepted_estimates
assert "unrecognized-continuation-artifact" not in payload.get("terminal_blockers", [])
assert any(
    row.get("real_score_superseded_by")
    for row in semantic.get("ranked_candidates", [])
)
print("issue1030 smoke passed")
PY
```

Optionally run retained-frontier/allocator on the fixed continuation artifact plus the real source-model/recombine artifacts and assert no semantic recombine retained frontier remains actionable.

## Acceptance Criteria

- Source-family continuation no longer reports estimated Sort semantic recombine 2/2 candidates as accepted source-actionable hits.
- Raw `debug search combine` artifacts with top-level `combinations` are recognized and consumed even without `protected_structural_synthesis`.
- Real combine score rows supersede same-parent estimated semantic recombines by candidate id or parent pair.
- A real 0/2 or 1/2 recombine result terminalizes the semantic recombine route instead of leaving `target_score.estimated=true` rows actionable.
- A real 2/2 recombine result remains actionable only when it carries retained source evidence and real `target_score`.
- Retained-frontier and allocator handoff no longer disagree with source-family continuation for #1030.
