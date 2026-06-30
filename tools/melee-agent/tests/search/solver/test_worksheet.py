import json

from src.search.solver.worksheet import (
    Candidate, FilterSummary, PairEscalation, Worksheet, classify_confidence,
)


def test_classify_confidence_high_requires_full_vector_and_tier_a():
    assert classify_confidence(full_vector=True, has_tier_a_source_object=True) == "high"
    assert classify_confidence(full_vector=False, has_tier_a_source_object=True) == "proposal"
    assert classify_confidence(full_vector=True, has_tier_a_source_object=False) == "proposal"


def test_worksheet_serializes_exact_schema_keys():
    cand = Candidate(
        rank=1,
        perturbation={"kind": "node-add", "target_ig": 41, "use_set": [42]},
        predicted_assignment_delta={"42": [29, 27]},
        c_realizations=[{"lever": "alias", "source_object": "data_alias",
                         "confidence_tier": "a"}],
        surrogate_confidence="high",
        fidelity_gate="pending",
    )
    ws = Worksheet(
        function="mnDiagram_80241E78", class_id=0, g1_rate=1.0,
        force_phys_target={"42": 27}, reachable=True,
        filter_summary=FilterSummary(candidates_generated=12, rejected_a=1,
                                     rejected_b=1, flagged_c=0, rejected_survival=2),
        candidates=[cand], tooling_leads=[], window_order=[],
        pair_escalation=PairEscalation(ran=False, reason="actionable single exists",
                                       frontier_size=0, frontier=[], pair_hits=[]),
        enumeration_truncated=False,
        evals_per_kind={"node-add": 8, "edge": 2, "order": 2},
    )
    payload = json.loads(ws.to_json())
    assert set(payload) == {
        "function", "class_id", "g1_rate", "force_phys_target", "reachable",
        "filter_summary", "candidates", "tooling_leads", "window_order",
        "pair_escalation", "enumeration_truncated", "evals_per_kind",
    }
    assert set(payload["filter_summary"]) == {
        "candidates_generated", "rejected_a", "rejected_b", "flagged_c",
        "rejected_survival",
    }
    c = payload["candidates"][0]
    assert set(c) == {
        "rank", "perturbation", "predicted_assignment_delta", "c_realizations",
        "surrogate_confidence", "fidelity_gate",
    }
    assert c["surrogate_confidence"] in {"high", "proposal"}
    assert c["fidelity_gate"] == "pending"
    assert set(c["c_realizations"][0]) == {"lever", "source_object", "confidence_tier"}
    # pair_escalation: spec keys + the recorded pair_hits extension (Deviations).
    assert set(payload["pair_escalation"]) == {
        "ran", "reason", "frontier_size", "frontier", "pair_hits",
    }
    assert set(payload["evals_per_kind"]) == {"node-add", "edge", "order"}
