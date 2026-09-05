import os
import pytest

from src.search.directed.kill_switch import evaluate_kill_switch
from src.search.directed.order_metric import CandidateScore


def _score(od, ranks):
    return CandidateScore(
        valid=True, invalid_reason=None, ranks_by_role=ranks,
        order_distance=od, phys_matched=0, coverage=1.0,
    )


# Target: ig21 before ig22 (ranks 5 < 7). Pair order is DERIVED from each
# candidate's ranks_by_role (B7) — there are no separate pair-order inputs.
_TARGET = {21: 5, 22: 7}


def test_all_assertions_pass_when_win_descends():
    scores = {
        "pre_win": _score(1, {21: 7, 22: 5}),            # pair inverted
        "win": _score(0, {21: 5, 22: 7}),                # pair correct, descends
        "negative_control": _score(1, {21: 7, 22: 5}),   # no descent
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22), order_target=_TARGET)
    assert res.passed is True
    assert (res.assertion_a, res.assertion_b, res.assertion_c, res.assertion_d) == (
        True, True, True, True)


def test_fires_when_win_does_not_descend():
    scores = {
        "pre_win": _score(1, {21: 7, 22: 5}),
        "win": _score(1, {21: 7, 22: 5}),                # still inverted
        "negative_control": _score(2, {21: 7, 22: 5}),
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22), order_target=_TARGET)
    assert res.passed is False
    assert res.assertion_b is False
    assert "strict descent" in res.failure_reason


def test_fires_when_anchor_sets_differ():
    scores = {
        "pre_win": _score(1, {21: 7, 22: 5}),
        "win": _score(0, {21: 5, 99: 7}),                # different role anchored
        "negative_control": _score(1, {21: 7, 22: 5}),
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22), order_target=_TARGET)
    assert res.passed is False
    assert res.assertion_a is False


def test_fires_when_negative_control_descends():
    scores = {
        "pre_win": _score(1, {21: 7, 22: 5}),
        "win": _score(0, {21: 5, 22: 7}),
        "negative_control": _score(0, {21: 5, 22: 7}),   # control improved
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22), order_target=_TARGET)
    assert res.passed is False
    assert res.assertion_d is False


def test_fires_when_named_pair_does_not_flip():
    # Three roles: the descent comes from the (22, 23) pair; the NAMED pair
    # (21, 22) was already correct in pre_win -> (c) must fail even though
    # (b) holds. Pins that the descent is the INTENDED relation.
    target = {21: 5, 22: 7, 23: 9}
    scores = {
        "pre_win": _score(1, {21: 5, 22: 7, 23: 6}),     # only (22,23) inverted
        "win": _score(0, {21: 5, 22: 7, 23: 9}),
        "negative_control": _score(1, {21: 5, 22: 7, 23: 6}),
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22), order_target=target)
    assert res.passed is False
    assert res.assertion_b is True
    assert res.assertion_c is False


def test_invalid_candidate_fires():
    scores = {
        "pre_win": CandidateScore(False, "target_role_lost", None, None, None, 0.5),
        "win": _score(0, {21: 5, 22: 7}),
        "negative_control": _score(1, {21: 7, 22: 5}),
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22), order_target=_TARGET)
    assert res.passed is False
    assert "invalid" in res.failure_reason


_LIVE = pytest.mark.skipif(
    not os.environ.get("LIVE_KILLSWITCH"),
    reason="Set LIVE_KILLSWITCH=1 to score the real frozen pcdumps",
)


@pytest.mark.slow
@_LIVE
def test_kill_switch_on_frozen_fixtures():
    """Score the real frozen pcdumps of the GATING witness (eligibility.json)
    against its frozen OrderTarget, write the result doc, and assert the
    verdict. PASS == the premise holds; anything else == STOP (loud)."""
    from pathlib import Path
    from src.search.directed.kill_switch import run_kill_switch_from_fixtures

    # tests/search/directed/test_kill_switch.py -> parents[2] == tests/
    fixtures_root = Path(__file__).resolve().parents[2] / "fixtures" / "order_distance"
    res = run_kill_switch_from_fixtures(fixtures_root)
    assert res.result_doc_path is not None and Path(res.result_doc_path).exists()
    assert res.passed, f"KILL SWITCH FIRED — premise refuted/stopped: {res.failure_reason}"
