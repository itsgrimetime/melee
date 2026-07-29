# Issue #1240 Progress Ledger

Last reconciled: 2026-07-28, replacement root orchestration.

## Durable foundation

- Tasks 1-3 remain complete at `ea3d1ca65..660606143`.
- Branch: `codex/issue-1240-retail-pcode-proof`.
- The committed foundation includes the verified finite-control and audited
  decoded-instruction cache checkpoints.
- The installed `gc_125n.json` PCode instrumentation gate is still disabled and
  the exact proof registry is still empty, as required before promotion.

## Task 4: exact raw CFG/control closure

In progress.  The committed implementation and current repair diff now recover
the retail raw PE closure, reconcile executable residue, and close several
additional indirect-flow families.  The authoritative producer-quiescent
diagnostic replay contains 360,322 instructions, 96,910 blocks, 155,292 edges,
26,000 calls, 3,242 functions, 564 jump tables, and all 28,783 raw `E8`
candidates partitioned.

- Receiver-sensitive object/stream family: exact 23-site slice closed.  The
  29-entry callback table at `0x54d050`, 19 object calls, and 3 stream calls all
  have finite targets with zero blockers.
- Movzx producer-domain family: implementation/tests and quiescent fixed-point
  regression are green; 1,168 durable producer certificates have been
  checkpointed.  The current exact certificates prove association/readability
  but conservatively admit byte values `0..255`; the 30 index-75 blockers need
  a closed lifecycle proof before they can use the retail `0..74` table bound.
- The exact diagnostic frontier contains 75 obligations: 36 computed-flow
  blockers (30 movzx, 3 constructor-descriptor, 2 registered-static
  helper-result, and 1 registered-linked callback), 32 raw indirect calls,
  1 object-callback-table blocker, and the 6 independently triaged residue
  relocation obligations.
- The six relocation obligations remain exactly the reviewed set at
  `0x401d37`, `0x401d97`, `0x425b27`, `0x4e0ae7`, `0x50652f`, and `0x50f5b3`.
  Five are exact decoded calls/pushes in provisional residue; `0x50652f` is
  the exact retail Ninji marker text and not code.
- A read-only hydrator reconstructs the persisted exact graph plus its derived
  write indexes in about 12 seconds and answers whole blocker batches without
  replaying CFG discovery.  It identified four global-stack calls whose
  already-proved sibling byte guard selects the sole nonzero callback.  The
  resolver integration is green in 950 x86 CFG tests and resolves exact-state
  addresses `0x4d03e6`, `0x4d099b`, `0x4d131a`, and `0x4d24b7`; a fresh exact
  replay still must confirm the frontier delta.
- Finite argument domains now distinguish current least-reachable callers from
  raw `E8` bytes in provisional residue.  Every excluded raw caller is retained
  as a `provisional-unowned-raw-caller` obligation in the exact partition;
  ownership growth reopens the domain, and publication still requires exact
  residue/Ghidra reconciliation.  Positive and promoted-hostile tests are
  green.  Exact-state hydration now also resolves the recursive callback calls
  at `0x44c96e` and `0x44c9db`, for six locally demonstrated blocker closures
  total before replay.
- A stack-local callback proof now accepts only one exact four-byte write that
  dominates the indirect transfer, rejects bypasses, intervening calls,
  overlapping pushes/writes, and possible pointer aliases, and requires every
  loop re-entry to pass through the write again.  Positive and hostile tests
  are green.  Exact-state hydration proves the saved callback at `0x4d1bba`
  has the finite domain `{0}`; its dominating nonzero guard therefore makes
  the transfer unreachable.  This raises the locally demonstrated exact
  blocker closures to seven before replay.
- Re-running the global-slot resolver against the hydrated exact graph after
  the least-reachable caller-domain fix closes `0x4743e3` without any new
  correlation rule.  Its loader-zero slot now has four proved nonzero callback
  values supplied by the closed registrar argument domain.  This raises the
  locally demonstrated exact blocker closures to eight before replay.
- The registered-static command proof now follows a helper result through a
  guarded merge with literal zero, provided the same reaching-definition set
  is tested and passed to the descriptor consumer.  It validates only the
  producer's calls to the pure lookup helper while retaining a closed domain
  for every direct helper caller, so unrelated read-only lookup users do not
  invalidate the graph.  Positive and hostile fixtures are green, and exact
  hydration closes `0x42a1aa` and `0x42a304` with 16 and one relocated callback
  targets respectively.  This raises the locally demonstrated exact blocker
  closures to ten before replay.
- The fourth exact continuation completed 128 queries in 3,232.45 seconds at
  5.27 GB maximum RSS with no swap, then exposed a further 24-query wave.
- The retained finite-control indexes advanced the same 420-second profiled
  workload from pass 18 to pass 27. An unsafe partial stack-state cache was
  found by the full suite and removed before checkpointing.
- The next comparable continuation completed 128 queries in 2,343.54 seconds:
  888.91 seconds (27.5%) faster, or 1.38x throughput. The following four-query
  continuation completed in 2,323.89 seconds, establishing a practical
  current-architecture replay floor of about 38-40 minutes.
- A clean producer-quiescent replay then reached final publication validation
  in 2,425.01 seconds. All producer certificates were fresh, but 69 downstream
  raw control transfers remained fail-closed.
- The exact diagnostic replay completed in 2,303.13 seconds (38m23s) at
  5.30 GB maximum RSS with no swap and persisted the complete 75-obligation
  frontier above.  Compared with the 3,232.45-second continuation, this is
  28.8% less wall time, or 1.40x throughput.
- The next exact optimization trusts already-audited decoded cache hits and
  memoizes Capstone's immutable instruction-group set in the eight measured
  hot traversals. Microbenchmarks improved cached decode lookup by 4.0x and a
  cached group query by 2.8x; the 1,075-test adjacent slice remains green.
- Incoming-call closure now reuses the existing revision-keyed seed-record
  address index instead of scanning the complete seed set for every target.
  The identical exact 24-transfer profile improved from 105.96 seconds to
  99.56 seconds (6.0%) with identical outcomes, about 2.7 GB maximum RSS, and
  no swap.
- Backward pushed-argument scans now cache only call-free completed results
  for the current summary-fact signature and preserve dependency collection
  on hits; traversals crossing another call remain uncached.  The same profile
  improved again from 99.56 seconds to 95.19 seconds (4.4%), with identical
  outcomes, about 2.68 GB maximum RSS, and no swap.
- Guarded fresh-receiver checks now use the existing exact direct-call source
  index instead of linearly scanning approximately 26,000 recovered calls.
  The same profile improved from 95.19 seconds to 89.69 seconds (5.8%), or
  15.4% cumulatively from the corrected 105.96-second baseline, with identical
  outcomes, about 2.50 GB maximum RSS, and no swap. This closes the bounded
  optimization gate; the active lane returns to exact Task 4 proof closure.
- Exact hydration demonstrated that the valid `0x54d050` object-callback table
  hypothesis reproduces by itself and adds 29 function roots without exposing
  new indirect transfers.  It was nevertheless rejected when replayed in the
  same trial as 2,250 unvalidated relocated-bootstrap candidates, because the
  unrelated expansion polluted the reproduction check.  Fixed-point recovery
  now trials precise object and copied-descriptor hypotheses individually
  before retaining the existing batched bootstrap trial.  A hostile
  cross-candidate regression test, the 963-test CFG suite, and the 1,090-test
  adjacent Task 4 slice are green; a fresh exact compiler replay is next.
- The staged exact replay completed in 4,365.81 seconds at 6.42 GB maximum RSS
  with no process swaps.  All ten implemented local closures survived, reducing
  the prior 69-address raw-control frontier to 60 addresses.  The replay also
  exposed one additional constructor obligation at `0x41c098`, but retained
  the object-table blocker at `0x425a59`.
- The replay proved that the same object table could acquire additional
  consumers after graph growth, changing the prior replay identity even though
  its table/store/field/receiver/record provenance was unchanged.  Object
  identity is now based only on that stable provenance.  Any changed consumer
  evidence refreshes the accepted hypothesis and forces a clean rerun before
  its evidence can be consumed, rather than reusing stale subset evidence.
  The hostile consumer-expansion regression, the 964-test CFG suite, and the
  1,091-test adjacent Task 4 slice are green.
- The stable-identity exact replay completed in 4,068.11 seconds at 6.09 GB
  maximum RSS with no swaps.  Its final accepted object-plus-copied-descriptor
  graph is stable at 363,420 instructions, 97,858 blocks, 156,726 edges, and
  564 jump tables.  The `0x54d050` object-table hypothesis now survives its
  mandatory clean replay and closes `0x425a59`; the expansion exposes no new
  indirect-control obligations.  All ten earlier local closures also remain
  closed.  The exact raw-control frontier is now 59 addresses: 24 remaining
  raw indirect transfers, four constructor-descriptor transfers, 30 movzx
  lifecycle transfers, and one registered-linked callback.
- The remaining registered-linked callback at `0x4c7ad1` is now traced through
  the loader-zero `0x587c74` registry, its main-node/object intrusive lists,
  the `0x49d060` list publisher, and the central object constructor at
  `0x4a2660`.  The constructor stores the exact signed head index to object
  `+0x14` before filling a variable-length tail at `+0x1c`.
- Fresh-allocation field proof now accepts a finite dynamic allocation-size
  interval, extracts bytes from closed multi-byte register stores, and uses a
  fail-closed lower/upper alias bound when an exact loop-offset set would grow
  to the summary cap.  On the retail constructor this proves that the exact
  `0x22` index survives every later tail-fill path without weakening the
  ordinary exact-offset proof.
- Allocation-pointee summaries now carry a finite secondary object argument
  through a closed association-field publication.  This covers the retail
  publisher's two `outer->tail = object` arms while rejecting an open source
  field or later unproved mutation.  Focused hostile regressions and the full
  974-test x86 CFG suite pass.  A fresh exact replay is still required to bind
  all publisher callers, allocator-session totality, and the two raw call
  sites that become owned only after graph expansion.
- Constructor-field closure now combines collectively path-covering writes,
  follows every nullable call-return field origin through a register-only
  epilogue restore, and recognizes both arms of the retail nonzero allocation
  guard.  The field proof remains fail-closed when a branch bypasses all
  writes, a return is unknown, or a guarded arm admits an unknown receiver.
- The remaining constructor input is now proved through the private
  loader-zero intrusive registry rooted at `0x57d91c`.  The insertion cursor
  is restricted to that head and node `+0x10` links, every published node
  comes from the closed zero-field record constructor, and point-specific
  nullable-node dataflow rejects an unknown alternate definition.  Hydrated
  retail diagnostics prove `EBX` at `0x4098f6` has the registered zero-field
  origin and that the field at `0x417546` has exactly the target `Pars`
  constructor plus the already rejected `cldr`, `Comp`/`Link`, zero, and null
  alternatives.  The 984-test CFG suite and 1,111-test adjacent Task 4 slice
  are green; a fresh exact replay with this checkpoint is still required.
- Relocated dispatch bootstrap replay now isolates candidates by transfer
  table while keeping every slot for one table in the same trial.  Previously
  all 2,250 tentative slots from 30 independent transfers were seeded
  together, so one invalid table could suppress otherwise reproducible
  neighbors.  A hostile two-table regression proves that an invalid first
  table is rejected cleanly and a valid second table remains accepted.
- Returned-fresh constructor proof now binds scalar argument bytes to exact
  stores, requires the allocation extent to cover every observed field, and
  rejects later overlap, pointer escape, indexed aliases, or an open size.
  The retail variadic constructor contract is closed across all 241 wrapper
  callers: only the two `#` format tags consume the variable width, their
  signed-word guards bound it, and the resulting allocation remains within
  `0x28..0x60c1c`.  The full CFG file is 999 passing tests and the adjacent
  Task 4 slice is 1,126 passing tests; scoped Ruff, `py_compile`, and
  `git diff --check` are green.
- The remaining tag-1 constructor widths are closed over the retail signed
  global-word network.  All relocated references must be direct accesses;
  every overlapping writer must be an exact whole-word immediate, a
  straight-line word copy, or the bounded `0x20 - selected_counter` loop
  shape.  The cyclic copy component
  `{0x581370,0x5883ea,0x588438,0x58843a}` has the exact nonnegative interval
  `0..18`, and all four formerly open wrapper callsites now prove constructor
  byte `{1}`.  Unknown writers, partial overlaps, and address escapes remain
  blocked.  A dependency-aware cache replays every slot and writer-function
  dependency without rescanning the network for each caller.
- Returned-fresh clone proof now covers both allocation arms of `0x49d270`,
  proves the indexed `+0x1c` tail remains disjoint from copied header fields,
  binds the signed source count to the dynamic allocation extents, and closes
  the central variadic constructor's copied count bytes.  Negative or unknown
  indices, high-bit signed counts, overlap, and pointer escape remain blocked.
- Forwarded object-byte caller closure now applies the existing
  `provisional-unowned-raw-caller` residue policy consistently with scalar
  domains.  The two raw `E8` patterns outside current function ownership are
  deferred to final unreachable-residue reconciliation, while promoting
  either byte into executable ownership immediately reopens the proof.
- The next decoded publisher caller at `0x463470` is isolated.  Its
  three-arm constructor `0x463640` now proves the copied source tag through a
  saved `ESI` result, dominating whole-object initialization, and the exact
  nonnegative tail writer `0x4a2290`.  Hostile negative-offset writes,
  post-copy initialization, pointer publication, and used return aliases are
  rejected.  The remaining blocker is now only the dynamic allocation extent
  on two of the constructor's three arms; the third arm already proves
  `0x28..0xc34`.
- Bounded allocation arithmetic can now consume an explicitly certified
  interval from one exact helper call.  Uncertified or duplicate calls, invalid
  ranges, caller-saved inputs, stack-memory assumptions across the call, and
  arithmetic wrap remain fail-closed.  The retail helper at `0x4bc7b0` now has
  a checked list-counter shape: argument 0, link field `+0`, a zero-initialized
  callee-saved counter, and at most two increments on every single-node path.
  The remaining linked-count obligation is the separate provenance/stability
  certificate showing that every reachable node belongs to the fixed-size
  allocation family; only then can its address-space bound be supplied as the
  helper-return interval.

Task 4 is not complete until a fresh exact-hash raw/Ghidra replay has zero
current blockers, an accepted reconciliation certificate, and a published
transactional generation.

## Task 5: bounded values/types

Implementation exists at `1de0a5216` plus current repairs.  It now produces
canonical dependency, alias-write, transitive lifecycle/helper-effect, and
final-emission certificates.  Formal dependency rebinding, must-write
dominance, typed encoder/result/buffer/range/relocation/machine-field evidence,
and closed pseudo-op disposition are implemented.  Task 5 cannot be closed
independently of the final Task 4 control-target result; a fresh exact replay
follows Task 4 closure.

## Task 6: lifetime/site closure

In progress.  The inventory includes every raw `E8` arena and unlink candidate,
distinguishes reachable-owned calls from accepted unreachable residue, and
fails closed on uncertified residue.  Reviewed addresses are regression anchors
only: they no longer create ObjObject, unlink, mutation, reuse, or emission
acceptance.  Task 5/6 + CFG/PE validation is 589 passing tests with scoped
static checks green.  A fresh exact whole-PE replay and zero relevant unresolved
rows remain required.

## Task 7: opcode proof and canonical bundle

Implementation-complete pending exact inputs.  The schema models exact retail
custom/variadic constructors, count-driven BL/BLRL tails, flags-driven roles,
and evidence-derived register domains; reachable BCTRL remains fail-closed
without a proved producer.  Production consumers use the closed role resolver.
The CLI now constructs and transactionally publishes the canonical nine-member
generation.  Task 7 proof/lineage/map/runtime/CLI validation is 508 passing
tests.  The tracked proof/hook files remain placeholders and must not be
promoted until the exact run is ready and byte-identical twice.

## Task 8: runtime bundle and lifecycle hooks

Implementation-complete pending the exact Task 7 proof.  Strict compiler/table/
proof/manifest loading, independent breakpoint/source re-decoding, nested-safe
lifecycle generations, exact all-or-nothing installation, shared map/PCode/
one-pass wiring, and PCode `--instrumentation-table` support are implemented.
Validation: 184 focused and 533 adjacent tests pass; a real installed-default
check returns controlled `unpromoted` against the exact compiler.

## Task 9: atomic events and live-probe selection

Implementation-complete pending an exact candidate proof.  Atomic rewrite,
mutation, and emission capture; lifecycle/lineage serialization; exact cap,
drop, truncation, and error finalization; retained PPC parity objects; bounded
observed-feature probe selection; and per-run/union validators are implemented.
The runtime stack-argument decoder now correctly reads argument zero at
`ESP+4`, not the return address at `ESP`.  Validation: 366 focused and 829 broad
adjacent tests pass.  No live probe claim has been made.

## Task 10

The four old exploratory probes are not proof-bound promotion runs.  Task 10
still requires two byte-identical exact generations, tracking the reviewed
proof/hooks, four exact live probes, exact tuple promotion, broad verification/
review, coherent commits, merge to `master`, installed-CLI replay, issue
resolution, and final queue refresh.

## Current verification

- Task 4 now has a scoped fresh-intrusive-list bound: it rejects stack,
  open-link, missing-storeback, and unwitnessed-empty lists; requires one
  owned monotonic allocator; evaluates every exact request through the
  allocator's unavoidable normalization; and bounds a `0x20`-stride arena at
  `0x08000000` live nodes.
- The loader-zero global scratch transformer is closed with exact
  caller/lifetime context.  Global-append summaries now exclude calls after
  the guarded observation, return direct scalar discriminator tags, accept
  only dominating whole-field empty overwrites, retain optional-empty
  association evidence, and admit selected clones only for their exact scalar
  tag query.  Hostile post-observation writes, selected-clone payload reads,
  malformed storeback, and context-sensitive memo reuse remain rejected.
- Hydrated retail progress for the tag-16 dispatcher now closes publications
  through `0x477c9d`; the selected-clone scalar extension targets the next
  former tag blocker at `0x477e5c`.  Payload publication `0x4767ce` closes as
  optional-empty after its dominating null overwrite.  The next observed
  payload blocker is `0x4776dd`, whose source reaches the current-object
  restoration at `0x477844`.
- The next repair is a narrow heap-context save/restore identity certificate:
  bind one fresh context node, its exact save from the current-object global,
  its closed head/tail-list publication, every list reader's preservation of
  the saved field, and the exact later restore.  Unknown field overlap, node
  escape, malformed list publication, or an unclosed reader must fail closed.
  After that, rerun the retail dispatcher query, close the two remaining
  constructor allocation arms, close parent `0x49d060`, and perform the fresh
  run-018/reconciliation/adversarial review.
- Context-sensitive producer summaries now bind the complete exact-call stack
  in their memo keys and propagate nested call contexts.  This prevents one
  caller's finite argument value from contaminating another caller while
  retaining the original multi-caller union.
- `test_retro_x86_cfg.py`: 1,073 passed.
- Task 4 backend/struct-map adjacent slice: 830 passed.
- Task 5/6 + CFG/PE: 589 passed.
- Task 7 adjacent proof/runtime/CLI suites: 508 passed.
- Task 8 focused/adjacent suites: 184 / 533 passed.
- Task 9 focused/broad adjacent suites: 366 / 829 passed.
- Scoped Ruff, `py_compile`, and `git diff --check`: green for the touched
  Task 4-7 files.
