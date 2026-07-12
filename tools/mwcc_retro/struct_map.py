"""Confidence gates for retail GC/1.2.5n backend/regalloc maps."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

INSTRUMENTATION_PROOF_SCHEMA = "mwcc-retro-lifetime-proof.v1"
_INSTRUMENTATION_PROOF_ROW_FIELDS = frozenset(
    {
        "compiler_executable_sha256",
        "proof_id",
        "proof_sha256",
        "promoted",
    }
)
_LOWER_HEX = frozenset("0123456789abcdef")

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
    "PCodeBlock": {
        "next": 0x00,
        "firstPCode": 0x14,
        "blockIndex": 0x1C,
    },
    "PCode": {
        "next": 0x00,
        "opcode": 0x14,
        "arg_count": 0x1A,
    },
}

REQUIRED_PCODE_SNAPSHOT_STRUCT_FIELDS = {
    "PCodeBlock": REQUIRED_STRUCT_FIELDS["PCodeBlock"],
    "PCode": REQUIRED_STRUCT_FIELDS["PCode"],
}

REQUIRED_BACKEND_READER_FAMILIES = (
    "function_start",
    "backend_marker",
    "block",
    "pcode_instruction",
    "regclass",
    "node",
    "edge",
    "coalesce_mapping",
    "simplify_order",
    "select_order",
    "color_decision",
    "frame_state",
)

REQUIRED_BACKEND_IG_SNAPSHOT_FAMILIES = (
    "function_start",
    "backend_marker",
    "regclass",
    "node",
    "edge",
    "coalesce_mapping",
    "coalesce_mapping_empty",
    "simplify_order",
    "select_order",
    "color_decision",
)

REQUIRED_BACKEND_COLORGRAPH_INTERNAL_KEYS = (
    "colorgraph_select_start",
    "colorgraph_candidates_ready",
    "colorgraph_assign_volatile",
    "colorgraph_assign_nonvolatile",
    "colorgraph_spill",
)

REQUIRED_BACKEND_PCODE_SNAPSHOT_FAMILIES = (
    "function_start",
    "backend_marker",
    "block",
    "pcode_instruction",
)


def load_gc125n_struct_map() -> dict[str, Any]:
    """Load the installed GC/1.2.5n struct map and proof registry."""
    table_path = Path(__file__).with_name("tables") / "gc_125n.json"
    return json.loads(table_path.read_text())


def _is_lower_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _LOWER_HEX for char in value)
    )


def validate_instrumentation_proof_registry(table: object) -> list[str]:
    """Validate the independent proof trust registry without promoting entries."""
    if not isinstance(table, Mapping):
        return ["instrumentation proof registry must be object"]
    errors: list[str] = []
    if table.get("instrumentation_proof_schema") != INSTRUMENTATION_PROOF_SCHEMA:
        errors.append(
            f"instrumentation_proof_schema must be {INSTRUMENTATION_PROOF_SCHEMA}"
        )
    rows = table.get("instrumentation_proofs")
    if not isinstance(rows, list):
        errors.append("instrumentation_proofs must be list")
        return errors
    seen: set[tuple[object, object, object]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"instrumentation proof registry row {index} must be object")
            continue
        if set(row) != _INSTRUMENTATION_PROOF_ROW_FIELDS:
            errors.append(
                f"instrumentation proof registry row {index} has unexpected fields"
            )
        compiler_digest = row.get("compiler_executable_sha256")
        proof_id = row.get("proof_id")
        digest = row.get("proof_sha256")
        if not _is_lower_sha256(compiler_digest):
            errors.append(
                f"instrumentation proof registry row {index} compiler_executable_sha256 "
                "must be 64 lowercase hex"
            )
        if not isinstance(proof_id, str) or not proof_id:
            errors.append(
                f"instrumentation proof registry row {index} proof_id must be non-empty string"
            )
        if not _is_lower_sha256(digest):
            errors.append(
                f"instrumentation proof registry row {index} proof_sha256 must be 64 lowercase hex"
            )
        if not isinstance(row.get("promoted"), bool):
            errors.append(
                f"instrumentation proof registry row {index} promoted must be boolean"
            )
        if (
            isinstance(compiler_digest, str)
            and isinstance(proof_id, str)
            and isinstance(digest, str)
        ):
            key = (compiler_digest, proof_id, digest)
            if key in seen:
                errors.append("duplicate instrumentation proof registry tuple")
            seen.add(key)
    return errors


def validate_required_backend_map(table: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    entries = table.get("entries") or {}
    if not isinstance(entries, Mapping):
        errors.append("entries must be object")
        entries = {}
    structs = table.get("structs") or {}
    if not isinstance(structs, Mapping):
        errors.append("structs must be object")
        structs = {}
    for key in REQUIRED_GC125N_BACKEND_KEYS:
        entry = entries.get(key)
        if entry is None:
            errors.append(f"missing required backend entry {key}")
            continue
        if not isinstance(entry, Mapping):
            errors.append(f"backend entry {key} must be object")
            continue
        conf = entry.get("confidence")
        if conf not in ACCEPTED_REQUIRED_CONFIDENCE:
            errors.append(f"{key} confidence {conf} below required gate")
        if not isinstance(entry.get("va"), int) or entry.get("va") <= 0:
            errors.append(f"{key} missing positive va")
    for name, fields in REQUIRED_STRUCT_FIELDS.items():
        struct = structs.get(name)
        if struct is None:
            errors.append(f"missing required struct {name}")
            continue
        if not isinstance(struct, Mapping):
            errors.append(f"struct {name} must be object")
            continue
        conf = struct.get("confidence")
        if conf not in ACCEPTED_REQUIRED_CONFIDENCE:
            errors.append(f"struct {name} confidence {conf} below required gate")
        actual = struct.get("fields")
        if not isinstance(actual, Mapping):
            errors.append(f"struct {name} fields must be object")
            continue
        for field, offset in fields.items():
            if actual.get(field) != offset:
                errors.append(
                    f"struct {name}.{field} expected offset {offset:#x}, got {actual.get(field)!r}"
                )
    return errors


def validate_backend_reader_capability(table: dict[str, Any]) -> list[str]:
    """Validate that the runtime reader, not just the address map, is complete.

    This gate intentionally stays separate from validate_required_backend_map().
    It lets GC/1.2.5n addresses/structs graduate from live evidence without
    allowing the marker-only backend hook to masquerade as a consumable trace.
    """
    errors: list[str] = []
    reader = table.get("backend_reader")
    if reader is None:
        return ["missing backend_reader capability gate"]
    if not isinstance(reader, Mapping):
        return ["backend_reader must be object"]
    if reader.get("complete") is not True:
        errors.append("backend_reader.complete is not true")
    families = reader.get("event_families")
    if not isinstance(families, list):
        errors.append("backend_reader.event_families must be list")
        families = []
    family_set = {family for family in families if isinstance(family, str)}
    for family in REQUIRED_BACKEND_READER_FAMILIES:
        if family not in family_set:
            errors.append(f"backend_reader missing event family {family}")
    return errors


def validate_backend_ig_snapshot_capability(table: dict[str, Any]) -> list[str]:
    """Validate the partial reader coverage needed for IG snapshots."""
    errors: list[str] = []
    reader = table.get("backend_reader")
    if reader is None:
        return ["missing backend_reader capability gate"]
    if not isinstance(reader, Mapping):
        return ["backend_reader must be object"]
    families = reader.get("partial_event_families")
    if not isinstance(families, list):
        errors.append("backend_reader.partial_event_families must be list")
        families = []
    family_set = {family for family in families if isinstance(family, str)}
    for family in REQUIRED_BACKEND_IG_SNAPSHOT_FAMILIES:
        if family not in family_set:
            errors.append(f"backend_reader missing partial event family {family}")
    for family in sorted(family_set - set(REQUIRED_BACKEND_IG_SNAPSHOT_FAMILIES)):
        errors.append(f"backend_reader unexpected partial event family {family}")
    entries = table.get("entries") or {}
    if not isinstance(entries, Mapping):
        entries = {}
    for key in REQUIRED_BACKEND_COLORGRAPH_INTERNAL_KEYS:
        entry = entries.get(key)
        if not isinstance(entry, Mapping):
            errors.append(f"missing {key}")
            continue
        if not isinstance(entry.get("va"), int) or entry.get("va") <= 0:
            errors.append(f"{key} missing positive va")
        conf = entry.get("confidence")
        if conf not in ACCEPTED_REQUIRED_CONFIDENCE:
            errors.append(f"{key} confidence {conf} below required gate")
    return errors


def validate_backend_pcode_snapshot_capability(table: dict[str, Any]) -> list[str]:
    """Validate the partial reader coverage needed for PCode snapshots."""
    errors: list[str] = []
    reader = table.get("backend_reader")
    if reader is None:
        return ["missing backend_reader capability gate"]
    if not isinstance(reader, Mapping):
        return ["backend_reader must be object"]
    families = reader.get("partial_pcode_event_families")
    if not isinstance(families, list):
        errors.append("backend_reader.partial_pcode_event_families must be list")
        families = []
    family_set = {family for family in families if isinstance(family, str)}
    for family in REQUIRED_BACKEND_PCODE_SNAPSHOT_FAMILIES:
        if family not in family_set:
            errors.append(f"backend_reader missing partial PCode event family {family}")
    for family in sorted(family_set - set(REQUIRED_BACKEND_PCODE_SNAPSHOT_FAMILIES)):
        errors.append(f"backend_reader unexpected partial PCode event family {family}")
    structs = table.get("structs") or {}
    if not isinstance(structs, Mapping):
        errors.append("structs must be object")
        structs = {}
    for name, fields in REQUIRED_PCODE_SNAPSHOT_STRUCT_FIELDS.items():
        struct = structs.get(name)
        if struct is None:
            errors.append(f"missing required PCode snapshot struct {name}")
            continue
        if not isinstance(struct, Mapping):
            errors.append(f"struct {name} must be object")
            continue
        conf = struct.get("confidence")
        if conf not in ACCEPTED_REQUIRED_CONFIDENCE:
            errors.append(f"struct {name} confidence {conf} below required gate")
        actual = struct.get("fields")
        if not isinstance(actual, Mapping):
            errors.append(f"struct {name} fields must be object")
            continue
        for field, offset in fields.items():
            if actual.get(field) != offset:
                errors.append(
                    f"struct {name}.{field} expected offset {offset:#x}, got {actual.get(field)!r}"
                )
    return errors
