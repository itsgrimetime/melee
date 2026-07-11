# Causal Object-Binding Producer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generic, strict-evidence retail MWCC producer that connects an assembly operand to its same-run PCode virtual, compiler ObjObject, allocator node, and derived stack home, while using `mnDiagram_DrawFighterHeaders` as the proven pilot.

**Architecture:** Extend the retail one-pass tracer with a versioned, independently promoted instrumentation proof and two capture-local identity systems: allocation generations for ObjObject/PCode instances and explicit lineage for mutable PCode operands. Normalize those facts into `mwcc-retro-backend-trace.v2`, bind them to an immutable candidate object in `causal-frontier-bundle.v2`, and adapt only verified same-run paths into causal evidence. Phase 1 must still abstain at the source-binding gate; Phase 2 remains a later bundle/schema upgrade.

**Tech Stack:** Python 3.11+, pytest, Pydantic, RFC 8785 canonical JSON, pyelftools, GDB Python hooks under retrowin32, Typer CLI, retail MWCC GC/1.2.5n.

## Global Constraints

- Run `melee-agent capabilities search "exact task description"` before adding any new command or tool surface.
- Runtime pointers and virtual/IG numbers are meaningful only inside one `capture_run_id`; never join them across compiler processes or frontiers.
- `causes` remains strict: heuristic, incomplete, ambiguous, truncated, cross-run, or unregistered evidence abstains.
- `mwcc-retro-object-bindings.v1` requires `source_bindings: []` and `source_capture: null`; Phase 1 must end with `source-object-binding-missing` when source ownership is required.
- Existing `causal-frontier-bundle.v1` and `mwcc-retro-backend-trace.v1` inputs remain readable and lack the new ownership capabilities.
- The GC/1.2.5n proof registry is trusted only after an exhaustive static audit and bounded live probes; an embedded proof cannot attest itself.
- The proof path uses retail same-run PCode evidence. Patched-DLL pcdump evidence is diagnostic only.
- The candidate object is immutable input. Causal analysis remains read-only and never compiles or refreshes artifacts.
- All producer collections use the canonical ordering specified in the approved design.
- Every task uses test-driven development and ends with its own focused commit and two-stage review.

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/mwcc_retro/backend_instrumentation_proof.py` | Parse, canonicalize, digest, and validate the promoted GC/1.2.5n instrumentation proof. |
| `tools/mwcc_retro/backend_capture_identity.py` | Finalize and validate capture identities after candidate-object hashing. |
| `tools/mwcc_retro/backend_object_bindings.py` | Normalize and fail-closed validate ObjObject lifecycle, virtual, and frame bindings. |
| `tools/mwcc_retro/backend_pcode_lineage.py` | Replay PCode lifecycle/mutations, validate operand lineage, and resolve operand-scoped object ranges. |
| `tools/mwcc_retro/backend_object_snapshot.py` | Read immutable ObjObject fingerprints from retail memory without calling compiler accessors. |
| `tools/mwcc_retro/backend_pcode_snapshot.py` | Read full validated PCode/PCodeArg inventories instead of opcode-only rows. |
| `tools/mwcc_retro/backend_onepass_trace_hook.py` | Emit lifecycle, rewrite, mutation, emission, object, and coverage events in one retail process. |
| `tools/mwcc_retro/backend_events.py` | Normalize raw v2 events into deterministic producer collections. |
| `tools/mwcc_retro/backend_schema.py` | Dispatch and validate v1/v2 backend payload schemas. |
| `tools/mwcc_retro/backend_trace_assembler.py` | Assemble capture identity, embedded proof, coverage, object bindings, and candidate-object pins. |
| `tools/mwcc_retro/struct_map.py` and `tools/mwcc_retro/tables/gc_125n.json` | Store the independently promoted proof tuple and required layouts/sites. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/models.py` | Define closed v1/v2 bundle and backend-reference models/capabilities. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/bundles.py` | Hash candidate objects and verify all capture/bundle pins. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/object_binding_adapter.py` | Convert verified v2 producer facts into compile-local nodes and edges. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/backend_adapter.py` | Compose existing allocator evidence with the new focused adapter. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/alignment.py` | Resolve the unique bilateral backend owner without weakening source gates. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/effects.py` | Preserve Phase 1 strict abstention and expose backend/frame effect directions diagnostically. |

---

### Task 1: Freeze the Existing Strict-Abstention Pilot Baseline

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/alignment.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/backend_adapter.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/effects.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/frame_adapter.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/graph.py`
- Test: `tools/melee-agent/tests/test_causal_diff_alignment.py`
- Test: `tools/melee-agent/tests/test_causal_diff_backend_adapters.py`
- Test: `tools/melee-agent/tests/test_causal_diff_draw_fighter_headers.py`
- Fixture: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/`

**Interfaces:**
- Consumes: current v1 bundle/adapters and the exact paired/direct regenerated artifacts already present in the worktree.
- Produces: a committed baseline where both frontiers expose exact backend/stack facts but verdict inference deterministically abstains with `source-object-binding-missing`.

- [ ] **Step 1: Add/retain the pilot assertion that Phase 1 cannot claim source ownership**

```python
def test_draw_fighter_headers_exact_artifacts_abstain_without_source_object_binding(tmp_path):
    report = run_pilot(tmp_path)
    assert report.analysis_status is AnalysisStatus.ABSTAINED
    verdict = next(item for item in report.verdicts if item.status is VerdictStatus.ABSTAIN)
    assert verdict.failed_gates == ("gate-9-source-object-binding",)
    assert "source-object-binding-missing" in report.missing_evidence
    allocator = next(row for row in report.effects.allocator_effects if row.operand_key == "def:0")
    assert allocator.expected_phys == 22
    assert {allocator.first_phys, allocator.second_phys} == {20, 22}
    stack = report.effects.stack_effects[0]
    assert stack.expected_offset == 0x44
    assert {stack.first_offset, stack.second_offset} == {0x44, 0x48}
```

- [ ] **Step 2: Run the focused existing-work tests before editing**

Run:

```bash
cd tools/melee-agent
python -m pytest \
  tests/test_causal_diff_alignment.py \
  tests/test_causal_diff_backend_adapters.py \
  tests/test_causal_diff_draw_fighter_headers.py -q
```

Expected: all tests pass. If any fail, use `superpowers:systematic-debugging`; do not alter regenerated artifacts to fit the code.

- [ ] **Step 3: Inspect the preserved diff and remove only accidental or heuristic ownership claims**

The accepted inference shape is:

```python
if not bilateral_source_object_records:
    return Verdict.abstain(
        reason="source-object-binding-missing",
        retained_records=tuple(backend_and_frame_records),
    )
```

Do not add name, ordinal, nearest-source, physical-register, or cross-run virtual fallbacks.

- [ ] **Step 4: Re-run the focused tests**

Run the Step 2 command.

Expected: PASS with the exact pilot abstention reason.

- [ ] **Step 5: Commit the baseline**

```bash
git add \
  tools/melee-agent/src/mwcc_debug/causal_diff/alignment.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/backend_adapter.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/effects.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/frame_adapter.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/graph.py \
  tools/melee-agent/tests/test_causal_diff_alignment.py \
  tools/melee-agent/tests/test_causal_diff_backend_adapters.py \
  tools/melee-agent/tests/test_causal_diff_draw_fighter_headers.py \
  tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers
git commit -m "test: freeze causal differencer abstention pilot"
```

---

### Task 2: Add the Trusted Instrumentation-Proof Registry

**Files:**
- Create: `tools/mwcc_retro/backend_instrumentation_proof.py`
- Modify: `tools/mwcc_retro/struct_map.py`
- Modify: `tools/mwcc_retro/tables/gc_125n.json`
- Test: `tools/melee-agent/tests/test_retro_backend_instrumentation_proof.py`
- Test: `tools/melee-agent/tests/test_retro_struct_map.py`

**Interfaces:**
- Consumes: RFC 8785 canonical JSON and the GC/1.2.5n struct-map table.
- Produces: `InstrumentationProof`, `proof_sha256()`, `validate_embedded_proof()`, and `trusted_proof_from_trace()` used by every later producer/loader task.

- [ ] **Step 1: Write failing proof-registry tests**

```python
def test_embedded_proof_requires_exact_promoted_registry_tuple():
    proof = minimal_instrumentation_proof()
    digest = proof_sha256(proof)
    table = {
        "instrumentation_proofs": [{
            "compiler_executable_sha256": "a" * 64,
            "proof_id": proof["proof_id"],
            "proof_sha256": digest,
            "promoted": True,
        }]
    }
    assert validate_embedded_proof(proof, table, "a" * 64) == ()
    assert validate_embedded_proof(proof, table, "b" * 64) == (
        "instrumentation proof is not independently promoted for this compiler",
    )


def test_proof_rejects_duplicate_sites_and_unsorted_rules():
    proof = minimal_instrumentation_proof()
    proof["allocation_sites"] *= 2
    assert "duplicate allocation site" in "\n".join(validate_proof_shape(proof))
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_instrumentation_proof.py tests/test_retro_struct_map.py -q
```

Expected: FAIL because the module and registry validator do not exist.

- [ ] **Step 3: Implement the focused proof API**

```python
@dataclass(frozen=True)
class InstrumentationProof:
    proof_id: str
    compiler_executable_sha256: str
    payload: Mapping[str, object]
    sha256: str


def proof_sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(rfc8785.dumps(dict(payload))).hexdigest()


def validate_embedded_proof(
    payload: Mapping[str, object],
    struct_map: Mapping[str, object],
    compiler_executable_sha256: str,
) -> tuple[str, ...]:
    errors = list(validate_proof_shape(payload))
    digest = proof_sha256(payload)
    trusted = {
        (row["compiler_executable_sha256"], row["proof_id"], row["proof_sha256"])
        for row in struct_map.get("instrumentation_proofs", [])
        if row.get("promoted") is True
    }
    key = (compiler_executable_sha256, payload.get("proof_id"), digest)
    if key not in trusted:
        errors.append("instrumentation proof is not independently promoted for this compiler")
    return tuple(errors)


def trusted_proof_from_trace(
    trace: Mapping[str, object],
    function: str,
    struct_map: Mapping[str, object] | None = None,
) -> InstrumentationProof:
    table = load_gc125n_struct_map() if struct_map is None else struct_map
    matches = [row for row in trace["functions"] if row["name"] == function]
    if len(matches) != 1:
        raise ValueError(f"expected one function {function!r}, found {len(matches)}")
    object_bindings = matches[0]["object_bindings"]
    payload = object_bindings["lifetime_proof"]
    compiler_sha256 = object_bindings["capture_identity"]["compiler_executable_sha256"]
    errors = validate_embedded_proof(payload, table, compiler_sha256)
    if errors:
        raise ValueError("; ".join(errors))
    return InstrumentationProof(payload["proof_id"], compiler_sha256, payload, proof_sha256(payload))
```

`validate_proof_shape()` must implement the closed fields, canonical ordering, unique address/site IDs, entity-kind/stage vocabularies, opcode table, operand rules, and all four site inventories from the approved spec.

- [ ] **Step 4: Add an unpromoted registry entry shape, not guessed production addresses**

Add `instrumentation_proofs: []` and the required proof-schema/version gate to `gc_125n.json`. Do not set `promoted: true` until Task 7 completes the static audit and live probes.

```json
{
  "instrumentation_proof_schema": "mwcc-retro-lifetime-proof.v1",
  "instrumentation_proofs": []
}
```

- [ ] **Step 5: Run tests and commit**

Run the Step 2 command.

Expected: PASS.

```bash
git add \
  tools/mwcc_retro/backend_instrumentation_proof.py \
  tools/mwcc_retro/struct_map.py \
  tools/mwcc_retro/tables/gc_125n.json \
  tools/melee-agent/tests/test_retro_backend_instrumentation_proof.py \
  tools/melee-agent/tests/test_retro_struct_map.py
git commit -m "feat: validate promoted retail instrumentation proofs"
```

---

### Task 3: Version the Bundle and Bind Capture Identity to Candidate Bytes

**Files:**
- Create: `tools/mwcc_retro/backend_capture_identity.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/models.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/bundles.py`
- Test: `tools/melee-agent/tests/test_retro_backend_identity.py`
- Test: `tools/melee-agent/tests/test_causal_diff_bundles.py`

**Interfaces:**
- Consumes: nonce, compiler/source/command/environment digests, function, and candidate-object bytes.
- Produces: `finalize_capture_identity(...) -> dict[str, str]`, `causal-frontier-bundle.v2`, `backend-trace.v2`, a verified `candidate_object` artifact, `ValidatedBundle.candidate_object_path`, and `ValidatedBundle.backend_paths(format_name)`.

- [ ] **Step 1: Write failing identity and wrong-bundle tests**

```python
def test_capture_identity_is_finalized_after_candidate_hash(tmp_path):
    obj = tmp_path / "candidate.o"
    obj.write_bytes(b"candidate-bytes")
    identity = finalize_capture_identity(
        nonce="1" * 32,
        compiler_executable_sha256="2" * 64,
        source_sha256="3" * 64,
        mwcc_command_sha256="4" * 64,
        environment_digest="5" * 64,
        function="fn",
        candidate_object=obj,
    )
    assert identity["candidate_object_sha256"] == hashlib.sha256(b"candidate-bytes").hexdigest()
    payload = {key: value for key, value in identity.items() if key != "capture_run_id"}
    assert identity["capture_run_id"] == hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


def test_bundle_v2_rejects_candidate_object_digest_mismatch(bundle_v2):
    bundle_v2.candidate_object.write_bytes(b"changed")
    with pytest.raises(BundleInputError, match="candidate object digest mismatch"):
        load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_identity.py tests/test_causal_diff_bundles.py -q
```

Expected: FAIL on missing v2 models and capture finalizer.

- [ ] **Step 3: Implement capture finalization**

```python
def finalize_capture_identity(
    *,
    nonce: str,
    compiler_executable_sha256: str,
    source_sha256: str,
    mwcc_command_sha256: str,
    environment_digest: str,
    function: str,
    candidate_object: Path,
) -> dict[str, str]:
    payload = {
        "nonce": nonce,
        "compiler_executable_sha256": compiler_executable_sha256,
        "source_sha256": source_sha256,
        "mwcc_command_sha256": mwcc_command_sha256,
        "environment_digest": environment_digest,
        "candidate_object_sha256": hashlib.sha256(candidate_object.read_bytes()).hexdigest(),
        "function": function,
    }
    return {**payload, "capture_run_id": hashlib.sha256(rfc8785.dumps(payload)).hexdigest()}
```

- [ ] **Step 4: Add closed v2 Pydantic models and loader verification**

Define separate v1/v2 models. `FrontierBundleManifestV2` requires `candidate_object`; `BackendArtifactRefV2` requires the five identity pins and accepts the new capabilities. `load_bundle()` must dispatch on `schema_version`, hash every artifact, recompute capture identity, compare environment/function/source, and reject `backend-trace.v2` inside a v1 manifest.

```python
class BackendArtifactRefV2(ArtifactRef):
    format: Literal["backend-trace.v2"]
    capabilities: tuple[str, ...]
    capture_identity_sha256: str
    compiler_executable_sha256: str
    mwcc_command_sha256: str
    environment_digest: str
    candidate_object_sha256: str


class ArtifactsManifestV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: ArtifactRef
    checkdiff: ArtifactRef
    backend: tuple[BackendArtifactRef | BackendArtifactRefV2, ...]
    inspector: ArtifactRef
    frame_report: ArtifactRef | None = None
    candidate_object: ArtifactRef
```

Extend the frozen bundle with these accessors:

```python
@property
def candidate_object_path(self) -> Path | None:
    return self.artifact_paths.get("candidate_object")


def backend_paths(self, format_name: str) -> tuple[Path, ...]:
    return tuple(
        self.artifact_paths[f"backend[{index}]"]
        for index, ref in enumerate(self.manifest.artifacts.backend)
        if ref.format == format_name
    )
```

- [ ] **Step 5: Run tests and commit**

Run the Step 2 command plus:

```bash
python -m pytest tests/test_causal_diff_cli.py -q
```

Expected: PASS, including unchanged v1 fixtures.

```bash
git add \
  tools/mwcc_retro/backend_capture_identity.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/models.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/bundles.py \
  tools/melee-agent/tests/test_retro_backend_identity.py \
  tools/melee-agent/tests/test_causal_diff_bundles.py
git commit -m "feat: bind causal bundles to retail candidate objects"
```

---

### Task 4: Validate ObjObject Lifecycle, Virtual, and Frame Bindings

**Files:**
- Create: `tools/mwcc_retro/backend_object_bindings.py`
- Test: `tools/melee-agent/tests/test_retro_backend_object_bindings.py`

**Interfaces:**
- Consumes: `object_bindings` v1 payload plus a trusted `InstrumentationProof`.
- Produces: `ObjectBindingValidation(normalized, capabilities, errors)` with no capability on partial input.

- [ ] **Step 1: Write failing lifecycle and confidence tests**

```python
def test_replay_requires_generation_active_at_both_snapshots():
    payload = minimal_object_bindings()
    payload["lifecycle_events"] = [
        lifecycle(0, "allocate", "objobject", 0x1000, 1),
        lifecycle(1, "free", "objobject", 0x1000, 1),
        lifecycle(2, "allocate", "objobject", 0x1000, 2),
    ]
    payload["objects"][0]["stage_snapshots"][1]["lifecycle_sequence_at_capture"] = 2
    result = validate_object_bindings(payload, trusted_proof())
    assert any("snapshot generation is not active" in error for error in result.errors)
    assert result.capabilities == frozenset()


def test_frame_home_is_derived_unique_not_observed():
    result = validate_object_bindings(minimal_object_bindings(), trusted_proof())
    assert result.normalized["frame_bindings"][0]["confidence"] == "derived-unique"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_object_bindings.py -q
```

Expected: FAIL because the validator does not exist.

- [ ] **Step 3: Implement the pure validation result and replay**

```python
@dataclass(frozen=True)
class ObjectBindingValidation:
    normalized: Mapping[str, object]
    capabilities: frozenset[str]
    errors: tuple[str, ...]


def validate_object_bindings(
    payload: Mapping[str, object],
    proof: InstrumentationProof,
) -> ObjectBindingValidation:
    errors = validate_closed_object_binding_shape(payload)
    lifecycle = replay_lifecycle(payload.get("lifecycle_events", []), proof)
    errors.extend(lifecycle.errors)
    normalized = normalize_objects_virtuals_and_frames(payload, lifecycle, errors)
    capabilities = frozenset() if errors else verified_object_capabilities(normalized)
    return ObjectBindingValidation(MappingProxyType(dict(normalized)), capabilities, tuple(errors))
```

Implement every spec invariant: capture-local generations, one/two object snapshots, fingerprint consistency, deterministic IDs, one-to-many virtuals, spill-only objects, frame-list coverage, derived `r1` offsets, reserved Phase 2 fields, canonical arrays, caps/drops/errors, and empty-capture capability semantics.

- [ ] **Step 4: Add negative matrices**

Cover cross-run pointer equality, same-address different generation, missing/free-before-snapshot, fingerprint changes, frame-only/allocator-only records, duplicate bindings, spill objects with fabricated homes, source fields populated in v1, partial coverage, and producer-declared false completeness.

```python
def reuse_address_with_new_generation(payload):
    payload["objects"][0]["stage_snapshots"][1]["allocation_generation"] += 1


def change_cross_stage_type_pointer(payload):
    payload["objects"][0]["stage_snapshots"][1]["type_pointer"] += 4


def invent_spill_frame_home(payload):
    payload["objects"][0]["areas"] = ["spill-owned"]


def populate_source_capture(payload):
    payload["source_capture"] = {"schema_version": "invalid"}


def drop_lifecycle_event(payload):
    payload["lifecycle_events"].pop(0)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (reuse_address_with_new_generation, "snapshot generation is not active"),
        (change_cross_stage_type_pointer, "object fingerprint changed"),
        (invent_spill_frame_home, "spill-owned object cannot have frame binding"),
        (populate_source_capture, "source_capture must be null in v1"),
        (drop_lifecycle_event, "lifecycle sequence gap"),
    ],
)
def test_object_binding_fail_closed_matrix(mutation, message):
    payload = minimal_object_bindings()
    mutation(payload)
    errors = validate_object_bindings(payload, trusted_proof()).errors
    assert any(message in error for error in errors)
```

- [ ] **Step 5: Run tests and commit**

Run the Step 2 command.

Expected: PASS.

```bash
git add tools/mwcc_retro/backend_object_bindings.py tools/melee-agent/tests/test_retro_backend_object_bindings.py
git commit -m "feat: validate retail object ownership records"
```

---

### Task 5: Capture ObjObject Identity at Allocator and Frame Stages

**Files:**
- Create: `tools/mwcc_retro/backend_object_snapshot.py`
- Modify: `tools/mwcc_retro/backend_ig_snapshot.py`
- Modify: `tools/mwcc_retro/backend_frame_state.py`
- Modify: `tools/mwcc_retro/backend_onepass_trace_hook.py`
- Test: `tools/melee-agent/tests/test_retro_backend_object_snapshot.py`
- Test: `tools/melee-agent/tests/test_retro_backend_ig_snapshot.py`
- Test: `tools/melee-agent/tests/test_retro_backend_frame_state.py`

**Interfaces:**
- Consumes: validated struct-map offsets, lifecycle generation lookup, stopped GDB memory readers.
- Produces: observed allocator-stage ObjObject snapshots, `object_virtual_binding` events, final frame snapshots, and raw frame bindings.

- [ ] **Step 1: Write failing raw-pointer retention tests**

```python
def test_ig_node_emits_observed_objobject_binding(fake_memory):
    events = snapshot_interference_graph(**fake_memory.ig_with_obj_addr(0x1200))
    node = next(event for event in events if event["event"] == "node")
    assert node["objobject_ptr"] == 0x1200
    assert node["object_binding_confidence"] == "observed"


def test_frame_row_retains_raw_object_pointer_and_stack_inputs(fake_memory):
    frame = snapshot_frame_state(**fake_memory.frame_object(0x1200, stack_offset=-12))
    row = frame["areas"]["locals"][0]
    assert row["objobject_ptr"] == 0x1200
    assert row["raw_object_stack_offset"] == -12
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd tools/melee-agent
python -m pytest \
  tests/test_retro_backend_object_snapshot.py \
  tests/test_retro_backend_ig_snapshot.py \
  tests/test_retro_backend_frame_state.py -q
```

Expected: FAIL because normalized readers discard the pointers.

- [ ] **Step 3: Implement one immutable object snapshot reader**

```python
def snapshot_objobject(
    *,
    ptr: int,
    stage: str,
    lifecycle_sequence: int,
    generation: int,
    read_u32: ReadU32,
    read_s32: ReadS32,
    offsets: ObjObjectOffsets,
) -> dict[str, object]:
    return {
        "stage": stage,
        "runtime_address": ptr,
        "allocation_generation": generation,
        "lifecycle_sequence_at_capture": lifecycle_sequence,
        "name_record_pointer": read_u32(ptr + offsets.name_record),
        "type_pointer": read_u32(ptr + offsets.type_pointer),
        "type_size": read_s32(read_u32(ptr + offsets.type_pointer) + offsets.type_size),
        "readable": True,
    }
```

Do not call backend accessor `0x4C1720` or any compiler function.

- [ ] **Step 4: Thread snapshots through IG/frame capture and hook state**

Read `IGNode.obj_addr @ +0x04`; retain all positive mappings, including spill-owned objects absent from frame lists. Frame capture retains list node, object pointer, raw object offset, base size, and call-argument size. Emit positive raw facts even on partial coverage, but mark capabilities absent.

```python
events.append({
    "event": "object_virtual_binding",
    "source_stage": "colorgraph_return",
    "objobject_ptr": objobject_ptr,
    "allocation_generation": lifecycle.generation("objobject", objobject_ptr),
    "class_id": class_id,
    "virtual_kind": virtual_kind,
    "virtual": virtual,
    "ig_id": ig_id,
    "confidence": "observed",
})
```

- [ ] **Step 5: Run tests and commit**

Run the Step 2 command.

Expected: PASS.

```bash
git add \
  tools/mwcc_retro/backend_object_snapshot.py \
  tools/mwcc_retro/backend_ig_snapshot.py \
  tools/mwcc_retro/backend_frame_state.py \
  tools/mwcc_retro/backend_onepass_trace_hook.py \
  tools/melee-agent/tests/test_retro_backend_object_snapshot.py \
  tools/melee-agent/tests/test_retro_backend_ig_snapshot.py \
  tools/melee-agent/tests/test_retro_backend_frame_state.py
git commit -m "feat: capture retail object allocator and frame identity"
```

---

### Task 6: Implement Pure PCode Lineage and Candidate-Object Validation

**Files:**
- Create: `tools/mwcc_retro/backend_pcode_lineage.py`
- Test: `tools/melee-agent/tests/test_retro_backend_pcode_lineage.py`
- Fixture: `tools/melee-agent/tests/fixtures/retro/pcode_lineage/`

**Interfaces:**
- Consumes: normalized lifecycle events, trusted opcode/operand/site proof, raw PCode snapshots/rewrite/mutation/emission records, candidate object, and function name.
- Produces: `PCodeLineageValidation(normalized, anchor_bindings, capabilities, errors)`.

- [ ] **Step 1: Write failing replay and operand-scoped anchor tests**

```python
def test_reorder_preserves_lineage_but_not_operand_index(candidate_object):
    payload = pcode_payload_with_reorder(
        virtual=66,
        original_index=1,
        emitted_index=0,
        machine_key="use:0",
    )
    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")
    binding = result.anchor_bindings[(0x234, "use:0")]
    assert binding.virtual == 66
    assert binding.confidence == "derived-unique"


def test_multi_parent_lineage_abstains(candidate_object):
    result = validate_pcode_lineage(
        pcode_payload_with_derived_lineage(parents=("ol-1", "ol-2")),
        trusted_proof(),
        candidate_object,
        "fn",
    )
    assert any("multiple allocator origins" in error for error in result.errors)
    assert "pcode-to-code-range" not in result.capabilities
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_pcode_lineage.py -q
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the immutable result and event replay**

```python
@dataclass(frozen=True)
class AnchorVirtualBinding:
    code_offset: int
    machine_operand_key: str
    pcode_id: str
    operand_lineage_id: str
    class_id: int
    virtual: int
    physical_register: int
    confidence: str


@dataclass(frozen=True)
class PCodeLineageValidation:
    normalized: Mapping[str, object]
    anchor_bindings: Mapping[tuple[int, str], AnchorVirtualBinding]
    capabilities: frozenset[str]
    errors: tuple[str, ...]
```

Replay the shared PCode event sequence. Enforce trusted site inventories, active allocation generations, exact update/clone/replace/delete/create shapes, stable lineage reuse, deterministic fresh IDs, complete input/output states, opcode/operand rules, exactly one rewrite per allocatable operand, no rewrite for fixed operands, one emission per final PCode, and unique ancestry.

- [ ] **Step 4: Parse candidate ELF ranges and relocations with pyelftools**

```python
def load_function_object_view(path: Path, function: str) -> FunctionObjectView:
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        symbol = unique_defined_function_symbol(elf, function)
        section = elf.get_section(symbol["st_shndx"])
        start = int(symbol["st_value"])
        size = int(symbol["st_size"])
        if size <= 0:
            raise ValueError("function symbol has no positive extent")
        return FunctionObjectView(section.name, start, size, bytes(section.data()), relocations_for(elf, section))
```

Validate half-open function-relative ranges, raw bytes, exact relocation tuples, decoded PowerPC register operands, role ordinals, physical registers, and one machine mapping per decoded register operand.

- [ ] **Step 5: Add the full negative matrix**

Test pointer reuse, lifecycle mismatch, missing/misclassified rewrite, bad mutation cardinality, self-parent/fresh clone IDs, duplicate outputs, missing emission, ambiguous symbol, zero symbol size, overlapping/out-of-range bytes, relocation mismatch, opcode-name mismatch, wrong machine operand key/index/register, drops/caps, and producer-declared completeness.

```python
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "retro" / "pcode_lineage"

INVALID_CASES = (
    ("self_parent.json", "self-parented lineage"),
    ("fresh_clone_id.json", "clone may not define fresh lineage"),
    ("duplicate_output.json", "duplicate output pcode_id"),
    ("missing_emission.json", "final PCode has no emission event"),
    ("wrong_machine_register.json", "decoded physical register mismatch"),
)


@pytest.mark.parametrize(("fixture_name", "message"), INVALID_CASES)
def test_invalid_lineage_fixtures_fail_closed(fixture_name, message, candidate_object):
    payload = json.loads((FIXTURE_ROOT / fixture_name).read_text())
    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")
    assert any(message in error for error in result.errors)
    assert result.capabilities == frozenset()
```

- [ ] **Step 6: Run tests and commit**

Run the Step 2 command.

Expected: PASS.

```bash
git add \
  tools/mwcc_retro/backend_pcode_lineage.py \
  tools/melee-agent/tests/test_retro_backend_pcode_lineage.py \
  tools/melee-agent/tests/fixtures/retro/pcode_lineage
git commit -m "feat: validate same-run retail pcode lineage"
```

---

### Task 7: Instrument the Retail PCode Lifecycle and Promote the Proof Gate

**Files:**
- Modify: `tools/mwcc_retro/backend_pcode_snapshot.py`
- Modify: `tools/mwcc_retro/backend_onepass_trace_hook.py`
- Modify: `tools/mwcc_retro/backend_map_probe_hook.py`
- Modify: `tools/mwcc_retro/struct_map.py`
- Modify: `tools/mwcc_retro/tables/gc_125n.json`
- Test: `tools/melee-agent/tests/test_retro_backend_pcode_snapshot.py`
- Test: `tools/melee-agent/tests/test_retro_backend_runtime.py`
- Test: `tools/melee-agent/tests/test_retro_backend_map_evidence.py`

**Interfaces:**
- Consumes: the Task 2 proof schema and Task 6 raw event contract.
- Produces: same-run PCodeArg inventories plus site-tagged lifecycle/rewrite/mutation/emission events; a promoted registry tuple only if static and live gates pass.

- [ ] **Step 1: Write failing structured-PCode and coverage tests**

```python
def test_snapshot_pcode_emits_full_arg_inventory(fake_memory):
    events = snapshot_pcode_blocks(**fake_memory.addi_with_virtual_args())
    row = next(event for event in events if event["event"] == "pcode_instruction")
    assert row["opcode_id"] == fake_memory.ADDI_OPCODE
    assert row["arg_count"] == 3
    assert row["operand_lineage_inventory"][1]["raw_arg_kind_id"] == fake_memory.VREG_ARG_KIND


def test_runtime_drops_capability_when_mutation_site_is_unhooked(runtime_payload):
    runtime_payload["coverage"]["pcode_instrumentation"]["operand_mutation_sites_hooked"] -= 1
    assert "pcode-to-code-range" not in verified_capabilities(runtime_payload)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd tools/melee-agent
python -m pytest \
  tests/test_retro_backend_pcode_snapshot.py \
  tests/test_retro_backend_runtime.py \
  tests/test_retro_backend_map_evidence.py -q
```

Expected: FAIL because PCode operands and hook coverage are not emitted.

- [ ] **Step 3: Implement full PCode/PCodeArg reads and event helpers**

Use only promoted offsets. Every event includes raw PCode address, allocation generation, lifecycle position, proof site ID, and the appropriate event sequence. Capture the allocator-input state before mutation, record virtual/physical rewrite facts before replacement, emit full mutation input/output states atomically, and record exact code-emission ranges/machine mappings.

```python
def emit_pcode_event(state, event, *, site_id, pcode_ptr):
    event = {
        **event,
        "pcode_event_sequence": state["next_pcode_event_sequence"],
        "instrumented_site_id": site_id,
        "runtime_address": pcode_ptr,
        "allocation_generation": state["lifecycle"].generation("pcode", pcode_ptr),
        "lifecycle_sequence_at_capture": state["lifecycle"].last_sequence,
    }
    state["next_pcode_event_sequence"] += 1
    append_event(event)
```

- [ ] **Step 4: Extend the existing probe command instead of adding a new CLI**

Run the audit-first check:

```bash
melee-agent capabilities search "retail pcode operand lifecycle mutation emission proof"
```

Then extend `debug retro probe-backend-map` output with bounded site/layout evidence. The command must report `unpromoted` until every required field/site is validated.

- [ ] **Step 5: Perform the compiler-specific static audit and bounded live probes**

Static audit must enumerate every ObjObject/PCode allocate/free site, allocator rewrite site, operand mutation site, emission site, opcode mnemonic, and operand rule. Run:

```bash
cd tools/melee-agent
python -m src.cli debug retro probe-backend-map \
  ../../src/melee/mn/mndiagram.c \
  --function mnDiagram_DrawFighterHeaders
```

Also run the probe on one small named-local function, one address-taken/multi-virtual local, and one FPR/spill case selected from existing test fixtures. Expected: all required layouts/sites are observed, event sequences are gap-free, candidate ranges match, and the command prints the exact proof digest.

If any exhaustive-site claim cannot be proven, leave the registry unpromoted, record the exact missing site/layout in the shared issue queue, and stop this task as a strict feasibility blocker. Do not weaken the validator.

- [ ] **Step 6: Promote only the exact audited tuple and rerun tests**

Add one `promoted: true` tuple keyed by compiler executable SHA-256, proof ID, and proof SHA-256. Re-run the Step 2 command.

Expected: PASS; altered executable/proof/site inventories fail closed.

- [ ] **Step 7: Commit**

```bash
git add \
  tools/mwcc_retro/backend_pcode_snapshot.py \
  tools/mwcc_retro/backend_onepass_trace_hook.py \
  tools/mwcc_retro/backend_map_probe_hook.py \
  tools/mwcc_retro/struct_map.py \
  tools/mwcc_retro/tables/gc_125n.json \
  tools/melee-agent/tests/test_retro_backend_pcode_snapshot.py \
  tools/melee-agent/tests/test_retro_backend_runtime.py \
  tools/melee-agent/tests/test_retro_backend_map_evidence.py
git commit -m "feat: trace retail pcode operand provenance"
```

---

### Task 8: Assemble and Validate Backend Trace v2 Through the CLI

**Files:**
- Modify: `tools/mwcc_retro/backend_events.py`
- Modify: `tools/mwcc_retro/backend_schema.py`
- Modify: `tools/mwcc_retro/backend_trace_assembler.py`
- Modify: `tools/melee-agent/src/cli/debug/retro.py`
- Modify: `tools/mwcc_retro/README.md`
- Test: `tools/melee-agent/tests/test_retro_backend_events.py`
- Test: `tools/melee-agent/tests/test_retro_backend_schema.py`
- Test: `tools/melee-agent/tests/test_retro_backend_trace_assembler.py`
- Test: `tools/melee-agent/tests/test_retro_backend_cli.py`

**Interfaces:**
- Consumes: raw v2 events, trusted proof, candidate object, compile identity inputs, and Task 4/6 validators.
- Produces: deterministic `backend-trace.v2.json`, candidate object artifact, verified capability list, and strict summary/exit behavior.

- [ ] **Step 1: Write failing v2 normalization and CLI tests**

```python
def test_v2_event_order_is_canonical(raw_v2_events):
    forward = normalize_events(raw_v2_events, schema_version="mwcc-retro-backend-trace.v2")
    reverse = normalize_events(list(reversed(raw_v2_events)), schema_version="mwcc-retro-backend-trace.v2")
    assert rfc8785.dumps(forward) == rfc8785.dumps(reverse)


def test_cli_emits_candidate_object_and_v2_trace(retro_runner):
    result = retro_runner.backend_v2("mnDiagram_DrawFighterHeaders")
    assert result.trace.name == "backend-trace.v2.json"
    assert result.candidate_object.read_bytes()
    assert result.payload["schema_version"] == "mwcc-retro-backend-trace.v2"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd tools/melee-agent
python -m pytest \
  tests/test_retro_backend_events.py \
  tests/test_retro_backend_schema.py \
  tests/test_retro_backend_trace_assembler.py \
  tests/test_retro_backend_cli.py -q
```

Expected: FAIL because only v1 assembly exists.

- [ ] **Step 3: Add explicit v1/v2 dispatch and deterministic normalization**

Keep `SCHEMA_VERSION_V1` and add `SCHEMA_VERSION_V2`. V2 normalization collects lifecycle, proof, object, PCode, lineage, rewrite, emission, and coverage events; sorts each collection by the approved keys; calls both pure validators; and emits only the capabilities returned by them.

```python
SCHEMA_VERSION_V1 = "mwcc-retro-backend-trace.v1"
SCHEMA_VERSION_V2 = "mwcc-retro-backend-trace.v2"


def validate_backend_trace(payload: dict[str, Any]) -> list[str]:
    version = payload.get("schema_version")
    if version == SCHEMA_VERSION_V1:
        return validate_backend_trace_v1(payload)
    if version == SCHEMA_VERSION_V2:
        return validate_backend_trace_v2(payload)
    return [f"unsupported backend trace schema {version!r}"]
```

- [ ] **Step 4: Assemble identity only after candidate-object finalization**

The CLI creates the nonce at process entry, runs the serialized retail trace, persists the candidate object, hashes it, finalizes capture identity, embeds the trusted proof, validates the completed payload, and then writes artifacts. A validation error removes no existing artifact and exits nonzero with the exact failing gate.

```python
identity = finalize_capture_identity(
    nonce=nonce,
    compiler_executable_sha256=compiler_sha256,
    source_sha256=source_sha256,
    mwcc_command_sha256=command_sha256,
    environment_digest=environment_digest,
    function=function,
    candidate_object=candidate_object_path,
)
payload = assemble_candidate_trace(events, capture_identity=identity, lifetime_proof=proof)
errors = validate_backend_trace(payload)
if errors:
    raise RuntimeError("backend trace v2 failed validation: " + "; ".join(errors))
write_backend_trace(trace_path, payload)
```

- [ ] **Step 5: Document v1/v2 commands and abstention semantics**

Document artifact names, fixed-port serialization, candidate-object immutability, proof promotion, same-run virtual rules, and Phase 1 source abstention.

```markdown
`backend-trace.v2.json` is proof-capable only when its embedded proof matches the
promoted GC/1.2.5n registry tuple. Virtual and pointer identities never cross
compiler processes. Missing source-object evidence remains a strict Phase 1
abstention.
```

- [ ] **Step 6: Run tests and commit**

Run the Step 2 command.

Expected: PASS, including v1 regression tests.

```bash
git add \
  tools/mwcc_retro/backend_events.py \
  tools/mwcc_retro/backend_schema.py \
  tools/mwcc_retro/backend_trace_assembler.py \
  tools/melee-agent/src/cli/debug/retro.py \
  tools/mwcc_retro/README.md \
  tools/melee-agent/tests/test_retro_backend_events.py \
  tools/melee-agent/tests/test_retro_backend_schema.py \
  tools/melee-agent/tests/test_retro_backend_trace_assembler.py \
  tools/melee-agent/tests/test_retro_backend_cli.py
git commit -m "feat: emit retail backend trace v2"
```

---

### Task 9: Adapt Verified Object/PCode Evidence Into the Causal Graph

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/object_binding_adapter.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/backend_adapter.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/alignment.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/effects.py`
- Test: `tools/melee-agent/tests/test_causal_diff_object_bindings.py`
- Test: `tools/melee-agent/tests/test_causal_diff_ownership.py`
- Test: `tools/melee-agent/tests/test_causal_diff_inference.py`

**Interfaces:**
- Consumes: a validated v2 bundle, `ObjectBindingValidation`, `PCodeLineageValidation`, and existing allocator/checkdiff evidence.
- Produces: compile-local `retail-pcode`, `compiler-object`, operand-scoped anchor, lineage, virtual, allocator, and stack-home records; an analysis-scoped `backend-owner-corresponds-to` comparison; `resolve_backend_owner_candidates()`, `proof_complete()`, `bilateral_source_object_records()`, `derive_backend_frame_recommendation()`, and verified gate-9 abstention.

- [ ] **Step 1: Write failing same-run edge and cross-run rejection tests**

```python
def test_adapter_emits_operand_scoped_same_run_path(validated_v2_bundle):
    evidence = adapt_object_bindings(validated_v2_bundle)
    edge_kinds = {edge.kind for edge in evidence.edges}
    assert {
        "assembly-anchor-emitted-by-pcode",
        "pcode-operand-lineage",
        "pcode-operand-uses-virtual",
        "object-materializes-virtual",
        "object-has-stack-home",
    } <= edge_kinds
    assert all(edge.confidence is not Confidence.HEURISTIC for edge in evidence.edges)


def test_adapter_rejects_matching_debug_dll_virtual(validated_v2_bundle):
    evidence = adapt_object_bindings(validated_v2_bundle)
    assert not any(
        edge.kind == "pcode-operand-uses-virtual"
        and edge.provenance.parser == "mwcc-debug-pcdump"
        for edge in evidence.edges
    )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd tools/melee-agent
python -m pytest \
  tests/test_causal_diff_object_bindings.py \
  tests/test_causal_diff_ownership.py \
  tests/test_causal_diff_inference.py -q
```

Expected: FAIL because the focused adapter does not exist.

- [ ] **Step 3: Implement the focused adapter**

```python
@dataclass(frozen=True)
class ObjectBindingEvidence:
    nodes: tuple[EvidenceNode, ...]
    edges: tuple[EvidenceEdge, ...]
    capabilities: frozenset[str]


def adapt_object_bindings(bundle: ValidatedBundle) -> ObjectBindingEvidence:
    trace_paths = bundle.backend_paths("backend-trace.v2")
    if len(trace_paths) != 1 or bundle.candidate_object_path is None:
        return ObjectBindingEvidence((), (), frozenset())
    trace = load_backend_trace(trace_paths[0])
    rows = [row for row in trace["functions"] if row["name"] == bundle.manifest.function]
    if len(rows) != 1:
        return ObjectBindingEvidence((), (), frozenset())
    object_bindings = rows[0]["object_bindings"]
    proof = trusted_proof_from_trace(trace, bundle.manifest.function)
    object_result = validate_object_bindings(object_bindings, proof)
    pcode_result = validate_pcode_lineage(
        object_bindings, proof, bundle.candidate_object_path, bundle.manifest.function
    )
    if object_result.errors or pcode_result.errors:
        return ObjectBindingEvidence((), (), frozenset())
    return emit_compile_local_evidence(bundle, object_result, pcode_result)
```

Every stable record ID includes compile ID, capture-run ID, local object/PCode/lineage ID, and event kind. Runtime pointers remain attributes only. The stack-home edge is `derived-unique`; rewrite/mutation raw records retain observed confidence; unique traversal is `derived-unique`.

- [ ] **Step 4: Integrate bilateral owner alignment without weakening source gates**

Resolve each frontier's unique backend owner using the approved role tuple. Require positive same-run paths on both sides, preserve every alternative, and keep `gate-9-source-object-binding` mandatory. Phase 1 may expose the preserve-allocation/shorten-stack diagnostic direction but verdict remains `abstain/source-object-binding-missing`.

```python
owners = resolve_backend_owner_candidates(first_records, second_records, role_tuple)
if len(owners) != 1:
    return abstain("backend-owner-ambiguous", alternatives=owners)
if not proof_complete(owners[0]):
    return abstain("backend-owner-path-incomplete", alternatives=owners)
if not bilateral_source_object_records(owners[0]):
    return abstain(
        "source-object-binding-missing",
        recommendation=derive_backend_frame_recommendation(owners[0]),
        retained_records=owners[0].supporting_records,
    )
```

- [ ] **Step 5: Run tests and commit**

Run the Step 2 command plus all causal-diff tests:

```bash
python -m pytest tests/test_causal_diff_*.py -q
```

Expected: PASS.

```bash
git add \
  tools/melee-agent/src/mwcc_debug/causal_diff/object_binding_adapter.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/backend_adapter.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/alignment.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/effects.py \
  tools/melee-agent/tests/test_causal_diff_object_bindings.py \
  tools/melee-agent/tests/test_causal_diff_ownership.py \
  tools/melee-agent/tests/test_causal_diff_inference.py
git commit -m "feat: adapt retail object provenance into causal evidence"
```

---

### Task 10: Regenerate and Prove the DrawFighterHeaders Pilot

**Files:**
- Modify: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/`
- Modify: `tools/melee-agent/tests/test_causal_diff_draw_fighter_headers.py`
- Modify: `tools/mwcc_retro/README.md`
- Modify: `docs/superpowers/specs/2026-07-11-causal-object-binding-producer-design.md`
- Modify: `docs/superpowers/specs/2026-07-11-cross-layer-causal-differencer-design.md`

**Interfaces:**
- Consumes: exact paired/direct source commits, promoted proof, v2 retail producer, and causal adapter.
- Produces: immutable regenerated v2 pilot bundles proving exact backend ownership on both sides and deterministic source-binding abstention.

- [ ] **Step 1: Add the final pilot expectations before regenerating fixtures**

```python
def run_pilot_v2():
    return run_causal_diff(CausalDiffOptions(
        function=FUNCTION,
        frontiers=(
            ("paired", FIXTURE_ROOT / "paired" / "manifest.json"),
            ("direct", FIXTURE_ROOT / "direct" / "manifest.json"),
        ),
        retail_offset=0x234,
    ))


def test_draw_fighter_headers_v2_proves_backend_mediator_but_abstains_at_source():
    report = run_pilot_v2()
    owner = next(
        row for row in report.comparisons
        if row.relation_kind == "backend-owner-corresponds-to"
    )
    assert owner.attributes["paired_anchor"] == (0x234, "use:0", 38, 21, 22)
    assert owner.attributes["direct_anchor"] == (0x234, "use:0", 38, 19, 20)
    assert owner.attributes["paired_stack"] == (0x48, 0x44)
    assert owner.attributes["direct_stack"] == (0x44, 0x44)
    verdict = next(item for item in report.verdicts if item.status is VerdictStatus.ABSTAIN)
    assert verdict.recommendation == "preserve-allocation/shorten-materialization"
    assert verdict.failed_gates == ("gate-9-source-object-binding",)
    assert "source-object-binding-missing" in report.missing_evidence
```

- [ ] **Step 2: Run the pilot test to verify failure against old fixtures**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_draw_fighter_headers.py -q
```

Expected: FAIL because old fixtures lack v2 ownership records.

- [ ] **Step 3: Regenerate paired/direct retail artifacts with exact provenance**

Create exact disposable clones and use branch-local CLI code:

```bash
git clone --shared --no-checkout \
  /Users/mike/.codex/worktrees/b8fa/melee \
  /tmp/task10-regen-paired
git -C /tmp/task10-regen-paired checkout --detach \
  f70dfdafa867307e6f04aa16820870a49a4b0a10
cd /tmp/task10-regen-paired
python tools/worktree-doctor.py --fix
python configure.py
ninja
PYTHONPATH=/Users/mike/.codex/worktrees/b8fa/melee/tools/melee-agent \
  python -m src.cli debug retro backend src/melee/mn/mndiagram.c \
  --function mnDiagram_DrawFighterHeaders

git clone --shared --no-checkout \
  /Users/mike/.codex/worktrees/b8fa/melee \
  /tmp/task10-regen-direct
git -C /tmp/task10-regen-direct checkout --detach \
  871eec422ad6ea536f6d88e004ba2f03a1b73e44
cd /tmp/task10-regen-direct
python tools/worktree-doctor.py --fix
python configure.py
ninja
PYTHONPATH=/Users/mike/.codex/worktrees/b8fa/melee/tools/melee-agent \
  python -m src.cli debug retro backend src/melee/mn/mndiagram.c \
  --function mnDiagram_DrawFighterHeaders
```

Copy only immutable trace, object, source, checkdiff, inspector, frame, and manifest artifacts into their respective fixture directories. Manifests must record the exact commands above, timestamps, compiler/tool/source/environment/artifact hashes, nonces, and capture IDs.

- [ ] **Step 4: Validate the two bundles and strict output**

Run:

```bash
cd /Users/mike/.codex/worktrees/b8fa/melee/tools/melee-agent
python -m src.cli debug inspect causal-diff \
  --frontier paired=tests/fixtures/causal_diff/draw_fighter_headers/paired/manifest.json \
  --frontier direct=tests/fixtures/causal_diff/draw_fighter_headers/direct/manifest.json \
  --function mnDiagram_DrawFighterHeaders \
  --retail-offset 0x234 \
  --json > /tmp/draw-causal-v2.json
```

Expected: one bilateral backend owner, proof-capable same-run anchor/allocator/stack paths, no heuristic edge in those paths, recommendation `preserve-allocation/shorten-materialization`, and verdict `abstain` solely because gate 9 lacks a source-object binding.

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
python -m pytest tests/test_retro_backend_*.py tests/test_retro_struct_map.py -q
python -m pytest tests/test_causal_diff_*.py -q
cd ../..
python configure.py
ninja
git diff --check
```

Expected: all tests pass, the repository build succeeds, and `git diff --check` prints nothing. Pre-existing unrelated failures must be reported separately and must not be hidden by changing this feature's expectations.

- [ ] **Step 6: Update docs with observed facts and residual Phase 2 gate**

Record the promoted proof digest, exact probe commands, verified layouts/sites, regenerated pilot hashes, backend recommendation, and the remaining `source-object-binding-missing` requirement. Do not claim the final `causes` verdict until Phase 2 exists.

- [ ] **Step 7: Commit the pilot**

```bash
git add \
  tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers \
  tools/melee-agent/tests/test_causal_diff_draw_fighter_headers.py \
  tools/mwcc_retro/README.md \
  docs/superpowers/specs/2026-07-11-causal-object-binding-producer-design.md \
  docs/superpowers/specs/2026-07-11-cross-layer-causal-differencer-design.md
git commit -m "test: prove DrawFighterHeaders causal backend provenance"
```

---

## Completion Gate

The plan is complete only when all ten task commits have passed task-specific tests and two-stage review, the promoted proof matches the exact compiler executable, the live retail probes pass without missing sites or dropped events, both DrawFighterHeaders v2 bundles reproduce their known facts, and Phase 1 abstains only at `gate-9-source-object-binding`.
