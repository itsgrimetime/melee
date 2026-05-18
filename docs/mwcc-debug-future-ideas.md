# mwcc_debug — future improvement ideas

The current tooling answers "which register did MWCC pick" and (with the
analyze command) "what were the constraints" — but not "why this register
specifically." These are notes on what we could build next to close that
gap. Not detailed designs; just enough that we don't re-derive the ideas
from scratch later.

## Tier 2 — hook MWCC's register-allocator entry point — ✅ DONE

Implemented in commit 17517fb08. Hook on `colorgraph` at VA 0x4CE2D0 in
mwcceppc.exe v1.2.5n. After the original runs, the hook walks the IGNode
linked list and emits a `COLORGRAPH DECISIONS` section to `pcdump.txt`
with per-virtual: iteration index, assigned physical reg, degree,
original interferer count, flags.

Critical finding from the hook: MWCC dispenses nonvolatiles **TOP-DOWN
from r31** (r31 → r30 → r29 → ...), not bottom-up from r27 as our
positional-alignment analysis had suggested. The simulator (Tier 1.5)
and algorithm docs have been corrected.

IGNode struct layout for v1.2.5n (different from 7.0!): see
`tools/mwcc_debug/mwcc_debug.c` or `docs/mwcc-allocator-algorithm.md`.

What we still don't capture: the **iteration order** within colorgraph
(determined by `simplifygraph`'s spill-cost-aware Chaitin-style
simplification). Adding a hook on `simplifygraph` would surface this.
Also the workingMask state per-decision is computed but not stored
across the loop — would need an in-loop hook (much more invasive).

## Tier 3 — hook IG construction + cross-ref 7.0 source — ✅ DONE

Implemented in commits described below. Two parts:

**A. 7.0 source cross-reference (done during Tier 2).**
We read `compiler_and_linker/BackEnd/PowerPC/RegisterAllocator/{Coloring,
InterferenceGraph,RegisterInfo}.c` from git.wuffs.org/MWCC. That established:
- The Chaitin-style coloring algorithm
- The TOP-DOWN nonvolatile dispense order (corrected our wrong hypothesis)
- IGNode structure layout (different offsets in 1.2.5n vs 7.0)
- Build pipeline: `buildinterferencegraph` → `simplifygraph` → `colorgraph` → `rewritepcode`

The Python simulator (`melee-agent debug simulate`) replays the colorgraph
algorithm based on this understanding.

**B. IG construction hook.**
Hooked `buildinterferencegraph` at VA 0x530A00 (9-byte prologue). After
construction completes, emits an `IG CONSTRUCTED (class=N, n_nodes=K)`
event line to pcdump.txt. This gives agents ordering visibility — they
can see exactly when each (function, register class) pair has its IG
constructed, paired with the subsequent COLORGRAPH DECISIONS section.

**Known limitation:** iterating `interferencegraph[]` from inside the
build_ig hook causes mwcceppc to crash (Rosetta exception at 0x6c2e1xxx).
Likely cause: `findrematerializations` (called near the end of
buildinterferencegraph) may reallocate the array, leaving stale pointers
at some indices. The minimal hook (just logging the event) is stable.

**Workaround:** the colorgraph hook's per-iter interferer dumps (committed
in c232825c2) provide the full adjacency-list data for all virtuals that
made it to the worklist. Simplified-out leaves aren't visible there, but
their interferences would have been edges to non-simplified virtuals
which ARE in the output. The data is functionally complete for matching
investigations.

**What we still don't have:** the FULL pre-simplification graph including
simplified-out leaves. Would require either:
- Hooking a stable intermediate function (e.g. between `buildinterferencematrix`
  and `findrematerializations`)
- Reading the interference *matrix* directly (at global 0x583088) instead of
  the post-coalescing adjacency vectors — the matrix is bit-packed and stable

**Effort spent:** ~half-day, mostly RE work on mwcceppc.exe to find VAs and
debugging the iteration crash.

## Tier 4 — permuter integration

[Decomp Permuter](https://github.com/simonlindholm/decomp-permuter) does
randomized C-source mutation, recompiles, scores against target asm.
It's the heavyweight tool people reach for when nothing else moves the
needle (inspector's `GOAL.md` mentions 50,000+ iterations on
`mpColl_80046904` without finding a beating local minimum).

The permuter is random by design. With our pcdump output + analyze
command, we could make it smarter — after each candidate, examine the
dump to see whether the mutation moved any of:
- A virtual register's live range (toward or away from the target)
- The use count of a virtual that's at the wrong physical
- The interference graph

A *guided* permuter that prefers mutations that affect the right
virtuals would converge much faster than random. Likely needs a custom
permuter scorer that incorporates the analyze output.

**What it unlocks:** systematically explorable "stuck at 99.8%" cases,
rather than stochastic.

**Rough path:** much bigger build. Implement as either (a) a new scorer
plugin for permuter that calls our analyze command, or (b) a separate
guided-search tool that owns its own mutation loop. (b) is cleaner but
re-implements a lot of permuter's machinery.

**Effort:** week-plus, depending on how deep the integration goes.

## Tier 5 — speculative: directly modify the DLL to bias coloring

The patched DLL already injects code into mwcceppc's address space. In
principle we could go further: not just observe the allocator but *bias*
it — e.g. force a specific virtual to a specific physical, or change
the candidate ordering.

This would let us answer "what if r36 got r31?" by actually compiling
that variant and diffing. It's the most invasive change (we'd be
modifying the compiler's behavior, not just observing it) but it's also
the most direct path to confirming hypotheses about the allocator.

**What it unlocks:** ground-truth answers via experimentation.

**Risks:** harder to know whether a forced-mapping result reveals a
real allocator preference or an artifact of our bias. Need careful
experiment design.

**Effort:** depends on what we want to bias; ~day per knob.

## Other small wins not worth their own tier

- **JSON output mode** for the analyze command — easier for agents to
  consume programmatically.
- **Comparison mode**: given two pcdumps (e.g. a passing-attempt and a
  failing-attempt for the same function), diff just the coloring
  decisions to surface what changed.
- **ABI annotation** in the analyze command — show "r3 = arg0", "r4 =
  arg1" etc. derived from function signature so the caller-save
  candidate filtering accounts for argument pinning.
- **Live-range alignment improvements** — the current pre/post-pass
  alignment is naive (skip-forward on opcode mismatch). Could use a
  proper sequence-alignment algorithm (e.g. Smith-Waterman variant) to
  recover more virtuals' live ranges from passes that re-order
  instructions.
