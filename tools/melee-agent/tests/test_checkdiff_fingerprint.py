"""Integration tests for the fingerprint hooks in tools/checkdiff.py."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKDIFF = _REPO_ROOT / "tools" / "checkdiff.py"
_FIXTURES = Path(__file__).parent / "fixtures" / "fingerprint"


def _load_checkdiff():
    spec = importlib.util.spec_from_file_location("checkdiff", _CHECKDIFF)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["checkdiff"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def checkdiff():
    return _load_checkdiff()


def test_fingerprint_for_function_uses_src_path(checkdiff, tmp_path, monkeypatch):
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text(
        "void fn_alpha(int x) {\n"
        "    int y = x + 1;\n"
        "}\n"
    )

    monkeypatch.setattr(checkdiff, "SRC_ROOT", tmp_path / "src")
    fp = checkdiff.fingerprint_for_function("fn_alpha", "melee/mn/sample")
    assert fp is not None
    assert fp.raw
    assert "int y = x + 1;" in fp.body


def test_fingerprint_for_function_includes_file_local_context(checkdiff, tmp_path, monkeypatch):
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text(
        "typedef struct LocalData { int text[6]; } LocalData;\n"
        "void fn_alpha(int x) {\n"
        "    int y = x + 1;\n"
        "}\n"
    )

    _patch_paths(checkdiff, monkeypatch, tmp_path)
    before = checkdiff.fingerprint_for_function("fn_alpha", "melee/mn/sample")
    src.write_text(
        "typedef struct LocalData { int text[5]; } LocalData;\n"
        "void fn_alpha(int x) {\n"
        "    int y = x + 1;\n"
        "}\n"
    )
    after = checkdiff.fingerprint_for_function("fn_alpha", "melee/mn/sample")

    assert before is not None
    assert after is not None
    assert before.raw != after.raw


def test_fingerprint_for_function_includes_depfile_headers(checkdiff, tmp_path, monkeypatch):
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    header = tmp_path / "include" / "melee" / "mn" / "sample.h"
    depfile = tmp_path / "build" / "GALE01" / "src" / "melee" / "mn" / "sample.d"
    src.parent.mkdir(parents=True)
    header.parent.mkdir(parents=True)
    depfile.parent.mkdir(parents=True)
    src.write_text(
        '#include "melee/mn/sample.h"\n'
        "void fn_alpha(int x) {\n"
        "    int y = x + 1;\n"
        "}\n"
    )
    header.write_text("void helper(int);\n")
    depfile.write_text(
        "build/GALE01/src/melee/mn/sample.o: "
        "src/melee/mn/sample.c include/melee/mn/sample.h\n"
    )

    _patch_paths(checkdiff, monkeypatch, tmp_path)
    before = checkdiff.fingerprint_for_function("fn_alpha", "melee/mn/sample")
    header.write_text("int helper(int);\n")
    after = checkdiff.fingerprint_for_function("fn_alpha", "melee/mn/sample")

    assert before is not None
    assert after is not None
    assert before.raw != after.raw


def test_fingerprint_for_function_returns_none_for_missing_src(checkdiff, tmp_path, monkeypatch):
    monkeypatch.setattr(checkdiff, "SRC_ROOT", tmp_path / "src")
    fp = checkdiff.fingerprint_for_function("fn_alpha", "nonexistent")
    assert fp is None


def test_no_fingerprint_flag_parsed(checkdiff):
    """The argparse setup includes --no-fingerprint."""
    ap = checkdiff._build_arg_parser()
    actions = {opt for action in ap._actions for opt in action.option_strings}
    assert "--no-fingerprint" in actions


def test_no_fingerprint_env_var_recognized(checkdiff, monkeypatch):
    monkeypatch.setenv("CHECKDIFF_NO_FINGERPRINT", "1")
    assert checkdiff.fingerprint_disabled() is True
    monkeypatch.setenv("CHECKDIFF_NO_FINGERPRINT", "0")
    assert checkdiff.fingerprint_disabled() is False
    monkeypatch.delenv("CHECKDIFF_NO_FINGERPRINT", raising=False)
    assert checkdiff.fingerprint_disabled() is False


def test_classify_attempt_novel(checkdiff):
    branch = checkdiff.classify_attempt(prior=None, current_match=87.2)
    assert branch == "novel"


def test_classify_attempt_repeat_same_match(checkdiff):
    prior = {"match_percent": 87.2, "match_type": "raw"}
    branch = checkdiff.classify_attempt(prior=prior, current_match=87.2)
    assert branch == "repeat"


def test_classify_attempt_repeat_within_tolerance(checkdiff):
    prior = {"match_percent": 87.2, "match_type": "raw"}
    branch = checkdiff.classify_attempt(prior=prior, current_match=87.25)
    assert branch == "repeat"


def test_classify_attempt_divergent(checkdiff):
    prior = {"match_percent": 87.2, "match_type": "raw"}
    branch = checkdiff.classify_attempt(prior=prior, current_match=98.5)
    assert branch == "divergent"


def test_format_banner_repeat(checkdiff):
    prior = {
        "index": 5,
        "match_percent": 99.2,
        "classification": "register-allocation",
        "outcome": "reverted",
        "agent_id": "pid83109",
        "timestamp_utc": "2026-05-15T22:34:17+00:00",
        "note": "Tried assigning aligned_100 before width...",
        "replay_count": 28,
        "match_type": "raw",
    }
    banner = checkdiff.format_banner("repeat", "fn_8024E1B4", prior, current_match=99.2)
    assert "[REPEAT]" in banner
    assert "fn_8024E1B4" in banner
    assert "99.2" in banner
    assert "register-allocation" in banner
    assert "30th time" in banner  # replay_count=28 → next will be 30th


def test_format_banner_repeat_semantic(checkdiff):
    prior = {
        "index": 5, "match_percent": 99.2, "classification": "",
        "outcome": "neutral", "agent_id": "pid7842",
        "timestamp_utc": "2026-05-15T22:34:17+00:00", "note": "",
        "replay_count": 0, "match_type": "norm",
    }
    banner = checkdiff.format_banner("repeat", "fn_x", prior, current_match=99.2)
    assert "[REPEAT (semantic)]" in banner


def test_format_banner_divergent(checkdiff):
    prior = {
        "index": 5, "match_percent": 99.2, "classification": "",
        "outcome": "neutral", "agent_id": "pid7842",
        "timestamp_utc": "2026-05-15T22:34:17+00:00", "note": "",
        "replay_count": 0, "match_type": "raw",
    }
    banner = checkdiff.format_banner("divergent", "fn_x", prior,
                                     current_match=98.5,
                                     distinct_match_count=2)
    assert "[DIVERGENT REPEAT]" in banner
    assert "99.2" in banner
    assert "98.5" in banner
    assert "2 distinct match%s" in banner


def test_format_banner_divergent_mentions_dependency_context(checkdiff):
    prior = {
        "index": 5, "match_percent": 99.2, "classification": "",
        "outcome": "neutral", "agent_id": "pid7842",
        "timestamp_utc": "2026-05-15T22:34:17+00:00", "note": "",
        "replay_count": 0, "match_type": "raw",
    }

    banner = checkdiff.format_banner("divergent", "fn_x", prior,
                                     current_match=98.5,
                                     distinct_match_count=2)

    assert "dependency/header/source context may have changed" in banner
    assert "same source as attempt" not in banner
    assert "same function-body/dependency fingerprint" in banner


def test_emit_attempt_banner_flushes_stdout_before_stderr(checkdiff, monkeypatch):
    events: list[str] = []

    class FakeStdout:
        def flush(self) -> None:
            events.append("stdout.flush")

    class FakeStderr:
        def write(self, text: str) -> int:
            if text:
                events.append(f"stderr.write:{text.strip()}")
            return len(text)

        def flush(self) -> None:
            events.append("stderr.flush")

    monkeypatch.setattr(checkdiff.sys, "stdout", FakeStdout())
    monkeypatch.setattr(checkdiff.sys, "stderr", FakeStderr())

    checkdiff.emit_attempt_banner("[REPEAT] buffered output boundary")

    assert events[0] == "stdout.flush"
    assert any(
        event == "stderr.write:[REPEAT] buffered output boundary"
        for event in events[1:]
    )


def test_checkdiff_lock_is_repo_wide(checkdiff, tmp_path, monkeypatch):
    monkeypatch.setattr(checkdiff, "ROOT", tmp_path)

    first = checkdiff.checkdiff_lock_path("melee/mn/a")
    second = checkdiff.checkdiff_lock_path("melee/ft/b")

    assert first == second
    assert str(tmp_path) not in first.name


def test_checkdiff_no_build_skips_build_report_lock(checkdiff):
    ap = checkdiff._build_arg_parser()

    no_build_args = ap.parse_args(["fn_alpha", "--no-build", "--format", "json"])
    build_args = ap.parse_args(["fn_alpha", "--format", "json"])

    assert checkdiff.should_acquire_checkdiff_lock(no_build_args) is False
    assert checkdiff.should_acquire_checkdiff_lock(build_args) is True


def test_record_post_build_novel(checkdiff, tmp_path, monkeypatch):
    """Novel branch: writes a new ledger entry, no banner."""
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    monkeypatch.setattr(checkdiff, "ROOT", tmp_path)

    fp = checkdiff.Fingerprint(raw="abc111", normalized="def222",
                               body="int y = x;")
    msg = checkdiff.record_post_build_attempt(
        func_name="fn_alpha", obj_path="melee/mn/sample",
        fp=fp, prior_attempt=None,
        c_file=tmp_path / "src" / "melee" / "mn" / "sample.c",
        current_match=87.2,
    )
    data = json.loads(ledger.read_text())
    a = data["functions"]["fn_alpha"]["attempts"][0]
    assert a["fingerprint"] == "abc111"
    assert a["match_percent"] == 87.2
    assert a["replay_count"] == 0
    assert msg == ""


def test_record_post_build_repeat(checkdiff, tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    monkeypatch.setattr(checkdiff, "ROOT", tmp_path)

    fp = checkdiff.Fingerprint(raw="abc111", normalized="def222",
                               body="int y = x;")
    checkdiff.record_attempt(
        "fn_alpha", match_percent=87.2, outcome="neutral",
        fingerprint="abc111", fingerprint_norm="def222",
    )
    prior = checkdiff.find_attempt_by_fp("fn_alpha", "abc111", "def222")

    msg = checkdiff.record_post_build_attempt(
        func_name="fn_alpha", obj_path="melee/mn/sample",
        fp=fp, prior_attempt=prior,
        c_file=tmp_path / "src" / "melee" / "mn" / "sample.c",
        current_match=87.2,
    )
    data = json.loads(ledger.read_text())
    assert len(data["functions"]["fn_alpha"]["attempts"]) == 1
    assert data["functions"]["fn_alpha"]["attempts"][0]["replay_count"] == 1
    assert "[REPEAT]" in msg
    assert "2nd time" in msg


def test_record_post_build_divergent(checkdiff, tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    monkeypatch.setattr(checkdiff, "ROOT", tmp_path)

    fp = checkdiff.Fingerprint(raw="abc111", normalized="def222",
                               body="int y = x;")
    checkdiff.record_attempt(
        "fn_alpha", match_percent=87.2, outcome="neutral",
        fingerprint="abc111", fingerprint_norm="def222",
    )
    prior = checkdiff.find_attempt_by_fp("fn_alpha", "abc111", "def222")

    msg = checkdiff.record_post_build_attempt(
        func_name="fn_alpha", obj_path="melee/mn/sample",
        fp=fp, prior_attempt=prior,
        c_file=tmp_path / "src" / "melee" / "mn" / "sample.c",
        current_match=98.5,
    )
    data = json.loads(ledger.read_text())
    attempts = data["functions"]["fn_alpha"]["attempts"]
    assert len(attempts) == 2
    assert attempts[1]["match_percent"] == 98.5
    assert attempts[0]["fingerprint"] == attempts[1]["fingerprint"]
    assert "[DIVERGENT REPEAT]" in msg
    assert "2 distinct match%s" in msg


def test_record_post_build_clamps_out_of_range_match(checkdiff, tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    monkeypatch.setattr(checkdiff, "ROOT", tmp_path)

    fp = checkdiff.Fingerprint(raw="abc111", normalized="def222",
                               body="int y = x;")
    msg = checkdiff.record_post_build_attempt(
        func_name="fn_alpha", obj_path="melee/mn/sample",
        fp=fp, prior_attempt=None,
        c_file=tmp_path / "src" / "melee" / "mn" / "sample.c",
        current_match=150.0,
    )
    data = json.loads(ledger.read_text())
    a = data["functions"]["fn_alpha"]["attempts"][0]
    assert a["match_percent"] == 100.0


def test_record_post_build_handles_negative_match(checkdiff, tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    monkeypatch.setattr(checkdiff, "ROOT", tmp_path)

    fp = checkdiff.Fingerprint(raw="abc111", normalized="def222",
                               body="int y = x;")
    checkdiff.record_post_build_attempt(
        func_name="fn_alpha", obj_path="melee/mn/sample",
        fp=fp, prior_attempt=None,
        c_file=tmp_path / "src" / "melee" / "mn" / "sample.c",
        current_match=-3.0,
    )
    data = json.loads(ledger.read_text())
    a = data["functions"]["fn_alpha"]["attempts"][0]
    assert a["match_percent"] == 0.0


def _make_stub_repo(tmp_path: Path, fn_name: str, match_pct: float,
                    body: str = "int y = x + 1;\n") -> Path:
    (tmp_path / "src" / "melee" / "mn").mkdir(parents=True)
    (tmp_path / "src" / "melee" / "mn" / "sample.c").write_text(
        f"void {fn_name}(int x) {{\n    {body}}}\n"
    )
    (tmp_path / "build" / "GALE01").mkdir(parents=True)
    (tmp_path / "build" / "GALE01" / "report.json").write_text(json.dumps({
        "units": [{
            "name": "main/melee/mn/sample",
            "functions": [{"name": fn_name, "fuzzy_match_percent": match_pct}],
        }],
    }))
    return tmp_path


def _patch_paths(checkdiff, monkeypatch, tmp_path):
    monkeypatch.setattr(checkdiff, "ROOT", tmp_path)
    monkeypatch.setattr(checkdiff, "SRC_ROOT", tmp_path / "src")
    monkeypatch.setattr(checkdiff, "REPORT_PATH",
                        tmp_path / "build" / "GALE01" / "report.json")


def test_dry_run_does_not_invoke_subprocess(checkdiff, tmp_path, monkeypatch):
    _make_stub_repo(tmp_path, "fn_alpha", match_pct=87.2)
    _patch_paths(checkdiff, monkeypatch, tmp_path)
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    monkeypatch.setattr(sys, "argv",
                        ["checkdiff.py", "fn_alpha", "--dry-run", "--no-tty"])

    def _fail(*args, **kwargs):
        raise AssertionError(f"--dry-run must not invoke subprocess: {args!r}")

    monkeypatch.setattr(checkdiff.subprocess, "run", _fail)
    rc = checkdiff.main()
    assert rc == 0


def test_dry_run_does_not_mutate_ledger(checkdiff, tmp_path, monkeypatch):
    _make_stub_repo(tmp_path, "fn_alpha", match_pct=87.2)
    _patch_paths(checkdiff, monkeypatch, tmp_path)
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    monkeypatch.setattr(sys, "argv",
                        ["checkdiff.py", "fn_alpha", "--dry-run", "--no-tty"])

    checkdiff.main()
    assert not ledger.exists()


def test_dry_run_exits_3_on_missing_report(checkdiff, tmp_path, monkeypatch):
    _make_stub_repo(tmp_path, "fn_alpha", match_pct=87.2)
    _patch_paths(checkdiff, monkeypatch, tmp_path)
    (tmp_path / "build" / "GALE01" / "report.json").unlink()
    monkeypatch.setattr(sys, "argv",
                        ["checkdiff.py", "fn_alpha", "--dry-run", "--no-tty"])
    rc = checkdiff.main()
    assert rc == 3


def test_dry_run_exits_3_on_unknown_function(checkdiff, tmp_path, monkeypatch):
    _make_stub_repo(tmp_path, "fn_alpha", match_pct=87.2)
    _patch_paths(checkdiff, monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["checkdiff.py", "fn_unknown", "--dry-run", "--no-tty"])
    rc = checkdiff.main()
    assert rc == 3


def test_dry_run_reports_banner_for_prior_attempt(checkdiff, tmp_path, monkeypatch, capsys):
    _make_stub_repo(tmp_path, "fn_alpha", match_pct=87.2)
    _patch_paths(checkdiff, monkeypatch, tmp_path)
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))

    fp = checkdiff.fingerprint_for_function("fn_alpha", "melee/mn/sample")
    assert fp is not None
    checkdiff.record_attempt(
        "fn_alpha", match_percent=87.2, outcome="neutral",
        fingerprint=fp.raw, fingerprint_norm=fp.normalized,
    )

    monkeypatch.setattr(sys, "argv",
                        ["checkdiff.py", "fn_alpha", "--dry-run", "--no-tty"])
    rc = checkdiff.main()
    err = capsys.readouterr().err
    assert rc == 0
    assert "[REPEAT]" in err


def test_dry_run_divergent_banner_includes_pending_in_count(checkdiff, tmp_path, monkeypatch, capsys):
    """--dry-run is read-only, but the divergent banner must still
    count the in-flight attempt's match% as a 'distinct' value."""
    _make_stub_repo(tmp_path, "fn_alpha", match_pct=98.5)
    _patch_paths(checkdiff, monkeypatch, tmp_path)
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))

    # Seed a prior attempt at 87.2 against the same source
    fp = checkdiff.fingerprint_for_function("fn_alpha", "melee/mn/sample")
    assert fp is not None
    checkdiff.record_attempt(
        "fn_alpha", match_percent=87.2, outcome="neutral",
        fingerprint=fp.raw, fingerprint_norm=fp.normalized,
    )

    # Dry-run: report.json now says 98.5, ledger says 87.2 → divergent
    monkeypatch.setattr(sys, "argv",
                        ["checkdiff.py", "fn_alpha", "--dry-run", "--no-tty"])
    rc = checkdiff.main()
    err = capsys.readouterr().err
    assert rc == 0
    assert "[DIVERGENT REPEAT]" in err
    assert "2 distinct match%s" in err  # 87.2 (in ledger) + 98.5 (pending) = 2


def test_no_build_json_suppresses_stale_report_match_percent(
    checkdiff, tmp_path, monkeypatch, capsys,
):
    _make_stub_repo(tmp_path, "fn_alpha", match_pct=27.27)
    _patch_paths(checkdiff, monkeypatch, tmp_path)
    ref_obj = tmp_path / "build" / "GALE01" / "obj" / "melee" / "mn" / "sample.o"
    our_obj = tmp_path / "build" / "GALE01" / "src" / "melee" / "mn" / "sample.o"
    ref_obj.parent.mkdir(parents=True)
    our_obj.parent.mkdir(parents=True)
    ref_obj.write_bytes(b"ref")
    our_obj.write_bytes(b"ours")

    objdump_output = (
        "00000000 <fn_alpha>:\n"
        "   0:\t4e 80 00 20\tblr\n"
    )

    def fake_run(cmd, **kwargs):
        if cmd[:1] == ["killall"]:
            return checkdiff.subprocess.CompletedProcess(cmd, 0, "", "")
        return checkdiff.subprocess.CompletedProcess(cmd, 0, objdump_output, "")

    monkeypatch.setattr(checkdiff, "ensure_disassembler", lambda: ("objdump", "objdump"))
    monkeypatch.setattr(checkdiff.subprocess, "run", fake_run)
    monkeypatch.setattr(checkdiff, "apply_name_magic_if_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        checkdiff,
        "collect_section_anchor_aliases",
        lambda path, peer_path=None: {},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "checkdiff.py",
            "fn_alpha",
            "--no-build",
            "--format",
            "json",
            "--no-fingerprint",
        ],
    )

    rc = checkdiff.main()
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["match"] is True
    assert payload["fuzzy_match_percent"] is None
    assert payload["fuzzy_match_percent_source"] == "suppressed_stale_report_no_build"


def test_no_build_json_falls_back_to_dtk_when_objdump_extracts_no_function(
    checkdiff, tmp_path, monkeypatch, capsys,
):
    _make_stub_repo(tmp_path, "fn_alpha", match_pct=27.27)
    _patch_paths(checkdiff, monkeypatch, tmp_path)
    ref_obj = tmp_path / "build" / "GALE01" / "obj" / "melee" / "mn" / "sample.o"
    our_obj = tmp_path / "build" / "GALE01" / "src" / "melee" / "mn" / "sample.o"
    ref_obj.parent.mkdir(parents=True)
    our_obj.parent.mkdir(parents=True)
    ref_obj.write_bytes(b"ref")
    our_obj.write_bytes(b"ours")

    def fake_run(cmd, **kwargs):
        exe = str(cmd[0])
        if exe.endswith("python") or exe.endswith("python3"):
            return checkdiff.subprocess.CompletedProcess(cmd, 0, "", "")
        if exe == "bad-objdump":
            return checkdiff.subprocess.CompletedProcess(cmd, 0, "", "")
        if exe == "dtk":
            Path(cmd[-1]).write_text(
                "# .text:0x0 | size: 0x4\n"
                ".fn fn_alpha, global\n"
                "/* 00000000 00000000  4E 80 00 20 */\tblr\n"
                ".endfn fn_alpha\n",
                encoding="utf-8",
            )
            return checkdiff.subprocess.CompletedProcess(cmd, 0, "", "")
        return checkdiff.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(
        checkdiff,
        "ensure_disassembler",
        lambda: ("objdump", Path("bad-objdump")),
    )
    monkeypatch.setattr(checkdiff, "find_dtk", lambda: Path("dtk"))
    monkeypatch.setattr(checkdiff.subprocess, "run", fake_run)
    monkeypatch.setattr(checkdiff, "apply_name_magic_if_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        checkdiff,
        "collect_section_anchor_aliases",
        lambda path, peer_path=None: {},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "checkdiff.py",
            "fn_alpha",
            "--no-build",
            "--format",
            "json",
            "--no-fingerprint",
        ],
    )

    rc = checkdiff.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert rc == 0
    assert payload["match"] is True
    assert "fell back to dtk" in captured.err


def test_record_post_build_returns_empty_string_for_none_fp(checkdiff, tmp_path, monkeypatch):
    """record_post_build_attempt must defend against fp=None even
    though the current caller guards — future-proofs new callers."""
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    monkeypatch.setattr(checkdiff, "ROOT", tmp_path)

    msg = checkdiff.record_post_build_attempt(
        func_name="fn_alpha", obj_path="melee/mn/sample",
        fp=None, prior_attempt=None,
        c_file=tmp_path / "src" / "melee" / "mn" / "sample.c",
        current_match=87.2,
    )
    assert msg == ""
    assert not ledger.exists()  # no write happened


def test_format_subprocess_failure_includes_command_and_cause(checkdiff):
    result = checkdiff.subprocess.CompletedProcess(
        ["ninja", "build/GALE01/report.json"],
        1,
        stdout="",
        stderr="ninja: error: loading 'build.ninja': No such file or directory\n",
    )

    message = checkdiff.format_subprocess_failure(
        "warning: failed to regenerate report.json",
        result,
    )

    assert "warning: failed to regenerate report.json" in message
    assert "command: ninja build/GALE01/report.json" in message
    assert "exit code: 1" in message
    assert "ninja: error: loading 'build.ninja'" in message
