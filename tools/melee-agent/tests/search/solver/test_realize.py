from src.search.solver.enumerate import EnumResult
from src.search.solver.realize import (
    CRealization, assemble_realized, lever_priority_rank, load_catalog,
    realize_perturbation,
)
from src.search.solver.types import Perturbation, PerturbationKind


_CATALOG = {
    "node-add": [
        {"lever": "alias", "tier": "a", "note": "T* a = x;"},
        {"lever": "temp-for-expr", "tier": "a", "note": "T t = expr;"},
    ],
    "edge-add": [{"lever": "statement-hoist-sink", "tier": "b", "note": "..."}],
    "edge-remove": [{"lever": "statement-hoist-sink", "tier": "b", "note": "..."}],
    "order": [{"lever": "decl-reorder", "tier": "c", "note": "census caveat"}],
}


def _node_add(target=41, new_ig=99):
    return Perturbation(PerturbationKind.NODE_ADD, target_ig=target,
                        use_set=(42,), new_ig=new_ig, position="after",
                        interfere_original=True)


def test_load_catalog_from_inline_dict_and_dir(tmp_path):
    assert load_catalog(_CATALOG)["node-add"][0]["lever"] == "alias"
    import json
    (tmp_path / "node-add.json").write_text(json.dumps(_CATALOG["node-add"]))
    cat = load_catalog(tmp_path)
    assert cat["node-add"][0]["lever"] == "alias"


def test_realize_orders_by_priority_and_carries_source_object():
    reals = realize_perturbation(_node_add(), _CATALOG, source_object="data_alias")
    assert reals and reals[0].lever == "alias" and reals[0].confidence_tier == "a"
    assert reals[0].source_object == "data_alias"


def test_no_source_object_yields_empty_realizations():
    assert realize_perturbation(_node_add(), _CATALOG, source_object=None) == []


def test_lever_priority_node_set_over_edge_over_order():
    a = CRealization("alias", "a", "obj")
    b = CRealization("statement-hoist-sink", "b", "obj")
    c = CRealization("decl-reorder", "c", "obj")
    assert [r.confidence_tier for r in sorted([c, b, a], key=lever_priority_rank)] \
        == ["a", "b", "c"]


# ---- assemble_realized (codex major 10) ----

def _enum_out(full_hits, window_hits=(), pair_hits=(), pair_ran=False):
    single = EnumResult(
        full_hits=list(full_hits), partial_hits=[],
        window_order_hits=list(window_hits),
        filter_counts={"candidates_generated": 10, "rejected_a": 2,
                       "rejected_b": 1, "flagged_c": len(window_hits),
                       "rejected_survival": 1},
        evals_per_kind={"node-add": 6, "edge": 2, "order": 2},
        truncated=False, last_kind="order")
    pe = {"ran": pair_ran, "reason": "no actionable single" if pair_ran
          else "actionable single exists", "frontier_size": 0, "frontier": [],
          "pair_hits": list(pair_hits), "pair_evals": len(pair_hits),
          "truncated": False}
    return {"single": single, "pair_escalation": pe}


def test_assemble_routes_no_source_hits_to_tooling_leads():
    hit = {"perturbation": _node_add(target=50), "targets_met": 1,
           "delta": {"50": [22, 21]}, "actionable": False}
    bundle = assemble_realized(
        _enum_out([hit]), phys_target={50: 21}, catalog=_CATALOG,
        source_lookup=lambda ig_idx: None)
    assert bundle.candidates == []
    assert len(bundle.tooling_leads) == 1
    assert bundle.tooling_leads[0]["perturbation"]["target_ig"] == 50


def test_assemble_builds_high_confidence_candidate():
    hit = {"perturbation": _node_add(target=41), "targets_met": 1,
           "delta": {"41": [30, 27]}, "actionable": False}
    bundle = assemble_realized(
        _enum_out([hit]), phys_target={41: 27}, catalog=_CATALOG,
        source_lookup=lambda ig_idx: "data_alias")
    assert len(bundle.candidates) == 1
    c = bundle.candidates[0]
    assert c["rank"] == 1
    assert c["surrogate_confidence"] == "high"      # full vector + tier-a + source
    assert c["fidelity_gate"] == "pending"
    assert c["perturbation"] == {"kind": "node-add", "target_ig": 41,
                                 "use_set": [42]}
    assert c["c_realizations"][0]["confidence_tier"] == "a"
    # mutually exclusive routing: an actionable candidate is not a lead.
    assert bundle.tooling_leads == []


def test_assemble_edge_hit_is_proposal_tier():
    p = Perturbation(PerturbationKind.EDGE_REMOVE, target_ig=88, edge=(88, 37))
    hit = {"perturbation": p, "targets_met": 1, "delta": {"88": [26, 25]},
           "actionable": False}
    bundle = assemble_realized(
        _enum_out([hit]), phys_target={88: 25}, catalog=_CATALOG,
        source_lookup=lambda ig_idx: "row_text")
    assert bundle.candidates[0]["surrogate_confidence"] == "proposal"   # tier b


def test_assemble_routes_window_hits_to_window_order():
    whit = {"perturbation": _node_add(target=60), "targets_met": 1,
            "delta": {"60": [22, 21]}, "actionable": False}
    bundle = assemble_realized(
        _enum_out([], window_hits=[whit]), phys_target={60: 21},
        catalog=_CATALOG, source_lookup=lambda ig_idx: "table_copy")
    assert bundle.candidates == []
    assert len(bundle.window_order) == 1
    assert bundle.window_order[0]["residual"] == "allocation-window"


def test_assemble_filter_summary_passthrough_and_evals():
    bundle = assemble_realized(
        _enum_out([]), phys_target={41: 27}, catalog=_CATALOG,
        source_lookup=lambda ig_idx: None)
    assert bundle.filter_summary == {"candidates_generated": 10, "rejected_a": 2,
                                     "rejected_b": 1, "flagged_c": 0,
                                     "rejected_survival": 1}
    assert bundle.evals_per_kind == {"node-add": 6, "edge": 2, "order": 2}


def test_assemble_enriches_pair_hits_actionability():
    p1 = _node_add(target=41, new_ig=100)
    p2 = _node_add(target=43, new_ig=101)
    ph = {"perturbations": (p1, p2), "targets_met": 2, "delta": {},
          "actionable": False}
    bundle = assemble_realized(
        _enum_out([], pair_hits=[ph], pair_ran=True), phys_target={41: 27, 43: 26},
        catalog=_CATALOG,
        source_lookup=lambda ig_idx: "obj" if ig_idx in (41, 43) else None)
    enriched = bundle.pair_escalation["pair_hits"][0]
    assert enriched["actionable"] is True
    assert [pp["target_ig"] for pp in enriched["perturbations"]] == [41, 43]

    bundle2 = assemble_realized(
        _enum_out([], pair_hits=[ph], pair_ran=True), phys_target={41: 27, 43: 26},
        catalog=_CATALOG,
        source_lookup=lambda ig_idx: "obj" if ig_idx == 41 else None)
    assert bundle2.pair_escalation["pair_hits"][0]["actionable"] is False


def test_assemble_ranking_tier_then_churn():
    p_alias = _node_add(target=41, new_ig=100)
    p_edge = Perturbation(PerturbationKind.EDGE_REMOVE, target_ig=88, edge=(88, 37))
    hits = [
        {"perturbation": p_edge, "targets_met": 1, "delta": {"88": [26, 25]},
         "actionable": False},
        {"perturbation": p_alias, "targets_met": 1, "delta": {"41": [30, 27]},
         "actionable": False},
    ]
    bundle = assemble_realized(
        _enum_out(hits), phys_target={41: 27}, catalog=_CATALOG,
        source_lookup=lambda ig_idx: "obj")
    # tier-a node-add ranks above tier-b edge regardless of input order.
    assert bundle.candidates[0]["perturbation"]["kind"] == "node-add"
    assert bundle.candidates[0]["rank"] == 1
    assert bundle.candidates[1]["rank"] == 2
