import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_schema, backend_trace_assembler  # noqa: E402

COMPILER = {"family": "MWCC", "version": "GC/1.2.5n", "retail": True}
SOURCE = {
    "tu": "src/melee/test/unit.c",
    "function": "candidate_fn",
    "mwcc_command": "test mwcc command candidate candidate_fn",
    "mwcc_command_hash": "sha256:d673911e77f8e9f1945c4c85d7908512517c76d9aee542551bbf918cddd8162b",
}


def _function_start() -> dict:
    return {"event": "function_start", "name": "candidate_fn"}


def _pcode_events() -> list[dict]:
    return [
        _function_start(),
        {"event": "backend_marker", "name": "pcode_pass_boundary"},
        {
            "event": "block",
            "id": "B0",
            "order": 0,
            "succ": [],
            "pred": [],
            "labels": [],
        },
        {
            "event": "pcode_instruction",
            "pass_id": "pcode_snapshot",
            "pass_name": "PCode Snapshot",
            "id": "p0",
            "block_id": "B0",
            "order": 0,
            "opcode": "mr",
            "operands": "",
            "normalized": "mr",
        },
    ]


def _regclass_event() -> dict:
    return {
        "event": "regclass",
        "class_name": "gpr",
        "class_id": 0,
        "registers": {
            "physical_count": 32,
            "allocatable": [0, 3, 4, 31],
            "initial_volatile": [0, 3, 4],
            "reserved": [1, 2],
            "fixed": [{"phys": 1, "reason": "stack_pointer"}],
            "precolored": [],
            "nonvolatile_dispense_order": [31],
            "model_boundary": [{"name": "LR", "reason": "outside-v1"}],
        },
        "non_allocatable_state": {"status": "model-boundary"},
    }


def _node(ig_id: int) -> dict:
    return {
        "event": "node",
        "class_name": "gpr",
        "class_id": 0,
        "ig_id": ig_id,
        "virtual": {"kind": "r", "number": ig_id},
        "first_def": {"status": "unavailable", "reason": "fixture"},
        "source_attribution": {"status": "unattributed", "confidence": "fixture"},
        "live": {"blocks": [], "intervals": [], "confidence": "fixture"},
        "degree": 1,
        "flags": [],
        "coalesce": {"root_ig_id": ig_id, "aliases": []},
        "simplify_order": None,
        "select_order": None,
        "assigned_phys": None,
        "spill": {"spilled": False, "reason": None},
        "color_status": "uncolored",
        "coalesced_into": None,
        "color_decision_ref": None,
    }


def _partial_decision() -> dict:
    return {
        "event": "color_decision",
        "class_name": "gpr",
        "class_id": 0,
        "id": "gpr-c0",
        "ig_id": 32,
        "iter": 0,
        "assigned_phys": 0,
        "node_state_before_select": {
            "status": "unavailable",
            "reason": "retail-post-colorgraph-only",
        },
        "reserved_or_precolored_filtered": [],
        "available_phys_ordered": [],
        "blocked_candidates": [],
        "candidate_phys_ordered": [0],
        "chosen_source": "observed-retail-assignment",
        "volatile_pool_before": [],
        "volatile_pool_after": [],
        "nonvolatile_dispense_before": {},
        "nonvolatile_dispense_after": {},
        "tie_rule": "unavailable-retail-post-colorgraph",
        "blocked_by": [],
        "decision_rule": "retail-post-colorgraph-observed-assignment",
        "confidence": "observed-partial",
        "provenance": "retail-colorgraph-return",
        "source_stage": "colorgraph_return",
    }


def _ig_events(include_partial: bool = True) -> list[dict]:
    events = [
        _function_start(),
        {"event": "backend_marker", "name": "codegen_start"},
        _regclass_event(),
        _node(32),
        _node(33),
        {
            "event": "edge",
            "class_name": "gpr",
            "class_id": 0,
            "a": 32,
            "b": 33,
        },
        {
            "event": "coalesce_mapping_empty",
            "class_name": "gpr",
            "class_id": 0,
        },
        {
            "event": "simplify_order",
            "class_name": "gpr",
            "class_id": 0,
            "order": [33, 32],
        },
        {
            "event": "select_order",
            "class_name": "gpr",
            "class_id": 0,
            "order": [33, 32],
        },
    ]
    if include_partial:
        events.append(_partial_decision())
    return events


def _frame_events() -> list[dict]:
    return [
        {
            "event": "frame_state",
            "function": "candidate_fn",
            "source_stage": "final_scheduler",
            "provenance": "frame_locals",
            "base_size_bytes": 16,
            "call_args_size_bytes": 0,
            "objects": [
                {
                    "area": "locals",
                    "name": "tmp",
                    "stack_offset": -4,
                    "size": 4,
                    "type": "s32",
                    "confidence": "observed",
                    "provenance": "frame_locals",
                }
            ],
        }
    ]


def _exact_decision(
    *,
    decision_id: str = "gpr-i0",
    ig_id: int = 32,
    iteration: int = 0,
    assigned_phys: int = 0,
) -> dict:
    return {
        "event": "color_decision",
        "class_name": "gpr",
        "class_id": 0,
        "id": decision_id,
        "ig_id": ig_id,
        "iter": iteration,
        "assigned_phys": assigned_phys,
        "node_state_before_select": {
            "precolored": False,
            "coalesced": False,
            "spill_marked": False,
            "rematerialized": False,
        },
        "reserved_or_precolored_filtered": [1, 2],
        "available_phys_ordered": [0, 3, 4],
        "blocked_candidates": [],
        "candidate_phys_ordered": [assigned_phys, *[phys for phys in [0, 3, 4] if phys != assigned_phys]],
        "chosen_source": "volatile_pool",
        "volatile_pool_before": [0, 3, 4],
        "volatile_pool_after": [3, 4],
        "nonvolatile_dispense_before": {"next": None, "remaining": []},
        "nonvolatile_dispense_after": {"consumed": None, "remaining": []},
        "tie_rule": "first_volatile_available",
        "blocked_by": [],
        "decision_rule": "lowest_available_or_nonvolatile_dispense",
        "confidence": "observed-internal",
        "provenance": "retail-colorgraph-internal",
        "source_stage": "colorgraph",
    }


def test_assemble_candidate_trace_replaces_matching_partial_decisions() -> None:
    trace = backend_trace_assembler.assemble_candidate_trace(
        pcode_events=_pcode_events(),
        ig_events=_ig_events(include_partial=True),
        frame_events=_frame_events(),
        colorgraph_events=[
            _function_start(),
            _exact_decision(decision_id="gpr-i0", ig_id=32, iteration=1, assigned_phys=0),
            _exact_decision(decision_id="gpr-i1", ig_id=33, iteration=0, assigned_phys=3),
        ],
        compiler=COMPILER,
        source=SOURCE,
        tool_version="test",
    )

    assert backend_schema.validate_backend_trace(trace) == []
    fn = trace["functions"][0]
    cls = fn["regalloc"]["classes"][0]
    nodes = {node["ig_id"]: node for node in cls["nodes"]}
    assert fn["pcode"]["passes"][0]["instructions"][0]["opcode"] == "mr"
    assert [decision["id"] for decision in cls["color_decisions"]] == ["gpr-i0", "gpr-i1"]
    assert nodes[32]["assigned_phys"] == 0
    assert nodes[32]["color_decision_ref"] == "gpr-i0"
    assert nodes[33]["assigned_phys"] == 3
    assert nodes[33]["color_decision_ref"] == "gpr-i1"


def test_assemble_candidate_trace_rejects_leftover_partial_decisions() -> None:
    with pytest.raises(ValueError, match="leftover partial color decisions"):
        backend_trace_assembler.assemble_candidate_trace(
            pcode_events=_pcode_events(),
            ig_events=_ig_events(include_partial=True),
            frame_events=_frame_events(),
            colorgraph_events=[_function_start()],
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_assemble_candidate_trace_rejects_mismatched_colorgraph_function() -> None:
    with pytest.raises(ValueError, match="colorgraph function_start mismatch"):
        backend_trace_assembler.assemble_candidate_trace(
            pcode_events=_pcode_events(),
            ig_events=_ig_events(include_partial=True),
            frame_events=_frame_events(),
            colorgraph_events=[{"event": "function_start", "name": "other_fn"}, _exact_decision()],
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_assemble_candidate_trace_rejects_exact_partial_assignment_disagreement() -> None:
    exact = _exact_decision()
    exact["assigned_phys"] = 3
    exact["candidate_phys_ordered"] = [0, 3, 4]

    with pytest.raises(ValueError, match="exact/partial assigned_phys mismatch"):
        backend_trace_assembler.assemble_candidate_trace(
            pcode_events=_pcode_events(),
            ig_events=_ig_events(include_partial=True),
            frame_events=_frame_events(),
            colorgraph_events=[_function_start(), exact],
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_assemble_candidate_trace_rejects_duplicate_exact_decisions() -> None:
    with pytest.raises(ValueError, match="duplicate exact color decision"):
        backend_trace_assembler.assemble_candidate_trace(
            pcode_events=_pcode_events(),
            ig_events=_ig_events(include_partial=True),
            frame_events=_frame_events(),
            colorgraph_events=[_function_start(), _exact_decision(), _exact_decision()],
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_assemble_candidate_trace_requires_frame_state() -> None:
    with pytest.raises(ValueError, match="candidate trace requires frame_state"):
        backend_trace_assembler.assemble_candidate_trace(
            pcode_events=_pcode_events(),
            ig_events=_ig_events(include_partial=False),
            frame_events=[],
            colorgraph_events=[],
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_frame_events_from_map_probe_payload_converts_probe_frame_shape() -> None:
    payload = {
        "events": [
            {
                "stage": "final_scheduler",
                "frame_state": {
                    "locals": {
                        "va": 0x587FB8,
                        "head": 0x710000,
                        "objects_sample": [
                            {
                                "node": 0x710000,
                                "next": 0,
                                "object": 0x711000,
                                "name": "tmp",
                                "stack_offset": -4,
                                "type": 0x712000,
                                "size": 4,
                            }
                        ],
                    },
                    "arguments": {"va": 0x58806C, "head": 0, "objects_sample": []},
                    "temps": {"va": 0x57FEC0, "head": 0, "objects_sample": []},
                    "frame_base_size": {"va": 0x5880CC, "s32": 16},
                    "frame_call_args_size": {"va": 0x58712C, "s32": 8},
                },
            }
        ]
    }

    assert backend_trace_assembler.frame_events_from_map_probe_payload(payload) == [
        {
            "event": "frame_state",
            "source_stage": "final_scheduler",
            "provenance": "backend-map-probe-frame_state",
            "base_size_bytes": 16,
            "call_args_size_bytes": 8,
            "objects": [
                {
                    "area": "locals",
                    "name": "tmp",
                    "stack_offset": -4,
                    "size": 4,
                    "type": "type@0x712000",
                    "confidence": "observed",
                    "provenance": "frame_locals",
                }
            ],
        }
    ]


def test_frame_events_from_map_probe_payload_rejects_incomplete_probe_frame() -> None:
    payload = {
        "events": [
            {
                "stage": "final_scheduler",
                "frame_state": {
                    "locals": {"va": 0x587FB8, "objects_sample": []},
                    "frame_base_size": {"va": 0x5880CC, "error": "bad read"},
                    "frame_call_args_size": {"va": 0x58712C, "s32": 8},
                },
            }
        ]
    }

    with pytest.raises(ValueError, match="missing frame_base_size"):
        backend_trace_assembler.frame_events_from_map_probe_payload(payload)


def test_frame_events_from_map_probe_payload_names_unnamed_slots_by_area_and_offset() -> None:
    payload = {
        "events": [
            {
                "stage": "final_scheduler",
                "frame_state": {
                    "arguments": {
                        "va": 0x58806C,
                        "head": 0x710000,
                        "objects_sample": [
                            {
                                "node": 0x710000,
                                "next": 0,
                                "object": 0x711000,
                                "name_ptr": 0,
                                "stack_offset": 4,
                                "type": 0x712000,
                                "size": 4,
                            }
                        ],
                    },
                    "frame_base_size": {"va": 0x5880CC, "s32": 0},
                    "frame_call_args_size": {"va": 0x58712C, "s32": 0},
                },
            }
        ]
    }

    [event] = backend_trace_assembler.frame_events_from_map_probe_payload(payload)

    assert event["objects"][0]["name"] == "arguments_slot_4"
    assert event["objects"][0]["confidence"] == "observed-unnamed"
