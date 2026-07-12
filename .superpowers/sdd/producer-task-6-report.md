# Producer Task 6 Report

## Scope

Implemented only the pure same-run PCode lineage and candidate-object validator:

- `tools/mwcc_retro/backend_pcode_lineage.py`
- `tools/melee-agent/tests/test_retro_backend_pcode_lineage.py`
- `tools/melee-agent/tests/fixtures/retro/pcode_lineage/`

No retail hook, probe, struct-map promotion, trace assembly, bundle integration,
adapter, or causal-inference file was changed. Those remain Tasks 7–9.

## Capability audit and reuse

Ran:

```text
melee-agent capabilities search "same-run PCode operand lineage candidate ELF validation"
```

The audit found the existing `debug retro backend-candidate` and
`debug retro probe-backend-pcode` workflows, but no existing pure lineage
validator or target operand decoder. The implementation reuses:

- `InstrumentationProof`, its canonical digest, and its closed proof validator;
- the lifecycle replay conventions established by `backend_object_bindings`;
- pyelftools for ELF symbols, sections, and relocation tables; and
- host-side Capstone for explicit PowerPC GPR/FPR operand decoding, with a
  controlled fail-closed result when the decoder is unavailable.

## TDD record

RED 1 established the missing public module:

```text
python -m pytest tests/test_retro_backend_pcode_lineage.py -q
ModuleNotFoundError: No module named 'tools.mwcc_retro.backend_pcode_lineage'
```

After the public frozen dataclasses and closed stub were added, collection
succeeded and exposed 37 behavioral failures with 6 contract tests passing.
Implementation then proceeded in small RED/GREEN patches. Two later focused
RED cases caught and drove fixes for:

- fixed-physical emitted operands incorrectly requiring allocator ancestry;
- deleted/non-emitted PCode records retaining claimed code ranges.

The final focused suite contains 50 tests. It covers immutable normalization;
non-boolean safe integer fields; float, surrogate, recursion, and mutable-input
attacks; trusted site/opcode/rule lookup; allocation-generation replay; stable
initial and fresh lineage IDs; update/reorder, clone-with-surviving-input,
disjoint replace, delete, and create; complete state accounting; rewrite and
emission cardinality; unique ancestry; fixed operands; recomputed coverage,
caps, drops, and truncation; ELF symbol extent, bytes, overlap, and relocation
tuples; decoded machine operand roles, ordinals, lineage/index mappings, and
physical-register agreement; and controlled malformed input handling.

## Implementation summary

The validator returns only deeply immutable `PCodeLineageValidation` data.
Capability is all-or-nothing: any schema, proof, replay, coverage, ELF, decode,
mapping, or ancestry error returns no `pcode-to-code-range` capability and no
proof-capable anchor binding, while the immutable normalized input preserves
all rejected alternatives for diagnostics.

The implementation independently recomputes deterministic PCode/lineage IDs,
active generations, the merged contiguous event sequence, current PCode
states, final/emission cardinality, rewrite requirements, unique allocator
origins, coverage counts, cap reach, candidate bytes/relocations, and
operand-scoped anchors `(function-relative offset, machine_operand_key)`.

## Verification

Focused Task 6 tests:

```text
python -m pytest tests/test_retro_backend_pcode_lineage.py -q -o addopts=''
50 passed
```

Adjacent Task 2 proof, Task 4 lifecycle/object, and Task 3 identity/bundle
regressions:

```text
python -m pytest \
  tests/test_retro_backend_instrumentation_proof.py \
  tests/test_retro_struct_map.py \
  tests/test_retro_backend_object_bindings.py \
  tests/test_retro_backend_identity.py \
  tests/test_causal_diff_bundles.py -q -o addopts=''
282 passed
```

Formatting and default lint:

```text
ruff format --check ../mwcc_retro/backend_pcode_lineage.py \
  tests/test_retro_backend_pcode_lineage.py
ruff check ../mwcc_retro/backend_pcode_lineage.py \
  tests/test_retro_backend_pcode_lineage.py
git diff --check
```

## Self-review and concerns

Every capability gate was reviewed against the approved design. Capability is
never inferred from producer `status`; the raw record invariants and counts
must independently agree. Fixed physical operands are validated against the
decoded register and emission inventory but correctly produce no virtual
anchor. Allocatable operands require exactly one rewrite and exactly one
reachable origin. Mutation-output snapshots are tied to exactly one new output,
and unrelated active PCode IDs cannot be overwritten.

The implementation has no Task 7 behavior: it consumes trusted proof and raw
records but does not install hooks, collect runtime data, promote proof tuples,
or modify the GC/1.2.5n registry.

Default project Ruff is clean. An explicit optional `ruff --select C901` audit
reports 14 validator helpers over complexity 10 (the largest are mutation,
range, instruction, and coverage validation). No complexity warning was
suppressed. Splitting the single requested validator into internal modules
would reduce those scores, but was not done here because Task 6 explicitly
scopes the implementation to one production file and the current helpers map
directly to separately tested contract gates.

Capstone is present in the validated environment but is not declared by the
current melee-agent project metadata. The validator therefore imports it only
at decode time and fails closed if absent; changing dependency metadata would
cross the requested Task 6 file boundary. Task 8 integration should confirm
the packaged runtime supplies the target decoder before enabling v2 assembly.
