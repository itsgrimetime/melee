# Format Callback Literal-Count Design

## Problem

The private-stack residue proof reaches the retail formatter's one-byte prefix
callback with an unknown generic alias value.  The integer conversion helper
decrements its output cursor in a loop; the generic alias analysis enumerates
65 cursor positions and conservatively widens the return to TOP.  The existing
`_audited_reverse_format_helper_return` proof independently certifies that the
same helper return stays inside the formatter's fixed buffer window.

This is a precision boundary, not authority to weaken the generic alias
lattice.  The callback may receive a buffer cursor only when the existing
formatter protocol, helper-return certificate, source path, and count jointly
prove every copied byte remains inside the private buffer.

## Chosen Design

Extend `_audited_format_buffer_end_count` so its existing path-sensitive
source/count interpreter supports two count origins:

- the current callee-saved register relation used by the final callback; or
- one exact positive immediate pushed as the callback count.

For an immediate count, seed every path fact with the exact bounded interval
`[count, count]`.  Do not create a count register family, do not run the final
register-zero guard refinement, and preserve the literal fact across unrelated
instructions and certified calls.  Source tracking remains unchanged:
buffer LEAs, audited reverse-format-helper returns, and exact cursor arithmetic
are tracked; unknown writes become unknown; nonbuffer sources remain distinct.

At the callback, every buffer-derived source fact must satisfy
`_format_count_fact_covers_sources`.  Nonbuffer facts may remain nonbuffer, but
the proof must observe at least one valid buffer fact.  The existing immutable
format-domain guard, raw CFG successor equality, callee-saved preservation,
fact cap, and iteration cap remain mandatory.  TOP, ambiguity, wraparound,
zero count, a count whose upper endpoint crosses the window, or any malformed
helper/forwarding edge rejects.

The envelope consumer remains unchanged.  Once the existing auditor proves the
source/count relation, it issues the same buffer envelope already used for the
dynamic end-minus-source callback.  No retail virtual address, compiler hash,
function fingerprint allowlist, or raised analysis limit is introduced.

## Alternatives Rejected

- A bounded affine recurrence in the generic alias engine would solve a wider
  problem but would alter the core lattice and require a substantially larger
  soundness review.
- A callback-address or exact-body special case would not be a reusable semantic
  proof and would weaken currentness.
- Treating TOP as buffer-derived at the envelope boundary would conflate unknown
  provenance with certified buffer provenance and is unsound.

## Tests

Add a real synthetic engine/helper fixture that reaches an indirect callback
with `(stream, helper-return, immediate-count)`.  The unchanged production
code must fail the positive case before implementation.  One-fact hostiles
must cover at least:

- helper return outside the certified reverse buffer window;
- forwarding the wrong engine slot to the helper;
- zero immediate count;
- a literal count whose interval can cross the buffer end;
- an unclassified source definition; and
- malformed or detached callback ownership.

The positive and hostiles must exercise `_audited_format_buffer_end_count`
directly with recovered instructions and CFG, not mocks.  After GREEN, retain
all existing dynamic-count tests, formatter/writer tests, the focused Task 8
selection, the full x86 module, static checks, and a detached retail call-slot
replay.  Retail success is not inferred from local tests.

## Completion Boundary

This change closes only the helper-return/literal-count formatter boundary.
Task 8 remains open until the detached retail replay is green and the required
focused, full-module, static, root, artifact, promotion, merge, and installed
replay gates complete.
