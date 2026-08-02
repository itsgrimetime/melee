# MOVZX Object-Tag Lifecycle Implementation Plan

> **For agentic workers:** Execute inline with strict red-green-refactor cycles.

**Goal:** Add a durable, generic lifecycle-domain fallback for offset-zero
object-tag MOVZX dispatches without changing v25 producer certificates.

**Architecture:** A separate lifecycle query proves a finite byte domain from
closed fresh-allocation and caller lifecycles. Each consumer binds the proved
receiver to both the byte load and argument zero before the existing jump-table
validator consumes the bound.

**Tech Stack:** Python, Capstone, pytest, synthetic PE fixtures.

## Global Constraints

- Do not change `movzx-producer-analysis-v25` semantics or persisted query shape.
- Do not derive a bound from relocation length.
- Keep type-3 relocation and executable-target validation unchanged.
- Fail closed on every open origin, writer, caller, alias, or consumer binding.
- Use no retail-address allowlist.

---

### Task 1: Positive lifecycle proof

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify: `tools/mwcc_retro/x86_cfg.py`

- [x] Add a synthetic PE with a closed cross-function allocation/tag/consumer lifecycle.
- [x] Add a test requiring two consumers to recover with `movzx-lifecycle-domain` and bound 74.
- [x] Run the focused test and confirm it fails because the fallback is absent.
- [x] Add the minimal lifecycle query, write index, receiver binding, and fallback.
- [x] Run the focused test and confirm it passes.

### Task 2: Hostile lifecycle matrix

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify: `tools/mwcc_retro/x86_cfg.py`

- [x] Parameterize open caller, unknown writer, tag 75, receiver mismatch, and argument-zero mismatch mutations.
- [x] Confirm each mutation initially recovers unsafely or otherwise fails for the intended missing guard.
- [x] Tighten lifecycle closure and per-consumer binding until each mutation blocks.
- [x] Add missing-relocation and non-executable-entry cases to prove existing table checks remain active.

### Task 3: Durable separation and verification

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify: `tools/mwcc_retro/x86_cfg.py`

- [x] Add checkpoint tests proving lifecycle persistence and dependency invalidation while v25 query identity remains unchanged.
- [x] Run focused tests, the complete `test_retro_x86_cfg.py`, Ruff, py_compile, and whitespace/diff checks.
- [x] Review the final diff for address allowlists or weakened table validation.
- [x] Commit the coherent green change.
