# Cleanup Loop and Inline Boundary Variants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add source-emitting cleanup-loop and inline-boundary variants to structure search so #497 and #498 produce retained/scored candidates instead of advisory dead ends.

**Architecture:** Extend existing probe generators rather than adding a new harness. `pressure_explorer` owns cleanup-loop source-lifetime probes; `search.structure` owns the inline-boundary axis and adapts generated source into `StructureVariant` rows for the existing scorer.

**Tech Stack:** Python 3.11, Typer CLI, pytest, existing `StructureVariant`/`AxisSummary`, existing structure scorer and source-retained candidate files.

---

### Task 1: Cleanup-Loop Source-Lifetime Probes

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/pressure_explorer.py`
- Test: `tools/melee-agent/tests/test_pressure_explorer.py`
- Test: `tools/melee-agent/tests/search/test_structure.py`

- [ ] **Step 1: Add failing direct probe tests**

Add tests that call `generate_source_lifetime_probes` with a function containing:

```c
void fn_80000000(Diagram3* data)
{
    int i;
    for (i = 0; i < 0xA; i++) {
        if (data->row_labels[i] != NULL) {
            HSD_SisLib_803A5CC4(data->row_labels[i]);
            data->row_labels[i] = NULL;
        }
    }
}
```

Assert generated operators include `cleanup-loop-role-shape`, labels include
`cleanup-loop-slot-base-temp-0`, `cleanup-loop-counter-block-0`,
`cleanup-loop-value-temp-0`, `cleanup-loop-slot-cursor-0`, and
`cleanup-loop-null-sentinel-0`, and source snippets contain:

```c
HSD_Text** ll_probe_base_0 = data->row_labels;
int ll_probe_i_0;
HSD_Text* ll_probe_text_0 = data->row_labels[i];
{
    HSD_Text** ll_probe_cursor_0;
    for (i = 0, ll_probe_cursor_0 = data->row_labels;
HSD_Text* ll_probe_null_0 = NULL;
```

Also add a repeated-loop fixture with two matching cleanup loops and assert a
label `cleanup-loop-all-null-sentinel-0` rewrites both loop bodies. This
all-repeated candidate must appear before per-occurrence cleanup-loop candidates
when repeated loops are found, so capped structure-search runs retain it.

- [ ] **Step 2: Add failing structure-search test**

In `tests/search/test_structure.py`, add a `run_structure_search` test with
`axes=("source-lifetime",)`, `max_candidates=3`, and `score_variants=False`
using the repeated-loop source. Assert the first retained variants are
source-lifetime rows and the first cleanup-loop label starts with
`cleanup-loop-all-`.

- [ ] **Step 3: Implement cleanup-loop scanner**

In `pressure_explorer.py`, add `_probe_cleanup_loop_role_shape`. It should:

```python
operator = "cleanup-loop-role-shape"
span = _find_function_body_span(source_text, function)
body = source_text[body_start:body_end]
for each for-loop:
    parse init/condition/increment enough to identify `i`, `0`, and bound
    require a body pattern:
        if (SLOT != NULL) { CLEANUP(SLOT); SLOT = NULL; }
    require SLOT contains `[i]`
    emit slot-base, counter-role, value-temp, C89 block-scoped cursor,
    null-sentinel, and all-repeated variants with provenance
```

Use existing helpers such as `_find_matching_paren`, `_find_matching_brace`,
`_line_indent_at`, `_replace_slice`, `_mask_c_non_code_text`, and
`_region_has_preprocessor_directive`.

Only support `HSD_SisLib_803A5CC4` in this task. Use the explicit mapping
`value_type="HSD_Text*"` and `slot_type="HSD_Text**"` for that callee. Skip other
cleanup callees with a family summary blocker until type information is
available.

- [ ] **Step 4: Wire into source-lifetime targeted generators**

Add `("cleanup-loop-role-shape", _probe_cleanup_loop_role_shape)` before the
generic source-lifetime probe pass so cleanup variants get retained under small
caps.

- [ ] **Step 5: Run focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_pressure_explorer.py::test_source_lifetime_cleanup_loop_role_shape_probes \
  tools/melee-agent/tests/search/test_structure.py::test_source_lifetime_axis_retains_cleanup_loop_role_shape_under_small_cap -q
```

Expected: both pass.

### Task 2: Inline-Boundary Structure Axis

**Files:**
- Modify: `tools/melee-agent/src/search/structure.py`
- Test: `tools/melee-agent/tests/search/test_structure.py`
- Test: `tools/melee-agent/tests/search/test_cli_smoke.py`

- [ ] **Step 1: Add failing axis support tests**

Add tests asserting:

```python
assert "inline-boundary" in SUPPORTED_STRUCTURE_AXES
payload = run_structure_search(
    "fn_80000000",
    source_path,
    tmp_path / "structure",
    axes=("inline-boundary",),
    max_candidates=6,
    score_variants=False,
)
assert payload["axes"][0]["axis"] == "inline-boundary"
assert payload["axes"][0]["status"] == "evaluated"
assert "inline-boundary" not in {row["axis"] for row in payload["future_axes"]}
assert all(Path(row["source_retained"]).exists() for row in payload["variants"])
```

Use fixture source containing fake translate wrappers defined after the target
function, a direct `HSD_JObjSetTranslateY(popup, spacing * (f32) i)` call with an expression
argument, a `data = gobj->user_data;` assignment, and a SisLib cleanup loop.
Assert the axis-setter candidate inserts this prototype before the target
function when the fake definition is not visible at the call site:

```c
static inline void HSD_JObjSetTranslateY_Fake(HSD_JObj* jobj, f32 y);
```

- [ ] **Step 2: Implement axis dispatch**

In `DEFAULT_STRUCTURE_AXES` leave defaults unchanged. Add `inline-boundary` to
`OPTIONAL_STRUCTURE_AXES`. In `run_structure_search`, add:

```python
if axis == "inline-boundary":
    if source is None:
        summary, axis_variants = _blocked_axis(
            axis,
            "source-unavailable",
            source_read_error or "source file was not provided",
        )
    else:
        summary, axis_variants = generate_inline_boundary_variants(
            source,
            function,
            output_path / "inline-boundary",
            baseline_percent=baseline_percent,
            max_candidates=max_candidates,
        )
    axis_summaries.append(summary)
    variants.extend(axis_variants)
    continue
```

Remove `inline-boundary` from `future_axes` once supported.

- [ ] **Step 3: Implement inline-boundary generators**

Add `generate_inline_boundary_variants(source, function, output_dir, *,
baseline_percent, max_candidates)`. It should call helpers that return
`StructureVariant` rows:

- `_inline_boundary_axis_setter_wrapper_probes`
- `_inline_boundary_call_arg_temp_probes`
- `_inline_boundary_user_data_cast_probes`
- `_inline_boundary_sislib_cleanup_helper_probes`

Each helper writes candidate source to `<output_dir>/<safe-label>.c`, sets
`axis="inline-boundary"`, a specific operator, `status="candidate"`,
`source_retained`, and metadata describing the source family.

- [ ] **Step 4: Reuse existing safe source helpers**

For call-arg temps, call `generate_lifetime_layout_probes` with
`operator_filter=("call-argument-tempization",)` and adapt probes. For other
families, use conservative regex scanners over the target function body and skip
preprocessor regions. Do not mutate the working tree.

For fake wrapper calls, detect whether the wrapper definition starts before the
target function. If not, insert a matching prototype before the target function
in the candidate source. Do not emit a fake-wrapper candidate if neither a
definition nor enough signature information is present.

The initial fake-wrapper implementation rewrites direct calls to the matching
fake wrapper. It does not synthesize inverse fake-wrapper-to-direct candidates.

- [ ] **Step 5: Run focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_axis_retains_source_variants \
  tools/melee-agent/tests/search/test_cli_smoke.py::test_structure_search_help_lists_inline_boundary_axis -q
```

Expected: both pass.

### Task 3: Verification, Review, Commit, and Issue Resolution

**Files:**
- Modify: `docs/superpowers/specs/2026-06-07-cleanup-loop-inline-boundary-variants-design.md`
- Modify: `docs/superpowers/plans/2026-06-07-cleanup-loop-inline-boundary-variants.md`

- [ ] **Step 1: Run affected suites**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_pressure_explorer.py \
  tools/melee-agent/tests/search/test_structure.py \
  tools/melee-agent/tests/search/test_cli_smoke.py -q
```

- [ ] **Step 2: Run static checks**

Run:

```bash
python -m py_compile \
  tools/melee-agent/src/mwcc_debug/pressure_explorer.py \
  tools/melee-agent/src/search/structure.py \
  tools/melee-agent/tests/test_pressure_explorer.py \
  tools/melee-agent/tests/search/test_structure.py
git diff --check
```

- [ ] **Step 3: Run command-level smokes**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug search structure \
  -f fn_802461BC --source-file src/melee/mn/mndiagram3.c \
  --axis source-lifetime --max-candidates 8 --score --score-timeout 120 --json

PYTHONPATH=tools/melee-agent python -m src.cli debug search structure \
  -f mnDiagram3_80245BA4 --source-file src/melee/mn/mndiagram3.c \
  --axis inline-boundary --max-candidates 4 --score --score-timeout 120 --json
```

Expected: first smoke includes `cleanup-loop-role-shape` and at least one
retained label beginning with `cleanup-loop-all-`; second smoke includes
`inline-boundary` variants, no inline-boundary future-axis placeholder, and at
least one inline-boundary variant with `compile_status == "ok"` and
`checkdiff_status == "ok"`.

- [ ] **Step 4: Independent review**

Ask a read-only Codex subagent to review the diff for spec compliance and code
quality. Address any blocking findings before committing.

- [ ] **Step 5: Commit and close issues**

Stage only tooling, tests, spec, and plan files. Commit, resolve #497 and #498
with the commit hash, refresh the editable `melee-agent` install, verify no open
issues, and pause the automation again.
