# Global Float Literal Transform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add guarded executable `global_float_literal_shape` transform-corpus probes for source-local floating literal/global constant swaps.

**Architecture:** Reuse `TransformProbe`, `Anchor`, and exact-span mutators. Add a small source-local floating constant analyzer in `transform_corpus.py`, register two strict mutator keys in `mutators.py`, and update catalog/docs drift checks.

**Tech Stack:** Python 3.11, pytest, existing `src.search.directed` transform-corpus modules.

---

### Task 1: Red Tests

- [ ] Update `test_transform_corpus.py` to expect `global_float_literal_shape` mutators `replace_float_literal_with_global_constant` and `replace_global_float_constant_with_literal`.
- [ ] Add positive f32 and f64 fixtures for inline literal to constant replacement.
- [ ] Add a positive fixture for constant reference to literal replacement.
- [ ] Add rejection fixtures for duplicate target-width equal values, suffix/type-width ambiguity, local constants, volatile declarations, hex floats, macro expressions, commented/string/disabled declarations, comment/string body literals, target-body parameter/top-level/nested local shadowing, static-local initializers, and address-taken symbol uses.
- [ ] Add direct mutator span-validation tests in `test_mutators.py`.
- [ ] Update catalog count tests from 83 to 85, directed concrete form count from 30 to 32, and expect both new keys in `DIRECTED_MUTATOR_KEYS`.
- [ ] Add a CLI smoke test for `plan-transforms --write-probes --json`.
- [ ] Run focused tests and confirm failures are missing mutator keys/anchors.

### Task 2: Implementation

- [ ] Add exact-span mutators for literal-to-symbol and symbol-to-literal replacements.
- [ ] Register both mutator keys.
- [ ] Update family metadata and generic cluster membership.
- [ ] Add source-local scalar floating constant parsing with type-width and target-width binary value proof.
- [ ] Add target-body literal anchors using blanked comments/strings, shadowing/static-initializer guards, and exact source spans.
- [ ] Add target-body symbol anchors for non-address-taken identifier uses with shadowing guards.
- [ ] Add the generator to `_iter_full_source_anchors`.
- [ ] Update source-transform catalog notes and docs.

### Task 3: Verification

- [ ] Run focused transform-corpus/mutator/catalog/CLI tests.
- [ ] Run `compileall` for modified modules and `git diff --check`.
- [ ] Run command-level `plan-transforms --write-probes --json` smoke for a temp source.
- [ ] Request independent review of the implementation diff and fix any blockers.
- [ ] Commit, refresh editable `melee-agent`, run installed CLI smoke, resolve #693 with the commit hash.
