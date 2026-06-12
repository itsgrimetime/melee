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
