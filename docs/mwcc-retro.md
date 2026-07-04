# mwcc-retro workflow

`mwcc-retro` runs the **retail** MWCC GC/1.2.5n compiler under the retrowin32
x86 emulator with a gdb stub, then reads compiler-internal data structures. For
GC/1.2.5n it produces front-end IRO optimizer traces and exact retail
backend/regalloc traces. Backend map, IG, and PCode probe commands remain
available for lower-level diagnostics. Unlike
`mwcc-inspect` (which gives a single front-end IR snapshot), `mwcc-retro` traces
the IR **through every optimizer pass** and does so from the unmodified retail
binary.

## When to reach for each tool

| Situation | Best tool |
|---|---|
| First investigation; need callers/strings/xrefs | `ghidra`, `mismatch-db`, `opseq`, `discord-knowledge` |
| Need parsed expression trees or ObjObject IDs | `mwcc-inspect` |
| Need fast back-end PCode, virtual registers, coloring decisions | `mwcc-debug` (fast; DLL pcdump) |
| Need exact retail GC/1.2.5n backend/regalloc facts | `mwcc-retro backend` |
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

# Front-end IRO trace (1.2.5n)
melee-agent debug retro dump src/melee/mn/mndraw.c -f mnDraw_8024A3B0

# Front-end only (fast; skip backend when you only need the IRO trace)
melee-agent debug retro dump src/melee/gm/gm_1BA8.c -f gm_801BCC9C --phases frontend

# Exact retail GC/1.2.5n backend/regalloc trace
melee-agent debug retro backend src/melee/lb/lb_00B0.c -f lb_8000CE30

# Exact retail trace plus retail-vs-debug-DLL fidelity report
melee-agent debug retro backend src/melee/lb/lb_00B0.c -f lb_8000CE30 --verify-debug

# GC/1.2.5n backend map evidence probe; writes candidates/probe JSON, not a trace
melee-agent debug retro probe-backend-map src/melee/lb/lbarq.c -f lbArq_80014ABC

# GC/1.2.5n partial retail IG/order/coalesce/color snapshot.
# Also writes backend-colorgraph-* sidecar files for exact internal color decisions when observed.
melee-agent debug retro probe-backend-ig src/melee/lb/lbarq.c -f lbArq_80014ABC

# GC/1.2.5n partial retail PCode/block snapshot; writes block/pcode events only
melee-agent debug retro probe-backend-pcode src/melee/lb/lbarq.c -f lbArq_80014ABC

# GC/1.2.5n candidate backend trace assembled from separate validated partial probes.
# Writes backend-trace.candidate.v1.json for diagnostics and schema fixtures.
melee-agent debug retro backend-candidate src/melee/lb/lb_00B0.c -f lb_8000CE30

# One-pass candidate diagnostic path: one retail compile, same candidate-only outputs.
melee-agent debug retro backend-candidate src/melee/lb/lb_00B0.c -f lb_8000CE30 --one-pass

# Compare a full or candidate backend trace with an existing mwcc-debug pcdump.
# With -O pointed at a candidate output dir, verify-backend falls back to
# backend-trace.candidate.v1.json when backend-trace.v1.json is absent.
melee-agent debug retro verify-backend src/melee/lb/lb_00B0.c -f lb_8000CE30 --debug-pcdump pcdump.txt

# After a vendor SHA update, confirm retail fidelity is intact
melee-agent debug retro verify
```

Output lands in `build/mwcc_retro/<unit>/<fn>/`. The most useful files for
front-end investigation are `iro-trace.txt`, the split `iro-NN-<phase>.txt`
files, and `iro-summary.txt`. For exact retail backend work, start with
`backend-trace.v1.json`, `regalloc-summary.txt`, and `backend-summary.txt`.

## Backend map probe

`melee-agent debug retro probe-backend-map <src.c> -f <FUNCTION>` is the
GC/1.2.5n backend-tracer bring-up command. It does not produce a consumable
backend trace. Instead, it records the evidence needed to promote retail
compiler addresses and structure fields into the backend map:

- `backend-map-candidates.json`: static PE presence evidence for required
  backend keys, with confidence values that still require live invariants.
- `backend-map-probe.json`: live retrowin32+gdb stage hits, sampled globals,
  and function-scoping evidence for the requested function.
- `backend-map-evidence.json`: normalized promotable-vs-blocked facts derived
  from the live probe. Promotable entries use `confidence: live-invariant`;
  blocked entries include a reason.
- `launch.log`: the emulator/gdb transcript.

The live probe runs the raw `.o` byte-parity gate before trusting any backend
state. Use `--static-only` when you only need the candidate report. Some map
facts are class-dependent: a GPR-only function can prove `used_vreg_gpr`, while
a function with FPR allocation is needed to prove `used_vreg_fpr`.

## Backend IG snapshot probe

`melee-agent debug retro probe-backend-ig <src.c> -f <FUNCTION>` compiles the
requested TU through the unmodified retail GC/1.2.5n compiler and emits the
exact retail interference graph plus post-`colorgraph` order, coalesced-alias
mappings, and observed assignment/blocker rows as partial backend events:

- `backend-ig-snapshot.json`: requested-function match status, functions seen,
  classes captured, and hook errors.
- `backend-ig-snapshot-events.v1.jsonl`: `function_start`, `backend_marker`,
  `regclass`, `node`, `edge`, `coalesce_mapping`, `coalesce_mapping_empty`,
  `simplify_order`, `select_order`, and optional `color_decision` events.

This is a bring-up artifact, not `backend-trace.v1.json`. Use
`debug retro backend` when you need the full normalized allocator, PCode, and
frame facts in one output.

## Backend PCode snapshot probe

`melee-agent debug retro probe-backend-pcode <src.c> -f <FUNCTION>` compiles
the requested TU through retail GC/1.2.5n, stops at a proven PCode backend
stage, and emits partial block/PCode events:

- `backend-pcode-snapshot.json`: requested-function match status, functions
  seen, captured pass counts, and hook errors.
- `backend-pcode-snapshot-events.v1.jsonl`: `function_start`,
  `backend_marker`, `block`, and `pcode_instruction` events.

This is a bring-up artifact, not `backend-trace.v1.json`. Use
`debug retro backend` when you need allocator classes, live ranges, color
decisions, simplify/select order, scheduler output, and frame maps together.

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

For backend/regalloc fidelity, use `debug retro verify-backend` with an
existing mwcc-debug pcdump, or `debug retro backend --verify-debug` when a
cached/generated pcdump can be resolved for the function.

Run `verify` whenever you update a vendor SHA or when a dump seems to
contradict what `mwcc-debug` shows for the same function.

## Output file reference

All output goes to `build/mwcc_retro/<unit>/<fn>/`:

| File | Contents | When produced |
|------|----------|---------------|
| `iro-trace.txt` | All IRO passes concatenated | Frontend (both compilers) |
| `iro-NN-<phase>.txt` | One file per optimizer pass | Frontend (both compilers) |
| `iro-summary.txt` | Node ledger (added/removed per transition) | Frontend (both compilers) |
| `backend-events.v1.jsonl` | Raw retail backend/regalloc events | GC/1.2.5n backend (`debug retro backend`) |
| `backend-onepass-summary.json` | Hook completeness summary and warnings | GC/1.2.5n backend (`debug retro backend`) |
| `backend-trace.v1.json` | Stable PCode, frame, and allocator facts | GC/1.2.5n backend (`debug retro backend`) |
| `regalloc-summary.txt` | Compact allocator summary for diffs | GC/1.2.5n backend (`debug retro backend`) |
| `backend-summary.txt` | Human-readable backend/PCode/frame summary | GC/1.2.5n backend (`debug retro backend`) |
| `backend-fidelity.json` / `backend-fidelity.txt` | Retail-vs-mwcc-debug comparison | `verify-backend`, `backend --verify-debug` |
| `frontend-NN-ast-<pass>.txt` | AST per front-end pass | GC/1.1 backend (`--compiler 1.1`) |
| `backend-NN-<pass>.txt` | Back-end PCode per pass | GC/1.1 backend (`--compiler 1.1`) |
| `regalloc-<cls>-pass-N-all.txt` | Allocator priority, cost, and adjacency | GC/1.1 backend (`--compiler 1.1`) |
| `regalloc-<cls>-pass-N-assigned.txt` | Final register assignments | GC/1.1 backend (`--compiler 1.1`) |
| `variables.txt` | Stack map (variable home assignments) | GC/1.1 backend (`--compiler 1.1`) |
| `backend-ig-snapshot.json` | Partial retail IG/order/coalesce/color snapshot status | `probe-backend-ig` |
| `backend-ig-snapshot-events.v1.jsonl` | Partial `regclass`/`node`/`edge`/coalesce/order/color events | `probe-backend-ig` |
| `backend-pcode-snapshot.json` | Partial retail PCode snapshot status | `probe-backend-pcode` |
| `backend-pcode-snapshot-events.v1.jsonl` | Partial `block`/`pcode_instruction` events | `probe-backend-pcode` |
| `launch.log` | Emulator stdout/stderr for this run | `dump`, failed probes |
| `provenance.json` | Compiler identity, vendor SHAs, fidelity-gate result | `dump` |

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
