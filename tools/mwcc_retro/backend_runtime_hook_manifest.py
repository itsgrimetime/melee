"""Closed validation for digest-bound retail backend runtime hook manifests."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping

import rfc8785

from .struct_map import materialize_json_safe

MANIFEST_SCHEMA = "mwcc-retro-runtime-hooks.v1"

_ROOT_FIELDS = frozenset(
    {"schema_version", "compiler_executable_sha256", "proof_id", "sites"}
)
_SITE_FIELDS = frozenset(
    {
        "site_id",
        "family",
        "proof_address",
        "operation",
        "breakpoints",
        "capture_sources",
        "pairing",
        "hit_policy",
    }
)
_BREAKPOINT_FIELDS = frozenset(
    {"phase", "address", "instruction_bytes", "instruction_sha256"}
)
_CAPTURE_SOURCE_FIELDS = frozenset(
    {
        "name",
        "source_kind",
        "phase",
        "operand_index",
        "register",
        "stack_argument_index",
        "byte_offset",
        "byte_width",
    }
)
_FAMILY_OPERATIONS = {
    "allocation_sites": frozenset({"allocation", "cache-acquire"}),
    "free_sites": frozenset(
        {"recycle", "rewind", "release", "cache-release"}
    ),
    "operand_rewrite_sites": frozenset({"operand-rewrite"}),
    "operand_mutation_sites": frozenset(
        {"create", "delete", "reorder", "clone", "replace", "spill", "coalesce"}
    ),
    "code_emission_sites": frozenset({"encode", "final-buffer-emission"}),
}
_FAMILY_RANK = {family: rank for rank, family in enumerate(_FAMILY_OPERATIONS)}
_PAIRING_PHASES = {
    "same-thread-instruction": ("before", "after"),
    "same-thread-call-return": ("before", "return"),
    "same-thread-function-entry-exit": ("before", "after"),
}
_OPERATION_CONTRACTS = {
    ("allocation_sites", "allocation"): (
        "same-thread-call-return",
        (
            ("allocation_length", "stack-argument", "before", None, None, 0, 0, 4),
            ("allocated_pointer", "return-register", "return", None, "eax", None, 0, 4),
        ),
    ),
    ("allocation_sites", "cache-acquire"): (
        "same-thread-instruction",
        (
            (
                "entity_pointer",
                "effective-address",
                "before",
                0,
                None,
                None,
                -0x2A,
                4,
            ),
        ),
    ),
    **{
        ("free_sites", operation): (
            "same-thread-call-return",
            (("entity_pointer", "stack-argument", "before", None, None, 0, 0, 4),),
        )
        for operation in ("recycle", "rewind", "release")
    },
    ("free_sites", "cache-release"): (
        "same-thread-instruction",
        (
            (
                "entity_pointer",
                "effective-address",
                "before",
                0,
                None,
                None,
                -0x2A,
                4,
            ),
        ),
    ),
    ("operand_rewrite_sites", "operand-rewrite"): (
        "same-thread-instruction",
        (("operand_address", "effective-address", "before", 0, None, None, -2, 12),),
    ),
    ("operand_mutation_sites", "create"): (
        "same-thread-function-entry-exit",
        (
            ("output_pointer", "x86-register", "after", None, "eax", None, 0, 4),
            ("output_length", "x86-register", "after", None, "ecx", None, 0, 4),
        ),
    ),
    ("operand_mutation_sites", "delete"): (
        "same-thread-function-entry-exit",
        (
            ("input_pointer", "x86-register", "before", None, "eax", None, 0, 4),
            ("input_length", "x86-register", "before", None, "ecx", None, 0, 4),
        ),
    ),
    **{
        ("operand_mutation_sites", operation): (
            "same-thread-function-entry-exit",
            (
                ("input_pointer", "x86-register", "before", None, "eax", None, 0, 4),
                ("input_length", "x86-register", "before", None, "ecx", None, 0, 4),
                ("output_pointer", "x86-register", "after", None, "eax", None, 0, 4),
                ("output_length", "x86-register", "after", None, "ecx", None, 0, 4),
            ),
        )
        for operation in ("reorder", "clone", "replace", "spill", "coalesce")
    },
    ("code_emission_sites", "encode"): (
        "same-thread-call-return",
        (
            ("pcode_pointer", "stack-argument", "before", None, None, 0, 0, 4),
            ("encoded_word", "return-register", "return", None, "eax", None, 0, 4),
        ),
    ),
    ("code_emission_sites", "final-buffer-emission"): (
        "same-thread-instruction",
        (
            ("buffer_pointer", "x86-register", "before", None, "eax", None, 0, 4),
            ("buffer_length", "x86-register", "before", None, "ecx", None, 0, 4),
        ),
    ),
}
_SOURCE_KINDS = frozenset(
    {
        "x86-register",
        "stack-argument",
        "return-register",
        "effective-address",
        "memory-at-source",
    }
)
_REGISTERS = frozenset(
    {
        "eax",
        "ebx",
        "ecx",
        "edx",
        "esi",
        "edi",
        "ebp",
        "esp",
    }
)
_HEX = frozenset("0123456789abcdef")


def runtime_hook_manifest_sha256(payload: Mapping[str, object]) -> str:
    """Return the RFC 8785 canonical SHA-256 of a runtime-hook manifest."""

    return hashlib.sha256(rfc8785.dumps(dict(payload))).hexdigest()


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


def _nonnegative(value: object) -> bool:
    return type(value) is int and value >= 0


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(char in _HEX for char in value)
    )


def _closed(
    row: object, fields: frozenset[str], label: str, errors: list[str]
) -> dict[str, object] | None:
    if type(row) is not dict:
        errors.append(f"{label} must be object")
        return None
    actual = set(row)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        details = []
        if missing:
            details.append(f"missing {missing!r}")
        if extra:
            details.append(f"unexpected {extra!r}")
        errors.append(f"{label} fields: {', '.join(details)}")
    return row


def _validate_breakpoints(
    value: object, pairing: object, label: str, errors: list[str]
) -> set[str]:
    if type(value) is not list:
        errors.append(f"{label} breakpoints must be list")
        return set()
    phases: list[str] = []
    keys: list[tuple[int, int]] = []
    phase_rank = {"before": 0, "after": 1, "return": 2}
    for index, raw in enumerate(value):
        row = _closed(raw, _BREAKPOINT_FIELDS, f"{label} breakpoint {index}", errors)
        if row is None:
            continue
        phase = row.get("phase")
        if type(phase) is not str or phase not in phase_rank:
            errors.append(f"{label} breakpoint {index} phase is invalid")
        else:
            phases.append(phase)
        address = row.get("address")
        if not _positive(address):
            errors.append(f"{label} breakpoint {index} address must be positive integer")
        raw_hex = row.get("instruction_bytes")
        decoded = None
        if (
            type(raw_hex) is not str
            or not raw_hex
            or len(raw_hex) % 2
            or any(char not in _HEX for char in raw_hex)
        ):
            errors.append(
                f"{label} breakpoint {index} instruction_bytes must be lowercase even hex"
            )
        else:
            decoded = bytes.fromhex(raw_hex)
        digest = row.get("instruction_sha256")
        if not _sha(digest):
            errors.append(f"{label} breakpoint {index} instruction digest is invalid")
        elif decoded is not None and hashlib.sha256(decoded).hexdigest() != digest:
            errors.append(
                f"{label} breakpoint {index} instruction digest does not match bytes"
            )
        if type(phase) is str and phase in phase_rank and _positive(address):
            keys.append((phase_rank[phase], address))
    expected = _PAIRING_PHASES.get(pairing) if type(pairing) is str else None
    if expected is None:
        errors.append(f"{label} pairing is invalid")
    elif tuple(phases) != expected:
        errors.append(f"{label} breakpoint phases must be exactly {expected!r}")
    if len(phases) != len(set(phases)):
        errors.append(f"{label} breakpoint phases overlap")
    if keys != sorted(keys):
        errors.append(f"{label} breakpoints must be canonically ordered")
    return set(phases)


def _validate_capture_sources(
    value: object,
    phases: set[str],
    family: object,
    operation: object,
    pairing: object,
    label: str,
    errors: list[str],
) -> None:
    contract = (
        _OPERATION_CONTRACTS.get((family, operation))
        if type(family) is str and type(operation) is str
        else None
    )
    if contract is not None and pairing != contract[0]:
        errors.append(f"{label} pairing does not match operation contract")
    if type(value) is not list:
        errors.append(f"{label} capture_sources must be nonempty list")
        return
    if not value:
        errors.append(f"{label} capture_sources must be nonempty list")
    signatures: list[tuple[object, ...]] = []
    for index, raw in enumerate(value):
        row = _closed(
            raw,
            _CAPTURE_SOURCE_FIELDS,
            f"{label} capture source {index}",
            errors,
        )
        if row is None:
            continue
        name = row.get("name")
        if type(name) is not str or not name:
            errors.append(f"{label} capture source {index} name must be nonempty string")
        source_kind = row.get("source_kind")
        if type(source_kind) is not str or source_kind not in _SOURCE_KINDS:
            errors.append(f"{label} capture source {index} source_kind is invalid")
        phase = row.get("phase")
        if type(phase) is not str or phase not in phases:
            errors.append(f"{label} capture source {index} phase has no breakpoint")
        operand_index = row.get("operand_index")
        register = row.get("register")
        stack_index = row.get("stack_argument_index")
        if register is not None and (
            type(register) is not str or register not in _REGISTERS
        ):
            errors.append(f"{label} capture source {index} register is invalid")
        if source_kind == "effective-address":
            valid_coupling = (
                _nonnegative(operand_index)
                and register is None
                and stack_index is None
            )
        elif source_kind == "stack-argument":
            valid_coupling = (
                operand_index is None
                and register is None
                and _nonnegative(stack_index)
            )
        elif source_kind in {"x86-register", "return-register"}:
            valid_coupling = (
                operand_index is None
                and type(register) is str
                and register in _REGISTERS
                and stack_index is None
            )
        elif source_kind == "memory-at-source":
            valid_coupling = (
                operand_index is None
                and type(register) is str
                and register in _REGISTERS
                and stack_index is None
            )
        else:
            valid_coupling = False
        if not valid_coupling:
            errors.append(f"{label} capture source {index} source coupling is invalid")
        if type(row.get("byte_offset")) is not int:
            errors.append(f"{label} capture source {index} byte_offset must be integer")
        if not _positive(row.get("byte_width")):
            errors.append(f"{label} capture source {index} byte_width must be positive integer")
        signatures.append(
            (
                name,
                source_kind,
                phase,
                operand_index,
                register,
                stack_index,
                row.get("byte_offset"),
                row.get("byte_width"),
            )
        )
    if contract is None:
        return
    _expected_pairing, expected_signatures = contract
    if tuple(signatures) != expected_signatures:
        errors.append(f"{label} capture_sources do not match operation contract")


def _proof_sites(
    proof: dict[str, object], errors: list[str]
) -> list[tuple[str, int, str]]:
    result: list[tuple[str, int, str]] = []
    seen_ids: set[str] = set()
    for family in _FAMILY_OPERATIONS:
        rows = proof.get(family)
        if type(rows) is not list:
            errors.append(f"proof {family} must be list")
            continue
        for index, row in enumerate(rows):
            if type(row) is not dict:
                errors.append(f"proof {family} site {index} must be object")
                continue
            site_id = row.get("site_id")
            address = row.get("address")
            if type(site_id) is not str or not site_id:
                errors.append(
                    f"proof {family} site {index} site_id must be nonempty string"
                )
                continue
            if not _positive(address):
                errors.append(
                    f"proof {family} site {index} address must be positive integer"
                )
                continue
            if site_id in seen_ids:
                errors.append("runtime hook proof has duplicate site_id")
            seen_ids.add(site_id)
            result.append((family, address, site_id))
    return sorted(
        result,
        key=lambda item: (_FAMILY_RANK[item[0]], item[1], item[2]),
    )


def validate_runtime_hook_manifest(
    payload: object, proof: object
) -> tuple[str, ...]:
    """Validate a closed manifest and its exact proof/digest binding."""

    errors: list[str] = []
    try:
        payload = materialize_json_safe(payload)
    except Exception as exc:  # noqa: BLE001 - trust boundary fails closed
        return (f"runtime hook manifest could not be materialized: {exc}",)
    try:
        proof = materialize_json_safe(proof)
    except Exception as exc:  # noqa: BLE001 - trust boundary fails closed
        return (f"runtime hook proof could not be materialized: {exc}",)
    manifest = _closed(payload, _ROOT_FIELDS, "runtime hook manifest", errors)
    if manifest is None:
        return tuple(errors)
    if type(proof) is not dict:
        errors.append("runtime hook proof must be object")
        return tuple(errors)
    from .backend_instrumentation_proof import validate_proof_shape

    errors.extend(
        f"runtime hook proof shape: {error}" for error in validate_proof_shape(proof)
    )
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        errors.append(f"runtime hook manifest schema_version must be {MANIFEST_SCHEMA}")
    if manifest.get("compiler_executable_sha256") != proof.get(
        "compiler_executable_sha256"
    ):
        errors.append("runtime hook manifest compiler digest differs from proof")
    if manifest.get("proof_id") != proof.get("proof_id"):
        errors.append("runtime hook manifest proof ID differs from proof")

    expected = _proof_sites(proof, errors)
    sites = manifest.get("sites")
    if type(sites) is not list:
        errors.append("runtime hook manifest sites must be list")
        sites = []
    actual: list[tuple[str, int, str]] = []
    actual_site_ids: set[str] = set()
    sort_keys: list[tuple[int, int, str]] = []
    for index, raw in enumerate(sites):
        label = f"runtime hook site {index}"
        row = _closed(raw, _SITE_FIELDS, label, errors)
        if row is None:
            continue
        site_id = row.get("site_id")
        family = row.get("family")
        address = row.get("proof_address")
        operation = row.get("operation")
        if type(site_id) is not str or not site_id:
            errors.append(f"{label} site_id must be nonempty string")
        if type(family) is not str or family not in _FAMILY_OPERATIONS:
            errors.append(f"{label} family is invalid")
        elif (
            type(operation) is not str
            or operation not in _FAMILY_OPERATIONS[family]
        ):
            errors.append(f"{label} operation is invalid for family")
        if not _positive(address):
            errors.append(f"{label} proof_address must be positive integer")
        if type(row.get("hit_policy")) is not str or row.get(
            "hit_policy"
        ) not in {"per-run", "probe-union"}:
            errors.append(f"{label} hit_policy is invalid")
        pairing = row.get("pairing")
        phases = _validate_breakpoints(row.get("breakpoints"), pairing, label, errors)
        _validate_capture_sources(
            row.get("capture_sources"),
            phases,
            family,
            operation,
            pairing,
            label,
            errors,
        )
        if type(site_id) is str and site_id and type(family) is str and _positive(address):
            if site_id in actual_site_ids:
                errors.append("runtime hook manifest has duplicate site_id")
            actual_site_ids.add(site_id)
            actual.append((family, address, site_id))
            if family in _FAMILY_RANK:
                sort_keys.append((_FAMILY_RANK[family], address, site_id))
    if sort_keys != sorted(sort_keys):
        errors.append("runtime hook manifest sites must be canonically ordered")
    if actual != expected:
        errors.append("runtime hook manifest site inventory differs from proof")
    try:
        digest = runtime_hook_manifest_sha256(manifest)
    except (
        rfc8785.CanonicalizationError,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        errors.append("runtime hook manifest is not RFC 8785 canonicalizable")
    else:
        if proof.get("runtime_hook_manifest_sha256") != digest:
            errors.append("runtime hook manifest digest differs from proof")
    return tuple(errors)


__all__ = ["runtime_hook_manifest_sha256", "validate_runtime_hook_manifest"]
