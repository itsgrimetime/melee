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


def test_compare_records_missing_functions_as_not_comparable():
    retail = {"functions": None}
    debug = json.loads(FIXTURE.read_text())
    report = backend_fidelity.compare_backend_traces(retail, debug)
    assert report["summary"]["not_comparable"] == 1
    assert report["not_comparable"] == [
        {"side": "retail", "reason": "functions must be list"}
    ]


def test_compare_records_malformed_trace_pieces_as_not_comparable():
    retail = {
        "functions": [
            "not-a-function",
            {"name": "bad_classes", "regalloc": {"classes": None}},
            {"name": "bad_class_entry", "regalloc": {"classes": ["not-a-class"]}},
            {
                "name": "bad_nodes",
                "regalloc": {"classes": [{"class_id": 1, "nodes": None}]},
            },
            {
                "name": "bad_node_entry",
                "regalloc": {"classes": [{"class_id": 2, "nodes": ["not-a-node"]}]},
            },
            {
                "name": "missing_ig",
                "regalloc": {"classes": [{"class_id": 3, "nodes": [{"degree": 1}]}]},
            },
        ]
    }
    debug = json.loads(FIXTURE.read_text())
    report = backend_fidelity.compare_backend_traces(retail, debug)
    assert report["summary"]["not_comparable"] == 6
    assert {"side": "retail", "reason": "function must be object"} in report[
        "not_comparable"
    ]
    assert {
        "side": "retail",
        "function": "bad_classes",
        "reason": "classes must be list",
    } in report["not_comparable"]
    assert {
        "side": "retail",
        "function": "bad_class_entry",
        "reason": "class must be object",
    } in report["not_comparable"]
    assert {
        "side": "retail",
        "function": "bad_nodes",
        "class_id": 1,
        "reason": "nodes must be list",
    } in report["not_comparable"]
    assert {
        "side": "retail",
        "function": "bad_node_entry",
        "class_id": 2,
        "reason": "node must be object",
    } in report["not_comparable"]
    assert {
        "side": "retail",
        "function": "missing_ig",
        "class_id": 3,
        "reason": "node missing ig_id",
    } in report["not_comparable"]


def test_render_fidelity_text_includes_function_and_class_context():
    retail = json.loads(FIXTURE.read_text())
    debug = json.loads(FIXTURE.read_text())
    debug["functions"][0]["regalloc"]["classes"][0]["nodes"][0]["assigned_phys"] = 29
    report = backend_fidelity.compare_backend_traces(retail, debug)
    text = backend_fidelity.render_fidelity_text(report)
    assert "function=test_fn class_id=0 ig=32 assigned_phys retail=31 debug=29" in text
