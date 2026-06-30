"""Regression tests for tools/workflow/pr-worktree.sh."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_pr_worktree_create_overlays_missing_fork_tools(tmp_path: Path) -> None:
    repo = tmp_path / "melee"
    repo.mkdir()
    _git(repo, "init", "-b", "master")
    _git(repo, "config", "user.email", "agent@example.test")
    _git(repo, "config", "user.name", "Agent")
    (repo / "src").mkdir()
    (repo / "src" / "demo.c").write_text("void demo(void) {}\n", encoding="utf-8")
    (repo / "config" / "GALE01").mkdir(parents=True)
    (repo / "tools").mkdir()
    (repo / "tools" / "upstream-tool.py").write_text(
        "# upstream tool\n",
        encoding="utf-8",
    )
    _git(repo, "add", "src/demo.c", "tools/upstream-tool.py")
    _git(repo, "commit", "-m", "upstream baseline")
    _git(repo, "branch", "pr/demo")

    workflow_dir = repo / "tools" / "workflow"
    workflow_dir.mkdir()
    shutil.copy2(
        REPO_ROOT / "workflow" / "pr-worktree.sh",
        workflow_dir / "pr-worktree.sh",
    )
    (repo / "tools" / "checkdiff.py").write_text("# checkdiff\n", encoding="utf-8")
    (repo / "tools" / "worktree-doctor.py").write_text(
        "# doctor\n",
        encoding="utf-8",
    )
    _git(
        repo,
        "add",
        "tools/workflow/pr-worktree.sh",
        "tools/checkdiff.py",
        "tools/worktree-doctor.py",
    )
    _git(repo, "commit", "-m", "fork tooling")

    result = subprocess.run(
        ["bash", "tools/workflow/pr-worktree.sh", "create", "pr/demo"],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    worktree = tmp_path / "melee-pr"
    assert (worktree / "tools" / "upstream-tool.py").exists()
    assert (worktree / "tools" / "checkdiff.py").is_symlink()
    assert (worktree / "tools" / "worktree-doctor.py").is_symlink()
    gitdir = _git(worktree, "rev-parse", "--git-dir").stdout.strip()
    exclude = (worktree / gitdir / "info" / "exclude").resolve()
    assert exclude.exists()
    exclude_text = exclude.read_text(encoding="utf-8")
    assert "tools/checkdiff.py" in exclude_text
    assert "tools/worktree-doctor.py" in exclude_text
    assert "tools/melee-agent/" in exclude_text
    assert "\ntools/\n" not in exclude_text
