import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_frame_state  # noqa: E402


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
            source_stage="codegen_end",
        )

    mem.u32(0x700000, 0x1234)
    with pytest.raises(ValueError, match="invalid locals frame object pointer"):
        backend_frame_state.snapshot_frame_state(
            mem.read_u32,
            mem.read_s32,
            mem.read_cstr,
            list_vas={"locals": 0x700000, "arguments": 0x700004, "temps": 0x700008},
            frame_base_size_va=0x70000C,
            frame_call_args_size_va=0x700010,
            source_stage="codegen_end",
        )
