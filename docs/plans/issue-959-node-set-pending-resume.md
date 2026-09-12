# Implementation Plan: Issue #959 Node-Set Pending Resume

## Scope

Plan only. Do not implement production code while preparing this plan.

Target repo reviewed: `/Users/mike/code/melee`

Issue: `#959 Draw live FPR node-set split exhausts budget before scoring or
retaining pending candidates`

Tool: `mwcc-debug`

Claimed by: `codex-fd86-issue-resolver`

Capability audit run:

```bash
melee-agent capabilities search "node-set-split pending resume budget-aware generation scoring candidates"
```

Relevant capability found:

- `debug solve node-set-split`

This fix should extend the existing `debug solve node-set-split` command. Do
not add a new top-level command.

## Reviewed Context

Current dirty files in `/Users/mike/code/melee` before planning:

- `tools/melee-agent/src/cli/debug/__init__.py`
- `tools/melee-agent/src/cli/scratch/__init__.py`
- `tools/melee-agent/src/cli/sync/production.py`
- `tools/melee-agent/src/search/solver/solve.py`
- `tools/melee-agent/tests/search/solver/test_solve.py`
- `tools/melee-agent/tests/test_scratch.py`
- untracked `docs/matching-tooling-postmortem-2026-06-15.md`

The relevant dirty hunks in `tools/melee-agent/src/cli/debug/__init__.py` are
unrelated messaging/score handling edits. Implementation must inspect them and
avoid broad rewrites.

Relevant files:

- `tools/melee-agent/src/cli/debug/__init__.py`
  - `solve_node_set_split_cmd`
  - `_node_set_split_resume_manifest_path`
  - `_node_set_split_load_resume_summary`
  - `_node_set_split_resume_command`
  - `_emit_node_set_split_summary`
- `tools/melee-agent/src/mwcc_debug/node_set_split.py`
  - `generate_node_set_split_patches`
  - `generate_node_set_introduce_binding_patches`
  - `generate_coupled_node_set_split_patches`
  - `summarize_node_set_split_scores`
- `tools/melee-agent/src/mwcc_debug/source_shape.py`
  - `CandidatePatch`
  - `CandidateScore`
- `tools/melee-agent/tests/search/solver/test_cli_solve.py`
- `tools/melee-agent/tests/search/solver/test_solve.py`

## Root Cause

`solve_node_set_split_cmd` can generate source candidates under a global
deadline, then discover there is no time left for baseline compilation or
candidate scoring. In that path:

- generated candidate sources live only in memory or a temporary directory,
- summaries do not include pending candidate source paths,
- budget-exhausted summaries do not receive resume commands,
- `--resume-summary` notices a manifest path but no writer/reader exists,
- single-IG generation ignores the computed `candidate_limit`, so bounded runs
  can still spend budget generating far more candidates than intended.

For issue #959 this produced the bad handoff: candidates existed conceptually,
but no scoring, retained source list, ranked partial list, or resume metadata
survived.

## Recommended Implementation Scope

Implement a manifest-backed resume path inside the existing
`debug solve node-set-split` command, plus a small bounded-generation fix.

Do not implement a new command. Do not touch `src/melee/`.

### 1. Add Manifest Helpers

File: `tools/melee-agent/src/cli/debug/__init__.py`

Add small helpers near the existing node-set summary/resume helpers:

- `_node_set_split_candidate_dir(summary_path: Path) -> Path`
- `_node_set_split_write_generated_manifest(...) -> Path`
- `_node_set_split_load_generated_manifest(...) -> list[CandidatePatch]`
- `_node_set_split_pending_candidate_records(...) -> list[dict[str, Any]]`

Manifest behavior:

- Write to `_node_set_split_resume_manifest_path(summary_path)`.
- Write candidate source files to `<summary-stem>.candidates/`.
- Store `version`, `kind`, `function`, `class_id`, `source_file`,
  `source_sha256`, `request`, `coupled_requests`, `candidate_order`, and
  candidate records.
- Candidate records include `candidate_id`, `summary`, `source_path`,
  `source_sha256`, `touched_ranges`, `hunk`, and `metadata`.
- Write candidate files first and the manifest last.
- Use deterministic safe filenames derived from candidate IDs.
- Hash the original source and retained candidate source, then verify both on
  resume.

### 2. Bound Generation Consistently

File: `tools/melee-agent/src/cli/debug/__init__.py`

Update the generator calls in `solve_node_set_split_cmd`:

- Pass `max_candidates=candidate_limit` to
  `generate_node_set_split_patches`.
- Pass `max_candidates=candidate_limit` to
  `generate_node_set_introduce_binding_patches`.
- Keep coupled generation bounded by `candidate_limit`, but ensure the coupled
  path does not discard complete candidates already built if the deadline
  expires late.

Do not reinterpret `--max-candidates 0`; it should remain unlimited.

### 3. Write Manifest Before Baseline Compile

File: `tools/melee-agent/src/cli/debug/__init__.py`

After `patches = _order_node_set_patches_for_search(patches)` and after
`summary_path` is known:

- Write a manifest whenever generated candidates exist and either:
  - `--retain-generated` is set,
  - `--output` is set,
  - a budget/candidate stop condition leaves pending candidates,
  - or `--resume-summary` is in use.
- Add manifest path metadata to summaries that have pending candidates.
- For budget exhaustion before baseline compile, call the summary writer with
  `write_for_resume=True`.

Implementation note: `summary_path` may need to be computed before the
baseline-timeout branch so the manifest exists before any early exit.

### 4. Resume From Manifest

File: `tools/melee-agent/src/cli/debug/__init__.py`

In the `--resume-summary` flow:

- If the manifest exists, set `resume_mode="manifest"`.
- Load `patches` from manifest source files.
- Do not call generation functions in manifest mode.
- Validate function/class/source compatibility.
- Fail with exit 2 for missing source files, hash mismatches, malformed
  manifest JSON, or function mismatch.
- Preserve `touched_ranges` when reconstructing `CandidatePatch` objects.
- Treat rows with `score.status == "budget-exhausted"` or realized objectives
  without `checkdiff_pct/checkdiff_delta` as still pending. They must be
  eligible for resume/checkdiff scoring rather than counted as complete.
- Preserve existing `regenerated-no-manifest` behavior for old summaries.

Optional but useful:

- Treat prior summary rows as already-scored rows and score only remaining
  manifest candidates. This is not required for the first fix if all current
  issue #959 summaries have `scored_count=0`, but the code should not make
  later pending-only resume harder.

### 5. Emit Resume Commands For Budget Exhaustion

Files:

- `tools/melee-agent/src/cli/debug/__init__.py`
- `tools/melee-agent/src/mwcc_debug/node_set_split.py`

Update final summary creation so `resume_command` is passed for
`budget-exhausted` when unscored generated candidates exist, not only for
`candidate-limit`.

The resume command should point at the summary path and keep existing context:

```text
melee-agent debug solve node-set-split ... --resume-summary <summary> --output <summary> --max-candidates 0 --json
```

Add summary keys:

- `manifest_path`
- `generated_candidate_manifest`
- `pending_candidates`
- `resume_mode`

Keep summaries honest:

- `status="exhausted"` is acceptable for budget stop.
- `exhaustive=false` must be set when pending candidates exist.
- Do not emit terminal wording that implies the source-shape family is fully
  exhausted while `pending_count > 0`.

## Regression Tests

Add or update tests in
`tools/melee-agent/tests/search/solver/test_cli_solve.py`.

### Test: Single-IG Generation Honors Max Candidates

Name:

```python
test_solve_node_set_split_single_generation_passes_candidate_limit
```

Shape:

- Use `_node_split_repo`.
- Monkeypatch `src.mwcc_debug.node_set_split.generate_node_set_split_patches`.
- Assert the fake receives `max_candidates == 2`.
- Return exactly two `CandidatePatch` objects when max is 2.
- Invoke:

```bash
debug solve node-set-split -f fn_test --class gpr --ig 40 \
  --target-reg r30 --var holder --max-candidates 2 --json
```

Expected:

- exit 4 if no candidate realizes the objective,
- `generated_count == 2`,
- candidate IDs are the two retained/generated IDs,
- no unexpected third candidate is scored or reported.

### Test: Budget Exhaustion Writes Manifest And Resume Command

Name:

```python
test_solve_node_set_split_budget_exhausted_writes_pending_manifest
```

Shape:

- Monkeypatch generator to return three patches.
- Use `--budget 0 --retain-generated --output <tmp>/node-set-summary.json`.
- Ensure compile/baseline functions are not called.

Expected:

- exit 4,
- `stop_condition.kind == "budget-exhausted"`,
- `generated_count == 3`,
- `scored_count == 0`,
- `pending_count == 3`,
- `manifest_path` points to an existing JSON file,
- manifest has three candidate records,
- each candidate `source_path` exists and contains the patched source,
- `stop_condition.resume_command` includes `--resume-summary` and the summary
  path,
- the output summary file exists.

### Test: Resume Manifest Scores Without Regeneration

Name:

```python
test_solve_node_set_split_resume_manifest_scores_retained_candidates_without_regeneration
```

Shape:

- Create a summary plus matching manifest, either by calling the helper or by
  running the previous budget-exhausted setup.
- Monkeypatch all generation functions to raise if called.
- Monkeypatch baseline/candidate compile and scoring helpers to return
  deterministic signatures/scores.
- Invoke:

```bash
debug solve node-set-split -f fn_test --class gpr --ig 40 \
  --target-reg r30 --var holder \
  --resume-summary <summary> --json
```

Expected:

- `resume_mode == "manifest"`,
- generator fake was not called,
- compile labels include `baseline` and retained candidate IDs,
- candidate IDs in output match manifest order,
- at least one candidate is scored or realized according to the fake.

### Test: Coupled Resume Manifest Scores Without Regeneration

Name:

```python
test_solve_node_set_split_coupled_resume_manifest_preserves_requests_without_regeneration
```

Shape:

- Create a coupled summary plus manifest containing at least two
  `coupled_requests`.
- Monkeypatch `generate_coupled_node_set_split_patches`,
  `generate_node_set_split_patches`, and
  `generate_node_set_introduce_binding_patches` to fail if called.
- Monkeypatch compile/signature/scoring helpers to score one retained
  candidate.
- Invoke with `--resume-summary <summary> --coupled --json`.

Expected:

- `resume_mode == "manifest"`,
- generator fakes were not called,
- output keeps `coupled_requests`,
- candidate IDs and touched ranges match the manifest,
- retained candidate is compiled/scored.

### Test: Old Summaries Still Regenerate

Keep/update:

```python
test_solve_node_set_split_resume_summary_regenerates_without_manifest
```

Expected:

- `resume_mode == "regenerated-no-manifest"`,
- generation still runs,
- behavior stays compatible with existing summaries.

### Test: Budget Exhaustion After Objective Retains Candidate

Name:

```python
test_solve_node_set_split_budget_exhausted_after_objective_keeps_manifest_resume
```

Shape:

- Fake candidate compile returns a realized objective.
- Advance fake time so budget expires before checkdiff scoring.

Expected:

- output includes a scored row with `status="budget-exhausted"` or equivalent
  objective metadata,
- retained source path exists,
- manifest exists,
- resume command exists.
- a follow-up resume treats that candidate as pending and scores it.

### Test: Retain-Generated Without Output Writes Default Summary

Name:

```python
test_solve_node_set_split_retain_generated_budget_exhaustion_uses_default_summary_path
```

Shape:

- Fake generation returns candidate patches.
- Invoke with `--budget 0 --retain-generated --json` and no `--output`.

Expected:

- exit 4,
- payload includes `output`, `manifest_path`, and `pending_candidates`,
- both output and manifest files exist,
- `stop_condition.resume_command` points at the default summary path.

### Test: Manifest Hash Mismatch Fails Fast

Name:

```python
test_solve_node_set_split_resume_manifest_rejects_modified_candidate_source
```

Shape:

- Create a summary/manifest pair, then modify one retained candidate source.
- Invoke with `--resume-summary <summary> --json`.

Expected:

- exit 2,
- output or stderr names the hash mismatch,
- no compile/scoring helper is called.

## Command-Level Smoke Checks

Run focused tests:

```bash
python -m pytest tools/melee-agent/tests/search/solver/test_cli_solve.py \
  -k "node_set_split and (budget or resume or max_candidates)"
```

Run adjacent solver tests:

```bash
python -m pytest tools/melee-agent/tests/search/solver/test_solve.py
```

Syntax check edited modules:

```bash
python -m py_compile \
  tools/melee-agent/src/cli/debug/__init__.py \
  tools/melee-agent/src/mwcc_debug/node_set_split.py
```

CLI help smoke:

```bash
melee-agent debug solve node-set-split --help | \
  rg -- "--resume-summary|--retain-generated|--max-candidates"
```

Optional live smoke if the issue artifacts are available:

```bash
/opt/homebrew/bin/melee-agent debug solve node-set-split \
  -f mnDiagram_DrawCellNumber \
  --class fpr \
  --node-set-delta build/diagnostics/mndiagram_958_rerun/draw_solve_coloring_live.json \
  --source-file src/melee/mn/mndiagram.c \
  --force-phys '32:28,37:26,46:26' \
  --coupled \
  --max-candidates 2 \
  --budget 1 \
  --timeout 1 \
  --retain-generated \
  --output build/diagnostics/issue_959_smoke/node_set_split.json \
  --json
```

Inspect:

```bash
jq '.manifest_path, .pending_count, .stop_condition.resume_command' \
  build/diagnostics/issue_959_smoke/node_set_split.json
```

Then resume:

```bash
/opt/homebrew/bin/melee-agent debug solve node-set-split \
  --resume-summary build/diagnostics/issue_959_smoke/node_set_split.json \
  --budget 30 \
  --timeout 30 \
  --json
```

## Guardrails

- Before editing, run:

```bash
git -C /Users/mike/code/melee diff -- tools/melee-agent/src/cli/debug/__init__.py
```

- Preserve unrelated dirty hunks in `tools/melee-agent/src/cli/debug/__init__.py`.
- Keep edits narrow; do not run autoformatters over the large CLI file.
- Do not edit `src/melee/` or matching source.
- Do not resolve issue #959 until the fix is implemented, verified, committed,
  and the live/smoke checks prove the root cause is addressed.
- Do not add a new top-level command or a new raw API workflow.
- Manifest source files must be written under build/diagnostic/cache locations,
  not into the source tree.
- Hash-check manifest source files on resume to catch stale or edited retained
  candidates.
- Keep the first implementation focused on complete `CandidatePatch` objects
  returned to the CLI. Do not refactor coupled generation internals unless a
  focused regression shows complete candidates are discarded inside the
  generator.

## Acceptance Criteria

- A budget-exhausted node-set run with generated candidates produces a summary
  and manifest that list pending generated sources.
- The summary includes a copyable resume command for pending budget-exhausted
  work.
- `--resume-summary` with a manifest scores retained candidates without
  regenerating.
- Single-IG `--max-candidates N` bounds generation as well as scoring.
- Existing no-manifest resume behavior remains compatible.
- Focused pytest, syntax checks, and CLI help smoke pass.
