"""Tests for the pcdump cache layer."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.mwcc_debug.cache import (
    CACHE_DIRNAME,
    cache_path,
    ensure_cache_dir,
    hash_path,
    lookup,
    source_path,
    write_hash_sidecar,
)


@pytest.fixture
def melee_root(tmp_path: Path) -> Path:
    """A fake melee tree at tmp_path with src/ and build/ directories."""
    (tmp_path / "src" / "melee" / "mn").mkdir(parents=True)
    (tmp_path / "build").mkdir()
    return tmp_path


def test_cache_path_layout(melee_root: Path) -> None:
    p = cache_path(melee_root, "melee/mn/mnvibration")
    assert p == melee_root / "build" / CACHE_DIRNAME / "melee/mn/mnvibration.txt"


def test_source_path_layout(melee_root: Path) -> None:
    p = source_path(melee_root, "melee/mn/mnvibration")
    assert p == melee_root / "src" / "melee/mn/mnvibration.c"


def test_lookup_returns_none_when_no_cache(melee_root: Path) -> None:
    assert lookup(melee_root, "melee/mn/mnvibration") is None


def test_lookup_fresh_when_cache_newer_than_source(melee_root: Path) -> None:
    src = melee_root / "src" / "melee" / "mn" / "mnvibration.c"
    src.write_text("// source")

    # Wait briefly so mtimes are distinguishable
    time.sleep(0.02)

    cache = cache_path(melee_root, "melee/mn/mnvibration")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("Starting function ...")

    entry = lookup(melee_root, "melee/mn/mnvibration")
    assert entry is not None
    assert entry.fresh is True
    assert entry.path == cache


def test_lookup_stale_when_source_newer_than_cache(melee_root: Path) -> None:
    cache = cache_path(melee_root, "melee/mn/mnvibration")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("Starting function ...")

    time.sleep(0.02)

    src = melee_root / "src" / "melee" / "mn" / "mnvibration.c"
    src.write_text("// updated source")

    entry = lookup(melee_root, "melee/mn/mnvibration")
    assert entry is not None
    assert entry.fresh is False


def test_lookup_when_source_missing(melee_root: Path) -> None:
    """Cache exists but source doesn't. Should return entry, not-fresh."""
    cache = cache_path(melee_root, "melee/missing/foo")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("dump")
    entry = lookup(melee_root, "melee/missing/foo")
    assert entry is not None
    assert entry.fresh is False


def test_ensure_cache_dir_creates_path(melee_root: Path) -> None:
    p = ensure_cache_dir(melee_root)
    assert p == melee_root / "build" / CACHE_DIRNAME
    assert p.is_dir()


def test_hash_path_is_sidecar_of_cache(melee_root: Path) -> None:
    """hash_path() returns a .hash sibling of the cache .txt file."""
    cp = cache_path(melee_root, "melee/mn/mnvibration")
    hp = hash_path(cp)
    assert hp == cp.with_suffix(".hash")
    assert hp.parent == cp.parent


def test_write_hash_sidecar_creates_sidecar(melee_root: Path) -> None:
    """write_hash_sidecar() writes a hex-digest file next to the cache."""
    src = melee_root / "src" / "melee" / "mn" / "mnvibration.c"
    src.write_text("// source content for hashing")

    cache = cache_path(melee_root, "melee/mn/mnvibration")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("Starting function ...")

    write_hash_sidecar(cache, src)

    hp = hash_path(cache)
    assert hp.exists()
    digest = hp.read_text(encoding="ascii").strip()
    assert len(digest) == 64  # SHA-256 hex digest
    assert all(c in "0123456789abcdef" for c in digest)


def test_lookup_fresh_when_hash_matches(melee_root: Path) -> None:
    """Fix B: lookup() uses the hash sidecar when present.

    mtime bumped but content unchanged → fresh (no stale warning).
    This is the scenario that broke after enumerate-decl-orders, tier3-search,
    or verify-perm restored the original source (updating mtime even though
    the file bytes are identical).
    """
    src = melee_root / "src" / "melee" / "mn" / "mnvibration.c"
    src.write_text("// original source content")

    cache = cache_path(melee_root, "melee/mn/mnvibration")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("Starting function ...")

    # Write the hash sidecar (records the current source digest).
    write_hash_sidecar(cache, src)

    # Simulate a tool that restores the source (touching mtime) but leaves
    # the CONTENT unchanged — the classic false-stale scenario.
    time.sleep(0.05)
    src.write_text("// original source content")  # same bytes, new mtime
    assert src.stat().st_mtime > cache.stat().st_mtime, (
        "Precondition: source mtime must be newer than cache to trigger "
        "the old false-stale path"
    )

    entry = lookup(melee_root, "melee/mn/mnvibration")
    assert entry is not None
    assert entry.fresh is True, (
        "Entry must be fresh because source CONTENT is unchanged "
        "(mtime newer is a false alarm from restore-after-patch)"
    )


def test_lookup_stale_when_hash_differs(melee_root: Path) -> None:
    """Fix B: lookup() reports stale when source content actually changed."""
    src = melee_root / "src" / "melee" / "mn" / "mnvibration.c"
    src.write_text("// original content")

    cache = cache_path(melee_root, "melee/mn/mnvibration")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("Starting function ...")

    # Record hash of the ORIGINAL source.
    write_hash_sidecar(cache, src)

    # Now the user actually edits the source.
    src.write_text("// CHANGED content")

    entry = lookup(melee_root, "melee/mn/mnvibration")
    assert entry is not None
    assert entry.fresh is False, (
        "Entry must be stale because source content has genuinely changed"
    )


def test_lookup_mtime_fallback_when_no_sidecar(melee_root: Path) -> None:
    """Fix B backward-compat: no sidecar → mtime comparison is used."""
    src = melee_root / "src" / "melee" / "mn" / "mnvibration.c"
    src.write_text("// original")
    time.sleep(0.02)

    cache = cache_path(melee_root, "melee/mn/mnvibration")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("Starting function ...")
    # Deliberately do NOT write a hash sidecar.

    entry = lookup(melee_root, "melee/mn/mnvibration")
    assert entry is not None
    # Cache was written AFTER the source → mtime says fresh.
    assert entry.fresh is True


def test_lookup_fresh_after_rename_with_utime(melee_root: Path) -> None:
    """Simulate the pcdump-local rename path: a temp file created before a
    source edit is renamed to the cache. Without an explicit os.utime() call
    the cache mtime stays at pre-edit time, causing a false stale report.
    With os.utime() the mtime is bumped to now and the entry should be fresh.
    """
    import os

    src = melee_root / "src" / "melee" / "mn" / "mnvibration.c"
    src.write_text("// original")

    # Simulate temp pcdump created BEFORE source edit
    tmp = melee_root / "pcdump_tmp.txt"
    tmp.write_text("Starting function ...")
    old_tmp_mtime = tmp.stat().st_mtime

    time.sleep(0.05)

    # Source is saved/touched after pcdump started (ninja or user edit)
    src.write_text("// updated")

    time.sleep(0.01)

    # Rename to cache (preserves old mtime — this is the bug scenario)
    cache = cache_path(melee_root, "melee/mn/mnvibration")
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp.rename(cache)

    # Without utime: cache has old mtime → stale
    entry_before_utime = lookup(melee_root, "melee/mn/mnvibration")
    assert entry_before_utime is not None
    assert entry_before_utime.fresh is False, (
        "Expected stale before utime (rename preserves old mtime)"
    )

    # Apply the fix: touch mtime to now
    os.utime(cache, None)

    entry_after_utime = lookup(melee_root, "melee/mn/mnvibration")
    assert entry_after_utime is not None
    assert entry_after_utime.fresh is True, (
        "Expected fresh after os.utime() bumps cache mtime to now"
    )
