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

# Check if wibo can run in this environment (requires modify_ldt syscall)
check_wibo_support() {
    if [ -f "build/tools/wibo" ]; then
        # Test if wibo can run without segfaulting
        if ! timeout 5 build/tools/wibo --version >/dev/null 2>&1; then
            return 1
        fi
    fi
    return 0
}

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

    # Check if wibo works after bootstrap
    if ! check_wibo_support; then
        echo "" >&2
        echo "WARNING: Container security restrictions prevent full compilation." >&2
        echo "  - wibo (Windows emulator for mwcc) cannot run (modify_ldt blocked)" >&2
        echo "  - decomp.me is behind Cloudflare protection" >&2
        echo "" >&2
        echo "AVAILABLE IN THIS ENVIRONMENT:" >&2
        echo "  - Read/analyze source in src/melee/ and include/melee/" >&2
        echo "  - View target assembly: build/tools/dtk elf disasm build/GALE01/obj/<path>.o" >&2
        echo "  - Edit C source files for decompilation" >&2
        echo "  - Use objdiff-cli for assembly comparison (if objects exist)" >&2
        echo "" >&2
        echo "NOT AVAILABLE:" >&2
        echo "  - Compiling C code to verify matches" >&2
        echo "  - python tools/checkdiff.py (requires compilation)" >&2
        echo "" >&2
    fi
fi

# Output workflow context for Claude
cat << 'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "REMOTE ENVIRONMENT DETECTED\n\nCompilation is LIMITED (wibo blocked by container security).\n\nWORKING:\n- View target assembly: build/tools/dtk elf disasm build/GALE01/obj/<path>.o /tmp/out.s\n- Build context files: ninja build/GALE01/src/<path>.ctx\n- Read/edit source: src/melee/, include/melee/\n- Reference objects exist in build/GALE01/obj/\n\nNOT WORKING:\n- Compiling C code (requires mwcc via wibo)\n- checkdiff.py, ninja <path>.o targets"
  }
}
EOF

exit 0
