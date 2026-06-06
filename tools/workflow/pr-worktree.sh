#!/bin/bash
# pr-worktree.sh - Create or manage a worktree for PR or WIP iteration
#
# Usage:
#   ./tools/workflow/pr-worktree.sh create <pr/topic|wip/topic>   # Create worktree
#   ./tools/workflow/pr-worktree.sh delete [branch]               # Remove worktree
#   ./tools/workflow/pr-worktree.sh status [branch]               # Show status
#
# Two modes:
#
#   pr/<topic>   Worktree at ../melee-pr. Branch must already exist (typically
#                created via ./tools/workflow/create-pr.sh, which branches
#                from upstream/master). Fork tooling (.claude/, tools/, docs/,
#                CLAUDE.md, etc.) is symlinked in from the main repo and
#                excluded from git so the PR stays clean for upstream review.
#                delete/status with no argument default to this worktree.
#
#   wip/<topic>  Worktree at ../melee-wip-<topic>. Branch is created from
#                master if it doesn't exist, so the tooling overlay is
#                inherited directly via git checkout — no symlinks needed.
#                Use for long-running per-agent decomp work that needs full
#                tooling access in an isolated tree. To pick up later master
#                overlay updates, fetch and merge master into the wip branch.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Tooling paths to symlink into pr/* worktrees (relative to repo root).
# Not used for wip/* worktrees — those inherit the overlay from master.
TOOLING_SYMLINKS=(
    ".claude"
    "tools"
    "docs"
    ".vscode"
    "CLAUDE.md"
    "AGENTS.md"
)

# Files to copy (can't be symlinks for various reasons).
TOOLING_COPIES=(
    "configure.py"
    ".gitignore"
    "decomp.yaml"
    "permuter_settings.toml"
)

# Resolve a branch name to a worktree path + mode.
# Sets globals WORKTREE_MODE ("pr"|"wip") and WORKTREE_PATH.
resolve_worktree() {
    local branch="$1"
    case "$branch" in
        pr/*)
            WORKTREE_MODE="pr"
            WORKTREE_PATH="$(dirname "$REPO_ROOT")/melee-pr"
            ;;
        wip/*)
            WORKTREE_MODE="wip"
            local topic="${branch#wip/}"
            WORKTREE_PATH="$(dirname "$REPO_ROOT")/melee-wip-${topic}"
            ;;
        *)
            echo -e "${RED}Error: branch must be pr/<topic> or wip/<topic> (got '$branch')${NC}"
            exit 1
            ;;
    esac
}

mode_label() {
    if [[ "$WORKTREE_MODE" == "pr" ]]; then echo "PR"; else echo "WIP"; fi
}

ensure_base_dol() {
    local dest="orig/GALE01/sys/main.dol"
    if [[ -f "$dest" ]]; then
        echo "Base DOL present: $dest"
        return
    fi

    local candidates=(
        "$REPO_ROOT/orig/GALE01/sys/main.dol"
        "$HOME/.config/decomp-me/orig/GALE01/main.dol"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -f "$candidate" ]]; then
            mkdir -p "$(dirname "$dest")"
            if [[ -L "$dest" && ! -e "$dest" ]]; then
                rm "$dest"
            fi
            if ln -s "$candidate" "$dest" 2>/dev/null; then
                echo "Linked base DOL: $dest -> $candidate"
            else
                cp "$candidate" "$dest"
                echo "Copied base DOL: $dest"
            fi
            return
        fi
    done

    echo -e "${YELLOW}Warning: base DOL not found; run python tools/worktree-doctor.py --fix in the worktree.${NC}"
}

link_tooling_overlay_item() {
    local item="$1"
    local src="$REPO_ROOT/$item"
    local dest="$WORKTREE_PATH/$item"

    if [[ -d "$src" && -d "$dest" && ! -L "$dest" ]]; then
        local child
        while IFS= read -r -d '' child; do
            local name
            local target
            name="$(basename "$child")"
            target="$dest/$name"
            if [[ -e "$target" || -L "$target" ]]; then
                continue
            fi
            ln -sf "$child" "$target"
            echo "  Linked: $item/$name"
        done < <(find "$src" -mindepth 1 -maxdepth 1 -print0)
        return
    fi

    if [[ ! -e "$dest" && ! -L "$dest" ]]; then
        ln -sf "$src" "$dest"
        echo "  Linked: $item"
    else
        echo "  Kept existing: $item"
    fi
}

cmd_create() {
    local branch="$1"

    if [[ -z "$branch" ]]; then
        echo -e "${RED}Error: Branch name required${NC}"
        echo "Usage: $0 create <pr/topic|wip/topic>"
        exit 1
    fi

    resolve_worktree "$branch"

    local branch_exists=0
    if git show-ref --verify --quiet "refs/heads/$branch"; then
        branch_exists=1
    fi

    # pr/* must already exist (typically built by create-pr.sh from upstream/master).
    if [[ "$WORKTREE_MODE" == "pr" ]] && [[ "$branch_exists" -eq 0 ]]; then
        echo -e "${RED}Error: Branch '$branch' does not exist${NC}"
        echo "Use ./tools/workflow/create-pr.sh to create a PR branch first."
        exit 1
    fi

    # Check if worktree already exists
    if [[ -d "$WORKTREE_PATH" ]]; then
        echo -e "${YELLOW}Worktree already exists at $WORKTREE_PATH${NC}"
        echo "Current branch: $(cd "$WORKTREE_PATH" && git branch --show-current)"
        echo ""
        read -p "Switch to $branch? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            cd "$WORKTREE_PATH"
            git checkout "$branch"
            echo -e "${GREEN}Switched to $branch${NC}"
        fi
        return
    fi

    echo "=== Creating $(mode_label) Worktree ==="
    echo ""
    echo "Branch: $branch"
    echo "Location: $WORKTREE_PATH"
    echo ""

    # Create worktree
    cd "$REPO_ROOT"
    if [[ "$branch_exists" -eq 1 ]]; then
        git worktree add "$WORKTREE_PATH" "$branch"
    else
        # wip/* branch doesn't exist — create from master so it inherits the overlay.
        echo "Creating new branch '$branch' from master..."
        git worktree add -b "$branch" "$WORKTREE_PATH" master
    fi

    cd "$WORKTREE_PATH"

    if [[ "$WORKTREE_MODE" == "pr" ]]; then
        # PR mode: branched from upstream/master, no tooling overlay present.
        # Symlink overlay in from main repo and exclude it from git locally.
        echo "Setting up tooling symlinks..."
        for item in "${TOOLING_SYMLINKS[@]}"; do
            if [[ -e "$REPO_ROOT/$item" || -L "$REPO_ROOT/$item" ]]; then
                link_tooling_overlay_item "$item"
            fi
        done

        for item in "${TOOLING_COPIES[@]}"; do
            if [[ -e "$REPO_ROOT/$item" ]]; then
                cp "$REPO_ROOT/$item" "$item"
                echo "  Copied: $item"
            fi
        done

        # Create .codex symlink (PR branches don't have .codex in their tree).
        if [[ ! -e ".codex" ]]; then
            mkdir -p .codex
            ln -sf ../.claude/skills .codex/skills
        fi

        # Add tooling to local exclude (so it doesn't show as untracked).
        echo "Configuring local git exclude..."
        # In a worktree, .git is a file pointing to the actual gitdir.
        GITDIR=$(git rev-parse --git-dir)
        mkdir -p "$GITDIR/info"
        cat >> "$GITDIR/info/exclude" << 'EOF'
# Symlinked tooling (not part of PR)
.claude/
tools/checkdiff.py
tools/decomp.py
tools/workflow/
tools/worktree-doctor.py
tools/melee-agent/
tools/table-typer/
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
    else
        # WIP mode: branched from master, tooling overlay is already in the tree.
        # Symlinks would shadow real files; skip them. Still refresh the
        # TOOLING_COPIES so per-worktree edits stay local to this branch.
        echo "Tooling overlay inherited from master (no symlinks needed)."
        for item in "${TOOLING_COPIES[@]}"; do
            if [[ -e "$REPO_ROOT/$item" ]]; then
                cp "$REPO_ROOT/$item" "$item"
                echo "  Refreshed: $item"
            fi
        done
    fi

    ensure_base_dol

    echo ""
    echo -e "${GREEN}=== $(mode_label) Worktree Ready ===${NC}"
    echo ""
    echo "Location: $WORKTREE_PATH"
    echo "Branch: $branch"
    echo ""
    if [[ "$WORKTREE_MODE" == "pr" ]]; then
        echo "Tooling is symlinked from main repo - changes there are shared."
        echo "Only src/config/include changes will be committed to the PR."
    else
        echo "Tooling overlay is tracked on master in this worktree."
        echo "To pull in later overlay updates:"
        echo "  cd $WORKTREE_PATH && git fetch && git merge master"
    fi
    echo ""
    echo "To work in this worktree:"
    echo "  cd $WORKTREE_PATH"
    echo ""
    echo "To remove worktree later:"
    echo "  $0 delete $branch"
}

# Resolve a (possibly empty) branch arg to a target worktree path.
# Empty arg means the legacy ../melee-pr path (back-compat).
target_worktree_path() {
    local branch="$1"
    if [[ -n "$branch" ]]; then
        resolve_worktree "$branch"
        echo "$WORKTREE_PATH"
    else
        echo "$(dirname "$REPO_ROOT")/melee-pr"
    fi
}

cmd_delete() {
    local branch="${1:-}"
    local worktree_path
    worktree_path="$(target_worktree_path "$branch")"

    if [[ ! -d "$worktree_path" ]]; then
        echo "No worktree found at $worktree_path"
        exit 0
    fi

    echo "=== Removing Worktree ==="
    echo ""
    echo "Location: $worktree_path"

    # Check for uncommitted changes
    cd "$worktree_path"
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
    git worktree remove "$worktree_path" --force

    echo -e "${GREEN}Worktree removed${NC}"
}

cmd_status() {
    local branch="${1:-}"
    local worktree_path
    worktree_path="$(target_worktree_path "$branch")"

    if [[ ! -d "$worktree_path" ]]; then
        echo "No worktree exists at $worktree_path."
        echo "Create one with: $0 create <pr/topic|wip/topic>"
        exit 0
    fi

    echo "=== Worktree Status ==="
    echo ""
    echo "Location: $worktree_path"

    cd "$worktree_path"
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
        cmd_delete "$2"
        ;;
    status)
        cmd_status "$2"
        ;;
    *)
        echo "Usage: $0 <command> [args]"
        echo ""
        echo "Commands:"
        echo "  create <pr/topic|wip/topic>  Create worktree for branch"
        echo "  delete [branch]              Remove worktree (defaults to ../melee-pr)"
        echo "  status [branch]              Show worktree status"
        exit 1
        ;;
esac
