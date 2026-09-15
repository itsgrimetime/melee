from __future__ import annotations

import os
import time
from pathlib import Path

from src.mwcc_debug import temp_scratch


def test_reaped_scratch_root_removes_stale_entries_and_caps_size(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "scratch"
    monkeypatch.setenv("MWCC_DEBUG_TMP_ROOT", str(root))
    monkeypatch.setenv("MWCC_DEBUG_TMP_MAX_AGE_SECONDS", "60")
    monkeypatch.setenv("MWCC_DEBUG_TMP_MAX_BYTES", "16")
    monkeypatch.setenv("MWCC_DEBUG_TMP_ACTIVE_GRACE_SECONDS", "0")

    old_file = root / "old.txt"
    old_dir = root / "old-dir"
    fresh_a = root / "fresh-a.txt"
    fresh_b = root / "fresh-b.txt"
    old_dir.mkdir(parents=True)
    old_file.write_text("old")
    (old_dir / "nested.txt").write_text("old")
    fresh_a.write_text("a" * 12)
    fresh_b.write_text("b" * 12)

    now = time.time()
    os.utime(old_file, (now - 120, now - 120))
    os.utime(old_dir / "nested.txt", (now - 120, now - 120))
    os.utime(old_dir, (now - 120, now - 120))
    os.utime(fresh_a, (now - 30, now - 30))
    os.utime(fresh_b, (now - 10, now - 10))

    assert temp_scratch.reaped_scratch_root(now=now) == root

    assert not old_file.exists()
    assert not old_dir.exists()
    assert not fresh_a.exists()
    assert fresh_b.exists()


def test_reaped_scratch_root_removes_stale_legacy_top_level_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "scratch"
    legacy = tmp_path / "pcdump_forced_123_456.txt"
    legacy.write_text("leaked")
    now = time.time()
    os.utime(legacy, (now - 120, now - 120))

    monkeypatch.setenv("MWCC_DEBUG_TMP_ROOT", str(root))
    monkeypatch.setenv("MWCC_DEBUG_TMP_MAX_AGE_SECONDS", "60")

    temp_scratch.reaped_scratch_root(now=now)

    assert not legacy.exists()
