# Exact x86 CFG Finite-Flow Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development while executing this plan. Work in the dedicated temporary worktree, not the canonical issue worktree whose authoritative replay is active.

**Goal:** Replace repeated whole-image instruction scans in the affine-loop and dominating-guard finite-flow helpers with exact, ordered slices from the existing per-function instruction index, without changing any recovery result or durable semantics.

**Architecture:** Add one private range helper on `_DirectCfgRecovery`. It obtains the cached tuple from `_function_instruction_addresses(function_entry)` and uses `bisect_left` to return a half-open `[start, stop)` slice. The four targeted analyses consume that helper with bounds equivalent to their current predicates; all decode, ownership, traversal, cap, diagnostic, certificate, and fail-closed logic remains unchanged.

**Tech Stack:** Python 3.11, Capstone x86 decoding, pytest, Ruff, `py_compile`.

## Global Constraints

- Run `melee-agent capabilities search "x86 cfg finite flow per function instruction index"` before editing, per `AGENTS.md`.
- Implement only the approved scope in `docs/superpowers/specs/2026-07-18-x86-cfg-finite-flow-indexing-design.md`.
- Do not modify the producer-certificate schema, `_MOVZX_PRODUCER_ANALYSIS_SEMANTICS`, recovery caps, diagnostics, decoded-instruction cache, finite-value memoization, or persisted artifacts.
- Do not run the exact whole-PE replay in the temporary worktree and do not touch or stop the canonical worktree's active replay.
- Preserve numeric address order exactly. Use half-open ranges and express inclusive loop ends as `edge.source + 1`.
- Do not retain the optimization if focused tests or later exact counts/artifact bytes differ from the unoptimized oracle.

---

### Task 1: RED indexed range contract

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Produces: `_DirectCfgRecovery._function_instruction_addresses_between(function_entry, start, stop) -> tuple[int, ...]`.
- Consumes: existing `_function_instruction_addresses(function_entry)` cache and sorted address tuples.

- [ ] **Step 1: Extend the existing function-address-index fixture**

  In `test_function_address_index_rebuilds_once_for_new_entry_and_instruction`, add assertions for an empty half-open range, exact instruction boundaries, sparse interior bounds, a stop equal to the following function entry, and bounds extending outside the requested function. Prove neighboring-function instructions remain excluded.

  Compare every case with this reference contract, preserving tuple order:

  ```python
  expected = tuple(
      address
      for address in recovery._function_instruction_addresses(function_entry)
      if start <= address < stop
  )
  ```

- [ ] **Step 2: Run RED**

  ```bash
  cd tools/melee-agent
  python -m pytest -o addopts='' tests/test_retro_x86_cfg.py -k 'function_address_index' -q
  ```

  Confirm the new assertions fail because `_function_instruction_addresses_between` does not exist. Record the failing test name and exception.

- [ ] **Step 3: Commit the RED test**

  ```bash
  git add tools/melee-agent/tests/test_retro_x86_cfg.py
  git commit -m "test: specify indexed instruction ranges"
  ```

---

### Task 2: GREEN range helper and targeted consumers

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Produces: ordered half-open per-function instruction slices.
- Updates only: `_loop_can_bypass_register_definition`, `_finite_affine_loop_register_values`, `_dominating_nonzero_guard`, and `_dominating_register_equal_guard`.

- [ ] **Step 1: Add the minimal range helper**

  Immediately after `_function_instruction_addresses`, add:

  ```python
  def _function_instruction_addresses_between(
      self,
      function_entry: int,
      start: int,
      stop: int,
  ) -> tuple[int, ...]:
      addresses = self._function_instruction_addresses(function_entry)
      slice_start = bisect_left(addresses, start)
      slice_end = bisect_left(addresses, stop, lo=slice_start)
      return addresses[slice_start:slice_end]
  ```

  Do not add a second cache; slicing the existing tuple is the complete implementation.

- [ ] **Step 2: Replace only the equivalent affine-loop scans**

  Make these mechanical substitutions:

  - `_loop_can_bypass_register_definition`: use `[edge.target, edge.source + 1)` instead of iterating `self.instructions` and applying the inclusive filter.
  - `cycle_addresses` inside `_finite_affine_loop_register_values`: use `[edge.target, edge.source + 1)` instead of sorting the whole map and applying the same filter.
  - affine-loop base/counter discovery: use `[function_entry, backedge.target)` instead of sorting the whole map and filtering.

  Keep every subsequent predicate and early return byte-for-byte unchanged where practical.

- [ ] **Step 3: Replace only the equivalent dominating-guard scans**

  In both `_dominating_nonzero_guard` and `_dominating_register_equal_guard`, build `candidates` from `_function_instruction_addresses_between(function_entry, function_entry, transfer_address)[-2048:]`. Preserve reverse iteration, the 2048 cap, condition walk, reachability checks, and register-clobber scan unchanged.

- [ ] **Step 4: Run GREEN and focused semantic regressions**

  ```bash
  cd tools/melee-agent
  python -m pytest -o addopts='' tests/test_retro_x86_cfg.py -k 'function_address_index or bounded_affine_descriptor_array or nested_affine or dominating_equal_guard or equal_guard_rejects_register_clobber or zero_domain_and_nonzero_guard or guarded_zero_context' -q
  ```

- [ ] **Step 5: Add a structural performance regression if needed**

  Reuse the existing `builtins.sorted` observer pattern. Exercise the bounded affine and dominating-guard fixtures and assert the targeted helper calls do not sort `recovery.instructions`. Do not add wall-clock thresholds.

- [ ] **Step 6: Commit GREEN**

  ```bash
  git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
  git commit -m "perf: index finite-flow instruction scans"
  ```

---

### Task 3: Focused verification and review handoff

**Files:**
- Verify: `tools/mwcc_retro/x86_cfg.py`
- Verify: `tools/melee-agent/tests/test_retro_x86_cfg.py`

- [ ] **Step 1: Run the complete Task 4 focused suite**

  From `tools/melee-agent`:

  ```bash
  python -m pytest -o addopts='' tests/test_retro_x86_cfg.py tests/test_retro_backend_lifetime_audit.py tests/test_retro_backend_cli.py tests/test_ghidra_mwcc_setup.py tests/test_mwcc_ghidra_setup_script.py -q
  ```

- [ ] **Step 2: Run static validation**

  From the repository root:

  ```bash
  python -m ruff check tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
  python -m py_compile tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
  git diff --check HEAD~2..HEAD
  ```

- [ ] **Step 3: Self-review exact scope**

  Inspect `git diff HEAD~2..HEAD` and verify only the two planned files changed; every new range matches the old inclusivity; candidate order and the 2048 cap are unchanged; no semantics/schema constant, diagnostic, limit, or persistence code changed; and there are no placeholders, temporary prints, timing assertions, or unrelated cleanup.

- [ ] **Step 4: Return a durable handoff**

  Push the temporary branch and report both commit hashes, RED evidence, focused/full pass counts, static-check results, changed paths, and any observed limitation. Do not cherry-pick or merge into the canonical issue branch; the root orchestrator will review and integrate only after the unoptimized exact replay reaches a durable boundary.

## Canonical Integration Gate (Root Orchestrator Only)

After the active unoptimized CLI replay terminates, retain its exact generation as the oracle. Review and cherry-pick the optimization commits, rerun the focused/static gates, and perform the next exact CLI replay. Accept the optimization only if the closure remains exactly 362,835 instructions, 97,552 blocks, 156,219 edges, and 564 tables, existing producer certificates validate, and repeated canonical artifacts are byte-identical.
