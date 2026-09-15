import json
from unittest.mock import patch
from typer.testing import CliRunner
from src.cli import app


def test_backtest_status_is_registered():
    result = CliRunner().invoke(app, ["backtest", "status", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"harness": "backtest", "ready": True}


_CANNED_TRIPLES = [
    {"function": "grIceMt_801F9ACC", "c_sha": "3ce0722cd00", "cprev_sha": "13ccea11400",
     "file": "src/melee/gr/gricemt.c", "added": 1, "removed": 1, "shape": "tweak"},
]


def test_discover_json_output():
    """discover --json prints the triples as JSON (monkeypatched discover_match_commits)."""
    with patch("src.backtest.discover.discover_match_commits", return_value=_CANNED_TRIPLES):
        result = CliRunner().invoke(app, ["backtest", "discover", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["function"] == "grIceMt_801F9ACC"
