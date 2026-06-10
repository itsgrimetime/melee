# mwcc-retro: usage & output interpretation

A practical field guide for `melee-agent debug retro`. Companion to the workflow
doc (`docs/mwcc-retro.md`) and spec (`docs/superpowers/specs/2026-06-10-mwcc-retro-debugger-design.md`).

## TL;DR — when to reach for it

Reach for mwcc-retro when you need to see **what the front-end IRO optimizer did
to your C** — loop unrolling, CSE, copy/constant propagation, induction-variable
rewrites, temp creation — on the **real retail GC/1.2.5n compiler**, with zero
perturbation. It is the only tool that dumps the IR **after each front-end pass**.

It is **diagnosis-grade, not first-resort**. Try `mismatch-db`, `opseq`, `ghidra`,
`discord-knowledge`, and `mwcc-debug` (DLL pcdump) first. Emulated compiles are
slower than the wibo path; this is for understanding a mismatch, not inner-loop search.

**Scope boundary (important):** it helps **front-end-shaped** mismatches (the IR
the compiler builds differs between your source and the target). It does **not**
directly help **register-coloring last-mile ceilings** (r30-vs-r27 tiebreaks,
spill order) — those are back-end. Per the near-100% census, the stuck pool is
ceiling-dominated, so a random 99%+ function is usually the *wrong* class for this
tool. The right candidates are lower-% functions with loops or structural diffs
(different instruction counts, extra/missing temps), not register swaps.

## Commands

```bash
# One-time: clone + build the vendored retrowin32 + cadmic at pinned SHAs
melee-agent debug retro setup

# Front-end IRO per-phase trace on RETAIL 1.2.5n (THE headline; scoped to one fn)
melee-agent debug retro dump src/melee/mn/mnvibration.c -f mnVibration_802474C4 --phases frontend

# Backend (AST + per-pass PCode + regalloc + stack) — GC/1.1 only today
melee-agent debug retro dump src/melee/lb/lbarq.c -f lbArq_80014ABC --phases backend --compiler 1.1

# Fidelity gate: is the emulator byte-faithful for this TU?
melee-agent debug retro verify --unit src/melee/mn/mnvibration.c
```

Notes:
- `-f/--function` takes the **C function name** (e.g. `mnVibration_802474C4`), not a
  mangled symbol. It scopes the dump to that one function.
- Default is `--phases all --compiler 1.2.5n`, which delivers the **frontend** trace
  (1.2.5n backend is follow-on #542; use `--compiler 1.1` or the DLL pcdump for backend).
- Output lands in `build/mwcc_retro/<unit>/<fn>/` (gitignored).

## Output files

| File | Phase | What it is |
|---|---|---|
| `iro-trace.txt` | frontend | Raw retail IRO dump stream for the target fn (the full thing) |
| `iro-NN-<phase>.txt` | frontend | The flowgraph/IR after each front-end pass, split out, in order |
| `iro-summary.txt` | frontend | Per-phase **node ledger** — which IR node indices appear/disappear per pass |
| `frontend-NN-ast-<pass>.txt` | backend (1.1) | AST: initial / after-optimizations / final |
| `backend-NN-<pass>.txt` | backend (1.1) | PCode after each back-end pass (CSE, copy-prop, scheduling, regalloc, peephole…) |
| `regalloc-<cls>-pass-N-{all,assigned}.txt` | backend (1.1) | Chaitin allocator: nodes in priority order, cost, adjusted cost, neighbors |
| `variables.txt` | backend (1.1) | Stack allocation map (r1+offset ranges) for args/locals/temps/spills |
| `launch.log` | both | gdb + emulator session log (read this when something looks wrong) |
| `provenance.json` | both | True compiler id, pins, exit code, what was produced |

## Interpreting the front-end IRO trace

The trace shows the optimizer's **pass pipeline** for one function. Read it as a
narrative of transformations:

- **`Starting function <fn>` / `Dumps for pass=N`** — the optimizer runs a fixpoint
  loop; `pass=0`, `pass=1`… are iterations. A pass cycle repeating means it found
  more to do. The pre-loop phases (BuildflowGraph, RemoveUnreachable, RemoveLabels)
  run once before the loop.
- **`Dumping function <fn> after <PHASE>`** — a snapshot of the full flowgraph IR
  after that pass. Diffing consecutive snapshots tells you exactly what each pass
  changed.
- **`IRO_FindLoops_Unroll:Found loop with header N` / `After IRO_LoopUnroller`** —
  the front-end unrolled a loop. Cross-check: the node count jumps (e.g. 35→173) and
  the asm shows N stores per iteration. This is the most common front-end-shape lever:
  if your loop unrolls differently than the target, the IR diverges here.
- **`Found induction variable …`** — the optimizer replaced `i*k` with a variable
  incremented by `k` each iteration. Source that defeats induction recognition (e.g.
  a function call in the loop, `u8` index) changes this.
- **propagation / CommonSubs / ConstantFolding** — CSE and copy/constant propagation.
  If the target has a temp where you have a recomputation (or vice versa), it shows here.

### Reading `iro-summary.txt` (the node ledger)

Format (it tracks **flowgraph node indices**, not named temps):

```
IRO pass sequence (node ledger v1):

[00] after IRO_BuildflowGraph (pre-loop) — 36 nodes
[01] after IRO_RemoveUnreachable (pre-loop) — 35 nodes
     removed: [35] (vs IRO_BuildflowGraph)
[12] after After IRO_LoopUnroller (pass=0) — 173 nodes
     added: [37, 38, 39, …]      <- the unroll created 138 IR nodes here
```

Use it as an index: find the pass where node count or membership changes sharply,
then open the matching `iro-NN-<phase>.txt` to see the actual IR.

`iro-summary.txt` also ends with a **named-leaf creation-order timeline** (#544):
every front-end temp (`temp_rN`), var (`var_rN`), source local, and data symbol
in the order it **first appears** across the trace, with the introducing phase,
plus a one-line **synthesized-temp creation sequence** (e.g. `temp_r4 -> var_r4`).
This is the front-end materialization order — the signal upstream of back-end
vreg/`ig_idx` ordering. Node indices renumber every phase so they're not stable
across phases; the temp/var *names* are, which is why the timeline keys on them.

## Interpreting the backend output (GC/1.1)

`regalloc-gpr-pass-1-assigned.txt` is the most useful for matching:
- Variables are listed in **priority order** (the order Chaitin assigns them).
- `cost` / `adjusted cost` (= cost ÷ remaining-neighbors) = spill cost; lowest gets
  spilled first.
- `previous neighbors` / `neighbors` = interference. The allocator gives each variable
  the lowest free register not taken by a previous neighbor.
- Note: this is GC/1.1 (a proxy for the 1.0–1.2.5 family). For exact 1.2.5n back-end
  behavior today, use the `mwcc-debug` DLL pcdump (`debug dump local`). Retrowin32
  backend on 1.2.5n is follow-on #542.

## The matching workflow (where it earns its keep)

Front-end visibility is most powerful **comparatively**:

1. Dump the IRO trace of your current (stuck) source.
2. Dump a reference: a matched sibling function in the same TU, or a target-equivalent
   source variant.
3. Diff the per-phase files (`iro-NN-*.txt`) to find the **earliest** pass where the
   two diverge. That divergence is the front-end behavior your source isn't
   reproducing.
4. Reshape the C to make that pass behave the same (e.g. change a loop so it unrolls
   the same, restructure an expression so CSE fires the same), re-dump, repeat.

If the front-end IR is **identical** between your source and a target-equivalent but
the asm still differs, the residual is **back-end** (register coloring / scheduling) —
stop using this tool and switch to the back-end provenance workflow below. That's a
real, useful conclusion, not a failure.

### Back-end / register-coloring residuals: `explain-virtual`

When the mismatch is a coloring tiebreak — two temps assigned swapped registers
(e.g. ig_idx 88 got r27 but should be r25) — the front-end IRO trace will be
identical and won't help. Use the pcdump's allocator provenance instead:

```bash
# Get a pcdump (back-end) for the function:
melee-agent debug dump local src/melee/mn/mndiagram.c --output /tmp/d.txt
# Read the COLORGRAPH DECISIONS section for the offending ig_idx values, then:
melee-agent debug inspect explain-virtual -f mnDiagram_InputProc --ig 88,90 --pcdump /tmp/d.txt
```

`--ig N,M` answers "what *is* ig_idx N?" — it maps each ig_idx to its virtual
register (ig_idx N == virtual rN), then reports the **assigned physical register,
the defining instruction** (e.g. `subfic r88,r36,25` = a `25 - i` bound check),
the **source line/expression** it attributes to, and the **interferers**. That tells
you which C expression each coloring node corresponds to, so you know where to nudge.
(`--virtuals rN` / `--all` / `--pairs rA/rB` are the other entry points; `--pairs`
is useful for "why do these two interfere?".) This is the right tool for the
coloring-tiebreak class that dominates the near-100% stuck pool — *not* mwcc-retro's
front-end trace.

## Operational notes / gotchas

- **Per-function scoping is real:** the dump contains only the target fn's phases
  (the tool toggles the compiler's dump file on only while that function compiles).
  Other functions in the TU emit nothing.
- **Exit codes:** `0` produced; `2` compile-under-emulation failed; `3` target
  function never compiled in that TU (check the name); `4` partial (a requested phase
  stream is missing — see `launch.log`); `5` a safety byte-assert fired (the binary
  layout didn't match expectation — file a tooling issue).
- **Serialized on port 9001:** retrowin32's gdb port is hardcoded, so retro runs are
  serialized via a lockfile. Don't run two retro dumps concurrently; they'll queue.
- **No on-disk mutation:** all the compiler patches (enabling dumps, NOPping the
  per-phase flag) land only in the emulated process memory; the real `mwcceppc.exe`
  is never modified.
- **`verify` is the trust check:** if `debug retro verify` reports byte-parity for a
  TU, the emulator is faithful and its dumps are trustworthy for that TU. Run it once
  if you doubt a result.
- **Speed:** expect a few seconds per single-function dump (whole-TU compile under
  emulation + gdb). Fine for diagnosis; don't script thousands of these.

## Intervention hooks: `--gdb-py` (mutate state, replay forward)

For experiments beyond dumping — forcing a specific compiler state at a stage
and watching the downstream effect — `dump` accepts an intervention hook:

```bash
melee-agent debug retro dump <tu> -f <fn> \
    --gdb-py tools/mwcc_retro/hooks/example_intervene.py
```

The hook is a `.py` defining `intervene(ctx)`; the runtime hands it the
connected, descriptor-injected gdb session. `ctx` (a RetroContext) exposes the
write-capable substrate: `ctx.addr(key)` (named VA from the 1.2.5n table),
`ctx.read/write`, `ctx.u32/set_u32`, `ctx.reg(name)`, `ctx.brk(va)`,
`ctx.cont()`, and `ctx.call(fn_va, *int_args)` (staged-pointer calls). All
writes hit the emulated inferior only — the exe on disk is never modified. See
`tools/mwcc_retro/hooks/example_intervene.py` for a worked example (break,
read, register, write+readback, continue). This generalizes "intervene at
stage k, replay forward" beyond the DLL's force-phys/coalesce.

## Back-end on 1.2.5n via retrowin32 (#542): why it's the DLL's job

Porting cadmic's GC/1.1 backend address table to 1.2.5n was attempted and is
**not reliably achievable by byte-correlation alone**, so 1.2.5n backend stays on
the DLL pcdump path. The evidence (recorded in `tables/gc_125n.json` under
`backend_partial`): drift is **non-uniform** across the binary — the codegen
region drifts `+0x10` (codegen_start 0x4351B0→0x4351C0, verified prologue) but
the regalloc region drifts `-0x710` (regalloc-end 0x4CEB04→0x4CE3F4, verified
just inside colorgraph). Worse, the correlator produces **false matches** for
some functions (cmangler_getlinkname 0x4C2C70 collides with the DLL-known
pcode_traverse 0x4C2560). Since `cad.run_compiler` needs the *complete, correct*
set (incl. cmangler + the `.bss` data globals: interference graph,
used_virtual_registers, pcbasicblocks, frame lists), a partial/false port would
be worse than the DLL pcdump — which #543 proved **byte-identical to retail** for
front-end IRO. The confidently-ported addresses are recorded (not wired in) for a
future full port via a region-drift map or instruction-operand extraction.

**Use the DLL pcdump for 1.2.5n backend** (`melee-agent debug dump local`), and
`explain-virtual --ig` for coloring-node provenance.

## What it does NOT do (yet)

- Full back-end / regalloc / stack on **1.2.5n** via retrowin32 (#542, above).
