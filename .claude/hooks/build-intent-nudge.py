#!/usr/bin/env python3
"""UserPromptSubmit hook: when a prompt expresses build-intent, inject a
non-blocking reminder to search existing capabilities first."""
import json
import re
import sys

BUILD_INTENT = re.compile(
    r"\b(build|create|write|implement|add|make|develop)\b.{0,40}?"
    r"\b(tool|script|command|cli|utility|helper|wrapper|sub-?command|integration)\b",
    re.IGNORECASE | re.DOTALL,
)

CONTEXT = (
    "Build-intent detected. Before building, run "
    "`melee-agent capabilities search <task>` — an equivalent CLI command or "
    "skill may already exist (this repo has 150+ subcommands and ~20 skills). "
    "Past sessions wasted hours rebuilding mwcc-inspector and a permuter scorer "
    "(`debug target score-source`) that already existed."
)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    prompt = str(data.get("prompt", ""))
    if not BUILD_INTENT.search(prompt):
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": CONTEXT,
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
