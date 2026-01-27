#!/bin/bash
# sync-upstream.sh - Reset master to upstream/master + tooling overlay
#
# Usage: ./tools/workflow/sync-upstream.sh [--dry-run]
#
# This script:
# 1. Saves any WIP work as a patch
# 2. Resets master to upstream/master
# 3. Re-applies the tooling overlay
# 4. Optionally restores WIP work

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo -e "${YELLOW}DRY RUN MODE - no changes will be made${NC}"
fi

# Tooling files/directories to preserve
TOOLING_PATHS=(
    "tools/"
    ".claude/"
    "docs/"
    ".github/"
    ".vscode/"
    "configure.py"
    ".gitignore"
    ".pre-commit-config.yaml"
    "CLAUDE.md"
    "AGENTS.md"
    ".codex/"
    "decomp.yaml"
    "permuter_settings.toml"
)

echo "=== Upstream Sync Tool ==="
echo ""

# Check we're on master or can switch to it
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "master" ]]; then
    echo -e "${YELLOW}Currently on branch: $CURRENT_BRANCH${NC}"
    echo "Will switch to master for sync"
fi

# Fetch upstream
echo "Fetching upstream..."
git fetch upstream

# Show what we're syncing
UPSTREAM_HEAD=$(git rev-parse --short upstream/master)
MASTER_HEAD=$(git rev-parse --short master)
echo ""
echo "upstream/master: $UPSTREAM_HEAD"
echo "master:          $MASTER_HEAD"
echo ""

# Check for new upstream commits
NEW_COMMITS=$(git log --oneline master..upstream/master | wc -l | tr -d ' ')
if [[ "$NEW_COMMITS" == "0" ]]; then
    echo -e "${GREEN}Master is already up to date with upstream!${NC}"
    exit 0
fi

echo "New upstream commits: $NEW_COMMITS"
git log --oneline master..upstream/master | head -10
if [[ "$NEW_COMMITS" -gt 10 ]]; then
    echo "... and $((NEW_COMMITS - 10)) more"
fi
echo ""

# Check for uncommitted changes
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo -e "${RED}Error: You have uncommitted changes. Please commit or stash them first.${NC}"
    exit 1
fi

# Check for WIP work on master that's not in upstream
WIP_COMMITS=$(git log --oneline upstream/master..master -- src/ config/ include/ | wc -l | tr -d ' ')
if [[ "$WIP_COMMITS" -gt 0 ]]; then
    echo -e "${YELLOW}Found $WIP_COMMITS commits with src/config changes on master${NC}"
    echo "These will be saved as a patch before sync."
    echo ""

    # Create patch for src/config changes
    PATCH_FILE="/tmp/melee-wip-$(date +%Y%m%d-%H%M%S).patch"

    if [[ "$DRY_RUN" == false ]]; then
        git diff upstream/master..master -- src/ config/ include/ > "$PATCH_FILE"
        if [[ -s "$PATCH_FILE" ]]; then
            echo -e "${GREEN}WIP saved to: $PATCH_FILE${NC}"
        else
            rm "$PATCH_FILE"
            PATCH_FILE=""
        fi
    else
        echo "[DRY RUN] Would save WIP to: $PATCH_FILE"
    fi
fi

if [[ "$DRY_RUN" == true ]]; then
    echo ""
    echo "[DRY RUN] Would perform:"
    echo "  1. git checkout master"
    echo "  2. git reset --hard upstream/master"
    echo "  3. Restore tooling from current master"
    echo "  4. git commit -m 'restore fork tooling after upstream sync'"
    exit 0
fi

# Perform the sync
echo ""
echo "Performing sync..."

# Switch to master if needed
if [[ "$CURRENT_BRANCH" != "master" ]]; then
    git checkout master
fi

# Create backup branch
BACKUP_BRANCH="backup/master-pre-sync-$(date +%Y%m%d-%H%M%S)"
git branch "$BACKUP_BRANCH"
echo "Backup created: $BACKUP_BRANCH"

# Reset to upstream
git reset --hard upstream/master

# Restore tooling
echo "Restoring tooling..."
for path in "${TOOLING_PATHS[@]}"; do
    if git show "$BACKUP_BRANCH:$path" &>/dev/null 2>&1; then
        git checkout "$BACKUP_BRANCH" -- "$path" 2>/dev/null || true
    fi
done

# Recreate symlinks
ln -sf CLAUDE.md AGENTS.md 2>/dev/null || true
mkdir -p .codex && ln -sf ../.claude/skills .codex/skills 2>/dev/null || true

# Commit tooling
git add -A
if ! git diff --cached --quiet; then
    git commit -m "restore fork tooling after upstream sync

Synced to upstream/master at $(git rev-parse --short upstream/master)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
fi

echo ""
echo -e "${GREEN}=== Sync Complete ===${NC}"
echo ""
echo "Master is now at upstream/master + tooling"
git log --oneline -3

if [[ -n "$PATCH_FILE" && -f "$PATCH_FILE" ]]; then
    echo ""
    echo -e "${YELLOW}WIP patch saved at: $PATCH_FILE${NC}"
    echo "To restore: git apply $PATCH_FILE"
fi

echo ""
echo "Backup branch: $BACKUP_BRANCH"
echo "To delete backup: git branch -D $BACKUP_BRANCH"
