---
name: mwcc-debug
description: Dump MWCC's internal codegen passes (BEFORE/AFTER REGISTER COLORING, instruction scheduling, etc.) for a Melee TU. Runs locally on macOS (via wibo+Zig-built DLL) by default, or on a remote Windows host as a fallback. Use when stuck on register-allocation cascades or other last-mile matching issues — complement to mwcc-inspect (which shows front-end IR / ENodes / ObjObjects).
---

# MWCC Debug (local or remote)

Runs a patched mwcc_debug DLL against our 1.2.5n compiler and produces `pcdump.txt`. The patch unlocks MWCC's normally-disabled `debuglisting` code path, which emits a per-pass dump of the compiler's PCode (back-end IR) for every function. We add our own hooks on top (simplifygraph, IG construction, colorgraph decisions) for stuck-function diagnostics.

**Two execution modes:**

| Mode | Command | Speed | Setup |
|---|---|---|---|
| **Local (recommended on macOS)** | `melee-agent debug pcdump-local` | ~1s | One-time: `melee-agent debug setup-local`; needs `melee-harness` adjacent for wibo |
| **Remote SSH** | `melee-agent debug pcdump` | ~30s | One-time: nzxt-local host with DLL deployed |

Local mode is 30-40x faster and is the default for new agents. Remote remains the fallback for cases where wibo doesn't work (rare).

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

### Step 1: dump a TU

```bash
# Save to a file (preferred — pcdump is 50KB–MB)
melee-agent debug pcdump src/melee/lb/lbarq.c --output build/mwcc_debug/lbarq.txt

# Stream pcdump to stdout (small TUs)
melee-agent debug pcdump src/melee/lb/lbarq.c

# Longer timeout for big TUs
melee-agent debug pcdump src/melee/mn/mnevent.c --timeout 180 --output build/mwcc_debug/mnevent.txt

# Test stale code (skip git pull on remote)
melee-agent debug pcdump src/melee/lb/lbarq.c --no-pull
```

### Step 2: analyze a specific function

The raw dump is verbose. The `analyze` command extracts per-virtual-register info
(live ranges, use counts, interferences, candidate physicals) — much faster to
reason about than scrolling through the pass dumps.

```bash
# List functions in the dump
melee-agent debug analyze build/mwcc_debug/lbarq.txt

# Detailed per-virtual-register table + coloring decisions for one function
melee-agent debug analyze build/mwcc_debug/lbarq.txt --function lbArq_80014AC4
```

Output shows live ranges, interferences, and the candidate set for each
virtual (the physicals NOT used by an interferer — i.e., the choices the
allocator could have made).

### Step 2.5: diff two dumps to see what a source change did

When iterating on a source change for a stuck function, dump before and
after the change, then diff:

```bash
melee-agent debug diff before.txt after.txt --function mnVibration_80248644
```

Surfaces per-virtual changes (assigned reg, interferer set additions/
removals, degree, flags). "No coloring changes detected" is itself a
useful signal — your change had no IR-level effect (often because
MWCC constant-inlined it; see [docs/mwcc-allocator-mechanism-deep-dive.md](../../docs/mwcc-allocator-mechanism-deep-dive.md)).

### Step 3: simulate what the allocator would pick (and why)

The `simulate` command replays MWCC's actual algorithm (extracted from the
7.0 source at git.wuffs.org/MWCC). For each virtual it predicts what physical
the allocator would pick and shows the reasoning. Mismatches against actual
highlight cases our model doesn't capture (caller-save kill, r0 special-case,
iteration-order edge cases).

```bash
melee-agent debug simulate build/mwcc_debug/mnvibration.txt \
    --function mnVibration_80248644 --all
```

The verified MWCC algorithm (Tier 2 — direct binary-hook confirmation):
1. workingMask = caller-save regs (r3..r12) minus interferers' regs
2. If non-empty: pick LOWEST set bit
3. Else: obtain_nonvolatile_register() — dispenses **r31, r30, r29, r28, r27,
   then r26, r25, ...** (TOP-DOWN from r31). Once dispensed, the reg is
   added to the volatile pool and can be reused for non-interfering virtuals.

This is why r32 (highest-degree, lives whole function) often ends up at r26
in big functions: by the time r32 is colored, r27..r31 have all been
dispensed to earlier virtuals AND r32 interferes with their holders, so the
next dispense is needed.

For full per-decision data including iteration order and the actual mapping
of iter index → virtual → assigned physical, look at the `COLORGRAPH
DECISIONS` sections in the raw pcdump. These come from the colorgraph hook
in mwcc_debug.c (Tier 2 — fires once per register class per function).

The pcdump ALSO includes `IG CONSTRUCTED (class=N, n_nodes=K)` event lines
that pair with each COLORGRAPH DECISIONS section. They mark when MWCC
finished building the interference graph for that class — useful for
ordering visibility (which function/class is being processed at any
given point in the dump). Tier 3 hook.

`SIMPLIFY GRAPH (class=N, n_colors=K, n_class_regs=M)` event lines pair
with each COLORGRAPH DECISIONS section. They show simplifygraph's
output: the simplification stack order (head = colored first), each
node's pre-simplification interferer count (`arraySize`), and the
SPILLED flag if simplifygraph marked the node as a potential spill.
Tier 2.5 hook — useful when you need to know whether a virtual was
structurally hard to color (Chaitin's "can't be removed cleanly")
before colorgraph even got to it. SPILLED markers are the headline
signal: a virtual flagged here probably won't get a clean physical
unless you reduce its degree by C-source restructuring.

And `CONSTPROP RAN (changed_flag: before=X after=Y)` event lines: one per
function, marking when constant propagation fired. The `changed_flag`
indicates whether CP modified anything. Tier 3.5 hook — useful for
identifying functions where CP played a role (and conversely, confirming
when an apparent variable-split happened at PCode generation rather than
in CP).

For deep diagnosis of why scroll_offset-style variable splits happen,
see [`docs/mwcc-allocator-mechanism-deep-dive.md`](../../docs/mwcc-allocator-mechanism-deep-dive.md).

### Step 4: force a specific register mapping (Tier 5, hypothesis testing)

When you suspect the matching ceiling is register-allocation only — and
want to confirm before spending hours coaxing the C source — use
`--force-phys` to override MWCC's allocator decisions and see whether
the resulting `.text` matches the target.

```bash
# Force virtual #36 to physical r31
melee-agent debug pcdump src/melee/mn/mnvibration.c \
    --output /tmp/forced.txt \
    --force-phys "36:31"

# Multiple overrides at once
melee-agent debug pcdump src/melee/mn/mnvibration.c \
    --output /tmp/forced.txt \
    --force-phys "36:31,50:27"
```

The format is `virtIdx:physReg[,virtIdx:physReg]*`. The DLL patches
`IGNode->assignedReg` after colorgraph runs, so the override propagates
through `rewritepcode` to the emitted instructions. Each override fires
a `[FORCE_PHYS] virtual N: rX -> rY` event in the dump.

**Interpretation:**
- Forced ASM matches target → goal is reachable via C-source. Spend
  time finding the C pattern that nudges the allocator there.
- Forced ASM still doesn't match → the constraint isn't the allocator.
  Look at instruction selection (earlier passes) or scheduling (later).

**Caveats:**
- Forcing two interfering virtuals to the same physical produces
  incorrect code (data corruption). DLL-patched ASM is a
  hypothesis-test artifact, NOT a real compiler output — never commit
  source based on a forced result without confirming the real
  compiler reproduces it from natural C.
- Find virtual indices by inspecting the `COLORGRAPH DECISIONS` table
  in an unforced dump first. The `ig_idx` column (positive values) is
  the index you pass.

### Step 5: get actionable guidance (Tier 4, hypothesis → C-source)

Once you've used Step 4 to confirm a target allocation is reachable,
use `guide` to find out WHAT specifically blocks the natural source
from getting there. Often this points straight at a single interfering
virtual whose lifetime needs shrinking.

```bash
# Capture target from a forced run
melee-agent debug derive-target /tmp/forced.txt -f mnVibration_80248644 \
    --format json > /tmp/target.json

# Score baseline against target
melee-agent debug score /tmp/baseline.txt -f mnVibration_80248644 \
    --target /tmp/target.json --breakdown

# Get actionable suggestions
melee-agent debug guide /tmp/baseline.txt -f mnVibration_80248644 \
    --target /tmp/target.json
```

Example output:
```
Suggestions (highest severity first):
  ! [r36 / interference] r36 wants r31 but r31 is taken by interfering
    virtual(s) r51. Try: shrink the live range of r51 so they don't
    overlap r36, or move r36's definition earlier so it's colored
    before r51.
```

`guide` covers three blocker categories:
- **interference**: target physical is taken by a known interferer →
  shrink interferer's lifetime
- **spill**: virtual is on the spill-candidate list → reduce its
  interferer count
- **rank**: no direct blocker, but iteration order pushed this virtual
  to a lower slot → adjust other virtuals' lifetimes that consumed the
  desired physical earlier

`guide` also cites named **mutation patterns** from the catalog
(`debug pattern-catalog`) — `alias-split`, `widen-u8-to-u32`,
`drop-variadic-cast`, `decl-order`, etc. These are the recurring
shapes the permuter rediscovers across stuck functions.

The `score` command emits a single number for permuter integration
(lower = better). Designed to be called from a custom permuter scorer
wrapper that compiles candidates via SSH.

### Step 6: matching workflow tools (Tier 7)

After Tier 5/6 confirm the target is reachable, the matching workflow
becomes "find the C-source change." Tier 7 commands automate the
specific friction points the matching agent identified in their
permuter sessions:

```bash
# Apply a permuter winner to the real source + verify match% improves
melee-agent debug verify-perm output-1234/source.c -f my_fn
melee-agent debug verify-perm output-1234/source.c -f my_fn --keep

# Brute-force the decl-order search space (would find decl-reorder
# wins in ~10 iterations, vs permuter's ~2000)
melee-agent debug enumerate-decl-orders my_fn
melee-agent debug enumerate-decl-orders my_fn --strategy all
melee-agent debug enumerate-decl-orders my_fn --keep-best

# Browse known mutation patterns
melee-agent debug pattern-catalog
melee-agent debug pattern-catalog decl-order

# Static lint for suspicious casts + compare-opcode signedness mismatches
melee-agent debug suggest-casts my_fn
melee-agent debug suggest-casts my_fn --severity all --asm
melee-agent debug suggest-casts my_fn --signedness  # detect cmplwi/cmpwi disagreements

# Batch-triage permuter outputs against the real tree
melee-agent debug triage-perm permute_output_dir -f my_fn
melee-agent debug triage-perm permute_output_dir -f my_fn --apply-best

# Generate a pattern-tuned permuter settings.toml so permuter biases
# toward the mutation family that addresses this function's pattern.
# Pairs with triage-perm: tune-then-triage is the full loop.
melee-agent debug gen-permuter-config -f my_fn --target target.json
melee-agent debug gen-permuter-config -f my_fn --pattern decl-order
melee-agent debug gen-permuter-config -f my_fn --print  # dry-run

# Compile source file locally and score against a target spec (IGNode distance).
# Used as the external scorer for decomp-permuter (--quiet flag for machine use).
melee-agent debug score-source src/melee/mn/mnfoo.c -f my_fn --target target.json
melee-agent debug score-source src/melee/mn/mnfoo.c -f my_fn --target target.json --quiet

# Source-level variable ↔ virtual register bridge (symbol bridge)
melee-agent debug var-to-virtual my_var -f my_fn          # which virtual does my_var map to?
melee-agent debug var-to-virtual my_var -f my_fn --basis  # + show confidence evidence
melee-agent debug virtual-to-var r53 -f my_fn             # which source var maps to r53?
melee-agent debug virtual-to-ig -f my_fn --virtual r108   # map visible pcode virtual to allocator graph
melee-agent debug virtual-to-ig -f my_fn --virtual r50 --class gpr  # disambiguate GPR/FP ig_idx collisions

# Suggest C-source patterns to produce a specific coalesce (or discover candidates)
melee-agent debug suggest-coalesce-source -f my_fn -V 53=3          # pair mode: coalesce r53 with r3
melee-agent debug suggest-coalesce-source -f my_fn --discover --top 5  # discover best candidates
# Preflight warnings flag unsafe force-coalesce probes, including direct
# interference, pairs where either virtual is absent from the colorgraph, and
# non-interfering pairs that lack a direct pre-coloring copy/identity edge.

# Trace a source-created pcode copy through the allocator. Use this when a
# manual local/temp creates `mr rTO,rFROM` before coloring, but final ASM
# appears to coalesce or remove the copy. The report includes the first pass
# where the copy is absent and a coarse transform category.
melee-agent debug trace-copy -f my_fn --from r50 --to r108
melee-agent debug trace-copy -f my_fn --from r50 --to r108 --class gpr
melee-agent debug trace-copy -f my_fn --from r50 --to r108 --json
melee-agent debug trace-copy -f my_fn --list-copies
melee-agent debug trace-copy -f my_fn --involving r50 --near-block 245

# Suggest hidden inline/helper source shapes
melee-agent debug suggest-inlines -f my_fn
melee-agent debug suggest-inlines -f my_fn --seed-source repeated
melee-agent debug suggest-inlines -f my_fn --seed-source coalesce  # pattern fallback for coalesce leads
melee-agent debug suggest-inlines -f my_fn --verify
melee-agent debug suggest-inlines -f my_fn --verify --trace-copies
melee-agent debug suggest-inlines -f my_fn --verify --explain
melee-agent debug suggest-inlines -f my_fn --verify --checkdiff-timeout 120
melee-agent debug suggest-inlines -f my_fn --verify --apply-best
melee-agent debug suggest-inlines -f my_fn --json              # summaries only
melee-agent debug suggest-inlines -f my_fn --json --emit-hunks
melee-agent debug suggest-inlines -f my_fn --json --emit-patches

# `suggest-inlines` is diagnostic by default. It reports repeated/helper-shaped
# statement groups, short-lived call-argument temp candidates, and rejected
# candidates with reasons. Pattern seeds understand visible
# `HSD_JObjSetTranslateX/Y/Z` calls as hiding `HSD_JObjSetMtxDirtySub`, so they
# can propose typed cursor-copy/dirty-call lifetime splits, including grouped
# X/Y/Z candidates, even when the dirty call is inside a header inline or a
# same-source direct static-inline helper and comments before the helper contain
# non-ASCII text. Use `--verify` to stage candidates and score them against
# real-tree `checkdiff`; output includes baseline percent, candidate percent,
# and delta, and source is restored unless `--apply-best` keeps a verified
# winner. Use `--trace-copies` or `--explain` with `--verify` when you need to
# know whether a candidate-introduced `mr` copy survives to simplify/colorgraph
# or is eliminated before coloring. Human output summarizes the
# candidate-relevant subset first, especially copies involving the candidate
# argument's source virtual or patch-local block, then dominant source-virtual
# copies that are removed before coloring. Labels distinguish copies eliminated
# before coloring from copies that survive coloring but disappear later, and
# before-coloring eliminations sort ahead of generic later disappearances. The
# summary reports how many noisy candidate-only copies were omitted. Use
# `--json --emit-hunks` (alias: `--emit-diffs`) for compact unified diffs
# without full `patched_source` payloads; reserve `--emit-patches` for the full
# rewritten TU.

# Keep temporary source probes out of the canonical pcdump cache.
melee-agent debug pcdump-local src/melee/mn/mnvibration.c --no-cache-sync
melee-agent debug pcdump-local src/melee/mn/mnvibration.c --diff --checkdiff-timeout 120
melee-agent debug pcdump-local src/melee/mn/mnvibration.c --output /tmp/probe.txt --no-cache-sync
# If MWCC_DEBUG_HANG_TIMEOUT kills a local compile, pcdump-local exits 124 even
# if it wrote a partial dump, so scripts do not treat the partial as valid.

# Apply targeted source mutations (type change, alias insertion)
melee-agent debug mutate type-change -f my_fn --var my_var --type u32
melee-agent debug mutate type-change -f my_fn --var my_var --type u32 --apply
melee-agent debug mutate insert-alias -f my_fn --var my_var --at 0
melee-agent debug mutate insert-alias -f my_fn --var my_var --at 0 --apply

# Multi-start search over targeted mutation seeds (Tier 3)
# Enumerates variable bindings, plans seed mutations, smoke-compiles each,
# then launches permuter per seed. Use when manual attempts stall.
melee-agent debug tier3-search -f my_fn
melee-agent debug tier3-search -f my_fn --budget 10 --per-seed-iters 500
```

**There is NO patched permuter binary.** Run upstream `decomp-permuter`
as usual; mwcc-debug just informs (`gen-permuter-config`) and filters
(`triage-perm`) around it. See
[docs/mwcc-debug-permuter-integration.md](../../docs/mwcc-debug-permuter-integration.md)
for the full Tier 0 / Tier 1 / deferred-tier picture.

The `pcdump` (remote) wrapper:
1. SSHes to the remote with the relative .c path
2. Remote: acquires a lock, `git pull --rebase` (so it sees current master), installs patched DLL, runs `mwcceppc.exe` with stock Melee flags
3. Remote: streams `pcdump.txt` bytes back over SSH stdout
4. Local: writes raw bytes to `--output` file (or stdout)
5. Remote: restores stock DLL via `try/finally` (so a crash doesn't leave the patched DLL installed)

**For the remote pcdump path only:** uncommitted local changes are not seen by the remote. Commit + push first (auto-push is on master, so a normal commit is enough). Local mode (`pcdump-local`) always sees the current working tree.

### Function-scoped force options

All `--force-phys`, `--force-iter-first`, and `--force-coalesce` options accept a `-fn` scoped variant that limits the override to a single named function in multi-function TUs:

```bash
# Scope --force-phys to one function only
melee-agent debug pcdump src/melee/mn/mnfoo.c \
    --force-phys "36:31" --force-phys-fn mnFoo_80246000

# Scope --force-coalesce to one function only
melee-agent debug pcdump src/melee/mn/mnfoo.c \
    --force-coalesce "53=3" --force-coalesce-fn mnFoo_80246000

# Scope --force-iter-first to one function
melee-agent debug pcdump src/melee/mn/mnfoo.c \
    --force-iter-first "62,47" --force-iter-first-fn mnFoo_80246000

# Force by colorgraph iteration position (for nodes without an addressable ig_idx)
melee-agent debug pcdump src/melee/mn/mnfoo.c \
    --force-phys-iter "0:3:31"   # class 0, iter 3 → r31
```

Use `-fn` variants when the TU has multiple functions and the override would otherwise affect all of them.
`match-iter-first --auto-verify` uses `--force-iter-first-fn` automatically,
prints the exact scoped force list before compiling, and emits periodic
status while `pcdump-local`'s watchdog bounds no-progress hangs.

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
- **One TU at a time.** The DLL is swapped repo-wide; for remote mode the script holds a lock so concurrent invocations queue. Local mode uses a unique pcdump path per invocation (no locking needed).
- **Output is large.** A typical Melee TU produces 50KB–MB. Use `--output` rather than streaming.
- **Remote mode requires committed code.** The remote does `git pull --rebase`, so uncommitted local changes aren't seen. Commit first (auto-push on master). Local mode (`pcdump-local`) always uses the current working tree — no commit required.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ssh: Could not resolve hostname nzxt-local` | Check SSH config; set `MWCC_DEBUG_HOST` to your host alias |
| Remote: `patched DLL not found` | Re-run setup (scp + Move-Item) |
| Remote: `lock held by PID=N` | A previous run is in flight or crashed. Wait 30 min or `ssh nzxt-local 'powershell -Command "Remove-Item $env:TEMP\mwcc_debug.lock"'` |
| Remote: `git pull failed: You are not currently on a branch` | The Windows repo is in detached HEAD. `ssh nzxt-local 'cd /c/Users/mikes/code/melee && git fetch origin && git reset --hard origin/master'` |
| `compile exit=124` (timeout) | Either a very large TU or mwcceppc hung. Try `--timeout 300`. If still timing out, the TU is unusually large — try splitting or using `pcdump-local` instead. |
| Empty pcdump.txt | Compile failed too early to produce output. Check the stderr passthrough in the wrapper output. |

## Compare to mwcc-inspect

| Aspect | mwcc-debug | mwcc-inspect |
|--------|------------|--------------|
| **Stage** | Back-end (codegen passes, register allocation) | Front-end (parsing, AST, IR) |
| **Output** | Per-pass PCode dump for each function | Per-function ENode tree + ObjObject list |
| **Mechanism** | Patches `lmgr326b.dll` to unlock `debuglisting=1` | Attaches debugger via `dbgeng.dll` |
| **Best for** | "Why did the allocator pick THESE registers?" | "How did the compiler parse my expressions?" |
| **Output size** | 50KB–MB per TU (very verbose) | 5–50KB per function (structured) |
| **Stability** | Stable: local (macOS/wibo) + remote (Windows). Local is preferred. | Stable on Windows, not built for macOS |

You can use both on the same TU back-to-back to triangulate.

## See also

- Upstream tool: https://github.com/Savestate2A03/mwcc_debug
- Workflow doc: [docs/mwcc-debug.md](../../docs/mwcc-debug.md)
- macOS local mode docs: [docs/mwcc-debug-poc-design.md](../../docs/mwcc-debug-poc-design.md) and [docs/mwcc-debug-poc-plan.md](../../docs/mwcc-debug-poc-plan.md) (PoC docs, now shipped as `pcdump-local`)
- Sister skill: `/mwcc-inspect` for front-end IR
