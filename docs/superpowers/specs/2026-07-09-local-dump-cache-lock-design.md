# Local Dump Cache Source-Lock Design

## Goal

Prevent cache-syncing `debug dump local` runs from compiling or publishing a pcdump while source-scoring temporarily stages candidate bytes into the real translation unit.

## Context

The compiled-source guard correctly compares SHA-256 bytes and ignores mtime-only changes. The #1208 refusal therefore reflects a real concurrent source-staging window, not a false mtime alarm: score-source holds the repo-wide checkdiff lock while replacing a real TU with candidate bytes, but a natural local dump does not hold that lock from its source snapshot through cache publication.

## Approaches Considered

1. Replace the SHA guard with mtime checks. This would accept races and can publish a pcdump for the wrong source bytes.
2. Lock only cache publication. This still permits the compiler to read staged bytes after the natural source snapshot.
3. Wrap every cache-syncing local dump in the existing repo-wide checkdiff lock, from entry through cache publication. Candidate source probes already use `--no-cache-sync`, so they bypass this wrapper while their parent holds the same lock. Make the shared lock re-entrant for a cache-syncing `--diff` run’s inner checkdiff section. This is selected.

## Design

Add a `functools.wraps` command decorator around `pcdump_local`. When `no_cache_sync` is false, it acquires `_acquire_checkdiff_repo_lock(DEFAULT_MELEE_ROOT, label="local pcdump cache sync")` before invoking the existing callback; the entire command, including source digest, compiler launch, and sidecar/cache publication, stays inside the lock. `--no-cache-sync` skips the wrapper, preserving source-probe behavior.

Extend `_acquire_checkdiff_repo_lock` with per-thread re-entrancy by repository root. A nested acquisition in the same command yields without opening a second flock handle; the outer acquisition remains responsible for release. Existing environment-driven child no-lock behavior remains unchanged.

## Testing

- Test the local-dump decorator with a fake command and fake lock: cache-syncing calls enter the lock around the callback; `--no-cache-sync` does not acquire it.
- Test nested same-thread checkdiff lock acquisition does not attempt a second filesystem lock and releases only after the outer context exits.
- Retain the existing mtime/snapshot guard test as the proof that the fix does not weaken freshness verification.
- Run cache and debug CLI suites plus `git diff --check`.

## Scope

Only `tools/melee-agent/src/cli/debug/__init__.py`, `tools/melee-agent/src/cli/debug/dump.py`, and focused tests change. Direct select-order cancellation is handled separately by #1209.
