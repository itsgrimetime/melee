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
