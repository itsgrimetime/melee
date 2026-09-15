"""Negative controls N4-N7 (spec §6 N-series; plan Task 15).

Each control must FAIL on a broken/permissive solver:
  N4  matched/no-residual fn  -> exit-3 ABSTAIN, BEFORE enumeration (_boom proof).
  N5  shuffled/unreachable    -> exit-3 (force-phys collision / reachable=False).
  N6  no-op / wrong alias      -> never scored as a win.
  N7  pair-only IG             -> escalation FIRES and the recorded working pair
                                 is FOUND (kind+target_ig), AND no single
                                 perturbation reaches the target under the
                                 PRODUCTION enumerator (brute-force exhaustive).

N7 fixture provenance (the rev2-7 trap): the plan's literal JSON illustration
(40/41/50/51 cross-connected) was brute-force-proven SINGLE-solvable, so it is
NOT used. The frozen fixture is the VERIFIED Task-5 `_pair_only_ig` (two
independent columns 60/50 and 61/51), whose no-single property is confirmed by
`test_n7_no_single_reaches_target_brute_force` below with the production
enumerator in exhaustive mode. See the fixture's PROVENANCE.md.
"""
import json
from pathlib import Path

from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.enumerate import (
    EnumConfig, enumerate_single, enumerate_with_escalation,
)
from src.search.solver.gate import classify_fidelity
from src.search.solver.solve import Preconditions, solve_coloring
from src.search.solver.validity import FilterVerdict

# tests/search/solver/... -> parents[2] == tests/ (codex minor 11 path fix)
N7 = (Path(__file__).resolve().parents[2]
      / "fixtures" / "solver" / "n7_pair" / "n7_ig.json")


def _boom(**k):
    raise AssertionError("must not be called")


# --- N4: matched function (empty phys_target) -> exit-3, never enumerates ---
def test_n4_matched_function_abstains_exit3():
    pre = Preconditions(register_only=True, reachable=True, g1_rate=1.0,
                        phys_target={}, g1_truncated=False,
                        force_phys_collision=False)
    res = solve_coloring(function="matched_fn", class_id=0,
                         preconditions_fn=lambda **k: pre,
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3


# --- N5: shuffled/unreachable target (collision) -> exit-3, never enumerates ---
# T2-review binding: the shuffled/unreachable target must TOGGLE A CONTENDED
# register under the dispense rule, not merely differ in a precolor value. r3
# is the contention boundary (lowest free legal pick after machine reg r0); a
# neighbor pinned at r3 forces the node off r3 -> r4 (verified at fixture
# authoring: see PROVENANCE.md "N5 contention proof"). The plan's narrative
# {42: 27} is NOT used: r27 is not the boundary under this dispense rule
# (_GPR_CALLEE_FRESH allocates r31-downward, so r27 is only contended once
# r31..r28 are taken). The abstain still fires BEFORE enumeration (_boom).
def test_n5_shuffled_target_collision_abstains_exit3():
    pre = Preconditions(register_only=True, reachable=False, g1_rate=1.0,
                        phys_target={42: 3}, g1_truncated=False,
                        force_phys_collision=True)
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: pre,
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3


# --- N6: wrong/no-op alias on a known win -> never a confirmed win ---
def test_n6_wrong_alias_is_realization_miss():
    out = classify_fidelity(new_ig=99, perturbation_present=False, g1_rate=1.0,
                            predicted={99: 27}, actual={}, phys_target={99: 27},
                            no_op=False)
    assert out.classification == "realization-miss" and out.is_win is False


def test_n6_noop_alias_is_unattributed():
    out = classify_fidelity(new_ig=99, perturbation_present=False, g1_rate=1.0,
                            predicted={}, actual={}, phys_target={99: 27},
                            no_op=True)
    assert out.classification == "UNATTRIBUTED" and out.is_win is False


# --- N7: pair-only fixture — brute-force no-single + pair FOUND ---
def _build_ig(rec):
    nodes = {int(k): IGNode(int(k), set(n["neighbors"]),
                            {int(a): b for a, b in (n.get("precolored") or {}).items()},
                            n["array_size"], n["incomplete"], n["observed_reg"])
             for k, n in rec["ig"]["nodes"].items()}
    return IG(class_id=rec["class_id"],
              select_order=list(rec["ig"]["select_order"]),
              nodes=nodes, decision_igs=set(nodes))


def _admit_all(p, ctx):
    return FilterVerdict(admit=True)


def test_n7_no_single_reaches_target_brute_force():
    rec = json.loads(N7.read_text())
    ig = _build_ig(rec)
    phys_target = {int(k): v for k, v in rec["phys_target"].items()}
    big = EnumConfig(eval_cap=10_000_000, edge_floor=4_000_000,
                     order_floor=4_000_000)
    res = enumerate_single(ig, phys_target, config=big, filter_fn=_admit_all,
                           probe_ctx_fn=lambda p: None)
    assert res.full_hits == [], "N7 fixture is secretly single-solvable — re-derive"
    assert res.partial_hits, "frontier must be non-empty for pair composition"


def test_n7_escalation_fires_and_FINDS_the_working_pair():
    # codex blocker 1: not "the callback ran" — the production composition must
    # FIND the recorded working pair within frontier/cap.
    rec = json.loads(N7.read_text())
    ig = _build_ig(rec)
    phys_target = {int(k): v for k, v in rec["phys_target"].items()}
    out = enumerate_with_escalation(
        ig, phys_target, config=EnumConfig(), filter_fn=_admit_all,
        probe_ctx_fn=lambda p: None,
        actionable_fn=lambda hit: hit.get("actionable", False))
    pe = out["pair_escalation"]
    assert pe["ran"] is True
    assert pe["pair_hits"], "production pair composition found no pair"
    expected = {(e["kind"], e["target_ig"])
                for e in rec["expected"]["working_pair"]}
    found = any(
        {(p.kind.value, p.target_ig) for p in hit["perturbations"]} == expected
        for hit in pe["pair_hits"])
    assert found, (f"recorded working pair {sorted(expected)} not among "
                   f"pair_hits")
    assert pe["truncated"] is False                       # respected the cap


def test_n7_low_confidence_single_does_not_suppress_pairs():
    # finding 3 regression: a FULL but non-actionable single must not gate pairs.
    rec = json.loads(N7.read_text())
    ig = _build_ig(rec)
    phys_target = {int(k): v for k, v in rec["phys_target"].items()}

    from src.search.solver.enumerate import EnumResult, compose_frontier_pairs

    def single_with_lead(*a, **k):
        real = enumerate_single(ig, phys_target, config=EnumConfig(),
                                filter_fn=_admit_all,
                                probe_ctx_fn=lambda p: None)
        fake_full = [{"perturbation": real.partial_hits[0]["perturbation"],
                      "targets_met": len(phys_target), "delta": {},
                      "actionable": False}]          # tooling-lead-shaped
        return EnumResult(fake_full, real.partial_hits, [], real.filter_counts,
                          real.evals_per_kind, False, "order")

    out = enumerate_with_escalation(
        ig, phys_target, config=EnumConfig(), filter_fn=_admit_all,
        probe_ctx_fn=lambda p: None,
        actionable_fn=lambda hit: hit.get("actionable", False),
        _single_impl=single_with_lead, _pair_impl=compose_frontier_pairs)
    assert out["pair_escalation"]["ran"] is True
