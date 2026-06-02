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

def _objective(roles_n=2):
    class _RT: pass
    rt = _RT(); rt.roles = [object()] * roles_n; rt.function = "grIceMt_801F9ACC"
    return DirectedObjective(search_target=None, role_target=rt, baseline_compile=None,
        baseline_pcdump_path=None, baseline_source_hash="h", class_id=0,
        objective_iter_by_original_ig={37: 3, 34: 103}, proof_force_phys={})

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

def test_valid_scores_and_is_pure(tmp_path):
    call = DirectedScoringCall(_objective(), _parent(disp=0.3))
    p = _pipe("B")
    a = p.score_directed(_art(tmp_path), call); b = p.score_directed(_art(tmp_path), call)
    assert a.directed_meta.valid is True and a.status == "ok"
    assert a.directed_meta.order_distance == b.directed_meta.order_distance   # pure: same parent -> same
    # candidate iters {37:103,34:3} vs objective {37:3,34:103} -> inverted -> order_distance 1
    assert a.directed_meta.order_distance == 1
    assert a.directed_meta.displacement_delta == pytest.approx(a.directed_meta.displacement - 0.3)

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
