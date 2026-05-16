#!/bin/bash
# cleanup-stale.sh - Report on stale git worktrees
#
# Usage: ./tools/workflow/cleanup-stale.sh [--apply]
#
# Read-only report by default. Lists every worktree with branch, path, age,
# dirty file count, and ahead/behind master. Flags worktrees as stale
# candidates if they have not received a commit in 30 days.
#
# With --apply, prints the exact `git worktree remove` commands needed to
# delete the stale candidates. The script does NOT execute them; the user
# runs them manually after reviewing.
#
# The main worktree (master) is always skipped.

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

APPLY=false
if [[ "$1" == "--apply" ]]; then
    APPLY=true
fi

STALE_DAYS=30
NOW=$(date +%s)
STALE_CUTOFF=$((NOW - STALE_DAYS * 86400))

MAIN_WT=$(git rev-parse --path-format=absolute --git-common-dir | xargs dirname)

echo -e "${BOLD}=== Worktree Cleanup Report ===${NC}"
echo ""
echo "Stale threshold: ${STALE_DAYS} days since last commit on HEAD"
echo "Main worktree (skipped): $MAIN_WT"
echo ""

# Collect worktree records into parallel arrays
PATHS=()
HEADS=()
BRANCHES=()

current_path=""
current_head=""
current_branch=""

flush_record() {
    if [[ -n "$current_path" ]]; then
        PATHS+=("$current_path")
        HEADS+=("$current_head")
        BRANCHES+=("$current_branch")
    fi
    current_path=""
    current_head=""
    current_branch=""
}

while IFS= read -r line; do
    if [[ -z "$line" ]]; then
        flush_record
        continue
    fi
    key=${line%% *}
    val=${line#* }
    case "$key" in
        worktree) current_path="$val" ;;
        HEAD) current_head="$val" ;;
        branch) current_branch="${val#refs/heads/}" ;;
        detached) current_branch="(detached)" ;;
    esac
done < <(git worktree list --porcelain)
flush_record

# Print header
printf "${BOLD}%-60s %-35s %5s %6s %8s %8s${NC}\n" \
    "PATH" "BRANCH" "AGE" "DIRTY" "AHEAD" "BEHIND"
printf '%s\n' "------------------------------------------------------------------------------------------------------------------------------"

STALE_PATHS=()
STALE_REASONS=()

for i in "${!PATHS[@]}"; do
    wt_path="${PATHS[$i]}"
    head="${HEADS[$i]}"
    branch="${BRANCHES[$i]}"

    # Skip main worktree
    if [[ "$wt_path" == "$MAIN_WT" ]]; then
        continue
    fi

    # Age (days since last commit on HEAD)
    last_commit_ts=$(git log -1 --format=%ct "$head" 2>/dev/null || echo "")
    if [[ -n "$last_commit_ts" ]]; then
        age_days=$(( (NOW - last_commit_ts) / 86400 ))
    else
        age_days="?"
    fi

    # Dirty file count - run in the worktree directory if accessible
    if [[ -d "$wt_path" ]]; then
        dirty=$(git -C "$wt_path" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    else
        dirty="N/A"
    fi

    # Ahead/behind master (using the head commit, so it works for detached too)
    if git rev-parse --verify master >/dev/null 2>&1; then
        ahead=$(git rev-list --count master.."$head" 2>/dev/null || echo "?")
        behind=$(git rev-list --count "$head"..master 2>/dev/null || echo "?")
    else
        ahead="?"
        behind="?"
    fi

    # Determine staleness
    stale_reason=""
    if [[ "$age_days" != "?" && "$age_days" -gt "$STALE_DAYS" ]]; then
        stale_reason="no commits in ${age_days}d"
    fi
    if [[ ! -d "$wt_path" ]]; then
        if [[ -n "$stale_reason" ]]; then
            stale_reason="$stale_reason; missing dir"
        else
            stale_reason="missing dir"
        fi
    fi

    # Format row with color if stale
    if [[ -n "$stale_reason" ]]; then
        printf "${YELLOW}%-60s %-35s %5s %6s %8s %8s${NC}\n" \
            "$wt_path" "$branch" "${age_days}d" "$dirty" "$ahead" "$behind"
        STALE_PATHS+=("$wt_path")
        STALE_REASONS+=("$stale_reason")
    else
        printf "%-60s %-35s %5s %6s %8s %8s\n" \
            "$wt_path" "$branch" "${age_days}d" "$dirty" "$ahead" "$behind"
    fi
done

echo ""

# Candidates section
if [[ ${#STALE_PATHS[@]} -eq 0 ]]; then
    echo -e "${GREEN}No stale candidates found.${NC}"
    exit 0
fi

echo -e "${CYAN}${BOLD}Candidates for deletion (${#STALE_PATHS[@]}):${NC}"
for i in "${!STALE_PATHS[@]}"; do
    echo -e "  ${YELLOW}${STALE_PATHS[$i]}${NC}  -- ${STALE_REASONS[$i]}"
done
echo ""

if [[ "$APPLY" == true ]]; then
    echo -e "${CYAN}${BOLD}Commands to remove stale worktrees:${NC}"
    echo -e "${YELLOW}# Review each command before running. This script does NOT execute them.${NC}"
    echo ""
    for wt_path in "${STALE_PATHS[@]}"; do
        # Use --force only if the directory is missing (broken worktree)
        if [[ -d "$wt_path" ]]; then
            echo "git worktree remove \"$wt_path\""
        else
            echo "git worktree remove --force \"$wt_path\"  # missing directory"
        fi
    done
    echo ""
    echo -e "${CYAN}After removal, prune any stale admin entries:${NC}"
    echo "git worktree prune"
else
    echo -e "Run with ${BOLD}--apply${NC} to print removal commands."
fi

echo ""
