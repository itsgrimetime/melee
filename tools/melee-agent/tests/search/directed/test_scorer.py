"""Tests for DirectedScorePipeline (Task 5)."""
import pytest
from dataclasses import replace
from src.search.directed.scorer import DirectedScorePipeline, ORDER_CHANGE_MUTATORS
from src.search.directed.contracts import DirectedScoringCall, DirectedObjective, DirectedSearchState
from src.search.types import SearchContext

# --- fakes ---
class _Fact:
    def __init__(self, case): self.case = case; self.ig_idx = 37
class _State:
    def __init__(self, case, identity=37, rank=2):
        self.fact = _Fact(case); self.identity = identity; self.role_order_rank = rank
class _Re:
    def __init__(self, matched): self.matched = matched
class _Dec:
    def __init__(self, iter_idx, assigned_reg=None):
        self.iter_idx = iter_idx
        self.assigned_reg = assigned_reg
class _Case:                      # mimic a DivergenceCase enum member
    def __init__(self, v): self.value = v

def _objective(roles_n=2, proof_force_phys=None):
    class _RT: pass
    rt = _RT(); rt.roles = [object()] * roles_n; rt.function = "grIceMt_801F9ACC"
    return DirectedObjective(search_target=None, role_target=rt, baseline_compile=None,
        baseline_pcdump_path=None, baseline_source_hash="h", class_id=0,
        objective_iter_by_original_ig={37: 3, 34: 103},
        proof_force_phys=proof_force_phys if proof_force_phys is not None else {})

def _force_phys_objective():
    class _RT: pass
    rt = _RT(); rt.roles = [object()] * 3; rt.function = "ftCo_8009E7B4"
    return DirectedObjective(search_target=None, role_target=rt, baseline_compile=None,
        baseline_pcdump_path=None, baseline_source_hash="h", class_id=0,
        objective_iter_by_original_ig={58: 1, 44: 2, 42: 3},
        proof_force_phys={58: 4, 44: 4, 42: 3})

def _parent(disp=0.3, last_lever=None):
    ps = DirectedSearchState(prev_state=None, history=(), last_lever=last_lever, current_best=None, state_id="p")
    object.__setattr__(ps, "displacement", disp)   # the per-state displacement accessor reads this
    return ps

def _art(tmp_path, text="CAND"):
    from src.search.artifact import CandidateArtifact, CompileSpec, Provenance
    from pathlib import Path
    blob = tmp_path / "b.c"; blob.write_text(text)
    dump = tmp_path / "d.txt"; dump.write_text("PC")
    spec = CompileSpec("t","cf","bc","tc","pcdump-local", Path("/m"))
    return CandidateArtifact("cid","sh",blob,spec,tmp_path/"o.o",None,None,None,dump,"",Provenance("d",None,None,"",{}),"ok")

def _pipe(case_value, matched={1:37,2:34}, decisions={1:_Dec(103),2:_Dec(3)}):
    return DirectedScorePipeline(
        analyze=lambda t,c,class_id=0:(_State(_Case(case_value)), object(), _Re(matched)),
        compile_from_text=lambda art: object(),
        decisions_of=lambda compile: decisions,
        classify=lambda prev,curr,**k: type("L",(),{"value":"SAME"})())

def test_invalid_on_enum_abstained(tmp_path):
    out = _pipe("abstained").score_directed(_art(tmp_path), DirectedScoringCall(_objective(), _parent()))
    assert out.status == "invalid" and out.directed_meta.valid is False and out.directed_meta.invalid_reason == "case_abstained"

def test_force_phys_assignment_fallback_scores_abstained_case(tmp_path):
    p = DirectedScorePipeline(
        analyze=lambda t,c,class_id=0:(
            _State(_Case("abstained")),
            object(),
            _Re({1: 58, 2: 44}),
        ),
        compile_from_text=lambda art: object(),
        decisions_of=lambda c:{1: _Dec(10, 4), 2: _Dec(20, 5)},
        classify=lambda prev,curr,**k: type("L",(),{"value":"SAME"})(),
    )
    art = replace(_art(tmp_path), byte_score=6)

    out = p.score_directed(
        art,
        DirectedScoringCall(_force_phys_objective(), _parent(disp=0.0)),
    )

    assert out.status == "ok"
    assert out.directed_score == pytest.approx(1 / 3)
    meta = out.directed_meta
    assert meta.valid is True
    assert meta.case == "force_phys_assignment"
    assert meta.label == "assignment_fallback"
    assert meta.proof_assignments["satisfied"] == [
        {
            "original_ig": 58,
            "new_ig": 1,
            "desired_phys": 4,
            "assigned_phys": 4,
        }
    ]
    assert meta.proof_assignments["blocked"] == [
        {
            "original_ig": 44,
            "new_ig": 2,
            "desired_phys": 4,
            "assigned_phys": 5,
        }
    ]
    assert meta.proof_assignments["abstained"] == [
        {
            "original_ig": 42,
            "new_ig": None,
            "desired_phys": 3,
            "assigned_phys": None,
            "reason": "not_reanchored",
        }
    ]
    assert meta.byte_score == 6
    assert meta.checkdiff_gate == "byte_mismatch"

def test_invalid_on_case_none(tmp_path):
    out = _pipe("none").score_directed(_art(tmp_path), DirectedScoringCall(_objective(), _parent()))
    assert out.directed_meta.invalid_reason == "case_none"

def test_invalid_on_no_roles(tmp_path):
    out = _pipe("B").score_directed(_art(tmp_path), DirectedScoringCall(_objective(roles_n=0), _parent()))
    assert out.directed_meta.invalid_reason == "no_roles"

def test_invalid_directed_meta_keeps_artifact_provenance(tmp_path):
    from src.search.artifact import Provenance

    art = replace(
        _art(tmp_path),
        candidate_id="flag_bool",
        source_hash="flag-bool-hash",
        provenance=Provenance(
            "seed-list",
            None,
            "flag_bool",
            "base",
            {"candidate_id_override": "flag_bool"},
        ),
    )

    out = _pipe("B", matched={}).score_directed(
        art,
        DirectedScoringCall(_objective(roles_n=2), _parent(last_lever=None)),
    )

    assert out.status == "invalid"
    assert out.directed_meta.invalid_reason == "low_coverage"
    assert out.directed_meta.candidate_id == "flag_bool"
    assert out.directed_meta.source_hash == "flag-bool-hash"
    assert out.directed_meta.applied_mutator == "flag_bool"

def test_valid_scores_and_is_pure(tmp_path):
    # GATE SIGNAL is phys-match; with empty proof there are no roles to satisfy,
    # so the phys-match gate signal is 0.0 / mismatch 0. The OLD iter-ordering
    # metric is demoted to the iter_* DIAGNOSTIC fields and is NEVER the gate
    # signal.
    call = DirectedScoringCall(_objective(), _parent(disp=0.0))
    p = _pipe("B")
    a = p.score_directed(_art(tmp_path), call); b = p.score_directed(_art(tmp_path), call)
    assert a.directed_meta.valid is True and a.status == "ok"
    # pure: same parent -> same (gate signal)
    assert a.directed_meta.order_distance == b.directed_meta.order_distance
    assert a.directed_meta.displacement == b.directed_meta.displacement
    # GATE SIGNAL fields (phys-match): empty proof -> 0.0 / 0
    assert a.directed_meta.displacement == 0.0
    assert a.directed_meta.order_distance == 0
    # DIAGNOSTIC ONLY: candidate iters {37:103,34:3} vs objective {37:3,34:103}
    # are inverted -> iter_order_distance 1 (telemetry, not the gate signal).
    assert a.directed_meta.iter_order_distance == 1
    assert a.directed_meta.displacement_delta == pytest.approx(a.directed_meta.displacement - 0.0)


def test_phys_match_is_the_gate_signal(tmp_path):
    # The directed gate signal measures phys-match: how many roles' assigned_reg
    # equals their desired_phys (proof_force_phys), mapped via reanchor.matched.
    # proof {37: 27, 34: 29}; reanchor {new1->37, new2->34}.
    proof_obj = lambda dec: DirectedScorePipeline(
        analyze=lambda t,c,class_id=0:(_State(_Case("B")), object(), _Re({1: 37, 2: 34})),
        compile_from_text=lambda art: object(),
        decisions_of=lambda compile: dec,
        classify=lambda prev,curr,**k: type("L",(),{"value":"SAME"})())
    call = DirectedScoringCall(
        _objective(proof_force_phys={37: 27, 34: 29}), _parent(disp=0.0))

    # 0/2: neither role at desired phys (the WALL — baseline scores 0.0).
    wall = proof_obj({1: _Dec(103, assigned_reg=29), 2: _Dec(3, assigned_reg=27)})
    m0 = wall.score_directed(_art(tmp_path), call).directed_meta
    assert m0.displacement == 0.0 and m0.order_distance == 2

    # 1/2: one role reached desired phys.
    half = proof_obj({1: _Dec(103, assigned_reg=27), 2: _Dec(3, assigned_reg=27)})
    m1 = half.score_directed(_art(tmp_path), call).directed_meta
    assert m1.displacement == pytest.approx(0.5) and m1.order_distance == 1

    # 2/2: both roles at desired phys (the phys-swap WIN).
    win = proof_obj({1: _Dec(103, assigned_reg=27), 2: _Dec(3, assigned_reg=29)})
    m2 = win.score_directed(_art(tmp_path), call).directed_meta
    assert m2.displacement == 1.0 and m2.order_distance == 0
    assert m2.proof_assignments["satisfied"] and not m2.proof_assignments["blocked"]

def test_edit_was_order_change_passed_from_last_lever(tmp_path):
    seen = {}
    p = DirectedScorePipeline(analyze=lambda t,c,class_id=0:(_State(_Case("B")),object(),_Re({1:37,2:34})),
        compile_from_text=lambda art: object(), decisions_of=lambda c:{1:_Dec(103),2:_Dec(3)},
        classify=lambda prev,curr,*,edit_was_order_change,history,checkdiff_clean: seen.update(eoc=edit_was_order_change) or type("L",(),{"value":"SAME"})())
    p.score_directed(_art(tmp_path), DirectedScoringCall(_objective(), _parent(last_lever="reorder_local_decls")))
    assert seen["eoc"] is True

def test_should_escalate_plateau():
    p = DirectedScorePipeline(analyze=None, compile_from_text=None, decisions_of=None, plateau_n=3)
    ctx = SearchContext(); ctx.byte_history = [5,5,5]
    assert p.should_escalate(None, ctx) is True       # no improvement in last 3 -> escalate
    ctx.byte_history = [7,6,5]
    assert p.should_escalate(None, ctx) is False      # still improving -> do NOT escalate
    ctx.byte_history = [5,5]
    assert p.should_escalate(None, ctx) is False      # < plateau_n -> no


def test_directed_from_start_always_escalates():
    # The explicit, documented replacement for the old _AlwaysEscalate hack:
    # a directed-only run scores directed from iteration 1 by design.
    p = DirectedScorePipeline(analyze=None, compile_from_text=None, decisions_of=None,
                              plateau_n=3, directed_from_start=True)
    ctx = SearchContext(); ctx.byte_history = []        # empty -> plateau would be False
    assert p.should_escalate(None, ctx) is True
    ctx.byte_history = [7, 6, 5]                          # improving -> plateau would be False
    assert p.should_escalate(None, ctx) is True          # but directed_from_start forces True
