# Allocator Session Capability-Seal Design

**Date:** 2026-08-06

**Issue:** Melee tooling #1240

**Parent design:** `2026-08-02-return-path-publication-noninterference-design.md`

**Bounded private-heap child design:**
`2026-08-06-private-heap-bounded-interior-design.md`

**Supersedes:** `2026-08-06-allocator-transaction-slice-design.md`

## Decision

Split allocator evidence into three independently dependency-bound parts:

1. a structural session certificate that proves callback installation,
   setjmp/restore pairing, selected backend identity, caller membership, and
   the exact nonreturning failure arm;
2. a protected-state capability seal that inventories how the allocator's
   callback, cursor, remaining-capacity, return-storage, and descriptor-family
   addresses can be materialized or exported during the checked session; and
3. a semantic allocator-state audit over the exact returning-publication
   closure.

Only their conjunction is an allocator-totality certificate. The structural
session certificate may conditionally prune the proved failure arm while the
returning closure is constructed, but it must not be exposed or cached as
totality by itself.

## Why the Transaction Slice Was Rejected

The exact retail backend call graph is recursive. For backend `0x4908f0`, the
complete reachable set contains 1,778 owned functions after stopping at the
context-restoring terminal; 970 of those functions can reach an allocator
goal through the recovered call graph. The alternate root produces 1,029 such
functions. A shortest-path prototype reduced this to 22 functions but is not
sound: it drops longer branch alternatives that may execute in the same
session. Expanding all target-reachable functions recreates the whole-backend
proof that the slice was meant to avoid.

The small, semantically relevant boundary already exists later in the proof:
the exact returning-publication closure is expected to contain 39 retail
bodies. The design therefore proves the session facts needed to construct that
closure, then audits allocator state over that closure without claiming that
the entire compiler process is isolated.

## Claim and Trust Boundary

The final claim is deliberately session-scoped:

> For the checked compiler image and selected backend session, every execution
> that returns to the publication observation sees the proved allocator state
> and cannot reach its failure callback.

The proof assumes that executable code cannot forge a protected mapped-global
address from an untracked numeric source and that no external caller,
concurrent thread, signal handler, or unmodeled imported routine injects such a
capability during the synchronous session. Calls are also required to obey the
x86 ABI rule that the direction flag is clear on return; explicit DF operations
in each directly participating body are still checked. These are explicit
assumptions, not deductions from arbitrary raw x86. The certificate must bind
and serialize them; it must never be described as process-global memory
isolation.

Within that boundary, all capabilities that the checked image does
materialize are audited. A protected address may not escape to an uncertified
body, import, unresolved indirect call, writable global, or opaque memory.

## Phase A: Structural Session Certificate

Add a private `_AllocatorSessionCertificate`. It proves only:

- the exact session root and initialization target;
- the installed callback slot and singleton callback target;
- the paired setjmp context and context-restoring nonreturn target;
- the selected backend call site and backend root;
- the allocation caller, allocator, grow target, private-heap/finalized-handle
  contracts, and their typed return domains;
- one backend root whose complete direct closure contains the lifecycle
  consumer, allocation caller, and every exact incoming consumer owner; and
- stability of the protected session fields from successful initialization to
  the backend invocation, using the finite session slice plus complete raw
  protected-reference/writer inventory rather than semantic expansion of every
  callee reachable from that slice.

Phase A does not prove allocator totality, freshness across the backend, or
reset exclusion. Its only control-flow authority is a typed witness that the
exact installed failure callback restores the paired context and therefore
does not return to its call continuation.

The witness is usable solely by `_returning_publication_closure` for pruning
that exact callback target and its exact failure arm. It cannot authorize
generic nonreturn pruning or satisfy `_allocator_totality_certificate`.

## Phase B: Returning-Publication Closure

Build the existing exact returning closure with Phase A's narrow callback
witness. All other closure rules stay fail-closed: unresolved indirect calls,
unowned targets, imports without exact contracts, recursive lifecycle reentry,
or analysis-limit exhaustion bottom the query.

For retail, the integration witness remains the expected 39 owned returning
bodies. The count is not an acceptance rule; the typed body inventory and call
edges are.

## Phase C: Protected-State Capability Seal

The seal covers byte spans for:

- callback slot;
- cursor and remaining-capacity fields;
- allocator return-storage fields; and
- the arena-base, cursor, and remaining fields (`+8`, `+12`, and `+16`) of
  every descriptor in the proved descriptor family, including partial
  overlaps and affine indexed accesses.

For each span, inventory all loader relocations, literal immediates,
displacements, absolute memory operands, LEA forms, finite arithmetic
materializations, affine/indexed materializations, and REP/string-operation
destinations that may carry or write the address. Unknown mapped-global
domains that may overlap a protected span are bottom.

Every materialized protected capability is classified as one of:

- an exact certified role use;
- an allowed returning-closure read/write governed by the state audit; or
- an escape.

The certified descriptor roles are deliberately narrow and carry their own
exact instruction witnesses:

- a descriptor-rebuild role may rewind one descriptor head and rebuild only
  its derived protected fields;
- a sibling descriptor-allocator role must use the checked grow target and the
  descriptor's exact cursor/remaining (`+12`/`+16`) layout;
- a descriptor-initializer role may perform the bounded zero initialization of
  the certified descriptor family, with the paired callback/grow evidence; and
- a descriptor-allocation-site role may perform one exact inline
  bump/grow/result-load sequence for a certified descriptor.

This is a use-based rule, not an owner-based allowlist. Membership in one of
these roles permits only its recorded protected write addresses and shape; an
additional protected write by the same function is an escape and bottoms.
Rebuild and initializer role functions must also be outside the returning body
inventory. Their pre-session work cannot justify a mutation on an execution
that returns to the publication observation.

An escape includes storing the address or a derived interior pointer to an
unprotected global/opaque memory, passing that capability to an import or
unresolved call, returning it from an uncertified body, or carrying it across
an unmodeled indirect edge. Every escape bottoms. An unrelated call that
receives no protected capability is permitted under the explicit no-external-
pointer-injection/no-unmodeled-writer assumption. Exact private-stack stores
whose destination is proven local remain allowed and dependency-bound. A PUSH
of a protected capability remains bottom because it may be a call argument;
proving a balanced, nonescaping push/pop transport is outside this certificate.
Certified finite direct calls remain allowed and dependency-bound.

The seal binds the executable ownership partition, complete reference rows,
call-target facts, protected spans, role assignments and exact write
witnesses, and the explicit non-forgeable/no-external-injection assumption.

## Phase D: Returning-Closure Allocator-State Audit

Audit every instruction and returning call edge in the Phase B body inventory
with the existing semantic address-domain machinery, generalized to all
protected spans. Require:

- no reset, cursor rewind, capacity overwrite, callback overwrite, or
  descriptor-family mutation between allocation/grow and observation except
  the exact proved allocator transitions;
- no dynamic, partial, affine, REP, or unknown write that may overlap a
  protected span;
- the private allocator and finalized-handle chain to preserve size and fresh
  storage under their exact contracts; and
- every imported effect in the returning closure to match its exact typed
  contract.

A reset outside the active returning interval is valid and must remain
accepted. An unrelated `GlobalReAlloc` branch outside the returning closure is
irrelevant under the stated capability seal; the same call in the returning
closure must satisfy an exact effect contract or bottom.

## Final Certificate and Dependencies

`_AllocatorTotalityCertificate` is created only after Phases A-D succeed. It
contains or digests:

- the structural session certificate;
- the returning body inventory and exact call edges;
- the capability seal and explicit assumption identifier;
- the protected-state semantic audit witnesses;
- private heap/finalized handle contracts and typed domains; and
- every role function and exact role-write witness, plus every call-target,
  global-slot, reference, import, ownership, and control-flow dependency used
  by those facts.

Memo hits replay each component independently. A change to session structure,
one protected reference, an address materialization, a returning body, an
import binding, or a private allocator dependency invalidates the final
certificate. Phase A may have its own private dependency memo, but a hit never
masquerades as final totality.

The full backend closure remains a Task 5 identity/caller-membership inventory.
It is fingerprinted but is not semantically write-audited.

## Hostile Verification Matrix

Tests must reject:

1. callback restoration with a reachable success continuation, wrong context,
   returning callback, or callback overwrite;
2. a protected one- or two-byte partial write;
3. affine/indexed or REP writes that may overlap a protected descriptor;
4. a protected address passed to an import, unresolved call, opaque global, or
   uncertified return;
5. a reset or rewind inside the returning closure;
6. an unsafe system reallocation in the returning closure;
7. a split backend where no single root contains all required owners; and
8. an extra protected write by an otherwise certified descriptor-role function;
9. malformed rebuild, sibling-allocator, initializer, or allocation-site role
   shape; and
10. stale Phase A, seal, returning-body, role, or state-audit memo evidence.

Tests must accept:

1. a reset wholly before initialization or after the returning observation;
2. unrelated compiler-runtime branches outside the returning closure when no
   protected capability reaches them; and
3. the exact private allocator/finalized-handle chain with fresh typed returns;
   and
4. the exact bounded descriptor initializer, rebuild, sibling allocator, and
   inline allocation-site roles outside the returning closure.

After focused tests, run the full x86-CFG/lifetime suite, Ruff, `py_compile`,
`git diff --check`, the exact retail hydrated query, and one clean checkpoint
replay. Promotion requires the existing zero-new and independent verifier
gates; the expected retail body counts are diagnostics, never substitutes for
typed evidence.

## Non-Goals

- No whole-process memory-safety claim.
- No shortest-path or preferred-trace proof.
- No new allowlist for unrelated imports.
- No retail-address exception in production code.
- No Rust or broad performance rewrite inside this correctness repair.
