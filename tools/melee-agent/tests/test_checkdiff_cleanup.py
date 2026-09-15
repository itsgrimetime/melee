from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKDIFF_PATH = REPO_ROOT / "tools" / "checkdiff.py"


def _load_checkdiff():
    spec = importlib.util.spec_from_file_location(
        "checkdiff_cleanup_under_test", CHECKDIFF_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checkdiff():
    return _load_checkdiff()


def test_cleanup_skips_no_build_invocations(checkdiff, monkeypatch):
    monkeypatch.setattr(
        checkdiff.shutil,
        "which",
        lambda _name: pytest.fail("--no-build must not look up killall"),
    )

    checkdiff._cleanup_wine_preloader(no_build=True)


def test_cleanup_skips_when_killall_is_unavailable(checkdiff, monkeypatch):
    monkeypatch.setattr(checkdiff.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        checkdiff.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("missing killall must not be invoked"),
    )

    checkdiff._cleanup_wine_preloader(no_build=False)


def test_cleanup_ignores_utility_disappearing_after_lookup(checkdiff, monkeypatch):
    monkeypatch.setattr(checkdiff.shutil, "which", lambda _name: "/usr/bin/killall")

    def missing_utility(*_args, **_kwargs):
        raise FileNotFoundError("killall disappeared")

    monkeypatch.setattr(checkdiff.subprocess, "run", missing_utility)

    checkdiff._cleanup_wine_preloader(no_build=False)


def test_cleanup_runs_available_killall_best_effort(checkdiff, monkeypatch):
    calls = []
    monkeypatch.setattr(checkdiff.shutil, "which", lambda _name: "/usr/bin/killall")
    monkeypatch.setattr(
        checkdiff.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    checkdiff._cleanup_wine_preloader(no_build=False)

    assert calls == [
        (
            ["/usr/bin/killall", "wine-preloader"],
            {"capture_output": True, "check": False},
        )
    ]
