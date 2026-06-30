import json
from pathlib import Path
from src.backtest.feedback import stage_gap, issue_report_argv


def test_stage_gap_writes_file(tmp_path):
    case = {"case_id": "abc123", "function": "f", "lever_class": "retype", "ground_truth_diff": "@@"}
    p = stage_gap(case, staging_dir=tmp_path)
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["function"] == "f" and data["lever_class"] == "retype"


def test_issue_argv_targets_the_function():
    case = {"function": "grIceMt_801F9ACC", "lever_class": "retype", "case_id": "x"}
    argv = issue_report_argv(case)
    assert argv[:2] == ["issue", "report"]
    assert "grIceMt_801F9ACC" in argv
