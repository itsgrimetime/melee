# Directed (pcdump-guided) Search Layer — Design

**Status:** Approved (brainstorming, 2026-06-01)
**Builds on:** `docs/superpowers/specs/2026-06-01-fast-directed-search-substrate-design.md` (the substrate — five primitives, two converging paths, deferred directed seams)
**Proof target:** `grIceMt_801F9ACC` (the ev/did register select-order wall, 98.84%, blind permuter confirmed insufficient)

---

## 1. Context & motivation

The recurring terminal wall on hard functions is an **emergent register select-order / interference-graph (ig) ordering** that local source tweaks can't reach and blind permuter can't crack. Confirmed empirically on `grIceMt_801F9ACC`: its sole residual is a 2-way `ev`/`did` callee-save coloring swap; remote permuter floored at 7,400+ AND ~72K iters on semantically-neutral "no-op nudges" that never flip the coloring. This is a **mutation-space** ceiling, not an iteration-count one — more blind iterations cannot help. It is exactly the class the substrate's deferred **directed** seams were designed for.

Two assets already exist:
- **The substrate** ships the directed seams unimplemented but in place: `ScorePipeline.score_directed` (raises `NotImplementedError`), `ScorePipeline.should_escalate` (returns `False`), `CandidateArtifact.pcdump_path` / `want_pcdump` / `supports_pcdump`, and the `VariantSource` / `ArtifactProducer` / `Scheduler` protocols with an `observe()` feedback edge. The litmus proved a new source/scorer drops in with **zero engine change**.
- **A general convergence/divergence engine** exists in `tools/melee-agent/src/mwcc_debug/`: `run_convergence_loop(function, target, editor, checker)` with `Editor`/`Checker` protocols, `analyze_iteration_full` (divergence case, role identities, role-order-rank, reanchor coverage), `classify_progress` (`MOVED_LATER`/`ROLE_GONE`/…), stall detection, cause reports; plus `suggest_coalesce` + `coalesce_patterns` (5 IR-grounded checkers mapping a desired register coalesce → concrete C-source `source_hint`s), and `colorgraph_parser`. This machinery shipped as the role-identity matcher (Units 1–5 + gates) but is **research-grade**: the **Editor** (the generator that turns analysis into a real edit) was the never-completed live experiment, and the **gate-3 convergence pilots hit repeated silent harness-validation bugs** (empty `target.roles` → `case=NONE` → every arm == control; VOID 4×).

This build connects the two: it finishes the **Editor** and a **trustworthy validation harness**, and wires the general engine's analysis into the substrate's directed seams.

## 2. Decisions (locked in brainstorming)

1. **Success = both, sequenced.** Phase 1: a validated directed *mechanism* that measurably advances the directed score on 9ACC under a trustworthy harness. Machine-checked gate. Phase 2: add LLM escalation and attempt 9ACC → 100%. A sound mechanism that doesn't crack 9ACC is still a characterized partial success.
2. **Editor = hybrid.** Deterministic `coalesce_patterns` Editor is the validated phase-1 spine; escalate to an LLM Editor when patterns stop moving the directed score (phase-2 reach).
3. **Scope = general divergence engine.** Reuse the full `analyze_iteration_full` + role-identity + all progress labels + reanchor coverage — handle any divergence case, not only select-order. This choice makes the **harness-validity problem a first-class design pillar** (it is the part that produced the gate-3 VOID failures).
4. **Approach = decompose into substrate primitives.** Reuse the convergence engine's *analysis* as a library; do **not** run `run_convergence_loop` — the substrate's tested scheduler replaces its orchestration, shedding the buggy harness rather than inheriting it.

## 3. Architecture & data flow

Three reused pieces map onto three substrate seams:

| Convergence piece (reused as library) | Substrate seam |
|---|---|
| `Editor` (hybrid `coalesce_patterns` → LLM) | **`DirectedSource`** — a `VariantSource` vending edited candidate sources |
| `analyze_iteration_full` + `classify_progress` | **tier-2 `ScorePipeline.score_directed`** |
| pattern-exhaustion → LLM trigger | **`ScorePipeline.should_escalate`** + `DirectedSource.observe()` |

`run_convergence_loop` is **not** used. The substrate `DefaultScheduler` drives one directed iteration:

1. `DirectedSource.next()` → `SourceVariant` (Editor applies a `coalesce_patterns` edit to the current best, guided by the last diagnosis).
2. Scheduler → `backend.compile(variant)` → `CandidateArtifact`. **Directed mode requires a pcdump-capable backend** (`want_pcdump`/`supports_pcdump`): it emits the mwcc-debug colorgraph dump alongside the `.o`.
3. `pipeline.score_byte` → tier-1 byte distance. `byte_score==0` + checkdiff-clean → win short-circuit (already exists).
4. On byte plateau, `should_escalate` → `score_directed(candidate)` reads the pcdump → directed score.
5. `DirectedSource.observe([scored])` → Editor updates direction; K stalls flip patterns→LLM.

The directed score is a real tier-2 `ScorePipeline`, so it inherits the substrate's lock/restore/no-leak guarantees and dedup/promote scheduler.

## 4. The two core units

### 4.1 `DirectedSource` (`VariantSource`)
- **`next() → SourceVariant | None`**: consults the latest diagnosis. *Deterministic tier:* selects the next untried `coalesce_patterns` `source_hint` applicable to that diagnosis and applies it to the current-best source (concrete C transforms: route `->user_data` through an inline wrapper; hoist a temp computed before the branch; reorder a decl). *LLM tier* (post-escalation): prompt = {current source, diagnosis, failed pattern attempts, `source_hint`s} → LLM returns a C edit. Returns `None` when both tiers are exhausted.
- **`observe(scored) → None`**: ingests directed-scored candidates; updates current-best, records which patterns moved vs stalled the directed score, increments a stall counter (**K consecutive stalls → patterns→LLM**), stores the diagnosis for the next `next()`.
- State is internal; the only cross-unit datum is the diagnosis (produced by 4.2, consumed here).

### 4.2 `score_directed` (tier-2 `ScorePipeline`)
- Reads `candidate.pcdump_path`, runs the convergence analysis vs the target → divergence case, role identities, **role-order-rank, reanchor coverage, `distance_to_flip`**. Reduces to: a **ranking scalar** (how close), a **categorical label** (direction), and the **diagnosis** (what to try next).
- **Discovery step (plan task 1):** `analyze_iteration_full` currently takes `(target, compile, class_id)` (a compile-callable + target), not a pcdump path — mirroring the substrate's Task-9 real-signature discoveries, the plan must first establish the exact pcdump→analysis adapter (either feed the analysis a `compile` that returns the already-built pcdump, or call the lower-level `colorgraph_parser` + role/rank functions directly). The scalar-reduction formula is derived from the real `analyze_iteration_full` return fields at that point.
- **`should_escalate(tier-1 history) → bool`**: `True` when byte-score plateaus over the last N (gates the expensive tier-2 on a tier-1 stall, per the substrate two-tier design).
- **Validity gates (hard preconditions):** before returning any score, assert (a) real roles derived (`target.roles` non-empty), (b) `case ≠ NONE`, (c) `diagnosis_chars > 0`. On failure → return an **`INVALID` sentinel**, distinct from a legitimate "no-progress" score.

## 5. Escalation, scheduler wiring & the validity harness

**Scheduler wiring:** no orchestration change — `sources=[DirectedSource]`, `backend=`pcdump-capable local backend, `pipeline=`directed `ScorePipeline`. The existing dedup/promote/win-short-circuit apply unchanged. The loop ends on a win, `next()→None` (Editor exhausted), or budget.

**Escalation** lives in `DirectedSource.observe`: K consecutive stalled directed scores flip patterns→LLM; the LLM tier has a hard per-run edit cap (token-cost control).

**Validity harness — three layers (the gate-3 fix; a silent VOID run must be impossible):**
1. **Per-candidate:** `score_directed`'s `INVALID` sentinel on empty roles / `case==NONE` / `diagnosis_chars==0`. The scheduler surfaces `INVALID` loudly and never counts it as control-equivalent.
2. **Per-run pre-flight:** before any search, run `analyze_iteration_full` once on the target and assert real roles + non-NONE case + `diagnosis_chars>0`. On failure, **abort loudly** — never start a search that can only emit `INVALID`s (the exact empty-`target.roles` failure that voided gate-3 pilot #1).
3. **Per-run gate telemetry:** `SearchResult` records per escalated candidate `{valid, diagnosis_chars, case, label, rank_delta}`. The **phase-1 gate passes iff** pre-flight passed AND escalated candidates have `diagnosis_chars>0 & case≠none` AND ≥1 real directed-progress signal (`MOVED_LATER` / role-order-rank improvement). This automates the gate-3 post-mortem rule rather than relying on a manual eyeball.

## 6. Phase plan

- **Phase 1 — Validated mechanism.** Build `DirectedSource` (deterministic tier only), `score_directed` + validity gates, `should_escalate`, the pcdump-capable backend extension, the validity harness. Wire into the substrate scheduler. Validate on 9ACC.
  **→ GATE (machine-checked):** pre-flight green AND treatment candidates `diagnosis_chars>0 & case≠none` AND ≥1 real directed-progress signal. If red, **stop and reassess** — do not build the LLM tier on a broken foundation.
- **Phase 2 — Capability + 100% attempt.** Add the LLM Editor tier + bounded patterns→LLM escalation. Run the full hybrid directed search on 9ACC for `byte_score==0`+checkdiff-clean. Deliverable: 9ACC cracked, or a characterized partial (directed score reached X; final edit eluded the LLM).

## 7. Testing

- `DirectedSource`: fake scorer feeds canned diagnoses → assert the right pattern per case; `observe` flips to LLM after K stalls; exhaustion → `None`. LLM tier tested with a fake LLM returning a canned edit.
- `score_directed`: **fixture pcdumps captured from 9ACC at known states** → assert scalar/label/diagnosis; assert `INVALID` on empty-roles / `case==NONE` / `diagnosis_chars==0` fixtures.
- **Gate-3 regression test:** a VOID-class input (empty `target.roles`) triggers pre-flight **ABORT**, not a silent control-equivalent run.
- Scheduler integration: directed source+scorer drop in with no engine change (litmus extended); a planted matching candidate reaches the win short-circuit.
- Phase-1 gate: passes on a valid-progress telemetry fixture, fails on a VOID telemetry fixture.

## 8. Out of scope (YAGNI)

- Pattern-library expansion beyond what 9ACC + the existing `coalesce_patterns` cover (extend as needed, don't pre-build).
- Multi-function batch directed search.
- Remote/distributed directed search — the local pcdump backend is the phase-1/2 vehicle; remote directed is a later concern.

## 9. Success criteria

- **Phase 1 (gate):** on 9ACC, machine-checked: pre-flight passes; escalated candidates have `diagnosis_chars>0 & case≠none`; ≥1 real directed-progress signal. The mechanism is provably non-VOID and genuinely diagnosing.
- **Phase 2:** `grIceMt_801F9ACC` reaches `match=true`/100%, OR a characterized partial that advances the directed score and isolates the residual the LLM couldn't close.
- **No regression:** the directed source + scorer integrate behind the existing seams with no change to the substrate engine (extended litmus stays green); all substrate tests stay green.
