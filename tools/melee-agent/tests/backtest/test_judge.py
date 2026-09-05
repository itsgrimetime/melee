# tools/melee-agent/tests/backtest/test_judge.py
import pytest
from src.backtest.judge import build_judge_input, parse_judge_verdict
from src.backtest.types import Case


def make_case():
    return Case(function="f", c_sha="a"*40, cprev_sha="b"*40, unit="u", file="x.c",
                ground_truth_diff="@@ retype", lever_locus="in_function", author="us",
                provenance="in_corpus", lever_class="retype", baseline_pct=99.0,
                baseline_ndl=4, target_pct=100.0, target_ndl=0)


def test_judge_input_is_label_blinded():
    ji = build_judge_input(make_case(), {"t": {"rc": 0, "stdout": "x"}})
    assert "provenance" not in ji and "author" not in ji
    assert ji["lever_class"] == "retype" and "tool_outputs" in ji


def test_parse_verdict_ok():
    assert parse_judge_verdict('prefix {"verdict": "names-lever", "rationale": "ok"} suffix') == "names-lever"


def test_parse_verdict_rejects_garbage():
    with pytest.raises(ValueError):
        parse_judge_verdict('{"verdict": "totally-made-up"}')
