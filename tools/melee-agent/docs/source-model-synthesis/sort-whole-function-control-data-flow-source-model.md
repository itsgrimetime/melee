# Sort whole-function control/data-flow source model

Issue #1024 adds the bounded source-model-synthesis layer reached after
`sort-full-selection-swap-source-structure` exhausts for
`mnDiagram_SortNamesByKOs` / `mnDiagram_8023FC28`.

## Trigger

The family is generated only when the retained proof names the previous layer's
terminal handoff:

- `next_unsupported_source_family`:
  `sort-whole-function-control-data-flow-rewrite`
- or `next_unsupported_source_model`:
  `SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_MODEL`

Use the existing command surface:

```bash
melee-agent debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json <full-selection-terminal.json> \
  --source-file src/melee/mn/mndiagram.c \
  --source-function mnDiagram_8023FC28 \
  --write-probes build/diagnostics/sort-whole-function/probes \
  --max-per-dimension 8 \
  --no-score \
  --json
```

## Dimension

The dimension id is:

```text
sort-whole-function-control-data-flow-rewrite
```

It replaces the full `mnDiagram_8023FC28` function body, not only the
selection/swap region. Each candidate carries source hunks, source components,
score-source hints, and required assignment metadata for:

- `IG34->r27`
- `IG44->r25`

## Initial bounded candidates

The initial family is deterministic and intentionally small:

- `post-meta-sort-whole-function-source-owner-unified`
- `post-meta-sort-whole-function-selected-record-carried`
- `post-meta-sort-whole-function-selected-name-total-carried`
- `post-meta-sort-whole-function-shift-emission-indexed`
- `post-meta-sort-whole-function-prefix-insertion-rebuild`

These candidates cover declarations, initialization, source-owner flow,
selection, selected-name/total state, and swap/emission. The prefix insertion
candidate is marked high semantic risk because it changes the algorithm shape
most strongly.

## Exhaustion

If all generated whole-function candidates are scored and none jointly preserve
`IG34->r27` and `IG44->r25` with an accepted structural guard, the terminal proof
must name a non-circular next family:

```text
sort-helper-extraction-data-layout-or-cross-function-rewrite
```

This prevents the source-model proof from looping back to the family it just
exhausted.
