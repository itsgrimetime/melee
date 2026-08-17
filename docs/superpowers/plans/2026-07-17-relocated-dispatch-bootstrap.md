# Relocated Dispatch Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover cyclic movzx-indexed callback families from independently relocated table slots without accepting any edge or target until the normal producer-domain resolver reproduces that exact slot.

**Architecture:** Ordinary recovery records one tentative hypothesis per structurally valid relocated slot discovered from an owned scale-four indexed call. The outer recovery loop may replay all tentative slot records as trial seeds, but only accepts slots reproduced by a normal `JumpTable` at the same transfer, base, index, and target; partial reproduction forces a clean rerun with the accepted subset. The existing object/copied hypothesis identity, invalidation, and whole-trial reuse loop remains the sole promotion mechanism.

**Tech Stack:** Python 3.11, Capstone x86 decoding, pytest, Ruff, `py_compile`.

## Global Constraints

- No exact compiler run during this task.
- No address allowlist or raw relocation promoted directly to a control edge.
- Only owned indexed indirect calls with scale four may nominate a table.
- Every nominated slot must have exactly one i386 type-3 HIGHLOW relocation and an executable instruction-aligned target.
- The candidate run must end at a nonrelocated or otherwise invalid slot.
- Final recovery may retain only per-slot seeds reproduced by normal exact producer-domain resolution.
- Bump durable movzx producer semantics from v5 to v6 because trial roots can change producer results.

---

### Task 1: RED cyclic dispatch fixtures

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Produces: `cyclic_relocated_movzx_dispatch_image(...) -> tuple[pe.Image, int, tuple[int, ...]]` for focused recovery tests.
- Consumes: existing `recover_cfg`, `build_seed_inventory`, and `generous_limits` helpers.

- [x] **Step 1: Add a real cyclic PE fixture**

  Seed only a consumer containing `mov eax,[esp+4]; movzx ebx,[eax]; call [ebx*4+TABLE]; ret`. Put its complete raw caller set in initially unreachable relocated callbacks that construct stack bytes for the requested producer endpoints and call the consumer. Populate a 75-slot relocated run, terminate it with a nonrelocated zero, and support mutations for absent relocation, non-executable target, instruction-interior target, raw-only transfer, no callback callers, and all-slot producer domain.

- [x] **Step 2: Add positive and refinement assertions**

  Assert the default fixture resolves a producer-domain table over indices `0..2`, retains only bootstrap slots `0..2`, omits the unique slot-3 target from final instructions/seeds, performs three recoveries, and leaves no unresolved transfer or bootstrap-only edge. Assert the `0..74` fixture performs two recoveries and reuses the all-slots trial CFG.

- [x] **Step 3: Add hostile assertions**

  Assert absent relocation, non-executable/interior targets, raw-only transfer, bottom producer domain, and an unrelated raw mutual-recursion cycle retain no relocated-dispatch bootstrap seed and no resolved transfer. Assert invalidating a reproduced slot causes a clean rebuild.

- [x] **Step 4: Run RED**

  Run `python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -k 'relocated_dispatch_bootstrap or cyclic_relocated' -q` and verify failures are caused by the missing hypothesis type/behavior.

### Task 2: GREEN per-slot hypothesis discovery

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Produces: `_RelocatedDispatchSlotHypothesis(transfer_address, table_base, index, slot_address, target, records)`.
- Produces: `_record_relocated_dispatch_bootstrap_slots()` which records tentative and validated per-slot sets without adding edges, finite targets, data evidence, or pending code.

- [x] **Step 1: Define canonical per-slot state**

  Add tentative and validated hypothesis sets to `_DirectCfgRecovery`; use one `SeedRecord` category `relocated-dispatch-bootstrap-entry` per exact slot.

- [x] **Step 2: Discover strict candidate runs**

  For each owned indirect call with one scale-four memory operand and a local/absolute table base, require a local movzx index definition, scan contiguous exact type-3 slots in a non-executable raw-backed section, stop at the first nonrelocated/invalid slot, reject overlapping owned writes and instruction-interior targets, and emit only tentative hypotheses.

- [x] **Step 3: Reproduce exact slots**

  If normal recovery has a `JumpTable` at the same transfer/base, mark only slots whose index lies in its exact interval and whose slot target equals the resolved entry as validated. Do not create a bootstrap edge.

- [x] **Step 4: Run GREEN for discovery/hostile tests**

  Run the focused `-k` command from Task 1 and verify candidate discovery and hostile rejection pass.

### Task 3: GREEN outer-loop promotion and invalidation

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Consumes: tentative/validated relocated-slot sets.
- Produces: relocated-slot identity integrated with existing object/copied candidate, acceptance, invalidation, rejection, and reusable-trial logic.

- [x] **Step 1: Extend identity and candidate ordering**

  Include transfer, base, index, slot, target, and record bytes in canonical identity; sort candidates by those fields.

- [x] **Step 2: Validate accepted slots on every recovery**

  Add validated relocated slots to `valid_identities`. If an accepted slot is no longer reproduced, remove it and rebuild without reusing the invalid trial.

- [x] **Step 3: Enforce subset clean rerun and union reuse**

  Trial all new slots together. Accept only reproduced identities; reject unused identities permanently for the invocation. Reuse the trial CFG only when every new slot reproduced, otherwise run a clean recovery with only the accepted subset.

- [x] **Step 4: Run GREEN for replay tests**

  Run the focused `-k` command and verify three-run subset refinement, two-run all-slot reuse, and accepted-slot invalidation.

### Task 4: Durable semantics and broad verification

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Produces: `_MOVZX_PRODUCER_ANALYSIS_SEMANTICS = "movzx-producer-analysis-v6"`.

- [x] **Step 1: Bump and test durable semantics**

  Update the semantics identifier and certificate assertion from v5 to v6.

- [x] **Step 2: Run full CFG and CLI suites**

  Run `python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py tools/melee-agent/tests/test_retro_backend_cli.py -q`.

- [x] **Step 3: Run static validation**

  Run `python -m ruff check tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py tools/melee-agent/src/cli/debug/retro.py`, `python -m py_compile tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py`, and `git diff --check`.

- [x] **Step 4: Report soundness and recovery counts**

  Report RED evidence, focused/broad pass counts, subset/all-union recovery counts, hostile outcomes, and confirm no exact compiler run was performed.
