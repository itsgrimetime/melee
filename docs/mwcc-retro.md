# mwcc-retro workflow

`mwcc-retro` runs the **retail** MWCC GC/1.2.5n compiler under the retrowin32
x86 emulator with a gdb stub, then reads compiler-internal data structures to
produce front-end IRO optimizer traces, back-end PCode passes,
register-allocator dumps, and stack maps. Unlike `mwcc-debug` (which uses a
patched debug DLL) and `mwcc-inspect` (which gives a single front-end IR
snapshot), `mwcc-retro` traces the IR **through every optimizer pass** and
does so from the unmodified retail binary.

## When to reach for each tool

| Situation | Best tool |
|---|---|
| First investigation; need callers/strings/xrefs | `ghidra`, `mismatch-db`, `opseq`, `discord-knowledge` |
| Need parsed expression trees or ObjObject IDs | `mwcc-inspect` |
| Need back-end PCode, basic blocks, virtual registers, coloring decisions, scheduling | `mwcc-debug` (fast; DLL pcdump) |
| Need front-end IRO pass-by-pass trace (CSE, loop unrolling, propagation, DCE…) | `mwcc-retro` |
| Suspect a mismatch is a debug-DLL artifact vs. retail | `mwcc-retro verify` |
| Register mismatch confirmed, source shape is already correct | `mwcc-debug` force options + permuter |

`mwcc-retro` is **diagnosis-grade** (emulated compile is slower than the
wibo/DLL path). Do not reach for it in the inner search loop. Use it when
lighter tools have failed to explain a residual and you specifically need
front-end visibility or retail-vs-DLL confirmation.

## Quick workflow

```bash
# One-time setup: clone+build retrowin32 and cadmic/mwcc-debugger, run P0 gate
melee-agent debug retro setup

# Front-end IRO trace (1.2.5n). Backend/regalloc/stack: --compiler 1.1, or mwcc-debug for 1.2.5n backend.
melee-agent debug retro dump src/melee/mn/mndraw.c -f mnDraw_8024A3B0

# Front-end only (fast; skip backend when you only need the IRO trace)
melee-agent debug retro dump src/melee/gm/gm_1BA8.c -f gm_801BCC9C --phases frontend

# After a vendor SHA update, confirm retail fidelity is intact
melee-agent debug retro verify
```

Output lands in `build/mwcc_retro/<unit>/<fn>/`. The most useful files for
front-end investigation are `iro-trace.txt`, the split `iro-NN-<phase>.txt`
files, and `iro-summary.txt`.

## Front-end IRO trace layout

`iro-trace.txt` is the concatenated trace of every IRO optimizer pass the
compiler ran on the target function. Passes appear in compilation order,
labeled by phase name. The per-pass split files (`iro-NN-<phase>.txt`, where
`NN` is a zero-padded sequence index) let you diff two consecutive passes
directly:

```bash
diff build/mwcc_retro/mn_mndraw/mnDraw_8024A3B0/iro-04-cse.txt \
     build/mwcc_retro/mn_mndraw/mnDraw_8024A3B0/iro-05-copy_prop.txt
```

Each phase file contains the IROLinear node list for the function as the
compiler saw it entering and leaving that phase. Nodes are numbered by their
index in the compiler's internal IR list.

### Reading iro-summary.txt

`iro-summary.txt` is a pass-iteration-aware node ledger. It answers:
"which IROLinear node indices appeared or disappeared between two passes?"

Structure of each entry:

```
IRO pass sequence (temp/node ledger v1):

[00] after IRO_BuildflowGraph (pre-loop) — 36 nodes
[01] after IRO_RemoveUnreachable (pre-loop) — 35 nodes
     removed: [35] (vs IRO_BuildflowGraph)
[12] after After IRO_LoopUnroller (pass=0) — 173 nodes
     added: [37, 38, 39, ...]
```

The `removed` list is the primary signal for CSE and DCE. If a node you
expected the compiler to keep was removed here, the matching pass is where the
deviation from your expected output began. The `added` list traces where new
nodes were introduced by optimizer actions (loop unrolling, strength
reduction), which can influence register pressure downstream.

If the summary shows no changes across all passes, the function's IR was
stable through the entire front-end optimizer and the mismatch is purely
back-end — switch to `mwcc-debug` for register-coloring investigation.

## Verify semantics

`melee-agent debug retro verify` cross-checks the emulated retail compile
against the normal wibo build by **byte-comparing the produced `.o`** for a
control TU. If they are byte-identical, the emulator is a faithful oracle and
its dumps can be trusted.

**Authoritative check** (failure means the dump cannot be trusted):

- The `.o` produced by the emulated retail path is byte-identical to the `.o`
  produced by the normal wibo/MWCC build for the control TU.

**Planned (follow-on #542):**

- Virtual-to-physical register map cross-check (depends on GC/1.2.5n backend port).
- Regalloc node count cross-check (depends on GC/1.2.5n backend port).
- LOOPWEIGHT value cross-check (depends on GC/1.2.5n backend port).

Run `verify` whenever you update a vendor SHA or when a dump seems to
contradict what `mwcc-debug` shows for the same function.

## Output file reference

All output goes to `build/mwcc_retro/<unit>/<fn>/`:

| File | Contents | When produced |
|------|----------|---------------|
| `iro-trace.txt` | All IRO passes concatenated | Frontend (both compilers) |
| `iro-NN-<phase>.txt` | One file per optimizer pass | Frontend (both compilers) |
| `iro-summary.txt` | Node ledger (added/removed per transition) | Frontend (both compilers) |
| `frontend-NN-ast-<pass>.txt` | AST per front-end pass | GC/1.1 backend (`--compiler 1.1`) |
| `backend-NN-<pass>.txt` | Back-end PCode per pass | GC/1.1 backend (`--compiler 1.1`) |
| `regalloc-<cls>-pass-N-all.txt` | Allocator priority, cost, and adjacency | GC/1.1 backend (`--compiler 1.1`) |
| `regalloc-<cls>-pass-N-assigned.txt` | Final register assignments | GC/1.1 backend (`--compiler 1.1`) |
| `variables.txt` | Stack map (variable home assignments) | GC/1.1 backend (`--compiler 1.1`) |
| `launch.log` | Emulator stdout/stderr for this run | Both |
| `provenance.json` | Compiler identity, vendor SHAs, fidelity-gate result | Both |

## Name-spoof note

The retail GC/1.2.5n compiler internally reports its descriptor as `"GC/1.1"`.
The cadmic struct readers use the descriptor for table disambiguation and were
designed to handle this uniformly. `provenance.json` always records the true
compiler identity (`GC/1.2.5n`) so stored dumps are never mislabeled.

## See also

- Tool README: [tools/mwcc_retro/README.md](../tools/mwcc_retro/README.md)
- Skill: [.claude/skills/mwcc-retro/SKILL.md](../.claude/skills/mwcc-retro/SKILL.md)
- Spec: [docs/superpowers/specs/2026-06-10-mwcc-retro-debugger-design.md](superpowers/specs/2026-06-10-mwcc-retro-debugger-design.md)
- Plan: [docs/superpowers/plans/2026-06-10-mwcc-retro-debugger.md](superpowers/plans/2026-06-10-mwcc-retro-debugger.md)
- Sister tool workflow: [docs/mwcc-debug.md](mwcc-debug.md)
