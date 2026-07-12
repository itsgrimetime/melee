"""Fail-closed validation of same-run retail PCode operand lineage."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
from elftools.elf.sections import SymbolTableSection

from .backend_instrumentation_proof import (
    InstrumentationProof,
    proof_sha256,
    validate_proof_shape,
)

CAPABILITY = "pcode-to-code-range"
_SAFE_INT = (1 << 53) - 1
_SHA = frozenset("0123456789abcdef")
_TOP_REQUIRED = frozenset(
    {
        "lifecycle_events",
        "coverage",
        "pcode_instructions",
        "pcode_occurrences",
        "pcode_operand_lineage_events",
    }
)
_TOP_ALLOWED = _TOP_REQUIRED | frozenset(
    {
        "schema_version",
        "capture_identity",
        "capture_run_id",
        "lifetime_proof",
        "objects",
        "virtual_bindings",
        "frame_bindings",
        "source_bindings",
        "source_capture",
    }
)


class _Malformed(ValueError):
    pass


@dataclass(frozen=True)
class _FunctionObjectView:
    section_name: str
    section_index: int
    symbol_start: int
    symbol_size: int
    section_data: bytes
    relocations: tuple[tuple[int, int, int, str, int], ...]


@dataclass(frozen=True)
class _EmissionObservation:
    pcode_id: str
    event_sequence: int
    state: Mapping[str, object]
    parents: Mapping[str, tuple[str, ...]]
    origins: Mapping[str, tuple[Mapping[str, object], ...]]


@dataclass
class _Context:
    errors: list[str]
    proof: InstrumentationProof
    allocation_sites: dict[str, Mapping[str, object]]
    free_sites: dict[str, Mapping[str, object]]
    rewrite_sites: dict[str, Mapping[str, object]]
    mutation_sites: dict[str, Mapping[str, object]]
    emission_sites: dict[str, Mapping[str, object]]
    opcodes: dict[int, str]
    rules: list[Mapping[str, object]]
    lifecycle_states: dict[int, dict[tuple[str, int], int]]
    pcode_rows: dict[str, Mapping[str, object]]
    current: dict[str, Mapping[str, object]]
    parents: dict[str, tuple[str, ...]]
    origins: dict[str, list[Mapping[str, object]]]
    allocatable_lineages: set[str]


@dataclass(frozen=True)
class AnchorVirtualBinding:
    code_offset: int
    machine_operand_key: str
    pcode_id: str
    operand_lineage_id: str
    class_id: int
    virtual: int
    physical_register: int
    confidence: str


@dataclass(frozen=True)
class PCodeLineageValidation:
    normalized: Mapping[str, object]
    anchor_bindings: Mapping[tuple[int, str], AnchorVirtualBinding]
    capabilities: frozenset[str]
    errors: tuple[str, ...]


def _int(value: object) -> bool:
    return type(value) is int and -_SAFE_INT <= value <= _SAFE_INT


def _nonnegative(value: object) -> bool:
    return _int(value) and value >= 0


def _positive(value: object) -> bool:
    return _int(value) and value > 0


def _physical(value: object) -> bool:
    return _int(value) and 0 <= value <= 31


_CLASS_SHAPES = {0: ("gpr", "r"), 1: ("fpr", "f")}


def _validate_class_shape(
    *,
    class_id: object,
    virtual_kind: object,
    label: str,
    errors: list[str],
    class_name: object | None = None,
) -> None:
    shape = _CLASS_SHAPES.get(class_id) if _nonnegative(class_id) else None
    if shape is None:
        errors.append(f"{label} class_id must be 0 or 1")
        return
    expected_name, expected_kind = shape
    if class_name is not None and class_name != expected_name:
        errors.append(f"{label} class/class_name coupling is invalid")
    if virtual_kind is not None and virtual_kind != expected_kind:
        errors.append(f"{label} class/virtual kind coupling is invalid")


def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in _SHA for char in value)


def _copy_json(value: object, active: set[int] | None = None) -> object:
    """Copy the exact RFC8785-safe JSON domain, rejecting aliases only when recursive."""

    stack = set() if active is None else active
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in stack:
            raise _Malformed("recursive mapping")
        stack.add(identity)
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise _Malformed("JSON object key is not exact string")
            try:
                key.encode("utf-8")
            except UnicodeError as exc:
                raise _Malformed("JSON object key contains surrogate") from exc
            result[key] = _copy_json(item, stack)
        stack.remove(identity)
        return result
    if type(value) is list:
        identity = id(value)
        if identity in stack:
            raise _Malformed("recursive list")
        stack.add(identity)
        result = [_copy_json(item, stack) for item in value]
        stack.remove(identity)
        return result
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if not -_SAFE_INT <= value <= _SAFE_INT:
            raise _Malformed("integer outside RFC8785 safe domain")
        return value
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise _Malformed("string contains surrogate") from exc
        return value
    if type(value) is float:
        raise _Malformed("float is not accepted by exact integer schema")
    raise _Malformed(f"non-JSON value {type(value).__name__}")


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _closed(
    value: object,
    fields: frozenset[str],
    label: str,
    errors: list[str],
    *,
    required: frozenset[str] | None = None,
) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        errors.append(f"{label} must be object")
        return None
    actual = set(value)
    needed = fields if required is None else required
    extra = sorted(actual - fields)
    missing = sorted(needed - actual)
    if extra or missing:
        detail = []
        if extra:
            detail.append(f"unexpected {extra!r}")
        if missing:
            detail.append(f"missing {missing!r}")
        errors.append(f"{label} fields: {', '.join(detail)}")
    return value


def _rows(value: object, label: str, errors: list[str]) -> list[object]:
    if not isinstance(value, list):
        errors.append(f"{label} must be list")
        return []
    return value


def _proof_inventory(
    proof: InstrumentationProof,
    name: str,
    errors: list[str],
) -> dict[str, Mapping[str, object]]:
    rows = proof.payload.get(name) if isinstance(proof.payload, Mapping) else None
    if not isinstance(rows, list):
        errors.append(f"trusted proof {name} must be list")
        return {}
    result: dict[str, Mapping[str, object]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not isinstance(row.get("site_id"), str):
            errors.append(f"trusted proof {name} row {index} is malformed")
            continue
        site_id = row["site_id"]
        if site_id in result:
            errors.append(f"trusted proof {name} contains duplicate site id")
        result[site_id] = row
    return result


def _context(proof: object, errors: list[str]) -> _Context | None:
    if not isinstance(proof, InstrumentationProof) or not isinstance(proof.payload, Mapping):
        errors.append("trusted proof must be InstrumentationProof")
        return None
    shape_errors = validate_proof_shape(proof.payload)
    errors.extend(f"trusted proof: {error}" for error in shape_errors)
    try:
        digest = proof_sha256(proof.payload)
    except (OverflowError, RecursionError, TypeError, ValueError):
        errors.append("trusted proof payload is not canonicalizable")
    else:
        if digest != proof.sha256:
            errors.append("trusted proof digest does not match payload")
    if proof.proof_id != proof.payload.get("proof_id"):
        errors.append("trusted proof id does not match payload")
    if proof.compiler_executable_sha256 != proof.payload.get("compiler_executable_sha256"):
        errors.append("trusted proof compiler digest does not match payload")
    opcodes: dict[int, str] = {}
    opcode_rows = proof.payload.get("opcode_table")
    if isinstance(opcode_rows, list):
        for row in opcode_rows:
            if isinstance(row, Mapping) and _nonnegative(row.get("opcode_id")) and isinstance(row.get("mnemonic"), str):
                opcode_id = row["opcode_id"]
                if opcode_id in opcodes:
                    errors.append("trusted proof has duplicate opcode id")
                opcodes[opcode_id] = row["mnemonic"]
    rules = proof.payload.get("operand_rules")
    return _Context(
        errors,
        proof,
        _proof_inventory(proof, "allocation_sites", errors),
        _proof_inventory(proof, "free_sites", errors),
        _proof_inventory(proof, "operand_rewrite_sites", errors),
        _proof_inventory(proof, "operand_mutation_sites", errors),
        _proof_inventory(proof, "code_emission_sites", errors),
        opcodes,
        [row for row in rules if isinstance(row, Mapping)] if isinstance(rules, list) else [],
        {-1: {}},
        {},
        {},
        {},
        {},
        set(),
    )


_LIFECYCLE_FIELDS = frozenset(
    {
        "sequence",
        "event",
        "entity_kind",
        "runtime_address",
        "allocation_generation",
        "instrumented_site_id",
        "compiler_stage",
    }
)


def _replay_lifecycle(payload: Mapping[str, object], ctx: _Context) -> None:
    events = _rows(payload.get("lifecycle_events"), "lifecycle_events", ctx.errors)
    active: dict[tuple[str, int], int] = {}
    generations: dict[tuple[str, int], int] = {}
    for index, raw in enumerate(events):
        event = _closed(raw, _LIFECYCLE_FIELDS, f"lifecycle event {index}", ctx.errors)
        if event is None:
            continue
        sequence = event.get("sequence")
        if not _nonnegative(sequence) or sequence != index:
            ctx.errors.append(f"lifecycle sequence gap at index {index}")
        action = event.get("event")
        kind = event.get("entity_kind")
        address = event.get("runtime_address")
        generation = event.get("allocation_generation")
        site_id = event.get("instrumented_site_id")
        stage = event.get("compiler_stage")
        if action not in ("allocate", "free"):
            ctx.errors.append(f"lifecycle event {index} has unknown event")
        if kind not in ("objobject", "pcode"):
            ctx.errors.append(f"lifecycle event {index} has unknown entity kind")
        if not _positive(address) or not _positive(generation):
            ctx.errors.append(f"lifecycle event {index} identity must use positive integers")
            continue
        sites = ctx.allocation_sites if action == "allocate" else ctx.free_sites
        site = sites.get(site_id) if isinstance(site_id, str) else None
        if site is None:
            ctx.errors.append(f"lifecycle event {index} references unknown {action} site")
        elif site.get("entity_kind") != kind or site.get("compiler_stage") != stage:
            ctx.errors.append(f"lifecycle event {index} does not match trusted site")
        key = (kind, address)
        if action == "allocate":
            expected = generations.get(key, 0) + 1
            if generation != expected:
                ctx.errors.append(f"lifecycle event {index} generation must increment to {expected}")
            if key in active:
                ctx.errors.append(f"lifecycle event {index} allocation while generation active")
            active[key] = generation
            generations[key] = generation
        elif action == "free":
            if active.get(key) != generation:
                ctx.errors.append(f"lifecycle event {index} free lacks active generation")
            else:
                del active[key]
        if sequence == index:
            ctx.lifecycle_states[index] = dict(active)


def _active(ctx: _Context, address: object, generation: object, sequence: object, label: str) -> bool:
    if not _positive(address) or not _positive(generation) or not _int(sequence):
        ctx.errors.append(f"{label} lifecycle identity fields must be exact integers")
        return False
    state = ctx.lifecycle_states.get(sequence)
    if state is None or state.get(("pcode", address)) != generation:
        ctx.errors.append(f"{label} does not resolve to active PCode generation")
        return False
    return True


def _validated_elf(stream: object) -> ELFFile:
    ident = stream.read(16)
    if len(ident) < 16 or ident[:4] != b"\x7fELF":
        raise _Malformed("candidate object must be ELF")
    if ident[4] != 1:
        raise _Malformed("candidate object must be ELF32")
    if ident[5] != 2:
        raise _Malformed("candidate object must be big-endian")
    stream.seek(0)
    elf = ELFFile(stream)
    if elf.elfclass != 32:
        raise _Malformed("candidate object must be ELF32")
    if elf.little_endian:
        raise _Malformed("candidate object must be big-endian")
    if elf.header["e_machine"] != "EM_PPC":
        raise _Malformed("candidate object machine must be EM_PPC")
    if elf.header["e_type"] != "ET_REL":
        raise _Malformed("candidate object type must be ET_REL")
    return elf


def _unique_function_symbol(elf: ELFFile, function: str) -> object:
    matches = [
        symbol
        for section in elf.iter_sections()
        if isinstance(section, SymbolTableSection)
        for symbol in section.iter_symbols()
        if symbol.name == function and symbol["st_info"]["type"] == "STT_FUNC" and symbol["st_shndx"] != "SHN_UNDEF"
    ]
    if len(matches) != 1:
        raise _Malformed(f"expected one defined function symbol {function!r}, found {len(matches)}")
    return matches[0]


def _object_relocations(elf: ELFFile, section_index: int) -> tuple[tuple[int, int, int, str, int], ...]:
    rows: list[tuple[int, int, int, str, int]] = []
    for relocation_section in elf.iter_sections():
        if not isinstance(relocation_section, RelocationSection) or int(relocation_section["sh_info"]) != section_index:
            continue
        symbol_table = elf.get_section(relocation_section["sh_link"])
        if not isinstance(symbol_table, SymbolTableSection):
            raise _Malformed("relocation symbol table is invalid")
        for relocation in relocation_section.iter_relocations():
            symbol_index = int(relocation["r_info_sym"])
            if symbol_index >= symbol_table.num_symbols():
                raise _Malformed("relocation target symbol index is out of range")
            target = symbol_table.get_symbol(symbol_index)
            addend = int(relocation["r_addend"]) if relocation_section.is_RELA() else 0
            rows.append(
                (
                    int(relocation["r_offset"]),
                    int(relocation["r_info_type"]),
                    symbol_index,
                    target.name,
                    addend,
                )
            )
    return tuple(sorted(rows, key=lambda row: (row[0], row[1], row[2], row[4])))


def _load_object(path: object, function: object) -> _FunctionObjectView:
    if not isinstance(path, (str, Path)):
        raise _Malformed("candidate object path must be path-like")
    if not isinstance(function, str) or not function:
        raise _Malformed("function must be non-empty string")
    function.encode("utf-8")
    with Path(path).open("rb") as stream:
        elf = _validated_elf(stream)
        symbol = _unique_function_symbol(elf, function)
        size = int(symbol["st_size"])
        if size <= 0:
            raise _Malformed("function symbol must have positive size")
        section_index = symbol["st_shndx"]
        if not isinstance(section_index, int):
            raise _Malformed("function symbol section is not concrete")
        section = elf.get_section(section_index)
        if section["sh_type"] != "SHT_PROGBITS":
            raise _Malformed("function section must be SHT_PROGBITS")
        if int(section["sh_flags"]) & 0x4 == 0:
            raise _Malformed("function section must be executable")
        start = int(symbol["st_value"])
        data = bytes(section.data())
        if start < 0 or start + size > len(data):
            raise _Malformed("function symbol extent lies outside section")
        return _FunctionObjectView(
            section.name,
            section_index,
            start,
            size,
            data,
            _object_relocations(elf, section_index),
        )


_INSTRUCTION_FIELDS = frozenset(
    {
        "pcode_id",
        "runtime_address",
        "allocation_generation",
        "block_order",
        "instruction_order",
        "function_symbol",
        "section_name",
        "coordinate_space",
        "stage_snapshots",
        "emission_event_sequence",
        "emission_site_id",
        "emission_runtime_address",
        "emission_allocation_generation",
        "emission_lifecycle_sequence_at_capture",
        "code_ranges",
        "cross_stage_identity_confidence",
    }
)
_SNAPSHOT_FIELDS = frozenset(
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
_PARSED_FIELDS = frozenset(
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
_OPERAND_FIELDS = frozenset(
    {
        "operand_index",
        "operand_lineage_id",
        "raw_arg_kind_id",
        "raw_payload_sha256",
        "parent_lineage_ids",
    }
)
_OPERAND_REQUIRED = _OPERAND_FIELDS - {"parent_lineage_ids"}
_STATE_FIELDS = frozenset(
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
_REWRITE_FIELDS = frozenset(
    {
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
        "pcode_event_sequence",
        "instrumented_site_id",
        "runtime_address",
        "allocation_generation",
        "lifecycle_sequence_at_capture",
        "source_stage",
        "confidence",
    }
)
_MUTATION_FIELDS = frozenset(
    {
        "pcode_event_sequence",
        "instrumented_site_id",
        "mutation_kind",
        "inputs",
        "outputs",
    }
)


def _rule(
    ctx: _Context,
    opcode_id: object,
    operand_index: object,
    kind: object,
    flags: object,
    label: str,
) -> Mapping[str, object] | None:
    if not all(_nonnegative(value) for value in (opcode_id, operand_index, kind, flags)):
        ctx.errors.append(f"{label} rule key fields must be nonnegative integers")
        return None
    matches = [
        row
        for row in ctx.rules
        if row.get("opcode_id") == opcode_id
        and row.get("operand_index") == operand_index
        and row.get("raw_arg_kind_id") == kind
        and _nonnegative(row.get("register_flags_mask"))
        and _nonnegative(row.get("register_flags_value"))
        and flags & row["register_flags_mask"] == row["register_flags_value"]
    ]
    if len(matches) != 1:
        ctx.errors.append(f"{label} must match exactly one trusted operand rule")
        return None
    return matches[0]


def _validate_operands(
    value: object,
    arg_count: object,
    label: str,
    ctx: _Context,
    *,
    allow_parents: bool = False,
) -> list[Mapping[str, object]]:
    rows = _rows(value, f"{label} operands", ctx.errors)
    result: list[Mapping[str, object]] = []
    indexes: list[int] = []
    for index, raw in enumerate(rows):
        row = _closed(
            raw,
            _OPERAND_FIELDS,
            f"{label} operand {index}",
            ctx.errors,
            required=_OPERAND_REQUIRED,
        )
        if row is None:
            continue
        operand_index = row.get("operand_index")
        if not _nonnegative(operand_index):
            ctx.errors.append(f"{label} operand {index} index must be nonnegative integer")
        else:
            indexes.append(operand_index)
        if not isinstance(row.get("operand_lineage_id"), str) or not row.get("operand_lineage_id"):
            ctx.errors.append(f"{label} operand {index} lineage id must be non-empty string")
        if not _nonnegative(row.get("raw_arg_kind_id")):
            ctx.errors.append(f"{label} operand {index} raw kind must be nonnegative integer")
        if not _sha(row.get("raw_payload_sha256")):
            ctx.errors.append(f"{label} operand {index} raw payload digest must be lowercase SHA-256")
        if "parent_lineage_ids" in row:
            if not allow_parents:
                ctx.errors.append(f"{label} operand {index} must omit parent_lineage_ids")
            parents = _rows(
                row.get("parent_lineage_ids"),
                f"{label} operand {index} parents",
                ctx.errors,
            )
            if any(not isinstance(parent, str) or not parent for parent in parents):
                ctx.errors.append(f"{label} operand {index} parents must be non-empty strings")
            elif parents != sorted(set(parents)):
                ctx.errors.append(f"{label} operand {index} parents must be sorted and unique")
        result.append(row)
    if _nonnegative(arg_count) and len(rows) != arg_count:
        ctx.errors.append(f"{label} operand count does not match arg_count")
    if indexes != list(range(len(rows))):
        ctx.errors.append(f"{label} operand indexes must be contiguous")
    return result


def _validate_parsed(
    value: object,
    opcode_id: object,
    inventory: list[Mapping[str, object]],
    label: str,
    ctx: _Context,
) -> list[Mapping[str, object]]:
    rows = _rows(value, f"{label} parsed_register_operands", ctx.errors)
    result: list[Mapping[str, object]] = []
    keys: list[tuple[object, ...]] = []
    for index, raw in enumerate(rows):
        row = _closed(raw, _PARSED_FIELDS, f"{label} parsed operand {index}", ctx.errors)
        if row is None:
            continue
        operand_index = row.get("operand_index")
        if not _nonnegative(operand_index) or operand_index >= len(inventory):
            ctx.errors.append(f"{label} parsed operand {index} references invalid operand index")
            continue
        item = inventory[operand_index]
        if item.get("operand_lineage_id") != row.get("operand_lineage_id") or item.get("raw_arg_kind_id") != row.get(
            "raw_arg_kind_id"
        ):
            ctx.errors.append(f"{label} parsed operand {index} disagrees with lineage inventory")
        rule = _rule(
            ctx,
            opcode_id,
            operand_index,
            row.get("raw_arg_kind_id"),
            row.get("raw_register_flags"),
            f"{label} parsed operand {index}",
        )
        if rule is not None:
            for field in ("role", "class_id", "allocation_requirement"):
                if row.get(field) != rule.get(field):
                    ctx.errors.append(
                        f"{label} parsed operand {index} allocation requirement/role/class disagrees with trusted rule"
                    )
        requirement = row.get("allocation_requirement")
        _validate_class_shape(
            class_id=row.get("class_id"),
            virtual_kind=row.get("virtual_kind"),
            label=f"{label} parsed operand {index}",
            errors=ctx.errors,
        )
        if requirement == "allocator-rewrite-required":
            if (
                row.get("virtual_kind") not in ("r", "f")
                or not _nonnegative(row.get("virtual"))
                or row.get("physical_register") is not None
            ):
                ctx.errors.append(f"{label} allocatable operand has invalid virtual/physical shape")
        elif requirement == "fixed-physical":
            if (
                row.get("virtual_kind") is not None
                or row.get("virtual") is not None
                or not _physical(row.get("physical_register"))
            ):
                ctx.errors.append(f"{label} fixed operand has invalid virtual/physical shape")
            if not _physical(row.get("physical_register")):
                ctx.errors.append(f"{label} parsed operand {index} physical register must be in 0..31")
        else:
            ctx.errors.append(f"{label} has unknown allocation requirement")
        key = (
            operand_index,
            row.get("role"),
            row.get("class_id"),
            row.get("raw_arg_kind_id"),
            row.get("raw_register_flags"),
        )
        keys.append(key)
        result.append(row)
    try:
        if keys != sorted(keys):
            ctx.errors.append(f"{label} parsed register operands must be canonically ordered")
    except TypeError:
        ctx.errors.append(f"{label} parsed register operands are not sortable")
    if len(keys) != len(set(keys)):
        ctx.errors.append(f"{label} has duplicate parsed register operand")
    parsed_counts = Counter(row.get("operand_index") for row in result)
    for operand_index, item in enumerate(inventory):
        has_register_rule = any(
            rule.get("opcode_id") == opcode_id
            and rule.get("operand_index") == operand_index
            and rule.get("raw_arg_kind_id") == item.get("raw_arg_kind_id")
            for rule in ctx.rules
        )
        expected = 1 if has_register_rule else 0
        if parsed_counts[operand_index] != expected:
            ctx.errors.append(f"{label} parsed register inventory is incomplete at operand {operand_index}")
    return result


def _state_from_snapshot(row: Mapping[str, object], snapshot: Mapping[str, object]) -> dict[str, object]:
    return {
        "pcode_id": row.get("pcode_id"),
        "runtime_address": row.get("runtime_address"),
        "allocation_generation": row.get("allocation_generation"),
        "lifecycle_sequence_at_capture": snapshot.get("lifecycle_sequence_at_capture"),
        "opcode_id": snapshot.get("opcode_id"),
        "arg_count": snapshot.get("arg_count"),
        "operands": snapshot.get("operand_lineage_inventory"),
    }


def _state_signature(row: Mapping[str, object]) -> tuple[object, ...]:
    operands = row.get("operands")
    operand_signature = (
        tuple(
            (
                item.get("operand_index"),
                item.get("operand_lineage_id"),
                item.get("raw_arg_kind_id"),
                item.get("raw_payload_sha256"),
            )
            for item in operands
            if isinstance(item, Mapping)
        )
        if isinstance(operands, list)
        else ()
    )
    return (
        row.get("pcode_id"),
        row.get("runtime_address"),
        row.get("allocation_generation"),
        row.get("opcode_id"),
        row.get("arg_count"),
        operand_signature,
    )


def _state_lifecycle_positions(raw: object) -> list[int]:
    if not isinstance(raw, list):
        return []
    return [
        position
        for state in raw
        if isinstance(state, Mapping) and _int(position := state.get("lifecycle_sequence_at_capture"))
    ]


def _shared_lifecycle_position(
    raw: object,
    side: str,
    ctx: _Context,
) -> int | None:
    positions = _state_lifecycle_positions(raw)
    if not positions:
        return None
    if len(set(positions)) != 1:
        ctx.errors.append(f"PCode mutation {side} must share one lifecycle position")
        return None
    return positions[0]


def _event_lifecycle_interval(
    kind: str,
    row: Mapping[str, object],
    ctx: _Context,
) -> tuple[int, int] | None:
    if kind == "rewrite":
        position = row.get("lifecycle_sequence_at_capture")
        return (position, position) if _int(position) else None
    if kind == "emission":
        position = row.get("emission_lifecycle_sequence_at_capture")
        return (position, position) if _int(position) else None
    pre = _shared_lifecycle_position(row.get("inputs"), "inputs", ctx)
    post = _shared_lifecycle_position(row.get("outputs"), "outputs", ctx)
    if pre is not None and post is not None and pre > post:
        ctx.errors.append("PCode mutation pre-state lifecycle position exceeds post-state")
    if pre is None:
        pre = post
    if post is None:
        post = pre
    return (pre, post) if pre is not None and post is not None else None


def _event_pcode_ids(kind: str, row: Mapping[str, object]) -> set[str]:
    if kind in {"rewrite", "emission"}:
        pcode_id = row.get("pcode_id")
        return {pcode_id} if isinstance(pcode_id, str) else set()
    result: set[str] = set()
    for side in (row.get("inputs"), row.get("outputs")):
        if not isinstance(side, list):
            continue
        result.update(
            pcode_id
            for state in side
            if isinstance(state, Mapping) and isinstance((pcode_id := state.get("pcode_id")), str)
        )
    return result


def _allocator_first_observed_bounds(
    snapshots: Mapping[tuple[str, str], Mapping[str, object]],
) -> dict[str, int]:
    return {
        pcode_id: position
        for (pcode_id, stage), snapshot in snapshots.items()
        if stage == "allocator_input" and _int(position := snapshot.get("lifecycle_sequence_at_capture"))
    }


def _bind_mutation_output_positions(
    row: Mapping[str, object],
    interval: tuple[int, int] | None,
    snapshots: Mapping[tuple[str, str], Mapping[str, object]],
    first_observed_bounds: dict[str, int],
    ctx: _Context,
) -> None:
    if interval is None:
        return
    input_ids = _event_pcode_ids("mutation", {"inputs": row.get("inputs"), "outputs": []})
    output_ids = _event_pcode_ids("mutation", {"inputs": [], "outputs": row.get("outputs")})
    post_position = interval[1]
    for pcode_id in sorted(output_ids - input_ids):
        snapshot = snapshots.get((pcode_id, "mutation_output"))
        if snapshot is None:
            continue
        snapshot_position = snapshot.get("lifecycle_sequence_at_capture")
        if not _int(snapshot_position) or snapshot_position != post_position:
            ctx.errors.append(
                f"PCode {pcode_id} mutation_output snapshot lifecycle position disagrees "
                "with defining mutation post-position"
            )
            continue
        first_observed_bounds[pcode_id] = snapshot_position


def _validate_instructions(
    payload: Mapping[str, object],
    function: str,
    ctx: _Context,
) -> tuple[list[Mapping[str, object]], dict[tuple[str, str], Mapping[str, object]]]:
    rows = _rows(payload.get("pcode_instructions"), "pcode_instructions", ctx.errors)
    valid_rows: list[Mapping[str, object]] = []
    identities: list[tuple[int, int]] = []
    snapshots_by_stage: dict[tuple[str, str], Mapping[str, object]] = {}
    initial_inventory: list[tuple[str, int, str]] = []
    for index, raw in enumerate(rows):
        row = _closed(raw, _INSTRUCTION_FIELDS, f"PCode instruction {index}", ctx.errors)
        if row is None:
            continue
        pcode_id = row.get("pcode_id")
        address = row.get("runtime_address")
        generation = row.get("allocation_generation")
        if not isinstance(pcode_id, str) or not pcode_id:
            ctx.errors.append(f"PCode instruction {index} pcode_id must be non-empty string")
        elif pcode_id in ctx.pcode_rows:
            ctx.errors.append("duplicate pcode_id")
        else:
            ctx.pcode_rows[pcode_id] = row
        if not _positive(address) or not _positive(generation):
            ctx.errors.append(f"PCode instruction {index} identity must be positive integers")
        else:
            identities.append((address, generation))
        for field in ("block_order", "instruction_order"):
            if not _nonnegative(row.get(field)):
                ctx.errors.append(f"PCode instruction {index} {field} must be nonnegative integer")
        if row.get("function_symbol") != function:
            ctx.errors.append(f"PCode instruction {index} function symbol does not match requested function")
        if not isinstance(row.get("section_name"), str) or not row.get("section_name"):
            ctx.errors.append(f"PCode instruction {index} section_name must be non-empty string")
        if row.get("coordinate_space") != "function-relative-bytes":
            ctx.errors.append(f"PCode instruction {index} coordinate space must be function-relative-bytes")
        snapshots = _rows(
            row.get("stage_snapshots"),
            f"PCode instruction {index} stage_snapshots",
            ctx.errors,
        )
        if len(snapshots) not in (1, 2):
            ctx.errors.append(f"PCode instruction {index} must have one first-observed and optional emission snapshot")
        expected_stages: list[str] = []
        parsed_by_stage: dict[str, list[Mapping[str, object]]] = {}
        for snap_index, raw_snapshot in enumerate(snapshots):
            label = f"PCode instruction {index} snapshot {snap_index}"
            snapshot = _closed(raw_snapshot, _SNAPSHOT_FIELDS, label, ctx.errors)
            if snapshot is None:
                continue
            stage = snapshot.get("stage")
            if snap_index == 0 and stage not in ("allocator_input", "mutation_output"):
                ctx.errors.append(f"{label} must be first-observed snapshot")
            if snap_index == 1 and stage != "code_emission":
                ctx.errors.append(f"{label} must be code_emission")
            if isinstance(stage, str):
                expected_stages.append(stage)
                snapshots_by_stage[(str(pcode_id), stage)] = snapshot
            if snapshot.get("runtime_address") != address or snapshot.get("allocation_generation") != generation:
                ctx.errors.append(f"{label} identity does not match PCode instruction")
            _active(
                ctx,
                snapshot.get("runtime_address"),
                snapshot.get("allocation_generation"),
                snapshot.get("lifecycle_sequence_at_capture"),
                label,
            )
            opcode_id = snapshot.get("opcode_id")
            if not _nonnegative(opcode_id):
                ctx.errors.append(f"{label} opcode_id must be nonnegative integer")
            elif ctx.opcodes.get(opcode_id) != snapshot.get("opcode"):
                ctx.errors.append(f"{label} opcode mnemonic disagrees with trusted opcode table")
            if not _nonnegative(snapshot.get("arg_count")):
                ctx.errors.append(f"{label} arg_count must be nonnegative integer")
            inventory = _validate_operands(
                snapshot.get("operand_lineage_inventory"),
                snapshot.get("arg_count"),
                label,
                ctx,
            )
            parsed_rows = _validate_parsed(
                snapshot.get("parsed_register_operands"),
                opcode_id,
                inventory,
                label,
                ctx,
            )
            parsed_by_stage[str(stage)] = parsed_rows
            if snap_index == 0:
                ctx.allocatable_lineages.update(
                    str(parsed_row.get("operand_lineage_id"))
                    for parsed_row in parsed_rows
                    if parsed_row.get("allocation_requirement") == "allocator-rewrite-required"
                )
            if snap_index == 0 and stage == "allocator_input" and isinstance(pcode_id, str):
                for operand_row in inventory:
                    if isinstance(operand_row.get("operand_lineage_id"), str) and _nonnegative(
                        operand_row.get("operand_index")
                    ):
                        initial_inventory.append(
                            (
                                pcode_id,
                                operand_row["operand_index"],
                                operand_row["operand_lineage_id"],
                            )
                        )
                ctx.current[pcode_id] = _state_from_snapshot(row, snapshot)
        if len(set(expected_stages)) != len(expected_stages):
            ctx.errors.append(f"PCode instruction {index} has duplicate stage snapshot")
        emitted = len(snapshots) == 2
        if emitted and row.get("cross_stage_identity_confidence") != "derived-unique":
            ctx.errors.append(f"PCode instruction {index} emitted identity confidence must be derived-unique")
        if not emitted and row.get("cross_stage_identity_confidence") is not None:
            ctx.errors.append(f"PCode instruction {index} one-stage confidence must be null")
        valid_rows.append(row)
    if identities != sorted(identities):
        ctx.errors.append("pcode_instructions must be canonically ordered")
    if len(identities) != len(set(identities)):
        ctx.errors.append("duplicate PCode runtime address/generation")
    sorted_rows = sorted(
        (
            (
                row.get("runtime_address"),
                row.get("allocation_generation"),
                row.get("pcode_id"),
            )
            for row in valid_rows
            if _positive(row.get("runtime_address")) and _positive(row.get("allocation_generation"))
        ),
    )
    for index, (_address, _generation, pcode_id) in enumerate(sorted_rows):
        if pcode_id != f"pc-{index}":
            ctx.errors.append(f"PCode {pcode_id!r} has non-deterministic pcode_id")
    initial_inventory.sort(key=lambda item: (item[0], item[1]))
    for index, (_pcode_id, _operand_index, lineage) in enumerate(initial_inventory):
        expected = f"ol-{index}"
        if lineage != expected:
            ctx.errors.append(f"initial lineage {lineage!r} is not deterministic; expected {expected}")
        if lineage in ctx.parents:
            ctx.errors.append(f"lineage {lineage!r} is multiply defined")
        ctx.parents[lineage] = ()
    return valid_rows, snapshots_by_stage


def _validate_state(
    raw: object,
    label: str,
    ctx: _Context,
    *,
    allow_parents: bool,
) -> Mapping[str, object] | None:
    row = _closed(raw, _STATE_FIELDS, label, ctx.errors)
    if row is None:
        return None
    if not isinstance(row.get("pcode_id"), str) or not row.get("pcode_id"):
        ctx.errors.append(f"{label} pcode_id must be non-empty string")
    if not _positive(row.get("runtime_address")) or not _positive(row.get("allocation_generation")):
        ctx.errors.append(f"{label} raw PCode identity must be positive integers")
    _active(
        ctx,
        row.get("runtime_address"),
        row.get("allocation_generation"),
        row.get("lifecycle_sequence_at_capture"),
        label,
    )
    if not _nonnegative(row.get("opcode_id")) or row.get("opcode_id") not in ctx.opcodes:
        ctx.errors.append(f"{label} references unknown opcode_id")
    if not _nonnegative(row.get("arg_count")):
        ctx.errors.append(f"{label} arg_count must be nonnegative integer")
    _validate_operands(
        row.get("operands"),
        row.get("arg_count"),
        label,
        ctx,
        allow_parents=allow_parents,
    )
    pcode = ctx.pcode_rows.get(row.get("pcode_id")) if isinstance(row.get("pcode_id"), str) else None
    if pcode is None:
        ctx.errors.append(f"{label} references unknown pcode_id")
    elif row.get("runtime_address") != pcode.get("runtime_address") or row.get("allocation_generation") != pcode.get(
        "allocation_generation"
    ):
        ctx.errors.append(f"{label} raw identity does not reconstruct pcode_id")
    return row


def _first_parsed(
    ctx: _Context,
    snapshots: Mapping[tuple[str, str], Mapping[str, object]],
    pcode_id: str,
    operand_index: int,
) -> Mapping[str, object] | None:
    for stage in ("allocator_input", "mutation_output"):
        snapshot = snapshots.get((pcode_id, stage))
        if not isinstance(snapshot, Mapping):
            continue
        parsed_rows = snapshot.get("parsed_register_operands")
        if isinstance(parsed_rows, list):
            matches = [
                row for row in parsed_rows if isinstance(row, Mapping) and row.get("operand_index") == operand_index
            ]
            if len(matches) == 1:
                return matches[0]
    return None


def _validate_rewrite(
    raw: object,
    index: int,
    snapshots: Mapping[tuple[str, str], Mapping[str, object]],
    ctx: _Context,
) -> Mapping[str, object] | None:
    label = f"PCode rewrite {index}"
    row = _closed(raw, _REWRITE_FIELDS, label, ctx.errors)
    if row is None:
        return None
    sequence = row.get("pcode_event_sequence")
    if not _nonnegative(sequence):
        ctx.errors.append(f"{label} event sequence must be nonnegative integer")
    site = (
        ctx.rewrite_sites.get(row.get("instrumented_site_id"))
        if isinstance(row.get("instrumented_site_id"), str)
        else None
    )
    if site is None:
        ctx.errors.append(f"{label} references unknown rewrite site")
    pcode_id = row.get("pcode_id")
    operand_index = row.get("operand_index")
    current = ctx.current.get(pcode_id) if isinstance(pcode_id, str) else None
    operands = current.get("operands") if isinstance(current, Mapping) else None
    if not _nonnegative(operand_index) or not isinstance(operands, list) or operand_index >= len(operands):
        ctx.errors.append(f"{label} occurrence is absent from current PCode inventory")
        inventory_row = None
    else:
        inventory_row = operands[operand_index]
        if not isinstance(inventory_row, Mapping) or inventory_row.get("operand_lineage_id") != row.get(
            "operand_lineage_id"
        ):
            ctx.errors.append(f"{label} lineage does not occupy stated operand index")
    pcode = ctx.pcode_rows.get(pcode_id) if isinstance(pcode_id, str) else None
    if (
        pcode is None
        or pcode.get("runtime_address") != row.get("runtime_address")
        or pcode.get("allocation_generation") != row.get("allocation_generation")
    ):
        ctx.errors.append(f"{label} raw identity does not reconstruct pcode_id")
    _active(
        ctx,
        row.get("runtime_address"),
        row.get("allocation_generation"),
        row.get("lifecycle_sequence_at_capture"),
        label,
    )
    parsed = _first_parsed(
        ctx,
        snapshots,
        str(pcode_id),
        int(operand_index) if _nonnegative(operand_index) else -1,
    )
    if parsed is None:
        ctx.errors.append(f"{label} has no parsed register occurrence")
    else:
        for field in (
            "operand_lineage_id",
            "role",
            "class_id",
            "virtual_kind",
            "virtual",
        ):
            if row.get(field) != parsed.get(field):
                ctx.errors.append(f"{label} {field} disagrees with parsed occurrence")
        if parsed.get("allocation_requirement") != "allocator-rewrite-required":
            ctx.errors.append(f"{label} rewrites a fixed physical operand")
    _validate_class_shape(
        class_id=row.get("class_id"),
        class_name=row.get("class_name"),
        virtual_kind=row.get("virtual_kind"),
        label=label,
        errors=ctx.errors,
    )
    if row.get("ig_id") != row.get("virtual"):
        ctx.errors.append(f"{label} virtual must equal ig_id")
    if not _physical(row.get("allocated_physical")):
        ctx.errors.append(f"{label} physical register must be in 0..31")
    if row.get("source_stage") != "allocator_operand_rewrite" or row.get("confidence") != "observed":
        ctx.errors.append(f"{label} source/confidence shape is invalid")
    lineage = row.get("operand_lineage_id")
    if isinstance(lineage, str):
        ctx.origins.setdefault(lineage, []).append(row)
    return row


def _validate_mutation(
    raw: object,
    index: int,
    fresh_counter: list[int],
    snapshots: Mapping[tuple[str, str], Mapping[str, object]],
    mutation_outputs_seen: Counter[str],
    ctx: _Context,
) -> Mapping[str, object] | None:
    label = f"PCode mutation {index}"
    row = _closed(raw, _MUTATION_FIELDS, label, ctx.errors)
    if row is None:
        return None
    if ctx.mutation_sites.get(row.get("instrumented_site_id")) is None:
        ctx.errors.append(f"{label} references unknown mutation site")
    kind = row.get("mutation_kind")
    input_raw = _rows(row.get("inputs"), f"{label} inputs", ctx.errors)
    output_raw = _rows(row.get("outputs"), f"{label} outputs", ctx.errors)
    expected = {
        "update": (1, 1),
        "clone": (1, None),
        "replace": (None, None),
        "delete": (None, 0),
        "create": (0, None),
    }
    if kind not in expected:
        ctx.errors.append(f"{label} has unknown mutation kind")
    if kind == "update" and (len(input_raw), len(output_raw)) != (1, 1):
        ctx.errors.append(f"{label} update requires exactly one input and output")
    if kind == "clone" and (len(input_raw) != 1 or len(output_raw) < 2):
        ctx.errors.append(f"{label} clone requires one input and two or more outputs")
    if kind == "replace" and (not input_raw or not output_raw):
        ctx.errors.append(f"{label} replace requires non-empty inputs and outputs")
    if kind == "delete" and (not input_raw or output_raw):
        ctx.errors.append(f"{label} delete requires inputs and no outputs")
    if kind == "create" and (input_raw or not output_raw):
        ctx.errors.append(f"{label} create requires no inputs and non-empty outputs")
    inputs = [
        state
        for i, item in enumerate(input_raw)
        if (state := _validate_state(item, f"{label} input {i}", ctx, allow_parents=False)) is not None
    ]
    outputs = [
        state
        for i, item in enumerate(output_raw)
        if (state := _validate_state(item, f"{label} output {i}", ctx, allow_parents=True)) is not None
    ]
    input_ids = [state.get("pcode_id") for state in inputs]
    output_ids = [state.get("pcode_id") for state in outputs]
    for side, states in (("inputs", inputs), ("outputs", outputs)):
        identity_keys = [
            (
                state.get("pcode_id"),
                state.get("runtime_address"),
                state.get("allocation_generation"),
            )
            for state in states
        ]
        try:
            if identity_keys != sorted(identity_keys):
                ctx.errors.append(f"{label} {side} must be canonically ordered")
        except TypeError:
            ctx.errors.append(f"{label} {side} identities are not sortable")
    if len(input_ids) != len(set(input_ids)):
        ctx.errors.append(f"{label} duplicate input pcode_id")
    if len(output_ids) != len(set(output_ids)):
        ctx.errors.append(f"{label} duplicate output pcode_id")
    if kind == "update" and input_ids != output_ids:
        ctx.errors.append(f"{label} update must preserve pcode_id")
    if kind == "clone" and sum(pcode_id in set(input_ids) for pcode_id in output_ids) > 1:
        ctx.errors.append(f"{label} clone may retain input pcode_id at most once")
    if kind == "replace" and set(input_ids) & set(output_ids):
        ctx.errors.append(f"{label} replacement input/output IDs must be disjoint")
    live_not_consumed = set(ctx.current) - {str(pcode_id) for pcode_id in input_ids}
    for pcode_id in output_ids:
        if str(pcode_id) in live_not_consumed:
            ctx.errors.append(f"{label} output overwrites unrelated live pcode_id")
        if pcode_id not in input_ids:
            first_snapshot = snapshots.get((str(pcode_id), "mutation_output"))
            output_state = next((state for state in outputs if state.get("pcode_id") == pcode_id), None)
            if first_snapshot is None or output_state is None:
                ctx.errors.append(f"{label} new output lacks mutation_output first-observed snapshot")
            else:
                pcode_row = ctx.pcode_rows.get(str(pcode_id))
                snapshot_state = _state_from_snapshot(pcode_row, first_snapshot) if pcode_row is not None else {}
                if _state_signature(snapshot_state) != _state_signature(output_state):
                    ctx.errors.append(f"{label} mutation_output snapshot disagrees with output state")
                mutation_outputs_seen[str(pcode_id)] += 1
    input_lineages: set[str] = set()
    for state in inputs:
        current = ctx.current.get(str(state.get("pcode_id")))
        if current is None or _state_signature(current) != _state_signature(state):
            ctx.errors.append(f"{label} input state disagrees with replay state")
        operands = state.get("operands")
        if isinstance(operands, list):
            input_lineages.update(str(item.get("operand_lineage_id")) for item in operands if isinstance(item, Mapping))
    ordered_outputs = sorted(
        outputs,
        key=lambda state: (
            str(state.get("pcode_id")),
            state.get("runtime_address", 0),
            state.get("allocation_generation", 0),
        ),
    )
    for state in ordered_outputs:
        operands = state.get("operands")
        if not isinstance(operands, list):
            continue
        for operand_row in operands:
            if not isinstance(operand_row, Mapping):
                continue
            lineage = operand_row.get("operand_lineage_id")
            parents = operand_row.get("parent_lineage_ids")
            if lineage in ctx.parents:
                if parents is not None:
                    ctx.errors.append(f"{label} preserved lineage must omit parent_lineage_ids")
                if kind == "create":
                    ctx.errors.append(f"{label} create may not reuse an existing lineage")
                elif lineage not in input_lineages:
                    ctx.errors.append(f"{label} output reuses lineage absent from event inputs")
                continue
            expected_lineage = f"ol-{fresh_counter[0]}"
            fresh_counter[0] += 1
            if lineage != expected_lineage:
                ctx.errors.append(f"{label} fresh lineage id is not deterministic; expected {expected_lineage}")
            if kind == "clone":
                ctx.errors.append(f"{label} clone may not define fresh lineage")
            if not isinstance(parents, list):
                ctx.errors.append(f"{label} fresh lineage must define parent_lineage_ids")
                parent_tuple: tuple[str, ...] = ()
            else:
                parent_tuple = tuple(parent for parent in parents if isinstance(parent, str))
            if lineage in parent_tuple:
                ctx.errors.append(f"{label} self-parented lineage")
            if kind == "create" and parent_tuple:
                ctx.errors.append(f"{label} create lineage parents must be empty")
            if kind != "create" and not parent_tuple:
                ctx.errors.append(f"{label} derived lineage parents must be non-empty")
            if any(parent not in input_lineages for parent in parent_tuple):
                ctx.errors.append(f"{label} lineage parent is absent from event inputs")
            if isinstance(lineage, str):
                if lineage in ctx.parents:
                    ctx.errors.append(f"lineage {lineage!r} is multiply defined")
                ctx.parents[lineage] = parent_tuple
    for pcode_id in input_ids:
        ctx.current.pop(str(pcode_id), None)
    for state in outputs:
        ctx.current[str(state.get("pcode_id"))] = state
    return row


def _observe_emission(
    row: Mapping[str, object],
    snapshots: Mapping[tuple[str, str], Mapping[str, object]],
    ctx: _Context,
) -> _EmissionObservation | None:
    pcode_id = str(row.get("pcode_id"))
    label = f"PCode {pcode_id} emission"
    snapshot = snapshots.get((pcode_id, "code_emission"))
    if snapshot is None:
        ctx.errors.append(f"{label} event lacks code_emission snapshot")
        return None
    if ctx.emission_sites.get(row.get("emission_site_id")) is None:
        ctx.errors.append(f"PCode {pcode_id} references unknown emission site")
    snapshot_position = snapshot.get("lifecycle_sequence_at_capture")
    event_position = row.get("emission_lifecycle_sequence_at_capture")
    if not _int(snapshot_position) or not _int(event_position) or snapshot_position != event_position:
        ctx.errors.append(f"PCode {pcode_id} code_emission snapshot lifecycle position disagrees with emission event")
    if row.get("emission_runtime_address") != row.get("runtime_address") or row.get(
        "emission_allocation_generation"
    ) != row.get("allocation_generation"):
        ctx.errors.append(f"{label} raw identity does not reconstruct pcode_id")
    _active(
        ctx,
        row.get("emission_runtime_address"),
        row.get("emission_allocation_generation"),
        row.get("emission_lifecycle_sequence_at_capture"),
        label,
    )
    current_state = ctx.current.get(pcode_id)
    emitted_state = _state_from_snapshot(row, snapshot)
    if current_state is None or _state_signature(current_state) != _state_signature(emitted_state):
        ctx.errors.append(f"{label} snapshot disagrees with replay state at emission sequence")
    sequence = row.get("emission_event_sequence")
    if not _nonnegative(sequence):
        ctx.errors.append(f"{label} event sequence must be nonnegative integer")
        return None
    return _EmissionObservation(
        pcode_id,
        sequence,
        emitted_state,
        MappingProxyType(dict(ctx.parents)),
        MappingProxyType({key: tuple(values) for key, values in ctx.origins.items()}),
    )


def _replay_pcode_events(
    payload: Mapping[str, object],
    snapshots: Mapping[tuple[str, str], Mapping[str, object]],
    ctx: _Context,
) -> tuple[
    list[Mapping[str, object]],
    list[Mapping[str, object]],
    list[tuple[int, str, Mapping[str, object]]],
    list[_EmissionObservation],
]:
    rewrite_raw = _rows(payload.get("pcode_occurrences"), "pcode_occurrences", ctx.errors)
    mutation_raw = _rows(
        payload.get("pcode_operand_lineage_events"),
        "pcode_operand_lineage_events",
        ctx.errors,
    )
    rewrites: list[Mapping[str, object]] = []
    mutations: list[Mapping[str, object]] = []
    emissions: list[_EmissionObservation] = []
    events: list[tuple[int, str, Mapping[str, object]]] = []
    raw_rewrite_keys: list[tuple[int, str, int]] = []
    raw_mutation_sequences: list[int] = []
    for index, raw_row in enumerate(rewrite_raw):
        row = _closed(raw_row, _REWRITE_FIELDS, f"PCode rewrite {index}", ctx.errors)
        if row is None:
            continue
        sequence = row.get("pcode_event_sequence")
        if not _nonnegative(sequence):
            ctx.errors.append(f"PCode rewrite {index} event sequence must be nonnegative integer")
            continue
        events.append((sequence, "rewrite", row))
        if isinstance(row.get("pcode_id"), str) and _nonnegative(row.get("operand_index")):
            raw_rewrite_keys.append((sequence, row["pcode_id"], row["operand_index"]))
    for index, raw_row in enumerate(mutation_raw):
        row = _closed(raw_row, _MUTATION_FIELDS, f"PCode mutation {index}", ctx.errors)
        if row is None:
            continue
        sequence = row.get("pcode_event_sequence")
        if not _nonnegative(sequence):
            ctx.errors.append(f"PCode mutation {index} event sequence must be nonnegative integer")
            continue
        events.append((sequence, "mutation", row))
        raw_mutation_sequences.append(sequence)
    for row in ctx.pcode_rows.values():
        if _nonnegative(row.get("emission_event_sequence")):
            events.append((row["emission_event_sequence"], "emission", row))
    event_sequences = [sequence for sequence, _kind, _row in sorted(events, key=lambda item: item[0])]
    if event_sequences != list(range(len(events))):
        ctx.errors.append("PCode event sequence must be unique and contiguous from zero")
    fresh_counter = [len(ctx.parents)]
    mutation_outputs_seen: Counter[str] = Counter()
    rewrite_indexes = {id(row): index for index, row in enumerate(rewrite_raw)}
    mutation_indexes = {id(row): index for index, row in enumerate(mutation_raw)}
    terminal_ids: set[str] = set()
    first_observed_bounds = _allocator_first_observed_bounds(snapshots)
    prior_lifecycle_end: int | None = None
    for sequence, kind, row in sorted(events, key=lambda item: item[0]):
        del sequence
        interval = _event_lifecycle_interval(kind, row, ctx)
        if interval is not None:
            start, end = interval
            if prior_lifecycle_end is not None and start < prior_lifecycle_end:
                ctx.errors.append(f"PCode {kind} event moves backward in lifecycle time")
            prior_lifecycle_end = end if prior_lifecycle_end is None else max(prior_lifecycle_end, end)
        event_pcode_ids = _event_pcode_ids(kind, row)
        if interval is not None:
            for pcode_id in sorted(event_pcode_ids):
                first_observed = first_observed_bounds.get(pcode_id)
                if first_observed is not None and interval[0] < first_observed:
                    ctx.errors.append(f"PCode {kind} event for {pcode_id} precedes first-observed lifecycle position")
        for pcode_id in sorted(event_pcode_ids & terminal_ids):
            ctx.errors.append(f"PCode {kind} touches terminal emitted pcode_id {pcode_id}")
        if kind == "rewrite":
            validated = _validate_rewrite(row, rewrite_indexes[id(row)], snapshots, ctx)
            if validated is not None:
                rewrites.append(validated)
        elif kind == "mutation":
            validated = _validate_mutation(
                row,
                mutation_indexes[id(row)],
                fresh_counter,
                snapshots,
                mutation_outputs_seen,
                ctx,
            )
            if validated is not None:
                mutations.append(validated)
            _bind_mutation_output_positions(row, interval, snapshots, first_observed_bounds, ctx)
        elif kind == "emission":
            observation = _observe_emission(row, snapshots, ctx)
            if observation is not None:
                emissions.append(observation)
            terminal_ids.update(_event_pcode_ids(kind, row))
    if raw_rewrite_keys != sorted(raw_rewrite_keys):
        ctx.errors.append("pcode_occurrences must be canonically ordered")
    if raw_mutation_sequences != sorted(raw_mutation_sequences):
        ctx.errors.append("pcode_operand_lineage_events must be canonically ordered")
    for (pcode_id, stage), _snapshot in snapshots.items():
        if stage == "mutation_output" and mutation_outputs_seen[pcode_id] != 1:
            ctx.errors.append(f"PCode {pcode_id} mutation_output snapshot must correspond to exactly one new output")
    return rewrites, mutations, events, emissions


_RANGE_FIELDS = frozenset({"start", "end_exclusive", "bytes", "relocations", "machine_operand_mappings"})
_RELOCATION_FIELDS = frozenset(
    {
        "offset_within_range",
        "relocation_type_id",
        "target_symbol_table_index",
        "target_symbol",
        "addend",
    }
)
_MAPPING_FIELDS = frozenset(
    {
        "instruction_offset_within_range",
        "machine_operand_position",
        "machine_operand_key",
        "emission_pcode_operand_index",
        "operand_lineage_id",
        "physical_register",
    }
)


def _lineage_origins(
    lineage: str,
    ctx: _Context,
    active: set[str] | None = None,
    *,
    parents: Mapping[str, tuple[str, ...]] | None = None,
    origins: Mapping[str, tuple[Mapping[str, object], ...]] | None = None,
) -> list[Mapping[str, object]]:
    stack = set() if active is None else active
    if lineage in stack:
        ctx.errors.append(f"cyclic operand lineage at {lineage}")
        return []
    parent_map = ctx.parents if parents is None else parents
    origin_map: Mapping[str, object] = ctx.origins if origins is None else origins
    direct = origin_map.get(lineage, [])
    if direct:
        return list(direct)
    lineage_parents = parent_map.get(lineage)
    if lineage_parents is None:
        ctx.errors.append(f"undeclared operand lineage {lineage}")
        return []
    stack.add(lineage)
    result: list[Mapping[str, object]] = []
    for parent in lineage_parents:
        result.extend(
            _lineage_origins(
                parent,
                ctx,
                stack,
                parents=parent_map,
                origins=origins,
            )
        )
    stack.remove(lineage)
    unique: dict[tuple[object, ...], Mapping[str, object]] = {}
    for origin in result:
        key = (
            origin.get("pcode_id"),
            origin.get("operand_index"),
            origin.get("pcode_event_sequence"),
        )
        unique[key] = origin
    return list(unique.values())


_INDEXED_LOADS = frozenset(
    {
        "lbzx",
        "lbzux",
        "lhzx",
        "lhzux",
        "lhax",
        "lhaux",
        "lwzx",
        "lwzux",
        "lwbrx",
        "lwarx",
        "eciwx",
        "lfsx",
        "lfsux",
        "lfdx",
        "lfdux",
    }
)
_INDEXED_LOAD_UPDATES = frozenset({"lbzux", "lhzux", "lhaux", "lwzux", "lfsux", "lfdux"})
_INDEXED_STORES = frozenset(
    {
        "stbx",
        "stbux",
        "sthx",
        "sthux",
        "stwx",
        "stwux",
        "sthbrx",
        "stwbrx",
        "stwcx",
        "ecowx",
        "stfsx",
        "stfsux",
        "stfdx",
        "stfdux",
    }
)
_INDEXED_STORE_UPDATES = frozenset({"stbux", "sthux", "stwux", "stfsux", "stfdux"})
_D_FORM_UPDATES = frozenset({33, 35, 37, 39, 41, 43, 45, 49, 51, 53, 55, 57, 61})
_D_FORM_INTEGER_UPDATE_LOADS = frozenset({33, 35, 41, 43})
_X_FORM_UPDATES = frozenset({55, 119, 183, 247, 311, 375, 439, 567, 631, 695, 759})
_X_FORM_INTEGER_UPDATE_LOADS = frozenset({55, 119, 311, 375})
_INTEGER_RESULTS = frozenset(
    {
        "add",
        "addc",
        "adde",
        "addme",
        "addze",
        "subf",
        "subfc",
        "subfe",
        "subfme",
        "subfze",
        "neg",
        "mullw",
        "mulhw",
        "mulhwu",
        "divw",
        "divwu",
        "and",
        "andc",
        "or",
        "orc",
        "xor",
        "nand",
        "nor",
        "eqv",
        "slw",
        "srw",
        "sraw",
        "srawi",
        "cntlzw",
        "extsb",
        "extsh",
        "mr",
        "not",
    }
)
_COMPARE_OR_TRAP = frozenset({"cmpw", "cmplw", "tw", "td", "fcmpu", "fcmpo"})
_SPECIAL_DEFS = frozenset({"mfcr", "mfctr", "mflr", "mfxer", "mfspr", "mftb", "mffs"})
_SPECIAL_USES = frozenset({"mtcrf", "mtctr", "mtlr", "mtxer", "mtspr", "mtfsf"})
_CACHE_USES = frozenset({"dcbf", "dcbi", "dcbst", "dcbt", "dcbtst", "dcbz", "icbi"})
_FLOAT_RESULTS = frozenset(
    {
        "fadd",
        "fadds",
        "fsub",
        "fsubs",
        "fmul",
        "fmuls",
        "fdiv",
        "fdivs",
        "fsqrt",
        "fsqrts",
        "fres",
        "frsqrte",
        "fsel",
        "fmadd",
        "fmadds",
        "fmsub",
        "fmsubs",
        "fnmadd",
        "fnmadds",
        "fnmsub",
        "fnmsubs",
        "fmr",
        "fabs",
        "fnabs",
        "fneg",
        "frsp",
        "fctiw",
        "fctiwz",
    }
)
_PRIMARY_SEMANTIC_FORMS = {
    **{primary: "load" for primary in (32, 34, 40, 42, 48, 50)},
    **{primary: "load-update" for primary in (33, 35, 41, 43, 49, 51)},
    **{primary: "store" for primary in (36, 38, 44, 52, 54)},
    **{primary: "store-update" for primary in (37, 39, 45, 53, 55)},
    **{primary: "all-use" for primary in (2, 3, 10, 11)},
    **{primary: "result" for primary in (7, 8, 12, 13, 14, 15, 21, 23, 24, 25, 26, 27, 28, 29)},
    20: "result-update",
    **{primary: "no-register" for primary in (16, 17, 18, 19)},
}
_MNEMONIC_SEMANTIC_FORMS = {
    **{mnemonic: "indexed-load" for mnemonic in _INDEXED_LOADS},
    **{mnemonic: "indexed-store" for mnemonic in _INDEXED_STORES},
    **{mnemonic: "result" for mnemonic in _INTEGER_RESULTS | _FLOAT_RESULTS},
    **{mnemonic: "all-use" for mnemonic in _COMPARE_OR_TRAP | _SPECIAL_USES | _CACHE_USES},
    **{mnemonic: "result" for mnemonic in _SPECIAL_DEFS},
}


def _register_identity(name: str) -> tuple[int, int] | None:
    lowered = name.lower()
    if lowered.startswith("r") and lowered[1:].isdigit():
        physical = int(lowered[1:])
        return (0, physical) if 0 <= physical <= 31 else None
    if lowered.startswith("f") and lowered[1:].isdigit():
        physical = int(lowered[1:])
        return (1, physical) if 0 <= physical <= 31 else None
    return None


def _result_roles(_mnemonic: str, count: int) -> list[str]:
    return ["def"] + ["use"] * (count - 1) if count else []


def _result_update_roles(_mnemonic: str, count: int) -> list[str]:
    return ["use-def"] + ["use"] * (count - 1) if count else []


def _load_update_roles(_mnemonic: str, count: int) -> list[str]:
    if count != 2:
        raise _Malformed("update load requires nonzero base register")
    return ["def", "use-def"]


def _store_update_roles(_mnemonic: str, count: int) -> list[str]:
    if count != 2:
        raise _Malformed("update store requires nonzero base register")
    return ["use", "use-def"]


def _no_register_roles(mnemonic: str, count: int) -> list[str]:
    if count:
        raise _Malformed(f"ambiguous PowerPC semantic form {mnemonic!r}")
    return []


def _indexed_roles(mnemonic: str, count: int, *, store: bool) -> list[str]:
    roles = ["use" if store else "def"] + ["use"] * (count - 1)
    updates = _INDEXED_STORE_UPDATES if store else _INDEXED_LOAD_UPDATES
    if mnemonic in updates and count > 1:
        roles[1] = "use-def"
    return roles


_ROLE_BUILDERS = {
    "load": lambda mnemonic, count: _result_roles(mnemonic, count),
    "load-update": _load_update_roles,
    "store": lambda _mnemonic, count: ["use"] * count,
    "store-update": _store_update_roles,
    "all-use": lambda _mnemonic, count: ["use"] * count,
    "result": _result_roles,
    "result-update": _result_update_roles,
    "no-register": _no_register_roles,
    "indexed-load": lambda mnemonic, count: _indexed_roles(mnemonic, count, store=False),
    "indexed-store": lambda mnemonic, count: _indexed_roles(mnemonic, count, store=True),
}


def _roles_for_form(form: str, mnemonic: str, count: int) -> list[str]:
    builder = _ROLE_BUILDERS.get(form)
    if builder is None:
        raise _Malformed(f"ambiguous PowerPC semantic form {mnemonic!r}")
    return builder(mnemonic, count)


def _roles_for_semantic_form(primary: int, mnemonic: str, count: int) -> list[str]:
    if primary in {46, 47}:
        raise _Malformed("unsupported multi-register PowerPC memory instruction")
    form = _PRIMARY_SEMANTIC_FORMS.get(primary) or _MNEMONIC_SEMANTIC_FORMS.get(mnemonic)
    if form is not None:
        return _roles_for_form(form, mnemonic, count)
    raise _Malformed(f"unsupported PowerPC semantic form {mnemonic!r}")


def _paired_single_registers(word: int, offset: int) -> list[tuple[int, int, str, int, int]]:
    primary = word >> 26
    register = (word >> 21) & 31
    base_register = (word >> 16) & 31
    roles = {
        56: ("def", "use"),
        57: ("def", "use-def"),
        60: ("use", "use"),
        61: ("use", "use-def"),
    }[primary]
    identities = [(1, register)]
    selected_roles = [roles[0]]
    if primary in {57, 61} and base_register == 0:
        raise _Malformed("paired-single update requires nonzero base register")
    if base_register != 0:
        identities.append((0, base_register))
        selected_roles.append(roles[1])
    counters: Counter[str] = Counter()
    result: list[tuple[int, int, str, int, int]] = []
    for position, ((class_id, physical), role) in enumerate(zip(identities, selected_roles, strict=True)):
        key = f"{role}:{counters[role]}"
        counters[role] += 1
        result.append((offset, position, key, class_id, physical))
    return result


def _validate_raw_update_form(word: int) -> None:
    primary = word >> 26
    target = (word >> 21) & 31
    base = (word >> 16) & 31
    indexed_opcode = (word >> 1) & 0x3FF if primary == 31 else None
    is_update = primary in _D_FORM_UPDATES or indexed_opcode in _X_FORM_UPDATES
    is_integer_load = primary in _D_FORM_INTEGER_UPDATE_LOADS or indexed_opcode in _X_FORM_INTEGER_UPDATE_LOADS
    if is_update and base == 0:
        raise _Malformed("PowerPC update form RA must be nonzero")
    if is_integer_load and target == base:
        raise _Malformed("PowerPC integer update load RT must differ from RA")


def _standard_instruction_registers(
    decoder: object,
    raw: bytes,
    address: int,
    offset: int,
    reg_operand_type: int,
    mem_operand_type: int,
) -> list[tuple[int, int, str, int, int]]:
    instructions = list(decoder.disasm(raw, address))
    if len(instructions) != 1 or instructions[0].size != 4:
        raise _Malformed("emitted range does not decode as complete PowerPC instructions")
    instruction = instructions[0]
    identities: list[tuple[int, int]] = []
    for operand in instruction.operands:
        register_name: str | None = None
        if operand.type == reg_operand_type:
            register_name = instruction.reg_name(operand.reg)
        elif operand.type == mem_operand_type and operand.mem.base:
            register_name = instruction.reg_name(operand.mem.base)
        if register_name and (identity := _register_identity(register_name)) is not None:
            identities.append(identity)
    mnemonic = instruction.mnemonic.lower().rstrip(".")
    if mnemonic in {"mr", "not"} and len(identities) == 2:
        identities.append(identities[1])
    roles = _roles_for_semantic_form(int.from_bytes(raw, "big") >> 26, mnemonic, len(identities))
    if len(roles) != len(identities):
        raise _Malformed(f"ambiguous PowerPC semantic form {mnemonic!r}")
    counters: Counter[str] = Counter()
    result: list[tuple[int, int, str, int, int]] = []
    for position, ((class_id, physical), role) in enumerate(zip(identities, roles, strict=True)):
        key = f"{role}:{counters[role]}"
        counters[role] += 1
        result.append((offset, position, key, class_id, physical))
    return result


def _decode_registers(code: bytes, base: int) -> list[tuple[int, int, str, int, int]]:
    """Decode complete explicit GPR/FPR effects using a closed semantic inventory."""

    try:
        from capstone import CS_ARCH_PPC, CS_MODE_32, CS_MODE_BIG_ENDIAN, Cs
        from capstone.ppc import PPC_OP_MEM, PPC_OP_REG
    except ImportError as exc:  # pragma: no cover - declared runtime dependency
        raise _Malformed("PowerPC decoder is unavailable") from exc
    if len(code) % 4:
        raise _Malformed("emitted range does not contain complete PowerPC instructions")
    decoder = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN)
    decoder.detail = True
    result: list[tuple[int, int, str, int, int]] = []
    for offset in range(0, len(code), 4):
        raw = code[offset : offset + 4]
        word = int.from_bytes(raw, "big")
        _validate_raw_update_form(word)
        primary = word >> 26
        if primary in {56, 57, 60, 61}:
            result.extend(_paired_single_registers(word, offset))
            continue
        result.extend(
            _standard_instruction_registers(
                decoder,
                raw,
                base + offset,
                offset,
                PPC_OP_REG,
                PPC_OP_MEM,
            )
        )
    return result


def _validate_ranges(
    row: Mapping[str, object],
    emission_snapshot: Mapping[str, object],
    view: _FunctionObjectView,
    ctx: _Context,
    all_intervals: list[tuple[int, int, str]],
    anchors: dict[tuple[int, str], list[AnchorVirtualBinding]],
    observation: _EmissionObservation | None,
) -> None:
    pcode_id = str(row.get("pcode_id"))
    ranges = _rows(row.get("code_ranges"), f"PCode {pcode_id} code_ranges", ctx.errors)
    range_keys: list[tuple[object, ...]] = []
    parsed_emission = emission_snapshot.get("parsed_register_operands")
    parsed_by_index = (
        {
            item.get("operand_index"): item
            for item in parsed_emission
            if isinstance(item, Mapping) and _nonnegative(item.get("operand_index"))
        }
        if isinstance(parsed_emission, list)
        else {}
    )
    for range_index, raw_range in enumerate(ranges):
        label = f"PCode {pcode_id} range {range_index}"
        code_range = _closed(raw_range, _RANGE_FIELDS, label, ctx.errors)
        if code_range is None:
            continue
        start, end = code_range.get("start"), code_range.get("end_exclusive")
        if not _nonnegative(start) or not _nonnegative(end) or start >= end:
            ctx.errors.append(f"{label} must be ordered non-empty half-open range")
            continue
        if end > view.symbol_size:
            ctx.errors.append(f"{label} lies outside function extent")
            continue
        bytes_hex = code_range.get("bytes")
        if not isinstance(bytes_hex, str) or len(bytes_hex) != 2 * (end - start) or bytes_hex.lower() != bytes_hex:
            ctx.errors.append(f"{label} bytes must be exact lowercase hex for range")
            continue
        try:
            raw_bytes = bytes.fromhex(bytes_hex)
        except ValueError:
            ctx.errors.append(f"{label} bytes are invalid hex")
            continue
        object_bytes = view.section_data[view.symbol_start + start : view.symbol_start + end]
        if raw_bytes != object_bytes:
            ctx.errors.append(f"{label} candidate object bytes disagree")
        all_intervals.append((start, end, pcode_id))
        range_keys.append((start, end, bytes_hex))
        expected_relocations = [
            (offset - view.symbol_start - start, kind, symbol_index, target, addend)
            for offset, kind, symbol_index, target, addend in view.relocations
            if view.symbol_start + start <= offset < view.symbol_start + end
        ]
        relocation_rows = _rows(code_range.get("relocations"), f"{label} relocations", ctx.errors)
        actual_relocations: list[tuple[object, ...]] = []
        for relocation_index, raw_relocation in enumerate(relocation_rows):
            relocation = _closed(
                raw_relocation,
                _RELOCATION_FIELDS,
                f"{label} relocation {relocation_index}",
                ctx.errors,
            )
            if relocation is not None:
                for field in (
                    "offset_within_range",
                    "relocation_type_id",
                    "target_symbol_table_index",
                ):
                    if not _nonnegative(relocation.get(field)):
                        ctx.errors.append(f"{label} relocation {relocation_index} {field} must be nonnegative integer")
                if not _int(relocation.get("addend")):
                    ctx.errors.append(f"{label} relocation {relocation_index} addend must be integer")
                if not isinstance(relocation.get("target_symbol"), str):
                    ctx.errors.append(f"{label} relocation {relocation_index} target_symbol must be string")
                actual_relocations.append(
                    tuple(
                        relocation.get(field)
                        for field in (
                            "offset_within_range",
                            "relocation_type_id",
                            "target_symbol_table_index",
                            "target_symbol",
                            "addend",
                        )
                    )
                )
        if actual_relocations != expected_relocations:
            ctx.errors.append(f"{label} relocations disagree with candidate object")
        try:
            decoded = _decode_registers(raw_bytes, start)
        except (OverflowError, TypeError, ValueError) as exc:
            ctx.errors.append(f"{label} PowerPC decode failed: {exc}")
            decoded = []
        mapping_rows = _rows(
            code_range.get("machine_operand_mappings"),
            f"{label} machine mappings",
            ctx.errors,
        )
        mappings_by_position: dict[tuple[int, int], list[Mapping[str, object]]] = {}
        mapping_keys: list[tuple[object, ...]] = []
        for mapping_index, raw_mapping in enumerate(mapping_rows):
            mapping = _closed(
                raw_mapping,
                _MAPPING_FIELDS,
                f"{label} mapping {mapping_index}",
                ctx.errors,
            )
            if mapping is None:
                continue
            offset = mapping.get("instruction_offset_within_range")
            position = mapping.get("machine_operand_position")
            if not _nonnegative(offset) or not _nonnegative(position):
                ctx.errors.append(f"{label} mapping {mapping_index} positions must be nonnegative integers")
                continue
            if not _nonnegative(mapping.get("emission_pcode_operand_index")):
                ctx.errors.append(f"{label} mapping {mapping_index} emission operand index must be nonnegative integer")
            if not isinstance(mapping.get("operand_lineage_id"), str) or not mapping.get("operand_lineage_id"):
                ctx.errors.append(f"{label} mapping {mapping_index} lineage id must be non-empty string")
            if not isinstance(mapping.get("machine_operand_key"), str) or not mapping.get("machine_operand_key"):
                ctx.errors.append(f"{label} mapping {mapping_index} machine operand key must be non-empty string")
            if not _physical(mapping.get("physical_register")):
                ctx.errors.append(f"{label} mapping {mapping_index} physical register must be in 0..31")
            mappings_by_position.setdefault((offset, position), []).append(mapping)
            mapping_keys.append(
                (
                    offset,
                    position,
                    mapping.get("emission_pcode_operand_index"),
                    mapping.get("operand_lineage_id"),
                )
            )
        if mapping_keys != sorted(mapping_keys):
            ctx.errors.append(f"{label} machine mappings must be canonically ordered")
        decoded_positions = {(offset, position) for offset, position, _key, _class, _physical in decoded}
        if set(mappings_by_position) != decoded_positions or any(
            len(items) != 1 for items in mappings_by_position.values()
        ):
            ctx.errors.append(f"{label} requires exactly one mapping for every decoded register operand")
        for offset, position, machine_key, class_id, physical in decoded:
            matches = mappings_by_position.get((offset, position), [])
            if len(matches) != 1:
                continue
            mapping = matches[0]
            if mapping.get("machine_operand_key") != machine_key:
                ctx.errors.append(f"{label} mapping machine operand key disagrees with decoded role ordinal")
            operand_index = mapping.get("emission_pcode_operand_index")
            parsed = parsed_by_index.get(operand_index)
            if parsed is None or parsed.get("operand_lineage_id") != mapping.get("operand_lineage_id"):
                ctx.errors.append(f"{label} mapping operand index or lineage disagrees with emission snapshot")
                continue
            if parsed.get("class_id") != class_id:
                ctx.errors.append(f"{label} decoded register class disagrees with emission operand")
            if mapping.get("physical_register") != physical:
                ctx.errors.append(f"{label} decoded physical register mismatch")
            lineage = str(mapping.get("operand_lineage_id"))
            origins = _lineage_origins(
                lineage,
                ctx,
                parents=observation.parents if observation is not None else MappingProxyType({}),
                origins=observation.origins if observation is not None else MappingProxyType({}),
            )
            if (
                not origins
                and lineage not in ctx.allocatable_lineages
                and parsed.get("allocation_requirement") == "fixed-physical"
            ):
                if mapping.get("physical_register") != parsed.get("physical_register"):
                    ctx.errors.append(f"{label} fixed emission physical register disagrees")
                continue
            if len(origins) != 1:
                qualifier = "multiple" if len(origins) > 1 else "no"
                ctx.errors.append(f"{label} emitted lineage has {qualifier} allocator origins at emission")
                continue
            origin = origins[0]
            expected_physical = origin.get("allocated_physical")
            if (
                mapping.get("physical_register") != expected_physical
                or parsed.get("physical_register") != expected_physical
            ):
                ctx.errors.append(f"{label} lineage physical register disagrees with allocator origin")
                continue
            binding = AnchorVirtualBinding(
                start + offset,
                str(mapping.get("machine_operand_key")),
                pcode_id,
                lineage,
                int(origin.get("class_id")),
                int(origin.get("virtual")),
                int(expected_physical),
                "derived-unique",
            )
            anchors.setdefault((binding.code_offset, binding.machine_operand_key), []).append(binding)
    if range_keys != sorted(range_keys):
        ctx.errors.append(f"PCode {pcode_id} code_ranges must be canonically ordered")


def _validate_emissions(
    instruction_rows: list[Mapping[str, object]],
    snapshots: Mapping[tuple[str, str], Mapping[str, object]],
    view: _FunctionObjectView,
    ctx: _Context,
    observations: list[_EmissionObservation],
) -> tuple[int, dict[tuple[int, str], AnchorVirtualBinding]]:
    all_intervals: list[tuple[int, int, str]] = []
    alternatives: dict[tuple[int, str], list[AnchorVirtualBinding]] = {}
    emitted_ids: list[str] = []
    observations_by_id: dict[str, list[_EmissionObservation]] = {}
    for observation in observations:
        observations_by_id.setdefault(observation.pcode_id, []).append(observation)
    for row in instruction_rows:
        pcode_id = str(row.get("pcode_id"))
        emission = snapshots.get((pcode_id, "code_emission"))
        has_sequence = _nonnegative(row.get("emission_event_sequence"))
        if emission is None:
            if has_sequence:
                ctx.errors.append(f"PCode {pcode_id} emission event lacks code_emission snapshot")
            if row.get("code_ranges") != []:
                ctx.errors.append(f"PCode {pcode_id} non-emitted PCode must have no code ranges")
            for field in (
                "emission_event_sequence",
                "emission_site_id",
                "emission_runtime_address",
                "emission_allocation_generation",
                "emission_lifecycle_sequence_at_capture",
            ):
                if row.get(field) is not None:
                    ctx.errors.append(f"PCode {pcode_id} non-emitted {field} must be null")
            continue
        emitted_ids.append(pcode_id)
        if not has_sequence:
            ctx.errors.append(f"final PCode has no emission event: {pcode_id}")
        matches = observations_by_id.get(pcode_id, [])
        observation = matches[0] if len(matches) == 1 else None
        if observation is None:
            ctx.errors.append(f"PCode {pcode_id} must have exactly one chronological emission observation")
        if row.get("section_name") != view.section_name:
            ctx.errors.append(f"PCode {pcode_id} section name disagrees with candidate object")
        _validate_ranges(row, emission, view, ctx, all_intervals, alternatives, observation)
    final_ids = set(ctx.current)
    emission_counts = Counter(emitted_ids)
    for pcode_id in sorted(final_ids):
        if emission_counts[pcode_id] == 0:
            ctx.errors.append(f"final PCode has no emission event: {pcode_id}")
        elif emission_counts[pcode_id] != 1:
            ctx.errors.append(f"final PCode has multiple emission events: {pcode_id}")
        matches = observations_by_id.get(pcode_id, [])
        if len(matches) == 1 and _state_signature(matches[0].state) != _state_signature(ctx.current[pcode_id]):
            ctx.errors.append(f"PCode {pcode_id} final state changed after its emission")
    for pcode_id in set(emitted_ids) - final_ids:
        ctx.errors.append(f"non-final PCode has emission event: {pcode_id}")
    for previous, current in zip(sorted(all_intervals), sorted(all_intervals)[1:]):
        if current[0] < previous[1]:
            ctx.errors.append(f"candidate code ranges overlap between {previous[2]} and {current[2]}")
    bindings: dict[tuple[int, str], AnchorVirtualBinding] = {}
    for key, rows in alternatives.items():
        if len(rows) != 1:
            ctx.errors.append(f"anchor {key!r} has ambiguous covering PCode/operand alternatives")
        else:
            bindings[key] = rows[0]
    return len(emitted_ids), bindings


_PCODE_COVERAGE_FIELDS = frozenset(
    {
        "status",
        "operand_rewrite_sites_expected",
        "operand_rewrite_sites_hooked",
        "operand_mutation_sites_expected",
        "operand_mutation_sites_hooked",
        "code_emission_sites_expected",
        "code_emission_sites_hooked",
        "first_event_sequence",
        "last_event_sequence",
        "parsed_register_operands",
        "allocatable_register_operands",
        "fixed_physical_register_operands",
        "rewrite_events",
        "mutation_events",
        "final_pcodes",
        "emission_events",
        "event_cap",
        "dropped_events",
        "truncated",
        "errors",
    }
)
_COVERAGE_ALLOWED = frozenset(
    {
        "status",
        "ig_classes",
        "frame_areas",
        "spill_owned_ig_coverage",
        "pcode_instrumentation",
        "lifetime_identity",
        "allocator_stage",
        "frame_stage",
        "objects_seen",
        "virtual_bindings_seen",
        "frame_bindings_seen",
        "pcode_instructions_seen",
        "pcode_occurrences_seen",
        "caps",
        "truncated",
        "errors",
    }
)
_COVERAGE_REQUIRED = frozenset(
    {
        "pcode_instrumentation",
        "pcode_instructions_seen",
        "pcode_occurrences_seen",
        "caps",
        "truncated",
        "errors",
    }
)
_CAP_ALLOWED = frozenset(
    {
        "max_ig_nodes",
        "max_frame_objects_per_area",
        "max_pcode_instructions",
        "max_pcode_operands_per_instruction",
    }
)
_CAP_REQUIRED = frozenset({"max_pcode_instructions", "max_pcode_operands_per_instruction"})


def _empty_errors(value: object, label: str, errors: list[str]) -> None:
    rows = _rows(value, f"{label} errors", errors)
    if any(not isinstance(item, str) for item in rows):
        errors.append(f"{label} errors must contain strings")
    if all(isinstance(item, str) for item in rows) and rows != sorted(rows):
        errors.append(f"{label} errors must be canonically ordered")
    if rows:
        errors.append(f"{label} errors must be empty")


def _validate_recomputed_int(
    value: object,
    expected: int,
    field: str,
    errors: list[str],
    *,
    nonnegative: bool = True,
) -> None:
    valid = _nonnegative(value) if nonnegative else _int(value)
    if not valid:
        errors.append(f"{field} must be integer" + (" >= 0" if nonnegative else ""))
    elif value != expected:
        errors.append(f"{field} does not match recomputed PCode coverage")


def _validate_coverage(
    payload: Mapping[str, object],
    instruction_rows: list[Mapping[str, object]],
    rewrites: list[Mapping[str, object]],
    mutations: list[Mapping[str, object]],
    emission_count: int,
    snapshots: Mapping[tuple[str, str], Mapping[str, object]],
    ctx: _Context,
) -> None:
    coverage = _closed(
        payload.get("coverage"),
        _COVERAGE_ALLOWED,
        "coverage",
        ctx.errors,
        required=_COVERAGE_REQUIRED,
    )
    if coverage is None:
        return
    pcode = _closed(
        coverage.get("pcode_instrumentation"),
        _PCODE_COVERAGE_FIELDS,
        "pcode instrumentation",
        ctx.errors,
    )
    if pcode is None:
        return
    if pcode.get("status") != "complete":
        ctx.errors.append("pcode instrumentation status must be complete")
    site_counts = (
        ("operand_rewrite", len(ctx.rewrite_sites)),
        ("operand_mutation", len(ctx.mutation_sites)),
        ("code_emission", len(ctx.emission_sites)),
    )
    for prefix, proof_count in site_counts:
        expected = pcode.get(f"{prefix}_sites_expected")
        hooked = pcode.get(f"{prefix}_sites_hooked")
        _validate_recomputed_int(
            expected,
            proof_count,
            f"{prefix}_sites_expected",
            ctx.errors,
        )
        if not _nonnegative(hooked):
            ctx.errors.append(f"{prefix}_sites_hooked must be integer >= 0")
        elif hooked != expected:
            ctx.errors.append(f"{prefix} site coverage is incomplete")
    raw_event_count = (
        len(payload.get("pcode_occurrences", []))
        + len(payload.get("pcode_operand_lineage_events", []))
        + sum(
            1
            for row in instruction_rows
            if isinstance(row.get("stage_snapshots"), list)
            and any(
                isinstance(snapshot, Mapping) and snapshot.get("stage") == "code_emission"
                for snapshot in row["stage_snapshots"]
            )
        )
    )
    first = 0 if raw_event_count else -1
    last = raw_event_count - 1
    _validate_recomputed_int(
        pcode.get("first_event_sequence"),
        first,
        "first_event_sequence",
        ctx.errors,
        nonnegative=False,
    )
    _validate_recomputed_int(
        pcode.get("last_event_sequence"),
        last,
        "last_event_sequence",
        ctx.errors,
        nonnegative=False,
    )
    first_parsed: list[Mapping[str, object]] = []
    for row in instruction_rows:
        pcode_id = str(row.get("pcode_id"))
        snapshot = snapshots.get((pcode_id, "allocator_input")) or snapshots.get((pcode_id, "mutation_output"))
        parsed = snapshot.get("parsed_register_operands") if isinstance(snapshot, Mapping) else None
        if isinstance(parsed, list):
            first_parsed.extend(item for item in parsed if isinstance(item, Mapping))
    allocatable = [item for item in first_parsed if item.get("allocation_requirement") == "allocator-rewrite-required"]
    fixed = [item for item in first_parsed if item.get("allocation_requirement") == "fixed-physical"]
    counts = {
        "parsed_register_operands": len(first_parsed),
        "allocatable_register_operands": len(allocatable),
        "fixed_physical_register_operands": len(fixed),
        "rewrite_events": len(payload.get("pcode_occurrences", [])),
        "mutation_events": len(payload.get("pcode_operand_lineage_events", [])),
        "final_pcodes": len(ctx.current),
        "emission_events": emission_count,
    }
    for field, expected in counts.items():
        _validate_recomputed_int(pcode.get(field), expected, field, ctx.errors)
    expected_rewrites = Counter()
    for row in instruction_rows:
        pcode_id = str(row.get("pcode_id"))
        snapshot = snapshots.get((pcode_id, "allocator_input")) or snapshots.get((pcode_id, "mutation_output"))
        parsed = snapshot.get("parsed_register_operands") if isinstance(snapshot, Mapping) else None
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, Mapping) and item.get("allocation_requirement") == "allocator-rewrite-required":
                    expected_rewrites[(pcode_id, item.get("operand_index"))] += 1
    actual_rewrites = Counter((str(item.get("pcode_id")), item.get("operand_index")) for item in rewrites)
    for key in sorted(set(expected_rewrites) | set(actual_rewrites)):
        if expected_rewrites[key] != 1 or actual_rewrites[key] != 1:
            ctx.errors.append(f"allocatable operand {key!r} must have exactly one rewrite")
    event_cap = pcode.get("event_cap")
    if not _positive(event_cap):
        ctx.errors.append("PCode event_cap must be positive integer")
    elif raw_event_count >= event_cap:
        ctx.errors.append("PCode event cap was reached")
    dropped = pcode.get("dropped_events")
    if not _nonnegative(dropped):
        ctx.errors.append("dropped_events must be integer >= 0")
    elif dropped != 0:
        ctx.errors.append("PCode events were dropped")
    if pcode.get("truncated") is not False:
        ctx.errors.append("PCode instrumentation is truncated")
    _empty_errors(pcode.get("errors"), "pcode instrumentation", ctx.errors)
    _validate_recomputed_int(
        coverage.get("pcode_instructions_seen"),
        len(instruction_rows),
        "pcode_instructions_seen",
        ctx.errors,
    )
    _validate_recomputed_int(
        coverage.get("pcode_occurrences_seen"),
        len(payload.get("pcode_occurrences", [])),
        "pcode_occurrences_seen",
        ctx.errors,
    )
    caps = coverage.get("caps")
    if not isinstance(caps, Mapping):
        ctx.errors.append("coverage caps must be object")
    else:
        _closed(caps, _CAP_ALLOWED, "coverage caps", ctx.errors, required=_CAP_REQUIRED)
        max_instructions = caps.get("max_pcode_instructions")
        max_operands = caps.get("max_pcode_operands_per_instruction")
        if not _positive(max_instructions) or len(instruction_rows) >= max_instructions:
            ctx.errors.append("PCode instruction cap was reached or invalid")
        if not _positive(max_operands):
            ctx.errors.append("PCode operand cap must be positive integer")
        else:
            for row in instruction_rows:
                snapshots_value = row.get("stage_snapshots")
                if isinstance(snapshots_value, list) and any(
                    isinstance(snap, Mapping)
                    and _nonnegative(snap.get("arg_count"))
                    and snap.get("arg_count") >= max_operands
                    for snap in snapshots_value
                ):
                    ctx.errors.append("PCode operand cap was reached")
    if coverage.get("truncated") is not False:
        ctx.errors.append("coverage is truncated")
    _empty_errors(coverage.get("errors"), "coverage", ctx.errors)


def validate_pcode_lineage(
    payload: object,
    proof: InstrumentationProof,
    candidate_object: Path,
    function: str,
) -> PCodeLineageValidation:
    """Validate a capture without ever granting capability on partial evidence."""

    try:
        copied = _copy_json(payload)
    except Exception as exc:
        return PCodeLineageValidation(
            MappingProxyType({}),
            MappingProxyType({}),
            frozenset(),
            (f"PCode lineage diagnostic normalization failed: malformed {type(exc).__name__}",),
        )
    if not isinstance(copied, Mapping):
        return PCodeLineageValidation(
            MappingProxyType({}),
            MappingProxyType({}),
            frozenset(),
            ("PCode lineage payload must be object",),
        )
    normalized = _freeze(copied)
    errors: list[str] = []
    top = _closed(copied, _TOP_ALLOWED, "PCode lineage payload", errors, required=_TOP_REQUIRED)
    if top is None:  # pragma: no cover - copied mapping
        return PCodeLineageValidation(normalized, MappingProxyType({}), frozenset(), tuple(errors))
    try:
        ctx = _context(proof, errors)
        if ctx is None:
            return PCodeLineageValidation(normalized, MappingProxyType({}), frozenset(), tuple(errors))
        _replay_lifecycle(top, ctx)
        view = _load_object(candidate_object, function)
        instructions, snapshots = _validate_instructions(top, function, ctx)
        rewrites, mutations, _events, emission_observations = _replay_pcode_events(top, snapshots, ctx)
        emission_count, bindings = _validate_emissions(
            instructions,
            snapshots,
            view,
            ctx,
            emission_observations,
        )
        _validate_coverage(top, instructions, rewrites, mutations, emission_count, snapshots, ctx)
    except Exception as exc:
        errors.append(f"PCode lineage contains malformed values: {type(exc).__name__}: {exc}")
        bindings = {}
    if errors:
        return PCodeLineageValidation(normalized, MappingProxyType({}), frozenset(), tuple(errors))
    return PCodeLineageValidation(
        normalized,
        MappingProxyType(dict(sorted(bindings.items()))),
        frozenset({CAPABILITY}),
        (),
    )


__all__ = [
    "AnchorVirtualBinding",
    "PCodeLineageValidation",
    "validate_pcode_lineage",
]
