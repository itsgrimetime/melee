# Sync Upstream Configure Overlay Design

## Problem

`tools/workflow/sync-upstream.sh` resets `master` to `upstream/master`, then
restores every path in `TOOLING_PATHS` from the pre-sync backup branch.
`configure.py` is in that list, but it is not fork-only tooling. It contains a
small set of fork customizations mixed into an upstream-owned source list and
match-status configuration. Restoring the whole file can silently erase upstream
restructuring and leave the source tree out of sync with the build config.

The same sync leaves generated `build/*/config.json` files in place. When dtk's
version has not changed, `tools/project.py` can reuse stale generated unit
metadata that still references removed or renamed translation units.

## Goals

- Keep upstream-owned `configure.py` content from the new `upstream/master`
  after a sync.
- Reapply only the fork-owned `configure.py` deltas:
  `--no-require-protos`, default-on `require_protos`, `wibo_tag = "1.0.0"`,
  and the `_purge_wrong_arch_wibo` helper plus configure-mode call.
- Fail loudly if upstream changes the relevant anchors enough that the fork
  deltas cannot be applied safely.
- Remove stale generated `build/*/config.json` after sync so the next configure
  regenerates unit metadata from current config files.
- Add regression coverage that exercises the shell script in a temporary git
  repository and checks the committed result.

## Non-Goals

- Do not redesign every hybrid path under `tools/`.
- Do not change `tools/project.py` config cache invalidation in this fix. The
  workflow papercut is specifically post-sync stale state.
- Do not run a real upstream sync against the working repository in tests.

## Approach

`sync-upstream.sh` should remove `configure.py` from the normal wholesale
tooling overlay. After reset and normal tooling restore, it should run a small
embedded Python transform over the upstream `configure.py` in the worktree. The
transform applies the fork deltas by exact textual anchors and exits non-zero on
missing or unexpected anchors.

The transform should specifically require the upstream line
`config.wibo_tag = "0.7.0"` before changing it. If upstream later advances the
tag, sync should fail for a deliberate review instead of pinning over it.

After restoring tooling and applying the configure overlay, the script should
delete `build/*/config.json` files and include that deletion in the sync commit
if those generated files were tracked. Untracked ignored generated files will
also be removed from the worktree.

## Tests

Add a pytest file under `tools/melee-agent/tests/` that:

- creates a temporary git repo and a local bare upstream remote;
- commits a fork `master` containing the current sync script, an old
  whole-file-overlay `configure.py`;
- creates stale `build/GALE01/config.json` as an untracked generated file after
  the fork tooling commit, so the hard reset cannot remove it before the
  cleanup path runs;
- advances `upstream/master` with an upstream-owned `configure.py` content
  change that must survive sync;
- runs `bash tools/workflow/sync-upstream.sh`;
- asserts `git show HEAD:configure.py` still contains the upstream-owned
  content, contains all fork deltas, and does not contain old fork-only
  upstream-owned content;
- asserts `build/GALE01/config.json` is removed;
- asserts `git status --porcelain` is empty.

The test should be lightweight and should not run `configure.py` or `ninja`.
