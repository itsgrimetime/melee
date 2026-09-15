# Issue #1090 Plan: Sort Semantic Recombine Scores Address Name Instead of Public Function

## Scope

Plan only. Do not edit Melee production C source. The fix belongs in the `melee-agent` source-model/scoring plumbing under `/Users/mike/code/melee/tools/melee-agent`.

## Reviewed Evidence

- Issue #1090: `mnDiagram_SortNamesByKOs` semantic recombine retained rows fail with `function 'mnDiagram_8023FC28' not in compiled pcdump`.
- Current failing artifact:
  `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1088_1089_rerun/sort_post_broader_inline/source_model/source_model_scored.json`
- Continuation/frontier artifacts:
  `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1088_1089_rerun/sort_post_broader_inline/triage/source_family_continuation.json`
  `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1088_1089_rerun/sort_post_broader_inline/triage/retained_frontiers.json`
- Manual rescored semantic rows:
  `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1088_1089_rerun/sort_post_broader_inline/manual_rescore_semantic/*.json`

Key code reviewed:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
  - `SORT_FUNCTION = "mnDiagram_SortNamesByKOs"` and `SORT_SOURCE_FUNCTION = "mnDiagram_8023FC28"` at lines 40-41.
  - `generate_source_family_candidates()` resolves the actual source function locally at lines 1319-1329, but that resolved context is not returned to the CLI.
  - `_validation_metadata()` defaults `score_function` to `context.source_function or context.function` at lines 20723-20750.
  - `materialize_semantic_recombine_source_candidates()` builds semantic recombine candidate metadata from the stale caller context at lines 20870-20963.
  - `score_source_candidates()` honors candidate `validation_metadata.score_function` via `_candidate_score_function()` at lines 9270-9280 and 21270-21279.
- `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`
  - `source-model-synthesis` creates `context`, reads `source_text`, generates/scored first-pass candidates, then later materializes semantic recombines using the original `context` at lines 4903-5105.
- `/Users/mike/code/melee/tools/melee-agent/src/cli/debug/target.py`
  - `score-source` parses the compiled pcdump and fails if the requested `--function` is absent at lines 2689-2717.
- `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`
  - Existing semantic recombine live-scoring test at lines 7258-7493 does not assert the `--function` used for the second pass.
  - Existing public source-function override test at lines 14735-14772 proves the public alias is valid when explicitly supplied, but does not cover automatic resolution for semantic recombine.

## Root Cause

The first-pass generator resolves the source symbol correctly, but only inside `generate_source_family_candidates()`.

In the failing artifact, normal source-family candidates have:

- `function = mnDiagram_SortNamesByKOs`
- `source_function = mnDiagram_SortNamesByKOs`
- `score_function = mnDiagram_SortNamesByKOs`

Those rows score successfully.

The semantic recombine second pass is different. The CLI calls `materialize_semantic_recombine_source_candidates()` with the original normalized context, whose profile default is still:

- `function = mnDiagram_SortNamesByKOs`
- `source_function = mnDiagram_8023FC28`

`materialize_semantic_recombine_source_candidates()` then calls `_validation_metadata(context, ...)`, which stamps:

- `score_function = mnDiagram_8023FC28`
- `score_source_command_hint = ... --function mnDiagram_8023FC28 ... --full-unit-source ...`

`score_source_candidates()` later honors that candidate-level `score_function`, so `debug target score-source` compiles the full-unit retained source but searches the resulting pcdump for `mnDiagram_8023FC28`. The retained source actually defines and compiles `mnDiagram_SortNamesByKOs`, so `score-source` correctly reports that the requested address-name function is absent.

The continuation and retained-frontier outputs are downstream symptoms. They conservatively block on `score-row-error` / `score-rows-not-terminal-safe` because the semantic recombine rows contain scoring errors rather than valid target/structural evidence.

Do not fix this by changing `SORT_SOURCE_FUNCTION` to the public name globally. `/Users/mike/code/melee/src/melee/mn/mndiagram.c` still defines `mnDiagram_8023FC28`, while the issue artifacts come from a worktree where the function has been renamed. The scorer must use the symbol actually present in the source being scored.

## Implementation Plan

1. Centralize source-function resolution.

   File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

   Add a small helper near `_find_source_function()`:

   - Public or semi-public name: `resolve_source_function_context(source_text, context, *, require=True)`.
   - Internally call `_find_source_function(source_text, context)`.
   - If found, return `replace(context, source_function=found_name)`.
   - If not found and `require=True`, raise the same `SourceFamilySynthesisError("source-function-not-found", ...)` currently raised by `generate_source_family_candidates()`.
   - If not found and `require=False`, return the original context. This keeps direct materialization tests that use tiny synthetic source snippets from becoming stricter than today.

   Optionally add a private helper returning both context and span to avoid scanning twice:

   ```python
   def _resolve_source_function_context_and_span(...):
       ...
       return resolved_context, span
   ```

2. Reuse that helper in first-pass generation.

   File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

   In `generate_source_family_candidates()`, replace the current lines 1319-1329 local resolution block with the helper. Preserve current behavior:

   - Missing source function still raises `source-function-not-found`.
   - Candidate `source_function`, `validation_metadata.source_function`, `validation_metadata.score_function`, and score hints still use the resolved symbol.

3. Resolve the CLI context once and propagate it through all scoring phases.

   File: `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`

   In `source_model_synthesis_cmd()`:

   - Import `resolve_source_function_context`.
   - After `source_text = resolved_source.read_text(...)` and after the optional `--source-function` override, call:

     ```python
     context = resolve_source_function_context(source_text, context)
     ```

   - Keep building `validation_options` after this call.
   - Pass this resolved `context` to:
     - `generate_source_family_candidates()`
     - both `score_source_candidates()` calls
     - `classify_source_family_scores()`
     - `materialize_semantic_recombine_source_candidates()`
     - final payload `context.to_dict()`

   This fixes the CLI path that generated the failing artifact. It also makes the output context truthful: if the retained source has the public function, `context.source_function` will be public.

4. Harden direct semantic recombine materialization.

   File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

   In `materialize_semantic_recombine_source_candidates()`, before `metadata_base = _validation_metadata(...)`, call:

   ```python
   context = resolve_source_function_context(source_text, context, require=False)
   ```

   This makes direct callers safe even if they bypass the CLI. With real full-unit source, the materialized semantic recombine rows will inherit the compiled source symbol. With synthetic snippet tests that do not include the profiled function, behavior remains backward-compatible.

5. Do not add manual-rescore ingestion as the primary fix.

   The manual rescored JSON files prove the correct function name works, but they currently lack enough durable join/provenance fields at top level (`candidate_id`, `source_retained`, command metadata). Ingesting them ad hoc would paper over the bad command generation and risk attaching score evidence to the wrong retained source. The correct production fix is to generate valid score rows in the semantic recombine second pass.

   If a one-off recovery is still needed before rerunning, normalize manual score JSON externally by deriving `candidate_id` from the filename and `source_retained` from `source_model/probes/<candidate_id>.c`, then pass those normalized rows via `--score-json`. Do not bake that into the main path for this issue.

## Regression Tests

1. Add a source-function resolution unit test.

   File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

   Add a test near the existing source-function override coverage:

   - Build `context = _context()` so `context.source_function == "mnDiagram_8023FC28"`.
   - Build source text by replacing `mnDiagram_8023FC28` with `mnDiagram_SortNamesByKOs` in `_sort_source()`.
   - Call `resolve_source_function_context(source_text, context)`.
   - Assert the returned context has `source_function == SORT_FUNCTION`.
   - Assert old-name source still resolves to `SORT_SOURCE_FUNCTION`.

   Why it prevents recurrence: it locks the alias-resolution rule to the source text, not the static profile default.

2. Add or strengthen direct semantic recombine materialization coverage.

   File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

   Extend the existing materialization test around lines 7180-7212, or add a sibling test:

   - Use a context whose profile source function is `mnDiagram_8023FC28`.
   - Use source text defining `void mnDiagram_SortNamesByKOs(void)`.
   - Materialize a semantic recombine row.
   - Assert the materialized candidate has:
     - `source_function == "mnDiagram_SortNamesByKOs"`
     - `validation_metadata.source_function == "mnDiagram_SortNamesByKOs"`
     - `validation_metadata.score_function == "mnDiagram_SortNamesByKOs"`
     - `score_source_command_hint` contains `--function mnDiagram_SortNamesByKOs`
     - `score_source_command_hint` does not contain `mnDiagram_8023FC28`
     - `--full-unit-source` is still present

   Why it prevents recurrence: this is the exact failing materializer path, independent of the CLI.

3. Strengthen the live semantic recombine CLI test.

   File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

   In `test_cli_source_model_synthesis_scores_materialized_semantic_recombine()`:

   - Keep `context = _sort_semantic_context()` so the normalized profile starts with `mnDiagram_8023FC28`.
   - Keep the source fixture defining `mnDiagram_SortNamesByKOs`.
   - In `fake_score_source_candidates()`, when `len(score_calls) == 2`, assert every semantic recombine candidate row has public score metadata and command:

     ```python
     metadata = row["validation_metadata"]
     assert metadata["score_function"] == SORT_FUNCTION
     assert metadata["source_function"] == SORT_FUNCTION
     assert "--function mnDiagram_SortNamesByKOs" in row["score_command"]
     assert "mnDiagram_8023FC28" not in row["score_command"]
     assert row["full_unit_source"] is True or metadata["requires_full_unit_source"] is True
     ```

   Why it prevents recurrence: it covers the two-pass CLI flow that generated the bad artifact. The current test fakes scores but never inspects the function passed to the scorer.

4. Keep existing override coverage.

   Existing tests:

   - `test_cli_source_function_override_allows_public_sort_alias`
   - `test_cli_source_function_override_allows_public_draw_alias`

   These should continue to pass. They verify explicit `--source-function` remains honored.

5. No retained-frontier unit test is required for this fix.

   `retained_frontier_triage.py` is correctly conservative when score rows contain errors. The regression should ensure the score rows no longer contain the bad function error. Add retained-frontier tests only if implementation changes evidence consumption, which this plan does not require.

## Test Commands

Run focused unit tests:

```bash
cd /Users/mike/code/melee
pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  -k "semantic_recombine_materialization or scores_materialized_semantic_recombine or source_function_override_allows_public_sort_alias"
```

Run broader relevant tests:

```bash
cd /Users/mike/code/melee
pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
       tools/melee-agent/tests/test_candidate_verify.py \
       tools/melee-agent/tests/test_transform_corpus_full_unit_scoring.py
```

## Artifact Smoke Checks

These are intended after the code fix. They should be run in the artifact worktree because that source defines the public Sort function.

First, confirm the current failure shape:

```bash
cd /Users/mike/.codex/worktrees/eeff/melee
jq -r '
  .semantic_recombine_second_pass.materialization.candidates[]
  | [.candidate_id, .validation_metadata.score_function, .score_command]
  | @tsv
' build/diagnostics/mndiagram_1088_1089_rerun/sort_post_broader_inline/source_model/source_model_scored.json

jq -e '
  [.score_rows[]
   | select((.candidate_id // "") | contains("semantic-recombine"))
   | select((.score_error // "") | contains("not in compiled pcdump"))]
  | length == 4
' build/diagnostics/mndiagram_1088_1089_rerun/sort_post_broader_inline/source_model/source_model_scored.json
```

Then rerun source-model synthesis into a fresh diagnostics directory:

```bash
cd /Users/mike/.codex/worktrees/eeff/melee
mkdir -p build/diagnostics/issue_1090_verify/source_model
set +e
melee-agent debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json build/diagnostics/mndiagram_1088_1089_rerun/sort_post_broader_inline/allocator_ceiling.json \
  --source-file src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/issue_1090_verify/source_model/probes \
  --target build/diagnostics/mndiagram_958_rerun/sort_target_from_diff_live.json \
  --cflags-from src/melee/mn/mndiagram.c \
  --score \
  --checkdiff-guard \
  --continue-after-final-source-family \
  --timeout 90 \
  --json > build/diagnostics/issue_1090_verify/source_model/source_model_scored.json
status=$?
set -e
test "$status" -eq 0 -o "$status" -eq 3
```

Validate the semantic recombine rows used the public function and produced real score evidence:

```bash
cd /Users/mike/.codex/worktrees/eeff/melee
jq -e '
  [.semantic_recombine_second_pass.materialization.candidates[]
   | .validation_metadata.score_function] as $functions
  | ($functions | length) == 4
    and all($functions[]; . == "mnDiagram_SortNamesByKOs")
' build/diagnostics/issue_1090_verify/source_model/source_model_scored.json

jq -e '
  [.score_rows[]
   | select((.candidate_id // "") | contains("semantic-recombine"))] as $rows
  | ($rows | length) == 4
    and all($rows[];
      (.score_error == null)
      and ((.score_command // "") | contains("--function mnDiagram_SortNamesByKOs"))
      and ((.score_command // "") | contains("--full-unit-source"))
      and (.target_score != null)
    )
' build/diagnostics/issue_1090_verify/source_model/source_model_scored.json

! rg "post-meta-sort-semantic-recombine.*--function mnDiagram_8023FC28" \
  build/diagnostics/issue_1090_verify/source_model/source_model_scored.json
```

Rebuild continuation from the fixed source-model artifact:

```bash
cd /Users/mike/.codex/worktrees/eeff/melee
mkdir -p build/diagnostics/issue_1090_verify/triage
set +e
melee-agent debug search source-family-continuation \
  --function mnDiagram_SortNamesByKOs \
  --source-model-json build/diagnostics/issue_1090_verify/source_model/source_model_scored.json \
  --out build/diagnostics/issue_1090_verify/triage/source_family_continuation.json \
  --json > build/diagnostics/issue_1090_verify/triage/source_family_continuation.stdout.json
status=$?
set -e
test "$status" -eq 0 -o "$status" -eq 3

jq -e '
  (.reason // "") != "score-rows-not-terminal-safe"
  and (.terminal_reason // "") != "post-meta-source-family-continuation-needs-more-evidence"
' build/diagnostics/issue_1090_verify/triage/source_family_continuation.json
```

Optionally rerun retained-frontiers over the fixed artifacts:

```bash
cd /Users/mike/.codex/worktrees/eeff/melee
set +e
melee-agent debug search retained-frontiers \
  --function mnDiagram_SortNamesByKOs \
  --artifact build/diagnostics/issue_1090_verify/source_model/source_model_scored.json \
  --artifact build/diagnostics/issue_1090_verify/triage/source_family_continuation.json \
  --json > build/diagnostics/issue_1090_verify/triage/retained_frontiers.json
status=$?
set -e
test "$status" -eq 0 -o "$status" -eq 3

jq -e '
  [.. | objects | select((.reason? // "") == "score-rows-not-terminal-safe")]
  | length == 0
' build/diagnostics/issue_1090_verify/triage/retained_frontiers.json
```

## Risks And Guardrails

- Do not globally replace `SORT_SOURCE_FUNCTION`; older worktrees still compile `mnDiagram_8023FC28`.
- Do not make `materialize_semantic_recombine_source_candidates()` strictly require a real function in every synthetic snippet unless all existing synthetic tests are updated. Use `require=False` there and strict resolution in the CLI/generator path.
- Keep `score-source` behavior unchanged. It is correct to report a missing function when the caller asks for a symbol absent from the pcdump.
- Keep retained-frontier terminal safety strict. The recurrence should be prevented by valid score rows, not by classifying infrastructure-like score errors as acceptable terminal proof.

## Definition Of Done

- Semantic recombine materialized candidates generated from public Sort source carry `score_function = mnDiagram_SortNamesByKOs`.
- Their embedded `score_command` and actual `score_source_candidates()` invocation use `--function mnDiagram_SortNamesByKOs`.
- The four retained semantic recombine rows no longer contain `score_error`.
- `source-family-continuation` no longer blocks with `score-rows-not-terminal-safe` for this artifact family.
- Focused unit tests and the artifact smoke checks above pass.
