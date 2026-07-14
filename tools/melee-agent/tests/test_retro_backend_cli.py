import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()


def test_retro_backend_help_lists_exact_retail_language():
    r = runner.invoke(app, ["debug", "retro", "backend", "--help"])
    assert r.exit_code == 0
    assert "Gated retail GC/1.2.5n backend/regalloc trace command" in r.output
    assert "--verify-debug" in r.output


def test_retro_backend_candidate_help_lists_candidate_language():
    r = runner.invoke(app, ["debug", "retro", "backend-candidate", "--help"])
    assert r.exit_code == 0
    assert "Assemble a candidate retail GC/1.2.5n backend trace" in r.output
    assert "Diagnostic candidate output" in r.output
    assert "--one-pass" in r.output


def test_retro_verify_backend_help():
    r = runner.invoke(app, ["debug", "retro", "verify-backend", "--help"])
    assert r.exit_code == 0
    assert "Compare a retail backend trace to mwcc-debug" in r.output
    assert "--debug-pcdump" in r.output


def test_retro_probe_backend_map_help():
    r = runner.invoke(app, ["debug", "retro", "probe-backend-map", "--help"])
    assert r.exit_code == 0
    assert "Probe retail GC/1.2.5n backend map candidates" in r.output
    assert "--static-only" in r.output
    assert "raw-pe-cfg.v1.jsonl" in r.output
    assert "raw-ghidra-crosscheck.v1.json" in r.output


def test_retro_probe_backend_ig_help():
    r = runner.invoke(app, ["debug", "retro", "probe-backend-ig", "--help"])
    assert r.exit_code == 0
    assert (
        "Probe retail GC/1.2.5n partial IG/order/coalesce/observed-color snapshots"
        in r.output
    )


def test_retro_probe_backend_pcode_help():
    r = runner.invoke(app, ["debug", "retro", "probe-backend-pcode", "--help"])
    assert r.exit_code == 0
    assert "Probe retail GC/1.2.5n backend PCode/block snapshots" in r.output


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


def test_backend_command_rejects_success_without_trace(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    def fake_run_backend_trace(**kwargs):
        kwargs["out_dir"].mkdir(parents=True, exist_ok=True)
        return retro.BackendOutcome(exit_code=0, trace=None, fidelity=None)

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
    assert r.exit_code == 2
    assert "backend trace runner returned success without a trace" in r.output
    assert not (tmp_path / "backend-trace.v1.json").exists()


def test_backend_command_rejects_success_without_required_outputs(
    monkeypatch,
    tmp_path,
):
    import src.cli.debug.retro as retro

    fixture = (
        Path(__file__).resolve().parents[3]
        / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"
    )
    trace = json.loads(fixture.read_text())

    def fake_run_backend_trace(**kwargs):
        return retro.BackendOutcome(exit_code=0, trace=trace, fidelity=None)

    def fake_write_backend_outputs(*_args, **_kwargs):
        return None

    monkeypatch.setattr(retro, "_run_backend_trace", fake_run_backend_trace)
    monkeypatch.setattr(retro, "_write_backend_outputs", fake_write_backend_outputs)
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

    assert r.exit_code == 2
    assert (
        "backend trace command reported success but did not produce "
        "required output(s): backend-trace.v1.json, regalloc-summary.txt, "
        "backend-summary.txt"
    ) in r.output


def test_backend_command_reports_runtime_errors(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    def fail_backend(**_kwargs):
        raise RuntimeError("backend event launcher produced no backend-events.v1.jsonl")

    monkeypatch.setattr(retro, "_run_backend_trace", fail_backend)
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
    assert r.exit_code == 2
    assert "backend event launcher produced no backend-events.v1.jsonl" in r.output


def test_backend_candidate_command_writes_candidate_outputs(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    trace = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"
        ).read_text()
    )
    calls = []

    def fake_candidate(**kwargs):
        calls.append(kwargs)
        out = kwargs["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        return retro.BackendCandidateOutcome(exit_code=0, trace=trace)

    monkeypatch.setattr(retro, "_run_backend_candidate_trace", fake_candidate)
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)

    r = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "backend-candidate",
            "src/melee/test/unit.c",
            "-f",
            "test_fn",
            "-O",
            str(tmp_path),
            "--one-pass",
        ],
    )

    assert r.exit_code == 0, r.output
    assert calls
    assert calls[0]["one_pass"] is True
    assert (tmp_path / "backend-trace.candidate.v1.json").exists()
    assert (tmp_path / "regalloc-summary.candidate.txt").exists()
    assert (tmp_path / "backend-summary.candidate.txt").exists()
    assert not (tmp_path / "backend-trace.v1.json").exists()
    assert "backend candidate trace:" in r.output


def test_probe_backend_map_command_writes_probe_without_backend_trace(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    calls = []

    def fake_probe(**kwargs):
        calls.append(kwargs)
        out = kwargs["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "backend-map-candidates.json").write_text('{"compiler":"1.2.5n"}\n')
        (out / "backend-map-probe.json").write_text('{"schema_version":"mwcc-retro-backend-map-probe.v1"}\n')
        (out / "backend-map-evidence.json").write_text('{"promotable_entries":{}}\n')
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_run_backend_map_probe", fake_probe)

    r = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "probe-backend-map",
            "src/melee/test/unit.c",
            "-f",
            "test_fn",
            "-O",
            str(tmp_path),
        ],
    )
    assert r.exit_code == 0, r.output
    assert calls and calls[0]["static_only"] is False
    assert (tmp_path / "backend-map-candidates.json").exists()
    assert (tmp_path / "backend-map-probe.json").exists()
    assert (tmp_path / "backend-map-evidence.json").exists()
    assert not (tmp_path / "backend-events.v1.jsonl").exists()
    assert not (tmp_path / "backend-trace.v1.json").exists()


def test_probe_backend_ig_command_writes_partial_events_without_trace(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    calls = []

    def fake_probe(**kwargs):
        calls.append(kwargs)
        out = kwargs["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        summary = out / "backend-ig-snapshot.json"
        events = out / "backend-ig-snapshot-events.v1.jsonl"
        summary.write_text('{"schema_version":"mwcc-retro-backend-ig-snapshot.v1"}\n')
        events.write_text('{"event":"function_start","name":"test_fn"}\n')
        return retro.BackendIgSnapshotOutcome(
            exit_code=0,
            summary_path=summary,
            events_path=events,
        )

    monkeypatch.setattr(retro, "_run_backend_ig_snapshot", fake_probe)

    r = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "probe-backend-ig",
            "src/melee/test/unit.c",
            "-f",
            "test_fn",
            "-O",
            str(tmp_path),
        ],
    )
    assert r.exit_code == 0, r.output
    assert calls
    assert "backend IG snapshot: " in r.output
    assert "backend IG events: " in r.output
    assert (tmp_path / "backend-ig-snapshot.json").exists()
    assert (tmp_path / "backend-ig-snapshot-events.v1.jsonl").exists()
    assert not (tmp_path / "backend-trace.v1.json").exists()
    assert not (tmp_path / "regalloc-summary.txt").exists()


def test_probe_backend_pcode_command_writes_partial_events_without_trace(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    calls = []

    def fake_probe(**kwargs):
        calls.append(kwargs)
        out = kwargs["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        summary = out / "backend-pcode-snapshot.json"
        events = out / "backend-pcode-snapshot-events.v1.jsonl"
        summary.write_text('{"schema_version":"mwcc-retro-backend-pcode-snapshot.v1"}\n')
        events.write_text('{"event":"function_start","name":"test_fn"}\n')
        return retro.BackendPcodeSnapshotOutcome(
            exit_code=0,
            summary_path=summary,
            events_path=events,
        )

    monkeypatch.setattr(retro, "_run_backend_pcode_snapshot", fake_probe)

    r = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "probe-backend-pcode",
            "src/melee/test/unit.c",
            "-f",
            "test_fn",
            "-O",
            str(tmp_path),
        ],
    )
    assert r.exit_code == 0, r.output
    assert calls
    assert "backend PCode snapshot: " in r.output
    assert "backend PCode events: " in r.output
    assert (tmp_path / "backend-pcode-snapshot.json").exists()
    assert (tmp_path / "backend-pcode-snapshot-events.v1.jsonl").exists()
    assert not (tmp_path / "backend-trace.v1.json").exists()
    assert not (tmp_path / "regalloc-summary.txt").exists()


def test_probe_backend_map_static_only_skips_live_launcher(monkeypatch, tmp_path):
    from tools.mwcc_retro.backend_lifetime_audit import (
        publish_static_backend_bundle,
    )

    import src.cli.debug.retro as retro
    from src.mwcc_debug.ghidra_mwcc_setup import EXPECTED_COMPILER_SHA256

    calls = []

    def fake_probe(**kwargs):
        calls.append(kwargs)
        kwargs["out_dir"].mkdir(parents=True, exist_ok=True)
        publish_static_backend_bundle(
            kwargs["out_dir"],
            {
                "raw-pe-cfg.v1.jsonl": b"{}\n",
                "raw-ghidra-crosscheck.v1.json": b"{}\n",
                "backend-map-candidates.json": b"{}\n",
            },
            compiler_sha256=EXPECTED_COMPILER_SHA256,
        )
        return retro.DumpOutcome(exit_code=0, produced=["static"], missing=[])

    monkeypatch.setattr(retro, "_run_backend_map_probe", fake_probe)

    r = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "probe-backend-map",
            "src/melee/test/unit.c",
            "-f",
            "test_fn",
            "--static-only",
            "-O",
            str(tmp_path),
        ],
    )
    assert r.exit_code == 0, r.output
    assert calls and calls[0]["static_only"] is True
    assert "raw PE CFG:" in r.output
    assert "raw/Ghidra cross-check:" in r.output


def test_static_backend_map_builds_candidates_inside_publication_transaction(
    monkeypatch, tmp_path
):
    from tools.mwcc_retro import backend_discovery

    import src.cli.debug.retro as retro

    order = []

    observed = {}

    def fake_static(*, melee_root, out_dir, candidate_payload):
        order.append("raw-crosscheck")
        observed["candidate_payload"] = json.loads(candidate_payload)

    def fake_candidates(_exe):
        order.append("candidates")
        return {"compiler": "1.2.5n"}

    monkeypatch.setattr(retro, "_run_static_backend_map_audit", fake_static)
    monkeypatch.setattr(
        backend_discovery,
        "build_gc125n_backend_candidate_report",
        fake_candidates,
    )
    root = tmp_path / "root"
    out = tmp_path / "out"
    (root / "build/compilers/GC/1.2.5n").mkdir(parents=True)
    (root / "build/compilers/GC/1.2.5n/mwcceppc.exe").write_bytes(b"PE")

    outcome = retro._run_backend_map_probe(
        src="unit.c",
        fn="unit",
        out_dir=out,
        static_only=True,
        melee_root=root,
    )

    assert outcome.exit_code == 0
    assert order == ["candidates", "raw-crosscheck"]
    assert observed["candidate_payload"] == {"compiler": "1.2.5n"}
    assert not (out / "backend-map-candidates.json").exists()


def test_transient_ghidra_inventory_is_exact_hash_and_deleted(
    monkeypatch,
):
    import subprocess

    import src.cli.debug.retro as retro
    from src.mwcc_debug.ghidra_mwcc_setup import EXPECTED_COMPILER_SHA256

    repo = Path(__file__).resolve().parents[3]
    project = repo / "tools/mwcc_debug/ghidra_project"
    observed = {}
    monkeypatch.setattr(
        retro,
        "setup_mwcc_ghidra",
        lambda **_kwargs: SimpleNamespace(
            compiler_sha256=EXPECTED_COMPILER_SHA256,
            project_name="mwcceppc",
            program_path="/mwcceppc.exe",
            project_dir=project,
            headless_path=Path("/ghidra/analyzeHeadless"),
        ),
    )

    def fake_runner(command, **_kwargs):
        inventory = Path(command[-1])
        observed["temporary"] = inventory.parent
        inventory.write_text(
            json.dumps(
                {
                    "record_kind": "metadata",
                    "schema_version": "mwcc-ghidra-raw-crosscheck.v1",
                    "compiler_sha256": EXPECTED_COMPILER_SHA256,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        assert command[-2] == EXPECTED_COMPILER_SHA256
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(retro, "_run_with_process_group_timeout", fake_runner)
    inventory = retro._load_transient_ghidra_inventory(melee_root=repo)
    assert inventory.compiler_sha256 == EXPECTED_COMPILER_SHA256
    assert not observed["temporary"].exists()


def test_transient_ghidra_inventory_is_deleted_after_parse_failure(monkeypatch):
    import subprocess

    import src.cli.debug.retro as retro
    from src.mwcc_debug.ghidra_mwcc_setup import EXPECTED_COMPILER_SHA256

    repo = Path(__file__).resolve().parents[3]
    project = repo / "tools/mwcc_debug/ghidra_project"
    observed = {}
    monkeypatch.setattr(
        retro,
        "setup_mwcc_ghidra",
        lambda **_kwargs: SimpleNamespace(
            compiler_sha256=EXPECTED_COMPILER_SHA256,
            project_name="mwcceppc",
            program_path="/mwcceppc.exe",
            project_dir=project,
            headless_path=Path("/ghidra/analyzeHeadless"),
        ),
    )

    def fake_runner(command, **_kwargs):
        inventory = Path(command[-1])
        observed["temporary"] = inventory.parent
        inventory.write_text("not-json\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(retro, "_run_with_process_group_timeout", fake_runner)
    try:
        retro._load_transient_ghidra_inventory(melee_root=repo)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid transient inventory was accepted")
    assert not observed["temporary"].exists()


def test_probe_backend_map_reports_unexpected_failure(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    def fail_probe(**_kwargs):
        raise FileNotFoundError("mwcceppc.exe")

    monkeypatch.setattr(retro, "_run_backend_map_probe", fail_probe)

    r = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "probe-backend-map",
            "src/melee/test/unit.c",
            "-f",
            "test_fn",
            "-O",
            str(tmp_path),
        ],
    )

    assert r.exit_code == 2
    assert "backend map probe failed: FileNotFoundError: mwcceppc.exe" in r.output
    assert "Traceback" not in r.output
