"""Validation and trust lookup for retail backend instrumentation proofs."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import rfc8785

from .struct_map import (
    load_gc125n_struct_map,
    materialize_json_safe,
    validate_instrumentation_proof_registry,
)

PROOF_SCHEMA = "mwcc-retro-lifetime-proof.v1"
PROOF_MODE = "allocation-generation"
PROOF_BASIS = "exhaustive-static-callgraph-and-disassembly"

ENTITY_KINDS = frozenset({"objobject", "pcode"})
COMPILER_STAGES = frozenset(
    {
        "frontend",
        "optimizer",
        "backend-lowering",
        "colorgraph",
        "scheduler",
        "backend-finalize",
    }
)
OPERAND_ROLES = frozenset({"use", "def", "use-def"})
CAPTURE_STAGES = frozenset(
    {"allocator_input", "mutation_output", "code_emission"}
)
ALLOCATION_STATES = frozenset({"virtual", "physical", "non-allocator"})
CONSTRUCTOR_KINDS = frozenset({"generic-fixed", "generic-variadic", "custom"})
CUSTOM_CONSTRUCTOR_OPCODES = frozenset({3, 4, 12, 13, 15, 16, 199})

_PROOF_FIELDS = frozenset(
    {
        "schema_version",
        "proof_id",
        "compiler_executable_sha256",
        "runtime_hook_manifest_sha256",
        "mode",
        "allocation_sites",
        "free_sites",
        "operand_rewrite_sites",
        "operand_mutation_sites",
        "code_emission_sites",
        "operand_rules",
        "opcode_table",
        "initialization_address",
        "proof_basis",
    }
)
_LIFECYCLE_SITE_FIELDS = frozenset(
    {"site_id", "address", "entity_kind", "compiler_stage"}
)
_PCODE_SITE_FIELDS = frozenset({"site_id", "address", "compiler_stage"})
_DESCRIPTOR_FIELDS = frozenset(
    {
        "opcode_id",
        "descriptor_index",
        "format_code",
        "expansion",
        "raw_arg_kind_id",
        "role",
        "register_form",
        "class_id",
        "virtual_kind",
        "state_rules",
    }
)
_EXPANSION_FIELDS = frozenset({"kind", "count"})
_STATE_RULE_FIELDS = frozenset(
    {
        "capture_stage",
        "register_flags_mask",
        "register_flags_value",
        "register_value_min",
        "register_value_max",
        "allocation_state",
    }
)
_OPCODE_FIELDS = frozenset(
    {
        "opcode_id",
        "mnemonic",
        "format_string",
        "constructor_kind",
        "custom_constructor_addresses",
    }
)
_HEX_DIGITS = frozenset("0123456789abcdef")
_STAGE_RANK = {"allocator_input": 0, "mutation_output": 1, "code_emission": 2}
_STATE_RANK = {"virtual": 0, "physical": 1, "non-allocator": 2}
_REGISTER_COUPLING = {
    "gpr": (0, 0, "r"),
    "fpr": (1, 1, "f"),
    "vector": (9, 9, "v"),
    "special": (2, None, None),
    "cr": (3, None, None),
}


@dataclass(frozen=True)
class InstrumentationProof:
    proof_id: str
    compiler_executable_sha256: str
    payload: Mapping[str, object]
    sha256: str


@dataclass(frozen=True, slots=True)
class ExpandedOperandDescriptor:
    operand_index: int
    descriptor_index: int
    raw_arg_kind_id: int
    role: str
    register_form: str
    class_id: int | None
    virtual_kind: str | None
    state_rules: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class OperandState:
    allocation_state: str
    virtual: int | None
    physical_register: int | None


def proof_sha256(payload: Mapping[str, object]) -> str:
    """Return the RFC 8785 canonical SHA-256 digest of a proof payload."""

    return hashlib.sha256(rfc8785.dumps(dict(payload))).hexdigest()


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _is_positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _is_u8(value: object) -> bool:
    return type(value) is int and 0 <= value <= 0xFF


def _is_u16(value: object) -> bool:
    return type(value) is int and 0 <= value <= 0xFFFF


def _is_lower_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(char in _HEX_DIGITS for char in value)
    )


def _unexpected_fields(
    value: Mapping[str, object], expected: frozenset[str], label: str
) -> str | None:
    extra = sorted(set(value) - expected, key=repr)
    missing = sorted(expected - set(value))
    if not extra and not missing:
        return None
    details: list[str] = []
    if extra:
        details.append(f"unexpected {extra!r}")
    if missing:
        details.append(f"missing {missing!r}")
    return f"{label} fields: {', '.join(details)}"


def _validate_site_inventory(
    payload: Mapping[str, object], collection: str, *, lifecycle: bool
) -> tuple[list[str], list[tuple[str, int]]]:
    errors: list[str] = []
    sites = payload.get(collection)
    label = collection.removesuffix("_sites").replace("_", " ")
    if type(sites) is not list:
        return [f"{collection} must be list"], []
    if not sites:
        errors.append(f"{collection} must not be empty")
    expected = _LIFECYCLE_SITE_FIELDS if lifecycle else _PCODE_SITE_FIELDS
    sort_keys: list[tuple[object, ...]] = []
    valid: list[tuple[str, int]] = []
    seen: set[tuple[object, ...]] = set()
    sortable = True
    for index, site in enumerate(sites):
        if type(site) is not dict:
            errors.append(f"{label} site {index} must be object")
            sortable = False
            continue
        field_error = _unexpected_fields(site, expected, f"unexpected {label} site")
        if field_error:
            errors.append(field_error)
        site_id = site.get("site_id")
        address = site.get("address")
        stage = site.get("compiler_stage")
        entity_kind = site.get("entity_kind") if lifecycle else None
        if type(site_id) is not str or not site_id:
            errors.append(f"{label} site {index} site_id must be non-empty string")
        if not _is_positive_int(address):
            errors.append(f"{label} site {index} address must be positive integer")
        if type(stage) is not str or stage not in COMPILER_STAGES:
            errors.append(f"{label} site {index} has unknown compiler_stage {stage!r}")
        if lifecycle and (
            type(entity_kind) is not str or entity_kind not in ENTITY_KINDS
        ):
            errors.append(f"{label} site {index} has unknown entity_kind {entity_kind!r}")
        if type(site_id) is str and site_id and _is_positive_int(address):
            valid.append((site_id, address))
        row_key = (
            (entity_kind, address, site_id, stage)
            if lifecycle
            else (address, site_id, stage)
        )
        try:
            duplicate = row_key in seen
            seen.add(row_key)
        except TypeError:
            duplicate = False
        if duplicate:
            errors.append(f"duplicate {label} site")
        sort_keys.append(
            (entity_kind, address, site_id) if lifecycle else (address, site_id)
        )
        sortable = (
            sortable
            and _is_positive_int(address)
            and type(site_id) is str
            and (not lifecycle or type(entity_kind) is str)
        )
    if sortable and sort_keys != sorted(sort_keys):
        errors.append(f"{collection} must be canonically ordered")
    return errors, valid


def _validate_opcode_table(
    payload: Mapping[str, object],
) -> tuple[list[str], dict[int, Mapping[str, object]]]:
    errors: list[str] = []
    rows = payload.get("opcode_table")
    if type(rows) is not list:
        return ["opcode_table must be list"], {}
    ids: list[int] = []
    mnemonics: list[str] = []
    result: dict[int, Mapping[str, object]] = {}
    for index, row in enumerate(rows):
        if type(row) is not dict:
            errors.append(f"opcode table row {index} must be object")
            continue
        field_error = _unexpected_fields(row, _OPCODE_FIELDS, "unexpected opcode table")
        if field_error:
            errors.append(field_error)
        opcode_id = row.get("opcode_id")
        mnemonic = row.get("mnemonic")
        format_string = row.get("format_string")
        constructor = row.get("constructor_kind")
        addresses = row.get("custom_constructor_addresses")
        if not _is_nonnegative_int(opcode_id):
            errors.append(f"opcode table row {index} opcode_id must be nonnegative integer")
        else:
            ids.append(opcode_id)
            result[opcode_id] = row
        if type(mnemonic) is not str or not mnemonic:
            errors.append(f"opcode table row {index} mnemonic must be non-empty string")
        else:
            mnemonics.append(mnemonic)
        if type(format_string) is not str:
            errors.append(f"opcode table row {index} format_string must be string")
        if type(constructor) is not str or constructor not in CONSTRUCTOR_KINDS:
            errors.append(f"opcode table row {index} constructor_kind is invalid")
        if type(addresses) is not list:
            errors.append(
                f"opcode table row {index} custom_constructor_addresses must be list"
            )
            addresses = []
        valid_addresses = all(_is_positive_int(address) for address in addresses)
        if not valid_addresses:
            errors.append(f"opcode table row {index} constructor address is invalid")
        if valid_addresses and addresses != sorted(set(addresses)):
            errors.append(
                f"opcode table row {index} constructor addresses must be ascending and unique"
            )
        if constructor == "custom" and not addresses:
            errors.append("custom opcode must have constructor addresses")
        if (
            type(constructor) is str
            and constructor in {"generic-fixed", "generic-variadic"}
            and addresses
        ):
            errors.append("generic opcode must not have constructor addresses")
        format_codes = _format_codes(format_string) if type(format_string) is str else []
        if constructor == "generic-variadic" and format_codes[-1:] != ["V"]:
            errors.append("generic-variadic opcode must use final V descriptor")
        if constructor == "generic-fixed" and "V" in format_codes:
            errors.append("generic-fixed opcode must not use V descriptor")
        if (
            type(constructor) is str
            and constructor in {"generic-fixed", "generic-variadic"}
            and any(code in {"?", "t"} for code in format_codes)
        ):
            errors.append("generic opcode must not guess custom ? or t format")
        if (
            _is_nonnegative_int(opcode_id)
            and opcode_id in CUSTOM_CONSTRUCTOR_OPCODES
            and constructor != "custom"
        ):
            errors.append(f"opcode {opcode_id} must use audited custom constructor")
    if ids != list(range(468)):
        errors.append("opcode IDs must be exactly 0..467")
    if len(mnemonics) != len(set(mnemonics)):
        errors.append("opcode mnemonics must be unique")
    if ids and ids != sorted(ids):
        errors.append("opcode_table must be canonically ordered")
    return errors, result


def _format_codes(value: str) -> list[str]:
    return [char for char in value if char not in {"=", ",", "#"} and not char.isspace()]


def _state_rule_key(rule: Mapping[str, object]) -> tuple[object, ...]:
    return (
        _STAGE_RANK.get(rule.get("capture_stage"), 99)
        if type(rule.get("capture_stage")) is str
        else 99,
        rule.get("register_flags_mask"),
        rule.get("register_flags_value"),
        rule.get("register_value_min"),
        rule.get("register_value_max"),
        _STATE_RANK.get(rule.get("allocation_state"), 99)
        if type(rule.get("allocation_state")) is str
        else 99,
    )


def _flag_predicates_overlap(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    left_mask = left.get("register_flags_mask")
    right_mask = right.get("register_flags_mask")
    left_value = left.get("register_flags_value")
    right_value = right.get("register_flags_value")
    if not all(_is_u8(value) for value in (left_mask, right_mask, left_value, right_value)):
        return False
    return ((left_value ^ right_value) & (left_mask & right_mask)) == 0


def _validate_state_rules(
    value: object, register_form: object, label: str, errors: list[str]
) -> None:
    if type(value) is not list:
        errors.append(f"{label} state_rules must be list")
        return
    if register_form != "none" and not value:
        errors.append("register descriptor must have state rules")
    keys: list[tuple[object, ...]] = []
    valid: list[Mapping[str, object]] = []
    for index, rule in enumerate(value):
        if type(rule) is not dict:
            errors.append(f"{label} state rule {index} must be object")
            continue
        field_error = _unexpected_fields(rule, _STATE_RULE_FIELDS, f"{label} state rule {index}")
        if field_error:
            errors.append(field_error)
        stage = rule.get("capture_stage")
        mask = rule.get("register_flags_mask")
        flags_value = rule.get("register_flags_value")
        value_min = rule.get("register_value_min")
        value_max = rule.get("register_value_max")
        state = rule.get("allocation_state")
        if type(stage) is not str or stage not in CAPTURE_STAGES:
            errors.append(f"{label} state rule {index} capture_stage is invalid")
        if not _is_u8(mask) or not _is_u8(flags_value):
            errors.append(f"{label} state rule {index} flag predicate must be unsigned byte")
        elif flags_value & ~mask:
            errors.append(f"{label} state rule {index} flags value exceeds mask")
        if not _is_u16(value_min) or not _is_u16(value_max):
            errors.append(f"{label} state rule {index} value range must be unsigned 16-bit")
        elif value_min > value_max:
            errors.append(f"{label} state rule {index} value range is reversed")
        if type(state) is not str or state not in ALLOCATION_STATES:
            errors.append(f"{label} state rule {index} allocation_state is invalid")
        if (
            type(register_form) is str
            and register_form in {"gpr", "fpr", "vector"}
            and (type(state) is not str or state not in {"virtual", "physical"})
        ):
            errors.append(f"{label} allocator register state is invalid")
        if type(register_form) is str and register_form in {"special", "cr"} and state != "non-allocator":
            errors.append(f"{register_form} registers may only be non-allocator")
        keys.append(_state_rule_key(rule))
        valid.append(rule)
    try:
        if keys != sorted(keys):
            errors.append(f"{label} state rules must be canonically ordered")
    except TypeError:
        errors.append(f"{label} state rules are not sortable")
    for index, left in enumerate(valid):
        for right in valid[index + 1 :]:
            if (
                left.get("capture_stage") == right.get("capture_stage")
                and _is_u16(left.get("register_value_min"))
                and _is_u16(left.get("register_value_max"))
                and _is_u16(right.get("register_value_min"))
                and _is_u16(right.get("register_value_max"))
                and max(left["register_value_min"], right["register_value_min"])
                <= min(left["register_value_max"], right["register_value_max"])
                and _flag_predicates_overlap(left, right)
            ):
                errors.append(f"{label} has overlapping state rules")


def _validate_descriptors(
    payload: Mapping[str, object], opcodes: Mapping[int, Mapping[str, object]]
) -> list[str]:
    errors: list[str] = []
    rows = payload.get("operand_rules")
    if type(rows) is not list:
        return ["operand_rules must be list"]
    keys: list[tuple[int, int]] = []
    by_opcode: dict[int, list[Mapping[str, object]]] = {}
    for index, row in enumerate(rows):
        label = f"operand descriptor {index}"
        if type(row) is not dict:
            errors.append(f"{label} must be object")
            continue
        field_error = _unexpected_fields(row, _DESCRIPTOR_FIELDS, label)
        if field_error:
            errors.append(field_error)
        opcode_id = row.get("opcode_id")
        descriptor_index = row.get("descriptor_index")
        if not _is_nonnegative_int(opcode_id):
            errors.append(f"{label} opcode_id must be nonnegative integer")
        elif opcode_id not in opcodes:
            errors.append(f"{label} references unknown opcode_id")
        if not _is_nonnegative_int(descriptor_index):
            errors.append(f"{label} descriptor_index must be nonnegative integer")
        if _is_nonnegative_int(opcode_id) and _is_nonnegative_int(descriptor_index):
            keys.append((opcode_id, descriptor_index))
            by_opcode.setdefault(opcode_id, []).append(row)
        format_code = row.get("format_code")
        if type(format_code) is not str or len(format_code) != 1 or format_code == "#":
            errors.append(f"{label} format_code must be one non-# character")
        expansion = row.get("expansion")
        if type(expansion) is not dict:
            errors.append(f"{label} expansion must be object")
        else:
            field_error = _unexpected_fields(expansion, _EXPANSION_FIELDS, f"{label} expansion")
            if field_error:
                errors.append(field_error)
            kind = expansion.get("kind")
            count = expansion.get("count")
            if kind == "one" and count != 1:
                errors.append(f"{label} one expansion count must be 1")
            elif kind == "fixed" and (not _is_positive_int(count) or count < 2):
                errors.append(f"{label} fixed expansion count must be at least 2")
            elif kind == "remaining" and count is not None:
                errors.append(f"{label} remaining expansion count must be null")
            elif type(kind) is not str or kind not in {"one", "fixed", "remaining"}:
                errors.append(f"{label} expansion kind is invalid")
            if format_code == "Y" and (kind != "fixed" or count != 8):
                errors.append("Y expansion count must be 8")
            if format_code == "V" and kind != "remaining":
                errors.append("V must use remaining expansion")
            if format_code != "V" and kind == "remaining":
                errors.append("remaining expansion must use V")
        if not _is_u8(row.get("raw_arg_kind_id")):
            errors.append(f"{label} raw_arg_kind_id must be unsigned byte")
        if type(row.get("role")) is not str or row.get("role") not in OPERAND_ROLES:
            errors.append(f"{label} operand role is invalid")
        form = row.get("register_form")
        raw_kind = row.get("raw_arg_kind_id")
        class_id = row.get("class_id")
        virtual_kind = row.get("virtual_kind")
        if type(form) is str and form in _REGISTER_COUPLING:
            expected = _REGISTER_COUPLING[form]
            if (raw_kind, class_id, virtual_kind) != expected:
                errors.append(f"{form} register coupling is invalid")
        elif form == "none":
            if raw_kind in {0, 1, 2, 3, 9} or class_id is not None or virtual_kind is not None:
                errors.append("none operand coupling is invalid")
        else:
            errors.append(f"{label} register_form is invalid")
        state_rules = row.get("state_rules")
        if form == "none" and state_rules != []:
            errors.append("none descriptor must have no state rules")
        _validate_state_rules(state_rules, form, label, errors)
    if len(keys) != len(set(keys)):
        errors.append("duplicate operand descriptor")
    if keys != sorted(keys):
        errors.append("operand_rules must be canonically ordered")
    for opcode_id, opcode in opcodes.items():
        descriptors = by_opcode.get(opcode_id, [])
        indexes = [row.get("descriptor_index") for row in descriptors]
        if indexes != list(range(len(descriptors))):
            errors.append(f"opcode {opcode_id} descriptor indices must be contiguous")
        codes = [row.get("format_code") for row in descriptors]
        format_string = opcode.get("format_string")
        if type(format_string) is str and codes != _format_codes(format_string):
            errors.append(f"opcode {opcode_id} descriptors do not reproduce format string")
        for descriptor_index, descriptor in enumerate(descriptors):
            expansion = descriptor.get("expansion")
            if (
                type(expansion) is dict
                and expansion.get("kind") == "remaining"
                and descriptor_index != len(descriptors) - 1
            ):
                errors.append("remaining expansion must be final")
    return errors


def validate_proof_shape(payload: object) -> tuple[str, ...]:
    """Validate the closed, canonically ordered lifetime-proof schema."""

    try:
        payload = materialize_json_safe(payload)
    except Exception as exc:  # noqa: BLE001 - proof trust boundary fails closed
        return (f"instrumentation proof could not be materialized: {exc}",)
    if type(payload) is not dict:
        return ("instrumentation proof must be object",)
    errors: list[str] = []
    field_error = _unexpected_fields(payload, _PROOF_FIELDS, "unexpected proof")
    if field_error:
        errors.append(field_error)
    if payload.get("schema_version") != PROOF_SCHEMA:
        errors.append(f"schema_version must be {PROOF_SCHEMA}")
    if type(payload.get("proof_id")) is not str or not payload.get("proof_id"):
        errors.append("proof_id must be non-empty string")
    if not _is_lower_sha256(payload.get("compiler_executable_sha256")):
        errors.append("compiler_executable_sha256 must be 64 lowercase hex")
    if not _is_lower_sha256(payload.get("runtime_hook_manifest_sha256")):
        errors.append("runtime_hook_manifest_sha256 must be 64 lowercase hex")
    if payload.get("mode") != PROOF_MODE:
        errors.append(f"mode must be {PROOF_MODE}")
    if not _is_positive_int(payload.get("initialization_address")):
        errors.append("initialization_address must be positive integer")
    if payload.get("proof_basis") != PROOF_BASIS:
        errors.append(f"proof_basis must be {PROOF_BASIS}")

    all_sites: list[tuple[str, int]] = []
    for collection in ("allocation_sites", "free_sites"):
        site_errors, sites = _validate_site_inventory(payload, collection, lifecycle=True)
        errors.extend(site_errors)
        all_sites.extend(sites)
    for collection in (
        "operand_rewrite_sites",
        "operand_mutation_sites",
        "code_emission_sites",
    ):
        site_errors, sites = _validate_site_inventory(payload, collection, lifecycle=False)
        errors.extend(site_errors)
        all_sites.extend(sites)
    site_ids = [site_id for site_id, _ in all_sites]
    addresses = [address for _, address in all_sites]
    if len(site_ids) != len(set(site_ids)):
        errors.append("duplicate site_id across instrumentation inventories")
    if len(addresses) != len(set(addresses)):
        errors.append("duplicate site address across instrumentation inventories")
    opcode_errors, opcodes = _validate_opcode_table(payload)
    errors.extend(opcode_errors)
    errors.extend(_validate_descriptors(payload, opcodes))
    return tuple(errors)


def _descriptor_rows(
    proof: Mapping[str, object], opcode_id: int
) -> list[Mapping[str, object]]:
    rows = proof.get("operand_rules")
    if not isinstance(rows, list):
        raise ValueError("proof operand_rules must be list")
    return [
        row
        for row in rows
        if isinstance(row, Mapping) and row.get("opcode_id") == opcode_id
    ]


def expand_operand_descriptors(
    proof: Mapping[str, object], opcode_id: int, arg_count: int
) -> tuple[ExpandedOperandDescriptor, ...]:
    """Expand layout descriptors into exact runtime operand indices."""

    if not _is_nonnegative_int(opcode_id) or not _is_nonnegative_int(arg_count):
        raise ValueError("opcode_id and arg_count must be nonnegative integers")
    result: list[ExpandedOperandDescriptor] = []
    consumed = 0
    rows = _descriptor_rows(proof, opcode_id)
    for position, row in enumerate(rows):
        expansion = row.get("expansion")
        if not isinstance(expansion, Mapping):
            raise ValueError("operand descriptor expansion must be object")
        kind = expansion.get("kind")
        if kind in {"one", "fixed"}:
            count = expansion.get("count")
            if not _is_positive_int(count):
                raise ValueError("operand expansion count must be positive")
        elif kind == "remaining":
            if position != len(rows) - 1:
                raise ValueError("remaining expansion must be final")
            count = arg_count - consumed
            if count < 0:
                raise ValueError("negative operand remainder")
        else:
            raise ValueError("unknown operand expansion kind")
        if consumed + count > arg_count:
            raise ValueError("negative operand remainder")
        state_rules = row.get("state_rules")
        if not isinstance(state_rules, list):
            raise ValueError("operand descriptor state_rules must be list")
        frozen_rules = tuple(MappingProxyType(dict(rule)) for rule in state_rules)
        for _ in range(count):
            result.append(
                ExpandedOperandDescriptor(
                    consumed,
                    int(row["descriptor_index"]),
                    int(row["raw_arg_kind_id"]),
                    str(row["role"]),
                    str(row["register_form"]),
                    row.get("class_id"),
                    row.get("virtual_kind"),
                    frozen_rules,
                )
            )
            consumed += 1
    if consumed != arg_count:
        raise ValueError("leftover operands after descriptor expansion")
    return tuple(result)


def classify_operand(
    descriptor: ExpandedOperandDescriptor,
    capture_stage: str,
    raw_flags: int,
    raw_value: int,
) -> OperandState:
    """Classify exact raw state, requiring exactly one audited rule."""

    if type(capture_stage) is not str or capture_stage not in CAPTURE_STAGES:
        raise ValueError("capture stage is invalid")
    if not _is_u8(raw_flags) or not _is_u16(raw_value):
        raise ValueError("raw register flags/value are outside unsigned bounds")
    matches = [
        rule
        for rule in descriptor.state_rules
        if rule.get("capture_stage") == capture_stage
        and raw_flags & rule["register_flags_mask"] == rule["register_flags_value"]
        and rule["register_value_min"] <= raw_value <= rule["register_value_max"]
    ]
    if len(matches) != 1:
        raise ValueError("operand must match exactly one operand state rule")
    state = str(matches[0]["allocation_state"])
    return OperandState(
        state,
        raw_value if state == "virtual" else None,
        raw_value if state == "physical" else None,
    )


def validate_embedded_proof(
    payload: object,
    struct_map: object,
    compiler_executable_sha256: str,
) -> tuple[str, ...]:
    """Validate proof shape and require its exact independently promoted tuple."""

    errors = list(validate_proof_shape(payload))
    digest: str | None = None
    safe_payload: object = None
    try:
        safe_payload = materialize_json_safe(payload)
    except Exception:  # noqa: BLE001 - proof trust boundary fails closed
        errors.append("instrumentation proof is not RFC 8785 canonicalizable")
    if type(safe_payload) is dict:
        try:
            digest = proof_sha256(safe_payload)
        except (
            rfc8785.CanonicalizationError,
            OverflowError,
            RecursionError,
            TypeError,
            ValueError,
        ):
            errors.append("instrumentation proof is not RFC 8785 canonicalizable")
    registry_errors = validate_instrumentation_proof_registry(struct_map)
    errors.extend(registry_errors)
    compiler_matches = type(safe_payload) is dict and (
        safe_payload.get("compiler_executable_sha256") == compiler_executable_sha256
    )
    if type(safe_payload) is dict and not compiler_matches:
        errors.append("proof compiler digest does not match capture compiler digest")
    trusted = False
    if (
        type(safe_payload) is dict
        and isinstance(struct_map, Mapping)
        and digest is not None
        and not registry_errors
        and compiler_matches
    ):
        key = (compiler_executable_sha256, safe_payload.get("proof_id"), digest)
        registry = struct_map["instrumentation_proofs"]
        trusted = any(
            row["promoted"] is True
            and (
                row["compiler_executable_sha256"],
                row["proof_id"],
                row["proof_sha256"],
            )
            == key
            for row in registry
        )
    if not trusted:
        errors.append("instrumentation proof is not independently promoted for this compiler")
    return tuple(errors)


def trusted_proof_from_trace(
    trace: object, function: str, struct_map: object | None = None
) -> InstrumentationProof:
    """Extract one function's embedded proof after independent trust validation."""

    table = load_gc125n_struct_map() if struct_map is None else struct_map
    if not isinstance(trace, Mapping):
        raise ValueError("trace must be object")
    functions = trace.get("functions")
    if not isinstance(functions, list):
        raise ValueError("trace functions must be list")
    matches: list[Mapping[str, object]] = []
    for index, row in enumerate(functions):
        if not isinstance(row, Mapping):
            raise ValueError(f"trace function {index} must be object")
        if not isinstance(row.get("name"), str):
            raise ValueError(f"trace function {index} name must be string")
        if row["name"] == function:
            matches.append(row)
    if len(matches) != 1:
        raise ValueError(f"expected one function {function!r}, found {len(matches)}")
    object_bindings = matches[0].get("object_bindings")
    if not isinstance(object_bindings, Mapping):
        raise ValueError(f"function {function!r} object_bindings must be object")
    payload = object_bindings.get("lifetime_proof")
    if not isinstance(payload, Mapping):
        raise ValueError(f"function {function!r} lifetime_proof must be object")
    capture_identity = object_bindings.get("capture_identity")
    if not isinstance(capture_identity, Mapping):
        raise ValueError(f"function {function!r} capture_identity must be object")
    compiler_sha256 = capture_identity.get("compiler_executable_sha256")
    if not _is_lower_sha256(compiler_sha256):
        raise ValueError(
            f"function {function!r} capture compiler digest must be 64 lowercase hex"
        )
    errors = validate_embedded_proof(payload, table, compiler_sha256)
    if errors:
        raise ValueError("; ".join(errors))
    return InstrumentationProof(
        payload["proof_id"], compiler_sha256, payload, proof_sha256(payload)
    )


__all__ = [
    "ExpandedOperandDescriptor",
    "InstrumentationProof",
    "OperandState",
    "classify_operand",
    "expand_operand_descriptors",
    "proof_sha256",
    "trusted_proof_from_trace",
    "validate_embedded_proof",
    "validate_proof_shape",
]
