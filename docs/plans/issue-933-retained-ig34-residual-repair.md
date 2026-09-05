# Issue 933: Retained IG34 Residual Repair

## Root Cause

Issue #933 was filed after the #932 retained Case-C simplify-order pass found a
lower-drift frontier for `mnDiagram_SortNamesByKOs`: IG44 improved to the
retained r26 state, but the target map still needed final IG34 r27 and IG44
r25. The existing plan-transform path only modeled the earlier IG44 simplify
order objective, so it could not materialize probes from the retained
`case_c_max_idx_probe` source shape, classify residual IG34 progress, or teach
allocator-ceiling evidence that this lower-drift residual family had been
exhausted.

## Implemented Design

Extend `retained_gpr_case_c_simplify_order_continuation` with an explicit
lower-drift residual goal consumed from
`retained_case_c_lower_drift_residual` in `--select-order-json`.

The residual path:

- requires the retained `case_c_max_idx_probe` source shape before emitting
  probes
- protects the lower-drift IG44 r26 state while attempting IG34 r27 and
  ranking against the final force-phys target
- emits bounded variants around probe declaration placement, block scope,
  reload placement, alias preservation, and `dst_iter` lifetime anchoring
- carries baseline score and first-divergence metadata into validation
  summaries
- distinguishes exact hits, residual hits, lower-drift frontiers, lost
  lower-drift progress, protected negatives, and unscoreable probes

Allocator-ceiling evidence now recognizes both retained simplify-order and
lower-drift residual plan-transform exhaustion summaries, including retained
source identity from best candidates.

## Verification Plan

Focused tests cover:

- transform-corpus materialization and blocked diagnostics for the retained
  residual source shape
- CLI JSON output and ranking for lower-drift residual validation
- baseline score parsing for real `score.json` payloads
- allocator-ceiling recognition of plan-transform residual exhaustion

Command-level smoke checks should run `plan-transforms` against the retained
#933 source, write bounded residual probes, and run the same path with a
synthetic validation command before handing the matcher back to remote scoring.
