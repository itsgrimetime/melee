from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import app


runner = CliRunner()


def test_run_local_permuter_terminates_process_group_on_sigterm(monkeypatch):
    import src.cli.debug.permute as permute_cli

    handlers = {}
    calls = {}

    class FakeProc:
        pid = 4321
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            if timeout is None:
                handlers[signal.SIGTERM](signal.SIGTERM, None)
            self.returncode = -signal.SIGTERM
            return self.returncode

        def kill(self):
            calls["kill"] = True

    def fake_popen(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["popen_kwargs"] = kwargs
        return FakeProc()

    def fake_signal(signum, handler):
        previous = handlers.get(signum)
        handlers[signum] = handler
        return previous

    killed = []
    monkeypatch.setattr(permute_cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(permute_cli.signal, "signal", fake_signal)
    monkeypatch.setattr(permute_cli.os, "getpgid", lambda pid: 9876)
    group_alive = True

    def fake_killpg(pgid, sig):
        nonlocal group_alive
        if sig == 0:
            if not group_alive:
                raise ProcessLookupError
            return
        killed.append((pgid, sig))
        group_alive = False

    monkeypatch.setattr(permute_cli.os, "killpg", fake_killpg)

    with pytest.raises(SystemExit) as exc:
        permute_cli._run_local_permuter(
            ["python", "wrapper.py"],
            env={"KEY": "value"},
            cwd=Path("/tmp/permuter"),
        )

    assert exc.value.code == 128 + signal.SIGTERM
    assert calls["popen_kwargs"]["start_new_session"] is True
    assert calls["popen_kwargs"]["env"] == {"KEY": "value"}
    assert calls["popen_kwargs"]["cwd"] == Path("/tmp/permuter")
    assert killed == [(9876, signal.SIGTERM)]


def test_run_local_permuter_reaps_group_after_leader_exits(monkeypatch):
    import src.cli.debug.permute as permute_cli

    handlers = {}
    group_alive = True
    leader_waited = False
    signals_sent = []

    class FakeProc:
        pid = 4321
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            nonlocal leader_waited
            leader_waited = True
            self.returncode = 0
            return 0

        def kill(self):
            raise AssertionError("the dead group leader must not be killed")

    def fake_signal(signum, handler):
        previous = handlers.get(signum)
        handlers[signum] = handler
        return previous

    def fake_getpgid(pid):
        assert pid == 4321
        assert not leader_waited, "PGID must be captured while the leader is alive"
        return 9876

    def fake_killpg(pgid, signum):
        nonlocal group_alive
        assert pgid == 9876
        if signum == 0:
            if not group_alive:
                raise ProcessLookupError
            return
        signals_sent.append(signum)
        if signum == signal.SIGTERM:
            group_alive = False

    monkeypatch.setattr(permute_cli.subprocess, "Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr(permute_cli.signal, "signal", fake_signal)
    monkeypatch.setattr(permute_cli.os, "getpgid", fake_getpgid)
    monkeypatch.setattr(permute_cli.os, "getpgrp", lambda: 111)
    monkeypatch.setattr(permute_cli.os, "killpg", fake_killpg)

    rc = permute_cli._run_local_permuter(
        ["python", "wrapper.py"],
        env={"KEY": "value"},
        cwd=Path("/tmp/permuter"),
    )

    assert rc == 0
    assert signals_sent == [signal.SIGTERM]


def test_terminate_local_permuter_group_escalates_surviving_group(monkeypatch):
    import src.cli.debug.permute as permute_cli

    signals_sent = []

    class FakeProc:
        pid = 4321
        returncode = 0

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return 0

        def kill(self):
            raise AssertionError("the dead group leader must not be killed")

    def fake_group_exists(pgid):
        return not signals_sent or signals_sent[-1] != signal.SIGKILL

    monkeypatch.setattr(permute_cli, "_process_group_exists", fake_group_exists, raising=False)
    monkeypatch.setattr(
        permute_cli,
        "_signal_captured_process_group",
        lambda pgid, signum, proc=None: signals_sent.append(signum),
        raising=False,
    )
    monkeypatch.setattr(permute_cli.time, "sleep", lambda _seconds: None)

    permute_cli._terminate_local_permuter_group(
        FakeProc(),
        pgid=9876,
        grace_seconds=0,
    )

    assert signals_sent == [signal.SIGTERM, signal.SIGKILL]


def test_run_local_permuter_sigint_does_not_deadlock_inside_wait(tmp_path):
    child_pid_file = tmp_path / "child.pid"
    parent_code = textwrap.dedent(
        f"""
        import os
        import sys
        from pathlib import Path
        from src.cli.debug.permute import _run_local_permuter

        child_code = {f'''
import os
import time
from pathlib import Path
Path({str(child_pid_file)!r}).write_text(str(os.getpid()))
print("child-ready", flush=True)
time.sleep(30)
'''.strip()!r}

        rc = _run_local_permuter(
            [sys.executable, "-c", child_code],
            env=os.environ.copy(),
            cwd=Path.cwd(),
        )
        sys.exit(rc)
        """
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path("tools/melee-agent").resolve())
    proc = subprocess.Popen(
        [sys.executable, "-c", parent_code],
        cwd=Path.cwd(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not child_pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert child_pid_file.exists(), "child process did not start"

        os.kill(proc.pid, signal.SIGINT)
        try:
            stdout, stderr = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            pytest.fail(
                "parent deadlocked during SIGINT cleanup; "
                f"stdout={stdout!r} stderr={stderr!r}"
            )
    finally:
        if child_pid_file.exists():
            try:
                child_pid = int(child_pid_file.read_text())
                os.killpg(os.getpgid(child_pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

    assert proc.returncode == 128 + signal.SIGINT
    assert "child-ready" in stdout


def test_debug_permute_run_uses_local_permuter_helper(monkeypatch, tmp_path):
    import src.cli.debug as debug_cli
    import src.cli.debug.permute as permute_cli

    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    perm_dir = perm_root / "nonmatchings" / "fn_80000000"
    wrapper = melee_root / "tools" / "melee-agent" / "scripts" / "permute_with_mwcc.py"
    target = tmp_path / "target.json"
    perm_dir.mkdir(parents=True)
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("# fake wrapper\n")
    target.write_text("{}\n")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_resolve_permuter_function_dir",
        lambda function, *, perm_root, melee_root: perm_dir,
    )
    monkeypatch.setattr(
        debug_cli,
        "_resolve_decomp_permuter_root",
        lambda requested_root: perm_root,
    )
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        permute_cli.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("debug permute run must use _run_local_permuter")
        ),
    )

    seen = {}

    def fake_run_local(cmd, *, env, cwd):
        seen["cmd"] = cmd
        seen["env"] = env
        seen["cwd"] = cwd
        return 7

    monkeypatch.setattr(permute_cli, "_run_local_permuter", fake_run_local, raising=False)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "run",
            "-f",
            "fn_80000000",
            "--target",
            str(target),
            "--perm-root",
            str(perm_root),
            "-j",
            "3",
            "--",
            "--best-only",
        ],
    )

    assert result.exit_code == 7
    assert seen["cmd"] == [
        "python",
        str(wrapper),
        str(perm_dir),
        "-j",
        "3",
        "--best-only",
    ]
    assert seen["cwd"] == perm_root
    assert seen["env"]["MELEE_PERMUTER_ROOT"] == str(perm_root)
    assert seen["env"]["MELEE_ROOT"] == str(melee_root)
    assert seen["env"]["MWCC_DEBUG_TARGET"] == str(target)
    assert seen["env"]["MWCC_DEBUG_FN"] == "fn_80000000"
    assert seen["env"]["MWCC_DEBUG_UNIT"] == "src/melee/mn/sample.c"
