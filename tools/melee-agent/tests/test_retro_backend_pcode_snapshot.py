import hashlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import (  # noqa: E402
    backend_events,
    backend_onepass_trace_hook,
    backend_pcode_snapshot,
)

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

    def bytes(self, addr: int, value: bytes) -> None:
        for offset, byte in enumerate(value):
            self._u32[addr + offset] = byte

    def read_bytes(self, addr: int, size: int) -> bytes:
        return bytes(self._u32[addr + offset] for offset in range(size))


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


def add_pcode_arg(
    mem: Memory,
    *,
    pcode_ptr: int,
    index: int,
    kind: int,
    flags: int,
    payload: bytes,
) -> bytes:
    raw = bytes((kind, flags)) + payload.ljust(10, b"\0")
    mem.bytes(pcode_ptr + 0x1C + index * 0x0C, raw)
    return raw


def test_snapshot_pcode_emits_full_arg_inventory() -> None:
    mem = Memory()
    add_block(mem, ptr=0x600000, first_pcode=0x610000, block_index=0)
    add_pcode(mem, ptr=0x610000, opcode=62, arg_count=3)
    raw_args = [
        add_pcode_arg(
            mem,
            pcode_ptr=0x610000,
            index=0,
            kind=0,
            flags=1,
            payload=(67).to_bytes(2, "little"),
        ),
        add_pcode_arg(
            mem,
            pcode_ptr=0x610000,
            index=1,
            kind=0,
            flags=0,
            payload=(66).to_bytes(2, "little"),
        ),
        add_pcode_arg(
            mem,
            pcode_ptr=0x610000,
            index=2,
            kind=4,
            flags=0,
            payload=(7).to_bytes(4, "little", signed=True),
        ),
    ]

    events = backend_pcode_snapshot.snapshot_pcode_blocks(
        mem.read_u32,
        mem.read_s16,
        0x600000,
        read_bytes=mem.read_bytes,
        pass_id="pcode_snapshot",
        pass_name="PCode Snapshot",
        opcode_names={62: "addi"},
        source_stage="allocator_input",
    )

    row = next(event for event in events if event["event"] == "pcode_instruction")
    assert row["opcode_id"] == 62
    assert row["arg_count"] == 3
    assert row["runtime_address"] == 0x610000
    assert row["operand_lineage_inventory"] == [
        {
            "operand_index": index,
            "raw_arg_kind_id": raw[0],
            "raw_register_flags": raw[1],
            "raw_register_value": int.from_bytes(raw[2:4], "little"),
            "raw_payload_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_payload_hex": raw.hex(),
        }
        for index, raw in enumerate(raw_args)
    ]


class Lifecycle:
    def sequence_at_stop(self) -> int:
        return 12

    def generation(self, kind: str, ptr: int) -> int:
        assert kind == "pcode"
        assert ptr == 0x610000
        return 3


def test_emit_pcode_event_adds_exact_same_run_anchor() -> None:
    state = {"next_pcode_event_sequence": 7, "pcode_events": []}

    event = backend_onepass_trace_hook._emit_pcode_event(
        state,
        {"event": "operand_rewrite", "operand_index": 1},
        site_id="rewrite-register-operand-4",
        pcode_ptr=0x610000,
        lifecycle=Lifecycle(),
    )

    assert event == {
        "event": "operand_rewrite",
        "operand_index": 1,
        "pcode_event_sequence": 7,
        "instrumented_site_id": "rewrite-register-operand-4",
        "runtime_address": 0x610000,
        "allocation_generation": 3,
        "lifecycle_sequence_at_capture": 12,
    }
    assert state["pcode_events"] == [event]
    assert state["next_pcode_event_sequence"] == 8


def test_mutation_capture_is_atomic_when_output_snapshot_fails() -> None:
    state = {"next_pcode_event_sequence": 0, "pcode_events": []}

    with pytest.raises(ValueError, match="output unreadable"):
        backend_onepass_trace_hook._emit_pcode_mutation_event(
            state,
            site_id="rewrite-pcode-operands-1",
            mutation_kind="update",
            capture_inputs=lambda: [{"pcode_id": "pc-0"}],
            capture_outputs=lambda: (_ for _ in ()).throw(
                ValueError("output unreadable")
            ),
        )

    assert state == {"next_pcode_event_sequence": 0, "pcode_events": []}


def test_runtime_drops_capability_when_mutation_site_is_unhooked() -> None:
    proof = {
        "operand_rewrite_sites": [{"site_id": "rewrite-1"}],
        "operand_mutation_sites": [
            {"site_id": "mutation-1"},
            {"site_id": "mutation-2"},
        ],
        "code_emission_sites": [{"site_id": "emit-1"}],
    }
    coverage = backend_onepass_trace_hook._pcode_instrumentation_status(
        proof,
        hooked_site_ids={"rewrite-1", "mutation-1", "emit-1"},
        events=[],
        event_cap=64,
        dropped_events=0,
        truncated=False,
        errors=[],
    )

    assert coverage["operand_mutation_sites_expected"] == 2
    assert coverage["operand_mutation_sites_hooked"] == 1
    assert coverage["status"] == "partial"
    assert coverage["capabilities"] == []


def test_onepass_snapshot_forwards_full_raw_memory_reader() -> None:
    calls = []

    def snapshot_reader(read_u32, read_s16, block_head, **kwargs):
        calls.append((read_u32, read_s16, block_head, kwargs))
        return [{"event": "pcode_instruction"}]

    def read_u32(_addr):
        return 0

    def read_s16(_addr):
        return 0

    def read_bytes(_addr, size):
        return bytes(size)

    events = backend_onepass_trace_hook._capture_pcode_events(
        snapshot_reader,
        read_u32,
        read_s16,
        read_bytes,
        0x600000,
        pass_id="pcode_snapshot",
        pass_name="PCode Snapshot",
        opcode_names={62: "addi"},
        source_stage="allocator_input",
    )

    assert events == [{"event": "pcode_instruction"}]
    assert calls == [
        (
            read_u32,
            read_s16,
            0x600000,
            {
                "read_bytes": read_bytes,
                "pass_id": "pcode_snapshot",
                "pass_name": "PCode Snapshot",
                "opcode_names": {62: "addi"},
                "source_stage": "allocator_input",
            },
        )
    ]


def test_onepass_withholds_raw_arg_reader_until_layout_gate_passes() -> None:
    def read_bytes(_addr, size):
        return bytes(size)

    assert (
        backend_onepass_trace_hook._validated_pcode_raw_reader({}, read_bytes)
        is None
    )


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


def test_onepass_pcode_stage_failure_allows_later_stage_retry() -> None:
    state = {"pcode_captured": False, "warnings": []}
    attempts = []

    def fail(stage: str) -> None:
        attempts.append(stage)
        raise ValueError("invalid arg_count 31016")

    assert (
        backend_onepass_trace_hook._try_capture_pcode_stage(
            state,
            "pcode_pass_boundary",
            fail,
            fallback_stage="final_scheduler",
        )
        is False
    )
    assert state["pcode_captured"] is False
    assert attempts == ["pcode_pass_boundary"]
    assert state["warnings"] == [
        {
            "stage": "pcode_pass_boundary",
            "warning": (
                "PCode pcode_pass_boundary snapshot skipped; "
                "final_scheduler fallback will be tried: invalid arg_count 31016"
            ),
        }
    ]

    def succeed(stage: str) -> None:
        attempts.append(stage)
        state["pcode_captured"] = True

    assert (
        backend_onepass_trace_hook._try_capture_pcode_stage(
            state,
            "final_scheduler",
            succeed,
            fallback_stage="codegen_end",
        )
        is True
    )
    assert attempts == ["pcode_pass_boundary", "final_scheduler"]
    assert state["pcode_captured"] is True
