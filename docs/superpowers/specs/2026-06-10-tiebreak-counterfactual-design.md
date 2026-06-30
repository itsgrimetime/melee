# Tiebreak counterfactual engine (`debug inspect tiebreak`)

**Date:** 2026-06-10 · **Forcing case:** mnDiagram_InputProc (94.53%, 9 compiler-temp
callee-saves, 2-position simplify swap ig88/ig90, force-phys-proven reachable)

> **REVISED per feasibility review (real-data, 2026-06-10).** The first draft's
> central choice — search interference EDGES with select order held fixed — is
> WRONG for the forcing case: ig88 and ig90 do not interfere; their regs come
> from dispense state at their (fixed) **select positions**, so the lever is
> simplify ORDER, not edges. Verified empirically. Edits folded in below:
> (1) G1 surrogate validated at **100%** on 8 fixtures + InputProc with the
> CORRECT dispense rule (the draft's rule scored 68%); (2) G2 "predict order
> from IG" is an unsolved research problem here (1.3–35.5% on real fns) — DROPPED
> as a gate; v1 takes order from the dump; (3) search axis is now **order
> perturbations AND edges**, and connects to the existing simplify-order
> tooling rather than reinventing it; (4) the draft's `--want 90:r27` is
> UNREACHABLE (ig90 only ever picks r25/r26) and was cross-variant — targets
> must be re-derived from the proven force-phys map of the EXACT source variant.

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
2. **Selection surrogate (the validated, reusable core)** —
   `predict_assignments(ig, select_order) -> assignments`, the SELECT phase only:
   - pop nodes in `select_order` (v1 takes the OBSERVED order from the dump; the
     search perturbs it — see component 4). Assign the lowest legal physical by
     the **empirically-verified dispense rule** (this exact ordering is
     load-bearing; the obvious reading scores only 68%, the verified one 100%):
     **(a) volatiles lowest-first; then (b) already-dispensed callee-saves in
     ASCENDING register order (reuse a dispensed saved reg before allocating a
     fresh one); then (c) a new callee-save from r31 downward.** A neighbor's
     already-assigned physical (incl. precolored 0–31 and resolved coalesce
     ghosts, whose physical is inline in the interferer list) blocks that color.
   - Spill path (no legal reg) → ABSTAIN (`spill-abstain`); costs aren't in the
     dump, out of v1 scope.
3. **Validation harness** — `validate(cache_glob)`:
   - **G1 (assignment-given-observed-order) — the only v1 gate:** feed each
     function's OBSERVED select order, predict assignments. Gate: **100% on the
     8 committed/cached fixtures + mnVibration control** (the review measured
     exactly 100% with the verified dispense rule, incl. the 331-node
     truncated-node fn_80247510). G1 < 100% on a clean fixture ⇒ HARD STOP: the
     dispense rule reading is wrong — fix, don't relax.
   - **NO G2 gate.** "Predict select order from the IG alone" is degree-priority/
     constrained-first, not low-degree-first Briggs; it scores 1.3–35.5% on real
     functions and is an open problem. v1 never predicts order — it takes the
     observed order and perturbs it locally.
4. **Minimal-perturbation solver** — `solve(ig, targets, observed_order)`:
   - targets: `{ig_idx: physical}` from the proven force-phys map of the EXACT
     source variant (NOT hardcoded; see Acceptance).
   - move set, smallest-first: **(A) select-order perturbations** — move one
     target node earlier/later in `observed_order` (the forcing-case lever:
     ig88/ig90's regs are pure dispense-position effects); **(B) edge edits** —
     add/remove one edge between complete, non-precolored nodes (covers the
     `remove(88,37) → ig88 r26→r25` class the review found). Depth 1
     exhaustive over both; depth 2 only over the **top-K=32** depth-1 results
     ranked by a partial-satisfaction score (#targets met, then total
     assignment churn), capped at 200k surrogate evals.
   - objective: `predict_assignments` at the perturbed config meets all targets.
   - output, ranked by perturbation size, each annotated via
     `virtual_attribution` (explain-virtual core; **best-effort** — ig→source
     comes from the fragile IRO/virtual↔ig bridge, stated as a dependency):
     - order moves → a **precise simplify-order objective** handed to the
       EXISTING `debug target score-simplify-order` / `mutate simplify-order`
       tooling (e.g. `--want-first 90,88`): the new value is replacing the
       agent's BLIND 23k permuter run with a surrogate-proven target order.
     - edge moves → "make temp-A's range overlap/not-overlap temp-B" with both
       defining instructions (honest caveat: edge structure is a weaker,
       less-reliable source lever than order position).
5. **CLI** — `melee-agent debug inspect tiebreak -f FN [--pcdump P]
   [--class gpr] --want "<ig:phys,...>" [--max-perturb 2] [--validate-only]
   [--json]`. `--validate-only` runs G1 and prints the fidelity report. Exit
   0 = perturbation(s) found (with the order objective / edge goal); 3 =
   abstain (spill / target node incomplete-degree / G1 failed for this fn —
   reason printed); 4 = no perturbation ≤ max achieves the targets (honest:
   redirect — the binding constraint is broader than a local move, or the
   target is unreachable; verify the force-phys map).

## Acceptance (the forcing case)

PREREQUISITE: re-derive `--want` from the proven force-phys map of the EXACT
committed source variant being matched, by dumping THAT variant and reading its
COLORGRAPH (the review showed ig_idx identity + current assignments differ
across variants — the original "ig88 r27→r25, ig90 r25→r27" was a different
variant than the clean mndiagram.c dump where ig90 only reaches r25/r26).
`r27` for ig90 is provably unreachable, so a target containing it ⇒ the campaign
was chasing an impossible order (which would explain the flat 23k permuter run).

Then on that variant's pcdump with the verified `--want`: either (a) a
surrogate-proven **simplify-order objective** (e.g. "simplify ig90 before ig88")
handed to `score-simplify-order` so the permuter has a precise, reachable target
instead of blind search — and/or a named edge goal; or (b) a trustworthy exit-4
"no ≤2 perturbation reaches it", redirecting the campaign honestly. Both are
wins; blind-search-against-a-maybe-impossible-target is the losing state we are
eliminating. G1 numbers for the cache are committed in the PR description.

## Non-goals (v1)

- Spill-path modeling (abstain), FPR class beyond parsing (gate on GPR first),
  G2 order prediction (open problem — take order from the dump), IG-construction
  modeling (creation order → ig_idx — the reverse-compiler surrogate's later
  layer), automatic source PATCHING (we emit objectives, the matcher writes C),
  reinventing the simplify-order search (we FEED the existing one), DLL changes
  to widen truncated interferer lists (only if truncation blocks a forcing case).

## Tests

- Parser: committed mnVibration fixture → exact node/edge counts; symmetry
  assertion (review: 728/728 edges symmetric); `...(N more)` truncation → node
  flagged `incomplete` with true degree from `nIntfr` (review: cap is 64).
- Surrogate G1: **100% on the committed fixture AND on a freshly dumped
  mndiagram.c** (the verified dispense rule; non-negotiable — <100% means the
  rule reading is wrong). No G2 test.
- Solver: synthetic IG where moving one node's select position provably flips a
  target's color → solver finds exactly that order move; and the review's
  `remove(88,37) → ig88 r26→r25` edge case on the real dump.
- CLI: exit codes 0/3/4 with a mocked surrogate.
