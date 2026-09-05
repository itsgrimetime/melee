# Unused Trailing Parameter Transform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add guarded executable transform-corpus probes for unused trailing parameter add/remove call-contract variants.

**Architecture:** Reuse `Anchor` and `TransformProbe` with a new exact multi-edit mutator. Add conservative whole-source analysis in `transform_corpus.py` that only emits probes for static target functions whose local declarations and direct calls can all be updated safely. Mark these probes as full-unit source candidates and update scoring paths so prototype/caller edits are not dropped by target-function transfer.

**Tech Stack:** Python 3.11, pytest, existing `src.search.directed` transform-corpus modules.

---

### Task 1: Red Tests

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/search/directed/test_mutators.py`
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`

- [ ] Update metadata tests so `unused_trailing_parameter` exposes `("remove_unused_trailing_parameter", "add_unused_trailing_parameter")` and no longer says record-only.
- [ ] Add mutator tests that apply two or more exact edits and verify stale spans return `None`.
- [ ] Add positive corpus fixtures:
  - remove `static int helper(int value, int unused)` and update `static int helper(int value);` plus calls `helper(arg, 0)` to `helper(arg)`;
  - add `int unused` to `static int helper(int value)` and update `static int helper(int value);` plus calls `helper(arg)` to `helper(arg, 0)`.
- [ ] Add positive corpus fixtures with multiple caller functions, expression call sites (`return helper(x, 0) + 1;`), nested call arguments (`sink(helper(x, 0));`), two calls on one line, removing the sole parameter to `helper(void)`/`helper()`, and adding to `helper(void)` as `helper(int unused)`/`helper(0)`.
- [ ] Add rejection fixtures for non-static definitions, `extern` prototypes, used trailing parameters, varargs, mismatched prototypes, missing call updates, required header/cross-TU edits that are not self-contained in the candidate source, address-taking, function-pointer storage, macro/preprocessor references, target-name shadowing, an existing `unused` parameter when adding, comments/strings in edited argument lists, and non-call references.
- [ ] Add provenance assertions that `updated_call_sites` records caller, call span, old/new arity, and replacement text, and that `requires_full_unit_source` is true.
- [ ] Update catalog count tests from 88 to 90 and directed concrete form count from 35 to 37.
- [ ] Add CLI smoke coverage for `plan-transforms --write-probes --json` materializing one remove and one add candidate from static fixtures.
- [ ] Add scoring-path tests that prove generated full-unit probes pass `unit_source` to `compile_source_variant` and real-tree scoring applies the full candidate source rather than `transfer_candidate`.
- [ ] Run the focused tests and confirm failures are missing mutator keys, anchors, catalog keys, or CLI candidates.

### Task 2: Mutator

**Files:**
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Test: `tools/melee-agent/tests/search/directed/test_mutators.py`

- [ ] Add `_apply_exact_edits(anchor, source_text)` that reads `payload["edits"]` as `(start, end, span_text, replacement_text)` tuples, validates every span, rejects overlaps, and applies replacements in descending `start` order.
- [ ] Add `_remove_unused_trailing_parameter` and `_add_unused_trailing_parameter` as thin wrappers over `_apply_exact_edits`.
- [ ] Register both mutator keys in `_DISPATCH`.
- [ ] Run `PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/directed/test_mutators.py -q -k 'unused_trailing_parameter or exact_edits'`.

### Task 3: Analyzer

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Test: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`

- [ ] Update the `unused_trailing_parameter` family metadata and generic fallback cluster to use both mutator keys.
- [ ] Add helper records for parsed contract signatures, parameter spans, and call spans.
- [ ] Add parsing helpers that find a matching close parenthesis, split parameter/argument spans with existing top-level CSV splitting, and normalize parameter types with existing compatibility helpers.
- [ ] Add safety helpers that reject non-static/extern/varargs signatures, target preprocessor references, target-name macros, address-taking, function-pointer storage, local shadows, unparseable calls, and remaining non-call references.
- [ ] Add remove-anchor generation that updates the definition, all local prototypes, and all direct calls only when the final parameter is unused and every contract site has matching arity/type.
- [ ] Add add-anchor generation that updates the definition, all local prototypes, and all direct calls with `int unused` and `0`, rejecting when `unused` is already a target parameter name.
- [ ] Wire `_iter_unused_trailing_parameter_anchors` into `_iter_full_source_anchors`.
- [ ] Run `PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/directed/test_transform_corpus.py -q -k 'unused_trailing_parameter' --tb=short`.

### Task 4: Full-Unit Scoring Support

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_probe_adapter.py`
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Modify: `tools/melee-agent/src/mwcc_debug/diff_capture.py` if a helper is needed for explicit full-unit compile flags
- Test: `tools/melee-agent/tests/search/test_cli_smoke.py`

- [ ] Preserve `requires_full_unit_source` and `updated_call_sites` in `transform_probe_to_lifetime_probe()` provenance.
- [ ] Add a helper in `cli/debug/__init__.py` that checks a generated probe's provenance for `requires_full_unit_source`.
- [ ] Update generated transform-probe scoring in coalesce-search, select-order-search, lifetime-layout, and frame-transform-search so full-unit probes pass the resolved source unit path as `unit_source` to `compile_source_variant`.
- [ ] Update real-tree match-percent scoring to accept a `full_unit_source` flag and write the entire candidate source to the resolved unit path instead of calling `transfer_candidate` when the flag is true.
- [ ] Reject full-unit scoring with a clear failed-variant message when the source unit path cannot be resolved.
- [ ] Add tests that monkeypatch `compile_source_variant` or run a narrow CLI smoke to prove `unit_source` is used for full-unit transform probes.
- [ ] Add tests that exercise `_score_source_candidate_real_tree(..., full_unit_source=True)` and verify non-target edits are preserved in the applied source snapshot.

### Task 5: Catalog, Docs, And CLI

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `docs/source-transform-catalog.md`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`

- [ ] Register both directed mutator keys in `DIRECTED_MUTATOR_KEYS`.
- [ ] Update catalog notes so `unused_trailing_parameter` is described as guarded and executable.
- [ ] Update headline/concrete-form counts in docs/tests.
- [ ] Add CLI smoke tests that write candidate files for remove and add probes.
- [ ] Run `PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_source_transform_catalog.py tools/melee-agent/tests/search/test_cli_smoke.py -q -k 'unused_trailing_parameter or catalog'`.

### Task 6: Verification And Integration

**Files:**
- Review all files above.

- [ ] Run focused transform-corpus/mutator/catalog/CLI tests.
- [ ] Run `PYTHONPATH=tools/melee-agent python -m compileall -q tools/melee-agent/src/search/directed/transform_corpus.py tools/melee-agent/src/search/directed/mutators.py tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`.
- [ ] Run `git diff --check`.
- [ ] Run command-level `/opt/homebrew/bin/melee-agent debug search plan-transforms --write-probes --json` smoke checks for remove and add fixtures after refreshing the editable install.
- [ ] Run command-level generated-probe compile smoke for a full-unit probe, or the narrowest available mocked CLI test if a local pcdump/build fixture is unavailable.
- [ ] Request independent spec/code review and fix blockers.
- [ ] Commit the implementation and docs, refresh editable `melee-agent`, run installed CLI smoke, and resolve #695 with the commit hash.
