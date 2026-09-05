# Issue 1129: u8 Index-Table Pointer-Walk Probes

`pointer-walk-loop/pointer-walk-indexed-shape` source materialization now has a
generic `u8*` index-table path in addition to the existing mnVibration/member
array path.

The generic scanner is bounded to the target function plus same-file
`static inline` helpers called directly by that target. It recognizes simple
byte-table source shapes such as:

- `sorted[cur + 0x1C]`
- `*(sorted + cur + 0x1C)`
- `p = sorted; p += idx; return p[0x1C];`
- `ptr = sorted + cur; ptr = ptr + 0x1C;`

Safety gates keep the probes conservative:

- the table base must be declared as `u8*` or `unsigned char*`;
- the byte offset must be a decimal or hex integer constant;
- index expressions may only use identifiers, integer casts, constants,
  parentheses, `+`, and `-`;
- side effects, calls, nested subscripts, writes, dereferences, comma
  expressions, and conditional expressions are rejected.

Generated probes retain the existing family id and use
`pointer-walk-index-table-*` labels. Provenance records the owner function,
owner kind, base, pointer local, index expression, byte offset, source lines,
and `anchors: ["u8-index-table"]`.

When a baseline checkdiff is supplied to
`debug mutate control-flow-shape-search` and all generated candidates score at
or below that baseline, the JSON includes a terminal proof with
`terminal_blocker: "control-flow-shape-candidates-exhausted"`. The proof
retains candidate counts, baseline data, best-candidate source hunks, retained
source and pcdump paths, checkdiff delta, per-candidate summaries, and a
source-level next handoff. Candidate summaries include the owner function and
anchor kind, so helper-return probes such as `u8* sorted` + `0x1C` are visible
even when target-function anchors are generated first.
