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

## Tier 3.5 — mechanism investigation (propagateconstants hook + PCode-gen finding) — ✅ DONE

Investigation triggered by the matching agent reporting that their
"use scroll_offset as NULL store source" attempt produced no new
interferences for r36 — they observed MWCC was "splitting the live
range" but didn't know the mechanism.

Implemented in commits described below. Three findings:

**A.** Empirical proof via pcdump: scroll_offset's "split" between
cleanup-loop and j-loop is present in the EARLIEST pass (BEFORE GLOBAL
OPTIMIZATION) — `li r50, 0; stw r50, 112(r45)` for cleanup, `lbz r36,
10(r39)` for j-loop. Two distinct virtuals from creation.

**B.** Cross-source-form invariance: baseline source (`= NULL` literal)
and experimental (`= (HSD_Text*)(s32) scroll_offset`) produce
**byte-identical** IR in BEFORE GLOBAL OPTIMIZATION. MWCC's PCode
generator inlines compile-time-known constants at the use site, erasing
C variable identity. No C-source pattern can defeat this when the
constant is statically provable.

**C.** Optimization-pass invariance: r50 is unchanged across all 8
optimization passes (verified by Tier 3.5 propagateconstants hook at
VA 0x52B530). CP fires but doesn't touch r50 — because there's nothing
to propagate after PCode gen already inlined the constant.

The propagateconstants hook emits `CONSTPROP RAN (changed_flag: before=X
after=Y)` events. For functions where CP changes something, the flag
flips. For unchanged functions, it stays. Useful general visibility into
which functions get heavy CP treatment vs. which arrive at PCode gen
already-optimized.

**Implication for matching cascades:** when the binary hook shows a
cleanup-loop "constant-store" pattern (`li rX, 0; stw rX, ...`) paired
with a runtime-load pattern (`lbz rY, ...`) elsewhere in the same
function, both deriving from the same C variable — those virtuals are
unmergeable through pure C source. Document the case and move on.

Documented in [`docs/mwcc-allocator-mechanism-deep-dive.md`](mwcc-allocator-mechanism-deep-dive.md).

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

## Tier 5 — allocator biasing via env var — ✅ DONE

Implemented in commit c8c8555aa. Lets us answer "what if r36 got r31?"
by actually compiling that variant and diffing the emitted code.

**Mechanism:**
- DLL reads `MWCC_DEBUG_FORCE_PHYS` at `DllMain`. Format:
  `"virtIdx:physReg[,virtIdx:physReg]*"`. Example: `"36:31"` forces
  virtual #36 to physical r31. Example: `"36:31,50:27"` forces both.
- In `hook_colorgraph`, AFTER the trampoline call (normal coloring
  runs), the hook walks the IGNode worklist, finds each node's
  `ig_idx` via `INTERFERENCEGRAPH[]` scan, and patches
  `IGNode->assignedReg` if there's a matching override.
- Next pass (`rewritepcode`) reads the patched field, so the override
  propagates all the way to the emitted `.text`.

**CLI exposure:**
```bash
melee-agent debug pcdump src/melee/mn/mnvibration.c \
  --force-phys "36:31" \
  --output /tmp/mnvib_force.txt
```
The CLI validates that the value contains no quotes/semicolons/
whitespace, then passes it as `set MWCC_DEBUG_FORCE_PHYS=...` on the
remote SSH side.

**Verified on mnVibration_80248644:** forcing virtual 36
(scroll_offset) from r27 → r31 produced FINAL CODE AFTER INSTRUCTION
SCHEDULING with `lbz r31,10(r28)` and `add r0,r31,r29` — exactly the
codegen the matching agent's experimental tried (and failed) to coax
with C-source restructuring. 13 `[FORCE_PHYS]` events fired across the
TU. (Note: cleanup-loop NULL also lives in r31 because its live range
ends before scroll_offset's begins — same physical for both is correct
under interference-graph rules.)

**What it unlocks:** ground-truth answers via experimentation. Before
spending hours trying to coax a specific allocation via C-source
shuffling, force it via the env var, see whether the resulting `.text`
matches the target. If yes, the goal is reachable; spend the time
finding the C pattern. If no, the constraint is elsewhere (instruction
selection, scheduling, etc) and the allocator isn't the problem.

**Caveats (documented in mwcc_debug.c):**
- Forcing two interfering virtuals to the same physical produces
  incorrect code (data corruption — multiple live values sharing one
  reg). DLL-patched ASM is NOT what the real compiler would emit from
  any C source — it's a hypothesis-test artifact, not a match target.
- Forcing across register classes (GPR vs FPR) likely crashes.
- Only operates on virtuals that survive `simplifygraph` (made it onto
  the worklist). Simplified-out leaves are colored elsewhere and
  aren't reachable from the colorgraph hook.

**Effort spent:** ~half-day, mostly cmd-line plumbing and env-var
parsing in C. The IGNode patching itself is 5 lines.

## Other small wins not worth their own tier

Done (commits 81fbe074e, c3a26d82a):
- ✅ **JSON output mode** for the analyze command (`--json`)
- ✅ **Comparison mode** — `melee-agent debug diff` compares two
  pcdumps for the same function
- ✅ **ABI annotation** in analyze — shows `r3 = arg0`, `r4 = arg1`
  etc. derived from function signature

Still open:
- **Live-range alignment improvements** — the current pre/post-pass
  alignment is naive (skip-forward on opcode mismatch). Could use a
  proper sequence-alignment algorithm (e.g. Smith-Waterman variant) to
  recover more virtuals' live ranges from passes that re-order
  instructions.
