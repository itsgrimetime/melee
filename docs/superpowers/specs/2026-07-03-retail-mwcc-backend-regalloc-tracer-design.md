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

`mwcc-retro` already runs retail MWCC under retrowin32 with a gdb stub. Its
current production capabilities are:

- Frontend IRO pass tracing for retail GC/1.2.5n.
- Backend PCode/regalloc/stack dumps for GC/1.1 through the existing
  cadmic-style backend reader (`debug retro dump --phases backend --compiler
  1.1`).

The unfinished gap is exact retail GC/1.2.5n backend/regalloc tracing. The GC/1.1
backend path is useful as a donor, regression fixture, and shape reference, but
not as a substitute target. Implementation should reuse the existing GC/1.1
backend reader and normalizer shapes where they apply instead of treating all
backend tracing as greenfield.

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

## Function Identity And Selection

`-f <fn>` names the desired source/compiler function, not a runtime address or
encounter-order slot. The command resolves it before and during tracing using a
canonical identity record:

- `requested`: the exact user argument.
- `canonical_name`: the compiler/source function name used for matching trace
  records.
- `symbol_name`: symbol-table name when available.
- `source_name`: C source spelling when available.
- `aliases`: accepted alternates, including `fn_` symbols, static/source-local
  spellings, and known map/report aliases.
- `source_file`: repo-relative TU path.

Resolution may consult build report metadata, symbols, source parsing, and the
compiler's current-function object/link name. Runtime addresses may be recorded
as observations, but they must not be used as the stable identity.

The tracer may observe many functions in a TU. It must emit the requested
function's normalized record only when a seen compiler function matches the
canonical identity or one of its aliases. If the requested function is not found,
the command exits with the not-found code and writes a diagnostic listing the
requested name, attempted aliases, and nearby or same-TU function names seen
during the compile. That diagnostic must not rely on encounter order alone.

## Object Parity Gate

The v1 trust gate is raw object-byte parity. The tool compiles the same TU with
the same MWCC arguments through:

- the normal repo retail path, with output redirected to a temporary reference
  object; and
- retrowin32 retail GC/1.2.5n, with output redirected to a temporary retro
  object.

The comparator drops dependency-file side effects such as `-MMD` when necessary
and keeps the compile working directory and command flags otherwise equivalent.
The two produced `.o` files are expected to be deterministic byte-for-byte, based
on the existing `mwcc-retro` P0 evidence. The diagnostic records both object
paths, sizes, and cryptographic hashes.

If raw object bytes differ, `debug retro backend` fails before trusting backend
state. The tool must not silently fall back to a weaker comparator. If future
evidence proves benign non-code metadata drift, a normalized parity gate over
section bytes, relocations, and symbol-critical metadata must be designed and
documented before this hard gate is relaxed.

## Failure Policy

`debug retro backend` fails instead of degrading when any of these occur:

- Target function is not found in the TU.
- Retail retrowin32 compile does not produce a byte-identical object to the
  normal retail path.
- A required breakpoint resolves ambiguously or fails its first-hit invariant.
- A required struct field has invalid bounds, impossible pointer section,
  impossible register class, corrupt list shape, or inconsistent count.
- The command cannot emit complete regalloc decisions for every v1 allocator
  class the function actually uses.
- Required allocator facts are missing from the normalized consumer schema.

Best-effort source attribution is not a hard failure. It may be `unattributed`
or `ambiguous` because downstream tools can enrich it.

V1 allocator classes are GPR and FPR. CR, LR, CTR, condition-code, and other
special backend machinery may be represented in PCode or a
`non_allocatable_state` model-boundary section, but they are outside the v1
`AllocatorFacts` completeness gate.

## Output Files

All files are written under:

`build/mwcc_retro/<unit>/<function>/`

`<unit>` is a path-safe encoding of the repo-relative source path plus a short
hash of that repo-relative path or MWCC command. `<function>` is a path-safe
canonical compiler function name plus a short hash when needed to avoid
collisions. The display source path and display function name are recorded in
`provenance.json` and `backend-trace.v1.json`. Duplicate filenames, static
functions, unusual characters, and aliases must not collide on disk.

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
            "non_allocatable_state": {
              "status": "model-boundary",
              "notes": []
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
- `node_state_before_select`: whether the node was precolored, coalesced,
  spill-marked, rematerialized, or otherwise special before selection.
- `reserved_or_precolored_filtered`: physical registers removed before normal
  candidate selection because they are reserved, fixed, precolored, or
  unavailable for the class.
- `available_phys_ordered`: ordered candidate physical registers after reserved
  and precolored filtering, before interference blocking.
- `blocked_candidates`: one entry per candidate removed by pressure, including
  candidate physical register, blocker reason, holder `ig_id` when available,
  holder assigned physical, and provenance such as interference edge,
  call-clobber, reserved register, or class constraint.
- `candidate_phys_ordered`: ordered candidate physicals at the final choice
  point after filtering/blocking.
- `chosen_source`: `volatile_pool`, `nonvolatile_dispense`, `precolored`,
  `coalesced`, or `spill`.
- `volatile_pool_before` and `volatile_pool_after` when observed.
- `nonvolatile_dispense_before` and `nonvolatile_dispense_after` when observed,
  including next register, consumed register, and sticky-pool additions.
- `tie_rule`: the rule used to pick among available candidates, such as
  lowest-numbered volatile candidate or top-down nonvolatile dispense.
- `blocked_by`: compatibility summary of blockers for quick display. The
  structured source of truth is `blocked_candidates`.
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

- For every v1 allocator class a function uses, the consumer subset must
  include nodes, edges, coalesce roots/aliases, simplify/select order, color
  decisions, assigned physicals, spill flags, and the structured color-decision
  pressure fields needed to explain why one physical was chosen over another.
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

Default exit semantics:

- `--verify-debug` exits successfully when the retail trace is valid, schema
  validation passes, and the retail-vs-debug comparison completes.
- Retail/debug differences are reported as data in `backend-fidelity.json` and
  `backend-fidelity.txt`; they are not command failures by default.
- The command exits nonzero for trace defects, schema defects, runtime failures,
  missing required retail facts, missing requested inputs, or verifier crashes.
- A future `--strict` or equivalent mode may make selected unexpected
  retail/debug differences fail CI, but that is not the default because real
  retail/debug divergence is one reason this tool exists.

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

## Implementation Milestones

Implementation should land behind visible gates rather than trying to jump from
schema design directly to the hardest live case.

Milestone ladder:

1. Schema and synthetic normalizer fixtures. Artifact: schema docs plus a
   checked-in minimal `backend-trace.v1.json` fixture with allocator facts.
2. Existing GC/1.1 backend reuse/regression. Artifact: a GC/1.1 backend trace or
   fixture normalized through the new schema shape where applicable.
3. GC/1.2.5n address and struct confidence map. Artifact:
   `struct-map.v1.json`/table updates with invariants and evidence for required
   backend/regalloc fields.
4. One matched-function live GC/1.2.5n backend trace. Artifact: complete trace,
   summary, and verifier output.
5. One register-allocation-only mismatch live trace. Artifact: complete trace
   and enough color-decision facts to explain a wrong physical choice.
6. `mnDiagram_UpdateScrollArrows` live trace or documented current-name mapping
   plus blocker evidence if the function cannot be resolved.

Each milestone should produce an artifact that remains useful even if a later
stage blocks. A serious confidence blocker in milestone 3 or later should be
reported before pivoting.

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

The implementation must also add a checked-in consumer-contract fixture, for
example:

`tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json`

The fixture must contain at least two GPR nodes, one interference edge, one
coalesce mapping, simplify/select order, and one color decision with structured
blockers. It exists so downstream tools such as the lifetime-pressure explorer
can develop adapters without parsing raw gdb events or waiting for live retail
traces.

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
