# Allocator Session Capability-Seal Implementation Plan

> **Execution:** Use `superpowers:executing-plans`; self-review each checkpoint
> under the user's standing autonomous-approval instruction.

**Goal:** Replace the unsound/unbounded allocator transaction slice with a
session-scoped structural certificate, protected-state capability seal, and
returning-closure state audit whose conjunction proves allocator totality.

**Linked bounded private-heap plan:**
`2026-08-06-private-heap-bounded-interior.md`

**Architecture:** Phase A proves only session identity and the exact
context-restoring failure callback. It constructs the existing exact returning
closure. A complete protected-address seal and semantic audit over that closure
then produce the final totality certificate. The complete backend closure is
retained for identity and caller membership only.

## Constraints

- No provisional object may be named, cached, or consumed as allocator
  totality.
- Bind the non-forgeable/no-external-injection assumption explicitly.
- Preserve all existing exact caller reconciliation and one-root membership
  checks.
- Accept reset outside the active returning interval; reject it inside.
- Fail closed on partial/affine/REP writes, unknown mapped-global domains,
  protected-capability escapes, unresolved edges, and stale dependencies.
- Do not launch a full replay until the hydrated exact query succeeds.

## Task 1: Freeze the replacement boundary in tests

- [ ] Restore the existing reset-outside-lifetime test to acceptance.
- [ ] Add RED tests distinguishing `_AllocatorSessionCertificate` from final
      `_AllocatorTotalityCertificate`.
- [ ] Add RED tests showing that only the paired, nonreturning callback can
      prune the failure continuation.
- [ ] Add RED tests that an unrelated untrusted branch outside the returning
      closure is accepted, while the same effect in the closure rejects.
- [ ] Run the focused allocator/publication tests and record the RED failures.

## Task 2: Extract Phase A structural session evidence

- [ ] Add immutable session/callback-witness records with no totality wording.
- [ ] Refactor the structural prefix of `_allocator_totality_certificate` into
      `_allocator_session_certificate` without changing its strict session,
      caller, backend-membership, private-heap, or finalized-handle checks.
- [ ] Give Phase A a dependency memo that replays all structural inputs and
      cannot be returned by the totality cache.
- [ ] Make `_returning_publication_closure` accept only the narrow callback
      witness needed to exclude the exact context-restoring arm.
- [ ] Run focused tests, Ruff, `py_compile`, and `git diff --check`.

## Task 3: Implement the protected-state capability seal

- [ ] Define canonical protected spans for callback, cursor, remaining,
      return storage, and the complete descriptor family.
- [ ] Generalize the existing publication reference/address-domain inventory
      to partial overlaps, affine/indexed values, and REP destinations.
- [ ] Track finite protected-address capabilities through registers, stack,
      direct calls, returns, and stores.
- [ ] Classify exact allowed role uses and reject imports, unresolved calls,
      opaque stores, uncertified returns, and unknown aliases.
- [ ] Bind exact descriptor rebuild, sibling-allocator, bounded initializer,
      and inline allocation-site roles. Treat role membership as permission for
      only the recorded write witnesses, never as a function-wide allowlist;
      keep rebuild/initializer roles out of returning bodies.
- [ ] Bind ownership, reference, call-target, global-write, and assumption
      revisions to an immutable `_SessionStateCapabilitySeal`.
- [ ] Add hostile tests for literal, partial, affine, REP, import, indirect,
      global-store, and return escapes.
- [ ] Add role-shape and use-based hostile coverage: malformed role shapes,
      a second protected write by an otherwise certified role, and stale role
      dependency replay.

## Task 4: Audit allocator state over the returning closure

- [ ] Reuse the Phase B typed returning-body inventory rather than a backend
      call-graph slice.
- [ ] Audit all protected spans with semantic argument/return domains and exact
      private allocator/finalized-handle contracts.
- [ ] Reject reset/rewind/overwrite/dynamic alias effects in the active
      interval; keep pre-session/post-observation reset accepted.
- [ ] Require exact import effects for every returning import.
- [ ] Construct `_AllocatorTotalityCertificate` only from Phase A + returning
      bodies + capability seal + state audit.
- [ ] Bind/replay all component dependencies in the final memo.
- [ ] Verify the final certificate records and replays descriptor-role
      functions and exact protected-write witnesses without widening the
      returning-body audit to the full backend closure.

## Task 5: Remove the rejected transaction implementation

- [ ] Delete `_AllocatorTransactionFunctionSlice`,
      `_AllocatorTransactionSlice`, and transaction-slice construction when no
      production consumer remains.
- [ ] Remove or rewrite transaction-specific fixture mutations/tests as
      closure/capability-seal tests.
- [ ] Preserve validated private-heap/finalized-handle contracts, typed return
      propagation, and dependency-replay fixes.
- [ ] Confirm no documentation or audit output claims a whole-backend semantic
      proof.

## Task 6: Exact retail and replay gates

- [ ] Run the focused x86-CFG/lifetime matrix, Ruff, `py_compile`, and
      `git diff --check`.
- [ ] Run the hydrated retail query for allocator `0x441fa0`, allocation caller
      `0x4a2660`, lifecycle consumer `0x4351c0`, and selected backend session.
- [ ] Require the exact returning closure/state seal to succeed without
      semantically expanding the complete backend closure.
- [ ] Update the Task 4 design/progress/outlook evidence and commit/push.
- [ ] Run one clean checkpoint replay with 15-minute quiet waits, then execute
      zero-new and independent verifier gates before Task 8 promotion.
