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

# Full trace (front-end IRO + backend PCode + regalloc + stack)
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

`iro-summary.txt` is a pass-iteration-aware node/temp ledger. It answers:
"which IROLinear node indices appeared or disappeared between two passes?"

Structure of each entry:

```
Pass 04 cse  ->  Pass 05 copy_prop
  ADDED   nodes: [42, 43]     # new IROLinear indices introduced this transition
  REMOVED nodes: [17, 31]     # indices present in pass 04 but gone by pass 05
  ADDED   temps: [t8]         # new temp names introduced
  REMOVED temps: [t3, t5]     # temps that were CSE'd, propagated away, or DCE'd
```

The `REMOVED nodes` list is the primary signal for CSE and DCE. If a node you
expected the compiler to keep was removed here, the matching pass is where the
deviation from your expected output began. The `ADDED temps` list traces where
new synthetic temporaries were introduced by optimizer actions (loop unrolling,
strength reduction), which can influence register pressure downstream.

If the summary shows no changes across all passes, the function's IR was
stable through the entire front-end optimizer and the mismatch is purely
back-end — switch to `mwcc-debug` for register-coloring investigation.

## Verify semantics

`melee-agent debug retro verify` cross-checks a retro dump against the DLL
pcdump on the same control translation unit.

**Authoritative checks** (failures mean the dump cannot be trusted):

- Virtual-to-physical register map matches between retro and DLL pcdump.
- Regalloc node counts match.
- Final code in the retro dump is byte-identical to the `.o` produced by the
  normal wibo/MWCC build.

**Advisory check** (flagged but does not fail):

- LOOPWEIGHT values: divergence is noted in the verify report. LOOPWEIGHT
  affects loop-optimization heuristics in the front-end and can differ between
  retail and debug builds in edge cases. A LOOPWEIGHT divergence does not
  invalidate the regalloc or final-code checks, but it is worth noting when
  the mismatch you are investigating involves loop structure.

Run `verify` whenever you update a vendor SHA or when a dump seems to
contradict what `mwcc-debug` shows for the same function.

## Output file reference

All output goes to `build/mwcc_retro/<unit>/<fn>/`:

| File | Contents |
|------|----------|
| `ast-dump.txt` | Parsed AST before optimization |
| `iro-trace.txt` | All IRO passes concatenated |
| `iro-NN-<phase>.txt` | One file per optimizer pass |
| `iro-summary.txt` | Node/temp ledger (added/removed per transition) |
| `pcode-*.txt` | Back-end PCode per pass |
| `regalloc.txt` | Allocator priority, cost, and adjacency |
| `variables.txt` | Stack map (variable home assignments) |
| `provenance.json` | Compiler identity, vendor SHAs, fidelity-gate result |

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
