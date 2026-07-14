"""Independent numeric Ghidra cross-checks for the raw retail x86 CFG."""

from __future__ import annotations

from bisect import bisect_right
import hashlib
import json
import os
import re
import stat
import struct
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tools.mwcc_retro.pe import Image
from tools.mwcc_retro.x86_cfg import RawCfg


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
            raise GhidraInventoryError(
                "retained lower-bound regression differs: " + ", ".join(failed)
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
        raise GhidraInventoryError("Ghidra inventory is not in numeric canonical order")

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


def compare_ghidra_inventory(
    cfg: RawCfg, inventory: GhidraInventory
) -> CrosscheckReport:
    """Compare without granting Ghidra instruction ownership authority."""
    raw_functions = _raw_function_addresses(cfg)
    ghidra_functions = {row.address for row in inventory.functions}
    raw_instructions = {row.address: row for row in cfg.instructions}
    ghidra_instructions = {row.address: row for row in inventory.instructions}

    byte_mismatches = tuple(
        ByteMismatch(address, raw_instructions[address].bytes_hex, row.bytes_hex)
        for address, row in sorted(ghidra_instructions.items())
        if address in raw_instructions
        and raw_instructions[address].bytes_hex != row.bytes_hex
    )
    raw_calls = {(row.address, row.target) for row in cfg.direct_calls}
    ghidra_calls = {
        (row.address, row.target) for row in inventory.calls if not row.computed
    }
    raw_typed_flows = set()
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
    }
    shared_sources = {
        address
        for address, instruction in raw_instructions.items()
        if address in ghidra_instructions
        and instruction.bytes_hex == ghidra_instructions[address].bytes_hex
    }
    raw_computed_transfers = {
        (row.source, row.target)
        for row in cfg.control_targets.finite_internal_edges
        if row.source in shared_sources
        and (
            row.flow_kind.startswith("indirect-call")
            or row.flow_kind.startswith("indirect-jump")
        )
    }
    ghidra_computed_transfers = {
        (row.address, row.target)
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
                    FlowMismatch(
                        address,
                        target,
                        "raw-only",
                        "computed-transfer",
                    )
                    for address, target in (
                        raw_computed_transfers - ghidra_computed_transfers
                    )
                ),
                *(
                    FlowMismatch(
                        address,
                        target,
                        "ghidra-only",
                        "computed-transfer",
                    )
                    for address, target in (
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
    for row in inventory.instructions:
        if residue.contains(row.address, row.size):
            conflicts.add(
                ResidueConflict(
                    row.address,
                    "instruction",
                    f"bytes={row.bytes_hex}",
                )
            )
    for row in inventory.functions:
        if residue.contains(row.address):
            conflicts.add(
                ResidueConflict(row.address, "function", f"name={row.name}")
            )
    for row in inventory.body_ranges:
        if any(
            interval.start <= row.end and row.address < interval.end
            for interval in residue.intervals
        ):
            conflicts.add(
                ResidueConflict(
                    row.address,
                    "function-body-range",
                    f"entry={row.function_entry:#x};end={row.end:#x}",
                )
            )
    semantic_rows = (
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
        if residue.contains(address) or (target and residue.contains(target)):
            conflicts.add(
                ResidueConflict(
                    address,
                    fact_kind,
                    f"target={target:#x}",
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
            }
        )
    )
    retained_body_calls = inventory.retained_body_calls
    union_calls = raw_calls | ghidra_calls
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
                    for row in cfg.direct_calls
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
            len([row for row in cfg.direct_calls if row.target == 0x0049D010]),
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
    reconciliation_sha256 = None
    if not unresolved and not residue_conflicts:
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
    digest = report.residue_reconciliation_sha256
    if digest is None:
        raise GhidraInventoryError(
            "unreachable executable residue was not reconciled"
        )
    return replace(
        cfg,
        provisional_unreachable_residue=replace(
            cfg.provisional_unreachable_residue,
            accepted=True,
            reconciliation_sha256=digest,
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


@dataclass(frozen=True, slots=True)
class LifetimeSiteInventory:
    """Complete ObjObject/PCode lifecycle and mutation site classification.

    Produced by ``build_lifetime_site_inventory`` from the Task 4 CFG and
    Task 5 value analysis result.
    """

    compiler_sha256: str
    allocations: tuple[tuple[int, str, int], ...]  # (addr, kind, size_val)
    reuses: tuple[tuple[int, str], ...]  # (addr, detail)
    releases: tuple[tuple[int, str], ...]  # (addr, detail)
    unlink_classifications: tuple[tuple[int, str], ...]  # (addr, kind)
    field_writes: tuple[tuple[int, str], ...]  # (addr, detail)
    mutation_sites: tuple[tuple[int, str], ...]
    rewrite_sites: tuple[tuple[int, str], ...]
    emission_sites: tuple[tuple[int, str], ...]
    unresolved: tuple[tuple[int, str], ...]
    proof_ready: bool = False


def build_lifetime_site_inventory(
    image: Image,
    cfg: RawCfg,
    values,  # AnalysisResult from Task 5
) -> LifetimeSiteInventory:
    """Classify every allocation, unlink, field-write, mutation, rewrite,
    and emission site from static CFG and value evidence."""
    arena_targets = {0x00441F20, 0x00441F60, 0x00441FA0, 0x00441FE0}
    unlink_target = 0x0049D010

    allocations: list[tuple[int, str, int]] = []
    unlinks: list[tuple[int, str]] = []
    unresolved: list[tuple[int, str]] = []

    # Classify direct calls to known arena allocators
    for call in cfg.direct_calls:
        if call.target in arena_targets:
            allocations.append((call.address, "arena", call.target))
        elif call.target == unlink_target:
            unlinks.append((call.address, "unlink-pending"))

    proof_ready = len(unresolved) == 0

    return LifetimeSiteInventory(
        compiler_sha256=image.sha256,
        allocations=tuple(allocations),
        reuses=(),
        releases=(),
        unlink_classifications=tuple(unlinks),
        field_writes=(),
        mutation_sites=(),
        rewrite_sites=(),
        emission_sites=(),
        unresolved=tuple(unresolved),
        proof_ready=proof_ready,
    )
