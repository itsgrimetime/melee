"""Resolve the main-checkout root + DOL path for the backtest harness.

The harness needs *the shared main checkout* (full git history + an
`orig/GALE01/sys/main.dol`) as ground truth — it fetches pre-match objects from
it over `file://` and spins up read-only worktrees against it. That is by design
(see the plan's Global Constraints): blind tiers run in throwaway sandboxes, the
ground-truth scorer runs against the real checkout.

Historically this was a hard-coded `"/Users/mike/code/melee"` literal in both
``run.py`` and ``sandbox.py``. This module replaces those literals with the same
resolver the rest of the CLI uses (``_compute_melee_root`` /
``DEFAULT_MELEE_ROOT``), while still guaranteeing the resolved root actually has
a DOL — falling back to the worktree-doctor ``DOL_CANDIDATES`` ordering
(``~/code/melee`` first) when the resolver lands on a worktree that lacks one.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

# Relative path of the GameCube DOL inside a melee checkout (gitignored).
_DOL_RELATIVE = Path("orig") / "GALE01" / "sys" / "main.dol"


def _looks_like_melee_root(path: Path) -> bool:
    return (path / "configure.py").is_file() and (path / "src" / "melee").is_dir()


def _is_main_checkout(path: Path) -> bool:
    """True for a primary checkout (``.git`` is a directory), False for a linked
    ``git worktree`` (``.git`` is a gitdir-link file)."""
    return (path / ".git").is_dir()


def _dol_candidate_roots() -> list[Path]:
    """Checkout roots that the worktree-doctor knows tend to carry the DOL.

    Mirrors ``tools/worktree_doctor.DOL_CANDIDATES`` (``~/code/melee`` first) but
    expressed as *checkout roots* (the parent of ``orig/GALE01/sys/main.dol``).
    """
    return [Path.home() / "code" / "melee"]


@lru_cache(maxsize=1)
def main_repo_root() -> Path:
    """Resolve the shared main checkout (full history + DOL) for ground truth.

    The harness fetches pre-match objects from this checkout and runs the
    ground-truth scorer against it, so it must be a checkout with a DOL — and,
    per the plan, the *shared main checkout*, not a throwaway worktree.

    Order:
      1. The CLI resolver (``DEFAULT_MELEE_ROOT``) IF it is a real main checkout
         (``.git`` directory, not a worktree gitdir-link) that already carries the
         DOL.
      2. The first ``DOL_CANDIDATES``-style root that is a main checkout with a DOL
         (``~/code/melee`` is candidate #1, matching worktree-doctor) — used when
         the resolver lands on a worktree, as it does when the CLI is invoked from
         an isolated agent worktree.
      3. Otherwise fall back to the CLI resolver's answer (commands then fail with
         a clear DOL-missing error rather than acting on a wrong literal).
    """
    # Import lazily so importing this module never drags in the heavy CLI package
    # during unit tests that only want the path helpers.
    from src.cli._common import DEFAULT_MELEE_ROOT

    resolved = Path(DEFAULT_MELEE_ROOT)
    if _is_main_checkout(resolved) and (resolved / _DOL_RELATIVE).exists():
        return resolved

    for candidate in _dol_candidate_roots():
        if (
            _is_main_checkout(candidate)
            and _looks_like_melee_root(candidate)
            and (candidate / _DOL_RELATIVE).exists()
        ):
            return candidate

    return resolved


def main_repo_dol() -> Path:
    """Absolute path of the ground-truth DOL inside the resolved main checkout."""
    return main_repo_root() / _DOL_RELATIVE
