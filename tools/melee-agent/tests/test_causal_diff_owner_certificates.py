from dataclasses import replace

import pytest

from src.mwcc_debug.causal_diff import owner_certificate
from src.mwcc_debug.causal_diff.canonical import stable_id
from src.mwcc_debug.causal_diff.graph import add_adapter_results_atomically
from src.mwcc_debug.causal_diff.inference import VerdictStatus
from src.mwcc_debug.causal_diff.models import (
    Confidence,
    EvidenceEdge,
    EvidenceNode,
    Provenance,
)
from src.mwcc_debug.causal_diff.object_binding_adapter import (
    ObjectBindingEvidence,
)
from src.mwcc_debug.causal_diff.owner_certificate import (
    OwnerCertificateResult,
    OwnerResolutionStatus,
    OwnerRoleKey,
    OwnerSemanticState,
    build_owner_certificates,
)
from src.mwcc_debug.causal_diff.store import canonical_record_bytes
from tests.owner_certificate_fixtures import (
    STORE_FACTORIES,
    ambiguous_evidence,
    canonical_result,
    complete_evidence,
    disconnected_evidence,
    evidence_with_allocator_origin_conflict,
    evidence_with_certificate_and_global_rejection,
    evidence_with_certificate_and_role_rejection,
    evidence_with_coordinated_allocator_change,
    evidence_with_global_and_role_rejection,
    evidence_with_heuristic_support,
    evidence_with_independent_paths,
    evidence_with_lineage_variant,
    evidence_with_mutation_parent_override,
    evidence_with_object_generation_conflict,
    evidence_with_role_statuses,
    evidence_with_split_physical_assignment,
    evidence_with_two_mutation_outputs,
    evidence_with_zero_sized_owner,
    evidence_without_instrumentation_identity,
    first_role,
    future_complete_backend,
    only,
    other_role,
    replace_record,
    run_synthetic_future_complete_pair,
    second_role,
    support,
)
from tests.test_causal_diff_object_bindings import ALL_CAPABILITIES, _object_result

ROLE = OwnerRoleKey("use:0", "gpr", "row-home", 4, "locals")
STATE = OwnerSemanticState(21, 0x44, 4)


class _CountingTuple(tuple):
    def __new__(cls, values, counter):
        value = super().__new__(cls, values)
        value.counter = counter
        return value

    def __iter__(self):
        for item in super().__iter__():
            self.counter["visits"] += 1
            yield item


@pytest.mark.parametrize("path_count", [8, 32])
def test_candidate_index_is_built_once_without_per_candidate_source_rescans(path_count):
    evidence = evidence_with_independent_paths(path_count)
    counter = {"visits": 0}
    counted = ObjectBindingEvidence(
        _CountingTuple(evidence.nodes, counter),
        _CountingTuple(evidence.edges, counter),
        evidence.capabilities,
        evidence.capture_run_id,
        evidence.instrumentation_identity,
    )

    index = owner_certificate._index_evidence(counted)
    assert counter["visits"] == len(evidence.nodes) + len(evidence.edges)

    counter["visits"] = 0
    candidates = owner_certificate._enumerate_candidates(index)
    validated = tuple(owner_certificate._validate_candidate(counted, index, candidate) for candidate in candidates)

    assert len(candidates) == path_count
    assert all(not isinstance(item, owner_certificate.OwnerCertificateRejection) for item in validated)
    assert counter["visits"] == 0


def test_indexed_many_path_result_is_byte_stable_under_record_permutation():
    evidence = evidence_with_independent_paths(8)
    permuted = ObjectBindingEvidence(
        tuple(reversed(evidence.nodes)),
        tuple(reversed(evidence.edges)),
        evidence.capabilities,
        evidence.capture_run_id,
        evidence.instrumentation_identity,
    )

    assert canonical_result(owner_certificate.validate_owner_evidence(evidence)) == canonical_result(
        owner_certificate.validate_owner_evidence(permuted)
    )


def test_indexed_registration_rejects_conflicting_exact_path_id_permutation_stably():
    evidence = complete_evidence()
    original = support(evidence, "pcode-emission")
    conflicting = original.with_attributes({**original.attributes, "unknown": "conflict"})

    def diagnostic(nodes):
        return owner_certificate.validate_owner_evidence(
            ObjectBindingEvidence(
                nodes,
                evidence.edges,
                evidence.capabilities,
                evidence.capture_run_id,
                evidence.instrumentation_identity,
            )
        )

    first = diagnostic((*evidence.nodes, conflicting))
    second = diagnostic((conflicting, *evidence.nodes))

    assert first.certificate_nodes == second.certificate_nodes == ()
    assert first.role_resolutions == second.role_resolutions == ()
    assert {item.reason for item in first.global_rejections} == {"unregistered-support"}
    assert only(first.global_rejections).candidate_record_ids == (original.record_id, original.record_id)
    assert canonical_result(first) == canonical_result(second)


_PATH_NODE_KINDS = (
    "compiler-object",
    "assembly-operand-anchor",
    "retail-pcode",
    "pcode-operand",
    "retail-virtual-register",
    "allocator-node",
    "stack-object",
)
_PATH_EDGE_KINDS = (
    "assembly-anchor-emitted-by-pcode",
    "pcode-operand-lineage",
    "pcode-operand-uses-virtual",
    "object-materializes-virtual",
    "maps-to-allocator-node",
    "object-has-stack-home",
)


def _path_record(evidence: ObjectBindingEvidence, record_kind: str) -> EvidenceNode | EvidenceEdge:
    candidate = only(owner_certificate._enumerate_candidates(owner_certificate._index_evidence(evidence)))
    return only(record for record in candidate.path_records if record.kind == record_kind)


def _with_conflicting_path_record(
    evidence: ObjectBindingEvidence,
    record_kind: str,
    *,
    prepend: bool,
) -> ObjectBindingEvidence:
    records = evidence.nodes if record_kind in _PATH_NODE_KINDS else evidence.edges
    original = _path_record(evidence, record_kind)
    conflicting = original.with_attributes({**original.attributes, "conflict_marker": record_kind})
    changed_records = (conflicting, *records) if prepend else (*records, conflicting)
    return ObjectBindingEvidence(
        changed_records if record_kind in _PATH_NODE_KINDS else evidence.nodes,
        changed_records if record_kind in _PATH_EDGE_KINDS else evidence.edges,
        evidence.capabilities,
        evidence.capture_run_id,
        evidence.instrumentation_identity,
    )


def _with_python_equal_path_conflict(
    evidence: ObjectBindingEvidence,
    record_kind: str,
    *,
    prepend: bool,
) -> ObjectBindingEvidence:
    records = evidence.nodes if record_kind in _PATH_NODE_KINDS else evidence.edges
    original = _path_record(evidence, record_kind)
    assert original.attributes["class_id"] == 0
    conflicting = original.with_attributes({**original.attributes, "class_id": False})
    assert conflicting == original
    assert canonical_record_bytes(conflicting) != canonical_record_bytes(original)
    changed_records = (conflicting, *records) if prepend else (*records, conflicting)
    return ObjectBindingEvidence(
        changed_records if record_kind in _PATH_NODE_KINDS else evidence.nodes,
        changed_records if record_kind in _PATH_EDGE_KINDS else evidence.edges,
        evidence.capabilities,
        evidence.capture_run_id,
        evidence.instrumentation_identity,
    )


@pytest.mark.parametrize("record_kind", (*_PATH_NODE_KINDS, *_PATH_EDGE_KINDS))
def test_conflicting_path_id_permutation_is_globally_stable(record_kind):
    evidence = complete_evidence()
    original = _path_record(evidence, record_kind)
    prepend = owner_certificate.validate_owner_evidence(
        _with_conflicting_path_record(evidence, record_kind, prepend=True)
    )
    append = owner_certificate.validate_owner_evidence(
        _with_conflicting_path_record(evidence, record_kind, prepend=False)
    )

    assert canonical_result(prepend) == canonical_result(append)
    for result in (prepend, append):
        assert result.certificate_nodes == ()
        assert len(result.global_rejections) == 1
        rejection = only(item for item in result.global_rejections if item.reason == "unregistered-support")
        assert rejection.role is None
        assert rejection.candidate_record_ids == (original.record_id, original.record_id)


@pytest.mark.parametrize(
    "record_kind",
    ("retail-virtual-register", "maps-to-allocator-node"),
)
def test_python_equal_same_id_conflicts_are_global_and_permutation_stable(record_kind: str) -> None:
    evidence = complete_evidence()
    original = _path_record(evidence, record_kind)
    prepend = owner_certificate.validate_owner_evidence(
        _with_python_equal_path_conflict(
            evidence,
            record_kind,
            prepend=True,
        )
    )
    append = owner_certificate.validate_owner_evidence(
        _with_python_equal_path_conflict(
            evidence,
            record_kind,
            prepend=False,
        )
    )

    assert canonical_result(prepend) == canonical_result(append)
    for result in (prepend, append):
        assert result.certificate_nodes == ()
        assert result.role_resolutions == ()
        rejection = only(result.global_rejections)
        assert rejection.reason == "unregistered-support"
        assert rejection.role is None
        assert rejection.candidate_record_ids == (original.record_id, original.record_id)


def test_synthetic_future_complete_pair_reaches_only_gate_9():
    report = run_synthetic_future_complete_pair()

    assert any(item.relation_kind == "backend-owner-corresponds-to" for item in report.comparisons)
    assert any(item.relation_kind == "backend-owner-state-changed" for item in report.comparisons)
    verdict = only(report.verdicts)
    assert verdict.status is VerdictStatus.ABSTAIN
    assert verdict.failed_gates == ("gate-9-source-object-binding",)
    assert "source-object-binding-missing" in report.missing_evidence


def test_complete_path_builds_one_content_addressed_certificate():
    evidence = complete_evidence()
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
    assert certificate.record_id == stable_id(
        certificate.compile_id,
        certificate.kind,
        certificate.attributes["proof_content_sha256"],
    )


def test_trusted_result_retains_exact_certificate_cited_source_nodes():
    evidence = evidence_with_role_statuses()
    result = build_owner_certificates(evidence)
    resolution = result.resolution_for(first_role())
    certificate = result.certificate(resolution.certificate_record_ids[0])
    assert certificate is not None

    for attribute in ("pcode_record_id", "virtual_record_id", "allocator_record_id"):
        support_id = certificate.attributes[attribute]
        expected = next(node for node in evidence.nodes if node.record_id == support_id)
        assert result.certificate_support_node(certificate.record_id, support_id) is expected

    uncited = next(node for node in evidence.nodes if node.record_id not in certificate.provenance.input_record_ids)
    assert result.certificate_support_node(certificate.record_id, uncited.record_id) is None
    assert result.certificate_support_node("not-a-certificate", certificate.attributes["allocator_record_id"]) is None


def test_direct_certificate_result_construction_has_no_support_authority():
    trusted = build_owner_certificates(complete_evidence())
    certificate = trusted.certificate_nodes[0]
    support_id = certificate.attributes["allocator_record_id"]
    direct = OwnerCertificateResult(
        trusted.certificate_nodes,
        trusted.role_resolutions,
        trusted.global_rejections,
    )

    assert direct.is_trusted is False
    assert direct.certificate_support_node(certificate.record_id, support_id) is None


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
    first = build_owner_certificates(complete_evidence())
    second = build_owner_certificates(complete_evidence(object_result=_object_result(areas=("locals", "temps"))))

    assert first.certificate_nodes[0].record_id != second.certificate_nodes[0].record_id


def test_runtime_pointer_changes_do_not_change_certificate_id():
    first = build_owner_certificates(complete_evidence())
    second = build_owner_certificates(
        complete_evidence(
            object_result=_object_result(
                runtime_address=0xDEADBEEF,
                snapshot_runtime_address=0xDEAD0000,
                ignode_runtime_address=0xDEAD1000,
                list_node_runtime_address=0xBEEF0000,
            )
        )
    )

    assert first.certificate_nodes[0].record_id == second.certificate_nodes[0].record_id


def test_direct_diagnostic_evidence_construction_cannot_build_proof():
    evidence = complete_evidence()
    forged = ObjectBindingEvidence(
        evidence.nodes,
        evidence.edges,
        evidence.capabilities,
        evidence.capture_run_id,
        evidence.instrumentation_identity,
    )
    result = build_owner_certificates(forged)
    assert result.certificate_nodes == ()
    assert {item.reason for item in result.global_rejections} == {"untrusted-diagnostic-materialization"}


def test_direct_certificate_result_construction_is_not_trusted():
    forged = EvidenceNode(
        record_id="forged-owner-certificate",
        compile_id="compile-a",
        function="fn",
        kind="owner-proof-certificate",
        role_key="row-home",
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        confidence=Confidence.DERIVED_UNIQUE,
        provenance=Provenance(
            artifact_sha256="b" * 64,
            parser="causal-owner-certificate.v1",
            raw_start=None,
            raw_end=None,
            derivation_rule="forged",
        ),
        attributes={},
    )
    result = OwnerCertificateResult((forged,), (), ())

    assert result.is_trusted is False
    assert result.certificate(forged.record_id) is None


@pytest.mark.parametrize("store_factory", STORE_FACTORIES)
def test_certificate_round_trips_through_store_as_ordinary_evidence_node(
    store_factory,
    tmp_path,
    monkeypatch,
):
    backend = future_complete_backend(tmp_path, monkeypatch)
    store = store_factory()
    add_adapter_results_atomically(store, (backend.result,))
    certificate = backend.owner_certificates.certificate_nodes[0]

    reloaded = store.get_node(certificate.record_id)
    assert reloaded == certificate
    rebuilt = build_owner_certificates(backend.object_bindings)
    assert rebuilt.certificate(certificate.record_id) == reloaded
    forged_result = OwnerCertificateResult((reloaded,), (), ())
    assert forged_result.is_trusted is False
    assert forged_result.certificate(certificate.record_id) is None
    support_id = certificate.attributes["allocator_record_id"]
    expected_support = next(node for node in backend.object_bindings.nodes if node.record_id == support_id)
    assert rebuilt.certificate_support_node(certificate.record_id, support_id) == expected_support
    assert forged_result.certificate_support_node(certificate.record_id, support_id) is None


def test_certificate_result_subclass_cannot_override_trust():
    certificate = build_owner_certificates(complete_evidence()).certificate_nodes[0]

    try:

        class ForgedResult(OwnerCertificateResult):
            @property
            def is_trusted(self) -> bool:
                return True
    except TypeError as error:
        assert str(error) == "OwnerCertificateResult is runtime-final"
        return

    forged = ForgedResult((certificate,), (), ())
    assert forged.is_trusted is False
    assert forged.certificate(certificate.record_id) is None


def test_object_binding_evidence_subclass_cannot_replay_adapter_trust():
    trusted = complete_evidence()
    trusted_token = trusted._adapter_token

    try:

        class ForgedEvidence(ObjectBindingEvidence):
            def __getattribute__(self, name):
                if name == "_adapter_token":
                    return trusted_token
                return super().__getattribute__(name)
    except TypeError as error:
        assert str(error) == "ObjectBindingEvidence is runtime-final"
        return

    forged = ForgedEvidence(
        (),
        (),
        frozenset(),
        "forged-capture",
        None,
        ("forged-a", "forged-b", "forged-c", "forged-d"),
    )
    result = build_owner_certificates(forged)
    assert {item.reason for item in result.global_rejections} == {"untrusted-diagnostic-materialization"}


def test_replaced_certificate_results_lose_trust():
    trusted = build_owner_certificates(complete_evidence())
    certificate = trusted.certificate_nodes[0]
    forged = replace(certificate, record_id="forged-owner-certificate")

    for cloned in (
        replace(trusted),
        replace(trusted, certificate_nodes=(forged,)),
    ):
        assert cloned.is_trusted is False
        assert cloned.certificate(certificate.record_id) is None
        assert cloned.certificate(forged.record_id) is None
        support_id = certificate.attributes["allocator_record_id"]
        assert cloned.certificate_support_node(certificate.record_id, support_id) is None


def test_replaced_object_binding_evidence_loses_adapter_trust():
    trusted = complete_evidence()
    forged_identity = ("forged-a", "forged-b", "forged-c", "forged-d")

    for cloned in (
        replace(trusted),
        replace(
            trusted,
            nodes=(),
            edges=(),
            capabilities=frozenset(),
            capture_run_id="forged-capture",
            instrumentation_identity=forged_identity,
        ),
    ):
        result = build_owner_certificates(cloned)
        assert result.certificate_nodes == ()
        assert {item.reason for item in result.global_rejections} == {"untrusted-diagnostic-materialization"}


@pytest.mark.parametrize(
    "identity",
    [
        pytest.param((), id="empty-tuple"),
        pytest.param(("one",), id="one-member"),
        pytest.param(("one", "two", "", "four"), id="empty-member"),
        pytest.param(("one", "two", 3, "four"), id="non-string-member"),
        pytest.param(("one", "two", object(), "four"), id="unsupported-canonical-value"),
        pytest.param(("a", "b", "c", "d"), id="arbitrary-four-strings"),
        pytest.param(
            ("A" * 64, "proof-test", "2" * 64, "mwcc-retro-lifetime-proof.v1"),
            id="uppercase-compiler-digest",
        ),
        pytest.param(
            ("1" * 64, "proof-test", "short", "mwcc-retro-lifetime-proof.v1"),
            id="short-proof-digest",
        ),
        pytest.param(
            ("1" * 64, "proof-test", "2" * 64, "mwcc-retro-lifetime-proof.v2"),
            id="wrong-proof-schema",
        ),
    ],
)
def test_invalid_instrumentation_identity_is_controlled_rejection(identity):
    evidence = complete_evidence(instrumentation_identity=identity)

    try:
        result = build_owner_certificates(evidence)
    except Exception as error:  # pragma: no cover - the assertion reports the escaped error
        pytest.fail(f"invalid instrumentation identity escaped as {type(error).__name__}: {error}")

    assert result.certificate_nodes == ()
    assert {item.reason for item in result.global_rejections} == {"missing-instrumentation-identity"}


@pytest.mark.parametrize("unsupported", [object(), float("nan"), float("inf")])
def test_unsupported_semantic_proof_content_is_controlled_rejection(unsupported):
    evidence = complete_evidence(object_result=_object_result(areas=(unsupported,)))

    try:
        result = build_owner_certificates(evidence)
    except Exception as error:  # pragma: no cover - the assertion reports the escaped error
        pytest.fail(f"unsupported proof content escaped as {type(error).__name__}: {error}")

    assert result.certificate_nodes == ()
    assert {item.reason for item in result.global_rejections} == {"malformed-support"}


def test_independent_complete_results_have_equal_canonical_content():
    first = build_owner_certificates(complete_evidence())
    second = build_owner_certificates(complete_evidence())

    assert first is not second
    assert first.certificate_nodes[0] is not second.certificate_nodes[0]
    assert canonical_result(first) == canonical_result(second)


def test_split_physical_assignment_never_certifies():
    result = build_owner_certificates(evidence_with_split_physical_assignment())
    resolution = result.resolution_for(ROLE)

    assert resolution.status is OwnerResolutionStatus.CONTRADICTORY
    assert resolution.certificate_record_ids == ()
    assert {item.reason for item in resolution.rejections} == {"split-physical-assignment"}


def test_coordinated_allocator_changes_cannot_override_decoded_emission():
    result = build_owner_certificates(evidence_with_coordinated_allocator_change())
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


def test_multi_parent_lineage_is_stable_under_raw_container_reversal():
    evidence = evidence_with_two_mutation_outputs(
        first_parents=("ol-a",),
        second_parents=("ol-b", "ol-c"),
    )
    variants = tuple(
        ObjectBindingEvidence(
            tuple(reversed(evidence.nodes)) if reverse_nodes else evidence.nodes,
            tuple(reversed(evidence.edges)) if reverse_edges else evidence.edges,
            evidence.capabilities,
            evidence.capture_run_id,
            evidence.instrumentation_identity,
        )
        for reverse_nodes, reverse_edges in ((False, False), (True, False), (False, True), (True, True))
    )
    results = tuple(owner_certificate.validate_owner_evidence(variant) for variant in variants)

    assert len({canonical_result(result) for result in results}) == 1
    expected_certificate_ids = None
    for result in results:
        resolutions = tuple(
            next(resolution for resolution in result.role_resolutions if resolution.role == role)
            for role in (first_role(), second_role())
        )
        assert all(resolution.status is OwnerResolutionStatus.UNIQUE for resolution in resolutions)
        certificate_ids = tuple(only(resolution.certificate_record_ids) for resolution in resolutions)
        if expected_certificate_ids is None:
            expected_certificate_ids = certificate_ids
        assert certificate_ids == expected_certificate_ids

    index = owner_certificate._index_evidence(evidence)
    second_candidate = only(
        candidate
        for candidate in owner_certificate._enumerate_candidates(index)
        if owner_certificate._role_for(candidate) == second_role()
    )
    parent_edges = tuple(
        edge
        for edge in index.edges_by_kind_target[("pcode-operand-lineage", second_candidate.lineage.record_id)]
        if edge.attributes.get("lineage_event_side") == "outputs"
    )
    parent_nodes = tuple(index.node_by_id[edge.source_id] for edge in parent_edges)
    assert tuple(sorted(node.attributes["operand_lineage_id"] for node in parent_nodes)) == ("ol-b", "ol-c")
    assert tuple(node.record_id for node in parent_nodes) == tuple(edge.source_id for edge in parent_edges)


@pytest.mark.parametrize(
    "parent_kind",
    ("pcode-operand", "compiler-object", "allocator-node", "stack-object"),
)
def test_lineage_parent_requires_pcode_operand_kind(parent_kind):
    evidence = complete_evidence()
    index = owner_certificate._index_evidence(evidence)
    candidate = only(
        item for item in owner_certificate._enumerate_candidates(index) if owner_certificate._role_for(item) == ROLE
    )
    parent_edge = only(
        edge
        for edge in index.edges_by_kind_target[("pcode-operand-lineage", candidate.lineage.record_id)]
        if edge.attributes.get("lineage_event_side") == "outputs"
    )
    parent = index.node_by_id[parent_edge.source_id]
    assert parent.kind == "pcode-operand"

    diagnostic = owner_certificate.validate_owner_evidence(replace_record(evidence, replace(parent, kind=parent_kind)))
    resolution = next(item for item in diagnostic.role_resolutions if item.role == ROLE)

    if parent_kind == "pcode-operand":
        assert resolution.status is OwnerResolutionStatus.UNIQUE
        assert len(resolution.certificate_record_ids) == 1
    else:
        assert resolution.status is not OwnerResolutionStatus.UNIQUE
        assert resolution.certificate_record_ids == ()
        assert {item.reason for item in resolution.rejections} == {"lineage-parent-mismatch"}


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
    diagnostic = owner_certificate.validate_owner_evidence(evidence)
    resolution = next(item for item in diagnostic.role_resolutions if item.role == ROLE)

    assert resolution.status is not OwnerResolutionStatus.UNIQUE
    expected = "malformed-support" if parents in {(), ("ol-a", "ol-a")} else "lineage-parent-mismatch"
    assert {item.reason for item in resolution.rejections} == {expected}


@pytest.mark.parametrize(
    ("variant", "reason"),
    [
        ("event-index", "lineage-parent-mismatch"),
        ("side", "lineage-parent-mismatch"),
        ("mutation-kind", "lineage-parent-mismatch"),
        ("noncanonical-parent-order", "malformed-support"),
    ],
)
def test_lineage_event_variants_fail_closed(variant, reason):
    diagnostic = owner_certificate.validate_owner_evidence(evidence_with_lineage_variant(variant))
    resolution = next(item for item in diagnostic.role_resolutions if item.role == ROLE)

    assert resolution.status is not OwnerResolutionStatus.UNIQUE
    assert {item.reason for item in resolution.rejections} == {reason}


def test_heuristic_support_is_incomplete_and_never_certifies():
    result = build_owner_certificates(evidence_with_heuristic_support())
    resolution = result.resolution_for(ROLE)

    assert resolution.status is OwnerResolutionStatus.INCOMPLETE
    assert resolution.certificate_record_ids == ()
    assert {item.reason for item in resolution.rejections} == {"malformed-support"}


def test_roleless_candidate_rejection_is_global_and_visible():
    result = build_owner_certificates(evidence_with_zero_sized_owner())

    assert result.is_trusted
    assert result.certificate_nodes == ()
    assert result.role_resolutions == ()
    rejection = only(result.global_rejections)
    assert rejection.reason == "malformed-support"
    assert rejection.role is None
    assert rejection.candidate_record_ids
    assert result.resolution_for(ROLE).status is OwnerResolutionStatus.INCOMPLETE


def test_roleless_candidate_rejection_taints_an_otherwise_valid_role():
    result = build_owner_certificates(evidence_with_zero_sized_owner(include_valid=True))
    resolution = result.resolution_for(ROLE)

    assert {item.reason for item in result.global_rejections} == {"malformed-support"}
    assert resolution.status is OwnerResolutionStatus.INCOMPLETE
    assert len(resolution.certificate_record_ids) == 1
    assert result.certificate_nodes == ()
    assert result.certificate(resolution.certificate_record_ids[0]) is None


def test_allocator_origin_conflict_is_contradictory():
    result = build_owner_certificates(evidence_with_allocator_origin_conflict())
    resolution = result.resolution_for(ROLE)

    assert resolution.status is OwnerResolutionStatus.CONTRADICTORY
    assert {item.reason for item in resolution.rejections} == {"allocator-origin-contradiction"}


def test_object_allocation_generation_must_match_stage_snapshots():
    result = build_owner_certificates(evidence_with_object_generation_conflict())
    resolution = result.resolution_for(ROLE)

    assert resolution.status is OwnerResolutionStatus.CONTRADICTORY
    assert {item.reason for item in resolution.rejections} == {"allocator-origin-contradiction"}


def test_frame_binding_must_belong_to_the_owners_declared_area():
    evidence = complete_evidence(object_result=_object_result(areas=("temps",)))
    resolution = build_owner_certificates(evidence).resolution_for(ROLE)

    assert resolution.status is OwnerResolutionStatus.CONTRADICTORY
    assert {item.reason for item in resolution.rejections} == {"frame-binding-contradiction"}


def test_disconnected_path_without_a_compatible_role_is_global_incomplete():
    result = build_owner_certificates(disconnected_evidence())

    assert result.certificate_nodes == ()
    assert {item.reason for item in result.global_rejections} == {"disconnected-owner-path"}
    assert result.resolution_for(ROLE).status is OwnerResolutionStatus.INCOMPLETE


def test_missing_required_capability_is_global_and_fail_closed():
    evidence = complete_evidence(capabilities=ALL_CAPABILITIES - {"object-to-frame"})
    result = build_owner_certificates(evidence)

    assert result.certificate_nodes == ()
    assert {item.reason for item in result.global_rejections} == {"missing-required-capability"}
    assert result.resolution_for(ROLE).status is OwnerResolutionStatus.INCOMPLETE


def test_diagnostic_missing_capability_preserves_fully_validated_candidate_id():
    evidence = complete_evidence()
    tokenless = replace(
        evidence,
        capabilities=evidence.capabilities - {"object-to-frame"},
    )

    diagnostic = owner_certificate.validate_owner_evidence(tokenless)
    resolution = next(item for item in diagnostic.role_resolutions if item.role == ROLE)

    assert {item.reason for item in diagnostic.global_rejections} == {"missing-required-capability"}
    assert resolution.status is OwnerResolutionStatus.INCOMPLETE
    assert len(resolution.certificate_record_ids) == 1
    assert diagnostic.certificate_nodes == ()
    assert diagnostic.certificate(resolution.certificate_record_ids[0]) is None


@pytest.mark.parametrize("scope_field", ["compile", "capture", "artifact", "parser"])
def test_diagnostic_validation_rejects_mixed_record_scope(scope_field):
    evidence = complete_evidence()
    emission = support(evidence, "pcode-emission")
    if scope_field == "compile":
        changed = replace(emission, compile_id="compile-other")
    elif scope_field == "capture":
        changed = emission.with_attributes({**emission.attributes, "capture_run_id": "c" * 64})
    elif scope_field == "artifact":
        changed = replace(
            emission,
            provenance=replace(emission.provenance, artifact_sha256="d" * 64),
        )
    else:
        changed = replace(
            emission,
            provenance=replace(emission.provenance, parser="mwcc-debug-pcdump"),
        )
    tokenless = replace_record(evidence, changed)

    diagnostic = owner_certificate.validate_owner_evidence(tokenless)
    trusted_attempt = build_owner_certificates(tokenless)

    assert {item.reason for item in diagnostic.global_rejections} == {"mixed-record-scope"}
    assert diagnostic.certificate_nodes == ()
    assert diagnostic.is_trusted is False
    assert trusted_attempt.certificate_nodes == ()
    assert {item.reason for item in trusted_attempt.global_rejections} == {"untrusted-diagnostic-materialization"}


def test_diagnostic_validation_rejects_unregistered_provenance_input():
    evidence = complete_evidence()
    anchor_edge = next(edge for edge in evidence.edges if edge.kind == "assembly-anchor-emitted-by-pcode")
    changed = replace(
        anchor_edge,
        provenance=replace(
            anchor_edge.provenance,
            input_record_ids=(*anchor_edge.provenance.input_record_ids, "unregistered"),
        ),
    )
    diagnostic = owner_certificate.validate_owner_evidence(replace_record(evidence, changed))
    resolution = next(item for item in diagnostic.role_resolutions if item.role == ROLE)

    assert resolution.status is OwnerResolutionStatus.INCOMPLETE
    assert {item.reason for item in resolution.rejections} == {"unregistered-support"}
    assert diagnostic.certificate_nodes == ()


def test_diagnostic_validation_requires_each_edges_endpoint_provenance():
    evidence = complete_evidence()
    edge = next(item for item in evidence.edges if item.kind == "pcode-operand-uses-virtual")
    changed = replace(
        edge,
        provenance=replace(
            edge.provenance,
            input_record_ids=tuple(item for item in edge.provenance.input_record_ids if item != edge.target_id),
        ),
    )
    diagnostic = owner_certificate.validate_owner_evidence(replace_record(evidence, changed))
    resolution = next(item for item in diagnostic.role_resolutions if item.role == ROLE)

    assert resolution.status is OwnerResolutionStatus.INCOMPLETE
    assert {item.reason for item in resolution.rejections} == {"unregistered-support"}


def test_diagnostic_validation_requires_shared_emission_support():
    evidence = complete_evidence()
    emission = support(evidence, "pcode-emission")
    edge = next(
        item
        for item in evidence.edges
        if item.kind == "pcode-operand-lineage"
        and item.source_id == next(node.record_id for node in evidence.nodes if node.kind == "retail-pcode")
    )
    changed = replace(
        edge,
        provenance=replace(
            edge.provenance,
            input_record_ids=tuple(item for item in edge.provenance.input_record_ids if item != emission.record_id),
        ),
    )
    diagnostic = owner_certificate.validate_owner_evidence(replace_record(evidence, changed))
    resolution = next(item for item in diagnostic.role_resolutions if item.role == ROLE)

    assert resolution.status is OwnerResolutionStatus.INCOMPLETE
    assert {item.reason for item in resolution.rejections} == {"malformed-support"}


def test_diagnostic_validation_rejects_unknown_support_attribute():
    evidence = complete_evidence()
    emission = support(evidence, "pcode-emission")
    changed = emission.with_attributes({**emission.attributes, "unknown": True})
    diagnostic = owner_certificate.validate_owner_evidence(replace_record(evidence, changed))
    resolution = next(item for item in diagnostic.role_resolutions if item.role == ROLE)

    assert resolution.status is OwnerResolutionStatus.INCOMPLETE
    assert {item.reason for item in resolution.rejections} == {"malformed-support"}
    assert diagnostic.certificate_nodes == ()


def test_diagnostic_validator_cannot_mint_complete_record_content():
    evidence = complete_evidence()
    tokenless = replace(evidence)

    diagnostic = owner_certificate.validate_owner_evidence(tokenless)

    assert diagnostic.certificate_nodes == ()
    assert diagnostic.is_trusted is False
    assert diagnostic.certificate("anything") is None
    assert diagnostic.resolution_for(ROLE).status is OwnerResolutionStatus.INCOMPLETE
    assert (
        next(item for item in diagnostic.role_resolutions if item.role == ROLE).status is OwnerResolutionStatus.UNIQUE
    )


def test_valid_certificate_plus_compatible_rejection_is_not_unique():
    result = build_owner_certificates(evidence_with_certificate_and_role_rejection(ROLE))
    resolution = result.resolution_for(ROLE)

    assert resolution.status is OwnerResolutionStatus.AMBIGUOUS
    assert len(resolution.certificate_record_ids) == 1
    assert {item.reason for item in resolution.rejections} == {"plausible-owner-alternative"}


def test_global_rejection_taints_every_lookup_as_incomplete():
    result = build_owner_certificates(evidence_without_instrumentation_identity())
    resolution = result.resolution_for(ROLE)

    assert result.global_rejections
    assert all(rejection.role is None for rejection in result.global_rejections)
    assert resolution.status is OwnerResolutionStatus.INCOMPLETE
    assert len(resolution.certificate_record_ids) == 1
    assert result.certificate_nodes == ()
    assert result.certificate(resolution.certificate_record_ids[0]) is None
    assert result.resolution_for(other_role()).status is OwnerResolutionStatus.INCOMPLETE
    assert resolution.rejections == ()


def test_global_rejection_preserves_role_scoped_rejections():
    result = build_owner_certificates(evidence_with_global_and_role_rejection())
    resolution = result.resolution_for(ROLE)

    assert {item.reason for item in result.global_rejections} == {"missing-instrumentation-identity"}
    assert resolution.status is OwnerResolutionStatus.INCOMPLETE
    assert {item.reason for item in resolution.rejections} == {"malformed-support"}


def test_global_rejection_preserves_valid_certificate_ids():
    result = build_owner_certificates(evidence_with_certificate_and_global_rejection())
    resolution = result.resolution_for(ROLE)

    assert {item.reason for item in result.global_rejections} == {"disconnected-owner-path"}
    assert resolution.status is OwnerResolutionStatus.INCOMPLETE
    assert len(resolution.certificate_record_ids) == 1
    assert result.certificate(resolution.certificate_record_ids[0]) is not None


def test_repeated_lookup_does_not_change_resolution():
    result = build_owner_certificates(complete_evidence())

    assert result.resolution_for(ROLE) == result.resolution_for(ROLE)


def test_input_permutation_is_byte_stable():
    evidence = evidence_with_two_mutation_outputs(
        first_parents=("ol-a",),
        second_parents=("ol-b", "ol-c"),
    )
    permuted_evidence = evidence_with_two_mutation_outputs(
        first_parents=("ol-a",),
        second_parents=("ol-b", "ol-c"),
        permuted=True,
    )

    assert canonical_result(build_owner_certificates(evidence)) == canonical_result(
        build_owner_certificates(permuted_evidence)
    )


def test_semantic_duplicate_alternatives_retain_canonical_multiplicity():
    result = build_owner_certificates(ambiguous_evidence())
    resolution = result.resolution_for(ROLE)

    assert resolution.status is OwnerResolutionStatus.AMBIGUOUS
    assert resolution.certificate_record_ids == tuple(sorted(resolution.certificate_record_ids))
    groups = tuple(group for group in result._canonical_groups if group.role == ROLE)
    assert len(groups) == 2
    assert all(group.multiplicity == 1 for group in groups)
    assert all(len(group.provenance_record_ids) == 1 for group in groups)


def test_exact_duplicate_alternatives_retain_one_group_and_multiplicity():
    evidence = complete_evidence()
    duplicate_node = next(node for node in evidence.nodes if node.kind == "retail-pcode")
    duplicate = next(edge for edge in evidence.edges if edge.kind == "assembly-anchor-emitted-by-pcode")
    tokenless = ObjectBindingEvidence(
        (*evidence.nodes, duplicate_node),
        (*evidence.edges, duplicate),
        evidence.capabilities,
        evidence.capture_run_id,
        evidence.instrumentation_identity,
    )
    result = owner_certificate.validate_owner_evidence(tokenless)
    resolution = next(item for item in result.role_resolutions if item.role == ROLE)

    assert resolution.status is OwnerResolutionStatus.UNIQUE
    assert len(resolution.certificate_record_ids) == 1
    groups = tuple(group for group in result._canonical_groups if group.role == ROLE)
    assert len(groups) == 1
    assert groups[0].multiplicity == 2
    assert len(groups[0].provenance_record_ids) == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("capabilities", [], id="capabilities-list"),
        pytest.param("capabilities", {}, id="capabilities-mapping"),
        pytest.param("capture", [], id="capture-list"),
        pytest.param("capture", {}, id="capture-mapping"),
        pytest.param("compile", [], id="compile-list"),
        pytest.param("function", {}, id="function-mapping"),
        pytest.param("artifact", [], id="artifact-list"),
        pytest.param("parser", {}, id="parser-mapping"),
        pytest.param("physical", [], id="physical-list"),
        pytest.param("physical", {}, id="physical-mapping"),
        pytest.param("lineage-parents", [["ol-a"]], id="lineage-parent-list"),
        pytest.param(
            "lineage-parents",
            {"parent": "ol-a"},
            id="lineage-parent-mapping",
        ),
        pytest.param("nested", {"malformed": []}, id="nested-list"),
        pytest.param("nested", {"malformed": {}}, id="nested-mapping"),
        pytest.param("nested", float("nan"), id="nested-nonfinite"),
        pytest.param("nested", object(), id="nested-unsupported"),
    ],
)
def test_diagnostic_validation_closes_malformed_persistence_values(field, value):
    evidence = complete_evidence()
    if field == "capabilities":
        malformed = replace(evidence, capabilities=value)
    elif field == "capture":
        malformed = replace(evidence, capture_run_id=value)
    elif field in {"compile", "function", "artifact", "parser"}:
        emission = support(evidence, "pcode-emission")
        if field == "compile":
            changed = replace(emission, compile_id=value)
        elif field == "function":
            changed = replace(emission, function=value)
        elif field == "artifact":
            changed = replace(
                emission,
                provenance=replace(emission.provenance, artifact_sha256=value),
            )
        else:
            changed = replace(
                emission,
                provenance=replace(emission.provenance, parser=value),
            )
        malformed = replace_record(evidence, changed)
    elif field == "physical":
        anchor = next(node for node in evidence.nodes if node.kind == "assembly-operand-anchor")
        malformed = replace_record(
            evidence,
            anchor.with_attributes({**anchor.attributes, "physical_register": value}),
        )
    elif field == "lineage-parents":
        lineage = next(
            node
            for node in evidence.nodes
            if node.kind == "backend-support-record"
            and node.attributes.get("support_kind") == "pcode-lineage-event"
            and "event_index" in node.attributes
        )
        malformed = replace_record(
            evidence,
            lineage.with_attributes({**lineage.attributes, "parent_lineage_ids": value}),
        )
    else:
        emission = support(evidence, "pcode-emission")
        malformed = replace_record(
            evidence,
            emission.with_attributes({**emission.attributes, "nested": value}),
        )

    try:
        diagnostic = owner_certificate.validate_owner_evidence(malformed)
    except Exception as error:  # pragma: no cover - assertion reports escaped input
        pytest.fail(f"malformed {field} escaped as {type(error).__name__}: {error}")

    reasons = {
        rejection.reason
        for rejection in (
            *diagnostic.global_rejections,
            *(rejection for resolution in diagnostic.role_resolutions for rejection in resolution.rejections),
        )
    }
    assert reasons == {"malformed-support"}
    assert diagnostic.certificate_nodes == ()
    assert diagnostic.is_trusted is False


def test_diagnostic_boundary_maps_malformed_record_container_to_rejection():
    evidence = complete_evidence()
    malformed = replace(evidence, nodes={"unexpected": evidence.nodes[0]})

    diagnostic = owner_certificate.validate_owner_evidence(malformed)

    assert {item.reason for item in diagnostic.global_rejections} == {"malformed-support"}
    assert diagnostic.certificate_nodes == ()
    assert diagnostic.is_trusted is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("node-record-id", "", id="node-record-id-empty"),
        pytest.param("node-record-id", [], id="node-record-id-list"),
        pytest.param("node-record-id", {}, id="node-record-id-mapping"),
        pytest.param("node-compile-id", "", id="node-compile-id-empty"),
        pytest.param("node-compile-id", [], id="node-compile-id-list"),
        pytest.param("node-function", {}, id="node-function-mapping"),
        pytest.param("node-kind", "", id="node-kind-empty"),
        pytest.param("node-kind", [], id="node-kind-list"),
        pytest.param("node-role", [], id="node-role-list"),
        pytest.param("node-role", {}, id="node-role-mapping"),
        pytest.param("edge-record-id", [], id="edge-record-id-list"),
        pytest.param("edge-source-id", "", id="edge-source-id-empty"),
        pytest.param("edge-source-id", [], id="edge-source-id-list"),
        pytest.param("edge-target-id", {}, id="edge-target-id-mapping"),
        pytest.param("producer-confidence", "observed", id="producer-confidence"),
        pytest.param("adapter-confidence", "observed", id="adapter-confidence"),
        pytest.param("confidence", "observed", id="combined-confidence"),
        pytest.param("provenance", {}, id="provenance-object"),
        pytest.param("artifact", "not-a-sha256", id="artifact-digest"),
        pytest.param("artifact", [], id="artifact-list"),
        pytest.param("parser", "", id="parser-empty"),
        pytest.param("parser", {}, id="parser-mapping"),
        pytest.param("derivation", "", id="derivation-empty"),
        pytest.param("derivation", [], id="derivation-list"),
        pytest.param("raw-start", True, id="raw-start-bool"),
        pytest.param("raw-start", -1, id="raw-start-negative"),
        pytest.param("raw-end", {}, id="raw-end-mapping"),
        pytest.param("raw-range", (10, 5), id="raw-range-reversed"),
        pytest.param(
            "input-record-ids",
            (["unhashable"],),
            id="input-record-id-list",
        ),
        pytest.param(
            "input-record-ids",
            ("valid", 3),
            id="input-record-id-non-string",
        ),
        pytest.param("nodes", [], id="nodes-list"),
        pytest.param("edges", {}, id="edges-mapping"),
        pytest.param("capabilities", ["object-to-frame"], id="capabilities-list"),
        pytest.param("capabilities", frozenset({3}), id="capability-non-string"),
        pytest.param("capture-run-id", "", id="capture-run-id-empty"),
        pytest.param("capture-run-id", [], id="capture-run-id-list"),
        pytest.param("instrumentation-identity", [], id="identity-list"),
        pytest.param("instrumentation-identity", {}, id="identity-mapping"),
    ],
)
def test_diagnostic_boundary_rejects_malformed_structural_fields(field, value):
    evidence = complete_evidence()
    node = support(evidence, "pcode-emission")
    edge = next(item for item in evidence.edges if item.kind == "assembly-anchor-emitted-by-pcode")

    if field == "nodes":
        malformed = replace(evidence, nodes=value)
    elif field == "edges":
        malformed = replace(evidence, edges=value)
    elif field == "capabilities":
        malformed = replace(evidence, capabilities=value)
    elif field == "capture-run-id":
        malformed = replace(evidence, capture_run_id=value)
    elif field == "instrumentation-identity":
        malformed = replace(evidence, instrumentation_identity=value)
    elif field.startswith("edge-"):
        edge_field = {
            "edge-record-id": "record_id",
            "edge-source-id": "source_id",
            "edge-target-id": "target_id",
        }[field]
        changed_edge = replace(edge, **{edge_field: value})
        edge_index = evidence.edges.index(edge)
        malformed = replace(
            evidence,
            edges=tuple(changed_edge if index == edge_index else item for index, item in enumerate(evidence.edges)),
        )
    else:
        if field == "node-record-id":
            changed_node = replace(node, record_id=value)
        elif field == "node-compile-id":
            changed_node = replace(node, compile_id=value)
        elif field == "node-function":
            changed_node = replace(node, function=value)
        elif field == "node-kind":
            changed_node = replace(node, kind=value)
        elif field == "node-role":
            changed_node = replace(node, role_key=value)
        elif field in {
            "producer-confidence",
            "adapter-confidence",
            "confidence",
        }:
            changed_node = replace(node, **{field.replace("-", "_"): value})
        elif field == "provenance":
            changed_node = replace(node, provenance=value)
        else:
            provenance_field = {
                "artifact": "artifact_sha256",
                "parser": "parser",
                "derivation": "derivation_rule",
                "raw-start": "raw_start",
                "raw-end": "raw_end",
                "input-record-ids": "input_record_ids",
            }.get(field)
            if field == "raw-range":
                changed_provenance = replace(
                    node.provenance,
                    raw_start=value[0],
                    raw_end=value[1],
                )
            else:
                changed_provenance = replace(
                    node.provenance,
                    **{provenance_field: value},
                )
            changed_node = replace(node, provenance=changed_provenance)
        node_index = evidence.nodes.index(node)
        malformed = replace(
            evidence,
            nodes=tuple(changed_node if index == node_index else item for index, item in enumerate(evidence.nodes)),
        )

    diagnostic = owner_certificate.validate_owner_evidence(malformed)

    assert {item.reason for item in diagnostic.global_rejections} == {"malformed-support"}
    assert diagnostic.role_resolutions == ()
    assert diagnostic.resolution_for(ROLE).certificate_record_ids == ()
    assert diagnostic.certificate_nodes == ()
    assert diagnostic.is_trusted is False


def test_diagnostic_boundary_does_not_swallow_unknown_taxonomy(monkeypatch):
    def reject_with_unknown_taxonomy(_evidence):
        return owner_certificate._rejection("future-unknown-reason")

    monkeypatch.setattr(
        owner_certificate,
        "_validate_core",
        reject_with_unknown_taxonomy,
    )

    with pytest.raises(ValueError, match="unknown owner certificate rejection"):
        owner_certificate.validate_owner_evidence(complete_evidence())


def test_diagnostic_boundary_does_not_swallow_canonical_group_invariant(
    monkeypatch,
):
    def missing_group(_outcome):
        raise KeyError("missing canonical group")

    monkeypatch.setattr(owner_certificate, "_canonical_groups", missing_group)

    with pytest.raises(KeyError, match="missing canonical group"):
        owner_certificate.validate_owner_evidence(complete_evidence())


def test_five_role_statuses_are_resolved_independently():
    result = build_owner_certificates(evidence_with_role_statuses())
    ambiguous_role = OwnerRoleKey("use:1", "gpr", "ambiguous-home", 4, "locals")
    contradictory_role = OwnerRoleKey("use:2", "gpr", "contradictory-home", 4, "locals")
    incomplete_role = OwnerRoleKey("use:3", "gpr", "incomplete-home", 4, "locals")

    assert result.resolution_for(first_role()).status is OwnerResolutionStatus.UNIQUE
    assert result.resolution_for(other_role()).status is OwnerResolutionStatus.MISSING
    assert result.resolution_for(ambiguous_role).status is OwnerResolutionStatus.AMBIGUOUS
    assert result.resolution_for(contradictory_role).status is OwnerResolutionStatus.CONTRADICTORY
    assert result.resolution_for(incomplete_role).status is OwnerResolutionStatus.INCOMPLETE


def test_rejection_ids_change_with_cited_record_content_not_only_record_ids():
    first = owner_certificate.validate_owner_evidence(
        replace_record(
            complete_evidence(),
            support(complete_evidence(), "pcode-emission").with_attributes(
                {
                    **support(complete_evidence(), "pcode-emission").attributes,
                    "unknown": "first",
                }
            ),
        )
    )
    base = complete_evidence()
    emission = support(base, "pcode-emission")
    second = owner_certificate.validate_owner_evidence(
        replace_record(
            base,
            emission.with_attributes({**emission.attributes, "unknown": "second"}),
        )
    )

    first_rejection = next(item for item in first.role_resolutions if item.role == ROLE).rejections[0]
    second_rejection = next(item for item in second.role_resolutions if item.role == ROLE).rejections[0]
    assert first_rejection.candidate_record_ids == second_rejection.candidate_record_ids
    assert first_rejection.rejection_id != second_rejection.rejection_id
