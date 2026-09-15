# Issue 1037: Draw Whole-Function FPR Source Model

`debug search source-model-synthesis` now supports the
`draw-post-source-context-whole-function-fpr-source-model` handoff emitted after
Draw loop-body callsite/object-base lifetime source-context exhaustion.

The stage is exclusive: when allocator or retained-frontier evidence explicitly
reports `next_unsupported_source_dimension` for this handoff, synthesis emits
only bounded whole-function probes for the new dimension. The probes compose
preloop data/jobjs/base ownership with loop joint-data, digit-object, animation,
translate, and add-child ownership changes.

Terminal classification treats expression progress as real only when it is not
a renumbering-only virtual-id hit. Target floor progress remains actionable.
When all whole-function probes are scored without target or real-expression
floor progress, the terminal proof advances to
`draw-no-modeled-source-actionable-family-after-post-source-context-whole-function-fpr-source-model`.
