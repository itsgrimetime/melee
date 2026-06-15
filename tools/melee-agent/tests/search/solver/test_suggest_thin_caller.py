from typer.testing import CliRunner

import src.cli.debug as debugcli
from src.mwcc_debug import tiebreak as tb
from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.solve import SolveResult
from src.search.solver.worksheet import FilterSummary, PairEscalation, Worksheet

runner = CliRunner()


def _ws(class_id=0):
    return Worksheet(
        function="f", class_id=class_id, g1_rate=1.0, force_phys_target={},
        reachable=True, filter_summary=FilterSummary(0, 0, 0, 0, 0),
        candidates=[], tooling_leads=[], window_order=[],
        pair_escalation=PairEscalation(False, "x", 0, [], []),
        enumeration_truncated=False,
        evals_per_kind={"node-add": 0, "edge": 0, "order": 0})


def test_suggest_register_tiebreak_delegates_to_solve(monkeypatch):
    called = {"n": 0}
    seen = {}

    def fake_solve(**kw):
        called["n"] += 1
        seen.update(kw)
        return SolveResult(exit_code=4, reason="no actionable candidate",
                           worksheet=_ws())

    monkeypatch.setattr(debugcli, "_run_solve_coloring", fake_solve)
    monkeypatch.setattr(
        debugcli,
        "_register_tiebreak_window_order_fallback",
        lambda **_kw: {"ran": False, "reason": "not tested", "leads": []},
    )
    result = runner.invoke(debugcli.debug_app,
                           ["suggest", "register-tiebreak", "-f", "f", "--class", "gpr"])
    assert called["n"] == 1, "suggest register-tiebreak did not delegate"
    assert seen["class_id"] == 0
    assert seen["kinds"] == ["order"]
    assert seen["allow_unreachable_order"] is True
    assert seen["force_vector_timeout"] == 30.0
    assert result.exit_code == 4


def test_order_flip_fallback_canonicalizes_tail_move_after_anchor():
    ig = IG(
        class_id=0,
        select_order=[50, 60],
        nodes={
            50: IGNode(50, {0, 60}, {0: 0}, 2, False, 3),
            60: IGNode(60, {0, 50}, {0: 0}, 2, False, 4),
        },
        decision_igs={50, 60},
    )

    leads = debugcli._register_tiebreak_order_flip_leads(
        tb,
        ig,
        vector_targets=[{
            "ig_idx": 50,
            "already_target": True,
            "target_reg": 3,
            "target_reg_name": "r3",
        }],
        desired_regs={4},
    )

    assert leads[0]["target_ig"] == 50
    assert leads[0]["predicted_reg"] == 3
    assert leads[0]["perturbed_reg"] == 4
    assert leads[0]["order_move"] == ["after", 60]


def test_suggest_register_tiebreak_emits_fallback_lead(monkeypatch):
    def fake_solve(**_kw):
        return SolveResult(exit_code=4, reason="no actionable candidate",
                           worksheet=_ws())

    monkeypatch.setattr(debugcli, "_run_solve_coloring", fake_solve)
    monkeypatch.setattr(
        debugcli,
        "_register_tiebreak_window_order_fallback",
        lambda **_kw: {
            "ran": True,
            "reason": "window-order fallback leads found",
            "leads": [{
                "target_ig": 36,
                "observed_reg": 25,
                "predicted_reg": 25,
                "perturbed_reg": 23,
                "order_move": ["after", 33],
                "degree": 55,
                "move_distance": 379,
            }],
        },
    )

    result = runner.invoke(
        debugcli.debug_app,
        ["suggest", "register-tiebreak", "-f", "mnDiagram_InputProc"],
    )

    assert result.exit_code == 0
    assert "move ig36 after ig33: r25 -> r23" in result.output
    assert "window-order fallback lead(s) found" in result.output


def test_suggest_register_tiebreak_auto_retries_fpr_after_empty_gpr(monkeypatch):
    seen_classes = []

    def fake_solve(**kw):
        seen_classes.append(kw["class_id"])
        if kw["class_id"] == 0:
            return SolveResult(
                exit_code=3,
                reason="empty force-phys target (matched / no residual); nothing to reach",
            )
        return SolveResult(exit_code=4, reason="no actionable candidate",
                           worksheet=_ws(class_id=1))

    monkeypatch.setattr(debugcli, "_run_solve_coloring", fake_solve)
    monkeypatch.setattr(
        debugcli,
        "_register_tiebreak_window_order_fallback",
        lambda **kw: {
            "ran": True,
            "reason": "window-order fallback leads found",
            "leads": [{
                "target_ig": 39,
                "observed_reg": 28,
                "predicted_reg": 28,
                "perturbed_reg": 26,
                "order_move": ["after", 33],
                "degree": 12,
                "move_distance": 4,
            }] if kw["class_id"] == 1 else [],
        },
    )

    result = runner.invoke(
        debugcli.debug_app,
        ["suggest", "register-tiebreak", "-f", "mnDiagram_80241E78"],
    )

    assert seen_classes == [0, 1]
    assert result.exit_code == 0
    assert "move ig39 after ig33: f28 -> f26" in result.output
