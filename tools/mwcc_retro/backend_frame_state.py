"""Build backend frame/stack-local map events from retail MWCC globals."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

ReadU32 = Callable[[int], int]
ReadS32 = Callable[[int], int]
ReadCString = Callable[[int, int], str]

POINTER_LOW = 0x600000
POINTER_HIGH = 0x2000000
MAX_OBJECTS = 256
PROBE_MAX_OBJECTS = 6

OBJECT_LIST_NEXT = 0x00
OBJECT_LIST_OBJECT = 0x04
OBJECT_NAME_RECORD = 0x0A
OBJECT_TYPE = 0x0E
OBJECT_STACK_OFFSET = 0x2A
NAME_RECORD_TEXT = 0x0A
TYPE_SIZE = 0x02


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
) -> dict[str, Any]:
    """Return one ``frame_state`` backend event.

    ``list_vas`` maps frame areas (``arguments``, ``locals``, ``temps``) to the
    global list-head variables sampled from the retail compiler.
    """

    if max_objects <= 0:
        raise ValueError(f"max_objects must be positive, got {max_objects}")

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
            )
        )

    return {
        "event": "frame_state",
        "source_stage": source_stage,
        "provenance": "frame_locals",
        "base_size_bytes": _read_s32(
            read_s32, frame_base_size_va, "frame_base_size"
        ),
        "call_args_size_bytes": _read_s32(
            read_s32, frame_call_args_size_va, "frame_call_args_size"
        ),
        "objects": objects,
    }


def snapshot_probe_frame_state(
    read_u32: ReadU32,
    read_s32: ReadS32,
    read_cstr: ReadCString,
    *,
    list_vas: Mapping[str, int],
    frame_base_size_va: int,
    frame_call_args_size_va: int,
    max_objects: int = PROBE_MAX_OBJECTS,
) -> dict[str, Any]:
    """Return the legacy ``backend-map-probe.json`` frame evidence shape."""

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
                read_u32, read_s32, read_cstr, node=current
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
) -> dict[str, Any]:
    obj = _read_u32(read_u32, node + OBJECT_LIST_OBJECT, "frame object pointer")
    row = {
        "node": node,
        "next": _read_u32(read_u32, node + OBJECT_LIST_NEXT, "frame object next"),
        "object": obj,
    }
    if _bounded_ptr(obj):
        name_record = _read_u32(read_u32, obj + OBJECT_NAME_RECORD, "ObjObject name")
        row["name_ptr"] = name_record + NAME_RECORD_TEXT if _bounded_ptr(name_record) else 0
        if _bounded_ptr(row["name_ptr"]):
            row["name"] = read_cstr(row["name_ptr"], 96)
        row["stack_offset"] = _read_s32(
            read_s32, obj + OBJECT_STACK_OFFSET, "ObjObject stack offset"
        )
        type_ptr = _read_u32(read_u32, obj + OBJECT_TYPE, "ObjObject type")
        row["type"] = type_ptr
        row["size"] = (
            _read_s32(read_s32, type_ptr + TYPE_SIZE, "ObjObject type size")
            if _bounded_ptr(type_ptr)
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
            read_u32, current + OBJECT_LIST_NEXT, f"{area} frame object next"
        )
        obj = _read_u32(
            read_u32, current + OBJECT_LIST_OBJECT, f"{area} frame object pointer"
        )
        if not _bounded_ptr(obj):
            raise ValueError(f"invalid {area} ObjObject pointer 0x{obj:x}")

        type_ptr = _read_u32(read_u32, obj + OBJECT_TYPE, f"{area} ObjObject type")
        if not _bounded_ptr(type_ptr):
            raise ValueError(f"invalid {area} ObjObject type pointer 0x{type_ptr:x}")
        size = _read_s32(read_s32, type_ptr + TYPE_SIZE, f"{area} ObjObject type size")
        if size < 0:
            raise ValueError(f"negative {area} ObjObject size {size}")
        stack_offset = _read_s32(
            read_s32,
            obj + OBJECT_STACK_OFFSET,
            f"{area} ObjObject stack offset",
        )
        name_record = _read_u32(
            read_u32, obj + OBJECT_NAME_RECORD, f"{area} ObjObject name record"
        )
        name, confidence = _frame_object_name(
            read_cstr,
            area=area,
            stack_offset=stack_offset,
            name_record=name_record,
        )

        objects.append(
            {
                "area": area,
                "name": name,
                "stack_offset": stack_offset,
                "size": size,
                "type": f"type@0x{type_ptr:x}",
                "confidence": confidence,
                "provenance": f"frame_{area}",
            }
        )
        current = next_node
    raise ValueError(f"{area} frame object list exceeded max_objects {max_objects}")


def _frame_object_name(
    read_cstr: ReadCString,
    *,
    area: str,
    stack_offset: int,
    name_record: int,
) -> tuple[str, str]:
    if _bounded_ptr(name_record):
        try:
            name = read_cstr(name_record + NAME_RECORD_TEXT, 96)
        except Exception:  # noqa: BLE001 - unnamed frame slots are still useful facts
            name = ""
        if name:
            return name, "observed"
    return f"{area}_slot_{stack_offset}", "observed-unnamed"


def _bounded_ptr(value: int) -> bool:
    return POINTER_LOW <= int(value) < POINTER_HIGH


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
