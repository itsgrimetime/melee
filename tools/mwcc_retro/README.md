# mwcc-retro

`mwcc-retro` is a diagnosis tool that introspects the **retail** MWCC GC/1.2.5n
compiler — the exact binary this project matches against — with zero perturbation.
It runs the compiler under the [retrowin32](https://github.com/evmar/retrowin32)
x86 emulator with a gdb stub, attaches a GDB-protocol debugger, and reads
compiler-internal data structures directly from the emulated process.

The headline capabilities are **front-end IRO optimizer per-pass tracing** and
**exact retail GC/1.2.5n backend/regalloc tracing**. The front-end path records
AST dumps and IR node snapshots after each optimizer phase (CSE, loop unrolling,
constant propagation, dead-code elimination, and others). Neither existing tool
provides that per-pass front-end view: `mwcc-debug` (the pcdump/DLL path) covers
only back-end PCode; `mwcc-inspect` gives one front-end IR snapshot on demand.
For backend work, `debug retro backend` runs the unmodified retail GC/1.2.5n
compiler and emits machine-readable PCode, frame, interference-graph, coalesce,
simplify/select, color, and register-assignment facts. On the **GC/1.1**
compiler (`--compiler 1.1`), `mwcc-retro` also produces retail-faithful back-end
PCode passes, register-allocator priority/cost/adjacency dumps, and
stack-allocation maps. Lower-level map, interference-graph, PCode, and
candidate probes remain available for GC/1.2.5n diagnostics.

## Commands

### Setup

```bash
melee-agent debug retro setup
```

Clones and builds the vendored retrowin32 (encounter/retrowin32, gdb-stub
branch) and the cadmic/mwcc-debugger library at their pinned SHAs into
`vendor/` (gitignored). Also runs the P0 fidelity gate: it compiles a
control translation unit once through the emulator and once through the normal
wibo path, then byte-checks the resulting `.o` files. If they match, retro
dumps can be trusted for that compiler version. Setup refuses to proceed past
the fidelity gate on a mismatch.

Run once per machine, and again whenever vendor SHAs are updated.

### Dump

```bash
melee-agent debug retro dump <src.c> -f <FUNCTION> [--phases all|frontend|backend] [--compiler 1.2.5n|1.1]
```

Compiles `<src.c>` under the emulated retail compiler and writes dumps for
the requested phase group. Examples:

```bash
# Front-end IRO trace for one function (1.2.5n)
melee-agent debug retro dump src/melee/mn/mndraw.c -f mnDraw_8024A3B0

# Front-end only (fast; skips backend regalloc)
melee-agent debug retro dump src/melee/gm/gm_1BA8.c -f gm_801BCC9C --phases frontend

# Backend through the GC/1.1 donor/reference route
melee-agent debug retro dump src/melee/lb/lbarq.c -f lbArq_80014ABC --phases backend --compiler 1.1

# Exact retail GC/1.2.5n backend/regalloc trace
melee-agent debug retro backend src/melee/lb/lb_00B0.c -f lb_8000CE30

# Exact retail trace plus retail-vs-debug-DLL fidelity report
melee-agent debug retro backend src/melee/lb/lb_00B0.c -f lb_8000CE30 --verify-debug

# GC/1.2.5n backend map evidence probe (no trace output)
melee-agent debug retro probe-backend-map src/melee/lb/lbarq.c -f lbArq_80014ABC

# GC/1.2.5n partial retail IG/order/coalesce/color snapshot
melee-agent debug retro probe-backend-ig src/melee/lb/lbarq.c -f lbArq_80014ABC

# GC/1.2.5n partial retail PCode/block snapshot (block/pcode only)
melee-agent debug retro probe-backend-pcode src/melee/lb/lbarq.c -f lbArq_80014ABC

# GC/1.2.5n candidate backend trace assembled from validated partial probes
melee-agent debug retro backend-candidate src/melee/lb/lb_00B0.c -f lb_8000CE30

# One-pass candidate diagnostic hook; still writes only candidate outputs
melee-agent debug retro backend-candidate src/melee/lb/lb_00B0.c -f lb_8000CE30 --one-pass

# Proof-bearing v2 request (currently strict-abstains; see below)
melee-agent debug retro backend-candidate src/melee/lb/lb_00B0.c -f lb_8000CE30 \
  --one-pass --trace-version v2

# Compare a full or candidate backend trace with an existing mwcc-debug pcdump
melee-agent debug retro verify-backend src/melee/lb/lb_00B0.c -f lb_8000CE30 --debug-pcdump pcdump.txt

# Use the GC/1.1 compiler descriptor instead
melee-agent debug retro dump src/melee/ft/ftco.c -f ftCo_8009C744 --compiler 1.1
```

**Exit codes:** 0 = all requested phases produced; 2 = compiler crashed or
hung under emulation; 3 = function not found in the dump; 4 = partial output
(some phases missing); 5 = safety invariant fired (see `provenance.json` for
the triggered rule).

Output goes to `build/mwcc_retro/<unit>/<fn>/`:

| File | Contents | When produced |
|------|----------|---------------|
| `iro-trace.txt` | All IRO optimizer passes concatenated | Frontend (both compilers) |
| `iro-NN-<phase>.txt` | One file per optimizer pass (split from trace) | Frontend (both compilers) |
| `iro-summary.txt` | Pass-iteration-aware node ledger | Frontend (both compilers) |
| `backend-events.v1.jsonl` | Raw retail backend/regalloc events | GC/1.2.5n backend (`debug retro backend`) |
| `backend-onepass-summary.json` | Hook completeness summary and warnings | GC/1.2.5n backend (`debug retro backend`) |
| `backend-trace.v1.json` | Stable PCode, frame, and allocator facts | GC/1.2.5n backend (`debug retro backend`) |
| `backend-trace.candidate.v1.json` | Existing diagnostic candidate contract | `backend-candidate` (default `--trace-version v1`) |
| `backend-trace.v2.json` | Complete proof-bearing object/PCode lineage trace | `backend-candidate --one-pass --trace-version v2`, only after every trust gate passes |
| `candidate-object.o` | Immutable raw ELF32/PowerPC candidate bound by the v2 capture identity | Published atomically with a validated v2 trace |
| `regalloc-summary.txt` | Compact allocator summary for diffs | GC/1.2.5n backend (`debug retro backend`) |
| `backend-summary.txt` | Human-readable backend/PCode/frame summary | GC/1.2.5n backend (`debug retro backend`) |
| `backend-fidelity.json` / `backend-fidelity.txt` | Retail-vs-mwcc-debug comparison | `verify-backend`, `backend --verify-debug` |
| `frontend-NN-ast-<pass>.txt` | AST per front-end pass | GC/1.1 backend (`--compiler 1.1`) |
| `backend-NN-<pass>.txt` | Back-end PCode per pass | GC/1.1 backend (`--compiler 1.1`) |
| `regalloc-<cls>-pass-N-all.txt` | Register-allocator priority/cost/adjacency | GC/1.1 backend (`--compiler 1.1`) |
| `regalloc-<cls>-pass-N-assigned.txt` | Final register assignments | GC/1.1 backend (`--compiler 1.1`) |
| `variables.txt` | Stack allocation map (variable home assignments) | GC/1.1 backend (`--compiler 1.1`) |
| `launch.log` | Emulator stdout/stderr for this run | Both |
| `provenance.json` | Compiler identity, pinned SHAs, fidelity-gate result | Both |

### Backend Trace v2 Trust Boundary

`backend-candidate` defaults to the byte-for-byte compatible v1 diagnostic
workflow. The explicit v2 form is:

```bash
melee-agent debug retro backend-candidate <src.c> -f <FUNCTION> \
  --one-pass --trace-version v2 [-O OUT]
```

`--one-pass` is mandatory because runtime pointers, allocation generations,
PCode virtuals, object owners, and sidecar identities may be joined only inside
one serialized compiler process. The retrowin32 launcher already serializes
its fixed gdb port; v2 does not merge evidence from separate processes or from
patched-DLL pcdumps. Object and PCode sidecars must both have
`publication_complete: true`, the exact same 128-bit capture-attempt ID, and an
identity that names the requested function. Their producer `status` values are
diagnostic only and never grant a capability.

A successful v2 assembly finalizes `capture_identity` only after the raw
candidate-object bytes and compiler/source/command/environment/function pins
are available. It embeds the complete lifetime proof, recomputes the RFC 8785
proof digest, requires the exact independently promoted GC/1.2.5n registry and
installed-hook tuple, and then independently runs the object-binding and PCode
lineage validators. The artifact declares only capabilities those validators
actually return. In particular, the current object validator deliberately
withholds `object-to-virtual` without exhaustive IG inventory/cap evidence and
withholds `object-to-frame` without the promoted layout plus final
PCode/assembly gate.

The installed registry is presently empty and
`backend_reader.pcode_instrumentation.validated` is false because exhaustive
proof promotion is blocked by issues #1239 and #1240. Therefore the real v2
command exits 2 before running a capture or replacing any artifact. It does not
trust Task 7's diagnostic `status: complete`, synthesize a proof, write a
partial `backend-trace.v2.json`, or replace an existing trace/candidate pair.
The generic assembler is exercised with synthetic trusted test fixtures only.
When promotion is eventually available, a valid pair is written as
`backend-trace.v2.json` plus immutable, atomically published
`candidate-object.o`; a different existing candidate is never overwritten.

Phase 1 reserves source fields but requires `source_bindings: []` and
`source_capture: null`. It never emits `object-to-source`, never joins remote
inspector pointers to retail pointers, and ends at
`source-object-binding-missing` whenever a causal verdict requires source
ownership.

### Backend Map Probe

```bash
melee-agent debug retro probe-backend-map <src.c> -f <FUNCTION> [-O OUT]
```

This command is a GC/1.2.5n reverse-engineering aid for the backend tracer
confidence gate. It writes `backend-map-candidates.json` with every required
backend map key, static PE evidence, and whether that entry still needs a live
invariant. Without `--static-only`, it first runs the normal raw object
byte-parity gate, then attaches the retail compiler under retrowin32+gdb and
writes `backend-map-probe.json` with the backend stage hits observed while the
requested function compiles. It also writes `backend-map-evidence.json`, a
normalized classifier output that separates live-invariant promotable facts from
blocked facts with reasons.

`probe-backend-map` intentionally does **not** emit `backend-events.v1.jsonl`,
`backend-trace.v1.json`, or summaries. It is for validating the retail
GC/1.2.5n address/struct map before the full backend/regalloc trace path is
allowed to consume it.

### Backend IG Snapshot Probe

```bash
melee-agent debug retro probe-backend-ig <src.c> -f <FUNCTION> [-O OUT]
```

Captures the retail GC/1.2.5n interference graph, coalesced-alias mappings,
post-`colorgraph` order, and observed assignment/blocker rows as partial
backend facts:

- `backend-ig-snapshot.json`: requested-function match status, functions seen,
  captured register classes, and hook errors.
- `backend-ig-snapshot-events.v1.jsonl`: `function_start`, `backend_marker`,
  `regclass`, `node`, `edge`, `coalesce_mapping`, `coalesce_mapping_empty`,
  `simplify_order`, `select_order`, and optional `color_decision` events.
- `backend-colorgraph-trace.json`: sidecar status for exact internal
  `colorgraph` decision breakpoints.
- `backend-colorgraph-decisions.v1.jsonl`: sidecar `function_start` plus
  exact internal `color_decision` rows when the requested function exercises
  retail `colorgraph` selection.

This command intentionally does not write `backend-trace.v1.json`,
`regalloc-summary.txt`, or `backend-summary.txt`, and it does not claim full
allocator replay. The `backend-colorgraph-*` sidecar is validated and useful
for allocator-choice evidence; use `debug retro backend` when you need those
facts normalized with PCode and frame state into the full trace schema.

### Backend PCode Snapshot Probe

```bash
melee-agent debug retro probe-backend-pcode <src.c> -f <FUNCTION> [-O OUT]
```

Captures a retail GC/1.2.5n PCode/block snapshot at a proven backend PCode
stage and writes partial backend facts:

- `backend-pcode-snapshot.json`: requested-function match status, functions
  seen, captured pass counts, and hook errors.
- `backend-pcode-snapshot-events.v1.jsonl`: `function_start`,
  `backend_marker`, `block`, and `pcode_instruction` events.

This command intentionally does not write `backend-trace.v1.json`,
`regalloc-summary.txt`, or `backend-summary.txt`. It avoids the ambiguous
PCodeBlock line/loop-weight region and does not claim allocator decisions.

### Verify

```bash
melee-agent debug retro verify
```

Cross-checks the emulated retail compile against the normal wibo build by
**byte-comparing the produced `.o`** for a control TU. If they are
byte-identical, the emulator is a faithful oracle and its dumps can be trusted.
Use `debug retro verify-backend` or `debug retro backend --verify-debug` for
retail backend/regalloc comparison against mwcc-debug pcdump facts.

Use `verify` when you suspect the emulated path has drifted from retail, or
after a vendor SHA update.

## Vendor, Pinning, and Licensing

`mwcc-retro` is built on two upstream components:

- **cadmic/mwcc-debugger** ([https://github.com/cadmic/mwcc-debugger](https://github.com/cadmic/mwcc-debugger)):
  provides the GDB-protocol struct readers for MWCC's internal tables (uniform
  across GC/1.0–1.2.5). This repository has no license file, so `setup`
  clones it by SHA into `vendor/` (gitignored) and imports it as a library.
  It is never committed into this repo.

- **encounter/retrowin32** (gdb-stub branch): the x86 Windows emulator that
  runs the retail `.exe` and exposes a GDB remote-stub interface. Pinned by
  SHA; cloned into `vendor/` by `setup`.

Both SHAs are recorded in `tools/mwcc_retro/versions.py`. The gitignore
entry `vendor/` prevents accidental commits.

## Name-Spoof and Provenance

The retail GC/1.2.5n compiler internally reports its descriptor as `"GC/1.1"`.
The cadmic struct readers were written against the uniform GC/1.0–1.2.5 ABI
and use the descriptor for table disambiguation, so `mwcc-retro` lets the
spoof pass through to the reader. `provenance.json` records the **true**
compiler identity (`GC/1.2.5n`, from the binary version table), so dumps are
never mislabeled when stored or compared.

## Fidelity Gate (P0)

The P0 fidelity gate is a byte-parity check run by `setup`: `mwcc-retro`
compiles the designated control TU through both the emulated retail path and
the standard wibo path, then compares the resulting `.o` files. A match means
the emulator is producing retail-identical codegen and the struct dumps can be
trusted. Setup refuses to mark itself complete on a mismatch.

## Positioning

`mwcc-retro` is **diagnosis-grade**. The emulated compile is slower than the
wibo/DLL path — reach for it after the lighter tools (`mismatch-db`, `opseq`,
`ghidra`, `discord-knowledge`, and `mwcc-debug`) have been exhausted.

The primary reason to use it is **front-end pass visibility**: if a function
differs after instruction selection (not just register coloring), the IRO
trace will show which optimizer pass changed the IR shape. It is also the
right tool when you need to confirm whether a specific mismatch is a
debug-DLL artifact (the patched DLL is known to diverge in at least one
register-coloring case) or genuine retail behavior.

## See also

- Workflow doc: [docs/mwcc-retro.md](../../docs/mwcc-retro.md)
- Skill: [.claude/skills/mwcc-retro/SKILL.md](../../.claude/skills/mwcc-retro/SKILL.md)
- Spec: [docs/superpowers/specs/2026-06-10-mwcc-retro-debugger-design.md](../../docs/superpowers/specs/2026-06-10-mwcc-retro-debugger-design.md)
- Plan: [docs/superpowers/plans/2026-06-10-mwcc-retro-debugger.md](../../docs/superpowers/plans/2026-06-10-mwcc-retro-debugger.md)
