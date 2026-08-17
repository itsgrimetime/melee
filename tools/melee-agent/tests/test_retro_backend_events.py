import copy
import hashlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_events, backend_schema  # noqa: E402

FIXTURE = REPO / "tools/melee-agent/tests/fixtures/retro/backend_events_v1_minimal.jsonl"
COMPILER = {"family": "MWCC", "version": "GC/1.2.5n", "retail": True}
SOURCE = {
    "tu": "src/melee/test/unit.c",
    "function": "test_fn",
    "mwcc_command": "test mwcc command events test_fn",
    "mwcc_command_hash": "sha256:f74695e683c6f9bfe6eb33a4065ed1780d8cd018328a414a7c38c219d2c74861",
}


def test_jsonl_events_normalize_to_backend_trace():
    events = backend_events.load_events(FIXTURE)
    trace = backend_events.normalize_events(
        events,
        compiler=COMPILER,
        source=SOURCE,
        tool_version="test",
    )

    fn = trace["functions"][0]
    cls = fn["regalloc"]["classes"][0]
    node_by_id = {node["ig_id"]: node for node in cls["nodes"]}
    decision_by_id = {decision["id"]: decision for decision in cls["color_decisions"]}
    registers = cls["registers"]
    first_pass = fn["pcode"]["passes"][0]
    first_instruction = first_pass["instructions"][0]
    first_edge = cls["edges"][0]
    first_decision = cls["color_decisions"][0]
    frame = fn["frame"]

    assert trace["schema_version"] == backend_schema.SCHEMA_VERSION
    assert trace["struct_map"]["schema_version"] == backend_schema.STRUCT_MAP_SCHEMA_VERSION
    assert fn["name"] == "test_fn"
    assert first_instruction["id"] == "p0"
    assert registers["allocatable"] == [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 31, 30, 29, 28, 27]
    assert registers["initial_volatile"] == [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    assert registers["fixed"] == [
        {"phys": 1, "reason": "stack_pointer"},
        {"phys": 2, "reason": "toc"},
    ]
    assert registers["precolored"] == [
        {"ig_id": 3, "phys": 3, "reason": "incoming_arg"},
    ]
    assert registers["model_boundary"] == [
        {"name": "LR", "reason": "outside-v1-allocator-facts"},
    ]
    assert [node["ig_id"] for node in cls["nodes"]] == [32, 33, 40]
    assert cls["edges"] == [
        {
            "a": 32,
            "b": 33,
            "kind": "interference",
            "confidence": "observed",
            "provenance": "interferencegraph",
        }
    ]
    assert first_edge["a"] in node_by_id
    assert first_edge["b"] in node_by_id
    broken = copy.deepcopy(trace)
    broken["functions"][0]["regalloc"]["classes"][0]["edges"][0]["b"] = 999
    assert "test_fn:gpr edge references missing node 999" in backend_schema.validate_backend_trace(broken)
    assert cls["coalesce"]["mappings"][0]["alias"] == 40
    assert cls["coalesce"]["mappings"][0]["root"] == 32
    assert cls["simplify_order"] == [33, 32]
    assert cls["select_order"] == [33, 32]
    assert node_by_id[40]["color_status"] == "coalesced_alias"
    assert node_by_id[40]["coalesced_into"] == 32
    assert cls["simplify_order"]
    assert cls["select_order"]
    for ig_id in cls["select_order"]:
        node = node_by_id[ig_id]
        if node["color_status"] == "colored":
            assert cls["simplify_order"][node["simplify_order"]] == ig_id
            assert cls["select_order"][node["select_order"]] == ig_id
    assert decision_by_id["gpr-c0"]["blocked_candidates"][0]["holder_ig_id"] == 33
    assert first_decision["blocked_candidates"][0]["holder_ig_id"] == 33
    assert first_decision["candidate_phys_ordered"] == [31, 30]
    assert first_decision["provenance"] == "colorgraph"
    assert frame["base_size_bytes"] == 32
    assert frame["call_args_size_bytes"] == 16
    assert frame["objects"] == [
        {
            "area": "locals",
            "name": "tmp_a",
            "stack_offset": -8,
            "size": 4,
            "type": "s32",
            "confidence": "observed",
            "provenance": "frame_locals",
        },
        {
            "area": "arguments",
            "name": "arg_slot",
            "stack_offset": 8,
            "size": 4,
            "type": "s32",
            "confidence": "observed",
            "provenance": "frame_arguments",
        },
    ]
    assert frame["source_stage"] == "final_scheduler"
    assert backend_schema.validate_backend_trace(trace) == []


def test_event_normalizer_dispatches_exact_versions_without_changing_v1() -> None:
    events = backend_events.load_events(FIXTURE)
    explicit = backend_events.normalize_events(
        events,
        compiler=COMPILER,
        source=SOURCE,
        tool_version="test",
        schema_version=backend_schema.SCHEMA_VERSION_V1,
    )
    implicit = backend_events.normalize_events(
        events,
        compiler=COMPILER,
        source=SOURCE,
        tool_version="test",
    )
    assert explicit == implicit

    with pytest.raises(ValueError, match="proof-bearing v2 assembler"):
        backend_events.normalize_events(
            events,
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
            schema_version=backend_schema.SCHEMA_VERSION_V2,
        )
    with pytest.raises(ValueError, match="unsupported backend trace schema"):
        backend_events.normalize_events(
            events,
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
            schema_version="mwcc-retro-backend-trace.v3",
        )


def test_marker_only_events_do_not_normalize_to_complete_trace():
    with pytest.raises(ValueError, match="backend trace has no allocator classes"):
        backend_events.normalize_events(
            [
                {"event": "function_start", "name": "test_fn"},
                {"event": "backend_marker", "name": "codegen_start"},
            ],
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_pcode_normalization_preserves_exact_raw_operand_inventory():
    events = backend_events.load_events(FIXTURE)
    event = next(row for row in events if row.get("event") == "pcode_instruction")
    raw = bytes.fromhex("000222000000000000000000")
    event.update(
        {
            "opcode_id": 63,
            "arg_count": 1,
            "runtime_address": 0x700000,
            "source_stage": "allocator_input",
            "operand_lineage_inventory": [
                {
                    "operand_index": 0,
                    "raw_arg_kind_id": 0,
                    "raw_register_flags": 2,
                    "raw_register_value": 34,
                    "raw_payload_hex": raw.hex(),
                    "raw_payload_sha256": hashlib.sha256(raw).hexdigest(),
                }
            ],
        }
    )

    trace = backend_events.normalize_events(
        events, compiler=COMPILER, source=SOURCE, tool_version="test"
    )
    instruction = trace["functions"][0]["pcode"]["passes"][0]["instructions"][0]

    assert instruction["opcode_id"] == 63
    assert instruction["arg_count"] == 1
    assert instruction["runtime_address"] == 0x700000
    assert instruction["source_stage"] == "allocator_input"
    assert instruction["operand_lineage_inventory"] == event[
        "operand_lineage_inventory"
    ]


def test_allocator_event_before_regclass_is_rejected():
    events = backend_events.load_events(FIXTURE)
    regclass_index = next(i for i, event in enumerate(events) if event["event"] == "regclass")
    node_index = next(i for i, event in enumerate(events) if event["event"] == "node")
    events[regclass_index], events[node_index] = events[node_index], events[regclass_index]

    with pytest.raises(ValueError, match="regclass must precede node"):
        backend_events.normalize_events(
            events,
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_allocator_event_with_conflicting_class_identifiers_is_rejected():
    events = backend_events.load_events(FIXTURE)
    regclass_index = next(i for i, event in enumerate(events) if event["event"] == "regclass")
    events.insert(
        regclass_index + 1,
        {
            "event": "regclass",
            "class_id": 999,
            "class_name": "fpr",
            "registers": {
                "physical_count": 32,
                "allocatable": [1],
                "initial_volatile": [1],
                "reserved": [],
                "fixed": [],
                "precolored": [],
                "nonvolatile_dispense_order": [31],
                "model_boundary": [{"name": "FPSCR", "reason": "outside-v1-allocator-facts"}],
            },
        },
    )
    edge = next(event for event in events if event["event"] == "edge")
    edge["class_id"] = 999

    with pytest.raises(ValueError, match="class_name and class_id refer to different classes"):
        backend_events.normalize_events(
            events,
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_coalesced_alias_inherits_later_root_assignment_when_root_phys_is_null():
    events = backend_events.load_events(FIXTURE)
    mapping = next(event for event in events if event["event"] == "coalesce_mapping")
    mapping["root_phys"] = None

    trace = backend_events.normalize_events(
        events,
        compiler=COMPILER,
        source=SOURCE,
        tool_version="test",
    )

    cls = trace["functions"][0]["regalloc"]["classes"][0]
    nodes = {node["ig_id"]: node for node in cls["nodes"]}
    assert nodes[40]["color_status"] == "coalesced_alias"
    assert nodes[40]["assigned_phys"] == 31
    assert nodes[40]["coalesced_into"] == 32
    assert backend_schema.validate_backend_trace(trace) == []


def test_spill_color_decision_marks_node_spilled():
    events = backend_events.load_events(FIXTURE)
    first_decision = next(
        event for event in events
        if event.get("event") == "color_decision" and event.get("id") == "gpr-c1"
    )
    first_decision["assigned_phys"] = None
    first_decision["available_phys_ordered"] = []
    first_decision["candidate_phys_ordered"] = []
    first_decision["chosen_source"] = "spill"
    first_decision["tie_rule"] = "none_spill"
    first_decision["decision_rule"] = "spill_no_available_color"
    first_decision["spill"] = {"spilled": True, "reason": "no_available_color"}

    trace = backend_events.normalize_events(
        events,
        compiler=COMPILER,
        source=SOURCE,
        tool_version="test",
    )

    cls = trace["functions"][0]["regalloc"]["classes"][0]
    nodes = {node["ig_id"]: node for node in cls["nodes"]}
    node = nodes[33]
    assert node["color_status"] == "spilled"
    assert node["assigned_phys"] is None
    assert node["spill"] == {"spilled": True, "reason": "no_available_color"}
    assert node["color_decision_ref"] == "gpr-c1"
    assert backend_schema.validate_backend_trace(trace) == []


def test_load_events_reports_invalid_json_line_number(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"event": "function_start"}\n{"event":\n')

    with pytest.raises(ValueError, match="event line 2 invalid JSON: Expecting value"):
        backend_events.load_events(path)


def test_v2_object_binding_collection_order_is_canonical() -> None:
    payload = {
        "lifecycle_events": [{"sequence": 1}, {"sequence": 0}],
        "objects": [
            {
                "runtime_address": 2,
                "allocation_generation": 1,
                "areas": ["spill-owned", "locals"],
                "stage_snapshots": [
                    {"stage": "final_scheduler"},
                    {"stage": "colorgraph_return"},
                ],
            },
            {
                "runtime_address": 1,
                "allocation_generation": 2,
                "areas": [],
                "stage_snapshots": [],
            },
        ],
        "virtual_bindings": [
            {
                "object_id": "obj-1",
                "class_id": 0,
                "virtual_kind": "r",
                "virtual": 2,
                "ig_id": 2,
                "ignode_runtime_address": 4,
            },
            {
                "object_id": "obj-0",
                "class_id": 0,
                "virtual_kind": "r",
                "virtual": 1,
                "ig_id": 1,
                "ignode_runtime_address": 3,
            },
        ],
        "frame_bindings": [],
        "pcode_instructions": [],
        "pcode_occurrences": [
            {"pcode_event_sequence": 2, "pcode_id": "pc-0", "operand_index": 1},
            {"pcode_event_sequence": 1, "pcode_id": "pc-0", "operand_index": 0},
        ],
        "pcode_operand_lineage_events": [],
        "source_bindings": [],
        "source_capture": None,
        "coverage": {
            "ig_classes": ["fpr", "gpr"],
            "frame_areas": ["temps", "arguments", "locals"],
            "errors": ["z", "a"],
        },
        "lifetime_proof": {
            "allocation_sites": [
                {"entity_kind": "pcode", "address": 2, "site_id": "b"},
                {"entity_kind": "objobject", "address": 1, "site_id": "a"},
            ],
            "free_sites": [],
            "operand_rewrite_sites": [],
            "operand_mutation_sites": [],
            "code_emission_sites": [],
            "operand_rules": [
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
                    "state_rules": [
                        {
                            "capture_stage": "code_emission",
                            "register_flags_mask": 0xFF,
                            "register_flags_value": 2,
                            "register_value_min": 0,
                            "register_value_max": 31,
                            "allocation_state": "physical",
                        },
                        {
                            "capture_stage": "allocator_input",
                            "register_flags_mask": 0xFF,
                            "register_flags_value": 2,
                            "register_value_min": 32,
                            "register_value_max": 0xFFFF,
                            "allocation_state": "virtual",
                        },
                    ],
                },
                {
                    "opcode_id": 63,
                    "descriptor_index": 0,
                    "descriptor_source": "variadic-tail",
                    "format_code": None,
                    "expansion": {"kind": "remaining", "count": None},
                    "raw_arg_kind_id": 0,
                    "role": None,
                    "role_rules": [
                        {
                            "register_flags_mask": 1,
                            "register_flags_value": 1,
                            "role": "use",
                        },
                        {
                            "register_flags_mask": 1,
                            "register_flags_value": 0,
                            "role": "def",
                        },
                    ],
                    "register_form": "gpr",
                    "class_id": 0,
                    "virtual_kind": "r",
                    "state_rules": [],
                },
            ],
            "opcode_table": [],
        },
    }

    forward = backend_events.canonicalize_v2_object_bindings(payload)
    reverse = backend_events.canonicalize_v2_object_bindings(
        {
            **payload,
            "lifecycle_events": list(reversed(payload["lifecycle_events"])),
            "objects": list(reversed(payload["objects"])),
            "virtual_bindings": list(reversed(payload["virtual_bindings"])),
            "pcode_occurrences": list(reversed(payload["pcode_occurrences"])),
            "lifetime_proof": {
                **payload["lifetime_proof"],
                "operand_rules": [
                    {
                        **row,
                        "role_rules": list(reversed(row["role_rules"])),
                        "state_rules": list(reversed(row["state_rules"])),
                    }
                    for row in reversed(payload["lifetime_proof"]["operand_rules"])
                ],
            },
        }
    )

    assert forward == reverse
    assert [row["sequence"] for row in forward["lifecycle_events"]] == [0, 1]
    assert [row["runtime_address"] for row in forward["objects"]] == [1, 2]
    assert forward["objects"][1]["areas"] == ["locals", "spill-owned"]
    assert forward["coverage"]["ig_classes"] == ["gpr", "fpr"]
    assert forward["coverage"]["frame_areas"] == ["arguments", "locals", "temps"]
    assert forward["coverage"]["errors"] == ["a", "z"]
    descriptors = forward["lifetime_proof"]["operand_rules"]
    assert [(row["opcode_id"], row["descriptor_index"]) for row in descriptors] == [
        (63, 0),
        (63, 1),
    ]
    assert [row["role"] for row in descriptors[0]["role_rules"]] == ["def", "use"]
    assert [
        row["capture_stage"] for row in descriptors[1]["state_rules"]
    ] == ["allocator_input", "code_emission"]
