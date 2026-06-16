# Node-Set Split Source Families Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `debug solve node-set-split` so it can generate, prioritize, compose, and verify the four source-shape families requested by issue #732.

**Architecture:** Keep the CLI unchanged. Add conservative source scanning, candidate-family ordering, four source-family generators, and bounded same-IG composites inside `tools/melee-agent/src/mwcc_debug/node_set_split.py`; cover behavior with focused tests in `tools/melee-agent/tests/test_node_set_split.py`.

**Tech Stack:** Python 3.11, pytest, existing `mwcc_debug.node_set_split`, `source_spans`, `source_patch`, and `source_shape` helpers.

---

### Task 1: Family Ordering And Scanner Foundations

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Add failing tests for family classification and priority ordering**

Add these imports near the existing `node_set_split` imports in
`tools/melee-agent/tests/test_node_set_split.py`:

```python
import re

import src.mwcc_debug.node_set_split as node_set_split
from src.mwcc_debug.source_shape import CandidatePatch
```

Add this test near the existing generation tests:

```python
def test_node_set_patch_order_prioritizes_new_families_before_high_volume_legacy() -> None:
    source = "void fn_test(void) { int x; }\n"
    patches = [
        CandidatePatch(f"node-split-alias-holder-ig40-use{i}", source, "old alias", ((0, 0),))
        for i in range(8)
    ] + [
        CandidatePatch("node-split-prologue-reorder-holder-ig40-b0-s10", source + "/*a*/", "new reorder", ((0, 0),)),
        CandidatePatch("node-split-assignment-chain-holder-ig40-b0-s20-o0", source + "/*b*/", "new chain", ((0, 0),)),
        CandidatePatch("node-split-operand-alias-holder-ig40-b0-s30-o0", source + "/*c*/", "new alias", ((0, 0),)),
        CandidatePatch("node-split-block-scope-holder-ig40-b0-s40-w2", source + "/*d*/", "new scope", ((0, 0),)),
        CandidatePatch("node-split-combo-holder-ig40-prologue-reorder+operand-alias-c0", source + "/*e*/", "combo", ((0, 0),)),
    ]

    ordered = node_set_split._order_node_set_patches_for_search(patches)
    first_families = [
        node_set_split._node_set_candidate_family(patch.candidate_id)
        for patch in ordered[:5]
    ]

    assert first_families == [
        "combo",
        "prologue-reorder",
        "assignment-chain",
        "operand-alias",
        "block-scope",
    ]
```

- [ ] **Step 2: Add failing tests for scanner safety**

Add:

```python
def test_node_set_simple_assignment_records_require_immediate_block_and_safe_rhs() -> None:
    source = (
        "void fn_test(void) {\n"
        "    f32 a;\n"
        "    f32 b;\n"
        "    f32 c;\n"
        "    a = b;\n"
        "    {\n"
        "        b = c;\n"
        "    }\n"
        "    c = call(a);\n"
        "}\n"
    )

    records = node_set_split._simple_assignment_records(source, "fn_test", class_id=1)

    by_lhs = {record.lhs: record for record in records}
    assert by_lhs["a"].block_id == 0
    assert by_lhs["b"].block_id != by_lhs["a"].block_id
    assert "c" not in by_lhs
```

Add the spec-required unsafe scanner coverage:

```python
@pytest.mark.parametrize(
    "source",
    [
        "void fn_test(void) { int a; int b; switch (a) { case 0: b = a; } }\n",
        "void fn_test(void) { int a; int b; a = b; /* preserve order */ b = a; }\n",
        "void fn_test(void) { int a; int b; a = (b, 1); b = a; }\n",
        "void fn_test(void) { int a; int b; a = b ? 1 : 2; b = a; }\n",
        "void fn_test(void) { int a; int b; a = b && 1; b = a; }\n",
        "void fn_test(void) { volatile int a; int b; a = b; b = a; }\n",
        "void fn_test(void) { int a; int b; take(&a); b = a; }\n",
        "void fn_test(void) { int a; int b; a++; b = a; }\n",
        "void fn_test(void) { int a; int b[2]; a = b[0]; b[1] = a; }\n",
        "void fn_test(void) { int a; int* p; a = *p; use(a); }\n",
        "void fn_test(void) { int a; int b; a += b; b = a; }\n",
    ],
)
def test_node_set_simple_assignment_records_reject_spec_unsafe_regions(source: str) -> None:
    records = node_set_split._simple_assignment_records(source, "fn_test", class_id=0)

    assert records == []
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
PYTEST_ADDOPTS=--no-cov pytest \
  tools/melee-agent/tests/test_node_set_split.py::test_node_set_patch_order_prioritizes_new_families_before_high_volume_legacy \
  tools/melee-agent/tests/test_node_set_split.py::test_node_set_simple_assignment_records_require_immediate_block_and_safe_rhs \
  tools/melee-agent/tests/test_node_set_split.py::test_node_set_simple_assignment_records_reject_spec_unsafe_regions -q
```

Expected: FAIL because the private helpers do not exist.

- [ ] **Step 4: Implement ordering constants and assignment records**

In `tools/melee-agent/src/mwcc_debug/node_set_split.py`, add imports and dataclasses near the existing private dataclasses:

```python
from collections import defaultdict
from hashlib import sha1
```

```python
_NODE_SET_PRIORITY_FAMILIES = (
    "combo",
    "prologue-reorder",
    "assignment-chain",
    "operand-alias",
    "block-scope",
)

@dataclass(frozen=True)
class _SimpleAssignmentRecord:
    lhs: str
    rhs: str
    start: int
    end: int
    line_end: int
    line: str
    block_id: int
    reads: tuple[str, ...]
    lhs_type: str
```

Add:

```python
def _node_set_candidate_family(candidate_id: str) -> str:
    if candidate_id.startswith("node-split-combo-"):
        return "combo"
    prefix = "node-split-"
    if not candidate_id.startswith(prefix):
        return "other"
    remainder = candidate_id[len(prefix):]
    for family in (
        "prologue-reorder",
        "assignment-chain",
        "operand-alias",
        "block-scope",
        "decl-order",
        "loop-rename",
        "reassoc",
        "introduce-binding",
        "alias",
        "lifetime",
    ):
        if remainder.startswith(f"{family}-"):
            return family
    return remainder.split("-", 1)[0] if remainder else "other"


def _order_node_set_patches_for_search(
    patches: list[CandidatePatch],
    *,
    cap: int | None = None,
    priority_families: tuple[str, ...] = _NODE_SET_PRIORITY_FAMILIES,
) -> list[CandidatePatch]:
    by_family: dict[str, list[CandidatePatch]] = defaultdict(list)
    family_order: list[str] = []
    for patch in patches:
        family = _node_set_candidate_family(patch.candidate_id)
        if family not in by_family:
            family_order.append(family)
        by_family[family].append(patch)

    ordered: list[CandidatePatch] = []
    round_families = [
        family for family in priority_families if family in by_family
    ] + [
        family for family in family_order if family not in priority_families
    ]
    while round_families:
        next_round: list[str] = []
        for family in round_families:
            bucket = by_family[family]
            if not bucket:
                continue
            ordered.append(bucket.pop(0))
            if cap is not None and len(ordered) >= cap:
                return ordered
            if bucket:
                next_round.append(family)
        round_families = next_round
    return ordered
```

Implement `_simple_assignment_records(source, function, class_id)` using the
line-level scanner from `statement_order.py` as the model: blank comments and
literals, compute brace block IDs, parse one-line assignments
`lhs = rhs;`, require safe scalar declarations from visible params/locals, and
reject unsafe RHS text or candidate regions with calls, members, arrays,
address/deref, compound operators, comments, labels, `case`/`default`,
preprocessor lines, order notes, comma, ternary, logical operators, volatile
declarations, address-taken names, increment/decrement, control-flow words, or
unknown identifiers.

- [ ] **Step 5: Verify foundation tests pass**

Run the same focused pytest command. Expected: PASS.

### Task 2: Prologue-Reorder And Block-Scope Families

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Add failing positive tests**

Add:

```python
def test_generate_node_set_split_patches_emits_prologue_reorder_candidate() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_spacing;\n"
        "    f32 y_offset;\n"
        "    f32 col_offset;\n"
        "    f32 row_offset;\n"
        "    f32 col;\n"
        "    f32 rowf;\n"
        "    col_offset = y_spacing * col;\n"
        "    row_offset = y_offset * rowf;\n"
        "    use(col_offset, row_offset);\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="row_offset")

    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)
    patch = next(p for p in patches if p.candidate_id.startswith("node-split-prologue-reorder-row_offset-ig33-"))

    assert patch.patched_source.index("row_offset = y_offset * rowf;") < patch.patched_source.index("col_offset = y_spacing * col;")
```

```python
def test_generate_node_set_split_patches_emits_block_scope_candidate() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 a;\n"
        "    f32 b;\n"
        "    f32 c;\n"
        "    a = b;\n"
        "    c = a;\n"
        "    use(c);\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="a")

    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)
    patch = next(p for p in patches if p.candidate_id.startswith("node-split-block-scope-a-ig33-"))

    assert "{\n    a = b;\n    c = a;\n}" in patch.patched_source
```

- [ ] **Step 2: Add failing negative tests**

Add:

```python
@pytest.mark.parametrize(
    "source",
    [
        "void fn_test(void) { int a; int b; a = b; if (a) { b = a; } }\n",
        "void fn_test(void) { int a; int b; a = call(); b = a; }\n",
        "void fn_test(void) { int a; int b; a = obj.x; b = a; }\n",
        "void fn_test(void) { int a; int b; a = b; label: b = a; }\n",
        "void fn_test(void) { int a; int b; a = b; #if 0\n b = a;\n#endif\n }\n",
    ],
)
def test_generate_node_set_split_patches_reorder_and_scope_reject_unsafe_regions(source: str) -> None:
    req = NodeSetSplitRequest("fn_test", 0, 40, target_reg="r30", var_name="a")

    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)

    assert not any(p.candidate_id.startswith("node-split-prologue-reorder-a-ig40-") for p in patches)
    assert not any(p.candidate_id.startswith("node-split-block-scope-a-ig40-") for p in patches)
```

Add a dependency-order test that rejects only prologue-reorder:

```python
def test_generate_node_set_split_patches_prologue_reorder_rejects_adjacent_dependency() -> None:
    source = "void fn_test(void) { int a; int b; a = b; b = a; }\n"
    req = NodeSetSplitRequest("fn_test", 0, 40, target_reg="r30", var_name="a")

    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)

    assert not any(
        patch.candidate_id.startswith("node-split-prologue-reorder-a-ig40-")
        for patch in patches
    )
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_node_set_split.py -k 'prologue_reorder or block_scope or reorder_and_scope' -q
```

Expected: FAIL because the families do not exist.

- [ ] **Step 4: Implement helpers**

Add `_append_prologue_reorder_patches(...)` and
`_append_block_scope_patches(...)`. Both must snapshot and roll back on
exception. Prologue reorder swaps adjacent `_SimpleAssignmentRecord` lines when
they share `block_id`, are contiguous, have independent reads/writes, and the
request variable appears in either assignment. Block scope wraps windows of 1
to 3 adjacent assignment records in the same block when the request variable
appears in the window.

Call both helpers from the base patch generator.

- [ ] **Step 5: Verify tests pass**

Run the same focused pytest command. Expected: PASS.

### Task 3: Assignment-Chain Family

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Add failing positive and negative tests**

Add:

```python
def test_generate_node_set_split_patches_emits_assignment_chain_candidate() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_offset;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = y_offset * rowf - 0.4f;\n"
        "    use(row_offset_adj);\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="row_offset_adj")

    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)
    patch = next(p for p in patches if p.candidate_id.startswith("node-split-assignment-chain-row_offset_adj-ig33-"))

    assert "row_offset_adj = row_offset - 0.4f;" in patch.patched_source
```

```python
@pytest.mark.parametrize(
    "source",
    [
        (
            "typedef float f32;\n"
            "void fn_test(void) { f32 y_offset; f32 rowf; f32 row_offset; f32 out; "
            "row_offset = y_offset * rowf; y_offset = 1.0f; out = y_offset * rowf - 0.4f; }\n"
        ),
        (
            "typedef float f32;\n"
            "void fn_test(void) { f32 y_offset; double rowf; f32 row_offset; f32 out; "
            "row_offset = y_offset * rowf; out = y_offset * rowf - 0.4f; }\n"
        ),
        (
            "void fn_test(void) { int a; unsigned int b; int tmp; int out; "
            "tmp = a + b; out = a + b + 1; }\n"
        ),
    ],
)
def test_generate_node_set_split_patches_assignment_chain_rejects_unsafe_rewrites(source: str) -> None:
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="out")

    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)

    assert not any(p.candidate_id.startswith("node-split-assignment-chain-out-ig33-") for p in patches)
```

Add a separate GPR signedness test so the integer rule is exercised with
`class_id=0`:

```python
def test_generate_node_set_split_patches_assignment_chain_rejects_gpr_signedness_mix() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int a;\n"
        "    unsigned int b;\n"
        "    int tmp;\n"
        "    int out;\n"
        "    tmp = a + b;\n"
        "    out = a + b + 1;\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 0, 40, target_reg="r30", var_name="out")

    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)

    assert not any(p.candidate_id.startswith("node-split-assignment-chain-out-ig40-") for p in patches)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_node_set_split.py -k assignment_chain -q
```

Expected: FAIL because assignment-chain is not implemented.

- [ ] **Step 3: Implement assignment-chain**

Add `_append_assignment_chain_patches(...)`. Use `_SimpleAssignmentRecord`
pairs in the same `block_id`. For each earlier/later pair, require no
intervening writes to the earlier LHS or the expression's read identifiers.
Require type compatibility with helper functions:

```python
def _same_safe_scalar_type_class(type_a: str, type_b: str, class_id: int) -> bool:
    norm_a = _normalize_node_set_scalar_type(type_a)
    norm_b = _normalize_node_set_scalar_type(type_b)
    if norm_a is None or norm_b is None:
        return False
    if class_id == 1:
        return norm_a == norm_b and norm_a in {"f32", "f64"}
    if class_id == 0:
        return norm_a == norm_b and norm_a in {
            "s8", "s16", "s32", "s64", "u8", "u16", "u32", "u64", "ptr",
        }
    return False
```

Only rewrite a full parsed RHS occurrence by byte offset. Candidate IDs include
the earlier record start, later record start, and occurrence index. The helper
must snapshot `patches` and `seen_sources`, then roll back on exception without
leaking partially appended assignment-chain candidates.

- [ ] **Step 4: Verify tests pass**

Run the same focused pytest command. Expected: PASS.

### Task 4: Operand-Alias Family

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Add failing tests**

Add:

```python
def test_generate_node_set_split_patches_emits_operand_alias_candidate() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_spacing;\n"
        "    f32 col;\n"
        "    f32 col_offset;\n"
        "    col_offset = y_spacing * col;\n"
        "    use(col_offset);\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="col_offset")

    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)
    patch = next(p for p in patches if p.candidate_id.startswith("node-split-operand-alias-col_offset-ig33-"))

    assert "f32 y_spacing_alias_33_0;" in patch.patched_source
    assert "y_spacing_alias_33_0 = y_spacing;" in patch.patched_source
    assert "col_offset = y_spacing_alias_33_0 * col;" in patch.patched_source
```

```python
def test_generate_node_set_split_patches_operand_alias_rejects_mixed_declaration_statement_block() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_spacing;\n"
        "    use(y_spacing);\n"
        "    f32 col_offset;\n"
        "    col_offset = y_spacing;\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="col_offset")

    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)

    assert not any(p.candidate_id.startswith("node-split-operand-alias-col_offset-ig33-") for p in patches)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_node_set_split.py -k operand_alias -q
```

Expected: FAIL because operand-alias is not implemented.

- [ ] **Step 3: Implement operand-alias**

Add `_append_operand_alias_patches(...)`. Find simple identifier operands in
safe assignment RHS records. Insert the alias declaration at the immediate
block's legal declaration insertion point, insert the alias assignment before
the target statement, and rewrite exactly one operand occurrence. Abstain if
the target statement is inside the declaration section or if the operand has no
unique compatible scalar type. The helper must snapshot `patches` and
`seen_sources`, then roll back on exception without leaking partially appended
operand-alias candidates.

- [ ] **Step 4: Verify tests pass**

Run the same focused pytest command. Expected: PASS.

### Task 5: Composite Candidates And Coupled Cap Coverage

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Add failing composite and coupled tests**

Add:

```python
def test_generate_node_set_split_patches_emits_combo_for_reorder_chain_alias() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_spacing;\n"
        "    f32 y_offset;\n"
        "    f32 col;\n"
        "    f32 rowf;\n"
        "    f32 tmp;\n"
        "    f32 other;\n"
        "    f32 out;\n"
        "    tmp = y_offset * rowf;\n"
        "    other = y_spacing * col;\n"
        "    out = y_offset * rowf - 0.4f;\n"
        "    use(other, out);\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="out")

    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)
    combo_ids = [p.candidate_id for p in patches if p.candidate_id.startswith("node-split-combo-out-ig33-")]

    assert any(
        "prologue-reorder" in cid
        and "assignment-chain" in cid
        and "operand-alias" in cid
        and re.search(r"-c\d+-[0-9a-f]{6}$", cid)
        for cid in combo_ids
    )
```

```python
def test_coupled_node_set_split_default_cap_keeps_new_family_candidates() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_spacing; f32 y_offset; f32 col; f32 rowf;\n"
        "    f32 col_offset; f32 row_offset; f32 row_offset_adj; f32 other;\n"
        "    col_offset = y_spacing * col;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = y_offset * rowf - 0.4f;\n"
        "    other = col_offset;\n"
        "    use(other, row_offset_adj);\n"
        "}\n"
    )
    requests = [
        NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="row_offset_adj"),
        NodeSetSplitRequest("fn_test", 1, 34, target_reg="f29", var_name="other"),
    ]

    patches = generate_coupled_node_set_split_patches(
        source, "fn_test", requests, max_read_sites=4, max_candidates=16
    )
    joined = "\n".join(p.summary + " " + p.candidate_id for p in patches)

    assert "prologue-reorder" in joined
    assert "assignment-chain" in joined
    assert "operand-alias" in joined
    assert "block-scope" in joined
```

Add candidate provenance and rollback coverage:

```python
def test_node_set_new_family_candidate_ids_are_unique_for_multiple_occurrences() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 a; f32 b; f32 tmp; f32 out;\n"
        "    tmp = a * b;\n"
        "    out = (a * b) + (a * b);\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="out")

    patches = [
        patch for patch in generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)
        if patch.candidate_id.startswith("node-split-assignment-chain-out-ig33-")
    ]

    assert len(patches) >= 2
    assert len({patch.candidate_id for patch in patches}) == len(patches)
```

```python
def test_node_set_new_family_helper_rolls_back_partial_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 a; f32 b; f32 c;\n"
        "    a = b;\n"
        "    c = a;\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="a")
    original_append = node_set_split._append_unique_patch
    calls = 0

    def append_once_then_fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        original_append(*args, **kwargs)
        if calls == 1:
            raise RuntimeError("late family failure")

    monkeypatch.setattr(node_set_split, "_append_unique_patch", append_once_then_fail)

    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)

    new_family_prefixes = (
        "node-split-prologue-reorder-a-ig33-",
        "node-split-combo-a-ig33-",
    )
    assert not any(
        p.candidate_id.startswith(new_family_prefixes)
        for p in patches
    )
```

Add a composite-specific rollback test:

```python
def test_node_set_combo_generation_discards_failed_partial_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_spacing; f32 y_offset; f32 col; f32 rowf;\n"
        "    f32 tmp; f32 other; f32 out;\n"
        "    tmp = y_offset * rowf;\n"
        "    other = y_spacing * col;\n"
        "    out = y_offset * rowf - 0.4f;\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="out")
    original_append = node_set_split._append_unique_patch

    def fail_on_combo_append(patches, seen_sources, original_source, patched_source, *, candidate_id, summary):
        original_append(
            patches,
            seen_sources,
            original_source,
            patched_source,
            candidate_id=candidate_id,
            summary=summary,
        )
        if candidate_id.startswith("node-split-combo-out-ig33-"):
            raise RuntimeError("combo branch failed after append")

    monkeypatch.setattr(node_set_split, "_append_unique_patch", fail_on_combo_append)

    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=1)

    assert not any(
        p.candidate_id.startswith("node-split-combo-out-ig33-")
        for p in patches
    )
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_node_set_split.py -k 'combo or default_cap' -q
```

Expected: FAIL because combo generation and coupled family balancing are not
implemented.

- [ ] **Step 3: Implement composite generation and coupled ordering**

Refactor `generate_node_set_split_patches()` so base family generation can be
called with a family filter. Add `_append_composite_node_set_patches(...)` with
depth 3, no repeated family, at most 2 expansions per family per layer, and at
most 24 outputs. Composite generation must use only `prologue-reorder`,
`assignment-chain`, `operand-alias`, and `block-scope`, and each expansion must
re-run that family helper on the already patched source before accepting the
next step. Run `_order_node_set_patches_for_search()` after combo generation
and before returning patches to CLI scoring. Composite IDs must include the
family chain plus both a sequence number and a short SHA-1 digest of the
patched source, for example
`node-split-combo-row_offset_adj-ig33-prologue-reorder+assignment-chain-c0-a1b2c3`,
so two different combo patches cannot collide. The composite helper must
snapshot `patches` and `seen_sources`, then roll back on exception without
leaking partially appended combo candidates.

In `generate_coupled_node_set_split_patches()`, change the default
`max_per_ig` to 12 and order `singles` before taking from them.

- [ ] **Step 4: Verify tests pass**

Run the same focused pytest command. Expected: PASS.

### Task 6: Regression Suite, Live Smoke, And Resolution

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 0: Guard unrelated dirty files**

Run:

```bash
git status --short -- \
  tools/melee-agent/src/cli/debug/__init__.py \
  tools/melee-agent/src/search/solver/solve.py \
  tools/melee-agent/tests/search/solver/test_solve.py \
  docs/matching-tooling-postmortem-2026-06-15.md
```

Expected: any output is unrelated local work. Do not stage, revert, or rewrite
those paths for #732.

- [ ] **Step 1: Run the full node-set split test file**

Run:

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_node_set_split.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run syntax and CLI smoke checks**

Run:

```bash
python -m compileall -q tools/melee-agent/src/cli tools/melee-agent/src/mwcc_debug
cd tools/melee-agent && python -m src.cli debug solve node-set-split --help >/tmp/node-set-split-help.txt
rg "node-set-split|--max-candidates|--coupled" /tmp/node-set-split-help.txt
```

Expected: compileall exits 0 and help text contains the command/options.

- [ ] **Step 3: Run bounded live smoke for `mnDiagram_80241E78`**

Run:

```bash
mkdir -p build/issue732
melee-agent debug solve coloring -f mnDiagram_80241E78 --class fpr --json > build/issue732/80241E78-coloring.raw
python - <<'PY'
from pathlib import Path
text = Path("build/issue732/80241E78-coloring.raw").read_text()
start = text.find("{")
Path("build/issue732/80241E78-coloring.json").write_text(text[start:])
PY
melee-agent debug solve node-set-split \
  --coupled \
  --node-set-delta build/issue732/80241E78-coloring.json \
  --json \
  --budget 180 \
  --max-candidates 32 > build/issue732/80241E78-node-set-split.raw
rg "node-split-(combo|prologue-reorder|assignment-chain|operand-alias|block-scope)|realized|wrong-register|compile-failed" build/issue732/80241E78-node-set-split.raw
python - <<'PY'
import json
from pathlib import Path

priority = {
    "combo",
    "prologue-reorder",
    "assignment-chain",
    "operand-alias",
    "block-scope",
}

def family(candidate_id: str) -> str | None:
    if candidate_id.startswith("node-split-combo-"):
        return "combo"
    for name in priority - {"combo"}:
        if candidate_id.startswith(f"node-split-{name}-"):
            return name
    return None

text = Path("build/issue732/80241E78-node-set-split.raw").read_text()
payload = json.loads(text[text.find("{"):])
families = {
    fam for row in payload.get("candidates", [])
    for fam in [family(str(row.get("candidate_id", "")))]
    if fam is not None
}
realized = [
    row for row in payload.get("candidates", [])
    if family(str(row.get("candidate_id", ""))) is not None
    and row.get("objective_status") == "realized"
]
Path("build/issue732/80241E78-family-evidence.json").write_text(json.dumps({
    "families": sorted(families),
    "realized_ids": [row.get("candidate_id") for row in realized],
}, indent=2))
print("families", sorted(families))
print("realized", [row.get("candidate_id") for row in realized])
PY
```

Expected: at least one new-family or combo candidate ID appears. If any
new-family or combo row has `objective_status == "realized"`, the issue stop
condition is satisfied.

- [ ] **Step 4: If needed, run bounded live smoke for `8023FC28`**

Only run this step if `mnDiagram_80241E78` does not produce a realization.
Use the same commands with the function name replaced by `8023FC28`, and save
outputs under `build/issue732/8023FC28-*`.

Expected: either a new-family/combo `realized` row appears, or all four
families and combos are represented and triaged without improvement across both
functions. Prove this with the same JSON inspection script and save
`build/issue732/8023FC28-family-evidence.json`.

- [ ] **Step 5: Commit implementation**

Stage only files touched for this issue:

```bash
git add \
  tools/melee-agent/src/mwcc_debug/node_set_split.py \
  tools/melee-agent/tests/test_node_set_split.py
git commit -m "feat(melee-agent): expand node-set split source families"
```

- [ ] **Step 6: Refresh editable install and resolve #732**

Run:

```bash
repo_root="$(git rev-parse --show-toplevel)"
/opt/homebrew/opt/python@3.11/bin/python3.11 -m pip install -e "${repo_root}/tools/melee-agent"
/opt/homebrew/opt/python@3.11/bin/python3.11 - <<'PY'
import inspect
import src.mwcc_debug.node_set_split as nss
print(inspect.getfile(nss))
PY
commit="$(git rev-parse HEAD)"
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent issue resolve 732 --note "fixed in ${commit}: added prologue-reorder, assignment-chain, operand-alias, block-scope, bounded combos, family-balanced ordering, tests, and live smoke evidence"
melee-agent issue list
```

Expected: import path points at `/Users/mike/code/melee/tools/melee-agent`, #732
is resolved only if the live stop condition from the spec is met, and the issue
queue is empty or only contains separately claimed/in-actionable issues.
