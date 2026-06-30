from src.backtest.report import coverage_matrix, render_report, ESTIMAND_CAVEAT

CASES = [
    {"case_id": "a", "lever_class": "retype", "provenance": "held_out"},
    {"case_id": "b", "lever_class": "retype", "provenance": "held_out"},
    {"case_id": "c", "lever_class": "backend_coloring", "provenance": "held_out"},
]
RESULTS = [
    {"case_id": "a", "rollup": "SOLVED-BY-TOOLING"},
    {"case_id": "b", "rollup": "PARTIAL"},
    {"case_id": "c", "rollup": "GAP"},
]

def test_matrix_counts():
    m = coverage_matrix(CASES, RESULTS)
    assert m["retype"]["held_out"]["SOLVED-BY-TOOLING"] == 1
    assert m["retype"]["held_out"]["total"] == 2
    assert m["backend_coloring"]["held_out"]["GAP"] == 1

def test_report_prints_caveat():
    out = render_report(coverage_matrix(CASES, RESULTS))
    assert ESTIMAND_CAVEAT.split(".")[0] in out
    assert "held_out" in out
