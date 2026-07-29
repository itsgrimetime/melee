# Exact x86 CFG Semantic Memo Performance Design

Date: 2026-07-28

Status: Approved by the standing autonomous handoff for issue #1240

## Goal

Reduce the wall-clock, memory, and restart cost of the retail GC/1.2.5n
whole-PE producer proof without changing any instruction, edge, target,
dependency, proof rule, cap, diagnostic, fail-closed decision, or canonical
artifact.

The immediate acceptance case is the remaining Task 4 object-byte producer
query rooted at `0x0046FA24`. The same implementation must accelerate the
ordinary `recover_cfg` producer-checkpoint workflow used by
`probe-backend-map --static-only`; it must not remain a diagnostic-only
shortcut.

## Measured Evidence

The exact-call readable-global memo reached 422,307 entries. Loading the
original append journal expanded to an 80 GB process footprint on a 16 GB
machine, filled nearly all swap, and caused severe paging. Only about 2.7 GB
was resident because macOS compressed and swapped the rest.

The apparent entry count hides extreme structural duplication:

- all 422,307 live entries use only 142 distinct dependency tuples;
- an intermediate normalized database retained 163 dependency rows because it
  also contained 21 dependency versions superseded by later values for the
  same semantic key;
- dependency-interned in-memory loading completed in 373 seconds with a
  5.5 GB peak footprint and no additional swap;
- a normalized SQLite prototype stored all 422,307 entries in 368 MB and
  converted them in 753 seconds with a 1.2 GB peak footprint;
- prototype SQLite lookup cost was approximately 476 microseconds for a cold
  entry and 75 microseconds for a hot entry.

Sampling the active proof also found repeated Capstone decode, reachability,
stack-state, and read-before-write work. Increasing the decode LRU from 1,024
to 32,768 entries reduced decode churn, but it did not remove the dominant
semantic recursion. Those secondary helpers are optimization candidates only
after the memo redesign is measured end to end.

## Approaches Considered

### Selected: pooled in-memory dependencies with a normalized persistent store

Canonicalize equal dependency tuples so every memo entry references one shared
immutable tuple. When `recover_cfg` receives a `producer_checkpoint_dir`, back
the exact-call readable-global memo with a versioned normalized SQLite store
and a bounded in-process LRU. Reuse the store across the current recovery,
hypothesis trials, bounded producer restarts, and later invocations using the
same checkpoint directory.

This approach gives the in-memory path the simplest high-value reduction while
also preserving nested semantic work across restarts. The persistent store is
an acceleration cache only. Every hit still passes the existing exact image
hash and dependency-fingerprint validation before it can influence proof.

### Rejected: dependency interning alone

Interning cuts the measured footprint from 80 GB to 5.5 GB and should preserve
dictionary-speed lookup, but it still retains hundreds of thousands of keys
and results in memory and loses nested work when a bounded producer run exits.
It is a useful first implementation step, not the complete long-run design.

### Rejected: bounded memory-only LRU

An LRU would cap memory but evict expensive exact-call summaries. The current
query revisits long caller contexts, so eviction would trade a memory failure
for repeated multi-hour computation and would not improve restart behavior.

### Rejected: diagnostic-only persistence

The diagnostic prototype proves feasibility but cannot help the branch-local
static CLI or future exact proofs. Issue #1240 needs the production recovery
path to remain tractable through its final replay.

## Architecture

### Internal memo-store boundary

Introduce a private readable-global memo-store boundary with the operations
actually required by `_DirectCfgRecovery`: `get`, `put`, `len`, and `close`.
The analyzer continues to consume and produce `_DependencyMemoEntry` values.
No proof caller can distinguish whether an entry came from memory or disk.

Small recoveries and unit tests use an in-memory implementation. It interns
dependency tuples before publication and after retrieval. `recover_cfg`
creates one store and shares it with every `_DirectCfgRecovery` constructed
during the accepted/rejected callback-hypothesis fixed point.

When `producer_checkpoint_dir` is present, `recover_cfg` opens one persistent
store beneath that directory and closes it in a `finally` block. The existing
top-level producer-certificate files remain authoritative completion
certificates; the nested store does not replace or relax them.

### Canonical pooled representation

One dependency pool maps an immutable dependency tuple to its canonical tuple
object. Every entry published to an in-memory cache or reconstructed from disk
uses the canonical object. Pooling is equality-preserving and cannot merge
different fingerprints.

The persistent representation is normalized into:

- metadata binding schema, compiler SHA-256, and an explicit semantic-version
  identifier;
- a dependency table keyed by SHA-256 of canonical dependency JSON;
- a memo table keyed by SHA-256 of canonical semantic-key JSON and containing
  the exact canonical key bytes, dependency digest, and result payload.

The memo key contains the explicit readable-global analysis semantic version,
call target, slot, field path, exact call-context signature, summary-fact
signature, and control-flow revision. A semantic implementation change must
bump that version. Representation-only changes do not need to discard valid
entries.

Payloads use strict canonical JSON, optionally compressed as opaque bytes.
Production code does not unpickle persistent data. On lookup it verifies the
key digest and exact key bytes, decodes only the expected schema, reconstructs
an immutable `_DependencyMemoEntry`, interns its dependencies, and then runs
the existing `_dependency_memo_hit` check.

### Transactions and recovery

SQLite uses bounded page cache, WAL journaling, and explicit transactions.
Each completed semantic summary is durable before `put` returns. Metadata is
created transactionally before any rows are visible.

A missing database starts empty. A schema, compiler-hash, semantic-version,
canonical-payload, or SQLite-integrity mismatch fails closed with a specific
`CfgRecoveryError`; it is never treated as proof. The operator may remove an
invalid acceleration cache and recompute, but the analyzer does not silently
reinterpret or migrate it.

The store is local checkpoint state and never enters the nine-file canonical
proof bundle, manifest, or promotion tuple. Canonical proof outputs therefore
remain independent of cache layout, page order, timestamps, and host paths.

### Bounded hot state

The persistent implementation keeps:

- all distinct dependency tuples in one intern pool;
- a configurable but deterministic-count LRU of recently used memo entries;
- SQLite's page cache under an explicit memory bound.

The default LRU is sized from a fixed constant, not host memory detection, so
analysis behavior and cap accounting remain reproducible. Cache eviction only
changes performance because the durable row remains available.

## Secondary Optimization Phase

After the memo-store benchmark passes, profile the same focused Task 4 query.
Apply only optimizations with measured material impact:

1. make the decoded-instruction LRU size a per-recovery setting and use a
   larger fixed value for whole-PE checkpointed recovery if its measured
   memory cost remains bounded;
2. cache immutable reachability/successor, function stack-state, and
   read-before-write queries using keys that include every controlling
   revision or fact signature;
3. retain the existing dependency-fingerprint cache and bounded provenance
   representation after their focused regressions pass.

Each secondary change is a separate commit and benchmark. No speculative cache
is added merely because a helper appears frequently in a stack sample.

### Bounded producer-query batching

The exact Task 4 replay exposed a separate orchestration cost after the focused
memo workload was closed: the production CLI allowed only one new producer
query per process. Every query was checkpointed atomically, but every process
still rebuilt and replayed the shared whole-image fixed point before exiting.

The production CLI therefore evaluates at most 128 new producer queries per
process. The first production batch demonstrated that 32 queries could be
consumed by an intermediate fixed-point wave before the final 24-query wave;
128 covers several such waves while remaining explicitly bounded. This
changes no query, dependency, certificate, or proof semantics.
Each certificate is still written atomically immediately after its query
finishes, and any process that completed a query must still exit through
`ProducerCheckpointIncomplete` so the next process independently validates the
new certificates before publication. The external three-hour timeout remains
the wall-clock bound; an interruption can lose only the currently evaluating
query.

The batch size is a fixed source constant rather than host-derived or adaptive,
keeping work scheduling reproducible while amortizing whole-image setup across
enough queries to be material.

### Relocated-dispatch write-overlap index

Production phase timing then isolated a 374-second relocated-dispatch
bootstrap pass over 20,925 tentative slots. The scan tested every slot against
every known absolute write, repeatedly decoding the same writer instructions.

Build the exact owned-write interval set once per bootstrap pass, sort it by
start, and retain the maximum end seen at every prefix. A slot overlap query is
then one binary search plus one integer comparison. Half-open interval
semantics, global-slot treatment, operand filtering, candidate ordering, caps,
and all accepted or rejected hypotheses remain unchanged.

### Finite-control query indexes

A bounded 420-second `cProfile` sample of the resumed production workload
showed that the remaining runtime was dominated by repeated whole-function
graph traversals inside finite-control semantic queries. Four exact
optimizations were retained:

- compute the forward and reverse reachability regions once when proving a
  saved constructor receiver instead of issuing one reachability search per
  instruction;
- reuse a completed intrusive-list proof from unrelated recursive contexts,
  while never bypassing a cycle containing the queried function;
- skip the direct intrusive-list dataflow matrix when the function contains no
  instruction with the necessary exact link-store shape, while preserving
  wrapper analysis;
- index the cumulative direct-call dependency prefix once per exact
  function/fact/revision key instead of rescanning the function for every stack
  dependency query.

The same 420-second sample advanced from pass 18 to pass 27 after these
changes. The saved-receiver helper fell from 126.55 seconds to 4.91 seconds,
and stack call-dependency collection fell from 45.6 seconds to 3.0 seconds.
An attempted cache for stack-state graphs stopped at semantically open calls
was rejected: the complete x86 CFG suite demonstrated that call closure can
change without the proposed structural cache key changing. The original
fail-safe behavior remains.

### Audited decoded-instruction cache hits

The retained 420-second profile also recorded 27,095,881 calls to
`_owned_decoded`, with 48.04 cumulative seconds spent retrieving an
instruction and rechecking its size and byte string. Every cache entry is
already checked when it is first claimed from the immutable PE image, or when
an evicted entry is decoded again. Repeating the same conversion and
comparison on every hit adds no new evidence.

Trust an instruction while it remains in the private decoded-instruction
cache. Preserve the full size and byte check on every cache miss before the
new decode is inserted. A same-process microbenchmark of two million cached
lookups reduced the best lookup cost from 568.2 ns to 142.9 ns (4.0x). The
instruction record, image bytes, cache eviction behavior, and all proof
artifacts remain unchanged.

The same immutable-address fact also permits a local cache of Capstone group
membership. The profile spent 42.00 cumulative seconds across 50,958,337
`group()` calls, of which 25.80 seconds were repeatedly materializing the
same `groups` property. Cache the exact group set lazily per owned instruction
address and use it in the eight hottest whole-function traversals. Those
callers accounted for about 44.6 million (87.5%) of the profiled group calls.
A two-million-lookup microbenchmark reduced one cached membership query from
558.6 ns through Capstone to 197.5 ns through the helper; traversals that fetch
the set once use direct membership for their remaining classifications. The
cache stores only Capstone's exact group IDs and never infers an instruction
class.

### Indexed accepted seed provenance

The current whole-PE profile found 452 incoming-call-domain queries spending
6.32 cumulative seconds rebuilding the accepted relocation-provenance set by
scanning every seed record. The recovery already maintains an exact,
revision-keyed seed-record index by target address for producer
fingerprinting. Incoming-call closure can query that index for the one
function target and apply the same category filter without changing the
accepted set.

On the captured 24-transfer exact query batch, this substitution reduced the
profiled wall time from 105.96 seconds to 99.56 seconds (6.0%) with identical
resolver results, approximately 2.7 GB maximum RSS, and no swap. A regression
prewarms the index, forbids iteration over the complete seed set, and requires
the same incoming-domain result.

### Call-free pushed-argument cache

The same exact profile made 869,166 calls to the backward pushed-argument
scanner, primarily while auditing the global intrusive-list producer. A
successful or terminal scan that encounters no earlier call depends only on
the immutable owned instruction chain and current function-entry partition.
Cache those results for the current summary-fact signature, clear the cache
when that signature changes, and replay producer-dependency collection on
every hit. Do not cache a traversal that crosses another call, because its
stack cleanup can depend on evolving call closure.

After the seed-index change, this cache reduced the identical profiled batch
from 99.56 seconds to 95.19 seconds (4.4%) with identical resolver outcomes,
approximately 2.68 GB maximum RSS, and no swap. Regressions require reuse of a
call-free result and explicitly forbid caching across a call cleanup.

### Indexed guarded-allocation call lookup

The next profile found 4,880 guarded fresh-receiver checks spending about
5.3 self seconds locating a call by linearly scanning the approximately
26,000 recovered direct calls. Recovery already maintains the exact source
address to direct-target index used throughout the remaining analysis. The
guarded receiver check needs only to establish that the preceding instruction
is an accepted direct call and to preserve its source address, so it can use
that index without reconstructing a `DirectCall` row.

This substitution reduced the identical profiled batch from 95.19 seconds to
89.69 seconds (5.8%), for a cumulative 15.4% reduction from the corrected
105.96-second baseline. Resolver outcomes remained identical, maximum RSS was
approximately 2.50 GB, and no swap occurred. A regression replaces the
complete direct-call set with an iteration-forbidden set and requires the
guarded fresh-allocation identity to remain exact.

## Correctness Invariants

- Cache-disabled, cold-cache, warm-cache, and evicted-cache runs return equal
  `_DependencyMemoEntry` values and equal final CFG artifacts.
- Every persistent hit is revalidated against the exact compiler hash and
  current dependency fingerprints.
- Key hashing cannot substitute for key equality; exact canonical key bytes
  must also match.
- Dependency interning preserves tuple contents, order, and immutability.
- Cache state does not alter dependency collection, high-water accounting,
  analysis caps, recursion/induction rules, or diagnostic ordering.
- Failed, stale, corrupt, or semantically mismatched cache rows cannot become
  proof facts.
- No absolute host path, timing value, database metadata, or cache digest
  enters canonical proof output.
- The six previously triaged executable relocation obligations retain their
  exact dispositions; no seed, ownership, or relocation rule is weakened.

## Testing

Use test-driven development.

1. Add unit tests proving equal-but-distinct dependency tuples are interned
   while unequal tuples remain distinct.
2. Add store round-trip tests for finite and blocked results, cold/hot lookup,
   LRU eviction, reopen persistence, and sharing across recovery instances.
3. Add adversarial tests for key-hash mismatch, exact-key mismatch, duplicate
   JSON keys, malformed values, wrong image hash, wrong semantic version,
   stale dependency fingerprints, SQLite corruption, and interrupted
   transactions.
4. Run the relevant object/global/caller-chain regressions and compare their
   full values and semantic provenance markers with the cache disabled and
   enabled.
5. Run the complete x86 CFG, backend lifetime audit, backend CLI, and Ghidra
   setup suites, followed by Ruff, `py_compile`, and `git diff --check`.
6. Resume the exact `0x0046FA24` query from the converted diagnostic state,
   then repeat from the production store. Require the same result.
7. Run the exact Task 4 closure twice and compare all canonical outputs
   byte-for-byte.

Performance measurements are diagnostic gates rather than timing assertions in
unit tests.

## Performance Acceptance

On the current 16 GB host:

- no proof process may exceed an 8 GB physical footprint or increase swap use
  during the focused query;
- normalized persistent checkpoint storage should remain below 2 GB for the
  observed 422,307-entry workload;
- a warm restart must avoid the previous 80 GB expansion and must reach
  semantic evaluation without a multi-minute full-cache hydration;
- the first cold run may pay durable-write overhead, but it must not regress
  the measured focused workload by more than 10 percent unless the same run
  eliminates a later bounded restart by checkpointing completed summaries;
- a warm run must materially improve wall-clock time over recomputing the same
  nested summaries.

If the persistent implementation misses these gates, retain dependency
interning and revise the backing representation before resuming the long exact
replay.

## Rollout and Rollback

Implement dependency pooling first and verify it independently. Add the
persistent store behind the existing `producer_checkpoint_dir` boundary and
benchmark it before enabling secondary optimizations. Keep each phase in a
separate commit so a performance regression can be reverted without removing
correctness work.

The ignored diagnostic SQLite database may seed comparison experiments, but it
is not trusted or promoted into the production cache format. Production rows
must be generated or independently decoded and revalidated by the production
store.
