from __future__ import annotations

import json
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
            "sh -lc 'tail -n 20 /home/coder/decomp-permuter/remote-runs/fn_80000000-coder64-20260525-143012/permuter.log'",
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
