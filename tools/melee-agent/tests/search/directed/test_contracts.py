from dataclasses import replace
from src.search.directed.contracts import (
    DirectedObjective, DirectedSearchState, DirectedDiagnosis, DirectedMeta,
    DirectedScoringCall, DirectedSchedulerConfig,
)
from src.search.artifact import CandidateArtifact
from src.search.types import SearchContext, SearchResult


def _bare_artifact():
    from src.search.artifact import CompileSpec, Provenance
    from pathlib import Path
    spec = CompileSpec("t", "cf", "bc", "tc", "plain-local", Path("/m"))
    return CandidateArtifact("c1", "s1", Path("/b"), spec, None, None, None, None, None,
                             "", Provenance("n", None, None, "", {}), "ok")


def test_meta_linkage_and_artifact_invalid():
    m = DirectedMeta(candidate_id="c1", source_hash="s", iteration=2, parent_id="p",
        parent_state_id="ps", valid=True, invalid_reason=None, case="B", label="SAME",
        order_distance=1, displacement=0.5, displacement_delta=0.1, reanchor_matched=2,
        reanchor_total=2, diagnosis_chars=9, applied_mutator="reorder_local_decls",
        directed_scalar=0.5)
    a = replace(_bare_artifact(), status="invalid", directed_meta=m)
    assert a.status == "invalid" and a.directed_meta.parent_state_id == "ps"


def test_ctx_byte_history_and_result_telemetry():
    assert SearchContext().byte_history == [] and SearchResult().directed_telemetry == []


def test_scheduler_config_fields():
    cfg = DirectedSchedulerConfig(objective=None, score_pipeline=None, backend=None, plateau_n=3)
    assert cfg.plateau_n == 3


def test_scoring_call_carries_objective_and_parent():
    obj = DirectedObjective(search_target=None, role_target=None, baseline_compile=None,
        baseline_pcdump_path=None, baseline_source_hash="h", class_id=0,
        objective_iter_by_original_ig={37: 3, 34: 103}, proof_force_phys={37: 4, 34: 28})
    ps = DirectedSearchState(prev_state=None, history=(), last_lever=None, current_best=None, state_id="root")
    call = DirectedScoringCall(objective=obj, parent_state=ps)
    assert call.objective.class_id == 0 and call.parent_state.state_id == "root"
