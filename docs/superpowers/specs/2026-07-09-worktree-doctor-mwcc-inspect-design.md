# Worktree Doctor MWCC Inspector Refresh Design

## Goal

Ensure `worktree-doctor.py --fix` recognizes `tools/workflow/mwcc-inspect.sh` as fork tooling and refreshes it from `master` when a clean worktree has an older tracked copy.

## Context

The shared `melee-agent` installation deliberately uses the main tooling checkout, but workflow shell scripts are invoked from the active worktree. The #1212 remote-ref refresh therefore remained absent in an existing matcher worktree even though the installed CLI was current. `worktree-doctor` already compares selected fork-tooling files to `master` and refreshes clean stale copies, but its list omits `mwcc-inspect.sh`.

## Approaches Considered

1. Make every worktree script dynamically source `master`. This breaks branch-local workflow development and hides the actual version being executed.
2. Add `mwcc-inspect.sh` to the existing safe tooling currentness list. `--fix` refreshes a clean stale copy, while a locally modified script remains protected and reported. This is selected.
3. Auto-refresh all files in `tools/workflow`. This can overwrite branch-specific experimental workflow edits and expands scope beyond the reported wrapper.

## Design

Add `tools/workflow/mwcc-inspect.sh` to `TOOLING_FILES`. The existing doctor logic will compare it to `master`, refresh it only with `--fix` when it is clean, and warn without overwriting when it has local changes. No currentness semantics change for other workflow scripts.

## Testing

- Assert the wrapper is in the default tooling list.
- Construct a temporary master/matcher repository where the matcher tracks an old wrapper and master contains the current one; verify `Doctor(fix=True).check_tooling_overlay()` restores the wrapper and emits the existing refreshed-tooling result.
- Run `pytest tests/test_worktree_doctor.py -q --no-cov` and `git diff --check`.

## Scope

Only `tools/worktree_doctor/__init__.py` and `tools/melee-agent/tests/test_worktree_doctor.py` change. The doctor’s existing dirty-file protection remains authoritative.
