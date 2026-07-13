from dataclasses import replace

import pytest

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
from tests.test_causal_diff_object_bindings import _adapter_input

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


def test_trusted_result_has_stable_json_canonicalization():
    result = build_owner_certificates(complete_evidence())

    assert canonical_result(result) == canonical_result(result)
