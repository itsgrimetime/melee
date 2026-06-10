# Liveness hooks: live-set dump + force-interfere (mwcc-debug DLL)

**Date:** 2026-06-10 · **Status:** BUILT + validated (see Outcome below). ·
**Forcing case:** mnDiagram_InputProc
(94.53%; count needs ~8 more interference edges / simplify slot 7-8 → r24/r25; six
campaign rounds established that every failure mode is "a live range was not where
we believed it was").

> **REVISED per feasibility review (disassembled 0x530C00 + cross-checked the
> wuffs MWCC decomp `InterferenceGraph.c`/`LiveInfo.h`).** Ground truth: MWCC has
> **NO per-virtual live intervals**. Liveness = four per-BLOCK bitvectors
> (`LiveInfo{use,def,in,out}`); interference = a triangular **bitmatrix** at
> global `0x583088`, built by a backward instruction scan in
> `buildinterferencematrix` (**0x531290**); `buildadjacencyvectors` (0x530C00)
> only materializes exact-sized IGNodes from the finished matrix. Consequences
> folded in below: (1) Hook-1 is a **scan-recorder wrapping 0x531290** (the only
> place a per-position live-set exists), emitting per-block spans — not an
> interval field-read. (2) Force-liveness is re-specified as **force-INTERFERE**:
> inject edge bits into the matrix at 0x583088 *between* 0x531290 and 0x530C00,
> so the native scan sizes IGNode arrays correctly (post-build array growth is a
> NON-STARTER — exact-sized `oalloc` + `findrematerializations` realloc already
> crashed the DLL, mwcc_debug.c:1499). (3) G-LR `overlap⟺edge` downgraded to a
> scoped one-directional check.

## Why

We can observe the IG **after** construction (COLORGRAPH neighbor lists, 512-cap)
and force phys/coalesce/iter — but we cannot see **why an edge exists or
doesn't** (where each virtual's range actually starts/ends after sinking,
folding, rematerialization), nor test "would these edges flip the assignment?"
against the *real* allocator. The tiebreak surrogate proves order→register;
these two hooks close the remaining gap: range→edge (observe) and edge→outcome
(force). Note: `explain-virtual` already shows `live=a..b` **inferred from
pcode occurrences**; the hook gives **allocator-truth**, which is exactly what
diverges when the optimizer moves defs (the failure mode of rounds 5–6).

## 1. Live-set dump — `MWCC_DEBUG_DUMP_LIVERANGES=1`

- **Hook site: `buildinterferencematrix` at 0x531290** — the only place a
  per-position live-set exists (the rolling working-set `vec`, seeded per block
  from `liveinfo[block].out`, walked backward marking matrix bits). NOT 0x530C00
  (which sees only the finished matrix → can recover degree/neighbors, which the
  DLL already dumps, but no positional span). 0x530C00 is NOT currently hooked;
  the DLL hooks the wrapper 0x530A00 + 0x530A80/0x530E00 — wire a new trampoline
  at 0x531290.
- **What to record:** as the backward scan visits each instruction position,
  note for every virtual currently in `vec` its min/max position **per block**
  (liveness is cross-block and non-contiguous — a single flat `[a..b]` would
  over-approximate live-in-from-successor gaps).
- **Output (env-gated, into the pcdump):** `[LIVERANGES] class=0` then per
  virtual: `v73: B4[3..9] B7[0..2]` (per-block spans, MWCC internal walk
  numbering). Name resolution (count/hover/…) stays host-side via the symbol
  bridge. The genuinely-new datum vs existing dumps is the per-position span;
  degree/neighbors are already available.
- **Host side:** extend `colorgraph_parser` with a `LiveRangeSection`; surface
  in `explain-virtual` (`live(alloc)=…` next to the occurrence-inferred span,
  which is non-redundant) and `debug inspect tiebreak --ranges`.
- **Validation gate (G-LR), scoped + one-directional:** for **virtual–virtual,
  non-move, non-coalesced** node pairs only, `edge(a,b) ⇒ their per-block spans
  share a block with overlapping positions`. EXCLUDED (legitimately edge-without-
  overlap or overlap-without-edge): reg–reg pairs 0..31 (force-interfered
  unconditionally), call-scratch edges (live-across-call ↔ every scratch reg),
  `fIsMove` src/dst (edge suppressed despite overlap), and coalesced nodes
  (neighbor row is the union of merged virtuals). Checked across cached dumps in
  the surrogate-G1 style; a violation in the scoped set ⇒ the recorder is wrong —
  fix, don't relax.

## 2. Force-interfere — `MWCC_DEBUG_FORCE_INTERFERE="73=23,73=25,73=26,…"`

(Renamed from "force-liveness": there is no interval to extend; the causality
test we actually want is "make virtual V interfere with these nodes," which is
edges. This is also simpler and safer than range manipulation.)

- **Mechanism:** between 0x531290 (matrix built) and 0x530C00 (arrays
  materialized), set the requested interference bits directly in the matrix at
  global `0x583088`, replicating MWCC's `makeinterfere(a,b)` addressing
  (triangular: bit `(max*max)/2 + min`). 0x530C00 then allocates exact-sized
  IGNodes natively — **no heap growth, no stale pointers.** Read-before-write
  asserts on the matrix base/size per house style.
- **Explicitly NOT done:** growing already-materialized IGNode neighbor arrays
  (exact-sized `oalloc`; `findrematerializations` reallocates the graph at the
  tail — the array-iteration crash at mwcc_debug.c:1499 is direct evidence).
- Scoped per function via `MWCC_DEBUG_FORCE_INTERFERE_FUNCTION` (force-coalesce
  pattern). Emits `[FORCE_INTERFERE] +edge(73,23) +edge(73,25) …`; downstream
  SIMPLIFY/COLORGRAPH dumps show the natural consequence.
- **Acceptance (the causality test):** on InputProc, inject edges from count
  (v73) to the 8 live-through callee-saves → expect degree ~19-20, simplify slot
  7-8, **r24/r25** in COLORGRAPH, cross-checked by the tiebreak surrogate (G1) on
  the forced dump. Decisive both ways: YES ⇒ the C search has a proven minimal
  goal ("make count interfere with these specific values" → emit code where
  those 8 are live across count's window); NO ⇒ the mechanism exceeds degree
  and the function banks as the coloring-surrogate benchmark. Standard caveat:
  forced dumps are hypothesis tests, never source-level proof.

## Outcome (built 2026-06-10)

- **Hook-2 force-interfere — SHIPPED + validated, the high-value half.**
  `MWCC_DEBUG_FORCE_INTERFERE` injects matrix bits at 0x583088 between 0x530E00
  and 0x530C00 (no heap growth). Round-trip confirmed (inject 33=34 → appears in
  ig33 COLORGRAPH neighbors, scoped) AND cross-validated against the tiebreak
  surrogate (surrogate predicted ig434 r24→r26 under +edge(434,32); real
  allocator produced r26). This is the coloring-causality engine: surrogate
  proposes edges → predicts → force-interfere confirms against retail MWCC.
- **Hook-1 LIVERANGES — SHIPPED as a block-span diagnostic (scope corrected).**
  Dumps per-block live-in/out from LiveInfo @0x587E74 (fn-labeled). It answers
  "which blocks is V live across" (e.g. "count spans B4-B5; the callee-saves
  span B2-B9 → extend count to overlap") — directly useful for C placement. It
  is NOT an edge oracle: block-boundary co-liveness explains only ~47% of edges
  because interference forms from WITHIN-block transient liveness. The spec's
  `overlap⟺edge` G-LR gate is therefore retired (validate_glr is a documented
  diagnostic, not a pass/fail). RE-confirmed read (correct offset/stride;
  empty-entry / populated-later blocks as expected).
- **REMAINING increment: edge-faithful per-instruction liveness.** Instrument
  the backward scan *inside* buildinterferencematrix (0x531290 region) to record
  the live-set at each instruction position — the only thing that reconstructs
  edges exactly. Larger/invasive (the review's "much larger" path). Not needed
  for the current workflow: force-interfere (causality) + block-span (placement)
  + the surrogate (prediction) already close the loop at block resolution.

## Future extensions (explicitly out of scope here)

- **(3) Variant IG differ** — host-side: diff two dumps' graphs by *named*
  node (symbol bridge), each edge delta annotated, once (1) lands, with the
  range-based "why" (`edge lost: hover now [42..178], gap of 6 instrs`).
  No DLL work; builds directly on `LiveRangeSection`.
- **(4) Def-motion tracer** — host-side over existing per-pass dumps: track a
  def's position across backend passes; names the pass that sinks/folds a
  cached local. Pairs with the retro IRO trace for front-end motion.

## Risks

| Risk | Mitigation |
|---|---|
| Matrix bit-addressing wrong (triangular `(max*max)/2+min`) | replicate `makeinterfere` exactly; G-LR + a round-trip test (inject a known edge, confirm it appears in COLORGRAPH neighbors) |
| Matrix global 0x583088 / size not as RE'd | read-before-write assert on base + bounds; abort if shape unexpected |
| Per-block span numbering vs pcdump listing order | emit per-block spans (not a flat hull); G-LR scoped to within-block overlap |
| Hooking 0x531290 perturbs timing/other passes | trampoline pattern already proven for 0x530A00/0x530E00; scope by function |
| Dump bloat | env-gated; spans only when requested |

## Tests

Parser fixture (synthetic `[LIVERANGES]` per-block-span block); G-LR scoped
one-directional check (edge ⇒ within-block overlap, excluding reg-reg / call-
scratch / move / coalesced pairs) on the mnVibration fixture + a fresh mndiagram
dump (100% on clean fns in scope); force-interfere live test: inject one edge on
mnvibration, confirm it appears in that node's COLORGRAPH neighbor list and the
surrogate predicts the consequent assignment; CLI plumbing tests (env
passthrough, function scoping). Acceptance run on InputProc recorded in the case
memory.
