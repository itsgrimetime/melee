# Harvest Allocator Force-Vector Verify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve #458 by having allocator harvest rows auto-verify runnable force vectors and preserve diagnostic match evidence.

**Architecture:** `debug target match-iter-first` learns an `--force-vector auto` value that resolves to the derived target vector. `src.harvest` requests that mode and classifies the returned `force_vector_verify` payload before falling back to the existing allocator blocker mapping.

**Tech Stack:** Python 3.11, Typer CLI command adapters, pytest regression tests.

---

Spec: `docs/superpowers/specs/2026-06-06-harvest-allocator-force-vector-verify-design.md`
Issue: #458

## Files

- Modify: `tools/melee-agent/src/cli/debug.py`
- Modify: `tools/melee-agent/src/harvest.py`
- Modify: `tools/melee-agent/tests/test_match_iter_first.py`
- Modify: `tools/melee-agent/tests/test_harvest.py`

## Task 1 - Red tests

- [ ] Add `test_match_iter_first_force_vector_auto_uses_derived_vector` in
  `tools/melee-agent/tests/test_match_iter_first.py`. Construct the existing
  match-iter vector helper or monkeypatch the force-vector runner so passing
  `--force-vector auto` proves the command uses the derived vector instead of
  parsing `auto` as a literal force-vector entry.
- [ ] Update `test_allocator_pcdump_triage_builds_match_iter_first_command` in
  `tools/melee-agent/tests/test_harvest.py` so the expected command includes
  `--force-vector auto` before `--json`.
- [ ] Add `test_allocator_pcdump_triage_records_force_vector_diagnostic_match`
  with a payload whose `force_vector_verify.union.match` is true. Assert
  `status == "diagnostic_match"`, blocker
  `allocator-force-vector-match`, and details include
  `force_vector_matched_probes`.
- [ ] Add
  `test_allocator_pcdump_triage_records_singleton_force_vector_diagnostic_match`
  with union no-match and one singleton match.
- [ ] Add
  `test_allocator_pcdump_triage_records_force_vector_no_match_evidence` with
  `force_vector_verify.ran=true`, union no-match, and no matching diagnostic
  probes. Assert `status == "no_match"` and blocker
  `allocator-force-vector-no-match`.
- [ ] Add a summarizer regression that a `diagnostic_match` row is not included
  in `negative_evidence_functions`.

Run the targeted tests and confirm they fail for the expected missing behavior:

```bash
PYTEST_ADDOPTS=--no-cov python -m pytest \
  tools/melee-agent/tests/test_match_iter_first.py::test_match_iter_first_force_vector_auto_uses_derived_vector \
  tools/melee-agent/tests/test_harvest.py::test_allocator_pcdump_triage_builds_match_iter_first_command \
  tools/melee-agent/tests/test_harvest.py::test_allocator_pcdump_triage_records_force_vector_diagnostic_match \
  tools/melee-agent/tests/test_harvest.py::test_allocator_pcdump_triage_records_singleton_force_vector_diagnostic_match \
  tools/melee-agent/tests/test_harvest.py::test_allocator_pcdump_triage_records_force_vector_no_match_evidence \
  tools/melee-agent/tests/test_harvest.py::test_summarize_harvest_ledgers_keeps_allocator_diagnostic_matches_out_of_negative_evidence \
  -q
```

## Task 2 - Debug auto force-vector

- [ ] In `tools/melee-agent/src/cli/debug.py`, after `target_vector` is built,
  treat `force_vector == "auto"` as `target_vector["force_vector"]`.
- [ ] If the derived vector is empty, emit the existing `force_vector_result`
  shape with `ran=false` and a clear reason instead of calling
  `_parse_force_vector`.
- [ ] Keep explicit `--force-vector <csv>` behavior unchanged.
- [ ] Run the targeted `test_match_iter_first` regression and the existing
  force-vector tests around `_run_force_vector_auto_verify`.

## Task 3 - Harvest classification

- [ ] Add force-vector verification blocker constants in
  `tools/melee-agent/src/harvest.py`.
- [ ] Add force-vector verification fields to
  `ALLOCATOR_PCDUMP_TRIAGE_DETAIL_FIELDS`.
- [ ] Change `_allocator_pcdump_triage_command()` to pass
  `--force-vector auto`.
- [ ] Add helper logic to collect matching probes from
  `force_vector_verify.union` and `force_vector_verify.probes`.
- [ ] Do not rely only on top-level `force_vector_match`; singleton and prefix
  probes can match even when the union does not.
- [ ] Classify `force_vector_verify.ran=true` before the existing
  `needs-move` generic blocker path.
- [ ] Run the targeted harvest regressions.

## Task 4 - Verification and completion

- [ ] Run focused suites:

```bash
PYTEST_ADDOPTS=--no-cov python -m pytest \
  tools/melee-agent/tests/test_harvest.py \
  tools/melee-agent/tests/test_match_iter_first.py \
  -q
```

- [ ] Run compile and CLI smokes:

```bash
python -m py_compile tools/melee-agent/src/harvest.py tools/melee-agent/src/cli/debug.py
python -m src.cli harvest --help
python -m src.cli debug target match-iter-first --help
git diff --check
```

- [ ] Ask an independent Codex subagent to review the spec/plan and final diff.
- [ ] Stage only the spec, plan, debug code, harvest code, and tests.
- [ ] Commit the feature and resolve #458 with the commit hash.
- [ ] Refresh the editable `/opt/homebrew/bin/melee-agent` install from
  `/Users/mike/code/melee/tools/melee-agent`.
