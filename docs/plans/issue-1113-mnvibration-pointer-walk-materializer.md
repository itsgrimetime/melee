# Issue 1113: mnvibration pointer-walk materializer

## Problem

`debug suggest control-flow-shape` can identify the `fn_802487A8`
`pointer-walk-indexed-shape` family, but `debug mutate control-flow-shape-search
--operator pointer-walk-loop` previously produced no actionable probes for the
second `mnvibration` loop. The existing pointer-walk materializer only handled a
narrow `for` loop with a single indexed expression, while this function uses a
`do { ... } while` loop with several ownership axes:

- `var_r23` as the logical controller index.
- `var_r25` as a cursor over `mnVibration_804D4FE8`.
- `temp_r31` / `gobj->user_data` as byte and typed vibration data.
- `HSD_PadCopyStatus` as either typed direct indexing or raw byte-base access.
- repeated `jobjs[23]` child-walk ownership before `mnVibration_802480B4`.

The issue is considered fixed only if the reporter workflow produces retained,
scored source candidates with useful artifacts, or a bounded terminal proof that
the relevant candidate family was exhausted.

## Design

Extend the existing `pointer-walk-loop` operator instead of adding a new CLI.
The new materializer recognizes conservative `do` loops that:

- have a single simple counter increment and bounded `<` tail condition,
- avoid preprocessor regions, labels, `goto`, `break`, and `continue`,
- have no counter side effects beyond the loop increment,
- use at least two indexed/control-flow anchors from data, cursor, pad status,
  or child-walk call ownership.

Generate a bounded family of source probes:

- typed data-field direct indexing for `x6` and `x0`,
- byte-offset data indexing,
- `mnVibration_804D4FE8[index]` and base-plus-index cursor ownership,
- typed and raw byte-base `HSD_PadCopyStatus` ownership,
- child-walk hoisting from `gobj->user_data` to the established data local.

Keep the old generic pointer-walk probes available after the new family so this
extension does not shadow existing matches.

## Artifact Contract

For control-flow and indexed-struct mutate searches, retain candidate evidence:

- `source_hunks` on generated probes and compiled variants,
- retained source paths,
- retained pcdump paths for successfully compiled variants,
- compact checkdiff evidence when source scoring runs.

This makes the result actionable for matchers and allows terminal or plateau
decisions to be based on source-level evidence rather than a bare unsupported
family name.

## Verification

Regression coverage should include:

- synthetic `mnvibration`-style typed and raw-byte shapes,
- the current `fn_802487A8` source shape with casted `do`-while tail,
- bounded probe counts,
- rejection of side-effectful counter indexes,
- rejection of conditional cursor advancement for cursor-specific probes,
- preservation of the older generic pointer-walk probes,
- CLI JSON enrichment for control-flow and indexed-struct search variants.

The reporter workflow is complete when it emits retained scored candidates for
`fn_802487A8`; a 100% match is not required for this issue if the best retained
candidate improves fresh checkdiff over the reporter baseline and includes the
artifact evidence above.
