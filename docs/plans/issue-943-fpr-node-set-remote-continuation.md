# Fix 943: Remote-safe FPR node-set exhaustive evidence

## Scope

Issue #943 is a tooling feature for `mwcc-debug`, not a Melee source change.
The affected workflow is `mnDiagram_DrawCellNumber` FPR node-set evidence for
the IG32 `col_offset` f26->f28 and IG37 `row_offset` f28->f26 expression-anchor
swap.

The requested artifact paths were not present in `/Users/mike/code/melee` during
this review:

- `build/diagnostics/mndiagram_draw_901_post900_terminal/node_set_split/ig32_col_offset_f26_to_f28.json`
- `build/diagnostics/mndiagram_draw_901_post900_terminal/node_set_split/ig37_row_offset_f28_to_f26.json`

This plan uses the issue facts as the artifact state: both summaries have
`status=exhausted`, `stop_reason=candidate-limit`, `generated_count` 32/33,
`candidate_count` 8, no `terminal_summary`, and no `case_c_order_repair`.
That is enough to root-cause the code path because current node-set-split has a
candidate cap and no remote backend.

No production changes should be made as part of writing this plan. The checkout
has unrelated dirty files; do not revert or overwrite them.

## Reviewed Code

- `/Users/mike/code/melee/tools/melee-agent/src/cli/debug/__init__.py:21187`
  through `21695` defines `debug target score-source`. It already has
  `--remote`, `--remote-fallback`, retained-source staging via
  `_run_remote_pcdump`, pcdump retention, `target_score`, and `expression_score`.
- `/Users/mike/code/melee/tools/melee-agent/src/cli/debug/__init__.py:36352`
  through `37219` defines `debug solve node-set-split`. It has no remote
  backend options. Baseline signature compilation is local at lines `36868`
  through `36878`; per-candidate signature/pcdump compilation is local at
  lines `37008` through `37017`; realized-candidate real-tree scoring is local
  at lines `37139` through `37149`.
- `/Users/mike/code/melee/tools/melee-agent/src/cli/debug/__init__.py:36961`
  through `36969` enforces the candidate limit before scoring the remaining
  generated candidates, then records `stop_reason="candidate-limit"`.
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/node_set_split.py:2157`
  through `2338` summarizes node-set results. It marks
  `wrong_register_exhausted` only when `stop_reason is None`, `pending_count`
  is zero, every row is `wrong-register`, and every row compiled.
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/node_set_split.py:2298`
  through `2401` emits `case_c_order_repair`, but only after a true exhaustive
  all-wrong-register FPR result.
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/node_set_split.py:6134`
  through `6142` preserves `target_score` into candidate rows, but there is no
  equivalent `expression_score` pass-through.
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py:15`
  and `:89` through `:92` treat `candidate-limit` and `budget-exhausted` as
  bounded evidence, which correctly prevents a practical-ceiling verdict for
  the current IG32/IG37 summaries.
- `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py:3540`
  through `3823` implements `debug search plan-transforms`. It can materialize
  node-set-delta probes and validate them with an external command. Its
  validation parser at lines `837` through `1180` already preserves
  `target_score` and `expression_score` from JSON validator output.

## Root Cause

This is not an allocator-ceiling bug. `allocator-ceiling` is right to return
bounded evidence: the node-set artifacts stopped after the candidate cap, so
they do not prove that all generated source candidates were evaluated.

The root cause is the node-set-split orchestration layer:

1. `debug solve node-set-split` is local-only. It compiles the baseline and
   every candidate through the local pcdump lane. In this worktree that lane is
   unsafe because an older `node_set_split` wibo child remains in UE state.
2. The solver can generate more candidates than it scores. Once
   `--max-candidates` is reached, it stops with `candidate-limit`, deletes the
   temporary unscored candidate sources, and emits only a generic rerun hint.
3. The summary format has no resume ledger that records all generated candidate
   IDs, candidate source paths/hashes, evaluated rows, skipped rows, and the
   exact command needed to continue remotely.
4. The existing remote-safe scorer (`debug target score-source --remote`) is
   one layer lower and is not reused by node-set-split. As a result, the only
   safe current workaround is a manual plan-transforms validation route, but
   node-set-split itself cannot consume that route or emit complete evidence.

## Fix Direction

Implement direct remote-safe node-set continuation first, and keep
plan-transforms as the fallback route.

The direct fix should make this command family possible:

```bash
melee-agent debug solve node-set-split \
  -f mnDiagram_DrawCellNumber \
  --class fpr \
  --source-file src/melee/mn/mndiagram.c \
  --ig 32 \
  --current-reg f26 \
  --target-reg f28 \
  --var col_offset \
  --force-phys 32:28,37:26 \
  --target <expression-anchor-target.json> \
  --expression-baseline <baseline.pcdump.txt> \
  --expression-source src/melee/mn/mndiagram.c \
  --remote \
  --max-candidates 0 \
  --retain-generated \
  --output build/diagnostics/mndiagram_draw_901_post900_terminal/node_set_split/ig32_col_offset_f26_to_f28.remote.json \
  --json
```

Run the analogous command for IG37 with `--ig 37 --current-reg f28
--target-reg f26 --var row_offset`.

If a target JSON is unavailable, `--force-phys 32:28,37:26` is still enough to
retain node-set `target_score`; `expression_score` requires a target spec with
expression anchors or a baseline pcdump/source pair from which anchors can be
derived.

## Production Changes

### 1. Add node-set backend and continuation options

File:
`/Users/mike/code/melee/tools/melee-agent/src/cli/debug/__init__.py`

Extend `solve_node_set_split_cmd` with:

- `--remote/--no-remote`
- `--remote-fallback/--no-remote-fallback`
- `--remote-host`
- `--remote-script`
- `--remote-branch`
- `--remote-no-pull`
- `--resume-summary PATH`
- `--output PATH`
- `--retain-generated/--no-retain-generated`
- `--generated-dir PATH`
- `--target PATH` for optional score-source-compatible target JSON/YAML
- `--expression-baseline PATH`
- `--expression-source PATH`
- `--expression-reg-class`, default `fpr`

Keep the default local behavior unchanged. `--remote` must bypass all local
wibo/compiler discovery. `--remote-fallback` should switch to remote when the
local unsafe-lane guard reports a UE wibo process for the unit or related
node-set probe directory.

### 2. Add a shared node-set pcdump backend helper

File:
`/Users/mike/code/melee/tools/melee-agent/src/cli/debug/__init__.py`

Introduce helpers near the existing node-set helpers:

- `_node_set_split_source_rel(path, melee_root)`
- `_node_set_split_unsafe_lane_payload(...)`
- `_node_set_split_compile_signature_and_pcdump_backend(...)`
- `_node_set_split_score_metadata_from_pcdump(...)`
- `_node_set_split_resume_command(...)`

`_node_set_split_compile_signature_and_pcdump_backend` should return a typed
payload with:

- `signature`
- `pcdump_text`
- `pcdump_path` when retained
- `remote_fallback` metadata when remote was used
- `terminal_blocker` when the backend could not produce a pcdump
- `unsafe_local_pcdump_lane` when local scoring was refused

For local mode, wrap the current
`_node_set_split_compile_signature_and_pcdump` behavior. For remote mode, call
the already-existing `_run_remote_pcdump` with:

- `source_rel=<candidate or baseline rel>`
- `compile_source_rel=<real src/... unit>`
- `stage_source_path=<local candidate path>` when the candidate is outside
  `src/`
- `stage_source_label=<candidate rel>`

Then parse the returned pcdump with the same `parse_hook_events` and
`baseline_signature` path currently used locally.

### 3. Wire the helper into node-set-split

File:
`/Users/mike/code/melee/tools/melee-agent/src/cli/debug/__init__.py`

Replace the local-only baseline compile at lines `36868` through `36878` with
the backend helper. Replace the per-candidate compile at lines `37008` through
`37017` with the same helper.

On backend failure:

- Do not silently mark the candidate `compile-failed` if the failure is lane or
  transport related.
- Emit a top-level summary with `status="blocked"`,
  `stop_reason="unsafe-local-pcdump-lane"` or
  `stop_reason="remote-pcdump-failed"`, a populated `stop_condition`, and an
  exact `resume_command`.
- Include `terminal_blocker`, `unsafe_local_pcdump_lane`, `remote_fallback`,
  `candidate_id`, and retained source path if available.

On candidate-limit:

- Continue to report `stop_reason="candidate-limit"`.
- Add `stop_condition.resume_command` that repeats the current invocation with
  `--max-candidates 0`, `--remote`, and `--resume-summary <current output>`.
- If `--output` was not provided, emit a command using the recommended
  diagnostics path under `build/diagnostics/<function>/node_set_split/`.

### 4. Persist generated candidates and support resume

Files:

- `/Users/mike/code/melee/tools/melee-agent/src/cli/debug/__init__.py`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/node_set_split.py`

When `--retain-generated` or `--resume-summary` is active, write a manifest
beside the output JSON:

```json
{
  "function": "mnDiagram_DrawCellNumber",
  "class_id": 1,
  "source_sha1": "...",
  "generated_count": 33,
  "candidates": [
    {
      "candidate_id": "...",
      "source_path": "...",
      "source_sha1": "...",
      "hunk_path": "...",
      "generated_index": 0
    }
  ]
}
```

The resume path should:

1. Load the prior summary and manifest.
2. Verify function, class, source file, request target, and source hash.
3. Preserve prior evaluated rows whose candidate source hashes still match.
4. Re-score only candidates not already evaluated, unless
   `--force-rescore` is later added.
5. Merge old and new rows in generation order before calling
   `summarize_node_set_split_scores`.

For old #943 artifacts that do not have a manifest, the command should still
work by regenerating candidates from source. In that case the summary should
set `resume_mode="regenerated-no-manifest"` so the evidence is transparent.

### 5. Preserve expression scores in node-set rows

File:
`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/node_set_split.py`

Extend `_score_row` near lines `6134` through `6142` to pass through
`expression_score` from either the scored entry or the objective mapping, the
same way it already passes through `target_score`.

File:
`/Users/mike/code/melee/tools/melee-agent/src/cli/debug/__init__.py`

When `--target` or expression options are supplied, compute scoring metadata
from the candidate pcdump using the same internals as `score-source`:

- `_load_target_spec`
- `_score_source_target_details`
- `_score_expression_anchors`
- `_read_expression_source`

Attach both `target_score` and `expression_score` to each candidate row. For
remote runs, also keep `remote_fallback` metadata per row.

### 6. Make allocator-ceiling understand unsafe continuation blockers

File:
`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`

Add `unsafe-local-pcdump-lane` and `remote-pcdump-failed` to the bounded
evidence handling, but do not let them count as source exhaustion. The result
should remain `status="bounded"` with `terminal_reason="bounded-evidence"` and
should surface the exact resume command from `stop_condition.resume_command` in
`next_steps`.

Do not change the existing candidate-limit behavior. A candidate-limited
node-set artifact must remain bounded until a continuation evaluates all
generated candidates.

### 7. Plan-transforms fallback route

File:
`/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`

This is secondary, not the primary fix. Add a first-class helper or documented
template that validates generated probes with remote score-source:

```bash
melee-agent debug search plan-transforms \
  -f mnDiagram_DrawCellNumber \
  --unit melee/mn/mndiagram \
  --force-phys 32:28,37:26 \
  --node-set-delta <node_set_delta.json> \
  --source-file src/melee/mn/mndiagram.c \
  --max-per-family 0 \
  --write-probes build/diagnostics/mndiagram_draw_901_post900_terminal/plan_transform_node_set_remote/probes \
  --validate-command "melee-agent debug target score-source {candidate_path} -f mnDiagram_DrawCellNumber --target <target.json> --cflags-from src/melee/mn/mndiagram.c --remote --retain-pcdump --json --expression-baseline <baseline.pcdump.txt> --expression-source src/melee/mn/mndiagram.c" \
  --json
```

The existing validation parser already preserves `target_score` and
`expression_score`; the missing part is making this route easy to emit from
node-set `case_c_order_repair.routes` or `next_steps` when direct continuation
cannot proceed.

## Regression Tests

### Node-set direct remote continuation

File:
`/Users/mike/code/melee/tools/melee-agent/tests/test_node_set_split.py`

1. `test_cli_node_set_split_remote_scores_all_generated_wrong_register`
   - Generate three deterministic FPR patches.
   - Monkeypatch `_run_remote_pcdump` to return pcdumps whose signatures assign
     IG32 to f26 instead of f28.
   - Invoke `node-set-split --remote --max-candidates 0 --json`.
   - Assert `stop_reason is None`, `pending_count == 0`,
     `wrong_register_exhausted is True`, `terminal_reason ==
     "all-wrong-register"`, and `case_c_order_repair` exists.
   - Assert no local compile helper is called.

2. `test_cli_node_set_split_candidate_limit_emits_remote_resume_command`
   - Generate at least three patches and run with `--max-candidates 1`.
   - Assert `stop_condition.kind == "candidate-limit"`,
     `wrong_register_exhausted is False`, and
     `stop_condition.resume_command` contains `--remote`, `--max-candidates 0`,
     and `--resume-summary`.

3. `test_cli_node_set_split_resume_summary_scores_only_pending_candidates`
   - Seed a prior summary/manifest with one evaluated wrong-register candidate
     and two pending candidates.
   - Invoke `--resume-summary <prior> --remote --max-candidates 0`.
   - Assert the old row is preserved, only pending candidates are compiled, and
     the final summary is exhaustive.

4. `test_cli_node_set_split_remote_rows_preserve_target_and_expression_scores`
   - Supply a target spec and expression baseline/source.
   - Fake scoring metadata with `target_score` and `expression_score`.
   - Assert each candidate row and nested objective preserve both fields.

5. `test_cli_node_set_split_unsafe_lane_blocks_with_resume_command`
   - Monkeypatch local safety to report a UE wibo process.
   - Invoke node-set-split without `--remote` and without `--remote-fallback`.
   - Assert it does not launch local pcdump, emits
     `stop_reason="unsafe-local-pcdump-lane"`, includes
     `unsafe_local_pcdump_lane.processes`, and includes a remote resume command.

6. `test_cli_node_set_split_remote_backend_failure_is_bounded_not_exhausted`
   - Fake `_run_remote_pcdump` returning no pcdump/exit 66.
   - Assert the summary is blocked/bounded, carries `terminal_blocker`, and does
     not set `wrong_register_exhausted`.

### Allocator-ceiling evidence handling

File:
`/Users/mike/code/melee/tools/melee-agent/tests/test_allocator_ceiling.py`

1. `test_candidate_limited_node_set_remains_bounded`
   - Keep or extend existing coverage: a node-set summary with
     `stop_reason="candidate-limit"` must produce bounded evidence.

2. `test_remote_continued_node_set_all_wrong_register_satisfies_legacy_evidence`
   - Combine a solve-coloring node delta, force-vector match, an exhaustive
     all-wrong-register node-set summary, and transform-negative evidence.
   - Assert `status == "practical-ceiling"` and
     `wrong_register_exhausted is True`.

3. `test_unsafe_local_lane_summary_is_bounded_with_resume_step`
   - Feed a node-set summary with `stop_reason="unsafe-local-pcdump-lane"` and
     `stop_condition.resume_command`.
   - Assert `status == "bounded"` and the resume command appears in
     `next_steps`.

### Plan-transforms fallback

File:
`/Users/mike/code/melee/tools/melee-agent/tests/search/test_cli_smoke.py`

1. `test_plan_transforms_remote_score_source_validation_preserves_expression_score`
   - Use the existing validate-command parser with JSON containing
     `target_score`, `expression_score`, `pcdump_path`, and `remote_fallback`.
   - Assert validation evidence and `validation_summary.ranked_guarded_partials`
     preserve the fields.

2. `test_plan_transforms_node_set_delta_all_probes_evaluated_becomes_exhausted_negative`
   - Generate FPR node-set probes with `--node-set-delta`.
   - Validate every probe with `match=false`/negative score-source JSON.
   - Assert `validation_summary.stop_condition ==
     "exhausted-negative-evidence"` and `remaining_probe_ids == []`.

### Existing remote score-source tests

File:
`/Users/mike/code/melee/tools/melee-agent/tests/test_debug_cli_reorg.py`

Do not duplicate the already-covered remote retained-source staging behavior.
Only add a small integration assertion if node-set uses a new shared helper:
`test_node_set_remote_backend_uses_retained_source_staging_contract` can assert
the helper calls `_run_remote_pcdump` with `source_rel` as the retained candidate
and `compile_source_rel` as the real `src/melee/mn/mndiagram.c` unit.

## Acceptance Criteria

For #943, the fix is complete when the IG32 and IG37 continuations produce one
of these outcomes:

1. Exhaustive negative node-set evidence:
   - `stop_reason is None`
   - `generated_count == evaluated_count`
   - `pending_count == 0`
   - every evaluated candidate is `wrong-register`
   - `wrong_register_exhausted == true`
   - FPR summaries include `case_c_order_repair`
   - retained rows include pcdump/source paths and target/expression scores when
     a target spec was provided

2. A populated blocker JSON:
   - `stop_reason` is `budget-exhausted`, `unsafe-local-pcdump-lane`, or
     `remote-pcdump-failed`
   - `stop_condition` includes exact budget/backend details
   - `stop_condition.resume_command` is directly runnable and uses the remote
     backend
   - no summary with pending candidates is accepted by allocator-ceiling as a
     practical ceiling

After both IG32 and IG37 are continued exhaustively, rerunning
`melee-agent debug solve allocator-ceiling` with the continued summaries should
no longer report bounded evidence from `candidate-limit`. It should either
classify a practical ceiling or point to a later source-actionable route such as
the retained `case_c_order_repair`.
