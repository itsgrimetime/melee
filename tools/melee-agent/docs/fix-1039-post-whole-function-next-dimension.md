# Issue 1039: Draw Post-Whole-Function Discovery

## Root Cause

`post-source-context-next-dimension` only modeled the first Draw
post-source-context handoff. After the whole-function FPR source-model family
was exhausted, the discovery logic still found the earlier loop-body
source-context terminal family in nested retained-frontier artifacts and
re-emitted the already exhausted whole-function dimension.

## Design

The discovery now treats the whole-function stage as a distinct terminal stage
only when the artifacts include final whole-function family/class evidence plus
actual whole-function exhausted or scored rows. That avoids switching stages on a
stale `next_unsupported_source_dimension` string alone.

When the whole-function stage has no floor-improving retained row, the command
returns `unsupported-source-family` with the exhausted whole-function dimension,
the final unsupported source family/model, and the unsupported expression class.
Retained-frontier triage and allocator-ceiling accept that terminal family
without inventing another next dimension.
