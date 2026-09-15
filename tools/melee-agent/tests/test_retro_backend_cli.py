import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()


def _synthetic_v2_assembly(tmp_path: Path):
    from tools.mwcc_retro import backend_trace_assembler

    from tests.test_retro_backend_trace_assembler import _v2_assembly_kwargs

    kwargs = _v2_assembly_kwargs(tmp_path)
    return (
        backend_trace_assembler.assemble_candidate_trace_v2(**kwargs),
        kwargs["candidate_object"],
        kwargs["struct_map"],
    )


def test_retro_backend_help_lists_exact_retail_language():
    r = runner.invoke(app, ["debug", "retro", "backend", "--help"])
    assert r.exit_code == 0
    assert "Generate an exact retail GC/1.2.5n backend/regalloc trace." in r.output
    assert "--verify-debug" in r.output


def test_retro_backend_candidate_help_lists_candidate_language():
    r = runner.invoke(app, ["debug", "retro", "backend-candidate", "--help"])
    assert r.exit_code == 0
    assert "Assemble a candidate retail GC/1.2.5n backend trace" in r.output
    assert "Diagnostic candidate output" in r.output
    assert "--one-pass" in r.output
    assert "--trace-version" in r.output


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


def test_backend_candidate_v2_synthetic_trusted_capture_publishes_atomic_artifacts(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro
    assembly, staging, table = _synthetic_v2_assembly(tmp_path)

    def fake_v2(**_kwargs):
        return retro.BackendCandidateV2Outcome(
            exit_code=0,
            trace=assembly.payload,
            candidate_object=staging,
        )

    monkeypatch.setattr(retro, "_run_backend_candidate_v2_trace", fake_v2)
    monkeypatch.setattr(retro, "_load_backend_v2_struct_map", lambda _root: table)
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "backend-candidate",
            "src/melee/test/unit.c",
            "-f",
            "target",
            "-O",
            str(out),
            "--one-pass",
            "--trace-version",
            "v2",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads((out / "backend-trace.v2.json").read_text())
    assert payload["schema_version"] == "mwcc-retro-backend-trace.v2"
    assert (out / "candidate-object.o").read_bytes() == staging.read_bytes()
    assert "compiler-object-bindings, pcode-to-code-range" in result.output
    assert not (out / "backend-trace.candidate.v1.json").exists()


def test_backend_candidate_v2_empty_installed_registry_refuses_without_artifact_loss(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    def fail_setup(*_args, **_kwargs):
        raise AssertionError("setup must not run before the installed proof preflight")

    monkeypatch.setattr(retro, "_ensure_setup", fail_setup)
    trace = tmp_path / "backend-trace.v2.json"
    candidate = tmp_path / "candidate-object.o"
    trace.write_bytes(b"old-trace\n")
    candidate.write_bytes(b"old-candidate")

    result = runner.invoke(
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
            "--trace-version",
            "v2",
        ],
    )

    assert result.exit_code == 2
    assert "backend trace v2 unavailable" in result.output
    assert "no promoted instrumentation proof" in result.output
    assert trace.read_bytes() == b"old-trace\n"
    assert candidate.read_bytes() == b"old-candidate"


def test_backend_candidate_v2_validation_failure_preserves_prior_artifacts(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    staging = tmp_path / "staging.o"
    staging.write_bytes(b"not-an-elf")
    old_trace = b"old-trace\n"
    old_candidate = b"old-candidate"
    out = tmp_path / "out"
    out.mkdir()
    (out / "backend-trace.v2.json").write_bytes(old_trace)
    (out / "candidate-object.o").write_bytes(old_candidate)

    def fake_v2(**_kwargs):
        return retro.BackendCandidateV2Outcome(
            exit_code=0,
            trace={"schema_version": "mwcc-retro-backend-trace.v2"},
            candidate_object=staging,
        )

    monkeypatch.setattr(retro, "_run_backend_candidate_v2_trace", fake_v2)
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)
    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "backend-candidate",
            "src/melee/test/unit.c",
            "-f",
            "test_fn",
            "-O",
            str(out),
            "--one-pass",
            "--trace-version",
            "v2",
        ],
    )

    assert result.exit_code == 2
    assert "backend trace v2 schema errors" in result.output
    assert (out / "backend-trace.v2.json").read_bytes() == old_trace
    assert (out / "candidate-object.o").read_bytes() == old_candidate


def test_backend_candidate_v2_never_replaces_different_immutable_candidate(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro
    assembly, staging, table = _synthetic_v2_assembly(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    old_trace = b"old-trace\n"
    old_candidate = b"different-candidate"
    (out / "backend-trace.v2.json").write_bytes(old_trace)
    (out / "candidate-object.o").write_bytes(old_candidate)

    monkeypatch.setattr(
        retro,
        "_run_backend_candidate_v2_trace",
        lambda **_kwargs: retro.BackendCandidateV2Outcome(0, assembly.payload, staging),
    )
    monkeypatch.setattr(retro, "_load_backend_v2_struct_map", lambda _root: table)
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)
    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "backend-candidate",
            "src/melee/test/unit.c",
            "-f",
            "target",
            "-O",
            str(out),
            "--one-pass",
            "--trace-version",
            "v2",
        ],
    )

    assert result.exit_code == 2
    assert "candidate-object.o is immutable" in result.output
    assert (out / "backend-trace.v2.json").read_bytes() == old_trace
    assert (out / "candidate-object.o").read_bytes() == old_candidate


def test_backend_candidate_v2_trace_publication_failure_rolls_back_new_candidate(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro
    assembly, staging, table = _synthetic_v2_assembly(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    old_trace = b"old-trace\n"
    (out / "backend-trace.v2.json").write_bytes(old_trace)
    original_replace = retro.os.replace

    def fail_trace(source, destination):
        if Path(destination).name == "backend-trace.v2.json":
            raise OSError("trace replace failed")
        original_replace(source, destination)

    monkeypatch.setattr(retro.os, "replace", fail_trace)
    monkeypatch.setattr(
        retro,
        "_run_backend_candidate_v2_trace",
        lambda **_kwargs: retro.BackendCandidateV2Outcome(0, assembly.payload, staging),
    )
    monkeypatch.setattr(retro, "_load_backend_v2_struct_map", lambda _root: table)
    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "backend-candidate",
            "src/melee/test/unit.c",
            "-f",
            "target",
            "-O",
            str(out),
            "--one-pass",
            "--trace-version",
            "v2",
        ],
    )

    assert result.exit_code == 2
    assert "trace replace failed" in result.output
    assert (out / "backend-trace.v2.json").read_bytes() == old_trace
    assert not (out / "candidate-object.o").exists()


def test_backend_candidate_v2_reverifies_mutated_object_to_frame_before_writes(
    monkeypatch, tmp_path
):
    import copy

    import src.cli.debug.retro as retro
    assembly, staging, table = _synthetic_v2_assembly(tmp_path)
    mutated = copy.deepcopy(assembly.payload)
    mutated["capabilities"].append("object-to-frame")
    mutated["capabilities"].sort()
    out = tmp_path / "out"

    monkeypatch.setattr(
        retro,
        "_run_backend_candidate_v2_trace",
        lambda **_kwargs: retro.BackendCandidateV2Outcome(
            0,
            mutated,
            staging,
        ),
    )
    monkeypatch.setattr(retro, "_load_backend_v2_struct_map", lambda _root: table)
    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "backend-candidate",
            "src/melee/test/unit.c",
            "-f",
            "target",
            "-O",
            str(out),
            "--one-pass",
            "--trace-version",
            "v2",
        ],
    )

    assert result.exit_code == 2
    assert "capabilities do not equal independently verified" in result.output
    assert not (out / "backend-trace.v2.json").exists()
    assert not (out / "candidate-object.o").exists()


def test_backend_candidate_v2_nonzero_valid_runner_never_publishes(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro
    assembly, staging, _table = _synthetic_v2_assembly(tmp_path)
    out = tmp_path / "out"
    monkeypatch.setattr(
        retro,
        "_run_backend_candidate_v2_trace",
        lambda **_kwargs: retro.BackendCandidateV2Outcome(7, assembly.payload, staging),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "backend-candidate",
            "src/melee/test/unit.c",
            "-f",
            "target",
            "-O",
            str(out),
            "--one-pass",
            "--trace-version",
            "v2",
        ],
    )

    assert result.exit_code == 2
    assert "nonzero exit 7" in result.output
    assert not (out / "backend-trace.v2.json").exists()
    assert not (out / "candidate-object.o").exists()


def test_backend_candidate_v2_rollback_reports_original_and_unlink_failures(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro
    assembly, staging, table = _synthetic_v2_assembly(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "backend-trace.v2.json").write_bytes(b"old-trace\n")
    original_replace = retro.os.replace

    def fail_trace(source, destination):
        if Path(destination).name == "backend-trace.v2.json":
            raise OSError("trace replace failed")
        original_replace(source, destination)

    original_unlink = Path.unlink

    def fail_candidate_unlink(path, *args, **kwargs):
        if path.name == "candidate-object.o":
            raise OSError("candidate unlink failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(retro.os, "replace", fail_trace)
    monkeypatch.setattr(Path, "unlink", fail_candidate_unlink)
    monkeypatch.setattr(
        retro,
        "_run_backend_candidate_v2_trace",
        lambda **_kwargs: retro.BackendCandidateV2Outcome(0, assembly.payload, staging),
    )
    monkeypatch.setattr(retro, "_load_backend_v2_struct_map", lambda _root: table)
    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "backend-candidate",
            "src/melee/test/unit.c",
            "-f",
            "target",
            "-O",
            str(out),
            "--one-pass",
            "--trace-version",
            "v2",
        ],
    )

    assert result.exit_code == 2
    assert "trace replace failed" in result.output
    assert "candidate unlink failed" in result.output
    assert (out / "backend-trace.v2.json").read_bytes() == b"old-trace\n"


def test_backend_candidate_v2_fsyncs_directory_after_both_durable_replaces(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro
    assembly, staging, table = _synthetic_v2_assembly(tmp_path)
    calls: list[Path] = []
    monkeypatch.setattr(retro, "_fsync_directory", lambda path: calls.append(path))
    monkeypatch.setattr(
        retro,
        "_run_backend_candidate_v2_trace",
        lambda **_kwargs: retro.BackendCandidateV2Outcome(0, assembly.payload, staging),
    )
    monkeypatch.setattr(retro, "_load_backend_v2_struct_map", lambda _root: table)
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "debug",
            "retro",
            "backend-candidate",
            "src/melee/test/unit.c",
            "-f",
            "target",
            "-O",
            str(out),
            "--one-pass",
            "--trace-version",
            "v2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [out.parent, out, out, out, out]


def test_backend_candidate_v2_final_fsync_failure_restores_prior_trace_and_candidate(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    assembly, staging, table = _synthetic_v2_assembly(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    trace_path = out / "backend-trace.v2.json"
    old_trace = b"old-trace\n"
    trace_path.write_bytes(old_trace)
    failed = False

    def fail_final_fsync(path):
        nonlocal failed
        if path == out and trace_path.read_bytes() != old_trace and not failed:
            failed = True
            raise OSError("final directory fsync failed")

    monkeypatch.setattr(retro, "_fsync_directory", fail_final_fsync)
    monkeypatch.setattr(retro, "_load_backend_v2_struct_map", lambda _root: table)

    with pytest.raises(OSError, match="final directory fsync failed"):
        retro._write_backend_v2_outputs(
            out,
            assembly.payload,
            staging,
            function="target",
            melee_root=tmp_path,
        )

    assert failed
    assert trace_path.read_bytes() == old_trace
    assert not (out / "candidate-object.o").exists()


def test_backend_candidate_v2_final_fsync_failure_removes_new_pair(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    assembly, staging, table = _synthetic_v2_assembly(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    trace_path = out / "backend-trace.v2.json"
    failed = False

    def fail_final_fsync(path):
        nonlocal failed
        if path == out and trace_path.exists() and not failed:
            failed = True
            raise OSError("final directory fsync failed")

    monkeypatch.setattr(retro, "_fsync_directory", fail_final_fsync)
    monkeypatch.setattr(retro, "_load_backend_v2_struct_map", lambda _root: table)

    with pytest.raises(OSError, match="final directory fsync failed"):
        retro._write_backend_v2_outputs(
            out,
            assembly.payload,
            staging,
            function="target",
            melee_root=tmp_path,
        )

    assert failed
    assert not trace_path.exists()
    assert not (out / "candidate-object.o").exists()


def test_backend_candidate_v2_combines_all_post_replace_rollback_failures(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    assembly, staging, table = _synthetic_v2_assembly(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    trace_path = out / "backend-trace.v2.json"
    trace_path.write_bytes(b"old-trace\n")
    original_replace = retro.os.replace
    replace_trace_calls = 0
    fsync_calls = 0

    def fail_restore_replace(source, destination):
        nonlocal replace_trace_calls
        if Path(destination) == trace_path:
            replace_trace_calls += 1
            if replace_trace_calls == 2:
                raise OSError("restore trace replace failed")
        original_replace(source, destination)

    def fail_final_and_restore_fsync(path):
        nonlocal fsync_calls
        if path == out:
            fsync_calls += 1
            if fsync_calls == 3:
                raise OSError("final directory fsync failed")
            if fsync_calls == 4:
                raise OSError("restore directory fsync failed")

    original_unlink = Path.unlink

    def fail_candidate_unlink(path, *args, **kwargs):
        if path.name == "candidate-object.o":
            raise OSError("candidate unlink failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(retro.os, "replace", fail_restore_replace)
    monkeypatch.setattr(retro, "_fsync_directory", fail_final_and_restore_fsync)
    monkeypatch.setattr(Path, "unlink", fail_candidate_unlink)
    monkeypatch.setattr(retro, "_load_backend_v2_struct_map", lambda _root: table)

    with pytest.raises(RuntimeError) as raised:
        retro._write_backend_v2_outputs(
            out,
            assembly.payload,
            staging,
            function="target",
            melee_root=tmp_path,
        )

    message = str(raised.value)
    assert "final directory fsync failed" in message
    assert "restore trace replace failed" in message
    assert "restore directory fsync failed" in message
    assert "candidate unlink failed" in message


def test_backend_candidate_v2_success_cleans_backup_and_fsyncs_cleanup(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    assembly, staging, table = _synthetic_v2_assembly(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "backend-trace.v2.json").write_bytes(b"old-trace\n")
    calls: list[Path] = []
    monkeypatch.setattr(retro, "_fsync_directory", lambda path: calls.append(path))
    monkeypatch.setattr(retro, "_load_backend_v2_struct_map", lambda _root: table)

    retro._write_backend_v2_outputs(
        out,
        assembly.payload,
        staging,
        function="target",
        melee_root=tmp_path,
    )

    assert calls == [out, out, out, out]
    assert not list(out.glob(".*.tmp"))


def test_backend_candidate_v2_reports_cleanup_failure_with_valid_final_pair(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    assembly, staging, table = _synthetic_v2_assembly(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "backend-trace.v2.json").write_bytes(b"old-trace\n")
    original_unlink = Path.unlink

    def fail_backup_cleanup(path, *args, **kwargs):
        if "rollback" in path.name:
            raise OSError("backup cleanup failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_backup_cleanup)
    monkeypatch.setattr(retro, "_load_backend_v2_struct_map", lambda _root: table)

    with pytest.raises(RuntimeError, match="committed but cleanup failed.*backup cleanup failed"):
        retro._write_backend_v2_outputs(
            out,
            assembly.payload,
            staging,
            function="target",
            melee_root=tmp_path,
        )

    assert (out / "candidate-object.o").read_bytes() == staging.read_bytes()
    assert json.loads((out / "backend-trace.v2.json").read_text())["schema_version"] == (
        "mwcc-retro-backend-trace.v2"
    )


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
    import src.cli.debug.retro as retro

    calls = []

    def fake_probe(**kwargs):
        calls.append(kwargs)
        kwargs["out_dir"].mkdir(parents=True, exist_ok=True)
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
