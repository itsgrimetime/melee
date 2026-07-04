import json
import subprocess
from pathlib import Path

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
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)
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
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)
    r = runner.invoke(app, ["debug", "retro", "dump",
                            "src/melee/mn/mnvibration.c", "-f", "mnVibration_80248644"])
    assert r.exit_code == 0
    assert seen["phases"] == "all"
    assert seen["compiler"] == "1.2.5n"
    assert seen["melee_root"] == retro._resolve_melee_root()
    assert seen["timeout"] == 600


def test_retro_dump_passes_explicit_timeout(monkeypatch):
    import src.cli.debug.retro as retro
    seen = {}

    def fake_launch(**kw):
        seen.update(kw)
        return retro.DumpOutcome(exit_code=0, produced=["frontend"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch)
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, [
        "debug", "retro", "dump",
        "src/melee/mn/mnvibration.c",
        "-f", "mnVibration_80248644",
        "--timeout", "1234",
    ])

    assert result.exit_code == 0, result.output
    assert seen["timeout"] == 1234


def test_launch_dump_uses_process_group_timeout_runner(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro
    import tools.mwcc_retro.setup as retro_setup

    melee_root = tmp_path / "melee"
    out_dir = tmp_path / "out"
    table = tmp_path / "table.json"
    launcher = tmp_path / "vendor" / "mwcc_retro_debugger.py"
    cadmic_script = tmp_path / "vendor" / "cadmic" / "pkg" / "mwcc_debugger.py"
    retrowin32_bin = tmp_path / "retrowin32"
    for path in (launcher, cadmic_script, table, retrowin32_bin):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fake\n")

    class SetupResult:
        pass

    setup_result = SetupResult()
    setup_result.retrowin32_bin = retrowin32_bin
    setup_result.cadmic_script = cadmic_script
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda *_args, **_kwargs: setup_result)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda *_args, **_kwargs: "mwcceppc.exe -c src/melee/mn/mnvibration.c -o out.o",
    )

    seen = {}

    def fake_run(cmd, *, cwd, timeout, env=None):
        seen["cmd"] = cmd
        seen["cwd"] = cwd
        seen["timeout"] = timeout
        seen["env"] = env
        return subprocess.CompletedProcess(
            cmd,
            0,
            "[retro] running intervention hook\n",
            "",
        )

    monkeypatch.setattr(retro, "_run_with_process_group_timeout", fake_run)

    outcome = retro._launch_dump(
        src="src/melee/mn/mnvibration.c",
        fn="mnVibration_80248644",
        phases="all",
        compiler="1.2.5n",
        out_dir=out_dir,
        table=table,
        melee_root=melee_root,
        gdb_py=str(tmp_path / "hook.py"),
        timeout=17,
    )

    assert outcome.exit_code == 0
    assert seen["timeout"] == 17
    assert seen["cwd"] == melee_root
    assert str(launcher) in seen["cmd"]
    assert str(retrowin32_bin) in seen["cmd"]
    assert (out_dir / "launch.log").read_text().startswith(
        "[retro] running intervention hook"
    )


def test_retro_dump_uses_explicit_melee_root_for_paths(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    repo = tmp_path / "worktree"
    (repo / "src" / "melee").mkdir(parents=True)
    (repo / "tools" / "mwcc_retro" / "tables").mkdir(parents=True)
    (repo / "tools" / "mwcc_retro" / "tables" / "gc_125n.json").write_text("{}\n")
    (repo / "configure.py").write_text("# fake checkout marker\n")
    seen = {}

    def fake_launch(**kw):
        seen.update(kw)
        return retro.DumpOutcome(exit_code=0, produced=["frontend"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch)
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, [
        "debug", "retro", "dump",
        "src/melee/mn/mndiagram.c",
        "-f", "mnDiagram_DrawCellNumber",
        "--melee-root", str(repo),
        "--output", "build/mwcc_retro/draw",
    ])

    assert result.exit_code == 0, result.output
    assert seen["melee_root"] == repo.resolve()
    assert seen["out_dir"] == repo.resolve() / "build" / "mwcc_retro" / "draw"
    assert seen["table"] == repo.resolve() / "tools" / "mwcc_retro" / "tables" / "gc_125n.json"
    provenance = json.loads((seen["out_dir"] / "provenance.json").read_text())
    assert provenance["melee_root"] == str(repo.resolve())


def test_retro_dump_125n_backend_routes_to_full_trace(
    monkeypatch,
    tmp_path,
):
    import src.cli.debug.retro as retro
    trace = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"
        ).read_text()
    )
    seen = {}

    def fake_backend_trace(**kw):
        seen["backend"] = kw
        kw["out_dir"].mkdir(parents=True, exist_ok=True)
        return retro.BackendOutcome(exit_code=0, trace=trace, fidelity=None)

    def fail_launch(**_kw):
        raise AssertionError("1.2.5n backend-only dump should use full tracer")

    monkeypatch.setattr(retro, "_launch_dump", fail_launch)
    monkeypatch.setattr(retro, "_run_backend_trace", fake_backend_trace)
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, [
        "debug", "retro", "dump",
        "src/melee/mn/mnvibration.c",
        "-f", "mnVibration_80248644",
        "--compiler", "1.2.5n",
        "--phases", "backend",
        "-O", str(tmp_path),
    ])

    assert result.exit_code == 0, result.output
    assert seen["backend"]["src"] == "src/melee/mn/mnvibration.c"
    assert seen["backend"]["fn"] == "mnVibration_80248644"
    assert seen["backend"]["verify_debug"] is False
    assert (tmp_path / "backend-trace.v1.json").exists()
    assert (tmp_path / "regalloc-summary.txt").exists()
    assert (tmp_path / "backend-summary.txt").exists()
    assert not (tmp_path / "backend-source-attribution.json").exists()


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
        melee_root=tmp_path,
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
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)
    r = runner.invoke(app, ["debug", "retro", "dump",
                            "src/melee/mn/mnvibration.c", "-f", "mnVibration_80248644",
                            "--gdb-py", str(hook)])
    assert r.exit_code == 0
    assert seen["gdb_py"].endswith("hook.py")


def test_retro_dump_gdb_py_missing_hook_exit_2(monkeypatch):
    import src.cli.debug.retro as retro
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)
    r = runner.invoke(app, ["debug", "retro", "dump",
                            "src/melee/mn/mnvibration.c", "-f", "x",
                            "--gdb-py", "/no/such/hook.py"])
    assert r.exit_code == 2
