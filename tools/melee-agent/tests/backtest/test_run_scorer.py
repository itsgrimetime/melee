import json
from pathlib import Path
from src.backtest import run as R


def test_run_checkdiff_at_parses_json(monkeypatch):
    payload = {"function": "f", "match": True, "fuzzy_match_percent": 100.0,
               "classification": {"structural_truth_gate": {"normalized_diff_lines": 0, "status": "structural-match"}}}
    class P: returncode = 0; stdout = json.dumps(payload); stderr = ""
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: P())
    out = R.run_checkdiff_at("/repo", "f")
    assert out["fuzzy_match_percent"] == 100.0


def test_run_checkdiff_uses_required_flags_and_env(monkeypatch):
    seen = {}
    class P: returncode = 1; stdout = '{"fuzzy_match_percent": 99.9, "classification": {"structural_truth_gate": {"normalized_diff_lines": 3}}}'; stderr = ""
    def fake_run(cmd, **kw):
        seen["cmd"] = cmd; seen["env"] = kw["env"]; seen["cwd"] = kw["cwd"]; return P()
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    R.run_checkdiff_at("/repo", "grIceMt_801F9ACC")
    assert seen["cmd"][1:] == ["tools/checkdiff.py", "grIceMt_801F9ACC", "--format", "json", "--no-tty"]
    assert seen["env"]["CHECKDIFF_NO_LOCK"] == "1" and seen["env"]["CHECKDIFF_NO_FINGERPRINT"] == "1"
    assert seen["cwd"] == "/repo"


def test_score_at_commit_uses_provision(monkeypatch, tmp_path):
    from src.backtest import run as R
    calls = {}
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: type("P",(),{"returncode":0,"stdout":"","stderr":""})())
    monkeypatch.setattr("src.backtest.provision.provision_worktree", lambda *a, **k: calls.setdefault("prov", True))
    monkeypatch.setattr(R, "run_checkdiff_at", lambda sb, fn, timeout=600: {"fuzzy_match_percent": 100.0, "classification": {"structural_truth_gate": {"normalized_diff_lines": 0}}})
    pct, ndl = R.score_at_commit("/main", "fn", "abc123", scratch_root=tmp_path)
    assert calls.get("prov") and pct == 100.0 and ndl == 0
