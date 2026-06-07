from typer.testing import CliRunner

from src.cli.capabilities import capabilities_app

runner = CliRunner()


def test_capabilities_help_lists_subcommands():
    res = runner.invoke(capabilities_app, ["--help"])
    assert res.exit_code == 0
    out = res.output.lower()
    assert "search" in out
    assert "show" in out
    assert "generate" in out
