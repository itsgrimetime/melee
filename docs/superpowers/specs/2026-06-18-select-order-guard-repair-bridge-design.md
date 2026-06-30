# Select-Order Guard Repair Bridge Design

## Context

Issues #789 and #790 are follow-ons to the select-order guard work. The
command now ranks force-phys and select-order candidates with structural guard
metadata, but agents still hit two terminal gaps:

- #789: `mnDiagram_DrawCellNumber` has rejected FPR allocator-hit candidates.
  One lane moves the desired FPRs but drifts into an inline-boundary structural
  mismatch; another keeps normalized structure but adds an 8-byte stack-frame
  delta. The current beam reports those facts but does not seed a repair lane
  from them.
- #790: `mnDiagram_SortNamesByKOs` has GPR window-order leads after node-set
  exhaustion, but the command does not summarize which source regions and
  transform families remain actionable, or when the evidence is a terminal
  allocator ceiling rather than a source-edit lead.

The user delegated decisions and requested no human input. This spec extends
the existing `debug select-order-search` command instead of creating a new
tool.

## Design

Add a bounded guard-repair lane plus a reusable post-processing layer to
select-order output with two JSON sections:

- `guard_repair_summary`: ranks rejected candidates that made allocator
  progress, groups them by structural guard rejection reason, and reports any
  repair-lane candidates generated from those seeds. It must distinguish
  `inline-boundary-toolchain-artifact` from `stack-layout` drift, preserve the
  candidate source path, before/after force-phys register facts, match percent,
  normalized diff lines, frame delta, chain, probe provenance, and ranked
  repair action.
- `source_bridge_summary`: turns window-order fallback leads, source
  attributions, generated probe counts, diagnostic buckets, and final variant
  outcomes into ranked source-region advice or a terminal allocator-ceiling
  explanation. It must report the target IGs, achieved registers, target order
  leads, guard class distribution, generated source probes, and why probes
  failed to produce a source-actionable bridge.

The guard-repair lane runs only in force-phys beam workflows unless explicitly
overridden. It is deliberately small: seed from the best rejected allocator-hit
candidates, generate the same source probes from each retained candidate source,
score them with the existing real-tree structural guard, and rank repair
children by preserving protected hits and improving the guard before considering
match percent. The lane records its own campaign directory and ledger so agents
can inspect exactly which complementary probes were tried.

The repair layer uses retained seed and repair facts to expose the next bounded
commands/actions:

- Inline-boundary drift: try complementary transform-corpus probes that restore
  call/opcode shape while preserving the allocator-hit source.
- Stack-layout drift: try frame/lifetime probes such as frame reservation
  removal or local lifetime narrowing while preserving the allocator-hit source.
- GPR order lead with attributed local: move the attributed local assignment in
  the lead direction using the existing window-order source probe generator.
- GPR order lead without a safe source probe: explain whether attribution,
  statement mobility, stack/PAD_STACK shape, indexed-byte temp shape, or
  declaration/lifetime order was the blocker.

The bridge is diagnostic and deterministic. It should not guess unsafe source
edits, should not loosen `window_order_source` implicit-temp safety rules, and
should not mark a residual as source-actionable unless the existing source
attribution and generated probe metadata support that claim.

## Success Criteria

- #789: JSON output from force-phys beam select-order search includes
  `guard_repair_summary` and guard-repair ledger data with separate
  inline-boundary and stack-layout lanes, preserving hit/miss register facts and
  concrete repair candidates/actions for retained candidate sources.
- #790: JSON output includes `source_bridge_summary` with ranked window-order
  source leads or a terminal allocator-ceiling explanation that names the
  dominant blocker class, including whether the blocker is unmaterialized
  window-order leads, indexed-byte address-temp shape, stack/PAD_STACK frame
  shape, declaration/lifetime order, or remaining wrong-register allocator
  ceiling.
- Existing select-order ranking and beam behavior are unchanged.
- Focused pytest coverage proves the new summaries are produced from synthetic
  variants and command output.
