# Surrogate-as-solver: inverse register coloring via IG perturbation search

**Date:** 2026-06-12 · **Status:** REV 3 — incorporates the project owner's
review of rev 2 (rev 2 = REVISED post-codex-review). See Appendix A for the
codex finding-by-finding disposition AND the "Rev 3 — owner review disposition"
subsection. · **Forcing class:** the ~10/18 remaining mndiagram-module partials
that classify
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
  mostly realizable instead of mostly junk** (§1.5); and
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
| Lever-catalog (perturbation→C-realization) | agent memory dir (untracked); read by `realize.py` via `--catalog-dir` | UNTRACKED; spike uses `--catalog-dir`, units use inline fixtures, D0 tracks it post-calibration (finding rev2-5) |

**Lever catalog location (important correction, finding 7/8):** the
perturbation→C-realization catalog (`accessor_macro_inline_frame_lever`,
`comma_expr_defeats_licm_hoist`, `mndiagram_levers_and_walls`,
`mndiagram_inputproc_simplify_tiebreak`,
`dispform_inline_base_cast_and_per_loop_locals`,
`call_shape_and_fmadds_operand_levers`) and `reverse_compiler_feasibility.md`
live in the **agent memory dir** `/Users/mike/.claude/projects/-Users-mike-code-melee/memory/`
— they are **NOT git-tracked** and are absent from a clean checkout (codex
confirmed). **v1 deliverable D0 (POST-calibration cleanup — NOT spike-blocking;
finding rev2-5, DECISION = option b):** copy the relevant lever-catalog entries
into a tracked `docs/superpowers/lever-catalog/` so `realize.py` reads tracked
data, not an out-of-tree memory dir. D0 sequencing is explicit:
- **Unit tests** (the §9 perturbation/filter/gate units) use **INLINE fixture
  catalogs** — each test carries the lever entries it needs; no catalog dir
  dependency, so units never block on D0.
- **The §1.5 calibration spike's C-realization step** reads the agent memory-dir
  catalog via an explicit `--catalog-dir` parameter (defaulting to the memory
  dir), so the spike runs against the live catalog WITHOUT D0 first.
- **D0 (the curated copy into tracked `docs/superpowers/lever-catalog/`) is
  POST-calibration cleanup**: required BEFORE the driver-wiring milestone (so the
  shipped `realize.py` default reads tracked data), but it does NOT block the
  spike.
Until D0 lands, all catalog citations in this spec are agent-memory references,
called out as such.

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

## 1.5 Enumeration-time validity filter (the upstream model built INTO proposal generation)

The problem: §3 catches bad node-add proposals only AFTER the driver writes
C and rebuilds — so a SELECT-only surrogate emits mostly upstream-invalid
proposals that burn the apply/verify budget. **Fix: encode the
empirically-derived upstream laws as a predicate that runs at enumeration time,
so invalid node-adds are never emitted.** This is the proposal-QUALITY gate,
distinct from the §3 attribution gate.

The model has two corpus-validated laws (today's empirical results); each is
encoded as a per-candidate check applied BEFORE `predict_assignments`:

**(L1) Interference survival law** — corpus-validated over 8,888 matched
functions (agent memory / `/tmp/doorA-corpus-mine-report.md`): *a same-value copy
survives in emitted code iff the original and the copy INTERFERE* — the original
keeps genuine uses PAST the copy's first use, forcing the destination into a
distinct register. The old "(mutated-after-copy OR pressure-remat)" conjunct is
**FALSIFIED as necessary**: counterexample `ftCo_800DDDE4` (`ftCo_Throw.c:528`)
survives a never-mutated pointer copy `fp4 = fp2` purely because the source `fp2`
is itself live past the copy point. Interference is the necessary
IR condition the filter checks, and is **source-controllable**.
> **Interference is NECESSARY; REF-count-driven coalescing decisions are an
> additional necessary condition that §1.5 does not model** — a filtered,
> surrogate-winning proposal can still coalesce in the real build; that remainder
> is exactly what §3's post-application IG re-extraction gate catches (see "What
> the model does NOT cover"). The owner-named INTERMEDIATE case is a known
> unmodelled instance: when `V` retains exactly 1 use past `V'` and `V'` has 1
> use, below-threshold coalescing may STILL merge despite the interference the
> filter sees — the §1.5 spike's proposal-confirmation-rate metric quantifies how
> often this (and the other §3-remainder effects) fires.
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
  descend the base, proving node-processing ORDER not pressure. **Check
  (flag-and-quarantine, NOT hard reject — resolves the rev2 flag-vs-reject
  tension):** if force-phys shows the copy already survives and the residual is
  only the window base, window-order candidates ARE still enumerated (data stays
  visible) but are flagged `residual=allocation-window` and ROUTED to a separate
  `window_order` bucket that can NEVER produce an exit-0/apply recommendation (the
  surrogate may still be asked whether a window-base shift is reachable). **If ALL
  surviving hits are window-order-flagged**, the run exits **4 with `reason:
  window-order`** — satisfying the CreateStatRow exit-4 expectation (§6 pilot 2 /
  §1.5 spike) while keeping the data inspectable rather than silently dropped.

**Expected invalid-proposal rate (argued from probe data, finding 1):** the three
unfiltered blocked-site probes were **3/3 invalid (100%)**, each for a precondition
the filter catches — CreateStatRow violates (c) [window-order], 80242C0C violates
(b) [intra-inline], HandleInput S2 violates (a) [constant]. We do not claim a
precise filtered rate from n=3; we claim (i) the filter eliminates the entire
observed invalid class, and (ii) the §1.5 spike MEASURES the post-filter
proposal-confirmation rate before full enumeration is declared usable.

**What the model does NOT cover (the §3 remainder):** (i) REF-count effects on
dispense order (a node-add changes how many times `V` is read; the surrogate
doesn't model ref-driven dispense weights); (ii) coalesce weights (which of two
coalesce candidates wins); (iii) hidden temp-creation order incl. deleted temps
(`ft_800852B0` dead-temp dispense). The filter handles realizability and
survival; these three residual effects are why a filtered, surrogate-winning
node-add is still a PROPOSAL until §3 re-extracts the real IG. The two gates are
complementary: §1.5 makes the proposal stream mostly valid; §3 confirms the few
that survive and records the rest as MODEL-GAP data.

**Calibration spike (BLOCKING phase before full build — findings 1 + rev2-1).**
Before `enumerate.py` is wired into a driver/permuter application loop, run the
FULL solver (`solve_coloring`, §2 — NOT the filter predicates in isolation) on a
PERMANENT set of FIVE solver-level fixtures. Each freezes a real function + IG +
force-phys target and asserts a whole-solver outcome, so the gate exercises
enumeration + filter + ranking together rather than unit-testing one predicate:

- **WIN-RECOVERY (2):** CursorProc and 80241E78 pre-win fixtures — the full
  solver must surface the known alias node-add in the top-N=8 ranked rows on BOTH.
- **REJECT-CONFIRMATION (3):** each a whole-solver run whose enumeration trace must
  show the candidate generated then dropped/flagged for the stated reason —
  **HandleInput-S2 constant-zero** → the `var_r28` node-add is `rejected_a` at
  enumeration (constant `0`, no runtime dependence); **mnDiagram_80242C0C** → the
  `+13c` split inside `HSD_JObjSetTranslateX`'s inlined parameter web is
  `rejected_b` (intra-inline, no caller-level source object); **CreateStatRow** →
  the surviving copy is `flagged_c` (`residual=allocation-window`), no node-add
  passes, exit 4 `reason: window-order` (also pilot 2, §6).

**Gate to proceed — n≥5.** All five must behave as specified (2 win-recoveries
surface the alias in top-8; 3 reject-confirmations reject/flag for the stated
filter reason) AND the post-filter proposal-confirmation rate (surrogate-winning
filtered proposals that §3 confirms) is measured + reported. A win-recovery miss →
node-add encoding/filter is wrong; a reject-confirmation admit → filter too weak;
either way FIX before building enumeration. This calibration gate now rests on
**n≥5 (2 win-recoveries + 3 reject-confirmations)**, replacing the rev2 n=3 base,
and mirrors the order loop's eligibility-witness gate.

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
     - keep FULL hits (assigns ⊇ phys_target) AND partial hits (for the step-5 frontier).
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
     - Cap 200k surrogate evals total (single + pair) WITH RESERVED PER-KIND
       FLOORS (finding rev2-3, §2.1): edge and order each get a guaranteed
       10,000-eval floor; node-add (highest priority) may consume the remainder
       (≥180,000). Print when the cap was hit and that results are TRUNCATED
       (finding 2), and print per-kind evals-consumed.
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
- **200k-cap truncation + RESERVED PER-KIND FLOORS (finding rev2-3):** enumeration
  proceeds kind-by-kind in priority order (node-add first). So the ordering can't
  let node-add exhaust the whole cap before edge/order run, **edge and order each
  get a guaranteed 10,000-eval FLOOR**: node-add is capped at `200,000 − 10,000 −
  10,000 = 180,000`, the two 10k floors are then guaranteed regardless of node-add
  consumption, and any unused floor returns to the pool for the next kind.
  **Tradeoff stated:** the solver TRUSTS the lever-priority ranking (§2 step 4,
  node-set > edge > order) for the BULK allocation — node-add preferentially funded
  per the census — but the floors GUARANTEE an exit-4 "no candidate" can never
  silently mean "lower-priority kinds never evaluated." On mid-kind cap-hit,
  completed-kind results are kept; truncation (`enumeration_truncated: true,
  last_kind, evals`) and per-kind `evals_per_kind:{node-add, edge, order}` are
  recorded so exit-4 shows COVERAGE PER KIND; exit code is still 0/4 per whether an
  actionable hit was found in the completed portion.

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
  exercise this.
- **Sweep procedure (finding rev2-2 — the risk was undersold; STAGED, not a
  blanket "100% or stop"):**
  - **(a) SIZING STEP (first action).** Before committing to the gate, COUNT the
    FPR-COLORGRAPH-bearing matched functions — scan matched-corpus pcdumps for
    `COLORGRAPH` sections containing a class-1 (FPR) register pool and tally those
    with one. This yields N_fpr (the denominator), recorded in the sweep log so
    scope is known up front, not discovered mid-run.
  - **(b) CORPUS = "clean fixtures", not "all matched".** The G1 gate applies only
    to matched fns whose pcdump PARSES UNTRUNCATED and whose COLORGRAPH has
    COMPLETE interferer lists (no `incomplete`/512-cap flags). Truncated/incomplete
    dumps are EXCLUDED from the denominator (same truncation that triggers exit-3
    ABSTAIN) — un-gradeable, not "FPR G1 failures."
  - **(c) TIME-BOXED FALLBACK (if 100% is unobtainable within 3 working days).**
    CHARACTERIZE the failure class: if PRE-FILTERABLE by a static property (e.g.
    FPR spill presence), pre-filter with the exclusion documented in the worksheet
    (`fpr_coverage: filtered`) and PROCEED to the FPR pilot on the clean subset; if
    failures are random/uncharacterizable above **5% of clean fixtures**, the HARD
    STOP stands and **v1 ships GPR-only**. A <100% clean fixture NOT covered by a
    documented static exclusion → HARD STOP + fix the FPR dispense reading (same
    contract as the GPR G1 gate); do not relax.
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
7. **N7 — pair-only IG (construction strategy, finding rev2-7).** A
   `tiebreak.IG` where NO single perturbation but exactly one PAIR reaches the
   target. **Construction — PRIMARY = derive from a REAL IG, not hand-built:**
   take a function where a PAIR was empirically needed — candidate the cardstate
   `fn_803ACD58` decl-chain, where single decl peels each moved exactly one
   callee-save and the win REQUIRED chaining (agent memory
   `cardstate_iter12_volatile_index_and_decl_chain.md`). Extract its IG, find the
   working pair, then **BRUTE-FORCE-CONFIRM no single perturbation reaches the
   target** by running the enumerator itself in EXHAUSTIVE single-perturbation mode
   (no 200k cap / no priority truncation — every single generated by §2.1 must
   miss). Freeze that IG + target as the fixture. **FALLBACK = synthetic
   construction** only if no real pair-case extracts cleanly, with the SAME
   brute-force no-single confirmation required before freezing. **Trap being
   avoided:** a hand-built IG risks being secretly SINGLE-solvable (so the test
   passes for the wrong reason — escalation never needed to fire) OR structurally
   PAIR-UNREACHABLE (so the test can never pass); the brute-force no-single
   confirmation + a known-reachable pair rule both out. **PASS:** escalation fires
   (because there is no actionable single), stays within the top-F frontier, finds
   the pair, respects the 200k cap. **FAIL (caught):** if pair escalation is gated
   on "zero surrogate hits" instead of "no actionable single," a low-confidence
   single suppresses it and N7 FAILS — directly testing finding 3.

**Fixture e2e**
8. **mnDiagram_CursorProc (GPR; node-set; §3 end-to-end fixture).** Reached 100%
   via the gp/flow-alias port (merge `ea5da317c`, 99.52→100); pre/post source is
   byte-archived in git history. **PASS:** feed the pre-alias variant → solver
   proposes the gp/flow-alias node-add (top-8, §1.5-admitted) → §3 re-extract on
   the post-alias variant confirms the alias node is present AND assignments
   match. This is the full pipeline regression test.

## 7. Deliverables / CLI shape

- **D0 (POST-calibration cleanup, NOT spike-blocking — finding 7/8 + rev2-5):**
  copy the relevant lever-catalog entries from the agent memory dir into a tracked
  `docs/superpowers/lever-catalog/` so the shipped `realize.py` default reads
  tracked data. **Sequencing (DECISION = option b):** unit tests use INLINE
  fixture catalogs (no D0 dependency); the §1.5 calibration spike reads the
  live agent memory-dir catalog via `--catalog-dir`; D0 is REQUIRED before the
  driver-wiring milestone but does NOT block the spike.
- **Primary CLI:** `melee-agent debug solve coloring -f FN [--class gpr|fpr]
  [--pcdump P] [--max-perturb 2] [--frontier 32] [--kinds node-add,edge,order]
  [--experimental-kinds coalesce] [--catalog-dir DIR] [--json]` emitting the
  ranked C-move worksheet (`--catalog-dir` defaults to the tracked D0 catalog;
  the spike points it at the agent memory dir).
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
  no-source-object surrogate hits...], window_order:[...flagged
  `residual=allocation-window` hits — informational, never exit-0/apply...],
  pair_escalation:{ran:bool, reason, frontier_size, frontier:[...]},
  enumeration_truncated:bool, evals_per_kind:{node-add, edge, order}}` (per-kind
  coverage — finding rev2-3; `window_order` bucket — minor (c)).
- **`surrogate_confidence: high | proposal` — DEFINED (finding rev2-6).** A
  candidate is `high` iff BOTH hold: **(i)** the surrogate reproduces the FULL
  target assignment vector for EVERY contested register (not just the headline
  node — `predict_assignments(ig') ⊇ phys_target` across all phys_target entries),
  AND **(ii)** the perturbation has a RESOLVED SOURCE OBJECT with a TIER-A C
  realization from the catalog (a named node-add lever — alias / temp-for-expr /
  anchoring / per-loop-local / inline-base-cast — with a concrete source object,
  not None). **Everything else is `proposal`** (partial-vector match, edge/order
  tier, or no resolved source object). **Driver contract:** `high` = an APPLY-NOW
  candidate — the driver MAY go straight to source edit + build; `proposal` =
  INVESTIGATE-FIRST — the driver MUST confirm the source object / C realization
  before editing. (`high` still passes the §3 fidelity gate after the build like
  any candidate; the confidence tier governs whether the driver edits immediately
  vs investigates, not whether §3 runs.)
- **File layout:** new package `tools/melee-agent/src/search/solver/`:
  - `perturbations.py` — the §1 vocabulary as pure IG-edit functions over the
    `tiebreak.IG` dataclass (node-add, edge, order; coalesce behind a flag).
  - `validity.py` — **the §1.5 enumeration-time filter** (runtime/caller-
    visibility/window-order/survival checks). NEW.
  - `enumerate.py` — the §2.1 bounded generators, the single + pair enumeration,
    the §1.5 filter call, the 200k eval cap, the frontier.
  - `realize.py` — perturbation → lever-catalog C-realization (reads the catalog
    via a `--catalog-dir` parameter: the tracked D0 catalog by default, the agent
    memory dir during the pre-D0 spike) + `explain-virtual` source-object lookup +
    confidence tiering + ranking; routes no-source-object hits to `tooling_leads`.
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
- **Relationship to `suggest register-tiebreak` (DECISION — was open Q6,
  resolved):** in v1, `suggest register-tiebreak` BECOMES a thin caller of `solve
  coloring` so there are not two diverging lever vocabularies; `solve` supersedes
  its heuristic output with surrogate-checked, §1.5-filtered candidates. This is no
  longer an open question.

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
  driver):** FULL solver on the five PERMANENT solver-level fixtures (§1.5) — 2
  WIN-RECOVERY (CursorProc + 80241E78: known alias in top-8 on BOTH) + 3
  REJECT-CONFIRMATION (HandleInput-S2 → `rejected_a`; 80242C0C → `rejected_b`;
  CreateStatRow → `flagged_c` + exit-4 `window-order`); proposal-confirmation rate
  measured + reported; 1-hop implicated-set sufficiency checked (widen to 2-hop if
  a known alias source is outside). **Gate (n≥5):** all 5 fixtures behave as
  specified → proceed; any WIN-RECOVERY miss or REJECT-CONFIRMATION admit → fix
  encoding/filter. These fixtures persist as a regression suite, NOT one-shot
  spike scaffolding.
- **FPR G1 sweep (gate before any FPR pilot — staged, §5):** SIZING STEP first
  (count class-1-COLORGRAPH-bearing matched fns = N_fpr); then `validate_g1` on
  every CLEAN class-1 fixture (pcdump parses untruncated, interferer lists
  complete) → 100% on complete nodes. <100% on an unexcluded clean fixture = HARD
  STOP; time-boxed (3-day) fallback = characterize/pre-filter or ship GPR-only
  (§5).
- **§1.5 filter (unit, INLINE catalogs — no D0 dependency):** synthetic IGs
  proving each reject fires —
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
  negative controls N4–N7 (matched fn → exit-3; shuffled target → exit-3; no-op
  alias → not-a-win; pair-only IG → escalation fires because no actionable single,
  NOT zero hits). N7's IG is derived from the real `fn_803ACD58` decl-chain with
  brute-force no-single confirmation (synthetic fallback only if no real pair-case
  extracts) — see §6.
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
   as such (§4.1). Confirm the policy is acceptable. **Expectation note (rev3):**
   the apply→re-solve OUTER LOOP is out of scope for v1 — the driver re-runs
   `solve coloring` MANUALLY on the patched source between sequential K=1 moves;
   the solver itself does not orchestrate the loop. The sequential-K=1 policy
   above is unchanged.
4. **Frontier size F.** Default 32, parameterized and telemetry-calibrated (§2.1).
   Is there a principled F from the spike's partial-satisfaction distribution, or
   does it stay an empirical knob?
5. **explain-virtual bridge fragility.** No-source-object surrogate hits go to
   `tooling_leads` (non-actionable, §6/finding 7). Confirm tooling_leads is
   useful signal to a driver, not noise to suppress entirely.
6. **Pilot #4 / extra multi-target pilot.** If a fresh `extract list` shows an
   in-pool allocator-cascade GPR partial (GetRanked*/GetLeastPlayed*) verified
   against upstream, add it as a real (non-synthetic) pair-escalation pilot
   alongside N7. Derive at implementation time.

*(The rev2 open question on `suggest register-tiebreak` subsumption is RESOLVED in
rev3 — `suggest` becomes a thin caller of `solve coloring` in v1, §7 — and is no
longer listed here.)*

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

### Rev 3 — owner review disposition (rev2 review → spec change)

The project owner reviewed rev 2; each concern maps to a rev-3 change (detail in
the cited section). Where options were offered, the orchestrator DECISION is named.

| # | Owner concern | Where | Disposition (rev3) |
|---|---|---|---|
| 1 | n=3 calibration base too thin | §1.5, §9 | The 2 cleanly-rejectable real probes are now PERMANENT solver-level fixtures running the FULL solver (HandleInput-S2 → reject by filter (a); 80242C0C → reject by (b)), joined to the 2 win-recovery fixtures + CreateStatRow's (c)-flag. **Gate now rests on n≥5 (2 win-recoveries + 3 reject-confirmations).** |
| 2 | FPR G1 sweep risk undersold | §5, §9 | (a) SIZING STEP first (count class-1-COLORGRAPH-bearing matched fns by scanning pcdumps); (b) corpus = "clean fixtures" (untruncated pcdump + complete interferer lists), not all-matched; (c) 3-day time-boxed fallback — pre-filter by static property (`fpr_coverage: filtered`) + proceed, else HARD STOP + ship GPR-only if random failures >5% of clean fixtures. |
| 3 | 200k cap + priority ordering | §2 step 5, §2.1, schema | **DECISION = reserved floors.** Edge + order each get a guaranteed 10k-eval floor (node-add gets ≥180k remainder). Tradeoff stated; `evals_per_kind` in the worksheet shows per-kind coverage so exit-4 can't hide unevaluated kinds. |
| 4 | L1 necessary-not-sufficient | §1.5 L1 | Cross-ref added: interference is NECESSARY, REF-count coalescing is an additional necessary condition §1.5 doesn't model (caught by §3 re-extraction); owner-named intermediate case (V/V' each 1 use → below-threshold merge) recorded as unmodelled, quantified by the spike confirmation-rate metric. |
| 5 | D0 blocking ambiguity | substrate table, §7 | **DECISION = option (b).** Units use INLINE fixture catalogs; spike reads the memory-dir catalog via `--catalog-dir`; D0 (tracked copy) is POST-calibration cleanup, required before driver-wiring but NOT spike-blocking. |
| 6 | `surrogate_confidence` undefined | §7 | DEFINED: `high` = BOTH full target-vector reproduced for every contested register AND a resolved source object with a tier-a realization; else `proposal`. Driver contract: `high` = apply-now, `proposal` = investigate-first. |
| 7 | N7 pair-only construction | §6 N7, §9 | PRIMARY = derive from a real IG (cardstate `fn_803ACD58` decl-chain), find the pair, BRUTE-FORCE-CONFIRM no single reaches target (enumerator exhaustive mode), freeze. FALLBACK = synthetic with same no-single confirmation. Trap stated (secretly single-solvable / pair-unreachable). |
| m | §1.5 header dup | §1.5/opening/§7 | "codex BLOCKER fix" cleaned from header/parenthetical/body; kept only here (finding 1). |
| m | L2 (c) flag-vs-reject | §1.5 (c), schema | Window-order candidates ARE enumerated but quarantined to a `window_order` bucket (never exit-0/apply); if ALL surviving hits are window-order, exit 4 `reason: window-order`. |
| m | Open Q6 | §7, §10 | **DECISION:** `suggest register-tiebreak` becomes a thin caller of `solve coloring` in v1; Q6 removed, old Q7→Q6. |
| m | Open Q3 outer loop | §10 Q3 | Note added: apply→re-solve outer loop out of v1 scope — driver re-runs `solve coloring` manually; sequential-K=1 unchanged. |
