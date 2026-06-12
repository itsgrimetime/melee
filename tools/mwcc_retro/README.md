# mwcc-retro

`mwcc-retro` is a diagnosis tool that introspects the **retail** MWCC GC/1.2.5n
compiler — the exact binary this project matches against — with zero perturbation.
It runs the compiler under the [retrowin32](https://github.com/evmar/retrowin32)
x86 emulator with a gdb stub, attaches a GDB-protocol debugger, and reads
compiler-internal data structures directly from the emulated process.

The headline capability is **front-end IRO optimizer per-pass tracing**: AST
dumps and IR node snapshots after each optimizer phase (CSE, loop unrolling,
constant propagation, dead-code elimination, and others). Neither existing tool
provides this: `mwcc-debug` (the pcdump/DLL path) covers only back-end PCode;
`mwcc-inspect` gives one front-end IR snapshot on demand. In addition to the
front-end trace, on the **GC/1.1** compiler (`--compiler 1.1`) `mwcc-retro`
produces retail-faithful back-end PCode passes, register-allocator
priority/cost/adjacency dumps, and stack-allocation maps. Backend introspection
on GC/1.2.5n is a follow-on (#542); for backend on 1.2.5n use the `mwcc-debug`
DLL pcdump path.

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
# Front-end IRO trace for one function (1.2.5n; backend on 1.2.5n is follow-on #542)
melee-agent debug retro dump src/melee/mn/mndraw.c -f mnDraw_8024A3B0

# Front-end only (fast; skips backend regalloc)
melee-agent debug retro dump src/melee/gm/gm_1BA8.c -f gm_801BCC9C --phases frontend

# Backend (GC/1.1 only today)
melee-agent debug retro dump src/melee/lb/lbarq.c -f lbArq_80014ABC --phases backend --compiler 1.1

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
| `frontend-NN-ast-<pass>.txt` | AST per front-end pass | GC/1.1 backend (`--compiler 1.1`) |
| `backend-NN-<pass>.txt` | Back-end PCode per pass | GC/1.1 backend (`--compiler 1.1`) |
| `regalloc-<cls>-pass-N-all.txt` | Register-allocator priority/cost/adjacency | GC/1.1 backend (`--compiler 1.1`) |
| `regalloc-<cls>-pass-N-assigned.txt` | Final register assignments | GC/1.1 backend (`--compiler 1.1`) |
| `variables.txt` | Stack allocation map (variable home assignments) | GC/1.1 backend (`--compiler 1.1`) |
| `launch.log` | Emulator stdout/stderr for this run | Both |
| `provenance.json` | Compiler identity, pinned SHAs, fidelity-gate result | Both |

### Verify

```bash
melee-agent debug retro verify
```

Cross-checks the emulated retail compile against the normal wibo build by
**byte-comparing the produced `.o`** for a control TU. If they are
byte-identical, the emulator is a faithful oracle and its dumps can be trusted.
(The vreg-map / regalloc-count / LOOPWEIGHT cross-checks from the design depend
on the GC/1.2.5n backend port and are a #542 follow-on.)

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
