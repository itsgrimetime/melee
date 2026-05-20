"""Shared pytest fixtures for melee-agent tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MNVIBRATION_SRC_O = _REPO_ROOT / "build/GALE01/src/melee/mn/mnvibration.o"


@pytest.fixture(scope="session", autouse=True)
def _refresh_mnvibration_src_o() -> None:
    """Ensure the source .o used as the anonymous-magic-symbol fixture is
    freshly built at session start.

    ``tools/checkdiff.py`` now mutates this .o in place (renaming the
    anonymous ``@N`` .sdata2 symbols to their production names) on every
    invocation. Tests that depend on the .o having ``@N`` symbols would
    otherwise fail or pass non-deterministically depending on whether a
    user ran ``checkdiff.py`` between test sessions.

    The fixture deletes the .o and re-runs ninja so anyone consuming
    ``_FIXTURE_O`` / ``_SRC_O`` sees the canonical pre-rename state. If
    ninja isn't usable (e.g. build dir missing), do nothing — tests that
    truly need the fixture have their own skip guards.
    """
    if not (_REPO_ROOT / "build.ninja").exists():
        return
    _MNVIBRATION_SRC_O.unlink(missing_ok=True)
    subprocess.run(
        ["ninja", str(_MNVIBRATION_SRC_O.relative_to(_REPO_ROOT))],
        cwd=_REPO_ROOT,
        capture_output=True,
    )
