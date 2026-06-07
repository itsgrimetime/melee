#!/usr/bin/env python3
"""PreToolUse hook: nudge to search capabilities before creating a new tool
file (a .py/.sh under tools/). Non-blocking — emits additionalContext only."""
import json
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("tool_name") not in ("Write", "Edit"):
        return 0
    path = str((data.get("tool_input") or {}).get("file_path", "")).replace("\\", "/")
    if "tools/" not in path or not path.endswith((".py", ".sh")):
        return 0
    if "/tests/" in path or "capabilities" in path:
        return 0
    ctx = (
        "About to write a file under tools/. Before building new tooling, run "
        "`melee-agent capabilities search <task>` — an equivalent may already "
        "exist (150+ subcommands, ~20 skills)."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": ctx,
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
