# MWCC Retro Launch Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure a frontend retro dump leaves immediate evidence that it started, explains when its fixed GDB port is queued behind another dump, and cannot lose its trace to a concurrent invocation.

**Architecture:** Keep the existing process-group timeout and exclusive port serialization. Write an initial `launch.log` before entering the blocking launcher, have the launcher report lock contention to stderr, and move the singleton temporary trace's deletion/copy lifecycle inside the port lock so queued invocations cannot unlink an active trace.

**Tech Stack:** Python 3.11, Typer, pytest, POSIX `fcntl.flock`.

## Global Constraints

- Preserve exclusive serialization on retrowin32's fixed GDB port 9001; concurrent dumps must not collide.
- The port lock must cover stale temporary-trace removal, emulator/GDB execution, and copying `iro-trace.txt` into the requested output directory.
- Preserve the existing `DumpOutcome` exit-code contract and process-group cleanup behavior.
- Create `launch.log` before `_run_with_process_group_timeout` blocks so an interrupted or still-running dump never leaves an empty output directory.
- Lock diagnostics must be flushed to stderr and retained in the final or timeout `launch.log` transcript.
- Do not treat unrelated unreaped wibo processes as the cause of this retro-specific failure.

---

### Task 1: Make frontend launch and port-wait state observable

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/retro.py`
- Modify: `tools/mwcc_retro/mwcc_retro_debugger.py`
- Modify: `tools/melee-agent/tests/test_retro_cli.py`
- Modify: `docs/mwcc-retro.md`

**Interfaces:**
- Consumes: `_launch_dump(...) -> DumpOutcome` and `_port_lock()` as currently defined.
- Produces: immediate `launch.log` state before the subprocess runner starts; flushed `[retro] waiting for gdb port 9001 lock:` and `[retro] acquired gdb port 9001 lock:` diagnostics only when contention occurs.

- [ ] **Step 1: Write failing tests for immediate launch evidence and lock contention diagnostics**

Extend `test_launch_dump_uses_process_group_timeout_runner` so its fake runner reads `out_dir / "launch.log"` during the runner call and asserts that it already records an in-progress state, the requested function/source, the timeout, and the exact output directory. Add a focused `_port_lock` test that forces the nonblocking `flock` attempt to report contention, then asserts that the blocking acquisition is retained and stderr contains both the waiting and acquired messages for port 9001. Add a host-launcher lifecycle test with mocked emulator/GDB processes that records the order `lock enter -> stale trace removal -> emulator/GDB -> trace copy -> lock exit`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_retro_cli.py -k 'launch_dump_uses_process_group_timeout_runner or port_lock'`

Expected: FAIL because `_launch_dump` does not create `launch.log` until its runner returns, `_port_lock` blocks without diagnostics, and temporary-trace deletion/copy currently occur outside the lock.

- [ ] **Step 3: Write the initial launch transcript before blocking**

In `_launch_dump`, write `launch.log` immediately before `_run_with_process_group_timeout`. The in-progress content must include a stable status marker, source, function, output directory, timeout, and shell-quoted command. When the runner returns or times out, retain those launch facts and append/replace the state with the existing stdout/stderr transcript without changing `DumpOutcome` semantics.

- [ ] **Step 4: Report real port-lock contention without changing serialization**

In `_port_lock`, first attempt `fcntl.flock(..., LOCK_EX | LOCK_NB)`. On `BlockingIOError`, emit and flush a waiting diagnostic to stderr, perform the existing blocking `LOCK_EX` acquisition, then emit and flush an acquired diagnostic. Do not emit contention messages for immediate acquisitions. Preserve unconditional unlock/close cleanup.

- [ ] **Step 5: Protect the complete singleton trace lifecycle**

In `mwcc_retro_debugger.main`, enter `_port_lock` before deleting `_TRACE_TMP`, keep emulator/GDB execution inside it, and copy `_TRACE_TMP` to `a.out / "iro-trace.txt"` before leaving it. This preserves the required short inferior-visible path while preventing a queued launcher from unlinking or replacing the active launcher's trace.

- [ ] **Step 6: Document launch-log lifecycle**

Update the `launch.log` artifact description in `docs/mwcc-retro.md` to say it is created at launch and records fixed-port wait diagnostics as well as the emulator/GDB transcript.

- [ ] **Step 7: Run focused and broader regression tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_retro_cli.py
PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_mwcc_debug_diff_capture.py
git diff --check
```

Expected: both pytest commands pass and `git diff --check` exits 0. Existing coverage warnings from the baseline `test_retro_cli.py` run are acceptable but no new warning/error may be introduced.

- [ ] **Step 8: Commit**

```bash
git add tools/melee-agent/src/cli/debug/retro.py tools/mwcc_retro/mwcc_retro_debugger.py tools/melee-agent/tests/test_retro_cli.py docs/mwcc-retro.md
git commit -m "fix: expose retro frontend launch waits"
```
