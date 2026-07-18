"""Exact opcode, constructor, and operand-domain audit for GC/1.2.5n.

This module accepts only facts bound to the exact retail compiler.  Metadata
is decoded as a 468-row pointer table; constructor semantics, custom layouts,
variadic expansion, PCodeArg storage, allocator rewrites, and register ranges
are independently bound to reviewed executable windows.  General Task 5
closure facts are used only for the final-list pseudo-op obligation--there are
no layout/domain attestation booleans.
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
GENERIC_CONSTRUCTOR_END = 0x004A2B6E
GENERIC_FORMAT_DISPATCH = 0x0055EC24
ENCODER_DISPATCH = 0x0055EE4C
ALLOCATOR_REWRITE = 0x004CE1A0
ALLOCATOR_REWRITE_PAYLOAD_WRITE = 0x004CE1E7
FINAL_ENCODER = 0x004A3590
FINAL_ENCODER_CALL = 0x004A2D17

CUSTOM_OPCODES = frozenset({3, 4, 12, 13, 15, 16, 199})
VARIADIC_OPCODES = frozenset({1, 19, 20, 39, 54})
PSEUDO_OPCODES = frozenset({466, 467})

# All evidence instructions must occur once and in this canonical address
# order in the supplied raw CFG.  The bytes are also compared to Image, so a
# synthetic CFG cannot bless altered executable bytes.
EVIDENCE_ADDRESSES = tuple(
    sorted(
        {
            0x004A2660,
            0x004A268C,
            0x004A2691,
            0x004A26A1,
            0x004A26E2,
            0x004A26F6,
            0x004A272D,
            0x004A2AB5,
            0x004A2AF0,
            0x004A2B45,
            FINAL_ENCODER_CALL,
            0x004A317B,
            0x004A319B,
            0x004A3213,
            0x004A327D,
            0x004A3527,
            0x004A3530,
            0x004A3538,
            0x004A3540,
            0x004A35B8,
            0x004A3838,
            0x004A3940,
            0x004A4500,
            0x004C23C2,
            0x004C23CB,
            0x004C23D4,
            0x004CDF9B,
            0x004CE08B,
            0x004CE16B,
            ALLOCATOR_REWRITE_PAYLOAD_WRITE,
        }
    )
)

_EXPECTED_METADATA_SHA256 = (
    "4dfd675154dd9085db6a08dd78c2719a0bf2a1621f71d009791020f6fb76f238"
)
_EXPECTED_GENERIC_CONSTRUCTOR_SHA256 = (
    "e03b0e8e4eab1cd3fb06f7131dc8e2b87bd823246ebeb001dbdf9a3e039c4682"
)
_EXPECTED_WINDOWS = (
    (
        "generic-constructor",
        GENERIC_CONSTRUCTOR,
        GENERIC_CONSTRUCTOR_END,
        _EXPECTED_GENERIC_CONSTRUCTOR_SHA256,
    ),
    (
        "allocator-class-initialization",
        0x004C23B0,
        0x004C23E0,
        "66fcb8d4b6aa1ac80506e4248fb24e294057e31911822bd517d1dfb59063f10c",
    ),
    (
        "allocator-class-drivers",
        0x004CDEF0,
        0x004CE18A,
        "1ed4bc0e61b5e73a4fc77f0c293fc5a7611e3b869076f88724d1a6b3bfae4890",
    ),
    (
        "allocator-rewrite",
        ALLOCATOR_REWRITE,
        0x004CE1EE,
        "8e5f21fa7601fab18256305f302e0023e3760bf19805d56820131cce701e05e2",
    ),
    (
        "final-encoder",
        FINAL_ENCODER,
        0x004A4CB1,
        "4427c2b7a7d452d2c79f1d6c6b4c9513339170a6c5176c74473d2daf458b0176",
    ),
    (
        "final-list-walker",
        0x004A2B70,
        0x004A2D40,
        "e7cda934ff63f98ee028e80c280a8d57e33b3935fd52e13ac4372e0b3777dfe4",
    ),
    (
        "call-tail-fixed-writer",
        0x004A2290,
        0x004A237A,
        "8123e7f479c8268144bf83a4cd12a0ea8bd6825868fa027d7578546c42db89d9",
    ),
    (
        "call-tail-extra-writer",
        0x004BC530,
        0x004BC7A7,
        "c60875040aca25bfb706bca448745016cce0d6b6220c6eac6327168293af5f20",
    ),
    (
        "call-tail-extra-count",
        0x004BC7B0,
        0x004BC97D,
        "1dfbb85580d8ba442690d0eccfbec35526e85241691386529a3c6e1621b3034d",
    ),
)
_EXPECTED_GENERIC_DISPATCH_SHA256 = (
    "d320196ff657cb8b778f710480b6de73cf1f817f8b77f0d3084527fc5ec4f14f"
)
_EXPECTED_ENCODER_DISPATCH_SHA256 = (
    "f26296f32952af2adbf193658dc76105294f0f366a39c2bada22cf98a8087020"
)

# Format-code mapping recovered from the exact character dispatch.  Each
# target is checked against GENERIC_FORMAT_DISPATCH and the complete generic
# constructor window digest before descriptors are accepted.
_GENERIC_FORMAT_KINDS: dict[str, tuple[int, str, int | None, str | None, int]] = {
    "C": (2, "special", None, None, 0x004A2A93),
    "L": (2, "special", None, None, 0x004A2AA4),
    "M": (4, "memory", None, None, 0x004A2975),
    "V": (0, "gpr", 0, "r", 0x004A2AB5),
    "X": (2, "special", None, None, 0x004A2AE0),
    "Y": (3, "cr", None, None, 0x004A2AF0),
    "Z": (3, "cr", None, None, 0x004A2B10),
    "b": (0, "gpr", 0, "r", 0x004A2734),
    "c": (3, "cr", None, None, 0x004A2760),
    "f": (1, "fpr", 1, "f", 0x004A2780),
    "i": (4, "immediate", None, None, 0x004A27C0),
    "l": (5, "branch-target", None, None, 0x004A27E0),
    "m": (4, "memory", None, None, 0x004A2840),
    "p": (10, "opaque", None, None, 0x004A2B40),
    "r": (0, "gpr", 0, "r", 0x004A2A75),
    "v": (9, "vector", 9, "v", 0x004A27A0),
}

_CUSTOM_LAYOUTS: dict[
    int, tuple[tuple[str, str, int, str, int | None, str | None], ...]
] = {
    3: (
        ("i", "use", 4, "immediate", None, None),
        ("c", "use", 3, "cr", None, None),
        ("i", "use", 4, "immediate", None, None),
    ),
    4: (
        ("i", "use", 4, "immediate", None, None),
        ("c", "use", 3, "cr", None, None),
        ("i", "use", 4, "immediate", None, None),
    ),
    12: (
        ("c", "use", 3, "cr", None, None),
        ("i", "use", 4, "immediate", None, None),
        ("l", "use", 5, "branch-target", None, None),
    ),
    13: (
        ("c", "use", 3, "cr", None, None),
        ("i", "use", 4, "immediate", None, None),
        ("l", "use", 5, "branch-target", None, None),
    ),
    15: (
        ("c", "use", 3, "cr", None, None),
        ("i", "use", 4, "immediate", None, None),
        ("l", "use", 5, "branch-target", None, None),
    ),
    16: (
        ("c", "use", 3, "cr", None, None),
        ("i", "use", 4, "immediate", None, None),
        ("l", "use", 5, "branch-target", None, None),
    ),
    199: (
        ("r", "def", 0, "gpr", 0, "r"),
        ("t", "use", 4, "immediate", None, None),
    ),
}

_CUSTOM_EVIDENCE: dict[int, tuple[int, ...]] = {
    3: (0x004A317B, 0x004A3213, 0x004A3940),
    4: (0x004A319B, 0x004A327D, 0x004A3940),
    12: (0x004A3540, 0x004A3838),
    13: (0x004A3538, 0x004A3838),
    15: (0x004A3530, 0x004A3838),
    16: (0x004A3527, 0x004A3838),
    199: (0x004A2B45, 0x004A4500),
}


@dataclass(frozen=True, slots=True)
class OperandRoleRule:
    register_flags_mask: int
    register_flags_value: int
    role: str


@dataclass(frozen=True, slots=True)
class OperandLayoutDescriptor:
    opcode_id: int
    operand_index: int
    descriptor_source: str
    format_token: str
    format_code: str | None
    role: str | None
    role_rules: tuple[OperandRoleRule, ...]
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
    count_width: int
    base_operand_count: int
    constructor_count_min: int
    constructor_count_max: int
    bound_kind: str
    count_arithmetic: str
    tail_expansion: str
    reachability: str
    reachable_count_min: int | None
    reachable_count_max: int | None
    call_addresses: tuple[int, ...]
    bound_evidence: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RegisterDomain:
    raw_arg_kind_id: int
    register_form: str
    class_id: int | None
    virtual_kind: str | None
    capture_stage: str
    allocation_state: str
    value_min: int
    value_max: int
    raw_payload_unsigned: bool
    evidence_addresses: tuple[int, ...]
    evidence: str

    @property
    def physical_min(self) -> int | None:
        return self.value_min if self.allocation_state == "physical" else None

    @property
    def physical_max(self) -> int | None:
        return self.value_max if self.allocation_state == "physical" else None


@dataclass(frozen=True, slots=True)
class RawPCodeArgLayout:
    size: int
    kind_offset: int
    kind_width: int
    flags_offset: int
    flags_width: int
    payload_offset: int
    payload_width: int
    payload_signed: bool
    allocator_rewrite_address: int
    allocator_rewritten_fields: tuple[str, ...]
    allocator_preserved_fields: tuple[str, ...]
    evidence_addresses: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PseudoOpcodeEvidence:
    opcode_id: int
    mnemonic: str
    encoding: int
    maximum_encodable_opcode: int
    final_disposition: str
    evidence_addresses: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class OpcodeLayoutInventory:
    compiler_sha256: str
    metadata_sha256: str
    generic_constructor_sha256: str
    opcode_rows: tuple[OpcodeMetadataRow, ...]
    custom_constructors: tuple[ConstructorEvidence, ...]
    variadic_sources: tuple[VariadicCountSource, ...]
    register_domains: tuple[RegisterDomain, ...]
    raw_pcode_arg_layout: RawPCodeArgLayout
    pseudo_opcodes: tuple[PseudoOpcodeEvidence, ...]
    unresolved: tuple[str, ...]
    proof_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OpcodeProofTables:
    opcode_table: tuple[dict[str, Any], ...]
    operand_rules: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "opcode_table": list(self.opcode_table),
            "operand_rules": list(self.operand_rules),
        }


def _cstring(image: Image, address: int, *, maximum: int = 512) -> str:
    payload = bytearray()
    for offset in range(maximum):
        value = image.read(address + offset, 1)[0]
        if value == 0:
            try:
                return payload.decode("ascii")
            except UnicodeDecodeError as exc:
                raise ValueError(f"opcode string at {address:#x} is not ASCII") from exc
        payload.append(value)
    raise ValueError(f"unterminated opcode string at {address:#x}")


def _format_tokens(format_string: str) -> tuple[tuple[str, str, str], ...]:
    if format_string == "?":
        return ()
    result: list[tuple[str, str, str]] = []
    for token in format_string.split(","):
        if not token or token == "#":
            continue
        marker = token[0] if token[0] in "=+" else ""
        code = token[1:] if marker else token
        if len(code) != 1:
            raise ValueError(f"invalid opcode format token {token!r}")
        result.append((token, code, {"": "use", "=": "def", "+": "use-def"}[marker]))
    return tuple(result)


def _descriptor(
    opcode_id: int,
    operand_index: int,
    token: str,
    code: str | None,
    role: str | None,
    raw_kind: int,
    register_form: str,
    class_id: int | None,
    virtual_kind: str | None,
    *,
    descriptor_source: str = "format",
    expansion_kind: str | None = None,
    expansion_count: int | None = None,
    role_rules: tuple[OperandRoleRule, ...] = (),
) -> OperandLayoutDescriptor:
    if expansion_kind is None:
        expansion_kind = "one"
        expansion_count = 1
    fixed_payload: int | None = None
    if code == "V" and descriptor_source == "format":
        expansion_kind = "remaining"
        expansion_count = None
    elif code == "Y" and descriptor_source == "format":
        expansion_kind = "fixed"
        expansion_count = 8
    elif code == "C":
        fixed_payload = 1
    elif code == "L":
        fixed_payload = 2
    elif code in {"X", "Z"}:
        fixed_payload = 0
    return OperandLayoutDescriptor(
        opcode_id=opcode_id,
        operand_index=operand_index,
        descriptor_source=descriptor_source,
        format_token=token,
        format_code=code,
        role=role,
        role_rules=role_rules,
        raw_arg_kind_id=raw_kind,
        register_form=register_form,
        class_id=class_id,
        virtual_kind=virtual_kind,
        expansion_kind=expansion_kind,
        expansion_count=expansion_count,
        fixed_payload=fixed_payload,
    )


def _generic_descriptors(
    opcode_id: int, format_string: str
) -> tuple[OperandLayoutDescriptor, ...]:
    result: list[OperandLayoutDescriptor] = []
    for index, (token, code, role) in enumerate(_format_tokens(format_string)):
        mapping = _GENERIC_FORMAT_KINDS.get(code)
        if mapping is None:
            raise ValueError(f"opcode {opcode_id} has non-generic format code {code!r}")
        raw_kind, register_form, class_id, virtual_kind, _handler = mapping
        result.append(
            _descriptor(
                opcode_id,
                index,
                token,
                code,
                role,
                raw_kind,
                register_form,
                class_id,
                virtual_kind,
            )
        )
    return tuple(result)


def _custom_descriptors(opcode_id: int) -> tuple[OperandLayoutDescriptor, ...]:
    return tuple(
        _descriptor(
            opcode_id,
            index,
            ("=" if role == "def" else "+" if role == "use-def" else "") + code,
            code,
            role,
            raw_kind,
            register_form,
            class_id,
            virtual_kind,
        )
        for index, (
            code,
            role,
            raw_kind,
            register_form,
            class_id,
            virtual_kind,
        ) in enumerate(_CUSTOM_LAYOUTS[opcode_id])
    )


_DYNAMIC_DEF_USE_DEF = (
    OperandRoleRule(0xFF, 0x02, "def"),
    OperandRoleRule(0xFF, 0x03, "use-def"),
)


def _tail_descriptor(
    opcode_id: int,
    operand_index: int,
    raw_kind: int,
    register_form: str,
    class_id: int | None,
    virtual_kind: str | None,
    role: str | None,
    expansion_kind: str,
    expansion_count: int | None,
    *,
    role_rules: tuple[OperandRoleRule, ...] = (),
) -> OperandLayoutDescriptor:
    return _descriptor(
        opcode_id,
        operand_index,
        "",
        None,
        role,
        raw_kind,
        register_form,
        class_id,
        virtual_kind,
        descriptor_source="variadic-tail",
        expansion_kind=expansion_kind,
        expansion_count=expansion_count,
        role_rules=role_rules,
    )


def _call_tail_descriptors(
    opcode_id: int, start_index: int
) -> tuple[OperandLayoutDescriptor, ...]:
    """Describe the exact call-liveness tail written after BL/BLRL creation.

    ``0x004A2290`` writes 49 fixed operands in the order below.  The BL path
    exposes all 49 after its formatted ``m`` operand.  BLRL's metadata base is
    zero, so its captured count exposes 48, conditionally the 49th, then any
    extra GPR uses emitted by ``0x004BC530``.  BCTRL has no proved producer and
    therefore never calls this helper here.
    """

    result = [
        _tail_descriptor(
            opcode_id,
            start_index,
            0,
            "gpr",
            0,
            "r",
            None,
            "fixed",
            11,
            role_rules=_DYNAMIC_DEF_USE_DEF,
        ),
        _tail_descriptor(
            opcode_id,
            start_index + 1,
            1,
            "fpr",
            1,
            "f",
            None,
            "fixed",
            14,
            role_rules=_DYNAMIC_DEF_USE_DEF,
        ),
        _tail_descriptor(
            opcode_id,
            start_index + 2,
            9,
            "vector",
            9,
            "v",
            None,
            "fixed",
            20,
            role_rules=_DYNAMIC_DEF_USE_DEF,
        ),
        _tail_descriptor(
            opcode_id,
            start_index + 3,
            3,
            "cr",
            None,
            None,
            "def",
            "one",
            1,
        ),
        _tail_descriptor(
            opcode_id,
            start_index + 4,
            3,
            "cr",
            None,
            None,
            "use-def",
            "one",
            1,
        ),
    ]
    if opcode_id == 1:
        result.append(
            _tail_descriptor(
                opcode_id,
                start_index + 5,
                3,
                "cr",
                None,
                None,
                "def",
                "fixed",
                2,
            )
        )
    else:
        result.extend(
            (
                _tail_descriptor(
                    opcode_id,
                    start_index + 5,
                    3,
                    "cr",
                    None,
                    None,
                    "def",
                    "one",
                    1,
                ),
                _tail_descriptor(
                    opcode_id,
                    start_index + 6,
                    3,
                    "cr",
                    None,
                    None,
                    "def",
                    "optional",
                    1,
                ),
            )
        )
    result.append(
        _tail_descriptor(
            opcode_id,
            start_index + len(result),
            0,
            "gpr",
            0,
            "r",
            "use",
            "remaining",
            None,
        )
    )
    return tuple(result)


def _sha256(image: Image, start: int, end: int) -> str:
    return hashlib.sha256(image.read(start, end - start)).hexdigest()


def _validate_binary_windows(image: Image, unresolved: list[str]) -> None:
    for label, start, end, expected in _EXPECTED_WINDOWS:
        observed = _sha256(image, start, end)
        if observed != expected:
            unresolved.append(f"{label}-evidence-altered:{observed}")
    generic_dispatch = hashlib.sha256(
        image.read(GENERIC_FORMAT_DISPATCH, 56 * 4)
    ).hexdigest()
    if generic_dispatch != _EXPECTED_GENERIC_DISPATCH_SHA256:
        unresolved.append(
            f"generic-format-dispatch-evidence-altered:{generic_dispatch}"
        )
    encoder_dispatch = hashlib.sha256(image.read(ENCODER_DISPATCH, 466 * 4)).hexdigest()
    if encoder_dispatch != _EXPECTED_ENCODER_DISPATCH_SHA256:
        unresolved.append(f"encoder-dispatch-evidence-altered:{encoder_dispatch}")


def _validate_format_dispatch(image: Image, unresolved: list[str]) -> None:
    for code, (*_shape, expected_target) in _GENERIC_FORMAT_KINDS.items():
        index = ord(code) - 0x3F
        target = struct.unpack(
            "<I", image.read(GENERIC_FORMAT_DISPATCH + index * 4, 4)
        )[0]
        if target != expected_target:
            unresolved.append(
                f"generic-format-handler-differs:{code}:{target:#x}:"
                f"expected:{expected_target:#x}"
            )
    unsupported_t_target = struct.unpack(
        "<I", image.read(GENERIC_FORMAT_DISPATCH + (ord("t") - 0x3F) * 4, 4)
    )[0]
    if unsupported_t_target != 0x004A2B45:
        unresolved.append(
            f"custom-t-format-handler-differs:{unsupported_t_target:#x}:"
            "expected:0x4a2b45"
        )
    expected_custom_handlers = {
        3: 0x004A3940,
        4: 0x004A3940,
        12: 0x004A3838,
        13: 0x004A3838,
        15: 0x004A3838,
        16: 0x004A3838,
        199: 0x004A4500,
    }
    for opcode_id, expected_target in expected_custom_handlers.items():
        target = struct.unpack("<I", image.read(ENCODER_DISPATCH + opcode_id * 4, 4))[0]
        if target != expected_target:
            unresolved.append(
                f"custom-encoder-handler-differs:{opcode_id}:{target:#x}:"
                f"expected:{expected_target:#x}"
            )


def _validate_cfg_evidence(image: Image, cfg: RawCfg, unresolved: list[str]) -> None:
    evidence = set(EVIDENCE_ADDRESSES)
    rows = [row for row in cfg.instructions if row.address in evidence]
    observed = tuple(row.address for row in rows)
    if observed != tuple(sorted(observed)):
        unresolved.append("evidence-address-order-differs")
    for address in EVIDENCE_ADDRESSES:
        matches = [row for row in rows if row.address == address]
        if len(matches) != 1:
            unresolved.append(
                f"evidence-instruction-cardinality:{address:#x}:{len(matches)}"
            )
            continue
        row = matches[0]
        try:
            cfg_bytes = bytes.fromhex(row.bytes_hex)
        except ValueError:
            unresolved.append(f"evidence-invalid-bytes:{address:#x}")
            continue
        if cfg_bytes != image.read(address, len(cfg_bytes)):
            label = (
                "allocator-rewrite"
                if address == ALLOCATOR_REWRITE_PAYLOAD_WRITE
                else "executable"
            )
            unresolved.append(f"{label}-evidence-bytes-differ:{address:#x}")


def _custom_evidence(cfg: RawCfg) -> tuple[ConstructorEvidence, ...]:
    rows = {row.address: row.bytes_hex for row in cfg.instructions}
    result: list[ConstructorEvidence] = []
    for opcode_id in sorted(CUSTOM_OPCODES):
        addresses = _CUSTOM_EVIDENCE[opcode_id]
        result.append(
            ConstructorEvidence(
                opcode_id=opcode_id,
                addresses=addresses,
                instruction_bytes_hex=tuple(
                    rows.get(address, "") for address in addresses
                ),
                provenance=(
                    "exact-encoder-layout"
                    if opcode_id == 199
                    else "exact-rewrite-and-encoder-layout"
                ),
            )
        )
    return tuple(result)


def _variadic_call_domains(
    values: object | None, unresolved: list[str]
) -> dict[int, tuple[tuple[int, int], ...]]:
    result: dict[int, list[tuple[int, int]]] = {
        opcode_id: [] for opcode_id in VARIADIC_OPCODES
    }
    if values is None:
        unresolved.append("variadic-callsite-value-closure-unproved")
        return {key: () for key in result}
    if getattr(values, "compiler_sha256", None) != RETAIL_GC125N_SHA256:
        unresolved.append("variadic-values-compiler-differs")
        return {key: () for key in result}
    if not getattr(values, "proof_ready", False) or getattr(values, "unresolved", ()):
        unresolved.append("variadic-callsite-value-closure-unresolved")
        return {key: () for key in result}

    calls = tuple(getattr(values, "calls", ()))
    wrapper_calls = tuple(
        call
        for call in calls
        if getattr(call, "target", None) in {0x004A25D0, 0x004A2620}
    )
    for call in wrapper_calls:
        opcodes = _resolve_argument_domain(
            _call_argument(call, 0),
            getattr(call, "function_entry", -1),
            0,
            calls,
        )
        if opcodes is None:
            unresolved.append(
                f"variadic-wrapper-opcode-unresolved:{getattr(call, 'address', -1):#x}"
            )
            continue
        for opcode_id in sorted(opcodes.intersection(VARIADIC_OPCODES)):
            counts = _resolve_argument_domain(
                _call_argument(call, 1),
                getattr(call, "function_entry", -1),
                1,
                calls,
            )
            if counts is None or not counts or any(
                count < 0 or count > 0xFFFFFFFF for count in counts
            ):
                unresolved.append(
                    f"variadic-count-domain-unresolved:{opcode_id}:"
                    f"{getattr(call, 'address', -1):#x}"
                )
                continue
            result[opcode_id].extend(
                (getattr(call, "address", -1), count) for count in sorted(counts)
            )
    if result[19]:
        unresolved.append("variadic-tail-producer-unproved:19")
    return {key: tuple(sorted(set(value))) for key, value in result.items()}


def _variadic_sources(
    rows: list[OpcodeMetadataRow],
    values: object | None,
    unresolved: list[str],
) -> tuple[VariadicCountSource, ...]:
    domains = _variadic_call_domains(values, unresolved)
    result: list[VariadicCountSource] = []
    for opcode_id in sorted(VARIADIC_OPCODES):
        base = rows[opcode_id].flags & 0xFF
        facts = domains[opcode_id]
        counts = tuple(count for _address, count in facts)
        call_addresses = tuple(sorted({address for address, _count in facts}))
        reachable = bool(facts)
        if opcode_id == 19:
            tail_expansion = (
                "post-constructor-unproved" if reachable else "unreachable"
            )
        elif opcode_id in {1, 20}:
            tail_expansion = "post-constructor"
        else:
            tail_expansion = "format-V"
        evidence = {
            0x004A268C,
            0x004A2691,
            0x004A26A1,
            0x004A26E2,
            *call_addresses,
        }
        if opcode_id in {1, 20}:
            evidence.update({0x004A2290, 0x004BC530, 0x004BC7B0})
        if opcode_id in {39, 54}:
            evidence.add(0x004A2AB5)
        result.append(
            VariadicCountSource(
                opcode_id=opcode_id,
                source="first-vararg-u32-at-generic-constructor",
                count_width=4,
                base_operand_count=base,
                constructor_count_min=0,
                constructor_count_max=0xFFFFFFFF,
                bound_kind="exact-u32-constructor-load",
                count_arithmetic="u32-add-metadata-low-byte-store-low-u16",
                tail_expansion=tail_expansion,
                reachability="reachable" if reachable else "unreachable",
                reachable_count_min=min(counts) if counts else None,
                reachable_count_max=max(counts) if counts else None,
                call_addresses=call_addresses,
                bound_evidence=tuple(sorted(evidence)),
            )
        )
    return tuple(result)


def _register_domains(
    image: Image, unresolved: list[str]
) -> tuple[RegisterDomain, ...]:
    """Decode class bounds from exact retail initialization/consumer bytes."""

    result: list[RegisterDomain] = []
    class_shapes = (
        ("gpr", 0, 0, "r", 0x004C23C2, 0x004CE08B),
        ("fpr", 1, 1, "f", 0x004C23CB, 0x004CE16B),
        ("vector", 9, 9, "v", 0x004C23D4, 0x004CDF9B),
    )
    virtual_starts: dict[str, int] = {}
    for form, _raw_kind, _class_id, _virtual_kind, init, _driver in class_shapes:
        instruction = image.read(init, 9)
        if instruction[:3] != b"\x66\xc7\x05":
            unresolved.append(f"register-domain-init-shape-differs:{form}:{init:#x}")
            continue
        virtual_starts[form] = struct.unpack("<H", instruction[7:9])[0]
    if set(virtual_starts) != {"gpr", "fpr", "vector"} or len(
        set(virtual_starts.values())
    ) != 1:
        unresolved.append("register-domain-class-initializers-disagree")
        return ()
    virtual_min = next(iter(virtual_starts.values()))
    if image.read(0x004CE1D7, 4) != b"\x0f\xbf\x69\x02":
        unresolved.append("register-domain-allocator-signed-payload-shape-differs")
        return ()
    payload_bits = 16
    virtual_max = (1 << (payload_bits - 1)) - 1
    physical_max = virtual_min - 1
    if virtual_min <= 0 or physical_max >= virtual_max:
        unresolved.append("register-domain-decoded-boundary-is-invalid")
        return ()

    for form, raw_kind, class_id, virtual_kind, init, driver in class_shapes:
        stage_states = (
            ("allocator_input", "physical", 0, physical_max),
            ("allocator_input", "virtual", virtual_min, virtual_max),
            ("mutation_output", "physical", 0, physical_max),
            ("mutation_output", "virtual", virtual_min, virtual_max),
            ("code_emission", "physical", 0, physical_max),
        )
        for stage, state, value_min, value_max in stage_states:
            result.append(
                RegisterDomain(
                    raw_arg_kind_id=raw_kind,
                    register_form=form,
                    class_id=class_id,
                    virtual_kind=virtual_kind,
                    capture_stage=stage,
                    allocation_state=state,
                    value_min=value_min,
                    value_max=value_max,
                    raw_payload_unsigned=True,
                    evidence_addresses=(
                        init,
                        driver,
                        ALLOCATOR_REWRITE_PAYLOAD_WRITE,
                        FINAL_ENCODER,
                    ),
                    evidence=(
                        "decoded class counter initialization partitions physical "
                        "and virtual payloads; allocator reads virtual IDs as signed "
                        "16-bit and rewrites the exact unsigned 16-bit payload"
                    ),
                )
            )
    special_constants = tuple(
        struct.unpack("<H", image.read(address + 7, 2))[0]
        for address in (0x004A2AE0, 0x004A2A93, 0x004A2AA4)
    )
    if special_constants != (0, 1, 2):
        unresolved.append("special-register-fixed-domain-differs")
        return ()
    cr_loop_compare = image.read(0x004A2B00, 5)
    if cr_loop_compare[:1] != b"\x3d":
        unresolved.append("condition-register-domain-shape-differs")
        return ()
    cr_max = struct.unpack("<I", cr_loop_compare[1:])[0]
    for form, raw_kind, maximum, evidence_addresses in (
        ("special", 2, max(special_constants), (0x004A2A93, 0x004A2AA4, 0x004A2AE0)),
        ("cr", 3, cr_max, (0x004A2AF0, 0x004A2B00)),
    ):
        for stage in ("allocator_input", "mutation_output", "code_emission"):
            result.append(
                RegisterDomain(
                    raw_arg_kind_id=raw_kind,
                    register_form=form,
                    class_id=None,
                    virtual_kind=None,
                    capture_stage=stage,
                    allocation_state="non-allocator",
                    value_min=0,
                    value_max=maximum,
                    raw_payload_unsigned=True,
                    evidence_addresses=(*evidence_addresses, FINAL_ENCODER),
                    evidence=(
                        "decoded fixed special/condition constructor payloads; "
                        "not rewritten by allocator classes 0, 1, or 9"
                    ),
                )
            )
    return tuple(result)


def _finite_values(value: object) -> frozenset[int] | None:
    kind = getattr(value, "kind", None)
    values = getattr(value, "values", None)
    if kind not in {"exact", "finite", "null"} or not isinstance(
        values, (set, frozenset)
    ):
        return None
    if not all(type(item) is int for item in values):
        return None
    return frozenset(values)


def _call_argument(call: object, index: int) -> object | None:
    arguments = getattr(call, "arguments", ())
    return arguments[index] if index < len(arguments) else None


def _resolve_argument_domain(
    value: object,
    function_entry: int,
    argument_index: int,
    calls: tuple[object, ...],
    active: frozenset[int] = frozenset(),
) -> frozenset[int] | None:
    finite = _finite_values(value)
    if finite is not None:
        return finite
    if (
        getattr(value, "kind", None) != "argument"
        or getattr(value, "affine_symbol", f"arg{argument_index}")
        != f"arg{argument_index}"
        or function_entry in active
    ):
        return None
    callers = tuple(
        call for call in calls if getattr(call, "target", None) == function_entry
    )
    if not callers:
        return None
    result: set[int] = set()
    for caller in callers:
        resolved = _resolve_argument_domain(
            _call_argument(caller, argument_index),
            getattr(caller, "function_entry", -1),
            argument_index,
            calls,
            active | {function_entry},
        )
        if resolved is None:
            return None
        result.update(resolved)
    return frozenset(result)


def _pseudo_op_closure(
    cfg: RawCfg, values: object | None, unresolved: list[str]
) -> bool:
    if values is None:
        unresolved.append("pseudo-op-final-list-closure-unproved")
        return False
    if getattr(values, "compiler_sha256", None) != RETAIL_GC125N_SHA256:
        unresolved.append("pseudo-op-values-compiler-differs")
        return False
    if not getattr(values, "proof_ready", False) or getattr(values, "unresolved", ()):
        unresolved.append("pseudo-op-value-closure-unresolved")
        return False

    calls = tuple(getattr(values, "calls", ()))
    for wrapper in (0x004A25D0, 0x004A2620):
        wrapper_calls = tuple(
            call for call in calls if getattr(call, "target", None) == wrapper
        )
        if not wrapper_calls:
            unresolved.append(
                f"pseudo-op-constructor-call-inventory-empty:{wrapper:#x}"
            )
            return False
        for call in wrapper_calls:
            domain = _resolve_argument_domain(
                _call_argument(call, 0),
                getattr(call, "function_entry", -1),
                0,
                calls,
            )
            if domain is None:
                unresolved.append(
                    f"pseudo-op-constructor-opcode-unresolved:{getattr(call, 'address', -1):#x}"
                )
                return False
            if domain.intersection(PSEUDO_OPCODES):
                unresolved.append(
                    f"pseudo-op-constructor-domain-reaches-pseudo:"
                    f"{getattr(call, 'address', -1):#x}:{sorted(domain)}"
                )
                return False

    pseudo_writes: list[tuple[int, int, int, str]] = []
    for write in getattr(values, "memory_writes", ()):
        finite = _finite_values(getattr(write, "value", None))
        if finite is None or not finite.intersection(PSEUDO_OPCODES):
            continue
        pseudo_writes.append(
            (
                getattr(write, "address", -1),
                getattr(write, "width", -1),
                getattr(write, "offset", -1),
                getattr(getattr(write, "base", None), "pointer_type", ""),
            )
        )
    # The sole exact 466 immediate is an independently reviewed non-PCode
    # structure write.  PEXIT has no executable write.  Any expansion blocks.
    if pseudo_writes != [(0x004AEB14, 2, 0, "")]:
        unresolved.append(
            "pseudo-op-write-inventory-differs:" + repr(tuple(sorted(pseudo_writes)))
        )
        return False

    encoder_calls = tuple(
        sorted(
            call.address
            for call in getattr(cfg, "direct_calls", ())
            if call.target == FINAL_ENCODER
        )
    )
    if encoder_calls != (FINAL_ENCODER_CALL,):
        unresolved.append(
            "pseudo-op-encoder-call-inventory-differs:" + repr(encoder_calls)
        )
        return False
    return True


def analyze_opcode_layouts(
    image: Image,
    cfg: RawCfg,
    values: object | None = None,
    *,
    expected_sha256: str = RETAIL_GC125N_SHA256,
) -> OpcodeLayoutInventory:
    """Return the exact 468-row opcode/layout inventory or fail closed."""

    unresolved: list[str] = []
    if image.sha256 != expected_sha256:
        unresolved.append(f"compiler-sha256:{image.sha256}:expected:{expected_sha256}")
    if image.sha256 != RETAIL_GC125N_SHA256:
        unresolved.append(
            f"retail-compiler-sha256:{image.sha256}:"
            f"expected:{RETAIL_GC125N_SHA256}"
        )
    if expected_sha256 != RETAIL_GC125N_SHA256:
        unresolved.append(
            f"audit-expected-sha256:{expected_sha256}:"
            f"required:{RETAIL_GC125N_SHA256}"
        )
    _validate_binary_windows(image, unresolved)
    _validate_format_dispatch(image, unresolved)
    _validate_cfg_evidence(image, cfg, unresolved)

    raw_table = image.read(
        OPCODE_METADATA_TABLE, OPCODE_COUNT * OPCODE_METADATA_ROW_SIZE
    )
    metadata_sha256 = hashlib.sha256(raw_table).hexdigest()
    if metadata_sha256 != _EXPECTED_METADATA_SHA256:
        unresolved.append(f"opcode-metadata-evidence-altered:{metadata_sha256}")

    rows: list[OpcodeMetadataRow] = []
    mnemonics: set[str] = set()
    for opcode_id in range(OPCODE_COUNT):
        entry_address = OPCODE_METADATA_TABLE + opcode_id * OPCODE_METADATA_ROW_SIZE
        raw = raw_table[
            opcode_id * OPCODE_METADATA_ROW_SIZE : (opcode_id + 1)
            * OPCODE_METADATA_ROW_SIZE
        ]
        mnemonic_pointer, format_pointer, flags, encoding = struct.unpack("<IIII", raw)
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
            expected_format = "=r,t" if opcode_id == 199 else "?"
            if format_string != expected_format:
                unresolved.append(f"custom-format-differs:{opcode_id}:{format_string}")
            descriptors = _custom_descriptors(opcode_id)
            if flags & 0xFF != len(descriptors):
                unresolved.append(
                    f"custom-operand-count-differs:{opcode_id}:"
                    f"{flags & 0xFF}:expected:{len(descriptors)}"
                )
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
                if opcode_id in {1, 20}:
                    descriptors += _call_tail_descriptors(
                        opcode_id, len(descriptors)
                    )

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
    if len(mnemonics) != OPCODE_COUNT:
        unresolved.append("opcode-mnemonic-domain-has-gap-or-duplicate")

    custom = _custom_evidence(cfg)
    for evidence in custom:
        if len(evidence.addresses) != len(evidence.instruction_bytes_hex) or any(
            not row for row in evidence.instruction_bytes_hex
        ):
            unresolved.append(f"custom-layout-evidence-incomplete:{evidence.opcode_id}")

    pseudo_closed = _pseudo_op_closure(cfg, values, unresolved)
    pseudo = tuple(
        PseudoOpcodeEvidence(
            opcode_id=opcode_id,
            mnemonic=rows[opcode_id].mnemonic,
            encoding=rows[opcode_id].encoding,
            maximum_encodable_opcode=465,
            final_disposition=(
                "eliminated-before-encoder"
                if pseudo_closed
                else "final-disposition-unproved"
            ),
            evidence_addresses=(0x004A35B8, FINAL_ENCODER_CALL),
        )
        for opcode_id in sorted(PSEUDO_OPCODES)
    )
    for row in pseudo:
        if row.encoding != 0:
            unresolved.append(f"pseudo-op-encoding-nonzero:{row.opcode_id}")

    variadic_sources = _variadic_sources(rows, values, unresolved)
    generic_sha256 = _sha256(image, GENERIC_CONSTRUCTOR, GENERIC_CONSTRUCTOR_END)
    return OpcodeLayoutInventory(
        compiler_sha256=image.sha256,
        metadata_sha256=metadata_sha256,
        generic_constructor_sha256=generic_sha256,
        opcode_rows=tuple(rows),
        custom_constructors=custom,
        variadic_sources=variadic_sources,
        register_domains=_register_domains(image, unresolved),
        raw_pcode_arg_layout=RawPCodeArgLayout(
            size=12,
            kind_offset=0,
            kind_width=1,
            flags_offset=1,
            flags_width=1,
            payload_offset=2,
            payload_width=2,
            payload_signed=False,
            allocator_rewrite_address=ALLOCATOR_REWRITE_PAYLOAD_WRITE,
            allocator_rewritten_fields=("payload",),
            allocator_preserved_fields=("kind", "flags"),
            evidence_addresses=(
                0x004A26C6,
                0x004A274A,
                0x004A274D,
                0x004A2751,
                ALLOCATOR_REWRITE_PAYLOAD_WRITE,
            ),
        ),
        pseudo_opcodes=pseudo,
        unresolved=tuple(sorted(set(unresolved))),
        proof_ready=not unresolved,
    )


_ROLE_FLAG = {"use": 1, "def": 2, "use-def": 3}
_STAGE_ORDER = {"allocator_input": 0, "mutation_output": 1, "code_emission": 2}
_STATE_ORDER = {"virtual": 0, "physical": 1, "non-allocator": 2}


def _descriptor_flags(descriptor: OperandLayoutDescriptor) -> tuple[int, ...]:
    if descriptor.role is not None:
        result = {_ROLE_FLAG[descriptor.role]}
    else:
        result = {row.register_flags_value for row in descriptor.role_rules}
    if descriptor.descriptor_source == "format" and descriptor.format_code == "b":
        result.add(0)
    return tuple(sorted(result))


def build_opcode_proof_tables(
    inventory: OpcodeLayoutInventory,
) -> OpcodeProofTables:
    """Build canonical proof rows only from one closed exact inventory."""

    if not inventory.proof_ready or inventory.unresolved:
        raise ValueError("opcode layout inventory is not proof-ready")
    if (
        inventory.compiler_sha256 != RETAIL_GC125N_SHA256
        or inventory.metadata_sha256 != _EXPECTED_METADATA_SHA256
        or inventory.generic_constructor_sha256
        != _EXPECTED_GENERIC_CONSTRUCTOR_SHA256
    ):
        raise ValueError("opcode layout inventory lacks exact retail evidence")
    if tuple(row.opcode_id for row in inventory.opcode_rows) != tuple(
        range(OPCODE_COUNT)
    ):
        raise ValueError("opcode layout inventory is incomplete")
    custom = {row.opcode_id: row for row in inventory.custom_constructors}
    variadic = {row.opcode_id: row for row in inventory.variadic_sources}

    opcode_rows: list[dict[str, Any]] = []
    operand_rows: list[dict[str, Any]] = []
    for row in inventory.opcode_rows:
        variadic_layout: dict[str, Any] | None = None
        if row.constructor_kind == "generic-variadic":
            source = variadic.get(row.opcode_id)
            if source is None or source.tail_expansion == "post-constructor-unproved":
                raise ValueError(
                    f"opcode {row.opcode_id} variadic evidence is incomplete"
                )
            variadic_layout = {
                "count_source": source.source,
                "count_width": source.count_width,
                "constructor_count_min": source.constructor_count_min,
                "constructor_count_max": source.constructor_count_max,
                "base_operand_count": source.base_operand_count,
                "count_arithmetic": source.count_arithmetic,
                "tail_expansion": source.tail_expansion,
                "reachability": source.reachability,
                "reachable_count_min": source.reachable_count_min,
                "reachable_count_max": source.reachable_count_max,
                "call_addresses": list(source.call_addresses),
                "evidence_addresses": list(source.bound_evidence),
            }
        addresses = (
            list(custom[row.opcode_id].addresses)
            if row.constructor_kind == "custom"
            else []
        )
        opcode_rows.append(
            {
                "opcode_id": row.opcode_id,
                "mnemonic": row.mnemonic,
                "format_string": row.format_string,
                "constructor_kind": row.constructor_kind,
                "custom_constructor_addresses": addresses,
                "variadic_layout": variadic_layout,
            }
        )

        for descriptor in row.operand_descriptors:
            domains = [
                domain
                for domain in inventory.register_domains
                if domain.raw_arg_kind_id == descriptor.raw_arg_kind_id
                and domain.register_form == descriptor.register_form
                and domain.class_id == descriptor.class_id
                and domain.virtual_kind == descriptor.virtual_kind
            ]
            if descriptor.register_form == "memory" or descriptor.register_form in {
                "immediate",
                "branch-target",
                "opaque",
            }:
                register_form = "none"
                domains = []
            else:
                register_form = descriptor.register_form
            if register_form != "none" and not domains:
                raise ValueError(
                    f"opcode {row.opcode_id} descriptor {descriptor.operand_index} "
                    "has no exact register domain"
                )
            state_rules = [
                {
                    "capture_stage": domain.capture_stage,
                    "register_flags_mask": 0xFF,
                    "register_flags_value": flags,
                    "register_value_min": domain.value_min,
                    "register_value_max": domain.value_max,
                    "allocation_state": domain.allocation_state,
                }
                for domain in domains
                for flags in _descriptor_flags(descriptor)
            ]
            state_rules.sort(
                key=lambda rule: (
                    _STAGE_ORDER[rule["capture_stage"]],
                    rule["register_flags_mask"],
                    rule["register_flags_value"],
                    rule["register_value_min"],
                    rule["register_value_max"],
                    _STATE_ORDER[rule["allocation_state"]],
                )
            )
            operand_rows.append(
                {
                    "opcode_id": row.opcode_id,
                    "descriptor_index": descriptor.operand_index,
                    "descriptor_source": descriptor.descriptor_source,
                    "format_code": descriptor.format_code,
                    "expansion": {
                        "kind": descriptor.expansion_kind,
                        "count": descriptor.expansion_count,
                    },
                    "raw_arg_kind_id": descriptor.raw_arg_kind_id,
                    "role": descriptor.role,
                    "role_rules": [asdict(rule) for rule in descriptor.role_rules],
                    "register_form": register_form,
                    "class_id": descriptor.class_id,
                    "virtual_kind": descriptor.virtual_kind,
                    "state_rules": state_rules,
                }
            )
    return OpcodeProofTables(tuple(opcode_rows), tuple(operand_rows))
