import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from tools.mwcc_retro import setup as rs  # noqa: E402


def test_clone_pinned_raises_on_wrong_head(monkeypatch, tmp_path):
    dest = tmp_path / "repo"
    calls = []

    def fake_run(cmd, cwd=None):
        calls.append(cmd)
        if "rev-parse" in cmd:
            return "deadbeef\n"  # never matches the pin
        return ""

    monkeypatch.setattr(rs, "_run", fake_run)
    with pytest.raises(rs.SetupError):
        rs._clone_pinned("https://x/y", "branch", "PINSHA", dest)


def test_clone_pinned_skips_when_already_at_pin(monkeypatch, tmp_path):
    dest = tmp_path / "repo"
    dest.mkdir()
    monkeypatch.setattr(rs, "_run", lambda cmd, cwd=None: "PINSHA\n")
    # Already at pin -> returns without cloning (no exception).
    rs._clone_pinned("https://x/y", "branch", "PINSHA", dest)


def test_setup_error_is_runtimeerror():
    assert issubclass(rs.SetupError, RuntimeError)


def test_setup_preflights_missing_cmake_before_cargo_build(monkeypatch, tmp_path):
    vendor = tmp_path / "vendor"
    cargo_builds: list[list[str]] = []

    def fake_clone(_repo, _branch, _pin, dest):
        dest.mkdir(parents=True)
        if dest.name == "mwcc-debugger":
            (dest / "mwcc_debugger.py").write_text("# fake cadmic\n")

    def fake_run(cmd, cwd=None):
        if cmd[:2] == ["cargo", "build"]:
            cargo_builds.append(cmd)
            raise AssertionError("cargo build should not start without cmake")
        return ""

    def fake_which(name):
        if name == "cmake":
            return None
        return f"/usr/bin/{name}"

    monkeypatch.setattr(rs, "_clone_pinned", fake_clone)
    monkeypatch.setattr(rs, "_run", fake_run)
    monkeypatch.setattr(rs.shutil, "which", fake_which)
    monkeypatch.setattr(
        rs,
        "_retrowin32_binary",
        lambda repo_dir: repo_dir / "target" / "lto" / "retrowin32",
    )

    with pytest.raises(rs.SetupError) as excinfo:
        rs._ensure_in_vendor(vendor)

    message = str(excinfo.value)
    assert "cmake" in message
    assert "brew install cmake" in message
    assert "retrowin32" in message
    assert cargo_builds == []
