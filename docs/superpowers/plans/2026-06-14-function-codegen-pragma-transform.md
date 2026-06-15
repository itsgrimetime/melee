# Function Codegen Pragma Transform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add guarded executable `function_codegen_pragma_shape` transform-corpus probes for the mined `#pragma push` / `#pragma dont_inline on` / `#pragma pop` function wrapper shape.

**Architecture:** Reuse `TransformProbe`, `Anchor`, and `apply_mutator`. Add strict full-source anchors in `transform_corpus.py`, exact-span mutators in `mutators.py`, and catalog/docs drift updates.

**Tech Stack:** Python 3.11, pytest, existing `src.search.directed` transform-corpus modules.

---

### Task 1: Red Tests

- [ ] Update `test_transform_corpus.py` to expect `function_codegen_pragma_shape` mutators `add_dont_inline_pragma_pair` and `remove_dont_inline_pragma_pair`.
- [ ] Add positive insertion and removal fixtures.
- [ ] Add rejection fixtures for preprocessor, existing pragma adjacency, labels, case/default, and oversized bodies.
- [ ] Add direct mutator span-validation tests in `test_mutators.py`.
- [ ] Update catalog count tests from 81 to 83 and expect both new keys in `DIRECTED_MUTATOR_KEYS`.
- [ ] Run focused tests and confirm failures are missing mutator keys/anchors.

### Task 2: Implementation

- [ ] Add exact-span mutators for adding/removing the wrapper.
- [ ] Register both mutator keys.
- [ ] Update family metadata and generic cluster membership.
- [ ] Add `_iter_function_codegen_pragma_anchors` with strict adjacency and body guards.
- [ ] Add the generator to `_iter_full_source_anchors`.
- [ ] Update source-transform catalog notes and docs.

### Task 3: Verification

- [ ] Run focused transform-corpus/mutator/catalog tests.
- [ ] Run `test_cli_smoke.py` or a narrower plan-transforms CLI smoke.
- [ ] Run `compileall` for modified modules and `git diff --check`.
- [ ] Commit, refresh editable `melee-agent`, run installed CLI smoke, resolve #694 with the commit hash.
