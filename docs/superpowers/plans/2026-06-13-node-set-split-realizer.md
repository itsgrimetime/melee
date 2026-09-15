# Node-Set Split Realizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded, verified `mwcc-debug` source search that turns solve-coloring node-set split recipes into concrete alias/lifetime source candidates and reports either an improving patch or an exhausted search.

**Architecture:** Keep source generation and split-objective evaluation in a focused `src.mwcc_debug.node_set_split` module that reuses existing mutators, `CandidatePatch`/`CandidateScore`, and `simplify_search.BaselineSignature`. Add one CLI command under `debug solve` to parse either a solve-coloring `node_set_delta` JSON file or explicit ig/register/variable options, compile each candidate pcdump to verify the requested target register and no new spills, then run real-tree match scoring only for verified split realizations. Preserve source and rebuild the original object/report unless `--apply-best` keeps an improving verified candidate.

**Tech Stack:** Python 3.11, Typer CLI, pytest, existing `mwcc_debug.mutators`, `mwcc_debug.candidate_verify`, and repo-local `_build_and_match`.

**Completion note:** Implemented with the CLI tests in `tools/melee-agent/tests/search/solver/test_cli_solve.py`. Post-implementation review hardening added fresh-baseline scoring, failed-restore reporting, root-app registration coverage, and declaration-order candidate deduplication.

---

### Task 1: Node-Set Split Library

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [x] **Step 1: Write failing parser/generator tests**

Add tests that parse solve-coloring node-set-delta payloads, reject unbindable field names, generate bounded alias/lifetime patches, and evaluate target-register/no-spill objectives:

```python
def test_request_from_node_set_delta_extracts_simple_source_name() -> None:
    delta = {
        "kind": "node-set-delta",
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [{
            "target_ig": 33,
            "current_register": "f31",
            "desired_registers": ["f30"],
            "source": {"name": "holder", "expression": "holder"},
        }],
    }
    req = request_from_node_set_delta(delta)
    assert req.function == "fn_test"
    assert req.class_id == 1
    assert req.target_ig == 33
    assert req.current_reg == "f31"
    assert req.target_reg == "f30"
    assert req.var_name == "holder"


def test_request_from_node_set_delta_does_not_bind_field_name() -> None:
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [{
            "target_ig": 42,
            "current_register": "r29",
            "desired_registers": ["r27"],
            "source": {"name": "stat_value", "expression": "entries[i].stat_value"},
        }],
    }
    req = request_from_node_set_delta(delta)
    assert req is not None
    assert req.var_name is None
    assert "bindable" in req.blocked_reason


def test_generate_node_set_split_patches_alias_and_lifetime_forms() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int holder;\n"
        "    int out;\n"
        "    holder = make();\n"
        "    out = holder + 1;\n"
        "    use(out, holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="holder",
    )
    patches = generate_node_set_split_patches(source, "fn_test", req, max_read_sites=2)
    ids = {patch.candidate_id for patch in patches}
    assert "node-split-alias-holder-use0" in ids
    assert "node-split-lifetime-holder-use0" in ids
    assert len({patch.patched_source for patch in patches}) == len(patches)


def test_evaluate_node_set_split_signature_requires_target_reg_and_no_new_spills() -> None:
    baseline = BaselineSignature(
        interference_edges=frozenset(),
        coalesce_mappings=frozenset(),
        spill_set=frozenset(),
        simplify_order=(40,),
        assigned_regs=frozenset({(40, 31)}),
    )
    candidate = BaselineSignature(
        interference_edges=frozenset(),
        coalesce_mappings=frozenset(),
        spill_set=frozenset(),
        simplify_order=(40,),
        assigned_regs=frozenset({(40, 30)}),
    )
    req = NodeSetSplitRequest("fn_test", 1, 40, current_reg="f31", target_reg="f30", var_name="holder")
    assert evaluate_node_set_split_signature(baseline, candidate, req)["status"] == "realized"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tools/melee-agent/tests/test_node_set_split.py -q`

Expected: import failure for `src.mwcc_debug.node_set_split`.

- [x] **Step 3: Implement library module**

Create:

```python
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any

from .mutators import (
    MutationUnsupported,
    mutate_insert_alias_before_use,
    mutate_preserve_lifetime_after_use,
)
from .source_shape import CandidatePatch, CandidateScore


@dataclass(frozen=True)
class NodeSetSplitRequest:
    function: str
    class_id: int
    target_ig: int
    current_reg: str | None = None
    target_reg: str | None = None
    var_name: str | None = None


def request_from_node_set_delta(delta: dict[str, Any], target_ig: int | None = None) -> NodeSetSplitRequest | None:
    ...


def generate_node_set_split_patches(source: str, function: str, request: NodeSetSplitRequest, *, max_read_sites: int = 4) -> list[CandidatePatch]:
    ...


def summarize_node_set_split_scores(*, function: str, request: NodeSetSplitRequest, patches: list[CandidatePatch], scores: list[CandidateScore], threshold: float) -> dict[str, Any]:
    ...
```

Implementation details:
- Accept only simple identifier source names. Use `^[A-Za-z_][A-Za-z0-9_]*$`.
- Prefer a simple identifier from `source.expression`, then `source.base_var`, then `source.name` only if the expression is not field-like. `entries[i].stat_value` must not bind `stat_value`.
- Generate candidate ids:
  - `node-split-alias-{var}-ig{target_ig}-use{idx}`
  - `node-split-lifetime-{var}-ig{target_ig}-use{idx}`
- For aliases, call `mutate_insert_alias_before_use(..., new_name=f"{var}_split_{target_ig}_{idx}")`.
- For lifetime sinks, call `mutate_preserve_lifetime_after_use(..., sink_name=f"{var}_split_sink_{target_ig}_{idx}")`.
- Catch `MutationUnsupported` per candidate and continue.
- Deduplicate by patched source.
- Build `CandidatePatch.hunk` using `difflib.unified_diff`.
- Add `evaluate_node_set_split_signature(baseline, candidate, request)` using `BaselineSignature.assigned_regs` and `spill_set`; status is `realized` only when the target ig has the target physical register and `candidate.spill_set - baseline.spill_set` is empty.
- Summary status is `improved` if any score has objective status `realized` and `checkdiff_delta >= threshold`, `exhausted` if candidates were generated but none improved, and `blocked` if no candidates were generated.

- [x] **Step 4: Run library tests**

Run: `python -m pytest tools/melee-agent/tests/test_node_set_split.py -q`

Expected: all tests pass.

### Task 2: CLI Verification Path

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_debug_cli_reorg.py`

- [x] **Step 1: Write failing CLI tests**

Add tests in `tools/melee-agent/tests/search/solver/test_cli_solve.py` for:
- An improving candidate: monkeypatch candidate pcdump compilation so exactly one alias candidate has the requested target register and no new spills, monkeypatch `_build_and_match_with_diagnostic` to return a higher score only for that source, pass `--apply-best --json`, and assert JSON status `improved`.
- An exhausted search: all candidate pcdumps compile but fail the target-register objective or do not improve; assert status `exhausted` and source restored.
- A blocked field-source request: node-set-delta source expression is `entries[i].stat_value`; assert exit 3 and a bindable-source reason.
- A compile-failed candidate: compile failure is counted as failed, not unscored.

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tools/melee-agent/tests/test_debug_cli_reorg.py -k node_set_split -q`

Expected: command does not exist.

- [x] **Step 3: Implement `debug solve node-set-split`**

Add a command to `solve_app`:

```python
@solve_app.command("node-set-split")
def solve_node_set_split_cmd(...):
    ...
```

Required behavior:
- Resolve source file from `--source-file` or `_find_unit_for_function`.
- Build a `NodeSetSplitRequest` from `--node-set-delta` JSON or explicit `--ig/--class/--current-reg/--target-reg/--var`.
- Generate patches with `generate_node_set_split_patches`.
- Compile a baseline pcdump and each candidate pcdump through `compile_source_variant`; evaluate each candidate with `evaluate_node_set_split_signature`.
- Skip real-tree checkdiff scoring for candidates whose objective status is not `realized`.
- Baseline match with `_build_and_match_with_diagnostic(unit, function, DEFAULT_MELEE_ROOT)`.
- Verify realized patches with real-tree source writes and `_build_and_match_with_diagnostic`; raise/count candidate failures when the diagnostic build fails.
- After an exhausted or failed dry run, restore source and rebuild `build/GALE01/src/<unit>.o` plus `build/GALE01/report.json` so object/report state matches restored source.
- Print JSON via `summarize_node_set_split_scores` or concise text.
- Exit 0 on `improved`, 4 on `exhausted`, 3 on `blocked`.
- Apply only the best improving candidate when `--apply-best` is set.

- [x] **Step 4: Run CLI tests**

Run: `python -m pytest tools/melee-agent/tests/test_debug_cli_reorg.py -k node_set_split -q`

Expected: all selected tests pass.

### Task 3: Integration Verification and Queue Closure

**Files:**
- No production files unless tests reveal a bug.

- [ ] **Step 1: Run focused regression tests**

Run:

```bash
python -m pytest \
  tools/melee-agent/tests/test_node_set_split.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py -k 'node_set_split or decl_orders or diagnose_decl_orders' \
  tools/melee-agent/tests/test_mwcc_debug_simplify_variants.py \
  tools/melee-agent/tests/test_mwcc_debug_source_patch.py
```

- [ ] **Step 2: Run command-level smokes**

Run:

```bash
python -m src.cli debug solve node-set-split --help
python -m src.cli debug mutate decl-orders --help
```

- [ ] **Step 3: Review, commit, merge to master, refresh install**

Commit the plan and implementation, merge to `master`, reinstall editable `melee-agent` from `/Users/mike/code/melee/tools/melee-agent`, and resolve only #654/#656/#655/#657 after verification.
