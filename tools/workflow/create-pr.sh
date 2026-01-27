#!/bin/bash
# create-pr.sh - Create a clean PR branch from current changes
#
# Usage: ./tools/workflow/create-pr.sh <pr-branch-name> [--from <source-branch>]
#
# This script:
# 1. Identifies all src/config/include changes between master and source branch
# 2. Creates a new branch from upstream/master
# 3. Applies those changes cleanly
# 4. Commits with a template message

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
SOURCE_BRANCH="HEAD"

while [[ $# -gt 0 ]]; do
    case $1 in
        --from)
            SOURCE_BRANCH="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 <pr-branch-name> [--from <source-branch>]"
            echo ""
            echo "Creates a clean PR branch from decomp changes."
            echo ""
            echo "Options:"
            echo "  --from <branch>  Source branch for changes (default: HEAD)"
            echo ""
            echo "Examples:"
            echo "  $0 pr/mndiagram-improvements"
            echo "  $0 pr/mnvibration --from wip/mn-work"
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
    echo "Usage: $0 <pr-branch-name> [--from <source-branch>]"
    exit 1
fi

# Ensure branch name has pr/ prefix
if [[ ! "$PR_BRANCH" =~ ^pr/ ]]; then
    PR_BRANCH="pr/$PR_BRANCH"
    echo -e "${YELLOW}Adding pr/ prefix: $PR_BRANCH${NC}"
fi

echo "=== Create PR Branch ==="
echo ""
echo "Source: $SOURCE_BRANCH"
echo "Target: $PR_BRANCH (based on upstream/master)"
echo ""

# Fetch upstream
git fetch upstream

# Check if PR branch already exists
if git show-ref --verify --quiet "refs/heads/$PR_BRANCH"; then
    echo -e "${RED}Error: Branch $PR_BRANCH already exists${NC}"
    echo "Delete it first: git branch -D $PR_BRANCH"
    exit 1
fi

# Get the diff
echo "Analyzing changes..."
DIFF_STATS=$(git diff --stat master.."$SOURCE_BRANCH" -- src/ config/ include/ 2>/dev/null || echo "")

if [[ -z "$DIFF_STATS" ]]; then
    echo -e "${YELLOW}No src/config/include changes found between master and $SOURCE_BRANCH${NC}"
    exit 1
fi

echo "$DIFF_STATS"
echo ""

# Show affected modules
echo -e "${CYAN}Affected modules:${NC}"
git diff --name-only master.."$SOURCE_BRANCH" -- src/melee/ | \
    sed 's|src/melee/||' | cut -d'/' -f1 | sort -u | while read module; do
    echo "  - $module"
done
echo ""

# List affected files
echo -e "${CYAN}Files to include:${NC}"
FILES=$(git diff --name-only master.."$SOURCE_BRANCH" -- src/ config/ include/)
echo "$FILES" | head -20
FILE_COUNT=$(echo "$FILES" | wc -l | tr -d ' ')
if [[ "$FILE_COUNT" -gt 20 ]]; then
    echo "  ... and $((FILE_COUNT - 20)) more files"
fi
echo ""

# Confirm
read -p "Create PR branch $PR_BRANCH with these changes? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Create the branch
echo ""
echo "Creating branch..."
git checkout -b "$PR_BRANCH" upstream/master

# Apply the diff
echo "Applying changes..."
if ! git diff master.."$SOURCE_BRANCH" -- src/ config/ include/ | git apply; then
    echo -e "${RED}Failed to apply diff cleanly${NC}"
    echo "You may need to resolve conflicts manually."
    git checkout master
    git branch -D "$PR_BRANCH"
    exit 1
fi

# Stage all changes
git add -A

# Show what we're committing
echo ""
echo -e "${CYAN}Changes staged:${NC}"
git diff --cached --stat

# Generate commit message template
MODULES=$(git diff --cached --name-only -- src/melee/ | \
    sed 's|src/melee/||' | cut -d'/' -f1 | sort -u | head -3 | tr '\n' ',' | sed 's/,$//')

COMMIT_MSG_FILE=$(mktemp)
cat > "$COMMIT_MSG_FILE" << EOF
$MODULES: <brief description>

<detailed description of changes>

Functions matched/improved:
- <function_name>: <percentage>% match

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF

echo ""
echo -e "${YELLOW}Opening editor for commit message...${NC}"
echo "(Template has been prepared)"

# Commit with editor
git commit -t "$COMMIT_MSG_FILE"
rm "$COMMIT_MSG_FILE"

echo ""
echo -e "${GREEN}=== PR Branch Created ===${NC}"
echo ""
echo "Branch: $PR_BRANCH"
echo "Based on: upstream/master ($(git rev-parse --short upstream/master))"
echo ""
echo "Commits:"
git log --oneline upstream/master..HEAD
echo ""
echo "Next steps:"
echo "  1. Review: git log -p upstream/master..HEAD"
echo "  2. Build:  python configure.py && ninja"
echo "  3. Push:   git push origin $PR_BRANCH"
echo "  4. PR:     https://github.com/doldecomp/melee/compare/master...$PR_BRANCH"
echo ""
echo "To go back to your working branch:"
echo "  git checkout master  # or your WIP branch"
