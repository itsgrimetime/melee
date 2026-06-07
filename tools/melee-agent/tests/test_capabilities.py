from typer.testing import CliRunner

from src.cli import capabilities as cap
from src.cli.capabilities import capabilities_app

runner = CliRunner()


def test_capabilities_help_lists_subcommands():
    res = runner.invoke(capabilities_app, ["--help"])
    assert res.exit_code == 0
    out = res.output.lower()
    assert "search" in out
    assert "show" in out
    assert "generate" in out


def test_command_capabilities_include_known_commands():
    caps = cap.command_capabilities()
    names = {c.name for c in caps}
    # Known leaf commands from the real tree (verified against live introspection):
    assert "debug target score-source" in names   # NOTE: there is NO `debug score`
    assert "extract files" in names
    assert "struct verify" in names
    # Every command has a non-empty invoke string and a summary fallback.
    for c in caps:
        assert c.invoke.startswith("melee-agent ")
        assert isinstance(c.summary, str)
