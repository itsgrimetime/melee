# Verified Owner-Path Certificate Design

## Status and scope

This document amends the Task 9 adapter architecture in
`2026-07-11-causal-object-binding-producer-design.md`. It does not change the
retail producer schemas, promote the GC/1.2.5n proof registry, implement Phase
2 source binding, or add the persistent provenance database. It replaces the
repeated reconstruction of ownership proof in alignment, differencing,
effects, and inference with one immutable, capture-scoped certificate.

### Implemented status and explicit non-claims

The Phase 1 certificate boundary is implemented. Certificate nodes use kind
`owner-proof-certificate` and parser `causal-owner-certificate.v1`.
Cross-frontier consumers recognize these exact certified relations and producer
parsers:

- `backend-owner-corresponds-to` and `backend-owner-abstained` are emitted by
  `causal-backend-owner-alignment.v2`;
- `backend-owner-state-changed` is emitted by
  `causal-frontier-differ.v1`; and
- effects and inference require the exact correspondence and state-delta parser
  identities before a certificate-mediated effect or proof path is eligible.

The implementation does **not** claim source ownership, a final `causes`
verdict, a promoted GC/1.2.5n proof registry, or regenerated
`mnDiagram_DrawFighterHeaders` v2 artifacts. Task 10 retail artifact
regeneration remains open. A complete synthetic certificate pair therefore
abstains only at `gate-9-source-object-binding`; this is an acceptance result,
not a positive causal verdict.

The refactor is required because four successive hardening passes exposed the
same architectural defect in different forms: downstream consumers can combine
individually plausible records into a path that the producer never proved as
one coherent relation. Examples included split physical-register subproofs,
event-wide lineage unions applied to per-output edges, and noncanonical
alternative identities.

## Approaches considered

### 1. One verified owner-path certificate — selected

Build and validate the complete within-capture path once, then expose a frozen
certificate to every downstream consumer. This centralizes trust, makes the
proof reconstructable, removes duplicated traversal predicates, and produces a
versioned derived record suitable for later persistence.

### 2. Continue hardening loose graph traversal — rejected

Add more predicates to `alignment.py`, `effects.py`, and `inference.py`. This is
the smallest textual change, but it has already failed repeatedly: each layer
can select a different locally valid subpath or forget one cross-check. More
patches would preserve the architectural source of the defects.

### 3. Implement the persistent provenance database now — rejected

Store every raw and derived record first, then query ownership through a typed
database layer. This could solve identity and auditability, but persistence,
migrations, retention, and historical query semantics are outside the approved
Phase 1 scope. The certificate contract below is intentionally serializable so
this option remains available later without changing causal semantics.

## Trust boundary

`owner_certificate.py` is the only module allowed to turn verified v2 object,
PCode, allocator, and frame evidence into proof-capable backend ownership.

The module consumes one `ObjectBindingEvidence` from one compile and one capture.
It derives every connected capture-local role; it does not accept
`requested_roles`. It returns `OwnerCertificateResult`, containing canonical
certificate nodes, per-role resolutions, and explicit global rejections. It
never joins frontiers and never compares capture-local IDs across runs.

Alignment, differencing, effects, and inference may consume the result and its
registered certificate nodes. They must not independently traverse loose
ownership edges, call a weaker record predicate, or infer missing relations
from matching numeric IDs.

Legacy v1 and patched-DLL artifacts never produce certificates. Current genuine
v2 artifacts also produce no certificate because the installed proof registry
does not grant the required object-to-virtual and object-to-frame capabilities.
Their exact result remains `backend-owner-path-incomplete` with no ownership
recommendation or causal verdict.

The refactor removes public `proof_complete()`, `exact_owner_path_record()`, and
backend-frame recommendation helpers from `object_binding_adapter.py`.
Ownership-edge vocabularies and raw `ObjectBindingEvidence` are not imported by
`alignment.py`, `differ.py`, `effects.py`, or `inference.py`. An architectural
AST/import test enforces both rules and also rejects ownership-edge traversal in
those modules.

Diagnostic ownership nodes, edges, and capabilities remain in `BackendEvidence`
for reporting and later persistence, but their Python type and adapter result do
not expose a proof-capable flag. Only the module-private certificate builder may
interpret them as proof.

Direct construction or deserialization of a certificate node is not a trusted
path. Current analysis consumes the in-memory `OwnerCertificateResult` returned
by the builder. A future persisted certificate is trusted only after reloading
its cited immutable evidence, rebuilding the certificate through
`owner_certificate.py`, and byte-comparing the rebuilt node. A certificate node
without that result/revalidation context remains diagnostic and cannot satisfy
an inference gate.

## Certificate and resolution model

The persisted certificate is a first-class `EvidenceNode` with kind
`owner-proof-certificate`. This deliberately reuses the existing store
contract: it has `record_id`, `compile_id`, `confidence`, `provenance`, and
closed JSON-compatible attributes. Its provenance names every path and raw
support record, so a later `ComparisonRecord` can cite the certificate node and
the store can resolve both the input record and its confidence.

The implementation also introduces frozen, module-constructed views with closed
fields. Their constructors are private to `owner_certificate.py`; downstream
code receives them only through `OwnerCertificateResult`.

```python
class OwnerResolutionStatus(StrEnum):
    UNIQUE = "unique"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    CONTRADICTORY = "contradictory"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class OwnerRoleKey:
    operand_key: str
    register_class: str
    semantic_stack_role: str
    type_size: int
    frame_area: str


@dataclass(frozen=True, slots=True)
class OwnerSemanticState:
    assigned_physical_register: int
    stack_offset: int
    stack_size: int


@dataclass(frozen=True, slots=True)
class _VerifiedOwnerPathCertificate:
    record: EvidenceNode  # kind == "owner-proof-certificate"
    role: OwnerRoleKey
    semantic_state: OwnerSemanticState
    owner_record_id: str
    anchor_record_id: str
    pcode_record_id: str
    lineage_record_ids: tuple[str, ...]
    virtual_record_id: str
    allocator_record_id: str
    stack_record_id: str
    path_record_ids: tuple[str, ...]
    raw_support_record_ids: tuple[str, ...]
    proof_content_sha256: str
    effective_confidence: Confidence


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
```

The node uses parser `causal-owner-certificate.v1`. Its local identity is
`proof_content_sha256`, a digest over the complete canonical validated proof
payload: schema; compile/capture/function/artifact identity; role; semantic
state; full canonical content of every cited path/support record (record kind,
confidence, attributes, and provenance); and the trusted instrumentation tuple
`(compiler_executable_sha256, proof_id, proof_sha256, registry_schema)`. The
resulting `record_id` therefore changes even when a source record retains its ID
through `with_attributes()` but changes its content. Runtime pointers are
excluded from both the proof payload and ID.

The cross-frontier semantic identity is only `OwnerRoleKey`. The cross-frontier
changed state is only `OwnerSemanticState`. Compile IDs, capture IDs, object IDs,
PCode IDs, lineage IDs, virtual/IG numbers, record IDs, raw snapshots, and
runtime addresses remain provenance and cannot create a semantic delta.

The canonical vocabularies are closed before hashing:

- `operand_key`: `^(def|use):(0|[1-9][0-9]*)$`;
- `register_class`: exactly `gpr` or `fpr`;
- `semantic_stack_role`: `^[a-z][a-z0-9-]{0,63}$`;
- `frame_area`: exactly `arguments`, `locals`, or `temps`;
- `type_size` and `stack_size`: integer, not `bool`, in `1..0x7FFFFFFF`;
- `assigned_physical_register`: integer, not `bool`, in `0..31`; and
- `stack_offset`: integer, not `bool`, in `-0x80000000..0x7FFFFFFF`.

Aliases such as `r`, `f`, or `GPR` are normalized before certificate
construction and are never accepted in a certificate payload.

## Certificate construction invariants

A certificate exists only when one connected path satisfies every invariant
below in the same compile, function, artifact, capture-run ID, and verified v2
parser domain.

1. The independently reverified capability set contains every required owner
   capability. Manifest declarations and embedded status text are not authority.
2. Every path node, edge, and raw support record is registered in the exact
   `ObjectBindingEvidence` value being certified.
3. Every record has observed or derived-unique effective confidence. The
   certificate confidence is the minimum of all path and raw support inputs.
4. The assembly anchor, PCode code range, candidate-object decoded operand, and
   emission mapping agree on code offset, operand key, register class, and
   physical register.
5. The PCode instance has exactly one allocation generation and the selected
   range, emission, rewrite, and lineage events name that generation.
6. Mutation lineage is replayed per output. Each output records its exact
   canonical parent set, event index, side, and mutation kind. Multi-output
   events may have different parent sets. Subsets, supersets, duplicates,
   noncanonical ordering, or event-wide unions are invalid.
7. The selected output lineage has exactly one allocator origin. The origin's
   class, virtual, and allocated physical register agree with the rewrite,
   decoded emission, virtual node, allocator node, and mapping edge.
8. The compiler object has exactly one allocation generation and its
   object-to-virtual binding agrees with the selected class, virtual, and IG
   inside this capture.
9. The allocator assignment used in `OwnerSemanticState` comes from the unique
   validated allocator origin, not from an allocator node's self-asserted field.
10. The final frame binding agrees on object generation, area, semantic role,
    final R1 offset, and size. The stack state comes from this binding.
11. All required raw support relations use closed, typed schemas. Unknown keys,
    missing keys, semantically foreign records, and internally inconsistent but
    coordinated mutations invalidate the candidate.
12. The canonical proof-content digest covers full path/support record content
    and the independently trusted instrumentation tuple, not record IDs alone.
13. Every finite alternative is preserved in its role resolution. A certificate
    and a role-compatible rejection can never resolve as unique. Zero valid
    candidates is missing or incomplete; more than one valid or plausible
    candidate is ambiguous. Contradictory positive facts are contradictory.
    None of these cases is converted to a negative ownership fact.

`build_owner_certificates(evidence)` validates these invariants as one
operation. It does not expose a public per-record boolean predicate that
downstream consumers could combine into a different proof.

Certificate nodes and their cited diagnostic nodes/edges are added to the
existing evidence store atomically. Every certificate provenance input resolves
to a registered record with `.confidence`; comparisons and deltas cite the
certificate node IDs under the existing store contract.

## Data flow

1. `adapt_object_bindings()` independently reloads and verifies the immutable
   v2 trace and candidate object, runs the existing producer validators, and
   emits diagnostic graph evidence exactly as today.
2. `build_owner_certificates(evidence)` enumerates every connected capture-local
   path, derives its canonical `OwnerRoleKey`, constructs certificate nodes, and
   resolves all observed roles. Caller-supplied roles and duplicate requests
   cannot manufacture certificates or ambiguity.
3. Certificate nodes are included in the same `AdapterResult` as their cited
   diagnostic records so store ingestion remains atomic. `BackendEvidence`
   carries the diagnostic records plus the in-memory `OwnerCertificateResult`.
4. Alignment normalizes its requested role and looks it up in the result. A role
   absent from the result is `missing`. A global `role=None` rejection taints
   every lookup as `incomplete`. Exactly one certificate with no compatible or
   global rejection is `unique`. More than one certificate, or one certificate
   plus a plausible role-compatible rejection, is `ambiguous`. Conflicting
   positive facts are `contradictory`; malformed, unsupported, or truncated
   candidates are `incomplete`.
5. Only `unique` on both sides produces `backend-owner-corresponds-to`. Every
   other bilateral combination emits a deterministic abstention comparison with
   all relevant certificates and rejections.
6. Differencing compares the two `OwnerSemanticState` values. Equal states emit
   no owner delta. Different states emit one owner delta whose provenance cites
   the correspondence and both certificates and whose confidence is their
   minimum.
7. Effects and inference consume the certificate comparison/delta directly.
   Human proof paths are rendered from `path_record_ids` and
   `raw_support_record_ids`; no downstream graph search re-establishes proof.
8. Phase 1 still has no source binding. A unique changed owner certificate pair
   therefore reaches only `gate-9-source-object-binding` and abstains with
   `source-object-binding-missing`.

## Ambiguity and canonical ordering

Each `OwnerRoleResolution` contains the certificates and rejections relevant to
that role. `role=None` rejections live in `global_rejections` and force every
alignment lookup to `incomplete`; they are never silently assigned to one role.
Mixed roles therefore retain independent statuses—for example, one unique role,
one missing role, and one ambiguous role can coexist in one result.

Alternatives are represented as a canonical multiset of certificate and
rejection summaries, not by caller order and not by
`ComparisonRecord.record_id` alone.

The summary contains the certificate record ID, role, semantic state, effective
confidence, and canonical provenance IDs. Alternatives are sorted by canonical
JSON bytes. Exact duplicates retain a multiplicity count and their complete,
canonically sorted provenance summaries. Reversing input order must produce
byte-identical ambiguity records and reports.

Diagnostic alternatives that fail certificate construction are retained as
`OwnerCertificateRejection` values with content-derived rejection IDs. A
heuristic or malformed alternative can force abstention but can never become a
certificate or be promoted to derived-unique.

The role status is derived from the complete multiset after canonical grouping,
never by counting certificates before rejections. One valid certificate plus
one role-compatible heuristic alternative is ambiguous, not unique. Repeating
the same requested role does not change the multiset or status.

## Error handling and abstention

Malformed bundles and hostile materialization errors remain `BundleInputError`.
Well-formed but incomplete, contradictory, unsupported, or ambiguous ownership
evidence is analysis data, not an input exception. It returns certificates plus
rejections and causes deterministic abstention.

The certificate builder is fail-closed:

- unsupported parser or missing capability: no certificate;
- mixed process-local identity domains: no certificate;
- truncated or unregistered support: no certificate;
- split physical-register subproof: no certificate;
- incomplete or multi-parent lineage origin: no certificate;
- multiple role-compatible certificates: explicit ambiguity abstention;
- one certificate plus a role-compatible rejection: explicit ambiguity,
  contradiction, or incomplete abstention according to the rejection class;
- no source binding after a unique changed pair: gate-9 abstention.

The implemented certificate rejection vocabulary is closed to:

- `untrusted-diagnostic-materialization`;
- `missing-required-capability`;
- `missing-instrumentation-identity`;
- `mixed-record-scope`;
- `unregistered-support`;
- `malformed-support`;
- `disconnected-owner-path`;
- `plausible-owner-alternative`;
- `split-physical-assignment`;
- `lineage-parent-mismatch`;
- `allocator-origin-contradiction`; and
- `frame-binding-contradiction`.

Unknown reasons fail validation rather than widening this vocabulary.

No error path compiles code, refreshes artifacts, writes source, promotes the
registry, or mutates an input bundle.

## Persistence compatibility

The certificate node is a versioned derived evidence record, not a database
implementation. Its proof-content-derived ID, closed schema, raw support
references, compile/capture scope, `.confidence`, `.provenance`, and
JSON-compatible values allow the existing store to ingest/query it and a later
provenance store to persist/index it without changing causal inference.

The later database may store certificates, rejections, raw evidence, and
comparison records separately. Cross-frontier comparisons remain
analysis-scoped. Phase 2 may introduce a companion source-binding certificate
or `owner-proof-certificate.v2`; it must not mutate historical v1 certificates
or reinterpret their IDs.

Persistence does not make a certificate self-authenticating. A store round-trip
preserves bytes and references, but proof-capable loading requires the cited raw
evidence and instrumentation registry identity to be available for deterministic
rebuild-and-compare validation.

## Testing and acceptance

Implementation uses strict red-green-refactor cycles and replaces Task 9's
proof-bearing loose traversal with certificate tests.

The architectural boundary is enforced by
`tests/test_causal_diff_owner_architecture.py`, including
`test_downstream_modules_cannot_reconstruct_raw_owner_proof` and
`test_legacy_owner_helpers_categorically_reject_v2_records`. Final focused
acceptance is exercised with:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  tests/test_causal_diff_owner_certificates.py \
  tests/test_causal_diff_owner_architecture.py \
  tests/test_causal_diff_object_bindings.py \
  tests/test_causal_diff_alignment.py \
  tests/test_causal_diff_ownership.py \
  tests/test_causal_diff_inference.py \
  tests/test_causal_diff_store.py \
  tests/test_causal_diff_draw_fighter_headers.py \
  -q -p no:cacheprovider --no-cov --override-ini='addopts='
```

Every causal-diff test and the producer trust boundary are checked separately:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_causal_diff_*.py \
  -q -p no:cacheprovider --no-cov --override-ini='addopts='
PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  tests/test_retro_backend_instrumentation_proof.py \
  tests/test_retro_backend_object_bindings.py \
  tests/test_retro_backend_pcode_lineage.py \
  tests/test_retro_backend_trace_assembler.py \
  tests/test_retro_struct_map.py \
  -q -p no:cacheprovider --no-cov --override-ini='addopts='
```

Required coverage includes:

- a complete valid certificate and every individual invariant failure;
- coordinated physical-register mutations across rewrite/virtual/allocator/map
  while decoded emission remains unchanged;
- multi-output mutation events with distinct per-output parent sets;
- mutation parent subset, replacement, superset, duplicate, order, side, kind,
  and event-index failures;
- zero, one, and multiple certificates for a role;
- one valid certificate plus one role-compatible rejection never resolving as
  unique;
- independent unique, missing, ambiguous, contradictory, and incomplete role
  resolutions in one result, including `role=None` global rejection behavior;
- duplicate role lookups not manufacturing a certificate or ambiguity;
- identical semantics across different captures producing no delta;
- real allocator or stack semantic changes producing one reconstructable delta;
- input permutation and duplicate alternatives producing byte-identical output;
- mixed v1/pcdump/v2 numeric collisions producing no certificate;
- every certificate and delta confidence bounded by all cited inputs;
- certificate-node ingestion/query round-trip under `InMemoryEvidenceStore` and
  the store-conformance suite;
- direct certificate-node forgery or deserialization without rebuild context
  remaining non-proof-capable;
- a cited record changing content through `with_attributes()` while retaining
  its record ID changing the proof-content digest and certificate record ID;
- architectural import checks proving only `owner_certificate.py` interprets
  loose v2 ownership evidence;
- current genuine v2 evidence returning `backend-owner-path-incomplete` with no
  recommendation or verdict;
- existing v1 `mnDiagram_DrawFighterHeaders` behavior unchanged;
- a synthetic future-complete pair reaching only gate 9; and
- all causal-diff, producer trust-boundary, canonicalization, CLI, and store
  regressions remaining green.

Task 9 is complete only after an independent reviewer confirms that downstream
modules cannot manufacture, strengthen, or reconstruct an ownership proof from
loose graph evidence.
