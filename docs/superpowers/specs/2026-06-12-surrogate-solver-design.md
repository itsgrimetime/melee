# Surrogate-as-solver: inverse register coloring via IG perturbation search

**Date:** 2026-06-12 · **Status:** REVISED post-codex-review (REWORK-REQUIRED →
addressed; see Appendix A for finding-by-finding disposition). · **Forcing
class:** the ~10/18 remaining mndiagram-module partials that classify
register-only (checkdiff `operand-register-or-offset` / `backend-ceiling` /
`normalized-structural-match`), where force-phys proves the target coloring
REACHABLE but blind permuter search is the only path that has ever produced the
winning C reshape.

> **This spec EXTENDS** `docs/superpowers/specs/2026-06-10-tiebreak-counterfactual-design.md`
> (the G1-validated select **surrogate** + manual single-`--what-if` CLI, shipped
> as the predictor behind `melee-agent debug inspect tiebreak`) from its v1 move
> set — select-order perturbations AND interference EDGE edits, applied one at a
> time by hand — to **NODE-SET / CONTENT** perturbations (add a virtual that
> copies an existing value and routes a parameterized use-set through it; bump a
> REF count) **plus an enumeration/ranking/worksheet layer that does not exist
> yet**. It is the operational answer to the 2026-06-12 strategic finding (agent
> memory `reverse_compiler_feasibility.md`): the order axis is REFUTED as a lever
> class for this pool (0/13 derivations route `directed`; forcing simplify order
> never byte-eliminates), and the productive lever class is empirically
> **node-set / content** — alias introduction (CursorProc gp/flow-alias and the
> 80241E78 loop-tail data_alias = the type specimens), temp-for-expr,
> second-genuine-use anchoring. Every such win to date was found blind. This
> project converts that blind search into directed search by **modelling, at
> enumeration time, which node-set perturbations are source-realizable AND
> survive the allocator** (the new §1.5 enumeration filter), enumerating only
> those, predicting their coloring with the surrogate, then mapping the winning
> perturbations to concrete C moves and confirming each against a re-extracted IG.

## Why now / why this is a different bet than the order loop

- The order-distance directed loop was built end-to-end (Plans A+B; spec/plan/7
  codex-gated tasks under `docs/superpowers/{specs,plans,results}/2026-06-12-*`)
  and **STOPPED**: its kill switch fired with no derivation-eligible witness
  (`docs/superpowers/results/2026-06-12-order-distance-kill-switch-result.md`),
  and the per-function classifier
  (`tools/melee-agent/src/mwcc_debug/order_target_derive.py`) routes the whole
  pool to `not_order_class` / `unstable_target`. **This spec does NOT resurrect
  order search** (Non-goals §8). It targets the lever class the census points at:
  node-set / content. The order classifier is REUSED, unchanged, as a cheap
  precondition gate (it already partitions register-only-vs-structural and runs
  force-phys-from-diff for the target map).
- The surrogate core already exists and is validated: `predict_assignments` in
  `tools/melee-agent/src/mwcc_debug/tiebreak.py` re-implements only MWCC's SELECT
  phase under the empirically-verified dispense rule (volatiles lowest-first →
  already-dispensed callee-saves ascending → fresh r31-down). G1 = 100% on every
  GPR function tested, including the 331-node truncated `fn_80247510`. It accepts
  `extra_neighbors`, `removed_edges`, and `move_before/move_after` perturbations
  (`what_if`). What it LACKS, and this project adds, is (a) a node-ADD primitive
  (a new colorable virtual with a routed use-set, which changes who interferes
  with whom); (b) **an enumeration-time validity filter so the proposal stream is
  mostly realizable instead of mostly junk** (§1.5 — the codex BLOCKER fix); and
  (c) an enumeration + ranking + worksheet loop. There is no `solve`/`worksheet`/
  `enumerate` code today — this is a new layer over a predictor, not a tweak to a
  shipped solver.
- The "what input produces the desired state" stage-snapshot model is
  architecturally correct for MWCC (deterministic, stage-separable) under the
  three `reverse_compiler_feasibility.md` amendments — target states are never
  observed (back-infer the force-phys target map, pick a FRONT-REACHABLE member);
  inputs include HIDDEN BOOKKEEPING absent from the IR dumps (temp creation order
  incl. deleted temps, REF counts, ig_idx identity, coalesce/spill weights); and
  INTERVENTION (force-phys replay) beats passive snapshots. §1.5 builds the
  upstream model INTO enumeration; §3 is the post-application confirmation for the
  remainder the model can't cover.

## Verified substrate (paths/CLIs confirmed to exist as of 2026-06-12)

| Capability | Location / CLI | Status |
|---|---|---|
| Select surrogate (`predict_assignments`, `what_if`, `validate_g1`, `build_ig`, `load_ig`) | `tools/melee-agent/src/mwcc_debug/tiebreak.py` | EXISTS; **predictor only — no `solve`/`enumerate`/`worksheet`** |
| GPR G1 | `validate_g1` over matched GPR COLORGRAPHs | 100% on every GPR fn tested incl. truncated `fn_80247510` |
| FPR register pools | `tiebreak.py` `_FPR_VOLATILE_LOW_FIRST` / `_FPR_CALLEE_FRESH` (30-32), `_register_pools` (96-99); `--class fpr` parsed at `cli/debug/__init__.py:21653` | **path present; corpus G1 UNPROVEN** (spot-validated only — §5) |
| Manual single what-if CLI | `melee-agent debug inspect tiebreak -f FN [--class gpr/fpr] [--ig N (report context only)] --what-if "add-interferer T:N \| remove-edge A:B \| move T:before/after:M"` | EXISTS (`cli/debug/__init__.py:21649`); target identity comes from `--what-if`, NOT `--ig` (§10/finding-10); **one perturbation per call, no enumeration** |
| Heuristic source-lever guidance | `melee-agent debug suggest register-tiebreak` (`cli/debug/__init__.py` ~19449) | EXISTS (guidance, not surrogate-checked) |
| ig→virtual→source bridge | `melee-agent debug inspect explain-virtual -f FN --ig N[,N] [--class fpr]` (~21922); `explain_virtuals` builds `source` opportunistically in `virtual_attribution.py:603,661` | EXISTS; **best-effort — `source` can be None** (drives the §6 non-actionable rule) |
| force-phys replay (intervention) | `debug dump local --force-phys "class:ig:reg,..." [--force-phys-iter]`; force-phys-from-diff in `cli/debug/__init__.py` ~341/390 | EXISTS; byte-exact proofs for 8024714C, OnFrame, 80247510 |
| Per-function register-only classifier + target-map collection | `melee-agent debug target order-target` → `_collect_order_target_inputs` (`cli/debug/__init__.py:1565`) → `derive_order_target` (`mwcc_debug/order_target_derive.py`) | EXISTS; REUSED as precondition |
| IG / COLORGRAPH / LIVERANGES dumps | mwcc-debug pcdump (`debug dump local`), `colorgraph_parser.py`, `tiebreak.parse_live_ranges` (#549) | EXISTS; interferer print cap 512, list truncation flagged `incomplete` |
| Directed-search plumbing to reuse | `tools/melee-agent/src/search/directed/{contracts.py,gate.py,kill_switch.py,order_target.py}`; `DirectedMeta.non_actionable` UNATTRIBUTED discipline at `contracts.py:90` | EXISTS; contracts/gate/kill-switch/attribution patterns reusable |
| Permuter weight handoff | `randomize_funcs` / `weight_overrides` plumbing (`cli/debug/__init__.py` ~6690) | EXISTS; the worksheet feeds this |

**Lever catalog location (important correction, finding 7/8):** the
perturbation→C-realization catalog (`accessor_macro_inline_frame_lever`,
`comma_expr_defeats_licm_hoist`, `mndiagram_levers_and_walls`,
`mndiagram_inputproc_simplify_tiebreak`,
`dispform_inline_base_cast_and_per_loop_locals`,
`call_shape_and_fmadds_operand_levers`) and `reverse_compiler_feasibility.md`
live in the **agent memory dir** `/Users/mike/.claude/projects/-Users-mike-code-melee/memory/`
— they are **NOT git-tracked** and are absent from a clean checkout (codex
confirmed). **v1 deliverable D0:** copy the relevant lever-catalog entries into a
tracked `docs/superpowers/lever-catalog/` so `realize.py` reads tracked data, not
an out-of-tree memory dir. Until D0 lands, all catalog citations in this spec are
agent-memory references, called out as such.

## 1. Perturbation vocabulary

Each perturbation has (i) a surrogate-level encoding applied to the parsed `IG`
before `predict_assignments`, and (ii) zero-or-more candidate C realizations from
the lever catalog. **A surrogate-winning perturbation with no resolvable source
object is non-actionable telemetry, NOT a worksheet candidate** (finding 7): it
is recorded in a separate `tooling_leads` list (the surrogate found a coloring
lever the bridge can't name) and **cannot feed the driver or permuter weights**.
The vocabulary is a superset of the v1 edge/order moves; **v1 DEFAULT enumeration
is node-add + edge + order. Coalesce-veto and standalone ref-bump are NOT in the
v1 default** (finding 6; see 1c/1d).

### 1a. node-add (the new primitive — the project's center of gravity)
- **Concept:** introduce a fresh colorable virtual `V'` holding a COPY of an
  existing value `V`, and route a parameterized USE-SET through it — some subset
  of `V`'s uses now read `V'`. This is what `T* a = x; ... a->f ...` (alias
  introduction) does at the IR level: it splits one virtual's live range into
  two, changing interference and the REF counts that feed coalescing/dispense.
- **Surrogate encoding (the modelling hard part, stated honestly):** the
  surrogate is a SELECT-stage model; it does not build the IG. A node-add is a
  **structural edit to the parsed IG**: insert `V'` into `nodes` and at a
  parameterized `select_order` position; partition `V`'s neighbor set between `V`
  and `V'` per the routed use-set; add the `V`–`V'` edge iff their modelled
  ranges overlap. Because the real partition depends on liveness the surrogate
  can't see, node-add enumerates over a small **partition-hypothesis family**
  (§2 use-set samples), each a distinct surrogate input. This is an
  APPROXIMATION; the §1.5 filter rejects the ones that can't be realized or won't
  survive, and §3 confirms the rest against the rebuilt IG. Node-add predictions
  are lower-confidence than edge/order and MUST clear both §1.5 and §3.
- **C realizations:** alias introduction `T* a = x;` routing specific reads
  (CursorProc gp/flow-alias, `&mn_804A04F0` row-read alias, `&mnDiagram_804A076C`
  comma-alias); temp-for-expr `T t = expr;`; second-genuine-use anchoring;
  per-loop fresh locals (`snap1/saved1, snap2/saved2`); scoped block locals;
  inline-base-cast `((CardBufEntry*)g)[i].f`.

### 1b. edge-add / edge-remove (interference) — from v1, kept (v1 DEFAULT)
- **Surrogate encoding:** already implemented (`extra_neighbors`, `removed_edges`).
  Add/drop one edge between complete, non-precolored virtuals.
- **C realizations:** make/break a live-range overlap by moving a definition or
  use across the other value's range (statement-hoist-sink). Honest caveat: edge
  structure is a WEAKER source lever than node-set, because the C move that
  creates a specific edge is indirect. Edge moves rank below node-set in §2.

### 1c. REF-count bump — annotation only (NOT a standalone v1 kind)
- **Concept:** MWCC's coalescing/dispense consume REF counts (the `stmw r17→r14`
  ref-count effect, agent memory `cardstate_iter12_volatile_index_and_decl_chain.md`).
- **Surrogate encoding:** the SELECT surrogate does not model coalescing or
  ref-driven dispense weights. A ref-count change is encoded ONLY through a
  node-add (it is an annotation on a node-add candidate describing the REF delta
  the C realization implies), never independently scored. This is a known
  fidelity gap handled by §3.
- **C realizations:** introduce/delete a local so a value is read N±1 times
  (`DELETE phys=i+1` / inline-`i+1`; the 80241E78 `(f32)digit through base temp`).

### 1d. coalesce-veto — DEFERRED out of v1 default (finding 6)
- **Concept / encoding:** model the un-coalesced state by treating a coalesce
  ghost as a distinct colorable node, or model forced coalescing by merging two
  nodes. Both are structural IG edits + a select_order edit.
- **Scope:** coalescing is the single largest unmodelled upstream stage (§3).
  Including the riskiest stage in the first milestone would make node-add
  validation un-interpretable. **Coalesce-veto is NOT enumerated by default in
  v1.** It is gated behind `--experimental-kinds coalesce`, excluded from the v1
  acceptance gate (§4/§6), and revisited only AFTER node-add precision is
  calibrated (§1.5 spike). Its C realizations (per-loop fresh locals,
  inline-base-cast) remain reachable via node-add in the meantime.

### 1e. select-order perturbation — from v1, kept but DEPRIORITIZED
- **Surrogate encoding:** already implemented (`move_before/move_after`).
- **Status:** kept for completeness and the rare future `directed`-routing
  function, ranked LAST: the 0/13 order census means an order-only perturbation
  the surrogate likes is unlikely to have a byte-eliminating C realization. The
  worksheet still emits it (flagged with the census caveat) and can hand a
  simplify-order objective to the existing order tooling; it is not the bet.

## 1.5 Enumeration-time validity filter (the upstream model built INTO proposal generation — codex BLOCKER fix)

The codex BLOCKER: §3 catches bad node-add proposals only AFTER the driver writes
C and rebuilds — so a SELECT-only surrogate emits mostly upstream-invalid
proposals that burn the apply/verify budget. **Fix: encode the
empirically-derived upstream laws as a predicate that runs at enumeration time,
so invalid node-adds are never emitted.** This is the proposal-QUALITY gate
codex says is missing, distinct from the §3 attribution gate.

The model has two corpus-validated laws (today's empirical results); each is
encoded as a per-candidate check applied BEFORE `predict_assignments`:

**(L1) Interference survival law** — corpus-validated over 8,888 matched
functions (agent memory / `/tmp/doorA-corpus-mine-report.md`): *a same-value copy
survives in emitted code iff the original and the copy INTERFERE* — the original
keeps genuine uses PAST the copy's first use, forcing the destination into a
distinct register. The old "(mutated-after-copy OR pressure-remat)" conjunct is
**FALSIFIED as necessary**: counterexample `ftCo_800DDDE4` (`ftCo_Throw.c:528`)
survives a never-mutated pointer copy `fp4 = fp2` purely because the source `fp2`
is itself live past the copy point. Interference is the necessary-and-sufficient
IR condition and is **source-controllable**.
> **Survival check** — for the routed use-set, require `V` (the original) retain
> ≥1 genuine use past `V'`'s first use in the modelled order; reject
> "coalesce-bait" partitions where all later uses route through `V'` (those
> provably coalesce, per the failed A1 probes). This is the single highest-value
> reject — exactly why the prior blind `int keep = V;` probes were inert.

**(L2) Source-realizability preconditions** — probe-validated on the three
blocked sites (`/tmp/doorA-probe-report.md`): an interference-creating node-add is
realizable from C only when
- **(a) the value is RUNTIME**, not a compile-time constant — a constant gets
  `li`/`lis` rematerialized regardless of aliasing (HandleInput S2: a compile-time
  `0`; every algebraic-zero spelling folds; the DIAG probe `result & 1` flips it
  to the target held-`stb r28` form). **Check:** reject if `V` is li/lis-defined
  with no runtime dependence (the order-target register-diff exposes the def).
- **(b) the split point is CALLER-VISIBLE**, not inside an inlinee — `80242C0C
  +13c` needs a split inside `HSD_JObjSetTranslateX`'s inlined parameter web; no
  caller-level variable boundary reaches it and every caller-side spelling
  copy-propagates away. **Check:** reject if `explain-virtual` marks `V`'s split
  point intra-inline / cannot resolve a caller-level source object (this also
  satisfies the §6 non-actionable rule).
- **(c) the residual is genuine pressure/interference, NOT pure allocation-window
  order** — CreateStatRow's copy ALREADY survives; the residual is the callee-save
  window base (target r21 vs ours r22) and a genuine 11th live callee-save did NOT
  descend the base, proving node-processing ORDER not pressure. **Check (flag, not
  hard reject):** if force-phys shows the copy already survives and the residual
  is only the window base, flag `residual=allocation-window`, DEPRIORITIZE, and
  steer toward BANK — the surrogate can still be asked whether a window-base shift
  is reachable.

**Expected invalid-proposal rate, with vs without the filter (argued from
probe data, finding 1):** the three unfiltered blocked-site probes were ALL
invalid, each for a precondition the filter catches — CreateStatRow violates (c)
[window-order], 80242C0C violates (b) [intra-inline], HandleInput S2 violates (a)
[constant]. So on the observed sample the unfiltered node-add proposal stream was
**3/3 invalid (100%)**, and all three are caught by checks (a)/(b)/(c). We do not
claim a precise filtered rate from n=3; we claim (i) the filter eliminates the
entire observed invalid class, and (ii) the §1.5 spike (below) MEASURES the
post-filter proposal-confirmation rate on the two archived WIN fixtures before
the full enumeration is declared usable.

**What the model does NOT cover (the §3 remainder):** (i) REF-count effects on
dispense order (a node-add changes how many times `V` is read; the surrogate
doesn't model ref-driven dispense weights); (ii) coalesce weights (which of two
coalesce candidates wins); (iii) hidden temp-creation order incl. deleted temps
(`ft_800852B0` dead-temp dispense). The filter handles realizability and
survival; these three residual effects are why a filtered, surrogate-winning
node-add is still a PROPOSAL until §3 re-extracts the real IG. The two gates are
complementary: §1.5 makes the proposal stream mostly valid; §3 confirms the few
that survive and records the rest as MODEL-GAP data.

**Calibration spike (BLOCKING phase before full build — finding 1):** before
`enumerate.py` is wired into a driver/permuter application loop, run the filter +
surrogate on the two archived pre-win fixtures (CursorProc, 80241E78). **Gate to
proceed:** the known alias node-add must appear in the top-N=8 ranked rows on
BOTH fixtures, AND the post-filter proposal-confirmation rate (surrogate-winning
filtered proposals that §3 confirms) must be measured and reported. If the known
win is NOT recovered in top-8 on either fixture → the node-add encoding or filter
is wrong; FIX before building enumeration. This mirrors the order loop's
eligibility-witness gate.

## 2. The solve loop (per function)

```
solve_coloring(FN):
  1. PRECONDITION (reuse existing tooling):
     - debug target order-target FN → require routing ∈ register-only admit set
       (operand-register-or-offset / backend-ceiling / normalized-structural-match);
       capture phys_target = {orig_ig: desired_phys} (force-phys-from-diff).
     - require force-phys replay of phys_target byte-eliminates the residual
       (REACHABLE proof). If force-phys collides (32:26-style) → ABSTAIN (exit 3):
       target unreachable, the escape is a structurally different virtual.
  2. EXTRACT real IG: load_ig(pcdump, FN, class_id) → IG (observed order,
     neighbor sets, precolored/ghost blockers, incomplete flags).
     - validate_g1(ig) MUST be 100% on COMPLETE nodes; else → ABSTAIN (exit 3:
       truncation/spill corrupts dispense, what-ifs untrustworthy).
  3. ENUMERATE single perturbations (bounded, §2.1 generators):
     for kind in [node-add, edge-add/remove, order(last)]:   # coalesce NOT default
       for candidate value V in implicated_nodes(phys_target):   # see §2.1
         for use_set in use_set_family(V):                       # node-add only
           if not passes_1_5_filter(V, use_set): continue        # §1.5 — reject early
           for pos in insertion_positions(V, use_set):           # bounded, §2.1
             ig' = apply(ig, perturbation)
             assigns = predict_assignments(ig')
             record (perturbation, assigns, #targets_met = |assigns ∩ phys_target ⊇|)
     - keep FULL hits (assigns ⊇ phys_target) AND partial hits (for §2.5 frontier).
  4. RANK kept FULL hits by C-REALIZABILITY (all already meet the full target):
       (a) named lever-catalog realization WITH a resolved source object
           (node-add alias > temp-for-expr > anchoring > per-loop-local >
           inline-base-cast) — highest;
       (b) edge realization (weaker source lever) — middle;
       (c) order realization (census caveat) — lowest actionable.
     Perturbations with NO resolved source object → tooling_leads (NON-actionable,
     never ranked into the worksheet — finding 7).
     Tie-break by perturbation SIZE then assignment churn (smaller blast radius).
  5. ESCALATE to PAIRS when there is NO actionable high-confidence single
     (finding 3) — NOT merely on zero surrogate hits. "Actionable
     high-confidence single" = a FULL hit with a resolved-source-object node-add
     or edge realization (tier a/b) that passed §1.5. A worksheet containing only
     tooling_leads / order-only / proposal-tier rows does NOT suppress pairs.
     - Frontier: top-F single-perturbation PARTIAL-satisfaction results (ranked
       by #targets_met then churn), compose only within that set. **F is a
       tunable parameter (default 32), recorded in output and calibrated by the
       §2.1/spike telemetry — NOT asserted as correct** (finding 3).
     - Cap 200k surrogate evals total (single + pair); print when the cap was hit
       and that results are TRUNCATED (finding 2).
  6. EMIT the worksheet (§6): ranked actionable hits + tooling_leads +
     pair_escalation block. Never auto-applied.
```

### 2.1 Bounded generators (every search dimension capped — finding 2)

The bound is **O(|implicated| × kinds × |use_set_family| × |insertion_positions|)**
with a 200k eval cap. Each dimension is explicitly generated and capped:

- **implicated_nodes(phys_target):** the phys_target nodes AND their 1-hop
  neighbors in the IG. **Open risk codex raised (finding 2):** a useful source
  alias's effect may be mediated through a NON-neighbor blocker, so the 1-hop set
  could miss it. **The §1.5 spike MUST check** whether the known 80241E78 and
  CursorProc alias source nodes fall inside the 1-hop implicated set on the
  archived pre-win dumps; if either falls outside, widen to 2-hop (capped at 64
  nodes) and re-measure. This is a spike acceptance sub-criterion, not an
  assumption.
- **use_set_family(V)** (node-add only): a FIXED small family, NOT the power set
  — {all-uses-after-first-def, all-uses-in-innermost-loop, single-hottest-use,
  uses-past-the-conflicting-neighbor's-def}. Bounded at 4 per V. Open question 2
  (derive from #549 LIVERANGES instead) remains a spike option.
- **insertion_positions(V, use_set):** NOT every select slot. Two positions per
  candidate — {immediately-before-V's-original-slot, immediately-after}. The
  select-order position of a split is a coarse lever (the v1 before/after slot
  distinction); finer positions are not enumerated in v1. Capped at 2.
- **coalesce split family:** N/A in v1 default (coalesce-veto deferred). When
  `--experimental-kinds coalesce` is set, the split family is {ghost-as-separate,
  forced-merge} — 2 per ghost, no finer partition.
- **200k-cap truncation behavior:** enumeration proceeds kind-by-kind in priority
  order (node-add first); if the cap is reached mid-kind, the partial results for
  completed kinds are kept, the truncation is recorded in the worksheet
  (`enumeration_truncated: true, last_kind, evals`), and exit code is still 0/4
  per whether an actionable hit was found in the completed portion.

## 3. Fidelity guards (post-application attribution — the §1.5 remainder)

§1.5 filters proposals at enumeration time. §3 is the AFTER-application gate that
confirms a surrogate-winning, filtered proposal once the driver has actually
written the candidate C move and rebuilt — it handles the model remainder
(REF/coalesce/temp-order effects §1.5 can't see). A node-set perturbation the
surrogate likes is a **PROPOSAL, not a result**, until §3 clears it.

1. **Re-extract the REAL IG** from a fresh `debug dump local` of the patched
   source. Confirm the perturbation is present: node-add → the new virtual exists
   with (approximately) the routed use-set; edge → the edge changed. This is the
   "did we actually add that node/edge" check (the highest-leverage amendment
   from `reverse_compiler_feasibility.md`).
2. **Re-run G1** on the new IG; must stay 100% on complete nodes. If broken, the
   prediction for the patched function is void — STOP.
3. **Compare predicted vs actual assignments** on the patched IG. Three outcomes,
   each recorded honestly:
   - present + match target → **surrogate-confirmed win**.
   - present + DIFFER → **surrogate fidelity miss**: the perturbation landed but
     an upstream effect §1.5 couldn't model changed the outcome. Record as a
     counterexample with the divergence — a MODEL GAP datum (per orchestration
     doctrine: divergence = MODEL GAP, NOT "MWCC quirk"). These data refine §1.5.
   - perturbation absent → **realization miss**: the lever-catalog mapping was
     wrong for this shape (not the surrogate). Refine the C realization, retry.

A no-op perturbation (one that doesn't change the IG) is **UNATTRIBUTED** and can
NEVER be a win, reusing `DirectedMeta.non_actionable` discipline
(`contracts.py:90`).

**Known fidelity risks (state in output, do not paper over):**
- **Variant-specific `ig_idx`:** ig identity / current assignments differ across
  source variants (the v1 `r27`-for-ig90 cross-variant bug). The target map MUST
  be re-derived from the EXACT committed variant being matched (the order-target
  collector dumps THAT variant).
- **Hidden bookkeeping:** temp creation order (incl. DELETED temps —
  `ft_800852B0` dead-temp dispense), REF counts (`stmw r17→r14`), coalesce/spill
  weights. §3 re-extract is the only ground truth for these.
- **Coalescing is upstream of select and unmodelled:** the surrogate sees
  coalesce ghosts only as resolved blockers. This is why coalesce-veto is
  deferred (§1d) and why node-add stays PROPOSAL-tier.
- **Liveness the surrogate can't see:** interference is a backward
  per-instruction intra-block walk; block-boundary live-out (#549 LIVERANGES)
  explains only ~47% of edges (`validate_glr` docstring). The node-add use-set
  partition is a hypothesis family, not a derived fact.

## 4. Per-function gate criteria

- **When to RUN:** checkdiff classifies register-only (admit set above) AND
  force-phys replay of the derived target map byte-eliminates the residual
  (REACHABLE). Both are existing `debug target order-target` outputs. (The order
  classifier routing `not_order_class` is EXPECTED and FINE — it means
  "not order-class", precisely this pool. We gate on register-only admission +
  force-phys reachability, not on order routing.)
- **When to ABSTAIN immediately (exit 3):** force-phys collision (target
  unreachable); G1 < 100% on complete nodes (truncation/spill corrupts dispense).
- **When to BANK (exit 4):** see §4.1 — this is a BUDGET outcome, not an
  absence proof.

### 4.1 BANK is a budgeted no-candidate, NOT a trustworthy absence proof (finding 4)

Exit-4 fires when **no actionable single (size 1) and no actionable pair within
the top-F frontier (size ≤ K) recolors to the target, within the 200k eval cap,
the §2.1 generators, and the §1.5 filter.** The language is deliberately
**"budgeted no-candidate within K / frontier / sampling,"** NOT "trustworthy
bank." Rationale and honest limits:

- **K is a BUDGET, argued from the corpus, not a proof.** The campaign-win corpus
  is single-move (one alias, one temp, one comma) or an occasional two-move chain
  (the cardstate decl chain peels one callee-save per reorder — node-set/content,
  modelled here as composed node-adds). **Default K = 2** covers the observed
  distribution. K≥3 explodes the pair frontier past the 200k cap without corpus
  evidence that a SINGLE human-writable reshape maps to 3 coupled coloring moves.
- **Open: K=3 / sequential-vs-coupled (open question 3, unresolved).** The
  cardstate decl-chain is the test case: is it ONE K=3 perturbation or THREE
  independent K=1 worksheets applied in sequence? **v1 policy:** treat it as
  sequential K=1 — emit one worksheet, let the driver apply + re-extract, then
  RE-RUN solve on the patched source for the next move. A genuinely coupled K=3
  (no K=1 prefix improves the score) is OUT of v1 reach and is recorded as such
  when partial-frontier telemetry shows no improving K≤2 prefix.
- **BANK is promoted from "budgeted no-candidate" to a confident redirect ONLY
  after the calibrated negative controls (§6) pass** — i.e. once we've shown on
  CreateStatRow (window-order) and 8024714C (FPR ceiling) that the solver returns
  exit-4 for the RIGHT reason (filter (c) / no realizable ≤K move) and not
  because of an empty or over-conservative search. Until then exit-4 is reported
  verbatim as "no candidate within budget K=2/F=32/200k + §1.5 filter," with the
  frontier printed so a human can judge.

- **Expected cost per function:** surrogate enumeration is µs/eval, sub-second.
  The real cost is §3: one `debug dump local` re-extract per candidate the driver
  actually writes (~2s build each) — cost scales with worksheet rows tried, not
  enumeration. Precondition force-phys reachability is one dump. Total: a few
  builds per function vs the 23k-iteration blind permuter runs this replaces.

## 5. FPR support (explicit scope, per issue #573)

- The surrogate CORE is class-agnostic: `_register_pools` returns FPR pools and
  `load_ig`/`build_ig` accept `class_id=1`; `inspect tiebreak --class fpr` /
  `f`-prefixed ig tokens load the class-1 COLORGRAPH. So the solve loop CAN run
  on FPR functions.
- **State correction (finding 9):** the substrate is **"FPR path present; corpus
  G1 UNPROVEN."** The FPR dispense rule has been spot-validated (the #573
  workaround hand-simulated class-1 picks, confirmed via `--force-phys
  '1:46:31,...'` byte-exact), but a **dedicated G1=100% FPR validation sweep
  across the matched corpus is the first deliverable** before trusting FPR
  what-ifs the way we trust GPR. The 8024714C pilot (§6) is FPR precisely to
  exercise this. If the FPR G1 sweep is < 100% on any clean fixture → HARD STOP
  and fix the FPR dispense reading (same contract as the GPR G1 gate); do not
  relax.
- **Terminology (finding 9):** in this spec "FPR" always means floating-point
  registers (class 1). The proposal-precision metric (how many filtered
  surrogate-winning proposals §3 confirms) is a SEPARATE quantity, called
  **proposal-confirmation rate** throughout — G1 does NOT measure it.

## 6. Pilot plan (named functions + mandatory negative controls)

Pilots span the confidence tiers, the GPR/FPR axis, and — per finding 5 — include
**negative controls a broken solver CANNOT pass**. Each pilot states pass/fail
criteria. Pilots are derived from the live pool at implementation time and
re-verified against FRESH upstream (`verify-unmatched-against-fresh-upstream`);
the #2660 merge may have moved functions.

**WIN-expected**
1. **mnDiagram_80241E78 (GPR + node-set; expected WIN, partly validated).** Its
   residual was cracked blind to 99.88% by `data_alias at loop-tail AddChild +
   (f32)digit through base temp` (commit `c1aea2d0c`) — alias introduction (1a) +
   temp-for-expr (1a/1c). **PASS:** the §1.5 filter ADMITS the loop-tail data
   alias (runtime value, caller-visible split, genuine interference) AND the
   surrogate ranks it in top-8, AND §3 confirms it produces the target coloring.
   **FAIL (broken solver caught):** if the solver proposes the alias on this
   known-alias fixture but ALSO passes negative control N2 below, the "always
   propose an alias" failure mode is exposed.

**BANK-expected / negative controls** (a broken/empty/over-conservative solver
must FAIL at least one)
2. **mnDiagram2_CreateStatRow (GPR; expected BANK via §1.5 filter (c)).** Today's
   probe re-bucketed it as an **allocation-window residual**: the copy
   `int r21 = table[0x30]` ALREADY survives; the residual is the callee-save
   window base (target r21 vs ours r22), and a genuine 11th simultaneously-live
   callee-save did NOT descend the base (`/tmp/doorA-probe-report.md` Probe 1).
   **PASS:** §1.5 check (c) flags `residual=allocation-window`, no node-add passes
   the filter, exit-4 with the window-order reason printed. **FAIL (caught):** a
   solver that manufactures a false alias lever here (treats window-order as
   pressure) FAILS — this is the negative control for filter (c).
3. **mnDiagram3_8024714C (FPR; expected BANK; exercises §5).** f30↔f31 wall,
   f28-spill, confirmed edge-inert by the FPR oracle round (commit `7e2c744df`).
   force-phys `1:...:...` reaches the target coloring (REACHABLE) but edge moves
   don't byte-eliminate. **PASS:** single + pair node-set search within K=2/F=32
   finds NO realizable perturbation → exit-4, AND the FPR G1 sweep was 100%
   (else HARD STOP per §5). **FAIL (caught):** an empty/over-conservative solver
   that returns exit-4 on EVERYTHING also "passes" this — which is why N4/N5
   below are required to distinguish a correct BANK from a dead solver.

**Mandatory synthetic / structural negative controls (finding 5)**
4. **N4 — matched / no-residual function.** Feed a 100%-matched function (no
   residual, empty phys_target). **PASS:** exit-3 ABSTAIN (force-phys target is
   empty / already satisfied), NOT exit-4 and NOT a fabricated candidate. Catches
   a solver that emits levers regardless of input.
5. **N5 — shuffled / unreachable force-phys target.** Take a real function and
   feed a deliberately SHUFFLED phys_target (a coloring force-phys shows
   COLLIDES). **PASS:** exit-3 ABSTAIN (force-phys collision at precondition),
   never a "win." Catches a solver that ignores reachability.
6. **N6 — wrong/no-op alias on a known win.** On the 80241E78 fixture, feed a C
   realization that does NOT create the target node (an alias of a dead value).
   **PASS:** §3 classifies it `realization-miss` (perturbation absent) or the
   no-op is UNATTRIBUTED — never a confirmed win. Catches a §3 gate that rubber-
   stamps.

**Pair-path coverage (finding 5 — pair logic must not stay broken while named
pilots pass)**
7. **N7 — synthetic pair-only IG.** A hand-built `tiebreak.IG` where NO single
   perturbation but exactly one PAIR reaches the target. **PASS:** escalation
   fires (because there is no actionable single), stays within the top-F frontier,
   finds the pair, respects the 200k cap. **FAIL (caught):** if pair escalation
   is gated on "zero surrogate hits" instead of "no actionable single," a
   low-confidence single suppresses it and N7 FAILS — directly testing finding 3.

**Fixture e2e**
8. **mnDiagram_CursorProc (GPR; node-set; §3 end-to-end fixture).** Reached 100%
   via the gp/flow-alias port (merge `ea5da317c`, 99.52→100); pre/post source is
   byte-archived in git history. **PASS:** feed the pre-alias variant → solver
   proposes the gp/flow-alias node-add (top-8, §1.5-admitted) → §3 re-extract on
   the post-alias variant confirms the alias node is present AND assignments
   match. This is the full pipeline regression test.

## 7. Deliverables / CLI shape

- **D0 (prerequisite):** copy the relevant lever-catalog entries from the agent
  memory dir into a tracked `docs/superpowers/lever-catalog/` (finding 7/8) so
  `realize.py` reads tracked data.
- **Primary CLI:** `melee-agent debug solve coloring -f FN [--class gpr|fpr]
  [--pcdump P] [--max-perturb 2] [--frontier 32] [--kinds node-add,edge,order]
  [--experimental-kinds coalesce] [--json]` emitting the ranked C-move worksheet.
  Exit codes: `0` = ≥1 ACTIONABLE perturbation (resolved source object) found;
  `3` = abstain (G1 imperfect / force-phys collision / target truncated — reason
  printed); `4` = no actionable perturbation ≤ max-perturb within frontier/cap/
  filter (budgeted no-candidate — §4.1). JSON for driver consumption.
- **Worksheet schema (JSON):** `{function, class_id, g1_rate, force_phys_target,
  reachable: bool, filter_summary:{candidates_generated, rejected_a, rejected_b,
  flagged_c, rejected_survival}, candidates:[{rank, perturbation:{kind, target_ig,
  use_set?, edge?, order_move?}, predicted_assignment_delta,
  c_realizations:[{lever, source_object, confidence_tier}], surrogate_confidence:
  high|proposal, fidelity_gate: pending}], tooling_leads:[...non-actionable,
  no-source-object surrogate hits...], pair_escalation:{ran:bool, reason,
  frontier_size, frontier:[...]}, enumeration_truncated:bool}`.
- **File layout:** new package `tools/melee-agent/src/search/solver/`:
  - `perturbations.py` — the §1 vocabulary as pure IG-edit functions over the
    `tiebreak.IG` dataclass (node-add, edge, order; coalesce behind a flag).
  - `validity.py` — **the §1.5 enumeration-time filter** (runtime/caller-
    visibility/window-order/survival checks). NEW — the BLOCKER fix.
  - `enumerate.py` — the §2.1 bounded generators, the single + pair enumeration,
    the §1.5 filter call, the 200k eval cap, the frontier.
  - `realize.py` — perturbation → lever-catalog C-realization (reads the tracked
    D0 catalog) + `explain-virtual` source-object lookup + confidence tiering +
    ranking; routes no-source-object hits to `tooling_leads`.
  - `gate.py` — the §3 fidelity gate (re-extract, re-run G1, compare, classify
    confirmed/fidelity-miss/realization-miss; UNATTRIBUTED for no-ops).
  - `worksheet.py` — assemble + serialize.
  - CLI handler under `cli/debug/__init__.py` as `debug solve coloring` (new
    `solve_app` Typer group, mirroring `inspect_app`/`suggest_app`).
  - **Placement:** `src/search/solver/` (NOT `src/mwcc_debug/`) — a SEARCH layer
    over the surrogate (which stays in `mwcc_debug/tiebreak.py`); reuses
    `search/directed/` contracts/gate/kill-switch; produces ranked artifacts like
    the rest of `src/search/`.
- **Reuse from `search/directed/`:** the `DirectedMeta.non_actionable`
  UNATTRIBUTED discipline (`contracts.py:90`), the gate/kill-switch stop-honestly
  patterns, and the force-phys / order-target collection
  (`_collect_order_target_inputs`) for the precondition.
- **Relationship to `suggest register-tiebreak` (finding / open Q6):** `suggest`
  becomes a thin caller of `solve coloring` so there are not two diverging lever
  vocabularies; `solve` supersedes its heuristic output with surrogate-checked,
  §1.5-filtered candidates.

## 8. Non-goals

- **No order-search resurrection.** Order stays in the vocabulary, ranked LAST;
  the bet is node-set/content. The order-distance loop + kill switch stay STOPPED.
- **No global compiler inversion.** Stage-wise (SELECT) surrogate + filtered
  proposal enumeration only.
- **No automatic source synthesis.** The worksheet feeds humans / drivers /
  permuter weights; a human or the permuter writes and verifies the C. §3 runs on
  the driver's WRITTEN candidate.
- **No IG-construction model.** §1.5 is a realizability+survival FILTER over
  proposals, not a forward model of ig_idx / creation order from source. node-add
  is a structural IG edit confirmed by re-extract.
- **No coalescing/spill-weight solver.** Those stages are upstream of select and
  unmodelled; coalesce-veto is deferred behind a flag (§1d) and never in the v1
  acceptance gate.
- **No DLL changes** beyond what exists (interferer print cap already 512; widen
  only if truncation blocks a forcing case).

## 9. Test strategy

- **§1.5 calibration spike (BLOCKING — must pass before enumeration is wired to a
  driver):** filter + surrogate on CursorProc + 80241E78 pre-win fixtures; known
  alias in top-8 on BOTH; proposal-confirmation rate measured + reported; 1-hop
  implicated-set sufficiency checked (widen to 2-hop if a known alias source is
  outside). Gate: ≥1/2 fixture-recovery → proceed; 0/2 → fix encoding/filter.
- **FPR G1 sweep (gate before any FPR pilot):** `validate_g1` on every class-1
  COLORGRAPH in the matched-corpus cache → 100% on complete nodes. <100% on a
  clean fixture = HARD STOP (§5).
- **Fixtures (natural IG + known node-add win both exist):** CursorProc pre/post
  (`ea5da317c`); 80241E78 pre/post (`c1aea2d0c`). Solver proposes the known
  node-add; §3 confirms on the post variant.
- **§1.5 filter (unit):** synthetic IGs proving each reject fires —
  constant-value rejected (a); intra-inline-marked source rejected (b);
  already-survives window-order flagged (c); coalesce-bait all-uses-through-V'
  rejected (survival). Plus an admit case (ftCo_800DDDE4-shaped: runtime,
  caller-visible, genuine interference) that PASSES.
- **Perturbation primitives (unit, no compile):** synthetic IG where a node with a
  specific use-set provably re-colors a target → `enumerate.py` finds exactly
  that node-add; edge-add/remove reproduces the v1 `remove(88,37) → ig88 r26→r25`
  case; order move reproduces the v1 synthetic.
- **Gate (§3) classification:** mocked re-extract → (a) present+match=confirmed;
  (b) present+differ=fidelity-miss recorded as MODEL GAP; (c) absent=realization-
  miss; no-op=UNATTRIBUTED.
- **Exit codes + negative controls:** 0/3/4 with a mocked surrogate; the §6
  negative controls N4 (matched fn → exit-3), N5 (shuffled target → exit-3), N6
  (no-op alias → not-a-win), N7 (pair-only IG → escalation fires because no
  actionable single, NOT because zero hits).
- **Pair escalation gating (regression for finding 3):** an IG with a
  low-confidence/tooling-lead single AND a true actionable pair → pairs MUST run
  (single did not suppress them).

## 10. Open questions flagged for review

1. **1-hop implicated-set sufficiency.** Codex finding 2's hypothesis: a useful
   alias's effect may be mediated through a non-neighbor blocker, so 1-hop misses
   it. RESOLVED INTO a spike acceptance sub-criterion (§2.1): check the archived
   80241E78/CursorProc alias source nodes against the 1-hop set; widen to 2-hop
   (cap 64) if outside.
2. **Use-set sampling family.** The fixed family (after-first-def / innermost-loop
   / hottest-use / past-conflicting-def) is a guess. Derive from #549 LIVERANGES
   (even at ~47% edge coverage) instead? Trade-off: liveness-derived samples are
   fewer / better-motivated but block-resolution only. Spike option.
3. **K=3 / sequential-vs-coupled.** Is the cardstate decl-chain one K=3
   perturbation or three sequential K=1 worksheets? v1 policy = sequential K=1
   (re-run solve on patched source); coupled K=3 is out of v1 reach and recorded
   as such (§4.1). Confirm the policy is acceptable.
4. **Frontier size F.** Default 32, parameterized and telemetry-calibrated (§2.1).
   Is there a principled F from the spike's partial-satisfaction distribution, or
   does it stay an empirical knob?
5. **explain-virtual bridge fragility.** No-source-object surrogate hits go to
   `tooling_leads` (non-actionable, §6/finding 7). Confirm tooling_leads is
   useful signal to a driver, not noise to suppress entirely.
6. **`suggest register-tiebreak` subsumption.** v1 plan: `suggest` becomes a thin
   caller of `solve coloring` (§7). Confirm vs keeping two commands.
7. **Pilot #4 / extra multi-target pilot.** If a fresh `extract list` shows an
   in-pool allocator-cascade GPR partial (GetRanked*/GetLeastPlayed*) verified
   against upstream, add it as a real (non-synthetic) pair-escalation pilot
   alongside N7. Derive at implementation time.

---

## Appendix A — Review disposition (codex finding # → spec change)

| # | Severity | Disposition (detail in cited section) |
|---|---|---|
| 1 | BLOCKER | **ADDRESSED — §1.5 + §9 spike.** Enumeration-time validity filter (law L1 + preconditions (a)/(b)/(c)) runs pre-`predict_assignments`; BLOCKING calibration spike (known alias in top-8 on both fixtures + measured proposal-confirmation rate) before enumeration is driver-wired. Invalid-rate argued from probe data (3/3 unfiltered probes invalid, each caught by (a)/(b)/(c)); §1.5 states the uncovered remainder (REF/coalesce/temp-order) and that §3 handles it. |
| 2 | MAJOR | **ADDRESSED — §2.1.** All dimensions capped: insertion_positions=2, implicated=1-hop (spike-checked widen-to-2-hop, open Q1), use_set_family=4, coalesce-split N/A in v1, explicit 200k-cap truncation. |
| 3 | MAJOR | **ADDRESSED — §2 step 5 + N7.** Pairs fire when no ACTIONABLE high-confidence single (not on zero hits); F parameterized (`--frontier` 32, calibrated, not asserted); N7 + regression test enforce it. |
| 4 | MAJOR | **ADDRESSED — §4.1.** Exit-4 reframed "budgeted no-candidate within K=2/F=32/200k/filter"; K=2 = corpus-argued BUDGET with sequential-K=1 escalation (coupled K=3 out of v1, recorded); BANK→confident redirect only after §6 controls pass. |
| 5 | MAJOR | **ADDRESSED — §6.** Mandatory controls: N4 matched→exit-3, N5 shuffled→exit-3, N6 no-op alias→not-a-win, N7 pair-only→escalation fires; per-pilot PASS/FAIL catch the always-alias / empty-solver / skips-pairs failure modes. |
| 6 | MAJOR | **ADDRESSED — §1d.** Coalesce-veto out of v1 default + acceptance gate; behind `--experimental-kinds coalesce`; v1 default kinds = node-add + edge + order; its C realizations still reachable via node-add. |
| 7 | MAJOR | **ADDRESSED — substrate note + §6/§7.** (i) Lever catalog + `reverse_compiler_feasibility.md` are agent-memory, NOT git-tracked (confirmed); deliverable D0 copies them to tracked `docs/superpowers/lever-catalog/`. (ii) No-source-object hits → non-actionable `tooling_leads`, never fed to driver/permuter. |
| 8 | MAJOR | **ADDRESSED — opening + substrate table.** Prior spec = G1-validated PREDICTOR + manual single-`--what-if` CLI; no `solve`/`enumerate`/`worksheet`/200k/depth-2 code today (verified). This is a NEW layer over a predictor; no solver behavior cited as existing. |
| 9 | MINOR | **ADDRESSED — table + §5.** FPR row = "path present; corpus G1 UNPROVEN"; corpus sweep is first FPR deliverable + HARD STOP; "FPR"=float registers, proposal precision = separate "proposal-confirmation rate". |
| 10 | MINOR | **ADDRESSED — table.** What-if TARGET comes from `--what-if`; `--ig` is "report context only" (verified vs CLI help `cli/debug/__init__.py:21655`). |

**Findings REJECTED:** none. All 10 are accepted and addressed; the two MINORs
(9, 10) and the substrate overclaims (7, 8) were corrected against the verified
checkout rather than argued away. The only items deliberately left as
parameterized/open rather than fixed-in-spec are F (frontier size) and the
use-set family derivation — both are explicitly flagged as spike-calibrated
knobs (open Qs 2, 4), which is the honest state given no corpus telemetry for
them yet.
