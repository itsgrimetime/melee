# Workflow Tools

Scripts for managing the decomp workflow between fork and upstream.

## Quick Reference

| Script | Purpose |
|--------|---------|
| `status.sh` | Show current workflow status |
| `sync-upstream.sh` | Reset master to upstream + tooling |
| `create-pr.sh` | Create clean PR branch from changes |
| `update-pr.sh` | Apply changes from master to existing PR branch |
| `pr-worktree.sh` | Create worktree with tooling for PR iteration |

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

## Skills

Agents can use these skills for guided workflow:
- `/workflow` - General workflow management
- `/prepare-pr` - Step-by-step PR preparation
- `/sync-upstream` - Guided upstream sync
