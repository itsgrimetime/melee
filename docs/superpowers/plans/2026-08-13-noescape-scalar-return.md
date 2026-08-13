# No-Escape Scalar Return Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that closed mutating parsers return only protected-capability-free scalar values without weakening pointer escape rules.

**Architecture:** Extend the existing protected-capability dataflow with one query-local recursive return graph. Each exact callee is audited under the existing closed no-escape argument proof, and provisional cycles publish authority only when every reachable return and raw successor domain validates.

**Tech Stack:** Python 3.11, Capstone x86 decoding, pytest.

## Global Constraints

- No retail address, hash, or function-shape allowlist in production.
- Do not treat a mutating pointer argument as read-only.
- Memoized proof state is query-local and never serialized.
- Scope is exactly `tools/mwcc_retro/x86_cfg.py`, `tools/melee-agent/tests/test_retro_x86_cfg.py`, and the associated design/plan documents.

---

### Task 1: Symmetric affine pointer tracking

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Consumes: `_relative_pointer_states(..., collapse_nonnegative_offsets=True)`.
- Produces: identical pointer identity for `base + index` and `index + base` when exactly one unscaled input is tainted; exact `inc` and `dec` retain identity.

- [x] **Step 1: Add paired RED cases**

  Add base-position, index-position, index-decrement, scaled-index, and two-tainted-input fixtures. Require the first three to pass and the last two to reject.

- [x] **Step 2: Verify strict RED**

  Run `pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py -k read_only_argument_accepts_one_commutative_lea_pointer` and observe only the new index/decrement positives fail.

- [x] **Step 3: Implement the symmetric rules**

  In the collapsed LEA branch, accept either one unscaled tainted base or one unscaled tainted index, reject two tainted inputs and scaled tainted indices. Handle full-width `inc` and `dec` as signed one-step affine adjustments.

- [x] **Step 4: Verify focused GREEN**

  Run the Step 2 command and require all five cases to pass.

### Task 2: Query-local recursive scalar return proof

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Consumes: `_register_is_proven_image_capability_free_before`, `_function_argument_does_not_escape_closed_scc`, exact direct-call targets, `_summary_successors`.
- Produces: `_function_return_is_protected_capability_free(function_entry, protected_slots, call_return_domains, graph) -> bool`, where `graph` is one ephemeral proof graph owned by the capability-seal query.

- [ ] **Step 1: Add strict positive and hostile fixtures**

  Encode a closed mutating callee returning an incremented scalar count, a recursive two-function counterpart, and one-fact mutations for pointer return, global escape, unresolved call, protected literal return, protected-slot load, and raw-successor mismatch. Assert the old capability result rejects both positives and every hostile remains rejected.

- [ ] **Step 2: Run the new selection and record RED**

  Run `pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py -k noescape_scalar_return` and require the two positive assertions to fail before production changes.

- [ ] **Step 3: Implement the bounded graph evaluator**

  Add an immutable per-node status keyed by function, protected slots, exact call-return rows, summary signature, and CFG revision. Audit reachable raw successors, propagate the existing three-state protected lattice, require every pointer-derived call argument to pass `_function_argument_does_not_escape_closed_scc`, and invalidate every provisional member if any node fails.

- [ ] **Step 4: Connect the proof at transfer sites**

  Before returning `None` for an unknown PUSH/STORE register value, allow the transfer only if every reaching definition is an exact direct-call result whose target succeeds in the query-local scalar-return graph. Preserve all existing finite, partial-store, and quarantine checks.

- [ ] **Step 5: Run focused GREEN and currentness checks**

  Run `pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py -k 'noescape_scalar_return or read_only_argument_accepts_one_commutative_lea_pointer or capability_push'`. Require all selected cases to pass and a fresh recovery/query to recompute after a mocked failure.

### Task 3: Retail and regression validation

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Consumes: completed Tasks 1 and 2.
- Produces: durable evidence that the generic proof closes `0x44364a` and advances or closes root `0x435620`.

- [ ] **Step 1: Run the exact narrow retail proof**

  Hydrate the pinned CFG, assert the protected-free result at the failing transfer, and retain the decoded/read/no-escape diagnostics showing no retail-specific authorization.

- [ ] **Step 2: Run semantic adjacency**

  Run `pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py -k 'partial_return or partial_register or session_capability_seal or byte_predicate or private_stack_scalar or narrow_scalar_argument or partial_call_result or read_only_argument or noescape_scalar_return'`.

- [ ] **Step 3: Run static gates**

  Run `python -m py_compile tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py`, `ruff check` on those files, `git diff --check`, and a changed-line scan for retail addresses/hashes/allowlists.

- [ ] **Step 4: Run root replay**

  Run the pinned `--task4-publication-root 0x435620` replay with `/usr/bin/time -l`. If it fails, extract only the terminal stage row and diagnose the next boundary; if it succeeds, retain the timing/RSS/log digest for Task 8.

- [ ] **Step 5: Commit and push**

  Stage only the two Python files and these design/plan documents, commit with a scoped `mwcc-retro` message, and push `codex/issue-1240-retail-pcode-proof` to `origin`.
