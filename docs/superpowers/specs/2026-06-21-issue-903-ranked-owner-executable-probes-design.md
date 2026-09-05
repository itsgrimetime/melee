# Issue 903: Ranked Owner Executable Probes Design

## Context

Issue #902 made `debug select-order-search` preserve ranked local-owner and
indexed-byte source diagnostics for the retained
`mnDiagram_SortNamesByKOs` pointer-walk frontier. Issue #903 closes the next
gap: those ranked spans were still only diagnostics. The JSON reported
`listed_source_probes == 0` and `scored_window_order_source_probes == 0`, so a
matcher could not execute the suggested source continuation.

The failing source shape has two important blocker classes:

- IG34 maps to the loop-index local `i`, but `i` has no uniquely movable local
  write. The planner ranks declaration, loop header, body reads, and indexed
  expressions, then stops at `local-source-owner-no-unique-assignment`.
- IG44 maps to an implicit indexed-byte address temp rooted through a
  copy/coalesce chain. The planner ranks indexed-byte source candidates, but
  stops at `synthetic-temp-operands-unattributed`.

## Design

Extend `window_order_source.py` with a ranked-owner materialization layer. The
layer consumes the ranked candidate diagnostics from #902 and emits ordinary
`LifetimeLayoutProbe` objects with
`operator == "window-order-source-steering"` when a candidate is executable and
safe to transform.

For ranked local owners, support conservative loop-body read anchors. A probe
introduces a fresh temporary for the ranked local, assigns it immediately before
the anchor statement, and replaces one read in the anchor line. Declaration and
loop-header candidates remain diagnostic-only unless they gain a proven safe
rewrite.

For ranked indexed-byte candidates, support executable indexed-expression
anchors by introducing narrowly scoped index or value temporaries. Array
declarators such as `u32 totals[0x78];` are explicitly rejected as
`array-declarator-not-indexed-expression` so they remain useful diagnostics
without becoming bogus probes.

Every ranked materializer records byte/source span metadata, per-candidate
accept/reject reasons, materialized probe labels, source diffs, and provenance
kinds:

- `window-order-ranked-local-owner-source-probe`
- `window-order-ranked-indexed-byte-source-probe`

If ranked candidates exist but none are materializable, the bridge summary must
explain that terminal state with reason counts instead of only reporting
`window-order-leads-not-materialized`.

## Non-Goals

- Do not add a new CLI surface; keep `debug select-order-search` as the entry.
- Do not wrap the whole transform corpus inside the planner. The planner lacks
  the unit and force-phys inputs needed to do that safely.
- Do not promise that generated probes hit the requested registers. The issue
  is satisfied by executable, scored, retained probes or a hard terminal
  explanation.
