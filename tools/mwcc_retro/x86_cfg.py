"""Deterministic records and seed discovery for PE32 x86 CFG recovery.

The instruction decoder and ownership recovery intentionally live beyond this
initial seed-inventory layer.  Their public entry points fail explicitly until
that analysis is implemented.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    raw_e8_candidates: tuple[RawE8Candidate, ...]
    data_regions: tuple[ByteRegion, ...]
    padding_regions: tuple[ByteRegion, ...]
    ownership_diagnostics: tuple[OwnershipDiagnostic, ...]
    limits: AnalysisLimits
    high_water_marks: tuple[AnalysisHighWater, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_executable_span(image: Image, address: int, size: int) -> bool:
    end = address + size
    return any(
        start <= address and end <= range_end
        for start, range_end in image.executable_ranges
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
        if _is_executable_span(image, relocation.va, 4):
            continue
        try:
            pointer_bytes = image.read(relocation.va, 4)
        except ValueError:
            continue
        pointer = struct.unpack("<I", pointer_bytes)[0]
        if not _is_executable_span(image, pointer, 1):
            continue
        yield SeedRecord(
            address=pointer,
            category="relocation-executable-pointer",
            provenance_address=relocation.va,
            provenance_bytes=pointer_bytes.hex(),
            detail=f"i386-relocation-type-{relocation.type}",
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


def recover_cfg(
    image: Image,
    seeds: SeedInventory | Sequence[int],
    limits: AnalysisLimits,
) -> RawCfg:
    """Recover direct x86 CFG and exact ownership (decoder slice)."""
    raise NotImplementedError(
        "direct x86 CFG decoding is not implemented in the seed-inventory slice"
    )


def write_jsonl_atomic(path: Path, cfg: RawCfg) -> None:
    """Write canonical CFG JSONL atomically (decoder serialization slice)."""
    raise NotImplementedError(
        "canonical CFG JSONL is not implemented in the seed-inventory slice"
    )
