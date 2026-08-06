# Allocator Transaction Slice Design

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

This is the selected approach. The full closure continues to establish backend
identity and caller membership. A separate bidirectional CFG/callgraph slice
defines the semantic-write transaction. It excludes unrelated branches by
proof of non-reachability, not by trusting their effects.

## Design

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
rebuilding a whole-root semantic closure. Its body inventory fingerprints each
function participating in the transaction, while write auditing uses the
recorded retained addresses for spine functions and complete bodies for side
closures.

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
