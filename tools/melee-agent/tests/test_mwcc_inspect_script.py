"""Tests for the mwcc-inspect workflow wrapper."""

from __future__ import annotations

import hashlib
import json
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
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

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


def _install_local_ssh(
    fake_bin: Path,
    tmp_path: Path,
    *,
    real_git_source: Path | None = None,
) -> tuple[Path, Path]:
    remote_dir = tmp_path / "remote-melee"
    remote_bin = tmp_path / "remote-bin"
    remote_bin.mkdir()
    inspector = remote_bin / "inspector"
    if real_git_source is None:
        (remote_dir / "src" / "melee" / "pl").mkdir(parents=True)
        (remote_dir / "src" / "MSL").mkdir(parents=True)
        (remote_dir / "src" / "Runtime").mkdir(parents=True)
        (remote_dir / "extern" / "dolphin" / "include").mkdir(parents=True)
        _write_executable(
            remote_bin / "git",
            textwrap.dedent("""\
                #!/usr/bin/env python3
                import os
                import shutil
                import sys
                import time
                from pathlib import Path

                args = sys.argv[1:]
                if args[0] == "clone":
                    destination = Path(args[-1])
                    destination.mkdir(parents=True)
                    remote = Path(os.environ["FAKE_REMOTE_DIR"])
                    shutil.copytree(remote / "src", destination / "src")
                    if (remote / "extern").is_dir():
                        shutil.copytree(remote / "extern", destination / "extern")
                    (destination / ".git").mkdir()
                    block_id = os.environ.get("FAKE_CLONE_BLOCK_ID")
                    if block_id and destination.parent.name == block_id:
                        Path(os.environ["FAKE_CLONE_PID"]).write_text(str(os.getpid()))
                        Path(os.environ["FAKE_CLONE_READY"]).write_text("ready")
                        release = Path(os.environ["FAKE_CLONE_RELEASE"])
                        while not release.exists():
                            time.sleep(0.01)
                    raise SystemExit(0)
                if args[0] == "-C":
                    repository = Path(args[1])
                    operation = args[2:]
                    if operation[:2] == ["-c", "advice.detachedHead=false"]:
                        operation = operation[2:]
                    if operation[0] == "checkout":
                        (repository / ".git" / "fake-head").write_text(operation[-1] + "\\n")
                    elif operation[0] == "rev-parse":
                        print((repository / ".git" / "fake-head").read_text().strip())
                    raise SystemExit(0)
                raise SystemExit(0)
            """),
        )
    else:
        subprocess.run(
            ["git", "clone", "-q", str(real_git_source), str(remote_dir)],
            check=True,
        )
    _write_executable(remote_bin / "native-pid", "#!/bin/sh\nprintf '%s\\n' \"$1\"\n")
    _write_executable(remote_bin / "setsid", "#!/bin/sh\nexec \"$@\"\n")
    _write_executable(
        remote_bin / "taskkill.exe",
        textwrap.dedent("""\
            #!/usr/bin/env python3
            import os
            import signal
            import subprocess
            import sys

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
            import stat
            import subprocess
            import sys
            from pathlib import Path

            stdin_is_regular = stat.S_ISREG(os.fstat(sys.stdin.fileno()).st_mode)
            payload = sys.stdin.read()
            if (
                "stage=job-init" in payload
                and os.environ.get("FAKE_REQUIRE_STAGED_LAUNCH")
                and not stdin_is_regular
            ):
                print("compound launch stdin was not fully materialized", file=sys.stderr)
                raise SystemExit(91)
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
                (log_dir / f"{idx:02d}.stdin-kind").write_text(
                    "regular" if stdin_is_regular else "stream",
                    encoding="utf-8",
                )
            env = os.environ.copy()
            env["PATH"] = f"{env['FAKE_REMOTE_BIN']}:{env['PATH']}"
            env["MWCC_INSPECT_NATIVE_PID_CMD"] = str(Path(env["FAKE_REMOTE_BIN"]) / "native-pid")
            env["MWCC_INSPECT_SETSID"] = str(Path(env["FAKE_REMOTE_BIN"]) / "setsid")
            env["MWCC_INSPECT_TASKKILL"] = str(Path(env["FAKE_REMOTE_BIN"]) / "taskkill.exe")
            env["FAKE_REMOTE_DIR"] = env["MWCC_INSPECT_REMOTE_DIR"]
            proc = subprocess.run(["bash", "-s"], input=payload, text=True, env=env)
            raise SystemExit(proc.returncode)
        """),
    )
    return remote_dir, inspector


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)
    return _head_commit(repo)


def _status(repo: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _header_observing_inspector(path: Path) -> None:
    _write_executable(
        path,
        textwrap.dedent("""\
            #!/usr/bin/env python3
            import hashlib
            import json
            import os
            import stat
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            source = Path(args[args.index("-c") + 1])
            output = Path(args[args.index("-o") + 1])
            private_repo = source.parents[3]
            if not source.is_relative_to(private_repo):
                raise SystemExit("source escaped private repo")
            if not output.is_relative_to(private_repo):
                raise SystemExit("output escaped private repo")
            if not output.is_dir():
                print(f"expected -o directory, got: {output}", file=sys.stderr)
                raise SystemExit(86)
            header = source.with_name("inlines.h")
            record = {
                "argv": args,
                "cwd": os.getcwd(),
                "source": str(source),
                "output": str(output),
                "header": header.read_text(encoding="utf-8"),
                "source_mode": stat.S_IMODE(source.stat().st_mode),
                "header_mode": stat.S_IMODE(header.stat().st_mode),
            }
            log = os.environ.get("FAKE_INSPECTOR_RECORD")
            if log:
                Path(log).write_text(json.dumps(record), encoding="utf-8")
            barrier = os.environ.get("FAKE_INSPECTOR_BARRIER")
            if barrier:
                invocation = os.environ["MWCC_INSPECT_INVOCATION_ID"]
                barrier_dir = Path(barrier)
                (barrier_dir / f"ready-{invocation}").write_text("ready")
                release = barrier_dir / f"release-{invocation}"
                while not release.exists():
                    import time
                    time.sleep(0.01)
            digest = hashlib.sha256(header.read_bytes()).hexdigest()
            print(f"HEADER_SHA256={digest}")
            print("HEADER_TEXT=" + header.read_text(encoding="utf-8").strip())
            print("FUNCTION: fn_test")
            print("Compilation finished.")
        """),
    )


def _private_context_fixture(
    tmp_path: Path,
    *,
    header_text: str = "#define BASE_HEADER 1\n",
    compile_args: str = "-i src -i /opt/external",
) -> SimpleNamespace:
    repo = tmp_path / "repo"
    workflow = repo / "tools" / "workflow"
    workflow.mkdir(parents=True)
    script = _copy_inspect_workflow(workflow)
    tu_dir = repo / "src" / "melee" / "mn"
    tu_dir.mkdir(parents=True)
    source = tu_dir / "sample.c"
    source.write_text("void fn_test(void) {}\n", encoding="utf-8")
    header = tu_dir / "inlines.h"
    header.write_text(header_text, encoding="utf-8")
    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/mn/sample",'
        '"functions":[{"name":"fn_test"}]}]}',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    head = _commit(repo, "base")

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    candidate = bundle / "candidate.c"
    candidate.write_text("void fn_test(void) {}\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "ninja",
        "#!/bin/sh\n"
        f"echo 'wrapper mwcceppc.exe {compile_args} -c src/melee/mn/sample.c "
        "-o build/GALE01/src/melee/mn'\n",
    )
    remote_dir, inspector = _install_local_ssh(
        fake_bin,
        tmp_path,
        real_git_source=repo,
    )
    _header_observing_inspector(inspector)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_REMOTE_BIN": str(inspector.parent),
            "MWCC_INSPECT_HOST": "fake-host",
            "MWCC_INSPECT_FRESH_BASH": "/bin/bash",
            "MWCC_INSPECT_REMOTE_BASH": "bash",
            "MWCC_INSPECT_REMOTE_DIR": str(remote_dir),
            "MWCC_INSPECT_CLI": str(inspector),
            "MWCC_INSPECT_REMOTE_REF": head,
        }
    )
    return SimpleNamespace(
        repo=repo,
        script=script,
        tu_dir=tu_dir,
        source=source,
        header=header,
        head=head,
        bundle=bundle,
        candidate=candidate,
        fake_bin=fake_bin,
        remote_dir=remote_dir,
        inspector=inspector,
        env=env,
    )


def _run_private_context(
    fixture: SimpleNamespace,
    tmp_path: Path,
    invocation_id: str,
    *,
    source: Path | None = None,
    deadline: str = "5",
    env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    output = tmp_path / f"{invocation_id}.txt"
    proc = subprocess.run(
        [
            str(fixture.script),
            "--invocation-id",
            invocation_id,
            "--deadline-seconds",
            deadline,
            "--function",
            "fn_test",
            "--output",
            str(output),
            str(source or fixture.candidate),
        ],
        cwd=fixture.repo,
        env=env or fixture.env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc, output


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
        "#!/bin/sh\necho 'wrapper mwcceppc.exe -c src/melee/pl/plbonuslib.c -o "
        "build/GALE01/src/melee/pl'\n",
    )
    remote_dir, inspector = _install_local_ssh(fake_bin, tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_INSPECTOR_OUTPUT": "FUNCTION: fn_test\nCompilation finished.\n",
            "FAKE_REMOTE_BIN": str(inspector.parent),
            "MWCC_INSPECT_HOST": "fake-host",
            "MWCC_INSPECT_FRESH_BASH": "/bin/bash",
            "MWCC_INSPECT_REMOTE_BASH": "bash",
            "MWCC_INSPECT_REMOTE_DIR": str(remote_dir),
            "MWCC_INSPECT_CLI": str(inspector),
            "MWCC_INSPECT_REMOTE_REF": "HEAD",
        }
    )
    return repo, script, candidate, env, remote_dir


def test_stale_remote_header_is_ignored_by_exact_private_context(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workflow = repo / "tools" / "workflow"
    workflow.mkdir(parents=True)
    script = _copy_inspect_workflow(workflow)
    source_dir = repo / "src" / "melee" / "mn"
    source_dir.mkdir(parents=True)
    (source_dir / "sample.c").write_text("void fn_test(void) {}\n", encoding="utf-8")
    local_header = source_dir / "inlines.h"
    local_header.write_text('#include "lb/lbaudio_ax.h"\n', encoding="utf-8")
    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/mn/sample",'
        '"functions":[{"name":"fn_test"}]}]}',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    head = _commit(repo, "base")

    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_test(void) {}\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "ninja",
        "#!/bin/sh\necho 'wrapper mwcceppc.exe -i src -i src/melee "
        "-c src/melee/mn/sample.c -o build/GALE01/src/melee/mn'\n",
    )
    remote_dir, inspector = _install_local_ssh(
        fake_bin,
        tmp_path,
        real_git_source=repo,
    )
    _header_observing_inspector(inspector)
    remote_header = remote_dir / "src" / "melee" / "mn" / "inlines.h"
    remote_header.write_text('#include "lb/lb_00F9.h"\n', encoding="utf-8")
    remote_head_before = _head_commit(remote_dir)
    remote_status_before = _status(remote_dir)
    output = tmp_path / "inspect.txt"
    record = tmp_path / "record.json"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_INSPECTOR_RECORD": str(record),
            "FAKE_REMOTE_BIN": str(inspector.parent),
            "MWCC_INSPECT_HOST": "fake-host",
            "MWCC_INSPECT_FRESH_BASH": "/bin/bash",
            "MWCC_INSPECT_REMOTE_BASH": "bash",
            "MWCC_INSPECT_REMOTE_DIR": str(remote_dir),
            "MWCC_INSPECT_CLI": str(inspector),
            "MWCC_INSPECT_REMOTE_REF": head,
        }
    )

    proc = subprocess.run(
        [
            str(script),
            "--invocation-id",
            "stale-remote-header",
            "--deadline-seconds",
            "5",
            "--function",
            "fn_test",
            "--output",
            str(output),
            str(candidate),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    digest = hashlib.sha256(local_header.read_bytes()).hexdigest()
    assert f"HEADER_SHA256={digest}" in output.read_text(encoding="utf-8")
    assert remote_header.read_text(encoding="utf-8") == '#include "lb/lb_00F9.h"\n'
    assert _head_commit(remote_dir) == remote_head_before
    assert _status(remote_dir) == remote_status_before
    observed = json.loads(record.read_text(encoding="utf-8"))
    private_repo = remote_dir / "build" / "mwcc-inspect-jobs" / "stale-remote-header" / "repo"
    assert Path(observed["cwd"]) == private_repo
    assert Path(observed["source"]).is_relative_to(private_repo)


def test_dirty_active_tu_header_overlays_private_context(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path)
    fixture.header.write_text("#define LOCAL_WORKTREE_HEADER 1\n", encoding="utf-8")
    remote_header = fixture.remote_dir / "src/melee/mn/inlines.h"
    remote_header.write_text("#define REMOTE_STALE_HEADER 1\n", encoding="utf-8")
    remote_status = _status(fixture.remote_dir)

    proc, output = _run_private_context(fixture, tmp_path, "local-tu-header")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    digest = hashlib.sha256(fixture.header.read_bytes()).hexdigest()
    assert f"HEADER_SHA256={digest}" in output.read_text(encoding="utf-8")
    assert _status(fixture.remote_dir) == remote_status


def test_overlay_archive_restores_private_file_modes(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path)
    record = tmp_path / "archive-mode-record.json"
    fixture.env["FAKE_INSPECTOR_RECORD"] = str(record)

    proc, _output = _run_private_context(fixture, tmp_path, "archive-file-modes")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    observed = json.loads(record.read_text(encoding="utf-8"))
    assert observed["source_mode"] == 0o600
    assert observed["header_mode"] == 0o600


def test_overlay_archive_is_plain_ustar_without_copyfile_metadata(
    tmp_path: Path,
) -> None:
    fixture = _private_context_fixture(tmp_path)
    record = tmp_path / "local-tar-record.txt"
    fixture.env["FAKE_LOCAL_TAR_RECORD"] = str(record)
    _write_executable(
        fixture.fake_bin / "tar",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = --format=ustar ]; then\n"
        "  printf 'COPYFILE_DISABLE=%s\\n' \"${COPYFILE_DISABLE:-}\" > "
        "\"${FAKE_LOCAL_TAR_RECORD}\"\n"
        "  printf '%s\\n' \"$@\" >> \"${FAKE_LOCAL_TAR_RECORD}\"\n"
        "fi\n"
        "exec /usr/bin/tar \"$@\"\n",
    )

    proc, _output = _run_private_context(fixture, tmp_path, "archive-ustar")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    recorded = record.read_text(encoding="utf-8").splitlines()
    assert recorded[:3] == ["COPYFILE_DISABLE=1", "--format=ustar", "-cf"]


def test_candidate_header_wins_over_active_tu_and_exact_ref(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path, header_text="#define BASE_HEADER 1\n")
    fixture.header.write_text("#define LOCAL_TU 1\n", encoding="utf-8")
    candidate_header = fixture.bundle / "inlines.h"
    candidate_header.write_text("#define CANDIDATE_BUNDLE 1\n", encoding="utf-8")

    proc, output = _run_private_context(fixture, tmp_path, "header-precedence")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "HEADER_TEXT=#define CANDIDATE_BUNDLE 1" in output.read_text(encoding="utf-8")


def test_candidate_header_case_collision_is_rejected_before_ssh(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path)
    (fixture.bundle / "INLINES.H").write_text("#define COLLISION 1\n", encoding="utf-8")
    log_dir = tmp_path / "ssh-log"
    log_dir.mkdir()
    fixture.env["FAKE_SSH_LOG"] = str(log_dir)

    proc, output = _run_private_context(fixture, tmp_path, "case-collision")

    assert proc.returncode == 66
    assert "case-colliding header basename" in proc.stderr
    assert not output.exists()
    assert not list(log_dir.iterdir())


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("candidate-source-symlink", "source must be a regular non-symlink file"),
        ("tu-header-symlink", "unsafe TU header"),
        ("candidate-header-symlink", "unsafe candidate header"),
        ("header-name-with-newline", "unsafe header basename"),
    ],
)
def test_unsafe_local_inputs_are_rejected_before_ssh(
    tmp_path: Path,
    case: str,
    expected: str,
) -> None:
    fixture = _private_context_fixture(tmp_path)
    source = fixture.candidate
    if case == "candidate-source-symlink":
        source = fixture.bundle / "source-link.c"
        source.symlink_to(fixture.candidate)
    elif case == "tu-header-symlink":
        target = tmp_path / "tu-target.h"
        target.write_text("#define TARGET 1\n", encoding="utf-8")
        fixture.header.unlink()
        fixture.header.symlink_to(target)
    elif case == "candidate-header-symlink":
        target = tmp_path / "candidate-target.h"
        target.write_text("#define TARGET 1\n", encoding="utf-8")
        (fixture.bundle / "extra.h").symlink_to(target)
    else:
        (fixture.bundle / "bad\nname.h").write_text("#define BAD 1\n", encoding="utf-8")
    log_dir = tmp_path / "ssh-log"
    log_dir.mkdir()
    fixture.env["FAKE_SSH_LOG"] = str(log_dir)

    proc, output = _run_private_context(
        fixture,
        tmp_path,
        case,
        source=source,
    )

    assert proc.returncode in (64, 66)
    assert expected in proc.stderr
    assert not output.exists()
    assert not list(log_dir.iterdir())
    assert not (fixture.remote_dir / "build/mwcc-inspect-jobs").exists()


@pytest.mark.parametrize(
    ("compile_args", "output_arg", "expected"),
    [
        ("-i ../escape", "build/GALE01/sample.o", "unsafe relative compiler include"),
        ("-i src/../../escape", "build/GALE01/sample.o", "unsafe relative compiler include"),
        ("-i src", "../escape", "unsafe relative compiler output"),
        ("-i src", "build/GALE01/sample.o", "-c must be immediately followed"),
    ],
)
def test_unsafe_or_mismatched_compiler_argv_is_rejected_before_ssh(
    tmp_path: Path,
    compile_args: str,
    output_arg: str,
    expected: str,
) -> None:
    fixture = _private_context_fixture(tmp_path)
    if expected.startswith("-c must"):
        command = (
            f"wrapper mwcceppc.exe {compile_args} -c src/melee/mn/other.c "
            f"-o {output_arg}"
        )
    else:
        command = (
            f"wrapper mwcceppc.exe {compile_args} -c src/melee/mn/sample.c "
            f"-o {output_arg}"
        )
    _write_executable(
        fixture.fake_bin / "ninja",
        f"#!/usr/bin/env python3\nprint({command!r})\n",
    )
    log_dir = tmp_path / "ssh-log"
    log_dir.mkdir()
    fixture.env["FAKE_SSH_LOG"] = str(log_dir)

    proc, output = _run_private_context(fixture, tmp_path, "bad-argv")

    assert proc.returncode == 64
    assert expected in proc.stderr
    assert not output.exists()
    assert not list(log_dir.iterdir())


def test_compiler_argv_is_quoted_without_shell_reinterpretation(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path)
    sentinel = tmp_path / "argv-injection"
    unusual = f"-DVALUE=a b;$(touch {sentinel})"
    command = (
        "wrapper mwcceppc.exe -i src -i /opt/external "
        f"{shlex.quote(unusual)} -c src/melee/mn/sample.c "
        "-o build/GALE01/src/melee/mn"
    )
    _write_executable(
        fixture.fake_bin / "ninja",
        f"#!/usr/bin/env python3\nprint({command!r})\n",
    )
    record = tmp_path / "argv-record.json"
    fixture.env["FAKE_INSPECTOR_RECORD"] = str(record)

    proc, _output = _run_private_context(fixture, tmp_path, "quoted-argv")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    observed = json.loads(record.read_text(encoding="utf-8"))
    assert unusual in observed["argv"]
    assert not sentinel.exists()
    private_repo = fixture.remote_dir / "build/mwcc-inspect-jobs/quoted-argv/repo"
    assert Path(observed["cwd"]) == private_repo
    source = Path(observed["argv"][observed["argv"].index("-c") + 1])
    assert source.is_relative_to(private_repo)
    for index, arg in enumerate(observed["argv"]):
        if arg == "-i" and not Path(observed["argv"][index + 1]).is_absolute():
            raise AssertionError("relative include escaped private checkout")
    output_arg = Path(observed["argv"][observed["argv"].index("-o") + 1])
    assert output_arg.is_relative_to(private_repo)


def test_inspector_uses_fresh_child_bash_with_exact_argv(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path)
    inspector_record = tmp_path / "inspector-record.json"
    ssh_log = tmp_path / "ssh-log"
    ssh_log.mkdir()
    fixture.env.update(
        {
            "FAKE_INSPECTOR_RECORD": str(inspector_record),
            "FAKE_SSH_LOG": str(ssh_log),
        }
    )

    proc, _output = _run_private_context(fixture, tmp_path, "fresh-bash-handoff")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    observed = json.loads(inspector_record.read_text(encoding="utf-8"))
    assert observed["argv"][0].endswith("/build/compilers/GC/1.2.5n/mwcceppc.exe")
    launch = next(
        path.read_text(encoding="utf-8")
        for path in ssh_log.glob("*.stdin")
        if "stage=job-init" in path.read_text(encoding="utf-8")
    )
    assert "unset BASH_ENV ENV" in launch
    assert "'/bin/bash' '--noprofile' '--norc' '-c' 'exec \"$@\"'" in launch
    assert "'mwcc-inspect-fresh'" in launch


def test_fresh_child_bash_propagates_inspector_failure(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path)
    _write_executable(fixture.inspector, "#!/bin/sh\nexit 42\n")

    proc, output = _run_private_context(fixture, tmp_path, "fresh-bash-failure")

    assert proc.returncode == 1
    assert not output.exists()
    job = fixture.remote_dir / "build/mwcc-inspect-jobs/fresh-bash-failure"
    terminal = _terminal(job)
    assert terminal["status"] == "failed"
    assert terminal["reason"] == "inspector-exit-42"
    assert terminal["child_reaped"] == "true"


@pytest.mark.parametrize("fresh_bash", ["bash", "../bin/bash", "/bin/bash\nextra", "/bin/bash arg"])
def test_unsafe_fresh_bash_path_is_rejected_before_ssh(
    tmp_path: Path,
    fresh_bash: str,
) -> None:
    fixture = _private_context_fixture(tmp_path)
    ssh_log = tmp_path / "ssh-log"
    ssh_log.mkdir()
    fixture.env.update(
        {
            "FAKE_SSH_LOG": str(ssh_log),
            "MWCC_INSPECT_FRESH_BASH": fresh_bash,
        }
    )

    proc, output = _run_private_context(fixture, tmp_path, "unsafe-fresh-bash")

    assert proc.returncode == 64
    assert "MWCC_INSPECT_FRESH_BASH must be a safe absolute path" in proc.stderr
    assert not output.exists()
    assert not list(ssh_log.iterdir())


@pytest.mark.parametrize("termination", ["deadline", "cancel"])
def test_fresh_child_bash_is_recursively_reaped(
    tmp_path: Path,
    termination: str,
) -> None:
    fixture = _private_context_fixture(tmp_path)
    invocation = f"fresh-bash-{termination}"
    inner_pid = tmp_path / f"{invocation}.pid"
    outer_pid_file = tmp_path / f"{invocation}.outer-pid"
    fixture.env.update(
        {
            "FAKE_FRESH_CHILD_PID": str(inner_pid),
            "FAKE_FRESH_OUTER_PID": str(outer_pid_file),
        }
    )
    _write_executable(
        fixture.inspector.parent / "native-pid",
        "#!/bin/sh\n"
        "printf '%s\\n' \"$1\" > \"${FAKE_FRESH_OUTER_PID}\"\n"
        "printf '%s\\n' \"$1\"\n",
    )
    _write_executable(
        fixture.inspector,
        "#!/usr/bin/env python3\n"
        "import os, time\n"
        "from pathlib import Path\n"
        "Path(os.environ['FAKE_FRESH_CHILD_PID']).write_text(str(os.getpid()))\n"
        "while True:\n"
        "    time.sleep(0.05)\n",
    )
    output = tmp_path / f"{invocation}.txt"
    args = [
        str(fixture.script),
        "--invocation-id",
        invocation,
        "--deadline-seconds",
        "1" if termination == "deadline" else "5",
        "--function",
        "fn_test",
        "--output",
        str(output),
        str(fixture.candidate),
    ]
    proc = subprocess.Popen(
        args,
        cwd=fixture.repo,
        env=fixture.env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_for_path(inner_pid)
    job = fixture.remote_dir / f"build/mwcc-inspect-jobs/{invocation}"
    _wait_for_path(outer_pid_file)
    outer_pid = int(outer_pid_file.read_text(encoding="utf-8"))
    recorded_inner_pid = int(inner_pid.read_text(encoding="utf-8"))
    assert recorded_inner_pid != outer_pid
    if termination == "cancel":
        cancelled = subprocess.run(
            [str(fixture.script), "--cancel", invocation, "--cleanup-timeout", "2"],
            cwd=fixture.repo,
            env=fixture.env,
            capture_output=True,
            text=True,
            timeout=4,
        )
        assert cancelled.returncode == 0, cancelled.stdout + cancelled.stderr
    stdout, stderr = proc.communicate(timeout=4)

    assert proc.returncode == 124, stdout + stderr
    terminal = _terminal(job)
    assert terminal["status"] == ("timeout" if termination == "deadline" else "cancelled")
    assert terminal["child_reaped"] == "true"
    _wait_for_pid_exit(outer_pid)
    _wait_for_pid_exit(recorded_inner_pid)
    assert not output.exists()


def test_large_candidate_transport_has_bounded_payload_lines(tmp_path: Path) -> None:
    repo, script, candidate, env, _remote_dir = _wrapper_fixture(tmp_path)
    candidate.write_text("void fn_test(void) {\n" + ("  /* retained source */\n" * 10000) + "}\n")
    log_dir = tmp_path / "ssh-log"
    log_dir.mkdir()
    env["FAKE_SSH_LOG"] = str(log_dir)
    output = tmp_path / "large-candidate.txt"

    proc = subprocess.run(
        [
            str(script),
            "--invocation-id",
            "large-candidate",
            "--function",
            "fn_test",
            "--output",
            str(output),
            str(candidate),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=12,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    launch_payload = next(
        path.read_text(encoding="utf-8")
        for path in log_dir.glob("*.stdin")
        if "stage=job-init" in path.read_text(encoding="utf-8")
    )
    assert max(map(len, launch_payload.splitlines())) <= 4096
    assert "MWCC_INSPECT_OVERLAY_" in launch_payload
    assert output.read_text(encoding="utf-8") == "FUNCTION: fn_test\nCompilation finished.\n"


def test_compound_launch_stdin_is_fully_materialized_before_ssh(tmp_path: Path) -> None:
    repo, script, candidate, env, _remote_dir = _wrapper_fixture(tmp_path)
    log_dir = tmp_path / "ssh-log"
    log_dir.mkdir()
    local_tmp = tmp_path / "local-tmp"
    local_tmp.mkdir()
    env["FAKE_SSH_LOG"] = str(log_dir)
    env["FAKE_REQUIRE_STAGED_LAUNCH"] = "1"
    env["TMPDIR"] = str(local_tmp)
    output = tmp_path / "staged-launch.txt"

    proc = subprocess.run(
        [
            str(script),
            "--invocation-id",
            "staged-launch",
            "--function",
            "fn_test",
            "--output",
            str(output),
            str(candidate),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=12,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    launch_index = next(
        path.stem
        for path in log_dir.glob("*.stdin")
        if "stage=job-init" in path.read_text(encoding="utf-8")
    )
    assert (log_dir / f"{launch_index}.stdin-kind").read_text(encoding="utf-8") == "regular"
    assert output.read_text(encoding="utf-8") == "FUNCTION: fn_test\nCompilation finished.\n"
    assert not list(local_tmp.glob("mwcc-inspect-payload.*"))


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            "wrapper mwcceppc.exe -i src -c -o build/GALE01/sample.o "
            "src/melee/mn/sample.c",
            "-c must be immediately followed",
        ),
        (
            "wrapper mwcceppc.exe -i src -c src/melee/mn/sample.c "
            "src/melee/mn/other.c -o build/GALE01/sample.o",
            "unexpected additional source operand",
        ),
        (
            "wrapper mwcceppc.exe -i src src/melee/mn/other.c "
            "-c src/melee/mn/sample.c -o build/GALE01/sample.o",
            "unexpected additional source operand",
        ),
    ],
)
def test_compiler_argv_requires_one_adjacent_source_binding(
    tmp_path: Path,
    command: str,
    expected: str,
) -> None:
    fixture = _private_context_fixture(tmp_path)
    _write_executable(
        fixture.fake_bin / "ninja",
        f"#!/usr/bin/env python3\nprint({command!r})\n",
    )
    log_dir = tmp_path / "ssh-log"
    log_dir.mkdir()
    fixture.env["FAKE_SSH_LOG"] = str(log_dir)

    proc, output = _run_private_context(fixture, tmp_path, "strict-source-binding")

    assert proc.returncode == 64
    assert expected in proc.stderr
    assert not output.exists()
    assert not list(log_dir.iterdir())


def test_overlay_hash_corruption_fails_closed_under_supervisor(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path)
    inspector_record = tmp_path / "inspector-record.json"
    fixture.env["FAKE_INSPECTOR_RECORD"] = str(inspector_record)
    corrupting_base64 = fixture.inspector.parent / "base64"
    _write_executable(
        corrupting_base64,
        textwrap.dedent("""\
            #!/usr/bin/env python3
            import base64
            import sys

            encoded = sys.stdin.buffer.read()
            decoded = base64.b64decode(encoded)
            if len(decoded) > 262 and decoded[257:262] == b"ustar":
                decoded = bytes([decoded[0] ^ 1]) + decoded[1:]
            sys.stdout.buffer.write(decoded)
        """),
    )

    proc, output = _run_private_context(fixture, tmp_path, "upload-hash")

    assert proc.returncode == 125
    assert "overlay archive SHA-256 mismatch" in proc.stderr
    assert not output.exists()
    assert not inspector_record.exists()
    job = fixture.remote_dir / "build/mwcc-inspect-jobs/upload-hash"
    assert _terminal(job)["child_reaped"] == "true"
    assert _terminal(job)["status"] == "failed"
    cancelled = subprocess.run(
        [str(fixture.script), "--cancel", "upload-hash", "--cleanup-timeout", "1"],
        cwd=fixture.repo,
        env=fixture.env,
        capture_output=True,
        text=True,
        timeout=3,
    )
    assert cancelled.returncode == 0, cancelled.stdout + cancelled.stderr


@pytest.mark.parametrize(
    "corruption",
    ["decode", "member-list", "member-type", "extract", "file-hash"],
)
def test_overlay_archive_validation_fails_closed_before_inspector(
    tmp_path: Path,
    corruption: str,
) -> None:
    fixture = _private_context_fixture(tmp_path)
    inspector_record = tmp_path / "inspector-record.json"
    fixture.env["FAKE_INSPECTOR_RECORD"] = str(inspector_record)
    if corruption == "decode":
        _write_executable(
            fixture.inspector.parent / "base64",
            "#!/bin/sh\n"
            "if [ \"${MWCC_INSPECT_OVERLAY_DECODE:-}\" = 1 ]; then exit 1; fi\n"
            "exec /usr/bin/base64 \"$@\"\n",
        )
        expected = "overlay archive decode failed"
    elif corruption == "file-hash":
        _write_executable(
            fixture.inspector.parent / "tar",
            "#!/bin/sh\n"
            "if [ \"${1:-}\" = -xf ]; then\n"
            "  /usr/bin/tar \"$@\" || exit $?\n"
            "  destination=\n"
            "  while [ \"$#\" -gt 0 ]; do\n"
            "    if [ \"$1\" = -C ]; then shift; destination=$1; fi\n"
            "    shift\n"
            "  done\n"
            "  printf '\\nCORRUPTED\\n' >> \"${destination}/src/melee/mn/inlines.h\"\n"
            "  exit 0\n"
            "fi\n"
            "exec /usr/bin/tar \"$@\"\n",
        )
        expected = "overlay file SHA-256 mismatch"
    elif corruption in {"member-list", "member-type"}:
        injected = (
            "../sentinel"
            if corruption == "member-list"
            else "lrwxrwxrwx  0 owner group 0 Jan  1 00:00 src/melee/mn/inlines.h"
        )
        option = "-tf" if corruption == "member-list" else "-tvf"
        _write_executable(
            fixture.inspector.parent / "tar",
            "#!/bin/sh\n"
            f"if [ \"${{1:-}}\" = {shlex.quote(option)} ]; then\n"
            f"  printf '%s\\n' {shlex.quote(injected)}\n"
            "  exit 0\n"
            "fi\n"
            "exec /usr/bin/tar \"$@\"\n",
        )
        expected = (
            "overlay archive member mismatch"
            if corruption == "member-list"
            else "overlay archive contains non-regular member"
        )
    else:
        _write_executable(
            fixture.inspector.parent / "tar",
            "#!/bin/sh\n"
            "if [ \"${1:-}\" = -xf ]; then exit 1; fi\n"
            "exec /usr/bin/tar \"$@\"\n",
        )
        expected = "overlay archive extraction failed"

    proc, output = _run_private_context(
        fixture,
        tmp_path,
        f"overlay-archive-{corruption}",
    )

    assert proc.returncode == 125
    assert expected in proc.stderr
    assert not output.exists()
    assert not inspector_record.exists()
    job = fixture.remote_dir / f"build/mwcc-inspect-jobs/overlay-archive-{corruption}"
    terminal = _terminal(job)
    assert terminal["status"] == "failed"
    assert terminal["child_reaped"] == "true"
    assert not (job / "sentinel").exists()
    for retained in [
        *job.glob("overlays.*"),
        *job.glob("overlay-sha256.manifest"),
    ]:
        assert retained.is_file()
        assert not retained.is_symlink()


def test_overlay_archive_extraction_obeys_supervisor_deadline(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path)
    hang_pid = tmp_path / "archive-extract.pid"
    inspector_record = tmp_path / "inspector-record.json"
    fixture.env.update(
        {
            "FAKE_ARCHIVE_HANG_PID": str(hang_pid),
            "FAKE_INSPECTOR_RECORD": str(inspector_record),
        }
    )
    _write_executable(
        fixture.inspector.parent / "tar",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = -xf ]; then\n"
        "  printf '%s\\n' \"$$\" > \"${FAKE_ARCHIVE_HANG_PID}\"\n"
        "  while :; do sleep 0.05; done\n"
        "fi\n"
        "exec /usr/bin/tar \"$@\"\n",
    )
    started = time.monotonic()

    proc, output = _run_private_context(
        fixture,
        tmp_path,
        "overlay-archive-deadline",
        deadline="1",
    )

    assert proc.returncode == 124, proc.stdout + proc.stderr
    assert time.monotonic() - started < 4
    assert hang_pid.exists()
    job = fixture.remote_dir / "build/mwcc-inspect-jobs/overlay-archive-deadline"
    terminal = _terminal(job)
    assert terminal["status"] == "timeout"
    assert terminal["child_reaped"] == "true"
    _wait_for_pid_exit(int(hang_pid.read_text(encoding="utf-8")))
    assert not output.exists()
    assert not inspector_record.exists()


@pytest.mark.parametrize("escape_kind", ["ancestor-symlink", "destination-symlink"])
def test_private_exact_ref_symlink_escape_is_rejected(
    tmp_path: Path,
    escape_kind: str,
) -> None:
    fixture = _private_context_fixture(tmp_path)
    sentinel = tmp_path / "external-sentinel"
    sentinel.mkdir()
    marker = sentinel / "marker"
    marker.write_text("unchanged\n", encoding="utf-8")
    if escape_kind == "ancestor-symlink":
        shutil.rmtree(fixture.tu_dir)
        fixture.tu_dir.symlink_to(sentinel, target_is_directory=True)
    else:
        fixture.header.unlink()
        fixture.header.symlink_to(sentinel, target_is_directory=True)
    malicious_ref = _commit(fixture.repo, escape_kind)
    if escape_kind == "ancestor-symlink":
        fixture.tu_dir.unlink()
        fixture.tu_dir.mkdir()
        fixture.source.write_text("void fn_test(void) {}\n", encoding="utf-8")
        fixture.header.write_text("#define SAFE_LOCAL 1\n", encoding="utf-8")
    else:
        fixture.header.unlink()
        fixture.header.write_text("#define SAFE_LOCAL 1\n", encoding="utf-8")
    fixture.env["MWCC_INSPECT_REMOTE_REF"] = malicious_ref

    proc, output = _run_private_context(
        fixture,
        tmp_path,
        f"private-path-{escape_kind}",
    )

    assert proc.returncode == 125
    assert "unsafe private repository path" in proc.stderr
    assert marker.read_text(encoding="utf-8") == "unchanged\n"
    assert not output.exists()
    job = fixture.remote_dir / f"build/mwcc-inspect-jobs/private-path-{escape_kind}"
    terminal = _terminal(job)
    assert terminal["status"] == "failed"
    assert terminal["child_reaped"] == "true"


def test_injected_windows_reparse_ancestor_is_rejected(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path)
    checker = fixture.inspector.parent / "reparse-check"
    _write_executable(
        checker,
        "#!/bin/sh\n"
        "case \"$1\" in */repo/src/melee) exit 0;; *) exit 1;; esac\n",
    )
    fixture.env["MWCC_INSPECT_REPARSE_CHECK_CMD"] = str(checker)

    proc, output = _run_private_context(fixture, tmp_path, "private-path-reparse")

    assert proc.returncode == 125
    assert "unsafe private repository path" in proc.stderr
    assert not output.exists()
    job = fixture.remote_dir / "build/mwcc-inspect-jobs/private-path-reparse"
    terminal = _terminal(job)
    assert terminal["status"] == "failed"
    assert terminal["child_reaped"] == "true"


def _enable_fake_windows_reparse_batch(
    fixture: SimpleNamespace,
    tmp_path: Path,
    *,
    mode: str = "valid",
) -> SimpleNamespace:
    acl_init = fixture.inspector.parent / "acl-init"
    security = fixture.inspector.parent / "security-check"
    cygpath = fixture.inspector.parent / "cygpath"
    powershell = fixture.inspector.parent / "powershell.exe"
    call_count = tmp_path / "reparse-call-count"
    manifests = tmp_path / "reparse-manifests"
    call_count.write_text("0\n", encoding="utf-8")
    manifests.mkdir()
    _write_executable(
        acl_init,
        "#!/bin/sh\nmkdir -m 700 \"$1\"\n"
        "printf 'MWCC_INSPECT_WINDOWS_ACL_READY:S-1-5-21-1001\\n'\n",
    )
    _write_executable(
        security,
        "#!/bin/sh\nprintf 'MWCC_INSPECT_WINDOWS_SECURITY_OK:S-1-5-21-1001\\n'\n",
    )
    _write_executable(cygpath, "#!/bin/sh\nshift\nprintf '%s\\n' \"$@\"\n")
    _write_executable(
        powershell,
        textwrap.dedent("""\
            #!/bin/sh
            count="$(cat "${FAKE_REPARSE_CALL_COUNT}")"
            count=$((count + 1))
            printf '%s\n' "${count}" > "${FAKE_REPARSE_CALL_COUNT}"
            if [ -n "${MWCC_INSPECT_REPARSE_MANIFEST:-}" ]; then
              phase="${MWCC_INSPECT_REPARSE_PHASE}"
              cp "${MWCC_INSPECT_REPARSE_MANIFEST}" \
                "${FAKE_REPARSE_MANIFEST_DIR}/${phase}.tsv"
              actual="$(wc -l < "${MWCC_INSPECT_REPARSE_MANIFEST}" | tr -d ' ')"
              [ "${actual}" = "${MWCC_INSPECT_REPARSE_EXPECTED_COUNT}" ] || exit 97
              actual_sha="$(shasum -a 256 "${MWCC_INSPECT_REPARSE_MANIFEST}" | awk '{print $1}')"
              [ "${actual_sha}" = "${MWCC_INSPECT_REPARSE_MANIFEST_SHA}" ] || exit 98
              awk -F '\t' '{ key = tolower($2); if (seen[key]++) exit 1 }' \
                "${MWCC_INSPECT_REPARSE_MANIFEST}" || exit 95
              case "${FAKE_REPARSE_MODE}:${phase}" in
                empty:*) exit 0 ;;
                hang:PRE)
                  printf '%s\n' "$$" > "${FAKE_REPARSE_HANG_PID}"
                  while :; do sleep 0.05; done
                  ;;
                nonzero:*) exit 99 ;;
                pre-reparse:PRE)
                  grep -F "$(printf 'absent-or-file\\t%s' "${FAKE_REPARSE_TARGET}")" \
                    "${MWCC_INSPECT_REPARSE_MANIFEST}" >/dev/null || exit 96
                  exit 99
                  ;;
                post-reparse:POST)
                  grep -F "$(printf 'required-file\\t%s' "${FAKE_REPARSE_TARGET}")" \
                    "${MWCC_INSPECT_REPARSE_MANIFEST}" >/dev/null || exit 96
                  exit 99
                  ;;
              esac
              receipt_phase="${phase}"
              receipt_count="${MWCC_INSPECT_REPARSE_EXPECTED_COUNT}"
              receipt_sha="${MWCC_INSPECT_REPARSE_MANIFEST_SHA}"
              case "${FAKE_REPARSE_MODE}" in
                wrong-phase) receipt_phase="WRONG" ;;
                wrong-count) receipt_count=$((receipt_count + 1)) ;;
                wrong-hash) receipt_sha="0000000000000000000000000000000000000000000000000000000000000000" ;;
              esac
              printf 'MWCC_INSPECT_REPARSE_BATCH_OK:%s:%s:%s\n' \
                "${receipt_phase}" "${receipt_count}" "${receipt_sha}"
              exit 0
            fi
            [ "${count}" -le 2 ] && exit 1
            exit 99
        """),
    )
    fixture.env.update(
        {
            "MWCC_INSPECT_PLATFORM": "MSYS_NT-10.0",
            "MWCC_INSPECT_WINDOWS_ACL_INIT_CMD": str(acl_init),
            "MWCC_INSPECT_WINDOWS_SECURITY_CMD": str(security),
            "MWCC_INSPECT_CYGPATH": str(cygpath),
            "MWCC_INSPECT_POWERSHELL": str(powershell),
            "FAKE_REPARSE_CALL_COUNT": str(call_count),
            "FAKE_REPARSE_MANIFEST_DIR": str(manifests),
            "FAKE_REPARSE_MODE": mode,
            "FAKE_REPARSE_TARGET": "src/melee/mn/inlines.h",
            "FAKE_REPARSE_HANG_PID": str(tmp_path / "reparse-hang.pid"),
        }
    )
    assert "MWCC_INSPECT_REPARSE_CHECK_CMD" not in fixture.env
    return SimpleNamespace(
        call_count=call_count,
        manifests=manifests,
        hang_pid=tmp_path / "reparse-hang.pid",
    )


def _manifest_entries(path: Path) -> set[tuple[str, str]]:
    return {
        tuple(line.split("\t", 1))
        for line in path.read_text(encoding="ascii").splitlines()
    }


def _count_remote_overlay_tools(
    fixture: SimpleNamespace,
    tmp_path: Path,
) -> Path:
    log = tmp_path / "remote-overlay-tools.log"
    for name in ("base64", "sha256sum", "tar"):
        executable = shutil.which(name)
        assert executable is not None, f"required test utility is missing: {name}"
        _write_executable(
            fixture.inspector.parent / name,
            "#!/bin/sh\n"
            f"printf '%s\\n' {shlex.quote(name)} >> \"${{FAKE_REMOTE_TOOL_LOG}}\"\n"
            f"exec {shlex.quote(executable)} \"$@\"\n",
        )
    fixture.env["FAKE_REMOTE_TOOL_LOG"] = str(log)
    return log


def test_windows_many_overlays_use_two_complete_reparse_batches(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path)
    for index in range(36):
        (fixture.bundle / f"overlay_{index:02d}.h").write_text(
            f"#define OVERLAY_{index:02d} {index}\n",
            encoding="utf-8",
        )
    fake = _enable_fake_windows_reparse_batch(fixture, tmp_path)
    tool_log = _count_remote_overlay_tools(fixture, tmp_path)

    proc, output = _run_private_context(
        fixture,
        tmp_path,
        "windows-many-overlays",
        deadline="10",
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert fake.call_count.read_text(encoding="utf-8").strip() == "2"
    assert Counter(tool_log.read_text(encoding="utf-8").splitlines()) == {
        # Includes three supervisor trust decodes and six artifact/trust hashes;
        # these totals are constant as the overlay count grows.
        "base64": 6,
        "sha256sum": 10,
        "tar": 3,
    }
    assert output.read_text(encoding="utf-8").endswith(
        "FUNCTION: fn_test\nCompilation finished.\n"
    )
    pre = _manifest_entries(fake.manifests / "PRE.tsv")
    post = _manifest_entries(fake.manifests / "POST.tsv")
    overlay_paths = {
        "src/melee/mn/inlines.h",
        "src/melee/mn/sample.c",
        *(f"src/melee/mn/overlay_{index:02d}.h" for index in range(36)),
    }
    for relative in overlay_paths:
        assert ("absent-or-file", relative) in pre
        assert ("required-file", relative) in post
        stage = f"{relative}.upload.windows-many-overlays"
        assert ("must-absent", stage) in pre
        assert ("must-absent", f"{stage}.base64") in pre
        assert ("must-absent", stage) in post
        assert ("must-absent", f"{stage}.base64") in post
    for required_dir in (".", "src", "src/melee", "src/melee/mn"):
        assert ("required-dir", required_dir) in pre
        assert ("required-dir", required_dir) in post
    for output_dir in (
        "build",
        "build/GALE01",
        "build/GALE01/src",
        "build/GALE01/src/melee",
        "build/GALE01/src/melee/mn",
    ):
        assert ("absent-or-dir", output_dir) in pre
        assert ("required-dir", output_dir) in post


@pytest.mark.parametrize(
    "mode",
    ["empty", "wrong-phase", "wrong-count", "wrong-hash", "nonzero"],
)
def test_windows_reparse_batch_requires_exact_receipt(
    tmp_path: Path,
    mode: str,
) -> None:
    fixture = _private_context_fixture(tmp_path)
    fake = _enable_fake_windows_reparse_batch(fixture, tmp_path, mode=mode)

    proc, output = _run_private_context(
        fixture,
        tmp_path,
        f"windows-receipt-{mode}",
    )

    assert proc.returncode == 125
    assert "reparse batch failed" in proc.stderr
    assert not output.exists()
    assert int(fake.call_count.read_text(encoding="utf-8")) <= 2


@pytest.mark.parametrize(
    ("mode", "expected_calls"),
    [("pre-reparse", 1), ("post-reparse", 2)],
)
def test_windows_reparse_batch_rejects_pre_and_post_injections(
    tmp_path: Path,
    mode: str,
    expected_calls: int,
) -> None:
    fixture = _private_context_fixture(tmp_path)
    dirty_header = "#define DIRTY_LOCAL_HEADER 1\n"
    fixture.header.write_text(dirty_header, encoding="utf-8")
    inspector_record = tmp_path / "inspector-record.json"
    fixture.env["FAKE_INSPECTOR_RECORD"] = str(inspector_record)
    fake = _enable_fake_windows_reparse_batch(fixture, tmp_path, mode=mode)

    proc, output = _run_private_context(
        fixture,
        tmp_path,
        f"windows-{mode}",
    )

    assert proc.returncode == 125
    assert "reparse batch failed" in proc.stderr
    assert not output.exists()
    assert int(fake.call_count.read_text(encoding="utf-8")) == expected_calls
    private_header = (
        fixture.remote_dir
        / "build/mwcc-inspect-jobs"
        / f"windows-{mode}"
        / "repo/src/melee/mn/inlines.h"
    )
    if mode == "pre-reparse":
        assert private_header.read_text(encoding="utf-8") == "#define BASE_HEADER 1\n"
    else:
        assert private_header.read_text(encoding="utf-8") == dirty_header
    assert not inspector_record.exists()


def test_windows_reparse_batch_obeys_supervisor_deadline(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path)
    fake = _enable_fake_windows_reparse_batch(fixture, tmp_path, mode="hang")
    started = time.monotonic()

    proc, output = _run_private_context(
        fixture,
        tmp_path,
        "windows-reparse-deadline",
        deadline="0.75",
    )

    assert proc.returncode == 124, proc.stdout + proc.stderr
    assert time.monotonic() - started < 4
    assert fake.hang_pid.exists()
    job = fixture.remote_dir / "build/mwcc-inspect-jobs/windows-reparse-deadline"
    terminal = _terminal(job)
    assert terminal["status"] == "timeout"
    assert terminal["child_reaped"] == "true"
    _wait_for_pid_exit(int(fake.hang_pid.read_text(encoding="utf-8")))
    assert not output.exists()


def test_windows_reparse_batch_rejects_case_insensitive_path_collisions(
    tmp_path: Path,
) -> None:
    fixture = _private_context_fixture(tmp_path)
    _write_executable(
        fixture.fake_bin / "ninja",
        "#!/bin/sh\n"
        "echo 'wrapper mwcceppc.exe -i SRC -c src/melee/mn/sample.c "
        "-o build/GALE01/src/melee/mn'\n",
    )
    fake = _enable_fake_windows_reparse_batch(fixture, tmp_path)

    proc, output = _run_private_context(
        fixture,
        tmp_path,
        "windows-case-collision",
    )

    assert proc.returncode == 125
    assert "reparse batch failed: PRE" in proc.stderr
    assert fake.call_count.read_text(encoding="utf-8").strip() == "1"
    assert not output.exists()


@pytest.mark.parametrize(
    "path_kind",
    [
        "include-symlink",
        "include-reparse",
        "output-symlink",
        "output-reparse",
        "output-file",
    ],
)
def test_compiler_paths_are_fully_contained_before_exec(
    tmp_path: Path,
    path_kind: str,
) -> None:
    fixture = _private_context_fixture(tmp_path)
    sentinel_dir = tmp_path / "compiler-path-sentinel"
    sentinel_dir.mkdir()
    sentinel = sentinel_dir / "marker"
    sentinel.write_text("unchanged\n", encoding="utf-8")
    if path_kind.startswith("include"):
        include_path = fixture.tu_dir / "include-root"
        if path_kind == "include-symlink":
            include_path.symlink_to(sentinel_dir, target_is_directory=True)
        else:
            include_path.mkdir()
            (include_path / "placeholder.h").write_text("#define PLACEHOLDER 1\n")
        exact_ref = _commit(fixture.repo, path_kind)
        command = (
            "wrapper mwcceppc.exe -i src/melee/mn/include-root "
            "-c src/melee/mn/sample.c -o build/GALE01/sample-output"
        )
        if path_kind == "include-reparse":
            checker = fixture.inspector.parent / "include-reparse-check"
            _write_executable(
                checker,
                "#!/bin/sh\ncase \"$1\" in */repo/src/melee/mn/include-root) exit 0;; *) exit 1;; esac\n",
            )
            fixture.env["MWCC_INSPECT_REPARSE_CHECK_CMD"] = str(checker)
    else:
        output_path = fixture.repo / "build/GALE01/compiler-output"
        if path_kind == "output-symlink":
            output_path.symlink_to(sentinel_dir, target_is_directory=True)
        elif path_kind == "output-reparse":
            output_path.mkdir()
            (output_path / "placeholder").write_text("tracked directory\n")
        else:
            output_path.write_text("tracked output\n")
        exact_ref = _commit(fixture.repo, path_kind)
        command = (
            "wrapper mwcceppc.exe -i src -c src/melee/mn/sample.c "
            "-o build/GALE01/compiler-output"
        )
        if path_kind == "output-reparse":
            checker = fixture.inspector.parent / "output-reparse-check"
            _write_executable(
                checker,
                "#!/bin/sh\ncase \"$1\" in */repo/build/GALE01/compiler-output) exit 0;; *) exit 1;; esac\n",
            )
            fixture.env["MWCC_INSPECT_REPARSE_CHECK_CMD"] = str(checker)
    fixture.env["MWCC_INSPECT_REMOTE_REF"] = exact_ref
    _write_executable(
        fixture.fake_bin / "ninja",
        f"#!/usr/bin/env python3\nprint({command!r})\n",
    )

    proc, output = _run_private_context(
        fixture,
        tmp_path,
        f"compiler-path-{path_kind}",
        source=fixture.source,
    )

    assert proc.returncode == 125
    assert "unsafe private repository path" in proc.stderr
    assert sentinel.read_text(encoding="utf-8") == "unchanged\n"
    assert not output.exists()
    job = fixture.remote_dir / f"build/mwcc-inspect-jobs/compiler-path-{path_kind}"
    terminal = _terminal(job)
    assert terminal["status"] == "failed"
    assert terminal["child_reaped"] == "true"


def test_preparation_clone_obeys_supervisor_deadline(tmp_path: Path) -> None:
    repo, script, candidate, env, remote_dir = _wrapper_fixture(tmp_path)
    ready = tmp_path / "clone-ready"
    release = tmp_path / "clone-release"
    clone_pid = tmp_path / "clone.pid"
    env.update(
        {
            "FAKE_CLONE_BLOCK_ID": "preparation-deadline",
            "FAKE_CLONE_READY": str(ready),
            "FAKE_CLONE_RELEASE": str(release),
            "FAKE_CLONE_PID": str(clone_pid),
        }
    )
    output = tmp_path / "preparation-deadline.txt"
    started = time.monotonic()

    proc = subprocess.run(
        [
            str(script),
            "--invocation-id",
            "preparation-deadline",
            "--deadline-seconds",
            "0.75",
            "--function",
            "fn_test",
            "--output",
            str(output),
            str(candidate),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=4,
    )

    assert proc.returncode == 124, proc.stdout + proc.stderr
    assert time.monotonic() - started < 3.5
    assert ready.exists()
    job = remote_dir / "build/mwcc-inspect-jobs/preparation-deadline"
    terminal = _terminal(job)
    assert terminal["status"] == "timeout"
    assert terminal["child_reaped"] == "true"
    _wait_for_pid_exit(int(clone_pid.read_text(encoding="utf-8")))
    assert not output.exists()


def test_cancel_during_preparation_is_scoped_and_parallel_job_succeeds(
    tmp_path: Path,
) -> None:
    repo, script, candidate, env, remote_dir = _wrapper_fixture(tmp_path)
    ready = tmp_path / "clone-ready"
    release = tmp_path / "clone-release"
    clone_pid = tmp_path / "clone.pid"
    env_a = env.copy()
    env_a.update(
        {
            "FAKE_CLONE_BLOCK_ID": "concurrent-a",
            "FAKE_CLONE_READY": str(ready),
            "FAKE_CLONE_RELEASE": str(release),
            "FAKE_CLONE_PID": str(clone_pid),
        }
    )
    output_a = tmp_path / "concurrent-a.txt"
    proc_a = subprocess.Popen(
        [
            str(script),
            "--invocation-id",
            "concurrent-a",
            "--deadline-seconds",
            "5",
            "--function",
            "fn_test",
            "--output",
            str(output_a),
            str(candidate),
        ],
        cwd=repo,
        env=env_a,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_for_path(ready)

    output_b = tmp_path / "concurrent-b.txt"
    proc_b = subprocess.run(
        [
            str(script),
            "--invocation-id",
            "concurrent-b",
            "--deadline-seconds",
            "5",
            "--function",
            "fn_test",
            "--output",
            str(output_b),
            str(candidate),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=8,
    )
    cancelled = subprocess.run(
        [str(script), "--cancel", "concurrent-a", "--cleanup-timeout", "2"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=4,
    )
    stdout_a, stderr_a = proc_a.communicate(timeout=4)

    assert proc_b.returncode == 0, proc_b.stdout + proc_b.stderr
    assert cancelled.returncode == 0, cancelled.stdout + cancelled.stderr
    assert proc_a.returncode == 124, stdout_a + stderr_a
    terminal_a = _terminal(remote_dir / "build/mwcc-inspect-jobs/concurrent-a")
    assert terminal_a["status"] == "cancelled"
    assert terminal_a["child_reaped"] == "true"
    _wait_for_pid_exit(int(clone_pid.read_text(encoding="utf-8")))
    assert output_b.read_text(encoding="utf-8") == "FUNCTION: fn_test\nCompilation finished.\n"
    assert not output_a.exists()


def test_concurrent_exact_refs_use_isolated_private_checkouts(tmp_path: Path) -> None:
    fixture = _private_context_fixture(tmp_path, header_text="#define INITIAL 1\n")
    fixture.header.write_text("#define REF_A 1\n", encoding="utf-8")
    ref_a = _commit(fixture.repo, "ref-a")
    fixture.header.write_text("#define REF_B 1\n", encoding="utf-8")
    ref_b = _commit(fixture.repo, "ref-b")
    shared_head = _head_commit(fixture.remote_dir)
    shared_status = _status(fixture.remote_dir)
    barrier = tmp_path / "inspector-barrier"
    barrier.mkdir()
    env_a = fixture.env.copy()
    env_a.update(
        {
            "FAKE_INSPECTOR_BARRIER": str(barrier),
            "MWCC_INSPECT_REMOTE_REF": ref_a,
        }
    )
    env_b = fixture.env.copy()
    env_b.update(
        {
            "FAKE_INSPECTOR_BARRIER": str(barrier),
            "MWCC_INSPECT_REMOTE_REF": ref_b,
        }
    )
    output_a = tmp_path / "ref-a.txt"
    output_b = tmp_path / "ref-b.txt"
    args_a = [
        str(fixture.script),
        "--invocation-id",
        "concurrent-ref-a",
        "--deadline-seconds",
        "5",
        "--output",
        str(output_a),
        str(fixture.source),
    ]
    args_b = [
        str(fixture.script),
        "--invocation-id",
        "concurrent-ref-b",
        "--deadline-seconds",
        "5",
        "--output",
        str(output_b),
        str(fixture.source),
    ]
    proc_a = subprocess.Popen(
        args_a,
        cwd=fixture.repo,
        env=env_a,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_for_path(barrier / "ready-concurrent-ref-a")
    proc_b = subprocess.Popen(
        args_b,
        cwd=fixture.repo,
        env=env_b,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_for_path(barrier / "ready-concurrent-ref-b")
    (barrier / "release-concurrent-ref-a").write_text("release")
    (barrier / "release-concurrent-ref-b").write_text("release")
    stdout_a, stderr_a = proc_a.communicate(timeout=6)
    stdout_b, stderr_b = proc_b.communicate(timeout=6)

    assert proc_a.returncode == 0, stdout_a + stderr_a
    assert proc_b.returncode == 0, stdout_b + stderr_b
    assert "HEADER_TEXT=#define REF_A 1" in output_a.read_text(encoding="utf-8")
    assert "HEADER_TEXT=#define REF_B 1" in output_b.read_text(encoding="utf-8")
    assert _head_commit(fixture.remote_dir) == shared_head
    assert _status(fixture.remote_dir) == shared_status
    jobs = fixture.remote_dir / "build/mwcc-inspect-jobs"
    assert not (jobs / "concurrent-ref-a").exists()
    assert not (jobs / "concurrent-ref-b").exists()


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
        "-i src/MSL -i src/Runtime -i extern/dolphin/include -i /opt/external "
        "-c src/melee/pl/plbonuslib.c -o build/GALE01/src/melee/pl "
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
        "MWCC_INSPECT_FRESH_BASH": "/bin/bash",
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
    launch_log = next(
        log
        for log in stdin_logs
        if "stage=job-init" in log and "stage=supervisor-launch" in log
    )
    assert sum("stage=job-init" in log for log in stdin_logs) == 1
    assert sum("stage=supervisor-launch" in log for log in stdin_logs) == 1
    job_id = re.search(r"JOB_ID='([^']+)'", launch_log)
    assert job_id is not None
    private_repo = remote_dir / "build" / "mwcc-inspect-jobs" / job_id.group(1) / "repo"
    assert f"REMOTE_REPO='{private_repo}'" in launch_log
    assert 'git clone --quiet --shared --no-checkout "${REMOTE_DIR}" "${REMOTE_REPO}"' in launch_log
    assert 'checkout --quiet --detach "${REMOTE_REF}"' in launch_log
    assert 'git fetch origin --prune' in launch_log
    assert 'git cat-file -e "${REMOTE_REF}^{commit}"' in launch_log
    assert "codex/local-only" not in launch_log
    assert f"REMOTE_DIR='{remote_dir}'" in launch_log
    assert "apply_overlay_archive" in launch_log
    assert "MWCC_INSPECT_OVERLAY_ARCHIVE_EOF" in launch_log
    assert "src/melee/pl/plbonuslib.c" in launch_log
    assert "src/melee/pl/plbonuslib.h" in launch_log
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() in launch_log
    assert hashlib.sha256((tmp_path / "plbonuslib.h").read_bytes()).hexdigest() in launch_log
    assert f"'-i' '{private_repo}/src'" in launch_log
    assert f"'-i' '{private_repo}/src/melee'" in launch_log
    assert f"'-i' '{private_repo}/src/MSL'" in launch_log
    assert f"'-i' '{private_repo}/src/Runtime'" in launch_log
    assert f"'-i' '{private_repo}/extern/dolphin/include'" in launch_log
    assert "'-i' '/opt/external'" in launch_log
    assert "${REMOTE_DIR}//opt/external" not in launch_log
    assert "REMOTE_TMP" not in launch_log
    assert "MWCC_ARGS_REMOTE" not in launch_log
    assert "if false" not in launch_log
    assert launch_log.rstrip().endswith("remote_job_main")
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
        "echo 'python wrapper mwcceppc.exe -c src/melee/pl/plbonuslib.c -o "
        "build/GALE01/src/melee/pl "
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
        "MWCC_INSPECT_FRESH_BASH": "/bin/bash",
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
        "echo 'python wrapper mwcceppc.exe -c src/melee/pl/plbonuslib.c -o "
        "build/GALE01/src/melee/pl "
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
    local_tmp = tmp_path / "local-tmp"
    local_tmp.mkdir()
    out_file = repo / "build" / "mwcc_inspect" / "candidates" / "candidate.txt"
    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env['PATH']}",
        "FAKE_SSH_LOG": str(log_dir),
        "TMPDIR": str(local_tmp),
        "MWCC_INSPECT_HOST": "fake-host",
        "MWCC_INSPECT_FRESH_BASH": "/bin/bash",
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
    assert not list(local_tmp.glob("mwcc-inspect-payload.*"))


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
        "echo 'python wrapper mwcceppc.exe -c src/melee/pl/plbonuslib.c -o "
        "build/GALE01/src/melee/pl "
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
        "MWCC_INSPECT_FRESH_BASH": "/bin/bash",
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
    launched = _launch_supervisor(job, job_id, env, child_seconds="30")
    assert launched.returncode == 0, launched.stdout + launched.stderr

    proc = subprocess.run(
        _supervisor_command("cancel", job, job_id, "--wait-seconds", "1"),
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert proc.returncode == 125
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
    child_pid = int((tmp_path / "taskkill.log").read_text().split()[1])
    assert _pid_alive(child_pid)
    assert not (job / "cleanup-eventually-reaped").exists()
    os.kill(child_pid, signal.SIGTERM)
    _wait_for_path(job / "cleanup-eventually-reaped", timeout=2)
    _wait_for_pid_exit(child_pid)
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
    release_late_write = tmp_path / "release-late-write"
    late_code = (
        "import time\n"
        "from pathlib import Path\n"
        f"release = Path({str(release_late_write)!r})\n"
        "while not release.exists():\n"
        "    time.sleep(0.01)\n"
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
    release_late_write.write_text("release\n", encoding="utf-8")
    _wait_for_pid_exit(descendant_pid)
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
