# Issue 1040: Draw post-whole source-family suppression

## Root cause

`post-source-context-next-dimension` can now prove that
`draw-post-source-context-whole-function-fpr-source-model` is exhausted and that
the only remaining family is
`draw-no-modeled-source-actionable-family-after-post-source-context-whole-function-fpr-source-model`.
The later `source-model-synthesis` pass did not treat that proof shape as
terminal when the proof arrived through retained-frontiers or allocator
aggregates. A stale `next_unsupported_source_dimension` for the same exhausted
whole-function dimension could survive proof merging, causing the same six
whole-function probes to be generated again.

## Plan

1. Teach source-model synthesis to ingest terminal frontier proofs embedded in
   retained-frontiers aggregates, recognize `exhausted_source_dimension` and
   string/list `exhausted_dimensions`, and suppress the exhausted Draw
   whole-function stage before candidate generation.
2. Emit a zero-candidate terminal proof for the exhausted post-whole Draw
   source family, preserving retained score evidence such as the
   `draw-post-source-context-whole-function-joint-data-owner-with-loop-object`
   1/3 target and 1/3 expression row.
3. Scrub stale `next_unsupported_source_dimension` fields in retained-frontiers
   and allocator metadata when they equal an exhausted source dimension, while
   retaining the final unsupported family/model and source spans.
4. Add regressions for raw discovery input, retained-frontiers aggregate input,
   CLI `source-model-synthesis --write-probes`, and direct allocator
   classification of a #1039-style discovery artifact.

## Review adjustments

Independent review requested three safeguards: exhausted dimensions must be read
from `source_model_proof` and nested synthesis objects, stale next dimensions
must be removed during proof selection/merge rather than only at generation
time, and allocator coverage must exercise raw post-source-context discovery
input. The implementation follows those constraints.

## Verification

The fix is accepted when `source-model-synthesis` returns `status: terminal` and
`candidate_count: 0` for the post-whole Draw evidence, writes no
`draw-post-source-context-whole-function-*.c` probes, and retained-frontiers plus
allocator expose the final post-whole family/model without a next dimension
equal to the exhausted whole-function source model.
