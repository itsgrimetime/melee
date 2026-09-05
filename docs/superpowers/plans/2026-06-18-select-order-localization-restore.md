# Select-Order Localization and Restore Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve #791, #792, and #793 by making select-order output localize blocked guard/source leads and by restoring live source byte-exactly after interruption.

**Architecture:** Add a diagnostic planner beside the existing window-order source probe generator, then have `debug select-order-search` consume those per-lead diagnostics in `source_bridge_summary`. Add inline-boundary drift summaries for guard-rejected allocator-hit candidates and wrap the select-order command body in a byte snapshot restore guard.

**Tech Stack:** Python, Typer, pytest, existing `statement_move`, checkdiff JSON, and select-order test fixtures.

---

### Task 1: Window-Order Source Probe Planner

**Files:**
- Modify: `tools/melee-agent/src/search/directed/window_order_source.py`
- Test: `tools/melee-agent/tests/search/directed/test_window_order_source.py`

- [x] **Step 1: Write failing planner tests**

Add tests that import `plan_window_order_source_probes` and assert:

```python
def test_window_order_plan_marks_materialized_lead_actionable():
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int idx;
            int guard;
            int dst_iter;
            idx = seed;
            guard = seed;
            dst_iter = idx;
        }
    """)
    plan = plan_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={34: {"kind": "local", "name": "dst_iter", "source_line": 8}},
        max_probes=4,
    )
    assert len(plan.probes) == 1
    assert plan.lead_diagnostics[0]["status"] == "materialized"
    assert plan.lead_diagnostics[0]["materialized_probe_labels"] == [plan.probes[0].label]
    assert "source_diff" in plan.lead_diagnostics[0]
```

Also add tests for `ambiguous-movable-local-write`,
`implicit-temp-no-safe-source-move`, and `no-legal-destination`.

- [x] **Step 2: Run planner tests and verify failure**

Run:

```bash
python -m pytest tools/melee-agent/tests/search/directed/test_window_order_source.py -q
```

Expected: fail because `plan_window_order_source_probes` does not exist.

- [x] **Step 3: Implement planner dataclass and diagnostics**

Add:

```python
@dataclass(frozen=True)
class WindowOrderSourceProbePlan:
    probes: list[LifetimeLayoutProbe]
    lead_diagnostics: list[dict[str, Any]]
```

Implement `plan_window_order_source_probes(source_text, *, function,
fallback_leads, source_attributions=None, max_probes=8)` with the same inputs
as `generate_window_order_source_probes`. It should reuse the current safe move
logic, populate per-lead diagnostics, and return generated probes. Make
`generate_window_order_source_probes()` call the planner and return
`plan.probes`.

- [x] **Step 4: Run planner tests and verify pass**

Run:

```bash
python -m pytest tools/melee-agent/tests/search/directed/test_window_order_source.py -q
```

Expected: pass.

### Task 2: Source Bridge Per-Lead Actionability

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [x] **Step 1: Write failing source bridge tests**

Add tests that call `_select_order_source_bridge_summary()` with
`window_order_probe_diagnostics["lead_diagnostics"]`.

One test should verify a lead with `materialized_probe_labels` gets
`source_actionable=True` and a `try-window-order-source-move` action. Another
should verify an attributed lead with `terminal_blocker =
"ambiguous-movable-local-write"` stays blocked and carries that blocker in the
lead and action list.

- [x] **Step 2: Run targeted tests and verify failure**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_source_bridge_summary_explains_order_leads_and_blockers -q
```

Expected: current summary ignores per-lead diagnostics.

- [x] **Step 3: Wire planner diagnostics into select-order**

Change `_window_order_source_probes_for()` to call
`plan_window_order_source_probes()` and save the latest `lead_diagnostics` in
the enclosing command. Include those diagnostics in
`window_order_probe_diagnostics`.

Update `_select_order_source_bridge_leads()` and
`_select_order_source_bridge_summary()` so actionability is per lead, based on
matching `target_ig` and materialized/scored probe labels, not global
`listed_source_probes`.

- [x] **Step 4: Run targeted select-order tests**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_search_json_includes_source_bridge_summary tools/melee-agent/tests/test_select_order_search.py::test_select_order_search_force_phys_lists_window_order_probe_json -q
```

Expected: pass.

### Task 3: Inline-Boundary Drift Localization

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [x] **Step 1: Write failing guard localization tests**

Add a helper-level test for a rejected guard-repair candidate whose guard class
is `inline-boundary-toolchain-artifact`. Assert
`_select_order_guard_repair_summary()` includes:

```python
lane = summary["lanes"][0]
assert lane["inline_boundary_drift"]["status"] in {"localized", "coarse"}
assert lane["inline_boundary_drift"]["next_probe"]["axis"] == "inline-boundary"
assert "debug search structure" in lane["inline_boundary_drift"]["next_probe"]["command"]
```

- [x] **Step 2: Run the guard localization test and verify failure**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_summary_groups_rejected_allocator_hits -q
```

Expected: fail because no inline-boundary drift object exists.

- [x] **Step 3: Implement localization helpers**

Add helper functions near guard repair helpers:

- `_select_order_inline_boundary_drift_summary(candidate, function=None)`
Use existing guard fields, retained source path, compact function hunk, and a
targeted `debug search structure --axis inline-boundary` next-probe command. If
only guard fields are present, return status `coarse`.

- [x] **Step 4: Run guard localization tests**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_summary_groups_rejected_allocator_hits -q
```

Expected: pass.

### Task 4: Command-Wide Byte Restore

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [x] **Step 1: Write failing restore tests**

Add tests that assert:

```python
def test_select_order_command_restore_registers_active_source_for_signal(tmp_path):
    source = tmp_path / "sample.c"
    original = "void fn_80000000(void) { /* original */ }\n"
    source.write_text(original)
    debug_cli._ACTIVE_SOURCE_RESTORES.clear()
    debug_cli._SelectOrderCommandSourceRestore(source, melee_root=tmp_path)
    source.write_text("void fn_80000000(void) { /* interrupted residue */ }\n")
    with pytest.raises(SystemExit):
        debug_cli._restore_active_sources_for_signal(signal.SIGTERM, None)
    assert source.read_text() == original
```

Existing select-order tests also cover live source restore after probe
generation and probe compilation mutate the source.

- [x] **Step 2: Run restore tests and verify failure**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py -k 'restore and select_order' -q
```

Expected: at least one new test fails before command-wide restore is added.

- [x] **Step 3: Implement command restore context**

Make `_SelectOrderCommandSourceRestore` register the active command snapshot
before source probing starts. Active restore snapshots are stacked per path so
nested scorers unregister only their own top layer and the command snapshot
remains active underneath. Restore/unregister the command snapshot on normal and
known early exits, with a best-effort destructor for unexpected exceptions.

- [x] **Step 4: Run restore tests**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py -k 'restore and select_order' -q
```

Expected: pass.

### Task 5: Verification, Editable Install, and Issue Resolution

**Files:**
- Verify: `tools/melee-agent/src/search/directed/window_order_source.py`
- Verify: `tools/melee-agent/src/cli/debug/__init__.py`
- Verify: `tools/melee-agent/tests/search/directed/test_window_order_source.py`
- Verify: `tools/melee-agent/tests/test_select_order_search.py`

- [x] **Step 1: Run focused test suites**

Run:

```bash
python -m pytest tools/melee-agent/tests/search/directed/test_window_order_source.py tools/melee-agent/tests/test_select_order_search.py -q
```

Expected: pass.

- [x] **Step 2: Run CLI smoke checks**

Run:

```bash
python -m py_compile tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/src/search/directed/window_order_source.py
python -m src.cli debug select-order-search --help >/tmp/select-order-help.txt
git diff --check
```

Expected: all pass.

- [ ] **Step 3: Refresh editable install**

Run:

```bash
python -m pip install -e tools/melee-agent
/opt/homebrew/bin/melee-agent debug select-order-search --help | rg 'guard|repair|beam'
python - <<'PY'
import src.cli.debug
print(src.cli.debug.__file__)
PY
```

Expected: imported path is under `/Users/mike/code/melee/tools/melee-agent`.

- [ ] **Step 4: Commit and resolve issues**

Stage only intended hunks and docs, preserving unrelated local work. Commit with:

```bash
git commit -m "Localize select-order source repair blockers"
```

Resolve #791, #792, and #793 with notes naming the commit hash and verified
behavior.
