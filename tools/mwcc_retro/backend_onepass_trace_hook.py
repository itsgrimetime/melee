"""One-pass GC/1.2.5n backend trace hook.

This hook writes the legacy ``backend-events.v1.jsonl`` stream plus a raw
``backend-object-events.v1.jsonl`` identity sidecar for the requested function.
The full ``debug retro backend`` command uses it behind the
``backend_reader.complete`` gate; ``backend-candidate --one-pass`` reuses it
for candidate-only diagnostics.
"""

import json
import os
import secrets
import tempfile
from pathlib import Path

from tools.mwcc_retro import backend_object_snapshot, struct_map

_OBJECT_EVENT_KINDS = frozenset(
    {"objobject_snapshot", "object_virtual_binding", "object_frame_binding"}
)

_LEGACY_BACKEND_EVENT_KINDS = frozenset(
    {
        "function_start",
        "backend_marker",
        "block",
        "pcode_instruction",
        "regclass",
        "node",
        "edge",
        "coalesce_mapping",
        "coalesce_mapping_empty",
        "simplify_order",
        "select_order",
        "color_decision",
        "frame_state",
    }
)


def _legacy_backend_events(events):
    """Keep Task 7 raw instrumentation out of the stable v1 stream."""

    return [
        dict(event)
        for event in events
        if isinstance(event, dict)
        and event.get("event") in _LEGACY_BACKEND_EVENT_KINDS
    ]


def _emit_pcode_event(state, event, *, site_id, pcode_ptr, lifecycle):
    """Atomically append one site-tagged same-run PCode event."""

    if not isinstance(event, dict):
        raise ValueError("PCode event must be an object")
    sequence = state.get("next_pcode_event_sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise ValueError("next PCode event sequence must be nonnegative integer")
    if not isinstance(site_id, str) or not site_id:
        raise ValueError("PCode event site ID must be non-empty string")
    if (
        not isinstance(pcode_ptr, int)
        or isinstance(pcode_ptr, bool)
        or pcode_ptr <= 0
    ):
        raise ValueError("PCode runtime address must be positive integer")
    lifecycle_position = lifecycle.sequence_at_stop()
    generation = lifecycle.generation("pcode", pcode_ptr)
    if (
        not isinstance(lifecycle_position, int)
        or isinstance(lifecycle_position, bool)
        or lifecycle_position < -1
    ):
        raise ValueError("PCode lifecycle position must be integer at least -1")
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation <= 0
    ):
        raise ValueError("PCode allocation generation must be positive integer")
    row = {
        **event,
        "pcode_event_sequence": sequence,
        "instrumented_site_id": site_id,
        "runtime_address": pcode_ptr,
        "allocation_generation": generation,
        "lifecycle_sequence_at_capture": lifecycle_position,
    }
    state.setdefault("pcode_events", []).append(row)
    state["next_pcode_event_sequence"] = sequence + 1
    return row


def _emit_pcode_mutation_event(
    state,
    *,
    site_id,
    mutation_kind,
    capture_inputs,
    capture_outputs,
):
    """Capture complete mutation sides before publishing either side."""

    inputs = capture_inputs()
    outputs = capture_outputs()
    if not isinstance(inputs, list) or not isinstance(outputs, list):
        raise ValueError("PCode mutation inputs and outputs must be lists")
    sequence = state.get("next_pcode_event_sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise ValueError("next PCode event sequence must be nonnegative integer")
    row = {
        "event": "pcode_mutation",
        "pcode_event_sequence": sequence,
        "instrumented_site_id": site_id,
        "mutation_kind": mutation_kind,
        "inputs": inputs,
        "outputs": outputs,
    }
    state.setdefault("pcode_events", []).append(row)
    state["next_pcode_event_sequence"] = sequence + 1
    return row


_PCODE_EVENT_FIELDS = {
    "operand_rewrite": frozenset(
        {
            "event",
            "pcode_event_sequence",
            "instrumented_site_id",
            "pcode_id",
            "operand_index",
            "operand_lineage_id",
            "role",
            "class_id",
            "class_name",
            "virtual_kind",
            "virtual",
            "ig_id",
            "allocated_physical",
            "runtime_address",
            "allocation_generation",
            "lifecycle_sequence_at_capture",
            "source_stage",
            "confidence",
        }
    ),
    "pcode_mutation": frozenset(
        {
            "event",
            "pcode_event_sequence",
            "instrumented_site_id",
            "mutation_kind",
            "inputs",
            "outputs",
        }
    ),
    "code_emission": frozenset(
        {
            "event",
            "pcode_event_sequence",
            "instrumented_site_id",
            "pcode_id",
            "runtime_address",
            "allocation_generation",
            "lifecycle_sequence_at_capture",
            "emission_snapshot",
            "code_ranges",
        }
    ),
}

_PCODE_EVENT_SITE_COLLECTION = {
    "operand_rewrite": "operand_rewrite_sites",
    "pcode_mutation": "operand_mutation_sites",
    "code_emission": "code_emission_sites",
}

_PCODE_SITE_LABEL = {
    "operand_rewrite_sites": "operand rewrite",
    "operand_mutation_sites": "operand mutation",
    "code_emission_sites": "code emission",
}

_PCODE_ROLES = frozenset({"use", "def", "use-def"})
_PCODE_CLASS_SHAPES = {0: ("gpr", "r"), 1: ("fpr", "f")}
_PCODE_REQUIREMENTS = frozenset(
    {"allocator-rewrite-required", "fixed-physical"}
)
_PCODE_MUTATION_KINDS = frozenset(
    {"update", "clone", "replace", "delete", "create"}
)
_PCODE_STATE_FIELDS = frozenset(
    {
        "pcode_id",
        "runtime_address",
        "allocation_generation",
        "lifecycle_sequence_at_capture",
        "opcode_id",
        "arg_count",
        "operands",
    }
)
_PCODE_OPERAND_FIELDS = frozenset(
    {
        "operand_index",
        "operand_lineage_id",
        "raw_arg_kind_id",
        "raw_payload_sha256",
    }
)
_PCODE_OPERAND_FIELDS_WITH_PARENTS = _PCODE_OPERAND_FIELDS | frozenset(
    {"parent_lineage_ids"}
)
_PCODE_SNAPSHOT_FIELDS = frozenset(
    {
        "stage",
        "lifecycle_sequence_at_capture",
        "runtime_address",
        "allocation_generation",
        "opcode_id",
        "opcode",
        "arg_count",
        "parsed_register_operands",
        "operand_lineage_inventory",
    }
)
_PCODE_PARSED_FIELDS = frozenset(
    {
        "operand_index",
        "role",
        "class_id",
        "raw_arg_kind_id",
        "raw_register_flags",
        "allocation_requirement",
        "operand_lineage_id",
        "virtual_kind",
        "virtual",
        "physical_register",
    }
)
_PCODE_RANGE_FIELDS = frozenset(
    {
        "start",
        "end_exclusive",
        "bytes",
        "relocations",
        "machine_operand_mappings",
    }
)
_PCODE_RELOCATION_FIELDS = frozenset(
    {
        "offset_within_range",
        "relocation_type_id",
        "target_symbol_table_index",
        "target_symbol",
        "addend",
    }
)
_PCODE_MAPPING_FIELDS = frozenset(
    {
        "instruction_offset_within_range",
        "machine_operand_position",
        "machine_operand_key",
        "emission_pcode_operand_index",
        "operand_lineage_id",
        "physical_register",
    }
)


def _pcode_nonnegative(value):
    return type(value) is int and value >= 0


def _pcode_positive(value):
    return type(value) is int and value > 0


def _pcode_lifecycle_position(value):
    return type(value) is int and value >= -1


def _pcode_physical(value):
    return type(value) is int and 0 <= value <= 31


def _pcode_nonempty_string(value):
    return type(value) is str and bool(value)


def _pcode_sha256(value):
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _pcode_exact_fields(row, fields, label, diagnostics):
    if type(row) is not dict:
        diagnostics.append(f"{label} must be object")
        return False
    actual = set(row)
    if actual == fields:
        return True
    missing = sorted(fields - actual)
    unexpected = sorted(actual - fields)
    details = []
    if missing:
        details.append(f"missing {missing!r}")
    if unexpected:
        details.append(f"unexpected {unexpected!r}")
    diagnostics.append(
        f"{label} fields differ from exact schema ({', '.join(details)})"
    )
    return False


def _validate_pcode_identity(row, label, diagnostics):
    if not _pcode_nonempty_string(row.get("pcode_id")):
        diagnostics.append(f"{label} pcode_id must be nonempty string")
    if not _pcode_positive(row.get("runtime_address")):
        diagnostics.append(f"{label} runtime_address must be positive integer")
    if not _pcode_positive(row.get("allocation_generation")):
        diagnostics.append(
            f"{label} allocation_generation must be positive integer"
        )
    if not _pcode_lifecycle_position(
        row.get("lifecycle_sequence_at_capture")
    ):
        diagnostics.append(
            f"{label} lifecycle_sequence_at_capture must be integer at least -1"
        )


def _validate_pcode_operands(
    value,
    arg_count,
    label,
    diagnostics,
    *,
    allow_parents,
):
    if type(value) is not list:
        diagnostics.append(f"{label} operands must be list")
        return []
    indexes = []
    rows = []
    for index, row in enumerate(value):
        row_label = f"{label} operand {index}"
        expected = (
            _PCODE_OPERAND_FIELDS_WITH_PARENTS
            if type(row) is dict and "parent_lineage_ids" in row
            else _PCODE_OPERAND_FIELDS
        )
        _pcode_exact_fields(row, expected, row_label, diagnostics)
        if type(row) is not dict:
            continue
        operand_index = row.get("operand_index")
        if not _pcode_nonnegative(operand_index):
            diagnostics.append(
                f"{row_label} operand_index must be nonnegative integer"
            )
        else:
            indexes.append(operand_index)
        if not _pcode_nonempty_string(row.get("operand_lineage_id")):
            diagnostics.append(
                f"{row_label} operand_lineage_id must be nonempty string"
            )
        if not _pcode_nonnegative(row.get("raw_arg_kind_id")):
            diagnostics.append(
                f"{row_label} raw_arg_kind_id must be nonnegative integer"
            )
        if not _pcode_sha256(row.get("raw_payload_sha256")):
            diagnostics.append(f"{row_label} raw payload digest is invalid")
        if "parent_lineage_ids" in row:
            parents = row.get("parent_lineage_ids")
            if not allow_parents:
                diagnostics.append(f"{row_label} must omit parent_lineage_ids")
            if type(parents) is not list:
                diagnostics.append(f"{row_label} parent_lineage_ids must be list")
            elif any(
                not _pcode_nonempty_string(parent) for parent in parents
            ):
                diagnostics.append(
                    f"{row_label} parent_lineage_ids must contain nonempty strings"
                )
            elif parents != sorted(set(parents)):
                diagnostics.append(
                    f"{row_label} parent_lineage_ids must be sorted and unique"
                )
        rows.append(row)
    if _pcode_nonnegative(arg_count) and len(value) != arg_count:
        diagnostics.append(f"{label} operand count must equal arg_count")
    if indexes != list(range(len(value))):
        diagnostics.append(f"{label} operand indexes must be contiguous from zero")
    return rows


def _validate_pcode_state(row, label, diagnostics, *, allow_parents):
    _pcode_exact_fields(row, _PCODE_STATE_FIELDS, label, diagnostics)
    if type(row) is not dict:
        return
    _validate_pcode_identity(row, label, diagnostics)
    if not _pcode_nonnegative(row.get("opcode_id")):
        diagnostics.append(f"{label} opcode_id must be nonnegative integer")
    arg_count = row.get("arg_count")
    if not _pcode_nonnegative(arg_count):
        diagnostics.append(f"{label} arg_count must be nonnegative integer")
    _validate_pcode_operands(
        row.get("operands"),
        arg_count,
        label,
        diagnostics,
        allow_parents=allow_parents,
    )


def _validate_pcode_parsed_operands(value, inventory, label, diagnostics):
    if type(value) is not list:
        diagnostics.append(f"{label} parsed_register_operands must be list")
        return
    keys = []
    for index, row in enumerate(value):
        row_label = f"{label} parsed operand {index}"
        _pcode_exact_fields(row, _PCODE_PARSED_FIELDS, row_label, diagnostics)
        if type(row) is not dict:
            continue
        operand_index = row.get("operand_index")
        if not _pcode_nonnegative(operand_index):
            diagnostics.append(
                f"{row_label} operand_index must be nonnegative integer"
            )
        elif operand_index >= len(inventory):
            diagnostics.append(f"{row_label} operand_index is outside inventory")
        else:
            inventory_row = inventory[operand_index]
            if (
                inventory_row.get("operand_lineage_id")
                != row.get("operand_lineage_id")
                or inventory_row.get("raw_arg_kind_id")
                != row.get("raw_arg_kind_id")
            ):
                diagnostics.append(
                    f"{row_label} identity differs from operand inventory"
                )
        role = row.get("role")
        if type(role) is not str or role not in _PCODE_ROLES:
            diagnostics.append(f"{row_label} role is invalid")
        class_id = row.get("class_id")
        shape = (
            _PCODE_CLASS_SHAPES.get(class_id)
            if _pcode_nonnegative(class_id)
            else None
        )
        if shape is None:
            diagnostics.append(f"{row_label} class_id must be 0 or 1")
        if not _pcode_nonnegative(row.get("raw_arg_kind_id")):
            diagnostics.append(
                f"{row_label} raw_arg_kind_id must be nonnegative integer"
            )
        if not _pcode_nonnegative(row.get("raw_register_flags")):
            diagnostics.append(
                f"{row_label} raw_register_flags must be nonnegative integer"
            )
        if not _pcode_nonempty_string(row.get("operand_lineage_id")):
            diagnostics.append(
                f"{row_label} operand_lineage_id must be nonempty string"
            )
        requirement = row.get("allocation_requirement")
        if type(requirement) is not str or requirement not in _PCODE_REQUIREMENTS:
            diagnostics.append(f"{row_label} allocation_requirement is invalid")
        elif requirement == "allocator-rewrite-required":
            if (
                shape is None
                or row.get("virtual_kind") != shape[1]
                or not _pcode_nonnegative(row.get("virtual"))
                or row.get("physical_register") is not None
            ):
                diagnostics.append(f"{row_label} virtual register shape is invalid")
        elif (
            row.get("virtual_kind") is not None
            or row.get("virtual") is not None
            or not _pcode_physical(row.get("physical_register"))
        ):
            diagnostics.append(f"{row_label} physical register shape is invalid")
        keys.append(
            (
                operand_index,
                row.get("role"),
                class_id,
                row.get("raw_arg_kind_id"),
                row.get("raw_register_flags"),
            )
        )
    try:
        if keys != sorted(keys):
            diagnostics.append(
                f"{label} parsed register operands must be canonically ordered"
            )
    except TypeError:
        diagnostics.append(f"{label} parsed register operands are not sortable")
    try:
        if len(keys) != len(set(keys)):
            diagnostics.append(f"{label} parsed register operands must be unique")
    except TypeError:
        diagnostics.append(f"{label} parsed register operand keys are invalid")


def _validate_pcode_emission_snapshot(row, event, label, diagnostics):
    _pcode_exact_fields(row, _PCODE_SNAPSHOT_FIELDS, label, diagnostics)
    if type(row) is not dict:
        return
    if row.get("stage") != "code_emission":
        diagnostics.append(f"{label} stage must be code_emission")
    if not _pcode_lifecycle_position(
        row.get("lifecycle_sequence_at_capture")
    ):
        diagnostics.append(
            f"{label} lifecycle_sequence_at_capture must be integer at least -1"
        )
    if not _pcode_positive(row.get("runtime_address")):
        diagnostics.append(f"{label} runtime_address must be positive integer")
    if not _pcode_positive(row.get("allocation_generation")):
        diagnostics.append(
            f"{label} allocation_generation must be positive integer"
        )
    for field in (
        "runtime_address",
        "allocation_generation",
        "lifecycle_sequence_at_capture",
    ):
        if row.get(field) != event.get(field):
            diagnostics.append(f"{label} {field} differs from emission identity")
    if not _pcode_nonnegative(row.get("opcode_id")):
        diagnostics.append(f"{label} opcode_id must be nonnegative integer")
    if not _pcode_nonempty_string(row.get("opcode")):
        diagnostics.append(f"{label} opcode must be nonempty string")
    arg_count = row.get("arg_count")
    if not _pcode_nonnegative(arg_count):
        diagnostics.append(f"{label} arg_count must be nonnegative integer")
    inventory = _validate_pcode_operands(
        row.get("operand_lineage_inventory"),
        arg_count,
        label,
        diagnostics,
        allow_parents=False,
    )
    _validate_pcode_parsed_operands(
        row.get("parsed_register_operands"),
        inventory,
        label,
        diagnostics,
    )


def _validate_pcode_rewrite(row, label, diagnostics):
    _validate_pcode_identity(row, label, diagnostics)
    if not _pcode_nonnegative(row.get("operand_index")):
        diagnostics.append(
            f"{label} operand_index must be nonnegative integer"
        )
    if not _pcode_nonempty_string(row.get("operand_lineage_id")):
        diagnostics.append(
            f"{label} operand_lineage_id must be nonempty string"
        )
    role = row.get("role")
    if type(role) is not str or role not in _PCODE_ROLES:
        diagnostics.append(f"{label} role is invalid")
    class_id = row.get("class_id")
    shape = (
        _PCODE_CLASS_SHAPES.get(class_id)
        if _pcode_nonnegative(class_id)
        else None
    )
    if shape is None:
        diagnostics.append(f"{label} class_id must be 0 or 1")
    elif (
        row.get("class_name") != shape[0]
        or row.get("virtual_kind") != shape[1]
    ):
        diagnostics.append(f"{label} class/name/virtual-kind shape is invalid")
    if not _pcode_nonnegative(row.get("virtual")):
        diagnostics.append(f"{label} virtual must be nonnegative integer")
    if not _pcode_nonnegative(row.get("ig_id")):
        diagnostics.append(f"{label} ig_id must be nonnegative integer")
    elif row.get("ig_id") != row.get("virtual"):
        diagnostics.append(f"{label} ig_id must equal virtual")
    if not _pcode_physical(row.get("allocated_physical")):
        diagnostics.append(f"{label} allocated_physical must be in 0..31")
    if row.get("source_stage") != "allocator_operand_rewrite":
        diagnostics.append(f"{label} source_stage is invalid")
    if row.get("confidence") != "observed":
        diagnostics.append(f"{label} confidence is invalid")


def _validate_pcode_mutation(row, label, diagnostics):
    kind = row.get("mutation_kind")
    if type(kind) is not str or kind not in _PCODE_MUTATION_KINDS:
        diagnostics.append(f"{label} mutation_kind is invalid")
    inputs = row.get("inputs")
    outputs = row.get("outputs")
    if type(inputs) is not list:
        diagnostics.append(f"{label} inputs must be list")
        inputs = []
    if type(outputs) is not list:
        diagnostics.append(f"{label} outputs must be list")
        outputs = []
    for index, state in enumerate(inputs):
        _validate_pcode_state(
            state,
            f"{label} input {index}",
            diagnostics,
            allow_parents=False,
        )
    for index, state in enumerate(outputs):
        _validate_pcode_state(
            state,
            f"{label} output {index}",
            diagnostics,
            allow_parents=True,
        )
    if kind == "update" and (len(inputs), len(outputs)) != (1, 1):
        diagnostics.append(f"{label} update requires exactly one input and output")
    elif kind == "clone" and (len(inputs) != 1 or len(outputs) < 2):
        diagnostics.append(
            f"{label} clone requires one input and two or more outputs"
        )
    elif kind == "replace" and (not inputs or not outputs):
        diagnostics.append(f"{label} replace requires nonempty inputs and outputs")
    elif kind == "delete" and (not inputs or outputs):
        diagnostics.append(f"{label} delete requires inputs and no outputs")
    elif kind == "create" and (inputs or not outputs):
        diagnostics.append(f"{label} create requires no inputs and outputs")


def _validate_pcode_relocations(value, range_size, label, diagnostics):
    if type(value) is not list:
        diagnostics.append(f"{label} relocations must be list")
        return
    keys = []
    for index, row in enumerate(value):
        row_label = f"{label} relocation {index}"
        _pcode_exact_fields(row, _PCODE_RELOCATION_FIELDS, row_label, diagnostics)
        if type(row) is not dict:
            continue
        offset = row.get("offset_within_range")
        for field in (
            "offset_within_range",
            "relocation_type_id",
            "target_symbol_table_index",
        ):
            if not _pcode_nonnegative(row.get(field)):
                diagnostics.append(
                    f"{row_label} {field} must be nonnegative integer"
                )
        if _pcode_nonnegative(offset) and offset >= range_size:
            diagnostics.append(f"{row_label} offset lies outside code range")
        if type(row.get("target_symbol")) is not str:
            diagnostics.append(f"{row_label} target_symbol must be string")
        if type(row.get("addend")) is not int:
            diagnostics.append(f"{row_label} addend must be integer")
        keys.append(
            (
                offset,
                row.get("relocation_type_id"),
                row.get("target_symbol_table_index"),
                row.get("target_symbol"),
                row.get("addend"),
            )
        )
    try:
        if keys != sorted(keys):
            diagnostics.append(f"{label} relocations must be canonically ordered")
        if len(keys) != len(set(keys)):
            diagnostics.append(f"{label} relocations must be unique")
    except TypeError:
        diagnostics.append(f"{label} relocation keys are invalid")


def _validate_pcode_mappings(
    value,
    range_size,
    arg_count,
    label,
    diagnostics,
):
    if type(value) is not list:
        diagnostics.append(f"{label} machine_operand_mappings must be list")
        return
    keys = []
    for index, row in enumerate(value):
        row_label = f"{label} mapping {index}"
        _pcode_exact_fields(row, _PCODE_MAPPING_FIELDS, row_label, diagnostics)
        if type(row) is not dict:
            continue
        instruction_offset = row.get("instruction_offset_within_range")
        operand_position = row.get("machine_operand_position")
        emission_index = row.get("emission_pcode_operand_index")
        for field in (
            "instruction_offset_within_range",
            "machine_operand_position",
            "emission_pcode_operand_index",
        ):
            if not _pcode_nonnegative(row.get(field)):
                diagnostics.append(
                    f"{row_label} {field} must be nonnegative integer"
                )
        if (
            _pcode_nonnegative(instruction_offset)
            and instruction_offset >= range_size
        ):
            diagnostics.append(
                f"{row_label} instruction offset lies outside code range"
            )
        if (
            _pcode_nonnegative(emission_index)
            and _pcode_nonnegative(arg_count)
            and emission_index >= arg_count
        ):
            diagnostics.append(
                f"{row_label} emission operand index lies outside snapshot"
            )
        if not _pcode_nonempty_string(row.get("machine_operand_key")):
            diagnostics.append(
                f"{row_label} machine_operand_key must be nonempty string"
            )
        if not _pcode_nonempty_string(row.get("operand_lineage_id")):
            diagnostics.append(
                f"{row_label} operand_lineage_id must be nonempty string"
            )
        if not _pcode_physical(row.get("physical_register")):
            diagnostics.append(f"{row_label} physical_register must be in 0..31")
        keys.append(
            (
                instruction_offset,
                operand_position,
                emission_index,
                row.get("operand_lineage_id"),
            )
        )
    try:
        if keys != sorted(keys):
            diagnostics.append(
                f"{label} machine operand mappings must be canonically ordered"
            )
        if len(keys) != len(set(keys)):
            diagnostics.append(f"{label} machine operand mappings must be unique")
    except TypeError:
        diagnostics.append(f"{label} machine operand mapping keys are invalid")


def _validate_pcode_code_ranges(value, snapshot, label, diagnostics):
    if type(value) is not list:
        diagnostics.append(f"{label} code_ranges must be list")
        return
    if not value:
        return
    keys = []
    prior_end = None
    arg_count = snapshot.get("arg_count") if type(snapshot) is dict else None
    for index, row in enumerate(value):
        row_label = f"{label} range {index}"
        _pcode_exact_fields(row, _PCODE_RANGE_FIELDS, row_label, diagnostics)
        if type(row) is not dict:
            continue
        start = row.get("start")
        end = row.get("end_exclusive")
        valid_bounds = (
            _pcode_nonnegative(start)
            and _pcode_nonnegative(end)
            and start < end
        )
        if not valid_bounds:
            diagnostics.append(
                f"{row_label} must be ordered nonempty half-open range"
            )
            range_size = 0
        else:
            range_size = end - start
            if prior_end is not None and start < prior_end:
                diagnostics.append(f"{row_label} overlaps prior code range")
            prior_end = end
            keys.append((start, end, row.get("bytes")))
        bytes_hex = row.get("bytes")
        if (
            type(bytes_hex) is not str
            or bytes_hex.lower() != bytes_hex
            or len(bytes_hex) != 2 * range_size
        ):
            diagnostics.append(f"{row_label} bytes must be exact lowercase hex")
        else:
            try:
                bytes.fromhex(bytes_hex)
            except ValueError:
                diagnostics.append(f"{row_label} bytes must be exact lowercase hex")
        _validate_pcode_relocations(
            row.get("relocations"), range_size, row_label, diagnostics
        )
        _validate_pcode_mappings(
            row.get("machine_operand_mappings"),
            range_size,
            arg_count,
            row_label,
            diagnostics,
        )
    try:
        if keys != sorted(keys):
            diagnostics.append(f"{label} code_ranges must be canonically ordered")
    except TypeError:
        diagnostics.append(f"{label} code range keys are invalid")


def _validate_pcode_emission(row, label, diagnostics):
    _validate_pcode_identity(row, label, diagnostics)
    snapshot = row.get("emission_snapshot")
    _validate_pcode_emission_snapshot(
        snapshot,
        row,
        f"{label} emission snapshot",
        diagnostics,
    )
    _validate_pcode_code_ranges(
        row.get("code_ranges"), snapshot, label, diagnostics
    )


def _coverage_site_ids(proof, collection, diagnostics):
    label = _PCODE_SITE_LABEL[collection]
    rows = proof.get(collection) if type(proof) is dict else None
    if type(rows) is not list or not rows:
        diagnostics.append(f"{label} proof site inventory must be nonempty")
        return set()
    result = []
    for index, row in enumerate(rows):
        if type(row) is not dict:
            diagnostics.append(f"{label} proof site {index} must be object")
            continue
        site_id = row.get("site_id")
        if not _pcode_nonempty_string(site_id):
            diagnostics.append(
                f"{label} proof site {index} ID must be nonempty string"
            )
            continue
        result.append(site_id)
    if len(result) != len(set(result)):
        diagnostics.append(f"{label} proof site IDs must be unique")
    return set(result)


def _pcode_instrumentation_status(
    proof,
    *,
    hooked_site_ids,
    events,
    event_cap,
    dropped_events,
    truncated,
    errors,
):
    """Report raw producer coverage without trusting a declared status."""

    diagnostics = []
    try:
        proof = struct_map.materialize_json_safe(proof)
    except Exception as exc:  # noqa: BLE001 - raw coverage must fail closed
        diagnostics.append(
            f"PCode coverage proof could not be materialized: {exc}"
        )
        proof = {}
    if type(proof) is not dict:
        diagnostics.append("PCode coverage proof must be object")
        proof = {}
    try:
        events = struct_map.materialize_json_safe(events)
    except Exception as exc:  # noqa: BLE001 - raw coverage must fail closed
        diagnostics.append(f"PCode events could not be materialized: {exc}")
        events = []
    if type(events) is not list:
        diagnostics.append("PCode events must be list")
        events = []

    if type(errors) is list:
        for index, error in enumerate(errors):
            if type(error) is str:
                diagnostics.append(error)
            else:
                diagnostics.append(
                    f"PCode instrumentation error {index} must be string"
                )
    else:
        diagnostics.append("PCode instrumentation errors must be list")

    rewrite_sites = _coverage_site_ids(
        proof, "operand_rewrite_sites", diagnostics
    )
    mutation_sites = _coverage_site_ids(
        proof, "operand_mutation_sites", diagnostics
    )
    emission_sites = _coverage_site_ids(
        proof, "code_emission_sites", diagnostics
    )
    site_families = {
        "operand_rewrite_sites": rewrite_sites,
        "operand_mutation_sites": mutation_sites,
        "code_emission_sites": emission_sites,
    }
    expected_sites = rewrite_sites | mutation_sites | emission_sites

    if type(hooked_site_ids) is not set:
        diagnostics.append("hooked site IDs must be set")
        hooked = set()
    elif any(
        not _pcode_nonempty_string(site_id)
        for site_id in hooked_site_ids
    ):
        diagnostics.append("hooked site IDs must contain nonempty strings")
        hooked = set()
    else:
        hooked = hooked_site_ids
    if hooked != expected_sites:
        diagnostics.append("hooked site IDs differ from exact proof inventory")

    event_rows = events
    sequences = []
    for index, row in enumerate(event_rows):
        if type(row) is not dict:
            diagnostics.append(f"PCode event {index} must be object")
            continue
        kind = row.get("event")
        if type(kind) is not str or kind not in _PCODE_EVENT_FIELDS:
            diagnostics.append(f"unknown PCode event kind {kind!r}")
            continue
        expected_fields = _PCODE_EVENT_FIELDS[kind]
        exact_fields = _pcode_exact_fields(
            row,
            expected_fields,
            f"{kind} event {index}",
            diagnostics,
        )
        unexpected = sorted(set(row) - expected_fields, key=repr)
        if not exact_fields and unexpected:
            diagnostics.append(f"{kind} event {index} has unexpected fields")
        sequence = row.get("pcode_event_sequence")
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 0
        ):
            diagnostics.append(
                f"PCode event {index} sequence must be nonnegative integer"
            )
        else:
            sequences.append(sequence)
        site_id = row.get("instrumented_site_id")
        collection = _PCODE_EVENT_SITE_COLLECTION[kind]
        if (
            type(site_id) is not str
            or site_id not in site_families[collection]
        ):
            diagnostics.append(
                f"{kind} event site {site_id!r} not in matching proof family"
            )
        if kind == "operand_rewrite":
            _validate_pcode_rewrite(
                row, f"operand_rewrite event {index}", diagnostics
            )
        elif kind == "pcode_mutation":
            _validate_pcode_mutation(
                row, f"pcode_mutation event {index}", diagnostics
            )
        else:
            _validate_pcode_emission(
                row, f"code_emission event {index}", diagnostics
            )
    if sequences != list(range(len(event_rows))):
        diagnostics.append("PCode event sequences must be contiguous from zero")

    valid_cap = (
        type(event_cap) is int
        and event_cap > 0
    )
    if not valid_cap:
        diagnostics.append("PCode event cap must be positive integer")
    valid_dropped = (
        type(dropped_events) is int
        and dropped_events >= 0
    )
    if not valid_dropped:
        diagnostics.append("PCode dropped events must be nonnegative integer")
    if type(truncated) is not bool:
        diagnostics.append("PCode truncated must be boolean")

    complete = (
        not diagnostics
        and bool(event_rows)
        and dropped_events == 0
        and truncated is False
        and len(event_rows) < event_cap
    )
    return {
        "status": "complete" if complete else "partial",
        "operand_rewrite_sites_expected": len(rewrite_sites),
        "operand_rewrite_sites_hooked": len(rewrite_sites & hooked),
        "operand_mutation_sites_expected": len(mutation_sites),
        "operand_mutation_sites_hooked": len(mutation_sites & hooked),
        "code_emission_sites_expected": len(emission_sites),
        "code_emission_sites_hooked": len(emission_sites & hooked),
        "first_event_sequence": sequences[0] if sequences else None,
        "last_event_sequence": sequences[-1] if sequences else None,
        "event_cap": event_cap,
        "dropped_events": dropped_events,
        "truncated": truncated,
        "errors": diagnostics,
        # Task 6 performs the final independent replay before this can be set.
        "capabilities": [],
    }


def _capture_pcode_events(
    snapshot_reader,
    read_u32,
    read_s16,
    read_bytes,
    block_head,
    **kwargs,
):
    """Wire the stopped-process raw reader into the pure PCode snapshotter."""

    return snapshot_reader(
        read_u32,
        read_s16,
        block_head,
        read_bytes=read_bytes,
        **kwargs,
    )


def _validated_pcode_raw_reader(table, read_bytes):
    """Return the raw reader only after the installed layout passes its gate."""

    if struct_map.validate_pcode_arg_capture_capability(table):
        return None
    return read_bytes
_OBJECT_STAGE_ORDER = {"colorgraph_return": 0, "final_scheduler": 1}
_FRAME_AREA_ORDER = {"arguments": 0, "locals": 1, "temps": 2}


def _stopped_lifecycle_inputs(lifecycle):
    """Sample one lifecycle position while the compiler process is stopped."""

    if lifecycle is None:
        return {}
    sequence_reader = getattr(lifecycle, "sequence_at_stop", None)
    generation_for = getattr(lifecycle, "generation", None)
    if not callable(sequence_reader) or not callable(generation_for):
        raise ValueError("lifecycle capture lacks stopped sequence/generation readers")
    sequence = sequence_reader()
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < -1:
        raise ValueError(
            "lifecycle sequence at stopped capture must be an integer at least -1"
        )
    return {"lifecycle_sequence": sequence, "generation_for": generation_for}


def _capture_ig_class_events(
    snapshot_reader,
    read_u32,
    read_s16,
    *,
    read_s32,
    lifecycle,
    ignode_obj_addr_offset,
    object_offsets,
    **kwargs,
):
    """Capture an IG while preserving the pre-lifecycle reader call shape."""

    object_inputs = {"ignode_obj_addr_offset": ignode_obj_addr_offset}
    lifecycle_inputs = _stopped_lifecycle_inputs(lifecycle)
    if lifecycle_inputs:
        object_inputs.update(
            {
                "read_s32": read_s32,
                "object_offsets": object_offsets,
                **lifecycle_inputs,
            }
        )
    return snapshot_reader(read_u32, read_s16, **kwargs, **object_inputs)


def _new_capture_attempt_id():
    """Return a fresh 128-bit identity for one object-capture attempt."""

    return secrets.token_hex(16)


def _canonical_object_events(events):
    """Return deterministic raw Task 5 events, deduplicating snapshots only."""

    snapshots = {}
    other = []
    for raw in events:
        if not isinstance(raw, dict) or raw.get("event") not in _OBJECT_EVENT_KINDS:
            raise ValueError(f"malformed object capture event: {raw!r}")
        row = dict(raw)
        if row["event"] == "objobject_snapshot":
            key = (
                row.get("runtime_address"),
                row.get("allocation_generation"),
                row.get("stage"),
            )
            previous = snapshots.get(key)
            if previous is not None:
                sequence = row.get("lifecycle_sequence_at_capture")
                previous_sequence = previous.get("lifecycle_sequence_at_capture")
                row_content = {
                    field: value
                    for field, value in row.items()
                    if field != "lifecycle_sequence_at_capture"
                }
                previous_content = {
                    field: value
                    for field, value in previous.items()
                    if field != "lifecycle_sequence_at_capture"
                }
                if row_content != previous_content:
                    raise ValueError(f"conflicting ObjObject snapshots for {key!r}")
                if not isinstance(sequence, int) or not isinstance(
                    previous_sequence, int
                ):
                    raise ValueError(f"malformed ObjObject snapshot sequence for {key!r}")
                if sequence > previous_sequence:
                    snapshots[key] = row
            else:
                snapshots[key] = row
        else:
            if row in other:
                raise ValueError(f"duplicate object capture event: {row!r}")
            other.append(row)

    ordered_snapshots = sorted(
        snapshots.values(),
        key=lambda row: (
            row.get("runtime_address"),
            row.get("allocation_generation"),
            _OBJECT_STAGE_ORDER.get(row.get("stage"), -1),
        ),
    )

    def binding_key(row):
        if row["event"] == "object_virtual_binding":
            return (
                0,
                row.get("objobject_ptr"),
                row.get("allocation_generation"),
                row.get("class_id"),
                row.get("virtual_kind"),
                row.get("virtual"),
                row.get("ig_id"),
                row.get("ignode_runtime_address"),
            )
        return (
            1,
            row.get("objobject_ptr"),
            row.get("allocation_generation"),
            _FRAME_AREA_ORDER.get(row.get("area"), -1),
            row.get("list_node_runtime_address"),
            row.get("final_r1_offset"),
        )

    return [*ordered_snapshots, *sorted(other, key=binding_key)]


def _object_capture_status(events, *, errors, cap_reached):
    canonical_errors = sorted(str(error) for error in errors)
    return {
        "status": "partial",
        "events_seen": len(events),
        "cap_reached": bool(cap_reached),
        "errors": canonical_errors,
        # Task 4 intentionally withholds virtual/frame capabilities here.
        "capabilities": [],
    }


def _retain_partial_object_facts(state, error, *, stage):
    facts = [dict(fact) for fact in error.partial_facts]
    state["object_events"].extend(facts)
    state["object_capture_errors"].append(str(error))
    state["errors"].append(
        {
            "stage": stage,
            "error": str(error),
            "object_capture_partial": True,
        }
    )


def _reset_object_capture_state(
    state, *, function_identity, capture_attempt_id=None
):
    attempt_id = capture_attempt_id or _new_capture_attempt_id()
    if not (
        isinstance(attempt_id, str)
        and len(attempt_id) == 32
        and all(char in "0123456789abcdef" for char in attempt_id)
    ):
        raise ValueError("capture attempt ID must be 32 lowercase hex characters")
    if not isinstance(function_identity, dict):
        raise ValueError("object capture function identity must be an object")
    state["object_events"] = []
    state["object_capture_errors"] = []
    state["object_capture_warnings"] = []
    state["object_capture_attempt"] = {
        "capture_attempt_id": attempt_id,
        "function_identity": dict(function_identity),
    }


def _publish_atomic_sidecar(
    path, *, schema_version, events, status, capture_attempt
):
    target = Path(path)
    payload = {
        "schema_version": schema_version,
        "capture_attempt": capture_attempt,
        "capture_status": status,
        "events": events,
        "publication_complete": True,
    }
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _publish_object_sidecar(path, events, status, capture_attempt):
    _publish_atomic_sidecar(
        path,
        schema_version="mwcc-retro-object-events.v1",
        events=events,
        status=status,
        capture_attempt=capture_attempt,
    )


def _publish_pcode_sidecar(path, events, status, capture_attempt):
    _publish_atomic_sidecar(
        path,
        schema_version="mwcc-retro-pcode-events.v1",
        events=events,
        status=status,
        capture_attempt=capture_attempt,
    )


def _finalize_pcode_capture(
    state,
    path,
    *,
    proof,
    hooked_site_ids,
    gate_errors,
    event_cap=8192,
):
    """Publish partial raw PCode evidence with the object-attempt identity."""

    pcode_events = [dict(event) for event in state.get("pcode_events", [])]
    errors = list(gate_errors)

    def status():
        return _pcode_instrumentation_status(
            proof,
            hooked_site_ids=hooked_site_ids,
            events=pcode_events,
            event_cap=event_cap,
            dropped_events=0,
            truncated=len(pcode_events) >= event_cap,
            errors=errors,
        )

    capture_status = status()
    attempt = state["object_capture_attempt"]
    try:
        _publish_pcode_sidecar(path, pcode_events, capture_status, attempt)
    except Exception as exc:  # noqa: BLE001 - preserve prior atomic publication
        message = str(exc)
        errors.append(message)
        state.setdefault("errors", []).append(
            {"stage": "pcode_capture_publish", "error": message}
        )
        capture_status = status()
    return {
        "capture_attempt": attempt,
        "capture_status": capture_status,
        "events": pcode_events,
    }


def _finalize_object_capture(state, path):
    """Publish one attempt and return exactly correlated summary metadata."""

    try:
        object_events = _canonical_object_events(state["object_events"])
    except Exception as exc:  # noqa: BLE001 - malformed facts withhold publication
        object_events = []
        message = str(exc)
        state["object_capture_errors"].append(message)
        state["errors"].append(
            {"stage": "object_capture_finalize", "error": message}
        )

    def status():
        errors = state["object_capture_errors"]
        cap_reached = any(
            token in error
            for error in errors
            for token in ("max_nodes", "max_objects", "exceeds", "exceeded")
        )
        return _object_capture_status(
            object_events,
            errors=errors,
            cap_reached=cap_reached,
        )

    object_status = status()
    attempt = state["object_capture_attempt"]
    try:
        _publish_object_sidecar(path, object_events, object_status, attempt)
    except Exception as exc:  # noqa: BLE001 - retain the prior valid sidecar
        message = str(exc)
        state["object_capture_errors"].append(message)
        state["errors"].append(
            {"stage": "object_capture_publish", "error": message}
        )
        object_status = status()
    return {
        "capture_attempt": attempt,
        "capture_status": object_status,
        "events": object_events,
        "warnings": list(state["object_capture_warnings"]),
    }


def _frame_object_events(frame_event):
    events = []
    for row in frame_event.get("objects", []):
        snapshot = row.get("object_snapshot")
        if not isinstance(snapshot, dict):
            continue
        events.append({"event": "objobject_snapshot", **snapshot})
        events.append(
            {
                "event": "object_frame_binding",
                "source_stage": frame_event.get("source_stage"),
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
            }
        )
    return events


def _try_capture_pcode_stage(state, stage, capture_pcode, *, fallback_stage):
    if state["pcode_captured"]:
        return True
    try:
        capture_pcode(stage)
        return True
    except Exception as exc:  # noqa: BLE001 - later backend stages can still retry
        state["warnings"].append(
            {
                "stage": stage,
                "warning": (
                    f"PCode {stage} snapshot skipped; "
                    f"{fallback_stage} fallback will be tried: {exc}"
                ),
            }
        )
        return False


def intervene(ctx):
    import json
    import os

    from tools.mwcc_retro import (
        backend_colorgraph_trace,
        backend_frame_state,
        backend_ig_snapshot,
        backend_pcode_snapshot,
        backend_trace_assembler,
        struct_map,
    )

    gdb = ctx.gdb
    cad = ctx.cad
    entries = ctx.table.get("entries", {})
    out_events = ctx.out_dir + "/backend-events.v1.jsonl"
    out_object_events = ctx.out_dir + "/backend-object-events.v1.json"
    out_pcode_events = ctx.out_dir + "/backend-pcode-events.v1.json"
    out_summary = ctx.out_dir + "/backend-onepass-candidate.json"
    source_file = os.environ.get("RETRO_SOURCE", "")
    requested = os.environ.get("RETRO_FUNCTION", ctx.fn)
    lifecycle_capture = getattr(ctx, "lifecycle_capture", None)
    pcode_raw_reader = _validated_pcode_raw_reader(ctx.table, ctx.read)
    object_layout = struct_map.load_object_capture_layout(ctx.table)
    object_offsets = backend_object_snapshot.ObjObjectOffsets(
        name_record=object_layout.objobject_name_record,
        type_pointer=object_layout.objobject_type_pointer,
        type_size=object_layout.type_size,
        stack_offset=object_layout.objobject_stack_offset,
    )
    list_offsets = backend_object_snapshot.FrameListOffsets(
        next=object_layout.object_list_next,
        object=object_layout.object_list_object,
    )

    def parse_aliases():
        try:
            values = json.loads(os.environ.get("RETRO_FUNCTION_ALIASES", "[]"))
        except Exception:  # noqa: BLE001 - malformed caller env should not kill tracing
            return []
        if not isinstance(values, list):
            return []
        result = []
        seen = set()
        for value in values:
            if not isinstance(value, str):
                continue
            text = value.strip()
            if not text or text in seen:
                continue
            result.append(text)
            seen.add(text)
        return result

    function_aliases = parse_aliases()
    match_names = {
        name
        for name in [requested, ctx.fn, *function_aliases]
        if isinstance(name, str) and name
    }

    def function_matches(info):
        return info.get("name") in match_names

    def identity_payload(matched_name):
        aliases = []
        seen = set()
        for name in [*function_aliases, matched_name]:
            if not isinstance(name, str) or not name or name in {requested, ctx.fn}:
                continue
            if name in seen:
                continue
            aliases.append(name)
            seen.add(name)
        return {
            "requested": requested,
            "canonical_name": requested,
            "symbol_name": matched_name or requested,
            "source_name": ctx.fn,
            "aliases": aliases,
            "source_file": source_file,
        }

    def entry_va(key, fallback=None):
        entry = entries.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("va"), int):
            return entry["va"]
        return fallback

    def read_s16(va):
        return int.from_bytes(ctx.read(va, 2), "little", signed=True)

    def read_s32(va):
        return int.from_bytes(ctx.read(va, 4), "little", signed=True)

    def read_u32(va):
        return ctx.u32(va)

    def read_cstr(va, limit=96):
        data = ctx.read(va, limit)
        end = data.find(b"\x00")
        if end >= 0:
            data = data[:end]
        return data.decode("latin-1", errors="replace")

    def bounded_ptr(value):
        return isinstance(value, int) and 0x600000 <= value < 0x2000000

    def bounded_code_ptr(value):
        return isinstance(value, int) and 0x400000 <= value < 0x600000

    def append_event(event):
        with open(out_events, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")

    def current_function_name():
        sp = int(gdb.parse_and_eval("$esp"))
        obj_addr = read_u32(sp + 8)
        try:
            obj = cad.MwccObject.load(obj_addr, load_linkname=False)
            return {"addr": obj_addr, "name": obj.name}
        except Exception as exc:  # noqa: BLE001 - hook reports and continues
            return {"addr": obj_addr, "error": str(exc)}

    try:
        cad.load_opcode_info()
        opcode_names = {
            index: info.mnemonic.lower()
            for index, info in enumerate(cad.MWCC_OPCODE_INFO)
        }
    except Exception:  # noqa: BLE001 - op names are useful but not required
        opcode_names = {}

    class_names = {0: "gpr", 1: "fpr"}
    used_vreg_keys = {0: "used_vreg_gpr", 1: "used_vreg_fpr"}
    class_reserved = {0: [1, 2], 1: []}
    volatile_regs = {0: [0] + list(range(3, 13)), 1: list(range(14))}
    nonvolatile_regs = {0: list(range(31, 12, -1)), 1: list(range(31, 13, -1))}
    internal_pcs = {
        "select_start": entry_va("colorgraph_select_start"),
        "candidates_ready": entry_va("colorgraph_candidates_ready"),
        "assign_volatile": entry_va("colorgraph_assign_volatile"),
        "assign_nonvolatile": entry_va("colorgraph_assign_nonvolatile"),
        "spill": entry_va("colorgraph_spill"),
    }
    frame_vas = dict(object_layout.frame_list_vas)
    frame_base_size_va = object_layout.frame_base_size_va
    frame_call_args_size_va = object_layout.frame_call_args_size_va
    required = [
        "codegen_start",
        "codegen_end",
        "pcode_pass_boundary",
        "pcbasicblocks",
        "colorgraph",
        "interferencegraph",
        "used_vreg_gpr",
        "used_vreg_fpr",
        "final_scheduler",
        *[
            key
            for key in (
                "colorgraph_select_start",
                "colorgraph_candidates_ready",
                "colorgraph_assign_volatile",
                "colorgraph_assign_nonvolatile",
                "colorgraph_spill",
            )
        ],
    ]
    missing = [key for key in required if not isinstance(entry_va(key), int)]

    state = {
        "active": False,
        "matched": False,
        "function_start_emitted": False,
        "pcode_captured": False,
        "pcode_boundary_failed": False,
        "frame_captured": False,
        "captured_classes": set(),
        "pending_classes": set(),
        "return_breakpoints": [],
        "active_colorgraph": None,
        "current_decision": None,
        "class_iters": {},
        "exact_decisions_by_class": {},
        "matched_function_name": None,
        "functions_seen": [],
        "passes_seen": [],
        "classes_seen": [],
        "decisions_seen": [],
        "errors": [],
        "warnings": [],
        "object_events": [],
        "object_capture_errors": [],
        "object_capture_warnings": [],
        "pcode_events": [],
        "next_pcode_event_sequence": 0,
    }
    _reset_object_capture_state(
        state,
        function_identity=identity_payload(ctx.fn),
    )

    def emit_function_start():
        if state["function_start_emitted"]:
            return
        append_event(
            {
                "event": "function_start",
                "name": requested,
                "identity": identity_payload(state.get("matched_function_name") or ctx.fn),
                "source_file": source_file,
            }
        )
        state["function_start_emitted"] = True

    def capture_pcode(stage):
        if state["pcode_captured"]:
            return
        block_head = read_u32(entry_va("pcbasicblocks"))
        events = _capture_pcode_events(
            backend_pcode_snapshot.snapshot_pcode_blocks,
            read_u32,
            read_s16,
            pcode_raw_reader,
            block_head,
            pass_id="pcode_snapshot",
            pass_name="PCode Snapshot",
            opcode_names=opcode_names,
            source_stage=stage,
        )
        for event in events:
            append_event(event)
        state["passes_seen"].append(
            {
                "pass_id": "pcode_snapshot",
                "pass_name": "PCode Snapshot",
                "source_stage": stage,
                "blocks": sum(1 for event in events if event["event"] == "block"),
                "instructions": sum(
                    1 for event in events if event["event"] == "pcode_instruction"
                ),
            }
        )
        state["pcode_captured"] = True

    def capture_frame(stage):
        if state["frame_captured"]:
            return
        try:
            lifecycle_inputs = _stopped_lifecycle_inputs(lifecycle_capture)
            event = backend_frame_state.snapshot_frame_state(
                read_u32,
                read_s32,
                read_cstr,
                list_vas=frame_vas,
                frame_base_size_va=frame_base_size_va,
                frame_call_args_size_va=frame_call_args_size_va,
                source_stage=stage,
                object_offsets=object_offsets,
                list_offsets=list_offsets,
                name_record_text_offset=object_layout.name_record_text,
                **lifecycle_inputs,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to probe-shaped names
            if isinstance(exc, backend_object_snapshot.PartialObjectCaptureError):
                _retain_partial_object_facts(state, exc, stage=stage)
            state["object_capture_warnings"].append(
                f"frame_state fallback: {exc}"
            )
            state["warnings"].append(
                {"stage": stage, "warning": f"frame_state fallback: {exc}"}
            )
            probe_frame = backend_frame_state.snapshot_probe_frame_state(
                read_u32,
                read_s32,
                read_cstr,
                list_vas=frame_vas,
                frame_base_size_va=frame_base_size_va,
                frame_call_args_size_va=frame_call_args_size_va,
                object_offsets=object_offsets,
                list_offsets=list_offsets,
                name_record_text_offset=object_layout.name_record_text,
            )
            event = backend_trace_assembler.frame_events_from_map_probe_payload(
                {"events": [{"stage": stage, "frame_state": probe_frame}]}
            )[0]
        state["object_events"].extend(_frame_object_events(event))
        append_event(event)
        state["frame_captured"] = True

    def reset_for_function(matched_name):
        state["active"] = True
        state["matched"] = True
        state["function_start_emitted"] = False
        state["pcode_captured"] = False
        state["pcode_boundary_failed"] = False
        state["frame_captured"] = False
        state["captured_classes"] = set()
        state["pending_classes"] = set()
        state["return_breakpoints"] = []
        state["active_colorgraph"] = None
        state["current_decision"] = None
        state["class_iters"] = {}
        state["exact_decisions_by_class"] = {}
        state["matched_function_name"] = matched_name
        _reset_object_capture_state(
            state,
            function_identity=identity_payload(matched_name),
        )
        state["pcode_events"] = []
        state["next_pcode_event_sequence"] = 0

    class CodegenStart(gdb.Breakpoint):
        def stop(self):
            info = current_function_name()
            state["functions_seen"].append(info)
            if function_matches(info):
                reset_for_function(info.get("name"))
                emit_function_start()
                append_event(
                    {
                        "event": "backend_marker",
                        "name": "codegen_start",
                        "pc": int(gdb.parse_and_eval("$pc")),
                        "function": ctx.fn,
                        "source_file": source_file,
                    }
                )
            else:
                state["active"] = False
            return False

    class PCodeSnapshot(gdb.Breakpoint):
        def stop(self):
            if (
                not state["active"]
                or state["pcode_captured"]
                or state["pcode_boundary_failed"]
            ):
                return False
            if not _try_capture_pcode_stage(
                state,
                "pcode_pass_boundary",
                capture_pcode,
                fallback_stage="final_scheduler",
            ):
                state["pcode_boundary_failed"] = True
            return False

    class Colorgraph(gdb.Breakpoint):
        def stop(self):
            if not state["active"]:
                return False
            try:
                sp = int(gdb.parse_and_eval("$esp"))
                class_id = read_u32(sp + 4)
                class_name = class_names.get(class_id)
                if class_name is None:
                    state["object_capture_errors"].append(
                        f"unknown rclass {class_id}"
                    )
                    state["errors"].append(
                        {"stage": "colorgraph", "error": f"unknown rclass {class_id}"}
                    )
                    return False
                if class_id in state["captured_classes"] or class_id in state["pending_classes"]:
                    return False

                graph_global = entry_va("interferencegraph")
                used_global = entry_va(used_vreg_keys[class_id])
                graph = read_u32(graph_global)
                return_pc = read_u32(sp)
                colorgraph_head = read_u32(sp + 8)
                n_virtuals = read_s16(used_global)
                if not bounded_ptr(graph):
                    raise ValueError(f"interferencegraph value {graph:#x} is not bounded")
                if colorgraph_head != 0 and not bounded_ptr(colorgraph_head):
                    raise ValueError(f"colorgraph head value {colorgraph_head:#x} is not bounded")
                if not bounded_code_ptr(return_pc):
                    raise ValueError(f"colorgraph return pc {return_pc:#x} is not bounded")
                if n_virtuals <= 0:
                    return False

                state["pending_classes"].add(class_id)
                state["active_colorgraph"] = {
                    "class_id": class_id,
                    "class_name": class_name,
                    "graph": graph,
                    "n_virtuals": n_virtuals,
                    "return_pc": return_pc,
                }

                fired = {"done": False}

                class ColorgraphReturn(gdb.Breakpoint):
                    def stop(self):
                        if fired["done"]:
                            return False
                        fired["done"] = True
                        try:
                            events = _capture_ig_class_events(
                                backend_ig_snapshot.post_colorgraph_class_events,
                                read_u32,
                                read_s16,
                                read_s32=read_s32,
                                lifecycle=lifecycle_capture,
                                ignode_obj_addr_offset=object_layout.ignode_obj_addr,
                                object_offsets=object_offsets,
                                graph_va=graph,
                                head_ptr=colorgraph_head,
                                n_ignodes=n_virtuals,
                                class_id=class_id,
                                class_name=class_name,
                                function_name=ctx.fn,
                            )
                            state["object_events"].extend(
                                event
                                for event in events
                                if event.get("event") in _OBJECT_EVENT_KINDS
                            )
                            filtered = [
                                event
                                for event in events
                                if event.get("event") != "color_decision"
                                and event.get("event") not in _OBJECT_EVENT_KINDS
                            ]
                            for event in filtered:
                                append_event(event)
                            exact = state["exact_decisions_by_class"].get(class_id, [])
                            for event in exact:
                                append_event(event)
                            order = next(
                                (
                                    event.get("order", [])
                                    for event in events
                                    if event.get("event") == "select_order"
                                ),
                                [],
                            )
                            state["captured_classes"].add(class_id)
                            state["classes_seen"].append(
                                {
                                    "class_id": class_id,
                                    "class_name": class_name,
                                    "nodes": n_virtuals,
                                    "order_nodes": len(order),
                                    "exact_color_decisions": len(exact),
                                }
                            )
                        except Exception as exc:  # noqa: BLE001 - summarize in payload
                            if isinstance(
                                exc,
                                backend_object_snapshot.PartialObjectCaptureError,
                            ):
                                _retain_partial_object_facts(
                                    state, exc, stage="colorgraph_return"
                                )
                            else:
                                state["object_capture_errors"].append(str(exc))
                                state["errors"].append(
                                    {
                                        "stage": "colorgraph_return",
                                        "class_id": class_id,
                                        "error": str(exc),
                                    }
                                )
                        finally:
                            state["pending_classes"].discard(class_id)
                            if state.get("active_colorgraph", {}).get("return_pc") == return_pc:
                                state["active_colorgraph"] = None
                                state["current_decision"] = None
                        return False

                state["return_breakpoints"].append(ColorgraphReturn(f"*{return_pc:#x}"))
            except Exception as exc:  # noqa: BLE001 - summarize in payload
                if "class_id" in locals():
                    state["pending_classes"].discard(class_id)
                state["object_capture_errors"].append(str(exc))
                state["errors"].append({"stage": "colorgraph", "error": str(exc)})
            return False

    def mask_to_regs(mask, regs):
        return [phys for phys in regs if mask & (1 << phys)]

    def assigned_phys_or_none(ig_id, active):
        graph = active["graph"]
        n_ignodes = active["n_virtuals"]
        if ig_id < 0 or ig_id >= n_ignodes:
            return None
        node_ptr = read_u32(graph + ig_id * 4)
        if not bounded_ptr(node_ptr):
            return None
        flags = read_s16(node_ptr + 0x12) & 0xFF
        assigned = read_s16(node_ptr + 0x10)
        if flags & 0x04:
            return None
        if assigned < 0 or assigned >= 32:
            return None
        return assigned

    def current_blockers(active, node_ptr, available_mask, candidate_mask):
        blocked = []
        seen = set()
        array_size = read_s16(node_ptr + 0x14)
        if array_size < 0 or array_size > 2048:
            raise ValueError(f"invalid colorgraph neighbor count {array_size}")
        for index in range(array_size):
            holder = read_s16(node_ptr + 0x16 + index * 2)
            phys = assigned_phys_or_none(holder, active)
            if phys is None:
                continue
            if not (available_mask & (1 << phys)):
                continue
            if candidate_mask & (1 << phys):
                continue
            key = (holder, phys)
            if key in seen:
                continue
            seen.add(key)
            blocked.append(
                {
                    "phys": phys,
                    "reason": "interferer-assigned-phys",
                    "holder_ig_id": holder,
                    "holder_assigned_phys": phys,
                    "provenance": "colorgraph_neighbor_scan",
                }
            )
        return blocked

    def begin_decision():
        active = state.get("active_colorgraph")
        if not active:
            return
        if state.get("current_decision") is not None:
            state["errors"].append(
                {
                    "stage": "select_start",
                    "error": "new colorgraph decision started before previous decision closed",
                    "raw": state["current_decision"].get("raw", []),
                }
            )
            state["current_decision"] = None
        class_id = active["class_id"]
        class_name = active["class_name"]
        node_ptr = int(gdb.parse_and_eval("$ebx"))
        if not bounded_ptr(node_ptr):
            raise ValueError(f"colorgraph EBX node pointer {node_ptr:#x} is not bounded")
        sp = int(gdb.parse_and_eval("$esp"))
        available_mask = read_u32(sp)
        ig_id = read_s16(node_ptr + 0x0C)
        flags = read_s16(node_ptr + 0x12) & 0xFF
        if ig_id < 0 or ig_id >= active["n_virtuals"]:
            raise ValueError(
                f"colorgraph selected ig_id {ig_id} outside {active['n_virtuals']}"
            )
        iteration = state["class_iters"].get(class_id, 0)
        state["class_iters"][class_id] = iteration + 1
        decision_id = f"{class_name}-i{iteration}"
        nonvolatile_available = mask_to_regs(available_mask, nonvolatile_regs[class_id])
        start = {
            "event": "colorgraph_select_start",
            "id": decision_id,
            "class_id": class_id,
            "class_name": class_name,
            "iter": iteration,
            "ig_id": ig_id,
            "available_mask": available_mask,
            "pc": int(gdb.parse_and_eval("$pc")),
            "esp": sp,
            "ebx": node_ptr,
            "node_state_before_select": {
                "precolored": False,
                "coalesced": bool(flags & 0x04),
                "spill_marked": bool(flags & 0x01),
                "rematerialized": False,
            },
            "reserved_or_precolored_filtered": class_reserved[class_id],
            "volatile_pool_before": mask_to_regs(available_mask, volatile_regs[class_id]),
            "nonvolatile_dispense_before": {
                "next": nonvolatile_available[0] if nonvolatile_available else None,
                "remaining": nonvolatile_available,
            },
        }
        state["current_decision"] = {
            "id": decision_id,
            "node_ptr": node_ptr,
            "available_mask": available_mask,
            "raw": [start],
        }

    def capture_candidates():
        active = state.get("active_colorgraph")
        current = state.get("current_decision")
        if not active or not current:
            return
        candidate_mask = int(gdb.parse_and_eval("$eax")) & 0xFFFFFFFF
        current["raw"].append(
            {
                "event": "colorgraph_candidates_ready",
                "id": current["id"],
                "candidate_mask": candidate_mask,
                "pc": int(gdb.parse_and_eval("$pc")),
                "eax": int(gdb.parse_and_eval("$eax")) & 0xFFFFFFFF,
                "blocked_candidates": current_blockers(
                    active,
                    current["node_ptr"],
                    current["available_mask"],
                    candidate_mask,
                ),
            }
        )

    def finish_assignment(assigned_phys, chosen_source, tie_rule):
        current = state.get("current_decision")
        if not current:
            return
        class_id = state["active_colorgraph"]["class_id"]
        available_mask = current["available_mask"]
        volatile_after = mask_to_regs(available_mask, volatile_regs[class_id])
        nonvolatile_before = mask_to_regs(available_mask, nonvolatile_regs[class_id])
        nonvolatile_after = list(nonvolatile_before)
        consumed_nonvolatile = None
        if chosen_source == "volatile_pool":
            volatile_after = [phys for phys in volatile_after if phys != assigned_phys]
        elif chosen_source == "nonvolatile_dispense":
            consumed_nonvolatile = assigned_phys
            nonvolatile_after = [
                phys for phys in nonvolatile_after if phys != assigned_phys
            ]
        current["raw"].append(
            {
                "event": "colorgraph_assignment",
                "id": current["id"],
                "assigned_phys": assigned_phys,
                "pc": int(gdb.parse_and_eval("$pc")),
                "eax": int(gdb.parse_and_eval("$eax")) & 0xFFFFFFFF,
                "ecx": int(gdb.parse_and_eval("$ecx")) & 0xFFFFFFFF,
                "chosen_source": chosen_source,
                "volatile_pool_after": volatile_after,
                "nonvolatile_dispense_after": {
                    "consumed": consumed_nonvolatile,
                    "remaining": nonvolatile_after,
                },
                "tie_rule": tie_rule,
                "decision_rule": "lowest_available_or_nonvolatile_dispense",
            }
        )
        emit_current_decision()

    def finish_spill():
        current = state.get("current_decision")
        if not current:
            return
        current["raw"].append(
            {
                "event": "colorgraph_spill",
                "id": current["id"],
                "reason": "no_available_color",
            }
        )
        emit_current_decision()

    def emit_current_decision():
        current = state.get("current_decision")
        if not current:
            return
        try:
            decisions = backend_colorgraph_trace.assemble_color_decisions(current["raw"])
            for decision in decisions:
                class_id = decision["class_id"]
                state["exact_decisions_by_class"].setdefault(class_id, []).append(decision)
                state["decisions_seen"].append(
                    {
                        "class_id": decision["class_id"],
                        "class_name": decision["class_name"],
                        "ig_id": decision["ig_id"],
                        "assigned_phys": decision["assigned_phys"],
                    }
                )
        except Exception as exc:  # noqa: BLE001 - keep probing later decisions
            state["errors"].append(
                {"id": current.get("id"), "error": str(exc), "raw": current.get("raw", [])}
            )
        finally:
            state["current_decision"] = None

    class InternalColorgraphBreakpoint(gdb.Breakpoint):
        def __init__(self, name, va):
            self.name = name
            super().__init__(f"*{va:#x}")

        def stop(self):
            if not state.get("active_colorgraph"):
                return False
            try:
                if self.name == "select_start":
                    begin_decision()
                elif self.name == "candidates_ready":
                    capture_candidates()
                elif self.name == "assign_volatile":
                    finish_assignment(
                        int(gdb.parse_and_eval("$ecx")) & 0xFFFF,
                        "volatile_pool",
                        "first_volatile_available",
                    )
                elif self.name == "assign_nonvolatile":
                    finish_assignment(
                        int(gdb.parse_and_eval("$eax")) & 0xFFFF,
                        "nonvolatile_dispense",
                        "top_down_nonvolatile_dispense",
                    )
                elif self.name == "spill":
                    finish_spill()
            except Exception as exc:  # noqa: BLE001 - report and continue
                state["errors"].append({"stage": self.name, "error": str(exc)})
                if self.name in {"assign_volatile", "assign_nonvolatile", "spill"}:
                    state["current_decision"] = None
            return False

    class FinalScheduler(gdb.Breakpoint):
        def stop(self):
            if state["active"]:
                if not state["pcode_captured"]:
                    _try_capture_pcode_stage(
                        state,
                        "final_scheduler",
                        capture_pcode,
                        fallback_stage="codegen_end",
                    )
                try:
                    capture_frame("final_scheduler")
                except Exception as exc:  # noqa: BLE001 - codegen_end can still fallback
                    state["object_capture_errors"].append(str(exc))
                    state["errors"].append({"stage": "final_scheduler", "error": str(exc)})
            return False

    class CodegenEnd(gdb.Breakpoint):
        def stop(self):
            if state["active"]:
                if not state["pcode_captured"]:
                    try:
                        capture_pcode("codegen_end")
                    except Exception as exc:  # noqa: BLE001 - summarize in payload
                        state["errors"].append({"stage": "codegen_end_pcode", "error": str(exc)})
                if not state["frame_captured"]:
                    try:
                        capture_frame("codegen_end")
                    except Exception as exc:  # noqa: BLE001 - summarize in payload
                        state["object_capture_errors"].append(str(exc))
                        state["errors"].append({"stage": "codegen_end_frame", "error": str(exc)})
                append_event(
                    {
                        "event": "backend_marker",
                        "name": "codegen_end",
                        "pc": int(gdb.parse_and_eval("$pc")),
                        "function": ctx.fn,
                        "source_file": source_file,
                    }
                )
                state["active"] = False
            return False

    if os.path.exists(out_events):
        os.remove(out_events)

    if missing:
        print("[retro] ABORT: one-pass backend candidate missing entries " + ", ".join(missing))
    else:
        CodegenStart(f"*{entry_va('codegen_start'):#x}")
        PCodeSnapshot(f"*{entry_va('pcode_pass_boundary'):#x}")
        Colorgraph(f"*{entry_va('colorgraph'):#x}")
        FinalScheduler(f"*{entry_va('final_scheduler'):#x}")
        for name, va in internal_pcs.items():
            if isinstance(va, int):
                InternalColorgraphBreakpoint(name, va)
        CodegenEnd(f"*{entry_va('codegen_end'):#x}")

    try:
        ctx.cont()
    finally:
        object_capture = _finalize_object_capture(state, out_object_events)
        pcode_gate_errors = [
            *struct_map.validate_pcode_arg_capture_capability(ctx.table),
            *struct_map.validate_pcode_instrumentation_capability(ctx.table),
        ]
        pcode_capture = _finalize_pcode_capture(
            state,
            out_pcode_events,
            proof={
                "operand_rewrite_sites": [],
                "operand_mutation_sites": [],
                "code_emission_sites": [],
            },
            hooked_site_ids=set(),
            gate_errors=pcode_gate_errors,
        )
        payload = {
            "schema_version": "mwcc-retro-backend-onepass-candidate.v1",
            "compiler": {"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
            "requested_function": ctx.fn,
            "requested_function_matched": state["matched"],
            "functions_seen": state["functions_seen"],
            "passes_seen": state["passes_seen"],
            "classes_seen": state["classes_seen"],
            "decisions_seen": state["decisions_seen"],
            "internal_breakpoints": internal_pcs,
            "errors": state["errors"],
            "warnings": state["warnings"],
            "object_capture_attempt": object_capture["capture_attempt"],
            "object_capture": object_capture["capture_status"],
            "object_capture_warnings": object_capture["warnings"],
            "pcode_capture_attempt": pcode_capture["capture_attempt"],
            "pcode_capture": pcode_capture["capture_status"],
            "notes": [
                "One-pass retail backend event stream.",
                "Diagnostic sidecar for trace assembly and completeness checks.",
            ],
        }
        with open(out_summary, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
