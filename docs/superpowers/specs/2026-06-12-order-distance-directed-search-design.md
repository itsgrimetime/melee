# Order-Distance Directed Search — Design Spec

**Date:** 2026-06-12
**Status:** DRAFT for planning (audit-first inventory complete; pre-plan)
**Author:** spec phase (mndiagram TU-completion campaign)
**Builds on (frozen parents):**
- `docs/superpowers/specs/2026-06-01-directed-search-layer-design.md` (the directed layer — IMPLEMENTED as `tools/melee-agent/src/search/directed/`)
- `docs/superpowers/specs/2026-06-01-fast-directed-search-substrate-design.md` (the substrate — IMPLEMENTED as `tools/melee-agent/src/search/`)
- `docs/superpowers/specs/2026-05-28-role-descriptor-identity-layer-design.md` (the cross-variant identity layer — IMPLEMENTED as `role_descriptor.py`/`role_matcher.py`/`role_reanchor.py`)
- `docs/superpowers/specs/2026-06-10-tiebreak-counterfactual-design.md` (the select surrogate — IMPLEMENTED as `inspect tiebreak`)

**Companion runtime artifact:** `tools/melee-agent/src/search/directed/PHASE1_RESULT.md`
(the honest `NOT PASSED` Phase-1 gate result that this spec must reckon with).

---

## 0. TL;DR for the planner

Almost everything the title implies **already exists**. The order-vector extractor,
the role-anchored identity layer, two distance metrics, the typed-mutator search loop,
the per-candidate reanchored scorer, the remote-permuter producer, and the campaign CLI
(`debug search directed`) are all built and unit-tested (135 green). The Phase-0/1 pilot
ran end-to-end on one function (`grIceMt_801F9ACC`) and produced an honest **NOT PASSED**
verdict.

This spec is therefore **NOT a build of a new tool**. It is (a) a small, surgical set of
wirings that re-aim the existing directed layer at the **order-distance objective the
brief wants** (currently demoted to diagnostic), (b) the **per-pool-function target-vector
derivation** that the layer needs and does not yet have for the mndiagram pool, and (c) a
**decisive validation experiment** that tests whether the order-distance premise survives
the same scrutiny that demoted it the first time. If the validation's metric-descent check
(§6c) fails, **the premise is refuted and we stop** — directed-by-phys-match (already
shipped) remains the recommended path and the pool routes to the existing permuter arm.

Expected implementation size: **~6-9 tasks across 2 plans** (one wiring plan, one
validation/campaign plan). Detail in §9.

---

## 1. Problem + the pool

### 1.1 The wall class

~10 functions across the three `mndiagram` translation units are **FULLNORM-0 coloring
ceilings**: their reconstructed C is structurally byte-perfect (instruction selection,
scheduling, frame, and control flow all match) and the **only** residual is which physical
register each value lands in. That assignment is the output of MWCC's
simplify/select graph-coloring allocator. The select order over the interference graph
determines the assignment; the select order derives from IG-node creation order (`ig_idx`),
which derives from PCode emission order, which derives from front-end statement/temp
creation order. There is no in-allocator knob from C — the lever is the **shape of the C
that changes the front-end emission order**, and finding the spelling that produces the
right order is currently manual (the InputProc campaign spent 52 iterations / 10 drivers /
a 28,812-variant enumeration / 23k blind permuter iterations on exactly this).

The campaigns can **prove each target reachable**:
- `match-iter-first --force-vector` (a.k.a. force-iter-first) reproduces the bytes by
  forcing the target select order — proving the order is the lever and the target is real.
- `force-phys-from-diff` + `score-force-phys` prove the target *assignment* is reachable.

What is missing is **directed search of C-space for the spelling that produces that order**,
with a metric that measures *distance to the proven target order* and descends as edits get
closer. Today that search is a lottery (random permuter spellings) or hand-driven.

### 1.2 The pool (current match %, residual shape)

| Function | TU | Match % | Residual (from campaign notes) |
|---|---|---:|---|
| `mnDiagram_OnFrame` | mndiagram.c | 99.72 | one `r28`↔`r29` pair |
| `mnDiagram_802427B4` | mndiagram.c | 98.84 | reg-only (comma-expr crack history) |
| `mnDiagram_802417D0` | mndiagram.c | 98.03 | reg-only |
| `mnDiagram_CursorProc` | mndiagram.c | 99.52 | reg-only |
| `mnDiagram_80241E78` | mndiagram.c | 98.94 | `r25`↔`r26` + an FP shadow |
| `mnDiagram_8023FC28` | mndiagram.c | 97.82 | reg-only |
| `mnDiagram_8024227C` | mndiagram.c | 94.32 | ~175 reg-only lines (LARGE) |
| `mnDiagram3_HandleInput` | mndiagram3.c | 98.42 | 127 GPR + 17 FPR relabels |
| `mnDiagram2 UpdateHeader` | mndiagram2.c | 95.15 | one transposition |
| `mnDiagram2 AggRank` | mndiagram2.c | 94.11 | two transpositions |

(`AggRank` = `mnDiagram2_GetAggregatedFighterRank`; `UpdateHeader` is the header-update
function in mndiagram2.c — resolve exact symbol at derivation time, §3.) The pool spans
the full difficulty range: single-pair swaps (`OnFrame`, `UpdateHeader`), small multi-role
(`AggRank`, `80241E78`), and one large many-role ceiling (`8024227C`, `HandleInput`). FPR
relabels appear in `HandleInput` and `80241E78`; the role layer is GPR-only today (§3.4, §8).

---

## 2. Existing-pieces inventory (audit-first) + gap analysis

This is the load-bearing section: the design must be the **minimal wiring between existing
pieces**, not a rebuild. Every row below was verified against source (file:symbol) or
`--help` on 2026-06-12 in this worktree.

### 2.1 What EXISTS (verified)

**Order-vector extractor — EXISTS.**
`search/directed/order_metric.py::colorgraph_ranks(pcdump_text, function, class_id) -> {ig_idx: rank}`
reads the last `COLORGRAPH DECISIONS` section and returns 1-based color positions
(`rank = iter_idx + 1`). This *is* "build candidate → DECISIONS dump → vector." The DECISIONS
dump itself is produced by `debug dump local <tu> --function <fn>` (local macOS wibo+DLL;
`debug dump doctor` PASSES in this worktree). Parser: `colorgraph_parser.ColorgraphDecision`
= `{iter_idx, ig_idx, assigned_reg, degree, n_interferers, flags, interferers}`.

**Role-anchored identity layer — EXISTS and is wired into the scorer.**
- `role_descriptor.py::build_descriptors(Compile, class_id) -> {ig_idx: RoleDescriptor}`.
  Identity-core = `first_def_sig` (opcode + reg-normalized operands), `use_site_multiset`,
  `is_param`, `var_name`/`var_confidence`. Allocator-state (`assigned_reg`, `live_range`,
  `use_count`, `spilled`) is explicitly **excluded from identity** (it is what edits change).
- `role_matcher.py::match_roles(ref, cand) -> {ig: RoleMatch}` — exact min-cost-max-flow
  assignment, statuses `MATCHED/AMBIGUOUS/GONE/SPLIT/MERGED/NON_COMPARABLE`.
- `role_reanchor.py::reanchor(TargetSpec, Compile) -> ReanchorResult` — forward+inverse
  round-trip-confirmed `{new_ig: orig_ig}` mapping; non-1:1 / unstable roles routed to
  diagnostics and **excluded** from the force-phys map.
- `role_descriptor.py::build_target_spec(...) -> TargetSpec` persists the target with
  `role_order_rank` per role and a `RoleDescriptor` per role; `TargetSpec.save_json/load_json`.

**Distance metrics — TWO EXIST.**
- `search/directed/metric.py::order_distance(cand_iter_by_ig, objective_iter_by_ig) -> int`
  — **Kendall pairwise inversions** over shared role-matched igs (binary {0,1} for a 2-role
  swap; 0 = the flip achieved). `displacement(...)` — a smooth signed-gap pre-flip signal in
  [0,1]. **Both are role-keyed** (the dicts are keyed by *original* ig via the reanchor map).
- `search/directed/order_metric.py::order_distance(ranks, target) -> int` — **sum of
  absolute position deltas** (the Phase-0 standalone form), plus `_MISSING_PENALTY`.

**Per-candidate reanchored scorer — EXISTS.**
`order_metric.py::score_candidate_reanchored(cand_pcdump, ref_descs, ...)` reanchors via
`reanchor_descs` and reads ranks/assignments at the **reanchored** ig numbers — i.e. the
identity-safe, cross-variant order/phys scorer the brief's §3 constraint demands. (It is
currently hardcoded with `NINEACC_*` constants but accepts `order_target`/`phys_target`
overrides.)

**Search loop wiring — EXISTS.**
`search/directed/run.py::run_directed(function, unit, melee_root, store_dir, proof_force_phys,
class_id, source_file, max_iters)` assembles `DirectedObjective` + `PcdumpLocalBackend` +
`DirectedScorePipeline` + `DirectedSource` (typed-mutator `VariantSource`) + `DefaultScheduler`
(directed mode) + the Phase-1 gate. The typed mutators (`search/directed/mutators.py`,
resolved by `search/directed/anchors.py`) are exactly the brief's move set:
`reorder_local_decls`, `split_decl_init`, `change_counter_width`, `widen/narrow_local_lifetime`,
`reuse_loop_counter_scope`, plus branch-shape ops (`flatten/unflatten/add/remove` scope).

**Mutate operators (standalone) — EXIST.**
`debug mutate decl-orders` (Tier-7b enumerate decl orderings), the statement hoist-sink
substrate (`search/statement_move.py`: `extract_movable_units`/`legal_destinations`/
`select_positions` with line-ownership + volatile-barrier safety), `debug mutate
simplify-order`/`select-order-search`/`coalesce-search`, `debug mutate lifetime-layout`.

**Order/phys scorers + target derivation — EXIST.**
- `debug target score-simplify-order` (lex prefix/suffix + precolor distance, permuter
  `.command`), `score-force-phys` (lex force-phys assignment hits), `score-dump` (Tier-4
  coloring-decision distance). Wiring: `debug permute setup-simplify-order-scorer`.
- `debug target force-phys-from-diff -f <fn> [--verify]` — derives `{ig: phys}` targets from
  a **register-only checkdiff** and emits both a target-spec JSON and a class-scoped force
  vector for `match-iter-first --force-vector` verification. **This is the per-function
  target-derivation primitive.**
- `debug target match-iter-first -f <fn> --force-vector <...>` — composes force overrides,
  verifies the union with integrated checkdiff, probes singleton/prefix steps. **This is the
  force-iter-first order-forcing verifier.**

**Remote fan-out — EXISTS.**
`search/adapters.py` wraps `permuter_remote.{submit,fetch,status,stop}_job` as an
`ArtifactProducer`; `search/scheduler.py` ingests its outputs. decomp-permuter is an
**ArtifactProducer (source harvest)**, never a `VariantSource` (per the substrate spec).

**Campaign CLI — EXISTS.**
`debug search directed -f <fn> -u <unit> [--seed <file>] [--directed-force-phys <vec>]
[--directed-from-diff [--verify]] [--max-iters N] [--store <dir>]`. Live path
(`run.py::_run_live`) accepts operator `proof_force_phys` or derives it from diff; the
`grIceMt` fixture is used **only** when `function == "grIceMt_801F9ACC"`.

### 2.2 The GAP (what is actually missing or mis-aimed)

The brief hypothesized four gaps (extractor / metric / loop / CLI). **All four exist.** The
real, much smaller gaps are:

**GAP-A — The objective is phys-match, not order-distance.** The shipped gate signal
(`scorer.py::score_directed`, `DirectedMeta.displacement`/`order_distance`) is
`phys_match_fraction`/`phys_mismatch_count` — *did the role land on its desired physical
register*. The brief wants **order-distance to the proven target select-order vector** as the
primary objective. The Kendall/`displacement` order metric still computes, but is **demoted
to diagnostic-only** (`DirectedMeta.iter_order_distance`/`iter_displacement`). The demotion
was **deliberate and evidence-backed** (PHASE1_RESULT.md): the order metric, as it was wired,
was *hollow* — its objective vector came from the **baseline's own coloring**, so
`displacement = 1.0` merely meant "the edit changed nothing," and a no-op scored a perfect
order-distance. Re-promoting order-distance is only legitimate if the objective vector is the
**force-iter-first-PROVEN target vector of a DIFFERENT (correct) coloring**, not the
baseline's. See GAP-B and §3/§4/§6.

**GAP-B — No proven target *order* vector per pool function.** `build_directed_objective`
derives `objective_iter_by_original_ig` from the **baseline** decisions (the hollow source).
There is no step that derives the **target** order vector (the select order that
`match-iter-first --force-vector` proves reproduces the bytes) and persists it per function.
The phys target *is* derivable (`force-phys-from-diff`), but the **order** target is not
materialized. This is the single genuine new datum the objective needs.

**GAP-C — The mndiagram pool is not wired.** No per-function target artifacts exist on disk
(`find ... *target*` empty; no `build/directed-store`). Each pool function needs: a
register-only checkdiff → `force-phys-from-diff` → `match-iter-first` round-trip → a persisted
`OrderTarget` artifact (§4.3). This is data production, not code.

**GAP-D — The typed-mutator vocabulary under-covers the mndiagram levers.** The anchor set
(`anchors.py`) covers decl-order/split/lifetime/branch-shape. The mndiagram campaigns proved
levers the anchors do NOT emit: **band-lift / dead-anchor placement**, **comma-expr LICM
perturbation** (the proven `802427B4` crack), **accessor-macro inline (GET_X)**, and
**operand-flip comparison form**. The directed loop's deterministic arm will under-propose on
this pool until these are added — OR the **permuter fallback arm** (already an
ArtifactProducer) covers the long tail. The minimal design uses the permuter arm for coverage
and adds **only the comma-expr and band-lift mutators** if validation shows the deterministic
arm starves (§5.3, §9).

**GAP-E — Order-distance is binary for the small-residual pool.** The parent design already
records this: for a 2-role swap, Kendall order-distance is `1 → 0` at the flip with no
intermediate gradient. `OnFrame`/`UpdateHeader` (one pair) and `AggRank` (two) are exactly
this. The smooth `displacement` sub-metric is the only continuous signal, and it is **not
guaranteed monotone toward the flip** (its own docstring says so). This is a property of the
problem, not a missing piece — but it bounds what "directed" can buy on the small end and
forces the validation to test descent honestly (§6c, §7).

**Verdict:** this is a **wiring + data + validation** effort, not a tool build. The new code is
a re-aimed objective (order-distance primary, with the proven-target guard), an order-target
derivation/persistence step, a pool registry, and (conditionally) two extra mutators. The
new *work* is mostly target derivation and the decisive experiment.

---

## 3. THE CRITICAL DESIGN CONSTRAINT — identity across variants

### 3.1 Why ig_idx is not comparable across variants

`ig_idx` numbering is **variant-specific**. Proven in the InputProc campaign: a clean-form
variant and a goto-form variant number their IG nodes differently; "ig88" in one is not
"ig88" in the other. The tiebreak spec re-confirmed it (the original `ig88 r27→r25` target
was from a *different* variant than the clean dump where the same role is a different ig and
`r27` is unreachable). **Any distance metric that compares two variants by raw ig index is
measuring noise.** This is the same finding that killed first-divergence v1 (~89% ig drift
over a real solve path) and motivated the role layer.

### 3.2 The anchor: match nodes by ROLE, then compare positions

The metric MUST match nodes by **role descriptor** (def-site signature + use-pattern
multiset + param flag + strong var-name), never by ig index, then compare the *positions of
role-matched nodes*. This is exactly what `score_candidate_reanchored` already does:

1. Build `ref_descs = build_descriptors(baseline_compile, class_id)` **once** (the identity
   reference; the baseline is the current committed source).
2. Per candidate: `cand_descs = build_descriptors(cand_compile, class_id)`.
3. `reanchor_descs(ref_descs, cand_descs, desired_phys, class_id) -> ReanchorResult`, giving
   `matched = {new_ig: orig_ig}` (forward+inverse round-trip confirmed).
4. The candidate's order vector is read at the **reanchored** ig numbers:
   `cand_iter_by_orig_ig = {orig: rank(new) for new, orig in matched.items()}`.
5. Distance is computed between `cand_iter_by_orig_ig` and the **target** vector, which is
   also keyed by *original* ig (the identity reference's numbering).

The target vector is fixed in the **identity reference's** ig space; every candidate is
projected into that space by reanchoring. The objective never drifts with the candidate's
renumbering.

### 3.3 Ambiguous roles (compiler temps) — the honest abstain

The mndiagram campaigns are explicit that several residuals are **statement-temp webs with no
variable identity** (`found↔row2` cycle, `nc anchor transposition` +094, `nr-head load-order`)
— "Dead-anchor tool cannot reach statement-temp webs. Permuter-random territory only."
Compiler temps have weak role descriptors (no `var_name`; `first_def_sig` of identical field
loads collides; `use_site_multiset` may tie among siblings). The matcher's response is
already correct and load-bearing:

- A temp that ties an identical sibling returns `AMBIGUOUS`/`SPLIT`/`NON_COMPARABLE` (not a
  confident-wrong match), and `reanchor` **excludes** it from the matched map.
- The scorer's `coverage_floor` (default 0.5 in `DirectedScorePipeline`) **invalidates** any
  candidate where fewer than half the target roles reanchor. A candidate whose target role is
  an unanchorable temp is `invalid` (reason `low_coverage`), never scored as progress.

**Design rule (new, explicit):** a target whose roles are *predominantly* anonymous temps
(coverage below floor on the baseline itself) is **classified `UNANCHORABLE` at derivation
time** (§4.3) and routed **directly to the permuter arm** — it never enters the
order-distance loop, because the loop cannot measure its progress. This is the directed
analogue of the campaign's "permuter-random territory only" verdict, made mechanical. The
per-function preflight (§4.3, reusing `objective.py::preflight_objective`) reports the
baseline reanchor coverage so this routing is a number, not a guess.

### 3.4 FPR roles

`build_descriptors` raises `NotImplementedError` for `class_id != 0` (GPR-only: the IR-fact
maps are GPR-keyed). `HandleInput` (17 FPR relabels) and `80241E78` (an FP shadow) therefore
have FPR roles that the role layer **cannot anchor today**. Per §8 (out of scope), this spec
targets the **GPR** sub-objective of those functions only; the FPR residual is left to the
permuter arm or a future class-aware descriptor build (carry-forward #2 in
`role_descriptor.py`). A function whose residual is *entirely* FPR is `UNANCHORABLE` for this
spec.

---

## 4. The objective: order-distance to a proven target vector

### 4.1 Primary metric (chosen): role-matched Kendall-tau distance

**Primary = `metric.py::order_distance`** — the count of pairwise order inversions between the
candidate's role-matched select order and the **proven target** select order, over the shared
reanchored roles. Rationale:

- It is **already implemented**, **already role-keyed**, and **already unit-tested**.
- `distance == 0` **iff** every role-pair is in the target relative order — and because the
  target order is the **force-iter-first-proven** order (§4.2), `distance == 0` is the order
  that reproduces the target bytes (modulo dispense-rule fidelity, which `inspect tiebreak`
  G1 validates at 100%). It is not a proxy that can be satisfied by a wrong coloring the way a
  baseline-derived vector could.
- Kendall-tau is invariant to absolute position jitter (a role moving from rank 40→42 because
  an unrelated temp appeared changes no *pairwise* relation), so it is robust to the position
  churn that absolute-delta metrics conflate with progress. This is precisely the failure mode
  `order_metric.py`'s sum-of-deltas form is prone to.

**Diagnostic metric (chosen): smooth signed-gap `displacement`** — `metric.py::displacement`,
the mean closeness of each role-pair's signed iter-gap to the target's, in [0,1]. It is the
**pre-flip gradient** for the binary cases (§GAP-E): when Kendall is stuck at 1 (no flip yet),
`displacement` distinguishes "the two roles are 30 positions apart in the wrong order" (far)
from "they are adjacent and about to cross" (near). It is reported every iteration and used as
the scheduler's *tiebreak scalar* among equal-Kendall candidates, but is **never** the
accept/win signal (its non-monotonicity makes it unsafe as the objective; the parent design
and PHASE1_RESULT both warn on this).

Why one primary + one diagnostic (not a single blended scalar): the parent design burned
cycles on α-weighted blends (the `simplify_search.combined_value` story); the lesson, captured
in `simplify_order_scoring.py`'s module docstring, is **no tunable α at the objective layer**.
Kendall is the discrete truth; `displacement` is the gradient hint; they are kept separate.

### 4.2 The target vector derivation (closes GAP-B)

Per pool function, ONCE, at campaign setup (this is the "each pool fn gets its target vector
derived once" step):

1. Establish a **register-only checkdiff** of the committed source vs the expected object
   (`tools/checkdiff.py <fn> --format json`). Precondition: the diff must be register-only
   (the function is a FULLNORM-0 ceiling); a structural diff means the function is not in this
   pool.
2. `debug target force-phys-from-diff -f <fn> --verify` → `{ig: phys}` **phys target** in the
   baseline's ig space + a class-scoped force vector. `--verify` runs the bounded union /
   singleton / prefix force-vector checks.
3. `debug target match-iter-first -f <fn> --force-vector <derived>` → confirm the forced
   **select order** reproduces the target bytes (checkdiff clean under the force). The order
   that the force vector encodes — read back from the **forced** pcdump's `COLORGRAPH
   DECISIONS` via `colorgraph_ranks` — is the **proven target order vector**
   `target_iter_by_orig_ig: {orig_ig: rank}`.
   - If `match-iter-first` cannot reproduce the bytes with any ≤K force vector, the target is
     **not order-reachable** by a local select-order move (or the phys target is wrong); the
     function is classified `ORDER-UNREACHABLE` and routed to the permuter arm. This is the
     `inspect tiebreak` exit-4 outcome, made part of derivation.
4. Persist an **`OrderTarget`** artifact (§4.3) carrying both the phys target and the proven
   order target, the baseline source hash + pcdump sha256 (provenance), and the baseline
   reanchor coverage (the `UNANCHORABLE` gate, §3.3).

This makes the objective vector a **property of the correct coloring**, not the baseline's —
the single fix that distinguishes this design from the hollow Phase-1 order metric.

### 4.3 `OrderTarget` artifact (new, small)

A per-function YAML/JSON, stored at
`docs/superpowers/order-targets/<function>.yaml` (committed; small; human-auditable),
schema:

```yaml
function: mnDiagram_OnFrame
unit: melee/mn/mndiagram
class_id: 0
# Derived from force-phys-from-diff (baseline ig space):
phys_target: {28: 29, 29: 28}          # {orig_ig: desired_phys}
# Proven by match-iter-first --force-vector (read back from forced DECISIONS):
order_target: {28: 5, 29: 7}           # {orig_ig: target rank} (the PROVEN vector)
force_vector: "0:28:r29,0:29:r28"      # the verified force vector (provenance)
# Identity provenance (the reference the metric anchors to):
baseline_source_sha256: "…"
baseline_pcdump_sha256: "…"
# Routing gate (computed by preflight on the baseline):
baseline_reanchor_coverage: 1.0        # fraction of target roles that anchor
routing: directed                      # directed | unanchorable | order_unreachable
```

The CLI builds this with one command (§5.2). `TargetSpec` (the role-anchored object the scorer
consumes) is derived from `OrderTarget` at run time via `build_target_spec` — `OrderTarget` is
the *persisted, reviewable* input; `TargetSpec` is the in-memory runtime object.

---

## 5. The search loop

### 5.1 Seed, moves, accept (reuse `run_directed`)

- **Seed** = the current committed TU source (`--seed <tu>.c`, default = the TU). The
  identity reference `ref_descs` is built from the seed's baseline compile, ONCE.
- **Moves (deterministic arm)** = the existing typed mutators (`anchors.py` → `mutators.py`),
  proposed by `DirectedSource` from the first-divergence diagnosis each iteration. Move set
  for this pool: `reorder_local_decls`, `split_decl_init`, `widen/narrow_local_lifetime`,
  `reuse_loop_counter_scope`, branch-scope shape ops, `change_counter_width` (the `int` vs
  `s32` loop-counter lever from CLAUDE.md). **Conditionally added** (§GAP-D, §9): a
  `comma_expr_licm` mutator (insert `(0, X)` to perturb LICM hoist — the proven `802427B4`
  crack) and a `dead_anchor_band_lift` mutator (insert a DCE'd `var = <live>;` on a
  path-disjoint dead branch to move a variable's first-use band — the InputProc band-lift law).
- **Moves (fallback / wide arm)** = decomp-permuter via the existing `ArtifactProducer`
  adapter, **scored by the same order-distance objective** (the permuter's `.command` is wired
  to the order scorer the way `setup-simplify-order-scorer` wires `score-simplify-order`; see
  §5.3). This arm covers the temp-web long tail the deterministic arm cannot anchor, and runs
  as remote fan-out (§5.4).
- **Accept** = a candidate becomes the new current-best iff:
  - **(primary) Kendall order-distance strictly decreases** vs the parent, OR ties the parent
    with strictly higher `displacement` (the tiebreak), AND
  - **match% non-regression gate**: `checkdiff <fn> --summary` match% ≥ parent's (the
    `DirectedScorePipeline` already carries `byte_score`/`checkdiff_gate`; this gate is the
    `requesting-code-review`/`verification-before-completion` analogue for candidates — never
    accept a structural regression for an order gain), AND
  - **protected-sweep gate**: the candidate's reanchor coverage ≥ floor and no *non-target*
    role that was anchored in the parent went `GONE`/`SPLIT` (a guard that the edit did not
    collateral-damage an unrelated web — the campaign's "body gate"). Implemented as a
    coverage-delta check in the scorer's validity gates.
- **Win** = Kendall order-distance `== 0` **and** `checkdiff` clean (byte match). Order-distance
  0 without a byte match means the order matched but a *different* (unmodeled) residual remains
  — reported as `ORDER_MATCHED_BYTES_DIFFER`, a lead, not a win (mirrors the parent's
  `TARGET_SATISFIED` ≠ convergence rule).

### 5.2 CLI surface (extend `debug search directed`; add one derivation command)

Two CLI shapes, both extensions of existing groups:

**(new) `debug target order-target -f <fn> -u <unit> [--verify] [--out <path>]`**
Derives and persists the `OrderTarget` artifact (§4.2/§4.3): runs the register-only checkdiff
→ `force-phys-from-diff` → `match-iter-first --force-vector` → reads back the proven order
vector → computes baseline reanchor coverage → writes `docs/superpowers/order-targets/<fn>.yaml`
with a `routing` verdict. Exit 0 = `directed`; exit 3 = `unanchorable` (coverage < floor);
exit 4 = `order_unreachable` (no ≤K force vector reproduces bytes). This is a thin orchestration
over four existing commands.

**(extend) `debug search directed`** gains:
- `--order-target <path>` — load an `OrderTarget` artifact; sets the **objective mode to
  order-distance** (the new primary). When present, the objective's
  `objective_iter_by_original_ig` is set from `OrderTarget.order_target` (the PROVEN vector),
  not the baseline (closes GAP-A/B). `proof_force_phys` is set from `OrderTarget.phys_target`.
- `--objective {order,phys}` — explicit selector (default `phys` for backward compatibility
  with the shipped 9ACC behavior; `--order-target` implies `order`). The two modes differ
  only in which `DirectedMeta` field the gate/accept reads (`order_distance` Kendall vs
  `displacement` phys-match); both are already computed every iteration, so this is a
  one-branch change in `scorer.py::score_directed` + `gate.py`.
- `--permuter-arm {off,local,remote:<host>}` — enable the fallback/wide arm (§5.3/§5.4).

### 5.3 Wiring the order-distance objective into the scorer + permuter

- **Scorer (`scorer.py::score_directed`)**: today it hardcodes the phys-match buckets as the
  gate signal and demotes the iter metric. Add an `objective_mode` on `DirectedObjective`
  (`"order" | "phys"`). When `"order"`: the gate signal `order_distance` :=
  `metric.order_distance(cand_iter_by_orig_ig, obj.objective_iter_by_original_ig)` (Kendall vs
  the PROVEN vector) and `displacement` := `metric.displacement(...)`; phys-match moves to a
  *diagnostic* field. When `"phys"`: unchanged. **No metric code changes** — only which
  already-computed value the gate reads. (~30 lines.)
- **Gate (`gate.py::evaluate_phase1_gate`)**: it currently treats higher `displacement` as
  better (`displacement > control_displacement`, `displacement_delta > 0`). For order mode the
  win is **lower** `order_distance`; add an objective-aware comparator (`better(a, b)`), or
  invert order-distance into a `1/(1+d)` "closeness" so the existing `>` logic holds
  unchanged. Prefer the explicit comparator (no magic transform). (~25 lines.)
- **Permuter arm scorer**: add `debug target score-order` (sibling of `score-simplify-order`)
  that, given a candidate `.o`+pcdump sidecar and an `OrderTarget`, reanchors and emits the
  integer Kendall order-distance (lex-free: it is already a small non-negative int, monotone).
  Wire it via a `debug permute setup-order-scorer` (sibling of `setup-simplify-order-scorer`)
  so the permuter saves order-improving candidates. This reuses the entire
  `setup-simplify-order-scorer` machinery (compile.sh pcdump sidecar, settings.toml scorer
  section); only the score function differs. (~1 small module + 1 CLI command, both modeled
  line-for-line on the simplify-order pair.)

### 5.4 Remote fan-out

The wide permuter arm runs through the existing `permuter_remote` adapter
(`submit/fetch/status/stop` on coder1/2/3) as an `ArtifactProducer`, with its `.command`
pointed at `score-order` (§5.3). Candidates flow back into the same `ArtifactStore`, are
reanchored + scored by the identical order-distance objective, and compete with the
deterministic arm's candidates in the scheduler's best-selection. This is the substrate's
designed division: deterministic typed mutators as the `VariantSource`, permuter as the
async producer. No new transport code.

---

## 6. VALIDATION PLAN (the decisive experiment, cheap-first)

The premise under test: **directed order-distance search descends to the proven target order,
and the metric would have found known historical wins.** The Phase-1 pilot's hollowness is the
reason this must be tested before any pool campaign. Three functions, cheap → expensive.

**Picks:** `mnDiagram_OnFrame` (one pair — binary, the cheapest live target),
`mnDiagram2 UpdateHeader` (one transposition — second binary check, different TU), and
`mnDiagram_8024227C` (the large ~175-line many-role ceiling — the only case with a real
*gradient* and the only one that can show smooth descent). The brief's pick set exactly.

### 6a. Target vector round-trips (cheapest; pure derivation, no search)

For each of the three: run `debug target order-target` (§5.2). **PASS iff** the derived
`force_vector` makes `match-iter-first` reproduce the bytes (checkdiff clean under force) AND
reading the forced DECISIONS back through `colorgraph_ranks` yields a self-consistent
`order_target` (the forced order, re-extracted, equals the order we forced). This proves the
target vector is real and the extractor reads it correctly. **If a pick's target does not
round-trip, it is `order_unreachable` — drop it from the live experiment** (and note that the
campaign's "reachable" claim for it was a phys-only proof, not an order proof).

### 6b. Extractor stability (cheap; two compiles, no search)

Compile the **unchanged** seed twice (or compile, copy, recompile) and run `colorgraph_ranks`
+ `build_descriptors` + `reanchor_descs(ref, ref)` on both. **PASS iff** (i) identical source →
identical order vector (determinism), and (ii) self-reanchor is the identity on all
non-ambiguous roles (`matched[ig] == ig` for every confidently-matched role; ambiguous temps
may abstain — that is allowed and reported). This pins that the metric's zero point is stable
and the identity layer is not introducing drift on a no-op. (This is the check that, had it
been run on the Phase-1 baseline-derived vector, would have *exposed* the hollowness:
self-reanchor of a no-op scores order-distance 0 against a baseline-derived target trivially —
so 6b must be run against the **proven** target from 6a, where a no-op scores the *baseline's*
non-zero distance, not 0.)

### 6c. The metric would have found a KNOWN historical win (decisive; the kill switch)

Reconstruct two banked wins on their pre-win base and confirm the order-distance metric
**descends** at the winning edit:

1. **`802427B4` comma-expr crack** (banked 95.68→97.96; confirm the exact base commit at
   reconstruction time): the proven win is inserting a `(0, X)` comma expression that perturbs
   LICM so MWCC stops hoisting a loop-invariant base.
   Procedure: derive `OrderTarget` for `802427B4` on its pre-win base; score the pre-win base
   (control) and the comma-expr variant; **PASS iff** the comma-expr variant's Kendall
   order-distance is **strictly lower** than the control (ideally 0), i.e. the metric ranks the
   known win above the base.
2. **A cardstate decl-chain peel** (the `hsd_3AA7.c` `fn_803ACD58` decl-reorder chain that
   each peeled one callee-save) as a second, *gradient* witness: score the base and each
   successive peel; **PASS iff** order-distance is monotone non-increasing across the chain
   (the metric sees the partial progress the campaign saw). This is cross-TU (not mndiagram)
   on purpose — if the metric only works on the pool it was tuned for, it is overfit.

**This is the kill switch.** If the comma-expr win does NOT descend the metric (e.g. because
its lever changes the coloring without changing the *role-matched pairwise order* we targeted,
or because the role layer cannot anchor the affected web), then **order-distance is the wrong
objective for this class and the spec's premise is refuted** — say so in the result doc and
STOP. The recommendation in that case: keep the shipped phys-match objective (which does not
depend on an order gradient) and route the pool to the permuter arm. Do not proceed to a pool
campaign on a metric that cannot retrodict a known win.

### 6d. Live descent (only if 6a-c pass)

Run `debug search directed --order-target ... --objective order` on `OnFrame` and
`8024227C` with a small `--max-iters` (e.g. 12) + permuter arm off (deterministic only, for
attribution). Report the outcome distribution (matched / order-matched-bytes-differ /
no-smooth-gradient / unattributed). A `no_smooth_gradient` on `OnFrame` (binary, no gradient)
is an *expected, honest* non-pass that routes to the permuter arm — it is not a failure of the
metric (§7). The headline question 6d answers is whether `8024227C` (the gradient case) shows
the deterministic arm *descending* before the permuter arm is even needed.

---

## 7. Risks / unknowns (honest)

- **Landscape may be discontinuous (the band rules).** The InputProc "band ordering" is the
  dominant lever and it is *quantized*: locals number in reverse-decl order, temps in
  first-use order, promoted temps at r111+ by first-use. A one-line edit can jump a role across
  a whole band, flipping many pairwise relations at once. So Kendall order-distance may move in
  large discrete steps, not a smooth slope — `displacement` is the only continuous hint and it
  is non-monotone. **Mitigation:** the binary cases (`OnFrame`/`UpdateHeader`) are accepted to
  be gradient-free (route to permuter on `no_smooth_gradient`); the gradient claim is tested
  only on `8024227C` (6c/6d). **Refutation evidence:** if even `8024227C` shows no monotone
  descent on any reconstructed multi-step solve, the smooth-search premise is dead for this
  class and only the discrete win/no-win and the permuter arm remain.
- **DECISIONS-dump cost per candidate.** Every candidate needs a full `mwcc_debug` compile +
  pcdump parse (the order vector is not available cheaper). On this machine local dump is the
  PASS path; budget ~a few seconds/candidate (the `decl-orders` help cites ~6s/variant; the
  directed loop is comparable). The deterministic arm is small (tens of candidates); the
  permuter arm is the expensive one and is **why it runs remote** (§5.4). **Mitigation:** the
  scheduler dedups on `(CompileSpec, source_hash)`; the `ArtifactStore` caches; remote fan-out
  amortizes. Budget the deterministic arm at `max-iters × batch` compiles and cap the permuter
  arm by wall-clock, not iterations.
- **Role-matching on anonymous temps (the core fragility).** The most valuable residuals
  (`found↔row2`, the +094 anchor) are statement-temp webs with no `var_name`. The role layer
  *correctly abstains* on these (`AMBIGUOUS`/`NON_COMPARABLE`), which means the directed loop
  *cannot measure progress* on them and routes them to the permuter arm (§3.3). This is honest,
  but it means **directed order-distance buys nothing on the hardest residuals** — its value is
  on the variable-anchored ones (`OnFrame` r28/r29 if those are named locals, the decl-order
  pool). The validation's coverage report (6b, and `order-target` routing) quantifies how much
  of the pool is even anchorable; if most of it routes `UNANCHORABLE`, the directed arm's reach
  is small and the permuter arm is doing the real work.
- **The "blind register-source-search was census'd low-yield" prior.** MEMORY records that
  register crackability was 0/8 via blind remote permuter and that data-symbol harvest was
  0/25 — the near-100 buckets are "ceiling-dominated." **Why DIRECTED differs:** the censused
  search was *blind* (random permuter against objdiff, no target order, no gradient). This
  design searches against a **force-iter-first-PROVEN target order** with a role-anchored
  distance that *descends* — the permuter's `.command` is the order scorer, not objdiff, so the
  cloud compute is spent climbing toward a proven-reachable order instead of a random walk.
  **What would refute the premise:** if 6c shows the metric cannot even retrodict the
  comma-expr win, then "directed" is not actually directing (the metric is not aligned with the
  real lever), and this collapses back to the censused blind search. 6c is the test that
  distinguishes "directed search of a proven target" from "blind search with extra steps."
- **`OrderTarget` derivation may itself fail (exit 3/4) on much of the pool.** If `force-phys-
  from-diff` + `match-iter-first` cannot reproduce a function's bytes with a ≤K force vector
  (order not the sole lever, or phys target ambiguous), that function never enters the loop.
  This is a *correct* outcome (it bounds the addressable pool) but it may shrink the pool
  sharply — the derivation pass (§6a across all 10) is itself an informative census, run it
  before committing to a campaign.
- **Two CLI copies.** `tools/melee-agent/src/cli/debug.py` and
  `tools/melee-agent/src/cli/debug/__init__.py` both exist (~1MB each). The package form
  (`debug/__init__.py`) is the live one (it was the file modified at session start). New CLI
  must land in the live module; verify which is imported before editing (a papercut worth an
  issue if both are still wired).

---

## 8. Out of scope

- **FPR-specific extensions beyond what #573 gives.** The role descriptor is GPR-only
  (`build_descriptors` refuses `class_id != 0`). FPR residuals (`HandleInput`'s 17 FPR
  relabels, `80241E78`'s FP shadow) are addressed only via their GPR sub-objective or the
  permuter arm. A class-aware descriptor build (carry-forward #2) is a separate effort.
- **Reverse-compiler global inversion.** This is stage-wise: search C-space against a proven
  target order. No attempt to invert PCode→C or IG-construction (creation-order → ig_idx is the
  reverse-compiler's later layer, per the tiebreak non-goals).
- **Any retail-binary instrumentation.** The objective reads the local `mwcc_debug` DLL's
  `COLORGRAPH DECISIONS`; no retrowin32/gdb retail tracing (that is `mwcc-retro`'s domain and is
  not needed — `inspect tiebreak` G1 already validated the local dispense at 100%).
- **New distance-metric research.** We use the two metrics that exist (Kendall primary,
  `displacement` diagnostic). No first-divergence-depth or per-band-displacement metric is
  built — they are named in the brief as candidates but Kendall is chosen (§4.1) and adding a
  third unblended metric would re-introduce the α-calibration trap the parent design rejected.
- **Generalizing the typed-mutator vocabulary beyond the conditional two (§GAP-D).** Only
  `comma_expr_licm` and `dead_anchor_band_lift` are in scope, and only if validation shows the
  deterministic arm starves. Broader mutator coverage (accessor-macro inline, operand-flip) is
  deferred to the permuter arm.

---

## 9. Reused vs new + implementation size estimate

**Reused (no change):** `colorgraph_parser`, `order_metric.colorgraph_ranks`, `metric.order_distance`/`displacement`, `role_descriptor`/`role_matcher`/`role_reanchor`, `convergence.analyze_iteration_full`, `DirectedSource`/`anchors`/`mutators`, `PcdumpLocalBackend`, `DefaultScheduler` (directed mode), `ArtifactStore`, the permuter `ArtifactProducer` adapter, `force-phys-from-diff`, `match-iter-first`, `setup-simplify-order-scorer` (as the template), `checkdiff`.

**New / changed (the whole build):**

| # | Task | Where | Size |
|---|---|---|---|
| 1 | `objective_mode` field + order-branch in `score_directed` (gate reads Kendall vs proven vector) | `scorer.py`, `contracts.py` | S (~30 LOC + tests) |
| 2 | objective-aware comparator in the gate | `gate.py` | S (~25 LOC + tests) |
| 3 | `OrderTarget` artifact schema + load/save + `build_target_spec` adapter | new `search/directed/order_target.py` | S-M |
| 4 | `debug target order-target` CLI (orchestrates checkdiff→force-phys-from-diff→match-iter-first→readback→persist+route) | live `cli/debug` module | M |
| 5 | `debug search directed` flags: `--order-target`, `--objective`, `--permuter-arm`; build objective from `OrderTarget` | `run.py`, live `cli/debug` module | M |
| 6 | `score-order` permuter scorer + `setup-order-scorer` (modeled on the simplify-order pair) | new `search/directed/order_scoring.py` + `cli/debug` | M |
| 7 | Validation experiment 6a-6d (derive 3 targets, round-trip, stability, **6c kill switch**, live descent) + result doc | new `…/ORDER_DISTANCE_RESULT.md` | M (mostly runtime, not code) |
| 8 | (conditional, only if 6d starves) `comma_expr_licm` + `dead_anchor_band_lift` mutators + anchors | `mutators.py`, `anchors.py` | M |

**Estimate: 6 code tasks (1-6) + 1 validation task (7) + 1 conditional (8) ≈ 2 plans.**
Plan A = tasks 1-6 (the wiring + derivation + scorers), gated on the existing 135-test suite
staying green plus new unit tests per task. Plan B = task 7 (the decisive experiment), which is
**a gate, not a build**: if 6c fails, Plan B's deliverable is the refutation doc and task 8
never happens. This is small because the substrate, the identity layer, the metrics, the loop,
and the CLI already exist — the genuinely new work is **re-pointing the objective at a proven
target vector and proving (or refuting) that the metric descends**.

**Codex review gate (per MEMORY doctrine):** this SPEC and the resulting PLAN each get an
independent `codex:codex-rescue` review before execution (the spec-and-plan review gate that
caught safety blockers on prior efforts), with particular attention to whether 6c is a genuine
kill switch or a test the metric can pass trivially.
