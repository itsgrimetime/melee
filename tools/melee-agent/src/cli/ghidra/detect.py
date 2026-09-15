"""Auto-detect Ghidra install and Java for pyghidra."""
import os
from pathlib import Path

# Common installation root paths to search.
# A valid install has `application.properties` directly inside it.
# For Homebrew, this lives at /opt/homebrew/Cellar/ghidra/<version>/libexec
# For tarball installs, this lives at /Applications/ghidra_<version>_PUBLIC
_SEARCH_PATHS: list[Path] = [
    Path("/opt/homebrew/Cellar/ghidra"),       # macOS arm64 Homebrew
    Path("/usr/local/Cellar/ghidra"),          # macOS x86_64 Homebrew
    Path("/Applications"),                      # macOS manual install
    Path.home() / "Library" / "ghidra",        # macOS user-local
    Path("/opt"),                               # Linux manual install
    Path.home() / "ghidra",                    # user home tarball
]


def _is_valid_install(path: Path) -> bool:
    """A path is a valid Ghidra install if application.properties lives
    either directly under it, or under a `Ghidra/` subdir (Homebrew layout)."""
    if not path.is_dir():
        return False
    return (path / "application.properties").is_file() or (path / "Ghidra" / "application.properties").is_file()


def _search_path(root: Path) -> Path | None:
    """Find a valid install under `root`.

    Looks for `application.properties` directly under `root` or under
    `root/*` or `root/*/libexec` (Homebrew's nested layout).
    """
    if not root.exists():
        return None

    if _is_valid_install(root):
        return root

    for child in sorted(root.iterdir(), reverse=True):  # newest version first
        if not child.is_dir():
            continue
        if _is_valid_install(child):
            return child
        nested = child / "libexec"
        if _is_valid_install(nested):
            return nested
        # Some installs have Ghidra/Ghidra layout
        nested2 = child / "Ghidra"
        if _is_valid_install(nested2):
            return nested2

    return None


def detect_ghidra_install() -> Path | None:
    """Return path to a valid Ghidra install, or None if not found.

    Search order:
    1. $GHIDRA_INSTALL_DIR if set and valid
    2. Common installation roots
    """
    env_val = os.environ.get("GHIDRA_INSTALL_DIR")
    if env_val:
        env_path = Path(env_val)
        if _is_valid_install(env_path):
            return env_path

    for root in _SEARCH_PATHS:
        found = _search_path(root)
        if found is not None:
            return found

    return None
