from src.backtest.store import BacktestStore
from src.backtest.types import Case, CaseResult

def make_case():
    return Case(function="f", c_sha="a"*40, cprev_sha="b"*40, unit="main/melee/gr/g",
                file="src/melee/gr/g.c", ground_truth_diff="@@", lever_locus="in_function",
                author="other", provenance="held_out", lever_class="retype",
                baseline_pct=99.0, baseline_ndl=4, target_pct=100.0, target_ndl=0)

def test_roundtrip_case_and_result(tmp_path):
    s = BacktestStore(tmp_path / "bt.db"); s.ensure_schema()
    c = make_case(); s.insert_case(c)
    got = s.get_case(c.case_id)
    assert got["function"] == "f" and got["provenance"] == "held_out"
    s.upsert_result(CaseResult(case_id=c.case_id, advisory="names-lever", rollup="PARTIAL", evidence={"x": 1}))
    rows = s.results()
    assert rows[0]["advisory"] == "names-lever" and rows[0]["rollup"] == "PARTIAL"

def test_list_filter_by_provenance(tmp_path):
    s = BacktestStore(tmp_path / "bt.db"); s.ensure_schema()
    s.insert_case(make_case())
    assert len(s.list_cases(provenance="held_out")) == 1
    assert s.list_cases(provenance="in_corpus") == []
