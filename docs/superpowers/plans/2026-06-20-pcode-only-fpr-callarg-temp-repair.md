# Pcode-Only FPR Call-Arg Temp Repair Implementation Plan

> **For agentic workers:** Use subagent-driven review for implementation
> validation. The requested `superpowers:brainstorming` file was unavailable in
> this checkout, so this plan records the completed fallback design and review
> path for issue #874.

**Goal:** Add a reusable repair lane for `mnDiagram_DrawCellNumber` when an FPR
call-argument temp exists only in pcode and is copied into physical `f1`.

**Architecture:** Extend FPR copy tracing in `mwcc_debug.copy_trace`, add a
transform-corpus family for source-level call-argument temp shapes, and wire the
family into plan-transform validation and terminal-blocker summaries.

## Tasks

- [x] Claim issue #874 before investigating.
- [x] Audit existing capabilities for a pcode-only FPR call-argument repair lane.
- [x] Add regression tests for FPR `trace-copy --class fpr` and FPR copy
  discovery.
- [x] Extend trace-copy internals to detect and render same-class FPR `fmr`
  copies without changing default GPR behavior.
- [x] Add transform-corpus tests for existing-local and inline-cast
  `HSD_JObjReqAnimAll` call-argument shapes.
- [x] Implement `steer_pcode_only_fpr_callarg_temp` and the
  `pcode_only_fpr_callarg_temp_repair` family.
- [x] Wire the family into mndiagram FPR select-order search before generic
  coupled/coloring families.
- [x] Add validation summary terminal blockers for exhausted pcode-only FPR
  call-argument temp repair.
- [x] Smoke the real `mnDiagram_DrawCellNumber` retained partial to confirm the
  family emits ranked probes and `trace-copy --class fpr` finds `fmr f1,f34`.
- [ ] Run final focused tests, install refresh, issue resolution, and matcher
  handoff.
