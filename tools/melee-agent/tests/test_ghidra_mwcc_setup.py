from __future__ import annotations

import subprocess
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.mwcc_debug import ghidra_mwcc_setup as ghidra_setup_module
from src.mwcc_debug.ghidra_mwcc_setup import (
    EXPECTED_COMPILER_SHA256,
    MwccGhidraSetupError,
    MwccGhidraSetupResult,
    setup_mwcc_ghidra,
)

STATUS_MARKER = (
    'MWCC_AUDIT_STATUS {"sha256":"'
    + EXPECTED_COMPILER_SHA256
    + '","function_count":3248}\n'
)
ANALYSIS_SUCCEEDED = "REPORT: Analysis succeeded for file: mwcceppc.exe\n"


class ScriptedRunner:
    def __init__(self, *steps: subprocess.CompletedProcess[str] | BaseException):
        self.steps = list(steps)
        self.calls: list[dict[str, object]] = []

    def __call__(self, cmd, *, cwd, timeout, env=None):
        self.calls.append(
            {
                "cmd": list(cmd),
                "cwd": cwd,
                "timeout": timeout,
                "env": env,
            }
        )
        if not self.steps:
            raise AssertionError("unexpected Ghidra invocation")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def completed(stdout: str = "", *, stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(["analyzeHeadless"], returncode, stdout, stderr)


@pytest.fixture
def setup_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    melee_root = tmp_path / "melee"
    compiler = melee_root / "build/compilers/GC/1.2.5n/mwcceppc.exe"
    compiler.parent.mkdir(parents=True)
    compiler.write_bytes(b"fixture compiler")

    install = tmp_path / "ghidra"
    headless = install / "support/analyzeHeadless"
    native = install / "Ghidra/Features/Decompiler/os/mac_arm_64/decompile"
    for executable in (headless, native):
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)

    status_script = melee_root / "tools/mwcc_debug/scripts/MwccAuditStatus.java"
    status_script.parent.mkdir(parents=True)
    status_script.write_text("// fixture status script\n", encoding="utf-8")
    project_dir = melee_root / "tools/mwcc_debug/ghidra_project"

    monkeypatch.setattr(ghidra_setup_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ghidra_setup_module.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(ghidra_setup_module, "_sha256_file", lambda _path: EXPECTED_COMPILER_SHA256)
    return {
        "melee_root": melee_root,
        "compiler": compiler,
        "install": install,
        "headless": headless,
        "native": native,
        "status_script": status_script,
        "project_dir": project_dir,
    }


def invoke(setup_env, runner, **changes):
    values = {
        "melee_root": setup_env["melee_root"],
        "project_dir": setup_env["project_dir"],
        "analysis_timeout": 300,
        "wall_timeout": 420,
        "repair": False,
        "detect_install": lambda: setup_env["install"],
        "runner": runner,
        "now": lambda: datetime(2026, 7, 12, 12, 34, 56, tzinfo=UTC),
    }
    values.update(changes)
    return setup_mwcc_ghidra(**values)


def test_preflight_requires_host_native_macos_decompiler(setup_env) -> None:
    setup_env["native"].unlink()
    x86 = setup_env["install"] / "Ghidra/Features/Decompiler/os/mac_x86_64/decompile"
    x86.parent.mkdir(parents=True, exist_ok=True)
    x86.write_text("#!/bin/sh\n", encoding="utf-8")
    x86.chmod(0o755)

    with pytest.raises(MwccGhidraSetupError) as caught:
        invoke(setup_env, ScriptedRunner())

    assert caught.value.reason == "missing-native-decompiler"
    assert caught.value.details["host_arch"] == "arm64"


def test_preflight_rejects_wrong_compiler_sha256(setup_env, monkeypatch) -> None:
    monkeypatch.setattr(ghidra_setup_module, "_sha256_file", lambda _path: "0" * 64)

    with pytest.raises(MwccGhidraSetupError) as caught:
        invoke(setup_env, ScriptedRunner())

    assert caught.value.reason == "compiler-sha256-mismatch"
    assert caught.value.details == {
        "actual": "0" * 64,
        "expected": EXPECTED_COMPILER_SHA256,
        "path": str(setup_env["compiler"]),
    }


def test_missing_project_imports_then_validates_exact_program(setup_env) -> None:
    runner = ScriptedRunner(completed(ANALYSIS_SUCCEEDED), completed(STATUS_MARKER))

    result = invoke(setup_env, runner)

    assert result.status == "imported"
    assert result.compiler_sha256 == EXPECTED_COMPILER_SHA256
    assert result.function_count == 3248
    assert result.quarantined_paths == ()
    assert setup_env["project_dir"].is_dir()
    assert [call["cmd"] for call in runner.calls] == [
        [
            str(setup_env["headless"]),
            str(setup_env["project_dir"]),
            "mwcceppc",
            "-import",
            str(setup_env["compiler"]),
            "-analysisTimeoutPerFile",
            "300",
        ],
        [
            str(setup_env["headless"]),
            str(setup_env["project_dir"]),
            "mwcceppc",
            "-process",
            "mwcceppc.exe",
            "-noanalysis",
            "-scriptPath",
            str(setup_env["status_script"].parent),
            "-postScript",
            "MwccAuditStatus.java",
            EXPECTED_COMPILER_SHA256,
        ],
    ]
    assert all(call["cwd"] == setup_env["melee_root"] for call in runner.calls)
    assert all(call["timeout"] == 420 for call in runner.calls)


def test_valid_project_is_idempotent_and_skips_import(setup_env) -> None:
    (setup_env["project_dir"]).mkdir(parents=True)
    (setup_env["project_dir"] / "mwcceppc.gpr").touch()
    runner = ScriptedRunner(completed(STATUS_MARKER))

    result = invoke(setup_env, runner)

    assert result.status == "ready"
    assert result.function_count == 3248
    assert len(runner.calls) == 1
    assert "-process" in runner.calls[0]["cmd"]
    assert "-import" not in runner.calls[0]["cmd"]


def test_validation_accepts_ghidra_decorated_status_marker(setup_env) -> None:
    setup_env["project_dir"].mkdir(parents=True)
    (setup_env["project_dir"] / "mwcceppc.gpr").touch()
    runner = ScriptedRunner(completed("MwccAuditStatus.java> " + STATUS_MARKER))

    result = invoke(setup_env, runner)

    assert result.status == "ready"
    assert result.function_count == 3248


def test_empty_rep_is_invalid_without_repair(setup_env) -> None:
    rep = setup_env["project_dir"] / "mwcceppc.rep"
    (rep / "idata").mkdir(parents=True)
    (rep / "idata/~index.dat").write_bytes(b"empty")
    runner = ScriptedRunner(completed("", returncode=1))

    with pytest.raises(MwccGhidraSetupError) as caught:
        invoke(setup_env, runner)

    assert caught.value.reason == "invalid-existing-project"
    assert caught.value.details["cause"] == "ghidra-process-failed"
    assert rep.exists()
    assert len(runner.calls) == 1


def test_repair_retains_all_artifacts_under_one_utc_suffix(setup_env) -> None:
    project_dir = setup_env["project_dir"]
    project_dir.mkdir(parents=True)
    artifacts = tuple(project_dir / f"mwcceppc{suffix}" for suffix in (".gpr", ".rep", ".lock"))
    artifacts[0].write_text("invalid gpr", encoding="utf-8")
    artifacts[1].mkdir()
    artifacts[2].write_text("invalid lock", encoding="utf-8")
    runner = ScriptedRunner(
        completed("", returncode=1),
        completed(ANALYSIS_SUCCEEDED),
        completed(STATUS_MARKER),
    )

    result = invoke(setup_env, runner, repair=True)

    suffix = ".invalid-20260712T123456Z"
    expected = tuple(Path(f"{artifact}{suffix}") for artifact in artifacts)
    assert result.status == "repaired"
    assert result.quarantined_paths == expected
    assert all(path.exists() for path in expected)
    assert all(not path.exists() for path in artifacts)
    assert ["-process" in call["cmd"] for call in runner.calls] == [True, False, True]


def test_import_process_timeout_has_stable_reason(setup_env) -> None:
    runner = ScriptedRunner(subprocess.TimeoutExpired(["analyzeHeadless"], 420))

    with pytest.raises(MwccGhidraSetupError) as caught:
        invoke(setup_env, runner)

    assert caught.value.reason == "ghidra-process-timeout"
    assert caught.value.details["phase"] == "import"
    assert caught.value.details["timeout"] == 420


@pytest.mark.parametrize(
    ("output", "reason"),
    [
        ("REPORT: Analysis timed out at 300 seconds\n", "ghidra-analysis-timeout"),
        ("Analysis cancelled by user\n", "ghidra-analysis-cancelled"),
        ("REPORT: Processing cancelled\n", "ghidra-analysis-cancelled"),
        ("Abort due to Headless analyzer error: broken\n", "ghidra-headless-abort"),
    ],
)
def test_exit_zero_fatal_import_output_is_rejected(setup_env, output: str, reason: str) -> None:
    with pytest.raises(MwccGhidraSetupError) as caught:
        invoke(setup_env, ScriptedRunner(completed(output)))

    assert caught.value.reason == reason
    assert caught.value.details["phase"] == "import"


@pytest.mark.parametrize(
    ("marker", "reason"),
    [
        ('MWCC_AUDIT_STATUS {"sha256":"' + "0" * 64 + '","function_count":3248}\n', "status-sha256-mismatch"),
        (
            'MWCC_AUDIT_STATUS {"sha256":"' + EXPECTED_COMPILER_SHA256 + '","function_count":0}\n',
            "empty-status-functions",
        ),
        ("MWCC_AUDIT_STATUS not-json\n", "invalid-status-marker"),
    ],
)
def test_import_validation_requires_exact_marker_sha_and_positive_count(
    setup_env,
    marker: str,
    reason: str,
) -> None:
    runner = ScriptedRunner(completed(ANALYSIS_SUCCEEDED), completed(marker))

    with pytest.raises(MwccGhidraSetupError) as caught:
        invoke(setup_env, runner)

    assert caught.value.reason == reason


def test_result_is_immutable_and_has_stable_json_shape(tmp_path: Path) -> None:
    result = MwccGhidraSetupResult(
        status="repaired",
        ghidra_install=tmp_path / "ghidra",
        headless_path=tmp_path / "ghidra/support/analyzeHeadless",
        native_decompiler_path=tmp_path / "ghidra/Ghidra/Features/Decompiler/os/mac_arm_64/decompile",
        compiler_path=tmp_path / "mwcceppc.exe",
        compiler_sha256=EXPECTED_COMPILER_SHA256,
        project_dir=tmp_path / "project",
        project_name="mwcceppc",
        program_path="/mwcceppc.exe",
        function_count=3248,
        elapsed_seconds=82.125,
        quarantined_paths=(tmp_path / "project/mwcceppc.gpr.invalid-20260712T123456Z",),
    )

    assert result.to_dict() == {
        "schema_version": "mwcc-ghidra-setup.v1",
        "status": "repaired",
        "ghidra_install": str(tmp_path / "ghidra"),
        "headless_path": str(tmp_path / "ghidra/support/analyzeHeadless"),
        "native_decompiler_path": str(
            tmp_path / "ghidra/Ghidra/Features/Decompiler/os/mac_arm_64/decompile"
        ),
        "compiler_path": str(tmp_path / "mwcceppc.exe"),
        "compiler_sha256": EXPECTED_COMPILER_SHA256,
        "project_dir": str(tmp_path / "project"),
        "project_name": "mwcceppc",
        "program_path": "/mwcceppc.exe",
        "function_count": 3248,
        "elapsed_seconds": 82.125,
        "quarantined_paths": [str(tmp_path / "project/mwcceppc.gpr.invalid-20260712T123456Z")],
    }
    with pytest.raises(FrozenInstanceError):
        result.status = "ready"  # type: ignore[misc]


def test_java_status_script_enforces_sha_and_positive_function_count() -> None:
    root = Path(__file__).resolve().parents[3]
    text = (root / "tools/mwcc_debug/scripts/MwccAuditStatus.java").read_text(encoding="utf-8")

    assert "package " not in text
    assert "extends GhidraScript" in text
    assert "getScriptArgs()" in text
    assert "currentProgram == null" in text
    assert "getExecutableSHA256()" in text
    assert "equalsIgnoreCase" in text
    assert "getFunctionCount()" in text
    assert 'MWCC_AUDIT_STATUS {\\"sha256\\":\\"' in text
