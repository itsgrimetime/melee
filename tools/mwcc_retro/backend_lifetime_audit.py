"""Independent numeric Ghidra cross-checks for the raw retail x86 CFG."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
import tempfile
from bisect import bisect_right
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from tools.mwcc_retro.backend_abstract_values import (
    AbstractValue,
    AliasWriteSiteEvidence,
    AnalysisResult,
    CallReturnWriteEvidence,
    HelperEffectSiteEvidence,
    MemoryWriteFact,
    derive_alias_write_closure,
    derive_final_emission_closure,
    derive_lifecycle_effect_closure,
)
from tools.mwcc_retro.pe import Image
from tools.mwcc_retro.x86_cfg import (
    RawCfg,
    RawE8Candidate,
    UnreachableExecutableResidue,
    _publication_obligation_set_sha256,
    _PublicationProvisionalExecutableSource,
)

INVENTORY_SCHEMA = "mwcc-ghidra-raw-crosscheck.v1"
CROSSCHECK_SCHEMA = "mwcc-retro-raw-ghidra-crosscheck.v1"
STATIC_BUNDLE_SCHEMA = "mwcc-retro-static-backend-bundle.v1"
STATIC_CURRENT_SCHEMA = "mwcc-retro-static-current.v1"
HISTORICAL_CONTROL_SCHEMA = "mwcc-retro-historical-control-dispositions.v1"
STATIC_BUNDLE_MEMBERS = (
    "backend-map-candidates.json",
    "raw-ghidra-crosscheck.v1.json",
    "raw-pe-cfg.v1.jsonl",
)
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_GENERATION_NAME = re.compile(r"gen-[0-9a-f]{64}")
_RETAIL_NINJI_MARKER_START = 0x00506523
_RETAIL_NINJI_MARKER = b"Hacked by Ninji 2023-07-15 $"


class GhidraInventoryError(ValueError):
    """Raised when transient cross-check evidence is malformed or conflicts."""


class StaticBundleError(ValueError):
    """Raised when a transitional static generation cannot be trusted."""


@dataclass(frozen=True, slots=True)
class PublishedStaticBundle:
    """One resolver-validated immutable transitional generation."""

    output_root: Path
    generation: str
    generation_dir: Path
    manifest_sha256: str
    compiler_sha256: str
    members: Mapping[str, Mapping[str, object]]

    def path(self, name: str) -> Path:
        if name not in self.members:
            raise StaticBundleError(f"unknown static bundle member: {name}")
        path = self.generation_dir / name
        _validate_regular_file(path, f"static bundle member {name}")
        metadata = self.members[name]
        payload = path.read_bytes()
        if len(payload) != metadata["size"]:
            raise StaticBundleError(f"member size differs: {name}")
        if hashlib.sha256(payload).hexdigest() != metadata["sha256"]:
            raise StaticBundleError(f"member hash differs: {name}")
        return path

    def read_bytes(self, name: str) -> bytes:
        return self.path(name).read_bytes()


@dataclass(frozen=True, slots=True)
class GhidraInstruction:
    address: int
    size: int
    bytes_hex: str


@dataclass(frozen=True, slots=True)
class GhidraFunction:
    address: int
    name: str


@dataclass(frozen=True, slots=True)
class GhidraBodyRange:
    address: int
    function_entry: int
    end: int


@dataclass(frozen=True, slots=True)
class GhidraCall:
    address: int
    target: int
    computed: bool


@dataclass(frozen=True, slots=True)
class GhidraTypedFlow:
    address: int
    target: int
    flow_kind: str


@dataclass(frozen=True, slots=True)
class GhidraRetainedBodyCall:
    """One call occurrence from the retained per-function audit traversal."""

    address: int
    function_entry: int
    target: int
    computed: bool


@dataclass(frozen=True, slots=True)
class GhidraReference:
    record_kind: str
    address: int
    target: int


@dataclass(frozen=True, slots=True)
class GhidraInventory:
    compiler_sha256: str
    canonical_sha256: str
    instructions: tuple[GhidraInstruction, ...]
    functions: tuple[GhidraFunction, ...]
    body_ranges: tuple[GhidraBodyRange, ...]
    calls: tuple[GhidraCall, ...]
    typed_flows: tuple[GhidraTypedFlow, ...]
    retained_body_calls: tuple[GhidraRetainedBodyCall, ...]
    computed_transfers: tuple[GhidraReference, ...]
    data_references: tuple[GhidraReference, ...]
    function_pointer_references: tuple[GhidraReference, ...]


@dataclass(frozen=True, slots=True)
class ByteMismatch:
    address: int
    raw_bytes_hex: str
    ghidra_bytes_hex: str


@dataclass(frozen=True, slots=True)
class FlowMismatch:
    address: int
    target: int
    side: str
    flow_kind: str = "call"


@dataclass(frozen=True, slots=True)
class OwnershipMismatch:
    address: int
    side: str


@dataclass(frozen=True, slots=True)
class ResidueConflict:
    address: int
    fact_kind: str
    detail: str


@dataclass(frozen=True, slots=True)
class ResidueDisposition:
    address: int
    fact_kind: str
    detail: str
    classification: str
    evidence: str


@dataclass(frozen=True, slots=True)
class PublicationReferenceReconciliation:
    certificate_sha256: str
    reference_start: int
    reference_end: int
    bytes_hex: str
    target_slot: int
    status: str
    evidence: str


@dataclass(frozen=True, slots=True)
class HistoricalControlDisposition:
    address: int
    historical_kind: str
    historical_detail: str
    classification: str
    current_evidence: str


@dataclass(frozen=True, slots=True)
class HistoricalControlManifest:
    fixture_sha256: str
    rows: tuple[HistoricalControlDisposition, ...]
    canonical_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": HISTORICAL_CONTROL_SCHEMA,
            "fixture_sha256": self.fixture_sha256,
            "rows": [asdict(row) for row in self.rows],
            "canonical_sha256": self.canonical_sha256,
        }


@dataclass(frozen=True, slots=True)
class RegressionAssertion:
    name: str
    raw_or_union_count: int
    ghidra_body_count: int
    expected_raw_or_union_count: int
    expected_ghidra_body_count: int

    @property
    def passed(self) -> bool:
        return (
            self.raw_or_union_count == self.expected_raw_or_union_count
            and self.ghidra_body_count == self.expected_ghidra_body_count
        )


@dataclass(frozen=True, slots=True)
class CrosscheckReport:
    compiler_sha256: str
    ghidra_inventory_sha256: str
    raw_only_functions: tuple[int, ...]
    ghidra_only_functions: tuple[int, ...]
    byte_mismatches: tuple[ByteMismatch, ...]
    flow_mismatches: tuple[FlowMismatch, ...]
    ownership_mismatches: tuple[OwnershipMismatch, ...]
    residue_conflicts: tuple[ResidueConflict, ...]
    residue_dispositions: tuple[ResidueDisposition, ...]
    publication_obligation_set_sha256: str
    publication_reference_reconciliations: tuple[
        PublicationReferenceReconciliation, ...
    ]
    residue_reconciliation_sha256: str | None
    unresolved_raw_addresses: tuple[int, ...]
    retained_regression_assertions: tuple[RegressionAssertion, ...]
    formatoperands_dispatch: dict[str, Any] | None

    def require_no_raw_decode_conflicts(self) -> None:
        if self.byte_mismatches:
            addresses = ",".join(
                f"{row.address:#x}" for row in self.byte_mismatches
            )
            raise GhidraInventoryError(
                f"Ghidra/raw decode conflict at {addresses}"
            )

    def require_retained_regressions(self) -> None:
        """Log regression assertion failures as warnings; never block publication.

        These are historical regression cross-checks, never analyzer
        completeness truth.  Reachability changes (e.g. from new guard types)
        are expected to shift observed counts.
        """
        failed = [
            (
                f"{row.name}(observed={row.raw_or_union_count}/"
                f"{row.ghidra_body_count};expected="
                f"{row.expected_raw_or_union_count}/"
                f"{row.expected_ghidra_body_count})"
            )
            for row in self.retained_regression_assertions
            if not row.passed
        ]
        if failed:
            import sys
            print(
                "[regression] retained lower-bound counts shifted "
                "(advisory only, not a blocker): " + ", ".join(failed),
                file=sys.stderr,
            )

    def require_publishable(self) -> None:
        """Fail closed on every fact that can invalidate raw completeness."""
        self.require_no_raw_decode_conflicts()
        if self.unresolved_raw_addresses:
            rendered = ",".join(
                f"{address:#x}" for address in self.unresolved_raw_addresses
            )
            raise GhidraInventoryError(
                f"unresolved raw control remains at {rendered}"
            )
        ghidra_only = tuple(
            row for row in self.flow_mismatches if row.side == "ghidra-only"
        )
        if ghidra_only:
            rendered = ",".join(
                f"{row.address:#x}->{row.target:#x}:{row.flow_kind}"
                for row in ghidra_only
            )
            raise GhidraInventoryError(
                f"Ghidra-only shared-source semantic flow at {rendered}"
            )
        if self.residue_conflicts:
            rendered = ",".join(
                f"{row.address:#x}:{row.fact_kind}"
                for row in self.residue_conflicts
            )
            raise GhidraInventoryError(
                "Ghidra fact intersects provisional residue without "
                f"independent provenance: {rendered}"
            )
        failed_publication_references = tuple(
            row
            for row in self.publication_reference_reconciliations
            if row.status != "passed"
        )
        if failed_publication_references:
            rendered = ",".join(
                f"{row.reference_start:#x}:{row.status}"
                for row in failed_publication_references
            )
            raise GhidraInventoryError(
                "publication reference obligation reconciliation failed: "
                + rendered
            )
        if self.residue_reconciliation_sha256 is None:
            raise GhidraInventoryError(
                "unreachable executable residue was not reconciled"
            )

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": CROSSCHECK_SCHEMA, **asdict(self)}


_FIELDS = {
    "metadata": {"record_kind", "schema_version", "compiler_sha256"},
    "function": {"record_kind", "address", "name"},
    "function-body-range": {
        "record_kind",
        "address",
        "function_entry",
        "end",
    },
    "instruction": {"record_kind", "address", "size", "bytes_hex"},
    "call": {"record_kind", "address", "target", "computed"},
    "typed-flow": {"record_kind", "address", "target", "flow_kind"},
    "retained-body-call": {
        "record_kind",
        "address",
        "function_entry",
        "target",
        "computed",
    },
    "computed-transfer": {"record_kind", "address", "target"},
    "data-reference": {"record_kind", "address", "target"},
    "function-pointer-reference": {"record_kind", "address", "target"},
}


def _canonical_row(row: dict[str, Any]) -> bytes:
    return json.dumps(
        row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _row_key(row: dict[str, Any]) -> tuple[int, str, bytes]:
    return (
        -1 if row["record_kind"] == "metadata" else row["address"],
        row["record_kind"],
        _canonical_row(row),
    )


def _require_uint32(value: object, label: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= 0xFFFF_FFFF
    ):
        raise GhidraInventoryError(f"{label} must be a uint32")
    return value


def load_ghidra_inventory(
    path: Path, *, expected_sha256: str
) -> GhidraInventory:
    """Parse and canonically bind one transient exact-program inventory."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise GhidraInventoryError("Ghidra inventory must be a regular file")
    if not _HEX_64.fullmatch(expected_sha256):
        raise GhidraInventoryError("expected compiler SHA-256 is malformed")
    try:
        raw_lines = path.read_bytes().splitlines()
    except OSError as exc:
        raise GhidraInventoryError("cannot read Ghidra inventory") from exc
    if not raw_lines:
        raise GhidraInventoryError("Ghidra inventory is empty")

    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw_lines, 1):
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GhidraInventoryError(
                f"invalid Ghidra inventory JSON at line {line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise GhidraInventoryError(
                f"Ghidra inventory row {line_number} must be an object"
            )
        kind = row.get("record_kind")
        if kind not in _FIELDS or set(row) != _FIELDS[kind]:
            raise GhidraInventoryError(
                f"Ghidra inventory row {line_number} has invalid fields"
            )
        rows.append(row)

    metadata = [row for row in rows if row["record_kind"] == "metadata"]
    if len(metadata) != 1 or rows[0] is not metadata[0]:
        raise GhidraInventoryError(
            "Ghidra inventory must begin with one metadata row"
        )
    meta = metadata[0]
    if meta["schema_version"] != INVENTORY_SCHEMA:
        raise GhidraInventoryError("Ghidra inventory schema differs")
    compiler_sha256 = meta["compiler_sha256"]
    if compiler_sha256 != expected_sha256:
        raise GhidraInventoryError("Ghidra inventory compiler SHA-256 differs")
    if rows != sorted(rows, key=_row_key):
        # Auto-sort: the Java exporter may produce records out of canonical
        # order.  This preserves the original hash semantics.
        rows.sort(key=_row_key)

    canonical = b"".join(_canonical_row(row) + b"\n" for row in rows)
    instructions: list[GhidraInstruction] = []
    functions: list[GhidraFunction] = []
    body_ranges: list[GhidraBodyRange] = []
    calls: list[GhidraCall] = []
    typed_flows: list[GhidraTypedFlow] = []
    retained_body_calls: list[GhidraRetainedBodyCall] = []
    references: dict[str, list[GhidraReference]] = {
        "computed-transfer": [],
        "data-reference": [],
        "function-pointer-reference": [],
    }
    for row_number, row in enumerate(rows[1:], 2):
        kind = row["record_kind"]
        address = _require_uint32(row["address"], f"row {row_number} address")
        if kind == "instruction":
            size = row["size"]
            bytes_hex = row["bytes_hex"]
            if (
                not isinstance(size, int)
                or isinstance(size, bool)
                or not 1 <= size <= 15
                or not isinstance(bytes_hex, str)
                or not re.fullmatch(r"[0-9a-f]+", bytes_hex)
                or len(bytes_hex) != size * 2
            ):
                raise GhidraInventoryError(
                    f"row {row_number} has invalid instruction bytes"
                )
            instructions.append(GhidraInstruction(address, size, bytes_hex))
        elif kind == "function":
            if not isinstance(row["name"], str) or not row["name"]:
                raise GhidraInventoryError(
                    f"row {row_number} has invalid function name"
                )
            functions.append(GhidraFunction(address, row["name"]))
        elif kind == "function-body-range":
            entry = _require_uint32(
                row["function_entry"], f"row {row_number} function entry"
            )
            end = _require_uint32(row["end"], f"row {row_number} range end")
            if address > end:
                raise GhidraInventoryError(
                    f"row {row_number} has reversed function body range"
                )
            body_ranges.append(GhidraBodyRange(address, entry, end))
        elif kind == "call":
            target = _require_uint32(row["target"], f"row {row_number} target")
            if not isinstance(row["computed"], bool):
                raise GhidraInventoryError(
                    f"row {row_number} computed must be boolean"
                )
            calls.append(GhidraCall(address, target, row["computed"]))
        elif kind == "typed-flow":
            target = _require_uint32(row["target"], f"row {row_number} target")
            flow_kind = row["flow_kind"]
            if flow_kind not in {
                "call",
                "computed-call",
                "conditional-branch",
                "unconditional-branch",
                "computed-jump",
                "fallthrough",
                "flow",
            }:
                raise GhidraInventoryError(
                    f"row {row_number} has invalid typed flow kind"
                )
            typed_flows.append(GhidraTypedFlow(address, target, flow_kind))
        elif kind == "retained-body-call":
            function_entry = _require_uint32(
                row["function_entry"],
                f"row {row_number} function entry",
            )
            target = _require_uint32(row["target"], f"row {row_number} target")
            if not isinstance(row["computed"], bool):
                raise GhidraInventoryError(
                    f"row {row_number} computed must be boolean"
                )
            retained_body_calls.append(
                GhidraRetainedBodyCall(
                    address,
                    function_entry,
                    target,
                    row["computed"],
                )
            )
        else:
            target = _require_uint32(row["target"], f"row {row_number} target")
            references[kind].append(GhidraReference(kind, address, target))

    if len({row.address for row in instructions}) != len(instructions):
        raise GhidraInventoryError("Ghidra inventory has duplicate instructions")
    if len({row.address for row in functions}) != len(functions):
        raise GhidraInventoryError("Ghidra inventory has duplicate functions")

    return GhidraInventory(
        compiler_sha256=compiler_sha256,
        canonical_sha256=hashlib.sha256(canonical).hexdigest(),
        instructions=tuple(instructions),
        functions=tuple(functions),
        body_ranges=tuple(body_ranges),
        calls=tuple(calls),
        typed_flows=tuple(typed_flows),
        retained_body_calls=tuple(retained_body_calls),
        computed_transfers=tuple(references["computed-transfer"]),
        data_references=tuple(references["data-reference"]),
        function_pointer_references=tuple(
            references["function-pointer-reference"]
        ),
    )


def _raw_function_addresses(cfg: RawCfg) -> set[int]:
    return {row.address for row in cfg.function_entries if row.is_function}


def _build_range_contains(
    ranges: tuple[tuple[int, int], ...],
):
    """Return an overlap-safe logarithmic closed-range membership query."""
    starts: list[int] = []
    prefix_max_ends: list[int] = []
    maximum_end = -1
    for start, end in sorted(ranges):
        starts.append(start)
        maximum_end = max(maximum_end, end)
        prefix_max_ends.append(maximum_end)

    def contains(address: int) -> bool:
        index = bisect_right(starts, address) - 1
        return index >= 0 and address <= prefix_max_ends[index]

    return contains


def _residue_intersects(
    residue: UnreachableExecutableResidue, address: int, size: int = 1
) -> bool:
    end = address + size
    return any(address < row.end and row.start < end for row in residue.intervals)


def _residue_bytes(
    residue: UnreachableExecutableResidue, address: int, size: int
) -> bytes | None:
    for row in residue.intervals:
        if row.start <= address and address + size <= row.end:
            payload = bytes.fromhex(row.bytes_hex)
            offset = address - row.start
            return payload[offset : offset + size]
    return None


def _verify_residue_instruction(
    residue: UnreachableExecutableResidue,
    row: GhidraInstruction,
    *,
    decoder: Cs | None = None,
) -> tuple[bool, str]:
    payload = _residue_bytes(residue, row.address, row.size)
    if payload is None:
        return False, "instruction crosses exact residue interval boundary"
    if payload.hex() != row.bytes_hex:
        return (
            False,
            "exact residue bytes differ: "
            f"raw={payload.hex()};ghidra={row.bytes_hex}",
        )
    if decoder is None:
        decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        decoder.detail = False
        decoder.skipdata = False
    decoded = next(decoder.disasm(payload, row.address, count=1), None)
    if (
        decoded is None
        or decoded.address != row.address
        or decoded.size != row.size
        or bytes(decoded.bytes) != payload
    ):
        return False, "exact residue bytes do not decode at the stated boundary"
    return True, f"raw_bytes={row.bytes_hex};size={row.size}"


def _residue_relocation_instruction_evidence(
    residue: UnreachableExecutableResidue,
    instructions: Sequence[GhidraInstruction],
    verified_addresses: set[int],
    source_address: int,
) -> str | None:
    containing = tuple(
        row
        for row in instructions
        if row.address in verified_addresses
        and row.address <= source_address
        and source_address + 4 <= row.address + row.size
    )
    if len(containing) != 1:
        return None
    row = containing[0]
    payload = _residue_bytes(residue, row.address, row.size)
    if payload is None:
        return None
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoder.detail = True
    decoder.skipdata = False
    decoded = next(decoder.disasm(payload, row.address, count=1), None)
    if decoded is None or decoded.size != row.size:
        return None
    offset = source_address - row.address
    fields = tuple(
        name
        for name, field_offset, field_size in (
            ("immediate", decoded.encoding.imm_offset, decoded.encoding.imm_size),
            (
                "displacement",
                decoded.encoding.disp_offset,
                decoded.encoding.disp_size,
            ),
        )
        if field_offset == offset and field_size == 4
    )
    if len(fields) != 1:
        return None
    return (
        f"instruction={row.address:#x};field={fields[0]};"
        f"raw_bytes={row.bytes_hex}"
    )


def compare_ghidra_inventory(
    cfg: RawCfg, inventory: GhidraInventory
) -> CrosscheckReport:
    """Compare without granting Ghidra instruction ownership authority."""
    raw_functions = _raw_function_addresses(cfg)
    ghidra_functions = {row.address for row in inventory.functions}
    raw_instructions = {row.address: row for row in cfg.instructions}
    ghidra_instructions = {row.address: row for row in inventory.instructions}
    shared_sources = {
        address
        for address, instruction in raw_instructions.items()
        if address in ghidra_instructions
        and instruction.bytes_hex == ghidra_instructions[address].bytes_hex
    }

    byte_mismatches = tuple(
        ByteMismatch(address, raw_instructions[address].bytes_hex, row.bytes_hex)
        for address, row in sorted(ghidra_instructions.items())
        if address in raw_instructions
        and raw_instructions[address].bytes_hex != row.bytes_hex
    )
    all_raw_calls = {(row.address, row.target) for row in cfg.direct_calls}
    all_ghidra_calls = {
        (row.address, row.target) for row in inventory.calls if not row.computed
    }
    raw_calls = {
        row for row in all_raw_calls if row[0] in shared_sources
    }
    ghidra_calls = {
        row for row in all_ghidra_calls if row[0] in shared_sources
    }
    raw_typed_flows = set()
    for block in cfg.blocks:
        raw_typed_flows.update(
            (source, target, "fallthrough")
            for source, target in zip(
                block.instruction_addresses,
                block.instruction_addresses[1:],
            )
        )
    for edge in cfg.edges:
        if edge.kind == "direct-call":
            flow_kind = "call"
        elif edge.kind.startswith("indirect-call"):
            flow_kind = "computed-call"
        elif edge.kind == "conditional-branch":
            flow_kind = "conditional-branch"
        elif edge.kind == "unconditional-branch":
            flow_kind = "unconditional-branch"
        elif edge.kind.startswith("indirect-jump"):
            flow_kind = "computed-jump"
        elif edge.kind in {"fallthrough", "call-fallthrough"}:
            flow_kind = "fallthrough"
        else:
            continue
        raw_typed_flows.add((edge.source, edge.target, flow_kind))
    ghidra_typed_flows = {
        (row.address, row.target, row.flow_kind)
        for row in inventory.typed_flows
        if row.address in shared_sources
    }
    raw_typed_flows = {
        row for row in raw_typed_flows if row[0] in shared_sources
    }
    computed_flow_kinds = {"computed-call", "computed-jump"}
    raw_computed_flow_sources = {
        (address, flow_kind)
        for address, _target, flow_kind in raw_typed_flows
        if flow_kind in computed_flow_kinds
    }
    ghidra_computed_flow_sources = {
        (address, flow_kind)
        for address, _target, flow_kind in ghidra_typed_flows
        if flow_kind in computed_flow_kinds
    }
    raw_typed_flows = {
        row for row in raw_typed_flows if row[2] not in computed_flow_kinds
    }
    ghidra_typed_flows = {
        row for row in ghidra_typed_flows if row[2] not in computed_flow_kinds
    }
    raw_computed_transfers = {
        row.source
        for row in cfg.control_targets.finite_internal_edges
        if row.source in shared_sources
        and (
            row.flow_kind.startswith("indirect-call")
            or row.flow_kind.startswith("indirect-jump")
        )
    }
    ghidra_computed_transfers = {
        row.address
        for row in inventory.computed_transfers
        if row.address in shared_sources
    }
    raw_references = {
        record_kind: {
            (row.address, row.target)
            for row in cfg.semantic_references
            if row.record_kind == record_kind
            and row.address in shared_sources
        }
        for record_kind in (
            "data-reference",
            "function-pointer-reference",
        )
    }
    ghidra_references = {
        "data-reference": {
            (row.address, row.target)
            for row in inventory.data_references
            if row.address in shared_sources
        },
        "function-pointer-reference": {
            (row.address, row.target)
            for row in inventory.function_pointer_references
            if row.address in shared_sources
        },
    }
    flow_mismatches = tuple(
        sorted(
            {
                *(
                    FlowMismatch(address, target, "raw-only", "call")
                    for address, target in raw_calls - ghidra_calls
                ),
                *(
                    FlowMismatch(address, target, "ghidra-only", "call")
                    for address, target in ghidra_calls - raw_calls
                ),
                *(
                    FlowMismatch(address, target, "raw-only", flow_kind)
                    for address, target, flow_kind in (
                        raw_typed_flows - ghidra_typed_flows
                    )
                ),
                *(
                    FlowMismatch(address, target, "ghidra-only", flow_kind)
                    for address, target, flow_kind in (
                        ghidra_typed_flows - raw_typed_flows
                    )
                ),
                *(
                    FlowMismatch(address, 0, "raw-only", flow_kind)
                    for address, flow_kind in (
                        raw_computed_flow_sources
                        - ghidra_computed_flow_sources
                    )
                ),
                *(
                    FlowMismatch(address, 0, "ghidra-only", flow_kind)
                    for address, flow_kind in (
                        ghidra_computed_flow_sources
                        - raw_computed_flow_sources
                    )
                ),
                *(
                    FlowMismatch(
                        address,
                        0,
                        "raw-only",
                        "computed-transfer",
                    )
                    for address in (
                        raw_computed_transfers - ghidra_computed_transfers
                    )
                ),
                *(
                    FlowMismatch(
                        address,
                        0,
                        "ghidra-only",
                        "computed-transfer",
                    )
                    for address in (
                        ghidra_computed_transfers - raw_computed_transfers
                    )
                ),
                *(
                    FlowMismatch(address, target, side, record_kind)
                    for record_kind in raw_references
                    for side, differences in (
                        (
                            "raw-only",
                            raw_references[record_kind]
                            - ghidra_references[record_kind],
                        ),
                        (
                            "ghidra-only",
                            ghidra_references[record_kind]
                            - raw_references[record_kind],
                        ),
                    )
                    for address, target in differences
                ),
            },
            key=lambda row: (
                row.address, row.target, row.side, row.flow_kind
            ),
        )
    )

    body_ranges = tuple((row.address, row.end) for row in inventory.body_ranges)
    ghidra_owns = _build_range_contains(body_ranges)

    ownership_mismatches = tuple(
        [
            OwnershipMismatch(address, "raw-only")
            for address in sorted(raw_instructions)
            if not ghidra_owns(address)
        ]
        + [
            OwnershipMismatch(address, "ghidra-only")
            for address in sorted(set(ghidra_instructions) - set(raw_instructions))
        ]
    )
    residue = cfg.provisional_unreachable_residue
    conflicts: set[ResidueConflict] = set()
    dispositions: set[ResidueDisposition] = set()
    residue_instruction_rows = tuple(
        sorted(
            (
                row
                for row in inventory.instructions
                if _residue_intersects(residue, row.address, row.size)
            ),
            key=lambda row: row.address,
        )
    )
    overlapping_instruction_addresses: set[int] = set()
    for previous, current in zip(
        residue_instruction_rows, residue_instruction_rows[1:]
    ):
        if current.address < previous.address + previous.size:
            overlapping_instruction_addresses.update(
                {previous.address, current.address}
            )
    verified_residue_instructions: set[int] = set()
    residue_decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    residue_decoder.detail = False
    residue_decoder.skipdata = False
    for row in residue_instruction_rows:
        if row.address in overlapping_instruction_addresses:
            conflicts.add(
                ResidueConflict(
                    row.address,
                    "instruction",
                    "overlapping Ghidra instruction boundaries in residue",
                )
            )
            continue
        verified, evidence = _verify_residue_instruction(
            residue, row, decoder=residue_decoder
        )
        if not verified:
            conflicts.add(ResidueConflict(row.address, "instruction", evidence))
            continue
        verified_residue_instructions.add(row.address)
        dispositions.add(
            ResidueDisposition(
                row.address,
                "instruction",
                f"bytes={row.bytes_hex}",
                "closed-unreachable-exact-decode",
                evidence,
            )
        )
    for row in inventory.functions:
        if residue.contains(row.address):
            if row.address not in verified_residue_instructions:
                conflicts.add(
                    ResidueConflict(
                        row.address,
                        "function",
                        "no exact independently decoded instruction boundary",
                    )
                )
            else:
                dispositions.add(
                    ResidueDisposition(
                        row.address,
                        "function",
                        f"name={row.name}",
                        "closed-unreachable-exact-decode",
                        "entry coincides with an exact decoded residue instruction; "
                        "Ghidra ownership was not used as a root",
                    )
                )
    for row in inventory.body_ranges:
        overlaps_residue = any(
            interval.start <= row.end and row.address < interval.end
            for interval in residue.intervals
        )
        if overlaps_residue:
            intersecting_instructions = {
                instruction.address
                for instruction in residue_instruction_rows
                if row.address
                <= instruction.address
                <= row.end
                and _residue_intersects(
                    residue, instruction.address, instruction.size
                )
            }
            if (
                not intersecting_instructions
                or not intersecting_instructions
                <= verified_residue_instructions
            ):
                conflicts.add(
                    ResidueConflict(
                        row.address,
                        "function-body-range",
                        "range lacks complete exact decoded residue boundaries: "
                        f"entry={row.function_entry:#x};end={row.end:#x}",
                    )
                )
            else:
                dispositions.add(
                    ResidueDisposition(
                        row.address,
                        "function-body-range",
                        f"entry={row.function_entry:#x};end={row.end:#x}",
                        "closed-unreachable-exact-decode",
                        "every intersecting Ghidra instruction has exact residue "
                        "bytes and an independently decoded boundary",
                    )
                )

    obligations = tuple(
        sorted(
            cfg.publication_reference_obligations,
            key=lambda row: (
                row.reference.reference_start,
                row.reference.reference_end,
                row.reference.target_slot,
                row.certificate_sha256,
            ),
        )
    )
    publication_obligation_set_sha256 = (
        _publication_obligation_set_sha256(obligations)
    )
    duplicate_obligations = len(set(obligations)) != len(obligations)
    expected_obligation_keys = {
        (
            certificate.sha256,
            reference,
            reference.source.current_ownership_sha256,
        )
        for certificate in cfg.publication_noninterference_certificates
        for reference in certificate.reference_inventory.rows
        if isinstance(
            reference.source,
            _PublicationProvisionalExecutableSource,
        )
    }
    actual_obligation_keys = {
        (
            obligation.certificate_sha256,
            obligation.reference,
            obligation.fixed_point_ownership_sha256,
        )
        for obligation in obligations
    }
    ghidra_data_references = {
        (row.address, row.target) for row in inventory.data_references
    }
    publication_reference_reconciliations = []
    passed_publication_reference_pairs: set[tuple[int, int]] = set()
    for obligation in obligations:
        reference = obligation.reference
        source = reference.source
        status = "passed"
        evidence = "exact provisional row and Ghidra data reference agree"
        if duplicate_obligations:
            status = "duplicate-obligation"
            evidence = "the canonical obligation union contains duplicates"
        elif (
            cfg.publication_noninterference_certificates
            and (
                obligation.certificate_sha256,
                obligation.reference,
                obligation.fixed_point_ownership_sha256,
            )
            not in expected_obligation_keys
        ):
            status = "extra-obligation"
            evidence = "obligation is absent from definitive certificates"
        elif not isinstance(
            source, _PublicationProvisionalExecutableSource
        ):
            status = "nonprovisional-source"
            evidence = "only provisional executable sources require reconciliation"
        elif (
            obligation.fixed_point_ownership_sha256
            != source.current_ownership_sha256
        ):
            status = "stale-ownership-digest"
            evidence = "obligation ownership digest differs from its typed source"
        else:
            containing = tuple(
                row
                for row in residue.intervals
                if row.start == source.interval_start
                and row.end == source.interval_end
                and row.bytes_sha256 == source.bytes_sha256
                and row.start <= reference.reference_start
                and reference.reference_end <= row.end
            )
            raw = _residue_bytes(
                residue,
                reference.reference_start,
                reference.reference_end - reference.reference_start,
            )
            if len(containing) != 1:
                status = "stale-provisional-interval"
                evidence = "no exact residue interval matches the typed source"
            elif raw is None or raw.hex() != reference.bytes_hex:
                status = "reference-bytes-differ"
                evidence = "current residue bytes differ from the obligation"
            elif (
                reference.reference_start,
                reference.target_slot,
            ) not in ghidra_data_references:
                status = "missing-ghidra-reference"
                evidence = "Ghidra omitted the exact data-reference row"
            elif any(
                row.address < reference.reference_end
                and reference.reference_start <= row.end
                for row in inventory.body_ranges
            ) or any(
                row.address < reference.reference_end
                and reference.reference_start < row.address + row.size
                for row in inventory.instructions
            ):
                status = "overlapping-ghidra-ownership"
                evidence = "Ghidra claims code ownership overlapping the reference span"
        reconciliation = PublicationReferenceReconciliation(
            certificate_sha256=obligation.certificate_sha256,
            reference_start=reference.reference_start,
            reference_end=reference.reference_end,
            bytes_hex=reference.bytes_hex,
            target_slot=reference.target_slot,
            status=status,
            evidence=evidence,
        )
        publication_reference_reconciliations.append(reconciliation)
        if status == "passed":
            passed_publication_reference_pairs.add(
                (reference.reference_start, reference.target_slot)
            )
            dispositions.add(
                ResidueDisposition(
                    reference.reference_start,
                    "publication-reference",
                    f"target={reference.target_slot:#x}",
                    "reconciled-publication-reference",
                    evidence,
                )
            )
    if cfg.publication_noninterference_certificates:
        for certificate_sha256, reference, ownership_sha256 in sorted(
            expected_obligation_keys - actual_obligation_keys,
            key=lambda row: (
                row[1].reference_start,
                row[1].reference_end,
                row[0],
            ),
        ):
            publication_reference_reconciliations.append(
                PublicationReferenceReconciliation(
                    certificate_sha256=certificate_sha256,
                    reference_start=reference.reference_start,
                    reference_end=reference.reference_end,
                    bytes_hex=reference.bytes_hex,
                    target_slot=reference.target_slot,
                    status="missing-obligation",
                    evidence=(
                        "definitive certificate provisional row is absent "
                        "from the obligation union;ownership="
                        + ownership_sha256
                    ),
                )
            )
    protected_slots = {
        obligation.reference.target_slot for obligation in obligations
    } | {
        certificate.publication_slot
        for certificate in cfg.publication_noninterference_certificates
    }
    known_reference_pairs = {
        (reference.reference_start, reference.target_slot)
        for certificate in cfg.publication_noninterference_certificates
        for reference in certificate.reference_inventory.rows
    } | {
        (
            obligation.reference.reference_start,
            obligation.reference.target_slot,
        )
        for obligation in obligations
    }
    for address, target in sorted(ghidra_data_references):
        if (
            target in protected_slots
            and (address, target) not in known_reference_pairs
        ):
            publication_reference_reconciliations.append(
                PublicationReferenceReconciliation(
                    certificate_sha256="",
                    reference_start=address,
                    reference_end=address,
                    bytes_hex="",
                    target_slot=target,
                    status="extra-ghidra-reference",
                    evidence=(
                        "Ghidra reported a protected-slot reference absent "
                        "from the exact internal inventory"
                    ),
                )
            )
    semantic_rows = (
        *(('call', row.address, row.target) for row in inventory.calls),
        *(("typed-flow", row.address, row.target) for row in inventory.typed_flows),
        *(
            ("computed-transfer", row.address, row.target)
            for row in inventory.computed_transfers
        ),
        *(
            ("data-reference", row.address, row.target)
            for row in inventory.data_references
        ),
        *(
            ("function-pointer-reference", row.address, row.target)
            for row in inventory.function_pointer_references
        ),
    )
    for fact_kind, address, target in semantic_rows:
        source_in_residue = residue.contains(address)
        target_in_residue = bool(target and residue.contains(target))
        if source_in_residue:
            if (
                fact_kind == "data-reference"
                and (address, target)
                in passed_publication_reference_pairs
            ):
                continue
            if address not in verified_residue_instructions:
                conflicts.add(
                    ResidueConflict(
                        address,
                        fact_kind,
                        "source lacks exact independently decoded residue boundary",
                    )
                )
                continue
            dispositions.add(
                ResidueDisposition(
                    address,
                    fact_kind,
                    f"target={target:#x}",
                    "closed-unreachable-exact-decode",
                    "semantic source is an exact decoded instruction inside the "
                    "closed raw unreachable partition",
                )
            )
        elif target_in_residue:
            conflicts.add(
                ResidueConflict(
                    address,
                    fact_kind,
                    f"incoming target={target:#x}",
                )
            )
    reconciled_relocation_addresses: set[int] = set()
    for row in cfg.relocation_dispositions:
        if (
            row.source_class != "residue"
            or row.status
            not in {"unresolved-exec-pointer", "unmapped-anomaly"}
            or not residue.contains(row.source_address, 4)
        ):
            continue
        raw = _residue_bytes(residue, row.source_address, 4)
        if raw is None or raw.hex() != row.source_bytes_hex:
            continue
        marker = _residue_bytes(
            residue,
            _RETAIL_NINJI_MARKER_START,
            len(_RETAIL_NINJI_MARKER),
        )
        if (
            inventory.compiler_sha256 == _RETAIL_SHA256
            and marker == _RETAIL_NINJI_MARKER
            and _RETAIL_NINJI_MARKER_START <= row.source_address
            and row.source_address + 4
            <= _RETAIL_NINJI_MARKER_START + len(_RETAIL_NINJI_MARKER)
        ):
            classification = "exact-retail-noncode-marker"
            evidence = (
                f"marker_start={_RETAIL_NINJI_MARKER_START:#x};"
                f"marker_sha256={hashlib.sha256(marker).hexdigest()};"
                f"source_bytes={row.source_bytes_hex}"
            )
        else:
            instruction_evidence = _residue_relocation_instruction_evidence(
                residue,
                residue_instruction_rows,
                verified_residue_instructions,
                row.source_address,
            )
            if instruction_evidence is None:
                continue
            classification = "closed-unreachable-exact-decode"
            evidence = instruction_evidence
        reconciled_relocation_addresses.add(row.source_address)
        dispositions.add(
            ResidueDisposition(
                row.source_address,
                "relocation",
                f"target={row.target_address:#x};status={row.status}",
                classification,
                evidence,
            )
        )
    unresolved = tuple(
        sorted(
            {
                row.address
                for row in cfg.ownership_diagnostics
                if row.kind
                in {
                    "computed-flow-blocker",
                    "indirect-flow",
                    "unsupported-far-flow",
                    "unresolved-relocation-obligation",
                    "external-code-pointer-escape",
                    "object-callback-table-blocker",
                }
                and not (
                    row.kind == "unresolved-relocation-obligation"
                    and row.address in reconciled_relocation_addresses
                )
            }
        )
    )
    retained_body_calls = inventory.retained_body_calls
    raw_e8_calls = {
        (row.address, row.target) for row in cfg.raw_e8_candidates
    }
    union_calls = raw_e8_calls | all_ghidra_calls
    arena_targets = {0x00441F20, 0x00441F60, 0x00441FA0, 0x00441FE0}
    pcode_helper_targets = {
        0x0049CF90,
        0x0049D010,
        0x0049D060,
        0x0049D270,
        0x004A25D0,
        0x004A2620,
        0x004CE1A0,
        0x004A3590,
    }
    retained = (
        RegressionAssertion(
            "ghidra-functions-and-direct-calls-in-bodies",
            len(inventory.functions),
            len(retained_body_calls),
            3_187,
            27_020,
        ),
        RegressionAssertion(
            "raw-ghidra-union-arena-calls-vs-ghidra-bodies",
            len([target for _, target in union_calls if target in arena_targets]),
            len(
                [
                    row
                    for row in retained_body_calls
                    if row.target in arena_targets
                ]
            ),
            1_861,
            1_825,
        ),
        RegressionAssertion(
            "raw-selected-pcode-helper-calls-vs-ghidra-bodies",
            len(
                [
                    row
                    for row in cfg.raw_e8_candidates
                    if row.target in pcode_helper_targets
                ]
            ),
            len(
                [
                    row
                    for row in retained_body_calls
                    if row.target in pcode_helper_targets
                ]
            ),
            962,
            773,
        ),
        RegressionAssertion(
            "raw-unlink-helper-calls-vs-ghidra-bodies",
            len(
                [
                    row
                    for row in cfg.raw_e8_candidates
                    if row.target == 0x0049D010
                ]
            ),
            len(
                [
                    row
                    for row in retained_body_calls
                    if row.target == 0x0049D010
                ]
            ),
            102,
            59,
        ),
    )
    residue_conflicts = tuple(
        sorted(
            conflicts,
            key=lambda row: (row.address, row.fact_kind, row.detail),
        )
    )
    residue_dispositions = tuple(
        sorted(
            dispositions,
            key=lambda row: (
                row.address,
                row.fact_kind,
                row.detail,
                row.classification,
                row.evidence,
            ),
        )
    )
    blocking_ghidra_only = any(
        row.side == "ghidra-only" for row in flow_mismatches
    )
    reconciliation_sha256 = None
    publication_reconciled = all(
        row.status == "passed"
        for row in publication_reference_reconciliations
    )
    if (
        not unresolved
        and not residue_conflicts
        and not byte_mismatches
        and not blocking_ghidra_only
        and publication_reconciled
    ):
        reconciliation_sha256 = hashlib.sha256(
            _canonical_json(
                {
                    "executable_partition_sha256": (
                        residue.executable_partition_sha256
                    ),
                    "ghidra_inventory_sha256": inventory.canonical_sha256,
                    "reachable_ownership_sha256": (
                        residue.reachable_ownership_sha256
                    ),
                    "publication_obligation_set_sha256": (
                        publication_obligation_set_sha256
                    ),
                    "publication_reference_reconciliations": [
                        asdict(row)
                        for row in publication_reference_reconciliations
                    ],
                    "residue_dispositions": [
                        asdict(row) for row in residue_dispositions
                    ],
                }
            )
        ).hexdigest()
    return CrosscheckReport(
        compiler_sha256=inventory.compiler_sha256,
        ghidra_inventory_sha256=inventory.canonical_sha256,
        raw_only_functions=tuple(sorted(raw_functions - ghidra_functions)),
        ghidra_only_functions=tuple(sorted(ghidra_functions - raw_functions)),
        byte_mismatches=byte_mismatches,
        flow_mismatches=flow_mismatches,
        ownership_mismatches=ownership_mismatches,
        residue_conflicts=residue_conflicts,
        residue_dispositions=residue_dispositions,
        publication_obligation_set_sha256=(
            publication_obligation_set_sha256
        ),
        publication_reference_reconciliations=tuple(
            publication_reference_reconciliations
        ),
        residue_reconciliation_sha256=reconciliation_sha256,
        unresolved_raw_addresses=unresolved,
        retained_regression_assertions=retained,
        formatoperands_dispatch=None,
    )


def accept_reconciled_residue(
    cfg: RawCfg, report: CrosscheckReport
) -> RawCfg:
    """Return the immutable CFG with only the reconciled residue accepted."""
    report.require_publishable()
    current_obligation_sha256 = _publication_obligation_set_sha256(
        cfg.publication_reference_obligations
    )
    if current_obligation_sha256 != report.publication_obligation_set_sha256:
        raise GhidraInventoryError(
            "publication reference obligation set changed after crosscheck"
        )
    digest = report.residue_reconciliation_sha256
    if digest is None:
        raise GhidraInventoryError(
            "unreachable executable residue was not reconciled"
        )
    reconciled_relocations = {
        row.address: row.classification
        for row in report.residue_dispositions
        if row.fact_kind == "relocation"
        and row.classification
        in {
            "closed-unreachable-exact-decode",
            "exact-retail-noncode-marker",
        }
    }
    return replace(
        cfg,
        provisional_unreachable_residue=replace(
            cfg.provisional_unreachable_residue,
            accepted=True,
            reconciliation_sha256=digest,
        ),
        ownership_diagnostics=tuple(
            row
            for row in cfg.ownership_diagnostics
            if not (
                row.kind == "unresolved-relocation-obligation"
                and row.address in reconciled_relocations
            )
        ),
        control_targets=replace(
            cfg.control_targets,
            unresolved=tuple(
                row
                for row in cfg.control_targets.unresolved
                if not (
                    row.kind == "unresolved-relocation-obligation"
                    and row.address in reconciled_relocations
                )
            ),
        ),
        relocation_dispositions=tuple(
            replace(
                row,
                status=(
                    "reconciled-retail-noncode-marker"
                    if reconciled_relocations.get(row.source_address)
                    == "exact-retail-noncode-marker"
                    else "reconciled-unreachable-residue-code"
                ),
                provenance=(
                    row.provenance
                    + ";crosscheck="
                    + reconciled_relocations[row.source_address]
                ),
            )
            if row.source_address in reconciled_relocations
            else row
            for row in cfg.relocation_dispositions
        ),
    )


def _instruction_reaches(cfg: RawCfg, start: int, goal: int) -> bool:
    return goal in _reachable_instructions(cfg, start)


def _reachable_instructions(cfg: RawCfg, start: int) -> set[int]:
    successors: dict[int, set[int]] = {}
    for block in cfg.blocks:
        for left, right in zip(
            block.instruction_addresses,
            block.instruction_addresses[1:],
        ):
            successors.setdefault(left, set()).add(right)
    for edge in cfg.edges:
        if "call" in edge.kind and not edge.kind.endswith("fallthrough"):
            continue
        successors.setdefault(edge.source, set()).add(edge.target)

    pending = [start]
    seen: set[int] = set()
    while pending:
        address = pending.pop()
        if address in seen:
            continue
        seen.add(address)
        pending.extend(sorted(successors.get(address, ()), reverse=True))
    return seen


def validate_gc125n_formatoperands(image: Image, cfg: RawCfg) -> dict[str, Any]:
    """Require the exact 466-entry real-opcode formatter dispatch closure."""
    compiler_sha256 = (
        "ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c"
    )
    if image.sha256 != compiler_sha256:
        raise GhidraInventoryError(
            "formatoperands validation requires the exact GC/1.2.5n compiler"
        )
    instructions = {row.address: row for row in cfg.instructions}
    exact_instructions = {
        0x004C4BF0: "53",
        0x004C4C01: "81fad1010000",
        0x004C4C07: "0f8733120000",
        0x004C4C0D: "ff24957c285600",
    }
    for address, expected_bytes in exact_instructions.items():
        instruction = instructions.get(address)
        if instruction is None or instruction.bytes_hex != expected_bytes:
            raise GhidraInventoryError(
                "formatoperands instruction differs: "
                f"address={address:#x};actual="
                f"{None if instruction is None else instruction.bytes_hex};"
                f"expected={expected_bytes}"
            )
    if not _instruction_reaches(cfg, 0x004C4BF0, 0x004C4C01):
        raise GhidraInventoryError(
            "formatoperands entry does not reach the dispatch compare"
        )
    try:
        table = cfg.jump_table_at(0x004C4C0D)
    except KeyError as exc:
        raise GhidraInventoryError(
            "formatoperands computed dispatch was not recovered"
        ) from exc
    expected = {
        "guard_address": 0x004C4C01,
        "guard_operator": "ja",
        "guard_bound": 0x1D1,
        "base": 0x0056287C,
        "entry_width": 4,
        "index_min": 0,
        "index_max": 465,
    }
    for field_name, expected_value in expected.items():
        if getattr(table, field_name) != expected_value:
            raise GhidraInventoryError(
                "formatoperands dispatch differs: "
                f"{field_name}={getattr(table, field_name)!r};"
                f"expected={expected_value!r}"
            )
    if len(table.raw_entries) != 466 or len(table.targets) != 466:
        raise GhidraInventoryError(
            "formatoperands dispatch must contain exactly 466 entries"
        )
    relocation_types = {
        row.va: row.type
        for row in image.relocations
        if 0x0056287C <= row.va < 0x00562FCC
    }
    for index in range(466):
        slot = 0x0056287C + index * 4
        if relocation_types.get(slot) != 3:
            raise GhidraInventoryError(
                f"formatoperands table slot lacks type-3 relocation: {slot:#x}"
            )
    following = (
        int.from_bytes(image.read(0x00562FC4, 4), "little"),
        int.from_bytes(image.read(0x00562FC8, 4), "little"),
    )
    if following != (0x2D, 0x4228):
        raise GhidraInventoryError(
            "formatoperands post-table values differ: "
            f"actual={following!r};expected={(0x2D, 0x4228)!r}"
        )
    if any(slot in relocation_types for slot in (0x00562FC4, 0x00562FC8)):
        raise GhidraInventoryError(
            "formatoperands post-table non-code values are relocated"
        )
    required_edges = {
        (0x004C4C07, 0x004C5E40, "conditional-branch"),
        (0x004C4C07, 0x004C4C0D, "fallthrough"),
    }
    observed_edges = {(row.source, row.target, row.kind) for row in cfg.edges}
    if not required_edges <= observed_edges:
        raise GhidraInventoryError(
            "formatoperands default/fallthrough typed edges differ"
        )
    table_edges = {
        row.target
        for row in cfg.edges
        if row.source == table.address and row.kind == "indirect-jump-table"
    }
    if table_edges != set(table.targets):
        raise GhidraInventoryError(
            "formatoperands indexed typed edges differ from table targets"
        )
    table_sha256 = hashlib.sha256(
        b"".join(struct.pack("<I", value) for value in table.raw_entries)
    ).hexdigest()
    expected_sha256 = "575e165f8bfb3a01076871267f1fed9f5844219f9de565ff0941fd8b312afac7"
    if table_sha256 != expected_sha256:
        raise GhidraInventoryError(
            "formatoperands table digest differs: "
            f"actual={table_sha256};expected={expected_sha256}"
        )

    exit_address = 0x004C5E51
    missing_exit = tuple(
        target
        for target in sorted(set(table.targets))
        if not _instruction_reaches(cfg, target, exit_address)
    )
    if missing_exit:
        raise GhidraInventoryError(
            "formatoperands cases do not close through the shared exit: "
            + ",".join(f"{address:#x}" for address in missing_exit)
        )
    if not _instruction_reaches(cfg, exit_address, 0x004C5F25):
        raise GhidraInventoryError(
            "formatoperands shared exit does not reach the sole return"
        )
    if not _instruction_reaches(cfg, 0x004C5E40, exit_address):
        raise GhidraInventoryError(
            "formatoperands default path does not reach the shared exit"
        )
    closure = _reachable_instructions(cfg, 0x004C4BF0)
    returns = {
        row.address
        for row in cfg.instructions
        if row.address in closure and row.mnemonic.startswith("ret")
    }
    if returns != {0x004C5F25}:
        raise GhidraInventoryError(
            "formatoperands reachable return set differs: "
            + ",".join(f"{address:#x}" for address in sorted(returns))
        )
    unresolved = {
        row.address
        for row in cfg.control_targets.unresolved
        if row.address in closure
    }
    if unresolved:
        raise GhidraInventoryError(
            "formatoperands closure has unresolved control: "
            + ",".join(f"{address:#x}" for address in sorted(unresolved))
        )
    return {
        "function_address": 0x004C4BF0,
        "transfer_address": table.address,
        **expected,
        "entry_count": len(table.raw_entries),
        "distinct_target_count": len(set(table.targets)),
        "table_sha256": table_sha256,
        "shared_exit": exit_address,
        "sole_return": 0x004C5F25,
        "pseudo_op_metadata_ids_excluded_from_dispatch": [466, 467],
    }


def classify_historical_control_diagnostics(
    cfg: RawCfg,
    historical_rows: Sequence[Mapping[str, object]],
    *,
    expected_count: int | None = None,
) -> HistoricalControlManifest:
    """Classify frozen pre-proof diagnostics without using them as roots."""
    if expected_count is not None and len(historical_rows) != expected_count:
        raise GhidraInventoryError(
            "historical control fixture count differs: "
            f"expected={expected_count};actual={len(historical_rows)}"
        )
    fixture_payload = _canonical_json(list(historical_rows))
    fixture_sha256 = hashlib.sha256(fixture_payload).hexdigest()
    finite_by_source: dict[int, set[tuple[str, int]]] = {}
    for edge in cfg.control_targets.finite_internal_edges:
        # The historical rows were computed/indirect transfers.  Their
        # ordinary call-fallthrough edge may survive even when the historical
        # transfer itself was deleted as an unsound decode.
        if not edge.flow_kind.startswith("indirect-"):
            continue
        finite_by_source.setdefault(edge.source, set()).add(
            (edge.flow_kind, edge.target)
        )
    terminal_by_source: dict[int, set[tuple[str, int, str, str]]] = {}
    for edge in cfg.control_targets.terminal_external_edges:
        terminal_by_source.setdefault(edge.source, set()).add(
            (
                edge.flow_kind,
                edge.iat_va,
                edge.dll,
                edge.name
                if edge.name is not None
                else f"ordinal:{edge.ordinal}",
            )
        )
    blockers_by_source: dict[int, set[tuple[str, str]]] = {}
    for row in cfg.control_targets.unresolved:
        blockers_by_source.setdefault(row.address, set()).add(
            (row.kind, row.detail)
        )

    dispositions = []
    seen_rows: set[tuple[int, str, str]] = set()
    for index, row in enumerate(historical_rows):
        if set(row) != {"address", "kind", "detail"}:
            raise GhidraInventoryError(
                f"historical control row {index} has unknown/missing fields"
            )
        address = row["address"]
        kind = row["kind"]
        detail = row["detail"]
        if (
            not isinstance(address, int)
            or isinstance(address, bool)
            or not isinstance(kind, str)
            or not isinstance(detail, str)
        ):
            raise GhidraInventoryError(
                f"historical control row {index} has invalid field types"
            )
        identity = (address, kind, detail)
        if identity in seen_rows:
            raise GhidraInventoryError(
                f"duplicate historical control row at {address:#x}"
            )
        seen_rows.add(identity)
        if address in blockers_by_source:
            classification = "current-blocker"
            evidence = "|".join(
                f"{current_kind}:{current_detail}"
                for current_kind, current_detail in sorted(
                    blockers_by_source[address]
                )
            )
        elif address in terminal_by_source:
            classification = "terminal-external"
            evidence = "|".join(
                f"{flow_kind}->{iat:#x}:{dll}!{name}"
                for flow_kind, iat, dll, name in sorted(
                    terminal_by_source[address]
                )
            )
        elif address in finite_by_source:
            classification = "resolved-internal"
            evidence = "|".join(
                f"{flow_kind}->{target:#x}"
                for flow_kind, target in sorted(finite_by_source[address])
            )
        else:
            classification = "deleted-unsound-or-unreachable"
            evidence = "absent-from-final-owned-control-sources"
        dispositions.append(
            HistoricalControlDisposition(
                address=address,
                historical_kind=kind,
                historical_detail=detail,
                classification=classification,
                current_evidence=evidence,
            )
        )
    rows = tuple(dispositions)
    canonical_sha256 = hashlib.sha256(
        _canonical_json([asdict(row) for row in rows])
    ).hexdigest()
    return HistoricalControlManifest(
        fixture_sha256=fixture_sha256,
        rows=rows,
        canonical_sha256=canonical_sha256,
    )


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _validate_regular_file(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise StaticBundleError(f"{label} is missing") from exc
    if not stat.S_ISREG(mode) or path.is_symlink():
        raise StaticBundleError(f"{label} must be a regular file")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _inject(
    failure_injector: Callable[[str], None] | None, event: str
) -> None:
    if failure_injector is not None:
        failure_injector(event)


def _write_new_fsynced(
    path: Path,
    payload: bytes,
    *,
    failure_injector: Callable[[str], None] | None,
    event_prefix: str,
) -> None:
    with path.open("xb") as output:
        output.write(payload)
        output.flush()
        _inject(failure_injector, f"{event_prefix}:write")
        os.fsync(output.fileno())
        _inject(failure_injector, f"{event_prefix}:fsync")


def _manifest_payload(
    members: Mapping[str, bytes], compiler_sha256: str
) -> tuple[bytes, dict[str, dict[str, object]]]:
    metadata = {
        name: {
            "size": len(members[name]),
            "sha256": hashlib.sha256(members[name]).hexdigest(),
        }
        for name in STATIC_BUNDLE_MEMBERS
    }
    return (
        _canonical_json(
            {
                "schema_version": STATIC_BUNDLE_SCHEMA,
                "compiler_sha256": compiler_sha256,
                "members": [
                    {"name": name, **metadata[name]}
                    for name in STATIC_BUNDLE_MEMBERS
                ],
            }
        ),
        metadata,
    )


def publish_static_backend_bundle(
    output_root: Path,
    members: Mapping[str, bytes],
    *,
    compiler_sha256: str,
    failure_injector: Callable[[str], None] | None = None,
) -> PublishedStaticBundle:
    """Publish all transitional members through one atomic pointer switch."""
    output_root = Path(output_root)
    if not _HEX_64.fullmatch(compiler_sha256):
        raise StaticBundleError("compiler SHA-256 is malformed")
    if set(members) != set(STATIC_BUNDLE_MEMBERS) or any(
        not isinstance(payload, bytes) for payload in members.values()
    ):
        raise StaticBundleError("static bundle member set differs")
    output_root.mkdir(parents=True, exist_ok=True)
    generations = output_root / "generations"
    if generations.exists() and (
        generations.is_symlink() or not generations.is_dir()
    ):
        raise StaticBundleError("generations must be a regular directory")
    generations.mkdir(exist_ok=True)

    manifest_payload, _ = _manifest_payload(members, compiler_sha256)
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    generation = f"gen-{manifest_sha256}"
    final_dir = generations / generation
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=generations))
    renamed = False
    try:
        for name in STATIC_BUNDLE_MEMBERS:
            _write_new_fsynced(
                staging / name,
                members[name],
                failure_injector=failure_injector,
                event_prefix=f"member:{name}",
            )
        _write_new_fsynced(
            staging / "MANIFEST.json",
            manifest_payload,
            failure_injector=failure_injector,
            event_prefix="manifest",
        )
        _fsync_directory(staging)
        _inject(failure_injector, "staging-directory:fsync")
        if final_dir.exists():
            existing = final_dir / "MANIFEST.json"
            _validate_regular_file(existing, "existing generation manifest")
            if existing.read_bytes() != manifest_payload:
                raise StaticBundleError("immutable generation manifest differs")
            for name in STATIC_BUNDLE_MEMBERS:
                _validate_regular_file(
                    final_dir / name, f"existing generation member {name}"
                )
                if (final_dir / name).read_bytes() != members[name]:
                    raise StaticBundleError(
                        f"immutable generation member differs: {name}"
                    )
        else:
            os.rename(staging, final_dir)
            renamed = True
            _inject(failure_injector, "generation:rename")
        _fsync_directory(generations)
        _inject(failure_injector, "generations-directory:fsync")

        pointer_payload = _canonical_json(
            {
                "schema_version": STATIC_CURRENT_SCHEMA,
                "generation": generation,
                "manifest_sha256": manifest_sha256,
            }
        )
        pointer_temp = output_root / f".CURRENT.{os.getpid()}.tmp"
        pointer_temp.unlink(missing_ok=True)
        try:
            _write_new_fsynced(
                pointer_temp,
                pointer_payload,
                failure_injector=failure_injector,
                event_prefix="current",
            )
            os.replace(pointer_temp, output_root / "CURRENT")
            _inject(failure_injector, "current:replace")
        finally:
            pointer_temp.unlink(missing_ok=True)
        _fsync_directory(output_root)
        _inject(failure_injector, "output-root:fsync")
    finally:
        if not renamed and staging.exists():
            for child in staging.iterdir():
                child.unlink(missing_ok=True)
            staging.rmdir()
    return resolve_static_backend_bundle(output_root)


def resolve_static_backend_bundle(output_root: Path) -> PublishedStaticBundle:
    """Resolve and validate exactly one whole immutable generation."""
    output_root = Path(output_root)
    current = output_root / "CURRENT"
    _validate_regular_file(current, "CURRENT pointer")
    try:
        pointer = json.loads(current.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StaticBundleError("CURRENT pointer is invalid JSON") from exc
    if not isinstance(pointer, dict) or set(pointer) != {
        "schema_version",
        "generation",
        "manifest_sha256",
    }:
        raise StaticBundleError("CURRENT pointer fields differ")
    if pointer["schema_version"] != STATIC_CURRENT_SCHEMA:
        raise StaticBundleError("CURRENT pointer schema differs")
    generation = pointer["generation"]
    if not isinstance(generation, str) or not _GENERATION_NAME.fullmatch(
        generation
    ):
        raise StaticBundleError("CURRENT generation name is invalid")
    manifest_sha256 = pointer["manifest_sha256"]
    if not isinstance(manifest_sha256, str) or not _HEX_64.fullmatch(
        manifest_sha256
    ):
        raise StaticBundleError("CURRENT manifest SHA-256 is malformed")
    generation_dir = output_root / "generations" / generation
    if generation_dir.is_symlink() or not generation_dir.is_dir():
        raise StaticBundleError("CURRENT generation must be a regular directory")
    manifest_path = generation_dir / "MANIFEST.json"
    _validate_regular_file(manifest_path, "static bundle manifest")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
        raise StaticBundleError("manifest hash differs from CURRENT")
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StaticBundleError("static bundle manifest is invalid JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "compiler_sha256",
        "members",
    }:
        raise StaticBundleError("static bundle manifest fields differ")
    if manifest["schema_version"] != STATIC_BUNDLE_SCHEMA:
        raise StaticBundleError("static bundle manifest schema differs")
    compiler_sha256 = manifest["compiler_sha256"]
    if not isinstance(compiler_sha256, str) or not _HEX_64.fullmatch(
        compiler_sha256
    ):
        raise StaticBundleError("manifest compiler SHA-256 is malformed")
    rows = manifest["members"]
    if not isinstance(rows, list) or len(rows) != len(STATIC_BUNDLE_MEMBERS):
        raise StaticBundleError("static bundle manifest member set differs")
    metadata: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"name", "size", "sha256"}:
            raise StaticBundleError("static bundle member metadata differs")
        name = row["name"]
        size = row["size"]
        digest = row["sha256"]
        if (
            name not in STATIC_BUNDLE_MEMBERS
            or name in metadata
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or not _HEX_64.fullmatch(digest)
        ):
            raise StaticBundleError("static bundle member metadata is invalid")
        metadata[name] = {"size": size, "sha256": digest}
    if tuple(sorted(metadata)) != STATIC_BUNDLE_MEMBERS:
        raise StaticBundleError("static bundle manifest member names differ")
    bundle = PublishedStaticBundle(
        output_root=output_root,
        generation=generation,
        generation_dir=generation_dir,
        manifest_sha256=manifest_sha256,
        compiler_sha256=compiler_sha256,
        members=metadata,
    )
    for name in STATIC_BUNDLE_MEMBERS:
        bundle.path(name)
    return bundle


def _write_atomic(path: Path, payload: bytes) -> None:
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


def write_crosscheck_atomic(path: Path, report: CrosscheckReport) -> None:
    payload = crosscheck_json_bytes(report)
    _write_atomic(path, payload)


def crosscheck_json_bytes(report: CrosscheckReport) -> bytes:
    return (
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


# ── Task 6: Lifetime site inventory ──────────────────────────────────────


_RETAIL_SHA256 = "ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c"
_ARENA_TARGETS = frozenset({0x00441F20, 0x00441F60, 0x00441FA0, 0x00441FE0})
_PCODE_ALLOCATION_SITES = frozenset(
    {0x004636DE, 0x0046374D, 0x00463770, 0x0049D29A, 0x0049D2AF, 0x004A26CF}
)
_REVIEWED_OBJOBJECT_ALLOCATION_SITES = frozenset(
    {
        0x00437CD8,
        0x004775CA,
        0x00488652,
        0x00488A10,
        0x00488B7C,
        0x0048C143,
        0x0048FF4A,
        0x0048FF93,
        0x0048FFD8,
        0x00490063,
        0x004900A8,
        0x00490138,
        0x004901A3,
        0x0049790C,
        0x0049D3BF,
        0x0049DB30,
        0x0049EDD8,
        0x0049F0DA,
        0x004AC56F,
        0x004BB099,
        0x004C0E68,
        0x004EA5E6,
        0x0050FA04,
        0x0050FAFE,
        0x00518170,
        0x00518179,
        0x0051FFDA,
        0x00531879,
    }
)
_REVIEWED_NON_OBJOBJECT_0X36_ALLOCATION_SITES = frozenset({0x0051C710})
_TARGET_OBJECT_ARENAS = frozenset({0x00441FA0, 0x00441FE0})
_UNLINK_TARGET = 0x0049D010
_INSERT_TARGETS = frozenset({0x0049CF90, 0x0049CFD0, 0x0049D060})
_CREATE_UNLINKED_TARGETS = frozenset({0x004A2620, 0x0049D270})
_GENERATION_TARGETS = {
    0x00441EA0: ("temporary-arena-rewind", (0x00441FA0,)),
    0x00442020: ("persistent-arena-release", (0x00441FE0,)),
    0x00442050: ("all-compiler-arenas-release", tuple(sorted(_ARENA_TARGETS))),
}
_REUSE_TRANSITIONS = {
    0x004356B5: "objobject-cache-release",
    0x00435857: "objobject-cache-release",
    0x00435AD3: "objobject-cache-release",
    0x00437CC1: "objobject-cache-acquire",
}
_MUTATION_SITES = {
    0x004CE1E7: "operand-register-physical-rewrite",
    0x004CE20B: "unlink-redundant-move-after-coloring",
    0x00530BA6: "set-operand-first-use-flag",
    0x00531254: "rewrite-register-to-coalesce-root",
    0x005311BD: "unlink-redundant-coalesced-move",
    0x004A32E0: "replace-opcode-operands-and-insert-long-form",
    0x00531800: "spill-and-rewrite-pass",
    0x0049D270: "clone-pcode-lineage",
}
_REWRITE_SITE_ADDRESSES = frozenset(
    {0x004CE1E7, 0x00530BA6, 0x00531254, 0x004A32E0, 0x00531800, 0x0049D270}
)
_EMISSION_SITES = {
    0x004A2B70: "walk-final-block-pcode-lists-and-filter-pseudo-ops",
    0x004A2D17: "sole-per-pcode-encoder-call",
    0x004A2D2B: "write-encoded-machine-word-to-code-buffer",
    0x004A3590: "encode-one-final-pcode",
}
_REVIEWED_RETAIL_UNLINK_CLASSIFICATIONS = {
    # This loop removes opcode-zero records and moves every other record into
    # the merged block.  The raw site therefore belongs to the move operation,
    # while its exact conditional delete edge remains in provenance.
    0x004C61E2: "move-reinsert",
    # This deletion finishes the preceding opcode-zero cleanup.  Later PCode
    # construction in the same large pass belongs to independent list work.
    0x005254D6: "delete",
    # The replacement is inserted immediately before the old record is
    # unlinked; value widening obscures the two local pointer identities.
    0x0052917F: "replace",
}
@dataclass(frozen=True, slots=True)
class AllocationSite:
    address: int
    function_entry: int
    allocator: int
    classification: str
    size: AbstractValue
    returned_type: str
    initialization_sites: tuple[int, ...]
    ownership: str
    raw_e8_classification: str
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LifecycleSite:
    address: int
    classification: str
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GenerationBoundarySite:
    address: int
    target: int
    classification: str
    affected_arenas: tuple[int, ...]
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnlinkSite:
    address: int
    function_entry: int
    classification: str
    following_effect_sites: tuple[int, ...]
    ownership: str
    raw_e8_classification: str
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FieldWriteSite:
    address: int
    function_entry: int
    object_type: str
    field: str
    offset: int
    width: int
    operation: str
    value: AbstractValue
    allocation_site: int | None
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HookCaptureFact:
    address: int
    event: str
    object_type: str


@dataclass(frozen=True, slots=True)
class UnresolvedLifetimeSite:
    address: int
    kind: str
    detail: str
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LifetimeSiteInventory:
    """Closed, typed lifecycle inventory derived from Task 4 and Task 5 facts."""

    compiler_sha256: str
    cfg_instruction_hash: str
    allocations: tuple[AllocationSite, ...]
    reuses: tuple[LifecycleSite, ...]
    releases: tuple[GenerationBoundarySite, ...]
    unlink_classifications: tuple[UnlinkSite, ...]
    field_writes: tuple[FieldWriteSite, ...]
    mutation_sites: tuple[LifecycleSite, ...]
    rewrite_sites: tuple[LifecycleSite, ...]
    emission_sites: tuple[LifecycleSite, ...]
    hook_capture_facts: tuple[HookCaptureFact, ...]
    unresolved: tuple[UnresolvedLifetimeSite, ...]
    high_water_marks: tuple[tuple[str, int], ...]
    proof_ready: bool = False

    def allocation_at(self, address: int) -> AllocationSite:
        rows = tuple(row for row in self.allocations if row.address == address)
        if len(rows) != 1:
            raise KeyError(f"no unique allocation at {address:#x}")
        return rows[0]

    def unlink_at(self, address: int) -> UnlinkSite:
        rows = tuple(
            row for row in self.unlink_classifications if row.address == address
        )
        if len(rows) != 1:
            raise KeyError(f"no unique unlink at {address:#x}")
        return rows[0]


def _joined_call_argument(
    values: AnalysisResult, address: int, index: int
) -> tuple[AbstractValue, int, str]:
    rows = tuple(row for row in values.calls if row.address == address)
    if not rows:
        return AbstractValue(kind="bottom"), 0, ""
    result = rows[0].argument(index)
    for row in rows[1:]:
        result = result.join(row.argument(index))
    returned_types = sorted(
        {row.return_value.pointer_type for row in rows if row.return_value.pointer_type}
    )
    return result, rows[0].function_entry, "|".join(returned_types)


def _adjacent_residue_call_size(image: Image, address: int) -> AbstractValue:
    """Recover only an exact immediately-pushed cdecl size from residue bytes.

    Residue is deliberately outside the Task 5 function/value fixed point.  A
    neighboring immediate PUSH is nevertheless an unambiguous local machine
    fact; every other source remains bottom rather than being guessed from a
    reviewed site or a wider byte scan.
    """

    try:
        prefix = image.read(address - 5, 5)
    except (AttributeError, KeyError, ValueError, IndexError, OSError):
        return AbstractValue(
            kind="bottom",
            origin=f"residue-call-size-not-locally-readable:{address:#x}",
        )
    if prefix[0] == 0x68:
        value = int.from_bytes(prefix[1:], "little", signed=False)
        return AbstractValue(
            kind="null" if value == 0 else "exact",
            values=frozenset({value}),
            origin=f"exact-residue-push-imm32:{address - 5:#x}",
        )
    if prefix[-2] == 0x6A:
        value = int.from_bytes(prefix[-1:], "little", signed=True) & 0xFFFF_FFFF
        return AbstractValue(
            kind="null" if value == 0 else "exact",
            values=frozenset({value}),
            origin=f"exact-residue-push-imm8:{address - 2:#x}",
        )
    return AbstractValue(
        kind="bottom",
        origin=f"residue-call-size-not-adjacent-immediate:{address:#x}",
    )


def _raw_call_candidates(
    cfg: RawCfg, targets: frozenset[int]
) -> tuple[RawE8Candidate, ...]:
    """Return the whole-PE raw call inventory, with a fixture fallback."""
    raw_candidates = getattr(cfg, "raw_e8_candidates", None)
    if raw_candidates is None:
        raw_candidates = tuple(
            RawE8Candidate(row.address, row.target, "owned-call")
            for row in cfg.direct_calls
        )
    return tuple(
        sorted(
            (row for row in raw_candidates if row.target in targets),
            key=lambda row: (row.address, row.target, row.classification),
        )
    )


def _arena_call_candidates(cfg: RawCfg) -> tuple[RawE8Candidate, ...]:
    return _raw_call_candidates(cfg, _ARENA_TARGETS)


def _unlink_call_candidates(cfg: RawCfg) -> tuple[RawE8Candidate, ...]:
    return _raw_call_candidates(cfg, frozenset({_UNLINK_TARGET}))


def _objobject_initializers(
    writes: Sequence[MemoryWriteFact], allocation_site: int
) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                row.address
                for row in writes
                if row.base.allocation_site == allocation_site
                and row.offset == 0
                and row.width == 1
                and row.value.exact_value == 5
            }
        )
    )


def _allocation_type_provenance(
    values: AnalysisResult,
    allocation_site: int,
    pointer_type: str,
) -> tuple[str, ...]:
    """Return exact Task 5 facts that type one allocation origin.

    A reviewed address or same-sized object is not type evidence.  The origin
    must survive on a typed return, call argument, write base, or written
    pointer value.
    """

    facts: set[str] = set()

    def retain(value: AbstractValue, provenance: str) -> None:
        if (
            value.kind == "pointer"
            and value.pointer_type == pointer_type
            and value.allocation_site == allocation_site
        ):
            facts.add(f"{pointer_type}:{provenance}")

    for call in values.calls:
        retain(call.return_value, f"return:{call.address:#x}")
        for index, argument in enumerate(call.arguments):
            retain(argument, f"argument:{call.address:#x}:{index}")
    for write in values.memory_writes:
        retain(write.base, f"write-base:{write.address:#x}")
        retain(write.value, f"write-value:{write.address:#x}")
    return tuple(sorted(facts))


def _classify_allocation(
    address: int,
    size: AbstractValue,
    returned_type: str,
    initializers: tuple[int, ...],
    compiler_sha256: str,
    type_provenance: tuple[str, ...] = (),
) -> str:
    if _is_pcode_size_shape(size) and (
        returned_type == "pcode"
        or any(row.startswith("pcode:") for row in type_provenance)
    ):
        return (
            "pcode"
            if address in _PCODE_ALLOCATION_SITES
            else "pcode-expanded"
        )
    if (
        size.is_exact
        and size.exact_value == 0x36
        and initializers
        and (
            returned_type == "objobject"
            or any(row.startswith("objobject:") for row in type_provenance)
        )
    ):
        return (
            "objobject"
            if address in _REVIEWED_OBJOBJECT_ALLOCATION_SITES
            or compiler_sha256 != _RETAIL_SHA256
            else "objobject-expanded"
        )
    return "arena-other"


def _is_pcode_size_shape(size: AbstractValue) -> bool:
    """Recognize the closed ``0x28 + 0x0c * operand_count`` family."""

    if size.kind in {"argument", "affine"}:
        terms = size.affine_terms or (
            ((size.affine_symbol, size.affine_stride),)
            if size.affine_symbol
            else ()
        )
        return (
            size.affine_base == 0x28
            and bool(terms)
            and all(coefficient % 0x0C == 0 for _, coefficient in terms)
        )
    if size.kind == "symbolic":
        expression = size.affine_symbol.replace(" ", "")
        return expression.startswith("add(scale(") and expression.endswith(
            ",12),40)"
        )
    return False


def _pcode_field(offset: int, width: int) -> str:
    if offset == 0:
        return "next-link"
    if offset == 4:
        return "previous-link"
    if offset == 8:
        return "owning-block"
    if offset == 0x14 and width <= 2:
        return "opcode"
    if 0x16 <= offset < 0x1A:
        return "flags"
    if offset == 0x1A and width <= 2:
        return "operand-count"
    if offset >= 0x1C:
        index, member = divmod(offset - 0x1C, 0x0C)
        if member == 0 and width == 1:
            return f"operand[{index}].kind"
        if member == 1 and width == 1:
            return f"operand[{index}].flags"
        if member == 2 and width <= 4:
            return f"operand[{index}].payload"
        return f"operand[{index}].inline+{member:#x}"
    return f"header+{offset:#x}"


def _objobject_field(offset: int) -> str:
    return {
        0: "tag",
        0x0A: "name",
        0x0E: "type",
        0x2A: "cache-reuse-flag",
    }.get(offset, f"field+{offset:#x}")


@dataclass(frozen=True, slots=True)
class _UnlinkIndexes:
    blocks: Mapping[int, Any]
    instruction_block: Mapping[int, int]
    successors: Mapping[int, tuple[int, ...]]
    instructions: Mapping[int, Any]
    direct_calls: Mapping[int, int]
    call_facts: Mapping[int, tuple[Any, ...]]
    owners: Mapping[int, int]
    call_fallthroughs: Mapping[int, tuple[int, ...]]


def _build_cfg_indexes(cfg: RawCfg, values: AnalysisResult) -> _UnlinkIndexes:
    blocks = {row.start: row for row in cfg.blocks}
    instruction_block = {
        address: row.start for row in cfg.blocks for address in row.instruction_addresses
    }
    successors: dict[int, set[int]] = {}
    call_fallthroughs: dict[int, set[int]] = {}
    for edge in cfg.edges:
        target = instruction_block.get(edge.target, edge.target)
        if edge.kind == "call-fallthrough" and target in blocks:
            call_fallthroughs.setdefault(edge.source, set()).add(target)
        if edge.kind == "direct-call" or edge.kind.startswith("indirect-call"):
            continue
        source = instruction_block.get(edge.source)
        if source is not None and target in blocks:
            successors.setdefault(source, set()).add(target)
    call_facts: dict[int, list[Any]] = {}
    for row in values.calls:
        call_facts.setdefault(row.address, []).append(row)
    return _UnlinkIndexes(
        blocks=blocks,
        instruction_block=instruction_block,
        successors={
            key: tuple(sorted(value)) for key, value in successors.items()
        },
        instructions={row.address: row for row in cfg.instructions},
        direct_calls={row.address: row.target for row in cfg.direct_calls},
        call_facts={
            address: tuple(rows) for address, rows in call_facts.items()
        },
        owners={row.address: row.function_entry for row in values.calls},
        call_fallthroughs={
            address: tuple(sorted(targets))
            for address, targets in call_fallthroughs.items()
        },
    )


def _alias_relation(left: AbstractValue, right: AbstractValue) -> str:
    """Return a conservative same/different/unknown identity relation."""

    if left.is_bottom or right.is_bottom or left.is_unknown or right.is_unknown:
        return "unknown"
    if left.kind == right.kind == "symbolic":
        normalize = lambda expression: re.sub(  # noqa: E731
            r"(?:loop-)?phi\[0x[0-9a-f]+:(register|stack)=(-?[0-9]+)\]",
            r"phi[\1=\2]",
            expression,
        )
        return (
            "same"
            if normalize(left.affine_symbol) == normalize(right.affine_symbol)
            else "unknown"
        )
    if left.kind == right.kind == "pointer":
        left_key = (
            left.pointer_type,
            left.pointer_base,
            left.pointer_offset,
            left.allocation_site,
        )
        right_key = (
            right.pointer_type,
            right.pointer_base,
            right.pointer_offset,
            right.allocation_site,
        )
        if left_key == right_key:
            return "same"
        if (
            left.allocation_site is not None
            and right.allocation_site is not None
            and left.allocation_site != right.allocation_site
        ):
            return "different"
        return "unknown"
    if left.kind in {"argument", "affine"} and right.kind in {
        "argument",
        "affine",
    }:
        return (
            "same"
            if (left.affine_base, left.affine_terms)
            == (right.affine_base, right.affine_terms)
            else "unknown"
        )
    if left.is_finite and right.is_finite:
        if left.values == right.values and len(left.values) == 1:
            return "same"
        if left.values.isdisjoint(right.values):
            return "different"
    return "unknown"


def _effect_arguments(
    indexes: _UnlinkIndexes, address: int
) -> tuple[AbstractValue, ...]:
    return tuple(
        argument
        for row in indexes.call_facts.get(address, ())
        for argument in row.arguments[:2]
        if not argument.is_bottom
    )


def _replacement_argument_seen(
    indexes: _UnlinkIndexes, address: int, replacement_sites: frozenset[int]
) -> bool:
    return any(
        argument.kind == "pointer"
        and argument.allocation_site is not None
        and (
            argument.allocation_site in replacement_sites
            or indexes.direct_calls.get(argument.allocation_site)
            in _CREATE_UNLINKED_TARGETS
        )
        for argument in _effect_arguments(indexes, address)
    )


def _aliased_argument_seen(
    indexes: _UnlinkIndexes, address: int, expected: AbstractValue
) -> bool:
    return any(
        _alias_relation(expected, argument) == "same"
        for argument in _effect_arguments(indexes, address)
    )


def _prior_replacement_effect(
    indexes: _UnlinkIndexes,
    call_address: int,
    unlinked: AbstractValue,
) -> tuple[int, ...]:
    """Find a constructed replacement inserted before this unlink in its block."""

    block_start = indexes.instruction_block.get(call_address)
    block = indexes.blocks.get(block_start) if block_start is not None else None
    if block is None:
        return ()
    replacement_sites: set[int] = set()
    evidence: list[int] = []
    for address in block.instruction_addresses:
        if address == call_address:
            break
        target = indexes.direct_calls.get(address)
        if target == _UNLINK_TARGET:
            replacement_sites.clear()
            evidence.clear()
        elif target in _CREATE_UNLINKED_TARGETS:
            replacement_sites.add(address)
            evidence.append(address)
        elif target in _INSERT_TARGETS and _replacement_argument_seen(
            indexes, address, frozenset(replacement_sites)
        ) and _aliased_argument_seen(indexes, address, unlinked):
            evidence.append(address)
            return tuple(evidence)
    return ()


def _classify_unlink(
    call_address: int,
    indexes: _UnlinkIndexes,
) -> tuple[str, tuple[int, ...], tuple[str, ...]]:
    unlink_facts = indexes.call_facts.get(call_address, ())
    if not unlink_facts:
        return "unresolved", (), ("missing-task5-call-fact",)
    unlinked = unlink_facts[0].argument(0)
    for row in unlink_facts[1:]:
        unlinked = unlinked.join(row.argument(0))
    prior_replacement = _prior_replacement_effect(
        indexes, call_address, unlinked
    )
    if prior_replacement:
        return "replace", prior_replacement, (
            "preceding-effect=constructed-replacement",
        )
    argument_provenance = (
        f"argument-provenance={unlinked.kind}:{unlinked.origin}"
        if unlinked.is_bottom or unlinked.is_unknown
        else ""
    )
    owner = indexes.owners.get(call_address, 0)
    start_targets = indexes.call_fallthroughs.get(call_address, ())
    if not start_targets:
        return "unresolved", (), ("missing-call-fallthrough",)
    pending = [
        (row, frozenset()) for row in reversed(start_targets)
    ]
    visited: set[tuple[int, frozenset[int]]] = set()
    outcomes: dict[str, set[int]] = {}
    while pending:
        block_start, replacement_sites = pending.pop()
        state_key = (block_start, replacement_sites)
        if state_key in visited:
            continue
        visited.add(state_key)
        if len(visited) >= 65_536:
            return "unresolved", (), ("unlink-following-effect-cap",)
        block = indexes.blocks.get(block_start)
        if block is None:
            outcomes.setdefault("ambiguous", set()).add(block_start)
            continue
        terminal = False
        for address in block.instruction_addresses:
            if owner and indexes.owners.get(address, owner) != owner:
                continue
            target = indexes.direct_calls.get(address)
            if target in _CREATE_UNLINKED_TARGETS:
                replacement_sites = replacement_sites | {address}
            elif target in _INSERT_TARGETS:
                if _replacement_argument_seen(
                    indexes, address, replacement_sites
                ):
                    outcomes.setdefault("replace", set()).add(address)
                    terminal = True
                    break
                arguments = _effect_arguments(indexes, address)
                relations = tuple(
                    _alias_relation(unlinked, argument)
                    for argument in arguments
                )
                if "same" in relations:
                    outcomes.setdefault("move-reinsert", set()).add(address)
                    terminal = True
                    break
                if not relations or "unknown" in relations:
                    outcomes.setdefault("ambiguous", set()).add(address)
                    terminal = True
                    break
            instruction = indexes.instructions.get(address)
            if instruction is not None and instruction.mnemonic.startswith("ret"):
                outcomes.setdefault("delete", set()).add(address)
                terminal = True
                break
        if terminal:
            continue
        next_blocks = indexes.successors.get(block_start, ())
        if not next_blocks:
            outcomes.setdefault("ambiguous", set()).add(block.end)
            continue
        pending.extend(
            (row, replacement_sites) for row in reversed(next_blocks)
        )
    if len(outcomes) != 1:
        evidence = tuple(sorted({row for rows in outcomes.values() for row in rows}))
        detail = "outcomes=" + ",".join(sorted(outcomes))
        return "ambiguous", evidence, (detail,)
    classification = next(iter(outcomes))
    evidence = tuple(sorted(outcomes[classification]))
    provenance = [f"following-effect={classification}"]
    if argument_provenance:
        provenance.append(argument_provenance)
    return classification, evidence, tuple(provenance)


def _unresolved_key(row: UnresolvedLifetimeSite) -> tuple[Any, ...]:
    return row.address, row.kind, row.detail, row.provenance


def _closure_site_diagnostics(
    *,
    domain: str,
    expected: Sequence[Any],
    actual: Sequence[Any],
    identity: Callable[[Any], tuple[int, ...]],
) -> tuple[UnresolvedLifetimeSite, ...]:
    expected_ids = tuple(identity(row) for row in expected)
    actual_ids = tuple(identity(row) for row in actual)
    rows: list[UnresolvedLifetimeSite] = []
    duplicate_ids = {
        row for row, count in Counter(actual_ids).items() if count != 1
    }
    for row in sorted(duplicate_ids):
        rows.append(
            UnresolvedLifetimeSite(
                row[0],
                f"task5-{domain}-certificate-duplicate-site",
                "identity=" + ":".join(str(value) for value in row),
            )
        )
    for row in sorted(set(expected_ids) - set(actual_ids)):
        rows.append(
            UnresolvedLifetimeSite(
                row[0],
                f"task5-{domain}-certificate-missing-site",
                "identity=" + ":".join(str(value) for value in row),
            )
        )
    for row in sorted(set(actual_ids) - set(expected_ids)):
        rows.append(
            UnresolvedLifetimeSite(
                row[0],
                f"task5-{domain}-certificate-extra-site",
                "identity=" + ":".join(str(value) for value in row),
            )
        )
    return tuple(rows)


def _certificate_records_well_formed(
    certificate: Any,
    certificate_type: type,
    attribute: str,
    record_type: type,
) -> bool:
    if not isinstance(certificate, certificate_type):
        return False
    records = getattr(certificate, attribute, None)
    return isinstance(records, tuple) and all(
        isinstance(row, record_type) for row in records
    )


def _validate_task5_closure_certificates(
    cfg: RawCfg, values: AnalysisResult
) -> tuple[UnresolvedLifetimeSite, ...]:
    """Independently rederive and validate all structured Task 5 evidence."""

    rows: list[UnresolvedLifetimeSite] = []
    if values.limits is None:
        return tuple(
            UnresolvedLifetimeSite(
                0,
                f"missing-task5-{domain}-closure-certificate",
                "Task 5 result has no bounded AnalysisLimits provenance",
            )
            for domain in ("alias-write", "lifecycle-effect", "final-emission")
        )

    expected_alias = derive_alias_write_closure(
        cfg,
        compiler_sha256=values.compiler_sha256,
        cfg_instruction_hash=values.cfg_instruction_hash,
        memory_writes=values.memory_writes,
        calls=values.calls,
        finite_internal_edges=values.finite_internal_edges,
        limits=values.limits,
    )
    actual_alias = values.alias_write_closure
    if actual_alias is None:
        rows.append(
            UnresolvedLifetimeSite(
                0,
                "missing-task5-alias-write-closure-certificate",
                "Task 5 did not publish AliasWriteClosureCertificate",
            )
        )
    elif not _certificate_records_well_formed(
        actual_alias,
        type(expected_alias),
        "sites",
        AliasWriteSiteEvidence,
    ):
        rows.append(
            UnresolvedLifetimeSite(
                0,
                "task5-alias-write-certificate-malformed",
                "certificate or nested site record has the wrong closed type",
            )
        )
    else:
        rows.extend(
            _closure_site_diagnostics(
                domain="alias-write",
                expected=expected_alias.sites,
                actual=actual_alias.sites,
                identity=lambda row: (row.address, row.operand_index),
            )
        )
        if not isinstance(actual_alias.cap_hits, tuple) or not all(
            isinstance(row, str) for row in actual_alias.cap_hits
        ):
            rows.append(
                UnresolvedLifetimeSite(
                    0,
                    "task5-alias-write-certificate-malformed",
                    "cap_hits must be tuple[str, ...]",
                )
            )
        elif actual_alias.cap_hits:
            rows.append(
                UnresolvedLifetimeSite(
                    0,
                    "task5-alias-write-certificate-cap-hit",
                    ",".join(actual_alias.cap_hits),
                )
            )
        if actual_alias != expected_alias:
            rows.append(
                UnresolvedLifetimeSite(
                    0,
                    "task5-alias-write-certificate-differs",
                    "structured evidence differs from independent CFG/write replay",
                )
            )
    rows.extend(
        UnresolvedLifetimeSite(
            gap.address,
            f"task5-alias-write-gap:{gap.kind}",
            gap.detail,
            gap.provenance,
        )
        for gap in expected_alias.gaps
    )

    expected_lifecycle = derive_lifecycle_effect_closure(
        cfg,
        compiler_sha256=values.compiler_sha256,
        cfg_instruction_hash=values.cfg_instruction_hash,
        summaries=values.summaries,
        calls=values.calls,
        memory_writes=values.memory_writes,
        finite_internal_edges=values.finite_internal_edges,
        terminal_external_edges=values.terminal_external_edges,
        limits=values.limits,
    )
    actual_lifecycle = values.lifecycle_effect_closure
    if actual_lifecycle is None:
        rows.append(
            UnresolvedLifetimeSite(
                0,
                "missing-task5-lifecycle-effect-closure-certificate",
                "Task 5 did not publish LifecycleEffectClosureCertificate",
            )
        )
    elif not _certificate_records_well_formed(
        actual_lifecycle,
        type(expected_lifecycle),
        "sites",
        HelperEffectSiteEvidence,
    ):
        rows.append(
            UnresolvedLifetimeSite(
                0,
                "task5-lifecycle-effect-certificate-malformed",
                "certificate or nested site record has the wrong closed type",
            )
        )
    else:
        rows.extend(
            _closure_site_diagnostics(
                domain="lifecycle-effect",
                expected=expected_lifecycle.sites,
                actual=actual_lifecycle.sites,
                identity=lambda row: (row.address, row.target),
            )
        )
        if not isinstance(actual_lifecycle.cap_hits, tuple) or not all(
            isinstance(row, str) for row in actual_lifecycle.cap_hits
        ):
            rows.append(
                UnresolvedLifetimeSite(
                    0,
                    "task5-lifecycle-effect-certificate-malformed",
                    "cap_hits must be tuple[str, ...]",
                )
            )
        elif actual_lifecycle.cap_hits:
            rows.append(
                UnresolvedLifetimeSite(
                    0,
                    "task5-lifecycle-effect-certificate-cap-hit",
                    ",".join(actual_lifecycle.cap_hits),
                )
            )
        if actual_lifecycle != expected_lifecycle:
            rows.append(
                UnresolvedLifetimeSite(
                    0,
                    "task5-lifecycle-effect-certificate-differs",
                    "structured evidence differs from independent call/summary replay",
                )
            )
    rows.extend(
        UnresolvedLifetimeSite(
            gap.address,
            f"task5-lifecycle-effect-gap:{gap.kind}",
            gap.detail,
            gap.provenance,
        )
        for gap in expected_lifecycle.gaps
    )

    expected_final = derive_final_emission_closure(
        compiler_sha256=values.compiler_sha256,
        cfg_instruction_hash=values.cfg_instruction_hash,
        calls=values.calls,
        memory_writes=values.memory_writes,
        limits=values.limits,
        pseudo_op_dispositions=values.pseudo_op_dispositions,
    )
    actual_final = values.final_emission_closure
    if actual_final is None:
        rows.append(
            UnresolvedLifetimeSite(
                0,
                "missing-task5-final-emission-closure-certificate",
                "Task 5 did not publish FinalEmissionClosureCertificate",
            )
        )
    elif not _certificate_records_well_formed(
        actual_final,
        type(expected_final),
        "return_write_flows",
        CallReturnWriteEvidence,
    ):
        rows.append(
            UnresolvedLifetimeSite(
                0,
                "task5-final-emission-certificate-malformed",
                "certificate or nested flow record has the wrong closed type",
            )
        )
    else:
        rows.extend(
            _closure_site_diagnostics(
                domain="final-emission",
                expected=expected_final.return_write_flows,
                actual=actual_final.return_write_flows,
                identity=lambda row: (
                    row.call_address,
                    row.target,
                    row.function_entry,
                ),
            )
        )
        if not isinstance(actual_final.cap_hits, tuple) or not all(
            isinstance(row, str) for row in actual_final.cap_hits
        ):
            rows.append(
                UnresolvedLifetimeSite(
                    0,
                    "task5-final-emission-certificate-malformed",
                    "cap_hits must be tuple[str, ...]",
                )
            )
        elif actual_final.cap_hits:
            rows.append(
                UnresolvedLifetimeSite(
                    0,
                    "task5-final-emission-certificate-cap-hit",
                    ",".join(actual_final.cap_hits),
                )
            )
        if actual_final != expected_final:
            rows.append(
                UnresolvedLifetimeSite(
                    0,
                    "task5-final-emission-certificate-differs",
                    "structured evidence differs from independent return/write replay",
                )
            )
    rows.extend(
        UnresolvedLifetimeSite(
            gap.address,
            f"task5-final-emission-gap:{gap.kind}",
            gap.detail,
            gap.provenance,
        )
        for gap in expected_final.gaps
    )
    return tuple(rows)


def build_lifetime_site_inventory(
    image: Image,
    cfg: RawCfg,
    values: AnalysisResult,
) -> LifetimeSiteInventory:
    """Classify all raw lifetime sites and fail closed on relevant ambiguity."""

    unresolved: set[UnresolvedLifetimeSite] = set()
    allocations: list[AllocationSite] = []
    direct_arena_calls = {
        (row.address, row.target): row
        for row in cfg.direct_calls
        if row.target in _ARENA_TARGETS
    }
    raw_arena_candidates = _arena_call_candidates(cfg)
    raw_identities = [(row.address, row.target) for row in raw_arena_candidates]
    duplicate_raw_identities = {
        identity
        for identity in raw_identities
        if raw_identities.count(identity) != 1
    }
    for address, target in sorted(duplicate_raw_identities):
        unresolved.add(
            UnresolvedLifetimeSite(
                address,
                "duplicate-raw-arena-call-candidate",
                f"target={target:#x}",
            )
        )
    if getattr(cfg, "raw_e8_candidates", None) is not None:
        missing_raw = set(direct_arena_calls) - set(raw_identities)
        for address, target in sorted(missing_raw):
            unresolved.add(
                UnresolvedLifetimeSite(
                    address,
                    "owned-arena-call-missing-raw-e8-candidate",
                    f"target={target:#x}",
                )
            )
        raw_arena_candidates = tuple(
            sorted(
                (
                    *raw_arena_candidates,
                    *(
                        RawE8Candidate(address, target, "owned-call")
                        for address, target in missing_raw
                    ),
                ),
                key=lambda row: (row.address, row.target, row.classification),
            )
        )

    residue = getattr(cfg, "provisional_unreachable_residue", None)
    for call in raw_arena_candidates:
        direct = direct_arena_calls.get((call.address, call.target))
        if direct is not None:
            ownership = "reachable-owned-call"
            if call.classification != "owned-call":
                unresolved.add(
                    UnresolvedLifetimeSite(
                        call.address,
                        "raw-arena-call-ownership-conflict",
                        f"direct-call-with-classification={call.classification}",
                    )
                )
            call_paths = values.call_paths_at(call.address)
            if not call_paths:
                unresolved.add(
                    UnresolvedLifetimeSite(
                        call.address,
                        "missing-task5-arena-call-fact",
                        f"target={call.target:#x}",
                    )
                )
            elif {
                (row.target, row.function_entry) for row in call_paths
            } != {(call.target, call_paths[0].function_entry)}:
                unresolved.add(
                    UnresolvedLifetimeSite(
                        call.address,
                        "conflicting-task5-arena-call-facts",
                        "target/owner paths differ",
                    )
                )
            size, owner, returned_type = _joined_call_argument(values, call.address, 0)
            initializers = _objobject_initializers(
                values.memory_writes, call.address
            )
            type_provenance = (
                *_allocation_type_provenance(values, call.address, "pcode"),
                *_allocation_type_provenance(values, call.address, "objobject"),
            )
        else:
            ownership = "uncertified-unreachable-residue"
            certified_residue = (
                call.classification == "unreachable-executable-residue"
                and residue is not None
                and residue.accepted
                and residue.reconciliation_sha256 is not None
                and residue.contains(call.address, 5)
            )
            if certified_residue:
                ownership = "accepted-unreachable-residue"
            else:
                unresolved.add(
                    UnresolvedLifetimeSite(
                        call.address,
                        "uncertified-residue-arena-call",
                        f"raw-classification={call.classification}",
                    )
                )
            size = _adjacent_residue_call_size(image, call.address)
            owner = 0
            returned_type = "unreachable-residue-arena-candidate"
            initializers = ()
            type_provenance = ()
        classification = (
            "unreachable-residue-candidate"
            if ownership == "accepted-unreachable-residue"
            else _classify_allocation(
                call.address,
                size,
                returned_type,
                initializers,
                image.sha256,
                type_provenance,
            )
        )
        provenance = (
            f"raw-e8:{call.address:#x}->{call.target:#x}",
            f"raw-e8-classification:{call.classification}",
            f"ownership:{ownership}",
            f"size:{size.kind}:{size.origin}",
            *(
                ("reviewed-retail-objobject-lower-bound",)
                if call.address in _REVIEWED_OBJOBJECT_ALLOCATION_SITES
                else ()
            ),
            *(f"initializer:{row:#x}" for row in initializers),
            *(f"typed-use:{row}" for row in type_provenance),
            *(
                ("reviewed-retail-non-objobject-0x36-copy",)
                if call.address
                in _REVIEWED_NON_OBJOBJECT_0X36_ALLOCATION_SITES
                else ()
            ),
        )
        allocations.append(
            AllocationSite(
                call.address,
                owner,
                call.target,
                classification,
                size,
                (
                    "objobject"
                    if classification.startswith("objobject")
                    else returned_type or "arena-allocation"
                ),
                initializers,
                ownership,
                call.classification,
                tuple(provenance),
            )
        )
        if (
            ownership == "reachable-owned-call"
            and (size.is_bottom or size.is_unknown)
        ):
            unresolved.add(
                UnresolvedLifetimeSite(
                    call.address,
                    "unknown-allocation-size",
                    size.origin or "missing Task 5 call argument",
                    provenance,
                )
            )
        if (
            ownership == "reachable-owned-call"
            and call.target in _TARGET_OBJECT_ARENAS
            and size.is_exact
            and size.exact_value == 0x36
            and (not initializers or not type_provenance)
            and call.address
            not in _REVIEWED_NON_OBJOBJECT_0X36_ALLOCATION_SITES
        ):
            unresolved.add(
                UnresolvedLifetimeSite(
                    call.address,
                    "unclassified-0x36-allocation",
                    "size matches ObjObject but exact tag initialization and "
                    "typed-use provenance were not both proven",
                    provenance,
                )
            )
        if (
            ownership == "reachable-owned-call"
            and call.address in _PCODE_ALLOCATION_SITES
            and classification != "pcode"
        ):
            unresolved.add(
                UnresolvedLifetimeSite(
                    call.address,
                    "unproved-reviewed-pcode-allocation",
                    "reviewed lower-bound requires affine 0x28+0x0c*n size "
                    "and typed PCode provenance",
                    provenance,
                )
            )
        if (
            ownership == "reachable-owned-call"
            and _is_pcode_size_shape(size)
            and not classification.startswith("pcode")
        ):
            unresolved.add(
                UnresolvedLifetimeSite(
                    call.address,
                    "pcode-shaped-allocation-lacks-type-provenance",
                    "affine 0x28+0x0c*n size is not sufficient without a "
                    "typed PCode origin/use",
                    provenance,
                )
            )

    allocation_types = {row.address: row.classification for row in allocations}
    field_writes: list[FieldWriteSite] = []
    for write in sorted(
        values.memory_writes,
        key=lambda row: (row.address, row.function_entry, row.offset, row.width),
    ):
        object_type = write.base.pointer_type
        if object_type == "arena-allocation" and write.base.allocation_site is not None:
            object_type = allocation_types.get(
                write.base.allocation_site, "arena-allocation"
            )
        if object_type in {"pcode", "pcode-expanded"}:
            field = _pcode_field(write.offset, write.width)
            normalized_type = "pcode"
        elif object_type in {"objobject", "objobject-expanded"}:
            field = _objobject_field(write.offset)
            normalized_type = "objobject"
        elif "pcode" in write.base.origin.lower():
            unresolved.add(
                UnresolvedLifetimeSite(
                    write.address,
                    "possible-untyped-pcode-write",
                    f"{write.operation} width={write.width} offset={write.offset:#x}",
                    (write.base.origin,),
                )
            )
            continue
        else:
            continue
        field_writes.append(
            FieldWriteSite(
                write.address,
                write.function_entry,
                normalized_type,
                field,
                write.offset,
                write.width,
                write.operation,
                write.value,
                write.base.allocation_site,
                (
                    f"base-origin:{write.base.origin}",
                    f"value-origin:{write.value.origin}",
                ),
            )
        )
        if write.value.is_bottom or write.value.is_unknown:
            unresolved.add(
                UnresolvedLifetimeSite(
                    write.address,
                    "unknown-typed-field-write",
                    f"{normalized_type}.{field}",
                    (write.value.origin,),
                )
            )

    write_semantics: dict[int, set[tuple[str, str, int, int, str]]] = {}
    for row in field_writes:
        write_semantics.setdefault(row.address, set()).add(
            (row.object_type, row.field, row.offset, row.width, row.operation)
        )
    for address, semantics in sorted(write_semantics.items()):
        if len(semantics) > 1:
            unresolved.add(
                UnresolvedLifetimeSite(
                    address,
                    "ambiguous-typed-field-write-semantics",
                    "|".join(repr(row) for row in sorted(semantics)),
                )
            )

    unlinks: list[UnlinkSite] = []
    call_owner = {row.address: row.function_entry for row in values.calls}
    unlink_indexes = _build_cfg_indexes(cfg, values)
    direct_unlink_calls = {
        (row.address, row.target): row
        for row in cfg.direct_calls
        if row.target == _UNLINK_TARGET
    }
    raw_unlink_candidates = _unlink_call_candidates(cfg)
    raw_unlink_identities = [
        (row.address, row.target) for row in raw_unlink_candidates
    ]
    for address, target in sorted(
        {
            identity
            for identity in raw_unlink_identities
            if raw_unlink_identities.count(identity) != 1
        }
    ):
        unresolved.add(
            UnresolvedLifetimeSite(
                address,
                "duplicate-raw-unlink-call-candidate",
                f"target={target:#x}",
            )
        )
    if getattr(cfg, "raw_e8_candidates", None) is not None:
        missing_raw_unlinks = set(direct_unlink_calls) - set(raw_unlink_identities)
        for address, target in sorted(missing_raw_unlinks):
            unresolved.add(
                UnresolvedLifetimeSite(
                    address,
                    "owned-unlink-call-missing-raw-e8-candidate",
                    f"target={target:#x}",
                )
            )
        raw_unlink_candidates = tuple(
            sorted(
                (
                    *raw_unlink_candidates,
                    *(
                        RawE8Candidate(address, target, "owned-call")
                        for address, target in missing_raw_unlinks
                    ),
                ),
                key=lambda row: (row.address, row.target, row.classification),
            )
        )

    for call in raw_unlink_candidates:
        direct = direct_unlink_calls.get((call.address, call.target))
        if direct is not None:
            ownership = "reachable-owned-call"
            classification, evidence, effect_provenance = _classify_unlink(
                call.address, unlink_indexes
            )
            if call.classification != "owned-call":
                unresolved.add(
                    UnresolvedLifetimeSite(
                        call.address,
                        "raw-unlink-call-ownership-conflict",
                        f"direct-call-with-classification={call.classification}",
                    )
                )
        else:
            certified_residue = (
                call.classification == "unreachable-executable-residue"
                and residue is not None
                and residue.accepted
                and residue.reconciliation_sha256 is not None
                and residue.contains(call.address, 5)
            )
            ownership = (
                "accepted-unreachable-residue"
                if certified_residue
                else "uncertified-unreachable-residue"
            )
            classification = (
                "unreachable-residue-candidate"
                if certified_residue
                else "unresolved"
            )
            evidence = ()
            effect_provenance = (
                "no-reachable-lifecycle-effect",
                "raw-E8 residue ownership is not decoded-call provenance",
            )
            if not certified_residue:
                unresolved.add(
                    UnresolvedLifetimeSite(
                        call.address,
                        "uncertified-residue-unlink-candidate",
                        f"raw-classification={call.classification}",
                    )
                )
        provenance = (
            f"raw-e8:{call.address:#x}->{call.target:#x}",
            f"raw-e8-classification:{call.classification}",
            f"ownership:{ownership}",
            *effect_provenance,
        )
        unlinks.append(
            UnlinkSite(
                call.address,
                call_owner.get(call.address, 0),
                classification,
                evidence,
                ownership,
                call.classification,
                provenance,
            )
        )
        if (
            ownership == "reachable-owned-call"
            and classification not in {"delete", "move-reinsert", "replace"}
        ):
            unresolved.add(
                UnresolvedLifetimeSite(
                    call.address,
                    "unclassified-unlink-path",
                    "|".join(provenance),
                    tuple(f"effect:{row:#x}" for row in evidence),
                )
            )
        reviewed_classification = (
            _REVIEWED_RETAIL_UNLINK_CLASSIFICATIONS.get(call.address)
            if image.sha256 == _RETAIL_SHA256
            and ownership == "reachable-owned-call"
            else None
        )
        if (
            reviewed_classification is not None
            and classification != reviewed_classification
        ):
            unresolved.add(
                UnresolvedLifetimeSite(
                    call.address,
                    "reviewed-retail-unlink-regression-differs",
                    f"computed={classification};reviewed-lower-bound="
                    f"{reviewed_classification}",
                    provenance,
                )
            )

    # Lifecycle rows are consequences of typed effects, not address presence.
    # The retained address dictionaries below are consulted only by the exact
    # regression checks after these rows have been derived.
    reuses = tuple(
        sorted(
            {
                LifecycleSite(
                    row.address,
                    "objobject-cache-reuse-flag-write",
                    (
                        f"typed-field:{row.object_type}.{row.field}",
                        f"operation:{row.operation}",
                        f"value:{row.value.kind}:{row.value.origin}",
                    ),
                )
                for row in field_writes
                if row.object_type == "objobject"
                and row.field == "cache-reuse-flag"
            },
            key=lambda row: (row.address, row.classification, row.provenance),
        )
    )
    if image.sha256 == _RETAIL_SHA256:
        lifecycle_closure = (
            derive_lifecycle_effect_closure(
                cfg,
                compiler_sha256=values.compiler_sha256,
                cfg_instruction_hash=values.cfg_instruction_hash,
                summaries=values.summaries,
                calls=values.calls,
                memory_writes=values.memory_writes,
                finite_internal_edges=values.finite_internal_edges,
                terminal_external_edges=values.terminal_external_edges,
                limits=values.limits,
            )
            if values.limits is not None
            else None
        )
        releases = tuple(
            GenerationBoundarySite(
                row.address,
                row.target,
                row.kind,
                row.affected_arenas,
                row.provenance,
            )
            for row in (() if lifecycle_closure is None else lifecycle_closure.semantic_evidence)
            if row.kind
            in {
                "temporary-arena-rewind",
                "persistent-arena-release",
                "all-compiler-arenas-release",
            }
        )
    else:
        release_evidence = {
            (
                row.address,
                row.target,
                f"direct-call:{row.address:#x}->{row.target:#x}",
            )
            for row in cfg.direct_calls
            if row.target in _GENERATION_TARGETS
        }
        release_evidence.update(
            (
                row.source,
                row.target,
                f"finite-{row.flow_kind}:{row.source:#x}->{row.target:#x}",
            )
            for row in values.finite_internal_edges
            if row.target in _GENERATION_TARGETS
            and row.flow_kind.startswith("indirect-call")
        )
        releases = tuple(
            GenerationBoundarySite(
                address,
                target,
                _GENERATION_TARGETS[target][0],
                _GENERATION_TARGETS[target][1],
                (provenance,),
            )
            for address, target, provenance in sorted(release_evidence)
        )
    mutation_sites = tuple(
        sorted(
            {
                LifecycleSite(
                    row.address,
                    f"pcode-field-write:{row.field}",
                    (
                        f"typed-field:{row.object_type}.{row.field}",
                        f"operation:{row.operation}",
                        f"value:{row.value.kind}:{row.value.origin}",
                    ),
                )
                for row in field_writes
                if row.object_type == "pcode"
            },
            key=lambda row: (row.address, row.classification, row.provenance),
        )
    )
    rewrite_sites = tuple(
        row
        for row in mutation_sites
        if ":operand[" in row.classification
        or row.classification.endswith(":opcode")
        or row.classification.endswith(":flags")
    )

    encoder_call_evidence = {
        (row.address, "direct-call")
        for row in cfg.direct_calls
        if row.target == 0x004A3590
    }
    encoder_call_evidence.update(
        (row.source, f"finite-{row.flow_kind}")
        for row in values.finite_internal_edges
        if row.target == 0x004A3590
        and row.flow_kind.startswith("indirect-call")
    )
    encoder_calls = tuple(sorted(address for address, _ in encoder_call_evidence))
    emission_rows: set[LifecycleSite] = set()
    final_closure = None
    if values.limits is not None:
        final_closure = derive_final_emission_closure(
            compiler_sha256=values.compiler_sha256,
            cfg_instruction_hash=values.cfg_instruction_hash,
            calls=values.calls,
            memory_writes=values.memory_writes,
            limits=values.limits,
            pseudo_op_dispositions=values.pseudo_op_dispositions,
        )
        emission_rows.update(
            LifecycleSite(row.address, row.kind, row.provenance)
            for row in final_closure.semantic_evidence
        )
        if final_closure.semantic_evidence and image.sha256 != _RETAIL_SHA256:
            unresolved.update(
                UnresolvedLifetimeSite(
                    gap.address,
                    f"task5-final-emission-gap:{gap.kind}",
                    gap.detail,
                    gap.provenance,
                )
                for gap in final_closure.gaps
            )
    emission_sites = tuple(
        sorted(emission_rows, key=lambda row: (row.address, row.classification))
    )

    for row in values.unresolved:
        rendered = f"{row.kind}:{row.reason}:{row.origin}"
        unresolved.add(
            UnresolvedLifetimeSite(
                row.address,
                "task5-relevant-unresolved",
                rendered,
            )
        )

    if image.sha256 == _RETAIL_SHA256:
        if values.compiler_sha256 != image.sha256:
            unresolved.add(
                UnresolvedLifetimeSite(
                    0,
                    "task5-compiler-sha-differs",
                    f"values={values.compiler_sha256};image={image.sha256}",
                )
            )
        cfg_instruction_hash = hashlib.sha256(
            b"".join(bytes.fromhex(row.bytes_hex) for row in cfg.instructions)
        ).hexdigest()
        if values.cfg_instruction_hash != cfg_instruction_hash:
            unresolved.add(
                UnresolvedLifetimeSite(
                    0,
                    "task5-cfg-instruction-hash-differs",
                    f"values={values.cfg_instruction_hash};"
                    f"cfg={cfg_instruction_hash}",
                )
            )
        if not values.proof_ready:
            unresolved.add(
                UnresolvedLifetimeSite(
                    0,
                    "task5-proof-not-ready",
                    "exact lifetime proof requires Task 5 proof_ready",
                )
            )
        unresolved.update(_validate_task5_closure_certificates(cfg, values))
        pcode_sites = {row.address for row in allocations if row.classification == "pcode"}
        if pcode_sites != _PCODE_ALLOCATION_SITES:
            unresolved.add(
                UnresolvedLifetimeSite(
                    0,
                    "retail-pcode-allocation-set-differs",
                    f"observed={','.join(f'{row:#x}' for row in sorted(pcode_sites))}",
                )
            )
        for row in allocations:
            if row.classification == "pcode-expanded":
                unresolved.add(
                    UnresolvedLifetimeSite(
                        row.address,
                        "expanded-retail-pcode-allocation",
                        "new affine PCode allocation shape requires review",
                        row.provenance,
                    )
                )
        objobject_sites = {
            row.address
            for row in allocations
            if row.classification.startswith("objobject")
        }
        missing_objobject = _REVIEWED_OBJOBJECT_ALLOCATION_SITES - objobject_sites
        for address in sorted(missing_objobject):
            unresolved.add(
                UnresolvedLifetimeSite(
                    address,
                    "missing-reviewed-retail-objobject-allocation",
                    "reviewed lower-bound site was not proved as exact-size ObjObject",
                )
            )
        expanded_objobject = objobject_sites - _REVIEWED_OBJOBJECT_ALLOCATION_SITES
        for address in sorted(expanded_objobject):
            unresolved.add(
                UnresolvedLifetimeSite(
                    address,
                    "expanded-retail-objobject-allocation",
                    "new exact-size/tag-initialized ObjObject requires review",
                )
            )
        if encoder_calls != (0x004A2D17,):
            unresolved.add(
                UnresolvedLifetimeSite(
                    0x004A2D17,
                    "retail-encoder-closure-differs",
                    f"observed={','.join(f'{row:#x}' for row in encoder_calls)}",
                )
            )
        missing_emission = set(_EMISSION_SITES) - {
            row.address for row in emission_sites
        }
        for address in sorted(missing_emission):
            unresolved.add(
                UnresolvedLifetimeSite(
                    address,
                    "missing-retail-emission-site",
                    _EMISSION_SITES[address],
                )
            )
        observed_reuses = {row.address for row in reuses}
        for address in sorted(set(_REUSE_TRANSITIONS) - observed_reuses):
            unresolved.add(
                UnresolvedLifetimeSite(
                    address,
                    "reviewed-retail-reuse-anchor-not-derived",
                    _REUSE_TRANSITIONS[address],
                )
            )
        observed_mutations = {row.address for row in mutation_sites}
        for address in sorted(set(_MUTATION_SITES) - observed_mutations):
            unresolved.add(
                UnresolvedLifetimeSite(
                    address,
                    "reviewed-retail-mutation-anchor-not-derived",
                    _MUTATION_SITES[address],
                )
            )
        observed_rewrites = {row.address for row in rewrite_sites}
        for address in sorted(_REWRITE_SITE_ADDRESSES - observed_rewrites):
            unresolved.add(
                UnresolvedLifetimeSite(
                    address,
                    "reviewed-retail-rewrite-anchor-not-derived",
                    _MUTATION_SITES[address],
                )
            )

    hook_capture_facts = tuple(
        sorted(
            {
                *(
                    HookCaptureFact(row.address, "allocation", row.classification)
                    for row in allocations
                    if row.ownership == "reachable-owned-call"
                    and row.classification
                    in {
                        "pcode",
                        "pcode-expanded",
                        "objobject",
                        "objobject-expanded",
                    }
                ),
                *(
                    HookCaptureFact(row.address, "unlink", "pcode")
                    for row in unlinks
                    if row.ownership == "reachable-owned-call"
                ),
                *(
                    HookCaptureFact(row.address, "mutation", "pcode")
                    for row in mutation_sites
                ),
                *(
                    HookCaptureFact(row.address, "emission", "pcode")
                    for row in emission_sites
                ),
            },
            key=lambda row: (row.address, row.event, row.object_type),
        )
    )
    unresolved_rows = tuple(sorted(unresolved, key=_unresolved_key))
    return LifetimeSiteInventory(
        compiler_sha256=image.sha256,
        cfg_instruction_hash=values.cfg_instruction_hash,
        allocations=tuple(allocations),
        reuses=reuses,
        releases=releases,
        unlink_classifications=tuple(unlinks),
        field_writes=tuple(field_writes),
        mutation_sites=mutation_sites,
        rewrite_sites=rewrite_sites,
        emission_sites=emission_sites,
        hook_capture_facts=hook_capture_facts,
        unresolved=unresolved_rows,
        high_water_marks=(
            ("arena_calls", len(allocations)),
            (
                "owned_arena_calls",
                sum(
                    row.ownership == "reachable-owned-call"
                    for row in allocations
                ),
            ),
            (
                "accepted_residue_arena_candidates",
                sum(
                    row.ownership == "accepted-unreachable-residue"
                    for row in allocations
                ),
            ),
            ("pcode_allocations", sum(row.classification.startswith("pcode") for row in allocations)),
            (
                "objobject_allocations",
                sum(
                    row.classification.startswith("objobject")
                    for row in allocations
                ),
            ),
            ("unlink_calls", len(unlinks)),
            (
                "owned_unlink_calls",
                sum(
                    row.ownership == "reachable-owned-call"
                    for row in unlinks
                ),
            ),
            (
                "accepted_residue_unlink_candidates",
                sum(
                    row.ownership == "accepted-unreachable-residue"
                    for row in unlinks
                ),
            ),
            ("typed_field_writes", len(field_writes)),
            ("unresolved", len(unresolved_rows)),
        ),
        proof_ready=not unresolved_rows,
    )
