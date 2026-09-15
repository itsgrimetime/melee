"""Build backend frame/stack-local map events from retail MWCC globals."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from tools.mwcc_retro import backend_object_snapshot

ReadU32 = Callable[[int], int]
ReadS32 = Callable[[int], int]
ReadCString = Callable[[int, int], str]
GenerationFor = Callable[[str, int], int | None]
PartialObjectCaptureError = backend_object_snapshot.PartialObjectCaptureError

POINTER_LOW = 0x600000
POINTER_HIGH = 0x2000000
IMAGE_POINTER_LOW = 0x400000
IMAGE_POINTER_HIGH = POINTER_LOW
MAX_OBJECTS = 256
PROBE_MAX_OBJECTS = 6


def _resolve_frame_layout(
    object_offsets: backend_object_snapshot.ObjObjectOffsets | None,
    list_offsets: backend_object_snapshot.FrameListOffsets | None,
    name_record_text_offset: int | None,
) -> tuple[
    backend_object_snapshot.ObjObjectOffsets,
    backend_object_snapshot.FrameListOffsets,
    int,
]:
    supplied = (
        object_offsets is not None,
        list_offsets is not None,
        name_record_text_offset is not None,
    )
    if any(supplied) and not all(supplied):
        raise ValueError("frame layout arguments must be supplied together")
    if all(supplied):
        assert object_offsets is not None
        assert list_offsets is not None
        assert name_record_text_offset is not None
        return object_offsets, list_offsets, name_record_text_offset

    from tools.mwcc_retro import struct_map

    layout = struct_map.load_object_capture_layout(
        struct_map.load_gc125n_struct_map()
    )
    return (
        backend_object_snapshot.ObjObjectOffsets(
            name_record=layout.objobject_name_record,
            type_pointer=layout.objobject_type_pointer,
            type_size=layout.type_size,
            stack_offset=layout.objobject_stack_offset,
        ),
        backend_object_snapshot.FrameListOffsets(
            next=layout.object_list_next,
            object=layout.object_list_object,
        ),
        layout.name_record_text,
    )

def snapshot_frame_state(
    read_u32: ReadU32,
    read_s32: ReadS32,
    read_cstr: ReadCString,
    *,
    list_vas: Mapping[str, int],
    frame_base_size_va: int,
    frame_call_args_size_va: int,
    source_stage: str,
    max_objects: int = MAX_OBJECTS,
    lifecycle_sequence: int | None = None,
    generation_for: GenerationFor | None = None,
    object_offsets: backend_object_snapshot.ObjObjectOffsets | None = None,
    list_offsets: backend_object_snapshot.FrameListOffsets | None = None,
    name_record_text_offset: int | None = None,
) -> dict[str, Any]:
    object_offsets, list_offsets, name_record_text_offset = _resolve_frame_layout(
        object_offsets,
        list_offsets,
        name_record_text_offset,
    )
    partial_facts: list[dict[str, object]] = []
    try:
        return _snapshot_frame_state(
            read_u32,
            read_s32,
            read_cstr,
            list_vas=list_vas,
            frame_base_size_va=frame_base_size_va,
            frame_call_args_size_va=frame_call_args_size_va,
            source_stage=source_stage,
            max_objects=max_objects,
            lifecycle_sequence=lifecycle_sequence,
            generation_for=generation_for,
            object_offsets=object_offsets,
            list_offsets=list_offsets,
            name_record_text_offset=name_record_text_offset,
            partial_facts=partial_facts,
        )
    except PartialObjectCaptureError:
        raise
    except Exception as exc:
        if partial_facts:
            raise PartialObjectCaptureError(str(exc), partial_facts) from exc
        raise


def _snapshot_frame_state(
    read_u32: ReadU32,
    read_s32: ReadS32,
    read_cstr: ReadCString,
    *,
    list_vas: Mapping[str, int],
    frame_base_size_va: int,
    frame_call_args_size_va: int,
    source_stage: str,
    max_objects: int = MAX_OBJECTS,
    lifecycle_sequence: int | None = None,
    generation_for: GenerationFor | None = None,
    object_offsets: backend_object_snapshot.ObjObjectOffsets,
    list_offsets: backend_object_snapshot.FrameListOffsets,
    name_record_text_offset: int,
    partial_facts: list[dict[str, object]],
) -> dict[str, Any]:
    """Return one ``frame_state`` backend event.

    ``list_vas`` maps frame areas (``arguments``, ``locals``, ``temps``) to the
    global list-head variables sampled from the retail compiler.
    """

    if max_objects <= 0:
        raise ValueError(f"max_objects must be positive, got {max_objects}")
    capture_objects = _validate_object_capture_inputs(
        lifecycle_sequence, generation_for
    )
    if capture_objects and source_stage != "final_scheduler":
        raise ValueError(
            "lifecycle-aware ObjObject frame capture requires final_scheduler"
        )
    base_size = _read_s32(read_s32, frame_base_size_va, "frame_base_size")
    call_args_size = _read_s32(
        read_s32, frame_call_args_size_va, "frame_call_args_size"
    )

    objects: list[dict[str, Any]] = []
    for area in ("locals", "arguments", "temps"):
        list_va = list_vas.get(area)
        if list_va is None:
            continue
        objects.extend(
            _snapshot_object_list(
                read_u32,
                read_s32,
                read_cstr,
                area=area,
                list_va=list_va,
                max_objects=max_objects,
                frame_base_size=base_size,
                frame_call_args_size=call_args_size,
                lifecycle_sequence=lifecycle_sequence,
                generation_for=generation_for,
                object_offsets=object_offsets,
                list_offsets=list_offsets,
                name_record_text_offset=name_record_text_offset,
                partial_facts=partial_facts,
            )
        )

    event = {
        "event": "frame_state",
        "source_stage": source_stage,
        "provenance": "frame_locals",
        "base_size_bytes": base_size,
        "call_args_size_bytes": call_args_size,
        "objects": objects,
    }
    if capture_objects:
        event["object_binding_capabilities"] = []
    return event


def snapshot_probe_frame_state(
    read_u32: ReadU32,
    read_s32: ReadS32,
    read_cstr: ReadCString,
    *,
    list_vas: Mapping[str, int],
    frame_base_size_va: int,
    frame_call_args_size_va: int,
    max_objects: int = PROBE_MAX_OBJECTS,
    object_offsets: backend_object_snapshot.ObjObjectOffsets | None = None,
    list_offsets: backend_object_snapshot.FrameListOffsets | None = None,
    name_record_text_offset: int | None = None,
) -> dict[str, Any]:
    """Return the legacy ``backend-map-probe.json`` frame evidence shape."""

    object_offsets, list_offsets, name_record_text_offset = _resolve_frame_layout(
        object_offsets,
        list_offsets,
        name_record_text_offset,
    )
    if max_objects <= 0:
        raise ValueError(f"max_objects must be positive, got {max_objects}")

    frame: dict[str, Any] = {}
    for area in ("arguments", "locals", "temps"):
        list_va = list_vas.get(area)
        if list_va is None:
            continue
        frame[area] = _snapshot_probe_object_list(
            read_u32,
            read_s32,
            read_cstr,
            list_va=list_va,
            max_objects=max_objects,
            object_offsets=object_offsets,
            list_offsets=list_offsets,
            name_record_text_offset=name_record_text_offset,
        )

    for key, va in (
        ("frame_base_size", frame_base_size_va),
        ("frame_call_args_size", frame_call_args_size_va),
    ):
        try:
            frame[key] = {"va": va, "s32": _read_s32(read_s32, va, key)}
        except Exception as exc:  # noqa: BLE001 - probe evidence records failures
            frame[key] = {"va": va, "error": str(exc)}

    return frame


def _snapshot_probe_object_list(
    read_u32: ReadU32,
    read_s32: ReadS32,
    read_cstr: ReadCString,
    *,
    list_va: int,
    max_objects: int,
    object_offsets: backend_object_snapshot.ObjObjectOffsets,
    list_offsets: backend_object_snapshot.FrameListOffsets,
    name_record_text_offset: int,
) -> dict[str, Any]:
    head = _read_u32(read_u32, list_va, "frame object list head")
    out: dict[str, Any] = {"va": list_va, "head": head, "objects_sample": []}
    current = head
    seen: set[int] = set()
    for _slot in range(max_objects):
        if not _bounded_ptr(current) or current in seen:
            break
        seen.add(current)
        try:
            row = _snapshot_probe_object_row(
                read_u32,
                read_s32,
                read_cstr,
                node=current,
                object_offsets=object_offsets,
                list_offsets=list_offsets,
                name_record_text_offset=name_record_text_offset,
            )
            out["objects_sample"].append(row)
            current = row["next"]
        except Exception as exc:  # noqa: BLE001 - preserve probe evidence
            out["objects_sample"].append({"node": current, "error": str(exc)})
            break
    return out


def _snapshot_probe_object_row(
    read_u32: ReadU32,
    read_s32: ReadS32,
    read_cstr: ReadCString,
    *,
    node: int,
    object_offsets: backend_object_snapshot.ObjObjectOffsets,
    list_offsets: backend_object_snapshot.FrameListOffsets,
    name_record_text_offset: int,
) -> dict[str, Any]:
    obj = _read_u32(read_u32, node + list_offsets.object, "frame object pointer")
    row = {
        "node": node,
        "next": _read_u32(read_u32, node + list_offsets.next, "frame object next"),
        "object": obj,
    }
    if _bounded_ptr(obj):
        name_record = _read_u32(
            read_u32, obj + object_offsets.name_record, "ObjObject name"
        )
        row["name_ptr"] = (
            name_record + name_record_text_offset if _readable_ptr(name_record) else 0
        )
        if _readable_ptr(row["name_ptr"]):
            row["name"] = read_cstr(row["name_ptr"], 96)
        row["stack_offset"] = _read_s32(
            read_s32, obj + object_offsets.stack_offset, "ObjObject stack offset"
        )
        type_ptr = _read_u32(
            read_u32, obj + object_offsets.type_pointer, "ObjObject type"
        )
        row["type"] = type_ptr
        row["size"] = (
            _read_s32(
                read_s32, type_ptr + object_offsets.type_size, "ObjObject type size"
            )
            if _readable_ptr(type_ptr)
            else 0
        )
    return row


def _snapshot_object_list(
    read_u32: ReadU32,
    read_s32: ReadS32,
    read_cstr: ReadCString,
    *,
    area: str,
    list_va: int,
    max_objects: int,
    frame_base_size: int,
    frame_call_args_size: int,
    lifecycle_sequence: int | None,
    generation_for: GenerationFor | None,
    object_offsets: backend_object_snapshot.ObjObjectOffsets,
    list_offsets: backend_object_snapshot.FrameListOffsets,
    name_record_text_offset: int,
    partial_facts: list[dict[str, object]],
) -> list[dict[str, Any]]:
    head = _read_u32(read_u32, list_va, f"{area} frame object list head")
    if head == 0:
        return []
    if not _bounded_ptr(head):
        raise ValueError(f"invalid {area} frame object pointer 0x{head:x}")

    objects: list[dict[str, Any]] = []
    seen: set[int] = set()
    current = head
    for _slot in range(max_objects):
        if current == 0:
            return objects
        if not _bounded_ptr(current):
            raise ValueError(f"invalid {area} frame object pointer 0x{current:x}")
        if current in seen:
            raise ValueError(f"cycle in {area} frame object list at 0x{current:x}")
        seen.add(current)

        next_node = _read_u32(
            read_u32, current + list_offsets.next, f"{area} frame object next"
        )
        obj = _read_u32(
            read_u32, current + list_offsets.object, f"{area} frame object pointer"
        )
        if not _bounded_ptr(obj):
            raise ValueError(f"invalid {area} ObjObject pointer 0x{obj:x}")

        object_snapshot: dict[str, object] | None = None
        generation: int | None = None
        if lifecycle_sequence is not None and generation_for is not None:
            generation = generation_for("objobject", obj)
            if not _is_positive_int(generation):
                raise ValueError(
                    f"no active ObjObject generation for 0x{obj:x} "
                    f"at lifecycle sequence {lifecycle_sequence}"
                )
            object_snapshot = dict(
                backend_object_snapshot.snapshot_objobject(
                    ptr=obj,
                    stage="final_scheduler",
                    lifecycle_sequence=lifecycle_sequence,
                    generation=generation,
                    read_u32=read_u32,
                    read_s32=read_s32,
                    offsets=object_offsets,
                )
            )
            partial_facts.append({"event": "objobject_snapshot", **object_snapshot})
            type_ptr = object_snapshot["type_pointer"]
            size = object_snapshot["type_size"]
        else:
            type_ptr = _read_u32(
                read_u32,
                obj + object_offsets.type_pointer,
                f"{area} ObjObject type",
            )
            if not _readable_ptr(type_ptr):
                raise ValueError(f"invalid {area} ObjObject type pointer 0x{type_ptr:x}")
            size = _read_s32(
                read_s32,
                type_ptr + object_offsets.type_size,
                f"{area} ObjObject type size",
            )
            if size < 0:
                raise ValueError(f"negative {area} ObjObject size {size}")
        stack_offset = _read_s32(
            read_s32,
            obj + object_offsets.stack_offset,
            f"{area} ObjObject stack offset",
        )
        name_record = (
            object_snapshot["name_record_pointer"]
            if object_snapshot is not None
            else _read_u32(
                read_u32,
                obj + object_offsets.name_record,
                f"{area} ObjObject name record",
            )
        )
        name, confidence = _frame_object_name(
            read_cstr,
            area=area,
            stack_offset=stack_offset,
            name_record=name_record,
            name_record_text_offset=name_record_text_offset,
        )

        row = {
            "area": area,
            "name": name,
            "stack_offset": stack_offset,
            "size": size,
            "type": (
                f"type@0x{type_ptr:x}"
                if isinstance(type_ptr, int)
                else "unreadable"
            ),
            "confidence": confidence,
            "provenance": f"frame_{area}",
        }
        if object_snapshot is not None:
            row.update(
                {
                    "list_node_runtime_address": current,
                    "objobject_ptr": obj,
                    "allocation_generation": generation,
                    "raw_object_stack_offset": stack_offset,
                    "frame_base_size": frame_base_size,
                    "frame_call_args_size": frame_call_args_size,
                    "final_r1_offset": (
                        frame_base_size + frame_call_args_size + stack_offset
                    ),
                    "frame_binding_confidence": "derived-unique",
                    "frame_binding_provenance": [
                        "retail-frame-layout-formula.v1",
                        "retail-frame-list.object",
                        "retail-objobject.stack-offset",
                    ],
                    "object_snapshot": object_snapshot,
                }
            )
        objects.append(row)
        if object_snapshot is not None:
            partial_facts.extend(
                _frame_object_facts(row, source_stage="final_scheduler")[1:]
            )
        current = next_node
    raise ValueError(f"{area} frame object list exceeded max_objects {max_objects}")


def _frame_object_name(
    read_cstr: ReadCString,
    *,
    area: str,
    stack_offset: int,
    name_record: int | None,
    name_record_text_offset: int,
) -> tuple[str, str]:
    if isinstance(name_record, int) and _readable_ptr(name_record):
        try:
            name = read_cstr(name_record + name_record_text_offset, 96)
        except Exception:  # noqa: BLE001 - unnamed frame slots are still useful facts
            name = ""
        if name:
            return name, "observed"
    return f"{area}_slot_{stack_offset}", "observed-unnamed"


def _frame_object_facts(
    row: Mapping[str, object], *, source_stage: str
) -> list[dict[str, object]]:
    snapshot = row.get("object_snapshot")
    if not isinstance(snapshot, dict):
        return []
    return [
        {"event": "objobject_snapshot", **snapshot},
        {
            "event": "object_frame_binding",
            "source_stage": source_stage,
            "objobject_ptr": row.get("objobject_ptr"),
            "allocation_generation": row.get("allocation_generation"),
            "lifecycle_sequence_at_capture": snapshot.get(
                "lifecycle_sequence_at_capture"
            ),
            "area": row.get("area"),
            "list_node_runtime_address": row.get("list_node_runtime_address"),
            "raw_object_stack_offset": row.get("raw_object_stack_offset"),
            "frame_base_size": row.get("frame_base_size"),
            "frame_call_args_size": row.get("frame_call_args_size"),
            "final_r1_offset": row.get("final_r1_offset"),
            "size": row.get("size"),
            "confidence": row.get("frame_binding_confidence"),
            "provenance": row.get("frame_binding_provenance"),
        },
    ]


def _bounded_ptr(value: int) -> bool:
    return POINTER_LOW <= int(value) < POINTER_HIGH


def _readable_ptr(value: int) -> bool:
    value = int(value)
    return IMAGE_POINTER_LOW <= value < IMAGE_POINTER_HIGH or _bounded_ptr(value)


def _read_u32(read_u32: ReadU32, addr: int, label: str) -> int:
    try:
        return read_u32(addr)
    except Exception as exc:  # noqa: BLE001 - reader failures become controlled facts
        raise ValueError(f"failed to read {label} at 0x{addr:x}: {exc}") from exc


def _read_s32(read_s32: ReadS32, addr: int, label: str) -> int:
    try:
        return read_s32(addr)
    except Exception as exc:  # noqa: BLE001 - reader failures become controlled facts
        raise ValueError(f"failed to read {label} at 0x{addr:x}: {exc}") from exc


def _validate_object_capture_inputs(
    lifecycle_sequence: int | None, generation_for: GenerationFor | None
) -> bool:
    if (lifecycle_sequence is None) != (generation_for is None):
        raise ValueError(
            "lifecycle_sequence and generation_for must be supplied together"
        )
    if lifecycle_sequence is None:
        return False
    if isinstance(lifecycle_sequence, bool) or not isinstance(lifecycle_sequence, int):
        raise ValueError("lifecycle_sequence must be an integer at least -1")
    if lifecycle_sequence < -1:
        raise ValueError("lifecycle_sequence must be an integer at least -1")
    return True


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
