#!/bin/bash
# update-pr.sh - Update a PR branch with changes from master (or current branch)
#
# Usage:
#   ./tools/workflow/update-pr.sh <pr-branch> [--amend]
#
# This applies src/config/include changes to a PR branch without switching branches.
# Useful for iterating on PR feedback while staying on master with tooling.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Parse arguments
PR_BRANCH=""
AMEND=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --amend)
            AMEND=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 <pr-branch> [--amend]"
            echo ""
            echo "Updates a PR branch with current src/config/include changes."
            echo ""
            echo "Options:"
            echo "  --amend    Amend the last commit instead of creating new one"
            echo ""
            echo "Examples:"
            echo "  $0 pr/mndiagram           # Add new commit to PR branch"
            echo "  $0 pr/mndiagram --amend   # Amend last commit (for fixups)"
            exit 0
            ;;
        *)
            if [[ -z "$PR_BRANCH" ]]; then
                PR_BRANCH="$1"
            else
                echo -e "${RED}Unknown argument: $1${NC}"
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$PR_BRANCH" ]]; then
    echo -e "${RED}Error: PR branch name required${NC}"
    echo "Usage: $0 <pr-branch> [--amend]"
    exit 1
fi

# Verify branch exists
if ! git show-ref --verify --quiet "refs/heads/$PR_BRANCH"; then
    echo -e "${RED}Error: Branch '$PR_BRANCH' does not exist${NC}"
    exit 1
fi

CURRENT_BRANCH=$(git branch --show-current)
echo "=== Update PR Branch ==="
echo ""
echo "Source: $CURRENT_BRANCH (current)"
echo "Target: $PR_BRANCH"
echo "Mode: $(if $AMEND; then echo 'amend'; else echo 'new commit'; fi)"
echo ""

# Check for uncommitted changes
if ! git diff --quiet -- src/ config/ include/ || ! git diff --cached --quiet -- src/ config/ include/; then
    echo -e "${YELLOW}Warning: You have uncommitted changes in src/config/include${NC}"
    echo "These will NOT be included. Commit them first if you want them in the PR."
    echo ""
fi

# Get the diff between PR branch and current
# We want changes that are in current but not in PR branch
DIFF=$(git diff "$PR_BRANCH".."$CURRENT_BRANCH" -- src/ config/ include/)

if [[ -z "$DIFF" ]]; then
    echo -e "${GREEN}No new changes to apply - PR branch is up to date${NC}"
    exit 0
fi

# Show what will be applied
echo -e "${CYAN}Changes to apply:${NC}"
git diff --stat "$PR_BRANCH".."$CURRENT_BRANCH" -- src/ config/ include/
echo ""

read -p "Apply these changes to $PR_BRANCH? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Stash current state (in case we need to recover)
STASH_MSG="update-pr-backup-$(date +%s)"
git stash push -m "$STASH_MSG" --quiet 2>/dev/null || true

# Switch to PR branch
git checkout "$PR_BRANCH" --quiet

# Apply the diff
echo "Applying changes..."
echo "$DIFF" | git apply

# Stage changes
git add -A -- src/ config/ include/

# Commit
if $AMEND; then
    git commit --amend --no-edit
    echo -e "${GREEN}Amended commit on $PR_BRANCH${NC}"
else
    # Prompt for commit message
    echo ""
    echo "Enter commit message (or press enter for default):"
    read -r COMMIT_MSG
    if [[ -z "$COMMIT_MSG" ]]; then
        COMMIT_MSG="Update based on feedback

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
    fi
    git commit -m "$COMMIT_MSG"
    echo -e "${GREEN}Created new commit on $PR_BRANCH${NC}"
fi

# Show result
echo ""
echo "PR branch updated:"
git log --oneline -3 "$PR_BRANCH"

# Switch back to original branch
git checkout "$CURRENT_BRANCH" --quiet

# Restore stash if we had one
if git stash list | grep -q "$STASH_MSG"; then
    git stash pop --quiet
fi

echo ""
echo -e "${GREEN}Done!${NC} Back on $CURRENT_BRANCH"
echo ""
echo "To push the update:"
echo "  git push origin $PR_BRANCH $(if $AMEND; then echo '--force-with-lease'; fi)"
