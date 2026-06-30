# mwcc-debug force-remat diagnostic override

**Date:** 2026-06-12. **Status:** implementation plan for issue #579.

## Problem

Door-A allocator work found a repeatable A1 "constant-rider" class: two locals
seeded from the same literal sometimes lower as `li` plus copy (`mr`/`addi
...,0`) and sometimes remain two independent `li` instructions. Existing
`mwcc-debug` controls can force physical registers, coalescing, interference
edges, and scheduling, but none of them can probe the late rematerialization
choice that happens after coloring.

The requested diagnostic is not a source-generation feature. It should answer:
"if this IG node uses the alternate rematerialization operand path, does the
backend reach the target shape?"

## Design

Add a diagnostic-only hook at compiler VA `0x4CE1A0`, the post-coloring routine
that applies `IGNode.assignedReg` values to PCode operands/rematerialization
records. Its observed prologue is:

```text
53                       push ebx
56                       push esi
8b 35 74 7c 58 00        mov esi, [0x587c74]
57                       push edi
```

The trampoline copies the first 8 bytes and resumes at `push edi`, matching the
existing whole-instruction hook style.

Expose:

```text
MWCC_DEBUG_FORCE_REMAT="class:ig=copy[,class:ig=literal...]"
MWCC_DEBUG_FORCE_REMAT_FUNCTION="mnDiagram_80242C0C"
```

CLI spelling:

```text
melee-agent debug dump local src/melee/mn/mndiagram.c \
  --force-remat 0:62=copy --force-remat-fn mnDiagram_80242C0C
```

`copy` sets IGNode flag bit `0x10`; `literal` clears it. The disassembly shows
the hooked routine writing `assignedReg` into offset `0x26` when this bit is set
and `0x24` otherwise, so the bit is the narrowest available lever for probing
the late rematerialization alternate-operand path without mutating PCode payloads
or growing allocator structures. The name is deliberately conservative: it is an
observed alternate operand-slot selector, not a recovered MWCC source symbol.

The hook logs one line per reached node:

```text
[FORCE_REMAT] fn=... class=0 ig_idx=62 mode=copy flags 0x00 -> 0x10
```

Scope mismatches and parse capacity errors also log, following the existing
force-phys/coalesce/interfere style.

Rules that cannot affect code also log: out-of-range indices, physical-register
nodes, null IG slots, slot/index mismatches, spilled nodes, and nodes without a
rematerialization record are all reported as skipped.

## Non-Goals

- Do not synthesize new PCode or rewrite operand payloads directly.
- Do not grow `INTERFERENCEGRAPH` or any `IGNode` arrays.
- Do not claim the forced output is source-reachable; it is hypothesis evidence
  only.

## Acceptance

- The DLL parser and pure helper can parse and apply copy/literal rules against
  a fake IG array.
- `debug dump local` passes `MWCC_DEBUG_FORCE_REMAT` and
  `MWCC_DEBUG_FORCE_REMAT_FUNCTION` to the child compiler process, marks the run
  diagnostic-only, and skips baseline cache sync.
- `debug dump remote` forwards the same env vars through cmd.exe quoting and
  writes default forced output to managed scratch instead of the canonical cache.
- `debug dump local --help` documents the diagnostic and warns that it is not a
  production build path.
- The patched DLL builds successfully.

## Risks

- The `0x10` flag name is inferred from disassembly, not a recovered MWCC
  source name. Keep the code comment conservative: "alternate remat operand"
  rather than overclaiming "copy".
- If the hook point applies to non-rematerialized nodes, rules should skip null
  nodes and out-of-range indices and only touch explicitly requested nodes.
- Function scoping is mandatory in practice for multi-function TUs; the CLI
  mirrors the force-phys guard.
