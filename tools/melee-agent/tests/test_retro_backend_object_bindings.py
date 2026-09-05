import copy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro.backend_instrumentation_proof import (  # noqa: E402
    InstrumentationProof,
    proof_sha256,
)
from tools.mwcc_retro.backend_object_bindings import (  # noqa: E402
    validate_object_bindings,
)


def minimal_proof_payload() -> dict[str, object]:
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
                "site_id": "objobject-free-1",
                "address": 0x500200,
                "entity_kind": "objobject",
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


def trusted_proof() -> InstrumentationProof:
    payload = minimal_proof_payload()
    return InstrumentationProof(
        proof_id=payload["proof_id"],
        compiler_executable_sha256=payload["compiler_executable_sha256"],
        payload=payload,
        sha256=proof_sha256(payload),
    )


def lifecycle(
    sequence: int,
    event: str,
    entity_kind: str,
    runtime_address: int,
    generation: int,
) -> dict[str, object]:
    allocate = event == "allocate"
    return {
        "sequence": sequence,
        "event": event,
        "entity_kind": entity_kind,
        "runtime_address": runtime_address,
        "allocation_generation": generation,
        "instrumented_site_id": (f"{entity_kind}-alloc-1" if allocate else f"{entity_kind}-free-1"),
        "compiler_stage": "frontend" if allocate else "backend-finalize",
    }


def snapshot(stage: str, *, sequence: int = 0, generation: int = 1) -> dict[str, object]:
    return {
        "stage": stage,
        "allocation_generation": generation,
        "lifecycle_sequence_at_capture": sequence,
        "runtime_address": 0x1000,
        "name_record_pointer": 0x2000,
        "type_pointer": 0x3000,
        "type_size": 4,
        "readable": True,
    }


def object_record(
    *,
    stages: tuple[str, ...] = ("colorgraph_return", "final_scheduler"),
    areas: list[str] | None = None,
) -> dict[str, object]:
    if areas is None:
        areas = ["locals"]
    return {
        "object_id": "obj-0",
        "allocation_generation": 1,
        "runtime_address": 0x1000,
        "name": "@1897",
        "name_kind": "compiler-synthetic",
        "name_record_pointer": 0x2000,
        "type_pointer": 0x3000,
        "type_size": 4,
        "areas": areas,
        "stage_snapshots": [snapshot(stage) for stage in stages],
        "cross_stage_identity_confidence": ("derived-unique" if len(stages) == 2 else None),
        "lifetime_identity_mode": "allocation-generation",
    }


def virtual_binding(*, virtual: int = 66, ig_id: int | None = None) -> dict[str, object]:
    return {
        "object_id": "obj-0",
        "class_id": 0,
        "class_name": "gpr",
        "virtual_kind": "r",
        "virtual": virtual,
        "ig_id": virtual if ig_id is None else ig_id,
        "ignode_runtime_address": 0x4000 + virtual,
        "source_stage": "colorgraph_return",
        "confidence": "observed",
        "provenance": "retail-ignode.obj_addr",
    }


def frame_binding() -> dict[str, object]:
    return {
        "object_id": "obj-0",
        "area": "locals",
        "list_node_runtime_address": 0x5000,
        "raw_object_stack_offset": -12,
        "frame_base_size": 84,
        "frame_call_args_size": 0,
        "final_r1_offset": 72,
        "size": 4,
        "source_stage": "final_scheduler",
        "confidence": "derived-unique",
        "provenance": [
            "retail-frame-layout-formula.v1",
            "retail-frame-list.object",
            "retail-objobject.stack-offset",
        ],
    }


def pcode_coverage() -> dict[str, object]:
    return {
        "status": "complete",
        "operand_rewrite_sites_expected": 1,
        "operand_rewrite_sites_hooked": 1,
        "operand_mutation_sites_expected": 1,
        "operand_mutation_sites_hooked": 1,
        "code_emission_sites_expected": 1,
        "code_emission_sites_hooked": 1,
        "first_event_sequence": -1,
        "last_event_sequence": -1,
        "parsed_register_operands": 0,
        "allocatable_register_operands": 0,
        "fixed_physical_register_operands": 0,
        "rewrite_events": 0,
        "mutation_events": 0,
        "final_pcodes": 0,
        "emission_events": 0,
        "event_cap": 8192,
        "dropped_events": 0,
        "truncated": False,
        "errors": [],
    }


def lifetime_coverage(*, empty: bool = False) -> dict[str, object]:
    return {
        "mode": "allocation-generation",
        "status": "complete",
        "proof_id": "gc-1.2.5n-backend-entity-allocation-trace.v1",
        "proof_sha256": trusted_proof().sha256,
        "initialization_stage": "compiler-process-entry-before-compile",
        "allocation_sites_expected": 2,
        "allocation_sites_hooked": 2,
        "free_sites_expected": 1,
        "free_sites_hooked": 1,
        "first_event_sequence": -1 if empty else 0,
        "last_event_sequence": -1 if empty else 0,
        "allocation_events": 0 if empty else 1,
        "free_events": 0,
        "reuse_events": 0,
        "generation_assignments": 0 if empty else 1,
        "event_cap": 4096,
        "dropped_events": 0,
        "truncated": False,
        "errors": [],
    }


def minimal_object_bindings() -> dict[str, object]:
    proof = trusted_proof()
    return {
        "schema_version": "mwcc-retro-object-bindings.v1",
        "capture_identity": {
            "nonce": "1" * 32,
            "compiler_executable_sha256": "a" * 64,
            "source_sha256": "b" * 64,
            "mwcc_command_sha256": "c" * 64,
            "environment_digest": "d" * 64,
            "candidate_object_sha256": "e" * 64,
            "function": "target",
            "capture_run_id": "f" * 64,
        },
        "capture_run_id": "f" * 64,
        "lifetime_proof": copy.deepcopy(dict(proof.payload)),
        "coverage": {
            "status": "complete",
            "ig_classes": ["gpr", "fpr"],
            "frame_areas": ["arguments", "locals", "temps"],
            "spill_owned_ig_coverage": "complete",
            "pcode_instrumentation": pcode_coverage(),
            "lifetime_identity": lifetime_coverage(),
            "allocator_stage": "colorgraph_return",
            "frame_stage": "final_scheduler",
            "objects_seen": 1,
            "virtual_bindings_seen": 1,
            "frame_bindings_seen": 1,
            "pcode_instructions_seen": 0,
            "pcode_occurrences_seen": 0,
            "caps": {
                "max_ig_nodes": 2048,
                "max_frame_objects_per_area": 256,
                "max_pcode_instructions": 4096,
                "max_pcode_operands_per_instruction": 32,
            },
            "truncated": False,
            "errors": [],
        },
        "lifecycle_events": [lifecycle(0, "allocate", "objobject", 0x1000, 1)],
        "objects": [object_record()],
        "virtual_bindings": [virtual_binding()],
        "frame_bindings": [frame_binding()],
        "pcode_instructions": [],
        "pcode_occurrences": [],
        "pcode_operand_lineage_events": [],
        "source_bindings": [],
        "source_capture": None,
    }


def assert_invalid(payload: object, message: str) -> None:
    result = validate_object_bindings(payload, trusted_proof())
    assert any(message in error for error in result.errors), result.errors
    assert result.capabilities == frozenset()


def test_complete_capture_verifies_compiler_objects_but_withholds_downstream_capabilities():
    result = validate_object_bindings(minimal_object_bindings(), trusted_proof())

    assert result.errors == ()
    assert result.capabilities == frozenset({"compiler-object-bindings"})
    assert result.normalized["virtual_bindings"][0]["confidence"] == "observed"
    assert result.normalized["frame_bindings"][0]["confidence"] == "derived-unique"
    with pytest.raises(TypeError):
        result.normalized["objects"][0]["type_size"] = 8


def test_replay_requires_generation_active_at_both_snapshots():
    payload = minimal_object_bindings()
    payload["lifecycle_events"] = [
        lifecycle(0, "allocate", "objobject", 0x1000, 1),
        lifecycle(1, "free", "objobject", 0x1000, 1),
        lifecycle(2, "allocate", "objobject", 0x1000, 2),
    ]
    coverage = payload["coverage"]["lifetime_identity"]
    coverage.update(
        {
            "last_event_sequence": 2,
            "allocation_events": 2,
            "free_events": 1,
            "reuse_events": 1,
            "generation_assignments": 2,
        }
    )
    payload["objects"][0]["stage_snapshots"][1]["lifecycle_sequence_at_capture"] = 2

    assert_invalid(payload, "snapshot generation is not active")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda p: p["lifecycle_events"][0].update({"sequence": 1}),
            "lifecycle sequence gap",
        ),
        (
            lambda p: p["lifecycle_events"][0].update({"event": "recycle"}),
            "unknown lifecycle event",
        ),
        (
            lambda p: p["lifecycle_events"][0].update({"instrumented_site_id": "missing"}),
            "unknown allocation site",
        ),
        (
            lambda p: p["lifecycle_events"][0].update({"compiler_stage": "scheduler"}),
            "does not match trusted site",
        ),
        (
            lambda p: p["lifecycle_events"][0].update({"allocation_generation": 2}),
            "generation must increment",
        ),
        (
            lambda p: p["objects"][0]["stage_snapshots"][0].update({"lifecycle_sequence_at_capture": 9}),
            "snapshot lifecycle sequence is out of range",
        ),
    ],
)
def test_lifecycle_replay_fail_closed_matrix(mutate, message):
    payload = minimal_object_bindings()
    mutate(payload)
    assert_invalid(payload, message)


def test_unmatched_free_and_allocation_while_active_are_rejected():
    payload = minimal_object_bindings()
    payload["lifecycle_events"] = [lifecycle(0, "free", "objobject", 0x1000, 1)]
    assert_invalid(payload, "free has no matching active allocation")

    payload = minimal_object_bindings()
    payload["lifecycle_events"].append(lifecycle(1, "allocate", "objobject", 0x1000, 2))
    assert_invalid(payload, "allocation occurred while prior generation is active")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda p: p["objects"][0]["stage_snapshots"][1].update({"allocation_generation": 2}),
            "snapshot generation is not active",
        ),
        (
            lambda p: p["objects"][0]["stage_snapshots"][1].update({"type_pointer": 0x3004}),
            "object fingerprint changed",
        ),
        (
            lambda p: p["objects"][0].update({"cross_stage_identity_confidence": None}),
            "two-stage object confidence must be derived-unique",
        ),
        (
            lambda p: p["objects"][0]["stage_snapshots"].append(snapshot("final_scheduler")),
            "stage_snapshots must contain one or two records",
        ),
        (
            lambda p: p["objects"][0].update({"object_id": "obj-9"}),
            "object_id is not deterministic",
        ),
        (
            lambda p: p["objects"][0].update({"lifetime_identity_mode": "pointer"}),
            "lifetime_identity_mode must be allocation-generation",
        ),
    ],
)
def test_object_identity_fail_closed_matrix(mutate, message):
    payload = minimal_object_bindings()
    mutate(payload)
    assert_invalid(payload, message)


def test_one_stage_allocator_and_frame_objects_are_valid_diagnostic_facts():
    allocator = minimal_object_bindings()
    allocator["objects"][0] = object_record(stages=("colorgraph_return",), areas=["spill-owned"])
    allocator["frame_bindings"] = []
    allocator["coverage"]["frame_bindings_seen"] = 0
    result = validate_object_bindings(allocator, trusted_proof())
    assert result.errors == ()
    assert result.normalized["objects"][0]["cross_stage_identity_confidence"] is None

    frame = minimal_object_bindings()
    frame["objects"][0] = object_record(stages=("final_scheduler",))
    frame["virtual_bindings"] = []
    frame["coverage"]["virtual_bindings_seen"] = 0
    result = validate_object_bindings(frame, trusted_proof())
    assert result.errors == ()


def test_one_object_may_bind_multiple_virtuals_and_spill_objects_have_no_home():
    payload = minimal_object_bindings()
    payload["objects"][0] = object_record(stages=("colorgraph_return",), areas=["spill-owned"])
    payload["virtual_bindings"].append(virtual_binding(virtual=67))
    payload["frame_bindings"] = []
    payload["coverage"].update({"virtual_bindings_seen": 2, "frame_bindings_seen": 0})

    result = validate_object_bindings(payload, trusted_proof())

    assert result.errors == ()
    assert len(result.normalized["virtual_bindings"]) == 2


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda p: p["virtual_bindings"].append(copy.deepcopy(p["virtual_bindings"][0])),
            "duplicate virtual binding",
        ),
        (
            lambda p: p["virtual_bindings"][0].update({"object_id": "obj-7"}),
            "virtual binding references unknown object",
        ),
        (
            lambda p: p["virtual_bindings"][0].update({"class_id": 1, "class_name": "gpr", "virtual_kind": "f"}),
            "virtual class fields disagree",
        ),
        (
            lambda p: p["objects"][0].update({"areas": ["spill-owned"]}),
            "spill-owned object cannot have frame binding",
        ),
        (
            lambda p: p["frame_bindings"][0].update({"final_r1_offset": 73}),
            "final_r1_offset does not match frame layout formula",
        ),
        (
            lambda p: p["frame_bindings"][0].update({"confidence": "observed"}),
            "frame binding confidence must be derived-unique",
        ),
        (
            lambda p: p["frame_bindings"][0].update({"area": "temps"}),
            "frame binding area is absent from object areas",
        ),
    ],
)
def test_virtual_and_frame_binding_fail_closed_matrix(mutate, message):
    payload = minimal_object_bindings()
    mutate(payload)
    assert_invalid(payload, message)


def test_one_virtual_cannot_be_owned_by_two_objects():
    payload = minimal_object_bindings()
    second = copy.deepcopy(payload["objects"][0])
    second.update({"object_id": "obj-1", "runtime_address": 0x1100})
    for row in second["stage_snapshots"]:
        row["runtime_address"] = 0x1100
    payload["objects"].append(second)
    payload["lifecycle_events"].append(lifecycle(1, "allocate", "objobject", 0x1100, 1))
    other = copy.deepcopy(payload["virtual_bindings"][0])
    other.update({"object_id": "obj-1", "ignode_runtime_address": 0x6000})
    payload["virtual_bindings"].append(other)
    payload["coverage"].update({"objects_seen": 2, "virtual_bindings_seen": 2})
    payload["coverage"]["lifetime_identity"].update(
        {
            "last_event_sequence": 1,
            "allocation_events": 2,
            "generation_assignments": 2,
        }
    )

    assert_invalid(payload, "virtual/IG identity has multiple objects")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda p: p["capture_identity"].update({"capture_run_id": "0" * 64}),
            "capture_run_id does not match capture identity",
        ),
        (
            lambda p: p.update({"source_capture": {"schema_version": "invalid"}}),
            "source_capture must be null in v1",
        ),
        (
            lambda p: p.update({"source_bindings": [{"object_id": "obj-0"}]}),
            "source_bindings must be empty in v1",
        ),
        (
            lambda p: p.update({"unexpected": True}),
            "object_bindings fields",
        ),
        (
            lambda p: p["objects"][0].update({"unexpected": True}),
            "object 0 fields",
        ),
        (
            lambda p: p["objects"][0].update({"areas": ["locals", "arguments"]}),
            "areas must be canonically ordered",
        ),
        (
            lambda p: p["coverage"].update({"frame_areas": ["locals", "arguments", "temps"]}),
            "frame_areas must be canonically ordered",
        ),
    ],
)
def test_closed_schema_reserved_fields_and_canonical_arrays(mutate, message):
    payload = minimal_object_bindings()
    mutate(payload)
    assert_invalid(payload, message)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda p: p["coverage"].update({"status": "partial"}),
            "coverage status must be complete",
        ),
        (
            lambda p: p["coverage"].update({"ig_classes": ["gpr"]}),
            "IG coverage must include gpr and fpr",
        ),
        (
            lambda p: p["coverage"].update({"frame_areas": ["arguments", "locals"]}),
            "frame coverage must include arguments, locals, and temps",
        ),
        (
            lambda p: p["coverage"].update({"spill_owned_ig_coverage": "partial"}),
            "spill-owned IG coverage must be complete",
        ),
        (
            lambda p: p["coverage"].update({"objects_seen": 0}),
            "objects_seen does not match objects",
        ),
        (
            lambda p: p["coverage"].update({"truncated": True}),
            "coverage is truncated",
        ),
        (
            lambda p: p["coverage"].update({"errors": ["reader failed"]}),
            "coverage errors must be empty",
        ),
        (
            lambda p: p["coverage"]["lifetime_identity"].update({"dropped_events": 1}),
            "lifecycle events were dropped",
        ),
        (
            lambda p: p["coverage"]["lifetime_identity"].update({"allocation_sites_hooked": 1}),
            "allocation site coverage is incomplete",
        ),
        (
            lambda p: p["coverage"]["lifetime_identity"].update({"allocation_events": 0, "generation_assignments": 0}),
            "allocation_events does not match lifecycle replay",
        ),
        (
            lambda p: p["coverage"]["caps"].update({"max_ig_nodes": 1}),
            "IG node cap was reached",
        ),
    ],
)
def test_completeness_is_recomputed_and_partial_evidence_has_no_capability(mutate, message):
    payload = minimal_object_bindings()
    mutate(payload)
    assert_invalid(payload, message)


def test_embedded_proof_and_coverage_must_match_trusted_proof():
    payload = minimal_object_bindings()
    payload["lifetime_proof"]["proof_id"] = "self-attested"
    assert_invalid(payload, "embedded lifetime_proof does not match trusted proof")

    payload = minimal_object_bindings()
    payload["coverage"]["lifetime_identity"]["proof_sha256"] = "0" * 64
    assert_invalid(payload, "coverage proof_sha256 does not match trusted proof")


def test_trusted_proof_value_object_must_be_internally_digest_consistent():
    payload = minimal_object_bindings()
    proof = trusted_proof()
    forged = InstrumentationProof(
        proof_id=proof.proof_id,
        compiler_executable_sha256=proof.compiler_executable_sha256,
        payload=proof.payload,
        sha256="0" * 64,
    )
    payload["coverage"]["lifetime_identity"]["proof_sha256"] = forged.sha256

    result = validate_object_bindings(payload, forged)

    assert "trusted proof digest does not match trusted proof payload" in result.errors
    assert result.capabilities == frozenset()


def test_complete_empty_capture_still_verifies_availability_capabilities():
    payload = minimal_object_bindings()
    payload["lifecycle_events"] = []
    payload["objects"] = []
    payload["virtual_bindings"] = []
    payload["frame_bindings"] = []
    payload["coverage"].update(
        {
            "objects_seen": 0,
            "virtual_bindings_seen": 0,
            "frame_bindings_seen": 0,
            "lifetime_identity": lifetime_coverage(empty=True),
        }
    )

    result = validate_object_bindings(payload, trusted_proof())

    assert result.errors == ()
    assert result.capabilities == frozenset({"compiler-object-bindings"})


def test_zero_positive_virtual_bindings_cannot_prove_ig_cap_non_exhaustion():
    payload = minimal_object_bindings()
    payload["virtual_bindings"] = []
    payload["coverage"]["virtual_bindings_seen"] = 0
    payload["coverage"]["caps"]["max_ig_nodes"] = 1

    result = validate_object_bindings(payload, trusted_proof())

    assert result.errors == ()
    assert result.capabilities == frozenset({"compiler-object-bindings"})
    assert result.normalized["virtual_bindings"] == ()


def test_unreadable_snapshot_is_diagnostic_only_and_blocks_all_capabilities():
    payload = minimal_object_bindings()
    payload["objects"][0]["stage_snapshots"][0]["readable"] = False

    result = validate_object_bindings(payload, trusted_proof())

    assert any("snapshot is unreadable" in error for error in result.errors)
    assert result.capabilities == frozenset()
    assert result.normalized["objects"][0]["stage_snapshots"][0]["readable"] is False


def test_two_stage_snapshot_lifecycle_positions_must_be_monotonic():
    payload = minimal_object_bindings()
    pcode_event = lifecycle(1, "allocate", "pcode", 0x9000, 1)
    pcode_event["compiler_stage"] = "backend-lowering"
    payload["lifecycle_events"].append(pcode_event)
    payload["coverage"]["lifetime_identity"].update(
        {
            "last_event_sequence": 1,
            "allocation_events": 2,
            "generation_assignments": 2,
        }
    )
    payload["objects"][0]["stage_snapshots"][0]["lifecycle_sequence_at_capture"] = 1
    payload["objects"][0]["stage_snapshots"][1]["lifecycle_sequence_at_capture"] = 0

    assert_invalid(payload, "snapshot lifecycle sequences must be monotonic")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda p: p["virtual_bindings"][0].update({"ig_id": 67}),
            "virtual must equal ig_id",
        ),
        (
            lambda p: p["virtual_bindings"].append({**p["virtual_bindings"][0], "ignode_runtime_address": 0x7000}),
            "duplicate class/virtual binding",
        ),
        (
            lambda p: p["virtual_bindings"].append({**virtual_binding(virtual=67), "ignode_runtime_address": 0x4042}),
            "duplicate IGNode runtime address",
        ),
    ],
)
def test_virtual_identity_bijection_rejects_near_duplicate_rows(mutate, message):
    payload = minimal_object_bindings()
    mutate(payload)
    payload["coverage"]["virtual_bindings_seen"] = len(payload["virtual_bindings"])
    assert_invalid(payload, message)


def test_frame_list_node_pointer_is_globally_unique():
    payload = minimal_object_bindings()
    payload["objects"][0]["areas"] = ["locals", "temps"]
    second = copy.deepcopy(payload["frame_bindings"][0])
    second.update({"area": "temps", "final_r1_offset": 76, "raw_object_stack_offset": -8})
    payload["frame_bindings"].append(second)
    payload["coverage"]["frame_bindings_seen"] = 2

    assert_invalid(payload, "duplicate frame list node runtime address")


def test_partial_positive_bindings_remain_immutable_diagnostics_without_capability():
    payload = minimal_object_bindings()
    payload["coverage"]["lifetime_identity"]["dropped_events"] = 1

    result = validate_object_bindings(payload, trusted_proof())

    assert result.capabilities == frozenset()
    assert result.normalized["virtual_bindings"][0]["virtual"] == 66
    assert result.normalized["frame_bindings"][0]["final_r1_offset"] == 72
    with pytest.raises(TypeError):
        result.normalized["objects"][0]["type_size"] = 8


def _set_path(payload: dict[str, object], path: tuple[object, ...], value: object) -> None:
    current: object = payload
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value


INTEGER_FIELD_CASES = (
    (("lifecycle_events", 0, "sequence"), 0),
    (("lifecycle_events", 0, "runtime_address"), 0x1000),
    (("lifecycle_events", 0, "allocation_generation"), 1),
    (("coverage", "objects_seen"), 1),
    (("coverage", "virtual_bindings_seen"), 1),
    (("coverage", "frame_bindings_seen"), 1),
    (("coverage", "pcode_instructions_seen"), 0),
    (("coverage", "pcode_occurrences_seen"), 0),
    (("coverage", "caps", "max_ig_nodes"), 2048),
    (("coverage", "caps", "max_frame_objects_per_area"), 256),
    (("coverage", "caps", "max_pcode_instructions"), 4096),
    (("coverage", "caps", "max_pcode_operands_per_instruction"), 32),
    (("coverage", "lifetime_identity", "allocation_sites_expected"), 2),
    (("coverage", "lifetime_identity", "allocation_sites_hooked"), 2),
    (("coverage", "lifetime_identity", "free_sites_expected"), 1),
    (("coverage", "lifetime_identity", "free_sites_hooked"), 1),
    (("coverage", "lifetime_identity", "first_event_sequence"), 0),
    (("coverage", "lifetime_identity", "last_event_sequence"), 0),
    (("coverage", "lifetime_identity", "allocation_events"), 1),
    (("coverage", "lifetime_identity", "free_events"), 0),
    (("coverage", "lifetime_identity", "reuse_events"), 0),
    (("coverage", "lifetime_identity", "generation_assignments"), 1),
    (("coverage", "lifetime_identity", "event_cap"), 4096),
    (("coverage", "lifetime_identity", "dropped_events"), 0),
    (("objects", 0, "allocation_generation"), 1),
    (("objects", 0, "runtime_address"), 0x1000),
    (("objects", 0, "name_record_pointer"), 0x2000),
    (("objects", 0, "type_pointer"), 0x3000),
    (("objects", 0, "type_size"), 4),
    (("objects", 0, "stage_snapshots", 0, "allocation_generation"), 1),
    (("objects", 0, "stage_snapshots", 0, "lifecycle_sequence_at_capture"), 0),
    (("objects", 0, "stage_snapshots", 0, "runtime_address"), 0x1000),
    (("objects", 0, "stage_snapshots", 0, "name_record_pointer"), 0x2000),
    (("objects", 0, "stage_snapshots", 0, "type_pointer"), 0x3000),
    (("objects", 0, "stage_snapshots", 0, "type_size"), 4),
    (("virtual_bindings", 0, "class_id"), 0),
    (("virtual_bindings", 0, "virtual"), 66),
    (("virtual_bindings", 0, "ig_id"), 66),
    (("virtual_bindings", 0, "ignode_runtime_address"), 0x4042),
    (("frame_bindings", 0, "list_node_runtime_address"), 0x5000),
    (("frame_bindings", 0, "raw_object_stack_offset"), -12),
    (("frame_bindings", 0, "frame_base_size"), 84),
    (("frame_bindings", 0, "frame_call_args_size"), 0),
    (("frame_bindings", 0, "final_r1_offset"), 72),
    (("frame_bindings", 0, "size"), 4),
)


@pytest.mark.parametrize(("path", "original"), INTEGER_FIELD_CASES)
@pytest.mark.parametrize("replacement_kind", ["bool", "float"])
def test_every_task4_integer_field_rejects_bool_and_float(path, original, replacement_kind):
    payload = minimal_object_bindings()
    replacement = True if replacement_kind == "bool" else float(original)
    _set_path(payload, path, replacement)

    result = validate_object_bindings(payload, trusted_proof())

    assert result.errors, (path, replacement)
    assert result.capabilities == frozenset()


class _DeferredMutable:
    pass


@pytest.mark.parametrize(
    "bad_value",
    [
        {"not-json"},
        ("tuple-is-not-json-array",),
        bytearray(b"mutable"),
        _DeferredMutable(),
        {1: "non-string JSON object key"},
        "\ud800",
        1 << 100,
    ],
)
def test_non_json_or_deferred_mutable_values_are_rejected(bad_value):
    payload = minimal_object_bindings()
    payload["pcode_instructions"] = [{"deferred": bad_value}]
    payload["coverage"]["pcode_instructions_seen"] = 1

    result = validate_object_bindings(payload, trusted_proof())

    assert any("diagnostic normalization failed" in error for error in result.errors)
    assert result.capabilities == frozenset()


def test_deferred_mapping_rejects_unpaired_surrogate_key_without_capability():
    payload = minimal_object_bindings()
    payload["pcode_instructions"] = [{"deferred": {"\ud800": "value"}}]
    payload["coverage"]["pcode_instructions_seen"] = 1

    result = validate_object_bindings(payload, trusted_proof())

    assert any("diagnostic normalization failed" in error for error in result.errors)
    assert result.capabilities == frozenset()


def test_deferred_json_collections_are_deeply_frozen():
    payload = minimal_object_bindings()
    payload["pcode_instructions"] = [{"operands": [{"metadata": ["stable", {"value": 7}]}]}]
    payload["coverage"]["pcode_instructions_seen"] = 1

    result = validate_object_bindings(payload, trusted_proof())

    assert result.errors == ()
    row = result.normalized["pcode_instructions"][0]
    with pytest.raises(TypeError):
        row["new"] = True
    with pytest.raises(AttributeError):
        row["operands"].append({})
    with pytest.raises(TypeError):
        row["operands"][0]["metadata"][1]["value"] = 8


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"schema_version": "mwcc-retro-object-bindings.v1"},
        {**minimal_object_bindings(), "objects": None},
        {**minimal_object_bindings(), "lifecycle_events": [None]},
    ],
)
def test_malformed_types_fail_closed_without_raw_exceptions(payload):
    result = validate_object_bindings(payload, trusted_proof())
    assert result.errors
    assert result.capabilities == frozenset()


@pytest.mark.parametrize(
    ("mutate", "label"),
    [
        (lambda p: p.update({"capture_identity": []}), "capture identity"),
        (lambda p: p.update({"lifetime_proof": []}), "embedded proof"),
        (lambda p: p.update({"coverage": []}), "coverage"),
        (lambda p: p["coverage"].update({"ig_classes": {}}), "IG classes"),
        (lambda p: p["coverage"].update({"frame_areas": [{}]}), "frame areas"),
        (lambda p: p["coverage"].update({"caps": []}), "caps"),
        (
            lambda p: p["coverage"].update({"lifetime_identity": []}),
            "lifetime coverage",
        ),
        (
            lambda p: p["coverage"].update({"pcode_instrumentation": []}),
            "PCode coverage container",
        ),
        (lambda p: p.update({"lifecycle_events": [{}]}), "lifecycle row"),
        (lambda p: p["objects"].__setitem__(0, []), "object row"),
        (lambda p: p["objects"][0].update({"areas": [{}]}), "object areas"),
        (
            lambda p: p["objects"][0].update({"stage_snapshots": [[]]}),
            "snapshot row",
        ),
        (lambda p: p["virtual_bindings"].__setitem__(0, []), "virtual row"),
        (lambda p: p["frame_bindings"].__setitem__(0, []), "frame row"),
        (
            lambda p: p["frame_bindings"][0].update({"provenance": {}}),
            "frame provenance",
        ),
    ],
)
def test_nested_malformed_containers_never_escape_as_raw_exceptions(mutate, label):
    payload = minimal_object_bindings()
    mutate(payload)

    result = validate_object_bindings(payload, trusted_proof())

    assert result.errors, label
    assert result.capabilities == frozenset(), label
