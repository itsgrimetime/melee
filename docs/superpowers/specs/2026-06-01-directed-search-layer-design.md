# Directed (pcdump-guided) Search Layer — Design

**Status:** Approved design, under independent review (Codex rounds 1–2 incorporated 2026-06-01)
**Builds on:** `docs/superpowers/specs/2026-06-01-fast-directed-search-substrate-design.md`
**Proof target:** `grIceMt_801F9ACC` (the ev/did register select-order wall, 98.84%, blind permuter confirmed insufficient)

---

## 1. Context & motivation

The recurring terminal wall is an **emergent register select-order / interference-graph (ig) ordering** that local tweaks can't reach and blind permuter can't crack (9ACC's 2-way `ev`/`did` coloring swap floored permuter at 7,400+ and ~72K iters on no-op nudges). It is the class the substrate's deferred **directed** seams were designed for.

Two assets exist:
- **The substrate**: directed seams present but **deferred/unwired** — `score_directed` raises `NotImplementedError`, `should_escalate` returns `False`, `DefaultScheduler.ingest()` calls only `score_byte` (pcdump routing is a deferred comment), `CandidateArtifact.directed_score` slot, `BackendCaps.supports_pcdump`/`want_pcdump`. `VariantSource` is **`next_batch(n) -> list[SourceVariant]`** (synchronous, before producers poll); `ArtifactProducer` is async submit/poll. `search.TargetSpec` = `{function, unit, expected_obj}`.
- **The convergence engine** in `tools/melee-agent/src/mwcc_debug/`: `analyze_iteration_full(target, compile, class_id) -> (IterationState, FirstDivergenceReport, ReanchorResult)` where `case = state.fact.case`, identity `state.identity`/`res.matched`, `state.role_order_rank` (a **fixed target rank per original IG, not a candidate distance**), coverage `len(res.matched)/len(target.roles)`; its `target` is the **mwcc-debug** target (roles + metadata, distinct from `search.TargetSpec`) and `compile` is a `role_descriptor.Compile`. `classify_progress(prev_state, state, edit_was_order_change, history, checkdiff_clean)` → labels. `analyze_first_divergence` returns `source=None`. `suggest_coalesce`/`coalesce_patterns` are a separate pair/discover tool emitting `pattern_name` (`direct-identity`, `chain-init`, `alias-split`, `common-subexpr`) + advisory prose `source_hint`. `colorgraph_parser` exposes `ColorgraphDecision`/`SimplifyEntry` with `iter_idx`/`ig_idx`.

Per Codex rounds 1–2, several spec assumptions conflicted with this reality and are corrected throughout (see Appendix A). The load-bearing corrections: a real **candidate ordering distance** (not `role_order_rank`) is the directed metric; directed scoring is **pure vs an explicit parent**; a **`DirectedDiagnosis`** object and a **source-anchor resolver** must be *built* (the analysis returns neither mutator nor anchor); the scheduler **tier-2 branch is a build**, decided from byte-history *before* compile.

## 2. Decisions (locked in brainstorming)

1. **Success = both, sequenced.** Phase 1: validated mechanism with a machine-checked gate on 9ACC. Phase 2: LLM Editor + the 100% attempt.
2. **Editor = hybrid.** Deterministic **typed-mutator** `DirectedSource` (`VariantSource`) is the phase-1 spine; an **async `LlmEditorProducer`** is the phase-2 reach.
3. **Scope = general divergence engine.** Reuse `analyze_iteration_full` + role-identity + labels + reanchor coverage; harness-validity is a first-class pillar.
4. **Approach = decompose into substrate primitives.** Reuse the analysis as a library; do not run `run_convergence_loop`, but **preserve its progress state explicitly** as a `DirectedSearchState` (`prev_state`, `history`, `last_lever`, baseline) — advanced only on best-selection, never mid-batch.

## 3. Architecture & data flow

| Convergence piece (reused) | Substrate seam / **(build)** |
|---|---|
| typed mutators selected by `DirectedDiagnosis` **(build)** | **`DirectedSource`** (`VariantSource`, `next_batch`) |
| LLM edit generation **(build, phase 2)** | **`LlmEditorProducer`** (async `ArtifactProducer` + directed context) |
| `analyze_iteration_full` + ordering distance + `classify_progress` | **tier-2 `ScorePipeline.score_directed`** (pure vs parent) |
| byte-score plateau | **`ScorePipeline.should_escalate`** **(build)** |
| `MWCC_DEBUG_PCDUMP_PATH` + `--keep-obj` | **`PcdumpLocalBackend`** **(build)** |
| (none — derived) | **`DirectedDiagnosis`** + **source-anchor resolver** **(build)** |

`run_convergence_loop` is **not** used. The substrate `DefaultScheduler` gains a **tier-2 escalation branch (build)** — the deferred seam, activated. One directed iteration:

1. **Escalation mode is decided from prior byte-score history before the batch** (Codex P1-6), so `want_pcdump` is known at compile time. In directed mode, all compiles route to `PcdumpLocalBackend`.
2. `DirectedSource.next_batch(n)` → `list[SourceVariant]` (each = a typed mutator applied to the current-best, selected by the current `DirectedDiagnosis`). `[]` on exhaustion.
3. Backend compile (`PcdumpLocalBackend` in directed mode) → `.o` + bound pcdump pair.
4. `score_byte` (tier-1). `byte_score==0` + checkdiff-clean → win short-circuit.
5. `score_directed(candidate, parent_state)` — **pure** (Codex P0-1): scores the candidate against its **parent** state (`parent_candidate_id`/`parent_state_id`), returns `DirectedMeta`, mutates **no** global state.
6. The scheduler **selects the new current-best** from the batch (tier-1 byte, then directed scalar); `observe` then advances the global `DirectedSearchState` to that best and updates the stall counter. K stalls → scheduler **dynamically starts** `LlmEditorProducer` with directed context (Codex P1-7).

## 4. Data contracts (build — Codex P0-2, P1-3, P1-4, P2-8)

- **`DirectedObjective`** (qualified fields, resolving the `TargetSpec` collision): `{search_target: search.TargetSpec, role_target: mwcc_debug target, baseline_compile: role_descriptor.Compile, baseline_pcdump_path: Path, baseline_source_hash: str, class_id: int}`.
- **`DirectedDiagnosis`** (derived — does not exist in the analysis today): `{case, target_igs, source_idea, coalesce_pair | None, mutator_key | None, resolved_anchor | None, analysis_valid: bool, actionable: bool, invalid_reason: str | None}`. A builder composes it from `(IterationState, FirstDivergenceReport, ReanchorResult)` + the anchor resolver + `suggest_coalesce`. `analysis_valid` and `actionable` are **separate** (Codex P2-9).
- **`DirectedMeta`** (attached to the scored candidate, fully linkable): `{candidate_id, source_hash, iteration, parent_id, parent_state_id, valid, invalid_reason, case, label, order_distance: float, order_distance_delta: float, reanchor_matched, reanchor_total, diagnosis_chars, applied_mutator: str | None, directed_scalar: float}`.
- **`CandidateArtifact`** gains `directed_meta: DirectedMeta | None` and status **`"invalid"`**.
- **`SearchResult`** gains `directed_telemetry: list[DirectedMeta]`.

## 5. The core units

### 5.1 `DirectedSource` (`VariantSource`, `next_batch(n)`)
- **`next_batch(n)`**: from the current `DirectedDiagnosis`, apply up to `n` untried typed mutators to the current-best; `[]` on exhaustion.
- **Typed mutators + anchor resolver (build — Codex P1-5):** mutators are *programmatic* C transforms with resolved source anchors. They require a **source-anchor resolver** (build) that maps a `DirectedDiagnosis.source_idea`/`coalesce_pair` to concrete source spans — the existing `pattern_name`/prose `source_hint` do **not** carry anchors. Phase 1 ships **only the mutators whose anchors the resolver can actually derive** from real `SourceIdea` fields, mapped from real pattern names (`direct-identity`→accessor/identity routing, `chain-init`→hoist-temp-before-use, `alias-split`→introduce-indirection-local, `common-subexpr`→reorder/reuse). A mutator whose anchor can't resolve is skipped (never emits broken source). The 9ACC levers (int-return, GetUserData accessor, new_var indirection) are the concrete validation set.
- **`observe(scored)`**: the scheduler having selected the new current-best, `observe` advances the global `DirectedSearchState` (`prev_state`/`history`/`last_lever`) to it; records mutator→Δscalar; increments the stall counter; signals escalation at K stalls.

### 5.2 `score_directed` (tier-2 `ScorePipeline`, pure vs parent)
- **Pure**: `score_directed(candidate, parent_state) -> DirectedMeta`. Runs the analysis on the candidate's pcdump vs the `DirectedObjective`, using the **parent's** `prev_state`/`history`/`last_lever`; mutates no global state (Codex P0-1).
- **Directed scalar = candidate ordering distance (Codex P1-2, load-bearing):** for select-order cases the scalar is a real ordering distance between the candidate's decision order (from `colorgraph_parser`'s `iter_idx`) and the objective role order — **Kendall-τ / pairwise inversions over the objective role pairs**. `role_order_rank` is a fixed target rank and is *flat* on a 2-way swap, so it is **not** the metric. Reanchor coverage and the categorical `label` are secondary (direction/validity), not the primary gradient. The ordering distance is **mandatory** for the 9ACC proof target and gated by 9ACC fixtures.
- **`should_escalate(byte-score history) → bool` (Codex P1-6):** plateau over the last N (no best-byte improvement); evaluated from prior history *before* the next batch so `want_pcdump` is set at compile.
- **Validity (`analysis_valid`, hardened — Codex P1-6, P2-9):** `INVALID` (status `"invalid"`) unless roles non-empty, `case ∉ {NONE, ABSTAINED}` (`ABSTAINED` carries a non-empty `local_target` but is non-actionable), `report` present, reanchor coverage ≥ floor, and identity/rank present where used. This gates **scoring validity** only; whether the *next* diagnosis is actionable is a separate search-continuation signal and must **not** invalidate a candidate's real progress.

### 5.3 `PcdumpLocalBackend` (`CompileBackend`, build — Codex P1-8)
Compiles via the proven debug path (`--keep-obj` + `MWCC_DEBUG_PCDUMP_PATH=<out>.pcdump.txt`, one invocation), under the same repo build lock as `RealLocalCompiler`. Stores `.o` + pcdump as one content-addressed pair with both digests bound (no stale/mismatched pcdump). `supports_pcdump=True`.

### 5.4 `LlmEditorProducer` (`ArtifactProducer`, build — phase 2, Codex P1-7, P2-10)
Async producer with an explicit **directed request context** (extends the producer protocol): `{current_source, diagnosis, failed_mutators, source_hints, budget}`. The scheduler **starts and stops it dynamically mid-loop** after `observe` signals escalation (the substrate today starts producers only pre-loop — this is a scheduler extension). Bounded by a hard per-run token/edit budget; emits source-only candidates recompiled by the scheduler like any producer.

## 6. Scheduler tier-2 branch & validity harness (build — Codex P0-1, P1-6, P1-7, P2-9)

`DefaultScheduler` is extended (generic; any tier-2 scorer reuses it):
- Maintain **byte-score history** and the global `DirectedSearchState`. Decide escalation mode from history **before** each batch; in directed mode, compile through `PcdumpLocalBackend` (`want_pcdump`). The triggering candidate is recompiled once through `PcdumpLocalBackend` to bind its pcdump.
- Call `score_directed(candidate, parent_state)` **purely** per candidate; attach `directed_meta`; surface `INVALID` loudly (never control-equivalent); append to `directed_telemetry`.
- **Select** the new current-best, then `observe` (advances `DirectedSearchState`).
- Dynamically start/stop `LlmEditorProducer` on escalation.
- Existing dedup/promote/win short-circuit unchanged.

**Validity harness — three layers:**
1. **Per-candidate:** the hardened `analysis_valid` gate (§5.2), incl. `ABSTAINED`.
2. **Per-run pre-flight:** validate the `DirectedObjective` — run the analysis once against the defined `baseline_compile`/`baseline_pcdump` and assert roles non-empty, `case ∉ {NONE, ABSTAINED}`, `report` present. Abort loudly otherwise (the gate-3 pilot-#1 failure).
3. **Per-run gate (attributable — Codex P2-9, P2-11):** phase-1 passes iff pre-flight green AND treatment candidates are `analysis_valid` AND ≥1 shows **attributable** progress: an `order_distance` improvement (a) attributed to a specific applied mutator, (b) with non-regressed byte score and stable-or-improved reanchor coverage, (c) better than a control/baseline candidate. Attribution is on the **applied** mutator, independent of whether the *next* diagnosis is actionable.

## 7. Phase plan

- **Phase 1 — Validated mechanism.** Build: `PcdumpLocalBackend`; the scheduler tier-2 branch (byte-history, directed mode, pure scoring, best-selection, telemetry); `DirectedObjective` + pre-flight; the `DirectedDiagnosis` builder + source-anchor resolver; the ordering-distance metric (`iter_idx` Kendall) + `score_directed` + hardened validity; `should_escalate`; the typed-mutator `DirectedSource` (derivable mutators only); the contract additions (`directed_meta`, `"invalid"`, telemetry). Validate on 9ACC.
  **→ GATE (machine-checked, §6.3).** If red, **stop and reassess**.
- **Phase 2 — Capability + 100% attempt.** Build `LlmEditorProducer` + dynamic escalation. Run the hybrid search on 9ACC for `byte_score==0`+checkdiff-clean. Deliverable: cracked, or a characterized partial (order_distance reached X).

## 8. Testing

- **Ordering-distance metric:** 9ACC fixtures at known states → Kendall/inversion distance decreases as the ev/did order approaches the objective; `role_order_rank` is shown flat across the same fixtures (justifying its rejection).
- **Pure scoring (Codex P0-1):** two batch-sibling candidates from one parent get identical scores regardless of evaluation order (no cross-contamination).
- **`DirectedDiagnosis` builder:** from fixture `(IterationState, FirstDivergenceReport, ReanchorResult)` → asserts `case`, `mutator_key`, resolved anchor, and the `analysis_valid`/`actionable` split.
- **Anchor resolver + mutators:** golden tests — resolver derives the right span; each mutator produces the exact expected patched source; un-resolvable anchor → skipped.
- `score_directed` validity: `INVALID` on empty-roles, `NONE`, **`ABSTAINED`**, missing-report, low-coverage.
- **Gate-3 regression:** empty/degenerate roles → pre-flight ABORT, not a silent control-equivalent run.
- `PcdumpLocalBackend`: one invocation yields `.o`+pcdump with bound digests.
- **Plateau:** fixed-residual byte-history → `should_escalate` fires after exactly N; improving history → never.
- **Scheduler tier-2 + dynamic producer:** directed mode routes pcdump; INVALID surfaced (not progress); telemetry populated; `LlmEditorProducer` starts on escalation and stops on budget.
- **Phase-1 gate:** passes on attributable-progress telemetry; fails on VOID telemetry and on unattributed/regressing "progress".

## 9. Out of scope (YAGNI)

- Mutator/anchor-resolver coverage beyond what 9ACC + the derivable `coalesce_patterns` need.
- Multi-function batch directed search; remote/distributed directed search (local `PcdumpLocalBackend` is the vehicle).

## 10. Success criteria

- **Phase 1 (gate):** machine-checked per §6.3 on 9ACC — pre-flight passes; treatment candidates `analysis_valid`; ≥1 attributable `order_distance` improvement. Provably non-VOID and genuinely diagnosing.
- **Phase 2:** `grIceMt_801F9ACC` `match=true`/100%, or a characterized partial that advances `order_distance` and isolates the residual.
- **No silent regressions:** integrates behind the activated tier-2 seam; existing substrate tests stay green; the extended litmus (a second tier-2 scorer drops in behind the same branch) holds.

---

### Appendix A — Codex review log
- **Round 1 (gpt-5.5 xhigh):** scheduler tier-2 branch is a build; diagnosis/validity/telemetry channel + `INVALID`; `source_hint`s advisory → typed mutators; real `analyze_iteration_full` schema, drop `distance_to_flip`; preserve `DirectedSearchState`; `ABSTAINED` invalid; byte-history plateau; `PcdumpLocalBackend`; `DirectedObjective` baseline compile; LLM as async producer; attributable gate; `next_batch(n)`. (`ig_idx` exposed; same-invocation pcdump proven.)
- **Round 2 (gpt-5.5 xhigh):** directed scoring **pure vs parent**, global state advances only on best-selection (P0-1); **`role_order_rank` is flat on the 9ACC swap → ordering distance (Kendall on `iter_idx`) is the mandatory metric** (P1-2); `DirectedObjective` qualified fields resolving the `TargetSpec` collision (P1-3); `DirectedDiagnosis` must be built — analysis returns no diagnosis/mutator/anchor, `analyze_first_divergence` `source=None` (P1-4); mutators grounded in real pattern names + a source-anchor resolver, phase-1 shrunk to derivable mutators (P1-5); escalation decided from byte-history before compile so `want_pcdump` is set (P1-6); `LlmEditorProducer` needs directed context + dynamic mid-loop start/stop (P1-7); `directed_meta` linkage fields (P2-8); split `analysis_valid` from `actionable` (P2-9).
