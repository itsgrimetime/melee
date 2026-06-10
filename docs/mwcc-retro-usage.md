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
stop using this tool and switch to `mwcc-debug` / coalesce-search. That's a real,
useful conclusion, not a failure.

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

## What it does NOT do (yet)

- Back-end / regalloc / stack on **1.2.5n** via retrowin32 (#542 — use DLL pcdump today).
- Per-phase dumps in the fast DLL pcdump path (#543).
- A creation-**order** temp ledger for ig_idx investigation (#544).
- State-mutation / "intervene at stage k" CLI beyond the dump (#545).
