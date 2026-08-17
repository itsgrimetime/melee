# Private-Heap Bounded-Interior Design

**Date:** 2026-08-06
**Issue:** Melee tooling #1240
**Parent:** `2026-08-06-allocator-session-capability-seal-design.md`

## Decision

The returning-publication address audit may accept a private-heap dereference
only through a typed bounded-interior fact. The existing `"private-heap"`
tag is not sufficient: it records that a call returned from a certified heap,
but loses the allocation identity, requested extent, factory layout, and
relationship between a later helper argument and that allocation.

The new fact binds one exact factory call, the allocator root and factory
entry, the canonical extent token, factory header/return offsets, the pointer
position (`base` or a proven end-relative expression), and a no-wrap lower
bound. It is produced only after a complete direct incoming-call closure proves
the page-provider/helper forwarding chain. A body may write or dereference a
span only when its symbolic interval is wholly inside the factory's usable
extent. Every unrecognized affine form, index/scale, missing guard, alternate
incoming caller, stale dependency, or extra span bottoms the proof.

## Retail Boundary

The motivating recovered chain is page provider `0x4042a0`, factory
`0x406480`, and helper `0x403dd0`. The provider normalizes its requested
extent to at least `0x10000`, calls the exact factory, and forwards the same
extent and returned payload pointer to the helper. The helper makes interior
writes including `payload + extent - 8`; the proof must establish that this is
the same guarded extent, not merely a private-heap pointer plus a finite value.
These addresses are integration evidence only, never production rules.

## Proof Rules

1. The factory is the one recorded in a protected-slot-disjoint
   `_PrivateHeapAllocatorContract`; its `_PrivateRegionFactoryShape` supplies
   `allocation_call`, `size_argument`, `header_size`, and `return_offsets`.
2. A page-provider role proves a canonical extent from its incoming argument,
   including a checked minimum/no-wrap normalization, exact forwarding to the
   factory, and exact forwarding of the factory result plus the same extent to
   a helper call.
3. A helper role is admitted only if its full direct incoming-call inventory is
   complete and every caller is a proved page-provider role with that same
   factory/extent contract. Indirect or unresolved incoming control rejects.
4. Inside the helper, a pointer expression is accepted only when it reduces to
   one of the recorded payload-base or end-relative forms, with no scale and
   with a nonnegative, nonwrapping interval contained in the usable extent.
   Reads that establish a later derived bound require their own bounded source
   span and exact transformation witness.
5. The role's call and memory side effects are closed separately. Until that
   closure is complete, the new fact remains unavailable rather than granting
   a broad private-heap exception.
6. The serialized witness includes all provider/helper/factory instructions,
   incoming edges, contract dependencies, and exact permitted spans; dependency
   replay must reject a changed instruction, edge, factory shape, or state.

The selected effect closure is context-sensitive.  It symbolically executes
only exact affine payload/extent values, aligned low-bit metadata tags, and
known initializer memory cells.  Every real memory access must reduce to a
recorded base- or end-relative span; every direct call must have exact pushed
arguments and remain inside the allocator dependency closure.  A callee write
to the root metadata cell rejects even if it happens to store the same value.
Branches may be pruned only from an exact comparison.  The certificate stores
that comparison, selected and excluded successors, executed instruction
inventory, and pruned call sites; each pruned call must be reachable only from
an excluded successor.  Executed calls are independently reconciled against
decoded and raw direct-call facts, while the complete allocator dependency
function/fingerprint inventory is replayed before interpretation.  This
matters for retail's empty-list initialization: the freshly written zero
sentinel makes the two general nonempty-list helper calls unreachable in this
exact call context without claiming they are unreachable for arbitrary
allocator states or unrelated callers.

## Non-Goals

- Do not permit arbitrary `private-heap + finite` arithmetic.
- Do not add an address allowlist or weaken the publication-slot disjointness
  rules.
- Do not infer capacity from allocation type, a raw `0x10000` constant, or a
  helper name.
- Do not run a retail replay merely to develop this local proof layer.

## Verification

Focused fixtures must accept the exact typed base path and reject a mismatched
factory/helper extent, EBX redefinition, unrelated pointer, missing minimum
guard, undersized request, changed affine form or scale, extra out-of-range
write, incomplete helper incoming closure, and stale dependency replay. Then
run the focused x86-CFG tests, `py_compile`, Ruff, and `git diff --check`.
