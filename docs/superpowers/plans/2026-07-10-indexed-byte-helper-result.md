# Indexed Byte Helper-Result Steering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make automatic GPR indexed-byte select-order searches materialize a safe source probe when the byte result comes from a `u8` helper call rather than a caller-side array expression.

**Architecture:** Extend the existing `indexed_byte_address_temp_steering` anchor generator with one helper-result assignment form. The anchor replaces a single eligible masked helper assignment with a fresh `u8` local and a follow-up assignment; existing corpus orchestration then retains, force-phys scores, and validates it unchanged.

**Tech Stack:** Python 3, regex-based source anchors, transform-corpus registry, pytest.

## Global Constraints

- Only source-visible helpers declared or defined with return type `u8` qualify.
- Only one simple call occurrence with identifier-or-integer arguments qualifies.
- Preserve the original destination, statement order, and surrounding control flow.
- Reject non-byte helpers, side-effecting arguments, and ambiguous occurrences without producing a probe.
- Reuse the existing `indexed_byte_address_temp_steering` family and real-tree validation path.

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

### Task 2: Verify automatic select-order family materialization

**Files:**

- Modify: `tools/melee-agent/tests/test_select_order_search.py`

**Interfaces:**

- Consumes: automatic class-0 `indexed_byte_address_temp_steering` selection
  when `--transform-force-phys` is supplied.
- Produces: JSON probe output containing the helper-result mutator without
  enabling extra transform families.

- [ ] **Step 1: Write the failing CLI regression**

```python
def test_select_order_search_auto_materializes_indexed_byte_helper_result(
    monkeypatch, tmp_path
) -> None:
    source = tmp_path / "helper.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "static inline u8 visible_name(u8* sorted, int i) { return sorted[i]; }\n"
        "void fn(u8* sorted, int i) {\n"
        "    int name_id;\n"
        "    name_id = visible_name(sorted, i) &\n"
        "              0xFFFFFFFFFFFFFFFFu;\n"
        "}\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.pcdump.txt"
    baseline.write_text("Starting function fn\n", encoding="utf-8")
    result = runner.invoke(app, [
        "debug", "select-order-search", "-f", "fn",
        "--pcdump", str(baseline), "--source-file", str(source),
        "--transform-force-phys", "79:25", "--no-compile-probes", "--json",
    ])
    payload = json.loads(result.stdout)
    assert any(
        probe["mutator_key"] == "steer_indexed_byte_helper_result_temp"
        for probe in payload["probes"]
    )
```

- [ ] **Step 2: Run the failing CLI regression**

Run: `pytest tests/test_select_order_search.py::test_select_order_search_auto_materializes_indexed_byte_helper_result -q --no-cov`

Expected: FAIL before Task 1’s anchor is available.

- [ ] **Step 3: Keep selection behavior unchanged and verify the JSON boundary**

Use the existing class-0 automatic family selection. Do not add a new command
flag or a special-case scorer: the new anchor must enter as the normal
`transform-corpus:indexed_byte_address_temp_steering` probe and retain its
mutator key in JSON provenance.

- [ ] **Step 4: Verify Task 2 and commit**

Run: `pytest tests/test_select_order_search.py -q --no-cov`

Expected: PASS.

```bash
git add tools/melee-agent/tests/test_select_order_search.py
git commit -m "test: cover indexed byte helper select order probes"
```

## Plan Self-Review

- Spec coverage: Task 1 handles the verified helper-result split and all
  rejection constraints; Task 2 proves automatic family selection reaches it.
- Placeholder scan: no deferred work or unspecified error handling remains.
- Type consistency: the same mutator key and indexed-byte family identifier
  are used in both tasks.
