# Issue 1122: Copy/Coalesce Source Field-Load Probes

## Problem

`mnDiagram3_8024714C` select-order evidence attributed IG66 to a real source
expression, `gobj->user_data`, but the window-order source planner only routed
literal `field-load` attributions into the field-load materializer. The
source-visible `copy/coalesce-source` attribution therefore fell through to
`unsupported-source-attribution-kind`, producing no retained source probes for
the reporter workflow.

## Approach

Treat field-like `copy/coalesce-source` attributions as source-visible
field-load owner spans, while preserving the original copy/coalesce provenance
in diagnostics and emitted probe payloads. The existing bounded field-load
candidate resolver/materializer remains the source of generated C probes.

Retained summaries also carry `source_hunks`, the source-probe provenance kind,
and the field-load candidate payload so terminal proof can point at the exact
source-level handoff.

## Verification

Regression tests cover both materialized `copy/coalesce-source` field probes
and the negative unresolved-base case. The original #1122 artifact workflow now
materializes retained full-function C probes for `gobj->user_data`; scoring
exhausts the bounded family without moving IG66 to r30 and records retained
source, pcdumps, target scores, source hunks, and the next source-level handoff.
