"""Tests for the mwcc-inspect workflow wrapper."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_mwcc_inspect_upload_uses_remote_bash_stdin_for_candidate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workflow = repo / "tools" / "workflow"
    workflow.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "tools" / "workflow" / "mwcc-inspect.sh", workflow)

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

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_dir = tmp_path / "ssh-log"
    log_dir.mkdir()
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
            idx = len(list(log_dir.glob("*.argv")))
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
            (log_dir / f"{idx:02d}.argv").write_text(repr(sys.argv[1:]), encoding="utf-8")
            (log_dir / f"{idx:02d}.stdin").write_text(payload, encoding="utf-8")
            if "mktemp -d" in payload:
                print("/tmp/mwcc-inspect-plbonuslib.ABCDEF")
            elif "MwccInspectorCLI" in payload:
                print("FUNCTION: fn_test")
                print("LOCAL VARIABLES (sorted by ObjObject address):")
                print("STATEMENTS")
                print("Compilation finished")
        """),
    )

    out_file = repo / "build" / "mwcc_inspect" / "candidates" / "candidate.txt"
    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env['PATH']}",
        "FAKE_SSH_LOG": str(log_dir),
        "MWCC_INSPECT_HOST": "fake-host",
        "MWCC_INSPECT_REMOTE_BASH": "bash",
        "MWCC_INSPECT_REMOTE_DIR": "/remote/melee",
        "MWCC_INSPECT_CLI": "/remote/MwccInspectorCLI",
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
    assert "[mwcc-inspect] Remote ref: master" in proc.stdout
    assert "FUNCTION: fn_test" in out_file.read_text(encoding="utf-8")
    argv_logs = [path.read_text(encoding="utf-8") for path in sorted(log_dir.glob("*.argv"))]
    assert all("'-lc'" not in argv for argv in argv_logs)
    assert all("'-s'" in argv for argv in argv_logs)
    stdin_logs = [path.read_text(encoding="utf-8") for path in sorted(log_dir.glob("*.stdin"))]
    assert "mktemp -d '/remote/melee/build/mwcc-inspect-plbonuslib.XXXXXX'" in stdin_logs[0]
    assert "mkdir -p '/tmp/mwcc-inspect-plbonuslib.ABCDEF/src/melee/pl'" in stdin_logs[1]
    upload_log = next(log for log in stdin_logs if "plbonuslib.c" in log)
    assert "cat > '/tmp/mwcc-inspect-plbonuslib.ABCDEF/src/melee/pl/plbonuslib.c'" in upload_log
    assert "int candidate = 1;" in upload_log
    header_log = next(log for log in stdin_logs if "plbonuslib.h" in log)
    assert "cat > '/tmp/mwcc-inspect-plbonuslib.ABCDEF/src/melee/pl/plbonuslib.h'" in header_log
    assert "#define LOCAL_HEADER 1" in header_log
    assert any(
        "find '/remote/melee/src/melee/pl'" in log and "-name '*.h'" in log
        for log in stdin_logs
    )
    inspector_log = next(log for log in stdin_logs if "MwccInspectorCLI" in log)
    assert "checkout --quiet 'master'" in inspector_log
    assert "codex/local-only" not in inspector_log
    assert "REMOTE_DIR='/remote/melee'" in inspector_log
    assert (
        'MWCC_ARGS_REMOTE="-i ${REMOTE_TMP_REL}/src -i ${REMOTE_TMP}/src '
        '-i ${REMOTE_TMP_REL}/src/melee -i ${REMOTE_TMP}/src/melee '
        '${MWCC_ARGS_REMOTE}"'
    ) in inspector_log
    assert (
        'MWCC_ARGS_REMOTE="${MWCC_ARGS_REMOTE/ -i src / -i src -i '
        '${REMOTE_TMP_REL}/src -i ${REMOTE_TMP}/src }"'
    ) in inspector_log
    assert (
        'MWCC_ARGS_REMOTE="${MWCC_ARGS_REMOTE/ -i src\\/melee / -i '
        'src\\/melee -i ${REMOTE_TMP_REL}\\/src\\/melee -i '
        '${REMOTE_TMP}\\/src\\/melee }"'
    ) in inspector_log


def test_mwcc_inspect_remote_failure_preserves_diagnostics_and_no_empty_output(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    workflow = repo / "tools" / "workflow"
    workflow.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "tools" / "workflow" / "mwcc-inspect.sh", workflow)

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
            if "mktemp -d" in payload:
                print("/tmp/mwcc-inspect-plbonuslib.ABCDEF")
            elif "MwccInspectorCLI" in payload:
                print("mwcc inspector failed before structured output", file=sys.stderr)
                sys.exit(42)
        """),
    )

    out_file = repo / "build" / "mwcc_inspect" / "candidates" / "candidate.txt"
    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env['PATH']}",
        "MWCC_INSPECT_HOST": "fake-host",
        "MWCC_INSPECT_REMOTE_BASH": "bash",
        "MWCC_INSPECT_REMOTE_DIR": "/remote/melee",
        "MWCC_INSPECT_CLI": "/remote/MwccInspectorCLI",
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

    assert proc.returncode == 42
    assert "[mwcc-inspect] remote command failed" in proc.stderr
    assert "mwcc inspector failed before structured output" in proc.stderr
    assert not out_file.exists() or out_file.stat().st_size > 0
