# Node-Set Split Bounded Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `debug solve node-set-split` a bounded, machine-readable probe for allocator live-range split investigations.

**Architecture:** Extend the existing `node_set_split` summary helper with stop-condition metadata, then add CLI options that bound candidate evaluation and clamp child process timeouts to the remaining global budget. Keep the source-shape generator and objective evaluator unchanged.

**Tech Stack:** Python 3.11, Typer, pytest, existing `mwcc_debug.node_set_split` and `cli.debug` helpers.

---

### Task 1: Summary Contract

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [x] **Step 1: Write the failing summary test**

Add `test_summarize_node_set_split_scores_reports_candidate_limit` with three generated `CandidatePatch` values and one evaluated wrong-register row. Assert `status == "exhausted"`, `stop_condition.kind == "candidate-limit"`, `evaluated_count == 1`, `checkdiff_scored_count == 0`, and `omitted_count == 2`.

- [x] **Step 2: Run the summary test**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_node_set_split.py::test_summarize_node_set_split_scores_reports_candidate_limit -q
```

Expected before implementation: failure because `summarize_node_set_split_scores` does not accept stop-condition fields.

- [x] **Step 3: Implement summary fields**

Add optional `stop_reason`, `candidate_limit`, `budget_seconds`, and `elapsed_seconds` parameters. Keep primary `status` as `improved`, `exhausted`, or `blocked`; add `stop_condition`, `evaluated_count`, `checkdiff_scored_count`, `omitted_count`, `exhaustive`, and `next_steps`.

- [x] **Step 4: Re-run the summary test**

Run the same pytest command and verify it passes.

### Task 2: CLI Bounds

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/search/solver/test_cli_solve.py`

- [x] **Step 1: Write failing CLI tests**

Add tests for `--budget 0`, `--max-candidates 1`, and an improving first candidate that remains `status: "improved"` even when `stop_condition.kind == "candidate-limit"`.

- [x] **Step 2: Run the CLI tests**

Run:

```bash
python -m pytest tools/melee-agent/tests/search/solver/test_cli_solve.py::test_solve_node_set_split_budget_zero_skips_candidate_work tools/melee-agent/tests/search/solver/test_cli_solve.py::test_solve_node_set_split_max_candidates_stops_after_cap tools/melee-agent/tests/search/solver/test_cli_solve.py::test_solve_node_set_split_improved_status_wins_before_candidate_cap -q
```

Expected before implementation: Typer rejects `--budget` and `--max-candidates`.

- [x] **Step 3: Implement CLI options and budget clamps**

Add `--max-candidates` with default `16` and `0` as unlimited. Add optional
`--budget`. Validate non-negative values. Before each baseline/candidate/score
child call, compute the remaining wall-clock budget and pass
`min(--timeout, remaining_budget)` as that child timeout. Stop before starting a
child when less than a small meaningful time slice remains.

- [x] **Step 4: Re-run CLI tests**

Run the same pytest command and verify it passes.

### Task 3: Verification

**Files:**
- No additional source files.

- [x] **Step 1: Run focused regression tests**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_node_set_split.py -q
python -m pytest tools/melee-agent/tests/search/solver/test_cli_solve.py -k 'node_set_split' -q
python -m py_compile tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/src/mwcc_debug/node_set_split.py
```

Expected: all selected tests pass and both Python files compile.

- [x] **Step 2: Run live smoke checks**

Run a bounded real probe against `mnDiagram_80242C0C` with `--max-read-sites 0`,
`--max-candidates 1`, and a short budget. Confirm it returns structured JSON
instead of running unbounded. Run `debug inspect trace-copy` for the issue's
`r76 -> r47` pair and confirm that command reports `copy-not-found`.
