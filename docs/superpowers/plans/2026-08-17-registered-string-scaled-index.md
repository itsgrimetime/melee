# Registered-string scaled-index implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove registered-string record selection when a full-width address temporary, distinct from the bounded counter register, carries the scaled table index.

**Architecture:** Extend only `_registered_string_record_length_domain_before` so the table-load index family and the LEA source counter family have distinct roles. Reuse the existing closed writer, reader, counter, table, and immutable-string proofs without adding authority, caches, caps, or special cases.

**Tech Stack:** Python 3, Capstone x86 operands, pytest, Ruff, git.

## Global constraints

- Keep the proof address-, byte-, hash-, function-name-, and compiler-marker-independent.
- Require full-width unique definitions and identical LEA base/index counter families.
- Preserve every existing table, field, key, writer, reader, string, relocation, and work-limit gate.
- Fail closed on mixed LEA sources, partial registers, unknown definitions, unsupported scales, incomplete counter domains, or mutable evidence.
- Modify exactly `tools/mwcc_retro/x86_cfg.py`, `tools/melee-agent/tests/test_retro_x86_cfg.py`, and the existing progress/report handoff when recording results.
- Do not launch either publication root until the authoritative call-slot replay emits its exact positive row.

---

### Task 1: Separate the scaled-index and counter register families

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:516-683,72821-72874`
- Modify: `tools/mwcc_retro/x86_cfg.py:79436-79516`
- Modify after validation: `.superpowers/sdd/progress.md`
- Append after validation: `.superpowers/sdd/2026-08-06-private-page-arena-invariant/task-8-report.md`

**Interfaces:**
- Consumes: `_DirectCfgRecovery._registered_string_record_length_domain_before(address, operand, function_entry) -> tuple[int, ...] | None` and the existing `registered_string_record_table_image` fixture.
- Produces: the same method signature and return type, now accepting a distinct full-width scaled-index temporary only when both LEA inputs derive from the same bounded counter family.

- [x] **Step 1: Write the strict fixture RED**

  In `registered_string_record_table_image`, add mutations
  `distinct-reader-index` and `mixed-reader-index-source`. Preserve the
  existing default `EDX <- EDX * 3` reader. For the new cases use:

  ```python
  cursor = emit(
      cursor,
      "8d 0c 5a"
      if mutation == "mixed-reader-index-source"
      else "8d 0c 52",
  )
  cursor = emit_absolute(cursor, "8b 04 8d", table)
  ```

  These encode `lea ecx,[edx+edx*2]` followed by
  `mov eax,[ecx*4+table]`; the hostile changes only the LEA index input to
  `ebx`. Add `("distinct-reader-index", (3, 5))` and
  `("mixed-reader-index-source", None)` to the existing parameter matrix.
  Retain the default expected length tuple `(3, 5)` and every current hostile
  expectation.

- [x] **Step 2: Run the focused RED and authenticate its boundary**

  Run:

  ```bash
  pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py \
    -k registered_string_record_domain_requires_closed_writer_and_reader
  ```

  Expected at unchanged production: exactly ten selected parameter cases;
  the distinct-family positive fails because the result is `None` rather than
  `(3, 5)`, while the original same-register positive, the new mixed-source
  hostile, and all seven existing hostiles pass. Confirm the new positive and
  hostile differ only in the LEA SIB byte (`0x52` versus `0x5a`) and both
  retain non-null recovery/table prerequisites.

- [x] **Step 3: Implement the minimal family separation**

  In `_registered_string_record_length_domain_before`:

  ```python
  scaled_index_family = self._register_family(name_memory.index)
  scaled_index_definitions = self._register_definitions_across_blocks(
      load.address,
      scaled_index_family,
      function_entry,
  )
  ```

  Require the unique full-width LEA destination family to equal
  `scaled_index_family`. Require valid LEA base/index registers, identical
  full-width source families, and the existing scale set. Then derive:

  ```python
  counter_family = self._register_family(affine_memory.base)
  if self._register_family(affine_memory.index) != counter_family:
      return None
  ```

  Keep the stride calculation unchanged and pass `counter_family` to
  `_private_stack_postincrement_counter_index_values`. Do not alter later table
  or string checks.

- [x] **Step 4: Run focused and adjacent GREEN gates**

  Run:

  ```bash
  pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py \
    -k registered_string_record_domain_requires_closed_writer_and_reader
  pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py \
    -k 'registered_string_record or immutable_scalar_format_interval or scalar_format_alias_continuation'
  ```

  Expected: all ten focused cases pass; every collected adjacent case passes.
  Re-run the exact retail mini-query and require registered string lengths
  `(13, 14, 15, 16, 19, 20)` and scalar output interval `(53, 80)` at the
  current `0x408cbc -> 0x403c50` boundary, with no configured-limit row.

- [x] **Step 5: Run scoped static gates and review**

  Run:

  ```bash
  python -m py_compile tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
  ruff check tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
  git diff --check
  git diff --name-only
  ```

  Require only the two implementation/test files before handoff updates, no
  new Ruff findings, and no added retail address/hash/name/byte allowlist.
  Obtain independent review of the exact diff and focused/retail evidence.

- [x] **Step 6: Commit the reviewed repair and authenticate the module**

  Commit only the production/test repair with:

  ```bash
  git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
  git commit -m "fix(mwcc-retro): separate registered string index provenance"
  ```

  Run the complete x86 module under the existing restart-safe detached wrapper;
  require exit zero, the exact pass count, elapsed time, maximum RSS, and
  output/stderr/wrapper SHA-256 values. Append those facts to the Task 8 report
  and progress handoff, commit the documentation checkpoint, and push the
  branch.

- [ ] **Step 7: Replay the authoritative call-slot proof**

  Launch the current syntax-checked call-slot wrapper restart-safe. Use
  30--60-minute quiet waits while it is healthy. Require exactly one row:

  ```text
  call-slot-consumed=0x443a10;argument=1;function=0x443770;result=True
  ```

  A finite false result starts a new diagnostic/TDD cycle. An exception,
  configured-limit failure, stale currentness, or wrapper/hash mismatch stops
  fail closed. Only the exact positive row unlocks the two publication-root
  wrappers.
