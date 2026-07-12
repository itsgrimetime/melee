import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_frame_state  # noqa: E402

OBJECT_OFFSETS = backend_frame_state.backend_object_snapshot.ObjObjectOffsets(0x0A, 0x0E, 0x02, 0x2A)
LIST_OFFSETS = backend_frame_state.backend_object_snapshot.FrameListOffsets(0x00, 0x04)
CAPTURE_LAYOUT_KWARGS = {
    "object_offsets": OBJECT_OFFSETS,
    "list_offsets": LIST_OFFSETS,
    "name_record_text_offset": 0x0A,
}


class Memory:
    def __init__(self) -> None:
        self._u32 = {}
        self._s32 = {}
        self._cstr = {}

    def u32(self, addr: int, value: int) -> None:
        self._u32[addr] = value

    def s32(self, addr: int, value: int) -> None:
        self._s32[addr] = value

    def cstr(self, addr: int, value: str) -> None:
        self._cstr[addr] = value

    def read_u32(self, addr: int) -> int:
        return self._u32[addr]

    def read_s32(self, addr: int) -> int:
        return self._s32[addr]

    def read_cstr(self, addr: int, limit: int = 96) -> str:
        del limit
        return self._cstr[addr]


def add_frame_object(
    mem: Memory,
    *,
    list_node: int,
    next_node: int = 0,
    obj: int,
    name_record: int,
    name: str,
    stack_offset: int,
    type_ptr: int,
    size: int,
) -> None:
    mem.u32(list_node + 0x00, next_node)
    mem.u32(list_node + 0x04, obj)
    mem.u32(obj + 0x0A, name_record)
    mem.cstr(name_record + 0x0A, name)
    mem.u32(obj + 0x0E, type_ptr)
    mem.s32(obj + 0x2A, stack_offset)
    mem.s32(type_ptr + 0x02, size)


def test_snapshot_frame_state_emits_stack_local_map_event() -> None:
    mem = Memory()
    mem.u32(0x700000, 0x710000)
    mem.u32(0x700004, 0x720000)
    mem.u32(0x700008, 0)
    mem.s32(0x70000C, 32)
    mem.s32(0x700010, 16)
    add_frame_object(
        mem,
        list_node=0x710000,
        obj=0x711000,
        name_record=0x712000,
        name="tmp_a",
        stack_offset=-8,
        type_ptr=0x713000,
        size=4,
    )
    add_frame_object(
        mem,
        list_node=0x720000,
        obj=0x721000,
        name_record=0x722000,
        name="arg_slot",
        stack_offset=8,
        type_ptr=0x723000,
        size=4,
    )

    event = backend_frame_state.snapshot_frame_state(
        mem.read_u32,
        mem.read_s32,
        mem.read_cstr,
        list_vas={"locals": 0x700000, "arguments": 0x700004, "temps": 0x700008},
        frame_base_size_va=0x70000C,
        frame_call_args_size_va=0x700010,
        **CAPTURE_LAYOUT_KWARGS,
        source_stage="final_scheduler",
    )

    assert event == {
        "event": "frame_state",
        "source_stage": "final_scheduler",
        "provenance": "frame_locals",
        "base_size_bytes": 32,
        "call_args_size_bytes": 16,
        "objects": [
            {
                "area": "locals",
                "name": "tmp_a",
                "stack_offset": -8,
                "size": 4,
                "type": "type@0x713000",
                "confidence": "observed",
                "provenance": "frame_locals",
            },
            {
                "area": "arguments",
                "name": "arg_slot",
                "stack_offset": 8,
                "size": 4,
                "type": "type@0x723000",
                "confidence": "observed",
                "provenance": "frame_arguments",
            },
        ],
    }


def test_snapshot_frame_state_names_invalid_name_records_by_area_and_offset() -> None:
    mem = Memory()
    mem.u32(0x700000, 0)
    mem.u32(0x700004, 0x720000)
    mem.u32(0x700008, 0)
    mem.s32(0x70000C, 32)
    mem.s32(0x700010, 16)
    mem.u32(0x720000 + 0x00, 0)
    mem.u32(0x720000 + 0x04, 0x721000)
    mem.u32(0x721000 + 0x0A, 0x1234)
    mem.u32(0x721000 + 0x0E, 0x723000)
    mem.s32(0x721000 + 0x2A, 4)
    mem.s32(0x723000 + 0x02, 4)

    event = backend_frame_state.snapshot_frame_state(
        mem.read_u32,
        mem.read_s32,
        mem.read_cstr,
        list_vas={"locals": 0x700000, "arguments": 0x700004, "temps": 0x700008},
        frame_base_size_va=0x70000C,
        frame_call_args_size_va=0x700010,
        **CAPTURE_LAYOUT_KWARGS,
        source_stage="final_scheduler",
    )

    assert event["objects"] == [
        {
            "area": "arguments",
            "name": "arguments_slot_4",
            "stack_offset": 4,
            "size": 4,
            "type": "type@0x723000",
            "confidence": "observed-unnamed",
            "provenance": "frame_arguments",
        }
    ]


def test_snapshot_frame_state_accepts_static_image_type_pointers() -> None:
    mem = Memory()
    mem.u32(0x700000, 0x710000)
    mem.u32(0x700004, 0)
    mem.u32(0x700008, 0)
    mem.s32(0x70000C, 32)
    mem.s32(0x700010, 16)
    add_frame_object(
        mem,
        list_node=0x710000,
        obj=0x711000,
        name_record=0x712000,
        name="row_child",
        stack_offset=0x44,
        type_ptr=0x55F5F0,
        size=4,
    )

    event = backend_frame_state.snapshot_frame_state(
        mem.read_u32,
        mem.read_s32,
        mem.read_cstr,
        list_vas={"locals": 0x700000, "arguments": 0x700004, "temps": 0x700008},
        frame_base_size_va=0x70000C,
        frame_call_args_size_va=0x700010,
        **CAPTURE_LAYOUT_KWARGS,
        source_stage="final_scheduler",
    )

    assert event["objects"] == [
        {
            "area": "locals",
            "name": "row_child",
            "stack_offset": 0x44,
            "size": 4,
            "type": "type@0x55f5f0",
            "confidence": "observed",
            "provenance": "frame_locals",
        }
    ]


def test_snapshot_probe_frame_state_emits_map_probe_evidence_shape() -> None:
    mem = Memory()
    mem.u32(0x700000, 0x710000)
    mem.u32(0x700004, 0x720000)
    mem.u32(0x700008, 0)
    mem.s32(0x70000C, 32)
    mem.s32(0x700010, 16)
    add_frame_object(
        mem,
        list_node=0x710000,
        obj=0x711000,
        name_record=0x712000,
        name="tmp_a",
        stack_offset=-8,
        type_ptr=0x55F5F0,
        size=4,
    )
    add_frame_object(
        mem,
        list_node=0x720000,
        obj=0x721000,
        name_record=0x722000,
        name="arg_slot",
        stack_offset=8,
        type_ptr=0x723000,
        size=4,
    )

    frame = backend_frame_state.snapshot_probe_frame_state(
        mem.read_u32,
        mem.read_s32,
        mem.read_cstr,
        list_vas={"locals": 0x700000, "arguments": 0x700004, "temps": 0x700008},
        frame_base_size_va=0x70000C,
        frame_call_args_size_va=0x700010,
        **CAPTURE_LAYOUT_KWARGS,
    )

    assert frame == {
        "locals": {
            "va": 0x700000,
            "head": 0x710000,
            "objects_sample": [
                {
                    "node": 0x710000,
                    "next": 0,
                    "object": 0x711000,
                    "name_ptr": 0x71200A,
                    "name": "tmp_a",
                    "stack_offset": -8,
                    "type": 0x55F5F0,
                    "size": 4,
                }
            ],
        },
        "arguments": {
            "va": 0x700004,
            "head": 0x720000,
            "objects_sample": [
                {
                    "node": 0x720000,
                    "next": 0,
                    "object": 0x721000,
                    "name_ptr": 0x72200A,
                    "name": "arg_slot",
                    "stack_offset": 8,
                    "type": 0x723000,
                    "size": 4,
                }
            ],
        },
        "temps": {"va": 0x700008, "head": 0, "objects_sample": []},
        "frame_base_size": {"va": 0x70000C, "s32": 32},
        "frame_call_args_size": {"va": 0x700010, "s32": 16},
    }


def test_snapshot_frame_state_rejects_cycles_and_bad_pointers() -> None:
    mem = Memory()
    mem.u32(0x700000, 0x710000)
    mem.u32(0x700004, 0)
    mem.u32(0x700008, 0)
    mem.s32(0x70000C, 32)
    mem.s32(0x700010, 16)
    add_frame_object(
        mem,
        list_node=0x710000,
        next_node=0x710000,
        obj=0x711000,
        name_record=0x712000,
        name="tmp_a",
        stack_offset=-8,
        type_ptr=0x713000,
        size=4,
    )

    with pytest.raises(ValueError, match="cycle in locals frame object list"):
        backend_frame_state.snapshot_frame_state(
            mem.read_u32,
            mem.read_s32,
            mem.read_cstr,
            list_vas={"locals": 0x700000, "arguments": 0x700004, "temps": 0x700008},
            frame_base_size_va=0x70000C,
            frame_call_args_size_va=0x700010,
            **CAPTURE_LAYOUT_KWARGS,
            source_stage="codegen_end",
        )


def test_frame_row_retains_raw_object_pointer_snapshot_and_stack_inputs() -> None:
    mem = Memory()
    mem.u32(0x700000, 0x710000)
    mem.s32(0x70000C, 84)
    mem.s32(0x700010, 8)
    add_frame_object(
        mem,
        list_node=0x710000,
        obj=0x711000,
        name_record=0x712000,
        name="tmp_a",
        stack_offset=-12,
        type_ptr=0x713000,
        size=4,
    )

    event = backend_frame_state.snapshot_frame_state(
        mem.read_u32,
        mem.read_s32,
        mem.read_cstr,
        list_vas={"locals": 0x700000},
        frame_base_size_va=0x70000C,
        frame_call_args_size_va=0x700010,
        **CAPTURE_LAYOUT_KWARGS,
        source_stage="final_scheduler",
        lifecycle_sequence=11,
        generation_for=lambda kind, ptr: (4 if (kind, ptr) == ("objobject", 0x711000) else None),
    )

    row = event["objects"][0]
    assert row["list_node_runtime_address"] == 0x710000
    assert row["objobject_ptr"] == 0x711000
    assert row["raw_object_stack_offset"] == -12
    assert row["frame_base_size"] == 84
    assert row["frame_call_args_size"] == 8
    assert row["final_r1_offset"] == 80
    assert row["frame_binding_confidence"] == "derived-unique"
    assert row["object_snapshot"] == {
        "stage": "final_scheduler",
        "runtime_address": 0x711000,
        "allocation_generation": 4,
        "lifecycle_sequence_at_capture": 11,
        "name_record_pointer": 0x712000,
        "type_pointer": 0x713000,
        "type_size": 4,
        "readable": True,
    }
    assert event["object_binding_capabilities"] == []


def test_frame_positive_object_without_active_generation_fails_closed() -> None:
    mem = Memory()
    mem.u32(0x700000, 0x710000)
    mem.s32(0x70000C, 84)
    mem.s32(0x700010, 8)
    add_frame_object(
        mem,
        list_node=0x710000,
        obj=0x711000,
        name_record=0x712000,
        name="tmp_a",
        stack_offset=-12,
        type_ptr=0x713000,
        size=4,
    )

    with pytest.raises(ValueError, match="no active ObjObject generation"):
        backend_frame_state.snapshot_frame_state(
            mem.read_u32,
            mem.read_s32,
            mem.read_cstr,
            list_vas={"locals": 0x700000},
            frame_base_size_va=0x70000C,
            frame_call_args_size_va=0x700010,
            **CAPTURE_LAYOUT_KWARGS,
            source_stage="final_scheduler",
            lifecycle_sequence=11,
            generation_for=lambda _kind, _ptr: None,
        )


def test_frame_retains_controlled_unreadable_positive_snapshot() -> None:
    mem = Memory()
    mem.u32(0x700000, 0x710000)
    mem.u32(0x710000, 0)
    mem.u32(0x710004, 0x711000)
    mem.s32(0x70000C, 84)
    mem.s32(0x700010, 8)
    mem.s32(0x71102A, -12)

    event = backend_frame_state.snapshot_frame_state(
        mem.read_u32,
        mem.read_s32,
        mem.read_cstr,
        list_vas={"locals": 0x700000},
        frame_base_size_va=0x70000C,
        frame_call_args_size_va=0x700010,
        **CAPTURE_LAYOUT_KWARGS,
        source_stage="final_scheduler",
        lifecycle_sequence=11,
        generation_for=lambda _kind, _ptr: 4,
    )

    row = event["objects"][0]
    assert row["objobject_ptr"] == 0x711000
    assert row["raw_object_stack_offset"] == -12
    assert row["object_snapshot"]["readable"] is False
    assert row["object_snapshot"]["name_record_pointer"] is None
    assert row["confidence"] == "observed-unnamed"
    assert event["object_binding_capabilities"] == []


def test_lifecycle_aware_frame_capture_requires_final_scheduler_stage() -> None:
    mem = Memory()
    mem.u32(0x700000, 0)
    mem.s32(0x70000C, 84)
    mem.s32(0x700010, 8)

    with pytest.raises(ValueError, match="requires final_scheduler"):
        backend_frame_state.snapshot_frame_state(
            mem.read_u32,
            mem.read_s32,
            mem.read_cstr,
            list_vas={"locals": 0x700000},
            frame_base_size_va=0x70000C,
            frame_call_args_size_va=0x700010,
            **CAPTURE_LAYOUT_KWARGS,
            source_stage="codegen_end",
            lifecycle_sequence=11,
            generation_for=lambda _kind, _ptr: 4,
        )


def test_frame_late_generation_failure_carries_positive_prefix_facts() -> None:
    mem = Memory()
    mem.u32(0x700000, 0x710000)
    mem.s32(0x70000C, 84)
    mem.s32(0x700010, 8)
    add_frame_object(
        mem,
        list_node=0x710000,
        next_node=0x720000,
        obj=0x711000,
        name_record=0x712000,
        name="first",
        stack_offset=-12,
        type_ptr=0x713000,
        size=4,
    )
    add_frame_object(
        mem,
        list_node=0x720000,
        obj=0x721000,
        name_record=0x722000,
        name="second",
        stack_offset=-8,
        type_ptr=0x723000,
        size=4,
    )

    with pytest.raises(
        backend_frame_state.PartialObjectCaptureError,
        match="no active ObjObject generation",
    ) as caught:
        backend_frame_state.snapshot_frame_state(
            mem.read_u32,
            mem.read_s32,
            mem.read_cstr,
            list_vas={"locals": 0x700000},
            frame_base_size_va=0x70000C,
            frame_call_args_size_va=0x700010,
            **CAPTURE_LAYOUT_KWARGS,
            source_stage="final_scheduler",
            lifecycle_sequence=11,
            generation_for=lambda _kind, ptr: 4 if ptr == 0x711000 else None,
        )

    facts = caught.value.partial_facts
    assert [fact["event"] for fact in facts] == [
        "objobject_snapshot",
        "object_frame_binding",
    ]
    assert facts[1]["objobject_ptr"] == 0x711000

    mem.u32(0x700000, 0x1234)
    with pytest.raises(ValueError, match="invalid locals frame object pointer"):
        backend_frame_state.snapshot_frame_state(
            mem.read_u32,
            mem.read_s32,
            mem.read_cstr,
            list_vas={"locals": 0x700000, "arguments": 0x700004, "temps": 0x700008},
            frame_base_size_va=0x70000C,
            frame_call_args_size_va=0x700010,
            **CAPTURE_LAYOUT_KWARGS,
            source_stage="codegen_end",
        )
