---
name: mwcc-retro
description: Dump retail MWCC GC/1.2.5n front-end IRO and exact backend/regalloc traces via retrowin32+gdb. Use when you need optimizer pass visibility, retail PCode/allocator facts, or retail-vs-debug-DLL fidelity after lighter matching tools and mwcc-debug.
---

# MWCC Retro

Runs the **retail** MWCC GC/1.2.5n compiler under the retrowin32 x86 emulator
with a gdb stub and reads compiler-internal data structures directly from the
emulated process. For GC/1.2.5n it produces front-end IRO optimizer traces (one
snapshot per optimizer pass: CSE, loop unrolling, constant propagation, DCE, and
others) plus exact retail backend/regalloc traces. Lower-level backend map,
interference-graph, PCode, and candidate probes remain available for diagnostics.

Use this after the lighter tools have been exhausted and you specifically
need to see what the front-end optimizer did, need exact retail allocator/PCode
facts, or suspect a residual mismatch is a debug-DLL artifact rather than
genuine retail behavior.

## Quick Workflow

```bash
# One-time: clone and build retrowin32 + cadmic/mwcc-debugger at pinned SHAs; run P0 gate
melee-agent debug retro setup

# Before any stripped GC/1.2.5n compiler static audit, validate the bounded,
# exact-hash, host-native Ghidra project.
melee-agent debug retro ghidra-setup

# Front-end IRO trace (1.2.5n)
melee-agent debug retro dump src/melee/mn/mndraw.c -f mnDraw_8024A3B0

# Front-end only (faster; skip backend when you only need the IRO trace)
melee-agent debug retro dump src/melee/gm/gm_1BA8.c -f gm_801BCC9C --phases frontend

# Backend through the GC/1.1 donor/reference route
melee-agent debug retro dump src/melee/lb/lbarq.c -f lbArq_80014ABC --phases backend --compiler 1.1

# Exact retail GC/1.2.5n backend/regalloc trace
melee-agent debug retro backend src/melee/lb/lb_00B0.c -f lb_8000CE30

# Exact retail trace plus retail-vs-debug-DLL fidelity report
melee-agent debug retro backend src/melee/lb/lb_00B0.c -f lb_8000CE30 --verify-debug

# GC/1.2.5n backend map evidence probe; writes backend-map-evidence.json, no trace
melee-agent debug retro probe-backend-map src/melee/lb/lbarq.c -f lbArq_80014ABC

# GC/1.2.5n partial retail IG/order/coalesce/color snapshot plus exact colorgraph sidecar
melee-agent debug retro probe-backend-ig src/melee/lb/lbarq.c -f lbArq_80014ABC

# GC/1.2.5n partial retail PCode/block snapshot; writes block/pcode JSONL only
melee-agent debug retro probe-backend-pcode src/melee/lb/lbarq.c -f lbArq_80014ABC

# GC/1.2.5n candidate backend/regalloc diagnostic; writes backend-trace.candidate.v1.json
melee-agent debug retro backend-candidate src/melee/lb/lb_00B0.c -f lb_8000CE30

# One-pass candidate diagnostic path. Still writes only candidate outputs.
melee-agent debug retro backend-candidate src/melee/lb/lb_00B0.c -f lb_8000CE30 --one-pass

# Compare a full or candidate backend trace with an mwcc-debug pcdump.
melee-agent debug retro verify-backend src/melee/lb/lb_00B0.c -f lb_8000CE30 --debug-pcdump pcdump.txt

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
| Static audit of the stripped GC/1.2.5n compiler | Run `melee-agent debug retro ghidra-setup` first |
| Need parsed expression trees or ObjObject IDs | `/mwcc-inspect` |
| Back-end PCode, basic blocks, virtual regs, coloring (fast path) | `/mwcc-debug` |
| Need retail GC/1.2.5n backend/regalloc evidence | `melee-agent debug retro backend` |
| Front-end IRO pass-by-pass trace (CSE, unrolling, propagation, DCE…) | This skill |
| Confirm a mismatch is retail vs. debug-DLL artifact | `melee-agent debug retro verify` or `verify-backend` |

`mwcc-retro` is diagnosis-grade: the emulated compile is slower than the
wibo/DLL path. Use it when `mwcc-debug` and source-shape experiments have not
explained the residual and you need either front-end pass visibility or exact
retail GC/1.2.5n backend/regalloc facts.

For static audits of the stripped compiler executable, always run
`melee-agent debug retro ghidra-setup` first. Do not invoke archived or
hard-coded Ghidra installations directly: the setup command enforces the exact
compiler hash, a host-native decompiler, bounded analysis, and a nonempty
validated project. Use `--repair` when it reports an invalid retained project.

If `iro-summary.txt` shows no node changes across all passes, the mismatch is
purely back-end. Start with `/mwcc-debug` for speed, then use
`debug retro backend` when you need retail GC/1.2.5n allocator facts.

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
