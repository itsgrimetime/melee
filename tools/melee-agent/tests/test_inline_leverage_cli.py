from __future__ import annotations

import pathlib
import subprocess


CLI_CWD = pathlib.Path(__file__).parent.parent


def test_inline_leverage_help() -> None:
    proc = subprocess.run(
        [
            "python",
            "-m",
            "src.cli",
            "debug",
            "measure",
            "inline-leverage",
            "--help",
        ],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "--module" in proc.stdout
    assert "--function" in proc.stdout
    assert "--dry-run" in proc.stdout
    assert "--evidence-dir" in proc.stdout
    assert "--json" in proc.stdout
