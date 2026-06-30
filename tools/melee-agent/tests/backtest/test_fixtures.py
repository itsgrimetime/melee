from src.backtest.fixtures import load_calibration_fixtures


def test_fixtures_have_both_polarities():
    fx = load_calibration_fixtures()
    kinds = {f["kind"] for f in fx}
    assert kinds == {"positive", "negative"}
    # negatives must expect GAP, positives must expect SOLVED
    for f in fx:
        if f["kind"] == "negative":
            assert f["expected_rollup"] == "GAP"
        else:
            assert f["expected_rollup"] == "SOLVED-BY-TOOLING"


def test_negatives_are_backend_coloring():
    fx = load_calibration_fixtures()
    negs = [f for f in fx if f["kind"] == "negative"]
    assert negs and all(f["lever_class"] == "backend_coloring" for f in negs)
