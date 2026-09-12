# Issue 888: Expression-Preserving Structural Repair Implementation Plan

## Goal

Extend the existing `callarg_local_structural_repair` transform family so it
can continue from the fresh `digitf` frontier
`m04_digitf_local_callarg.c`, generate expression-preserving structural probes,
and report a precise terminal summary when no candidate crosses
`normalized_diff_lines < 30`.

This is a planning artifact only. Do not implement production changes during
this planning pass.

## Constraints

- Work in `/Users/mike/code/melee`.
- Do not edit `src/melee/mn/mndiagram.c` or other production code during this
  planning pass.
- Preserve unrelated dirty files:
  - `tools/melee-agent/src/cli/debug/__init__.py`
  - `tools/melee-agent/src/cli/scratch/__init__.py`
  - `tools/melee-agent/src/cli/sync/production.py`
  - `tools/melee-agent/src/search/solver/solve.py`
  - `tools/melee-agent/tests/search/solver/test_solve.py`
  - `tools/melee-agent/tests/test_scratch.py`
  - `docs/matching-tooling-postmortem-2026-06-15.md`
- Do not stage, commit, resolve issues, refresh installs, or touch
  `/Users/mike/.config/decomp-me`.
- Use subagent-driven development when ready to implement:
  - one implementation subagent for generator changes;
  - one implementation subagent for validation-summary/reporting changes;
  - main agent performs review, smoke checks, and final integration.

## Current Frontier

Important artifact facts:

- `m04_digitf_local_callarg.c`
  - raw `target_score=5/6`;
  - `expression_score=6/6`;
  - false positives `0`;
  - `normalized_diff_lines=30`;
  - `opcode_similarity=0.8092485549132948`;
  - remaining raw miss: baseline virtual 33 expected `f26`, raw virtual actual
    `f31`; expression identity still correctly matches `f26`.
- Existing generated callarg-local probes:
  - simple product/count movement keeps 6/6 expression but stays at 30 or 32;
  - block-scoped local regresses to 4/6 with one false-positive virtual-ID hit;
  - an old demotion probe failed pcdump function discovery, and #887 fixed the
    declaration placement for future runs.
- Manual loop-local probes:
  - assignment before load: 4/6 expression, 30 lines;
  - assignment after load: 4/6 expression, 30 lines;
  - assignment after `HSD_JObjAddAnimAll`: 4/6 expression, 18 lines.
- Coloring-register steering probes:
  - many retain raw 5/6 and expression 6/6;
  - observed expression-preserving candidates remain at 30 lines.

Root cause: the existing family has the right home but not enough fresh
`digitf` source grammar. It truncates to four anchors and misses the systematic
call-segment schedule and handoff probes needed to either find a sub-30 6/6
candidate or prove a terminal ceiling.

## Selected Approach

Use the existing transform-corpus path:

```text
debug search plan-transforms
  -> callarg_local_structural_repair
  -> debug target score-source validation
  -> validation_summary terminal or retained-candidate report
```

Do not add a new command. Do not change score semantics.

## Implementation Tasks

### 1. Add generator regression tests first

Modify:

```text
tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py
tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py
```

Add or extend tests around `_callarg_fresh_existing_structural_source`.

Required assertions:

- Generated strategies include:
  - `fresh-local-decl-demote-to-loop` with
    `digit_assignment_schedule == "before-load"`; this is the before-load
    schedule after #887 and should not be duplicated as a separate materialized
    probe with identical source text
  - `fresh-local-call-schedule-after-load`
  - `fresh-local-call-schedule-after-add`
  - `fresh-local-callarg-handoff-top`
  - `fresh-local-callarg-handoff-block`
- Existing strategies still include:
  - `continue-existing-fresh-callarg-local`
  - `fresh-local-product-count-order-swap`
  - `fresh-local-decl-demote-to-loop`
  - `fresh-local-block-scope-equivalent`
- With `max_per_family=12`, more than four callarg-local probes can
  materialize.
- `fresh-local-decl-demote-to-loop` keeps `f32 digitf;` at the top of the loop
  body, before `digit = mn_GetDigitAt(...)`.
- The `after-add` strategy places:

```c
HSD_JObjAddAnimAll(...);
digitf = (f32) digit;
HSD_JObjReqAnimAll(jobj, digitf);
```

- Handoff strategies keep the early `digitf = (f32) digit;` assignment and pass
  a second local to `HSD_JObjReqAnimAll`.
- Handoff locals are C89-safe:
  - `fresh-local-callarg-handoff-top` declares `digit_call_fpr` in a
    declaration-safe top-level region.
  - `fresh-local-callarg-handoff-block` declares `digit_call_fpr` at the top of
    the injected block before assignments or calls.
- Every generated callarg-local candidate contains exactly one
  `HSD_JObjReqAnimAll` call.
- Unsafe shapes produce no probes:
  - `sink(&digitf);`
  - duplicate `digitf = (f32) digit;`
  - duplicate `HSD_JObjReqAnimAll`
  - preprocessor directive inside the body
  - `digitf` used after the loop for demotion/block strategies
  - `digit_call_fpr` name collision

Expected pre-change failures:

- strategy names missing;
- only four anchors returned;
- no handoff variants.

### 2. Implement fresh-digitf generator changes

Modify:

```text
tools/melee-agent/src/search/directed/transform_corpus/register_steering.py
```

Implementation notes:

- Keep the existing dataclass and matcher. Add helper functions rather than a
  second matcher.
- In the `fresh-existing` branch, generate schedule variants by replacing only
  the loop-local segment from the fresh declaration through the request call.
- Reuse `_replace_validated_span` through the existing
  `steer_callarg_local_preserving_structural_repair` mutator.
- Replace the current `return anchors[:4]` with the full bounded list, or use a
  higher explicit cap such as 12. The orchestrator already has
  `max_per_family`; prefer returning all safe anchors and relying on that
  budget.
- Add payload fields:
  - `strategy`
  - `call_arg_local`
  - `call_arg_operand`
  - `call_arg_local_kind`
  - `uses_fresh_local`
  - `preserves_existing_callarg_local`
  - `digit_assignment_schedule`
  - `handoff_local` when applicable
  - `source_regions`
- Add skipped-strategy diagnostics where practical:
  - `handoff-local-name-collision`
  - `call-segment-schedule-unavailable`
  - `unsafe-intervening-callarg-span`

Do not touch `registry.py` or `mutators.py` unless tests prove metadata or
dispatch is missing.

### 3. Add validation-summary regression tests

Modify:

```text
tools/melee-agent/tests/test_source_transform_catalog.py
```

Add tests for `_summarize_transform_validations`:

- `test_callarg_local_summary_reports_sub30_success`
  - synthetic result: family `callarg_local_structural_repair`,
    `target_score.matched=5`, `expression_score.matched=6`,
    `expression_score.targeted=6`,
    `false_positive_virtual_id_hit_count=0`,
    `structural_guard.normalized_diff_lines=28`;
  - assert `callarg_local_frontier_summary.stop_condition_met is True`;
  - assert terminal blockers do not include structural ceiling.
- `test_callarg_local_summary_reports_structural_ceiling`
  - one 6/6 result at 30 lines;
  - one 4/6 result at 18 lines;
  - assert blockers include:
    - `structural-ceiling-with-protected-anchors`
    - `sub30-candidates-lost-protected-anchors`
    - `inline-boundary-opcode-drift`
- `test_callarg_local_summary_reports_raw_target_false_progress`
  - raw `target_score.matched=5`;
  - expression `matched=4` or false positives `1`;
  - assert `raw-target-progress-expression-regressed`.
- `test_callarg_local_summary_ranks_expression_before_raw_target`
  - 5/6 raw plus 4/6 expression must rank below 5/6 raw plus 6/6 expression.

### 4. Implement validation-summary reporting

Modify:

```text
tools/melee-agent/src/search/cli/__init__.py
```

Add small helpers near existing validation helpers:

- `_validation_normalized_diff_lines(result)`
- `_validation_opcode_similarity(result)`
- `_validation_expression_preserved(result, min_targeted=6)`
- `_validation_target_matched_at_least(result, minimum=5)`
- `_validation_callarg_local_frontier_summary(probe_payloads, validation_results)`

The summary should:

- inspect only `callarg_local_structural_repair` results;
- derive the strategy from the matching probe payload when available;
- report `best_expression_preserving`;
- report `best_structural`;
- report `raw_target_false_progress`;
- set `stop_condition_met` for the issue stop condition:

```text
expression 6/6
false_positive_virtual_id_hit_count == 0
target_score.matched >= 5
normalized_diff_lines < 30
```

- append terminal blockers to the existing `terminal_blockers` list without
  removing current blocker names.

### 5. Update catalog notes

Modify only if the implementation adds new strategy vocabulary:

```text
tools/melee-agent/src/mwcc_debug/source_transform_catalog.py
```

Update the existing `callarg_local_structural_repair` entry to mention:

- fresh-`digitf` call-segment schedules;
- callarg handoff locals;
- expression-preserving structural summaries.

No capabilities regeneration is needed because no command or family id is being
added.

### 6. Independent review before smoke

After subagents implement the two code areas, the main agent should run an
independent Codex review over:

```text
tools/melee-agent/src/search/directed/transform_corpus/register_steering.py
tools/melee-agent/src/search/cli/__init__.py
tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py
tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py
tools/melee-agent/tests/test_source_transform_catalog.py
```

Review focus:

- exact-span safety;
- no unsafe source generation;
- expression-score preservation is not confused with raw virtual-ID hits;
- `max_per_family` controls probe count;
- no issue-state, ledger, install-refresh, staging, or production source
  edits.

## Focused Tests

Run focused tests from `/Users/mike/code/melee`:

```bash
PYTEST_ADDOPTS=--no-cov pytest \
  tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py \
  -k callarg_local_structural_repair \
  -q
```

```bash
PYTEST_ADDOPTS=--no-cov pytest \
  tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py \
  -k callarg_local_structural_repair \
  -q
```

```bash
PYTEST_ADDOPTS=--no-cov pytest \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -k "callarg_local or transform_validation_summary" \
  -q
```

Run the combined targeted set:

```bash
PYTEST_ADDOPTS=--no-cov pytest \
  tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q
```

## Real Artifact Smoke

Do not use `--record-ledger`.

Create the output directory first:

```bash
mkdir -p build/diagnostics/mndiagram_draw_888_fresh_digitf_structural_repair_main_tooling
```

Generate and validate fresh probes from the #888 source frontier. The source
frontier is a full-file artifact from the matcher worktree, so run the command
with cwd `/Users/mike/.codex/worktrees/eeff/melee` and import the current
tooling from `/Users/mike/code/melee/tools/melee-agent`. Running the same
full-file artifact from `/Users/mike/code/melee` stages it over a different
`mndiagram.c` layout and can fail with unrelated file-scope redeclarations.

```bash
PYTHONPATH=/Users/mike/code/melee/tools/melee-agent \
  python -m src.cli debug search plan-transforms \
  --function mnDiagram_DrawCellNumber \
  --unit melee/mn/mndiagram \
  --force-phys 1:33:26,1:35:26,1:40:28,1:41:29,1:42:29,1:43:29 \
  --source-file /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_886_manual_rowf_matrix/candidates/m04_digitf_local_callarg.c \
  --transform-family callarg_local_structural_repair \
  --max-per-family 16 \
  --write-probes build/diagnostics/mndiagram_draw_888_fresh_digitf_structural_repair_main_tooling/probes \
  --validate-command '/usr/bin/env PYTHONPATH=/Users/mike/code/melee/tools/melee-agent python -m src.cli debug target score-source {candidate_path} -f mnDiagram_DrawCellNumber --cflags-from src/melee/mn/mndiagram.c --target /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_883_product_hit_target_spec.json --expression-baseline /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_874_clean_baseline.pcdump.txt --expression-source /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_881_expression_interferer_secondgen/probes/product-col-offset-sink-owner.c --expression-reg-class fpr --checkdiff-guard --timeout 120 --json' \
  --validate-all \
  --json \
  > build/diagnostics/mndiagram_draw_888_fresh_digitf_structural_repair_main_tooling/plan_transforms_validated_timeout120.json
```

Inspect the stop condition:

```bash
jq '.validation_summary.callarg_local_frontier_summary' \
  build/diagnostics/mndiagram_draw_888_fresh_digitf_structural_repair_main_tooling/plan_transforms_validated_timeout120.json
```

Success is only:

```text
stop_condition_met == true
best_expression_preserving.expression_score.matched == 6
best_expression_preserving.expression_score.targeted == 6
best_expression_preserving.false_positive_virtual_id_hit_count == 0
best_expression_preserving.target_score.matched >= 5
best_expression_preserving.structural_guard.normalized_diff_lines < 30
```

Terminal completion is acceptable only when the summary reports:

- best expression-preserving candidate remains at `normalized_diff_lines >= 30`;
- best sub-30 candidate loses expression anchors or has false-positive
  virtual-ID hits;
- `inline-boundary-opcode-drift` includes classification, normalized lines,
  opcode similarity, line delta, and hunk count.

## Capability Audit Under Current Restrictions

Do not run `melee-agent capabilities search` while
`/Users/mike/.config/decomp-me` is off limits, because the command logs through
`StateDB`. For a read-only local discovery check, use implementation/code
inspection or call the pure helper without invoking the CLI:

```bash
PYTHONPATH=tools/melee-agent python -c 'from src.cli.capabilities import run_search; [print(c.name, "->", c.invoke) for c in run_search("callarg local protected expression structural repair")]'
```

If the `.config` restriction is lifted in a later implementation session, run
the normal audit:

```bash
melee-agent capabilities search "callarg local protected expression structural repair"
```

## Final Verification

Before handing the implementation back:

- `git status --short` shows only intentional tooling/test/docs changes plus
  the pre-existing unrelated dirty files.
- No files under `/Users/mike/.config/decomp-me` were touched.
- No production decomp source under `src/melee/` was edited.
- No issue was resolved.
- Nothing was staged or committed unless a later implementation request
  explicitly asks for that.

When the feature is eventually committed, include these plan/spec files in the
feature commit:

```text
docs/superpowers/specs/2026-06-21-issue-888-expression-preserving-structural-repair-design.md
docs/superpowers/plans/issue-888-expression-preserving-structural-repair.md
```
