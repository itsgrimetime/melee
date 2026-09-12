# Matching Tooling Postmortem — why compiler-internals tooling didn't break through

*2026-06-15. Diagnosis from session review (issue DB, match-history, git provenance, session transcripts). Audience: anyone deciding where to invest decomp tooling effort.*

## TL;DR

We built a large suite of compiler-internals introspection tooling (`mwcc-debug`,
`debug solve`/`force-phys`, `mwcc-inspect`, `mwcc-retro`) on the premise that
*MWCC is deterministic, so if agents can see the internals they can leverage
them to break through hard matches.* Across 727 filed-and-resolved issues, the
introspection tooling has **localized** mismatches well but has **not been the
unblocker for matches**. Meanwhile the same stubborn functions repeatedly fell to
**simple, natural source edits** found by contributors *not* using the tooling.

The root cause is an **altitude mismatch made unfixable by non-invertibility**:
the tooling observes the compiler's *back end* (register coloring, scheduling);
the lever you control is the *source*; and the front-end + optimizer between them
is **not invertible** from back-end state. So back-end internals can never be
mechanically back-propagated into a source edit — and the matches live entirely
on the source side.

**The *bias* — over-investing in introspection, under-using generation, with
episodic premature give-up — is endemic to the workflow, not bad luck. It makes
matching expensive and sometimes stalls it; it does not make it impossible
(functions do get matched — see the 2026-06-15 correction below).**

## The evidence

- **Issue grind, quantified.** 727 issues, 725 resolved (99.7%). `mwcc-debug`
  alone generated 289 (40%). The 20 most-issued functions absorbed ~353 issues;
  of those, **5 are now matched (~155 issues' worth, including the single
  most-issued, `fn_8003F654` at 94) and 15 sit at 95–99.8%.** Heavily-tooled
  functions converge slowly and expensively — `fn_8003F654` matched only after
  94 issues, via sqrt-idiom recognition + an embedded-assign temp (`f32 new_var`,
  the same lever a transform family already generates), not via a coloring
  insight.
- **CORRECTION (2026-06-15).** An earlier draft of this section claimed
  `fn_8003F654`/`fn_8003F294` were "still unmatched at 97.73%, even uncontested."
  That was a measurement error: a `grep` on minified `report.json` returned the
  *whole-binary* 97.73% for them; both are actually **100%**. A fresh-eyes
  validation run caught it by building and running `checkdiff` directly. The
  "fails even uncontested / never breaks through" claim is **retracted** — the
  workflow does match functions; the real defect is *cost/efficiency* (see
  below), not inability.
- **Stubborn functions fell to simple edits by others.** On `mnDiagram_80240D94`
  (we filed 6 issues) Ford Lascari (#2689) used `text->pos_y = (new_var = -y);`
  (introduce a temp via embedded assignment), hoisted `&tbl->points[1]` into a
  local, split a reused `kos` into per-branch `u32 count`, and retyped
  `u8 result`→`s32`. On `mnDiagram_802417D0` (8 issues), `mnDiagram_80241E78`
  (17), `mnDiagram_8023FC28` (17) the story repeats. Jurre Groenendijk (#2535)
  used the same class of moves: hoist a cast into a named local, re-associate a
  boolean, `(u8) j`, `u64`→`u32`, model a data blob as a struct overlay. Two
  independent contributors, same altitude, on functions we had declared
  "exhausted / banked / source-lever-unreachable."
- **Every actual crack came from a generative channel, never from reading a
  dump backward.** Permuter (search) found OnFrame's alias and AggRank's
  branch-swap; codex (a different model) found UpdateHeader's scheduler fix;
  semantic reasoning found `gm_801A9DD0`'s `arg2: int→u16` (the frame tooling
  only *localized* the symptom). The introspection tooling is credited with zero
  unblocked matches.

## Why "more internals" was the wrong lever (the determinism argument)

The premise is half-right. MWCC *is* a deterministic function `f: source → bytes`,
and that determinism is real leverage. But the inference "deterministic +
observable internals ⟹ we can leverage internals to find the matching source"
conflates two different things:

- **Determinism buys reproducibility, not invertibility.** A cryptographic hash
  is deterministic and fully traceable; that buys you nothing toward finding a
  preimage. Matching is an *inversion* problem, and inversion difficulty is
  independent of determinism.
- **The observable internals sit on the wrong side of a lossy transform.**
  `source → IR → optimize(CSE/prop/DCE/loop) → PCode → coloring → schedule → bytes`.
  The tooling shows coloring/scheduling. Your lever is source. `source → IR` is
  **many-to-one** (CSE/copy-prop erase distinctions), so it can't be run backward.
  Coloring's *input* is optimized IR several non-invertible transforms removed
  from source. "The dump shows r28 where target has r29" therefore can **never**
  be mechanically turned into "change this source token." You can only guess a
  source edit, recompile, and look.
- **This is exactly why `debug solve` only solves the register-only,
  structure-fixed residual** — and why that class is empty/0-yield in practice
  (`reachable=False`; node-set-split census: 13 FPR + 6 GPR functions, 0
  improvements). It's the only case where you can hold the non-invertible part
  fixed. But nearly every worthwhile fix *changes the IR*, putting the answer
  outside the only place the tooling can reason. Not a maturity gap — a
  structural property of where the observable internals sit.

### Determinism's *actual* dividend (both generative)

1. **A perfect test oracle ⟹ search is sound.** Enumerate plausible source
   variants, compile, keep byte-exact wins. This is the permuter, and it's why
   it found the cracks. Determinism is what makes blind/guided search reliable.
2. **Stable `(codegen-pattern → source-lever)` correspondences ⟹ mineable
   generative priors.** Because the same source shape always yields the same
   codegen shape, "when the diff looks like X, the lever is usually Y" is
   learnable from past matches (mismatch-db / opseq / transform-corpus). This is
   also how veteran humans use compiler knowledge: as a *generative prior over
   source*, not as backward inference from internal state.

The bottleneck was never visibility ("why is my guess wrong?" — at 99% the agent
sees that precisely). It is **candidate generation/coverage** ("which of the many
plausible source variants is right?"). The correct response to a generation
bottleneck is to industrialize generation — not to deepen failure analysis, which
pulls attention to the altitude where the lever doesn't live and manufactures
false confidence that the simple edit can't help.

## How the tooling actively backfires

1. **Give-up:** `solve`/`force-phys` emit an unscoped `reachable=False` /
   "unreachable." The scope ("no register relabel for the *current structure*")
   is dropped; the agent reads a function-level verdict, banks it, and stops.
   ~12 of ~18 banked mndiagram functions were later improved and 4 reached 100% —
   every "ceiling" verdict over-scoped.
2. **Treadmill:** each tool emits one crisp residual, which looks like a single
   blocker, so the agent names it "THE unblocker" and files a capability request.
   The resolver grants it (99.7%), which validates the framing and trains the
   behavior. Compiler internals are bottomless, so "expose more internals" is
   never falsified — guaranteeing a treadmill, not convergence.
3. **Crowd-out:** staring at ig-nodes and callee-save swaps, the agent never
   asks "what natural variant would a developer have written?" — violating this
   repo's own rules (*"Think like a developer, not like the ASM"*, *"Structure
   first, registers last"*). The bias even contaminated our notes: a saved memory
   claimed external PRs "did NOT crack the hard partials… nothing to harvest…
   below the source," about functions those PRs matched simply.

## Corrected investment thesis

- **Invest in generation, not analysis.** Permuter breadth/guidance; a codified
  structural-lever library applied systematically; corpus-driven `(diff → lever)`
  proposers; diverse generators (codex / fresh-eyes). This is where matches come
  from and it's the correct way to exploit a deterministic oracle.
- **Demote introspection to a late-stage localizer.** Genuinely useful once
  structure is right and you need to understand one specific divergence
  (it localized `gm_801A9DD0`'s frame). Never the arbiter of matchability;
  never the thing you extend when stuck.
- **The walls are real, but they are search-coverage walls, not visibility
  walls.** The proof: fresh contributors clear them with five-line natural edits.

## Keystone experiment result (2026-06-15)

Before building generation tooling, we tested *where* the gap is: do we already
have transform families that generate the winning levers?

**Answer: yes, almost all of them.** The transform-corpus has ~40 families, and
they cover essentially every lever the external contributors used —
`assignment_expression_temp_seed` is literally Ford's `obj->f = (tmp = expr)`;
`temp_sink_hoist`/`scoped_alias` = hoist-to-local; `same_type_local_lifetime_reuse`
/`lifetime_preserve_shorten` = split-local; `numeric_cast_shape`/`counter_type_shape`
= retype; `raw_index_struct_field_shape`/`data_table_indirection_shape` =
struct-overlay; `fp_subtraction_operand_reassociation` = FP re-assoc;
`condition_split_merge` = the boolean restructure.

**So the bottleneck is NOT a missing lever vocabulary — it's that the generative
search isn't run as the primary strategy.** Corroborating: issues about
introspection internals (mwcc-debug/solve/force-phys/coloring) outnumber issues
about running the directed/transform-corpus search **~6:1 (325 vs 54)**; and the
directed-search delivery is flaky (stale editable `.pth`, families that fire but
aren't reached, engaged via `search directed` not `run`).

**Implication — do NOT mine more families** (that would be another lap of the
treadmill). #5's investment is: (1) make directed-search/permuter-with-families
the DEFAULT FIRST move on any stuck/>=95% function (operationalized by the
fresh-eyes skill + the protocol below); (2) fix generation *delivery* (the `.pth`
wiring, ensure families fire and reach the right anchors); (3) only add a family
when a real stuck function proves a coverage gap.

## Validation (2026-06-15): two fresh-eyes runs

Dispatched the fresh-eyes lane (constrained subagent: checkdiff + permuter + the
lever checklist only; no introspection tooling; no anchoring notes) on two
genuinely-stuck functions:

- **`grIceMt_801F9ACC` (99.98% → 100%, CRACKED).** Source-shape, no introspection:
  the residual was pure data-layout — the function used `HSD_ASSERT` (emitting a
  fresh `__FILE__` string) while the rest of the TU uses the explicit-filename
  idiom; matching the idiom realigned the TU data layout and the float
  relocations resolved automatically. The agent tried a wrong lever first
  (named-float-symbols → regressed 99.64%), reverted, and re-diagnosed — no
  fabrication.
- **`ftCo_8009E7B4` (99.31%, NOT cracked).** A genuine register-coloring
  tie-break: opcode similarity 100%, normalized-diff 0, structure provably
  correct (all 9 structural levers regressed/no-op'd; undirected permuter ~4460
  iters, no improvement). The agent correctly diagnosed it and — per the
  protocol — did NOT bank; it recommended a *directed* register-vector /
  PERM-macro search next.

**Refinement — two populations of stuck functions:**
- **(a) simple-lever-crackable** — most of them; a source-shape gap the workflow
  over-introspected instead of just trying. Fresh-eyes/generation-first catches
  these (grIceMt; the Ford/Jurre cases; the campaign's banked-then-cracked).
- **(b) genuine register-coloring tie-breaks** — structure already correct;
  undirected levers and random permuter don't reach them (ftCo). Here the
  introspection *classification* is correct and useful — its legitimate, narrow
  role. The right next move is a *directed* register-vector / PERM-macro search
  (generation guided by the coloring target), **not** banking and **not** a
  tooling-extension issue. Even directed search has a thin record here
  (node-set-split census was 0-yield), so the honest fallback is "leave at
  99.x%, coloring tie-break, no current lever reached it" — never "unreachable /
  below the source."

**Net:** the fresh-eyes skill is validated by *both* runs — it cracked the
tractable case, and on the hard case behaved exactly as designed (tried
generation, honestly diagnosed, refused to bank, pointed at the real next
lever). Introspection's value is real but narrow: diagnose + direct search for
population (b), *after* generation-first has ruled out population (a).

## Proposed protocol (the actionable part)

### Cheap-structural-first — run BEFORE any compiler-internals tool

When a function is stuck (and especially when ≥95%), exhaust this checklist —
ideally by handing it to the permuter, which mechanizes the search — before
reaching for `mwcc-debug`/`solve`/`force-phys`:

1. Re-associate / reorder FP arithmetic operands (and const-first vs const-last).
2. Hoist a subexpression or pointer-cast into a named local; or sink one in.
3. Introduce a temp via embedded assignment: `obj->f = (tmp = expr);`.
4. Split / rename a local per live-range (fresh local per branch vs one reused).
5. Retype locals/params: `int`↔`u32`↔`s32`↔`u16`↔`u8`; signed/unsigned; and the
   loop-counter `int` vs `s32` distinction.
6. Hoist a block-scoped local to function scope (or vice-versa) to re-open the
   `decl-orders` search; re-run after every such change.
7. Reorder declarations / statements (decl-order ladder).
8. Model a hidden data blob as a file-local struct overlay; access named fields.
9. Inline vs. out-of-line a tiny helper; inline a call argument.
10. Express masks/conversions differently: `(u8) x` vs `x & 0xFF`.

### Gates

- **G1 — "exhausted" requires evidence.** "exhausted / banked /
  source-lever-unreachable / NO-WIN" are forbidden conclusions unless the report
  shows (a) the structural checklist was tried and (b) a permuter sweep was run.
- **G2 — capability requests must name source hypotheses.** A tooling-issue is
  valid only if it names the specific *source variants it cannot test*. "I can't
  see deeper into coloring" is not a valid blocker.
- **G3 — issue cap per function.** Beyond K issues (suggest K=5) with no match,
  auto-flag and force a switch to generative search or shelving.
- **G4 — measure matches, not issues.** Success = match-% delta and matches
  landed, not issues filed/resolved.
- **G5 — fresh-eyes lane.** Stuck/banked functions get one pass from an agent
  with no internals tooling and no prior notes: just the asm diff and "what would
  a developer write?" — structurally reproducing what Ford and Jurre did.
- **G6 — coloring-tie-break escalation.** If fresh-eyes confirms "structure
  correct, pure coloring tie-break" (opcode ~100%, normalized-diff 0, every
  structural lever regresses, undirected permuter finds nothing), escalate to a
  DIRECTED register-vector / PERM-macro search — do NOT bank, do NOT file a
  tooling-extension issue, do NOT declare it unreachable. If the directed search
  also misses, leave it at its current % with an honest "coloring tie-break, no
  current lever reached it" note. This is introspection's one legitimate role,
  and it comes AFTER generation-first, not instead of it.
