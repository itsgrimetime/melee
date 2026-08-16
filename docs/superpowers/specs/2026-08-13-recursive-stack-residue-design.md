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

Raw caller and RET nodes remain available as provenance, but the bounded
worklist charges and connects their exact semantic effects only once. A caller
subscriber effect consists of its function and return cursor, exact caller-base
alias fact, transported escape demand, and every active formatter/stream
authority. A callee return effect consists of the callee identity, exact
returned alias fact, and exact callee-entry alias fact used to interpret
preserved inputs. Nodes with equal immutable effects may share one connection;
different caller bases, demands, authorities, returned aliases, or entry facts
never merge. This is canonicalization of identical transfer inputs, not an
approximation or a cap exemption.

The already audited, address-independent forward `memcpy` body may use one
parameterized entry-prefix alias transfer instead of materializing a callee
context for every absolute caller stack coordinate. The transfer requires its
exact reachable body bytes, including its callee-save and return protocol, a
singleton direct edge, exact caller stack arguments, a finite-value or
unsigned-interval upper bound for each non-immediate scalar length, and finite
source/destination alias values. An unknown scalar length is harmless only
when both endpoints are already proven non-stack; an unknown length at either
stack endpoint rejects. It
returns the exact destination alias in `EAX` and `EDX`, preserves callee-saved
aliases and caller spills, and makes `ECX` scalar. Source overlap uses a cyclic
32-bit byte interval; an unknown length or any interval that may contain a
tracked alias-bearing private word rejects the exact recognized call. It must
not fall back to the generic callee proof, which does not transfer alias values
through `rep movs`. An unrecognized body still follows the ordinary exact
callee proof. The transfer is not used for live-residue calls, whose
dereferences must still be audited instruction by instruction. Exact-body
classification is memoized only inside the current query and is recomputed by
the next fresh proof. Length bounds are likewise memoized per static call site
only within that query.

One separate pre-residue continuation closes a bounded scalar-format call at
its caller boundary without weakening generic `memcpy` or treating an indirect
writer callback as independently safe. Exact replay proved that the direct
bounded-writer context and the synchronous-stream-wrapper context are distinct:
the direct context has a stack-backed destination state and no stream authority.
It is therefore unsound to borrow the wrapper's immutable-format guard merely
because both targets occur in the formatter engine's recovered indirect-call
set. Such a context remains rejected if its caller-level output proof is absent.

The caller-level continuation requires an exact direct call to the existing
audited `sprintf`/`vsnprintf` body chain, a singleton immutable format, and a
small scalar-output grammar. Initially the grammar admits literal bytes, `%%`,
plain `%d`/`%u`, and plain `%s` only. Every conversion consumes exactly one
ordered pushed argument. Integer conversions contribute their complete 32-bit
text width. A string conversion requires a finite immutable NUL-terminated
domain and contributes the maximum measured byte length. A possible null value
is not a string authority; it may be removed only by a complete path proof that
the current caller replaces null with a specific immutable empty string before
the push. Flags, width, precision, length modifiers, `%n`, `%p`, wide strings,
unknown arguments, mutable bytes, arithmetic wrap, or an open/raw call edge
reject atomically.

A finite `%s` domain may also come from a closed registered-record table. This
is not immutable loader data: the retail table is zero-filled state populated
by one owned registration helper. Authority therefore requires the complete
record lifecycle, not merely a bounded indexed load. The registration helper
must find an empty record through a bounded full-width counter, write the name,
nonzero key, and payload fields in one exact record, and have the complete
incoming call domain sealed. Every name argument must belong to one finite
immutable NUL-terminated string domain. The reader must use a bounded counter
for the same stride, compare the requested nonzero key with the selected
record's key field, and preserve that selected-record identity through the
name-field load. The complete decoded/raw/provisional write inventory for all
record fields must contain only the audited registration writes. A missing
callsite, zero key, partial/swapped field write, index or stride drift, detached
reader guard, ambiguous selected-record identity, or open writer rejects.

For a stack destination, the complete maximum output including the terminator
must lie inside a currently allocated private interval under every coordinate
alternative. A non-stack destination is permitted. The output bytes are proven
scalar, so an overlapping private-spill alias row is killed only when every
destination alternative overwrites its complete four-byte word. A partial or
alternative-dependent overlap rejects because the alias fact cannot represent
the untouched bytes. The continuation preserves callee-saved aliases, makes
the audited integer return in `EAX` scalar, leaves caller-clobbered `ECX`/`EDX`
at TOP, projects existing escapes to the current demand, and rejoins the exact
caller return cursor. It applies only in the
entry-prefix alias tabulation before protected residue is live. Any body,
format, argument-domain, allocation, overwrite, cleanup, or return mutation
declines the continuation and follows the ordinary fail-closed path. No retail
address, body hash, format literal, or callback allowlist is production
authority.

Inputs at each invocation join monotonically under the exact-row/tail lattice.
Cross-call correlation that is lost by joining becomes a conservative union;
it can cause rejection but never authorization. Repetition alone is not a
closure witness: at least one path in the connected live-fact component must
reach an audited return fact or the exact trusted terminal boundary. Every
executed instruction and outgoing edge is still audited for observation or
escape. A divergent branch that performs no observation is safe under this
partial-correctness property; termination itself is not proof authority.

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
success witness. The backward witness relation is existential only after every
reachable transfer has passed its local no-observation checks; this permits
safe divergence but cannot hide a hostile edge, because any hostile transfer
rejects the query atomically. Retail acceptance must record the exact terminal
boundary that closes the widened tail.

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
callee-saved register at RET is an escape; caller-clobbered GPRs are also
observable machine outputs and must be proven non-alias or killed before RET.

Caller-spill demand projection retains only operands whose ESP or EBP base has
an exact canonical frame coordinate at that instruction. A saved inherited EBP
must pass the existing all-path seal before this projection is used. Once EBP is
overwritten by a scalar or arbitrary register value, `[ebp+...]` is not a direct
incoming-slot demand; any stack identity carried by that value is instead
handled by the register-alias observation rules. Ambiguous canonical frame
coordinates, indexed canonical frame accesses, or an unsealed inherited EBP
remain fail-closed.

Alignment projection may map several source spill rows or padding alternatives
to the same callee coordinate. Those rows are joined by coordinate before the
64-spill structural cap is charged: finite alias values union canonically and a
value-set overflow becomes TOP for that one coordinate. Counting duplicate keys
as distinct spills or retaining duplicate rows is forbidden.

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

The entry-prefix alias analysis may encounter two exact ABI boundaries before
the protected row exists. First, a direct owned function whose every reachable
exit is a registered
`indirect-jump-cw-exception-continuation` abandons the current call frame; an
unresolved indirect jump, incomplete context restore, unregistered target, or
ordinary cross-function jump remains blocking. Second, a direct one-jump
terminal import thunk may be treated as caller-cleaned only when its complete
raw direct-call domain is closed and every caller supplies the same exact
contiguous argument span followed by the same adjacent caller cleanup. Any
missing caller, mixed arity, mixed cleanup, extra raw reference, or nonterminal
thunk rejects. The entry-prefix alias tabulator seals that same boundary as an
unknown returning cdecl call: every word in the exact outgoing argument span
must be proven non-alias, callee-saved register aliases and private caller slots
are retained, and `EAX`/`ECX`/`EDX` become TOP. It never descends into the
one-JMP thunk as a normally returning owned body. An alias-valued argument,
ambiguous span, or missing continuation rejects. These rules establish pre-root
control/stack/alias facts only; they do not authorize a live residue to cross an
ordinary import and do not add a terminal shortcut to the residue fixed point.

A third entry-prefix boundary recognizes one exact setjmp-like context-save
protocol. The call must pass one immediate pointer to a mapped, writable,
non-executable 24-byte context and the target must have the exact already
audited 12-instruction save semantics. The current relocation-backed reference
inventory must contain exactly that one save call; every other owned reference
must be an adjacent argument to an exact nonreturning longjmp-like restore, and
every provisional unowned executable occurrence must raw-decode to the same
adjacent restore sequence inside its current residue interval. Interior context
references, exports, malformed save/restore bodies, returning restores, mixed
targets, or stale ownership reject. The transfer preserves existing alias facts
except for the save routine's exact scalar `EAX`/`ECX` result. It is query-local
entry-prefix authority only and does not exempt a live residue from ordinary
call auditing.

Query-local alias-key relevance may classify an incoming GPR as parametric
when a complete owned-return proof shows its incoming bits are never observed
and are either wholly preserved or wholly killed. At an otherwise blocking
terminal import, that survivor proof may use either the existing exact
named-stdcall arity contract or the already exact publication-import contract
only after the full normalized `(dll, name, ordinal, arity)` tuple and pushed
arity match. ABI callee-saved GPRs retain their mask, `EAX`/`ECX`/`EDX` are
killed, and `ESP` is never summarized by this rule. Unknown imports,
wrong-arity imports, and mixed terminal/owned targets remain TOP/fail-closed.
This classification only canonicalizes irrelevant alias values in a semantic
context key; it does not authorize protected residue to cross the import.

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
limit is raised for the retail case. `max_contexts_per_entry` is charged after
canonicalization per semantic `(owner entry, start address)`; distinct program
points in one owner do not consume one another's entry budget. The aggregate
query remains bounded independently by `max_summary_iterations`. Raw duplicate
subscriber/RET provenance does not consume that aggregate budget repeatedly;
each distinct immutable subscriber or return effect does, before it is inserted
or connected.

Nested pointer-return summaries may erase a tainted decreasing register only
after a complete owned-suffix audit proves that every use is scalar, every
exact owned call target cannot observe the incoming register, and every
reachable return first kills the value. Memory addressing, argument passing,
register copying, unresolved edges, or a live value at RET rejects. A locally
safe scalar recurrence is not enumerated offset-by-offset: divergence cannot
return the value, while every reachable exit remains audited.

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

The format-buffer authority may cross an owned copy only when a fresh,
address-independent writer protocol proves the complete source/count relation:
the initial remaining count is bounded by the issued buffer envelope, every
path selects a copy count no larger than that remainder, an optional delimiter
search can only reduce it to an in-range prefix, and the same count advances
the source while decreasing the remainder.  A known buffer source by itself
does not authorize an unknown length.  Wrong min-branch polarity, wrong count
store/source, an unbounded or out-of-range search result, mismatched copy
arguments, or unequal post-copy source/remainder updates must each reject while
the surrounding envelope and call graph remain current.

The same current formatter protocol may issue a one-byte leading-prefix
envelope only when the source alias is exactly one byte before the certified
buffer base and the path-local callback count is exactly the singleton value
one.  The envelope expands left by exactly one byte and retains the existing
escape-demand, basis, overflow, callback-domain, and stack-coordinate checks.
A source two bytes before the base, a count other than one, joined or TOP
source/count provenance, or overlap with the protected demand rejects.  This is
protocol-relative authority; no callback address, function hash, or format
literal participates in production acceptance.

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
