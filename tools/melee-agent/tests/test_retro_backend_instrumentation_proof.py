import copy
import hashlib
import importlib
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_instrumentation_proof as proof_module  # noqa: E402
from tools.mwcc_retro.backend_instrumentation_proof import (  # noqa: E402
    InstrumentationProof,
    proof_sha256,
    trusted_proof_from_trace,
    validate_embedded_proof,
    validate_proof_shape,
)


def expand_operand_descriptors(*args, **kwargs):
    return proof_module.expand_operand_descriptors(*args, **kwargs)


def classify_operand(*args, **kwargs):
    return proof_module.classify_operand(*args, **kwargs)


def resolve_operand_role(*args, **kwargs):
    return proof_module.resolve_operand_role(*args, **kwargs)


def _manifest_module():
    return importlib.import_module("tools.mwcc_retro.backend_runtime_hook_manifest")


def runtime_hook_manifest_sha256(*args, **kwargs):
    return _manifest_module().runtime_hook_manifest_sha256(*args, **kwargs)


def validate_runtime_hook_manifest(*args, **kwargs):
    return _manifest_module().validate_runtime_hook_manifest(*args, **kwargs)


CUSTOM_OPCODE_IDS = frozenset({3, 4, 12, 13, 15, 16, 199})


def _opcode_rows() -> list[dict[str, object]]:
    rows = []
    for opcode_id in range(468):
        custom = opcode_id in CUSTOM_OPCODE_IDS
        rows.append(
            {
                "opcode_id": opcode_id,
                "mnemonic": "ADDI" if opcode_id == 63 else f"OP_{opcode_id:03d}",
                "format_string": "=r,b,m,p" if opcode_id == 63 else "",
                "constructor_kind": "custom" if custom else "generic-fixed",
                "variadic_layout": None,
                "custom_constructor_addresses": (
                    [0x410000 + opcode_id * 0x10] if custom else []
                ),
            }
        )
    return rows


def _gpr_rules() -> list[dict[str, object]]:
    return [
        {
            "capture_stage": "allocator_input",
            "register_flags_mask": 0xFF,
            "register_flags_value": 2,
            "register_value_min": 32,
            "register_value_max": 0xFFFF,
            "allocation_state": "virtual",
        },
        {
            "capture_stage": "code_emission",
            "register_flags_mask": 0xFF,
            "register_flags_value": 2,
            "register_value_min": 0,
            "register_value_max": 31,
            "allocation_state": "physical",
        },
    ]


def _operand_descriptors() -> list[dict[str, object]]:
    return [
        {
            "opcode_id": 63,
            "descriptor_index": 0,
            "descriptor_source": "format",
            "format_code": "r",
            "expansion": {"kind": "one", "count": 1},
            "raw_arg_kind_id": 0,
            "role": "def",
            "role_rules": [],
            "register_form": "gpr",
            "class_id": 0,
            "virtual_kind": "r",
            "state_rules": _gpr_rules(),
        },
        {
            "opcode_id": 63,
            "descriptor_index": 1,
            "descriptor_source": "format",
            "format_code": "b",
            "expansion": {"kind": "one", "count": 1},
            "raw_arg_kind_id": 0,
            "role": "use",
            "role_rules": [],
            "register_form": "gpr",
            "class_id": 0,
            "virtual_kind": "r",
            "state_rules": _gpr_rules(),
        },
        {
            "opcode_id": 63,
            "descriptor_index": 2,
            "descriptor_source": "format",
            "format_code": "m",
            "expansion": {"kind": "one", "count": 1},
            "raw_arg_kind_id": 4,
            "role": "use",
            "role_rules": [],
            "register_form": "none",
            "class_id": None,
            "virtual_kind": None,
            "state_rules": [],
        },
        {
            "opcode_id": 63,
            "descriptor_index": 3,
            "descriptor_source": "format",
            "format_code": "p",
            "expansion": {"kind": "one", "count": 1},
            "raw_arg_kind_id": 5,
            "role": "use",
            "role_rules": [],
            "register_form": "none",
            "class_id": None,
            "virtual_kind": None,
            "state_rules": [],
        },
    ]


def _site(site_id: str, address: int, stage: str, **extra: object) -> dict[str, object]:
    return {"site_id": site_id, "address": address, "compiler_stage": stage, **extra}


def minimal_instrumentation_proof() -> dict[str, object]:
    return {
        "schema_version": "mwcc-retro-lifetime-proof.v1",
        "proof_id": "gc-1.2.5n-backend-entity-allocation-trace.v1",
        "compiler_executable_sha256": "a" * 64,
        "runtime_hook_manifest_sha256": "0" * 64,
        "mode": "allocation-generation",
        "allocation_sites": [
            _site(
                "pcode-alloc-1",
                0x500100,
                "backend-lowering",
                entity_kind="pcode",
            )
        ],
        "free_sites": [
            _site(
                "pcode-free-1",
                0x500200,
                "backend-finalize",
                entity_kind="pcode",
            )
        ],
        "operand_rewrite_sites": [
            _site("rewrite-register-operand-1", 0x500300, "colorgraph")
        ],
        "operand_mutation_sites": [
            _site("rewrite-pcode-operands-1", 0x500400, "optimizer")
        ],
        "code_emission_sites": [
            _site("emit-pcode-1", 0x500500, "backend-finalize")
        ],
        "operand_rules": _operand_descriptors(),
        "opcode_table": _opcode_rows(),
        "initialization_address": 0x401000,
        "proof_basis": "exhaustive-static-callgraph-and-disassembly",
    }


OPERATIONS = {
    "allocation_sites": "allocation",
    "free_sites": "release",
    "operand_rewrite_sites": "operand-rewrite",
    "operand_mutation_sites": "replace",
    "code_emission_sites": "final-buffer-emission",
}


def _capture_source(
    name: str,
    source_kind: str,
    phase: str,
    *,
    operand_index: int | None = None,
    register: str | None = None,
    stack_argument_index: int | None = None,
    byte_offset: int = 0,
    byte_width: int = 4,
) -> dict[str, object]:
    return {
        "name": name,
        "source_kind": source_kind,
        "phase": phase,
        "operand_index": operand_index,
        "register": register,
        "stack_argument_index": stack_argument_index,
        "byte_offset": byte_offset,
        "byte_width": byte_width,
    }


def _runtime_plan(operation: str) -> tuple[str, list[dict[str, object]]]:
    if operation == "allocation":
        return (
            "same-thread-call-return",
            [
                _capture_source(
                    "allocation_length",
                    "stack-argument",
                    "before",
                    stack_argument_index=0,
                ),
                _capture_source(
                    "allocated_pointer", "return-register", "return", register="eax"
                ),
            ],
        )
    if operation in {"recycle", "rewind", "release"}:
        return (
            "same-thread-call-return",
            [
                _capture_source(
                    "entity_pointer",
                    "stack-argument",
                    "before",
                    stack_argument_index=0,
                )
            ],
        )
    if operation == "operand-rewrite":
        return (
            "same-thread-instruction",
            [
                _capture_source(
                    "operand_address",
                    "effective-address",
                    "before",
                    operand_index=0,
                    byte_offset=-2,
                    byte_width=12,
                )
            ],
        )
    if operation in {"create", "delete", "reorder", "clone", "replace", "spill", "coalesce"}:
        sources = []
        if operation != "create":
            sources.extend(
                [
                    _capture_source(
                        "input_pointer", "x86-register", "before", register="eax"
                    ),
                    _capture_source(
                        "input_length", "x86-register", "before", register="ecx"
                    ),
                ]
            )
        if operation != "delete":
            sources.extend(
                [
                    _capture_source(
                        "output_pointer", "x86-register", "after", register="eax"
                    ),
                    _capture_source(
                        "output_length", "x86-register", "after", register="ecx"
                    ),
                ]
            )
        return "same-thread-function-entry-exit", sources
    if operation == "encode":
        return (
            "same-thread-call-return",
            [
                _capture_source(
                    "pcode_pointer",
                    "stack-argument",
                    "before",
                    stack_argument_index=0,
                ),
                _capture_source(
                    "encoded_word", "return-register", "return", register="eax"
                ),
            ],
        )
    if operation == "final-buffer-emission":
        return (
            "same-thread-instruction",
            [
                _capture_source(
                    "buffer_pointer", "x86-register", "before", register="eax"
                ),
                _capture_source(
                    "buffer_length", "x86-register", "before", register="ecx"
                ),
            ],
        )
    raise AssertionError(f"missing synthetic runtime plan for {operation}")


def _manifest_for_proof(proof: Mapping[str, object]) -> dict[str, object]:
    sites = []
    for family, operation in OPERATIONS.items():
        for proof_site in proof[family]:
            pairing, capture_sources = _runtime_plan(operation)
            before = bytes.fromhex("90")
            after = bytes.fromhex("6690")
            after_phase = "return" if pairing == "same-thread-call-return" else "after"
            sites.append(
                {
                    "site_id": proof_site["site_id"],
                    "family": family,
                    "proof_address": proof_site["address"],
                    "operation": operation,
                    "breakpoints": [
                        {
                            "phase": "before",
                            "address": proof_site["address"],
                            "instruction_bytes": before.hex(),
                            "instruction_sha256": hashlib.sha256(before).hexdigest(),
                        },
                        {
                            "phase": after_phase,
                            "address": proof_site["address"] + 1,
                            "instruction_bytes": after.hex(),
                            "instruction_sha256": hashlib.sha256(after).hexdigest(),
                        },
                    ],
                    "capture_sources": capture_sources,
                    "pairing": pairing,
                    "hit_policy": "probe-union",
                }
            )
    return {
        "schema_version": "mwcc-retro-runtime-hooks.v1",
        "compiler_executable_sha256": proof["compiler_executable_sha256"],
        "proof_id": proof["proof_id"],
        "sites": sites,
    }


def valid_proof_and_manifest() -> tuple[dict[str, object], dict[str, object]]:
    proof = minimal_instrumentation_proof()
    manifest = _manifest_for_proof(proof)
    proof["runtime_hook_manifest_sha256"] = runtime_hook_manifest_sha256(manifest)
    return proof, manifest


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


def proof_descriptor(
    proof: Mapping[str, object], opcode_id: int, descriptor_index: int
):
    descriptors = expand_operand_descriptors(proof, opcode_id, 4)
    return next(
        item for item in descriptors if item.descriptor_index == descriptor_index
    )


def test_complete_proof_has_valid_shape_and_stable_canonical_digest():
    proof, manifest = valid_proof_and_manifest()
    reordered = {key: proof[key] for key in reversed(proof)}

    assert validate_proof_shape(proof) == ()
    assert validate_runtime_hook_manifest(manifest, proof) == ()
    assert proof_sha256(proof) == proof_sha256(reordered)
    assert len(proof_sha256(proof)) == 64


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["opcode_table"].pop(), "opcode IDs must be exactly 0..467"),
        (
            lambda p: p["opcode_table"][1].update(
                {"mnemonic": p["opcode_table"][0]["mnemonic"]}
            ),
            "opcode mnemonics must be unique",
        ),
        (
            lambda p: p["opcode_table"][3].update(
                {"custom_constructor_addresses": []}
            ),
            "custom opcode must have constructor addresses",
        ),
        (
            lambda p: p["opcode_table"][63].update(
                {"constructor_kind": "generic-variadic"}
            ),
            "generic-variadic opcode must bind exact variadic_layout",
        ),
    ],
)
def test_opcode_table_is_complete_unique_and_constructor_bound(mutate, message):
    proof, _manifest = valid_proof_and_manifest()
    mutate(proof)
    assert message in "\n".join(validate_proof_shape(proof))


def test_hash_marker_does_not_consume_an_operand():
    proof, _manifest = valid_proof_and_manifest()
    proof["opcode_table"][63].update(
        {
            "format_string": "#,=r,b,m,=V",
            "constructor_kind": "generic-variadic",
            "variadic_layout": {
                "count_source": "first-vararg-u32-at-generic-constructor",
                "count_width": 4,
                "constructor_count_min": 0,
                "constructor_count_max": 0xFFFFFFFF,
                "base_operand_count": 3,
                "count_arithmetic": "u32-add-metadata-low-byte-store-low-u16",
                "tail_expansion": "format-V",
                "reachability": "reachable",
                "reachable_count_min": 1,
                "reachable_count_max": 32,
                "call_addresses": [0x410000],
                "evidence_addresses": [0x410000, 0x4A268C, 0x4A2AB5],
            },
        }
    )
    proof["operand_rules"][3].update(
        {
            "format_code": "V",
            "expansion": {"kind": "remaining", "count": None},
            "raw_arg_kind_id": 0,
            "role": "def",
            "register_form": "gpr",
            "class_id": 0,
            "virtual_kind": "r",
            "state_rules": _gpr_rules(),
        }
    )

    assert validate_proof_shape(proof) == ()
    assert len(expand_operand_descriptors(proof, 63, 4)) == 4


def test_real_non_v_variadic_uses_explicit_post_constructor_tail():
    proof, _manifest = valid_proof_and_manifest()
    proof["opcode_table"][1].update(
        {
            "format_string": "#,m",
            "constructor_kind": "generic-variadic",
            "variadic_layout": {
                "count_source": "first-vararg-u32-at-generic-constructor",
                "count_width": 4,
                "constructor_count_min": 0,
                "constructor_count_max": 0xFFFFFFFF,
                "base_operand_count": 1,
                "count_arithmetic": "u32-add-metadata-low-byte-store-low-u16",
                "tail_expansion": "post-constructor",
                "reachability": "reachable",
                "reachable_count_min": 0,
                "reachable_count_max": 0xFFFFFFFF,
                "call_addresses": [0x410000],
                "evidence_addresses": [0x410000, 0x4A268C, 0x4A2691, 0x4A26A1, 0x4A26E2],
            },
        }
    )
    proof["operand_rules"] = [
        {
            "opcode_id": 1,
            "descriptor_index": 0,
            "descriptor_source": "format",
            "format_code": "m",
            "expansion": {"kind": "one", "count": 1},
            "raw_arg_kind_id": 4,
            "role": "use",
            "role_rules": [],
            "register_form": "none",
            "class_id": None,
            "virtual_kind": None,
            "state_rules": [],
        },
        {
            "opcode_id": 1,
            "descriptor_index": 1,
            "descriptor_source": "variadic-tail",
            "format_code": None,
            "expansion": {"kind": "remaining", "count": None},
            "raw_arg_kind_id": 0,
            "role": "use",
            "role_rules": [],
            "register_form": "gpr",
            "class_id": 0,
            "virtual_kind": "r",
            "state_rules": _gpr_rules(),
        },
    ]
    proof["opcode_table"][63]["format_string"] = ""

    assert validate_proof_shape(proof) == ()
    expanded = expand_operand_descriptors(proof, 1, 4)
    assert [row.descriptor_index for row in expanded] == [0, 1, 1, 1]


def test_variadic_layout_and_tail_expansion_fail_closed():
    proof, _manifest = valid_proof_and_manifest()
    proof["opcode_table"][1].update(
        {
            "format_string": "#,m",
            "constructor_kind": "generic-variadic",
            "variadic_layout": None,
        }
    )
    errors = "\n".join(validate_proof_shape(proof))
    assert "generic-variadic opcode must bind exact variadic_layout" in errors

    proof, _manifest = valid_proof_and_manifest()
    proof["opcode_table"][1].update(
        {
            "format_string": "#,m",
            "constructor_kind": "generic-variadic",
            "variadic_layout": {
                "count_source": "first-vararg-u32-at-generic-constructor",
                "count_width": 4,
                "constructor_count_min": 0,
                "constructor_count_max": 32,
                "base_operand_count": 1,
                "count_arithmetic": "u32-add-metadata-low-byte-store-low-u16",
                "tail_expansion": "post-constructor",
                "reachability": "reachable",
                "reachable_count_min": 0,
                "reachable_count_max": 32,
                "call_addresses": [0x410000],
                "evidence_addresses": [0x410000, 0x4A268C],
            },
        }
    )
    errors = "\n".join(validate_proof_shape(proof))
    assert "constructor count bounds must be exact u32 domain" in errors
    assert "post-constructor variadic opcode must have tail descriptors" in errors


def test_variadic_tail_role_rules_resolve_exactly_one_flags_domain():
    descriptor = proof_module.ExpandedOperandDescriptor(
        operand_index=0,
        descriptor_index=0,
        descriptor_source="variadic-tail",
        raw_arg_kind_id=0,
        role=None,
        role_rules=(
            {
                "register_flags_mask": 0xFF,
                "register_flags_value": 2,
                "role": "def",
            },
            {
                "register_flags_mask": 0xFF,
                "register_flags_value": 3,
                "role": "use-def",
            },
        ),
        register_form="gpr",
        class_id=0,
        virtual_kind="r",
        state_rules=(),
    )
    assert resolve_operand_role(descriptor, 2) == "def"
    assert resolve_operand_role(descriptor, 3) == "use-def"
    with pytest.raises(ValueError, match="exactly one operand role rule"):
        resolve_operand_role(descriptor, 1)
    with pytest.raises(ValueError, match="exactly one operand role rule"):
        resolve_operand_role(descriptor, 0x82)


def test_overlapping_role_rules_fail_closed():
    proof, _manifest = valid_proof_and_manifest()
    descriptor = proof["operand_rules"][0]
    descriptor["role"] = None
    descriptor["role_rules"] = [
        {
            "register_flags_mask": 1,
            "register_flags_value": 0,
            "role": "def",
        },
        {
            "register_flags_mask": 2,
            "register_flags_value": 0,
            "role": "use",
        },
    ]

    assert "has overlapping role rules" in "\n".join(validate_proof_shape(proof))


def test_expansion_rejects_wrong_y_nonfinal_v_negative_and_leftover_counts():
    proof, _manifest = valid_proof_and_manifest()
    proof["opcode_table"][63]["format_string"] = "Y"
    proof["operand_rules"] = [copy.deepcopy(proof["operand_rules"][0])]
    descriptor = proof["operand_rules"][0]
    descriptor.update(
        {
            "descriptor_index": 0,
            "format_code": "Y",
            "expansion": {"kind": "fixed", "count": 7},
        }
    )
    assert "Y expansion count must be 8" in "\n".join(validate_proof_shape(proof))

    descriptor["expansion"] = {"kind": "fixed", "count": 8}
    assert len(expand_operand_descriptors(proof, 63, 8)) == 8

    descriptor.update(
        {"format_code": "V", "expansion": {"kind": "remaining", "count": None}}
    )
    proof["opcode_table"][63]["format_string"] = "Vr"
    proof["operand_rules"].append(copy.deepcopy(_operand_descriptors()[0]))
    proof["operand_rules"][1]["descriptor_index"] = 1
    assert "remaining expansion must be final" in "\n".join(validate_proof_shape(proof))

    proof, _manifest = valid_proof_and_manifest()
    with pytest.raises(ValueError, match="negative operand remainder"):
        expand_operand_descriptors(proof, 63, 3)
    with pytest.raises(ValueError, match="leftover operands"):
        expand_operand_descriptors(proof, 63, 5)
    with pytest.raises(ValueError, match="unsigned 16-bit"):
        expand_operand_descriptors(proof, 63, 0x10000)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {
                "register_form": "vector",
                "raw_arg_kind_id": 0,
                "class_id": 9,
                "virtual_kind": "v",
            },
            "vector register coupling is invalid",
        ),
        (
            {
                "register_form": "special",
                "raw_arg_kind_id": 2,
                "class_id": None,
                "virtual_kind": None,
            },
            "special registers may only be non-allocator",
        ),
        (
            {
                "register_form": "cr",
                "raw_arg_kind_id": 3,
                "class_id": None,
                "virtual_kind": None,
            },
            "cr registers may only be non-allocator",
        ),
    ],
)
def test_vector_special_and_cr_coupling_is_closed(updates, message):
    proof, _manifest = valid_proof_and_manifest()
    descriptor = proof["operand_rules"][0]
    descriptor.update(updates)
    assert message in "\n".join(validate_proof_shape(proof))


def test_addi_stage_and_u16_value_break_old_rule_collision():
    proof, _manifest = valid_proof_and_manifest()
    before = classify_operand(
        proof_descriptor(proof, 63, 0), "allocator_input", 2, 34
    )
    after = classify_operand(
        proof_descriptor(proof, 63, 0), "code_emission", 2, 0
    )
    assert (before.allocation_state, before.virtual, before.physical_register) == (
        "virtual",
        34,
        None,
    )
    assert (after.allocation_state, after.virtual, after.physical_register) == (
        "physical",
        None,
        0,
    )


def test_classification_rejects_wrong_stage_missing_and_overlapping_rules():
    proof, _manifest = valid_proof_and_manifest()
    descriptor = proof_descriptor(proof, 63, 0)
    with pytest.raises(ValueError, match="exactly one operand state rule"):
        classify_operand(descriptor, "mutation_output", 2, 34)

    proof["operand_rules"][0]["state_rules"] = []
    assert "register descriptor must have state rules" in "\n".join(
        validate_proof_shape(proof)
    )

    proof, _manifest = valid_proof_and_manifest()
    proof["operand_rules"][0]["state_rules"].append(
        copy.deepcopy(proof["operand_rules"][0]["state_rules"][0])
    )
    assert "overlapping state rules" in "\n".join(validate_proof_shape(proof))


def test_proof_digest_binds_runtime_hook_manifest():
    proof, manifest = valid_proof_and_manifest()
    manifest["sites"][0]["capture_sources"][0]["byte_width"] = 2
    assert "runtime hook manifest digest differs from proof" in validate_runtime_hook_manifest(
        manifest, proof
    )


def test_runtime_hook_manifest_recomputes_instruction_digest_and_rejects_expressions():
    proof, manifest = valid_proof_and_manifest()
    manifest["sites"][0]["breakpoints"][0]["instruction_bytes"] = "cc"
    manifest["sites"][1]["capture_sources"][0]["expression"] = "$eax+2"
    errors = "\n".join(validate_runtime_hook_manifest(manifest, proof))
    assert "instruction digest does not match bytes" in errors
    assert "capture source 0 fields" in errors


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda proof: proof["allocation_sites"].pop(),
            "allocation_sites must not be empty",
        ),
        (
            lambda proof: proof["allocation_sites"][0].update({"site_id": ""}),
            "site_id must be non-empty string",
        ),
        (
            lambda proof: proof["allocation_sites"].append(
                copy.deepcopy(proof["allocation_sites"][0])
            ),
            "duplicate allocation site",
        ),
        (
            lambda proof: proof["allocation_sites"][0].update(
                {"address": proof["allocation_sites"][0]["address"] + 4}
            ),
            "site inventory differs from proof",
        ),
    ],
)
def test_runtime_manifest_requires_valid_exact_proof_site_bijection(mutate, message):
    proof, manifest = valid_proof_and_manifest()
    mutate(proof)

    assert message in "\n".join(validate_runtime_hook_manifest(manifest, proof))


@pytest.mark.parametrize(
    ("site_index", "mutate", "message"),
    [
        (
            0,
            lambda sources: sources.pop(0),
            "capture_sources do not match operation contract",
        ),
        (
            4,
            lambda sources: sources.pop(1),
            "capture_sources do not match operation contract",
        ),
        (
            2,
            lambda sources: sources[0].update(
                {
                    "source_kind": "x86-register",
                    "operand_index": None,
                    "register": "eax",
                }
            ),
            "capture_sources do not match operation contract",
        ),
        (
            3,
            lambda sources: sources[0].update({"phase": "after"}),
            "capture_sources do not match operation contract",
        ),
        (
            2,
            lambda sources: sources[0].update({"byte_width": 4}),
            "capture_sources do not match operation contract",
        ),
        (
            2,
            lambda sources: sources[0].update({"byte_offset": 0}),
            "capture_sources do not match operation contract",
        ),
        (
            3,
            lambda sources: sources.append(copy.deepcopy(sources[0])),
            "capture_sources do not match operation contract",
        ),
    ],
)
def test_runtime_manifest_enforces_operation_capture_contract(
    site_index, mutate, message
):
    proof, manifest = valid_proof_and_manifest()
    mutate(manifest["sites"][site_index]["capture_sources"])

    assert message in "\n".join(validate_runtime_hook_manifest(manifest, proof))


def test_runtime_manifest_enforces_operation_pairing_contract():
    proof, manifest = valid_proof_and_manifest()
    manifest["sites"][0]["pairing"] = "same-thread-instruction"
    manifest["sites"][0]["breakpoints"][1]["phase"] = "after"

    assert "pairing does not match operation contract" in "\n".join(
        validate_runtime_hook_manifest(manifest, proof)
    )


@pytest.mark.parametrize(
    ("site_index", "source_index", "field", "value"),
    [
        (0, 0, "stack_argument_index", 99),
        (0, 1, "register", "ebx"),
        (2, 0, "operand_index", 1),
    ],
)
def test_runtime_manifest_binds_exact_capture_source_selector(
    site_index, source_index, field, value
):
    proof, manifest = valid_proof_and_manifest()
    manifest["sites"][site_index]["capture_sources"][source_index][field] = value

    assert "capture_sources do not match operation contract" in "\n".join(
        validate_runtime_hook_manifest(manifest, proof)
    )


class _HostileMapping(Mapping):
    def __getitem__(self, key):
        raise RuntimeError("hostile")

    def __iter__(self):
        raise RuntimeError("hostile")

    def __len__(self):
        return 1


def test_proof_and_manifest_validation_fail_closed_on_hostile_mappings():
    proof, _manifest = valid_proof_and_manifest()
    assert validate_proof_shape(_HostileMapping())
    assert validate_runtime_hook_manifest(_HostileMapping(), proof)
    assert validate_embedded_proof(
        _HostileMapping(), promoted_registry(proof), "a" * 64
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("family", []),
        ("operation", {}),
        ("pairing", []),
        ("hit_policy", []),
    ],
)
def test_runtime_manifest_rejects_unhashable_enum_values(field, value):
    proof, manifest = valid_proof_and_manifest()
    manifest["sites"][0][field] = value

    assert validate_runtime_hook_manifest(manifest, proof)


def test_runtime_manifest_rejects_unhashable_register_value():
    proof, manifest = valid_proof_and_manifest()
    source = manifest["sites"][0]["capture_sources"][0]
    source.update(
        {
            "source_kind": "x86-register",
            "operand_index": None,
            "register": [],
        }
    )

    assert validate_runtime_hook_manifest(manifest, proof)


def test_embedded_proof_and_trace_entrypoints_preserve_registry_contract():
    proof, _manifest = valid_proof_and_manifest()
    table = promoted_registry(proof)
    assert validate_embedded_proof(proof, table, "a" * 64) == ()
    assert validate_embedded_proof(proof, table, "b" * 64) == (
        "proof compiler digest does not match capture compiler digest",
        "instrumentation proof is not independently promoted for this compiler",
    )
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
    assert trusted_proof_from_trace(trace, "target", table) == InstrumentationProof(
        proof_id=proof["proof_id"],
        compiler_executable_sha256="a" * 64,
        payload=proof,
        sha256=proof_sha256(proof),
    )
    with pytest.raises(ValueError, match="expected one function 'missing', found 0"):
        trusted_proof_from_trace(trace, "missing", table)

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
def test_embedded_proof_rejects_invalid_registry_before_trust(
    mutate_table, expected
):
    proof, _manifest = valid_proof_and_manifest()
    table = promoted_registry(proof)
    mutate_table(table)

    errors = validate_embedded_proof(proof, table, "a" * 64)

    assert any(expected in error for error in errors)
    assert "instrumentation proof is not independently promoted for this compiler" in errors


@pytest.mark.parametrize("hostile_value", [float("nan"), float("inf"), 1 << 100])
def test_embedded_proof_rejects_noncanonical_payload_without_raising(hostile_value):
    proof, _manifest = valid_proof_and_manifest()
    proof["initialization_address"] = hostile_value

    errors = validate_embedded_proof(
        proof, promoted_registry(valid_proof_and_manifest()[0]), "a" * 64
    )

    assert "instrumentation proof is not RFC 8785 canonicalizable" in errors
    assert "instrumentation proof is not independently promoted for this compiler" in errors


def test_embedded_proof_rejects_recursive_payload_without_raising():
    proof, _manifest = valid_proof_and_manifest()
    recursive: list[object] = []
    recursive.append(recursive)
    proof["operand_rules"] = recursive

    errors = validate_embedded_proof(
        proof, promoted_registry(valid_proof_and_manifest()[0]), "a" * 64
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
    proof, _manifest = valid_proof_and_manifest()
    proof[collection][0].update(replacement)

    errors = validate_proof_shape(proof)
    if message is None:
        assert errors == ()
    else:
        assert message in "\n".join(errors)


def test_proof_rejects_unknown_fields_and_cross_inventory_site_collisions():
    proof, _manifest = valid_proof_and_manifest()
    proof["unexpected"] = True
    proof["free_sites"][0]["extra"] = "value"
    proof["code_emission_sites"][0]["site_id"] = proof["allocation_sites"][0][
        "site_id"
    ]
    proof["code_emission_sites"][0]["address"] = proof["allocation_sites"][0][
        "address"
    ]

    errors = "\n".join(validate_proof_shape(proof))
    assert "unexpected proof fields" in errors
    assert "unexpected free site fields" in errors
    assert "duplicate site_id" in errors
    assert "duplicate site address" in errors


def test_malformed_enum_values_report_errors_without_crashing():
    proof, _manifest = valid_proof_and_manifest()
    proof["allocation_sites"][0]["entity_kind"] = []
    proof["opcode_table"][0]["constructor_kind"] = []
    proof["operand_rules"][0]["role"] = []
    proof["operand_rules"][0]["state_rules"][0]["allocation_state"] = []

    errors = "\n".join(validate_proof_shape(proof))

    assert "unknown entity_kind" in errors
    assert "constructor_kind is invalid" in errors
    assert "operand role is invalid" in errors
    assert "allocation_state is invalid" in errors


@pytest.mark.parametrize(
    "mutate",
    [
        lambda proof: proof["operand_rules"][0]["expansion"].update({"kind": []}),
        lambda proof: proof["operand_rules"][0]["state_rules"][0].update(
            {"register_flags_mask": []}
        ),
        lambda proof: proof["opcode_table"][0].update(
            {
                "constructor_kind": "generic-variadic",
                "format_string": "#,m",
                "variadic_layout": {
                    "count_source": "first-vararg-u32-at-generic-constructor",
                    "count_width": 4,
                    "constructor_count_min": 0,
                    "constructor_count_max": 0xFFFFFFFF,
                    "base_operand_count": 1,
                    "count_arithmetic": "u32-add-metadata-low-byte-store-low-u16",
                    "tail_expansion": [],
                    "reachability": "reachable",
                    "reachable_count_min": 49,
                    "reachable_count_max": 49,
                    "call_addresses": [0x410000],
                    "evidence_addresses": [0x410000, 0x4A268C],
                },
            }
        ),
    ],
)
def test_proof_rejects_unhashable_nested_values_without_raising(mutate):
    proof, _manifest = valid_proof_and_manifest()
    mutate(proof)

    assert validate_proof_shape(proof)


def test_proof_rejects_duplicate_sites_and_unsorted_rules():
    proof, _manifest = valid_proof_and_manifest()
    proof["allocation_sites"] *= 2
    assert "duplicate allocation site" in "\n".join(validate_proof_shape(proof))

    proof, _manifest = valid_proof_and_manifest()
    second_rule = copy.deepcopy(proof["operand_rules"][0])
    second_rule["opcode_id"] = 62
    second_rule["descriptor_index"] = 0
    proof["operand_rules"].append(second_rule)
    assert "operand_rules must be canonically ordered" in validate_proof_shape(proof)


def test_opcode_table_and_operand_rules_are_closed_and_referentially_valid():
    proof, _manifest = valid_proof_and_manifest()
    proof["opcode_table"][0]["extra"] = True
    proof["operand_rules"][0]["role"] = "input"
    proof["operand_rules"][0]["state_rules"][0]["allocation_state"] = "maybe"
    proof["operand_rules"][0]["opcode_id"] = 999

    errors = "\n".join(validate_proof_shape(proof))
    assert "unexpected opcode table fields" in errors
    assert "operand role is invalid" in errors
    assert "allocation_state is invalid" in errors
    assert "operand descriptor 0 references unknown opcode_id" in errors


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
        trusted_proof_from_trace(
            trace,
            "target",
            promoted_registry(minimal_instrumentation_proof()),
        )
