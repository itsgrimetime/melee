# Struct Verify Non-Struct Mismatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve #460 by replacing THP row decoder `missing dataflow proof` skips with explicit `non-struct-source-shape` skips when unresolved mismatched-base offsets are not plausible same-struct field-layout rows.

**Architecture:** Add a small layout-aware classifier inside `tools/melee-agent/src/cli/struct.py` and call it only when `_resolve_row_from_dataflow()` fails for mismatched register bases. The helper does not create findings or alias roots; it only improves skip reasons.

**Tech Stack:** Python 3.11, existing struct-verify resolver helpers, pytest.

---

Spec: `docs/superpowers/specs/2026-06-06-struct-verify-nonstruct-mismatch-design.md`
Issue: #460

## Files

- Modify: `tools/melee-agent/src/cli/struct.py`
- Modify: `tools/melee-agent/tests/test_struct_verify.py`
- Create: `docs/superpowers/specs/2026-06-06-struct-verify-nonstruct-mismatch-design.md`
- Create: `docs/superpowers/plans/2026-06-06-struct-verify-nonstruct-mismatch.md`

## Task 1 - Red Tests

- [x] Add tests in `tools/melee-agent/tests/test_struct_verify.py`:
  - mismatched bases with current displacement unnamed returns a skip containing `non-struct-source-shape`
  - mismatched bases with current displacement named and reference displacement far away/unnamed returns `non-struct-source-shape`
  - mismatched bases where current and reference displacements map to different named fields returns `non-struct-source-shape`
  - mismatched bases with current displacement named and reference displacement nearby/unnamed keeps `unresolved mismatched bases`
  - mismatched bases with explicit `base_offset` where `base_offset + cur_disp` maps a named field keep `unresolved mismatched bases`
  - ambiguous same-base rows where every candidate is clearly non-struct return explicit `non-struct-source-shape` skips
  - plausible ambiguous same-base rows keep the existing `ambiguous offset base candidates` skip
  - ambiguous same-base rows with an exact or unique inferable interior layout fit keep the existing `ambiguous offset base candidates` skip
- [x] Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_struct_verify.py -q -k 'non_struct_source_shape or named_current_mismatch or mismatched_bases_without_proof or explicit_base_offset_field_mismatch or ambiguous_non_struct_sources or plausible_ambiguous_sources or inferable_interior_ambiguous_sources'
```

Expected: the new non-struct tests fail.

## Task 2 - Helper and Resolver Integration

- [x] Add `_non_struct_source_shape_reason(row, layout)` in `tools/melee-agent/src/cli/struct.py`.
- [x] The helper should return a reason string beginning with `non-struct-source-shape:` only when:
  - current displacement has no named field, or
  - both current and reference displacements map to different named fields, or
  - current displacement maps to a named field, reference maps to no field, and `abs(cur_disp - ref_disp) > 0x20`
- [x] Keep explicit base-offset rows unresolved when `base_offset + cur_disp` maps a named field.
- [x] Call this helper in both mismatched-base failure branches in `_resolve_discrepancy_rows()`.
- [x] Use the helper for ambiguous same-base fallback only when every ambiguous candidate is non-struct and no candidate has an explicit, exact, or unique inferable plausible layout fit.
- [x] Re-run the focused tests and verify they pass.

## Task 3 - Dogfood and Review

- [x] Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_struct_verify.py -q
PYTHONPATH=tools/melee-agent python -m src.cli struct verify __THPDecompressiMCURow640x480 --struct THPFileInfo --tu-src extern/dolphin/src/dolphin/thp/THPDec.c --json
PYTHONPATH=tools/melee-agent python -m src.cli struct verify __THPDecompressiMCURowNxN --struct THPFileInfo --tu-src extern/dolphin/src/dolphin/thp/THPDec.c --json
python -m py_compile tools/melee-agent/src/cli/struct.py
git diff --check
```

- [x] Confirm both THP CLI outputs have no `missing dataflow proof` skips.
- [x] Request independent Codex review.
- [x] Mark this plan complete, commit the #460 files, resolve issue #460, and refresh the editable `melee-agent` install.
