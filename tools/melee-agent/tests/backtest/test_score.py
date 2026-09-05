from src.backtest.score import generative_verdict, rollup_verdict


def test_byte_match():
    assert generative_verdict(baseline_ndl=4, baseline_pct=99.0, best_ndl=0, best_pct=100.0) == "byte-match-reproduced"


def test_improved():
    assert generative_verdict(baseline_ndl=4, baseline_pct=99.0, best_ndl=2, best_pct=99.4) == "improved-toward"


def test_no_progress_on_timeout():
    assert generative_verdict(baseline_ndl=4, baseline_pct=99.0, best_ndl=None, best_pct=None) == "no-progress"


def test_rollup():
    assert rollup_verdict("silent-or-wrong", "byte-match-reproduced", None) == "SOLVED-BY-TOOLING"
    assert rollup_verdict("names-lever", "no-progress", None) == "PARTIAL"
    assert rollup_verdict("silent-or-wrong", "no-progress", "stuck") == "GAP"
