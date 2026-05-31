from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyelftools_is_declared_for_name_magic_helpers() -> None:
    """checkdiff name-magic imports elftools through melee-agent helpers."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    deps = data["project"]["dependencies"]
    assert any(dep.lower().startswith("pyelftools") for dep in deps)
