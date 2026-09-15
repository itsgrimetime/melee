# Data-Symbol Blocker Rebucketing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve #459 by keeping non-candidate data-symbol blocker rows out of executable current-tools harvest filters.

**Architecture:** Taxonomy generation performs a cheap no-compile name-magic preflight for data-symbol rows and records stable blocker facets. Harvest preview/selection consumes those facets without running compiles.

**Tech Stack:** Python 3.11, TSV/JSONL taxonomy artifacts, pytest.

---

Spec: `docs/superpowers/specs/2026-06-06-data-symbol-blocker-rebucket-design.md`
Issue: #459

## Files

- Modify: `tools/function_taxonomy_inventory.py`
- Modify: `tools/melee-agent/src/harvest.py`
- Modify: `tools/melee-agent/tests/test_function_taxonomy_inventory.py`
- Modify: `tools/melee-agent/tests/test_harvest.py`

## Task 1 - Red tests

- [x] Add a taxonomy test that a zero-probe
  `no-name-magic-candidate` preflight changes
  `source_actionability` to
  `blocked-data-symbol-no-name-magic-candidate`, writes name-magic fields, and
  writes `queues/data-symbol-relocation.no-name-magic-candidate.tsv`.
- [x] In the same test, include a data-symbol row with one generated probe and
  assert it remains `current-tools-data-symbol`.
- [x] Add a parameterized taxonomy test for zero-probe
  `ambiguous-sdata2-value` and `sdata2-pool-order-dependent`.
- [x] Add a harvest test that preview facets include `name_magic_blocker`.
- [x] Add a harvest test that blocked data-symbol source-actionability rows do
  not select `name-magic-source-declarations`.

Run:

```bash
PYTEST_ADDOPTS=--no-cov python -m pytest \
  tools/melee-agent/tests/test_function_taxonomy_inventory.py::test_data_symbol_name_magic_preflight_rebuckets_non_candidate_rows \
  tools/melee-agent/tests/test_function_taxonomy_inventory.py::test_data_symbol_name_magic_preflight_rebuckets_sdata2_blockers \
  tools/melee-agent/tests/test_harvest.py::test_preview_harvest_queue_facets_name_magic_blocker \
  tools/melee-agent/tests/test_harvest.py::test_blocked_data_symbol_rows_do_not_select_name_magic_harness \
  -q
```

## Task 2 - Taxonomy preflight

- [x] Add `NameMagicPreflightRunner` and a default runner that invokes
  `melee-agent debug mutate name-magic-source-declarations` with
  `--no-compile-probes --no-score-match-percent --json`.
- [x] Thread the runner through `classify_candidate()` and `generate_inventory()`.
- [x] Add helper logic to attach preflight fields and rebucket the three stable
  zero-probe blockers.
- [x] Extend CSV/queue fields with the name-magic preflight columns.
- [x] Write physical blocker subqueues for data-symbol rows.

## Task 3 - Harvest preview and selection

- [x] Add `name_magic_blocker` to preview facet fields.
- [x] Add the three blocked data-symbol source-actionability values to a harvest
  skip set.
- [x] Make data-symbol harness selection return `None` for those blocked rows.
- [x] Ensure composed layer auto-selection does not re-add the name-magic
  harness for blocked rows.

## Task 4 - Verification and completion

- [x] Run:

```bash
PYTEST_ADDOPTS=--no-cov python -m pytest \
  tools/melee-agent/tests/test_function_taxonomy_inventory.py \
  tools/melee-agent/tests/test_harvest.py \
  -q
```

- [x] Run:

```bash
python -m py_compile tools/function_taxonomy_inventory.py tools/melee-agent/src/harvest.py
PYTHONPATH=tools/melee-agent python -m src.cli harvest --preview data-symbol-relocation --help
git diff --check
```

- [x] Request independent Codex review of the diff.
- [x] Stage only the #459 spec, plan, taxonomy code, harvest code, and tests.
- [x] Commit and resolve #459 with the commit hash.
- [x] Refresh the editable `melee-agent` install.
