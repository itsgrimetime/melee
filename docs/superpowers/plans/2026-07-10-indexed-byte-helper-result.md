# Indexed Byte Helper-Result Steering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make automatic GPR indexed-byte select-order searches materialize safe source probes for `u8` helper-call byte results and exact byte-mask `rlwinm` pcode temps.

**Architecture:** Extend the existing `indexed_byte_address_temp_steering` anchor generator with one helper-result assignment form. The anchor replaces a single eligible masked helper assignment with a fresh `u8` local and a follow-up assignment; existing corpus orchestration then retains, force-phys scores, and validates it unchanged. Extend the existing window-order implicit-temp path only for exact `rlwinm ...,0,24,31` byte masks so ranked indexed-byte C candidates can materialize instead of stopping at unsupported-shape.

**Tech Stack:** Python 3, regex-based source anchors, transform-corpus registry, pytest.

## Global Constraints

- Only source-visible helpers declared or defined with return type `u8` qualify.
- Only one simple call occurrence with identifier-or-integer arguments qualifies.
- Preserve the original destination, statement order, and surrounding control flow.
- Reject non-byte helpers, side-effecting arguments, and ambiguous occurrences without producing a probe.
- Reuse the existing `indexed_byte_address_temp_steering` family and real-tree validation path.
- Do not create source from assembly alone; `rlwinm` support only unlocks existing ranked indexed-byte source candidates.

---

### Task 1: Add the helper-result anchor and mutator registration

**Files:**

- Modify: `tools/melee-agent/src/search/directed/transform_corpus/indexed_byte_address.py`
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/registry.py`
- Test: `tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py`

**Interfaces:**

- Consumes: `_iter_indexed_byte_address_temp_anchors(source_text, function, span)` and `_replace_validated_span(anchor, source_text)`.
- Produces: anchors with `mutator_key="steer_indexed_byte_helper_result_temp"`, `strategy="indexed-byte-helper-result-temp"`, and payload keys `helper`, `target_local`, and `temp_local`.

- [ ] **Step 1: Write the failing source-transform test**

```python
def test_indexed_byte_address_temp_generates_helper_result_probe() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "static inline u8 visible_name(u8* sorted, int i) { return sorted[i]; }\n"
        "void fn(u8* sorted, int i) {\n"
        "    int name_id;\n"
        "    name_id = visible_name(sorted, i) &\n"
        "              0xFFFFFFFFFFFFFFFFu;\n"
        "}\n"
    )
    probes = generate_transform_probes(
        source, function="fn", unit="melee/mn/mndiagram",
        force_phys={79: 25},
        families=("indexed_byte_address_temp_steering",), max_per_family=8,
    )
    probe = next(
        probe for probe in probes
        if probe.mutator_key == "steer_indexed_byte_helper_result_temp"
    )
    assert probe.payload["helper"] == "visible_name"
    assert "u8 visible_name_probe;" in probe.candidate_text
    assert "visible_name_probe = visible_name(sorted, i);" in probe.candidate_text
    assert "name_id = visible_name_probe;" in probe.candidate_text
```

- [ ] **Step 2: Run the failing test**

Run: `pytest tests/search/directed/transform_corpus/test_indexed_byte_address.py::test_indexed_byte_address_temp_generates_helper_result_probe -q --no-cov`

Expected: FAIL because no helper-result mutator exists.

- [ ] **Step 3: Add the narrow anchor generator**

Add a `u8` helper declaration/definition matcher and an assignment matcher that
accepts exactly `target = helper(safe_args) & 0xFFFFFFFFFFFFFFFFu;`, including
the reported two-line spelling. Insert a fresh `u8` declaration at the start
of the selected function body and replace the whole assignment with:

```python
replacement_text = (
    f"    u8 {temp_name};\n"
    f"{body_text[:statement_start]}"
    f"{indent}{temp_name} = {helper}({arguments});\n"
    f"{indent}{target_local} = {temp_name};\n"
    f"{body_text[statement_end:]}"
)
```

Yield the anchor from `_iter_indexed_byte_address_temp_anchors` before its
direct-array early return. Register a `steer_indexed_byte_helper_result_temp`
wrapper in `mutators.py` that calls `_replace_validated_span`, and add that key
to the existing indexed-byte family in `registry.py`.

- [ ] **Step 4: Add rejection coverage**

```python
@pytest.mark.parametrize("return_type, arguments", [
    ("int", "sorted, i"),
    ("u8", "sorted, i++"),
])
def test_indexed_byte_helper_result_rejects_unsafe_shape(return_type, arguments):
    source = (
        "typedef unsigned char u8;\n"
        f"static inline {return_type} visible_name(u8* sorted, int i) "
        "{ return sorted[i]; }\n"
        "void fn(u8* sorted, int i) {\n"
        "    int name_id;\n"
        f"    name_id = visible_name({arguments}) & 0xFFFFFFFFFFFFFFFFu;\n"
        "}\n"
    )
    probes = generate_transform_probes(
        source, function="fn", unit="melee/mn/mndiagram",
        force_phys={79: 25},
        families=("indexed_byte_address_temp_steering",), max_per_family=8,
    )
    assert not [
        probe for probe in probes
        if probe.mutator_key == "steer_indexed_byte_helper_result_temp"
    ]
```

Also add:

```python
def test_indexed_byte_helper_result_rejects_ambiguous_occurrences() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "static inline u8 visible_name(u8* sorted, int i) { return sorted[i]; }\n"
        "void fn(u8* sorted, int i, int j) {\n"
        "    int first;\n"
        "    int second;\n"
        "    first = visible_name(sorted, i) & 0xFFFFFFFFFFFFFFFFu;\n"
        "    second = visible_name(sorted, j) & 0xFFFFFFFFFFFFFFFFu;\n"
        "}\n"
    )
    probes = generate_transform_probes(
        source, function="fn", unit="melee/mn/mndiagram",
        force_phys={79: 25},
        families=("indexed_byte_address_temp_steering",), max_per_family=8,
    )
    assert not [
        probe for probe in probes
        if probe.mutator_key == "steer_indexed_byte_helper_result_temp"
    ]
```

- [ ] **Step 5: Verify Task 1 and commit**

Run: `pytest tests/search/directed/transform_corpus/test_indexed_byte_address.py -q --no-cov`

Expected: PASS.

```bash
git add tools/melee-agent/src/search/directed/transform_corpus/indexed_byte_address.py \
  tools/melee-agent/src/search/directed/mutators.py \
  tools/melee-agent/src/search/directed/transform_corpus/registry.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py
git commit -m "feat: add indexed byte helper result probes"
```

### Task 2: Add byte-mask rlwinm fallback and verify automatic select-order family materialization

**Files:**

- Modify: `tools/melee-agent/src/search/directed/window_order_source.py`
- Test: `tools/melee-agent/tests/search/directed/test_window_order_source.py`
- Modify: `tools/melee-agent/tests/test_select_order_search.py`

**Interfaces:**

- Consumes: `_implicit_add_owner(...)` for source attributions with
  `kind="implicit-temp"` and expression `rlwinm rX,rY,0,24,31`.
- Produces: ranked indexed-byte materialization metadata instead of
  `synthetic-temp-unsupported-shape` for exact byte-mask `rlwinm` temps.
- Consumes: automatic class-0 `indexed_byte_address_temp_steering` selection
  when `--transform-force-phys` is supplied.
- Produces: JSON probe output containing the helper-result mutator without
  enabling extra transform families.

- [ ] **Step 1: Write the failing rlwinm window-order regression**

```python
def test_window_order_plan_attributes_rlwinm_byte_temp_to_indexed_byte_candidates() -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        void fn(u8* sorted, int i)
        {
            u8 temp;
            temp = sorted[i];
            use(temp);
        }
    """)
    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 79, "order_move": ["after", 34]}],
        source_attributions={
            79: {"kind": "implicit-temp", "expression": "rlwinm r79,r59,0,24,31"},
            59: {"kind": "implicit-temp", "expression": "lbz r59,r42,0"},
        },
        max_probes=4,
    )
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["synthetic_source_probe"]["expression"] == "rlwinm r79,r59,0,24,31"
    assert diag["synthetic_source_probe"]["materialized_ranked_indexed_byte_source_candidates"]
```

- [ ] **Step 2: Run the failing rlwinm regression**

Run: `pytest tests/search/directed/test_window_order_source.py::test_window_order_plan_attributes_rlwinm_byte_temp_to_indexed_byte_candidates -q --no-cov`

Expected: FAIL with blocked `synthetic-temp-unsupported-shape`.

- [ ] **Step 3: Implement exact byte-mask rlwinm support**

Add a helper that recognizes only `rlwinm rX,rY,0,24,31`, case-insensitively,
and let `_implicit_add_owner` use its existing ranked indexed-byte candidate
metadata/materializer for that opcode. Keep all other opcodes on the existing
unsupported-shape path.

- [ ] **Step 4: Write the CLI regression**

```python
def test_select_order_search_auto_materializes_indexed_byte_helper_result(
    tmp_path
) -> None:
    source = tmp_path / "helper.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "static inline u8 visible_name(u8* sorted, int i) { return sorted[i]; }\n"
        "void fn_80000000(u8* sorted, int i) {\n"
        "    int name_id;\n"
        "    name_id = visible_name(sorted, i) &\n"
        "              0xFFFFFFFFFFFFFFFFu;\n"
        "    use(name_id);\n"
        "}\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.pcdump.txt"
    baseline.write_text(BASELINE, encoding="utf-8")
    result = runner.invoke(app, [
        "debug", "select-order-search", "-f", "fn_80000000",
        "--target", "r32<r33", "--class", "0",
        "--pcdump", str(baseline), "--source-file", str(source),
        "--transform-force-phys", "79:25",
        "--no-compile-probes", "--max-probes", "4", "--json",
    ])
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert any(
        probe["mutator_key"] == "steer_indexed_byte_helper_result_temp"
        for probe in payload["probes"]
    )
```

- [ ] **Step 5: Run the CLI regression**

Run: `pytest tests/test_select_order_search.py::test_select_order_search_auto_materializes_indexed_byte_helper_result -q --no-cov`

Expected: PASS after Task 1’s anchor is available.

- [ ] **Step 6: Keep selection behavior unchanged and verify the JSON boundary**

Use the existing class-0 automatic family selection. Do not add a new command
flag or a special-case scorer: the new anchor must enter as the normal
`transform-corpus:indexed_byte_address_temp_steering` probe and retain its
mutator key in JSON provenance.

- [ ] **Step 7: Verify Task 2 and commit**

Run:

```bash
pytest tests/search/directed/test_window_order_source.py::test_window_order_plan_attributes_unattributed_implicit_add_to_indexed_byte_candidates \
  tests/search/directed/test_window_order_source.py::test_window_order_plan_attributes_rlwinm_byte_temp_to_indexed_byte_candidates \
  tests/search/directed/test_window_order_source.py::test_window_order_plan_reports_implicit_temp_no_safe_source_move -q --no-cov
pytest tests/test_select_order_search.py::test_select_order_search_auto_includes_indexed_byte_transform_probes \
  tests/test_select_order_search.py::test_select_order_search_auto_materializes_indexed_byte_helper_result -q --no-cov
```

Expected: PASS.

```bash
git add tools/melee-agent/src/search/directed/window_order_source.py \
  tools/melee-agent/tests/search/directed/test_window_order_source.py \
  tools/melee-agent/tests/test_select_order_search.py
git commit -m "fix: materialize indexed byte rlwinm probes"
```

## Plan Self-Review

- Spec coverage: Task 1 handles the verified helper-result split and all
  rejection constraints; Task 2 handles the exact byte-mask `rlwinm` fallback
  and proves automatic family selection reaches the helper-result anchor.
- Placeholder scan: no deferred work or unspecified error handling remains.
- Type consistency: the same mutator key and indexed-byte family identifier
  are used in both tasks.
