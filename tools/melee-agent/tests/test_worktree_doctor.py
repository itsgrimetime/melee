"""Regression tests for tools/worktree-doctor.py."""
from __future__ import annotations

import importlib.util
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path


def load_worktree_doctor(script: Path | None = None):
    if script is None:
        script = Path(__file__).resolve().parents[2] / "worktree-doctor.py"
    spec = importlib.util.spec_from_file_location("worktree_doctor_under_test", script)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_symlinked_doctor_uses_current_git_root(monkeypatch, tmp_path: Path) -> None:
    source_repo = tmp_path / "source"
    pr_worktree = tmp_path / "pr"
    source_tools = source_repo / "tools"
    pr_tools = pr_worktree / "tools"
    source_tools.mkdir(parents=True)
    pr_tools.mkdir(parents=True)
    for root in (source_repo, pr_worktree):
        (root / "configure.py").write_text("# config\n", encoding="utf-8")
        (root / "src").mkdir(exist_ok=True)
        (root / "config" / "GALE01").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        Path(__file__).resolve().parents[2] / "worktree-doctor.py",
        source_tools / "worktree-doctor.py",
    )
    (pr_tools / "worktree-doctor.py").symlink_to(
        source_tools / "worktree-doctor.py"
    )
    subprocess.run(["git", "init"], cwd=pr_worktree, check=True, capture_output=True)

    monkeypatch.chdir(pr_worktree)
    doctor_mod = load_worktree_doctor(pr_tools / "worktree-doctor.py")

    assert doctor_mod.ROOT == pr_worktree.resolve()


def test_missing_report_json_is_a_failure(tmp_path: Path) -> None:
    doctor = load_worktree_doctor()
    src = tmp_path / "src"
    src.mkdir()
    (src / "example.c").write_text("void example(void) {}\n")

    results = doctor.collect_stale_state_warnings(tmp_path)

    missing_report = [r for r in results if "report.json is missing" in r.message]
    assert missing_report
    assert missing_report[0].level == "fail"
    assert "ninja build/GALE01/report.json" in missing_report[0].fix


def test_fix_mode_reinstalls_stale_melee_agent_entrypoint(monkeypatch, tmp_path: Path) -> None:
    doctor_mod = load_worktree_doctor()
    fake_agent = tmp_path / "melee-agent"
    fake_agent.write_text("#!/usr/bin/env python\n")
    calls: list[list[str]] = []

    monkeypatch.setattr(doctor_mod, "ROOT", tmp_path)
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda name: str(fake_agent) if name == "melee-agent" else None)

    def fake_run_cmd(args: list[str], timeout: int):
        calls.append(args)
        return doctor_mod.subprocess.CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr(doctor_mod, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(
        doctor_mod,
        "collect_melee_agent_entrypoint_warnings",
        lambda root, executable: [
            doctor_mod.CheckResult(
                "warn",
                "melee-agent imports src.cli from /other/checkout/src/cli/__init__.py, expected local",
                "reinstall with: cd tools/melee-agent && python -m pip install -e .",
            )
        ],
    )
    monkeypatch.setattr(doctor_mod, "detect_ghidra_install", lambda: None)

    doctor = doctor_mod.Doctor(fix=True)
    doctor.check_cli_tools()

    assert [sys.executable, "-m", "pip", "install", "-e", "tools/melee-agent"] in calls
    assert any(result.level == "ok" and "reinstalled melee-agent" in result.message for result in doctor.results)


def test_resolve_melee_agent_module_path_uses_launcher_probe(monkeypatch, tmp_path: Path) -> None:
    doctor_mod = load_worktree_doctor()
    fake_agent = tmp_path / "melee-agent"
    fake_agent.write_text("#!/usr/bin/env python\n", encoding="utf-8")
    local_cli = tmp_path / "tools" / "melee-agent" / "src" / "cli" / "__init__.py"
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    def fake_run_cmd(
        args: list[str],
        timeout: int,
        *,
        cwd=None,
        env: dict[str, str] | None = None,
        timeout_message: str = "timed out",
    ):
        calls.append((args, env))
        return doctor_mod.subprocess.CompletedProcess(args, 0, str(local_cli) + "\n", "")

    monkeypatch.setattr(doctor_mod, "run_cmd", fake_run_cmd)

    assert doctor_mod.resolve_melee_agent_module_path(fake_agent) == local_cli
    assert len(calls) == 1
    assert calls[0][0] == [str(fake_agent)]
    assert calls[0][1] is not None
    assert calls[0][1]["MELEE_AGENT_PRINT_SRC_CLI"] == "1"


def test_collect_melee_agent_entrypoint_warnings_flags_old_same_worktree_entrypoint(tmp_path: Path) -> None:
    doctor_mod = load_worktree_doctor()
    fake_agent = tmp_path / "melee-agent"
    fake_agent.write_text(
        "#!/usr/bin/env python\n"
        "from src.cli import main\n"
        "main()\n",
        encoding="utf-8",
    )
    expected = (tmp_path / "tools" / "melee-agent" / "src" / "cli" / "__init__.py").resolve()

    results = doctor_mod.collect_melee_agent_entrypoint_warnings(
        tmp_path,
        fake_agent,
        module_path=expected,
    )

    assert results[0].level == "warn"
    assert "worktree-resolving launcher" in results[0].message
    assert "pip install -e" in (results[0].fix or "")


def test_fix_removes_local_exclude_that_hides_tracked_melee_agent(tmp_path: Path) -> None:
    doctor_mod = load_worktree_doctor()
    subprocess.run(["git", "init", "-b", "master"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Agent"], cwd=tmp_path, check=True)
    agent_file = tmp_path / "tools" / "melee-agent" / "pyproject.toml"
    agent_file.parent.mkdir(parents=True)
    agent_file.write_text("[project]\nname = 'melee-agent'\n", encoding="utf-8")
    subprocess.run(["git", "add", "tools/melee-agent/pyproject.toml"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "track melee agent"], cwd=tmp_path, check=True, capture_output=True)
    exclude = doctor_mod.local_exclude_path(tmp_path)
    assert exclude is not None
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("tools/melee-agent\n", encoding="utf-8")

    warnings = doctor_mod.collect_local_exclude_warnings(tmp_path, fix=False)

    assert warnings
    assert warnings[0].level == "warn"
    assert "tools/melee-agent" in warnings[0].message

    fixed = doctor_mod.collect_local_exclude_warnings(tmp_path, fix=True)

    assert fixed[0].level == "ok"
    assert "tools/melee-agent" not in exclude.read_text(encoding="utf-8")
    probe = subprocess.run(
        ["git", "check-ignore", "tools/melee-agent/new_file.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert probe.returncode != 0


def _make_table_typer_dir(tmp_path: Path) -> Path:
    ttdir = tmp_path / "tools" / "table-typer"
    ttdir.mkdir(parents=True)
    (ttdir / "go.mod").write_text("module table-typer\n")
    return ttdir


def test_fix_builds_table_typer_when_missing(monkeypatch, tmp_path: Path) -> None:
    """Issue #30: --fix should actually build table-typer, not just suggest it."""
    doctor_mod = load_worktree_doctor()
    ttdir = _make_table_typer_dir(tmp_path)
    monkeypatch.setattr(doctor_mod, "ROOT", tmp_path)

    calls: list[Path] = []

    def fake_build(root: Path):
        calls.append(root)
        (ttdir / "table-typer").write_text("#!binary\n")  # simulate go build output
        return doctor_mod.subprocess.CompletedProcess(["go", "build"], 0, "ok", "")

    monkeypatch.setattr(doctor_mod, "build_table_typer", fake_build)

    doctor = doctor_mod.Doctor(fix=True)
    doctor.check_table_typer()

    assert calls == [tmp_path]
    assert any(r.level == "ok" and "table-typer" in r.message for r in doctor.results)


def test_fix_table_typer_go_missing_is_optional_warn(monkeypatch, tmp_path: Path) -> None:
    """If Go isn't installed, --fix can't build it; warn but label opseq optional."""
    doctor_mod = load_worktree_doctor()
    _make_table_typer_dir(tmp_path)
    monkeypatch.setattr(doctor_mod, "ROOT", tmp_path)
    monkeypatch.setattr(
        doctor_mod,
        "build_table_typer",
        lambda root: doctor_mod.subprocess.CompletedProcess(["go", "build"], 127, "", "go: not found"),
    )

    doctor = doctor_mod.Doctor(fix=True)
    doctor.check_table_typer()

    warns = [r for r in doctor.results if r.level == "warn"]
    assert warns
    blob = " ".join((r.message + " " + (r.fix or "")).lower() for r in warns)
    assert "optional" in blob
    assert "go" in blob
    # A missing optional tool must never make the doctor fail.
    assert all(r.level != "fail" for r in doctor.results)


def test_fix_replaces_macos_arm64_dtk_with_rosetta_binary(monkeypatch, tmp_path: Path) -> None:
    doctor_mod = load_worktree_doctor()
    dtk = tmp_path / "build" / "tools" / "dtk"
    dtk.parent.mkdir(parents=True)
    dtk.write_bytes(b"arm64 dtk")

    monkeypatch.setattr(doctor_mod, "ROOT", tmp_path)
    monkeypatch.setattr(doctor_mod.sys, "platform", "darwin")
    monkeypatch.setattr(doctor_mod.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(doctor_mod, "detect_macho_arch", lambda path: "arm64")

    calls: list[Path] = []

    def fake_download(path: Path) -> bool:
        calls.append(path)
        path.write_bytes(b"x86_64 dtk")
        return True

    monkeypatch.setattr(doctor_mod, "redownload_dtk", fake_download)
    monkeypatch.setattr(doctor_mod.Doctor, "check_wibo_tool", lambda self: None)

    doctor = doctor_mod.Doctor(fix=True)
    doctor.check_build_tools()

    assert calls == [dtk]
    assert dtk.read_bytes() == b"x86_64 dtk"
    assert any("refreshed build/tools/dtk" in r.message for r in doctor.results)


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_refresh_report_timeout_kills_child_processes(monkeypatch, tmp_path: Path) -> None:
    doctor_mod = load_worktree_doctor()
    child_pid_file = tmp_path / "child.pid"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ninja = bin_dir / "ninja"
    ninja.write_text(
        "#!/bin/sh\n"
        "sleep 30 &\n"
        "echo $! > \"$CHILD_PID_FILE\"\n"
        "wait\n"
    )
    ninja.chmod(0o755)
    (tmp_path / "configure.py").write_text("import sys\nsys.exit(0)\n")

    monkeypatch.setattr(doctor_mod, "REPORT_REFRESH_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setenv("CHILD_PID_FILE", str(child_pid_file))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    child_pid: int | None = None
    try:
        result = doctor_mod.refresh_report_json(tmp_path)
        assert result.returncode == 124

        child_pid = int(child_pid_file.read_text().strip())
        for _ in range(20):
            if not _process_exists(child_pid):
                break
            time.sleep(0.05)
        assert not _process_exists(child_pid)
    finally:
        if child_pid is not None and _process_exists(child_pid):
            os.kill(child_pid, signal.SIGKILL)


def test_fix_removes_corrupt_ninja_deps(monkeypatch, tmp_path: Path) -> None:
    doctor_mod = load_worktree_doctor()
    ninja_deps = tmp_path / ".ninja_deps"
    ninja_deps.write_text("corrupt")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ninja = bin_dir / "ninja"
    ninja.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-t\" ] && [ \"$2\" = \"deps\" ]; then\n"
        "  echo 'ninja: warning: premature end of file; recovering' >&2\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    ninja.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    result = doctor_mod.repair_ninja_deps_if_corrupt(tmp_path, fix=True)

    assert result is not None
    assert result.level == "ok"
    assert "removed corrupt .ninja_deps" in result.message
    assert not ninja_deps.exists()


def test_table_typer_missing_without_fix_labels_optional(monkeypatch, tmp_path: Path) -> None:
    """Without --fix, the warning should point at --fix and call opseq optional."""
    doctor_mod = load_worktree_doctor()
    _make_table_typer_dir(tmp_path)
    monkeypatch.setattr(doctor_mod, "ROOT", tmp_path)

    def must_not_build(root: Path):
        raise AssertionError("build_table_typer must not run without --fix")

    monkeypatch.setattr(doctor_mod, "build_table_typer", must_not_build)

    doctor = doctor_mod.Doctor(fix=False)
    doctor.check_table_typer()

    warns = [r for r in doctor.results if r.level == "warn"]
    assert warns
    assert any("--fix" in (r.fix or "") for r in warns)
    blob = " ".join((r.message + " " + (r.fix or "")).lower() for r in warns)
    assert "optional" in blob


def test_fix_replaces_broken_base_dol_symlink(monkeypatch, tmp_path: Path) -> None:
    doctor_mod = load_worktree_doctor()
    candidate = tmp_path / "shared" / "main.dol"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"fake dol")
    worktree = tmp_path / "worktree"
    dol_path = worktree / "orig" / "GALE01" / "sys" / "main.dol"
    dol_path.parent.mkdir(parents=True)
    dol_path.symlink_to(tmp_path / "missing" / "main.dol")

    monkeypatch.setattr(doctor_mod, "ROOT", worktree)
    monkeypatch.setattr(doctor_mod, "DOL_CANDIDATES", [candidate])

    doctor = doctor_mod.Doctor(fix=True)
    doctor.check_base_dol()

    assert dol_path.exists()
    assert dol_path.is_symlink()
    assert dol_path.resolve() == candidate
    assert any(r.level == "ok" and "base DOL" in r.message for r in doctor.results)


def test_session_startup_links_base_dol_for_local_agent_worktree(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    script = repo / ".claude" / "hooks" / "session-startup.sh"
    project = tmp_path / "agent-worktree"
    project.mkdir()
    candidate = tmp_path / "shared" / "main.dol"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"fake dol")

    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_CODE_REMOTE"] = ""
    env["MELEE_BASE_DOL_SOURCE"] = str(candidate)

    proc = subprocess.run(
        ["bash", str(script)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    dol_path = project / "orig" / "GALE01" / "sys" / "main.dol"
    assert proc.returncode == 0, proc.stderr
    assert dol_path.exists()
    assert dol_path.is_symlink()
    assert dol_path.resolve() == candidate
