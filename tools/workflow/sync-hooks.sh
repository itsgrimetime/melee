#!/bin/bash
# sync-hooks.sh - Propagate master's tooling overlay to active worktrees
#
# Usage:
#   ./tools/workflow/sync-hooks.sh             # dry-run (default)
#   ./tools/workflow/sync-hooks.sh --apply     # actually copy
#   ./tools/workflow/sync-hooks.sh --help
#
# Why this exists:
#   Master can update .claude-plugin/melee-decomp/hooks/scripts/*.sh and
#   .git/hooks/* but those copies don't auto-refresh in existing worktrees.
#   Concrete example: commit 889686142 removed the "git add is not allowed"
#   block from validate-bash.sh on master at 17:00, but an agent session
#   that started at 23:38 in another worktree still hit the block 21 times
#   because its per-worktree copy wasn't refreshed.
#
#   This script propagates master's overlay so hook fixes reach worktrees
#   that already exist.
#
# Scope (per worktree):
#   Synced  = HEAD commit within last 30 days AND branch is one of
#             master, wip/*, codex/*, tooling/*.
#   Skipped = pr/* (intentionally no overlay), stale (handled separately),
#             detached HEAD, the main repo itself (it's the source).
#
# What gets synced:
#   - .claude-plugin/   (mirror of master's tree, --delete semantics)
#   - .agents/          (mirror of master's tree, if present on master)
#   - <git-common-dir>/hooks/*  (copied from main repo's .git/hooks/;
#     worktrees that share the main repo's .git already share these,
#     so this is a no-op for them and reported as such).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

APPLY=false
STALE_DAYS=30

# Paths to sync from master's tree (relative to repo root).
# Skills live under .claude/skills/ (Claude's native layout) and are exposed
# to Codex via the .codex/skills symlink. Both paths get propagated so every
# agent (regardless of provider) sees the same skill set.
OVERLAY_PATHS=(
    ".claude-plugin"
    ".claude/skills"
    ".codex"
)

# Branch prefixes that should receive the overlay.
ACTIVE_PREFIXES=(
    "master"
    "wip/"
    "codex/"
    "tooling/"
)

while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply)
            APPLY=true
            shift
            ;;
        --stale-days)
            STALE_DAYS="$2"
            shift 2
            ;;
        --help|-h)
            sed -n '2,31p' "$0" | sed 's|^# \{0,1\}||'
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown argument: $1${NC}"
            echo "Usage: $0 [--apply] [--stale-days N]"
            exit 1
            ;;
    esac
done

echo -e "${BOLD}=== Sync Overlay to Active Worktrees ===${NC}"
echo ""
if [[ "$APPLY" == "true" ]]; then
    echo -e "${YELLOW}Mode: APPLY${NC} (files will be written)"
else
    echo -e "${CYAN}Mode: DRY-RUN${NC} (no changes; pass --apply to write)"
fi
echo "Source: $REPO_ROOT (master)"
echo "Stale threshold: ${STALE_DAYS} days"
echo ""

# --- Materialize master's overlay into a temp dir ---
# Using `git archive` decouples us from REPO_ROOT's working-tree state
# (e.g., if the user has uncommitted changes in .claude-plugin).
STAGE=$(mktemp -d -t sync-hooks-stage.XXXXXX)
trap 'rm -rf "$STAGE"' EXIT

MASTER_PATHS=()
for p in "${OVERLAY_PATHS[@]}"; do
    if git -C "$REPO_ROOT" cat-file -e "master:$p" 2>/dev/null; then
        MASTER_PATHS+=("$p")
    fi
done

if [[ ${#MASTER_PATHS[@]} -eq 0 ]]; then
    echo -e "${RED}Error: master has none of the expected overlay paths${NC}"
    exit 1
fi

git -C "$REPO_ROOT" archive master -- "${MASTER_PATHS[@]}" \
    | tar -x -C "$STAGE"

MAIN_COMMON_DIR=$(git -C "$REPO_ROOT" rev-parse --git-common-dir)
MAIN_COMMON_DIR=$(cd "$REPO_ROOT" && cd "$MAIN_COMMON_DIR" && pwd)
MAIN_HOOKS_DIR="$MAIN_COMMON_DIR/hooks"

NOW=$(date +%s)
STALE_CUTOFF=$((NOW - STALE_DAYS * 86400))

# --- Collect worktree records ---
# Parse `git worktree list --porcelain` into a TSV (path \t head \t branch).
WORKTREE_TSV=$(git -C "$REPO_ROOT" worktree list --porcelain | awk '
    /^worktree / { wt = substr($0, 10); head = ""; br = "" }
    /^HEAD /     { head = $2 }
    /^branch /   { br = substr($2, 12) }   # strip "refs/heads/"
    /^detached/  { br = "(detached)" }
    /^$/         { if (wt != "") { print wt "\t" head "\t" br; wt = "" } }
    END          { if (wt != "") print wt "\t" head "\t" br }
')

classify_branch() {
    local br="$1"
    case "$br" in
        "")           echo "no-branch" ;;
        "(detached)") echo "detached" ;;
        pr/*)         echo "pr" ;;
        master)       echo "master" ;;
        wip/*)        echo "wip" ;;
        codex/*)      echo "codex" ;;
        tooling/*)    echo "tooling" ;;
        *)            echo "other" ;;
    esac
}

# rsync -c uses checksum to decide whether to transfer, but its itemized
# output still lists files where only attrs like mtime differ (lines that
# start with "."). Filter those out — they don't represent real work.
rsync_diff() {
    local src="$1" dst="$2"
    shift 2
    rsync -rclni "$@" "$src/" "$dst/" 2>/dev/null | grep -vE '^\.|^$' || true
}

# Returns 0 if path needs syncing, 1 if already in sync.
needs_sync() {
    local src="$1" dst="$2"
    if [[ ! -d "$dst" ]]; then
        return 0
    fi
    local out
    out=$(rsync_diff "$src" "$dst" --delete)
    [[ -n "$out" ]]
}

# Returns 0 if the two hook dirs are identical, 1 otherwise.
hooks_in_sync() {
    local src="$1" dst="$2"
    if [[ ! -d "$dst" ]]; then
        return 1
    fi
    local out
    out=$(rsync_diff "$src" "$dst")
    [[ -z "$out" ]]
}

# Track results for end-of-run summary.
COUNT_SOURCE=0
COUNT_SYNCED=0
COUNT_ALREADY=0
COUNT_SKIPPED=0
COUNT_ERROR=0

printf "%-72s  %s\n" "WORKTREE" "STATUS"
printf '%s\n' "$(printf '%.0s-' {1..120})"

while IFS=$'\t' read -r wt head branch; do
    [[ -z "$wt" ]] && continue

    label="$wt"
    [[ ${#label} -gt 72 ]] && label="...${label: -69}"

    # Skip the main repo (it's the source).
    if [[ "$wt" == "$REPO_ROOT" ]]; then
        printf "%-72s  ${CYAN}%s${NC}\n" "$label" "source (skipped)"
        COUNT_SOURCE=$((COUNT_SOURCE + 1))
        continue
    fi

    # Missing on disk (e.g., worktree was deleted but not pruned).
    if [[ ! -d "$wt" ]]; then
        printf "%-72s  ${YELLOW}%s${NC}\n" "$label" "skipped (path missing — run 'git worktree prune')"
        COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
        continue
    fi

    kind=$(classify_branch "$branch")

    case "$kind" in
        pr)
            printf "%-72s  ${CYAN}%s${NC}\n" "$label" "skipped (pr/* — no overlay by design)"
            COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
            continue
            ;;
        detached|no-branch)
            printf "%-72s  ${CYAN}%s${NC}\n" "$label" "skipped (detached HEAD)"
            COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
            continue
            ;;
        other)
            printf "%-72s  ${CYAN}%s${NC}\n" "$label" "skipped (branch '$branch' not in sync scope)"
            COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
            continue
            ;;
    esac

    # Staleness check based on HEAD commit time.
    head_ts=$(git -C "$REPO_ROOT" log -1 --format=%ct "$head" 2>/dev/null || echo "0")
    if [[ "$head_ts" -lt "$STALE_CUTOFF" ]]; then
        age_days=$(( (NOW - head_ts) / 86400 ))
        printf "%-72s  ${CYAN}%s${NC}\n" "$label" "skipped (stale — last commit ${age_days}d ago)"
        COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
        continue
    fi

    # --- Decide what work this worktree needs ---
    actions=()
    errors=()

    for p in "${MASTER_PATHS[@]}"; do
        src="$STAGE/$p"
        dst="$wt/$p"
        if needs_sync "$src" "$dst"; then
            actions+=("$p")
        fi
    done

    # .git/hooks handling: only act when the worktree's common-dir differs
    # from the main repo's. When they're the same (typical case), the hooks
    # dir is literally shared, so nothing to copy.
    wt_common_dir=$(git -C "$wt" rev-parse --git-common-dir 2>/dev/null || echo "")
    if [[ -n "$wt_common_dir" ]]; then
        wt_common_dir=$(cd "$wt" && cd "$wt_common_dir" && pwd)
    fi
    hooks_action=""
    if [[ -z "$wt_common_dir" ]]; then
        errors+=("cannot resolve git-common-dir")
    elif [[ "$wt_common_dir" == "$MAIN_COMMON_DIR" ]]; then
        hooks_action="shared"
    else
        wt_hooks_dir="$wt_common_dir/hooks"
        if ! hooks_in_sync "$MAIN_HOOKS_DIR" "$wt_hooks_dir"; then
            actions+=(".git/hooks")
            hooks_action="copy:$wt_hooks_dir"
        fi
    fi

    if [[ ${#errors[@]} -gt 0 ]]; then
        printf "%-72s  ${RED}%s${NC}\n" "$label" "error (${errors[*]})"
        COUNT_ERROR=$((COUNT_ERROR + 1))
        continue
    fi

    if [[ ${#actions[@]} -eq 0 ]]; then
        suffix=""
        [[ "$hooks_action" == "shared" ]] && suffix=" (hooks shared via $MAIN_COMMON_DIR)"
        printf "%-72s  ${GREEN}%s${NC}\n" "$label" "in sync${suffix}"
        COUNT_ALREADY=$((COUNT_ALREADY + 1))
        continue
    fi

    if [[ "$APPLY" == "false" ]]; then
        printf "%-72s  ${YELLOW}%s${NC}\n" "$label" "would sync: ${actions[*]}"
        COUNT_SYNCED=$((COUNT_SYNCED + 1))
        continue
    fi

    # --- Apply ---
    failed=false
    for p in "${MASTER_PATHS[@]}"; do
        src="$STAGE/$p"
        dst="$wt/$p"
        # Skip if this path wasn't in the action list.
        wanted=false
        for a in "${actions[@]}"; do
            [[ "$a" == "$p" ]] && wanted=true && break
        done
        $wanted || continue
        mkdir -p "$dst"
        if ! rsync -rcl --delete "$src/" "$dst/" 2>/dev/null; then
            errors+=("rsync $p failed")
            failed=true
        fi
    done

    if [[ "$hooks_action" == copy:* ]]; then
        wt_hooks_dir="${hooks_action#copy:}"
        mkdir -p "$wt_hooks_dir"
        if ! rsync -rcl "$MAIN_HOOKS_DIR/" "$wt_hooks_dir/" 2>/dev/null; then
            errors+=("rsync .git/hooks failed")
            failed=true
        fi
    fi

    if $failed; then
        printf "%-72s  ${RED}%s${NC}\n" "$label" "error (${errors[*]})"
        COUNT_ERROR=$((COUNT_ERROR + 1))
    else
        printf "%-72s  ${GREEN}%s${NC}\n" "$label" "synced: ${actions[*]}"
        COUNT_SYNCED=$((COUNT_SYNCED + 1))
    fi
done <<< "$WORKTREE_TSV"

echo ""
echo -e "${BOLD}=== Summary ===${NC}"
echo -e "  source:      $COUNT_SOURCE"
echo -e "  in sync:     $COUNT_ALREADY"
if [[ "$APPLY" == "true" ]]; then
    echo -e "  synced:      $COUNT_SYNCED"
else
    echo -e "  would sync:  $COUNT_SYNCED"
fi
echo -e "  skipped:     $COUNT_SKIPPED"
if [[ "$COUNT_ERROR" -gt 0 ]]; then
    echo -e "  ${RED}errors:      $COUNT_ERROR${NC}"
fi

if [[ "$APPLY" == "false" && "$COUNT_SYNCED" -gt 0 ]]; then
    echo ""
    echo -e "${YELLOW}Re-run with --apply to perform the sync.${NC}"
fi

if [[ "$COUNT_ERROR" -gt 0 ]]; then
    exit 1
fi
