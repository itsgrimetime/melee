from src.inline_leverage.score import classify_score, parse_checkdiff_metrics
from src.inline_leverage.types import ScoreResult


def test_classify_strict_structural_lever() -> None:
    score = ScoreResult(
        compiled=True,
        baseline_pct=100.0,
        deinlined_pct=99.4,
        delta_fuzzy=0.6,
        baseline_ndl=0,
        deinlined_ndl=4,
        delta_struct=4,
    )

    assert classify_score(score) == "lever"


def test_classify_fuzzy_only_not_strict_lever() -> None:
    score = ScoreResult(
        compiled=True,
        baseline_pct=100.0,
        deinlined_pct=99.7,
        delta_fuzzy=0.3,
        baseline_ndl=0,
        deinlined_ndl=0,
        delta_struct=0,
    )

    assert classify_score(score) == "fuzzy_only"


def test_classify_neutral_under_epsilon() -> None:
    score = ScoreResult(
        compiled=True,
        baseline_pct=100.0,
        deinlined_pct=99.99,
        delta_fuzzy=0.01,
        baseline_ndl=0,
        deinlined_ndl=0,
        delta_struct=0,
    )

    assert classify_score(score, epsilon=0.05) == "neutral"


def test_classify_failed_when_variant_did_not_compile() -> None:
    score = ScoreResult(
        compiled=False,
        baseline_pct=100.0,
        deinlined_pct=None,
        delta_fuzzy=None,
        baseline_ndl=0,
        deinlined_ndl=None,
        delta_struct=None,
    )

    assert classify_score(score) == "deinline_failed"


def test_parse_checkdiff_metrics_reads_nested_structural_gate() -> None:
    pct, ndl = parse_checkdiff_metrics(
        {
            "fuzzy_match_percent": 99.84,
            "classification": {
                "structural_truth_gate": {
                    "normalized_diff_lines": 3,
                },
            },
        }
    )

    assert pct == 99.84
    assert ndl == 3
