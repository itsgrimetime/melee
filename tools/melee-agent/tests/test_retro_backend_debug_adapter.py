import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from src.cli import app  # noqa: E402
from tools.mwcc_retro import backend_fidelity  # noqa: E402

PCDUMP = REPO / "tools/melee-agent/tests/fixtures/mwcc_debug/fn_80247510_pcdump.txt"
TRACE_FIXTURE = REPO / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"

runner = CliRunner()


def test_debug_pcdump_adapter_produces_comparable_trace_shape():
    trace = backend_fidelity.trace_from_mwcc_debug_pcdump(
        PCDUMP.read_text(),
        function="fn_80247510",
        source="src/melee/mn/mnvibration.c",
    )

    assert trace["schema_version"] == "mwcc-retro-backend-trace.v1"
    assert trace["compiler"]["retail"] is False
    assert trace["compiler"]["version"] == "GC/1.2.5n-debug-dll"
    fn = trace["functions"][0]
    assert fn["name"] == "fn_80247510"
    cls = next(c for c in fn["regalloc"]["classes"] if c["class_id"] == 0)
    assert cls["nodes"]
    colored = next(node for node in cls["nodes"] if node["color_status"] == "colored")
    assert colored["color_decision_ref"] is not None
    decisions = {decision["id"]: decision for decision in cls["color_decisions"]}
    decision = decisions[colored["color_decision_ref"]]
    assert decision["provenance"] == "mwcc-debug-pcdump"
    assert decision["confidence"] == "debug-adapter"
    assert "blocked_by" in decision
    assert isinstance(decision["blocked_candidates"], list)


def test_debug_pcdump_adapter_reports_missing_function():
    with pytest.raises(ValueError) as excinfo:
        backend_fidelity.trace_from_mwcc_debug_pcdump(
            PCDUMP.read_text(),
            function="missing_fn",
            source="src/melee/mn/mnvibration.c",
        )

    assert "mwcc-debug pcdump missing function missing_fn" in str(excinfo.value)
    assert "available: fn_80247510" in str(excinfo.value)


def test_verify_backend_compares_trace_with_debug_pcdump(tmp_path):
    trace = json.loads(TRACE_FIXTURE.read_text())
    trace["source"]["function"] = "fn_80247510"
    trace["functions"][0]["name"] = "fn_80247510"
    trace["functions"][0]["identity"]["requested"] = "fn_80247510"
    trace_path = tmp_path / "backend-trace.v1.json"
    trace_path.write_text(json.dumps(trace) + "\n")

    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "verify-backend",
            "src/melee/mn/mnvibration.c",
            "-f",
            "fn_80247510",
            "--trace",
            str(trace_path),
            "--debug-pcdump",
            str(PCDUMP),
            "-O",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "backend fidelity: " in result.output
    assert (tmp_path / "backend-fidelity.json").exists()
    assert (tmp_path / "backend-fidelity.txt").exists()
    report = json.loads((tmp_path / "backend-fidelity.json").read_text())
    assert report["schema_version"] == "mwcc-retro-backend-fidelity.v1"
    assert "different" in report["summary"]


def test_verify_backend_defaults_to_candidate_trace_when_full_trace_missing(tmp_path):
    trace = json.loads(TRACE_FIXTURE.read_text())
    trace["source"]["function"] = "fn_80247510"
    trace["functions"][0]["name"] = "fn_80247510"
    trace["functions"][0]["identity"]["requested"] = "fn_80247510"
    trace["functions"][0]["identity"]["canonical_name"] = "fn_80247510"
    trace["functions"][0]["identity"]["symbol_name"] = "fn_80247510"
    trace["functions"][0]["identity"]["source_name"] = "fn_80247510"
    candidate_path = tmp_path / "backend-trace.candidate.v1.json"
    candidate_path.write_text(json.dumps(trace) + "\n")

    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "verify-backend",
            "src/melee/mn/mnvibration.c",
            "-f",
            "fn_80247510",
            "--debug-pcdump",
            str(PCDUMP),
            "-O",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert f"backend trace: {candidate_path}" in result.output
    assert (tmp_path / "backend-fidelity.json").exists()


def test_verify_backend_reports_missing_debug_function(tmp_path):
    trace = json.loads(TRACE_FIXTURE.read_text())
    trace["source"]["function"] = "missing_fn"
    trace["functions"][0]["name"] = "missing_fn"
    trace["functions"][0]["identity"]["requested"] = "missing_fn"
    trace["functions"][0]["identity"]["canonical_name"] = "missing_fn"
    trace["functions"][0]["identity"]["symbol_name"] = "missing_fn"
    trace["functions"][0]["identity"]["source_name"] = "missing_fn"
    trace_path = tmp_path / "backend-trace.v1.json"
    trace_path.write_text(json.dumps(trace) + "\n")

    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "verify-backend",
            "src/melee/mn/mnvibration.c",
            "-f",
            "missing_fn",
            "--trace",
            str(trace_path),
            "--debug-pcdump",
            str(PCDUMP),
            "-O",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 2, result.output
    assert "mwcc-debug pcdump missing function missing_fn" in result.output
    assert not (tmp_path / "backend-fidelity.json").exists()


def test_verify_backend_rejects_trace_for_different_function(tmp_path):
    trace = json.loads(TRACE_FIXTURE.read_text())
    trace_path = tmp_path / "backend-trace.v1.json"
    trace_path.write_text(json.dumps(trace) + "\n")

    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "verify-backend",
            "src/melee/mn/mnvibration.c",
            "-f",
            "fn_80247510",
            "--trace",
            str(trace_path),
            "--debug-pcdump",
            str(PCDUMP),
            "-O",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 2, result.output
    assert "backend trace function mismatch" in result.output
    assert "test_fn" in result.output
    assert "fn_80247510" in result.output
    assert not (tmp_path / "backend-fidelity.json").exists()
