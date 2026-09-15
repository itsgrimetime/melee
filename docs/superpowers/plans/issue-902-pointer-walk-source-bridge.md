# Issue 902: Pointer-Walk Source Bridge

## Goal

Make `melee-agent debug select-order-search` produce source-actionable output for
the `mnDiagram_SortNamesByKOs` retained pointer-walk frontier when the remaining
terminal blockers are `local-source-owner-no-unique-assignment` and
`synthetic-temp-operands-unattributed`.

## Root Cause

The structural search had already found retained pointer-walk candidates, but
the source bridge stopped at abstract terminal blockers. It did not rank source
owner spans for non-FPR loop locals such as `i`, and it did not explain
implicit indexed-byte address temps through copy/coalesce operands. The terminal
lane also omitted retained probe pcdump paths and force-phys score summaries,
which left matcher agents without a concrete next probe to score or inspect.

## Implementation Plan

1. Extend window-order source diagnostics to report ranked local owner spans for
   GPR loop locals, including declaration, loop header, loop body reads, and
   indexed-byte expressions.
2. Extend implicit add/addi diagnostics with a bounded copy chain and ranked
   indexed-byte source candidates when operands are copy/coalesce products.
3. Extend select-order terminal bridge reporting with a `source_bridge_lane`
   that ranks retained source probes, preserves `pcdump_path`, includes
   IG34/IG44 force-phys score evidence, links terminal blockers, and emits
   follow-up score commands.
4. Keep existing recombine and frame-repair lanes intact so current workflows
   still see their previous next actions.
5. Cover the planner diagnostics and terminal bridge JSON with focused
   regression tests, then smoke the real #902 artifacts.

## Verification Targets

- Focused planner tests for ranked GPR local owner candidates and synthetic-temp
  indexed-byte diagnostics.
- Focused select-order bridge tests for ranked source probes, pcdump retention,
  and support-order-satisfied output.
- Real artifact smokes for `r34<r41` and `r42<r34` with
  `mnDiagram_SortNamesByKOs`, confirming ranked probes include retained source,
  pcdump path, target score, registers, linked blockers, and source provenance.
