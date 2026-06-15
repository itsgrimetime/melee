import json

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


def test_retro_dump_125n_backend_gap_writes_source_attribution(
    monkeypatch,
    tmp_path,
):
    import src.cli.debug.retro as retro
    seen = {}

    def fake_launch(**kw):
        seen["launch"] = kw
        return retro.DumpOutcome(
            exit_code=4,
            produced=["frontend"],
            missing=["backend"],
        )

    def fake_attribution(**kw):
        seen["attribution"] = kw
        path = kw["out_dir"] / "backend-source-attribution.json"
        path.write_text('{"status": "backend-trace-unavailable"}\n')
        return path

    monkeypatch.setattr(retro, "_launch_dump", fake_launch)
    monkeypatch.setattr(retro, "_ensure_setup", lambda: None)
    monkeypatch.setattr(retro, "_write_backend_source_attribution", fake_attribution)

    result = runner.invoke(app, [
        "debug", "retro", "dump",
        "src/melee/mn/mnvibration.c",
        "-f", "mnVibration_80248644",
        "--compiler", "1.2.5n",
        "--phases", "all",
        "-O", str(tmp_path),
    ])

    assert result.exit_code == 4
    assert seen["attribution"]["compiler"] == "1.2.5n"
    assert seen["attribution"]["missing"] == ["backend"]
    assert "backend source attribution" in result.output
    assert "backend-source-attribution.json" in result.output


def test_retro_backend_source_attribution_records_missing_pcdump(
    monkeypatch,
    tmp_path,
):
    import src.cli.debug as debugcli
    import src.cli.debug.retro as retro

    def missing_pcdump(*_args, **_kwargs):
        raise RuntimeError("cache missing")

    monkeypatch.setattr(debugcli, "_resolve_pcdump_path", missing_pcdump)

    path = retro._write_backend_source_attribution(
        out_dir=tmp_path,
        src="src/melee/mn/mnvibration.c",
        fn="mnVibration_80248644",
        compiler="1.2.5n",
        missing=["backend"],
    )

    payload = json.loads(path.read_text())
    assert payload["status"] == "pcdump-unavailable"
    assert "cache missing" in payload["reason"]
    assert payload["next_commands"][0].startswith("melee-agent debug dump local")


def test_retro_verify_passes(monkeypatch):
    import src.cli.debug.retro as retro
    import tools.mwcc_retro.verify as rv

    def fake_run(unit="x", fn=None):
        return [rv.Result(".o byte-parity", "parity", True, True, "ok")]
    monkeypatch.setattr(rv, "run", fake_run)
    r = runner.invoke(app, ["debug", "retro", "verify"])
    assert r.exit_code == 0
    assert "PASS" in r.output


def test_retro_verify_fails_on_authoritative(monkeypatch):
    import src.cli.debug.retro as retro
    import tools.mwcc_retro.verify as rv

    def fake_run(unit="x", fn=None):
        return [rv.Result(".o byte-parity", "parity", True, False, "mismatch")]
    monkeypatch.setattr(rv, "run", fake_run)
    r = runner.invoke(app, ["debug", "retro", "verify"])
    assert r.exit_code == 1
    assert "FAIL" in r.output


def test_retro_dump_gdb_py_threaded(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro
    seen = {}
    hook = tmp_path / "hook.py"
    hook.write_text("def intervene(ctx):\n    pass\n")

    def fake_launch(**kw):
        seen.update(kw)
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])
    monkeypatch.setattr(retro, "_launch_dump", fake_launch)
    monkeypatch.setattr(retro, "_ensure_setup", lambda: None)
    r = runner.invoke(app, ["debug", "retro", "dump",
                            "src/melee/mn/mnvibration.c", "-f", "mnVibration_80248644",
                            "--gdb-py", str(hook)])
    assert r.exit_code == 0
    assert seen["gdb_py"].endswith("hook.py")


def test_retro_dump_gdb_py_missing_hook_exit_2(monkeypatch):
    import src.cli.debug.retro as retro
    monkeypatch.setattr(retro, "_ensure_setup", lambda: None)
    r = runner.invoke(app, ["debug", "retro", "dump",
                            "src/melee/mn/mnvibration.c", "-f", "x",
                            "--gdb-py", "/no/such/hook.py"])
    assert r.exit_code == 2
