from typer.testing import CliRunner
from src.cli.layout import layout_app

runner = CliRunner()


def test_audit_help_lists_command():
    res = runner.invoke(layout_app, ["audit", "--help"])
    assert res.exit_code == 0
    assert "file" in res.output.lower()


def test_audit_missing_file_errors_cleanly(tmp_path):
    res = runner.invoke(layout_app, ["audit", str(tmp_path / "nope.c")])
    assert res.exit_code != 0
    assert "not found" in res.output.lower()
