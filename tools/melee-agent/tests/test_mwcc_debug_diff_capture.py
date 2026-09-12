"""Tests for source input resolution used by debug inspect diff."""
from __future__ import annotations

import re
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.mwcc_debug.diff_capture as diff_capture
from src.mwcc_debug.diff_capture import (
    CompileFailure,
    DiffInput,
    _run_with_process_group_timeout,
    compile_source_variant,
    read_inspect_input_if_available,
    resolve_diff_input,
)


def test_resolve_existing_pcdump_path(tmp_path: Path) -> None:
    dump = tmp_path / "a.txt"
    dump.write_text("Starting function fn_test\n", encoding="utf-8")

    result = resolve_diff_input("A", str(dump), function="fn_test", melee_root=tmp_path)

    assert result.kind == "pcdump"
    assert result.path == dump
    assert result.label == "A"


def test_resolve_existing_source_path(tmp_path: Path) -> None:
    src = tmp_path / "candidate.c"
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")

    result = resolve_diff_input("B", str(src), function="fn_test", melee_root=tmp_path)

    assert result.kind == "source"
    assert result.path == src


def test_resolve_unknown_token_rejects_slug_for_mvp(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="scratch slug inputs are not supported"):
        resolve_diff_input("A", "abc12", function="fn_test", melee_root=tmp_path)


def test_compile_source_variant_invokes_pcdump_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(cmd, *, cwd, timeout, env=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.write_text("Starting function fn_test\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="wrote")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )

    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)
    text = compile_source_variant(
        diff_input,
        function="fn_test",
        melee_root=tmp_path,
        timeout=30,
    )

    assert text == "Starting function fn_test\n"
    cmd = captured["cmd"]
    assert cmd[:6] == [sys.executable, "-m", "src.cli", "debug", "dump", "local"]
    assert "--no-cache-sync" in cmd
    assert "--function" in cmd


def test_compile_source_variant_bounds_long_pcdump_output_label(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")
    long_label = "node-split-" + "group-promote-steering-candidate-" * 20
    captured_output_names: list[str] = []

    def fake_run(cmd, *, cwd, timeout, env=None):
        out_path = Path(cmd[cmd.index("--output") + 1])
        captured_output_names.append(out_path.name)
        assert len(out_path.name.encode("utf-8")) <= 180
        out_path.write_text("Starting function fn_test\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="wrote")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )

    diff_input = DiffInput(
        label=long_label,
        token=str(src),
        kind="source",
        path=src,
    )
    text = compile_source_variant(
        diff_input,
        function="fn_test",
        melee_root=tmp_path,
        timeout=30,
    )

    assert text == "Starting function fn_test\n"
    assert captured_output_names
    assert captured_output_names[0].endswith(".pcdump.txt")
    assert captured_output_names[0] != f"{long_label.lower()}.pcdump.txt"


def test_compile_source_variant_retries_pcdump_function_alias_on_missing_function(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void mnDiagram_DrawCellNumber(void) {}\n", encoding="utf-8")
    attempted: list[str] = []

    def fake_run(cmd, *, cwd, timeout, env=None):
        dump_function = cmd[cmd.index("--function") + 1]
        attempted.append(dump_function)
        if dump_function == "mnDiagram_DrawCellNumber":
            return SimpleNamespace(
                returncode=3,
                stdout="",
                stderr=(
                    "function 'mnDiagram_DrawCellNumber' not found in pcdump"
                ),
            )
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.write_text("Starting function mnDiagram_80241E78\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="wrote")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )

    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)
    text = compile_source_variant(
        diff_input,
        function="mnDiagram_DrawCellNumber",
        function_aliases=("mnDiagram_80241E78",),
        melee_root=tmp_path,
        timeout=30,
    )

    assert attempted == ["mnDiagram_DrawCellNumber", "mnDiagram_80241E78"]
    assert text == "Starting function mnDiagram_80241E78\n"


def test_compile_source_variant_reports_attempted_aliases_when_all_names_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void mnDiagram_DrawCellNumber(void) {}\n", encoding="utf-8")

    def fake_run(cmd, *, cwd, timeout, env=None):
        if "--function" not in cmd:
            out_path = Path(cmd[cmd.index("--output") + 1])
            out_path.write_text(
                (
                    "Starting function actual_candidate_name\n"
                    "Starting function helper_function\n"
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="wrote")
        dump_function = cmd[cmd.index("--function") + 1]
        return SimpleNamespace(
            returncode=3,
            stdout="",
            stderr=f"function {dump_function!r} not found in pcdump",
        )

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )

    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)
    with pytest.raises(CompileFailure) as exc:
        compile_source_variant(
            diff_input,
            function="mnDiagram_DrawCellNumber",
            function_aliases=("mnDiagram_80241E78",),
            melee_root=tmp_path,
            timeout=30,
        )

    diagnostic = str(exc.value)
    assert "attempted: mnDiagram_DrawCellNumber, mnDiagram_80241E78" in diagnostic
    assert (
        "pcdump functions from unfiltered candidate: "
        "actual_candidate_name, helper_function"
    ) in diagnostic
    assert "mnDiagram_DrawCellNumber" in diagnostic
    assert "mnDiagram_80241E78" in diagnostic


def test_compile_source_variant_can_compile_direct_same_tu_probe_with_unit_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    real_src.parent.mkdir(parents=True)
    original_text = "void fn_test(void) { int original = 1; }\n"
    real_src.write_text(original_text, encoding="utf-8")
    probe = tmp_path / "build" / "mwcc_debug_cache" / "probes" / "sample.c"
    probe.parent.mkdir(parents=True)
    probe.write_text("void fn_test(void) { int probe = 2; }\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(cmd, *, cwd, timeout, env=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        assert real_src.read_text(encoding="utf-8") == original_text
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.write_text("Starting function fn_test\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )

    diff_input = DiffInput(label="probe", token=str(probe), kind="source", path=probe)
    text = compile_source_variant(
        diff_input,
        function="fn_test",
        melee_root=tmp_path,
        timeout=30,
        unit_source=real_src,
    )

    assert text == "Starting function fn_test\n"
    cmd = captured["cmd"]
    assert Path(cmd[0]).name == "melee-agent"
    assert cmd[1:4] == ["debug", "dump", "local"]
    assert cmd[4] == str(probe)
    assert cmd[cmd.index("--unit-source") + 1] == str(real_src)
    assert real_src.read_text(encoding="utf-8") == original_text


def test_compile_source_variant_uses_process_group_timeout_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def forbidden_run(*args, **kwargs):
        raise AssertionError("compile_source_variant must kill the process group")

    def fake_group_run(cmd, *, cwd, timeout, env=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.write_text("Starting function fn_test\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", forbidden_run)
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_group_run,
    )

    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)
    text = compile_source_variant(
        diff_input,
        function="fn_test",
        melee_root=tmp_path,
        timeout=7,
    )

    assert text == "Starting function fn_test\n"
    assert captured["cmd"][:6] == [
        sys.executable,
        "-m",
        "src.cli",
        "debug",
        "dump",
        "local",
    ]
    assert captured["cwd"] == tmp_path
    assert captured["timeout"] == 7


def test_compile_source_variant_sets_child_hang_watchdog_before_parent_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(cmd, *, cwd, timeout, env):
        captured["env"] = env
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.write_text("Starting function fn_test\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.delenv("MWCC_DEBUG_HANG_TIMEOUT", raising=False)
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )

    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)
    compile_source_variant(
        diff_input,
        function="fn_test",
        melee_root=tmp_path,
        timeout=7,
    )

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["MWCC_DEBUG_HANG_TIMEOUT"] == "6"


def test_compile_source_variant_preserves_shorter_existing_child_watchdog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(cmd, *, cwd, timeout, env):
        captured["env"] = env
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.write_text("Starting function fn_test\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("MWCC_DEBUG_HANG_TIMEOUT", "3")
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )

    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)
    compile_source_variant(
        diff_input,
        function="fn_test",
        melee_root=tmp_path,
        timeout=30,
    )

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["MWCC_DEBUG_HANG_TIMEOUT"] == "3"


def test_compile_source_variant_stages_outside_repo_source_and_restores(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    real_src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    real_src.parent.mkdir(parents=True)
    original_text = (
        "int retained_global;\n\n"
        "void fn_test(void) { int original = 1; }\n\n"
        "void retained_helper(void) {}\n"
    )
    real_src.write_text(original_text, encoding="utf-8")
    report = tmp_path / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/mn/sample","functions":[{"name":"fn_test"}]}]}',
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text(
        "void generated_probe_helper(void) {}\n\n"
        "void fn_test(void) { int candidate = 2; }\n",
        encoding="utf-8",
    )

    def fake_run(cmd, *, cwd, timeout, env=None):
        staged = real_src.read_text(encoding="utf-8")
        assert "candidate = 2" in staged
        assert "retained_global" in staged
        assert "retained_helper" in staged
        assert "generated_probe_helper" not in staged
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.write_text("Starting function fn_test\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )

    diff_input = DiffInput(
        label="B",
        token=str(candidate),
        kind="source",
        path=candidate,
    )
    text = compile_source_variant(diff_input, function="fn_test", melee_root=tmp_path, timeout=30)

    assert text == "Starting function fn_test\n"
    assert real_src.read_text(encoding="utf-8") == original_text


def test_compile_source_variant_holds_repo_source_lock_through_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    real_src.parent.mkdir(parents=True)
    original_text = "void fn_test(void) { int original = 1; }\n"
    real_src.write_text(original_text, encoding="utf-8")
    report = tmp_path / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/mn/sample","functions":[{"name":"fn_test"}]}]}',
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text(
        "void fn_test(void) { int candidate = 2; }\n",
        encoding="utf-8",
    )

    locked = False
    events: list[str] = []

    class FakeLock:
        def __enter__(self):
            nonlocal locked
            locked = True
            events.append("lock-enter")

        def __exit__(self, exc_type, exc, tb):
            nonlocal locked
            assert real_src.read_text(encoding="utf-8") == original_text
            events.append("lock-exit")
            locked = False

    def fake_lock(
        root: Path,
        *,
        label: str = "mwcc source compile",
        timeout: float | None = None,
    ):
        assert root == tmp_path
        assert label == "mwcc source compile"
        assert timeout == 30
        return FakeLock()

    def fake_run(cmd, *, cwd, timeout, env=None):
        assert locked is True
        assert "candidate = 2" in real_src.read_text(encoding="utf-8")
        events.append("dump-local")
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.write_text("Starting function fn_test\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(diff_capture, "_acquire_repo_source_mutation_lock", fake_lock)
    monkeypatch.setattr(diff_capture, "_run_with_process_group_timeout", fake_run)

    diff_input = DiffInput(label="B", token=str(candidate), kind="source", path=candidate)
    text = compile_source_variant(
        diff_input,
        function="fn_test",
        melee_root=tmp_path,
        timeout=30,
    )

    assert text == "Starting function fn_test\n"
    assert events == ["lock-enter", "dump-local", "lock-exit"]
    assert real_src.read_text(encoding="utf-8") == original_text


def test_compile_source_variant_repo_source_lock_uses_checkdiff_lock_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fcntl = pytest.importorskip("fcntl")
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    original_text = "void fn_test(void) {}\n"
    src.write_text(original_text, encoding="utf-8")

    lock_dir = Path(tempfile.gettempdir()) / "melee-checkdiff-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    digest = diff_capture.hashlib.sha1(
        str(tmp_path.resolve()).encode(),
    ).hexdigest()[:12]
    lock_path = lock_dir / f"repo.{digest}.lock"
    held_lock = lock_path.open("w")

    def fake_run(*args, **kwargs):
        raise AssertionError("compile must wait for the shared repo lock first")

    monkeypatch.setattr(diff_capture, "_run_with_process_group_timeout", fake_run)

    try:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_EX)
        diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)
        with pytest.raises(TimeoutError, match="repo-wide mwcc source compile lock"):
            compile_source_variant(
                diff_input,
                function="fn_test",
                melee_root=tmp_path,
                timeout=0.01,
            )
    finally:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_UN)
        held_lock.close()

    assert src.read_text(encoding="utf-8") == original_text


def test_compile_source_variant_missing_target_function_fails_before_staging(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    real_src.parent.mkdir(parents=True)
    original_text = "void fn_test(void) { int original = 1; }\n"
    real_src.write_text(original_text, encoding="utf-8")
    report = tmp_path / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/mn/sample","functions":[{"name":"fn_test"}]}]}',
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void different_function(void) {}\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        raise AssertionError("missing-function candidates must not invoke dump local")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )

    diff_input = DiffInput(label="B", token=str(candidate), kind="source", path=candidate)
    with pytest.raises(ValueError, match="target function fn_test not found"):
        compile_source_variant(diff_input, function="fn_test", melee_root=tmp_path, timeout=30)

    assert real_src.read_text(encoding="utf-8") == original_text


def test_compile_source_variant_surfaces_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) { broken }\n", encoding="utf-8")

    def fake_run(cmd, *, cwd, timeout, env=None):
        return SimpleNamespace(returncode=1, stdout="", stderr="sample.c:1: error: expected ';'")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )

    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)
    with pytest.raises(CompileFailure) as exc:
        compile_source_variant(diff_input, function="fn_test", melee_root=tmp_path, timeout=30)

    assert exc.value.side == "A"
    assert "expected ';'" in exc.value.stderr


def test_read_inspect_skips_pcdump_input(tmp_path: Path) -> None:
    dump = tmp_path / "candidate.txt"
    dump.write_text("Starting function fn_test\n", encoding="utf-8")
    diff_input = DiffInput(label="A", token=str(dump), kind="pcdump", path=dump)

    assert read_inspect_input_if_available(
        diff_input,
        function="fn_test",
        melee_root=tmp_path / "repo",
        timeout=30,
    ) is None


def test_read_inspect_runs_workflow_for_candidate_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_test(void) {}\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(cmd, *, cwd, timeout, env=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            "FUNCTION: fn_test\nSTATEMENTS\n  return;\n",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )
    diff_input = DiffInput(label="B", token=str(candidate), kind="source", path=candidate)

    text = read_inspect_input_if_available(
        diff_input,
        function="fn_test",
        melee_root=repo,
        timeout=45,
    )

    assert text is not None
    assert "FUNCTION: fn_test" in text
    cmd = captured["cmd"]
    assert cmd[0] == "tools/workflow/mwcc-inspect.sh"
    assert re.fullmatch(r"inspect-[0-9a-f]{24}", cmd[cmd.index("--invocation-id") + 1])
    assert 0 < float(cmd[cmd.index("--deadline-seconds") + 1]) <= 45
    assert cmd[cmd.index("--function") + 1] == "fn_test"
    assert cmd[-1] == str(candidate)
    out_path = Path(cmd[cmd.index("--output") + 1])
    assert out_path.parent == repo / "build" / "mwcc_inspect" / "candidates"
    assert out_path.name.startswith(".b-candidate-")
    assert ".result.inspect-" in out_path.name
    assert captured["cwd"] == repo
    assert 0 < captured["timeout"] <= 45


def test_read_inspect_honors_caller_output_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_test(void) {}\n", encoding="utf-8")
    requested_output = tmp_path / "inspect" / "candidate-inspect.txt"
    captured: dict[str, object] = {}

    def fake_run(cmd, *, cwd, timeout, env=None):
        captured["cmd"] = cmd
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("FUNCTION: fn_test\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )
    diff_input = DiffInput(label="A", token=str(candidate), kind="source", path=candidate)

    text = read_inspect_input_if_available(
        diff_input,
        function="fn_test",
        melee_root=repo,
        timeout=30,
        output_path=requested_output,
    )

    assert text == "FUNCTION: fn_test\n"
    cmd = captured["cmd"]
    result_path = Path(cmd[cmd.index("--output") + 1])
    assert result_path.parent == requested_output.parent
    assert result_path.name.startswith(f".{requested_output.name}.result.inspect-")
    assert requested_output.read_text(encoding="utf-8") == "FUNCTION: fn_test\n"


def test_read_inspect_concurrent_outputs_never_cross_return_or_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path
    src = repo / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")
    canonical = repo / "build" / "mwcc_inspect" / "sample.txt"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("baseline\n", encoding="utf-8")
    both_started = threading.Barrier(2)
    first_returned = threading.Event()
    artifacts = {
        "inspect-concurrent-a": "FUNCTION: fn_test\nA\n",
        "inspect-concurrent-b": "FUNCTION: fn_test\nB\n",
    }

    def fake_run(cmd, *, cwd, timeout, env=None):
        invocation = cmd[cmd.index("--invocation-id") + 1]
        both_started.wait(timeout=2)
        if invocation.endswith("-b"):
            assert first_returned.wait(timeout=2)
        result_path = Path(cmd[cmd.index("--output") + 1])
        result_path.write_text(artifacts[invocation], encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )
    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)
    results: dict[str, str | None] = {}

    def worker(invocation: str) -> None:
        results[invocation] = read_inspect_input_if_available(
            diff_input,
            function="fn_test",
            melee_root=repo,
            timeout=10,
            output_path=canonical,
            invocation_id=invocation,
        )
        if invocation.endswith("-a"):
            first_returned.set()

    threads = [
        threading.Thread(target=worker, args=("inspect-concurrent-a",)),
        threading.Thread(target=worker, args=("inspect-concurrent-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive()

    assert results["inspect-concurrent-a"] == artifacts["inspect-concurrent-a"]
    assert results["inspect-concurrent-b"] == artifacts["inspect-concurrent-b"]
    assert canonical.read_text(encoding="utf-8") == artifacts["inspect-concurrent-a"]
    assert not list(canonical.parent.glob(f".{canonical.name}.result.*"))


def test_read_inspect_runs_workflow_for_repo_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path
    src = repo / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")
    out_dir = repo / "build" / "mwcc_inspect"
    out_dir.mkdir(parents=True)
    captured: dict[str, object] = {}

    class FakeProc:
        returncode = 0

        def __init__(self, cmd, cwd):
            captured["cmd"] = cmd
            captured["cwd"] = cwd

        def communicate(self, timeout: int):
            result_path = Path(captured["cmd"][captured["cmd"].index("--output") + 1])
            result_path.write_text(
                "FUNCTION: fn_test\nSTATEMENTS\n  return;\n",
                encoding="utf-8",
            )
            return "", ""

    def fake_popen(cmd, cwd, stdout, stderr, text, start_new_session, env=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["start_new_session"] = start_new_session
        captured["env"] = env
        return FakeProc(cmd, cwd)

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)

    text = read_inspect_input_if_available(
        diff_input,
        function="fn_test",
        melee_root=repo,
        timeout=30,
    )

    assert text is not None
    assert "FUNCTION: fn_test" in text
    cmd = captured["cmd"]
    assert cmd[0] == "tools/workflow/mwcc-inspect.sh"
    assert re.fullmatch(r"inspect-[0-9a-f]{24}", cmd[cmd.index("--invocation-id") + 1])
    assert 0 < float(cmd[cmd.index("--deadline-seconds") + 1]) <= 30
    assert cmd[cmd.index("--function") + 1] == "fn_test"
    result_path = Path(cmd[cmd.index("--output") + 1])
    assert result_path.parent == out_dir
    assert result_path.name.startswith(".sample.txt.result.inspect-")
    assert cmd[-1] == str(src)
    assert captured["start_new_session"] is True


def test_compile_source_variant_surfaces_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")

    def fake_run(cmd, *, cwd, timeout, env=None):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )

    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)
    with pytest.raises(CompileFailure) as exc:
        compile_source_variant(diff_input, function="fn_test", melee_root=tmp_path, timeout=30)

    assert exc.value.side == "A"
    assert exc.value.returncode == 124
    assert "timed out" in exc.value.stderr


def test_compile_source_variant_restores_staged_source_on_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    real_src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    real_src.parent.mkdir(parents=True)
    real_src.write_text("void fn_test(void) { int original = 1; }\n", encoding="utf-8")
    report = tmp_path / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/mn/sample","functions":[{"name":"fn_test"}]}]}',
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_test(void) { int candidate = 2; }\n", encoding="utf-8")

    def fake_run(cmd, *, cwd, timeout, env=None):
        assert real_src.read_text(encoding="utf-8") == candidate.read_text(encoding="utf-8")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )

    diff_input = DiffInput(label="B", token=str(candidate), kind="source", path=candidate)
    with pytest.raises(CompileFailure):
        compile_source_variant(diff_input, function="fn_test", melee_root=tmp_path, timeout=30)

    assert "original = 1" in real_src.read_text(encoding="utf-8")


def test_read_inspect_propagates_timeout_and_cancels_exact_invocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path
    src = repo / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")

    calls: list[tuple[list[str], float]] = []

    def fake_run(cmd, *, cwd, timeout, env=None):
        calls.append((cmd, timeout))
        if "--cancel" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )
    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)

    with pytest.raises(subprocess.TimeoutExpired):
        read_inspect_input_if_available(
            diff_input,
            function="fn_test",
            melee_root=repo,
            timeout=30,
            invocation_id="inspect-test-123",
        )

    assert len(calls) == 2
    run_cmd, run_timeout = calls[0]
    assert run_cmd[:4] == [
        "tools/workflow/mwcc-inspect.sh",
        "--invocation-id",
        "inspect-test-123",
        "--deadline-seconds",
    ]
    assert 0 < float(run_cmd[4]) <= 30
    assert run_timeout <= 30
    cancel_cmd, cancel_timeout = calls[1]
    assert cancel_cmd == [
        "tools/workflow/mwcc-inspect.sh",
        "--cancel",
        "inspect-test-123",
        "--cleanup-timeout",
        "15",
    ]
    assert cancel_timeout == 30


def test_read_inspect_cleanup_failure_remains_typed_timeout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    repo = tmp_path
    src = repo / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")
    def fake_run(cmd, *, cwd, timeout, env=None):
        if "--cancel" in cmd:
            return SimpleNamespace(
                returncode=124,
                stdout="",
                stderr="remote cancellation did not finish",
            )
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )
    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)

    with pytest.raises(subprocess.TimeoutExpired):
        read_inspect_input_if_available(
            diff_input,
            function="fn_test",
            melee_root=repo,
            timeout=30,
            invocation_id="inspect-test-cleanup-failure",
        )

    captured = capsys.readouterr()
    assert "timeout cleanup failed for inspect-test-cleanup-failure" in captured.err
    assert "remote cancellation did not finish" in captured.err


@pytest.mark.parametrize(
    ("returncode", "stderr"),
    [
        (124, "[mwcc-inspect] timeout-status=deadline invocation=typed-timeout\n"),
        (
            125,
            "taskkill failed\n"
            "[mwcc-inspect] timeout-status=cleanup-failed invocation=typed-timeout\n",
        ),
    ],
    ids=["deadline", "cleanup-failed"],
)
def test_read_inspect_shell_timeout_status_remains_typed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    returncode: int,
    stderr: str,
) -> None:
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")

    def fake_run(cmd, *, cwd, timeout, env=None):
        return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture._run_with_process_group_timeout",
        fake_run,
    )
    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)
    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        read_inspect_input_if_available(
            diff_input,
            function="fn_test",
            melee_root=tmp_path,
            timeout=30,
            invocation_id="typed-timeout",
        )
    assert exc_info.value.stderr == stderr


def test_process_group_timeout_bounds_hung_communicate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, object] = {}
    unblock = threading.Event()

    class FakePipe:
        def close(self) -> None:
            unblock.set()

    class FakeProc:
        pid = 4321
        returncode = None
        stdout = FakePipe()
        stderr = FakePipe()

        def communicate(self, timeout: float):
            calls["communicate_timeout"] = timeout
            unblock.wait(30)
            return "", ""

        def wait(self, timeout: int):
            calls["wait_timeout"] = timeout
            self.returncode = -signal.SIGKILL

        def kill(self):
            calls["kill"] = True

    def fake_popen(cmd, cwd, env, stdout, stderr, text, start_new_session):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        calls["start_new_session"] = start_new_session
        return FakeProc()

    def fake_killpg(pgid: int, sig: int) -> None:
        calls["killpg"] = (pgid, sig)

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("os.killpg", fake_killpg)

    with pytest.raises(subprocess.TimeoutExpired):
        _run_with_process_group_timeout(
            ["python", "-c", "hang"],
            cwd=tmp_path,
            timeout=0.01,
        )

    assert calls["communicate_timeout"] == 0.01
    assert calls["start_new_session"] is True
    assert calls["killpg"] == (4321, signal.SIGKILL)
    assert calls["wait_timeout"] == 5


def test_process_group_interrupt_cleans_up_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, object] = {"closed_pipes": [], "killpg": []}
    interrupt = KeyboardInterrupt("cancel")

    class FakePipe:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            calls["closed_pipes"].append(self.name)

    class FakeProc:
        pid = 4321
        returncode = None
        stdout = FakePipe("stdout")
        stderr = FakePipe("stderr")

        def wait(self, timeout: int) -> None:
            calls["wait_timeout"] = timeout

        def kill(self) -> None:
            calls["kill"] = True

    class FakeThread:
        def __init__(self, *, target, daemon: bool) -> None:
            calls["thread_target"] = target
            calls["thread_daemon"] = daemon

        def start(self) -> None:
            calls["thread_started"] = True

        def join(self, timeout: float) -> None:
            calls["thread_join_timeout"] = timeout
            raise interrupt

    def fake_popen(cmd, cwd, env, stdout, stderr, text, start_new_session):
        calls["start_new_session"] = start_new_session
        return FakeProc()

    def fake_getpgid(pid: int) -> int:
        assert pid == 4321
        return 4321

    def fake_killpg(pgid: int, sig: int) -> None:
        calls["killpg"].append((pgid, sig))

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(diff_capture.threading, "Thread", FakeThread)
    monkeypatch.setattr(diff_capture, "_descendant_pids", lambda root_pid: [])
    monkeypatch.setattr("os.getpgid", fake_getpgid)
    monkeypatch.setattr("os.killpg", fake_killpg)

    with pytest.raises(KeyboardInterrupt) as excinfo:
        _run_with_process_group_timeout(
            ["python", "-c", "hang"],
            cwd=tmp_path,
            timeout=10,
        )

    assert excinfo.value is interrupt
    assert calls["start_new_session"] is True
    assert calls["killpg"] == [(4321, signal.SIGKILL)]
    assert calls["closed_pipes"] == ["stdout", "stderr"]
    assert calls["wait_timeout"] == 5


@pytest.mark.parametrize("interrupt_stage", ["construction", "start"])
def test_process_group_thread_setup_interrupt_cleans_up_child(
    interrupt_stage: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, object] = {"closed_pipes": [], "killpg": []}
    interrupt = KeyboardInterrupt("cancel")

    class FakePipe:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            calls["closed_pipes"].append(self.name)

    class FakeProc:
        pid = 4321
        returncode = None
        stdout = FakePipe("stdout")
        stderr = FakePipe("stderr")

        def wait(self, timeout: int) -> None:
            calls["wait_timeout"] = timeout

    class FakeThread:
        def __init__(self, *, target, daemon: bool) -> None:
            if interrupt_stage == "construction":
                raise interrupt

        def start(self) -> None:
            if interrupt_stage == "start":
                raise interrupt

        def join(self, timeout: float) -> None:
            raise AssertionError("join should not run after thread setup interruption")

    def fake_popen(cmd, cwd, env, stdout, stderr, text, start_new_session):
        calls["start_new_session"] = start_new_session
        return FakeProc()

    def fake_getpgid(pid: int) -> int:
        assert pid == 4321
        return 4321

    def fake_killpg(pgid: int, sig: int) -> None:
        calls["killpg"].append((pgid, sig))

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(diff_capture.threading, "Thread", FakeThread)
    monkeypatch.setattr(diff_capture, "_descendant_pids", lambda root_pid: [])
    monkeypatch.setattr("os.getpgid", fake_getpgid)
    monkeypatch.setattr("os.killpg", fake_killpg)

    with pytest.raises(KeyboardInterrupt) as excinfo:
        _run_with_process_group_timeout(
            ["python", "-c", "hang"],
            cwd=tmp_path,
            timeout=10,
        )

    assert excinfo.value is interrupt
    assert calls["start_new_session"] is True
    assert calls["killpg"] == [(4321, signal.SIGKILL)]
    assert calls["closed_pipes"] == ["stdout", "stderr"]
    assert calls["wait_timeout"] == 5


@pytest.mark.parametrize(
    "cleanup_failure",
    ["kill_process_tree", "pipe_close", "wait", "fallback_kill"],
)
def test_process_group_interrupt_cleanup_failures_preserve_original_exception(
    cleanup_failure: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, object] = {"closed_pipes": []}
    interrupt = KeyboardInterrupt("cancel")

    class FakePipe:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            calls["closed_pipes"].append(self.name)
            if cleanup_failure == "pipe_close" and self.name == "stdout":
                raise RuntimeError("pipe close failed")

    class FakeProc:
        pid = 4321
        returncode = None
        stdout = FakePipe("stdout")
        stderr = FakePipe("stderr")

        def wait(self, timeout: int) -> None:
            calls["wait_timeout"] = timeout
            if cleanup_failure == "wait":
                raise RuntimeError("wait failed")
            if cleanup_failure == "fallback_kill":
                raise subprocess.TimeoutExpired(["python", "-c", "hang"], timeout)

        def kill(self) -> None:
            calls["kill"] = True
            if cleanup_failure == "fallback_kill":
                raise RuntimeError("kill failed")

    class FakeThread:
        def __init__(self, *, target, daemon: bool) -> None:
            pass

        def start(self) -> None:
            pass

        def join(self, timeout: float) -> None:
            raise interrupt

    def fake_popen(cmd, cwd, env, stdout, stderr, text, start_new_session):
        return FakeProc()

    def fake_kill_process_tree(pid, proc) -> None:
        calls["kill_process_tree"] = pid
        if cleanup_failure == "kill_process_tree":
            raise RuntimeError("process tree kill failed")

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(diff_capture.threading, "Thread", FakeThread)
    monkeypatch.setattr(diff_capture, "_kill_process_tree", fake_kill_process_tree)

    with pytest.raises(KeyboardInterrupt) as excinfo:
        _run_with_process_group_timeout(
            ["python", "-c", "hang"],
            cwd=tmp_path,
            timeout=10,
        )

    assert excinfo.value is interrupt
    assert calls["kill_process_tree"] == 4321
    assert calls["closed_pipes"] == ["stdout", "stderr"]
    assert calls["wait_timeout"] == 5
    assert ("kill" in calls) is (cleanup_failure == "fallback_kill")


def test_process_group_interrupt_after_timeout_does_not_clean_up_twice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, object] = {"closed_pipes": [], "join_timeouts": [], "waits": []}
    interrupt = KeyboardInterrupt("cancel")

    class FakePipe:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            calls["closed_pipes"].append(self.name)

    class FakeProc:
        pid = 4321
        returncode = None
        stdout = FakePipe("stdout")
        stderr = FakePipe("stderr")

        def wait(self, timeout: int) -> None:
            calls["waits"].append(timeout)

    class FakeThread:
        def __init__(self, *, target, daemon: bool) -> None:
            pass

        def start(self) -> None:
            pass

        def join(self, timeout: float) -> None:
            calls["join_timeouts"].append(timeout)
            if timeout == 1:
                raise interrupt

        def is_alive(self) -> bool:
            return True

    def fake_popen(cmd, cwd, env, stdout, stderr, text, start_new_session):
        return FakeProc()

    def fake_kill_process_tree(pid, proc) -> None:
        calls.setdefault("cleanup_pids", []).append(pid)

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(diff_capture.threading, "Thread", FakeThread)
    monkeypatch.setattr(diff_capture, "_kill_process_tree", fake_kill_process_tree)

    with pytest.raises(KeyboardInterrupt) as excinfo:
        _run_with_process_group_timeout(
            ["python", "-c", "hang"],
            cwd=tmp_path,
            timeout=10,
        )

    assert excinfo.value is interrupt
    assert calls["cleanup_pids"] == [4321]
    assert calls["closed_pipes"] == ["stdout", "stderr"]
    assert calls["waits"] == [5]
    assert calls["join_timeouts"] == [10, 1]


def test_process_group_timeout_cleanup_interrupt_propagates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, object] = {"closed_pipes": [], "waits": []}
    interrupt = KeyboardInterrupt("cancel")

    class FakePipe:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            calls["closed_pipes"].append(self.name)

    class FakeProc:
        pid = 4321
        returncode = None
        stdout = FakePipe("stdout")
        stderr = FakePipe("stderr")

        def wait(self, timeout: int) -> None:
            calls["waits"].append(timeout)
            if len(calls["waits"]) == 1:
                raise interrupt

    class FakeThread:
        def __init__(self, *, target, daemon: bool) -> None:
            pass

        def start(self) -> None:
            pass

        def join(self, timeout: float) -> None:
            pass

        def is_alive(self) -> bool:
            return True

    def fake_popen(cmd, cwd, env, stdout, stderr, text, start_new_session):
        return FakeProc()

    def fake_kill_process_tree(pid, proc) -> None:
        calls.setdefault("cleanup_pids", []).append(pid)

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(diff_capture.threading, "Thread", FakeThread)
    monkeypatch.setattr(diff_capture, "_kill_process_tree", fake_kill_process_tree)

    with pytest.raises(KeyboardInterrupt) as excinfo:
        _run_with_process_group_timeout(
            ["python", "-c", "hang"],
            cwd=tmp_path,
            timeout=10,
        )

    assert excinfo.value is interrupt
    assert calls["cleanup_pids"] == [4321, 4321]
    assert calls["closed_pipes"] == ["stdout", "stderr", "stdout", "stderr"]
    assert calls["waits"] == [5, 5]


def test_process_group_timeout_suppresses_pipe_close_oserror(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, object] = {"closed_pipes": [], "join_timeouts": [], "waits": []}

    class FakePipe:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            calls["closed_pipes"].append(self.name)
            if self.name == "stdout":
                raise OSError("pipe close failed")

    class FakeProc:
        pid = 4321
        returncode = None
        stdout = FakePipe("stdout")
        stderr = FakePipe("stderr")

        def wait(self, timeout: int) -> None:
            calls["waits"].append(timeout)

    class FakeThread:
        def __init__(self, *, target, daemon: bool) -> None:
            pass

        def start(self) -> None:
            pass

        def join(self, timeout: float) -> None:
            calls["join_timeouts"].append(timeout)

        def is_alive(self) -> bool:
            return True

    def fake_popen(cmd, cwd, env, stdout, stderr, text, start_new_session):
        calls["start_new_session"] = start_new_session
        return FakeProc()

    def fake_kill_process_tree(pid, proc) -> None:
        calls["cleanup_pid"] = pid

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(diff_capture.threading, "Thread", FakeThread)
    monkeypatch.setattr(diff_capture, "_kill_process_tree", fake_kill_process_tree)

    with pytest.raises(subprocess.TimeoutExpired):
        _run_with_process_group_timeout(
            ["python", "-c", "hang"],
            cwd=tmp_path,
            timeout=10,
        )

    assert calls["start_new_session"] is True
    assert calls["cleanup_pid"] == 4321
    assert calls["closed_pipes"] == ["stdout", "stderr"]
    assert calls["waits"] == [5]
    assert calls["join_timeouts"] == [10, 1]


def test_process_group_timeout_kills_descendant_process_groups(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, object] = {"killpg": []}
    unblock = threading.Event()

    class FakePipe:
        def close(self) -> None:
            unblock.set()

    class FakeProc:
        pid = 4321
        returncode = None
        stdout = FakePipe()
        stderr = FakePipe()

        def communicate(self, timeout: float):
            unblock.wait(30)
            return "", ""

        def wait(self, timeout: int):
            self.returncode = -signal.SIGKILL

        def kill(self):
            calls["kill"] = True

    def fake_popen(cmd, cwd, env, stdout, stderr, text, start_new_session):
        return FakeProc()

    def fake_run(cmd, capture_output, text, check):
        parent = cmd[-1]
        stdout_text = {"4321": "5000\n", "5000": ""}[parent]
        return SimpleNamespace(returncode=0 if stdout_text else 1, stdout=stdout_text)

    def fake_getpgid(pid: int) -> int:
        return {4321: 4321, 5000: 5000}[pid]

    def fake_killpg(pgid: int, sig: int) -> None:
        calls["killpg"].append((pgid, sig))

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("os.getpgid", fake_getpgid)
    monkeypatch.setattr("os.killpg", fake_killpg)

    with pytest.raises(subprocess.TimeoutExpired):
        _run_with_process_group_timeout(
            ["python", "-c", "hang"],
            cwd=tmp_path,
            timeout=0.01,
        )

    assert calls["killpg"] == [
        (5000, signal.SIGKILL),
        (4321, signal.SIGKILL),
    ]


def test_process_group_timeout_reports_unreaped_uninterruptible_wibo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.mwcc_debug import diff_capture
    from src.mwcc_debug.local_safety import LocalWiboProcess

    unblock = threading.Event()

    class FakePipe:
        def close(self) -> None:
            unblock.set()

    class FakeProc:
        pid = 4321
        returncode = None
        stdout = FakePipe()
        stderr = FakePipe()

        def communicate(self, timeout: float):
            unblock.wait(30)
            return "", ""

        def wait(self, timeout: int):
            raise subprocess.TimeoutExpired(["python", "-c", "hang"], timeout)

        def kill(self):
            pass

    def fake_popen(cmd, cwd, env, stdout, stderr, text, start_new_session):
        return FakeProc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(diff_capture, "_kill_process_tree", lambda pid, proc: None)
    monkeypatch.setattr(
        diff_capture.local_safety,
        "scan_local_wibo_processes",
        lambda: [
            LocalWiboProcess(
                pid=4321,
                ppid=1,
                stat="UEs",
                elapsed="10:27",
                command=(
                    "wibo mwcceppc_debug.exe "
                    "-c src/sysdolphin/baselib/particle.c"
                ),
                source_rel="src/sysdolphin/baselib/particle.c",
            )
        ],
    )

    with pytest.raises(subprocess.TimeoutExpired) as excinfo:
        _run_with_process_group_timeout(
            ["python", "-c", "hang"],
            cwd=tmp_path,
            timeout=0.01,
        )

    assert "unreaped uninterruptible wibo process" in excinfo.value.stderr
    assert "4321" in excinfo.value.stderr
    assert "src/sysdolphin/baselib/particle.c" in excinfo.value.stderr
