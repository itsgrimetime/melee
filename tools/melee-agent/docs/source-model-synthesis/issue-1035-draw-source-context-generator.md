# Issue 1035: Draw source-context generator

Issue #1034 proves that the bounded Draw alternate FPR expression family has
exhausted against retained target/expression floors. Issue #1035 consumes that
terminal-safe proof only when it explicitly names this dimension:

```text
draw-loop-body-callsite-and-object-base-lifetime-source-context
```

The #1035 lane is exclusive. It does not rerun the older coupled FPR,
alternate FPR, or expression-lifetime candidates. It emits a small, bounded
source-context family for `mnDiagram_DrawCellNumber`/`mnDiagram_80241E78`:
JObj array local ownership, parent JObj lifetime, base snapshot locals, loop
digit JObj ownership, loop translate locals, and one combined lower-hill
backtracking probe.

Generated candidates are function-local retained C probes. Each candidate
carries `source_hunks`, `source_components`, a score-source command hint, the
Draw FPR target map, baseline target/expression floors, required source
patterns, and validation metadata requiring target, expression, and structural
guard scoring. The first implementation supports both the legacy `y_offset`
offset block and the retained split `row_offset`/`rowf` block.

Scoring is floor-gated like the alternate lane: a source-context candidate is
actionable only when it beats the retained Draw target or expression floor. If
all scored source-context probes stay at or below the floor and no nonterminal
score error occurs, the output is a new #1035 terminal proof with retained
source-context evidence, not the old #1034 placeholder.

The #1035 terminal proof records the new terminal reason, the final
source-context family/model, retained scored probes, candidate scores,
source hunks by candidate, and attempted dimensions for both
`draw-alternate-fpr-expression-structure` and
`draw-loop-body-callsite-and-object-base-lifetime-source-context`. This gives
retained-frontiers and allocator-ceiling enough evidence to render that the
bounded source-context layer has been attempted and exhausted.
