#!/bin/bash
# status.sh - Show current workflow status
#
# Usage: ./tools/workflow/status.sh
#
# Shows:
# - Current branch and its relationship to master/upstream
# - Uncommitted changes
# - Changes ready for PR (src/config differences)
# - Pending PR branches

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BOLD}=== Melee Decomp Workflow Status ===${NC}"
echo ""

# Fetch quietly
git fetch upstream --quiet 2>/dev/null || true
git fetch origin --quiet 2>/dev/null || true

# Current branch
CURRENT=$(git branch --show-current)
echo -e "${CYAN}Current Branch:${NC} $CURRENT"

# Branch relationships
echo ""
echo -e "${CYAN}Branch Status:${NC}"

# Master vs upstream
MASTER_AHEAD=$(git rev-list --count upstream/master..master 2>/dev/null || echo "?")
MASTER_BEHIND=$(git rev-list --count master..upstream/master 2>/dev/null || echo "?")
if [[ "$MASTER_BEHIND" == "0" ]]; then
    echo -e "  master: ${GREEN}up to date${NC} with upstream (+$MASTER_AHEAD tooling)"
else
    echo -e "  master: ${YELLOW}$MASTER_BEHIND commits behind${NC} upstream (+$MASTER_AHEAD local)"
fi

# Current branch vs master (if not on master)
if [[ "$CURRENT" != "master" ]]; then
    CURRENT_AHEAD=$(git rev-list --count master.."$CURRENT" 2>/dev/null || echo "?")
    CURRENT_BEHIND=$(git rev-list --count "$CURRENT"..master 2>/dev/null || echo "?")
    echo -e "  $CURRENT: +$CURRENT_AHEAD commits ahead, -$CURRENT_BEHIND behind master"
fi

# Uncommitted changes
echo ""
echo -e "${CYAN}Working Directory:${NC}"
STAGED=$(git diff --cached --name-only | wc -l | tr -d ' ')
UNSTAGED=$(git diff --name-only | wc -l | tr -d ' ')
UNTRACKED=$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')

if [[ "$STAGED" == "0" && "$UNSTAGED" == "0" && "$UNTRACKED" == "0" ]]; then
    echo -e "  ${GREEN}Clean${NC}"
else
    [[ "$STAGED" != "0" ]] && echo "  Staged: $STAGED files"
    [[ "$UNSTAGED" != "0" ]] && echo "  Modified: $UNSTAGED files"
    [[ "$UNTRACKED" != "0" ]] && echo "  Untracked: $UNTRACKED files"
fi

# Decomp changes ready for PR
echo ""
echo -e "${CYAN}Decomp Changes (src/config/include):${NC}"

# Changes on current branch vs master
if [[ "$CURRENT" != "master" ]]; then
    DECOMP_FILES=$(git diff --name-only master.."$CURRENT" -- src/ config/ include/ 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$DECOMP_FILES" != "0" ]]; then
        echo "  On $CURRENT vs master: $DECOMP_FILES files changed"
        echo ""
        echo "  Affected modules:"
        git diff --name-only master.."$CURRENT" -- src/melee/ 2>/dev/null | \
            sed 's|src/melee/||' | cut -d'/' -f1 | sort -u | while read module; do
            FILE_COUNT=$(git diff --name-only master.."$CURRENT" -- "src/melee/$module/" 2>/dev/null | wc -l | tr -d ' ')
            echo "    - $module ($FILE_COUNT files)"
        done
    else
        echo -e "  ${GREEN}No decomp changes on $CURRENT${NC}"
    fi
else
    # On master, check for uncommitted decomp changes
    DECOMP_UNCOMMITTED=$(git diff --name-only -- src/ config/ include/ | wc -l | tr -d ' ')
    DECOMP_STAGED=$(git diff --cached --name-only -- src/ config/ include/ | wc -l | tr -d ' ')
    if [[ "$DECOMP_UNCOMMITTED" != "0" || "$DECOMP_STAGED" != "0" ]]; then
        echo "  Uncommitted: $((DECOMP_UNCOMMITTED + DECOMP_STAGED)) files"
    else
        echo -e "  ${GREEN}No pending decomp changes${NC}"
    fi
fi

# PR branches
echo ""
echo -e "${CYAN}PR Branches:${NC}"
PR_BRANCHES=$(git branch --list 'pr/*' 2>/dev/null)
if [[ -z "$PR_BRANCHES" ]]; then
    echo "  None"
else
    echo "$PR_BRANCHES" | while read branch; do
        branch=$(echo "$branch" | tr -d ' *')
        COMMITS=$(git rev-list --count upstream/master.."$branch" 2>/dev/null || echo "?")
        # Check if pushed to origin
        if git show-ref --verify --quiet "refs/remotes/origin/$branch" 2>/dev/null; then
            PUSHED="${GREEN}pushed${NC}"
        else
            PUSHED="${YELLOW}local only${NC}"
        fi
        echo -e "  $branch: $COMMITS commits ($PUSHED)"
    done
fi

# WIP branches
echo ""
echo -e "${CYAN}WIP Branches:${NC}"
WIP_BRANCHES=$(git branch --list 'wip/*' 2>/dev/null)
if [[ -z "$WIP_BRANCHES" ]]; then
    echo "  None"
else
    echo "$WIP_BRANCHES" | while read branch; do
        branch=$(echo "$branch" | tr -d ' *')
        COMMITS=$(git rev-list --count master.."$branch" 2>/dev/null || echo "?")
        echo "  $branch: $COMMITS commits ahead of master"
    done
fi

# Backup branches
BACKUP_COUNT=$(git branch --list 'backup/*' 2>/dev/null | wc -l | tr -d ' ')
if [[ "$BACKUP_COUNT" != "0" ]]; then
    echo ""
    echo -e "${CYAN}Backup Branches:${NC} $BACKUP_COUNT"
    echo "  (run 'git branch --list backup/*' to see all)"
fi

# Recommendations
echo ""
echo -e "${CYAN}Recommendations:${NC}"

if [[ "$MASTER_BEHIND" != "0" && "$MASTER_BEHIND" != "?" ]]; then
    echo -e "  ${YELLOW}!${NC} Master is behind upstream. Run: ./tools/workflow/sync-upstream.sh"
fi

if [[ "$CURRENT" != "master" && "$DECOMP_FILES" != "0" ]]; then
    echo -e "  ${GREEN}>${NC} Changes ready for PR. Run: ./tools/workflow/create-pr.sh <name>"
fi

if [[ "$BACKUP_COUNT" -gt 5 ]]; then
    echo -e "  ${YELLOW}!${NC} Many backup branches. Consider cleanup."
fi

echo ""
