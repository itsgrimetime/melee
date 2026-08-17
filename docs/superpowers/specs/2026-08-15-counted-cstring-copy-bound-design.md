# Counted C-String Copy Bound Design

## Problem

The Task 8 private-stack residue replay now reaches the exact copy at
`0x412278` with a stack-derived destination and an unknown scalar length.  The
callee computes that length with `REPNE SCASB`, so both the finite-value query
and the unsigned-interval query correctly return unknown.  The exact call
context does not improve the result because the scanned bytes live in a
mutable scratch buffer rather than loader-initialized data.

The caller already establishes the missing fact.  Immediately before the
guarded copier, it invokes a counted-string writer whose full-width count is a
zero-extended byte.  That writer copies exactly `0..255` bytes into the same
scratch address and writes a terminating NUL at the copied length.  The
consumer then scans that scratch string, rejects lengths above 63, and copies
the accepted string plus NUL, for a maximum copy of 64 bytes.  The current
alias proof descends into the consumer after forgetting this caller-bound
producer/consumer relation.

This is a missing semantic continuation, not authority to weaken the generic
alias lattice, accept an unbounded scan, raise a cap, or treat TOP as bounded.

## Evidence

- The completed authoritative replay returned
  `call-slot-consumed=0x443a10;argument=1;function=0x443770;result=False` after
  2h19m and isolated the first unbounded copy at `0x412278`.
- The reachable function spine is
  `0x49b920 -> 0x4434e0 -> 0x445780 -> 0x446bc0 -> 0x41b830 ->
  0x424090 -> 0x413730 -> 0x412210`.
- At `0x412275`, `EDI` remains unknown even with exact caller context
  `(0x412210, 0x41376b, 0x413730)`.
- At the preceding counted writer, `ECX` at the count push is exactly the
  finite domain `0..255`, derived from one `MOVZX` byte load.
- The caller passes the same finite scratch pointer to the producer destination
  and the consumer source, with no intervening call, branch, or memory write.

## Chosen Design

Add one query-local, caller-bound alias continuation at an exact guarded
C-string copy call.  It has three independent proof components.

### Counted producer

Recognize an address-independent counted-string writer whose reachable body:

- loads destination argument 0 and source argument 1;
- zero-extends the byte at the source into the copy count;
- forwards `(destination, source + 1, count)` to the existing exact audited
  `memcpy` body;
- reloads the same byte count and stores one NUL at
  `destination + count`;
- preserves its callee-saved registers and returns with the exact cleanup; and
- has exact raw/recovered call and successor domains.

The caller-side auditor must find exactly one such producer on every path to
the guarded consumer, prove that the producer destination and consumer source
are the same nonzero finite pointer domain, and require a straight-line
producer-return-to-consumer interval with no call, jump, RET, IRET, memory
write, or explicit stack rewrite.  Ambiguous pointer values, bypass paths,
extra producers, unsupported instructions, or limit exhaustion reject.

### Guarded consumer

Recognize an address-independent guarded C-string copier whose reachable body:

- loads source argument 0 into the scan cursor, seeds a full-width count of
  `0xffffffff` in the instruction's implicit ECX counter, zeroes the implicit
  AL byte through full-width EAX, and performs the exact 32-bit-address forward
  `REPNE SCASB` through EDI;
- derives the byte length as `0xfffffffe - remaining_count`;
- admits the copy path only through a full-width comparison with 63 and the
  exact signed `JLE` arm;
- increments that accepted length exactly once and forwards
  `(destination argument 1, source argument 0, length + 1)` to the existing
  audited `memcpy` body;
- restores the exact prologue-saved source and cursor families on every
  reachable return without return-slot drift;
- performs no other write through either pointer and never stores or returns
  either pointer;
- permits intervening source-reader calls only when their direct owned target,
  pushed argument, return use, raw call domain, direction-flag restoration,
  preservation of the live source/cursor register values, and reachable body
  jointly prove read-only/no-escape behavior, including the existing
  address-independent `_audited_strchr_function` shape when its
  interior-or-null return is discarded as scalar status; and
- returns only pointer-independent scalar status values on every reachable
  return.

The producer's `0..255` NUL guarantee makes the scan result nonnegative and
prevents the signed guard from admitting a wrapped high-bit length.  The guard
then proves the copy width is in `1..64`.  The guarded-consumer proof is never
issued without the matching producer proof. The caller must enter both calls
with the ABI direction flag clear, and the consumer's scan and copy must remain
on must-clear paths.

### Alias continuation

At the caller call boundary, read the exact two outgoing argument words from
the current alias fact.  The source must be proven non-stack and non-TOP.  The
destination may carry finite private-stack aliases; the certified consumer may
write scalar bytes through it but cannot retain or publish the pointer.

Return the caller base fact with callee-saved registers and existing private
spills/escapes preserved, `EAX` and `ECX` set to scalar, and `EDX` set to the
exact destination alias left by the audited `memcpy` body.  This is an exact
body effect rather than a generic cdecl assumption; a caller that forwards
`EDX` into the later tracked argument slot must therefore remain rejectable.
Keeping destination spill
contents unchanged is a conservative over-approximation: this continuation
grants no must-overwrite authority.  Project the result through the existing
escape demand.  If the
target body is recognized but any caller-bound producer, argument, bound,
mapping, or projection fact is missing, decline the continuation and retain
the ordinary fail-closed analysis.

All recognizer caches are fresh-query local and keyed by current function/call
identity.  No semantic result is serialized or restored from the structural
scan cache.

## Alternatives Rejected

- Teaching the generic interval interpreter to infer arbitrary
  `REPNE SCASB` lengths would require a new mutable-memory string domain and
  signed-wrap proof throughout the core lattice.
- Adding a bounded-string authority to every alias-context key would preserve
  the fact but enlarge all context, subscriber, and return products for a fact
  used at one adjacent producer/consumer boundary.
- Summarizing the outer caller would also have to absorb its independent
  validation and structure-write effects, making the certificate broader than
  the missing fact.
- Accepting the signed `JLE 63` guard without the counted producer is unsound:
  a missing NUL or a scan length with the high bit set can enter the signed
  success arm and produce a huge copy.

## Tests

Add one synthetic caller with an exact counted writer, guarded copier, audited
`memcpy`, stack-derived destination, and later protected argument.  On unchanged
production, the positive must fail only because the protected call slot is not
closed, while all recovery, call-domain, producer-count, alias, and body-shape
prerequisites remain non-vacuously true.

The strict matrix includes one positive and one-fact hostiles for:

- a full-width instead of byte-sized producer count;
- a missing or displaced producer NUL store;
- producer destination / consumer source mismatch;
- a bypass path, caller direction-flag mutation, intervening call, or
  intervening memory write;
- a source reader that leaks the direction flag or clobbers a live
  callee-saved source/count register;
- malformed scan accumulator family, address width, implicit count family,
  seed, source cursor, length subtraction, guard operand, guard arm, increment,
  or copy argument;
- a missing or wrong-family consumer stack restore on one return path;
- mutated `memcpy`, producer, or consumer call target/body;
- an extra pointer publication, forwarding of the returned destination in
  `EDX` into the tracked argument slot, or pointer-valued return;
- TOP/ambiguous source or destination aliases; and
- a second unproduced consumer that would expose authority leakage across
  contexts or queries.

Positive controls retain a clean non-stack endpoint path and two distinct
produced scratch domains.  Count recognizer invocations and require at most one
classification per candidate within a fresh query.  Use exact collection IDs,
run the focused residue/alias/formatter/memcpy matrix, the adjacent Task 8
selection, `py_compile`, project-scoped Ruff, and `git diff --check`.  Only
after those gates are green may the authoritative call-slot replay run
detached.

## Completion Boundary

This change closes only the caller-bound counted-string copy boundary.  Task 8
remains open until the detached call-slot replay is green, roots `0x435620` and
`0x435a8c` are independently positive, exact artifacts are generated and
revalidated, and all remaining promotion, merge, installed replay, issue
resolution, claim-clear, and queue-refresh gates complete.
