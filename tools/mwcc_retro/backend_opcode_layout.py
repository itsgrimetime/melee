"""Exact opcode, constructor, and operand-layout audit for retail GC/1.2.5n.

The retail compiler stores opcode metadata as 468 four-word records.  The
first two words are pointers; treating the record bytes themselves as text is
both incorrect and dangerously permissive.  This module dereferences every
row through the strict PE image, validates the generic constructor evidence,
and reports every non-generic layout as a separate proof obligation.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import asdict, dataclass
from typing import Any

from tools.mwcc_retro.pe import Image
from tools.mwcc_retro.x86_cfg import RawCfg

RETAIL_GC125N_SHA256 = (
    "ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c"
)
OPCODE_METADATA_TABLE = 0x005654B0
OPCODE_METADATA_ROW_SIZE = 16
OPCODE_COUNT = 468
GENERIC_CONSTRUCTOR = 0x004A2660
GENERIC_CONSTRUCTOR_END = 0x004A2B56
ALLOCATOR_REWRITE = 0x004CE1A0

CUSTOM_OPCODES = frozenset({3, 4, 12, 13, 15, 16, 199})
VARIADIC_OPCODES = frozenset({1, 19, 20, 39, 54})

# The mapping is decoded from the generic constructor's character dispatch.
# Every use is gated by the exact bytes of GENERIC_CONSTRUCTOR..END below.
_GENERIC_FORMAT_KINDS: dict[str, tuple[int, str, int | None, str | None]] = {
    "C": (2, "special", None, None),
    "L": (2, "special", None, None),
    "M": (4, "memory", None, None),
    "V": (0, "gpr", 0, "r"),
    "X": (2, "special", None, None),
    "Y": (3, "cr", None, None),
    "Z": (3, "cr", None, None),
    "b": (0, "gpr", 0, "r"),
    "c": (3, "cr", None, None),
    "f": (1, "fpr", 1, "f"),
    "i": (4, "immediate", None, None),
    "l": (5, "branch-target", None, None),
    "m": (4, "memory", None, None),
    "p": (10, "opaque", None, None),
    "r": (0, "gpr", 0, "r"),
    "v": (9, "vector", 9, "v"),
}

# These are not guesses about a generic parser.  They are the exact write or
# front-end construction instructions which must be reconciled by the custom
# layout audit.  The instruction bytes are re-read from the accepted RawCfg.
_CUSTOM_SITE_ADDRESSES: dict[int, tuple[int, ...]] = {
    3: (0x004A317B, 0x004A3213),
    4: (0x004A319B, 0x004A327D),
    12: (0x004A3540,),
    13: (0x004A3538,),
    15: (0x004A3530,),
    16: (0x004A3527,),
    199: (
        0x0046B4C1,
        0x0046E097,
        0x0046E21A,
        0x0046E30A,
        0x004703F3,
        0x0047094D,
        0x004718DF,
    ),
}


@dataclass(frozen=True, slots=True)
class OperandLayoutDescriptor:
    opcode_id: int
    operand_index: int
    format_token: str
    format_code: str
    role: str
    raw_arg_kind_id: int
    register_form: str
    class_id: int | None
    virtual_kind: str | None
    expansion_kind: str
    expansion_count: int | None
    fixed_payload: int | None = None


@dataclass(frozen=True, slots=True)
class OpcodeMetadataRow:
    opcode_id: int
    entry_address: int
    mnemonic_pointer: int
    format_pointer: int
    mnemonic: str
    format_string: str
    flags: int
    encoding: int
    entry_bytes_hex: str
    constructor_kind: str
    operand_descriptors: tuple[OperandLayoutDescriptor, ...]


@dataclass(frozen=True, slots=True)
class ConstructorEvidence:
    opcode_id: int
    addresses: tuple[int, ...]
    instruction_bytes_hex: tuple[str, ...]
    provenance: str


@dataclass(frozen=True, slots=True)
class VariadicCountSource:
    opcode_id: int
    source: str
    base_operand_count: int
    expansion: str


@dataclass(frozen=True, slots=True)
class RegisterDomain:
    raw_arg_kind_id: int
    register_form: str
    class_id: int | None
    virtual_kind: str | None
    physical_min: int | None
    physical_max: int | None
    evidence: str


@dataclass(frozen=True, slots=True)
class OpcodeLayoutInventory:
    """Complete table plus explicit closed and unresolved obligations."""

    compiler_sha256: str
    metadata_sha256: str
    generic_constructor_sha256: str
    opcode_rows: tuple[OpcodeMetadataRow, ...]
    custom_constructors: tuple[ConstructorEvidence, ...]
    variadic_sources: tuple[VariadicCountSource, ...]
    register_domains: tuple[RegisterDomain, ...]
    unresolved: tuple[str, ...]
    proof_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cstring(image: Image, address: int, *, maximum: int = 512) -> str:
    payload = bytearray()
    for offset in range(maximum):
        value = image.read(address + offset, 1)[0]
        if value == 0:
            try:
                return payload.decode("ascii")
            except UnicodeDecodeError as exc:
                raise ValueError(
                    f"opcode string at {address:#x} is not ASCII"
                ) from exc
        payload.append(value)
    raise ValueError(f"unterminated opcode string at {address:#x}")


def _format_tokens(format_string: str) -> tuple[tuple[str, str, str], ...]:
    if format_string == "?":
        return ()
    rows: list[tuple[str, str, str]] = []
    for token in format_string.split(","):
        if not token or token == "#":
            continue
        marker = token[0] if token[0] in "=+" else ""
        code = token[1:] if marker else token
        if len(code) != 1:
            raise ValueError(f"invalid opcode format token {token!r}")
        rows.append((token, code, {"": "use", "=": "def", "+": "use-def"}[marker]))
    return tuple(rows)


def _generic_descriptors(
    opcode_id: int, format_string: str
) -> tuple[OperandLayoutDescriptor, ...]:
    rows: list[OperandLayoutDescriptor] = []
    for operand_index, (token, code, role) in enumerate(
        _format_tokens(format_string)
    ):
        if code not in _GENERIC_FORMAT_KINDS:
            raise ValueError(
                f"opcode {opcode_id} has non-generic format code {code!r}"
            )
        raw_kind, register_form, class_id, virtual_kind = (
            _GENERIC_FORMAT_KINDS[code]
        )
        expansion_kind = "one"
        expansion_count: int | None = 1
        fixed_payload: int | None = None
        if code == "V":
            expansion_kind = "remaining"
            expansion_count = None
        elif code == "Y":
            expansion_kind = "fixed"
            expansion_count = 8
        elif code == "C":
            fixed_payload = 1
        elif code == "L":
            fixed_payload = 2
        elif code in {"X", "Z"}:
            fixed_payload = 0
        rows.append(
            OperandLayoutDescriptor(
                opcode_id=opcode_id,
                operand_index=operand_index,
                format_token=token,
                format_code=code,
                role=role,
                raw_arg_kind_id=raw_kind,
                register_form=register_form,
                class_id=class_id,
                virtual_kind=virtual_kind,
                expansion_kind=expansion_kind,
                expansion_count=expansion_count,
                fixed_payload=fixed_payload,
            )
        )
    return tuple(rows)


def _instruction_bytes(cfg: RawCfg, addresses: tuple[int, ...]) -> tuple[str, ...]:
    rows = {row.address: row.bytes_hex for row in cfg.instructions}
    missing = tuple(address for address in addresses if address not in rows)
    if missing:
        rendered = ", ".join(f"{address:#x}" for address in missing)
        raise ValueError(f"custom constructor evidence is unreachable: {rendered}")
    return tuple(rows[address] for address in addresses)


def _custom_evidence(cfg: RawCfg) -> tuple[ConstructorEvidence, ...]:
    result: list[ConstructorEvidence] = []
    for opcode_id in sorted(CUSTOM_OPCODES):
        addresses = _CUSTOM_SITE_ADDRESSES[opcode_id]
        result.append(
            ConstructorEvidence(
                opcode_id=opcode_id,
                addresses=addresses,
                instruction_bytes_hex=_instruction_bytes(cfg, addresses),
                provenance=(
                    "frontend-objobject-construction"
                    if opcode_id == 199
                    else "pcode-opcode-rewrite"
                ),
            )
        )
    return tuple(result)


def analyze_opcode_layouts(
    image: Image,
    cfg: RawCfg,
    values: object | None = None,
    *,
    expected_sha256: str = RETAIL_GC125N_SHA256,
) -> OpcodeLayoutInventory:
    """Read and validate the exact 468-row opcode metadata table.

    ``proof_ready`` deliberately remains false until the non-generic layout
    and stage-specific virtual/physical range audits have supplied their
    closed evidence through ``values``.  Correct raw metadata is necessary,
    but is not sufficient to promote operand rules.
    """

    unresolved: list[str] = []
    if image.sha256 != expected_sha256:
        unresolved.append(
            f"compiler-sha256:{image.sha256}:expected:{expected_sha256}"
        )

    raw_table = image.read(
        OPCODE_METADATA_TABLE, OPCODE_COUNT * OPCODE_METADATA_ROW_SIZE
    )
    generic_bytes = image.read(
        GENERIC_CONSTRUCTOR, GENERIC_CONSTRUCTOR_END - GENERIC_CONSTRUCTOR
    )
    rows: list[OpcodeMetadataRow] = []
    mnemonics: set[str] = set()
    for opcode_id in range(OPCODE_COUNT):
        entry_address = OPCODE_METADATA_TABLE + opcode_id * OPCODE_METADATA_ROW_SIZE
        raw = raw_table[
            opcode_id * OPCODE_METADATA_ROW_SIZE :
            (opcode_id + 1) * OPCODE_METADATA_ROW_SIZE
        ]
        mnemonic_pointer, format_pointer, flags, encoding = struct.unpack(
            "<IIII", raw
        )
        mnemonic = _cstring(image, mnemonic_pointer)
        format_string = _cstring(image, format_pointer)
        if not mnemonic:
            unresolved.append(f"empty-mnemonic:{opcode_id}")
        elif mnemonic in mnemonics:
            unresolved.append(f"duplicate-mnemonic:{opcode_id}:{mnemonic}")
        mnemonics.add(mnemonic)

        constructor_kind = "generic-fixed"
        descriptors: tuple[OperandLayoutDescriptor, ...] = ()
        if opcode_id in CUSTOM_OPCODES:
            constructor_kind = "custom"
        else:
            if format_string == "?":
                unresolved.append(f"unexpected-custom-format:{opcode_id}")
            else:
                try:
                    descriptors = _generic_descriptors(opcode_id, format_string)
                except ValueError as exc:
                    unresolved.append(str(exc))
            if opcode_id in VARIADIC_OPCODES:
                constructor_kind = "generic-variadic"
                if not format_string.startswith("#"):
                    unresolved.append(f"variadic-marker-missing:{opcode_id}")

        rows.append(
            OpcodeMetadataRow(
                opcode_id=opcode_id,
                entry_address=entry_address,
                mnemonic_pointer=mnemonic_pointer,
                format_pointer=format_pointer,
                mnemonic=mnemonic,
                format_string=format_string,
                flags=flags,
                encoding=encoding,
                entry_bytes_hex=raw.hex(),
                constructor_kind=constructor_kind,
                operand_descriptors=descriptors,
            )
        )

    if tuple(row.opcode_id for row in rows) != tuple(range(OPCODE_COUNT)):
        unresolved.append("opcode-id-domain-is-not-exact")
    if rows and (rows[0].mnemonic != "B" or rows[-1].mnemonic != "PEXIT"):
        unresolved.append("opcode-table-endpoints-differ")

    custom: tuple[ConstructorEvidence, ...] = ()
    try:
        custom = _custom_evidence(cfg)
    except ValueError as exc:
        unresolved.append(str(exc))

    variadic = tuple(
        VariadicCountSource(
            opcode_id=opcode_id,
            source="first-vararg-u32-at-generic-constructor",
            base_operand_count=rows[opcode_id].flags & 0xFF,
            expansion=(
                "remaining-gpr-count"
                if opcode_id in {39, 54}
                else "additional-operand-count"
            ),
        )
        for opcode_id in sorted(VARIADIC_OPCODES)
    )

    # Task 5 supplies exact stage-specific ranges.  Do not recreate the old
    # guessed 0..255 domains here.
    domains = tuple(getattr(values, "register_domains", ()))
    if not domains:
        unresolved.append("stage-specific-register-domains-unproved")
    if custom and not getattr(values, "custom_opcode_layouts_proved", False):
        unresolved.append("custom-opcode-layouts-unproved")
    if not getattr(values, "variadic_bounds_proved", False):
        unresolved.append("variadic-count-bounds-unproved")

    return OpcodeLayoutInventory(
        compiler_sha256=image.sha256,
        metadata_sha256=hashlib.sha256(raw_table).hexdigest(),
        generic_constructor_sha256=hashlib.sha256(generic_bytes).hexdigest(),
        opcode_rows=tuple(rows),
        custom_constructors=custom,
        variadic_sources=variadic,
        register_domains=domains,
        unresolved=tuple(sorted(set(unresolved))),
        proof_ready=not unresolved,
    )
