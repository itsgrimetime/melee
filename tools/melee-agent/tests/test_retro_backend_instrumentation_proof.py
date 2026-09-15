import copy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro.backend_instrumentation_proof import (  # noqa: E402
    InstrumentationProof,
    proof_sha256,
    trusted_proof_from_trace,
    validate_embedded_proof,
    validate_proof_shape,
)


def minimal_instrumentation_proof() -> dict[str, object]:
    return {
        "schema_version": "mwcc-retro-lifetime-proof.v1",
        "proof_id": "gc-1.2.5n-backend-entity-allocation-trace.v1",
        "compiler_executable_sha256": "a" * 64,
        "mode": "allocation-generation",
        "allocation_sites": [
            {
                "site_id": "objobject-alloc-1",
                "address": 0x500000,
                "entity_kind": "objobject",
                "compiler_stage": "frontend",
            },
            {
                "site_id": "pcode-alloc-1",
                "address": 0x500100,
                "entity_kind": "pcode",
                "compiler_stage": "backend-lowering",
            },
        ],
        "free_sites": [
            {
                "site_id": "pcode-free-1",
                "address": 0x500200,
                "entity_kind": "pcode",
                "compiler_stage": "backend-finalize",
            }
        ],
        "operand_rewrite_sites": [
            {
                "site_id": "rewrite-register-operand-1",
                "address": 0x500300,
                "compiler_stage": "colorgraph",
            }
        ],
        "operand_mutation_sites": [
            {
                "site_id": "rewrite-pcode-operands-1",
                "address": 0x500400,
                "compiler_stage": "optimizer",
            }
        ],
        "code_emission_sites": [
            {
                "site_id": "emit-pcode-1",
                "address": 0x500500,
                "compiler_stage": "backend-finalize",
            }
        ],
        "operand_rules": [
            {
                "opcode_id": 42,
                "operand_index": 1,
                "raw_arg_kind_id": 7,
                "register_flags_mask": 3,
                "register_flags_value": 0,
                "role": "use",
                "class_id": 0,
                "allocation_requirement": "allocator-rewrite-required",
            }
        ],
        "opcode_table": [{"opcode_id": 42, "mnemonic": "ADDI"}],
        "initialization_address": 0x401000,
        "proof_basis": "exhaustive-static-callgraph-and-disassembly",
    }


def promoted_registry(
    proof: dict[str, object], compiler_sha256: str = "a" * 64
) -> dict[str, object]:
    return {
        "instrumentation_proof_schema": "mwcc-retro-lifetime-proof.v1",
        "instrumentation_proofs": [
            {
                "compiler_executable_sha256": compiler_sha256,
                "proof_id": proof["proof_id"],
                "proof_sha256": proof_sha256(proof),
                "promoted": True,
            }
        ],
    }


def test_minimal_proof_has_valid_shape_and_stable_canonical_digest():
    proof = minimal_instrumentation_proof()
    reordered = {key: proof[key] for key in reversed(proof)}

    assert validate_proof_shape(proof) == ()
    assert proof_sha256(proof) == proof_sha256(reordered)
    assert len(proof_sha256(proof)) == 64


def test_embedded_proof_requires_exact_promoted_registry_tuple():
    proof = minimal_instrumentation_proof()
    table = promoted_registry(proof)

    assert validate_embedded_proof(proof, table, "a" * 64) == ()
    assert validate_embedded_proof(proof, table, "b" * 64) == (
        "proof compiler digest does not match capture compiler digest",
        "instrumentation proof is not independently promoted for this compiler",
    )

    table["instrumentation_proofs"][0]["promoted"] = False
    assert validate_embedded_proof(proof, table, "a" * 64)[-1] == (
        "instrumentation proof is not independently promoted for this compiler"
    )


@pytest.mark.parametrize(
    ("mutate_table", "expected"),
    [
        (
            lambda table: table.pop("instrumentation_proof_schema"),
            "instrumentation_proof_schema must be mwcc-retro-lifetime-proof.v1",
        ),
        (
            lambda table: table.update(
                {"instrumentation_proof_schema": "mwcc-retro-lifetime-proof.v2"}
            ),
            "instrumentation_proof_schema must be mwcc-retro-lifetime-proof.v1",
        ),
        (
            lambda table: table["instrumentation_proofs"][0].update(
                {"unexpected": True}
            ),
            "instrumentation proof registry row 0 has unexpected fields",
        ),
        (
            lambda table: table["instrumentation_proofs"][0].update(
                {"compiler_executable_sha256": []}
            ),
            "instrumentation proof registry row 0 compiler_executable_sha256",
        ),
    ],
)
def test_embedded_proof_rejects_invalid_registry_before_trust(mutate_table, expected):
    proof = minimal_instrumentation_proof()
    table = promoted_registry(proof)
    mutate_table(table)

    errors = validate_embedded_proof(proof, table, "a" * 64)

    assert any(expected in error for error in errors)
    assert "instrumentation proof is not independently promoted for this compiler" in errors


@pytest.mark.parametrize(
    "hostile_value",
    [float("nan"), float("inf"), 1 << 100],
)
def test_embedded_proof_rejects_noncanonical_payload_without_raising(hostile_value):
    proof = minimal_instrumentation_proof()
    proof["initialization_address"] = hostile_value

    errors = validate_embedded_proof(proof, promoted_registry(minimal_instrumentation_proof()), "a" * 64)

    assert "instrumentation proof is not RFC 8785 canonicalizable" in errors
    assert "instrumentation proof is not independently promoted for this compiler" in errors


def test_embedded_proof_rejects_recursive_payload_without_raising():
    proof = minimal_instrumentation_proof()
    recursive: list[object] = []
    recursive.append(recursive)
    proof["operand_rules"] = recursive

    errors = validate_embedded_proof(
        proof, promoted_registry(minimal_instrumentation_proof()), "a" * 64
    )

    assert "instrumentation proof is not RFC 8785 canonicalizable" in errors
    assert "instrumentation proof is not independently promoted for this compiler" in errors


def test_embedded_proof_rejects_wrong_type_payload_and_registry_without_raising():
    errors = validate_embedded_proof([], [], "a" * 64)

    assert errors == (
        "instrumentation proof must be object",
        "instrumentation proof registry must be object",
        "instrumentation proof is not independently promoted for this compiler",
    )


def test_proof_rejects_duplicate_sites_and_unsorted_rules():
    proof = minimal_instrumentation_proof()
    proof["allocation_sites"] *= 2
    assert "duplicate allocation site" in "\n".join(validate_proof_shape(proof))

    proof = minimal_instrumentation_proof()
    second_rule = copy.deepcopy(proof["operand_rules"][0])
    second_rule["operand_index"] = 0
    proof["operand_rules"].append(second_rule)
    assert "operand_rules must be canonically ordered" in validate_proof_shape(proof)


@pytest.mark.parametrize(
    ("collection", "replacement", "message"),
    [
        ("allocation_sites", {"entity_kind": "temporary"}, "unknown entity_kind"),
        ("free_sites", {"compiler_stage": "linker"}, "unknown compiler_stage"),
        ("operand_rewrite_sites", {"compiler_stage": "frontend"}, None),
        ("operand_mutation_sites", {"compiler_stage": "scheduler"}, None),
        ("code_emission_sites", {"compiler_stage": "backend-finalize"}, None),
    ],
)
def test_all_site_inventories_are_validated(collection, replacement, message):
    proof = minimal_instrumentation_proof()
    proof[collection][0].update(replacement)

    errors = validate_proof_shape(proof)
    if message is None:
        assert errors == ()
    else:
        assert message in "\n".join(errors)


def test_proof_rejects_unknown_fields_and_cross_inventory_site_collisions():
    proof = minimal_instrumentation_proof()
    proof["unexpected"] = True
    proof["free_sites"][0]["extra"] = "value"
    proof["code_emission_sites"][0]["site_id"] = proof["allocation_sites"][0]["site_id"]
    proof["code_emission_sites"][0]["address"] = proof["allocation_sites"][0]["address"]

    errors = "\n".join(validate_proof_shape(proof))
    assert "unexpected proof fields" in errors
    assert "unexpected free site fields" in errors
    assert "duplicate site_id" in errors
    assert "duplicate site address" in errors


def test_opcode_table_and_operand_rules_are_closed_and_referentially_valid():
    proof = minimal_instrumentation_proof()
    proof["opcode_table"][0]["extra"] = True
    proof["operand_rules"][0]["role"] = "input"
    proof["operand_rules"][0]["allocation_requirement"] = "maybe"
    proof["operand_rules"][0]["opcode_id"] = 99

    errors = "\n".join(validate_proof_shape(proof))
    assert "unexpected opcode table fields" in errors
    assert "unknown operand role" in errors
    assert "unknown allocation_requirement" in errors
    assert "operand rule references unknown opcode_id" in errors


def test_malformed_enum_values_report_errors_without_crashing():
    proof = minimal_instrumentation_proof()
    proof["allocation_sites"][0]["entity_kind"] = []
    proof["allocation_sites"][0]["compiler_stage"] = {}
    proof["operand_rules"][0]["role"] = []
    proof["operand_rules"][0]["allocation_requirement"] = {}

    errors = "\n".join(validate_proof_shape(proof))

    assert "unknown entity_kind" in errors
    assert "unknown compiler_stage" in errors
    assert "unknown operand role" in errors
    assert "unknown allocation_requirement" in errors


def test_trusted_proof_from_trace_requires_one_function_and_returns_value_object():
    proof = minimal_instrumentation_proof()
    table = promoted_registry(proof)
    trace = {
        "functions": [
            {
                "name": "target",
                "object_bindings": {
                    "lifetime_proof": proof,
                    "capture_identity": {"compiler_executable_sha256": "a" * 64},
                },
            }
        ]
    }

    result = trusted_proof_from_trace(trace, "target", table)

    assert result == InstrumentationProof(
        proof_id=proof["proof_id"],
        compiler_executable_sha256="a" * 64,
        payload=proof,
        sha256=proof_sha256(proof),
    )
    with pytest.raises(ValueError, match="expected one function 'missing', found 0"):
        trusted_proof_from_trace(trace, "missing", table)


@pytest.mark.parametrize(
    ("trace", "message"),
    [
        ({}, "trace functions must be list"),
        ({"functions": {}}, "trace functions must be list"),
        ({"functions": [None]}, "trace function 0 must be object"),
        (
            {"functions": [{"name": "target"}]},
            "function 'target' object_bindings must be object",
        ),
        (
            {"functions": [{"name": "target", "object_bindings": []}]},
            "function 'target' object_bindings must be object",
        ),
        (
            {
                "functions": [
                    {"name": "target", "object_bindings": {"lifetime_proof": []}}
                ]
            },
            "function 'target' lifetime_proof must be object",
        ),
        (
            {
                "functions": [
                    {
                        "name": "target",
                        "object_bindings": {
                            "lifetime_proof": minimal_instrumentation_proof(),
                            "capture_identity": [],
                        },
                    }
                ]
            },
            "function 'target' capture_identity must be object",
        ),
        (
            {
                "functions": [
                    {
                        "name": "target",
                        "object_bindings": {
                            "lifetime_proof": minimal_instrumentation_proof(),
                            "capture_identity": {},
                        },
                    }
                ]
            },
            "function 'target' capture compiler digest must be 64 lowercase hex",
        ),
    ],
)
def test_trusted_proof_from_trace_controls_incomplete_and_wrong_type_evidence(
    trace, message
):
    with pytest.raises(ValueError, match=message):
        trusted_proof_from_trace(trace, "target", promoted_registry(minimal_instrumentation_proof()))
