# Local Remote-Run Retention Implementation Plan

**Goal:** Implement issue #1235 using the policy in the companion design.

## Task 1: Inventory and policy model

Create a dedicated local remote-run lifecycle module. Add failing tests for
owned path discovery, versioned and legacy metadata, exact candidate-audit
accounting, full-triage detection, winner and marker protection, partial fetch,
malformed input, nested symlinks, tracked files, and regular-file byte counts.
Implement deterministic run summaries and protected reasons.

## Task 2: Remote state and retention planning

Add failing tests for batched active/stopped/unknown probes, SSH and timeout
failure, age selection, global-cap selection, deterministic ordering, and an
unattainable cap caused by protected evidence. Implement read-only report and
prune-plan APIs. Unknown remote state must remain protected.

## Task 3: Apply lifecycle

Add failing tests for no-op dry runs, explicit apply, locking, apply-time rescan
and activity recheck, new retain/triage state, inode replacement, symlink swaps,
tracked-file changes, quarantine identity, deletion failure, and safe restore.
Implement quarantine-then-remove with per-run outcomes and exact reclaimed-byte
accounting.

## Task 4: Producer manifest and explicit retention

Add fetch tests for complete and partial atomic manifests without losing the
existing fetch warning or candidate audit. Add marker tests for exact job
resolution, atomic creation, idempotence, invalid paths, symlinks, and a required
reason. Implement `remote local-retain`.

## Task 5: CLI and documentation

Add `remote local-prune` text/JSON tests, help goldens, capability registration
if required, and integration documentation. The CLI defaults to dry-run and
requires `--apply` for deletion. Run a real dry-run over
`~/code/decomp-permuter` and inspect protected/eligible totals without applying.

## Verification

```bash
cd tools/melee-agent
pytest -q --no-cov \
  tests/test_mwcc_debug_local_remote_runs.py \
  tests/test_mwcc_debug_permuter_remote.py \
  tests/test_debug_cli_help_golden.py
ruff check src/mwcc_debug/local_remote_runs.py \
  src/mwcc_debug/permuter_remote.py \
  src/cli/debug/permute.py \
  tests/test_mwcc_debug_local_remote_runs.py
python -m compileall -q src/mwcc_debug src/cli/debug
git diff --check
python -m src.cli debug permute remote local-prune \
  --perm-root ~/code/decomp-permuter --json
```

After focused verification, request an independent destructive-path review,
incorporate all safety findings, fast-forward the branch, and resolve #1235.

