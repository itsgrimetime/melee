# Select-Order Synthetic Temp Source Probes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add conservative source probes for select-order synthetic temps so issues #821 and #822 produce source-actionable variants instead of terminal attribution blockers.

**Architecture:** Keep the existing local statement-move planner unchanged. Add a small synthetic-owner probe layer in `window_order_source.py` that only handles exact pcode-first-def shapes and returns normal `LifetimeLayoutProbe` instances plus diagnostics.

**Tech Stack:** Python 3.11, pytest, existing `statement_move` AST helpers, existing `LifetimeLayoutProbe` scoring payloads.

---

## File Map

- Modify `tools/melee-agent/src/search/directed/window_order_source.py`: add synthetic temp parsing, owner discovery, owner-split probe generation, and diagnostics.
- Modify `tools/melee-agent/tests/search/directed/test_window_order_source.py`: direct red/green tests for implicit GPR add and FPR pcode-first-def temps.
- Modify `tools/melee-agent/tests/test_select_order_search.py`: CLI JSON regression that proves synthetic probes are threaded through select-order summaries.

## Task 1: Direct Synthetic Planner Tests And Implementation

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_window_order_source.py`
- Modify: `tools/melee-agent/src/search/directed/window_order_source.py`

- [ ] **Step 1: Write failing direct planner tests**

Add tests for these behaviors:

```python
def test_window_order_plan_materializes_implicit_add_owner_split() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int idx;
            int dst_iter;
            idx = seed;
            dst_iter = idx;
            sink(dst_iter);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 44, "order_move": ["before", 43]}],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 6},
            44: {
                "kind": "implicit-temp",
                "expression": "add r44,r49,r34",
                "confidence": "pcode-first-def",
            },
        },
        max_probes=4,
    )

    assert plan.probes
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["synthetic_source_probe"]["handler"] == "implicit-add-owner-split"
    assert "synthetic" in plan.probes[0].provenance["kind"]
    assert "source_diff" in diag
```

```python
def test_window_order_plan_materializes_fpr_sub_owner_split() -> None:
    source = textwrap.dedent("""\
        typedef float f32;
        void fn(f32 base, f32 y_offset, f32 row)
        {
            f32 row_offset;
            f32 row_offset_adj;
            row_offset = y_offset * row;
            row_offset_adj = row_offset - 0.4f;
            sink(row_offset_adj);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 46, "order_move": ["before", 50]}],
        source_attributions={
            46: {
                "kind": "fpr-temp",
                "expression": "fsubs f46,f45,f44",
                "confidence": "pcode-first-def",
            },
        },
        max_probes=4,
    )

    assert plan.probes
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["synthetic_source_probe"]["handler"] == "fpr-arith-owner-split"
```

Run:

```bash
pytest tools/melee-agent/tests/search/directed/test_window_order_source.py::test_window_order_plan_materializes_implicit_add_owner_split tools/melee-agent/tests/search/directed/test_window_order_source.py::test_window_order_plan_materializes_fpr_sub_owner_split -q
```

Expected: both fail because synthetic temp support is not implemented.

- [ ] **Step 2: Implement exact-shape synthetic planner support**

In `window_order_source.py`:

- Parse virtual operands from first-def strings with a small regex helper.
- Find exactly one operand local attribution for `implicit-temp` add/addi.
- Find exact floating owner assignments or cast fragments for `fpr-temp`
  arithmetic/load shapes, emitting multiple FPR load candidates when the source
  has several safe exact fragments.
- Generate owner-split `LifetimeLayoutProbe` objects with labels beginning `window-order-synthetic-...`.
- Set diagnostic `status`, `materialized_probe_labels`, `source_diff`, and `synthetic_source_probe`.
- Return explicit blockers when no supported owner is found.

- [ ] **Step 3: Verify direct tests pass**

Run:

```bash
pytest tools/melee-agent/tests/search/directed/test_window_order_source.py -q
```

Expected: all tests in that file pass.

## Task 2: CLI Diagnostic Threading Regression

**Files:**
- Modify: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Write failing CLI JSON test**

Add a regression where `debug select-order-search --json --no-compile-probes`
receives an `implicit-temp` source attribution plus operand local attribution.
Monkeypatch compilation and fallback as existing select-order tests do. Assert:

```python
diagnostics = payload["window_order_probe_diagnostics"]
assert diagnostics["listed_source_probes"] == 1
lead = diagnostics["lead_diagnostics"][0]
assert lead["status"] == "materialized"
assert lead["synthetic_source_probe"]["handler"] == "implicit-add-owner-split"
actions = payload["source_bridge_summary"]["ranked_actions"]
assert any(action["kind"] == "try-window-order-source-move" for action in actions)
```

Run:

```bash
pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_search_threads_synthetic_temp_source_probe_json -q
```

Expected: fail before implementation or before wiring is complete.

- [ ] **Step 2: Fix wiring only if needed**

If the direct planner implementation already flows through existing
`_window_order_source_probes_for`, no production change is needed for basic
diagnostic counts. If source bridge actions omit synthetic metadata or operand
source attributions are missing, update only the attribution/summary wiring in
`tools/melee-agent/src/cli/debug/__init__.py`.

- [ ] **Step 3: Verify focused CLI test passes**

Run:

```bash
pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_search_threads_synthetic_temp_source_probe_json -q
```

Expected: pass.

## Task 3: Final Verification And Issue Closure

**Files:**
- No new production files.
- Stage only intended hunks and leave unrelated dirty files untouched.

- [ ] **Step 1: Run focused tests**

```bash
pytest tools/melee-agent/tests/search/directed/test_window_order_source.py tools/melee-agent/tests/test_select_order_search.py -q
python -m py_compile tools/melee-agent/src/search/directed/window_order_source.py tools/melee-agent/src/cli/debug/__init__.py
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent debug select-order-search --help >/tmp/select-order-synthetic-help.txt
```

- [ ] **Step 2: Commit**

Stage only:

```bash
git add docs/superpowers/specs/2026-06-18-select-order-synthetic-temp-source-probes-design.md docs/superpowers/plans/2026-06-18-select-order-synthetic-temp-source-probes.md tools/melee-agent/src/search/directed/window_order_source.py tools/melee-agent/tests/search/directed/test_window_order_source.py tools/melee-agent/tests/test_select_order_search.py
git commit -m "Add select-order synthetic temp source probes"
```

- [ ] **Step 3: Refresh editable install and resolve issues**

```bash
/opt/homebrew/opt/python@3.11/bin/python3.11 -m pip install -e tools/melee-agent
/opt/homebrew/opt/python@3.11/bin/python3.11 -c "import src.cli, pathlib; print(pathlib.Path(src.cli.__file__).resolve())"
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent issue resolve 821 --note "fixed in <commit>: synthetic implicit add owner-split source probes"
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent issue resolve 822 --note "fixed in <commit>: synthetic FPR pcode-first-def owner-split source probes"
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent issues list
```
