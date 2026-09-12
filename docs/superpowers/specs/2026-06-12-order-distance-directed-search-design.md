# Order-Distance Directed Search — Design Spec

**Date:** 2026-06-12
**Revision:** 2 (codex review round 1 — four blocking findings incorporated; ENDGAME ORACLE
ROUND 1 evidence folded; see §10 changelog)
**Status:** DRAFT for planning (audit-first inventory complete; pre-plan)
**Author:** spec phase (mndiagram TU-completion campaign)
**Builds on (frozen parents):**
- `docs/superpowers/specs/2026-06-01-directed-search-layer-design.md` (the directed layer — IMPLEMENTED as `tools/melee-agent/src/search/directed/`)
- `docs/superpowers/specs/2026-06-01-fast-directed-search-substrate-design.md` (the substrate — IMPLEMENTED as `tools/melee-agent/src/search/`)
- `docs/superpowers/specs/2026-05-28-role-descriptor-identity-layer-design.md` (the cross-variant identity layer — IMPLEMENTED as `tools/melee-agent/src/mwcc_debug/role_descriptor.py` / `role_matcher.py` / `role_reanchor.py`; NOTE the role layer lives in `mwcc_debug/`, not `search/directed/`)
- `docs/superpowers/specs/2026-06-10-tiebreak-counterfactual-design.md` (the select surrogate — IMPLEMENTED as `inspect tiebreak`)

**Companion runtime artifacts:**
- `tools/melee-agent/src/search/directed/PHASE1_RESULT.md` (the honest `NOT PASSED` Phase-1
  gate result that this spec must reckon with)
- `CAMPAIGN-STATE-D1COMPLETION.md` § "ENDGAME ORACLE ROUND 1" (commit `3eb0cd677`, 2026-06-12)
  — the oracle round that reclassified `8024227C` and supplies this spec's class-partition
  worked example plus two operational caveats (the 64-entry force cap; DLL/CLI feature skew).

---

## 0. TL;DR for the planner

Almost everything the title implies **already exists**. The order-vector extractor,
the role-anchored identity layer, two distance metrics, the typed-mutator search loop,
the per-candidate reanchored scorer, the remote-permuter producer, and the campaign CLI
(`debug search directed`) are all built and unit-tested (135 green). The Phase-0/1 pilot
ran end-to-end on one function (`grIceMt_801F9ACC`) and produced an honest **NOT PASSED**
verdict.

This spec is therefore **NOT a build of a new tool**. It is (a) a small set of wirings that
re-aim the existing directed layer at the **order-distance objective** (currently demoted to
diagnostic), including a first-class **polarity** change (gate + scheduler are hardcoded
higher-is-better), (b) the **per-pool-function target-vector derivation** — which is also the
**class partition**: a function whose forced-ORDER build does not byte-eliminate its class
residual is *classified out* (not order-class) at derivation time, exactly what the 2026-06-12
oracle round proved for `8024227C`, and (c) a **frozen-fixture kill-switch experiment** that
tests whether the metric retrodicts a known win before any pool campaign. If the kill switch
(§6c) fails, **the premise is refuted and we stop** — directed-by-phys-match (already shipped)
remains the recommended path and the pool routes to the permuter arm.

Expected implementation size: **12 tasks + 1 conditional, across 3 plans, ordered
cheapest-path-to-kill-switch** (Plan A objective core → Plan B kill switch [STOP gate] →
Plan C loop wiring + pool census). Detail in §9.

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

The diagnostic stack can **prove or refute order-reachability per function**:
- `match-iter-first` recommends `--force-iter-first` arguments (TRUE select-ORDER forcing)
  from the expected `.s`, and verifies application; a forced-ORDER build that byte-matches
  proves the order is the lever.
- `force-phys-from-diff` derives the target ASSIGNMENT (`{ig: phys}`) from a register-only
  checkdiff and verifies it with `--force-phys` probes; this proves the *assignment* is
  expressible on the current node set — and its **conflict entries** (one virtual wanting two
  target physregs) prove when it is NOT (the node set itself differs).
- **The proofs can fail** — and that is a classification, not an error. ENDGAME ORACLE ROUND 1
  (2026-06-12) showed `8024227C`'s residual is NOT order-class: forcing the target's 40 phys
  entries (union + all singletons + all prefixes) AND forcing the target simplify order BOTH
  fail to byte-match; the root is an **arg-home COALESCING divergence** (one virtual `ig56`
  in ours = three distinct lives in the target). See §4.4.

What is missing is **directed search of C-space** for the spelling that produces a *proven*
target order, with a metric that measures distance to that order and descends as edits get
closer. Today that search is a lottery (random permuter spellings) or hand-driven.

### 1.2 The pool (current match %, residual shape)

| Function | TU | Match % | Residual / class status |
|---|---|---:|---|
| `mnDiagram_OnFrame` | mndiagram.c | 99.72 | one `r28`↔`r29` pair |
| `mnDiagram_802427B4` | mndiagram.c | 98.84 | reg-only (comma-expr crack history → the §6c kill-switch function) |
| `mnDiagram_802417D0` | mndiagram.c | 98.03 | reg-only |
| `mnDiagram_CursorProc` | mndiagram.c | 99.52 | reg-only |
| `mnDiagram_80241E78` | mndiagram.c | 98.94 | `r25`↔`r26` + an FP shadow (FPR part v2, §8) |
| `mnDiagram_8023FC28` | mndiagram.c | 97.82 | reg-only |
| `mnDiagram_8024227C` | mndiagram.c | 94.32 | **ORACLE 2026-06-12: NOT order-class.** Arg-home coalescing root `ig56` (~45-node renumber cascade); force-phys 40-entry union/singletons/prefixes all `no_match`; forced order re-rolls wrong; tiebreak G1 126/126. Routed `not_order_class` — the §4.4 worked example. NOT in this spec's search pool. |
| `mnDiagram3_HandleInput` | mndiagram3.c | 98.42 | 127 GPR relabels (Family-A rotation cascade, oracle-confirmed relabel residual) + 17 FPR relabels (FPR v2, §8) — **the large validation case** (GPR sub-objective) |
| `mnDiagram2 UpdateHeader` | mndiagram2.c | 95.15 | one transposition |
| `mnDiagram2 AggRank` | mndiagram2.c | 94.11 | two transpositions |

(`AggRank` = `mnDiagram2_GetAggregatedFighterRank`; `UpdateHeader` is the header-update
function in mndiagram2.c — resolve exact symbol at derivation time, §4.2.) The pool spans
single-pair swaps (`OnFrame`, `UpdateHeader`), small multi-role (`AggRank`, `80241E78`), and
one large many-role case (`HandleInput`). Every pool member must pass **derivation** (§4.2)
before entering the search; derivation is expected to reclassify some of them out, as it
did `8024227C`.

---

## 2. Existing-pieces inventory (audit-first) + gap analysis

This is the load-bearing section: the design must be the **minimal wiring between existing
pieces**, not a rebuild. Every row below was verified against source (file:line) or `--help`
on 2026-06-12 in this worktree.

### 2.1 What EXISTS (verified)

**Order-vector extractor — EXISTS.**
`search/directed/order_metric.py::colorgraph_ranks(pcdump_text, function, class_id) -> {ig_idx: rank}`
reads the last `COLORGRAPH DECISIONS` section and returns 1-based color positions
(`rank = iter_idx + 1`). This *is* "build → DECISIONS dump → vector." The DECISIONS dump is
produced by `debug dump local <tu> --function <fn>` (local macOS wibo+DLL; `debug dump doctor`
PASSES in this worktree). Parser: `colorgraph_parser.ColorgraphDecision` =
`{iter_idx, ig_idx, assigned_reg, degree, n_interferers, flags, interferers}`.

**Role-anchored identity layer — EXISTS (in `tools/melee-agent/src/mwcc_debug/`) and is
wired into the directed scorer.**
- `mwcc_debug/role_descriptor.py::build_descriptors(Compile, class_id) -> {ig_idx: RoleDescriptor}`.
  Identity-core = `first_def_sig` (opcode + reg-normalized operands), `use_site_multiset`,
  `is_param`, `var_name`/`var_confidence`. Allocator-state (`assigned_reg`, `live_range`,
  `use_count`, `spilled`) is explicitly **excluded from identity**. **GPR-only**: it raises
  `NotImplementedError` for `class_id != 0` (role_descriptor.py:77) — FPR is v2 (§8).
- `mwcc_debug/role_matcher.py::match_roles(ref, cand)` — exact min-cost-max-flow assignment,
  statuses `MATCHED/AMBIGUOUS/GONE/SPLIT/MERGED/NON_COMPARABLE`.
- `mwcc_debug/role_reanchor.py::reanchor(...) -> ReanchorResult` — forward+inverse
  round-trip-confirmed `{new_ig: orig_ig}`; non-1:1 / unstable roles excluded, diagnosed.
- `role_descriptor.py::build_target_spec(...) -> TargetSpec` persists roles with
  `role_order_rank` and a `RoleDescriptor` each. **CAUTION:** its `target_coverage` field
  (role_descriptor.py:160) is the *rank-present* fraction over decisions — **rank-present ≠
  reanchored**; routing must never key on it (§3.3).

**Distance metrics — TWO EXIST.**
- `search/directed/metric.py::order_distance(cand_iter_by_ig, objective_iter_by_ig) -> int`
  (metric.py:115) — **Kendall pairwise inversions over the SHARED role-matched igs**. Binary
  {0,1} for a 2-role swap; 0 = the flip achieved. **Hollowing hazard, code-proven:** it
  silently drops unmapped roles — `tests/search/directed/test_metric.py:32`
  (`test_order_distance_ignores_unmapped`) pins `order_distance({37: 3}, {37: 3, 34: 103}) == 0`:
  a candidate that LOSES a target role scores a perfect 0. §3.3's validity rules exist
  because of this. `displacement(...)` — smooth signed-gap pre-flip signal in [0,1],
  documented non-monotone.
- `search/directed/order_metric.py::order_distance(ranks, target) -> int` — sum of absolute
  position deltas (the Phase-0 standalone form) + `_MISSING_PENALTY`.

**Per-candidate reanchored scorer — EXISTS, but 9ACC-shaped.**
`order_metric.py::score_candidate_reanchored(cand_pcdump, ref_descs, ...)` reanchors via
`reanchor_descs` and reads ranks/assignments at the reanchored ig numbers — the identity-safe
cross-variant scorer this design needs. Its result dataclass `CandidateScore`
(order_metric.py:204) is hardcoded to the pilot's two roles (`rank33`/`rank40` fields) and
must be **generalized to an arbitrary role set** (task T5).

**Search loop wiring — EXISTS.**
`search/directed/run.py::run_directed(...)` assembles `DirectedObjective` +
`PcdumpLocalBackend` + `DirectedScorePipeline` + `DirectedSource` (typed-mutator
`VariantSource`) + `DefaultScheduler` (directed mode) + the Phase-1 gate. Typed mutators
(`mutators.py`, dispatch table at mutators.py:279; resolved by `anchors.py`):
`reorder_local_decls`, `split_decl_init`, `change_counter_width`,
`widen/narrow_local_lifetime`, `reuse_loop_counter_scope`, branch-shape ops. **No comma-expr
or dead-anchor mutator exists** (conditional task T13).

**Polarity reality (verified — this is real work, not a toggle):**
- `contracts.py:9` `DirectedObjective` has **no `objective_mode` field**.
- `scorer.py::score_directed` hardcodes the phys-match buckets as the gate signal
  (scorer.py:197-207) and demotes the iter metric to `iter_*` diagnostics; the validity floor
  is `coverage_floor=0.5` (scorer.py:95, checked at scorer.py:190).
- `gate.py:92-101` requires `displacement_delta > 0` and
  `displacement > control_displacement` — **higher-is-better**.
- `scheduler.py:254-263` threads the selected best's `displacement` onto the next parent
  (via `object.__setattr__` on the frozen `DirectedSearchState`) with higher-is-better
  semantics baked into selection and delta computation.

**Order/phys scorers + target derivation — EXIST (with the critical phys-vs-order caveat).**
- `debug target score-simplify-order` / `score-force-phys` / `score-dump` permuter scorers;
  wiring template `debug permute setup-simplify-order-scorer`.
- `debug target force-phys-from-diff -f <fn> [--verify]` — derives `{ig: phys}` from a
  register-only checkdiff. **Its force vector is PHYS constraints**: entries are emitted as
  `class{N}:ig{M}:phys=...` (cli/debug/__init__.py:793, joined at :871) and are mapped to
  `--force-phys` (cli/debug/__init__.py:1396). **Forcing phys does NOT pin simplify order** —
  a phys-forced build's DECISIONS order is the baseline's own order. Its `conflicts` output
  (same virtual → ≥2 target physregs) is a first-class node-set-divergence signal (§4.2
  step 2, §4.4).
- `debug target match-iter-first -f <fn>` — recommends `--force-iter-first` (TRUE ORDER
  forcing) from the expected `.s`; `--force-vector` composes overrides and verifies the union
  with integrated checkdiff + singleton/prefix probes; verify-application (#550) confirms
  forced nodes actually moved.

**Remote fan-out — EXISTS.** `search/adapters.py` wraps
`permuter_remote.{submit,fetch,status,stop}_job` as an `ArtifactProducer`;
`search/scheduler.py` ingests its outputs.

**Campaign CLI — EXISTS (live copy identified).**
`debug search directed` is defined at `search/cli/__init__.py:2582`
(`@search_app.command("directed")`), surfaced through the package CLI
`cli/debug/__init__.py`. **Landing risk:** both have legacy ~1MB siblings
(`search/cli.py`, `cli/debug.py`) that still contain near-identical code; new code MUST land
in the package `__init__.py` copies, and the sibling duplication is filed as a tooling issue.

**Per-candidate compile path — EXISTS, and it is SERIALIZED.**
`search/directed/pcdump_backend.py` compiles each candidate by **writing the candidate
source INTO the real TU file** under `_acquire_repo_build_lock` (pcdump_backend.py:123-165:
save original → `tu_c.write_text(candidate)` → `debug dump local --keep-obj --no-cache-sync`
→ restore original). One repo-wide lock ⟹ one candidate compile at a time per checkout. This
defines the cost model (§7).

### 2.2 The GAP (what is actually missing or mis-aimed)

The round-1 brief hypothesized four gaps (extractor / metric / loop / CLI). **All four exist.**
The real gaps:

**GAP-A — The objective is phys-match, not order-distance, and the polarity is baked in.**
The shipped gate signal is `phys_match_fraction`/`phys_mismatch_count`; the Kendall/
`displacement` order metric is computed but demoted to diagnostics. The demotion was
**deliberate and evidence-backed** (PHASE1_RESULT.md): the order metric, as wired, was
*hollow* — its objective vector came from the **baseline's own coloring**, so a no-op scored
perfectly. Re-promoting order-distance is only legitimate with a **proven target vector from a
forced-ORDER build** (GAP-B). Re-aiming is not a one-flag change: `objective_mode` does not
exist (contracts.py:9), the scorer hardcodes phys (scorer.py:197), and **gate + scheduler
assume higher-is-better** (gate.py:92, scheduler.py:254) — the lower-is-better polarity is a
first-class task (T8/T9).

**GAP-B — No proven target *order* vector per pool function, and rev 1's derivation was
wrong.** `build_directed_objective` derives `objective_iter_by_original_ig` from the
**baseline** decisions (the hollow source). Rev 1 of this spec proposed reading the order from
the build forced by `force-phys-from-diff`'s vector — but that vector is **phys constraints**
(§2.1), and a phys-forced build keeps the baseline's select order: the readback would have
been the baseline's own order, **re-importing the exact hollowness this spec exists to fix**.
The corrected pipeline (§4.2) reads the order from a **TRUE forced-ORDER build**
(`--force-iter-first`), with verify-application and a derive-twice determinism check.

**GAP-C — The mndiagram pool is not wired, and derivation doubles as the class partition.**
No per-function target artifacts exist on disk. Deriving them is data production — and per the
oracle round, derivation *outcomes* are classifications (§4.4): `8024227C` failed both forcing
probes and routed out with a named cause.

**GAP-D — Metric-hollowing via coverage loss is code-proven and must be closed at the
objective.** Kendall ignores unmapped roles (metric.py:115; test_metric.py:32). The current
scorer floor (0.5 at scorer.py:190) would accept a candidate that lost half the target roles.
§3.3 hardens this: **1.0 reanchor coverage over the (pruned) target-role set + ≥2 anchored
roles, or the candidate is invalid**.

**GAP-E — Order-distance is binary for the small-residual pool.** For a 2-role swap, Kendall
is `1 → 0` at the flip with no gradient (`OnFrame`/`UpdateHeader`; `AggRank` has two
transpositions). `displacement` is the only continuous hint and is non-monotone. This bounds
what "directed" buys on the small end; the gradient claim is tested on `HandleInput` (§6).

**GAP-F — The mutator vocabulary under-covers the proven mndiagram levers.** No comma-expr
LICM mutator, no dead-anchor band-lift (mutators.py:279). The permuter fallback arm covers the
long tail; the two named mutators are **conditional** (T13) on the deterministic arm starving
in §6d. The kill switch does NOT depend on this gap — it scores two FIXED candidates (§6c).

**Verdict:** wiring + data + validation. New code = objective re-aim with polarity (scorer,
gate, scheduler, contracts), the order-target derivation/classification pipeline, the
`OrderTarget` artifact, a generalized candidate scorer, the permuter order-scorer pair, kill-
switch fixtures + harness, and (conditionally) two mutators.

---

## 3. THE CRITICAL DESIGN CONSTRAINT — identity across variants

### 3.1 Why ig_idx is not comparable across variants

`ig_idx` numbering is **variant-specific**. Proven in the InputProc campaign (clean vs
goto-form variants number differently) and re-confirmed by the tiebreak spec (a target derived
on one variant was unreachable on another). Any metric comparing variants by raw ig index
measures noise — the finding that killed first-divergence v1 (~89% ig drift) and motivated the
role layer.

### 3.2 The anchor: match nodes by ROLE, then compare positions

The metric matches nodes by **role descriptor** (def-site signature + use-pattern multiset +
param flag + strong var-name), never by ig index, then compares positions of role-matched
nodes — exactly what `score_candidate_reanchored` does:

1. Build `ref_descs = build_descriptors(baseline_compile, class_id)` ONCE (identity
   reference = the current committed source).
2. Per candidate: `cand_descs = build_descriptors(cand_compile, class_id)`.
3. `reanchor_descs(ref_descs, cand_descs, desired_phys, class_id)` →
   `matched = {new_ig: orig_ig}` (round-trip confirmed).
4. Candidate order vector at reanchored igs:
   `cand_iter_by_orig_ig = {orig: rank(new) for new, orig in matched.items()}`.
5. Distance vs the **proven target vector** (§4.2), which is keyed in the *baseline's*
   ig space. The objective never drifts with candidate renumbering.

One addition this revision makes explicit: the **forced-ORDER build used at derivation is the
same source as the baseline**, so its IG construction (and ig numbering) is identical —
forcing alters only simplify/select. Derivation asserts ig-set identity between baseline and
forced build (cheap; a mismatch means the forcing perturbed construction and the target is
suspect). Role descriptors are built on the baseline; identity-core features are
allocator-independent (they come from PCode def/use sites), so they are valid anchors for any
forced or candidate build.

### 3.3 Coverage rules — closing the proven hollowing hole (codex blocker 2)

Kendall silently ignores unmapped roles (test_metric.py:32): a candidate that makes a target
role `GONE`/`SPLIT`/`AMBIGUOUS` scores distance over the surviving pairs — potentially a
perfect 0 with the objective destroyed. The scorer's generic `coverage_floor=0.5`
(scorer.py:95/:190) is far too weak for an order objective. Rules, in order:

- **Derivation-time target-role pruning (makes the validity rule implementable):** the
  target-role set persisted in `OrderTarget` includes ONLY roles that **confidently
  self-reanchor on the baseline** (round-trip MATCHED, not AMBIGUOUS). Roles that fail —
  anonymous statement temps with colliding signatures — are recorded in
  `unscored_roles: [{ig, reason}]` as *unscored residual* (honest: the metric cannot see
  them). If fewer than 2 roles survive pruning → `routing: unanchorable`.
- **Candidate VALIDITY (the objective rule):** a candidate is scoreable iff **every** pruned
  target role round-trip-reanchors (coverage **== 1.0 over the target-role set**) AND the
  anchored target-role count is **≥ 2** (Kendall needs pairs). Otherwise the candidate is
  `invalid` (reason `target_role_lost`), never ranked, never accepted. This closes the
  test_metric.py:32 hole at the objective: losing a target role can never look like progress.
- **Diagnostic floor (~0.8, telemetry only):** reanchor coverage over the *broader* anchored
  universe (all baseline-confident roles, not just targets) below ~0.8 is logged as identity
  drift — a warning that the edit is reshaping the function wholesale — but does not by
  itself invalidate (the validity rule above is the gate).
- **Routing keys on REANCHOR coverage, never `TargetSpec.target_coverage`:**
  role_descriptor.py:160's `target_coverage` is the fraction of roles with a
  `role_order_rank` (rank-present over decisions). Rank-present ≠ reanchorable — a role can
  sit in the colorgraph yet be identity-ambiguous. `UNANCHORABLE` classification uses
  baseline round-trip reanchor coverage exclusively.

### 3.4 FPR roles — explicitly v2

`build_descriptors` refuses `class_id != 0` (role_descriptor.py:77: the IR-fact maps are
GPR-keyed; non-GPR lookups would be silently polluted). `HandleInput` (17 FPR relabels) and
`80241E78` (FP shadow) therefore get **GPR sub-objectives only**; their FPR residual is out of
scope for v1 (permuter arm or a future class-aware descriptor build — carry-forward #2 in
`role_descriptor.py`). Consequence for validation: a mixed-class function at GPR
order-distance 0 is **not expected to byte-match** — its success criterion is class-scoped
(§4.2 step 4, §6d).

---

## 4. The objective: order-distance to a proven target vector

### 4.1 Primary metric (chosen): role-matched Kendall-tau distance

**Primary = `metric.py::order_distance`** — pairwise order inversions between the candidate's
role-matched select order and the proven target order, over the pruned target-role set
(validity per §3.3). Rationale:

- Already implemented, role-keyed, unit-tested.
- `distance == 0` under the 1.0-coverage validity rule means every target role survived AND
  every pair is in the target relative order — and because the target order is the
  **forced-ORDER-proven** order (§4.2), distance 0 is the order that reproduces the target's
  class residual elimination. Not a proxy satisfiable by a wrong coloring.
- Kendall is invariant to absolute-position jitter (an unrelated temp shifting ranks changes
  no pairwise relation), unlike `order_metric.py`'s sum-of-deltas form.

**Diagnostic metric (chosen): smooth signed-gap `displacement`** (`metric.py::displacement`) —
the pre-flip gradient for binary cases; scheduler tiebreak among equal-Kendall candidates;
**never** the accept/win signal (non-monotone by its own docstring; the parent design and
PHASE1_RESULT both warn on this).

No blended α-scalar (the parent design's documented calibration trap; see
`simplify_order_scoring.py`'s module docstring).

### 4.2 Target derivation = the class partition (closes GAP-B; codex blocker 1)

Per pool function, ONCE, at campaign setup. **Every failure mode is a named classification,
not an error** (the oracle round's design lesson). Pipeline:

1. **Precondition — register-only checkdiff.** `tools/checkdiff.py <fn> --format json` must
   show a register-only diff (FULLNORM-0). A structural diff ⟹ not in this pool.
2. **Phys target + conflict classifier.** `debug target force-phys-from-diff -f <fn> --verify`
   → `{orig_ig: phys}` + the `conflicts` list. Its force vector is **phys-constraint
   evidence only** (assignment reachability), NEVER the order source (§2.1).
   - **Early classifier:** any conflict entry — the SAME virtual mapped to ≥2 target
     physregs at different sites — is the *target-splits-lives-ours-coalesces* signature
     (`8024227C`'s `ig56` → {r29, r28, r27}). Route `not_order_class` immediately, evidence
     attached, **before any forced compile is spent**.
3. **TRUE forced-ORDER compile.** `debug target match-iter-first -f <fn>` recommends the
   `--force-iter-first` ig list from the expected `.s`; run
   `debug dump local <tu> --force-iter-first <list> --diff` (diagnostic-only; no cache sync).
   - **The 64-entry force cap (oracle TOOLING NOTE):** the DLL's override parser caps at 64
     entries and **silently applies NOTHING** beyond it. Derivation therefore seeks a
     **minimal forcing set** (match-iter-first's per-register first-instruction anchors +
     prefix probing, both existing) that eliminates the class residual. If no ≤64-entry set
     does ⟹ `routing: force_cap_blocked` (named; the candidate fix is a DLL cap raise — a
     tooling task, out of this spec). Relevant to `HandleInput`'s 127 relabels: its cascade is
     expected to have few roots (cf. `8024227C`: ~45 nodes, ONE root), but this is verified,
     not assumed.
   - **VERIFY APPLICATION (#550-style, mandatory):** in the forced build's DECISIONS
     readback, assert each forced ig sits at its forced position. A force that silently
     failed to apply must never produce a target (the oracle round caught exactly this
     failure shape with a stale DLL — §7).
4. **CLASS-PARTITION GATE.** The forced-ORDER build must **byte-eliminate the targeted
   class's residual**: for a pure-GPR function, integrated checkdiff clean; for a mixed-class
   function (`HandleInput`), all GPR relabels gone with the remaining diff exclusively
   other-class (reported separately). If not ⟹ `routing: not_order_class` with evidence
   (the order is a symptom, not the cause — coalescing/VN/liveness divergence upstream;
   §4.4). **A derivation failure is a classification.**
5. **Readback.** From the FORCED build's `COLORGRAPH DECISIONS` via `colorgraph_ranks` →
   `order_target: {orig_ig: rank}`. Assert forced-build ig-set ≡ baseline ig-set (§3.2).
6. **Target-role pruning** per §3.3 → the persisted target-role set + `unscored_roles`.
   Fewer than 2 surviving roles ⟹ `routing: unanchorable`.
7. **DETERMINISM (derive twice).** Repeat steps 3+5 (a second forced compile + readback) and
   assert: identical order vectors, identical ig sets, identical DECISIONS-section hashes.
   mwcc given identical input is expected deterministic; a mismatch ⟹
   `routing: unstable_target` — do not enter the loop, file a tooling issue (nondeterministic
   forced builds would be a DLL/hook fault to investigate, never papered over by averaging).
8. **Persist** the `OrderTarget` artifact (§4.3) with routing + evidence.

### 4.3 `OrderTarget` artifact (new, small)

Per-function YAML at `docs/superpowers/order-targets/<function>.yaml` (committed,
human-auditable):

```yaml
function: mnDiagram_OnFrame
unit: melee/mn/mndiagram
class_id: 0
# Step 2 — assignment evidence (NOT the order source):
phys_target: {28: 29, 29: 28}            # {orig_ig: desired_phys}
phys_conflicts: []                        # non-empty => not_order_class (step 2)
# Step 3 — the TRUE order forcing (provenance):
force_iter_first: [46, 28, 29]            # the minimal verified forcing list (<= 64)
# Step 5 — the PROVEN vector, read from the FORCED build's DECISIONS:
order_target: {28: 5, 29: 7}              # {orig_ig: rank in the forced build}
# Step 6 — identity:
target_roles: [28, 29]                    # pruned, baseline-self-reanchor-confident
unscored_roles: []                        # [{ig, reason}] — honest unscored residual
# Step 7 — determinism evidence:
forced_decisions_sha256: ["…", "…"]      # two independent forced readbacks, must match
baseline_source_sha256: "…"
baseline_pcdump_sha256: "…"
# Routing (the class partition):
routing: directed   # directed | not_order_class | unanchorable | force_cap_blocked | unstable_target
class_evidence: ""  # e.g. "phys conflict ig56 -> {r29,r28,r27}: arg-home coalescing"
```

`TargetSpec` (the role-anchored runtime object) is derived from `OrderTarget` +
`build_target_spec` at run time; `OrderTarget` is the persisted, reviewable input.

### 4.4 Derivation IS the class partition — the `8024227C` worked example

ENDGAME ORACLE ROUND 1 (commit `3eb0cd677`) executed this pipeline's probes manually on
`8024227C` and is the canonical demonstration that **forcing-probe failures are
classifications**:

- Step 2 fired: `force-phys-from-diff --verify` derived 40 entries; union + all 40
  singletons + all 39 prefixes = `no_match`, AND the conflict signal appeared — `ig56`
  (the three `addi rN,argN,0` arg-home copies, ONE coalesced virtual in ours) wanted
  r29/r28/r27 at different sites: the target keeps three distinct lives.
- Step 3/4 fired: forcing the non-conflicting order subset verified as APPLIED (the
  prologue nodes moved) but re-rolled into a new-but-still-wrong config — the order is a
  **symptom**; the node SET differs.
- Corroboration: tiebreak G1 126/126 (coloring internally consistent ⟹ divergence upstream);
  force-remat #579 inert (the li-vs-copy trio is a liveness/VN sibling of the same root).
- Outcome: `routing: not_order_class`,
  `class_evidence: "arg-home coalescing root ig56; ~45-node renumber cascade"`. The function
  leaves this spec's pool and routes to the **named other-class queue** (coalescing-boundary
  permuter / structural arg-home-liveness reopen — per the oracle's recommendation), NOT to
  blind retries of register-endgame rungs.

This conversion — derivation failure → named class + named next tool — is a design feature of
the pipeline, not a salvage of an error path.

---

## 5. The search loop

### 5.1 Seed, moves, accept (reuse `run_directed`)

- **Seed** = the current committed TU source (`--seed`, default the TU). Identity reference
  built from the seed's baseline compile, ONCE.
- **Moves (deterministic arm)** = the existing typed mutators (§2.1). Conditional additions
  (T13, only if §6d shows starvation): `comma_expr_licm` (the proven `802427B4` lever) and
  `dead_anchor_band_lift` (the InputProc band-lift law).
- **Moves (fallback / wide arm)** = decomp-permuter via the existing `ArtifactProducer`
  adapter, scored by the same order-distance objective (`score-order`, §5.3), run as remote
  fan-out (§5.4). Covers the temp-web long tail the deterministic arm cannot anchor.
- **Accept** (candidate becomes current-best) iff ALL of:
  - **validity** per §3.3 (1.0 target-role reanchor coverage, ≥2 roles) — else never ranked;
  - **(primary)** Kendall order-distance strictly decreases vs the parent, OR ties with
    strictly higher `displacement` (tiebreak only);
  - **match% non-regression**: `checkdiff <fn> --summary` ≥ parent (never trade structure for
    order);
  - **protected-sweep gate**: no non-target baseline-confident role went `GONE`/`SPLIT`
    (the ~0.8 diagnostic floor of §3.3 escalates to a hard reject when the loss is a
    previously-anchored role — collateral-damage guard, the campaign's "body gate").
- **Win** = order-distance 0 AND checkdiff clean **for the targeted class** (mixed-class
  functions: GPR relabels eliminated; FPR residual remains and is reported).
  Order-distance 0 without class-residual elimination ⟹ `ORDER_MATCHED_BYTES_DIFFER` —
  a lead and a flag that the OrderTarget under-modeled the residual; re-derive.

### 5.2 CLI surface

**(new) `debug target order-target -f <fn> -u <unit> [--verify] [--out <path>]`**
Runs §4.2 end-to-end and persists the artifact. Exit codes mirror routing: 0 `directed`;
3 `unanchorable`; 4 `not_order_class`; 5 `force_cap_blocked`; 6 `unstable_target`.
Lands in the **package** CLI (`cli/debug/__init__.py` — the live copy; §2.1 landing risk).

**(extend) `debug search directed`** (live def at `search/cli/__init__.py:2582`) gains:
- `--order-target <path>` — load an `OrderTarget`; refuses to run unless
  `routing: directed`; sets objective mode `order` (the proven vector becomes
  `objective_iter_by_original_ig`; `phys_target` populates `proof_force_phys` for
  diagnostics).
- `--objective {order,phys}` — explicit; default `phys` (backward compatible);
  `--order-target` implies `order`.
- `--permuter-arm {off,local,remote:<host>}`.

### 5.3 Wiring the objective (with the polarity work made first-class)

- **Contracts** (`contracts.py`): add `objective_mode: str` (+ the OrderTarget-sourced
  fields) to `DirectedObjective` (it has none today — contracts.py:9).
- **Scorer** (`scorer.py::score_directed`): branch on `objective_mode`. `"order"`: gate
  signal = Kendall vs the proven vector + the §3.3 validity rules (replacing the generic
  0.5 floor for target roles); phys-match becomes diagnostic. `"phys"`: unchanged. The
  scoring core is the **generalized** reanchored scorer (T5) so the kill-switch harness and
  the live loop exercise the same path.
- **Gate** (`gate.py`): objective-aware comparator — the winner test at gate.py:92
  (`displacement_delta > 0`, `displacement > control`) becomes `better(candidate, control)`
  with lower-is-better semantics in order mode. Explicit comparator, no sign-flip transforms.
- **Scheduler** (`scheduler.py:254-263`): best-selection and the parent-state threading
  assume higher-is-better and thread `displacement` specifically (via `object.__setattr__`
  on the frozen state). Order mode must thread the order-distance scalar with inverted
  comparison — and this is the right moment to replace the frozen-dataclass mutation with a
  proper field. **This is a first-class task (T9), not a footnote** — codex verified the
  higher-is-better assumption is structural in both files.
- **Permuter arm scorer**: `debug target score-order` (sibling of `score-simplify-order`):
  candidate `.o` + pcdump sidecar + `OrderTarget` → reanchor → integer Kendall distance
  (with §3.3 validity → sentinel penalty on coverage loss, mirroring `PENALTY_INF`
  conventions). Wire via `debug permute setup-order-scorer` (modeled on
  `setup-simplify-order-scorer`'s three-file pattern).

### 5.4 Remote fan-out

The wide permuter arm runs through the existing `permuter_remote` adapter as an
`ArtifactProducer` with its `.command` pointed at `score-order`. Candidates flow into the
same `ArtifactStore`, reanchored + scored identically, competing in the same selection. No
new transport code. (This is also the only parallelism — see the cost model, §7.)

---

## 6. VALIDATION PLAN (the decisive experiment, cheap-first)

Premise under test: **directed order-distance search descends toward a forced-ORDER-proven
target, and the metric retrodicts known wins.** The Phase-1 hollowness is why this must pass
before any pool campaign.

**Picks (revised per oracle):** `mnDiagram_OnFrame` (one pair — binary, cheapest live
target), `mnDiagram2 UpdateHeader` (one transposition, different TU), and
**`mnDiagram3_HandleInput`** (the large case: 127 GPR relabels = a rich pairwise gradient;
GPR sub-objective per §3.4). **`8024227C` is REMOVED** — the oracle proved it not-order-class
(§4.4); it now serves as the derivation pipeline's negative worked example instead.
`802427B4` is the kill-switch function (6c).

### 6a. Target derivation round-trips + determinism (cheapest; no search)

For each of the three: run `debug target order-target`. PASS iff routing = `directed` with:
the forced-ORDER build byte-eliminates the class residual (step 4), verify-application
confirms every forced node moved (step 3), and the derive-twice readbacks are identical
(step 7). `HandleInput` additionally answers the 64-cap question (is there a ≤64 minimal
forcing set?) — `force_cap_blocked` is a possible honest outcome that removes it from 6d and
becomes a DLL-cap tooling request. Any pick that routes `not_order_class` here follows
`8024227C` out of the pool — that is the partition working, not the experiment failing.

### 6b. Extractor + identity stability (cheap; two compiles, no search)

Compile the unchanged seed twice; run `colorgraph_ranks` + `build_descriptors` +
self-reanchor on both. PASS iff identical order vectors (determinism at the extractor level)
and self-reanchor is the identity on every pruned target role (round-trip MATCHED; ambiguous
temps may abstain — they were pruned at derivation). Note the no-op scores the **baseline's
distance to the proven target** (non-zero by construction) — under the rev-1 baseline-derived
vector it would have scored 0; this check is the anti-hollowness tripwire made permanent.

### 6c. THE KILL SWITCH — frozen-fixture retrodiction of a known win (decisive)

**Design (adopting the codex prescription):** the kill switch scores **two FIXED candidate
sources** through the same scoring core the loop uses. It does not depend on the mutator
vocabulary at all (no comma-expr mutator exists — mutators.py:279 — and none is needed here).

**Fixtures (frozen under `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/`):**
- `pre_win.c` — the TU source at commit `a527c0227~1` (the pre-crack base, 95.68%).
- `win.c` — the TU source at commit `a527c0227` (the comma-expr crack:
  `pos.y = (0, mnDiagram_804DBFAC) - HSD_JObjGetTranslationY(j);` + the split base-pointer
  assignment; 97.96%; stmw r20/12-saves → r21/11-saves). **Verified present in the object
  store** (`git cat-file -t a527c0227` = commit) — fixture creation is extraction +
  re-verification + freezing, not archaeology.
- `negative_control.c` — `pre_win.c` plus ONE edit verified at freeze time to NOT improve
  match% (an adjacent decl-pair swap in the same function, re-scored at freeze; the campaign
  history records ~12 failed reshapes on this function — any reconstructible one is
  acceptable). Frozen alongside.
- `pre_win.pcdump.txt`, `win.pcdump.txt`, `negative_control.pcdump.txt`, and
  `order_target.yaml` — the OrderTarget derived **on the pre-win base** via §4.2, subject to
  T6's eligibility verification (see the derivation contingency below).

**Derivation contingency (flagged, evidence-based):** the win commit's own message records a
callee-save-count change (stmw r20/12-saves → r21/11-saves; our hoisted base eliminated in
favor of the target's in-loop recompute). That raises a real possibility that the pre-win
base is NOT FULLNORM-0 (the hoist is an instruction-placement difference, not a pure
relabel), in which case §4.2 step 1 or step 4 will refuse it and no `routing: directed`
OrderTarget exists on that base. T6 therefore verifies eligibility FIRST. If the pre-win
base routes out, that is recorded as a finding (the celebrated `802427B4` win was a
node-set-class win, partially outside this metric's class), the **cardstate decl-chain
witness is promoted to the gating retrodiction** (decl reorders are pure order moves on a
stable node set — squarely in-class), and the orchestrator is informed that the kill-switch
function assignment needs revisiting. The kill switch still runs; it does not silently pass.

**Assertions (all must hold):**
- **(a) Same anchor set:** both `pre_win` and `win` candidates round-trip-anchor the EXACT
  SAME target-role set (set equality over the pruned target roles). Note the win changes the
  callee-save count (a hoisted-base live range disappears) — the target-role set must
  therefore be chosen at derivation from roles that persist across the win (the mismatched
  destination-register roles, not the eliminated temp). If the winning edit's mechanism
  removes the very roles that were mismatched, (a) fails — and that is the kill switch
  firing with a precise cause: *this win class is invisible to role-stable order distance.*
- **(b) Strict descent:** `order_distance(win) < order_distance(pre_win)`, both valid per
  §3.3.
- **(c) A named pair flips:** at least one specific target-role pair, recorded by name in the
  fixture's `order_target.yaml`, is inverted in `pre_win` and correct in `win`. The pair must
  be chosen among **persistent** roles (the relabeled callee-save-band roles that exist in
  both candidates — NOT the hoisted-base node the win eliminates, which assertion (a) already
  excludes from the target set). This pins that the descent is the *intended* relation, not
  an accident of unrelated pairs.
- **(d) Negative control does not descend:**
  `order_distance(negative_control) >= order_distance(pre_win)`. If a verified-non-improving
  edit lowers the metric, the metric admits false positives at exactly the granularity the
  search will exploit — the kill switch fires.

**Secondary witness (cheap, cross-TU, non-gating but reported):** the cardstate
`fn_803ACD58` decl-chain peels (each peeled one callee-save) scored as a monotone sequence —
order-distance should be non-increasing along the chain. Cross-TU on purpose: a metric that
only works on the pool it was designed against is overfit.

**If 6c fails (any assertion): the premise is refuted — STOP.** Write the refutation into
the result doc, keep the shipped phys-match objective, route the pool to the permuter arm.
Do not proceed to a pool campaign on a metric that cannot retrodict a known win.

### 6d. Live descent (only if 6a-6c pass)

`debug search directed --order-target … --objective order` on `OnFrame` and `HandleInput`,
deterministic arm only (attribution), small budget (`--max-iters 12`). Expected honest
outcomes: `OnFrame` (binary, no gradient) may legitimately return `no_smooth_gradient` →
routes to the permuter arm — not a metric failure. The headline question is whether
`HandleInput` (the gradient case, 127 relabels → thousands of pairs) shows the deterministic
arm **descending** — and its success criterion is class-scoped (GPR relabel reduction;
byte-match is not expected while the FPR residual stands, §3.4).

---

## 7. Risks / unknowns (honest)

- **Landscape may be discontinuous (the band rules).** The InputProc band model says locals
  number in reverse-decl order, temps in first-use order, promoted temps at r111+ — a
  one-line edit can jump a role across a band, flipping many pairwise relations at once.
  Kendall may move in large steps; `displacement` is the only continuous hint and is
  non-monotone. Mitigation: binary cases route to the permuter on `no_smooth_gradient`; the
  gradient claim is tested only on `HandleInput`. Refutation evidence: if even `HandleInput`
  shows no descent under 6d, the smooth-search premise is dead for this class and only the
  discrete win/no-win + permuter arm remain.
- **Per-candidate cost is a SERIALIZED full-TU compile.** `PcdumpLocalBackend` writes the
  candidate INTO the real TU and compiles under `_acquire_repo_build_lock`
  (pcdump_backend.py:123-165) — one candidate at a time per checkout, each a full
  `dump local` of an ~88KB TU (mndiagram.c) plus pcdump parse. Budget: the deterministic arm
  is tens of serialized compiles per run (minutes, acceptable); **wide search is only viable
  on the remote permuter arm** (or N separate worktrees, each with its own lock — not
  designed here). The scheduler's `(CompileSpec, source_hash)` dedup and the ArtifactStore
  cache are already in place.
- **The 64-entry force cap silently no-ops (oracle TOOLING NOTE).** Any force-* list > 64
  applies NOTHING (`override list exceeded parser capacity (cap=64)`). Derivation must keep
  forcing sets ≤ 64 and ALWAYS verify reached-nodes in the forced dump — never trust a
  silent flag. `force_cap_blocked` is the named routing when no ≤64 set suffices.
- **DLL/CLI feature skew can fake "inert" (oracle TOOLING NOTE).** The editable CLI resolves
  to the MAIN checkout while a worktree's deployed DLL may predate a hook — the flag is
  forwarded and silently ignored, and `dump doctor` PASSES (it checks DLL↔worktree-source
  consistency, not feature presence). The oracle round lost a probe to exactly this (#579).
  Derivation's verify-application step (§4.2.3) is the structural defense; a doctor-level
  feature-presence check is a worthwhile tooling follow-up.
- **Role-matching on anonymous temps (the core fragility).** The hardest residuals
  (`found↔row2`, the +094 anchor) are statement-temp webs with no variable identity; the
  role layer correctly abstains, derivation prunes them to `unscored_roles`, and the loop
  cannot measure them. Directed order-distance buys nothing there — the permuter arm does
  that work. The derivation census (6a across the pool) quantifies the anchorable fraction;
  if most of the pool prunes away or routes out, the directed arm's reach is small and the
  honest conclusion is "the partition was the deliverable."
- **The "blind register-source-search was census'd low-yield" prior.** The near-100 census
  (0/8 via blind remote permuter) is the strongest argument against this whole direction.
  Why DIRECTED differs: the censused search was blind (objdiff scoring, no target order, no
  gradient); this design scores against a **forced-ORDER-proven** target with a role-anchored
  distance. What would refute the premise: 6c failing — then "directed" is not directing and
  this collapses to the censused blind search. That is exactly what the kill switch tests
  before pool spend.
- **Derivation may classify most of the pool out.** `8024227C` already routed
  `not_order_class`; others may follow (or hit `force_cap_blocked`/`unanchorable`). That
  shrinks the campaign but is correct — the partition converts "stuck at N%" into a named
  class + named next tool per function, which has standalone value.
- **Two CLI copies (landing risk).** `search/cli.py` + `cli/debug.py` are ~1MB legacy
  siblings of the live package `__init__.py` copies. New code lands in the package copies
  only; the duplication is filed in the issue queue so it gets deleted or de-duplicated
  before it eats a landing.

---

## 8. Out of scope

- **FPR (v2).** `build_descriptors` is GPR-only by guard (role_descriptor.py:77). FPR
  residuals (`HandleInput`'s 17, `80241E78`'s shadow) are not targeted; mixed-class success
  criteria are class-scoped (§3.4). A class-aware descriptor build is the named v2 item.
- **Reverse-compiler global inversion.** Stage-wise search against a proven target order
  only; no PCode→C or IG-construction inversion.
- **Retail-binary instrumentation.** The objective reads the local debug-DLL DECISIONS;
  `inspect tiebreak` G1 already validates the dispense at 100% (126/126 on `8024227C`).
- **New distance-metric research.** Kendall primary + `displacement` diagnostic, both
  existing. No first-divergence-depth or per-band-displacement metric; no blended scalar.
- **Raising the 64-entry DLL force cap.** Named as the fix for `force_cap_blocked` routing
  but is a DLL/tooling task outside this spec.
- **Splitting coalesced lives / the `8024227C` arg-home reopen.** That is the
  `not_order_class` queue's territory (coalescing-boundary permuter / structural reopen per
  the oracle's recommendation) — explicitly NOT this tool.
- **Generalizing the mutator vocabulary beyond T13's two**, and any automated source-edit
  generation beyond the existing typed mutators.

---

## 9. Reused vs new + implementation size estimate (revised honestly)

**Reused (no change):** `colorgraph_parser`, `colorgraph_ranks`, `metric.order_distance`/
`displacement`, the `mwcc_debug` role layer (`role_descriptor`/`role_matcher`/
`role_reanchor`), `convergence.analyze_iteration_full`, `DirectedSource`/`anchors`/
`mutators`, `PcdumpLocalBackend`, `ArtifactStore`, the permuter `ArtifactProducer` adapter,
`force-phys-from-diff`, `match-iter-first`, `setup-simplify-order-scorer` (template),
`checkdiff`, `inspect tiebreak`.

**The build — 12 tasks + 1 conditional, 3 plans, cheapest-path-to-kill-switch:**

**Plan A — objective core (the minimum the kill switch needs):**
| # | Task | Where | Size |
|---|---|---|---|
| T1 | `objective_mode` + OrderTarget-sourced fields on `DirectedObjective` | `contracts.py` | S |
| T2 | `OrderTarget` artifact module (schema, load/save, routing enum, validation) | new `search/directed/order_target.py` | M |
| T3 | Derivation pipeline `debug target order-target` (§4.2: conflict classifier, forced-ORDER compile w/ ≤64 minimal-set search, verify-application, class gate, readback, pruning, derive-twice, persist+route) | live `cli/debug/__init__.py` + a `mwcc_debug` helper module | **L** (the largest task — orchestrates 4 tools + classification) |
| T4 | Scorer order-mode branch + §3.3 hardened validity (1.0 target coverage, ≥2 roles, `target_role_lost`) | `scorer.py` | M |
| T5 | Generalize `CandidateScore`/`score_candidate_reanchored` to arbitrary role sets (drop `rank33`/`rank40` — order_metric.py:204); this becomes the shared scoring core for T4 + the 6c harness | `order_metric.py` | S-M |

**Plan B — the kill switch (STOP gate; runs before any loop wiring):**
| # | Task | Where | Size |
|---|---|---|---|
| T6 | Fixture creation: extract `a527c0227~1`/`a527c0227` pair; **verify the pre-win base is derivation-eligible** (register-only + `routing: directed` — see §6c contingency; if not, promote the cardstate witness to gating and report); derive OrderTarget on the pre-win base; choose + verify the negative control; freeze sources+pcdumps+target | `tests/fixtures/order_distance/…` | M (extraction + re-verification; commit verified present) |
| T7 | Kill-switch harness + assertions (a)-(d) + the cardstate secondary witness + result doc | new test/harness module | M |

**Plan C — loop wiring + pool census (only after B passes):**
| # | Task | Where | Size |
|---|---|---|---|
| T8 | POLARITY: objective-aware gate comparator (lower-is-better order mode) | `gate.py` | S-M |
| T9 | POLARITY: scheduler best-selection + parent-state scalar threading (incl. replacing the `object.__setattr__` frozen-state hack at scheduler.py:254-263) | `scheduler.py`, `contracts.py` | M |
| T10 | `debug search directed` flags (`--order-target`/`--objective`/`--permuter-arm`) + objective build from OrderTarget + routing refusal | `search/cli/__init__.py`, `run.py` | M |
| T11 | `score-order` permuter scorer + `setup-order-scorer` (modeled on the simplify-order pair, §3.3 sentinel on coverage loss) | new module + `cli/debug/__init__.py` | M |
| T12 | Pool derivation census (run `order-target` across the remaining 9; classification table) + validation runs 6a/6b/6d + result doc | runtime + docs | M |
| T13 | *(conditional on 6d starvation)* `comma_expr_licm` + `dead_anchor_band_lift` mutators + anchors | `mutators.py`, `anchors.py` | M |

**Why this is bigger than rev 1's estimate (6-9 → 12+1):** codex verified each rev-1 task was
underestimated — no `objective_mode` exists, the scorer/gate/scheduler polarity is structural
(two files, plus a frozen-dataclass mutation to unwind), `CandidateScore` is pilot-shaped,
the derivation pipeline gained the conflict classifier + minimal-set search + verify-
application + determinism steps, and the kill-switch fixtures are a real task. The ordering
spends the least before the §6c STOP gate: A (core) → B (kill switch) → C (everything else).

**Codex review gate (per doctrine):** this revised SPEC and each PLAN get an independent
`codex:codex-rescue` review before execution, with explicit attention to (i) whether 6c can
be passed trivially and (ii) whether the §4.2 minimal-forcing-set search is well-defined on
`HandleInput`.

---

## 10. Revision 2 changelog (codex blockers + oracle evidence)

1. **Derivation rewritten (codex B1):** rev 1 read the order from the build forced by
   `force-phys-from-diff`'s vector — but that vector is PHYS constraints
   (cli/debug/__init__.py:793/:871/:1396), and phys forcing leaves the select order at
   baseline ⟹ rev 1 would have re-imported the hollow objective. §4.2 now: phys map (+
   conflict classifier) → TRUE forced-ORDER compile (`--force-iter-first`, ≤64 minimal set)
   → verify-application → class-partition gate → readback from the FORCED build →
   prune → derive-twice determinism → persist.
2. **Coverage hardening (codex B2):** §3.3 — Kendall's ignores-unmapped behavior
   (metric.py:115, test_metric.py:32) closed at the objective: 1.0 reanchor coverage over the
   pruned target-role set + ≥2 roles or `invalid`; ~0.8 as diagnostic only; routing keys on
   REANCHOR coverage, never `TargetSpec.target_coverage` (rank-present ≠ reanchored,
   role_descriptor.py:160). Amendment: derivation-time target-role pruning makes 1.0
   implementable on many-role targets.
3. **Estimate redone (codex B3):** 6-9 tasks/2 plans → **12 + 1 conditional / 3 plans**, with
   the gate+scheduler POLARITY work first-class (gate.py:92, scheduler.py:254), the
   `CandidateScore` generalization explicit, and the live-CLI landing risk (package
   `__init__.py` copies; legacy 1MB siblings) named + filed.
4. **Kill switch tightened (codex B4, adopted verbatim):** §6c — frozen fixtures (pre-win /
   win / negative-control sources + pcdumps + OrderTarget), assertions (a) same anchored
   target-role set, (b) strict descent, (c) a named pair flips in the intended direction,
   (d) negative control does not descend; mutator-independent by construction. Correction to
   the finding's framing: the fixture pair is NOT lost — commit `a527c0227` exists in the
   object store (verified), so T6 is extraction+freezing, not archaeology. One flagged
   addition: the win commit's save-count change means the pre-win base may not be
   derivation-eligible — §6c carries an explicit contingency (cardstate witness promoted to
   gating + orchestrator informed) instead of a silent assumption.
5. **Oracle evidence folded:** `8024227C` reclassified `not_order_class` (arg-home coalescing
   root ig56) and removed from validation — replaced by `mnDiagram3_HandleInput` as the large
   gradient case (GPR sub-objective). New §4.4: derivation IS the class partition, with
   `8024227C` as the worked example. Two operational caveats absorbed: the 64-entry force cap
   (silent no-op ⟹ minimal-set search + `force_cap_blocked` routing) and DLL/CLI feature skew
   (verify-application mandatory).
6. **Advisories:** role-layer paths corrected to `tools/melee-agent/src/mwcc_debug/`; FPR
   declared v2 with the code guard cited (role_descriptor.py:77); the serialized
   build-lock cost model added (pcdump_backend.py:123-165).
