#!/usr/bin/env bash
# Import + analyze mwcceppc.exe in a fresh Ghidra project.
#
# One-time setup for RE work on the MWCC 1.2.5n compiler. The resulting
# project is at tools/mwcc_debug/ghidra_project/mwcceppc (gitignored).
# After this runs, the ghidra_query_*.py scripts can decompile functions
# and resolve cross-references via pyghidra.
#
# Prereqs:
#   - brew install ghidra        (provides analyzeHeadless)
#   - pip install pyghidra       (for the query scripts)
#
# Takes ~90s the first time, then is a no-op (analyzeHeadless detects
# the existing import).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MWCC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MELEE_ROOT="$(cd "$MWCC_DIR/../.." && pwd)"

EXE="$MELEE_ROOT/build/compilers/GC/1.2.5n/mwcceppc.exe"
PROJECT_DIR="$MWCC_DIR/ghidra_project"
PROJECT_NAME="mwcceppc"

if [[ ! -f "$EXE" ]]; then
    echo "error: mwcceppc.exe not found at $EXE" >&2
    echo "  (it ships with the dtk toolchain; build the project once to fetch it)" >&2
    exit 1
fi

GHIDRA_HEADLESS="$(brew --prefix ghidra 2>/dev/null)/libexec/support/analyzeHeadless"
if [[ ! -x "$GHIDRA_HEADLESS" ]]; then
    # Try Cellar path as fallback (homebrew links can sometimes be missing).
    GHIDRA_HEADLESS="$(ls /opt/homebrew/Cellar/ghidra/*/libexec/support/analyzeHeadless 2>/dev/null | head -1)"
fi
if [[ ! -x "$GHIDRA_HEADLESS" ]]; then
    echo "error: analyzeHeadless not found. Install Ghidra: brew install ghidra" >&2
    exit 1
fi

mkdir -p "$PROJECT_DIR"

# If already imported, analyzeHeadless will refuse with "already exists" —
# skip. Otherwise import + analyze.
if [[ -d "$PROJECT_DIR/$PROJECT_NAME.rep" ]]; then
    echo "Ghidra project already exists at $PROJECT_DIR/$PROJECT_NAME (skipping import)"
else
    echo "Importing $EXE into Ghidra (~90s)..."
    "$GHIDRA_HEADLESS" "$PROJECT_DIR" "$PROJECT_NAME" \
        -import "$EXE" \
        -analysisTimeoutPerFile 300
fi

echo
echo "Done. To query the project from Python:"
echo "  python3 $SCRIPT_DIR/ghidra_query_diagnostic.py"
echo "  python3 $SCRIPT_DIR/ghidra_query_coalesce_pipeline.py"
