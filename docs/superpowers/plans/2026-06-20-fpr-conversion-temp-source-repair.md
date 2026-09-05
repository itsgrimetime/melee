# FPR Conversion Temp Source Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pcode-only FPR conversion temps produce source-actionable cast-fragment repairs and preserve target-score virtual evidence in compact tooling outputs.

**Architecture:** Extend existing source-transform and summary helpers. `window_order_source` owns the conversion-temp source attribution, `node_set_split` owns typed binding and candidate summaries, and `search.cli` owns transform validation evidence.

**Tech Stack:** Python, pytest, Typer CLI, existing Melee `tools/melee-agent` modules.

## Global Constraints

- Preserve unrelated local work in `/Users/mike/code/melee`; do not overwrite dirty files you did not create.
- Follow test-driven development: add or update regression tests before production changes.
- Keep changes scoped to `tools/melee-agent` and docs for issue #862.
- Existing generic FPR subtraction owner-split behavior must remain intact.
- No new CLI command; reuse existing `debug search plan-transforms`, `debug solve node-set-split`, and validation evidence paths.
- Final CLI smoke checks must include `melee-agent debug search plan-transforms --help` and `melee-agent debug solve node-set-split --help`.

---

### Task 1: Conversion Consumer Owner Split

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_window_order_source.py`
- Modify: `tools/melee-agent/src/search/directed/window_order_source.py`

**Interfaces:**
- Consumes: `plan_window_order_source_probes(source_text, *, function, fallback_leads, source_attributions, max_probes)`
- Produces: conversion-temp synthetic owner metadata with handler `fpr-conversion-owner-split`, `owner_local`, `split_expression`, `consumer_ig`, and `operand_ig`.

- [ ] **Step 1: Write failing regression test**

Add this test to `tools/melee-agent/tests/search/directed/test_window_order_source.py` after the existing FPR owner-split tests:

```python
def test_window_order_plan_prefers_fpr_conversion_consumer_cast_owner() -> None:
    source = textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn(f32 y_spacing, int col, f32 row_offset)
        {
            f32 col_offset;
            f32 row_offset_adj;
            col_offset = y_spacing * (f32) col;
            row_offset_adj = row_offset - 0.4f;
            sink(col_offset + row_offset_adj);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 46, "order_move": ["before", 50]}],
        source_attributions={
            32: {
                "kind": "local",
                "name": "col_offset",
                "type": "f32",
                "source_line": 8,
                "expression": "y_spacing * (f32) col",
                "first_def": {
                    "opcode": "fmuls",
                    "operands": "f32,f34,f46",
                },
            },
            46: {
                "kind": "fpr-temp",
                "expression": "fsubs f46,f45,f44",
            },
        },
        max_probes=4,
    )
    if not plan.lead_diagnostics:
        pytest.skip("tree-sitter unavailable")

    assert plan.probes
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["source_local"] == "col_offset"
    assert diag["synthetic_source_probe"]["handler"] == "fpr-conversion-owner-split"
    assert diag["synthetic_source_probe"]["consumer_ig"] == 32
    assert diag["synthetic_source_probe"]["operand_ig"] == 46
    assert diag["synthetic_source_probe"]["split_expression"] == "(f32) col"
    assert "window_order_synthetic_col_offset = (f32) col;" in plan.probes[0].source_text
    assert "col_offset = y_spacing * window_order_synthetic_col_offset;" in plan.probes[0].source_text
    assert "row_offset_adj = row_offset - 0.4f;" in plan.probes[0].source_text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/directed/test_window_order_source.py::test_window_order_plan_prefers_fpr_conversion_consumer_cast_owner -q
```

Expected: FAIL because the current planner picks `fpr-arith-owner-split` for `row_offset_adj`.

- [ ] **Step 3: Implement consumer-first conversion owner scan**

In `tools/melee-agent/src/search/directed/window_order_source.py`:

1. Include `first_def` in `_source_attr_dict`.
2. Add helpers:

```python
def _source_attr_first_def_operands(source_attr: Any) -> str | None:
    first_def = _attr_value(source_attr, "first_def")
    if isinstance(first_def, Mapping):
        operands = first_def.get("operands")
        return operands if isinstance(operands, str) else None
    operands = getattr(first_def, "operands", None)
    return operands if isinstance(operands, str) else None


def _virtual_operand_ids(text: str | None) -> tuple[int, ...]:
    if not isinstance(text, str):
        return ()
    return tuple(int(value) for _, value in _VIRTUAL_OPERAND_RE.findall(text))


def _fpr_conversion_consumer_owners(
    groups: list[statement_move.SiblingGroup],
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None,
    target_ig: int,
) -> list[_SyntheticOwnerCandidate]:
    candidates: list[_SyntheticOwnerCandidate] = []
    if source_attributions is None:
        return candidates
    seen_keys: set[tuple[str, str]] = set()
    for raw_key, attr in source_attributions.items():
        try:
            consumer_ig = int(raw_key)
        except (TypeError, ValueError):
            continue
        if consumer_ig == target_ig or _attr_value(attr, "kind") != "local":
            continue
        if target_ig not in _virtual_operand_ids(_source_attr_first_def_operands(attr)):
            continue
        local_name = _attr_value(attr, "name")
        if not isinstance(local_name, str) or not local_name:
            continue
        owners = _matching_assignment_owners(
            groups,
            local_name=local_name,
            opcode="lfs",
            source_line=_attr_value(attr, "source_line"),
        )
        for owner in owners:
            split_expression = owner.split_expression or owner.rhs
            key = (owner.local_name, split_expression)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            metadata = {
                "handler": "fpr-conversion-owner-split",
                "consumer_ig": consumer_ig,
                "operand_ig": target_ig,
                "owner_local": owner.local_name,
                "split_expression": split_expression,
                "expression": _attr_value(attr, "expression"),
            }
            candidates.append(_SyntheticOwnerCandidate(owner, metadata))
    return candidates
```

3. Factor `_fpr_assignment_owners` through a new `_matching_assignment_owners(groups, opcode, *, local_name: str | None = None, source_line: object = None)` helper so conversion lookup can restrict to the consumer local and line.
4. Change `_fpr_temp_owner` signature to receive `source_attributions`. For `fsub`/`fsubs`, call `_fpr_conversion_consumer_owners(groups, source_attributions, target_ig)` before the generic arithmetic-owner fallback.
5. Update the call site in `plan_window_order_source_probes` to pass `source_attributions`.

- [ ] **Step 4: Run focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/directed/test_window_order_source.py -q
```

Expected: PASS.

### Task 2: Node-Set Binding and Candidate Score Evidence

**Files:**
- Modify: `tools/melee-agent/tests/test_node_set_split.py`
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`

**Interfaces:**
- Consumes: `request_from_node_set_delta`, `summarize_node_set_split_scores`
- Produces: introducible typed cast request support and candidate row `target_score` preservation.

- [ ] **Step 1: Write failing tests**

Add a test near the existing introducible-expression tests:

```python
def test_request_from_node_set_delta_allows_simple_typed_cast_binding() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(int col) {\n"
        "    f32 out;\n"
        "    out = (f32) col;\n"
        "    use(out);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [{
            "target_ig": 46,
            "desired_registers": ["f26"],
            "source": {
                "kind": "synthetic-owner-split",
                "expression": "(f32) col",
                "type": "f32",
                "introduce_binding": True,
            },
        }],
    }

    req = request_from_node_set_delta(delta, source_text=source)

    assert req is not None
    assert req.target_ig == 46
    assert req.source_expression == "(f32) col"
    assert req.source_type == "f32"
    assert node_set_split.is_node_set_request_introducible(req) is True
```

Extend `test_summarize_node_set_split_scores_surfaces_wrong_register_residuals` with:

```python
                "target_score": {
                    "matched": 4,
                    "targeted": 6,
                    "virtuals": {
                        "32": {"expected": 28, "actual": 25, "matched": False},
                        "46": {"expected": 26, "actual": 1, "matched": False},
                    },
                },
```

and assert:

```python
    assert row["target_score"]["matched"] == 4
    assert row["target_score"]["virtuals"]["46"]["actual"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_node_set_split.py::test_request_from_node_set_delta_allows_simple_typed_cast_binding tools/melee-agent/tests/test_node_set_split.py::test_summarize_node_set_split_scores_surfaces_wrong_register_residuals -q
```

Expected: FAIL because cast expressions are currently rejected and `_score_row` does not copy `target_score`.

- [ ] **Step 3: Implement minimal fixes**

In `tools/melee-agent/src/mwcc_debug/node_set_split.py`:

1. Add `_CAST_PREFIX_RE`:

```python
_CAST_PREFIX_RE = re.compile(
    r"^\(\s*[A-Za-z_][A-Za-z_0-9]*(?:\s+[A-Za-z_][A-Za-z_0-9]*)*\s*\)\s*"
)
```

2. Change `_source_expression_is_safe_to_bind` so a leading cast is stripped before the safety checks instead of rejected:

```python
text = expression.strip()
if not text:
    return False
text_without_cast = _CAST_PREFIX_RE.sub("", text, count=1).strip()
if not text_without_cast:
    return False
if re.search(r"\b[A-Za-z_][A-Za-z_0-9]*\s*\(", text_without_cast):
    return False
if re.search(r"\+\+|--|(?<![=!<>])=(?!=)|<<=|>>=|,", text_without_cast):
    return False
return re.search(r"\b[A-Za-z_][A-Za-z_0-9]*\b", text_without_cast) is not None
```

3. In `_score_row`, after source hunk handling, copy mapping-valued `target_score` from the entry first, then from `objective`:

```python
    target_score = None
    if isinstance(entry, Mapping) and isinstance(entry.get("target_score"), Mapping):
        target_score = dict(entry["target_score"])
    elif isinstance(objective, Mapping) and isinstance(objective.get("target_score"), Mapping):
        target_score = dict(objective["target_score"])
    if target_score is not None:
        row["target_score"] = target_score
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_node_set_split.py::test_request_from_node_set_delta_allows_simple_typed_cast_binding tools/melee-agent/tests/test_node_set_split.py::test_summarize_node_set_split_scores_surfaces_wrong_register_residuals -q
```

Expected: PASS.

### Task 3: Transform Validation Target-Score Evidence

**Files:**
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
- Modify: `tools/melee-agent/src/search/cli/__init__.py`

**Interfaces:**
- Consumes: validator JSON from `_run_transform_validations`
- Produces: `validation[*].evidence.target_score` containing compact score evidence.

- [ ] **Step 1: Write failing validation evidence test**

Add this test near the existing `plan-transforms --validate-command` tests:

```python
def test_search_plan_transforms_validation_evidence_preserves_target_score(tmp_path: Path) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text(
        "typedef struct HSD_GObj HSD_GObj;\n"
        "typedef struct Data { int selected; int is_name_mode; } Data;\n"
        "void mnDiagram2_Create(HSD_GObj* gobj, Data* data) {\n"
        "    int selected;\n"
        "    selected = data->selected;\n"
        "    sink(gobj, selected);\n"
        "}\n"
    )
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": "mnDiagram2_Create",
            "class_id": 0,
            "missing_virtuals": [{
                "target_ig": 36,
                "current_register": "r25",
                "desired_registers": ["r27"],
                "source": {"expression": "gobj", "name": "gobj"},
            }],
        }
    }))
    probes_dir = tmp_path / "probes"
    validator = (
        "import json; "
        "print(json.dumps({"
        "'status':'negative-evidence',"
        "'target_score':{'matched':4,'targeted':6,'virtuals':{'46':{'expected':26,'actual':1,'matched':False}}}"
        "}))"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_Create",
            "--unit", "melee/mn/mndiagram2",
            "--force-phys", "36:27",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(probes_dir),
            "--validate-command", f"{sys.executable} -c \"{validator}\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    evidence = payload["validation"][0]["evidence"]
    assert evidence["target_score"]["matched"] == 4
    assert evidence["target_score"]["virtuals"]["46"]["actual"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/test_cli_smoke.py::test_search_plan_transforms_validation_evidence_preserves_target_score -q
```

Expected: FAIL because `_transform_validation_evidence` omits `target_score`.

- [ ] **Step 3: Implement evidence propagation**

In `tools/melee-agent/src/search/cli/__init__.py`, rewrite `_transform_validation_evidence` to build the evidence dict first, then conditionally attach the target score:

```python
def _transform_validation_evidence(probe: dict, result: dict) -> dict:
    evidence = {
        "probe_id": result.get("probe_id"),
        "family_id": result.get("family_id"),
        "family_label": probe.get("family_label"),
        "outcome": result.get("outcome"),
        "semantic_risk": probe.get("semantic_risk"),
        "source_region": probe.get("source_region"),
        "target_assignments": list(probe.get("target_assignments") or []),
        "expected_compiler_effect": probe.get("expected_compiler_effect"),
        "match_percent": result.get("match_percent"),
        "target_assignment_movement": result.get("target_assignment_movement"),
        "recommendation": result.get("recommendation"),
        "source_regions": result.get("source_regions"),
        "uncovered_transform_classes": result.get("uncovered_transform_classes"),
    }
    payload = result.get("validator_payload")
    target_score = payload.get("target_score") if isinstance(payload, dict) else None
    if isinstance(target_score, dict):
        evidence["target_score"] = target_score
    return evidence
```

- [ ] **Step 4: Run focused test**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/test_cli_smoke.py::test_search_plan_transforms_validation_evidence_preserves_target_score -q
```

Expected: PASS.

### Task 4: Verification and CLI Smoke

**Files:**
- No new production files.

**Interfaces:**
- Verifies all task-level changes and the public CLI entry points.

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_window_order_source.py \
  tools/melee-agent/tests/test_node_set_split.py::test_request_from_node_set_delta_allows_simple_typed_cast_binding \
  tools/melee-agent/tests/test_node_set_split.py::test_summarize_node_set_split_scores_surfaces_wrong_register_residuals \
  tools/melee-agent/tests/search/test_cli_smoke.py::test_search_plan_transforms_validation_evidence_preserves_target_score \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run CLI smoke checks**

Run:

```bash
melee-agent debug search plan-transforms --help >/tmp/plan-transforms-help.txt
melee-agent debug solve node-set-split --help >/tmp/node-set-split-help.txt
```

Expected: both commands exit 0.

- [ ] **Step 3: Review final diff**

Run:

```bash
git diff -- docs/superpowers/specs/2026-06-20-fpr-conversion-temp-source-repair-design.md docs/superpowers/plans/2026-06-20-fpr-conversion-temp-source-repair.md tools/melee-agent/src/search/directed/window_order_source.py tools/melee-agent/src/mwcc_debug/node_set_split.py tools/melee-agent/src/search/cli/__init__.py tools/melee-agent/tests/search/directed/test_window_order_source.py tools/melee-agent/tests/test_node_set_split.py tools/melee-agent/tests/search/test_cli_smoke.py
```

Expected: diff contains only issue #862 scoped changes.
