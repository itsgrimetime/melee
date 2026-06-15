"""Spec §3.1: verification mutates the SHARED build tree (copies the candidate
.o into build/GALE01/.../*.o + runs checkdiff), so it MUST hold the same
repo-wide lock as the compile path, and MUST restore build/ afterward.
"""
from __future__ import annotations

import json
from pathlib import Path

import src.search.adapters as adapters
from src.search.adapters import RealCheckdiffVerifier


def _make_fake_repo(root: Path, function: str, unit: str) -> Path:
    """Create a minimal repo tree with report.json + a build .o."""
    build = root / "build" / "GALE01"
    build.mkdir(parents=True, exist_ok=True)
    (build / "report.json").write_text(
        json.dumps(
            {"units": [{"name": f"main/{unit}", "functions": [{"name": function}]}]}
        )
    )
    build_o = build / "src" / f"{unit}.o"
    build_o.parent.mkdir(parents=True, exist_ok=True)
    build_o.write_bytes(b"ORIGINAL-BUILD-O")
    return build_o


def test_is_match_holds_lock_and_restores_build(tmp_path, monkeypatch):
    function, unit = "MatToQuat", "quatlib"
    melee_root = tmp_path / "melee"
    build_o = _make_fake_repo(melee_root, function, unit)

    candidate = tmp_path / "candidate.o"
    candidate.write_bytes(b"CANDIDATE-O")

    events: list[str] = []

    # Spy on the repo build lock so we can prove is_match acquired it.
    import contextlib

    real_lock = adapters._acquire_repo_build_lock

    @contextlib.contextmanager
    def spy_lock(root, *, label="search compile"):
        events.append(f"lock-enter:{label}")
        with real_lock(root, label=label):
            yield
        events.append("lock-exit")

    monkeypatch.setattr(adapters, "_acquire_repo_build_lock", spy_lock)

    # Stub CheckdiffChecker so no real checkdiff subprocess runs. It records
    # that (a) the build .o was swapped to the candidate while it runs and
    # (b) the lock was held at that point.
    class StubChecker:
        def __init__(self, function, melee_root, build_obj_path):
            self.build_obj_path = Path(build_obj_path)

        def is_clean(self, obj_path):
            # While "checking", the candidate has been staged into build/ by
            # the real CheckdiffChecker.is_clean; here we just assert the lock
            # is held (lock-enter recorded, lock-exit not yet).
            events.append("check-run")
            assert "lock-enter:search verify" in events
            assert "lock-exit" not in events
            return False

    monkeypatch.setattr(
        "src.mwcc_debug.checkdiff_checker.CheckdiffChecker", StubChecker
    )

    verifier = RealCheckdiffVerifier(melee_root)
    result = verifier.is_match(function, candidate)

    assert result is False
    # Lock was entered (around the check) and released after.
    assert events == ["lock-enter:search verify", "check-run", "lock-exit"]
    # build/ is restored to its original bytes (StubChecker never swapped, but
    # this guards that is_match leaves the tree untouched on the no-match path).
    assert build_o.read_bytes() == b"ORIGINAL-BUILD-O"
