from src.backtest.types import Case, CaseResult, LEVER_CLASSES

def test_case_id_is_stable_and_short():
    c = Case(function="grIceMt_801F9ACC", c_sha="3ce0722cd"*4 + "abcd",
             cprev_sha="13ccea114"*4 + "abcd", unit="main/melee/gr/gricemt",
             file="src/melee/gr/gricemt.c", ground_truth_diff="@@ ...",
             lever_locus="in_function", author="other", provenance="held_out",
             lever_class="retype", baseline_pct=99.98, baseline_ndl=4, target_pct=100.0)
    assert len(c.case_id) == 16
    assert c.case_id == c.case_id  # deterministic

def test_lever_classes_include_backend_coloring():
    assert "backend_coloring" in LEVER_CLASSES
    assert "other" in LEVER_CLASSES

def test_case_result_row_jsonifies_evidence():
    r = CaseResult(case_id="abc", advisory="names-lever", generative=None,
                   agent=None, rollup="PARTIAL", evidence={"k": [1, 2]})
    row = r.to_row()
    assert row["evidence"] == '{"k": [1, 2]}'
