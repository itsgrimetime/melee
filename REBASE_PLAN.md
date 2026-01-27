# Comprehensive Rebase Plan

## Current Situation

### Repository State
- **master**: 71 commits ahead, 9 commits behind upstream/master
- **origin**: itsgrimetime/melee (our fork)
- **upstream**: doldecomp/melee (canonical)
- **Merge-base**: `f52bd69a5` (PR #2126)

### Worktrees
| Worktree | Branch | Commits Ahead | Focus |
|----------|--------|---------------|-------|
| melee-2 | `pr/mndiagram2` | 7 | mnDiagram2 improvements |
| melee-3 | `melee-3` | 39 | mnvibration, mnsoundtest WIP |

### Key Insight
PR #2129 (`mndiagram, mndiagram2 matches & naming`) was created from our fork and merged upstream. Our master has **continued improvements after that PR** that are not yet upstream:
- `mnDiagram_InputProc` at 84.1%
- `mnDiagram2_HandleInput` at 89.5%
- `mnDiagram_PopupInputProc` matched
- `mnDiagram_GetLeastPlayedFighter` matched
- `mnDiagram_802417D0` at 91.3%
- mnvibration improvements (up to 98%)
- it_802CD4FC (Wobbuffet) at 96.4%

## Strategy Overview

```
                        upstream/master
                              │
                              ▼
    ┌─────────────────────────────────────────────┐
    │  1. Reset master to upstream/master          │
    │  2. Cherry-pick tooling commits (fork-only)  │
    │  3. Create PR branches for decomp work       │
    │  4. Rebase worktrees onto new master         │
    └─────────────────────────────────────────────┘
```

## Phase 1: Backup & Preparation

```bash
# Create backups of ALL branches
git branch backup/master-$(date +%Y%m%d) master
git branch backup/melee-2-$(date +%Y%m%d) pr/mndiagram2
git branch backup/melee-3-$(date +%Y%m%d) melee-3

# Stash any uncommitted changes
git stash push -m "pre-rebase stash"

# Fetch latest from all remotes
git fetch --all
```

## Phase 2: Categorize Our Commits

### Commits to Keep (Tooling - Fork Only)
These stay on our fork, never go upstream:
- `.claude/` - Claude skills, hooks, settings
- `tools/melee-agent/` - Agent CLI
- `tools/melee-vscode/` - VSCode extension
- `docs/discord-knowledge/` - Knowledge base
- `.github/workflows/` - Fork-specific CI

### Commits for New PRs (Decompilation Work)
These should become new upstream PRs, **grouped by module**:

**PR 1: mnDiagram Module** (mndiagram + mndiagram2 + mndiagram3 improvements post-#2129)
- `mnDiagram_InputProc` improvements (84.1%)
- `mnDiagram_PopupInputProc` match
- `mnDiagram_GetLeastPlayedFighter` match
- `mnDiagram_802417D0` improvements (91.3%)
- `mnDiagram2_HandleInput` improvements (89.5%)
- Any mndiagram3 work

**PR 2: mnvibration WIP**
- `fn_802487A8` (87.42%)
- `fn_80248A78` (98.0%)
- Other mnvibration improvements

**Note:** Skipping Wobbuffet (it_802CD4FC) - someone else has a PR in progress for that.

**Note:** The `pr/mndiagram2` branch in melee-2 worktree is the base for PR #2129, which is already merged upstream. No new work there.

## Phase 3: Reset Master to Upstream

```bash
# IMPORTANT: Ensure all worktrees are on their own branches, not master
cd /Users/mike/code/melee-2 && git checkout pr/mndiagram2
cd /Users/mike/code/melee-3 && git checkout melee-3
cd /Users/mike/code/melee

# Hard reset master to upstream
git checkout master
git reset --hard upstream/master

# Verify we now have the 9 upstream commits
git log --oneline -15
```

## Phase 4: Recreate Tooling Layer

Restore all fork-specific files from backup in a single commit:

```bash
# Stage the unstaged tool first (before backup)
git add tools/compare_branch.py

# Checkout fork-specific directories
git checkout backup/master-YYYYMMDD -- \
  tools/ \
  .claude/ \
  docs/ \
  .vscode/ \
  .github/

# Checkout fork-specific root files
git checkout backup/master-YYYYMMDD -- \
  configure.py \
  .gitignore \
  .pre-commit-config.yaml \
  CLAUDE.md \
  decomp.yaml \
  permuter_settings.toml

# Recreate symlinks (git checkout doesn't preserve them properly)
ln -sf CLAUDE.md AGENTS.md
mkdir -p .codex && ln -sf ../.claude/skills .codex/skills

# Create a single commit for all tooling
git add -A
git commit -m "restore fork tooling after upstream sync"
```

## Phase 5: Create PR Branches for Decompilation Work

### PR Branch 1: mnDiagram Module (all mn diagram work)
```bash
git checkout -b pr/mndiagram-module upstream/master

# Cherry-pick mnDiagram improvement commits from backup
# These are commits AFTER PR #2129 was created:
git cherry-pick eafe90d76  # mnDiagram_PopupInputProc match
git cherry-pick 539f75232  # mnDiagram_GetLeastPlayedFighter match
git cherry-pick 80a2458b4  # mnDiagram_802417D0 improvements
git cherry-pick 10efd3d93  # mnDiagram_InputProc improvements
git cherry-pick c6262dae3  # mnDiagram2_HandleInput improvements
git cherry-pick b4ddf496e  # mndiagram (latest)
# May need to resolve conflicts - keep our higher-percentage matches
```

### PR Branch 2: mnvibration WIP
```bash
git checkout -b pr/mnvibration upstream/master

# mnvibration commits to cherry-pick:
# cd9f40b79 - mnvibration: improve fn_802487A8 to 68%
# 6503b981d - mnvibration: improve fn_80248A78 to 94.4% match
# b97ac8d02 - mnvibration: improve fn_802487A8 match (68% -> 78%)
# 67b88e3bd - fn_802487A8: improve match from 77.66% to 86.25%
# 06ae2fb4b - mnvibration: improve fn_802487A8 match to 86.32%
# 8db41407b - mnvibration: improve fn_802487A8 match to 87.42%
# 960b22390 - mnvibration: improve fn_80248A78 match to 94.46%
# abf2fc1d7 - mnvibration: use while loop for correct bottom-test structure
# e4769f54e - mnvibration: Improve fn_80248A78 match to 97.6%
# 193410cf7 - mnvibration: Improve fn_80248A78 match to 98.0%

# May be easier to just checkout the files from backup and squash:
git checkout backup/master-YYYYMMDD -- src/melee/mn/mnvibration.c
git add src/melee/mn/mnvibration.c
git commit -m "mnvibration: improve matches (fn_802487A8 87%, fn_80248A78 98%)"
```

## Phase 6: Handle Worktree Branches

### melee-2 (pr/mndiagram2)
The `pr/mndiagram2` branch is the base for PR #2129, which is already merged upstream.
**Action:** This branch can be deleted or archived - no unique work remains.

```bash
cd /Users/mike/code/melee-2
# Verify no unique work
git log upstream/master..HEAD --oneline
# If empty or all merged, can reset to master
git checkout master
# Or archive the branch
git branch -m pr/mndiagram2 archive/pr-mndiagram2-merged
```

### melee-3 (melee-3)
This branch has 39 commits with valuable WIP work:
- **mnvibration improvements** (already captured in PR branch)
- **mnsoundtest refactoring** (unique to this branch)

**Cleanest approach:** Reset melee-3 to new master, then checkout unique source files:

```bash
cd /Users/mike/code/melee-3

# First, identify unique source files not in master
git diff --name-only master..HEAD -- src/melee/

# Create backup
git branch backup/melee-3-YYYYMMDD

# Reset to new master
git fetch origin
git reset --hard origin/master

# Checkout unique work (mnsoundtest is the main unique file)
git checkout backup/melee-3-YYYYMMDD -- src/melee/mn/mnsoundtest.c
git checkout backup/melee-3-YYYYMMDD -- src/melee/mn/mnsoundtest.h  # if exists

# Commit the unique work
git add -A
git commit -m "mnsoundtest: WIP refactoring from melee-3"
```

## Phase 7: Verify & Push

```bash
# Verify build passes
cd /Users/mike/code/melee
python configure.py && ninja

# Push master to origin (may need --force)
git push origin master --force-with-lease

# Push PR branches
git push origin pr/mndiagram-module
git push origin pr/mnvibration
```

## Conflict Resolution Guidelines

When resolving conflicts, **always keep the better match**:

1. **Check match percentages**: Our improvements generally have higher percentages
2. **Keep better function names**: Our naming is often more descriptive
3. **Preserve inline helpers**: Functions like `CheckAllZeroPlayTime_u8` improve matches
4. **Use hex literals with comments**: `case 0x00: /* VSRecordStatType_Kills */`

## Files Requiring Special Attention

| File | Action |
|------|--------|
| `src/melee/mn/mndiagram.c` | Keep our improvements (InputProc, PopupInputProc) |
| `src/melee/mn/mndiagram2.c` | Keep our HandleInput improvements |
| `src/melee/mn/mndiagram.h` | Keep our function renames |
| `config/GALE01/symbols.txt` | Merge carefully - keep all symbol definitions |

## Rollback Plan

If anything goes wrong:
```bash
# Restore master from backup
git checkout master
git reset --hard backup/master-$(date +%Y%m%d)

# Restore worktrees
cd /Users/mike/code/melee-2
git reset --hard backup/melee-2-$(date +%Y%m%d)

cd /Users/mike/code/melee-3
git reset --hard backup/melee-3-$(date +%Y%m%d)
```

## Post-Sync Checklist

- [ ] Master builds successfully (`python configure.py && ninja`)
- [ ] Master is even with upstream/master (for non-tooling files)
- [ ] All tooling works (skills, melee-agent, VSCode extension)
- [ ] `pr/mndiagram-module` branch created with improved matches
- [ ] `pr/mnvibration` branch created with WIP work
- [ ] melee-2 worktree cleaned up (archived or deleted)
- [ ] melee-3 worktree reset with mnsoundtest WIP preserved
- [ ] Origin pushed and up-to-date
- [ ] Backup branches can be deleted after verification
