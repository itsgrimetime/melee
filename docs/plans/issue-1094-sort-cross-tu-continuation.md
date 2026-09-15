# Issue 1094: Sort Cross-TU Continuation Handoff

## Problem

`source-model-synthesis --continue-after-final-source-family` correctly receives
an unbounded-TU terminal Sort artifact whose active
`next_unsupported_source_family` is
`sort-cross-tu-symbol-linkage-or-data-section-ownership-source-context`, but the
candidate generator does not treat that family as an active stage. It falls
through to the base Sort generators and re-emits exhausted lower families such as
`sort-init-indexed-write`, `sort-indexed-byte-cache`, and natural rewrites.

## Fix

Add an explicit active-stage gate for the cross-TU/data-section ownership
handoff. When no modeled cross-TU candidate generator exists for that active
family, emit a zero-candidate terminal proof using the existing final family
`sort-no-modeled-source-actionable-family-after-cross-tu-linkage` instead of
falling back to lower source families.

## Regression Coverage

Add tests that build the unbounded-TU terminal handoff, then verify both direct
generation and the CLI path with `--continue-after-final-source-family --no-score`
produce a terminal zero-candidate payload with the cross-TU final family and no
old Sort candidate dimensions.
