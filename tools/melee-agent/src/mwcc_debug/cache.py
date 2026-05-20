"""Pcdump cache layer.

Stores pcdump.txt files at `build/mwcc_debug_cache/<unit>.txt` keyed by
the translation unit (without the `src/` prefix). Cache invalidation is
content-hash-based (with mtime fallback for older entries that pre-date
the hash sidecar).

Why content hashing instead of pure mtime:
  Several commands (``enumerate-decl-orders``, ``tier3-search``,
  ``verify-perm``) temporarily patch and restore the source file.  A
  restore updates mtime even when the content is byte-for-byte identical.
  Subsequent debug commands would then warn "src is newer than cache"
  despite no real change.  Comparing SHA-256 digests eliminates these
  false-stale reports.

Freshness algorithm:
  1. If ``<cache>.hash`` exists: read it, hash the source, compare.
     Fresh iff digests match (mtime is ignored).
  2. Otherwise (legacy cache without sidecar): fall back to mtime
     comparison so old caches stay valid.

Why bother: each pcdump is a 30-second SSH roundtrip. Across a typical
"stuck function" session an agent runs 4-5 commands that all consume
the same pcdump. Caching turns 4-5×30sec into 1×30sec + 4×instant.

The cache is intentionally in `build/` so it gets cleaned by
`ninja -t clean` along with everything else.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CACHE_DIRNAME = "mwcc_debug_cache"


@dataclass
class CacheEntry:
    """A located cache entry with freshness info."""

    path: Path  # absolute path to the cached pcdump.txt
    source_path: Path  # the .c file the cache was built from
    fresh: bool  # True if cache content matches source content


def cache_path(melee_root: Path, unit: str) -> Path:
    """Return the cache pcdump path for a given unit.

    `unit` is the path WITHOUT the `src/` prefix and WITHOUT the `.c`
    suffix — i.e. the same convention as `report.json`'s unit names.
    For example, `melee/mn/mnvibration`.

    The cache file is `build/mwcc_debug_cache/<unit>.txt`.
    """
    return melee_root / "build" / CACHE_DIRNAME / f"{unit}.txt"


def hash_path(cache_p: Path) -> Path:
    """Return the sidecar hash file path for a given cache pcdump path.

    The sidecar lives alongside the cache file with a `.hash` extension.
    It stores the SHA-256 hex digest of the source file as of the time
    the cache was written.
    """
    return cache_p.with_suffix(".hash")


def _sha256_file(p: Path) -> str:
    """Return the SHA-256 hex digest of ``p``'s content."""
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_hash_sidecar(cache_p: Path, src: Path) -> None:
    """Write (or overwrite) the ``.hash`` sidecar for ``cache_p``.

    Called by the pcdump writer immediately after the cache file is
    written/renamed so that freshness checks use content comparison
    rather than mtime.
    """
    digest = _sha256_file(src)
    hash_path(cache_p).write_text(digest + "\n", encoding="ascii")


def source_path(melee_root: Path, unit: str) -> Path:
    """Return the source `.c` file path for a unit."""
    return melee_root / "src" / f"{unit}.c"


def lookup(melee_root: Path, unit: str) -> Optional[CacheEntry]:
    """Look up the cache entry for a unit. Returns None if there's no
    cache file at all. Returns a CacheEntry with ``fresh=False`` if the
    cache is determined to be stale.

    Freshness check (in order):
      1. If the ``.hash`` sidecar exists: compare its stored digest to
         the current source digest.  Fresh iff they match.
      2. Otherwise: fall back to mtime comparison (legacy behaviour for
         caches written before the hash sidecar was introduced).

    Callers should check ``entry.fresh`` and either use the cached
    pcdump or trigger a fresh ``debug pcdump`` run.
    """
    cache = cache_path(melee_root, unit)
    src = source_path(melee_root, unit)
    if not cache.exists():
        return None
    if not src.exists():
        # No source — can't determine freshness. Treat as stale.
        return CacheEntry(path=cache, source_path=src, fresh=False)

    hp = hash_path(cache)
    if hp.exists():
        # Content-hash path: compare stored digest to current source digest.
        try:
            stored = hp.read_text(encoding="ascii").strip()
            current = _sha256_file(src)
            fresh = (stored == current)
        except OSError:
            fresh = False
        return CacheEntry(path=cache, source_path=src, fresh=fresh)

    # Legacy mtime fallback for caches without a sidecar.
    cache_mtime = cache.stat().st_mtime
    src_mtime = src.stat().st_mtime
    return CacheEntry(path=cache, source_path=src, fresh=src_mtime <= cache_mtime)


def ensure_cache_dir(melee_root: Path) -> Path:
    """Create the cache directory if it doesn't exist. Returns the
    cache root path."""
    p = melee_root / "build" / CACHE_DIRNAME
    p.mkdir(parents=True, exist_ok=True)
    return p
