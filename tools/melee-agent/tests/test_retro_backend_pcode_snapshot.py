import hashlib
import sys
from collections.abc import Mapping
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


def _complete_coverage_proof():
    return {
        "operand_rewrite_sites": [{"site_id": "rewrite-1"}],
        "operand_mutation_sites": [{"site_id": "mutation-1"}],
        "code_emission_sites": [{"site_id": "emit-1"}],
    }


def _coverage_operand(
    *,
    kind=7,
    digest="a" * 64,
    parents=None,
):
    row = {
        "operand_index": 0,
        "operand_lineage_id": "ol-0",
        "raw_arg_kind_id": kind,
        "raw_payload_sha256": digest,
    }
    if parents is not None:
        row["parent_lineage_ids"] = parents
    return row


def _coverage_state(*, output=False):
    return {
        "pcode_id": "pc-0",
        "runtime_address": 0x610000,
        "allocation_generation": 3,
        "lifecycle_sequence_at_capture": 12,
        "opcode_id": 42,
        "arg_count": 1,
        "operands": [
            _coverage_operand(
                kind=8 if output else 7,
                digest=("b" if output else "a") * 64,
            )
        ],
    }


def _coverage_emission_snapshot():
    return {
        "stage": "code_emission",
        "lifecycle_sequence_at_capture": 12,
        "runtime_address": 0x610000,
        "allocation_generation": 3,
        "opcode_id": 42,
        "opcode": "ADDI",
        "arg_count": 1,
        "parsed_register_operands": [
            {
                "operand_index": 0,
                "role": "use",
                "class_id": 0,
                "raw_arg_kind_id": 8,
                "raw_register_flags": 0,
                "allocation_requirement": "fixed-physical",
                "operand_lineage_id": "ol-0",
                "virtual_kind": None,
                "virtual": None,
                "physical_register": 3,
            }
        ],
        "operand_lineage_inventory": [
            _coverage_operand(kind=8, digest="b" * 64)
        ],
    }


def _complete_coverage_events():
    return [
        {
            "event": "operand_rewrite",
            "pcode_event_sequence": 0,
            "instrumented_site_id": "rewrite-1",
            "pcode_id": "pc-0",
            "operand_index": 0,
            "operand_lineage_id": "ol-0",
            "role": "use",
            "class_id": 0,
            "class_name": "gpr",
            "virtual_kind": "r",
            "virtual": 67,
            "ig_id": 67,
            "allocated_physical": 3,
            "runtime_address": 0x610000,
            "allocation_generation": 3,
            "lifecycle_sequence_at_capture": 12,
            "source_stage": "allocator_operand_rewrite",
            "confidence": "observed",
        },
        {
            "event": "pcode_mutation",
            "pcode_event_sequence": 1,
            "instrumented_site_id": "mutation-1",
            "mutation_kind": "update",
            "inputs": [_coverage_state()],
            "outputs": [_coverage_state(output=True)],
        },
        {
            "event": "code_emission",
            "pcode_event_sequence": 2,
            "instrumented_site_id": "emit-1",
            "pcode_id": "pc-0",
            "runtime_address": 0x610000,
            "allocation_generation": 3,
            "lifecycle_sequence_at_capture": 12,
            "emission_snapshot": _coverage_emission_snapshot(),
            "code_ranges": [
                {
                    "start": 0,
                    "end_exclusive": 4,
                    "bytes": "7c000000",
                    "relocations": [
                        {
                            "offset_within_range": 0,
                            "relocation_type_id": 1,
                            "target_symbol_table_index": 2,
                            "target_symbol": "target",
                            "addend": 0,
                        }
                    ],
                    "machine_operand_mappings": [
                        {
                            "instruction_offset_within_range": 0,
                            "machine_operand_position": 0,
                            "machine_operand_key": "use:0",
                            "emission_pcode_operand_index": 0,
                            "operand_lineage_id": "ol-0",
                            "physical_register": 3,
                        }
                    ],
                }
            ],
        },
    ]


def _coverage_status(**overrides):
    values = {
        "proof": _complete_coverage_proof(),
        "hooked_site_ids": {"rewrite-1", "mutation-1", "emit-1"},
        "events": _complete_coverage_events(),
        "event_cap": 64,
        "dropped_events": 0,
        "truncated": False,
        "errors": [],
    }
    values.update(overrides)
    proof = values.pop("proof")
    return backend_onepass_trace_hook._pcode_instrumentation_status(
        proof, **values
    )


class _HostileMapping(Mapping):
    def __getitem__(self, key):
        raise RuntimeError("hostile nested mapping")

    def __iter__(self):
        raise RuntimeError("hostile nested mapping")

    def __len__(self):
        return 1


class _HostileList(list):
    def __iter__(self):
        raise RuntimeError("hostile nested list")


def test_runtime_marks_only_exact_complete_instrumentation_complete():
    coverage = _coverage_status()

    assert coverage["status"] == "complete"
    assert coverage["errors"] == []
    assert coverage["capabilities"] == []


def test_runtime_accepts_complete_zero_byte_emission_with_empty_code_ranges():
    events = _complete_coverage_events()
    events[2]["code_ranges"] = []

    coverage = _coverage_status(events=events)

    assert coverage["status"] == "complete"
    assert coverage["errors"] == []
    assert coverage["operand_rewrite_sites_expected"] == 1
    assert coverage["operand_rewrite_sites_hooked"] == 1
    assert coverage["operand_mutation_sites_expected"] == 1
    assert coverage["operand_mutation_sites_hooked"] == 1
    assert coverage["code_emission_sites_expected"] == 1
    assert coverage["code_emission_sites_hooked"] == 1
    assert coverage["first_event_sequence"] == 0
    assert coverage["last_event_sequence"] == 2
    assert coverage["capabilities"] == []


@pytest.mark.parametrize(
    ("code_ranges", "expected"),
    [
        ({}, "code_emission event 2 code_ranges must be list"),
        (
            [{}],
            "code_emission event 2 range 0 fields differ from exact schema",
        ),
    ],
)
def test_runtime_rejects_malformed_code_range_containers(
    code_ranges, expected
):
    events = _complete_coverage_events()
    events[2]["code_ranges"] = code_ranges

    coverage = _coverage_status(events=events)

    assert coverage["status"] == "partial"
    assert any(expected in error for error in coverage["errors"])
    assert coverage["capabilities"] == []


def test_runtime_fails_closed_on_hostile_nested_coverage_proof_site():
    proof = _complete_coverage_proof()
    proof["operand_rewrite_sites"][0] = _HostileMapping()

    coverage = _coverage_status(proof=proof)

    assert coverage["status"] == "partial"
    assert any(
        "PCode coverage proof could not be materialized" in error
        for error in coverage["errors"]
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda events: events.__setitem__(0, _HostileMapping()),
        lambda events: events[1]["inputs"].__setitem__(
            0, _HostileMapping()
        ),
        lambda events: events[2]["code_ranges"][0][
            "machine_operand_mappings"
        ].__setitem__(0, _HostileMapping()),
        lambda events: events[1].update(
            {"outputs": _HostileList(events[1]["outputs"])}
        ),
    ],
)
def test_runtime_fails_closed_on_hostile_nested_event_containers(mutate):
    events = _complete_coverage_events()
    mutate(events)

    coverage = _coverage_status(events=events)

    assert coverage["status"] == "partial"
    assert any(
        "PCode events could not be materialized" in error
        for error in coverage["errors"]
    )


def test_runtime_fails_closed_on_recursive_event_container():
    events = _complete_coverage_events()
    events[2]["code_ranges"][0]["recursive"] = events

    coverage = _coverage_status(events=events)

    assert coverage["status"] == "partial"
    assert any(
        "PCode events could not be materialized" in error
        for error in coverage["errors"]
    )


def test_runtime_rejects_empty_expected_site_family():
    proof = _complete_coverage_proof()
    proof["operand_mutation_sites"] = []

    coverage = _coverage_status(proof=proof)

    assert coverage["status"] == "partial"
    assert "operand mutation proof site inventory must be nonempty" in coverage[
        "errors"
    ]


def test_runtime_rejects_extra_hooked_site():
    coverage = _coverage_status(
        hooked_site_ids={"rewrite-1", "mutation-1", "emit-1", "extra-1"}
    )

    assert coverage["status"] == "partial"
    assert "hooked site IDs differ from exact proof inventory" in coverage["errors"]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda events: events[0].update({"event": "unknown"}),
            "unknown PCode event kind 'unknown'",
        ),
        (
            lambda events: events[0].update(
                {"instrumented_site_id": "mutation-1"}
            ),
            "operand_rewrite event site 'mutation-1' not in matching proof family",
        ),
        (
            lambda events: events[0].update({"pcode_event_sequence": True}),
            "PCode event 0 sequence must be nonnegative integer",
        ),
        (
            lambda events: events[1].update({"pcode_event_sequence": 0}),
            "PCode event sequences must be contiguous from zero",
        ),
        (
            lambda events: events[0].update({"unexpected": 1}),
            "operand_rewrite event 0 has unexpected fields",
        ),
        (
            lambda events: events.__setitem__(0, 7),
            "PCode event 0 must be object",
        ),
        (
            lambda events: events[0].update({"event": []}),
            "unknown PCode event kind []",
        ),
    ],
)
def test_runtime_rejects_malformed_or_misclassified_events(mutate, expected):
    events = _complete_coverage_events()
    mutate(events)

    coverage = _coverage_status(events=events)

    assert coverage["status"] == "partial"
    assert expected in coverage["errors"]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda events: events[0].pop("pcode_id"),
            "operand_rewrite event 0 fields differ from exact schema",
        ),
        (
            lambda events: events[0].update({"operand_index": True}),
            "operand_rewrite event 0 operand_index must be nonnegative integer",
        ),
        (
            lambda events: events[0].update({"role": "read"}),
            "operand_rewrite event 0 role is invalid",
        ),
        (
            lambda events: events[0].update({"role": []}),
            "operand_rewrite event 0 role is invalid",
        ),
        (
            lambda events: events[1]["inputs"][0].pop("opcode_id"),
            "pcode_mutation event 1 input 0 fields differ from exact schema",
        ),
        (
            lambda events: events[1]["outputs"][0]["operands"][0].update(
                {"raw_payload_sha256": "not-a-digest"}
            ),
            "pcode_mutation event 1 output 0 operand 0 raw payload digest is invalid",
        ),
        (
            lambda events: events[2]["emission_snapshot"].pop("opcode"),
            "code_emission event 2 emission snapshot fields differ from exact schema",
        ),
        (
            lambda events: events[2]["emission_snapshot"][
                "parsed_register_operands"
            ][0].update({"allocation_requirement": []}),
            "code_emission event 2 emission snapshot parsed operand 0 allocation_requirement is invalid",
        ),
        (
            lambda events: events[2]["code_ranges"][0][
                "machine_operand_mappings"
            ][0].pop("physical_register"),
            "code_emission event 2 range 0 mapping 0 fields differ from exact schema",
        ),
        (
            lambda events: events[2]["code_ranges"][0]["relocations"][0].update(
                {"target_symbol": 9}
            ),
            "code_emission event 2 range 0 relocation 0 target_symbol must be string",
        ),
    ],
)
def test_runtime_requires_complete_closed_event_shapes(mutate, expected):
    events = _complete_coverage_events()
    mutate(events)

    coverage = _coverage_status(events=events)

    assert coverage["status"] == "partial"
    assert any(expected in error for error in coverage["errors"])


def test_runtime_rejects_equal_float_before_event_validation():
    events = _complete_coverage_events()
    events[0]["operand_index"] = 0.0

    coverage = _coverage_status(events=events)

    assert coverage["status"] == "partial"
    assert any(
        "PCode events could not be materialized" in error
        for error in coverage["errors"]
    )


def test_runtime_rejects_malformed_hook_and_coverage_scalars():
    coverage = _coverage_status(
        hooked_site_ids="rewrite-1",
        event_cap=True,
        dropped_events=False,
        truncated=0,
        errors="bad",
    )

    assert coverage["status"] == "partial"
    assert "hooked site IDs must be set" in coverage["errors"]
    assert "PCode event cap must be positive integer" in coverage["errors"]
    assert "PCode dropped events must be nonnegative integer" in coverage["errors"]
    assert "PCode truncated must be boolean" in coverage["errors"]
    assert "PCode instrumentation errors must be list" in coverage["errors"]


@pytest.mark.parametrize(
    ("reader", "match"),
    [
        (lambda _addr, _size: bytes(11), "short PCodeArg\\[0\\] read"),
        (lambda _addr, _size: 12, "PCodeArg\\[0\\] reader must return bytes-like"),
    ],
)
def test_snapshot_rejects_short_or_malformed_raw_pcodearg_reads(reader, match):
    mem = Memory()
    add_block(mem, ptr=0x600000, first_pcode=0x610000, block_index=0)
    add_pcode(mem, ptr=0x610000, opcode=62, arg_count=1)

    with pytest.raises(ValueError, match=match):
        backend_pcode_snapshot.snapshot_pcode_blocks(
            mem.read_u32,
            mem.read_s16,
            0x600000,
            read_bytes=reader,
            pass_id="pcode_snapshot",
            pass_name="PCode Snapshot",
            opcode_names={62: "addi"},
            source_stage="allocator_input",
        )


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
