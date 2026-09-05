#!/bin/bash
# Pre-commit hook for melee decompilation project
# Implements style checks derived from maintainer PR feedback
#
# Installation:
#   ln -sf ../../tools/pre-commit-hook.sh .git/hooks/pre-commit
#
# Or with pre-commit framework, add to .pre-commit-config.yaml:
#   - repo: local
#     hooks:
#       - id: melee-style-check
#         name: Melee Style Check
#         entry: tools/pre-commit-hook.sh
#         language: script
#         types: [c]

set -e

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

error() {
    echo -e "${RED}ERROR:${NC} $1"
    ERRORS=$((ERRORS + 1))
}

warn() {
    echo -e "${YELLOW}WARNING:${NC} $1"
    WARNINGS=$((WARNINGS + 1))
}

# Get list of staged C/H files
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACMR | grep -E '\.(c|h)$' || true)

if [ -z "$STAGED_FILES" ]; then
    exit 0
fi

echo "Running melee style checks..."

# Get the staged diff for pattern matching
STAGED_DIFF=$(git diff --cached)

# =============================================================================
# CRITICAL CHECKS (Errors - will block commit)
# =============================================================================

# 1. Check for modifications to /orig folder
if git diff --cached --name-only | grep -q '^orig/'; then
    error "Do not modify files in /orig folder"
fi

# 2. Check for .build_validated or other unexpected files
if git diff --cached --name-only | grep -qE '\.build_validated|\.claude'; then
    error "Do not commit build artifacts or tool state files"
fi

# 3. Check for TRUE/FALSE usage (should use true/false)
if echo "$STAGED_DIFF" | grep -E '^\+.*\b(TRUE|FALSE)\b' | grep -v '#define' > /dev/null; then
    error "Use lowercase true/false instead of TRUE/FALSE"
    echo "  Affected lines:"
    echo "$STAGED_DIFF" | grep -E '^\+.*\b(TRUE|FALSE)\b' | grep -v '#define' | head -5
fi

# 4. Check for .static.h includes in headers
for file in $STAGED_FILES; do
    if [[ "$file" == *.h ]] && git diff --cached -- "$file" | grep -E '^\+.*#include.*\.static\.h' > /dev/null; then
        error "$file: .static.h should only be included from .c files"
    fi
done

# 5. Check for local sqrtf/math definitions (should include math_ppc.h)
if echo "$STAGED_DIFF" | grep -E '^\+.*(extern|static).*\bsqrtf\b' > /dev/null; then
    error "Include <math_ppc.h> instead of defining sqrtf locally"
fi

# =============================================================================
# IMPORTANT CHECKS (Warnings - won't block but should be reviewed)
# =============================================================================

# 6. Check for s32 and M2C_UNK usage
if echo "$STAGED_DIFF" | grep -E '^\+.*(\bs32\b|M2C_UNK)' | grep -v '//.*s32\|//.*M2C' > /dev/null; then
    warn "Consider using int instead of s32, UNK_T instead of M2C_UNK"
fi

# 7. Check for local extern declarations in .c files
for file in $STAGED_FILES; do
    if [[ "$file" == *.c ]] && git diff --cached -- "$file" | grep -E '^\+\s*extern\s+' > /dev/null; then
        warn "$file: Consider using header includes instead of local extern declarations"
    fi
done

# 8. Check for underscore-prefixed struct names in headers
for file in $STAGED_FILES; do
    if [[ "$file" == *.h ]] && git diff --cached -- "$file" | grep -E '^\+.*struct\s+_\w+' > /dev/null; then
        warn "$file: Don't prefix struct names with underscores"
    fi
done

# 9. Check for relative includes in headers
for file in $STAGED_FILES; do
    if [[ "$file" == *.h ]] && git diff --cached -- "$file" | grep -E '^\+\s*#include\s+"[^/]' > /dev/null; then
        warn "$file: Headers should use angle bracket includes with full paths"
    fi
done

# 10. Check for types.h includes in headers
for file in $STAGED_FILES; do
    if [[ "$file" == *.h ]] && git diff --cached -- "$file" | grep -E '^\+.*#include.*types\.h' | grep -v forward > /dev/null; then
        warn "$file: Consider using forward declarations instead of including types.h in headers"
    fi
done

# 11. Check for empty functions with { return; }
if echo "$STAGED_DIFF" | grep -E '^\+.*void.*\{\s*return;\s*\}' > /dev/null; then
    warn "Empty void functions should use {} not { return; }"
fi

# 12. Check for manual stack padding patterns
if echo "$STAGED_DIFF" | grep -E '^\+.*int\s+_?pad\s*=' > /dev/null; then
    warn "Consider using PAD_STACK macro instead of manual padding variables"
fi

# 13. Check for 0xFFFFFFFF (often should be -1 in ItemStateTable)
if echo "$STAGED_DIFF" | grep -E '^\+.*0xFFFFFFFF' > /dev/null; then
    warn "Consider using -1 instead of 0xFFFFFFFF (especially in ItemStateTable)"
fi

# 14. Check for raw pointer arithmetic patterns
if echo "$STAGED_DIFF" | grep -E '^\+.*\*\s*\([^)]+\*\)\s*\(\s*\(\s*(char|u8)\s*\*\s*\)' > /dev/null; then
    warn "Use M2C_FIELD or proper struct fields instead of pointer arithmetic"
fi

# 15. Check for HSD_GObj casts (might indicate wrong types)
if echo "$STAGED_DIFF" | grep -E '^\+.*\(HSD_GObj\s*\*\)' | grep -v 'user_data\|->data' > /dev/null; then
    warn "Check if HSD_GObj cast is necessary - consider fixing argument types instead"
fi

# 16. Check for missing include guards in new headers
for file in $STAGED_FILES; do
    if [[ "$file" == *.h ]]; then
        # Check if this is a new file
        if ! git show HEAD:"$file" > /dev/null 2>&1; then
            if ! grep -q '#ifndef' "$file" 2>/dev/null; then
                warn "$file: New header is missing include guard"
            fi
        fi
    fi
done

# =============================================================================
# SUMMARY
# =============================================================================

echo ""
if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}Found $ERRORS error(s) that must be fixed before committing.${NC}"
    echo "See docs/STYLE_GUIDE.md for details on these conventions."
    exit 1
fi

if [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}Found $WARNINGS warning(s) that should be reviewed.${NC}"
    echo "These won't block your commit, but please address them if possible."
    echo "See docs/STYLE_GUIDE.md for details on these conventions."
fi

exit 0
