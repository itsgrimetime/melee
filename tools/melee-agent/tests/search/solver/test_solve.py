from src.search.solver.realize import RealizedBundle
from src.search.solver.solve import Preconditions, SolveResult, solve_coloring


def _ok_pre(**over):
    base = dict(register_only=True, reachable=True, g1_rate=1.0,
                phys_target={42: 27}, g1_truncated=False,
                force_phys_collision=False)
    base.update(over)
    return Preconditions(**base)


def _bundle(candidates=(), leads=(), window=(), pair_hits=(), pair_ran=False):
    return RealizedBundle(
        candidates=list(candidates), tooling_leads=list(leads),
        window_order=list(window),
        filter_summary={"candidates_generated": 4, "rejected_a": 0,
                        "rejected_b": 0, "flagged_c": len(window),
                        "rejected_survival": 0},
        evals_per_kind={"node-add": 4, "edge": 0, "order": 0},
        pair_escalation={"ran": pair_ran,
                         "reason": "no actionable single" if pair_ran
                         else "actionable single exists",
                         "frontier_size": 0, "frontier": [],
                         "pair_hits": list(pair_hits), "pair_evals": 0,
                         "truncated": False},
        enumeration_truncated=False, last_kind="order")


def _cand(rank=1):
    return {"rank": rank, "perturbation": {"kind": "node-add", "target_ig": 41,
                                           "use_set": [42]},
            "predicted_assignment_delta": {"42": [29, 27]},
            "c_realizations": [{"lever": "alias", "source_object": "x",
                                "confidence_tier": "a"}],
            "surrogate_confidence": "high", "fidelity_gate": "pending"}


def _boom(**k):
    raise AssertionError("must not be called")


def test_abstain_exit3_when_g1_imperfect():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(g1_rate=0.8),
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3 and "G1" in res.reason


def test_abstain_exit3_on_force_phys_collision():
    delta = {
        "kind": "node-set-delta",
        "missing_virtuals": [{"target_ig": 42, "source_action": "split tmp"}],
    }
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(
                             reachable=False, force_phys_collision=True,
                             node_set_delta=delta),
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3
    assert "collision" in res.reason.lower() or "unreachable" in res.reason.lower()
    assert res.node_set_delta == delta


def test_recoverable_order_collision_reaches_enumeration():
    calls = {"enumerate": 0}

    def enum(**k):
        calls["enumerate"] += 1
        return {"enum": True}

    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(
                             reachable=False,
                             force_phys_collision=True,
                             recoverable_order_collision=True),
                         enumerate_fn=enum,
                         realize_fn=lambda **k: _bundle(pair_ran=True))
    assert calls["enumerate"] == 1
    assert res.exit_code == 4
    assert "collision" not in res.reason.lower()


def test_abstain_exit3_when_not_register_only():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(register_only=False),
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3
    # Control: no delta on this path => threaded value stays None.
    assert res.node_set_delta is None


def test_abstain_not_register_only_threads_node_set_delta():
    # #705 Task 3: the FPR node-set fallback abstains HERE (genuinely not
    # register-only) but must still carry the worksheet payload for the
    # downstream consumer.
    delta = {
        "kind": "node-set-delta",
        "register_prefix": "f",
        "missing_virtuals": [{"target_ig": 39, "source_action": "split f26"}],
    }
    res = solve_coloring(function="f", class_id=1,
                         preconditions_fn=lambda **k: _ok_pre(
                             register_only=False, phys_target={39: 26},
                             node_set_delta=delta),
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3
    assert res.reason.startswith("checkdiff not register-only")
    assert res.node_set_delta == delta


def test_abstain_exit3_on_empty_phys_target_matched_function():
    # codex major 7 / N4: matched function (empty target) ABSTAINS without
    # enumerating — never exit-4, never a fabricated candidate.
    res = solve_coloring(function="matched_fn", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(phys_target={}),
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3
    assert "empty" in res.reason.lower() or "matched" in res.reason.lower()


def test_abstain_exit3_when_target_truncated():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(g1_truncated=True),
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3


def test_abstain_exit3_on_unreachable_without_collision():
    # rev-t9 issue 3: the `not pre.reachable` half of the collision guard must
    # abstain on its own — a non-colliding-but-unreachable target still exits 3
    # BEFORE enumeration (_boom proves the guard short-circuits).
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(
                             reachable=False, force_phys_collision=False),
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3
    assert "collision" in res.reason.lower() or "unreachable" in res.reason.lower()


def test_exit0_when_actionable_candidate_found():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(),
                         enumerate_fn=lambda **k: {"enum": True},
                         realize_fn=lambda **k: _bundle(candidates=[_cand()]))
    assert res.exit_code == 0
    assert res.worksheet.candidates[0]["surrogate_confidence"] == "high"


def test_exit0_when_actionable_pair_found():
    ph = {"perturbations": [{"kind": "order", "target_ig": 50,
                             "order_move": ["before", 40]},
                            {"kind": "order", "target_ig": 51,
                             "order_move": ["before", 40]}],
          "targets_met": 2, "predicted_assignment_delta": {}, "actionable": True}
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(),
                         enumerate_fn=lambda **k: {"enum": True},
                         realize_fn=lambda **k: _bundle(pair_hits=[ph],
                                                        pair_ran=True))
    assert res.exit_code == 0


def test_exit4_when_no_actionable_candidate():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(),
                         enumerate_fn=lambda **k: {"enum": True},
                         realize_fn=lambda **k: _bundle(
                             leads=[{"note": "no source"}], pair_ran=True))
    assert res.exit_code == 4
    assert "budget" in res.reason.lower() or "no actionable" in res.reason.lower()


def test_exit4_window_order_when_all_hits_flagged():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(),
                         enumerate_fn=lambda **k: {"enum": True},
                         realize_fn=lambda **k: _bundle(
                             window=[{"residual": "allocation-window"}]))
    assert res.exit_code == 4
    assert res.reason == "window-order"


def test_exit4_generic_reason_when_window_hits_coexist_with_leads():
    # rev-t9 issue 1 / spec §1.5: reason="window-order" ONLY when ALL surviving
    # hits are window-flagged. tooling_leads (no-source-object FULL hits) are
    # surviving hits, so window + leads (no candidates/pairs) must fall through
    # to the GENERIC budgeted string, NOT report "window-order".
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(),
                         enumerate_fn=lambda **k: {"enum": True},
                         realize_fn=lambda **k: _bundle(
                             window=[{"residual": "allocation-window"}],
                             leads=[{"note": "no source"}]))
    assert res.exit_code == 4
    assert res.reason != "window-order"
    assert "budget" in res.reason.lower() or "no actionable" in res.reason.lower()
