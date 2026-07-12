"""Build backend events from a retail GC/1.2.5n interference graph snapshot.

This module is intentionally pure: callers provide memory readers, and the
builder returns raw backend event dictionaries suitable for backend_events.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from tools.mwcc_retro import backend_object_snapshot

ReadU32 = Callable[[int], int]
ReadS16 = Callable[[int], int]
ReadS32 = Callable[[int], int]
GenerationFor = Callable[[str, int], int | None]

IGNODE_NEXT = 0x00
IGNODE_OBJ_ADDR = 0x04
IGNODE_IG_IDX = 0x0C
IGNODE_DEGREE = 0x0E
IGNODE_ASSIGNED_REG = 0x10
IGNODE_FLAGS = 0x12
IGNODE_ARRAY_SIZE = 0x14
IGNODE_NEIGHBORS = 0x16

DEFAULT_MAX_NODES = 2048
MAX_NEIGHBORS_PER_NODE = 2048

_GPR_INITIAL_VOLATILE = [0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
_GPR_NONVOLATILE_ORDER = list(range(31, 12, -1))
_FPR_INITIAL_VOLATILE = list(range(14))
_FPR_NONVOLATILE_ORDER = list(range(31, 13, -1))

_REGISTER_CLASSES = {
    "gpr": {
        "virtual_kind": "r",
        "registers": {
            "physical_count": 32,
            "allocatable": _GPR_INITIAL_VOLATILE + _GPR_NONVOLATILE_ORDER,
            "initial_volatile": _GPR_INITIAL_VOLATILE,
            "reserved": [1, 2],
            "fixed": [
                {"phys": 1, "reason": "stack_pointer"},
                {"phys": 2, "reason": "toc"},
            ],
            "precolored": [],
            "nonvolatile_dispense_order": _GPR_NONVOLATILE_ORDER,
            "model_boundary": [
                {"name": "LR", "reason": "outside-v1-allocator-facts"},
            ],
        },
        "non_allocatable_state": {
            "status": "model-boundary",
            "notes": ["CR/LR/CTR not modeled in v1 allocator facts"],
        },
    },
    "fpr": {
        "virtual_kind": "f",
        "registers": {
            "physical_count": 32,
            "allocatable": _FPR_INITIAL_VOLATILE + _FPR_NONVOLATILE_ORDER,
            "initial_volatile": _FPR_INITIAL_VOLATILE,
            "reserved": [],
            "fixed": [],
            "precolored": [],
            "nonvolatile_dispense_order": _FPR_NONVOLATILE_ORDER,
            "model_boundary": [
                {"name": "FPSCR", "reason": "outside-v1-allocator-facts"},
            ],
        },
        "non_allocatable_state": {
            "status": "model-boundary",
            "notes": ["FPSCR not modeled in v1 allocator facts"],
        },
    },
}


def snapshot_interference_graph(
    read_u32: ReadU32,
    read_s16: ReadS16,
    graph_va: int,
    n_ignodes: int,
    *,
    class_id: int,
    class_name: str,
    source_stage: str,
    function_name: str | None = None,
    max_nodes: int = DEFAULT_MAX_NODES,
    read_s32: ReadS32 | None = None,
    lifecycle_sequence: int | None = None,
    generation_for: GenerationFor | None = None,
    object_offsets: backend_object_snapshot.ObjObjectOffsets = (
        backend_object_snapshot.GC_125N_OBJOBJECT_OFFSETS
    ),
) -> list[dict[str, Any]]:
    """Return normalized backend events for one retail interference graph.

    GC/1.2.5n stores ``interferencegraph`` as an array of u32 node pointers at
    ``graph_va + ig_id * 4``.  Each node points at the discovered IGNode layout
    documented by the offset constants above.  A single node's neighbor array
    is capped at 2048 s16 entries to avoid trusting corrupt snapshot sizes.
    """

    class_info = _class_info(class_name)
    _validate_node_count(n_ignodes, max_nodes)

    node_events: list[dict[str, Any]] = []
    coalesce_events: list[dict[str, Any]] = []
    edge_pairs: set[tuple[int, int]] = set()
    object_snapshots: dict[tuple[int, int], dict[str, Any]] = {}
    object_bindings: list[dict[str, Any]] = []
    neighbor_cap = min(max_nodes, MAX_NEIGHBORS_PER_NODE)
    capture_objects = _validate_object_capture_inputs(
        read_s32=read_s32,
        lifecycle_sequence=lifecycle_sequence,
        generation_for=generation_for,
    )

    for ig_id in range(n_ignodes):
        node_ptr = _read_u32(read_u32, graph_va + ig_id * 4, f"node pointer for ig_id {ig_id}")
        if node_ptr == 0:
            raise ValueError(f"null node pointer for ig_id {ig_id}")

        next_ptr = _read_u32(read_u32, node_ptr + IGNODE_NEXT, f"IGNode[{ig_id}].next")
        objobject_ptr = _read_u32(
            read_u32,
            node_ptr + IGNODE_OBJ_ADDR,
            f"IGNode[{ig_id}].obj_addr",
        )
        observed_ig_id = _read_s16(read_s16, node_ptr + IGNODE_IG_IDX, f"IGNode[{ig_id}].ig_idx")
        if observed_ig_id != ig_id:
            raise ValueError(
                f"ig_id mismatch for slot {ig_id}: node at 0x{node_ptr:x} reports {observed_ig_id}"
            )

        degree = _read_s16(read_s16, node_ptr + IGNODE_DEGREE, f"IGNode[{ig_id}].degree")
        assigned_reg = _read_s16(
            read_s16, node_ptr + IGNODE_ASSIGNED_REG, f"IGNode[{ig_id}].assignedReg"
        )
        flags = _read_s16(read_s16, node_ptr + IGNODE_FLAGS, f"IGNode[{ig_id}].flags")
        array_size = _read_s16(
            read_s16, node_ptr + IGNODE_ARRAY_SIZE, f"IGNode[{ig_id}].arraySize"
        )
        if array_size < 0:
            raise ValueError(f"negative arraySize {array_size} for ig_id {ig_id}")
        if array_size > neighbor_cap:
            raise ValueError(
                f"arraySize {array_size} exceeds neighbor cap {neighbor_cap} for ig_id {ig_id}"
            )

        node_events.append(
            _node_event(
                class_id=class_id,
                class_name=class_name,
                virtual_kind=class_info["virtual_kind"],
                ig_id=ig_id,
                node_ptr=node_ptr,
                next_ptr=next_ptr,
                objobject_ptr=objobject_ptr,
                degree=degree,
                assigned_reg=assigned_reg,
                flags=flags,
                array_size=array_size,
                source_stage=source_stage,
                function_name=function_name,
            )
        )

        if capture_objects and objobject_ptr > 0:
            assert read_s32 is not None
            assert lifecycle_sequence is not None
            assert generation_for is not None
            generation = generation_for("objobject", objobject_ptr)
            if not _is_positive_int(generation):
                raise ValueError(
                    f"no active ObjObject generation for 0x{objobject_ptr:x} "
                    f"at lifecycle sequence {lifecycle_sequence}"
                )
            snapshot = backend_object_snapshot.snapshot_objobject(
                ptr=objobject_ptr,
                stage=source_stage,
                lifecycle_sequence=lifecycle_sequence,
                generation=generation,
                read_u32=read_u32,
                read_s32=read_s32,
                offsets=object_offsets,
            )
            object_snapshots.setdefault(
                (objobject_ptr, generation),
                {"event": "objobject_snapshot", **dict(snapshot)},
            )
            object_bindings.append(
                {
                    "event": "object_virtual_binding",
                    "source_stage": source_stage,
                    "objobject_ptr": objobject_ptr,
                    "allocation_generation": generation,
                    "lifecycle_sequence_at_capture": lifecycle_sequence,
                    "class_id": class_id,
                    "class_name": class_name,
                    "virtual_kind": class_info["virtual_kind"],
                    "virtual": ig_id,
                    "ig_id": ig_id,
                    "ignode_runtime_address": node_ptr,
                    "confidence": "observed",
                    "provenance": "retail-ignode.obj_addr",
                }
            )

        flag_byte = flags & 0xFF
        if flag_byte & 0x04:
            root = assigned_reg
            if root < 0 or root >= n_ignodes:
                raise ValueError(
                    f"coalesced alias {ig_id} references invalid root {root}; "
                    f"n_ignodes={n_ignodes}"
                )
            if root == ig_id:
                raise ValueError(f"coalesced alias {ig_id} self-maps to its own root")
            coalesce_events.append(
                _coalesce_mapping_event(
                    class_id=class_id,
                    class_name=class_name,
                    source_stage=source_stage,
                    alias=ig_id,
                    root=root,
                )
            )

        for index in range(array_size):
            neighbor = _read_s16(
                read_s16,
                node_ptr + IGNODE_NEIGHBORS + index * 2,
                f"IGNode[{ig_id}].neighbors[{index}]",
            )
            if neighbor < 0:
                raise ValueError(f"invalid neighbor {neighbor} for ig_id {ig_id} at index {index}")
            if neighbor >= n_ignodes:
                raise ValueError(
                    f"out-of-range neighbor {neighbor} for ig_id {ig_id}; n_ignodes={n_ignodes}"
                )
            if neighbor == ig_id:
                raise ValueError(f"self edge for ig_id {ig_id} at neighbor index {index}")
            edge_pairs.add((min(ig_id, neighbor), max(ig_id, neighbor)))

    return [
        _regclass_event(
            class_id=class_id,
            class_name=class_name,
            source_stage=source_stage,
            registers=class_info["registers"],
            non_allocatable_state=class_info["non_allocatable_state"],
        ),
        *node_events,
        *(
            coalesce_events
            if coalesce_events
            else [
                _coalesce_mapping_empty_event(
                    class_id=class_id,
                    class_name=class_name,
                    source_stage=source_stage,
                )
            ]
        ),
        *[
            _edge_event(
                class_id=class_id,
                class_name=class_name,
                source_stage=source_stage,
                a=a,
                b=b,
            )
            for a, b in sorted(edge_pairs)
        ],
        *[object_snapshots[key] for key in sorted(object_snapshots)],
        *sorted(
            object_bindings,
            key=lambda row: (
                row["objobject_ptr"],
                row["allocation_generation"],
                row["class_id"],
                row["virtual_kind"],
                row["virtual"],
                row["ig_id"],
                row["ignode_runtime_address"],
            ),
        ),
    ]


def walk_colorgraph_head_order(
    read_u32: ReadU32,
    read_s16: ReadS16,
    head_ptr: int,
    n_ignodes: int,
    *,
    allow_empty: bool = False,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> list[int]:
    """Walk the colorgraph entry IGNode list and return observed IG ids.

    The retail ``colorgraph`` entry receives the post-``simplifygraph`` linked
    list head as its second stack argument.  This captures only that list
    order; it does not infer color decisions.
    """

    if max_nodes <= 0:
        raise ValueError(f"max_nodes must be positive, got {max_nodes}")
    if n_ignodes <= 0:
        raise ValueError(f"n_ignodes must be positive, got {n_ignodes}")
    if head_ptr == 0:
        if allow_empty:
            return []
        raise ValueError("null colorgraph head")

    order: list[int] = []
    seen_ptrs: set[int] = set()
    seen_ig_ids: set[int] = set()
    ptr = head_ptr
    while ptr:
        if ptr in seen_ptrs:
            raise ValueError(f"cycle in colorgraph head list at 0x{ptr:x}")
        if len(order) >= max_nodes:
            raise ValueError(f"colorgraph head list exceeds max_nodes {max_nodes}")
        seen_ptrs.add(ptr)

        ig_id = _read_s16(read_s16, ptr + IGNODE_IG_IDX, "colorgraph IGNode.ig_idx")
        if ig_id < 0:
            raise ValueError(f"negative ig_idx {ig_id} in colorgraph head list")
        if ig_id >= n_ignodes:
            raise ValueError(
                f"out-of-range ig_idx {ig_id} in colorgraph head list; n_ignodes={n_ignodes}"
            )
        if ig_id in seen_ig_ids:
            raise ValueError(f"duplicate ig_idx {ig_id} in colorgraph head list")
        seen_ig_ids.add(ig_id)
        order.append(ig_id)
        ptr = _read_u32(read_u32, ptr + IGNODE_NEXT, f"colorgraph IGNode[{ig_id}].next")
    return order


def colorgraph_order_events(
    order: list[int],
    *,
    class_id: int,
    class_name: str,
    source_stage: str,
    provenance: str,
) -> list[dict[str, Any]]:
    return [
        _order_event(
            event=event,
            class_id=class_id,
            class_name=class_name,
            order=order,
            source_stage=source_stage,
            provenance=provenance,
        )
        for event in ("simplify_order", "select_order")
    ]


def post_colorgraph_color_decision_events(
    read_u32: ReadU32,
    read_s16: ReadS16,
    head_ptr: int,
    graph_va: int,
    n_ignodes: int,
    *,
    class_id: int,
    class_name: str,
    colorgraph_order: list[int] | None = None,
    source_stage: str = "colorgraph",
    max_nodes: int = DEFAULT_MAX_NODES,
) -> list[dict[str, Any]]:
    """Return partial observed color decisions from a post-colorgraph IG list.

    These events describe facts visible after retail ``colorgraph`` returns.
    They intentionally do not replay allocator candidate filtering or tie
    behavior; unavailable fields are explicit conservative placeholders.
    """

    class_info = _class_info(class_name)
    _validate_node_count(n_ignodes, max_nodes)
    order = walk_colorgraph_head_order(
        read_u32,
        read_s16,
        head_ptr,
        n_ignodes,
        allow_empty=True,
        max_nodes=max_nodes,
    )
    if colorgraph_order is not None and list(colorgraph_order) != order:
        raise ValueError(
            "post-colorgraph head order does not match supplied colorgraph_order: "
            f"{order!r} != {list(colorgraph_order)!r}"
        )
    if not order:
        return []

    facts = _read_post_colorgraph_node_facts(
        read_u32,
        read_s16,
        graph_va,
        n_ignodes,
        max_nodes=max_nodes,
    )
    physical_count = class_info["registers"]["physical_count"]
    decisions: list[dict[str, Any]] = []
    for index, ig_id in enumerate(order):
        fact = facts[ig_id]
        assigned_phys = _assigned_phys_or_none(fact, physical_count)
        blocked_candidates, blocked_by = _post_colorgraph_blockers(
            fact,
            facts,
            physical_count,
        )
        decisions.append(
            {
                "event": "color_decision",
                "class_id": class_id,
                "class_name": class_name,
                "id": f"{class_name}-c{index}",
                "ig_id": ig_id,
                "iter": index,
                "assigned_phys": assigned_phys,
                "node_state_before_select": {
                    "status": "unavailable",
                    "reason": "retail-post-colorgraph-only",
                },
                "reserved_or_precolored_filtered": [],
                "available_phys_ordered": [],
                "blocked_candidates": blocked_candidates,
                "blocked_by": blocked_by,
                "candidate_phys_ordered": (
                    [assigned_phys] if assigned_phys is not None else []
                ),
                "chosen_source": "observed-retail-assignment",
                "tie_rule": "unavailable-retail-post-colorgraph",
                "decision_rule": "retail-post-colorgraph-observed-assignment",
                "confidence": "observed-partial",
                "provenance": "retail-colorgraph-return",
                "source_stage": source_stage,
            }
        )
    return decisions


def post_colorgraph_class_events(
    read_u32: ReadU32,
    read_s16: ReadS16,
    *,
    graph_va: int,
    head_ptr: int,
    n_ignodes: int,
    class_id: int,
    class_name: str,
    function_name: str | None = None,
    max_nodes: int = DEFAULT_MAX_NODES,
    read_s32: ReadS32 | None = None,
    lifecycle_sequence: int | None = None,
    generation_for: GenerationFor | None = None,
    object_offsets: backend_object_snapshot.ObjObjectOffsets = (
        backend_object_snapshot.GC_125N_OBJOBJECT_OFFSETS
    ),
) -> list[dict[str, Any]]:
    """Return one post-colorgraph class snapshot event batch.

    This is the partial-probe equivalent of the debug DLL's immediate
    post-colorgraph walk: one regclass/node/edge/coalesce snapshot, enriched
    coalesce root physicals, colorgraph order, and observed color decisions.
    """

    source_stage = "colorgraph_return"
    order = walk_colorgraph_head_order(
        read_u32,
        read_s16,
        head_ptr,
        n_ignodes,
        allow_empty=True,
        max_nodes=max_nodes,
    )
    events = snapshot_interference_graph(
        read_u32,
        read_s16,
        graph_va,
        n_ignodes,
        class_id=class_id,
        class_name=class_name,
        source_stage=source_stage,
        function_name=function_name,
        max_nodes=max_nodes,
        read_s32=read_s32,
        lifecycle_sequence=lifecycle_sequence,
        generation_for=generation_for,
        object_offsets=object_offsets,
    )
    events = enrich_post_colorgraph_coalesce_mappings(
        events,
        read_u32,
        read_s16,
        graph_va,
        n_ignodes,
        class_name=class_name,
        max_nodes=max_nodes,
    )
    return [
        *events,
        *colorgraph_order_events(
            order,
            class_id=class_id,
            class_name=class_name,
            source_stage=source_stage,
            provenance="colorgraph_return_head",
        ),
        *post_colorgraph_color_decision_events(
            read_u32,
            read_s16,
            head_ptr,
            graph_va,
            n_ignodes,
            class_id=class_id,
            class_name=class_name,
            colorgraph_order=order,
            source_stage=source_stage,
            max_nodes=max_nodes,
        ),
    ]


def enrich_post_colorgraph_coalesce_mappings(
    events: list[dict[str, Any]],
    read_u32: ReadU32,
    read_s16: ReadS16,
    graph_va: int,
    n_ignodes: int,
    *,
    class_name: str,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> list[dict[str, Any]]:
    """Return events with coalesce mappings enriched by observed root phys."""

    class_info = _class_info(class_name)
    _validate_node_count(n_ignodes, max_nodes)
    facts = _read_post_colorgraph_node_facts(
        read_u32,
        read_s16,
        graph_va,
        n_ignodes,
        max_nodes=max_nodes,
    )
    physical_count = class_info["registers"]["physical_count"]
    enriched: list[dict[str, Any]] = []
    for event in events:
        copied = deepcopy(event)
        if copied.get("event") != "coalesce_mapping":
            enriched.append(copied)
            continue
        if copied.get("class_name") != class_name:
            enriched.append(copied)
            continue
        root = copied.get("root")
        if not isinstance(root, int) or root not in facts:
            enriched.append(copied)
            continue
        root_phys = _assigned_phys_or_none(facts[root], physical_count)
        if root_phys is None:
            enriched.append(copied)
            continue
        existing = copied.get("root_phys")
        if existing not in (None, root_phys):
            raise ValueError(
                f"coalesce_mapping root {root} has contradictory root_phys "
                f"{existing!r} != observed {root_phys}"
            )
        copied["root_phys"] = root_phys
        enriched.append(copied)
    return enriched


def _class_info(class_name: str) -> dict[str, Any]:
    try:
        return _REGISTER_CLASSES[class_name]
    except KeyError as exc:
        raise ValueError(f"unknown register class {class_name!r}") from exc


def _validate_node_count(n_ignodes: int, max_nodes: int) -> None:
    if max_nodes <= 0:
        raise ValueError(f"max_nodes must be positive, got {max_nodes}")
    if n_ignodes <= 0:
        raise ValueError(f"n_ignodes must be positive, got {n_ignodes}")
    if n_ignodes > max_nodes:
        raise ValueError(f"n_ignodes {n_ignodes} exceeds max_nodes {max_nodes}")


def _regclass_event(
    *,
    class_id: int,
    class_name: str,
    source_stage: str,
    registers: dict[str, Any],
    non_allocatable_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event": "regclass",
        "class_id": class_id,
        "class_name": class_name,
        "registers": deepcopy(registers),
        "non_allocatable_state": deepcopy(non_allocatable_state),
        "source_stage": source_stage,
    }


def _node_event(
    *,
    class_id: int,
    class_name: str,
    virtual_kind: str,
    ig_id: int,
    node_ptr: int,
    next_ptr: int,
    objobject_ptr: int,
    degree: int,
    assigned_reg: int,
    flags: int,
    array_size: int,
    source_stage: str,
    function_name: str | None,
) -> dict[str, Any]:
    unavailable_reason = "retail_ig_snapshot_only"
    flag_byte = flags & 0xFF
    coalesced_into = assigned_reg if flag_byte & 0x04 and assigned_reg >= 0 else None
    coalesce_root = coalesced_into if coalesced_into is not None else ig_id
    spilled = bool(flag_byte & 0x01)
    precolored = bool(flag_byte & 0x08)
    assigned_phys = assigned_reg if precolored and assigned_reg >= 0 else None
    color_status = "precolored" if precolored else "uncolored"
    return {
        "event": "node",
        "class_id": class_id,
        "class_name": class_name,
        "ig_id": ig_id,
        "objobject_ptr": objobject_ptr,
        "object_binding_confidence": "observed" if objobject_ptr > 0 else None,
        "virtual": {"kind": virtual_kind, "number": ig_id},
        "first_def": {
            "status": "unavailable",
            "reason": unavailable_reason,
            "source_stage": source_stage,
        },
        "source_attribution": {
            "status": "unattributed",
            "symbol": None,
            "line": None,
            "confidence": "unavailable",
            "reason": unavailable_reason,
            "function": function_name,
            "source_stage": source_stage,
        },
        "live": {
            "blocks": [],
            "intervals": [],
            "confidence": "unavailable",
            "source_stage": source_stage,
        },
        "degree": degree,
        "flags": _flag_facts(flag_byte),
        "coalesce": {"root_ig_id": coalesce_root, "aliases": []},
        "simplify_order": None,
        "select_order": None,
        "assigned_phys": assigned_phys,
        "spill": {
            "spilled": spilled,
            "reason": "retail_ignode_flag" if spilled else None,
        },
        "color_status": color_status,
        "coalesced_into": coalesced_into,
        "color_decision_ref": None,
        "retail_ignode": {
            "ptr": node_ptr,
            "next": next_ptr,
            "obj_addr": objobject_ptr,
            "assignedReg": assigned_reg,
            "flags": flag_byte,
            "arraySize": array_size,
        },
        "source_stage": source_stage,
    }


def _validate_object_capture_inputs(
    *,
    read_s32: ReadS32 | None,
    lifecycle_sequence: int | None,
    generation_for: GenerationFor | None,
) -> bool:
    supplied = (
        read_s32 is not None,
        lifecycle_sequence is not None,
        generation_for is not None,
    )
    if any(supplied) and not all(supplied):
        raise ValueError(
            "read_s32, lifecycle_sequence, and generation_for must be supplied together"
        )
    if lifecycle_sequence is not None and (
        not isinstance(lifecycle_sequence, int)
        or isinstance(lifecycle_sequence, bool)
        or lifecycle_sequence < -1
    ):
        raise ValueError("lifecycle_sequence must be an integer at least -1")
    return all(supplied)


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _flag_facts(flags: int) -> list[dict[str, int]]:
    if flags == 0:
        return []
    return [{"raw": flags & 0xFFFF}]


def _read_post_colorgraph_node_facts(
    read_u32: ReadU32,
    read_s16: ReadS16,
    graph_va: int,
    n_ignodes: int,
    *,
    max_nodes: int,
) -> dict[int, dict[str, Any]]:
    neighbor_cap = min(max_nodes, MAX_NEIGHBORS_PER_NODE)
    facts: dict[int, dict[str, Any]] = {}
    for ig_id in range(n_ignodes):
        node_ptr = _read_u32(read_u32, graph_va + ig_id * 4, f"node pointer for ig_id {ig_id}")
        if node_ptr == 0:
            raise ValueError(f"null node pointer for ig_id {ig_id}")
        observed_ig_id = _read_s16(read_s16, node_ptr + IGNODE_IG_IDX, f"IGNode[{ig_id}].ig_idx")
        if observed_ig_id != ig_id:
            raise ValueError(
                f"ig_id mismatch for slot {ig_id}: node at 0x{node_ptr:x} reports {observed_ig_id}"
            )
        assigned_reg = _read_s16(
            read_s16, node_ptr + IGNODE_ASSIGNED_REG, f"IGNode[{ig_id}].assignedReg"
        )
        flags = _read_s16(read_s16, node_ptr + IGNODE_FLAGS, f"IGNode[{ig_id}].flags")
        array_size = _read_s16(
            read_s16, node_ptr + IGNODE_ARRAY_SIZE, f"IGNode[{ig_id}].arraySize"
        )
        if array_size < 0:
            raise ValueError(f"negative arraySize {array_size} for ig_id {ig_id}")
        if array_size > neighbor_cap:
            raise ValueError(
                f"arraySize {array_size} exceeds neighbor cap {neighbor_cap} for ig_id {ig_id}"
            )
        neighbors: list[int] = []
        for index in range(array_size):
            neighbor = _read_s16(
                read_s16,
                node_ptr + IGNODE_NEIGHBORS + index * 2,
                f"IGNode[{ig_id}].neighbors[{index}]",
            )
            if neighbor < 0:
                raise ValueError(f"invalid neighbor {neighbor} for ig_id {ig_id} at index {index}")
            if neighbor >= n_ignodes:
                raise ValueError(
                    f"out-of-range neighbor {neighbor} for ig_id {ig_id}; n_ignodes={n_ignodes}"
                )
            if neighbor == ig_id:
                raise ValueError(f"self edge for ig_id {ig_id} at neighbor index {index}")
            neighbors.append(neighbor)
        facts[ig_id] = {
            "assigned_reg": assigned_reg,
            "flags": flags & 0xFF,
            "neighbors": neighbors,
        }
    return facts


def _assigned_phys_or_none(fact: dict[str, Any], physical_count: int) -> int | None:
    assigned_reg = fact["assigned_reg"]
    if fact["flags"] & 0x04:
        return None
    if not isinstance(assigned_reg, int):
        return None
    if assigned_reg < 0 or assigned_reg >= physical_count:
        return None
    return assigned_reg


def _post_colorgraph_blockers(
    fact: dict[str, Any],
    facts: dict[int, dict[str, Any]],
    physical_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, int]]]:
    blocked_candidates: list[dict[str, Any]] = []
    blocked_by: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()
    for neighbor in fact["neighbors"]:
        neighbor_fact = facts.get(neighbor)
        if neighbor_fact is None:
            continue
        phys = _assigned_phys_or_none(neighbor_fact, physical_count)
        if phys is None:
            continue
        key = (neighbor, phys)
        if key in seen:
            continue
        seen.add(key)
        blocked_candidates.append(
            {
                "phys": phys,
                "reason": "interferer-assigned-phys",
                "holder_ig_id": neighbor,
                "holder_assigned_phys": phys,
                "provenance": "retail-post-colorgraph-interference",
            }
        )
        blocked_by.append({"ig_id": neighbor, "phys": phys})
    return blocked_candidates, blocked_by


def _edge_event(
    *,
    class_id: int,
    class_name: str,
    source_stage: str,
    a: int,
    b: int,
) -> dict[str, Any]:
    return {
        "event": "edge",
        "class_id": class_id,
        "class_name": class_name,
        "a": a,
        "b": b,
        "kind": "interference",
        "confidence": "observed",
        "provenance": "interferencegraph",
        "source_stage": source_stage,
    }


def _coalesce_mapping_event(
    *,
    class_id: int,
    class_name: str,
    source_stage: str,
    alias: int,
    root: int,
) -> dict[str, Any]:
    return {
        "event": "coalesce_mapping",
        "class_id": class_id,
        "class_name": class_name,
        "alias": alias,
        "root": root,
        "root_phys": None,
        "confidence": "observed",
        "provenance": "retail_ignode_coalesced_away",
        "source_stage": source_stage,
    }


def _coalesce_mapping_empty_event(
    *,
    class_id: int,
    class_name: str,
    source_stage: str,
) -> dict[str, Any]:
    return {
        "event": "coalesce_mapping_empty",
        "class_id": class_id,
        "class_name": class_name,
        "confidence": "observed",
        "provenance": "retail_ignode_no_coalesced_aliases",
        "source_stage": source_stage,
    }


def _order_event(
    *,
    event: str,
    class_id: int,
    class_name: str,
    order: list[int],
    source_stage: str,
    provenance: str,
) -> dict[str, Any]:
    return {
        "event": event,
        "class_id": class_id,
        "class_name": class_name,
        "order": list(order),
        "confidence": "observed",
        "provenance": provenance,
        "source_stage": source_stage,
    }


def _read_u32(read_u32: ReadU32, addr: int, label: str) -> int:
    try:
        return read_u32(addr)
    except Exception as exc:  # noqa: BLE001 - reader failures become controlled facts
        raise ValueError(f"failed to read {label} at 0x{addr:x}: {exc}") from exc


def _read_s16(read_s16: ReadS16, addr: int, label: str) -> int:
    try:
        return read_s16(addr)
    except Exception as exc:  # noqa: BLE001 - reader failures become controlled facts
        raise ValueError(f"failed to read {label} at 0x{addr:x}: {exc}") from exc
