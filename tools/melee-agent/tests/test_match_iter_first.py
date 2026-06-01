"""Tests for match-iter-first verification helpers."""

from __future__ import annotations

import pathlib
import subprocess
import sys

from typer.testing import CliRunner

from src.cli import app
from src.cli import debug as debug_cli
from src.mwcc_debug.cache import cache_path
from src.mwcc_debug.colorgraph_parser import (
    ColorgraphDecision,
    ColorgraphSection,
    FunctionEvents,
)


CLI_CWD = pathlib.Path(__file__).parent.parent
MELEE_ROOT = CLI_CWD.parent.parent
runner = CliRunner()


def test_pcdump_local_help_exposes_force_iter_first_function_scope() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "dump", "local", "--help"],
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
        [
            "python", "-m", "src.cli", "debug", "target", "match-iter-first",
            "--help",
        ],
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
    assert "--force-vector" in proc.stdout
    assert "integrated checkdiff" in proc.stdout


def test_match_iter_first_rejects_stale_auto_cache_by_default(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    cached = cache_path(melee_root, "melee/mn/sample")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text("Starting function fn_80000000\n", encoding="utf-8")
    cached.with_suffix(".hash").write_text("0" * 64 + "\n", encoding="ascii")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "target",
            "match-iter-first",
            "-f",
            "fn_80000000",
        ],
    )

    assert result.exit_code == 4
    assert "cached pcdump is stale" in result.stdout + result.stderr
    assert "--allow-stale-pcdump" in result.stdout + result.stderr


def test_match_iter_first_reg_parser_accepts_fpr_tokens() -> None:
    regs = debug_cli._parse_match_iter_first_regs("f31,f30,r29")

    assert [reg.name for reg in regs] == ["f31", "f30", "r29"]
    assert [(reg.kind, reg.number) for reg in regs] == [
        ("f", 31),
        ("f", 30),
        ("r", 29),
    ]


def test_match_iter_first_reg_parser_expands_callee_alias_and_ranges() -> None:
    regs = debug_cli._parse_match_iter_first_regs("gpr-callee,f31-f30")

    assert [reg.name for reg in regs] == [
        "r31", "r30", "r29", "r28", "r27", "r26", "r25", "f31", "f30",
    ]


def test_match_iter_first_vector_keeps_full_target_order_and_current_regs() -> None:
    events = FunctionEvents(
        name="fn_test",
        colorgraph_sections=[
            ColorgraphSection(
                class_id=0,
                result=1,
                n_nodes=3,
                decisions=[
                    ColorgraphDecision(
                        iter_idx=0,
                        ig_idx=33,
                        assigned_reg=27,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                    ColorgraphDecision(
                        iter_idx=1,
                        ig_idx=40,
                        assigned_reg=26,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                    ColorgraphDecision(
                        iter_idx=2,
                        ig_idx=45,
                        assigned_reg=29,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                ],
            ),
        ],
    )
    results = [
        {"status": "ok", "kind": "r", "reg": 31, "reg_name": "r31", "ig_idx": 33},
        {"status": "ok", "kind": "r", "reg": 30, "reg_name": "r30", "ig_idx": 40},
        {"status": "ok", "kind": "r", "reg": 29, "reg_name": "r29", "ig_idx": 45},
    ]

    vector = debug_cli._build_match_iter_first_target_vector(results, events)

    assert vector["force_iter_first"] == [33, 40, 45]
    assert vector["force_iter_first_csv"] == "33,40,45"
    assert vector["force_phys"] == {"33": 31, "40": 30, "45": 29}
    assert vector["force_phys_csv"] == "33:31,40:30,45:29"
    assert [target["current_reg_name"] for target in vector["targets"]] == [
        "r27", "r26", "r29",
    ]
    assert [target["already_target"] for target in vector["targets"]] == [
        False, False, True,
    ]


def test_restore_object_report_help_exposes_guarded_cleanup_command() -> None:
    proc = subprocess.run(
        [
            "python", "-m", "src.cli", "debug", "dump", "restore-object-report",
            "--help",
        ],
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
    assert "/dev/null" not in cmd
    output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
    assert output_path.parent == src_path.parent
    assert output_path.name.startswith(".fn_80247510.auto-verify.")


def test_force_vector_parser_accepts_phys_coalesce_iter_and_iter_first() -> None:
    entries = debug_cli._parse_force_vector(
        "ig40:phys=r30,ig42:coalesce=38,class0:iter5:phys=r31,ig50:iter-first"
    )

    assert [entry.kind for entry in entries] == [
        "force_phys",
        "force_coalesce",
        "force_phys_iter",
        "force_iter_first",
    ]
    assert entries[0].ig_idx == 40
    assert entries[0].phys == 30
    assert entries[1].ig_idx == 42
    assert entries[1].root == 38
    assert entries[2].class_id == 0
    assert entries[2].iter_idx == 5
    assert entries[2].phys == 31
    assert entries[3].ig_idx == 50


def test_force_vector_auto_verify_command_scopes_all_force_types(
    tmp_path: pathlib.Path,
) -> None:
    src_path = tmp_path / "sample.c"
    src_path.write_text("void fn_test(void) {}\n", encoding="utf-8")
    entries = debug_cli._parse_force_vector(
        "ig40:phys=r30,ig42:coalesce=38,class0:iter5:phys=r31,ig50:iter-first"
    )
    output = tmp_path / "forced.pcdump.txt"

    cmd = debug_cli._build_force_vector_auto_verify_cmd(
        src_path=src_path,
        function="fn_test",
        entries=entries,
        output_path=output,
        checkdiff_timeout=12.5,
    )

    assert cmd[:6] == [
        sys.executable,
        "-m",
        "src.cli",
        "debug",
        "dump",
        "local",
    ]
    assert "--force-phys" in cmd
    assert cmd[cmd.index("--force-phys") + 1] == "40:30"
    assert "--force-phys-iter" in cmd
    assert cmd[cmd.index("--force-phys-iter") + 1] == "0:5:31"
    assert "--force-phys-fn" in cmd
    assert cmd[cmd.index("--force-phys-fn") + 1] == "fn_test"
    assert "--force-coalesce" in cmd
    assert cmd[cmd.index("--force-coalesce") + 1] == "42=38"
    assert "--force-coalesce-fn" in cmd
    assert cmd[cmd.index("--force-coalesce-fn") + 1] == "fn_test"
    assert "--force-iter-first" in cmd
    assert cmd[cmd.index("--force-iter-first") + 1] == "50"
    assert "--force-iter-first-fn" in cmd
    assert cmd[cmd.index("--force-iter-first-fn") + 1] == "fn_test"
    assert "--diff" in cmd
    assert "--function" in cmd
    assert cmd[cmd.index("--function") + 1] == "fn_test"
    assert "--checkdiff-timeout" in cmd
    assert cmd[cmd.index("--checkdiff-timeout") + 1] == "12.5"
    assert str(output) in cmd


def test_force_vector_auto_verify_runs_union_singles_and_prefixes(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    src_path = tmp_path / "sample.c"
    src_path.write_text("void fn_test(void) {}\n", encoding="utf-8")
    entries = debug_cli._parse_force_vector(
        "ig40:phys=r30,ig42:coalesce=38,ig50:iter-first"
    )
    calls: list[list[str]] = []

    def fake_run(cmd, *, cwd, status_label, phase="testing",
                 status_interval_s=10.0, timeout_s=None, env=None):
        calls.append(cmd)
        stdout = "[diff] MATCH - function bytes are identical.\n" if "union" in status_label else "diff remained\n"
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(
        debug_cli,
        "_run_auto_verify_command_with_status",
        fake_run,
    )

    result = debug_cli._run_force_vector_auto_verify(
        src_path=src_path,
        function="fn_test",
        entries=entries,
        melee_root=tmp_path,
        checkdiff_timeout=30.0,
        run_diagnostic_probes=True,
    )

    labels = [probe["label"] for probe in result["probes"]]
    assert result["union"]["match"] is True
    assert labels == [
        "single[1]",
        "single[2]",
        "single[3]",
        "prefix[1..2]",
    ]
    assert all(probe["match"] is False for probe in result["probes"])
    assert len(calls) == 5
    assert all("--diff" in call for call in calls)
    assert calls[0][calls[0].index("--force-phys") + 1] == "40:30"
    assert calls[0][calls[0].index("--force-coalesce") + 1] == "42=38"
    assert calls[0][calls[0].index("--force-iter-first") + 1] == "50"


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


def test_hsd_assert_override_guidance_is_self_contained() -> None:
    guidance = debug_cli._format_hsd_assert_override_guidance()

    assert "MEMORY.md" not in guidance
    assert "#include <baselib/debug.h>" in guidance
    assert "#undef HSD_ASSERT" in guidance
    assert "__assert(<file_sym>, line, <fn_sym>)" in guidance
    assert "transitively" in guidance
    assert "may be neutral" in guidance
    assert "nearby affected functions" in guidance


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


def test_expensive_restore_guard_explains_stale_metadata_and_preview() -> None:
    result = debug_cli._make_expensive_restore_result(
        ["ninja", "build/GALE01/src/melee/mn/mnvibration.o"],
        planned_steps=575,
        max_steps=64,
        dry_run_output=(
            "[1/575] Linking build/GALE01/report.json\n"
            "[2/575] Compiling src/melee/mn/mnvibration.c\n"
        ),
    )

    assert "dry-run preview" in result.stderr
    assert "[1/575] Linking build/GALE01/report.json" in result.stderr
    assert "report.json is older than build.ninja" in result.stderr
    assert "no metadata-only repair" in result.stderr


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
