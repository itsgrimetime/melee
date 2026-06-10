from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()


def test_retro_help_lists_subcommands():
    r = runner.invoke(app, ["debug", "retro", "--help"])
    assert r.exit_code == 0
    assert "setup" in r.output and "dump" in r.output and "verify" in r.output


def test_retro_dump_unknown_function_exit_3(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    def fake_launch(**kw):
        return retro.DumpOutcome(exit_code=3, produced=[], missing=["frontend"])
    monkeypatch.setattr(retro, "_launch_dump", fake_launch)
    monkeypatch.setattr(retro, "_ensure_setup", lambda: None)
    r = runner.invoke(app, ["debug", "retro", "dump",
                            "src/melee/mn/mnvibration.c", "-f", "nope_80000000"])
    assert r.exit_code == 3


def test_retro_dump_default_phases_all(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro
    seen = {}

    def fake_launch(**kw):
        seen.update(kw)
        return retro.DumpOutcome(exit_code=0, produced=["frontend"], missing=[])
    monkeypatch.setattr(retro, "_launch_dump", fake_launch)
    monkeypatch.setattr(retro, "_ensure_setup", lambda: None)
    r = runner.invoke(app, ["debug", "retro", "dump",
                            "src/melee/mn/mnvibration.c", "-f", "mnVibration_80248644"])
    assert r.exit_code == 0
    assert seen["phases"] == "all"
    assert seen["compiler"] == "1.2.5n"
