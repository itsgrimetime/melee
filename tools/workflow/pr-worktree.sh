#!/bin/bash
# pr-worktree.sh - Create or manage a worktree for PR iteration
#
# Usage:
#   ./tools/workflow/pr-worktree.sh create <pr-branch>   # Create worktree with tooling
#   ./tools/workflow/pr-worktree.sh delete               # Remove PR worktree
#   ./tools/workflow/pr-worktree.sh status               # Show PR worktree status
#
# This creates a worktree at ../melee-pr with symlinked tooling,
# so you can iterate on PR branches with full agent support.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PR_WORKTREE="$(dirname "$REPO_ROOT")/melee-pr"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Tooling paths to symlink (relative to repo root)
TOOLING_SYMLINKS=(
    ".claude"
    "tools"
    "docs"
    ".vscode"
    "CLAUDE.md"
    "AGENTS.md"
)

# Files to copy (can't be symlinks for various reasons)
TOOLING_COPIES=(
    "configure.py"
    ".gitignore"
    "decomp.yaml"
    "permuter_settings.toml"
)

cmd_create() {
    local branch="$1"

    if [[ -z "$branch" ]]; then
        echo -e "${RED}Error: Branch name required${NC}"
        echo "Usage: $0 create <pr-branch>"
        exit 1
    fi

    # Ensure branch exists
    if ! git show-ref --verify --quiet "refs/heads/$branch"; then
        echo -e "${RED}Error: Branch '$branch' does not exist${NC}"
        exit 1
    fi

    # Check if worktree already exists
    if [[ -d "$PR_WORKTREE" ]]; then
        echo -e "${YELLOW}PR worktree already exists at $PR_WORKTREE${NC}"
        echo "Current branch: $(cd "$PR_WORKTREE" && git branch --show-current)"
        echo ""
        read -p "Switch to $branch? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            cd "$PR_WORKTREE"
            git checkout "$branch"
            echo -e "${GREEN}Switched to $branch${NC}"
        fi
        return
    fi

    echo "=== Creating PR Worktree ==="
    echo ""
    echo "Branch: $branch"
    echo "Location: $PR_WORKTREE"
    echo ""

    # Create worktree
    cd "$REPO_ROOT"
    git worktree add "$PR_WORKTREE" "$branch"

    # Create symlinks for tooling
    echo "Setting up tooling symlinks..."
    cd "$PR_WORKTREE"

    for item in "${TOOLING_SYMLINKS[@]}"; do
        if [[ -e "$REPO_ROOT/$item" ]]; then
            ln -sf "$REPO_ROOT/$item" "$item"
            echo "  Linked: $item"
        fi
    done

    # Copy files that need to be actual files
    for item in "${TOOLING_COPIES[@]}"; do
        if [[ -e "$REPO_ROOT/$item" ]]; then
            cp "$REPO_ROOT/$item" "$item"
            echo "  Copied: $item"
        fi
    done

    # Create .codex symlink
    mkdir -p .codex
    ln -sf ../.claude/skills .codex/skills

    # Add tooling to local exclude (so it doesn't show as untracked)
    echo "Configuring local git exclude..."
    mkdir -p .git
    # Note: In a worktree, .git is a file pointing to the main repo
    # We need to find the actual gitdir
    GITDIR=$(cat .git | sed 's/gitdir: //')
    cat >> "$GITDIR/info/exclude" << 'EOF'
# Symlinked tooling (not part of PR)
.claude/
tools/
docs/
.vscode/
CLAUDE.md
AGENTS.md
.codex/
configure.py
.gitignore
decomp.yaml
permuter_settings.toml
EOF

    echo ""
    echo -e "${GREEN}=== PR Worktree Ready ===${NC}"
    echo ""
    echo "Location: $PR_WORKTREE"
    echo "Branch: $branch"
    echo ""
    echo "Tooling is symlinked from main repo - changes there are shared."
    echo "Only src/config/include changes will be committed to the PR."
    echo ""
    echo "To work on PR:"
    echo "  cd $PR_WORKTREE"
    echo ""
    echo "When done, return to main repo:"
    echo "  cd $REPO_ROOT"
    echo ""
    echo "To remove worktree later:"
    echo "  $0 delete"
}

cmd_delete() {
    if [[ ! -d "$PR_WORKTREE" ]]; then
        echo "No PR worktree found at $PR_WORKTREE"
        exit 0
    fi

    echo "=== Removing PR Worktree ==="
    echo ""
    echo "Location: $PR_WORKTREE"

    # Check for uncommitted changes
    cd "$PR_WORKTREE"
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo -e "${YELLOW}Warning: Uncommitted changes in worktree${NC}"
        git status --short
        echo ""
        read -p "Delete anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted."
            exit 1
        fi
    fi

    cd "$REPO_ROOT"
    git worktree remove "$PR_WORKTREE" --force

    echo -e "${GREEN}PR worktree removed${NC}"
}

cmd_status() {
    if [[ ! -d "$PR_WORKTREE" ]]; then
        echo "No PR worktree exists."
        echo "Create one with: $0 create <pr-branch>"
        exit 0
    fi

    echo "=== PR Worktree Status ==="
    echo ""
    echo "Location: $PR_WORKTREE"

    cd "$PR_WORKTREE"
    echo "Branch: $(git branch --show-current)"
    echo ""

    # Show changes
    if git diff --quiet && git diff --cached --quiet; then
        echo -e "Working directory: ${GREEN}Clean${NC}"
    else
        echo "Changes:"
        git status --short -- src/ config/ include/
    fi

    echo ""
    echo "Commits ahead of upstream:"
    git log --oneline upstream/master..HEAD 2>/dev/null || echo "(upstream not fetched)"
}

# Main
case "${1:-status}" in
    create)
        cmd_create "$2"
        ;;
    delete|remove)
        cmd_delete
        ;;
    status)
        cmd_status
        ;;
    *)
        echo "Usage: $0 <command> [args]"
        echo ""
        echo "Commands:"
        echo "  create <branch>  Create PR worktree for branch"
        echo "  delete           Remove PR worktree"
        echo "  status           Show PR worktree status"
        exit 1
        ;;
esac
