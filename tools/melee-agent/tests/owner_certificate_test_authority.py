"""Test-only authority for synthetic owner-certificate evidence."""

from src.mwcc_debug.causal_diff import object_binding_adapter
from src.mwcc_debug.causal_diff.object_binding_adapter import (
    ObjectBindingAdapterInput,
    ObjectBindingEvidence,
    emit_object_binding_evidence,
)


def emit_trusted_object_binding_evidence_for_test(
    source: ObjectBindingAdapterInput,
) -> ObjectBindingEvidence:
    evidence = emit_object_binding_evidence(source)
    if type(evidence) is not ObjectBindingEvidence or evidence._adapter_token is not None:
        raise AssertionError("test authority requires fresh tokenless diagnostic evidence")
    object.__setattr__(
        evidence,
        "_adapter_token",
        object_binding_adapter._OBJECT_BINDING_ADAPTER_TOKEN,
    )
    return evidence
