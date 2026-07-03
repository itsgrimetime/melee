import json
from pathlib import Path


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


def test_run_backend_trace_stops_on_failed_parity(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    monkeypatch.setattr(
        retro, "_run_object_parity_for_backend", lambda **kw: {"matched": False}
    )
    outcome = retro._run_backend_trace(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        verify_debug=False,
        melee_root=Path.cwd(),
    )
    assert outcome.exit_code == 2
    assert outcome.trace is None
