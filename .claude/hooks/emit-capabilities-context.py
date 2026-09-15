#!/usr/bin/env python3
"""Print a SessionStart hookSpecificOutput JSON injecting the capabilities brief.

Called by session-startup.sh in ALL environments. json.dumps handles escaping.
Degrades gracefully: still emits the nudge if the brief is missing; the brief
dir can be overridden with CAPABILITIES_BRIEF_DIR (for tests)."""
import json
import os
import sys
from pathlib import Path

NUDGE = (
    "Before building any new tool, script, or CLI command, run "
    "`melee-agent capabilities search <task>` first — this repo has 150+ "
    "subcommands and ~20 skills; your need may already exist."
)

REMOTE_NOTICE = (
    "REMOTE ENVIRONMENT DETECTED\n\n"
    "Compilation is LIMITED (wibo blocked by container security).\n"
    "WORKING: view target asm via dtk; build .ctx files; read/edit src.\n"
    "NOT WORKING: compiling C (mwcc via wibo), checkdiff.py."
)


def _brief_dir() -> Path:
    override = os.environ.get("CAPABILITIES_BRIEF_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / ".claude"


def main() -> int:
    parts = [NUDGE]
    brief = _brief_dir() / "capabilities-brief.md"
    if brief.exists():
        parts.append(brief.read_text(encoding="utf-8", errors="replace").strip())
    if "--remote" in sys.argv:
        parts.append(REMOTE_NOTICE)
    context = "\n\n".join(p for p in parts if p)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
