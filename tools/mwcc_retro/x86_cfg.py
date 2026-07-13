"""Deterministic seed discovery and direct PE32 x86 CFG recovery."""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import struct
import tempfile
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
    X86_INS_LEA,
    X86_INS_JMP,
    X86_INS_LJMP,
    X86_INS_MOV,
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


@dataclass(frozen=True, slots=True)
class _ExactValue:
    value: int
    chain: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _DataEvidence:
    start: int
    end: int
    provenance: str


_I386_RELOCATION_WIDTHS = {1: 2, 2: 2, 3: 4, 4: 2}
_CANONICAL_NOP_ENCODINGS = tuple(
    sorted(
        (
            bytes.fromhex("90"),
            bytes.fromhex("66 90"),
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
        self.data_evidence: set[_DataEvidence] = set()
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
        instruction = self.instructions[decoded.address]
        for index, operand in enumerate(decoded.operands):
            if operand.type != X86_OP_MEM or operand.size <= 0:
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
            return _ExactValue(operand.imm & 0xFFFF_FFFF, ())
        if operand.type == X86_OP_REG and operand.size == 4:
            return state.get(self._register_family(operand.reg))
        return None

    def _record_initializer(
        self,
        decoded,
        state: dict[str, _ExactValue],
    ) -> None:
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
        destination_is_valid = destination_address is not None
        if destination_is_valid:
            try:
                self.image.read(destination_address, destination.size)
            except ValueError:
                destination_is_valid = False
        if (
            not destination_is_valid
            or destination.size != 4
            or _is_executable_span(self.image, destination_address, 4)
        ):
            raise CfgRecoveryError(
                "unresolved function-pointer initializer: "
                f"store at {decoded.address:#x}"
            )

        instruction = self.instructions[decoded.address]
        chain = (*exact_value.chain, self._chain_step(instruction))
        self.seed_records.add(
            SeedRecord(
                address=exact_value.value,
                category="function-pointer-initializer",
                provenance_address=instruction.address,
                provenance_bytes=instruction.bytes_hex,
                detail=(
                    f"store-ea={destination_address:#x};"
                    f"propagation-chain={'>'.join(chain)}"
                ),
            )
        )
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
                    state[family] = _ExactValue(
                        source.imm & 0xFFFF_FFFF, (step,)
                    )
                    return
                if (
                    decoded.id == X86_INS_LEA
                    and source.type == X86_OP_MEM
                    and source.mem.segment == X86_REG_INVALID
                    and source.mem.base == X86_REG_INVALID
                    and source.mem.index == X86_REG_INVALID
                ):
                    state[family] = _ExactValue(
                        source.mem.disp & 0xFFFF_FFFF, (step,)
                    )
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

        _, written = decoded.regs_access()
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
        self.data_evidence = set()
        for block in blocks:
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

        for relocation in self.image.relocations:
            width = _I386_RELOCATION_WIDTHS.get(relocation.type)
            if width is None:
                raise CfgRecoveryError(
                    "unsupported relocation width during data ownership: "
                    f"type={relocation.type}"
                )
            provenance = _read_provenance(
                self.image,
                relocation.va,
                width,
                "relocation data",
            )
            self.data_evidence.add(
                _DataEvidence(
                    start=relocation.va,
                    end=relocation.va + width,
                    provenance=(
                        f"relocation={relocation.va:#x};"
                        f"type={relocation.type};width={width};"
                        f"bytes={provenance.hex()}"
                    ),
                )
            )

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
                start = left.address + left.size
                end = right.address
                if start >= end or left.address not in self.terminators:
                    continue
                if any(
                    region.start < end and start < region.end
                    for region in data_regions
                ):
                    continue
                blob = _read_provenance(
                    self.image, start, end - start, "padding"
                )
                if not self._is_canonical_padding(blob):
                    continue
                regions.append(
                    ByteRegion(
                        start=start,
                        end=end,
                        provenance=(
                            f"unreachable-after={left.address:#x};"
                            f"before={right.address:#x};"
                            "encoding=canonical-x86-nop-or-int3"
                        ),
                    )
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

    def _raw_e8_candidates(
        self, data_regions: tuple[ByteRegion, ...]
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

    def recover(self) -> RawCfg:
        while True:
            while self.pending:
                address = heapq.heappop(self.pending)
                self._decode_from(address)
            blocks = self._build_blocks()
            block_start_count = len(self.block_starts)
            self._scan_owned_blocks(blocks)
            if (
                not self.pending
                and len(self.block_starts) == block_start_count
            ):
                break

        data_regions = self._merged_data_regions()
        padding_regions = self._padding_regions(data_regions)
        raw_e8_candidates = self._raw_e8_candidates(data_regions)
        self._require_complete_ownership(data_regions, padding_regions)
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
