import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_events, backend_pcode_snapshot  # noqa: E402

COMPILER = {"family": "MWCC", "version": "GC/1.2.5n", "retail": True}
SOURCE = {
    "tu": "src/melee/test/unit.c",
    "function": "pcode_fn",
    "mwcc_command": "test mwcc command pcode-snapshot pcode_fn",
    "mwcc_command_hash": "sha256:4a2bdf569da6d14a2c4b461d6b4f4bb26c0fc0cfc18bb3be34a538b50e4e48bc",
}


class Memory:
    def __init__(self) -> None:
        self._u32 = {}
        self._s16 = {}

    def u32(self, addr: int, value: int) -> None:
        self._u32[addr] = value

    def s16(self, addr: int, value: int) -> None:
        self._s16[addr] = value

    def read_u32(self, addr: int) -> int:
        return self._u32[addr]

    def read_s16(self, addr: int) -> int:
        return self._s16[addr]


def add_block(
    mem: Memory,
    *,
    ptr: int,
    next_ptr: int = 0,
    first_pcode: int = 0,
    block_index: int = 0,
) -> None:
    mem.u32(ptr + 0x00, next_ptr)
    mem.u32(ptr + 0x14, first_pcode)
    mem.u32(ptr + 0x1C, block_index)


def add_pcode(
    mem: Memory,
    *,
    ptr: int,
    next_ptr: int = 0,
    opcode: int = 0,
    arg_count: int = 0,
) -> None:
    mem.u32(ptr + 0x00, next_ptr)
    mem.s16(ptr + 0x14, opcode)
    mem.s16(ptr + 0x1A, arg_count)


def test_pcode_snapshot_events_normalize_as_partial_pcode_then_fail_full_trace(
    tmp_path,
) -> None:
    mem = Memory()
    add_block(mem, ptr=0x600000, next_ptr=0x600040, first_pcode=0x610000, block_index=0)
    add_block(mem, ptr=0x600040, first_pcode=0x610080, block_index=1)
    add_pcode(mem, ptr=0x610000, next_ptr=0x610040, opcode=5, arg_count=2)
    add_pcode(mem, ptr=0x610040, opcode=6, arg_count=0)
    add_pcode(mem, ptr=0x610080, opcode=7, arg_count=1)

    events = backend_pcode_snapshot.snapshot_pcode_blocks(
        mem.read_u32,
        mem.read_s16,
        0x600000,
        pass_id="pcode_snapshot",
        pass_name="PCode Snapshot",
        opcode_names={5: "mr", 6: "addi", 7: "blr"},
        source_stage="pcode_pass_boundary",
    )

    assert [event["event"] for event in events] == [
        "block",
        "pcode_instruction",
        "pcode_instruction",
        "block",
        "pcode_instruction",
    ]
    assert events[0] == {
        "event": "block",
        "id": "B0",
        "order": 0,
        "succ": [],
        "pred": [],
        "labels": [],
        "source_stage": "pcode_pass_boundary",
        "retail_pcode_block": {"ptr": 0x600000, "next": 0x600040},
    }
    assert events[1]["id"] == "p0"
    assert events[1]["block_id"] == "B0"
    assert events[1]["opcode"] == "mr"
    assert events[1]["operands"] == ""
    assert events[1]["retail_pcode"]["arg_count"] == 2
    assert events[4]["id"] == "p2"
    assert events[4]["block_id"] == "B1"
    assert events[4]["normalized"] == "blr"

    events_path = tmp_path / "pcode-events.jsonl"
    events_path.write_text(
        "\n".join(
            __import__("json").dumps(event)
            for event in [
                {"event": "function_start", "name": "pcode_fn"},
                {"event": "backend_marker", "name": "pcode_pass_boundary"},
                *events,
            ]
        )
        + "\n"
    )
    loaded = backend_events.load_events(events_path)
    with pytest.raises(ValueError, match="backend trace has no allocator classes"):
        backend_events.normalize_events(
            loaded,
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )

@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda mem: mem.u32(0x600000 + 0x00, 0x600000),
            "cycle in PCode block list",
        ),
        (
            lambda mem: mem.u32(0x600000 + 0x14, 0x1234),
            "invalid first PCode pointer",
        ),
        (
            lambda mem: mem.s16(0x610000 + 0x1A, -1),
            "invalid arg_count -1",
        ),
        (
            lambda mem: mem.s16(0x610000 + 0x1A, 65),
            "invalid arg_count 65",
        ),
    ],
)
def test_pcode_snapshot_rejects_suspect_block_or_instruction_facts(
    mutate, match: str
) -> None:
    mem = Memory()
    block_head = 0x600000
    add_block(mem, ptr=block_head, first_pcode=0x610000, block_index=0)
    add_pcode(mem, ptr=0x610000, opcode=1)
    mutate(mem)

    with pytest.raises(ValueError, match=match):
        backend_pcode_snapshot.snapshot_pcode_blocks(
            mem.read_u32,
            mem.read_s16,
            block_head,
            pass_id="pcode_snapshot",
            pass_name="PCode Snapshot",
            opcode_names={1: "mr"},
            source_stage="pcode_pass_boundary",
        )


def test_pcode_snapshot_rejects_null_block_list_pointer() -> None:
    mem = Memory()

    with pytest.raises(ValueError, match="block list pointer is null"):
        backend_pcode_snapshot.snapshot_pcode_blocks(
            mem.read_u32,
            mem.read_s16,
            0,
            pass_id="pcode_snapshot",
            pass_name="PCode Snapshot",
            opcode_names={1: "mr"},
            source_stage="pcode_pass_boundary",
        )
