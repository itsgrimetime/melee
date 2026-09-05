# tools/melee-agent/tests/backtest/test_sandbox.py
import pytest
from src.backtest.sandbox import assert_commit_absent, LeakError

class FakeProc:
    def __init__(self, rc, out=""): self.returncode = rc; self.stdout = out; self.stderr = ""

def test_assert_commit_absent_passes_when_object_missing(monkeypatch):
    import src.backtest.sandbox as S
    def fake_run(cmd, **kw):
        if "cat-file" in cmd: return FakeProc(1)            # object absent -> good
        if "rev-list" in cmd: return FakeProc(0, "13ccea114\n")  # C not present
        return FakeProc(0)
    monkeypatch.setattr(S.subprocess, "run", fake_run)
    assert_commit_absent("/sandbox", "3ce0722cd" * 4 + "abcd")  # no raise

def test_assert_commit_absent_raises_when_present(monkeypatch):
    import src.backtest.sandbox as S
    def fake_run(cmd, **kw):
        if "cat-file" in cmd: return FakeProc(0)            # object PRESENT -> leak
        return FakeProc(0)
    monkeypatch.setattr(S.subprocess, "run", fake_run)
    with pytest.raises(LeakError):
        assert_commit_absent("/sandbox", "3ce0722cd" * 4 + "abcd")

def test_assert_commit_absent_raises_when_reachable_via_ref(monkeypatch):
    import src.backtest.sandbox as S
    c = "3ce0722cd" * 4 + "abcd"  # full 40-char sha used by the other tests
    def fake_run(cmd, **kw):
        if "cat-file" in cmd: return FakeProc(1)            # object reported absent
        if "rev-list" in cmd: return FakeProc(0, c + "\n")  # but still reachable from a ref
        return FakeProc(0)
    monkeypatch.setattr(S.subprocess, "run", fake_run)
    with pytest.raises(LeakError):
        assert_commit_absent("/sandbox", c)


def test_build_sandbox_provisions_and_checks_absence(monkeypatch, tmp_path):
    import src.backtest.sandbox as S
    state = {"git": [], "absent": False, "provision": False}
    monkeypatch.setattr(S, "_git", lambda repo, args, check=True: state["git"].append(" ".join(args)))
    monkeypatch.setattr(S, "assert_commit_absent", lambda repo, c: state.__setitem__("absent", True))
    monkeypatch.setattr("src.backtest.provision.provision_worktree",
                        lambda workdir, *, main_repo, **k: state.__setitem__("provision", True))
    S.build_sandbox(main_repo="/main", c_sha="C"*40, cprev_sha="P"*40, dest=tmp_path/"sb")
    assert any("PPPP" in g for g in (x.replace("P"*40,"PPPP") for x in state["git"]))  # cprev fetched
    assert state["absent"] is True and state["provision"] is True
