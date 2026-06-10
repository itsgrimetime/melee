# Liveness hooks: live-range dump + force-liveness (mwcc-debug DLL)

**Date:** 2026-06-10 · **Status:** Draft — needs the standard adversarial review
gate before planning/build. · **Forcing case:** mnDiagram_InputProc (94.53%;
count needs ~8 more interference edges / simplify slot 7-8 → r24/r25; six
campaign rounds established that every failure mode is "a live range was not
where we believed it was").

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

## 1. Live-range dump — `MWCC_DEBUG_DUMP_LIVERANGES=1`

- **Hook site:** the IG builder (0x530C00, already stubbed by the DLL). RE task:
  locate the per-virtual live-interval data the builder consumes. If intervals
  are not materialized (edges built by per-position scan), FALLBACK: wrap the
  scan and record min/max PCode position per virtual touched — equivalent output.
- **Output (env-gated, into the pcdump):**
  `[LIVERANGES] class=0` then one line per virtual:
  `v73: [184..210]` (positions in pre-coloring PCode numbering; block spans
  derivable host-side). Name resolution (count/hover/…) stays host-side via the
  existing symbol bridge.
- **Host side:** extend `colorgraph_parser` with a `LiveRangeSection`; surface
  in `explain-virtual` (`live(alloc)=[a..b]` next to the inferred span) and
  `debug inspect tiebreak --ranges`.
- **Validation gate (G-LR):** ranges must explain edges: for complete nodes,
  `overlap(a,b) ⟺ edge(a,b)` in COLORGRAPH (modulo call-crossing machine-reg
  edges). Checked across all cached dumps, same style as the surrogate's G1;
  <100% on clean functions ⇒ the interval read is wrong — fix, don't relax.

## 2. Force-liveness — `MWCC_DEBUG_FORCE_LIVERANGE="73=184..260[,…]"`

- **Mechanism (preferred):** extend the virtual's interval **before** edge
  construction so the builder allocates neighbor arrays natively at the right
  size. Direct post-build edge injection is the fallback but requires growing
  exact-sized IGNode arrays (allocate via the compiler's own CRT, as the fopen
  trick already does) — higher risk, only if pre-build extension is infeasible.
- Scoped per function via `MWCC_DEBUG_FORCE_LIVERANGE_FUNCTION` (same pattern
  as force-coalesce). Emits `[FORCE_LIVERANGE] v73: [184..210] -> [184..260]`;
  downstream SIMPLIFY/COLORGRAPH dumps then show the natural consequence.
- **Acceptance (the causality test):** on InputProc, extend count's range
  across the 8 live-through callee-saves' window → expect degree ~19-20,
  simplify slot 7-8, **r24/r25** in COLORGRAPH, cross-checked by the tiebreak
  surrogate (G1) on the forced dump. Either outcome is decisive: YES ⇒ the C
  search has a proven minimal goal ("emit code whose count range spans X..Y");
  NO ⇒ the mechanism exceeds degree/range and the function banks as the
  coloring-surrogate benchmark. Standard caveat: forced dumps are hypothesis
  tests, never source-level proof.

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
| Intervals not materialized in builder | scan-wrap fallback (same output contract) |
| IGNode array growth corrupts heap | prefer pre-build extension; CRT-alloc fallback; read-before-write asserts per house style |
| Dump bloat | env-gated; ranges only when requested |
| Range numbering vs pcdump instruction numbering mismatch | G-LR gate catches it on day one |

## Tests

Parser fixture (synthetic `[LIVERANGES]` block); G-LR overlap⟺edge on the
mnVibration fixture + a fresh mndiagram dump (100% on clean fns); force-liveness
live test: one vetoed/extended range on mnvibration changes exactly the
predicted edges (surrogate-confirmed); CLI plumbing tests (env passthrough,
scoping). Acceptance run on InputProc recorded in the case memory.
