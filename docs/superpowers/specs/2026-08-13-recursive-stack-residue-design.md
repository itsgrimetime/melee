# Recursive Stack Residue Design

## Goal

Extend the private-stack scalar-quarantine proof so a closed recursive caller
graph can discharge capability-bearing outgoing argument slots without
declaring stale stack bytes dead. The proof must accept the exact recursive
parser used by the retail publication-root query only when every possible
caller, unwind, stack access, and terminal path preserves the capability seal.

## Problem

`_closed_call_argument_slot_is_consumed` currently tracks exact four-byte,
byte-masked stack rows through callees and reverse caller closure. It rejects a
caller function already present in `root_returns`. That rejection is sound but
too coarse for exact self-recursion: each unwind moves the same unconsumed
outgoing argument farther below ESP, producing an unbounded family of exact
negative offsets.

Three tempting alternatives are not acceptable:

1. Bytes below ESP cannot simply be declared dead. A caller may explicitly
   reload or publish them after return.
2. An exact recursive-call exemption cannot close the outgoing slot. Exact
   target identity proves provenance, not lifetime; the recursive slot can
   remain readable after cleanup.
3. A full affine or congruence domain is unnecessary for the current proof and
   would substantially enlarge the trusted implementation around branches,
   writes, and caller rebasing.

## Chosen abstraction

Retain the existing exact slot rows on acyclic paths. Add one query-local dense
negative-tail fact to the same state:

```text
Tail(U) = a protected byte may exist at every stack offset <= U
```

`Tail(U)` is an over-approximation. It deliberately forgets stride,
congruence, byte mask, and alignment correlations. The tail is introduced only
at a repeated reverse-caller SCC control key whose exact live rows exhibit a
single uniform negative displacement. Stationary exact rows remain exact. A
mixed displacement, zero or positive drift, ambiguous row correspondence, or
state/cap overflow rejects.

The instruction state is conceptually:

```python
(
    current_function,
    cursor,
    exact_slot_rows,
    negative_tail_upper,
    stack_alias_facts,
)
```

All state is owned by one `_closed_call_argument_slot_is_consumed` invocation.
No tail, recurrence summary, provisional success, or currentness fact may be
stored in a recovery-wide or persistent cache.

The exact-row/tail lattice is ordered by the set of bytes it may contain. At
every ordinary CFG or caller join, tail bounds join with `max(U1, U2)`. Exact
bytes at offsets `<= U` are subsumed by the joined tail; exact bytes above `U`
remain exact and join byte masks and correlation alternatives. Stationary rows
never disappear merely because another row widened. A branch-local overwrite
therefore cannot hide a preserving sibling: the preserving fact is restored at
the join. Every increase in a tail bound, exact mask, or correlation set
re-enqueues successors.

## Context-free call and recurrence graph

Concrete continuation stacks cannot bound the retail parser: after returning
from one self-call, its loop can reach the same call again while residue is
live. Replace the current explicit-continuation walk with a query-local
tabulation graph. An invocation contains a function, entry cursor, and joined
input exact-row/tail/alias facts. A direct owned call performs the pre-call
transfer, registers a subscriber containing the caller continuation cursor and
exact cleanup, and joins its input into the callee invocation. Every callee RET
fact is transformed back through every subscriber. New or enlarged input and
return facts re-enqueue their affected instruction states. Recursive and mutual
call SCCs therefore converge without growing a concrete call stack, while every
call and return edge is still audited.

Inputs at each invocation join monotonically under the exact-row/tail lattice.
Cross-call correlation that is lost by joining becomes a conservative union;
it can cause rejection but never authorization. A call SCC is not accepted
coinductively merely because it repeats. It must reach an audited return fact or
the exact trusted terminal boundary, and every reachable outgoing edge must
remain closed.

Reverse caller closure uses the same graph. At a root RET, complete closed
incoming direct-call enumeration creates subscriber-like caller-suffix
invocations beginning at each exact return cursor. It does not build a
`root_returns` path history or skip a repeated caller.

Before joining a new invocation or caller-suffix input, the proof canonicalizes
the live rows into a recurrence shape containing:

- function and exact start/return cursor;
- byte masks and alignment-correlation identities;
- the pairwise relative positions of rows that must move together; and
- stationary rows that are not part of the recurrence.

For a repeated shape, the implementation requires a unique one-to-one row
correspondence. Every drifting row must have the same displacement `d < 0` and
every other row must be stationary. The drifting rows are replaced by
`Tail(U)`, where `U` is the greatest live byte offset represented by either
observation. An existing tail joins with `max(old_U, new_U)`. The recurrence is
then re-enqueued only when this abstract fact grows.

The dense tail covers every later recursion depth, so the worklist reaches a
finite fixed point. Recurrences with positive drift, incompatible masks,
incompatible correlations, more than one nonzero drift, or no exact exit are
not widened and reject fail-closed.

The same widening rule applies at forward invocation inputs, return-summary
joins, and reverse caller-suffix inputs. Zero/positive drift or incompatible
shape does not receive a recurrence shortcut; if ordinary finite joins do not
stabilize within the existing cap, the query rejects.

The graph must retain a non-vacuous closure witness. Exact rows may be
eliminated by guaranteed overwrites. A downward-infinite tail cannot be
eliminated by any finite sequence of overwrites; it can only reach an audited
terminal process boundary. Encountering a repeated state by itself is never a
success witness. Retail acceptance must record the exact terminal boundary
that closes the widened tail.

## Transfer semantics

### Explicit stack memory

Every ESP- or stack-valued-EBP memory operand is reduced to a finite set of
effective intervals. Segment overrides, unresolved EBP coordinates, unbounded
indices, unsupported scales, or more than the configured finite address budget
reject.

A read, read-modify-write, or address-taking operand rejects when any feasible
interval overlaps a live exact byte or may intersect `Tail(U)`. An interval
`[lo, hi]` intersects the tail exactly when `lo <= U`.

A pure MOV overwrite clears an exact byte only when every feasible effective
address covers that byte. It may shrink a tail only when every feasible
interval covers its upper boundary. If the feasible interval starts are
`lo_1...lo_n`, the new upper boundary is `max(lo_i) - 1`. Using any alternative
or the minimum start would be unsound.

### ESP movement

Constant full-width `add esp, imm` and `sub esp, imm` translate exact rows and
the tail by the same signed coordinate change. Existing magnitude and
instruction-form bounds remain mandatory. Supported stack-alignment states
retain exact correlated rows; a tail cannot cross a non-unique alignment reset
unless every possible movement produces the same safe tail result. Otherwise
the proof rejects.

The already validated EBP-to-ESP reset remains available only when its finite
coordinate alternatives translate every live fact safely. Any other write to
ESP is non-affine and rejects.

### Implicit stack operations

All explicit operands are evaluated before an implicit stack effect. Thus
`push [esp-4]` and `call [esp-4]` observe the old interval and reject before the
implicit overwrite is applied.

PUSH and CALL overwrite exact live bytes in `[-4, -1]`, then rebase remaining
exact rows by `+4`. Their dense-tail transfer is piecewise:

```text
U < -4         -> U' = U + 4
-4 <= U <= -1 -> U' = -1
U >= 0         -> U' = U + 4
```

The middle case retains a nonempty infinite tail; the finite overwrite never
eliminates it. POP and RET read four bytes at the pre-instruction ESP. An
overlap is an observation, but when a POP destination is proven to have the
capability-specific closed suffix the physical exact bytes or tail remain live
and are rebased by `-4`; POP does not overwrite them. RET always rejects an
overlap. Otherwise both operations rebase by `-4`, with RET applying the exact
additional cleanup: `offset' = offset - 4 - cleanup` and
`U' = U - 4 - cleanup`.

All implicit operations use byte-interval overlap, not row-start equality, so
partially aligned rows straddling `[-4, -1]` or `[0, 3]` are handled correctly.

A POP that overlaps protected bytes is accepted only when its exact full-width
destination has the capability-specific closed unobserved suffix already
required by the current proof. RET or IRET observing any protected byte
rejects.

### Stack-base aliases

Each invocation carries a query-local may-stack-alias analysis from its entry,
not merely from the point where the protected word becomes live. The analysis
tracks finite affine ESP/stack-valued-EBP addresses through full-width GPR
copies, LEA, constant add/sub, proven-private allocated stack spills/restores,
and joins. Incoming register facts are mapped from the complete direct-call
domain; any value without a closed caller proof is TOP. An ordinary call return
family is TOP unless an interprocedural return-alias summary proves it
stack-disjoint. An alias live in a return register or a caller-visible
callee-saved register at RET is an escape.

Storing a stack alias in non-stack memory, an incoming/caller-owned stack slot,
or a stack slot visible to a call is also an escape. Only a currently allocated,
proven-private coordinate may be used as an internal spill, and every reachable
path must kill it before deallocation or return. Unresolved arithmetic, partial
register operations, unbounded indices, ambiguous stack resets, or the alias
analysis cap produce TOP and reject when the value is observed, escapes, or
could intersect a live exact row or negative tail region.

This entry-prefix analysis prevents pre-taint aliases from bypassing the
suffix proof. In particular, `lea edi,[esp-4]` before the protected PUSH is
still recognized after the call, and prepublishing that address to global
memory rejects before a tail can be introduced. While any exact row or tail is
live, new `lea reg,[esp+...]`, `mov reg,esp`, `push esp`, and equivalent
stack-valued-EBP materialization likewise reject unless the tracked alias is
used only by the existing exact coordinate machinery and is killed before any
observation or escape.

### Calls and returns

Direct owned calls retain exact target, raw-successor, stack-cleanup, and
subscriber checks, and the proof descends into owned no-return bodies rather
than closing at the call instruction. Any unresolved, indirect, ordinary
import, or other unowned call rejects while any exact row or tail is live:
formal-argument disjointness cannot show that unknown code will not allocate
downward and read caller residue.

The sole terminal shortcut is the exact existing trusted import contract
`("kernel32.dll", "ExitProcess", None, 1)` from
`_EXACT_STDCALL_IMPORT_ARITIES`, with DLL and name compared under the existing
canonical import normalization, ordinal exactly `None`, arity exactly one, and
an empty recovered successor domain. `_call_is_proven_no_return` alone is not
sufficient authority because it currently recognizes the name more broadly.
The proof first evaluates all explicit operands, requires the tail and exact
rows to be disjoint from the complete one-argument span, and rejects any
stack-alias escape. This is a semantic program-observation boundary, not a
claim that an arbitrary no-return callee is stack-pure. No owned function,
unresolved edge, ordinary import, callback, or new import name acquires this
authority.

Root returns enumerate the complete closed incoming direct-call domain. Tail
and exact rows are translated into each caller; every caller suffix is audited.
No caller is skipped merely because another caller is safe. Any missing owner,
raw-edge mismatch, unresolved active call edge, or unclosed caller rejects the
whole proof atomically.

## Limits and currentness

The existing `max_summary_iterations` and `max_contexts_per_entry` limits
remain hard fail-closed bounds. Recurrence-shape, alias-state, and finite-address
enumeration also charge those limits before insertion or materialization. No
limit is raised for the retail case.

The enclosing scalar-quarantine boolean cache must include the complete current
summary-fact signature and CFG revision, or be cleared whenever either changes;
instruction count alone is not currentness. A run-true-then-mutate test changes
one caller/target/summary fact without changing instruction count and requires
fresh rejection. A fresh recovery/query never reuses recurrence or alias state.

## Required RED matrix

The implementation begins with named, one-fact tests for:

1. the safe self-recursive unwind that currently fails only at recurrence;
2. a caller reload of recursive residue immediately after cleanup;
3. a caller reload reachable only after multiple recursive unwinds;
4. one hostile reverse-caller edge among otherwise safe callers;
5. a hostile exit in a mutual-recursion SCC;
6. ESP- and EBP-relative negative reloads;
7. bounded-index alternatives where at least one address overlaps residue;
8. an unbounded index, segment override, non-affine ESP update, and cap
   exhaustion;
9. stack-base LEA, MOV, and PUSH aliases followed by indirect reload, including
   aliases and global prepublication created before the protected PUSH;
10. partially aligned exact rows that straddle PUSH/CALL/POP/RET intervals,
    plus `pop ecx; kill ecx; mov eax,[esp-4]` to prove POP retains residue;
11. explicit `push [esp-4]` and `call [esp-4]` reads before implicit overwrite;
12. a pure overwrite with multiple possible addresses where only one covers
    the tail boundary;
13. an unresolved/import no-argument call and an owned no-return callee that
    inspect or publish deeper residue;
14. ordinary branch joins where one branch shrinks a tail and one preserves it,
    and a tail joined with a stationary exact row above its bound;
15. a zero/positive-drift or incompatible recurrence and cap exhaustion;
16. live forward self-recursion and mutual recursion, including a hostile
    subscriber edge and a later loop iteration that observes residue;
17. a pre-live helper return carrying a stack alias, a call-return TOP used as
    a memory base, an alias returned/carrying out in a callee-saved register,
    and an alias stored in incoming/caller-owned stack storage; and
18. cached `True` followed by a same-instruction-count caller, target, or
    summary mutation.

Positive controls cover safe self-recursion ending at the existing trusted
process-termination boundary, live forward self-recursion and mutual recursion
whose complete return/subscriber graph is safe, safe acyclic upstream callers,
a guaranteed overwrite from every finite address alternative, a proven-private
alias spill/restore, nonzero `ret imm16` cleanup, and existing non-recursive slot
consumption behavior.

Every hostile must prove that Task 1--4 recovery and the fixture's exact call
topology remain intact. Tests may not pass vacuously because an earlier proof
stage disappeared.

## Retail acceptance

Synthetic GREEN is necessary but not sufficient. The pinned retail recovery
must establish the exact scalar quarantine at `0x4439ae` through this generic
proof, while the separately validated protected push at `0x44364a` remains
green. Then the complete publication-root replay at `0x435620` must advance or
close. Addresses belong only in tests, diagnostics, and tracked evidence; no
retail address, hash, or shape allowlist may enter production.

## Scope

Production and test changes remain limited to:

- `tools/mwcc_retro/x86_cfg.py`
- `tools/melee-agent/tests/test_retro_x86_cfg.py`

This design may add its implementation plan and Task 8 evidence updates. It
does not change Task 5--8 schemas, resolver output, immutable artifact formats,
or the authority of any existing certificate.
