# Diagnostic Artifact Retention Design

## Problem

Melee-agent diagnostic and permuter workflows currently mix durable evidence
with disposable compiler products. Some paths place retained candidate source,
score JSON, and pcdumps beside source files or in arbitrary `build/diagnostics`
directories. Other paths leave staging copies, probe directories, compiler
objects, and pcdump caches in a worktree's `build/` tree. The result is both
unbounded disk use and unsafe manual cleanup: deleting `build/` can erase
evidence that later tools and agents need to inspect.

Issues #1204, #1205, and #1206 share this root cause. #1205 is the first
implementation slice: it establishes an explicit lifecycle for diagnostic and
permuter run artifacts. The worktree-wide audit and shared immutable toolchain
assets requested by #1204 remain a separate follow-up because they operate on
multiple worktrees rather than one command run.

## Goals

- Preserve source-actionable evidence by default: candidate source, score and
  status payloads, manifests, command provenance, and pcdumps used to support
  a candidate.
- Place retained evidence in an ignored, predictable per-run directory rather
  than beside tracked source or arbitrary locations under `build/`.
- Delete only disposable compiler products, staging copies, and temporary probe
  output at the end of a successful, failed, or cancelled run.
- Provide a dry-run report and explicit cleanup command that applies retention
  rules to completed runs without touching active runs or user-owned files.
- Bound retained evidence by age and total size, pruning whole completed runs
  atomically so a manifest never points at a partially deleted evidence set.
- Keep the existing translation-unit pcdump cache separate from run evidence.
  It remains rebuildable and conservatively pruneable because freshness is
  source-hash based and regenerating one entry is supported by existing tools.

## Non-Goals

- Do not delete candidate source, score JSON, pcdumps, or manifests immediately
  after a run.
- Do not change a command's matching or scoring algorithm.
- Do not make the pcdump cache globally shared in this slice; source and
  compiler identity requirements need an independent cache-key design.
- Do not scan or remove arbitrary `build/` directories across worktrees in this
  slice; that is the #1204 worktree-doctor feature.
- Do not automatically clean incomplete or active run directories.

## Alternatives Considered

1. Delete all artifacts by default and retain only a JSON summary. This gives
   the strongest disk bound but makes source/pcdump-backed results impossible to
   inspect or pass to later tools. It is rejected.
2. Keep every file emitted by every command indefinitely. This is convenient in
   the short term but recreates the 23 GiB build-tree failure in #1205. It is
   rejected.
3. Retain an evidence bundle per completed run and prune bundles as a unit by
   age and size, while disposing compiler products at run finalization. This
   keeps the source-level proof agents need and gives operators a predictable,
   safe bound. This is the selected approach.

## Interface

Add a shared artifact-lifecycle module and expose it through the existing
`melee-agent debug` command family:

- Commands that create source-actionable candidates create an ignored run
  directory under `build/diagnostics/runs/<run-id>/` by default. The root is
  configurable for callers that need an external volume.
- Each completed run writes `manifest.json`, containing the command,
  repository and source identity, completion state, timestamps, all retained
  evidence paths, and the number of disposable bytes removed.
- Retained evidence is stored beneath `evidence/`; disposable output is stored
  beneath `transient/`. A finalizer removes only `transient/` and only after the
  run has reached a terminal state.
- `melee-agent debug artifacts report` lists completed runs, their age, size,
  manifest state, and retention eligibility. It is read-only by default and
  supports JSON for automation.
- `melee-agent debug artifacts prune` first reports its deletion plan, and
  removes only complete, manifest-owned run directories that exceed the
  configured age or total-size budget. Active/incomplete runs, malformed
  directories, and paths outside the configured root are skipped with a reason.
- Defaults retain completed evidence for 30 days and cap completed-run storage
  at 10 GiB, pruning oldest eligible bundles first. `--max-age-days`,
  `--max-total-bytes`, `--dry-run`, and `--artifact-root` make this explicit.

`debug target score-source` is the first producer migrated to this interface
because it already supports retained pcdumps and is used by the permuter
external scorer. Its retained source and pcdump are copied or written into the
same evidence bundle as its score payload. The command's existing
`--retain-pcdump` behavior remains compatible; when a lifecycle run is active,
retention goes to that bundle rather than next to a tracked source file.

The existing `build/mwcc_debug_cache` remains a separate, source-hash-aware
baseline cache. The artifact report surfaces its size but does not delete it in
this first slice; a later cache-specific policy can use its freshness metadata
without conflating it with candidate evidence.

## Safety and Failure Handling

The lifecycle module resolves and validates every owned path before creating or
removing it. A manifest records a run as `active` before a producer writes
files, and changes it to `completed`, `failed`, or `cancelled` only in the
producer's finalization path. Pruning requires a terminal manifest state and a
directory that is directly below the configured root; it never follows a
manifest path to delete arbitrary filesystem locations.

If a producer fails, it preserves evidence already written, finalizes the
manifest as `failed`, and removes only its own `transient/` directory. If it is
interrupted before finalization, its `active` manifest prevents pruning. The
report command identifies these runs for an operator rather than guessing that
they are safe to remove.

## Data Flow

```text
producer command
  -> create active run manifest
  -> write candidate source / score / pcdump to evidence/
  -> write compiler and probe byproducts to transient/
  -> finalize manifest (completed, failed, or cancelled)
  -> remove transient/

artifact report / prune
  -> validate run root and manifests
  -> report evidence size and eligible completed bundles
  -> optionally remove whole eligible bundle directories
```

## Test Strategy

- Unit-test run creation and finalization: evidence remains, transient output
  is removed, and the manifest reports terminal state and byte counts.
- Unit-test failure finalization: already-written source, score, and pcdump
  evidence remains while transient output is removed.
- Unit-test report and dry-run pruning: it reports age/size eligibility without
  modifying files.
- Unit-test pruning: it removes only oldest, terminal, manifest-owned run
  directories necessary to satisfy a size budget and never splits a bundle.
- Safety tests: active, malformed, symlinked, and out-of-root entries are
  skipped; a manifest cannot direct deletion outside the artifact root.
- CLI tests for `debug artifacts report` and `debug artifacts prune` cover text
  and JSON output.
- Score-source integration tests prove retained source/score/pcdump evidence is
  written to one bundle and legacy explicit pcdump output remains compatible.

## Acceptance Criteria

- A completed score-source/permuter scorer run leaves a self-contained,
  ignored evidence bundle containing its source, score metadata, and pcdump
  when retained, with no compiler staging or probe output beside tracked source.
- Failed and cancelled runs preserve the same evidence already produced and do
  not retain disposable compiler products.
- Operators can preview and apply retention cleanup without risking active jobs,
  tracked files, non-ignored paths, or individual files inside an evidence
  bundle.
- The 30-day/10-GiB default policy bounds completed evidence while keeping
  recent cross-tool pcdump-backed results available.
