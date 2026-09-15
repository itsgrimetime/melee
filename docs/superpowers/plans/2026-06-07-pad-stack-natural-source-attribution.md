# PAD_STACK Natural-Source Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured natural-source attribution to frame-transform probe evaluation so PAD_STACK-only wins are clearly diagnostic rather than PR-ready source replacements.

**Architecture:** Extend `tools/melee-agent/src/mwcc_debug/frame_reservations.py` in the existing evaluation layer. Add focused tests in `tools/melee-agent/tests/test_frame_reservations.py`; no new CLI command is needed because `debug mutate frame-transform-search --json` already returns `frame_transform_probe_evaluation`.

**Tech Stack:** Python, pytest, existing `melee-agent` CLI.

---

### Task 1: Frame-Transform Natural-Source Attribution

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/frame_reservations.py`
- Test: `tools/melee-agent/tests/test_frame_reservations.py`

- [ ] **Step 1: Write failing tests**

Add tests that call `evaluate_frame_transform_probe_results()` directly:

```python
def test_frame_transform_evaluation_reports_padstack_only_diagnostic_attribution() -> None:
    report = {"current": {"frame_size": 96}, "expected": {"frame_size": 80}, "frame_delta": -16}
    padstack = {
        "label": "frame-reservation-pad-stack-16",
        "operator": "frame-reservation-pad-stack",
        "status": "ok",
        "objective": {"frame_after": 80},
    }
    block_scope = {
        "label": "block-scope",
        "operator": "block-scope",
        "status": "ok",
        "objective": {"frame_after": 96},
    }

    evaluation = evaluate_frame_transform_probe_results(report, [padstack, block_scope])

    attribution = evaluation["natural_source_attribution"]
    assert evaluation["verdict"] == "diagnostic-pad-stack-frame-transform"
    assert attribution["status"] == "diagnostic-pad-stack-only"
    assert attribution["verdict"] == "diagnostic-only"
    assert attribution["best_diagnostic_variant"]["label"] == "frame-reservation-pad-stack-16"
    assert attribution["best_natural_variant"] is None
    assert "PAD_STACK diagnostic" in attribution["missing_reason"]
```

Also add tests for `validated-natural-source`, `partial-natural-source`, and
`no-source-lever`. The PAD_STACK-only test should include a
`frame_first_divergence.verdict.reason` fixture and assert that reason appears
in `missing_reason`.

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_frame_reservations.py::test_frame_transform_evaluation_reports_padstack_only_diagnostic_attribution \
  -q
```

Expected: fail with missing `natural_source_attribution`.

- [ ] **Step 3: Implement the attribution helper**

Add helper functions near the frame-transform evaluation helpers:

```python
def _frame_transform_natural_source_attribution(
    verdict: str,
    variants: list[dict],
    *,
    semantic_lever_status: Any = None,
) -> dict:
    ...
```

Classify natural-source operators with an explicit allowlist:
`frame-local-dematerialize`, `frame-direct-literal-at-final-fp-call`,
`frame-split-fp-const-lifetime`, and `frame-magic-scratch-relocation`.
Classify `frame-reservation-pad-stack` as diagnostic. Include best natural and
diagnostic variant summaries with label/operator/status/frame deltas. Pull
missing-reason context from `frame_first_divergence.verdict.reason` or
`frame_first_divergence.source_attribution.reason` when present.

- [ ] **Step 4: Attach attribution to evaluation and stop condition**

In `evaluate_frame_transform_probe_results()`, compute the attribution after
ranking variants and include it in the returned dict. If the attribution is
`diagnostic-pad-stack-only`, change the top-level verdict to
`diagnostic-pad-stack-frame-transform`. Pass the attribution into
`_frame_transform_probe_stop_condition()` and include it for PAD_STACK
diagnostic and no-safe-semantic-lever stop conditions.

- [ ] **Step 5: Verify focused tests pass**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_frame_reservations.py -q
```

Expected: all frame reservation tests pass.

- [ ] **Step 6: Smoke the CLI JSON path**

Run a bounded `debug mutate frame-transform-search --json` smoke or a
test-backed `--candidate` frame-transform evaluation and verify the JSON includes
`frame_transform_probe_evaluation.natural_source_attribution` plus the
diagnostic verdict for PAD_STACK-only results.

- [ ] **Step 7: Commit with related bug fixes**

Stage only the changed tooling tests/source plus this spec and plan:

```bash
git add tools/melee-agent/src/mwcc_debug/frame_reservations.py \
  tools/melee-agent/tests/test_frame_reservations.py \
  tools/melee-agent/src/mwcc_debug/pressure_explorer.py \
  tools/melee-agent/src/cli/debug.py \
  tools/melee-agent/tests/test_pressure_explorer.py \
  docs/superpowers/specs/2026-06-07-pad-stack-natural-source-attribution-design.md \
  docs/superpowers/plans/2026-06-07-pad-stack-natural-source-attribution.md
git commit -m "Improve frame probe source attribution"
```
