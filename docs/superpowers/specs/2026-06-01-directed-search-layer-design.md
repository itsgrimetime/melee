# Directed (pcdump-guided) Search Layer — Design

**Status:** Approved design, under independent review (Codex round 1 incorporated 2026-06-01)
**Builds on:** `docs/superpowers/specs/2026-06-01-fast-directed-search-substrate-design.md` (the substrate — five primitives, two converging paths, deferred directed seams)
**Proof target:** `grIceMt_801F9ACC` (the ev/did register select-order wall, 98.84%, blind permuter confirmed insufficient)

---

## 1. Context & motivation

The recurring terminal wall on hard functions is an **emergent register select-order / interference-graph (ig) ordering** that local source tweaks can't reach and blind permuter can't crack. Confirmed empirically on `grIceMt_801F9ACC`: its sole residual is a 2-way `ev`/`did` callee-save coloring swap; remote permuter floored at 7,400+ AND ~72K iters on semantically-neutral "no-op nudges" that never flip the coloring. This is a **mutation-space** ceiling, not an iteration-count one — exactly the class the substrate's deferred **directed** seams were designed for.

Two assets already exist:
- **The substrate** ships the directed seams in place but **deferred/unwired**: `ScorePipeline.score_directed` raises `NotImplementedError`, `should_escalate` returns `False`, `DefaultScheduler.ingest()` calls only `score_byte` (pcdump routing is an explicit deferred comment), `CandidateArtifact` has a `directed_score: float | None` slot, and `BackendCaps.supports_pcdump`/`want_pcdump` exist. The `VariantSource` interface is **`next_batch(n) -> list[SourceVariant]`** (synchronous, called inline before producers are polled); `ArtifactProducer` is the async submit/poll lifecycle.
- **A general convergence/divergence engine** in `tools/melee-agent/src/mwcc_debug/`: `analyze_iteration_full(target, compile, class_id) -> (IterationState, report, ReanchorResult)` (divergence `case = state.fact.case`; role identity `state.identity` / `res.matched`; `state.role_order_rank`; reanchor coverage `len(res.matched)/len(target.roles)`); `classify_progress(prev_state, state, edit_was_order_change, history, checkdiff_clean)` producing `MOVED_LATER`/`SAME`/`CYCLE`/`NON_COMPARABLE`/`ROLE_GONE`; `coalesce_patterns` + `suggest_coalesce` (IR-grounded checkers emitting **advisory** `source_hint: Optional[str]` prose); `colorgraph_parser` (`ColorgraphDecision`/`SimplifyEntry` expose `iter_idx`/`ig_idx`). This shipped as the role-identity matcher but is **research-grade**: the **Editor** was never completed, and the **gate-3 pilots silently ran VOID 4×** (empty `target.roles` → `case=NONE` → every arm == control).

This build connects the two. Per Codex round 1, three spec assumptions were wrong and are corrected throughout: (a) the scheduler **must** gain a tier-2 branch (it is not zero-change — it activates a deferred seam); (b) `source_hint`s are advisory text, so a real **typed-mutator** Editor must be built; (c) `distance_to_flip` is not a real field — the directed signal is built from `role_order_rank` + reanchor coverage + label (+ optional `ig_idx`-derived refinement).

## 2. Decisions (locked in brainstorming)

1. **Success = both, sequenced.** Phase 1: a validated directed *mechanism* that measurably advances the directed score on 9ACC under a trustworthy harness; machine-checked gate. Phase 2: add the LLM Editor and attempt 9ACC → 100%. A sound mechanism that doesn't crack 9ACC is a characterized partial success.
2. **Editor = hybrid.** A deterministic **typed-mutator** Editor (a `DirectedSource` `VariantSource`) is the validated phase-1 spine; an **LLM Editor** (an async `ArtifactProducer`) is the phase-2 reach, activated only after the deterministic tier stalls.
3. **Scope = general divergence engine.** Reuse the full `analyze_iteration_full` + role-identity + progress labels + reanchor coverage. This makes the **harness-validity problem a first-class pillar** (it caused the gate-3 VOID failures).
4. **Approach = decompose into substrate primitives.** Reuse the convergence *analysis* as a library; do **not** run `run_convergence_loop`. The substrate scheduler (with an activated tier-2 branch) replaces its orchestration, but the **convergence progress state it carried (`prev_state`, `history`, `last_lever`, baseline) is preserved explicitly** as a `DirectedSearchState` (Codex P1-5) — dropping the loop must not drop that state.

## 3. Architecture & data flow

Reused convergence pieces map onto substrate seams; new build items are marked **(build)**:

| Convergence piece (reused as library) | Substrate seam / new item |
|---|---|
| typed mutators selected by diagnosis **(build)** | **`DirectedSource`** — a `VariantSource` (`next_batch`) vending edited sources |
| LLM edit generation **(build, phase 2)** | **`LlmEditorProducer`** — an async `ArtifactProducer` |
| `analyze_iteration_full` + `classify_progress` (+ `DirectedSearchState`) | **tier-2 `ScorePipeline.score_directed`** |
| byte-score plateau detection **(build)** | **`ScorePipeline.should_escalate`** |
| `MWCC_DEBUG_PCDUMP_PATH` + `--keep-obj` compile path | **`PcdumpLocalBackend`** **(build)** |

`run_convergence_loop` is **not** used. The substrate `DefaultScheduler` gains a **tier-2 escalation branch (build)** — the deferred seam, now activated. One directed iteration:

1. `DirectedSource.next_batch(n)` → `list[SourceVariant]` (each = a typed mutator applied to the current best, selected by the latest diagnosis). Returns `[]` on exhaustion (Codex P2-12).
2. Scheduler → backend compile. **When `should_escalate` is active, route to the pcdump-capable `PcdumpLocalBackend`** (`want_pcdump`), which emits `.o` + pcdump from one invocation as a content-addressed pair (Codex P1-8).
3. `score_byte` (tier-1). `byte_score==0` + checkdiff-clean → win short-circuit (exists).
4. **`should_escalate(byte-score history)`** (Codex P1-7): `True` on a defined plateau (N candidates with no best-byte improvement). On escalate → `score_directed(candidate, DirectedSearchState)` reads the pcdump → directed result (scalar + label + diagnosis + validity), updating `DirectedSearchState`.
5. Directed results flow back via `observe` (the existing per-batch feedback edge): `DirectedSource` updates current-best and stall counter; on K stalls the scheduler **starts the `LlmEditorProducer`** (phase 2).

**Cross-unit coupling (corrected, Codex P1-5):** not just "diagnosis." A `DirectedSearchState` (owned by the directed coordinator/pipeline) carries `prev_state`, `history`, `last_lever`, the `DirectedObjective` (below), and the current best — threaded into every `score_directed` so `classify_progress` is correct.

## 4. Data contracts (new — Codex P0-2, P1-9)

- **`DirectedObjective`** (the pre-flight-validated target): `{TargetSpec, baseline_compile, baseline_pcdump, baseline_source_hash, class_id, roles}`. Defines exactly which compile/pcdump the analysis runs against (the existing analysis needs a `compile` callable; `TargetSpec` has none today).
- **`DirectedMeta`** (attached to a scored candidate; extends the artifact/telemetry channel): `{valid: bool, invalid_reason: str | None, case, label, role_order_rank: int | None, rank_delta: int | None, reanchor_matched: int, reanchor_total: int, diagnosis: str, diagnosis_chars: int, applied_mutator: str | None, directed_scalar: float}`.
- **`CandidateArtifact.status`** gains **`"invalid"`** (alongside `ok`/`harvested`/`compile_failed`/`score_failed`) so an `INVALID` directed analysis is first-class, never silently a "no-progress" score.
- **`SearchResult`** gains a `directed_telemetry: list[DirectedMeta]` so the phase-1 gate is machine-checkable from the result alone.

## 5. The core units

### 5.1 `DirectedSource` (`VariantSource`, `next_batch(n)`)
- **`next_batch(n) → list[SourceVariant]`**: from the latest diagnosis, select up to `n` untried **typed mutators** and apply each to the current-best source. Returns `[]` when mutators are exhausted (Codex P2-12).
- **Typed mutators (build — Codex P0-3):** a small library of *programmatic* C transforms, each with resolved source anchors + concrete replacement (not the advisory `source_hint` text). Initial set, grounded in the 9ACC levers and `coalesce_patterns` semantics: `wrap_field_access_in_accessor`, `hoist_temp_before_branch`, `reorder_decl`, `change_return_type_to_int`, `introduce_indirection_local`. The diagnosis (target coalesce/role from the analysis) + the advisory `source_hint` select the mutator and its parameters; the mutator performs the edit. Mutators that cannot resolve their anchors in the current source are skipped (not emitted as broken candidates).
- **`observe(scored)`**: updates current-best (best tier-1, tie-broken by directed scalar), records which mutator moved vs stalled the directed scalar, increments a stall counter; **K consecutive stalls signals escalation** (the scheduler then starts the LLM producer).

### 5.2 `score_directed` (tier-2 `ScorePipeline`)
- Reads `candidate.pcdump_path`, runs the analysis vs the `DirectedObjective` using `DirectedSearchState.prev_state`/`history`/`last_lever` → `case`, identity, `role_order_rank`, reanchor coverage, progress `label`. Updates `DirectedSearchState`.
- **Directed scalar (corrected — no `distance_to_flip`, Codex P1-4):** composite of reanchor coverage (primary "how close") and `role_order_rank` progress, with the categorical `label` as direction. *Optional refinement* for select-order cases: an ig-ordering distance derived from `colorgraph_parser`'s `ig_idx` (confirmed exposed) — gated behind its own tests; not a hard dependency.
- **`should_escalate(byte-score history) → bool` (Codex P1-7):** `True` when the best byte-score has not improved over the last N candidates (plateau). Requires byte-score history in the directed context (added; `SearchContext` lacks it today).
- **Validity gates (hardened — Codex P1-6):** return an `INVALID` result (status `"invalid"`, with `invalid_reason`) unless ALL hold: roles non-empty; **`case ∉ {NONE, ABSTAINED}`** (`ABSTAINED` carries a non-empty `local_target` but is explicitly non-actionable — text length alone is insufficient); `report` present; reanchor coverage ≥ a floor; identity/rank present when rank scoring is used; and the diagnosis maps to an **actionable** mutator/anchor (not just `diagnosis_chars>0`). The scheduler surfaces `INVALID` loudly and never counts it as control-equivalent.

### 5.3 `PcdumpLocalBackend` (`CompileBackend`, build — Codex P1-8)
Compiles a candidate through the debug compiler path that already works (`debug dump local` style: `--keep-obj` + `MWCC_DEBUG_PCDUMP_PATH=<out>.pcdump.txt` in one invocation), under the same repo build lock as `RealLocalCompiler`. Stores the `.o` and the pcdump as a single content-addressed artifact pair (source/object/dump digests) so the pcdump provably belongs to the same compile that produced the `.o`. Reports `supports_pcdump=True`.

### 5.4 `LlmEditorProducer` (`ArtifactProducer`, build — phase 2, Codex P2-10)
The LLM Editor is **async** (an `ArtifactProducer`), not a blocking `next_batch` call: given {current source, diagnosis, failed mutator attempts, advisory `source_hint`s}, it generates candidate edits off the critical path, bounded by a hard per-run token/edit budget, with submit/poll/stop like the permuter producer. The scheduler starts it only on escalation (K deterministic stalls).

## 6. Escalation, scheduler wiring & the validity harness

**Scheduler tier-2 branch (build — Codex P0-1):** `DefaultScheduler` is extended (the deferred seam, activated) to: keep byte-score history + `DirectedSearchState`; when `should_escalate` fires, route `want_pcdump` to `PcdumpLocalBackend`, call `score_directed`, attach `DirectedMeta`, surface `INVALID` loudly, record `directed_telemetry`, and pass directed-scored candidates to `observe`. This branch is generic (any tier-2 scorer uses it); the directed layer drops in behind it. The existing dedup/promote/win short-circuit are unchanged.

**Escalation:** K consecutive stalled directed scalars (tracked in `observe`) → scheduler starts `LlmEditorProducer` (bounded). Deterministic mutators are the validated phase-1 spine; the LLM is the phase-2 reach.

**Validity harness — three layers (the gate-3 fix; a silent VOID run must be impossible):**
1. **Per-candidate:** the hardened `INVALID` result (§5.2), including `ABSTAINED`.
2. **Per-run pre-flight:** before any search, validate the `DirectedObjective` — run the analysis once against the **defined baseline compile/pcdump** and assert roles non-empty, `case ∉ {NONE, ABSTAINED}`, `report` present, `diagnosis` actionable. On failure, **abort loudly** (the exact empty-`target.roles` failure that voided gate-3 pilot #1).
3. **Per-run gate telemetry:** the **phase-1 gate passes iff** pre-flight passed AND the escalated/treatment candidates are `valid` with `case ∉ {NONE, ABSTAINED}` AND ≥1 shows **attributable** directed progress (Codex P2-11): a `MOVED_LATER`/`role_order_rank` improvement that is (a) attributed to a specific applied mutator, (b) accompanied by non-regressed byte score and stable-or-improved reanchor coverage, and (c) better than a control/baseline candidate. This automates the gate-3 post-mortem rule.

## 7. Phase plan

- **Phase 1 — Validated mechanism.** Build: `PcdumpLocalBackend`; the scheduler tier-2 branch + byte-history + `DirectedSearchState`; `score_directed` + hardened validity gates; `should_escalate`; the `DirectedObjective` + pre-flight; the typed-mutator `DirectedSource` (deterministic only); the `DirectedMeta`/`INVALID`/telemetry contract additions. Validate on 9ACC.
  **→ GATE (machine-checked):** pre-flight green AND treatment candidates valid (`case ∉ {NONE,ABSTAINED}`) AND ≥1 *attributable* directed-progress signal (§6.3). If red, **stop and reassess** — do not build the LLM tier on a broken foundation.
- **Phase 2 — Capability + 100% attempt.** Build `LlmEditorProducer` + escalation. Run the full hybrid directed search on 9ACC for `byte_score==0`+checkdiff-clean. Deliverable: 9ACC cracked, or a characterized partial (directed scalar reached X; final edit eluded the LLM).

## 8. Testing

- **Typed mutators:** golden tests — each mutator applied to a fixture source produces the exact expected patched source; un-resolvable anchors → skipped, not broken output.
- `DirectedSource`: fake scorer feeds canned diagnoses → asserts the right mutator per case; `observe` flips to escalation after K stalls; exhaustion → `[]`.
- `score_directed`: **fixture pcdumps captured from 9ACC at known states** → assert scalar/label/diagnosis from the real `analyze_iteration_full` return; assert `INVALID` on empty-roles, `case==NONE`, **`case==ABSTAINED`**, missing-report, and low-coverage fixtures.
- **Gate-3 regression test:** empty/degenerate `target.roles` triggers pre-flight **ABORT**, not a silent control-equivalent run.
- `PcdumpLocalBackend`: a compile yields a `.o` and a pcdump from one invocation; the pcdump digest is bound to the `.o` digest (no stale/mismatched pcdump).
- **Plateau:** byte-history with a 9ACC-like fixed residual → `should_escalate` fires after exactly N; a still-improving history → does not fire.
- **Scheduler tier-2 branch:** a planted matching candidate reaches the win short-circuit; an escalated INVALID candidate is surfaced (not counted as progress); `directed_telemetry` is populated.
- **Phase-1 gate:** passes on an attributable-progress telemetry fixture; fails on a VOID telemetry fixture and on an unattributed/regressing "progress" fixture (Codex P2-11).

## 9. Out of scope (YAGNI)

- Typed-mutator library expansion beyond what 9ACC + the relevant `coalesce_patterns` cover (extend as needed, don't pre-build the full catalogue).
- Multi-function batch directed search.
- Remote/distributed directed search — the local `PcdumpLocalBackend` is the phase-1/2 vehicle.

## 10. Success criteria

- **Phase 1 (gate):** on 9ACC, machine-checked per §6.3: pre-flight passes; treatment candidates valid (`case ∉ {NONE,ABSTAINED}`); ≥1 attributable directed-progress signal. The mechanism is provably non-VOID and genuinely diagnosing.
- **Phase 2:** `grIceMt_801F9ACC` reaches `match=true`/100%, OR a characterized partial that advances the directed scalar and isolates the residual the LLM couldn't close.
- **No silent regressions:** the directed source/scorer integrate behind the (now-activated) tier-2 seam; all existing substrate tests stay green; the extended litmus (a second tier-2 scorer drops in behind the same branch) holds.

---

### Appendix A — Codex review log
- **Round 1 (2026-06-01, gpt-5.5 xhigh):** incorporated. P0: scheduler tier-2 branch must be built (§3,§6); artifact diagnosis/validity/telemetry channel + `INVALID` status (§4); `source_hint`s are advisory → typed mutators (§5.1). P1: real `analyze_iteration_full` return schema, drop `distance_to_flip` (§5.2); preserve `DirectedSearchState` when dropping the loop (§2,§3); `ABSTAINED` is invalid (§5.2,§6); byte-history for `should_escalate` (§5.2); `PcdumpLocalBackend` (§5.3); `DirectedObjective` baseline compile for pre-flight (§4,§6). P2: LLM editor as async `ArtifactProducer` (§5.4); attributable phase-1 gate (§6.3); `next_batch(n)` shape (§5.1). Confirmed FINE: `ig_idx` exposed; same-invocation pcdump sidecars proven.
