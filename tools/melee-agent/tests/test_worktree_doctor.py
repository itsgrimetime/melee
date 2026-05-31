"""Regression tests for tools/worktree-doctor.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_worktree_doctor():
    script = Path(__file__).resolve().parents[2] / "worktree-doctor.py"
    spec = importlib.util.spec_from_file_location("worktree_doctor_under_test", script)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
