#!/bin/bash
# agent-prompt.sh - Generate a /loop prompt for a decomp agent
#
# Usage:
#   ./tools/workflow/agent-prompt.sh <branch> [scope-description]
#   ./tools/workflow/agent-prompt.sh --list
#   ./tools/workflow/agent-prompt.sh --help
#
# Looks up the worktree checked out on <branch>, derives the module from
# the branch name (wip/<module>[-<topic>] or pr/<module>[-<topic>]), and
# prints a /loop prompt suitable for pasting into a decomp agent session.
#
# Examples:
#   ./tools/workflow/agent-prompt.sh wip/lb-mthp
#   ./tools/workflow/agent-prompt.sh wip/lb-mthp 'lbmthp.{c,h,static.h} + lb_01F8.c'
#   ./tools/workflow/agent-prompt.sh wip/mn-heartbeat 'broad mn/ refactor + gm/gm_1601'
#   ./tools/workflow/agent-prompt.sh --list

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# git-common-dir returns a path relative to git's cwd; cd there first so dirname resolves correctly.
MAIN_REPO="$(cd "$SCRIPT_DIR" && cd "$(git rev-parse --git-common-dir)/.." && pwd)"

usage() {
    awk '
        NR == 1            { next }
        /^set -e/          { exit }
        /^# /              { sub(/^# /, ""); print; next }
        /^#$/              { print ""; next }
        /^$/               { print ""; next }
    ' "$0"
}

list_branches() {
    echo "wip/* and pr/* branches with worktrees:"
    git -C "$MAIN_REPO" worktree list --porcelain | awk '
        /^worktree / { wt = $2 }
        /^branch refs\/heads\/(wip|pr)\// {
            ref = $2
            sub(/^refs\/heads\//, "", ref)
            printf "  %-36s  %s\n", ref, wt
        }
    '
}

case "${1:-}" in
    -h|--help)
        usage
        exit 0
        ;;
    --list|-l)
        list_branches
        exit 0
        ;;
    "")
        echo "Usage: $0 <branch> [scope-description]" >&2
        echo "       $0 --list" >&2
        echo "       $0 --help" >&2
        exit 1
        ;;
esac

BRANCH="$1"
SCOPE_DESC="${2:-}"

# Find worktree path for this branch (must already exist).
WORKTREE="$(git -C "$MAIN_REPO" worktree list --porcelain | awk -v want="refs/heads/$BRANCH" '
    /^worktree / { wt = $2 }
    /^branch / && $2 == want { print wt; found=1; exit }
    END { if (!found) exit 1 }
' || true)"

if [[ -z "$WORKTREE" ]]; then
    echo "Error: no worktree checked out on branch '$BRANCH'" >&2
    echo "" >&2
    list_branches >&2
    exit 1
fi

# Derive module from branch name.
case "$BRANCH" in
    wip/*-*|wip/*)
        TOPIC="${BRANCH#wip/}"
        MODULE="${TOPIC%%-*}"
        ;;
    pr/*-matching-cleanups)
        STRIPPED="${BRANCH#pr/}"
        MODULE="${STRIPPED%-matching-cleanups}"
        ;;
    pr/*-*|pr/*)
        TOPIC="${BRANCH#pr/}"
        MODULE="${TOPIC%%-*}"
        ;;
    *)
        echo "Error: branch must be wip/<topic> or pr/<topic> (got '$BRANCH')" >&2
        exit 1
        ;;
esac

# Default scope description if not provided.
if [[ -z "$SCOPE_DESC" ]]; then
    SCOPE_DESC="src/melee/$MODULE/ (be specific about which files — other agents may be on adjacent modules)"
fi

cat << PROMPT
/loop 20m

You're working in $WORKTREE on branch $BRANCH.
Focus: $SCOPE_DESC. Avoid touching files outside that scope — other agents
are working on adjacent modules.

If anything looks unexpected at session start (renamed branches, rebased
master, missing tooling), run worktree-doctor first.

## Setup (first 60 seconds, every invocation)

cd $WORKTREE
python tools/worktree-doctor.py        # if red, --fix or investigate
git fetch --all --prune
./tools/workflow/sync-hooks.sh         # pick up hook/overlay updates from master
git status --short && git branch --show-current

## Core loop (per function)

1. Pick next function in scope: melee-agent extract list --module $MODULE --max-match 0.5
2. python tools/checkdiff.py <function>      # see current diff
3. Edit src/melee/$MODULE/<file>.c
4. ninja build/GALE01/src/melee/$MODULE/<file>.o
5. python tools/checkdiff.py <function>      # re-check

Rules:
- If match % drops, revert immediately — don't fix forward.
- After 3 attempts with no improvement on the same fn: log via
  melee-agent attempts record <fn> --outcome saturated --classification <kind> --note "..."
  then move on.
- After 10 total attempts on a function with no progress, fully document and skip;
  come back only if you spot a similar pattern elsewhere.
- When a fn hits 100%: commit to this branch with a descriptive message.

## When stuck (use the tooling — don't spin)

- /mismatch-db search "<pattern>"         # known patterns + fixes
- /discord-knowledge search "<term>"       # 6+ years of community knowledge
- /opseq <function>                        # find similar matched functions
- /ppc-ref <instruction>                   # instruction docs
- melee-agent patterns inlines src/melee/$MODULE/<file>.c   # stubborn PAD_STACK usually = missing inline
- /understand <fn>                         # name & document before re-attempting

Slow-down move: step back from the ASM. Understand what the function actually
DOES — callers, callees, intent. Replicate the high-level behavior in C, not
the ASM line-by-line.

## When you have a coherent batch ready

You decide when. Defaults: 1+ functions matched, build green, src-only changes.
You're empowered to open the PR yourself — no need to ask first.

  ./tools/workflow/create-pr.sh $MODULE-<short-topic>
  git push origin pr/$MODULE-<short-topic>
  gh pr create --repo doldecomp/melee \\
    --base master \\
    --head itsgrimetime:pr/$MODULE-<short-topic> \\
    --title "$MODULE: <one-line summary of what you matched>" \\
    --body "\$(cat <<'EOF'
## Summary

<1-3 bullets on what changed and why>

## Functions matched

- fn_XXXXXXXX: 100%
- ...

## Files

<list of src/include/config files touched>

## Verification

- \`python configure.py && ninja\` → green
- <any notable match% improvements or behaviors>
EOF
)"

PR text hygiene: describe matched functions, source layout, type changes,
verification. Do NOT mention fork tooling (melee-agent, checkdiff.py,
attempts ledger, worktree-doctor) — upstream visibility only.
See CLAUDE.md "PR description hygiene".

## Branch hygiene

- Commit only matched, build-green work to this branch.
- If you stop mid-batch, leave a "wip:" commit so the next session has clean handoff.
- Do NOT commit fork tooling changes from this branch.

## Tooling improvements (separate from decomp)

If you want to improve fork tooling during decomp work:
  cd $MAIN_REPO && git checkout master
  <make tooling change>
  git commit && git push origin master
Then back in your worktree: git fetch && git merge master.
Other agents should run ./tools/workflow/sync-hooks.sh to pick up hook updates.

## Upstream sync

We rebase from doldecomp/melee every few days. If master is >5 commits behind
upstream, that's a signal — but coordinate before running sync-upstream.sh,
it affects all agents.

## Cadence

Don't end after 1-2 iterations. The heartbeat is a stall-prevention nudge,
not a stop signal. Plan for 1-2 hours of continuous work per invocation.
PROMPT
