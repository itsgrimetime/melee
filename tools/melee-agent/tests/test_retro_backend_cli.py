import json
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()


def test_retro_backend_help_lists_exact_retail_language():
    r = runner.invoke(app, ["debug", "retro", "backend", "--help"])
    assert r.exit_code == 0
    assert "exact retail GC/1.2.5n backend/regalloc trace" in r.output
    assert "--verify-debug" in r.output


def test_retro_verify_backend_help():
    r = runner.invoke(app, ["debug", "retro", "verify-backend", "--help"])
    assert r.exit_code == 0
    assert "Compare a retail backend trace to mwcc-debug" in r.output


def test_backend_command_writes_trace_outputs(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    fixture = (
        Path(__file__).resolve().parents[3]
        / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"
    )
    trace = json.loads(fixture.read_text())

    def fake_run_backend_trace(**kwargs):
        out = kwargs["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        return retro.BackendOutcome(exit_code=0, trace=trace, fidelity=None)

    monkeypatch.setattr(retro, "_run_backend_trace", fake_run_backend_trace)
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)

    r = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "backend",
            "src/melee/test/unit.c",
            "-f",
            "test_fn",
            "-O",
            str(tmp_path),
        ],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "backend-trace.v1.json").exists()
    assert (tmp_path / "regalloc-summary.txt").exists()
    assert (tmp_path / "backend-summary.txt").exists()


def test_backend_launcher_returns_not_wired_after_parity(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    monkeypatch.setattr(
        retro, "_run_object_parity_for_backend", lambda **_kwargs: {"matched": True}
    )

    r = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "backend",
            "src/melee/test/unit.c",
            "-f",
            "test_fn",
            "-O",
            str(tmp_path),
        ],
    )
    assert r.exit_code == 2
    assert "backend event launcher requires validated 1.2.5n struct map" in r.output
