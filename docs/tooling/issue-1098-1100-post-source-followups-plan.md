# Issue 1098-1100 Post-Source Followups Plan

## Scope

Issues #1098, #1099, and #1100 are follow-ups to the post-source-ceiling axis
diagnostics added for #1096 and #1097.

- #1100 is shared across Sort and Draw: post-source-ceiling-axis emitted a
  `score-force-phys` command shape that the CLI does not accept.
- #1098 is Sort-specific: retained coalesce-search probes were scored through
  function-only transfer, so full-TU retained context could be lost before
  `mnDiagram_SortNamesByKOs` was emitted.
- #1099 is Draw-specific: first-divergence found an FPR Case C pcode-only
  constant load (`lfd f46,@192(r0)`) with no source line, local, or candidate
  span, leaving no source-actionable repair lane.

## Fix Plan

1. Replace invalid force-phys hints.
   - Keep executable `debug inspect first-divergence` hints for retained
     pcdumps.
   - Derive force-phys CSV from retained anchors.
   - When enough evidence exists, emit
     `debug permute setup-simplify-order-scorer --scorer-mode force-phys`
     instead of a fabricated `score-force-phys --source --pcdump` command.

2. Preserve retained full-TU coalesce probes.
   - Detect out-of-repo retained `--source-file` inputs.
   - Retain generated probes under the repo cache before compiling.
   - Compile retained probes with the live unit as `--unit-source` and mark
     match-percent scoring as full-unit.
   - If all variants still fail, emit a structured terminal summary naming
     the target-function-missing failure while preserving retained source and
     error evidence.

3. Add a terminal Draw FPR constant-load lane.
   - Allow post-source-ceiling-axis to consume first-divergence and
     simplify-order JSON.
   - Recognize FPR Case C `fpr-temp` loads like `lfd f46,@192(r0)`.
   - If no source owner or span exists, emit a terminal blocker
     (`pcode-only-fpr-constant-load-owner-unmapped`) with preserved
     IG32/IG37/IG46 anchors and bounded-probe evidence.

## Regression Tests

- `test_post_source_ceiling_axis.py`
  - No diagnostic emits invalid `score-force-phys --source --pcdump`.
  - Force-phys setup hints include baseline pcdump, class, and force map.
  - Draw FPR pcode constant-load first-divergence produces a terminal repair
    lane with retained expression anchors.

- `test_coalesce_search.py`
  - Retained out-of-repo full-TU coalesce probes compile through a retained
    repo-cache source and the live unit source.
  - All missing-target-function failures produce a top-level terminal summary.

## Verification

Run focused tests first:

```bash
python -m pytest tools/melee-agent/tests/test_post_source_ceiling_axis.py
python -m pytest tools/melee-agent/tests/test_coalesce_search.py -k "retained_full_tu or all_missing_function"
python -m pytest tools/melee-agent/tests/test_debug_cli_help_golden.py
```

Then run command-level smoke checks for:

```bash
melee-agent debug search post-source-ceiling-axis --help
melee-agent debug coalesce-search --help
melee-agent debug permute setup-simplify-order-scorer --help
```
