"""Confidence gates for retail GC/1.2.5n backend/regalloc maps."""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
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

REQUIRED_PCODE_ARG_CAPTURE_STRUCT_FIELDS: dict[str, dict[str, int]] = {
    "PCode": {**REQUIRED_STRUCT_FIELDS["PCode"], "args": 0x1C},
    "PCodeArg": {
        "kind": 0x00,
        "register_flags": 0x01,
        "payload": 0x02,
    },
}
PCODE_ARG_SIZE = 0x0C

REQUIRED_OBJECT_CAPTURE_KEYS = (
    "arguments",
    "locals",
    "temps",
    "frame_base_size",
    "frame_call_args_size",
)

REQUIRED_OBJECT_CAPTURE_STRUCT_FIELDS: dict[str, dict[str, int]] = {
    "IGNode": {"obj_addr": 0x04},
    "ObjObject": {
        "name_record": 0x0A,
        "type_pointer": 0x0E,
        "stack_offset": 0x2A,
    },
    "ObjectListNode": {"next": 0x00, "object": 0x04},
    "Type": {"size": 0x02},
    "NameRecord": {"text": 0x0A},
}


@dataclass(frozen=True, slots=True)
class ObjectCaptureLayout:
    ignode_obj_addr: int
    objobject_name_record: int
    objobject_type_pointer: int
    objobject_stack_offset: int
    object_list_next: int
    object_list_object: int
    type_size: int
    name_record_text: int
    frame_list_vas: Mapping[str, int]
    frame_base_size_va: int
    frame_call_args_size_va: int

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


_MAX_JSON_SAFE_INTEGER = (1 << 53) - 1


def materialize_json_safe(value: object) -> object:
    """Recursively copy an exact, finite I-JSON-shaped value.

    The trust gates call this before inspecting attacker-controlled containers.
    Exact builtin types prevent Mapping/list subclasses from running code during
    later validation, while the active-container set rejects recursive values.
    """

    active: set[int] = set()

    def visit(item: object, path: str) -> object:
        item_type = type(item)
        if item is None or item_type is bool:
            return item
        if item_type is int:
            if not -_MAX_JSON_SAFE_INTEGER <= item <= _MAX_JSON_SAFE_INTEGER:
                raise ValueError(f"{path} integer is outside the JSON-safe range")
            return item
        if item_type is str:
            try:
                item.encode("utf-8", "strict")
            except UnicodeEncodeError as exc:
                raise ValueError(f"{path} contains an invalid Unicode surrogate") from exc
            return item
        if item_type not in (dict, list):
            raise ValueError(f"{path} has unsupported non-JSON type")

        marker = id(item)
        if marker in active:
            raise ValueError(f"{path} contains a recursive container")
        active.add(marker)
        try:
            if item_type is list:
                return [
                    visit(child, f"{path}[{index}]")
                    for index, child in enumerate(item)
                ]
            result: dict[str, object] = {}
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError(f"{path} object key must be exact string")
                try:
                    key.encode("utf-8", "strict")
                except UnicodeEncodeError as exc:
                    raise ValueError(
                        f"{path} object key contains an invalid Unicode surrogate"
                    ) from exc
                result[key] = visit(child, f"{path}.{key}")
            return result
        finally:
            active.remove(marker)

    return visit(value, "$")


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


def validate_pcode_arg_capture_capability(table: object) -> list[str]:
    """Require the complete inline PCodeArg layout before any raw reads."""

    if not isinstance(table, Mapping):
        return ["PCodeArg capture table must be object"]
    errors: list[str] = []
    structs = table.get("structs")
    if not isinstance(structs, Mapping):
        structs = {}
    for name, fields in REQUIRED_PCODE_ARG_CAPTURE_STRUCT_FIELDS.items():
        struct = structs.get(name)
        if not isinstance(struct, Mapping):
            errors.append(f"missing required {name} struct")
            continue
        if struct.get("confidence") not in ACCEPTED_REQUIRED_CONFIDENCE:
            errors.append(f"struct {name} confidence below required gate")
        actual = struct.get("fields")
        if not isinstance(actual, Mapping):
            actual = {}
        for field, offset in fields.items():
            if actual.get(field) != offset:
                errors.append(
                    f"{name}.{field} expected offset {offset:#x}, "
                    f"got {actual.get(field)!r}"
                )
        if name == "PCodeArg" and struct.get("size") != PCODE_ARG_SIZE:
            errors.append(
                f"PCodeArg size expected {PCODE_ARG_SIZE:#x}, "
                f"got {struct.get('size')!r}"
            )
    return errors


def _proof_site_ids(proof: Mapping[str, object], collection: str) -> list[str]:
    rows = proof.get(collection)
    if not isinstance(rows, list):
        return []
    return [
        row["site_id"]
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("site_id"), str)
    ]


def _validate_gate_site_ids(
    gate: Mapping[str, object],
    *,
    field: str,
    label: str,
    expected: list[str],
) -> list[str]:
    errors: list[str] = []
    value = gate.get(field)
    if not isinstance(value, list) or not value:
        return [f"{label} site IDs must be nonempty list"]
    if any(not isinstance(site_id, str) or not site_id for site_id in value):
        errors.append(f"{label} site IDs must contain nonempty strings")
        return errors
    if len(value) != len(set(value)):
        errors.append(f"{label} site IDs must be unique")
    if value != expected:
        if len(value) == len(expected) and set(value) == set(expected):
            errors.append(f"{label} site IDs must be canonically ordered")
        else:
            errors.append(f"{label} site inventory differs from proof")
    return errors


def validate_pcode_instrumentation_capability(
    table: object, *, proof: Mapping[str, object] | None = None
) -> list[str]:
    """Require one promoted tuple and an exactly matching installed hook set."""

    try:
        table = materialize_json_safe(table)
    except Exception as exc:  # noqa: BLE001 - trust boundary must fail closed
        return [f"PCode instrumentation table could not be materialized: {exc}"]
    errors = list(validate_instrumentation_proof_registry(table))
    if type(table) is not dict:
        errors.append("PCode instrumentation table must be object")
        return errors
    rows = table.get("instrumentation_proofs")
    promoted = (
        [
            row
            for row in rows
            if isinstance(row, Mapping) and row.get("promoted") is True
        ]
        if isinstance(rows, list)
        else []
    )
    if not promoted:
        errors.append("no promoted instrumentation proof")
    elif len(promoted) != 1:
        errors.append("expected exactly one promoted instrumentation proof")

    reader = table.get("backend_reader")
    gate = (
        reader.get("pcode_instrumentation")
        if isinstance(reader, Mapping)
        else None
    )
    if not isinstance(gate, Mapping) or gate.get("validated") is not True:
        errors.append("pcode instrumentation gate is not validated")
        gate = None

    try:
        proof = materialize_json_safe(proof)
    except Exception as exc:  # noqa: BLE001 - trust boundary must fail closed
        errors.append("PCode instrumentation proof could not be materialized")
        errors.append(f"PCode instrumentation proof materialization error: {exc}")
        return errors
    if type(proof) is not dict:
        errors.append("PCode instrumentation proof must be object")
        return errors

    from .backend_instrumentation_proof import proof_sha256, validate_proof_shape

    try:
        errors.extend(validate_proof_shape(proof))
    except Exception:  # noqa: BLE001 - malformed proof must fail closed
        errors.append("PCode instrumentation proof shape validation failed")
    digest = None
    try:
        digest = proof_sha256(proof)
    except Exception:  # noqa: BLE001 - malformed proof must fail closed
        errors.append("PCode instrumentation proof is not canonicalizable")

    if len(promoted) == 1:
        row = promoted[0]
        if proof.get("compiler_executable_sha256") != row.get(
            "compiler_executable_sha256"
        ):
            errors.append("proof compiler digest differs from promoted registry")
        if proof.get("proof_id") != row.get("proof_id"):
            errors.append("proof ID differs from promoted registry")
        if digest != row.get("proof_sha256"):
            errors.append("proof digest differs from promoted registry")

    if gate is not None:
        if len(promoted) == 1:
            row = promoted[0]
            for field in (
                "compiler_executable_sha256",
                "proof_id",
                "proof_sha256",
            ):
                if gate.get(field) != row.get(field):
                    errors.append(
                        f"pcode instrumentation {field} differs from registry"
                    )
        if gate.get("compiler_executable_sha256") != proof.get(
            "compiler_executable_sha256"
        ):
            errors.append("compiler executable digest differs from proof")
        if gate.get("proof_id") != proof.get("proof_id"):
            errors.append("proof ID differs from installed gate")
        for collection, gate_field, label in (
            (
                "operand_rewrite_sites",
                "operand_rewrite_site_ids",
                "operand rewrite",
            ),
            (
                "operand_mutation_sites",
                "operand_mutation_site_ids",
                "operand mutation",
            ),
            ("code_emission_sites", "code_emission_site_ids", "code emission"),
        ):
            errors.extend(
                _validate_gate_site_ids(
                    gate,
                    field=gate_field,
                    label=label,
                    expected=_proof_site_ids(proof, collection),
                )
            )
    return errors


def validate_object_capture_capability(table: object) -> list[str]:
    """Validate the promoted retail ObjObject/frame observational layout."""

    if not isinstance(table, Mapping):
        return ["object capture table must be object"]
    errors: list[str] = []
    reader = table.get("backend_reader")
    if not isinstance(reader, Mapping):
        errors.append("missing object capture backend_reader gate")
    else:
        gate = reader.get("object_capture")
        if not isinstance(gate, Mapping) or gate.get("validated") is not True:
            errors.append("backend_reader.object_capture.validated is not true")

    entries = table.get("entries")
    if not isinstance(entries, Mapping):
        errors.append("object capture entries must be object")
        entries = {}
    for key in REQUIRED_OBJECT_CAPTURE_KEYS:
        entry = entries.get(key)
        if not isinstance(entry, Mapping):
            errors.append(f"missing object capture entry {key}")
            continue
        confidence = entry.get("confidence")
        if confidence not in ACCEPTED_REQUIRED_CONFIDENCE:
            errors.append(f"{key} confidence {confidence} below required gate")
        va = entry.get("va")
        if not isinstance(va, int) or isinstance(va, bool) or va <= 0:
            errors.append(f"{key} missing positive va")

    structs = table.get("structs")
    if not isinstance(structs, Mapping):
        errors.append("object capture structs must be object")
        structs = {}
    for name, expected_fields in REQUIRED_OBJECT_CAPTURE_STRUCT_FIELDS.items():
        struct = structs.get(name)
        if not isinstance(struct, Mapping):
            errors.append(f"missing object capture struct {name}")
            continue
        confidence = struct.get("confidence")
        if confidence not in ACCEPTED_REQUIRED_CONFIDENCE:
            errors.append(f"struct {name} confidence {confidence} below required gate")
        fields = struct.get("fields")
        if not isinstance(fields, Mapping):
            errors.append(f"struct {name} fields must be object")
            continue
        for field, expected in expected_fields.items():
            actual = fields.get(field)
            if (
                not isinstance(actual, int)
                or isinstance(actual, bool)
                or actual != expected
            ):
                errors.append(
                    f"struct {name}.{field} expected offset {expected:#x}, "
                    f"got {actual!r}"
                )
    return errors


def load_object_capture_layout(table: object) -> ObjectCaptureLayout:
    errors = validate_object_capture_capability(table)
    if errors:
        raise ValueError("object capture map failed validation: " + "; ".join(errors))
    assert isinstance(table, Mapping)
    entries = table["entries"]
    structs = table["structs"]
    return ObjectCaptureLayout(
        ignode_obj_addr=structs["IGNode"]["fields"]["obj_addr"],
        objobject_name_record=structs["ObjObject"]["fields"]["name_record"],
        objobject_type_pointer=structs["ObjObject"]["fields"]["type_pointer"],
        objobject_stack_offset=structs["ObjObject"]["fields"]["stack_offset"],
        object_list_next=structs["ObjectListNode"]["fields"]["next"],
        object_list_object=structs["ObjectListNode"]["fields"]["object"],
        type_size=structs["Type"]["fields"]["size"],
        name_record_text=structs["NameRecord"]["fields"]["text"],
        frame_list_vas=MappingProxyType(
            {area: entries[area]["va"] for area in ("arguments", "locals", "temps")}
        ),
        frame_base_size_va=entries["frame_base_size"]["va"],
        frame_call_args_size_va=entries["frame_call_args_size"]["va"],
    )
