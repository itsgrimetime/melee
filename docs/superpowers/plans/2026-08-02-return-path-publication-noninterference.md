# Return-Path Publication Noninterference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic lifecycle-only certificate that proves a published
object generation cannot be mutated through any synchronous path returning to
its later field observation.

**Architecture:** A v6 object-tag lifecycle evaluation context permits the
existing preservation routines to request one narrow publication
noninterference certificate. The certificate binds an exact same-generation
slice, returning direct/finite call closure, opaque-actual effects, protected
slot references, exact imports, and a context-bound allocator-totality/backend
session bridge. Reference fingerprints remain query-independent; the internal
certificate separately proves closure disjointness and per-body address
domains. `_recover_indexed_table` emits a non-mutating tentative table
hypothesis only after validating its entries. A disposable accepted-candidate
trial may install the table provisionally, close the graph with its edges,
finalize dependency-affecting normalization, and then recompute lifecycle v6;
only this post-install certificate reproduces the hypothesis. Provisional
executable rows flow to an exact-set external Ghidra/residue publication gate.
Dependency-bearing memo entries replay all nested totality and publication
dependencies into the unchanged durable lifecycle checkpoint schema, while
warm finite hits recompute typed evidence without spending budget.

**Tech Stack:** Python 3, Capstone x86-32 detail mode, PE relocations/imports,
pytest synthetic PE fixtures, canonical producer checkpoints, branch-local
`melee-agent debug retro probe-backend-map`.

## Global Constraints

- Run `melee-agent capabilities search <task>` before adding any new helper or
  command. This plan adds no CLI command.
- Work only in the active isolated worktree. Run branch-local CLI code with
  `cd tools/melee-agent && python -m src.cli ...`.
- Keep `_MOVZX_PRODUCER_ANALYSIS_SEMANTICS` exactly
  `movzx-producer-analysis-v27`.
- Advance `_OBJECT_TAG_LIFECYCLE_ANALYSIS_SEMANTICS` exactly from
  `object-tag-lifecycle-analysis-v5` to
  `object-tag-lifecycle-analysis-v6` in Task 2, in the same commit that first
  enables the changed lifecycle behavior. Never commit the new proof meaning
  under the v5 identity.
- Keep `_OBJECT_TAG_LIFECYCLE_CERTIFICATE_SCHEMA` at
  `mwcc-retro-x86-object-tag-lifecycle-certificate-v1` and keep
  `_ObjectTagLifecycleQuery` fields unchanged.
- Keep internal typed publication witnesses out of checkpoint schema v1.
  Persist only the existing aggregate query/result and dependency
  rows/fingerprints.
- Enable the new exception only inside an active v6 object-tag lifecycle
  evaluation. Every producer and non-lifecycle preservation caller retains the
  existing publication rejection.
- Install one lifecycle context per active consumer binding with
  `consumer_entry=binding.function_entry`, decoded from persisted `binding[0]`.
  The publication owner and
  certificate caller must equal that consumer; never use the query's minimum
  `function_entry` as a semantic caller.
- Derive every slice, closure, target, slot, import, caller, owner, session, and
  backend root structurally. Put no retail address allowlist in production.
- Require strict `_incoming_call_domain_is_closed`; do not use
  `_least_reachable_incoming_call_domain_is_closed` for the backend bridge.
- Treat `0x587ffc`-style copying as an opaque-copy escape, never as no-escape.
- Bind typed taint origins/flows, full reference rows and digest, complete
  backend bridges/closures, parsed import lookup mode/effects, and typed opaque
  destinations. Do not persist positional witness tuples.
- Prune allocator failure only through a context-bound
  `_AllocatorTotalityCertificate` whose backend bridge covers the lifecycle
  caller and every exact incoming owner. Allocation-caller membership alone is
  insufficient.
- Keep the exact system-import trust boundary to PE-bound identities and
  per-argument effects; never accept arbitrary imports as pure.
- Trust production imports through strict parsed `pe.Import` rows plus compiler
  SHA. Use a raw parsed PE fixture for ordinal/name and changed-IAT integrity
  tests loaded through `pe_mod.load`; a hand-built `Image.imports` row proves
  only semantic matching.
- Make `absolute-reference` fingerprints query-independent: complete raw rows,
  source classifications, exact ownership/data/provisional intervals, and
  recovery revisions only. Raw rows are type-3 or decoded literal references
  exactly equal to the slot; finite arithmetic/materialization domains belong
  only to function-dependent body witnesses. Never put a closure-relative
  safety boolean in the slot-keyed dependency.
- During recovery, treat an exact unowned executable source only as
  provisional. The internal certificate separately binds its span's
  disjointness from every complete returning body/range, and revalidates after
  the ownership fixed point.
- Require existing external Ghidra/residue reconciliation to accept every
  provisional certificate row before final publication. Lifecycle recovery
  never consults `UnreachableExecutableResidue.accepted`.
- Key memo lookups and bottom entries only by structural inputs and current
  revisions. Witness digests belong to stored successful results, never lookup
  keys.
- Treat a republish as a generation cut only when the new value is a distinct
  closed generation and no live alias preserves the old identity.
- Fail closed on unresolved targets, unknown address materialization, open
  caller domains, returning failure callbacks, hostile actual effects,
  incomplete reference reconciliation, analysis limits, or stale dependencies.
- Preserve existing relocation, executable-target, table-bound, and rejection
  ledger checks.
- Never let the preservation helper synthesize target records or install table
  state. The entry-reading table layer emits a tentative hypothesis. Target
  seeding adds no table edge; an accepted-candidate trial installs the table
  only provisionally, runs installed-edge closure to quiescence, finalizes
  normalization, and recomputes exact-binding lifecycle v6 before reproduction.
  No final `RawCfg` table may depend on a pre-install certificate.
- Treat every accepted-candidate publication trial as disposable until
  definitive post-install validation succeeds. If it fails, discard its
  tables, edges, ownership, seeds, memo state, and CFG wholesale; never return
  or cache the mutated trial as `reusable_trial`.
- Run `_classify_relocations`, `_bind_seed_instruction_provenance`, typed
  data/padding finalization, and executable-complement construction before the
  definitive publication recomputation. Any later revision or fingerprint
  change restarts/rejects before `RawCfg`.
- A lifecycle-v6 warm finite checkpoint hit must recompute its typed
  certificate under exact binding contexts without budget. Only a warm
  post-install dependency variant can reproduce current table/audit evidence;
  it must exactly match the stored aggregate result and dependency tuple before
  validation.
- Treat `0x4b1f95` as an independent ESP-slot binding blocker. Do not make the
  publication certificate accept it.
- Use `apply_patch` for source and test edits. Preserve unrelated `.agents/`
  and `.pi/` worktree files.
- Follow red-green-refactor order for every task and commit only coherent green
  changes.

## File map

- `tools/mwcc_retro/x86_cfg.py`: lifecycle context, certificate data, path and
  closure analysis, actual/import/reference effects, allocator-totality memo
  replay, query-independent dependency fingerprints, non-mutating table
  hypotheses, disposable post-install trials, final-normalization revalidation,
  warm-hit rehydration, semantics bump, and rejection-ledger binding.
- `tools/mwcc_retro/backend_lifetime_audit.py`: final external reconciliation
  of provisional publication-reference obligations; the lifecycle analysis
  does not use its post-CFG accepted state.
- `tools/melee-agent/tests/test_retro_x86_cfg.py`: synthetic PE fixture,
  positive and hostile matrices, cache/dependency tests, checkpoint replay,
  and ledger invalidation.
- `tools/melee-agent/tests/test_retro_backend_lifetime_audit.py`: external
  reconciliation acceptance/failure tests for provisional publication rows.
- `docs/superpowers/results/2026-08-02-return-path-publication-noninterference.md`:
  implementation-time retail command, exact 29/30 outcome, separate
  `0x4b1f95` result, and verification evidence.

---

### Task 1: Build the synthetic proof boundary and capture RED

**Files:**

- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**

- Consumes: existing `lifecycle_movzx_dispatch_image`,
  `lifecycle_optional_allocation_pointee_image`, `_DirectCfgRecovery`,
  `recover_cfg`, `build_seed_inventory`, and `generous_limits` test patterns.
- Produces: `ReturnPathPublicationFixture` and
  `return_path_publication_lifecycle_image(*, mutation: str | None = None)`,
  reused by Tasks 2-6.

- [ ] **Step 1: Re-run the capability audit and inspect nearby fixtures**

Run:

```bash
melee-agent capabilities search "x86 lifecycle publication returning call closure fixture"
rg -n "def lifecycle_movzx_dispatch_image|def lifecycle_optional_allocation_pointee_image|def test_object_tag_lifecycle" \
  tools/melee-agent/tests/test_retro_x86_cfg.py
```

Expected: no existing return-path publication certificate; reuse the existing
fixture conventions rather than adding a tool or command.

- [ ] **Step 2: Add the fixture result type and mutation vocabulary**

Add this exact interface near the lifecycle fixtures:

```python
@dataclass(frozen=True, slots=True)
class ReturnPathPublicationFixture:
    image: pe_mod.Image
    transfers: tuple[int, ...]
    consumer_entries: tuple[int, ...]
    minimum_consumer: int
    publishing_consumer: int
    incoming_calls: tuple[int, ...]
    incoming_owners: tuple[int, ...]
    publication: int
    publication_slot: int
    observation: int
    slice_addresses: tuple[int, ...]
    helper_call: int
    helper_target: int
    allocator: int
    grow_target: int
    callback_slot: int
    callback_targets: tuple[int, ...]
    session_root: int
    backend_root: int


_RETURN_PATH_PUBLICATION_MUTATIONS = frozenset(
    {
        "alternate-slice-entry",
        "partial-publication",
        "different-observation-root",
        "same-root-republish",
        "unknown-republish-root",
        "stale-alias-republish",
        "returning-unresolved-indirect",
        "extra-finite-returning-target",
        "closure-slot-read",
        "closure-slot-materialization",
        "root-actual",
        "child-actual",
        "slot-address-actual",
        "opaque-actual-dereference",
        "opaque-actual-mutation",
        "opaque-actual-unknown-forward",
        "opaque-multihop-reload-dereference",
        "wrong-import-dll",
        "wrong-import-symbol",
        "wrong-import-lookup-mode",
        "changed-import-iat",
        "unlisted-import",
        "extra-tainted-import-argument",
        "sync-handle-alias",
        "returning-failure-callback",
        "callback-slot-overwrite",
        "partial-callback-slot-overwrite",
        "reset-in-lifetime",
        "lifecycle-root-outside-backend",
        "incoming-owner-outside-backend",
        "split-backend-union",
        "unowned-raw-incoming-call",
        "exported-lifecycle-caller",
        "unreconciled-address-taken-caller",
        "unreconciled-slot-reference",
        "outside-residue-slot-reference",
        "overlapping-residue-slot-reference",
        "ownership-growth-into-returning-closure",
    }
)
```

If `dataclass` or `pe_mod` is already imported under another established name,
use that existing import and keep the field types unchanged.

- [ ] **Step 3: Implement one deterministic PE layout**

Implement `return_path_publication_lifecycle_image` with this virtual layout:

```text
0x00401000  minimum nonpublishing lifecycle consumer
0x00401080  later publishing consumer: publish -> switch -> helper -> observation
0x00401200  incoming owner A
0x00401280  incoming owner B
0x00401300  backend root calling both owners
0x00401500  checked session root
0x00401600  checked initializer
0x00401800  publication helper
0x00401900  owned bump allocator
0x00401980  grow helper with finite callback slot
0x00401a80  context save
0x00401ac0  context restore
0x00401b00  installed nonreturn callback
0x00401b40  default callback candidate
0x00403000  protected publication slot
0x00403004  callback slot
0x00403400  75-entry relocated call table
```

The baseline fixture must contain two consumers sharing the lifecycle query.
The minimum consumer does not publish; the later consumer publishes and must
be returned as `publishing_consumer`. Include tag roots 0 and 74, an exact
pointer-width publication, one switch arm whose call returns to the
observation, another arm satisfying both generation-cut conditions, exact
raw/decoded incoming calls for the publishing consumer, a checked session, and
type-3 relocations for every semantic absolute reference. The helper must copy
the first actual loaded from the synthetic root's `[root+0x16]` field into an
unrelated global and return without dereferencing it. Return every important
address through `ReturnPathPublicationFixture`; no test should rediscover
fixture constants by arithmetic.

Encode each mutation at its named semantic boundary. Reject any unknown
mutation immediately:

```python
if mutation is not None and mutation not in _RETURN_PATH_PUBLICATION_MUTATIONS:
    raise ValueError(f"unknown return-path publication mutation: {mutation}")
```

- [ ] **Step 4: Add the positive integration test that is RED before production changes**

```python
def test_object_tag_lifecycle_accepts_return_path_publication_noninterference():
    fixture = return_path_publication_lifecycle_image()

    cfg = recover_cfg(
        fixture.image,
        build_seed_inventory(fixture.image, ()),
        generous_limits(fixture.image),
    )

    assert {
        cfg.jump_table_at(transfer).guard_operator
        for transfer in fixture.transfers
    } == {"movzx-lifecycle-domain"}
    assert {
        cfg.jump_table_at(transfer).index_max
        for transfer in fixture.transfers
    } == {74}
```

- [ ] **Step 5: Add a control test proving non-lifecycle callers still reject publication**

Construct `_DirectCfgRecovery` from the same image, call the relevant
`_pointer_definition_preserves_field_before` without a lifecycle evaluation
context, and assert `False`. Also assert that a v27 producer query over the
same store does not gain `movzx-lifecycle-domain` provenance.

- [ ] **Step 6: Run the RED tests**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_x86_cfg.py \
  -k 'return_path_publication_noninterference or non_lifecycle_callers_still_reject' -vv
```

Expected: the positive integration test fails because the pointer publication
is rejected; the non-lifecycle control passes.

- [ ] **Step 7: Commit the RED fixture and tests**

```bash
git add tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "test(mwcc-retro): cover lifecycle return publication"
```

---

### Task 2: Certify the same-generation publication/observation slice

**Files:**

- Modify: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/mwcc_retro/backend_lifetime_audit.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_lifetime_audit.py`

**Interfaces:**

- Consumes: `ReturnPathPublicationFixture`, relative-pointer states,
  `_reachable_within_function`, function instruction ownership, and the two
  preservation routines.
- Produces: `_ObjectTagLifecycleEvaluationContext`,
  `_TrackedPublicationRoot`,
  `_ReturnPathPublicationNoninterferenceCertificate`, and
  `_return_path_publication_noninterference_certificate(...)` with path and
  identity fields populated. Call closure fields remain empty until Task 3.

- [ ] **Step 1: Add unit RED tests for publication shape and root identity**

Add this matrix:

```python
@pytest.mark.parametrize(
    "mutation",
    (
        "alternate-slice-entry",
        "partial-publication",
        "different-observation-root",
        "same-root-republish",
        "unknown-republish-root",
        "stale-alias-republish",
    ),
)
def test_return_path_publication_rejects_hostile_generation_shape(mutation):
    fixture = return_path_publication_lifecycle_image(mutation=mutation)
    cfg = recover_cfg(
        fixture.image,
        build_seed_inventory(fixture.image, ()),
        generous_limits(fixture.image),
    )

    assert not any(
        table.address in fixture.transfers
        and table.guard_operator == "movzx-lifecycle-domain"
        for table in cfg.jump_tables
    )
```

Add a direct certificate test that asserts its `same_generation_slice`,
publication slot, caller, root definition, observation, and
republish cuts exactly equal the fixture witness. Assert
`certificate.caller_entry == fixture.publishing_consumer`, that the publishing
consumer is not `fixture.minimum_consumer`, and that replacing the active
binding with the minimum consumer returns bottom. It should fail because the
certificate type/helper does not exist.

For `stale-alias-republish`, kill the original source register before the
republish but retain an old-generation alias in a different storage identity;
reload that stale alias and publish it. The test must return bottom, proving
that register death without global alias death is not a generation cut.

- [ ] **Step 2: Run the slice RED tests**

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_x86_cfg.py \
  -k 'hostile_generation_shape or publication_certificate_binds_exact_slice' -vv
```

Expected: FAIL on missing lifecycle context/certificate implementation.

- [ ] **Step 3: Add the lifecycle context and frozen identities**

Add these data boundaries near `_ObjectTagLifecycleQuery` and the other frozen
proof records:

```python
@dataclass(frozen=True, slots=True)
class _ObjectTagLifecycleConsumerBinding:
    function_entry: int
    movzx_address: int
    movzx_bytes_hex: str
    transfer_address: int
    transfer_bytes_hex: str
    destination_register: str
    source_register: str
    argument_push_address: int
    argument_push_bytes_hex: str


@dataclass(frozen=True, slots=True)
class _ObjectTagLifecycleEvaluationContext:
    query_sha256: str
    analysis_semantics: str
    binding: _ObjectTagLifecycleConsumerBinding
    consumer_entry: int


@dataclass(frozen=True, slots=True)
class _TrackedPublicationRoot:
    kind: Literal["definition", "argument"]
    identifier: int


@dataclass(frozen=True, slots=True)
class _PublicationCandidateIdentity:
    compiler_sha256: str
    lifecycle_query_sha256: str
    lifecycle_analysis_semantics: str
    consumer_binding: _ObjectTagLifecycleConsumerBinding
    consumer_entry: int
    caller_entry: int
    publication_address: int
    publication_slot: int
    root: _TrackedPublicationRoot
    observation_address: int
    field_start: int
    field_width: int
    analysis_limits_sha256: str


@dataclass(frozen=True, slots=True)
class _PublicationCertificateLookupKey:
    candidate_identity: _PublicationCandidateIdentity
    control_flow_revision: int
    producer_seed_revision: int
    absolute_memory_write_revision: int
    reference_classification_revision: int


@dataclass(frozen=True, slots=True)
class _PublicationBodyInterval:
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _PublicationFunctionBody:
    function_entry: int
    range_start: int
    range_end: int
    owned_intervals: tuple[_PublicationBodyInterval, ...]
    instruction_sha256: str


@dataclass(frozen=True, slots=True)
class _PublicationCallEdge:
    source_address: int
    target_address: int
    flow_kind: Literal["direct", "finite-indirect", "import"]
    returns_to_continuation: bool


@dataclass(frozen=True, slots=True)
class _PublicationRepublishCut:
    instruction_address: int
    old_root: _TrackedPublicationRoot
    new_root: _TrackedPublicationRoot
    distinct_generation_provenance: str
    alias_deaths: tuple[_PublicationAliasDeath, ...]


@dataclass(frozen=True, slots=True)
class _PublicationStorageIdentity:
    kind: Literal["register", "stack", "global-slot", "object-field", "immediate"]
    owner_entry: int
    address: int
    offset: int


@dataclass(frozen=True, slots=True)
class _PublicationAliasDeath:
    alias: _PublicationStorageIdentity
    death_address: int
    proof_kind: Literal["overwritten", "scope-ended", "generation-advanced"]


@dataclass(frozen=True, slots=True)
class _PublicationTaintOrigin:
    origin_address: int
    call_address: int
    argument_index: int
    source_kind: Literal["root-field", "derived-scalar"]
    root_field_path: tuple[int, ...]
    width: int


@dataclass(frozen=True, slots=True)
class _PublicationTaintFlow:
    origin: _PublicationTaintOrigin
    instruction_address: int
    operation: Literal["copy", "store", "reload", "compare", "mask", "test"]
    source: _PublicationStorageIdentity
    destination: _PublicationStorageIdentity
    width: int


@dataclass(frozen=True, slots=True)
class _PublicationOpaqueCopyDestination:
    origin: _PublicationTaintOrigin
    instruction_address: int
    destination: _PublicationStorageIdentity
    width: int


@dataclass(frozen=True, slots=True)
class _PublicationOwnedInstructionSource:
    kind: Literal["owned-instruction"]
    owner_instruction_address: int
    owner_function_entry: int
    range_start: int
    range_end: int
    owned_interval: _PublicationBodyInterval


@dataclass(frozen=True, slots=True)
class _PublicationTypedDataSource:
    kind: Literal["typed-data"]
    region_start: int
    region_end: int
    provenance: str


@dataclass(frozen=True, slots=True)
class _PublicationProvisionalExecutableSource:
    kind: Literal["provisional-unowned-executable"]
    interval_start: int
    interval_end: int
    bytes_sha256: str
    current_ownership_sha256: str


_PublicationReferenceSource = (
    _PublicationOwnedInstructionSource
    | _PublicationTypedDataSource
    | _PublicationProvisionalExecutableSource
)


@dataclass(frozen=True, slots=True)
class _PublicationReferenceRow:
    reference_start: int
    reference_end: int
    bytes_hex: str
    relocation_type: int | None
    reference_class: Literal[
        "type-3-relocation",
        "immediate",
        "displacement",
        "absolute-memory",
        "lea",
    ]
    source: _PublicationReferenceSource
    target_slot: int


@dataclass(frozen=True, slots=True)
class _PublicationReferenceInventory:
    slot: int
    rows: tuple[_PublicationReferenceRow, ...]
    control_flow_revision: int
    producer_seed_revision: int
    absolute_memory_write_revision: int
    reference_classification_revision: int
    current_ownership_sha256: str
    sha256: str


@dataclass(frozen=True, slots=True)
class _PublicationReferenceDisjointnessWitness:
    reference: _PublicationReferenceRow
    returning_body: _PublicationFunctionBody
    declared_range_relation: Literal["disjoint"]
    owned_intervals_relation: Literal["disjoint"]
    fixed_point_ownership_sha256: str


@dataclass(frozen=True, slots=True)
class _PublicationFiniteAddressDomain:
    kind: Literal["finite"]
    values: frozenset[int]


@dataclass(frozen=True, slots=True)
class _PublicationUnknownMappedGlobalDomain:
    kind: Literal["unknown-mapped-global"]
    mapped_intervals: tuple[_PublicationBodyInterval, ...]


_PublicationAddressDomain = (
    _PublicationFiniteAddressDomain | _PublicationUnknownMappedGlobalDomain
)


@dataclass(frozen=True, slots=True)
class _PublicationBodyAddressDomainWitness:
    returning_body: _PublicationFunctionBody
    instruction_addresses: tuple[int, ...]
    instruction_bytes_sha256: str
    input_domain: _PublicationAddressDomain
    output_domain: _PublicationAddressDomain
    protected_slot_relation: Literal["disjoint"]
    function_dependency: tuple[Literal["function"], int, str]


@dataclass(frozen=True, slots=True)
class _PublicationReferenceReconciliationObligation:
    certificate_sha256: str
    reference: _PublicationReferenceRow
    fixed_point_ownership_sha256: str


@dataclass(frozen=True, slots=True)
class _PublicationImportArgumentEffect:
    argument_index: int
    origin: _PublicationTaintOrigin | None
    alias_class: Literal["disjoint", "protected", "opaque-taint"]
    effect: Literal["scalar", "fresh-size", "mutates-sync", "handle-query"]


@dataclass(frozen=True, slots=True)
class _PublicationImportContract:
    dll: str
    name: str | None
    ordinal: int | None
    effect: Literal["sync-enter", "sync-leave", "fresh-allocation", "last-error", "flags-query"]


@dataclass(frozen=True, slots=True)
class _PublicationImportWitness:
    call_address: int
    iat_va: int
    dll: str
    lookup_mode: Literal["name", "ordinal"]
    name: str | None
    ordinal: int | None
    hint: int | None
    effect: Literal["sync-enter", "sync-leave", "fresh-allocation", "last-error", "flags-query"]
    argument_effects: tuple[_PublicationImportArgumentEffect, ...]


@dataclass(frozen=True, slots=True)
class _PublicationIncomingCall:
    call_address: int
    owner_entry: int
    call_kind: Literal["direct", "finite-indirect"]
    raw_reconciled: bool


@dataclass(frozen=True, slots=True)
class _PublicationBackendBridge:
    consumer_entry: int
    incoming_calls: tuple[_PublicationIncomingCall, ...]
    allocator_certificate: _AllocatorTotalityCertificate
    backend_root: int
    backend_bodies: tuple[_PublicationFunctionBody, ...]


@dataclass(frozen=True, slots=True)
class _ReturnPathPublicationNoninterferenceCertificate:
    compiler_sha256: str
    lifecycle_analysis_semantics: str
    lifecycle_query_sha256: str
    consumer_binding: _ObjectTagLifecycleConsumerBinding
    caller_entry: int
    root: _TrackedPublicationRoot
    publication_address: int
    publication_slot: int
    observation_address: int
    field_start: int
    field_width: int
    same_generation_slice: frozenset[int]
    republish_cuts: tuple[_PublicationRepublishCut, ...]
    returning_bodies: tuple[_PublicationFunctionBody, ...]
    call_edges: tuple[_PublicationCallEdge, ...]
    candidate_targets: frozenset[int]
    taint_origins: tuple[_PublicationTaintOrigin, ...]
    taint_flows: tuple[_PublicationTaintFlow, ...]
    reference_inventory: _PublicationReferenceInventory
    reference_disjointness: tuple[
        _PublicationReferenceDisjointnessWitness, ...
    ]
    body_address_domains: tuple[_PublicationBodyAddressDomainWitness, ...]
    imports: tuple[_PublicationImportWitness, ...]
    opaque_copy_destinations: tuple[_PublicationOpaqueCopyDestination, ...]
    backend_bridges: tuple[_PublicationBackendBridge, ...]
    summary_fact_signature: tuple[int, ...]
    control_flow_revision: int
    producer_seed_revision: int
    absolute_memory_write_revision: int


@dataclass(frozen=True, slots=True)
class _PublicationTableHypothesis:
    transfer_address: int
    table_base: int
    entry_width: int
    index_min: int
    index_max: int
    entry_rows_sha256: str
    target_records: tuple[SeedRecord, ...]
    candidate_identity: _PublicationCandidateIdentity


@dataclass(frozen=True, slots=True)
class _PublicationFinalReferenceEnvironment:
    control_flow_revision: int
    producer_seed_revision: int
    absolute_memory_write_revision: int
    reference_classification_revision: int
    relocation_classification_sha256: str
    data_regions_sha256: str
    padding_regions_sha256: str
    executable_complement_sha256: str
    sha256: str


@dataclass(frozen=True, slots=True)
class _ReproducedPublicationTableHypothesis:
    hypothesis: _PublicationTableHypothesis
    installed_table: JumpTable
    final_reference_environment: _PublicationFinalReferenceEnvironment
    certificate_entry: _DependencyMemoEntry


class _PublicationCandidateTrialRejected(CfgRecoveryError):
    def __init__(
        self,
        candidate_identities: tuple[_PublicationCandidateIdentity, ...],
        reason: str,
    ) -> None:
        self.candidate_identities = candidate_identities
        self.reason = reason
        super().__init__(
            "publication candidate trial rejected: "
            f"candidates={len(candidate_identities)};reason={reason}"
        )
```

Initialize `self.object_tag_lifecycle_evaluation_contexts`, a
`reference_classification_revision`, a dependency-bearing
publication-certificate memo keyed by `_PublicationCertificateLookupKey`, and
a collection of tentative `_PublicationTableHypothesis` rows in
`_DirectCfgRecovery.__init__`.
Import `Literal` if it is not already present. Canonically sort every tuple at
construction and validate every stored digest against its complete rows.

In the same edit, advance the lifecycle constant before enabling the
exception:

```python
_MOVZX_PRODUCER_ANALYSIS_SEMANTICS = "movzx-producer-analysis-v27"
_OBJECT_TAG_LIFECYCLE_ANALYSIS_SEMANTICS = (
    "object-tag-lifecycle-analysis-v6"
)
```

Update all existing assertions that describe the current lifecycle semantics
to v6. Change the prior-version lifecycle checkpoint input from v4 to v5 so it
continues testing stale semantic replay. Leave producer v27 and lifecycle
schema v1 unchanged.

- [ ] **Step 4: Scope v6 lifecycle computation explicitly**

In `_object_tag_lifecycle_guard_for_index.compute_domain`, decode each active
binding into `_ObjectTagLifecycleConsumerBinding`, push a separate context for
that binding, and pop the identical object in a `finally` block:

```python
results = []
for raw_binding in bindings:
    binding = _ObjectTagLifecycleConsumerBinding(
        function_entry=raw_binding[0],
        movzx_address=raw_binding[1],
        movzx_bytes_hex=raw_binding[2],
        transfer_address=raw_binding[3],
        transfer_bytes_hex=raw_binding[4],
        destination_register=raw_binding[5],
        source_register=raw_binding[6],
        argument_push_address=raw_binding[7],
        argument_push_bytes_hex=raw_binding[8],
    )
    context = _ObjectTagLifecycleEvaluationContext(
        query_sha256=query.sha256,
        analysis_semantics=query.analysis_semantics,
        binding=binding,
        consumer_entry=binding.function_entry,
    )
    self.object_tag_lifecycle_evaluation_contexts.append(context)
    try:
        results.append(compute_lifecycle_binding(binding))
    finally:
        if self.object_tag_lifecycle_evaluation_contexts.pop() is not context:
            raise CfgRecoveryError("object-tag lifecycle context stack is corrupted")
```

`query.function_entry` remains a shared query/dependency root only. It must
never be substituted for `binding.function_entry`, used as the semantic
caller, or copied into `certificate.caller_entry`. Do not install this context
in `_movzx_guard_for_index` producer-domain evaluation. Add a positive test in
which the publishing consumer is not the minimum binding entry; substituting
the minimum/query entry for the publishing consumer must return bottom.

- [ ] **Step 5: Implement exact publication and slice recognition**

Add a bounded helper with this signature:

```python
def _return_path_publication_noninterference_certificate(
    self,
    *,
    publication_address: int,
    publication_slot: int,
    caller_entry: int,
    root: _TrackedPublicationRoot,
    observation_address: int,
    field_start: int,
    field_width: int,
    relative_states,
) -> _ReturnPathPublicationNoninterferenceCertificate | None:
```

It must require an active v6 context and
`caller_entry == context.consumer_entry == context.binding.function_entry`,
require the publication store owner to equal that same consumer, and then
check the exact mapped pointer-width store, singleton root offset zero at
publication and observation, no interior entry, and exact slice. A republish
is a cut only when both (a) the stored root has a closed origin proving a
distinct new generation and (b) typed alias-death facts prove no register,
stack, global, field, or other live alias preserves the old identity. Killing
the original source register alone is insufficient. Record all typed fields
and revisions, including the current ownership digest, in the certificate and
memoize it under its structural lookup key. Return `None` for every ambiguous
state or limit hit. The helper returns proof evidence only: it never creates a
`SeedRecord`, `_PublicationTableHypothesis`, `JumpTable`, edge, or ownership
fact. At its call site `_object_tag_lifecycle_guard_for_index` runs before
`_recover_indexed_table` has read table entries, so table records do not yet
exist. This helper never consults final `RawCfg`,
`UnreachableExecutableResidue.accepted`, Ghidra facts, or an external
reconciliation report.

- [ ] **Step 6: Call the helper only at the two existing rejection points**

At the non-stack publication branch in
`_pointer_definition_preserves_field_before` and the corresponding
`reject_pointer_publication` branch in
`_function_argument_preserves_field_before`, preserve the current rejection
unless the helper returns a certificate. Include the query SHA, complete typed
binding, `consumer_entry`, structural publication/root/observation/field
inputs, limits digest, and current revisions in lookup/bottom cache keys. Do
not include a slice, closure, inventory, or other computed witness digest in a
lookup key. Store the typed certificate in `_DependencyMemoEntry.result`; its
`.dependencies` contains only canonical `(kind, identifier, fingerprint)`
rows. Do not skip any other write/call checks.

- [ ] **Step 7: Run the focused tests and keep the call-bearing baseline RED**

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_x86_cfg.py \
  -k 'publication_certificate_binds_exact_slice or hostile_generation_shape or non_lifecycle_callers_still_reject' -vv
```

Expected: slice/identity tests PASS. The full positive fixture remains
unresolved because Task 3 has not certified its returning call closure.

- [ ] **Step 8: Commit the path certificate**

```bash
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "feat(mwcc-retro): certify lifecycle publication slices"
```

---

### Task 3: Close returning calls, protected references, actuals, and imports

**Files:**

- Modify: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/mwcc_retro/backend_lifetime_audit.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_lifetime_audit.py`

**Interfaces:**

- Consumes: Task 2's slice certificate, existing direct and finite control
  target facts, PE imports/relocations, pointer states, and dependency
  collectors.
- Produces: `_ReturningPublicationClosure`,
  `_returning_publication_closure(...)`,
  `_publication_actual_effects_are_opaque(...)`,
  `_exact_publication_import_effect(...)`, and
  `_publication_reference_inventory(...)`,
  `_publication_reference_disjointness(...)`,
  `_publication_body_address_domains(...)`,
  `_PublicationTableHypothesis`, `_PublicationFinalReferenceEnvironment`,
  `_ReproducedPublicationTableHypothesis`,
  `_PublicationCandidateTrialRejected`, and final audit
  reconciliation of `_PublicationReferenceReconciliationObligation`, including
  the durable lifecycle-only `absolute-reference` dependency kind.

- [ ] **Step 1: Add RED matrices for closure and protected-slot access**

```python
@pytest.mark.parametrize(
    "mutation",
    (
        "returning-unresolved-indirect",
        "extra-finite-returning-target",
        "closure-slot-read",
        "closure-slot-materialization",
        "unreconciled-slot-reference",
        "overlapping-residue-slot-reference",
        "ownership-growth-into-returning-closure",
    ),
)
def test_return_path_publication_rejects_hostile_returning_closure(mutation):
    fixture = return_path_publication_lifecycle_image(mutation=mutation)
    cfg = recover_cfg(
        fixture.image,
        build_seed_inventory(fixture.image, ()),
        generous_limits(fixture.image),
    )
    assert set(fixture.transfers) <= {
        row.address
        for row in cfg.control_targets.unresolved
        if row.kind == "computed-flow-blocker"
    }
```

Add a positive direct helper variant with no allocator failure branch and one
finite indirect call whose two owned targets both return without touching the
slot. Assert the certificate contains every typed direct edge, finite edge,
candidate target, and full `_PublicationFunctionBody` row. Add a positive
`outside-residue-slot-reference` fixture whose exact reference span belongs to
the current unowned executable complement. Assert its full
`_PublicationReferenceRow` contains a
`_PublicationProvisionalExecutableSource`, while the candidate certificate
contains a separate `_PublicationReferenceDisjointnessWitness` for that row
against every returning body. No test may set or consult residue
`accepted=True` during recovery. The overlapping-residue mutation must place
one byte of the same span in a returning declared range and return bottom.

For `ownership-growth-into-returning-closure`, make the first producer pass see
the row as provisional and outside, then let the tentative table target records
discover a returning body that owns the span. Assert the disposable
accepted-candidate trial invalidates the first memo/certificate, recomputes
against the new owner, and rejects the table rather than retaining stale
disjointness.

Add
`test_publication_table_reproduction_requires_post_install_quiescent_certificate`.
Instrument the fixture/recovery and assert this exact order:

```python
assert baseline.tentative_hypothesis is not None
assert baseline.table is None
assert baseline.candidate_edges == ()
assert trial.seeded_target_records == baseline.tentative_hypothesis.target_records
assert trial.edges_before_table_install == baseline.edges
assert trial.post_install_control_flow_revision > trial.preinstall_control_flow_revision
assert not trial.preinstall_certificate_entry_is_current
assert trial.ordinary_closure_is_quiescent
assert trial.final_normalization_is_stable
assert trial.post_install_certificate_entry_is_current
assert trial.reproduced_hypothesis is not None
```

Add a hostile variant whose installed candidate edge exposes a returning slot
read. Definitive recomputation must return bottom. Assert the outer loop marks
the candidate unreproduced, does not put the recovery in `reusable_trial`,
discards every provisional table/edge/owner/memo mutation, and rebuilds a
baseline `RawCfg` without the candidate. A second recovery using the same outer
state must not observe any mutation from the failed trial.

Parameterize a final-normalization hostile test over
`seed-provenance-binding`, `relocation-classification`, `typed-data-boundary`,
`padding-boundary`, and `executable-complement`. Each mutation occurs after
installed-edge quiescence but before definitive validation. Assert the
pre-install dependency entry is stale, the definitive certificate binds the
final environment, and any revision/fingerprint change after that snapshot
restarts or rejects before `RawCfg` construction.

In `test_retro_backend_lifetime_audit.py`, add a positive provisional-row
reconciliation test and a hostile
`test_publication_reference_obligation_blocks_final_reconciliation_failure`.
The hostile Ghidra fixture either claims overlapping ownership or omits the
exact row; this is the `final-residue-reconciliation-failure` case and
`report.require_publishable()` must fail for both mutations.

- [ ] **Step 2: Add RED matrices for root/child and opaque actual effects**

```python
@pytest.mark.parametrize(
    "mutation",
    (
        "root-actual",
        "child-actual",
        "slot-address-actual",
        "opaque-actual-dereference",
        "opaque-actual-mutation",
        "opaque-actual-unknown-forward",
        "opaque-multihop-reload-dereference",
    ),
)
def test_return_path_publication_rejects_hostile_actual_effect(mutation):
    fixture = return_path_publication_lifecycle_image(mutation=mutation)
    cfg = recover_cfg(
        fixture.image,
        build_seed_inventory(fixture.image, ()),
        generous_limits(fixture.image),
    )
    assert not any(
        table.address in fixture.transfers
        and table.guard_operator == "movzx-lifecycle-domain"
        for table in cfg.jump_tables
    )
```

Add a positive assertion that the unrelated global copy address appears as a
typed `_PublicationOpaqueCopyDestination` in
`certificate.opaque_copy_destinations`. Name the test
`test_return_path_publication_records_opaque_copy_escape` and assert no
provenance string contains `no-escape` or `does-not-escape`.

- [ ] **Step 3: Add RED tests for the exact import boundary**

Parameterize `wrong-import-dll`, `wrong-import-symbol`,
`wrong-import-lookup-mode`, `changed-import-iat`, `unlisted-import`,
`extra-tainted-import-argument`, and `sync-handle-alias`. Add positive fixture
imports for exact `KERNEL32.dll` names `EnterCriticalSection`,
`LeaveCriticalSection`, `GlobalAlloc`, `GetLastError`, and `GlobalFlags`; assert
the closure records a complete `_PublicationImportWitness`, including call
source, parsed `Import.iat_va`, DLL, exactly one of name/ordinal, hint, typed
effect, and every typed argument effect. Add raw-PE fixtures parsed through
the strict public `pe_mod.load(...)` entry point for both name and ordinal
lookup modes and for a changed-IAT
integrity failure. Hand-built `Image(imports=...)` fixtures test only semantic
matching; they do not establish raw descriptor integrity.

- [ ] **Step 4: Run all Task 3 RED tests**

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_x86_cfg.py tests/test_retro_backend_lifetime_audit.py \
  -k 'hostile_returning_closure or hostile_actual_effect or opaque_copy_escape or exact_import_boundary or publication_reference_obligation' -vv
```

Expected: the positive closure/import/opaque-copy assertions fail because no
returning effect implementation exists.

- [ ] **Step 5: Add the returning closure record and fixed point**

Add:

```python
@dataclass(frozen=True, slots=True)
class _ReturningPublicationClosure:
    bodies: tuple[_PublicationFunctionBody, ...]
    call_edges: tuple[_PublicationCallEdge, ...]
    candidate_targets: frozenset[int]
    imports: tuple[_PublicationImportWitness, ...]
```

`_returning_publication_closure` starts only from calls whose continuation can
reach the observation before a valid republish cut. It walks owned direct and
finite indirect targets to a bounded fixed point, retains every finite
candidate as a dependency, and includes only instructions that can return to
the relevant continuation. Reject unresolved calls, unowned targets, open
tail escapes, and recursive reentry into `context.consumer_entry`. Canonically
sort every typed row; do not use under-specified positional tuples.

- [ ] **Step 6: Add lifecycle-only absolute-reference dependency plumbing**

Add `_note_producer_absolute_reference_dependency(slot)` and extend
`_producer_dependency_fingerprint` with `absolute-reference`. Its semantic
digest contains the complete canonically sorted `_PublicationReferenceRow`
sequence, independent of any lifecycle query or returning closure: every
reference span and exact bytes, relocation type when present, literal
reference class, target slot, and one typed owned-instruction, typed-data, or
provisional-unowned-executable source. Include the exact owner/range,
data-region provenance, or provisional interval/hash, plus current ownership
digest and control-flow, seed, absolute-write, and reference-classification
revisions. Do not include `_PublicationReferenceDisjointnessWitness`, a
returning-body entry, or an `outside_returning_ranges` boolean.

Cache the inventory by `(slot, recovery revisions)`. Increment
`reference_classification_revision` whenever instruction ownership, a declared
function range, typed-data boundaries, relocation classification, or decoded
literal operand classification changes in a way that can change a raw row.
Finite arithmetic/materialization facts do not affect this revision or the
absolute-reference fingerprint; they are body-local function-dependent
witnesses. This fingerprint must remain callable after the per-binding
lifecycle context has been popped.

Change producer checkpoint dependency decoding so `absolute-reference` is
accepted only when the expected query is an `_ObjectTagLifecycleQuery` with
v6 semantics. A `_MovzxProducerQuery` continues accepting exactly `function`,
`global-slot`, and `dynamic-field`. Add decoder tests for lifecycle acceptance,
producer rejection, malformed rows, noncanonical order, and fingerprint
invalidation before any successful proof can emit the new dependency. Keep
checkpoint schema v1 unchanged: the durable row remains the existing
`(kind="absolute-reference", identifier=slot, fingerprint=...)` shape and does
not serialize internal inventory, body, taint, import, or bridge dataclasses.

- [ ] **Step 7: Reconcile raw slot references and body-local materializations**

Implement `_publication_reference_inventory(slot)` to inventory every
type-3 PE relocation whose initialized value is `slot`, every direct/immediate
displacement/absolute-memory or LEA literal operand whose decoded value is
exactly `slot`, with exact operand span, bytes, relocation type, literal
reference class, and ownership classification. It must not scan or serialize
finite arithmetic/materialization chains. An exact executable span with no
current instruction owner or typed-data boundary receives only
`_PublicationProvisionalExecutableSource`; recovery must not construct or read
the later `UnreachableExecutableResidue.accepted` state and must not consult
Ghidra.

Canonicalize one row per exact `(reference_start, reference_end, bytes,
target_slot)`. When a decoded literal operand carries a matching type-3
relocation, emit one `type-3-relocation` row rather than a duplicate literal
row. Reject conflicting relocation/decoded spans or source classifications.

Implement `_publication_reference_disjointness(inventory, returning_bodies)`
separately. It constructs one typed witness for every inventory-row/body pair
and validates the reference span against both the body's declared range and
every owned interval. Reject an overlap, straddle, ambiguous source class,
missing cross-product pair, or in-closure raw literal read/write/LEA reference.
Owned and typed-data references outside the closure stay
in the raw inventory and relation just like provisional rows.

Implement `_publication_body_address_domains(slot, returning_bodies)` as the
separate certificate-local pass. For each returning body, analyze finite
arithmetic/materialization chains and unknown mapped-global address domains,
emit typed `_PublicationBodyAddressDomainWitness` rows with exact instruction
addresses/bytes digest and input/output domains, and bind every witness to the
current `("function", body.function_entry, fingerprint)` dependency. Reject a
finite output containing `slot`, an unknown mapped-global output that may
contain `slot`, an incomplete body scan, or a witness/dependency mismatch.

Note an `("absolute-reference", slot)` dependency only while a v6 lifecycle
context is active. Store that query-independent dependency row in the
publication memo dependency snapshot; table replay later compares its
fingerprint without attempting to place body-local materialization facts in
the slot-keyed digest.

- [ ] **Step 8: Admit tables only through reproduced publication hypotheses**

Do not let `_object_tag_lifecycle_guard_for_index` or either preservation
helper create target records or mutate table/edge/ownership state. They execute
before `_recover_indexed_table` reads entries and return only a guard result
plus structural certificate identity and typed certificate evidence.

Refactor `_recover_indexed_table` so its entry loop remains the sole layer that
validates bounds, type-3 relocations, exact entry bytes, executable targets,
and constructs target `SeedRecord`s. When the otherwise-valid table needs the
publication exception on a first pass, do not install `JumpTable`, data
evidence, edges, finite targets, ownership, or enqueue work. Instead emit one
tentative `_PublicationTableHypothesis` containing the exact transfer/table
shape, canonical entry-row digest, target records, and structural
`_PublicationCandidateIdentity`; leave the transfer unresolved. The tentative
hypothesis must not contain the revision-bearing memo lookup key, because seed
and ownership revisions intentionally change in the disposable
accepted-candidate trial.

Integrate this table-layer hypothesis with the existing outer replay. Extend
`identity`, `hypothesis_kind`, `hypothesis_payload`, candidate ordering,
accepted target-record seed replay, reproduction, and invalidation with a
`return-path-publication-table` kind. Hypothesis identity includes table bytes,
target records, and structural certificate identity, but excludes the computed
certificate and dependency snapshot. A disposable accepted-candidate trial
starts from authoritative seeds plus the accepted/tentative hypothesis target
records and candidate identity. Pass the exact accepted candidates separately
as `accepted_publication_table_hypotheses` to `_DirectCfgRecovery`; do not infer
acceptance from the presence of a target seed alone. Merely constructing this
trial inventory must not add the candidate table edge or change
`control_flow_revision`. Give a publication trial private copies of shared
`producer_domain_memo` and `finite_control_memo`; merge only entries whose
dependencies pass definitive validation after reproduction. Recovery-local
publication memos never escape a failed trial. Durable checkpoint files may
remain as dependency-bound variants, but do not authorize graph reuse.

Implement the accepted-candidate path as a disposable trial with these phases:

1. `_recover_indexed_table` rereads and matches the exact hypothesis entry
   rows. It may now install the `JumpTable`, data evidence, finite targets, and
   edges provisionally, incrementing `control_flow_revision`, and enqueue table
   targets. The certificate used to screen the baseline is immediately stale;
   remove/ignore its revision-bearing memo entry.
2. Continue the existing ordinary recovery loop until pending decode, blocks,
   computed flows, installed table edges, target ownership, and summaries are
   quiescent. Do not add the candidate to `validated_*` or outer
   `reproduced_hypotheses` during this phase.
3. Before definitive publication validation, execute the current late
   normalization in dependency order: `_classify_relocations()`,
   `_bind_seed_instruction_provenance()`, `_merged_data_regions()`,
   `_padding_regions(...)`, `_require_disjoint_ownership(...)`, and
   `_provisional_unreachable_residue(...)`, followed by final relocation
   dispositions. Build `_PublicationFinalReferenceEnvironment` from their exact
   rows/digests and current revisions. Explicitly recompute lifecycle v6 under
   every exact binding against the installed, quiescent graph and that finalized
   environment. Construct `_ReproducedPublicationTableHypothesis` only from the
   installed table, final environment, and successful post-install
   `_DependencyMemoEntry`.

The definitive certificate must contain the current post-install
`control_flow_revision`, post-binding `producer_seed_revision`, complete raw
inventory/current complement, row/body disjointness, body address-domain
witnesses, and dependency snapshot. Snapshot all final revisions/digests before
the recomputation and compare them again afterward. If any changed, restart the
disposable trial from authoritative seeds or reject the candidate; never patch
the certificate in place.

If any table byte, target record, identity, normalization row, revision,
fingerprint, aggregate result, or certificate witness changes, do not reproduce
the hypothesis. Before constructing `RawCfg`, raise
`_PublicationCandidateTrialRejected` with the exact structural identities.
Catch it only at the outer accepted-candidate trial boundary, mark those
identities unreproduced/rejected, discard the recovery object and all memo
entries it created, and rebuild from authoritative seeds without the candidate.
In particular, the existing `reusable_trial = trial_recovery, trial_cfg`
optimization is forbidden for a publication candidate unless definitive
post-install validation already succeeded. After failure, construct a fresh
candidate-free `_DirectCfgRecovery` from authoritative seeds; do not return the
failed trial or substitute it for `reusable_baseline`. None of its table, edge,
ownership, seed, memo, certificate, or obligation state survives.

Before constructing and again before returning `RawCfg`, assert that every
publication-dependent `JumpTable` maps to exactly one current
`_ReproducedPublicationTableHypothesis`; its installed table equals the current
table, its final reference environment equals freshly recomputed current
digests/revisions, its `certificate_entry.result` is the emitted certificate,
and every row in `certificate_entry.dependencies` still has its current
fingerprint. Hypothesis membership alone is insufficient. Only certificates
passing this assertion populate
`publication_noninterference_certificates` and only their provisional rows
populate `publication_reference_obligations`.

- [ ] **Step 9: Gate final publication on external residue reconciliation**

Expose the canonical set union of provisional rows from every reproduced,
definitive post-install certificate as typed
`_PublicationReferenceReconciliationObligation` rows on `RawCfg`; equality is
required, not merely containment. Add exact frozen
`RawCfg` fields
`publication_noninterference_certificates: tuple[_ReturnPathPublicationNoninterferenceCertificate, ...]`
and
`publication_reference_obligations: tuple[_PublicationReferenceReconciliationObligation, ...]`;
they are internal CFG/audit evidence and are not encoded in lifecycle
checkpoint schema v1. Extend
`backend_lifetime_audit` so its existing Ghidra/residue reconciliation must
match every obligation's exact span, bytes, provisional interval/hash,
ownership digest, and source disposition. Bind the crosscheck digest to the
exact canonically sorted obligation set and its reconciliation results.
`CrosscheckReport.require_publishable()` must fail if a result is missing,
extra, stale, conflicting, or classified as reachable code/data differently.
`accept_reconciled_residue()` may bind the report's reconciliation SHA-256 only
after exact set equality and every obligation pass; it does not rerun or supply
lifecycle closure safety.

The accepted `RawCfg` serializer must emit exactly one read-only
`return-path-publication-noninterference` audit row derived from the internal
certificate: certificate digest, publication/observation, returning-body
entries, default-callback closure count, exact import identities, raw reference
inventory and canonical `reference_inventory_sha256` over the raw-row
projection (before adding final reconciliation fields), provisional source
sites, exact obligation-set digest, and external reconciliation digest. This
is bundle evidence, not a producer checkpoint field, and does not change
lifecycle checkpoint schema v1. Serialize each audit reference with explicit
`reference_start`, `reference_end`, `bytes_hex`, `relocation_type`, and
`reference_class`, `target_slot`, and `source_kind` plus a canonical
`source_evidence` object containing every field of its exact typed source so
the read-only verifier never infers classification from an address list. Each
provisional row also carries
the exact interval start/end/hash and final `residue_reconciliation_sha256`
that accepted it. Refuse accepted serialization if the consolidated row is
missing, duplicated, or cannot be derived from the exact current obligation
union.

Never serialize a baseline/pre-install certificate, its raw inventory, or its
provisional rows. Audit evidence is derived exclusively from the final
`_ReproducedPublicationTableHypothesis.certificate_entry.result` values that
pass the current fingerprint assertion immediately before `RawCfg` return.

Make the Step 1 positive audit test pass only when the outside provisional row
is independently reconciled, and make its hostile failure cases leave the
bundle unpublishable even though internal fixed-point disjointness succeeded.

- [ ] **Step 10: Implement opaque actual tainting without a no-escape shortcut**

Before entering a callee, reject every actual whose relative-pointer offsets
contain the root or child and reject any actual that materializes the protected
slot address itself. Taint field-derived scalar actuals and propagate them
through arbitrarily many bounded register, stack, object-field, and global
store/reload hops. Permit copying, storing to an unrelated slot, comparison,
masking, and testing. Reject a taint used as a memory base/index, store
receiver, protected-address materializer, or actual to an unresolved target,
including after a multi-hop reload. Record every origin, flow, and unrelated
store in the certificate's typed taint and opaque-copy rows.

- [ ] **Step 11: Implement exact import contracts**

Bind each accepted import to the strict parser's exact `pe.Import` row, DLL,
IAT slot, hint, and exactly one lookup mode (`name` xor `ordinal`). Production
trust is the parsed import row plus compiler SHA; the lifecycle proof does not
reparse raw PE bytes. Raw descriptor integrity belongs in the `pe_mod.load`
fixtures specified above. Implement typed contracts only for these effects:

```python
_PUBLICATION_IMPORT_CONTRACTS: tuple[_PublicationImportContract, ...] = (
    _PublicationImportContract("kernel32.dll", "EnterCriticalSection", None, "sync-enter"),
    _PublicationImportContract("kernel32.dll", "LeaveCriticalSection", None, "sync-leave"),
    _PublicationImportContract("kernel32.dll", "GlobalAlloc", None, "fresh-allocation"),
    _PublicationImportContract("kernel32.dll", "GetLastError", None, "last-error"),
    _PublicationImportContract("kernel32.dll", "GlobalFlags", None, "flags-query"),
)
```

Normalize the parsed DLL name only with the same PE import normalization used
elsewhere. Require exact lookup-mode equality; a name contract cannot accept an
ordinal import and vice versa. Bind every actual, reject extra tainted actuals,
and require the synchronization pointer and queried handle to be disjoint from
the protected root, protected slot, and opaque actual taints. Reject any
unlisted import, IAT mismatch, or effect ambiguity. Do not add a default case.

- [ ] **Step 12: Run focused GREEN tests**

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_x86_cfg.py tests/test_retro_backend_lifetime_audit.py \
  -k 'return_path_publication and not backend_bridge and not checkpoint and not rejection_ledger' -vv
```

Expected: every Task 2/3 path, closure, actual, reference, import, disposable
post-install reproduction/failure-discard, final-normalization, and external
reconciliation test passes; the full allocator fixture remains RED only at the
context-bound failure branch.

- [ ] **Step 13: Review checkpoint 1**

Inspect the staged diff before committing:

```bash
git diff --check
git diff -- tools/mwcc_retro/x86_cfg.py tools/mwcc_retro/backend_lifetime_audit.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_lifetime_audit.py
rg -n '435628|43576b|587130|436470|44235b|48b6c0' tools/mwcc_retro/x86_cfg.py
```

Expected: `git diff --check` succeeds; the production address scan has zero
matches. Confirm the ordinary publication rejection and v27 paths are still
present, no lifecycle helper reads `accepted`, and every provisional
publication row from a current post-install certificate becomes exactly one
member of the final canonical obligation union. Confirm a failed mutated trial
cannot reach `reusable_trial` and no pre-install certificate reaches audit
serialization. Stop for reviewer approval if the exception is reachable
without an active lifecycle context.

- [ ] **Step 14: Commit the returning effect proof**

```bash
git add tools/mwcc_retro/x86_cfg.py tools/mwcc_retro/backend_lifetime_audit.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_lifetime_audit.py
git commit -m "feat(mwcc-retro): close returning publication effects"
```

---

### Task 4: Make allocator-totality memo hits replay every dependency

**Files:**

- Modify: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**

- Consumes: `_AllocatorTotalityCertificate`, `_DependencyMemoEntry`,
  `_producer_dependency_snapshot`, `_dependency_memo_hit`, direct closures,
  callback target facts, and producer dependency collectors.
- Produces: `_allocator_totality_dependencies(...) -> set[tuple[str, int]]`
  and dependency-bearing `allocator_totality_cache` entries.

- [ ] **Step 1: Write a RED cache-hit dependency equality test**

```python
def test_allocator_totality_cache_hit_replays_all_dependencies():
    fixture = return_path_publication_lifecycle_image()
    recovery = _DirectCfgRecovery(
        fixture.image,
        build_seed_inventory(fixture.image, ()),
        generous_limits(fixture.image),
    )
    recovery.recover()

    fresh: set[tuple[str, int]] = set()
    recovery.producer_dependency_collectors.append(fresh)
    try:
        first = recovery._allocator_totality_certificate(
            fixture.allocator,
            fixture.helper_target,
            lifetime_roots=frozenset({fixture.publishing_consumer}),
        )
    finally:
        assert recovery.producer_dependency_collectors.pop() is fresh

    replayed: set[tuple[str, int]] = set()
    recovery.producer_dependency_collectors.append(replayed)
    try:
        second = recovery._allocator_totality_certificate(
            fixture.allocator,
            fixture.helper_target,
            lifetime_roots=frozenset({fixture.publishing_consumer}),
        )
    finally:
        assert recovery.producer_dependency_collectors.pop() is replayed

    assert first is not None and second == first
    assert replayed == fresh
    assert ("global-slot", fixture.callback_slot) in replayed
    assert {("function", target) for target in fixture.callback_targets} <= replayed
```

Also assert dependencies contain the allocator/caller, session/init/grow,
setjmp/restore, all backend and lifetime closure functions, system allocators,
finalizers, resets, and every callback candidate.

- [ ] **Step 2: Run the cache test to verify the bug**

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_x86_cfg.py \
  -k 'allocator_totality_cache_hit_replays_all_dependencies' -vv
```

Expected: FAIL because the second collector is empty or incomplete.

- [ ] **Step 3: Extend the certificate with exact callback candidates**

Add `callback_candidate_targets: frozenset[int]` to
`_AllocatorTotalityCertificate`. Populate it from the finite target set at the
grow helper callback call, include it in candidate compatibility keys, and
require the installed callback target to be a member.

- [ ] **Step 4: Refactor the cache to dependency-bearing entries**

Change its type to:

```python
self.allocator_totality_cache: dict[
    tuple[Any, ...], _DependencyMemoEntry | None
] = {}
```

Add:

```python
def _allocator_totality_dependencies(
    self,
    allocator: int,
    allocation_caller: int,
    certificate: _AllocatorTotalityCertificate,
) -> set[tuple[str, int]]:
```

Return function dependencies for every item listed in the test, expanding
every backend root and lifetime root closure, plus
`("global-slot", certificate.callback_slot)`. Do not recompute this set on a
cache hit.

- [ ] **Step 5: Store, validate, and replay the exact snapshot**

On successful construction, snapshot the set into `_DependencyMemoEntry`,
propagate the set to the active collector, then cache the entry. On a positive
hit, call `_dependency_memo_hit`; it both validates fingerprints and propagates
the stored rows. Remove and recompute an invalid positive entry. Keep `None` as
the in-progress/proved-bottom sentinel.

- [ ] **Step 6: Add invalidation RED/GREEN coverage**

Mutate one owned instruction in a returning backend closure function, one
whole callback-slot write, and one overlapping partial-byte callback-slot
write in separate fixture instances. Seed the prior memo entry, then assert
`_dependency_memo_hit` rejects each stale entry and totality recomputes or
returns bottom. Do not mutate the image SHA field alone; exercise function and
global-slot fingerprints. Partial overlap is an overwrite even when no
pointer-width store starts exactly at the callback slot.

- [ ] **Step 7: Run allocator and adjacent lifecycle tests**

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_x86_cfg.py \
  -k 'allocator_totality or lifecycle_total_allocation or lifecycle_naked_context or lifecycle_flag_preserving' -vv
```

Expected: PASS, including fresh/cache dependency equality.

- [ ] **Step 8: Commit the cache fix independently**

```bash
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "fix(mwcc-retro): replay allocator proof dependencies"
```

---

### Task 5: Bind allocator failure to the exact backend session and caller domain

**Files:**

- Modify: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**

- Consumes: Task 3 returning closure, Task 4 totality certificate/memo,
  `_incoming_call_domain_is_closed`, `_incoming_call_sites`,
  `_registrar_function_entry`, and `_direct_function_call_closure`.
- Produces: `_PublicationBackendBridge` and
  `_publication_backend_bridge(...) -> _PublicationBackendBridge | None`.

- [ ] **Step 1: Complete the typed backend bridge record**

Use the Task 2 `_PublicationBackendBridge` shape without replacing its typed
`_PublicationIncomingCall` rows with address sets. Its `consumer_entry` is the
active binding's entry, its allocator certificate is complete, and its
`backend_bodies` is the complete typed body inventory for the one exact closure
that covers the consumer, allocation caller, and every incoming owner.

- [ ] **Step 2: Add RED tests that allocation-caller membership cannot substitute for context**

```python
@pytest.mark.parametrize(
    "mutation",
    (
        "lifecycle-root-outside-backend",
        "incoming-owner-outside-backend",
        "unowned-raw-incoming-call",
        "exported-lifecycle-caller",
        "unreconciled-address-taken-caller",
        "split-backend-union",
    ),
)
def test_return_path_publication_requires_closed_backend_caller_bridge(mutation):
    fixture = return_path_publication_lifecycle_image(mutation=mutation)
    cfg = recover_cfg(
        fixture.image,
        build_seed_inventory(fixture.image, ()),
        generous_limits(fixture.image),
    )
    assert not any(
        table.address in fixture.transfers
        and table.guard_operator == "movzx-lifecycle-domain"
        for table in cfg.jump_tables
    )
```

For `incoming-owner-outside-backend`, keep the allocation caller inside the
backend closure so the test specifically catches the missing bridge.

- [ ] **Step 3: Add RED tests for failure pruning**

Parameterize `returning-failure-callback`, `callback-slot-overwrite`,
`partial-callback-slot-overwrite`, and `reset-in-lifetime`. Assert all remain
computed-flow blockers. Add a positive direct bridge test asserting the
certificate's session, callback slot/target, setjmp/restore, backend root,
typed incoming calls, and incoming owners equal the fixture witness. The split
backend fixture must arrange two individually valid backend closures whose
union covers the required functions while neither closure does; it must return
bottom.

- [ ] **Step 4: Run bridge/failure RED tests**

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_x86_cfg.py \
  -k 'closed_backend_caller_bridge or failure_callback or backend_bridge_binds' -vv
```

Expected: FAIL on the positive bridge and, before the strict checks, at least
one hostile mutation is incorrectly accepted or fails for the wrong reason.

- [ ] **Step 5: Implement strict caller-domain reconciliation**

`_publication_backend_bridge` must first require
`consumer_entry == active_context.binding.function_entry` and call
`_incoming_call_domain_is_closed(consumer_entry)`. It must not call the
least-reachable fallback. Enumerate `_incoming_call_sites`, resolve every
source with `_registrar_function_entry`, reject missing/ambiguous owners, and
record a typed `_PublicationIncomingCall` with exact source, owner, call kind,
and raw reconciliation. Note the consumer plus every owner as function
dependencies. Never substitute the allocation caller, minimum binding, or
`query.function_entry` for `consumer_entry`.

- [ ] **Step 6: Require one complete backend closure**

Request allocator totality with
`lifetime_roots=frozenset({consumer_entry})`. Among the certificate's backend
roots, accept one root only if its direct closure contains all of:

```python
required = {
    consumer_entry,
    allocation_caller,
    *incoming_owners,
}
```

Require `required <= backend_closure`. Do not accept a union where different
backend roots cover different required functions. Note the backend root and
every closure function as dependencies.

- [ ] **Step 7: Prune only the context-bound callback failure path**

At a finite callback call, preserve all candidate target dependencies. Narrow
the active slot only when the totality certificate proves the checked session
installed its callback and excluded every later whole or partially overlapping
write/reset. Treat that callback as nonreturning only when
`_callback_nonreturns_via_context_restore` binds the same saved context and
restore target. Otherwise include its fallthrough in the returning closure and
reject any unsafe effect.

- [ ] **Step 8: Complete the certificate and provenance**

Populate the complete typed `_PublicationBackendBridge` rows, including
allocator certificates, backend roots/closures, and incoming calls/owners, in
`_ReturnPathPublicationNoninterferenceCertificate`. Provenance must say
`opaque-copy-escape=<slot>` for allowed copies and include publication,
observation, slice digest, reference-inventory digest, closure digest, session,
and backend root. It must not say no-escape.

- [ ] **Step 9: Run the full synthetic positive and hostile matrix**

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_x86_cfg.py \
  -k 'return_path_publication or allocator_totality_cache_hit' -vv
```

Expected: the baseline two-consumer lifecycle table is recovered with bound
74; every named hostile mutation remains unresolved.

- [ ] **Step 10: Review checkpoint 2**

```bash
git diff --check
rg -n '_least_reachable_incoming_call_domain_is_closed' tools/mwcc_retro/x86_cfg.py
rg -n 'allocation_caller.*closure|incoming_owners|lifetime_roots' tools/mwcc_retro/x86_cfg.py
git diff --stat
git diff --stat 54927e8e3..HEAD
```

Inspect every newly added least-reachable reference; the backend bridge must
have none. Confirm the hostile fixture proves the allocation caller can be in
the backend closure while an incoming owner is outside it. Pause for review
before persistence work.

- [ ] **Step 11: Commit the context bridge**

```bash
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "feat(mwcc-retro): bind publication proof to backend session"
```

---

### Task 6: Complete persisted dependencies and rejection-ledger replay

**Files:**

- Modify: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/mwcc_retro/backend_lifetime_audit.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_lifetime_audit.py`

**Interfaces:**

- Consumes: Task 3 `absolute-reference` notes, Task 4 dependency replay, Task 5
  complete publication certificate, producer checkpoint session, and relocated
  rejection ledger.
- Produces: complete lifecycle-v6 durable dependency replay and rejection
  ledger invalidation while retaining producer v27, plus no-budget typed
  witness rehydration for warm finite lifecycle-v6 hits.

- [ ] **Step 1: Add RED tests for the exact durable dependency set**

Complete the fixture with a checkpoint directory and assert its v6 lifecycle
certificate contains only the unchanged schema-v1 aggregate query/result and
durable dependency rows:

```python
expected_functions = {
    fixture.publishing_consumer,
    *fixture.incoming_owners,
    fixture.helper_target,
    fixture.allocator,
    fixture.grow_target,
    fixture.session_root,
    fixture.backend_root,
    *fixture.callback_targets,
}
dependencies = {
    (row["kind"], row["identifier"])
    for row in lifecycle_certificate["dependencies"]
}
assert {("function", address) for address in expected_functions} <= dependencies
assert ("global-slot", fixture.callback_slot) in dependencies
assert ("absolute-reference", fixture.publication_slot) in dependencies
binding_entries = {
    binding[0]
    for binding in lifecycle_certificate["query"]["consumer_bindings"]
}
assert binding_entries == set(fixture.consumer_entries)
assert lifecycle_certificate["query"]["function_entry"] == fixture.minimum_consumer
assert lifecycle_certificate["result"]["values"] == [0, 74]
assert all(
    len(row["fingerprint"]) == 64
    for row in lifecycle_certificate["dependencies"]
)
```

Do not assert or add serialized fields for the active consumer/caller, typed
returning bodies, imports, taint flows, reference rows/disjointness, or backend
bridges. Those are in-memory evidence. In a separate in-process unit test,
compare the internal certificate's complete returning/backend functions with
the function dependencies above and assert its active caller is
`fixture.publishing_consumer != fixture.minimum_consumer`.

- [ ] **Step 2: Add RED checkpoint replay tests for v5/v6 separation and v27 stability**

Create valid current producer and lifecycle files, rewrite only the lifecycle
query to `object-tag-lifecycle-analysis-v5` with a self-consistent digest, and
resume with budget one. Assert:

```python
assert _MOVZX_PRODUCER_ANALYSIS_SEMANTICS == "movzx-producer-analysis-v27"
assert _OBJECT_TAG_LIFECYCLE_ANALYSIS_SEMANTICS == "object-tag-lifecycle-analysis-v6"
assert producer_v27_query_id in validated_query_ids
assert lifecycle_v5_path.exists()
assert lifecycle_v6_result_values == [0, 74]
```

The progress log must show reuse of the unchanged v27 producer query and
evaluation of a new v6 lifecycle query.

Add a warm finite lifecycle-v6 checkpoint test. Seed a valid schema-v1 file,
then resume with `producer_query_budget=0`. After `_load` validates the durable
rows, assert `_ProducerCertificateSession.evaluate` invokes `compute` under
every exact `_ObjectTagLifecycleEvaluationContext` in a rehydration mode,
rebuilds the publication certificate, and consumes neither query budget nor
`completed_this_run`. Assert the continuing `_recover_indexed_table` entry loop
then rebuilds the same table hypothesis from current bytes. In the disposable
accepted-candidate trial, assert installation increments `control_flow_revision`,
ordinary closure reaches quiescence, final normalization increments/binds its
revisions, and `_ProducerCertificateSession.evaluate` is invoked again for the
definitive post-install variant. Only that variant may report the hypothesis
reproduced; `RawCfg` finalization rebuilds the exact provisional obligation
union from it. Require its fresh aggregate result and fresh canonical dependency
tuple to equal the stored post-install result/dependencies before reporting a
validated hit. A matching pre-install file is insufficient. Mutate either
post-install value in separate cases; each file becomes stale and may not
supply a finite result or typed evidence.

Add a budget-one/fresh-resume test in which the pre-install query variant
already exists, but installed edges plus seed provenance binding create a new
dependency SHA-256 during definitive validation. Assert a second file with the
same query SHA-256 and different dependency SHA-256 is written, the normal
fresh-resume gate fires before reproduction, and the entire mutated trial is
discarded. On resume, recovery rebuilds the trial from authoritative seeds,
rehydrates/validates the post-install variant under exact bindings, and only
then emits the certificate/obligations. No test may treat the pre-install
snapshot as final.

In `test_retro_backend_lifetime_audit.py`, add
`test_return_path_publication_checkpoint_warm_hit_rejects_hostile_external_evidence`:
keep every durable dependency fingerprint valid, but remove one current
provisional reconciliation result, add an extra stale result, or change its
interval/hash. Warm rehydration must rebuild the current obligations, the
crosscheck digest must bind their exact set, `require_publishable()` must fail,
and no accepted publication audit row or bundle may be serialized. External
reconciliation is never satisfied by a warm checkpoint.

- [ ] **Step 3: Add RED dependency invalidation tests**

Parameterize semantic mutations to one returning closure function, one finite
candidate target, one exact incoming owner/call edge, the callback slot, one
session/backend function, and every field of one raw publication-slot reference
row (including provisional source interval/hash and current ownership digest).
For each, seed a prior lifecycle checkpoint and assert its stored
`absolute-reference` or function/global fingerprint no longer validates.
Exercise the actual query-independent dependency fingerprint rather than
changing only the compiler SHA.

Add checkpoint invalidation/revalidation coverage for ownership growth: write
a valid schema-v1 checkpoint with the initial provisional raw inventory, then
grow ownership into the returning closure before resume. Assert the old
`absolute-reference` fingerprint misses; the exact binding is re-evaluated,
the stale certificate is not reused, and the result is blocked. A second case
where ownership grows only outside the returning closure must miss, recompute,
and write a fresh finite checkpoint with the new raw-inventory fingerprint.

Add a two-binding cache test whose shared query root/minimum consumer does not
publish and whose later binding does. Populate a bottom result for the first
binding and a successful certificate for the later binding, then replay in the
opposite order. Assert no memo entry crosses binding identity and all cache
keys include query SHA, the full typed binding, `consumer_entry`, structural
publication/root/observation/field inputs, limits digest, and relevant
revisions—but no computed witness digest.

- [ ] **Step 4: Add RED relocated-rejection-ledger replay coverage**

Create a valid ledger whose contract says lifecycle v5 and producer v27. Resume
under current constants and assert `rejection-ledger-miss`, `trial-start`, and
a newly written contract with lifecycle v6 and producer v27. Keep the malformed
record tests strict; do not relabel the old file in place.

- [ ] **Step 5: Run persistence/ledger RED tests**

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_x86_cfg.py tests/test_retro_backend_lifetime_audit.py \
  -k 'return_path_publication_checkpoint or lifecycle_checkpoint or relocated_rejection_ledger' -vv
```

Expected: FAIL because complete publication/totality dependency replay and the
v5 rejection-ledger transition are not yet asserted or propagated.

- [ ] **Step 6: Verify lifecycle-only absolute-reference fingerprints**

Confirm Task 3's fingerprint includes the canonical query-independent raw rows
and recovery revisions, excludes returning bodies/disjointness, and that its
decoder accepts the kind only for lifecycle v6. Add any missing hostile
checkpoint coverage found by Step 3. Do not broaden producer-v27 dependency
kinds or checkpoint schema v1.

- [ ] **Step 7: Make publication memo hits validate and replay dependencies**

Store the complete typed publication certificate (including binding/caller,
slice, returning bodies/edges/candidates, imports, taint flows, raw inventory,
body address-domain witnesses, incoming owners, backend/session/totality
evidence, and provisional reference source rows) in
`_DependencyMemoEntry.result`. `RawCfg` finalization derives the exact
obligation union from those fresh source rows.
`_DependencyMemoEntry.dependencies` contains only canonical
`(kind, identifier, fingerprint)` rows for functions, global slots, and the
lifecycle-only publication `absolute-reference`; it never contains typed
certificate evidence. On hit, use `_dependency_memo_hit` to validate and replay
those rows to the lifecycle collector, then return `.result`. Key positive and
bottom memo entries only by `_PublicationCertificateLookupKey`: structural
inputs plus current revisions, never certificate or witness digests.

For a durable warm finite hit, do not return this in-memory memo result merely
because aggregate checkpoint dependencies validate. Run the exact compute path
in no-budget rehydration mode, rebuild `.result`, and compare the fresh
aggregate result and dependency rows byte-for-byte/canonically with the stored
checkpoint before installing the in-memory entry.

Concretely, change `_ProducerCertificateSession.evaluate`: when `_load` returns
a finite lifecycle-v6 entry after current fingerprint validation, keep that
entry aside rather than preloading `producer_domain_memo`. Clear any memo value,
invoke `compute` through `_producer_domain_cached` under the normal exact
binding push/pop path with a `rehydrating_warm_hit` guard, and capture the fresh
`_ProducerDomainMemoEntry`. The producer entry remains aggregate-only; the
compute path repopulates the publication `_DependencyMemoEntry.result` with
the typed certificate and leaves only dependency triples in its
`.dependencies`. This call does not decrement `remaining_budget`,
increment `completed_this_run`, or write a checkpoint. Accept the warm hit only
when fresh `.result` equals the stored aggregate result and fresh
`.dependencies` equals the stored canonical dependency tuple exactly. On
mismatch mark the file stale, discard the fresh/incomplete memo state, and
continue through ordinary budgeted evaluation or bottom. Blocked files remain
aggregate bottoms and never provide positive publication evidence.

Run this session path once more at definitive post-install validation after
the installed graph is quiescent and `_PublicationFinalReferenceEnvironment`
is fixed. The same lifecycle query SHA may therefore have pre-install and
post-install files distinguished by dependency SHA. Only the post-install
entry is eligible for `_ReproducedPublicationTableHypothesis`. If evaluation
creates that variant and exhausts the per-run budget, propagate the existing
fresh-resume requirement before the outer loop records reproduction; discard
the mutated trial rather than caching it for reuse. On resume, a warm hit still
executes no-budget typed rehydration against the rebuilt installed graph and
final environment. Validate the resulting `_DependencyMemoEntry` immediately
before `RawCfg`; do not promote or rewrite the earlier snapshot.

- [ ] **Step 8: Assert semantic separation remains fixed**

Assert these constants without changing them:

```python
_MOVZX_PRODUCER_ANALYSIS_SEMANTICS = "movzx-producer-analysis-v27"
_OBJECT_TAG_LIFECYCLE_ANALYSIS_SEMANTICS = (
    "object-tag-lifecycle-analysis-v6"
)
```

The implementation must already have advanced lifecycle semantics in Task 2.
Keep v5 only as rejected prior input. Do not change the producer constant,
producer query fields, or lifecycle schema string.

- [ ] **Step 9: Bind the rejection ledger through its existing contract field**

Keep `rejection_contract()` structure unchanged. Its existing
`object_tag_lifecycle_analysis_semantics` value now carries v6. Update the test
name that refers to old v26/v4 semantics so it explicitly verifies v27/v5 is
replayed under v27/v6.

- [ ] **Step 10: Run focused GREEN persistence tests**

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_x86_cfg.py tests/test_retro_backend_lifetime_audit.py \
  -k 'return_path_publication or object_tag_lifecycle_checkpoint or relocated_rejection_ledger' -vv
```

Expected: PASS. Inspect one lifecycle JSON file and verify it says schema v1,
semantics v6, contains only the existing query/result/dependency envelope,
includes a fingerprinted `absolute-reference`, and retains compiler SHA/limits.

- [ ] **Step 11: Review checkpoint 3**

```bash
rg -n 'movzx-producer-analysis-v|object-tag-lifecycle-analysis-v' \
  tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
rg -n 'absolute-reference' tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
git diff --check
git diff -- tools/mwcc_retro/x86_cfg.py tools/mwcc_retro/backend_lifetime_audit.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_lifetime_audit.py
```

Expected: production contains producer v27 and lifecycle v6 only; tests retain
v5 solely as stale input. Confirm cache-hit tests compare exact dependency sets
and that the rejection ledger misses instead of silently skipping. Pause for
review.

- [ ] **Step 12: Commit persistence and semantics**

```bash
git add tools/mwcc_retro/x86_cfg.py tools/mwcc_retro/backend_lifetime_audit.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_lifetime_audit.py
git commit -m "feat(mwcc-retro): persist lifecycle publication proofs"
```

---

### Task 7: Run the focused retail proof and check `0x4b1f95` separately

**Files:**

- Create: `docs/superpowers/results/2026-08-02-return-path-publication-noninterference.md`
- Modify if a generic proof defect is exposed:
  `tools/mwcc_retro/x86_cfg.py`
- Modify if an external reconciliation defect is exposed:
  `tools/mwcc_retro/backend_lifetime_audit.py`
- Modify if a regression fixture is needed:
  `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify if an audit regression fixture is needed:
  `tools/melee-agent/tests/test_retro_backend_lifetime_audit.py`

**Interfaces:**

- Consumes: complete v6 implementation and branch-local static retail command.
- Produces: a canonical ignored static bundle and a tracked result note proving
  29 publication-blocked calls are admitted while `0x4b1f95` remains separate.

- [ ] **Step 1: Prepare the exact compiler/Ghidra environment**

```bash
ROOT=/Users/mike/code/melee/.claude/worktrees/codex-issue-1240-retail-pcode-proof
OUT="$ROOT/build/mwcc_retro/gc125n-proof/return-path-publication-v6"
test ! -e "$OUT" || { echo "refusing to overwrite $OUT" >&2; exit 1; }
cd "$ROOT"
DECOMP_AGENT_ID=codex-issue-1240-retail-pcode-proof \
  melee-agent debug retro ghidra-setup \
  --melee-root "$ROOT" \
  --project-dir "$ROOT/tools/mwcc_debug/ghidra_project"
```

Expected: exact compiler hash and validated Ghidra project are ready.

- [ ] **Step 2: Run the focused branch-local static retail command**

```bash
cd "$ROOT/tools/melee-agent"
DECOMP_AGENT_ID=codex-issue-1240-retail-pcode-proof \
  python -m src.cli debug retro probe-backend-map \
  "$ROOT/src/melee/mn/mndiagram.c" \
  -f mnDiagram_DrawFighterHeaders \
  --static-only \
  --melee-root "$ROOT" \
  -O "$OUT"
```

Expected: command succeeds, exact raw/Ghidra reconciliation accepts every
provisional publication-reference obligation, and the canonical static bundle
is published under `OUT`. A fixed-point-valid lifecycle certificate alone is
not sufficient to publish the bundle; it must be the current definitive
post-install certificate and still pass external reconciliation.

- [ ] **Step 3: Assert the 29 lifecycle calls from the canonical JSONL**

Run this read-only verifier:

```bash
cd "$ROOT"
PYTHONPATH="$ROOT/tools" python - "$OUT" <<'PY'
import json
import sys
from pathlib import Path

from mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle

bundle = resolve_lifetime_bundle(Path(sys.argv[1]))
rows = [
    json.loads(line)
    for line in bundle.canonical_files()["raw-pe-cfg.v1.jsonl"].splitlines()
]
admitted = [
    row
    for row in rows
    if row.get("record_kind") == "jump-table"
    and row.get("flow_kind") == "call"
    and row.get("base") == 0x00560648
    and row.get("guard_operator") == "movzx-lifecycle-domain"
    and row.get("index_min") == 0
    and row.get("index_max") == 74
]
assert len(admitted) == 29, [hex(row["address"]) for row in admitted]
assert 0x004B1F95 not in {row["address"] for row in admitted}
print("admitted", len(admitted))
print("addresses", " ".join(hex(row["address"]) for row in admitted))
PY
```

Expected: `admitted 29`. If the count differs, inspect the exact lifecycle
provenance and fix only a generic proof defect; do not add an address case.

- [ ] **Step 4: Assert the exact publication evidence**

Run a second read-only verifier against the accepted bundle audit row:

```bash
PYTHONPATH="$ROOT/tools" python - "$OUT" <<'PY'
import hashlib
import json
from pathlib import Path
from sys import argv

from mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle

payload = resolve_lifetime_bundle(Path(argv[1])).canonical_files()[
    "raw-pe-cfg.v1.jsonl"
]
rows = [json.loads(line) for line in payload.splitlines()]
evidence = [
    row
    for row in rows
    if row.get("record_kind") == "return-path-publication-noninterference"
]
assert len(evidence) == 1, evidence
witness = evidence[0]
assert witness["publication_address"] == 0x00435628
assert witness["observation_address"] == 0x0043576B
expected_returning = {
    0x403D90, 0x403DB0, 0x403DD0, 0x403E30, 0x403ED0, 0x403F60,
    0x403FD0, 0x404020, 0x4040E0, 0x404180, 0x404220, 0x4042A0,
    0x4042F0, 0x404400, 0x4044E0, 0x404610, 0x406480, 0x4128F0,
    0x412990, 0x4129C0, 0x412A50, 0x412A90, 0x4138B0, 0x4138C0,
    0x413950, 0x413990, 0x413A00, 0x413A40, 0x436470, 0x441FA0,
    0x4422F0, 0x443110, 0x443120, 0x4431A0, 0x49D140, 0x49D170,
    0x49D1B0, 0x49D240, 0x4A24E0,
}
expected_imports = {
    ("KERNEL32.dll", "EnterCriticalSection", 0x57A168),
    ("KERNEL32.dll", "LeaveCriticalSection", 0x57A16C),
    ("KERNEL32.dll", "GlobalAlloc", 0x57A190),
    ("KERNEL32.dll", "GetLastError", 0x57A178),
    ("KERNEL32.dll", "GlobalFlags", 0x57A1E4),
}
expected_reference_owners = {
    0x435350: 0x43534E,
    0x43562A: 0x435628,
    0x435AE2: 0x435AE0,
    0x4636B2: 0x4636B0,
    0x4636C4: 0x4636C2,
    0x463B7E: 0x463B7C,
    0x463B90: 0x463B8E,
    0x4A1CC2: None,
    0x4A1CCB: None,
    0x4A1D10: None,
    0x4A1D19: None,
    0x4A1DB4: None,
    0x4A1DBD: None,
    0x4A2146: 0x4A2144,
    0x4A214F: 0x4A214D,
    0x4A21BD: 0x4A21BB,
    0x4A21C6: 0x4A21C4,
    0x4A2269: 0x4A2267,
    0x4A2272: 0x4A2270,
}
expected_provisional = {
    address: (
        0x4A1CAA,
        0x4A1DD0,
        "ad98fc322eda4028deb382fe6c3f844e70bab2b747d5b620088ad6e7bd8903a0",
    )
    for address in (
        0x4A1CC2, 0x4A1CCB, 0x4A1D10,
        0x4A1D19, 0x4A1DB4, 0x4A1DBD,
    )
}
assert set(witness["returning_body_entries"]) == expected_returning
assert len(expected_returning) == 39
assert witness["default_callback_closure_count"] == 56
assert {
    (row["dll"], row["name"], row["iat_va"])
    for row in witness["imports"]
} == expected_imports
inventory = witness["reference_inventory"]
assert len(inventory) == 19
assert len({row["reference_start"] for row in inventory}) == 19
assert {row["reference_start"] for row in inventory} == set(expected_reference_owners)
assert inventory == sorted(
    inventory,
    key=lambda row: (
        row["reference_start"], row["reference_end"], row["reference_class"]
    ),
)

base_keys = {
    "reference_start", "reference_end", "bytes_hex", "relocation_type",
    "reference_class", "target_slot", "source_kind", "source_evidence",
    "residue_reconciliation_sha256",
}
for row in inventory:
    assert set(row) == base_keys, row
    start = row["reference_start"]
    expected_owner = expected_reference_owners[start]
    assert row["reference_end"] == start + 4
    assert row["bytes_hex"] == "30715800"
    assert row["relocation_type"] == 3
    assert row["reference_class"] == "type-3-relocation"
    assert row["target_slot"] == 0x587130
    source = row["source_evidence"]
    assert source["kind"] == row["source_kind"]
    if expected_owner is not None:
        assert row["source_kind"] == "owned-instruction"
        assert set(source) == {
            "kind", "owner_instruction_address", "owner_function_entry",
            "range_start", "range_end", "owned_interval",
        }
        assert source["owner_instruction_address"] == expected_owner
        assert source["range_start"] <= expected_owner < source["range_end"]
        assert set(source["owned_interval"]) == {"start", "end"}
        assert (
            source["owned_interval"]["start"]
            <= expected_owner
            < source["owned_interval"]["end"]
        )
        assert row["residue_reconciliation_sha256"] is None
    else:
        assert row["source_kind"] == "provisional-unowned-executable"
        assert set(source) == {
            "kind", "interval_start", "interval_end", "bytes_sha256",
            "current_ownership_sha256",
        }
        interval_start, interval_end, interval_sha256 = expected_provisional[start]
        assert (
            source["interval_start"],
            source["interval_end"],
            source["bytes_sha256"],
        ) == (interval_start, interval_end, interval_sha256)
        assert len(source["current_ownership_sha256"]) == 64
        assert row["residue_reconciliation_sha256"] == witness[
            "residue_reconciliation_sha256"
        ]

raw_inventory_projection = [
    {
        key: value
        for key, value in row.items()
        if key != "residue_reconciliation_sha256"
    }
    for row in inventory
]
canonical_inventory = json.dumps(
    raw_inventory_projection,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
).encode("utf-8")
assert witness["reference_inventory_sha256"] == hashlib.sha256(
    canonical_inventory
).hexdigest()
assert witness["residue_reconciliation_sha256"]
print("returning", len(expected_returning))
print("default-closure", witness["default_callback_closure_count"])
print("imports", len(expected_imports))
print("references", len(inventory), "provisional", len(expected_provisional))
PY
```

Expected: 39 returning bodies, a 56-function default callback closure, five
exact imports/IATs, all 19 `0x587130` reference sites, and the six provisional
executable sites accepted by the external reconciliation.

- [ ] **Step 5: Check `0x4b1f95` independently**

```bash
cd "$ROOT"
PYTHONPATH="$ROOT/tools" python - "$OUT" <<'PY'
import json
from pathlib import Path
from sys import argv

from mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle

payload = resolve_lifetime_bundle(Path(argv[1])).canonical_files()[
    "raw-pe-cfg.v1.jsonl"
]
rows = [json.loads(line) for line in payload.splitlines()]

def contains_address(value, needle):
    if isinstance(value, dict):
        return any(contains_address(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(contains_address(item, needle) for item in value)
    if isinstance(value, int):
        return value == needle
    if isinstance(value, str):
        lowered = value.lower()
        return f"0x{needle:x}" in lowered or f"0x{needle:08x}" in lowered
    return False

blockers = [
    row
    for row in rows
    if row.get("record_kind") == "unresolved-control-target"
    and row.get("address") == 0x004B1F95
    and row.get("kind") == "computed-flow-blocker"
]
assert len(blockers) == 1, blockers
assert "index=75" in blockers[0]["detail"]
assert not any(
    row.get("record_kind") == "jump-table"
    and row.get("address") == 0x004B1F95
    and row.get("guard_operator") == "movzx-lifecycle-domain"
    for row in rows
)
assert not any(
    "return-path-publication-noninterference" in json.dumps(row, sort_keys=True)
    and contains_address(row, 0x004B1F95)
    for row in rows
), "0x4b1f95 must have no publication-certificate/provenance row"
print(blockers[0]["detail"])
PY
```

Expected: one independent computed-flow blocker at `0x4b1f95`; it has no
publication certificate provenance.

- [ ] **Step 6: Record the exact retail witness**

Create the result note with:

- branch and commit tested;
- compiler SHA, bundle generation/manifest digest, and external residue
  reconciliation SHA-256;
- the exact focused command;
- all 29 admitted call addresses and lifecycle bound `0..74`;
- exact publication `0x435628`, observation `0x43576b`, helper call
  `0x43575c -> 0x436470`, three incoming calls/owners, session `0x43edb0`, and
  backend root `0x48b6c0` as observed facts;
- all 39 returning-body entries and the five exact `KERNEL32.dll` name/IAT
  identities checked in Step 4;
- the canonical direct closure rooted at `0x41e960` has 56 owned functions,
  identified as an observed integration witness rather than a production rule;
- all 19 raw references to `0x587130`, identifying `0x4a1cc2`, `0x4a1ccb`,
  `0x4a1d10`, `0x4a1d19`, `0x4a1db4`, and `0x4a1dbd` as the six provisional
  executable sites accepted only by the final external reconciliation;
- explicit wording that the first actual is loaded from `[EDI+0x16]` and its
  value is copied to `0x587ffc` as an opaque-copy escape; and
- the separate `0x4b1f95` blocker detail.

Do not mention local agent process state or describe retail addresses as
acceptance rules.

- [ ] **Step 7: Review checkpoint 4**

Review the result note and canonical verifier output. Require the 29/30 split,
zero new unresolved control other than the already separated blocker set,
exact raw/Ghidra reconciliation, and no publication provenance on `0x4b1f95`.
Pause for review before the full suite.

- [ ] **Step 8: Commit the retail result and any generic repair**

```bash
git add docs/superpowers/results/2026-08-02-return-path-publication-noninterference.md
git add tools/mwcc_retro/x86_cfg.py tools/mwcc_retro/backend_lifetime_audit.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_lifetime_audit.py
git commit -m "test(mwcc-retro): verify retail publication proof"
```

If no production/test repair was needed, only the result note is staged.

---

### Task 8: Run full verification and final proof review

**Files:**

- Verify: `tools/mwcc_retro/x86_cfg.py`
- Verify: `tools/mwcc_retro/backend_lifetime_audit.py`
- Verify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Verify: `tools/melee-agent/tests/test_retro_backend_lifetime_audit.py`
- Verify: `docs/superpowers/results/2026-08-02-return-path-publication-noninterference.md`

**Interfaces:**

- Consumes: all prior task commits.
- Produces: one fully verified branch ready for collection/review.

- [ ] **Step 1: Use the completion-verification skill**

Read and follow `superpowers:verification-before-completion` before making any
passing or complete claim.

- [ ] **Step 2: Run focused and adjacent pytest suites**

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_x86_cfg.py \
  tests/test_retro_backend_lifetime_audit.py \
  tests/test_retro_backend_cli.py -x
```

Expected: all tests pass.

- [ ] **Step 3: Run static validation**

```bash
cd ../..
python -m ruff check \
  tools/mwcc_retro/x86_cfg.py \
  tools/mwcc_retro/backend_lifetime_audit.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
python -m py_compile \
  tools/mwcc_retro/x86_cfg.py tools/mwcc_retro/backend_lifetime_audit.py
git diff --check
```

Expected: zero errors.

- [ ] **Step 4: Audit semantic constants and production address independence**

```bash
rg -n 'movzx-producer-analysis-v27|object-tag-lifecycle-analysis-v6' \
  tools/mwcc_retro/x86_cfg.py
rg -n '435628|43576b|587130|587ffc|436470|44235b|4351c0|48b6c0|4b1f95' \
  tools/mwcc_retro/x86_cfg.py
rg -n 'no-escape|does-not-escape' \
  tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
```

Expected: exact v27/v6 constants are present; production retail-address scan
has zero matches; no positive provenance falsely claims no escape.

- [ ] **Step 5: Audit dependency completeness from a real checkpoint**

Run the focused checkpoint test with `-s` and retain its temporary lifecycle
JSON long enough to inspect. Confirm schema v1 contains only the aggregate
query/result and canonical dependency rows/fingerprints. Compare its function,
global-slot, and query-independent `absolute-reference` dependencies with the
in-process certificate's returning closure, candidates, session/backend proof,
incoming owners, and raw reference inventory. Confirm a second in-process call
records the identical dependency set from cache without serializing internal
typed witnesses. When both pre-install and post-install files exist for the
same lifecycle query SHA, identify the definitive file by its current
post-install dependency SHA and prove that only it supplies the emitted
certificate/obligations; the earlier variant must be stale under current
control-flow/seed/reference fingerprints.

- [ ] **Step 6: Inspect the complete branch diff**

```bash
git log --oneline --decorate -8
git diff --stat 54927e8e3..HEAD
git diff 54927e8e3..HEAD -- \
  tools/mwcc_retro/x86_cfg.py \
  tools/mwcc_retro/backend_lifetime_audit.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_lifetime_audit.py \
  docs/superpowers/results/2026-08-02-return-path-publication-noninterference.md
git status --short
```

Expected: only intended code/tests/result changes plus the pre-existing
untracked `.agents/` and `.pi/` paths. Verify every hostile mutation fails at
the intended boundary and no table integrity check was weakened.

- [ ] **Step 7: Run a final review checkpoint**

Review these questions explicitly:

1. Can the exception execute without an active lifecycle-v6 context?
2. Is the semantic caller exactly the active binding's `consumer_entry`, even
   when the publishing consumer is not the minimum/query entry?
3. Does each republish cut prove both a distinct closed new generation and the
   death of every live alias of the old identity?
4. Are all returning direct/finite targets, typed bodies/edges, and
   context-pruned candidates bound?
5. Is the slot-keyed fingerprint a complete query-independent raw inventory of
   only type-3 and decoded literal references exactly equal to the slot, with
   closure-relative disjointness and per-body materialization/address domains
   only in separate function-dependent typed witnesses?
6. Are provisional unowned executable rows revalidated only after provisional
   table installation, installed-edge quiescence, and final normalization, then
   accepted only by the later exact-set external Ghidra/residue gate?
7. Is `0x587ffc` correctly described as the opaque-copy destination for the
   first actual loaded from `[EDI+0x16]`?
8. Are imports exact parsed PE identities, including name/ordinal lookup mode,
   IAT, compiler SHA, and narrow typed argument effects?
9. Does callback failure rely only on context-bound totality, with partial slot
   overwrites rejected?
10. Does strict caller closure include every incoming owner under one backend
   root, never a union of split closures?
11. Are memo lookup/bottom keys structural, with typed evidence only in
    `_DependencyMemoEntry.result`, canonical dependency triples only in
    `.dependencies`, and no cache hit crossing consumer bindings?
12. Does checkpoint schema v1 remain aggregate-only while producer stays v27,
    lifecycle/rejection-ledger semantics use v6, and every warm finite v6 hit
    rehydrates the definitive post-install typed evidence without budget before
    exact result/dependency comparison?
13. Does target seeding add no candidate edge, does the disposable trial
    provisionally install the table and close its graph, and does exact-binding
    recomputation happen only after all dependency-affecting normalization?
14. On post-install failure, is the entire mutated trial discarded and barred
    from `reusable_trial`, and does the final assertion validate current
    certificate dependency fingerprints rather than hypothesis membership?
15. Does the retail verifier require exactly one audit row, 39 returning
    bodies, the 56-body default closure, five exact imports/IATs, exactly 19
    unique full `0x587130` rows, a recomputed inventory digest, and six exact
    interval/hash/reconciliation bindings?
16. Does the verifier detect both integer fields and hex-string provenance when
    asserting `0x4b1f95` has no publication certificate?

Any "no" blocks completion.

- [ ] **Step 8: Commit final test-only corrections if needed**

If verification required a correction, rerun Steps 2-7 and commit it:

```bash
git add tools/mwcc_retro/x86_cfg.py tools/mwcc_retro/backend_lifetime_audit.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_lifetime_audit.py \
  docs/superpowers/results/2026-08-02-return-path-publication-noninterference.md
git commit -m "test(mwcc-retro): harden publication proof verification"
```

If no correction was needed, do not create an empty commit.
