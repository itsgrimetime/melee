# Issue 1034: Draw post-alternate terminal replay

Issues #1032 and #1033 covered the bounded Draw alternate FPR expression
graph family. That family models local `col_offset`, `row_offset`, and digit
call-argument expression structure variants and records retained score
evidence when those probes do not improve the post-ceiling floor.

Issue #1034 makes the post-alternate no-modeled-source result replayable from
retained allocator/frontier artifacts. A follow-up
`debug search source-model-synthesis` invocation should not report an empty
`generated` result after the alternate terminal sentinel. It should emit a
terminal source-model proof when the retained artifact carries real alternate
score rows.

The replay is evidence-gated. The terminal proof requires the final alternate
next model/family sentinel, the `draw-alternate-fpr-expression-structure`
dimension, retained scored probes with `source_retained`, `pcdump_path`,
`target_score`, `expression_score`, and `source_hunks`, plus either the
alternate no-floor terminal blocker or retained rows that stay at or below the
Draw post-ceiling floor. Sentinel text alone is not enough.

The next unsupported dimension is broader Draw source context, not another
local expression-graph retry. Future source generation would need to model
object/base lifetime and access order before the loop, loop-body interaction
between digit animation and translate calls, or coherent source-shape
backtracking away from the retained lower-hill baseline.

Issue #1035 adds that bounded source-context generator and its retained
frontier/allocator handoff contract; see
`issue-1035-draw-source-context-generator.md`.

The replay also preserves candidate-cap evidence. The real handoff scored six
retained probes from an eight-spec modeled alternate family, so replay payloads
record available, generated, scored, and unscored alternate candidate IDs
instead of implying the replay command rescored every modeled alternate spec.
