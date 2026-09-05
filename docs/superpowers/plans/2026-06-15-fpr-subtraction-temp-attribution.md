# FPR Subtraction Temp Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make FPR subtraction temps from solve-coloring node-set evidence source-bindable when they correspond to unique floating local assignments.

**Architecture:** Extend the existing `virtual_attribution` FPR expression-order bridge. The node-set-split request parser and coupled generator should not need new control flow; they will consume richer `name`, `type`, and `expression` metadata from solve-coloring/virtual attribution.
The node-set-split eligibility gate should also reject unsafe typed expressions before coupled composition.

**Tech Stack:** Python, Typer CLI, pytest, existing `mwcc_debug` parser and virtual attribution helpers.

---

### Task 1: Regression Tests

**Files:**
- Modify: `tools/melee-agent/tests/test_virtual_attribution.py`
- Modify: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Add the failing FPR subtraction attribution test**

Append this test after `test_explain_virtuals_binds_fpr_product_to_float_local_assignment`:

```python
def test_explain_virtuals_binds_fpr_subtraction_to_float_local_assignment() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000006
        BEFORE REGISTER COLORING
        fn_80000006
        B0: Succ={} Pred={} Labels={}
            fsubs f36,f42,f41
            lfd f44,@192(r0)
            lfd f45,@1518(r1)
            fsubs f46,f45,f44
            fmuls f38,f35,f49
            lfs f50,@1517(r0)
            fsubs f33,f38,f50
        COLORGRAPH DECISIONS (class=1, result=1, n_nodes=2)
          iter ig_idx phys degree nIntfr flags
            0 36 r27 0 0 0x00
            1 33 r28 0 0 0x00
    """)
    source = textwrap.dedent("""\
        typedef float f32;
        void fn_80000006(f32 base, f32 y_offset, f32 row) {
            f32 y_spacing;
            f32 row_offset;
            f32 row_offset_adj;
            y_spacing = y_offset - base;
            row_offset = y_offset * row;
            row_offset_adj = row_offset - 0.4f;
            sink(y_spacing, row_offset_adj);
        }
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000006",
        virtuals=[36, 33],
        source_text=source,
        source_file="sample.c",
        reg_class="fpr",
    )

    by_virtual = {entry.virtual: entry for entry in report.virtuals}
    first = by_virtual[36].source
    second = by_virtual[33].source
    assert first is not None
    assert first.kind == "local"
    assert first.confidence == "fpr-expression-order"
    assert first.name == "y_spacing"
    assert first.type == "f32"
    assert first.expression == "y_offset - base"
    assert second is not None
    assert second.kind == "local"
    assert second.confidence == "fpr-expression-order"
    assert second.name == "row_offset_adj"
    assert second.type == "f32"
    assert second.expression == "row_offset - 0.4f"
```

- [ ] **Step 2: Add the failing node-set request routing test**

Append this test near `test_requests_from_node_set_delta_can_include_introducible_entries`:

```python
def test_requests_from_node_set_delta_keeps_fpr_subtraction_local_in_coupled_set() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(f32 y_spacing, f32 col, f32 row_offset) {\n"
        "    f32 col_offset;\n"
        "    f32 row_offset_adj;\n"
        "    col_offset = y_spacing * col;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    sink(col_offset, row_offset_adj);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [
            {
                "target_ig": 32,
                "current_register": "f26",
                "desired_registers": ["f0"],
                "source": {
                    "kind": "local",
                    "name": "col_offset",
                    "type": "f32",
                    "expression": "y_spacing * col",
                },
            },
            {
                "target_ig": 33,
                "current_register": "f27",
                "desired_registers": ["f28"],
                "source": {
                    "kind": "local",
                    "name": "row_offset_adj",
                    "type": "f32",
                    "expression": "row_offset - 0.4f",
                },
            },
        ],
    }

    reqs = requests_from_node_set_delta(
        delta,
        source_text=source,
        include_introducible=True,
        max_requests=0,
    )

    assert [req.target_ig for req in reqs] == [32, 33]
    assert [req.var_name for req in reqs] == ["col_offset", "row_offset_adj"]
    assert [req.class_id for req in reqs] == [1, 1]
    assert [req.target_reg for req in reqs] == ["f0", "f28"]
```

- [ ] **Step 3: Add the unsafe introducible eligibility regression**

Append a test near the introducible request tests that builds a node-set delta
with a normal bindable local plus an unbindable typed call expression such as
`get_value(i)`. With `include_introducible=True`, assert only the bindable local
survives.

- [ ] **Step 4: Run RED tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_virtual_attribution.py::test_explain_virtuals_binds_fpr_subtraction_to_float_local_assignment \
  tools/melee-agent/tests/test_node_set_split.py::test_requests_from_node_set_delta_keeps_fpr_subtraction_local_in_coupled_set \
  tools/melee-agent/tests/test_node_set_split.py::test_requests_from_node_set_delta_rejects_unsafe_introducible_entries
```

Expected: the virtual-attribution test fails because `fsubs` stays `pcode-first-def`; the unsafe introducible test fails because the call expression is still included; the node-set request test may already pass because it exercises the downstream parser with already-attributed metadata.

### Task 2: Implement Guarded FPR Subtraction Attribution

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/virtual_attribution.py`

- [ ] **Step 1: Add subtraction operators to the existing map**

Change `_FPR_SOURCE_EXPR_OPS` to include:

```python
_FPR_SOURCE_EXPR_OPS = {
    "fmul": "*",
    "fmuls": "*",
    "fsub": "-",
    "fsubs": "-",
}
```

- [ ] **Step 2: Add conversion-skip helper**

Add helper functions near `_fpr_source_expr_rank`:

```python
def _is_conversion_subtract(instr, block) -> bool:
    if instr.opcode.lower() not in {"fsub", "fsubs"} or len(instr.regs) < 3:
        return False
    src_regs = [num for kind, num in instr.regs[1:3] if kind == "f"]
    if len(src_regs) != 2:
        return False
    seen_lfd: set[int] = set()
    for earlier in block.instructions:
        if earlier is instr:
            break
        if earlier.opcode.lower() != "lfd" or len(earlier.regs) < 1:
            continue
        kind, num = earlier.regs[0]
        if kind == "f":
            seen_lfd.add(num)
    return all(num in seen_lfd for num in src_regs)
```

Then skip these instructions in `_fpr_source_expr_rank` before incrementing the rank.

- [ ] **Step 3: Add compound subtraction source candidates**

Add a regex near `_PLAIN_ASSIGNMENT_RE`:

```python
_COMPOUND_FLOAT_SUB_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)"
    r"(?P<lhs>[A-Za-z_][A-Za-z_0-9]*)"
    r"[ \t]*-=[ \t]*(?P<rhs>[^;\n]+);[ \t]*$"
)
```

In `_source_from_fpr_expression_assignment`, after collecting plain assignments,
also collect `lhs -= rhs` when the operator is `"-"` and `lhs` is a unique floating scalar. Store expression as `f"{lhs} - {rhs}"`, with the same line/column handling as plain assignments.

- [ ] **Step 4: Tighten introducible eligibility**

Update `is_node_set_request_introducible` so it requires
`_source_expression_is_safe_to_bind(request.source_expression)`.

- [ ] **Step 5: Run GREEN tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_virtual_attribution.py::test_explain_virtuals_binds_fpr_product_to_float_local_assignment \
  tools/melee-agent/tests/test_virtual_attribution.py::test_explain_virtuals_binds_fpr_subtraction_to_float_local_assignment \
  tools/melee-agent/tests/test_node_set_split.py::test_requests_from_node_set_delta_keeps_fpr_subtraction_local_in_coupled_set \
  tools/melee-agent/tests/test_node_set_split.py::test_requests_from_node_set_delta_rejects_unsafe_introducible_entries
```

Expected: all pass.

### Task 3: Live CLI Evidence

**Files:**
- No production file changes.
- Create ignored evidence under `build/issue727/` if useful.

- [ ] **Step 1: Refresh local pcdump cache for both reported functions**

Run:

```bash
melee-agent debug dump local src/melee/mn/mndiagram.c --function mnDiagram_80241E78
melee-agent debug dump local src/melee/mn/mndiagram.c --function mnDiagram_8023FC28
```

Expected: commands complete without stale-cache warnings on subsequent smokes.

- [ ] **Step 2: Run focused unit and compile checks**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_virtual_attribution.py \
  tools/melee-agent/tests/test_node_set_split.py \
  tools/melee-agent/tests/search/solver/test_cli_solve.py
python -m compileall -q tools/melee-agent/src
git diff --check
```

Expected: all pass.

- [ ] **Step 3: Run real #727 smokes**

Run solve-coloring and node-set-split for both functions. Save raw JSON under `build/issue727/` and inspect:

```bash
mkdir -p build/issue727
melee-agent debug solve coloring -f mnDiagram_80241E78 --class fpr --json > build/issue727/80241E78-solve-coloring.json
melee-agent debug solve node-set-split --coupled --node-set-delta build/issue727/80241E78-solve-coloring.json --json --budget 180 --max-candidates 0 > build/issue727/80241E78-node-set-split.raw
melee-agent debug inspect virtual-to-var -f mnDiagram_80241E78 --class fpr 38 --json > build/issue727/80241E78-fpr38-virtual-to-var.json
melee-agent debug solve coloring -f mnDiagram_8023FC28 --class gpr --json > build/issue727/8023FC28-solve-coloring.json
melee-agent debug solve node-set-split --coupled --node-set-delta build/issue727/8023FC28-solve-coloring.json --json --budget 120 --max-candidates 0 > build/issue727/8023FC28-node-set-split.raw
```

Expected: direct `virtual-to-var` inspection attributes the `80241E78`
subtraction virtual to `row_offset_adj` with type `f32`. The refreshed
`solve-coloring` residual may no longer include that virtual in its coupled
node-set payload; in the verified run it instead produced bindable product
locals plus a remaining raw `lfs`. `8023FC28` remains raw pcode for the address
cursor unless a later safe cursor bridge exists. If no candidate improves,
resolve #727 with the direct FPR subtraction attribution evidence plus explicit
GPR/raw-load triage.
