# Issue 898 Plan

## Steps

1. Add regression coverage for a #898-style expression score where
   `col_offset` IG32 and `row_offset` IG37 are swapped.
2. Extend the C2 blocker formatter to attach a `sticky_pool_bridge` payload
   with focus/paired anchors, focus first-def operands, source actions, and
   follow-up force/pressure/select-order targets.
3. Add product-operand source generation for the retained
   `col_offset = y_spacing * (f32) col` shape:
   materialize `(f32) col`, materialize `y_spacing`, and materialize both.
4. Ensure generated bridge targets are explicitly broader than the failed
   pair-only `[37, 32]` order proof.
5. Verify the existing `debug suggest expression-interferer-repair` JSON output
   contains the bridge and the new source candidates against the #898 reporter
   artifacts.

## Review Notes

An independent Codex planning subagent reviewed the issue evidence and found
the root cause is not simple row/column ordering. The allocator needs a bridge
from expression anchors to sticky-pool admission or upstream product operands;
the focused implementation keeps that bridge inside the existing
expression-interferer workflow.
