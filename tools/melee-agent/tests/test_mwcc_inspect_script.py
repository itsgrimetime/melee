"""Tests for the mwcc-inspect workflow wrapper."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _head_commit(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _copy_inspect_workflow(workflow: Path) -> Path:
    script = workflow / "mwcc-inspect.sh"
    shutil.copy2(REPO_ROOT / "tools" / "workflow" / "mwcc-inspect.sh", script)
    shutil.copy2(
        REPO_ROOT / "tools" / "workflow" / "mwcc-inspect-supervisor.sh",
        workflow / "mwcc-inspect-supervisor.sh",
    )
    return script


def _install_local_ssh(fake_bin: Path, tmp_path: Path) -> tuple[Path, Path]:
    remote_dir = tmp_path / "remote-melee"
    (remote_dir / "src" / "melee" / "pl").mkdir(parents=True)
    remote_bin = tmp_path / "remote-bin"
    remote_bin.mkdir()
    inspector = remote_bin / "inspector"
    _write_executable(
        remote_bin / "git",
        "#!/bin/sh\ncase \"$1\" in fetch|checkout|cat-file) exit 0;; esac\nexit 0\n",
    )
    _write_executable(remote_bin / "native-pid", "#!/bin/sh\nprintf '%s\\n' \"$1\"\n")
    _write_executable(remote_bin / "setsid", "#!/bin/sh\nexec \"$@\"\n")
    _write_executable(
        remote_bin / "taskkill.exe",
        "#!/bin/sh\nkill -TERM \"$2\" 2>/dev/null || true\n",
    )
    _write_executable(
        inspector,
        textwrap.dedent("""\
            #!/usr/bin/env python3
            import os
            import sys

            sys.stdout.write(os.environ.get("FAKE_INSPECTOR_OUTPUT", ""))
            sys.stdout.flush()
            sys.stderr.write(os.environ.get("FAKE_INSPECTOR_STDERR", ""))
            raise SystemExit(int(os.environ.get("FAKE_INSPECTOR_EXIT", "0")))
        """),
    )
    _write_executable(
        fake_bin / "ssh",
        textwrap.dedent("""\
            #!/usr/bin/env python3
            import os
            import subprocess
            import sys
            from pathlib import Path

            payload = sys.stdin.read()
            if (
                "set -- 'finalize-stored-token' " in payload
                and os.environ.get("FAKE_FINALIZE_FAILURE")
            ):
                print("injected finalize failure", file=sys.stderr)
                raise SystemExit(125)
            log_dir_value = os.environ.get("FAKE_SSH_LOG")
            if log_dir_value:
                log_dir = Path(log_dir_value)
                idx = len(list(log_dir.glob("*.stdin")))
                (log_dir / f"{idx:02d}.argv").write_text(repr(sys.argv[1:]), encoding="utf-8")
                (log_dir / f"{idx:02d}.stdin").write_text(payload, encoding="utf-8")
            env = os.environ.copy()
            env["PATH"] = f"{env['FAKE_REMOTE_BIN']}:{env['PATH']}"
            env["MWCC_INSPECT_NATIVE_PID_CMD"] = str(Path(env["FAKE_REMOTE_BIN"]) / "native-pid")
            env["MWCC_INSPECT_SETSID"] = str(Path(env["FAKE_REMOTE_BIN"]) / "setsid")
            env["MWCC_INSPECT_TASKKILL"] = str(Path(env["FAKE_REMOTE_BIN"]) / "taskkill.exe")
            proc = subprocess.run(["bash", "-s"], input=payload, text=True, env=env)
            raise SystemExit(proc.returncode)
        """),
    )
    return remote_dir, inspector


def _wrapper_fixture(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str], Path]:
    repo = tmp_path / "repo"
    workflow = repo / "tools" / "workflow"
    workflow.mkdir(parents=True)
    script = _copy_inspect_workflow(workflow)
    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/pl/plbonuslib",'
        '"functions":[{"name":"fn_test"}]}]}',
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_test(void) {}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "ninja",
        "#!/bin/sh\necho 'wrapper mwcceppc.exe -c -o "
        "build/GALE01/src/melee/pl/plbonuslib.o src/melee/pl/plbonuslib.c'\n",
    )
    remote_dir, inspector = _install_local_ssh(fake_bin, tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_INSPECTOR_OUTPUT": "FUNCTION: fn_test\nCompilation finished.\n",
            "FAKE_REMOTE_BIN": str(inspector.parent),
            "MWCC_INSPECT_HOST": "fake-host",
            "MWCC_INSPECT_REMOTE_BASH": "bash",
            "MWCC_INSPECT_REMOTE_DIR": str(remote_dir),
            "MWCC_INSPECT_CLI": str(inspector),
            "MWCC_INSPECT_REMOTE_REF": "HEAD",
        }
    )
    return repo, script, candidate, env, remote_dir


def _wait_for_path(path: Path, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path}")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_for_pid_exit(pid: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for PID {pid} to exit")


SUPERVISOR = REPO_ROOT / "tools" / "workflow" / "mwcc-inspect-supervisor.sh"
TOKEN = "a" * 64


def _supervisor_job(tmp_path: Path, job_id: str) -> Path:
    job = tmp_path / job_id
    job.mkdir(mode=0o700)
    job.chmod(0o700)
    (job / "token").write_text(f"{TOKEN}\n", encoding="utf-8")
    return job


def _supervisor_env(tmp_path: Path, *, taskkill_mode: str = "kill") -> dict[str, str]:
    native_pid = tmp_path / "native-pid"
    taskkill = tmp_path / "taskkill"
    setsid = tmp_path / "setsid"
    taskkill_log = tmp_path / "taskkill.log"
    _write_executable(native_pid, "#!/bin/sh\nprintf '%s\\n' \"$1\"\n")
    _write_executable(
        taskkill,
        textwrap.dedent("""\
            #!/usr/bin/env python3
            import os
            import signal
            import subprocess
            import sys
            from pathlib import Path

            Path(os.environ["FAKE_TASKKILL_LOG"]).write_text(
                " ".join(sys.argv[1:]), encoding="utf-8"
            )
            mode = os.environ["FAKE_TASKKILL_MODE"]
            if mode == "fail":
                raise SystemExit(7)
            if mode == "kill":
                try:
                    os.kill(int(sys.argv[2]), signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if mode == "kill-tree":
                root = int(sys.argv[2])
                rows = subprocess.run(
                    ["ps", "-axo", "pid=,ppid="],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.splitlines()
                children = {}
                for row in rows:
                    pid_text, parent_text = row.split()
                    children.setdefault(int(parent_text), []).append(int(pid_text))
                ordered = []
                stack = [root]
                while stack:
                    parent = stack.pop()
                    for child in children.get(parent, []):
                        stack.append(child)
                        ordered.append(child)
                for pid in [*reversed(ordered), root]:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
        """),
    )
    _write_executable(setsid, "#!/bin/sh\nexec \"$@\"\n")
    env = os.environ.copy()
    env.update(
        {
            "FAKE_TASKKILL_LOG": str(taskkill_log),
            "FAKE_TASKKILL_MODE": taskkill_mode,
            "MWCC_INSPECT_KILL_AWAIT_SECONDS": "0.10",
            "MWCC_INSPECT_NATIVE_PID_CMD": str(native_pid),
            "MWCC_INSPECT_POLL_SECONDS": "0.005",
            "MWCC_INSPECT_SETSID": str(setsid),
            "MWCC_INSPECT_STARTUP_SECONDS": "1",
            "MWCC_INSPECT_TASKKILL": str(taskkill),
        }
    )
    return env


def _supervisor_command(mode: str, job: Path, job_id: str, *args: str) -> list[str]:
    return [
        str(SUPERVISOR),
        mode,
        "--job-dir",
        str(job),
        "--job-id",
        job_id,
        "--token",
        TOKEN,
        *args,
    ]


def _terminal(job: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in (job / "terminal").read_text(encoding="utf-8").splitlines()
    )


def _launch_supervisor(
    job: Path,
    job_id: str,
    env: dict[str, str],
    *,
    deadline: str = "5",
    child_seconds: str = "30",
) -> subprocess.CompletedProcess[str]:
    code = (
        "import time\n"
        "print('FUNCTION: fn_test', flush=True)\n"
        "print('Compilation finished.', flush=True)\n"
        f"time.sleep({child_seconds})\n"
    )
    return subprocess.run(
        _supervisor_command(
            "launch",
            job,
            job_id,
            "--deadline-seconds",
            deadline,
            "--",
            sys.executable,
            "-c",
            code,
        ),
        env=env,
        capture_output=True,
        text=True,
        timeout=3,
    )


def test_mwcc_inspect_upload_uses_remote_bash_stdin_for_candidate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workflow = repo / "tools" / "workflow"
    workflow.mkdir(parents=True)
    _copy_inspect_workflow(workflow)

    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/pl/plbonuslib",'
        '"functions":[{"name":"fn_test"}]}]}',
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_test(void) { int candidate = 1; }\n", encoding="utf-8")
    (tmp_path / "plbonuslib.h").write_text("#define LOCAL_HEADER 1\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "build/GALE01/report.json", "tools/workflow/mwcc-inspect.sh"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "codex/local-only"], cwd=repo, check=True)
    exact_commit = _head_commit(repo)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_dir = tmp_path / "ssh-log"
    log_dir.mkdir()
    _write_executable(
        fake_bin / "ninja",
        "#!/usr/bin/env bash\n"
        "echo 'python wrapper mwcceppc.exe -cwd source -i src -i src/melee "
        "-i src/MSL -i src/Runtime -i extern/dolphin/include -i /opt/external -c -o "
        "build/GALE01/src/melee/pl/plbonuslib.o src/melee/pl/plbonuslib.c "
        "&& transform_dep.py'\n",
    )
    remote_dir, inspector = _install_local_ssh(fake_bin, tmp_path)

    out_file = repo / "build" / "mwcc_inspect" / "candidates" / "candidate.txt"
    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env['PATH']}",
        "FAKE_INSPECTOR_OUTPUT": "FUNCTION: fn_test\nCompilation finished.\n",
        "FAKE_REMOTE_BIN": str(inspector.parent),
        "FAKE_SSH_LOG": str(log_dir),
        "MWCC_INSPECT_HOST": "fake-host",
        "MWCC_INSPECT_REMOTE_BASH": "bash",
        "MWCC_INSPECT_REMOTE_DIR": str(remote_dir),
        "MWCC_INSPECT_CLI": str(inspector),
        "MWCC_INSPECT_REMOTE_REF": "HEAD",
    })

    proc = subprocess.run(
        [
            str(workflow / "mwcc-inspect.sh"),
            "--function",
            "fn_test",
            "--output",
            str(out_file),
            str(candidate),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"[mwcc-inspect] Remote ref: {exact_commit}" in proc.stdout
    assert "FUNCTION: fn_test" in out_file.read_text(encoding="utf-8")
    argv_logs = [path.read_text(encoding="utf-8") for path in sorted(log_dir.glob("*.argv"))]
    assert all("'-lc'" not in argv for argv in argv_logs)
    assert all("'-s'" in argv for argv in argv_logs)
    stdin_logs = [path.read_text(encoding="utf-8") for path in sorted(log_dir.glob("*.stdin"))]
    init_log = next(log for log in stdin_logs if "stage=job-init" in log)
    job_id = re.search(r"JOB_ID='([^']+)'", init_log)
    assert job_id is not None
    remote_tmp = f"{remote_dir}/build/mwcc-inspect-jobs/{job_id.group(1)}/candidate"
    assert f"REMOTE_TMP='{remote_tmp}'" in init_log
    assert init_log.rstrip().endswith("exit 0")
    mkdir_log = next(log for log in stdin_logs if f"mkdir -p '{remote_tmp}/src/melee/pl'" in log)
    assert mkdir_log.rstrip().endswith("exit")
    upload_log = next(log for log in stdin_logs if "plbonuslib.c" in log)
    assert f"cat > '{remote_tmp}/src/melee/pl/plbonuslib.c'" in upload_log
    assert "int candidate = 1;" in upload_log
    assert upload_log.rstrip().endswith("exit")
    header_log = next(log for log in stdin_logs if "plbonuslib.h" in log)
    assert f"cat > '{remote_tmp}/src/melee/pl/plbonuslib.h'" in header_log
    assert "#define LOCAL_HEADER 1" in header_log
    assert header_log.rstrip().endswith("exit")
    headers_copy_log = next(
        log
        for log in stdin_logs
        if f"find '{remote_dir}/src/melee/pl'" in log and "-name '*.h'" in log
    )
    assert headers_copy_log.rstrip().endswith("exit")
    inspector_log = next(log for log in stdin_logs if "stage=supervisor-launch" in log)
    assert f"checkout --quiet '{exact_commit}'" in inspector_log
    assert "git fetch origin --prune '+refs/heads/*:refs/remotes/origin/*'" in inspector_log
    assert "if ! git rev-parse --verify" not in inspector_log
    assert f"git cat-file -e '{exact_commit}^{{commit}}'" in inspector_log
    assert (
        inspector_log.index("git fetch origin --prune '+refs/heads/*:refs/remotes/origin/*'")
        < inspector_log.index(f"git cat-file -e '{exact_commit}^{{commit}}'")
    )
    assert f"remote is missing ref '{exact_commit}'" in inspector_log
    assert "codex/local-only" not in inspector_log
    assert f"REMOTE_DIR='{remote_dir}'" in inspector_log
    assert (
        'MWCC_ARGS_REMOTE="-i ${REMOTE_TMP}/src -i ${REMOTE_TMP}/src/melee '
        '${MWCC_ARGS_REMOTE}"'
    ) in inspector_log
    assert (
        'MWCC_ARGS_REMOTE="$(sed -E "s@(^|[[:space:]])-i[[:space:]]+'
        '([^/[:space:]][^[:space:]]*)@\\1-i ${REMOTE_DIR}/\\2@g" '
        '<<< "${MWCC_ARGS_REMOTE}")"'
    ) in inspector_log
    assert "-i src -i src/melee -i src/MSL -i src/Runtime" in inspector_log
    assert "-i extern/dolphin/include -i /opt/external" in inspector_log
    assert "${REMOTE_DIR}//opt/external" not in inspector_log
    assert "REMOTE_TMP_REL" not in inspector_log
    assert "export MWCC_ARGS_REMOTE" in inspector_log
    assert inspector_log.rstrip().endswith('"${COMMAND}"')
    assert not (remote_dir / "build" / "mwcc-inspect-jobs" / job_id.group(1)).exists()


def test_mwcc_inspect_remote_failure_preserves_diagnostics_and_no_empty_output(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    workflow = repo / "tools" / "workflow"
    workflow.mkdir(parents=True)
    _copy_inspect_workflow(workflow)

    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/pl/plbonuslib",'
        '"functions":[{"name":"fn_test"}]}]}',
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_test(void) { int candidate = 1; }\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "add", "build/GALE01/report.json", "tools/workflow/mwcc-inspect.sh"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    exact_commit = _head_commit(repo)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "ninja",
        "#!/bin/sh\n"
        "echo 'python wrapper mwcceppc.exe -c -o "
        "build/GALE01/src/melee/pl/plbonuslib.o src/melee/pl/plbonuslib.c "
        "&& transform_dep.py'\n",
    )
    remote_dir, inspector = _install_local_ssh(fake_bin, tmp_path)

    out_file = repo / "build" / "mwcc_inspect" / "candidates" / "candidate.txt"
    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env['PATH']}",
        "FAKE_INSPECTOR_EXIT": "42",
        "FAKE_INSPECTOR_STDERR": "mwcc inspector failed before structured output\n",
        "FAKE_REMOTE_BIN": str(inspector.parent),
        "MWCC_INSPECT_HOST": "fake-host",
        "MWCC_INSPECT_REMOTE_BASH": "bash",
        "MWCC_INSPECT_REMOTE_DIR": str(remote_dir),
        "MWCC_INSPECT_CLI": str(inspector),
        "MWCC_INSPECT_REMOTE_REF": "HEAD",
    })

    proc = subprocess.run(
        [
            str(workflow / "mwcc-inspect.sh"),
            "--function",
            "fn_test",
            "--output",
            str(out_file),
            str(candidate),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 1
    assert f"[mwcc-inspect] Remote ref: {exact_commit}" in proc.stdout
    assert "[mwcc-inspect] invocation" in proc.stderr
    assert "inspector-exit-42" in proc.stderr
    assert "mwcc inspector failed before structured output" in proc.stderr
    assert not out_file.exists() or out_file.stat().st_size > 0
    assert len(list((remote_dir / "build" / "mwcc-inspect-jobs").iterdir())) == 1


def test_mwcc_inspect_rejects_remote_job_initialization_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workflow = repo / "tools" / "workflow"
    workflow.mkdir(parents=True)
    _copy_inspect_workflow(workflow)

    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/pl/plbonuslib",'
        '"functions":[{"name":"fn_test"}]}]}',
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_test(void) { int candidate = 1; }\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "add", "build/GALE01/report.json", "tools/workflow/mwcc-inspect.sh"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    exact_commit = _head_commit(repo)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "ninja",
        "#!/bin/sh\n"
        "echo 'python wrapper mwcceppc.exe -c -o "
        "build/GALE01/src/melee/pl/plbonuslib.o src/melee/pl/plbonuslib.c "
        "&& transform_dep.py'\n",
    )
    _write_executable(
        fake_bin / "ssh",
        textwrap.dedent("""\
            #!/usr/bin/env python3
            from __future__ import annotations

            import os
            import select
            import sys
            from pathlib import Path

            log_dir = Path(os.environ["FAKE_SSH_LOG"])
            idx = len(list(log_dir.glob("*.stdin")))
            chunks = []
            while True:
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                if not ready:
                    break
                chunk = os.read(sys.stdin.fileno(), 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            payload = b"".join(chunks).decode()
            (log_dir / f"{idx:02d}.stdin").write_text(payload, encoding="utf-8")
            if "stage=job-init" in payload:
                print("remote job directory collision", file=sys.stderr)
                sys.exit(73)
            raise AssertionError("wrapper should abort before later remote calls")
        """),
    )

    log_dir = tmp_path / "ssh-log"
    log_dir.mkdir()
    out_file = repo / "build" / "mwcc_inspect" / "candidates" / "candidate.txt"
    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env['PATH']}",
        "FAKE_SSH_LOG": str(log_dir),
        "MWCC_INSPECT_HOST": "fake-host",
        "MWCC_INSPECT_REMOTE_BASH": "bash",
        "MWCC_INSPECT_REMOTE_DIR": "/remote/melee",
        "MWCC_INSPECT_CLI": "/remote/MwccInspectorCLI",
        "MWCC_INSPECT_REMOTE_REF": "HEAD",
    })

    proc = subprocess.run(
        [
            str(workflow / "mwcc-inspect.sh"),
            "--function",
            "fn_test",
            "--output",
            str(out_file),
            str(candidate),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode != 0
    assert f"[mwcc-inspect] Remote ref: {exact_commit}" in proc.stdout
    assert proc.returncode == 73
    assert "remote job directory collision" in proc.stderr
    assert not out_file.exists()
    assert len(list(log_dir.glob("*.stdin"))) == 1


@pytest.mark.parametrize(
    ("inspector_output", "expected_diagnostic"),
    [
        (
            "FUNCTION: fn_test\n"
            "# Error: cannot open lb/lb_00F9.h\n"
            "Compilation finished\n",
            "compiler-diagnostics",
        ),
        ("Compilation finished\n", "no-function-section"),
    ],
    ids=["compiler-diagnostic", "functionless-output"],
)
def test_mwcc_inspect_rejects_invalid_zero_exit_output(
    tmp_path: Path,
    inspector_output: str,
    expected_diagnostic: str,
) -> None:
    repo = tmp_path / "repo"
    workflow = repo / "tools" / "workflow"
    workflow.mkdir(parents=True)
    _copy_inspect_workflow(workflow)

    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/pl/plbonuslib",'
        '"functions":[{"name":"fn_test"}]}]}',
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_test(void) { int candidate = 1; }\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "add", "build/GALE01/report.json", "tools/workflow/mwcc-inspect.sh"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    exact_commit = _head_commit(repo)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "ninja",
        "#!/bin/sh\n"
        "echo 'python wrapper mwcceppc.exe -c -o "
        "build/GALE01/src/melee/pl/plbonuslib.o src/melee/pl/plbonuslib.c "
        "&& transform_dep.py'\n",
    )
    remote_dir, inspector = _install_local_ssh(fake_bin, tmp_path)

    out_file = repo / "build" / "mwcc_inspect" / "candidates" / "candidate.txt"
    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env['PATH']}",
        "FAKE_INSPECTOR_OUTPUT": inspector_output,
        "FAKE_REMOTE_BIN": str(inspector.parent),
        "MWCC_INSPECT_HOST": "fake-host",
        "MWCC_INSPECT_REMOTE_BASH": "bash",
        "MWCC_INSPECT_REMOTE_DIR": str(remote_dir),
        "MWCC_INSPECT_CLI": str(inspector),
        "MWCC_INSPECT_REMOTE_REF": "HEAD",
    })

    proc = subprocess.run(
        [
            str(workflow / "mwcc-inspect.sh"),
            "--function",
            "fn_test",
            "--output",
            str(out_file),
            str(candidate),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode != 0
    assert f"[mwcc-inspect] Remote ref: {exact_commit}" in proc.stdout
    assert not out_file.exists()
    assert not list(out_file.parent.glob(f"{out_file.name}.stage.*"))
    assert expected_diagnostic in proc.stderr


def test_mwcc_inspect_help_and_detached_supervisor_contract() -> None:
    script = REPO_ROOT / "tools" / "workflow" / "mwcc-inspect.sh"
    help_proc = subprocess.run([str(script), "--help"], capture_output=True, text=True, check=True)
    help_text = help_proc.stdout + help_proc.stderr
    assert "--invocation-id" in help_text
    assert "--deadline-seconds" in help_text
    assert "--cancel" in help_text
    assert "--cleanup-timeout" in help_text

    wrapper = script.read_text(encoding="utf-8")
    assert "taskkill" not in wrapper
    assert "msys.pid" not in wrapper
    assert "win.pid" not in wrapper
    assert "owner.pid" not in wrapper
    assert 'REMOTE_PHASE_STARTED="$(python3' not in wrapper
    assert "python3" not in SUPERVISOR.read_text(encoding="utf-8")
    assert ".stage.${INVOCATION_ID}" in wrapper

    supervisor = SUPERVISOR.read_text(encoding="utf-8")
    for native_security_term in (
        "SetAccessRuleProtection",
        "AreAccessRulesProtected",
        "ReparsePoint",
        "WindowsIdentity",
        "SecurityIdentifier",
        "ContainerInherit",
        "ObjectInherit",
        "FullControl",
        "MWCC_INSPECT_WINDOWS_ACL_READY:",
        "MWCC_INSPECT_WINDOWS_SECURITY_OK:",
    ):
        assert native_security_term in wrapper + supervisor
    assert "-EncodedCommand" in wrapper
    assert "-EncodedCommand" in supervisor
    assert "MSYS2_ARG_CONV_EXCL" in wrapper
    assert "MSYS2_ARG_CONV_EXCL" in supervisor
    assert "</dev/null" in wrapper
    assert "</dev/null" in supervisor
    assert "ps -W" in supervisor
    assert "-o winpid=" not in supervisor
    assert "-Command -" not in wrapper
    assert "-Command -" not in supervisor
    assert "[System.IO.Directory]::CreateDirectory" in wrapper
    assert wrapper.count('exec "${JOB_DIR}/supervisor"') == 1
    assert 'exec "${JOB_DIR}/supervisor" launch' in wrapper
    assert "trusted_remote_supervisor finalize-stored-token" in wrapper
    assert "trusted_remote_supervisor cancel-stored-token" in wrapper
    assert "trusted_remote_supervisor await" in wrapper
    assert "trusted_remote_supervisor emit-success" in wrapper
    assert "TRUSTED_SUPERVISOR_SHA256" in wrapper
    assert "trusted supervisor transport hash mismatch" in wrapper
    assert '"${trusted_supervisor}" "$@" </dev/null' in wrapper


def test_mwcc_inspect_local_promotion_failure_still_finalizes_remote_success(
    tmp_path: Path,
) -> None:
    repo, script, candidate, env, remote_dir = _wrapper_fixture(tmp_path)
    out_file = tmp_path / "promotion-failure.txt"
    fake_mv = tmp_path / "bin" / "mv"
    _write_executable(
        fake_mv,
        "#!/usr/bin/env bash\n"
        f"if [[ \"${{!#}}\" == '{out_file}' ]]; then exit 77; fi\n"
        "exec /bin/mv \"$@\"\n",
    )
    proc = subprocess.run(
        [
            str(script),
            "--invocation-id",
            "promotion-failure",
            "--function",
            "fn_test",
            "--output",
            str(out_file),
            str(candidate),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 77
    assert not out_file.exists()
    jobs = remote_dir / "build" / "mwcc-inspect-jobs"
    assert not (jobs / "promotion-failure").exists()


def test_mwcc_inspect_finalize_failure_is_nonzero_and_retains_diagnostics(
    tmp_path: Path,
) -> None:
    repo, script, candidate, env, remote_dir = _wrapper_fixture(tmp_path)
    out_file = tmp_path / "finalize-failure.txt"
    env["FAKE_FINALIZE_FAILURE"] = "1"
    proc = subprocess.run(
        [
            str(script),
            "--invocation-id",
            "finalize-failure",
            "--function",
            "fn_test",
            "--output",
            str(out_file),
            str(candidate),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 125
    assert "retained success cleanup failed" in proc.stderr
    assert out_file.read_text(encoding="utf-8") == "FUNCTION: fn_test\nCompilation finished.\n"
    job = remote_dir / "build" / "mwcc-inspect-jobs" / "finalize-failure"
    assert job.exists()
    assert _terminal(job)["status"] == "success"


def test_mwcc_inspect_rejects_unsafe_invocation_id_before_ssh(tmp_path: Path) -> None:
    script = REPO_ROOT / "tools" / "workflow" / "mwcc-inspect.sh"
    fake_ssh = tmp_path / "ssh"
    touched = tmp_path / "ssh-called"
    _write_executable(fake_ssh, f"#!/bin/sh\ntouch '{touched}'\nexit 99\n")
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    proc = subprocess.run(
        [str(script), "--cancel", "unsafe;taskkill-all"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert proc.returncode == 64
    assert "invalid invocation ID" in proc.stderr
    assert not touched.exists()


def test_mwcc_inspect_cancel_reads_stored_token_and_cancels_in_one_connection(
    tmp_path: Path,
) -> None:
    repo, script, _candidate, env, remote_dir = _wrapper_fixture(tmp_path)
    log_dir = tmp_path / "ssh-log"
    log_dir.mkdir()
    env["FAKE_SSH_LOG"] = str(log_dir)
    job_id = "one-connection-cancel"
    job = remote_dir / "build" / "mwcc-inspect-jobs" / job_id
    job.mkdir(parents=True, mode=0o700)
    job.chmod(0o700)
    (job / "token").write_text(f"{TOKEN}\n", encoding="utf-8")
    (job / "terminal").write_text(
        "version=1\n"
        f"id={job_id}\n"
        f"token={TOKEN}\n"
        "status=cancelled\n"
        "reason=requested\n"
        "child_reaped=true\n"
        "artifact_sha256=\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [str(script), "--cancel", job_id, "--cleanup-timeout", "3"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payloads = [path.read_text(encoding="utf-8") for path in log_dir.glob("*.stdin")]
    assert len(payloads) == 1
    assert "set -- 'cancel-stored-token'" in payloads[0]
    assert "set -- 'read-token'" not in payloads[0]


def test_supervisor_taskkill_failure_is_terminal_cleanup_failure(tmp_path: Path) -> None:
    job_id = "taskkill-failure"
    job = _supervisor_job(tmp_path, job_id)
    env = _supervisor_env(tmp_path, taskkill_mode="fail")
    launched = _launch_supervisor(job, job_id, env, child_seconds="0.35")
    assert launched.returncode == 0, launched.stdout + launched.stderr

    started = time.monotonic()
    proc = subprocess.run(
        _supervisor_command("cancel", job, job_id, "--wait-seconds", "1"),
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert proc.returncode == 125
    assert time.monotonic() - started < 0.25
    assert "cleanup failed" in proc.stderr
    assert _terminal(job) == {
        "version": "1",
        "id": job_id,
        "token": TOKEN,
        "status": "cleanup-failed",
        "reason": "cancelled-requested-taskkill-exit-7",
        "child_reaped": "false",
        "artifact_sha256": "",
    }
    _wait_for_path(job / "cleanup-eventually-reaped", timeout=2)
    finalize = subprocess.run(
        _supervisor_command("finalize-success", job, job_id),
        env=env,
        capture_output=True,
        text=True,
    )
    assert finalize.returncode == 125
    assert job.exists()


def test_supervisor_reports_child_survival_after_successful_taskkill(tmp_path: Path) -> None:
    job_id = "child-survived"
    job = _supervisor_job(tmp_path, job_id)
    env = _supervisor_env(tmp_path, taskkill_mode="survive")
    launched = _launch_supervisor(job, job_id, env, deadline="0.05", child_seconds="30")
    assert launched.returncode == 0, launched.stdout + launched.stderr
    _wait_for_path(job / "terminal")
    terminal = _terminal(job)
    assert terminal["status"] == "cleanup-failed"
    assert terminal["reason"] == "timeout-deadline-child-survived-taskkill"
    assert terminal["child_reaped"] == "false"
    child_pid = int((tmp_path / "taskkill.log").read_text().split()[1])
    os.kill(child_pid, signal.SIGTERM)
    _wait_for_path(job / "cleanup-eventually-reaped", timeout=2)


def test_supervisor_enforces_precise_subsecond_deadline(tmp_path: Path) -> None:
    job_id = "precise-deadline"
    job = _supervisor_job(tmp_path, job_id)
    env = _supervisor_env(tmp_path)
    started = time.monotonic()
    proc = subprocess.Popen(
        _supervisor_command(
            "supervise",
            job,
            job_id,
            "--deadline-seconds",
            "0.125",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = proc.communicate(timeout=2)
    deadline_elapsed = time.monotonic() - started
    assert proc.returncode == 124, stdout + stderr
    assert 0.10 <= deadline_elapsed < 0.50
    terminal = _terminal(job)
    assert terminal["status"] == "timeout"
    assert terminal["reason"] == "deadline"
    assert terminal["child_reaped"] == "true"


def test_supervisor_deadline_wins_over_simultaneous_complete_output(tmp_path: Path) -> None:
    job_id = "deadline-boundary"
    job = _supervisor_job(tmp_path, job_id)
    env = _supervisor_env(tmp_path)
    child_complete = tmp_path / "child-complete"
    child_pid_file = tmp_path / "boundary-child.pid"
    clock_count = tmp_path / "clock-count"
    bash_env = tmp_path / "boundary-bash-env"
    gated_native_pid = tmp_path / "gated-native-pid"
    monotonic_clock = tmp_path / "monotonic-clock"
    _write_executable(
        gated_native_pid,
        "#!/bin/sh\n"
        "while [[ ! -e \"$BOUNDARY_CHILD_COMPLETE\" ]]; do sleep 0.005; done\n"
        "printf '%s\\n' \"$1\" > \"$BOUNDARY_CHILD_PID_FILE\"\n"
        "printf '%s\\n' \"$1\"\n",
    )
    bash_env.write_text(
        "kill() {\n"
        "  if [[ \"$1\" == '-0' && -f \"$BOUNDARY_CHILD_PID_FILE\" ]] && "
        "[[ \"$2\" == \"$(cat \"$BOUNDARY_CHILD_PID_FILE\")\" ]] && "
        "[[ -e \"$BOUNDARY_CHILD_COMPLETE\" ]]; then\n"
        "    return 1\n"
        "  fi\n"
        "  builtin kill \"$@\"\n"
        "}\n",
        encoding="utf-8",
    )
    _write_executable(
        monotonic_clock,
        textwrap.dedent("""\
            #!/usr/bin/env python3
            import os
            from pathlib import Path

            count_path = Path(os.environ["BOUNDARY_CLOCK_COUNT"])
            count = int(count_path.read_text()) if count_path.exists() else 0
            count_path.write_text(str(count + 1), encoding="utf-8")
            print("100.0" if count == 0 else ("100.1" if count == 1 else "102.0"))
        """),
    )
    env["BOUNDARY_CHILD_COMPLETE"] = str(child_complete)
    env["BOUNDARY_CHILD_PID_FILE"] = str(child_pid_file)
    env["BOUNDARY_CLOCK_COUNT"] = str(clock_count)
    env["BASH_ENV"] = str(bash_env)
    env["MWCC_INSPECT_MONOTONIC_CMD"] = str(monotonic_clock)
    env["MWCC_INSPECT_NATIVE_PID_CMD"] = str(gated_native_pid)
    child_code = (
        "from pathlib import Path\n"
        "print('FUNCTION: fn_test', flush=True)\n"
        "print('Compilation finished.', flush=True)\n"
        f"Path({str(child_complete)!r}).write_text('complete', encoding='utf-8')\n"
    )
    proc = subprocess.run(
        _supervisor_command(
            "supervise",
            job,
            job_id,
            "--deadline-seconds",
            "1",
            "--",
            sys.executable,
            "-c",
            child_code,
        ),
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert proc.returncode == 124, proc.stdout + proc.stderr
    assert child_complete.read_text(encoding="utf-8") == "complete"
    # Calls 1/2 establish the execution and PID-resolution deadlines. The third
    # call is the first loop observation, gated until the child is complete.
    assert int(clock_count.read_text(encoding="utf-8")) == 3
    assert _terminal(job)["status"] == "timeout"
    assert not (job / "artifact.success").exists()
    emitted = subprocess.run(
        _supervisor_command("emit-success", job, job_id),
        env=env,
        capture_output=True,
        text=True,
    )
    assert emitted.returncode == 125


def test_supervisor_cancel_kills_descendant_before_late_final_output_write(
    tmp_path: Path,
) -> None:
    job_id = "descendant-late-write"
    job = _supervisor_job(tmp_path, job_id)
    env = _supervisor_env(tmp_path, taskkill_mode="kill-tree")
    canonical_output = tmp_path / "canonical-output.txt"
    canonical_output.write_text("baseline\n", encoding="utf-8")
    descendant_pid_file = tmp_path / "descendant.pid"
    late_code = (
        "import time\n"
        "from pathlib import Path\n"
        "time.sleep(0.35)\n"
        f"Path({str(canonical_output)!r}).write_text('late write\\n', encoding='utf-8')\n"
    )
    child_code = textwrap.dedent(f"""\
        import subprocess
        import sys
        import time
        from pathlib import Path

        descendant = subprocess.Popen([sys.executable, "-c", {late_code!r}])
        Path({str(descendant_pid_file)!r}).write_text(str(descendant.pid), encoding="utf-8")
        print("FUNCTION: fn_test", flush=True)
        print("Compilation finished.", flush=True)
        time.sleep(30)
    """)
    launched = subprocess.run(
        _supervisor_command(
            "launch",
            job,
            job_id,
            "--deadline-seconds",
            "5",
            "--",
            sys.executable,
            "-c",
            child_code,
        ),
        env=env,
        capture_output=True,
        text=True,
        timeout=3,
    )
    assert launched.returncode == 0, launched.stdout + launched.stderr
    _wait_for_path(descendant_pid_file)
    descendant_pid = int(descendant_pid_file.read_text(encoding="utf-8"))

    cancelled = subprocess.run(
        _supervisor_command("cancel", job, job_id, "--wait-seconds", "1"),
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert cancelled.returncode == 0, cancelled.stdout + cancelled.stderr
    assert _terminal(job)["status"] == "cancelled"
    taskkill_args = (tmp_path / "taskkill.log").read_text(encoding="utf-8")
    taskkill_tokens = taskkill_args.split()
    assert taskkill_tokens[0] == "//PID"
    assert taskkill_tokens[2:] == ["//T", "//F"]
    _wait_for_pid_exit(int(taskkill_tokens[1]))
    _wait_for_pid_exit(descendant_pid)
    time.sleep(0.45)
    assert canonical_output.read_text(encoding="utf-8") == "baseline\n"


def test_supervisor_accepts_token_bound_msys_directory_without_posix_mode(
    tmp_path: Path,
) -> None:
    job_id = "msys-permissions"
    job = _supervisor_job(tmp_path, job_id)
    job.chmod(0o755)
    env = _supervisor_env(tmp_path)
    env["MWCC_INSPECT_PLATFORM"] = "MSYS_NT-10.0"
    validator = tmp_path / "windows-security-validator"
    _write_executable(
        validator,
        "#!/bin/sh\n"
        "test \"$1\" = \"$EXPECTED_WINDOWS_JOB\" || exit 1\n"
        "printf 'MWCC_INSPECT_WINDOWS_SECURITY_OK:S-1-5-21-1001\\n'\n",
    )
    env["EXPECTED_WINDOWS_JOB"] = str(job)
    env["MWCC_INSPECT_WINDOWS_SECURITY_CMD"] = str(validator)
    launched = _launch_supervisor(job, job_id, env, deadline="2", child_seconds="0")
    assert launched.returncode == 0, launched.stdout + launched.stderr
    _wait_for_path(job / "terminal")
    assert _terminal(job)["status"] == "success"


def test_supervisor_rejects_msys_directory_when_native_security_validation_fails(
    tmp_path: Path,
) -> None:
    job_id = "msys-insecure"
    job = _supervisor_job(tmp_path, job_id)
    job.chmod(0o755)
    env = _supervisor_env(tmp_path)
    env["MWCC_INSPECT_PLATFORM"] = "MSYS_NT-10.0"
    validator = tmp_path / "windows-security-validator"
    _write_executable(validator, "#!/bin/sh\nexit 19\n")
    env["MWCC_INSPECT_WINDOWS_SECURITY_CMD"] = str(validator)

    proc = subprocess.run(
        _supervisor_command(
            "supervise",
            job,
            job_id,
            "--deadline-seconds",
            "1",
            "--",
            sys.executable,
            "-c",
            "print('FUNCTION: fn_test\\nCompilation finished.')",
        ),
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert proc.returncode == 125
    assert "native Windows security validation failed" in proc.stderr
    assert not (job / "ready").exists()
    assert not (job / "artifact.partial").exists()


def test_supervisor_rejects_silent_success_from_noop_windows_powershell(
    tmp_path: Path,
) -> None:
    job_id = "msys-noop-powershell"
    job = _supervisor_job(tmp_path, job_id)
    job.chmod(0o755)
    env = _supervisor_env(tmp_path)
    env["MWCC_INSPECT_PLATFORM"] = "MSYS_NT-10.0"
    cygpath = tmp_path / "cygpath"
    powershell = tmp_path / "powershell.exe"
    _write_executable(cygpath, "#!/bin/sh\nprintf '%s\\n' \"$2\"\n")
    _write_executable(powershell, "#!/bin/sh\nexit 0\n")
    env["MWCC_INSPECT_CYGPATH"] = str(cygpath)
    env["MWCC_INSPECT_POWERSHELL"] = str(powershell)

    proc = subprocess.run(
        _supervisor_command(
            "supervise",
            job,
            job_id,
            "--deadline-seconds",
            "1",
            "--",
            sys.executable,
            "-c",
            "print('FUNCTION: fn_test\\nCompilation finished.')",
        ),
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert proc.returncode == 125
    assert "native Windows security validation failed" in proc.stderr
    assert not (job / "artifact.partial").exists()


def test_streamed_supervisor_isolates_powershell_from_script_stdin(
    tmp_path: Path,
) -> None:
    job_id = "streamed-powershell-stdin"
    job = _supervisor_job(tmp_path, job_id)
    job.chmod(0o755)
    env = _supervisor_env(tmp_path)
    env["MWCC_INSPECT_PLATFORM"] = "MSYS_NT-10.0"
    cygpath = tmp_path / "cygpath"
    powershell = tmp_path / "powershell.exe"
    _write_executable(cygpath, "#!/bin/sh\nprintf '%s\\n' \"$2\"\n")
    _write_executable(
        powershell,
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        "printf 'MWCC_INSPECT_WINDOWS_SECURITY_OK:S-1-5-21-1001\\n'\n",
    )
    env["MWCC_INSPECT_CYGPATH"] = str(cygpath)
    env["MWCC_INSPECT_POWERSHELL"] = str(powershell)
    args = _supervisor_command(
        "supervise",
        job,
        job_id,
        "--deadline-seconds",
        "1",
        "--",
        sys.executable,
        "-c",
        "print('FUNCTION: fn_test\\nCompilation finished.')",
    )[1:]
    payload = "set -- " + " ".join(shlex.quote(arg) for arg in args) + "\n"
    payload += SUPERVISOR.read_text(encoding="utf-8")

    proc = subprocess.run(
        ["bash", "-s"],
        input=payload,
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _terminal(job)["status"] == "success"


def test_supervisor_rejects_non_64_hex_job_token(tmp_path: Path) -> None:
    job_id = "short-token"
    job = _supervisor_job(tmp_path, job_id)
    short_token = "a" * 32
    (job / "token").write_text(f"{short_token}\n", encoding="utf-8")
    cmd = _supervisor_command(
        "supervise",
        job,
        job_id,
        "--deadline-seconds",
        "1",
        "--",
        sys.executable,
        "-c",
        "print('FUNCTION: fn_test\\nCompilation finished.')",
    )
    cmd[cmd.index(TOKEN)] = short_token

    proc = subprocess.run(
        cmd,
        env=_supervisor_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert proc.returncode == 64
    assert "invalid token" in proc.stderr
    assert not (job / "artifact.partial").exists()


def test_supervisor_rejects_msys_symlink_job_directory(tmp_path: Path) -> None:
    real_job = _supervisor_job(tmp_path, "real-job")
    linked_job = tmp_path / "linked-job"
    linked_job.symlink_to(real_job, target_is_directory=True)
    env = _supervisor_env(tmp_path)
    env["MWCC_INSPECT_PLATFORM"] = "MSYS_NT-10.0"
    proc = subprocess.run(
        _supervisor_command(
            "supervise",
            linked_job,
            "linked-job",
            "--deadline-seconds",
            "1",
            "--",
            sys.executable,
            "-c",
            "print('FUNCTION: fn_test\\nCompilation finished.')",
        ),
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert proc.returncode == 125
    assert "safe job directory" in proc.stderr


def test_supervisor_survives_launcher_loss_and_publishes_only_after_exit(tmp_path: Path) -> None:
    job_id = "launcher-loss"
    job = _supervisor_job(tmp_path, job_id)
    env = _supervisor_env(tmp_path)
    launched = _launch_supervisor(job, job_id, env, deadline="2", child_seconds="0.25")
    assert launched.returncode == 0, launched.stdout + launched.stderr
    assert (job / "ready").exists()
    assert not (job / "terminal").exists()
    assert not (job / "artifact.success").exists()

    _wait_for_path(job / "terminal")
    terminal = _terminal(job)
    assert terminal["status"] == "success"
    assert terminal["child_reaped"] == "true"
    emitted = subprocess.run(
        _supervisor_command("emit-success", job, job_id),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert emitted.stdout == "FUNCTION: fn_test\nCompilation finished.\n"


def test_detached_command_receives_args_and_success_finalization_removes_job(
    tmp_path: Path,
) -> None:
    job_id = "real-command"
    job = _supervisor_job(tmp_path, job_id)
    env = _supervisor_env(tmp_path)
    args_log = tmp_path / "args.json"
    inspector = tmp_path / "inspector"
    command = job / "inspector-command"
    _write_executable(
        inspector,
        textwrap.dedent("""\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            Path(os.environ["ARGS_LOG"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
            print("FUNCTION: fn_test")
            print("Compilation finished.")
        """),
    )
    _write_executable(
        command,
        f"#!/usr/bin/env bash\nset -euo pipefail\nexec '{inspector}' ${{MWCC_ARGS_REMOTE}}\n",
    )
    env["ARGS_LOG"] = str(args_log)
    env["MWCC_ARGS_REMOTE"] = "--alpha two --omega"
    launched = subprocess.run(
        _supervisor_command(
            "launch",
            job,
            job_id,
            "--deadline-seconds",
            "2",
            "--",
            str(command),
        ),
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert launched.returncode == 0, launched.stdout + launched.stderr
    _wait_for_path(job / "terminal")
    assert args_log.read_text(encoding="utf-8") == '["--alpha", "two", "--omega"]'
    finalize = subprocess.run(
        _supervisor_command("finalize-success", job, job_id),
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr
    assert not job.exists()


def test_supervisor_ignores_stale_pid_files_and_cancel_is_invocation_scoped(
    tmp_path: Path,
) -> None:
    env = _supervisor_env(tmp_path)
    first = _supervisor_job(tmp_path, "scope-a")
    second = _supervisor_job(tmp_path, "scope-b")
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        for name in ("msys.pid", "win.pid", "owner.pid"):
            (first / name).write_text(f"{sentinel.pid}\n", encoding="utf-8")
        for job, job_id in ((first, "scope-a"), (second, "scope-b")):
            launched = _launch_supervisor(job, job_id, env)
            assert launched.returncode == 0, launched.stdout + launched.stderr

        cancel = subprocess.run(
            _supervisor_command("cancel", first, "scope-a", "--wait-seconds", "1"),
            env=env,
            capture_output=True,
            text=True,
            timeout=2,
        )
        assert cancel.returncode == 0, cancel.stdout + cancel.stderr
        assert _terminal(first)["status"] == "cancelled"
        assert sentinel.poll() is None
        assert not (second / "terminal").exists()

        taskkill_args = (tmp_path / "taskkill.log").read_text().split()
        assert taskkill_args[0] == "//PID"
        assert taskkill_args[2:] == ["//T", "//F"]
        killed_pid = int(taskkill_args[1])
        assert killed_pid != sentinel.pid
    finally:
        subprocess.run(
            _supervisor_command("cancel", second, "scope-b", "--wait-seconds", "1"),
            env=env,
            capture_output=True,
            text=True,
            timeout=2,
        )
        sentinel.send_signal(signal.SIGKILL)
        sentinel.wait(timeout=2)
