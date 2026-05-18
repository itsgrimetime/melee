---
name: mwcc-debug
description: Dump MWCC's internal codegen passes (BEFORE/AFTER REGISTER COLORING, instruction scheduling, etc.) for a Melee TU by running Savestate2A03/mwcc_debug on a remote Windows host. Use when stuck on register-allocation cascades or other last-mile matching issues — complement to mwcc-inspect (which shows front-end IR / ENodes / ObjObjects).
---

# MWCC Debug (remote Windows)

Runs [`Savestate2A03/mwcc_debug`](https://github.com/Savestate2A03/mwcc_debug) against our 1.2.5n compiler on a remote Windows host (default: `nzxt-local`) and streams the resulting `pcdump.txt` back locally. The tool patches `lmgr326b.dll` to unlock MWCC's normally-disabled verbose-debug code path, which emits a per-pass dump of the compiler's PCode (back-end IR) for every function.

## When to use this

| Situation | Should I use mwcc-debug? |
|-----------|-----|
| First look at a function | No — start with `tools/checkdiff.py` and m2c |
| Asm diff doesn't match — figure out why | Try `/mismatch-db` and `/opseq` first |
| Known pattern from Discord | Try `/discord-knowledge` first |
| Need callers / xrefs | Use `/ghidra` |
| Want front-end parser view (ENodes, ObjObject addresses) | Use `/mwcc-inspect` |
| **Want back-end view (basic blocks, virtual registers, coloring decisions)** | **Yes** |
| Register-cascade stalled and you want to see what the allocator did | **Yes** |
| Want to compare a matched sibling fn's codegen passes against the unmatched one | **Yes** |
| Stack-frame mismatches, SDA relocations | No — these happen later in the pipeline |

This is the **back-end counterpart** to `mwcc-inspect`. The two answer different questions:

- `mwcc-inspect`: *"how did the compiler parse my expressions?"* (ENode trees, variable IDs)
- `mwcc-debug`: *"what did each codegen pass produce?"* (BB structure, virtual→physical reg mapping)

For a stuck register cascade, usually it's worth dumping both — front-end to see whether the parse differs from a matched sibling, back-end to see whether the allocator made different decisions.

## What you get

The dump is a textual trace of every codegen pass for every function in the TU. Roughly:

```
Starting function <name>
...
BEFORE GLOBAL OPTIMIZATION
<fn>
B0: Succ={B1} Pred={} Labels={L0}
    mr      r32,r3              ← virtual registers (32+) before coloring
    mr      r33,r4
...
AFTER COPY PROPAGATION
<fn>
...
AFTER CODE MOTION
...
AFTER REGISTER COLORING
<fn>
B0: Succ={B1} Pred={} Labels={L0}
    mr      r3,r3               ← physical registers after coloring
    mr      r4,r4
...
AFTER INSTRUCTION SCHEDULING
...
```

Each instruction line carries annotation flags: `; fIsPtrOp`, `; fIsLive`, `; fIsVolatile`, `; fSideEffects`, `; fLink` (branches that link), etc.

## Setup (one-time)

The skill assumes:
- SSH access via `ssh nzxt-local` (configurable via `MWCC_DEBUG_HOST`)
- The melee fork cloned at `C:\Users\mikes\code\melee` on the remote (override via `MWCC_DEBUG_REPO` env var on the remote)
- The patched DLL at `C:\Users\mikes\code\mwcc_debug\lmgr326b.dll` on the remote
- The wrapper script at `C:\Users\mikes\code\mwcc_debug\run_pcdump.ps1` on the remote
- The GC/1.2.5n compiler accessible to the remote (either at the repo's `build/compilers/GC/1.2.5n/` or at the inspector-package fallback path)

Build + install:

```bash
# On macOS (one-time, or whenever you change mwcc_debug.c)
make -C tools/mwcc_debug all              # builds lmgr326b.dll via MinGW

# Push to remote
scp build/tools/mwcc_debug/lmgr326b.dll nzxt-local:
scp tools/mwcc_debug/win/run_pcdump.ps1 nzxt-local:
ssh nzxt-local 'powershell -Command "
  New-Item -ItemType Directory -Force C:\Users\mikes\code\mwcc_debug | Out-Null;
  Move-Item -Force ~/lmgr326b.dll C:\Users\mikes\code\mwcc_debug\;
  Move-Item -Force ~/run_pcdump.ps1 C:\Users\mikes\code\mwcc_debug\
"'
```

## Usage

```bash
# Stream pcdump to stdout (small TUs)
melee-agent debug pcdump src/melee/lb/lbarq.c

# Save to a file (preferred for normal TUs — output is 50KB–MB)
melee-agent debug pcdump src/melee/lb/lbarq.c --output build/mwcc_debug/lbarq.txt

# Longer timeout for big TUs
melee-agent debug pcdump src/melee/mn/mnevent.c --timeout 180 --output build/mwcc_debug/mnevent.txt

# Test stale code (skip git pull on remote)
melee-agent debug pcdump src/melee/lb/lbarq.c --no-pull
```

The wrapper:
1. SSHes to the remote with the relative .c path
2. Remote: acquires a lock, `git pull --rebase` (so it sees current master), installs patched DLL, runs `mwcceppc.exe` with stock Melee flags
3. Remote: streams `pcdump.txt` bytes back over SSH stdout
4. Local: writes raw bytes to `--output` file (or stdout)
5. Remote: restores stock DLL via `try/finally` (so a crash doesn't leave the patched DLL installed)

**Uncommitted local changes are not seen by the remote.** Commit + push first (auto-push is on master, so a normal commit is enough).

### Useful env-var overrides

| Var | Default | What |
|-----|---------|------|
| `MWCC_DEBUG_HOST` | `nzxt-local` | SSH alias for the Windows machine |
| `MWCC_DEBUG_REMOTE_SCRIPT` | `C:\Users\mikes\code\mwcc_debug\run_pcdump.ps1` | Remote script path |
| `MWCC_DEBUG_REPO` (set on remote) | `C:\Users\mikes\code\melee` | Remote repo path |
| `MWCC_DEBUG_TIMEOUT_SECS` (passed to remote) | 60 | Per-compile timeout |

## Workflow: register-cascade investigation

Diff the BEFORE/AFTER REGISTER COLORING passes between a matched sibling function and the stuck one:

1. Identify the TU and a matched function in it. (Any same-file function that's at 100% works as a baseline.)

2. Dump:
   ```bash
   melee-agent debug pcdump src/melee/<module>/<file>.c --output /tmp/<file>.txt
   ```

3. In the dump, find the matched fn's `AFTER REGISTER COLORING` block. Note the virtual→physical register mapping pattern.

4. Find the unmatched fn's `AFTER REGISTER COLORING` block. Diff the mappings. Look for:
   - Same-shape virtual registers (e.g. `r32` first-defined here, used there) mapped to different physical registers
   - Different basic-block boundaries between matched and unmatched
   - Different instruction order within blocks (suggesting scheduling decisions diverged)

5. Use that signal to inform C-source changes — usually adding/removing intermediate variables or reordering declarations to nudge the allocator.

For front-end investigation (why did the IR look different in the first place), pair with `/mwcc-inspect` on the same TU.

## Output sample

```
Starting function lbArq_80014ABC
--------------------------------------------------------------------------------
Removing unreachable code at: 1
*****************
Dumps for pass=0
*****************

BEFORE GLOBAL OPTIMIZATION
lbArq_80014ABC
:{0005}::::LOOPWEIGHT=0
B0: Succ={B1 } Pred={} Labels={L0 }

:{0004}::::LOOPWEIGHT=0
B1: Succ={B2 } Pred={B0 } Labels={L1 }

    mr      r32,r3

:{0004}::::LOOPWEIGHT=0
B2: Succ={B3 } Pred={B1 } Labels={L2 }

    lwz     r3,4(r32); fIsPtrOp

:{0006}::::LOOPWEIGHT=0
B3: Succ={} Pred={B2 } Labels={L3 }


AFTER COPY PROPAGATION
lbArq_80014ABC
...
AFTER REGISTER COLORING
lbArq_80014ABC
B0: Succ={B1 } Pred={} Labels={L0 }

B1: Succ={B3 } Pred={B0 } Labels={L1 }

    lwz     r3,4(r3); fIsPtrOp
...
```

## Limitations

- **Back-end only.** Doesn't show parsed expression trees, ObjObject addresses, or variable scoping decisions. For those, use `/mwcc-inspect`.
- **Runs on Windows.** macOS+wibo+Rosetta crashes mwcceppc when the verbose-debug path is active. The macOS PoC produced partial output before hanging; the Windows path is the only viable production workflow.
- **One TU at a time.** The DLL is swapped repo-wide on the remote; the script holds a lock so concurrent invocations queue.
- **Output is large.** A typical Melee TU produces 50KB–MB. Use `--output` rather than streaming.
- **Requires committed code.** The remote does `git pull --rebase`, so uncommitted local changes aren't seen. Commit first (auto-push on master).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ssh: Could not resolve hostname nzxt-local` | Check SSH config; set `MWCC_DEBUG_HOST` to your host alias |
| Remote: `patched DLL not found` | Re-run setup (scp + Move-Item) |
| Remote: `lock held by PID=N` | A previous run is in flight or crashed. Wait 30 min or `ssh nzxt-local 'powershell -Command "Remove-Item $env:TEMP\mwcc_debug.lock"'` |
| Remote: `git pull failed: You are not currently on a branch` | The Windows repo is in detached HEAD. `ssh nzxt-local 'cd /c/Users/mikes/code/melee && git fetch origin && git reset --hard origin/master'` |
| `compile exit=124` (timeout) | Either a very large TU or mwcceppc hung. Try `--timeout 300`. If still timing out, the TU may hit the same bug we hit on macOS — try a smaller subset. |
| Empty pcdump.txt | Compile failed too early to produce output. Check the stderr passthrough in the wrapper output. |

## Compare to mwcc-inspect

| Aspect | mwcc-debug | mwcc-inspect |
|--------|------------|--------------|
| **Stage** | Back-end (codegen passes, register allocation) | Front-end (parsing, AST, IR) |
| **Output** | Per-pass PCode dump for each function | Per-function ENode tree + ObjObject list |
| **Mechanism** | Patches `lmgr326b.dll` to unlock `debuglisting=1` | Attaches debugger via `dbgeng.dll` |
| **Best for** | "Why did the allocator pick THESE registers?" | "How did the compiler parse my expressions?" |
| **Output size** | 50KB–MB per TU (very verbose) | 5–50KB per function (structured) |
| **Stability** | Stable on Windows, broken on macOS (Rosetta) | Stable on Windows, not built for macOS |

You can use both on the same TU back-to-back to triangulate.

## See also

- Upstream tool: https://github.com/Savestate2A03/mwcc_debug
- Workflow doc: [docs/mwcc-debug.md](../../docs/mwcc-debug.md)
- macOS PoC investigation (abandoned): [docs/mwcc-debug-poc-design.md](../../docs/mwcc-debug-poc-design.md) and [docs/mwcc-debug-poc-plan.md](../../docs/mwcc-debug-poc-plan.md)
- Sister skill: `/mwcc-inspect` for front-end IR
