"""Deterministic seed discovery and direct PE32 x86 CFG recovery."""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import re
import struct
import tempfile
from collections import OrderedDict
from bisect import bisect_right
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
    x86_const,
)
from capstone.x86 import (
    X86_INS_ENTER,
    X86_INS_JMP,
    X86_INS_LCALL,
    X86_INS_LEA,
    X86_INS_LJMP,
    X86_INS_MOV,
    X86_INS_XOR,
    X86_OP_IMM,
    X86_OP_MEM,
    X86_OP_REG,
    X86_REG_INVALID,
)

_REGISTER_FAMILIES = ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp")
_DECODED_INSTRUCTION_CACHE_LIMIT = 1024

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
    max_exception_entries: int = 65_536
    max_exception_actions: int = 65_536
    max_exception_landing_sites: int = 65_536

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
    is_function: bool = False


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
class ExecutableResidueInterval:
    """One exact-hashed interval not reached by the raw fixed point."""

    start: int
    end: int
    bytes_hex: str
    bytes_sha256: str


@dataclass(frozen=True, slots=True)
class UnreachableExecutableResidue:
    """Provisional complement of reachable executable ownership."""

    intervals: tuple[ExecutableResidueInterval, ...]
    reachable_ownership_sha256: str
    executable_partition_sha256: str
    accepted: bool = False
    reconciliation_sha256: str | None = None

    def contains(self, address: int, size: int = 1) -> bool:
        end = address + size
        return any(
            row.start <= address and end <= row.end for row in self.intervals
        )


@dataclass(frozen=True, slots=True)
class FunctionEntry:
    """Explicit raw function-entry fact, independent of category names."""

    address: int
    is_function: bool
    provenance: tuple[str, ...]


def _materialize_function_entries(
    function_addresses: Iterable[int], seed_records: Iterable[SeedRecord]
) -> tuple[FunctionEntry, ...]:
    """Aggregate seed provenance in one pass before materializing entries."""
    function_provenance: dict[int, set[str]] = {}
    for row in seed_records:
        if row.is_function:
            function_provenance.setdefault(row.address, set()).add(
                row.category
            )
    return tuple(
        FunctionEntry(
            address=address,
            is_function=True,
            provenance=tuple(
                sorted(
                    function_provenance.get(address, set())
                    or {"derived-function-target"}
                )
            ),
        )
        for address in sorted(function_addresses)
    )


@dataclass(frozen=True, slots=True)
class FiniteControlTarget:
    source: int
    target: int
    flow_kind: str
    provenance: str


@dataclass(frozen=True, slots=True)
class TerminalExternalEdge:
    source: int
    flow_kind: str
    iat_va: int
    dll: str
    name: str | None
    ordinal: int | None
    provenance: str


@dataclass(frozen=True, slots=True)
class ExternalCodePointerEscape:
    source: int
    target_import_iat: int
    possible_internal_targets: tuple[int, ...]
    provenance: str


@dataclass(frozen=True, slots=True)
class UnresolvedControlTarget:
    address: int
    kind: str
    detail: str


@dataclass(frozen=True, slots=True)
class ControlTargetResult:
    """Closed finite target facts consumed unchanged by Task 5."""

    finite_internal_edges: tuple[FiniteControlTarget, ...]
    terminal_external_edges: tuple[TerminalExternalEdge, ...]
    external_escapes: tuple[ExternalCodePointerEscape, ...]
    unresolved: tuple[UnresolvedControlTarget, ...]


@dataclass(frozen=True, slots=True)
class OwnershipDiagnostic:
    kind: str
    address: int
    detail: str


@dataclass(frozen=True, slots=True)
class RelocationDisposition:
    source_address: int
    source_bytes_hex: str
    source_class: str
    source_owner: int | None
    target_address: int
    target_section: str | None
    target_import: str | None
    status: str
    provenance: str


@dataclass(frozen=True, slots=True)
class SemanticReference:
    record_kind: str
    address: int
    target: int
    provenance: str


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
class CwExceptionMetadata:
    """Strictly decoded CodeWarrior x86 packed exception metadata."""

    range_table: tuple[tuple[int, int], ...]
    pc_map: tuple[tuple[int, int, int, int], ...]
    landing_sites: tuple[int, ...]
    action_kinds: tuple[int, ...]
    direct_callbacks: tuple[int, ...]
    continuation_targets: tuple[tuple[int, int], ...]
    action_records: tuple[int, ...]
    action_contexts: tuple[tuple[int, int, int], ...]


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
    cw_exception_metadata: CwExceptionMetadata | None
    raw_e8_candidates: tuple[RawE8Candidate, ...]
    data_regions: tuple[ByteRegion, ...]
    padding_regions: tuple[ByteRegion, ...]
    provisional_unreachable_residue: UnreachableExecutableResidue
    function_entries: tuple[FunctionEntry, ...]
    control_targets: ControlTargetResult
    ownership_diagnostics: tuple[OwnershipDiagnostic, ...]
    relocation_dispositions: tuple[RelocationDisposition, ...]
    semantic_references: tuple[SemanticReference, ...]
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


def _read_loader_initialized(image: Image, address: int, size: int) -> bytes:
    """Read file-backed bytes or a wholly zero-filled PE section tail."""
    try:
        return image.read(address, size)
    except ValueError as exc:
        end = address + size
        if any(
            section.va + section.raw_size <= address
            and end <= section.va + section.mapped_size
            for section in image.sections
        ):
            return b"\0" * size
        raise exc


_CW_ACTION_FIXED_SIZES = {
    1: 0x0A,
    2: 0x0E,
    4: 0x0A,
    5: 0x12,
    6: 0x12,
    7: 0x0E,
    8: 0x12,
    9: 0x16,
    10: 0x0A,
    11: 0x0E,
    12: 0x0E,
    16: 0x0E,
    17: 0x06,
    18: 0x02,
}
_CW_ACTION_DIRECT_CALLBACK_OFFSETS = {
    1: 0x06,
    2: 0x0A,
    4: 0x06,
    7: 0x06,
    8: 0x0A,
    10: 0x06,
    11: 0x06,
}
_CW_ACTION_CONTINUATION_OFFSETS = {16: 0x06, 19: 0x04}


def parse_cw_exception_metadata(
    image: Image, limits: AnalysisLimits
) -> CwExceptionMetadata | None:
    """Parse the retail CodeWarrior ``.exc`` and packed action streams.

    The parser deliberately relies on the section sentinel, exact HIGHLOW
    relocation fields, and the runtime's audited size dispatch.  Packed u32
    fields are allowed to be unaligned; action-record starts remain u16
    aligned because the runtime reads their tags as u16 values.
    """

    exc_sections = tuple(row for row in image.sections if row.name == ".exc")
    if not exc_sections:
        return None
    if len(exc_sections) != 1:
        raise CfgRecoveryError("CodeWarrior exception table is not unique")
    rdata_sections = tuple(
        row for row in image.sections if row.name == ".rdata"
    )
    if len(rdata_sections) != 1:
        raise CfgRecoveryError(
            "CodeWarrior exception metadata requires one .rdata section"
        )
    exc = exc_sections[0]
    rdata = rdata_sections[0]
    if exc.va & 3:
        raise CfgRecoveryError("CodeWarrior exception range table is unaligned")
    try:
        table_bytes = image.read(exc.va, exc.virt_size)
    except ValueError as exc_read:
        raise CfgRecoveryError(
            "CodeWarrior exception range table is not wholly file-backed"
        ) from exc_read

    relocation_slots = {
        row.va for row in image.relocations if row.type == 3
    }
    if len(relocation_slots) != sum(
        row.type == 3 for row in image.relocations
    ):
        raise CfgRecoveryError(
            "CodeWarrior exception metadata has duplicate HIGHLOW relocations"
        )

    ranges: list[tuple[int, int]] = []
    cursor = 0
    while True:
        if cursor + 4 > len(table_bytes):
            raise CfgRecoveryError(
                "CodeWarrior exception range table is missing its sentinel"
            )
        function_entry = struct.unpack_from("<I", table_bytes, cursor)[0]
        if function_entry == 0xFFFF_FFFF:
            if cursor + 4 != len(table_bytes):
                raise CfgRecoveryError(
                    "CodeWarrior exception sentinel is not the exact table end"
                )
            if exc.va + cursor in relocation_slots:
                raise CfgRecoveryError(
                    "CodeWarrior exception sentinel must not be relocated"
                )
            break
        if cursor + 8 > len(table_bytes):
            raise CfgRecoveryError(
                "CodeWarrior exception range table is missing its sentinel"
            )
        metadata = struct.unpack_from("<I", table_bytes, cursor + 4)[0]
        if (
            exc.va + cursor not in relocation_slots
            or exc.va + cursor + 4 not in relocation_slots
        ):
            raise CfgRecoveryError(
                "CodeWarrior exception range row lacks exact relocations"
            )
        if not _is_executable_span(image, function_entry, 1):
            raise CfgRecoveryError(
                "CodeWarrior exception range start is not executable: "
                f"{function_entry:#x}"
            )
        if not (
            rdata.va <= metadata
            and metadata + 4 <= rdata.va + rdata.virt_size
        ):
            raise CfgRecoveryError(
                "CodeWarrior function metadata is outside .rdata: "
                f"{metadata:#x}"
            )
        if ranges and function_entry <= ranges[-1][0]:
            raise CfgRecoveryError(
                "CodeWarrior exception ranges are not strictly sorted"
            )
        ranges.append((function_entry, metadata))
        limits.check("max_exception_entries", len(ranges))
        cursor += 8
    if not ranges:
        raise CfgRecoveryError("CodeWarrior exception range table is empty")

    metadata_bounds: dict[int, tuple[int, int]] = {}
    for index, (function_entry, metadata) in enumerate(ranges):
        function_end = (
            ranges[index + 1][0]
            if index + 1 < len(ranges)
            else max(end for _start, end in image.executable_ranges)
        )
        existing = metadata_bounds.get(metadata)
        bound = (function_entry, function_end)
        if existing is not None and existing != bound:
            raise CfgRecoveryError(
                "CodeWarrior function metadata is shared across ranges"
            )
        metadata_bounds[metadata] = bound

    action_roots: set[int] = set()
    root_contexts: dict[int, set[int]] = {}
    pc_map: list[tuple[int, int, int, int]] = []
    landing_sites: set[int] = set()
    metadata_starts = tuple(sorted(metadata_bounds))
    for metadata in metadata_starts:
        # A relocated pointer beginning at +1 is the unambiguous packed-map
        # discriminator.  Compact records contain only their four flag bytes.
        if metadata + 1 not in relocation_slots:
            image.read(metadata, 4)
            continue
        if metadata & 1:
            raise CfgRecoveryError(
                "CodeWarrior packed function metadata is not u16 aligned"
            )
        header = image.read(metadata, 7)
        initial_action = struct.unpack_from("<I", header, 1)[0]
        count = struct.unpack_from("<H", header, 5)[0]
        if count == 0:
            raise CfgRecoveryError(
                "CodeWarrior packed function metadata has an empty PC map"
            )
        total_landings = len(landing_sites) + count
        limits.check("max_exception_landing_sites", total_landings)
        record_end = metadata + 7 + count * 8
        following_metadata = next(
            (row for row in metadata_starts if row > metadata),
            rdata.va + rdata.virt_size,
        )
        if record_end > following_metadata:
            raise CfgRecoveryError(
                "CodeWarrior packed function metadata overlaps the next record"
            )
        padding = image.read(record_end, following_metadata - record_end)
        # Only the alignment tail belongs to this header.  A larger gap may
        # contain action records referenced by a later header.
        alignment_padding = min(len(padding), (-record_end) & 3)
        if padding[:alignment_padding] != b"\0" * alignment_padding:
            raise CfgRecoveryError(
                "CodeWarrior packed function metadata has nonzero padding"
            )
        action_roots.add(initial_action)
        function_start, function_end = metadata_bounds[metadata]
        root_contexts.setdefault(initial_action, set()).add(function_start)
        previous_end = function_start
        for index in range(count):
            row_address = metadata + 7 + index * 8
            if (
                row_address not in relocation_slots
                or row_address + 4 not in relocation_slots
            ):
                raise CfgRecoveryError(
                    "CodeWarrior packed PC map lacks exact relocations"
                )
            instruction_end, action = struct.unpack(
                "<II", image.read(row_address, 8)
            )
            if not previous_end < instruction_end < function_end:
                raise CfgRecoveryError(
                    "CodeWarrior packed PC map is outside its function range"
                )
            previous_end = instruction_end
            landing_sites.add(instruction_end)
            action_roots.add(action)
            root_contexts.setdefault(action, set()).add(function_start)
            pc_map.append(
                (function_start, metadata, instruction_end, action)
            )

    action_kinds: set[int] = set()
    direct_callbacks: set[int] = set()
    continuation_targets: set[tuple[int, int]] = set()
    action_records: set[int] = set()
    action_contexts: set[tuple[int, int, int]] = set()
    for root in sorted(action_roots):
        if root & 1:
            raise CfgRecoveryError(
                f"CodeWarrior action record is not u16 aligned: {root:#x}"
            )
        action = root
        while True:
            if action in action_records:
                break
            limits.check("max_exception_actions", len(action_records) + 1)
            tag = struct.unpack("<H", image.read(action, 2))[0]
            kind = tag & 0xFF
            is_last = bool(tag & 0x8000)
            if tag & 0x7F00:
                raise CfgRecoveryError(
                    f"CodeWarrior action tag has unknown flags: {tag:#x}"
                )
            if kind == 19:
                count = struct.unpack("<H", image.read(action + 2, 2))[0]
                limits.check("max_exception_actions", len(action_records) + count)
                size = 0x0C + count * 4
            else:
                size = _CW_ACTION_FIXED_SIZES.get(kind, 0)
            if not size:
                raise CfgRecoveryError(
                    f"CodeWarrior action kind has no audited size: {kind}"
                )
            if not (
                rdata.va <= action
                and action + size <= rdata.va + rdata.virt_size
            ):
                raise CfgRecoveryError(
                    f"CodeWarrior action record is outside .rdata: {action:#x}"
                )
            image.read(action, size)
            callback_offset = _CW_ACTION_DIRECT_CALLBACK_OFFSETS.get(kind)
            if callback_offset is not None:
                callback_slot = action + callback_offset
                if callback_slot not in relocation_slots:
                    raise CfgRecoveryError(
                        "CodeWarrior action callback lacks an exact relocation"
                    )
                callback = struct.unpack(
                    "<I", image.read(callback_slot, 4)
                )[0]
                if not _is_executable_span(image, callback, 1):
                    raise CfgRecoveryError(
                        "CodeWarrior action callback is not executable: "
                        f"{callback:#x}"
                    )
                direct_callbacks.add(callback)
            continuation_offset = _CW_ACTION_CONTINUATION_OFFSETS.get(kind)
            if continuation_offset is not None:
                continuation_slot = action + continuation_offset
                if continuation_slot not in relocation_slots:
                    raise CfgRecoveryError(
                        "CodeWarrior continuation lacks an exact relocation"
                    )
                continuation = struct.unpack(
                    "<I", image.read(continuation_slot, 4)
                )[0]
                if not _is_executable_span(image, continuation, 1):
                    raise CfgRecoveryError(
                        "CodeWarrior continuation is not executable: "
                        f"{continuation:#x}"
                    )
                continuation_targets.add((kind, continuation))
            action_records.add(action)
            action_kinds.add(kind)
            for function_entry in root_contexts[root]:
                action_contexts.add((function_entry, action, kind))
            if is_last:
                break
            action += size

    return CwExceptionMetadata(
        range_table=tuple(ranges),
        pc_map=tuple(sorted(pc_map)),
        landing_sites=tuple(sorted(landing_sites)),
        action_kinds=tuple(sorted(action_kinds)),
        direct_callbacks=tuple(sorted(direct_callbacks)),
        continuation_targets=tuple(sorted(continuation_targets)),
        action_records=tuple(sorted(action_records)),
        action_contexts=tuple(sorted(action_contexts)),
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
            is_function=True,
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
            is_function=True,
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
            is_function=True,
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
                is_function=True,
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
class _GlobalSlotWrite:
    instruction_address: int
    value: int | None
    provenance: str


@dataclass(frozen=True, slots=True)
class _DynamicFieldWrite:
    instruction_address: int
    width: int
    value: int | None
    provenance: str


@dataclass(frozen=True, slots=True)
class _ObjectCallbackTableHypothesis:
    table_base: int
    store_address: int
    records: tuple[SeedRecord, ...]
    data_evidence: _DataEvidence


@dataclass(frozen=True, slots=True)
class _CopiedDescriptorCallbackHypothesis:
    source_bases: tuple[int, ...]
    target_source_bases: tuple[tuple[int, tuple[int, ...]], ...]
    records: tuple[SeedRecord, ...]
    data_evidence: tuple[_DataEvidence, ...]


@dataclass(frozen=True, slots=True)
class _ClosedObjectOrigin:
    has_target_constructor: bool
    rejected_tags: frozenset[int]
    detail: str


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
        rejected_object_callback_tables: frozenset[int] = frozenset(),
    ) -> None:
        _validate_capstone_audit_contract()
        self.image = image
        self.limits = limits
        self.seed_records = set(seed_inventory.records)
        self.instructions: dict[int, Instruction] = {}
        self.decoded_instruction_cache: OrderedDict[int, Any] = OrderedDict()
        self.instruction_by_end: dict[int, Instruction] = {}
        self.byte_owners: dict[int, int] = {}
        self.block_starts: set[int] = set()
        self.terminators: set[int] = set()
        self.edges: set[CfgEdge] = set()
        self.call_targets_by_source: dict[int, set[int]] = {}
        self.direct_call_targets_by_source: dict[int, int] = {}
        self.direct_call_sources_by_target: dict[int, set[int]] = {}
        self.non_call_successors: dict[int, set[int]] = {}
        self.incoming_edges: dict[int, set[tuple[int, str]]] = {}
        self.non_call_backedges: set[CfgEdge] = set()
        self.control_flow_revision = 0
        self.edge_provenance: dict[CfgEdge, str] = {}
        self.direct_calls: set[DirectCall] = set()
        self.jump_tables: dict[int, JumpTable] = {}
        self.jump_table_entry_count = 0
        self.indirect_candidates: dict[int, tuple[str, bool]] = {}
        self.terminal_external_edges: set[TerminalExternalEdge] = set()
        self.external_escapes: set[ExternalCodePointerEscape] = set()
        self.global_slot_writes: dict[int, set[_GlobalSlotWrite]] = {}
        self.global_slot_write_count = 0
        self.absolute_memory_writes: dict[int, set[int]] = {}
        self.dynamic_field_writes: dict[int, set[_DynamicFieldWrite]] = {}
        self.dynamic_field_write_count = 0
        self.dynamic_field_cache: dict[
            tuple[int, tuple[int, ...]],
            tuple[frozenset[int], str] | None,
        ] = {}
        self.copied_descriptor_cache: dict[
            tuple[int, ...],
            tuple[
                int,
                tuple[frozenset[int], frozenset[int], frozenset[int]],
            ]
            | None,
        ] = {}
        self.copy_origin_cache: dict[
            tuple[int, int, int, tuple[int, ...], int], bool
        ] = {}
        self.copied_argument_origin_cache: set[tuple[Any, ...]] = set()
        self.global_copy_origin_cache: set[tuple[Any, ...]] = set()
        self.copied_back_reference_origin_cache: set[
            tuple[Any, ...]
        ] = set()
        self.runtime_descriptor_field_origin_cache: set[
            tuple[Any, ...]
        ] = set()
        self.global_runtime_descriptor_field_origin_cache: set[
            tuple[Any, ...]
        ] = set()
        self.back_reference_initializer_cache: dict[
            tuple[Any, ...], tuple[int, int] | None
        ] = {}
        self.initialized_back_reference_cache: set[
            tuple[Any, ...]
        ] = set()
        self.copy_registry_cache: dict[
            tuple[int, tuple[int, ...]],
            tuple[tuple[int, int, int], ...],
        ] = {}
        self.registry_cursor_domain_cache: dict[
            tuple[Any, ...], tuple[int, int] | None
        ] = {}
        self.registered_copy_return_cache: dict[tuple[Any, ...], bool] = {}
        self.copy_return_cache: dict[
            tuple[int, int, tuple[int, ...], int], bool
        ] = {}
        self.pointer_identity_cache: dict[
            tuple[int, str, int, tuple[int, ...]], tuple[int, int] | None
        ] = {}
        self.intrusive_list_return_cache: dict[
            tuple[int, tuple[int, ...], int], int | None
        ] = {}
        self.intrusive_list_insert_cache: dict[
            tuple[int, tuple[int, ...], int], tuple[int, int] | None
        ] = {}
        self.global_list_field_cache: dict[
            tuple[int, int, int, int, tuple[int, ...], int], bool
        ] = {}
        self.global_list_field_active: set[
            tuple[int, int, int, int, tuple[int, ...], int]
        ] = set()
        self.function_instruction_cache: dict[
            tuple[int, tuple[int, ...]], tuple[int, ...]
        ] = {}
        self.relative_pointer_state_cache: dict[tuple[Any, ...], Any] = {}
        self.argument_return_offset_cache: dict[
            tuple[Any, ...], frozenset[int] | None
        ] = {}
        self.argument_return_offset_active: set[tuple[Any, ...]] = set()
        self.incoming_register_read_cache: dict[tuple[Any, ...], bool] = {}
        self.dead_call_return_cache: dict[tuple[Any, ...], bool] = {}
        self.raw_dead_call_return_cache: dict[tuple[int, int], bool] = {}
        self.field_preservation_cache: dict[tuple[Any, ...], bool] = {}
        self.field_read_avoidance_cache: dict[tuple[Any, ...], bool] = {}
        self.zeroing_wrapper_cache: dict[tuple[Any, ...], int | None] = {}
        self.zeroed_field_return_cache: dict[tuple[Any, ...], bool] = {}
        self.runtime_global_copy_field_cache: dict[tuple[Any, ...], bool] = {}
        self.runtime_global_copy_field_active: set[tuple[Any, ...]] = set()
        self.raw_direct_call_sites_cache: (
            dict[int, frozenset[int]] | None
        ) = None
        self.direct_call_domain_cache: dict[
            tuple[int, tuple[int, ...]], bool
        ] = {}
        self.incoming_call_domain_cache: dict[
            tuple[int, tuple[int, ...], int], bool
        ] = {}
        self.guarded_slot_zero_consumer_cache: dict[
            tuple[tuple[int, ...], int],
            tuple[tuple[int, int, int, int], ...],
        ] = {}
        self.registered_copy_register_cache: dict[tuple[Any, ...], bool] = {}
        self.registered_copy_state_cache: dict[
            tuple[Any, ...],
            dict[int, dict[str, int]] | None,
        ] = {}
        self.registered_copy_state_active: set[tuple[Any, ...]] = set()
        self.registered_copy_state_tainted: set[tuple[Any, ...]] = set()
        self.cw_k17_domain_cache: dict[
            tuple[int, ...], tuple[frozenset[int], str] | None
        ] = {}
        self.cw_k17_wrapper_cache: dict[tuple[int, ...], int] = {}
        self.cw_inactive_helpers_cache: dict[
            tuple[int, ...], tuple[dict[int, set[int]], set[int]]
        ] = {}
        self.stack_state_cache: dict[
            tuple[int, int, int], dict[int, tuple[int, int | None]] | None
        ] = {}
        self.callee_cleanup_cache: dict[
            tuple[int, int, int], int | None
        ] = {}
        self.argument_state_cache: dict[
            tuple[int, str, tuple[int, ...]],
            dict[int, tuple[int, frozenset[int]] | None],
        ] = {}
        self.definition_state_cache: dict[
            tuple[int, str, tuple[int, ...]],
            dict[int, frozenset[int] | None],
        ] = {}
        self.finite_argument_cache: dict[
            tuple[int, int, tuple[int, ...]],
            tuple[frozenset[int], str] | None,
        ] = {}
        self.no_return_cache: dict[
            tuple[int, tuple[int, ...]], bool
        ] = {}
        self.diagnostics: set[OwnershipDiagnostic] = set()
        self.data_evidence: set[_DataEvidence] = set()
        self.structural_data_evidence: set[_DataEvidence] = set()
        self.semantic_data_references: set[SemanticReference] = set()
        self.function_addresses: set[int] = set()
        self.sorted_function_addresses_cache: tuple[int, ...] = ()
        self.finite_targets: set[int] = set()
        self.finite_values: set[int] = set()
        self.produced_initializers: set[tuple[int, int]] = set()
        self.accepted_initializer_instructions: set[int] = set()
        self.object_callback_table_hypotheses: set[
            _ObjectCallbackTableHypothesis
        ] = set()
        self.copied_descriptor_callback_hypotheses: set[
            _CopiedDescriptorCallbackHypothesis
        ] = set()
        self.validated_copied_descriptor_callback_hypotheses: set[
            _CopiedDescriptorCallbackHypothesis
        ] = set()
        self.rejected_object_callback_tables = (
            rejected_object_callback_tables
        )
        self.fixpoint_updates = 0
        self.high_water = {
            limit_name: 0
            for limit_name in self.limits.__dataclass_fields__
        }
        self.pending: list[int] = []
        self.queued: set[int] = set()
        self.cw_exception_metadata = parse_cw_exception_metadata(
            image, limits
        )
        if self.cw_exception_metadata is not None:
            self.high_water["max_exception_entries"] = len(
                self.cw_exception_metadata.range_table
            )
            self.high_water["max_exception_actions"] = len(
                self.cw_exception_metadata.action_records
            )
            self.high_water["max_exception_landing_sites"] = len(
                self.cw_exception_metadata.landing_sites
            )

        self.decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        self.decoder.detail = True
        self.decoder.skipdata = False

        seed_function_flags: dict[int, bool] = {}
        for record in self.seed_records:
            seed_function_flags[record.address] = (
                seed_function_flags.get(record.address, False)
                or record.is_function
            )
        for address, is_function in sorted(seed_function_flags.items()):
            self._enqueue(
                address,
                is_function=is_function,
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

    def _summary_fact_signature(self) -> tuple[int, ...]:
        return (
            len(self.instructions),
            len(self.function_addresses),
            len(self.direct_calls),
            len(self.jump_tables),
            self.global_slot_write_count,
            self.dynamic_field_write_count,
        )

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
            predecessor = self.instruction_by_end.get(address)
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

    def _add_edge(
        self,
        source: int,
        target: int,
        kind: str,
        *,
        provenance: str | None = None,
    ) -> None:
        edge = CfgEdge(source=source, target=target, kind=kind)
        if edge in self.edges:
            if provenance is not None:
                prior = self.edge_provenance.get(edge)
                if prior is not None and prior != provenance:
                    raise CfgRecoveryError(
                        f"conflicting edge provenance at {source:#x}"
                    )
                self.edge_provenance[edge] = provenance
            return
        self.edges.add(edge)
        if kind == "direct-call" or kind.startswith("indirect-call-"):
            self.call_targets_by_source.setdefault(source, set()).add(target)
        if kind == "direct-call":
            prior_target = self.direct_call_targets_by_source.get(source)
            if prior_target is not None and prior_target != target:
                raise CfgRecoveryError(
                    f"conflicting direct-call target at {source:#x}"
                )
            self.direct_call_targets_by_source[source] = target
            self.direct_call_sources_by_target.setdefault(target, set()).add(
                source
            )
        self.incoming_edges.setdefault(target, set()).add((source, kind))
        if "call" not in kind:
            successors = self.non_call_successors.setdefault(source, set())
            if target not in successors:
                successors.add(target)
                self.control_flow_revision += 1
            if target < source:
                self.non_call_backedges.add(edge)
        elif kind.startswith("indirect-call-"):
            self.control_flow_revision += 1
        self.edge_provenance[edge] = provenance or (
            f"instruction-bytes={self.instructions[source].bytes_hex}"
        )
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
        self._cache_decoded_instruction(decoded)
        self.instruction_by_end[end] = instruction
        for operand in decoded.operands:
            absolute = self._absolute_memory_operand(operand)
            if absolute is not None and operand.access & CS_AC_WRITE:
                self.absolute_memory_writes.setdefault(absolute, set()).add(
                    address
                )
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
                is_function=category == "direct-call-target",
            )
        )

    def _previous_instruction(self, address: int) -> Instruction | None:
        return self.instruction_by_end.get(address)

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
        incoming = self.incoming_edges.get(transfer_address, set())
        if incoming != {(branch.address, "fallthrough")}:
            return None
        compare: Instruction | None = None
        compare_decoded = None
        cursor = branch.address
        index_family = self._register_family(index_register)
        for _ in range(16):
            candidate = self._previous_instruction(cursor)
            if candidate is None:
                return None
            decoded = self._owned_decoded(candidate.address)
            if (
                decoded.mnemonic == "cmp"
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and decoded.operands[0].size == 4
                and decoded.operands[1].type == X86_OP_IMM
                and self._register_family(decoded.operands[0].reg)
                == index_family
            ):
                compare = candidate
                compare_decoded = decoded
                break
            if (
                decoded.group(CS_GRP_CALL)
                or decoded.group(CS_GRP_JUMP)
                or decoded.group(CS_GRP_RET)
                or decoded.group(CS_GRP_IRET)
                or any(
                    self._register_family(register) == index_family
                    for register in decoded.regs_write
                    if register != x86_const.X86_REG_EFLAGS
                )
                or x86_const.X86_REG_EFLAGS in decoded.regs_write
                or candidate.address in self.block_starts
            ):
                return None
            cursor = candidate.address
        if compare is None or compare_decoded is None:
            return None
        bound = compare_decoded.operands[1].imm & 0xFFFF_FFFF
        index_min = adjustment[0]
        index_max = bound + adjustment[1]
        if index_max < index_min:
            return None
        return compare, branch_decoded.mnemonic, bound, index_min, index_max

    def _signed_memory_guard_for_index(
        self, transfer_address: int, index_register: int
    ) -> tuple[Instruction, str, int, int, int] | None:
        """Prove ``0 <= byte < bound`` from two same-location guards.

        CodeWarrior commonly validates a signed byte in memory, sign-extends
        that exact byte, and only then copies it into the table index register.
        The ordinary unsigned-register guard intentionally cannot infer this
        domain.  Keep this recognizer strict: both rejecting branches and the
        sign extension must be adjacent, use the same byte location, and have
        no call or write between the checks and the transfer.
        """
        index_family = self._register_family(index_register)
        copy = self._previous_instruction(transfer_address)
        if copy is None:
            return None
        copy_decoded = self._owned_decoded(copy.address)
        value_family = index_family
        sign_extend = copy
        sign_decoded = copy_decoded
        if (
            copy_decoded.id == X86_INS_MOV
            and len(copy_decoded.operands) == 2
            and all(row.type == X86_OP_REG for row in copy_decoded.operands)
            and self._register_family(copy_decoded.operands[0].reg)
            == index_family
        ):
            value_family = self._register_family(copy_decoded.operands[1].reg)
            cursor = copy.address
            sign_extend = None
            spill_count = 0
            for _ in range(4):
                candidate = self._previous_instruction(cursor)
                if candidate is None:
                    return None
                candidate_decoded = self._owned_decoded(candidate.address)
                if candidate_decoded.id == x86_const.X86_INS_MOVSX:
                    sign_extend = candidate
                    sign_decoded = candidate_decoded
                    break
                if not (
                    spill_count == 0
                    and candidate_decoded.id == X86_INS_MOV
                    and len(candidate_decoded.operands) == 2
                    and candidate_decoded.operands[0].type == X86_OP_MEM
                    and candidate_decoded.operands[0].size == 4
                    and candidate_decoded.operands[0].mem.segment
                    == X86_REG_INVALID
                    and candidate_decoded.operands[0].mem.index
                    == X86_REG_INVALID
                    and candidate_decoded.operands[0].mem.base
                    != X86_REG_INVALID
                    and self._register_family(
                        candidate_decoded.operands[0].mem.base
                    )
                    in {"esp", "ebp"}
                    and candidate_decoded.operands[1].type == X86_OP_REG
                    and self._register_family(
                        candidate_decoded.operands[1].reg
                    )
                    == value_family
                ):
                    return None
                spill_count += 1
                cursor = candidate.address
            if sign_extend is None:
                return None
        if (
            sign_decoded.id != x86_const.X86_INS_MOVSX
            or len(sign_decoded.operands) != 2
            or sign_decoded.operands[0].type != X86_OP_REG
            or self._register_family(sign_decoded.operands[0].reg)
            != value_family
            or sign_decoded.operands[1].type != X86_OP_MEM
            or sign_decoded.operands[1].size != 1
        ):
            return None
        guarded_memory = sign_decoded.operands[1].mem

        cursor = sign_extend.address
        pushed_arguments = 0
        pushed_addresses = []
        upper_branch = self._previous_instruction(cursor)
        while upper_branch is not None and pushed_arguments < 8:
            upper_candidate = self._owned_decoded(upper_branch.address)
            if upper_candidate.mnemonic != "push":
                break
            pushed_addresses.append(upper_branch.address)
            pushed_arguments += 1
            cursor = upper_branch.address
            upper_branch = self._previous_instruction(cursor)
        upper_compare = (
            None
            if upper_branch is None
            else self._previous_instruction(upper_branch.address)
        )
        lower_branch = (
            None
            if upper_compare is None
            else self._previous_instruction(upper_compare.address)
        )
        lower_compare = (
            None
            if lower_branch is None
            else self._previous_instruction(lower_branch.address)
        )
        if None in {
            upper_branch,
            upper_compare,
            lower_branch,
            lower_compare,
        }:
            return None
        upper_branch_decoded = self._owned_decoded(upper_branch.address)
        upper_compare_decoded = self._owned_decoded(upper_compare.address)
        lower_branch_decoded = self._owned_decoded(lower_branch.address)
        lower_compare_decoded = self._owned_decoded(lower_compare.address)
        if (
            upper_branch_decoded.mnemonic != "jge"
            or lower_branch_decoded.mnemonic != "jl"
            or self._direct_target(upper_branch_decoded) is None
            or self._direct_target(upper_branch_decoded)
            != self._direct_target(lower_branch_decoded)
            or self._direct_target(upper_branch_decoded)
            <= transfer_address
        ):
            return None

        def same_guarded_byte(decoded, expected: int) -> bool:
            if (
                decoded.id != x86_const.X86_INS_CMP
                or len(decoded.operands) != 2
                or decoded.operands[0].type != X86_OP_MEM
                or decoded.operands[0].size != 1
                or decoded.operands[1].type != X86_OP_IMM
                or decoded.operands[1].imm & 0xFFFF_FFFF != expected
            ):
                return False
            memory = decoded.operands[0].mem
            return (
                memory.segment == guarded_memory.segment
                and memory.base == guarded_memory.base
                and memory.index == guarded_memory.index
                and memory.scale == guarded_memory.scale
                and memory.disp == guarded_memory.disp
            )

        if not same_guarded_byte(lower_compare_decoded, 0):
            return None
        if (
            upper_compare_decoded.id != x86_const.X86_INS_CMP
            or len(upper_compare_decoded.operands) != 2
            or upper_compare_decoded.operands[1].type != X86_OP_IMM
        ):
            return None
        bound = upper_compare_decoded.operands[1].imm & 0xFFFF_FFFF
        if bound == 0 or not same_guarded_byte(upper_compare_decoded, bound):
            return None
        if pushed_arguments == 0:
            incoming = self.incoming_edges.get(sign_extend.address, set())
            if incoming != {(upper_branch.address, "fallthrough")}:
                return None
        elif (
            sign_extend.address in self.block_starts
            or any(
                address in self.block_starts
                for address in pushed_addresses[:-1]
            )
        ):
            return None
        return lower_compare, "signed-memory-range", bound, 0, bound - 1

    def _movzx_guard_for_index(
        self, transfer_address: int, index_register: int
    ) -> tuple[Instruction, str, int, int, int] | None:
        """Prove ``0 <= index < 2**(8*src_size)`` from a zero-extend load.

        When the index register is loaded by ``movzx reg, byte/word ptr [...]``
        and no intervening instruction clobbers it, the value is inherently
        bounded to ``0..255`` (byte) or ``0..65535`` (word).
        """
        index_family = self._register_family(index_register)

        cursor = transfer_address
        for _ in range(16):
            candidate = self._previous_instruction(cursor)
            if candidate is None:
                return None
            decoded = self._owned_decoded(candidate.address)

            if decoded.group(CS_GRP_CALL) and index_family not in {
                "ebx",
                "esi",
                "edi",
                "ebp",
            }:
                return None

            # Reject jumps, returns, and IRETs.  Calls and arithmetic
            # (including EFLAGS writes) are allowed between movzx and the
            # transfer only when the index register is callee-saved.
            if (
                decoded.group(CS_GRP_JUMP)
                or decoded.group(CS_GRP_RET)
                or decoded.group(CS_GRP_IRET)
            ):
                return None

            # Check if this instruction writes the index register.
            # movzx is special: Capstone does not populate regs_write for
            # it, so we must also examine the destination operand directly.
            is_movzx_to_index = (
                decoded.id == x86_const.X86_INS_MOVZX
                and len(decoded.operands) >= 2
                and decoded.operands[0].type == X86_OP_REG
                and self._register_family(decoded.operands[0].reg)
                == index_family
            )
            index_written = any(
                self._register_family(reg) == index_family
                for reg in decoded.regs_write
                if reg != x86_const.X86_REG_EFLAGS
            )
            if index_written:
                # Some other instruction wrote the index register.
                return None
            if not is_movzx_to_index:
                cursor = candidate.address
                continue

            # Found a movzx to the index register.
            src_size = decoded.operands[1].size
            if src_size not in (1, 2):
                return None

            bound = (1 << (8 * src_size)) - 1
            return decoded, "movzx", bound, 0, bound

        return None

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
            guard = self._signed_memory_guard_for_index(
                instruction.address, memory.index
            )
        if guard is None:
            guard = self._movzx_guard_for_index(
                instruction.address, memory.index
            )
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
        require_relocated_entries = operator in {
            "signed-memory-range",
            "movzx",
        }
        relocation_types = {row.va: row.type for row in self.image.relocations}
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
            if (
                require_relocated_entries
                and relocation_types.get(entry_address) != 3
            ):
                self._computed_flow_blocker(
                    instruction,
                    f"{operator}-domain table entry lacks a type-3 relocation: "
                    f"index={index};address={entry_address:#x}",
                )
                return False
            target = int.from_bytes(raw, "little")
            # For type-3 HIGHLOW-relocated entries, the raw value is an RVA;
            # the loaded VA is raw + image_base.  Skip adjustment when the
            # raw value is already an absolute VA (synthetic test fixtures).
            if (
                relocation_types.get(entry_address) == 3
                and target < self.image.image_base
            ):
                target = (target + self.image.image_base) & 0xFFFF_FFFF
            if not _is_executable_span(self.image, target, 1):
                self._computed_flow_blocker(
                    instruction,
                    "jump-table target is not executable: "
                    f"index={index};entry={entry_address:#x};target={target:#x}",
                )
                return False
            entries.append(target)
            entry_rows.append((entry_address, raw, target))

        if not entries:
            # No executable entries found (e.g., all data in movzx table)
            self._computed_flow_blocker(
                instruction,
                "jump-table has no executable entries: "
                f"base={base:#x};indices={index_min}..{index_max}",
            )
            return False

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
            self.semantic_data_references.add(
                SemanticReference(
                    record_kind="data-reference",
                    address=instruction.address,
                    target=base,
                    provenance=(
                        f"bytes={instruction.bytes_hex};"
                        f"table={base:#x};entry-width={entry_width}"
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
                        is_function=flow_kind == "call",
                    )
                )
                self._add_edge(instruction.address, target, edge_kind)
                self._record_finite_target(target)
                self._enqueue(target, is_function=flow_kind == "call")
            self._record_fixpoint_update()
        return True

    @staticmethod
    def _absolute_memory_operand(operand) -> int | None:
        if (
            operand.type != X86_OP_MEM
            or operand.mem.segment != X86_REG_INVALID
            or operand.mem.base != X86_REG_INVALID
            or operand.mem.index != X86_REG_INVALID
        ):
            return None
        return operand.mem.disp & 0xFFFF_FFFF

    def _count_slot_loaded_before(
        self, address: int, index_register: int
    ) -> int | None:
        """Find the local exact counter load feeding an indexed transfer."""
        index_family = self._register_family(index_register)
        cursor = address
        for _ in range(16):
            previous = self._previous_instruction(cursor)
            if previous is None:
                return None
            decoded = self._owned_decoded(previous.address)
            if (
                decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and decoded.operands[0].size == 4
                and self._register_family(decoded.operands[0].reg)
                == index_family
            ):
                source_address = self._absolute_memory_operand(
                    decoded.operands[1]
                )
                if (
                    source_address is not None
                    and decoded.operands[1].size == 4
                ):
                    return source_address
                return None
            if (
                decoded.group(CS_GRP_CALL)
                or decoded.group(CS_GRP_JUMP)
                or decoded.group(CS_GRP_RET)
                or any(
                    self._register_family(register) == index_family
                    for register in decoded.regs_write
                )
                or previous.address in self.block_starts
            ):
                return None
            cursor = previous.address
        return None

    def _registrar_function_entry(self, address: int) -> int | None:
        if len(self.sorted_function_addresses_cache) != len(
            self.function_addresses
        ):
            self.sorted_function_addresses_cache = tuple(
                sorted(self.function_addresses)
            )
        index = bisect_right(self.sorted_function_addresses_cache, address)
        if index == 0:
            return None
        return self.sorted_function_addresses_cache[index - 1]

    def _function_returns_byte(self, entry: int) -> bool:
        """Prove that every reachable return has EAX in unsigned-byte range."""
        following_entry = min(
            (row for row in self.function_addresses if row > entry),
            default=0x1_0000_0000,
        )
        states: dict[int, frozenset[str]] = {entry: frozenset()}
        pending = [entry]
        queued = {entry}
        returns = 0
        iterations = 0
        while pending:
            address = heapq.heappop(pending)
            queued.remove(address)
            if address not in self.instructions:
                return False
            decoded = self._owned_decoded(address)
            bounded = set(states[address])
            if decoded.group(CS_GRP_RET):
                returns += 1
                if "eax" not in bounded:
                    return False
                continue

            if decoded.group(CS_GRP_CALL):
                bounded.difference_update({"eax", "ecx", "edx"})
            elif (
                decoded.mnemonic == "movzx"
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and decoded.operands[0].size == 4
                and decoded.operands[1].size == 1
            ):
                bounded.add(
                    self._register_family(decoded.operands[0].reg)
                )
            elif (
                decoded.mnemonic in {"mov", "movsx"}
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and decoded.operands[0].size == 4
                and decoded.operands[1].type == X86_OP_REG
            ):
                destination = self._register_family(decoded.operands[0].reg)
                source = self._register_family(decoded.operands[1].reg)
                if source in bounded:
                    bounded.add(destination)
                else:
                    bounded.discard(destination)
            elif (
                decoded.mnemonic == "mov"
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and decoded.operands[0].size == 4
                and decoded.operands[1].type == X86_OP_IMM
            ):
                destination = self._register_family(decoded.operands[0].reg)
                value = decoded.operands[1].imm & 0xFFFF_FFFF
                if value <= 0xFF:
                    bounded.add(destination)
                else:
                    bounded.discard(destination)
            elif (
                decoded.mnemonic == "xor"
                and len(decoded.operands) == 2
                and all(row.type == X86_OP_REG for row in decoded.operands)
                and self._register_family(decoded.operands[0].reg)
                == self._register_family(decoded.operands[1].reg)
            ):
                bounded.add(
                    self._register_family(decoded.operands[0].reg)
                )
            else:
                written = {
                    self._register_family(row.reg)
                    for row in decoded.operands
                    if row.type == X86_OP_REG
                    and row.size == 4
                    and row.access & CS_AC_WRITE
                }
                written.update(
                    self._register_family(row)
                    for row in decoded.regs_write
                    if self._register_family(row)
                    in {"eax", "ebx", "ecx", "edx", "esi", "edi", "ebp"}
                )
                bounded.difference_update(written)

            next_address = decoded.address + decoded.size
            if decoded.group(CS_GRP_CALL):
                successors = (next_address,)
            elif decoded.group(CS_GRP_JUMP):
                target = self._direct_target(decoded)
                if target is None:
                    table = self.jump_tables.get(decoded.address)
                    if table is None or table.flow_kind != "jump":
                        return False
                    successors = table.targets
                else:
                    successors = (
                        (target,)
                        if decoded.id in {X86_INS_JMP, X86_INS_LJMP}
                        else (target, next_address)
                    )
            else:
                successors = (next_address,)
            output = frozenset(bounded)
            for successor in successors:
                if (
                    not entry <= successor < following_entry
                    or successor not in self.instructions
                ):
                    return False
                previous = states.get(successor)
                updated = output if previous is None else previous & output
                if updated == previous:
                    continue
                states[successor] = updated
                if successor not in queued:
                    heapq.heappush(pending, successor)
                    queued.add(successor)
            iterations += 1
            self.high_water["max_summary_iterations"] = max(
                self.high_water["max_summary_iterations"], iterations
            )
            self.limits.check("max_summary_iterations", iterations)
        return returns > 0

    def _byte_return_producer_before(
        self, transfer_address: int, index_register: int
    ) -> tuple[DirectCall, int] | None:
        index_family = self._register_family(index_register)
        cursor = transfer_address
        source_family = None
        for _ in range(16):
            previous = self._previous_instruction(cursor)
            if previous is None:
                return None
            decoded = self._owned_decoded(previous.address)
            if (
                decoded.mnemonic == "movsx"
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and self._register_family(decoded.operands[0].reg)
                == index_family
                and decoded.operands[1].type == X86_OP_REG
                and decoded.operands[1].size == 2
            ):
                source_family = self._register_family(
                    decoded.operands[1].reg
                )
                cursor = previous.address
                break
            if any(
                self._register_family(row) == index_family
                for row in decoded.regs_write
            ):
                return None
            cursor = previous.address
        if source_family != "eax":
            return None
        for _ in range(128):
            previous = self._previous_instruction(cursor)
            if previous is None:
                return None
            call = next(
                (
                    row
                    for row in self.direct_calls
                    if row.address == previous.address
                ),
                None,
            )
            if call is not None:
                if any(
                    row.source < call.address < row.target <= cursor
                    for row in self.edges
                ):
                    return None
                if self._function_returns_byte(call.target):
                    return call, call.target
                return None
            decoded = self._owned_decoded(previous.address)
            if any(
                self._register_family(row) == source_family
                for row in decoded.regs_write
            ):
                return None
            cursor = previous.address
        return None

    def _recover_byte_return_table(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        if (
            flow_kind != "call"
            or len(decoded.operands) != 1
            or decoded.operands[0].type != X86_OP_MEM
        ):
            return False
        operand = decoded.operands[0]
        memory = operand.mem
        if (
            operand.size != 4
            or memory.segment != X86_REG_INVALID
            or memory.base != X86_REG_INVALID
            or memory.index == X86_REG_INVALID
            or memory.scale != 4
        ):
            return False
        producer = self._byte_return_producer_before(
            instruction.address, memory.index
        )
        if producer is None:
            return False
        producer_call, producer_entry = producer
        table_base = memory.disp & 0xFFFF_FFFF
        entries = []
        entry_rows = []
        for index in range(256):
            entry_address = table_base + index * 4
            try:
                raw = self.image.read(entry_address, 4)
            except ValueError:
                return False
            target = int.from_bytes(raw, "little")
            if not _is_executable_span(self.image, target, 1):
                return False
            entries.append(target)
            entry_rows.append((entry_address, raw, target))
        new_total = self.jump_table_entry_count + len(entries)
        self._check_count("max_jump_table_entries", new_total)
        provenance = (
            f"producer-call={producer_call.address:#x};"
            f"producer-entry={producer_entry:#x};range=0..255;"
            f"table={table_base:#x}"
        )
        table = JumpTable(
            address=instruction.address,
            flow_kind=flow_kind,
            guard_address=producer_entry,
            guard_operator="byte-return-summary",
            guard_bound=0xFF,
            base=table_base,
            entry_width=4,
            index_min=0,
            index_max=0xFF,
            raw_entries=tuple(entries),
            targets=tuple(entries),
        )
        prior = self.jump_tables.get(instruction.address)
        if prior is not None and prior != table:
            raise CfgRecoveryError(
                f"conflicting computed-flow table at {instruction.address:#x}"
            )
        if prior is not None:
            return True
        self.jump_tables[instruction.address] = table
        self.jump_table_entry_count = new_total
        self._check_count("max_jump_tables", len(self.jump_tables))
        self.data_evidence.add(
            _DataEvidence(
                start=table_base,
                end=table_base + 256 * 4,
                provenance=provenance,
            )
        )
        for entry_address, raw, target in entry_rows:
            self.seed_records.add(
                SeedRecord(
                    address=target,
                    category="byte-return-callback-entry",
                    provenance_address=entry_address,
                    provenance_bytes=raw.hex(),
                    detail=provenance,
                    is_function=True,
                )
            )
            self._add_edge(
                instruction.address,
                target,
                "indirect-call-byte-return-table",
                provenance=provenance,
            )
            self._record_finite_target(target)
            self._enqueue(target, is_function=True)
        self._record_fixpoint_update()
        return True



    def _zero_excluding_guard(
        self, mutation_address: int, count_slot: int, transfer_address: int
    ) -> bool:
        cursor = mutation_address
        branch = None
        for _ in range(8):
            previous = self._previous_instruction(cursor)
            if previous is None:
                return False
            decoded = self._owned_decoded(previous.address)
            if decoded.group(CS_GRP_JUMP):
                branch = decoded
                break
            if (
                decoded.group(CS_GRP_CALL)
                or decoded.group(CS_GRP_RET)
                or x86_const.X86_REG_EFLAGS in decoded.regs_write
                or previous.address in self.block_starts
            ):
                return False
            cursor = previous.address
        if branch is None or branch.mnemonic not in {"jle", "je", "jbe"}:
            return False
        target = self._direct_target(branch)
        if target is None or target <= transfer_address:
            return False
        cursor = branch.address
        for _ in range(8):
            previous = self._previous_instruction(cursor)
            if previous is None:
                return False
            decoded = self._owned_decoded(previous.address)
            if (
                decoded.mnemonic == "cmp"
                and len(decoded.operands) == 2
                and self._absolute_memory_operand(decoded.operands[0])
                == count_slot
                and decoded.operands[0].size == 4
                and decoded.operands[1].type == X86_OP_IMM
                and decoded.operands[1].imm & 0xFFFF_FFFF == 0
            ):
                return True
            if (
                decoded.group(CS_GRP_CALL)
                or decoded.group(CS_GRP_JUMP)
                or decoded.group(CS_GRP_RET)
                or x86_const.X86_REG_EFLAGS in decoded.regs_write
                or previous.address in self.block_starts
            ):
                return False
            cursor = previous.address
        return False

    def _recover_zero_count_indexed_control(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        if (
            flow_kind != "call"
            or len(decoded.operands) != 1
            or decoded.operands[0].type != X86_OP_MEM
        ):
            return False
        operand = decoded.operands[0]
        memory = operand.mem
        if (
            operand.size != 4
            or memory.segment != X86_REG_INVALID
            or memory.base != X86_REG_INVALID
            or memory.index == X86_REG_INVALID
            or memory.scale != 4
        ):
            return False
        count_slot = self._count_slot_loaded_before(
            instruction.address, memory.index
        )
        if count_slot is None:
            return False
        try:
            initial = _read_loader_initialized(self.image, count_slot, 4)
        except ValueError:
            return False
        if initial != b"\0" * 4:
            return False
        mutations = [
            self._owned_decoded(address)
            for address in sorted(
                self.absolute_memory_writes.get(count_slot, ())
            )
        ]
        if any(
            row.mnemonic != "dec"
            or not self._zero_excluding_guard(
                row.address, count_slot, instruction.address
            )
            for row in mutations
        ):
            return False
        table_base = memory.disp & 0xFFFF_FFFF
        self.diagnostics.add(
            OwnershipDiagnostic(
                kind="proven-unreachable-control",
                address=instruction.address,
                detail=(
                    f"loader-zero counter remains zero: count={count_slot:#x};"
                    f"table={table_base:#x};guarded-decrements={len(mutations)};"
                    "pending-unreachable-residue-reconciliation"
                ),
            )
        )
        return True

    def _recover_registrar_table(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        """Prove a finite callback table populated by a bounded registrar."""
        if (
            flow_kind != "call"
            or len(decoded.operands) != 1
            or decoded.operands[0].type != X86_OP_MEM
        ):
            return False
        operand = decoded.operands[0]
        memory = operand.mem
        if (
            operand.size != 4
            or memory.segment != X86_REG_INVALID
            or memory.base != X86_REG_INVALID
            or memory.index == X86_REG_INVALID
            or memory.scale != 4
        ):
            return False
        table_base = memory.disp & 0xFFFF_FFFF
        count_slot = self._count_slot_loaded_before(
            instruction.address, memory.index
        )
        if count_slot is None:
            return False
        try:
            if _read_loader_initialized(self.image, count_slot, 4) != b"\0" * 4:
                return False
        except ValueError:
            return False

        stores = []
        for address in sorted(self.instructions):
            candidate = self._owned_decoded(address)
            if candidate.id != X86_INS_MOV or len(candidate.operands) != 2:
                continue
            destination = candidate.operands[0]
            if destination.type != X86_OP_MEM:
                continue
            destination_memory = destination.mem
            if (
                destination.size == 4
                and destination_memory.segment == X86_REG_INVALID
                and destination_memory.base == X86_REG_INVALID
                and destination_memory.index != X86_REG_INVALID
                and destination_memory.scale == 4
                and destination_memory.disp & 0xFFFF_FFFF == table_base
                and candidate.operands[1].type == X86_OP_REG
            ):
                loaded_slot = self._count_slot_loaded_before(
                    address, destination_memory.index
                )
                if loaded_slot == count_slot:
                    stores.append(candidate)
        if len(stores) != 1:
            return False
        store = stores[0]
        registrar_entry = self._registrar_function_entry(store.address)
        if registrar_entry is None:
            return False
        following_entry = min(
            (
                entry
                for entry in self.function_addresses
                if entry > registrar_entry
            ),
            default=0x1_0000_0000,
        )

        capacity_rows = []
        for address in sorted(self.instructions):
            if not registrar_entry <= address < following_entry:
                continue
            candidate = self._owned_decoded(address)
            if (
                candidate.mnemonic == "cmp"
                and len(candidate.operands) == 2
                and self._absolute_memory_operand(candidate.operands[0])
                == count_slot
                and candidate.operands[0].size == 4
                and candidate.operands[1].type == X86_OP_IMM
            ):
                capacity_rows.append(candidate)
        if len(capacity_rows) != 1:
            return False
        capacity_compare = capacity_rows[0]
        capacity = capacity_compare.operands[1].imm & 0xFFFF_FFFF
        if not 0 < capacity <= self.limits.max_jump_table_entries:
            return False
        capacity_branch = self.instructions.get(
            capacity_compare.address + capacity_compare.size
        )
        if capacity_branch is None:
            return False
        branch = self._owned_decoded(capacity_branch.address)
        if (
            branch.mnemonic not in {"jae", "jnb", "jne"}
            or not branch.group(CS_GRP_JUMP)
            or self._direct_target(branch) is None
        ):
            return False

        count_mutations = [
            self._owned_decoded(address)
            for address in sorted(
                self.absolute_memory_writes.get(count_slot, ())
            )
        ]
        if (
            not count_mutations
            or any(row.mnemonic not in {"inc", "dec"} for row in count_mutations)
            or sum(
                row.mnemonic == "inc"
                and registrar_entry <= row.address < following_entry
                for row in count_mutations
            )
            != 1
        ):
            return False

        try:
            initialized_table = _read_loader_initialized(
                self.image, table_base, capacity * 4
            )
        except ValueError:
            return False
        if initialized_table != b"\0" * len(initialized_table):
            return False

        callers = []
        for call in self._direct_calls_to(registrar_entry):
            push = self._previous_instruction(call.address)
            if push is None or push.address not in self.accepted_initializer_instructions:
                return False
            push_decoded = self._owned_decoded(push.address)
            if (
                push_decoded.mnemonic != "push"
                or len(push_decoded.operands) != 1
                or push_decoded.operands[0].type != X86_OP_IMM
            ):
                return False
            target = push_decoded.operands[0].imm & 0xFFFF_FFFF
            if not _is_executable_span(self.image, target, 1):
                return False
            callers.append((call, push, target))
        if not callers or len(callers) > capacity:
            return False

        targets = tuple(target for _call, _push, target in callers)
        new_total = self.jump_table_entry_count + len(targets)
        self._check_count("max_jump_table_entries", new_total)
        provenance = (
            f"registrar={registrar_entry:#x};count={count_slot:#x};"
            f"capacity={capacity};table={table_base:#x};callers="
            + ",".join(f"{call.address:#x}" for call, _push, _target in callers)
        )
        table = JumpTable(
            address=instruction.address,
            flow_kind=flow_kind,
            guard_address=capacity_compare.address,
            guard_operator="registrar-capacity",
            guard_bound=capacity,
            base=table_base,
            entry_width=4,
            index_min=0,
            index_max=len(targets) - 1,
            raw_entries=targets,
            targets=targets,
        )
        prior = self.jump_tables.get(instruction.address)
        if prior is not None and prior != table:
            raise CfgRecoveryError(
                f"conflicting computed-flow table at {instruction.address:#x}"
            )
        if prior is not None:
            return True
        self.jump_tables[instruction.address] = table
        self.jump_table_entry_count = new_total
        self._check_count("max_jump_tables", len(self.jump_tables))
        self.data_evidence.add(
            _DataEvidence(
                start=table_base,
                end=table_base + capacity * 4,
                provenance=provenance,
            )
        )
        for call, push, target in callers:
            self.seed_records.add(
                SeedRecord(
                    address=target,
                    category="registrar-callback-entry",
                    provenance_address=push.address,
                    provenance_bytes=push.bytes_hex,
                    detail=(
                        f"{provenance};registrar-call={call.address:#x}"
                    ),
                    is_function=True,
                )
            )
            self._add_edge(
                instruction.address,
                target,
                "indirect-call-registrar-table",
                provenance=provenance,
            )
            self._record_finite_target(target)
            self._enqueue(target, is_function=True)
        self._record_fixpoint_update()
        return True

    def _recover_iat_terminal(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        if len(decoded.operands) != 1 or decoded.operands[0].type != X86_OP_MEM:
            return False
        memory = decoded.operands[0].mem
        if (
            decoded.operands[0].size != 4
            or memory.segment != X86_REG_INVALID
            or memory.base != X86_REG_INVALID
            or memory.index != X86_REG_INVALID
        ):
            return False
        iat_va = memory.disp & 0xFFFF_FFFF
        imported = next(
            (row for row in self.image.imports if row.iat_va == iat_va), None
        )
        if imported is None:
            return False
        self.terminal_external_edges.add(
            TerminalExternalEdge(
                source=instruction.address,
                flow_kind=flow_kind,
                iat_va=iat_va,
                dll=imported.dll,
                name=imported.name,
                ordinal=imported.ordinal,
                provenance=(
                    f"instruction={instruction.address:#x};"
                    f"bytes={instruction.bytes_hex};iat={iat_va:#x};"
                    f"dll={imported.dll};"
                    f"symbol={imported.name or imported.ordinal}"
                ),
            )
        )
        escaped_targets = set()
        cursor = instruction.address
        for _ in range(32):
            previous = self._previous_instruction(cursor)
            if previous is None:
                break
            pushed = self._owned_decoded(previous.address)
            if pushed.mnemonic != "push" or len(pushed.operands) != 1:
                break
            operand = pushed.operands[0]
            if (
                operand.type == X86_OP_IMM
                and pushed.imm_size == 4
                and any(
                    row.type == 3
                    and row.va == pushed.address + pushed.imm_offset
                    for row in self.image.relocations
                )
            ):
                value = operand.imm & 0xFFFF_FFFF
                if _is_executable_span(self.image, value, 1):
                    escaped_targets.add(value)
            cursor = previous.address
        if escaped_targets:
            provenance = (
                f"unmodelled-import={imported.dll}!"
                f"{imported.name or imported.ordinal};"
                "relocated-cdecl-arguments="
                + ",".join(
                    f"{target:#x}" for target in sorted(escaped_targets)
                )
            )
            self.external_escapes.add(
                ExternalCodePointerEscape(
                    source=instruction.address,
                    target_import_iat=iat_va,
                    possible_internal_targets=tuple(sorted(escaped_targets)),
                    provenance=provenance,
                )
            )
            self.diagnostics.add(
                OwnershipDiagnostic(
                    kind="external-code-pointer-escape",
                    address=instruction.address,
                    detail=provenance,
                )
            )
        return True

    def _recover_global_slot_targets(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        if len(decoded.operands) != 1 or decoded.operands[0].type != X86_OP_MEM:
            return False
        memory = decoded.operands[0].mem
        if (
            decoded.operands[0].size != 4
            or memory.segment != X86_REG_INVALID
            or memory.base != X86_REG_INVALID
            or memory.index != X86_REG_INVALID
        ):
            return False
        slot = memory.disp & 0xFFFF_FFFF
        result = self._finite_global_slot_values(slot, frozenset())
        if result is None:
            return False
        possible_values, slot_detail = result
        initial_bytes = _read_loader_initialized(self.image, slot, 4)
        writes = self.global_slot_writes.get(slot, ())
        nonzero = {value for value in possible_values if value}
        if not nonzero:
            self.diagnostics.add(
                OwnershipDiagnostic(
                    kind="proven-unreachable-control",
                    address=instruction.address,
                    detail=(
                        f"global slot remains zero: slot={slot:#x};"
                        f"writes={len(writes)}"
                    ),
                )
            )
            return True
        if any(
            not _is_executable_span(self.image, value, 1)
            for value in nonzero
        ):
            return False
        edge_kind = f"indirect-{flow_kind}-global-slot"
        provenance = f"slot={slot:#x};{slot_detail}"
        for target in sorted(nonzero):
            record = SeedRecord(
                address=target,
                category="global-function-pointer",
                provenance_address=slot,
                provenance_bytes=initial_bytes.hex(),
                detail=provenance,
                is_function=flow_kind == "call",
            )
            self.seed_records.add(record)
            edge = CfgEdge(instruction.address, target, edge_kind)
            if edge not in self.edges:
                self._record_fixpoint_update()
            self._add_edge(
                instruction.address,
                target,
                edge_kind,
                provenance=provenance,
            )
            self._record_finite_target(target)
            self._enqueue(target, is_function=flow_kind == "call")
        return True

    def _absolute_global_load_origins_before(
        self,
        address: int,
        register_family: str,
        function_entry: int,
        visited: frozenset[tuple[int, str]],
    ) -> tuple[tuple[int, int], ...] | None:
        """Trace register copies to complete absolute dword loads."""
        key = (address, f"absolute-global-load:{register_family}")
        if key in visited:
            return None
        definitions = self._register_definitions_across_blocks(
            address, register_family, function_entry
        )
        if not definitions:
            return None
        origins = set()
        for definition in sorted(definitions):
            decoded = self._owned_decoded(definition)
            if (
                decoded.id != X86_INS_MOV
                or len(decoded.operands) != 2
                or decoded.operands[0].type != X86_OP_REG
                or self._register_family(decoded.operands[0].reg)
                != register_family
            ):
                return None
            source = decoded.operands[1]
            if source.type == X86_OP_REG:
                forwarded = self._absolute_global_load_origins_before(
                    definition,
                    self._register_family(source.reg),
                    function_entry,
                    visited | {key},
                )
                if forwarded is None:
                    return None
                origins.update(forwarded)
                continue
            if (
                source.type != X86_OP_MEM
                or source.size != 4
                or source.mem.segment != X86_REG_INVALID
                or source.mem.base != X86_REG_INVALID
                or source.mem.index != X86_REG_INVALID
            ):
                return None
            slot = source.mem.disp & 0xFFFF_FFFF
            if (
                not _is_mapped_span(self.image, slot, 4)
                or _is_executable_span(self.image, slot, 4)
            ):
                return None
            origins.add((definition, slot))
        return tuple(sorted(origins)) or None

    def _recover_zero_origin_guarded_global_control(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        """Prove a control site unreachable behind a zero-only global root."""
        if (
            len(decoded.operands) != 1
            or decoded.operands[0].type != X86_OP_MEM
            or decoded.operands[0].mem.segment != X86_REG_INVALID
            or decoded.operands[0].mem.base == X86_REG_INVALID
            or decoded.operands[0].mem.index != X86_REG_INVALID
        ):
            return False
        function_entry = self._registrar_function_entry(instruction.address)
        if function_entry is None:
            return False
        node_family = self._register_family(
            decoded.operands[0].mem.base
        )
        node_definitions = self._register_definitions_across_blocks(
            instruction.address, node_family, function_entry
        )
        if not node_definitions:
            return False

        slots = set()
        transfer_guards = set()
        load_addresses = set()
        for definition in sorted(node_definitions):
            node_definition = self._owned_decoded(definition)
            if (
                node_definition.id != X86_INS_MOV
                or len(node_definition.operands) != 2
                or node_definition.operands[0].type != X86_OP_REG
                or self._register_family(node_definition.operands[0].reg)
                != node_family
                or node_definition.operands[1].type != X86_OP_REG
            ):
                return False
            current = node_definition.operands[1]
            guard = self._dominating_nonzero_guard(
                definition, current, function_entry
            )
            if guard is None:
                return False
            origins = self._absolute_global_load_origins_before(
                definition,
                self._register_family(current.reg),
                function_entry,
                frozenset(),
            )
            if origins is None:
                return False
            transfer_guards.add(guard)
            load_addresses.update(row[0] for row in origins)
            slots.update(row[1] for row in origins)
        if len(slots) != 1:
            return False
        slot = next(iter(slots))
        try:
            initial = _read_loader_initialized(self.image, slot, 4)
        except ValueError:
            return False
        if initial != b"\0\0\0\0":
            return False

        # Every reachable write must itself depend on a nonzero value loaded
        # from this same slot.  Starting from loader zero, the least fixed
        # point therefore contains no write and no control-site execution.
        writes = []
        for address in sorted(self.instructions):
            candidate = self._owned_decoded(address)
            for operand in candidate.operands:
                if not (
                    operand.type == X86_OP_MEM
                    and operand.access & CS_AC_WRITE
                    and operand.mem.segment == X86_REG_INVALID
                    and operand.mem.base == X86_REG_INVALID
                    and operand.mem.index == X86_REG_INVALID
                    and (operand.mem.disp & 0xFFFF_FFFF) == slot
                ):
                    continue
                if (
                    candidate.id != X86_INS_MOV
                    or len(candidate.operands) != 2
                    or candidate.operands[0].type != X86_OP_MEM
                    or candidate.operands[0].size != 4
                    or candidate.operands[1].type != X86_OP_REG
                ):
                    return False
                writer_entry = self._registrar_function_entry(address)
                if writer_entry is None:
                    return False
                source_family = self._register_family(
                    candidate.operands[1].reg
                )
                source_definitions = self._register_definitions_across_blocks(
                    address, source_family, writer_entry
                )
                if not source_definitions:
                    return False
                guarded = False
                for source_definition in sorted(source_definitions):
                    source_decoded = self._owned_decoded(source_definition)
                    if (
                        source_decoded.id != X86_INS_MOV
                        or len(source_decoded.operands) != 2
                        or source_decoded.operands[1].type != X86_OP_MEM
                        or source_decoded.operands[1].mem.segment
                        != X86_REG_INVALID
                        or source_decoded.operands[1].mem.base
                        == X86_REG_INVALID
                        or source_decoded.operands[1].mem.index
                        != X86_REG_INVALID
                    ):
                        return False
                    current_family = self._register_family(
                        source_decoded.operands[1].mem.base
                    )
                    origins = self._absolute_global_load_origins_before(
                        source_definition,
                        current_family,
                        writer_entry,
                        frozenset(),
                    )
                    if origins is None or {row[1] for row in origins} != {
                        slot
                    }:
                        return False
                    for load_address, _ in origins:
                        load = self._owned_decoded(load_address)
                        guard = self._dominating_nonzero_guard(
                            address, load.operands[0], writer_entry
                        )
                        if guard is None:
                            return False
                        transfer_guards.add(guard)
                        load_addresses.add(load_address)
                    guarded = True
                if not guarded:
                    return False
                writes.append(address)

        recorded_writes = {
            row.instruction_address
            for row in self.global_slot_writes.get(slot, ())
        }
        if set(writes) != recorded_writes:
            return False

        references = []
        for relocation in self.image.relocations:
            if relocation.type != 3:
                continue
            try:
                raw = _read_provenance(
                    self.image, relocation.va, 4, "global root relocation"
                )
            except ValueError:
                return False
            if int.from_bytes(raw, "little") != slot:
                continue
            owner = self.byte_owners.get(relocation.va)
            if owner is None:
                return False
            reference = self._owned_decoded(owner)
            if not any(
                operand.type == X86_OP_MEM
                and operand.mem.segment == X86_REG_INVALID
                and operand.mem.base == X86_REG_INVALID
                and operand.mem.index == X86_REG_INVALID
                and (operand.mem.disp & 0xFFFF_FFFF) == slot
                for operand in reference.operands
            ):
                return False
            references.append(owner)
        if not references or not load_addresses <= set(references):
            return False

        detail = (
            f"zero-origin-guarded-global={slot:#x};"
            "proof=loader-zero+all-relocated-references-owned+"
            "all-writes-nonzero-guarded;loads="
            + ",".join(f"{row:#x}" for row in sorted(load_addresses))
            + ";writes="
            + ",".join(f"{row:#x}" for row in sorted(writes))
            + ";guards="
            + ",".join(
                f"{condition:#x}/{branch:#x}"
                for condition, branch in sorted(transfer_guards)
            )
        )
        self.diagnostics.add(
            OwnershipDiagnostic(
                kind="proven-unreachable-control",
                address=instruction.address,
                detail=detail,
            )
        )
        self.data_evidence.add(_DataEvidence(slot, slot + 4, detail))
        return True

    def _indexed_global_loads_before(
        self,
        address: int,
        register_family: str,
        function_entry: int,
        visited: frozenset[tuple[int, str]],
    ) -> tuple[tuple[int, int, int, str], ...] | None:
        """Trace register copies to complete absolute indexed dword loads."""
        key = (address, f"indexed-global-load:{register_family}")
        if key in visited:
            return None
        definitions = self._register_definitions_across_blocks(
            address, register_family, function_entry
        )
        if not definitions:
            return None
        loads = set()
        for definition in sorted(definitions):
            decoded = self._owned_decoded(definition)
            if (
                decoded.id != X86_INS_MOV
                or len(decoded.operands) != 2
                or decoded.operands[0].type != X86_OP_REG
                or self._register_family(decoded.operands[0].reg)
                != register_family
            ):
                return None
            source = decoded.operands[1]
            if source.type == X86_OP_REG:
                forwarded = self._indexed_global_loads_before(
                    definition,
                    self._register_family(source.reg),
                    function_entry,
                    visited | {key},
                )
                if forwarded is None:
                    return None
                loads.update(forwarded)
                continue
            if (
                source.type != X86_OP_MEM
                or source.size != 4
                or source.mem.segment != X86_REG_INVALID
                or source.mem.base != X86_REG_INVALID
                or source.mem.index == X86_REG_INVALID
                or source.mem.scale != 4
            ):
                return None
            loads.add(
                (
                    definition,
                    source.mem.disp & 0xFFFF_FFFF,
                    source.mem.scale,
                    self._register_family(source.mem.index),
                )
            )
        return tuple(sorted(loads)) or None

    def _recover_indexed_global_slot_targets(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        """Resolve a callback loaded from a finite indexed global registry."""
        if (
            len(decoded.operands) != 1
            or decoded.operands[0].type != X86_OP_REG
        ):
            return False
        function_entry = self._registrar_function_entry(instruction.address)
        if function_entry is None:
            return False
        loads = self._indexed_global_loads_before(
            instruction.address,
            self._register_family(decoded.operands[0].reg),
            function_entry,
            frozenset(),
        )
        if loads is None:
            return False
        layouts = {(base, scale) for _, base, scale, _ in loads}
        if len(layouts) != 1:
            return False
        base, scale = next(iter(layouts))

        load_indices = set()
        load_details = []
        for load_address, _, _, index_family in loads:
            result = self._finite_register_values_before(
                load_address,
                index_family,
                function_entry,
                frozenset(),
            )
            if result is None:
                return False
            indices, detail = result
            if not indices:
                return False
            load_indices.update(indices)
            load_details.append(
                f"load={load_address:#x};index={index_family};"
                f"{detail.split(';caller=', 1)[0]}"
            )
        self._check_count("max_finite_values", len(load_indices))

        slot_addresses = set()
        values = set()
        for index in load_indices:
            address = base + index * scale
            if (
                address > 0xFFFF_FFFF
                or not _is_mapped_span(self.image, address, 4)
                or _is_executable_span(self.image, address, 4)
            ):
                return False
            slot_addresses.add(address)
            try:
                initial = _read_loader_initialized(self.image, address, 4)
            except ValueError:
                return False
            values.add(int.from_bytes(initial, "little"))

        write_details = []
        for write_address in sorted(self.instructions):
            write_decoded = self._owned_decoded(write_address)
            matching_destinations = [
                operand
                for operand in write_decoded.operands
                if (
                    operand.type == X86_OP_MEM
                    and operand.access & CS_AC_WRITE
                    and operand.mem.segment == X86_REG_INVALID
                    and operand.mem.base == X86_REG_INVALID
                    and operand.mem.index != X86_REG_INVALID
                    and (operand.mem.disp & 0xFFFF_FFFF) == base
                )
            ]
            if not matching_destinations:
                continue
            if (
                len(matching_destinations) != 1
                or write_decoded.id != X86_INS_MOV
                or len(write_decoded.operands) != 2
                or write_decoded.operands[0] is not matching_destinations[0]
                or matching_destinations[0].size != 4
                or matching_destinations[0].mem.scale != scale
            ):
                return False
            destination = matching_destinations[0]
            writer_entry = self._registrar_function_entry(write_address)
            if writer_entry is None:
                return False
            index_family = self._register_family(destination.mem.index)
            index_result = self._finite_register_values_before(
                write_address,
                index_family,
                writer_entry,
                frozenset(),
            )
            if index_result is None:
                return False
            write_indices, index_detail = index_result
            if not write_indices:
                return False
            if load_indices.isdisjoint(write_indices):
                continue
            value_result = self._finite_operand_values_before(
                write_address,
                write_decoded.operands[1],
                writer_entry,
                frozenset(),
            )
            if value_result is None:
                return False
            write_values, value_detail = value_result
            if not write_values:
                return False
            values.update(write_values)
            write_details.append(
                f"write={write_address:#x};indices="
                + ",".join(f"{row:#x}" for row in sorted(write_indices))
                + f";{index_detail.split(';caller=', 1)[0]};"
                + value_detail.split(";caller=", 1)[0]
            )

        for slot in sorted(slot_addresses):
            direct_values = self._finite_global_slot_values(
                slot, frozenset()
            )
            if direct_values is None:
                return False
            slot_values, slot_detail = direct_values
            values.update(slot_values)
            if self.global_slot_writes.get(slot):
                write_details.append(
                    f"direct-slot={slot:#x};{slot_detail}"
                )

        if 0 in values:
            guard = self._dominating_nonzero_guard(
                instruction.address, decoded.operands[0], function_entry
            )
            if guard is None:
                return False
            values.remove(0)
        if (
            not values
            or any(
                not _is_executable_span(self.image, target, 1)
                or target not in self.instructions
                or target not in self.function_addresses
                for target in values
            )
        ):
            return False

        provenance = (
            f"base={base:#x};scale={scale};indices="
            + ",".join(f"{row:#x}" for row in sorted(load_indices))
            + ";proof=all-owned-indexed-writes-finite;"
            + "|".join((*load_details, *write_details))
        )
        edge_kind = f"indirect-{flow_kind}-indexed-global-slot"
        for target in sorted(values):
            self.seed_records.add(
                SeedRecord(
                    address=target,
                    category="indexed-global-function-pointer",
                    provenance_address=instruction.address,
                    provenance_bytes=instruction.bytes_hex,
                    detail=provenance,
                    is_function=flow_kind == "call",
                )
            )
            edge = CfgEdge(instruction.address, target, edge_kind)
            if edge not in self.edges:
                self._record_fixpoint_update()
            self._add_edge(
                instruction.address,
                target,
                edge_kind,
                provenance=provenance,
            )
            self._record_finite_target(target)
            self._enqueue(target, is_function=flow_kind == "call")
        for slot in sorted(slot_addresses):
            self.data_evidence.add(
                _DataEvidence(slot, slot + 4, provenance)
            )
        return True

    def _finite_global_slot_values(
        self,
        slot: int,
        visited: frozenset[tuple[int, str]],
    ) -> tuple[frozenset[int], str] | None:
        key = (slot, "global-slot")
        if key in visited:
            return None
        try:
            initial_bytes = _read_loader_initialized(self.image, slot, 4)
        except ValueError:
            return None
        initial = int.from_bytes(initial_bytes, "little")
        possible_values = {initial}
        write_provenance = []
        writes = tuple(
            sorted(
                self.global_slot_writes.get(slot, ()),
                key=lambda row: (row.instruction_address, row.provenance),
            )
        )
        for write in writes:
            if write.value is not None:
                possible_values.add(write.value)
                write_provenance.append(write.provenance)
                continue
            if write.instruction_address not in self.instructions:
                return None
            decoded_write = self._owned_decoded(write.instruction_address)
            if decoded_write.id != X86_INS_MOV or len(decoded_write.operands) != 2:
                return None
            function_entry = self._registrar_function_entry(
                write.instruction_address
            )
            if function_entry is None:
                return None
            result = self._finite_operand_values_before(
                write.instruction_address,
                decoded_write.operands[1],
                function_entry,
                visited | {key},
            )
            if result is None:
                return None
            values, detail = result
            if not values:
                return None
            self._check_count("max_finite_values", len(values))
            possible_values.update(values)
            stable_detail = detail.split(";caller=", 1)[0]
            write_provenance.append(f"{write.provenance};{stable_detail}")
        self._check_count("max_finite_values", len(possible_values))
        detail = f"initial={initial:#x}"
        if write_provenance:
            detail += ";" + "|".join(write_provenance)
        return frozenset(possible_values), detail

    def _stack_argument_index_at(
        self, address: int, operand, function_entry: int
    ) -> int | None:
        if (
            operand.type != X86_OP_MEM
            or operand.mem.segment != X86_REG_INVALID
            or operand.mem.index != X86_REG_INVALID
            or operand.mem.base == X86_REG_INVALID
        ):
            return None
        base_family = self._register_family(operand.mem.base)
        if base_family not in {"ebp", "esp"}:
            return None
        if base_family == "ebp":
            first = self.instructions.get(function_entry)
            second = (
                None
                if first is None
                else self.instructions.get(first.address + first.size)
            )
            if first is not None and second is not None:
                first_decoded = self._owned_decoded(first.address)
                second_decoded = self._owned_decoded(second.address)
                canonical_frame = (
                    first_decoded.mnemonic == "push"
                    and len(first_decoded.operands) == 1
                    and first_decoded.operands[0].type == X86_OP_REG
                    and self._register_family(first_decoded.operands[0].reg)
                    == "ebp"
                    and second_decoded.id == X86_INS_MOV
                    and len(second_decoded.operands) == 2
                    and all(
                        row.type == X86_OP_REG
                        for row in second_decoded.operands
                    )
                    and self._register_family(second_decoded.operands[0].reg)
                    == "ebp"
                    and self._register_family(second_decoded.operands[1].reg)
                    == "esp"
                )
                if canonical_frame:
                    if self._register_definitions_across_blocks(
                        address, "ebp", function_entry
                    ) != frozenset({second.address}):
                        return None
                    if operand.mem.disp < 8 or operand.mem.disp % 4:
                        return None
                    return operand.mem.disp // 4 - 2
        stack_states = self._function_stack_states(function_entry)
        stack_state = (
            None if stack_states is None else stack_states.get(address)
        )
        if stack_state is None:
            stack_state = self._linear_stack_state_before(
                address, function_entry
            )
        if stack_state is None:
            return None
        sp_delta, bp_delta = stack_state
        base_delta = sp_delta if base_family == "esp" else bp_delta
        if base_delta is None:
            return None
        logical_offset = base_delta + operand.mem.disp
        if logical_offset < 4 or logical_offset % 4:
            return None
        return logical_offset // 4 - 1

    def _linear_stack_state_before(
        self, address: int, function_entry: int
    ) -> tuple[int, int | None] | None:
        """Prove an early stack state without depending on a complex tail."""
        if address < function_entry:
            return None
        cursor = function_entry
        predecessor: int | None = None
        sp_delta = 0
        bp_delta: int | None = None
        for _ in range(128):
            instruction = self.instructions.get(cursor)
            if instruction is None:
                return None
            if predecessor is not None and any(
                source != predecessor
                for source, _kind in self.incoming_edges.get(cursor, ())
            ):
                return None
            if cursor == address:
                return sp_delta, bp_delta
            if cursor > address or cursor + instruction.size > address:
                return None
            decoded = self._owned_decoded(cursor)
            if (
                decoded.group(CS_GRP_CALL)
                or decoded.group(CS_GRP_JUMP)
                or decoded.group(CS_GRP_RET)
                or decoded.group(CS_GRP_IRET)
            ):
                return None

            handled_esp_write = False
            handled_ebp_write = False
            if decoded.mnemonic == "push":
                sp_delta -= 4
                handled_esp_write = True
            elif decoded.mnemonic == "pop":
                sp_delta += 4
                handled_esp_write = True
            elif (
                decoded.mnemonic in {"add", "sub"}
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and self._register_family(decoded.operands[0].reg) == "esp"
                and decoded.operands[1].type == X86_OP_IMM
            ):
                amount = decoded.operands[1].imm & 0xFFFF_FFFF
                sp_delta += (
                    amount if decoded.mnemonic == "add" else -amount
                )
                handled_esp_write = True
            elif (
                decoded.mnemonic == "mov"
                and len(decoded.operands) == 2
                and all(row.type == X86_OP_REG for row in decoded.operands)
            ):
                destination = self._register_family(decoded.operands[0].reg)
                source = self._register_family(decoded.operands[1].reg)
                if destination == "ebp" and source == "esp":
                    bp_delta = sp_delta
                    handled_ebp_write = True
                elif destination == "ebp":
                    bp_delta = None
                    handled_ebp_write = True
                elif destination == "esp" and source == "ebp":
                    if bp_delta is None:
                        return None
                    sp_delta = bp_delta
                    handled_esp_write = True
            elif decoded.mnemonic == "leave":
                if bp_delta is None:
                    return None
                sp_delta = bp_delta + 4
                handled_esp_write = True
                handled_ebp_write = True

            written_families = {
                self._register_family(register)
                for register in decoded.regs_write
            }
            if "esp" in written_families and not handled_esp_write:
                return None
            if "ebp" in written_families and not handled_ebp_write:
                bp_delta = None
            predecessor = cursor
            cursor += instruction.size
        return None

    def _register_argument_proof_across_blocks(
        self,
        address: int,
        register_family: str,
        function_entry: int,
    ) -> tuple[int, frozenset[int]] | None:
        cache_key = (
            function_entry,
            register_family,
            self._summary_fact_signature(),
        )
        cached = self.argument_state_cache.get(cache_key)
        if cached is not None:
            return cached.get(address)
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        states: dict[int, tuple[int, frozenset[int]] | None] = {
            function_entry: None
        }
        pending = [function_entry]
        queued = {function_entry}
        iterations = 0

        while pending:
            current = heapq.heappop(pending)
            queued.remove(current)
            if current not in self.instructions:
                return None
            decoded = self._owned_decoded(current)
            incoming = states[current]
            writes_family = any(
                self._register_family(row) == register_family
                for row in decoded.regs_write
            ) or any(
                row.type == X86_OP_REG
                and row.access & CS_AC_WRITE
                and self._register_family(row.reg) == register_family
                for row in decoded.operands
            )
            if (
                decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and self._register_family(decoded.operands[0].reg)
                == register_family
            ):
                source = decoded.operands[1]
                if (
                    source.type == X86_OP_REG
                    and self._register_family(source.reg) == register_family
                ):
                    output = incoming
                else:
                    argument_index = self._stack_argument_index_at(
                        current, source, function_entry
                    )
                    output = (
                        None
                        if argument_index is None
                        else (argument_index, frozenset({current}))
                    )
            elif (
                decoded.group(CS_GRP_CALL)
                and register_family in {"eax", "ecx", "edx"}
            ) or writes_family:
                output = None
            else:
                output = incoming

            next_address = decoded.address + decoded.size
            if decoded.group(CS_GRP_RET) or decoded.group(CS_GRP_IRET):
                successors: tuple[int, ...] = ()
            elif decoded.group(CS_GRP_CALL):
                successors = (next_address,)
            elif decoded.group(CS_GRP_JUMP):
                successors = tuple(
                    sorted(
                        self.non_call_successors.get(decoded.address, ())
                    )
                )
                if not successors:
                    return None
            else:
                successors = (next_address,)
            for successor in successors:
                if not function_entry <= successor < following_entry:
                    continue
                if successor not in self.instructions:
                    return None
                if successor not in states:
                    updated = output
                else:
                    previous = states[successor]
                    if previous is None or output is None:
                        updated = None
                    elif previous[0] != output[0]:
                        updated = None
                    else:
                        updated = (previous[0], previous[1] | output[1])
                if successor in states and updated == states[successor]:
                    continue
                states[successor] = updated
                if successor not in queued:
                    heapq.heappush(pending, successor)
                    queued.add(successor)
            iterations += 1
            self.high_water["max_summary_iterations"] = max(
                self.high_water["max_summary_iterations"], iterations
            )
            self.limits.check("max_summary_iterations", iterations)
        self.argument_state_cache[cache_key] = states
        return states.get(address)

    def _register_argument_index_across_blocks(
        self,
        address: int,
        register_family: str,
        function_entry: int,
    ) -> int | None:
        proof = self._register_argument_proof_across_blocks(
            address, register_family, function_entry
        )
        return None if proof is None else proof[0]

    def _register_definitions_across_blocks(
        self,
        address: int,
        register_family: str,
        function_entry: int,
    ) -> frozenset[int] | None:
        cache_key = (
            function_entry,
            register_family,
            self._summary_fact_signature(),
        )
        cached = self.definition_state_cache.get(cache_key)
        if cached is not None:
            return cached.get(address)
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        states: dict[int, frozenset[int] | None] = {function_entry: None}
        pending = [function_entry]
        queued = {function_entry}
        iterations = 0
        while pending:
            current = heapq.heappop(pending)
            queued.remove(current)
            if current not in self.instructions:
                return None
            decoded = self._owned_decoded(current)
            incoming = states[current]
            writes_family = any(
                self._register_family(row) == register_family
                for row in decoded.regs_write
            ) or any(
                row.type == X86_OP_REG
                and row.access & CS_AC_WRITE
                and self._register_family(row.reg) == register_family
                for row in decoded.operands
            )
            if (
                decoded.id in {X86_INS_MOV, X86_INS_LEA}
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and self._register_family(decoded.operands[0].reg)
                == register_family
            ):
                source = decoded.operands[1]
                if (
                    decoded.id == X86_INS_MOV
                    and source.type == X86_OP_REG
                    and self._register_family(source.reg) == register_family
                ):
                    output = incoming
                else:
                    output = frozenset({current})
            elif (
                decoded.id == X86_INS_XOR
                and len(decoded.operands) == 2
                and all(row.type == X86_OP_REG for row in decoded.operands)
                and decoded.operands[0].size == 4
                and self._register_family(decoded.operands[0].reg)
                == register_family
                and self._register_family(decoded.operands[1].reg)
                == register_family
            ):
                output = frozenset({current})
            elif decoded.group(CS_GRP_CALL) and register_family == "eax":
                # EAX is defined by the call return.  Consumers still have
                # to prove the callee's return domain explicitly; retaining
                # the definition lets those fail-closed proofs inspect it.
                output = frozenset({current})
            elif (
                decoded.group(CS_GRP_CALL)
                and register_family in {"eax", "ecx", "edx"}
            ) or writes_family:
                output = None
            else:
                output = incoming

            next_address = decoded.address + decoded.size
            if decoded.group(CS_GRP_RET) or decoded.group(CS_GRP_IRET):
                successors: tuple[int, ...] = ()
            elif decoded.group(CS_GRP_CALL):
                successors = (next_address,)
            elif decoded.group(CS_GRP_JUMP):
                successors = tuple(
                    sorted(
                        self.non_call_successors.get(decoded.address, ())
                    )
                )
                if not successors:
                    return None
            else:
                successors = (next_address,)
            for successor in successors:
                if not function_entry <= successor < following_entry:
                    continue
                if successor not in self.instructions:
                    return None
                if successor not in states:
                    updated = output
                else:
                    previous = states[successor]
                    if previous is None or output is None:
                        updated = None
                    else:
                        updated = previous | output
                if successor in states and updated == states[successor]:
                    continue
                states[successor] = updated
                if successor not in queued:
                    heapq.heappush(pending, successor)
                    queued.add(successor)
            iterations += 1
            self.high_water["max_summary_iterations"] = max(
                self.high_water["max_summary_iterations"], iterations
            )
            self.limits.check("max_summary_iterations", iterations)
        self.definition_state_cache[cache_key] = states
        return states.get(address)

    def _finite_argument_values(
        self,
        function_entry: int,
        argument_index: int,
        visited: frozenset[tuple[int, str]],
    ) -> tuple[frozenset[int], str] | None:
        key = (function_entry, f"argument:{argument_index}")
        if key in visited:
            return None
        cache_key = (
            function_entry,
            argument_index,
            self._summary_fact_signature(),
        )
        if cache_key in self.finite_argument_cache:
            return self.finite_argument_cache[cache_key]
        callers = self._direct_calls_to(function_entry)
        if not callers:
            self.finite_argument_cache[cache_key] = None
            return None
        values: set[int] = set()
        provenance = []
        for call in callers:
            remaining = argument_index
            cursor = call.address
            result = None
            for _ in range(32):
                previous = self._previous_instruction(cursor)
                if previous is None:
                    break
                decoded = self._owned_decoded(previous.address)
                if decoded.mnemonic == "push" and len(decoded.operands) == 1:
                    if remaining == 0:
                        caller_entry = self._registrar_function_entry(
                            call.address
                        )
                        if caller_entry is None:
                            self.finite_argument_cache[cache_key] = None
                            return None
                        result = self._finite_operand_values_before(
                            previous.address,
                            decoded.operands[0],
                            caller_entry,
                            visited | {key},
                        )
                        if (
                            result is None
                            and caller_entry == function_entry
                            and decoded.operands[0].type == X86_OP_REG
                            and self._register_argument_index_across_blocks(
                                previous.address,
                                self._register_family(
                                    decoded.operands[0].reg
                                ),
                                function_entry,
                            )
                            == argument_index
                        ):
                            result = (
                                frozenset(),
                                f"recursive-forward=argument:{argument_index}",
                            )
                        break
                    remaining -= 1
                elif (
                    decoded.group(CS_GRP_CALL)
                    or decoded.group(CS_GRP_JUMP)
                    or decoded.group(CS_GRP_RET)
                    or any(
                        self._register_family(row) == "esp"
                        for row in decoded.regs_write
                    )
                ):
                    break
                cursor = previous.address
                if previous.address in self.block_starts:
                    break
            if result is None:
                self.finite_argument_cache[cache_key] = None
                return None
            caller_values, detail = result
            values.update(caller_values)
            provenance.append(f"caller={call.address:#x}:{detail}")
        if not values:
            self.finite_argument_cache[cache_key] = None
            return None
        self._check_count("max_contexts_per_entry", len(callers))
        self._check_count("max_finite_values", len(values))
        final = (
            frozenset(values),
            f"argument={argument_index};" + "|".join(provenance),
        )
        self.finite_argument_cache[cache_key] = final
        return final

    def _finite_stack_slot_before(
        self,
        address: int,
        *,
        base_family: str,
        displacement: int,
        function_entry: int,
        visited: frozenset[tuple[int, str]],
    ) -> tuple[frozenset[int], str] | None:
        key = (address, f"stack:{base_family}:{displacement}")
        if key in visited:
            return None
        stack_states = self._function_stack_states(function_entry)
        argument_result: tuple[frozenset[int], str] | None = None
        logical_offset: int | None = None
        if stack_states is not None and address in stack_states:
            sp_delta, bp_delta = stack_states[address]
            base_delta = sp_delta if base_family == "esp" else bp_delta
            if base_delta is not None:
                logical_offset = base_delta + displacement
                if logical_offset >= 4 and logical_offset % 4 == 0:
                    argument_index = logical_offset // 4 - 1
                    result = self._finite_argument_values(
                        function_entry,
                        argument_index,
                        visited | {key},
                    )
                    if result is not None:
                        values, detail = result
                        argument_result = (
                            values,
                            f"stack-argument={argument_index};{detail}",
                        )
        if argument_result is not None and stack_states is not None:
            following_entry = min(
                (
                    row
                    for row in self.function_addresses
                    if row > function_entry
                ),
                default=0x1_0000_0000,
            )
            reaching_writes = []
            for write_address, write_state in sorted(stack_states.items()):
                if not function_entry <= write_address < following_entry:
                    continue
                decoded_write = self._owned_decoded(write_address)
                if decoded_write.id != X86_INS_MOV or len(
                    decoded_write.operands
                ) != 2:
                    continue
                destination = decoded_write.operands[0]
                if (
                    destination.type != X86_OP_MEM
                    or destination.size != 4
                    or destination.mem.segment != X86_REG_INVALID
                    or destination.mem.index != X86_REG_INVALID
                    or destination.mem.base == X86_REG_INVALID
                ):
                    continue
                write_base = self._register_family(destination.mem.base)
                if write_base not in {"esp", "ebp"}:
                    continue
                write_sp, write_bp = write_state
                write_base_delta = (
                    write_sp if write_base == "esp" else write_bp
                )
                if (
                    write_base_delta is None
                    or write_base_delta + destination.mem.disp
                    != logical_offset
                    or not self._reachable_within_function(
                        function_entry,
                        write_address,
                        function_entry,
                        following_entry,
                    )
                    or not self._reachable_within_function(
                        write_address,
                        address,
                        function_entry,
                        following_entry,
                    )
                ):
                    continue
                reaching_writes.append(decoded_write)
            if reaching_writes:
                values = set(argument_result[0])
                details = [argument_result[1]]
                for decoded_write in reaching_writes:
                    write_result = self._finite_operand_values_before(
                        decoded_write.address,
                        decoded_write.operands[1],
                        function_entry,
                        visited | {key},
                    )
                    if write_result is None:
                        return None
                    write_values, write_detail = write_result
                    values.update(write_values)
                    details.append(
                        f"stack-write={decoded_write.address:#x};"
                        f"{write_detail}"
                    )
                return frozenset(values), ";".join(details)
        if logical_offset is not None:
            output_results = []
            for call in sorted(
                (
                    row
                    for row in self.direct_calls
                    if function_entry <= row.address < address
                ),
                key=lambda row: row.address,
                reverse=True,
            )[:128]:
                output = self._finite_call_output_to_stack(
                    call,
                    address,
                    logical_offset,
                    function_entry,
                    visited | {key},
                )
                if output is not None:
                    output_results.append(output)
            if len(output_results) == 1:
                return output_results[0]
        cursor = address
        for _ in range(128):
            previous = self._previous_instruction(cursor)
            if previous is None or previous.address < function_entry:
                return argument_result
            decoded = self._owned_decoded(previous.address)
            if decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                destination = decoded.operands[0]
                if (
                    destination.type == X86_OP_MEM
                    and destination.mem.segment == X86_REG_INVALID
                    and destination.mem.index == X86_REG_INVALID
                    and destination.mem.base != X86_REG_INVALID
                    and self._register_family(destination.mem.base)
                    == base_family
                    and destination.mem.disp == displacement
                ):
                    result = self._finite_operand_values_before(
                        previous.address,
                        decoded.operands[1],
                        function_entry,
                        visited | {key},
                    )
                    if result is None:
                        return None
                    values, detail = result
                    return (
                        values,
                        f"spill={base_family}{displacement:+#x};"
                        f"store={previous.address:#x};{detail}",
                    )
            if (
                decoded.group(CS_GRP_CALL)
                or decoded.group(CS_GRP_JUMP)
                or decoded.group(CS_GRP_RET)
                or previous.address in self.block_starts
                or (
                    base_family == "esp"
                    and any(
                        self._register_family(row) == "esp"
                        for row in decoded.regs_write
                    )
                )
            ):
                return argument_result
            cursor = previous.address
        return argument_result

    def _finite_call_output_to_stack(
        self,
        call: DirectCall,
        read_address: int,
        logical_offset: int,
        function_entry: int,
        visited: frozenset[tuple[int, str]],
    ) -> tuple[frozenset[int], str] | None:
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        if self._reachable_within_function(
            function_entry,
            read_address,
            function_entry,
            following_entry,
            excluded=call.address,
        ):
            return None
        stack_states = self._function_stack_states(function_entry)
        if stack_states is None:
            return None
        for candidate in sorted(self.instructions):
            if not call.address < candidate < read_address:
                continue
            decoded = self._owned_decoded(candidate)
            if decoded.group(CS_GRP_CALL):
                return None
            for operand in decoded.operands:
                if (
                    operand.type != X86_OP_MEM
                    or not operand.access & CS_AC_WRITE
                    or operand.mem.segment != X86_REG_INVALID
                    or operand.mem.index != X86_REG_INVALID
                    or operand.mem.base == X86_REG_INVALID
                ):
                    continue
                base_family = self._register_family(operand.mem.base)
                if base_family not in {"esp", "ebp"}:
                    continue
                state = stack_states.get(candidate)
                if state is None:
                    return None
                base_delta = state[0] if base_family == "esp" else state[1]
                if (
                    base_delta is not None
                    and base_delta + operand.mem.disp == logical_offset
                ):
                    return None

        matches = []
        for argument_index in range(16):
            pushed = self._pushed_call_argument(
                call.address, argument_index
            )
            if pushed is None:
                break
            push_instruction, operand, caller_entry = pushed
            if caller_entry != function_entry or operand.type != X86_OP_REG:
                continue
            definitions = self._register_definitions_across_blocks(
                push_instruction.address,
                self._register_family(operand.reg),
                function_entry,
            )
            if not definitions or len(definitions) != 1:
                continue
            definition_address = next(iter(definitions))
            definition = self._owned_decoded(definition_address)
            if (
                definition.id != X86_INS_LEA
                or len(definition.operands) != 2
                or definition.operands[1].type != X86_OP_MEM
            ):
                continue
            pointer = definition.operands[1].mem
            if (
                pointer.segment != X86_REG_INVALID
                or pointer.index != X86_REG_INVALID
                or pointer.base == X86_REG_INVALID
            ):
                continue
            pointer_base = self._register_family(pointer.base)
            if pointer_base not in {"esp", "ebp"}:
                continue
            pointer_state = stack_states.get(definition_address)
            if pointer_state is None:
                continue
            pointer_delta = (
                pointer_state[0]
                if pointer_base == "esp"
                else pointer_state[1]
            )
            if pointer_delta is None:
                continue
            pointer_offset = pointer_delta + pointer.disp
            output = self._fixed_output_argument_values(
                call.target, argument_index
            )
            if output is None:
                continue
            field, values, detail = output
            if pointer_offset + field != logical_offset:
                continue
            matches.append(
                (
                    values,
                    f"outparam-call={call.address:#x};"
                    f"callee={call.target:#x};argument={argument_index};"
                    f"logical-stack={logical_offset:+#x};{detail}",
                )
            )
        if len(matches) != 1:
            return None
        return matches[0]

    def _fixed_output_argument_values(
        self, function_entry: int, argument_index: int
    ) -> tuple[int, frozenset[int], str] | None:
        if function_entry not in self.function_addresses:
            return None
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        if any(
            self._owned_decoded(address).group(CS_GRP_CALL)
            for address in sorted(self.instructions)
            if function_entry <= address < following_entry
            and self._reachable_within_function(
                function_entry,
                address,
                function_entry,
                following_entry,
            )
        ):
            return None
        writes = []
        for rows in self.dynamic_field_writes.values():
            for row in rows:
                if not (
                    function_entry <= row.instruction_address < following_entry
                ):
                    continue
                decoded = self._owned_decoded(row.instruction_address)
                if (
                    decoded.id != X86_INS_MOV
                    or len(decoded.operands) != 2
                    or decoded.operands[0].type != X86_OP_MEM
                    or decoded.operands[0].size != 4
                    or decoded.operands[0].mem.segment != X86_REG_INVALID
                    or decoded.operands[0].mem.index != X86_REG_INVALID
                    or decoded.operands[0].mem.base == X86_REG_INVALID
                    or decoded.operands[1].type != X86_OP_IMM
                    or self._register_argument_index_across_blocks(
                        row.instruction_address,
                        self._register_family(
                            decoded.operands[0].mem.base
                        ),
                        function_entry,
                    )
                    != argument_index
                ):
                    continue
                writes.append((row, decoded))
        if len(writes) != 1:
            return None
        write, decoded = writes[0]
        if not self._reachable_within_function(
            function_entry,
            write.instruction_address,
            function_entry,
            following_entry,
        ):
            return None
        returns = [
            address
            for address in sorted(self.instructions)
            if function_entry <= address < following_entry
            and self._owned_decoded(address).group(CS_GRP_RET)
            and self._reachable_within_function(
                function_entry,
                address,
                function_entry,
                following_entry,
            )
        ]
        if not returns or any(
            self._reachable_within_function(
                function_entry,
                return_address,
                function_entry,
                following_entry,
                excluded=write.instruction_address,
            )
            for return_address in returns
        ):
            return None
        value = decoded.operands[1].imm & 0xFFFF_FFFF
        return (
            decoded.operands[0].mem.disp,
            frozenset({value}),
            f"fixed-output-store={write.instruction_address:#x};"
            f"value={value:#x}",
        )

    def _function_stack_states(
        self, function_entry: int
    ) -> dict[int, tuple[int, int | None]] | None:
        cache_key = (
            function_entry,
            len(self.instructions),
            self.control_flow_revision,
        )
        if cache_key in self.stack_state_cache:
            return self.stack_state_cache[cache_key]
        states: dict[int, tuple[int, int | None]] = {
            function_entry: (0, None)
        }
        pending = [function_entry]
        queued = {function_entry}
        iterations = 0
        while pending:
            address = heapq.heappop(pending)
            queued.remove(address)
            if address not in self.instructions:
                self.stack_state_cache[cache_key] = None
                return None
            decoded = self._owned_decoded(address)
            sp_delta, bp_delta = states[address]
            if decoded.mnemonic == "push":
                sp_delta -= 4
            elif decoded.mnemonic == "pop":
                sp_delta += 4
            elif (
                decoded.mnemonic in {"add", "sub"}
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and self._register_family(decoded.operands[0].reg) == "esp"
                and decoded.operands[1].type == X86_OP_IMM
            ):
                amount = decoded.operands[1].imm & 0xFFFF_FFFF
                sp_delta += amount if decoded.mnemonic == "add" else -amount
            elif (
                decoded.mnemonic == "mov"
                and len(decoded.operands) == 2
                and all(row.type == X86_OP_REG for row in decoded.operands)
            ):
                destination = self._register_family(decoded.operands[0].reg)
                source = self._register_family(decoded.operands[1].reg)
                if destination == "ebp" and source == "esp":
                    bp_delta = sp_delta
                elif destination == "ebp":
                    bp_delta = None
                elif destination == "esp" and source == "ebp":
                    if bp_delta is None:
                        self.stack_state_cache[cache_key] = None
                        return None
                    sp_delta = bp_delta
            elif decoded.mnemonic == "leave":
                if bp_delta is None:
                    self.stack_state_cache[cache_key] = None
                    return None
                sp_delta = bp_delta + 4

            if decoded.group(CS_GRP_RET) or decoded.group(CS_GRP_IRET):
                successors: tuple[int, ...] = ()
            elif decoded.group(CS_GRP_CALL):
                cleanup = self._closed_call_stack_cleanup(decoded.address)
                if cleanup is None:
                    successors = ()
                else:
                    sp_delta += cleanup
                    successors = (decoded.address + decoded.size,)
            elif decoded.group(CS_GRP_JUMP):
                successors = tuple(
                    sorted(
                        self.non_call_successors.get(decoded.address, ())
                    )
                )
                if not successors:
                    self.stack_state_cache[cache_key] = None
                    return None
            else:
                successors = (decoded.address + decoded.size,)
            output = (sp_delta, bp_delta)
            for successor in successors:
                if successor not in self.instructions:
                    self.stack_state_cache[cache_key] = None
                    return None
                prior = states.get(successor)
                if prior is not None and prior != output:
                    self.stack_state_cache[cache_key] = None
                    return None
                if prior is not None:
                    continue
                states[successor] = output
                if successor not in queued:
                    heapq.heappush(pending, successor)
                    queued.add(successor)
            iterations += 1
            self.high_water["max_summary_iterations"] = max(
                self.high_water["max_summary_iterations"], iterations
            )
            self.limits.check("max_summary_iterations", iterations)
        self.stack_state_cache[cache_key] = states
        return states

    def _closed_function_stack_cleanup(self, function_entry: int) -> int | None:
        cache_key = (
            function_entry,
            len(self.instructions),
            self.control_flow_revision,
        )
        if cache_key in self.callee_cleanup_cache:
            return self.callee_cleanup_cache[cache_key]
        if function_entry not in self.function_addresses:
            self.callee_cleanup_cache[cache_key] = None
            return None
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        cleanups = set()
        pending = [function_entry]
        seen = set()
        while pending:
            address = heapq.heappop(pending)
            if address in seen:
                continue
            if (
                address not in self.instructions
                or not function_entry <= address < following_entry
            ):
                self.callee_cleanup_cache[cache_key] = None
                return None
            seen.add(address)
            self.limits.check("max_summary_iterations", len(seen))
            decoded = self._owned_decoded(address)
            if not decoded.group(CS_GRP_RET):
                for successor in self._summary_successors(
                    address, function_entry, following_entry
                ):
                    if successor not in seen:
                        heapq.heappush(pending, successor)
                continue
            if not decoded.operands:
                cleanups.add(0)
            elif (
                len(decoded.operands) == 1
                and decoded.operands[0].type == X86_OP_IMM
            ):
                cleanups.add(decoded.operands[0].imm & 0xFFFF_FFFF)
            else:
                self.callee_cleanup_cache[cache_key] = None
                return None
        result = next(iter(cleanups)) if len(cleanups) == 1 else None
        self.callee_cleanup_cache[cache_key] = result
        return result

    def _closed_call_stack_cleanup(self, call_address: int) -> int | None:
        targets = self.call_targets_by_source.get(call_address, set())
        if not targets or any(
            row.address == call_address
            and row.kind in {"indirect-flow", "computed-flow-blocker"}
            for row in self.diagnostics
        ):
            return None
        cleanups = {
            self._closed_function_stack_cleanup(target)
            for target in targets
        }
        if None in cleanups or len(cleanups) != 1:
            return None
        return next(iter(cleanups))

    def _finite_register_values_across_blocks(
        self,
        address: int,
        register_family: str,
        function_entry: int,
        visited: frozenset[tuple[int, str]],
    ) -> tuple[frozenset[int], str] | None:
        argument_proof = self._register_argument_proof_across_blocks(
            address, register_family, function_entry
        )
        if argument_proof is not None:
            argument_index, argument_definitions = argument_proof
            finite_argument = self._finite_argument_values(
                function_entry, argument_index, visited
            )
            if finite_argument is not None:
                values, detail = finite_argument
                if len(argument_definitions) == 1:
                    definition_detail = (
                        "dominating-definition="
                        f"{next(iter(argument_definitions)):#x}"
                    )
                else:
                    definition_detail = "reaching-definitions=" + ",".join(
                        f"{row:#x}" for row in sorted(argument_definitions)
                    )
                return (
                    values,
                    f"register={register_family};{definition_detail};{detail}",
                )

        key = (address, f"register-definitions:{register_family}")
        if key in visited:
            return None
        definitions = self._register_definitions_across_blocks(
            address, register_family, function_entry
        )
        if not definitions:
            return None
        values = set()
        provenance = []
        for definition in sorted(definitions):
            decoded = self._owned_decoded(definition)
            if (
                decoded.id not in {X86_INS_MOV, X86_INS_LEA}
                or len(decoded.operands) != 2
                or decoded.operands[0].type != X86_OP_REG
                or self._register_family(decoded.operands[0].reg)
                != register_family
            ):
                return None
            result = self._finite_operand_values_before(
                definition,
                decoded.operands[1],
                function_entry,
                visited | {key},
                lea=decoded.id == X86_INS_LEA,
            )
            if result is None:
                return None
            definition_values, detail = result
            values.update(definition_values)
            provenance.append(f"definition={definition:#x};{detail}")
        if not values:
            return None
        self._check_count("max_finite_values", len(values))
        return (
            frozenset(values),
            f"register={register_family};" + "|".join(provenance),
        )

    def _finite_register_values_before(
        self,
        address: int,
        register_family: str,
        function_entry: int,
        visited: frozenset[tuple[int, str]],
    ) -> tuple[frozenset[int], str] | None:
        key = (address, f"register:{register_family}")
        if key in visited:
            return None
        equal_guard = self._dominating_register_equal_guard(
            address, register_family, function_entry
        )
        if equal_guard is not None:
            value, compare_address, branch_address = equal_guard
            return (
                frozenset({value}),
                f"register={register_family};"
                f"equal-guard={compare_address:#x};"
                f"branch={branch_address:#x};value={value:#x}",
            )
        cursor = address
        for _ in range(128):
            previous = self._previous_instruction(cursor)
            if previous is None or previous.address < function_entry:
                break
            decoded = self._owned_decoded(previous.address)
            writes_family = any(
                self._register_family(row) == register_family
                for row in decoded.regs_write
            ) or any(
                row.type == X86_OP_REG
                and row.access & CS_AC_WRITE
                and self._register_family(row.reg) == register_family
                for row in decoded.operands
            )
            if writes_family:
                if (
                    decoded.id in {X86_INS_MOV, X86_INS_LEA}
                    and len(decoded.operands) == 2
                    and decoded.operands[0].type == X86_OP_REG
                    and self._register_family(decoded.operands[0].reg)
                    == register_family
                ):
                    if self._loop_can_bypass_register_definition(
                        address,
                        previous.address,
                        register_family,
                        function_entry,
                    ):
                        affine_loop, affine_values = (
                            self._finite_affine_loop_register_values(
                                address, register_family, function_entry
                            )
                        )
                        if affine_loop:
                            return affine_values
                    result = self._finite_operand_values_before(
                        previous.address,
                        decoded.operands[1],
                        function_entry,
                        visited | {key},
                        lea=decoded.id == X86_INS_LEA,
                    )
                    if result is None:
                        return None
                    values, detail = result
                    return (
                        values,
                        f"register={register_family};"
                        f"definition={previous.address:#x};{detail}",
                    )
                affine_loop, affine_values = (
                    self._finite_affine_loop_register_values(
                        address, register_family, function_entry
                    )
                )
                return affine_values if affine_loop else None
            if (
                decoded.group(CS_GRP_CALL)
                and register_family in {"eax", "ecx", "edx"}
            ) or decoded.group(CS_GRP_RET):
                return None
            if decoded.group(CS_GRP_JUMP):
                break
            cursor = previous.address
            if previous.address in self.block_starts:
                break
        affine_loop, affine_values = self._finite_affine_loop_register_values(
            address, register_family, function_entry
        )
        if affine_loop:
            return affine_values
        return self._finite_register_values_across_blocks(
            address,
            register_family,
            function_entry,
            visited | {key},
        )

    def _loop_can_bypass_register_definition(
        self,
        address: int,
        definition: int,
        register_family: str,
        function_entry: int,
    ) -> bool:
        for edge in self.non_call_backedges:
            if not (
                function_entry <= definition < edge.target <= address
                and address < edge.source
            ):
                continue
            for row in self.instructions:
                if not edge.target <= row <= edge.source:
                    continue
                decoded = self._owned_decoded(row)
                if any(
                    self._register_family(register) == register_family
                    for register in decoded.regs_write
                ) or any(
                    operand.type == X86_OP_REG
                    and operand.access & CS_AC_WRITE
                    and self._register_family(operand.reg) == register_family
                    for operand in decoded.operands
                ):
                    return True
        return False

    def _finite_affine_loop_register_values(
        self,
        address: int,
        register_family: str,
        function_entry: int,
    ) -> tuple[bool, tuple[frozenset[int], str] | None]:
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        cycle_cache: dict[CfgEdge, frozenset[int]] = {}

        def cycle_addresses(edge: CfgEdge) -> frozenset[int]:
            if edge in cycle_cache:
                return cycle_cache[edge]
            adjacency: dict[int, tuple[int, ...]] = {}
            reverse: dict[int, set[int]] = {}
            for row in sorted(self.instructions):
                if not edge.target <= row <= edge.source:
                    continue
                successors = tuple(
                    successor
                    for successor in self._summary_successors(
                        row, function_entry, following_entry
                    )
                    if edge.target <= successor <= edge.source
                )
                adjacency[row] = successors
                for successor in successors:
                    reverse.setdefault(successor, set()).add(row)

            reachable = set()
            pending = [edge.target]
            while pending:
                current = heapq.heappop(pending)
                if current in reachable:
                    continue
                reachable.add(current)
                for successor in adjacency.get(current, ()):
                    if successor not in reachable:
                        heapq.heappush(pending, successor)

            reaches_source = set()
            pending = [edge.source]
            while pending:
                current = heapq.heappop(pending)
                if current in reaches_source:
                    continue
                reaches_source.add(current)
                for predecessor in reverse.get(current, ()):
                    if predecessor not in reaches_source:
                        heapq.heappush(pending, predecessor)
            result = frozenset(reachable & reaches_source)
            cycle_cache[edge] = result
            return result

        backedges = tuple(
            sorted(
                (
                    edge
                    for edge in self.non_call_backedges
                    if edge.target <= address < edge.source
                    and function_entry <= edge.target
                ),
                key=_edge_key,
            )
        )
        if not backedges:
            return False, None
        writing_backedges = []
        for edge in backedges:
            writes_register = False
            for row in sorted(cycle_addresses(edge)):
                decoded = self._owned_decoded(row)
                if any(
                    self._register_family(register) == register_family
                    for register in decoded.regs_write
                ) or any(
                    operand.type == X86_OP_REG
                    and operand.access & CS_AC_WRITE
                    and self._register_family(operand.reg) == register_family
                    for operand in decoded.operands
                ):
                    writes_register = True
                    break
            if writes_register:
                writing_backedges.append(edge)
        if not writing_backedges:
            return False, None
        innermost_backedges = [
            candidate
            for candidate in writing_backedges
            if not any(
                candidate.target <= nested.target
                and nested.source <= candidate.source
                and (
                    candidate.target != nested.target
                    or candidate.source != nested.source
                )
                for nested in writing_backedges
            )
        ]
        if len(innermost_backedges) != 1:
            return True, None
        backedge = innermost_backedges[0]

        # An enclosing loop may inherit this loop's register write.  It is safe
        # to reason about the inner recurrence only when each enclosing loop
        # resets the target register to a fixed base before re-entering it.
        for enclosing in writing_backedges:
            if enclosing == backedge:
                continue
            resets_before_inner = []
            for row in sorted(cycle_addresses(enclosing)):
                if row >= backedge.target:
                    continue
                decoded = self._owned_decoded(row)
                if any(
                    self._register_family(register) == register_family
                    for register in decoded.regs_write
                ) or any(
                    operand.type == X86_OP_REG
                    and operand.access & CS_AC_WRITE
                    and self._register_family(operand.reg) == register_family
                    for operand in decoded.operands
                ):
                    resets_before_inner.append(decoded)
            if len(resets_before_inner) != 1:
                return True, None
            reset = resets_before_inner[0]
            if (
                reset.address >= backedge.target
                or reset.mnemonic != "mov"
                or len(reset.operands) != 2
                or reset.operands[0].type != X86_OP_REG
                or self._register_family(reset.operands[0].reg)
                != register_family
                or reset.operands[1].type != X86_OP_IMM
            ):
                return True, None
        branch = self._owned_decoded(backedge.source)
        if branch.mnemonic not in {"jl", "jle", "jb", "jbe"}:
            return True, None
        condition = self._previous_instruction(branch.address)
        if condition is None or condition.address + condition.size != branch.address:
            return True, None
        compared = self._owned_decoded(condition.address)
        if (
            compared.mnemonic != "cmp"
            or len(compared.operands) != 2
            or compared.operands[0].type != X86_OP_REG
            or compared.operands[1].type != X86_OP_IMM
        ):
            return True, None
        counter_family = self._register_family(compared.operands[0].reg)
        bound = compared.operands[1].imm & 0xFFFF_FFFF
        count = bound + (1 if branch.mnemonic in {"jle", "jbe"} else 0)
        if count <= 0 or count > 4096:
            return True, None

        stride = None
        counter_increments = 0
        for row in sorted(cycle_addresses(backedge)):
            decoded = self._owned_decoded(row)
            writes_target = any(
                self._register_family(register) == register_family
                for register in decoded.regs_write
            ) or any(
                operand.type == X86_OP_REG
                and operand.access & CS_AC_WRITE
                and self._register_family(operand.reg) == register_family
                for operand in decoded.operands
            )
            if writes_target:
                if (
                    decoded.mnemonic == "add"
                    and len(decoded.operands) == 2
                    and decoded.operands[0].type == X86_OP_REG
                    and self._register_family(decoded.operands[0].reg)
                    == register_family
                    and decoded.operands[1].type == X86_OP_IMM
                    and stride is None
                ):
                    stride = decoded.operands[1].imm & 0xFFFF_FFFF
                else:
                    return True, None
            if (
                decoded.mnemonic == "inc"
                and len(decoded.operands) == 1
                and decoded.operands[0].type == X86_OP_REG
                and self._register_family(decoded.operands[0].reg)
                == counter_family
            ):
                counter_increments += 1
        if stride is None or counter_increments != 1:
            return True, None

        base = None
        counter_zero = False
        for row in sorted(self.instructions):
            if not function_entry <= row < backedge.target:
                continue
            decoded = self._owned_decoded(row)
            if decoded.mnemonic == "mov" and len(decoded.operands) == 2:
                destination, source = decoded.operands
                if (
                    destination.type == X86_OP_REG
                    and self._register_family(destination.reg)
                    == register_family
                    and source.type == X86_OP_IMM
                ):
                    base = source.imm & 0xFFFF_FFFF
                if (
                    destination.type == X86_OP_REG
                    and self._register_family(destination.reg)
                    == counter_family
                    and source.type == X86_OP_IMM
                    and source.imm == 0
                ):
                    counter_zero = True
            if (
                decoded.mnemonic == "xor"
                and len(decoded.operands) == 2
                and all(operand.type == X86_OP_REG for operand in decoded.operands)
                and self._register_family(decoded.operands[0].reg)
                == counter_family
                and self._register_family(decoded.operands[1].reg)
                == counter_family
            ):
                counter_zero = True
        if base is None or not counter_zero:
            return True, None
        values = frozenset(
            (base + index * stride) & 0xFFFF_FFFF
            for index in range(count)
        )
        self._check_count("max_finite_values", len(values))
        return (
            True,
            (
                values,
                f"affine-loop-base={base:#x};stride={stride:#x};"
                f"count={count};backedge={backedge.source:#x}",
            ),
        )

    def _finite_operand_values_before(
        self,
        address: int,
        operand,
        function_entry: int,
        visited: frozenset[tuple[int, str]],
        *,
        lea: bool = False,
    ) -> tuple[frozenset[int], str] | None:
        if operand.type == X86_OP_IMM:
            value = operand.imm & 0xFFFF_FFFF
            return frozenset({value}), f"immediate={value:#x}"
        if operand.type == X86_OP_REG:
            return self._finite_register_values_before(
                address,
                self._register_family(operand.reg),
                function_entry,
                visited,
            )
        if operand.type != X86_OP_MEM or operand.mem.segment != X86_REG_INVALID:
            return None
        memory = operand.mem
        if memory.index != X86_REG_INVALID:
            return None
        if memory.base == X86_REG_INVALID:
            absolute = memory.disp & 0xFFFF_FFFF
            if lea:
                return frozenset({absolute}), f"absolute-address={absolute:#x}"
            if operand.size == 4 and self.global_slot_writes.get(absolute):
                global_values = self._finite_global_slot_values(
                    absolute, visited
                )
                if global_values is None:
                    return None
                values, detail = global_values
                return (
                    values,
                    f"global-slot={absolute:#x};{detail}",
                )
            try:
                raw = _read_loader_initialized(self.image, absolute, operand.size)
            except ValueError:
                return None
            if operand.size != 4:
                return None
            value = int.from_bytes(raw, "little")
            return (
                frozenset({value}),
                f"absolute-load={absolute:#x};bytes={raw.hex()}",
            )
        if operand.size == 4:
            base_family = self._register_family(memory.base)
            if base_family == "ebp":
                argument_index = self._stack_argument_index_at(
                    address, operand, function_entry
                )
                if argument_index is not None:
                    argument = self._finite_argument_values(
                        function_entry, argument_index, visited
                    )
                    if argument is None:
                        return None
                    values, detail = argument
                    following_entry = min(
                        (
                            row
                            for row in self.function_addresses
                            if row > function_entry
                        ),
                        default=0x1_0000_0000,
                    )
                    combined_values = set(values)
                    write_details = []
                    for write in sorted(
                        self.dynamic_field_writes.get(memory.disp, ()),
                        key=lambda row: row.instruction_address,
                    ):
                        write_address = write.instruction_address
                        if not function_entry <= write_address < following_entry:
                            continue
                        write_decoded = self._owned_decoded(write_address)
                        if (
                            write_decoded.id != X86_INS_MOV
                            or len(write_decoded.operands) != 2
                            or write_decoded.operands[0].type != X86_OP_MEM
                            or write_decoded.operands[0].size != 4
                        ):
                            continue
                        destination = write_decoded.operands[0].mem
                        if (
                            destination.segment != X86_REG_INVALID
                            or destination.index != X86_REG_INVALID
                            or destination.base == X86_REG_INVALID
                            or self._register_family(destination.base) != "ebp"
                            or destination.disp != memory.disp
                            or not self._reachable_within_function(
                                function_entry,
                                write_address,
                                function_entry,
                                following_entry,
                            )
                            or not self._reachable_within_function(
                                write_address,
                                address,
                                function_entry,
                                following_entry,
                            )
                        ):
                            continue
                        write_result = self._finite_operand_values_before(
                            write_address,
                            write_decoded.operands[1],
                            function_entry,
                            visited
                            | {
                                (
                                    address,
                                    f"canonical-ebp:{memory.disp}",
                                )
                            },
                        )
                        if write_result is None:
                            return None
                        write_values, write_detail = write_result
                        combined_values.update(write_values)
                        write_details.append(
                            f"stack-write={write_address:#x};"
                            f"{write_detail}"
                        )
                    return (
                        frozenset(combined_values),
                        f"stack-argument={argument_index};{detail}"
                        + (
                            ";" + ";".join(write_details)
                            if write_details
                            else ""
                        ),
                    )
            local_field = self._finite_local_field_store_before(
                address,
                memory,
                function_entry,
                visited,
            )
            if local_field is not None:
                return local_field
        base_family = self._register_family(memory.base)
        displacement = memory.disp
        if base_family == "esp":
            return self._finite_stack_slot_before(
                address,
                base_family=base_family,
                displacement=displacement,
                function_entry=function_entry,
                visited=visited,
            )
        if operand.size == 4:
            copied_component = self._finite_copied_descriptor_component(
                address,
                base_family,
                displacement,
                function_entry,
                visited,
            )
            if copied_component is not None:
                return copied_component
        base = self._finite_register_values_before(
            address, base_family, function_entry, visited
        )
        if base is None and base_family == "ebp":
            stack_value = self._finite_stack_slot_before(
                address,
                base_family=base_family,
                displacement=displacement,
                function_entry=function_entry,
                visited=visited,
            )
            if stack_value is not None:
                return stack_value
        if base is None or operand.size != 4:
            if operand.size == 4:
                dynamic = self._finite_dynamic_field_values(
                    displacement, visited
                )
                if dynamic is not None:
                    values, detail = dynamic
                    return (
                        values,
                        f"dynamic-field={displacement:+#x};{detail}",
                    )
            return None
        base_values, base_detail = base
        values = set()
        faulting_bases = []
        runtime_field_details = []
        for value in base_values:
            field_address = (value + displacement) & 0xFFFF_FFFF
            if self.global_slot_writes.get(field_address):
                runtime_field = self._finite_global_slot_values(
                    field_address, visited
                )
                if runtime_field is None:
                    return None
                field_values, field_detail = runtime_field
                values.update(field_values)
                runtime_field_details.append(
                    f"global-slot={field_address:#x};{field_detail}"
                )
                continue
            try:
                raw = _read_loader_initialized(self.image, field_address, 4)
            except ValueError:
                faulting_bases.append(value)
                continue
            values.add(int.from_bytes(raw, "little"))
        if not values:
            return None
        detail = f"field={displacement:+#x}"
        if runtime_field_details:
            detail += ";" + "|".join(runtime_field_details)
        if faulting_bases:
            detail += ";fault-before-transfer=" + ",".join(
                f"{value:#x}" for value in sorted(faulting_bases)
            )
        detail += f";{base_detail}"
        return frozenset(values), detail

    def _finite_copied_descriptor_component(
        self,
        address: int,
        base_family: str,
        displacement: int,
        function_entry: int,
        visited: frozenset[tuple[int, str]],
    ) -> tuple[frozenset[int], str] | None:
        if displacement not in {0, 4, 8}:
            return None
        copy_info = self._copied_descriptor_source_domains(visited)
        if copy_info is None:
            return None
        copy_function, domains = copy_info
        argument_proof = self._register_argument_proof_across_blocks(
            address, base_family, function_entry
        )
        if argument_proof is None:
            return None
        argument_index, _ = argument_proof
        if not self._argument_has_copied_descriptor_origin(
            function_entry,
            argument_index,
            copy_function,
            frozenset(value for value in domains[0] if value),
            frozenset(),
        ):
            return None
        component = displacement // 4
        values = domains[component]
        if not values:
            return None
        return (
            values,
            f"copied-descriptor-component={component};"
            + "sources="
            + ",".join(f"{value:#x}" for value in sorted(values)),
        )

    def _argument_has_copied_descriptor_origin(
        self,
        function_entry: int,
        argument_index: int,
        copy_function: int,
        source_bases: frozenset[int],
        visited: frozenset[tuple[int, int]],
    ) -> bool:
        """Prove every caller supplies a source record or its fresh copy."""
        cache_key = (
            function_entry,
            argument_index,
            copy_function,
            tuple(sorted(source_bases)),
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.copied_argument_origin_cache:
            return True
        key = (function_entry, 0x3_0000_0000 + argument_index)
        if key in visited or not self._incoming_call_domain_is_closed(
            function_entry
        ):
            return False
        next_visited = visited | {key}
        for call_address in self._incoming_call_sites(function_entry):
            pushed = self._pushed_call_argument(call_address, argument_index)
            if pushed is None:
                return False
            push_address, operand, caller_entry = pushed
            if self._operand_has_copy_constructor_origin(
                push_address.address,
                operand,
                caller_entry,
                copy_function,
                next_visited,
            ):
                continue
            finite = self._finite_operand_values_before(
                push_address.address,
                operand,
                caller_entry,
                frozenset(),
            )
            if finite is not None and finite[0] and finite[0] <= source_bases:
                continue
            if self._operand_has_copied_back_reference_origin(
                push_address.address,
                operand,
                caller_entry,
                copy_function,
                source_bases,
                frozenset(),
            ):
                continue
            forwarded_argument = self._operand_argument_index(
                push_address.address,
                operand,
                caller_entry,
            )
            if forwarded_argument is not None and (
                self._argument_has_copied_descriptor_origin(
                    caller_entry,
                    forwarded_argument,
                    copy_function,
                    source_bases,
                    next_visited,
                )
            ):
                continue
            return False
        self.copied_argument_origin_cache.add(cache_key)
        return True

    def _back_reference_initializer(
        self,
        function_entry: int,
        object_field: int,
        pointer_field: int,
        target_field: int,
    ) -> tuple[int, int] | None:
        """Recognize ``*(*(descriptor + object) + pointer) = descriptor``."""
        cache_key = (
            function_entry,
            object_field,
            pointer_field,
            target_field,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.back_reference_initializer_cache:
            return self.back_reference_initializer_cache[cache_key]
        self.back_reference_initializer_cache[cache_key] = None
        if function_entry not in self.function_addresses:
            return None
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        candidates = []
        for write in sorted(
            self.dynamic_field_writes.get(target_field, ()),
            key=lambda row: row.instruction_address,
        ):
            if not (
                function_entry
                <= write.instruction_address
                < following_entry
            ):
                continue
            decoded = self._owned_decoded(write.instruction_address)
            if not (
                decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_MEM
                and decoded.operands[0].size == 4
                and decoded.operands[0].mem.segment == X86_REG_INVALID
                and decoded.operands[0].mem.base != X86_REG_INVALID
                and decoded.operands[0].mem.index == X86_REG_INVALID
                and decoded.operands[0].mem.disp == target_field
                and decoded.operands[1].type == X86_OP_REG
            ):
                continue
            descriptor_family = self._register_family(
                decoded.operands[1].reg
            )
            descriptor_argument = self._register_argument_origin_index(
                decoded.address, descriptor_family, function_entry
            )
            if descriptor_argument is None:
                continue
            holder_family = self._register_family(
                decoded.operands[0].mem.base
            )
            holder_definitions = self._register_definitions_across_blocks(
                decoded.address, holder_family, function_entry
            )
            if not holder_definitions or len(holder_definitions) != 1:
                continue
            holder_load = self._owned_decoded(
                next(iter(holder_definitions))
            )
            if not (
                holder_load.id == X86_INS_MOV
                and len(holder_load.operands) == 2
                and holder_load.operands[0].type == X86_OP_REG
                and holder_load.operands[1].type == X86_OP_MEM
                and holder_load.operands[1].size == 4
                and holder_load.operands[1].mem.segment
                == X86_REG_INVALID
                and holder_load.operands[1].mem.base
                != X86_REG_INVALID
                and holder_load.operands[1].mem.index
                == X86_REG_INVALID
                and holder_load.operands[1].mem.disp == pointer_field
            ):
                continue
            runtime_family = self._register_family(
                holder_load.operands[1].mem.base
            )
            runtime_definitions = self._register_definitions_across_blocks(
                holder_load.address, runtime_family, function_entry
            )
            if not runtime_definitions or len(runtime_definitions) != 1:
                continue
            runtime_load = self._owned_decoded(
                next(iter(runtime_definitions))
            )
            if not (
                runtime_load.id == X86_INS_MOV
                and len(runtime_load.operands) == 2
                and runtime_load.operands[0].type == X86_OP_REG
                and runtime_load.operands[1].type == X86_OP_MEM
                and runtime_load.operands[1].size == 4
                and runtime_load.operands[1].mem.segment
                == X86_REG_INVALID
                and runtime_load.operands[1].mem.base
                != X86_REG_INVALID
                and runtime_load.operands[1].mem.index
                == X86_REG_INVALID
                and runtime_load.operands[1].mem.disp == object_field
                and self._register_argument_origin_index(
                    runtime_load.address,
                    self._register_family(
                        runtime_load.operands[1].mem.base
                    ),
                    function_entry,
                )
                == descriptor_argument
            ):
                continue
            returns = [
                address
                for address in self._function_instruction_addresses(
                    function_entry
                )
                if self._owned_decoded(address).group(CS_GRP_RET)
                and self._reachable_within_function(
                    function_entry,
                    address,
                    function_entry,
                    following_entry,
                )
            ]
            if not returns or any(
                self._reachable_within_function(
                    function_entry,
                    return_address,
                    function_entry,
                    following_entry,
                    excluded=decoded.address,
                )
                for return_address in returns
            ):
                continue
            if any(
                row.kind in {"indirect-flow", "computed-flow-blocker"}
                and function_entry <= row.address < following_entry
                for row in self.diagnostics
            ):
                continue
            candidates.append((descriptor_argument, decoded.address))
        result = candidates[0] if len(set(candidates)) == 1 else None
        self.back_reference_initializer_cache[cache_key] = result
        return result

    def _descriptor_back_reference_is_initialized(
        self,
        address: int,
        descriptor_family: str,
        function_entry: int,
        object_field: int,
        pointer_field: int,
        target_field: int,
        visited: frozenset[tuple[Any, ...]],
    ) -> bool:
        cache_key = (
            address,
            descriptor_family,
            function_entry,
            object_field,
            pointer_field,
            target_field,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.initialized_back_reference_cache:
            return True
        key = (
            address,
            "initialized-back-reference",
            descriptor_family,
            object_field,
            pointer_field,
            target_field,
        )
        if key in visited:
            return False
        next_visited = visited | {key}
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )

        current_initializer = self._back_reference_initializer(
            function_entry,
            object_field,
            pointer_field,
            target_field,
        )
        descriptor_argument = self._register_argument_index_across_blocks(
            address, descriptor_family, function_entry
        )
        if (
            current_initializer is not None
            and descriptor_argument == current_initializer[0]
            and not self._reachable_within_function(
                function_entry,
                address,
                function_entry,
                following_entry,
                excluded=current_initializer[1],
            )
        ):
            self.initialized_back_reference_cache.add(cache_key)
            return True

        function_calls = [
            DirectCall(source, target)
            for source in self._function_instruction_addresses(
                function_entry
            )
            if source < address
            and (
                target := self.direct_call_targets_by_source.get(source)
            )
            is not None
        ]
        for call in function_calls:
            if call.address >= address:
                continue
            relation = self._back_reference_initializer(
                call.target,
                object_field,
                pointer_field,
                target_field,
            )
            if relation is None:
                continue
            pushed = self._pushed_call_argument(
                call.address, relation[0]
            )
            pushed_argument = (
                None
                if pushed is None
                else self._operand_argument_index(
                    pushed[0].address, pushed[1], function_entry
                )
            )
            pushed_definitions = (
                None
                if pushed is None or pushed[1].type != X86_OP_REG
                else self._register_definitions_across_blocks(
                    pushed[0].address,
                    self._register_family(pushed[1].reg),
                    function_entry,
                )
            )
            descriptor_definitions = (
                self._register_definitions_across_blocks(
                    address,
                    descriptor_family,
                    function_entry,
                )
            )
            same_register = bool(
                pushed is not None
                and pushed[1].type == X86_OP_REG
                and self._register_family(pushed[1].reg)
                == descriptor_family
                and pushed_definitions
                and pushed_definitions == descriptor_definitions
            )
            if pushed is None or not (
                same_register
                or descriptor_argument is not None
                and pushed_argument == descriptor_argument
            ):
                continue
            if self._reachable_within_function(
                function_entry,
                address,
                function_entry,
                following_entry,
                excluded=call.address,
            ):
                continue
            if any(
                call.address < other.address < address
                for other in function_calls
            ):
                continue
            self.initialized_back_reference_cache.add(cache_key)
            return True

        if descriptor_argument is None:
            return False
        if not self._argument_back_reference_is_initialized(
            function_entry,
            descriptor_argument,
            object_field,
            pointer_field,
            target_field,
            next_visited,
        ):
            return False
        self.initialized_back_reference_cache.add(cache_key)
        return True

    def _argument_back_reference_is_initialized(
        self,
        function_entry: int,
        argument_index: int,
        object_field: int,
        pointer_field: int,
        target_field: int,
        visited: frozenset[tuple[Any, ...]],
    ) -> bool:
        cache_key = (
            function_entry,
            "initialized-back-reference-argument",
            argument_index,
            object_field,
            pointer_field,
            target_field,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.initialized_back_reference_cache:
            return True
        key = cache_key[:6]
        if key in visited or not self._incoming_call_domain_is_closed(
            function_entry
        ):
            return False
        next_visited = visited | {key}
        callers = self._incoming_call_sites(function_entry)
        if not callers:
            return False
        for call_address in callers:
            pushed = self._pushed_call_argument(
                call_address, argument_index
            )
            if (
                pushed is None
                or not (
                    self._operand_back_reference_is_initialized(
                        pushed[0].address,
                        pushed[1],
                        pushed[2],
                        object_field,
                        pointer_field,
                        target_field,
                        next_visited,
                    )
                )
            ):
                return False
        self.initialized_back_reference_cache.add(cache_key)
        return True

    def _argument_back_reference_is_initialized_locally(
        self,
        address: int,
        function_entry: int,
        argument_index: int,
        object_field: int,
        pointer_field: int,
        target_field: int,
    ) -> bool:
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        function_calls = [
            DirectCall(source, target)
            for source in self._function_instruction_addresses(
                function_entry
            )
            if source < address
            and (
                target := self.direct_call_targets_by_source.get(source)
            )
            is not None
        ]
        for call in function_calls:
            relation = self._back_reference_initializer(
                call.target,
                object_field,
                pointer_field,
                target_field,
            )
            if relation is None:
                continue
            pushed = self._pushed_call_argument(call.address, relation[0])
            if pushed is None or self._operand_argument_index(
                pushed[0].address, pushed[1], function_entry
            ) != argument_index:
                continue
            if self._reachable_within_function(
                function_entry,
                address,
                function_entry,
                following_entry,
                excluded=call.address,
            ):
                continue
            intervening = [
                other
                for other in function_calls
                if call.address < other.address < address
            ]
            if not intervening:
                return True
            descriptor_escapes = False
            for other in intervening:
                for callee_argument in range(8):
                    other_pushed = self._pushed_call_argument(
                        other.address, callee_argument
                    )
                    if other_pushed is None:
                        break
                    if self._operand_argument_index(
                        other_pushed[0].address,
                        other_pushed[1],
                        function_entry,
                    ) == argument_index:
                        descriptor_escapes = True
                        break
                if descriptor_escapes:
                    break
            if descriptor_escapes:
                continue
            runtime_definitions = []
            for row in self._function_instruction_addresses(function_entry):
                if not call.address < row < address:
                    continue
                decoded = self._owned_decoded(row)
                if not (
                    decoded.id == X86_INS_MOV
                    and len(decoded.operands) == 2
                    and decoded.operands[0].type == X86_OP_REG
                    and decoded.operands[0].size == 4
                    and decoded.operands[1].type == X86_OP_MEM
                    and decoded.operands[1].size == 4
                    and decoded.operands[1].mem.segment
                    == X86_REG_INVALID
                    and decoded.operands[1].mem.base
                    != X86_REG_INVALID
                    and decoded.operands[1].mem.index
                    == X86_REG_INVALID
                    and decoded.operands[1].mem.disp == object_field
                    and self._register_argument_index_across_blocks(
                        decoded.address,
                        self._register_family(
                            decoded.operands[1].mem.base
                        ),
                        function_entry,
                    )
                    == argument_index
                ):
                    continue
                if any(
                    call.address < other.address < decoded.address
                    for other in function_calls
                ):
                    continue
                runtime_definitions.append(decoded.address)
            if any(
                self._pointer_definition_preserves_back_reference_until(
                    function_entry,
                    runtime_definition,
                    pointer_field,
                    address,
                )
                for runtime_definition in runtime_definitions
            ):
                return True
        return False

    def _operand_back_reference_is_initialized(
        self,
        address: int,
        operand,
        function_entry: int,
        object_field: int,
        pointer_field: int,
        target_field: int,
        visited: frozenset[tuple[Any, ...]],
    ) -> bool:
        argument_index = self._operand_argument_index(
            address, operand, function_entry
        )
        if argument_index is not None and (
            self._argument_back_reference_is_initialized_locally(
                address,
                function_entry,
                argument_index,
                object_field,
                pointer_field,
                target_field,
            )
        ):
            return True
        if operand.type == X86_OP_REG:
            return self._descriptor_back_reference_is_initialized(
                address,
                self._register_family(operand.reg),
                function_entry,
                object_field,
                pointer_field,
                target_field,
                visited,
            )
        if argument_index is None:
            return False
        return self._argument_back_reference_is_initialized(
            function_entry,
            argument_index,
            object_field,
            pointer_field,
            target_field,
            visited,
        )

    def _register_has_copied_descriptor_origin(
        self,
        address: int,
        register_family: str,
        function_entry: int,
        copy_function: int,
        source_bases: frozenset[int],
        visited: frozenset[tuple[Any, ...]],
    ) -> bool:
        if self._register_has_copy_constructor_origin(
            address,
            register_family,
            function_entry,
            copy_function,
            frozenset(),
        ):
            return True
        argument_index = self._register_argument_index_across_blocks(
            address, register_family, function_entry
        )
        if argument_index is not None and (
            self._argument_has_copied_descriptor_origin(
                function_entry,
                argument_index,
                copy_function,
                source_bases,
                frozenset(),
            )
        ):
            return True
        finite = self._finite_register_values_across_blocks(
            address,
            register_family,
            function_entry,
            frozenset(),
        )
        return bool(
            finite is not None
            and finite[0]
            and finite[0] <= source_bases
        )

    def _argument_has_runtime_descriptor_field_origin(
        self,
        function_entry: int,
        argument_index: int,
        pointer_field: int,
        target_field: int,
        copy_function: int,
        source_bases: frozenset[int],
        visited: frozenset[tuple[Any, ...]],
    ) -> bool:
        cache_key = (
            function_entry,
            argument_index,
            pointer_field,
            target_field,
            copy_function,
            tuple(sorted(source_bases)),
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.runtime_descriptor_field_origin_cache:
            return True
        key = (
            function_entry,
            "runtime-field-argument",
            argument_index,
            pointer_field,
            target_field,
        )
        if key in visited or not self._incoming_call_domain_is_closed(
            function_entry
        ):
            return False
        callers = self._incoming_call_sites(function_entry)
        if not callers:
            return False
        next_visited = visited | {key}
        for call_address in callers:
            pushed = self._pushed_call_argument(
                call_address, argument_index
            )
            if pushed is None or not (
                self._operand_has_runtime_descriptor_field_origin(
                    pushed[0].address,
                    pushed[1],
                    pushed[2],
                    pointer_field,
                    target_field,
                    copy_function,
                    source_bases,
                    next_visited,
                )
            ):
                return False
        self.runtime_descriptor_field_origin_cache.add(cache_key)
        return True

    def _register_has_runtime_descriptor_field_origin(
        self,
        address: int,
        register_family: str,
        function_entry: int,
        pointer_field: int,
        target_field: int,
        copy_function: int,
        source_bases: frozenset[int],
        visited: frozenset[tuple[Any, ...]],
    ) -> bool:
        argument_index = self._register_argument_index_across_blocks(
            address, register_family, function_entry
        )
        if argument_index is not None:
            return self._argument_has_runtime_descriptor_field_origin(
                function_entry,
                argument_index,
                pointer_field,
                target_field,
                copy_function,
                source_bases,
                visited,
            )
        key = (
            address,
            "runtime-field-register",
            register_family,
            pointer_field,
            target_field,
        )
        if key in visited:
            return False
        definitions = self._register_definitions_across_blocks(
            address, register_family, function_entry
        )
        if not definitions:
            return False
        next_visited = visited | {key}
        for definition_address in definitions:
            definition = self._owned_decoded(definition_address)
            if not (
                definition.id == X86_INS_MOV
                and len(definition.operands) == 2
                and definition.operands[0].type == X86_OP_REG
                and self._operand_has_runtime_descriptor_field_origin(
                    definition.address,
                    definition.operands[1],
                    function_entry,
                    pointer_field,
                    target_field,
                    copy_function,
                    source_bases,
                    next_visited,
                )
            ):
                return False
        return True

    def _relocated_global_zeroing_reference(
        self, owner: int, slot: int
    ) -> bool:
        decoded = self._owned_decoded(owner)
        if not (
            decoded.id == X86_INS_MOV
            and len(decoded.operands) == 2
            and decoded.operands[0].type == X86_OP_REG
            and self._register_family(decoded.operands[0].reg) == "edi"
            and decoded.operands[1].type == X86_OP_IMM
            and decoded.operands[1].imm & 0xFFFF_FFFF == slot
            and decoded.imm_size == 4
            and any(
                row.type == 3
                and row.va == decoded.address + decoded.imm_offset
                for row in self.image.relocations
            )
        ):
            return False
        function_entry = self._registrar_function_entry(owner)
        if function_entry is None:
            return False
        addresses = self._function_instruction_addresses(function_entry)
        zero_states = self._zero_register_states(function_entry)
        if zero_states is None:
            return False
        for address in addresses:
            if address <= owner:
                continue
            store = self._owned_decoded(address)
            width = {
                "rep stosb": 1,
                "rep stosw": 2,
                "rep stosd": 4,
            }.get(store.mnemonic)
            if width is None:
                continue
            edi_definitions = self._register_definitions_across_blocks(
                address, "edi", function_entry
            )
            count = self._resolve_register_constant_before(
                address, x86_const.X86_REG_ECX
            )
            state = zero_states.get(address)
            if (
                edi_definitions == frozenset({owner})
                and count is not None
                and 0 < count <= self.limits.max_finite_values
                and count * width >= 4
                and state is not None
                and state[_REGISTER_FAMILIES.index("eax")] == 1
                and not any(
                    row < address
                    and self._owned_decoded(row).mnemonic == "std"
                    for row in addresses
                )
            ):
                return True
        return False

    def _pointer_definition_preserves_field_without_escape(
        self,
        root_definition: int | None,
        function_entry: int,
        field: int,
        *,
        root_call: int | None = None,
        active: frozenset[tuple[int, int, int]] = frozenset(),
    ) -> bool:
        """Prove one loaded pointer cannot mutate or escape a field."""
        root = root_definition if root_call is None else root_call
        if root is None:
            return False
        key = (root, function_entry, field)
        if key in active:
            return False
        states = self._relative_pointer_states(
            function_entry,
            root_definition=root_definition,
            root_call=root_call,
            propagate_call_returns=False,
            allow_partial_taint=True,
            collapse_nonnegative_offsets=field + 4 <= 0,
        )
        if states is None:
            return False
        saw_root = False
        for address in self._function_instruction_addresses(function_entry):
            state = states.get(address)
            if state is None or not state[1] & 2:
                continue
            saw_root = True
            decoded = self._owned_decoded(address)
            for operand in decoded.operands:
                if operand.type != X86_OP_MEM:
                    continue
                base_values = (
                    frozenset()
                    if operand.mem.base == X86_REG_INVALID
                    else state[0][
                        _REGISTER_FAMILIES.index(
                            self._register_family(operand.mem.base)
                        )
                    ]
                )
                index_values = (
                    frozenset()
                    if operand.mem.index == X86_REG_INVALID
                    else state[0][
                        _REGISTER_FAMILIES.index(
                            self._register_family(operand.mem.index)
                        )
                    ]
                )
                if index_values:
                    return False
                if (
                    operand.access & CS_AC_WRITE
                    and base_values
                    and (
                        operand.size <= 0
                        or any(
                            value + operand.mem.disp < field + 4
                            and field
                            < value + operand.mem.disp + operand.size
                            for value in base_values
                        )
                    )
                ):
                    return False
            if decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                destination, source = decoded.operands
                if (
                    destination.type == X86_OP_MEM
                    and self._relative_operand_offsets(
                        address,
                        source,
                        function_entry,
                        None,
                        states,
                    )
                    and not self._partial_register_value_is_pointer_independent(
                        address, source, function_entry, states
                    )
                ):
                    return False
            if decoded.group(CS_GRP_CALL):
                target = self.direct_call_targets_by_source.get(address)
                if state[0][_REGISTER_FAMILIES.index("ecx")] and (
                    target is None
                    or self._function_reads_incoming_register(target, "ecx")
                ):
                    return False
                for argument_index in range(8):
                    pushed = self._pushed_call_argument(
                        address, argument_index
                    )
                    if pushed is None:
                        break
                    values = self._relative_operand_offsets(
                        pushed[0].address,
                        pushed[1],
                        function_entry,
                        None,
                        states,
                    )
                    for value in values:
                        relative_field = field - value
                        if target is None or not (
                            self._function_argument_is_not_used_as_pointer(
                                target, argument_index
                            )
                            or (
                                self._function_argument_preserves_field(
                                    target,
                                    argument_index,
                                    relative_field,
                                )
                                and (
                                    relative_field + 4 <= 0
                                    or self._function_argument_does_not_escape(
                                        target, argument_index
                                    )
                                )
                            )
                        ):
                            return False
            if decoded.group(CS_GRP_RET) and state[0][
                _REGISTER_FAMILIES.index("eax")
            ]:
                if self._incoming_call_domain_is_closed(function_entry):
                    callers = self._incoming_call_sites(function_entry)
                else:
                    callers = self._raw_direct_caller_domain_without_address_taken(
                        function_entry
                    )
                    if callers is None:
                        return False
                decoded_callers = self.direct_call_sources_by_target.get(
                    function_entry, set()
                )
                for caller in callers:
                    owner = self.byte_owners.get(caller)
                    if owner != caller:
                        if owner is not None and all(
                            self.byte_owners.get(byte_address) == owner
                            for byte_address in range(caller, caller + 5)
                        ):
                            continue
                        if not (
                            all(
                                self.byte_owners.get(byte_address) is None
                                for byte_address in range(caller, caller + 5)
                            )
                            and self._unowned_raw_call_return_is_overwritten_before_use(
                                caller, function_entry
                            )
                        ):
                            return False
                        continue
                    if caller not in decoded_callers:
                        return False
                    caller_entry = self._registrar_function_entry(caller)
                    if caller_entry is None:
                        return False
                    for value in state[0][
                        _REGISTER_FAMILIES.index("eax")
                    ]:
                        if not (
                            self._pointer_definition_preserves_field_without_escape(
                                None,
                                caller_entry,
                                field - value,
                                root_call=caller,
                                active=active | {key},
                            )
                        ):
                            return False
            if (
                decoded.group(CS_GRP_JUMP)
                and not self.non_call_successors.get(address)
                and any(state[0])
            ):
                return False
        return saw_root

    def _raw_direct_caller_domain_without_address_taken(
        self, function_entry: int
    ) -> tuple[int, ...] | None:
        """Enumerate raw direct callers when the target is not address-taken."""
        decoded = set(
            self.direct_call_sources_by_target.get(function_entry, ())
        )
        raw = self._raw_direct_call_sites(function_entry)
        if (
            not raw
            or not decoded <= raw
            or any(row.va == function_entry for row in self.image.exports)
            or any(
                row.type == 3
                and _is_mapped_span(self.image, row.va, 4)
                and int.from_bytes(
                    _read_loader_initialized(self.image, row.va, 4),
                    "little",
                )
                == function_entry
                for row in self.image.relocations
            )
        ):
            return None
        return tuple(sorted(raw))

    def _unowned_raw_call_return_is_overwritten_before_use(
        self, call_address: int, target: int
    ) -> bool:
        """Prove an unowned raw call's EAX result dies on fallthrough."""
        cache_key = (call_address, target)
        if cache_key in self.raw_dead_call_return_cache:
            return self.raw_dead_call_return_cache[cache_key]
        result = False
        try:
            call = self._decode_one(call_address)
            if not (
                call.group(CS_GRP_CALL)
                and self._direct_target(call) == target
            ):
                return False
            address = call.address + call.size
            for _ in range(64):
                decoded = self._decode_one(address)
                zeroes_eax = (
                    decoded.id == X86_INS_XOR
                    and len(decoded.operands) == 2
                    and all(
                        row.type == X86_OP_REG
                        and row.size == 4
                        and self._register_family(row.reg) == "eax"
                        for row in decoded.operands
                    )
                )
                if zeroes_eax:
                    result = True
                    break
                reads_eax = any(
                    self._register_family(register) == "eax"
                    for register in decoded.regs_read
                ) or any(
                    row.type == X86_OP_REG
                    and row.access & CS_AC_READ
                    and self._register_family(row.reg) == "eax"
                    or row.type == X86_OP_MEM
                    and any(
                        register != X86_REG_INVALID
                        and self._register_family(register) == "eax"
                        for register in (row.mem.base, row.mem.index)
                    )
                    for row in decoded.operands
                )
                if reads_eax:
                    break
                if decoded.group(CS_GRP_CALL):
                    result = True
                    break
                full_definition = any(
                    row.type == X86_OP_REG
                    and row.size == 4
                    and row.access & CS_AC_WRITE
                    and not row.access & CS_AC_READ
                    and self._register_family(row.reg) == "eax"
                    for row in decoded.operands
                )
                if full_definition:
                    result = True
                    break
                if (
                    decoded.group(CS_GRP_JUMP)
                    or decoded.group(CS_GRP_RET)
                    or decoded.group(CS_GRP_IRET)
                ):
                    break
                address += decoded.size
        except (CfgRecoveryError, ValueError):
            result = False
        self.raw_dead_call_return_cache[cache_key] = result
        return result

    def _partial_register_value_is_pointer_independent(
        self,
        address: int,
        operand,
        function_entry: int,
        states: dict[int, tuple[tuple[frozenset[int], ...], int]],
    ) -> bool:
        """Prove a stored subregister was overwritten independently."""
        if (
            operand.type != X86_OP_REG
            or operand.size <= 0
            or operand.size >= 4
        ):
            return False
        family = self._register_family(operand.reg)
        definitions = self._register_definitions_across_blocks(
            address, family, function_entry
        )
        if not definitions:
            return False
        for definition_address in definitions:
            definition = self._owned_decoded(definition_address)
            if not (
                definition.id == X86_INS_MOV
                and len(definition.operands) == 2
                and definition.operands[0].type == X86_OP_REG
                and definition.operands[0].reg == operand.reg
                and definition.operands[0].size == operand.size
                and not self._relative_operand_offsets(
                    definition_address,
                    definition.operands[1],
                    function_entry,
                    None,
                    states,
                )
            ):
                return False
        return True

    def _global_pointer_slot_preserves_published_field(
        self,
        pointer_slot: int,
        published_base: int,
        field: int = 0,
    ) -> bool:
        finite = self._finite_global_slot_values(
            pointer_slot, frozenset()
        )
        if finite is None or finite[0] - {0} != {published_base}:
            return False
        for write in self.global_slot_writes.get(pointer_slot, ()):
            decoded = self._owned_decoded(write.instruction_address)
            if not (
                decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and self._absolute_memory_operand(decoded.operands[0])
                == pointer_slot
            ):
                return False
            source = decoded.operands[1]
            if (
                source.type == X86_OP_IMM
                and source.imm & 0xFFFF_FFFF == 0
            ):
                continue
            if not self._operand_is_closed_relocated_address(
                decoded.address,
                source,
                self._registrar_function_entry(decoded.address),
                published_base,
                frozenset(),
            ):
                return False
        relocation_types: dict[int, list[int]] = {}
        references = []
        saw_load = False
        for relocation in self.image.relocations:
            relocation_types.setdefault(relocation.va, []).append(
                relocation.type
            )
            if not (
                relocation.type == 3
                and _is_mapped_span(self.image, relocation.va, 4)
                and int.from_bytes(
                    _read_loader_initialized(
                        self.image, relocation.va, 4
                    ),
                    "little",
                )
                == pointer_slot
            ):
                continue
            owner = self.byte_owners.get(relocation.va)
            if owner is None:
                continue
            reference = self._owned_decoded(owner)
            absolute_operands = [
                operand
                for operand in reference.operands
                if operand.type == X86_OP_MEM
                and operand.mem.segment == X86_REG_INVALID
                and operand.mem.base == X86_REG_INVALID
                and operand.mem.index == X86_REG_INVALID
                and (operand.mem.disp & 0xFFFF_FFFF) == pointer_slot
            ]
            if not absolute_operands:
                return False
            references.append(relocation.va)
            if any(operand.access & CS_AC_WRITE for operand in absolute_operands):
                if owner not in {
                    row.instruction_address
                    for row in self.global_slot_writes.get(pointer_slot, ())
                }:
                    return False
                continue
            if not (
                reference.id == X86_INS_MOV
                and len(reference.operands) == 2
                and reference.operands[0].type == X86_OP_REG
                and reference.operands[0].size == 4
                and reference.operands[1] in absolute_operands
            ):
                return False
            function_entry = self._registrar_function_entry(owner)
            if function_entry is None or not (
                self._pointer_definition_preserves_field_without_escape(
                    owner, function_entry, field
                )
            ):
                return False
            saw_load = True
        return (
            saw_load
            and bool(references)
            and all(
                relocation_types[address] == [3]
                for address in references
            )
        )

    def _relocated_global_pointer_publication(
        self,
        owner: int,
        relocation_address: int,
        published_field: int,
    ) -> bool:
        decoded = self._owned_decoded(owner)
        if not (
            decoded.id == X86_INS_MOV
            and len(decoded.operands) == 2
            and decoded.operands[0].type == X86_OP_MEM
            and decoded.operands[0].size == 4
            and decoded.operands[1].type == X86_OP_IMM
            and decoded.operands[1].size == 4
            and decoded.operands[1].imm & 0xFFFF_FFFF == published_field
            and relocation_address
            == decoded.address + decoded.imm_offset
        ):
            return False
        pointer_slot = self._absolute_memory_operand(decoded.operands[0])
        return (
            pointer_slot is not None
            and pointer_slot != published_field
            and self._global_pointer_slot_preserves_published_field(
                pointer_slot, published_field, 0
            )
        )

    def _function_argument_escapes_only_to_closed_global_pointer(
        self,
        function_entry: int,
        argument_index: int,
        published_base: int,
        field: int,
        active: frozenset[tuple[int, int, int, int]] = frozenset(),
    ) -> bool:
        """Allow one pointer argument to escape only by closed publication."""
        key = (function_entry, argument_index, published_base, field)
        if key in active:
            return False
        states = self._relative_pointer_states(
            function_entry,
            argument_index=argument_index,
            propagate_call_returns=False,
            allow_partial_taint=True,
            collapse_nonnegative_offsets=True,
        )
        if states is None:
            return False
        next_active = active | {key}
        saw_publication = False
        saw_return = False
        for address in self._function_instruction_addresses(function_entry):
            state = states.get(address)
            if state is None:
                continue
            decoded = self._owned_decoded(address)
            if decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                destination, source = decoded.operands
                source_offsets = self._relative_operand_offsets(
                    address,
                    source,
                    function_entry,
                    argument_index,
                    states,
                )
                if destination.type == X86_OP_MEM and source_offsets:
                    pointer_slot = self._absolute_memory_operand(destination)
                    if not (
                        source.type == X86_OP_REG
                        and source.size == 4
                        and source_offsets == frozenset({0})
                        and destination.size == 4
                        and pointer_slot is not None
                        and pointer_slot != published_base
                        and self._global_pointer_slot_preserves_published_field(
                            pointer_slot, published_base, field
                        )
                    ):
                        return False
                    saw_publication = True
            if decoded.group(CS_GRP_CALL):
                target = self.direct_call_targets_by_source.get(address)
                if state[0][_REGISTER_FAMILIES.index("ecx")] and (
                    target is None
                    or self._function_reads_incoming_register(target, "ecx")
                ):
                    return False
                passed_pointer = False
                return_may_alias = False
                for callee_argument in range(8):
                    pushed = self._pushed_call_argument(
                        address, callee_argument
                    )
                    if pushed is None:
                        break
                    values = self._relative_operand_offsets(
                        pushed[0].address,
                        pushed[1],
                        function_entry,
                        argument_index,
                        states,
                    )
                    if not values:
                        continue
                    passed_pointer = True
                    if target is None or not (
                        self._function_argument_does_not_escape(
                            target, callee_argument
                        )
                        or (
                            values == frozenset({0})
                            and self._function_argument_escapes_only_to_closed_global_pointer(
                                target,
                                callee_argument,
                                published_base,
                                field,
                                next_active,
                            )
                        )
                    ):
                        return False
                    return_offsets = self._function_argument_return_offsets(
                        target, callee_argument
                    )
                    return_may_alias |= (
                        return_offsets is None or bool(return_offsets)
                    )
                if (
                    passed_pointer
                    and return_may_alias
                    and not self._call_return_is_not_used_as_pointer(
                        address, function_entry
                    )
                ):
                    return False
            if decoded.group(CS_GRP_RET):
                saw_return = True
                if state[0][_REGISTER_FAMILIES.index("eax")]:
                    return False
            if (
                decoded.group(CS_GRP_JUMP)
                and not self.non_call_successors.get(address)
                and any(state[0])
            ):
                return False
        return saw_publication and saw_return

    def _relocated_global_address_argument_reference(
        self,
        owner: int,
        relocation_address: int,
        published_base: int,
        field: int,
    ) -> bool:
        """Prove a relocated global address has only closed call uses."""
        decoded = self._owned_decoded(owner)
        if not (
            decoded.mnemonic == "push"
            and len(decoded.operands) == 1
            and decoded.operands[0].type == X86_OP_IMM
            and decoded.operands[0].size == 4
            and decoded.operands[0].imm & 0xFFFF_FFFF == published_base
            and decoded.imm_size == 4
            and relocation_address == decoded.address + decoded.imm_offset
        ):
            return False
        function_entry = self._registrar_function_entry(owner)
        if function_entry is None:
            return False
        uses: list[tuple[int, int]] = []
        for call in sorted(self.direct_calls, key=lambda row: row.address):
            if self._registrar_function_entry(call.address) != function_entry:
                continue
            for argument_index in range(8):
                pushed = self._pushed_call_argument(
                    call.address, argument_index
                )
                if pushed is None:
                    break
                if pushed[0].address == owner:
                    uses.append((call.target, argument_index))
        return bool(uses) and all(
            self._function_argument_preserves_field(target, argument, field)
            and (
                self._function_argument_does_not_escape(target, argument)
                or self._function_argument_escapes_only_to_closed_global_pointer(
                    target,
                    argument,
                    published_base,
                    field,
                )
            )
            for target, argument in uses
        )

    def _argument_is_closed_relocated_address(
        self,
        function_entry: int,
        argument_index: int,
        target: int,
        visited: frozenset[tuple[int, int, int]],
    ) -> bool:
        key = (function_entry, argument_index, target)
        if key in visited or not self._incoming_call_domain_is_closed(
            function_entry
        ):
            return False
        callers = self._incoming_call_sites(function_entry)
        if not callers:
            return False
        next_visited = visited | {key}
        for call_address in callers:
            pushed = self._pushed_call_argument(
                call_address, argument_index
            )
            if pushed is None or not self._operand_is_closed_relocated_address(
                pushed[0].address,
                pushed[1],
                pushed[2],
                target,
                next_visited,
            ):
                return False
        return True

    def _operand_is_closed_relocated_address(
        self,
        address: int,
        operand,
        function_entry: int | None,
        target: int,
        visited: frozenset[tuple[int, int, int]],
    ) -> bool:
        if function_entry is None:
            return False
        decoded = self._owned_decoded(address)
        if operand.type == X86_OP_IMM:
            return (
                operand.imm & 0xFFFF_FFFF == target
                and decoded.imm_size == 4
                and any(
                    row.type == 3
                    and row.va == decoded.address + decoded.imm_offset
                    for row in self.image.relocations
                )
            )
        argument_index = self._operand_argument_index(
            address, operand, function_entry
        )
        if argument_index is not None:
            return self._argument_is_closed_relocated_address(
                function_entry,
                argument_index,
                target,
                visited,
            )
        if operand.type != X86_OP_REG:
            return False
        definitions = self._register_definitions_across_blocks(
            address,
            self._register_family(operand.reg),
            function_entry,
        )
        if not definitions:
            return False
        for definition_address in definitions:
            definition = self._owned_decoded(definition_address)
            if not (
                definition.id == X86_INS_MOV
                and len(definition.operands) == 2
                and definition.operands[0].type == X86_OP_REG
                and definition.operands[0].size == 4
                and self._operand_is_closed_relocated_address(
                    definition.address,
                    definition.operands[1],
                    function_entry,
                    target,
                    visited,
                )
            ):
                return False
        return True

    def _global_has_runtime_descriptor_field_origin(
        self,
        slot: int,
        pointer_field: int,
        target_field: int,
        copy_function: int,
        source_bases: frozenset[int],
        visited: frozenset[tuple[Any, ...]],
    ) -> bool:
        cache_key = (
            slot,
            pointer_field,
            target_field,
            copy_function,
            tuple(sorted(source_bases)),
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.global_runtime_descriptor_field_origin_cache:
            return True
        key = (
            slot,
            "runtime-field-global",
            pointer_field,
            target_field,
        )
        if key in visited:
            return False
        try:
            initial = int.from_bytes(
                _read_loader_initialized(self.image, slot, 4), "little"
            )
        except ValueError:
            return False
        if initial != 0:
            return False
        writes = tuple(
            sorted(
                self.global_slot_writes.get(slot, ()),
                key=lambda row: (row.instruction_address, row.provenance),
            )
        )
        if not writes:
            return False
        write_addresses = {row.instruction_address for row in writes}
        next_visited = visited | {key}
        for write in writes:
            decoded = self._owned_decoded(write.instruction_address)
            if not (
                decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_MEM
                and decoded.operands[0].size == 4
                and self._absolute_memory_operand(decoded.operands[0])
                == slot
            ):
                return False
            source = decoded.operands[1]
            if (
                source.type == X86_OP_IMM
                and source.imm & 0xFFFF_FFFF == 0
            ):
                continue
            writer_entry = self._registrar_function_entry(
                write.instruction_address
            )
            if writer_entry is None or not (
                self._operand_has_runtime_descriptor_field_origin(
                    write.instruction_address,
                    source,
                    writer_entry,
                    pointer_field,
                    target_field,
                    copy_function,
                    source_bases,
                    next_visited,
                )
            ):
                return False

        for address, writers in self.absolute_memory_writes.items():
            for writer in writers:
                decoded = self._owned_decoded(writer)
                widths = {
                    operand.size
                    for operand in decoded.operands
                    if operand.type == X86_OP_MEM
                    and operand.access & CS_AC_WRITE
                    and self._absolute_memory_operand(operand) == address
                }
                if any(
                    address < slot + 4 and slot < address + width
                    for width in widths
                ) and writer not in write_addresses:
                    return False

        relocation_types: dict[int, list[int]] = {}
        references = []
        for relocation in self.image.relocations:
            relocation_types.setdefault(relocation.va, []).append(
                relocation.type
            )
            if not (
                relocation.type == 3
                and _is_mapped_span(self.image, relocation.va, 4)
                and int.from_bytes(
                    _read_loader_initialized(
                        self.image, relocation.va, 4
                    ),
                    "little",
                )
                == slot
            ):
                continue
            owner = self.byte_owners.get(relocation.va)
            if owner is None:
                # An executable-source relocation outside the current least
                # reachable closure is not an executable read or write.  Its
                # residue/Ghidra obligation remains fail-closed elsewhere; if
                # later provenance promotes it, recovery restarts and the
                # summary signature invalidates this successful proof.
                continue
            reference = self._owned_decoded(owner)
            if not any(
                operand.type == X86_OP_MEM
                and operand.mem.segment == X86_REG_INVALID
                and operand.mem.base == X86_REG_INVALID
                and operand.mem.index == X86_REG_INVALID
                and (operand.mem.disp & 0xFFFF_FFFF) == slot
                for operand in reference.operands
            ) and not (
                self._relocated_global_zeroing_reference(owner, slot)
                or self._relocated_global_pointer_publication(
                    owner, relocation.va, slot
                )
                or self._relocated_global_address_argument_reference(
                    owner, relocation.va, slot, 0
                )
            ):
                return False
            references.append(relocation.va)
        if not references or any(
            relocation_types[address] != [3] for address in references
        ):
            return False
        self.global_runtime_descriptor_field_origin_cache.add(cache_key)
        return True

    def _operand_has_runtime_descriptor_field_origin(
        self,
        address: int,
        operand,
        function_entry: int,
        pointer_field: int,
        target_field: int,
        copy_function: int,
        source_bases: frozenset[int],
        visited: frozenset[tuple[Any, ...]],
    ) -> bool:
        if operand.type == X86_OP_IMM:
            return operand.imm & 0xFFFF_FFFF == 0
        if operand.type == X86_OP_REG:
            return self._register_has_runtime_descriptor_field_origin(
                address,
                self._register_family(operand.reg),
                function_entry,
                pointer_field,
                target_field,
                copy_function,
                source_bases,
                visited,
            )
        argument_index = self._stack_argument_index_at(
            address, operand, function_entry
        )
        if argument_index is not None:
            return self._argument_has_runtime_descriptor_field_origin(
                function_entry,
                argument_index,
                pointer_field,
                target_field,
                copy_function,
                source_bases,
                visited,
            )
        if operand.type != X86_OP_MEM or operand.size != 4:
            return False
        memory = operand.mem
        if (
            memory.segment != X86_REG_INVALID
            or memory.index != X86_REG_INVALID
        ):
            return False
        if memory.base == X86_REG_INVALID:
            return self._global_has_runtime_descriptor_field_origin(
                memory.disp & 0xFFFF_FFFF,
                pointer_field,
                target_field,
                copy_function,
                source_bases,
                visited,
            )
        descriptor_family = self._register_family(memory.base)
        finite_bases = self._finite_register_values_across_blocks(
            address,
            descriptor_family,
            function_entry,
            frozenset(),
        )
        if finite_bases is not None and finite_bases[0]:
            pointer_identity = self._register_global_pointer_field_identity(
                address, descriptor_family, function_entry
            )
            published_bases: frozenset[int] | None = None
            published_field = 0
            if pointer_identity is not None:
                pointer_slot, pointer_offset = pointer_identity
                pointer_values = self._finite_global_slot_values(
                    pointer_slot, frozenset()
                )
                if pointer_values is not None:
                    published_bases = pointer_values[0] - {0}
                    published_field = pointer_offset + memory.disp
            mapped_fields = {
                (base + memory.disp) & 0xFFFF_FFFF
                for base in finite_bases[0]
                if _is_mapped_span(
                    self.image,
                    (base + memory.disp) & 0xFFFF_FFFF,
                    4,
                )
            }
            published_pointer_is_closed = (
                pointer_identity is None
                or published_bases is not None
                and bool(published_bases)
                and all(
                    self._global_pointer_slot_preserves_published_field(
                        pointer_identity[0],
                        published_base,
                        published_field,
                    )
                    for published_base in published_bases
                )
            )
            if (
                published_pointer_is_closed
                and mapped_fields
                and all(
                    self._global_has_runtime_descriptor_field_origin(
                        field_address,
                        pointer_field,
                        target_field,
                        copy_function,
                        source_bases,
                        visited,
                    )
                    for field_address in mapped_fields
                )
            ):
                return True
        if not self._register_has_copied_descriptor_origin(
            address,
            descriptor_family,
            function_entry,
            copy_function,
            source_bases,
            visited,
        ):
            return False
        return self._descriptor_back_reference_is_initialized(
            address,
            descriptor_family,
            function_entry,
            memory.disp,
            pointer_field,
            target_field,
            visited,
        )

    def _operand_has_copied_back_reference_origin(
        self,
        address: int,
        operand,
        function_entry: int,
        copy_function: int,
        source_bases: frozenset[int],
        visited: frozenset[tuple[Any, ...]],
    ) -> bool:
        cache_key = (
            address,
            str(operand),
            function_entry,
            copy_function,
            tuple(sorted(source_bases)),
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.copied_back_reference_origin_cache:
            return True
        key = (address, "copied-back-reference", str(operand))
        if key in visited:
            return False
        next_visited = visited | {key}
        if operand.type == X86_OP_REG:
            definitions = self._register_definitions_across_blocks(
                address,
                self._register_family(operand.reg),
                function_entry,
            )
            if not definitions:
                return False
            for definition_address in definitions:
                definition = self._owned_decoded(definition_address)
                if not (
                    definition.id == X86_INS_MOV
                    and len(definition.operands) == 2
                    and definition.operands[0].type == X86_OP_REG
                    and self._operand_has_copied_back_reference_origin(
                        definition.address,
                        definition.operands[1],
                        function_entry,
                        copy_function,
                        source_bases,
                        next_visited,
                    )
                ):
                    return False
            self.copied_back_reference_origin_cache.add(cache_key)
            return True
        if operand.type != X86_OP_MEM or operand.size != 4:
            return False
        memory = operand.mem
        if (
            memory.segment != X86_REG_INVALID
            or memory.base == X86_REG_INVALID
            or memory.index != X86_REG_INVALID
        ):
            return False
        holder_family = self._register_family(memory.base)
        definitions = self._register_definitions_across_blocks(
            address, holder_family, function_entry
        )
        if not definitions:
            return False
        for definition_address in definitions:
            definition = self._owned_decoded(definition_address)
            if not (
                definition.id == X86_INS_MOV
                and len(definition.operands) == 2
                and definition.operands[0].type == X86_OP_REG
                and definition.operands[1].type == X86_OP_MEM
                and definition.operands[1].size == 4
                and definition.operands[1].mem.segment
                == X86_REG_INVALID
                and definition.operands[1].mem.base
                != X86_REG_INVALID
                and definition.operands[1].mem.index
                == X86_REG_INVALID
                and self._register_has_runtime_descriptor_field_origin(
                    definition.address,
                    self._register_family(
                        definition.operands[1].mem.base
                    ),
                    function_entry,
                    definition.operands[1].mem.disp,
                    memory.disp,
                    copy_function,
                    source_bases,
                    next_visited,
                )
            ):
                return False
        self.copied_back_reference_origin_cache.add(cache_key)
        return True

    def _copied_descriptor_source_domains(
        self,
        visited: frozenset[tuple[int, str]],
    ) -> (
        tuple[
            int,
            tuple[frozenset[int], frozenset[int], frozenset[int]],
        ]
        | None
    ):
        signature = self._summary_fact_signature()
        if signature in self.copied_descriptor_cache:
            return self.copied_descriptor_cache[signature]
        candidate_functions = {
            function_entry
            for row, instruction in self.instructions.items()
            if instruction.mnemonic == "rep movsd"
            and (
                function_entry := self._registrar_function_entry(row)
            )
            is not None
        }
        candidates = []
        ordered_instructions = sorted(self.instructions)
        for function_entry in sorted(candidate_functions):
            following_entry = min(
                (
                    row
                    for row in self.function_addresses
                    if row > function_entry
                ),
                default=0x1_0000_0000,
            )
            mnemonics = [
                self.instructions[row].mnemonic
                for row in ordered_instructions
                if function_entry <= row < following_entry
            ]
            if (
                mnemonics.count("rep movsd") != 1
                or mnemonics.count("movsd") != 6
            ):
                continue
            has_nine_dword_copy = False
            for row in ordered_instructions:
                if not function_entry <= row < following_entry:
                    continue
                decoded = self._owned_decoded(row)
                if (
                    decoded.id == X86_INS_MOV
                    and len(decoded.operands) == 2
                    and decoded.operands[0].type == X86_OP_REG
                    and self._register_family(decoded.operands[0].reg) == "ecx"
                    and decoded.operands[1].type == X86_OP_IMM
                    and decoded.operands[1].imm == 9
                ):
                    has_nine_dword_copy = True
                    break
            if has_nine_dword_copy and self._is_descriptor_copy_constructor(
                function_entry, following_entry
            ):
                candidates.append(function_entry)
        if len(candidates) != 1:
            self.copied_descriptor_cache[signature] = None
            return None
        copy_function = candidates[0]
        decoded_call_sites = {
            row.address
            for row in self.direct_calls
            if row.target == copy_function
        }
        if (
            not decoded_call_sites
            or self._raw_direct_call_sites(copy_function)
            != decoded_call_sites
            or any(row.va == copy_function for row in self.image.exports)
            or any(
                row.type == 3
                and _is_mapped_span(self.image, row.va, 4)
                and int.from_bytes(
                    _read_loader_initialized(self.image, row.va, 4),
                    "little",
                )
                == copy_function
                for row in self.image.relocations
            )
        ):
            self.copied_descriptor_cache[signature] = None
            return None
        domains = []
        for argument_index in range(3):
            result = self._finite_argument_values(
                copy_function, argument_index, visited
            )
            if result is None:
                self.copied_descriptor_cache[signature] = None
                return None
            values, _ = result
            if any(
                value
                and (
                    not _is_mapped_span(self.image, value, 1)
                    or _is_executable_span(self.image, value, 1)
                )
                for value in values
            ):
                self.copied_descriptor_cache[signature] = None
                return None
            domains.append(values)
        final = (
            copy_function,
            (domains[0], domains[1], domains[2]),
        )
        self.copied_descriptor_cache[signature] = final
        return final

    def _argument_has_copy_constructor_origin(
        self,
        function_entry: int,
        argument_index: int,
        copy_function: int,
        visited: frozenset[tuple[int, int]],
    ) -> bool:
        key = (function_entry, argument_index)
        if key in visited or not self._incoming_call_domain_is_closed(
            function_entry
        ):
            return False
        cache_key = (
            function_entry,
            argument_index,
            copy_function,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.copy_origin_cache:
            return self.copy_origin_cache[cache_key]
        for call_address in self._incoming_call_sites(function_entry):
            pushed = self._pushed_call_argument(
                call_address, argument_index
            )
            if pushed is None or not (
                self._operand_has_copy_constructor_origin(
                    pushed[0].address,
                    pushed[1],
                    pushed[2],
                    copy_function,
                    visited | {key},
                )
            ):
                return False
        self.copy_origin_cache[cache_key] = True
        return True

    def _operand_has_copy_constructor_origin(
        self,
        address: int,
        operand,
        function_entry: int,
        copy_function: int,
        visited: frozenset[tuple[int, int]],
    ) -> bool:
        if operand.type == X86_OP_IMM:
            return operand.imm & 0xFFFF_FFFF == 0
        if operand.type == X86_OP_REG:
            return self._register_has_copy_constructor_origin(
                address,
                self._register_family(operand.reg),
                function_entry,
                copy_function,
                visited,
            )
        argument_index = self._stack_argument_index_at(
            address, operand, function_entry
        )
        if argument_index is not None:
            return self._argument_has_copy_constructor_origin(
                function_entry,
                argument_index,
                copy_function,
                visited,
            )
        logical_offset = self._stack_operand_logical_offset(
            address, operand, function_entry
        )
        if logical_offset is not None and (
            self._register_has_registered_copy_origin(
                address,
                f"stack:{logical_offset:+#x}",
                function_entry,
                copy_function,
            )
        ):
            return True
        if (
            operand.type == X86_OP_MEM
            and operand.size == 4
            and operand.mem.segment == X86_REG_INVALID
            and operand.mem.base == X86_REG_INVALID
            and operand.mem.index == X86_REG_INVALID
        ):
            return self._global_slot_has_copy_constructor_origin(
                operand.mem.disp & 0xFFFF_FFFF,
                copy_function,
                visited,
            )
        if (
            operand.type == X86_OP_MEM
            and operand.mem.segment == X86_REG_INVALID
            and operand.mem.index == X86_REG_INVALID
            and operand.mem.base != X86_REG_INVALID
        ):
            return self._object_field_has_copy_constructor_origin(
                address,
                self._register_family(operand.mem.base),
                operand.mem.disp,
                function_entry,
                copy_function,
                visited,
            )
        return False

    def _global_slot_has_copy_constructor_origin(
        self,
        slot: int,
        copy_function: int,
        visited: frozenset[tuple[int, int]],
    ) -> bool:
        """Prove one relocated global contains only null or fresh copies."""
        cache_key = (
            slot,
            copy_function,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.global_copy_origin_cache:
            return True
        key = (slot, 0x4_0000_0000)
        if key in visited:
            return False
        try:
            initial = int.from_bytes(
                _read_loader_initialized(self.image, slot, 4), "little"
            )
        except ValueError:
            return False
        if initial != 0:
            return False

        writes = tuple(
            sorted(
                self.global_slot_writes.get(slot, ()),
                key=lambda row: (row.instruction_address, row.provenance),
            )
        )
        if not writes:
            return False
        write_addresses = {row.instruction_address for row in writes}
        next_visited = visited | {key}
        for write in writes:
            if write.instruction_address not in self.instructions:
                return False
            decoded = self._owned_decoded(write.instruction_address)
            if (
                decoded.id != X86_INS_MOV
                or len(decoded.operands) != 2
                or decoded.operands[0].type != X86_OP_MEM
                or decoded.operands[0].size != 4
                or self._absolute_memory_operand(decoded.operands[0]) != slot
            ):
                return False
            source = decoded.operands[1]
            if (
                source.type == X86_OP_IMM
                and source.imm & 0xFFFF_FFFF == 0
            ):
                continue
            writer_entry = self._registrar_function_entry(
                write.instruction_address
            )
            if writer_entry is None or not (
                self._operand_has_copy_constructor_origin(
                    write.instruction_address,
                    source,
                    writer_entry,
                    copy_function,
                    next_visited,
                )
            ):
                return False

        for address, writers in self.absolute_memory_writes.items():
            for writer in writers:
                decoded = self._owned_decoded(writer)
                widths = {
                    operand.size
                    for operand in decoded.operands
                    if operand.type == X86_OP_MEM
                    and operand.access & CS_AC_WRITE
                    and self._absolute_memory_operand(operand) == address
                }
                if any(
                    address < slot + 4 and slot < address + width
                    for width in widths
                ) and writer not in write_addresses:
                    return False

        relocation_types: dict[int, list[int]] = {}
        references = []
        for relocation in self.image.relocations:
            relocation_types.setdefault(relocation.va, []).append(
                relocation.type
            )
            if not (
                relocation.type == 3
                and _is_mapped_span(self.image, relocation.va, 4)
            ):
                continue
            if int.from_bytes(
                _read_loader_initialized(self.image, relocation.va, 4),
                "little",
            ) != slot:
                continue
            owner = self.byte_owners.get(relocation.va)
            if owner is None:
                return False
            reference = self._owned_decoded(owner)
            if not any(
                operand.type == X86_OP_MEM
                and operand.mem.segment == X86_REG_INVALID
                and operand.mem.base == X86_REG_INVALID
                and operand.mem.index == X86_REG_INVALID
                and (operand.mem.disp & 0xFFFF_FFFF) == slot
                for operand in reference.operands
            ):
                return False
            references.append(relocation.va)
        if not references or any(
            relocation_types[address] != [3] for address in references
        ):
            return False

        self.global_copy_origin_cache.add(cache_key)
        return True

    def _pointer_field_has_copy_constructor_origin(
        self,
        address: int,
        operand,
        field: int,
        function_entry: int,
        copy_function: int,
        visited: frozenset[tuple[int, int]],
    ) -> bool:
        if operand.type == X86_OP_IMM:
            # A null object faults before a later field load can reach its
            # indirect transfer.  No non-null integer is accepted as an
            # object provenance fact.
            return operand.imm & 0xFFFF_FFFF == 0
        if operand.type == X86_OP_REG:
            return self._object_field_has_copy_constructor_origin(
                address,
                self._register_family(operand.reg),
                field,
                function_entry,
                copy_function,
                visited,
            )
        if (
            operand.type == X86_OP_MEM
            and operand.mem.segment == X86_REG_INVALID
            and operand.mem.base == X86_REG_INVALID
            and operand.mem.index == X86_REG_INVALID
            and operand.size == 4
        ):
            return self._closed_runtime_global_copy_field_origin(
                operand.mem.disp & 0xFFFF_FFFF,
                field,
                copy_function,
                visited,
            )
        argument_index = self._stack_argument_index_at(
            address, operand, function_entry
        )
        if argument_index is None:
            return False
        key = (function_entry, 0x1_0000_0000 + argument_index)
        if key in visited:
            return False
        callers = self._direct_calls_to(function_entry)
        if not callers:
            return False
        for call in callers:
            pushed = self._pushed_call_argument(call.address, argument_index)
            if pushed is None or not self._pointer_field_has_copy_constructor_origin(
                pushed[0].address,
                pushed[1],
                field,
                pushed[2],
                copy_function,
                visited | {key},
            ):
                return False
        return True

    def _function_instruction_addresses(
        self, function_entry: int
    ) -> tuple[int, ...]:
        cache_key = (function_entry, self._summary_fact_signature())
        cached = self.function_instruction_cache.get(cache_key)
        if cached is not None:
            return cached
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        result = tuple(
            row
            for row in sorted(self.instructions)
            if function_entry <= row < following_entry
        )
        self.function_instruction_cache[cache_key] = result
        return result

    def _relative_pointer_states(
        self,
        function_entry: int,
        *,
        argument_index: int | None = None,
        root_call: int | None = None,
        root_definition: int | None = None,
        propagate_call_returns: bool = True,
        allow_partial_taint: bool = False,
        collapse_nonnegative_offsets: bool = False,
    ) -> dict[int, tuple[tuple[frozenset[int], ...], int]] | None:
        """Track one pointer identity and constant interior offsets.

        Exactly one root is supplied: a stack argument, the EAX return from a
        particular direct call, or a register definition.  Unsupported pointer
        arithmetic, an unowned path, or an excessive offset domain fails
        closed.
        """
        if sum(
            value is not None
            for value in (argument_index, root_call, root_definition)
        ) != 1:
            return None
        cache_key = (
            function_entry,
            argument_index,
            root_call,
            root_definition,
            propagate_call_returns,
            allow_partial_taint,
            collapse_nonnegative_offsets,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.relative_pointer_state_cache:
            return self.relative_pointer_state_cache[cache_key]
        self.relative_pointer_state_cache[cache_key] = None
        if function_entry not in self.function_addresses:
            return None
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        empty = tuple(frozenset() for _ in _REGISTER_FAMILIES)
        family_index = {
            family: index
            for index, family in enumerate(_REGISTER_FAMILIES)
        }
        states: dict[
            int, tuple[tuple[frozenset[int], ...], int]
        ] = {
            function_entry: (
                empty,
                1 if root_call is not None or root_definition is not None else 2,
            )
        }
        pending = [function_entry]
        queued = {function_entry}
        iterations = 0

        def normalize(values) -> frozenset[int]:
            result = frozenset(values)
            if collapse_nonnegative_offsets and result and all(
                value >= 0 for value in result
            ):
                return frozenset({0})
            return result

        while pending:
            current = heapq.heappop(pending)
            queued.remove(current)
            if current not in self.instructions:
                return None
            incoming_offsets, incoming_seen = states[current]
            offsets = list(incoming_offsets)
            seen = incoming_seen
            decoded = self._owned_decoded(current)

            def register_offsets(register: int) -> frozenset[int]:
                return offsets[
                    family_index[self._register_family(register)]
                ]

            if decoded.group(CS_GRP_CALL):
                returned_offsets: set[int] = set()
                target = self.direct_call_targets_by_source.get(current)
                for callee_argument in range(8) if propagate_call_returns else ():
                    pushed = self._pushed_call_argument(
                        current, callee_argument
                    )
                    if pushed is None:
                        break
                    argument_offsets = self._relative_operand_offsets(
                        pushed[0].address,
                        pushed[1],
                        function_entry,
                        argument_index,
                        states,
                    )
                    if not argument_offsets:
                        continue
                    if target is None:
                        if not self._external_call_has_scalar_return(decoded):
                            return None
                        continue
                    return_offsets = self._function_argument_return_offsets(
                        target, callee_argument
                    )
                    if return_offsets is None:
                        return None
                    returned_offsets.update(
                        base + returned
                        for base in argument_offsets
                        for returned in return_offsets
                    )
                for family in ("eax", "ecx", "edx"):
                    offsets[family_index[family]] = frozenset()
                offsets[family_index["eax"]] = frozenset(
                    returned_offsets
                )
                if current == root_call:
                    if seen not in {1, 3}:
                        return None
                    offsets[family_index["eax"]] = frozenset({0})
                    seen = 2
            elif decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                destination, source = decoded.operands
                if destination.type == X86_OP_REG:
                    destination_family = self._register_family(
                        destination.reg
                    )
                    destination_index = family_index[destination_family]
                    if destination.size != 4 and offsets[destination_index]:
                        if allow_partial_taint:
                            value = offsets[destination_index]
                            offsets[destination_index] = value
                            destination = None
                        else:
                            return None
                    if destination is None:
                        pass
                    else:
                        source_argument = self._stack_argument_index_at(
                            current, source, function_entry
                        )
                        if (
                            argument_index is not None
                            and source_argument == argument_index
                        ):
                            value = frozenset({0})
                        elif source.type == X86_OP_REG:
                            value = register_offsets(source.reg)
                        else:
                            value = frozenset()
                        offsets[destination_index] = value
            elif decoded.id == X86_INS_LEA and len(decoded.operands) == 2:
                destination, source = decoded.operands
                if destination.type != X86_OP_REG or source.type != X86_OP_MEM:
                    return None
                destination_index = family_index[
                    self._register_family(destination.reg)
                ]
                base_values = (
                    frozenset()
                    if source.mem.base == X86_REG_INVALID
                    else register_offsets(source.mem.base)
                )
                index_values = (
                    frozenset()
                    if source.mem.index == X86_REG_INVALID
                    else register_offsets(source.mem.index)
                )
                if index_values or (
                    base_values and source.mem.index != X86_REG_INVALID
                ):
                    return None
                offsets[destination_index] = normalize(
                    value + source.mem.disp for value in base_values
                )
            elif (
                decoded.mnemonic in {"add", "sub"}
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and decoded.operands[1].type == X86_OP_IMM
            ):
                destination_index = family_index[
                    self._register_family(decoded.operands[0].reg)
                ]
                delta = decoded.operands[1].imm
                if decoded.mnemonic == "sub":
                    delta = -delta
                offsets[destination_index] = normalize(
                    value + delta for value in offsets[destination_index]
                )
            elif (
                decoded.mnemonic == "and"
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and decoded.operands[0].size == 4
                and decoded.operands[1].type == X86_OP_IMM
                and decoded.operands[1].imm & 0xFFFF_FFFF == 0xFF
            ):
                destination = decoded.operands[0]
                destination_index = family_index[
                    self._register_family(destination.reg)
                ]
                previous = self._previous_instruction(current)
                canonical_setcc = False
                if previous is not None:
                    prior = self._owned_decoded(previous.address)
                    canonical_setcc = (
                        prior.mnemonic.startswith("set")
                        and len(prior.operands) == 1
                        and prior.operands[0].type == X86_OP_REG
                        and prior.operands[0].reg
                        in {
                            x86_const.X86_REG_AL,
                            x86_const.X86_REG_BL,
                            x86_const.X86_REG_CL,
                            x86_const.X86_REG_DL,
                        }
                        and self._register_family(prior.operands[0].reg)
                        == self._register_family(destination.reg)
                    )
                if offsets[destination_index] and not canonical_setcc:
                    return None
                offsets[destination_index] = frozenset()
            elif (
                decoded.mnemonic == "inc"
                and len(decoded.operands) == 1
                and decoded.operands[0].type == X86_OP_REG
                and decoded.operands[0].size == 4
            ):
                destination_index = family_index[
                    self._register_family(decoded.operands[0].reg)
                ]
                offsets[destination_index] = normalize(
                    value + 1 for value in offsets[destination_index]
                )
            elif (
                decoded.mnemonic == "add"
                and len(decoded.operands) == 2
                and all(row.type == X86_OP_REG for row in decoded.operands)
            ):
                destination_index = family_index[
                    self._register_family(decoded.operands[0].reg)
                ]
                source_values = register_offsets(decoded.operands[1].reg)
                if source_values:
                    return None
                if offsets[destination_index]:
                    if not (
                        collapse_nonnegative_offsets
                        and self._register_is_forward_string_extent(
                            current,
                            self._register_family(decoded.operands[1].reg),
                            function_entry,
                        )
                    ):
                        return None
                    offsets[destination_index] = normalize(
                        offsets[destination_index]
                    )
            elif (
                decoded.id == X86_INS_XOR
                and len(decoded.operands) == 2
                and all(row.type == X86_OP_REG for row in decoded.operands)
                and self._register_family(decoded.operands[0].reg)
                == self._register_family(decoded.operands[1].reg)
            ):
                destination_index = family_index[
                    self._register_family(decoded.operands[0].reg)
                ]
                if (
                    decoded.operands[0].size != 4
                    and offsets[destination_index]
                ):
                    if not allow_partial_taint:
                        return None
                else:
                    offsets[destination_index] = frozenset()
            elif decoded.mnemonic in {"stosb", "stosd"}:
                step = 1 if decoded.mnemonic == "stosb" else 4
                index = family_index["edi"]
                offsets[index] = normalize(
                    value + step for value in offsets[index]
                )
            elif decoded.mnemonic in {
                "rep movsb",
                "rep movsw",
                "rep movsd",
            }:
                if any(
                    row < current
                    and self._owned_decoded(row).mnemonic == "std"
                    for row in self._function_instruction_addresses(
                        function_entry
                    )
                ):
                    return None
                count = self._resolve_register_constant_before(
                    current, x86_const.X86_REG_ECX
                )
                if count is None:
                    if any(
                        offsets[family_index[family]]
                        for family in ("esi", "edi")
                    ):
                        return None
                else:
                    step = {
                        "rep movsb": 1,
                        "rep movsw": 2,
                        "rep movsd": 4,
                    }[decoded.mnemonic]
                    for family in ("esi", "edi"):
                        index = family_index[family]
                        offsets[index] = normalize(
                            value + count * step
                            for value in offsets[index]
                        )
                offsets[family_index["ecx"]] = frozenset()
            elif decoded.mnemonic in {"movsb", "movsw", "movsd"}:
                if any(
                    row < current
                    and self._owned_decoded(row).mnemonic == "std"
                    for row in self._function_instruction_addresses(
                        function_entry
                    )
                ):
                    return None
                step = {"movsb": 1, "movsw": 2, "movsd": 4}[
                    decoded.mnemonic
                ]
                for family in ("esi", "edi"):
                    index = family_index[family]
                    offsets[index] = normalize(
                        value + step for value in offsets[index]
                    )
            elif decoded.mnemonic == "lodsb":
                index = family_index["esi"]
                offsets[index] = normalize(
                    value + 1 for value in offsets[index]
                )
                eax_index = family_index["eax"]
                if offsets[eax_index]:
                    return None
                offsets[eax_index] = frozenset()
            elif decoded.mnemonic in {"rep stosb", "repne scasb"}:
                offsets[family_index["edi"]] = frozenset()
                offsets[family_index["ecx"]] = frozenset()
            elif decoded.mnemonic == "pop" and decoded.operands:
                if decoded.operands[0].type == X86_OP_REG:
                    offsets[
                        family_index[
                            self._register_family(decoded.operands[0].reg)
                        ]
                    ] = frozenset()
            else:
                written_families = {
                    self._register_family(register)
                    for register in decoded.regs_write
                    if self._register_family(register) in family_index
                } | {
                    self._register_family(row.reg)
                    for row in decoded.operands
                    if row.type == X86_OP_REG
                    and row.access & CS_AC_WRITE
                    and self._register_family(row.reg) in family_index
                }
                for family in written_families:
                    index = family_index[family]
                    if offsets[index]:
                        written_operands = [
                            row
                            for row in decoded.operands
                            if row.type == X86_OP_REG
                            and row.access & CS_AC_WRITE
                            and self._register_family(row.reg) == family
                        ]
                        if any(
                            row.size == 4
                            and not row.access & CS_AC_READ
                            for row in written_operands
                        ):
                            offsets[index] = frozenset()
                        elif allow_partial_taint and written_operands and all(
                            row.size < 4 for row in written_operands
                        ):
                            continue
                        else:
                            return None
                    else:
                        offsets[index] = frozenset()

            if current == root_definition:
                if (
                    seen not in {1, 3}
                    or decoded.id != X86_INS_MOV
                    or len(decoded.operands) != 2
                    or decoded.operands[0].type != X86_OP_REG
                    or decoded.operands[0].size != 4
                ):
                    return None
                destination_index = family_index[
                    self._register_family(decoded.operands[0].reg)
                ]
                offsets[destination_index] = frozenset({0})
                seen = 2

            output = (tuple(offsets), seen)
            for successor in self._summary_successors(
                current, function_entry, following_entry
            ):
                prior = states.get(successor)
                if prior is None:
                    joined = output
                else:
                    joined_offsets = tuple(
                        normalize(prior[0][index] | output[0][index])
                        for index in range(len(_REGISTER_FAMILIES))
                    )
                    if any(
                        len(values) > self.limits.max_finite_values
                        for values in joined_offsets
                    ):
                        return None
                    joined = (joined_offsets, prior[1] | output[1])
                if prior == joined:
                    continue
                states[successor] = joined
                if successor not in queued:
                    heapq.heappush(pending, successor)
                    queued.add(successor)
            iterations += 1
            self.limits.check("max_summary_iterations", iterations)
        self.relative_pointer_state_cache[cache_key] = states
        return states

    def _register_is_forward_string_extent(
        self,
        address: int,
        register_family: str,
        function_entry: int,
    ) -> bool:
        cursor = address
        rows = []
        for _ in range(8):
            previous = self._previous_instruction(cursor)
            if previous is None or previous.address < function_entry:
                break
            rows.append(self._owned_decoded(previous.address))
            cursor = previous.address
        if len(rows) < 5:
            return False
        subtract = rows[0]
        constant = rows[1]
        if not (
            subtract.mnemonic == "sub"
            and len(subtract.operands) == 2
            and all(row.type == X86_OP_REG for row in subtract.operands)
            and self._register_family(subtract.operands[0].reg)
            == register_family
            and self._register_family(subtract.operands[1].reg) == "ecx"
            and constant.id == X86_INS_MOV
            and len(constant.operands) == 2
            and constant.operands[0].type == X86_OP_REG
            and self._register_family(constant.operands[0].reg)
            == register_family
            and constant.operands[1].type == X86_OP_IMM
            and constant.operands[1].imm & 0xFFFF_FFFF == 0xFFFF_FFFE
        ):
            return False
        return (
            any(row.mnemonic == "repne scasb" for row in rows[2:])
            and any(
                row.id == X86_INS_MOV
                and len(row.operands) == 2
                and row.operands[0].type == X86_OP_REG
                and self._register_family(row.operands[0].reg) == "ecx"
                and row.operands[1].type == X86_OP_IMM
                and row.operands[1].imm & 0xFFFF_FFFF == 0xFFFF_FFFF
                for row in rows[2:]
            )
            and any(
                row.id == X86_INS_XOR
                and len(row.operands) == 2
                and all(value.type == X86_OP_REG for value in row.operands)
                and all(
                    self._register_family(value.reg) == "eax"
                    for value in row.operands
                )
                for row in rows[2:]
            )
        )

    def _relative_operand_offsets(
        self,
        address: int,
        operand,
        function_entry: int,
        argument_index: int | None,
        states: dict[int, tuple[tuple[frozenset[int], ...], int]],
    ) -> frozenset[int]:
        state = states.get(address)
        if state is None:
            return frozenset()
        if operand.type == X86_OP_REG:
            family = self._register_family(operand.reg)
            return state[0][_REGISTER_FAMILIES.index(family)]
        if argument_index is not None and (
            self._stack_argument_index_at(
                address, operand, function_entry
            )
            == argument_index
        ):
            return frozenset({0})
        return frozenset()

    def _import_for_call(self, decoded):
        if len(decoded.operands) != 1 or decoded.operands[0].type != X86_OP_MEM:
            return None
        memory = decoded.operands[0].mem
        if (
            memory.segment != X86_REG_INVALID
            or memory.base != X86_REG_INVALID
            or memory.index != X86_REG_INVALID
        ):
            return None
        iat_va = memory.disp & 0xFFFF_FFFF
        return next(
            (row for row in self.image.imports if row.iat_va == iat_va),
            None,
        )

    def _external_call_has_scalar_return(self, decoded) -> bool:
        imported = self._import_for_call(decoded)
        return (
            imported is not None
            and imported.dll.casefold() == "kernel32.dll"
            and imported.name in {"GetCurrentDirectoryA", "GetLastError"}
        )

    def _external_call_argument_preserves_field(
        self,
        decoded,
        call_address: int,
        argument_index: int,
        field: int,
    ) -> bool:
        imported = self._import_for_call(decoded)
        if (
            imported is None
            or imported.dll.casefold() != "kernel32.dll"
            or imported.name != "GetCurrentDirectoryA"
            or argument_index != 1
        ):
            return False
        length = self._pushed_call_argument(call_address, 0)
        if length is None or length[1].type != X86_OP_IMM:
            return False
        byte_count = length[1].imm & 0xFFFF_FFFF
        return field + 4 <= 0 or field >= byte_count

    def _function_argument_return_offsets(
        self, function_entry: int, argument_index: int
    ) -> frozenset[int] | None:
        cache_key = (
            function_entry,
            argument_index,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.argument_return_offset_cache:
            return self.argument_return_offset_cache[cache_key]
        if cache_key in self.argument_return_offset_active:
            return None
        self.argument_return_offset_active.add(cache_key)
        try:
            states = self._relative_pointer_states(
                function_entry,
                argument_index=argument_index,
                collapse_nonnegative_offsets=True,
            )
            if states is None:
                result = (
                    frozenset()
                    if self._function_returns_pointer_independent_constants(
                        function_entry
                    )
                    else None
                )
            else:
                returns = []
                for address in self._function_instruction_addresses(
                    function_entry
                ):
                    if not self._owned_decoded(address).group(CS_GRP_RET):
                        continue
                    state = states.get(address)
                    if state is None:
                        continue
                    returns.append(
                        state[0][_REGISTER_FAMILIES.index("eax")]
                    )
                result = (
                    frozenset().union(*returns) if returns else None
                )
        finally:
            self.argument_return_offset_active.remove(cache_key)
        self.argument_return_offset_cache[cache_key] = result
        return result

    def _function_returns_pointer_independent_constants(
        self, function_entry: int
    ) -> bool:
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        saw_return = False
        for address in self._function_instruction_addresses(function_entry):
            if not (
                self._owned_decoded(address).group(CS_GRP_RET)
                and self._reachable_within_function(
                    function_entry,
                    address,
                    function_entry,
                    following_entry,
                )
            ):
                continue
            saw_return = True
            definitions = self._register_definitions_across_blocks(
                address, "eax", function_entry
            )
            if not definitions:
                return False
            for definition_address in definitions:
                definition = self._owned_decoded(definition_address)
                immediate = (
                    definition.id == X86_INS_MOV
                    and len(definition.operands) == 2
                    and definition.operands[0].type == X86_OP_REG
                    and definition.operands[0].size == 4
                    and self._register_family(definition.operands[0].reg)
                    == "eax"
                    and definition.operands[1].type == X86_OP_IMM
                )
                zero = (
                    definition.id == X86_INS_XOR
                    and len(definition.operands) == 2
                    and all(
                        row.type == X86_OP_REG
                        and row.size == 4
                        and self._register_family(row.reg) == "eax"
                        for row in definition.operands
                    )
                )
                if not (immediate or zero):
                    return False
        return saw_return

    def _function_argument_does_not_escape(
        self,
        function_entry: int,
        argument_index: int,
        active: frozenset[tuple[int, int]] = frozenset(),
    ) -> bool:
        key = (function_entry, argument_index)
        if key in active:
            return False
        states = self._relative_pointer_states(
            function_entry,
            argument_index=argument_index,
            propagate_call_returns=False,
            allow_partial_taint=True,
            collapse_nonnegative_offsets=True,
        )
        if states is None:
            return False
        next_active = active | {key}
        saw_return = False
        for address in self._function_instruction_addresses(function_entry):
            state = states.get(address)
            if state is None:
                continue
            decoded = self._owned_decoded(address)
            if decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                destination, source = decoded.operands
                if (
                    destination.type == X86_OP_MEM
                    and self._relative_operand_offsets(
                        address,
                        source,
                        function_entry,
                        argument_index,
                        states,
                    )
                ):
                    return False
            if decoded.group(CS_GRP_CALL):
                target = self.direct_call_targets_by_source.get(address)
                if state[0][_REGISTER_FAMILIES.index("ecx")] and (
                    target is None
                    or self._function_reads_incoming_register(target, "ecx")
                ):
                    return False
                passed_pointer = False
                return_may_alias = False
                for callee_argument in range(8):
                    pushed = self._pushed_call_argument(
                        address, callee_argument
                    )
                    if pushed is None:
                        break
                    values = self._relative_operand_offsets(
                        pushed[0].address,
                        pushed[1],
                        function_entry,
                        argument_index,
                        states,
                    )
                    if not values:
                        continue
                    passed_pointer = True
                    if target is None or not (
                        self._function_argument_does_not_escape(
                            target, callee_argument, next_active
                        )
                    ):
                        return False
                    return_offsets = self._function_argument_return_offsets(
                        target, callee_argument
                    )
                    return_may_alias |= (
                        return_offsets is None or bool(return_offsets)
                    )
                if (
                    passed_pointer
                    and return_may_alias
                    and not self._call_return_is_not_used_as_pointer(
                        address, function_entry
                    )
                ):
                    return False
            if decoded.group(CS_GRP_RET):
                saw_return = True
                if state[0][_REGISTER_FAMILIES.index("eax")]:
                    return False
            if (
                decoded.group(CS_GRP_JUMP)
                and not self.non_call_successors.get(address)
                and any(state[0])
            ):
                return False
        return saw_return

    def _function_argument_is_not_used_as_pointer(
        self,
        function_entry: int,
        argument_index: int,
        active: frozenset[tuple[int, int]] = frozenset(),
    ) -> bool:
        key = (function_entry, argument_index)
        if key in active:
            return False
        states = self._relative_pointer_states(
            function_entry,
            argument_index=argument_index,
            propagate_call_returns=False,
            allow_partial_taint=True,
            collapse_nonnegative_offsets=True,
        )
        if states is None:
            return False
        next_active = active | {key}
        saw_return = False
        for address in self._function_instruction_addresses(function_entry):
            state = states.get(address)
            if state is None:
                continue
            decoded = self._owned_decoded(address)
            for operand in decoded.operands:
                if operand.type != X86_OP_MEM:
                    continue
                for register in (operand.mem.base, operand.mem.index):
                    if register == X86_REG_INVALID:
                        continue
                    if state[0][
                        _REGISTER_FAMILIES.index(
                            self._register_family(register)
                        )
                    ]:
                        return False
            if decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                destination, source = decoded.operands
                if (
                    destination.type == X86_OP_MEM
                    and self._relative_operand_offsets(
                        address,
                        source,
                        function_entry,
                        argument_index,
                        states,
                    )
                ):
                    return False
            if decoded.group(CS_GRP_CALL):
                target = self.direct_call_targets_by_source.get(address)
                if state[0][_REGISTER_FAMILIES.index("ecx")] and (
                    target is None
                    or self._function_reads_incoming_register(target, "ecx")
                ):
                    return False
                for callee_argument in range(8):
                    pushed = self._pushed_call_argument(
                        address, callee_argument
                    )
                    if pushed is None:
                        break
                    if not self._relative_operand_offsets(
                        pushed[0].address,
                        pushed[1],
                        function_entry,
                        argument_index,
                        states,
                    ):
                        continue
                    if target is None or not (
                        self._function_argument_is_not_used_as_pointer(
                            target, callee_argument, next_active
                        )
                    ):
                        return False
            if decoded.group(CS_GRP_RET):
                saw_return = True
                if state[0][_REGISTER_FAMILIES.index("eax")]:
                    return False
            if (
                decoded.group(CS_GRP_JUMP)
                and not self.non_call_successors.get(address)
                and any(state[0])
            ):
                return False
        return saw_return

    def _call_return_is_not_used_as_pointer(
        self,
        call_address: int,
        function_entry: int,
        active: frozenset[tuple[int, int]] = frozenset(),
    ) -> bool:
        key = (call_address, function_entry)
        if key in active:
            return False
        cache_key = (
            *key,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.dead_call_return_cache:
            return self.dead_call_return_cache[cache_key]
        self.dead_call_return_cache[cache_key] = False
        states = self._relative_pointer_states(
            function_entry,
            root_call=call_address,
            propagate_call_returns=False,
            allow_partial_taint=True,
        )
        if states is None:
            return False
        next_active = active | {key}
        saw_root = False
        for address in self._function_instruction_addresses(function_entry):
            state = states.get(address)
            if state is None or not state[1] & 2:
                continue
            saw_root = True
            decoded = self._owned_decoded(address)
            for operand in decoded.operands:
                if operand.type == X86_OP_MEM:
                    for register in (operand.mem.base, operand.mem.index):
                        if register == X86_REG_INVALID:
                            continue
                        if state[0][
                            _REGISTER_FAMILIES.index(
                                self._register_family(register)
                            )
                        ]:
                            return False
            if decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                destination, source = decoded.operands
                if destination.type == X86_OP_MEM and (
                    self._relative_operand_offsets(
                        address,
                        source,
                        function_entry,
                        None,
                        states,
                    )
                ):
                    return False
            if decoded.group(CS_GRP_CALL):
                target = self.direct_call_targets_by_source.get(address)
                if state[0][_REGISTER_FAMILIES.index("ecx")] and (
                    target is None
                    or self._function_reads_incoming_register(target, "ecx")
                ):
                    return False
                for argument_index in range(8):
                    pushed = self._pushed_call_argument(
                        address, argument_index
                    )
                    if pushed is None:
                        break
                    if not self._relative_operand_offsets(
                        pushed[0].address,
                        pushed[1],
                        function_entry,
                        None,
                        states,
                    ):
                        continue
                    if target is None or not (
                        self._function_argument_is_not_used_as_pointer(
                            target, argument_index
                        )
                    ):
                        return False
            if decoded.group(CS_GRP_RET) and any(state[0]):
                if not self._direct_call_domain_is_closed(function_entry):
                    return False
                callers = self.direct_call_sources_by_target.get(
                    function_entry, set()
                )
                if not callers:
                    return False
                for caller in callers:
                    caller_entry = self._registrar_function_entry(caller)
                    if caller_entry is None or not (
                        self._call_return_is_not_used_as_pointer(
                            caller, caller_entry, next_active
                        )
                    ):
                        return False
        self.dead_call_return_cache[cache_key] = saw_root
        return saw_root

    def _function_reads_incoming_register(
        self, function_entry: int, register_family: str
    ) -> bool:
        cache_key = (
            function_entry,
            register_family,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.incoming_register_read_cache:
            return self.incoming_register_read_cache[cache_key]
        self.incoming_register_read_cache[cache_key] = True
        if function_entry not in self.function_addresses:
            return True
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        states = {function_entry: True}
        pending = [function_entry]
        queued = {function_entry}
        iterations = 0
        while pending:
            address = heapq.heappop(pending)
            queued.remove(address)
            live = states[address]
            decoded = self._owned_decoded(address)
            if live:
                reads = any(
                    self._register_family(register) == register_family
                    for register in decoded.regs_read
                ) or any(
                    row.type == X86_OP_REG
                    and row.access & CS_AC_READ
                    and self._register_family(row.reg) == register_family
                    for row in decoded.operands
                ) or any(
                    row.type == X86_OP_MEM
                    and any(
                        register != X86_REG_INVALID
                        and self._register_family(register)
                        == register_family
                        for register in (row.mem.base, row.mem.index)
                    )
                    for row in decoded.operands
                )
                if reads:
                    return True
            writes = [
                row
                for row in decoded.operands
                if row.type == X86_OP_REG
                and row.access & CS_AC_WRITE
                and self._register_family(row.reg) == register_family
            ]
            killed = decoded.group(CS_GRP_CALL) and register_family in {
                "eax",
                "ecx",
                "edx",
            } or any(row.size == 4 for row in writes)
            output = live and not killed
            for successor in self._summary_successors(
                address, function_entry, following_entry
            ):
                prior = states.get(successor, False)
                joined = prior or output
                if successor in states and joined == prior:
                    continue
                states[successor] = joined
                if successor not in queued:
                    heapq.heappush(pending, successor)
                    queued.add(successor)
            iterations += 1
            self.limits.check("max_summary_iterations", iterations)
        self.incoming_register_read_cache[cache_key] = False
        return False

    def _forward_bounded_string_writer_size_argument(
        self, function_entry: int, argument_index: int
    ) -> int | None:
        rows = [
            self._owned_decoded(address)
            for address in self._function_instruction_addresses(
                function_entry
            )
        ]
        if (
            not rows
            or any(row.group(CS_GRP_CALL) for row in rows)
            or any(row.mnemonic == "std" for row in rows)
            or sum(row.mnemonic == "stosb" for row in rows) != 1
            or sum(row.mnemonic == "rep stosb" for row in rows) != 1
            or not any(row.group(CS_GRP_RET) for row in rows)
        ):
            return None
        pointer_loads = [
            row
            for row in rows
            if row.id == X86_INS_MOV
            and len(row.operands) == 2
            and row.operands[0].type == X86_OP_REG
            and self._register_family(row.operands[0].reg) == "edx"
            and self._stack_argument_index_at(
                row.address, row.operands[1], function_entry
            )
            == argument_index
        ]
        pointer_copies = [
            row
            for row in rows
            if row.id == X86_INS_MOV
            and len(row.operands) == 2
            and all(value.type == X86_OP_REG for value in row.operands)
            and self._register_family(row.operands[0].reg) == "edi"
            and self._register_family(row.operands[1].reg) == "edx"
        ]
        bound_adds = [
            row
            for row in rows
            if row.mnemonic == "add"
            and len(row.operands) == 2
            and all(value.type == X86_OP_REG for value in row.operands)
            and self._register_family(row.operands[0].reg) == "ecx"
            and self._register_family(row.operands[1].reg) == "edi"
        ]
        bound_loads = [
            (
                row,
                self._stack_argument_index_at(
                    row.address, row.operands[1], function_entry
                ),
            )
            for row in rows
            if row.id == X86_INS_MOV
            and len(row.operands) == 2
            and row.operands[0].type == X86_OP_REG
            and self._register_family(row.operands[0].reg) == "ecx"
            and self._stack_argument_index_at(
                row.address, row.operands[1], function_entry
            )
            is not None
        ]
        bound_compares = [
            row
            for row in rows
            if row.mnemonic == "cmp"
            and len(row.operands) == 2
            and all(value.type == X86_OP_REG for value in row.operands)
            and self._register_family(row.operands[0].reg) == "edi"
            and self._register_family(row.operands[1].reg) == "ecx"
        ]
        remaining_counts = [
            row
            for row in rows
            if row.mnemonic == "sub"
            and len(row.operands) == 2
            and all(value.type == X86_OP_REG for value in row.operands)
            and self._register_family(row.operands[0].reg) == "ecx"
            and self._register_family(row.operands[1].reg) == "edi"
        ]
        if not all(
            len(values) == 1
            for values in (
                pointer_loads,
                pointer_copies,
                bound_loads,
                bound_adds,
                bound_compares,
                remaining_counts,
            )
        ):
            return None
        bound_load, size_argument = bound_loads[0]
        if size_argument == argument_index:
            return None
        compare = bound_compares[0]
        unsigned_backedges = [
            row
            for row in rows
            if row.mnemonic == "jb"
            and self._direct_target(row) is not None
            and self._direct_target(row) < row.address
            and compare.address < row.address
        ]
        if len(unsigned_backedges) != 1:
            return None
        for row in rows:
            for operand in row.operands:
                if operand.type != X86_OP_MEM or not operand.access & CS_AC_WRITE:
                    continue
                if (
                    row.mnemonic not in {"stosb", "rep stosb"}
                    or operand.mem.base != x86_const.X86_REG_EDI
                ):
                    return None
        if not (
            pointer_loads[0].address < pointer_copies[0].address
            < bound_adds[0].address
            and bound_load.address < bound_adds[0].address
            < unsigned_backedges[0].address
            < remaining_counts[0].address
        ):
            return None
        return size_argument

    def _is_forward_bounded_string_writer(
        self, function_entry: int, argument_index: int
    ) -> bool:
        return (
            self._forward_bounded_string_writer_size_argument(
                function_entry, argument_index
            )
            is not None
        )

    def _direct_call_argument_preserves_field(
        self,
        call_address: int,
        function_entry: int,
        argument_index: int,
        field: int,
    ) -> bool:
        size_argument = self._forward_bounded_string_writer_size_argument(
            function_entry, argument_index
        )
        if size_argument is None:
            return False
        pushed = self._pushed_call_argument(call_address, size_argument)
        if pushed is None or pushed[1].type != X86_OP_IMM:
            return False
        byte_count = pushed[1].imm & 0xFFFF_FFFF
        return field + 4 <= 0 or field >= byte_count

    def _function_argument_preserves_field(
        self,
        function_entry: int,
        argument_index: int,
        field: int,
        active: frozenset[tuple[int, int, int]] = frozenset(),
    ) -> bool:
        key = (function_entry, argument_index, field)
        if key in active:
            return False
        cache_key = (
            *key,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.field_preservation_cache:
            return self.field_preservation_cache[cache_key]
        self.field_preservation_cache[cache_key] = False
        states = self._relative_pointer_states(
            function_entry,
            argument_index=argument_index,
            propagate_call_returns=False,
            allow_partial_taint=True,
            collapse_nonnegative_offsets=field + 4 <= 0,
        )
        if states is None:
            result = field + 4 <= 0 and (
                self._is_forward_bounded_string_writer(
                    function_entry, argument_index
                )
                or (
                    argument_index in {0, 1}
                    and (
                        self._memcpy_like_function(function_entry)
                        or self._overlap_safe_copy_function(function_entry)
                    )
                )
            )
            self.field_preservation_cache[cache_key] = result
            return result
        next_active = active | {key}
        saw_return = False
        for address in self._function_instruction_addresses(function_entry):
            state = states.get(address)
            if state is None:
                continue
            decoded = self._owned_decoded(address)
            for operand in decoded.operands:
                if (
                    operand.type != X86_OP_MEM
                    or not operand.access & CS_AC_WRITE
                    or operand.mem.base == X86_REG_INVALID
                ):
                    continue
                base_values = state[0][
                    _REGISTER_FAMILIES.index(
                        self._register_family(operand.mem.base)
                    )
                ]
                if not base_values:
                    continue
                if operand.mem.index != X86_REG_INVALID or operand.size <= 0:
                    return False
                if decoded.mnemonic == "rep stosb" and any(
                    field + 4 > value for value in base_values
                ):
                    return False
                if any(
                    value + operand.mem.disp < field + 4
                    and field < value + operand.mem.disp + operand.size
                    for value in base_values
                ):
                    return False
            if decoded.group(CS_GRP_CALL):
                ecx_values = state[0][_REGISTER_FAMILIES.index("ecx")]
                target = self.direct_call_targets_by_source.get(address)
                if ecx_values and (
                    target is None
                    or self._function_reads_incoming_register(target, "ecx")
                ):
                    return False
                passed_pointer = False
                return_may_alias = False
                for callee_argument in range(8):
                    pushed = self._pushed_call_argument(
                        address, callee_argument
                    )
                    if pushed is None:
                        break
                    values = self._relative_operand_offsets(
                        pushed[0].address,
                        pushed[1],
                        function_entry,
                        argument_index,
                        states,
                    )
                    passed_pointer |= bool(values)
                    if values and target is not None:
                        return_offsets = self._function_argument_return_offsets(
                            target, callee_argument
                        )
                        return_may_alias |= (
                            return_offsets is None or bool(return_offsets)
                        )
                    for value in values:
                        preserved = (
                            self._external_call_argument_preserves_field(
                                decoded,
                                address,
                                callee_argument,
                                field - value,
                            )
                            if target is None
                            else (
                                self._direct_call_argument_preserves_field(
                                    address,
                                    target,
                                    callee_argument,
                                    field - value,
                                )
                                or self._function_argument_preserves_field(
                                    target,
                                    callee_argument,
                                    field - value,
                                    next_active,
                                )
                            )
                        )
                        if not preserved:
                            return False
                if (
                    passed_pointer
                    and return_may_alias
                    and not self._call_return_is_not_used_as_pointer(
                        address, function_entry
                    )
                ):
                    return False
            if decoded.group(CS_GRP_RET):
                saw_return = True
            if (
                decoded.group(CS_GRP_JUMP)
                and not self.non_call_successors.get(address)
                and any(state[0])
            ):
                return False
        self.field_preservation_cache[cache_key] = saw_return
        return saw_return

    def _function_argument_does_not_read_field(
        self,
        function_entry: int,
        argument_index: int,
        field: int,
        active: frozenset[tuple[int, int, int]] = frozenset(),
    ) -> bool:
        key = (function_entry, argument_index, field)
        if key in active:
            return False
        cache_key = (
            *key,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.field_read_avoidance_cache:
            return self.field_read_avoidance_cache[cache_key]
        self.field_read_avoidance_cache[cache_key] = False
        states = self._relative_pointer_states(
            function_entry,
            argument_index=argument_index,
            propagate_call_returns=False,
            allow_partial_taint=True,
            collapse_nonnegative_offsets=field + 4 <= 0,
        )
        if states is None:
            result = (
                field + 4 <= 0
                and argument_index in {0, 1}
                and (
                    self._memcpy_like_function(function_entry)
                    or self._overlap_safe_copy_function(function_entry)
                )
            )
            self.field_read_avoidance_cache[cache_key] = result
            return result
        next_active = active | {key}
        saw_return = False
        for address in self._function_instruction_addresses(function_entry):
            state = states.get(address)
            if state is None:
                continue
            decoded = self._owned_decoded(address)
            for operand in decoded.operands:
                if (
                    operand.type != X86_OP_MEM
                    or not operand.access & CS_AC_READ
                    or operand.mem.base == X86_REG_INVALID
                ):
                    continue
                base_values = state[0][
                    _REGISTER_FAMILIES.index(
                        self._register_family(operand.mem.base)
                    )
                ]
                if not base_values:
                    continue
                if operand.mem.index != X86_REG_INVALID or operand.size <= 0:
                    return False
                if decoded.mnemonic.startswith("rep") and any(
                    field + 4 > value for value in base_values
                ):
                    return False
                if any(
                    value + operand.mem.disp < field + 4
                    and field < value + operand.mem.disp + operand.size
                    for value in base_values
                ):
                    return False
            if decoded.group(CS_GRP_CALL):
                ecx_values = state[0][_REGISTER_FAMILIES.index("ecx")]
                target = self.direct_call_targets_by_source.get(address)
                if ecx_values and (
                    target is None
                    or self._function_reads_incoming_register(target, "ecx")
                ):
                    return False
                passed_pointer = False
                return_may_alias = False
                for callee_argument in range(8):
                    pushed = self._pushed_call_argument(
                        address, callee_argument
                    )
                    if pushed is None:
                        break
                    values = self._relative_operand_offsets(
                        pushed[0].address,
                        pushed[1],
                        function_entry,
                        argument_index,
                        states,
                    )
                    passed_pointer |= bool(values)
                    if values and target is not None:
                        return_offsets = self._function_argument_return_offsets(
                            target, callee_argument
                        )
                        return_may_alias |= (
                            return_offsets is None or bool(return_offsets)
                        )
                    for value in values:
                        if target is None or not (
                            self._function_argument_does_not_read_field(
                                target,
                                callee_argument,
                                field - value,
                                next_active,
                            )
                        ):
                            return False
                if (
                    passed_pointer
                    and return_may_alias
                    and not self._call_return_is_not_used_as_pointer(
                        address, function_entry
                    )
                ):
                    return False
            if decoded.group(CS_GRP_RET):
                saw_return = True
            if (
                decoded.group(CS_GRP_JUMP)
                and not self.non_call_successors.get(address)
                and any(state[0])
            ):
                return False
        self.field_read_avoidance_cache[cache_key] = saw_return
        return saw_return

    def _pointer_definition_preserves_back_reference_until(
        self,
        function_entry: int,
        root_definition: int,
        pointer_field: int,
        end_address: int,
    ) -> bool:
        states = self._relative_pointer_states(
            function_entry,
            root_definition=root_definition,
            propagate_call_returns=False,
            allow_partial_taint=True,
            collapse_nonnegative_offsets=pointer_field + 4 <= 0,
        )
        end_state = None if states is None else states.get(end_address)
        if end_state is None or end_state[1] != 2:
            return False
        for address in self._function_instruction_addresses(function_entry):
            if not root_definition < address < end_address:
                continue
            state = states.get(address)
            if state is None:
                continue
            if state[1] != 2:
                if any(state[0]):
                    return False
                continue
            decoded = self._owned_decoded(address)
            for operand in decoded.operands:
                if (
                    operand.type != X86_OP_MEM
                    or not operand.access & (CS_AC_READ | CS_AC_WRITE)
                    or operand.mem.base == X86_REG_INVALID
                ):
                    continue
                base_values = state[0][
                    _REGISTER_FAMILIES.index(
                        self._register_family(operand.mem.base)
                    )
                ]
                if not base_values:
                    continue
                if operand.mem.index != X86_REG_INVALID or operand.size <= 0:
                    return False
                if decoded.mnemonic.startswith("rep") and any(
                    pointer_field + 4 > value for value in base_values
                ):
                    return False
                if any(
                    value + operand.mem.disp < pointer_field + 4
                    and pointer_field
                    < value + operand.mem.disp + operand.size
                    for value in base_values
                ):
                    return False
            if decoded.group(CS_GRP_CALL):
                target = self.direct_call_targets_by_source.get(address)
                ecx_values = state[0][_REGISTER_FAMILIES.index("ecx")]
                if ecx_values and (
                    target is None
                    or self._function_reads_incoming_register(target, "ecx")
                ):
                    return False
                passed_pointer = False
                return_may_alias = False
                for callee_argument in range(8):
                    pushed = self._pushed_call_argument(
                        address, callee_argument
                    )
                    if pushed is None:
                        break
                    values = self._relative_operand_offsets(
                        pushed[0].address,
                        pushed[1],
                        function_entry,
                        None,
                        states,
                    )
                    passed_pointer |= bool(values)
                    if values and target is not None:
                        return_offsets = self._function_argument_return_offsets(
                            target, callee_argument
                        )
                        return_may_alias |= (
                            return_offsets is None or bool(return_offsets)
                        )
                    for value in values:
                        relative_field = pointer_field - value
                        if target is None or not (
                            self._function_argument_preserves_field(
                                target,
                                callee_argument,
                                relative_field,
                            )
                            and self._function_argument_does_not_read_field(
                                target,
                                callee_argument,
                                relative_field,
                            )
                        ):
                            return False
                if (
                    passed_pointer
                    and return_may_alias
                    and not self._call_return_is_not_used_as_pointer(
                        address, function_entry
                    )
                ):
                    return False
        return True

    def _zero_register_states(
        self, function_entry: int
    ) -> dict[int, tuple[int, ...]] | None:
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        # Domain bits: 1=zero, 2=unknown/nonzero.
        initial = tuple(2 for _ in _REGISTER_FAMILIES)
        states = {function_entry: initial}
        pending = [function_entry]
        queued = {function_entry}
        iterations = 0
        while pending:
            current = heapq.heappop(pending)
            queued.remove(current)
            if current not in self.instructions:
                return None
            values = list(states[current])
            decoded = self._owned_decoded(current)
            if decoded.group(CS_GRP_CALL):
                for family in ("eax", "ecx", "edx"):
                    values[_REGISTER_FAMILIES.index(family)] = 2
            elif decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                destination, source = decoded.operands
                if destination.type == X86_OP_REG:
                    index = _REGISTER_FAMILIES.index(
                        self._register_family(destination.reg)
                    )
                    if source.type == X86_OP_REG:
                        value = values[
                            _REGISTER_FAMILIES.index(
                                self._register_family(source.reg)
                            )
                        ]
                    elif source.type == X86_OP_IMM and (
                        source.imm & 0xFFFF_FFFF == 0
                    ):
                        value = 1
                    else:
                        value = 2
                    values[index] = value
            elif (
                decoded.id == X86_INS_XOR
                and len(decoded.operands) == 2
                and all(row.type == X86_OP_REG for row in decoded.operands)
                and self._register_family(decoded.operands[0].reg)
                == self._register_family(decoded.operands[1].reg)
            ):
                values[
                    _REGISTER_FAMILIES.index(
                        self._register_family(decoded.operands[0].reg)
                    )
                ] = 1
            else:
                for register in decoded.regs_write:
                    family = self._register_family(register)
                    if family in _REGISTER_FAMILIES:
                        values[_REGISTER_FAMILIES.index(family)] = 2
                for operand in decoded.operands:
                    if operand.type == X86_OP_REG and operand.access & CS_AC_WRITE:
                        family = self._register_family(operand.reg)
                        if family in _REGISTER_FAMILIES:
                            values[_REGISTER_FAMILIES.index(family)] = 2
            output = tuple(values)
            for successor in self._summary_successors(
                current, function_entry, following_entry
            ):
                prior = states.get(successor)
                joined = (
                    output
                    if prior is None
                    else tuple(
                        prior[index] | output[index]
                        for index in range(len(_REGISTER_FAMILIES))
                    )
                )
                if prior == joined:
                    continue
                states[successor] = joined
                if successor not in queued:
                    heapq.heappush(pending, successor)
                    queued.add(successor)
            iterations += 1
            self.limits.check("max_summary_iterations", iterations)
        return states

    def _zeroing_wrapper_size_argument(
        self, function_entry: int
    ) -> int | None:
        cache_key = (
            function_entry,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.zeroing_wrapper_cache:
            return self.zeroing_wrapper_cache[cache_key]
        self.zeroing_wrapper_cache[cache_key] = None
        addresses = self._function_instruction_addresses(function_entry)
        repeat_stores = [
            address
            for address in addresses
            if self._owned_decoded(address).mnemonic == "rep stosb"
        ]
        calls = [
            address
            for address in addresses
            if self._owned_decoded(address).group(CS_GRP_CALL)
        ]
        returns = [
            address
            for address in addresses
            if self._owned_decoded(address).group(CS_GRP_RET)
        ]
        if len(repeat_stores) != 1 or len(calls) != 1 or not returns:
            return None
        repeat_store = repeat_stores[0]
        allocation_call = calls[0]
        pointer_states = self._relative_pointer_states(
            function_entry, root_call=allocation_call
        )
        zero_states = self._zero_register_states(function_entry)
        if pointer_states is None or zero_states is None:
            return None
        repeat_pointer_state = pointer_states.get(repeat_store)
        repeat_zero_state = zero_states.get(repeat_store)
        if (
            repeat_pointer_state is None
            or repeat_pointer_state[1] != 2
            or repeat_pointer_state[0][
                _REGISTER_FAMILIES.index("edi")
            ]
            != frozenset({0})
            or repeat_zero_state is None
            or repeat_zero_state[_REGISTER_FAMILIES.index("eax")] != 1
        ):
            return None
        for return_address in returns:
            state = pointer_states.get(return_address)
            if (
                state is None
                or state[1] != 2
                or state[0][_REGISTER_FAMILIES.index("eax")]
                != frozenset({0})
            ):
                return None
            fallthrough = allocation_call + self.instructions[
                allocation_call
            ].size
            if self._reachable_within_function(
                fallthrough,
                return_address,
                function_entry,
                max(addresses, default=function_entry) + 16,
                excluded=repeat_store,
            ):
                return None
        candidates = []
        for argument_index in range(4):
            argument_states = self._relative_pointer_states(
                function_entry,
                argument_index=argument_index,
                propagate_call_returns=False,
            )
            if argument_states is None:
                continue
            repeat_argument_state = argument_states.get(repeat_store)
            if (
                repeat_argument_state is None
                or repeat_argument_state[0][
                    _REGISTER_FAMILIES.index("ecx")
                ]
                != frozenset({0})
            ):
                continue
            passed_to_allocator = False
            for callee_argument in range(8):
                pushed = self._pushed_call_argument(
                    allocation_call, callee_argument
                )
                if pushed is None:
                    break
                if self._relative_operand_offsets(
                    pushed[0].address,
                    pushed[1],
                    function_entry,
                    argument_index,
                    argument_states,
                ) == frozenset({0}):
                    passed_to_allocator = True
            if passed_to_allocator:
                candidates.append(argument_index)
        result = candidates[0] if len(candidates) == 1 else None
        self.zeroing_wrapper_cache[cache_key] = result
        return result

    def _zeroed_field_root_returns(
        self, function_entry: int, root_call: int, field: int
    ) -> bool:
        states = self._relative_pointer_states(
            function_entry,
            root_call=root_call,
            propagate_call_returns=False,
        )
        if states is None:
            return False
        saw_return = False
        for address in self._function_instruction_addresses(function_entry):
            state = states.get(address)
            if state is None:
                continue
            decoded = self._owned_decoded(address)
            if state[1] & 2:
                for operand_index, operand in enumerate(decoded.operands):
                    if (
                        operand.type != X86_OP_MEM
                        or not operand.access & CS_AC_WRITE
                        or operand.mem.base == X86_REG_INVALID
                    ):
                        continue
                    base_values = state[0][
                        _REGISTER_FAMILIES.index(
                            self._register_family(operand.mem.base)
                        )
                    ]
                    if not base_values:
                        continue
                    if operand.mem.index != X86_REG_INVALID or operand.size <= 0:
                        return False
                    overlaps = any(
                        value + operand.mem.disp < field + 4
                        and field
                        < value + operand.mem.disp + operand.size
                        for value in base_values
                    )
                    if overlaps and not (
                        decoded.id == X86_INS_MOV
                        and operand_index == 0
                        and len(decoded.operands) == 2
                        and decoded.operands[1].type == X86_OP_IMM
                        and decoded.operands[1].imm & 0xFFFF_FFFF == 0
                    ):
                        return False
            if decoded.group(CS_GRP_CALL) and address != root_call:
                if state[1] != 2:
                    continue
                target = self.direct_call_targets_by_source.get(address)
                if state[0][_REGISTER_FAMILIES.index("ecx")] and (
                    target is None
                    or self._function_reads_incoming_register(target, "ecx")
                ):
                    return False
                passed_pointer = False
                return_may_alias = False
                for callee_argument in range(8):
                    pushed = self._pushed_call_argument(
                        address, callee_argument
                    )
                    if pushed is None:
                        break
                    values = self._relative_operand_offsets(
                        pushed[0].address,
                        pushed[1],
                        function_entry,
                        None,
                        states,
                    )
                    passed_pointer |= bool(values)
                    if values and target is not None:
                        return_offsets = self._function_argument_return_offsets(
                            target, callee_argument
                        )
                        return_may_alias |= (
                            return_offsets is None or bool(return_offsets)
                        )
                    for value in values:
                        preserved = (
                            self._external_call_argument_preserves_field(
                                decoded,
                                address,
                                callee_argument,
                                field - value,
                            )
                            if target is None
                            else (
                                self._direct_call_argument_preserves_field(
                                    address,
                                    target,
                                    callee_argument,
                                    field - value,
                                )
                                or self._function_argument_preserves_field(
                                    target,
                                    callee_argument,
                                    field - value,
                                )
                            )
                        )
                        if not preserved:
                            return False
                if (
                    passed_pointer
                    and return_may_alias
                    and not self._call_return_is_not_used_as_pointer(
                        address, function_entry
                    )
                ):
                    return False
            if decoded.group(CS_GRP_RET):
                saw_return = True
                if (
                    state[1] != 2
                    or state[0][_REGISTER_FAMILIES.index("eax")]
                    != frozenset({0})
                ):
                    return False
        return saw_return

    def _function_returns_zeroed_field(
        self, function_entry: int, field: int
    ) -> bool:
        cache_key = (
            function_entry,
            field,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.zeroed_field_return_cache:
            return self.zeroed_field_return_cache[cache_key]
        self.zeroed_field_return_cache[cache_key] = False
        candidates = []
        for address in self._function_instruction_addresses(function_entry):
            target = self.direct_call_targets_by_source.get(address)
            if target is None:
                continue
            size_argument = self._zeroing_wrapper_size_argument(target)
            if size_argument is None:
                continue
            pushed = self._pushed_call_argument(address, size_argument)
            if (
                pushed is None
                or pushed[1].type != X86_OP_IMM
                or pushed[1].imm & 0xFFFF_FFFF < field + 4
            ):
                continue
            candidates.append(address)
        result = any(
            self._zeroed_field_root_returns(
                function_entry, root_call, field
            )
            for root_call in candidates
        )
        self.zeroed_field_return_cache[cache_key] = result
        return result

    def _runtime_global_pointer_field_is_zero(
        self, slot: int, field: int
    ) -> bool:
        try:
            if int.from_bytes(
                _read_loader_initialized(self.image, slot, 4), "little"
            ) != 0:
                return False
        except ValueError:
            return False
        writes = tuple(
            sorted(
                self.global_slot_writes.get(slot, ()),
                key=lambda row: row.instruction_address,
            )
        )
        if len(writes) != 1:
            return False
        write = writes[0]
        decoded = self._owned_decoded(write.instruction_address)
        writer_entry = self._registrar_function_entry(
            write.instruction_address
        )
        if (
            writer_entry is None
            or decoded.id != X86_INS_MOV
            or len(decoded.operands) != 2
            or decoded.operands[1].type != X86_OP_REG
        ):
            return False
        family = self._register_family(decoded.operands[1].reg)
        definitions = self._register_definitions_across_blocks(
            write.instruction_address, family, writer_entry
        )
        if not definitions:
            return False
        for definition_address in definitions:
            definition = self._owned_decoded(definition_address)
            target = self.direct_call_targets_by_source.get(
                definition_address
            )
            if (
                family != "eax"
                or not definition.group(CS_GRP_CALL)
                or target is None
                or not self._function_returns_zeroed_field(target, field)
            ):
                return False
        return True

    def _global_pointer_field_identity(
        self,
        address: int,
        operand,
        function_entry: int,
    ) -> tuple[int, int] | None:
        """Trace a local ``[global pointer] + constant`` expression.

        The proof is intentionally local and exact.  It accepts only MOV
        copies plus constant ADD/SUB/LEA transforms in one owned basic block;
        calls, joins, partial writes, arguments, and other arithmetic fail
        closed.
        """
        if operand.type != X86_OP_REG:
            return None
        return self._register_global_pointer_field_identity(
            address,
            self._register_family(operand.reg),
            function_entry,
        )

    def _register_global_pointer_field_identity(
        self,
        address: int,
        family: str,
        function_entry: int,
    ) -> tuple[int, int] | None:
        """Trace a register to one exact loaded global pointer plus offset."""
        cache_key = (
            address,
            family,
            function_entry,
            self._summary_fact_signature(),
        )
        if cache_key in self.pointer_identity_cache:
            return self.pointer_identity_cache[cache_key]
        cursor = address
        offset = 0
        for _ in range(64):
            previous = self._previous_instruction(cursor)
            if previous is None or previous.address < function_entry:
                break
            decoded = self._owned_decoded(previous.address)
            if (
                decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and self._register_family(decoded.operands[0].reg) == family
            ):
                source = decoded.operands[1]
                if (
                    source.type == X86_OP_MEM
                    and source.mem.segment == X86_REG_INVALID
                    and source.mem.base == X86_REG_INVALID
                    and source.mem.index == X86_REG_INVALID
                ):
                    result = (
                        source.mem.disp & 0xFFFF_FFFF,
                        offset,
                    )
                    self.pointer_identity_cache[cache_key] = result
                    return result
                if source.type != X86_OP_REG:
                    break
                family = self._register_family(source.reg)
            elif (
                decoded.mnemonic in {"add", "sub"}
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and self._register_family(decoded.operands[0].reg) == family
                and decoded.operands[1].type == X86_OP_IMM
            ):
                delta = decoded.operands[1].imm
                offset += delta if decoded.mnemonic == "add" else -delta
            elif (
                decoded.id == X86_INS_LEA
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and self._register_family(decoded.operands[0].reg) == family
                and decoded.operands[1].type == X86_OP_MEM
                and decoded.operands[1].mem.segment == X86_REG_INVALID
                and decoded.operands[1].mem.base != X86_REG_INVALID
                and decoded.operands[1].mem.index == X86_REG_INVALID
            ):
                family = self._register_family(
                    decoded.operands[1].mem.base
                )
                offset += decoded.operands[1].mem.disp
            elif any(
                self._register_family(register) == family
                for register in decoded.regs_write
            ) or any(
                row.type == X86_OP_REG
                and row.access & CS_AC_WRITE
                and self._register_family(row.reg) == family
                for row in decoded.operands
            ):
                break
            if decoded.group(CS_GRP_CALL) and family in {
                "eax",
                "ecx",
                "edx",
            }:
                break
            cursor = previous.address
            if previous.address in self.block_starts:
                break
        self.pointer_identity_cache[cache_key] = None
        return None

    def _closed_runtime_global_copy_field_origin(
        self,
        slot: int,
        field: int,
        copy_function: int,
        visited: frozenset[tuple[int, int]],
    ) -> bool:
        """Prove one field of a unique runtime global object stays copied."""
        registries = self._closed_copy_registries(copy_function)
        cache_key = (
            slot,
            field,
            copy_function,
            self._summary_fact_signature(),
            self.control_flow_revision,
            registries,
        )
        if cache_key in self.runtime_global_copy_field_cache:
            return self.runtime_global_copy_field_cache[cache_key]
        if cache_key in self.runtime_global_copy_field_active:
            return False
        self.runtime_global_copy_field_active.add(cache_key)
        try:
            if not self._runtime_global_pointer_field_is_zero(slot, field):
                return False
            copy_info = self._copied_descriptor_source_domains(frozenset())
            if copy_info is None or copy_info[0] != copy_function:
                return False
            source_bases = frozenset(
                value for value in copy_info[1][0] if value
            )
            overlapping_writes = []
            for displacement, rows in self.dynamic_field_writes.items():
                for row in rows:
                    if not (
                        displacement < field + 4
                        and field < displacement + row.width
                    ):
                        continue
                    writer_entry = self._registrar_function_entry(
                        row.instruction_address
                    )
                    if writer_entry is None:
                        return False
                    decoded = self._owned_decoded(row.instruction_address)
                    if self._is_stack_backed_memory(
                        row.instruction_address,
                        decoded.operands[0],
                        writer_entry,
                    ):
                        continue
                    overlapping_writes.append(
                        (row, decoded, writer_entry)
                    )
            for row, decoded, writer_entry in overlapping_writes:
                if not (
                    row.width == 4
                    and decoded.id == X86_INS_MOV
                    and len(decoded.operands) == 2
                    and decoded.operands[0].type == X86_OP_MEM
                    and decoded.operands[0].size == 4
                    and decoded.operands[0].mem.segment
                    == X86_REG_INVALID
                    and decoded.operands[0].mem.base
                    != X86_REG_INVALID
                    and decoded.operands[0].mem.index
                    == X86_REG_INVALID
                    and decoded.operands[0].mem.disp == field
                    and self._register_global_pointer_field_identity(
                        row.instruction_address,
                        self._register_family(
                            decoded.operands[0].mem.base
                        ),
                        writer_entry,
                    )
                    == (slot, 0)
                ):
                    return False
                source = decoded.operands[1]
                if (
                    source.type == X86_OP_IMM
                    and source.imm & 0xFFFF_FFFF == 0
                ):
                    continue
                if self._operand_has_copy_constructor_origin(
                    row.instruction_address,
                    source,
                    writer_entry,
                    copy_function,
                    visited,
                ):
                    continue
                finite = self._finite_operand_values_before(
                    row.instruction_address,
                    source,
                    writer_entry,
                    frozenset(),
                )
                if (
                    finite is not None
                    and finite[0]
                    and finite[0] <= source_bases
                ):
                    continue
                return False
        finally:
            self.runtime_global_copy_field_active.remove(cache_key)
        self.runtime_global_copy_field_cache[cache_key] = True
        return True

    def _intrusive_list_return_argument(
        self, function_entry: int
    ) -> int | None:
        """Return the argument whose null-terminated link chain is returned."""
        cache_key = (
            function_entry,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.intrusive_list_return_cache:
            return self.intrusive_list_return_cache[cache_key]
        self.intrusive_list_return_cache[cache_key] = None
        if function_entry not in self.function_addresses:
            return None
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        candidates = []
        # Domain bits: 1=list pointer, 2=node, 4=null, 8=unknown.
        for argument_index in range(4):
            initial = {family: 8 for family in _REGISTER_FAMILIES}
            states = {function_entry: initial}
            pending = [function_entry]
            queued = {function_entry}
            returns = []
            saw_head_load = False
            saw_next_load = False
            iterations = 0
            while pending:
                current = heapq.heappop(pending)
                queued.remove(current)
                decoded = self._owned_decoded(current)
                state = dict(states[current])
                if decoded.group(CS_GRP_RET):
                    returns.append(state.get("eax", 8))
                    continue
                if decoded.group(CS_GRP_CALL):
                    for family in ("eax", "ecx", "edx"):
                        state[family] = 8
                elif (
                    decoded.id == X86_INS_XOR
                    and len(decoded.operands) == 2
                    and all(row.type == X86_OP_REG for row in decoded.operands)
                    and self._register_family(decoded.operands[0].reg)
                    == self._register_family(decoded.operands[1].reg)
                ):
                    state[self._register_family(decoded.operands[0].reg)] = 4
                elif (
                    decoded.id == X86_INS_MOV
                    and len(decoded.operands) == 2
                    and decoded.operands[0].type == X86_OP_REG
                ):
                    destination = self._register_family(
                        decoded.operands[0].reg
                    )
                    source = decoded.operands[1]
                    source_argument = self._stack_argument_index_at(
                        current, source, function_entry
                    )
                    if source_argument is not None:
                        value = 1 if source_argument == argument_index else 8
                    elif source.type == X86_OP_REG:
                        value = state.get(
                            self._register_family(source.reg), 8
                        )
                    elif source.type == X86_OP_IMM and (
                        source.imm & 0xFFFF_FFFF == 0
                    ):
                        value = 4
                    elif (
                        source.type == X86_OP_MEM
                        and source.mem.segment == X86_REG_INVALID
                        and source.mem.base != X86_REG_INVALID
                        and source.mem.index == X86_REG_INVALID
                        and source.mem.disp == 0
                    ):
                        base = state.get(
                            self._register_family(source.mem.base), 8
                        )
                        if base & 8 or not base & 3:
                            value = 8
                        else:
                            value = 6
                            saw_head_load |= bool(base & 1)
                            saw_next_load |= bool(base & 2)
                    else:
                        value = 8
                    state[destination] = value
                else:
                    for register in decoded.regs_write:
                        state[self._register_family(register)] = 8
                    for operand_row in decoded.operands:
                        if (
                            operand_row.type == X86_OP_REG
                            and operand_row.access & CS_AC_WRITE
                        ):
                            state[
                                self._register_family(operand_row.reg)
                            ] = 8
                for successor in self._summary_successors(
                    current, function_entry, following_entry
                ):
                    prior = states.get(successor)
                    joined = (
                        dict(state)
                        if prior is None
                        else {
                            family: prior.get(family, 8)
                            | state.get(family, 8)
                            for family in _REGISTER_FAMILIES
                        }
                    )
                    if prior == joined:
                        continue
                    states[successor] = joined
                    if successor not in queued:
                        heapq.heappush(pending, successor)
                        queued.add(successor)
                iterations += 1
                self.limits.check("max_summary_iterations", iterations)
            if (
                saw_head_load
                and bool(returns)
                and any(row & 2 for row in returns)
                and all(row & ~6 == 0 for row in returns)
            ):
                candidates.append(argument_index)
        result = candidates[0] if len(candidates) == 1 else None
        self.intrusive_list_return_cache[cache_key] = result
        return result

    def _operand_argument_index(
        self, address: int, operand, function_entry: int
    ) -> int | None:
        stack_argument = self._stack_argument_index_at(
            address, operand, function_entry
        )
        if stack_argument is not None:
            return stack_argument
        if operand.type != X86_OP_REG:
            return None
        proof = self._register_argument_proof_across_blocks(
            address,
            self._register_family(operand.reg),
            function_entry,
        )
        return None if proof is None else proof[0]

    def _intrusive_list_insert_arguments(
        self,
        function_entry: int,
        active: frozenset[int] = frozenset(),
    ) -> tuple[int, int] | None:
        """Recognize a closed intrusive-list insertion or exact wrapper."""
        cache_key = (
            function_entry,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if not active and cache_key in self.intrusive_list_insert_cache:
            return self.intrusive_list_insert_cache[cache_key]
        if function_entry in active or function_entry not in self.function_addresses:
            return None
        next_active = active | {function_entry}
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        direct_candidates = []
        # Domain bits: 1=cursor, 2=node argument, 4=existing/null, 8=unknown.
        for list_argument in range(4):
            for node_argument in range(4):
                if list_argument == node_argument:
                    continue
                initial = {family: 8 for family in _REGISTER_FAMILIES}
                states = {function_entry: initial}
                pending = [function_entry]
                queued = {function_entry}
                inserted = False
                invalid = False
                iterations = 0
                while pending and not invalid:
                    current = heapq.heappop(pending)
                    queued.remove(current)
                    decoded = self._owned_decoded(current)
                    state = dict(states[current])
                    if decoded.group(CS_GRP_RET):
                        continue
                    if decoded.group(CS_GRP_CALL):
                        for family in ("eax", "ecx", "edx"):
                            state[family] = 8
                    elif (
                        decoded.id == X86_INS_XOR
                        and len(decoded.operands) == 2
                        and all(
                            row.type == X86_OP_REG for row in decoded.operands
                        )
                        and self._register_family(decoded.operands[0].reg)
                        == self._register_family(decoded.operands[1].reg)
                    ):
                        state[
                            self._register_family(decoded.operands[0].reg)
                        ] = 4
                    elif decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                        destination, source = decoded.operands

                        def value_of(value_operand):
                            argument = self._stack_argument_index_at(
                                current, value_operand, function_entry
                            )
                            if argument is not None:
                                if argument == list_argument:
                                    return 1
                                if argument == node_argument:
                                    return 2
                                return 8
                            if value_operand.type == X86_OP_REG:
                                return state.get(
                                    self._register_family(value_operand.reg), 8
                                )
                            if value_operand.type == X86_OP_IMM and (
                                value_operand.imm & 0xFFFF_FFFF == 0
                            ):
                                return 4
                            if (
                                value_operand.type == X86_OP_MEM
                                and value_operand.mem.segment
                                == X86_REG_INVALID
                                and value_operand.mem.base
                                != X86_REG_INVALID
                                and value_operand.mem.index
                                == X86_REG_INVALID
                                and value_operand.mem.disp == 0
                            ):
                                base = state.get(
                                    self._register_family(
                                        value_operand.mem.base
                                    ),
                                    8,
                                )
                                return 4 if base & 5 and not base & 8 else 8
                            return 8

                        source_value = value_of(source)
                        if destination.type == X86_OP_REG:
                            state[
                                self._register_family(destination.reg)
                            ] = source_value
                        elif (
                            destination.type == X86_OP_MEM
                            and destination.mem.segment == X86_REG_INVALID
                            and destination.mem.base != X86_REG_INVALID
                            and destination.mem.index == X86_REG_INVALID
                        ):
                            base = state.get(
                                self._register_family(destination.mem.base), 8
                            )
                            if destination.mem.disp == 0 and base & 5:
                                if base & 8 or source_value & 8:
                                    invalid = True
                                elif source_value & 2:
                                    inserted = True
                                elif not source_value & 4:
                                    invalid = True
                            elif destination.mem.disp == 0 and base & 2:
                                if source_value & 8 or not source_value & 4:
                                    invalid = True
                    elif (
                        decoded.id == X86_INS_LEA
                        and len(decoded.operands) == 2
                        and decoded.operands[0].type == X86_OP_REG
                        and decoded.operands[1].type == X86_OP_MEM
                        and decoded.operands[1].mem.segment
                        == X86_REG_INVALID
                        and decoded.operands[1].mem.base
                        != X86_REG_INVALID
                        and decoded.operands[1].mem.index
                        == X86_REG_INVALID
                        and decoded.operands[1].mem.disp == 0
                        and self._register_family(decoded.operands[0].reg)
                        == self._register_family(
                            decoded.operands[1].mem.base
                        )
                    ):
                        pass
                    else:
                        for register in decoded.regs_write:
                            state[self._register_family(register)] = 8
                        for operand_row in decoded.operands:
                            if (
                                operand_row.type == X86_OP_REG
                                and operand_row.access & CS_AC_WRITE
                            ):
                                state[
                                    self._register_family(operand_row.reg)
                                ] = 8
                    for successor in self._summary_successors(
                        current, function_entry, following_entry
                    ):
                        prior = states.get(successor)
                        joined = (
                            dict(state)
                            if prior is None
                            else {
                                family: prior.get(family, 8)
                                | state.get(family, 8)
                                for family in _REGISTER_FAMILIES
                            }
                        )
                        if prior == joined:
                            continue
                        states[successor] = joined
                        if successor not in queued:
                            heapq.heappush(pending, successor)
                            queued.add(successor)
                    iterations += 1
                    self.limits.check("max_summary_iterations", iterations)
                if inserted and not invalid:
                    direct_candidates.append((list_argument, node_argument))
        result = (
            direct_candidates[0]
            if len(set(direct_candidates)) == 1
            else None
        )
        if result is None:
            wrapper_candidates = []
            for call_address, target in sorted(
                self.direct_call_targets_by_source.items()
            ):
                if not function_entry <= call_address < following_entry:
                    continue
                nested = self._intrusive_list_insert_arguments(
                    target, next_active
                )
                if nested is None:
                    continue
                mapped = []
                for nested_argument in nested:
                    pushed = self._pushed_call_argument(
                        call_address, nested_argument
                    )
                    if pushed is None:
                        mapped = []
                        break
                    argument = self._operand_argument_index(
                        pushed[0].address,
                        pushed[1],
                        function_entry,
                    )
                    if argument is None:
                        mapped = []
                        break
                    mapped.append(argument)
                if len(mapped) == 2 and mapped[0] != mapped[1]:
                    wrapper_candidates.append(tuple(mapped))
            if len(set(wrapper_candidates)) == 1:
                result = wrapper_candidates[0]
        if not active:
            self.intrusive_list_insert_cache[cache_key] = result
        return result

    def _function_argument_is_read_only(
        self,
        function_entry: int,
        argument_index: int,
        visited: frozenset[tuple[int, int]] = frozenset(),
    ) -> bool:
        key = (function_entry, argument_index)
        if key in visited or function_entry not in self.function_addresses:
            return False
        next_visited = visited | {key}
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        for address in sorted(self.instructions):
            if not function_entry <= address < following_entry:
                continue
            decoded = self._owned_decoded(address)
            if decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                destination, source = decoded.operands
                if (
                    destination.type == X86_OP_MEM
                    and destination.mem.base != X86_REG_INVALID
                    and self._register_argument_index_across_blocks(
                        address,
                        self._register_family(destination.mem.base),
                        function_entry,
                    )
                    == argument_index
                ):
                    return False
                if source.type == X86_OP_REG and destination.type == X86_OP_MEM:
                    proof = self._register_argument_index_across_blocks(
                        address,
                        self._register_family(source.reg),
                        function_entry,
                    )
                    if proof == argument_index:
                        return False
            if not decoded.group(CS_GRP_CALL):
                continue
            target = self.direct_call_targets_by_source.get(address)
            for callee_argument in range(8):
                pushed = self._pushed_call_argument(address, callee_argument)
                if pushed is None:
                    break
                if (
                    self._operand_argument_index(
                        pushed[0].address,
                        pushed[1],
                        function_entry,
                    )
                    != argument_index
                ):
                    continue
                if target is None or not self._function_argument_is_read_only(
                    target, callee_argument, next_visited
                ):
                    return False
        return True

    def _closed_global_intrusive_list_field_origin(
        self,
        slot: int,
        list_field: int,
        object_field: int,
        copy_function: int,
        visited: frozenset[tuple[int, int]],
    ) -> bool:
        cache_key = (
            slot,
            list_field,
            object_field,
            copy_function,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.global_list_field_cache:
            return self.global_list_field_cache[cache_key]
        if cache_key in self.global_list_field_active:
            return False
        self.global_list_field_active.add(cache_key)
        try:
            result = self._compute_closed_global_intrusive_list_field_origin(
                slot,
                list_field,
                object_field,
                copy_function,
                visited,
            )
        finally:
            self.global_list_field_active.remove(cache_key)
        if result:
            self.global_list_field_cache[cache_key] = True
        return result

    def _compute_closed_global_intrusive_list_field_origin(
        self,
        slot: int,
        list_field: int,
        object_field: int,
        copy_function: int,
        visited: frozenset[tuple[int, int]],
    ) -> bool:
        try:
            initial_pointer = int.from_bytes(
                _read_loader_initialized(self.image, slot, 4), "little"
            )
        except ValueError:
            return False
        initially_zero = False
        if initial_pointer:
            field_address = (initial_pointer + list_field) & 0xFFFF_FFFF
            try:
                initially_zero = (
                    int.from_bytes(
                        _read_loader_initialized(self.image, field_address, 4),
                        "little",
                    )
                    == 0
                    and any(
                        row.type == 3 and row.va == slot
                        for row in self.image.relocations
                    )
                )
            except ValueError:
                initially_zero = False
        elif self._runtime_global_pointer_field_is_zero(slot, list_field):
            initially_zero = True
        if not initially_zero:
            return False
        target_identity = (slot, list_field)
        saw_accessor = False
        saw_insert = False
        for call in sorted(self.direct_calls, key=lambda row: row.address):
            caller_entry = self._registrar_function_entry(call.address)
            if caller_entry is None:
                return False
            matched_arguments = []
            for argument_index in range(8):
                pushed = self._pushed_call_argument(
                    call.address, argument_index
                )
                if pushed is None:
                    break
                if (
                    self._global_pointer_field_identity(
                        pushed[0].address,
                        pushed[1],
                        caller_entry,
                    )
                    == target_identity
                ):
                    matched_arguments.append(argument_index)
            if not matched_arguments:
                continue
            accessor_argument = self._intrusive_list_return_argument(
                call.target
            )
            insert_arguments = self._intrusive_list_insert_arguments(
                call.target
            )
            for argument_index in matched_arguments:
                if accessor_argument == argument_index:
                    saw_accessor = True
                    continue
                if (
                    insert_arguments is not None
                    and insert_arguments[0] == argument_index
                ):
                    pushed = self._pushed_call_argument(
                        call.address, insert_arguments[1]
                    )
                    if pushed is None or not (
                        self._pointer_field_has_copy_constructor_origin(
                            pushed[0].address,
                            pushed[1],
                            object_field,
                            caller_entry,
                            copy_function,
                            visited,
                        )
                    ):
                        return False
                    saw_insert = True
                    continue
                if self._function_argument_is_read_only(
                    call.target, argument_index
                ):
                    continue
                return False
        return saw_accessor and saw_insert

    def _call_returns_object_with_copy_field(
        self,
        call_address: int,
        call_target: int,
        field: int,
        caller_entry: int,
        copy_function: int,
        visited: frozenset[tuple[int, int]],
    ) -> bool:
        list_argument = self._intrusive_list_return_argument(call_target)
        if list_argument is None:
            return False
        pushed = self._pushed_call_argument(call_address, list_argument)
        if pushed is None:
            return False
        identity = self._global_pointer_field_identity(
            pushed[0].address, pushed[1], caller_entry
        )
        return identity is not None and (
            self._closed_global_intrusive_list_field_origin(
                identity[0],
                identity[1],
                field,
                copy_function,
                visited,
            )
        )

    def _object_field_has_copy_constructor_origin(
        self,
        address: int,
        base_family: str,
        field: int,
        function_entry: int,
        copy_function: int,
        visited: frozenset[tuple[int, int]],
    ) -> bool:
        """Prove one object field contains only a fresh copied descriptor.

        This is deliberately object-correlated: it first looks for a closed
        dominating write through the same base value, then follows that base
        through arguments or exact MOV definitions.  It never unions every
        object that happens to use the same displacement.
        """
        key = (address, 0x2_0000_0000 + (field & 0xFFFF_FFFF))
        if key in visited:
            return False
        next_visited = visited | {key}
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        writes: list[tuple[int, bool]] = []
        for write in sorted(
            self.dynamic_field_writes.get(field, ()),
            key=lambda row: row.instruction_address,
        ):
            write_address = write.instruction_address
            if not function_entry <= write_address < following_entry:
                continue
            decoded = self._owned_decoded(write_address)
            if not (
                decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_MEM
                and decoded.operands[0].size == 4
                and decoded.operands[0].mem.segment == X86_REG_INVALID
                and decoded.operands[0].mem.index == X86_REG_INVALID
                and decoded.operands[0].mem.base != X86_REG_INVALID
                and self._register_family(decoded.operands[0].mem.base)
                == base_family
                and self._reachable_within_function(
                    function_entry,
                    write_address,
                    function_entry,
                    following_entry,
                )
                and self._reachable_within_function(
                    write_address,
                    address,
                    function_entry,
                    following_entry,
                )
            ):
                continue
            source = decoded.operands[1]
            is_null = (
                source.type == X86_OP_IMM
                and source.imm & 0xFFFF_FFFF == 0
            )
            has_origin = not is_null and (
                self._operand_has_copy_constructor_origin(
                    write_address,
                    source,
                    function_entry,
                    copy_function,
                    next_visited,
                )
            )
            if not is_null and not has_origin:
                return False
            writes.append((write_address, has_origin))

        safe_write_addresses = frozenset(row[0] for row in writes)
        if safe_write_addresses and not self._reachable_within_function(
            function_entry,
            address,
            function_entry,
            following_entry,
            excluded=safe_write_addresses,
        ):
            # A callee can invalidate the local field fact only when the same
            # base pointer is passed to it.  Reject that escape; unrelated
            # calls cannot name this non-global object value.
            for call in sorted(self.direct_calls, key=lambda row: row.address):
                if not function_entry <= call.address < address:
                    continue
                if not (
                    any(
                        self._reachable_within_function(
                            write_address,
                            call.address,
                            function_entry,
                            following_entry,
                        )
                        for write_address in safe_write_addresses
                    )
                    and self._reachable_within_function(
                        call.address,
                        address,
                        function_entry,
                        following_entry,
                    )
                ):
                    continue
                for argument_index in range(8):
                    pushed = self._pushed_call_argument(
                        call.address, argument_index
                    )
                    if pushed is None:
                        break
                    pushed_operand = pushed[1]
                    if (
                        pushed_operand.type == X86_OP_REG
                        and self._register_family(pushed_operand.reg)
                        == base_family
                    ):
                        return False
            return True

        argument_index = self._register_argument_index_across_blocks(
            address, base_family, function_entry
        )
        if argument_index is not None:
            callers = self._direct_calls_to(function_entry)
            if not callers:
                return False
            for call in callers:
                pushed = self._pushed_call_argument(
                    call.address, argument_index
                )
                if pushed is None or not (
                    self._pointer_field_has_copy_constructor_origin(
                        pushed[0].address,
                        pushed[1],
                        field,
                        pushed[2],
                        copy_function,
                        next_visited,
                    )
                ):
                    return False
            return True

        definitions = self._register_definitions_across_blocks(
            address, base_family, function_entry
        )
        if not definitions:
            return False
        for definition_address in sorted(definitions):
            definition = self._owned_decoded(definition_address)
            if definition.group(CS_GRP_CALL) and base_family == "eax":
                target = self.direct_call_targets_by_source.get(
                    definition_address
                )
                if target is None or not (
                    self._call_returns_object_with_copy_field(
                        definition_address,
                        target,
                        field,
                        function_entry,
                        copy_function,
                        next_visited,
                    )
                ):
                    return False
                continue
            if (
                definition.id != X86_INS_MOV
                or len(definition.operands) != 2
                or definition.operands[0].type != X86_OP_REG
                or not self._pointer_field_has_copy_constructor_origin(
                    definition_address,
                    definition.operands[1],
                    field,
                    function_entry,
                    copy_function,
                    next_visited,
                )
            ):
                return False
        return True

    def _closed_registry_cursor_domain(
        self,
        registrar: int,
        store_address: int,
        cursor_family: str,
        *,
        continue_after_observation: bool = False,
    ) -> tuple[int, int] | None:
        """Prove a cursor ranges only over a head slot and node link slots."""
        cache_key = (
            registrar,
            store_address,
            cursor_family,
            continue_after_observation,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.registry_cursor_domain_cache:
            return self.registry_cursor_domain_cache[cache_key]
        following_entry = min(
            (row for row in self.function_addresses if row > registrar),
            default=0x1_0000_0000,
        )
        observation_region: frozenset[int] | None = None
        if continue_after_observation:
            predecessors: dict[int, set[int]] = {}
            for candidate in self._function_instruction_addresses(registrar):
                for successor in self._summary_successors(
                    candidate, registrar, following_entry
                ):
                    if registrar <= successor < following_entry:
                        predecessors.setdefault(successor, set()).add(candidate)
            reverse_pending = [store_address]
            reverse_reachable = {store_address}
            while reverse_pending:
                current = reverse_pending.pop()
                for predecessor in predecessors.get(current, ()):
                    if predecessor in reverse_reachable:
                        continue
                    reverse_reachable.add(predecessor)
                    reverse_pending.append(predecessor)
            if registrar not in reverse_reachable:
                self.registry_cursor_domain_cache[cache_key] = None
                return None
            observation_region = frozenset(reverse_reachable)
        # Domain bits: 1=head slot, 2=node link slot, 4=unknown, 8=node.
        states = {registrar: 4}
        pending = [registrar]
        queued = {registrar}
        heads = set()
        links = set()
        store_domains = []
        saw_cursor_load = False
        iterations = 0
        while pending:
            address = heapq.heappop(pending)
            queued.remove(address)
            decoded = self._owned_decoded(address)
            state = states[address]
            if address == store_address:
                store_domains.append(state)
                # This proof is scoped to the insertion cursor at its write.
                # Later reuse of the same callee-saved register is irrelevant.
                if not continue_after_observation:
                    continue
            writes_cursor = any(
                self._register_family(row) == cursor_family
                for row in decoded.regs_write
            ) or any(
                row.type == X86_OP_REG
                and row.access & CS_AC_WRITE
                and self._register_family(row.reg) == cursor_family
                for row in decoded.operands
            )
            if writes_cursor:
                destination = (
                    decoded.operands[0]
                    if decoded.operands
                    else None
                )
                source = (
                    decoded.operands[1]
                    if len(decoded.operands) == 2
                    else None
                )
                if (
                    decoded.id == X86_INS_MOV
                    and destination is not None
                    and destination.type == X86_OP_REG
                    and self._register_family(destination.reg)
                    == cursor_family
                    and source is not None
                    and source.type == X86_OP_IMM
                ):
                    heads.add(source.imm & 0xFFFF_FFFF)
                    state = 1
                elif (
                    decoded.id == X86_INS_MOV
                    and destination is not None
                    and destination.type == X86_OP_REG
                    and self._register_family(destination.reg)
                    == cursor_family
                    and source is not None
                    and source.type == X86_OP_MEM
                    and source.mem.segment == X86_REG_INVALID
                    and source.mem.index == X86_REG_INVALID
                    and source.mem.base != X86_REG_INVALID
                    and self._register_family(source.mem.base)
                    == cursor_family
                    and source.mem.disp == 0
                    and not state & 4
                    and state & ~(1 | 2) == 0
                ):
                    saw_cursor_load = True
                    state = 8
                elif (
                    decoded.mnemonic == "add"
                    and destination is not None
                    and destination.type == X86_OP_REG
                    and self._register_family(destination.reg)
                    == cursor_family
                    and source is not None
                    and source.type == X86_OP_IMM
                    and source.imm > 0
                    and state == 8
                ):
                    links.add(source.imm)
                    state = 2
                elif decoded.mnemonic == "pop" and address > store_address:
                    state = 4
                else:
                    state = 4
            for successor in self._summary_successors(
                address, registrar, following_entry
            ):
                if (
                    observation_region is not None
                    and successor not in observation_region
                ):
                    continue
                prior = states.get(successor)
                joined = state if prior is None else prior | state
                if prior == joined:
                    continue
                states[successor] = joined
                if successor not in queued:
                    heapq.heappush(pending, successor)
                    queued.add(successor)
            iterations += 1
            self.limits.check("max_summary_iterations", iterations)
        if (
            len(heads) != 1
            or len(links) != 1
            or not saw_cursor_load
            or not store_domains
            or any(row & 4 or not row & (1 | 2) for row in store_domains)
        ):
            self.registry_cursor_domain_cache[cache_key] = None
            return None
        result = next(iter(heads)), next(iter(links))
        self.registry_cursor_domain_cache[cache_key] = result
        return result

    def _is_closed_registered_cursor_load(
        self,
        function_entry: int,
        address: int,
        memory,
        registries: tuple[tuple[int, int, int], ...],
    ) -> bool:
        if not (
            registries
            and memory.segment == X86_REG_INVALID
            and memory.base != X86_REG_INVALID
            and memory.index == X86_REG_INVALID
            and memory.disp == 0
        ):
            return False
        domain = self._closed_registry_cursor_domain(
            function_entry,
            address,
            self._register_family(memory.base),
            continue_after_observation=True,
        )
        return domain is not None and domain in {
            (head, link) for head, link, _registrar in registries
        }

    def _closed_copy_registries(
        self, copy_function: int
    ) -> tuple[tuple[int, int, int], ...]:
        """Return closed ``(head slot, link field, registrar)`` domains."""
        signature = self._summary_fact_signature()
        cache_key = (copy_function, signature)
        if cache_key in self.copy_registry_cache:
            return self.copy_registry_cache[cache_key]
        # Break the constructor-origin/registry discovery recursion while the
        # registry itself is being proved.  A caller can still prove the
        # direct copy-function return without registry facts.
        self.copy_registry_cache[cache_key] = ()
        candidates = []
        for write in sorted(
            self.dynamic_field_writes.get(0, ()),
            key=lambda row: row.instruction_address,
        ):
            address = write.instruction_address
            registrar = self._registrar_function_entry(address)
            if registrar is None:
                continue
            decoded = self._owned_decoded(address)
            if not (
                decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_MEM
                and decoded.operands[0].size == 4
                and decoded.operands[0].mem.segment == X86_REG_INVALID
                and decoded.operands[0].mem.index == X86_REG_INVALID
                and decoded.operands[0].mem.base != X86_REG_INVALID
                and decoded.operands[1].type == X86_OP_REG
                and self._register_argument_index_across_blocks(
                    address,
                    self._register_family(decoded.operands[1].reg),
                    registrar,
                )
                == 0
                and self._direct_call_domain_is_closed(registrar)
            ):
                continue
            cursor_family = self._register_family(
                decoded.operands[0].mem.base
            )
            cursor_domain = self._closed_registry_cursor_domain(
                registrar, address, cursor_family
            )
            if cursor_domain is None:
                continue
            head, link = cursor_domain
            try:
                initial = int.from_bytes(
                    _read_loader_initialized(self.image, head, 4), "little"
                )
            except ValueError:
                continue
            if initial != 0:
                continue
            absolute_writers = self.global_slot_writes.get(head, ())
            if any(row.value != 0 for row in absolute_writers):
                continue
            raw_head = head.to_bytes(4, "little")
            references_are_owned_operands = True
            for section in self.image.sections:
                if not section.is_executable:
                    continue
                blob = self.image.read(section.va, section.raw_size)
                offset = blob.find(raw_head)
                while offset >= 0:
                    reference = section.va + offset
                    owner = self.byte_owners.get(reference)
                    if owner is None:
                        references_are_owned_operands = False
                        break
                    instruction = self._owned_decoded(owner)
                    if not any(
                        (
                            operand.type == X86_OP_IMM
                            and operand.imm & 0xFFFF_FFFF == head
                        )
                        or (
                            operand.type == X86_OP_MEM
                            and operand.mem.base == X86_REG_INVALID
                            and operand.mem.index == X86_REG_INVALID
                            and operand.mem.disp & 0xFFFF_FFFF == head
                        )
                        for operand in instruction.operands
                    ):
                        references_are_owned_operands = False
                        break
                    offset = blob.find(raw_head, offset + 1)
                if not references_are_owned_operands:
                    break
            if not references_are_owned_operands:
                continue
            if any(
                relocation.type == 3
                and not _is_executable_span(
                    self.image, relocation.va, 1
                )
                and _is_mapped_span(self.image, relocation.va, 4)
                and int.from_bytes(
                    _read_loader_initialized(
                        self.image, relocation.va, 4
                    ),
                    "little",
                )
                == head
                for relocation in self.image.relocations
            ):
                continue
            if not self._argument_has_copy_constructor_origin(
                registrar, 0, copy_function, frozenset()
            ):
                continue
            candidates.append((head, link, registrar))
        result = tuple(sorted(set(candidates)))
        self.copy_registry_cache[cache_key] = result
        return result

    def _function_returns_registered_copy_origin(
        self,
        function_entry: int,
        copy_function: int,
        trusted_arguments: frozenset[int] = frozenset(),
    ) -> bool:
        signature = self._summary_fact_signature()
        registries = self._closed_copy_registries(copy_function)
        cache_key = (
            function_entry,
            copy_function,
            signature,
            self.control_flow_revision,
            tuple(sorted(trusted_arguments)),
            registries,
        )
        if cache_key in self.registered_copy_return_cache:
            return self.registered_copy_return_cache[cache_key]
        self.registered_copy_return_cache[cache_key] = False
        heads = {row[0] for row in registries}
        links = {row[1] for row in registries}
        if not heads or function_entry not in self.function_addresses:
            self.registered_copy_return_cache[cache_key] = False
            return False
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        # Bit domain: 1=null, 2=registered node, 4=unknown.
        initial = {name: 4 for name in _REGISTER_FAMILIES}
        states: dict[int, dict[str, int]] = {function_entry: initial}
        pending = [function_entry]
        queued = {function_entry}
        return_domains = []
        saw_registry_load = False
        iterations = 0

        def operand_domain(
            current: int, operand, state: dict[str, int]
        ) -> int:
            nonlocal saw_registry_load
            if operand.type == X86_OP_REG:
                return state.get(self._register_family(operand.reg), 4)
            if operand.type == X86_OP_IMM:
                return 1 if operand.imm & 0xFFFF_FFFF == 0 else 4
            if operand.type != X86_OP_MEM:
                return 4
            memory = operand.mem
            argument_index = self._stack_argument_index_at(
                current, operand, function_entry
            )
            if argument_index is not None:
                return (
                    3
                    if argument_index in trusted_arguments
                    or self._argument_has_copy_constructor_origin(
                        function_entry,
                        argument_index,
                        copy_function,
                        frozenset(),
                    )
                    else 4
                )
            logical_offset = self._stack_operand_logical_offset(
                current, operand, function_entry
            )
            if logical_offset is not None:
                return state.get(f"stack:{logical_offset:+#x}", 4)
            if (
                memory.segment == X86_REG_INVALID
                and memory.base == X86_REG_INVALID
                and memory.index == X86_REG_INVALID
                and memory.disp & 0xFFFF_FFFF in heads
            ):
                saw_registry_load = True
                return 3
            if (
                memory.segment == X86_REG_INVALID
                and memory.base != X86_REG_INVALID
                and memory.index == X86_REG_INVALID
                and memory.disp in links
                and not state.get(self._register_family(memory.base), 4) & 4
            ):
                return 3
            if self._is_closed_registered_cursor_load(
                function_entry,
                current,
                memory,
                registries,
            ):
                saw_registry_load = True
                return 3
            return 4

        while pending:
            address = heapq.heappop(pending)
            queued.remove(address)
            if not function_entry <= address < following_entry:
                self.registered_copy_return_cache[cache_key] = False
                return False
            decoded = self._owned_decoded(address)
            state = dict(states[address])
            if decoded.group(CS_GRP_RET):
                return_domains.append(state.get("eax", 4))
                continue
            if decoded.group(CS_GRP_CALL):
                for family in ("eax", "ecx", "edx"):
                    state[family] = 4
            elif (
                decoded.id == X86_INS_XOR
                and len(decoded.operands) == 2
                and all(row.type == X86_OP_REG for row in decoded.operands)
                and self._register_family(decoded.operands[0].reg)
                == self._register_family(decoded.operands[1].reg)
            ):
                state[self._register_family(decoded.operands[0].reg)] = 1
            elif decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                destination, source = decoded.operands
                value = operand_domain(address, source, state)
                if destination.type == X86_OP_REG:
                    state[self._register_family(destination.reg)] = value
                elif destination.type == X86_OP_MEM:
                    logical_offset = self._stack_operand_logical_offset(
                        address, destination, function_entry
                    )
                    if logical_offset is not None:
                        state[f"stack:{logical_offset:+#x}"] = value
            else:
                for register in decoded.regs_write:
                    state[self._register_family(register)] = 4
                for operand in decoded.operands:
                    if operand.type == X86_OP_REG and operand.access & CS_AC_WRITE:
                        state[self._register_family(operand.reg)] = 4
            for successor in self._summary_successors(
                address, function_entry, following_entry
            ):
                if not function_entry <= successor < following_entry:
                    self.registered_copy_return_cache[cache_key] = False
                    return False
                prior = states.get(successor)
                if prior is None:
                    states[successor] = dict(state)
                    changed = True
                else:
                    keys = set(_REGISTER_FAMILIES) | set(prior) | set(state)
                    joined = {
                        family: prior.get(family, 4) | state.get(family, 4)
                        for family in keys
                    }
                    changed = joined != prior
                    if changed:
                        states[successor] = joined
                if changed and successor not in queued:
                    heapq.heappush(pending, successor)
                    queued.add(successor)
            iterations += 1
            self.limits.check("max_summary_iterations", iterations)
        result = (
            saw_registry_load
            and bool(return_domains)
            and any(row & 2 for row in return_domains)
            and all(not row & 4 for row in return_domains)
        )
        self.registered_copy_return_cache[cache_key] = result
        return result

    def _function_returns_copy_constructor_origin(
        self, function_entry: int, copy_function: int
    ) -> bool:
        """Prove every return is null or a fresh/registered descriptor copy."""
        signature = self._summary_fact_signature()
        cache_key = (
            function_entry,
            copy_function,
            signature,
            self.control_flow_revision,
        )
        if cache_key in self.copy_return_cache:
            return self.copy_return_cache[cache_key]
        self.copy_return_cache[cache_key] = False
        if (
            function_entry not in self.function_addresses
            or not self._function_directly_calls_target(
                function_entry, copy_function
            )
        ):
            return False
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        # Bit domain: 1=null, 2=copy origin, 4=unknown.
        initial = {name: 4 for name in _REGISTER_FAMILIES}
        states: dict[int, dict[str, int]] = {function_entry: initial}
        pending = [function_entry]
        queued = {function_entry}
        return_domains = []
        iterations = 0
        while pending:
            address = heapq.heappop(pending)
            queued.remove(address)
            if not function_entry <= address < following_entry:
                return False
            decoded = self._owned_decoded(address)
            state = dict(states[address])
            if decoded.group(CS_GRP_RET):
                return_domains.append(state.get("eax", 4))
                continue
            if decoded.group(CS_GRP_CALL):
                target = self.direct_call_targets_by_source.get(address)
                state["eax"] = (
                    3
                    if target is not None
                    and target == copy_function
                    else 4
                )
                state["ecx"] = 4
                state["edx"] = 4
            elif (
                decoded.id == X86_INS_XOR
                and len(decoded.operands) == 2
                and all(row.type == X86_OP_REG for row in decoded.operands)
                and self._register_family(decoded.operands[0].reg)
                == self._register_family(decoded.operands[1].reg)
            ):
                state[self._register_family(decoded.operands[0].reg)] = 1
            elif (
                decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
            ):
                destination = self._register_family(decoded.operands[0].reg)
                source = decoded.operands[1]
                if source.type == X86_OP_REG:
                    value = state.get(self._register_family(source.reg), 4)
                elif (
                    source.type == X86_OP_IMM
                    and source.imm & 0xFFFF_FFFF == 0
                ):
                    value = 1
                else:
                    value = 4
                state[destination] = value
            else:
                for register in decoded.regs_write:
                    state[self._register_family(register)] = 4
                for operand in decoded.operands:
                    if (
                        operand.type == X86_OP_REG
                        and operand.access & CS_AC_WRITE
                    ):
                        state[self._register_family(operand.reg)] = 4
            for successor in self._summary_successors(
                address, function_entry, following_entry
            ):
                if not function_entry <= successor < following_entry:
                    return False
                prior = states.get(successor)
                if prior is None:
                    joined = dict(state)
                else:
                    joined = {
                        family: prior.get(family, 4) | state.get(family, 4)
                        for family in _REGISTER_FAMILIES
                    }
                if prior == joined:
                    continue
                states[successor] = joined
                if successor not in queued:
                    heapq.heappush(pending, successor)
                    queued.add(successor)
            iterations += 1
            self.limits.check("max_summary_iterations", iterations)
        result = (
            bool(return_domains)
            and any(row & 2 for row in return_domains)
            and all(not row & 4 for row in return_domains)
        )
        self.copy_return_cache[cache_key] = result
        return result

    def _function_directly_calls_target(
        self, function_entry: int, target: int
    ) -> bool:
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        return any(
            function_entry <= source < following_entry
            for source in self.direct_call_sources_by_target.get(target, ())
        )

    def _registered_copy_states(
        self, function_entry: int, copy_function: int
    ) -> dict[int, dict[str, int]] | None:
        """Build nullable registered-copy state once for one function."""
        signature = self._summary_fact_signature()
        registries = self._closed_copy_registries(copy_function)
        cache_key = (
            function_entry,
            copy_function,
            signature,
            self.control_flow_revision,
            registries,
        )
        if cache_key in self.registered_copy_state_cache:
            if self.registered_copy_state_cache[cache_key] is None:
                self.registered_copy_state_tainted.update(
                    self.registered_copy_state_active
                )
            return self.registered_copy_state_cache[cache_key]
        # ``None`` is an in-progress sentinel. Recursive origin questions are
        # therefore fail-closed without caching a false per-address result.
        self.registered_copy_state_cache[cache_key] = None
        self.registered_copy_state_active.add(cache_key)
        heads = {row[0] for row in registries}
        links = {row[1] for row in registries}
        if function_entry not in self.function_addresses:
            return self._finish_registered_copy_states(cache_key, {})
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        # Bit domain: 1=null, 2=registered node, 4=unknown.
        initial = {name: 4 for name in _REGISTER_FAMILIES}
        states: dict[int, dict[str, int]] = {function_entry: initial}
        pending = [function_entry]
        queued = {function_entry}
        iterations = 0

        def operand_domain(current: int, operand, state: dict[str, int]) -> int:
            if operand.type == X86_OP_REG:
                return state.get(self._register_family(operand.reg), 4)
            if operand.type == X86_OP_IMM:
                return 1 if operand.imm & 0xFFFF_FFFF == 0 else 4
            if operand.type != X86_OP_MEM:
                return 4
            memory = operand.mem
            if (
                memory.segment == X86_REG_INVALID
                and memory.base == X86_REG_INVALID
                and memory.index == X86_REG_INVALID
                and memory.disp & 0xFFFF_FFFF in heads
            ):
                return 3
            if (
                memory.segment == X86_REG_INVALID
                and memory.base != X86_REG_INVALID
                and memory.index == X86_REG_INVALID
                and memory.disp in links
                and not state.get(self._register_family(memory.base), 4) & 4
            ):
                return 3
            if self._is_closed_registered_cursor_load(
                function_entry,
                current,
                memory,
                registries,
            ):
                return 3
            argument_index = self._stack_argument_index_at(
                current, operand, function_entry
            )
            if argument_index is not None and (
                self._argument_has_copy_constructor_origin(
                    function_entry,
                    argument_index,
                    copy_function,
                    frozenset(),
                )
            ):
                return 3
            logical_offset = self._stack_operand_logical_offset(
                current, operand, function_entry
            )
            if logical_offset is not None:
                return state.get(f"stack:{logical_offset:+#x}", 4)
            return 4

        while pending:
            current = heapq.heappop(pending)
            queued.remove(current)
            if not function_entry <= current < following_entry:
                return self._finish_registered_copy_states(cache_key, {})
            decoded = self._owned_decoded(current)
            state = dict(states[current])
            if decoded.group(CS_GRP_CALL):
                call_target = self.direct_call_targets_by_source.get(current)
                call_returns_origin = (
                    call_target is not None
                    and (
                        call_target == copy_function
                        or self._function_returns_copy_constructor_origin(
                            call_target, copy_function
                        )
                        or self._function_returns_registered_copy_origin(
                            call_target, copy_function
                        )
                    )
                )
                if not call_returns_origin and call_target is not None:
                    pushed = self._pushed_call_argument(current, 0)
                    if pushed is not None and pushed[2] == function_entry:
                        argument_domain = operand_domain(
                            pushed[0].address, pushed[1], state
                        )
                        call_returns_origin = (
                            bool(argument_domain & 3)
                            and not argument_domain & 4
                            and self._function_returns_registered_copy_origin(
                                call_target,
                                copy_function,
                                frozenset({0}),
                            )
                        )
                state["eax"] = (
                    3 if call_returns_origin else 4
                )
                state["ecx"] = 4
                state["edx"] = 4
            elif (
                decoded.id == X86_INS_XOR
                and len(decoded.operands) == 2
                and all(row.type == X86_OP_REG for row in decoded.operands)
                and self._register_family(decoded.operands[0].reg)
                == self._register_family(decoded.operands[1].reg)
            ):
                state[self._register_family(decoded.operands[0].reg)] = 1
            elif decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                destination, source = decoded.operands
                value = operand_domain(current, source, state)
                if destination.type == X86_OP_REG:
                    state[
                        self._register_family(destination.reg)
                    ] = value
                elif destination.type == X86_OP_MEM:
                    logical_offset = self._stack_operand_logical_offset(
                        current, destination, function_entry
                    )
                    if logical_offset is not None:
                        state[f"stack:{logical_offset:+#x}"] = value
            else:
                for register in decoded.regs_write:
                    state[self._register_family(register)] = 4
                for operand in decoded.operands:
                    if (
                        operand.type == X86_OP_REG
                        and operand.access & CS_AC_WRITE
                    ):
                        state[self._register_family(operand.reg)] = 4
            for successor in self._summary_successors(
                current, function_entry, following_entry
            ):
                prior = states.get(successor)
                if prior is None:
                    joined = dict(state)
                else:
                    keys = set(_REGISTER_FAMILIES) | set(prior) | set(state)
                    joined = {
                        family: prior.get(family, 4) | state.get(family, 4)
                        for family in keys
                    }
                if prior == joined:
                    continue
                states[successor] = joined
                if successor not in queued:
                    heapq.heappush(pending, successor)
                    queued.add(successor)
            iterations += 1
            self.limits.check("max_summary_iterations", iterations)
        return self._finish_registered_copy_states(cache_key, states)

    def _finish_registered_copy_states(
        self,
        cache_key: tuple[Any, ...],
        states: dict[int, dict[str, int]],
    ) -> dict[int, dict[str, int]]:
        self.registered_copy_state_active.remove(cache_key)
        if cache_key in self.registered_copy_state_tainted:
            self.registered_copy_state_tainted.remove(cache_key)
            self.registered_copy_state_cache.pop(cache_key, None)
        else:
            self.registered_copy_state_cache[cache_key] = states
        return states

    def _register_has_registered_copy_origin(
        self,
        address: int,
        register_family: str,
        function_entry: int,
        copy_function: int,
    ) -> bool:
        """Prove a register is a nullable fresh or registered copy."""
        signature = self._summary_fact_signature()
        registries = self._closed_copy_registries(copy_function)
        cache_key = (
            address,
            register_family,
            function_entry,
            copy_function,
            signature,
            self.control_flow_revision,
            registries,
        )
        if cache_key in self.registered_copy_register_cache:
            return self.registered_copy_register_cache[cache_key]
        state_cache_key = (
            function_entry,
            copy_function,
            signature,
            self.control_flow_revision,
            registries,
        )
        states = self._registered_copy_states(function_entry, copy_function)
        if states is None:
            return False
        domain = states.get(address, {}).get(register_family, 4)
        result = bool(domain & 2) and not domain & 4
        if self.registered_copy_state_cache.get(state_cache_key) is states:
            self.registered_copy_register_cache[cache_key] = result
        return result

    def _register_has_copy_constructor_origin(
        self,
        address: int,
        register_family: str,
        function_entry: int,
        copy_function: int,
        visited: frozenset[tuple[int, int]],
    ) -> bool:
        def registered_origin() -> bool:
            return self._register_has_registered_copy_origin(
                address, register_family, function_entry, copy_function
            )

        argument_proof = self._register_argument_proof_across_blocks(
            address, register_family, function_entry
        )
        if argument_proof is not None:
            if self._argument_has_copy_constructor_origin(
                function_entry,
                argument_proof[0],
                copy_function,
                visited,
            ):
                return True
            return registered_origin()

        def definitions_have_copy_origin() -> bool:
            key = (
                address,
                -1 - _REGISTER_FAMILIES.index(register_family),
            )
            if key in visited:
                return False
            definitions = self._register_definitions_across_blocks(
                address, register_family, function_entry
            )
            if not definitions:
                return False
            next_visited = visited | {key}
            for definition_address in definitions:
                definition = self._owned_decoded(definition_address)
                if (
                    definition.id == X86_INS_MOV
                    and len(definition.operands) == 2
                    and definition.operands[0].type == X86_OP_REG
                    and self._register_family(definition.operands[0].reg)
                    == register_family
                ):
                    if not self._operand_has_copy_constructor_origin(
                        definition_address,
                        definition.operands[1],
                        function_entry,
                        copy_function,
                        next_visited,
                    ):
                        return False
                    continue
                if definition.group(CS_GRP_CALL) and register_family == "eax":
                    call_target = self.direct_call_targets_by_source.get(
                        definition_address
                    )
                    if call_target is None or not (
                        call_target == copy_function
                        or self._function_returns_copy_constructor_origin(
                            call_target, copy_function
                        )
                        or self._function_returns_registered_copy_origin(
                            call_target, copy_function
                        )
                    ):
                        return False
                    continue
                return False
            return True

        cursor = address
        for _ in range(128):
            previous = self._previous_instruction(cursor)
            if previous is None or previous.address < function_entry:
                return registered_origin()
            decoded = self._owned_decoded(previous.address)
            writes_family = any(
                self._register_family(row) == register_family
                for row in decoded.regs_write
            ) or any(
                row.type == X86_OP_REG
                and row.access & CS_AC_WRITE
                and self._register_family(row.reg) == register_family
                for row in decoded.operands
            )
            if writes_family:
                if (
                    decoded.id == X86_INS_MOV
                    and len(decoded.operands) == 2
                    and decoded.operands[0].type == X86_OP_REG
                    and self._register_family(decoded.operands[0].reg)
                    == register_family
                ):
                    if self._operand_has_copy_constructor_origin(
                        previous.address,
                        decoded.operands[1],
                        function_entry,
                        copy_function,
                        visited,
                    ):
                        return True
                return registered_origin()
            if decoded.group(CS_GRP_CALL):
                if register_family == "eax":
                    call_target = self.direct_call_targets_by_source.get(
                        decoded.address
                    )
                    if call_target is not None and (
                        call_target == copy_function
                        or self._function_returns_copy_constructor_origin(
                            call_target, copy_function
                        )
                        or self._function_returns_registered_copy_origin(
                            call_target, copy_function
                        )
                    ):
                        return True
                    return registered_origin()
                if register_family in {"ecx", "edx"}:
                    return registered_origin()
            if decoded.group(CS_GRP_RET):
                return registered_origin()
            if decoded.group(CS_GRP_JUMP):
                if definitions_have_copy_origin():
                    return True
                return registered_origin()
            cursor = previous.address
            if previous.address in self.block_starts:
                predecessor = self._previous_instruction(previous.address)
                if (
                    predecessor is None
                    or predecessor.address + predecessor.size
                    != previous.address
                    or not self._owned_decoded(predecessor.address).group(
                        CS_GRP_CALL
                    )
                ):
                    if definitions_have_copy_origin():
                        return True
                    return registered_origin()
        return registered_origin()

    def _guarded_slot_zero_descriptor_consumers(
        self,
    ) -> tuple[tuple[int, int, int, int], ...]:
        """Find guarded ``call (*(*(arg + 0) + 0))`` consumers."""
        cache_key = (
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        cached = self.guarded_slot_zero_consumer_cache.get(cache_key)
        if cached is not None:
            return cached
        consumers = []
        for address in sorted(self.instructions):
            decoded = self._owned_decoded(address)
            if (
                not decoded.group(CS_GRP_CALL)
                or len(decoded.operands) != 1
                or decoded.operands[0].type != X86_OP_REG
            ):
                continue
            function_entry = self._registrar_function_entry(address)
            if function_entry is None:
                continue
            target_family = self._register_family(
                decoded.operands[0].reg
            )
            target_definitions = self._register_definitions_across_blocks(
                address, target_family, function_entry
            )
            if not target_definitions:
                continue
            descriptor_families = set()
            valid_target_loads = True
            for definition_address in sorted(target_definitions):
                definition = self._owned_decoded(definition_address)
                if (
                    definition.id != X86_INS_MOV
                    or len(definition.operands) != 2
                    or definition.operands[0].type != X86_OP_REG
                    or self._register_family(definition.operands[0].reg)
                    != target_family
                    or definition.operands[1].type != X86_OP_MEM
                    or definition.operands[1].size != 4
                    or definition.operands[1].mem.segment
                    != X86_REG_INVALID
                    or definition.operands[1].mem.index
                    != X86_REG_INVALID
                    or definition.operands[1].mem.base
                    == X86_REG_INVALID
                    or definition.operands[1].mem.disp != 0
                ):
                    valid_target_loads = False
                    break
                descriptor_families.add(
                    self._register_family(
                        definition.operands[1].mem.base
                    )
                )
            if not valid_target_loads or len(descriptor_families) != 1:
                continue
            descriptor_family = next(iter(descriptor_families))
            descriptor_definitions = set()
            for definition_address in sorted(target_definitions):
                definitions = self._register_definitions_across_blocks(
                    definition_address,
                    descriptor_family,
                    function_entry,
                )
                if not definitions:
                    descriptor_definitions.clear()
                    break
                descriptor_definitions.update(definitions)
            if not descriptor_definitions:
                continue
            argument_indices = set()
            valid_descriptor_loads = True
            for definition_address in sorted(descriptor_definitions):
                definition = self._owned_decoded(definition_address)
                if (
                    definition.id != X86_INS_MOV
                    or len(definition.operands) != 2
                    or definition.operands[0].type != X86_OP_REG
                    or self._register_family(definition.operands[0].reg)
                    != descriptor_family
                    or definition.operands[1].type != X86_OP_MEM
                    or definition.operands[1].size != 4
                    or definition.operands[1].mem.segment
                    != X86_REG_INVALID
                    or definition.operands[1].mem.index
                    != X86_REG_INVALID
                    or definition.operands[1].mem.base
                    == X86_REG_INVALID
                    or definition.operands[1].mem.disp != 0
                ):
                    valid_descriptor_loads = False
                    break
                argument_index = self._register_argument_index_across_blocks(
                    definition_address,
                    self._register_family(
                        definition.operands[1].mem.base
                    ),
                    function_entry,
                )
                if argument_index is None:
                    valid_descriptor_loads = False
                    break
                argument_indices.add(argument_index)
            if not valid_descriptor_loads or len(argument_indices) != 1:
                continue
            guard = self._dominating_nonzero_guard(
                address, decoded.operands[0], function_entry
            )
            if guard is None:
                continue
            consumers.append(
                (
                    address,
                    function_entry,
                    next(iter(argument_indices)),
                    guard[0],
                )
            )
        result = tuple(consumers)
        self.guarded_slot_zero_consumer_cache[cache_key] = result
        return result

    def _record_copied_descriptor_callback_tables(self) -> None:
        """Hypothesize slot-zero roots from a closed copied-record shape."""
        copy_info = self._copied_descriptor_source_domains(frozenset())
        if copy_info is None:
            return
        copy_function, domains = copy_info
        source_bases = tuple(sorted(value for value in domains[0] if value))
        consumers = self._guarded_slot_zero_descriptor_consumers()
        if not source_bases or not consumers:
            return

        relocation_rows: dict[int, list[int]] = {}
        for relocation in self.image.relocations:
            relocation_rows.setdefault(relocation.va, []).append(
                relocation.type
            )
        records = []
        evidence = []
        target_source_bases: dict[int, set[int]] = {}
        consumer_detail = ",".join(
            f"{address:#x}/arg{argument}/guard={guard:#x}"
            for address, _function, argument, guard in consumers
        )
        for table_base in source_bases:
            if table_base % 4:
                return
            slots = []
            relocation_detail = []
            for index in range(9):
                slot = table_base + index * 4
                try:
                    raw = _read_loader_initialized(self.image, slot, 4)
                except ValueError:
                    return
                target = int.from_bytes(raw, "little")
                relocations = relocation_rows.get(slot, [])
                if target == 0:
                    if relocations:
                        return
                elif relocations != [3] or not _is_executable_span(
                    self.image, target, 1
                ):
                    return
                if self.global_slot_writes.get(slot) or any(
                    write_address < slot + 4
                    and slot < write_address + width
                    for write_address, writers in (
                        self.absolute_memory_writes.items()
                    )
                    for writer in writers
                    for width in {
                        operand.size
                        for operand in self._owned_decoded(writer).operands
                        if self._absolute_memory_operand(operand)
                        == write_address
                        and operand.access & CS_AC_WRITE
                    }
                ):
                    return
                slots.append((slot, raw, target))
                if target:
                    relocation_detail.append(
                        f"relocation={slot:#x};type=3;"
                        f"bytes={raw.hex()}"
                    )
            detail = (
                "proof=finite-all-raw-callers+fixed-nine-dword-copy+"
                "guarded-two-load-slot-zero-consumer+immutable-relocated-"
                "record-shape;raw-relocation-is-not-code-root;"
                f"copy-function={copy_function:#x};"
                f"table-base={table_base:#x};entries=9;"
                f"consumers={consumer_detail}"
            )
            evidence.append(
                _DataEvidence(
                    start=table_base,
                    end=table_base + 9 * 4,
                    provenance=detail
                    + (
                        "|" + "|".join(relocation_detail)
                        if relocation_detail
                        else ""
                    ),
                )
            )
            slot, raw, target = slots[0]
            if target:
                target_source_bases.setdefault(target, set()).add(table_base)
                records.append(
                    SeedRecord(
                        address=target,
                        category="copied-descriptor-callback-entry",
                        provenance_address=slot,
                        provenance_bytes=raw.hex(),
                        detail=f"slot=0;{detail}",
                        is_function=True,
                    )
                )
        if not records:
            return
        hypothesis = _CopiedDescriptorCallbackHypothesis(
            source_bases=source_bases,
            target_source_bases=tuple(
                (target, tuple(sorted(bases)))
                for target, bases in sorted(target_source_bases.items())
            ),
            records=tuple(records),
            data_evidence=tuple(evidence),
        )
        self.copied_descriptor_callback_hypotheses.add(hypothesis)
        replayed_seed_identities = {
            (
                record.address,
                record.category,
                record.provenance_address,
                record.provenance_bytes,
                record.is_function,
            )
            for record in self.seed_records
        }
        if not all(
            (
                record.address,
                record.category,
                record.provenance_address,
                record.provenance_bytes,
                record.is_function,
            )
            in replayed_seed_identities
            for record in records
        ):
            return
        self.validated_copied_descriptor_callback_hypotheses.add(
            hypothesis
        )
        self.data_evidence.update(evidence)
        for address, _function, _argument, guard in consumers:
            for target, target_bases in hypothesis.target_source_bases:
                provenance = (
                    "finite-all-raw-callers+fixed-nine-dword-copy+"
                    "guarded-two-load-slot-zero-consumer;"
                    f"guard={guard:#x};slots="
                    + ",".join(f"{base:#x}" for base in target_bases)
                )
                self._add_edge(
                    address,
                    target,
                    "indirect-call-copied-descriptor-slot-zero",
                    provenance=provenance,
                )
                self._record_finite_target(target)

    def _is_descriptor_copy_constructor(
        self, function_entry: int, following_entry: int
    ) -> bool:
        addresses = [
            row
            for row in sorted(self.instructions)
            if function_entry <= row < following_entry
        ]
        decoded_rows = [self._owned_decoded(row) for row in addresses]
        index_by_address = {
            decoded.address: index
            for index, decoded in enumerate(decoded_rows)
        }

        allocation_fields: dict[int, tuple[int, int, str, int]] = {}
        for call in sorted(
            (
                row
                for row in self.direct_calls
                if function_entry <= row.address < following_entry
            ),
            key=lambda row: row.address,
        ):
            zero_push = self._previous_instruction(call.address)
            size_push = (
                None
                if zero_push is None
                else self._previous_instruction(zero_push.address)
            )
            following = self.instructions.get(call.address)
            if zero_push is None or size_push is None or following is None:
                continue
            zero_decoded = self._owned_decoded(zero_push.address)
            size_decoded = self._owned_decoded(size_push.address)
            next_address = call.address + following.size
            if next_address not in self.instructions:
                continue
            store = self._owned_decoded(next_address)
            if (
                zero_decoded.mnemonic != "push"
                or len(zero_decoded.operands) != 1
                or zero_decoded.operands[0].type != X86_OP_IMM
                or zero_decoded.operands[0].imm != 0
                or size_decoded.mnemonic != "push"
                or len(size_decoded.operands) != 1
                or size_decoded.operands[0].type != X86_OP_IMM
                or store.mnemonic != "mov"
                or len(store.operands) != 2
                or store.operands[0].type != X86_OP_MEM
                or store.operands[0].mem.segment != X86_REG_INVALID
                or store.operands[0].mem.index != X86_REG_INVALID
                or store.operands[0].mem.base == X86_REG_INVALID
                or store.operands[1].type != X86_OP_REG
                or self._register_family(store.operands[1].reg) != "eax"
            ):
                continue
            displacement = store.operands[0].mem.disp
            if displacement not in {0, 4, 8}:
                continue
            if displacement in allocation_fields:
                return False
            allocation_fields[displacement] = (
                size_decoded.operands[0].imm & 0xFFFF_FFFF,
                call.target,
                self._register_family(store.operands[0].mem.base),
                index_by_address[next_address],
            )
        if set(allocation_fields) != {0, 4, 8}:
            return False
        if {
            displacement: row[0]
            for displacement, row in allocation_fields.items()
        } != {0: 0x24, 4: 0x18, 8: 8}:
            return False
        if len({row[1] for row in allocation_fields.values()}) != 1:
            return False
        object_families = {row[2] for row in allocation_fields.values()}
        if len(object_families) != 1:
            return False
        object_family = next(iter(object_families))

        def no_clobber(family: str, start: int, end: int) -> bool:
            if start >= end:
                return False
            definitions = self._register_definitions_across_blocks(
                decoded_rows[end].address,
                family,
                function_entry,
            )
            return definitions == frozenset({decoded_rows[start].address})

        def mov_eax_from_object(index: int, displacement: int) -> bool:
            decoded = decoded_rows[index]
            if (
                decoded.mnemonic != "mov"
                or len(decoded.operands) != 2
                or decoded.operands[0].type != X86_OP_REG
                or self._register_family(decoded.operands[0].reg) != "eax"
                or decoded.operands[1].type != X86_OP_MEM
            ):
                return False
            memory = decoded.operands[1].mem
            return (
                memory.segment == X86_REG_INVALID
                and memory.index == X86_REG_INVALID
                and memory.base != X86_REG_INVALID
                and self._register_family(memory.base) == object_family
                and memory.disp == displacement
                and index > allocation_fields[displacement][3]
            )

        def lea_from_eax(index: int, family: str) -> bool:
            decoded = decoded_rows[index]
            if (
                decoded.mnemonic != "lea"
                or len(decoded.operands) != 2
                or decoded.operands[0].type != X86_OP_REG
                or self._register_family(decoded.operands[0].reg) != family
                or decoded.operands[1].type != X86_OP_MEM
            ):
                return False
            memory = decoded.operands[1].mem
            return (
                memory.segment == X86_REG_INVALID
                and memory.index == X86_REG_INVALID
                and memory.base != X86_REG_INVALID
                and self._register_family(memory.base) == "eax"
                and memory.disp == 0
            )

        def stack_argument_load(index: int, argument_index: int) -> bool:
            decoded = decoded_rows[index]
            return (
                decoded.mnemonic == "mov"
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and self._register_family(decoded.operands[0].reg) == "eax"
                and self._stack_argument_index_at(
                    decoded.address, decoded.operands[1], function_entry
                )
                == argument_index
            )

        def copied_string_contract(
            copy_index: int, displacement: int, argument_index: int
        ) -> bool:
            window_start = max(0, copy_index - 32)
            for destination_load in range(window_start, copy_index):
                if not mov_eax_from_object(destination_load, displacement):
                    continue
                for destination_lea in range(
                    destination_load + 1, copy_index
                ):
                    if not lea_from_eax(destination_lea, "edi") or not no_clobber(
                        "eax", destination_load, destination_lea
                    ):
                        continue
                    for source_load in range(destination_lea + 1, copy_index):
                        if not stack_argument_load(source_load, argument_index):
                            continue
                        for source_lea in range(source_load + 1, copy_index):
                            if (
                                lea_from_eax(source_lea, "esi")
                                and no_clobber("eax", source_load, source_lea)
                                and no_clobber("edi", destination_lea, copy_index)
                                and no_clobber("esi", source_lea, copy_index)
                            ):
                                return True
            return False

        rep_indices = [
            index
            for index, decoded in enumerate(decoded_rows)
            if decoded.mnemonic == "rep movsd"
        ]
        if len(rep_indices) != 1:
            return False
        rep_index = rep_indices[0]
        if not copied_string_contract(rep_index, 0, 0):
            return False
        ecx_nine = [
            index
            for index in range(max(0, rep_index - 8), rep_index)
            if decoded_rows[index].mnemonic == "mov"
            and len(decoded_rows[index].operands) == 2
            and decoded_rows[index].operands[0].type == X86_OP_REG
            and self._register_family(decoded_rows[index].operands[0].reg)
            == "ecx"
            and decoded_rows[index].operands[1].type == X86_OP_IMM
            and decoded_rows[index].operands[1].imm == 9
            and no_clobber("ecx", index, rep_index)
        ]
        if len(ecx_nine) != 1:
            return False

        movsd_indices = [
            index
            for index, decoded in enumerate(decoded_rows)
            if decoded.mnemonic == "movsd"
        ]
        if len(movsd_indices) != 6:
            return False
        if any(
            decoded_rows[left].address + decoded_rows[left].size
            != decoded_rows[right].address
            for left, right in zip(movsd_indices, movsd_indices[1:])
        ):
            return False
        if not copied_string_contract(movsd_indices[0], 4, 1):
            return False

        argument_two_loads = []
        for index, decoded in enumerate(decoded_rows):
            if (
                decoded.mnemonic == "mov"
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and self._stack_argument_index_at(
                    decoded.address, decoded.operands[1], function_entry
                )
                == 2
            ):
                argument_two_loads.append(
                    (index, self._register_family(decoded.operands[0].reg))
                )
        for argument_load, source_family in argument_two_loads:
            destination_loads = [
                index
                for index, decoded in enumerate(decoded_rows)
                if argument_load < index
                and index > allocation_fields[8][3]
                and decoded.mnemonic == "mov"
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and decoded.operands[1].type == X86_OP_MEM
                and decoded.operands[1].mem.base != X86_REG_INVALID
                and decoded.operands[1].mem.index == X86_REG_INVALID
                and self._register_family(decoded.operands[1].mem.base)
                == object_family
                and decoded.operands[1].mem.disp == 8
            ]
            for destination_load in destination_loads:
                destination_family = self._register_family(
                    decoded_rows[destination_load].operands[0].reg
                )
                component_reads: dict[int, list[tuple[int, str]]] = {}
                component_writes: dict[int, list[tuple[int, str]]] = {}
                for index in range(destination_load + 1, len(decoded_rows)):
                    decoded = decoded_rows[index]
                    if decoded.mnemonic != "mov" or len(decoded.operands) != 2:
                        continue
                    destination, source = decoded.operands
                    if (
                        destination.type == X86_OP_REG
                        and source.type == X86_OP_MEM
                        and source.mem.base != X86_REG_INVALID
                        and source.mem.index == X86_REG_INVALID
                        and self._register_family(source.mem.base)
                        == source_family
                        and source.mem.disp in {0, 4}
                    ):
                        component_reads.setdefault(source.mem.disp, []).append(
                            (
                                index,
                                self._register_family(destination.reg),
                            )
                        )
                    if (
                        destination.type == X86_OP_MEM
                        and destination.mem.base != X86_REG_INVALID
                        and destination.mem.index == X86_REG_INVALID
                        and self._register_family(destination.mem.base)
                        == destination_family
                        and destination.mem.disp in {0, 4}
                        and source.type == X86_OP_REG
                    ):
                        component_writes.setdefault(
                            destination.mem.disp, []
                        ).append(
                            (index, self._register_family(source.reg))
                        )
                if set(component_reads) != {0, 4} or set(component_writes) != {
                    0,
                    4,
                }:
                    continue
                if any(
                    len(component_reads[offset]) != 1
                    or len(component_writes[offset]) != 1
                    for offset in (0, 4)
                ):
                    continue
                singular_reads = {
                    offset: component_reads[offset][0] for offset in (0, 4)
                }
                singular_writes = {
                    offset: component_writes[offset][0] for offset in (0, 4)
                }
                if any(
                    singular_reads[offset][1] != singular_writes[offset][1]
                    or singular_reads[offset][0] >= singular_writes[offset][0]
                    for offset in (0, 4)
                ):
                    continue
                first_read = min(row[0] for row in singular_reads.values())
                last_write = max(row[0] for row in singular_writes.values())
                if (
                    destination_family != source_family
                    and no_clobber(
                        source_family, argument_load, first_read
                    )
                    and no_clobber(
                        destination_family, destination_load, last_write
                    )
                    and not any(
                        decoded_rows[index].group(CS_GRP_CALL)
                        for index in range(first_read, last_write + 1)
                    )
                ):
                    return True
        return False

    def _finite_local_field_store_before(
        self,
        address: int,
        memory,
        function_entry: int,
        visited: frozenset[tuple[int, str]],
    ) -> tuple[frozenset[int], str] | None:
        base_family = self._register_family(memory.base)
        cursor = address
        for _ in range(128):
            previous = self._previous_instruction(cursor)
            if previous is None or previous.address < function_entry:
                return None
            decoded = self._owned_decoded(previous.address)
            if decoded.id == X86_INS_MOV and len(decoded.operands) == 2:
                destination = decoded.operands[0]
                if (
                    destination.type == X86_OP_MEM
                    and destination.size == 4
                    and destination.mem.segment == X86_REG_INVALID
                    and destination.mem.index == X86_REG_INVALID
                    and destination.mem.base != X86_REG_INVALID
                    and self._register_family(destination.mem.base)
                    == base_family
                    and destination.mem.disp == memory.disp
                ):
                    result = self._finite_operand_values_before(
                        previous.address,
                        decoded.operands[1],
                        function_entry,
                        visited
                        | {(address, f"local-field:{base_family}:{memory.disp}")},
                    )
                    if result is None:
                        return None
                    values, detail = result
                    return (
                        values,
                        f"local-field-store={previous.address:#x};{detail}",
                    )
            if (
                decoded.group(CS_GRP_CALL)
                or decoded.group(CS_GRP_JUMP)
                or decoded.group(CS_GRP_RET)
                or previous.address in self.block_starts
                or any(
                    self._register_family(row) == base_family
                    for row in decoded.regs_write
                )
            ):
                return None
            cursor = previous.address
        return None

    def _finite_dynamic_field_values(
        self,
        displacement: int,
        visited: frozenset[tuple[int, str]],
    ) -> tuple[frozenset[int], str] | None:
        key = (-1, f"dynamic-field:{displacement}")
        if key in visited:
            return None
        cache_key = (displacement, self._summary_fact_signature())
        if cache_key in self.dynamic_field_cache:
            return self.dynamic_field_cache[cache_key]
        all_writes = tuple(
            sorted(
                (
                    write
                    for write_displacement, rows in (
                        self.dynamic_field_writes.items()
                    )
                    for write in rows
                    if write_displacement < displacement + 4
                    and displacement < write_displacement + write.width
                ),
                key=lambda row: row.instruction_address,
            )
        )
        writes = []
        stack_writes = []
        for write in all_writes:
            function_entry = self._registrar_function_entry(
                write.instruction_address
            )
            decoded = self._owned_decoded(write.instruction_address)
            if (
                function_entry is not None
                and decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and self._is_stack_backed_memory(
                    write.instruction_address,
                    decoded.operands[0],
                    function_entry,
                )
            ):
                stack_writes.append(write.instruction_address)
                continue
            writes.append(write)
        writes = tuple(writes)
        if not writes:
            self.dynamic_field_cache[cache_key] = None
            return None
        values = set()
        provenance = []
        for write in writes:
            if write.value is not None:
                values.add(write.value)
                provenance.append(write.provenance)
                continue
            function_entry = self._registrar_function_entry(
                write.instruction_address
            )
            if function_entry is None:
                self.dynamic_field_cache[cache_key] = None
                return None
            decoded = self._owned_decoded(write.instruction_address)
            if not (
                decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_MEM
                and decoded.operands[0].size == 4
                and decoded.operands[0].mem.disp == displacement
            ):
                self.dynamic_field_cache[cache_key] = None
                return None
            result = self._finite_operand_values_before(
                write.instruction_address,
                decoded.operands[1],
                function_entry,
                visited | {key},
            )
            if result is None:
                self.dynamic_field_cache[cache_key] = None
                return None
            write_values, detail = result
            values.update(write_values)
            provenance.append(f"{write.provenance};{detail.split(';caller=', 1)[0]}")
        if not values:
            self.dynamic_field_cache[cache_key] = None
            return None
        self._check_count("max_finite_values", len(values))
        result = (
            frozenset(values),
            "writes="
            + "|".join(provenance)
            + (
                ";stack-storage-disjoint="
                + ",".join(f"{address:#x}" for address in stack_writes)
                if stack_writes
                else ""
            ),
        )
        self.dynamic_field_cache[cache_key] = result
        return result

    def _summary_successors(
        self, address: int, function_entry: int, following_entry: int
    ) -> tuple[int, ...]:
        decoded = self._owned_decoded(address)
        next_address = decoded.address + decoded.size
        if decoded.group(CS_GRP_RET) or decoded.group(CS_GRP_IRET):
            successors: tuple[int, ...] = ()
        elif decoded.group(CS_GRP_CALL):
            successors = (
                ()
                if self._call_is_proven_no_return(decoded, frozenset())
                else (next_address,)
            )
        elif decoded.group(CS_GRP_JUMP):
            successors = tuple(
                sorted(
                    self.non_call_successors.get(decoded.address, ())
                )
            )
        else:
            successors = (next_address,)
        return tuple(
            row
            for row in successors
            if function_entry <= row < following_entry
            and row in self.instructions
        )

    def _call_is_proven_no_return(
        self, decoded, visited: frozenset[int]
    ) -> bool:
        if len(decoded.operands) != 1:
            return False
        operand = decoded.operands[0]
        if operand.type == X86_OP_MEM:
            memory = operand.mem
            if (
                operand.size == 4
                and memory.segment == X86_REG_INVALID
                and memory.base == X86_REG_INVALID
                and memory.index == X86_REG_INVALID
            ):
                iat_va = memory.disp & 0xFFFF_FFFF
                imported = next(
                    (row for row in self.image.imports if row.iat_va == iat_va),
                    None,
                )
                return (
                    imported is not None
                    and imported.name is not None
                    and imported.name.casefold() == "exitprocess"
                )
            return False
        target = self._direct_target(decoded)
        if target is None or target not in self.function_addresses:
            return False
        return self._function_is_proven_no_return(target, visited)

    def _function_is_proven_no_return(
        self, function_entry: int, visited: frozenset[int]
    ) -> bool:
        if function_entry in visited:
            return False
        cache_key = (function_entry, self._summary_fact_signature())
        if cache_key in self.no_return_cache:
            return self.no_return_cache[cache_key]
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        pending = [function_entry]
        seen = set()
        while pending:
            address = heapq.heappop(pending)
            if address in seen:
                continue
            if (
                address not in self.instructions
                or not function_entry <= address < following_entry
            ):
                self.no_return_cache[cache_key] = False
                return False
            seen.add(address)
            self.limits.check("max_summary_iterations", len(seen))
            decoded = self._owned_decoded(address)
            if decoded.group(CS_GRP_RET) or decoded.group(CS_GRP_IRET):
                self.no_return_cache[cache_key] = False
                return False
            if decoded.group(CS_GRP_CALL):
                if self._call_is_proven_no_return(
                    decoded, visited | {function_entry}
                ):
                    continue
                successors = (decoded.address + decoded.size,)
            elif decoded.group(CS_GRP_JUMP):
                successors = tuple(
                    sorted(
                        self.non_call_successors.get(decoded.address, ())
                    )
                )
                if not successors:
                    self.no_return_cache[cache_key] = False
                    return False
            else:
                successors = (decoded.address + decoded.size,)
            for successor in successors:
                if not function_entry <= successor < following_entry:
                    self.no_return_cache[cache_key] = False
                    return False
                if successor not in seen:
                    heapq.heappush(pending, successor)
        self.no_return_cache[cache_key] = True
        return True

    def _reachable_within_function(
        self,
        start: int,
        target: int,
        function_entry: int,
        following_entry: int,
        *,
        excluded: int | frozenset[int] | None = None,
    ) -> bool:
        excluded_addresses = (
            frozenset()
            if excluded is None
            else frozenset({excluded})
            if isinstance(excluded, int)
            else excluded
        )
        pending = [start]
        visited = set()
        while pending:
            current = heapq.heappop(pending)
            if current in excluded_addresses or current in visited:
                continue
            if current == target:
                return True
            visited.add(current)
            self.limits.check("max_summary_iterations", len(visited))
            for successor in self._summary_successors(
                current, function_entry, following_entry
            ):
                if successor not in visited:
                    heapq.heappush(pending, successor)
        return False

    def _same_guard_operand(
        self,
        guard_address: int,
        guard_operand,
        transfer_address: int,
        transfer_operand,
        function_entry: int,
    ) -> bool:
        if guard_operand.type != transfer_operand.type:
            return False
        if guard_operand.type == X86_OP_REG:
            return (
                self._register_family(guard_operand.reg)
                == self._register_family(transfer_operand.reg)
            )
        if guard_operand.type != X86_OP_MEM:
            return False
        left = guard_operand.mem
        right = transfer_operand.mem
        if (
            left.segment != X86_REG_INVALID
            or right.segment != X86_REG_INVALID
            or left.index != X86_REG_INVALID
            or right.index != X86_REG_INVALID
            or left.base == X86_REG_INVALID
            or right.base == X86_REG_INVALID
        ):
            return False
        left_base = self._register_family(left.base)
        right_base = self._register_family(right.base)
        if left_base != right_base:
            return False
        if left_base == "ebp" and left.disp == right.disp:
            for address in sorted(self.instructions):
                if not guard_address < address < transfer_address:
                    continue
                decoded = self._owned_decoded(address)
                if decoded.group(CS_GRP_CALL) or any(
                    self._register_family(register) == "ebp"
                    for register in decoded.regs_write
                ) or any(
                    operand.type == X86_OP_REG
                    and operand.access & CS_AC_WRITE
                    and self._register_family(operand.reg) == "ebp"
                    for operand in decoded.operands
                ):
                    return False
            return True
        if left_base in {"esp", "ebp"}:
            stack_states = self._function_stack_states(function_entry)
            if (
                stack_states is None
                or guard_address not in stack_states
                or transfer_address not in stack_states
            ):
                return False
            left_sp, left_bp = stack_states[guard_address]
            right_sp, right_bp = stack_states[transfer_address]
            left_delta = left_sp if left_base == "esp" else left_bp
            right_delta = right_sp if right_base == "esp" else right_bp
            return (
                left_delta is not None
                and right_delta is not None
                and left_delta + left.disp == right_delta + right.disp
            )
        return left.disp == right.disp

    def _dominating_nonzero_guard(
        self,
        transfer_address: int,
        transfer_operand,
        function_entry: int,
    ) -> tuple[int, int] | None:
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        candidates = [
            row
            for row in sorted(self.instructions)
            if function_entry <= row < transfer_address
        ][-2048:]
        for branch_address in reversed(candidates):
            branch = self._owned_decoded(branch_address)
            if branch.mnemonic not in {"je", "jne", "jz", "jnz"}:
                continue
            condition = None
            cursor = branch_address
            for _ in range(16):
                previous = self._previous_instruction(cursor)
                if previous is None or previous.address + previous.size != cursor:
                    break
                previous_decoded = self._owned_decoded(previous.address)
                if x86_const.X86_REG_EFLAGS in previous_decoded.regs_write:
                    condition = previous
                    break
                if (
                    previous_decoded.group(CS_GRP_CALL)
                    or previous_decoded.group(CS_GRP_JUMP)
                    or previous_decoded.group(CS_GRP_RET)
                    or previous.address in self.block_starts
                ):
                    break
                cursor = previous.address
            if condition is None:
                continue
            compared = self._owned_decoded(condition.address)
            guard_operand = None
            if (
                compared.mnemonic == "test"
                and len(compared.operands) == 2
                and self._same_guard_operand(
                    condition.address,
                    compared.operands[0],
                    condition.address,
                    compared.operands[1],
                    function_entry,
                )
            ):
                guard_operand = compared.operands[0]
            elif (
                compared.mnemonic == "cmp"
                and len(compared.operands) == 2
                and compared.operands[1].type == X86_OP_IMM
                and compared.operands[1].imm & 0xFFFF_FFFF == 0
            ):
                guard_operand = compared.operands[0]
            if guard_operand is None or not self._same_guard_operand(
                condition.address,
                guard_operand,
                transfer_address,
                transfer_operand,
                function_entry,
            ):
                continue
            branch_target = self._direct_target(branch)
            if branch_target is None:
                continue
            fallthrough = branch.address + branch.size
            if branch.mnemonic in {"je", "jz"}:
                zero_successor, nonzero_successor = branch_target, fallthrough
            else:
                zero_successor, nonzero_successor = fallthrough, branch_target
            if self._reachable_within_function(
                function_entry,
                transfer_address,
                function_entry,
                following_entry,
                excluded=branch.address,
            ):
                continue
            if self._reachable_within_function(
                zero_successor,
                transfer_address,
                function_entry,
                following_entry,
                excluded=branch.address,
            ):
                continue
            if not self._reachable_within_function(
                nonzero_successor,
                transfer_address,
                function_entry,
                following_entry,
            ):
                continue
            return condition.address, branch.address
        return None

    def _dominating_register_equal_guard(
        self,
        transfer_address: int,
        register_family: str,
        function_entry: int,
    ) -> tuple[int, int, int] | None:
        """Return an exact value forced by a dominating equality arm."""
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        candidates = [
            row
            for row in sorted(self.instructions)
            if function_entry <= row < transfer_address
        ][-2048:]
        for branch_address in reversed(candidates):
            branch = self._owned_decoded(branch_address)
            if branch.mnemonic not in {"je", "jne", "jz", "jnz"}:
                continue
            condition = None
            cursor = branch_address
            for _ in range(16):
                previous = self._previous_instruction(cursor)
                if previous is None or previous.address + previous.size != cursor:
                    break
                previous_decoded = self._owned_decoded(previous.address)
                if x86_const.X86_REG_EFLAGS in previous_decoded.regs_write:
                    condition = previous
                    break
                if (
                    previous_decoded.group(CS_GRP_CALL)
                    or previous_decoded.group(CS_GRP_JUMP)
                    or previous_decoded.group(CS_GRP_RET)
                    or previous.address in self.block_starts
                ):
                    break
                cursor = previous.address
            if condition is None:
                continue
            compared = self._owned_decoded(condition.address)
            if (
                compared.mnemonic != "cmp"
                or len(compared.operands) != 2
                or compared.operands[0].type != X86_OP_REG
                or self._register_family(compared.operands[0].reg)
                != register_family
                or compared.operands[1].type != X86_OP_IMM
            ):
                continue
            branch_target = self._direct_target(branch)
            if branch_target is None:
                continue
            fallthrough = branch.address + branch.size
            if branch.mnemonic in {"je", "jz"}:
                equal_successor, unequal_successor = branch_target, fallthrough
            else:
                equal_successor, unequal_successor = fallthrough, branch_target
            if self._reachable_within_function(
                function_entry,
                transfer_address,
                function_entry,
                following_entry,
                excluded=branch.address,
            ):
                continue
            if self._reachable_within_function(
                unequal_successor,
                transfer_address,
                function_entry,
                following_entry,
                excluded=branch.address,
            ):
                continue
            if not self._reachable_within_function(
                equal_successor,
                transfer_address,
                function_entry,
                following_entry,
            ):
                continue
            clobbered = False
            for row in candidates:
                if not condition.address < row < transfer_address:
                    continue
                decoded = self._owned_decoded(row)
                if decoded.group(CS_GRP_CALL):
                    if register_family in {"eax", "ecx", "edx"}:
                        clobbered = True
                        break
                    continue
                if any(
                    self._register_family(register) == register_family
                    for register in decoded.regs_write
                ) or any(
                    operand.type == X86_OP_REG
                    and operand.access & CS_AC_WRITE
                    and self._register_family(operand.reg) == register_family
                    for operand in decoded.operands
                ):
                    clobbered = True
                    break
            if clobbered:
                continue
            return (
                compared.operands[1].imm & 0xFFFF_FFFF,
                condition.address,
                branch.address,
            )
        return None

    def _cw_action_dispatch_table(self) -> JumpTable | None:
        """Return the unique table indexing ``(packed_action.kind - 1)``."""
        if self.cw_exception_metadata is None:
            return None
        matches = []
        for table in self.jump_tables.values():
            if (
                table.flow_kind != "jump"
                or table.index_min != 0
                or table.index_max != 18
                or len(table.raw_entries) != 19
            ):
                continue
            transfer = self._owned_decoded(table.address)
            if (
                len(transfer.operands) != 1
                or transfer.operands[0].type != X86_OP_MEM
                or transfer.operands[0].mem.index == X86_REG_INVALID
            ):
                continue
            index_family = self._register_family(
                transfer.operands[0].mem.index
            )
            compare = self.instructions.get(table.guard_address)
            if compare is None:
                continue
            subtract = self._previous_instruction(compare.address)
            mask = (
                None
                if subtract is None
                else self._previous_instruction(subtract.address)
            )
            if subtract is None or mask is None:
                continue
            subtract_decoded = self._owned_decoded(subtract.address)
            mask_decoded = self._owned_decoded(mask.address)
            if not (
                subtract_decoded.mnemonic == "sub"
                and len(subtract_decoded.operands) == 2
                and subtract_decoded.operands[0].type == X86_OP_REG
                and self._register_family(subtract_decoded.operands[0].reg)
                == index_family
                and subtract_decoded.operands[1].type == X86_OP_IMM
                and subtract_decoded.operands[1].imm & 0xFFFF_FFFF == 1
                and mask_decoded.mnemonic == "and"
                and len(mask_decoded.operands) == 2
                and mask_decoded.operands[0].type == X86_OP_REG
                and self._register_family(mask_decoded.operands[0].reg)
                == index_family
                and mask_decoded.operands[1].type == X86_OP_IMM
                and mask_decoded.operands[1].imm & 0xFFFF_FFFF == 0xFF
            ):
                continue
            source_family = None
            cursor = mask.address
            for _ in range(4):
                previous = self._previous_instruction(cursor)
                if previous is None:
                    break
                decoded = self._owned_decoded(previous.address)
                if (
                    decoded.mnemonic == "movzx"
                    and len(decoded.operands) == 2
                    and decoded.operands[0].type == X86_OP_REG
                    and self._register_family(decoded.operands[0].reg)
                    == index_family
                    and decoded.operands[1].type == X86_OP_REG
                    and decoded.operands[1].size == 2
                ):
                    source_family = self._register_family(
                        decoded.operands[1].reg
                    )
                    cursor = previous.address
                    break
                if any(
                    self._register_family(row) == index_family
                    for row in decoded.regs_write
                ):
                    break
                cursor = previous.address
            if source_family is None:
                continue
            tag_load = self._previous_instruction(cursor)
            if tag_load is None:
                continue
            tag_decoded = self._owned_decoded(tag_load.address)
            if not (
                tag_decoded.id == X86_INS_MOV
                and len(tag_decoded.operands) == 2
                and tag_decoded.operands[0].type == X86_OP_REG
                and self._register_family(tag_decoded.operands[0].reg)
                == source_family
                and tag_decoded.operands[0].size == 2
                and tag_decoded.operands[1].type == X86_OP_MEM
                and tag_decoded.operands[1].size == 2
                and tag_decoded.operands[1].mem.segment == X86_REG_INVALID
                and tag_decoded.operands[1].mem.index == X86_REG_INVALID
                and tag_decoded.operands[1].mem.base != X86_REG_INVALID
                and tag_decoded.operands[1].mem.disp == 0
            ):
                continue
            matches.append(table)
        return matches[0] if len(matches) == 1 else None

    def _cw_inactive_action_helpers(
        self,
    ) -> tuple[dict[int, set[int]], set[int]]:
        signature = self._summary_fact_signature()
        if signature in self.cw_inactive_helpers_cache:
            return self.cw_inactive_helpers_cache[signature]
        table = self._cw_action_dispatch_table()
        if table is None or self.cw_exception_metadata is None:
            result: tuple[dict[int, set[int]], set[int]] = ({}, set())
            self.cw_inactive_helpers_cache[signature] = result
            return result
        active_kinds = set(self.cw_exception_metadata.action_kinds) - {
            3,
            13,
            14,
            15,
            18,
        }
        callback_kinds = {1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12}
        helper_kinds: dict[int, set[int]] = {}
        handler_calls: set[int] = set()
        direct_call_by_address = {
            row.address: row for row in self.direct_calls
        }
        for kind in sorted(callback_kinds - active_kinds):
            handler = table.raw_entries[kind - 1]
            cursor = handler
            calls = []
            for _ in range(32):
                instruction = self.instructions.get(cursor)
                if instruction is None:
                    break
                decoded = self._owned_decoded(cursor)
                direct_call = direct_call_by_address.get(cursor)
                if direct_call is not None:
                    calls.append(direct_call)
                if (
                    decoded.group(CS_GRP_JUMP)
                    or decoded.group(CS_GRP_RET)
                    or decoded.group(CS_GRP_IRET)
                ):
                    break
                cursor += decoded.size
            if len(calls) != 1:
                continue
            call = calls[0]
            helper_kinds.setdefault(call.target, set()).add(kind)
            handler_calls.add(call.address)
        result = (helper_kinds, handler_calls)
        self.cw_inactive_helpers_cache[signature] = result
        return result

    def _recover_cw_inactive_action_helper(
        self, instruction: Instruction
    ) -> bool:
        function_entry = self._registrar_function_entry(instruction.address)
        if function_entry is None:
            return False
        helper_kinds, handler_calls = self._cw_inactive_action_helpers()
        kinds = helper_kinds.get(function_entry)
        if not kinds:
            return False
        callers = set(
            self.direct_call_sources_by_target.get(function_entry, ())
        )
        if not callers or not callers <= handler_calls:
            return False
        self.diagnostics.add(
            OwnershipDiagnostic(
                kind="proven-unreachable-control",
                address=instruction.address,
                detail=(
                    "CodeWarrior packed action kinds are absent: kinds="
                    + ",".join(str(row) for row in sorted(kinds))
                    + ";registered-kinds="
                    + ",".join(
                        str(row)
                        for row in self.cw_exception_metadata.action_kinds
                    )
                    + f";helper={function_entry:#x}"
                ),
            )
        )
        return True

    def _recover_cw_continuation_jump(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        if (
            flow_kind != "jump"
            or self.cw_exception_metadata is None
            or len(decoded.operands) != 1
            or decoded.operands[0].type != X86_OP_REG
        ):
            return False
        target_family = self._register_family(decoded.operands[0].reg)
        target_definition = None
        cursor = instruction.address
        for _ in range(20):
            previous = self._previous_instruction(cursor)
            if previous is None:
                return False
            candidate = self._owned_decoded(previous.address)
            writes_target = any(
                self._register_family(row) == target_family
                for row in candidate.regs_write
            ) or (
                bool(candidate.operands)
                and candidate.operands[0].type == X86_OP_REG
                and self._register_family(candidate.operands[0].reg)
                == target_family
                and bool(candidate.operands[0].access & CS_AC_WRITE)
            )
            if writes_target:
                if (
                    candidate.id == X86_INS_MOV
                    and len(candidate.operands) == 2
                    and candidate.operands[0].type == X86_OP_REG
                    and self._register_family(candidate.operands[0].reg)
                    == target_family
                    and candidate.operands[1].type == X86_OP_MEM
                    and candidate.operands[1].size == 4
                    and candidate.operands[1].mem.segment
                    == X86_REG_INVALID
                    and candidate.operands[1].mem.index == X86_REG_INVALID
                    and candidate.operands[1].mem.base != X86_REG_INVALID
                    and candidate.operands[1].mem.disp in {4, 6}
                ):
                    target_definition = candidate
                break
            if candidate.group(CS_GRP_CALL) or candidate.group(CS_GRP_JUMP):
                return False
            cursor = previous.address
        if target_definition is None:
            return False
        displacement = target_definition.operands[1].mem.disp
        kind = 19 if displacement == 4 else 16

        # Both runtime continuation paths restore the four nonvolatile GPRs
        # from one context object and reset x87 immediately before jumping.
        context_loads_by_base: dict[str, dict[int, str]] = {}
        saw_fninit = False
        saw_wait = False
        cursor = instruction.address
        for _ in range(20):
            previous = self._previous_instruction(cursor)
            if previous is None:
                break
            candidate = self._owned_decoded(previous.address)
            if candidate.mnemonic == "fninit":
                saw_fninit = True
            if candidate.mnemonic == "wait":
                saw_wait = True
            if (
                candidate.address != target_definition.address
                and candidate.id == X86_INS_MOV
                and len(candidate.operands) == 2
                and candidate.operands[0].type == X86_OP_REG
                and candidate.operands[1].type == X86_OP_MEM
                and candidate.operands[1].size == 4
                and candidate.operands[1].mem.segment == X86_REG_INVALID
                and candidate.operands[1].mem.index == X86_REG_INVALID
                and candidate.operands[1].mem.base != X86_REG_INVALID
                and candidate.operands[1].mem.disp in {0, 4, 8, 12}
            ):
                base_family = self._register_family(
                    candidate.operands[1].mem.base
                )
                context_loads_by_base.setdefault(base_family, {})[
                    candidate.operands[1].mem.disp
                ] = self._register_family(candidate.operands[0].reg)
            cursor = previous.address
        if (
            {0: "ebx", 4: "esi", 8: "edi", 12: "ebp"}
            not in context_loads_by_base.values()
            or not saw_fninit
            or not saw_wait
        ):
            return False
        targets = tuple(
            target
            for target_kind, target in (
                self.cw_exception_metadata.continuation_targets
            )
            if target_kind == kind
        )
        if not targets:
            return False
        provenance = (
            f"cw-packed-continuation-kind={kind};"
            f"field={displacement:+#x};"
            f"definition={target_definition.address:#x};"
            "targets=" + ",".join(f"{row:#x}" for row in targets)
        )
        for target in targets:
            self.seed_records.add(
                SeedRecord(
                    address=target,
                    category="cw-exception-continuation",
                    provenance_address=instruction.address,
                    provenance_bytes=instruction.bytes_hex,
                    detail=provenance,
                )
            )
            self._add_edge(
                instruction.address,
                target,
                "indirect-jump-cw-exception-continuation",
                provenance=provenance,
            )
            self._record_finite_target(target)
            self._enqueue(target, is_function=False)
        self._record_fixpoint_update()
        return True

    def _raw_direct_call_sites(self, target: int) -> frozenset[int]:
        if self.raw_direct_call_sites_cache is not None:
            return self.raw_direct_call_sites_cache.get(target, frozenset())
        sites_by_target: dict[int, set[int]] = {}
        for section in self.image.sections:
            if not section.is_executable or section.raw_size < 5:
                continue
            blob = self.image.read(section.va, section.raw_size)
            for offset, opcode in enumerate(blob[:-4]):
                if opcode != 0xE8:
                    continue
                displacement = struct.unpack_from("<i", blob, offset + 1)[0]
                address = section.va + offset
                resolved = (address + 5 + displacement) & 0xFFFF_FFFF
                sites_by_target.setdefault(resolved, set()).add(address)
        self.raw_direct_call_sites_cache = {
            resolved: frozenset(sites)
            for resolved, sites in sites_by_target.items()
        }
        return self.raw_direct_call_sites_cache.get(target, frozenset())

    def _direct_calls_to(self, target: int) -> tuple[DirectCall, ...]:
        return tuple(
            DirectCall(address, target)
            for address in sorted(
                self.direct_call_sources_by_target.get(target, ())
            )
        )

    def _cw_k17_builder_domain(
        self, builder: int
    ) -> tuple[int, frozenset[int], str] | None:
        builder_callers = self._direct_calls_to(builder)
        if len(builder_callers) != 1:
            return None
        builder_call = builder_callers[0]
        pushed_context = self._previous_instruction(builder_call.address)
        if pushed_context is None:
            return None
        push = self._owned_decoded(pushed_context.address)
        if not (
            push.mnemonic == "push"
            and len(push.operands) == 1
            and push.operands[0].type == X86_OP_REG
            and self._register_family(push.operands[0].reg) == "esp"
        ):
            return None
        wrapper = self._registrar_function_entry(builder_call.address)
        if wrapper is None:
            return None

        maps_argument_two = False
        for address in sorted(self.instructions):
            if not wrapper <= address < builder_call.address:
                continue
            load = self._owned_decoded(address)
            if not (
                load.id == X86_INS_MOV
                and len(load.operands) == 2
                and load.operands[0].type == X86_OP_REG
                and load.operands[1].type == X86_OP_MEM
                and load.operands[1].mem.segment == X86_REG_INVALID
                and load.operands[1].mem.index == X86_REG_INVALID
                and load.operands[1].mem.base != X86_REG_INVALID
                and self._register_family(load.operands[1].mem.base) == "ebp"
                and load.operands[1].mem.disp == 0x10
            ):
                continue
            following = self.instructions.get(address + load.size)
            if following is None:
                continue
            store = self._owned_decoded(following.address)
            if (
                store.id == X86_INS_MOV
                and len(store.operands) == 2
                and store.operands[0].type == X86_OP_MEM
                and store.operands[0].mem.segment == X86_REG_INVALID
                and store.operands[0].mem.index == X86_REG_INVALID
                and store.operands[0].mem.base != X86_REG_INVALID
                and self._register_family(store.operands[0].mem.base) == "esp"
                and store.operands[0].mem.disp == 0x1C
                and store.operands[1].type == X86_OP_REG
                and self._register_family(store.operands[1].reg)
                == self._register_family(load.operands[0].reg)
            ):
                maps_argument_two = True
                break
        if not maps_argument_two:
            return None

        raw_callers = self._raw_direct_call_sites(wrapper)
        decoded_callers = set(
            self.direct_call_sources_by_target.get(wrapper, ())
        )
        exc_section = next(
            row for row in self.image.sections if row.name == ".exc"
        )
        assert self.cw_exception_metadata is not None
        exception_range_functions = {
            function
            for function, _metadata in self.cw_exception_metadata.range_table
        }
        address_taken = any(
            row.type == 3
            and _is_mapped_span(self.image, row.va, 4)
            and int.from_bytes(
                _read_loader_initialized(self.image, row.va, 4), "little"
            )
            == wrapper
            and not (
                exc_section.va <= row.va < exc_section.va + exc_section.virt_size
                and (row.va - exc_section.va) % 8 == 0
                and wrapper in exception_range_functions
            )
            for row in self.image.relocations
        ) or any(row.va == wrapper for row in self.image.exports)
        if not raw_callers or raw_callers != decoded_callers or address_taken:
            return None
        result = self._finite_argument_values(wrapper, 2, frozenset())
        if result is None:
            return None
        values, detail = result
        callbacks = frozenset(value for value in values if value)
        if (
            not callbacks
            or any(
                not _is_executable_span(self.image, value, 1)
                for value in callbacks
            )
            or values - callbacks not in {frozenset(), frozenset({0})}
        ):
            return None
        return (
            wrapper,
            callbacks,
            f"cw-k17-builder={builder:#x};wrapper={wrapper:#x};"
            f"raw-callers={len(raw_callers)};{detail.split(';caller=', 1)[0]}",
        )

    def _cw_k17_destructor_domain(
        self,
    ) -> tuple[frozenset[int], str] | None:
        signature = self._summary_fact_signature()
        if signature in self.cw_k17_domain_cache:
            return self.cw_k17_domain_cache[signature]
        if (
            self.cw_exception_metadata is None
            or not any(
                kind == 17
                for _function, _action, kind in (
                    self.cw_exception_metadata.action_contexts
                )
            )
        ):
            self.cw_k17_domain_cache[signature] = None
            return None

        builders = set()
        for write in sorted(
            self.dynamic_field_writes.get(8, ()),
            key=lambda row: row.instruction_address,
        ):
            address = write.instruction_address
            store = self._owned_decoded(address)
            if not (
                store.id == X86_INS_MOV
                and len(store.operands) == 2
                and store.operands[0].type == X86_OP_MEM
                and store.operands[0].size == 4
                and store.operands[0].mem.segment == X86_REG_INVALID
                and store.operands[0].mem.index == X86_REG_INVALID
                and store.operands[0].mem.base != X86_REG_INVALID
                and store.operands[0].mem.disp == 8
                and store.operands[1].type == X86_OP_REG
            ):
                continue
            load_row = self._previous_instruction(address)
            if load_row is None:
                continue
            load = self._owned_decoded(load_row.address)
            if not (
                load.id == X86_INS_MOV
                and len(load.operands) == 2
                and load.operands[0].type == X86_OP_REG
                and self._register_family(load.operands[0].reg)
                == self._register_family(store.operands[1].reg)
                and load.operands[1].type == X86_OP_MEM
                and load.operands[1].size == 4
                and load.operands[1].mem.segment == X86_REG_INVALID
                and load.operands[1].mem.index == X86_REG_INVALID
                and load.operands[1].mem.base != X86_REG_INVALID
                and load.operands[1].mem.disp == 0x1C
            ):
                continue
            builder = self._registrar_function_entry(address)
            if builder is not None:
                builders.add(builder)
        candidates = [
            result
            for builder in sorted(builders)
            if (result := self._cw_k17_builder_domain(builder)) is not None
        ]
        if len(candidates) != 1:
            self.cw_k17_domain_cache[signature] = None
            return None
        wrapper, callbacks, detail = candidates[0]
        domain = (
            callbacks,
            detail,
        )
        self.cw_k17_wrapper_cache[signature] = wrapper
        self.cw_k17_domain_cache[signature] = domain
        return domain

    def _recover_cw_k17_callback(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        if (
            flow_kind != "call"
            or self.cw_exception_metadata is None
            or len(decoded.operands) != 1
            or decoded.operands[0].type != X86_OP_MEM
            or decoded.operands[0].size != 4
            or decoded.operands[0].mem.segment != X86_REG_INVALID
            or decoded.operands[0].mem.index != X86_REG_INVALID
            or decoded.operands[0].mem.base == X86_REG_INVALID
            or decoded.operands[0].mem.disp != 8
        ):
            return False
        table = self._cw_action_dispatch_table()
        if table is None:
            return False
        handler = table.raw_entries[16]
        handler_function = self._registrar_function_entry(handler)
        if (
            handler_function is None
            or self._registrar_function_entry(instruction.address)
            != handler_function
        ):
            return False
        pending = [handler]
        seen = set()
        following_entry = min(
            (
                row
                for row in self.function_addresses
                if row > handler_function
            ),
            default=0x1_0000_0000,
        )
        handler_contains_call = False
        while pending and len(seen) < 64:
            cursor = heapq.heappop(pending)
            if cursor in seen:
                continue
            seen.add(cursor)
            if cursor == instruction.address:
                handler_contains_call = True
                break
            for successor in sorted(
                self._summary_successors(
                    cursor, handler_function, following_entry
                )
            ):
                if (
                    successor not in seen
                    and successor in self.instructions
                    and self._registrar_function_entry(successor)
                    == handler_function
                ):
                    heapq.heappush(pending, successor)
        if not handler_contains_call:
            return False

        call_base = self._register_family(decoded.operands[0].mem.base)
        guarded = False
        cursor = handler
        while cursor < instruction.address:
            compared_row = self.instructions.get(cursor)
            if compared_row is None:
                break
            compared = self._owned_decoded(cursor)
            if (
                compared.mnemonic == "cmp"
                and len(compared.operands) == 2
                and compared.operands[0].type == X86_OP_MEM
                and compared.operands[0].mem.segment == X86_REG_INVALID
                and compared.operands[0].mem.index == X86_REG_INVALID
                and compared.operands[0].mem.base != X86_REG_INVALID
                and compared.operands[0].mem.disp == 8
                and compared.operands[1].type == X86_OP_IMM
                and compared.operands[1].imm & 0xFFFF_FFFF == 0
            ):
                aliases = {
                    self._register_family(compared.operands[0].mem.base)
                }
                branch = None
                branch_cursor = cursor + compared.size
                for _ in range(4):
                    branch_row = self.instructions.get(branch_cursor)
                    if branch_row is None:
                        break
                    candidate = self._owned_decoded(branch_row.address)
                    if candidate.mnemonic in {"je", "jz"}:
                        branch = candidate
                        break
                    if not (
                        candidate.id == X86_INS_MOV
                        and len(candidate.operands) == 2
                        and candidate.operands[0].type == X86_OP_REG
                        and candidate.operands[1].type == X86_OP_REG
                    ):
                        break
                    destination = self._register_family(
                        candidate.operands[0].reg
                    )
                    source = self._register_family(candidate.operands[1].reg)
                    if source in aliases:
                        aliases.add(destination)
                    else:
                        aliases.discard(destination)
                    branch_cursor += candidate.size
                if branch is None:
                    break
                zero_target = self._direct_target(branch)
                if zero_target is None:
                    break
                scan = branch.address + branch.size
                while scan < instruction.address:
                    row = self._owned_decoded(scan)
                    if (
                        row.id == X86_INS_MOV
                        and len(row.operands) == 2
                        and row.operands[0].type == X86_OP_REG
                    ):
                        destination = self._register_family(
                            row.operands[0].reg
                        )
                        source_is_alias = (
                            row.operands[1].type == X86_OP_REG
                            and self._register_family(row.operands[1].reg)
                            in aliases
                        )
                        if source_is_alias:
                            aliases.add(destination)
                        else:
                            aliases.discard(destination)
                    scan += row.size
                guarded = call_base in aliases and zero_target > instruction.address
                break
            cursor += compared.size
        if not guarded:
            return False
        result = self._cw_k17_destructor_domain()
        if result is None:
            return False
        values, detail = result
        provenance = (
            f"transfer={instruction.address:#x};cw-packed-action-kind=17;"
            + detail
        )
        for target in sorted(values):
            self.seed_records.add(
                SeedRecord(
                    address=target,
                    category="cw-exception-k17-destructor",
                    provenance_address=instruction.address,
                    provenance_bytes=instruction.bytes_hex,
                    detail=provenance,
                    is_function=True,
                )
            )
            self._add_edge(
                instruction.address,
                target,
                "indirect-call-cw-exception-k17",
                provenance=provenance,
            )
            self._record_finite_target(target)
            self._enqueue(target, is_function=True)
        self._record_fixpoint_update()
        return True

    def _finite_direct_call_argument(
        self,
        call: DirectCall,
        argument_index: int,
        visited: frozenset[tuple[int, str]],
    ) -> tuple[frozenset[int], str] | None:
        remaining = argument_index
        cursor = call.address
        for _ in range(32):
            previous = self._previous_instruction(cursor)
            if previous is None:
                return None
            decoded = self._owned_decoded(previous.address)
            if decoded.mnemonic == "push" and len(decoded.operands) == 1:
                if remaining == 0:
                    caller_entry = self._registrar_function_entry(call.address)
                    if caller_entry is None:
                        return None
                    return self._finite_operand_values_before(
                        previous.address,
                        decoded.operands[0],
                        caller_entry,
                        visited,
                    )
                remaining -= 1
            elif (
                decoded.group(CS_GRP_CALL)
                or decoded.group(CS_GRP_JUMP)
                or decoded.group(CS_GRP_RET)
                or any(
                    self._register_family(row) == "esp"
                    for row in decoded.regs_write
                )
            ):
                return None
            cursor = previous.address
            if previous.address in self.block_starts:
                return None
        return None

    def _recover_cw_registered_destructor_callback(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        if (
            flow_kind != "call"
            or len(decoded.operands) != 1
            or decoded.operands[0].type != X86_OP_MEM
            or decoded.operands[0].size != 4
            or decoded.operands[0].mem.segment != X86_REG_INVALID
            or decoded.operands[0].mem.index != X86_REG_INVALID
            or decoded.operands[0].mem.base == X86_REG_INVALID
        ):
            return False
        function_entry = self._registrar_function_entry(instruction.address)
        if function_entry is None:
            return False
        domain = self._cw_k17_destructor_domain()
        signature = self._summary_fact_signature()
        wrapper = self.cw_k17_wrapper_cache.get(signature)
        if domain is None or wrapper is None:
            return False
        global_values, global_detail = domain
        constructor_calls = tuple(
            row
            for row in self.direct_calls
            if row.target == wrapper
            and function_entry <= row.address < instruction.address
        )
        narrowed_calls = []
        for call in constructor_calls:
            local = self._finite_direct_call_argument(
                call, 2, frozenset()
            )
            if local is None:
                return False
            local_values, local_detail = local
            values = frozenset(value for value in local_values if value)
            if not values:
                continue
            if not values <= global_values:
                return False
            narrowed_calls.append((call, values, local_detail))
        if len(narrowed_calls) != 1:
            return False
        constructor_call, values, local_detail = narrowed_calls[0]
        guard = self._dominating_nonzero_guard(
            instruction.address,
            decoded.operands[0],
            function_entry,
        )
        if guard is None:
            return False
        provenance = (
            f"transfer={instruction.address:#x};"
            f"cw-registered-destructor-call={constructor_call.address:#x};"
            f"guard={guard[0]:#x}/{guard[1]:#x};"
            f"{local_detail.split(';caller=', 1)[0]};{global_detail}"
        )
        for target in sorted(values):
            self.seed_records.add(
                SeedRecord(
                    address=target,
                    category="cw-registered-destructor",
                    provenance_address=instruction.address,
                    provenance_bytes=instruction.bytes_hex,
                    detail=provenance,
                    is_function=True,
                )
            )
            self._add_edge(
                instruction.address,
                target,
                "indirect-call-cw-registered-destructor",
                provenance=provenance,
            )
            self._record_finite_target(target)
            self._enqueue(target, is_function=True)
        self._record_fixpoint_update()
        return True

    def _recover_finite_value_target(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        if len(decoded.operands) != 1:
            return False
        operand = decoded.operands[0]
        if operand.type == X86_OP_MEM and operand.mem.index != X86_REG_INVALID:
            return False
        function_entry = self._registrar_function_entry(instruction.address)
        if function_entry is None:
            return False
        result = self._finite_operand_values_before(
            instruction.address,
            operand,
            function_entry,
            frozenset(),
        )
        if result is None:
            return False
        values, detail = result

        def stable_control_detail(value: str) -> str:
            stable = value.split(";caller=", 1)[0]
            marker = ";dynamic-field="
            if marker not in stable:
                return stable
            prefix, dynamic = stable.split(marker, 1)
            displacement = dynamic.split(";", 1)[0]
            return (
                f"{prefix}{marker}{displacement};"
                "proof=all-owned-overlapping-nonstack-writes-finite;"
                "stack-storage-excluded"
            )

        if 0 in values:
            guard = self._dominating_nonzero_guard(
                instruction.address, operand, function_entry
            )
            if guard is not None:
                condition, branch = guard
                stable_detail = stable_control_detail(detail)
                if values == frozenset({0}):
                    self.diagnostics.add(
                        OwnershipDiagnostic(
                            kind="proven-unreachable-control",
                            address=instruction.address,
                            detail=(
                                "zero-domain contradicts nonzero guard: "
                                f"condition={condition:#x};branch={branch:#x};"
                                f"{stable_detail}"
                            ),
                        )
                    )
                    return True
                values = values - {0}
                self.diagnostics.add(
                    OwnershipDiagnostic(
                        kind="proven-unreachable-control-context",
                        address=instruction.address,
                        detail=(
                            "zero context contradicts nonzero guard: "
                            f"condition={condition:#x};branch={branch:#x};"
                            "retained-nonzero-domain="
                            + ",".join(
                                f"{value:#x}" for value in sorted(values)
                            )
                            + f";{stable_detail}"
                        ),
                    )
                )
        if not values or any(
            not _is_executable_span(self.image, value, 1) for value in values
        ):
            return False
        edge_kind = f"indirect-{flow_kind}-finite-value"
        stable_detail = stable_control_detail(detail)
        provenance = (
            f"transfer={instruction.address:#x};function={function_entry:#x};"
            + stable_detail
        )
        for target in sorted(values):
            self.seed_records.add(
                SeedRecord(
                    address=target,
                    category="finite-value-control-target",
                    provenance_address=instruction.address,
                    provenance_bytes=instruction.bytes_hex,
                    detail=provenance,
                    is_function=flow_kind == "call",
                )
            )
            self._add_edge(
                instruction.address,
                target,
                edge_kind,
                provenance=provenance,
            )
            self._record_finite_target(target)
            self._enqueue(target, is_function=flow_kind == "call")
        self._record_fixpoint_update()
        return True

    def _strict_identity_validator(
        self, function_entry: int
    ) -> tuple[int, int] | None:
        """Return ``(tag offset, tag)`` for an identity-or-zero validator."""
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        rows = [
            self._owned_decoded(address)
            for address in sorted(self.instructions)
            if function_entry <= address < following_entry
        ]
        if len(rows) != 8 or [row.mnemonic for row in rows] != [
            "mov",
            "test",
            "je",
            "cmp",
            "jne",
            "ret",
            "xor",
            "ret",
        ]:
            return None
        load, tested, zero_branch, compared, mismatch_branch, _, zeroed, _ = rows
        if (
            len(load.operands) != 2
            or load.operands[0].type != X86_OP_REG
            or self._register_family(load.operands[0].reg) != "eax"
            or self._stack_argument_index_at(
                load.address, load.operands[1], function_entry
            )
            != 0
            or len(tested.operands) != 2
            or any(row.type != X86_OP_REG for row in tested.operands)
            or any(
                self._register_family(row.reg) != "eax"
                for row in tested.operands
            )
            or len(compared.operands) != 2
            or compared.operands[0].type != X86_OP_MEM
            or compared.operands[0].size != 4
            or compared.operands[0].mem.segment != X86_REG_INVALID
            or compared.operands[0].mem.index != X86_REG_INVALID
            or compared.operands[0].mem.base == X86_REG_INVALID
            or self._register_family(compared.operands[0].mem.base) != "eax"
            or compared.operands[1].type != X86_OP_IMM
            or self._direct_target(zero_branch) != zeroed.address
            or self._direct_target(mismatch_branch) != zeroed.address
            or len(zeroed.operands) != 2
            or any(row.type != X86_OP_REG for row in zeroed.operands)
            or any(
                self._register_family(row.reg) != "eax"
                for row in zeroed.operands
            )
        ):
            return None
        return (
            compared.operands[0].mem.disp,
            compared.operands[1].imm & 0xFFFF_FFFF,
        )

    def _pushed_call_argument(
        self, call_address: int, argument_index: int
    ) -> tuple[Instruction, Any, int] | None:
        remaining = argument_index
        cursor = call_address
        for _ in range(32):
            previous = self._previous_instruction(cursor)
            if previous is None:
                return None
            decoded = self._owned_decoded(previous.address)
            if decoded.mnemonic == "push" and len(decoded.operands) == 1:
                if remaining == 0:
                    caller_entry = self._registrar_function_entry(call_address)
                    if caller_entry is None:
                        return None
                    return previous, decoded.operands[0], caller_entry
                remaining -= 1
            elif (
                decoded.group(CS_GRP_CALL)
                or decoded.group(CS_GRP_JUMP)
                or decoded.group(CS_GRP_RET)
                or any(
                    self._register_family(row) == "esp"
                    for row in decoded.regs_write
                )
            ):
                return None
            cursor = previous.address
        return None

    def _fresh_constructor_receiver(
        self, constructor_call: DirectCall, descriptor_field: int
    ) -> tuple[str, int] | None:
        """Prove a constructor receiver is one fresh allocation result."""
        caller_entry = self._registrar_function_entry(constructor_call.address)
        if caller_entry is None:
            return None
        cursor = constructor_call.address
        receiver_family = None
        object_family = None
        allocation_call = None
        saw_nonnull_guard = False
        for _ in range(24):
            previous = self._previous_instruction(cursor)
            if previous is None or previous.address < caller_entry:
                return None
            decoded = self._owned_decoded(previous.address)
            if receiver_family is None:
                if (
                    decoded.id == X86_INS_MOV
                    and len(decoded.operands) == 2
                    and all(row.type == X86_OP_REG for row in decoded.operands)
                    and self._register_family(decoded.operands[0].reg) == "ecx"
                ):
                    receiver_family = "ecx"
                    object_family = self._register_family(
                        decoded.operands[1].reg
                    )
                else:
                    return None
            elif (
                decoded.mnemonic == "test"
                and len(decoded.operands) == 2
                and all(row.type == X86_OP_REG for row in decoded.operands)
                and all(
                    self._register_family(row.reg) == object_family
                    for row in decoded.operands
                )
            ):
                branch = self.instructions.get(decoded.address + decoded.size)
                if branch is not None:
                    branch_decoded = self._owned_decoded(branch.address)
                    saw_nonnull_guard = (
                        branch_decoded.mnemonic == "je"
                        and self._direct_target(branch_decoded) is not None
                    )
            elif (
                decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_REG
                and self._register_family(decoded.operands[0].reg)
                == object_family
                and decoded.operands[1].type == X86_OP_REG
                and self._register_family(decoded.operands[1].reg) == "eax"
            ):
                call_instruction = self._previous_instruction(decoded.address)
                while call_instruction is not None:
                    candidate = self._owned_decoded(call_instruction.address)
                    if candidate.group(CS_GRP_CALL):
                        target = self._direct_target(candidate)
                        if target is not None:
                            allocation_call = call_instruction.address
                        break
                    if candidate.group(CS_GRP_JUMP) or candidate.group(CS_GRP_RET):
                        break
                    call_instruction = self._previous_instruction(
                        call_instruction.address
                    )
                break
            elif decoded.group(CS_GRP_CALL) or any(
                self._register_family(row) == object_family
                for row in decoded.regs_write
            ):
                return None
            cursor = previous.address
        if allocation_call is None or not saw_nonnull_guard or object_family is None:
            return None
        allocation_argument = self._pushed_call_argument(allocation_call, 0)
        if (
            allocation_argument is None
            or allocation_argument[1].type != X86_OP_IMM
            or allocation_argument[1].imm & 0xFFFF_FFFF
            < descriptor_field + 4
        ):
            return None
        return object_family, allocation_call

    def _constructed_consumer_argument(
        self,
        consumer_call: DirectCall,
        constructor_entry: int,
        descriptor_field: int,
        validator: tuple[int, int],
    ) -> bool:
        pushed = self._pushed_call_argument(consumer_call.address, 0)
        if pushed is None:
            return False
        origin = self._closed_object_origin_operand(
            pushed[0].address,
            pushed[1],
            pushed[2],
            constructor_entry,
            descriptor_field,
            validator,
            frozenset(),
        )
        return origin is not None and origin.has_target_constructor

    def _incoming_call_sites(self, function_entry: int) -> tuple[int, ...]:
        return tuple(
            sorted(
                set(
                    self.direct_call_sources_by_target.get(
                        function_entry, ()
                    )
                )
                | {
                    source
                    for source, kind in self.incoming_edges.get(
                        function_entry, ()
                    )
                    if kind.startswith("indirect-call")
                }
            )
        )

    def _direct_call_domain_is_closed(self, function_entry: int) -> bool:
        cache_key = (function_entry, self._summary_fact_signature())
        if cache_key in self.direct_call_domain_cache:
            return self.direct_call_domain_cache[cache_key]
        decoded = set(
            self.direct_call_sources_by_target.get(function_entry, ())
        )
        result = bool(decoded) and (
            self._raw_direct_call_sites(function_entry) == decoded
            and not any(row.va == function_entry for row in self.image.exports)
            and not any(
                row.type == 3
                and _is_mapped_span(self.image, row.va, 4)
                and int.from_bytes(
                    _read_loader_initialized(self.image, row.va, 4), "little"
                )
                == function_entry
                for row in self.image.relocations
            )
        )
        self.direct_call_domain_cache[cache_key] = result
        return result

    def _incoming_call_domain_is_closed(self, function_entry: int) -> bool:
        """Prove all certified address-taken entries have finite callers."""
        cache_key = (
            function_entry,
            self._summary_fact_signature(),
            self.control_flow_revision,
        )
        if cache_key in self.incoming_call_domain_cache:
            return self.incoming_call_domain_cache[cache_key]

        decoded = set(
            self.direct_call_sources_by_target.get(function_entry, ())
        )
        if (
            self._raw_direct_call_sites(function_entry) != decoded
            or any(row.va == function_entry for row in self.image.exports)
        ):
            self.incoming_call_domain_cache[cache_key] = False
            return False

        relocation_types: dict[int, list[int]] = {}
        relocation_references: set[int] = set()
        for relocation in self.image.relocations:
            relocation_types.setdefault(relocation.va, []).append(
                relocation.type
            )
            if not (
                relocation.type == 3
                and _is_mapped_span(self.image, relocation.va, 4)
            ):
                continue
            if int.from_bytes(
                _read_loader_initialized(self.image, relocation.va, 4),
                "little",
            ) == function_entry:
                relocation_references.add(relocation.va)

        accepted_references = {
            row.provenance_address
            for row in self.seed_records
            if row.address == function_entry
            and row.category
            in {
                "copied-descriptor-callback-entry",
                "object-callback-table-entry",
            }
        }
        indirect_sources = {
            source
            for source, kind in self.incoming_edges.get(function_entry, ())
            if kind.startswith("indirect-call-")
        }
        if relocation_references or accepted_references:
            result = (
                relocation_references == accepted_references
                and bool(indirect_sources)
                and all(
                    relocation_types.get(address) == [3]
                    for address in accepted_references
                )
            )
        else:
            result = bool(decoded)
        self.incoming_call_domain_cache[cache_key] = result
        return result

    def _copied_slot_zero_source_bases(
        self, function_entry: int
    ) -> tuple[int, ...] | None:
        records = {
            row.provenance_address
            for row in self.seed_records
            if row.address == function_entry
            and row.category == "copied-descriptor-callback-entry"
        }
        if not records:
            return None
        copy_info = self._copied_descriptor_source_domains(frozenset())
        if copy_info is None:
            return None
        _copy_function, domains = copy_info
        sources = []
        relocation_types: dict[int, list[int]] = {}
        for relocation in self.image.relocations:
            relocation_types.setdefault(relocation.va, []).append(
                relocation.type
            )
        for base in sorted(value for value in domains[0] if value):
            if base not in records or relocation_types.get(base) != [3]:
                continue
            try:
                target = int.from_bytes(
                    _read_loader_initialized(self.image, base, 4), "little"
                )
            except ValueError:
                return None
            if target == function_entry:
                sources.append(base)
        return tuple(sources) or None

    def _stack_pointer_logical_offset(
        self, push_address: int, operand, function_entry: int
    ) -> int | None:
        if operand.type != X86_OP_REG:
            return None
        definitions = self._register_definitions_across_blocks(
            push_address,
            self._register_family(operand.reg),
            function_entry,
        )
        if not definitions or len(definitions) != 1:
            return None
        definition = self._owned_decoded(next(iter(definitions)))
        if (
            definition.id != X86_INS_LEA
            or len(definition.operands) != 2
            or definition.operands[1].type != X86_OP_MEM
        ):
            return None
        memory = definition.operands[1].mem
        if (
            memory.segment != X86_REG_INVALID
            or memory.index != X86_REG_INVALID
            or memory.base == X86_REG_INVALID
        ):
            return None
        base_family = self._register_family(memory.base)
        if base_family not in {"esp", "ebp"}:
            return None
        states = self._function_stack_states(function_entry)
        state = None if states is None else states.get(definition.address)
        if state is None:
            state = self._linear_stack_state_before(
                definition.address, function_entry
            )
        if state is None:
            return None
        sp_delta, bp_delta = state
        base_delta = sp_delta if base_family == "esp" else bp_delta
        return None if base_delta is None else base_delta + memory.disp

    def _stack_operand_logical_offset(
        self, address: int, operand, function_entry: int
    ) -> int | None:
        if (
            operand.type != X86_OP_MEM
            or operand.mem.segment != X86_REG_INVALID
            or operand.mem.index != X86_REG_INVALID
            or operand.mem.base == X86_REG_INVALID
        ):
            return None
        family = self._register_family(operand.mem.base)
        if family not in {"esp", "ebp"}:
            return None
        states = self._function_stack_states(function_entry)
        state = None if states is None else states.get(address)
        if state is None:
            state = self._linear_stack_state_before(address, function_entry)
        if state is None:
            return None
        sp_delta, bp_delta = state
        delta = sp_delta if family == "esp" else bp_delta
        return None if delta is None else delta + operand.mem.disp

    def _stack_value_logical_offset(
        self, address: int, operand, function_entry: int
    ) -> int | None:
        direct = self._stack_operand_logical_offset(
            address, operand, function_entry
        )
        if direct is not None or operand.type != X86_OP_REG:
            return direct
        definitions = self._register_definitions_across_blocks(
            address,
            self._register_family(operand.reg),
            function_entry,
        )
        if not definitions or len(definitions) != 1:
            return None
        definition = self._owned_decoded(next(iter(definitions)))
        if (
            definition.id != X86_INS_MOV
            or len(definition.operands) != 2
            or definition.operands[1].type != X86_OP_MEM
        ):
            return None
        return self._stack_operand_logical_offset(
            definition.address, definition.operands[1], function_entry
        )

    def _same_closed_caller_value(
        self,
        left_address: int,
        left_operand,
        right_address: int,
        right_operand,
        function_entry: int,
    ) -> bool:
        def argument_index(address: int, operand) -> int | None:
            if operand.type == X86_OP_REG:
                return self._register_argument_index_across_blocks(
                    address,
                    self._register_family(operand.reg),
                    function_entry,
                )
            return self._stack_argument_index_at(
                address, operand, function_entry
            )

        left_argument = argument_index(left_address, left_operand)
        right_argument = argument_index(right_address, right_operand)
        if left_argument is not None or right_argument is not None:
            return (
                left_argument is not None
                and left_argument == right_argument
            )
        if left_operand.type != X86_OP_REG or right_operand.type != X86_OP_REG:
            return False
        left_family = self._register_family(left_operand.reg)
        right_family = self._register_family(right_operand.reg)
        if left_family != right_family or left_family not in {
            "ebx",
            "esi",
            "edi",
            "ebp",
        }:
            return False
        left_definitions = self._register_definitions_across_blocks(
            left_address, left_family, function_entry
        )
        right_definitions = self._register_definitions_across_blocks(
            right_address, right_family, function_entry
        )
        return bool(left_definitions) and left_definitions == right_definitions

    def _register_argument_origin_index(
        self,
        address: int,
        register_family: str,
        function_entry: int,
        visited: frozenset[tuple[int, str]] = frozenset(),
    ) -> int | None:
        key = (address, register_family)
        if key in visited:
            return None
        direct = self._register_argument_index_across_blocks(
            address, register_family, function_entry
        )
        if direct is not None:
            return direct
        definitions = self._register_definitions_across_blocks(
            address, register_family, function_entry
        )
        if not definitions:
            return None
        indices = set()
        for definition_address in definitions:
            definition = self._owned_decoded(definition_address)
            if (
                definition.id != X86_INS_MOV
                or len(definition.operands) != 2
                or definition.operands[0].type != X86_OP_REG
            ):
                return None
            source = definition.operands[1]
            index = self._stack_argument_index_at(
                definition.address, source, function_entry
            )
            if index is None and source.type == X86_OP_REG:
                index = self._register_argument_origin_index(
                    definition.address,
                    self._register_family(source.reg),
                    function_entry,
                    visited | {key},
                )
            if index is None:
                return None
            indices.add(index)
        return next(iter(indices)) if len(indices) == 1 else None

    def _copied_record_object_relation(
        self,
        call_address: int,
        record_argument: int,
        object_argument: int,
    ) -> tuple[int, int, int] | None:
        record = self._pushed_call_argument(call_address, record_argument)
        object_value = self._pushed_call_argument(call_address, object_argument)
        if record is None or object_value is None:
            return None
        wrapper_entry = record[2]
        if object_value[2] != wrapper_entry or object_value[1].type != X86_OP_REG:
            return None
        object_family = self._register_family(object_value[1].reg)
        definitions = self._register_definitions_across_blocks(
            object_value[0].address, object_family, wrapper_entry
        )
        if not definitions or len(definitions) != 1:
            return None
        load = self._owned_decoded(next(iter(definitions)))
        if (
            load.id != X86_INS_MOV
            or len(load.operands) != 2
            or load.operands[1].type != X86_OP_MEM
            or load.operands[1].size != 4
            or load.operands[1].mem.segment != X86_REG_INVALID
            or load.operands[1].mem.index != X86_REG_INVALID
            or load.operands[1].mem.base == X86_REG_INVALID
            or load.operands[1].mem.disp <= 0
        ):
            return None
        record_family = self._register_family(load.operands[1].mem.base)
        record_parameter = self._register_argument_index_across_blocks(
            load.address, record_family, wrapper_entry
        )
        if record_parameter is None:
            return None
        if record[1].type == X86_OP_REG:
            if self._register_family(record[1].reg) != record_family:
                return None
        elif self._stack_argument_index_at(
            record[0].address, record[1], wrapper_entry
        ) != record_parameter:
            return None
        return wrapper_entry, record_parameter, load.operands[1].mem.disp

    def _relocated_immediate_in_function(
        self, function_entry: int, value: int
    ) -> bool:
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        occurrences = []
        relocated = []
        for address in sorted(self.instructions):
            if not function_entry <= address < following_entry:
                continue
            decoded = self._owned_decoded(address)
            if not any(
                operand.type == X86_OP_IMM
                and operand.size == 4
                and operand.imm & 0xFFFF_FFFF == value
                for operand in decoded.operands
            ):
                continue
            occurrences.append(address)
            if any(
                row.type == 3
                and row.va == decoded.address + decoded.imm_offset
                for row in self.image.relocations
            ):
                relocated.append(address)
        return bool(occurrences) and occurrences == relocated

    def _memcpy_like_function(self, function_entry: int) -> bool:
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        rows = [
            self._owned_decoded(address)
            for address in sorted(self.instructions)
            if function_entry <= address < following_entry
            and self._reachable_within_function(
                function_entry, address, function_entry, following_entry
            )
        ]
        expected_mnemonics = [
            "mov",
            "push",
            "push",
            "mov",
            "mov",
            "mov",
            "xor",
            "cmp",
            "jl",
            "sub",
            "and",
            "je",
            "sub",
            "rep movsb",
            "mov",
            "and",
            "shr",
            "rep movsd",
            "test",
            "je",
            "mov",
            "rep movsb",
            "mov",
            "pop",
            "pop",
            "ret",
        ]
        if [row.mnemonic for row in rows] != expected_mnemonics:
            return False
        dest_load, _, _, length_load, source_load, dest_copy = rows[:6]
        if (
            self._stack_argument_index_at(
                dest_load.address, dest_load.operands[1], function_entry
            )
            != 0
            or self._register_family(dest_load.operands[0].reg) != "edx"
            or self._stack_argument_index_at(
                length_load.address, length_load.operands[1], function_entry
            )
            != 2
            or self._register_family(length_load.operands[0].reg) != "eax"
            or self._stack_argument_index_at(
                source_load.address, source_load.operands[1], function_entry
            )
            != 1
            or self._register_family(source_load.operands[0].reg) != "esi"
            or any(row.type != X86_OP_REG for row in dest_copy.operands)
            or self._register_family(dest_copy.operands[0].reg) != "edi"
            or self._register_family(dest_copy.operands[1].reg) != "edx"
        ):
            return False
        if (
            self._direct_target(rows[8]) != rows[20].address
            or self._direct_target(rows[11]) != rows[14].address
            or self._direct_target(rows[19]) != rows[22].address
            or [row.op_str for row in (rows[6], rows[9], rows[10])] != [
                "ecx, ecx",
                "ecx, edi",
                "ecx, 3",
            ]
            or rows[7].op_str != "eax, 0x10"
            or rows[12].op_str != "eax, ecx"
            or rows[14].op_str != "ecx, eax"
            or rows[15].op_str != "eax, 3"
            or rows[16].op_str != "ecx, 2"
            or rows[18].op_str != "eax, eax"
            or rows[20].op_str != "ecx, eax"
            or rows[22].op_str != "eax, edx"
        ):
            return False
        return True

    def _overlap_safe_copy_function(self, function_entry: int) -> bool:
        """Recognize the audited address-independent runtime memmove body."""
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        rows = [
            self._owned_decoded(address)
            for address in sorted(self.instructions)
            if function_entry <= address < following_entry
            and self._reachable_within_function(
                function_entry, address, function_entry, following_entry
            )
        ]
        expected = bytes.fromhex(
            "8b54240456578b4424148b74241089d731c939f7772b3d100000007c1e"
            "29f981e103000000740429c8f3a489c12503000000c1e902f3a585c074"
            "4689c1f3a4eb40fd8d7406ff8d7c07ff3d100000007c2b8d4ffd81e103"
            "000000740429c8f3a483ee0383ef0389c12503000000c1e902f3a585c0"
            "740a83c60383c70389c1f3a4fc89d05f5ec3"
        )
        return b"".join(bytes(row.bytes) for row in rows) == expected

    def _copied_metadata_tags(
        self,
        resolver_entry: int,
        source_bases: tuple[int, ...],
        tag_offset: int,
    ) -> tuple[frozenset[int], str] | None:
        following_entry = min(
            (row for row in self.function_addresses if row > resolver_entry),
            default=0x1_0000_0000,
        )
        callback_calls = []
        for address in sorted(self.instructions):
            if not resolver_entry <= address < following_entry:
                continue
            decoded = self._owned_decoded(address)
            if not decoded.group(CS_GRP_CALL) or len(decoded.operands) != 1:
                continue
            target_operand = decoded.operands[0]
            if target_operand.type != X86_OP_REG:
                continue
            target_definitions = self._register_definitions_across_blocks(
                address,
                self._register_family(target_operand.reg),
                resolver_entry,
            )
            if not target_definitions or len(target_definitions) != 1:
                continue
            target_load = self._owned_decoded(next(iter(target_definitions)))
            if (
                target_load.id != X86_INS_MOV
                or target_load.operands[1].type != X86_OP_MEM
                or target_load.operands[1].mem.disp != 4
                or target_load.operands[1].mem.base == X86_REG_INVALID
            ):
                continue
            table_family = self._register_family(
                target_load.operands[1].mem.base
            )
            table_definitions = self._register_definitions_across_blocks(
                target_load.address, table_family, resolver_entry
            )
            if not table_definitions or len(table_definitions) != 1:
                continue
            table_load = self._owned_decoded(next(iter(table_definitions)))
            if (
                table_load.id != X86_INS_MOV
                or table_load.operands[1].type != X86_OP_MEM
                or table_load.operands[1].mem.disp != 0
                or table_load.operands[1].mem.base == X86_REG_INVALID
                or self._register_argument_index_across_blocks(
                    table_load.address,
                    self._register_family(table_load.operands[1].mem.base),
                    resolver_entry,
                )
                != 0
                or self._dominating_nonzero_guard(
                    address, target_operand, resolver_entry
                )
                is None
            ):
                continue
            callback_calls.append(address)
        if len(callback_calls) != 1:
            return None
        callback_address = callback_calls[0]
        out_offsets = []
        for argument_index in (0, 1):
            pushed = self._pushed_call_argument(callback_address, argument_index)
            if pushed is None or pushed[2] != resolver_entry:
                return None
            offset = self._stack_pointer_logical_offset(
                pushed[0].address, pushed[1], resolver_entry
            )
            if offset is None:
                return None
            out_offsets.append(offset)
        if out_offsets[0] == out_offsets[1]:
            return None

        relocation_types: dict[int, list[int]] = {}
        for relocation in self.image.relocations:
            relocation_types.setdefault(relocation.va, []).append(relocation.type)
        tags = set()
        provider_details = []
        for base in source_bases:
            slot = base + 4
            if relocation_types.get(slot) != [3]:
                return None
            try:
                provider = int.from_bytes(
                    _read_loader_initialized(self.image, slot, 4), "little"
                )
            except ValueError:
                return None
            if not _is_executable_span(self.image, provider, 1):
                return None
            provider_end = min(
                (
                    row
                    for row in self.function_addresses
                    if row > provider
                ),
                default=0x1_0000_0000,
            )
            provider_returns = [
                self._owned_decoded(address)
                for address in sorted(self.instructions)
                if provider <= address < provider_end
                and self._owned_decoded(address).group(CS_GRP_RET)
                and self._reachable_within_function(
                    provider, address, provider, provider_end
                )
            ]
            if not provider_returns or any(
                len(row.operands) != 1
                or row.operands[0].type != X86_OP_IMM
                or row.operands[0].imm != 8
                for row in provider_returns
            ):
                return None
            pointer_output = self._fixed_output_argument_values(provider, 0)
            length_output = self._fixed_output_argument_values(provider, 1)
            if (
                pointer_output is None
                or length_output is None
                or pointer_output[0] != 0
                or length_output[0] != 0
                or len(pointer_output[1]) != 1
                or not length_output[1]
            ):
                return None
            pointer = next(iter(pointer_output[1]))
            if (
                not self._relocated_immediate_in_function(provider, pointer)
                or any(length < tag_offset + 4 for length in length_output[1])
                or not _is_mapped_span(self.image, pointer + tag_offset, 4)
                or _is_executable_span(self.image, pointer + tag_offset, 4)
            ):
                return None
            tag = int.from_bytes(
                _read_loader_initialized(
                    self.image, pointer + tag_offset, 4
                ),
                "little",
            )
            tags.add(tag)
            provider_details.append(
                f"source-table={base:#x};provider={provider:#x};"
                f"metadata={pointer:#x};lengths="
                + ",".join(f"{value:#x}" for value in sorted(length_output[1]))
                + f";tag={tag:#x}"
            )

        returns = [
            self._owned_decoded(address)
            for address in sorted(self.instructions)
            if resolver_entry <= address < following_entry
            and self._owned_decoded(address).group(CS_GRP_RET)
            and self._reachable_within_function(
                resolver_entry, address, resolver_entry, following_entry
            )
        ]
        if not returns:
            return None
        success_kinds = set()
        for returned in returns:
            definitions = self._register_definitions_across_blocks(
                returned.address, "eax", resolver_entry
            )
            if not definitions:
                cursor = returned.address
                zero_definition = None
                for _ in range(4):
                    previous = self._previous_instruction(cursor)
                    if previous is None or previous.address < resolver_entry:
                        break
                    previous_decoded = self._owned_decoded(previous.address)
                    if (
                        previous_decoded.mnemonic == "xor"
                        and len(previous_decoded.operands) == 2
                        and all(
                            row.type == X86_OP_REG
                            and self._register_family(row.reg) == "eax"
                            for row in previous_decoded.operands
                        )
                    ):
                        zero_definition = previous.address
                        break
                    if previous_decoded.group(CS_GRP_CALL) or any(
                        self._register_family(row) == "eax"
                        for row in previous_decoded.regs_write
                    ):
                        break
                    cursor = previous.address
                if zero_definition is None:
                    return None
                definitions = frozenset({zero_definition})
            for definition_address in definitions:
                definition = self._owned_decoded(definition_address)
                if (
                    definition.mnemonic == "xor"
                    and len(definition.operands) == 2
                    and all(row.type == X86_OP_REG for row in definition.operands)
                    and all(
                        self._register_family(row.reg) == "eax"
                        for row in definition.operands
                    )
                ):
                    continue
                if (
                    definition.id == X86_INS_MOV
                    and definition.operands[0].type == X86_OP_REG
                    and self._register_family(definition.operands[0].reg) == "eax"
                    and definition.operands[1].type == X86_OP_MEM
                    and self._stack_operand_logical_offset(
                        definition.address,
                        definition.operands[1],
                        resolver_entry,
                    )
                    == out_offsets[0]
                ):
                    success_kinds.add("direct-outparam")
                    continue
                if (
                    definition.id == X86_INS_MOV
                    and definition.operands[0].type == X86_OP_REG
                    and self._register_family(definition.operands[0].reg) == "eax"
                    and definition.operands[1].type == X86_OP_IMM
                ):
                    destination = definition.operands[1].imm & 0xFFFF_FFFF
                    copy_calls = []
                    for call in self.direct_calls:
                        if not resolver_entry <= call.address < definition.address:
                            continue
                        arguments = [
                            self._pushed_call_argument(call.address, index)
                            for index in range(3)
                        ]
                        if any(row is None for row in arguments):
                            continue
                        assert all(row is not None for row in arguments)
                        dest, source, length = arguments
                        if (
                            dest[1].type == X86_OP_IMM
                            and dest[1].imm & 0xFFFF_FFFF == destination
                            and self._stack_value_logical_offset(
                                source[0].address, source[1], resolver_entry
                            )
                            == out_offsets[0]
                            and self._stack_value_logical_offset(
                                length[0].address, length[1], resolver_entry
                            )
                            == out_offsets[1]
                            and self._memcpy_like_function(call.target)
                            and not self._reachable_within_function(
                                resolver_entry,
                                definition.address,
                                resolver_entry,
                                following_entry,
                                excluded=call.address,
                            )
                        ):
                            copy_calls.append(call.address)
                    if (
                        len(copy_calls) == 1
                        and self._relocated_immediate_in_function(
                            resolver_entry, destination
                        )
                    ):
                        success_kinds.add("fixed-memcpy")
                        continue
                return None
        if not success_kinds:
            return None
        return frozenset(tags), (
            f"resolver={resolver_entry:#x};slot=1;tag-offset={tag_offset:+#x};"
            f"return-shape={','.join(sorted(success_kinds))};"
            + "|".join(provider_details)
        )

    def _copied_tag_stamper(
        self,
        stamper_entry: int,
        object_field: int,
        validator: tuple[int, int],
        source_bases: tuple[int, ...],
    ) -> tuple[frozenset[int], str] | None:
        following_entry = min(
            (row for row in self.function_addresses if row > stamper_entry),
            default=0x1_0000_0000,
        )
        stores = []
        for row in self.dynamic_field_writes.get(validator[0], ()):
            if not stamper_entry <= row.instruction_address < following_entry:
                continue
            decoded = self._owned_decoded(row.instruction_address)
            if (
                decoded.id == X86_INS_MOV
                and len(decoded.operands) == 2
                and decoded.operands[0].type == X86_OP_MEM
                and decoded.operands[0].size == 4
                and decoded.operands[1].type == X86_OP_REG
            ):
                stores.append(decoded)
        if len(stores) != 1:
            return None
        store = stores[0]
        object_family = self._register_family(store.operands[0].mem.base)
        object_definitions = self._register_definitions_across_blocks(
            store.address, object_family, stamper_entry
        )
        if not object_definitions:
            return None
        for definition_address in object_definitions:
            definition = self._owned_decoded(definition_address)
            if (
                definition.id != X86_INS_MOV
                or definition.operands[1].type != X86_OP_MEM
                or definition.operands[1].mem.disp != object_field
                or definition.operands[1].mem.base == X86_REG_INVALID
                or self._register_argument_origin_index(
                    definition.address,
                    self._register_family(definition.operands[1].mem.base),
                    stamper_entry,
                )
                != 0
            ):
                return None
        tag_family = self._register_family(store.operands[1].reg)
        tag_definitions = self._register_definitions_across_blocks(
            store.address, tag_family, stamper_entry
        )
        if not tag_definitions or len(tag_definitions) != 1:
            return None
        tag_load = self._owned_decoded(next(iter(tag_definitions)))
        if (
            tag_load.id != X86_INS_MOV
            or tag_load.operands[0].type != X86_OP_REG
            or tag_load.operands[1].type != X86_OP_MEM
            or tag_load.operands[1].size != 4
            or tag_load.operands[1].mem.base == X86_REG_INVALID
        ):
            return None
        resolver_call_instruction = self._previous_instruction(tag_load.address)
        if resolver_call_instruction is None:
            return None
        resolver_call = next(
            (
                row
                for row in self.direct_calls
                if row.address == resolver_call_instruction.address
            ),
            None,
        )
        if resolver_call is None:
            return None
        pushed_record = self._pushed_call_argument(resolver_call.address, 0)
        if (
            pushed_record is None
            or pushed_record[1].type != X86_OP_REG
            or self._register_argument_index_across_blocks(
                pushed_record[0].address,
                self._register_family(pushed_record[1].reg),
                stamper_entry,
            )
            != 0
        ):
            return None
        resolved = self._copied_metadata_tags(
            resolver_call.target,
            source_bases,
            tag_load.operands[1].mem.disp,
        )
        if resolved is None or validator[1] in resolved[0]:
            return None
        returns = [
            address
            for address in sorted(self.instructions)
            if stamper_entry <= address < following_entry
            and self._owned_decoded(address).group(CS_GRP_RET)
            and self._reachable_within_function(
                stamper_entry, address, stamper_entry, following_entry
            )
        ]
        if not returns or any(
            self._reachable_within_function(
                stamper_entry,
                return_address,
                stamper_entry,
                following_entry,
                excluded=store.address,
            )
            for return_address in returns
        ):
            return None
        return resolved[0], (
            f"tag-stamper={stamper_entry:#x};store={store.address:#x};"
            f"object-field={object_field:+#x};{resolved[1]}"
        )

    def _closed_copied_slot_zero_tag_origin(
        self,
        function_entry: int,
        argument_index: int,
        validator: tuple[int, int],
    ) -> _ClosedObjectOrigin | None:
        if argument_index != 0:
            return None
        source_bases = self._copied_slot_zero_source_bases(function_entry)
        if source_bases is None:
            return None
        relations = []
        for call_address, consumer_entry, record_argument, _guard in (
            self._guarded_slot_zero_descriptor_consumers()
        ):
            pushed = self._pushed_call_argument(call_address, 0)
            if pushed is None or pushed[1].type != X86_OP_REG:
                return None
            object_argument = self._register_argument_index_across_blocks(
                pushed[0].address,
                self._register_family(pushed[1].reg),
                consumer_entry,
            )
            if object_argument is None:
                return None
            if not self._direct_call_domain_is_closed(consumer_entry):
                return None
            consumer_calls = sorted(
                row.address
                for row in self.direct_calls
                if row.target == consumer_entry
            )
            for consumer_call in consumer_calls:
                relation = self._copied_record_object_relation(
                    consumer_call, record_argument, object_argument
                )
                if relation is None:
                    return None
                relations.append(relation)
        if not relations or len({row[2] for row in relations}) != 1:
            return None
        object_field = relations[0][2]
        stamper_targets: set[int] | None = None
        stamper_details: dict[int, tuple[frozenset[int], str]] = {}
        for wrapper_entry, wrapper_record_argument, _field in relations:
            if not self._direct_call_domain_is_closed(wrapper_entry):
                return None
            following_entry = min(
                (row for row in self.function_addresses if row > wrapper_entry),
                default=0x1_0000_0000,
            )
            for wrapper_call in sorted(
                (
                    row
                    for row in self.direct_calls
                    if row.target == wrapper_entry
                ),
                key=_call_key,
            ):
                wrapper_record = self._pushed_call_argument(
                    wrapper_call.address, wrapper_record_argument
                )
                if wrapper_record is None:
                    return None
                candidates = set()
                for candidate in self.direct_calls:
                    if not (
                        wrapper_record[2] <= candidate.address < wrapper_call.address
                    ):
                        continue
                    candidate_record = self._pushed_call_argument(
                        candidate.address, 0
                    )
                    if (
                        candidate_record is None
                        or candidate_record[2] != wrapper_record[2]
                        or not self._same_closed_caller_value(
                            candidate_record[0].address,
                            candidate_record[1],
                            wrapper_record[0].address,
                            wrapper_record[1],
                            wrapper_record[2],
                        )
                        or self._reachable_within_function(
                            wrapper_record[2],
                            wrapper_call.address,
                            wrapper_record[2],
                            following_entry,
                            excluded=candidate.address,
                        )
                    ):
                        continue
                    if candidate.target not in stamper_details:
                        proof = self._copied_tag_stamper(
                            candidate.target,
                            object_field,
                            validator,
                            source_bases,
                        )
                        if proof is not None:
                            stamper_details[candidate.target] = proof
                    if candidate.target in stamper_details:
                        candidates.add(candidate.target)
                if not candidates:
                    return None
                stamper_targets = (
                    candidates
                    if stamper_targets is None
                    else stamper_targets & candidates
                )
        if stamper_targets is None or len(stamper_targets) != 1:
            return None
        stamper = next(iter(stamper_targets))
        tags, detail = stamper_details[stamper]
        return _ClosedObjectOrigin(
            False,
            tags,
            "copied-slot-zero-tag-domain;"
            + "rejected-tag="
            + ",".join(f"{tag:#x}" for tag in sorted(tags))
            + ";"
            + detail,
        )

    def _closed_object_origin_argument(
        self,
        function_entry: int,
        argument_index: int,
        constructor_entry: int,
        descriptor_field: int,
        validator: tuple[int, int],
        visited: frozenset[tuple[int, str]],
    ) -> _ClosedObjectOrigin | None:
        copied_tag_origin = self._closed_copied_slot_zero_tag_origin(
            function_entry, argument_index, validator
        )
        if copied_tag_origin is not None:
            return copied_tag_origin
        key = (
            function_entry,
            f"object-argument:{argument_index}:{constructor_entry:#x}",
        )
        if key in visited:
            return None
        callers = self._incoming_call_sites(function_entry)
        if not callers:
            return None
        has_object = False
        rejected_tags: set[int] = set()
        details = []
        for call_address in callers:
            pushed = self._pushed_call_argument(call_address, argument_index)
            if pushed is None:
                return None
            origin = self._closed_object_origin_operand(
                pushed[0].address,
                pushed[1],
                pushed[2],
                constructor_entry,
                descriptor_field,
                validator,
                visited | {key},
            )
            if origin is None:
                return None
            has_object |= origin.has_target_constructor
            rejected_tags.update(origin.rejected_tags)
            details.append(f"caller={call_address:#x}:{origin.detail}")
        return _ClosedObjectOrigin(
            has_object,
            frozenset(rejected_tags),
            "|".join(details),
        )

    def _closed_pointer_field_origin(
        self,
        address: int,
        operand,
        function_entry: int,
        field: int,
        constructor_entry: int,
        descriptor_field: int,
        validator: tuple[int, int],
        visited: frozenset[tuple[int, str]],
    ) -> _ClosedObjectOrigin | None:
        if operand.type == X86_OP_REG:
            return self._closed_object_field_origin(
                address,
                self._register_family(operand.reg),
                function_entry,
                field,
                constructor_entry,
                descriptor_field,
                validator,
                visited,
            )
        if (
            operand.type == X86_OP_MEM
            and operand.mem.segment == X86_REG_INVALID
            and operand.mem.base == X86_REG_INVALID
            and operand.mem.index == X86_REG_INVALID
        ):
            slot = operand.mem.disp & 0xFFFF_FFFF
            key = (
                slot,
                f"pointer-global-field:{field:+#x}:{constructor_entry:#x}",
            )
            if key in visited:
                return None
            try:
                initial = int.from_bytes(
                    _read_loader_initialized(self.image, slot, 4), "little"
                )
            except ValueError:
                return None
            origins = []
            if initial:
                if not any(
                    row.type == 3 and row.va == slot
                    for row in self.image.relocations
                ):
                    return None
                origin = self._closed_global_object_origin(
                    (initial + field) & 0xFFFF_FFFF,
                    constructor_entry,
                    descriptor_field,
                    validator,
                    visited | {key},
                )
                if origin is None:
                    return None
                origins.append(origin)
            for write in sorted(
                self.global_slot_writes.get(slot, ()),
                key=lambda row: row.instruction_address,
            ):
                write_decoded = self._owned_decoded(
                    write.instruction_address
                )
                if (
                    write_decoded.id != X86_INS_MOV
                    or len(write_decoded.operands) != 2
                ):
                    return None
                if write.value is not None:
                    if write.value == 0:
                        continue
                    if (
                        write_decoded.operands[1].type != X86_OP_IMM
                        or not any(
                            row.type == 3
                            and row.va
                            == write_decoded.address
                            + write_decoded.imm_offset
                            for row in self.image.relocations
                        )
                    ):
                        return None
                    origin = self._closed_global_object_origin(
                        (write.value + field) & 0xFFFF_FFFF,
                        constructor_entry,
                        descriptor_field,
                        validator,
                        visited | {key},
                    )
                else:
                    writer_entry = self._registrar_function_entry(
                        write.instruction_address
                    )
                    if writer_entry is None:
                        return None
                    origin = self._closed_pointer_field_origin(
                        write.instruction_address,
                        write_decoded.operands[1],
                        writer_entry,
                        field,
                        constructor_entry,
                        descriptor_field,
                        validator,
                        visited | {key},
                    )
                if origin is None:
                    return None
                origins.append(origin)
            if not origins:
                return None
            return _ClosedObjectOrigin(
                any(row.has_target_constructor for row in origins),
                frozenset().union(
                    *(row.rejected_tags for row in origins)
                ),
                f"global-slot={slot:#x};pointer-field={field:+#x};"
                + "|".join(row.detail for row in origins),
            )
        argument_index = self._stack_argument_index_at(
            address, operand, function_entry
        )
        if argument_index is None:
            return None
        key = (
            function_entry,
            f"pointer-field-argument:{argument_index}:{field:+#x}",
        )
        if key in visited:
            return None
        callers = self._incoming_call_sites(function_entry)
        if not callers:
            return None
        has_object = False
        rejected_tags: set[int] = set()
        details = []
        for call_address in callers:
            pushed = self._pushed_call_argument(call_address, argument_index)
            if pushed is None:
                return None
            origin = self._closed_pointer_field_origin(
                pushed[0].address,
                pushed[1],
                pushed[2],
                field,
                constructor_entry,
                descriptor_field,
                validator,
                visited | {key},
            )
            if origin is None:
                return None
            has_object |= origin.has_target_constructor
            rejected_tags.update(origin.rejected_tags)
            details.append(f"caller={call_address:#x}:{origin.detail}")
        return _ClosedObjectOrigin(
            has_object,
            frozenset(rejected_tags),
            "|".join(details),
        )

    def _closed_object_field_origin(
        self,
        address: int,
        base_family: str,
        function_entry: int,
        field: int,
        constructor_entry: int,
        descriptor_field: int,
        validator: tuple[int, int],
        visited: frozenset[tuple[int, str]],
    ) -> _ClosedObjectOrigin | None:
        key = (address, f"object-field:{base_family}:{field:+#x}")
        if key in visited:
            return None
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        writes = []
        for row in sorted(
            self.dynamic_field_writes.get(field, ()),
            key=lambda item: item.instruction_address,
        ):
            if not (
                function_entry <= row.instruction_address < following_entry
            ):
                continue
            decoded = self._owned_decoded(row.instruction_address)
            if (
                decoded.id != X86_INS_MOV
                or len(decoded.operands) != 2
                or decoded.operands[0].type != X86_OP_MEM
                or decoded.operands[0].mem.base == X86_REG_INVALID
                or decoded.operands[0].mem.index != X86_REG_INVALID
                or self._register_family(decoded.operands[0].mem.base)
                != base_family
                or not self._reachable_within_function(
                    function_entry,
                    row.instruction_address,
                    function_entry,
                    following_entry,
                )
                or not self._reachable_within_function(
                    row.instruction_address,
                    address,
                    function_entry,
                    following_entry,
                )
            ):
                continue
            origin = self._closed_object_origin_operand(
                row.instruction_address,
                decoded.operands[1],
                function_entry,
                constructor_entry,
                descriptor_field,
                validator,
                visited | {key},
            )
            if origin is None:
                return None
            writes.append((row.instruction_address, origin))
        dominating_object_write = next(
            (
                (write_address, origin)
                for write_address, origin in writes
                if origin.has_target_constructor
                and not self._reachable_within_function(
                    function_entry,
                    address,
                    function_entry,
                    following_entry,
                    excluded=write_address,
                )
            ),
            None,
        )
        if dominating_object_write is not None:
            return _ClosedObjectOrigin(
                True,
                dominating_object_write[1].rejected_tags,
                f"field={field:+#x};store="
                f"{dominating_object_write[0]:#x};"
                f"{dominating_object_write[1].detail}",
            )

        argument_index = self._register_argument_index_across_blocks(
            address, base_family, function_entry
        )
        incoming = None
        if argument_index is not None:
            callers = self._incoming_call_sites(function_entry)
            if not callers:
                return None
            origins = []
            for call_address in callers:
                pushed = self._pushed_call_argument(
                    call_address, argument_index
                )
                if pushed is None:
                    return None
                origin = self._closed_pointer_field_origin(
                    pushed[0].address,
                    pushed[1],
                    pushed[2],
                    field,
                    constructor_entry,
                    descriptor_field,
                    validator,
                    visited | {key},
                )
                if origin is None:
                    return None
                origins.append(origin)
            incoming = _ClosedObjectOrigin(
                any(row.has_target_constructor for row in origins),
                frozenset().union(
                    *(row.rejected_tags for row in origins)
                ),
                "|".join(row.detail for row in origins),
            )
        if incoming is None:
            definitions = self._register_definitions_across_blocks(
                address, base_family, function_entry
            )
            if not definitions:
                return None
            definition_origins = []
            for definition_address in sorted(definitions):
                definition = self._owned_decoded(definition_address)
                if (
                    definition.id != X86_INS_MOV
                    or len(definition.operands) != 2
                    or definition.operands[0].type != X86_OP_REG
                ):
                    return None
                origin = self._closed_pointer_field_origin(
                    definition_address,
                    definition.operands[1],
                    function_entry,
                    field,
                    constructor_entry,
                    descriptor_field,
                    validator,
                    visited | {key},
                )
                if origin is None:
                    return None
                definition_origins.append(origin)
            incoming = _ClosedObjectOrigin(
                any(
                    row.has_target_constructor
                    for row in definition_origins
                ),
                frozenset().union(
                    *(row.rejected_tags for row in definition_origins)
                ),
                "|".join(row.detail for row in definition_origins),
            )
        if (
            any(
                not origin.has_target_constructor
                for _, origin in writes
            )
            and incoming is None
        ):
            return None
        return incoming

    def _fixed_constructor_tag(
        self, function_entry: int, tag_field: int
    ) -> int | None:
        """Return one immediate tag that dominates every constructor return."""
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        overlapping_writes = []
        for displacement, rows in self.dynamic_field_writes.items():
            for row in rows:
                if not (
                    displacement < tag_field + 4
                    and tag_field < displacement + row.width
                    and function_entry
                    <= row.instruction_address
                    < following_entry
                ):
                    continue
                decoded = self._owned_decoded(row.instruction_address)
                if self._is_stack_backed_memory(
                    row.instruction_address, decoded.operands[0], function_entry
                ):
                    continue
                overlapping_writes.append((row, decoded))
        if len(overlapping_writes) != 1:
            return None
        writer, decoded = overlapping_writes[0]
        if (
            writer.width != 4
            or writer.value is None
            or decoded.id != X86_INS_MOV
            or len(decoded.operands) != 2
            or decoded.operands[0].type != X86_OP_MEM
            or decoded.operands[0].size != 4
            or decoded.operands[0].mem.segment != X86_REG_INVALID
            or decoded.operands[0].mem.index != X86_REG_INVALID
            or decoded.operands[0].mem.base == X86_REG_INVALID
            or self._register_family(decoded.operands[0].mem.base) != "ecx"
            or decoded.operands[0].mem.disp != tag_field
            or decoded.operands[1].type != X86_OP_IMM
            or decoded.imm_size != 4
            or not self._reachable_within_function(
                function_entry,
                writer.instruction_address,
                function_entry,
                following_entry,
            )
        ):
            return None
        returns = [
            address
            for address in sorted(self.instructions)
            if function_entry <= address < following_entry
            and self._owned_decoded(address).group(CS_GRP_RET)
            and self._reachable_within_function(
                function_entry,
                address,
                function_entry,
                following_entry,
            )
        ]
        if not returns or any(
            self._reachable_within_function(
                function_entry,
                return_address,
                function_entry,
                following_entry,
                excluded=writer.instruction_address,
            )
            for return_address in returns
        ):
            return None
        if any(
            row.kind in {"indirect-flow", "computed-flow-blocker"}
            and function_entry <= row.address < following_entry
            for row in self.diagnostics
        ):
            return None
        return writer.value

    def _closed_object_origin_operand(
        self,
        address: int,
        operand,
        function_entry: int,
        constructor_entry: int,
        descriptor_field: int,
        validator: tuple[int, int],
        visited: frozenset[tuple[int, str]],
    ) -> _ClosedObjectOrigin | None:
        key = (address, f"object-operand:{constructor_entry:#x}")
        if key in visited:
            return None
        if operand.type == X86_OP_IMM:
            if operand.imm & 0xFFFF_FFFF == 0:
                return _ClosedObjectOrigin(
                    False, frozenset(), "nullable-zero"
                )
            return None
        if operand.type == X86_OP_REG:
            family = self._register_family(operand.reg)
            constructor_calls = [
                row
                for row in self.direct_calls
                if row.target == constructor_entry
                and function_entry <= row.address < address
                and (
                    fresh := self._fresh_constructor_receiver(
                        row, descriptor_field
                    )
                )
                is not None
                and fresh[0] == family
            ]
            if len(constructor_calls) == 1:
                constructor_call = constructor_calls[0]
                if not any(
                    any(
                        self._register_family(register) == family
                        for register in self._owned_decoded(row).regs_write
                    )
                    or any(
                        value.type == X86_OP_REG
                        and value.access & CS_AC_WRITE
                        and self._register_family(value.reg) == family
                        for value in self._owned_decoded(row).operands
                    )
                    for row in sorted(self.instructions)
                    if constructor_call.address < row < address
                ):
                    return _ClosedObjectOrigin(
                        True,
                        frozenset(),
                        f"fresh-constructor={constructor_entry:#x};"
                        f"call={constructor_call.address:#x}",
                    )
            alternate_calls = []
            for row in self.direct_calls:
                if (
                    row.target == constructor_entry
                    or not function_entry <= row.address < address
                ):
                    continue
                fresh = self._fresh_constructor_receiver(
                    row, descriptor_field
                )
                if fresh is None or fresh[0] != family:
                    continue
                if any(
                    any(
                        self._register_family(register) == family
                        for register in self._owned_decoded(candidate).regs_write
                    )
                    or any(
                        value.type == X86_OP_REG
                        and value.access & CS_AC_WRITE
                        and self._register_family(value.reg) == family
                        for value in self._owned_decoded(candidate).operands
                    )
                    for candidate in sorted(self.instructions)
                    if row.address < candidate < address
                ):
                    continue
                alternate_calls.append(row)
            if len(alternate_calls) == 1:
                alternate_call = alternate_calls[0]
                alternate_tag = self._fixed_constructor_tag(
                    alternate_call.target, validator[0]
                )
                if alternate_tag == validator[1]:
                    return None
                if alternate_tag is not None:
                    return _ClosedObjectOrigin(
                        False,
                        frozenset({alternate_tag}),
                        f"fresh-constructor={alternate_call.target:#x};"
                        f"call={alternate_call.address:#x};"
                        f"rejected-tag={alternate_tag:#x}",
                    )
            argument_index = self._register_argument_index_across_blocks(
                address, family, function_entry
            )
            if argument_index is not None:
                return self._closed_object_origin_argument(
                    function_entry,
                    argument_index,
                    constructor_entry,
                    descriptor_field,
                    validator,
                    visited | {key},
                )
            definitions = self._register_definitions_across_blocks(
                address, family, function_entry
            )
            if not definitions:
                return None
            origins = []
            for definition_address in sorted(definitions):
                definition = self._owned_decoded(definition_address)
                if (
                    definition.id != X86_INS_MOV
                    or len(definition.operands) != 2
                    or definition.operands[0].type != X86_OP_REG
                ):
                    return None
                origin = self._closed_object_origin_operand(
                    definition_address,
                    definition.operands[1],
                    function_entry,
                    constructor_entry,
                    descriptor_field,
                    validator,
                    visited | {key},
                )
                if origin is None:
                    return None
                origins.append(origin)
            return _ClosedObjectOrigin(
                any(row.has_target_constructor for row in origins),
                frozenset().union(
                    *(row.rejected_tags for row in origins)
                ),
                "|".join(row.detail for row in origins),
            )
        if operand.type != X86_OP_MEM:
            return None
        memory = operand.mem
        if (
            memory.segment != X86_REG_INVALID
            or memory.index != X86_REG_INVALID
        ):
            return None
        if memory.base == X86_REG_INVALID:
            slot = memory.disp & 0xFFFF_FFFF
            return self._closed_global_object_origin(
                slot,
                constructor_entry,
                descriptor_field,
                validator,
                visited | {key},
            )
        argument_index = self._stack_argument_index_at(
            address, operand, function_entry
        )
        if argument_index is not None:
            return self._closed_object_origin_argument(
                function_entry,
                argument_index,
                constructor_entry,
                descriptor_field,
                validator,
                visited | {key},
            )
        return self._closed_object_field_origin(
            address,
            self._register_family(memory.base),
            function_entry,
            memory.disp,
            constructor_entry,
            descriptor_field,
            validator,
            visited | {key},
        )

    def _closed_global_object_origin(
        self,
        slot: int,
        constructor_entry: int,
        descriptor_field: int,
        validator: tuple[int, int],
        visited: frozenset[tuple[int, str]],
    ) -> _ClosedObjectOrigin | None:
        """Trace a loader-zero global slot's complete object-pointer domain."""
        key = (slot, f"global-object:{constructor_entry:#x}")
        if key in visited:
            return None
        try:
            initial = int.from_bytes(
                _read_loader_initialized(self.image, slot, 4), "little"
            )
        except ValueError:
            return None
        if initial != 0:
            return None
        writes = sorted(
            self.global_slot_writes.get(slot, ()),
            key=lambda row: row.instruction_address,
        )
        if not writes:
            return None
        origins = []
        for write in writes:
            write_decoded = self._owned_decoded(write.instruction_address)
            if (
                write_decoded.id != X86_INS_MOV
                or len(write_decoded.operands) != 2
            ):
                return None
            writer_entry = self._registrar_function_entry(
                write.instruction_address
            )
            if writer_entry is None:
                return None
            origin = self._closed_object_origin_operand(
                write.instruction_address,
                write_decoded.operands[1],
                writer_entry,
                constructor_entry,
                descriptor_field,
                validator,
                visited | {key},
            )
            if origin is None:
                return None
            origins.append(origin)
        return _ClosedObjectOrigin(
            any(row.has_target_constructor for row in origins),
            frozenset().union(*(row.rejected_tags for row in origins)),
            f"global-slot={slot:#x};"
            + "|".join(row.detail for row in origins),
        )

    def _is_stack_backed_memory(
        self, address: int, operand, function_entry: int
    ) -> bool:
        if (
            operand.type != X86_OP_MEM
            or operand.mem.base == X86_REG_INVALID
        ):
            return False
        family = self._register_family(operand.mem.base)
        if family not in {"esp", "ebp"}:
            return False
        if family == "esp":
            return True
        stack_states = self._function_stack_states(function_entry)
        if stack_states is None or address not in stack_states:
            return False
        _, bp_delta = stack_states[address]
        return bp_delta is not None

    def _recover_constructor_descriptor_target(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        """Close a validated constructor-assigned descriptor callback."""
        if (
            flow_kind != "call"
            or len(decoded.operands) != 1
            or decoded.operands[0].type != X86_OP_MEM
            or decoded.operands[0].size != 4
            or decoded.operands[0].mem.segment != X86_REG_INVALID
            or decoded.operands[0].mem.index != X86_REG_INVALID
            or decoded.operands[0].mem.base == X86_REG_INVALID
        ):
            return False
        descriptor_family = self._register_family(
            decoded.operands[0].mem.base
        )
        function_entry = self._registrar_function_entry(instruction.address)
        if function_entry is None:
            return False
        definitions = self._register_definitions_across_blocks(
            instruction.address, descriptor_family, function_entry
        )
        if definitions is None or len(definitions) != 1:
            return False
        definition_address = next(iter(definitions))
        definition = self._owned_decoded(definition_address)
        if (
            definition.id != X86_INS_MOV
            or len(definition.operands) != 2
            or definition.operands[0].type != X86_OP_REG
            or definition.operands[1].type != X86_OP_MEM
            or definition.operands[1].size != 4
            or definition.operands[1].mem.segment != X86_REG_INVALID
            or definition.operands[1].mem.index != X86_REG_INVALID
            or definition.operands[1].mem.base == X86_REG_INVALID
        ):
            return False
        object_family = self._register_family(
            definition.operands[1].mem.base
        )
        descriptor_field = definition.operands[1].mem.disp
        following_entry = min(
            (row for row in self.function_addresses if row > function_entry),
            default=0x1_0000_0000,
        )
        validator_calls = []
        if object_family == "eax":
            for call in sorted(self.direct_calls, key=lambda row: row.address):
                if not (
                    function_entry <= call.address < definition.address
                    and self._strict_identity_validator(call.target)
                    is not None
                ):
                    continue
                call_instruction = self.instructions[call.address]
                fallthrough = call.address + call_instruction.size
                if (
                    not self._reachable_within_function(
                        fallthrough,
                        definition.address,
                        function_entry,
                        following_entry,
                    )
                    or self._reachable_within_function(
                        function_entry,
                        definition.address,
                        function_entry,
                        following_entry,
                        excluded=call.address,
                    )
                ):
                    continue
                clobbered = False
                for candidate_address in sorted(self.instructions):
                    if not (
                        function_entry
                        <= candidate_address
                        < following_entry
                        and candidate_address
                        not in {call.address, definition.address}
                    ):
                        continue
                    candidate = self._owned_decoded(candidate_address)
                    writes_object = (
                        candidate.group(CS_GRP_CALL)
                        or any(
                            self._register_family(row) == object_family
                            for row in candidate.regs_write
                        )
                        or any(
                            row.type == X86_OP_REG
                            and row.access & CS_AC_WRITE
                            and self._register_family(row.reg)
                            == object_family
                            for row in candidate.operands
                        )
                    )
                    if (
                        writes_object
                        and self._reachable_within_function(
                            fallthrough,
                            candidate_address,
                            function_entry,
                            following_entry,
                        )
                        and self._reachable_within_function(
                            candidate_address,
                            definition.address,
                            function_entry,
                            following_entry,
                        )
                    ):
                        clobbered = True
                        break
                if not clobbered:
                    validator_calls.append(call)
        if len(validator_calls) != 1:
            return False
        validator_call = validator_calls[0]
        validator = self._strict_identity_validator(validator_call.target)
        if validator is None:
            return False

        def block(detail: str) -> bool:
            self._computed_flow_blocker(
                instruction, "constructor descriptor provenance is open: " + detail
            )
            return True

        overlapping_writes = []
        for displacement, rows in self.dynamic_field_writes.items():
            for row in rows:
                if not (
                    displacement < descriptor_field + 4
                    and descriptor_field < displacement + row.width
                ):
                    continue
                writer_entry = self._registrar_function_entry(
                    row.instruction_address
                )
                if writer_entry is None:
                    continue
                writer_decoded = self._owned_decoded(
                    row.instruction_address
                )
                if self._is_stack_backed_memory(
                    row.instruction_address,
                    writer_decoded.operands[0],
                    writer_entry,
                ):
                    continue
                overlapping_writes.append(row)
        overlapping_writes = tuple(
            sorted(
                overlapping_writes,
                key=lambda row: row.instruction_address,
            )
        )
        if len(overlapping_writes) != 1:
            return block("descriptor field does not have one closed writer")
        writer = overlapping_writes[0]
        writer_decoded = self._owned_decoded(writer.instruction_address)
        if (
            writer.value is None
            or writer_decoded.id != X86_INS_MOV
            or len(writer_decoded.operands) != 2
            or writer_decoded.operands[1].type != X86_OP_IMM
            or writer_decoded.imm_size != 4
            or not any(
                row.type == 3
                and row.va
                == writer_decoded.address + writer_decoded.imm_offset
                for row in self.image.relocations
            )
        ):
            return block("descriptor writer is not one relocated immediate")
        constructor_entry = self._registrar_function_entry(
            writer.instruction_address
        )
        if constructor_entry is None:
            return block("descriptor writer has no constructor function")
        constructor_calls = tuple(
            sorted(
                (
                    row
                    for row in self.direct_calls
                    if row.target == constructor_entry
                ),
                key=lambda row: row.address,
            )
        )
        if not constructor_calls or any(
            self._fresh_constructor_receiver(row, descriptor_field) is None
            for row in constructor_calls
        ):
            return block("constructor caller domain is incomplete")
        validator_argument = self._pushed_call_argument(
            validator_call.address, 0
        )
        object_origin = (
            None
            if validator_argument is None
            else self._closed_object_origin_operand(
                validator_argument[0].address,
                validator_argument[1],
                validator_argument[2],
                constructor_entry,
                descriptor_field,
                validator,
                frozenset(),
            )
        )
        if object_origin is None:
            return block("consumer object-producer domain is incomplete")
        if not object_origin.has_target_constructor:
            self.diagnostics.add(
                OwnershipDiagnostic(
                    kind="proven-unreachable-control",
                    address=instruction.address,
                    detail=(
                        "identity validator rejects closed object domain: "
                        f"validator={validator_call.target:#x};"
                        f"tag-field={validator[0]:+#x};"
                        f"required-tag={validator[1]:#x};"
                        f"object-origin={object_origin.detail}"
                    ),
                )
            )
            return True
        target_slot = (
            writer.value + decoded.operands[0].mem.disp
        ) & 0xFFFF_FFFF
        try:
            raw_target = _read_loader_initialized(self.image, target_slot, 4)
        except ValueError:
            return block("descriptor callback slot is not loader initialized")
        target = int.from_bytes(raw_target, "little")
        if (
            not _is_executable_span(self.image, target, 1)
            or not any(
                row.type == 3 and row.va == target_slot
                for row in self.image.relocations
            )
        ):
            return block(
                "descriptor callback slot is not relocated executable control"
            )
        provenance = (
            f"identity-validator={validator_call.target:#x};"
            f"tag-field={validator[0]:+#x};tag={validator[1]:#x};"
            f"constructor={constructor_entry:#x};"
            f"descriptor-field={descriptor_field:+#x};"
            f"writer={writer.instruction_address:#x};"
            f"descriptor={writer.value:#x};slot={target_slot:#x};"
            f"object-origin={object_origin.detail}"
        )
        edge_kind = "indirect-call-constructor-descriptor"
        self.seed_records.add(
            SeedRecord(
                address=target,
                category="constructor-descriptor-callback",
                provenance_address=target_slot,
                provenance_bytes=raw_target.hex(),
                detail=provenance,
                is_function=True,
            )
        )
        self._add_edge(
            instruction.address,
            target,
            edge_kind,
            provenance=provenance,
        )
        self._record_finite_target(target)
        self._enqueue(target, is_function=True)
        self._record_fixpoint_update()
        return True

    def _recover_sentinel_callback_table(
        self, decoded, instruction: Instruction, *, flow_kind: str
    ) -> bool:
        if (
            flow_kind != "call"
            or len(decoded.operands) != 1
            or decoded.operands[0].type != X86_OP_REG
        ):
            return False
        target_family = self._register_family(decoded.operands[0].reg)
        function_entry = self._registrar_function_entry(instruction.address)
        if function_entry is None:
            return False
        following_entry = min(
            (
                row
                for row in self.function_addresses
                if row > function_entry
            ),
            default=0x1_0000_0000,
        )
        loads = []
        for address in sorted(self.instructions):
            if not function_entry <= address < following_entry:
                continue
            candidate = self._owned_decoded(address)
            if (
                candidate.id == X86_INS_MOV
                and len(candidate.operands) == 2
                and candidate.operands[0].type == X86_OP_REG
                and self._register_family(candidate.operands[0].reg)
                == target_family
                and candidate.operands[1].type == X86_OP_MEM
                and candidate.operands[1].size == 4
                and candidate.operands[1].mem.segment == X86_REG_INVALID
                and candidate.operands[1].mem.base != X86_REG_INVALID
                and candidate.operands[1].mem.index == X86_REG_INVALID
                and candidate.operands[1].mem.disp == 0
            ):
                loads.append(candidate)
        if len(loads) != 1:
            return False
        load = loads[0]
        base_family = self._register_family(load.operands[1].mem.base)
        initializers = []
        increments = []
        for address in sorted(self.instructions):
            if not function_entry <= address < following_entry:
                continue
            candidate = self._owned_decoded(address)
            if (
                candidate.id == X86_INS_MOV
                and len(candidate.operands) == 2
                and candidate.operands[0].type == X86_OP_REG
                and self._register_family(candidate.operands[0].reg)
                == base_family
                and candidate.operands[1].type == X86_OP_IMM
            ):
                initializers.append(candidate.operands[1].imm & 0xFFFF_FFFF)
            if (
                candidate.mnemonic == "add"
                and len(candidate.operands) == 2
                and candidate.operands[0].type == X86_OP_REG
                and self._register_family(candidate.operands[0].reg)
                == base_family
                and candidate.operands[1].type == X86_OP_IMM
                and candidate.operands[1].imm & 0xFFFF_FFFF == 4
            ):
                increments.append(candidate.address)
        if len(initializers) != 1 or len(increments) != 1:
            return False
        table_base = initializers[0]
        entries = []
        entry_rows = []
        for index in range(self.limits.max_jump_table_entries):
            entry_address = table_base + index * 4
            try:
                raw = _read_loader_initialized(self.image, entry_address, 4)
            except ValueError:
                return False
            target = int.from_bytes(raw, "little")
            if target == 0:
                sentinel = entry_address
                break
            if (
                not _is_executable_span(self.image, target, 1)
                or not any(
                    row.type == 3 and row.va == entry_address
                    for row in self.image.relocations
                )
            ):
                return False
            entries.append(target)
            entry_rows.append((entry_address, raw, target))
        else:
            self._check_count(
                "max_jump_table_entries", self.limits.max_jump_table_entries
            )
            return False
        if not entries:
            section = next(
                (
                    row
                    for row in self.image.sections
                    if row.name == ".CRT"
                    and row.va <= sentinel < row.va + row.virt_size
                ),
                None,
            )
            if (
                section is None
                or self.global_slot_writes.get(sentinel)
                or any(
                    row.type == 3 and row.va == sentinel
                    for row in self.image.relocations
                )
            ):
                return False
            provenance = (
                f"empty .CRT sentinel={sentinel:#x};"
                f"section={section.va:#x}-{section.va + section.virt_size:#x};"
                f"load={load.address:#x};increment={increments[0]:#x}"
            )
            self.diagnostics.add(
                OwnershipDiagnostic(
                    kind="proven-unreachable-control",
                    address=instruction.address,
                    detail=provenance,
                )
            )
            self.data_evidence.add(
                _DataEvidence(
                    start=sentinel,
                    end=sentinel + 4,
                    provenance=provenance,
                )
            )
            return True
        if any(
            row.type == 3 and row.va == sentinel
            for row in self.image.relocations
        ):
            return False
        provenance = (
            f"sentinel-table={table_base:#x};sentinel={sentinel:#x};"
            f"load={load.address:#x};increment={increments[0]:#x}"
        )
        for entry_address, raw, target in entry_rows:
            self.seed_records.add(
                SeedRecord(
                    address=target,
                    category="sentinel-callback-entry",
                    provenance_address=entry_address,
                    provenance_bytes=raw.hex(),
                    detail=provenance,
                    is_function=True,
                )
            )
            self._add_edge(
                instruction.address,
                target,
                "indirect-call-sentinel-table",
                provenance=provenance,
            )
            self._record_finite_target(target)
            self._enqueue(target, is_function=True)
        self.data_evidence.add(
            _DataEvidence(
                start=table_base,
                end=sentinel + 4,
                provenance=provenance,
            )
        )
        self._record_fixpoint_update()
        return True

    def _resolve_computed_flows(self) -> None:
        """Resolve indirect candidates to fixed point.

        Resolution of jump tables exposes new reachable code which may
        contain additional indirect candidates.  Iterate until no new
        tables are created and no candidates remain.
        """
        processed: set[int] = set()
        for iteration in range(8):  # safety bound
            candidate_addresses = (
                set(self.indirect_candidates) - processed
            )
            if not candidate_addresses:
                break
            processed |= candidate_addresses
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
            new_tables = 0
            for address in sorted(candidate_addresses):
                if address in self.jump_tables:
                    continue
                flow_kind, is_far = self.indirect_candidates[address]
                instruction = self.instructions[address]
                decoded = self._owned_decoded(address)
                recovered = (
                    False
                    if is_far
                    else (
                        self._recover_cw_inactive_action_helper(instruction)
                        or self._recover_cw_registered_destructor_callback(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_cw_k17_callback(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_cw_continuation_jump(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_iat_terminal(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_global_slot_targets(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_constructor_descriptor_target(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_zero_origin_guarded_global_control(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_indexed_global_slot_targets(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_finite_value_target(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_sentinel_callback_table(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_byte_return_table(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_zero_count_indexed_control(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_registrar_table(
                            decoded, instruction, flow_kind=flow_kind
                        )
                        or self._recover_indexed_table(
                            decoded, instruction, flow_kind=flow_kind
                        )
                    )
                )
                if recovered:
                    new_tables += 1
                    continue
                if any(
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
            if new_tables == 0:
                break



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
        decoded = self.decoded_instruction_cache.get(address)
        if decoded is None:
            decoded = self._decode_one(address)
            self._cache_decoded_instruction(decoded)
        else:
            self.decoded_instruction_cache.move_to_end(address)
        instruction = self.instructions[address]
        if (
            decoded.size != instruction.size
            or bytes(decoded.bytes).hex() != instruction.bytes_hex
        ):
            raise CfgRecoveryError(
                f"owned instruction bytes changed at {address:#x}"
            )
        return decoded

    def _cache_decoded_instruction(self, decoded) -> None:
        address = decoded.address
        self.decoded_instruction_cache[address] = decoded
        self.decoded_instruction_cache.move_to_end(address)
        while (
            len(self.decoded_instruction_cache)
            > _DECODED_INSTRUCTION_CACHE_LIMIT
        ):
            self.decoded_instruction_cache.popitem(last=False)

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
            self.semantic_data_references.add(
                SemanticReference(
                    record_kind="data-reference",
                    address=instruction.address,
                    target=address,
                    provenance=(
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

    def _record_object_callback_tables(self) -> None:
        """Seed finite callback tables proved by stores and owned dispatches."""
        relocation_rows: dict[int, list[int]] = {}
        for relocation in self.image.relocations:
            relocation_rows.setdefault(relocation.va, []).append(
                relocation.type
            )

        def relocated_executable_pointer(address: int) -> tuple[bytes, int] | None:
            if relocation_rows.get(address) != [3]:
                return None
            try:
                raw = self.image.read(address, 4)
            except ValueError:
                return None
            target = int.from_bytes(raw, "little")
            if not _is_executable_span(self.image, target, 1):
                return None
            return raw, target

        def overlaps_owned_absolute_write(start: int, end: int) -> bool:
            for address, writers in self.absolute_memory_writes.items():
                for writer in writers:
                    decoded = self._owned_decoded(writer)
                    widths = {
                        operand.size
                        for operand in decoded.operands
                        if self._absolute_memory_operand(operand) == address
                        and operand.access & CS_AC_WRITE
                    }
                    if any(address < end and start < address + width for width in widths):
                        return True
            return False

        for displacement, writes in sorted(self.dynamic_field_writes.items()):
            candidates = []
            for write in sorted(writes, key=lambda row: row.instruction_address):
                decoded = self._owned_decoded(write.instruction_address)
                if not (
                    decoded.id == X86_INS_MOV
                    and len(decoded.operands) == 2
                    and decoded.operands[0].type == X86_OP_MEM
                    and decoded.operands[0].size == 4
                    and decoded.operands[0].mem.segment == X86_REG_INVALID
                    and decoded.operands[0].mem.base != X86_REG_INVALID
                    and decoded.operands[0].mem.index == X86_REG_INVALID
                    and decoded.operands[0].mem.disp == displacement
                    and displacement != 0
                    and decoded.operands[1].type == X86_OP_IMM
                    and decoded.operands[1].size == 4
                    and decoded.imm_size == 4
                ):
                    continue
                table_base = decoded.operands[1].imm & 0xFFFF_FFFF
                store_relocation = decoded.address + decoded.imm_offset
                if (
                    table_base % 4
                    or relocation_rows.get(store_relocation) != [3]
                ):
                    continue
                candidates.append(
                    (decoded, table_base, store_relocation)
                )
            if not candidates:
                continue
            domain = self._finite_dynamic_field_values(
                displacement, frozenset()
            )
            if domain is None:
                continue
            field_values, field_detail = domain
            for decoded, table_base, store_relocation in candidates:
                if table_base not in field_values:
                    continue
                section = next(
                    (
                        row
                        for row in self.image.sections
                        if not row.is_executable
                        and row.va <= table_base < row.va + row.raw_size
                    ),
                    None,
                )
                if section is None or relocated_executable_pointer(
                    table_base - 4
                ) is not None:
                    continue

                entries: list[tuple[int, bytes, int]] = []
                cursor = table_base
                while cursor + 4 <= section.va + section.raw_size:
                    row = relocated_executable_pointer(cursor)
                    if row is None:
                        break
                    _raw, target = row
                    owner = self.byte_owners.get(target)
                    if owner is not None and owner != target:
                        entries = []
                        break
                    entries.append((cursor, *row))
                    self._check_count(
                        "max_jump_table_entries", len(entries)
                    )
                    cursor += 4
                if (
                    len(entries) < 2
                    or cursor + 4 > section.va + section.raw_size
                    or overlaps_owned_absolute_write(table_base, cursor + 4)
                    or any(
                        relocation.va < cursor + 4
                        and cursor
                        < relocation.va
                        + _I386_RELOCATION_WIDTHS[relocation.type]
                        for relocation in self.image.relocations
                    )
                ):
                    continue
                try:
                    terminator = self.image.read(cursor, 4)
                except ValueError:
                    continue
                if terminator != b"\0" * 4:
                    continue

                entries_by_offset = {
                    slot - table_base: target
                    for slot, _raw, target in entries
                }
                consumers = []
                for edge in sorted(self.edges, key=_edge_key):
                    if edge.kind != "indirect-call-finite-value":
                        continue
                    transfer = self._owned_decoded(edge.source)
                    if (
                        len(transfer.operands) != 1
                        or transfer.operands[0].type != X86_OP_MEM
                    ):
                        continue
                    memory = transfer.operands[0].mem
                    if (
                        memory.segment != X86_REG_INVALID
                        or memory.base == X86_REG_INVALID
                        or memory.index != X86_REG_INVALID
                        or memory.disp not in entries_by_offset
                        or entries_by_offset[memory.disp] != edge.target
                    ):
                        continue
                    function_entry = self._registrar_function_entry(
                        transfer.address
                    )
                    if function_entry is None:
                        continue
                    family = self._register_family(memory.base)
                    definitions = self._register_definitions_across_blocks(
                        transfer.address, family, function_entry
                    )
                    if not definitions:
                        continue
                    field_loads = []
                    for definition in definitions:
                        load = self._owned_decoded(definition)
                        if not (
                            load.id == X86_INS_MOV
                            and len(load.operands) == 2
                            and load.operands[0].type == X86_OP_REG
                            and self._register_family(load.operands[0].reg)
                            == family
                            and load.operands[1].type == X86_OP_MEM
                            and load.operands[1].size == 4
                            and load.operands[1].mem.segment
                            == X86_REG_INVALID
                            and load.operands[1].mem.base
                            != X86_REG_INVALID
                            and load.operands[1].mem.index
                            == X86_REG_INVALID
                            and load.operands[1].mem.disp == displacement
                        ):
                            field_loads = []
                            break
                        field_loads.append(definition)
                    if not field_loads:
                        continue
                    consumers.append(
                        (transfer.address, memory.disp, edge.target)
                    )
                if not consumers:
                    continue

                instruction = self.instructions[decoded.address]
                consumer_detail = ",".join(
                    f"{source:#x}+{offset:#x}->{target:#x}"
                    for source, offset, target in consumers
                )
                detail = (
                    "proof=reachable-object-field-store+owned-finite-dispatch+"
                    "relocated-slots+unrelocated-zero-terminator;"
                    "raw-relocation-is-not-code-root;"
                    f"object-field={displacement:+#x};"
                    f"table-base={table_base:#x};entries={len(entries)};"
                    f"zero-terminator={cursor:#x};"
                    f"store={decoded.address:#x};"
                    f"store-relocation={store_relocation:#x};"
                    f"consumers={consumer_detail};{field_detail}"
                )
                evidence = _DataEvidence(
                    start=table_base,
                    end=cursor + 4,
                    provenance=(
                        f"instruction={instruction.address:#x};"
                        f"bytes={instruction.bytes_hex};{detail}"
                    ),
                )
                self.data_evidence.add(evidence)
                records = tuple(
                    SeedRecord(
                        address=target,
                        category="object-callback-table-entry",
                        provenance_address=slot,
                        provenance_bytes=raw.hex(),
                        detail=detail,
                        is_function=True,
                    )
                    for slot, raw, target in entries
                )
                if table_base in self.rejected_object_callback_tables:
                    self.diagnostics.add(
                        OwnershipDiagnostic(
                            kind="object-callback-table-blocker",
                            address=decoded.address,
                            detail=(
                                "hypothesis expansion invalidated the "
                                "complete receiver-field domain;"
                                + detail.split(";consumers=", 1)[0]
                            ),
                        )
                    )
                    continue
                self.object_callback_table_hypotheses.add(
                    _ObjectCallbackTableHypothesis(
                        table_base=table_base,
                        store_address=decoded.address,
                        records=records,
                        data_evidence=evidence,
                    )
                )

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
                    is_function=True,
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
            for operand in decoded.operands:
                if not (
                    operand.type == X86_OP_MEM
                    and operand.size > 0
                    and operand.access & CS_AC_WRITE
                    and operand.mem.segment == X86_REG_INVALID
                    and operand.mem.base != X86_REG_INVALID
                    and operand.mem.index == X86_REG_INVALID
                ):
                    continue
                instruction = self.instructions[decoded.address]
                displacement = operand.mem.disp
                rows = self.dynamic_field_writes.setdefault(
                    displacement, set()
                )
                before = len(rows)
                rows.add(
                    _DynamicFieldWrite(
                        instruction_address=decoded.address,
                        width=operand.size,
                        value=None,
                        provenance=(
                            f"instruction={decoded.address:#x};"
                            f"bytes={instruction.bytes_hex};"
                            f"field={displacement:+#x};"
                            f"width={operand.size};rmw-or-non-mov"
                        ),
                    )
                )
                self.dynamic_field_write_count += len(rows) - before
            return
        destination, source = decoded.operands
        if destination.type != X86_OP_MEM:
            return
        destination_address = self._exact_memory_address(
            destination.mem, state
        )
        exact_value = self._initializer_value(source, state)
        if (
            destination.size == 4
            and destination.mem.segment == X86_REG_INVALID
            and destination.mem.base != X86_REG_INVALID
            and destination.mem.index == X86_REG_INVALID
        ):
            instruction = self.instructions[decoded.address]
            displacement = destination.mem.disp
            rows = self.dynamic_field_writes.setdefault(displacement, set())
            before = len(rows)
            rows.add(
                _DynamicFieldWrite(
                    instruction_address=decoded.address,
                    width=destination.size,
                    value=(
                        exact_value.value if exact_value is not None else None
                    ),
                    provenance=(
                        f"instruction={decoded.address:#x};"
                        f"bytes={instruction.bytes_hex};"
                        f"field={displacement:+#x};"
                        f"width={destination.size}"
                    ),
                )
            )
            self.dynamic_field_write_count += len(rows) - before
        if (
            destination_address is not None
            and destination.size == 4
            and _is_mapped_span(self.image, destination_address, 4)
            and not _is_executable_span(self.image, destination_address, 4)
        ):
            instruction = self.instructions[decoded.address]
            rows = self.global_slot_writes.setdefault(
                destination_address, set()
            )
            before = len(rows)
            rows.add(
                _GlobalSlotWrite(
                    instruction_address=decoded.address,
                    value=(exact_value.value if exact_value is not None else None),
                    provenance=(
                        f"instruction={decoded.address:#x};"
                        f"bytes={instruction.bytes_hex};"
                        f"slot={destination_address:#x}"
                    ),
                )
            )
            self.global_slot_write_count += len(rows) - before
        if exact_value is None or not _is_executable_span(
            self.image, exact_value.value, 1
        ):
            return
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
            is_function=True,
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
        self.global_slot_writes = {}
        self.global_slot_write_count = 0
        self.dynamic_field_writes = {}
        self.dynamic_field_write_count = 0
        self.dynamic_field_cache = {}
        self.semantic_data_references = set()
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
        self.diagnostics = {
            row
            for row in self.diagnostics
            if row.kind != "unresolved-relocation-obligation"
        }
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
                self._instruction_relocation_field(
                    instruction_address, start, end
                )
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
                continue
            if len(data_boundaries) != 1:
                raise CfgRecoveryError(
                    "executable relocation data boundary is ambiguous: "
                    f"relocation={start:#x}-{end:#x};"
                    f"attributions={len(containing_data)};"
                    f"boundaries={len(data_boundaries)}"
                )

            self.data_evidence.add(
                _DataEvidence(start=start, end=end, provenance=detail)
            )
            # The relocation owns bytes only after an independent typed data
            # boundary.  It never contributes a code root or finite target.

    def _final_relocation_dispositions(
        self,
    ) -> tuple[RelocationDisposition, ...]:
        """Partition every executable-source HIGHLOW at final fixed point."""
        self.diagnostics = {
            row
            for row in self.diagnostics
            if row.kind != "unresolved-relocation-obligation"
        }
        non_relocation_data = tuple(
            row
            for row in self.data_evidence
            if not row.provenance.startswith("relocation=")
        )
        semantic_slots = {
            (record.provenance_address, record.address)
            for record in self.seed_records
            if record.category
            not in {
                "entrypoint",
                "export",
                "explicit-seed",
                "audit-anchor",
            }
        }
        for table in self.jump_tables.values():
            for index, target in enumerate(table.raw_entries):
                semantic_slots.add(
                    (
                        table.base
                        + (table.index_min + index) * table.entry_width,
                        target,
                    )
                )
        imports = {row.iat_va: row for row in self.image.imports}
        rows = []
        for relocation in self.image.relocations:
            if relocation.type != 3 or not _is_executable_span(
                self.image, relocation.va, 4
            ):
                continue
            start = relocation.va
            end = start + 4
            raw = _read_provenance(
                self.image, start, 4, "final relocation disposition"
            )
            target = struct.unpack("<I", raw)[0]
            owned_bytes = [
                self.byte_owners.get(address) for address in range(start, end)
            ]
            present_owners = {row for row in owned_bytes if row is not None}
            source_owner = None
            if present_owners:
                if (
                    len(present_owners) != 1
                    or any(row is None for row in owned_bytes)
                ):
                    raise CfgRecoveryError(
                        "final relocation source straddles instruction "
                        f"ownership: relocation={start:#x}-{end:#x}"
                    )
                source_owner = next(iter(present_owners))
                self._instruction_relocation_field(
                    source_owner, start, end
                )
                source_class = "instruction"
                provenance = f"instruction={source_owner:#x}"
            else:
                containing = [
                    evidence
                    for evidence in non_relocation_data
                    if evidence.start <= start and end <= evidence.end
                ]
                boundaries = {
                    (evidence.start, evidence.end) for evidence in containing
                }
                if len(boundaries) > 1:
                    raise CfgRecoveryError(
                        "final relocation typed-data boundary is ambiguous: "
                        f"relocation={start:#x}-{end:#x};"
                        f"boundaries={len(boundaries)}"
                    )
                if boundaries:
                    source_class = "unique-typed-data-boundary"
                    boundary = next(iter(boundaries))
                    provenance = (
                        f"typed-data={boundary[0]:#x}-{boundary[1]:#x}"
                    )
                else:
                    source_class = "residue"
                    provenance = "no-final-owner-or-typed-data-boundary"

            target_section = self.image.section_of_va(target)
            target_import_row = imports.get(target)
            target_import = (
                None
                if target_import_row is None
                else (
                    f"{target_import_row.dll}!"
                    + (
                        target_import_row.name
                        if target_import_row.name is not None
                        else f"ordinal:{target_import_row.ordinal}"
                    )
                )
            )
            target_mapped = _is_mapped_span(self.image, target, 1)
            target_executable = _is_executable_span(self.image, target, 1)
            if not target_mapped:
                status = "unmapped-anomaly"
            elif source_class == "instruction":
                status = "owned-instruction-operand"
            elif source_class == "unique-typed-data-boundary":
                status = (
                    "owned-typed-data"
                    if not target_executable
                    or (start, target) in semantic_slots
                    else "unresolved-exec-pointer"
                )
            else:
                status = (
                    "unresolved-exec-pointer"
                    if target_executable
                    else "residue-nonexec-address"
                )
            disposition = RelocationDisposition(
                source_address=start,
                source_bytes_hex=raw.hex(),
                source_class=source_class,
                source_owner=source_owner,
                target_address=target,
                target_section=target_section,
                target_import=target_import,
                status=status,
                provenance=provenance,
            )
            rows.append(disposition)
            if status in {"unresolved-exec-pointer", "unmapped-anomaly"}:
                self.diagnostics.add(
                    OwnershipDiagnostic(
                        kind="unresolved-relocation-obligation",
                        address=start,
                        detail=(
                            f"status={status};source-class={source_class};"
                            f"target={target:#x};"
                            f"target-section={target_section or 'unmapped'};"
                            f"{provenance}"
                        ),
                    )
                )
        return tuple(sorted(rows, key=lambda row: row.source_address))

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
        residue: UnreachableExecutableResidue,
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
                elif residue.contains(address, 5):
                    classification = "unreachable-executable-residue"
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

    def _provisional_unreachable_residue(
        self,
        data_regions: tuple[ByteRegion, ...],
        padding_regions: tuple[ByteRegion, ...],
    ) -> UnreachableExecutableResidue:
        """Build the exact complement without promoting its bytes to code."""
        owned = set(self.byte_owners)
        for region in (*data_regions, *padding_regions):
            owned.update(range(region.start, region.end))

        intervals: list[ExecutableResidueInterval] = []
        for raw_start, raw_end in self._executable_raw_ranges():
            start: int | None = None
            for address in range(raw_start, raw_end):
                if address not in owned and start is None:
                    start = address
                elif address in owned and start is not None:
                    blob = self.image.read(start, address - start)
                    intervals.append(
                        ExecutableResidueInterval(
                            start=start,
                            end=address,
                            bytes_hex=blob.hex(),
                            bytes_sha256=hashlib.sha256(blob).hexdigest(),
                        )
                    )
                    start = None
            if start is not None:
                blob = self.image.read(start, raw_end - start)
                intervals.append(
                    ExecutableResidueInterval(
                        start=start,
                        end=raw_end,
                        bytes_hex=blob.hex(),
                        bytes_sha256=hashlib.sha256(blob).hexdigest(),
                    )
                )

        reachable_rows = [
            *(f"i:{row.address:x}:{row.size}:{row.bytes_hex}" for row in sorted(self.instructions.values(), key=_instruction_key)),
            *(f"d:{row.start:x}:{row.end:x}:{row.provenance}" for row in data_regions),
            *(f"p:{row.start:x}:{row.end:x}:{row.provenance}" for row in padding_regions),
        ]
        reachable_digest = hashlib.sha256(
            ("\n".join(reachable_rows) + "\n").encode("utf-8")
        ).hexdigest()
        partition_rows = [
            *reachable_rows,
            *(
                f"u:{row.start:x}:{row.end:x}:{row.bytes_sha256}"
                for row in intervals
            ),
        ]
        partition_digest = hashlib.sha256(
            ("\n".join(sorted(partition_rows)) + "\n").encode("utf-8")
        ).hexdigest()
        return UnreachableExecutableResidue(
            intervals=tuple(intervals),
            reachable_ownership_sha256=reachable_digest,
            executable_partition_sha256=partition_digest,
        )

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
                    is_function=record.is_function,
                )
            )
        self.seed_records = rebound

    def recover(self) -> RawCfg:
        while True:
            while self.pending:
                address = heapq.heappop(self.pending)
                self._decode_from(address)
            blocks = self._build_blocks()
            block_start_count = len(self.block_starts)
            self._scan_owned_blocks(blocks)
            self._resolve_computed_flows()
            self._record_copied_descriptor_callback_tables()
            self._record_object_callback_tables()
            if (
                not self.pending
                and len(self.block_starts) == block_start_count
            ):
                break

        self._bind_seed_instruction_provenance()
        data_regions = self._merged_data_regions()
        padding_regions = self._padding_regions(data_regions)
        self._require_disjoint_ownership(data_regions, padding_regions)
        provisional_residue = self._provisional_unreachable_residue(
            data_regions, padding_regions
        )
        relocation_dispositions = self._final_relocation_dispositions()
        semantic_references = set(self.semantic_data_references)
        for disposition in relocation_dispositions:
            if (
                disposition.source_owner is not None
                and _is_executable_span(
                    self.image, disposition.target_address, 1
                )
            ):
                semantic_references.add(
                    SemanticReference(
                        record_kind="function-pointer-reference",
                        address=disposition.source_owner,
                        target=disposition.target_address,
                        provenance=(
                            f"relocation={disposition.source_address:#x};"
                            f"status={disposition.status}"
                        ),
                    )
                )
        raw_e8_candidates = self._raw_e8_candidates(
            data_regions, padding_regions, provisional_residue
        )
        for limit_name in self.limits.__dataclass_fields__:
            self.limits.check(limit_name, self.high_water[limit_name])
        high_water = tuple(
            AnalysisHighWater(limit_name, self.high_water[limit_name])
            for limit_name in self.limits.__dataclass_fields__
        )
        function_entries = _materialize_function_entries(
            self.function_addresses, self.seed_records
        )
        blocking_kinds = {
            "computed-flow-blocker",
            "indirect-flow",
            "unsupported-far-flow",
            "external-code-pointer-escape",
            "object-callback-table-blocker",
            "unresolved-relocation-obligation",
        }
        control_targets = ControlTargetResult(
            finite_internal_edges=tuple(
                FiniteControlTarget(
                    source=edge.source,
                    target=edge.target,
                    flow_kind=edge.kind,
                    provenance=self.edge_provenance[edge],
                )
                for edge in sorted(self.edges, key=_edge_key)
            ),
            terminal_external_edges=tuple(
                sorted(
                    self.terminal_external_edges,
                    key=lambda row: (
                        row.source,
                        row.flow_kind,
                        row.iat_va,
                        row.dll,
                        row.name or "",
                        row.ordinal if row.ordinal is not None else -1,
                    ),
                )
            ),
            external_escapes=tuple(
                sorted(
                    self.external_escapes,
                    key=lambda row: (row.source, row.target_import_iat),
                )
            ),
            unresolved=tuple(
                UnresolvedControlTarget(row.address, row.kind, row.detail)
                for row in sorted(self.diagnostics, key=_diagnostic_key)
                if row.kind in blocking_kinds
            ),
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
            cw_exception_metadata=self.cw_exception_metadata,
            raw_e8_candidates=raw_e8_candidates,
            data_regions=data_regions,
            padding_regions=padding_regions,
            provisional_unreachable_residue=provisional_residue,
            function_entries=function_entries,
            control_targets=control_targets,
            ownership_diagnostics=tuple(
                sorted(self.diagnostics, key=_diagnostic_key)
            ),
            relocation_dispositions=relocation_dispositions,
            semantic_references=tuple(
                sorted(
                    semantic_references,
                    key=lambda row: (
                        row.address,
                        row.record_kind,
                        row.target,
                        row.provenance,
                    ),
                )
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

    def identity(row):
        if isinstance(row, _ObjectCallbackTableHypothesis):
            prefix = (
                "object-callback-table",
                row.table_base,
                row.store_address,
                row.data_evidence.start,
                row.data_evidence.end,
            )
        else:
            prefix = (
                "copied-descriptor-callback-table",
                *row.source_bases,
                row.target_source_bases,
            )
        return (
            *prefix,
            tuple(
                (
                    record.address,
                    record.provenance_address,
                    record.provenance_bytes,
                )
                for record in row.records
            ),
        )

    accepted: dict[tuple, Any] = {}
    rejected_identities: set[tuple] = set()
    rejected_object_bases: set[int] = set()
    while True:
        current_inventory = SeedInventory(
            (
                *seed_inventory.records,
                *(
                    record
                    for hypothesis in accepted.values()
                    for record in hypothesis.records
                ),
            )
        )
        current_recovery = _DirectCfgRecovery(
            image,
            current_inventory,
            limits,
            rejected_object_callback_tables=frozenset(
                rejected_object_bases
            ),
        )
        current_cfg = current_recovery.recover()
        valid_identities = {
            identity(row)
            for row in (
                *current_recovery.object_callback_table_hypotheses,
                *current_recovery.validated_copied_descriptor_callback_hypotheses,
            )
        }
        invalidated = {
            hypothesis_identity: hypothesis
            for hypothesis_identity, hypothesis in accepted.items()
            if hypothesis_identity not in valid_identities
        }
        if invalidated:
            for hypothesis_identity, hypothesis in invalidated.items():
                del accepted[hypothesis_identity]
                rejected_identities.add(hypothesis_identity)
                if isinstance(
                    hypothesis, _ObjectCallbackTableHypothesis
                ):
                    rejected_object_bases.add(hypothesis.table_base)
            continue

        candidates = tuple(
            sorted(
                current_recovery.object_callback_table_hypotheses,
                key=lambda row: (row.table_base, row.store_address),
            )
        ) + tuple(
            sorted(
                current_recovery.copied_descriptor_callback_hypotheses,
                key=lambda row: row.source_bases,
            )
        )
        new_candidates = {
            identity(hypothesis): hypothesis
            for hypothesis in candidates
            if identity(hypothesis) not in accepted
            and identity(hypothesis) not in rejected_identities
        }
        if not new_candidates:
            return current_cfg

        trial_inventory = SeedInventory(
            (
                *seed_inventory.records,
                *(
                    record
                    for hypothesis in (
                        *accepted.values(),
                        *new_candidates.values(),
                    )
                    for record in hypothesis.records
                ),
            )
        )
        trial_recovery = _DirectCfgRecovery(
            image,
            trial_inventory,
            limits,
            rejected_object_callback_tables=frozenset(
                rejected_object_bases
            ),
        )
        trial_recovery.recover()
        reproduced_identities = {
            identity(row)
            for row in (
                *trial_recovery.object_callback_table_hypotheses,
                *trial_recovery.validated_copied_descriptor_callback_hypotheses,
            )
        }
        for hypothesis_identity, hypothesis in new_candidates.items():
            if hypothesis_identity in reproduced_identities:
                accepted[hypothesis_identity] = hypothesis
                continue
            rejected_identities.add(hypothesis_identity)
            if isinstance(hypothesis, _ObjectCallbackTableHypothesis):
                rejected_object_bases.add(hypothesis.table_base)


def canonical_jsonl_bytes(cfg: RawCfg) -> bytes:
    """Return canonical compact UTF-8 CFG records with a final newline."""
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
    if cfg.cw_exception_metadata is not None:
        rows.append(
            {
                "record_kind": "cw-exception-metadata",
                "address": -1,
                **asdict(cfg.cw_exception_metadata),
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
    for entry in cfg.function_entries:
        rows.append(
            {
                "record_kind": "function-entry",
                **asdict(entry),
            }
        )
    for edge in cfg.control_targets.finite_internal_edges:
        rows.append(
            {
                "record_kind": "finite-control-target",
                "address": edge.source,
                **asdict(edge),
            }
        )
    for edge in cfg.control_targets.terminal_external_edges:
        rows.append(
            {
                "record_kind": "terminal-external-edge",
                "address": edge.source,
                **asdict(edge),
            }
        )
    for escape in cfg.control_targets.external_escapes:
        rows.append(
            {
                "record_kind": "external-code-pointer-escape",
                "address": escape.source,
                **asdict(escape),
            }
        )
    for unresolved in cfg.control_targets.unresolved:
        rows.append(
            {
                "record_kind": "unresolved-control-target",
                **asdict(unresolved),
            }
        )
    for interval in cfg.provisional_unreachable_residue.intervals:
        rows.append(
            {
                "record_kind": "unreachable-executable-residue",
                "address": interval.start,
                **asdict(interval),
            }
        )
    rows.append(
        {
            "record_kind": "unreachable-executable-residue-summary",
            "address": -1,
            "reachable_ownership_sha256": (
                cfg.provisional_unreachable_residue.reachable_ownership_sha256
            ),
            "executable_partition_sha256": (
                cfg.provisional_unreachable_residue.executable_partition_sha256
            ),
            "accepted": cfg.provisional_unreachable_residue.accepted,
            "reconciliation_sha256": (
                cfg.provisional_unreachable_residue.reconciliation_sha256
            ),
        }
    )
    for diagnostic in cfg.ownership_diagnostics:
        rows.append(
            {"record_kind": "ownership-diagnostic", **asdict(diagnostic)}
        )
    for disposition in cfg.relocation_dispositions:
        rows.append(
            {
                "record_kind": "relocation-disposition",
                "address": disposition.source_address,
                **asdict(disposition),
            }
        )
    for reference in cfg.semantic_references:
        rows.append(
            {
                "record_kind": "semantic-reference",
                "reference_kind": reference.record_kind,
                "address": reference.address,
                "target": reference.target,
                "provenance": reference.provenance,
            }
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
    return b"".join(
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
        for row in rows
    )



def write_jsonl_atomic(path: Path, cfg: RawCfg) -> None:
    """Write canonical compact UTF-8 CFG records with atomic replacement."""
    payload = canonical_jsonl_bytes(cfg)
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
