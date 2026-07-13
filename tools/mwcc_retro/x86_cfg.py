"""Deterministic seed discovery and direct PE32 x86 CFG recovery."""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import re
import struct
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import capstone
from capstone import (
    CS_AC_READ,
    CS_AC_WRITE,
    CS_ARCH_X86,
    CS_GRP_CALL,
    CS_GRP_IRET,
    CS_GRP_JUMP,
    CS_GRP_RET,
    CS_MODE_32,
    Cs,
)
from capstone import x86_const
from capstone.x86 import (
    X86_INS_LCALL,
    X86_INS_LEA,
    X86_INS_JMP,
    X86_INS_LJMP,
    X86_INS_MOV,
    X86_INS_ENTER,
    X86_OP_IMM,
    X86_OP_MEM,
    X86_OP_REG,
    X86_REG_INVALID,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from tools.mwcc_retro.pe import Image


class CfgRecoveryError(ValueError):
    """Raised when evidence cannot safely seed x86 CFG recovery."""


class AnalysisLimitError(CfgRecoveryError):
    """Raised when a deterministic analysis cap reaches its limit."""

    def __init__(
        self, limit_name: str, configured: int, observed: int
    ) -> None:
        self.limit_name = limit_name
        self.configured = configured
        self.observed = observed
        super().__init__(
            f"analysis limit reached: {limit_name}, "
            f"configured={configured}, observed={observed}"
        )


@dataclass(frozen=True, slots=True)
class AnalysisLimits:
    """Explicit structural and fixed-point limits for x86 analysis."""

    max_instructions: int
    max_blocks: int
    max_edges: int
    max_jump_tables: int = 65_536
    max_jump_table_entries: int = 524_288
    max_functions: int = 65_536
    max_finite_targets: int = 65_536
    max_finite_values: int = 8_192
    max_states_per_block: int = 256
    max_contexts_per_entry: int = 256
    max_scc_iterations: int = 65_536
    max_summary_iterations: int = 65_536
    max_fixpoint_updates: int = 8_000_000

    @classmethod
    def for_image(cls, image: Image) -> AnalysisLimits:
        executable_raw_bytes = sum(
            section.raw_size
            for section in image.sections
            if section.is_executable
        )
        return cls(
            max_instructions=executable_raw_bytes,
            max_blocks=executable_raw_bytes,
            max_edges=8 * executable_raw_bytes,
        )

    def check(self, limit_name: str, observed: int) -> None:
        """Fail when ``observed`` reaches the configured high-water cap."""
        if limit_name not in self.__dataclass_fields__:
            raise ValueError(f"unknown analysis limit: {limit_name}")
        configured = getattr(self, limit_name)
        if observed >= configured:
            raise AnalysisLimitError(limit_name, configured, observed)


@dataclass(frozen=True, slots=True)
class AuditAnchor:
    """Closed audit seed bound to exact instruction bytes and their digest."""

    name: str
    address: int
    instruction_bytes: bytes
    evidence: str
    instruction_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("audit anchor name must not be empty")
        if self.address < 0:
            raise ValueError("audit anchor address must not be negative")
        if not isinstance(self.instruction_bytes, bytes):
            raise TypeError("audit anchor instruction_bytes must be bytes")
        if not self.instruction_bytes:
            raise ValueError("audit anchor instruction_bytes must not be empty")
        if not self.evidence:
            raise ValueError("audit anchor evidence must not be empty")
        object.__setattr__(
            self,
            "instruction_sha256",
            hashlib.sha256(self.instruction_bytes).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class SeedRecord:
    """One independently proven executable CFG seed."""

    address: int
    category: str
    provenance_address: int
    provenance_bytes: str
    detail: str


def _seed_key(record: SeedRecord) -> tuple[int, str, int, str, str]:
    return (
        record.address,
        record.category,
        record.provenance_address,
        record.detail,
        record.provenance_bytes,
    )


@dataclass(frozen=True, slots=True)
class SeedInventory:
    """Canonical immutable inventory of independently proven CFG seeds."""

    records: tuple[SeedRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "records",
            tuple(sorted(set(self.records), key=_seed_key)),
        )

    @property
    def addresses(self) -> tuple[int, ...]:
        return tuple(sorted({record.address for record in self.records}))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Instruction:
    address: int
    size: int
    bytes_hex: str
    mnemonic: str
    operands: str


@dataclass(frozen=True, slots=True)
class BasicBlock:
    start: int
    end: int
    instruction_addresses: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CfgEdge:
    source: int
    target: int
    kind: str


@dataclass(frozen=True, slots=True)
class DirectCall:
    address: int
    target: int


@dataclass(frozen=True, slots=True)
class RawE8Candidate:
    address: int
    target: int
    classification: str


@dataclass(frozen=True, slots=True)
class ByteRegion:
    start: int
    end: int
    provenance: str


@dataclass(frozen=True, slots=True)
class OwnershipDiagnostic:
    kind: str
    address: int
    detail: str


@dataclass(frozen=True, slots=True)
class JumpTable:
    """One finite computed-transfer table proven from a dominating guard."""

    address: int
    flow_kind: str
    guard_address: int
    guard_operator: str
    guard_bound: int
    base: int
    entry_width: int
    index_min: int
    index_max: int
    raw_entries: tuple[int, ...]
    targets: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class AnalysisHighWater:
    limit_name: str
    observed: int


@dataclass(frozen=True, slots=True)
class RawCfg:
    """Immutable public shape produced by direct CFG recovery."""

    seed_inventory: SeedInventory
    instructions: tuple[Instruction, ...]
    blocks: tuple[BasicBlock, ...]
    edges: tuple[CfgEdge, ...]
    direct_calls: tuple[DirectCall, ...]
    jump_tables: tuple[JumpTable, ...]
    raw_e8_candidates: tuple[RawE8Candidate, ...]
    data_regions: tuple[ByteRegion, ...]
    padding_regions: tuple[ByteRegion, ...]
    ownership_diagnostics: tuple[OwnershipDiagnostic, ...]
    limits: AnalysisLimits
    high_water_marks: tuple[AnalysisHighWater, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def jump_table_at(self, address: int) -> JumpTable:
        """Return the uniquely recovered table at a computed transfer."""
        matches = tuple(row for row in self.jump_tables if row.address == address)
        if len(matches) != 1:
            raise KeyError(f"no unique jump table at {address:#x}")
        return matches[0]


def _is_executable_span(image: Image, address: int, size: int) -> bool:
    end = address + size
    return any(
        start <= address and end <= range_end
        for start, range_end in image.executable_ranges
    )


def _is_mapped_span(image: Image, address: int, size: int) -> bool:
    end = address + size
    if image.image_base <= address and end <= image.image_base + image.size_of_headers:
        return True
    return any(
        section.va <= address and end <= section.va + section.mapped_size
        for section in image.sections
    )


def _read_provenance(image: Image, address: int, size: int, label: str) -> bytes:
    try:
        return image.read(address, size)
    except ValueError as exc:
        raise CfgRecoveryError(
            f"{label} provenance is not wholly mapped at {address:#x}"
        ) from exc


def _executable_seed_bytes(image: Image, address: int, label: str) -> bytes:
    if not _is_executable_span(image, address, 1):
        raise CfgRecoveryError(f"{label} is not executable: {address:#x}")
    return _read_provenance(image, address, 1, label)


def _initial_seed_records(
    image: Image, audit_anchors: Sequence[AuditAnchor]
) -> Iterable[SeedRecord]:
    if image.entrypoint:
        entry_bytes = _executable_seed_bytes(
            image, image.entrypoint, "PE entry point"
        )
        yield SeedRecord(
            address=image.entrypoint,
            category="entrypoint",
            provenance_address=image.entrypoint,
            provenance_bytes=entry_bytes.hex(),
            detail="pe-address-of-entry-point",
        )

    for export in image.exports:
        if export.va is None:
            raise CfgRecoveryError(
                "forwarded PE export cannot seed direct CFG recovery: "
                f"ordinal={export.ordinal}"
            )
        export_bytes = _executable_seed_bytes(
            image, export.va, f"PE export ordinal {export.ordinal}"
        )
        yield SeedRecord(
            address=export.va,
            category="export",
            provenance_address=export.va,
            provenance_bytes=export_bytes.hex(),
            detail=f"name={export.name or ''};ordinal={export.ordinal}",
        )

    for relocation in image.relocations:
        width = _I386_RELOCATION_WIDTHS.get(relocation.type)
        if width != 4 or relocation.type != 3:
            continue
        if _is_executable_span(image, relocation.va, width):
            continue
        pointer_bytes = _read_provenance(
            image, relocation.va, width, "relocation pointer"
        )
        pointer = struct.unpack("<I", pointer_bytes)[0]
        if not _is_executable_span(image, pointer, 1):
            continue
        yield SeedRecord(
            address=pointer,
            category="relocation-executable-pointer",
            provenance_address=relocation.va,
            provenance_bytes=pointer_bytes.hex(),
            detail=(
                f"i386-relocation-type-{relocation.type};width={width}"
            ),
        )

    for anchor in audit_anchors:
        if not _is_executable_span(
            image, anchor.address, len(anchor.instruction_bytes)
        ):
            raise CfgRecoveryError(
                f"audit anchor is not executable: {anchor.name} "
                f"at {anchor.address:#x}"
            )
        actual = _read_provenance(
            image,
            anchor.address,
            len(anchor.instruction_bytes),
            f"audit anchor {anchor.name}",
        )
        if actual != anchor.instruction_bytes:
            raise CfgRecoveryError(
                f"audit anchor bytes differ: {anchor.name} "
                f"at {anchor.address:#x}"
            )
        actual_sha256 = hashlib.sha256(actual).hexdigest()
        if actual_sha256 != anchor.instruction_sha256:
            raise CfgRecoveryError(
                f"audit anchor digest differs: {anchor.name} "
                f"at {anchor.address:#x}"
            )
        yield SeedRecord(
            address=anchor.address,
            category="audit-anchor",
            provenance_address=anchor.address,
            provenance_bytes=actual.hex(),
            detail=(
                f"name={anchor.name};evidence={anchor.evidence};"
                f"sha256={anchor.instruction_sha256}"
            ),
        )


def build_seed_inventory(
    image: Image, audit_anchors: Sequence[AuditAnchor]
) -> SeedInventory:
    """Build the canonical initial seed universe without decoding x86."""
    return SeedInventory(tuple(_initial_seed_records(image, audit_anchors)))


def _explicit_seed_inventory(
    image: Image, seeds: Sequence[int]
) -> SeedInventory:
    records = []
    for address in sorted(set(seeds)):
        seed_bytes = _executable_seed_bytes(
            image, address, "explicit CFG seed"
        )
        records.append(
            SeedRecord(
                address=address,
                category="explicit-seed",
                provenance_address=address,
                provenance_bytes=seed_bytes.hex(),
                detail="caller-supplied",
            )
        )
    return SeedInventory(tuple(records))


def _instruction_key(instruction: Instruction) -> int:
    return instruction.address


def _block_key(block: BasicBlock) -> int:
    return block.start


def _edge_key(edge: CfgEdge) -> tuple[int, str, int]:
    return edge.source, edge.kind, edge.target


def _call_key(call: DirectCall) -> tuple[int, int]:
    return call.address, call.target


def _diagnostic_key(
    diagnostic: OwnershipDiagnostic,
) -> tuple[int, str, str]:
    return diagnostic.address, diagnostic.kind, diagnostic.detail


def _jump_table_key(table: JumpTable) -> int:
    return table.address


@dataclass(frozen=True, slots=True)
class _ExactValue:
    value: int
    chain: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _DataEvidence:
    start: int
    end: int
    provenance: str


@dataclass(frozen=True, slots=True)
class _RelocationEntryCandidate:
    relocation_va: int
    category: str
    entry: int
    gap_start: int
    evidence_address: int
    evidence_bytes: str
    boundary_evidence: str
    span_end: int
    internal_branch_targets: tuple[int, ...] = ()


def _relocation_candidate_key(
    candidate: _RelocationEntryCandidate,
) -> tuple[int, int, int, int, int, str, int, str, str, tuple[int, ...]]:
    return (
        candidate.relocation_va,
        candidate.entry,
        candidate.gap_start,
        candidate.span_end,
        {
            "relocation-computed-transfer": 0,
            "relocation-inline-data-successor": 1,
        }.get(candidate.category, 2),
        candidate.category,
        candidate.evidence_address,
        candidate.evidence_bytes,
        candidate.boundary_evidence,
        candidate.internal_branch_targets,
    )


def _select_relocation_entry_candidates(
    candidates: tuple[_RelocationEntryCandidate, ...],
) -> tuple[_RelocationEntryCandidate, ...]:
    """Choose the unique non-overlapping relocation-entry assignment."""
    canonical_by_shape: dict[
        tuple[int, int, int, int], _RelocationEntryCandidate
    ] = {}
    for candidate in sorted(candidates, key=_relocation_candidate_key):
        shape = (
            candidate.relocation_va,
            candidate.entry,
            candidate.gap_start,
            candidate.span_end,
        )
        canonical_by_shape.setdefault(shape, candidate)

    canonical_candidates = tuple(canonical_by_shape.values())
    dominated_internal_entries = {
        candidate
        for candidate in canonical_candidates
        if any(
            other.relocation_va == candidate.relocation_va
            and other.entry < candidate.entry
            and candidate.entry in other.internal_branch_targets
            and candidate.span_end <= other.span_end
            for other in canonical_candidates
        )
    }
    grouped: dict[int, list[_RelocationEntryCandidate]] = {}
    for candidate in canonical_candidates:
        if candidate in dominated_internal_entries:
            continue
        grouped.setdefault(candidate.relocation_va, []).append(candidate)
    groups = tuple(
        (relocation_va, tuple(sorted(rows, key=_relocation_candidate_key)))
        for relocation_va, rows in sorted(grouped.items())
    )
    if not groups:
        return ()

    solutions: list[tuple[_RelocationEntryCandidate, ...]] = []

    def compatible(
        candidate: _RelocationEntryCandidate,
        selected: tuple[_RelocationEntryCandidate, ...],
    ) -> bool:
        return all(
            candidate.entry == other.entry
            or candidate.span_end <= other.gap_start
            or other.span_end <= candidate.gap_start
            for other in selected
        )

    def visit(
        index: int, selected: tuple[_RelocationEntryCandidate, ...]
    ) -> None:
        if len(solutions) > 1:
            return
        if index == len(groups):
            solutions.append(selected)
            return
        for candidate in groups[index][1]:
            if compatible(candidate, selected):
                visit(index + 1, (*selected, candidate))

    visit(0, ())
    if not solutions:
        relocations = ",".join(f"{row[0]:#x}" for row in groups)
        raise CfgRecoveryError(
            "relocation entry candidates have an overlap conflict: "
            f"relocations={relocations}"
        )
    signatures = {
        tuple(
            (row.relocation_va, row.entry, row.gap_start, row.span_end)
            for row in solution
        )
        for solution in solutions
    }
    if len(signatures) != 1:
        relocations = ",".join(f"{row[0]:#x}" for row in groups)
        raise CfgRecoveryError(
            "relocation entry candidate set is ambiguous: "
            f"relocations={relocations}"
        )
    return tuple(sorted(solutions[0], key=_relocation_candidate_key))


@dataclass(frozen=True, slots=True)
class _RegisterSlice:
    family: str
    mask: int
    name: str


@dataclass(frozen=True, slots=True)
class _ValueDependency:
    kind: str
    register: _RegisterSlice | None = None
    value: int | None = None
    operand_index: int | None = None


@dataclass(frozen=True, slots=True)
class _RegisterEffect:
    destination: _RegisterSlice
    dependencies: tuple[_ValueDependency, ...]
    taint_mask: int | None = None


@dataclass(frozen=True, slots=True)
class _X87State:
    """Finite physical x87/MMX payload, TOP, and tag abstraction."""

    phys_taint: tuple[int, int, int, int, int, int, int, int]
    top_mask: int
    valid_must: int
    valid_may: int

    def __post_init__(self) -> None:
        if len(self.phys_taint) != 8:
            raise ValueError("x87 physical state must contain eight slots")
        if not 0 < self.top_mask <= 0xFF:
            raise ValueError("x87 TOP mask must contain one to eight values")
        if self.valid_must & ~self.valid_may:
            raise ValueError("x87 must-valid tags exceed may-valid tags")
        if (self.valid_must | self.valid_may) & ~0xFF:
            raise ValueError("x87 tag masks exceed eight physical slots")
        if any(mask < 0 or mask >> 80 for mask in self.phys_taint):
            raise ValueError("x87 physical taint exceeds 80-bit payload")

    @classmethod
    def clean_unknown(cls) -> _X87State:
        return cls((0,) * 8, 0xFF, 0, 0xFF)


@dataclass(slots=True)
class _TaintState:
    registers: dict[str, int]
    x87: _X87State

    @classmethod
    def empty(cls) -> _TaintState:
        return cls({}, _X87State((0,) * 8, 1, 0, 0xFF))


@dataclass(frozen=True, slots=True)
class _X87Effect:
    kind: str
    target: int = 0
    pop_count: int = 0
    dependencies: tuple[_ValueDependency, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryWriteSpec:
    """One audited memory sink and the values actually stored by it."""

    classification: str
    dependencies: tuple[_ValueDependency, ...]


@dataclass(frozen=True, slots=True)
class _InstructionValueFlow:
    register_effects: tuple[_RegisterEffect, ...] = ()
    memory_writes: tuple[MemoryWriteSpec, ...] = ()
    join_overlapping_register_effects: bool = False
    taint_blocker_dependencies: tuple[_ValueDependency, ...] = ()
    taint_blocker_reason: str | None = None
    x87_effect: _X87Effect | None = None


_I386_RELOCATION_WIDTHS = {1: 2, 2: 2, 3: 4, 4: 2}
_AUDITED_CAPSTONE_VERSION = "5.0.7"
_AUDITED_X86_INS_ENDING = 1524
_AUDITED_X86_ENUM_COUNT = 1525
_AUDITED_X86_ENUM_SHA256 = (
    "1f5c37794e44d07e6fa47775c27d1b2418876ceadb08090eb75421f33d5e36b0"
)
_CALL_CLOBBERED_REGISTER_NAMES = ("eax", "ecx", "edx")
_MMX_PAYLOAD_MASK = (1 << 64) - 1
_X87_PHYSICAL_PAYLOAD_MASK = (1 << 80) - 1
_XMM_PAYLOAD_MASK = (1 << 128) - 1
_LEGACY_X86_PREFIXES = frozenset(
    {
        0x26,
        0x2E,
        0x36,
        0x3E,
        0x64,
        0x65,
        0x66,
        0x67,
        0x9B,
        0xF0,
        0xF2,
        0xF3,
    }
)

# Capstone 5.0.7 reports these operand-0 memory destinations as reads.  The
# audit contract above makes this metadata correction table fail closed when
# the decoder schema changes.
_MEMORY_DESTINATION_ACCESS_OVERRIDES = frozenset(
    {
        30,
        167,
        377,
        378,
        380,
        407,
        471,
        472,
        474,
        475,
        479,
        480,
        481,
        482,
        494,
        495,
        534,
        535,
        536,
        804,
        805,
        816,
        861,
        866,
        871,
        1005,
        1006,
        1021,
        1022,
        1023,
        1025,
        1026,
        1027,
        1028,
        1029,
        1030,
        1031,
        1032,
        1033,
        1035,
        1036,
        1038,
        1039,
        1043,
        1044,
        1045,
        1046,
        1049,
        1050,
        1051,
        1135,
        1136,
        1178,
        1179,
        1180,
        1181,
        1230,
        1231,
        1317,
        1318,
        1319,
        1320,
        1439,
        1440,
        1449,
        1450,
    }
)
_MASKMOV_IMPLICIT_WRITERS = frozenset({359, 376, 1004})
_MASKED_EXPLICIT_WRITERS = frozenset({1005, 1006, 1230, 1231})
_LOW_LANE_WRITERS = frozenset({377, 378, 1021, 1025})
_HIGH_HALF_WRITERS = frozenset({471, 472, 1035, 1036})
_SCALAR_EXTRACT_WIDTHS = {
    167: 32,
    407: 16,
    534: 8,
    535: 32,
    536: 64,
    871: 32,
    1178: 8,
    1179: 32,
    1180: 64,
    1181: 16,
}
_VECTOR_EXTRACT_WIDTHS = {861: 128, 866: 128}
_SCATTER_WRITERS = frozenset(
    {1317, 1318, 1319, 1320, 1439, 1440, 1449, 1450}
)
_CET_MEMORY_WRITERS = frozenset({1485, 1486, 1487, 1488})
_FNSAVE_WRITERS = frozenset({204})
_FXSAVE_WRITERS = frozenset({212, 213})
_XSAVE_WRITERS = frozenset(
    {1511, 1512, 1513, 1514, 1515, 1516, 1517, 1518}
)
_CMPXCHG_INSTRUCTIONS = frozenset({113, 114, 115})
_XCHG_INSTRUCTIONS = frozenset({1493})
_XADD_INSTRUCTIONS = frozenset({1491})
_CMOV_INSTRUCTIONS = frozenset(range(80, 105))
_MOVS_INSTRUCTIONS = frozenset({485, 486, 491})
_STOS_INSTRUCTIONS = frozenset({708, 709, 711})
_LODS_INSTRUCTIONS = frozenset({344, 345, 347})
_INS_INSTRUCTIONS = frozenset({233, 236, 237})
_OUTS_INSTRUCTIONS = frozenset({516, 517, 518})
_POPF_INSTRUCTIONS = frozenset({589, 590, 591})
_PUSH_INSTRUCTIONS = frozenset({609})
_PUSHA_INSTRUCTIONS = frozenset({610, 611})
_PUSHF_INSTRUCTIONS = frozenset({612, 613, 614})
_X87_VALUE_WRITERS = frozenset({174, 251, 252, 253, 713, 714})
_X87_POP_VALUE_WRITERS = frozenset({174, 251, 253, 714})
_X87_CONSTANT_LOADS = frozenset({187, 188, 189, 190, 191, 329, 330})
_X87_MEMORY_LOADS = frozenset({173, 227})
_X87_BINARY_ARITHMETIC_MNEMONICS = frozenset(
    {
        "fadd",
        "faddp",
        "fdiv",
        "fdivp",
        "fdivr",
        "fdivrp",
        "fiadd",
        "fidiv",
        "fidivr",
        "fimul",
        "fisub",
        "fisubr",
        "fmul",
        "fmulp",
        "fsub",
        "fsubp",
        "fsubr",
        "fsubrp",
    }
)
_X87_COMPARISON_POP_COUNTS = {
    "fcomp": 1,
    "fcomip": 1,
    "fcompp": 2,
    "fucomp": 1,
    "fucomip": 1,
    "fucompp": 2,
}
_X87_NON_STACK_MNEMONICS = frozenset(
    {
        "fclex",
        "fdisi",
        "feni",
        "fnclex",
        "fndisi",
        "fneni",
        "fnop",
        "fnstcw",
        "fnstenv",
        "fnstsw",
        "fstcw",
        "fstenv",
        "fstsw",
    }
)
_X87_CONTROL_WRITERS = {
    195: "fpcw",  # FNSTCW
    196: "fpsw",  # FNSTSW memory form
    707: "mxcsr",  # STMXCSR
}
_NO_TRACKED_PAYLOAD_MEMORY_WRITERS = frozenset(
    {
        # External/constant/engine memory payloads.
        78,  # CLZERO
        233,
        236,
        237,  # INS*
        466,  # MOVDIR64B
        1522,  # XSTORE
        # VIA PadLock and virtualization state.
        459,  # MONTMUL
        1058,  # VMSAVE
        1495,
        1496,
        1497,
        1498,
        1499,
        1520,
        1521,
        # Descriptor, x87 environment, and architectural state saves.
        208,  # FNSTENV
        675,  # SGDT
        691,  # SIDT
    }
)
_NON_WRITER_EXCLUSIONS = frozenset(
    {
        # Scatter prefetch hints do not architecturally store payload.
        1441,
        1442,
        1443,
        1444,
        1445,
        1446,
        1447,
        1448,
    }
)
_CANONICAL_NOP_ENCODINGS = tuple(
    sorted(
        (
            bytes.fromhex("90"),
            bytes.fromhex("66 90"),
            bytes.fromhex("89 c0"),
            bytes.fromhex("8d 40 00"),
            bytes.fromhex("8d 44 20 00"),
            bytes.fromhex("8d 80 00 00 00 00"),
            bytes.fromhex("8d 84 20 00 00 00 00"),
            bytes.fromhex("0f 1f 00"),
            bytes.fromhex("0f 1f 40 00"),
            bytes.fromhex("0f 1f 44 00 00"),
            bytes.fromhex("66 0f 1f 44 00 00"),
            bytes.fromhex("0f 1f 80 00 00 00 00"),
            bytes.fromhex("0f 1f 84 00 00 00 00 00"),
            bytes.fromhex("66 0f 1f 84 00 00 00 00 00"),
        ),
        key=len,
        reverse=True,
    )
)


def _validate_capstone_audit_contract() -> None:
    enum_rows = sorted(
        (name, value)
        for name, value in vars(x86_const).items()
        if name.startswith("X86_INS_") and isinstance(value, int)
    )
    enum_digest = hashlib.sha256(
        "\n".join(f"{name}={value}" for name, value in enum_rows).encode()
    ).hexdigest()
    observed = (
        capstone.__version__,
        x86_const.X86_INS_ENDING,
        len(enum_rows),
        enum_digest,
    )
    expected = (
        _AUDITED_CAPSTONE_VERSION,
        _AUDITED_X86_INS_ENDING,
        _AUDITED_X86_ENUM_COUNT,
        _AUDITED_X86_ENUM_SHA256,
    )
    if observed != expected:
        raise CfgRecoveryError(
            "Capstone audit contract mismatch: "
            f"observed-version={observed[0]};"
            f"observed-ending={observed[1]};"
            f"observed-enum-count={observed[2]};"
            f"observed-enum-sha256={observed[3]};"
            f"expected-version={expected[0]};"
            f"expected-ending={expected[1]};"
            f"expected-enum-count={expected[2]};"
            f"expected-enum-sha256={expected[3]}"
        )


class _DirectCfgRecovery:
    """Address-priority direct decoder with exact instruction ownership."""

    def __init__(
        self,
        image: Image,
        seed_inventory: SeedInventory,
        limits: AnalysisLimits,
    ) -> None:
        _validate_capstone_audit_contract()
        self.image = image
        self.limits = limits
        self.seed_records = set(seed_inventory.records)
        self.instructions: dict[int, Instruction] = {}
        self.byte_owners: dict[int, int] = {}
        self.block_starts: set[int] = set()
        self.terminators: set[int] = set()
        self.edges: set[CfgEdge] = set()
        self.direct_calls: set[DirectCall] = set()
        self.jump_tables: dict[int, JumpTable] = {}
        self.jump_table_entry_count = 0
        self.indirect_candidates: dict[int, tuple[str, bool]] = {}
        self.diagnostics: set[OwnershipDiagnostic] = set()
        self.data_evidence: set[_DataEvidence] = set()
        self.structural_data_evidence: set[_DataEvidence] = set()
        self.function_addresses: set[int] = set()
        self.finite_targets: set[int] = set()
        self.finite_values: set[int] = set()
        self.produced_initializers: set[tuple[int, int]] = set()
        self.accepted_initializer_instructions: set[int] = set()
        self.fixpoint_updates = 0
        self.high_water = {
            limit_name: 0
            for limit_name in self.limits.__dataclass_fields__
        }
        self.pending: list[int] = []
        self.queued: set[int] = set()

        self.decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        self.decoder.detail = True
        self.decoder.skipdata = False

        for address in seed_inventory.addresses:
            categories = {
                record.category
                for record in seed_inventory.records
                if record.address == address
            }
            self._enqueue(
                address,
                is_function=bool(
                    categories
                    & {
                        "entrypoint",
                        "export",
                        "audit-anchor",
                        "explicit-seed",
                    }
                ),
            )
            self._record_finite_target(address)

    def _check_count(self, limit_name: str, observed: int) -> None:
        self.high_water[limit_name] = max(
            self.high_water[limit_name], observed
        )
        self.limits.check(limit_name, observed)

    def _record_finite_value(self, value: int) -> None:
        if value in self.finite_values:
            return
        self.finite_values.add(value)
        self._check_count("max_finite_values", len(self.finite_values))

    def _record_finite_target(self, address: int) -> None:
        if address in self.finite_targets:
            return
        self.finite_targets.add(address)
        self._check_count("max_finite_targets", len(self.finite_targets))

    def _record_fixpoint_update(self) -> None:
        self.fixpoint_updates += 1
        self._check_count("max_fixpoint_updates", self.fixpoint_updates)

    def _validate_target(self, address: int) -> None:
        if not _is_executable_span(self.image, address, 1):
            raise CfgRecoveryError(
                f"CFG seed or target is not executable: {address:#x}"
            )
        owner = self.byte_owners.get(address)
        if owner is not None and owner != address:
            raise CfgRecoveryError(
                f"CFG seed or target lies in instruction interior: "
                f"{address:#x} is owned by {owner:#x}"
            )

    def _enqueue(self, address: int, *, is_function: bool = False) -> None:
        self._validate_target(address)
        is_new_block_start = address not in self.block_starts
        self.block_starts.add(address)
        if is_new_block_start and address in self.instructions:
            predecessor = next(
                (
                    instruction
                    for instruction in self.instructions.values()
                    if instruction.address + instruction.size == address
                ),
                None,
            )
            if (
                predecessor is not None
                and predecessor.address not in self.terminators
            ):
                self._add_edge(
                    predecessor.address, address, "fallthrough"
                )
        if is_function and address not in self.function_addresses:
            self.function_addresses.add(address)
            self._check_count("max_functions", len(self.function_addresses))
        if address not in self.queued and address not in self.instructions:
            self.queued.add(address)
            heapq.heappush(self.pending, address)

    def _add_edge(self, source: int, target: int, kind: str) -> None:
        edge = CfgEdge(source=source, target=target, kind=kind)
        if edge in self.edges:
            return
        self.edges.add(edge)
        self._check_count("max_edges", len(self.edges))

    def _executable_raw_end(self, address: int) -> int:
        for section in self.image.sections:
            if (
                section.is_executable
                and section.va <= address < section.va + section.raw_size
            ):
                return section.va + section.raw_size
        raise CfgRecoveryError(
            "CFG seed or target is not backed by executable raw bytes: "
            f"{address:#x}"
        )

    def _decode_one(self, address: int):
        executable_raw_end = self._executable_raw_end(address)
        available = min(15, executable_raw_end - address)
        code = _read_provenance(
            self.image, address, available, "x86 instruction"
        )
        decoded = next(self.decoder.disasm(code, address, count=1), None)
        if decoded is None:
            raise CfgRecoveryError(
                f"cannot decode x86 instruction at {address:#x}"
            )
        return decoded

    def _claim_instruction(self, decoded) -> Instruction:
        address = decoded.address
        end = address + decoded.size
        for byte_address in range(address, end):
            owner = self.byte_owners.get(byte_address)
            if owner is not None and owner != address:
                raise CfgRecoveryError(
                    "conflicting decode reaches instruction interior: "
                    f"{address:#x} overlaps {owner:#x} at {byte_address:#x}"
                )
        instruction = Instruction(
            address=address,
            size=decoded.size,
            bytes_hex=bytes(decoded.bytes).hex(),
            mnemonic=decoded.mnemonic,
            operands=decoded.op_str,
        )
        self.instructions[address] = instruction
        for byte_address in range(address, end):
            self.byte_owners[byte_address] = address
        self._check_count("max_instructions", len(self.instructions))
        return instruction

    @staticmethod
    def _direct_target(decoded) -> int | None:
        if (
            decoded.id in {X86_INS_LCALL, X86_INS_LJMP}
            or len(decoded.operands) != 1
            or decoded.operands[0].type != X86_OP_IMM
        ):
            return None
        return decoded.operands[0].imm & 0xFFFF_FFFF

    def _record_direct_target(
        self,
        instruction: Instruction,
        target: int,
        category: str,
    ) -> None:
        self.seed_records.add(
            SeedRecord(
                address=target,
                category=category,
                provenance_address=instruction.address,
                provenance_bytes=instruction.bytes_hex,
                detail=(
                    f"mnemonic={instruction.mnemonic};"
                    f"operands={instruction.operands}"
                ),
            )
        )

    def _previous_instruction(self, address: int) -> Instruction | None:
        return next(
            (
                row
                for row in self.instructions.values()
                if row.address + row.size == address
            ),
            None,
        )

    def _computed_flow_blocker(
        self, instruction: Instruction, detail: str
    ) -> None:
        self.diagnostics.add(
            OwnershipDiagnostic(
                kind="computed-flow-blocker",
                address=instruction.address,
                detail=detail,
            )
        )

    def _resolve_register_constant_before(
        self, address: int, register: int
    ) -> int | None:
        """Resolve a local exact register initializer without crossing a gap."""
        family = self._register_family(register)
        cursor = address
        for _ in range(64):
            previous = self._previous_instruction(cursor)
            if previous is None:
                return None
            decoded = self._owned_decoded(previous.address)
            if decoded.operands and decoded.operands[0].type == X86_OP_REG:
                destination = self._register_family(decoded.operands[0].reg)
                if destination == family:
                    if (
                        decoded.id == X86_INS_MOV
                        and len(decoded.operands) == 2
                        and decoded.operands[0].size == 4
                        and decoded.operands[1].type == X86_OP_IMM
                    ):
                        return decoded.operands[1].imm & 0xFFFF_FFFF
                    if (
                        decoded.id == X86_INS_LEA
                        and len(decoded.operands) == 2
                        and decoded.operands[0].size == 4
                        and decoded.operands[1].type == X86_OP_MEM
                        and decoded.operands[1].mem.base == X86_REG_INVALID
                        and decoded.operands[1].mem.index == X86_REG_INVALID
                    ):
                        return decoded.operands[1].mem.disp & 0xFFFF_FFFF
                    return None
            if any(
                self._register_family(written) == family
                for written in decoded.regs_write
            ):
                return None
            cursor = previous.address
            if previous.address in self.block_starts:
                return None
        return None

    def _guard_for_index(
        self, transfer_address: int, index_register: int
    ) -> tuple[Instruction, str, int, int, int] | None:
        """Return compare, operator, bound, min, max for a fallthrough guard."""
        branch = self._previous_instruction(transfer_address)
        if branch is None:
            return None
        branch_decoded = self._owned_decoded(branch.address)
        operators = {"ja": (0, 0), "jae": (0, -1)}
        adjustment = operators.get(branch_decoded.mnemonic)
        if adjustment is None or not branch_decoded.group(CS_GRP_JUMP):
            return None
        if self._direct_target(branch_decoded) is None:
            return None
        incoming = {
            (edge.source, edge.kind)
            for edge in self.edges
            if edge.target == transfer_address
        }
        if incoming != {(branch.address, "fallthrough")}:
            return None
        compare = self._previous_instruction(branch.address)
        if compare is None:
            return None
        compare_decoded = self._owned_decoded(compare.address)
        if (
            compare_decoded.mnemonic != "cmp"
            or len(compare_decoded.operands) != 2
            or compare_decoded.operands[0].type != X86_OP_REG
            or compare_decoded.operands[0].size != 4
            or compare_decoded.operands[1].type != X86_OP_IMM
            or self._register_family(compare_decoded.operands[0].reg)
            != self._register_family(index_register)
        ):
            return None
        bound = compare_decoded.operands[1].imm & 0xFFFF_FFFF
        index_min = adjustment[0]
        index_max = bound + adjustment[1]
        if index_max < index_min:
            return None
        return compare, branch_decoded.mnemonic, bound, index_min, index_max

    def _recover_indexed_table(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        if len(decoded.operands) != 1 or decoded.operands[0].type != X86_OP_MEM:
            return False
        operand = decoded.operands[0]
        memory = operand.mem
        if memory.index == X86_REG_INVALID:
            return False
        if memory.segment != X86_REG_INVALID:
            self._computed_flow_blocker(
                instruction,
                "jump-table operand uses an unsupported segment override",
            )
            return False

        guard = self._guard_for_index(instruction.address, memory.index)
        if guard is None:
            self._computed_flow_blocker(
                instruction,
                "computed transfer has no finite dominating guard",
            )
            return False
        compare, operator, bound, index_min, index_max = guard
        entry_width = operand.size
        if entry_width != 4 or memory.scale != entry_width:
            self._computed_flow_blocker(
                instruction,
                "jump-table entry width conflicts with index scale: "
                f"width={entry_width};scale={memory.scale}",
            )
            return False
        if memory.base == X86_REG_INVALID:
            base = memory.disp & 0xFFFF_FFFF
        else:
            base_value = self._resolve_register_constant_before(
                compare.address, memory.base
            )
            if base_value is None:
                self._computed_flow_blocker(
                    instruction,
                    "jump-table base has no finite local initializer",
                )
                return False
            base = base_value + memory.disp
            if not 0 <= base <= 0xFFFF_FFFF:
                self._computed_flow_blocker(
                    instruction, "jump-table base address wraps 32 bits"
                )
                return False

        entry_count = index_max - index_min + 1
        last_entry = base + index_max * entry_width
        if not 0 <= base <= last_entry <= 0xFFFF_FFFF - entry_width + 1:
            self._computed_flow_blocker(
                instruction, "jump-table entry range wraps 32 bits"
            )
            return False
        new_total = self.jump_table_entry_count + entry_count
        try:
            self._check_count("max_jump_table_entries", new_total)
        except AnalysisLimitError:
            raise

        entries: list[int] = []
        entry_rows: list[tuple[int, bytes, int]] = []
        for index in range(index_min, index_max + 1):
            entry_address = base + index * entry_width
            try:
                raw = self.image.read(entry_address, entry_width)
            except ValueError:
                self._computed_flow_blocker(
                    instruction,
                    "jump-table entry is not wholly mapped: "
                    f"index={index};address={entry_address:#x}",
                )
                return False
            target = int.from_bytes(raw, "little")
            if not _is_executable_span(self.image, target, 1):
                self._computed_flow_blocker(
                    instruction,
                    "jump-table target is not executable: "
                    f"index={index};entry={entry_address:#x};target={target:#x}",
                )
                return False
            entries.append(target)
            entry_rows.append((entry_address, raw, target))

        table = JumpTable(
            address=instruction.address,
            flow_kind=flow_kind,
            guard_address=compare.address,
            guard_operator=operator,
            guard_bound=bound,
            base=base,
            entry_width=entry_width,
            index_min=index_min,
            index_max=index_max,
            raw_entries=tuple(entries),
            targets=tuple(entries),
        )
        prior = self.jump_tables.get(instruction.address)
        if prior is not None and prior != table:
            raise CfgRecoveryError(
                f"conflicting computed-flow table at {instruction.address:#x}"
            )
        if prior is None:
            self.jump_tables[instruction.address] = table
            self.jump_table_entry_count = new_total
            self._check_count("max_jump_tables", len(self.jump_tables))
            self.data_evidence.add(
                _DataEvidence(
                    start=base + index_min * entry_width,
                    end=base + (index_max + 1) * entry_width,
                    provenance=(
                        f"guard={compare.address:#x};operator={operator};"
                        f"bound={bound};transfer={instruction.address:#x}"
                    ),
                )
            )
            category = (
                "callback-table-entry"
                if flow_kind == "call"
                else "jump-table-entry"
            )
            edge_kind = (
                "indirect-call-table"
                if flow_kind == "call"
                else "indirect-jump-table"
            )
            for entry_address, raw, target in entry_rows:
                self.seed_records.add(
                    SeedRecord(
                        address=target,
                        category=category,
                        provenance_address=entry_address,
                        provenance_bytes=raw.hex(),
                        detail=(
                            f"table={instruction.address:#x};base={base:#x};"
                            f"entry-width={entry_width}"
                        ),
                    )
                )
                self._add_edge(instruction.address, target, edge_kind)
                self._record_finite_target(target)
                self._enqueue(target, is_function=flow_kind == "call")
            self._record_fixpoint_update()
        return True

    def _resolve_computed_flows(self) -> None:
        candidate_addresses = set(self.indirect_candidates)
        self.diagnostics = {
            row
            for row in self.diagnostics
            if row.address not in candidate_addresses
            or row.kind
            not in {
                "computed-flow-blocker",
                "indirect-flow",
                "unsupported-far-flow",
            }
        }
        for address in sorted(candidate_addresses):
            flow_kind, is_far = self.indirect_candidates[address]
            instruction = self.instructions[address]
            decoded = self._owned_decoded(address)
            recovered = (
                False
                if is_far
                else self._recover_indexed_table(
                    decoded, instruction, flow_kind=flow_kind
                )
            )
            if recovered or any(
                row.address == address
                and row.kind == "computed-flow-blocker"
                for row in self.diagnostics
            ):
                continue
            self.diagnostics.add(
                OwnershipDiagnostic(
                    kind=("unsupported-far-flow" if is_far else "indirect-flow"),
                    address=address,
                    detail=(
                        f"unsupported far {flow_kind}: "
                        if is_far
                        else f"unresolved indirect {flow_kind}: "
                    )
                    + f"{instruction.mnemonic} {instruction.operands}".rstrip(),
                )
            )

    def _relocation_computed_candidates(
        self,
        relocation,
        *,
        byte_owners: dict[int, int],
        instructions: dict[int, Instruction],
    ) -> tuple[_RelocationEntryCandidate, ...]:
        candidates: list[_RelocationEntryCandidate] = []
        lower = max(
            relocation.va - 14,
            next(
                start
                for start, end in self.image.executable_ranges
                if start <= relocation.va < end
            ),
        )
        for start in range(lower, relocation.va + 1):
            try:
                decoded = self._decode_one(start)
            except CfgRecoveryError:
                continue
            if (
                not (decoded.group(CS_GRP_CALL) or decoded.group(CS_GRP_JUMP))
                or len(decoded.operands) != 1
                or decoded.operands[0].type != X86_OP_MEM
                or decoded.operands[0].mem.index == X86_REG_INVALID
                or decoded.disp_size != 4
                or decoded.address + decoded.disp_offset != relocation.va
            ):
                continue
            nearest_entry = decoded.address & ~0xF
            section_start = next(
                section_start
                for section_start, section_end in self.image.executable_ranges
                if section_start <= decoded.address < section_end
            )
            entry_floor = max(section_start, decoded.address - 512)
            for entry in range(nearest_entry, entry_floor - 1, -16):
                if entry >= decoded.address or entry in byte_owners:
                    continue
                sequence = []
                cursor = entry
                while cursor <= decoded.address:
                    try:
                        row = self._decode_one(cursor)
                    except CfgRecoveryError:
                        sequence = []
                        break
                    sequence.append(row)
                    cursor += row.size
                    if (
                        cursor > decoded.address
                        and row.address != decoded.address
                    ):
                        sequence = []
                        break
                if (
                    len(sequence) < 3
                    or sequence[-1].address != decoded.address
                    or sequence[-2].mnemonic not in {"ja", "jae"}
                    or sequence[-3].mnemonic != "cmp"
                    or len(sequence[-3].operands) != 2
                    or sequence[-3].operands[0].type != X86_OP_REG
                    or sequence[-3].operands[0].size != 4
                    or sequence[-3].operands[1].type != X86_OP_IMM
                    or self._register_family(sequence[-3].operands[0].reg)
                    != self._register_family(decoded.operands[0].mem.index)
                ):
                    continue
                prefix = sequence[:-2]
                internal_branch_targets = tuple(
                    sorted(
                        {
                            row.operands[0].imm
                            for row in prefix
                            if row.group(CS_GRP_JUMP)
                            and len(row.operands) == 1
                            and row.operands[0].type == X86_OP_IMM
                            and entry <= row.operands[0].imm <= decoded.address
                        }
                    )
                )
                branch_free_prefix = not any(
                    row.group(CS_GRP_RET)
                    or row.group(CS_GRP_IRET)
                    or (
                        row.group(CS_GRP_JUMP)
                        and row.mnemonic in {"jmp", "ljmp"}
                    )
                    for row in prefix
                )
                forward_guard_entries = tuple(
                    row.operands[0].imm
                    for row in prefix
                    if row.group(CS_GRP_JUMP)
                    and row.mnemonic not in {"jmp", "ljmp"}
                    and len(row.operands) == 1
                    and row.operands[0].type == X86_OP_IMM
                    and row.address < row.operands[0].imm
                    and entry <= row.operands[0].imm
                    <= sequence[-3].address
                )
                has_forward_guard_entry = any(
                    not any(
                        row.group(CS_GRP_RET) or row.group(CS_GRP_IRET)
                        for row in prefix
                        if row.address >= guard_entry
                    )
                    for guard_entry in forward_guard_entries
                )
                if not (branch_free_prefix or has_forward_guard_entry):
                    continue
                has_intervening_aligned_boundary = False
                for boundary in range(entry + 16, decoded.address, 16):
                    zero_start = boundary
                    while (
                        zero_start > max(section_start, boundary - 32)
                        and self.image.read(zero_start - 1, 1) == b"\0"
                    ):
                        zero_start -= 1
                    if (
                        boundary - zero_start >= 4
                        and boundary not in internal_branch_targets
                    ):
                        has_intervening_aligned_boundary = True
                        break
                if has_intervening_aligned_boundary:
                    continue
                gap_start = entry
                while (
                    gap_start > max(section_start, entry - 32)
                    and _is_executable_span(self.image, gap_start - 1, 1)
                    and self.image.read(gap_start - 1, 1) == b"\0"
                ):
                    gap_start -= 1
                gap_width = entry - gap_start
                self_lea = self._zero_gap_self_lea(gap_start, entry)
                if self_lea is not None:
                    kind, self_lea_start = self_lea
                    if kind == "internal-instruction":
                        continue
                    gap_start = self_lea_start
                    gap_width = entry - gap_start
                predecessor_owner = byte_owners.get(gap_start - 1)
                predecessor = (
                    instructions.get(predecessor_owner)
                    if predecessor_owner is not None
                    else None
                )
                follows_owned_terminal = (
                    predecessor is not None
                    and predecessor.address + predecessor.size == gap_start
                    and (
                        predecessor.mnemonic.startswith("ret")
                        or predecessor.mnemonic.startswith("iret")
                        or predecessor.mnemonic in {"jmp", "ljmp"}
                    )
                )
                if gap_width < 4 and not follows_owned_terminal:
                    continue
                if any(
                    address in byte_owners
                    for address in range(gap_start, entry)
                ):
                    continue
                span_end = decoded.address + decoded.size
                expected_owners = {
                    address: row.address
                    for row in sequence
                    for address in range(row.address, row.address + row.size)
                }
                if any(
                    address in byte_owners
                    and byte_owners[address] != expected_owners.get(address)
                    for address in range(entry, span_end)
                ):
                    continue
                candidates.append(
                    _RelocationEntryCandidate(
                        relocation_va=relocation.va,
                        category="relocation-computed-transfer",
                        entry=entry,
                        gap_start=gap_start,
                        evidence_address=decoded.address,
                        evidence_bytes=self.image.read(
                            decoded.address, decoded.size
                        ).hex(),
                        boundary_evidence=(
                            f"zero-alignment={gap_start:#x}-{entry:#x}"
                            + (
                                ";owned-terminal="
                                f"{predecessor.address:#x}:"
                                f"{predecessor.mnemonic}"
                                if follows_owned_terminal
                                else ""
                            )
                        ),
                        span_end=span_end,
                        internal_branch_targets=internal_branch_targets,
                    )
                )
        return tuple(sorted(set(candidates), key=_relocation_candidate_key))

    def _relocation_inline_data_candidates(
        self,
        relocation,
        *,
        byte_owners: dict[int, int],
        instructions: dict[int, Instruction],
    ) -> tuple[_RelocationEntryCandidate, ...]:
        section_start = next(
            start
            for start, end in self.image.executable_ranges
            if start <= relocation.va < end
        )
        candidates: list[_RelocationEntryCandidate] = []
        first_entry = (relocation.va + 4 + 15) & ~0xF
        for entry in range(first_entry, first_entry + 65, 16):
            if not _is_executable_span(self.image, entry, 1):
                break
            try:
                decoded = self._decode_one(entry)
            except CfgRecoveryError:
                continue
            if (
                not decoded.group(CS_GRP_CALL)
                or len(decoded.operands) != 1
                or decoded.operands[0].type != X86_OP_IMM
                or not _is_executable_span(
                    self.image, decoded.operands[0].imm, 1
                )
            ):
                continue
            for data_start in range(max(section_start, entry - 32), entry):
                predecessor_owner = byte_owners.get(data_start - 1)
                predecessor = (
                    instructions.get(predecessor_owner)
                    if predecessor_owner is not None
                    else None
                )
                if (
                    predecessor is None
                    or predecessor.address + predecessor.size != data_start
                    or not (
                        predecessor.mnemonic.startswith("ret")
                        or predecessor.mnemonic.startswith("iret")
                        or predecessor.mnemonic in {"jmp", "ljmp"}
                    )
                    or not (
                        data_start <= relocation.va
                        and relocation.va + 4 <= entry
                    )
                ):
                    continue
                blob = self.image.read(data_start, entry - data_start)
                printable_count = 0
                while (
                    printable_count < len(blob)
                    and 0x20 <= blob[printable_count] <= 0x7E
                ):
                    printable_count += 1
                trailing = blob[printable_count:]
                if (
                    printable_count < 16
                    or len(trailing) > 3
                    or any(byte >= 0x20 for byte in trailing)
                    or any(
                        address in byte_owners
                        for address in range(data_start, entry)
                    )
                ):
                    continue
                candidates.append(
                    _RelocationEntryCandidate(
                        relocation_va=relocation.va,
                        category="relocation-inline-data-successor",
                        entry=entry,
                        gap_start=data_start,
                        evidence_address=decoded.address,
                        evidence_bytes=bytes(decoded.bytes).hex(),
                        boundary_evidence=(
                            f"terminal-inline-data={data_start:#x}-{entry:#x};"
                            f"printable-prefix={printable_count};"
                            f"trailing-control-bytes={len(trailing)};"
                            f"owned-terminal={predecessor.address:#x}:"
                            f"{predecessor.mnemonic}"
                        ),
                        span_end=decoded.address + decoded.size,
                    )
                )
        return tuple(sorted(set(candidates), key=_relocation_candidate_key))

    def _zero_gap_self_lea(
        self, gap_start: int, entry: int
    ) -> tuple[str, int] | None:
        if gap_start >= entry:
            return None
        section_start = next(
            start
            for start, end in self.image.executable_ranges
            if start <= gap_start < end
        )
        for start in range(max(section_start, entry - 15), gap_start):
            try:
                decoded = self._decode_one(start)
            except CfgRecoveryError:
                continue
            if (
                decoded.id != X86_INS_LEA
                or decoded.address + decoded.size != entry
                or len(decoded.operands) != 2
                or decoded.operands[0].type != X86_OP_REG
                or decoded.operands[1].type != X86_OP_MEM
                or decoded.operands[1].mem.index != X86_REG_INVALID
                or decoded.operands[1].mem.disp != 0
                or self._register_family(decoded.operands[0].reg)
                != self._register_family(decoded.operands[1].mem.base)
            ):
                continue
            predecessors = []
            for predecessor_start in range(
                max(section_start, decoded.address - 15), decoded.address
            ):
                try:
                    predecessor = self._decode_one(predecessor_start)
                except CfgRecoveryError:
                    continue
                if predecessor.address + predecessor.size == decoded.address:
                    predecessors.append(predecessor)
            predecessor = max(
                predecessors, key=lambda row: row.address, default=None
            )
            is_terminal = predecessor is not None and (
                predecessor.group(CS_GRP_RET)
                or predecessor.group(CS_GRP_IRET)
                or (
                    predecessor.group(CS_GRP_JUMP)
                    and predecessor.mnemonic in {"jmp", "ljmp"}
                )
            )
            return (
                "terminal-padding" if is_terminal else "internal-instruction",
                decoded.address,
            )
        return None

    def _relocation_aligned_entry_candidates(
        self,
        relocation,
        *,
        byte_owners: dict[int, int],
        instructions: dict[int, Instruction],
    ) -> tuple[_RelocationEntryCandidate, ...]:
        pointer = int.from_bytes(self.image.read(relocation.va, 4), "little")
        if not _is_mapped_span(self.image, pointer, 1):
            return ()
        section_start = next(
            start
            for start, end in self.image.executable_ranges
            if start <= relocation.va < end
        )
        candidates: list[_RelocationEntryCandidate] = []
        for start in range(max(section_start, relocation.va - 14), relocation.va + 1):
            try:
                decoded = self._decode_one(start)
            except CfgRecoveryError:
                continue
            field_matches = (
                decoded.disp_size == 4
                and decoded.address + decoded.disp_offset == relocation.va
            ) or (
                decoded.imm_size == 4
                and decoded.address + decoded.imm_offset == relocation.va
            )
            if not field_matches:
                continue

            nearest_entry = decoded.address & ~0xF
            for entry in range(
                nearest_entry, max(section_start, decoded.address - 64), -16
            ):
                if entry in byte_owners:
                    continue
                sequence = []
                cursor = entry
                while cursor <= decoded.address:
                    try:
                        row = self._decode_one(cursor)
                    except CfgRecoveryError:
                        sequence = []
                        break
                    sequence.append(row)
                    cursor += row.size
                    if cursor > decoded.address and row.address != decoded.address:
                        sequence = []
                        break
                if (
                    not sequence
                    or sequence[-1].address != decoded.address
                ):
                    continue

                gap_start = entry
                while (
                    gap_start > max(section_start, entry - 32)
                    and self.image.read(gap_start - 1, 1) == b"\0"
                ):
                    gap_start -= 1
                predecessor_owner = byte_owners.get(gap_start - 1)
                predecessor = (
                    instructions.get(predecessor_owner)
                    if predecessor_owner is not None
                    else None
                )
                follows_owned_terminal = (
                    predecessor is not None
                    and predecessor.address + predecessor.size == gap_start
                    and (
                        predecessor.mnemonic.startswith("ret")
                        or predecessor.mnemonic.startswith("iret")
                        or predecessor.mnemonic in {"jmp", "ljmp"}
                    )
                )
                prefix = sequence[:-1]
                has_return = any(
                    row.group(CS_GRP_RET) or row.group(CS_GRP_IRET)
                    for row in prefix
                )
                branch_free_prefix = not any(
                    row.group(CS_GRP_CALL) or row.group(CS_GRP_JUMP)
                    for row in prefix
                )
                gap_width = entry - gap_start
                self_lea = self._zero_gap_self_lea(gap_start, entry)
                if self_lea is not None:
                    kind, self_lea_start = self_lea
                    if kind == "internal-instruction":
                        continue
                    gap_start = self_lea_start
                    gap_width = entry - gap_start
                if (
                    has_return
                    or (
                        gap_width < 4
                        and (
                            not follows_owned_terminal
                            or not branch_free_prefix
                        )
                    )
                ):
                    continue
                has_intervening_aligned_boundary = False
                for boundary in range(entry + 16, decoded.address, 16):
                    zero_start = boundary
                    while (
                        zero_start > max(section_start, boundary - 32)
                        and self.image.read(zero_start - 1, 1) == b"\0"
                    ):
                        zero_start -= 1
                    if boundary - zero_start >= 4:
                        has_intervening_aligned_boundary = True
                        break
                if has_intervening_aligned_boundary:
                    continue
                if any(
                    address in byte_owners
                    for address in range(gap_start, entry)
                ):
                    continue
                span_end = decoded.address + decoded.size
                expected_owners = {
                    address: row.address
                    for row in sequence
                    for address in range(row.address, row.address + row.size)
                }
                if any(
                    address in byte_owners
                    and byte_owners[address] != expected_owners.get(address)
                    for address in range(entry, span_end)
                ):
                    continue
                candidates.append(
                    _RelocationEntryCandidate(
                        relocation_va=relocation.va,
                        category="relocation-aligned-entry",
                        entry=entry,
                        gap_start=gap_start,
                        evidence_address=decoded.address,
                        evidence_bytes=bytes(decoded.bytes).hex(),
                        boundary_evidence=(
                            f"zero-alignment={gap_start:#x}-{entry:#x}"
                            + (
                                ";owned-terminal="
                                f"{predecessor.address:#x}:"
                                f"{predecessor.mnemonic}"
                                if follows_owned_terminal
                                else ""
                            )
                        ),
                        span_end=span_end,
                    )
                )
        return tuple(sorted(set(candidates), key=_relocation_candidate_key))

    def _discover_relocation_computed_transfers(self) -> None:
        byte_owners = dict(self.byte_owners)
        instructions = dict(self.instructions)
        discovered: list[_RelocationEntryCandidate] = []
        for relocation in sorted(
            self.image.relocations, key=lambda row: (row.va, row.type)
        ):
            if (
                relocation.type != 3
                or not _is_executable_span(self.image, relocation.va, 4)
            ):
                continue
            relocation_owners = {
                byte_owners[address]
                for address in range(relocation.va, relocation.va + 4)
                if address in byte_owners
            }
            if relocation_owners:
                if (
                    len(relocation_owners) != 1
                    or any(
                        byte_owners.get(address) not in relocation_owners
                        for address in range(
                            relocation.va, relocation.va + 4
                        )
                    )
                ):
                    continue
                owner = next(iter(relocation_owners))
                decoded_owner = self._decode_one(owner)
                if (
                    not (
                        decoded_owner.disp_size == 4
                        and decoded_owner.address
                        + decoded_owner.disp_offset
                        == relocation.va
                    )
                    and not (
                        decoded_owner.imm_size == 4
                        and decoded_owner.address
                        + decoded_owner.imm_offset
                        == relocation.va
                    )
                ):
                    continue
            else:
                discovered.extend(
                    self._relocation_inline_data_candidates(
                        relocation,
                        byte_owners=byte_owners,
                        instructions=instructions,
                    )
                )
            discovered.extend(
                self._relocation_aligned_entry_candidates(
                    relocation,
                    byte_owners=byte_owners,
                    instructions=instructions,
                )
            )
            discovered.extend(
                self._relocation_computed_candidates(
                    relocation,
                    byte_owners=byte_owners,
                    instructions=instructions,
                )
            )

        selected = _select_relocation_entry_candidates(tuple(discovered))
        for candidate in selected:
            if candidate.category == "relocation-aligned-entry":
                detail = (
                    f"instruction-bytes={candidate.evidence_bytes};"
                    f"{candidate.boundary_evidence}"
                )
                evidence_provenance = (
                    "relocation-aligned-entry;"
                    f"relocation={candidate.relocation_va:#x};"
                    f"entry={candidate.entry:#x}"
                )
            elif candidate.category == "relocation-inline-data-successor":
                detail = (
                    f"successor-instruction-bytes="
                    f"{candidate.evidence_bytes};"
                    f"aligned-entry={candidate.entry:#x};"
                    f"{candidate.boundary_evidence}"
                )
                evidence_provenance = (
                    "relocation-inline-data-successor;"
                    f"relocation={candidate.relocation_va:#x};"
                    f"entry={candidate.entry:#x}"
                )
            else:
                detail = (
                    f"transfer={candidate.evidence_address:#x};"
                    f"instruction-bytes={candidate.evidence_bytes};"
                    f"aligned-entry={candidate.entry:#x};"
                    f"{candidate.boundary_evidence}"
                )
                evidence_provenance = (
                    "computed-dispatch-alignment;"
                    f"relocation={candidate.relocation_va:#x};"
                    f"transfer={candidate.evidence_address:#x}"
                )
            record = SeedRecord(
                address=candidate.entry,
                category=candidate.category,
                provenance_address=candidate.relocation_va,
                provenance_bytes=self.image.read(
                    candidate.relocation_va, 4
                ).hex(),
                detail=detail,
            )
            if record in self.seed_records:
                continue
            self.seed_records.add(record)
            if candidate.gap_start < candidate.entry:
                self.structural_data_evidence.add(
                    _DataEvidence(
                        start=candidate.gap_start,
                        end=candidate.entry,
                        provenance=evidence_provenance,
                    )
                )
            self._record_finite_target(candidate.entry)
            self._enqueue(candidate.entry, is_function=True)
            self._record_fixpoint_update()

    def _decode_from(self, start: int) -> None:
        self._validate_target(start)
        owner = self.byte_owners.get(start)
        if owner is not None:
            if owner != start:
                raise CfgRecoveryError(
                    f"CFG seed or target lies in instruction interior: "
                    f"{start:#x} is owned by {owner:#x}"
                )
            return

        address = start
        previous: Instruction | None = None
        while True:
            if address != start and address in self.block_starts:
                if previous is not None:
                    self._add_edge(
                        previous.address, address, "fallthrough"
                    )
                return

            owner = self.byte_owners.get(address)
            if owner is not None:
                if owner != address:
                    raise CfgRecoveryError(
                        "sequential decode reaches instruction interior: "
                        f"{address:#x} is owned by {owner:#x}"
                    )
                return

            decoded = self._decode_one(address)
            instruction = self._claim_instruction(decoded)
            next_address = address + instruction.size

            if decoded.group(CS_GRP_CALL):
                target = self._direct_target(decoded)
                if target is None:
                    is_far = decoded.id == X86_INS_LCALL
                    self.indirect_candidates[address] = ("call", is_far)
                else:
                    self._record_direct_target(
                        instruction, target, "direct-call-target"
                    )
                    self.direct_calls.add(
                        DirectCall(address=address, target=target)
                    )
                    self._add_edge(address, target, "direct-call")
                    self._record_finite_target(target)
                    self._enqueue(target, is_function=True)
                self._add_edge(address, next_address, "call-fallthrough")
                self._enqueue(next_address)
                self.terminators.add(address)
                return

            if decoded.group(CS_GRP_JUMP):
                target = self._direct_target(decoded)
                is_unconditional = decoded.id in {
                    X86_INS_JMP,
                    X86_INS_LJMP,
                }
                if target is None:
                    is_far = decoded.id == X86_INS_LJMP
                    self.indirect_candidates[address] = ("jump", is_far)
                else:
                    self._record_direct_target(
                        instruction, target, "direct-branch-target"
                    )
                    edge_kind = (
                        "unconditional-branch"
                        if is_unconditional
                        else "conditional-branch"
                    )
                    self._add_edge(address, target, edge_kind)
                    self._record_finite_target(target)
                    self._enqueue(target)
                if not is_unconditional:
                    self._add_edge(address, next_address, "fallthrough")
                    self._enqueue(next_address)
                self.terminators.add(address)
                return

            if decoded.group(CS_GRP_RET) or decoded.group(CS_GRP_IRET):
                self.terminators.add(address)
                return

            previous = instruction
            address = next_address

    def _build_blocks(self) -> tuple[BasicBlock, ...]:
        blocks = []
        for start in sorted(self.block_starts):
            if start not in self.instructions:
                continue
            addresses = []
            address = start
            while address in self.instructions:
                instruction = self.instructions[address]
                addresses.append(address)
                next_address = address + instruction.size
                if address in self.terminators:
                    break
                if next_address in self.block_starts:
                    break
                address = next_address
            block = BasicBlock(
                start=start,
                end=(
                    self.instructions[addresses[-1]].address
                    + self.instructions[addresses[-1]].size
                ),
                instruction_addresses=tuple(addresses),
            )
            blocks.append(block)
            self._check_count("max_blocks", len(blocks))
        return tuple(sorted(blocks, key=_block_key))

    def _owned_decoded(self, address: int):
        decoded = self._decode_one(address)
        instruction = self.instructions[address]
        if (
            decoded.size != instruction.size
            or bytes(decoded.bytes).hex() != instruction.bytes_hex
        ):
            raise CfgRecoveryError(
                f"owned instruction bytes changed at {address:#x}"
            )
        return decoded

    def _register_family(self, register: int) -> str:
        name = self.decoder.reg_name(register)
        families = {
            "al": "eax",
            "ah": "eax",
            "ax": "eax",
            "eax": "eax",
            "bl": "ebx",
            "bh": "ebx",
            "bx": "ebx",
            "ebx": "ebx",
            "cl": "ecx",
            "ch": "ecx",
            "cx": "ecx",
            "ecx": "ecx",
            "dl": "edx",
            "dh": "edx",
            "dx": "edx",
            "edx": "edx",
            "si": "esi",
            "esi": "esi",
            "di": "edi",
            "edi": "edi",
            "bp": "ebp",
            "ebp": "ebp",
            "sp": "esp",
            "esp": "esp",
            "ip": "eip",
            "eip": "eip",
        }
        return families.get(name, name)

    def _flow_error(self, decoded, reason: str) -> CfgRecoveryError:
        instruction = self.instructions[decoded.address]
        return CfgRecoveryError(
            "ambiguous x86 value-flow semantics: "
            f"address={decoded.address:#x};bytes={instruction.bytes_hex};"
            f"id={decoded.id};mnemonic={decoded.mnemonic};"
            f"operands={decoded.op_str};reason={reason}"
        )

    def _register_slice(
        self, register: int, width_bits: int | None = None
    ) -> _RegisterSlice:
        name = self.decoder.reg_name(register)
        gpr_aliases = {
            "al": ("gpr:a", 0, 8),
            "ah": ("gpr:a", 8, 8),
            "ax": ("gpr:a", 0, 16),
            "eax": ("gpr:a", 0, 32),
            "rax": ("gpr:a", 0, 64),
            "bl": ("gpr:b", 0, 8),
            "bh": ("gpr:b", 8, 8),
            "bx": ("gpr:b", 0, 16),
            "ebx": ("gpr:b", 0, 32),
            "rbx": ("gpr:b", 0, 64),
            "cl": ("gpr:c", 0, 8),
            "ch": ("gpr:c", 8, 8),
            "cx": ("gpr:c", 0, 16),
            "ecx": ("gpr:c", 0, 32),
            "rcx": ("gpr:c", 0, 64),
            "dl": ("gpr:d", 0, 8),
            "dh": ("gpr:d", 8, 8),
            "dx": ("gpr:d", 0, 16),
            "edx": ("gpr:d", 0, 32),
            "rdx": ("gpr:d", 0, 64),
            "si": ("gpr:si", 0, 16),
            "esi": ("gpr:si", 0, 32),
            "rsi": ("gpr:si", 0, 64),
            "di": ("gpr:di", 0, 16),
            "edi": ("gpr:di", 0, 32),
            "rdi": ("gpr:di", 0, 64),
            "bp": ("gpr:bp", 0, 16),
            "ebp": ("gpr:bp", 0, 32),
            "rbp": ("gpr:bp", 0, 64),
            "sp": ("gpr:sp", 0, 16),
            "esp": ("gpr:sp", 0, 32),
            "rsp": ("gpr:sp", 0, 64),
            "ip": ("gpr:ip", 0, 16),
            "eip": ("gpr:ip", 0, 32),
            "rip": ("gpr:ip", 0, 64),
        }
        if name in gpr_aliases:
            family, offset, natural_width = gpr_aliases[name]
            width = natural_width if width_bits is None else width_bits
            if width <= 0 or offset + width > 64:
                raise CfgRecoveryError(
                    f"invalid register slice width: register={name};"
                    f"width={width}"
                )
            return _RegisterSlice(
                family=family,
                mask=((1 << width) - 1) << offset,
                name=name,
            )

        match = re.fullmatch(r"(?:xmm|ymm|zmm)(\d+)", name)
        if match:
            natural_width = {
                "x": 128,
                "y": 256,
                "z": 512,
            }[name[0]]
            width = natural_width if width_bits is None else width_bits
            if width <= 0 or width > natural_width:
                raise CfgRecoveryError(
                    f"invalid vector slice width: register={name};"
                    f"width={width}"
                )
            return _RegisterSlice(
                family=f"vector:{match.group(1)}",
                mask=(1 << width) - 1,
                name=name,
            )

        match = re.fullmatch(r"mm(\d+)", name)
        if match:
            width = 64 if width_bits is None else width_bits
            return _RegisterSlice(
                family=f"x87-physical:{match.group(1)}",
                mask=(1 << width) - 1,
                name=name,
            )
        match = re.fullmatch(r"st\((\d+)\)", name)
        if match:
            width = 80 if width_bits is None else width_bits
            return _RegisterSlice(
                family=f"x87-logical:{match.group(1)}",
                mask=(1 << width) - 1,
                name=name,
            )
        match = re.fullmatch(r"k(\d+)", name)
        if match:
            width = 64 if width_bits is None else width_bits
            return _RegisterSlice(
                family=f"mask:{match.group(1)}",
                mask=(1 << width) - 1,
                name=name,
            )

        fixed_widths = {
            "eflags": ("flags", 32),
            "rflags": ("flags", 64),
            "fpsw": ("fpsw", 16),
            "fpcw": ("fpcw", 16),
            "mxcsr": ("mxcsr", 32),
            "cs": ("segment:cs", 16),
            "ds": ("segment:ds", 16),
            "es": ("segment:es", 16),
            "fs": ("segment:fs", 16),
            "gs": ("segment:gs", 16),
            "ss": ("segment:ss", 16),
        }
        if name in fixed_widths:
            family, natural_width = fixed_widths[name]
            width = natural_width if width_bits is None else width_bits
            return _RegisterSlice(
                family=family, mask=(1 << width) - 1, name=name
            )

        match = re.fullmatch(r"(?:cr|dr|bnd|tmm)(\d+)", name)
        if match:
            width = 64 if width_bits is None else width_bits
            return _RegisterSlice(
                family=f"opaque:{name}",
                mask=(1 << width) - 1,
                name=name,
            )
        raise CfgRecoveryError(f"unmodeled x86 register alias: {name or register}")

    def _named_register_slice(self, name: str) -> _RegisterSlice:
        synthetic = {
            "fpcw": _RegisterSlice("fpcw", (1 << 16) - 1, "fpcw"),
            "mxcsr": _RegisterSlice("mxcsr", (1 << 32) - 1, "mxcsr"),
        }
        if name in synthetic:
            return synthetic[name]
        register_id = getattr(x86_const, f"X86_REG_{name.upper()}", None)
        if register_id is None:
            raise CfgRecoveryError(f"unknown audited register name: {name}")
        return self._register_slice(register_id)

    def _register_dependency(
        self, register: int, width_bits: int | None = None
    ) -> _ValueDependency:
        return _ValueDependency(
            "register", register=self._register_slice(register, width_bits)
        )

    @staticmethod
    def _memory_dependency(index: int) -> _ValueDependency:
        return _ValueDependency("memory", operand_index=index)

    @staticmethod
    def _immediate_dependency(value: int, index: int) -> _ValueDependency:
        return _ValueDependency(
            "immediate", value=value & 0xFFFF_FFFF, operand_index=index
        )

    def _operand_dependency(
        self, decoded, index: int, *, max_width_bits: int | None = None
    ) -> _ValueDependency:
        operand = decoded.operands[index]
        if operand.type == X86_OP_REG:
            width = operand.size * 8
            if max_width_bits is not None:
                width = min(width, max_width_bits)
            return self._register_dependency(operand.reg, width)
        if operand.type == X86_OP_MEM:
            return self._memory_dependency(index)
        if operand.type == X86_OP_IMM:
            return self._immediate_dependency(operand.imm, index)
        raise self._flow_error(decoded, f"unsupported operand type at {index}")

    def _register_subslice_dependency(
        self, decoded, index: int, offset_bits: int, width_bits: int
    ) -> _ValueDependency:
        operand = decoded.operands[index]
        if operand.type != X86_OP_REG:
            raise self._flow_error(
                decoded, f"operand {index} is not a register slice"
            )
        whole = self._register_slice(operand.reg, operand.size * 8)
        mask = ((1 << width_bits) - 1) << offset_bits
        if mask & ~whole.mask:
            raise self._flow_error(
                decoded,
                f"register slice exceeds operand {index}: "
                f"offset={offset_bits};width={width_bits}",
            )
        return _ValueDependency(
            "register",
            register=_RegisterSlice(whole.family, mask, whole.name),
            operand_index=index,
        )

    def _explicit_register_effect(
        self,
        decoded,
        operand,
        dependencies: tuple[_ValueDependency, ...],
    ) -> _RegisterEffect:
        natural = self._register_slice(operand.reg, operand.size * 8)
        name = natural.name
        first_byte = bytes(decoded.bytes)[0]
        written_mask = natural.mask
        # VEX XMM writes zero the upper YMM alias; EVEX XMM/YMM writes zero
        # every lane above the selected vector length in the ZMM alias.
        if name.startswith("xmm") and first_byte in {0xC4, 0xC5}:
            written_mask = (1 << 256) - 1
        elif name.startswith(("xmm", "ymm")) and first_byte == 0x62:
            written_mask = (1 << 512) - 1
        destination = _RegisterSlice(
            family=natural.family,
            mask=written_mask,
            name=natural.name,
        )
        return _RegisterEffect(
            destination=destination,
            dependencies=dependencies,
            taint_mask=natural.mask,
        )

    def _implicit_dependency_slices(
        self, decoded
    ) -> tuple[_ValueDependency, ...]:
        explicit_registers = {
            operand.reg
            for operand in decoded.operands
            if operand.type == X86_OP_REG
        }
        for operand in decoded.operands:
            if operand.type != X86_OP_MEM:
                continue
            explicit_registers.update(
                register
                for register in (
                    operand.mem.segment,
                    operand.mem.base,
                    operand.mem.index,
                )
                if register != X86_REG_INVALID
            )
        return tuple(
            self._register_dependency(register)
            for register in decoded.regs_read
            if register not in explicit_registers
        )

    def _address_dependencies(
        self, decoded, memory
    ) -> tuple[_ValueDependency, ...]:
        dependencies = []
        for register in (memory.base, memory.index):
            if register == X86_REG_INVALID:
                continue
            name = self.decoder.reg_name(register)
            if name in {"eiz", "riz"}:
                continue
            dependencies.append(
                _ValueDependency(
                    "address-register", register=self._register_slice(register)
                )
            )
        dependencies.append(
            _ValueDependency("address-immediate", value=memory.disp & 0xFFFF_FFFF)
        )
        return tuple(dependencies)

    def _state_save_dependencies(self, kind: str) -> tuple[_ValueDependency, ...]:
        dependencies: list[_ValueDependency] = []
        for index in range(8):
            dependencies.append(
                _ValueDependency(
                    "register",
                    register=_RegisterSlice(
                        family=f"x87-physical:{index}",
                        mask=(1 << 80) - 1,
                        name=f"x87-physical-{index}",
                    ),
                )
            )
        if kind in {"fxsave", "xsave"}:
            vector_count = 8 if kind == "fxsave" else 32
            vector_width = 128 if kind == "fxsave" else 512
            for index in range(vector_count):
                dependencies.append(
                    _ValueDependency(
                        "register",
                        register=_RegisterSlice(
                            family=f"vector:{index}",
                            mask=(1 << vector_width) - 1,
                            name=(
                                f"xmm{index}"
                                if kind == "fxsave"
                                else f"zmm{index}"
                            ),
                        ),
                    )
                )
        if kind == "xsave":
            for index in range(8):
                dependencies.append(
                    _ValueDependency(
                        "register",
                        register=_RegisterSlice(
                            family=f"mask:{index}",
                            mask=(1 << 64) - 1,
                            name=f"k{index}",
                        ),
                    )
                )
        return tuple(dependencies)

    @staticmethod
    def _x87_stack_slice(index: int) -> _RegisterSlice:
        if not 0 <= index < 8:
            raise CfgRecoveryError(f"invalid x87 stack index: {index}")
        return _RegisterSlice(
            family=f"x87-logical:{index}",
            mask=(1 << 80) - 1,
            name=f"st({index})",
        )

    def _x87_stack_dependency(self, index: int) -> _ValueDependency:
        return _ValueDependency(
            "register", register=self._x87_stack_slice(index)
        )

    def _x87_stack_dependencies(self) -> tuple[_ValueDependency, ...]:
        return tuple(self._x87_stack_dependency(index) for index in range(8))

    def _x87_register_index(self, decoded, operand) -> int:
        if operand.type != X86_OP_REG:
            raise self._flow_error(decoded, "x87 operand is not a register")
        name = self.decoder.reg_name(operand.reg)
        match = re.fullmatch(r"st\((\d+)\)", name)
        if match is None or int(match.group(1)) >= 8:
            raise self._flow_error(
                decoded, f"unsupported x87 register operand: {name}"
            )
        return int(match.group(1))

    @staticmethod
    def _has_x87_opcode(decoded) -> bool:
        instruction_bytes = bytes(decoded.bytes)
        opcode_index = 0
        while (
            opcode_index < len(instruction_bytes)
            and instruction_bytes[opcode_index] in _LEGACY_X86_PREFIXES
        ):
            opcode_index += 1
        return (
            opcode_index < len(instruction_bytes)
            and 0xD8 <= instruction_bytes[opcode_index] <= 0xDF
        )

    def _x87_value_flow(self, decoded) -> _InstructionValueFlow | None:
        if decoded.mnemonic in {"emms", "femms"}:
            return _InstructionValueFlow(
                x87_effect=_X87Effect("empty-tags")
            )
        if decoded.id == 210:  # FXRSTOR
            return _InstructionValueFlow(
                register_effects=tuple(
                    _RegisterEffect(
                        _RegisterSlice(
                            family=f"vector:{index}",
                            mask=_XMM_PAYLOAD_MASK,
                            name=f"xmm{index}",
                        ),
                        (),
                    )
                    for index in range(8)
                ),
                x87_effect=_X87Effect("restore"),
            )
        if not self._has_x87_opcode(decoded):
            return None
        operands = decoded.operands
        mnemonic = decoded.mnemonic

        if mnemonic == "fld":
            if len(operands) != 1:
                raise self._flow_error(decoded, "unexpected FLD form")
            source = operands[0]
            if source.type == X86_OP_REG:
                value = (
                    self._x87_stack_dependency(
                        self._x87_register_index(decoded, source)
                    ),
                )
            elif source.type == X86_OP_MEM:
                value = (self._memory_dependency(0),)
            else:
                raise self._flow_error(decoded, "unsupported FLD source")
            return _InstructionValueFlow(
                x87_effect=_X87Effect("push", dependencies=value)
            )

        if decoded.id in _X87_CONSTANT_LOADS:
            return _InstructionValueFlow(
                x87_effect=_X87Effect("push")
            )
        if decoded.id in _X87_MEMORY_LOADS:
            if len(operands) != 1 or operands[0].type != X86_OP_MEM:
                raise self._flow_error(decoded, "unexpected x87 load form")
            return _InstructionValueFlow(
                x87_effect=_X87Effect(
                    "push", dependencies=(self._memory_dependency(0),)
                )
            )

        if mnemonic == "fxch":
            register_operands = [
                operand for operand in operands if operand.type == X86_OP_REG
            ]
            if not register_operands:
                raise self._flow_error(decoded, "unexpected FXCH form")
            target = self._x87_register_index(decoded, register_operands[-1])
            return _InstructionValueFlow(
                x87_effect=_X87Effect("swap", target=target)
            )

        if decoded.id in _X87_VALUE_WRITERS:
            if len(operands) != 1:
                raise self._flow_error(decoded, "unexpected x87 store form")
            destination = operands[0]
            writes: tuple[MemoryWriteSpec, ...] = ()
            if destination.type == X86_OP_MEM:
                writes = (
                    MemoryWriteSpec(
                        "x87-value-store",
                        (self._x87_stack_dependency(0),),
                    ),
                )
            elif destination.type == X86_OP_REG and decoded.id in {713, 714}:
                target = self._x87_register_index(decoded, destination)
                return _InstructionValueFlow(
                    x87_effect=_X87Effect(
                        "store-register",
                        target=target,
                        pop_count=(1 if decoded.id == 714 else 0),
                        dependencies=(self._x87_stack_dependency(0),),
                    )
                )
            else:
                raise self._flow_error(decoded, "unsupported x87 store form")
            effect = (
                _X87Effect("pop", pop_count=1)
                if decoded.id in _X87_POP_VALUE_WRITERS
                else None
            )
            return _InstructionValueFlow(
                memory_writes=writes, x87_effect=effect
            )

        if mnemonic in _X87_BINARY_ARITHMETIC_MNEMONICS:
            is_pop = mnemonic.endswith("p")
            if operands and operands[0].type == X86_OP_MEM:
                if is_pop or len(operands) != 1:
                    raise self._flow_error(
                        decoded, "unexpected x87 memory arithmetic form"
                    )
                dependencies = (
                    self._x87_stack_dependency(0),
                    self._memory_dependency(0),
                )
                return _InstructionValueFlow(
                    x87_effect=_X87Effect(
                        "arithmetic",
                        target=0,
                        dependencies=dependencies,
                    )
                )
            register_operands = [
                operand for operand in operands if operand.type == X86_OP_REG
            ]
            if not register_operands:
                raise self._flow_error(
                    decoded, "unexpected x87 register arithmetic form"
                )
            target = (
                self._x87_register_index(decoded, register_operands[0])
                if len(register_operands) > 1 or is_pop
                else 0
            )
            other = (
                self._x87_register_index(decoded, register_operands[-1])
                if len(register_operands) > 1
                else (
                    0
                    if is_pop
                    else self._x87_register_index(
                        decoded, register_operands[0]
                    )
                )
            )
            return _InstructionValueFlow(
                x87_effect=_X87Effect(
                    "arithmetic",
                    target=target,
                    pop_count=(1 if is_pop else 0),
                    dependencies=(
                        self._x87_stack_dependency(target),
                        self._x87_stack_dependency(other),
                    ),
                )
            )

        pop_count = _X87_COMPARISON_POP_COUNTS.get(mnemonic)
        if pop_count is not None:
            return _InstructionValueFlow(
                x87_effect=_X87Effect("pop", pop_count=pop_count)
            )
        if mnemonic in {"fcom", "fucom", "ftst", "fxam"}:
            return _InstructionValueFlow()

        if mnemonic == "ffree" and len(operands) == 1:
            target = self._x87_register_index(decoded, operands[0])
            return _InstructionValueFlow(
                x87_effect=_X87Effect("free", target=target)
            )
        if mnemonic == "ffreep" and len(operands) == 1:
            target = self._x87_register_index(decoded, operands[0])
            return _InstructionValueFlow(
                x87_effect=_X87Effect(
                    "free", target=target, pop_count=1
                )
            )

        if mnemonic in {"fninit", "finit"}:
            return _InstructionValueFlow(x87_effect=_X87Effect("init"))
        if mnemonic == "fdecstp":
            return _InstructionValueFlow(
                x87_effect=_X87Effect("rotate-top", target=-1)
            )
        if mnemonic == "fincstp":
            return _InstructionValueFlow(
                x87_effect=_X87Effect("rotate-top", target=1)
            )
        if mnemonic == "fldenv":
            return _InstructionValueFlow(
                x87_effect=_X87Effect("load-environment")
            )
        if mnemonic == "frstor":
            return _InstructionValueFlow(
                x87_effect=_X87Effect("restore")
            )
        if decoded.id in _FNSAVE_WRITERS:
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "fnsave-state", self._state_save_dependencies("fnsave")
                    ),
                ),
                x87_effect=_X87Effect("init"),
            )
        if mnemonic in _X87_NON_STACK_MNEMONICS or decoded.id in (
            set(_X87_CONTROL_WRITERS)
            | _NO_TRACKED_PAYLOAD_MEMORY_WRITERS
        ):
            return None

        return _InstructionValueFlow(
            taint_blocker_dependencies=self._x87_stack_dependencies(),
            taint_blocker_reason=(
                "unmodeled x87 stack effect; "
                f"mnemonic={mnemonic};operands={decoded.op_str}"
            ),
        )

    def _zero_idiom_flow(self, decoded) -> _InstructionValueFlow | None:
        operands = decoded.operands
        zero_mnemonics = {
            "pxor",
            "sub",
            "vpxor",
            "vpxord",
            "vpxorq",
            "vxorpd",
            "vxorps",
            "xor",
            "xorpd",
            "xorps",
        }
        if decoded.mnemonic not in zero_mnemonics or len(operands) < 2:
            return None
        sources = operands[-2:]
        if any(operand.type != X86_OP_REG for operand in sources):
            return None
        left = self._register_slice(
            sources[0].reg, sources[0].size * 8
        )
        right = self._register_slice(
            sources[1].reg, sources[1].size * 8
        )
        if left.family != right.family or left.mask != right.mask:
            return None
        destination = operands[0]
        if destination.type != X86_OP_REG:
            return None
        effects = [self._explicit_register_effect(decoded, destination, ())]
        effects.extend(
            _RegisterEffect(self._register_slice(register), ())
            for register in decoded.regs_write
        )
        return _InstructionValueFlow(register_effects=tuple(effects))

    def _instruction_value_flow(self, decoded) -> _InstructionValueFlow:
        operands = decoded.operands

        if decoded.group(CS_GRP_CALL):
            return _InstructionValueFlow(
                register_effects=tuple(
                    _RegisterEffect(self._named_register_slice(name), ())
                    for name in _CALL_CLOBBERED_REGISTER_NAMES
                ),
                x87_effect=_X87Effect("load-environment"),
            )
        if decoded.group(CS_GRP_JUMP) or decoded.group(CS_GRP_RET) or decoded.group(
            CS_GRP_IRET
        ):
            return _InstructionValueFlow()

        zero_flow = self._zero_idiom_flow(decoded)
        if zero_flow is not None:
            return zero_flow

        x87_flow = self._x87_value_flow(decoded)
        if x87_flow is not None:
            return x87_flow

        if decoded.id == X86_INS_LEA:
            if (
                len(operands) != 2
                or operands[0].type != X86_OP_REG
                or operands[1].type != X86_OP_MEM
            ):
                raise self._flow_error(decoded, "unexpected LEA form")
            return _InstructionValueFlow(
                register_effects=(
                    _RegisterEffect(
                        self._register_slice(
                            operands[0].reg, operands[0].size * 8
                        ),
                        self._address_dependencies(decoded, operands[1].mem),
                    ),
                )
            )

        if decoded.id in _CMOV_INSTRUCTIONS:
            if len(operands) != 2 or operands[0].type != X86_OP_REG:
                raise self._flow_error(decoded, "unexpected CMOV form")
            destination = self._register_slice(
                operands[0].reg, operands[0].size * 8
            )
            dependencies = (
                _ValueDependency("register", register=destination),
                self._operand_dependency(decoded, 1),
                *self._implicit_dependency_slices(decoded),
            )
            return _InstructionValueFlow(
                register_effects=(
                    _RegisterEffect(destination, tuple(dependencies)),
                )
            )

        if decoded.id in _XCHG_INSTRUCTIONS:
            if len(operands) != 2:
                raise self._flow_error(decoded, "unexpected XCHG form")
            left, right = operands
            effects: list[_RegisterEffect] = []
            writes: list[MemoryWriteSpec] = []
            if left.type == X86_OP_REG:
                effects.append(
                    _RegisterEffect(
                        self._register_slice(left.reg, left.size * 8),
                        (self._operand_dependency(decoded, 1),),
                    )
                )
            elif left.type == X86_OP_MEM:
                writes.append(
                    MemoryWriteSpec(
                        "xchg-memory",
                        (self._operand_dependency(decoded, 1),),
                    )
                )
            else:
                raise self._flow_error(decoded, "invalid XCHG operand 0")
            if right.type == X86_OP_REG:
                effects.append(
                    _RegisterEffect(
                        self._register_slice(right.reg, right.size * 8),
                        (self._operand_dependency(decoded, 0),),
                    )
                )
            elif right.type == X86_OP_MEM:
                writes.append(
                    MemoryWriteSpec(
                        "xchg-memory",
                        (self._operand_dependency(decoded, 0),),
                    )
                )
            else:
                raise self._flow_error(decoded, "invalid XCHG operand 1")
            if len(writes) > 1:
                raise self._flow_error(decoded, "memory-to-memory XCHG")
            return _InstructionValueFlow(
                tuple(effects),
                tuple(writes),
                join_overlapping_register_effects=True,
            )

        if decoded.id in _XADD_INSTRUCTIONS:
            if len(operands) != 2 or operands[1].type != X86_OP_REG:
                raise self._flow_error(decoded, "unexpected XADD form")
            destination_dep = self._operand_dependency(decoded, 0)
            source_dep = self._operand_dependency(decoded, 1)
            source_effect = _RegisterEffect(
                self._register_slice(operands[1].reg, operands[1].size * 8),
                (destination_dep,),
            )
            flag_effects = (
                _RegisterEffect(
                    self._named_register_slice("eflags"),
                    (destination_dep, source_dep),
                ),
            )
            if operands[0].type == X86_OP_MEM:
                return _InstructionValueFlow(
                    (source_effect, *flag_effects),
                    (
                        MemoryWriteSpec(
                            "xadd-memory", (destination_dep, source_dep)
                        ),
                    ),
                    join_overlapping_register_effects=True,
                )
            if operands[0].type != X86_OP_REG:
                raise self._flow_error(decoded, "invalid XADD destination")
            return _InstructionValueFlow(
                (
                    _RegisterEffect(
                        self._register_slice(
                            operands[0].reg, operands[0].size * 8
                        ),
                        (destination_dep, source_dep),
                    ),
                    source_effect,
                    *flag_effects,
                ),
                join_overlapping_register_effects=True,
            )

        if decoded.id in _CMPXCHG_INSTRUCTIONS:
            if decoded.id in {113, 115}:
                if len(operands) != 1 or operands[0].type != X86_OP_MEM:
                    raise self._flow_error(
                        decoded, "unexpected CMPXCHG8B/16B form"
                    )
                payload_names = ("ebx", "ecx") if decoded.id == 115 else (
                    "rbx",
                    "rcx",
                )
                accumulator_names = (
                    ("eax", "edx") if decoded.id == 115 else ("rax", "rdx")
                )
                memory_dep = self._memory_dependency(0)
                return _InstructionValueFlow(
                    (
                        *tuple(
                            _RegisterEffect(
                                self._named_register_slice(name),
                                (
                                    _ValueDependency(
                                        "register",
                                        register=self._named_register_slice(
                                            name
                                        ),
                                    ),
                                    memory_dep,
                                ),
                            )
                            for name in accumulator_names
                        ),
                        _RegisterEffect(
                            self._named_register_slice("eflags"),
                            tuple(
                                _ValueDependency(
                                    "register",
                                    register=self._named_register_slice(name),
                                )
                                for name in accumulator_names
                            )
                            + (memory_dep,),
                        ),
                    ),
                    (
                        MemoryWriteSpec(
                            "cmpxchg-wide-memory",
                            tuple(
                                _ValueDependency(
                                    "register",
                                    register=self._named_register_slice(name),
                                )
                                for name in payload_names
                            ),
                        ),
                    ),
                )
            if len(operands) != 2:
                raise self._flow_error(decoded, "unexpected CMPXCHG form")
            destination, source = operands
            width = destination.size * 8
            accumulator_name = {8: "al", 16: "ax", 32: "eax", 64: "rax"}.get(
                width
            )
            if accumulator_name is None or source.type != X86_OP_REG:
                raise self._flow_error(decoded, "unsupported CMPXCHG width/form")
            accumulator = self._named_register_slice(accumulator_name)
            destination_dep = self._operand_dependency(decoded, 0)
            source_dep = self._operand_dependency(decoded, 1)
            accumulator_dep = _ValueDependency("register", register=accumulator)
            effects = [
                _RegisterEffect(
                    accumulator, (accumulator_dep, destination_dep)
                )
            ]
            writes: tuple[MemoryWriteSpec, ...] = ()
            if destination.type == X86_OP_MEM:
                writes = (
                    MemoryWriteSpec("cmpxchg-memory", (source_dep,)),
                )
            elif destination.type == X86_OP_REG:
                destination_slice = self._register_slice(
                    destination.reg, width
                )
                if destination_slice.family == accumulator.family and (
                    destination_slice.mask & accumulator.mask
                ):
                    if destination_slice.mask != accumulator.mask:
                        raise self._flow_error(
                            decoded,
                            "partially overlapping CMPXCHG accumulator "
                            "destination",
                        )
                    effects = [
                        _RegisterEffect(accumulator, (source_dep,))
                    ]
                else:
                    effects.append(
                        _RegisterEffect(
                            destination_slice, (destination_dep, source_dep)
                        )
                    )
            else:
                raise self._flow_error(decoded, "invalid CMPXCHG destination")
            effects.append(
                _RegisterEffect(
                    self._named_register_slice("eflags"),
                    (accumulator_dep, destination_dep),
                )
            )
            return _InstructionValueFlow(
                tuple(effects),
                writes,
                join_overlapping_register_effects=True,
            )

        if decoded.id in _MASKMOV_IMPLICIT_WRITERS:
            if (
                len(operands) != 2
                or any(operand.type != X86_OP_REG for operand in operands)
            ):
                raise self._flow_error(decoded, "unexpected MASKMOV form")
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "maskmov-implicit-edi",
                        (self._operand_dependency(decoded, 0),),
                    ),
                )
            )

        if decoded.id == X86_INS_ENTER:
            if len(operands) != 2 or any(
                operand.type != X86_OP_IMM for operand in operands
            ):
                raise self._flow_error(decoded, "unexpected ENTER form")
            ebp = self._named_register_slice("ebp")
            esp = self._named_register_slice("esp")
            return _InstructionValueFlow(
                register_effects=(
                    _RegisterEffect(
                        ebp, (_ValueDependency("register", register=esp),)
                    ),
                ),
                memory_writes=(
                    MemoryWriteSpec(
                        "enter-frame-link",
                        (_ValueDependency("register", register=ebp),),
                    ),
                ),
            )

        if decoded.id in _PUSH_INSTRUCTIONS:
            if len(operands) != 1:
                raise self._flow_error(decoded, "unexpected PUSH form")
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "push", (self._operand_dependency(decoded, 0),)
                    ),
                )
            )
        if decoded.id in _PUSHA_INSTRUCTIONS:
            width_names = (
                ("ax", "cx", "dx", "bx", "sp", "bp", "si", "di")
                if decoded.id == 610
                else (
                    "eax",
                    "ecx",
                    "edx",
                    "ebx",
                    "esp",
                    "ebp",
                    "esi",
                    "edi",
                )
            )
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "pusha",
                        tuple(
                            _ValueDependency(
                                "register",
                                register=self._named_register_slice(name),
                            )
                            for name in width_names
                        ),
                    ),
                )
            )
        if decoded.id in _PUSHF_INSTRUCTIONS:
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "pushf",
                        (
                            _ValueDependency(
                                "register",
                                register=self._named_register_slice("eflags"),
                            ),
                        ),
                    ),
                )
            )

        if decoded.id == 585:
            if len(operands) != 1:
                raise self._flow_error(decoded, "unexpected POP form")
            if operands[0].type == X86_OP_REG:
                return _InstructionValueFlow(
                    register_effects=(
                        _RegisterEffect(
                            self._register_slice(
                                operands[0].reg, operands[0].size * 8
                            ),
                            (self._memory_dependency(0),),
                        ),
                    )
                )
            if operands[0].type == X86_OP_MEM:
                return _InstructionValueFlow(
                    memory_writes=(
                        MemoryWriteSpec(
                            "pop-memory", (self._memory_dependency(0),)
                        ),
                    )
                )
            raise self._flow_error(decoded, "invalid POP destination")
        if decoded.id in {586, 587}:
            names = (
                ("ax", "cx", "dx", "bx", "bp", "si", "di")
                if decoded.id == 586
                else ("eax", "ecx", "edx", "ebx", "ebp", "esi", "edi")
            )
            return _InstructionValueFlow(
                register_effects=tuple(
                    _RegisterEffect(self._named_register_slice(name), ())
                    for name in names
                )
            )
        if decoded.id in _POPF_INSTRUCTIONS:
            return _InstructionValueFlow(
                register_effects=(
                    _RegisterEffect(self._named_register_slice("eflags"), ()),
                )
            )
        if decoded.id == 333:  # LEAVE
            ebp = self._named_register_slice("ebp")
            return _InstructionValueFlow(
                register_effects=(
                    _RegisterEffect(
                        self._named_register_slice("esp"),
                        (_ValueDependency("register", register=ebp),),
                    ),
                    _RegisterEffect(ebp, (self._memory_dependency(0),)),
                )
            )

        if decoded.id in _STOS_INSTRUCTIONS:
            if len(operands) != 2 or operands[1].type != X86_OP_REG:
                raise self._flow_error(decoded, "unexpected STOS form")
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "stos", (self._operand_dependency(decoded, 1),)
                    ),
                )
            )
        if decoded.id in _MOVS_INSTRUCTIONS:
            if (
                len(operands) != 2
                or operands[0].type != X86_OP_MEM
                or operands[1].type != X86_OP_MEM
            ):
                raise self._flow_error(decoded, "unexpected MOVS form")
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec("movs", (self._memory_dependency(1),)),
                )
            )
        if decoded.id in _LODS_INSTRUCTIONS:
            if (
                len(operands) != 2
                or operands[0].type != X86_OP_REG
                or operands[1].type != X86_OP_MEM
            ):
                raise self._flow_error(decoded, "unexpected LODS form")
            return _InstructionValueFlow(
                register_effects=(
                    _RegisterEffect(
                        self._register_slice(
                            operands[0].reg, operands[0].size * 8
                        ),
                        (self._memory_dependency(1),),
                    ),
                )
            )
        if decoded.id in _INS_INSTRUCTIONS:
            return _InstructionValueFlow(
                memory_writes=(MemoryWriteSpec("ins-external-input", ()),)
            )
        if decoded.id in _OUTS_INSTRUCTIONS:
            return _InstructionValueFlow()

        if decoded.id in _FNSAVE_WRITERS:
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "fnsave-state", self._state_save_dependencies("fnsave")
                    ),
                )
            )
        if decoded.id in _X87_VALUE_WRITERS:
            if len(operands) != 1 or operands[0].type != X86_OP_MEM:
                raise self._flow_error(
                    decoded, "unexpected x87 memory-store form"
                )
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "x87-value-store",
                        (
                            _ValueDependency(
                                "register",
                                register=_RegisterSlice(
                                    family="fp:0",
                                    mask=(1 << 80) - 1,
                                    name="st(0)",
                                ),
                            ),
                        ),
                    ),
                )
            )
        if decoded.id in _X87_CONTROL_WRITERS and operands and (
            operands[0].type == X86_OP_MEM
        ):
            register_name = _X87_CONTROL_WRITERS[decoded.id]
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "x87-control-store",
                        (
                            _ValueDependency(
                                "register",
                                register=self._named_register_slice(
                                    register_name
                                ),
                            ),
                        ),
                    ),
                )
            )
        if decoded.id in _FXSAVE_WRITERS:
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "fxsave-state", self._state_save_dependencies("fxsave")
                    ),
                )
            )
        if decoded.id in _XSAVE_WRITERS:
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "xsave-state", self._state_save_dependencies("xsave")
                    ),
                )
            )

        if decoded.id in _CET_MEMORY_WRITERS:
            if (
                len(operands) != 2
                or operands[0].type != X86_OP_MEM
                or operands[1].type != X86_OP_REG
            ):
                raise self._flow_error(decoded, "unexpected CET write form")
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "cet-shadow-stack",
                        (self._operand_dependency(decoded, 1),),
                    ),
                )
            )

        if decoded.id in _SCATTER_WRITERS:
            if (
                len(operands) != 3
                or operands[0].type != X86_OP_MEM
                or operands[1].type != X86_OP_REG
                or operands[2].type != X86_OP_REG
            ):
                raise self._flow_error(decoded, "unexpected scatter-store form")
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec(
                        "scatter-store",
                        (
                            self._operand_dependency(
                                decoded,
                                2,
                                max_width_bits=operands[0].size * 8,
                            ),
                        ),
                    ),
                )
            )

        if decoded.id in _NO_TRACKED_PAYLOAD_MEMORY_WRITERS:
            return _InstructionValueFlow(
                memory_writes=(
                    MemoryWriteSpec("audited-non-pointer-payload", ()),
                )
            )
        if decoded.id in _NON_WRITER_EXCLUSIONS:
            return _InstructionValueFlow()

        explicit_inputs: list[_ValueDependency] = []
        explicit_effects: list[_RegisterEffect] = []
        memory_write_indices: list[int] = []
        for index, operand in enumerate(operands):
            if operand.type == X86_OP_REG:
                if operand.access & CS_AC_READ:
                    explicit_inputs.append(
                        self._operand_dependency(decoded, index)
                    )
                if operand.access & CS_AC_WRITE:
                    explicit_effects.append(
                        self._explicit_register_effect(decoded, operand, ())
                    )
                if operand.access == 0:
                    if operand.reg not in decoded.regs_read:
                        raise self._flow_error(
                            decoded,
                            f"register operand {index} has access=0",
                        )
            elif operand.type == X86_OP_MEM:
                if operand.access & CS_AC_READ:
                    explicit_inputs.append(self._memory_dependency(index))
                if operand.access & CS_AC_WRITE:
                    memory_write_indices.append(index)
                if operand.access == 0:
                    raise self._flow_error(
                        decoded, f"memory operand {index} has access=0"
                    )
            elif operand.type == X86_OP_IMM:
                explicit_inputs.append(
                    self._immediate_dependency(operand.imm, index)
                )
            else:
                raise self._flow_error(
                    decoded, f"operand {index} has unsupported type"
                )

        if (
            decoded.id in _MEMORY_DESTINATION_ACCESS_OVERRIDES
            and operands
            and operands[0].type == X86_OP_MEM
        ):
            if 0 not in memory_write_indices:
                memory_write_indices.append(0)

        implicit_inputs = self._implicit_dependency_slices(decoded)
        dependencies = tuple((*explicit_inputs, *implicit_inputs))
        effects = [
            _RegisterEffect(
                effect.destination, dependencies, effect.taint_mask
            )
            for effect in explicit_effects
        ]
        for register in decoded.regs_write:
            implicit_output = self._register_slice(register)
            overlaps = [
                effect.destination
                for effect in explicit_effects
                if effect.destination.family == implicit_output.family
                and bool(effect.destination.mask & implicit_output.mask)
            ]
            if overlaps:
                if any(output.mask != implicit_output.mask for output in overlaps):
                    raise self._flow_error(
                        decoded,
                        "explicit/implicit output metadata disagree: "
                        f"register={implicit_output.name}",
                    )
                continue
            effects.append(_RegisterEffect(implicit_output, dependencies))

        if len(memory_write_indices) > 1:
            raise self._flow_error(decoded, "multiple memory destinations")
        writes: tuple[MemoryWriteSpec, ...] = ()
        if memory_write_indices:
            destination_index = memory_write_indices[0]
            destination_width = operands[destination_index].size * 8
            if decoded.id in _MASKED_EXPLICIT_WRITERS:
                if len(operands) != 3 or operands[2].type != X86_OP_REG:
                    raise self._flow_error(
                        decoded, "unexpected masked-store form"
                    )
                payload_dependencies = (
                    self._operand_dependency(decoded, 2),
                )
            elif decoded.id in _SCALAR_EXTRACT_WIDTHS:
                if (
                    len(operands) != 3
                    or operands[1].type != X86_OP_REG
                    or operands[2].type != X86_OP_IMM
                ):
                    raise self._flow_error(
                        decoded, "unexpected scalar-extract store form"
                    )
                width = _SCALAR_EXTRACT_WIDTHS[decoded.id]
                lane_count = max(1, (operands[1].size * 8) // width)
                lane = operands[2].imm % lane_count
                payload_dependencies = (
                    self._register_subslice_dependency(
                        decoded, 1, lane * width, width
                    ),
                )
            elif decoded.id in _VECTOR_EXTRACT_WIDTHS:
                if (
                    len(operands) != 3
                    or operands[1].type != X86_OP_REG
                    or operands[2].type != X86_OP_IMM
                ):
                    raise self._flow_error(
                        decoded, "unexpected vector-extract store form"
                    )
                width = _VECTOR_EXTRACT_WIDTHS[decoded.id]
                lane_count = max(1, (operands[1].size * 8) // width)
                lane = operands[2].imm % lane_count
                payload_dependencies = (
                    self._register_subslice_dependency(
                        decoded, 1, lane * width, width
                    ),
                )
            elif decoded.id in _HIGH_HALF_WRITERS:
                source_indices = [
                    index
                    for index, operand in enumerate(operands)
                    if index != destination_index and operand.type == X86_OP_REG
                ]
                if len(source_indices) != 1:
                    raise self._flow_error(
                        decoded, "unexpected high-half store form"
                    )
                payload_dependencies = (
                    self._register_subslice_dependency(
                        decoded, source_indices[0], 64, 64
                    ),
                )
            elif decoded.id in _LOW_LANE_WRITERS:
                source_indices = [
                    index
                    for index, operand in enumerate(operands)
                    if index != destination_index and operand.type == X86_OP_REG
                ]
                if len(source_indices) != 1:
                    raise self._flow_error(
                        decoded, "unexpected low-lane store form"
                    )
                payload_dependencies = (
                    self._register_subslice_dependency(
                        decoded,
                        source_indices[0],
                        0,
                        destination_width,
                    ),
                )
            else:
                payload_dependencies = tuple(
                    self._operand_dependency(decoded, index)
                    for index, operand in enumerate(operands)
                    if index != destination_index
                    and (
                        operand.type == X86_OP_IMM
                        or bool(operand.access & CS_AC_READ)
                    )
                )
                payload_dependencies = (
                    *payload_dependencies,
                    *implicit_inputs,
                )
            writes = (
                MemoryWriteSpec("explicit-memory-destination", payload_dependencies),
            )
        return _InstructionValueFlow(tuple(effects), writes)

    @staticmethod
    def _x87_slot(family: str, prefix: str) -> int | None:
        if not family.startswith(prefix):
            return None
        rendered = family.removeprefix(prefix)
        if not rendered.isdigit() or not 0 <= int(rendered) < 8:
            raise CfgRecoveryError(f"invalid x87 register family: {family}")
        return int(rendered)

    @staticmethod
    def _possible_tops(top_mask: int) -> tuple[int, ...]:
        return tuple(top for top in range(8) if top_mask & (1 << top))

    @staticmethod
    def _join_x87_states(states: tuple[_X87State, ...]) -> _X87State:
        if not states:
            raise CfgRecoveryError("cannot join an empty x87 state set")
        physical = [0] * 8
        top_mask = 0
        valid_must = 0xFF
        valid_may = 0
        for state in states:
            for index, taint in enumerate(state.phys_taint):
                physical[index] |= taint
            top_mask |= state.top_mask
            valid_must &= state.valid_must
            valid_may |= state.valid_may
        return _X87State(
            tuple(physical), top_mask, valid_must, valid_may
        )

    @classmethod
    def _join_taint_states(
        cls, left: _TaintState, right: _TaintState
    ) -> _TaintState:
        registers = dict(left.registers)
        for family, mask in right.registers.items():
            registers[family] = registers.get(family, 0) | mask
        return _TaintState(
            registers, cls._join_x87_states((left.x87, right.x87))
        )

    @staticmethod
    def _x87_pop(
        physical: list[int],
        top: int,
        valid_must: int,
        valid_may: int,
        count: int,
    ) -> tuple[list[int], int, int, int]:
        for _ in range(count):
            slot_mask = 1 << top
            valid_must &= ~slot_mask
            valid_may &= ~slot_mask
            top = (top + 1) & 7
        return physical, top, valid_must, valid_may

    def _dependency_is_tainted(
        self,
        dependency: _ValueDependency,
        state: _TaintState,
        *,
        exact_top: int | None = None,
    ) -> bool:
        if dependency.kind in {"register", "address-register"}:
            if dependency.register is None:
                raise CfgRecoveryError("register dependency has no slice")
            physical_slot = self._x87_slot(
                dependency.register.family, "x87-physical:"
            )
            if physical_slot is not None:
                return bool(
                    state.x87.phys_taint[physical_slot]
                    & dependency.register.mask
                )
            logical_index = self._x87_slot(
                dependency.register.family, "x87-logical:"
            )
            if logical_index is not None:
                tops = (
                    (exact_top,)
                    if exact_top is not None
                    else self._possible_tops(state.x87.top_mask)
                )
                for top in tops:
                    physical_slot = (top + logical_index) & 7
                    if not state.x87.valid_may & (1 << physical_slot):
                        continue
                    if (
                        state.x87.phys_taint[physical_slot]
                        & dependency.register.mask
                    ):
                        return True
                return False
            return bool(
                state.registers.get(dependency.register.family, 0)
                & dependency.register.mask
            )
        if dependency.kind in {"immediate", "address-immediate"}:
            if dependency.value is None:
                raise CfgRecoveryError("immediate dependency has no value")
            return _is_executable_span(self.image, dependency.value, 1)
        if dependency.kind == "memory":
            return False
        raise CfgRecoveryError(
            f"unmodeled x86 value dependency kind: {dependency.kind}"
        )

    def _instruction_uses_mmx(self, decoded) -> bool:
        registers = {
            operand.reg
            for operand in decoded.operands
            if operand.type == X86_OP_REG
        }
        registers.update(decoded.regs_read)
        registers.update(decoded.regs_write)
        return any(
            re.fullmatch(r"mm[0-7]", self.decoder.reg_name(register))
            for register in registers
        )

    def _apply_x87_effect(
        self,
        decoded,
        effect: _X87Effect,
        state: _TaintState,
    ) -> _X87State:
        old = state.x87
        if effect.kind == "empty-tags":
            return _X87State(old.phys_taint, old.top_mask, 0, 0)
        if effect.kind == "init":
            return _X87State(old.phys_taint, 1, 0, 0)
        if effect.kind == "load-environment":
            return _X87State(old.phys_taint, 0xFF, 0, 0xFF)
        if effect.kind == "restore":
            return _X87State.clean_unknown()
        if effect.kind == "rotate-top":
            rotated = 0
            for top in self._possible_tops(old.top_mask):
                rotated |= 1 << ((top + effect.target) & 7)
            return _X87State(
                old.phys_taint, rotated, old.valid_must, old.valid_may
            )

        tops = self._possible_tops(old.top_mask)
        if len(tops) > 1 and any(old.phys_taint):
            raise self._flow_error(
                decoded,
                "ambiguous x87 TOP with tainted physical payload: "
                f"effect={effect.kind};top-mask={old.top_mask:#04x};"
                f"valid-must={old.valid_must:#04x};"
                f"valid-may={old.valid_may:#04x}",
            )

        branches: list[_X87State] = []
        for top in tops:
            physical = list(old.phys_taint)
            valid_must = old.valid_must
            valid_may = old.valid_may
            next_top = top

            if effect.kind == "push":
                next_top = (top - 1) & 7
                physical[next_top] = (
                    (1 << 80) - 1
                    if any(
                        self._dependency_is_tainted(
                            dependency, state, exact_top=top
                        )
                        for dependency in effect.dependencies
                    )
                    else 0
                )
                valid_must |= 1 << next_top
                valid_may |= 1 << next_top
            elif effect.kind == "swap":
                other_slot = (top + effect.target) & 7
                physical[top], physical[other_slot] = (
                    physical[other_slot],
                    physical[top],
                )
                top_bit = bool(valid_must & (1 << top))
                other_bit = bool(valid_must & (1 << other_slot))
                valid_must &= ~((1 << top) | (1 << other_slot))
                if top_bit:
                    valid_must |= 1 << other_slot
                if other_bit:
                    valid_must |= 1 << top
                top_bit = bool(valid_may & (1 << top))
                other_bit = bool(valid_may & (1 << other_slot))
                valid_may &= ~((1 << top) | (1 << other_slot))
                if top_bit:
                    valid_may |= 1 << other_slot
                if other_bit:
                    valid_may |= 1 << top
            elif effect.kind in {"store-register", "arithmetic"}:
                destination = (top + effect.target) & 7
                physical[destination] = (
                    (1 << 80) - 1
                    if any(
                        self._dependency_is_tainted(
                            dependency, state, exact_top=top
                        )
                        for dependency in effect.dependencies
                    )
                    else 0
                )
                valid_must |= 1 << destination
                valid_may |= 1 << destination
                physical, next_top, valid_must, valid_may = self._x87_pop(
                    physical,
                    next_top,
                    valid_must,
                    valid_may,
                    effect.pop_count,
                )
            elif effect.kind == "pop":
                physical, next_top, valid_must, valid_may = self._x87_pop(
                    physical,
                    next_top,
                    valid_must,
                    valid_may,
                    effect.pop_count,
                )
            elif effect.kind == "free":
                destination = (top + effect.target) & 7
                valid_must &= ~(1 << destination)
                valid_may &= ~(1 << destination)
                physical, next_top, valid_must, valid_may = self._x87_pop(
                    physical,
                    next_top,
                    valid_must,
                    valid_may,
                    effect.pop_count,
                )
            else:
                raise self._flow_error(
                    decoded, f"unmodeled x87 state effect: {effect.kind}"
                )
            branches.append(
                _X87State(
                    tuple(physical),
                    1 << next_top,
                    valid_must,
                    valid_may,
                )
            )
        return self._join_x87_states(tuple(branches))

    def _apply_instruction_value_flow(
        self, decoded, state: _TaintState
    ) -> _TaintState:
        flow = self._instruction_value_flow(decoded)
        if flow.taint_blocker_reason is not None and any(
            self._dependency_is_tainted(dependency, state)
            for dependency in flow.taint_blocker_dependencies
        ):
            raise self._flow_error(decoded, flow.taint_blocker_reason)
        if decoded.address not in self.accepted_initializer_instructions:
            for write in flow.memory_writes:
                if any(
                    self._dependency_is_tainted(dependency, state)
                    for dependency in write.dependencies
                ):
                    raise CfgRecoveryError(
                        "unresolved function-pointer initializer: "
                        "unsupported semantic memory write of an executable "
                        f"value at {decoded.address:#x};"
                        f"classification={write.classification}"
                    )

        written_masks: dict[str, int] = {}
        for effect in flow.register_effects:
            overlap = written_masks.get(effect.destination.family, 0) & (
                effect.destination.mask
            )
            if overlap and not flow.join_overlapping_register_effects:
                raise self._flow_error(
                    decoded,
                    "overlapping simultaneous register effects: "
                    f"family={effect.destination.family};mask={overlap:#x}",
                )
            written_masks[effect.destination.family] = (
                written_masks.get(effect.destination.family, 0)
                | effect.destination.mask
            )

        old_state = state
        next_registers = dict(old_state.registers)
        next_x87 = old_state.x87
        for family, mask in written_masks.items():
            if family.startswith(("x87-physical:", "x87-logical:")):
                continue
            remaining = next_registers.get(family, 0) & ~mask
            if remaining:
                next_registers[family] = remaining
            else:
                next_registers.pop(family, None)

        physical = list(next_x87.phys_taint)
        wrote_physical = False
        for effect in flow.register_effects:
            physical_slot = self._x87_slot(
                effect.destination.family, "x87-physical:"
            )
            if physical_slot is None:
                continue
            taint_mask = (
                effect.destination.mask
                if effect.taint_mask is None
                else effect.taint_mask
            )
            if (
                effect.destination.mask != _MMX_PAYLOAD_MASK
                or taint_mask != _MMX_PAYLOAD_MASK
            ):
                raise self._flow_error(
                    decoded,
                    "partial or ambiguous MMX destination effect: "
                    f"register={effect.destination.name};"
                    f"written-mask={effect.destination.mask:#x};"
                    f"taint-mask={taint_mask:#x}",
                )
            wrote_physical = True
            physical[physical_slot] &= ~_X87_PHYSICAL_PAYLOAD_MASK
        for effect in flow.register_effects:
            taint_mask = (
                effect.destination.mask
                if effect.taint_mask is None
                else effect.taint_mask
            )
            if taint_mask & ~effect.destination.mask:
                raise self._flow_error(
                    decoded,
                    "register effect taint lanes exceed written lanes: "
                    f"register={effect.destination.name}",
                )
            is_tainted = any(
                self._dependency_is_tainted(dependency, old_state)
                for dependency in effect.dependencies
            )
            physical_slot = self._x87_slot(
                effect.destination.family, "x87-physical:"
            )
            logical_slot = self._x87_slot(
                effect.destination.family, "x87-logical:"
            )
            if logical_slot is not None:
                raise self._flow_error(
                    decoded,
                    "generic value flow attempted a logical x87 write: "
                    f"register={effect.destination.name}",
                )
            if physical_slot is not None:
                if is_tainted:
                    physical[physical_slot] |= taint_mask
            elif is_tainted:
                next_registers[effect.destination.family] = (
                    next_registers.get(effect.destination.family, 0)
                    | taint_mask
                )
        if wrote_physical or self._instruction_uses_mmx(decoded):
            # Every MMX instruction transitions the shared register file into
            # MMX state: TOP=0 and every physical tag is valid.  EMMS later
            # empties the tags but deliberately preserves TOP and payload.
            next_x87 = _X87State(
                tuple(physical),
                1,
                0xFF,
                0xFF,
            )
        next_state = _TaintState(next_registers, next_x87)
        if flow.x87_effect is not None:
            next_state.x87 = self._apply_x87_effect(
                decoded, flow.x87_effect, old_state
            )
        self._check_count(
            "max_states_per_block", next_state.x87.top_mask.bit_count()
        )
        return next_state

    @staticmethod
    def _chain_step(instruction: Instruction) -> str:
        return f"{instruction.address:#x}:{instruction.bytes_hex}"

    def _exact_memory_address(
        self, memory, state: dict[str, _ExactValue]
    ) -> int | None:
        if (
            memory.segment != X86_REG_INVALID
            or memory.index != X86_REG_INVALID
        ):
            return None
        if memory.base == X86_REG_INVALID:
            return memory.disp & 0xFFFF_FFFF
        base = state.get(self._register_family(memory.base))
        if base is None:
            return None
        return (base.value + memory.disp) & 0xFFFF_FFFF

    def _record_data_operands(
        self, decoded, state: dict[str, _ExactValue]
    ) -> None:
        if (
            decoded.id == X86_INS_LEA
            or decoded.group(CS_GRP_CALL)
            or decoded.group(CS_GRP_JUMP)
        ):
            return
        instruction = self.instructions[decoded.address]
        for index, operand in enumerate(decoded.operands):
            if (
                operand.type != X86_OP_MEM
                or operand.size <= 0
                or not operand.access & CS_AC_READ
            ):
                continue
            address = self._exact_memory_address(operand.mem, state)
            if address is None:
                continue
            try:
                self.image.read(address, operand.size)
            except ValueError:
                continue
            self.data_evidence.add(
                _DataEvidence(
                    start=address,
                    end=address + operand.size,
                    provenance=(
                        f"instruction={instruction.address:#x};"
                        f"bytes={instruction.bytes_hex};operand={index};"
                        f"width={operand.size}"
                    ),
                )
            )

    def _initializer_value(
        self, operand, state: dict[str, _ExactValue]
    ) -> _ExactValue | None:
        if operand.type == X86_OP_IMM:
            value = operand.imm & 0xFFFF_FFFF
            self._record_finite_value(value)
            return _ExactValue(value, ())
        if operand.type == X86_OP_REG and operand.size == 4:
            return state.get(self._register_family(operand.reg))
        return None

    def _record_initializer(
        self,
        decoded,
        state: dict[str, _ExactValue],
    ) -> None:
        if (
            decoded.id in _PUSH_INSTRUCTIONS
            and len(decoded.operands) == 1
            and decoded.operands[0].type == X86_OP_IMM
            and decoded.imm_size == 4
        ):
            target = decoded.operands[0].imm & 0xFFFF_FFFF
            relocation_address = decoded.address + decoded.imm_offset
            if _is_executable_span(self.image, target, 1) and any(
                relocation.type == 3 and relocation.va == relocation_address
                for relocation in self.image.relocations
            ):
                instruction = self.instructions[decoded.address]
                record = SeedRecord(
                    address=target,
                    category="function-pointer-initializer",
                    provenance_address=instruction.address,
                    provenance_bytes=instruction.bytes_hex,
                    detail=(
                        "stack-argument-or-handler;"
                        f"i386-relocation={relocation_address:#x};"
                        f"propagation-chain={self._chain_step(instruction)}"
                    ),
                )
                initializer_key = (
                    record.address,
                    record.provenance_address,
                )
                if initializer_key not in self.produced_initializers:
                    self.produced_initializers.add(initializer_key)
                    self._record_fixpoint_update()
                self.seed_records.add(record)
                self.accepted_initializer_instructions.add(
                    instruction.address
                )
                self._record_finite_target(target)
                self._enqueue(target, is_function=True)
            return
        if decoded.id != X86_INS_MOV or len(decoded.operands) != 2:
            return
        destination, source = decoded.operands
        if destination.type != X86_OP_MEM:
            return
        exact_value = self._initializer_value(source, state)
        if exact_value is None or not _is_executable_span(
            self.image, exact_value.value, 1
        ):
            return

        destination_address = self._exact_memory_address(
            destination.mem, state
        )
        destination_is_valid = (
            destination_address is not None
            and _is_mapped_span(
                self.image, destination_address, destination.size
            )
        )
        relocation_proven_dynamic_field = (
            not destination_is_valid
            and destination.size == 4
            and source.type == X86_OP_IMM
            and destination.mem.segment == X86_REG_INVALID
            and destination.mem.base != X86_REG_INVALID
            and destination.mem.index == X86_REG_INVALID
            and destination.mem.disp != 0
            and decoded.imm_size == 4
            and any(
                relocation.type == 3
                and relocation.va == decoded.address + decoded.imm_offset
                for relocation in self.image.relocations
            )
        )
        if (
            (not destination_is_valid and not relocation_proven_dynamic_field)
            or destination.size != 4
            or (
                destination_address is not None
                and _is_executable_span(self.image, destination_address, 4)
            )
        ):
            raise CfgRecoveryError(
                "unresolved function-pointer initializer: "
                f"store at {decoded.address:#x}"
            )

        instruction = self.instructions[decoded.address]
        chain = (*exact_value.chain, self._chain_step(instruction))
        record = SeedRecord(
            address=exact_value.value,
            category="function-pointer-initializer",
            provenance_address=instruction.address,
            provenance_bytes=instruction.bytes_hex,
            detail=(
                (
                    f"store-ea={destination_address:#x};"
                    if destination_address is not None
                    else "store-ea=dynamic-relocation-proven-field;"
                )
                + f"propagation-chain={'>'.join(chain)}"
            ),
        )
        initializer_key = (record.address, record.provenance_address)
        if initializer_key not in self.produced_initializers:
            self.produced_initializers.add(initializer_key)
            self._record_fixpoint_update()
        self.seed_records.add(record)
        self.accepted_initializer_instructions.add(instruction.address)
        self._record_finite_target(exact_value.value)
        self._enqueue(exact_value.value, is_function=True)

    def _update_exact_state(
        self, decoded, state: dict[str, _ExactValue]
    ) -> None:
        instruction = self.instructions[decoded.address]
        step = self._chain_step(instruction)
        if decoded.group(CS_GRP_CALL):
            state.clear()
            return
        if len(decoded.operands) == 2:
            destination, source = decoded.operands
            if destination.type == X86_OP_REG and destination.size == 4:
                family = self._register_family(destination.reg)
                if decoded.id == X86_INS_MOV and source.type == X86_OP_IMM:
                    value = source.imm & 0xFFFF_FFFF
                    self._record_finite_value(value)
                    state[family] = _ExactValue(value, (step,))
                    return
                if (
                    decoded.id == X86_INS_LEA
                    and source.type == X86_OP_MEM
                    and source.mem.segment == X86_REG_INVALID
                    and source.mem.base == X86_REG_INVALID
                    and source.mem.index == X86_REG_INVALID
                ):
                    value = source.mem.disp & 0xFFFF_FFFF
                    self._record_finite_value(value)
                    state[family] = _ExactValue(value, (step,))
                    return
                if (
                    decoded.id == X86_INS_MOV
                    and source.type == X86_OP_REG
                    and source.size == 4
                ):
                    source_value = state.get(
                        self._register_family(source.reg)
                    )
                    if source_value is None:
                        state.pop(family, None)
                    else:
                        state[family] = _ExactValue(
                            source_value.value,
                            (*source_value.chain, step),
                        )
                    return

        written = {
            operand.reg
            for operand in decoded.operands
            if operand.type == X86_OP_REG and operand.access & CS_AC_WRITE
        }
        written.update(decoded.regs_write)
        if decoded.id in _CMPXCHG_INSTRUCTIONS:
            if decoded.id == 115:
                written.update(
                    {
                        x86_const.X86_REG_EAX,
                        x86_const.X86_REG_EDX,
                    }
                )
            elif decoded.id == 113:
                written.update(
                    {
                        x86_const.X86_REG_RAX,
                        x86_const.X86_REG_RDX,
                    }
                )
            elif decoded.operands:
                accumulator_name = {
                    1: "al",
                    2: "ax",
                    4: "eax",
                    8: "rax",
                }.get(decoded.operands[0].size)
                if accumulator_name is not None:
                    written.add(
                        getattr(
                            x86_const,
                            f"X86_REG_{accumulator_name.upper()}",
                        )
                    )
        for register in written:
            state.pop(self._register_family(register), None)

    def _scan_owned_blocks(
        self, blocks: tuple[BasicBlock, ...]
    ) -> None:
        previous_initializers = {
            (record.address, record.provenance_address)
            for record in self.seed_records
            if record.category == "function-pointer-initializer"
        }
        self.seed_records = {
            record
            for record in self.seed_records
            if record.category != "function-pointer-initializer"
        }
        self.data_evidence = set(self.structural_data_evidence) | {
            _DataEvidence(
                start=table.base + table.index_min * table.entry_width,
                end=table.base + (table.index_max + 1) * table.entry_width,
                provenance=(
                    f"guard={table.guard_address:#x};"
                    f"operator={table.guard_operator};"
                    f"bound={table.guard_bound};transfer={table.address:#x}"
                ),
            )
            for table in self.jump_tables.values()
        }
        self.accepted_initializer_instructions = set()
        for block in blocks:
            self._check_count("max_states_per_block", 1)
            state: dict[str, _ExactValue] = {}
            for address in block.instruction_addresses:
                decoded = self._owned_decoded(address)
                self._record_data_operands(decoded, state)
                self._record_initializer(decoded, state)
                self._update_exact_state(decoded, state)

        current_initializers = {
            (record.address, record.provenance_address)
            for record in self.seed_records
            if record.category == "function-pointer-initializer"
        }
        if not previous_initializers <= current_initializers:
            raise CfgRecoveryError(
                "unresolved function-pointer initializer: "
                "propagation crosses an owned basic-block boundary"
            )

        self._reject_unsafe_initializer_taint(blocks)
        self._classify_relocations()

    def _reject_unsafe_initializer_taint(
        self, blocks: tuple[BasicBlock, ...]
    ) -> None:
        block_by_instruction = {
            address: block.start
            for block in blocks
            for address in block.instruction_addresses
        }
        successors: dict[int, set[int]] = {
            block.start: set() for block in blocks
        }
        for edge in self.edges:
            if edge.kind in {"direct-call", "indirect-call-table"}:
                continue
            source_block = block_by_instruction.get(edge.source)
            if source_block is not None and edge.target in successors:
                successors[source_block].add(edge.target)

        entries: dict[int, _TaintState | None] = {
            block.start: (
                _TaintState.empty()
                if block.start in self.function_addresses
                else None
            )
            for block in blocks
        }
        outputs: dict[int, _TaintState] = {}
        pending = [
            block_start
            for block_start, entry in entries.items()
            if entry is not None
        ]
        heapq.heapify(pending)
        queued = set(pending)
        blocks_by_start = {block.start: block for block in blocks}
        while pending:
            block_start = heapq.heappop(pending)
            queued.remove(block_start)
            block = blocks_by_start[block_start]
            entry = entries[block_start]
            if entry is None:
                raise CfgRecoveryError(
                    f"taint worklist reached bottom block: {block_start:#x}"
                )
            tainted = _TaintState(dict(entry.registers), entry.x87)
            for address in block.instruction_addresses:
                decoded = self._owned_decoded(address)
                tainted = self._apply_instruction_value_flow(
                    decoded, tainted
                )

            output = tainted
            if outputs.get(block_start) == output:
                continue
            outputs[block_start] = output
            for successor in sorted(successors[block_start]):
                successor_entry = entries[successor]
                updated = (
                    _TaintState(dict(output.registers), output.x87)
                    if successor_entry is None
                    else self._join_taint_states(successor_entry, output)
                )
                if updated == entries[successor]:
                    continue
                entries[successor] = updated
                self._record_fixpoint_update()
                if successor not in queued:
                    heapq.heappush(pending, successor)
                    queued.add(successor)

    def _instruction_relocation_field(
        self, instruction_address: int, start: int, end: int
    ) -> str:
        decoded = self._owned_decoded(instruction_address)
        fields = []
        for field_name, offset, size in (
            (
                "immediate",
                decoded.encoding.imm_offset,
                decoded.encoding.imm_size,
            ),
            (
                "displacement",
                decoded.encoding.disp_offset,
                decoded.encoding.disp_size,
            ),
        ):
            if (
                size == end - start
                and 0 <= offset <= decoded.size
                and size <= decoded.size - offset
                and instruction_address + offset == start
            ):
                fields.append(field_name)
        if len(fields) != 1:
            raise CfgRecoveryError(
                "executable relocation operand boundary is ambiguous: "
                f"relocation={start:#x}-{end:#x};"
                f"instruction={instruction_address:#x};"
                f"matching-fields={','.join(fields) or 'none'}"
            )
        return fields[0]

    def _classify_relocations(self) -> None:
        non_relocation_data = tuple(self.data_evidence)
        for relocation in self.image.relocations:
            width = _I386_RELOCATION_WIDTHS.get(relocation.type)
            if width is None:
                raise CfgRecoveryError(
                    "unsupported relocation width during data ownership: "
                    f"type={relocation.type}"
                )
            start = relocation.va
            end = start + width
            provenance = _read_provenance(
                self.image, start, width, "relocation provenance"
            )
            detail = (
                f"relocation={start:#x};type={relocation.type};"
                f"width={width};bytes={provenance.hex()}"
            )
            if not _is_executable_span(self.image, start, width):
                self.data_evidence.add(
                    _DataEvidence(start=start, end=end, provenance=detail)
                )
                continue

            owners = {
                self.byte_owners[address]
                for address in range(start, end)
                if address in self.byte_owners
            }
            if owners:
                if (
                    relocation.type != 3
                    or width != 4
                    or len(owners) != 1
                    or any(
                        self.byte_owners.get(address) not in owners
                        for address in range(start, end)
                    )
                ):
                    raise CfgRecoveryError(
                        "executable relocation crosses an instruction "
                        f"operand boundary: relocation={start:#x}-{end:#x}"
                    )
                instruction_address = next(iter(owners))
                field_name = self._instruction_relocation_field(
                    instruction_address, start, end
                )
                pointer = struct.unpack("<I", provenance)[0]
                if _is_executable_span(self.image, pointer, 1):
                    instruction = self.instructions[instruction_address]
                    record = SeedRecord(
                        address=pointer,
                        category="relocation-executable-pointer",
                        provenance_address=start,
                        provenance_bytes=provenance.hex(),
                        detail=(
                            f"i386-relocation-type-3;width=4;"
                            f"instruction={instruction.address:#x};"
                            f"instruction-bytes={instruction.bytes_hex};"
                            f"field={field_name}"
                        ),
                    )
                    if record not in self.seed_records:
                        self._record_fixpoint_update()
                    self.seed_records.add(record)
                    self._record_finite_target(pointer)
                    self._enqueue(pointer)
                continue

            containing_data = [
                evidence
                for evidence in non_relocation_data
                if evidence.start <= start and end <= evidence.end
            ]
            data_boundaries = {
                (evidence.start, evidence.end)
                for evidence in containing_data
            }
            if not data_boundaries:
                if self.pending:
                    continue
                raise CfgRecoveryError(
                    "executable relocation has no exact instruction or data "
                    f"boundary: relocation={start:#x}-{end:#x};"
                    "data-attributions=0"
                )
            if len(data_boundaries) != 1:
                raise CfgRecoveryError(
                    "executable relocation data boundary is ambiguous: "
                    f"relocation={start:#x}-{end:#x};"
                    f"attributions={len(containing_data)};"
                    f"boundaries={len(data_boundaries)}"
                )

            data_start, data_end = next(iter(data_boundaries))
            self.data_evidence.add(
                _DataEvidence(start=start, end=end, provenance=detail)
            )
            if relocation.type != 3 or width != 4:
                continue

            pointer = struct.unpack("<I", provenance)[0]
            if not _is_executable_span(self.image, pointer, 1):
                continue
            record = SeedRecord(
                address=pointer,
                category="relocation-executable-pointer",
                provenance_address=start,
                provenance_bytes=provenance.hex(),
                detail=(
                    "i386-relocation-type-3;width=4;"
                    f"data-boundary={data_start:#x}-{data_end:#x};"
                    f"data-attributions={len(containing_data)}"
                ),
            )
            if record not in self.seed_records:
                self._record_fixpoint_update()
            self.seed_records.add(record)
            self._record_finite_target(pointer)
            self._enqueue(pointer)

    def _merged_data_regions(self) -> tuple[ByteRegion, ...]:
        merged: list[ByteRegion] = []
        current_start: int | None = None
        current_end = 0
        provenance: set[str] = set()
        for evidence in sorted(
            self.data_evidence,
            key=lambda row: (row.start, row.end, row.provenance),
        ):
            if current_start is None:
                current_start = evidence.start
                current_end = evidence.end
                provenance = {evidence.provenance}
                continue
            if evidence.start <= current_end:
                current_end = max(current_end, evidence.end)
                provenance.add(evidence.provenance)
                continue
            merged.append(
                ByteRegion(
                    start=current_start,
                    end=current_end,
                    provenance="|".join(sorted(provenance)),
                )
            )
            current_start = evidence.start
            current_end = evidence.end
            provenance = {evidence.provenance}
        if current_start is not None:
            merged.append(
                ByteRegion(
                    start=current_start,
                    end=current_end,
                    provenance="|".join(sorted(provenance)),
                )
            )
        return tuple(merged)

    def _record_terminal_zero_alignment_evidence(self) -> None:
        """Own zero fill immediately before an independently proven function.

        Retail MWCC aligns many functions with zero bytes.  Zero is also a
        valid instruction encoding, so alignment is accepted only when the
        right boundary is an already proven, 16-byte-aligned function entry
        and the left boundary is an already owned return or unconditional
        jump.  The 32-byte bound matches relocation-derived alignment proof.
        """
        for entry in sorted(self.function_addresses):
            if entry % 16 or entry not in self.instructions:
                continue
            raw_range = next(
                (
                    (start, end)
                    for start, end in self._executable_raw_ranges()
                    if start <= entry < end
                ),
                None,
            )
            if raw_range is None:
                continue
            raw_start, _ = raw_range
            gap_start = entry
            while (
                gap_start > max(raw_start, entry - 32)
                and gap_start - 1 not in self.byte_owners
                and self.image.read(gap_start - 1, 1) == b"\0"
            ):
                gap_start -= 1
            if gap_start == entry:
                continue
            predecessor_owner = self.byte_owners.get(gap_start - 1)
            predecessor = (
                self.instructions.get(predecessor_owner)
                if predecessor_owner is not None
                else None
            )
            if (
                predecessor is None
                or predecessor.address + predecessor.size != gap_start
            ):
                continue
            decoded = self._owned_decoded(predecessor.address)
            if not (
                decoded.group(CS_GRP_RET)
                or decoded.group(CS_GRP_IRET)
                or (
                    decoded.group(CS_GRP_JUMP)
                    and decoded.id in {X86_INS_JMP, X86_INS_LJMP}
                )
            ):
                continue
            evidence = _DataEvidence(
                start=gap_start,
                end=entry,
                provenance=(
                    "terminal-zero-alignment;"
                    f"terminal={predecessor.address:#x}:"
                    f"{predecessor.mnemonic};entry={entry:#x};"
                    "alignment=16;max-gap=32"
                ),
            )
            self.structural_data_evidence.add(evidence)
            self.data_evidence.add(evidence)

    @staticmethod
    def _is_canonical_padding(blob: bytes) -> bool:
        if blob and not blob.strip(b"\0"):
            return True
        offset = 0
        while offset < len(blob):
            if blob[offset] == 0xCC:
                offset += 1
                continue
            encoding = next(
                (
                    encoding
                    for encoding in _CANONICAL_NOP_ENCODINGS
                    if blob.startswith(encoding, offset)
                ),
                None,
            )
            if encoding is None:
                return False
            offset += len(encoding)
        return bool(blob)

    def _padding_regions(
        self, data_regions: tuple[ByteRegion, ...]
    ) -> tuple[ByteRegion, ...]:
        regions: list[ByteRegion] = []

        def record_gap(
            left: Instruction,
            start: int,
            end: int,
            right_description: str,
        ) -> None:
            if start >= end or left.address not in self.terminators:
                return
            uncovered = [(start, end)]
            for data_region in data_regions:
                if data_region.end <= start or end <= data_region.start:
                    continue
                partitioned = []
                for part_start, part_end in uncovered:
                    if (
                        data_region.end <= part_start
                        or part_end <= data_region.start
                    ):
                        partitioned.append((part_start, part_end))
                        continue
                    if part_start < data_region.start:
                        partitioned.append((part_start, data_region.start))
                    if data_region.end < part_end:
                        partitioned.append((data_region.end, part_end))
                uncovered = partitioned
            for part_start, part_end in uncovered:
                blob = _read_provenance(
                    self.image,
                    part_start,
                    part_end - part_start,
                    "padding",
                )
                if not self._is_canonical_padding(blob):
                    continue
                regions.append(
                    ByteRegion(
                        start=part_start,
                        end=part_end,
                        provenance=(
                            f"unreachable-after={left.address:#x};"
                            f"{right_description};"
                            "encoding=canonical-x86-nop-or-int3"
                        ),
                    )
                )

        for raw_start, raw_end in self._executable_raw_ranges():
            instructions = sorted(
                (
                    instruction
                    for instruction in self.instructions.values()
                    if raw_start <= instruction.address < raw_end
                ),
                key=_instruction_key,
            )
            for left, right in zip(instructions, instructions[1:]):
                record_gap(
                    left,
                    left.address + left.size,
                    right.address,
                    f"before={right.address:#x}",
                )
            if instructions:
                left = instructions[-1]
                record_gap(
                    left,
                    left.address + left.size,
                    raw_end,
                    f"before-executable-raw-end={raw_end:#x}",
                )
        return tuple(sorted(regions, key=lambda row: (row.start, row.end)))

    def _executable_raw_ranges(self) -> tuple[tuple[int, int], ...]:
        return tuple(
            (section.va, section.va + section.raw_size)
            for section in self.image.sections
            if section.is_executable and section.raw_size
        )

    @staticmethod
    def _region_contains(
        regions: tuple[ByteRegion, ...], start: int, end: int
    ) -> bool:
        return any(
            region.start <= start and end <= region.end
            for region in regions
        )

    def _require_disjoint_ownership(
        self,
        data_regions: tuple[ByteRegion, ...],
        padding_regions: tuple[ByteRegion, ...],
    ) -> None:
        for region in data_regions:
            overlapping_owners = sorted(
                {
                    self.byte_owners[address]
                    for address in range(region.start, region.end)
                    if address in self.byte_owners
                }
            )
            if overlapping_owners:
                rendered = ",".join(
                    f"{address:#x}" for address in overlapping_owners
                )
                raise CfgRecoveryError(
                    "instruction/data ownership overlap: "
                    f"data={region.start:#x}-{region.end:#x};"
                    f"instructions={rendered}"
                )
        for data_region in data_regions:
            for padding_region in padding_regions:
                if (
                    data_region.start < padding_region.end
                    and padding_region.start < data_region.end
                ):
                    raise CfgRecoveryError(
                        "data/padding ownership overlap: "
                        f"data={data_region.start:#x}-{data_region.end:#x};"
                        "padding="
                        f"{padding_region.start:#x}-{padding_region.end:#x}"
                    )
        for padding_region in padding_regions:
            overlapping_owners = sorted(
                {
                    self.byte_owners[address]
                    for address in range(
                        padding_region.start, padding_region.end
                    )
                    if address in self.byte_owners
                }
            )
            if overlapping_owners:
                rendered = ",".join(
                    f"{address:#x}" for address in overlapping_owners
                )
                raise CfgRecoveryError(
                    "instruction/padding ownership overlap: "
                    f"padding={padding_region.start:#x}-"
                    f"{padding_region.end:#x};instructions={rendered}"
                )

    def _raw_e8_candidates(
        self,
        data_regions: tuple[ByteRegion, ...],
        padding_regions: tuple[ByteRegion, ...],
    ) -> tuple[RawE8Candidate, ...]:
        candidates = []
        for start, end in self._executable_raw_ranges():
            blob = _read_provenance(
                self.image, start, end - start, "executable raw bytes"
            )
            for offset, opcode in enumerate(blob):
                if opcode != 0xE8:
                    continue
                address = start + offset
                if offset + 5 > len(blob):
                    raise CfgRecoveryError(
                        "raw E8 candidate is unresolved: "
                        f"truncated rel32 at {address:#x}"
                    )
                displacement = struct.unpack_from("<i", blob, offset + 1)[0]
                target = (address + 5 + displacement) & 0xFFFF_FFFF
                if not _is_executable_span(self.image, target, 1):
                    continue
                instruction = self.instructions.get(address)
                direct_call = DirectCall(address=address, target=target)
                if (
                    instruction is not None
                    and instruction.size == 5
                    and direct_call in self.direct_calls
                    and all(
                        self.byte_owners.get(byte_address) == address
                        for byte_address in range(address, address + 5)
                    )
                ):
                    classification = "owned-call"
                elif (
                    self.byte_owners.get(address) not in {None, address}
                    and all(
                        byte_address in self.byte_owners
                        for byte_address in range(address, address + 5)
                    )
                ):
                    classification = "owned-instruction-bytes"
                elif (
                    self.byte_owners.get(address) not in {None, address}
                    and all(
                        byte_address in self.byte_owners
                        or self._region_contains(
                            data_regions,
                            byte_address,
                            byte_address + 1,
                        )
                        or self._region_contains(
                            padding_regions,
                            byte_address,
                            byte_address + 1,
                        )
                        for byte_address in range(address, address + 5)
                    )
                ):
                    classification = "owned-instruction-and-data"
                elif self._region_contains(
                    data_regions, address, address + 5
                ):
                    classification = "owned-data"
                else:
                    raise CfgRecoveryError(
                        "raw E8 candidate is unresolved: "
                        f"address={address:#x};target={target:#x}"
                    )
                candidates.append(
                    RawE8Candidate(
                        address=address,
                        target=target,
                        classification=classification,
                    )
                )
        return tuple(sorted(candidates, key=lambda row: row.address))

    def _require_complete_ownership(
        self,
        data_regions: tuple[ByteRegion, ...],
        padding_regions: tuple[ByteRegion, ...],
    ) -> None:
        covered = set(self.byte_owners)
        for region in (*data_regions, *padding_regions):
            for address in range(region.start, region.end):
                if _is_executable_span(self.image, address, 1):
                    covered.add(address)
        unexplained: list[tuple[int, int]] = []
        for start, end in self._executable_raw_ranges():
            gap_start: int | None = None
            for address in range(start, end):
                if address not in covered and gap_start is None:
                    gap_start = address
                elif address in covered and gap_start is not None:
                    unexplained.append((gap_start, address))
                    gap_start = None
            if gap_start is not None:
                unexplained.append((gap_start, end))
        if unexplained:
            rendered = ",".join(
                f"{start:#x}-{end:#x}" for start, end in unexplained
            )
            raise CfgRecoveryError(
                f"unexplained executable bytes: {rendered}"
            )

    def _closed_island_candidate(
        self, start: int, end: int
    ) -> tuple[int, int, int, str] | None:
        predecessor_owner = self.byte_owners.get(start - 1)
        predecessor = (
            self.instructions.get(predecessor_owner)
            if predecessor_owner is not None
            else None
        )
        if (
            predecessor is None
            or predecessor.address + predecessor.size != start
            or predecessor.address not in self.terminators
        ):
            return None

        candidate = start
        while candidate < end and self.image.read(candidate, 1) == b"\0":
            candidate += 1
        zero_prefix_end = candidate
        if candidate != start and (
            candidate == end
            or candidate % 16
            or candidate - start > 32
        ):
            return None

        cursor = candidate
        while cursor < end:
            try:
                decoded = self._decode_one(cursor)
            except CfgRecoveryError:
                return None
            instruction_end = decoded.address + decoded.size
            if instruction_end > end or any(
                address in self.byte_owners
                for address in range(decoded.address, instruction_end)
            ):
                return None

            if decoded.group(CS_GRP_CALL):
                target = self._direct_target(decoded)
                if target is None:
                    return None
                owner = self.byte_owners.get(target)
                if owner is not None and owner != target:
                    return None
                cursor = instruction_end
                continue

            if decoded.group(CS_GRP_RET) or decoded.group(CS_GRP_IRET):
                return (
                    candidate,
                    zero_prefix_end,
                    decoded.address,
                    decoded.mnemonic,
                )

            if decoded.group(CS_GRP_JUMP):
                target = self._direct_target(decoded)
                if target is None:
                    return None
                owner = self.byte_owners.get(target)
                if owner is not None and owner != target:
                    return None
                if decoded.id in {X86_INS_JMP, X86_INS_LJMP}:
                    return (
                        candidate,
                        zero_prefix_end,
                        decoded.address,
                        decoded.mnemonic,
                    )

            cursor = instruction_end
        if candidate != start and end in self.instructions:
            return candidate, zero_prefix_end, end, "owned-merge"
        return None

    def _discover_closed_executable_islands(self) -> bool:
        """Seed only terminal-bounded residual code with a closed linear path."""
        data_regions = self._merged_data_regions()
        padding_regions = self._padding_regions(data_regions)
        covered = set(self.byte_owners)
        for region in (*data_regions, *padding_regions):
            covered.update(range(region.start, region.end))

        gaps: list[tuple[int, int]] = []
        for raw_start, raw_end in self._executable_raw_ranges():
            gap_start: int | None = None
            for address in range(raw_start, raw_end):
                if address not in covered and gap_start is None:
                    gap_start = address
                elif address in covered and gap_start is not None:
                    gaps.append((gap_start, address))
                    gap_start = None
            if gap_start is not None:
                gaps.append((gap_start, raw_end))

        discovered = False
        for start, end in gaps:
            proof = self._closed_island_candidate(start, end)
            if proof is None:
                if (
                    end - start == 1
                    and end in self.instructions
                    and start - 1 in self.byte_owners
                ):
                    predecessor = self.instructions[
                        self.byte_owners[start - 1]
                    ]
                    predecessor_decoded = self._owned_decoded(
                        predecessor.address
                    )
                    separator_decoded = self._decode_one(start)
                    is_closed_predecessor = (
                        predecessor.address + predecessor.size == start
                        and (
                            predecessor_decoded.group(CS_GRP_RET)
                            or predecessor_decoded.group(CS_GRP_IRET)
                            or predecessor_decoded.id
                            in {X86_INS_JMP, X86_INS_LJMP}
                        )
                    )
                    if (
                        is_closed_predecessor
                        and separator_decoded.address
                        + separator_decoded.size
                        > end
                    ):
                        evidence = _DataEvidence(
                            start=start,
                            end=end,
                            provenance=(
                                "terminal-noninstruction-separator;"
                                f"terminal={predecessor.address:#x}:"
                                f"{predecessor.mnemonic};"
                                f"right-owner={end:#x};"
                                f"bytes={self.image.read(start, 1).hex()}"
                            ),
                        )
                        if evidence not in self.structural_data_evidence:
                            self.structural_data_evidence.add(evidence)
                            self.data_evidence.add(evidence)
                            self._record_fixpoint_update()
                            discovered = True
                continue
            candidate, zero_prefix_end, closure_address, closure_kind = proof
            category = (
                "closed-aligned-function"
                if candidate != start
                else "closed-executable-island"
            )
            first = self._decode_one(candidate)
            record = SeedRecord(
                address=candidate,
                category=category,
                provenance_address=self.byte_owners[start - 1],
                provenance_bytes=bytes(first.bytes).hex(),
                detail=(
                    f"uncovered-range={start:#x}-{end:#x};"
                    f"closed-terminal={closure_address:#x}:"
                    f"{closure_kind};"
                    f"zero-prefix={start:#x}-{zero_prefix_end:#x}"
                ),
            )
            if record in self.seed_records:
                continue
            self.seed_records.add(record)
            if candidate != start:
                evidence = _DataEvidence(
                    start=start,
                    end=candidate,
                    provenance=(
                        "closed-aligned-function-zero-prefix;"
                        f"entry={candidate:#x};max-gap=32"
                    ),
                )
                self.structural_data_evidence.add(evidence)
                self.data_evidence.add(evidence)
            self._record_finite_target(candidate)
            self._enqueue(candidate, is_function=candidate != start)
            self._record_fixpoint_update()
            discovered = True
        return discovered

    def _bind_seed_instruction_provenance(self) -> None:
        rebound: set[SeedRecord] = set()
        for record in self.seed_records:
            if record.category not in {
                "entrypoint",
                "export",
                "explicit-seed",
                "audit-anchor",
            }:
                rebound.add(record)
                continue
            instruction = self.instructions.get(record.address)
            if instruction is None:
                raise CfgRecoveryError(
                    "seed is not bound to a decoded first instruction: "
                    f"category={record.category};address={record.address:#x}"
                )
            if (
                record.category == "audit-anchor"
                and record.provenance_bytes != instruction.bytes_hex
            ):
                raise CfgRecoveryError(
                    "audit anchor does not span one complete instruction: "
                    f"address={record.address:#x};"
                    f"anchor-bytes={record.provenance_bytes};"
                    f"instruction-bytes={instruction.bytes_hex}"
                )
            rebound.add(
                SeedRecord(
                    address=record.address,
                    category=record.category,
                    provenance_address=record.provenance_address,
                    provenance_bytes=instruction.bytes_hex,
                    detail=record.detail,
                )
            )
        self.seed_records = rebound

    def recover(self) -> RawCfg:
        while True:
            while self.pending:
                address = heapq.heappop(self.pending)
                self._decode_from(address)
            self._discover_relocation_computed_transfers()
            if self.pending:
                continue
            blocks = self._build_blocks()
            block_start_count = len(self.block_starts)
            self._scan_owned_blocks(blocks)
            self._resolve_computed_flows()
            if (
                not self.pending
                and len(self.block_starts) == block_start_count
            ):
                if self._discover_closed_executable_islands():
                    continue
                break

        self._bind_seed_instruction_provenance()
        self._record_terminal_zero_alignment_evidence()
        data_regions = self._merged_data_regions()
        padding_regions = self._padding_regions(data_regions)
        self._require_disjoint_ownership(data_regions, padding_regions)
        raw_e8_candidates = self._raw_e8_candidates(
            data_regions, padding_regions
        )
        self._require_complete_ownership(data_regions, padding_regions)
        for limit_name in self.limits.__dataclass_fields__:
            self.limits.check(limit_name, self.high_water[limit_name])
        high_water = tuple(
            AnalysisHighWater(limit_name, self.high_water[limit_name])
            for limit_name in self.limits.__dataclass_fields__
        )
        return RawCfg(
            seed_inventory=SeedInventory(tuple(self.seed_records)),
            instructions=tuple(
                sorted(self.instructions.values(), key=_instruction_key)
            ),
            blocks=blocks,
            edges=tuple(sorted(self.edges, key=_edge_key)),
            direct_calls=tuple(
                sorted(self.direct_calls, key=_call_key)
            ),
            jump_tables=tuple(
                sorted(self.jump_tables.values(), key=_jump_table_key)
            ),
            raw_e8_candidates=raw_e8_candidates,
            data_regions=data_regions,
            padding_regions=padding_regions,
            ownership_diagnostics=tuple(
                sorted(self.diagnostics, key=_diagnostic_key)
            ),
            limits=self.limits,
            high_water_marks=high_water,
        )


def recover_cfg(
    image: Image,
    seeds: SeedInventory | Sequence[int],
    limits: AnalysisLimits,
) -> RawCfg:
    """Recover direct x86 CFG and exact ownership (decoder slice)."""
    seed_inventory = (
        seeds
        if isinstance(seeds, SeedInventory)
        else _explicit_seed_inventory(image, seeds)
    )
    return _DirectCfgRecovery(image, seed_inventory, limits).recover()


def write_jsonl_atomic(path: Path, cfg: RawCfg) -> None:
    """Write canonical compact UTF-8 CFG records with atomic replacement."""
    rows: list[dict[str, Any]] = []
    for record in cfg.seed_inventory.records:
        rows.append({"record_kind": "seed", **asdict(record)})
    for instruction in cfg.instructions:
        rows.append(
            {
                "record_kind": "instruction",
                **asdict(instruction),
            }
        )
    for block in cfg.blocks:
        rows.append(
            {
                "record_kind": "basic-block",
                "address": block.start,
                **asdict(block),
            }
        )
    for edge in cfg.edges:
        rows.append(
            {
                "record_kind": "edge",
                "address": edge.source,
                **asdict(edge),
            }
        )
    for call in cfg.direct_calls:
        rows.append({"record_kind": "direct-call", **asdict(call)})
    for table in cfg.jump_tables:
        rows.append(
            {
                "record_kind": "jump-table",
                **asdict(table),
            }
        )
    for candidate in cfg.raw_e8_candidates:
        rows.append({"record_kind": "raw-e8", **asdict(candidate)})
    for region in cfg.data_regions:
        rows.append(
            {
                "record_kind": "data-region",
                "address": region.start,
                **asdict(region),
            }
        )
    for region in cfg.padding_regions:
        rows.append(
            {
                "record_kind": "padding-region",
                "address": region.start,
                **asdict(region),
            }
        )
    for diagnostic in cfg.ownership_diagnostics:
        rows.append(
            {"record_kind": "ownership-diagnostic", **asdict(diagnostic)}
        )
    for limit_name, configured in asdict(cfg.limits).items():
        rows.append(
            {
                "address": -1,
                "record_kind": "analysis-limit",
                "limit_name": limit_name,
                "configured": configured,
            }
        )
    for high_water in cfg.high_water_marks:
        rows.append(
            {
                "address": -1,
                "record_kind": "analysis-high-water",
                **asdict(high_water),
            }
        )

    rows.sort(
        key=lambda row: (
            row["address"],
            row["record_kind"],
            row.get("target", -1),
        )
    )
    payload = b"".join(
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
        for row in rows
    )

    path = Path(path)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
