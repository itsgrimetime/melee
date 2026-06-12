"""Regression tests for state diff-remotes build orchestration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.cli.state import diff_remotes


def test_run_owned_process_group_starts_new_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    popen_kwargs: list[dict] = []

    class FakeProc:
        pid = 4242
        returncode = 0

        def communicate(self, timeout=None):
            return "stdout", "stderr"

    def fake_popen(cmd, **kwargs):
        popen_kwargs.append(kwargs)
        return FakeProc()

    monkeypatch.setattr(diff_remotes.subprocess, "Popen", fake_popen)

    result = diff_remotes._run_owned_process_group(["ninja"], cwd=tmp_path)

    assert result.returncode == 0
    assert result.stdout == "stdout"
    assert result.stderr == "stderr"
    assert popen_kwargs[0]["start_new_session"] is True


def test_run_owned_process_group_kills_group_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    killed: list[int] = []

    class FakeProc:
        pid = 4243
        returncode = None

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(
                ["ninja"],
                timeout,
                output="partial stdout",
                stderr="partial stderr",
            )

    monkeypatch.setattr(
        diff_remotes.subprocess,
        "Popen",
        lambda *args, **kwargs: FakeProc(),
    )
    monkeypatch.setattr(
        diff_remotes,
        "_terminate_process_group",
        lambda pgid: killed.append(pgid),
    )

    with pytest.raises(subprocess.TimeoutExpired) as excinfo:
        diff_remotes._run_owned_process_group(
            ["ninja"],
            cwd=tmp_path,
            timeout=0.01,
        )

    assert killed == [4243]
    assert excinfo.value.output == "partial stdout"
    assert excinfo.value.stderr == "partial stderr"


def test_run_owned_process_group_kills_group_on_sigterm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    killed: list[int] = []
    handlers: dict[int, object] = {}

    class FakeProc:
        pid = 4244
        returncode = None

        def communicate(self, timeout=None):
            handlers[diff_remotes.signal.SIGTERM](
                diff_remotes.signal.SIGTERM,
                None,
            )
            raise AssertionError("signal handler should abort communicate")

    def fake_signal(signum, handler):
        previous = handlers.get(signum, diff_remotes.signal.SIG_DFL)
        handlers[signum] = handler
        return previous

    monkeypatch.setattr(
        diff_remotes.subprocess,
        "Popen",
        lambda *args, **kwargs: FakeProc(),
    )
    monkeypatch.setattr(diff_remotes.signal, "signal", fake_signal)
    monkeypatch.setattr(
        diff_remotes.signal,
        "getsignal",
        lambda signum: handlers.get(signum, diff_remotes.signal.SIG_DFL),
    )
    monkeypatch.setattr(
        diff_remotes,
        "_terminate_process_group",
        lambda pgid: killed.append(pgid),
    )

    with pytest.raises(KeyboardInterrupt):
        diff_remotes._run_owned_process_group(["ninja"], cwd=tmp_path)

    assert killed == [4244]


def test_build_ref_uses_owned_process_groups_for_configure_and_ninja(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "melee"
    repo.mkdir()
    worktree = tmp_path / ".diff-worktree-origin-master"
    commands: list[tuple[tuple[str, ...], Path]] = []

    def fake_run_git(args: list[str], cwd: Path):
        if args[:2] == ["rev-parse", "origin/master"]:
            return 0, "abc123\n", ""
        if args[:3] == ["worktree", "add", "--detach"]:
            worktree.mkdir(parents=True)
            return 0, "", ""
        return 0, "", ""

    def fake_owned_process_group(cmd: list[str], cwd: Path, **kwargs):
        commands.append((tuple(cmd), cwd))
        if cmd == ["ninja"]:
            report = cwd / "build" / "GALE01" / "report.json"
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps({
                "units": [
                    {
                        "functions": [
                            {
                                "name": "fn_80000000",
                                "fuzzy_match_percent": 100.0,
                            }
                        ]
                    }
                ]
            }))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(diff_remotes, "_run_git", fake_run_git)
    monkeypatch.setattr(diff_remotes, "ensure_dol_in_worktree", lambda path: True)
    monkeypatch.setattr(
        diff_remotes,
        "_run_owned_process_group",
        fake_owned_process_group,
    )

    funcs = diff_remotes._build_ref_and_get_all_functions(repo, "origin/master")

    assert funcs == {"fn_80000000": 100.0}
    assert commands == [
        (("python", "configure.py"), worktree),
        (("ninja",), worktree),
    ]
