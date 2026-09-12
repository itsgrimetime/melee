# Symbolic Local And Complement Diagnostics Design

## Context

Issues #802 and #803 are follow-ups to the frame and inline attribution work in
commit `8cc7e82b8`. Both reports show that the diagnostic tools now expose the
right broad lane, but still lose key state needed to make the lane actionable.

#802 is a frame-reservation bug. `mnDiagram_SortNamesByKOs` has current pcode
such as `addi r25,r1,totals` and later indexed accesses through the derived
registers. The frame tool recognizes expected `totals[0x78]`, but because it
only resolves symbolic memory operands like `totals(r1)`, it reports the
current 480-byte range as unused/outgoing floor and incorrectly recommends a
local-area repair.

#803 is a select-order feature gap. A downhill retained candidate for
`mnDiagram_DrawCellNumber` preserves several hard FPR assignments while failing
the structural guard as an inline-boundary artifact. Follow-up guard repair
probes can be scored, but the output does not clearly state whether those
probes preserve the candidate's achieved FPR state while repairing shape, or
whether the candidate is a terminal source/allocator ceiling.

## Approach

The implementation will extend existing reports rather than add new commands.

For frame reservations, the parser will recognize symbolic stack address
materialization in pcode: `addi rX,r1,<symbol>`. If the symbol can be mapped to
a concrete offset from current or expected asm, the analyzer will emit an
address-taken trace for that offset with `symbolic_home`, `original_operands`,
and `resolved_operands`. The destination register becomes a symbolic base for
later direct or indexed accesses such as `0(r25)` and `(r30,r0)`, so the
address-taken stack object can report the current uses that prove the local is
live. Address-taken stack objects will carry `source_symbols` the same way
direct symbolic memory accesses do. When current and expected both materialize
the same range, the false oversized outgoing floor disappears instead of
producing a local-area repair recommendation.

For select-order guard repair, the summary will add a
`downhill_complement` section. It will compare each repair candidate against the
seed's protected FPR hits, classify whether the candidate preserves all, some,
or none of those hits, and identify whether any candidate both repairs the
guard and preserves protected hits. If no candidate does, the output will report
a terminal complement ceiling with the best preserving and best structural
attempts, plus the localized inline-boundary drift evidence already produced by
#800.

## Data Flow

Frame reservation analysis already receives final pcode and optional current
and expected asm. The new symbolic-address parser stays inside
`tools/melee-agent/src/mwcc_debug/frame_reservations/__init__.py`, beside the
existing symbolic stack-home resolution. It feeds existing address-taken range
construction and stack-object attribution so downstream report code does not
need a second model.

Select-order guard repair already stores seed protected hits in the guard
repair ledger and includes repair variants in the summary. The new complement
summary derives from those existing variants and ledger seeds. It does not
change candidate generation or scoring semantics; it changes how the result is
explained and ranked for the user.

## Error Handling

Symbolic address operands that cannot be resolved stay in
`unresolved_symbolic_homes` with an `address_materialization` marker;
unresolved symbols must not create synthetic stack objects. If a symbol
resolves inconsistently, the existing resolver drops it.

Complement reporting is best-effort. If a ledger or seed hit map is absent, the
section reports `status: unavailable` and leaves the existing guard-repair
summary unchanged.

## Testing

Add a frame regression where final pcode contains `addi r25,r1,totals`, a store
through the derived register, and an indexed load through another derived base
register while expected/current asm maps `totals` to the same range. The test
must fail before implementation by showing that the address-taken object is
missing, derived current uses are not attributed, or a false local-area
divergence remains. Add a negative test where unresolved symbolic address
materialization is recorded but does not synthesize a stack object.

Add select-order unit coverage for guard-repair summaries with a protected-hit
seed and two follow-up variants: one that preserves hits but remains
structurally rejected, and one that repairs structure while losing hits. The
test must assert that the new complement section reports a terminal ceiling and
shows the trade-off explicitly: a structural candidate repaired shape but lost
the protected hits, while a preserving candidate kept the hits but did not
repair shape.

Run the existing focused frame-reservation and select-order test files, plus
CLI help smokes for the changed commands.
