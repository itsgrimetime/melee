from src.backtest.calibrate import calibrate
from src.backtest.fixtures import load_calibration_fixtures


def test_calibration_passes_with_correct_scorers():
    fx = load_calibration_fixtures()
    # ideal scorers: positives solved, negatives gap
    def adv(f): return "names-lever" if f["kind"] == "positive" else "silent-or-wrong"
    def gen(f): return "byte-match-reproduced" if f["kind"] == "positive" else "no-progress"
    out = calibrate(fx, score_advisory=adv, score_generative=gen)
    assert out["passed"] is True


def test_calibration_fails_when_negative_leaks_to_solved():
    fx = load_calibration_fixtures()
    def adv(f): return "names-lever"
    def gen(f): return "byte-match-reproduced"   # everything "solved" -> negatives leak
    out = calibrate(fx, score_advisory=adv, score_generative=gen)
    assert out["passed"] is False
    assert any(fl["kind"] == "negative" for fl in out["failures"])
