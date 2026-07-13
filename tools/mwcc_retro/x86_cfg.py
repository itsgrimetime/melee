"""Deterministic seed discovery and direct PE32 x86 CFG recovery."""

from __future__ import annotations

import hashlib
import heapq
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from capstone import (
    CS_ARCH_X86,
    CS_GRP_CALL,
    CS_GRP_IRET,
    CS_GRP_JUMP,
    CS_GRP_RET,
    CS_MODE_32,
    Cs,
)
from capstone.x86 import (
    X86_INS_JMP,
    X86_INS_LJMP,
    X86_INS_MOV,
    X86_OP_IMM,
    X86_OP_MEM,
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


class _DirectCfgRecovery:
    """Address-priority direct decoder with exact instruction ownership."""

    def __init__(
        self,
        image: Image,
        seed_inventory: SeedInventory,
        limits: AnalysisLimits,
    ) -> None:
        self.image = image
        self.limits = limits
        self.seed_records = set(seed_inventory.records)
        self.instructions: dict[int, Instruction] = {}
        self.byte_owners: dict[int, int] = {}
        self.block_starts: set[int] = set()
        self.terminators: set[int] = set()
        self.edges: set[CfgEdge] = set()
        self.direct_calls: set[DirectCall] = set()
        self.diagnostics: set[OwnershipDiagnostic] = set()
        self.function_addresses: set[int] = set()
        self.finite_targets: set[int] = set()
        self.pending: list[int] = []
        self.queued: set[int] = set()

        self.decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        self.decoder.detail = True
        self.decoder.skipdata = False

        for address in seed_inventory.addresses:
            self._enqueue(address, is_function=True)

    def _check_count(self, limit_name: str, observed: int) -> None:
        self.limits.check(limit_name, observed)

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
        self.block_starts.add(address)
        if address not in self.finite_targets:
            self.finite_targets.add(address)
            self._check_count(
                "max_finite_targets", len(self.finite_targets)
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

    def _executable_end(self, address: int) -> int:
        for start, end in self.image.executable_ranges:
            if start <= address < end:
                return end
        raise CfgRecoveryError(
            f"CFG seed or target is not executable: {address:#x}"
        )

    def _decode_one(self, address: int):
        executable_end = self._executable_end(address)
        available = min(15, executable_end - address)
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
        if not decoded.operands or decoded.operands[0].type != X86_OP_IMM:
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

    def _record_absolute_initializer(self, decoded) -> None:
        """Recognize only a direct absolute ``mov [addr], imm32`` seed."""
        if decoded.id != X86_INS_MOV or len(decoded.operands) != 2:
            return
        destination, value = decoded.operands
        if destination.type != X86_OP_MEM or value.type != X86_OP_IMM:
            return
        memory = destination.mem
        if (
            memory.segment != X86_REG_INVALID
            or memory.base != X86_REG_INVALID
            or memory.index != X86_REG_INVALID
        ):
            return
        destination_address = memory.disp & 0xFFFF_FFFF
        destination_size = destination.size
        if destination_size != 4:
            return
        try:
            self.image.read(destination_address, destination_size)
        except ValueError:
            return
        if _is_executable_span(
            self.image, destination_address, destination_size
        ):
            return
        target = value.imm & 0xFFFF_FFFF
        if not _is_executable_span(self.image, target, 1):
            return

        instruction = self.instructions[decoded.address]
        self.seed_records.add(
            SeedRecord(
                address=target,
                category="function-pointer-initializer",
                provenance_address=instruction.address,
                provenance_bytes=instruction.bytes_hex,
                detail=f"absolute-store={destination_address:#x}",
            )
        )
        self._enqueue(target, is_function=True)

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
            self._record_absolute_initializer(decoded)
            next_address = address + instruction.size

            if decoded.group(CS_GRP_CALL):
                target = self._direct_target(decoded)
                if target is None:
                    self.diagnostics.add(
                        OwnershipDiagnostic(
                            kind="indirect-flow",
                            address=address,
                            detail=(
                                f"unresolved indirect call: "
                                f"{instruction.mnemonic} "
                                f"{instruction.operands}"
                            ).rstrip(),
                        )
                    )
                else:
                    self._record_direct_target(
                        instruction, target, "direct-call-target"
                    )
                    self.direct_calls.add(
                        DirectCall(address=address, target=target)
                    )
                    self._add_edge(address, target, "direct-call")
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
                    self.diagnostics.add(
                        OwnershipDiagnostic(
                            kind="indirect-flow",
                            address=address,
                            detail=(
                                f"unresolved indirect jump: "
                                f"{instruction.mnemonic} "
                                f"{instruction.operands}"
                            ).rstrip(),
                        )
                    )
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

    def recover(self) -> RawCfg:
        while self.pending:
            address = heapq.heappop(self.pending)
            self._decode_from(address)

        blocks = self._build_blocks()
        high_water = (
            AnalysisHighWater(
                "max_instructions", len(self.instructions)
            ),
            AnalysisHighWater("max_blocks", len(blocks)),
            AnalysisHighWater("max_edges", len(self.edges)),
            AnalysisHighWater(
                "max_functions", len(self.function_addresses)
            ),
            AnalysisHighWater(
                "max_finite_targets", len(self.finite_targets)
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
            raw_e8_candidates=(),
            data_regions=(),
            padding_regions=(),
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
    """Write canonical CFG JSONL atomically (decoder serialization slice)."""
    raise NotImplementedError(
        "canonical CFG JSONL is not implemented in the seed-inventory slice"
    )
