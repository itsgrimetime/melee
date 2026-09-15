# Issue #1081: Sort Whole-Function Continuation

## Problem

`source-family-continuation` could consume a raw `source_model_scored.json` artifact
from the Sort full-selection/swap run, but that artifact only contains
`score_rows`; it has no `source_model_proof` or explicit terminal handoff. The
continuation payload therefore fell back to the older protected-loss/full-selection
handoff and did not expose the next concrete
`sort-whole-function-control-data-flow-rewrite` family.

## Fix

Treat raw scored-row artifacts for advanced Sort source-model dimensions as
terminal exhaustion evidence when no row jointly preserves all protected target
assignments under an accepted structural guard. The recognizer picks the most
advanced Sort dimension present, carries the best scored row as
`next_unsupported_source_spans`, and emits the matching next source family.

The guard is intentionally conservative: if a scored row already satisfies the
protected assignments and has a retained source route, the continuation remains
actionable instead of being terminalized.

## Verification

- Added a regression for raw full-selection/swap scored rows.
- Verified the live #1081 full-selection/swap scored artifact now points to
  `sort-whole-function-control-data-flow-rewrite`.
- Verified that the continuation output feeds `source-model-synthesis` and
  generates retained whole-function candidates.
- Ran a scored smoke for two generated whole-function candidates; both produced
  retained source paths, pcdumps, target scores, structural guard evidence, and a
  terminal proof for the next helper/data-layout family.
