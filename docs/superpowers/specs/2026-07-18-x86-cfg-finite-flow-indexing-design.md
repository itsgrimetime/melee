# Exact x86 CFG Finite-Flow Indexing Design

## Goal

Reduce the wall-clock cost of the exact GC/1.2.5n whole-PE control-flow
closure without changing any recovered instruction, edge, table, producer
certificate, proof rule, cap, diagnostic, or fail-closed decision.

## Evidence

A five-second sample of the exact replay showed one active Python thread at a
full core.  The dominant work was recursive finite-value analysis and repeated
Capstone/Python object access.  Exact logs attributed roughly 1,682 seconds of
pass 31 and 1,281 seconds of pass 33 to the finite-value resolver, while decode,
block construction, and the other resolvers together took tens of seconds.
The pathological `0x408d4e` transfer repeatedly invalidated a dependency set
of more than 3,100 functions.

The implementation already maintains a sorted per-function instruction-address
index.  Several affine-loop and dominating-guard helpers still sort or scan the
whole instruction map when they need only one function's address range.

## Chosen Approach

Reuse the existing sorted/bisected per-function instruction-address index in
the finite-flow helpers that currently perform global scans.  Keep their
control predicates, decode ownership checks, traversal order, caps, and return
values unchanged.

The first implementation is limited to:

- affine-loop register-definition and value analysis;
- dominating nonzero/equality guard candidate scans; and
- a shared internal range-iteration helper only when it is a mechanical reuse
  of the existing index.

This change does not add dependency-keyed finite-domain memoization, persist a
closed CFG snapshot, change the producer-certificate schema, or alter the
durable analysis-semantics identifier.  Those are separate future designs.

## Correctness Invariants

- Indexed iteration returns the same addresses in the same numeric order as
  the reference whole-map filter for every function boundary and sparse range.
- Interior, missing, or foreign-function addresses are neither added nor
  removed.
- Cap accounting and high-water values remain identical.
- Producer certificate query/digest semantics remain identical, so existing
  exact certificates may be reused.
- Exact CLI output must retain the known closure of 362,835 instructions,
  97,552 blocks, 156,219 edges, and 564 tables and must publish byte-identical
  canonical artifacts on repeated runs.

## Test Strategy

Use test-driven development:

1. Add focused adversarial fixtures comparing indexed range iteration with the
   current reference filter across empty, boundary, sparse, and neighboring
   functions; observe the test fail before production changes.
2. Add or extend finite-loop and dominating-guard regressions so the optimized
   helpers recover exactly the same targets and diagnostics.
3. Run the full Task 4 focused suite, Ruff, `py_compile`, and `git diff --check`.
4. Compare the next exact CLI generation against the already validated exact
   closure and canonical bundle.  Any semantic delta rejects the optimization.

Performance measurements are diagnostic only and are not asserted with flaky
wall-clock thresholds.  The optimization is retained only if profiling shows
a material reduction in the targeted scans.

## Isolation and Rollback

Implementation and focused tests run in a separate temporary Git worktree so
the active authoritative CLI replay continues entirely from its already loaded
source.  After review, the small commit is applied to the canonical issue
branch only at a durable replay boundary.  If tests, exact counts, certificate
validation, or canonical bytes differ, the commit is not promoted.
