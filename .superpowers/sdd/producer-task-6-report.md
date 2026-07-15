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

The initial implementation found Capstone present in the validation
environment but absent from project metadata. The review remediation below
resolves that packaging concern with an explicit bounded dependency while
retaining fail-closed runtime handling.

## Review remediation

The Task 6 review was addressed in a second strict RED/GREEN cycle. The first
adversarial selection reproduced 33 failures with 11 already-safe cases. The
new tests prove the following corrections:

1. Every raw rewrite and mutation row is closed-shape validated and its event
   sequence is checked as an exact non-boolean integer before event merging.
   Coverage and cap accounting use all raw rows, including malformed rows.
2. Emission now participates in chronological shared-event replay. It freezes
   complete PCode state, lineage parents, and allocator origins at the exact
   emission sequence. A later rewrite cannot retroactively prove an earlier
   anchor, and a final state changed after emission is rejected.
3. The machine decoder now uses Capstone only to parse the instruction and raw
   operands. A closed PowerPC semantic inventory supplies roles. REG operands
   and MEM bases are flattened into deterministic positions; RA=0 is omitted;
   update bases are `use-def`; indexed GPR/FPR, arithmetic, compare, branch,
   special-register moves, and Gekko paired-single D forms are covered.
   Unknown semantic forms and `lmw`/`stmw` reject the complete range. Missing
   or extra flattened mappings are rejected. `capstone>=5,<6` is now a declared
   melee-agent dependency.
4. Register classes are closed to `(0, gpr, r)` and `(1, fpr, f)`. Every
   serialized or decoded physical register is constrained to `0..31` before an
   anchor can be constructed.
5. Coverage counts, bounds, caps, drops, and top-level collection counters use
   exact non-boolean RFC 8785-safe integers. Equal booleans/floats cannot pass
   Python numeric equality.
6. Candidate objects must be ELF32, big-endian, `EM_PPC`, and `ET_REL`; the
   function must resolve uniquely to a positive-size defined `STT_FUNC` in an
   executable `SHT_PROGBITS` section with an in-bounds extent.
7. Mutation inputs use a closed operand shape that forbids
   `parent_lineage_ids`; only fresh output definitions may serialize parents.
8. The five negative JSON fixtures are now standalone invalid payloads loaded
   directly by the parametrized validator test. Decoder tests extend beyond
   ADDI through immediate, indexed, floating, update, special, memory-base,
   paired-single, unsupported, and ambiguous cases.

The focused suite now contains 101 tests. The optional C901 audit improved
from 14 flagged helpers to 12 after extracting ELF validation/relocation
parsing and PowerPC semantic/operand decoding helpers. No complexity warning
is suppressed. Remaining reports are concentrated in the deliberately closed
schema, transition, range, and coverage validators; default project Ruff is
clean.

The decoder dependency concern recorded above is resolved by the explicit
project dependency. Runtime import still fails closed if an installation is
broken rather than emitting heuristic evidence.

Final post-review verification:

```text
python -m pytest \
  tests/test_retro_backend_pcode_lineage.py \
  tests/test_retro_backend_instrumentation_proof.py \
  tests/test_retro_struct_map.py \
  tests/test_retro_backend_object_bindings.py \
  tests/test_retro_backend_identity.py \
  tests/test_causal_diff_bundles.py -q -o addopts=''
383 passed
```

`ruff format --check`, default `ruff check`, and `git diff --check` pass. The
explicit optional C901 audit reports the 12 unsuppressed helpers summarized
above and no longer reports the ELF or decoder helpers refactored during this
review cycle.

## Final blocker remediation

The final review blockers were resolved in a third focused RED/GREEN cycle.
Before implementation, the new adversarial selection produced 18 failures with
107 existing tests passing. The completed suite now proves these additional
gates:

1. Emission makes a `pcode_id` terminal in the shared chronological replay.
   Every later rewrite or mutation input/output touching that ID is rejected,
   including no-op updates, deletion, replacement output, and delete/recreate
   sequences. A control case confirms that a different, not-yet-emitted PCode
   may continue to evolve.
2. Lifecycle position is observation time, not PCode state identity. Mutation
   inputs share one pre-position, outputs share one post-position, pre cannot
   exceed post, every state must be active at its side's position, and create
   or delete takes its interval from the existing side. Rewrite and emission
   are point events, and every shared event starts at or after the prior event's
   end. Tests cover later observations of unchanged state, clone atomicity,
   create/delete one-sided intervals, rewrite/emission ordering, and generation
   reuse after free.
3. Raw PowerPC update-form legality is checked before semantic-role inference.
   Every update form requires nonzero `RA`; integer D/X update loads additionally
   require `RT != RA`. Exact negative controls cover `lwzu`, `lwzux`, `lbzux`,
   and `lhzux`, while legal controls include `stwu r1, displacement(r1)`.

Final focused and adjacent verification:

```text
python -m pytest \
  tests/test_retro_backend_pcode_lineage.py \
  tests/test_retro_backend_instrumentation_proof.py \
  tests/test_retro_struct_map.py \
  tests/test_retro_backend_object_bindings.py \
  tests/test_retro_backend_identity.py \
  tests/test_causal_diff_bundles.py -q -o addopts=''
409 passed
```

`ruff format --check`, default `ruff check`, and `git diff --check` pass. The
optional C901 audit remains informational at the same 12 unsuppressed helpers;
no complexity warning was suppressed.

## Lifecycle anchor remediation

The remaining lifecycle-binding review issue was resolved with a fourth
focused RED/GREEN cycle. Before implementation, the new probes produced eight
failures with 132 tests passing. They demonstrated that chronological event
ordering alone did not bind events back to a PCode's first-observed snapshot,
and that lifecycle-free semantic equality correctly allowed observational
timestamps to drift unless checked separately.

The validator now maintains PCode-local first-observed lifecycle bounds for
allocator-input snapshots and rejects every touching rewrite, mutation, or
emission whose event interval begins before that PCode's bound. A later bound
on an unrelated PCode does not constrain earlier events for another PCode.
When clone, create, or replace first defines a mutation-output PCode, its
first snapshot must occur exactly at the defining mutation's output
post-position. Every code-emission snapshot must likewise occur exactly at its
emission event's lifecycle position. Lifecycle position remains excluded from
persistent semantic-state equality.

The focused suite now contains 140 tests. Final focused and adjacent
verification reports:

```text
python -m pytest \
  tests/test_retro_backend_pcode_lineage.py \
  tests/test_retro_backend_instrumentation_proof.py \
  tests/test_retro_struct_map.py \
  tests/test_retro_backend_object_bindings.py \
  tests/test_retro_backend_identity.py \
  tests/test_causal_diff_bundles.py -q -o addopts=''
422 passed
```

`ruff format --check`, default `ruff check`, and `git diff --check` pass. The
optional C901 audit remains informational at 12 unsuppressed helpers.
