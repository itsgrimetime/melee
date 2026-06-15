from src.search.solver.fpr_sweep import SweepTally, classify_sweep


def test_zero_misses_is_pass():
    t = SweepTally(n_fpr=120, clean=100, excluded_truncated=20,
                   g1_perfect=100, g1_imperfect_clean=0,
                   characterized_exclusions=0)
    v = classify_sweep(t)
    assert v["verdict"] == "pass" and v["fpr_coverage"] == "full"
    assert v["n_fpr"] == 120 and v["denominator_clean"] == 100


def test_all_characterized_misses_proceed_filtered():
    t = SweepTally(n_fpr=120, clean=100, excluded_truncated=20,
                   g1_perfect=92, g1_imperfect_clean=8,
                   characterized_exclusions=8)
    v = classify_sweep(t)
    assert v["verdict"] == "proceed_filtered" and v["fpr_coverage"] == "filtered"


def test_any_uncharacterized_miss_is_hard_stop_even_below_5pct():
    # codex major 8: rev3 §5 — a clean fixture NOT covered by a documented
    # static exclusion is a HARD STOP ("do not relax"), even at 1%.
    t = SweepTally(n_fpr=120, clean=100, excluded_truncated=20,
                   g1_perfect=99, g1_imperfect_clean=1,
                   characterized_exclusions=0)
    v = classify_sweep(t)
    assert v["verdict"] == "hard_stop"
    assert v["remedy"] == "fix-fpr-dispense-reading"     # <=5%: fix and re-run


def test_uncharacterized_above_5pct_ships_gpr_only():
    t = SweepTally(n_fpr=120, clean=100, excluded_truncated=20,
                   g1_perfect=90, g1_imperfect_clean=10,
                   characterized_exclusions=0)
    v = classify_sweep(t)
    assert v["verdict"] == "hard_stop" and v["remedy"] == "ship-gpr-only"


def test_partially_characterized_is_still_hard_stop():
    t = SweepTally(n_fpr=120, clean=100, excluded_truncated=20,
                   g1_perfect=94, g1_imperfect_clean=6,
                   characterized_exclusions=4)        # 2 uncharacterized
    v = classify_sweep(t)
    assert v["verdict"] == "hard_stop"
