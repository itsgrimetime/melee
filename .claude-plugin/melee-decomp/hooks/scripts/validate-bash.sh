#!/bin/bash
# PreToolUse hook for Bash commands
# Blocks wrong build tools and serializes ninja builds.
#
# Exit codes:
#   0 = allow (optionally with updatedInput for ninja wrapping)
#   2 = deny (with reason)

set -euo pipefail

# Read tool input from stdin into a temp file for safe processing
TMPFILE=$(mktemp)
trap "rm -f $TMPFILE" EXIT
cat > "$TMPFILE"

COMMAND=$(python3 -c "import sys,json; print(json.load(open(sys.argv[1])).get('tool_input',{}).get('command',''))" "$TMPFILE" 2>/dev/null || echo "")

if [ -z "$COMMAND" ]; then
    exit 0
fi

STRIPPED=$(echo "$COMMAND" | sed 's/^[[:space:]]*//')

# --- Block direct wine/wibo/objdiff-cli usage ---
if echo "$STRIPPED" | grep -qE '(^|&&|\|\||;)\s*(wine|wibo|wine-preloader)\b'; then
    echo '{"decision":"block","reason":"Do not invoke wine/wibo directly. Use tools/checkdiff.py instead."}'
    exit 2
fi

if echo "$STRIPPED" | grep -qE '(^|&&|\|\||;)\s*objdiff-cli\b'; then
    echo '{"decision":"block","reason":"Do not invoke objdiff-cli directly. Use tools/checkdiff.py instead."}'
    exit 2
fi

# --- Wrap ninja commands with build lock ---
if echo "$STRIPPED" | grep -qE '(^|&&|\|\||;)\s*ninja\b'; then
    python3 -c "
import json, sys

with open(sys.argv[1]) as f:
    original_input = json.load(f)

tool_input = original_input.get('tool_input', {})
cmd = tool_input.get('command', '')

lock_dir = '/tmp/melee-build.lock'
# Escape single quotes in original command for bash -c wrapping
escaped_cmd = cmd.replace(\"'\", \"'\\\"'\\\"'\")
wrapped = f\"bash -c 'while ! mkdir {lock_dir} 2>/dev/null; do sleep 3; done; trap \\\"rmdir {lock_dir} 2>/dev/null\\\" EXIT; {escaped_cmd}'\"

tool_input['command'] = wrapped
print(json.dumps({'decision': 'allow', 'updatedInput': tool_input}))
" "$TMPFILE"
    exit 0
fi

# --- Allow everything else ---
exit 0
