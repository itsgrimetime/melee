# Loop-Shape Expanded Structure Axis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a source-retained `loop-shape-expanded` structure-search axis for MN sorted-list visible-entry scan loops.

**Architecture:** Keep the implementation in `tools/melee-agent/src/search/structure.py`, following the existing `statement-order` and `inline-boundary` source-axis patterns. Add tests in `tools/melee-agent/tests/search/test_structure.py` and rely on the existing scorer to compile/checkdiff retained variants when `--score` is enabled.

**Tech Stack:** Python 3.11, pytest, Typer CLI, existing structure-search dataclasses and source masking helpers.

---

## File Structure

- Modify `tools/melee-agent/src/search/structure.py`: add the axis constant, generator, helpers, payload future-axis filtering, and run wiring.
- Modify `tools/melee-agent/tests/search/test_structure.py`: add unit and run-level regression coverage.
- Commit this plan and the matching spec with the implementation.

## Task 1: Axis Wiring And Future-Axis Contract

**Files:**
- Modify: `tools/melee-agent/src/search/structure.py`
- Test: `tools/melee-agent/tests/search/test_structure.py`

- [ ] **Step 1: Write the failing run-level test**

Add a test that writes a small sorted-name scan source, runs:

```python
payload = run_structure_search(
    "fn_80000000",
    source_path,
    tmp_path / "structure",
    axes=("loop-shape-expanded",),
    max_candidates=8,
    score_variants=False,
)
```

Assert:

```python
assert payload["axes"][0]["axis"] == "loop-shape-expanded"
assert payload["axes"][0]["status"] == "evaluated"
assert payload["variants"]
assert all(row["axis"] == "loop-shape-expanded" for row in payload["variants"])
assert "loop-shape-expanded" not in {row["axis"] for row in payload["future_axes"]}
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py::test_run_structure_search_supports_loop_shape_expanded_axis -q
```

Expected: fail with unsupported axis or missing variants.

- [ ] **Step 3: Add axis wiring**

In `structure.py`, add `loop-shape-expanded` to `OPTIONAL_STRUCTURE_AXES`.
Add a `run_structure_search` branch that calls
`generate_loop_shape_expanded_variants(...)`, appends the returned
`AxisSummary`, and extends variants. Add a dynamic future-axis helper so
`loop-shape-expanded` is omitted once it is supported.

- [ ] **Step 4: Re-run the run-level test**

Run the same pytest command. Expected: still fail until the generator is added,
but no longer as an unsupported axis.

## Task 2: Sorted-List Scan Detection

**Files:**
- Modify: `tools/melee-agent/src/search/structure.py`
- Test: `tools/melee-agent/tests/search/test_structure.py`

- [ ] **Step 1: Write generator tests for names and fighters**

Add tests that call `generate_loop_shape_expanded_variants(...)` directly on
sources that cover the requested shapes:

- a `GetNameText(*p2) == NULL` scan over `assets->sorted_names`;
- an `mn_IsFighterUnlocked(*p2) == 0` scan over `assets->sorted_fighters`.
- a `mnDiagram_802417D0`-style local alias scan:
  `u8* sorted = mnDiagram_804A0750.sorted_fighters; ptr = sorted + i; ptr =
  ptr + 0x1C; ... GetNameText(*ptr2) == NULL ... result = sorted[i + 0x1C];`.
- a `mnDiagram_8024227C`-style goto/register-var scan:
  `var_r17_3 = &assets->sorted_names[arg1_r]; loop_52: ... var_r16_3 =
  var_r17_3; loop_48: ... if (GetNameText((s32) *var_r16_3) != NULL) { ... }`.

Assert the axis is `evaluated`, the variants contain operators
`loop-shape-expanded-direct-index`, `loop-shape-expanded-base-pointer`,
`loop-shape-expanded-predicate-temp`,
`loop-shape-expanded-inverted-predicate`, and
`loop-shape-expanded-helper` for the clean sources, that the alias/goto snippets
produce at least one retained variant, and every retained path exists.

- [ ] **Step 2: Verify the generator tests fail**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py -q \
  -k 'loop_shape_expanded'
```

Expected: fail because the generator does not exist.

- [ ] **Step 3: Implement detection**

Add a small `_LoopShapeScan` dataclass with sorted member, sorted expression,
predicate, result/index/remaining variables, cursor argument, pointer alias,
optional alias offset, and source spans. Implement regex-backed detection over
masked function body. Only return scans that include sorted-list evidence and
one of the two allowed predicates.

Detection must understand:

```c
p = &assets->sorted_names[arg2];
p = sorted + i;
p = p + 0x1C;
var_r17_3 = &assets->sorted_names[arg1_r];
```

and predicate expressions using either `*p2`, register pointer aliases, or
direct sorted-list loads.

- [ ] **Step 4: Implement blocked results**

Return `AxisSummary(axis="loop-shape-expanded", status="blocked",
blocker="no-loop-shape-expanded-candidates")` when no safe scan is found, and
`blocker="unsafe-loop-shape-preprocessor"` when the function body contains
preprocessor directives.

## Task 3: Candidate Families

**Files:**
- Modify: `tools/melee-agent/src/search/structure.py`
- Test: `tools/melee-agent/tests/search/test_structure.py`

- [ ] **Step 1: Implement retained variant writer**

Follow the `generate_statement_order_variants` local `add_variant` pattern:
dedupe by source text, write each candidate to
`output_dir / f"{_safe_candidate_label(label)}.c"`, and include touched lines,
source diff, and `live_mutation=False` metadata.

- [ ] **Step 2: Implement direct-index and base-pointer variants**

For direct-index variants, replace pointer cursor predicate references with the
detected sorted expression indexed by the detected index variable, preserving a
detected `+ 0x1C` alias offset. Remove only simple pointer alias and increment
statements when they are exact standalone statements in the scan span.

For base-pointer variants, introduce one base pointer assignment before the
guard and use `base[idx]` in predicate and final result expressions. For local
alias shapes such as `sorted + 0x1C`, the base pointer should be
`sorted + 0x1C`.

- [ ] **Step 3: Implement predicate spelling variants**

For predicate-temp, wrap the predicate branch in a block and introduce either
`char* loop_probe_predicate_0 = GetNameText(...);` or
`int loop_probe_predicate_0 = mn_IsFighterUnlocked(...);`.

For inverted-predicate, rewrite:

```c
if (GetNameText(expr) == NULL) {
    goto label;
}
```

to:

```c
if (GetNameText(expr) != NULL) {
} else {
    goto label;
}
```

and the analogous fighter-unlocked zero check.

- [ ] **Step 4: Implement helper variant**

Insert a `static inline u8 loop_probe_visible_entry_0(...)` helper before the
target function and replace the detected scan span with a helper call only for
clean sources where the scan span can be isolated without crossing labels used
outside the span. For goto-heavy sources, skip this family and expose other
families.

Interleave candidates by scan and family:

```python
for scan in scans:
    for family in families:
        add_variant(scan, family)
```

This prevents functions with many scans, such as `mnDiagram_8024227C`, from
using the full candidate budget on one family.

- [ ] **Step 5: Re-run loop-shape tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py -q \
  -k 'loop_shape_expanded'
```

Expected: all loop-shape tests pass.

## Task 4: Verification And Issue Closure

**Files:**
- Modify: issue queue only through `melee-agent issue resolve`

- [ ] **Step 1: Run focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_pressure_explorer.py \
  tools/melee-agent/tests/search/test_structure.py -q \
  -k 'temp_introduction or call_arg_tempization or loop_shape_expanded or structure_payload_reports_future_axes'
```

- [ ] **Step 2: Run structure-search smoke**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug search structure \
  -f mnDiagram_802427B4 --axis loop-shape-expanded --no-score --json
```

Expected: JSON payload with an evaluated `loop-shape-expanded` axis and at
least one retained variant.

- [ ] **Step 3: Run syntax checks**

Run:

```bash
python -m py_compile \
  tools/melee-agent/src/mwcc_debug/pressure_explorer.py \
  tools/melee-agent/src/search/structure.py \
  tools/melee-agent/tests/test_pressure_explorer.py \
  tools/melee-agent/tests/search/test_structure.py
git diff --check
```

- [ ] **Step 4: Commit and resolve**

Commit the tool, test, spec, and plan changes. Resolve #508, #509, and #510
with notes that include the commit hash and the verified root causes.
