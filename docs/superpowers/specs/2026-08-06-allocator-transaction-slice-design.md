# Allocator Transaction Slice Design

> **Superseded 2026-08-06:** Exact retail graph measurements showed that a
> bidirectional call-graph slice is not a bounded proof boundary. Cycles make
> 970 functions target-reachable even after context-restoring terminals are
> cut, while choosing only shortest paths would omit valid executions. The
> replacement is `2026-08-06-allocator-session-capability-seal-design.md`.
> This document is retained as rejected-design evidence; its implementation
> must not be promoted as the Task 4 closure.

**Date:** 2026-08-06

**Issue:** Melee tooling #1240

**Parent design:** `2026-08-02-return-path-publication-noninterference-design.md`

## Problem

The return-path publication proof must show that one checked backend session
makes the owned bump allocator total while the callback, cursor, remaining
capacity, and return-storage slots remain stable.

The current implementation uses the complete transitive call closure of the
backend and lifecycle roots as the semantic-write scope. On retail GC/1.2.5n,
the backend root at `0x4908f0` reaches 2,333 owned functions, 32 Windows import
identities, and 79 unresolved indirect calls. The first newly exposed import is
`0x412941 -> GlobalReAlloc`, reached through:

```text
0x4908f0 -> 0x490a40 -> 0x445780 -> 0x446bc0 -> 0x492070
           -> 0x495210 -> 0x443170 -> 0x413ad0 -> 0x412930
```

That buffer-reallocation branch is not on a path to the exact allocator call
whose totality is being proved. Expanding it turns a bounded transaction proof
into a whole-compiler proof. Adding `GlobalReAlloc` or arbitrary imports to a
pure allowlist would hide the symptom and weaken the trust boundary.

## Requirements

The repair must:

1. Preserve the existing full direct-closure test that one backend root contains
   the lifecycle consumer, allocation caller, and every incoming owner.
2. Audit every instruction and call that can participate in an execution from
   the selected backend entry to an exact call of the proved allocator.
3. Include branch alternatives that reconverge before the allocator call.
4. Include the complete effects of side calls executed on a retained path.
5. Fail closed on unresolved control, unknown imports, unsafe writes, stack
   pivots, direction-flag ambiguity, or an unproved deferred callback inside the
   retained transaction.
6. Exclude a branch only when exact CFG reachability proves that it cannot reach
   any transaction goal.
7. Bind the slice, all semantic summaries, and every dependency to the totality
   certificate and its memo entry.
8. Leave publication's exact five-import boundary and expected retail returning
   closure unchanged.

## Considered Approaches

### Complete backend closure

This is conservative but requires proving most of the compiler runtime and all
of its dynamic dispatch. The retail measurement shows that it is not a bounded
way to close #1240.

### Certified allocator leaves only

The private-heap and finalized-handle contracts can safely summarize calls that
they certify under the same protected-slot set. They cannot remove the
independent `0x443170 -> GlobalReAlloc` path, so they are an optimization inside
the solution rather than the primary boundary.

### Exact interprocedural transaction slice

This was the selected approach in this historical design. The full closure
would have continued to establish backend identity and caller membership. A
separate bidirectional CFG/callgraph slice would have defined the
semantic-write transaction, excluding unrelated branches by proof of
non-reachability rather than by trusting their effects.

## Historical Disposition

Retail graph hydration invalidated the proposed boundary before it could become
accepted Task 4 proof evidence. The sound target-reachable set remains large
because of recursive call-graph cycles; the much smaller shortest-path set is
not complete over valid executions. Accordingly, transaction-specific records,
construction, memo payloads, and tests are historical scaffolding and should be
removed or migrated once they have no live production consumer.

That removal is proof-preserving rather than a relaxation. The rejected slice
does not supply a positive allocator-totality fact. The replacement design
keeps the already validated full-closure identity/caller inventory,
private-heap and finalized-handle contracts, typed domains, and dependency
replay, then admits totality only from the conjunction of the structural
session certificate, exact returning-publication closure, protected-state
capability seal, and returning-closure allocator-state audit. See
`2026-08-06-allocator-session-capability-seal-design.md` for the current proof
boundary and `2026-08-06-allocator-session-capability-seal.md` for its active
implementation plan.

The remaining sections are preserved as rejected-design rationale. Their
present-tense requirements describe the proposal and must not be read as the
current implementation contract.

## Rejected Design (Historical)

### Transaction goals

For an allocator-totality query `(backend_root, allocator,
allocation_caller)`, the terminal goals are all exact owned calls to
`allocator` made by `allocation_caller`. If the function contains multiple
such calls, the slice is their union; no runtime trace or preferred arm may
select a subset. A query bottoms if no goal exists, an incoming domain is open,
or a goal is reachable only through unresolved control.

### Spine functions and intraprocedural slices

Build a finite exact callgraph from the already recovered direct and finite
indirect targets. Compute the least set of spine functions that can reach an
allocation goal from `backend_root`.

For each spine function, retain the union of instructions that are:

- reachable from that function's selected entry continuation; and
- able to reach either an allocation goal or a call site into another spine
  function.

This is a bidirectional intraprocedural slice over `_summary_successors`. A
conditional branch that calls a side function and reconverges before a spine
call remains in the slice. A branch whose successors cannot reach any goal is
excluded. Missing successors, interior ownership, unresolved jumps, or
ambiguous finite targets bottom the query.

### Calls in retained blocks

Every call instruction in a retained block is classified as one of:

- **Spine call:** at least one exact target is a spine function. All exact
  targets must be reconciled; returning targets are sliced recursively.
- **Certified allocator leaf:** an existing private-heap/finalized-handle
  contract succeeds under the identical protected-slot set. The witness and
  its full function/global dependency snapshot are recorded.
- **Exact import:** the existing parsed-PE identity, arity, argument-domain, and
  effect contract succeeds.
- **Deferred lifecycle/callback call:** the existing context-bound finite-target
  and nonreturn proof succeeds.
- **Side call:** every exact target enters a complete finite semantic closure.
  That closure is audited with the existing argument-domain, write-domain, and
  direction-flag machinery.

Any unclassified call bottoms. A call is never excluded merely because its
fallthrough reaches a goal; its effects must be certified first.

### Slice record

Add a typed internal record containing:

- backend root, allocation caller, allocator, and goal call sites;
- canonical per-function retained instruction addresses;
- spine call edges and side-scope function entries;
- certified leaf, exact import, and deferred-call witnesses;
- protected slots and typed call-return/argument domains;
- function, global-slot, absolute-reference, and control-flow dependency
  fingerprints.

The record is private implementation evidence. The public audit row continues
to serialize the existing allocator-totality and publication facts. The
certificate digest and dependency memo must nevertheless bind the canonical
slice payload.

### Totality and backend bridge integration

`_allocator_totality_certificate` uses the transaction slice for backend and
lifetime semantic-write audits. The existing full direct closure remains the
only source for the Task 5 one-root membership check.

The totality certificate stores the transaction slice and includes its
functions, instructions, calls, leaf dependencies, and protected slots in
`_allocator_totality_dependencies`. Memo hits replay all of them.

`_publication_backend_bridge` reuses the current totality slice rather than
rebuilding a whole-root semantic-write closure. Its existing `backend_bodies`
inventory still fingerprints every function in the full direct closure, as
required by the Task 5 caller bridge. Write auditing alone uses the recorded
retained addresses for spine functions and complete bodies for side closures.

### Caching and invalidation

Any slice cache key must bind:

- backend root, allocator, allocation caller, and goal call sites;
- protected slots and typed call-return domains;
- summary-fact signature, control-flow revision, and relevant write/reference
  revisions.

A hit is valid only after all recorded dependencies replay successfully. A
changed branch, call target, import/IAT identity, allocator leaf, private-state
writer, or retained instruction fingerprint forces recomputation or bottom.

## Error Handling

The implementation remains proof-producing and fail-closed. It returns `None`
for an empty goal set, an open incoming domain, an unresolved retained edge, an
uncontracted import, an unsafe side closure, a protected-slot overlap, a stale
dependency, or a slice that exceeds analysis limits. It does not fall back to
the old whole-closure semantic audit after a slice failure, because that would
make failures unpredictably expensive and could obscure the exact blocker.

## Verification

Add focused tests for:

1. An unrelated `GlobalReAlloc` branch that cannot reach the allocation goal;
   totality succeeds and the branch is absent from the transaction slice.
2. The same call before the goal or on a branch that reconverges before it;
   the call is retained and the uncontracted import bottoms.
3. A retained protected-slot writer; bottom.
4. A retained unresolved indirect call or unresolved branch edge; bottom.
5. A branch that terminates through the exact context-restoring callback;
   only the proved nonreturn arm is pruned.
6. The finalized-handle/private-heap allocator chain remains retained or is
   summarized only by its exact certificate.
7. Multi-root and split-closure hostiles still reject.
8. Slice-cache invalidation for a changed retained instruction, call target,
   protected slot, certified allocator leaf, and private deallocator writer.
9. The existing publication/import/caller-domain hostile matrix remains green.

After focused tests, run the full x86-CFG/lifetime-audit suite, Ruff,
`py_compile`, `git diff --check`, the retail-address scan, and a hydrated retail
query. The retail query must exclude the independent `0x443170` chain while
retaining the expected allocator, grow, finalizer, session, lifecycle consumer,
and incoming-owner transaction facts. Only then may the next full retail replay
start.

## Non-Goals

- No new import allowlist for unrelated compiler runtime APIs.
- No address-specific retail exception.
- No single arbitrary callgraph path that drops reconverging alternatives.
- No weakening of the full backend-root caller-membership requirement.
- No Rust rewrite or performance refactor in this repair.
