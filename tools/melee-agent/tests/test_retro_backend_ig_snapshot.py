import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import (  # noqa: E402
    backend_events,
    backend_ig_snapshot,
    backend_object_snapshot,
)

OBJECT_OFFSETS = backend_object_snapshot.ObjObjectOffsets(0x0A, 0x0E, 0x02, 0x2A)

COMPILER = {"family": "MWCC", "version": "GC/1.2.5n", "retail": True}
SOURCE = {
    "tu": "src/melee/test/unit.c",
    "function": "snapshot_fn",
    "mwcc_command": "test mwcc command ig-snapshot snapshot_fn",
    "mwcc_command_hash": "sha256:143b108bfc3a01302102157c950676ad3d792527de8188a76d8f5a3297d5eaa3",
}
FRAME_EVENT = {
    "event": "frame_state",
    "function": "snapshot_fn",
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


class Memory:
    def __init__(self) -> None:
        self._u32 = {}
        self._s16 = {}
        self._s32 = {}

    def u32(self, addr: int, value: int) -> None:
        self._u32[addr] = value

    def s16(self, addr: int, value: int) -> None:
        self._s16[addr] = value

    def s32(self, addr: int, value: int) -> None:
        self._s32[addr] = value

    def read_u32(self, addr: int) -> int:
        return self._u32[addr]

    def read_s16(self, addr: int) -> int:
        return self._s16[addr]

    def read_s32(self, addr: int) -> int:
        return self._s32[addr]


def add_node(
    mem: Memory,
    *,
    graph_va: int,
    ig_id: int,
    ptr: int,
    degree: int = 0,
    assigned_reg: int = -1,
    flags: int = 0,
    neighbors: list[int] | None = None,
    objobject_ptr: int = 0,
) -> None:
    neighbors = neighbors or []
    mem.u32(graph_va + ig_id * 4, ptr)
    mem.u32(ptr + 0x00, 0)
    mem.u32(ptr + 0x04, objobject_ptr)
    mem.s16(ptr + 0x0C, ig_id)
    mem.s16(ptr + 0x0E, degree)
    mem.s16(ptr + 0x10, assigned_reg)
    mem.s16(ptr + 0x12, flags)
    mem.s16(ptr + 0x14, len(neighbors))
    for index, neighbor in enumerate(neighbors):
        mem.s16(ptr + 0x16 + index * 2, neighbor)


def add_objobject(mem: Memory, ptr: int, *, type_size: int = 4) -> None:
    mem.u32(ptr + 0x0A, ptr + 0x100)
    mem.u32(ptr + 0x0E, ptr + 0x200)
    mem.s32(ptr + 0x202, type_size)


def test_ig_node_emits_observed_objobject_snapshot_and_binding() -> None:
    mem = Memory()
    add_node(mem, graph_va=0x1000, ig_id=0, ptr=0x2000, objobject_ptr=0x1200)
    add_objobject(mem, 0x1200)

    events = backend_ig_snapshot.snapshot_interference_graph(
        mem.read_u32,
        mem.read_s16,
        0x1000,
        1,
        class_id=0,
        class_name="gpr",
        source_stage="colorgraph_return",
        read_s32=mem.read_s32,
        lifecycle_sequence=7,
        generation_for=lambda kind, ptr: (
            3 if (kind, ptr) == ("objobject", 0x1200) else None
        ),
        ignode_obj_addr_offset=0x04,
        object_offsets=OBJECT_OFFSETS,
    )

    node = next(event for event in events if event["event"] == "node")
    assert node["objobject_ptr"] == 0x1200
    assert node["object_binding_confidence"] == "observed"
    assert node["retail_ignode"]["obj_addr"] == 0x1200
    assert next(event for event in events if event["event"] == "objobject_snapshot") == {
        "event": "objobject_snapshot",
        "stage": "colorgraph_return",
        "runtime_address": 0x1200,
        "allocation_generation": 3,
        "lifecycle_sequence_at_capture": 7,
        "name_record_pointer": 0x1300,
        "type_pointer": 0x1400,
        "type_size": 4,
        "readable": True,
    }
    assert next(event for event in events if event["event"] == "object_virtual_binding") == {
        "event": "object_virtual_binding",
        "source_stage": "colorgraph_return",
        "objobject_ptr": 0x1200,
        "allocation_generation": 3,
        "lifecycle_sequence_at_capture": 7,
        "class_id": 0,
        "class_name": "gpr",
        "virtual_kind": "r",
        "virtual": 0,
        "ig_id": 0,
        "ignode_runtime_address": 0x2000,
        "confidence": "observed",
        "provenance": "retail-ignode.obj_addr",
    }


def test_ig_keeps_null_object_node_without_emitting_positive_binding() -> None:
    mem = Memory()
    add_node(mem, graph_va=0x1000, ig_id=0, ptr=0x2000)

    events = backend_ig_snapshot.snapshot_interference_graph(
        mem.read_u32,
        mem.read_s16,
        0x1000,
        1,
        class_id=0,
        class_name="gpr",
        source_stage="colorgraph_return",
        read_s32=mem.read_s32,
        lifecycle_sequence=7,
        generation_for=lambda _kind, _ptr: None,
        ignode_obj_addr_offset=0x04,
        object_offsets=OBJECT_OFFSETS,
    )

    node = next(event for event in events if event["event"] == "node")
    assert node["objobject_ptr"] == 0
    assert node["object_binding_confidence"] is None
    assert not [event for event in events if event["event"] == "object_virtual_binding"]
    assert not [event for event in events if event["event"] == "objobject_snapshot"]


def test_ig_retains_one_to_many_and_spill_owned_positive_bindings_canonically() -> None:
    mem = Memory()
    add_node(mem, graph_va=0x1000, ig_id=0, ptr=0x2000, objobject_ptr=0x1200)
    add_node(
        mem,
        graph_va=0x1000,
        ig_id=1,
        ptr=0x2040,
        objobject_ptr=0x1200,
        flags=0x01,
    )
    add_objobject(mem, 0x1200)

    events = backend_ig_snapshot.snapshot_interference_graph(
        mem.read_u32,
        mem.read_s16,
        0x1000,
        2,
        class_id=0,
        class_name="gpr",
        source_stage="colorgraph_return",
        read_s32=mem.read_s32,
        lifecycle_sequence=0,
        generation_for=lambda _kind, _ptr: 1,
        ignode_obj_addr_offset=0x04,
        object_offsets=OBJECT_OFFSETS,
    )

    snapshots = [event for event in events if event["event"] == "objobject_snapshot"]
    bindings = [event for event in events if event["event"] == "object_virtual_binding"]
    assert len(snapshots) == 1
    assert [(row["virtual"], row["ig_id"]) for row in bindings] == [(0, 0), (1, 1)]
    assert next(event for event in events if event.get("ig_id") == 1)["spill"]["spilled"]


def test_ig_positive_object_without_active_generation_fails_closed() -> None:
    mem = Memory()
    add_node(mem, graph_va=0x1000, ig_id=0, ptr=0x2000, objobject_ptr=0x1200)

    with pytest.raises(ValueError, match="no active ObjObject generation"):
        backend_ig_snapshot.snapshot_interference_graph(
            mem.read_u32,
            mem.read_s16,
            0x1000,
            1,
            class_id=0,
            class_name="gpr",
            source_stage="colorgraph_return",
            read_s32=mem.read_s32,
            lifecycle_sequence=0,
            generation_for=lambda _kind, _ptr: None,
            ignode_obj_addr_offset=0x04,
            object_offsets=OBJECT_OFFSETS,
        )


def test_ig_late_failure_carries_immutable_positive_prefix_facts() -> None:
    mem = Memory()
    add_node(mem, graph_va=0x1000, ig_id=0, ptr=0x2000, objobject_ptr=0x1200)
    add_node(mem, graph_va=0x1000, ig_id=1, ptr=0x2040, objobject_ptr=0x1300)
    add_objobject(mem, 0x1200)
    add_objobject(mem, 0x1300)
    del mem._s16[0x2040 + 0x0E]

    with pytest.raises(
        backend_ig_snapshot.PartialObjectCaptureError,
        match=r"failed to read IGNode\[1\].degree",
    ) as caught:
        backend_ig_snapshot.snapshot_interference_graph(
            mem.read_u32,
            mem.read_s16,
            0x1000,
            2,
            class_id=0,
            class_name="gpr",
            source_stage="colorgraph_return",
            read_s32=mem.read_s32,
            lifecycle_sequence=7,
            generation_for=lambda _kind, ptr: {0x1200: 3, 0x1300: 4}.get(ptr),
            ignode_obj_addr_offset=0x04,
            object_offsets=OBJECT_OFFSETS,
        )

    facts = caught.value.partial_facts
    assert [fact["event"] for fact in facts] == [
        "objobject_snapshot",
        "object_virtual_binding",
    ]
    assert facts[1]["objobject_ptr"] == 0x1200
    with pytest.raises(TypeError):
        facts[1]["virtual"] = 99  # type: ignore[index]


def test_post_colorgraph_late_head_cycle_carries_positive_snapshot_facts() -> None:
    mem = Memory()
    add_node(mem, graph_va=0x1000, ig_id=0, ptr=0x2000, objobject_ptr=0x1200)
    add_node(mem, graph_va=0x1000, ig_id=1, ptr=0x2040, objobject_ptr=0x1300)
    add_objobject(mem, 0x1200)
    add_objobject(mem, 0x1300)
    mem.u32(0x2000, 0x2040)
    mem.u32(0x2040, 0x2000)

    with pytest.raises(
        backend_ig_snapshot.PartialObjectCaptureError,
        match="cycle in colorgraph head list",
    ) as caught:
        backend_ig_snapshot.post_colorgraph_class_events(
            mem.read_u32,
            mem.read_s16,
            graph_va=0x1000,
            head_ptr=0x2000,
            n_ignodes=2,
            class_id=0,
            class_name="gpr",
            read_s32=mem.read_s32,
            lifecycle_sequence=7,
            generation_for=lambda _kind, ptr: {0x1200: 3, 0x1300: 4}.get(ptr),
            ignode_obj_addr_offset=0x04,
            object_offsets=OBJECT_OFFSETS,
        )

    assert [fact["objobject_ptr"] for fact in caught.value.partial_facts if fact["event"] == "object_virtual_binding"] == [
        0x1200,
        0x1300,
    ]


def test_walk_colorgraph_head_reads_ignode_next_order() -> None:
    mem = Memory()
    graph_va = 0x1000
    add_node(mem, graph_va=graph_va, ig_id=0, ptr=0x2000)
    add_node(mem, graph_va=graph_va, ig_id=1, ptr=0x2040)
    add_node(mem, graph_va=graph_va, ig_id=2, ptr=0x2080)
    mem.u32(0x2040 + 0x00, 0x2000)
    mem.u32(0x2000 + 0x00, 0x2080)

    assert backend_ig_snapshot.walk_colorgraph_head_order(
        mem.read_u32,
        mem.read_s16,
        0x2040,
        3,
    ) == [1, 0, 2]


@pytest.mark.parametrize(
    ("mutate", "max_nodes", "match"),
    [
        (lambda mem: 0, 3, "null colorgraph head"),
        (
            lambda mem: mem.u32(0x2080 + 0x00, 0x2040) or 0x2040,
            4,
            "cycle in colorgraph head list",
        ),
        (
            lambda mem: mem.s16(0x2040 + 0x0C, -1) or 0x2040,
            3,
            "negative ig_idx -1",
        ),
        (
            lambda mem: mem.s16(0x2040 + 0x0C, 3) or 0x2040,
            3,
            "out-of-range ig_idx 3",
        ),
        (
            lambda mem: mem.s16(0x2000 + 0x0C, 1) or 0x2040,
            3,
            "duplicate ig_idx 1",
        ),
        (lambda mem: 0x2040, 2, "colorgraph head list exceeds max_nodes 2"),
    ],
)
def test_walk_colorgraph_head_rejects_suspect_order_facts(
    mutate, max_nodes: int, match: str
) -> None:
    mem = Memory()
    graph_va = 0x1000
    add_node(mem, graph_va=graph_va, ig_id=0, ptr=0x2000)
    add_node(mem, graph_va=graph_va, ig_id=1, ptr=0x2040)
    add_node(mem, graph_va=graph_va, ig_id=2, ptr=0x2080)
    mem.u32(0x2040 + 0x00, 0x2000)
    mem.u32(0x2000 + 0x00, 0x2080)

    head = mutate(mem)
    with pytest.raises(ValueError, match=match):
        backend_ig_snapshot.walk_colorgraph_head_order(
            mem.read_u32,
            mem.read_s16,
            head,
            3,
            max_nodes=max_nodes,
        )


def test_walk_colorgraph_head_can_treat_null_head_as_empty_order() -> None:
    mem = Memory()

    assert backend_ig_snapshot.walk_colorgraph_head_order(
        mem.read_u32,
        mem.read_s16,
        0,
        33,
        allow_empty=True,
    ) == []


def test_post_colorgraph_decisions_use_head_order_and_blocker_rows() -> None:
    mem = Memory()
    graph_va = 0x1000
    add_node(mem, graph_va=graph_va, ig_id=0, ptr=0x2000, assigned_reg=31, neighbors=[1])
    add_node(mem, graph_va=graph_va, ig_id=1, ptr=0x2040, assigned_reg=30, neighbors=[0])
    mem.u32(0x2040 + 0x00, 0x2000)

    events = backend_ig_snapshot.post_colorgraph_color_decision_events(
        mem.read_u32,
        mem.read_s16,
        0x2040,
        graph_va,
        2,
        class_id=0,
        class_name="gpr",
        colorgraph_order=[1, 0],
    )

    assert [event["event"] for event in events] == ["color_decision", "color_decision"]
    assert [(event["id"], event["ig_id"], event["iter"], event["assigned_phys"]) for event in events] == [
        ("gpr-c0", 1, 0, 30),
        ("gpr-c1", 0, 1, 31),
    ]
    assert events[0]["blocked_candidates"] == [
        {
            "phys": 31,
            "reason": "interferer-assigned-phys",
            "holder_ig_id": 0,
            "holder_assigned_phys": 31,
            "provenance": "retail-post-colorgraph-interference",
        }
    ]
    assert events[0]["blocked_by"] == [{"ig_id": 0, "phys": 31}]
    assert events[0]["chosen_source"] == "observed-retail-assignment"
    assert events[0]["tie_rule"] == "unavailable-retail-post-colorgraph"
    assert events[0]["decision_rule"] == "retail-post-colorgraph-observed-assignment"
    assert events[0]["confidence"] == "observed-partial"
    assert events[0]["provenance"] == "retail-colorgraph-return"


def test_post_colorgraph_enriches_coalesce_mapping_root_phys() -> None:
    mem = Memory()
    graph_va = 0x7000
    add_node(mem, graph_va=graph_va, ig_id=0, ptr=0x8000, assigned_reg=31)
    add_node(mem, graph_va=graph_va, ig_id=1, ptr=0x8040)
    add_node(mem, graph_va=graph_va, ig_id=2, ptr=0x8080, assigned_reg=0, flags=0x04)
    base_events = [
        {
            "event": "coalesce_mapping",
            "class_id": 0,
            "class_name": "gpr",
            "alias": 2,
            "root": 0,
            "root_phys": None,
            "confidence": "observed",
            "provenance": "retail_ignode_coalesced_away",
            "source_stage": "colorgraph",
        }
    ]

    events = backend_ig_snapshot.enrich_post_colorgraph_coalesce_mappings(
        base_events,
        mem.read_u32,
        mem.read_s16,
        graph_va,
        3,
        class_name="gpr",
    )

    assert events[0]["root_phys"] == 31


def test_snapshot_marks_precolored_root_nodes_with_assigned_phys() -> None:
    mem = Memory()
    graph_va = 0x7000
    for ig_id in range(5):
        add_node(mem, graph_va=graph_va, ig_id=ig_id, ptr=0x8000 + ig_id * 0x40)
    add_node(
        mem,
        graph_va=graph_va,
        ig_id=3,
        ptr=0x80C0,
        assigned_reg=3,
        flags=0x08,
        neighbors=[4],
    )
    add_node(
        mem,
        graph_va=graph_va,
        ig_id=4,
        ptr=0x8100,
        assigned_reg=3,
        flags=0x04,
        neighbors=[3],
    )

    events = backend_ig_snapshot.snapshot_interference_graph(
        mem.read_u32,
        mem.read_s16,
        graph_va,
        5,
        class_id=0,
        class_name="gpr",
        source_stage="colorgraph_return",
    )
    nodes = {event["ig_id"]: event for event in events if event["event"] == "node"}

    assert nodes[3]["color_status"] == "precolored"
    assert nodes[3]["assigned_phys"] == 3
    assert nodes[4]["coalesced_into"] == 3


def test_post_colorgraph_empty_head_emits_no_decisions() -> None:
    mem = Memory()

    assert (
        backend_ig_snapshot.post_colorgraph_color_decision_events(
            mem.read_u32,
            mem.read_s16,
            0,
            0x1000,
            2,
            class_id=0,
            class_name="gpr",
            colorgraph_order=[],
        )
        == []
    )


def test_post_colorgraph_class_events_emit_single_enriched_snapshot() -> None:
    mem = Memory()
    graph_va = 0x7000
    add_node(mem, graph_va=graph_va, ig_id=0, ptr=0x8000, assigned_reg=31, neighbors=[1])
    add_node(mem, graph_va=graph_va, ig_id=1, ptr=0x8040, assigned_reg=30, neighbors=[0])
    add_node(mem, graph_va=graph_va, ig_id=2, ptr=0x8080, assigned_reg=0, flags=0x04)
    mem.u32(0x8000 + 0x00, 0x8040)

    events = backend_ig_snapshot.post_colorgraph_class_events(
        mem.read_u32,
        mem.read_s16,
        graph_va=graph_va,
        head_ptr=0x8000,
        n_ignodes=3,
        class_id=0,
        class_name="gpr",
        function_name="snapshot_fn",
    )

    kinds = [event["event"] for event in events]
    assert kinds == [
        "regclass",
        "node",
        "node",
        "node",
        "coalesce_mapping",
        "edge",
        "simplify_order",
        "select_order",
        "color_decision",
        "color_decision",
    ]
    mappings = [event for event in events if event["event"] == "coalesce_mapping"]
    assert mappings == [
        {
            "event": "coalesce_mapping",
            "class_id": 0,
            "class_name": "gpr",
            "alias": 2,
            "root": 0,
            "root_phys": 31,
            "confidence": "observed",
            "provenance": "retail_ignode_coalesced_away",
            "source_stage": "colorgraph_return",
        }
    ]
    decisions = [event for event in events if event["event"] == "color_decision"]
    assert [(event["id"], event["ig_id"], event["assigned_phys"]) for event in decisions] == [
        ("gpr-c0", 0, 31),
        ("gpr-c1", 1, 30),
    ]
    assert decisions[0]["blocked_candidates"][0]["holder_ig_id"] == 1


def test_snapshot_events_normalize_to_backend_trace() -> None:
    mem = Memory()
    graph_va = 0x1000
    add_node(
        mem,
        graph_va=graph_va,
        ig_id=0,
        ptr=0x2000,
        degree=1,
        flags=0x20,
        neighbors=[1, 1],
    )
    add_node(
        mem,
        graph_va=graph_va,
        ig_id=1,
        ptr=0x2040,
        degree=1,
        assigned_reg=29,
        neighbors=[0],
    )
    add_node(mem, graph_va=graph_va, ig_id=2, ptr=0x2080)

    snapshot_events = backend_ig_snapshot.snapshot_interference_graph(
        mem.read_u32,
        mem.read_s16,
        graph_va,
        3,
        class_id=0,
        class_name="gpr",
        source_stage="build_interference_graph_wrapper",
        function_name="snapshot_fn",
    )

    assert [event["event"] for event in snapshot_events] == [
        "regclass",
        "node",
        "node",
        "node",
        "coalesce_mapping_empty",
        "edge",
    ]
    assert snapshot_events[0]["registers"]["physical_count"] == 32
    assert snapshot_events[0]["registers"]["initial_volatile"] == [
        0,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
    ]
    assert snapshot_events[1]["ig_id"] == 0
    assert snapshot_events[1]["assigned_phys"] is None
    assert snapshot_events[1]["flags"] == [{"raw": 0x20}]
    assert snapshot_events[1]["coalesce"] == {"root_ig_id": 0, "aliases": []}
    assert snapshot_events[1]["spill"] == {"spilled": False, "reason": None}
    assert snapshot_events[1]["color_status"] == "uncolored"
    assert snapshot_events[2]["ig_id"] == 1
    assert snapshot_events[2]["assigned_phys"] is None
    assert snapshot_events[2]["retail_ignode"]["assignedReg"] == 29
    assert snapshot_events[2]["source_attribution"]["function"] == "snapshot_fn"
    assert snapshot_events[4] == {
        "event": "coalesce_mapping_empty",
        "class_id": 0,
        "class_name": "gpr",
        "confidence": "observed",
        "provenance": "retail_ignode_no_coalesced_aliases",
        "source_stage": "build_interference_graph_wrapper",
    }
    assert snapshot_events[5] == {
        "event": "edge",
        "class_id": 0,
        "class_name": "gpr",
        "a": 0,
        "b": 1,
        "kind": "interference",
        "confidence": "observed",
        "provenance": "interferencegraph",
        "source_stage": "build_interference_graph_wrapper",
    }

    trace = backend_events.normalize_events(
        [{"event": "function_start", "name": "snapshot_fn"}, *snapshot_events, FRAME_EVENT],
        compiler=COMPILER,
        source=SOURCE,
        tool_version="test",
    )

    cls = trace["functions"][0]["regalloc"]["classes"][0]
    assert cls["class_name"] == "gpr"
    assert cls["registers"]["allocatable"] == [
        0,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        31,
        30,
        29,
        28,
        27,
        26,
        25,
        24,
        23,
        22,
        21,
        20,
        19,
        18,
        17,
        16,
        15,
        14,
        13,
    ]
    assert [node["ig_id"] for node in cls["nodes"]] == [0, 1, 2]
    assert all(node["color_status"] == "uncolored" for node in cls["nodes"])
    assert cls["nodes"][1]["assigned_phys"] is None
    assert cls["edges"] == [
        {
            "a": 0,
            "b": 1,
            "kind": "interference",
            "confidence": "observed",
            "provenance": "interferencegraph",
        }
    ]


def test_snapshot_emits_coalesce_mapping_for_coalesced_alias() -> None:
    mem = Memory()
    graph_va = 0x7000
    add_node(mem, graph_va=graph_va, ig_id=0, ptr=0x8000)
    add_node(mem, graph_va=graph_va, ig_id=1, ptr=0x8040, assigned_reg=0, flags=0x04)

    events = backend_ig_snapshot.snapshot_interference_graph(
        mem.read_u32,
        mem.read_s16,
        graph_va,
        2,
        class_id=0,
        class_name="gpr",
        source_stage="colorgraph",
        function_name="snapshot_fn",
    )

    mappings = [event for event in events if event["event"] == "coalesce_mapping"]
    assert mappings == [
        {
            "event": "coalesce_mapping",
            "class_id": 0,
            "class_name": "gpr",
            "alias": 1,
            "root": 0,
            "root_phys": None,
            "confidence": "observed",
            "provenance": "retail_ignode_coalesced_away",
            "source_stage": "colorgraph",
        }
    ]
    assert not [event for event in events if event["event"] == "coalesce_mapping_empty"]

    trace = backend_events.normalize_events(
        [{"event": "function_start", "name": "snapshot_fn"}, *events, FRAME_EVENT],
        compiler=COMPILER,
        source=SOURCE,
        tool_version="test",
    )
    cls = trace["functions"][0]["regalloc"]["classes"][0]
    alias = next(node for node in cls["nodes"] if node["ig_id"] == 1)
    root = next(node for node in cls["nodes"] if node["ig_id"] == 0)
    assert alias["color_status"] == "uncolored"
    assert alias["coalesced_into"] == 0
    assert alias["assigned_phys"] is None
    assert root["coalesce"]["aliases"] == [1]


def test_snapshot_rejects_coalesced_alias_with_out_of_range_root() -> None:
    mem = Memory()
    graph_va = 0x9000
    add_node(mem, graph_va=graph_va, ig_id=0, ptr=0xA000)
    add_node(mem, graph_va=graph_va, ig_id=1, ptr=0xA040, assigned_reg=2, flags=0x04)

    with pytest.raises(ValueError, match="coalesced alias 1 references invalid root 2"):
        backend_ig_snapshot.snapshot_interference_graph(
            mem.read_u32,
            mem.read_s16,
            graph_va,
            2,
            class_id=0,
            class_name="gpr",
            source_stage="colorgraph",
        )


def test_snapshot_rejects_coalesced_alias_self_mapping() -> None:
    mem = Memory()
    graph_va = 0x9000
    add_node(mem, graph_va=graph_va, ig_id=0, ptr=0xA000)
    add_node(mem, graph_va=graph_va, ig_id=1, ptr=0xA040, assigned_reg=1, flags=0x04)

    with pytest.raises(ValueError, match="coalesced alias 1 self-maps to its own root"):
        backend_ig_snapshot.snapshot_interference_graph(
            mem.read_u32,
            mem.read_s16,
            graph_va,
            2,
            class_id=0,
            class_name="gpr",
            source_stage="colorgraph",
        )


def test_snapshot_sorts_multiple_deduped_edges() -> None:
    mem = Memory()
    graph_va = 0x5000
    add_node(mem, graph_va=graph_va, ig_id=0, ptr=0x6000, neighbors=[2])
    add_node(mem, graph_va=graph_va, ig_id=1, ptr=0x6040, neighbors=[2])
    add_node(mem, graph_va=graph_va, ig_id=2, ptr=0x6080, neighbors=[1, 0])

    events = backend_ig_snapshot.snapshot_interference_graph(
        mem.read_u32,
        mem.read_s16,
        graph_va,
        3,
        class_id=0,
        class_name="gpr",
        source_stage="colorgraph",
    )

    edges = [event for event in events if event["event"] == "edge"]
    assert [(edge["a"], edge["b"]) for edge in edges] == [(0, 2), (1, 2)]


def test_fpr_regclass_metadata_is_schema_complete() -> None:
    mem = Memory()
    graph_va = 0x3000
    add_node(mem, graph_va=graph_va, ig_id=0, ptr=0x4000)

    events = backend_ig_snapshot.snapshot_interference_graph(
        mem.read_u32,
        mem.read_s16,
        graph_va,
        1,
        class_id=1,
        class_name="fpr",
        source_stage="build_interference_graph_wrapper",
    )

    registers = events[0]["registers"]
    assert registers.keys() >= {
        "physical_count",
        "allocatable",
        "initial_volatile",
        "reserved",
        "fixed",
        "precolored",
        "nonvolatile_dispense_order",
        "model_boundary",
    }
    assert registers["physical_count"] == 32
    assert registers["initial_volatile"] == list(range(14))
    assert registers["nonvolatile_dispense_order"] == list(range(31, 13, -1))
    assert registers["model_boundary"] == [
        {"name": "FPSCR", "reason": "outside-v1-allocator-facts"}
    ]


@pytest.mark.parametrize(
    ("n_ignodes", "max_nodes", "match"),
    [
        (0, 2048, "n_ignodes must be positive"),
        (3, 2, "n_ignodes 3 exceeds max_nodes 2"),
    ],
)
def test_snapshot_rejects_invalid_node_count(
    n_ignodes: int, max_nodes: int, match: str
) -> None:
    mem = Memory()

    with pytest.raises(ValueError, match=match):
        backend_ig_snapshot.snapshot_interference_graph(
            mem.read_u32,
            mem.read_s16,
            0x1000,
            n_ignodes,
            class_id=0,
            class_name="gpr",
            source_stage="build_interference_graph_wrapper",
            max_nodes=max_nodes,
        )


def test_snapshot_rejects_invalid_max_nodes() -> None:
    mem = Memory()

    with pytest.raises(ValueError, match="max_nodes must be positive"):
        backend_ig_snapshot.snapshot_interference_graph(
            mem.read_u32,
            mem.read_s16,
            0x1000,
            1,
            class_id=0,
            class_name="gpr",
            source_stage="colorgraph",
            max_nodes=0,
        )


def test_snapshot_wraps_reader_failures_as_value_error() -> None:
    mem = Memory()

    with pytest.raises(ValueError, match="failed to read node pointer for ig_id 0 at 0x1000"):
        backend_ig_snapshot.snapshot_interference_graph(
            mem.read_u32,
            mem.read_s16,
            0x1000,
            1,
            class_id=0,
            class_name="gpr",
            source_stage="colorgraph",
        )


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda mem, graph_va, ptr: mem.u32(graph_va, 0), "null node pointer for ig_id 0"),
        (lambda mem, graph_va, ptr: mem.s16(ptr + 0x0C, 1), "ig_id mismatch"),
        (lambda mem, graph_va, ptr: mem.s16(ptr + 0x14, -1), "negative arraySize"),
        # The reader caps a single node's neighbor array at 2048 entries.
        (lambda mem, graph_va, ptr: mem.s16(ptr + 0x14, 2049), "arraySize 2049 exceeds"),
        (lambda mem, graph_va, ptr: mem.s16(ptr + 0x16, 0), "self edge"),
        (lambda mem, graph_va, ptr: mem.s16(ptr + 0x16, 2), "out-of-range neighbor"),
        (lambda mem, graph_va, ptr: mem.s16(ptr + 0x16, -1), "invalid neighbor"),
    ],
)
def test_snapshot_rejects_suspect_graph_facts(mutate, match: str) -> None:
    mem = Memory()
    graph_va = 0x1000
    ptr = 0x2000
    add_node(mem, graph_va=graph_va, ig_id=0, ptr=ptr, degree=1, neighbors=[1])
    add_node(mem, graph_va=graph_va, ig_id=1, ptr=0x2040, degree=1, neighbors=[0])
    mutate(mem, graph_va, ptr)

    with pytest.raises(ValueError, match=match):
        backend_ig_snapshot.snapshot_interference_graph(
            mem.read_u32,
            mem.read_s16,
            graph_va,
            2,
            class_id=0,
            class_name="gpr",
            source_stage="build_interference_graph_wrapper",
        )


def test_snapshot_rejects_unknown_register_class() -> None:
    mem = Memory()

    with pytest.raises(ValueError, match="unknown register class 'vr'"):
        backend_ig_snapshot.snapshot_interference_graph(
            mem.read_u32,
            mem.read_s16,
            0x1000,
            1,
            class_id=2,
            class_name="vr",
            source_stage="build_interference_graph_wrapper",
        )
