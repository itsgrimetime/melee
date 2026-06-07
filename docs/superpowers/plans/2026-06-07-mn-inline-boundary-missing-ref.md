# MN Inline Boundary Missing-Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Extend `debug search structure --axis inline-boundary` so reported `mn` missing-reference-call rows receive retained, scoreable source candidates instead of `no-inline-boundary-candidates`.

**Architecture:** Keep all generation inside `tools/melee-agent/src/search/structure.py` and reuse the existing `StructureVariant` writer/scorer. Add bounded inline-boundary families for call-result temporaries, popup text/number helper extraction, and sort-entry initialization helper extraction, plus optional baseline classification metadata for shifted same-target call evidence.

**Tech Stack:** Python 3.11, pytest, existing `source_patch.find_function`, existing structure-search CLI/scorer, retained source candidate files.

---

## File Structure

- Modify `tools/melee-agent/src/search/structure.py`: add baseline classification plumbing and new inline-boundary variant families.
- Modify `tools/melee-agent/src/search/cli.py`: pass initial checkdiff classification into `run_structure_search` when available.
- Modify `tools/melee-agent/tests/search/test_structure.py`: add unit coverage for the new generators and metadata.
- Modify `tools/melee-agent/tests/search/test_cli_smoke.py`: add CLI smoke coverage for inline-boundary help/output behavior as needed.
- Commit with `docs/superpowers/specs/2026-06-07-mn-inline-boundary-missing-ref-design.md` and this plan.

## Task 1: Baseline Inline-Boundary Metadata Plumbing

**Files:**
- Modify: `tools/melee-agent/src/search/structure.py`
- Modify: `tools/melee-agent/src/search/cli.py`
- Test: `tools/melee-agent/tests/search/test_structure.py`

- [x] **Step 1: Write failing metadata tests**

Append tests to `tools/melee-agent/tests/search/test_structure.py`:

```python
def test_inline_boundary_axis_reports_shifted_missing_reference_metadata(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    sink(GetNameText(0));\n"
        "}\n",
        encoding="utf-8",
    )
    classification = {
        "primary": "inline-boundary-toolchain-artifact",
        "inline_boundary_artifact": {
            "missing_ref_calls": [
                "<fn_80000000+0x10>",
                "<fn_80000000+0x24>",
            ],
        },
    }

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("inline-boundary",),
        max_candidates=4,
        score_variants=False,
        baseline_classification=classification,
    )

    metadata = payload["axes"][0]["metadata"]["inline_boundary_artifact"]
    assert metadata["missing_ref_call_count"] == 2
    assert metadata["same_function_offset_count"] == 2
    assert metadata["source_lever_classification"] == "shifted-same-target-calls"
```

- [x] **Step 2: Run the failing metadata test**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_axis_reports_shifted_missing_reference_metadata -q
```

Expected: fail because `run_structure_search` does not accept
`baseline_classification`.

- [x] **Step 3: Add classification parameters**

In `run_structure_search(...)`, add a keyword-only parameter:

```python
baseline_classification: dict[str, Any] | None = None,
```

Pass it into `generate_inline_boundary_variants(...)`:

```python
summary, axis_variants = generate_inline_boundary_variants(
    source,
    function,
    output_path / "inline-boundary",
    baseline_percent=baseline_percent,
    max_candidates=max_candidates,
    baseline_classification=baseline_classification,
)
```

Update `generate_inline_boundary_variants(...)` with the same keyword-only
parameter and merge metadata:

```python
metadata = {"families": family_counts}
artifact = _inline_boundary_artifact_metadata(
    baseline_classification,
    function=function,
)
if artifact is not None:
    metadata["inline_boundary_artifact"] = artifact
```

Add helper:

```python
def _inline_boundary_artifact_metadata(
    classification: dict[str, Any] | None,
    *,
    function: str,
) -> dict[str, Any] | None:
    if not isinstance(classification, dict):
        return None
    artifact = classification.get("inline_boundary_artifact")
    if not isinstance(artifact, dict):
        return None
    calls = [
        str(call)
        for call in artifact.get("missing_ref_calls", [])
        if call is not None
    ]
    marker = f"<{function}+"
    same_function = [call for call in calls if call.startswith(marker)]
    if same_function and len(same_function) == len(calls):
        source_class = "shifted-same-target-calls"
    elif same_function:
        source_class = "mixed"
    else:
        source_class = "true-missing-reference-calls"
    return {
        "missing_ref_calls": calls,
        "missing_ref_call_count": len(calls),
        "same_function_offset_count": len(same_function),
        "source_lever_classification": source_class,
    }
```

- [x] **Step 4: Wire CLI baseline classification**

In `tools/melee-agent/src/search/cli.py`, locate the existing baseline
checkdiff/classification payload used for structure search scoring. Thread the
classification into `run_structure_search`:

```python
baseline_classification=(
    checkdiff_payload.get("classification")
    if isinstance(checkdiff_payload, dict)
    and isinstance(checkdiff_payload.get("classification"), dict)
    else None
),
```

If the CLI does not have a baseline payload in the unscored path, leave
`baseline_classification=None`; unit tests cover direct plumbing and scored
CLI smokes cover the live path.

- [x] **Step 5: Run metadata tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_axis_reports_shifted_missing_reference_metadata -q
```

Expected: pass.

## Task 2: Call-Result Temporary Variants

**Files:**
- Modify: `tools/melee-agent/src/search/structure.py`
- Test: `tools/melee-agent/tests/search/test_structure.py`

- [x] **Step 1: Write failing call-result temp tests**

Append tests:

```python
def test_inline_boundary_generates_call_result_temp_for_if_condition(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(int j)\n"
        "{\n"
        "    if (GetNameText((u8) j) != NULL) {\n"
        "        total++;\n"
        "    }\n"
        "}\n"
    )

    axis, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=4,
    )

    assert axis.status == "evaluated"
    variant = next(
        row for row in variants if row.operator == "inline-boundary-call-result-temp"
    )
    text = Path(variant.source_retained or "").read_text()
    assert "char* ib_probe_call_result_0 = GetNameText((u8) j);" in text
    assert "if (ib_probe_call_result_0 != NULL)" in text
    assert "        total++;" in text
    assert variant.metadata["callee"] == "GetNameText"
    assert variant.metadata["return_type"] == "char*"


def test_inline_boundary_generates_call_result_temp_for_member_access(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(int i, int j)\n"
        "{\n"
        "    total += GetPersistentNameData((u8) i)->vs_kos[(u8) j];\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=4,
    )

    variant = next(
        row for row in variants if row.operator == "inline-boundary-call-result-temp"
    )
    text = Path(variant.source_retained or "").read_text()
    assert (
        "struct NameTagData* ib_probe_call_result_0 = "
        "GetPersistentNameData((u8) i);"
    ) in text
    assert "total += ib_probe_call_result_0->vs_kos[(u8) j];" in text
```

- [x] **Step 2: Run failing call-result tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_generates_call_result_temp_for_if_condition \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_generates_call_result_temp_for_member_access -q
```

Expected: fail because the generator does not exist.

- [x] **Step 3: Implement call-result temp generator**

In `structure.py`, add the return type allowlist:

```python
_INLINE_BOUNDARY_CALL_RESULT_RETURNS = {
    "GetNameText": "char*",
    "GetPersistentNameData": "struct NameTagData*",
    "GetPersistentFighterData": "struct FighterData*",
    "mnDiagram_GetFighterByIndex": "u8",
}
```

Call the generator from `generate_inline_boundary_variants` before
`call_arg_temp`:

```python
_generate_inline_boundary_call_result_temp_variants(
    source,
    function_span,
    add_variant,
)
```

Implement helpers that:

1. mask comments/literals;
2. find each allowed callee call in the target function body;
3. find the matching `(` and `)` with `_find_matching`;
4. skip calls whose span is on the left side of an assignment or in a
   declaration line;
5. find the owning statement span with `_inline_boundary_statement_span`;
6. replace the call expression with `ib_probe_call_result_<n>`;
7. wrap the statement span:

```python
replacement = (
    f"{indent}{{\n"
    f"{indent}    {return_type} {temp_name} = {call_expr};\n"
    f"{rewritten_statement}"
    f"{indent}}}\n"
)
```

Add a candidate with:

```python
operator="inline-boundary-call-result-temp"
label=f"inline-boundary-call-result-temp-{callee}-{index}"
metadata={
    "family": "call-result-temp",
    "callee": callee,
    "return_type": return_type,
    "temp": temp_name,
    "statement_span": _line_span(source, statement_start, statement_end),
}
```

For `if`, `while`, and `for` statements, `_inline_boundary_statement_span`
must include the braced body when present. For expression statements, it ends
at the first top-level semicolon after the call.

- [x] **Step 4: Run call-result tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_generates_call_result_temp_for_if_condition \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_generates_call_result_temp_for_member_access -q
```

Expected: pass.

## Task 3: Popup Helper Variants

**Files:**
- Modify: `tools/melee-agent/src/search/structure.py`
- Test: `tools/melee-agent/tests/search/test_structure.py`

- [x] **Step 1: Write failing popup helper tests**

Append tests:

```python
def test_inline_boundary_generates_popup_text_setup_helper(tmp_path: Path) -> None:
    source = (
        "void fn_80000000(HSD_GObj* gobj, int slot)\n"
        "{\n"
        "    PopupData* data = gobj->user_data;\n"
        "    AnimTable* tbl = &table;\n"
        "    Point3d pos;\n"
        "    HSD_Text* text;\n"
        "    text = HSD_SisLib_803A6754(0, 1);\n"
        "    data->text[0] = text;\n"
        "    lb_8000B1CC(data->jobjs[8], &tbl->points[0], &pos);\n"
        "    text->font_size.x = 0.0521f;\n"
        "    text->font_size.y = 0.0521f;\n"
        "    text->default_alignment = 0;\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=8,
    )

    variant = next(
        row
        for row in variants
        if row.operator == "inline-boundary-popup-text-setup-helper"
    )
    text = Path(variant.source_retained or "").read_text()
    assert "static inline HSD_Text* ib_probe_popup_text_setup_0" in text
    assert "ib_probe_popup_text_setup_0(data, tbl, &pos" in text
    assert variant.metadata["family"] == "popup-text-setup-helper"


def test_inline_boundary_generates_popup_number_format_helper(tmp_path: Path) -> None:
    source = (
        "void fn_80000000(HSD_Text* text, char* buf, int arg1, int arg2)\n"
        "{\n"
        "    u16 kos;\n"
        "    kos = GetPersistentNameData((u8) arg1)->vs_kos[(u8) arg2];\n"
        "    mnDiagram_IntToStr(buf, kos);\n"
        "    HSD_SisLib_803A6B98(text, 0.0f, 0.0f, buf);\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=8,
    )

    variant = next(
        row
        for row in variants
        if row.operator == "inline-boundary-popup-number-format-helper"
    )
    text = Path(variant.source_retained or "").read_text()
    assert "static inline void ib_probe_popup_number_format_0" in text
    assert "ib_probe_popup_number_format_0(text, buf, kos);" in text
    assert variant.metadata["family"] == "popup-number-format-helper"
```

- [x] **Step 2: Run failing popup tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_generates_popup_text_setup_helper \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_generates_popup_number_format_helper -q
```

Expected: fail because the generators do not exist.

- [x] **Step 3: Implement popup helper generators**

Add calls in `generate_inline_boundary_variants`:

```python
_generate_inline_boundary_popup_text_setup_variants(source, function_span, add_variant)
_generate_inline_boundary_popup_number_format_variants(source, function_span, add_variant)
```

For text setup:

- match a contiguous statement group containing `HSD_SisLib_803A6754`,
  `data->text[...] = text`, `lb_8000B1CC(...)`, font size x/y assignments, and
  `default_alignment`;
- insert helper before target function;
- replace the matched group with:

```c
text = ib_probe_popup_text_setup_0(data, tbl, &pos, text_slot, jobj_slot,
                                  point_slot, font_x, font_y, align);
```

For number formatting:

- match three adjacent statements: value assignment, `mnDiagram_IntToStr`, and
  `HSD_SisLib_803A6B98(..., buf)`;
- insert helper before target function;
- replace the last two statements with
  `ib_probe_popup_number_format_0(text, buf, value_var);`;
- leave the value assignment intact.

Both helpers use static inline definitions inserted at
`_line_start_index(source, function_span.sig_start)`.

- [x] **Step 4: Run popup tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_generates_popup_text_setup_helper \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_generates_popup_number_format_helper -q
```

Expected: pass.

## Task 4: Sort Entry Initialization Helper

**Files:**
- Modify: `tools/melee-agent/src/search/structure.py`
- Test: `tools/melee-agent/tests/search/test_structure.py`

- [x] **Step 1: Write failing sort-entry test**

Append:

```python
def test_inline_boundary_generates_sort_entry_init_helper(tmp_path: Path) -> None:
    source = (
        "void fn_80000000(void)\n"
        "{\n"
        "    mnDiagram2_SortEntry entries[25];\n"
        "    mnDiagram2_SortEntry* ptr;\n"
        "    int i;\n"
        "    int zero;\n"
        "    ptr = entries;\n"
        "    i = 0;\n"
        "    zero = 0;\n"
        "    do {\n"
        "        ptr->name = mnDiagram_GetFighterByIndex(i);\n"
        "        i++;\n"
        "        ptr->xC = zero;\n"
        "        ptr->x8 = zero;\n"
        "        ptr++;\n"
        "    } while (i < 25);\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=8,
    )

    variant = next(
        row
        for row in variants
        if row.operator == "inline-boundary-sort-entry-init-helper"
    )
    text = Path(variant.source_retained or "").read_text()
    assert "static inline void ib_probe_sort_entry_init_0" in text
    assert "ib_probe_sort_entry_init_0(entries, zero);" in text
    assert variant.metadata["family"] == "sort-entry-init-helper"
```

- [x] **Step 2: Run failing sort-entry test**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_generates_sort_entry_init_helper -q
```

Expected: fail because the generator does not exist.

- [x] **Step 3: Implement sort-entry helper generator**

Add `_generate_inline_boundary_sort_entry_init_variants(...)` and call it from
`generate_inline_boundary_variants`.

The matcher should detect the exact do/while loop shape:

```c
do {
    ptr->name = mnDiagram_GetFighterByIndex(i);
    i++;
    ptr->xC = zero;
    ptr->x8 = zero;
    ptr++;
} while (i < 25);
```

Insert before the function:

```c
static inline void ib_probe_sort_entry_init_0(mnDiagram2_SortEntry* entries,
                                             int zero)
{
    int i = 0;
    mnDiagram2_SortEntry* ptr = entries;

    do {
        ptr->name = mnDiagram_GetFighterByIndex(i);
        i++;
        ptr->xC = zero;
        ptr->x8 = zero;
        ptr++;
    } while (i < 25);
}
```

Replace the original `ptr = entries; i = 0; zero = 0; do { ... } while ...;`
group with:

```c
zero = 0;
ib_probe_sort_entry_init_0(entries, zero);
ptr = entries + 25;
i = 25;
```

Record metadata with family, helper, entry array, pointer variable, index
variable, zero variable, and touched lines.

- [x] **Step 4: Run sort-entry test**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py::test_inline_boundary_generates_sort_entry_init_helper -q
```

Expected: pass.

## Task 5: Verification, Review, Commit, and Resolution

**Files:**
- Modify: `docs/superpowers/plans/2026-06-07-mn-inline-boundary-missing-ref.md`
- Existing: `docs/superpowers/specs/2026-06-07-mn-inline-boundary-missing-ref-design.md`

- [x] **Step 1: Run affected tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/test_structure.py \
  tools/melee-agent/tests/search/test_cli_smoke.py -q
```

- [x] **Step 2: Run static checks**

Run:

```bash
python -m py_compile \
  tools/melee-agent/src/search/structure.py \
  tools/melee-agent/src/search/cli.py \
  tools/melee-agent/tests/search/test_structure.py \
  tools/melee-agent/tests/search/test_cli_smoke.py
git diff --check
```

- [x] **Step 3: Run reported-function smokes**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug search structure \
  -f mnDiagram_80240D94 --source-file src/melee/mn/mndiagram.c \
  --axis inline-boundary --max-candidates 8 --json

PYTHONPATH=tools/melee-agent python -m src.cli debug search structure \
  -f mnDiagram_8023FC28 --source-file src/melee/mn/mndiagram.c \
  --axis inline-boundary --max-candidates 8 --json

PYTHONPATH=tools/melee-agent python -m src.cli debug search structure \
  -f mnDiagram2_GetAggregatedFighterRank --source-file src/melee/mn/mndiagram2.c \
  --axis inline-boundary --max-candidates 8 --json
```

Expected: each payload has `axes[0].status == "evaluated"` and at least one
variant with `axis == "inline-boundary"`.

- [x] **Step 4: Ask independent code review**

Ask a read-only Codex subagent to review:

- `tools/melee-agent/src/search/structure.py`
- `tools/melee-agent/src/search/cli.py`
- `tools/melee-agent/tests/search/test_structure.py`
- `tools/melee-agent/tests/search/test_cli_smoke.py`
- this plan and the design spec

Address any critical or important findings and rerun the affected tests.

- [x] **Step 5: Commit and resolve issue**

Stage only tooling, tests, spec, and plan files:

```bash
git add \
  docs/superpowers/plans/2026-06-07-mn-inline-boundary-missing-ref.md \
  tools/melee-agent/src/search/structure.py \
  tools/melee-agent/src/search/cli.py \
  tools/melee-agent/tests/search/test_structure.py \
  tools/melee-agent/tests/search/test_cli_smoke.py
git commit -m "Add MN inline-boundary missing-ref variants"
commit=$(git rev-parse --short HEAD)
PYTHONPATH=tools/melee-agent python -m src.cli issue resolve 505 \
  --note "fixed in ${commit}: inline-boundary structure search now emits MN call-result, popup helper, and sort-entry helper candidates plus missing-reference metadata"
```

- [x] **Step 6: Refresh install and final queue**

Run:

```bash
python -m pip install -e /Users/mike/code/melee/tools/melee-agent
/opt/homebrew/bin/melee-agent issue list --status open
/opt/homebrew/bin/python3 - <<'PY'
import inspect
import src.cli
print(inspect.getfile(src.cli))
PY
```

Expected: no open issues and installed CLI imports from
`/Users/mike/code/melee/tools/melee-agent/src`.
