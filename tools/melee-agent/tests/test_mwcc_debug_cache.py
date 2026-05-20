"""Tests for the pcdump cache layer."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.mwcc_debug.cache import (
    CACHE_DIRNAME,
    cache_path,
    ensure_cache_dir,
    lookup,
    source_path,
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
