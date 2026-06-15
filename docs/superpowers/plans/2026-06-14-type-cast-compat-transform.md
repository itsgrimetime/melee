# Type And Cast Compatibility Transform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add guarded executable transform-corpus probes for pointer cast elision, callback cast elision, and vector alias type spelling.

**Architecture:** Reuse `TransformProbe`, `Anchor`, and exact-span mutators. Add local type/prototype parsing helpers in `transform_corpus.py`, three exact-span mutators in `mutators.py`, and catalog/docs drift updates.

**Tech Stack:** Python 3.11, pytest, existing `src.search.directed` transform-corpus modules.

---

### Task 1: Red Tests

- [x] Update metadata tests so `redundant_pointer_cast_elision`, `callback_cast_elision`, and `vector_alias_type_shape` expose concrete mutator keys.
- [x] Add direct exact-span mutator tests for `elide_redundant_pointer_cast`, `elide_callback_cast`, and `rewrite_vector_alias_type`.
- [x] Add positive transform-corpus fixtures for pointer call-argument cast elision, pointer assignment cast elision, callback call-argument cast elision, and vector alias local declaration rewriting.
- [x] Add rejection fixtures for varargs, missing prototypes, incompatible pointer expression types, volatile types, macro/preprocessor cases, address-taken functions, table initializers, non-identical vector layouts, vector alias parameter rewriting, local alias-name shadowing, comments/strings/preprocessor regions, and stale spans.
- [x] Update catalog count tests from 85 to 88 and directed concrete form count from 32 to 35.
- [x] Add a CLI smoke test for `plan-transforms --write-probes --json` that materializes all three new families from one fixture.
- [x] Run focused tests and confirm failures are missing mutators/anchors/catalog keys.

### Task 2: Implementation

- [x] Add exact-span mutators for the three keys.
- [x] Register all three mutator keys.
- [x] Update family metadata and generic cluster membership.
- [x] Add normalized local type helpers for pointer types and function-pointer signatures.
- [x] Add pointer cast anchors for call arguments and simple assignments.
- [x] Add callback cast anchors for call arguments with matching source-local function-pointer signatures.
- [x] Add vector alias anchors for source-local identical struct aliases in target function local declarations.
- [x] Add the generator to `_iter_full_source_anchors`.
- [x] Update source-transform catalog notes and docs.

### Task 3: Verification

- [x] Run focused transform-corpus/mutator/catalog/CLI tests.
- [x] Run `compileall` for modified modules and `git diff --check`.
- [x] Run command-level `plan-transforms --write-probes --json` smoke for a temp source.
- [x] Request independent review of the implementation diff and fix any blockers.
- [x] Commit, refresh editable `melee-agent`, run installed CLI smoke, resolve #692 with the commit hash.
