"""Pcdump cache layer.

Stores pcdump.txt files at `build/mwcc_debug_cache/<unit>.txt` keyed by
the translation unit (without the `src/` prefix). Cache invalidation is
mtime-based: if `<unit>.c` is newer than the cached pcdump, the cache
is stale.

Why bother: each pcdump is a 30-second SSH roundtrip. Across a typical
"stuck function" session an agent runs 4-5 commands that all consume
the same pcdump. Caching turns 4-5×30sec into 1×30sec + 4×instant.

The cache is intentionally in `build/` so it gets cleaned by
`ninja -t clean` along with everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CACHE_DIRNAME = "mwcc_debug_cache"


@dataclass
class CacheEntry:
    """A located cache entry with freshness info."""

    path: Path  # absolute path to the cached pcdump.txt
    source_path: Path  # the .c file the cache was built from
    fresh: bool  # True if cache is newer than source


def cache_path(melee_root: Path, unit: str) -> Path:
    """Return the cache pcdump path for a given unit.

    `unit` is the path WITHOUT the `src/` prefix and WITHOUT the `.c`
    suffix — i.e. the same convention as `report.json`'s unit names.
    For example, `melee/mn/mnvibration`.

    The cache file is `build/mwcc_debug_cache/<unit>.txt`.
    """
    return melee_root / "build" / CACHE_DIRNAME / f"{unit}.txt"


def source_path(melee_root: Path, unit: str) -> Path:
    """Return the source `.c` file path for a unit."""
    return melee_root / "src" / f"{unit}.c"


def lookup(melee_root: Path, unit: str) -> Optional[CacheEntry]:
    """Look up the cache entry for a unit. Returns None if there's no
    cache file at all. Returns a CacheEntry with `fresh=False` if the
    cache exists but is older than the source.

    Callers should check `entry.fresh` and either use the cached
    pcdump or trigger a fresh `debug pcdump` run.
    """
    cache = cache_path(melee_root, unit)
    src = source_path(melee_root, unit)
    if not cache.exists():
        return None
    if not src.exists():
        # No source — can't determine freshness. Treat as stale.
        return CacheEntry(path=cache, source_path=src, fresh=False)
    cache_mtime = cache.stat().st_mtime
    src_mtime = src.stat().st_mtime
    return CacheEntry(path=cache, source_path=src, fresh=src_mtime <= cache_mtime)


def ensure_cache_dir(melee_root: Path) -> Path:
    """Create the cache directory if it doesn't exist. Returns the
    cache root path."""
    p = melee_root / "build" / CACHE_DIRNAME
    p.mkdir(parents=True, exist_ok=True)
    return p
