"""Validation and trust lookup for retail backend instrumentation proofs."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

import rfc8785

from .struct_map import load_gc125n_struct_map

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
ALLOCATION_REQUIREMENTS = frozenset(
    {"allocator-rewrite-required", "fixed-physical"}
)

_PROOF_FIELDS = frozenset(
    {
        "schema_version",
        "proof_id",
        "compiler_executable_sha256",
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
_OPERAND_RULE_FIELDS = frozenset(
    {
        "opcode_id",
        "operand_index",
        "raw_arg_kind_id",
        "register_flags_mask",
        "register_flags_value",
        "role",
        "class_id",
        "allocation_requirement",
    }
)
_OPCODE_FIELDS = frozenset({"opcode_id", "mnemonic"})
_HEX_DIGITS = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class InstrumentationProof:
    proof_id: str
    compiler_executable_sha256: str
    payload: Mapping[str, object]
    sha256: str


def proof_sha256(payload: Mapping[str, object]) -> str:
    """Return the RFC 8785 canonical SHA-256 digest of a proof payload."""
    return hashlib.sha256(rfc8785.dumps(dict(payload))).hexdigest()


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_lower_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _HEX_DIGITS for char in value)
    )


def _unexpected_fields(
    value: Mapping[str, object], expected: frozenset[str], label: str
) -> str | None:
    extra = sorted(set(value) - expected)
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
    payload: Mapping[str, object],
    collection: str,
    *,
    lifecycle: bool,
) -> tuple[list[str], list[tuple[str, int]]]:
    errors: list[str] = []
    sites = payload.get(collection)
    label = collection.removesuffix("_sites").replace("_", " ")
    if not isinstance(sites, list):
        return [f"{collection} must be list"], []
    if not sites:
        errors.append(f"{collection} must not be empty")

    expected = _LIFECYCLE_SITE_FIELDS if lifecycle else _PCODE_SITE_FIELDS
    sort_keys: list[tuple[object, ...]] = []
    sortable = True
    valid_ids_and_addresses: list[tuple[str, int]] = []
    seen_rows: set[tuple[object, ...]] = set()
    for index, site in enumerate(sites):
        if not isinstance(site, Mapping):
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
        if not isinstance(site_id, str) or not site_id:
            errors.append(f"{label} site {index} site_id must be non-empty string")
        if not _is_positive_int(address):
            errors.append(f"{label} site {index} address must be positive integer")
        if not isinstance(stage, str) or stage not in COMPILER_STAGES:
            errors.append(f"{label} site {index} has unknown compiler_stage {stage!r}")
        if lifecycle and (
            not isinstance(entity_kind, str) or entity_kind not in ENTITY_KINDS
        ):
            errors.append(f"{label} site {index} has unknown entity_kind {entity_kind!r}")

        if isinstance(site_id, str) and site_id and _is_positive_int(address):
            valid_ids_and_addresses.append((site_id, address))
        if lifecycle:
            row_key = (entity_kind, address, site_id, stage)
            sort_key = (entity_kind, address, site_id)
            sortable = sortable and isinstance(entity_kind, str)
        else:
            row_key = (address, site_id, stage)
            sort_key = (address, site_id)
        try:
            duplicate = row_key in seen_rows
            seen_rows.add(row_key)
        except TypeError:
            duplicate = False
        if duplicate:
            errors.append(f"duplicate {label} site")
        sort_keys.append(sort_key)
        sortable = (
            sortable
            and _is_positive_int(address)
            and isinstance(site_id, str)
            and bool(site_id)
        )

    if sortable and sort_keys != sorted(sort_keys):
        errors.append(f"{collection} must be canonically ordered")
    return errors, valid_ids_and_addresses


def _validate_opcode_table(payload: Mapping[str, object]) -> tuple[list[str], set[int]]:
    errors: list[str] = []
    rows = payload.get("opcode_table")
    if not isinstance(rows, list):
        return ["opcode_table must be list"], set()
    if not rows:
        errors.append("opcode_table must not be empty")
    opcode_ids: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"opcode table row {index} must be object")
            continue
        field_error = _unexpected_fields(row, _OPCODE_FIELDS, "unexpected opcode table")
        if field_error:
            errors.append(field_error)
        opcode_id = row.get("opcode_id")
        mnemonic = row.get("mnemonic")
        if not _is_nonnegative_int(opcode_id):
            errors.append(f"opcode table row {index} opcode_id must be nonnegative integer")
        else:
            opcode_ids.append(opcode_id)
        if not isinstance(mnemonic, str) or not mnemonic:
            errors.append(f"opcode table row {index} mnemonic must be non-empty string")
    if len(opcode_ids) != len(set(opcode_ids)):
        errors.append("duplicate opcode_id")
    if len(opcode_ids) == len(rows) and opcode_ids != sorted(opcode_ids):
        errors.append("opcode_table must be canonically ordered")
    return errors, set(opcode_ids)


def _validate_operand_rules(
    payload: Mapping[str, object], opcode_ids: set[int]
) -> list[str]:
    errors: list[str] = []
    rows = payload.get("operand_rules")
    if not isinstance(rows, list):
        return ["operand_rules must be list"]
    if not rows:
        errors.append("operand_rules must not be empty")
    keys: list[tuple[int, int, int, int, int]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"operand rule {index} must be object")
            continue
        field_error = _unexpected_fields(row, _OPERAND_RULE_FIELDS, "unexpected operand rule")
        if field_error:
            errors.append(field_error)
        integer_fields = (
            "opcode_id",
            "operand_index",
            "raw_arg_kind_id",
            "register_flags_mask",
            "register_flags_value",
            "class_id",
        )
        valid_integers = True
        for field in integer_fields:
            if not _is_nonnegative_int(row.get(field)):
                errors.append(f"operand rule {index} {field} must be nonnegative integer")
                valid_integers = False
        opcode_id = row.get("opcode_id")
        if _is_nonnegative_int(opcode_id) and opcode_id not in opcode_ids:
            errors.append(f"operand rule references unknown opcode_id {opcode_id}")
        role = row.get("role")
        if not isinstance(role, str) or role not in OPERAND_ROLES:
            errors.append(f"operand rule {index} has unknown operand role {role!r}")
        requirement = row.get("allocation_requirement")
        if (
            not isinstance(requirement, str)
            or requirement not in ALLOCATION_REQUIREMENTS
        ):
            errors.append(
                f"operand rule {index} has unknown allocation_requirement {requirement!r}"
            )
        mask = row.get("register_flags_mask")
        value = row.get("register_flags_value")
        if _is_nonnegative_int(mask) and _is_nonnegative_int(value) and value & ~mask:
            errors.append(f"operand rule {index} register_flags_value exceeds mask")
        if valid_integers:
            keys.append(
                (
                    row["opcode_id"],
                    row["operand_index"],
                    row["raw_arg_kind_id"],
                    row["register_flags_mask"],
                    row["register_flags_value"],
                )
            )
    if len(keys) != len(set(keys)):
        errors.append("duplicate operand rule")
    if len(keys) == len(rows) and keys != sorted(keys):
        errors.append("operand_rules must be canonically ordered")
    return errors


def validate_proof_shape(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Validate the closed, canonically ordered lifetime-proof schema."""
    errors: list[str] = []
    field_error = _unexpected_fields(payload, _PROOF_FIELDS, "unexpected proof")
    if field_error:
        errors.append(field_error)
    if payload.get("schema_version") != PROOF_SCHEMA:
        errors.append(f"schema_version must be {PROOF_SCHEMA}")
    if not isinstance(payload.get("proof_id"), str) or not payload.get("proof_id"):
        errors.append("proof_id must be non-empty string")
    if not _is_lower_sha256(payload.get("compiler_executable_sha256")):
        errors.append("compiler_executable_sha256 must be 64 lowercase hex")
    if payload.get("mode") != PROOF_MODE:
        errors.append(f"mode must be {PROOF_MODE}")
    if not _is_positive_int(payload.get("initialization_address")):
        errors.append("initialization_address must be positive integer")
    if payload.get("proof_basis") != PROOF_BASIS:
        errors.append(f"proof_basis must be {PROOF_BASIS}")

    all_sites: list[tuple[str, int]] = []
    for collection in ("allocation_sites", "free_sites"):
        site_errors, sites = _validate_site_inventory(
            payload, collection, lifecycle=True
        )
        errors.extend(site_errors)
        all_sites.extend(sites)
    for collection in (
        "operand_rewrite_sites",
        "operand_mutation_sites",
        "code_emission_sites",
    ):
        site_errors, sites = _validate_site_inventory(
            payload, collection, lifecycle=False
        )
        errors.extend(site_errors)
        all_sites.extend(sites)

    site_ids = [site_id for site_id, _ in all_sites]
    addresses = [address for _, address in all_sites]
    if len(site_ids) != len(set(site_ids)):
        errors.append("duplicate site_id across instrumentation inventories")
    if len(addresses) != len(set(addresses)):
        errors.append("duplicate site address across instrumentation inventories")

    opcode_errors, opcode_ids = _validate_opcode_table(payload)
    errors.extend(opcode_errors)
    errors.extend(_validate_operand_rules(payload, opcode_ids))
    return tuple(errors)


def validate_embedded_proof(
    payload: Mapping[str, object],
    struct_map: Mapping[str, object],
    compiler_executable_sha256: str,
) -> tuple[str, ...]:
    """Validate proof shape and require its exact independently promoted tuple."""
    errors = list(validate_proof_shape(payload))
    digest = proof_sha256(payload)
    registry = struct_map.get("instrumentation_proofs", [])
    trusted: set[tuple[object, object, object]] = set()
    if isinstance(registry, list):
        for row in registry:
            if isinstance(row, Mapping) and row.get("promoted") is True:
                trusted.add(
                    (
                        row.get("compiler_executable_sha256"),
                        row.get("proof_id"),
                        row.get("proof_sha256"),
                    )
                )
    key = (compiler_executable_sha256, payload.get("proof_id"), digest)
    if key not in trusted:
        errors.append("instrumentation proof is not independently promoted for this compiler")
    return tuple(errors)


def trusted_proof_from_trace(
    trace: Mapping[str, object],
    function: str,
    struct_map: Mapping[str, object] | None = None,
) -> InstrumentationProof:
    """Extract one function's embedded proof after independent trust validation."""
    table = load_gc125n_struct_map() if struct_map is None else struct_map
    functions = trace["functions"]
    matches = [row for row in functions if row["name"] == function]
    if len(matches) != 1:
        raise ValueError(f"expected one function {function!r}, found {len(matches)}")
    object_bindings = matches[0]["object_bindings"]
    payload = object_bindings["lifetime_proof"]
    compiler_sha256 = object_bindings["capture_identity"][
        "compiler_executable_sha256"
    ]
    errors = validate_embedded_proof(payload, table, compiler_sha256)
    if errors:
        raise ValueError("; ".join(errors))
    return InstrumentationProof(
        payload["proof_id"],
        compiler_sha256,
        payload,
        proof_sha256(payload),
    )
