#!/bin/bash
# agent-prompt.sh - Generate a /goal prompt for a decomp agent
#
# Usage:
#   ./tools/workflow/agent-prompt.sh <branch> [scope] [-g "goal"] [-d "directive"]
#   ./tools/workflow/agent-prompt.sh --list
#   ./tools/workflow/agent-prompt.sh --help
#
# Prints a /goal-ready prompt starting with `/goal <text>` (default: match all
# the module's TUs to 100%) plus the per-agent context. Stays under /goal's
# 4000-character limit by keeping the per-agent body concise; longer-form
# guidance lives in CLAUDE.md (auto-loaded) and docs/.
#
# Positional args:
#   branch      wip/<module>[-<topic>] or pr/<module>[-<topic>]
#   scope       optional file-scope description (defaults to src/melee/<module>/)
#
# Flags:
#   -g, --goal "<text>"        override the /goal mission line
#                              (default: "Match all <module> translation units (TUs) to 100%")
#   -d, --directive "<text>"   optional "Immediate directive" appended for session resume
#
# Examples:
#   ./tools/workflow/agent-prompt.sh wip/ty-toy
#   ./tools/workflow/agent-prompt.sh wip/ty-toy 'toy.c + toy.h'
#   ./tools/workflow/agent-prompt.sh wip/ty-toy -g "Push fn_8001D2A8 to 100%"
#   ./tools/workflow/agent-prompt.sh wip/ty-toy -d "Resume — your toy.c work is intact"

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

BRANCH=""
SCOPE_DESC=""
GOAL=""
DIRECTIVE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --list|-l)
            list_branches
            exit 0
            ;;
        -g|--goal)
            GOAL="$2"
            shift 2
            ;;
        -d|--directive)
            DIRECTIVE="$2"
            shift 2
            ;;
        -*)
            echo "Unknown flag: $1" >&2
            exit 1
            ;;
        *)
            if [[ -z "$BRANCH" ]]; then
                BRANCH="$1"
            elif [[ -z "$SCOPE_DESC" ]]; then
                SCOPE_DESC="$1"
            else
                echo "Unexpected positional arg: $1" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$BRANCH" ]]; then
    echo "Usage: $0 <branch> [scope] [-g goal] [-d directive]" >&2
    echo "       $0 --list" >&2
    echo "       $0 --help" >&2
    exit 1
fi

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
    SCOPE_DESC="src/melee/$MODULE/ (be specific; other agents may be on adjacent modules)"
fi

# Default goal if not provided.
if [[ -z "$GOAL" ]]; then
    GOAL="Match all $MODULE translation units (TUs) to 100%"
fi

# Optional module-specific notes doc hint.
MODULE_NOTES_HINT=""
if [[ -f "$MAIN_REPO/docs/${MODULE}-module-notes.md" ]]; then
    MODULE_NOTES_HINT=" Also: docs/${MODULE}-module-notes.md."
fi

cat << PROMPT
/goal $GOAL

You're working in $WORKTREE on branch $BRANCH.
Focus: $SCOPE_DESC. Avoid touching files outside that scope — other agents
are working on adjacent modules.

If anything looks unexpected at session start (renamed branches, rebased
master, missing tooling), run worktree-doctor first.

## Setup

cd $WORKTREE
python tools/worktree-doctor.py --fix  # apply safe local bootstrap repairs
git fetch --all --prune
./tools/workflow/sync-hooks.sh         # pick up hook/overlay updates from master
git status --short && git branch --show-current

## Core loop (per function)

Use the /decomp skill.

**Read all four metrics on every checkdiff, not just match%.** checkdiff now
prints opcode similarity, line delta, and hunk count alongside match% — and
shows deltas vs your previous run. Match% can drop while structure improves
(register/operand diffs keep match% low even when the shape is now correct).
If checkdiff prints a NOTE about structural progress, treat it seriously:
read the full diff and decide if you're closer to the true match before
reverting. Reflexive revert on match% drop alone is a known anti-pattern.

When you've gotten enough clean matches/improvements in a single TU, clean it
up per community & project guidelines and prepare a PR.

PR scope rules (per pr-scope-expectations memory + ribbanya feedback on #2506/#2507):
- Bar: substantial enough for a maintainer review cycle — multiple matches
  or one fn reaching 100% as part of moving a TU forward.
- NOT OK: single partial-match nudge (one fn 89%→95%, no 100%), data-section
  refinement on a TU whose .text isn't fully matched, header tidies alone.
- Data-section work (named struct fields, named constants, unk_NN renames)
  adds ~zero reviewer value until every .text fn is at 100% — bundle with matches.

## When stuck

- /mismatch-db search "<pattern>"        # known patterns + fixes
- /discord-knowledge search "<term>"      # 6+ years of community knowledge
- /opseq <function>                       # find similar matched functions
- /ppc-ref <instruction>                  # instruction docs
- melee-agent patterns inlines src/melee/$MODULE/<file>.c   # stubborn PAD_STACK = missing inline
- /understand <fn>                        # name & document before re-attempting

**Step back from the ASM. Understand what the function DOES — callers, callees,
intent. Replicate the high-level behavior in C, not the ASM line-by-line.
/understand can help. Think about how a developer of that era, with that
tooling, would have written it. Don't try to replicate ASM instruction by
instruction.**

**When in doubt: you're probably missing an inline, multiple inlines, or your
existing inlines are wrong. Inline tricks are the key to ~75% of matches.**

PR text hygiene: describe matched functions, source layout, type changes,
verification. Do NOT mention fork tooling (melee-agent, checkdiff.py, attempts
ledger, worktree-doctor) — upstream visibility only.
See CLAUDE.md "PR description hygiene".${MODULE_NOTES_HINT}

## Branch hygiene

- Commit only matched, build-green work to this branch.
- If you stop mid-batch, leave a "wip:" commit so the next session has a clean handoff.
- Do NOT commit fork tooling changes from this branch.

## Tooling improvements (separate from decomp)

If you need to improve fork tooling during decomp work:
  cd $MAIN_REPO && git checkout master
  <make tooling change>
  git commit && git push origin master
Back in your worktree: git fetch && git merge master. Other agents pick up via
./tools/workflow/sync-hooks.sh.

## Upstream sync

We rebase from doldecomp/melee every few days. If master is >5 commits behind
upstream, that's a signal — coordinate before sync-upstream.sh, it affects all agents.
PROMPT

if [[ -n "$DIRECTIVE" ]]; then
    cat << DIRECTIVE_BLOCK

## Immediate directive

$DIRECTIVE
DIRECTIVE_BLOCK
fi
