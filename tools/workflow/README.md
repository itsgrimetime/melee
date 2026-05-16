# Workflow Tools

Scripts for managing the decomp workflow between fork and upstream.

## Quick Reference

| Script | Purpose |
|--------|---------|
| `status.sh` | Show current workflow status |
| `../worktree-doctor.py` | Check and repair local agent/tooling prerequisites |
| `sync-upstream.sh` | Reset master to upstream + tooling |
| `create-pr.sh` | Create clean PR branch from changes |
| `update-pr.sh` | Apply changes from master to existing PR branch |
| `pr-worktree.sh` | Create worktree with tooling for `pr/*` or `wip/*` iteration |
| `agent-prompt.sh` | Generate a `/loop` prompt for a decomp agent, given a branch name |

## The Workflow

```
upstream/master ─────────────────────────► (canonical)
      │
      └── master (upstream + tooling overlay)
              │
              └── wip/* or HEAD (active decomp work)
                        │
                        └── pr/* (clean PR branches) ──► upstream
```

### Key Principles

1. **Master = upstream + tooling**: Always exactly one commit ahead of upstream
2. **Decomp on master**: Work directly on master, commit freely
3. **PR branches are fresh**: Created from upstream/master, not master
4. **Reset, don't rebase**: After PR merges, reset master (saves WIP as patch)

## Usage

### Check Status
```bash
./tools/workflow/status.sh
```

### Check Agent Tooling
```bash
python tools/worktree-doctor.py

# Apply safe local bootstrap fixes, such as restoring fork tooling files from
# master or symlinking an existing base DOL into the current worktree.
python tools/worktree-doctor.py --fix
```

### Sync with Upstream
```bash
# Preview what will happen
./tools/workflow/sync-upstream.sh --dry-run

# Perform sync
./tools/workflow/sync-upstream.sh
```

### Create PR
```bash
# From current HEAD
./tools/workflow/create-pr.sh mndiagram-improvements

# From specific branch
./tools/workflow/create-pr.sh mnvibration --from wip/mn-work
```

### Iterate on PR (Option A: Stay on Master)
```bash
# Make changes on master (has tooling)
# Edit src/melee/mn/module.c, etc.
git commit -m "fix based on feedback"

# Apply those changes to PR branch (without switching)
./tools/workflow/update-pr.sh pr/my-module

# Or amend the PR's last commit
./tools/workflow/update-pr.sh pr/my-module --amend

# Push the update
git push origin pr/my-module --force-with-lease
```

### Iterate on PR (Option B: PR Worktree)
```bash
# Create worktree with symlinked tooling
./tools/workflow/pr-worktree.sh create pr/my-module

# Work in the worktree (has tooling via symlinks)
cd ../melee-pr
# Make changes, commit directly to PR branch
git commit -m "fix based on feedback"
git push origin pr/my-module

# Return to main repo when done
cd ../melee

# Clean up worktree when PR is merged
./tools/workflow/pr-worktree.sh delete
```

### Long-Running WIP Worktree (per-agent isolation with overlay)
```bash
# Create an isolated worktree for an agent doing decomp work.
# Branches from master, so the fork tooling overlay is inherited
# directly via git checkout — no symlinks, no broken paths.
./tools/workflow/pr-worktree.sh create wip/mn-cleanup
# -> creates ../melee-wip-mn-cleanup on branch wip/mn-cleanup

cd ../melee-wip-mn-cleanup
# tools/checkdiff.py and melee-agent work directly here.
# Commit decomp work freely on the wip/ branch.

# Pull in later overlay updates from master:
git fetch && git merge master

# When done, hand off to a pr/* branch or clean up:
./tools/workflow/pr-worktree.sh delete wip/mn-cleanup
```

The `pr/*` and `wip/*` modes differ in where the overlay comes from:

| Mode | Branches from | Overlay source | Worktree path |
|------|---------------|----------------|---------------|
| `pr/*`  | `upstream/master` (via `create-pr.sh`) | Symlinks to main repo | `../melee-pr` |
| `wip/*` | `master`                                | Tracked on the branch | `../melee-wip-<topic>` |

For `wip/*`, master overlay changes don't reach existing worktrees until you
`git merge master` inside each one — the overlay is real files, not a symlink.

### Kick Off an Agent on a wip/ Branch
```bash
# See which wip/* and pr/* branches have worktrees ready for an agent
./tools/workflow/agent-prompt.sh --list

# Generate a /loop prompt for the agent
./tools/workflow/agent-prompt.sh wip/lb-mthp

# With a specific file scope (recommended when multiple agents share a module)
./tools/workflow/agent-prompt.sh wip/lb-mthp 'lbmthp.{c,h,static.h} + lb_01F8.c'
```

Output goes to stdout — pipe to `pbcopy` on macOS to grab it for the agent
session. The tool auto-detects the worktree path from the branch name and
derives the module focus from the branch prefix (`wip/<module>-<topic>`).

## Why This Workflow?

The main challenge is that:
1. PRs get squashed when merged upstream
2. Your local commits have different SHAs than the squashed result
3. Rebasing causes conflicts because git sees "different" changes

The solution:
- Never rebase master onto upstream
- Reset master and re-apply tooling
- Create PR branches fresh from upstream (no merge conflicts)
- WIP work is saved as patches and re-applied cleanly

## PR Cleanliness Boundaries

Fork tooling is for local iteration. Upstream PR branches should contain only
clean decompilation changes:

- OK: `src/`, `config/`, `include/`, and documentation directly needed by the
  upstreamable decomp change.
- Not OK: local agent tooling, `.claude/`, `tools/checkdiff.py`,
  `tools/workflow/`, local DOL symlinks, scratch databases, or generated build
  output.
- Use `./tools/workflow/create-pr.sh <name>` to package from `upstream/master`
  and keep the tooling overlay out of the PR branch.
- Use `./tools/workflow/update-pr.sh pr/<name>` to move source/config/include
  fixes from a tooling-enabled worktree onto an existing clean PR branch.
- Do not mention fork-only tooling in upstream PR descriptions. Keep PR text
  upstream-visible: summarize the matched/improved functions, source/data
  layout, type changes, and verification. Do not mention local attempts DB,
  attempt ledgers, `melee-agent`, `tools/checkdiff.py`, worktree doctor output,
  Discord archive searches, or agent process notes.

## Skills

Agents can use these skills for guided workflow:
- `/workflow` - General workflow management
- `/prepare-pr` - Step-by-step PR preparation
- `/sync-upstream` - Guided upstream sync
