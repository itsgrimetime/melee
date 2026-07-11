# Score-Source External Candidate Staging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let shared score-source verification score candidates retained outside the Melee repository without weakening score-source's repo-local source boundary.

**Architecture:** Keep the requested `ScoreSourceConfig.output_dir` as the durable candidate location. For each external candidate, create a short-lived copy beneath `<repo>/build/diagnostics/score_source_staging/`, pass only that copy to `debug target score-source`, then restore result-row source fields to the durable external file and remove the staging directory on success, failure, timeout, or interruption.

**Tech Stack:** Python 3.11, pathlib, tempfile/contextlib, pytest.

## Global Constraints

- `debug target score-source` must continue rejecting C source paths outside the active Melee repository.
- An explicit external `--score-output-dir` remains the durable location for generated candidate C sources.
- Temporary verification copies must live under `<repo>/build/diagnostics/score_source_staging/` and must be removed after each scoring attempt.
- Returned `source_file`, `source_retained`, and `c_file` fields must identify the durable candidate, not a deleted staging copy.
- Existing repo-local candidates must be passed to score-source unchanged.
- Existing timeout, interruption, pcdump retention, blocker, and terminal-safety behavior must remain unchanged.

---

### Task 1: Stage external retained candidates for score-source

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/source_candidate_scoring.py`
- Modify: `tools/melee-agent/tests/test_candidate_verify.py`
- Verify: `tools/melee-agent/tests/test_suggest_inlines_cli.py`

**Interfaces:**
- Consumes: `score_retained_source_rows(rows, config, runner=...)` and `build_score_source_command(candidate_path, config, ...)`.
- Produces: a private context manager that yields the original path when it is within `config.repo_root`, otherwise yields a temporary repo-local `.c` copy and guarantees cleanup.

- [ ] **Step 1: Write a failing external-output regression**

Add a test to `test_candidate_verify.py` with `repo_root=tmp_path / "melee"` and `output_dir=tmp_path / "external"`. Its fake runner must assert that the command's score-source C path resolves under `repo_root`, contains the external candidate text, and is not the durable external path. After scoring, assert the temporary path no longer exists, the external candidate remains, and `source_file`, `source_retained`, and `c_file` all equal the external candidate path. Also retain the existing test coverage proving repo-local paths are passed unchanged.

- [ ] **Step 2: Run the regression and verify RED**

Run: `PYTHONPATH=tools/melee-agent pytest -q --no-cov tools/melee-agent/tests/test_candidate_verify.py -k external`

Expected: FAIL because the score-source command currently receives the external candidate path directly.

- [ ] **Step 3: Implement transient repo-local staging**

Add a private context manager in `source_candidate_scoring.py` that resolves `candidate_path` and `config.repo_root`. If the candidate is inside the repository, yield it unchanged. Otherwise create `<repo>/build/diagnostics/score_source_staging/`, open a uniquely named temporary directory there, copy the candidate bytes to a sanitized `.c` filename, yield that path, and rely on the temporary-directory context for cleanup.

Wrap command construction and runner invocation in that context. Preserve the actual command used in `score_command`, but after merging score-source JSON explicitly set `source_file`, `source_retained`, and `c_file` back to the original durable path. Do not alter timeout/interruption rows, which already use the original candidate path.

- [ ] **Step 4: Run focused GREEN verification**

Run: `PYTHONPATH=tools/melee-agent pytest -q --no-cov tools/melee-agent/tests/test_candidate_verify.py -k 'external or retain_and_score'`

Expected: PASS with the external candidate staged/cleaned and the repo-local candidate path unchanged.

- [ ] **Step 5: Run broader regressions and hygiene checks**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q --no-cov tools/melee-agent/tests/test_candidate_verify.py
PYTHONPATH=tools/melee-agent pytest -q --no-cov tools/melee-agent/tests/test_suggest_inlines_cli.py
python -m compileall -q tools/melee-agent/src/mwcc_debug/source_candidate_scoring.py
git diff --check
```

Expected: both suites pass, compileall exits 0, and `git diff --check` is silent.

- [ ] **Step 6: Commit**

```bash
git add tools/melee-agent/src/mwcc_debug/source_candidate_scoring.py tools/melee-agent/tests/test_candidate_verify.py
git commit -m "fix: stage external score-source candidates"
```
