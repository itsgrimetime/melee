import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app
from src.mwcc_debug.ghidra_mwcc_setup import (
    EXPECTED_COMPILER_SHA256,
    MwccGhidraSetupError,
    MwccGhidraSetupResult,
)

runner = CliRunner()


def test_retro_help_lists_subcommands():
    r = runner.invoke(app, ["debug", "retro", "--help"])
    assert r.exit_code == 0
    assert "setup" in r.output and "dump" in r.output and "verify" in r.output
    assert "ghidra-setup" in r.output


def _ghidra_setup_result(melee_root: Path, **changes) -> MwccGhidraSetupResult:
    values = {
        "status": "imported",
        "ghidra_install": Path("/opt/ghidra"),
        "headless_path": Path("/opt/ghidra/support/analyzeHeadless"),
        "native_decompiler_path": Path(
            "/opt/ghidra/Ghidra/Features/Decompiler/os/mac_arm_64/decompile"
        ),
        "compiler_path": melee_root / "build/compilers/GC/1.2.5n/mwcceppc.exe",
        "compiler_sha256": EXPECTED_COMPILER_SHA256,
        "project_dir": melee_root / "tools/mwcc_debug/ghidra_project",
        "project_name": "mwcceppc",
        "program_path": "/mwcceppc.exe",
        "function_count": 3248,
        "elapsed_seconds": 82.125,
        "quarantined_paths": (),
    }
    values.update(changes)
    return MwccGhidraSetupResult(**values)


def test_retro_ghidra_setup_passes_exact_defaults_and_resolves_relative_project(
    monkeypatch,
    tmp_path,
):
    import src.cli.debug.retro as retro

    melee_root = tmp_path / "melee"
    seen = {}

    def fake_setup(**kwargs):
        seen.update(kwargs)
        return _ghidra_setup_result(
            melee_root,
            project_dir=kwargs["project_dir"],
        )

    monkeypatch.setattr(retro, "_resolve_melee_root", lambda _root=None: melee_root)
    monkeypatch.setattr(retro, "setup_mwcc_ghidra", fake_setup, raising=False)

    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "ghidra-setup",
            "--project-dir",
            "build/audit-project",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen == {
        "melee_root": melee_root,
        "project_dir": melee_root / "build/audit-project",
        "analysis_timeout": 300,
        "wall_timeout": 420,
        "repair": False,
    }
    assert "status: imported" in result.output
    assert f"compiler SHA-256: {EXPECTED_COMPILER_SHA256}" in result.output
    assert "function count: 3248" in result.output
    assert f"project: {melee_root / 'build/audit-project'}" in result.output
    assert "Ghidra: /opt/ghidra" in result.output
    assert "native decompiler:" in result.output
    assert "elapsed seconds: 82.125" in result.output
    assert "quarantine paths: none" in result.output


def test_retro_ghidra_setup_json_is_stable_sorted_result_schema(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    melee_root = tmp_path / "melee"
    expected = _ghidra_setup_result(melee_root)
    monkeypatch.setattr(retro, "_resolve_melee_root", lambda _root=None: melee_root)
    monkeypatch.setattr(retro, "setup_mwcc_ghidra", lambda **_kwargs: expected, raising=False)

    result = runner.invoke(app, ["debug", "retro", "ghidra-setup", "--json"])

    assert result.exit_code == 0, result.output
    assert result.output == json.dumps(expected.to_dict(), sort_keys=True) + "\n"


def test_retro_ghidra_setup_invalid_existing_project_prints_repair_retry(
    monkeypatch,
    tmp_path,
):
    import src.cli.debug.retro as retro

    melee_root = tmp_path / "melee"
    project_dir = melee_root / "build/broken audit"
    monkeypatch.setattr(retro, "_resolve_melee_root", lambda _root=None: melee_root)

    def fail_setup(**_kwargs):
        raise MwccGhidraSetupError(
            "invalid-existing-project",
            {"cause": "invalid-status-marker"},
        )

    monkeypatch.setattr(retro, "setup_mwcc_ghidra", fail_setup, raising=False)

    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "ghidra-setup",
            "--project-dir",
            str(project_dir),
            "--analysis-timeout",
            "17",
            "--wall-timeout",
            "23",
        ],
    )

    assert result.exit_code == 4
    assert "ghidra setup failed: invalid-existing-project" in result.output
    assert '"cause": "invalid-status-marker"' in result.output
    assert (
        "Retry: melee-agent debug retro ghidra-setup --repair --melee-root "
        f"{melee_root} --project-dir '{project_dir}' --analysis-timeout 17 "
        "--wall-timeout 23"
    ) in result.output


def test_retro_ghidra_setup_requires_positive_timeouts(monkeypatch):
    import src.cli.debug.retro as retro

    monkeypatch.setattr(
        retro,
        "setup_mwcc_ghidra",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("runner called")),
        raising=False,
    )

    for option in ("--analysis-timeout", "--wall-timeout"):
        result = runner.invoke(
            app,
            ["debug", "retro", "ghidra-setup", option, "0"],
        )
        assert result.exit_code == 2
        assert "x>=1" in result.output


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
    cadmic_script = tmp_path / "vendor" / "cadmic" / "pkg" / "mwcc_debugger.py"
    retrowin32_bin = tmp_path / "retrowin32"
    for path in (cadmic_script, table, retrowin32_bin):
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
        launch_log = (out_dir / "launch.log").read_text()
        assert "STATUS: running" in launch_log
        assert "RETRO_SOURCE: src/melee/mn/mnvibration.c" in launch_log
        assert "RETRO_FUNCTION: mnVibration_80248644" in launch_log
        assert f"RETRO_OUTPUT_DIR: {out_dir}" in launch_log
        assert "TIMEOUT_SECONDS: 17" in launch_log
        command_text = retro.shlex.join([str(part) for part in cmd])
        assert f"COMMAND: {command_text}" in launch_log
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
    assert seen["cmd"][1] == str(
        retro._PACKAGE_REPO / "tools" / "mwcc_retro" / "mwcc_retro_debugger.py"
    )
    assert str(retrowin32_bin) in seen["cmd"]
    assert seen["env"]["PYTHONPATH"].split(os.pathsep)[0] == str(retro._PACKAGE_REPO)
    launch_log = (out_dir / "launch.log").read_text()
    assert "STATUS: exited" in launch_log
    assert "EXIT: 0" in launch_log
    assert "[retro] running intervention hook" in launch_log


def test_launch_dump_timeout_retains_late_process_group_streams(
    monkeypatch,
    tmp_path,
):
    import src.cli.debug.retro as retro
    import tools.mwcc_retro.setup as retro_setup
    from src.mwcc_debug import diff_capture

    melee_root = tmp_path / "melee"
    out_dir = tmp_path / "out"
    table = tmp_path / "table.json"
    retrowin32_bin = tmp_path / "retrowin32"
    for path in (table, retrowin32_bin):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fake\n")

    class SetupResult:
        pass

    setup_result = SetupResult()
    setup_result.retrowin32_bin = retrowin32_bin
    monkeypatch.setattr(
        retro_setup,
        "ensure_for_root",
        lambda *_args, **_kwargs: setup_result,
    )
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda *_args, **_kwargs: "mwcceppc.exe -c input.c -o out.o",
    )

    class FakePipe:
        def close(self):
            pass

    class FakeProc:
        pid = 4321
        returncode = None
        stdout = FakePipe()
        stderr = FakePipe()

        def communicate(self, timeout):
            return (
                "launcher stdout\n",
                "[retro] waiting for gdb port 9001 lock: /tmp/retro.lock\n"
                "[retro] acquired gdb port 9001 lock: /tmp/retro.lock\n",
            )

        def wait(self, timeout):
            self.returncode = -9

        def kill(self):
            pass

    class OuterTimeoutWinsThread:
        def __init__(self, *, target, daemon):
            self.target = target
            self.alive = True
            self.join_count = 0

        def start(self):
            pass

        def join(self, timeout):
            self.join_count += 1
            if self.join_count == 2:
                self.target()
                self.alive = False

        def is_alive(self):
            return self.alive

    def fake_popen(cmd, cwd, env, stdout, stderr, text, start_new_session):
        return FakeProc()

    monkeypatch.setattr(diff_capture.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(diff_capture.threading, "Thread", OuterTimeoutWinsThread)
    monkeypatch.setattr(diff_capture, "_kill_process_tree", lambda *_args: None)
    monkeypatch.setattr(diff_capture, "_unreaped_wibo_timeout_note", lambda: "")

    outcome = retro._launch_dump(
        src="input.c",
        fn="target_fn",
        phases="frontend",
        compiler="1.2.5n",
        out_dir=out_dir,
        table=table,
        melee_root=melee_root,
        timeout=17,
    )

    assert outcome == retro.DumpOutcome(
        exit_code=2,
        produced=[],
        missing=["timeout"],
    )
    launch_log = (out_dir / "launch.log").read_text()
    assert "launcher stdout" in launch_log
    assert "[retro] waiting for gdb port 9001 lock:" in launch_log
    assert "[retro] acquired gdb port 9001 lock:" in launch_log


def test_launch_dump_failed_run_does_not_consume_retained_frontend_trace(
    monkeypatch,
    tmp_path,
):
    import src.cli.debug.retro as retro
    import tools.mwcc_retro.setup as retro_setup

    melee_root = tmp_path / "melee"
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    table = tmp_path / "table.json"
    retrowin32_bin = tmp_path / "retrowin32"
    for path in (table, retrowin32_bin):
        path.write_text("# fake\n")

    stale_trace = (
        "Starting function target_fn\n"
        "Dumping function target_fn after IRO_BuildflowGraph \n"
        "Flowgraph node 0  First=0, Last=0\n"
    )
    trace = out_dir / "iro-trace.txt"
    trace.write_text(stale_trace)

    class SetupResult:
        pass

    setup_result = SetupResult()
    setup_result.retrowin32_bin = retrowin32_bin
    monkeypatch.setattr(
        retro_setup,
        "ensure_for_root",
        lambda *_args, **_kwargs: setup_result,
    )
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda *_args, **_kwargs: "mwcceppc.exe -c input.c -o out.o",
    )
    monkeypatch.setattr(
        retro,
        "_run_with_process_group_timeout",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(
            cmd,
            1,
            "",
            "gdb failed\n",
        ),
    )

    outcome = retro._launch_dump(
        src="input.c",
        fn="target_fn",
        phases="frontend",
        compiler="1.2.5n",
        out_dir=out_dir,
        table=table,
        melee_root=melee_root,
    )

    assert outcome == retro.DumpOutcome(
        exit_code=2,
        produced=[],
        missing=["frontend"],
    )
    assert trace.read_text() == stale_trace
    assert not (out_dir / "iro-summary.txt").exists()
    assert not list(out_dir.glob("iro-*-*.txt"))


def test_port_lock_reports_contention_and_keeps_blocking_acquisition(
    monkeypatch,
    capsys,
):
    import fcntl

    from tools.mwcc_retro import mwcc_retro_debugger as debugger

    calls = []

    def fake_flock(_file, operation):
        calls.append(operation)
        if operation == fcntl.LOCK_EX | fcntl.LOCK_NB:
            raise BlockingIOError

    monkeypatch.setattr(fcntl, "flock", fake_flock)

    with debugger._port_lock():
        calls.append("yield")

    assert calls == [
        fcntl.LOCK_EX | fcntl.LOCK_NB,
        fcntl.LOCK_EX,
        "yield",
        fcntl.LOCK_UN,
    ]
    stderr = capsys.readouterr().err
    assert "[retro] waiting for gdb port 9001 lock:" in stderr
    assert "[retro] acquired gdb port 9001 lock:" in stderr


def test_main_holds_port_lock_across_complete_trace_lifecycle(monkeypatch, tmp_path):
    import shutil

    from tools.mwcc_retro import mwcc_retro_debugger as debugger

    events = []
    trace_tmp = tmp_path / "mwcc_retro_iro.txt"
    trace_tmp.write_text("stale trace\n")
    out_dir = tmp_path / "out"

    @contextmanager
    def fake_port_lock():
        events.append("lock enter")
        try:
            yield
        finally:
            events.append("lock exit")

    real_remove = os.remove

    def fake_remove(path):
        events.append("stale trace removal")
        real_remove(path)

    class FakeEmulator:
        def poll(self):
            return 0

    def fake_popen(_cmd):
        events.append("emulator")
        return FakeEmulator()

    def fake_run(_cmd, *, check, env):
        assert check is True
        assert env["RETRO_PORT"] == "9001"
        events.append("gdb")
        trace_tmp.write_text("fresh trace\n")

    real_copy = shutil.copy

    def fake_copy(src, dst):
        events.append("trace copy")
        return real_copy(src, dst)

    monkeypatch.setattr(debugger, "_TRACE_TMP", str(trace_tmp))
    monkeypatch.setattr(debugger, "_port_lock", fake_port_lock)
    monkeypatch.setattr(debugger.os, "remove", fake_remove)
    monkeypatch.setattr(debugger.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(debugger.subprocess, "run", fake_run)
    monkeypatch.setattr(debugger.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(shutil, "copy", fake_copy)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mwcc_retro_debugger.py",
            "-e",
            "retrowin32",
            "-a",
            "mwcceppc.exe input.c",
            "--table",
            "table.json",
            "--out",
            str(out_dir),
            "target_fn",
        ],
    )

    debugger.main()

    assert events == [
        "lock enter",
        "stale trace removal",
        "emulator",
        "gdb",
        "trace copy",
        "lock exit",
    ]
    assert (out_dir / "iro-trace.txt").read_text() == "fresh trace\n"


def test_retro_dump_uses_package_table_with_explicit_melee_root(monkeypatch, tmp_path):
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
    assert seen["table"] == retro.TABLES_DIR / "gc_125n.json"
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


def test_retro_dump_backend_rejects_success_without_required_outputs(
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

    def fake_backend_trace(**_kw):
        return retro.BackendOutcome(exit_code=0, trace=trace, fidelity=None)

    def fake_write_backend_outputs(*_args, **_kwargs):
        return None

    def fail_launch(**_kw):
        raise AssertionError("1.2.5n backend-only dump should use full tracer")

    monkeypatch.setattr(retro, "_launch_dump", fail_launch)
    monkeypatch.setattr(retro, "_run_backend_trace", fake_backend_trace)
    monkeypatch.setattr(retro, "_write_backend_outputs", fake_write_backend_outputs)
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, [
        "debug", "retro", "dump",
        "src/melee/mn/mnvibration.c",
        "-f", "mnVibration_80248644",
        "--compiler", "1.2.5n",
        "--phases", "backend",
        "-O", str(tmp_path),
    ])

    assert result.exit_code == 2
    assert (
        "backend trace command reported success but did not produce "
        "required output(s): backend-trace.v1.json, regalloc-summary.txt, "
        "backend-summary.txt"
    ) in result.output


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
