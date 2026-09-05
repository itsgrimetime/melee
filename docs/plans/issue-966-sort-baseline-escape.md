# Issue 966 Plan: Sort Baseline Escape

1. Add tests that demonstrate Sort residual Case-C evidence can generate baseline-escape candidates without an expression-interferer JSON.
2. Add tests that classify `target_score.virtuals` progress and terminal no-progress for Sort.
3. Add retained-frontier triage coverage for `no-post-ceiling-sort-source-family/current-source-shape-ceiling`.
4. Extend `post_ceiling_baseline_escape.py` with function-specific evidence profiles, target-score classification, Sort candidate families, and Sort validation hints.
5. Extend the CLI with optional expression evidence and repeatable supplemental `--evidence-json` artifacts.
6. Verify with focused pytest, py_compile, CLI help, and a live Sort artifact smoke that writes candidate `.c` probes.
7. Refresh the editable `melee-agent` install from `/Users/mike/code/melee`, resolve issue #966, and commit the spec, plan, tests, and implementation.
