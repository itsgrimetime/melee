import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_fidelity, backend_schema  # noqa: E402

FIXTURE = REPO / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"


def test_compare_trace_to_itself_all_equal():
    trace = json.loads(FIXTURE.read_text())
    report = backend_fidelity.compare_backend_traces(trace, trace)
    assert report["summary"]["different"] == 0
    assert report["summary"]["equal"] > 0


def test_compare_detects_assignment_difference():
    retail = json.loads(FIXTURE.read_text())
    debug = json.loads(FIXTURE.read_text())
    debug["functions"][0]["regalloc"]["classes"][0]["nodes"][0]["assigned_phys"] = 29
    report = backend_fidelity.compare_backend_traces(retail, debug)
    assert report["summary"]["different"] == 1
    assert report["different"][0]["field"] == "assigned_phys"
    assert report["different"][0]["ig_id"] == 32


def test_render_fidelity_text_reports_data_not_failure():
    retail = json.loads(FIXTURE.read_text())
    debug = json.loads(FIXTURE.read_text())
    debug["functions"][0]["regalloc"]["classes"][0]["nodes"][0]["assigned_phys"] = 29
    report = backend_fidelity.compare_backend_traces(retail, debug)
    text = backend_fidelity.render_fidelity_text(report)
    assert "different: 1" in text
    assert "ig=32 assigned_phys retail=31 debug=29" in text
