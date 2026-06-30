"""Permuter-backed VariantSource adapter for `simplify_search.search()`.

This adapter harvests pre-existing decomp-permuter output dirs and yields
each ``output-*/source.c`` as a `SourceVariant`. The MVP is harvest-only:
the user runs permuter separately (typically via the existing
``debug permute run`` Tier 2 workflow), and this adapter walks whatever
output is already on disk.

The decomp-permuter clone is unforked upstream — there is no patched
permuter binary. We compose by reading its output dirs.

Why a separate file from ``simplify_variants.py``? The variant-stream
architecture in ``simplify_search.py`` is designed so that adding a new
adapter family is a one-file addition with no driver changes. Keeping
the permuter adapter in its own module makes that guarantee visible in
the directory layout (and avoids dragging the existing primitives into
permuter's launch/resolution concerns).

Auto-launching permuter from this adapter is out of scope for the MVP —
that orchestration is its own follow-up. The brute-force harvest path
is enough to validate the variant-stream + permuter combination.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from .simplify_search import FunctionContext, SourceVariant


_DEFAULT_PERMUTER_ROOTS: tuple[Path, ...] = (
    Path("~/code/decomp-permuter").expanduser(),
    Path("~/code/melee-harness/decomp-permuter").expanduser(),
)


def _default_permuter_root() -> Path | None:
    """Mirror the resolution used by `scripts/permute_with_mwcc.py`.

    Honors `MELEE_PERMUTER_ROOT` first so tests and unusual layouts can
    override without touching `$HOME`. Returns None if no candidate
    exists — callers decide whether that's an error (CLI) or just a
    skip (the adapter)."""
    env = os.environ.get("MELEE_PERMUTER_ROOT")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p
    for cand in _DEFAULT_PERMUTER_ROOTS:
        if cand.exists():
            return cand
    return None


def resolve_permuter_function_dir(
    function: str,
    *,
    perm_root: Path | None = None,
) -> Path | None:
    """Resolve `<perm_root>/nonmatchings/<function>/` if it exists.

    Returns the resolved directory `Path` or `None` if either the perm
    root can't be located or the per-function subdir doesn't exist. The
    None result is the signal to the adapter that there's no permuter
    output to harvest — the search proceeds with whatever other sources
    are configured.

    Mirrors the inline pattern used in `cli/debug.py` (`perm_root /
    "nonmatchings" / function`) rather than introducing a competing
    convention.
    """
    if perm_root is None:
        perm_root = _default_permuter_root()
        if perm_root is None:
            return None
    fn_dir = perm_root / "nonmatchings" / function
    if not fn_dir.is_dir():
        return None
    return fn_dir


def permuter_source(
    ctx: FunctionContext,
    *,
    perm_dir_override: Path | None = None,
    perm_root: Path | None = None,
) -> Iterator[SourceVariant]:
    """Yield `SourceVariant`s from existing decomp-permuter output dirs.

    Walks `<perm_dir>/output-*/source.c` and yields each candidate as a
    `SourceVariant`. The provenance string includes the output dir name
    so callers can trace candidates back to a specific permuter session
    (e.g. ``"permuter output-0042-1/source.c"``).

    Args:
      ctx: Function being searched. `ctx.source_path` is reused as the
        `parent_baseline` on every emitted variant (consistent with the
        other adapters — even though permuter outputs aren't strict
        mutations of `ctx.source_path`, the field documents where the
        canonical pre-search source lives).
      perm_dir_override: If set, the adapter walks this directory
        directly. Useful for tests and for pointing at a perm dir that
        doesn't follow the standard `<perm_root>/nonmatchings/<fn>/`
        layout.
      perm_root: Override the permuter root for auto-resolution. If
        neither this nor `perm_dir_override` is provided, falls back to
        the env var / standard locations checked by
        `_default_permuter_root`.

    Yields nothing (silently) if no permuter output dir is found. That
    keeps the adapter cheap to include in every search call — if the
    user hasn't run permuter for this function, the CLI layer is
    responsible for surfacing a "run permuter first" hint.

    Variants are yielded in lexicographic order of their dir name, so
    re-running the search on an unchanged dir produces the same compile
    order. Permuter's `output-NNNN-N` naming sorts naturally under this
    rule.
    """
    if perm_dir_override is not None:
        perm_dir = perm_dir_override
    else:
        resolved = resolve_permuter_function_dir(
            ctx.function, perm_root=perm_root,
        )
        if resolved is None:
            return
        perm_dir = resolved

    if not perm_dir.is_dir():
        return

    # Sort by directory name so the harvest order is deterministic. The
    # filter excludes regular files / symlinks that happen to match the
    # `output-*` glob shape — only real directories can hold a candidate.
    output_dirs = sorted(
        (d for d in perm_dir.glob("output-*") if d.is_dir()),
        key=lambda p: p.name,
    )

    for output_dir in output_dirs:
        candidate = output_dir / "source.c"
        # Skip dirs that aren't yet fully written (permuter occasionally
        # crashes mid-output and leaves a directory without a source.c).
        # Also skip if `source.c` is somehow not a regular file (symlink
        # to a missing target, fifo, etc.).
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            # Race against the permuter process or a permissions issue —
            # treat as a soft skip rather than aborting the harvest.
            continue
        yield SourceVariant(
            text=text,
            provenance=f"permuter {output_dir.name}/source.c",
            parent_baseline=ctx.source_path,
        )
