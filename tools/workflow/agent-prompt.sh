#!/bin/bash
# agent-prompt.sh - Generate a /goal prompt for a decomp agent
#
# Usage:
#   ./tools/workflow/agent-prompt.sh <branch> [scope-description]
#   ./tools/workflow/agent-prompt.sh --list
#   ./tools/workflow/agent-prompt.sh --help
#
# Looks up the worktree checked out on <branch>, derives the module from
# the branch name (wip/<module>[-<topic>] or pr/<module>[-<topic>]), and
# prints a /goal prompt suitable for pasting into a decomp agent session.
#
# Output is kept under /goal's 4000-character limit by referencing repo
# docs instead of duplicating their content. CLAUDE.md (a.k.a. AGENTS.md)
# is auto-loaded by Claude Code at session start, so this prompt focuses
# on per-agent specifics + the unique rules/conventions not already in
# CLAUDE.md or docs/.
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
    SCOPE_DESC="src/melee/$MODULE/ (be specific; other agents work adjacent modules)"
fi

# Module-specific notes doc, if it exists.
MODULE_NOTES_HINT=""
if [[ -f "$MAIN_REPO/docs/${MODULE}-module-notes.md" ]]; then
    MODULE_NOTES_HINT=", docs/${MODULE}-module-notes.md"
fi

cat << PROMPT
You're on $BRANCH in $WORKTREE ($MODULE module).
Focus: $SCOPE_DESC. Don't touch files outside scope.

Read first: docs/parallel-agent-workflow.md (canonical agent flow) and
.agents/skills/decomp/SKILL.md (matching workflow). Also:
docs/mwcc-pattern-book.md, docs/agent-tool-manifest.md,
docs/large-function-checkpoint.md${MODULE_NOTES_HINT}.
CLAUDE.md is auto-loaded — covers CLI commands, branch model, PR hygiene.

## Setup (60s)

cd $WORKTREE
python tools/worktree-doctor.py --fix    # heal anything red
git fetch --all --prune
./tools/workflow/sync-hooks.sh           # pick up master overlay
git status --short && git branch --show-current

## Core loop

melee-agent extract list --module $MODULE --max-match 0.5    # find targets
python tools/checkdiff.py <fn>                                # diff → edit → ninja → re-check
melee-agent attempts record <fn> --outcome <kind> --note "..."  # log saturation

## Rules (overrides/additions beyond the docs)

- Match % drop ≠ unviable, but unless you have reason to stack changes, revert.
- 10 attempts on a fn with no progress → log + move on.
- A pattern that works in one place often applies elsewhere in the TU — go
  back and apply it even to functions you'd "moved on" from.
- Commit per matched fn. Prepare for PR when the full TU (.text + data) is at 100%.
- **Don't chase data-section matches before the TU's .text is fully matched.**
  Named struct fields / float constants / unk_NN renames add ~zero reviewer
  value until every function body is at 100%. Bundle that polish with the
  final matches. Per ribbanya (project lead): "I just wouldn't bother in general."
- Stuck? Missing inline(s) is the answer to ~75% of matches.

## Opening the PR (you're empowered to do it yourself)

Don't open a PR that's only data-section refinement on a partially-matched TU
(see rule above). Otherwise:

  ./tools/workflow/create-pr.sh $MODULE-<short-topic>
  git push origin pr/$MODULE-<short-topic>
  gh pr create --repo doldecomp/melee --base master \\
    --head itsgrimetime:pr/$MODULE-<short-topic> \\
    --title "$MODULE: <one-line summary>" \\
    --body "\$(cat <<'EOF'
## Summary
<1-3 bullets>

## Functions matched
- fn_XXXXXXXX: 100%

## Files
<list>

## Verification
- \`python configure.py && ninja\` → green
EOF
)"

PR text hygiene: no fork-tooling mentions. See CLAUDE.md "PR description hygiene".

## Tooling fixes (separate flow)

Fork tooling lives on master at $MAIN_REPO. Edit there, commit + push origin
master, then run sync-hooks.sh in your worktree to pick it up.

## Cadence

The heartbeat is anti-stall, not a stop signal. Plan for 1-2h continuous work.
PROMPT
