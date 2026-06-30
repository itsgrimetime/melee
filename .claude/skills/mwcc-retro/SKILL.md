---
name: mwcc-retro
description: Dump retail MWCC GC/1.2.5n front-end IRO per-pass traces + backend PCode, register-allocator internals, and stack maps via retrowin32+gdb. Use when you need front-end optimizer pass visibility (CSE, loop unrolling, propagation, DCE) or a retail-vs-debug-DLL fidelity check. Not first-resort — reach for mismatch-db, opseq, ghidra, discord-knowledge, and mwcc-debug first.
---

# MWCC Retro

Runs the **retail** MWCC GC/1.2.5n compiler under the retrowin32 x86 emulator
with a gdb stub and reads compiler-internal data structures directly from the
emulated process. Produces front-end IRO optimizer traces (one snapshot per
optimizer pass: CSE, loop unrolling, constant propagation, DCE, and others),
back-end PCode passes, register-allocator priority/cost/adjacency dumps, and
stack allocation maps — all from the unmodified retail binary.

Use this after the lighter tools have been exhausted and you specifically
need to see what the front-end optimizer did, or when you suspect a residual
mismatch is a debug-DLL artifact rather than genuine retail behavior.

## Quick Workflow

```bash
# One-time: clone and build retrowin32 + cadmic/mwcc-debugger at pinned SHAs; run P0 gate
melee-agent debug retro setup

# Front-end IRO trace (1.2.5n). Backend/regalloc/stack: --compiler 1.1, or mwcc-debug for 1.2.5n backend.
melee-agent debug retro dump src/melee/mn/mndraw.c -f mnDraw_8024A3B0

# Front-end only (faster; skip backend when you only need the IRO trace)
melee-agent debug retro dump src/melee/gm/gm_1BA8.c -f gm_801BCC9C --phases frontend

# Backend (GC/1.1 only today)
melee-agent debug retro dump src/melee/lb/lbarq.c -f lbArq_80014ABC --phases backend --compiler 1.1

# After a vendor SHA update, confirm retail fidelity
melee-agent debug retro verify
```

Output goes to `build/mwcc_retro/<unit>/<fn>/`. Key files: `iro-trace.txt`
(all IRO passes concatenated), `iro-NN-<phase>.txt` (one file per pass, diff
adjacent pairs to see what each phase changed), `iro-summary.txt` (node
ledger: which IROLinear indices appeared or disappeared between passes).

## When to use this

| Situation | Recommendation |
|---|---|
| First look at a function | `tools/checkdiff.py`, m2c, nearby source |
| Diff matches a known pattern | `/mismatch-db` or `/opseq` |
| Need callers, callees, or string xrefs | `/ghidra` |
| Need parsed expression trees or ObjObject IDs | `/mwcc-inspect` |
| Back-end PCode, basic blocks, virtual regs, coloring (fast path) | `/mwcc-debug` |
| Front-end IRO pass-by-pass trace (CSE, unrolling, propagation, DCE…) | This skill |
| Confirm a mismatch is retail vs. debug-DLL artifact | `melee-agent debug retro verify` |

`mwcc-retro` is diagnosis-grade: the emulated compile is slower than the
wibo/DLL path. Use it when `mwcc-debug` and source-shape experiments have not
explained the residual and front-end pass visibility is specifically needed.

If `iro-summary.txt` shows no node changes across all passes, the mismatch is
purely back-end — switch to `/mwcc-debug` for register-coloring investigation.

## Tooling Issue Gate

Report bugs, hangs, unexpected output, and missing affordances immediately.

```bash
melee-agent issue report "mwcc-retro dump hung after iro pass 07" \
  --tool mwcc-retro --kind bug --function fn_80247510 \
  --body "Command run, last visible output, timeout elapsed, and what this blocked"
```

Include the function, the `--phases` flag used, and the last line of output
before the hang. The issue queue is shared across agents; claim an issue
before working it and resolve it with a note when fixed.

## See also

- Tool README: [tools/mwcc_retro/README.md](../../tools/mwcc_retro/README.md)
- Workflow doc: [docs/mwcc-retro.md](../../docs/mwcc-retro.md)
- Spec: [docs/superpowers/specs/2026-06-10-mwcc-retro-debugger-design.md](../../docs/superpowers/specs/2026-06-10-mwcc-retro-debugger-design.md)
- Plan: [docs/superpowers/plans/2026-06-10-mwcc-retro-debugger.md](../../docs/superpowers/plans/2026-06-10-mwcc-retro-debugger.md)
- Sister skill: `/mwcc-debug`
