#!/bin/bash
#
# Session startup hook for Melee decompilation project.
# Only runs in remote/containerized environments (Claude Code web).
#

set -e

# Only run in remote Claude Code environment
if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Check if bootstrap is needed (main.dol missing or build not done)
NEEDS_BOOTSTRAP=false

if [ ! -f "orig/GALE01/sys/main.dol" ]; then
    NEEDS_BOOTSTRAP=true
fi

if [ ! -f "build/GALE01/report.json" ]; then
    NEEDS_BOOTSTRAP=true
fi

if [ "$NEEDS_BOOTSTRAP" = "true" ]; then
    echo "Running bootstrap for remote environment..." >&2
    python tools/bootstrap.py 2>&1 || true
fi

# Output workflow context for Claude
cat << 'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "REMOTE ENVIRONMENT DETECTED - Function matching workflow:\n1. Edit source files in src/melee/\n2. Run: python tools/checkdiff.py <function_name>\n3. Iterate until 100% match\n\nNOTE: decomp.me is NOT available in this environment. Use checkdiff.py directly."
  }
}
EOF

exit 0
