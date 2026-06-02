# Directed Search Layer — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the validated directed-search *mechanism* (Phase 1 of the directed-layer spec) — a pcdump-guided tier-2 scorer + 9ACC-scoped typed-mutator source + scheduler directed-mode + a trustworthy validity harness — and run the machine-checked Phase-1 gate on `grIceMt_801F9ACC`.

**Architecture:** New package `tools/melee-agent/src/search/directed/` reuses the `mwcc_debug` convergence analysis as a library (never `run_convergence_loop`) and plugs into the existing substrate (`tools/melee-agent/src/search/`). Phase 2 (LLM Editor) is explicitly excluded.

**Tech Stack:** Python 3, pytest, the existing `mwcc_debug` analysis modules, the substrate's `CompileBackend`/`ScorePipeline`/`VariantSource`/`DefaultScheduler` seams, `mwcc` via `debug dump local`.

**Spec:** `docs/superpowers/specs/2026-06-01-directed-search-layer-design.md` (frozen after 3 Codex rounds). All work on branch `master` in `/Users/mike/code/melee`. NEVER `git add -A` (permuter scratch lives under `nonmatchings/`); stage explicit paths. Commits auto-push.

---

## Ground-truth API reference (verified against the code — use these EXACT shapes)

```python
# src/mwcc_debug/convergence.py:19
analyze_iteration_full(target, new_compile, class_id=0) -> (IterationState, FirstDivergenceReport | None, ReanchorResult)
# src/mwcc_debug/progress_classifier.py
IterationState(fact: FactView, identity: int|None, role_order_rank: int|None, gone_roles: frozenset)
FactView(case: DivergenceCase, ig_idx: int)
classify_progress(prev, curr, *, edit_was_order_change: bool, history: list, checkdiff_clean: bool) -> ProgressLabel
ProgressLabel: ASM_MATCHED|TARGET_SATISFIED|MOVED_LATER|NEW_EARLIER|NON_COMPARABLE|SAME|ROLE_GONE|CYCLE
# src/mwcc_debug/first_divergence.py
DivergenceCase: A_BLOCKED="A" B_TARGET_HIGHER="B" B_INVERSE="B-inverse" C_DISPENSE_ORDER="C" C2_STICKY_POOL="C2" D_COALESCED="D" E_SPILLED="E" ABSENT="absent" ABSTAINED="abstained" NONE="none"
AllocatorFact(class_id, ig_idx, case, iter_idx, baseline_reg, target_reg, coalesced_nodes, coalesced_root, coalesced_root_phys, blocker_ig, blocker_dependency, working_mask, cap_hit, earlier_unmapped_warning, local_target)
attach_source_ideas(fact: AllocatorFact, source_text: str, fn_name: str, pre_pass) -> SourceIdea
SourceIdea(ig_idx, var_name, confidence, alternates, ideas, rejected, first_def, blocker_ig, blocker_var_name, ...)
# src/mwcc_debug/role_reanchor.py:7,55
ReanchorResult(class_id, force_phys: dict, diagnostics: dict, matched: dict)   # matched = {new_ig: original_ig}
reanchor(target, new_compile, class_id=0) -> ReanchorResult
# src/mwcc_debug/role_descriptor.py
Compile(name, fev, fn, source, ir_facts);  Compile.from_text(pcdump_text, function, source) -> Compile
TargetSpec(function, target_kind, target_coverage, causal_closure, provenance, roles: list[TargetRoleSpec])  # mwcc_debug one
TargetRoleSpec(original_ig, desired_phys, class_id, descriptor, role_order_rank)
build_target_spec(c: Compile, force_phys: dict, class_id, target_kind, provenance, causal_closure=False) -> TargetSpec
# src/mwcc_debug/colorgraph_parser.py
parse_hook_events(text) -> list[FunctionEvents];  find_function(events, name) -> FunctionEvents|None
FunctionEvents(name, colorgraph_sections, ...);  ColorgraphSection(class_id, result, n_nodes, decisions: list[ColorgraphDecision])
ColorgraphDecision(iter_idx, ig_idx, assigned_reg, degree, n_interferers, flags, interferers)
# src/mwcc_debug/suggest_coalesce.py:70
run(function, *, pair=None, discover=False, top=3, include_low_confidence=False, pcdump_text, source_text="") -> Report
Suggestion(pattern_name, summary, ir_evidence, source_hint, catalog_ref)   # patterns: direct-identity|chain-init|alias-split|common-subexpr|ternary-collapse
# src/search/artifact.py
CandidateArtifact(candidate_id, source_hash, source_blob, compile_spec, object_path, producer_score, byte_score, directed_score, pcdump_path, compiler_stderr, provenance, status)  # status Literal — ADD "invalid"
# src/search/protocols.py
CompileBackend.compile(variant, *, want_pcdump=False) -> CandidateArtifact     # already takes want_pcdump
ScorePipeline.score_byte(art, target); .should_escalate(art, ctx) -> bool; .score_directed(art, objective) -> CandidateArtifact
VariantSource.name(); .seed(base); .next_batch(n) -> list[SourceVariant]; .observe(scored)
# src/search/types.py
SourceVariant(source_text, provenance);  SearchContext(iters_done=0, best_byte_score=None)  # ADD byte_history
SchedulePolicy(batch_size=16, promote_top_k=8, max_retries=2, route_pcdump_to_capable_only=True)
SearchResult(best, matched, accounting)   # ADD directed_telemetry
# pcdump compile: NO reusable lib fn. Shell: python -m src.cli debug dump local <c_file> --function <fn> --output <pcdump> --keep-obj <obj> --no-cache-sync
# class_id=0 (GPR) ONLY is supported by build_descriptors. 9ACC ev/did are GPRs → class_id=0.
```

---

## File structure

- `src/search/directed/__init__.py` — package marker.
- `src/search/directed/contracts.py` — `DirectedObjective`, `DirectedSearchState`, `DirectedDiagnosis`, `DirectedMeta`, `DirectedScoringCall` dataclasses.
- `src/search/directed/pcdump_backend.py` — `PcdumpLocalBackend` (`CompileBackend`).
- `src/search/directed/objective.py` — `build_directed_objective`, `preflight_objective`.
- `src/search/directed/metric.py` — reanchor mapping + `order_distance` + `displacement`.
- `src/search/directed/scorer.py` — `DirectedScorePipeline`.
- `src/search/directed/diagnosis.py` — `build_diagnosis`.
- `src/search/directed/anchors.py` — 9ACC-scoped source-anchor resolver.
- `src/search/directed/mutators.py` — typed mutators.
- `src/search/directed/source.py` — `DirectedSource` (`VariantSource`).
- `src/search/directed/gate.py` — `evaluate_phase1_gate`.
- Modify `src/search/artifact.py` (add `directed_meta`, `"invalid"`), `src/search/types.py` (add `SearchContext.byte_history`, `SearchResult.directed_telemetry`), `src/search/scheduler.py` (directed-mode path).
- Tests under `tests/search/directed/`.

Run all tests with: `cd /Users/mike/code/melee/tools/melee-agent && python -m pytest tests/search/ -q`

---

## STAGE P1.A — Compile/objective infrastructure

### Task 1: Directed contracts (dataclasses)

**Files:** Create `src/search/directed/__init__.py` (empty), `src/search/directed/contracts.py`; Test `tests/search/directed/__init__.py` (empty), `tests/search/directed/test_contracts.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/search/directed/test_contracts.py
from pathlib import Path
from src.search.directed.contracts import (
    DirectedObjective, DirectedSearchState, DirectedDiagnosis, DirectedMeta, DirectedScoringCall,
)

def test_directed_meta_is_fully_linkable():
    m = DirectedMeta(candidate_id="c1", source_hash="s1", iteration=2, parent_id="p1",
                     parent_state_id="ps1", valid=True, invalid_reason=None, case="B",
                     label="SAME", order_distance=1, displacement=0.5, displacement_delta=-0.1,
                     reanchor_matched=2, reanchor_total=2, diagnosis_chars=42,
                     applied_mutator="change_return_type_to_int", directed_scalar=0.5)
    assert m.candidate_id == "c1" and m.parent_state_id == "ps1" and m.order_distance == 1

def test_scoring_call_carries_objective_and_parent():
    obj = DirectedObjective(search_target=None, role_target=None, baseline_compile=None,
                            baseline_pcdump_path=Path("/x"), baseline_source_hash="h",
                            class_id=0, objective_iter_by_original_ig={37: 3, 34: 103})
    ps = DirectedSearchState(prev_state=None, history=(), last_lever=None,
                             current_best=None, state_id="root")
    call = DirectedScoringCall(objective=obj, parent_state=ps)
    assert call.objective.class_id == 0 and call.parent_state.state_id == "root"
```

- [ ] **Step 2: Run → FAIL** `python -m pytest tests/search/directed/test_contracts.py -q` (ModuleNotFoundError)

- [ ] **Step 3: Implement `contracts.py`**
```python
# src/search/directed/contracts.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class DirectedObjective:
    search_target: Any            # src.search.types.TargetSpec
    role_target: Any              # src.mwcc_debug.role_descriptor.TargetSpec
    baseline_compile: Any         # src.mwcc_debug.role_descriptor.Compile
    baseline_pcdump_path: Path
    baseline_source_hash: str
    class_id: int
    objective_iter_by_original_ig: dict   # {original_ig: iter_idx} from the proof/target compile

@dataclass(frozen=True)
class DirectedSearchState:
    prev_state: Any               # IterationState | None
    history: tuple
    last_lever: Any               # str | None  (the mutator/case applied to reach current_best)
    current_best: Any             # CandidateArtifact | None
    state_id: str

@dataclass(frozen=True)
class DirectedDiagnosis:
    case: str
    target_igs: tuple
    source_idea: Any              # SourceIdea | None
    coalesce_pair: tuple | None
    mutator_key: str | None
    resolved_anchor: Any          # Anchor | None (see anchors.py)
    analysis_valid: bool
    actionable: bool
    invalid_reason: str | None

@dataclass(frozen=True)
class DirectedMeta:
    candidate_id: str
    source_hash: str
    iteration: int
    parent_id: str | None
    parent_state_id: str
    valid: bool
    invalid_reason: str | None
    case: str
    label: str
    order_distance: int
    displacement: float
    displacement_delta: float
    reanchor_matched: int
    reanchor_total: int
    diagnosis_chars: int
    applied_mutator: str | None
    directed_scalar: float

@dataclass(frozen=True)
class DirectedScoringCall:
    """Passed as the `objective` arg to score_directed (keeps the 2-arg protocol)."""
    objective: DirectedObjective
    parent_state: DirectedSearchState
```

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit**
```bash
git add tools/melee-agent/src/search/directed/__init__.py tools/melee-agent/src/search/directed/contracts.py tools/melee-agent/tests/search/directed/__init__.py tools/melee-agent/tests/search/directed/test_contracts.py
git commit -m "feat(directed): contracts (objective/state/diagnosis/meta/scoring-call)"
```

### Task 2: `PcdumpLocalBackend` (compile → bound .o + pcdump)

**Files:** Create `src/search/directed/pcdump_backend.py`; Test `tests/search/directed/test_pcdump_backend.py`

Mirrors `RealLocalCompiler` (write TU `.c` → compile → restore, under the repo build lock) but shells to `debug dump local --keep-obj` so one invocation yields both the `.o` (for byte scoring) and the pcdump (for directed scoring). Reuse the lock helper `_acquire_repo_build_lock` from `src/search/adapters.py`.

- [ ] **Step 1: Write the failing test** (uses a fake runner so no real mwcc needed)
```python
# tests/search/directed/test_pcdump_backend.py
from pathlib import Path
from src.search.directed.pcdump_backend import PcdumpLocalBackend
from src.search.types import TargetSpec, SourceVariant, BackendCaps

def test_caps_report_pcdump(tmp_path):
    be = PcdumpLocalBackend(melee_root=tmp_path, unit="melee/gr/gricemt",
                            target=TargetSpec("grIceMt_801F9ACC", "melee/gr/gricemt", tmp_path/"e.o"),
                            store=_FakeStore(tmp_path), runner=lambda argv, **k: _ok(tmp_path))
    assert be.capabilities() == BackendCaps("local", 1, True)

def test_compile_binds_obj_and_pcdump(tmp_path):
    # fake runner writes both files where the CLI flags point, returns rc 0
    def runner(argv, **k):
        obj = Path(argv[argv.index("--keep-obj")+1]); obj.write_bytes(b"\x00"*4)
        dump = Path(argv[argv.index("--output")+1]); dump.write_text("PCDUMP")
        class R: returncode=0; stdout=""; stderr=""
        return R()
    (tmp_path/"src/melee/gr").mkdir(parents=True); (tmp_path/"src/melee/gr/gricemt.c").write_text("orig")
    be = PcdumpLocalBackend(melee_root=tmp_path, unit="melee/gr/gricemt",
                            target=TargetSpec("grIceMt_801F9ACC","melee/gr/gricemt",tmp_path/"e.o"),
                            store=_FakeStore(tmp_path), runner=runner)
    art = be.compile(SourceVariant("CANDIDATE", None), want_pcdump=True)
    assert art.object_path and art.object_path.exists()
    assert art.pcdump_path and art.pcdump_path.read_text() == "PCDUMP"
    assert (tmp_path/"src/melee/gr/gricemt.c").read_text() == "orig"   # restored
    assert art.status == "ok"
```
(Define `_FakeStore` with `put_source(text)->Path` writing a temp file, and `_ok` returning an rc-0 object.)

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `PcdumpLocalBackend`** — write candidate to `src/<unit>.c`, run `[sys.executable, "-m", "src.cli", "debug", "dump", "local", str(tu_c), "--function", fn, "--output", str(pcdump_tmp), "--keep-obj", str(obj_tmp), "--no-cache-sync"]` via the injected `runner` (default `subprocess.run`) under `_acquire_repo_build_lock`, restore the `.c` (and any pre-existing `.o`) in a `finally`, copy obj+pcdump into the store via `mkstemp`, return a `CandidateArtifact` (compute `candidate_id` from a spec factory; `status="ok"` iff both files exist else `"compile_failed"`). `capabilities()` → `BackendCaps("local", 1, True)`.

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit** `feat(directed): PcdumpLocalBackend (one-invocation .o + pcdump)`

### Task 3: `DirectedObjective` builder + pre-flight

**Files:** Create `src/search/directed/objective.py`; Test `tests/search/directed/test_objective.py`

- [ ] **Step 1: Write the failing test** (fixtures, no live compile)
```python
# tests/search/directed/test_objective.py
import pytest
from src.search.directed.objective import build_directed_objective, preflight_objective, PreflightError

def test_preflight_aborts_on_empty_roles(monkeypatch):
    # role_target with no roles must abort loudly (gate-3 pilot #1 failure)
    obj = _objective_with_roles([])
    with pytest.raises(PreflightError):
        preflight_objective(obj)

def test_preflight_aborts_on_case_none(monkeypatch):
    obj = _objective_with_roles([_role(37)])
    monkeypatch.setattr("src.search.directed.objective.analyze_iteration_full",
                        lambda t, c, class_id=0: (_state(case="none"), None, _reanchor({})))
    with pytest.raises(PreflightError):
        preflight_objective(obj)

def test_preflight_passes_on_valid(monkeypatch):
    obj = _objective_with_roles([_role(37), _role(34)])
    monkeypatch.setattr("src.search.directed.objective.analyze_iteration_full",
                        lambda t, c, class_id=0: (_state(case="B"), _report(), _reanchor({1:37,2:34})))
    preflight_objective(obj)   # no raise
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** `build_directed_objective(melee_root, search_target, function, unit, class_id=0)`: compile the baseline (current repo TU) via `PcdumpLocalBackend`-style `debug dump local` to get `baseline_pcdump_path`; `Compile.from_text(pcdump_text, function, source)`; derive `force_phys` for the proof target and `role_target = build_target_spec(c, force_phys, class_id, "force_proof_proxy", provenance)`; compute `objective_iter_by_original_ig` from the target compile's colorgraph decisions keyed by each role's `original_ig`; return `DirectedObjective`. `preflight_objective(obj)`: run `analyze_iteration_full(obj.role_target, obj.baseline_compile, obj.class_id)`; raise `PreflightError` unless `obj.role_target.roles` non-empty AND `state.fact.case not in {"none","abstained"}` AND `report is not None`.

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit** `feat(directed): DirectedObjective builder + loud pre-flight`

---

## STAGE P1.B — Metric + scorer

### Task 4: Ordering metric (binary `order_distance` + smooth `displacement`)

**Files:** Create `src/search/directed/metric.py`; Test `tests/search/directed/test_metric.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/search/directed/test_metric.py
from src.search.directed.metric import candidate_iter_by_original_ig, order_distance, displacement

def test_reanchor_mapping():
    # matched = {new_ig: original_ig}; decisions keyed by new_ig give iter positions
    matched = {1: 37, 2: 34}
    decisions = {1: _dec(iter_idx=103), 2: _dec(iter_idx=3)}
    assert candidate_iter_by_original_ig(matched, decisions) == {37: 103, 34: 3}

def test_order_distance_binary_for_two_roles():
    # objective wants 37 before 34 (objective iters: 37@3, 34@103)
    objective = {37: 3, 34: 103}
    # candidate has them flipped (37@103, 34@3) -> 1 inversion
    assert order_distance({37: 103, 34: 3}, objective) == 1
    # candidate in objective order -> 0 inversions (the flip achieved)
    assert order_distance({37: 3, 34: 103}, objective) == 0

def test_displacement_moves_before_flip():
    objective = {37: 3, 34: 103}   # want 37 earlier than 34 (gap +100 in objective)
    far = displacement({37: 103, 34: 3}, objective)     # fully inverted
    near = displacement({37: 50, 34: 60}, objective)    # same (wrong) order but closer iters
    assert near > far    # displacement increases as the pair's signed gap approaches objective
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement**
```python
# src/search/directed/metric.py — concrete, no external deps
from itertools import combinations

def candidate_iter_by_original_ig(matched: dict, decisions_by_new_ig: dict) -> dict:
    out = {}
    for new_ig, orig_ig in matched.items():
        d = decisions_by_new_ig.get(new_ig)
        if d is not None:
            out[orig_ig] = d.iter_idx
    return out

def order_distance(cand_iter_by_ig: dict, objective_iter_by_ig: dict) -> int:
    igs = [ig for ig in objective_iter_by_ig if ig in cand_iter_by_ig]
    inv = 0
    for a, b in combinations(igs, 2):
        obj_order = objective_iter_by_ig[a] < objective_iter_by_ig[b]
        cand_order = cand_iter_by_ig[a] < cand_iter_by_ig[b]
        if obj_order != cand_order:
            inv += 1
    return inv

def displacement(cand_iter_by_ig: dict, objective_iter_by_ig: dict) -> float:
    """Heuristic smooth signal: mean cosine-like closeness of each role pair's signed
    iter-gap to the objective's signed gap. NOT guaranteed monotone toward the flip."""
    igs = [ig for ig in objective_iter_by_ig if ig in cand_iter_by_ig]
    if len(igs) < 2:
        return 0.0
    score, n = 0.0, 0
    for a, b in combinations(igs, 2):
        og = objective_iter_by_ig[a] - objective_iter_by_ig[b]
        cg = cand_iter_by_ig[a] - cand_iter_by_ig[b]
        denom = (abs(og) + abs(cg)) or 1
        score += 1.0 - abs(og - cg) / denom    # 1.0 when gaps match, →0 when opposite
        n += 1
    return score / n
```
(`_dec` in the test is a tiny stub with an `iter_idx` attribute.)

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit** `feat(directed): ordering metric (binary order_distance + smooth displacement)`

### Task 5: `DirectedScorePipeline` (pure score_directed + validity + should_escalate)

**Files:** Create `src/search/directed/scorer.py`; Test `tests/search/directed/test_scorer.py`

- [ ] **Step 1: Write the failing test** (inject a fake analyzer so no live pcdump)
```python
# tests/search/directed/test_scorer.py
from src.search.directed.scorer import DirectedScorePipeline
from src.search.directed.contracts import DirectedScoringCall
from src.search.types import SearchContext

def test_invalid_on_case_abstained(make_call, make_art):
    pipe = DirectedScorePipeline(analyze=lambda t,c,class_id=0:(_state(case="abstained"),_rep(),_re({1:37})),
                                 compile_from_text=lambda art:_compile(), decisions_of=lambda c:{1:_dec(3)})
    out = pipe.score_directed(make_art(pcdump="X"), make_call())
    assert out.directed_meta.valid is False and out.directed_meta.invalid_reason == "case_abstained"
    assert out.status == "invalid"

def test_valid_scores_and_is_pure(make_call, make_art):
    pipe = DirectedScorePipeline(analyze=lambda t,c,class_id=0:(_state(case="B",identity=37,rank=2),_rep(),_re({1:37,2:34})),
                                 compile_from_text=lambda art:_compile(), decisions_of=lambda c:{1:_dec(103),2:_dec(3)})
    a = pipe.score_directed(make_art(pcdump="X"), make_call())   # parent state P
    b = pipe.score_directed(make_art(pcdump="X"), make_call())   # same parent -> identical
    assert a.directed_meta.order_distance == b.directed_meta.order_distance
    assert a.directed_meta.valid is True

def test_should_escalate_on_byte_plateau():
    pipe = DirectedScorePipeline(analyze=None, compile_from_text=None, decisions_of=None, plateau_n=3)
    ctx = SearchContext(); ctx.byte_history = [5,5,5]    # field added in Task 6
    assert pipe.should_escalate(None, ctx) is True
    ctx.byte_history = [7,6,5]
    assert pipe.should_escalate(None, ctx) is False
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `DirectedScorePipeline`** with injected seams (`analyze` = `analyze_iteration_full`, `compile_from_text` = `Compile.from_text` adapter, `decisions_of` = colorgraph decisions keyed by new_ig). `score_directed(art, call)`:
  1. `compile = compile_from_text(art)` (reads `art.pcdump_path`).
  2. `state, report, reanchor = analyze(call.objective.role_target, compile, call.objective.class_id)`.
  3. **Validity:** invalid (return `replace(art, status="invalid", directed_meta=DirectedMeta(valid=False, invalid_reason=...))`) if `not role_target.roles` → `no_roles`; `state.fact.case in {"none"}` → `case_none`; `state.fact.case in {"abstained"}` → `case_abstained`; `report is None` → `no_report`; coverage `len(reanchor.matched)/len(roles) < floor (0.5)` → `low_coverage`.
  4. **Metric:** `cand = candidate_iter_by_original_ig(reanchor.matched, decisions_of(compile))`; `od = order_distance(cand, call.objective.objective_iter_by_original_ig)`; `disp = displacement(...)`; `label = classify_progress(call.parent_state.prev_state, state, edit_was_order_change=..., history=list(call.parent_state.history), checkdiff_clean=False).value`.
  5. Build `DirectedMeta` (`directed_scalar = disp`); return `replace(art, directed_score=disp, directed_meta=meta, status="ok")`. **No global mutation.**
  `should_escalate(art, ctx)`: `len(ctx.byte_history) >= plateau_n and len(set(ctx.byte_history[-plateau_n:])) == 1` (no improvement over last N).

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit** `feat(directed): DirectedScorePipeline (pure, validity-gated, displacement scalar)`

---

## STAGE P1.C — Scheduler directed-mode + contract additions

### Task 6: Artifact/types contract additions

**Files:** Modify `src/search/artifact.py`, `src/search/types.py`; Test `tests/search/directed/test_contract_additions.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/search/directed/test_contract_additions.py
from dataclasses import replace
from src.search.artifact import CandidateArtifact
from src.search.types import SearchContext, SearchResult

def test_candidate_artifact_has_directed_meta_and_invalid_status():
    a = _bare_artifact()  # build a minimal CandidateArtifact
    a2 = replace(a, status="invalid", directed_meta=None)
    assert a2.status == "invalid" and a2.directed_meta is None

def test_searchcontext_byte_history_and_result_telemetry():
    ctx = SearchContext(); assert ctx.byte_history == []
    r = SearchResult(); assert r.directed_telemetry == []
```

- [ ] **Step 2: Run → FAIL** (TypeError: unexpected keyword `directed_meta` / no attribute `byte_history`)

- [ ] **Step 3: Implement** — add `directed_meta: DirectedMeta | None = None` field to `CandidateArtifact` (import under `TYPE_CHECKING` or use `Any` to avoid a cycle; the frozen dataclass needs a default so add it LAST), extend the `status` `Literal` with `"invalid"`; add `byte_history: list = field(default_factory=list)` to `SearchContext`; add `directed_telemetry: list = field(default_factory=list)` to `SearchResult`. Verify the existing 29 substrate tests still pass.

- [ ] **Step 4: Run → PASS** + `python -m pytest tests/search/ -q` (all green)

- [ ] **Step 5: Commit** `feat(directed): artifact directed_meta/"invalid" + ctx byte_history + result telemetry`

### Task 7: Scheduler directed-mode

**Files:** Modify `src/search/scheduler.py`; Test `tests/search/directed/test_scheduler_directed.py`

The directed path is added to `DefaultScheduler` guarded by an injected `directed` config (`{objective, score_pipeline, plateau_n}`); when absent, behavior is byte-for-byte the existing Tier-1 loop (keeps the 29 tests green).

- [ ] **Step 1: Write the failing test** (all fakes — no mwcc)
```python
# tests/search/directed/test_scheduler_directed.py
def test_directed_escalation_routes_pcdump_and_scores_per_parent(fakes):
    # byte-history plateaus -> next batch compiled want_pcdump=True via the pcdump backend;
    # score_directed called per candidate with the SAME parent; one best selected; telemetry recorded.
    result = run_directed_scheduler(fakes)
    assert fakes.pcdump_backend.compiled_with_pcdump        # routed
    assert all(c.parent_state_id == fakes.root_state_id for c in result.directed_telemetry)  # per-parent
    assert len(result.directed_telemetry) >= 1

def test_invalid_candidate_surfaced_not_progress(fakes_invalid):
    result = run_directed_scheduler(fakes_invalid)
    assert any(m.valid is False for m in result.directed_telemetry)
    assert result.accounting.get("directed_invalid", 0) >= 1
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** — in `run(...)`, accept an optional `directed=None` kwarg. Maintain `ctx.byte_history` (append each accepted `byte_score`). Before each batch, if `directed` and `directed.score_pipeline.should_escalate(None, ctx)` → set `want = True` and route compiles to `directed.backend` (pcdump-capable) else the normal backend; compile with `backend.compile(variant, want_pcdump=want)`. After `score_byte`, if escalated, call `directed.score_pipeline.score_directed(art, DirectedScoringCall(directed.objective, parent_state))`; append `art.directed_meta` to `directed_telemetry`; if `art.directed_meta and not art.directed_meta.valid` → `acct["directed_invalid"] += 1` (do NOT treat as progress); else keep for best-selection. After the batch, **select one best** (lowest byte, tie-break highest `displacement`) and call `src.observe([best])`; advance the directed state via the source. Return `SearchResult(..., directed_telemetry=directed_telemetry)`. Keep dedup keyed on `(candidate_id, parent_state_id)` in directed mode.

- [ ] **Step 4: Run → PASS** + full substrate suite green.

- [ ] **Step 5: Commit** `feat(directed): scheduler directed-mode (escalate, pcdump-route, per-parent score, select-best, telemetry)`

---

## STAGE P1.D — Diagnosis + resolver + mutators (9ACC-scoped)

### Task 8: `build_diagnosis`

**Files:** Create `src/search/directed/diagnosis.py`; Test `tests/search/directed/test_diagnosis.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/search/directed/test_diagnosis.py
from src.search.directed.diagnosis import build_diagnosis

def test_diagnosis_splits_analysis_valid_from_actionable(fake_inputs):
    # valid analysis (case B, roles) but no resolvable anchor -> analysis_valid True, actionable False
    d = build_diagnosis(state=_state(case="B"), report=_rep_with_idea(), reanchor=_re({1:37}),
                        source_text="...", function="grIceMt_801F9ACC", resolve=lambda idea, src: None)
    assert d.analysis_valid is True and d.actionable is False and d.mutator_key is None

def test_diagnosis_actionable_when_anchor_resolves(fake_inputs):
    d = build_diagnosis(state=_state(case="B"), report=_rep_with_idea(), reanchor=_re({1:37}),
                        source_text="...", function="grIceMt_801F9ACC",
                        resolve=lambda idea, src: _anchor(mutator_key="change_return_type_to_int"))
    assert d.analysis_valid is True and d.actionable is True and d.mutator_key == "change_return_type_to_int"
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** — `build_diagnosis(state, report, reanchor, source_text, function, resolve)`: `case = state.fact.case` (str via `.value` if enum); `analysis_valid = bool(reanchor.matched) and case not in {"none","abstained"} and report is not None`; obtain the `SourceIdea` via `report.source` or `attach_source_ideas(report.fact, source_text, function, pre_pass=None)`; `anchor = resolve(source_idea, source_text)`; `actionable = anchor is not None`; `mutator_key = anchor.mutator_key if anchor else None`; return `DirectedDiagnosis(case, target_igs, source_idea, coalesce_pair, mutator_key, anchor, analysis_valid, actionable, invalid_reason)`. The `resolve` callable is `anchors.resolve_anchor` (Task 9), injected for testability.

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit** `feat(directed): build_diagnosis (analysis_valid vs actionable split)`

### Task 9: 9ACC-scoped source-anchor resolver

**Files:** Create `src/search/directed/anchors.py`; Test `tests/search/directed/test_anchors.py`

Scoped to 9ACC's three known levers. An `Anchor` = `{mutator_key, span(start,end), payload}`. The resolver matches the diagnosis's `var_name`/`first_def` against the candidate source to locate the exact span. **Out of scope:** any generalization beyond these patterns.

- [ ] **Step 1: Write the failing test** (real gricemt-shaped source snippets)
```python
# tests/search/directed/test_anchors.py
from src.search.directed.anchors import resolve_anchor

SRC = ("int grIceMt_801F9ACC(Ground_GObj* gobj, float y, GrIceMtSegmentLookup ev,\n"
       "                     Ground_GObj* arg3)\n{\n    s32 did = 0;\n    gp = Ground_801C2BA4(id)->user_data;\n}\n")

def test_resolves_return_type_anchor():
    idea = _idea(var_name="did", first_def="s32 did = 0;")
    a = resolve_anchor(idea, SRC)
    assert a is not None and a.mutator_key in {"change_return_type_to_int","introduce_indirection_local","wrap_field_access_in_accessor"}

def test_unresolvable_returns_none():
    idea = _idea(var_name="not_present", first_def="nope")
    assert resolve_anchor(idea, SRC) is None
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** `resolve_anchor(source_idea, source_text) -> Anchor | None`: dataclass `Anchor(mutator_key, span, payload)`. Use targeted regex/string search keyed on the idea's `var_name`/`first_def` to locate spans for the three 9ACC levers: (a) `->user_data` reads → `wrap_field_access_in_accessor`; (b) a `gp->gv.icemt2.xC8` access usable as a hoisted indirection local → `introduce_indirection_local`; (c) the `void`/`int` return signature + `s32 <flag> = 0;` → `change_return_type_to_int`. Return the first lever whose span resolves, else `None`. Keep each matcher small and exact; never return a span that doesn't string-match the source.

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit** `feat(directed): 9ACC-scoped source-anchor resolver`

### Task 10: Typed mutators

**Files:** Create `src/search/directed/mutators.py`; Test `tests/search/directed/test_mutators.py`

- [ ] **Step 1: Write the failing test** (golden: exact patched source)
```python
# tests/search/directed/test_mutators.py
from src.search.directed.mutators import apply_mutator

def test_change_return_type_to_int_is_exact():
    src = "void grIceMt_801F9ACC(Ground_GObj* gobj)\n{\n    s32 did = 0;\n    return;\n}\n"
    anchor = _anchor("change_return_type_to_int", payload={"flag":"did"})
    out = apply_mutator("change_return_type_to_int", anchor, src)
    assert out.startswith("int grIceMt_801F9ACC(") and "return did;" in out and "return 0;" in out

def test_unresolvable_mutator_returns_none():
    assert apply_mutator("change_return_type_to_int", _anchor("change_return_type_to_int", payload={"flag":"missing"}), "x") is None
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** `apply_mutator(key, anchor, source_text) -> str | None`: a dispatch over the three mutators, each performing an exact, anchor-bounded string transform: `change_return_type_to_int` (void→int sig + `return;`→`return 0;` early + `return <flag>;` before the final `}`), `wrap_field_access_in_accessor` (`<expr>->user_data` → `grIceMt_GetUserData(<expr>)`), `introduce_indirection_local` (hoist `&gp->gv.icemt2.xC8` into a `new_var` declared before the branch + replace uses with `new_var`). Return `None` if the anchor's payload doesn't string-match (never emit broken source).

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit** `feat(directed): 9ACC typed mutators (golden-tested)`

### Task 11: `DirectedSource`

**Files:** Create `src/search/directed/source.py`; Test `tests/search/directed/test_source.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/search/directed/test_source.py
from src.search.directed.source import DirectedSource

def test_next_batch_applies_untried_mutators_then_exhausts(fake_diag):
    src = DirectedSource(diagnose=lambda best: fake_diag, mutators=["change_return_type_to_int"],
                         apply=lambda k,a,s: s+f"/*{k}*/")
    src.seed(_spec(base="BASE"))
    b1 = src.next_batch(8); assert len(b1) == 1 and b1[0].source_text.endswith("/*change_return_type_to_int*/")
    b2 = src.next_batch(8); assert b2 == []     # exhausted (only mutator already tried)

def test_observe_advances_best_and_counts_stalls(fake_diag):
    src = DirectedSource(diagnose=lambda best: fake_diag, mutators=["m1","m2"], apply=lambda k,a,s:s)
    src.seed(_spec(base="BASE"))
    src.observe([_scored(displacement=0.4)]); src.observe([_scored(displacement=0.4)])
    assert src.stalls >= 1   # no displacement improvement -> stall
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** `DirectedSource` (`VariantSource`): `seed(base)` stores `current_best=base.base_source`; `next_batch(n)` builds the current `DirectedDiagnosis` via injected `diagnose(current_best)`, picks up to `n` untried mutators whose `resolved_anchor` matches, `apply`s each → `SourceVariant`s (provenance records `parent_id`+`mutation=mutator_key`); `[]` when none left. `observe(scored)`: pick the best by `(byte_score, displacement)`; if its `displacement` did not improve over the last best → `self.stalls += 1` else reset + update `current_best`; expose `self.stalls` for the scheduler's escalation. (LLM escalation itself is Phase 2.)

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit** `feat(directed): DirectedSource (mutator vending + stall tracking)`

---

## STAGE P1.E — End-to-end + the Phase-1 gate

### Task 12: `evaluate_phase1_gate`

**Files:** Create `src/search/directed/gate.py`; Test `tests/search/directed/test_gate.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/search/directed/test_gate.py
from src.search.directed.gate import evaluate_phase1_gate, GateVerdict

def test_gate_passes_on_attributable_displacement():
    tele = [_meta(valid=True, case="B", applied_mutator="change_return_type_to_int",
                  displacement_delta=0.2, order_distance=1)]
    v = evaluate_phase1_gate(preflight_ok=True, telemetry=tele, byte_regressed=False, coverage_ok=True,
                             control_displacement=0.0)
    assert v.passed is True

def test_gate_fails_void_and_unattributed():
    assert evaluate_phase1_gate(True, [], False, True, 0.0).passed is False          # VOID (no telemetry)
    bad = [_meta(valid=True, case="B", applied_mutator=None, displacement_delta=0.2)]  # unattributed
    assert evaluate_phase1_gate(True, bad, False, True, 0.0).passed is False

def test_gate_records_no_gradient_finding():
    flat = [_meta(valid=True, case="B", applied_mutator="m", displacement_delta=0.0)]
    v = evaluate_phase1_gate(True, flat, False, True, 0.0)
    assert v.passed is False and v.reason == "no_smooth_gradient"
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** `evaluate_phase1_gate(preflight_ok, telemetry, byte_regressed, coverage_ok, control_displacement) -> GateVerdict(passed, reason, evidence)`: fail `not_preflight` if `not preflight_ok`; fail `void_no_treatment` if no `valid` treatment metas; the pass requires ≥1 meta with `valid and case not in {"none","abstained"} and applied_mutator and displacement_delta > 0 and not byte_regressed and coverage_ok and displacement > control_displacement`; if treatment is valid+attributed but all `displacement_delta <= 0` → fail with reason `"no_smooth_gradient"` (the honest transposition outcome that routes to Phase 2), else `"unattributed_or_regressing"`.

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit** `feat(directed): phase-1 gate (attributable displacement; honest no-gradient verdict)`

### Task 13: End-to-end CLI + 9ACC run

**Files:** Create `src/search/directed/run.py` (wires objective→backend→source→scorer→scheduler→gate) + register `debug search directed` in `src/cli/debug.py`; Test `tests/search/directed/test_run_smoke.py`

- [ ] **Step 1: Write the failing test** (dry, fully faked — no mwcc/live)
```python
# tests/search/directed/test_run_smoke.py
def test_directed_run_dry_assembles_and_runs(monkeypatch, tmp_path):
    from src.search.directed.run import run_directed
    res = run_directed(function="grIceMt_801F9ACC", unit="melee/gr/gricemt",
                       melee_root=tmp_path, store_dir=tmp_path/"store", dry=True)
    assert "gate" in res and "directed_telemetry" in res
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** `run_directed(...)`: build the `DirectedObjective` (or a dry stub when `dry=True`), `preflight_objective`, assemble `PcdumpLocalBackend` + `DirectedScorePipeline` + `DirectedSource` + `DefaultScheduler(directed=...)`, run, then `evaluate_phase1_gate(...)` from `result.directed_telemetry`; return `{gate, directed_telemetry, accounting}`. Register a Typer command `debug search directed --function --unit [--dry]` that calls it and prints JSON. Keep `--dry` independent of mwcc.

- [ ] **Step 4: Run → PASS** + full suite green.

- [ ] **Step 5: Commit** `feat(directed): debug search directed run + e2e assembly`

- [ ] **Step 6: LIVE 9ACC run (manual, records the gate result)** — `cd /Users/mike/code/melee && melee-agent debug search directed --function grIceMt_801F9ACC --unit melee/gr/gricemt` and record the gate verdict (`passed` / `no_smooth_gradient` / mechanism evidence) in the commit message. This is the Phase-1 gate evaluation; its outcome decides whether to write the Phase-2 (LLM) plan or reassess.

---

## Self-Review (run before handoff)

**Spec coverage:** P1.A (PcdumpLocalBackend §5.3, DirectedObjective+pre-flight §4/§6.2) → Tasks 2,3; P1.B (metric §5.2, scorer §5.2) → Tasks 4,5; P1.C (contracts §4, scheduler refactor §6.1) → Tasks 6,7; P1.D (diagnosis §5.1, resolver §5.1, mutators §5.1, DirectedSource §5.1) → Tasks 8–11; P1.E (gate §6.2.3, e2e §7) → Tasks 12,13. Contracts (Task 1) underpin all. ✓

**Placeholder scan:** every code step shows concrete code; the only injected seams (`analyze`/`compile_from_text`/`decisions_of`/`resolve`/`apply`/`runner`/`diagnose`) are real-function adapters made injectable for TDD, named consistently across tasks. No TBD/TODO.

**Type consistency:** `DirectedObjective`/`DirectedSearchState`/`DirectedDiagnosis`/`DirectedMeta`/`DirectedScoringCall` fields (Task 1) are used identically in Tasks 3,5,7,8,12; `score_directed(art, call)` (call = `DirectedScoringCall`) is consistent; `Anchor(mutator_key, span, payload)` (Task 9) is consumed by Task 10's `apply_mutator`; `byte_history`/`directed_telemetry`/`"invalid"`/`directed_meta` (Task 6) are used by Tasks 5,7,12.

**Out of scope (per spec §9):** no `LlmEditorProducer`, no dynamic producer start/stop, no generalized resolver — Phase 2.
