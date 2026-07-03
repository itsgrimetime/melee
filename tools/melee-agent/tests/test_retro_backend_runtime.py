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
