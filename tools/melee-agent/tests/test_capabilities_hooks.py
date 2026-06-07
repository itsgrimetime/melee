# tools/melee-agent/tests/test_capabilities_hooks.py
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EMIT = REPO / ".claude/hooks/emit-capabilities-context.py"


def _run(args, briefdir):
    return subprocess.run(
        [sys.executable, str(EMIT), *args],
        capture_output=True, text=True,
        env={"CAPABILITIES_BRIEF_DIR": str(briefdir), "PATH": "/usr/bin:/bin"},
    )


def test_emitter_outputs_valid_json_with_tricky_brief(tmp_path):
    (tmp_path / "capabilities-brief.md").write_text('Has "quotes", `backticks`,\nand newlines.')
    res = _run([], tmp_path)
    assert res.returncode == 0
    obj = json.loads(res.stdout)  # must be valid JSON despite tricky chars
    assert obj["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "backticks" in obj["hookSpecificOutput"]["additionalContext"]


def test_emitter_degrades_when_brief_missing(tmp_path):
    res = _run([], tmp_path)  # no brief file present
    assert res.returncode == 0
    obj = json.loads(res.stdout)
    # Still emits the nudge even without a brief.
    assert "capabilities search" in obj["hookSpecificOutput"]["additionalContext"]


def test_emitter_includes_remote_notice(tmp_path):
    (tmp_path / "capabilities-brief.md").write_text("brief body")
    res = _run(["--remote"], tmp_path)
    obj = json.loads(res.stdout)
    assert "REMOTE ENVIRONMENT" in obj["hookSpecificOutput"]["additionalContext"]
