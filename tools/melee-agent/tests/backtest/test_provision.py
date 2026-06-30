# tests/backtest/test_provision.py
import subprocess
import pytest
from pathlib import Path
from src.backtest.provision import provision_worktree, ProvisionError


class Rec:
    def __init__(self): self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        return P()


def test_provision_runs_recipe_in_order(tmp_path, monkeypatch):
    rec = Rec()
    # main_repo="/main" doesn't exist -> the toolchain symlink loop is skipped (src.exists() False).
    monkeypatch.setattr("src.backtest.provision.Path.symlink_to", lambda *a, **k: None)
    monkeypatch.setattr("src.backtest.provision.Path.is_symlink", lambda self: False)
    provision_worktree(str(tmp_path / "wt"), main_repo="/main", runner=rec)
    joined = [" ".join(c) for c in rec.calls]
    assert any("checkout master -- tools" in j for j in joined)  # bootstrap
    assert any(j.endswith("configure.py") or "configure.py" in j for j in joined)
    assert any("ninja" in j and "report.json" in j for j in joined)  # report.json before checkdiff
    # configure precedes ninja report.json
    assert next(i for i, j in enumerate(joined) if "configure.py" in j) < \
           next(i for i, j in enumerate(joined) if "report.json" in j)


def test_provision_raises_on_failed_step(tmp_path, monkeypatch):
    def boom(cmd, **kw):
        class P:
            returncode = (1 if "configure.py" in " ".join(cmd) else 0)
            stdout = ""
            stderr = "cfg boom"

        return P()

    monkeypatch.setattr("src.backtest.provision.Path.symlink_to", lambda *a, **k: None)
    monkeypatch.setattr("src.backtest.provision.Path.is_symlink", lambda self: False)
    with pytest.raises(ProvisionError):
        provision_worktree(str(tmp_path / "wt"), main_repo="/main", runner=boom)
