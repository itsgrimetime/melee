# Fix 1036: Post-Source-Context Next Dimension

Issue #1036 adds an explicit handoff after the Draw post-alternate
source-context family reaches the #1035 terminal sentinel:

`draw-no-modeled-source-actionable-family-after-loop-body-callsite-and-object-base-lifetime-source-context`

The default workflow is intentionally explicit:

1. Run `melee-agent debug search post-source-context-next-dimension` with the
   terminal source-model, retained-frontiers, allocator-ceiling, and optional
   continuation JSON artifacts.
2. Pass the produced discovery JSON to
   `melee-agent debug search retained-frontiers --artifact ...`.
3. Pass that retained-frontiers JSON to
   `melee-agent debug solve allocator-ceiling --evidence ...`.

The discovery artifact is diagnostic and source-actionable. It does not
silently generate a broader C probe family from the filesystem. If retained
evidence genuinely exceeds the current Draw floor, the artifact emits
`ranked_retained_c_probes` and a retained-frontier actionable lane. Otherwise
it emits the concrete unsupported dimension
`draw-post-source-context-whole-function-fpr-source-model` with source spans,
retained evidence, representative pcdump paths, target/expression scores,
structural guard evidence, and command handoff hints.

Expression renumbering is normalized before ranking. Rows carry
`real_expression_matched`, `expression_floor_progress_real`, and
`expression_renumbering_only`; actionable decisions use the real expression
count, so renumbered-only FPR expression hits do not cross the Draw floor.

When both the old #1035 source-context terminal proof and the new discovery
proof are supplied to retained-frontiers, the new post-source-context proof has
the higher Draw stage rank and is propagated into allocator-ceiling output.
