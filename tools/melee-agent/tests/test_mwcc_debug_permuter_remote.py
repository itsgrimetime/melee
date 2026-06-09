from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.mwcc_debug import permuter_remote as pr


def test_load_targets_parses_config(tmp_path: Path) -> None:
    config = tmp_path / "permuter-remotes.toml"
    config.write_text(
        """
[target.coder64]
ssh = "coder.coder64"
remote_melee_root = "/home/coder/melee"
remote_perm_root = "/home/coder/decomp-permuter"
threads = 64
session_prefix = "melee-perm"
""".strip()
        + "\n"
    )

    targets = pr.load_targets(config)

    assert targets["coder64"] == pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )


def test_load_targets_missing_config_has_example(tmp_path: Path) -> None:
    missing = tmp_path / "permuter-remotes.toml"

    with pytest.raises(pr.RemoteConfigError) as exc:
        pr.load_targets(missing)

    msg = str(exc.value)
    assert str(missing) in msg
    assert "[target.coder64]" in msg
    assert "remote_perm_root" in msg


def test_remote_targets_cli_missing_config_mentions_example(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(pr, "CONFIG_PATH", tmp_path / "missing.toml")
    result = CliRunner().invoke(app, ["debug", "permute", "remote", "targets"])

    assert result.exit_code == 2
    combined = result.stdout + result.stderr
    assert "Remote permuter config not found" in combined
    assert "[target.coder64]" in combined


def test_remote_tail_cli_streams_and_exits_2_on_tail_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = _sample_job(tmp_path)
    seen_runner = False

    def fake_read_job(job_id: str, jobs_dir: Path = pr.JOBS_DIR) -> pr.RemoteJob:
        assert job_id == job.job_id
        return job

    def fake_tail_job(
        loaded_job: pr.RemoteJob,
        *,
        runner,
        lines: int = 80,
        follow: bool = False,
    ) -> pr.CommandResult:
        nonlocal seen_runner
        seen_runner = runner is not pr.run_command
        assert loaded_job == job
        assert lines == 12
        assert follow is True
        return pr.CommandResult(returncode=1, stdout="", stderr="missing log\n")

    monkeypatch.setattr(pr, "read_job", fake_read_job)
    monkeypatch.setattr(pr, "tail_job", fake_tail_job)

    result = CliRunner().invoke(
        app,
        [
            "debug",
            "permute",
            "remote",
            "tail",
            job.job_id,
            "--lines",
            "12",
            "--follow",
        ],
    )

    assert result.exit_code == 2
    assert seen_runner
    assert "missing log" in result.stderr


def test_remote_tail_cli_help_documents_snapshot_and_follow() -> None:
    result = CliRunner().invoke(
        app,
        ["debug", "permute", "remote", "tail", "--help"],
    )

    assert result.exit_code == 0
    assert "--follow" in result.stdout
    assert "--no-follow" in result.stdout
    assert "snapshot" in result.stdout.lower()


def test_remote_tail_cli_sanitizes_carriage_return_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = _sample_job(tmp_path)

    def fake_read_job(job_id: str, jobs_dir: Path = pr.JOBS_DIR) -> pr.RemoteJob:
        assert job_id == job.job_id
        return job

    def fake_tail_job(
        loaded_job: pr.RemoteJob,
        *,
        runner,
        lines: int = 80,
        follow: bool = False,
    ) -> pr.CommandResult:
        assert loaded_job == job
        assert lines == 3
        assert follow is False
        return pr.CommandResult(
            returncode=0,
            stdout=(
                "started\n"
                "iter 1 score 120\riter 2 score 115\riter 3 score 110\r"
                "done\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(pr, "read_job", fake_read_job)
    monkeypatch.setattr(pr, "tail_job", fake_tail_job)

    result = CliRunner().invoke(
        app,
        ["debug", "permute", "remote", "tail", job.job_id, "--lines", "3"],
    )

    assert result.exit_code == 0
    assert "\r" not in result.stdout
    assert "iter 1 score" not in result.stdout
    assert "iter 2 score 115" in result.stdout
    assert "iter 3 score 110" in result.stdout
    assert "done" in result.stdout


def test_remote_status_reports_stale_age_and_cleanup_guidance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = _sample_job(tmp_path)
    now = pr.parse_timestamp("2026-05-27T15:30:12")

    def fake_read_job(job_id: str, jobs_dir: Path = pr.JOBS_DIR) -> pr.RemoteJob:
        assert job_id == job.job_id
        return job

    def fake_status_job(
        loaded_job: pr.RemoteJob,
    ) -> pr.RemoteStatus:
        assert loaded_job == job
        return pr.RemoteStatus(job_id=job.job_id, state="active")

    def fake_remote_log_status(
        loaded_job: pr.RemoteJob,
    ) -> pr.RemoteLogStatus:
        assert loaded_job == job
        return pr.RemoteLogStatus(
            exists=True,
            modified_at=pr.parse_timestamp("2026-05-26T14:30:12"),
            best_score="99.71%",
        )

    monkeypatch.setattr(pr, "read_job", fake_read_job)
    monkeypatch.setattr(pr, "status_job", fake_status_job)
    monkeypatch.setattr(pr, "remote_log_status", fake_remote_log_status)
    monkeypatch.setattr(pr, "utcnow", lambda: now)

    result = CliRunner().invoke(
        app,
        [
            "debug",
            "permute",
            "remote",
            "status",
            job.job_id,
            "--stale-hours",
            "24",
            "--idle-hours",
            "12",
        ],
    )

    assert result.exit_code == 0
    assert f"{job.job_id}: active" in result.stdout
    assert "wall age: 49.0h" in result.stdout
    assert "log idle: 25.0h" in result.stdout
    assert "best score: 99.71%" in result.stdout
    assert "recommendation: stop" in result.stdout
    assert f"melee-agent debug permute remote stop {job.job_id}" in result.stdout


def test_parse_permuter_log_summary_uses_global_min_not_latest() -> None:
    summary = pr.parse_permuter_log_summary(
        (
            "[fn_80169900] base score = 1000\n"
            "iteration 5726, 1 errors, score = 20\r"
            "iteration 7679, 1 errors, score = 1390\r"
            "wrote to remote-runs/job/nonmatchings/fn_80169900/output-20-1\n"
        )
    )

    assert summary.global_best_score == 20
    assert summary.global_best_iteration == 5726
    assert summary.latest_score == 1390
    assert summary.latest_iteration == 7679
    assert summary.match_found is False
    assert summary.output_candidate_saved is True


def test_parse_permuter_log_summary_detects_zero_match() -> None:
    summary = pr.parse_permuter_log_summary(
        (
            "iteration 10, 1 errors, score = 50\r"
            "iteration 12, 0 errors, score = 0\n"
            "wrote to remote-runs/job/nonmatchings/fn_8001EBF0/output-0-0\n"
        )
    )

    assert summary.global_best_score == 0
    assert summary.global_best_iteration == 12
    assert summary.match_found is True
    assert summary.output_candidate_saved is True
    assert summary.verdict == "match"


def test_remote_log_status_reads_full_log_summary(tmp_path: Path) -> None:
    job = _sample_job(tmp_path)
    scripts: list[str] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        scripts.append(argv[2])
        return pr.CommandResult(
            returncode=0,
            stdout=(
                "exists\t1\n"
                "mtime\t1770000000\n"
                "has_output\t1\n"
                "log_begin\n"
                "iteration 1, 1 errors, score = 50\r"
                "iteration 2, 1 errors, score = 1155\r"
                "iteration 3, 1 errors, score = 20\r"
                "iteration 4, 1 errors, score = 1390\r"
            ),
            stderr="",
        )

    status = pr.remote_log_status(job, runner=fake_runner)

    assert "cat \"$log\"" in scripts[0]
    assert "tail -c 65536" not in scripts[0]
    assert status.exists is True
    assert status.global_best_score == 20
    assert status.global_best_iteration == 3
    assert status.latest_score == 1390
    assert status.latest_iteration == 4
    assert status.output_candidate_saved is True


def test_remote_status_prints_global_min_latest_match_and_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = _sample_job(tmp_path)

    def fake_read_job(job_id: str, jobs_dir: Path = pr.JOBS_DIR) -> pr.RemoteJob:
        assert job_id == job.job_id
        return job

    def fake_status_job(loaded_job: pr.RemoteJob) -> pr.RemoteStatus:
        assert loaded_job == job
        return pr.RemoteStatus(job_id=job.job_id, state="active")

    def fake_remote_log_status(loaded_job: pr.RemoteJob) -> pr.RemoteLogStatus:
        assert loaded_job == job
        return pr.RemoteLogStatus(
            exists=True,
            modified_at=pr.parse_timestamp("2026-05-27T15:00:00"),
            global_best_score=20,
            global_best_iteration=5726,
            latest_score=1390,
            latest_iteration=7679,
            match_found=False,
            output_candidate_saved=True,
            verdict="ceiling",
        )

    monkeypatch.setattr(pr, "read_job", fake_read_job)
    monkeypatch.setattr(pr, "status_job", fake_status_job)
    monkeypatch.setattr(pr, "remote_log_status", fake_remote_log_status)
    monkeypatch.setattr(pr, "utcnow", lambda: pr.parse_timestamp("2026-05-27T15:30:00"))

    result = CliRunner().invoke(
        app,
        ["debug", "permute", "remote", "status", job.job_id],
    )

    assert result.exit_code == 0
    assert "best (global-min): 20 @iter5726" in result.stdout
    assert "latest: 1390 @iter7679" in result.stdout
    assert "match: no" in result.stdout
    assert "output candidate: yes" in result.stdout
    assert "verdict: ceiling" in result.stdout


def test_remote_triage_summarizes_local_jobs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = _sample_job(tmp_path)
    second = replace(
        first,
        job_id="fn_80000010-coder64-20260525-143012",
        function="fn_80000010",
    )

    def fake_list_jobs(jobs_dir: Path = pr.JOBS_DIR) -> list[pr.RemoteJob]:
        assert jobs_dir == pr.JOBS_DIR
        return [first, second]

    def fake_status_job(job: pr.RemoteJob) -> pr.RemoteStatus:
        return pr.RemoteStatus(job_id=job.job_id, state="active")

    def fake_remote_log_status(job: pr.RemoteJob) -> pr.RemoteLogStatus:
        if job == first:
            return pr.RemoteLogStatus(
                exists=True,
                global_best_score=20,
                global_best_iteration=5726,
                latest_score=1390,
                latest_iteration=7679,
                match_found=False,
                output_candidate_saved=True,
                verdict="ceiling",
            )
        return pr.RemoteLogStatus(
            exists=True,
            global_best_score=0,
            global_best_iteration=22,
            latest_score=0,
            latest_iteration=22,
            match_found=True,
            output_candidate_saved=True,
            verdict="match",
        )

    monkeypatch.setattr(pr, "list_jobs", fake_list_jobs)
    monkeypatch.setattr(pr, "status_job", fake_status_job)
    monkeypatch.setattr(pr, "remote_log_status", fake_remote_log_status)

    result = CliRunner().invoke(app, ["debug", "permute", "remote", "triage"])

    assert result.exit_code == 0
    assert "fn\tjob\tstate\titers\tglobal-min\tlatest\tmatch\toutput\tverdict" in result.stdout
    assert "fn_80000000" in result.stdout
    assert "20@5726" in result.stdout
    assert "1390@7679" in result.stdout
    assert "no\tyes\tceiling" in result.stdout
    assert "fn_80000010" in result.stdout
    assert "0@22" in result.stdout
    assert "yes\tyes\tmatch" in result.stdout


def test_remote_triage_filters_function_and_forwards_probe_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = _sample_job(tmp_path)
    second = replace(
        first,
        job_id="fn_80000010-coder64-20260525-143012",
        function="fn_80000010",
    )
    seen_status: list[tuple[str, float | None]] = []
    seen_logs: list[tuple[str, float | None]] = []

    monkeypatch.setattr(pr, "list_jobs", lambda jobs_dir=pr.JOBS_DIR: [first, second])

    def fake_status_job(
        job: pr.RemoteJob,
        *,
        timeout: float | None = None,
    ) -> pr.RemoteStatus:
        seen_status.append((job.function, timeout))
        return pr.RemoteStatus(job_id=job.job_id, state="active")

    def fake_remote_log_status(
        job: pr.RemoteJob,
        *,
        timeout: float | None = None,
    ) -> pr.RemoteLogStatus:
        seen_logs.append((job.function, timeout))
        return pr.RemoteLogStatus(exists=False)

    monkeypatch.setattr(pr, "status_job", fake_status_job)
    monkeypatch.setattr(pr, "remote_log_status", fake_remote_log_status)

    result = CliRunner().invoke(
        app,
        [
            "debug",
            "permute",
            "remote",
            "triage",
            "-f",
            "fn_80000010",
            "--timeout",
            "0.25",
        ],
    )

    assert result.exit_code == 0
    assert "fn_80000010" in result.stdout
    assert "fn_80000000" not in result.stdout
    assert seen_status == [("fn_80000010", 0.25)]
    assert seen_logs == [("fn_80000010", 0.25)]


def test_run_command_returns_timeout_result_when_check_disabled() -> None:
    result = pr.run_command(
        [sys.executable, "-c", "import time; time.sleep(1)"],
        timeout=0.01,
        check=False,
    )

    assert result.returncode == 124
    assert "timed out after 0.01s" in result.stderr


def test_permute_local_orphans_cli_reports_uninterruptible_wibo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pr,
        "detect_orphaned_wibo_processes",
        lambda: [
            pr.OrphanedWiboProcess(
                pid=24276,
                ppid=1,
                stat="UE",
                elapsed="40:01:02",
                command=(
                    "build/tools/wibo build/compilers/GC/1.2.5n/"
                    "mwcceppc.exe -c src/melee/ft/ftdynamics.c"
                ),
            )
        ],
    )

    result = CliRunner().invoke(app, ["debug", "permute", "local-orphans"])

    assert result.exit_code == 1
    assert "24276" in result.stdout
    assert "STAT=UE" in result.stdout
    assert "uninterruptible" in result.stdout
    assert "restart" in result.stdout.lower()


def test_remote_doctor_cli_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    monkeypatch.setattr(pr, "load_targets", lambda config_path=pr.CONFIG_PATH: {"coder64": target})
    monkeypatch.setattr(
        pr,
        "doctor_target",
        lambda loaded_target, local_perm_dir=None: pr.DoctorReport(
            target=loaded_target.name,
            checks=[
                pr.DoctorCheck("remote tmux", True, "/usr/bin/tmux"),
                pr.DoctorCheck("remote python3 toml", False, "No module named toml"),
            ],
        ),
    )

    result = CliRunner().invoke(
        app,
        ["debug", "permute", "remote", "doctor", "--target", "coder64"],
    )

    assert result.exit_code == 2
    assert "PASS\tremote tmux\trequired - /usr/bin/tmux" in result.stdout
    assert "FAIL\tremote python3 toml\trequired - No module named toml" in result.stdout


def test_remote_submit_cli_suggests_healthy_target_after_preflight_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    function = "fn_80000000"
    perm_root = tmp_path / "decomp-permuter"
    perm_dir = perm_root / "nonmatchings" / function
    perm_dir.mkdir(parents=True)
    (perm_dir / "base.c").write_text("void fn_80000000(void) {}\n")
    coder2 = pr.RemoteTarget(
        name="coder2",
        ssh="coder2.example",
        remote_melee_root="/home/discord/melee",
        remote_perm_root="/home/discord/decomp-permuter",
        threads=16,
        session_prefix="melee-perm",
    )
    coder3 = pr.RemoteTarget(
        name="coder3",
        ssh="coder3.example",
        remote_melee_root="/home/discord/melee",
        remote_perm_root="/home/discord/decomp-permuter",
        threads=16,
        session_prefix="melee-perm",
    )

    def fake_submit_job(**kwargs: object) -> pr.RemoteJob:
        assert kwargs["target"] == coder2
        assert kwargs["local_perm_dir"] == perm_dir
        raise pr.RemoteJobError(
            "remote preflight failed for coder2: remote melee root: "
            "/home/discord/melee missing"
        )

    def fake_suggest_ready_targets(
        targets: dict[str, pr.RemoteTarget],
        *,
        failed_target_name: str,
        local_perm_dir: Path | None = None,
    ) -> list[str]:
        assert targets == {"coder2": coder2, "coder3": coder3}
        assert failed_target_name == "coder2"
        assert local_perm_dir == perm_dir
        return ["coder3"]

    monkeypatch.setattr(pr, "load_targets", lambda config_path=pr.CONFIG_PATH: {
        "coder2": coder2,
        "coder3": coder3,
    })
    monkeypatch.setattr(pr, "submit_job", fake_submit_job)
    monkeypatch.setattr(pr, "suggest_ready_targets", fake_suggest_ready_targets, raising=False)

    result = CliRunner().invoke(
        app,
        [
            "debug", "permute", "remote", "submit",
            "-f", function,
            "--target", "coder2",
            "--perm-root", str(perm_root),
        ],
    )

    assert result.exit_code == 2
    assert "remote preflight failed for coder2" in result.stderr
    assert "Healthy configured target(s): coder3" in result.stderr
    assert "Retry with --target coder3" in result.stderr


def test_remote_doctor_cli_repair_runs_before_final_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )
    artifact_root = tmp_path / "matcher-worktree"
    function_dir = artifact_root / "nonmatchings" / "fn_80000000"
    function_dir.mkdir(parents=True)
    decomp_root = tmp_path / "decomp-permuter"
    (decomp_root / "src").mkdir(parents=True)
    (decomp_root / "permuter.py").write_text("#!/usr/bin/env python3\n")
    (decomp_root / "src" / "compiler.py").write_text("# compiler\n")
    repaired = False

    def fake_repair_target(
        loaded_target: pr.RemoteTarget,
        *,
        local_melee_root: Path,
        local_perm_root: Path,
        function: str | None = None,
        local_perm_dir: Path | None = None,
    ) -> pr.RepairReport:
        nonlocal repaired
        repaired = True
        assert loaded_target == target
        assert function == "fn_80000000"
        assert local_perm_dir == function_dir
        assert local_perm_root == decomp_root
        return pr.RepairReport(target=target.name, actions=["synced tooling"])

    def fake_doctor_target(
        loaded_target: pr.RemoteTarget,
        local_perm_dir: Path | None = None,
    ) -> pr.DoctorReport:
        assert repaired
        assert loaded_target == target
        assert local_perm_dir == function_dir
        return pr.DoctorReport(
            target=loaded_target.name,
            checks=[pr.DoctorCheck("remote tmux", True, "/usr/bin/tmux")],
        )

    monkeypatch.setattr(pr, "load_targets", lambda config_path=pr.CONFIG_PATH: {"coder64": target})
    monkeypatch.setattr(pr, "repair_target", fake_repair_target, raising=False)
    monkeypatch.setattr(pr, "doctor_target", fake_doctor_target)
    monkeypatch.setenv("MELEE_DECOMP_PERMUTER_ROOT", str(decomp_root))

    result = CliRunner().invoke(
        app,
        [
            "debug", "permute", "remote", "doctor",
            "--target", "coder64",
            "--function", "fn_80000000",
            "--perm-root", str(artifact_root),
            "--repair",
        ],
    )

    assert result.exit_code == 0
    assert "REPAIR\tsynced tooling" in result.stdout
    assert "PASS\tremote tmux\trequired - /usr/bin/tmux" in result.stdout


def test_load_targets_uses_conservative_defaults(tmp_path: Path) -> None:
    config = tmp_path / "permuter-remotes.toml"
    config.write_text(
        """
[target.coder64]
ssh = "coder.coder64"
remote_melee_root = "/home/coder/melee"
remote_perm_root = "/home/coder/decomp-permuter"
""".strip()
        + "\n"
    )

    target = pr.load_targets(config)["coder64"]

    assert target.threads == 1
    assert target.session_prefix == "melee-perm"


def test_load_targets_rejects_boolean_threads(tmp_path: Path) -> None:
    config = tmp_path / "permuter-remotes.toml"
    config.write_text(
        """
[target.coder64]
ssh = "coder.coder64"
remote_melee_root = "/home/coder/melee"
remote_perm_root = "/home/coder/decomp-permuter"
threads = true
""".strip()
        + "\n"
    )

    with pytest.raises(pr.RemoteConfigError) as exc:
        pr.load_targets(config)

    msg = str(exc.value)
    assert "threads" in msg
    assert "invalid positive integer" in msg


def test_job_metadata_round_trip(tmp_path: Path) -> None:
    job = pr.RemoteJob(
        job_id="fn_80000000-coder64-20260525-143012",
        function="fn_80000000",
        target="coder64",
        ssh="coder.coder64",
        remote_perm_dir=(
            "/home/coder/decomp-permuter/remote-runs/"
            "fn_80000000-coder64-20260525-143012/nonmatchings/fn_80000000"
        ),
        remote_run_dir="/home/coder/decomp-permuter/remote-runs/fn_80000000-coder64-20260525-143012",
        local_perm_dir="/tmp/decomp-permuter/nonmatchings/fn_80000000",
        tmux_session="melee-perm-fn_80000000-coder64-20260525-143012",
        threads=64,
        mode="stock",
        created_at="2026-05-25T14:30:12",
    )

    pr.write_job(job, jobs_dir=tmp_path)
    loaded = pr.read_job(job.job_id, jobs_dir=tmp_path)

    assert loaded == job
    assert json.loads((tmp_path / f"{job.job_id}.json").read_text())["function"] == "fn_80000000"


def _sample_job(tmp_path: Path) -> pr.RemoteJob:
    return pr.RemoteJob(
        job_id="fn_80000000-coder64-20260525-143012",
        function="fn_80000000",
        target="coder64",
        ssh="coder.coder64",
        remote_perm_dir=(
            "/home/coder/decomp-permuter/remote-runs/"
            "fn_80000000-coder64-20260525-143012/nonmatchings/fn_80000000"
        ),
        remote_run_dir="/home/coder/decomp-permuter/remote-runs/fn_80000000-coder64-20260525-143012",
        local_perm_dir=str(tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"),
        tmux_session="melee-perm-fn_80000000-coder64-20260525-143012",
        threads=64,
        mode="stock",
        created_at="2026-05-25T14:30:12",
    )


def test_status_job_reports_active_from_tmux(tmp_path: Path) -> None:
    job = _sample_job(tmp_path)
    calls: list[list[str]] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(returncode=0, stdout="active\n", stderr="")

    status = pr.status_job(job, runner=fake_runner)

    assert status == pr.RemoteStatus(
        job_id="fn_80000000-coder64-20260525-143012",
        state="active",
        detail="",
    )
    assert calls == [
        [
            "ssh",
            "coder.coder64",
            "sh -lc 'tmux has-session -t melee-perm-fn_80000000-coder64-20260525-143012 2>/dev/null && printf active || printf stopped'",
        ]
    ]


def test_status_job_reports_unknown_on_ssh_failure(tmp_path: Path) -> None:
    job = _sample_job(tmp_path)

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        return pr.CommandResult(returncode=255, stdout="", stderr="ssh: Could not resolve hostname\n")

    status = pr.status_job(job, runner=fake_runner)

    assert status == pr.RemoteStatus(
        job_id="fn_80000000-coder64-20260525-143012",
        state="unknown",
        detail="ssh: Could not resolve hostname",
    )


def test_fetch_job_rsyncs_outputs_to_run_dir(tmp_path: Path) -> None:
    job = _sample_job(tmp_path)
    calls: list[list[str]] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        if argv and argv[0] == "ssh" and "remote-rsync" in argv[2]:
            return pr.CommandResult(returncode=0, stdout=_remote_doctor_ok_stdout(), stderr="")
        return pr.CommandResult(returncode=0, stdout="", stderr="")

    dest = pr.fetch_job(job, runner=fake_runner)

    assert dest == Path(job.local_perm_dir) / "remote-runs" / job.job_id
    assert dest.is_dir()
    assert len(calls) == 2
    assert calls[0][0] == "rsync"
    assert "remote-runs/***" not in calls[0]
    assert calls[0][-2] == (
        "coder.coder64:/home/coder/decomp-permuter/remote-runs/"
        "fn_80000000-coder64-20260525-143012/nonmatchings/fn_80000000/"
    )
    assert calls[0][-1] == str(dest) + "/"
    assert calls[1][0] == "rsync"
    assert "--prune-empty-dirs" in calls[1]
    nonmatchings_dir_include = calls[1].index("nonmatchings/")
    function_dir_include = calls[1].index("nonmatchings/fn_80000000/")
    target_include = calls[1].index("nonmatchings/fn_80000000/target.o")
    nonmatchings_exclude = calls[1].index("nonmatchings/***")
    metadata_include = calls[1].index("metadata.json")
    assert calls[1][nonmatchings_dir_include - 1] == "--include"
    assert calls[1][function_dir_include - 1] == "--include"
    assert calls[1][target_include - 1] == "--include"
    assert calls[1][nonmatchings_exclude - 1] == "--exclude"
    assert metadata_include < nonmatchings_dir_include
    assert target_include < nonmatchings_exclude
    assert "metadata.json" in calls[1]
    assert "*.log" in calls[1]
    assert "--exclude" in calls[1]
    assert calls[1][-2] == (
        "coder.coder64:/home/coder/decomp-permuter/remote-runs/"
        "fn_80000000-coder64-20260525-143012/"
    )
    assert calls[1][-1] == str(dest / "remote-run") + "/"


def test_fetch_job_writes_candidate_audit_summary(tmp_path: Path) -> None:
    job = _sample_job(tmp_path)

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        if argv and argv[0] == "rsync" and "output-*/***" in argv:
            dest = Path(argv[-1])
            output_dir = dest / "output-125-2"
            output_dir.mkdir(parents=True)
            (output_dir / "source.c").write_text(
                "void fn_80000000(void) { inline_fn(); }\n"
            )
        return pr.CommandResult(returncode=0, stdout="", stderr="")

    dest = pr.fetch_job(job, runner=fake_runner)

    summary = json.loads((dest / "candidate_audit.json").read_text())
    assert summary["total"] == 1
    assert summary["by_status"]["corrupt-candidate"] == 1
    sidecar = dest / "output-125-2" / "melee-agent-candidate-status.json"
    assert json.loads(sidecar.read_text())["status"] == "corrupt-candidate"


def test_tail_job_snapshots_remote_permuter_log_by_default(tmp_path: Path) -> None:
    job = _sample_job(tmp_path)
    calls: list[list[str]] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(returncode=0, stdout="", stderr="")

    pr.tail_job(job, runner=fake_runner, lines=20)

    assert calls == [
        [
            "ssh",
            "coder.coder64",
            "sh -lc 'tail -c 65536 /home/coder/decomp-permuter/remote-runs/fn_80000000-coder64-20260525-143012/permuter.log'",
        ]
    ]


def test_tail_job_follow_is_opt_in(tmp_path: Path) -> None:
    job = _sample_job(tmp_path)
    calls: list[list[str]] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(returncode=0, stdout="", stderr="")

    pr.tail_job(job, runner=fake_runner, lines=20, follow=True)

    assert calls == [
        [
            "ssh",
            "coder.coder64",
            "sh -lc 'tail -n 20 -f /home/coder/decomp-permuter/remote-runs/fn_80000000-coder64-20260525-143012/permuter.log'",
        ]
    ]


def test_tail_job_requires_explicit_streaming_runner_for_follow(tmp_path: Path) -> None:
    job = _sample_job(tmp_path)

    with pytest.raises(pr.RemoteJobError) as exc:
        pr.tail_job(job, follow=True)

    msg = str(exc.value)
    assert "explicit" in msg
    assert "streaming runner" in msg


@pytest.mark.parametrize("lines", [-1, 0, "20", True])
def test_tail_job_rejects_invalid_lines(tmp_path: Path, lines: object) -> None:
    job = _sample_job(tmp_path)
    calls: list[list[str]] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(returncode=0, stdout="", stderr="")

    with pytest.raises(pr.RemoteJobError) as exc:
        pr.tail_job(job, runner=fake_runner, lines=lines)  # type: ignore[arg-type]

    assert "lines" in str(exc.value)
    assert calls == []


def test_stop_job_kills_tmux_session(tmp_path: Path) -> None:
    job = _sample_job(tmp_path)
    calls: list[list[str]] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(returncode=0, stdout="", stderr="")

    pr.stop_job(job, runner=fake_runner)

    assert calls == [["ssh", "coder.coder64", "sh -lc 'tmux kill-session -t melee-perm-fn_80000000-coder64-20260525-143012'"]]


def _remote_doctor_ok_stdout() -> str:
    return "\n".join(
        [
            "remote-sh\tok\tsh",
            "remote-rsync\tok\t/usr/bin/rsync",
            "remote-tmux\tok\t/usr/bin/tmux",
            "remote-python3\tok\t/usr/bin/python3",
            "remote-melee-root\tok\t/home/coder/melee",
            "remote-perm-root\tok\t/home/coder/decomp-permuter",
            "remote-permuter-py\tok\t/home/coder/decomp-permuter/permuter.py",
            "remote-mwcc\tok\t/home/coder/melee/build/compilers/GC/1.2.5n/mwcceppc_debug.exe",
            "remote-wibo\tok\t/home/coder/melee/tools/mwcc_debug/bin/wibo",
            "remote-melee-agent\tok\t/home/coder/.local/bin/melee-agent",
            "remote-python3-toml\tok\ttoml ok",
        ]
    ) + "\n"


def test_doctor_target_reports_ready_remote_and_local_perm_dir(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "compile.sh").write_text("#!/bin/sh\n")
    (local_perm / "settings.toml").write_text(
        'objdump_command = "/usr/bin/powerpc-linux-gnu-objdump -dr"\n'
    )
    calls: list[list[str]] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(
            returncode=0,
            stdout=(
                _remote_doctor_ok_stdout()
                + "remote-objdump-command\tok\t/usr/bin/powerpc-linux-gnu-objdump\n"
            ),
            stderr="",
        )

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    report = pr.doctor_target(target, local_perm_dir=local_perm, runner=fake_runner)

    assert report.ok
    assert calls[0][:2] == ["ssh", "coder.coder64"]
    assert "python3" in calls[0][2]
    assert "import toml" in calls[0][2]
    assert "remote-objdump-command" in calls[0][2]
    assert {check.name: check.ok for check in report.checks}["local path leaks"]
    assert {check.name: check.ok for check in report.checks}["remote objdump command"]


def test_suggest_ready_targets_skips_failed_target_and_unhealthy_siblings() -> None:
    targets = {
        "coder2": pr.RemoteTarget(
            name="coder2",
            ssh="coder2.example",
            remote_melee_root="/home/discord/melee",
            remote_perm_root="/home/discord/decomp-permuter",
            threads=16,
            session_prefix="melee-perm",
        ),
        "coder1": pr.RemoteTarget(
            name="coder1",
            ssh="coder1.example",
            remote_melee_root="/home/discord/permuter-work/melee",
            remote_perm_root="/home/discord/permuter-work/decomp-permuter",
            threads=16,
            session_prefix="melee-perm",
        ),
        "coder3": pr.RemoteTarget(
            name="coder3",
            ssh="coder3.example",
            remote_melee_root="/home/discord/melee",
            remote_perm_root="/home/discord/decomp-permuter",
            threads=16,
            session_prefix="melee-perm",
        ),
    }
    probed: list[str] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        probed.append(argv[1])
        if argv[1] == "coder3.example":
            return pr.CommandResult(returncode=0, stdout=_remote_doctor_ok_stdout(), stderr="")
        return pr.CommandResult(returncode=255, stdout="", stderr="ssh failed\n")

    suggestions = pr.suggest_ready_targets(
        targets,
        failed_target_name="coder2",
        runner=fake_runner,
    )

    assert suggestions == ["coder3"]
    assert probed == ["coder1.example", "coder3.example"]


def test_doctor_target_flags_missing_remote_objdump_from_settings(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "compile.sh").write_text("#!/bin/sh\n")
    (local_perm / "settings.toml").write_text(
        'objdump_command = "/opt/devkitpro/devkitPPC/bin/powerpc-eabi-objdump -dr"\n'
    )

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    report = pr.doctor_target(
        target,
        local_perm_dir=local_perm,
        runner=lambda argv, **kwargs: pr.CommandResult(
            returncode=0,
            stdout=(
                _remote_doctor_ok_stdout()
                + "remote-objdump-command\tfail\t/opt/devkitpro/devkitPPC/bin/powerpc-eabi-objdump not found or not executable\n"
            ),
            stderr="",
        ),
    )

    assert not report.ok
    objdump_check = next(
        check for check in report.checks if check.name == "remote objdump command"
    )
    assert not objdump_check.ok
    assert "powerpc-eabi-objdump" in objdump_check.detail


def test_doctor_target_uses_staged_remote_objdump_for_local_absolute_settings(
    tmp_path: Path,
) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "compile.sh").write_text("#!/bin/sh\n")
    (local_perm / "settings.toml").write_text(
        'objdump_command = "/opt/devkitpro/devkitPPC/bin/powerpc-eabi-objdump -dr"\n'
    )

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )
    calls: list[list[str]] = []

    def fake_runner(argv: list[str], **_: object) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(
            returncode=0,
            stdout=(
                _remote_doctor_ok_stdout()
                + "remote-objdump-command\tok\tmelee-agent debug target dtk-objdump --help\n"
            ),
            stderr="",
        )

    report = pr.doctor_target(target, local_perm_dir=local_perm, runner=fake_runner)

    assert report.ok
    remote_script = calls[0][2]
    assert "/opt/devkitpro/devkitPPC/bin/powerpc-eabi-objdump" not in remote_script
    assert "melee-agent debug target dtk-objdump --melee-root /home/coder/melee" in remote_script


def test_doctor_target_checks_full_objdump_command(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "compile.sh").write_text("#!/bin/sh\n")
    (local_perm / "settings.toml").write_text(
        'objdump_command = "melee-agent debug target dtk-objdump"\n'
    )

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )
    calls: list[list[str]] = []

    def fake_runner(argv: list[str], **_: object) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(
            returncode=0,
            stdout=_remote_doctor_ok_stdout()
            + "remote-objdump-command\tok\tmelee-agent debug target dtk-objdump --help\n",
            stderr="",
        )

    report = pr.doctor_target(target, local_perm_dir=local_perm, runner=fake_runner)

    assert report.ok
    remote_script = calls[0][2]
    assert "melee-agent debug target dtk-objdump --melee-root /home/coder/melee" in remote_script
    assert "$HOME/.local/bin/melee-agent" in remote_script
    assert "MELEE_ROOT=\"$melee_root\"" in remote_script
    assert "objdump_run_command" in remote_script
    assert "objdump_probe" in remote_script
    assert "/home/coder/decomp-permuter/nonmatchings/fn_80000000/target.o" in remote_script


def test_doctor_target_objdump_failure_reports_command_rc_and_probe(
    tmp_path: Path,
) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "compile.sh").write_text("#!/bin/sh\n")
    (local_perm / "settings.toml").write_text(
        'objdump_command = "melee-agent debug target dtk-objdump"\n'
    )

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )
    calls: list[list[str]] = []

    def fake_runner(argv: list[str], **_: object) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(returncode=0, stdout=_remote_doctor_ok_stdout(), stderr="")

    pr.doctor_target(target, local_perm_dir=local_perm, runner=fake_runner)

    remote_script = calls[0][2]
    assert "rc=$objdump_rc" in remote_script
    assert "command=$objdump_run_command" in remote_script
    assert "target=$objdump_probe" in remote_script
    assert "stdout_stderr=$objdump_out" in remote_script


def test_doctor_target_treats_local_runner_fallback_block_as_remote_ready(
    tmp_path: Path,
) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "compile.sh").write_text(
        """#!/usr/bin/env bash
cd /Users/mike/code/melee
if command -v wine >/dev/null 2>&1; then
    MWCC_RUNNER=wine
else
    MWCC_RUNNER=build/tools/wibo
fi
"$MWCC_RUNNER" build/compilers/GC/1.2.5n/mwcceppc.exe -Cpp_exceptions off "$INPUT" -o "$OUTPUT"
"""
    )
    (local_perm / "settings.toml").write_text("[score]\n")

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    report = pr.doctor_target(
        target,
        local_perm_dir=local_perm,
        runner=lambda argv, **kwargs: pr.CommandResult(
            returncode=0,
            stdout=_remote_doctor_ok_stdout(),
            stderr="",
        ),
    )

    checks = {check.name: check for check in report.checks}
    assert checks["local compile runner"].ok
    assert "remote Linux wibo" in checks["local compile runner"].detail


def test_doctor_target_treats_rewritable_compile_sh_as_remote_ready(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "compile.sh").write_text(
        """#!/usr/bin/env bash
INPUT_ABS="$(realpath "$1")"
OUTPUT_ABS="$(realpath "$3")"
cd /Users/mike/code/melee
STAGE="nonmatchings/.permuter_stage_$$.c"
cp "$INPUT_ABS" "$STAGE"
INPUT="$STAGE"
OUTPUT="$OUTPUT_ABS"
wine build/compilers/GC/1.2.5n/mwcceppc.exe -Cpp_exceptions off "$INPUT" -o "$OUTPUT"
"""
    )
    (local_perm / "settings.toml").write_text("[score]\n")

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    report = pr.doctor_target(
        target,
        local_perm_dir=local_perm,
        runner=lambda argv, **kwargs: pr.CommandResult(
            returncode=0,
            stdout=_remote_doctor_ok_stdout(),
            stderr="",
        ),
    )

    assert report.ok
    checks = {check.name: check for check in report.checks}
    assert checks["local path leaks"].ok
    assert checks["local compile runner"].ok
    assert "wibo" in checks["local compile runner"].detail


def test_doctor_target_flags_stale_validation_roots(tmp_path: Path) -> None:
    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        return pr.CommandResult(returncode=0, stdout=_remote_doctor_ok_stdout(), stderr="")

    target = pr.RemoteTarget(
        name="coder3",
        ssh="mike-grimes-dev-3.coder",
        remote_melee_root="/tmp/codex-remote-perm-123-remote-melee",
        remote_perm_root="/tmp/codex-remote-perm-123-remote-perm",
        threads=2,
        session_prefix="codex-validate",
    )

    report = pr.doctor_target(target, runner=fake_runner)

    assert not report.ok
    root_check = next(check for check in report.checks if check.name == "config target roots")
    assert not root_check.ok
    assert "/tmp/codex-remote-perm-123-remote-melee" in root_check.detail


def test_doctor_target_flags_yaml_local_path_leaks(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "compile.sh").write_text("#!/bin/sh\n")
    (local_perm / "settings.toml").write_text("[score]\n")
    (local_perm / "simplify_order_target.yaml").write_text(
        "baseline_dump: /Users/mike/code/melee/build/cache.txt\n"
    )

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        return pr.CommandResult(returncode=0, stdout=_remote_doctor_ok_stdout(), stderr="")

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    report = pr.doctor_target(target, local_perm_dir=local_perm, runner=fake_runner)

    assert not report.ok
    leak_check = next(check for check in report.checks if check.name == "local path leaks")
    assert not leak_check.ok
    assert "simplify_order_target.yaml" in leak_check.detail


def test_doctor_target_flags_relative_custom_scorer_target(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "compile.sh").write_text("#!/bin/sh\n")
    (local_perm / "settings.toml").write_text(
        """
[scorer]
command = "melee-agent debug target score-simplify-order --function fn_80000000 --target nonmatchings/fn_80000000/simplify_order_target.yaml"
""".strip()
        + "\n"
    )

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    report = pr.doctor_target(
        target,
        local_perm_dir=local_perm,
        runner=lambda argv, **kwargs: pr.CommandResult(
            returncode=0,
            stdout=_remote_doctor_ok_stdout(),
            stderr="",
        ),
    )

    assert not report.ok
    target_check = next(
        check for check in report.checks if check.name == "local scorer target path"
    )
    assert not target_check.ok
    assert "relative --target" in target_check.detail


def test_doctor_target_flags_remote_without_custom_scorer_support(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "compile.sh").write_text("#!/bin/sh\n")
    (local_perm / "settings.toml").write_text(
        """
[scorer]
command = "melee-agent debug target score-simplify-order --function fn_80000000 --target /home/coder/decomp-permuter/nonmatchings/fn_80000000/simplify_order_target.yaml"
""".strip()
        + "\n"
    )

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    report = pr.doctor_target(
        target,
        local_perm_dir=local_perm,
        runner=lambda argv, **kwargs: pr.CommandResult(
            returncode=0,
            stdout=(
                _remote_doctor_ok_stdout()
                + "remote-custom-scorer\tfail\tCustomCommandScorer missing\n"
                + "remote-scorer-command\tok\t/home/coder/.local/bin/melee-agent --help\n"
                + "remote-scorer-target\tok\t/home/coder/decomp-permuter/nonmatchings/fn_80000000/simplify_order_target.yaml\n"
            ),
            stderr="",
        ),
    )

    assert not report.ok
    custom_check = next(
        check for check in report.checks if check.name == "remote custom scorer"
    )
    assert not custom_check.ok
    assert "CustomCommandScorer missing" in custom_check.detail


def test_doctor_target_flags_stale_remote_scorer_schema(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "compile.sh").write_text("#!/bin/sh\n")
    (local_perm / "settings.toml").write_text(
        """
[scorer]
command = "melee-agent debug target score-simplify-order --function fn_80000000 --target /home/coder/decomp-permuter/nonmatchings/fn_80000000/simplify_order_target.yaml"
""".strip()
        + "\n"
    )

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    report = pr.doctor_target(
        target,
        local_perm_dir=local_perm,
        runner=lambda argv, **kwargs: pr.CommandResult(
            returncode=0,
            stdout=(
                _remote_doctor_ok_stdout()
                + "remote-custom-scorer\tok\t/home/coder/decomp-permuter\n"
                + "remote-scorer-command\tok\t/home/coder/.local/bin/melee-agent --help\n"
                + "remote-scorer-schema\tfail\tmissing --strict-polarity\n"
                + "remote-scorer-target\tok\t/home/coder/decomp-permuter/nonmatchings/fn_80000000/simplify_order_target.yaml\n"
            ),
            stderr="",
        ),
    )

    assert not report.ok
    schema_check = next(
        check for check in report.checks if check.name == "remote scorer schema"
    )
    assert not schema_check.ok
    assert "--strict-polarity" in schema_check.detail


def test_repair_target_syncs_tooling_permuter_deps_and_function_dir(tmp_path: Path) -> None:
    local_melee = tmp_path / "melee"
    local_perm_root = tmp_path / "decomp-permuter"
    function_dir = local_perm_root / "nonmatchings" / "fn_80000000"
    (local_melee / "tools" / "melee-agent").mkdir(parents=True)
    (local_melee / "tools" / "melee-agent" / "pyproject.toml").write_text("[project]\n")
    (local_melee / "tools" / "mwcc_debug").mkdir(parents=True)
    compiler_dir = local_melee / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("mwcc\n")
    (compiler_dir / "MWDBG326.dll").write_text("dll\n")
    tools_dir = local_melee / "build" / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "dtk").write_text("dtk\n")
    (local_perm_root / "src").mkdir(parents=True)
    (local_perm_root / "permuter.py").write_text("#!/usr/bin/env python3\n")
    function_dir.mkdir(parents=True)
    (function_dir / "compile.sh").write_text("#!/bin/sh\n")
    (function_dir / "remote-runs" / "old-job").mkdir(parents=True)
    (function_dir / "output-1000-1").mkdir()
    (function_dir / "settings.toml").write_text(
        """
[scorer]
command = "/home/coder/.local/bin/melee-agent debug target score-simplify-order --function fn_80000000 --target /home/coder/decomp-permuter/nonmatchings/fn_80000000/simplify_order_target.yaml"
""".strip()
        + "\n"
    )
    calls: list[list[str]] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(returncode=0, stdout="", stderr="")

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    report = pr.repair_target(
        target,
        local_melee_root=local_melee,
        local_perm_root=local_perm_root,
        function="fn_80000000",
        local_perm_dir=function_dir,
        runner=fake_runner,
    )

    assert report.target == "coder64"
    assert "synced tools/melee-agent" in report.actions
    assert "refreshed remote Linux dtk" in report.actions
    assert "installed remote python dependencies" in report.actions
    assert ["ssh", "coder.coder64"] == calls[0][:2]
    assert "mkdir -p /home/coder/melee /home/coder/decomp-permuter" in calls[0][2]
    joined_calls = "\n".join(" ".join(call) for call in calls)
    assert f"{local_melee}/tools/melee-agent/" in joined_calls
    assert "coder.coder64:/home/coder/melee/tools/melee-agent/" in joined_calls
    assert f"{local_melee}/tools/mwcc_debug/" in joined_calls
    assert "mwcceppc_debug.exe" in joined_calls
    assert f"{local_melee}/build/tools/dtk" not in joined_calls
    assert "dtk-linux-" in calls[-1][2]
    assert "/home/coder/melee/build/tools/dtk" in calls[-1][2]
    assert f"{local_perm_root}/" in joined_calls
    assert "coder.coder64:/home/coder/decomp-permuter/" in joined_calls
    perm_root_sync = next(
        call
        for call in calls
        if call[0] == "rsync"
        and f"{local_perm_root}/" in call
        and "coder.coder64:/home/coder/decomp-permuter/" in call
    )
    assert _exclude_index(perm_root_sync, "nonmatchings") >= 0
    assert _exclude_index(perm_root_sync, "nonmatchings/***") >= 0
    assert f"{function_dir}/" in joined_calls
    assert "rm -rf /home/coder/decomp-permuter/nonmatchings/fn_80000000" in joined_calls
    assert "coder.coder64:/home/coder/decomp-permuter/nonmatchings/fn_80000000/" in joined_calls
    function_sync = next(
        call
        for call in calls
        if call[0] == "rsync"
        and f"{function_dir}/" in call
        and "coder.coder64:/home/coder/decomp-permuter/nonmatchings/fn_80000000/" in call
    )
    assert _exclude_index(function_sync, "remote-runs") >= 0
    assert _exclude_index(function_sync, "remote-runs/***") >= 0
    assert _exclude_index(function_sync, "output-*") >= 0
    assert _exclude_index(function_sync, "output-*/***") >= 0
    bootstrap_script = calls[-1][2]
    assert "pip install --user" in bootstrap_script
    assert "wibo-x86_64" in bootstrap_script
    assert 'exec \\"$py_path\\" -m src.cli \\"\\$@\\"' in bootstrap_script
    assert "cd /home/coder/melee/tools/melee-agent" in bootstrap_script


def test_repair_python_deps_include_toml_for_remote_doctor() -> None:
    assert any(dep.partition(">=")[0] == "toml" for dep in pr.PYTHON_DEPS)


def test_remote_doctor_uses_python311_for_toml_when_available() -> None:
    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    script = pr._remote_doctor_script(target)

    assert "command -v python3.11" in script
    assert '"$doctor_py" - <<' in script


def _exclude_index(call: list[str], pattern: str) -> int:
    for index, arg in enumerate(call):
        if arg == pattern and index > 0 and call[index - 1] == "--exclude":
            return index
    return -1


def test_submit_job_builds_rsync_ssh_tmux_and_metadata(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "base.c").write_text("void fn_80000000(void) {}\n")
    (local_perm / "compile.sh").write_text("#!/bin/sh\n")
    (local_perm / "settings.toml").write_text(
        'objdump_command = "melee-agent debug target dtk-objdump"\n'
    )
    jobs_dir = tmp_path / "jobs"
    calls: list[list[str]] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        if argv and argv[0] == "ssh" and "remote-rsync" in argv[2]:
            return pr.CommandResult(
                returncode=0,
                stdout=(
                    _remote_doctor_ok_stdout()
                    + "remote-objdump-command\tok\tmelee-agent debug target dtk-objdump --help\n"
                ),
                stderr="",
            )
        return pr.CommandResult(returncode=0, stdout="", stderr="")

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    job = pr.submit_job(
        function="fn_80000000",
        target=target,
        local_perm_dir=local_perm,
        jobs_dir=jobs_dir,
        runner=fake_runner,
        now=lambda: "2026-05-25T14:30:12",
    )

    assert job.job_id == "fn_80000000-coder64-20260525-143012"
    assert job.threads == 64
    assert job.mode == "stock"
    assert (jobs_dir / f"{job.job_id}.json").exists()
    rsync_call = next(call for call in calls if call[0] == "rsync")
    assert rsync_call[-2].endswith("/fn_80000000/")
    assert str(local_perm) + "/" not in rsync_call
    assert (
        "coder.coder64:/home/coder/decomp-permuter/remote-runs/"
        "fn_80000000-coder64-20260525-143012/nonmatchings/fn_80000000/"
    ) in rsync_call
    submit_call = calls[-1]
    assert submit_call[:2] == ["ssh", "coder.coder64"]
    remote_script = submit_call[2]
    assert "/home/coder/decomp-permuter" in remote_script
    assert "/home/coder/melee" in remote_script
    assert 'MELEE_ROOT=\\"$remote_melee_root\\"' in remote_script
    assert "command -v tmux" in remote_script
    assert "command -v python3.11" in remote_script
    assert "tmux new-session -d" in remote_script
    assert (
        '\\"$remote_py\\" ./permuter.py remote-runs/fn_80000000-coder64-20260525-143012/'
        "nonmatchings/fn_80000000 -j 64"
    ) in remote_script
    assert "metadata.json" in remote_script
    assert "permuter.log" in remote_script


def test_submit_job_repairs_missing_remote_toml_before_start(
    tmp_path: Path,
) -> None:
    local_melee = tmp_path / "melee"
    local_perm_root = tmp_path / "decomp-permuter"
    local_perm = local_perm_root / "nonmatchings" / "fn_80000000"
    (local_melee / "tools" / "melee-agent").mkdir(parents=True)
    (local_melee / "tools" / "mwcc_debug").mkdir(parents=True)
    compiler_dir = local_melee / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("mwcc\n")
    (compiler_dir / "MWDBG326.dll").write_text("dll\n")
    local_perm.mkdir(parents=True)
    (local_perm / "base.c").write_text("void fn_80000000(void) {}\n")
    (local_perm / "compile.sh").write_text("#!/bin/sh\n")
    (local_perm / "settings.toml").write_text(
        'objdump_command = "melee-agent debug target dtk-objdump"\n'
    )
    (local_perm_root / "permuter.py").write_text("#!/usr/bin/env python3\n")
    (local_perm_root / "src").mkdir()
    jobs_dir = tmp_path / "jobs"
    calls: list[list[str]] = []
    doctor_calls = 0

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        nonlocal doctor_calls
        calls.append(argv)
        if argv and argv[0] == "ssh" and "remote-rsync" in argv[2]:
            doctor_calls += 1
            stdout = _remote_doctor_ok_stdout().replace(
                "remote-python3-toml\tok\ttoml ok\n",
                "",
            )
            if doctor_calls == 1:
                stdout += (
                    "remote-python3-toml\tfail\tTraceback (most recent call last):\n"
                    + "ModuleNotFoundError: No module named 'toml'\n"
                    + "remote-objdump-command\tok\tmelee-agent debug target dtk-objdump --help\n"
                )
            else:
                stdout += (
                    "remote-python3-toml\tok\ttoml ok\n"
                    + "remote-objdump-command\tok\tmelee-agent debug target dtk-objdump --help\n"
                )
            return pr.CommandResult(returncode=0, stdout=stdout, stderr="")
        return pr.CommandResult(returncode=0, stdout="", stderr="")

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    job = pr.submit_job(
        function="fn_80000000",
        target=target,
        local_perm_dir=local_perm,
        jobs_dir=jobs_dir,
        runner=fake_runner,
        now=lambda: "2026-05-25T14:30:12",
        local_melee_root=local_melee,
        local_perm_root=local_perm_root,
    )

    assert job.job_id == "fn_80000000-coder64-20260525-143012"
    assert doctor_calls == 2
    bootstrap_call = next(
        call for call in calls
        if call[0] == "ssh" and "pip install --user" in call[2]
    )
    assert "toml>=0.10.2" in bootstrap_call[2]
    assert (jobs_dir / f"{job.job_id}.json").exists()


def test_submit_job_stages_compile_sh_with_remote_wibo_and_melee_root(
    tmp_path: Path,
) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "base.c").write_text("void fn_80000000(void) {}\n")
    (local_perm / "settings.toml").write_text("[score]\n")
    (local_perm / "remote-runs" / "old-job").mkdir(parents=True)
    (local_perm / "output-1000-1").mkdir()
    (local_perm / "compile.sh").write_text(
        """#!/usr/bin/env bash
INPUT_ABS="$(realpath "$1")"
OUTPUT_ABS="$(realpath "$3")"
cd /Users/mike/code/melee
STAGE="nonmatchings/.permuter_stage_$$.c"
cp "$INPUT_ABS" "$STAGE"
INPUT="$STAGE"
OUTPUT="$OUTPUT_ABS"
wine build/compilers/GC/1.2.5n/mwcceppc.exe -Cpp_exceptions off "$INPUT" -o "$OUTPUT"
"""
    )
    jobs_dir = tmp_path / "jobs"
    staged_compile: list[str] = []
    staged_settings: list[str] = []
    staged_has_history: list[bool] = []
    calls: list[list[str]] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        if argv and argv[0] == "ssh" and "remote-rsync" in argv[2]:
            return pr.CommandResult(
                returncode=0,
                stdout=(
                    _remote_doctor_ok_stdout()
                    + "remote-objdump-command\tok\tmelee-agent debug target dtk-objdump --help\n"
                ),
                stderr="",
            )
        if argv and argv[0] == "rsync":
            source = Path(argv[-2].rstrip("/"))
            staged_compile.append((source / "compile.sh").read_text())
            staged_settings.append((source / "settings.toml").read_text())
            staged_has_history.append(
                (source / "remote-runs").exists()
                or (source / "output-1000-1").exists()
            )
        return pr.CommandResult(returncode=0, stdout="", stderr="")

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    pr.submit_job(
        function="fn_80000000",
        target=target,
        local_perm_dir=local_perm,
        jobs_dir=jobs_dir,
        runner=fake_runner,
        now=lambda: "2026-05-25T14:30:12",
    )

    assert staged_compile
    assert "/Users/mike" not in staged_compile[0]
    assert " wine " not in staged_compile[0]
    assert 'cd "${MELEE_ROOT:?MELEE_ROOT must be set}"' in staged_compile[0]
    assert 'MWCC_DEBUG_WIBO:-$MELEE_ROOT/tools/mwcc_debug/bin/wibo' in staged_compile[0]
    assert "mwcceppc_debug.exe" in staged_compile[0]
    assert staged_settings
    assert staged_has_history == [False]
    assert (
        "melee-agent debug target dtk-objdump --melee-root /home/coder/melee"
        " --object-root /home/coder/decomp-permuter"
        in staged_settings[0]
    )
    assert any(call[0] == "rsync" for call in calls)


def test_submit_job_preflights_remote_objdump_before_rsync(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "base.c").write_text("void fn_80000000(void) {}\n")
    (local_perm / "settings.toml").write_text(
        'objdump_command = "melee-agent debug target dtk-objdump"\n'
    )
    jobs_dir = tmp_path / "jobs"
    calls: list[list[str]] = []

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(
            returncode=0,
            stdout=(
                _remote_doctor_ok_stdout()
                + "remote-objdump-command\tfail\t/home/coder/melee/build/tools/dtk missing\n"
            ),
            stderr="",
        )

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    with pytest.raises(pr.RemoteJobError) as exc:
        pr.submit_job(
            function="fn_80000000",
            target=target,
            local_perm_dir=local_perm,
            jobs_dir=jobs_dir,
            runner=fake_runner,
            now=lambda: "2026-05-25T14:30:12",
        )

    assert "remote preflight failed" in str(exc.value)
    assert "remote objdump command" in str(exc.value)
    assert not any(call[0] == "rsync" for call in calls)
    assert not list(jobs_dir.glob("*.json"))


def test_submit_job_preserves_multiline_remote_preflight_detail(
    tmp_path: Path,
) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "base.c").write_text("void fn_80000000(void) {}\n")
    (local_perm / "settings.toml").write_text("[score]\n")
    jobs_dir = tmp_path / "jobs"

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        ok_without_toml = _remote_doctor_ok_stdout().replace(
            "remote-python3-toml\tok\ttoml ok\n",
            "",
        )
        return pr.CommandResult(
            returncode=0,
            stdout=(
                ok_without_toml
                + "remote-python3-toml\tfail\tTraceback (most recent call last):\n"
                + "  File \"<stdin>\", line 1, in <module>\n"
                + "ModuleNotFoundError: No module named 'toml'\n"
            ),
            stderr="",
        )

    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    with pytest.raises(pr.RemoteJobError) as exc:
        pr.submit_job(
            function="fn_80000000",
            target=target,
            local_perm_dir=local_perm,
            jobs_dir=jobs_dir,
            runner=fake_runner,
            now=lambda: "2026-05-25T14:30:12",
        )

    detail = str(exc.value)
    assert "remote python3 toml: Traceback (most recent call last):" in detail
    assert "File \"<stdin>\", line 1, in <module>" in detail
    assert "ModuleNotFoundError: No module named 'toml'" in detail
    assert not list(jobs_dir.glob("*.json"))


def test_submit_job_missing_local_perm_dir_raises(tmp_path: Path) -> None:
    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    with pytest.raises(pr.RemoteJobError) as exc:
        pr.submit_job(
            function="fn_80000000",
            target=target,
            local_perm_dir=tmp_path / "missing",
            jobs_dir=tmp_path / "jobs",
            now=lambda: "2026-05-25T14:30:12",
        )

    assert "local permuter dir not found" in str(exc.value)


def test_submit_job_rejects_non_stock_mode(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    with pytest.raises(pr.RemoteJobError) as exc:
        pr.submit_job(
            function="fn_80000000",
            target=target,
            local_perm_dir=local_perm,
            jobs_dir=tmp_path / "jobs",
            mode="mwcc",
            now=lambda: "2026-05-25T14:30:12",
        )

    assert "mode" in str(exc.value)
    assert "stock" in str(exc.value)


def test_submit_job_rejects_local_only_paths_in_permuter_files(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "compile.sh").write_text("MELEE_ROOT=/Users/mike/src/melee\n")
    calls: list[list[str]] = []
    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(returncode=0, stdout="", stderr="")

    with pytest.raises(pr.RemoteJobError) as exc:
        pr.submit_job(
            function="fn_80000000",
            target=target,
            local_perm_dir=local_perm,
            jobs_dir=tmp_path / "jobs",
            runner=fake_runner,
            now=lambda: "2026-05-25T14:30:12",
        )

    msg = str(exc.value)
    assert "not remote-ready" in msg
    assert "compile.sh" in msg
    assert calls == []


def test_submit_job_rejects_inferred_worktree_paths_in_permuter_files(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    (local_perm / "settings.toml").write_text(f'melee_root = "{Path.cwd()}"\n')
    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    with pytest.raises(pr.RemoteJobError) as exc:
        pr.submit_job(
            function="fn_80000000",
            target=target,
            local_perm_dir=local_perm,
            jobs_dir=tmp_path / "jobs",
            now=lambda: "2026-05-25T14:30:12",
        )

    msg = str(exc.value)
    assert "not remote-ready" in msg
    assert "settings.toml" in msg


def test_submit_job_metadata_conflict_prevents_remote_side_effects(tmp_path: Path) -> None:
    local_perm = tmp_path / "local-perm" / "nonmatchings" / "fn_80000000"
    local_perm.mkdir(parents=True)
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "fn_80000000-coder64-20260525-143012.json").write_text("{}\n")
    calls: list[list[str]] = []
    target = pr.RemoteTarget(
        name="coder64",
        ssh="coder.coder64",
        remote_melee_root="/home/coder/melee",
        remote_perm_root="/home/coder/decomp-permuter",
        threads=64,
        session_prefix="melee-perm",
    )

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> pr.CommandResult:
        calls.append(argv)
        return pr.CommandResult(returncode=0, stdout="", stderr="")

    with pytest.raises(pr.RemoteJobError) as exc:
        pr.submit_job(
            function="fn_80000000",
            target=target,
            local_perm_dir=local_perm,
            jobs_dir=jobs_dir,
            runner=fake_runner,
            now=lambda: "2026-05-25T14:30:12",
        )

    assert "already exists" in str(exc.value)
    assert calls == []


# ── _parse_tmux_session_name ─────────────────────────────────────────────────


def test_parse_tmux_session_name_extracts_job_id() -> None:
    result = pr._parse_tmux_session_name(
        "melee-perm-fn_80000000-coder64-20260608-120000",
        "melee-perm-",
    )
    assert result == "fn_80000000-coder64-20260608-120000"


def test_parse_tmux_session_name_rejects_non_matching_prefix() -> None:
    result = pr._parse_tmux_session_name("other-fn_80000000", "melee-perm-")
    assert result is None


# ── _job_is_done ─────────────────────────────────────────────────────────────


def test_job_is_done_byte_match() -> None:
    log = pr.RemoteLogStatus(exists=True, match_found=True)
    should_stop, reason = pr._job_is_done(log)
    assert should_stop is True
    assert "byte-matched" in reason


def test_job_is_done_descending_not_done() -> None:
    log = pr.RemoteLogStatus(
        exists=True,
        match_found=False,
        verdict="descending",
        modified_at=pr.utcnow(),
    )
    should_stop, reason = pr._job_is_done(log)
    assert should_stop is False


def test_job_is_done_plateau_stale_enough() -> None:
    log = pr.RemoteLogStatus(
        exists=True,
        match_found=False,
        verdict="plateau",
        modified_at=pr.parse_timestamp("2026-06-01T00:00:00"),
    )
    should_stop, reason = pr._job_is_done(log, idle_hours_threshold=1.0)
    assert should_stop is True
    assert "plateaued" in reason


def test_job_is_done_plateau_recent_not_done() -> None:
    log = pr.RemoteLogStatus(
        exists=True,
        match_found=False,
        verdict="plateau",
        modified_at=pr.utcnow(),
    )
    should_stop, reason = pr._job_is_done(log, idle_hours_threshold=24.0)
    assert should_stop is False


# ── probe_jobs_active ────────────────────────────────────────────────────────


def test_probe_jobs_active_maps_active_dead(tmp_path: Path) -> None:
    job = _sample_job(tmp_path)
    calls = 0

    def fake_status_job(
        loaded_job: pr.RemoteJob,
        *,
        runner=None,
        timeout=None,
    ) -> pr.RemoteStatus:
        nonlocal calls
        calls += 1
        return pr.RemoteStatus(job_id=loaded_job.job_id, state="active" if calls == 1 else "stopped")

    import types
    original = pr.status_job
    pr.status_job = fake_status_job
    try:
        active_map = pr.probe_jobs_active([job, replace(job, job_id="job2-target-20260101-000000")])
    finally:
        pr.status_job = original

    assert active_map[job.job_id] is True
    assert active_map["job2-target-20260101-000000"] is False


# ── prune_dead_jobs ──────────────────────────────────────────────────────────


def test_prune_dead_jobs_removes_only_dead_metadata(tmp_path: Path) -> None:
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job1 = _sample_job(tmp_path)
    job2 = replace(job1, job_id="job2-target-20260101-000000")
    pr.write_job(job1, jobs_dir=jobs_dir)
    pr.write_job(job2, jobs_dir=jobs_dir)

    def fake_probe(jobs, **kwargs):
        return {job1.job_id: True, job2.job_id: False}

    original = pr.probe_jobs_active
    pr.probe_jobs_active = fake_probe
    try:
        pruned = pr.prune_dead_jobs(
            [job1, job2], dry_run=False, jobs_dir=jobs_dir,
        )
    finally:
        pr.probe_jobs_active = original

    assert pruned == [job2.job_id]
    assert (jobs_dir / f"{job1.job_id}.json").exists()
    assert not (jobs_dir / f"{job2.job_id}.json").exists()


def test_prune_dead_jobs_dry_run_does_not_delete(tmp_path: Path) -> None:
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job = _sample_job(tmp_path)
    pr.write_job(job, jobs_dir=jobs_dir)

    def fake_probe(jobs, **kwargs):
        return {job.job_id: False}

    original = pr.probe_jobs_active
    pr.probe_jobs_active = fake_probe
    try:
        pruned = pr.prune_dead_jobs([job], dry_run=True, jobs_dir=jobs_dir)
    finally:
        pr.probe_jobs_active = original

    assert pruned == [job.job_id]
    assert (jobs_dir / f"{job.job_id}.json").exists()


# ── remote list CLI ──────────────────────────────────────────────────────────


def test_remote_list_cli_shows_active_dead(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = _sample_job(tmp_path)

    def fake_list_jobs(jobs_dir=None):
        return [job]

    def fake_probe(jobs, **kwargs):
        return {job.job_id: True}

    monkeypatch.setattr(pr, "list_jobs", fake_list_jobs)
    monkeypatch.setattr(pr, "probe_jobs_active", fake_probe)

    result = CliRunner().invoke(app, ["debug", "permute", "remote", "list"])
    assert result.exit_code == 0
    assert "active" in result.stdout
    assert job.job_id in result.stdout


def test_remote_list_cli_active_flag_filters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = _sample_job(tmp_path)
    job2 = replace(job, job_id="job2-target-20260101-000000", function="fn_80000010")

    def fake_list_jobs(jobs_dir=None):
        return [job, job2]

    def fake_probe(jobs, **kwargs):
        return {job.job_id: True, job2.job_id: False}

    monkeypatch.setattr(pr, "list_jobs", fake_list_jobs)
    monkeypatch.setattr(pr, "probe_jobs_active", fake_probe)

    result = CliRunner().invoke(
        app, ["debug", "permute", "remote", "list", "--active"],
    )
    assert result.exit_code == 0
    assert job.job_id in result.stdout
    assert job2.job_id not in result.stdout


def test_remote_list_cli_dead_flag_filters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = _sample_job(tmp_path)
    job2 = replace(job, job_id="job2-target-20260101-000000", function="fn_80000010")

    def fake_list_jobs(jobs_dir=None):
        return [job, job2]

    def fake_probe(jobs, **kwargs):
        return {job.job_id: True, job2.job_id: False}

    monkeypatch.setattr(pr, "list_jobs", fake_list_jobs)
    monkeypatch.setattr(pr, "probe_jobs_active", fake_probe)

    result = CliRunner().invoke(
        app, ["debug", "permute", "remote", "list", "--dead"],
    )
    assert result.exit_code == 0
    assert job.job_id not in result.stdout
    assert job2.job_id in result.stdout


def test_remote_list_cli_active_dead_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pr, "list_jobs", lambda jobs_dir=None: [])
    result = CliRunner().invoke(
        app, ["debug", "permute", "remote", "list", "--active", "--dead"],
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.stderr


# ── remote fetch --all ───────────────────────────────────────────────────────


def test_remote_fetch_cli_all_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = _sample_job(tmp_path)
    fetch_calls: list[pr.RemoteJob] = []

    def fake_fetch_all(jobs, **kwargs):
        fetch_calls.extend(jobs)
        return [Path("/tmp/out")]

    monkeypatch.setattr(pr, "list_jobs", lambda jobs_dir=None: [job])
    monkeypatch.setattr(pr, "fetch_all_jobs", fake_fetch_all)

    result = CliRunner().invoke(
        app, ["debug", "permute", "remote", "fetch", "--all"],
    )
    assert result.exit_code == 0
    assert len(fetch_calls) == 1
    assert fetch_calls[0] == job
    assert "Fetched" in result.stdout


def test_remote_fetch_cli_requires_job_id_or_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = CliRunner().invoke(app, ["debug", "permute", "remote", "fetch"])
    assert result.exit_code == 2
    assert "JOB_ID or --all" in result.stderr


# ── remote reap ──────────────────────────────────────────────────────────────


def test_remote_reap_cli_dry_run_shows_would_stop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = _sample_job(tmp_path)

    def fake_reap(targets, jobs, **kwargs):
        return [
            pr.ReapAction(
                job_id=job.job_id,
                function=job.function,
                target=job.target,
                action="would-stop",
                reason="byte-matched (score 0)",
            )
        ]

    monkeypatch.setattr(pr, "load_targets", lambda config_path=pr.CONFIG_PATH: {})
    monkeypatch.setattr(pr, "list_jobs", lambda jobs_dir=None: [job])
    monkeypatch.setattr(pr, "remote_reap", fake_reap)

    result = CliRunner().invoke(
        app, ["debug", "permute", "remote", "reap", "--dry-run"],
    )
    assert result.exit_code == 0
    assert "would-stop" in result.stdout
    assert "byte-matched" in result.stdout
    assert "dry run" in result.stdout.lower()


# ── remote prune ─────────────────────────────────────────────────────────────


def test_remote_prune_cli_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_prune(targets, **kwargs):
        return [
            pr.PruneAction(
                target="coder64",
                remote_dir="/home/coder/decomp-permuter/remote-runs/old-job",
                action="would-delete",
                reason="stale (21d old)",
            )
        ]

    monkeypatch.setattr(pr, "load_targets", lambda config_path=pr.CONFIG_PATH: {})
    monkeypatch.setattr(pr, "remote_prune", fake_prune)

    result = CliRunner().invoke(
        app, ["debug", "permute", "remote", "prune", "--dry-run"],
    )
    assert result.exit_code == 0
    assert "would-delete" in result.stdout
    assert "21d" in result.stdout
    assert "dry run" in result.stdout.lower()


# ── _parse_ps_log_tail ───────────────────────────────────────────────────────


def test_parse_ps_log_tail_extracts_score_and_verdict() -> None:
    # All iterations at same best score = plateau (no record improvements)
    best, iters, verdict, plateau, match = pr._parse_ps_log_tail(
        "iteration 100, 0 errors, score = 35\r"
        "iteration 200, 0 errors, score = 35\r"
        "iteration 300, 0 errors, score = 50\r"
    )
    assert best == "35"
    assert verdict == "plateau"
    assert plateau is True
    assert match is False


def test_parse_ps_log_tail_detects_match() -> None:
    best, iters, verdict, plateau, match = pr._parse_ps_log_tail(
        "iteration 50, 0 errors, score = 0\n"
    )
    assert best == "0"
    assert match is True
    assert verdict == "match"
