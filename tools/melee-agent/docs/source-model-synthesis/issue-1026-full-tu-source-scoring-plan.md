# Issue 1026: full-TU source scoring for helper/data/layout source-context candidates

Working repo reviewed: `/Users/mike/code/melee`

Production code was not modified while preparing this plan. The requested plan file is the only intended write.

## Evidence reviewed

- Capability audit:
  - `melee-agent capabilities search "source-model-synthesis full TU retained source scoring helper data layout candidates score-source"` returns the existing `debug target score-source` scorer and `debug search source-model-synthesis` family.
  - The installed `melee-agent` wrapper in this shell did not expose `debug search source-model-synthesis`, but the repo-local command does: `python -m src.cli debug search source-model-synthesis --help`.
- Current #1025 implementation exists in `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`:
  - `SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION`
  - `SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_MODEL`
  - `_sort_helper_data_layout_context_source_candidates(...)`
  - helper/accessor/layout variants:
    - `post-meta-sort-source-context-comparison-helper`
    - `post-meta-sort-source-context-comparison-helper-split-text-total`
    - `post-meta-sort-source-context-shift-emission-helper`
    - `post-meta-sort-source-context-sorted-names-accessor`
    - `post-meta-sort-source-context-layout-overlay-local`
- Existing generated artifacts under `/Users/mike/code/melee/build/diagnostics/issue_1025_helper_data_layout/` confirm the immediate defect:
  - helper/data/layout candidates are full source files and include helper/type insertions before `mnDiagram_8023FC28`;
  - their `validation_metadata.requires_full_unit_source` is absent;
  - their score command hints omit any full-TU scoring flag;
  - example command hint still reads `debug target score-source ... --function mnDiagram_8023FC28 ... --checkdiff-guard --json`.
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py::score_source_candidates(...)` constructs live scoring subprocess commands and never appends a full-unit option.
- `/Users/mike/code/melee/tools/melee-agent/src/cli/debug/target.py::score_source(...)` has no `--full-unit-source` CLI option.
- `/Users/mike/code/melee/tools/melee-agent/src/cli/debug/target.py::score_source(...)` invokes `_score_source_candidate_real_tree(...)` for `--checkdiff-guard` without `full_unit_source=True`.
- `/Users/mike/code/melee/tools/melee-agent/src/cli/debug/__init__.py::_score_source_candidate_real_tree(...)` already supports `full_unit_source=True`; in that mode it writes the whole candidate TU into the real source path, builds/checkdiffs, and restores the original file.
- The same function intentionally rejects helper definitions in target-function mode through `_new_external_function_definitions(...)`; this is the exact source of the issue's `candidate source defines helper function(s) outside mnDiagram_SortNamesByKOs...` / `mnDiagram_8023FC28...` errors.
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py::_score_error(...)` treats `structural_guard_error` as `score_error`. Therefore score-source can exit `0` and still be classified as a score-row error, producing `blocked` / `score-rows-not-terminal-safe`.
- Retained-frontier and allocator propagation are mostly already updated in this checkout:
  - `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py` knows `_SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION`, maps `post-meta-sort-source-context-*`, and ranks helper/data/layout terminal proof stage above whole-function and full-selection stages.
  - `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py` renders `next_unsupported_source_family` in retained-frontier terminal next steps.
- Focused tests run:
  - `python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k "helper_data_layout or live_score_returns_partial_row or cli_source_model_synthesis_writes_helper_data_layout_context_probes" -q`
  - Result: `8 passed, 96 deselected`.
  - `python -m pytest tools/melee-agent/tests/test_transform_corpus_full_unit_scoring.py -q`
  - Result: `1 failed, 3 passed`. The failure is an existing test-harness mismatch: the monkeypatched `_acquire_source_score_repo_lock` lambda does not accept the production `timeout=` keyword.

## Root cause

Issue #1025 added the bounded helper/data/layout source-context family and produces full-source candidates, but the scoring contract remains target-function-only.

The generated candidates intentionally define helpers or file-local layout/accessor types outside `mnDiagram_8023FC28`. `debug target score-source` can compile candidate text for target scoring, but its checkdiff structural guard still calls `_score_source_candidate_real_tree(...)` in default target-transfer mode. That path transfers only the target function into `src/melee/mn/mndiagram.c`; helper/type definitions outside the function would be dropped, so it rejects the candidate and sets `structural_guard_error`.

`source-model-synthesis` then joins those score-source JSON rows. Because `_score_error(...)` treats `structural_guard_error` as a score error, every helper/data/layout row is considered errored, even when `score_returncode=0` and `target_score` exists. Rows with score errors are deliberately not terminal-safe, so classification returns `blocked` / `score-rows-not-terminal-safe` instead of actionable ranked candidates or an exhausted helper/data/layout proof.

The loop back to older source families is a secondary consequence: once the helper/data/layout scored artifact is blocked instead of terminal/actionable, downstream retained-frontier and allocator stages lack a terminal-safe full-TU proof to carry forward. Current retained-frontier ranking appears already prepared for the helper/data/layout dimension, so the missing link is producing non-errored full-TU score rows.

## Fix strategy

Implement reusable full-TU retained source scoring. Do not create a Sort-only scoring side path.

Use metadata-driven behavior:

- Candidates that require definitions outside the target function set `validation_metadata.requires_full_unit_source = true`.
- Score command hints include `--full-unit-source`.
- Live `source-model-synthesis` scoring reads that metadata and appends `--full-unit-source`.
- `debug target score-source --full-unit-source` forwards full-unit mode into the checkdiff structural guard.
- The JSON output preserves the mode so retained artifacts are auditable.

This keeps the candidate family reusable for future helper/data/layout/cross-function candidates and avoids generating lower-fidelity inline-only rewrites just to satisfy the current scorer.

## Production changes

### 1. Mark helper/data/layout candidates as full-unit source candidates

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

In `_sort_helper_data_layout_context_source_candidates(...)`, extend the `metadata.update(...)` block for `SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION`:

```python
"requires_full_unit_source": True,
```

Keep existing metadata:

- `requires_target_score_validation = True`
- `requires_structural_guard = True`
- `score_function = context.source_function or context.function`
- `required_preserved_assignments = ["IG34->r27", "IG44->r25"]`

Do not mark ordinary local, natural, semantic, protected-loss, full-selection, or whole-function body-only candidates as full-unit unless they actually introduce helper/type/data definitions outside the target function.

### 2. Add a reusable candidate full-unit predicate

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Add a small helper near `_candidate_requires_expression_score_validation(...)`:

```python
def _candidate_requires_full_unit_source(candidate: Mapping[str, Any]) -> bool:
    if candidate.get("requires_full_unit_source") is True:
        return True
    metadata = candidate.get("validation_metadata")
    return isinstance(metadata, Mapping) and metadata.get("requires_full_unit_source") is True
```

Use it in all command construction and row preservation paths below. This lets future callers put the flag either top-level or under `validation_metadata`.

### 3. Thread full-unit mode into command hints and live score-source subprocesses

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

Update `_score_command_hint(metadata)`:

- If `metadata.get("requires_full_unit_source") is True`, append `--full-unit-source` before the checkdiff/json options.
- This ensures generated artifacts and manual command hints are accurate.

Update `score_source_candidates(...)`:

- After adding `--retain-pcdump` / before guard options, append `--full-unit-source` when `_candidate_requires_full_unit_source(candidate)` is true.
- Add a conservative JSON/audit field to returned payloads if the scorer does not provide it:

```python
payload.setdefault(
    "full_unit_source",
    _candidate_requires_full_unit_source(candidate),
)
```

Update `_score_row(...)`:

- Preserve `requires_full_unit_source` as a top-level row boolean.
- Continue preserving the full `validation_metadata`.

### 4. Add `--full-unit-source` to `debug target score-source`

File: `/Users/mike/code/melee/tools/melee-agent/src/cli/debug/target.py`

Add a Typer option to `score_source(...)`:

```python
full_unit_source: Annotated[
    bool,
    typer.Option(
        "--full-unit-source/--target-function-source",
        help=(
            "Treat C_FILE as a complete replacement for the compile unit when "
            "running the real-tree checkdiff guard. Required when a retained "
            "candidate defines helper/type/data context outside the target function."
        ),
    ),
] = False,
```

Then, in the `if checkdiff_guard:` block, change the call to `_score_source_candidate_real_tree(...)`:

```python
real_score = _score_source_candidate_real_tree(
    candidate_path,
    function=function,
    melee_root=melee_root,
    timeout=active_timeout,
    deadline=command_deadline,
    include_structural_guard=True,
    full_unit_source=full_unit_source,
)
```

Add `full_unit_source` to JSON output when `json_out` is true, preferably regardless of checkdiff guard:

```python
payload["full_unit_source"] = full_unit_source
```

The existing local/remote pcdump compile staging can remain unchanged initially. `_score_source_compile_source_rel(...)` already stages non-`src/` retained candidates through the cflags unit source path, so the defect is specifically the checkdiff guard's target-function transfer. If implementation finds a path where full-unit candidates bypass staging, thread `full_unit_source` into `_score_source_compile_source_rel(...)` as an assertion/guard, but do not broaden the initial patch unnecessarily.

### 5. Make terminal-safe classification depend on full-TU rows, not helper errors

File: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`

No broad classifier rewrite is expected. Current code already includes `SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION` in:

- `_can_terminalize_structural_guard_exhaustion(...)`
- `_can_terminalize_required_assignment_exhaustion(...)`
- `_terminal_next_unsupported_source_model(...)`
- `_full_selection_swap_next_hint(...)`

After the full-unit scoring fix, helper/data/layout rows should no longer have the external-helper `structural_guard_error`, allowing these existing terminalization branches to run.

Add one defensive regression check rather than a broad behavior change:

- If every helper/data/layout row has `score_error` containing `candidate source defines helper function(s) outside`, classification should stay `blocked` and include a clear blocker telling the caller that the candidates were scored without `--full-unit-source`.
- This is optional if the command-level tests below prevent the state entirely, but it improves diagnosis for stale/offline score JSON.

### 6. Verify retained-frontier and allocator propagation, patch only if tests expose drift

Files:

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`

Expected current behavior:

- `retained_frontier_triage.py` already maps `post-meta-sort-source-context-*` to `_SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION`.
- `_source_model_proof_stage_rank(...)` already ranks helper/data/layout stage above whole-function and full-selection.
- `allocator_ceiling.py::_next_steps(...)` already renders `next_unsupported_source_family`.

Implementation should not rewrite these paths unless the regression tests fail. If a test still reproduces the loop to older families, patch only the stale rank/fallback path and preserve the current monotonic stage order:

`legacy/local < natural < semantic/protected-loss < full-selection < whole-function < helper/data/layout`.

## Regression tests

### A. Candidate generation marks helper/data/layout rows full-unit

File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Extend `test_sort_helper_data_layout_context_generation_from_whole_function_terminal`:

- Assert every helper/data/layout candidate has:
  - `row["validation_metadata"]["requires_full_unit_source"] is True`
  - `--full-unit-source` in `row["validation_metadata"]["score_source_command_hint"]`
- Assert no unrelated candidate family in nearby generation tests gets `requires_full_unit_source`.

### B. Written probe command hints preserve full-unit mode

File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Extend `test_cli_source_model_synthesis_writes_helper_data_layout_context_probes`:

- Assert every `payload["candidates"]` row for helper/data/layout has `--full-unit-source` in `score_command`.
- Assert the generated source files still contain helper/type definitions before `mnDiagram_8023FC28`.

### C. Live source-model-synthesis scoring appends `--full-unit-source`

File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add a focused `score_source_candidates(...)` test based on the existing subprocess-capture pattern around the current `score_source_candidates` tests:

- Build one candidate with:
  - `candidate_id = "post-meta-sort-source-context-shift-emission-helper"`
  - `candidate_path` under `repo_root/build/...`
  - `validation_metadata.requires_full_unit_source = True`
- Monkeypatch `synthesis.subprocess.run` and capture `cmd`.
- Return a JSON payload with `target_score`, accepted `structural_guard`, and no `structural_guard_error`.
- Assert:
  - `--full-unit-source` is present in `cmd`;
  - `--checkdiff-guard` is present;
  - the returned row has `full_unit_source` or equivalent metadata preserved;
  - `classify_source_family_scores(...)` can terminalize/actionable based on the normal target-score result rather than blocking as `score-rows-not-terminal-safe`.

Add the negative companion:

- Candidate without full-unit metadata should not include `--full-unit-source`.

### D. `debug target score-source` forwards full-unit mode into the structural guard

File: `/Users/mike/code/melee/tools/melee-agent/tests/test_transform_corpus_full_unit_scoring.py` or a new focused target CLI test file.

First repair the existing test harness:

- In `test_real_tree_scoring_full_unit_writes_whole_candidate_and_restores`, change the monkeypatch to accept `timeout`:

```python
lambda root, timeout=None: nullcontext()
```

Then add a CLI-level test:

- Use `CliRunner` against the top-level app or `target_app`.
- Monkeypatch the pcdump compile/parse/score dependencies enough to avoid a real compiler run, or add a narrower unit test around the `checkdiff_guard` call if CLI setup is too heavy.
- Monkeypatch `_score_source_candidate_real_tree` in the imported debug module to capture `full_unit_source`.
- Invoke:

```bash
debug target score-source <candidate.c> \
  --function fn_80000000 \
  --target <target.json> \
  --cflags-from src/melee/demo.c \
  --checkdiff-guard \
  --full-unit-source \
  --json
```

- Assert the captured call has `full_unit_source is True`.
- Add a default-mode assertion that omitting the flag passes `False`.

If a full CLI test is too brittle because `score_source(...)` imports many debug helpers inside the function, a targeted unit test can call the function with monkeypatched imports, but it must still prove the Typer option is wired to `_score_source_candidate_real_tree`.

### E. Stale/offline helper-error rows remain non-terminal but diagnostic

File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add a test using an offline score JSON row with:

- `score_returncode = 0`
- valid `target_score`
- `structural_guard_error = "candidate source defines helper function(s) outside mnDiagram_8023FC28: ..."`

Expected:

- Status remains `blocked`, not terminal.
- Reason remains `score-rows-not-terminal-safe`.
- Blockers include `score-row-error`.
- If the optional diagnostic is implemented, blockers also point at missing full-unit scoring.

This prevents stale unsafe rows from being accepted as terminal proof.

### F. Retained-frontier/allocator loop regression

File: `/Users/mike/code/melee/tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`

Add or extend the existing retained-frontier helper/data/layout tests:

- Feed a helper/data/layout terminal payload created from full-unit, non-error score rows into `triage_retained_frontiers(...)`.
- Feed the retained-frontiers output into `classify_allocator_ceiling(...)`.
- Feed that allocator artifact back into `generate_source_family_candidates(...)`.
- Expected:
  - If helper/data/layout is terminal, the next model is `SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_MODEL` and the next family is `SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_FAMILY`.
  - It must not regenerate older full-selection or whole-function source families.
  - If the intended behavior after terminal helper/data/layout is "proper next unsupported proof", candidate count should be `0` with a blocker naming the TU-level data-symbol/helper-boundary/cross-function family, not old candidates.

## Command-level smoke checks

Run from `/Users/mike/code/melee`.

Capability and help checks:

```bash
melee-agent capabilities search "source-model-synthesis full TU retained source scoring helper data layout candidates score-source"
cd tools/melee-agent
python -m src.cli debug target score-source --help | rg "full-unit|checkdiff|target-function-source"
python -m src.cli debug search source-model-synthesis --help | rg "score-source|write-probes|source"
```

Focused tests:

```bash
python -m pytest tools/melee-agent/tests/test_transform_corpus_full_unit_scoring.py -q
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py \
  -k "helper_data_layout or full_unit or score_source_candidates or retained_frontier_normalizes_helper_data_layout" \
  -q
```

No-score generation smoke:

```bash
python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json build/diagnostics/issue_1025_helper_data_layout/generated.json \
  --source-file src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/issue_1026_full_tu_generation/probes \
  --max-per-dimension 10 \
  --no-score \
  --json
```

Note: the input above is only useful if it represents the correct current ceiling. Prefer the issue's real retained-frontier/allocator artifact if available:

```bash
python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json build/diagnostics/mndiagram_1025_rerun/retained_frontiers_after_helper_data_context/sort_allocator_after_helper_data_context.json \
  --source-file src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/issue_1026_full_tu_generation/probes \
  --max-per-dimension 10 \
  --no-score \
  --json
```

Live score smoke, when target JSON is available:

```bash
python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json <whole-function-or-helper-data-layout-handoff.json> \
  --source-file src/melee/mn/mndiagram.c \
  --target <sort-ig34-ig44-target.json> \
  --cflags-from src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/issue_1026_full_tu_score/probes \
  --max-per-dimension 10 \
  --score \
  --timeout 120 \
  --json
```

Expected live-score artifact properties:

- helper/data/layout candidate score commands include `--full-unit-source`;
- `score_returncode=0` rows do not contain the external-helper `structural_guard_error`;
- status is either `actionable` with ranked retained candidates or `terminal` with `SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_MODEL`;
- no `blocked` / `score-rows-not-terminal-safe` solely due to helpers outside the target function.

## Risks and mitigations

- Risk: `--full-unit-source` could accidentally be applied to target-only snippets and overwrite the real TU with incomplete source during checkdiff guard.
  - Mitigation: only set metadata for candidates known to carry complete TU source; `_score_source_candidate_real_tree(full_unit_source=True)` already verifies the target function exists before writing.
- Risk: full-TU checkdiff guard builds are slower and hold the source-score repo lock longer.
  - Mitigation: use the flag only for candidates that need it and keep existing timeout behavior.
- Risk: remote score-source behavior may already stage full candidate text while local checkdiff guard did not; adding the flag changes only the guard, so remote/local target-score deltas should not change.
  - Mitigation: preserve current `_score_source_compile_source_rel(...)` behavior unless tests expose a staging bypass.
- Risk: stale offline score JSON from before this fix will still block.
  - Mitigation: keep it blocked, add a clearer diagnostic if practical, and regenerate scores with full-unit commands.
- Risk: retained-frontier loop could still occur if an artifact omits helper/data/layout dimension metadata.
  - Mitigation: retained-frontier already infers dimensions from `post-meta-sort-source-context-*`; add the loop regression test to lock that in.

## Stop condition

The issue is fixed when a bounded helper/data/layout source-context candidate set for `mnDiagram_SortNamesByKOs` is scored with helper definitions and full TU context preserved, and the resulting artifact is one of:

- `actionable`, with ranked retained C candidates whose score rows have no helper-definition structural guard error; or
- `terminal`, with no jointly preserved IG34/IG44 improvement and a proof naming the next unsupported TU-level data-symbol/helper-boundary/cross-function source-context family.

It is not fixed if helper/data/layout candidates still return `score_returncode=0` plus `structural_guard_error` about external helper definitions, or if feeding the resulting allocator/retained artifact back into `source-model-synthesis` regenerates older full-selection/whole-function families instead of preserving the helper/data/layout terminal proof.

## Orchestrator review addition

Run an end-to-end smoke after implementation using the real matcher artifacts from `/Users/mike/.codex/worktrees/eeff/melee`:

```bash
melee-agent debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1025_rerun/retained_frontiers_after_whole_function/sort_allocator_after_whole_function.json \
  --source-file /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --source-function mnDiagram_8023FC28 \
  --target /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_958_rerun/sort_target_from_diff_live.json \
  --cflags-from /Users/mike/code/melee/src/melee/mn/mndiagram.c \
  --write-probes /Users/mike/code/melee/build/diagnostics/issue_1026_full_tu_smoke/probes \
  --max-per-dimension 5 \
  --score \
  --timeout 120 \
  --json
```

The smoke should no longer produce `score_error` strings containing `candidate source defines helper function(s) outside`, and helper/data-layout source-context score commands should include `--full-unit-source`.
