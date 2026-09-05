from src.backtest.score import select_escalation


def test_escalation_includes_gaps_and_control_sample():
    results = [{"case_id": f"c{i}", "rollup": "SOLVED-BY-TOOLING"} for i in range(20)]
    results += [{"case_id": "g1", "rollup": "GAP"}, {"case_id": "p1", "rollup": "PARTIAL"}]
    cases = {f"c{i}": {"provenance": "held_out"} for i in range(20)}
    cases["g1"] = {"provenance": "held_out"}; cases["p1"] = {"provenance": "held_out"}
    sel = select_escalation(results, cases, control_n=5)
    assert "g1" in sel and "p1" in sel
    controls = [cid for cid in sel if cid.startswith("c")]
    assert len(controls) == 5  # capped control sample
