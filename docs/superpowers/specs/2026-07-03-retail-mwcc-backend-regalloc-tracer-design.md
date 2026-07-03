# Retail MWCC Backend/Register-Allocation Tracer Design

Date: 2026-07-03
Status: Design spec for user review

## Goal

Build a generic retail MWCC backend/register-allocation tracer for the Melee
decompilation repo. The tracer must inspect the unmodified retail
`mwcceppc.exe` for GC/1.2.5n through the existing `mwcc-retro` retrowin32+gdb
workflow and emit reusable backend/regalloc facts for any translation unit and
function compiled with the repo's normal MWCC flags.

The first approved implementation requires live, exact GC/1.2.5n backend and
register-allocation tracing. GC/1.1 may be used as donor evidence or a proxy
regression fixture, but it is not an acceptable substitute for the target
compiler.

## Existing Context

`mwcc-debug` already exposes rich backend and allocator data through a patched
debug DLL path. It is fast and useful, but it is not the unmodified retail
compiler.

`mwcc-retro` already runs the retail GC/1.2.5n compiler under retrowin32 with a
gdb stub. Its current production capability is frontend IRO pass tracing. The
existing docs and code explicitly leave exact 1.2.5n backend/regalloc tracing as
unfinished because an earlier address-port attempt had incomplete data globals
and false byte-correlation matches.

This project closes that gap by extending `mwcc-retro` instead of creating a
parallel tool.

## Design Decision

Use the existing `melee-agent debug retro` workflow and complete the GC/1.2.5n
backend port with confidence-gated address and struct discovery. The runtime
tracer will read retail compiler-owned state at backend and allocator stages,
emit raw event data for auditability, normalize it into versioned JSON, and
compare it against `mwcc-debug` pcdump facts.

This path is preferred because it preserves the existing retrowin32 substrate,
keeps exact retail behavior authoritative, avoids duplicating cadmic-style
compiler readers where they are still useful, and creates a stable contract for
downstream tooling.

Rejected alternatives:

- Add ad hoc in-memory binary patches that mimic the debug DLL path. This may
  expose text quickly, but it does not give enough structure or confidence for
  reusable allocator facts.
- Build a standalone retail allocator reader from scratch. This gives control
  over schema design, but duplicates too much existing debugger knowledge and
  delays the live GC/1.2.5n target.

If address or struct discovery hits a significant confidence blocker, the work
must stop and report evidence before changing strategy.

## Architecture

The implementation extends `tools/mwcc_retro` and
`tools/melee-agent/src/cli/debug/retro.py`.

Core components:

- `debug retro backend <src.c> -f <fn>`: documented entrypoint for exact retail
  GC/1.2.5n backend/regalloc tracing.
- `dump --phases backend --compiler 1.2.5n`: compatibility route that calls the
  same implementation.
- Completed `tools/mwcc_retro/tables/gc_125n.json`: backend and allocator map
  with versioned entries for functions, breakpoints, globals, struct fields,
  and confidence/provenance.
- Gdb-side tracer: runs unmodified retail `mwcceppc.exe` under retrowin32, sets
  backend/regalloc breakpoints, validates first-hit invariants, reads compiler
  data structures, and emits raw JSONL events.
- Host normalizer: converts raw events into versioned machine-readable JSON,
  pcdump-like text summaries, and compact per-function regalloc summaries.
- Verifier: compares normalized retail facts to `mwcc-debug` pcdump facts for
  the same source/function and reports fidelity differences.

Retail output is authoritative when retail and debug-DLL facts differ.

## Address And Struct Discovery

Discovery and runtime tracing are separate stages.

Discovery uses:

- String anchors and call-target disassembly for backend pass functions.
- Existing DLL-known GC/1.2.5n addresses as seeds, not as proof by themselves.
- Instruction-operand extraction for `.bss` globals such as
  `INTERFERENCEGRAPH`, `COALESCE_ALIAS`, `INTERFERENCE_MATRIX`, block lists,
  used-virtual-register sets, and frame lists.
- GC/1.1 donor addresses only when corroborated by local 1.2.5n evidence.
- Read-only probes against the retail binary and live retrowin32 sessions.

Every discovered address or field must record:

- Name.
- Address or offset.
- Owning compiler version.
- Confidence level.
- Evidence class, such as string-anchor, call-target, operand-extract,
  dll-seed-confirmed, live-invariant, or manual-disassembly-confirmed.
- Expected runtime invariant.

Required backend/regalloc fields below the confidence threshold block the
feature. The tracer must not emit partial allocator data that looks complete.

## Trace Collection

For a requested source file and function, the backend tracer will:

1. Resolve the normal repo MWCC compile command for the TU.
2. Compile under retrowin32 using retail GC/1.2.5n.
3. Verify the emulated compile is byte-identical to the normal retail path for
   the TU before trusting backend data.
4. Break at backend and allocator stages, including codegen start/end, PCode
   pass boundaries, liveness/interference/coalesce/IG construction,
   simplifygraph, colorgraph, frame/local allocation, and final scheduling.
5. Emit raw chronological events to `backend-events.v1.jsonl`.
6. Normalize events into `backend-trace.v1.json`, `backend-summary.txt`, and
   `regalloc-summary.txt`.

Backend tracing is observational. It should be read-only unless the user
explicitly supplies an intervention hook through the existing `--gdb-py`
escape hatch. The frontend IRO dump machinery may continue using its existing
in-memory toggles, but the backend tracer must not depend on write patches for
normal fact collection.

## Failure Policy

`debug retro backend` fails instead of degrading when any of these occur:

- Target function is not found in the TU.
- Retail retrowin32 compile does not produce a byte-identical object to the
  normal retail path.
- A required breakpoint resolves ambiguously or fails its first-hit invariant.
- A required struct field has invalid bounds, impossible pointer section,
  impossible register class, corrupt list shape, or inconsistent count.
- The command cannot emit complete regalloc decisions for every GPR or FPR class
  the function actually uses.
- Required allocator facts are missing from the normalized consumer schema.

Best-effort source attribution is not a hard failure. It may be `unattributed`
or `ambiguous` because downstream tools can enrich it.

## Output Files

All files are written under:

`build/mwcc_retro/<unit>/<function>/`

New or extended files:

- `backend-events.v1.jsonl`: raw chronological gdb events, producer-facing.
- `backend-trace.v1.json`: complete normalized per-function backend/regalloc
  data, including the consumer-facing allocator facts subset.
- `backend-summary.txt`: human-readable pcdump-like summary.
- `regalloc-summary.txt`: compact diff-friendly per-function allocator summary.
- `backend-fidelity.json`: machine-readable retail-vs-debug comparison.
- `backend-fidelity.txt`: human-readable retail-vs-debug comparison.
- `struct-map.v1.json`: named discovered structures and fields when not fully
  embedded in `backend-trace.v1.json`.
- `provenance.json`: compiler identity, command provenance, pins, schema
  versions, validation gates, and output status.

Every machine-readable file includes schema version, compiler identity, source
and command provenance, tool version, and enough data to reproduce or reject the
trace.

## Shared AllocatorFacts Contract

The design reserves a consumer-facing subset in `backend-trace.v1.json` for
other backend-inspection tools, especially the lifetime-pressure explorer being
designed in parallel.

Supported consumer path:

`functions[].regalloc.classes[]`

This subset is distinct from raw `backend-events.v1.jsonl`. Downstream tools
should consume the normalized subset and avoid depending on raw gdb event names,
retrowin32 implementation details, or retail struct pointer addresses.

Required shape:

```json
{
  "schema_version": "mwcc-retro-backend-trace.v1",
  "compiler": {
    "family": "MWCC",
    "version": "GC/1.2.5n",
    "retail": true
  },
  "source": {
    "tu": "src/melee/.../file.c",
    "function": "FunctionName",
    "mwcc_command_hash": "..."
  },
  "functions": [
    {
      "name": "FunctionName",
      "blocks": [
        {
          "id": "B0",
          "order": 0,
          "succ": ["B1"],
          "pred": [],
          "labels": []
        }
      ],
      "pcode": {
        "passes": [],
        "instruction_identity_note": "instruction ids are stable only within this trace"
      },
      "regalloc": {
        "classes": [
          {
            "class_id": 0,
            "class_name": "gpr",
            "registers": {
              "physical_count": 32,
              "allocatable": [],
              "nonvolatile_dispense_order": [31, 30, 29, 28, 27]
            },
            "nodes": [],
            "edges": [],
            "coalesce": {
              "mappings": []
            },
            "simplify_order": [],
            "select_order": [],
            "color_decisions": []
          }
        ]
      }
    }
  ]
}
```

Per-node fields:

- `ig_id`: compile-scoped interference graph id.
- `virtual`: register kind and number, such as `{ "kind": "r", "number": 32 }`.
- `first_def`: pass, block, instruction id, opcode, operands, and normalized
  signature.
- `source_attribution`: status, source symbol or line if available, confidence,
  and ambiguity data.
- `live`: live blocks and intervals when observed, with confidence.
- `degree`: node degree.
- `flags`: decoded allocator flags.
- `coalesce`: root id and aliases.
- `simplify_order`: position or null.
- `select_order`: position or null.
- `assigned_phys`: assigned physical register or null before coloring.
- `spill`: spilled state and reason if known.

Per-edge fields:

- `a` and `b`: compile-scoped node ids.
- `kind`: normally `interference`.
- `confidence`: observed, inferred, or unavailable.
- `provenance`: which retail structure or pass produced the edge.

Per-color-decision fields:

- `ig_id`.
- `iter`.
- `assigned_phys`.
- `candidate_phys_before_choice` when observed.
- `blocked_by`: interferers and physical registers that removed candidates.
- `decision_rule`: e.g. `lowest_available_or_nonvolatile_dispense`.
- `confidence`.

Identity caveats:

- Raw `ig_id`, virtual ids, PCode instruction ids, and runtime addresses are
  scoped to one compile.
- Cross-candidate comparison must use role descriptors or normalized anchors:
  first-def signatures, source attribution, block/instruction context, and
  symbol bridge data.
- Runtime addresses may be recorded as `runtime_address`, but they are never a
  stable identity.

Completeness gate:

- For every register class a function uses, the consumer subset must include
  nodes, edges, coalesce roots/aliases, simplify/select order, color decisions,
  assigned physicals, and spill flags.
- Missing required allocator facts fail the command.
- Source attribution may be incomplete without failing the command.

Coordination result:

- The retail tracer owns producing this subset from exact GC/1.2.5n retail
  tracing.
- The lifetime-pressure explorer owns explanation, target-vs-current analysis,
  and ranked source experiments over this subset.
- The explorer's MVP may consume `mwcc-debug` pcdumps through an adapter, then
  later consume this retail subset through a separate adapter.

## Regalloc Summary

`regalloc-summary.txt` is compact and stable enough for diffs. It contains one
line per function/class/node with:

- class name/id.
- `ig_id` and virtual register.
- normalized first-def.
- degree.
- simplify position.
- select/color position.
- assigned physical register.
- spill state.
- coalesce root.
- compact blocker/interferer physical set.

The summary avoids raw pointers and volatile event ordering that would create
diff noise.

## Verifier

The verifier compares retail normalized facts against existing `mwcc-debug`
pcdump facts for the same source/function.

CLI forms:

- `melee-agent debug retro backend <src.c> -f <fn> --verify-debug`
- `melee-agent debug retro verify-backend <src.c> -f <fn>`

Comparison categories:

- `equal`.
- `retail_only`.
- `debug_only`.
- `different`.
- `not_comparable`.

Fields compared where both tools expose them:

- Backend pass names and order.
- Block counts and block order.
- PCode instruction stream before and after major passes.
- Virtual-to-physical assignments.
- Simplify/select order.
- Coalesce aliases and roots.
- Spill flags.
- IG node counts and edge sets.
- First-def signatures.
- Stack/local offsets.
- Final scheduled/colored instruction stream.

Retail is authoritative. The verifier reports DLL differences and does not
massage retail data to match the debug DLL.

## CLI

New or extended commands:

```bash
melee-agent debug retro backend src/melee/mn/mndiagram.c \
  -f mnDiagram_UpdateScrollArrows

melee-agent debug retro backend src/melee/mn/mndiagram.c \
  -f mnDiagram_UpdateScrollArrows --verify-debug

melee-agent debug retro verify-backend src/melee/mn/mndiagram.c \
  -f mnDiagram_UpdateScrollArrows

melee-agent debug retro dump src/melee/mn/mndiagram.c \
  -f mnDiagram_UpdateScrollArrows --phases backend --compiler 1.2.5n
```

The documented entrypoint is `debug retro backend`. The `dump --phases backend`
route exists for consistency with current `mwcc-retro` command shape.

CLI help must state that GC/1.2.5n backend tracing is exact retail tracing and
that the command fails on missing required allocator facts.

## Documentation

Update:

- `docs/mwcc-retro.md`.
- `docs/mwcc-retro-usage.md`.
- `tools/mwcc_retro/README.md`.
- `.claude/skills/mwcc-retro/SKILL.md`.
- debug CLI help golden fixtures.

Add schema documentation for:

- `backend-trace.v1.json`.
- `backend-events.v1.jsonl`.
- `regalloc-summary.txt`.
- `backend-fidelity.json`.
- `struct-map.v1.json`.
- Shared `AllocatorFacts` subset.

Docs must include reproducible commands and explain how to interpret hard
failures versus fidelity differences.

## Validation

Use at least three live validation cases:

1. An already matched function in a normal Melee TU, such as
   `lbArq_80014ABC` or an equivalent current stable matched function found
   from build metadata.
2. A register-allocation-only mismatch with existing debug tooling support,
   such as `mnVibration_80248644`, `grVenom_80204284`, or another current
   high-percent regalloc residual discovered from repo metadata and source
   comments.
3. `mnDiagram_UpdateScrollArrows` as the motivating case. If the function name
   has drifted in the current tree, resolve the actual source/symbol name and
   document the mapping.

Validation checks:

- `debug retro backend` emits complete retail backend/regalloc outputs.
- `regalloc-summary.txt` has stable, non-pointer identities.
- `backend-trace.v1.json` includes complete `functions[].regalloc.classes[]`
  facts for used classes.
- `--verify-debug` emits fidelity reports.
- The trace contains enough data to explain why a virtual got one physical
  register instead of another: candidate set, blocked registers, interferers,
  simplify/select position, coalesce/spill state, and register class metadata.

## Tests

Fast tests:

- Schema serialization and validation.
- Struct-map confidence validation.
- Normalizer tests from synthetic raw events.
- Regalloc summary generation.
- Verifier diff bucketing.
- CLI argument and help tests.

Binary-backed tests:

- Address/struct-map tests against local compiler binaries when present.
- PE/string-anchor/operand-extraction tests.

Live tests:

- Env-gated retrowin32 tests for the three validation cases.
- Object byte-parity gate against the normal retail path.
- Retail-vs-debug verifier generation.

Live tests may be skipped by default, but docs must list the exact commands used
to reproduce them.

## Non-Goals

- No source experiment ranking in the retail tracer. That belongs to downstream
  explanation tools such as the lifetime-pressure explorer.
- No reliance on GC/1.1 as a target compiler.
- No silent fallback to `mwcc-debug` data for retail backend facts.
- No ad hoc source-specific or function-specific hacks.
- No hardcoded Melee module/function/register assumptions in the tracer.

## Completion Criteria

The work is complete when:

- A user can run one command with a source file and function name and get exact
  GC/1.2.5n retail backend/regalloc traces.
- `backend-trace.v1.json` and `regalloc-summary.txt` are emitted for arbitrary
  supported TUs/functions.
- Existing debug-DLL pcdump facts can be compared to retail facts through the
  verifier.
- The shared allocator facts subset is documented and stable enough for the
  lifetime-pressure explorer to target.
- The tracer provides enough allocator detail to explain physical register
  choice for a virtual register.
- The required validation commands have been run or are documented with clear
  skip reasons for env-gated live tests.
- Any tooling bugs, hangs, or missing affordances encountered during work are
  reported with `melee-agent issue report`.
