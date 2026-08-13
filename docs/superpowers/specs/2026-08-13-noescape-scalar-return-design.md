# No-Escape Scalar Return Design

## Goal

Close a capability-seal false rejection when an owned parser mutates a caller-
provided buffer but returns only a scalar count.  The proof must remain generic:
it may not name retail addresses, treat mutable input as read-only, or trust an
open call graph.

## Design

Add a query-local greatest-fixed-point proof over `(function, protected-slots)`
nodes.  A node is provisionally scalar while its body is audited.  The audit
propagates the existing protected-capability lattice through every reachable
instruction and accepts a direct call result as protected-free only when:

1. every exact target is owned and belongs to the same active proof graph;
2. every argument at that call site is either not pointer-derived or is proved
   non-escaping by the existing closed-SCC argument proof; and
3. the callee node completes successfully, or is an active recursive node whose
   complete body will be validated before the root certificate is published.

The graph succeeds only if every reachable return has a protected-free EAX
state, raw successor domains exactly equal recovered successors, and no node
uses an unresolved/terminal-external call.  A failed member invalidates the
whole provisional cycle.  Results live only in the enclosing capability-seal
query and carry no persistent authority.

The existing non-recursive capability proof remains the first path.  The new
proof is a fallback for a PUSH or STORE whose register still has conservative
literal lineage and no exact finite value.  It does not authorize dereference,
write bounds, or read-only behavior; it establishes only that the transferred
word cannot name a sealed allocator slot.

## Required tests

- Positive: one closed caller pushes a derived input pointer into a mutating
  callee whose return is a scalar count.
- Positive: a recursive exact call SCC with non-escaping pointer arguments and
  scalar returns.
- Negative: one SCC member returns the pointer.
- Negative: one argument escapes to global memory.
- Negative: unresolved or terminal-external call.
- Negative: full protected literal or protected-slot load reaches EAX.
- Negative: raw-successor mismatch.
- Currentness: the memo is query-local and a fresh query recomputes.
- Retail: `0x44364a` is accepted only through the generic protected-free
  transfer proof; the complete `0x435620` root replay must progress or close.

## Scope

Only `tools/mwcc_retro/x86_cfg.py` and
`tools/melee-agent/tests/test_retro_x86_cfg.py` may change.  No Task 5–8 schema,
retail allowlist, artifact format, or resolver behavior changes.
