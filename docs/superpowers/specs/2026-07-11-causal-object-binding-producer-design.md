# Causal Object-Binding Producer Extension Design

**Status:** Approved and independently reviewed

**Date:** 2026-07-11

**Parent design:** `docs/superpowers/specs/2026-07-11-cross-layer-causal-differencer-design.md`

## 1. Purpose

The cross-layer causal differencer correctly abstains on the exact regenerated
`mnDiagram_DrawFighterHeaders` frontiers. Existing artifacts independently show:

- source and inspector objects;
- virtual registers and allocator nodes;
- final physical-register assignments; and
- final stack objects and offsets.

They do not preserve an exact identity from one compiler `ObjObject` to both its
allocator virtual/IG node and its final stack home. Reconstructing that identity
from names, ordinals, instruction proximity, or source order is heuristic and
cannot support a `causes` verdict.

This extension adds an exact, capture-scoped producer record:

```text
compiler ObjObject
  ├── produced virtual / allocator node
  └── materialized in final frame slot
```

Phase 1 uses the existing retail MWCC one-pass tracer. It deliberately leaves a
compatible seam for a later same-process inspector to add exact
source-expression/ENode identity without changing Phase 1 records.

## 2. Goals

1. Emit same-run `ObjObject* -> virtual/IG` bindings from retail GC/1.2.5n.
2. Emit same-run PCode operand-to-virtual and PCode-to-final-code-offset
   bindings from the retail compiler.
3. Emit same-run `ObjObject* -> final stack home` bindings.
4. Preserve one-to-many object/virtual relationships and spill-owned objects.
5. Validate every struct field and global before treating bindings as proof.
6. Normalize bindings into immutable compile-local causal evidence.
7. Align corresponding compiler objects across frontiers by proven semantic
   roles, never by runtime pointers or source names alone.
8. Keep all existing strict inference and abstention gates unchanged.
9. Keep v1 traces and bundles readable; they simply lack ownership capability.
10. Reserve stable Phase 2 source/ENode field names and an explicit schema
   upgrade seam without accepting underspecified records.
11. Preserve storage-neutral records suitable for a persistent provenance DB.

## 3. Non-goals

- Do not infer ownership from nearest declaration, ObjObject address order,
  synthetic `@NNNN` names, or physical-register equality.
- Do not compare runtime pointers across processes, captures, or frontiers.
- Do not call compiler accessors that may lazily allocate backend state.
- Do not classify missing ownership as positive `no-owner` evidence.
- Do not weaken `causes`, gate 3, gate 5, gate 7, or traversal-completeness rules.
- Do not make the remote mwcc-inspector pointer space comparable to the retail
  tracer pointer space.
- Do not require Phase 2 same-process inspector work in the Phase 1 patch.

## 4. Why the retail one-pass tracer

The retail tracer is the smallest exact seam already present in the repository.

- Vendored cadmic GC/1.1-family structures define `IGNode.obj_addr` at `+0x04`
  and already join that pointer to frame-list ObjObjects.
- Static GC/1.2.5n disassembly shows the same pointer being stored in
  `interferencegraph[virtual] + 0x04`.
- The current GC/1.2.5n reader captures every relevant IGNode field except
  `obj_addr`.
- The current frame reader dereferences each frame-list ObjObject but drops the
  raw pointer from normalized output.
- The one-pass hook observes allocator state at colorgraph return and frame
  state at final scheduling in one compiler process.

The patched debug DLL remains a fast diagnostic PCode/allocator producer, but
its virtual and IG numbers belong to a different compiler process. Phase 1
never joins those numbers into a proof path. The retail producer must instead
emit structured PCode operands, allocator rewrites, and final code-offset
ranges from the same capture as the ObjObject/IG evidence. Patched-DLL pcdump
may corroborate a result but cannot supply a proof-capable edge.

## 5. Architectural invariants

### 5.1 Capture identity

Every object-binding capture has:

- a fresh 128-bit random nonce;
- compiler executable digest;
- source digest;
- MWCC command digest;
- dependency/environment digest;
- generated candidate-object digest;
- function identity; and
- trace artifact digest after finalization.

After compilation, the producer finalizes this identity payload, which
deliberately excludes `capture_run_id`:

```json
{
  "nonce": "<32 lowercase hex>",
  "compiler_executable_sha256": "<64 lowercase hex>",
  "source_sha256": "<64 lowercase hex>",
  "mwcc_command_sha256": "<64 lowercase hex>",
  "environment_digest": "<64 lowercase hex>",
  "candidate_object_sha256": "<64 lowercase hex>",
  "function": "mnDiagram_DrawFighterHeaders"
}
```

`capture_run_id` is the lowercase hexadecimal SHA-256 digest of the RFC 8785
canonical bytes of that payload. The nonce is created before compilation, but
the identity payload and run ID are finalized only after the producer hashes
the generated candidate object. The producer then serializes the same fields
plus `capture_run_id` as `capture_identity`.

This identity remains serialized inside the producer artifact. Bundle loading
later verifies it before adding the compile-scoped evidence ID:

The serialized record is identical to the canonical payload above with one
additional `capture_run_id` field.

The producer receives the compile manifest's existing bare-hex
`environment_digest` as an explicit capture input and serializes it unchanged;
this design does not invent or claim a new dependency-closure algorithm. The
v2 bundle also contains the exact generated candidate object as an immutable
artifact. The producer hashes its raw bytes, and the loader independently
hashes the loaded candidate-object artifact.

The loader recomputes `capture_run_id`; requires source, function, and
environment digests to match the compile manifest; requires the candidate
object digest to match the independently loaded candidate-object artifact; and
requires the v2 backend artifact reference to pin the compiler executable,
command, environment, candidate-object, and RFC 8785 capture-identity digests.
The artifact digest protects the complete trace. A trace cannot be attached to a
bundle merely because source bytes and command text agree.

Runtime pointers are meaningful only inside the tuple:

```text
(trace_artifact_digest, capture_run_id, function, runtime_address)
```

The nonce prevents accidental equality when separate compiler processes reuse
the same addresses.

### 5.2 Cardinality

- One ObjObject may bind to multiple virtuals.
- Multiple objects may participate in one source expression.
- One virtual/IG node has at most one non-null ObjObject pointer in a capture.
- An ObjObject may have no frame binding.
- An object absent from frame lists is not considered non-materialized unless
  coverage is complete and spill-owned objects were also enumerated.

### 5.3 Confidence

- Raw allocator-stage `IGNode.obj_addr` and object snapshots are `observed`.
- Raw final-stage frame-list object snapshots are `observed`.
- The computed final `r1` stack home is `derived-unique` from observed frame
  membership, raw object offset, base size, and call-argument size.
- Raw same-run PCode operand rewrites and emitted byte ranges are `observed`.
- Cross-stage PCode allocation-generation identity and the resulting
  anchor-to-PCode join are `derived-unique`.
- A cross-stage address/generation join is `derived-unique`; fingerprint
  equality is only a required consistency check.
- Exact virtual-to-IG/coalesce joins retain their existing confidence.
- A complete unique semantic source/inspector join is `derived-unique`.
- Names, ordinals, address order, and partial fingerprints are `heuristic`.
- The effective confidence remains the minimum of all producer, adapter, and
  input-record confidences.

## 6. Producer trace contract

Phase 1 introduces the inner payload schema
`mwcc-retro-backend-trace.v2`. The v1 payload schema remains unchanged and
supported. Section 9 separately names the bundle artifact format.

Each v2 function may contain:

```json
{
  "object_bindings": {
    "schema_version": "mwcc-retro-object-bindings.v1",
    "capture_identity": {},
    "capture_run_id": "<64 lowercase hex>",
    "lifetime_proof": {},
    "coverage": {},
    "lifecycle_events": [],
    "objects": [],
    "virtual_bindings": [],
    "frame_bindings": [],
    "pcode_instructions": [],
    "pcode_occurrences": [],
    "pcode_operand_lineage_events": [],
    "source_bindings": [],
    "source_capture": null
  }
}
```

`capture_run_id` must equal `capture_identity.capture_run_id`.

`source_bindings` must be empty and `source_capture` must be null in
`mwcc-retro-object-bindings.v1`. They reserve stable field names only; v1
validators reject any populated value. Phase 2 introduces
`mwcc-retro-object-bindings.v2` and a new outer payload schema after its source
graph, edge, coverage, ordering, cardinality, and referential-integrity rules
are fully specified. The Phase 1 object, virtual, and frame record shapes and
IDs remain unchanged in that later schema.

`lifetime_proof` is embedded so a trace is self-contained. This
schema-shape example abbreviates its collection arrays:

```json
{
  "schema_version": "mwcc-retro-lifetime-proof.v1",
  "proof_id": "gc-1.2.5n-backend-entity-allocation-trace.v1",
  "compiler_executable_sha256": "<64 lowercase hex>",
  "mode": "allocation-generation",
  "allocation_sites": [
    {
      "site_id": "objobject-alloc-2",
      "address": 5426422,
      "entity_kind": "objobject",
      "compiler_stage": "frontend"
    },
    {
      "site_id": "pcode-alloc-1",
      "address": 5426500,
      "entity_kind": "pcode",
      "compiler_stage": "backend-lowering"
    }
  ],
  "free_sites": [
    {
      "site_id": "objobject-free-1",
      "address": 5427010,
      "entity_kind": "objobject",
      "compiler_stage": "backend-finalize"
    }
  ],
  "operand_rewrite_sites": [
    {
      "site_id": "rewrite-register-operand-1",
      "address": 5034000,
      "compiler_stage": "colorgraph"
    }
  ],
  "operand_mutation_sites": [
    {
      "site_id": "rewrite-pcode-operands-1",
      "address": 5012000,
      "compiler_stage": "optimizer"
    }
  ],
  "code_emission_sites": [
    {
      "site_id": "emit-pcode-1",
      "address": 4969000,
      "compiler_stage": "backend-finalize"
    }
  ],
  "operand_rules": [
    {
      "opcode_id": 42,
      "operand_index": 1,
      "raw_arg_kind_id": 7,
      "register_flags_mask": 3,
      "register_flags_value": 0,
      "role": "use",
      "class_id": 0,
      "allocation_requirement": "allocator-rewrite-required"
    }
  ],
  "opcode_table": [
    {"opcode_id": 42, "mnemonic": "ADDI"}
  ],
  "initialization_address": 4198400,
  "proof_basis": "exhaustive-static-callgraph-and-disassembly"
}
```

`proof_sha256` is the lowercase SHA-256 digest of this complete proof object
encoded as RFC 8785 canonical JSON; the proof object does not contain its own
digest. Its compiler digest must equal the capture identity and bundle pins.
In an accepted artifact the site arrays are complete, not abbreviated: the
loader rejects duplicate IDs/addresses, unknown fields, or counts that
disagree with coverage.

The embedded proof is portable evidence, not its own trust anchor. The
version-controlled GC/1.2.5n struct-map registry in
`tools/mwcc_retro/tables/gc_125n.json` contains the independently promoted tuple
`(compiler_executable_sha256, proof_id, proof_sha256)`. The loader reads that
installed registry and requires an exact match before accepting lifecycle
coverage.
Promotion requires the existing bounded probe plus a reviewed exhaustive
static call-graph/disassembly audit of all ObjObject/PCode allocation and
free/recycle sites, every register-operand rewrite path, and every PCode
operand creation/deletion/reorder/clone/replace path and code-emission path,
plus the exhaustive opcode/PCodeArg role and allocatability table and raw-opcode
mnemonic table. An embedded proof absent from the registry, or differing from
its registered digest, is untrusted even when internally consistent.

When `lifetime_identity.mode` is `allocation-generation`,
`lifecycle_events` contains the canonical raw input from which coverage is
recomputed. Each record has this shape:

```json
{
  "sequence": 0,
  "event": "allocate",
  "entity_kind": "objobject",
  "runtime_address": 17341832,
  "allocation_generation": 1,
  "instrumented_site_id": "objobject-alloc-2",
  "compiler_stage": "frontend"
}
```

`event` is only `allocate` or `free`; `entity_kind` is only `objobject` or
`pcode`. `compiler_stage` is only `frontend`,
`optimizer`, `backend-lowering`, `colorgraph`, `scheduler`, or
`backend-finalize`. An `allocate` event must reference an entry in
`allocation_sites`; a `free` event must reference an entry in `free_sites`.
The event's entity kind and stage must equal the registered values for that
site. Cross-kind site references and unknown event types, entity kinds, sites,
stages, or fields fail closed. Generations are tracked independently by
`(entity_kind, runtime_address)`.

### 6.1 Compiler object

```json
{
  "object_id": "obj-<capture-local ordinal>",
  "allocation_generation": 31,
  "runtime_address": 17341832,
  "name": "@1897",
  "name_kind": "compiler-synthetic",
  "name_record_pointer": 5633400,
  "type_pointer": 5633520,
  "type_size": 4,
  "areas": ["locals"],
  "stage_snapshots": [
    {
      "stage": "colorgraph_return",
      "allocation_generation": 31,
      "lifecycle_sequence_at_capture": 38,
      "runtime_address": 17341832,
      "name_record_pointer": 5633400,
      "type_pointer": 5633520,
      "type_size": 4,
      "readable": true
    },
    {
      "stage": "final_scheduler",
      "allocation_generation": 31,
      "lifecycle_sequence_at_capture": 45,
      "runtime_address": 17341832,
      "name_record_pointer": 5633400,
      "type_pointer": 5633520,
      "type_size": 4,
      "readable": true
    }
  ],
  "cross_stage_identity_confidence": "derived-unique",
  "lifetime_identity_mode": "allocation-generation"
}
```

`object_id` is assigned deterministically after capture by sorting
`(runtime_address, allocation_generation)`. Both components are non-null. The
raw address and generation remain capture-local provenance, not cross-run
identity.

The producer snapshots every positive `obj_addr` at colorgraph return,
including objects absent from final frame lists. The allocator-stage snapshot
contains the raw address, name-record pointer, type pointer, type size, and
readability status. A second snapshot records the same identity fields at final
scheduling when the object appears in a frame list.

Both stage snapshots are serialized. Snapshot fingerprint agreement is a
consistency check, not sufficient identity proof: an address may be freed and
reused for an object with the same fingerprint. Cross-stage identity therefore
requires complete allocation-generation identity: allocation/free tracing
assigns a monotonically increasing generation to every ObjObject allocation,
and both stages cite the same address and generation.

Version 1 permits only `lifetime_identity_mode: allocation-generation` and
serializes the same non-null `allocation_generation` on the object and each
snapshot. Missing or incomplete lifetime proof leaves the two snapshots as
separate observed facts and cannot produce a cross-stage compiler-object
identity. A differing fingerprint is still a contradiction and forces
abstention. A future no-reuse proof mode requires a new discriminated lifetime
proof schema; v1 rejects it instead of accepting an underspecified variant.

Every snapshot also serializes `lifecycle_sequence_at_capture`, the greatest
event sequence atomically committed before the stopped compiler stage was
read, or `-1` when no lifecycle event has occurred. Compiler execution is
already stopped at both capture hooks, so no lifecycle event can race the
snapshot. The loader replays lifecycle events through that inclusive sequence
and requires the snapshot's address/generation pair to be active at that exact
point.

`stage_snapshots` contains one or two records:

- allocator-only and spill-owned objects contain only `colorgraph_return`;
- frame-only objects contain only `final_scheduler`; and
- cross-stage objects contain exactly one of each.

`cross_stage_identity_confidence` is `null` for a one-stage object and
`derived-unique` only when two agreeing snapshots also share a proven lifetime
identity. One-stage objects are valid diagnostic facts but cannot support the
complete object-to-allocator and object-to-stack ownership proof.

`name_kind` is one of:

- `source-name` when the compiler exposes a non-synthetic name;
- `compiler-synthetic` for observed compiler-generated names;
- `observed-unnamed` when the name record is absent/unreadable.

Absence of a source name never means compiler-generated ownership.

### 6.2 Object-to-virtual binding

```json
{
  "object_id": "obj-7",
  "class_id": 0,
  "class_name": "gpr",
  "virtual_kind": "r",
  "virtual": 66,
  "ig_id": 66,
  "ignode_runtime_address": 17400000,
  "source_stage": "colorgraph_return",
  "confidence": "observed",
  "provenance": "retail-ignode.obj_addr"
}
```

Null object pointers are not emitted as bindings. Coalesced aliases remain
separate bindings and reuse the existing exact coalesce-root relationship.

### 6.3 Object-to-frame binding

```json
{
  "object_id": "obj-7",
  "area": "locals",
  "list_node_runtime_address": 17500000,
  "raw_object_stack_offset": -12,
  "frame_base_size": 84,
  "frame_call_args_size": 0,
  "final_r1_offset": 72,
  "size": 4,
  "source_stage": "final_scheduler",
  "confidence": "derived-unique",
  "provenance": [
    "retail-frame-list.object",
    "retail-objobject.stack-offset",
    "retail-frame-layout-formula.v1"
  ]
}
```

The producer computes:

```text
final_r1_offset = frame_base_size + frame_call_args_size
                  + raw_object_stack_offset
```

Frame-list membership and each raw input remain separately recorded as
`observed`. Because `final_r1_offset` is calculated, the layout-bearing frame
binding and normalized stack-home edge are `derived-unique`; validation against
final PCode/assembly is an independent consistency gate and does not upgrade
them to `observed`.

The live probe must confirm this formula against final PCode/assembly stack
operands before the capability can be enabled.

### 6.4 Same-run PCode anchor and virtual occurrences

The retail capture serializes final-emission instruction records:

```json
{
  "pcode_id": "pc-<capture-local ordinal>",
  "runtime_address": 17450000,
  "allocation_generation": 12,
  "block_order": 4,
  "instruction_order": 37,
  "function_symbol": "mnDiagram_DrawFighterHeaders",
  "section_name": ".text",
  "coordinate_space": "function-relative-bytes",
  "stage_snapshots": [
    {
      "stage": "allocator_input",
      "lifecycle_sequence_at_capture": 50,
      "runtime_address": 17450000,
      "allocation_generation": 12,
      "opcode_id": 42,
      "opcode": "ADDI",
      "arg_count": 3,
      "parsed_register_operands": [
        {
          "operand_index": 0,
          "role": "def",
          "class_id": 0,
          "raw_arg_kind_id": 7,
          "raw_register_flags": 0,
          "allocation_requirement": "allocator-rewrite-required",
          "operand_lineage_id": "ol-6",
          "virtual_kind": "r",
          "virtual": 67,
          "physical_register": null
        },
        {
          "operand_index": 1,
          "role": "use",
          "class_id": 0,
          "raw_arg_kind_id": 7,
          "raw_register_flags": 0,
          "allocation_requirement": "allocator-rewrite-required",
          "operand_lineage_id": "ol-7",
          "virtual_kind": "r",
          "virtual": 66,
          "physical_register": null
        }
      ],
      "operand_lineage_inventory": [
        {
          "operand_index": 0,
          "operand_lineage_id": "ol-6",
          "raw_arg_kind_id": 7,
          "raw_payload_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        },
        {
          "operand_index": 1,
          "operand_lineage_id": "ol-7",
          "raw_arg_kind_id": 7,
          "raw_payload_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        },
        {
          "operand_index": 2,
          "operand_lineage_id": "ol-8",
          "raw_arg_kind_id": 1,
          "raw_payload_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
        }
      ]
    },
    {
      "stage": "code_emission",
      "lifecycle_sequence_at_capture": 61,
      "runtime_address": 17450000,
      "allocation_generation": 12,
      "opcode_id": 42,
      "opcode": "ADDI",
      "arg_count": 3,
      "parsed_register_operands": [
        {
          "operand_index": 0,
          "role": "def",
          "class_id": 0,
          "raw_arg_kind_id": 8,
          "raw_register_flags": 1,
          "allocation_requirement": "fixed-physical",
          "operand_lineage_id": "ol-6",
          "virtual_kind": null,
          "virtual": null,
          "physical_register": 22
        },
        {
          "operand_index": 1,
          "role": "use",
          "class_id": 0,
          "raw_arg_kind_id": 8,
          "raw_register_flags": 1,
          "allocation_requirement": "fixed-physical",
          "operand_lineage_id": "ol-7",
          "virtual_kind": null,
          "virtual": null,
          "physical_register": 21
        }
      ],
      "operand_lineage_inventory": [
        {
          "operand_index": 0,
          "operand_lineage_id": "ol-6",
          "raw_arg_kind_id": 8,
          "raw_payload_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
        },
        {
          "operand_index": 1,
          "operand_lineage_id": "ol-7",
          "raw_arg_kind_id": 8,
          "raw_payload_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        },
        {
          "operand_index": 2,
          "operand_lineage_id": "ol-8",
          "raw_arg_kind_id": 1,
          "raw_payload_sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        }
      ]
    }
  ],
  "emission_event_sequence": 101,
  "emission_site_id": "emit-pcode-1",
  "emission_runtime_address": 17450000,
  "emission_allocation_generation": 12,
  "emission_lifecycle_sequence_at_capture": 61,
  "code_ranges": [
    {
      "start": 564,
      "end_exclusive": 568,
      "bytes": "3ad50000",
      "relocations": [],
      "machine_operand_mappings": [
        {
          "instruction_offset_within_range": 0,
          "machine_operand_position": 0,
          "machine_operand_key": "def:0",
          "emission_pcode_operand_index": 0,
          "operand_lineage_id": "ol-6",
          "physical_register": 22
        },
        {
          "instruction_offset_within_range": 0,
          "machine_operand_position": 1,
          "machine_operand_key": "use:0",
          "emission_pcode_operand_index": 1,
          "operand_lineage_id": "ol-7",
          "physical_register": 21
        }
      ]
    }
  ],
  "cross_stage_identity_confidence": "derived-unique"
}
```

Each PCode instance has exactly one first-observed snapshot, whose stage is
`allocator_input` when it existed at the pre-allocation boundary or
`mutation_output` when a later transformation created it. An emitted instance
has exactly one additional `code_emission` snapshot. There is never one stage
snapshot per operand rewrite; individual rewrites carry their own event and
lifecycle positions. Every snapshot contains its stage-local opcode ID and
name, exact argument count, complete ordered operand-lineage inventory, and
the parsed register subset. A two-snapshot instance has
`cross_stage_identity_confidence: derived-unique`; a non-emitted or newly
observed one-stage diagnostic instance has null confidence.

At the allocator rewrite that replaces or annotates an operand, the same
retail process emits:

```json
{
  "pcode_id": "pc-9",
  "operand_index": 1,
  "operand_lineage_id": "ol-7",
  "role": "use",
  "class_id": 0,
  "class_name": "gpr",
  "virtual_kind": "r",
  "virtual": 66,
  "ig_id": 66,
  "allocated_physical": 21,
  "pcode_event_sequence": 76,
  "instrumented_site_id": "rewrite-register-operand-1",
  "runtime_address": 17450000,
  "allocation_generation": 12,
  "lifecycle_sequence_at_capture": 55,
  "source_stage": "allocator_operand_rewrite",
  "confidence": "observed"
}
```

Every trusted PCode operand mutation site also emits full input/output state
transition. For example:

```json
{
  "pcode_event_sequence": 77,
  "instrumented_site_id": "rewrite-pcode-operands-1",
  "mutation_kind": "update",
  "inputs": [{
    "pcode_id": "pc-9",
    "runtime_address": 17450000,
    "allocation_generation": 12,
    "lifecycle_sequence_at_capture": 55,
    "opcode_id": 42,
    "arg_count": 3,
    "operands": [
      {
        "operand_index": 0,
        "operand_lineage_id": "ol-6",
        "raw_arg_kind_id": 7,
        "raw_payload_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      },
      {
        "operand_index": 1,
        "operand_lineage_id": "ol-7",
        "raw_arg_kind_id": 7,
        "raw_payload_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
      },
      {
        "operand_index": 2,
        "operand_lineage_id": "ol-8",
        "raw_arg_kind_id": 1,
        "raw_payload_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      }
    ]
  }],
  "outputs": [{
    "pcode_id": "pc-9",
    "runtime_address": 17450000,
    "allocation_generation": 12,
    "lifecycle_sequence_at_capture": 56,
    "opcode_id": 42,
    "arg_count": 3,
    "operands": [
      {
        "operand_index": 0,
        "operand_lineage_id": "ol-6",
        "raw_arg_kind_id": 8,
        "raw_payload_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
      },
      {
        "operand_index": 1,
        "operand_lineage_id": "ol-7",
        "raw_arg_kind_id": 8,
        "raw_payload_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
      },
      {
        "operand_index": 2,
        "operand_lineage_id": "ol-8",
        "raw_arg_kind_id": 1,
        "raw_payload_sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
      }
    ]
  }]
}
```

`mutation_kind` is a closed discriminator with these state cardinalities:

| Kind | Inputs | Outputs | PCode survival rule |
|---|---:|---:|---|
| `update` | exactly 1 | exactly 1 | output has the same `pcode_id` |
| `clone` | exactly 1 | 2 or more | output IDs are distinct; the input ID may appear at most once |
| `replace` | 1 or more | 1 or more | input and output PCode-ID sets are disjoint |
| `delete` | 1 or more | exactly 0 | all input states are consumed |
| `create` | exactly 0 | 1 or more | all output PCode IDs are new |

Each input/output state contains a complete operand array, not a delta. The
loader recomputes every PCode ID from raw identity, requires all input states
to be distinct and equal their current replay states, atomically removes those
states, then installs distinct complete output states. Any transformation that
does not fit one discriminator is recorded diagnostically and makes lineage
coverage incomplete.

Lineage IDs denote stable semantic operand identity, not per-event graph nodes.
An output that preserves, reorders, or clones an operand reuses its existing
lineage ID and must omit `parent_lineage_ids`. A fresh output lineage ID is a
definition and must include `parent_lineage_ids`: empty only for `create`, or a
non-empty sorted set of lineage IDs present in the event inputs for a derived
operand. Clone outputs may reuse input lineage IDs across multiple output
states but may not define fresh lineages. Inputs absent from all outputs are
consumed from those PCode states; their lineage definitions may remain
reachable from other states.

Initial lineage IDs are assigned after capture by sorting
`(allocator-input pcode_id, operand_index)`; fresh output definitions follow
`(pcode_event_sequence, output pcode_id, operand_index)`. Existing IDs may
appear in many states but are defined once. Fresh IDs are defined once, cannot
parent themselves, and may reference only earlier/input definitions, making
the parent graph acyclic by construction. The loader recomputes IDs and rejects
undeclared, self-parented, cyclic, or multiply defined fresh lineages.

The machine-operand mapping at emission references its current
`operand_lineage_id`, not an assumed stable allocator-stage index. A
proof-capable anchor walks the complete lineage graph backward and requires
exactly one reachable allocator rewrite occurrence. Zero reachable origins
abstain as missing; multiple reachable origins abstain as ambiguous. Thus an
opcode change, argument reorder, clone, PCode replacement, or in-place payload
mutation cannot silently reuse operand-index meaning.

`role` is only `use`, `def`, or `use-def`. The producer validates the complete
GC/1.2.5n PCode and PCodeArg layouts, records every register operand and
allocator rewrite path, and observes the exact PCode pointer passed to code
emission. PCode lifecycle events assign allocation generations exactly like
ObjObjects; `pcode_id` is sorted from `(runtime_address,
allocation_generation)`. The loader replays lifecycle events at both snapshot
positions and requires the same active PCode generation.

Every PCode stage snapshot and mutation side preserves numeric `opcode_id`;
stage snapshots also carry the display mnemonic. The loader requires exactly
one matching entry in the trusted proof's `opcode_table` and verifies every
serialized display mnemonic against that entry; display strings are never used
as rule lookup keys.

The promoted proof contains a compiler-version-specific operand-role and
allocatability table over `(opcode, operand_index, raw_arg_kind_id,
raw_register_flags)`. Applying that closed table produces exactly one
`allocation_requirement`: `allocator-rewrite-required` or `fixed-physical`.
Unknown combinations fail closed. Fixed, reserved, stack-pointer, and
precolored operands remain in the parsed inventory as `fixed-physical`; they
must not have rewrite events.

An `allocator-rewrite-required` inventory record requires non-null
`virtual_kind` and `virtual` and has `physical_register: null`. A
`fixed-physical` record requires non-null `physical_register` and has both
virtual fields null. These are closed discriminated shapes; mixed or missing
identity fields fail validation.

The loader requires exactly one site-tagged rewrite occurrence for every
`allocator-rewrite-required` `(pcode_id, operand_index)`, rejects any rewrite
for `fixed-physical`, and rejects an occurrence absent from the parsed PCodeArg
inventory. Each rewrite record carries its raw PCode pointer, allocation
generation, and lifecycle position; the loader replays lifecycle state and
recomputes `pcode_id` for every event. It also replays operand lineage through
that position and requires the stated operand index to contain the occurrence's
lineage ID under the then-current opcode/argument rule. Each final PCode
dispatch, including a pseudo-op that emits no bytes, likewise records the raw
identity tuple and exactly one site-tagged emission event. Rewrite, mutation,
and emission events share one contiguous `pcode_event_sequence`; coverage is
recomputed from these raw records.

`code_ranges` uses function-relative byte offsets, the same coordinate system
as checkdiff `+NNN` anchors. The loader parses the candidate object's section,
symbol, and relocation tables, uniquely resolves `function_symbol` in
`section_name`, and translates a range to
`section_file_offset + symbol_section_value + start`. Each half-open range must
be ordered, non-overlapping, and within the symbol's declared extent; its hex
bytes must exactly equal the raw pre-link object bytes.

For every relocation whose section-relative offset falls inside a range, the
range serializes a record
`(offset_within_range, relocation_type_id, target_symbol_table_index,
target_symbol, addend)`. IDs and addends are the raw integers from the object;
the target name is checked against the indexed symbol-table entry. The loader
extracts and compares the complete ordered relocation set; missing, extra, or
ambiguous relocation/symbol records force abstention. Checkdiff anchors join by
function-relative offset, while the candidate-object digest binds the full
file. A PCode that emits zero or multiple ranges remains valid diagnostic
evidence, but an assembly anchor is proof-capable only when exactly one PCode
range covers it
and exactly one recorded operand occurrence supplies the required
`(class_id, virtual)` role. Every rejected covering PCode or operand
alternative is retained.

At emission, `machine_operand_mappings` records the exact relationship from a
machine instruction operand back to a PCode operand. Offsets are byte offsets
within the containing range; `machine_operand_position` is the zero-based
operand position produced by the target PowerPC decoder; and
`machine_operand_key` is the decoder's role ordinal (`def:0`, `use:0`,
`use:1`, and so on). The loader decodes every emitted instruction from the raw
candidate bytes and requires exactly one mapping for every decoded register
operand position. Each mapping must reference an existing parsed
emission-snapshot `emission_pcode_operand_index` with the same
`operand_lineage_id`. Its `physical_register` must equal both the decoded
machine register and either the unique reachable lineage rewrite's
`allocated_physical` or the emission inventory record's fixed physical
register. One operand lineage may map to multiple emitted operands, but each
emitted register operand has exactly one source mapping.

The normalized anchor edge is scoped to `(function-relative instruction
offset, machine_operand_key)`, not merely to the instruction range or broad
use/def role. Missing, conflicting, or ambiguous mappings force abstention and
all alternatives remain in diagnostics.

The PCode-to-virtual occurrence is `observed`; PCode-to-code-range emission is
`observed`; PCode instance joins use allocation generation; and the complete
unique operand-lineage traversal is `derived-unique`. The effective
anchor-to-virtual path is therefore `derived-unique`. Virtual/IG equality is
used only within this same `capture_run_id`. Patched-DLL pcdump virtuals are
never joined to these records and remain diagnostic.

### 6.5 Coverage

```json
{
  "status": "complete",
  "ig_classes": ["gpr", "fpr"],
  "frame_areas": ["arguments", "locals", "temps"],
  "spill_owned_ig_coverage": "complete",
  "pcode_instrumentation": {
    "status": "complete",
    "operand_rewrite_sites_expected": 4,
    "operand_rewrite_sites_hooked": 4,
    "operand_mutation_sites_expected": 6,
    "operand_mutation_sites_hooked": 6,
    "code_emission_sites_expected": 2,
    "code_emission_sites_hooked": 2,
    "first_event_sequence": 0,
    "last_event_sequence": 478,
    "parsed_register_operands": 320,
    "allocatable_register_operands": 286,
    "fixed_physical_register_operands": 34,
    "rewrite_events": 286,
    "mutation_events": 50,
    "final_pcodes": 143,
    "emission_events": 143,
    "event_cap": 8192,
    "dropped_events": 0,
    "truncated": false,
    "errors": []
  },
  "lifetime_identity": {
    "mode": "allocation-generation",
    "status": "complete",
    "proof_id": "gc-1.2.5n-backend-entity-allocation-trace.v1",
    "proof_sha256": "<64 lowercase hex>",
    "initialization_stage": "compiler-process-entry-before-compile",
    "allocation_sites_expected": 3,
    "allocation_sites_hooked": 3,
    "free_sites_expected": 1,
    "free_sites_hooked": 1,
    "first_event_sequence": 0,
    "last_event_sequence": 46,
    "allocation_events": 46,
    "free_events": 1,
    "reuse_events": 0,
    "generation_assignments": 46,
    "event_cap": 4096,
    "dropped_events": 0,
    "truncated": false,
    "errors": []
  },
  "allocator_stage": "colorgraph_return",
  "frame_stage": "final_scheduler",
  "objects_seen": 17,
  "virtual_bindings_seen": 24,
  "frame_bindings_seen": 9,
  "pcode_instructions_seen": 143,
  "pcode_occurrences_seen": 286,
  "caps": {
    "max_ig_nodes": 2048,
    "max_frame_objects_per_area": 256,
    "max_pcode_instructions": 4096,
    "max_pcode_operands_per_instruction": 32
  },
  "truncated": false,
  "errors": []
}
```

`complete` requires all declared IG classes, all three actual frame lists,
`spill_owned_ig_coverage: complete`, recomputed complete PCode instrumentation,
a complete lifetime-identity proof, no caps reached, and no reader errors.
`spill-owned` is never a frame area and never implies a frame binding. Partial
coverage may still emit observed positive bindings, but it cannot support
negative ownership, absence claims, or an anchor-to-virtual proof.

PCode instrumentation is complete only when the proof's expected rewrite,
mutation, and emission site inventories exactly equal the installed hooks;
merged raw event sequences are unique and contiguous from zero; every parsed allocatable
register operand has exactly one rewrite event; no fixed-physical operand has a
rewrite; total parsed operands equal allocatable plus fixed-physical operands;
every rewrite, mutation-side, and emission raw identity tuple resolves to its
referenced `pcode_id`; mutation input states equal replay state and output
states account for every operand slot; every final PCode has exactly one
emission event; every
event's site belongs to the correct proof inventory; every decoded emitted
register operand has one physically consistent lineage mapping; recomputed
counts equal coverage; no event was dropped; no cap was reached; and
`truncated` is false with no errors. Producer-declared status strings are never
sufficient. Missing an alternative mutation, rewrite, or emitter path
invalidates uniqueness and forces abstention.

For `allocation-generation`, `proof_sha256` pins a proof record that is itself
pinned to the compiler executable digest and exhaustively enumerates every
ObjObject and PCode allocation and free/recycle call site. Coverage is complete
only when:

1. tracing initialized at `compiler-process-entry-before-compile`, before the
   first frontend action or ObjObject/PCode allocation;
2. expected and hooked allocation/free site counts equal those in the proof;
3. event sequence numbers are contiguous from zero through
   `last_event_sequence`;
4. `generation_assignments == allocation_events`, every allocation increments
   the prior generation for that address, every free names the currently active
   generation, and reuse occurs only after its matching free;
5. every ObjObject and PCode snapshot resolves to exactly one active generation
   at its `lifecycle_sequence_at_capture` after replaying events through that
   inclusive position; and
6. `dropped_events == 0`, no cap was reached, `truncated` is false, and
   `errors` is empty.

The loader recomputes event counts and generation-map invariants from the raw
lifecycle events; producer-declared `status: complete` is not trusted. A gap,
unhooked site, premature initialization, unmatched free, non-increasing reuse,
or proof digest mismatch invalidates cross-stage identity and forces
abstention.

### 6.6 Canonical collection ordering

RFC 8785 canonicalizes object keys but deliberately preserves array order.
Before hashing or serialization, Phase 1 therefore uses these normative array
orders:

| Array | Sort key or fixed order |
|---|---|
| `lifetime_proof.allocation_sites`, `free_sites` | `(entity_kind, address, site_id)` ascending |
| `lifetime_proof.operand_rewrite_sites`, `operand_mutation_sites`, `code_emission_sites` | `(address, site_id)` ascending |
| `lifetime_proof.operand_rules` | `(opcode_id, operand_index, raw_arg_kind_id, register_flags_mask, register_flags_value)` ascending |
| `lifetime_proof.opcode_table` | `opcode_id` ascending |
| `lifecycle_events` | `sequence` ascending; sequences unique and contiguous |
| `objects` | `(runtime_address, allocation_generation)` ascending |
| `stage_snapshots` | `colorgraph_return`, then `final_scheduler` |
| object `areas` | `arguments`, `locals`, `temps`, `spill-owned`, omitting absent values |
| coverage `frame_areas` | `arguments`, `locals`, `temps`, omitting absent values |
| coverage `ig_classes` | `gpr`, then `fpr`, omitting absent values |
| `virtual_bindings` | `(object_id, class_id, virtual_kind, virtual, ig_id, ignode_runtime_address)` ascending |
| `frame_bindings` | `(object_id, frame-area order, list_node_runtime_address, final_r1_offset)` ascending |
| `pcode_instructions` | `(runtime_address, allocation_generation)` ascending; assigned `pcode_id` follows this order |
| PCode `stage_snapshots` | one first-observed stage (`allocator_input` before `mutation_output`), then optional `code_emission` |
| snapshot `operand_lineage_inventory` | `operand_index` ascending; indexes contiguous from zero |
| PCode `parsed_register_operands` | `(operand_index, role, class_id, raw_arg_kind_id, raw_register_flags)` ascending |
| PCode `code_ranges` | `(start, end_exclusive, bytes)` ascending |
| code-range `relocations` | `(offset_within_range, relocation_type_id, target_symbol_table_index, addend)` ascending |
| code-range `machine_operand_mappings` | `(instruction_offset_within_range, machine_operand_position, emission_pcode_operand_index, operand_lineage_id)` ascending |
| `pcode_occurrences` | `(pcode_event_sequence, pcode_id, operand_index)` ascending |
| `pcode_operand_lineage_events` | `pcode_event_sequence` ascending |
| lineage event `inputs`, `outputs` | `(pcode_id, runtime_address, allocation_generation)` ascending |
| lineage event input/output `operands` | `operand_index` ascending; parent lineage IDs use Unicode code-point lexical order |
| provenance string arrays | Unicode code-point lexical order after duplicate rejection |
| error string arrays | Unicode code-point lexical order; duplicates retained only when their full strings differ |

`source_bindings` is empty in v1. Any other Phase 1 array not listed above is
an ordered semantic path only when its field definition explicitly says so;
otherwise strings use Unicode code-point lexical order and records use the
lexicographic tuple of their required scalar fields in schema order. Duplicate
records are rejected rather than silently collapsed. Proof digests are
computed only after this normalization.

## 7. Capture algorithm

1. Generate the nonce and initialize lifecycle capture at process entry before
   any ObjObject or PCode allocation can occur. Do not derive `capture_run_id`
   yet.
2. At colorgraph return, read every validated IG node:
   - IG identity and class;
   - virtual identity;
   - raw `obj_addr`;
   - IGNode pointer;
   - coalesce/color state.
3. Dereference and snapshot every positive object pointer at that stage;
   retain positive object/virtual pairs in hook state even when the object will
   not appear in a final frame list.
4. At the validated allocator-input boundary, snapshot each PCode's complete
   opcode/argument state and assign deterministic initial operand lineage IDs.
5. At every validated allocator operand-rewrite path, record the active PCode
   generation, operand index/role, virtual/IG identity, and assigned physical
   register before mutation can discard the virtual.
6. At every promoted PCode mutation path, emit complete input/output PCode
   states and update the capture-side lineage table atomically.
7. At code emission, record the active PCode generation, complete emission
   snapshot, operand-lineage-to-machine-operand mapping, and every emitted
   candidate-object byte range.
8. At final scheduler, walk arguments, locals, and temporaries using validated
   list globals and ObjObject fields.
9. Retain raw list node, object pointer, name-record pointer, type pointer,
   name, size, readability status, and stack offset.
10. Add positive spill-owned objects present in IG mappings but absent from the
   frame lists; do not manufacture a frame binding for them.
11. Join only exact same-run pointers whose allocation generation agrees;
   require the cross-stage fingerprint `(runtime_address,
   name_record_pointer, type_pointer, type_size)` to agree as an additional
   consistency check.
12. Validate PCode code ranges and stack-offset calculations against the
    generated candidate object and final memory operands.
13. Canonically sort objects and bindings, emit coverage, then assemble v2.
14. After compilation, hash the generated candidate object, finalize the
    capture-identity payload and `capture_run_id`, then serialize the trace and
    immutable candidate-object artifact.

The tracer must never call the compiler backend-record accessor at `0x4C1720`:
it may lazily allocate and would violate observational tracing.

## 8. Struct-map and live-probe gate

No production capability is enabled from static similarity alone.

The accepted GC/1.2.5n struct map must add and validate:

- `IGNode.obj_addr @ +0x04`;
- IGNode identity fields already used by the trace;
- PCode linkage, opcode, argument-count, and argument-array fields;
- the complete PCodeArg kind/register payload layout and operand-role table;
- every allocator operand-rewrite, PCode operand mutation, and final
  code-emission entry used by the capture;
- frame list-node `next @ +0x00` and `object @ +0x04`;
- ObjObject name record, type, and stack offset;
- type size;
- arguments, locals, temps list globals; and
- frame base and call-argument size globals.

The existing `debug retro probe-backend-map` workflow is extended rather than
adding a new command. Its bounded object-binding probe must verify:

1. `IGNode.obj_addr` points to readable ObjObjects.
2. Both GPR and FPR mappings have valid object/virtual identity where present.
3. Pointers survive from colorgraph return to final scheduler.
4. PCode/PCodeArg parsing enumerates every register operand and role for GPR
   and FPR instructions, and rewrite events preserve the same-run virtual/IG
   identity before physical replacement.
5. Complete mutation instrumentation preserves or explicitly derives operand
   lineage through opcode changes, reorders, clones, deletes, creates, and
   PCode replacement; ambiguous multi-parent ancestry abstains.
6. Code-emission events map each retained PCode generation to exact
   candidate-object ranges and bytes, including zero- and multi-range cases.
7. Named, synthetic, unnamed, multi-virtual, and spill-owned objects are
   preserved without forcing exclusive ownership.
8. The stack-offset formula matches final PCode/assembly.
9. Both exact DrawFighterHeaders frontiers reproduce their known anchor,
   same-run PCode virtual, allocator, and stack facts.
10. The compiler-version-specific allocation-generation proof exactly matches
   the independently promoted struct-map registry tuple. Dynamic pointer
   survival or an unregistered embedded site list is not sufficient.

Probe failure leaves the struct map unpromoted and the v2 ownership capability
unavailable. There is no heuristic fallback.

## 9. Causal bundle and adapter integration

**Implemented amendment:** Task 9's loose ownership traversal remains available
only as diagnostic graph evidence. It is superseded as a proof API by the
content-addressed owner certificate whose parser is
`causal-owner-certificate.v1`, as specified in
`2026-07-12-verified-owner-path-certificate-design.md`. Alignment,
differencing, effects, and inference consume the certificate result and its
certified comparisons; they do not reconstruct v2 ownership proof from the raw
edges listed below. This amendment does not promote the currently empty retail
proof registry or make current genuine v2 artifacts proof-capable.

The causal bundle uses two distinct version identifiers:

```text
bundle schema_version: causal-frontier-bundle.v2
BackendArtifactRef.format: backend-trace.v2
backend payload schema_version: mwcc-retro-backend-trace.v2
```

This preserves the existing convention in which manifest artifact formats and
inner producer schema versions have different namespaces. It is not a naming
break and the loader never accepts one identifier in place of the other.
`causal-frontier-bundle.v2` adds the required
`artifacts.candidate_object: ArtifactRef`; the loader hashes that file's raw
bytes and compares them with the capture and backend-reference pins. V1 bundles
remain readable but cannot reference a v2 ownership backend.

Optional verified capabilities are:

- `compiler-object-bindings`;
- `object-to-virtual`;
- `object-to-frame`;
- `pcode-to-code-range`;
- reserved `object-to-source` for Phase 2.

The loader recomputes capability predicates and never trusts declaration or
parser support alone:

| Capability | Required verification | Empty capture semantics |
|---|---|---|
| `compiler-object-bindings` | Valid v2 capture/environment/output identity; trusted lifetime-proof registry match; complete lifecycle coverage; every object and snapshot passes generation, fingerprint, cardinality, and referential checks | May be present with zero objects when coverage proves the function has none |
| `object-to-virtual` | `compiler-object-bindings`; complete GPR/FPR and spill-owned IG coverage; every positive binding references an existing allocator-stage object and valid IG/virtual; no unresolved positive record | May be present with zero bindings; it proves exhaustive observation, not that an edge exists |
| `object-to-frame` | `compiler-object-bindings`; complete arguments/locals/temps coverage; promoted stack-layout formula; every positive binding references an existing final-stage object and its recomputed offset matches final PCode/assembly | May be present with zero bindings; it proves exhaustive observation, not materialization |
| `pcode-to-code-range` | Trusted PCode lifetime/opcode proof; complete operand-rewrite, mutation-lineage, and emission coverage; every range matches candidate-object bytes; every decoded register operand has one physically consistent lineage mapping with a unique rewrite origin; each event refers to an active same-run PCode generation | May be present with zero emitted instructions; it proves exhaustive observation, not an anchor edge |
| `object-to-source` | Always false for object-bindings v1; populated reserved fields are invalid | Never declared in Phase 1 |

Partial diagnostic traces declare none of these capabilities. A causal path
still requires positive records: capability presence on an empty function or
without a cross-stage object cannot satisfy an inference gate.

For a proof-capable anchor path, `pcode-occurrences`, `virtual-use-def`,
`pcode-to-code-range`, and `object-to-virtual` must all be verified on the same
`backend-trace.v2` artifact and `capture_run_id`. Equivalent capabilities from
a patched-DLL pcdump in another process are diagnostic only and cannot be
substituted or merged by virtual/IG number.

The five existing core backend capabilities remain unchanged. V1 bundles still
load; they simply lack object ownership proof.

For v2 artifacts, `BackendArtifactRef` additionally requires:

- `capture_identity_sha256`;
- `compiler_executable_sha256`;
- `mwcc_command_sha256`;
- `environment_digest`; and
- `candidate_object_sha256`.

The bundle loader compares these pins to the serialized capture identity and
recomputes its digest before parsing ownership evidence.

The backend adapter emits compile-local records:

- `compiler-object` node;
- `retail-pcode` node;
- `assembly-anchor-emitted-by-pcode` derived-unique edge;
- `pcode-operand-lineage` observed mutation records and derived-unique unique
  ancestry edges;
- `pcode-operand-uses-virtual` observed edge;
- `object-materializes-virtual` observed edge;
- `object-has-stack-home` derived-unique edge; and
- existing exact virtual-to-allocator/coalesce edges.

The operand-scoped anchor edge cites the exact candidate-object range, decoded
machine operand key, emission mapping, and derived-unique PCode generation
join. The PCode operand edge cites the exact PCode operand index and allocator
rewrite event from that same capture. The object virtual edge cites the
allocator-stage object snapshot. The frame edge cites the final-stage object
snapshot. The normalized `compiler-object` node cites both snapshots and the
derived-unique cross-stage fingerprint join, so the complete ownership path
cannot silently treat address equality, a broad use/def role, or a
cross-process virtual number as a raw observation.

Record IDs include compile ID, capture-run ID, object or PCode local ID, and
event kind. Raw runtime addresses remain attributes/provenance only.

Cross-run pointer equality is rejected even when numeric addresses match.

## 10. Source and inspector attachment

Phase 1 does not compare remote inspector pointers with retail pointers and
does not claim a proof-capable source-expression attachment. Its compiler
object contains exact backend and frame identity, but not enough object-side
lexical/ENode state to satisfy the complete source fingerprint.

Phase 1 may emit diagnostic heuristic source candidates using:

- source digest and function;
- canonical datatype and complete type;
- lexical and inline scope path;
- normalized defining ENode/operator tree;
- object role and frame area;
- consumer/callee context; and
- compiler-object role path.

Names may be diagnostic attributes but are never sufficient selectors.
Synthetic ordinals and address order are never selectors.

Every alternative is retained. These candidates never satisfy a required
source ownership gate and do not create `object-to-source` evidence records.
Phase 1 therefore ends at
`source-object-binding-missing` whenever a verdict requires the source layer.

Inference adds `gate-9-source-object-binding`: a `causes` verdict requires one
proof-capable `object-to-source` record for each bilateral compiler object.
Missing records always abstain. A complete finite record from a versioned
source-binding producer may be heuristic and cap the verdict at
`candidate-cause`; only derived-unique or observed records are proof-capable.
Phase 1 diagnostics are not such records.

A `derived-unique` source attachment remains supported only when another
versioned artifact independently provides every complete fingerprint field on
both sides. The current remote inspector plus Phase 1 trace does not meet that
condition.

## 11. Cross-frontier owner correspondence

Runtime object identities are never compared between frontiers.

Before computing effect direction, each frontier independently resolves the
unique compiler object that has proof-capable bindings to:

- the retail-derived allocator operand role; and
- the expected semantic stack role.

Phase 1 derives a backend-owner correspondence only when exactly one object in
each frontier matches this role tuple:

```text
(operand key, register class, semantic stack role, type size, frame area)
```

The tuple contains identities and expected roles, not whether a frontier is
exact or mismatched. This prevents circularly choosing an owner because it
produces the desired verdict.

This Phase 1 correspondence proves the shared backend/frame mediator but cannot
satisfy the source ownership gate. Phase 2 refines it with the capture-local
canonical type, defining ENode, lexical/inline scope, and consumer role. Missing
source fields never compare as equal empty values.

The correspondence is an analysis-scoped `ComparisonRecord`, never a
cross-compile `EvidenceEdge`. It lists every supporting within-compile record
and uses their weakest confidence.

Inference gate 3 remains unchanged: a `causes` verdict still requires exactly
one bilateral changed owner, complete paths on both sides, and no heuristic
edge. The new source-binding gate is evaluated separately and cannot be
satisfied by the backend-owner correspondence alone.

## 12. Error handling and abstention

The producer or adapter abstains on:

- unvalidated struct fields or globals;
- null, unreadable, reused, or contradictory pointers;
- capture-run, compile, or function mismatch;
- pointer equality across different runs;
- virtual/IG equality across different compiler processes or capture-run IDs;
- incomplete PCode operand-rewrite, mutation-lineage, lifecycle, or
  code-emission coverage;
- missing, cyclic, multiply defined, or multi-origin operand lineage;
- ambiguous anchor-to-PCode range or operand occurrence;
- candidate-object bytes that disagree with an emitted PCode range;
- caps, truncation, cycles, or reader errors;
- multiple unresolved virtual/object mappings;
- missing final frame home when a positive materialization claim is required;
- stack-offset disagreement with final PCode/assembly;
- ambiguous source/inspector attachment;
- missing versioned `object-to-source` evidence required by gate 9;
- incomplete proof traversal.

Positive observed bindings from partial traces may be displayed diagnostically,
but partial coverage cannot prove absence or support `causes` when a required
segment is missing.

## 13. Phase 2 compatibility

Phase 1 intentionally does not define a partially valid source graph. A future
same-process inspector produces a fresh combined capture under these new
version identifiers:

```text
bundle schema_version: causal-frontier-bundle.v3
BackendArtifactRef.format: backend-trace.v3
backend payload schema_version: mwcc-retro-backend-trace.v3
object bindings schema_version: mwcc-retro-object-bindings.v2
source capture schema_version: mwcc-retro-source-capture.v1
```

That Phase 2 design must normatively define statement and ENode records, graph
edge kinds and endpoint constraints, canonical ordering, coverage and
completeness, source-binding cardinality, object/source referential integrity,
and all fail-closed validation rules before any populated `source_capture` or
`source_bindings` value is accepted. Phase 1 v1 validators accept only null and
empty values respectively.

The compatibility seam is nevertheless fixed now:

- the fresh combined capture shares one `capture_run_id` across source,
  object, PCode, allocator, and frame observations;
- Phase 2 source bindings target unchanged Phase 1 `object_id` values;
- bindings use capture-local statement/ENode IDs, never unscoped runtime
  addresses;
- the outer backend artifact digest pins the complete source graph and object
  bindings without a self-referential inner digest;
- source spans remain unavailable unless a separately versioned live probe
  validates them, because current pre-1.3.2 inspector statement offsets are
  not trusted; and
- evidence-store, report, and persistence schemas consume the same normalized
  node/edge model, so existing Phase 1 records require no re-keying.

Historical Phase 1 artifacts remain immutable and coexist with the fresh Phase
2 capture. Gate 9 accepts `object-to-source` only after the later v2 binding
schema and its complete coverage rules have been implemented and verified.

## 14. Testing

### 14.1 Pure producer tests

- Read and validate `IGNode.obj_addr`.
- Retain raw frame-list object pointers.
- Compute final `r1` offsets.
- Preserve multiple virtuals per object.
- Preserve spill-owned objects without inventing frame homes.
- Reject null, invalid, cyclic, truncated, and contradictory inputs.
- Reject same numeric pointer under different capture-run IDs.
- Reject matching cross-stage fingerprints without allocation-generation.
- Reject differing generations, non-contiguous lifecycle events, missed or
  unhooked allocation/free sites, premature tracer initialization, unmatched
  frees, dropped/capped events, and proof-digest mismatch.
- Reject snapshots with missing/out-of-range lifecycle sequence positions or
  an address/generation that is not active at that exact position.
- Reject allocation/free events that use the wrong proof-site kind or a stage
  outside the closed vocabulary or different from the registered site stage.
- Parse every validated PCodeArg register kind and operand role.
- Preserve raw opcode IDs and reject mnemonic or operand-rule lookups that do
  not match the trusted opcode table.
- Preserve allocator rewrite virtual/IG identity through complete operand
  lineage to exact final code ranges, including in-place reorder and PCode
  replacement.
- Reject PCode pointer reuse, missing rewrite paths, overlapping/out-of-bounds
  ranges, byte disagreement, and ambiguous anchor coverage.
- Reject unregistered/unhooked rewrite, mutation, or emission sites,
  non-contiguous PCode event sequences, allocatable-operand/rewrite count
  mismatches, rewrites of fixed/precolored operands, missing final-PCode
  emission events, drops, and caps even when status says complete.
- Reject rewrite/mutation/emission records whose raw PCode pointer, allocation
  generation, or lifecycle position does not independently reconstruct the
  declared `pcode_id`, including multiple rewrites of one PCode.
- Enforce one first-observed snapshot and at most one emission snapshot per
  PCode instance; operand rewrites never create additional stage snapshots.
- Replay full mutation transitions and reject input-state disagreement,
  missing operand slots, cycles, multiply defined lineages, or multiple
  allocator origins for one emitted operand.
- Test update, clone-with-surviving-input, disjoint replacement, delete, and
  create cardinalities; reject self-parent edges, fresh clone IDs, duplicate
  output PCode IDs, and transforms outside the closed shapes.
- Resolve function-relative ranges through candidate-object section/symbol
  tables and reject missing/ambiguous symbols, wrong raw bytes, or any missing,
  extra, or mismatched relocation descriptor.
- Decode emitted machine operands and reject missing/duplicate PCode mappings,
  wrong role ordinals, wrong emission operand indexes or lineage IDs, or
  physical-register disagreement for repeated-use instructions.

### 14.2 Schema and assembler tests

- V1 remains valid and unchanged.
- V2 requires capture identity and valid coverage.
- All collections serialize canonically.
- Permuting any unordered producer collection normalizes to identical bytes
  and digests; semantic stage/path order remains significant.
- Lifecycle events serialize canonically and their site IDs must exist in the
  digest-pinned instrumentation proof.
- The embedded lifetime proof hashes canonically, matches the compiler digest,
  and agrees with coverage site counts.
- Unknown fields and confidence values fail closed.
- Reserved empty `source_bindings` and null `source_capture` round-trip.
- V1 rejects every populated `source_capture` or non-empty `source_bindings`
  value; Phase 2 requires the separately specified v2 binding schema.
- Allocation-generation coverage is recomputed from raw lifecycle events; a
  producer-declared complete status cannot bypass any invariant.
- Environment or candidate-object digest mismatch rejects a trace even when
  source, function, compiler, and command still agree.

### 14.3 Causal adapter tests

- Observed object-to-virtual and derived-unique object-to-frame edges.
- Derived-unique operand-scoped assembly-anchor-to-PCode plus observed same-run
  PCode-operand-to-virtual edges.
- Exact virtual-to-IG/coalesce continuation.
- Reject patched-DLL/retail cross-run virtual-number joins even when numbers
  and candidate-object bytes happen to agree.
- Cross-run pointer mismatch rejection.
- Phase 1 semantic source candidates remain heuristic even when unique.
- V1 rejects populated Phase 2 fields and never emits object-to-source evidence.
- Name-only, ordinal-only, and incomplete fingerprints remain heuristic.
- Ambiguous owner role causes abstention.
- V1 traces remain diagnostic but cannot prove ownership.
- Complete empty captures may verify availability capabilities but emit no
  causal edge; partial traces verify no ownership capability.

### 14.4 Live probe and pilot

Run the bounded probe on:

- one small function with a named local;
- one address-taken/multi-virtual local;
- one FPR or spill-owned object; and
- both exact `mnDiagram_DrawFighterHeaders` frontiers.

**Task 10 remains open.** The artifact-regeneration work below has not been
performed by the owner-certificate amendment. No DrawFighterHeaders v2 artifact
or proof-registry entry is promoted by the certificate implementation; the
committed v1 pilot fixtures remain the compatibility baseline.

Regenerate the paired/direct `backend-trace.v2` artifacts containing
`mwcc-retro-backend-trace.v2` payloads and their manifests with exact commands,
commits, source/tool/artifact hashes, timestamps, and capture IDs.

Phase 1 acceptance requires:

1. paired anchor exact at `r22/r21` with stack `0x48` versus expected `0x44`;
2. direct anchor `r20/r19` with stack exact at `0x44`;
3. one unique bilateral compiler-object owner;
4. proof-capable anchor-to-same-run-PCode-to-virtual/IG-to-object paths on both
   sides, with no patched-DLL virtual edge in either proof;
5. proof-capable object-to-allocator and object-to-stack paths on both sides;
6. complete capture coverage and all cross-stage identities validated; and
7. a deterministic `source-object-binding-missing` abstention that retains the
   exact backend and stack proof paths.

Phase 1 is producer infrastructure and does not claim the final `causes`
verdict. Overall feature acceptance still requires Phase 2 to attach the same
compiler object to a capture-local source/ENode record, after which the existing
strict inference gates must produce the preserve-allocation/shorten-
materialization recommendation.

Historical Phase 1 artifacts and records remain immutable. Phase 2 does not
augment an already-finished capture: it runs a fresh combined compiler capture
with a new nonce, capture-run ID, runtime pointers, and evidence record IDs.
"Not re-keyed" means schema compatibility—the Phase 1 object, PCode, virtual,
and frame record shapes are unchanged inside new combined captures, and
old/new captures coexist in a persistent provenance store.

## 15. Documentation and operational safety

Documentation must state:

- runtime pointers are capture-local provenance only;
- v1 traces lack ownership capability;
- absence is not positive no-owner evidence;
- the probe gate is mandatory before enabling v2 proof;
- the retail backend run is serialized because retrowin32 uses a fixed GDB
  port; and
- regenerated artifacts are immutable inputs to `causal-diff`.

All production analysis remains read-only. Producer commands intentionally
generate trace artifacts only when explicitly invoked; causal analysis itself
never compiles or refreshes artifacts.
