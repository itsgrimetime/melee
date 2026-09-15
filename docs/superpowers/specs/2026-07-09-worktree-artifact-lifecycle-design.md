# Worktree Artifact Lifecycle Design

## Problem

Issue #1204 found 96 ignored worktree build and cache directories consuming 46.58 GiB. Existing tooling repairs one worktree and lists stale worktrees, but cannot safely account for or reclaim ignored artifacts across registered worktrees. New worktrees also repeatedly download immutable compiler and tool payloads.

The cleanup and reuse problems share a lifecycle boundary but are independent components. This design keeps their safety policies separate while exposing both from worktree-doctor.

## Goals

- Provide dry-run reporting and explicit cleanup for ignored build and cache artifacts in registered Git worktrees.
- Never delete a directory containing tracked files, non-ignored files, symlinks, or an active build/debug process.
- Apply deterministic age and size thresholds; deletion requires '--apply'.
- Allow explicitly supplied discovery roots for unregistered Codex/Claude worktrees without scanning arbitrary directories by default.
- Seed and hydrate a validated shared immutable compiler/tool cache with file-level symlinks.
- Integrate asset hydration with new PR/WIP worktree creation.

## Non-Goals

- Do not remove Git worktrees, source directories, existing artifacts, or any path without '--apply'.
- Do not share mutable object output, Ninja state, report JSON, diagnostics, virtual environments, or source.
- Do not follow symlinks, use hard links, or overwrite real consumer files.
- Do not replace existing bootstrap or base-DOL repair behavior.

## Alternatives Considered

1. Recursively scan known Codex and Claude directories and delete every old build. This cannot safely distinguish unrelated or active checkouts, so it is rejected.
2. Add Git-clean automation to every worktree. It lacks a report, active-job protection, and explicit eligibility policy, so it is rejected.
3. Enumerate registered Git worktrees by default, require explicit extra roots, validate each artifact root against Git/process/filesystem state, and clean only with '--apply'. This is selected.
4. Symlink entire build/tools or build/compilers directories into a cache. A repair can unlink a child through a symlinked parent and mutate the cache, so it is rejected.
5. Cache immutable files and hydrate consumers with file-level symlinks below real directories. This is selected.

## Interface

Worktree-doctor gains two command families:

~~~
python tools/worktree-doctor.py artifacts report
python tools/worktree-doctor.py artifacts cleanup --min-age-days 7 --min-bytes 1073741824
python tools/worktree-doctor.py artifacts cleanup --min-age-days 7 --min-bytes 1073741824 --apply
python tools/worktree-doctor.py artifacts report --scan-root ~/.codex/worktrees

python tools/worktree-doctor.py assets seed --source <worktree>
python tools/worktree-doctor.py assets hydrate --asset-source <worktree>
~~~

The default artifact scope is 'git worktree list --porcelain' for the current repository. '--scan-root' is repeatable and discovers only paths independently recognized as Git worktrees; it never follows symlinks. The main checkout is reported but never eligible.

Only direct worktree children 'build/' and '.cache/' are candidates. A candidate is eligible when it is real and non-symlinked; ignored by that worktree's Git configuration; contains no tracked or non-ignored regular file; has no symlink descendant; meets '--min-age-days' and '--min-bytes'; and has no active local process referring to the worktree or candidate path.

'report' emits candidate size, newest modification time, eligibility, and precise skip reasons. 'cleanup' is dry-run by default. '--apply' revalidates the full policy immediately before 'shutil.rmtree()' and reports planned, removed, reclaimed, and skipped roots.

Shared assets default to:

~~~
~/.cache/melee-agent/worktree-assets/v1/<platform>-<machine>
~~~

Only these immutable file trees are eligible:

- 'build/compilers/'
- 'build/tools/'
- 'tools/table-typer/table-typer'

'assets seed' copies regular source files into an atomic staging directory, writes a manifest containing schema version, platform identity, relative paths, byte sizes, and SHA-256 digests, validates every digest, makes cache files read-only, and atomically publishes. It rejects symlink sources and will not overwrite a valid mismatched cache.

'assets hydrate' validates the cache manifest/digests then creates file-level relative symlinks in a target worktree. Parent directories remain real, so a consumer unlink removes only its symlink. Existing real files or mismatched symlinks remain untouched and are reported. If the cache is absent and '--asset-source' is valid, hydrate seeds first; without a source it returns a non-fatal skipped state.

'tools/workflow/pr-worktree.sh create' invokes 'worktree-doctor.py assets hydrate --asset-source "$REPO_ROOT"' after base-DOL setup. It reports seed/hydrate/skipped status but does not fail worktree creation when no cacheable files exist.

## Safety and Failure Handling

Discovery resolves and deduplicates real worktree roots. Git checks run with each target worktree as cwd and fail closed. Filesystem walks use lstat and scandir without following links. Active-process detection is conservative: a process referring to the normalized worktree or candidate path skips cleanup; a process-table error also fails closed.

Hydration never writes through a symlink. It compares any existing consumer symlink target with the expected cache file, preserving unexpected paths. The cache is never removed by artifacts cleanup because it is outside a candidate worktree root.

## Test Strategy

- Test registered-worktree parsing, explicit-root discovery, deduplication, and main-checkout exclusion.
- Use temporary Git worktrees to test ignored-only candidates, tracked/non-ignored files, direct/nested symlinks, age/size thresholds, dry-run, revalidation, and active-process skips.
- Test cache manifest creation, digest validation, invalid cache rejection, file-level hydration, existing-file preservation, and consumer unlink isolation.
- Test PR/WIP worktree creation invokes asset hydration without changing existing overlay/DOL behavior.
- Run existing worktree-doctor and PR-worktree suites plus focused artifact/asset suites.

## Acceptance Criteria

- Artifact reporting identifies eligible ignored build/cache roots without mutation.
- Cleanup only removes revalidated eligible roots after '--apply', never active, tracked, non-ignored, symlinked, or default-unregistered paths.
- Seed/hydrate reuse validated immutable compiler/tool files through file-level symlinks.
- New PR/WIP worktrees hydrate available assets but remain usable when no assets exist.
- #1204 is satisfied without manual Git-clean sweeps or unsafe raw deletion.
