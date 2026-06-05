from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyelftools_is_declared_for_name_magic_helpers() -> None:
    """checkdiff name-magic imports elftools through melee-agent helpers."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    deps = data["project"]["dependencies"]
    assert any(dep.lower().startswith("pyelftools") for dep in deps)


def test_repo_root_ignores_permuter_nonmatchings() -> None:
    """Bootstrap scratch dirs should not be swept into routine git add -A."""
    repo_root = Path(__file__).resolve().parents[3]
    gitignore = repo_root / ".gitignore"
    entries = {
        line.strip()
        for line in gitignore.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "/nonmatchings/" in entries or "nonmatchings/" in entries
