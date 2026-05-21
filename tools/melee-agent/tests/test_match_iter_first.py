"""Tests for match-iter-first verification helpers."""

from __future__ import annotations

import pathlib
import subprocess
import sys

from src.cli import debug as debug_cli


CLI_CWD = pathlib.Path(__file__).parent.parent
MELEE_ROOT = CLI_CWD.parent.parent


def test_pcdump_local_help_exposes_force_iter_first_function_scope() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "pcdump-local", "--help"],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "--force-iter-first-fn" in proc.stdout
    assert "Scope --force-iter-first" in proc.stdout


def test_match_iter_first_help_documents_auto_verify_cleanup_contract() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "match-iter-first", "--help"],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "MWCC_DEBUG_RESTORE_TIMEOUT" in proc.stdout
    assert "MWCC_DEBUG_HANG_TIMEOUT" in proc.stdout
    assert "cleanup_complete=false" in proc.stdout
    assert "non-zero" in proc.stdout


def test_restore_object_report_help_exposes_guarded_cleanup_command() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "restore-object-report", "--help"],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "--max-steps" in proc.stdout
    assert "--force" in proc.stdout
    assert "MWCC_DEBUG_RESTORE_MAX_STEPS" in proc.stdout


def test_match_iter_first_auto_verify_command_scopes_force_iter_first() -> None:
    src_path = MELEE_ROOT / "src" / "melee" / "mn" / "mnvibration.c"

    cmd = debug_cli._build_match_iter_first_auto_verify_cmd(
        src_path=src_path,
        ig_csv="151,48,45,153",
        function="fn_80247510",
    )

    assert "--force-iter-first" in cmd
    assert "151,48,45,153" in cmd
    assert "--force-iter-first-fn" in cmd
    assert "fn_80247510" in cmd


def test_auto_verify_runner_emits_periodic_status(capsys) -> None:
    cmd = [
        sys.executable,
        "-c",
        "import time; time.sleep(0.2); print('done')",
    ]

    result = debug_cli._run_auto_verify_command_with_status(
        cmd,
        cwd=CLI_CWD,
        status_label="--force-iter-first 151 --force-iter-first-fn fn_test",
        status_interval_s=0.05,
    )

    captured = capsys.readouterr()
    assert result.returncode == 0
    assert "done" in result.stdout
    assert "testing --force-iter-first 151 --force-iter-first-fn fn_test" in (
        captured.err
    )
    assert "still running" in captured.err


def test_auto_verify_runner_times_out_restore_phase(capsys) -> None:
    cmd = [
        sys.executable,
        "-c",
        "import time; time.sleep(5)",
    ]

    result = debug_cli._run_auto_verify_command_with_status(
        cmd,
        cwd=CLI_CWD,
        status_label="clean object/report",
        phase="restoring object/report",
        status_interval_s=0.05,
        timeout_s=0.12,
    )

    captured = capsys.readouterr()
    assert result.returncode == 124
    assert "restoring object/report: clean object/report" in captured.err
    assert "still running" in captured.err
    assert "timed out" in result.stderr


def test_auto_verify_restore_timeout_inherits_hang_timeout(monkeypatch) -> None:
    monkeypatch.delenv("MWCC_DEBUG_RESTORE_TIMEOUT", raising=False)
    monkeypatch.setenv("MWCC_DEBUG_HANG_TIMEOUT", "8")

    timeout_s, source = debug_cli._resolve_auto_verify_restore_timeout()

    assert timeout_s == 8.0
    assert source == "MWCC_DEBUG_HANG_TIMEOUT"


def test_auto_verify_restore_timeout_prefers_restore_env(monkeypatch) -> None:
    monkeypatch.setenv("MWCC_DEBUG_RESTORE_TIMEOUT", "12")
    monkeypatch.setenv("MWCC_DEBUG_HANG_TIMEOUT", "8")

    timeout_s, source = debug_cli._resolve_auto_verify_restore_timeout()

    assert timeout_s == 12.0
    assert source == "MWCC_DEBUG_RESTORE_TIMEOUT"


def test_auto_verify_restore_hint_explains_truncated_ninja_state() -> None:
    hint = debug_cli._auto_verify_restore_cleanup_hint(
        "ninja: warning: premature end of file; recovering\n"
    )

    assert "ninja -t recompact" in hint
    assert "restore-object-report" in hint
    assert ".ninja_deps" in hint
    assert "python configure.py" in hint


def test_ninja_dry_run_step_count_uses_total_planned_steps() -> None:
    assert debug_cli._ninja_dry_run_planned_steps(
        "[1/969] Building C object\n"
        "[2/969] Building C object\n"
    ) == 969
    assert debug_cli._ninja_dry_run_planned_steps("ninja: no work to do.\n") == 0
    assert debug_cli._ninja_dry_run_planned_steps("touch foo.o\nlink report\n") == 2


def test_expensive_restore_guard_returns_failure_without_running_ninja() -> None:
    result = debug_cli._make_expensive_restore_result(
        ["ninja", "build/GALE01/src/melee/mn/mnvibration.o"],
        planned_steps=969,
        max_steps=64,
    )

    assert result.returncode == 125
    assert "would run 969 ninja step(s)" in result.stderr
    assert "MWCC_DEBUG_RESTORE_MAX_STEPS" in result.stderr
    assert "--force" in result.stderr


def test_auto_verify_restore_failure_requests_nonzero_exit() -> None:
    assert debug_cli._auto_verify_failure_exit_code({
        "ran": True,
        "restore": {"returncode": 124},
    }) == 124
    assert debug_cli._auto_verify_failure_exit_code({
        "ran": True,
        "restore": {"returncode": 0},
    }) is None
    assert debug_cli._auto_verify_failure_exit_code({"ran": False}) is None


def test_mwcc_debug_dll_has_iter_first_function_scope() -> None:
    dll_source = (MELEE_ROOT / "tools" / "mwcc_debug" / "mwcc_debug.c").read_text()

    assert "MWCC_DEBUG_FORCE_ITER_FIRST_FUNCTION" in dll_source
    assert "g_iter_first_scope_fn_set" in dll_source
    assert "[FORCE_ITER_FIRST] scope skip" in dll_source
