# mwcc-retro: usage & output interpretation

A practical field guide for `melee-agent debug retro`. Companion to the workflow
doc (`docs/mwcc-retro.md`) and spec (`docs/superpowers/specs/2026-06-10-mwcc-retro-debugger-design.md`).

## TL;DR — when to reach for it

Reach for mwcc-retro when you need the **real retail GC/1.2.5n compiler** with
zero perturbation: either front-end IRO optimizer pass visibility or exact
backend/regalloc facts. For front-end work it shows what the optimizer did to
your C — loop unrolling, CSE, copy/constant propagation, induction-variable
rewrites, temp creation — after each pass.

It is **diagnosis-grade, not first-resort**. Try `mismatch-db`, `opseq`, `ghidra`,
`discord-knowledge`, and `mwcc-debug` (DLL pcdump) first. Emulated compiles are
slower than the wibo path; this is for understanding a mismatch, not inner-loop search.

**Scope boundary (important):** the frontend dump helps **front-end-shaped**
mismatches (the IR the compiler builds differs between your source and the
target). For **register-coloring last-mile ceilings** (r30-vs-r27 tiebreaks,
spill order), use `debug retro backend` for exact retail GC/1.2.5n allocator
facts, then compare or iterate with the faster `mwcc-debug` DLL pcdump path.

## Commands

```bash
# One-time: clone + build the vendored retrowin32 + cadmic at pinned SHAs
melee-agent debug retro setup

# Front-end IRO per-phase trace on retail 1.2.5n, scoped to one function
melee-agent debug retro dump src/melee/mn/mnvibration.c -f mnVibration_802474C4 --phases frontend

# Backend (AST + per-pass PCode + regalloc + stack) — GC/1.1 donor/reference path
melee-agent debug retro dump src/melee/lb/lbarq.c -f lbArq_80014ABC --phases backend --compiler 1.1

# Exact retail GC/1.2.5n backend/regalloc trace
melee-agent debug retro backend src/melee/lb/lb_00B0.c -f lb_8000CE30

# Exact retail trace plus retail-vs-debug-DLL fidelity report
melee-agent debug retro backend src/melee/lb/lb_00B0.c -f lb_8000CE30 --verify-debug

# GC/1.2.5n backend map evidence probe; writes candidates/probe JSON, not a trace
melee-agent debug retro probe-backend-map src/melee/lb/lbarq.c -f lbArq_80014ABC

# GC/1.2.5n partial retail interference graph snapshot
melee-agent debug retro probe-backend-ig src/melee/lb/lbarq.c -f lbArq_80014ABC

# GC/1.2.5n candidate backend trace assembled from partial map/PCode/IG/colorgraph probes
melee-agent debug retro backend-candidate src/melee/lb/lb_00B0.c -f lb_8000CE30

# Fidelity gate: is the emulator byte-faithful for this TU?
melee-agent debug retro verify --unit src/melee/mn/mnvibration.c
```

Notes:
- `-f/--function` takes the **C function name** (e.g. `mnVibration_802474C4`), not a
  mangled symbol. It scopes the dump to that one function.
- Default is `--phases all --compiler 1.2.5n`, which delivers the **frontend** trace
  through `dump`; use `debug retro backend` for the exact retail 1.2.5n backend trace.
- `probe-backend-map` validates GC/1.2.5n backend map candidates. It does not emit
  backend trace files and is not a replacement for `mwcc-debug`.
- `probe-backend-ig` emits partial retail IG/order/coalesce/color facts (`regclass`,
  `node`, `edge`, `coalesce_mapping`, `coalesce_mapping_empty`,
  `simplify_order`, `select_order`, optional `color_decision`) for GC/1.2.5n.
  It is not the full backend trace.
- `backend-candidate` runs the map, PCode, IG, and colorgraph probes in separate
  retail compiles and assembles `backend-trace.candidate.v1.json` plus compact
  summaries. It remains useful for diagnostics and schema fixture work; prefer
  `debug retro backend` for normal full-trace use.
- `backend-candidate --one-pass` uses an experimental single-compile hook that
  writes one `backend-events.v1.jsonl` before normalizing the same candidate-only
  JSON and summaries.
- `verify-backend` prefers `backend-trace.v1.json` and falls back to
  `backend-trace.candidate.v1.json` in the selected output directory when the
  full trace is absent. Pass `--trace` to compare a specific file.
- Output lands in `build/mwcc_retro/<unit>/<fn>/` (gitignored).

## Output files

| File | Phase | What it is |
|---|---|---|
| `iro-trace.txt` | frontend | Raw retail IRO dump stream for the target fn (the full thing) |
| `iro-NN-<phase>.txt` | frontend | The flowgraph/IR after each front-end pass, split out, in order |
| `iro-summary.txt` | frontend | Per-phase **node ledger** — which IR node indices appear/disappear per pass |
| `backend-events.v1.jsonl` | backend (1.2.5n) | Raw retail backend/regalloc event stream for the requested function |
| `backend-onepass-summary.json` | backend (1.2.5n) | Hook completeness summary and warnings for full trace assembly |
| `backend-trace.v1.json` | backend (1.2.5n) | Stable machine-readable PCode, frame, and allocator facts |
| `regalloc-summary.txt` | backend (1.2.5n) | Compact per-function allocator summary for diffs |
| `backend-summary.txt` | backend (1.2.5n) | Human-readable backend/PCode/frame summary |
| `backend-fidelity.json` / `backend-fidelity.txt` | backend verify | Retail-vs-mwcc-debug comparison report |
| `frontend-NN-ast-<pass>.txt` | backend (1.1) | AST: initial / after-optimizations / final |
| `backend-NN-<pass>.txt` | backend (1.1) | PCode after each back-end pass (CSE, copy-prop, scheduling, regalloc, peephole…) |
| `regalloc-<cls>-pass-N-{all,assigned}.txt` | backend (1.1) | Chaitin allocator: nodes in priority order, cost, adjusted cost, neighbors |
| `variables.txt` | backend (1.1) | Stack allocation map (r1+offset ranges) for args/locals/temps/spills |
| `backend-ig-snapshot.json` | backend IG probe | Partial retail GC/1.2.5n IG/order/coalesce/color snapshot status |
| `backend-ig-snapshot-events.v1.jsonl` | backend IG probe | Partial `regclass`/`node`/`edge`/coalesce/order/color event stream |
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
- Note: this is GC/1.1 (a proxy for the 1.0-1.2.5 family). For exact 1.2.5n
  back-end behavior, use `debug retro backend`; use `mwcc-debug` when you need
  the faster DLL pcdump path.

## GC/1.2.5n backend map probe

`probe-backend-map` is a bring-up command for the exact retail backend tracer:

```bash
melee-agent debug retro probe-backend-map src/melee/lb/lbarq.c -f lbArq_80014ABC
```

It writes `backend-map-candidates.json` with static PE evidence for every
required backend key, then, unless `--static-only` is passed, runs the raw object
byte-parity gate and a live retrowin32+gdb probe. The live output
(`backend-map-probe.json`) records function scoping, backend stage hit counts,
sampled globals, frame-list state, PCode block rows, and sampled
interference-graph rows. `backend-map-evidence.json` classifies those samples
into `live-invariant` promotable entries and blocked entries with reasons.

It deliberately does not write `backend-events.v1.jsonl` or
`backend-trace.v1.json`; use `debug retro backend` for the full trace. Use at
least one GPR-allocating function and one FPR-allocating function when
validating class-specific globals such as `used_vreg_gpr` and `used_vreg_fpr`.

## GC/1.2.5n backend IG snapshot probe

```bash
melee-agent debug retro probe-backend-ig src/melee/lb/lbarq.c -f lbArq_80014ABC
```

This command runs the raw object-byte parity gate, then captures the retail
interference graph, colorgraph-head order, coalesced-alias facts, and observed
post-`colorgraph` assignments for the requested function. It writes:

- `backend-ig-snapshot.json`: hook status, functions seen, classes captured, and
  errors.
- `backend-ig-snapshot-events.v1.jsonl`: partial backend events for
  `function_start`, `backend_marker`, `regclass`, `node`, `edge`,
  `coalesce_mapping`, `coalesce_mapping_empty`, `simplify_order`,
  `select_order`, and optional `color_decision`.
- `backend-colorgraph-trace.json`: sidecar status for exact internal
  `colorgraph` decision breakpoints.
- `backend-colorgraph-decisions.v1.jsonl`: sidecar exact internal
  `color_decision` rows when the function exercises retail color selection.

It does not write `backend-trace.v1.json`, `regalloc-summary.txt`, or
`backend-summary.txt`; use `debug retro backend` when you need allocator replay,
PCode, and frame maps in one normalized trace. Color decisions in
`backend-ig-snapshot-events.v1.jsonl` are observed post-return assignments and
blocker rows, not a replay of candidate filtering or tie rules. Exact
in-colorgraph decisions live in the `backend-colorgraph-*` sidecar for probe
diagnostics and are normalized by the full backend command.

## GC/1.2.5n backend PCode snapshot probe

```bash
melee-agent debug retro probe-backend-pcode src/melee/lb/lbarq.c -f lbArq_80014ABC
```

This command runs the raw object-byte parity gate, then captures a retail
PCode/block snapshot for the requested function. It writes:

- `backend-pcode-snapshot.json`: hook status, functions seen, captured pass
  counts, and errors.
- `backend-pcode-snapshot-events.v1.jsonl`: partial backend events for
  `function_start`, `backend_marker`, `block`, and `pcode_instruction`.

It does not write `backend-trace.v1.json`, `regalloc-summary.txt`, or
`backend-summary.txt`; use `debug retro backend` when you need allocator
classes, color decisions, coalescing, simplify/select order, scheduler output,
and frame maps together.

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

### Don't guess — check the counterfactual: `debug inspect tiebreak`

Before pouring C edits (or thousands of permuter iterations) into a coloring
tiebreak, *verify computationally* that the change you have in mind actually
flips the register. `tiebreak` reimplements MWCC's SELECT phase from the
COLORGRAPH interference graph — validated at **G1 = 100%** (predict each node's
register given the observed select order) on every non-truncated function and on
the InputProc forcing case — and runs what-ifs:

```bash
# Is the surrogate trustworthy for this function? (100% or it abstains)
melee-agent debug inspect tiebreak -f mnDiagram_InputProc --pcdump /tmp/d.txt --validate-only
# Report two nodes (observed vs predicted reg, degree):
melee-agent debug inspect tiebreak -f mnDiagram_InputProc --pcdump /tmp/d.txt --ig 88,90
# WHAT-IF: would equalizing the interference flip ig90? (add the count edge)
melee-agent debug inspect tiebreak -f mnDiagram_InputProc --pcdump /tmp/d.txt --what-if "add-interferer 90:72"
# or drop the asymmetric edge on ig88:
melee-agent debug inspect tiebreak -f mnDiagram_InputProc --pcdump /tmp/d.txt --what-if "remove-edge 88:72"
# or test a select-order move:
melee-agent debug inspect tiebreak -f FN --pcdump /tmp/d.txt --what-if "move 90:before:88"
```

It prints `predicted rX -> rY (FLIPS|no change)`. A FLIP means the edit is worth
making in C; "no change" means the mechanism is subtler and the planned edit
would waste effort. The engine **abstains (exit 3)** when the function's G1 isn't
100% (interferer lists are capped at 64 entries; heavy truncation corrupts the
dispense), so it never hands you an untrustworthy answer. Derive `--what-if`
targets from the **exact source variant you're matching** (re-dump it; ig_idx
identities and current assignments differ across variants).

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

## Back-end on 1.2.5n via retrowin32

Exact retail GC/1.2.5n backend/regalloc tracing is available through the
dedicated backend command:

```bash
melee-agent debug retro backend src/melee/mn/mndiagram2.c \
    -f mnDiagram2_UpdateScrollArrows \
    -O build/mwcc_retro/mnDiagram2_UpdateScrollArrows
```

The compatibility route also uses the same tracer for backend-only requests:

```bash
melee-agent debug retro dump src/melee/mn/mndiagram2.c \
    -f mnDiagram2_UpdateScrollArrows --phases backend --compiler 1.2.5n
```

The tracer keeps the older map/PCode/IG probes as diagnostic tools, but the
public `backend` output is `backend-trace.v1.json`, `regalloc-summary.txt`, and
`backend-summary.txt`. Use `--verify-debug` when you want a retail-vs-DLL pcdump
comparison; retail remains authoritative when the two differ.

## What it does NOT do (yet)

- Treat CR/LR/CTR/condition-code state as allocator classes in the v1
  `AllocatorFacts` subset; GPR/FPR are the modeled classes.
