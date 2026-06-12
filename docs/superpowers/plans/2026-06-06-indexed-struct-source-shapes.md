# Indexed-Struct Source Shapes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Resolve #452 by making `indexed-struct-search` emit candidates for the supported source shapes that currently block as `indexed-struct-hint-unavailable`.

**Architecture:** Extend the existing scanner in `pressure_explorer.py` instead of adding a new harness. Add narrowly scoped tests for casted pointer-plus array uses, single-use direct indexed fields, and direct indexed element expressions. Keep safety gates local to the scanner and let the existing harvest/CLI scoring path rank generated probes.

**Tech Stack:** Python 3.11, pytest, `melee-agent debug mutate indexed-struct-search`.

---

Spec: `docs/superpowers/specs/2026-06-06-indexed-struct-source-shapes-design.md`
Issue: #452

## Files

- Modify: `tools/melee-agent/src/mwcc_debug/pressure_explorer.py`
- Modify: `tools/melee-agent/tests/test_pressure_explorer.py`
- Create: `docs/superpowers/specs/2026-06-06-indexed-struct-source-shapes-design.md`
- Create: `docs/superpowers/plans/2026-06-06-indexed-struct-source-shapes.md`

## Task 1 - Red Tests

- [x] Add `test_indexed_struct_pointer_probe_rewrites_casted_pointer_plus_array_uses`.
  Use a source fixture with `u8* p;` followed later by
  `p = (u8*) (str + i);` and reads `p[2]` and `p[1]`. Assert the scan returns
  one probe, keeps the declaration, removes the redundant assignment,
  and rewrites reads to `((u8*) (str + i))[2]` and
  `((u8*) (str + i))[1]`.
- [x] Add `test_indexed_struct_pointer_probe_rejects_unsafe_casted_array_uses`.
  Include cases for `p[2] = value;`, `return &p[2] != 0;`, and a later plain
  `return p != 0;`. Assert no probes and
  `blocker == "no-safe-materialized-pointer"`.
- [x] Add `test_indexed_struct_pointer_probe_splits_single_direct_indexed_field`.
  Use a source fixture with `HSD_AnimJoint* fn(...)` and
  `return attr->entries[picked].anim;`. Assert one probe inserts
  `HSD_AnimJoint* ll_probe_indexed_field_0`, assigns the direct indexed field
  into it, and returns the scalar.
- [x] Add `test_indexed_struct_pointer_probe_splits_direct_indexed_element`.
  Use a visible typedef containing `HSD_JObj* jobjs[9]`, a `MnItemSwData* data`
  local, and calls using `data->jobjs[5]` and `data->jobjs[4]`. Assert one
  probe inserts `HSD_JObj* ll_probe_indexed_element_0`.
- [x] Add `test_indexed_struct_pointer_probe_splits_direct_indexed_element_with_void_pointer_fallback`.
  Use a source fixture with no visible struct field declaration and a call
  argument `HSD_JObjGetTranslationY(data->jobjs[5])`. Assert one probe inserts
  `void* ll_probe_indexed_element_0`.
- [x] Add one rejection test for direct indexed element lvalues and
  address-taken uses.
- [x] Run the new tests and verify they fail for missing probes:

```bash
PYTEST_ADDOPTS=--no-cov python -m pytest \
  tools/melee-agent/tests/test_pressure_explorer.py::test_indexed_struct_pointer_probe_rewrites_casted_pointer_plus_array_uses \
  tools/melee-agent/tests/test_pressure_explorer.py::test_indexed_struct_pointer_probe_rejects_unsafe_casted_array_uses \
  tools/melee-agent/tests/test_pressure_explorer.py::test_indexed_struct_pointer_probe_splits_single_direct_indexed_field \
  tools/melee-agent/tests/test_pressure_explorer.py::test_indexed_struct_pointer_probe_splits_direct_indexed_element \
  tools/melee-agent/tests/test_pressure_explorer.py::test_indexed_struct_pointer_probe_splits_direct_indexed_element_with_void_pointer_fallback \
  tools/melee-agent/tests/test_pressure_explorer.py::test_indexed_struct_pointer_probe_rejects_unsafe_direct_indexed_elements \
  -q
```

## Task 2 - Casted Pointer-Plus Array Uses

- [x] Add an `array-subscript` access mode to `_IndexedStructPointerFieldUse`
  provenance by reusing the existing dataclass fields with `syntax="array-subscript"`.
- [x] Extend `_indexed_struct_pointer_candidates()` to detect separated
  assignment candidates where a pointer variable is declared earlier in the
  function and later assigned a supported initializer. The candidate replacement
  span should be the assignment line only, not the earlier declaration.
- [x] Extend `_parse_indexed_struct_pointer_initializer()` with helpers that
  unwrap simple C casts and one layer of outer parentheses so
  `(u8*) (str + i)` parses as base `str`, index `i`, direct expression
  `(u8*) (str + i)`, and access mode `array-pointer-expression`.
- [x] Extend `_indexed_struct_pointer_field_uses()` to recognize standalone
  `p[expr]` reads for `array-pointer-expression` candidates and replace them
  with `(<direct_expression>)[expr]`.
- [x] Reject array-subscript candidates when any `p[expr]` use is an lvalue,
  address-taken, or when the pointer name remains in the affected region after
  accepted subscripts are masked.
- [x] Preserve the existing "no other pointer mentions" check after masking
  rewritten ranges.

## Task 3 - Single Direct Field Splits

- [x] In `_indexed_struct_direct_scalar_split_probes()`, allow groups with one
  safe use to generate a probe.
- [x] Extend `_infer_indexed_struct_direct_scalar_type()` to infer the current
  function return type for `return base[index].field;` statements. If the return
  type is pointer-like, emit that pointer type instead of falling back to `f32`.
- [x] Keep the existing mutation, lvalue, address-taken, side-effect, and
  preprocessor checks unchanged.
- [x] Ensure provenance marks `variant="direct-field-scalar-split"` and
  `split_first_field=True` for the one-use case.

## Task 4 - Direct Indexed Element Splits

- [x] Add `_IndexedStructDirectElementUse` with the same span/line fields as
  `_IndexedStructDirectFieldUse`, plus `element_type`.
- [x] Add `_INDEXED_STRUCT_DIRECT_ELEMENT_RE` that matches standalone
  `base[index]` and optional second index, but skips matches that are already
  part of `.field`, `->field`, declarations, lvalues, address-taken uses, or
  comments/strings.
- [x] Add `_infer_indexed_struct_element_type()` that resolves
  `base->field[index]` or `base.field[index]` by finding the base variable type
  in scoped identifiers and scanning visible typedef/struct declarations for
  `field` array declarations. Normalize `HSD_JObj* jobjs[9]` to `HSD_JObj*`.
- [x] When no visible field declaration exists, allow `void*` only for direct
  indexed element reads used as a function-call argument. Reject other unknown
  element types.
- [x] Add `_indexed_struct_direct_element_split_probes()` and call it from
  `scan_indexed_struct_pointer_probes()` after direct field probes.
- [x] Generate one scalar split probe named
  `indexed-struct-pointer-<label_index>` with temp prefix
  `ll_probe_indexed_element`.

## Task 5 - Verification

- [x] Run:

```bash
PYTEST_ADDOPTS=--no-cov python -m pytest tools/melee-agent/tests/test_pressure_explorer.py -q
```

- [x] Run the reported functions in no-compile mode:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug mutate indexed-struct-search -f hsd_80391AC8 --source-file src/sysdolphin/baselib/particle.c --no-compile-probes --no-score-match-percent --json --max-probes 8
PYTHONPATH=tools/melee-agent python -m src.cli debug mutate indexed-struct-search -f it_80294364 --source-file src/melee/it/items/itwstar.c --no-compile-probes --no-score-match-percent --json --max-probes 8
PYTHONPATH=tools/melee-agent python -m src.cli debug mutate indexed-struct-search -f mnItemSw_802351A0 --source-file src/melee/mn/mnitemsw.c --no-compile-probes --no-score-match-percent --json --max-probes 8
```

- [x] Run:

```bash
python -m py_compile tools/melee-agent/src/mwcc_debug/pressure_explorer.py
PYTHONPATH=tools/melee-agent python -m src.cli debug mutate indexed-struct-search --help
git diff --check
```

- [x] Request independent Codex review of the diff.
- [x] Commit only the #452 spec, plan, scanner, and tests.
- [x] Resolve #452 with the commit hash after verification.
- [x] Refresh the editable `melee-agent` install because shared CLI tooling changed.

## Completion Notes

- Added follow-up regression coverage from independent review for parenthesized
  lvalue expressions, comment/split-line control contexts, and nested outer-scope
  pointer declarations.
- The reported functions now generate probes in no-compile mode. `it_80294364`
  and `mnItemSw_802351A0` score candidates successfully; `hsd_80391AC8` generates
  the expected probe but local MWCC dump scoring can hit the known wibo hang.
