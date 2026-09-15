from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.enumerate import (
    EnumConfig, EnumResult, compose_frontier_pairs, enumerate_single,
    enumerate_with_escalation, implicated_nodes, insertion_positions,
    normalize_kinds, use_set_family,
)
from src.search.solver.types import Perturbation, PerturbationKind
from src.search.solver.validity import FilterVerdict


def _ig():
    nodes = {
        40: IGNode(40, {41}, {}, 1, False, 31),
        41: IGNode(41, {40, 42}, {}, 2, False, 30),
        42: IGNode(42, {41, 43}, {}, 2, False, 29),
        43: IGNode(43, {42}, {}, 1, False, 28),
    }
    return IG(class_id=0, select_order=[40, 41, 42, 43], nodes=nodes,
              decision_igs={40, 41, 42, 43})


def _pair_only_ig():
    """Verified pair-only construction (registers DERIVED via predict_assignments,
    NOT narrative constants — see plan's T2-review fixture hazard).

    Two independent "columns": 50 is blocked off r3 only by blocker 60 (which
    grabs r3 first, being earlier in select order and blocked only by machine
    reg 0); 51 is blocked off r3 only by blocker 61 the same way. 50 and 51 do
    NOT interfere, and neither blocker interferes with the other column. To get
    50==r3 you must order 50 before 60; to get 51==r3 you must order 51 before
    61 — and (crucially) one such move frees only its OWN column (the displaced
    blocker drops to r4 but the other column is untouched). So no SINGLE
    perturbation meets BOTH targets {50:3, 51:3} (best single met == 1), while
    the PAIR of the two order moves meets both. The precolored blocker (machine
    reg 0) sits at the contended physical r0 so r3 is the lowest free legal pick
    each blocker contends for — the T2 contention-boundary requirement.

    Baseline assignment (predict_assignments): {60:3, 61:3, 50:4, 51:4}."""
    nodes = {
        60: IGNode(60, {0, 50}, {0: 0}, 2, False, 3),
        61: IGNode(61, {0, 51}, {0: 0}, 2, False, 3),
        50: IGNode(50, {0, 60}, {0: 0}, 2, False, 4),
        51: IGNode(51, {0, 61}, {0: 0}, 2, False, 4),
    }
    return IG(class_id=0, select_order=[60, 61, 50, 51], nodes=nodes,
              decision_igs={60, 61, 50, 51})


def _after_order_ig():
    """Target 50 starts before 60 and gets r3.

    Moving 50 after 60 lets 60 take r3 first, so 50 is forced to r4. This
    catches order enumerators that only try "before" placements.
    """
    nodes = {
        50: IGNode(50, {0, 60}, {0: 0}, 2, False, 3),
        60: IGNode(60, {0, 50}, {0: 0}, 2, False, 4),
    }
    return IG(class_id=0, select_order=[50, 60], nodes=nodes,
              decision_igs={50, 60})


_PAIR_TARGET = {50: 3, 51: 3}


def _admit_all(p, ctx):
    return FilterVerdict(admit=True)


# --- generators ---
def test_normalize_kinds_expands_edge():
    # codex major 6: the advertised default "node-add,edge,order" must expand.
    assert normalize_kinds(["node-add", "edge", "order"]) == (
        "node-add", "edge-add", "edge-remove", "order")
    assert normalize_kinds(["edge-add"]) == ("edge-add",)


def test_implicated_1hop_is_target_plus_neighbors():
    assert implicated_nodes(_ig(), phys_target={41: 30}, hops=1) == {41, 40, 42}


def test_implicated_2hop_widens_capped():
    impl = implicated_nodes(_ig(), phys_target={41: 30}, hops=2, cap=64)
    assert {40, 41, 42, 43} <= impl


def test_use_set_family_is_bounded_four():
    assert 1 <= len(use_set_family(_ig(), v=42)) <= 4


def test_insertion_positions_are_two():
    assert set(insertion_positions(_ig(), v=42)) == {"before", "after"}


# --- single enumeration: tallies + window bucket + budget floors ---
def test_enumerate_single_tallies_filter_counts():
    def filt(p, ctx):
        if p.kind is not PerturbationKind.NODE_ADD:
            return FilterVerdict(admit=True)
        if p.target_ig == 41:
            return FilterVerdict(admit=False, reason="rejected_a")
        if p.target_ig == 42:
            return FilterVerdict(admit=False, flag="flagged_c")
        return FilterVerdict(admit=True)

    res = enumerate_single(_ig(), phys_target={42: 27}, config=EnumConfig(),
                           filter_fn=filt, probe_ctx_fn=lambda p: None)
    assert isinstance(res, EnumResult)
    fc = res.filter_counts
    assert fc["candidates_generated"] > 0
    assert fc["rejected_a"] > 0 and fc["flagged_c"] > 0
    assert set(fc) == {"candidates_generated", "rejected_a", "rejected_b",
                       "flagged_c", "rejected_survival"}
    # flagged candidates are EVALUATED into the window bucket, not dropped.
    assert isinstance(res.window_order_hits, list)
    assert set(res.evals_per_kind) == {"node-add", "edge", "order"}


def test_per_kind_floors_reserve_edge_and_order():
    cfg = EnumConfig(eval_cap=200_000, edge_floor=10_000, order_floor=10_000)
    assert cfg.node_add_budget() == 180_000


def test_full_hits_record_assignment_delta():
    res = enumerate_single(_pair_only_ig(), phys_target={50: 3},
                           config=EnumConfig(), filter_fn=_admit_all,
                           probe_ctx_fn=lambda p: None)
    # single order move (50 before 60) meets the one-target case -> FULL hit
    assert res.full_hits, "expected a full hit for the single-target case"
    hit = res.full_hits[0]
    assert "delta" in hit and 50 in hit["delta"]


# --- pair composition (codex blocker 1) ---
def test_pair_only_ig_has_no_single_full_hit_exhaustive():
    big = EnumConfig(eval_cap=10_000_000, edge_floor=4_000_000,
                     order_floor=4_000_000)
    res = enumerate_single(_pair_only_ig(), phys_target=_PAIR_TARGET,
                           config=big, filter_fn=_admit_all,
                           probe_ctx_fn=lambda p: None)
    assert res.full_hits == [], "construction is single-solvable — fix fixture"
    assert res.partial_hits, "order-move partials must exist for the frontier"


def test_compose_frontier_pairs_finds_the_working_pair():
    cfg = EnumConfig()
    single = enumerate_single(_pair_only_ig(), phys_target=_PAIR_TARGET,
                              config=cfg, filter_fn=_admit_all,
                              probe_ctx_fn=lambda p: None)
    frontier = sorted(single.partial_hits,
                      key=lambda h: -h["targets_met"])[:cfg.frontier]
    out = compose_frontier_pairs(_pair_only_ig(), _PAIR_TARGET, frontier, cfg,
                                 evals_used=sum(single.evals_per_kind.values()))
    assert out["pair_hits"], "the known working pair was not found"
    kinds = {tuple(sorted((p1.kind.value, p2.kind.value)))
             for p1, p2 in (h["perturbations"] for h in out["pair_hits"])}
    assert ("order", "order") in kinds
    assert out["pair_evals"] > 0 and out["truncated"] is False


def test_compose_frontier_pairs_respects_remaining_budget():
    # Normal single run builds a real (>=2 entry) frontier; then hand compose
    # an EXHAUSTED budget — it must evaluate nothing and flag truncation.
    cfg = EnumConfig()
    single = enumerate_single(_pair_only_ig(), phys_target=_PAIR_TARGET,
                              config=cfg, filter_fn=_admit_all,
                              probe_ctx_fn=lambda p: None)
    frontier = sorted(single.partial_hits,
                      key=lambda h: -h["targets_met"])[:cfg.frontier]
    assert len(frontier) >= 2
    out = compose_frontier_pairs(_pair_only_ig(), _PAIR_TARGET, frontier, cfg,
                                 evals_used=cfg.eval_cap)   # budget exhausted
    assert out["pair_evals"] == 0 and out["truncated"] is True


def test_per_kind_budget_hit_continues_to_next_kind():
    # spec §2.1: the floors are GUARANTEED — exhausting node-add's budget must
    # not abort enumeration before edge/order run.
    cfg = EnumConfig(eval_cap=22, edge_floor=10, order_floor=10)  # node-add: 2
    res = enumerate_single(_pair_only_ig(), phys_target=_PAIR_TARGET,
                           config=cfg, filter_fn=_admit_all,
                           probe_ctx_fn=lambda p: None)
    assert res.truncated is True                      # node-add hit its budget
    assert res.evals_per_kind["node-add"] == 2
    assert res.evals_per_kind["edge"] > 0             # floors still consumed
    assert res.evals_per_kind["order"] > 0
    assert res.last_kind == "order"                   # all kinds visited


def test_enumerate_with_escalation_honors_config_kinds_order_only():
    cfg = EnumConfig(kinds=("order",))
    out = enumerate_with_escalation(
        _pair_only_ig(), phys_target=_PAIR_TARGET, config=cfg,
        filter_fn=_admit_all, probe_ctx_fn=lambda p: None,
        actionable_fn=lambda hit: hit.get("actionable", False))
    single = out["single"]
    assert single.evals_per_kind["node-add"] == 0
    assert single.evals_per_kind["edge"] == 0
    assert single.evals_per_kind["order"] > 0


def test_order_enumeration_includes_before_and_after_moves():
    cfg = EnumConfig(kinds=("order",))
    res = enumerate_single(_after_order_ig(), phys_target={50: 4}, config=cfg,
                           filter_fn=_admit_all, probe_ctx_fn=lambda p: None,
                           kinds=cfg.kinds)

    moves = {
        tuple(hit["perturbation"].order_move)
        for hit in res.full_hits + res.partial_hits + res.window_order_hits
        if hit["perturbation"].target_ig == 50
    }

    assert ("after", 60) in moves


# --- escalation gating (finding 3) ---
def test_escalation_fires_on_no_actionable_single_not_zero_hits():
    calls = {"pairs_ran": False}

    def fake_single(*a, **k):
        return EnumResult(
            full_hits=[{"actionable": False, "targets_met": 2, "delta": {}}],
            partial_hits=[], window_order_hits=[],
            filter_counts={"candidates_generated": 1, "rejected_a": 0,
                           "rejected_b": 0, "flagged_c": 0, "rejected_survival": 0},
            evals_per_kind={"node-add": 1, "edge": 0, "order": 0},
            truncated=False, last_kind="node-add")

    def fake_pairs(ig, pt, frontier, cfg, *, evals_used):
        calls["pairs_ran"] = True
        return {"ran": True, "reason": "no actionable single",
                "frontier_size": len(frontier), "frontier": frontier,
                "pair_hits": [], "pair_evals": 0, "truncated": False}

    out = enumerate_with_escalation(
        _ig(), phys_target={42: 27}, config=EnumConfig(),
        filter_fn=_admit_all, probe_ctx_fn=lambda p: None,
        actionable_fn=lambda hit: hit.get("actionable", False),
        _single_impl=fake_single, _pair_impl=fake_pairs)
    assert calls["pairs_ran"] is True
    assert out["pair_escalation"]["ran"] is True


def test_escalation_skipped_when_actionable_single_exists():
    def fake_single(*a, **k):
        return EnumResult(
            full_hits=[{"actionable": True, "targets_met": 2, "delta": {}}],
            partial_hits=[], window_order_hits=[],
            filter_counts={"candidates_generated": 1, "rejected_a": 0,
                           "rejected_b": 0, "flagged_c": 0, "rejected_survival": 0},
            evals_per_kind={"node-add": 1, "edge": 0, "order": 0},
            truncated=False, last_kind="node-add")

    out = enumerate_with_escalation(
        _ig(), phys_target={42: 27}, config=EnumConfig(),
        filter_fn=_admit_all, probe_ctx_fn=lambda p: None,
        actionable_fn=lambda hit: hit.get("actionable", False),
        _single_impl=fake_single,
        _pair_impl=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no")))
    assert out["pair_escalation"]["ran"] is False


def test_default_pair_impl_is_production_compose():
    # Without injection, escalation runs the REAL compose_frontier_pairs and
    # FINDS the pair on the pair-only IG (codex blocker 1: not a stub).
    out = enumerate_with_escalation(
        _pair_only_ig(), phys_target=_PAIR_TARGET, config=EnumConfig(),
        filter_fn=_admit_all, probe_ctx_fn=lambda p: None,
        actionable_fn=lambda hit: hit.get("actionable", False))
    pe = out["pair_escalation"]
    assert pe["ran"] is True and pe["pair_hits"]
