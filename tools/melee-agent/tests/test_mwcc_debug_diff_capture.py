"""Tests for source input resolution used by debug inspect diff."""
from __future__ import annotations

import signal
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mwcc_debug.diff_capture import (
    CompileFailure,
    DiffInput,
    compile_source_variant,
    read_inspect_input_if_available,
    resolve_diff_input,
    _run_with_process_group_timeout,
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
    assert cmd[6] == str(probe)
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

    diff_input = DiffInput(label="B", token=str(candidate), kind="source", path=candidate)
    text = compile_source_variant(diff_input, function="fn_test", melee_root=tmp_path, timeout=30)

    assert text == "Starting function fn_test\n"
    assert real_src.read_text(encoding="utf-8") == original_text


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
    assert cmd[:4] == ["tools/workflow/mwcc-inspect.sh", "--function", "fn_test", "--output"]
    assert cmd[-1] == str(candidate)
    out_path = Path(cmd[cmd.index("--output") + 1])
    assert out_path.parent == repo / "build" / "mwcc_inspect" / "candidates"
    assert out_path.name.startswith("b-candidate-")
    assert captured["cwd"] == repo
    assert captured["timeout"] == 45


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
    assert cmd[cmd.index("--output") + 1] == str(requested_output)


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
            (out_dir / "sample.txt").write_text(
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
    assert captured["cmd"] == [
        "tools/workflow/mwcc-inspect.sh",
        "--function",
        "fn_test",
        "--output",
        str(out_dir / "sample.txt"),
        str(src),
    ]
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


def test_read_inspect_returns_none_on_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path
    src = repo / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")

    class FakeProc:
        pid = 4321

        def communicate(self, timeout: int):
            raise subprocess.TimeoutExpired(cmd=["tools/workflow/mwcc-inspect.sh"], timeout=timeout)

        def wait(self, timeout: int):
            return 0

    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr("os.killpg", lambda pgid, sig: None)
    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)

    result = read_inspect_input_if_available(
        diff_input,
        function="fn_test",
        melee_root=repo,
        timeout=30,
    )

    assert result is None


def test_read_inspect_timeout_kills_process_group(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path
    src = repo / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_test(void) {}\n", encoding="utf-8")
    calls: dict[str, object] = {}

    class FakeProc:
        pid = 4321
        returncode = None

        def communicate(self, timeout: int):
            raise subprocess.TimeoutExpired(cmd=["tools/workflow/mwcc-inspect.sh"], timeout=timeout)

        def wait(self, timeout: int):
            calls["wait_timeout"] = timeout
            self.returncode = -signal.SIGKILL

    def fake_popen(cmd, cwd, stdout, stderr, text, start_new_session, env=None):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        calls["start_new_session"] = start_new_session
        calls["env"] = env
        return FakeProc()

    def fake_killpg(pgid: int, sig: int) -> None:
        calls["killpg"] = (pgid, sig)

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("os.killpg", fake_killpg)
    diff_input = DiffInput(label="A", token=str(src), kind="source", path=src)

    result = read_inspect_input_if_available(
        diff_input,
        function="fn_test",
        melee_root=repo,
        timeout=30,
    )

    assert result is None
    assert calls["cmd"] == [
        "tools/workflow/mwcc-inspect.sh",
        "--function",
        "fn_test",
        "--output",
        str(repo / "build" / "mwcc_inspect" / "sample.txt"),
        str(src),
    ]
    assert calls["start_new_session"] is True
    assert calls["killpg"] == (4321, signal.SIGKILL)
    assert calls["wait_timeout"] == 5


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
