# Case-C Terminal Exhaustion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add machine-readable terminal summaries for retained Case-C select-order source-probe exhaustion and all-overlap recombine skips.

**Architecture:** Extend existing JSON payload builders in `debug select-order-search` and `debug search combine`; do not add new commands or scoring loops. Preserve `target_score` through existing summary structures via small extraction helpers.

**Tech Stack:** Python, Typer CLI, pytest, existing `melee-agent` test harness.

## Global Constraints

- Preserve unrelated local work in `/Users/mike/code/melee`; stage only files touched for issue #865.
- Use TDD: write failing regression tests before production changes.
- Do not add new source transform families or a new six-FPR rescoring hook for #865.
- Do not modify Melee C source.
- Refresh editable `/opt/homebrew/bin/melee-agent` from `/Users/mike/code/melee` after changing CLI tooling.

---

### Task 1: Select-Order Target Score and Soft Terminal Summary

**Files:**
- Modify: `tools/melee-agent/tests/test_select_order_search.py`
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`

**Interfaces:**
- Produces: `_select_order_variant_target_score(variant: Mapping[str, Any]) -> dict[str, Any] | None`
- Produces: `_select_order_terminal_exhaustion_summary(...) -> dict[str, Any] | None`
- Consumes: existing `_select_order_diagnostic_buckets`, `_select_order_source_bridge_summary`, and `debug_select_order_search_cmd` JSON payload.

- [ ] **Step 1: Add failing target-score propagation test**

Add a test to `tools/melee-agent/tests/test_select_order_search.py` that calls `_select_order_diagnostic_buckets` with one ok variant whose objective contains:

```python
"target_score": {
    "matched": 4,
    "targeted": 6,
    "virtuals": {
        "33": {"expected": 26, "actual": 26, "matched": True},
        "46": {"expected": 26, "actual": 1, "matched": False},
    },
}
```

Assert that the `global-top` or `best-frame-preserving-only` bucket entry includes `target_score["virtuals"]["46"]["actual"] == 1`.

- [ ] **Step 2: Run red test**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_diagnostic_buckets_preserve_target_score -q
```

Expected: fail because bucket entries do not include `target_score`.

- [ ] **Step 3: Add failing terminal-summary test**

Add a test that calls `_select_order_terminal_exhaustion_summary` with:

- `ranked_variants`: two ok retained `.c` variants, both force-phys unsatisfied;
- `force_phys={33: 26, 46: 26}` so protected hits can exist while blocker target IG46 remains dead;
- `blocker_targets={46}`;
- `diagnostic_buckets={"force-phys-hit-33": [{"label": "protected"}], "force-phys-hit-46": [], "global-top": [...]}`;
- `source_bridge_summary={"status": "blocked", "dominant_blocker": "source-probes-exhausted", "blocker_classes": ["wrong-register"], "terminal_next_lane": {"status": "available", "actions": [{"kind": "try-retained-variant-recombine"}]}}`;
- `timed_out=False`, `class_id=1`.

Assert:

```python
summary["status"] == "blocked"
summary["kind"] == "degree-zero-fpr-case-c-source-exhaustion"
summary["dominant_blocker"] == "source-probes-exhausted"
summary["force_phys_targets"]["46"] == 26
summary["blocker_targets"] == [46]
summary["recombine_status"] == "unverified"
"manual-subhunk-recombine" in summary["next_source_lever_classes"]
summary["best_retained_variants"][0]["target_score"]["virtuals"]["46"]["actual"] == 1
```

- [ ] **Step 4: Run red terminal test**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_terminal_exhaustion_reports_case_c_no_hit -q
```

Expected: fail because `_select_order_terminal_exhaustion_summary` does not exist.

- [ ] **Step 5: Implement minimal helpers**

In `tools/melee-agent/src/cli/debug/__init__.py`, add:

```python
def _select_order_variant_target_score(
    variant: Mapping[str, Any],
) -> dict[str, Any] | None:
    objective = variant.get("objective")
    candidates = []
    if isinstance(objective, Mapping):
        candidates.append(objective.get("target_score"))
        validator = objective.get("validator_payload")
        if isinstance(validator, Mapping):
            candidates.append(validator.get("target_score"))
    candidates.append(variant.get("target_score"))
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            return _select_order_json_safe(dict(candidate))
    return None
```

Add the extracted `target_score` to `_select_order_diagnostic_buckets`, `_select_order_source_bridge_terminal_next_lane`, and `_select_order_source_bridge_summary` variant entries.

Add `_select_order_terminal_exhaustion_summary` using the activation rules from the design. Keep it additive and bounded to the top retained variants. Do not let select-order claim recombine exhaustion; use `recombine_status: "unverified"` when the only next lane is recombine.

- [ ] **Step 6: Wire summary into JSON payload**

In `debug_select_order_search_cmd`, compute the summary after `source_bridge_summary` is built and before the JSON payload is emitted. Add it to `_json_success_payload()` as `terminal_exhaustion_summary`.

- [ ] **Step 7: Run green tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_diagnostic_buckets_preserve_target_score tools/melee-agent/tests/test_select_order_search.py::test_select_order_terminal_exhaustion_reports_case_c_no_hit -q
```

Expected: both pass.

### Task 2: Combine All-Overlap Terminal Summary

**Files:**
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
- Modify: `tools/melee-agent/src/search/cli/__init__.py`

**Interfaces:**
- Produces: `_combine_terminal_summary(combos: list[dict], loaded: list[dict]) -> dict | None`
- Consumes: existing `combine_cmd` JSON payload.

- [ ] **Step 1: Add failing combine test**

Add a CLI test using three incompatible candidates so every pair is skipped for `overlapping-source-hunks`. Assert that `payload["terminal_summary"]` exists and contains:

```python
{
    "status": "blocked",
    "dominant_blocker": "recombine-overlapping-source-hunks",
    "terminal_blocker": "manual-subhunk-recombine-required",
}
```

Also assert `skipped_count == 3`, each skipped parent pair is present, `manual_range_hint` contains `--range`, and at least one parent hunk span includes `base_start` and `base_end`.

- [ ] **Step 2: Run red combine test**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/test_cli_smoke.py::test_search_combine_reports_all_overlap_terminal_summary -q
```

Expected: fail because `terminal_summary` is absent.

- [ ] **Step 3: Implement combine summary**

In `tools/melee-agent/src/search/cli/__init__.py`, add a helper that returns `None` unless all combinations are skipped with `reason == "overlapping-source-hunks"`. When active, return the blocker payload, parent pairs, hunk spans from loaded candidates, and manual range hint. Add it to `payload` in `combine_cmd` only when not `None`.

- [ ] **Step 4: Run green combine test**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/test_cli_smoke.py::test_search_combine_reports_all_overlap_terminal_summary -q
```

Expected: pass.

### Task 3: Verification and Integration

**Files:**
- Modify only files from Tasks 1-2.

- [ ] **Step 1: Run touched tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py tools/melee-agent/tests/search/test_cli_smoke.py::test_search_combine_reports_all_overlap_terminal_summary -q
```

Expected: the selected tests pass. If the full select-order file has a known unrelated failure, document it and run the focused #865 tests plus adjacent passing tests.

- [ ] **Step 2: Run CLI smoke checks**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug select-order-search --help
PYTHONPATH=tools/melee-agent python -m src.cli debug search combine --help
```

Expected: both exit 0.

- [ ] **Step 3: Commit implementation**

Stage only #865 files:

```bash
git add docs/superpowers/specs/2026-06-20-case-c-terminal-exhaustion-design.md \
  docs/superpowers/plans/2026-06-20-case-c-terminal-exhaustion.md \
  tools/melee-agent/tests/test_select_order_search.py \
  tools/melee-agent/src/cli/debug/__init__.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/src/search/cli/__init__.py
git commit -m "Report Case-C select-order exhaustion"
```

- [ ] **Step 4: Refresh editable install**

Run:

```bash
/opt/homebrew/bin/python3.11 -m pip install -e /Users/mike/code/melee/tools/melee-agent
/opt/homebrew/bin/python3.11 - <<'PY'
import src.cli
print(src.cli.__file__)
PY
```

Expected import path: `/Users/mike/code/melee/tools/melee-agent/src/cli/__init__.py`.
