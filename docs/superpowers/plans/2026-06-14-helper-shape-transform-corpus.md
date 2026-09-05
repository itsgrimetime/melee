# Helper Shape Transform-Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add guarded executable `helper_shape` transform-corpus probes for simple helper inlining and repeated-expression helper extraction.

**Architecture:** Reuse the existing `Anchor` and `apply_mutator` path. Target-body helper-independent anchors stay in `anchors.py`; helper-boundary anchors that need full-file function definitions live in `transform_corpus.py`, alongside string/data, global-alias, and raw-offset full-source anchors.

**Tech Stack:** Python 3.11, pytest, existing `src.search.directed` transform-corpus modules, `src.mwcc_debug.source_patch.find_function_definitions`.

---

### Task 1: Red Tests For Helper Metadata And Probes

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/search/directed/test_mutators.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`

- [ ] **Step 1: Add failing metadata and probe tests**

Add tests that expect:

```python
helper = by_id["helper_shape"]
assert helper.mutator_keys == (
    "inline_simple_helper_call",
    "extract_repeated_assignment_helper",
)
assert "record-only" not in helper.generated_probe_form
```

Add a probe fixture with:

```c
static s32 add_bonus(s32 base, s32 inc) {
    return base + inc;
}

void target(s32 arg0, s32 arg1) {
    score = add_bonus(arg0, arg1);
}
```

and assert `generate_transform_probes(..., families=("helper_shape",))` emits `score = (arg0 + arg1);`.
Also assert the inline probe payload includes:

```python
from src.search.directed.transform_probe_adapter import transform_probe_key

assert inline.family_id == "helper_shape"
assert inline.mutator_key == "inline_simple_helper_call"
assert inline.probe_id == "helper_shape@0"
assert inline.span[0] < inline.span[1]
assert transform_probe_key(inline) == "transform-corpus:helper_shape:0"
assert inline.payload["helper_name"] == "add_bonus"
assert inline.payload["return_expr"] == "base + inc"
assert inline.payload["parameter_map"] == (("base", "arg0"), ("inc", "arg1"))
assert isinstance(inline.payload["helper_span"], tuple)
```

Add a repeated RHS extraction fixture with two assignments:

```c
void target(s32 arg0, s32 arg1) {
    s32 left;
    s32 right;
    left = arg0 + arg1;
    right = arg0 + arg1;
}
```

and assert the candidate inserts `static s32 target__helper_shape_0(s32 arg0, s32 arg1)` before `target` and rewrites both assignments to helper calls.
Also assert the extraction probe payload includes:

```python
assert extracted.family_id == "helper_shape"
assert extracted.mutator_key == "extract_repeated_assignment_helper"
assert extracted.probe_id.startswith("helper_shape@")
assert extracted.span[0] < extracted.span[1]
assert transform_probe_key(extracted).startswith("transform-corpus:helper_shape:")
assert extracted.payload["helper_name"] == "target__helper_shape_0"
assert extracted.payload["target_function"] == "target"
assert extracted.payload["rhs"] == "arg0 + arg1"
assert extracted.payload["operand_order"] == ("arg0", "arg1")
assert extracted.payload["operand_types"] == (("arg0", "s32"), ("arg1", "s32"))
assert len(extracted.payload["line_replacements"]) == 2
```

- [ ] **Step 2: Add failing mutator unit tests**

Add direct `apply_mutator` tests for:

```python
Anchor(
    "inline_simple_helper_call",
    (0, 0),
    {"line": "    score = add_bonus(arg0, arg1);", "replacement_line": "    score = (arg0 + arg1);"},
)
```

and:

```python
Anchor(
    "extract_repeated_assignment_helper",
    (0, 0),
    {
        "insert_before": "void target(s32 arg0, s32 arg1) {",
        "helper_text": "static s32 target__helper_shape_0(s32 arg0, s32 arg1) {\n    return arg0 + arg1;\n}\n\n",
        "line_replacements": (
            ("    left = arg0 + arg1;", "    left = target__helper_shape_0(arg0, arg1);"),
            ("    right = arg0 + arg1;", "    right = target__helper_shape_0(arg0, arg1);"),
        ),
        "helper_name": "target__helper_shape_0",
        "target_function": "target",
        "rhs": "arg0 + arg1",
        "operand_order": ("arg0", "arg1"),
        "operand_types": (("arg0", "s32"), ("arg1", "s32")),
    },
)
```

- [ ] **Step 3: Run red tests**

Run:

```bash
python -m pytest \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/test_source_transform_catalog.py -q
```

Expected: fails because helper mutators are not registered and `helper_shape` is still record-only.

### Task 2: Register Helper Mutators

**Files:**
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `docs/source-transform-catalog.md`

- [ ] **Step 1: Implement line-replacement mutators**

Add:

```python
def _inline_simple_helper_call(anchor: Anchor, source_text: str) -> Optional[str]:
    return _replace_exact_line_at_anchor(anchor, source_text)
```

Add an extraction mutator that inserts `helper_text` before `insert_before`, rejects pre-existing helper text, and applies each exact line replacement once. If any line is absent, duplicated ambiguously, or replacement makes no change, return `None`.

- [ ] **Step 2: Register dispatch and family metadata**

Add both mutator keys to `_DISPATCH`. Update `helper_shape` in `DEFAULT_TRANSFORM_FAMILIES` to use those keys and describe guarded inline/extract forms. Add `helper_shape` to the generic fallback cluster.

- [ ] **Step 3: Update catalog counts and docs**

Add both keys to `DIRECTED_MUTATOR_KEYS`. Update expected directed concrete forms from 25 to 27 and headline concrete forms from 78 to 80. Update `docs/source-transform-catalog.md` so `helper_shape` is listed among concrete guarded families, not record-only families.

- [ ] **Step 4: Run metadata/mutator tests**

Run:

```bash
python -m pytest \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/test_source_transform_catalog.py -q
```

Expected: mutator and catalog tests pass; probe tests may still fail until anchors are implemented.

### Task 3: Implement Full-Source Helper Anchors

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`

- [ ] **Step 1: Add helper parsing helpers**

Implement helpers for:

- Parsing simple static helper signatures into scalar return type, helper name, and scalar `(type, name)` params.
- Extracting eligible static helper expressions from single-return or assign-then-return bodies.
- Rejecting inline helper expressions that reference any identifier outside the helper parameter names.
- Rejecting inline helper expressions where any referenced parameter type differs from the helper return type.
- Finding single-line target call sites outside comments/literals.
- Substituting parameter identifiers using token-boundary replacements.
- Building source-local scalar type maps from function params and simple local declarations.
- Finding repeated simple assignment RHS groups and constructing one generated helper per group.

- [ ] **Step 2: Add safety guards**

Reject helper bodies or extraction RHS expressions when they contain:

```text
#, {, }, case, default, goto, if, for, while, do, switch, return ... return,
++ --, assignment inside RHS, top-level comma, &&, ||, pointer/member access,
address/deref operators, array indexing, direct calls, indirect calls
```

Reject helper signatures with pointer returns or pointer parameters. Reject inlining unless every call argument is a bare scalar identifier or integer literal and every parameter referenced by the helper expression has the helper return type. Reject extraction unless every RHS operand has a scalar source-local type and every assignment destination in the repeated group has the same scalar type.

Add explicit unsafe tests for:

```c
static s32 add_bonus(s32 base) {
    return base + bonus;
}

void target(s32 arg0) {
    s32 bonus;
    score = add_bonus(arg0);
}
```

Expected: no `helper_shape` inline probe, because `bonus` is a free helper identifier that could be captured by the target local.

Add explicit unsafe tests for helper return conversions:

```c
typedef signed char s8;
typedef int s32;
static s8 narrow(s32 base) {
    return base;
}

void target(s32 arg0) {
    score = narrow(arg0);
}
```

Expected: no `helper_shape` inline probe, because replacing `narrow(arg0)` with `arg0` would drop the helper return conversion.

- [ ] **Step 3: Yield anchors**

Add `_iter_helper_shape_anchors(source_text, function, span)` to yield `inline_simple_helper_call` and `extract_repeated_assignment_helper` anchors, and call it from `_iter_full_source_anchors`.

- [ ] **Step 4: Run transform-corpus tests**

Run:

```bash
python -m pytest tools/melee-agent/tests/search/directed/test_transform_corpus.py -q
```

Expected: helper probe tests pass, common `TransformProbe` provenance assertions pass, helper-specific payload assertions pass, and unsafe fixtures reject free identifiers, target-local name capture, helper return conversions, pointer/member access, direct calls, indirect calls, preprocessor regions, labels/case/default, multiple exits, and evaluation-order-changing substitutions.

### Task 4: Command Smoke And Issue Resolution

**Files:**
- No source files beyond Tasks 1-3.

- [ ] **Step 1: Run focused test set**

Run:

```bash
python -m pytest \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/test_source_transform_catalog.py -q
python -m py_compile \
  tools/melee-agent/src/search/directed/anchors.py \
  tools/melee-agent/src/search/directed/mutators.py \
  tools/melee-agent/src/search/directed/transform_corpus.py \
  tools/melee-agent/src/mwcc_debug/source_transform_catalog.py
git diff --check
```

- [ ] **Step 2: Run CLI smoke**

Create a temporary source with one inlineable helper and one repeated RHS extraction shape. Run:

```bash
python -m src.cli debug search plan-transforms \
  -f target -u melee/test/target --force-phys 1:3 \
  --source-file "$tmp_source" \
  --write-probes "$tmp_out" --json
```

Expected: JSON includes `helper_shape` probes and `$tmp_out` contains candidate files for both helper mutators.

Then run a consumer filter smoke:

```bash
python -m src.cli debug mutate lifetime-layout \
  -f target --pcdump "$synthetic_pcdump" \
  --source-file "$tmp_source" \
  --include-transform-corpus \
  --transform-family helper_shape \
  --transform-force-phys 1:3 \
  --no-compile-probes --json
```

Expected: emitted transform-corpus provenance is limited to `helper_shape`.

- [ ] **Step 3: Commit and resolve #687**

Stage the implementation, docs, and tests. Commit with:

```bash
git commit -m "Add helper shape transform probes"
```

Resolve issue #687 only after the tests and smoke pass.
