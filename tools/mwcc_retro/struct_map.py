"""Confidence gates for retail GC/1.2.5n backend/regalloc maps."""
from __future__ import annotations

from typing import Any

ACCEPTED_REQUIRED_CONFIDENCE = {
    "live-invariant",
    "operand-extract-confirmed",
    "manual-disassembly-confirmed",
    "dll-seed-confirmed",
}

REQUIRED_GC125N_BACKEND_KEYS = (
    "codegen_start",
    "codegen_end",
    "pcode_pass_boundary",
    "backend_block_list",
    "pcbasicblocks",
    "interference_matrix",
    "coalesce_alias",
    "interferencegraph",
    "n_ignodes",
    "used_vreg_gpr",
    "used_vreg_fpr",
    "build_interference_matrix",
    "real_coalesce",
    "build_adjacency_vectors",
    "simplifygraph",
    "colorgraph",
    "frame_locals",
    "final_scheduler",
)

REQUIRED_STRUCT_FIELDS: dict[str, dict[str, int]] = {
    "IGNode": {
        "next": 0x00,
        "ig_idx": 0x0C,
        "degree": 0x0E,
        "assignedReg": 0x10,
        "flags": 0x12,
        "arraySize": 0x14,
        "array": 0x16,
    },
    "PCode": {
        "opcode": 0x14,
    },
}


def validate_required_backend_map(table: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    entries = table.get("entries") or {}
    structs = table.get("structs") or {}
    for key in REQUIRED_GC125N_BACKEND_KEYS:
        entry = entries.get(key)
        if not entry:
            errors.append(f"missing required backend entry {key}")
            continue
        conf = entry.get("confidence")
        if conf not in ACCEPTED_REQUIRED_CONFIDENCE:
            errors.append(f"{key} confidence {conf} below required gate")
        if not isinstance(entry.get("va"), int) or entry.get("va") <= 0:
            errors.append(f"{key} missing positive va")
    for name, fields in REQUIRED_STRUCT_FIELDS.items():
        struct = structs.get(name)
        if not struct:
            errors.append(f"missing required struct {name}")
            continue
        conf = struct.get("confidence")
        if conf not in ACCEPTED_REQUIRED_CONFIDENCE:
            errors.append(f"struct {name} confidence {conf} below required gate")
        actual = struct.get("fields") or {}
        for field, offset in fields.items():
            if actual.get(field) != offset:
                errors.append(
                    f"struct {name}.{field} expected offset {offset:#x}, got {actual.get(field)!r}"
                )
    return errors
