#!/bin/bash
#
# Session startup hook for Melee decompilation project.
# Always injects the capabilities brief into session context (local and remote);
# additionally bootstraps the build environment in remote/containerized sessions.
#

set -e

if [ -n "$CLAUDE_PROJECT_DIR" ]; then
    cd "$CLAUDE_PROJECT_DIR"
else
    exit 0
fi

ensure_base_dol() {
    local dest="orig/GALE01/sys/main.dol"
    if [ -f "$dest" ]; then
        return 0
    fi

    local candidates=()
    if [ -n "$MELEE_BASE_DOL_SOURCE" ]; then
        candidates+=("$MELEE_BASE_DOL_SOURCE")
    fi
    candidates+=(
        "/Users/mike/code/melee/orig/GALE01/sys/main.dol"
        "$HOME/.config/decomp-me/orig/GALE01/main.dol"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
        if [ -f "$candidate" ]; then
            mkdir -p "$(dirname "$dest")"
            if [ -L "$dest" ] && [ ! -e "$dest" ]; then
                rm "$dest"
            fi
            if ln -s "$candidate" "$dest" 2>/dev/null; then
                echo "Linked base DOL from $candidate" >&2
            else
                cp "$candidate" "$dest"
                echo "Copied base DOL from $candidate" >&2
            fi
            return 0
        fi
    done
}

ensure_base_dol

# Local sessions: emit the capabilities context, then stop (no remote bootstrap).
if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/emit-capabilities-context.py" 2>/dev/null || true
    exit 0
fi

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

# Output workflow context for Claude (capabilities brief + remote notice).
python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/emit-capabilities-context.py" --remote 2>/dev/null || true

exit 0
