# Verified Owner-Path Certificate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace downstream reconstruction of loose retail ownership evidence with one immutable, capture-scoped owner-path certificate and deterministic per-role abstention.

**Architecture:** `owner_certificate.py` becomes the only proof-construction boundary for verified v2 object/PCode evidence. It emits content-addressed `EvidenceNode(kind="owner-proof-certificate")` records plus a trusted in-memory role-resolution result; backend integration stores those nodes atomically, while alignment, differencing, effects, and inference consume only certificates and certificate-derived comparisons. Existing v1 behavior and the DrawFighterHeaders pilot remain unchanged, current genuine v2 evidence still abstains, and the contract remains serializable for a later persistent provenance database.

**Tech Stack:** Python 3.11+, frozen dataclasses, pytest, RFC 8785 canonical JSON, SHA-256, the existing causal evidence/store protocols, and the verified retail MWCC GC/1.2.5n v2 producer.

## Global Constraints

- Run `melee-agent capabilities search "verified owner path certificate causal differencer object binding evidence"` before implementation; the audit currently finds no overlapping command or tool surface.
- Runtime pointers and virtual/IG numbers are meaningful only inside one `capture_run_id`; never join them across compiler processes or frontiers.
- `causes` remains strict: heuristic, incomplete, ambiguous, contradictory, truncated, cross-run, unregistered, forged, or unrevalidated evidence abstains.
- `mwcc-retro-object-bindings.v1` still requires `source_bindings: []` and `source_capture: null`; a unique changed certificate pair must stop at `gate-9-source-object-binding` with `source-object-binding-missing`.
- Existing `causal-frontier-bundle.v1` and `mwcc-retro-backend-trace.v1` inputs remain readable and keep their current behavior.
- Current genuine v2 artifacts do not gain owner certificates because the installed proof registry does not grant the required `object-to-virtual` and `object-to-frame` capabilities.
- The GC/1.2.5n proof registry is authority only through the independently verified tuple `(compiler_executable_sha256, proof_id, proof_sha256, registry_schema)`.
- Patched-DLL pcdump, legacy v1 traces, diagnostic graph edges, and deserialized certificate-shaped nodes are never owner-proof certificates.
- Certificate IDs cover every proof-semantic field and all cited record content; runtime-only pointer attributes are excluded by a closed key set.
- Certificate nodes and their cited diagnostic nodes/edges enter the evidence store in one atomic adapter batch.
- `alignment.py`, `differ.py`, `effects.py`, and `inference.py` must not import `ObjectBindingEvidence`, call object-binding proof helpers, or traverse the six raw v2 owner edge kinds.
- No analysis or error path compiles code, refreshes producer artifacts, promotes the instrumentation registry, writes source, or adds Phase 2 source binding; Task 6's explicit repository build is verification only.
- Every task uses red-green-refactor, ends with a focused commit, and receives specification-compliance review followed by code-quality review.
- The focused baseline at commit `f5fcfc6da` is 188 passing tests from `test_causal_diff_object_bindings.py`, `test_causal_diff_ownership.py`, `test_causal_diff_inference.py`, and `test_causal_diff_store.py`.

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/melee-agent/src/mwcc_debug/causal_diff/owner_certificate.py` | Own the closed role/state schemas, exact raw-evidence validation, content hashing, certificate construction, rejections, per-role resolution, and trusted-result token. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/object_binding_adapter.py` | Continue emitting diagnostic v2 nodes/edges and carry the independently verified instrumentation identity; stop declaring proof completeness. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/backend_adapter.py` | Build certificates exactly once, append certificate nodes to `AdapterResult`, and carry `OwnerCertificateResult` on `BackendEvidence`. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/legacy_ownership.py` | Preserve legacy v1/pcdump allocator and reachability helpers while categorically excluding every `mwcc-retro-backend-trace.v2` record. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/models.py` | Permit the certificate abstention comparison to have missing endpoints while preserving the closed endpoint rules for every existing relation. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/alignment.py` | Resolve bilateral semantic owner roles from trusted results and emit either one certificate correspondence or one canonical abstention comparison. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/differ.py` | Compare only certified semantic states and emit `backend-owner-state-changed`; stop reconstructing owner ambiguity from compiler-object records. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/effects.py` | Preserve legacy effect discovery while deriving v2 owner-mediated stack effects from certificate deltas, not raw owner graph traversal. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/inference.py` | Consume trusted certificate correspondences/deltas, render their recorded proof paths, and stop at gate 9 in Phase 1. |
| `tools/melee-agent/src/mwcc_debug/causal_diff/commands.py` | Run differencing before effects so certificate deltas are available to effect derivation. |
| `tools/melee-agent/tests/test_causal_diff_owner_certificates.py` | Cover certificate identity, exact path validation, rejection classification, role resolution, and hostile inputs. |
| `tools/melee-agent/tests/owner_certificate_fixtures.py` | Provide pure synthetic evidence, graph, comparison, and report builders shared by certificate-focused tests. |
| `tools/melee-agent/tests/test_causal_diff_owner_architecture.py` | Enforce imports, forbidden raw-edge literals, removed public helpers, and non-proof deserialization. |
| `tools/melee-agent/tests/test_causal_diff_object_bindings.py` | Update raw diagnostic-adapter expectations and synthetic future-complete fixtures. |
| `tools/melee-agent/tests/test_causal_diff_alignment.py` | Cover bilateral unique/missing/ambiguous/contradictory/incomplete certificate outcomes and canonical comparisons. |
| `tools/melee-agent/tests/test_causal_diff_ownership.py` | Cover certified semantic deltas, effect pairing, and provenance/confidence caps. |
| `tools/melee-agent/tests/test_causal_diff_inference.py` | Cover strict certificate consumption, forgery rejection, gate 9, and unchanged legacy inference. |
| `tools/melee-agent/tests/test_causal_diff_store.py` | Cover certificate-node atomic ingestion, conformance, collision rejection, and round-trip bytes. |
| `tools/melee-agent/tests/test_causal_diff_draw_fighter_headers.py` | Prove that the existing v1 pilot remains byte/order stable and keeps its strict Phase 1 outcome. |

---

### Task 1: Define and Content-Address the Trusted Certificate

**Files:**

- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/owner_certificate.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/object_binding_adapter.py`
- Create: `tools/melee-agent/tests/test_causal_diff_owner_certificates.py`
- Create: `tools/melee-agent/tests/owner_certificate_fixtures.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_object_bindings.py`

**Interfaces:**

- Consumes: `ObjectBindingEvidence(nodes, edges, capabilities, capture_run_id, instrumentation_identity)` and only records registered in that value.
- Produces: `OwnerRoleKey`, `OwnerSemanticState`, `OwnerResolutionStatus`, `OwnerCertificateRejection`, `OwnerRoleResolution`, `OwnerCertificateResult`, and `build_owner_certificates(evidence: ObjectBindingEvidence) -> OwnerCertificateResult`.
- `build_owner_certificates()` has no `requested_roles` parameter: it derives every connected capture-local role before any bilateral lookup, so duplicate caller requests cannot create certificates or ambiguity.
- `OwnerCertificateResult.resolution_for(role: OwnerRoleKey) -> OwnerRoleResolution` returns `missing` for an absent role unless a global rejection forces `incomplete`.
- `OwnerCertificateResult.certificate(record_id: str) -> EvidenceNode | None` returns a node only from the builder-created trusted result.
- Certificate nodes use kind `owner-proof-certificate`, parser `causal-owner-certificate.v1`, and `local_key=proof_content_sha256`.
- Produces test helpers `only(items)`, `complete_evidence(**adapter_overrides)`, `support(evidence, support_kind)`, `replace_record(evidence, record)`, and `canonical_result(result)` in `tests/owner_certificate_fixtures.py`. `complete_evidence()` returns `emit_object_binding_evidence(_adapter_input(**adapter_overrides))`; `support()` requires exactly one matching backend support node; `replace_record()` replaces one same-ID node/edge without reordering; and `canonical_result()` converts dataclasses/enums/mapping proxies to JSON values before `canonical_bytes()`.

- [ ] **Step 1: Write failing happy-path, schema, identity, and forgery tests**

Create `test_causal_diff_owner_certificates.py` and reuse the synthetic validated producer input from `tests.test_causal_diff_object_bindings`:

```python
from dataclasses import replace

import pytest

from src.mwcc_debug.causal_diff.models import Confidence
from src.mwcc_debug.causal_diff.object_binding_adapter import (
    ObjectBindingEvidence,
    emit_object_binding_evidence,
)
from src.mwcc_debug.causal_diff.owner_certificate import (
    OwnerResolutionStatus,
    OwnerRoleKey,
    OwnerSemanticState,
    build_owner_certificates,
)
from tests.test_causal_diff_object_bindings import _adapter_input
from tests.owner_certificate_fixtures import complete_evidence


ROLE = OwnerRoleKey("use:0", "gpr", "row-home", 4, "locals")
STATE = OwnerSemanticState(21, 0x44, 4)


def test_complete_path_builds_one_content_addressed_certificate():
    evidence = emit_object_binding_evidence(_adapter_input())
    result = build_owner_certificates(evidence)
    resolution = result.resolution_for(ROLE)

    assert result.is_trusted
    assert resolution.status is OwnerResolutionStatus.UNIQUE
    assert len(resolution.certificate_record_ids) == 1
    certificate = result.certificate(resolution.certificate_record_ids[0])
    assert certificate is not None
    assert certificate.kind == "owner-proof-certificate"
    assert certificate.provenance.parser == "causal-owner-certificate.v1"
    assert certificate.attributes["role"] == ROLE.as_json()
    assert certificate.attributes["semantic_state"] == STATE.as_json()
    assert certificate.attributes["proof_content_sha256"]
    assert certificate.confidence is Confidence.DERIVED_UNIQUE


@pytest.mark.parametrize(
    "role",
    [
        OwnerRoleKey("use:00", "gpr", "row-home", 4, "locals"),
        OwnerRoleKey("use:0", "GPR", "row-home", 4, "locals"),
        OwnerRoleKey("use:0", "gpr", "Row_Home", 4, "locals"),
        OwnerRoleKey("use:0", "gpr", "row-home", True, "locals"),
        OwnerRoleKey("use:0", "gpr", "row-home", 4, "local"),
    ],
)
def test_role_schema_is_closed(role):
    with pytest.raises(ValueError):
        role.validate()


def test_changed_semantic_support_content_changes_certificate_id():
    evidence = emit_object_binding_evidence(_adapter_input())
    first = build_owner_certificates(evidence)
    owner = next(node for node in evidence.nodes if node.kind == "compiler-object")
    changed = owner.with_attributes({**owner.attributes, "areas": ("locals", "temps")})
    poisoned = replace(
        evidence,
        nodes=tuple(changed if node.record_id == owner.record_id else node for node in evidence.nodes),
    )
    second = build_owner_certificates(poisoned)

    assert first.certificate_nodes[0].record_id != second.certificate_nodes[0].record_id


def test_runtime_pointer_changes_do_not_change_certificate_id():
    evidence = emit_object_binding_evidence(_adapter_input())
    owner = next(node for node in evidence.nodes if node.kind == "compiler-object")
    changed = owner.with_attributes({**owner.attributes, "runtime_address": 0xDEADBEEF})
    altered = replace(
        evidence,
        nodes=tuple(changed if node.record_id == owner.record_id else node for node in evidence.nodes),
    )
    assert (
        build_owner_certificates(evidence).certificate_nodes[0].record_id
        == build_owner_certificates(altered).certificate_nodes[0].record_id
    )


def test_direct_diagnostic_evidence_construction_cannot_build_proof():
    evidence = complete_evidence()
    forged = ObjectBindingEvidence(
        evidence.nodes,
        evidence.edges,
        evidence.capabilities,
        evidence.capture_run_id,
        evidence.abstention_reason,
        evidence.instrumentation_identity,
    )
    result = build_owner_certificates(forged)
    assert result.certificate_nodes == ()
    assert {item.reason for item in result.global_rejections} == {
        "untrusted-diagnostic-materialization"
    }
```

Also add a test that directly constructs an `EvidenceNode(kind="owner-proof-certificate")` and an `OwnerCertificateResult` without the module token; assert `is_trusted is False` and `certificate(record_id) is None`.

- [ ] **Step 2: Run the new tests to verify failure**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_owner_certificates.py -q
```

Expected: collection fails because `owner_certificate.py` and its public types do not exist.

- [ ] **Step 3: Thread the independently verified instrumentation tuple into diagnostic evidence**

Change both raw dataclasses to carry one closed tuple:

```python
OwnerInstrumentationIdentity = tuple[str, str, str, str]


@dataclass(frozen=True, slots=True)
class ObjectBindingAdapterInput:
    compile_id: str
    function: str
    artifact_sha256: str
    capture_run_id: str
    artifact_size: int
    capabilities: frozenset[str]
    object_validation: ObjectBindingValidation
    pcode_validation: PCodeLineageValidation
    instrumentation_identity: OwnerInstrumentationIdentity | None = None


@dataclass(frozen=True, slots=True)
class ObjectBindingEvidence:
    nodes: tuple[EvidenceNode, ...]
    edges: tuple[EvidenceEdge, ...]
    capabilities: frozenset[str]
    capture_run_id: str
    abstention_reason: str | None
    instrumentation_identity: OwnerInstrumentationIdentity | None
    _adapter_token: object | None = field(default=None, repr=False, compare=False)
```

In `adapt_object_bindings()`, populate it only from the already trusted proof and installed registry schema:

```python
instrumentation_identity = (
    proof.compiler_executable_sha256,
    proof.proof_id,
    proof.sha256,
    str(installed_table["instrumentation_proof_schema"]),
)
```

Update `_adapter_input()` to use `("1" * 64, "proof-test", "2" * 64, "mwcc-retro-lifetime-proof.v1")`. Legacy/no-v2 evidence uses `None`. Define a module-private `_OBJECT_BINDING_ADAPTER_TOKEN`, pass it only from `emit_object_binding_evidence()`, and have `owner_certificate.py` require identity with that token before building. Direct `ObjectBindingEvidence(...)` construction therefore yields a global `untrusted-diagnostic-materialization` rejection; the diagnostic type exposes no public proof-capable property.

- [ ] **Step 4: Add the closed certificate types and trusted-result token**

Implement these exact public shapes in `owner_certificate.py`:

```python
_TRUST_TOKEN = object()


class OwnerResolutionStatus(StrEnum):
    UNIQUE = "unique"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    CONTRADICTORY = "contradictory"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True, order=True)
class OwnerRoleKey:
    operand_key: str
    register_class: str
    semantic_stack_role: str
    type_size: int
    frame_area: str

    def validate(self) -> None:
        if re.fullmatch(r"^(def|use):(0|[1-9][0-9]*)$", self.operand_key) is None:
            raise ValueError("invalid owner operand key")
        if self.register_class not in {"gpr", "fpr"}:
            raise ValueError("invalid owner register class")
        if re.fullmatch(r"^[a-z][a-z0-9-]{0,63}$", self.semantic_stack_role) is None:
            raise ValueError("invalid semantic stack role")
        if isinstance(self.type_size, bool) or not isinstance(self.type_size, int) or not 1 <= self.type_size <= 0x7FFFFFFF:
            raise ValueError("invalid owner type size")
        if self.frame_area not in {"arguments", "locals", "temps"}:
            raise ValueError("invalid owner frame area")

    def as_json(self) -> dict[str, object]:
        self.validate()
        return {
            "operand_key": self.operand_key,
            "register_class": self.register_class,
            "semantic_stack_role": self.semantic_stack_role,
            "type_size": self.type_size,
            "frame_area": self.frame_area,
        }


@dataclass(frozen=True, slots=True, order=True)
class OwnerSemanticState:
    assigned_physical_register: int
    stack_offset: int
    stack_size: int

    def validate(self) -> None:
        values = (self.assigned_physical_register, self.stack_offset, self.stack_size)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("owner semantic state values must be integers")
        if not 0 <= self.assigned_physical_register <= 31:
            raise ValueError("invalid assigned physical register")
        if not -0x80000000 <= self.stack_offset <= 0x7FFFFFFF:
            raise ValueError("invalid stack offset")
        if not 1 <= self.stack_size <= 0x7FFFFFFF:
            raise ValueError("invalid stack size")

    def as_json(self) -> dict[str, int]:
        self.validate()
        return {
            "assigned_physical_register": self.assigned_physical_register,
            "stack_offset": self.stack_offset,
            "stack_size": self.stack_size,
        }


@dataclass(frozen=True, slots=True)
class OwnerCertificateRejection:
    rejection_id: str
    reason: str
    role: OwnerRoleKey | None
    candidate_record_ids: tuple[str, ...]
    raw_support_record_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OwnerRoleResolution:
    role: OwnerRoleKey
    status: OwnerResolutionStatus
    certificate_record_ids: tuple[str, ...]
    rejections: tuple[OwnerCertificateRejection, ...]


@dataclass(frozen=True, slots=True)
class OwnerCertificateResult:
    certificate_nodes: tuple[EvidenceNode, ...]
    role_resolutions: tuple[OwnerRoleResolution, ...]
    global_rejections: tuple[OwnerCertificateRejection, ...]
    _token: object | None = field(default=None, repr=False, compare=False)

    @property
    def is_trusted(self) -> bool:
        return self._token is _TRUST_TOKEN

    def certificate(self, record_id: str) -> EvidenceNode | None:
        if not self.is_trusted:
            return None
        return next((node for node in self.certificate_nodes if node.record_id == record_id), None)

    def resolution_for(self, role: OwnerRoleKey) -> OwnerRoleResolution:
        role.validate()
        base = next(
            (item for item in self.role_resolutions if item.role == role),
            OwnerRoleResolution(role, OwnerResolutionStatus.MISSING, (), ()),
        )
        if not self.is_trusted or self.global_rejections:
            return OwnerRoleResolution(
                role,
                OwnerResolutionStatus.INCOMPLETE,
                base.certificate_record_ids,
                (*base.rejections, *self.global_rejections),
            )
        return base
```

`validate()` must enforce the exact grammar/ranges in the design, including rejection of `bool` as an integer. Do not normalize aliases inside certificate construction.

- [ ] **Step 5: Implement proof-content canonicalization and the minimal complete path**

Use a closed runtime-only set:

```python
_RUNTIME_ONLY_ATTRIBUTE_KEYS = frozenset({
    "runtime_address",
    "ignode_runtime_address",
    "list_node_runtime_address",
})
```

Serialize every cited node/edge with record type, record ID, compile/function scope, kind, confidence fields, endpoints/role, recursively filtered attributes, and the complete provenance object. Hash this payload with `hashlib.sha256(canonical_bytes(payload)).hexdigest()`. The recursive filter removes only the three closed runtime-only keys, including occurrences nested inside snapshots/ranges. The certificate provenance must cite every path/support record and pass their confidences to `EvidenceNode.create()`.

For the first green implementation, enumerate the synthetic complete chain in this order:

```text
assembly anchor -> retail PCode -> emitted lineage -> retail virtual
compiler object -> retail virtual -> allocator node
compiler object -> stack object
```

Require the one pcode-rewrite support record shared by the virtual edge, allocator edge, and allocator node; derive `assigned_physical_register` from it, not from the allocator node. Build the node with:

```python
EvidenceNode.create(
    compile_id=compile_id,
    function=function,
    kind="owner-proof-certificate",
    local_key=proof_content_sha256,
    role_key=role.semantic_stack_role,
    producer_confidence=Confidence.OBSERVED,
    adapter_confidence=Confidence.DERIVED_UNIQUE,
    provenance=Provenance(
        artifact_sha256=artifact_sha256,
        parser="causal-owner-certificate.v1",
        raw_start=None,
        raw_end=None,
        derivation_rule="verified-capture-local-owner-path",
        input_record_ids=all_input_ids,
    ),
    input_confidences=all_input_confidences,
    attributes=certificate_attributes,
)
```

The attribute keys are exactly `schema_version`, `capture_run_id`, `role`, `semantic_state`, `owner_record_id`, `anchor_record_id`, `pcode_record_id`, `lineage_record_ids`, `virtual_record_id`, `allocator_record_id`, `stack_record_id`, `path_record_ids`, `raw_support_record_ids`, `proof_content_sha256`, and `instrumentation_identity`.

- [ ] **Step 6: Run the focused tests and commit**

Run:

```bash
python -m pytest \
  tests/test_causal_diff_owner_certificates.py \
  tests/test_causal_diff_object_bindings.py -q
```

Expected: PASS.

```bash
git add \
  tools/melee-agent/src/mwcc_debug/causal_diff/owner_certificate.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/object_binding_adapter.py \
  tools/melee-agent/tests/owner_certificate_fixtures.py \
  tools/melee-agent/tests/test_causal_diff_owner_certificates.py \
  tools/melee-agent/tests/test_causal_diff_object_bindings.py
git commit -m "feat: build verified owner path certificates"
```

---

### Task 2: Make Path Validation and Role Resolution Fail Closed

**Files:**

- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/owner_certificate.py`
- Modify: `tools/melee-agent/tests/owner_certificate_fixtures.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_owner_certificates.py`

**Interfaces:**

- Consumes: Task 1's exact types and `build_owner_certificates(evidence)`.
- Produces: complete invariant validation, content-derived rejections, canonical role-resolution multisets, and deterministic results under input permutation/duplication.
- Rejection reasons are closed to `untrusted-diagnostic-materialization`, `missing-required-capability`, `missing-instrumentation-identity`, `mixed-record-scope`, `unregistered-support`, `malformed-support`, `disconnected-owner-path`, `plausible-owner-alternative`, `split-physical-assignment`, `lineage-parent-mismatch`, `allocator-origin-contradiction`, and `frame-binding-contradiction`.
- Produces test helpers `evidence_with_two_mutation_outputs(first_parents, second_parents)`, `evidence_with_mutation_parent_override(parents)`, `evidence_with_certificate_and_role_rejection(role)`, `evidence_without_instrumentation_identity()`, `ambiguous_evidence()`, `first_role()`, `second_role()`, and `other_role()`. Each helper starts from `complete_evidence()`, changes only the named topology/role fact with `dataclasses.replace`, preserves all untouched record order/content, and never calls production-private functions. The certificate-plus-rejection fixture retains the complete valid path and adds one disconnected but role-compatible path candidate so the production builder creates both outcomes.

- [ ] **Step 1: Add adversarial assignment, lineage, scope, and support tests**

Add tests that mutate one fact at a time while retaining the remaining coordinated records:

```python
def test_split_physical_assignment_never_certifies():
    evidence = emit_object_binding_evidence(_adapter_input(physical_register=21))
    emission = support(evidence, "pcode-emission")
    poisoned = replace_record(
        evidence,
        emission.with_attributes({**emission.attributes, "physical_register": 22}),
    )
    result = build_owner_certificates(poisoned)
    resolution = result.resolution_for(ROLE)
    assert resolution.status is OwnerResolutionStatus.CONTRADICTORY
    assert resolution.certificate_record_ids == ()
    assert {item.reason for item in resolution.rejections} == {"split-physical-assignment"}


def test_multi_output_event_uses_each_outputs_exact_parent_set():
    evidence = evidence_with_two_mutation_outputs(
        first_parents=("ol-a",),
        second_parents=("ol-b", "ol-c"),
    )
    result = build_owner_certificates(evidence)
    assert result.resolution_for(first_role()).status is OwnerResolutionStatus.UNIQUE
    assert result.resolution_for(second_role()).status is OwnerResolutionStatus.UNIQUE


@pytest.mark.parametrize(
    "parents",
    [
        (),
        ("ol-a", "ol-extra"),
        ("ol-other",),
        ("ol-a", "ol-a"),
        ("ol-a", "ol-b"),
    ],
)
def test_mutation_parent_variants_fail_closed(parents):
    evidence = evidence_with_mutation_parent_override(parents)
    assert build_owner_certificates(evidence).resolution_for(ROLE).status is not OwnerResolutionStatus.UNIQUE
```

Cover mismatched event index, side, mutation kind, noncanonical parent order, record from another compile/capture/artifact, unregistered provenance input, heuristic support, unknown support attribute, and coordinated physical changes that disagree with the decoded emission.

- [ ] **Step 2: Add per-role status and canonical-alternative tests**

Construct one evidence value containing five semantic roles and assert `unique`, `missing`, `ambiguous`, `contradictory`, and `incomplete` simultaneously. Add these exact boundary tests:

```python
def test_valid_certificate_plus_compatible_rejection_is_not_unique():
    result = build_owner_certificates(evidence_with_certificate_and_role_rejection(ROLE))
    assert result.resolution_for(ROLE).status is OwnerResolutionStatus.AMBIGUOUS


def test_global_rejection_taints_every_lookup_as_incomplete():
    result = build_owner_certificates(evidence_without_instrumentation_identity())
    assert result.global_rejections
    assert all(rejection.role is None for rejection in result.global_rejections)
    assert result.resolution_for(ROLE).status is OwnerResolutionStatus.INCOMPLETE
    assert result.resolution_for(other_role()).status is OwnerResolutionStatus.INCOMPLETE


def test_repeated_lookup_does_not_change_resolution():
    result = build_owner_certificates(complete_evidence())
    assert result.resolution_for(ROLE) == result.resolution_for(ROLE)


def test_input_permutation_is_byte_stable():
    evidence = ambiguous_evidence()
    reversed_evidence = replace(evidence, nodes=evidence.nodes[::-1], edges=evidence.edges[::-1])
    assert canonical_result(build_owner_certificates(evidence)) == canonical_result(
        build_owner_certificates(reversed_evidence)
    )
```

Also assert exact duplicate alternatives retain one canonical group with a multiplicity count in the eventual alignment summary; the capture-local resolution must preserve the complete canonical provenance set. A `role=None` rejection belongs only to `global_rejections` and makes every `resolution_for()` lookup incomplete without discarding that role's certificate IDs or role-scoped rejections.

- [ ] **Step 3: Run the new tests to verify red failures**

Run:

```bash
python -m pytest tests/test_causal_diff_owner_certificates.py -q
```

Expected: the Task 1 happy path passes while the new adversarial/status cases fail.

- [ ] **Step 4: Centralize exact record and support validation**

Move the proof-semantic validation rules into private functions in `owner_certificate.py`. `_registered_record(evidence, record_id)` returns only the exactly registered `EvidenceNode`/`EvidenceEdge`; `_validate_common_scope(evidence, records)` rejects mixed compile/function/artifact/parser/capture/confidence domains; `_validated_support_records(evidence, dependent, excluded_ids)` resolves every non-endpoint provenance input through the closed support schemas; `_validate_emission(evidence, anchor, pcode, lineage)` returns the unique range/generation/emission support; `_validate_lineage_output(evidence, lineage)` replays only that output's exact canonical parents; `_validate_allocator_origin(evidence, virtual, allocator)` returns the unique rewrite-derived physical register; and `_validate_frame_binding(evidence, owner, stack)` returns the exact final stack state. Every rejection is an `OwnerCertificateRejection`, so none of these functions exposes a reusable public proof boolean.

Each function returns a validated value or an `OwnerCertificateRejection`; it must never return a bare truth value that downstream code could reuse as a weaker proof gate. Require exact key sets for every support schema. For mutation output `child`, compute parents only from edges whose `event_index`, `lineage_event_side`, `mutation_kind`, `operand_lineage_id`, and complete `parent_lineage_ids` equal that child's support record:

```python
selected = tuple(
    edge for edge in lineage_edges
    if edge.target_id == child.record_id
    and edge.attributes["event_index"] == support.attributes["event_index"]
    and edge.attributes["lineage_event_side"] == "outputs"
    and edge.attributes["mutation_kind"] == support.attributes["mutation_kind"]
    and edge.attributes["parent_lineage_ids"] == support.attributes["parent_lineage_ids"]
)
actual = tuple(sorted(parent_lineage_id(edge.source_id) for edge in selected))
if actual != support.attributes["parent_lineage_ids"]:
    reject("lineage-parent-mismatch", role, selected, (support,))
```

Never union parents across sibling outputs in the same event.

- [ ] **Step 5: Resolve the complete canonical multiset per role**

Group certificates and role-scoped rejections by validated `OwnerRoleKey`, sort by canonical JSON bytes, and apply this precedence:

```python
if global_rejections:
    status = OwnerResolutionStatus.INCOMPLETE
elif any(rejection.reason in _CONTRADICTORY_REASONS for rejection in rejections):
    status = OwnerResolutionStatus.CONTRADICTORY
elif any(rejection.reason in _INCOMPLETE_REASONS for rejection in rejections):
    status = OwnerResolutionStatus.INCOMPLETE
elif len(semantic_states) > 1:
    status = OwnerResolutionStatus.CONTRADICTORY
elif len(certificates) > 1 or any(
    rejection.reason == "plausible-owner-alternative" for rejection in rejections
):
    status = OwnerResolutionStatus.AMBIGUOUS
elif len(certificates) == 1:
    status = OwnerResolutionStatus.UNIQUE
elif rejections:
    status = OwnerResolutionStatus.INCOMPLETE
else:
    status = OwnerResolutionStatus.MISSING
```

Create rejection IDs from the canonical full-content projection of cited candidate/support records, not their record IDs alone. Keep exact duplicate counts in an internal canonical summary consumed by Task 4.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
python -m pytest \
  tests/test_causal_diff_owner_certificates.py \
  tests/test_causal_diff_object_bindings.py -q
```

Expected: PASS.

```bash
git add \
  tools/melee-agent/src/mwcc_debug/causal_diff/owner_certificate.py \
  tools/melee-agent/tests/owner_certificate_fixtures.py \
  tools/melee-agent/tests/test_causal_diff_owner_certificates.py
git commit -m "fix: make owner certificates fail closed"
```

---

### Task 3: Integrate Certificates Atomically With Backend Evidence and Storage

**Files:**

- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/backend_adapter.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/graph.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_backend_adapters.py`
- Modify: `tools/melee-agent/tests/owner_certificate_fixtures.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_store.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_owner_certificates.py`

**Interfaces:**

- Consumes: Task 2's `build_owner_certificates()` result.
- Produces: `BackendEvidence.owner_certificates: OwnerCertificateResult`, an `AdapterResult` containing diagnostic nodes/edges plus certificate nodes, and `BackendEvidence.owner_abstention_reason`.
- Store protocol signatures do not change; certificates remain ordinary `EvidenceNode` values.
- Produces `validated_current_v2_bundle(tmp_path, monkeypatch)` by reusing `_verified_bundle()` from `test_causal_diff_object_bindings.py`. `future_complete_backend(tmp_path, monkeypatch)` creates that valid bundle, builds `complete_evidence(compile_id=bundle.compile_id, function=bundle.manifest.function)`, monkeypatches only `backend_adapter.adapt_object_bindings` to return the synthetic evidence, then calls `adapt_backends(bundle)`; this isolates backend composition without pretending current producer artifacts have future capabilities.

- [ ] **Step 1: Write failing backend/store integration tests**

Add tests that assert:

```python
def test_backend_adds_certificate_and_all_inputs_in_one_adapter_result(tmp_path, monkeypatch):
    backend = future_complete_backend(tmp_path, monkeypatch)
    certificate = backend.owner_certificates.certificate_nodes[0]
    assert certificate in backend.result.nodes
    assert set(certificate.provenance.input_record_ids) <= {
        record.record_id for record in (*backend.result.nodes, *backend.result.edges)
    }


def test_certificate_round_trips_through_store_as_diagnostic_bytes(tmp_path, monkeypatch):
    backend = future_complete_backend(tmp_path, monkeypatch)
    store = InMemoryEvidenceStore()
    add_adapter_results_atomically(store, (backend.result,))
    certificate = backend.owner_certificates.certificate_nodes[0]
    reloaded = store.get_node(certificate.record_id)
    assert reloaded == certificate
    rebuilt = build_owner_certificates(backend.object_bindings)
    assert rebuilt.certificate(certificate.record_id) == reloaded
    forged_result = OwnerCertificateResult((reloaded,), (), ())
    assert forged_result.is_trusted is False
    assert forged_result.certificate(certificate.record_id) is None


def test_changed_content_with_same_certificate_id_is_store_collision(tmp_path, monkeypatch):
    certificate = future_complete_backend(tmp_path, monkeypatch).owner_certificates.certificate_nodes[0]
    store = InMemoryEvidenceStore()
    store.add_nodes((certificate,))
    with pytest.raises(ValueError, match="record ID collision"):
        store.add_nodes((certificate.with_attributes({**certificate.attributes, "stack_offset": 0x48}),))
```

Extend the store-conformance parametrization so the same assertions run for every registered store implementation, not only `InMemoryEvidenceStore`.

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```bash
python -m pytest \
  tests/test_causal_diff_backend_adapters.py \
  tests/test_causal_diff_store.py \
  tests/test_causal_diff_owner_certificates.py -q
```

Expected: FAIL because `BackendEvidence` does not carry or ingest certificates.

- [ ] **Step 3: Build certificates once inside `adapt_backends()`**

Change the backend shape and assembly order:

```python
@dataclass(frozen=True, slots=True)
class BackendEvidence:
    result: AdapterResult
    pcdump_text: str
    role_compile: role_descriptor.Compile | None
    nodes_by_class_ig: Mapping[tuple[int, int], str]
    nodes_by_virtual: Mapping[tuple[str, int], str]
    object_bindings: ObjectBindingEvidence | None = None
    owner_certificates: OwnerCertificateResult = EMPTY_OWNER_CERTIFICATE_RESULT

    @property
    def owner_abstention_reason(self) -> str | None:
        if self.object_bindings is None:
            return None
        return None if self.owner_certificates.certificate_nodes else "backend-owner-path-incomplete"
```

Immediately after `object_bindings = adapt_object_bindings(bundle)`, call `build_owner_certificates(object_bindings)`. Append `certificate_nodes` after the raw object-binding nodes and before `_deduplicate_nodes()`. Do not add a certificate capability to the manifest capability union; certificates are derived evidence, not producer declarations.

- [ ] **Step 4: Validate the whole batch, then ingest certificates after their cited edges**

Keep `EvidenceSink` unchanged. Partition nodes into `diagnostic_nodes` and `certificate_nodes`. A certificate may cite edges, so the preflight and destination order must be:

```python
preflight.add_nodes((*external_nodes, *diagnostic_nodes))
preflight.add_edges((*external_edges, *edges))
preflight.add_nodes(certificate_nodes)

store.add_nodes(diagnostic_nodes)
store.add_edges(edges)
store.add_nodes(certificate_nodes)
```

Before mutating the destination, require every certificate provenance input to appear in the normalized batch or already exist in the destination, run all three preflight calls, and perform the existing collision checks. This preserves the function's preflight-atomic behavior while satisfying the store rule that every provenance input already resolves when its dependent node is added.

Do not create a certificate-specific table or query API in this task.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python -m pytest \
  tests/test_causal_diff_backend_adapters.py \
  tests/test_causal_diff_store.py \
  tests/test_causal_diff_owner_certificates.py \
  tests/test_causal_diff_object_bindings.py -q
```

Expected: PASS.

```bash
git add \
  tools/melee-agent/src/mwcc_debug/causal_diff/backend_adapter.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/graph.py \
  tools/melee-agent/tests/owner_certificate_fixtures.py \
  tools/melee-agent/tests/test_causal_diff_backend_adapters.py \
  tools/melee-agent/tests/test_causal_diff_store.py \
  tools/melee-agent/tests/test_causal_diff_owner_certificates.py
git commit -m "feat: integrate owner certificates with evidence storage"
```

---

### Task 4: Align and Difference Only Certified Owner States

**Files:**

- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/models.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/alignment.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/differ.py`
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/legacy_ownership.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_alignment.py`
- Modify: `tools/melee-agent/tests/owner_certificate_fixtures.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_ownership.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_object_bindings.py`

**Interfaces:**

- Consumes: trusted `BackendEvidence.owner_certificates` from both frontiers.
- Produces: `backend-owner-corresponds-to` parser `causal-backend-owner-alignment.v2`, `backend-owner-abstained`, and `backend-owner-state-changed` parser `causal-frontier-differ.v1`.
- A correspondence's endpoints are the two certificate nodes. An abstention may have either or both endpoints absent and is the only relation allowed to do so.
- `BackendOwnerRoleTuple`, `BackendOwnerPath`, `BackendOwnerCandidate`, `resolve_backend_owner_candidates()`, and `backend_owner_correspondences()` are removed from `alignment.py`; `OwnerRoleKey` is the sole semantic role type.
- Produces test helpers `alignment()`, `graphs_with_statuses(left_status, right_status)`, `future_complete_graph_pair()`, `owner_comparison(states)`, `graphs()`, and `node(record_id)`. They build `FrontierGraph` values with ordinary `InMemoryEvidenceStore` ingestion; `owner_comparison()` uses certificate endpoints and parser `causal-backend-owner-alignment.v2`; `node()` resolves through the graph pair and requires exactly one match.
- `legacy_ownership.py` produces `legacy_allocator_from_virtual(graph, virtual_id)` and later `legacy_reachable_records()`/`legacy_simple_paths()`. Every helper rejects records whose parser is `mwcc-retro-backend-trace.v2` or whose attributes contain a v2 `capture_run_id`; it never imports `ObjectBindingEvidence`.

- [ ] **Step 1: Write failing bilateral resolution and canonical abstention tests**

Cover these exact cases:

```python
@pytest.mark.parametrize(
    ("left_status", "right_status", "reason"),
    [
        ("missing", "unique", "backend-owner-missing"),
        ("ambiguous", "unique", "backend-owner-ambiguous"),
        ("contradictory", "unique", "backend-owner-contradictory"),
        ("incomplete", "unique", "backend-owner-path-incomplete"),
    ],
)
def test_nonunique_bilateral_resolution_emits_one_abstention(left_status, right_status, reason):
    comparisons = build_role_comparisons(alignment(), graphs_with_statuses(left_status, right_status))
    abstention = only(comparison for comparison in comparisons if comparison.relation_kind == "backend-owner-abstained")
    assert abstention.attributes["reason"] == reason
    assert abstention.attributes["left_status"] == left_status
    assert abstention.attributes["right_status"] == right_status


def test_unique_pair_uses_certificate_endpoints_and_minimum_confidence():
    comparison = owner_comparison(future_complete_graph_pair())
    assert comparison.relation_kind == "backend-owner-corresponds-to"
    assert comparison.provenance.parser == "causal-backend-owner-alignment.v2"
    assert node(comparison.left_record_id).kind == "owner-proof-certificate"
    assert node(comparison.right_record_id).kind == "owner-proof-certificate"
    assert comparison.confidence == min_confidence(
        node(comparison.left_record_id).confidence,
        node(comparison.right_record_id).confidence,
    )
```

Add permutations and duplicate rejections; assert canonical bytes, comparison IDs, `alternatives`, and multiplicities are identical regardless of input order.

- [ ] **Step 2: Write failing semantic-delta tests**

```python
def test_equal_certificate_semantics_emit_no_owner_delta():
    deltas = diff_frontiers(graphs(), (owner_comparison(states=(STATE, STATE)),))
    assert not any(item.relation_kind == "backend-owner-state-changed" for item in deltas)


def test_changed_certificate_semantics_emit_one_reconstructable_delta():
    changed = OwnerSemanticState(22, 0x48, 4)
    comparison = owner_comparison(states=(STATE, changed))
    delta = only(item for item in diff_frontiers(graphs(), (comparison,)) if item.relation_kind == "backend-owner-state-changed")
    assert delta.left_record_id == comparison.left_record_id
    assert delta.right_record_id == comparison.right_record_id
    assert delta.attributes == {
        "role": ROLE.as_json(),
        "left_semantic_state": STATE.as_json(),
        "right_semantic_state": changed.as_json(),
    }
    assert set(delta.provenance.input_record_ids) == {
        comparison.record_id,
        comparison.left_record_id,
        comparison.right_record_id,
    }
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
python -m pytest \
  tests/test_causal_diff_alignment.py \
  tests/test_causal_diff_ownership.py \
  tests/test_causal_diff_object_bindings.py -q
```

Expected: FAIL against loose owner traversal and compiler-object endpoints.

- [ ] **Step 4: Permit only certificate abstention to have nullable endpoints**

In `ComparisonRecord.__post_init__`, add a closed branch before the existing added/removed logic:

```python
if self.relation_kind == "backend-owner-abstained":
    valid_endpoints = True
elif self.relation_kind in _ADDED_RELATIONS:
    valid_endpoints = self.left_record_id is None and self.right_record_id is not None
elif self.relation_kind in _REMOVED_RELATIONS:
    valid_endpoints = self.left_record_id is not None and self.right_record_id is None
else:
    valid_endpoints = self.left_record_id is not None and self.right_record_id is not None
```

Do not weaken endpoint validation for any existing relation. `InMemoryEvidenceStore._validate_comparison_endpoint()` already accepts `None` and requires every non-null endpoint to resolve.

- [ ] **Step 5: Replace bilateral graph enumeration with result lookup**

In `build_role_comparisons()`:

1. Take the sorted union of roles from both `role_resolutions` tuples.
2. Call `resolution_for(role)` once per side.
3. If both are `unique`, load each certificate through `result.certificate()`, verify it is present in that frontier's store, and emit one correspondence.
4. Otherwise emit one `backend-owner-abstained` comparison.

Use this fixed abstention priority: contradictory, incomplete, ambiguous, missing. Attributes contain `reason`, `role`, `left_status`, `right_status`, `certificate_record_ids`, `rejections`, and canonical `alternatives`. Alternative summaries contain certificate ID, role, state, confidence, canonical provenance IDs, and rejection ID/reason/support IDs. Group exact duplicate summaries and store `multiplicity`; sort groups by canonical JSON bytes.

`ComparisonRecord.record_id` does not hash attributes, so both relation constructors must bind the role/content explicitly in provenance. Use `derivation_rule="certified-owner-role:" + sha256(canonical_bytes(role.as_json()))` for correspondences and `derivation_rule="certified-owner-abstention:" + sha256(canonical_bytes({"role": role.as_json(), "alternatives": alternatives}))` for abstentions. Iterate sorted roles for `occurrence_ordinal`; set every abstention's producer/adapter confidence to `HEURISTIC`, even when it cites a nonheuristic surviving certificate.

For the existing allocator-only `_verified_retail_local_role()`, select allocator nodes only through unique trusted certificates matching the operand key/register class. Multiple distinct certificate allocator IDs remain `AMBIGUOUS_BACKEND_ROLE`; no raw edge traversal remains in that function.

Move the old generic `_allocator_from_virtual()` query to `legacy_allocator_from_virtual()`. The automatic v1/pcdump fallback may call that helper after certificate lookup fails, but the helper must categorically discard v2 nodes/edges before returning candidates. This preserves legacy role alignment without letting diagnostic v2 mappings become proof.

- [ ] **Step 6: Replace owner differencing with certificate semantic-state comparison**

Delete `_owner_ambiguity_records()` and all compiler-object owner acceptance/counting logic. For each v2 correspondence:

1. Require parser `causal-backend-owner-alignment.v2`.
2. Resolve both endpoint nodes and require kind `owner-proof-certificate`.
3. Require the correspondence provenance to cite both nodes.
4. Compare only `semantic_state`; equal values emit nothing.
5. Emit exactly one `backend-owner-state-changed` with the correspondence and both certificates as provenance inputs.

Generic role-aligned node/edge differencing remains unchanged for non-certificate records.

- [ ] **Step 7: Run tests and commit**

Run:

```bash
python -m pytest \
  tests/test_causal_diff_alignment.py \
  tests/test_causal_diff_ownership.py \
  tests/test_causal_diff_object_bindings.py -q
```

Expected: PASS.

```bash
git add \
  tools/melee-agent/src/mwcc_debug/causal_diff/models.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/alignment.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/differ.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/legacy_ownership.py \
  tools/melee-agent/tests/test_causal_diff_alignment.py \
  tools/melee-agent/tests/test_causal_diff_ownership.py \
  tools/melee-agent/tests/test_causal_diff_object_bindings.py
git commit -m "refactor: align certified owner states"
```

---

### Task 5: Consume Certificates in Effects and Inference, Then Seal the Boundary

**Files:**

- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/commands.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/effects.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/inference.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/legacy_ownership.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/object_binding_adapter.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_ownership.py`
- Modify: `tools/melee-agent/tests/owner_certificate_fixtures.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_inference.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_object_bindings.py`
- Create: `tools/melee-agent/tests/test_causal_diff_owner_architecture.py`

**Interfaces:**

- Consumes: `backend-owner-corresponds-to`, `backend-owner-abstained`, `backend-owner-state-changed`, and each graph's trusted `OwnerCertificateResult`.
- Produces: certificate-mediated `StackEffect.owner_record_ids`, proof paths rendered from certificate attributes, strict gate-9 abstention, and an enforced one-module trust boundary.
- `derive_effects(alignment, graphs, comparisons=())` extends the two-argument form without breaking legacy callers.
- `infer_pair(pair, query, comparisons, *, evidence_depth=4, owner_certificate_results_by_compile: Mapping[str, OwnerCertificateResult] | None = None)` replaces the `owner_evidence_by_compile` parameter.
- Produces `run_synthetic_future_complete_pair()`, `run_with_forged_certificate_node_but_no_trusted_result()`, `graph_with_legacy_and_v2_numeric_collision()`, and `legacy_roots(graph)` in the shared test fixture module. The first builds two trusted synthetic graphs with opposite allocator/stack quality and calls the normal orchestration functions; the second stores the same certificate-shaped nodes/comparisons but replaces both backend results with directly constructed, untrusted `OwnerCertificateResult` values; the collision graph contains one legacy and one v2 mapping with equal numeric virtual/IG values; and `legacy_roots()` returns only the legacy allocator root IDs.

- [ ] **Step 1: Write failing certificate effect/inference tests**

Add one future-complete pair with paired/direct semantic states and assert:

```python
def test_certificate_delta_drives_owner_mediated_stack_effect():
    report = run_synthetic_future_complete_pair()
    stack = only(report.effects.stack_effects)
    owner = only(item for item in report.comparisons if item.relation_kind == "backend-owner-corresponds-to")
    assert set(stack.owner_record_ids) == {owner.left_record_id, owner.right_record_id}
    assert stack.first_offset == 0x48
    assert stack.second_offset == 0x44


def test_unique_changed_certificate_pair_stops_only_at_source_binding_gate():
    report = run_synthetic_future_complete_pair()
    verdict = only(report.verdicts)
    owner = only(item for item in report.comparisons if item.relation_kind == "backend-owner-corresponds-to")
    assert verdict.status is VerdictStatus.ABSTAIN
    assert verdict.failed_gates == ("gate-9-source-object-binding",)
    assert report.missing_evidence == ("source-object-binding-missing",)
    assert {path[0] for path in verdict.proof_paths} == {
        owner.left_record_id,
        owner.right_record_id,
    }


def test_forged_stored_certificate_cannot_satisfy_inference():
    report = run_with_forged_certificate_node_but_no_trusted_result()
    verdict = only(report.verdicts)
    assert verdict.status is VerdictStatus.ABSTAIN
    assert "gate-7-proof-capable-path" in verdict.failed_gates
```

Keep the existing v1 inference cases and require identical statuses, gates, and recommendations.

- [ ] **Step 2: Write the architectural guard before refactoring**

Create an AST-based test over `alignment.py`, `differ.py`, `effects.py`, and `inference.py`:

```python
FORBIDDEN_IMPORTS = {
    "ObjectBindingEvidence",
    "_OBJECT_BINDING_ADAPTER_TOKEN",
    "proof_complete",
    "exact_owner_path_record",
    "owner_edge_requires_exact_v2",
    "derive_backend_frame_recommendation",
    "bilateral_source_object_records",
}
FORBIDDEN_EDGE_LITERALS = {
    "assembly-anchor-emitted-by-pcode",
    "pcode-operand-lineage",
    "pcode-operand-uses-virtual",
    "object-materializes-virtual",
    "maps-to-allocator-node",
    "object-has-stack-home",
}


def test_downstream_modules_cannot_reconstruct_raw_owner_proof():
    for path in DOWNSTREAM_PATHS:
        tree = ast.parse(path.read_text())
        assert imported_names(tree).isdisjoint(FORBIDDEN_IMPORTS)
        assert string_constants(tree).isdisjoint(FORBIDDEN_EDGE_LITERALS)


def test_legacy_owner_helpers_categorically_reject_v2_records():
    graph = graph_with_legacy_and_v2_numeric_collision()
    record_ids, edge_ids = legacy_reachable_records(graph, legacy_roots(graph))
    edges = tuple(graph.store.get_edge(record_id) for record_id in edge_ids)
    assert record_ids
    assert all(edge is not None for edge in edges)
    assert all(edge.provenance.parser != "mwcc-retro-backend-trace.v2" for edge in edges if edge is not None)
    assert not any("capture_run_id" in edge.attributes for edge in edges if edge is not None)
```

Also assert the removed helpers are absent from `object_binding_adapter.__all__` and absent as module attributes.

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
python -m pytest \
  tests/test_causal_diff_ownership.py \
  tests/test_causal_diff_inference.py \
  tests/test_causal_diff_owner_architecture.py -q
```

Expected: FAIL because effects/inference still traverse raw v2 owner edges and import the old helpers.

- [ ] **Step 4: Make certificate deltas available to effects**

In `run_causal_diff()`, change orchestration to:

```python
alignment = align_anchor(graph_pair, options.retail_offset, options.assertions)
comparisons = build_role_comparisons(alignment, graph_pair)
deltas = diff_frontiers(graph_pair, comparisons)
all_comparisons = comparisons + deltas
effects = derive_effects(alignment, graph_pair, all_comparisons)
store.add_comparisons(all_comparisons)
```

In `effects.py`, remove the six v2 edge names from `_OWNERSHIP_EDGE_KINDS` and remove all calls into `object_binding_adapter`. Move the legacy reachability traversal to `legacy_reachable_records(graph, roots)`, where the shared `maps-to-allocator-node` relation remains available only for non-v2 records. Certificate-mediated effects bypass this helper completely.

Create certificate stack effects only from `backend-owner-state-changed`. Validate that its correspondence and both certificate endpoints exist, match the allocator operand, and are members of each graph's trusted result. Read offsets/sizes from the two semantic states and set `owner_record_ids` to the certificate IDs. Add `owner_operand_key: str | None = None` as the final `StackEffect` field and require it to equal the allocator effect operand when pairing certificate effects.

- [ ] **Step 5: Replace inference graph search with trusted certificate consumption**

Remove the six v2 owner edge literals from inference. Move the legacy owner-specific simple-path search to `legacy_simple_paths(query, source_id, target_id, max_depth)`, which may traverse the shared allocator mapping only after its categorical v2 parser/capture exclusion. Certificate-mediated alternatives never call this helper.

For a certificate-mediated pair, `_owner_alternatives()` must:

1. Select one matching `backend-owner-corresponds-to` and one matching `backend-owner-state-changed`.
2. Resolve both endpoint nodes from the store.
3. Require each endpoint to be returned by the compile's trusted `OwnerCertificateResult.certificate()`.
4. Require the delta provenance to cite the correspondence and both certificates.
5. Render proof paths as `(certificate_id, *path_record_ids, *raw_support_record_ids)` directly from each certificate's immutable attributes.
6. Never call `neighbors()` or `find_edges()` for a v2 owner relation.

For certificate-mediated inference, gate 4 is satisfied only when `assigned_physical_register` differs in the certified semantic states, gate 5 only when `(stack_offset, stack_size)` differs, gate 6 only when exactly one correspondence/delta matches the effect pair, gate 7 only when both endpoints resolve through trusted results, and gate 8 only when no matching `backend-owner-abstained` comparison or integrity failure exists. These checks replace generic allocator/stack `node-changed` requirements for this path.

Because Phase 1 has no source certificate, a unique complete changed pair must pass gates 1–8 and return `ABSTAIN` at gate 9 with no backend recommendation elevated to a causal verdict. Legacy source-binding behavior remains unchanged.

- [ ] **Step 6: Remove the old proof surface from the diagnostic adapter**

Delete `proof_complete()`, `exact_owner_path_record()`, `owner_edge_requires_exact_v2()`, `bilateral_source_object_records()`, and `derive_backend_frame_recommendation()` from `object_binding_adapter.py` and its `__all__`.

Remove `ObjectBindingEvidence.abstention_reason`; report construction reads `BackendEvidence.owner_abstention_reason` instead. The adapter now emits diagnostics only, and `owner_certificate.py` contains the sole copy of the exact support/path validation rules.

- [ ] **Step 7: Run tests and commit**

Run:

```bash
python -m pytest \
  tests/test_causal_diff_ownership.py \
  tests/test_causal_diff_inference.py \
  tests/test_causal_diff_object_bindings.py \
  tests/test_causal_diff_owner_architecture.py -q
```

Expected: PASS.

```bash
git add \
  tools/melee-agent/src/mwcc_debug/causal_diff/commands.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/effects.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/inference.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/legacy_ownership.py \
  tools/melee-agent/src/mwcc_debug/causal_diff/object_binding_adapter.py \
  tools/melee-agent/tests/owner_certificate_fixtures.py \
  tools/melee-agent/tests/test_causal_diff_ownership.py \
  tools/melee-agent/tests/test_causal_diff_inference.py \
  tools/melee-agent/tests/test_causal_diff_object_bindings.py \
  tools/melee-agent/tests/test_causal_diff_owner_architecture.py
git commit -m "refactor: consume certified owner provenance"
```

---

### Task 6: Prove Strict Abstention, Pilot Compatibility, and Full Regression Safety

**Files:**

- Modify: `tools/melee-agent/tests/test_causal_diff_draw_fighter_headers.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_object_bindings.py`
- Modify: `tools/melee-agent/tests/test_causal_diff_owner_certificates.py`
- Modify: `docs/superpowers/specs/2026-07-11-causal-object-binding-producer-design.md`
- Modify: `docs/superpowers/specs/2026-07-12-verified-owner-path-certificate-design.md`

**Interfaces:**

- Consumes: Tasks 1–5 and the existing committed v1 DrawFighterHeaders fixtures.
- Produces: final regression proof for current v2 abstention, synthetic future-complete gate 9, legacy pilot stability, CLI/store determinism, and documentation of the new trust boundary.
- Does not regenerate Task 10 retail artifacts; that remains the next producer task after this amendment is complete.

- [ ] **Step 1: Add final acceptance tests**

Add or retain these exact outcomes:

```python
def test_current_genuine_v2_has_no_certificate_or_owner_verdict(validated_current_v2_bundle):
    backend = adapt_backends(validated_current_v2_bundle)
    assert backend.owner_certificates.certificate_nodes == ()
    assert backend.owner_abstention_reason == "backend-owner-path-incomplete"


def test_synthetic_future_complete_pair_reaches_only_gate_9():
    report = run_synthetic_future_complete_pair()
    assert any(item.relation_kind == "backend-owner-corresponds-to" for item in report.comparisons)
    assert any(item.relation_kind == "backend-owner-state-changed" for item in report.comparisons)
    verdict = only(report.verdicts)
    assert verdict.status is VerdictStatus.ABSTAIN
    assert verdict.failed_gates == ("gate-9-source-object-binding",)
    assert "source-object-binding-missing" in report.missing_evidence


def test_draw_fighter_headers_v1_report_is_unchanged(tmp_path):
    report = run_pilot(tmp_path)
    assert report.analysis_status is AnalysisStatus.ABSTAINED
    assert report.verdicts == ()
    assert report.effects.allocator_effects == ()
    assert {(item.operand_key, item.reason) for item in report.effects.abstentions} == {
        ("def:0", AbstentionReason.AMBIGUOUS_BACKEND_ROLE),
        ("use:0", AbstentionReason.AMBIGUOUS_BACKEND_ROLE),
    }
    stack = report.effects.stack_effects[0]
    assert stack.expected_offset == 0x44
    assert {stack.first_label: stack.first_offset, stack.second_label: stack.second_offset} == {
        "direct": 0x44,
        "paired": 0x48,
    }
```

Retain the existing in-memory versus protocol-store JSON/text byte-identity test and the forward/reversed frontier-order test.

- [ ] **Step 2: Run the final focused acceptance set**

Run:

```bash
cd tools/melee-agent
python -m pytest \
  tests/test_causal_diff_owner_certificates.py \
  tests/test_causal_diff_owner_architecture.py \
  tests/test_causal_diff_object_bindings.py \
  tests/test_causal_diff_alignment.py \
  tests/test_causal_diff_ownership.py \
  tests/test_causal_diff_inference.py \
  tests/test_causal_diff_store.py \
  tests/test_causal_diff_draw_fighter_headers.py -q
```

Expected: PASS.

- [ ] **Step 3: Run every causal-diff and producer trust-boundary regression**

Run:

```bash
python -m pytest tests/test_causal_diff_*.py -q
python -m pytest \
  tests/test_retro_backend_instrumentation_proof.py \
  tests/test_retro_backend_object_bindings.py \
  tests/test_retro_backend_pcode_lineage.py \
  tests/test_retro_backend_trace_assembler.py \
  tests/test_retro_struct_map.py -q
```

Expected: PASS. If unrelated in-progress tests still fail, record the exact test IDs and preserve the certificate-focused green commands; do not weaken causal expectations to absorb them.

- [ ] **Step 4: Run branch-local CLI and repository verification**

Run:

```bash
cd tools/melee-agent
python -m src.cli debug inspect causal-diff --help
cd ../..
python configure.py
ninja
git diff --check
```

Expected: CLI help exits 0, the repository build succeeds, and `git diff --check` prints nothing.

- [ ] **Step 5: Update the two design documents with implemented facts**

In the producer design, mark Task 9's loose traversal API as superseded by `causal-owner-certificate.v1` and leave Task 10 artifact regeneration open. In the certificate design, record the implemented parser/relation names, closed rejection reasons, architectural test, focused verification commands, and the fact that current genuine v2 artifacts still abstain because the registry lacks the required capabilities.

Do not claim source ownership, a final `causes` verdict, a promoted proof registry, or regenerated DrawFighterHeaders v2 artifacts.

- [ ] **Step 6: Commit the acceptance proof**

```bash
git add \
  tools/melee-agent/tests/test_causal_diff_draw_fighter_headers.py \
  tools/melee-agent/tests/test_causal_diff_object_bindings.py \
  tools/melee-agent/tests/test_causal_diff_owner_certificates.py \
  docs/superpowers/specs/2026-07-11-causal-object-binding-producer-design.md \
  docs/superpowers/specs/2026-07-12-verified-owner-path-certificate-design.md
git commit -m "test: prove certified owner provenance abstention"
```

---

## Completion Gate

This amendment is complete only when all six task commits pass their focused tests and two-stage reviews; certificates are content-addressed first-class evidence nodes; per-role unique/missing/ambiguous/contradictory/incomplete outcomes are deterministic; compatible rejections prevent uniqueness; multi-output lineage and split physical assignment are handled correctly; direct construction/deserialization remains non-proof-capable; downstream modules cannot import or traverse loose v2 ownership evidence; equal semantics emit no owner delta; changed semantics emit one reconstructable delta; current genuine v2 evidence abstains; the synthetic future-complete pair reaches only gate 9; the existing DrawFighterHeaders v1 pilot is unchanged; and all relevant causal-diff, producer, CLI, store, and build checks are green or have unrelated failures reported verbatim.
