"""Package-layout invariants for the melee-agent CLI."""
from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_cli_packages_do_not_have_legacy_module_siblings() -> None:
    agent_src = PACKAGE_ROOT / "src"
    package_paths = [
        agent_src / "cli" / "debug",
        agent_src / "search" / "cli",
    ]

    for package_path in package_paths:
        assert (package_path / "__init__.py").is_file()
        sibling = package_path.with_suffix(".py")
        assert not sibling.exists(), (
            f"{sibling.relative_to(PACKAGE_ROOT)} must not coexist with the "
            f"{package_path.relative_to(PACKAGE_ROOT)} package"
        )
