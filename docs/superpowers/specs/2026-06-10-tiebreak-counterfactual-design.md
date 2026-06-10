# Tiebreak counterfactual engine (`debug inspect tiebreak`)

**Date:** 2026-06-10 · **Forcing case:** mnDiagram_InputProc (94.53%, 9 compiler-temp
callee-saves, 2-position simplify swap ig88/ig90, force-phys-proven reachable)

## Goal

Turn register-coloring tiebreak residuals from blind search (23k permuter
iterations) into a solved constraint problem: given the function's REAL
interference graph (from the pcdump) and a target assignment (from a proven
force-phys map), compute the **minimal IG edits** (edge add/remove) that make
MWCC's own selection algorithm produce the target — then name the source
expressions behind each edit so the matcher knows exactly what to reshape.

## Why now / why this works

- The DLL pcdump emits, per function: SIMPLIFY GRAPH (iter, ig_idx, degree,
  arraySize, flags) and COLORGRAPH DECISIONS (iter, ig_idx, assignedReg, degree,
  nIntfr, flags, **full interferer lists** `n=rPHYS`). That is the allocator
  decision phase's exact INPUT (constructed IG incl. precolored machine-reg
  edges) and OUTPUT (select order + assignments), side by side — hundreds of
  validation pairs sit in `build/mwcc_debug_cache/`.
- We therefore do NOT need to model IG construction (the hidden-bookkeeping
  hard part). Only simplify+select, which is documented in prose in cadmic's
  README (levels, threshold, wrap-around, lowest-first volatile dispense,
  nonvolatile from r31, adjusted-cost spill, coalesce-ghost semantics) and in
  the wuffs MWCC decomp.
- The existing `inspect simulate` predates this data: it approximates order by
  ascending interferer count (~30% match, explanation-grade) and rebuilds
  interference from PCode. This engine replaces its order model with the real
  IG + real algorithm; `simulate` stays as the explanation tool.

## Components

`tools/melee-agent/src/mwcc_debug/tiebreak.py` (new):

1. **IG parser** — reuse/extend `colorgraph_parser.py` to materialize, per
   function+class: nodes (ig_idx), neighbor sets (from COLORGRAPH interferer
   lists, including precolored 0–31), degree/arraySize, flags, observed select
   order (COLORGRAPH iter sequence), observed assignments.
   - **Truncation guard:** interferer lines can end `...(N more)`. Mark such
     nodes `incomplete`; the surrogate may still run (their color choices are
     constrained by nIntfr count) but counterfactual edits never touch
     incomplete nodes, and fidelity stats report them separately.
2. **Selection surrogate** — `predict(ig) -> (select_order, assignments)`,
   implementing the documented algorithm:
   - simplify: repeated passes in ascending ig_idx; push node when
     remaining-degree < n_colors (from the SIMPLIFY header, e.g. 29 for GPR);
     remove from live graph; wrap until empty; if stuck → spill path: ABSTAIN
     (record `spill-abstain`) — costs aren't in the dump; out of v1 scope.
   - select: pop in reverse push order; assign lowest legal physical
     (volatiles lowest-first; previously-dispensed saved regs preferred; new
     nonvolatile from r31 downward; precolored neighbors block their color).
   - Where the cadmic prose underdetermines a detail, resolve it empirically
     against observed orders (that is the point of the validation gates).
3. **Validation harness** — `validate(pcdump|cache_glob)`:
   - **G1 (assignment-given-order):** feed the OBSERVED select order, predict
     assignments only. Gate: ≥99% node-level agreement on non-spill functions.
     G1 < 95% ⇒ HARD STOP (parsing or color rules wrong; fix before anything).
   - **G2 (order prediction):** predict order from the IG alone. Gate: ≥95%
     exact-position agreement on non-spill functions across the cache, AND
     100% on the two control functions (mnVibration_80248644, the committed
     fixture) — plus measured number for mnDiagram_InputProc reported
     explicitly. G2 failures on specific functions are reported per-function
     (abstain), not hidden in an average.
4. **Counterfactual search** — `search(ig, targets, max_edits=2)`:
   - targets: `{ig_idx: physical}` constraints (e.g. `88:r25, 90:r27` from the
     proven force-phys map).
   - moves: add/remove one edge between two complete, non-precolored nodes;
     depth 1 exhaustively, depth 2 over the top-K depth-1 near-misses.
     (Creation-order/ig_idx swaps are NOT searched in v1: ig_idx is identity
     in the dump; reordering it is not an IG-local counterfactual.)
   - objective: surrogate's predicted assignments satisfy all targets.
   - output: ranked by edit count; each edit `(A,B)` annotated with both
     nodes' defining instructions + source attribution via
     `virtual_attribution` (the explain-virtual core), e.g.
     `ADD edge (88,103): make '25 - i' temp overlap 'fp->x2C load' — extend
     one across the other's range`.
5. **CLI** — `melee-agent debug inspect tiebreak -f FN [--pcdump P]
   [--class gpr|fpr] --want "88:r25,90:r27" [--max-edits 2] [--validate-only]
   [--json]`. `--validate-only` runs G1/G2 for the function and prints the
   fidelity report. Exit 0 = counterfactual(s) found; 3 = surrogate abstained
   (spill/incomplete/G-gate failed for this fn — printed reason); 4 = no edit
   ≤ max-edits achieves the targets (an honest, useful answer: the tiebreak is
   not reachable by ≤2 IG-local edits).

## Acceptance (the forcing case)

On mnDiagram_InputProc's pcdump with `--want` from the agent's proven
force-phys map: either (a) ≥1 ranked counterfactual with named source
provenance — handed to the matching agent as a concrete edit goal; or (b) a
trustworthy exit-4 "no ≤2-edge counterfactual exists", which redirects the
campaign honestly (the lever must then change degree structure more broadly —
peel-chain class). Both outcomes are wins; blind-search-forever is the only
losing state. G1/G2 numbers for the cache are committed in the PR description
of the change.

## Non-goals (v1)

- Spill-path modeling (abstain), FPR class beyond parsing (gate on GPR first),
  IG-construction modeling (creation order → ig_idx — that is the
  reverse-compiler surrogate's later layer), automatic source PATCHING (we
  emit goals, the matcher writes C), DLL changes to widen truncated interferer
  lists (only if truncation blocks the forcing case; one-line follow-up).

## Tests

- Parser: fixture pcdump (committed mnVibration fixture) → exact node/edge
  counts, truncation flag on a `...(N more)` synthetic line.
- Surrogate: G1 on fixture = 100%; G2 on fixture = 100% (else the algorithm
  reading of cadmic's prose is wrong — fix, don't relax).
- Search: synthetic 6-node IG where removing one edge provably flips two
  nodes' colors under the surrogate → search finds exactly that edit.
- CLI: exit codes 0/3/4 with mocked engine.
