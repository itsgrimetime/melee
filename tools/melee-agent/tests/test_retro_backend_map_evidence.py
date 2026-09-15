import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_map_probe_hook, struct_map  # noqa: E402
from tools.mwcc_retro.backend_instrumentation_proof import (  # noqa: E402
    proof_sha256,
)
from tools.mwcc_retro.backend_map_evidence import classify_probe_evidence  # noqa: E402

PROMOTABLE_FROM_LIVE_PROBE = {
    "codegen_start",
    "codegen_end",
    "pcbasicblocks",
    "interference_matrix",
    "coalesce_alias",
    "interferencegraph",
    "n_ignodes",
    "build_interference_matrix",
    "real_coalesce",
    "build_adjacency_vectors",
    "simplifygraph",
    "colorgraph",
}

NOT_PROMOTABLE_FROM_CURRENT_PROBE = {
    "pcode_pass_boundary",
    "backend_block_list",
    "used_vreg_gpr",
    "used_vreg_fpr",
    "frame_locals",
    "final_scheduler",
}


def _valid_instrumentation_proof():
    return {
        "schema_version": "mwcc-retro-lifetime-proof.v1",
        "proof_id": "proof",
        "compiler_executable_sha256": "a" * 64,
        "mode": "allocation-generation",
        "allocation_sites": [
            {
                "site_id": "pcode-alloc-1",
                "address": 0x500100,
                "entity_kind": "pcode",
                "compiler_stage": "backend-lowering",
            }
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
                "site_id": "rewrite-1",
                "address": 0x500300,
                "compiler_stage": "colorgraph",
            },
            {
                "site_id": "rewrite-2",
                "address": 0x500310,
                "compiler_stage": "colorgraph",
            },
        ],
        "operand_mutation_sites": [
            {
                "site_id": "mutation-1",
                "address": 0x500400,
                "compiler_stage": "optimizer",
            }
        ],
        "code_emission_sites": [
            {
                "site_id": "emit-1",
                "address": 0x500500,
                "compiler_stage": "backend-finalize",
            }
        ],
        "operand_rules": [
            {
                "opcode_id": 42,
                "operand_index": 0,
                "raw_arg_kind_id": 0,
                "register_flags_mask": 1,
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


def _validated_instrumentation_table(proof=None):
    proof = _valid_instrumentation_proof() if proof is None else proof
    digest = proof_sha256(proof)
    return {
        "instrumentation_proof_schema": "mwcc-retro-lifetime-proof.v1",
        "instrumentation_proofs": [
            {
                "compiler_executable_sha256": proof["compiler_executable_sha256"],
                "proof_id": proof["proof_id"],
                "proof_sha256": digest,
                "promoted": True,
            }
        ],
        "backend_reader": {
            "pcode_instrumentation": {
                "validated": True,
                "compiler_executable_sha256": proof[
                    "compiler_executable_sha256"
                ],
                "proof_id": proof["proof_id"],
                "proof_sha256": digest,
                "operand_rewrite_site_ids": ["rewrite-1", "rewrite-2"],
                "operand_mutation_site_ids": ["mutation-1"],
                "code_emission_site_ids": ["emit-1"],
            }
        },
    }


class _BrokenProofMapping(Mapping):
    def __getitem__(self, key):
        raise RuntimeError("broken proof mapping")

    def __iter__(self):
        raise RuntimeError("broken proof mapping")

    def __len__(self):
        return 1


class _BrokenList(list):
    def __iter__(self):
        raise RuntimeError("broken proof list")


def test_pcode_instrumentation_gate_rejects_unpromoted_and_partial_site_inventory():
    table = struct_map.load_gc125n_struct_map()
    assert table["instrumentation_proofs"] == []

    errors = struct_map.validate_pcode_instrumentation_capability(table)

    assert "no promoted instrumentation proof" in errors
    assert "pcode instrumentation gate is not validated" in errors

    layout_errors = struct_map.validate_pcode_arg_capture_capability(table)
    assert "PCode.args expected offset 0x1c, got None" in layout_errors
    assert "missing required PCodeArg struct" in layout_errors


def test_pcode_instrumentation_gate_fails_closed_on_altered_site_inventory():
    proof = _valid_instrumentation_proof()
    table = _validated_instrumentation_table(proof)
    table["backend_reader"]["pcode_instrumentation"][
        "operand_mutation_site_ids"
    ] = ["mutation-2"]

    errors = struct_map.validate_pcode_instrumentation_capability(
        table, proof=proof
    )

    assert errors == ["operand mutation site inventory differs from proof"]


def test_validated_pcode_instrumentation_requires_proof_mapping():
    errors = struct_map.validate_pcode_instrumentation_capability(
        _validated_instrumentation_table()
    )

    assert "PCode instrumentation proof must be object" in errors


def test_validated_pcode_instrumentation_fails_closed_on_broken_proof_mapping():
    errors = struct_map.validate_pcode_instrumentation_capability(
        _validated_instrumentation_table(), proof=_BrokenProofMapping()
    )

    assert "PCode instrumentation proof could not be materialized" in errors


def test_validated_pcode_instrumentation_fails_closed_on_hostile_nested_table():
    table = _validated_instrumentation_table()
    table["instrumentation_proofs"][0] = _BrokenProofMapping()

    errors = struct_map.validate_pcode_instrumentation_capability(
        table, proof=_valid_instrumentation_proof()
    )

    assert any(
        "PCode instrumentation table could not be materialized" in error
        for error in errors
    )


def test_validated_pcode_instrumentation_fails_closed_on_hostile_nested_proof_site():
    proof = _valid_instrumentation_proof()
    table = _validated_instrumentation_table(proof)
    proof["operand_rewrite_sites"][0] = _BrokenProofMapping()

    errors = struct_map.validate_pcode_instrumentation_capability(
        table, proof=proof
    )

    assert any(
        "PCode instrumentation proof could not be materialized" in error
        for error in errors
    )


def test_validated_pcode_instrumentation_fails_closed_on_hostile_nested_proof_list():
    proof = _valid_instrumentation_proof()
    table = _validated_instrumentation_table(proof)
    proof["operand_rewrite_sites"] = _BrokenList(
        proof["operand_rewrite_sites"]
    )

    errors = struct_map.validate_pcode_instrumentation_capability(
        table, proof=proof
    )

    assert any(
        "PCode instrumentation proof could not be materialized" in error
        for error in errors
    )


@pytest.mark.parametrize("malformation", ["recursive", "surrogate", "float"])
def test_validated_pcode_instrumentation_rejects_non_json_safe_nested_proof(
    malformation,
):
    proof = _valid_instrumentation_proof()
    table = _validated_instrumentation_table(proof)
    site = proof["operand_rewrite_sites"][0]
    if malformation == "recursive":
        site["recursive"] = proof
    elif malformation == "surrogate":
        site["site_id"] = "bad-\ud800"
    else:
        site["address"] = 0x500300 + 0.0

    errors = struct_map.validate_pcode_instrumentation_capability(
        table, proof=proof
    )

    assert any(
        "PCode instrumentation proof could not be materialized" in error
        for error in errors
    )


def test_validated_pcode_instrumentation_accepts_exact_canonical_proof():
    proof = _valid_instrumentation_proof()
    assert (
        struct_map.validate_pcode_instrumentation_capability(
            _validated_instrumentation_table(proof), proof=proof
        )
        == []
    )


def test_validated_pcode_instrumentation_rejects_empty_proof_and_gate():
    proof = _valid_instrumentation_proof()
    for collection in (
        "allocation_sites",
        "free_sites",
        "operand_rewrite_sites",
        "operand_mutation_sites",
        "code_emission_sites",
        "opcode_table",
        "operand_rules",
    ):
        proof[collection] = []
    table = _validated_instrumentation_table(proof)
    gate = table["backend_reader"]["pcode_instrumentation"]
    gate["operand_rewrite_site_ids"] = []
    gate["operand_mutation_site_ids"] = []
    gate["code_emission_site_ids"] = []

    errors = struct_map.validate_pcode_instrumentation_capability(
        table, proof=proof
    )

    assert any("allocation_sites must not be empty" in error for error in errors)
    assert "operand rewrite site IDs must be nonempty list" in errors
    assert "operand mutation site IDs must be nonempty list" in errors
    assert "code emission site IDs must be nonempty list" in errors


def test_validated_pcode_instrumentation_rejects_malformed_registry():
    proof = _valid_instrumentation_proof()
    table = _validated_instrumentation_table(proof)
    table["instrumentation_proofs"].append({"promoted": True})

    errors = struct_map.validate_pcode_instrumentation_capability(
        table, proof=proof
    )

    assert any("registry row 1" in error for error in errors)


def test_validated_pcode_instrumentation_rejects_digest_mismatch():
    proof = _valid_instrumentation_proof()
    table = _validated_instrumentation_table(proof)
    table["instrumentation_proofs"][0]["proof_sha256"] = "b" * 64

    errors = struct_map.validate_pcode_instrumentation_capability(
        table, proof=proof
    )

    assert "proof digest differs from promoted registry" in errors


def test_validated_pcode_instrumentation_rejects_duplicate_gate_sites():
    proof = _valid_instrumentation_proof()
    table = _validated_instrumentation_table(proof)
    table["backend_reader"]["pcode_instrumentation"][
        "operand_rewrite_site_ids"
    ] = ["rewrite-1", "rewrite-1"]

    errors = struct_map.validate_pcode_instrumentation_capability(
        table, proof=proof
    )

    assert "operand rewrite site IDs must be unique" in errors


def test_validated_pcode_instrumentation_rejects_noncanonical_gate_sites():
    proof = _valid_instrumentation_proof()
    table = _validated_instrumentation_table(proof)
    table["backend_reader"]["pcode_instrumentation"][
        "operand_rewrite_site_ids"
    ] = ["rewrite-2", "rewrite-1"]

    errors = struct_map.validate_pcode_instrumentation_capability(
        table, proof=proof
    )

    assert "operand rewrite site IDs must be canonically ordered" in errors


def test_map_probe_reports_exact_unpromoted_pcode_gates_without_capability():
    status = backend_map_probe_hook.pcode_probe_status(
        struct_map.load_gc125n_struct_map()
    )

    assert status["status"] == "unpromoted"
    assert status["capabilities"] == []
    assert status["layout_errors"] == [
        "PCode.args expected offset 0x1c, got None",
        "missing required PCodeArg struct",
    ]
    assert status["proof_errors"] == [
        "no promoted instrumentation proof",
        "pcode instrumentation gate is not validated",
        "PCode instrumentation proof must be object",
    ]


def test_installed_table_records_explicit_unpromoted_pcode_gate():
    gate = struct_map.load_gc125n_struct_map()["backend_reader"][
        "pcode_instrumentation"
    ]

    assert gate == {
        "validated": False,
        "compiler_executable_sha256": (
            "ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c"
        ),
        "proof_id": None,
        "proof_sha256": None,
        "operand_rewrite_site_ids": [],
        "operand_mutation_site_ids": [],
        "code_emission_site_ids": [],
        "note": "Unpromoted: exhaustive static and live proof is incomplete.",
    }


def _fixture_payload():
    candidates = {
        "codegen_start": 0x4351C0,
        "codegen_end": 0x435DB9,
        "build_interference_matrix": 0x531290,
        "real_coalesce": 0x530E00,
        "build_adjacency_vectors": 0x530C00,
        "simplifygraph": 0x4CE400,
        "colorgraph": 0x4CE2D0,
    }

    def globals_sample(**overrides):
        sample = {
            "pcbasicblocks": {"va": 0x587C74, "u32": 0x62800C},
            "interference_matrix": {"va": 0x583088, "u32": 0x6501FC},
            "coalesce_alias": {"va": 0x58308C, "u32": 0x650254},
            "interferencegraph": {"va": 0x587E3C, "u32": 0x65029C},
            "n_ignodes": {"va": 0x587190, "u32": 4},
        }
        sample.update(overrides)
        return sample

    ig_sample = [
        {
            "slot": 0,
            "ptr": 0x65036C,
            "next": 0x6503C4,
            "ig_idx": 0,
            "degree": 2,
            "assignedReg": -1,
            "flags": 0,
            "arraySize": 2,
            "neighbors_sample": [1, 2],
        },
        {
            "slot": 1,
            "ptr": 0x6503C4,
            "next": 0,
            "ig_idx": 1,
            "degree": 1,
            "assignedReg": -1,
            "flags": 8,
            "arraySize": 1,
            "neighbors_sample": [0],
        },
    ]

    events = [
        {
            "stage": "codegen_start",
            "pc": candidates["codegen_start"],
            "globals": globals_sample(
                pcbasicblocks={"va": 0x587C74, "u32": 0},
                interference_matrix={"va": 0x583088, "u32": 0},
                coalesce_alias={"va": 0x58308C, "u32": 0},
                interferencegraph={"va": 0x587E3C, "u32": 0},
                n_ignodes={"va": 0x587190, "u32": 0},
            ),
        },
        {
            "stage": "build_interference_matrix",
            "pc": candidates["build_interference_matrix"],
            "globals": globals_sample(interference_matrix={"va": 0x583088, "u32": 0}),
        },
        {
            "stage": "real_coalesce",
            "pc": candidates["real_coalesce"],
            "globals": globals_sample(coalesce_alias={"va": 0x58308C, "u32": 0}),
        },
        {
            "stage": "build_adjacency_vectors",
            "pc": candidates["build_adjacency_vectors"],
            "globals": globals_sample(interferencegraph={"va": 0x587E3C, "u32": 0}),
        },
        {
            "stage": "simplifygraph",
            "pc": candidates["simplifygraph"],
            "globals": globals_sample(),
            "ig_sample": ig_sample,
        },
        {
            "stage": "colorgraph",
            "pc": candidates["colorgraph"],
            "globals": globals_sample(),
            "ig_sample": ig_sample,
        },
        {
            "stage": "codegen_end",
            "pc": candidates["codegen_end"],
            "globals": globals_sample(),
            "ig_sample": ig_sample,
        },
    ]
    return {
        "schema_version": "mwcc-retro-backend-map-probe.v1",
        "requested_function": "test_fn",
        "requested_function_matched": True,
        "errors": [],
        "candidates": candidates,
        "globals": {
            "pcbasicblocks": 0x587C74,
            "interference_matrix": 0x583088,
            "coalesce_alias": 0x58308C,
            "interferencegraph": 0x587E3C,
            "n_ignodes": 0x587190,
        },
        "events": events,
    }


def test_live_probe_fixture_classifies_only_explicit_invariants_as_promotable():
    result = classify_probe_evidence(_fixture_payload())

    assert set(result["promotable_entries"]) == PROMOTABLE_FROM_LIVE_PROBE
    for key, entry in result["promotable_entries"].items():
        assert entry["confidence"] == "live-invariant"
        assert isinstance(entry["va"], int)
        assert entry["va"] > 0

    assert set(NOT_PROMOTABLE_FROM_CURRENT_PROBE) <= set(result["blocked_entries"])
    assert "PCode" in result["blocked_structs"]
    assert "PCode" not in result["promotable_structs"]
    assert result["promotable_structs"]["IGNode"]["confidence"] == "live-invariant"
    assert result["promotable_structs"]["IGNode"]["fields"] == {
        "next": 0x00,
        "ig_idx": 0x0C,
        "degree": 0x0E,
        "assignedReg": 0x10,
        "flags": 0x12,
        "arraySize": 0x14,
        "array": 0x16,
    }


def test_unmatched_function_blocks_all_promotions():
    payload = _fixture_payload()
    payload["requested_function_matched"] = False

    result = classify_probe_evidence(payload)

    assert result["promotable_entries"] == {}
    assert result["promotable_structs"] == {}
    assert (
        result["blocked_entries"]["codegen_start"]["reason"]
        == "requested function was not matched"
    )
    assert (
        result["blocked_structs"]["IGNode"]["reason"]
        == "requested function was not matched"
    )


def test_payload_errors_block_all_promotions():
    payload = _fixture_payload()
    payload["errors"] = [{"stage": "simplifygraph", "error": "cannot read memory"}]

    result = classify_probe_evidence(payload)

    assert result["promotable_entries"] == {}
    assert result["promotable_structs"] == {}
    assert (
        "payload reported errors"
        in result["blocked_entries"]["codegen_start"]["reason"]
    )
    assert "payload reported errors" in result["blocked_structs"]["IGNode"]["reason"]


def test_missing_matching_stage_hit_blocks_that_candidate_only():
    payload = _fixture_payload()
    for event in payload["events"]:
        if event["stage"] == "colorgraph":
            event["pc"] = event["pc"] + 4

    result = classify_probe_evidence(payload)

    assert "colorgraph" not in result["promotable_entries"]
    assert (
        result["blocked_entries"]["colorgraph"]["reason"]
        == "missing matching stage hit"
    )
    assert "simplifygraph" in result["promotable_entries"]


def test_implausible_ig_sample_blocks_graph_evidence_and_ignode_struct():
    payload = _fixture_payload()
    for event in payload["events"]:
        if "ig_sample" in event:
            event["ig_sample"][0]["ig_idx"] = event["ig_sample"][0]["slot"] + 99
            break

    result = classify_probe_evidence(payload)

    assert "interferencegraph" not in result["promotable_entries"]
    assert "n_ignodes" not in result["promotable_entries"]
    assert "IGNode" not in result["promotable_structs"]
    assert (
        result["blocked_entries"]["interferencegraph"]["reason"]
        == "implausible IG sample"
    )
    assert (
        result["blocked_structs"]["IGNode"]["reason"]
        == "implausible IG sample"
    )


def test_ig_sample_neighbor_outside_live_node_count_blocks_graph_evidence():
    payload = _fixture_payload()
    for event in payload["events"]:
        if "ig_sample" in event:
            event["ig_sample"][0]["neighbors_sample"] = [100]

    result = classify_probe_evidence(payload)

    assert "interferencegraph" not in result["promotable_entries"]
    assert "n_ignodes" not in result["promotable_entries"]
    assert "IGNode" not in result["promotable_structs"]
    assert (
        result["blocked_entries"]["interferencegraph"]["reason"]
        == "implausible IG sample"
    )
    assert (
        result["blocked_structs"]["IGNode"]["reason"]
        == "implausible IG sample"
    )


def test_ig_sample_without_next_or_neighbors_does_not_promote_full_struct():
    payload = _fixture_payload()
    for event in payload["events"]:
        for row in event.get("ig_sample", []):
            row.pop("next", None)
            row.pop("neighbors_sample", None)

    result = classify_probe_evidence(payload)

    assert "interferencegraph" not in result["promotable_entries"]
    assert "n_ignodes" not in result["promotable_entries"]
    assert "IGNode" not in result["promotable_structs"]
    assert (
        result["blocked_structs"]["IGNode"]["reason"]
        == "IG sample missing next or inline array evidence"
    )


def test_richer_probe_promotes_used_vregs_final_scheduler_blocks_and_pcode():
    payload = _fixture_payload()
    payload["candidates"]["final_scheduler"] = 0x435D75
    payload["globals"]["used_vreg_gpr"] = 0x58846E
    payload["globals"]["used_vreg_fpr"] = 0x58846C

    block_sample = [
        {
            "slot": 0,
            "ptr": 0x62800C,
            "next": 0,
            "blockIndex": 0,
            "firstPCode": 0x650900,
            "lastPCode": 0x650930,
            "first_pcode": {
                "ptr": 0x650900,
                "next": 0,
                "opcode": 123,
                "arg_count": 2,
            },
        }
    ]
    final_globals = {
        "pcbasicblocks": {"va": 0x587C74, "u32": 0x62800C},
        "used_vreg_gpr": {"va": 0x58846E, "s16": 4},
        "used_vreg_fpr": {"va": 0x58846C, "s16": 3},
    }
    payload["events"].append(
        {
            "stage": "final_scheduler",
            "pc": 0x435D75,
            "stage_args": {},
            "globals": final_globals,
            "block_sample": block_sample,
            "frame_state": {
                "locals": {
                    "va": 0x587FB8,
                    "head": 0x650A00,
                    "objects_sample": [
                        {
                            "node": 0x650A00,
                            "next": 0,
                            "object": 0x650B00,
                            "name": "local_x",
                            "stack_offset": -0x20,
                            "size": 4,
                        }
                    ],
                },
                "frame_base_size": {"va": 0x5880CC, "s32": 0x50},
                "frame_call_args_size": {"va": 0x58712C, "s32": 0x20},
            },
        }
    )
    payload["events"].append(
        {
            "stage": "real_coalesce",
            "pc": payload["candidates"]["real_coalesce"],
            "stage_args": {"rclass": 0, "n_virtuals": 4},
            "globals": final_globals,
        }
    )
    payload["events"].append(
        {
            "stage": "real_coalesce",
            "pc": payload["candidates"]["real_coalesce"],
            "stage_args": {"rclass": 1, "n_virtuals": 3},
            "globals": final_globals,
        }
    )

    result = classify_probe_evidence(payload)

    for key in (
        "final_scheduler",
        "backend_block_list",
        "frame_locals",
        "used_vreg_gpr",
        "used_vreg_fpr",
    ):
        assert key in result["promotable_entries"]
        assert result["promotable_entries"][key]["confidence"] == "live-invariant"
    assert result["promotable_entries"]["backend_block_list"]["va"] == 0x587C74
    assert result["promotable_entries"]["frame_locals"]["va"] == 0x587FB8
    assert result["promotable_structs"]["PCode"] == {
        "confidence": "live-invariant",
        "fields": {"next": 0x00, "opcode": 0x14, "arg_count": 0x1A},
        "evidence": "block sample proves PCode next/opcode/arg_count fields",
    }
    assert result["promotable_structs"]["PCodeBlock"] == {
        "confidence": "live-invariant",
        "fields": {"next": 0x00, "firstPCode": 0x14, "blockIndex": 0x1C},
        "evidence": "block sample proves PCodeBlock next/firstPCode/blockIndex fields",
    }


def test_empty_block_sample_does_not_promote_pcode_structs():
    payload = _fixture_payload()
    payload["events"].append(
        {
            "stage": "final_scheduler",
            "pc": 0x435D75,
            "globals": {"pcbasicblocks": {"va": 0x587C74, "u32": 0x62800C}},
            "block_sample": [
                {
                    "slot": 0,
                    "ptr": 0x62800C,
                    "next": 0,
                    "blockIndex": 0,
                    "firstPCode": 0,
                    "lastPCode": 0,
                }
            ],
        }
    )

    result = classify_probe_evidence(payload)

    assert "PCode" not in result["promotable_structs"]
    assert "PCodeBlock" not in result["promotable_structs"]
    assert result["blocked_structs"]["PCode"]["reason"] == "missing PCode sample"
    assert result["blocked_structs"]["PCodeBlock"]["reason"] == "missing PCode sample"


def test_pcode_sample_without_next_does_not_promote_pcode_structs():
    payload = _fixture_payload()
    payload["events"].append(
        {
            "stage": "final_scheduler",
            "pc": 0x435D75,
            "globals": {"pcbasicblocks": {"va": 0x587C74, "u32": 0x62800C}},
            "block_sample": [
                {
                    "slot": 0,
                    "ptr": 0x62800C,
                    "next": 0,
                    "blockIndex": 0,
                    "firstPCode": 0x650900,
                    "lastPCode": 0x650930,
                    "first_pcode": {
                        "ptr": 0x650900,
                        "opcode": 123,
                        "arg_count": 2,
                    },
                }
            ],
        }
    )

    result = classify_probe_evidence(payload)

    assert "PCode" not in result["promotable_structs"]
    assert "PCodeBlock" not in result["promotable_structs"]
    assert result["blocked_structs"]["PCode"]["reason"] == "implausible PCode sample"
    assert (
        result["blocked_structs"]["PCodeBlock"]["reason"]
        == "implausible PCode sample"
    )
