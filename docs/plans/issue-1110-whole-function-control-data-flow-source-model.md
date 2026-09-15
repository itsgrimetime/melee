# Issue 1110: Sort Whole-Function Control/Data-Flow Source Model

## Root Cause

The `sort-whole-function-control-data-flow-rewrite` family was reached by
continuation metadata, but candidate generation stopped before patching. The
readiness gate only accepted canonical indexed Sort source (`i < 0x78` and
`dst[i] = temp`) while the reporter retained source uses a pointer-carried outer
loop and emits through `*ll_probe_iter_0 = temp`.

## Design

Keep the existing five whole-function body templates. Broaden only the readiness
predicate so it accepts the retained source shape when all semantic Sort regions
are present:

- Sort public or decompiled function signature.
- Initialization loop over `0x78` that writes sorted-name bytes and KO totals.
- Selection/comparison loop with `j = i + 1`, `GetNameText`, and `totals`.
- Shift/emission into the prefix.

For retained pointer loops, the final emission must write through the same outer
iterator advanced by the accepted loop. An arbitrary `*ptr = temp` write is not
enough.

Because the emitted probes are full translation-unit source files, whole-function
candidate metadata also needs `requires_full_unit_source` and structural guard
scoring enabled. Otherwise the scorer treats the probe as a fragment and fails
while stitching it into `mndiagram.c`.

## Tests

Add retained-source whole-function generation coverage using the existing
`_sort_retained_pointer_seed_source()` fixture, plus negatives for missing init
write and unrelated pointer emission. Keep canonical whole-function blocker and
exhaustion tests passing.

## Smoke Checks

Run the focused pytest set for whole-function synthesis, the adjacent retained
full-selection tests, and the reporter `source-model-synthesis` no-score/scored
commands. The no-score path should emit five whole-function candidates instead
of the `sort-whole-function-control-data-flow-source-model-not-materialized`
blocker; the scored path should either find an actionable candidate or
terminalize the populated family and name the next unsupported family.
