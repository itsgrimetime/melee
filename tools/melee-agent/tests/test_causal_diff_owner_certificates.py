from dataclasses import replace

import pytest

from src.mwcc_debug.causal_diff.canonical import stable_id
from src.mwcc_debug.causal_diff.models import Confidence, EvidenceNode, Provenance
from src.mwcc_debug.causal_diff.object_binding_adapter import (
    ObjectBindingEvidence,
    emit_object_binding_evidence,
)
from src.mwcc_debug.causal_diff.owner_certificate import (
    OwnerCertificateResult,
    OwnerResolutionStatus,
    OwnerRoleKey,
    OwnerSemanticState,
    build_owner_certificates,
)
from tests.owner_certificate_fixtures import canonical_result, complete_evidence
from tests.test_causal_diff_object_bindings import _adapter_input, _object_result

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
    assert certificate.record_id == stable_id(
        certificate.compile_id,
        certificate.kind,
        certificate.attributes["proof_content_sha256"],
    )


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
    second = build_owner_certificates(
        complete_evidence(object_result=_object_result(areas=("locals", "temps")))
    )

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
        evidence.abstention_reason,
        evidence.instrumentation_identity,
    )
    result = build_owner_certificates(forged)
    assert result.certificate_nodes == ()
    assert {item.reason for item in result.global_rejections} == {
        "untrusted-diagnostic-materialization"
    }


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
    assert {item.reason for item in result.global_rejections} == {
        "untrusted-diagnostic-materialization"
    }


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
        assert {item.reason for item in result.global_rejections} == {
            "untrusted-diagnostic-materialization"
        }


@pytest.mark.parametrize(
    "identity",
    [
        pytest.param((), id="empty-tuple"),
        pytest.param(("one",), id="one-member"),
        pytest.param(("one", "two", "", "four"), id="empty-member"),
        pytest.param(("one", "two", 3, "four"), id="non-string-member"),
        pytest.param(("one", "two", object(), "four"), id="unsupported-canonical-value"),
    ],
)
def test_invalid_instrumentation_identity_is_controlled_rejection(identity):
    evidence = complete_evidence(instrumentation_identity=identity)

    try:
        result = build_owner_certificates(evidence)
    except Exception as error:  # pragma: no cover - the assertion reports the escaped error
        pytest.fail(f"invalid instrumentation identity escaped as {type(error).__name__}: {error}")

    assert result.certificate_nodes == ()
    assert {item.reason for item in result.global_rejections} == {
        "invalid-instrumentation-identity"
    }


def test_unsupported_semantic_proof_content_is_controlled_rejection():
    evidence = complete_evidence(object_result=_object_result(areas=(object(),)))

    try:
        result = build_owner_certificates(evidence)
    except Exception as error:  # pragma: no cover - the assertion reports the escaped error
        pytest.fail(f"unsupported proof content escaped as {type(error).__name__}: {error}")

    assert result.certificate_nodes == ()
    assert {item.reason for item in result.global_rejections} == {
        "unsupported-certificate-canonicalization"
    }


def test_independent_complete_results_have_equal_canonical_content():
    first = build_owner_certificates(complete_evidence())
    second = build_owner_certificates(complete_evidence())

    assert first is not second
    assert first.certificate_nodes[0] is not second.certificate_nodes[0]
    assert canonical_result(first) == canonical_result(second)
