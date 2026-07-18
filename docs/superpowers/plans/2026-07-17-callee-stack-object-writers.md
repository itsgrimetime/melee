# Callee-Mediated Stack Object Writers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let movzx producer proofs conservatively derive a finite byte domain when an exact caller stack object is initialized or mutated through owned direct callees before a nested object-byte observation.

**Architecture:** Add one dependency-bound callee summary that follows a single argument-relative object field/path across reachable instructions and returns only an all-path finite writer result or a proven preservation result. Integrate those summaries as ordered pseudo-writers in the existing stack-object proof, while rejecting ambiguous aliases, escapes, unsupported calls/writes, and clobbers. Reuse the existing strict zero-fill recognizer and pointer-state machinery; do not add retail-address exceptions.

**Tech Stack:** Python 3, Capstone x86 detail API, pytest synthetic PE fixtures.

## Global Constraints

- No exact retail compiler replay in this task.
- Every production change follows a focused failing regression test.
- Every callee/helper/caller that affects a summary is a producer dependency.
- Caches include summary-fact and control-flow revisions.
- Unknown or ambiguous pointer effects fail closed.

---

### Task 1: Regression Fixture and RED Coverage

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Consumes: `recover_cfg`, synthetic `pe.Image`, 75-entry relocated dispatch table conventions.
- Produces: `callee_stack_object_writer_image(mutation=None)` and focused positive/hostile tests.

- [x] Add a synthetic program whose entrypoint constructs a stack root and nested stack node, calls an owned strict zero helper and two owned mutators through exact pushed pointers, then calls the movzx consumer from two ordered call sites.
- [x] Add hostile mutations for unowned/indirect callees, ambiguous aliases, pointer escape, conditional missing write, partial/overlapping unknown writes, conflicting path values, and post-call clobber.
- [x] Run the focused positive test and confirm it fails with `KeyError` because no table is recovered.
- [x] Run the hostile tests and confirm they remain unresolved under the old implementation.

### Task 2: Dependency-Bound Callee Writer Summary

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Consumes: `_relative_pointer_states`, `_relative_operand_offsets`, `_strict_zero_fill_function`, `_finite_byte_store_values`, `_pushed_call_argument`, `_summary_successors`.
- Produces: a private cached summary distinguishing finite all-path writes from preservation and bottom.

- [x] Add a small immutable summary type for `written values` versus `preserved`.
- [x] Implement a forward reachable-state summary for one callee argument/path: recognize exact finite MOV writes, strict zero fills with exact finite sizes, and transitive owned direct callees; require every reachable return to have a compatible state.
- [x] Reject pointer escape, ECX alias exposure, indirect/unowned callees, ambiguous offsets, partial/overlapping writes, unsupported post-write clobbers, and incompatible joins.
- [x] Bind every traversed function and helper as a producer dependency and key caches by summary/control revisions.
- [x] Integrate exact stack-pointer call arguments into `_finite_stack_object_byte_values_before_uncached` as pseudo-writers without skipping any bottom result.
- [x] Run the positive test until GREEN, then run all focused hostile cases.

### Task 3: Durable v7 Semantics and Broad Verification

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Consumes: `_MOVZX_PRODUCER_ANALYSIS_SEMANTICS`, certificate migration tests.
- Produces: `movzx-producer-analysis-v7` certificates that cannot reuse v6 blocked results.

- [x] Add/adjust the certificate migration regression to synthesize v6 and confirm v7 invalidation.
- [x] Bump the durable semantics constant from v6 to v7.
- [x] Run focused stack-writer and certificate tests.
- [x] Run the complete x86 CFG and CLI test sets, Ruff, `py_compile`, and `git diff --check`.
- [x] Review the final diff for address-specific logic, missing dependencies, or fail-open paths; report verification evidence without starting an exact replay.
