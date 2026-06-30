# In-Place Recolor Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `debug solve node-set-split --coupled --json` emit an explicit in-place recolor classification when the source-shape search reaches a practical ceiling.

**Architecture:** Add a pure summary helper in `node_set_split.py` and thread its output through existing summary JSON. The CLI already reports blocked, candidate-limited, budget-limited, and all-wrong-register cases; this feature labels those outcomes for the in-place recolor problem without changing candidate generation or acceptance.

**Tech Stack:** Python, Typer CLI, pytest, existing `mwcc_debug.node_set_split` summary model.

---

### Task 1: Unit-Level Classification

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Modify: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Add failing tests for terminal and incomplete classifications**

Add tests near `test_summarize_coupled_all_wrong_register_marks_exhaustive_terminal`:

```python
def test_summarize_coupled_all_wrong_register_emits_no_shippable_classification() -> None:
    reqs = _coupled_reqs()
    aggregate = NodeSetSplitRequest(
        "fn_test", 0, 34, target_reg="r27+r25", var_name="holder+other"
    )
    patches = [
        CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0"),
        CandidatePatch("c1", "src1", "c1", ((0, 0),), hunk="@@ c1"),
    ]
    scored = []
    for candidate_id in ("c0", "c1"):
        score = CandidateScore(
            candidate_id, compile_ok=True, checkdiff_pct=None,
            checkdiff_delta=None, pcdump_score_delta=None,
            diagnostics_path=None, status="objective-failed",
        )
        scored.append({
            "score": score,
            "objective": {"status": "wrong-register"},
        })

    summary = summarize_node_set_split_scores(
        "fn_test", aggregate, patches, scored, threshold=1.0,
        coupled_requests=reqs,
    )

    classification = summary["in_place_recolor"]
    assert classification["kind"] == "coupled-same-class-in-place-recolor"
    assert classification["status"] == "no-shippable-mutator"
    assert classification["target_igs"] == [34, 44]
    assert classification["class_id"] == 0
    assert classification["evidence"]["wrong_register_count"] == 2
    assert classification["evidence"]["pending_count"] == 0
    assert "do not rerun" in classification["recommendation"]


def test_summarize_coupled_candidate_limited_classification_is_incomplete() -> None:
    reqs = _coupled_reqs()
    aggregate = NodeSetSplitRequest(
        "fn_test", 0, 34, target_reg="r27+r25", var_name="holder+other"
    )
    patches = [
        CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0"),
        CandidatePatch("c1", "src1", "c1", ((0, 0),), hunk="@@ c1"),
    ]
    score = CandidateScore(
        "c0", compile_ok=True, checkdiff_pct=None,
        checkdiff_delta=None, pcdump_score_delta=None,
        diagnostics_path=None, status="objective-failed",
    )

    summary = summarize_node_set_split_scores(
        "fn_test", aggregate, patches,
        [{"score": score, "objective": {"status": "wrong-register"}}],
        threshold=1.0, stop_reason="candidate-limit", candidate_limit=1,
        coupled_requests=reqs,
    )

    classification = summary["in_place_recolor"]
    assert classification["status"] == "incomplete"
    assert classification["terminal"] is False
    assert "larger --max-candidates" in classification["recommendation"]
```

- [ ] **Step 2: Run RED tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_node_set_split.py::test_summarize_coupled_all_wrong_register_emits_no_shippable_classification \
  tools/melee-agent/tests/test_node_set_split.py::test_summarize_coupled_candidate_limited_classification_is_incomplete
```

Expected: both fail with `KeyError: 'in_place_recolor'`.

- [ ] **Step 3: Add the classification helper**

Add a helper near `_node_set_split_next_steps`:

```python
def _in_place_recolor_classification(
    *,
    status: str,
    request: NodeSetSplitRequest,
    patches: list[CandidatePatch],
    rows: list[dict[str, Any]],
    coupled_requests: list[NodeSetSplitRequest] | None,
    wrong_register_exhausted: bool,
    stop_reason: str | None,
    pending_count: int,
    candidate_limit: int | None,
    budget_seconds: float | None,
) -> dict[str, Any] | None:
    if coupled_requests is None:
        return None
    target_igs = [req.target_ig for req in coupled_requests]
    evidence = {
        "generated_count": len(patches),
        "scored_count": len(rows),
        "pending_count": pending_count,
        "wrong_register_count": sum(
            1 for row in rows if row.get("objective_status") == "wrong-register"
        ),
        "stop_reason": stop_reason,
    }
    candidate_cap_may_have_truncated = (
        candidate_limit is not None and len(patches) >= candidate_limit
    )

    if wrong_register_exhausted and not candidate_cap_may_have_truncated:
        class_status = "no-shippable-mutator"
        terminal = True
        recommendation = (
            "do not rerun node-set-split with the same delta; classify this "
            "as a practical ceiling for source-shape in-place recolor and move "
            "to backend/coalescer or a new mutator family"
        )
    elif status == "blocked" and len(coupled_requests) < 2:
        class_status = "insufficient-source-bindings"
        terminal = False
        recommendation = (
            request.blocked_reason
            or "coupled mode needs at least two source-bindable requests"
        )
    elif stop_reason == "candidate-limit" or candidate_cap_may_have_truncated:
        class_status = "incomplete"
        terminal = False
        recommendation = (
            "rerun with a larger --max-candidates value, or use "
            "--max-candidates 0 for an exhaustive source-shape search"
        )
    elif stop_reason == "budget-exhausted":
        class_status = "incomplete"
        terminal = False
        recommendation = "rerun with a larger --budget"
    else:
        class_status = "search-active"
        terminal = False
        recommendation = (
            "continue only if a broader source mutator family is available"
        )
    return {
        "kind": "coupled-same-class-in-place-recolor",
        "status": class_status,
        "terminal": terminal,
        "function": request.function,
        "class_id": request.class_id,
        "target_igs": target_igs,
        "evidence": evidence,
        "recommendation": recommendation,
    }
```

Call it from `summarize_node_set_split_scores` after `coupled_requests` handling and attach the result as `summary["in_place_recolor"]` when not `None`.

- [ ] **Step 4: Run GREEN tests**

Run the same two tests. Expected: both pass.

### Task 2: CLI Blocked Classification

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Modify: `tools/melee-agent/tests/test_node_set_split.py`
- Modify: `tools/melee-agent/tests/search/solver/test_cli_solve.py`

- [ ] **Step 1: Add failing CLI test for `<2` bindable coupled requests**

Extend `test_cli_coupled_blocks_when_less_than_two_bindable_requests` to assert:

```python
classification = summary["in_place_recolor"]
assert classification["status"] == "insufficient-source-bindings"
assert classification["terminal"] is False
assert classification["target_igs"] == [34]
```

- [ ] **Step 2: Run RED test**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_node_set_split.py::test_cli_coupled_blocks_when_less_than_two_bindable_requests
```

Expected: fail because blocked summaries currently add `coupled_requests` after the summary helper has already run.

- [ ] **Step 3: Route blocked coupled summaries through the coupled summary path**

In `solve_node_set_split_cmd`, replace the manual blocked-summary path for
`len(coupled_requests) < 2` with a call to `summarize_node_set_split_scores`
using a blocked aggregate request and `coupled_requests=coupled_requests`, so
the classification helper sees the coupled context.

- [ ] **Step 4: Run GREEN test**

Run the same CLI test. Expected: pass.

- [ ] **Step 5: Add and pass a coupled early-budget CLI regression**

In `tools/melee-agent/tests/search/solver/test_cli_solve.py`, add a test that
passes `--budget 0` with a coupled delta that has two bindable requests and
asserts `payload["in_place_recolor"]["status"] == "incomplete"`. Then update
the baseline timeout and baseline match timeout paths in
`solve_node_set_split_cmd` to pass `coupled_requests=coupled_requests` into
`summarize_node_set_split_scores`.

### Task 3: Regression and Smoke

**Files:**
- No additional production files.

- [ ] **Step 1: Run affected unit tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_node_set_split.py \
  tools/melee-agent/tests/search/solver/test_cli_solve.py
```

Expected: all pass.

- [ ] **Step 2: Run static checks**

Run:

```bash
python -m compileall -q tools/melee-agent/src
git diff --check
```

Expected: no output and exit 0.

- [ ] **Step 3: Run live classification smoke**

Use the ignored evidence directory:

```bash
mkdir -p build/issue728
melee-agent debug solve coloring -f mnDiagram_8023FC28 --class gpr --json > build/issue728/8023FC28-solve-coloring.json
melee-agent debug solve node-set-split --coupled --node-set-delta build/issue728/8023FC28-solve-coloring.json --json --max-candidates 0 > build/issue728/8023FC28-node-set-split.json
python -m json.tool build/issue728/8023FC28-node-set-split.json >/tmp/issue728-8023FC28.pretty
```

Expected: JSON includes `in_place_recolor`. If the run is blocked because only
one source binding exists, its status is `insufficient-source-bindings`; if the
run exhausts all wrong-register candidates, its status is
`no-shippable-mutator`.
