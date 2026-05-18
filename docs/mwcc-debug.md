# mwcc_debug — Compiler Diagnostic Dumps Workflow

A way to dump MWCC's internal IR + codegen for a Melee TU. Built around
[Savestate2A03/mwcc_debug](https://github.com/Savestate2A03/mwcc_debug) — a
drop-in `lmgr326b.dll` replacement that unlocks MWCC 1.2.5n's normally-disabled
verbose-debug code path.

> **Why this exists:** when stuck on a register-allocation cascade or other
> last-mile mismatch that `mismatch-db`, `opseq`, `ghidra`, and
> `discord-knowledge` can't explain, the dump lets you compare the compiler's
> internal state for a matched sibling function against the one that's stuck.

> **Companion:** the `mwcc-inspect` skill provides a more structured view
> (ENodes, ObjObjects, Statements) via [RootCubed/mwcc-inspector][mi]. Use that
> one when you want compiler-data-structure introspection; use `mwcc_debug`
> when you want the raw codegen-pass output (BEFORE/AFTER REGISTER COLORING,
> instruction scheduling, etc.).

[mi]: https://github.com/RootCubed/mwcc-inspector

## Architecture

```
macOS (agent)                       Windows (nzxt-local)
─────────────                       ────────────────────
melee-agent debug pcdump <c-file>
    │
    │   ssh nzxt-local
    │   "powershell -File run_pcdump.ps1 src/melee/.../X.c"
    ▼
                                    run_pcdump.ps1:
                                      • acquire $env:TEMP\mwcc_debug.lock
                                      • git pull --rebase
                                      • install patched lmgr326b.dll
                                      • mwcceppc.exe ... -c X.c -o obj.o
                                      • cat pcdump.txt → stdout
                                      • restore stock DLL + release lock
    │                               ▲
    │   pcdump.txt (raw bytes)      │
    ◀───────────────────────────────┘
    ▼
stdout (or --output <file>)
```

The CLI doesn't depend on a Windows-side service — it's just SSH. Diagnostics
go to stderr, raw `pcdump.txt` bytes go to stdout.

## Usage

```bash
# Dump a TU and print to stdout
melee-agent debug pcdump src/melee/lb/lbarq.c

# Save to a file
melee-agent debug pcdump src/melee/lb/lbarq.c --output build/mwcc_debug/lbarq.txt

# Skip the auto git pull on Windows (test stale code)
melee-agent debug pcdump src/melee/lb/lbarq.c --no-pull

# Longer timeout for large TUs
melee-agent debug pcdump src/melee/lb/lbarq.c --timeout 180
```

The first `--output` form is the typical workflow for an agent: dump the file
into a known location, then grep/diff it against an existing dump of a
working sibling function.

## Reading the dump

For each function in the TU, the dump contains roughly:

```
Starting function <name>
--------------------------------------------------------------------------------
...
BEFORE GLOBAL OPTIMIZATION
<fn>
B0: Succ={B1} Pred={} Labels={L0}
    mr      r32,r3              ; ← virtual registers (32+)
    mr      r33,r4
...
AFTER COPY PROPAGATION
<fn>
...
AFTER REGISTER COLORING
<fn>
B0: Succ={B1} Pred={} Labels={L0}
    mr      r3,r3               ; ← physical registers
    mr      r4,r4
...
AFTER INSTRUCTION SCHEDULING
...
```

The headline use case is **diff the BEFORE/AFTER REGISTER COLORING passes
between a matched function and an unmatched function in the same TU** —
the diff shows exactly how MWCC's allocator picked physical registers
differently for similar virtual-register shapes.

Other useful sections:

- IR optimizer events: `Found expression propagation at N from M`,
  loop unrolling decisions, dead-assignment eliminations
- Instruction annotations: `; fIsPtrOp`, `; fIsLive`, `; fIsVolatile`,
  `; fSideEffects`, `; fLink` (for branch instructions)

## When to use this vs. other tools

| Symptom | Try first |
|---|---|
| Diff already shows clear register swap on adjacent lines | `mismatch-db search` for the pattern |
| Looking for similar matched code structure | `opseq` |
| Need callers/callees, named strings | `ghidra` (cached SQLite, sub-ms) |
| Need historical context, compiler trick patterns | `discord-knowledge` |
| Need MWCC's parsed expression trees / variable IDs | `mwcc-inspect` skill |
| **None of the above explained the mismatch — want raw compiler-pass output** | **`melee-agent debug pcdump`** |

Don't reach for this first. It's heavier than the cached tools and the dumps
are large (tens-to-hundreds of KB per TU). Use it after the lighter tools
have failed to explain a stubborn mismatch.

## One-time Windows setup

The remote machine needs:
- Windows 10/11 with PowerShell 5.1+ and Git for Windows
- SSH server enabled and reachable via an SSH alias from macOS
- A copy of the melee repo at `C:\Users\mikes\code\melee` (or override via
  `MWCC_DEBUG_REPO` env var)
- The MWCC GC/1.2.5n compiler at the repo's `build/compilers/GC/1.2.5n/` path,
  OR at the inspector-package fallback path (the script tries both)
- `C:\Users\mikes\code\mwcc_debug\lmgr326b.dll` (the patched DLL from this
  project's `build/tools/mwcc_debug/lmgr326b.dll`)
- `C:\Users\mikes\code\mwcc_debug\run_pcdump.ps1` (from this project's
  `tools/mwcc_debug/win/run_pcdump.ps1`)

To install:

```bash
# On macOS
make -C tools/mwcc_debug all              # builds lmgr326b.dll via MinGW
scp build/tools/mwcc_debug/lmgr326b.dll nzxt-local:
scp tools/mwcc_debug/win/run_pcdump.ps1 nzxt-local:

# On Windows (via SSH)
ssh nzxt-local 'powershell -Command "
  New-Item -ItemType Directory -Force C:\Users\mikes\code\mwcc_debug | Out-Null;
  Move-Item -Force ~/lmgr326b.dll C:\Users\mikes\code\mwcc_debug\;
  Move-Item -Force ~/run_pcdump.ps1 C:\Users\mikes\code\mwcc_debug\
"'
```

If your SSH alias for the Windows machine isn't `nzxt-local`, set
`MWCC_DEBUG_HOST` in your env (e.g. via `.env`):

```
MWCC_DEBUG_HOST=my-windows-alias
```

## Recovery

If `run_pcdump.ps1` crashes mid-run and leaves the patched DLL installed on
Windows, future builds will be debug builds (slower + races `pcdump.txt`).
To recover:

```bash
ssh nzxt-local 'powershell -Command "
  $d = \"C:\Users\mikes\code\melee\build\compilers\GC\1.2.5n\";
  if (Test-Path \"$d\lmgr326b.dll.stock\") {
    Move-Item -Force \"$d\lmgr326b.dll.stock\" \"$d\lmgr326b.dll\";
    Write-Host \"restored\"
  } else { Write-Host \"no backup to restore\" }
"'
```

The lock at `%TEMP%\mwcc_debug.lock` auto-clears on next run if its PID is no
longer alive. To force-clear:

```bash
ssh nzxt-local 'powershell -Command "Remove-Item $env:TEMP\mwcc_debug.lock -Force"'
```

## Limitations

- **Windows-only execution.** Doesn't work on macOS — Rosetta 2's exception
  handling can't recover from a NULL-pointer execute that mwcceppc hits
  inside its translated-debug-output path. The DLL itself is correct (smoke
  test of a trivial 1-line TU works on macOS); it's specifically the
  larger-function debug code that crashes under Rosetta.
- **One TU at a time.** The DLL is swapped repo-wide on the Windows host;
  the script holds a lock so concurrent invocations queue rather than collide.
- **Output is large.** A typical Melee TU produces 50KB-MB of pcdump output.
  Consider `--output` to a file rather than streaming to stdout if you're
  inside a captured shell session.

## How it was built

See [docs/mwcc-debug-poc-design.md](mwcc-debug-poc-design.md) for the original
PoC design and [docs/mwcc-debug-poc-plan.md](mwcc-debug-poc-plan.md) for the
implementation plan that built the DLL, wibo patch, and macOS wrapper (the
macOS path is now obsolete — kept for historical context).
