# Process-Group Cancellation Cleanup Design

## Goal

Ensure an interrupt or cancellation of a source-mutating debug command cannot bypass cleanup of the compiler subprocess session it owns.

## Context

`_run_with_process_group_timeout()` starts compiler/dump commands in a separate process session and kills that tree when its own timeout expires. If an outer command receives `SIGINT`, `SIGTERM`, or another exception while waiting in `thread.join()`, the exception currently escapes without killing the separate session. The caller’s source-restore handler can restore the live translation unit while the orphaned child remains active, creating the background process and source-race reported by #1209.

## Approaches Considered

1. Remove `start_new_session`. This weakens normal timeout tree cleanup and relies on ambient shell signal groups.
2. Add select-order-specific process tracking. This duplicates a shared primitive used by multiple debug workflows.
3. Make the existing process-group runner clean up on every exceptional exit after `Popen`, reusing the existing tree-kill/pipe-close/wait sequence. This is selected.

## Design

Extract or reuse the existing timeout cleanup sequence so `_run_with_process_group_timeout()` invokes it both when its deadline expires and when `thread.join()` or post-join handling raises `BaseException`. After cleanup it re-raises the original interruption unchanged. Successful execution and ordinary compiler failures remain unchanged.

The cleanup acts on the child’s dedicated process group, so it terminates descendant processes that do not share the parent CLI’s signal group. Source restoration remains owned by the command-level handler/finally; this change prevents any child from surviving after that outer control flow begins.

## Testing

- Add a fake process/thread regression where `thread.join()` raises `KeyboardInterrupt`; assert the process group is killed, pipes close, the process is reaped, and the original interruption is re-raised.
- Keep the existing timeout and descendant-process-group tests unchanged.
- Run the process-group-focused diff-capture tests, full diff-capture tests, and `git diff --check`.

## Scope

Only `tools/melee-agent/src/mwcc_debug/diff_capture.py` and `tools/melee-agent/tests/test_mwcc_debug_diff_capture.py` change. Bounded-validation delegation is already addressed separately in #1210.
