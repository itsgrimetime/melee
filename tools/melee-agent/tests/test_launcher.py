from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_console_script_points_at_worktree_resolving_launcher() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"

    assert 'melee-agent = "src.launcher:main"' in pyproject.read_text(encoding="utf-8")


def test_launcher_imports_cli_from_invoking_git_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    local_package_root = repo / "tools" / "melee-agent"
    local_cli = local_package_root / "src" / "cli.py"
    local_cli.parent.mkdir(parents=True)
    (local_cli.parent / "__init__.py").write_text("", encoding="utf-8")
    local_cli.write_text(
        "from pathlib import Path\n"
        "def main():\n"
        "    print('LOCAL_CLI:' + str(Path(__file__).resolve()))\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    installed_src = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(installed_src)
    proc = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "from src.launcher import main; raise SystemExit(main())",
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert proc.returncode == 0, proc.stderr
    assert f"LOCAL_CLI:{local_cli.resolve()}" in proc.stdout
    assert "using repo-local package" in proc.stderr


def test_launcher_print_import_path_uses_invoking_git_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    local_package_root = repo / "tools" / "melee-agent"
    local_cli = local_package_root / "src" / "cli.py"
    local_cli.parent.mkdir(parents=True)
    (local_cli.parent / "__init__.py").write_text("", encoding="utf-8")
    local_cli.write_text("def main(): pass\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    installed_src = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(installed_src)
    env["MELEE_AGENT_PRINT_SRC_CLI"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "from src.launcher import main; raise SystemExit(main())",
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(local_cli.resolve())
