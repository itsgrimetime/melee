# Verified Owner-Path Certificate Design

## Status and scope

This document amends the Task 9 adapter architecture in
`2026-07-11-causal-object-binding-producer-design.md`. It does not change the
retail producer schemas, promote the GC/1.2.5n proof registry, implement Phase
2 source binding, or add the persistent provenance database. It replaces the
repeated reconstruction of ownership proof in alignment, differencing,
effects, and inference with one immutable, capture-scoped certificate.

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
It returns `OwnerCertificateResult`, containing a canonical tuple of zero or more
`VerifiedOwnerPathCertificate` values plus explicit rejection records. It never
joins frontiers and never compares capture-local IDs across runs.

Alignment, differencing, effects, and inference may consume certificates. They
must not independently traverse loose ownership edges, call a weaker record
predicate, or infer missing relations from matching numeric IDs.

Legacy v1 and patched-DLL artifacts never produce certificates. Current genuine
v2 artifacts also produce no certificate because the installed proof registry
does not grant the required object-to-virtual and object-to-frame capabilities.
Their exact result remains `backend-owner-path-incomplete` with no ownership
recommendation or causal verdict.

## Certificate model

The implementation introduces frozen, JSON-compatible dataclasses with closed
fields.

```python
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
class VerifiedOwnerPathCertificate:
    schema: Literal["owner-proof-certificate.v1"]
    certificate_id: str
    compile_id: str
    capture_run_id: str
    function: str
    artifact_sha256: str
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
    effective_confidence: Confidence


@dataclass(frozen=True, slots=True)
class OwnerCertificateRejection:
    rejection_id: str
    reason: str
    role: OwnerRoleKey | None
    candidate_record_ids: tuple[str, ...]
    raw_support_record_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OwnerCertificateResult:
    certificates: tuple[VerifiedOwnerPathCertificate, ...]
    rejections: tuple[OwnerCertificateRejection, ...]
    missing_reason: str | None
```

`certificate_id` is content-derived from the schema, compile ID, capture-run ID,
function, role, semantic state, canonical path record IDs, and raw support record
IDs. It is capture-scoped by design. Runtime pointers are never fields and never
participate in an ID.

The cross-frontier semantic identity is only `OwnerRoleKey`. The cross-frontier
changed state is only `OwnerSemanticState`. Compile IDs, capture IDs, object IDs,
PCode IDs, lineage IDs, virtual/IG numbers, record IDs, raw snapshots, and
runtime addresses remain provenance and cannot create a semantic delta.

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
12. Every finite alternative is preserved. Zero valid candidates is incomplete;
    more than one valid candidate is ambiguous. Neither case is converted to a
    negative ownership fact.

`build_owner_certificates()` validates these invariants as one operation. It
does not expose a public per-record boolean predicate that downstream consumers
could combine into a different proof.

## Data flow

1. `adapt_object_bindings()` independently reloads and verifies the immutable
   v2 trace and candidate object, runs the existing producer validators, and
   emits diagnostic graph evidence exactly as today.
2. `build_owner_certificates(evidence, requested_roles)` constructs canonical
   certificates and rejections from that evidence.
3. `BackendEvidence` carries both diagnostic graph records and the certificate
   result. Diagnostic records remain useful for reporting and a future database,
   but they do not grant ownership by themselves.
4. Alignment selects certificates by `OwnerRoleKey`. Exactly one certificate on
   each side produces `backend-owner-corresponds-to`; zero yields incomplete;
   any multiplicity yields `backend-owner-ambiguous` with all alternatives.
5. Differencing compares the two `OwnerSemanticState` values. Equal states emit
   no owner delta. Different states emit one owner delta whose provenance cites
   the correspondence and both certificates and whose confidence is their
   minimum.
6. Effects and inference consume the certificate comparison/delta directly.
   Human proof paths are rendered from `path_record_ids` and
   `raw_support_record_ids`; no downstream graph search re-establishes proof.
7. Phase 1 still has no source binding. A unique changed owner certificate pair
   therefore reaches only `gate-9-source-object-binding` and abstains with
   `source-object-binding-missing`.

## Ambiguity and canonical ordering

Alternatives are represented as a canonical multiset of certificate summaries,
not by caller order and not by `ComparisonRecord.record_id` alone.

The summary contains the certificate ID, role, semantic state, effective
confidence, and canonical provenance IDs. Alternatives are sorted by canonical
JSON bytes. Exact duplicates retain a multiplicity count and their complete,
canonically sorted provenance summaries. Reversing input order must produce
byte-identical ambiguity records and reports.

Diagnostic alternatives that fail certificate construction are retained as
`OwnerCertificateRejection` values with content-derived rejection IDs. A
heuristic or malformed alternative can force abstention but can never become a
certificate or be promoted to derived-unique.

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
- no source binding after a unique changed pair: gate-9 abstention.

No error path compiles code, refreshes artifacts, writes source, promotes the
registry, or mutates an input bundle.

## Persistence compatibility

The certificate is a versioned derived record, not a database implementation.
Its content-derived ID, closed schema, raw support references, compile/capture
scope, and JSON-compatible values allow a later provenance store to persist and
index it without changing causal inference.

The later database may store certificates, rejections, raw evidence, and
comparison records separately. Cross-frontier comparisons remain
analysis-scoped. Phase 2 may introduce a companion source-binding certificate
or `owner-proof-certificate.v2`; it must not mutate historical v1 certificates
or reinterpret their IDs.

## Testing and acceptance

Implementation uses strict red-green-refactor cycles and replaces Task 9's
proof-bearing loose traversal with certificate tests.

Required coverage includes:

- a complete valid certificate and every individual invariant failure;
- coordinated physical-register mutations across rewrite/virtual/allocator/map
  while decoded emission remains unchanged;
- multi-output mutation events with distinct per-output parent sets;
- mutation parent subset, replacement, superset, duplicate, order, side, kind,
  and event-index failures;
- zero, one, and multiple certificates for a role;
- identical semantics across different captures producing no delta;
- real allocator or stack semantic changes producing one reconstructable delta;
- input permutation and duplicate alternatives producing byte-identical output;
- mixed v1/pcdump/v2 numeric collisions producing no certificate;
- every certificate and delta confidence bounded by all cited inputs;
- current genuine v2 evidence returning `backend-owner-path-incomplete` with no
  recommendation or verdict;
- existing v1 `mnDiagram_DrawFighterHeaders` behavior unchanged;
- a synthetic future-complete pair reaching only gate 9; and
- all causal-diff, producer trust-boundary, canonicalization, CLI, and store
  regressions remaining green.

Task 9 is complete only after an independent reviewer confirms that downstream
modules cannot manufacture, strengthen, or reconstruct an ownership proof from
loose graph evidence.
