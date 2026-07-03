import json
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest


def test_run_backend_trace_invokes_parity_before_launcher(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    fixture = (
        Path(__file__).resolve().parents[3]
        / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"
    )
    trace = json.loads(fixture.read_text())
    calls = []

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **kw: calls.append("parity") or {"matched": True},
    )
    monkeypatch.setattr(
        retro,
        "_launch_backend_events",
        lambda **kw: calls.append("launch") or tmp_path / "events.jsonl",
    )
    monkeypatch.setattr(
        retro.backend_events, "load_events", lambda path: calls.append("load") or []
    )
    monkeypatch.setattr(
        retro.backend_events,
        "normalize_events",
        lambda *args, **kw: calls.append("normalize") or trace,
    )

    outcome = retro._run_backend_trace(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        verify_debug=False,
        melee_root=Path.cwd(),
    )
    assert outcome.exit_code == 0
    assert outcome.trace == trace
    assert calls == ["parity", "launch", "load", "normalize"]


def test_run_backend_trace_reports_failed_parity_detail(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **kw: {
            "matched": False,
            "reference": {
                "path": "/tmp/reference.o",
                "size": 12,
                "sha256": "a" * 64,
            },
            "retro": {
                "path": "/tmp/retro.o",
                "size": 13,
                "sha256": "b" * 64,
            },
        },
    )
    with pytest.raises(RuntimeError) as excinfo:
        retro._run_backend_trace(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            verify_debug=False,
            melee_root=Path.cwd(),
        )
    message = str(excinfo.value)
    assert "backend object parity mismatch" in message
    assert "/tmp/reference.o" in message
    assert "size=12" in message
    assert "sha256=" + ("a" * 64) in message
    assert "/tmp/retro.o" in message
    assert "size=13" in message
    assert "sha256=" + ("b" * 64) in message


def test_run_object_parity_wraps_reference_compile_failure(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    monkeypatch.setattr(
        retro_setup,
        "ensure_for_root",
        lambda *_args, **_kwargs: SimpleNamespace(
            retrowin32_bin=tmp_path / "retrowin32"
        ),
    )
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda *_args, **_kwargs: "build/compilers/GC/1.2.5n/mwcceppc.exe -c src.c -o old.o",
    )

    def fail_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(
            7,
            cmd,
            output=b"x" * 2000 + b"\nreference stdout tail",
            stderr=b"y" * 2000 + b"\nreference stderr tail",
        )

    monkeypatch.setattr(subprocess, "run", fail_run)

    with pytest.raises(RuntimeError) as excinfo:
        retro._run_object_parity_for_backend(
            src="src/melee/test/unit.c", melee_root=tmp_path
        )
    message = str(excinfo.value)
    assert "backend object parity reference compile failed" in message
    assert "exit code: 7" in message
    assert "mwcceppc.exe" in message
    assert "reference stdout tail" in message
    assert "reference stderr tail" in message


def test_launch_backend_events_writes_launch_log_on_nonzero(monkeypatch, tmp_path):
    import subprocess

    import pytest
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )

    def fake_run(cmd, **kwargs):
        assert kwargs["env"]["RETRO_SOURCE"] == "src/melee/test/unit.c"
        assert kwargs["env"]["RETRO_FUNCTION"] == "test_fn"
        (tmp_path / "backend-events.v1.jsonl").write_text('{"event":"backend_marker"}\n')
        return subprocess.CompletedProcess(cmd, 7, stdout="launcher stdout\n", stderr="launcher stderr\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="backend event launcher failed"):
        retro._launch_backend_events(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    launch_log = tmp_path / "launch.log"
    log_text = launch_log.read_text()
    log_lines = log_text.splitlines()
    assert log_lines[0].startswith("COMMAND: ")
    assert "mwcc_retro_debugger.py" in log_lines[0]
    assert "--phases backend" in log_lines[0]
    assert "--compiler 1.2.5n" in log_lines[0]
    assert log_lines[1] == "RETRO_SOURCE: src/melee/test/unit.c"
    assert log_lines[2] == "RETRO_FUNCTION: test_fn"
    assert log_lines[3] == "EXIT: 7"
    assert "STDOUT:" in log_text
    assert "launcher stdout" in log_text
    assert "STDERR:" in log_text
    assert "launcher stderr" in log_text
    assert not (tmp_path / "backend-events.v1.jsonl").exists()


def test_launch_backend_events_deletes_partial_events_on_abort(monkeypatch, tmp_path):
    import subprocess

    import pytest
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )

    def fake_run(cmd, **kwargs):
        (tmp_path / "backend-events.v1.jsonl").write_text('{"event":"backend_marker"}\n')
        return subprocess.CompletedProcess(cmd, 0, stdout="[retro] ABORT: missing colorgraph\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="backend event launcher aborted"):
        retro._launch_backend_events(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert not (tmp_path / "backend-events.v1.jsonl").exists()
    log_text = (tmp_path / "launch.log").read_text()
    log_lines = log_text.splitlines()
    assert log_lines[0].startswith("COMMAND: ")
    assert log_lines[1] == "RETRO_SOURCE: src/melee/test/unit.c"
    assert log_lines[2] == "RETRO_FUNCTION: test_fn"
    assert log_lines[3] == "EXIT: 0"
    assert "[retro] ABORT: missing colorgraph" in log_text


def test_launch_backend_events_writes_launch_log_on_timeout(monkeypatch, tmp_path):
    import subprocess

    import pytest
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )

    def fake_run(cmd, **kwargs):
        (tmp_path / "backend-events.v1.jsonl").write_text('{"event":"backend_marker"}\n')
        raise subprocess.TimeoutExpired(
            cmd,
            timeout=600,
            output="timeout stdout\n",
            stderr="timeout stderr\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="backend event launcher timed out"):
        retro._launch_backend_events(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    log_text = (tmp_path / "launch.log").read_text()
    log_lines = log_text.splitlines()
    assert log_lines[0].startswith("COMMAND: ")
    assert log_lines[1] == "RETRO_SOURCE: src/melee/test/unit.c"
    assert log_lines[2] == "RETRO_FUNCTION: test_fn"
    assert log_lines[3] == "EXIT: timeout after 600s"
    assert "timeout stdout" in log_text
    assert "timeout stderr" in log_text
    assert not (tmp_path / "backend-events.v1.jsonl").exists()


def test_launch_backend_events_writes_launch_log_on_oserror(monkeypatch, tmp_path):
    import subprocess

    import pytest
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )

    def fake_run(cmd, **kwargs):
        (tmp_path / "backend-events.v1.jsonl").write_text('{"event":"backend_marker"}\n')
        raise OSError("spawn failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="backend event launcher failed"):
        retro._launch_backend_events(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    log_text = (tmp_path / "launch.log").read_text()
    log_lines = log_text.splitlines()
    assert log_lines[0].startswith("COMMAND: ")
    assert log_lines[1] == "RETRO_SOURCE: src/melee/test/unit.c"
    assert log_lines[2] == "RETRO_FUNCTION: test_fn"
    assert log_lines[3] == "EXIT: OSError: spawn failed"
    assert not (tmp_path / "backend-events.v1.jsonl").exists()
