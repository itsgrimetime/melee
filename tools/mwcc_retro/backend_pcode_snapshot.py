"""Build backend PCode/block events from a retail GC/1.2.5n snapshot.

This reader is deliberately partial. It avoids the ambiguous PCodeBlock
line/loop-weight region and only reads fields already live-probed for #1158.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

ReadU32 = Callable[[int], int]
ReadS16 = Callable[[int], int]

BLOCK_NEXT = 0x00
BLOCK_FIRST_PCODE = 0x14
BLOCK_INDEX = 0x1C
PCODE_NEXT = 0x00
PCODE_OPCODE = 0x14
PCODE_ARG_COUNT = 0x1A

DEFAULT_MAX_BLOCKS = 512
DEFAULT_MAX_PCODE_PER_BLOCK = 4096
MAX_ARG_COUNT = 64
POINTER_LOW = 0x600000
POINTER_HIGH = 0x2000000


def snapshot_pcode_blocks(
    read_u32: ReadU32,
    read_s16: ReadS16,
    block_head: int,
    *,
    pass_id: str,
    pass_name: str,
    opcode_names: Mapping[int, str] | None = None,
    source_stage: str,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
    max_pcode_per_block: int = DEFAULT_MAX_PCODE_PER_BLOCK,
) -> list[dict[str, Any]]:
    """Return partial `block` and `pcode_instruction` backend events."""

    if block_head == 0:
        raise ValueError("block list pointer is null")
    if not _bounded_ptr(block_head):
        raise ValueError(f"invalid block list pointer 0x{block_head:x}")
    if max_blocks <= 0:
        raise ValueError(f"max_blocks must be positive, got {max_blocks}")
    if max_pcode_per_block <= 0:
        raise ValueError(
            f"max_pcode_per_block must be positive, got {max_pcode_per_block}"
        )

    opcode_names = opcode_names or {}
    events: list[dict[str, Any]] = []
    seen_blocks: set[int] = set()
    current_block = block_head
    instruction_order = 0

    for block_order in range(max_blocks):
        if current_block == 0:
            break
        if not _bounded_ptr(current_block):
            raise ValueError(f"invalid PCode block pointer 0x{current_block:x}")
        if current_block in seen_blocks:
            raise ValueError(f"cycle in PCode block list at 0x{current_block:x}")
        seen_blocks.add(current_block)

        next_block = _read_u32(read_u32, current_block + BLOCK_NEXT, "PCodeBlock.next")
        first_pcode = _read_u32(
            read_u32, current_block + BLOCK_FIRST_PCODE, "PCodeBlock.firstPCode"
        )
        block_index = _read_u32(
            read_u32, current_block + BLOCK_INDEX, "PCodeBlock.blockIndex"
        )
        if block_index < 0:
            raise ValueError(f"invalid block index {block_index}")
        block_id = f"B{block_index}"
        events.append(
            {
                "event": "block",
                "id": block_id,
                "order": block_order,
                "succ": [],
                "pred": [],
                "labels": [],
                "source_stage": source_stage,
                "retail_pcode_block": {"ptr": current_block, "next": next_block},
            }
        )

        if first_pcode != 0:
            if not _bounded_ptr(first_pcode):
                raise ValueError(f"invalid first PCode pointer 0x{first_pcode:x}")
            instruction_order = _append_pcode_events(
                events,
                read_u32,
                read_s16,
                first_pcode,
                block_id=block_id,
                start_order=instruction_order,
                pass_id=pass_id,
                pass_name=pass_name,
                opcode_names=opcode_names,
                source_stage=source_stage,
                max_pcode=max_pcode_per_block,
            )
        current_block = next_block
    else:
        raise ValueError(f"PCode block list exceeded max_blocks {max_blocks}")

    return events


def _append_pcode_events(
    events: list[dict[str, Any]],
    read_u32: ReadU32,
    read_s16: ReadS16,
    first_pcode: int,
    *,
    block_id: str,
    start_order: int,
    pass_id: str,
    pass_name: str,
    opcode_names: Mapping[int, str],
    source_stage: str,
    max_pcode: int,
) -> int:
    seen: set[int] = set()
    current = first_pcode
    order = start_order
    for _ in range(max_pcode):
        if current == 0:
            return order
        if not _bounded_ptr(current):
            raise ValueError(f"invalid PCode pointer 0x{current:x}")
        if current in seen:
            raise ValueError(f"cycle in PCode list at 0x{current:x}")
        seen.add(current)

        next_pcode = _read_u32(read_u32, current + PCODE_NEXT, "PCode.next")
        opcode = _read_s16(read_s16, current + PCODE_OPCODE, "PCode.opcode")
        arg_count = _read_s16(read_s16, current + PCODE_ARG_COUNT, "PCode.arg_count")
        if opcode < 0:
            raise ValueError(f"invalid opcode {opcode}")
        if arg_count < 0 or arg_count > MAX_ARG_COUNT:
            raise ValueError(f"invalid arg_count {arg_count}")
        mnemonic = opcode_names.get(opcode, f"op_{opcode}")
        events.append(
            {
                "event": "pcode_instruction",
                "pass_id": pass_id,
                "pass_name": pass_name,
                "id": f"p{order}",
                "block_id": block_id,
                "order": order,
                "opcode": mnemonic,
                "operands": "",
                "normalized": mnemonic,
                "source_stage": source_stage,
                "retail_pcode": {
                    "ptr": current,
                    "next": next_pcode,
                    "opcode": opcode,
                    "arg_count": arg_count,
                },
            }
        )
        order += 1
        current = next_pcode
    raise ValueError(f"PCode list for {block_id} exceeded max_pcode {max_pcode}")


def _bounded_ptr(value: int) -> bool:
    return POINTER_LOW <= int(value) < POINTER_HIGH


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
