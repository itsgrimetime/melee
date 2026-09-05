from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "tools/mwcc_debug/scripts/setup_ghidra.sh"


def test_setup_script_delegates_to_branch_local_cli_and_forwards_arguments(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture = tmp_path / "capture.txt"
    fake_python = fake_bin / "python"
    fake_python.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$PYTHONPATH\" > \"$CAPTURE\"\n"
        "printf '%s\\n' \"$@\" >> \"$CAPTURE\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    inherited_pythonpath = "/existing/pythonpath"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "PYTHONPATH": inherited_pythonpath,
        "CAPTURE": str(capture),
    }

    subprocess.run(
        [str(SCRIPT), "--repair", "--json"],
        cwd=tmp_path,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert capture.read_text(encoding="utf-8").splitlines() == [
        f"{REPO / 'tools/melee-agent'}{os.pathsep}{inherited_pythonpath}",
        "-m",
        "src.cli",
        "debug",
        "retro",
        "ghidra-setup",
        "--repair",
        "--json",
    ]
