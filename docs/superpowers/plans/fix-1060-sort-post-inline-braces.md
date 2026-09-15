# Fix #1060: Sort post-inline selection/emission probes emit invalid braces

## Scope

Plan only. Do not change production or test files until this plan is reviewed.

Issue #1060 reports that `source-model-synthesis` generated four
`mnDiagram_SortNamesByKOs` post-inline-boundary selection/emission probes with
`brace_balance=-1`. The malformed files live under:

- `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1058_1059_rerun/sort_post_inline_selection_emission/probes/`
- `source_model_sort_post_inline_selection_noscore.json`
- `source_model_sort_post_inline_selection_scored.json`
- `manual_fixed_helper_emission_cursor_owner_score.json`

The implementation target is `/Users/mike/code/melee`, primarily:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Working tree note from plan-time inspection: `/Users/mike/code/melee` already
had uncommitted edits in those two files while this plan was being written. The
observed production diff changes `_SORT_POST_INLINE_SELECTION_LOOP_RE` so the
captured suffix starts at `if (max_idx != i) {`, and the observed test diff adds
brace-balance assertions to
`test_sort_post_inline_boundary_continuation_generates_selection_emission_only`.
Review and keep or adjust those existing edits during implementation; do not
blindly duplicate them.

## Audit Notes

Capability audit:

```bash
melee-agent capabilities search source-model-synthesis
```

Relevant existing capabilities found:

- `debug search source-model-synthesis`
- `debug target score-source`

No existing repair tool specifically fixes malformed generated retained source.

Issue state:

```bash
melee-agent issue show 1060
```

The issue is already claimed by `codex-fd86-issue-resolver`, so the
implementation should keep that ownership rather than stealing/reclaiming it.

## Root Cause

The malformed brace is emitted by the Sort post-inline selection/emission
patcher in:

```text
/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py
```

Key functions/constants:

- `_sort_post_inline_boundary_selection_emission_source_shape_candidates`
- `_post_inline_boundary_selection_emission_patcher`
- `_post_inline_boundary_selection_emission_loop_block`
- `_SORT_POST_INLINE_SELECTION_LOOP_RE`

The regex `_SORT_POST_INLINE_SELECTION_LOOP_RE` captures:

```text
group(1): "        max_idx = i;\n"
group(2): "        for (j = i + 1; j < 0x78; j++) {\n"
group(3): "        }\n        if (max_idx != i) {"
```

But `_post_inline_boundary_selection_emission_loop_block()` returns a complete
replacement loop/body. For `selected_state == "decision"`, the replacement
already includes:

```c
        for (j = i + 1; j < 0x78; j++) {
            ...
        }
```

For `selected_state == "name"` and `"text-total"`, it also includes an outer
local-state block and closes the inner `j` loop.

`_post_inline_boundary_selection_emission_patcher()` currently substitutes:

```python
f"{match.group(1)}{replacement}{match.group(3)}"
```

Appending `match.group(3)` adds the original close brace for the `j` loop even
though the replacement already emitted it. The result is the exact invalid
shape from the issue:

```c
        }
        }
        if (max_idx != i) {
```

This affects all four generated variants because they all share the same
patcher and all replacement snippets close the selected region themselves:

- `helper-selected-name-carried`
- `helper-selected-total-carried`
- `helper-emission-cursor-owner`
- `helper-selected-state-emission-coupled`

I confirmed the current local test path fails with the same signature:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  -k "sort_post_inline_boundary_continuation_generates_selection_emission_only or sort_post_inline_boundary_selection_emission_classifier_sets_final_family" \
  -q
```

Observed failure:

```text
assert 15 == 16
where 15 = source_text.count("{")
where 16 = source_text.count("}")
```

## Production Changes

### 1. Fix the replacement boundary

In `_post_inline_boundary_selection_emission_patcher()`, stop appending the
closing brace from `match.group(3)` when the replacement is a complete selected
region.

Preferred minimal implementation:

```python
patched_function = _SORT_POST_INLINE_SELECTION_LOOP_RE.sub(
    lambda match: (
        f"{match.group(1)}"
        f"{replacement}"
        f"{match.group(3).lstrip('        }\\n')}"
    ),
    function_text,
    count=1,
)
```

Do not use that exact `lstrip` form; it is unsafe because `str.lstrip` removes a
character set, not a prefix. Instead add a small explicit helper, for example:

```python
def _post_inline_boundary_selection_emission_after_loop_suffix(match: re.Match[str]) -> str:
    suffix = match.group(3)
    prefix = "        }\n"
    if not suffix.startswith(prefix):
        return suffix
    return suffix[len(prefix):]
```

Then:

```python
lambda match: (
    f"{match.group(1)}"
    f"{replacement}"
    f"{_post_inline_boundary_selection_emission_after_loop_suffix(match)}"
)
```

This keeps `max_idx = i;`, uses the complete replacement loop/block, and keeps
`if (max_idx != i) {` without duplicating the captured loop close.

Alternative acceptable implementation:

- Change `_SORT_POST_INLINE_SELECTION_LOOP_RE` so group 3 captures only
  `if (max_idx != i) {`.
- Keep the patcher substitution shape simple.
- Verify no other call site depends on the old group 3 shape. Current search
  shows this regex is only used by this ready check/patcher pair.

Avoid converting `_post_inline_boundary_selection_emission_loop_block()` into
body-only snippets unless there is a strong reason; the `name` and `text-total`
variants need a local-state scope around the `j` loop, so complete region
replacement is the clearer model.

### 2. Add a generated-source structural validation guard

The immediate bug is generation, but issue #1060 also asks the scoring path to
distinguish invalid source from valid terminal exhaustion.

Add a small syntax/structure validator in
`post_meta_source_family_synthesis.py`, used before scoring and optionally
before returning generated payloads. It should be intentionally lightweight:

- Check brace balance with a C-comment/string-aware scanner if one already
  exists nearby; otherwise add a simple private helper that ignores braces in
  strings/comments.
- Check that the retained source still contains the expected score function
  (`context.source_function` / `_candidate_score_function(...)`) via existing
  `find_function` / `_find_source_function` helpers if practical.
- Return structured details, e.g.:

```json
{
  "status": "invalid-source",
  "reason": "brace-imbalance",
  "brace_balance": -1,
  "candidate_id": "...",
  "source_retained": "..."
}
```

Recommended integration points:

- `write_source_family_candidates(...)`: annotate each written row with
  `source_validation` and `source_valid` after writing `source_text`.
- `score_source_candidates(...)`: before invoking `debug target score-source`,
  if `source_valid is False`, append a score row with:
  - `error: "invalid-source"`
  - `score_returncode: None`
  - `source_validation`
  - `blockers: [{"reason": "invalid-generated-source", ...}]`
  - `source_file` / `source_retained`
  Then skip subprocess scoring for that candidate.

This prevents compiler stderr from being the first structured signal and makes
the failure actionable even in no-score/write-probe mode.

### 3. Refine score classification for invalid generated source

In `classify_source_family_scores(...)`, where `error_rows` are turned into a
generic `score-row-error` blocker, add a more specific blocker when all or any
error rows have `score_error == "invalid-source"` or a
`source_validation.status == "invalid-source"` payload:

```json
{
  "reason": "invalid-generated-source",
  "candidate_ids": [...],
  "source_validation": [...]
}
```

Return shape should remain non-terminal:

- `status: "blocked"`
- `reason: "invalid-generated-source"` or keep
  `reason: "score-rows-not-terminal-safe"` and add
  `terminal_blocker: "invalid-generated-source"`
- No `terminal_summary`
- No terminal exhausted proof

Do not allow invalid-source rows through either terminalization gate:

- `_can_terminalize_structural_guard_exhaustion`
- `_can_terminalize_required_assignment_exhaustion`

Those already reject any `score_error`, so the main change is explicit
classification/evidence, not terminal safety.

### 4. Preserve valid exhaustion behavior

Once the brace fix lands, valid-but-rejected Sort selection/emission rows should
continue to terminalize when all rows are score-valid and only terminal-safe
blockers remain:

- `structural-guard-not-accepted`
- `protected-targets-not-jointly-preserved`

Do not weaken the existing Sort terminalization checks for required assignment
exhaustion.

## Regression Tests

Add/update tests in:

```text
/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py
```

### Test 1: generator emits balanced post-inline selection/emission candidates

The current local test
`test_sort_post_inline_boundary_continuation_generates_selection_emission_only`
already has the right assertions and currently fails:

```python
for row in candidates:
    source_text = row["source_text"]
    assert source_text.count("{") == source_text.count("}")
    assert "\n        }\n        }\n        if (max_idx != i) {" not in source_text
```

Keep this test, or formalize it if it is currently an uncommitted local change.
Also assert the generated family count is four, so all reported issue variants
are covered:

```python
assert {row["variant_id"] for row in candidates} == {
    "helper-selected-name-carried",
    "helper-selected-total-carried",
    "helper-emission-cursor-owner",
    "helper-selected-state-emission-coupled",
}
```

### Test 2: write-probes materializes balanced files

Add a CLI or write helper test that exercises `--write-probes`/`write_source_family_candidates`
for this exact family, then reads every retained `.c` path and asserts:

- the file exists
- brace count is balanced
- the extra-brace pattern before `if (max_idx != i)` is absent
- the file still contains `void mnDiagram_8023FC28` or the configured
  `source_function`
- candidate metadata has `source_valid is True` and/or
  `source_validation.status == "valid"` if the validation guard is added

This covers the path that produced the artifacts in #1060, not only in-memory
`source_text`.

### Test 3: invalid generated source is classified explicitly

Construct a candidate for
`SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION` with a
retained source text/path that has the known extra brace pattern, then run the
new validation/scoring join path. The expected payload should be non-terminal
and explicit:

- `status == "blocked"`
- `reason` or `terminal_blocker` identifies `invalid-generated-source`
- blocker includes the candidate id
- no `terminal_summary`
- no `next_unsupported_source_family`
- `score_rows[0]["score_error"] == "invalid-source"`
- `score_rows[0]["source_validation"]["brace_balance"] == -1`

If using `score_source_candidates(...)`, monkeypatch `subprocess.run` and assert
it is not called for invalid source.

### Test 4: valid rejected rows still terminalize

Keep/extend
`test_sort_post_inline_boundary_selection_emission_classifier_sets_final_family`
to confirm that a score-valid row with required-assignment loss still returns:

- `status == "terminal"`
- terminal reason
  `sort-post-inline-boundary-selection-emission-source-shape-exhausted/no-floor-improvement`
- final family
  `sort-no-modeled-source-actionable-family-after-post-inline-boundary-selection-emission-source-shape`

This guards against making all score errors/generation blockers suppress valid
terminal exhaustion.

### Test 5: live score interruption/timeout unaffected

Existing tests:

- `test_cli_source_model_synthesis_live_score_interrupt_emits_partial_json`
- `test_cli_source_model_synthesis_live_score_timeout_emits_partial_json`

Run them after classifier changes. They should still produce `status:
"incomplete"` and live-score terminal blockers, not `invalid-generated-source`.

## Verification Commands

Targeted first:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  -k "sort_post_inline_boundary or invalid_generated_source or live_score_interrupt or live_score_timeout" \
  -q
```

Then the source-model test module:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -q
```

Then smoke for the CLI surface:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  -k "source_model_synthesis" -q
```

Optional retained artifact rerun after production/test changes:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1058_1059_rerun/sort_post_inline_selection_emission/source_model_sort_post_inline_selection_scored.json \
  --source-file src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/issue_1060_sort_post_inline_braces/probes \
  --json
```

For each generated `.c`, confirm no extra-brace pattern and balanced braces.
If scoring is enabled, a valid rejected family should terminalize only after all
generated rows have valid source and real score rows.

## Risks and Notes

- The source-model implementation file is large and has many adjacent Sort and
  Draw stages. Keep the production change scoped to the post-inline
  selection/emission patcher and generic validation/classification helpers.
- Avoid changing `_SORT_POST_CROSS_TU_J_LOOP_RE`; the older cross-TU families
  intentionally generate body-only comparison blocks and still rely on the
  captured closing brace.
- If adding a brace scanner, avoid naive line-based removal of braces inside
  strings/comments if the helper will become shared.
- `manual_fixed_helper_emission_cursor_owner_score.json` reported
  `mnDiagram_SortNamesByKOs not in compiled pcdump` after manually deleting the
  extra brace. That may be due to scoring the full-unit source with
  `score_function`/source-function mismatch. After the brace fix, verify that
  metadata still sets `score_function` to `context.source_function` (currently
  done in the candidate metadata) and that `--full-unit-source` is present in
  `score_source_command_hint`.
