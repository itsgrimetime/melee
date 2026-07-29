# Issue #1240 Progress Ledger

Last reconciled: 2026-07-28, replacement root orchestration.

## Durable foundation

- Tasks 1-3 remain complete at `ea3d1ca65..660606143`.
- Branch: `codex/issue-1240-retail-pcode-proof`.
- Current committed foundation: `706d09df8`, the verified finite-control
  optimization checkpoint.
- The installed `gc_125n.json` PCode instrumentation gate is still disabled and
  the exact proof registry is still empty, as required before promotion.

## Task 4: exact raw CFG/control closure

In progress.  The committed implementation and current repair diff now recover
the retail raw PE closure, reconcile executable residue, and close several
additional indirect-flow families.  Current exact facts before the last two
families were integrated: 361,219 instructions, 97,168 blocks, 155,669 edges,
26,070 calls, 3,251 functions, 564 jump tables, and all 28,783 raw `E8`
candidates partitioned.

- Receiver-sensitive object/stream family: exact 23-site slice closed.  The
  29-entry callback table at `0x54d050`, 19 object calls, and 3 stream calls all
  have finite targets with zero blockers.
- Movzx producer-domain family: implementation/tests and quiescent fixed-point
  regression are green; 1,168 durable producer certificates have been
  checkpointed and the authoritative optimized exact replay is continuing.
- Remaining families after those two close: global-stack, constructor,
  nested-descriptor, helper-return, and linked-list targets.
- Full `test_retro_x86_cfg.py`: 947 passed. The adjacent Task 4 performance
  slice is now 1,074 passed with scoped static gates green.
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
  raw control transfers remain fail-closed. An exact diagnostic replay is
  persisting their current details before the next proof-family repair.

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

- `test_retro_x86_cfg.py`: 945 passed.
- Task 4 performance/CFG/backend/CLI/Ghidra slice: 1,072 passed.
- Task 5/6 + CFG/PE: 589 passed.
- Task 7 adjacent proof/runtime/CLI suites: 508 passed.
- Task 8 focused/adjacent suites: 184 / 533 passed.
- Task 9 focused/broad adjacent suites: 366 / 829 passed.
- Scoped Ruff, `py_compile`, and `git diff --check`: green for the touched
  Task 4-7 files.
