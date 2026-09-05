"""Ghidra project location and validation."""
from pathlib import Path

from .._common import DECOMP_CONFIG_DIR

GHIDRA_PROJECT_NAME = "melee"


def ghidra_project_dir() -> Path:
    """Canonical Ghidra project directory.

    Shared across all worktrees — Ghidra projects are large (hundreds of MB)
    and the analyzed DOL doesn't change.
    """
    return DECOMP_CONFIG_DIR / "ghidra"


def ghidra_project_gpr() -> Path:
    """Path to the .gpr project file."""
    return ghidra_project_dir() / f"{GHIDRA_PROJECT_NAME}.gpr"


def is_project_populated(project_dir: Path) -> bool:
    """Check whether the project actually contains imported program data.

    Distinguishes a real populated project from an empty placeholder:
    Ghidra creates `.rep/idata/~index.dat` even for empty projects, but a
    real program adds hex-named subdirectories with file data.
    """
    gpr = next(project_dir.glob("*.gpr"), None)
    if gpr is None:
        return False
    rep = project_dir / f"{gpr.stem}.rep" / "idata"
    if not rep.exists():
        return False
    for entry in rep.iterdir():
        if entry.is_dir() and entry.name != "user":
            # Hex-named subdirs indicate imported program data
            return True
    return False
