# Formatter Writer Copy Authority Design

## Scope

This amendment closes the exact-retail `0x443a10` call-slot failure without
weakening generic private-stack alias or residue checks.  The failure occurs
before residue propagation: the formatter engine has already proved that a
private-buffer source/count pair is bounded, but that proof is not retained
when the selected callback enters its bounded writer and calls `memcpy`.

The change is confined to the query-local private-stack proof in
`tools/mwcc_retro/x86_cfg.py` and its tests.  It adds no retail-address
allowlist, persistent semantic cache, Task 4–8 arena authority, or general
unknown-length memcpy exemption.

## Diagnosed Boundary

The exact failing edge is the recognized callback writer's unique direct
copy.  On retail it is the call at `0x403acd` from the bounded writer at
`0x403aa0` to the exact memcpy body at `0x404c30`.

The existing proof facts establish complementary halves of the obligation:

- `_audited_format_buffer_end_count` proves at one exact formatter-engine
  callback edge that every private-buffer source/count path remains in the
  formatter cursor window.
- `_audited_format_writer_callback` proves the selected writer forwards the
  source and copies `min(incoming_count, remaining_destination)`.
- `memcpy_alias_continuation` proves the exact memcpy body and rejects an
  unbounded stack-alias source.

The current `_FormatCallbackAuthority` only partitions an engine's indirect
callback targets.  Its owner invariant is engine-local, so it is deliberately
discarded when analysis descends into the selected writer.  The writer then
has neither a finite generic length nor a stream `_FormatBufferEnvelope`, and
the memcpy continuation correctly fails closed.

## Considered Approaches

### 1. Extend the generic unsigned interval evaluator

This would teach a broadly used evaluator to correlate the writer's two
branches and infer the selected length.  It is rejected because it expands a
large proof surface, still does not connect that length to the engine-side
private source, and risks authorizing unrelated min-like copies.

### 2. Reuse `_FormatBufferEnvelope`

This is rejected because that token models a stream wrapper/writer
publication epoch.  The bounded formatter callback is a different protocol:
its writer directly calls memcpy and has no stream publication/restoration
addresses.  Forging dummy envelope fields would confuse lifetime and
currentness checks.

### 3. Add a per-invocation writer-copy authority

This is the selected design.  It records only the missing bridge between the
already audited engine edge and the already audited writer body.  It is
immutable, query-local, context-keyed, source-bound, and consumed at one exact
copy site.

## Authority Schema and Issuance

Add a frozen, slotted `_FormatWriterCopyAuthority` with:

- `engine`: the audited formatter engine owner;
- `callback_call`: the exact indirect callback invocation;
- `writer`: the selected exact bounded writer;
- `source_aliases`: the exact source aliases after mapping into the writer;
- `length_upper`: a conservative positive upper bound.

The authority is issued only while mapping an engine callback to a target,
and only when all of the following hold:

1. the current `_FormatCallbackAuthority` belongs to that engine and admits
   the selected target;
2. the target satisfies `_audited_format_writer_callback`;
3. one uniquely derived `_AuditedFormatCursorProtocol` describes the engine;
4. `_audited_format_buffer_end_count` succeeds for this exact callback call
   and its exact engine-side source aliases;
5. alias mapping into the writer is exact and produces a nonempty finite
   source-alias tuple; and
6. `length_upper` is exactly `protocol.cursor_extent + 1`, with checked
   non-wrapping range.

The engine-side and writer-side source tuples need not be textually equal:
the existing exact caller-to-callee mapper may rebase the same physical bytes
into the writer's stack coordinate system. The issuer validates the
engine-side tuple with the source/count proof, requires a nonempty canonical
writer-side tuple produced by that exact mapping, and stores the writer-side
tuple consumed at memcpy.

The cursor upper bound is intentionally conservative.  The engine-side
source/count proof establishes the correlation; the writer clamp can only
reduce the requested count.  A loose upper bound may conservatively reject a
nearby spill, but cannot authorize an unproven read.

The outer call-slot query may cache the stronger universal
`_audited_format_buffer_end_count(..., source_value=None)` result by exact
`(engine, callback_call, protocol)`. Before reusing that result, issuance must
still require every current engine-side source alias to lie inside the exact
protocol source window. This cache is query-local and cannot outlive the
current recovery or source tree.

Protocol discovery must be address-independent and fail closed: enumerate
the engine's exact callback-target union and closed incoming domain, identify
the sole non-writer wrapper with finite synchronous stream callback targets,
and require exactly one `_audited_format_cursor_protocol` result.  Ambiguity,
missing ownership, unresolved flow, or analysis limits produce no authority.

## Propagation and Consumption

The new authority participates in alias-context identity so a joined context
cannot borrow it from a different invocation.  It is deliberately not stored
in subscriber effects: those retain the caller's engine-level callback-target
authority, so return mapping restores the caller context while the writer-copy
authority dies with the writer invocation.  It is valid only for its `writer`
owner.

At the writer's unique exact memcpy call, `memcpy_alias_continuation` may use
the authority only when:

- owner, direct target, and copy call agree with the exact writer audit;
- the call's source alias equals `source_aliases` exactly;
- destination and scalar length-slot alias checks still pass; and
- the existing tracked-spill overlap check passes using `length_upper`.

All existing exact-memcpy, stack-coordinate, raw-CFG, argument-order,
destination, and escape-demand checks remain in force.  The continuation then
applies the same ABI register result as the existing exact memcpy path.

The residue fixed point may summarize that same exact memcpy call instead of
descending into its internal alignment branches only when the writer-copy
authority and exact alias continuation both validate.  It maps each certified
source coordinate against the current writer SP, requires the complete
half-open source window `[source, source + length_upper)` to be disjoint from
every live byte and dense tail in the current `_PrivateStackResidueFact`, and
enqueues the writer continuation with the residue fact unchanged.  A basis
ambiguity, exact-row overlap, or tail overlap rejects.  This is not a generic
memcpy or `rep movs` summary, and it does not relax TOP alias observation.

The authority remains in the writer context only through its unique exact
copy so the unchanged caller-owned source-argument word can be returned to
the audited subscriber.  It is consumed when the writer returns and is never
stored in the subscriber effect.  A later direct call with identical bytes
and arguments therefore cannot reuse it.  Generic calls, other memcpy bodies,
other writer instances, and contexts without the exact authority continue to
reject.

## Fail-Closed Behavior

The query returns no proof on any authority ambiguity, malformed schema,
source mismatch, wrong callback target, writer mutation, callback-count
mutation, tracked-spill overlap, nonunique protocol, cap exhaustion, or raw
control-flow discrepancy.  No new global memo is introduced; all authority
and protocol caches are local to one outer query.

## Verification Design

Tests must first fail on unchanged production and then pass after the minimal
implementation.  The strict matrix contains:

1. a positive joined private-buffer source/count path through an admitted
   engine callback into the exact bounded writer and exact memcpy;
2. an engine `sub count, source` to `add` mutation;
3. a writer clamp-operand mutation;
4. a writer copy-count mutation;
5. a writer copy-source mutation;
6. an excluded or unknown callback target;
7. a later direct invocation of the same writer proving the authority does
   not leak past return; and
8. an overlapping tracked private spill proving the conservative upper bound
   still rejects; and
9. a complete alias/residue-flow fixture proving exact engine-to-writer
   context plumbing, source-window disjointness, unchanged residue
   continuation, and post-return authority death.

Each hostile asserts nonvacuous recovery, exact call ownership/targets, and
the intended one-fact mutation before asserting rejection.  Focused tests are
followed by the formatter/private-stack partitions, full x86 module, static
checks, an independent review, and finally the exact retail call-slot replay.
