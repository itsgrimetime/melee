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


# --- Task 9: UserPromptSubmit nudge hook ---

NUDGE_HOOK = REPO / ".claude/hooks/build-intent-nudge.py"


def _run_nudge(prompt):
    return subprocess.run(
        [sys.executable, str(NUDGE_HOOK)],
        input=json.dumps({"prompt": prompt}),
        capture_output=True, text=True,
    )


def test_nudge_fires_on_build_intent():
    res = _run_nudge("Let's build a new tool to score permuter candidates")
    assert res.returncode == 0
    obj = json.loads(res.stdout)
    assert "capabilities search" in obj["hookSpecificOutput"]["additionalContext"]


def test_nudge_silent_on_ordinary_prompt():
    res = _run_nudge("Match function ftCo_8009C744 in ftcollision.c")
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_nudge_tolerates_bad_stdin():
    res = subprocess.run([sys.executable, str(NUDGE_HOOK)], input="not json",
                         capture_output=True, text=True)
    assert res.returncode == 0
    assert res.stdout.strip() == ""


# --- Task 9: PreToolUse nudge hook ---

TOOLUSE_HOOK = REPO / ".claude/hooks/build-intent-tooluse-nudge.py"


def _run_tooluse(tool, file_path):
    return subprocess.run(
        [sys.executable, str(TOOLUSE_HOOK)],
        input=json.dumps({"tool_name": tool, "tool_input": {"file_path": file_path}}),
        capture_output=True, text=True,
    )


def test_tooluse_fires_on_new_tool_file():
    res = _run_tooluse("Write", "tools/melee-agent/src/cli/myscorer.py")
    obj = json.loads(res.stdout)
    assert obj["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "capabilities search" in obj["hookSpecificOutput"]["additionalContext"]


def test_tooluse_silent_on_non_tool_paths():
    assert _run_tooluse("Write", "src/melee/mn/mnvibration.c").stdout.strip() == ""
    assert _run_tooluse("Write", "tools/melee-agent/tests/test_x.py").stdout.strip() == ""
    assert _run_tooluse("Read", "tools/melee-agent/src/cli/foo.py").stdout.strip() == ""
