"""Read immutable ObjObject identity facts from stopped retail memory."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

ReadU32 = Callable[[int], int]
ReadS32 = Callable[[int], int]

_STAGES = frozenset({"colorgraph_return", "final_scheduler"})


@dataclass(frozen=True, slots=True)
class ObjObjectOffsets:
    """Validated GC/1.2.5n fields used by observational capture."""

    name_record: int
    type_pointer: int
    type_size: int
    stack_offset: int


GC_125N_OBJOBJECT_OFFSETS = ObjObjectOffsets(
    name_record=0x0A,
    type_pointer=0x0E,
    type_size=0x02,
    stack_offset=0x2A,
)


def snapshot_objobject(
    *,
    ptr: int,
    stage: str,
    lifecycle_sequence: int,
    generation: int,
    read_u32: ReadU32,
    read_s32: ReadS32,
    offsets: ObjObjectOffsets,
) -> Mapping[str, object]:
    """Return one read-only snapshot without invoking any compiler routine.

    Identity inputs are rejected before memory is read. Reader failures are
    represented as a controlled unreadable snapshot so the raw same-run
    pointer and lifecycle position remain diagnostic evidence.
    """

    _validate_identity(
        ptr=ptr,
        stage=stage,
        lifecycle_sequence=lifecycle_sequence,
        generation=generation,
    )

    name_record_pointer: int | None = None
    type_pointer: int | None = None
    type_size = 0
    readable = True

    try:
        name_record_pointer = _read_pointer(read_u32, ptr + offsets.name_record)
        type_pointer = _read_pointer(read_u32, ptr + offsets.type_pointer)
        if type_pointer is not None:
            type_size = read_s32(type_pointer + offsets.type_size)
            if not _is_int(type_size) or type_size < 0:
                raise ValueError("ObjObject type size must be a nonnegative integer")
    except Exception:  # noqa: BLE001 - unreadability is a controlled capture fact
        readable = False
        if not _is_int(type_size) or type_size < 0:
            type_size = 0

    return MappingProxyType(
        {
            "stage": stage,
            "runtime_address": ptr,
            "allocation_generation": generation,
            "lifecycle_sequence_at_capture": lifecycle_sequence,
            "name_record_pointer": name_record_pointer,
            "type_pointer": type_pointer,
            "type_size": type_size,
            "readable": readable,
        }
    )


def _read_pointer(reader: ReadU32, address: int) -> int | None:
    value = reader(address)
    if not _is_int(value) or value < 0:
        raise ValueError("ObjObject pointer field must be a nonnegative integer")
    return value or None


def _validate_identity(*, ptr: object, stage: object, lifecycle_sequence: object, generation: object) -> None:
    if not _is_int(ptr) or ptr <= 0:
        raise ValueError("ptr must be a positive integer")
    if stage not in _STAGES:
        raise ValueError(f"unsupported ObjObject snapshot stage {stage!r}")
    if not _is_int(lifecycle_sequence) or lifecycle_sequence < -1:
        raise ValueError("lifecycle_sequence must be at least -1")
    if not _is_int(generation) or generation <= 0:
        raise ValueError("generation must be a positive integer")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
