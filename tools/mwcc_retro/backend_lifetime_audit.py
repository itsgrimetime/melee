"""Independent numeric Ghidra cross-checks for the raw retail x86 CFG."""

from __future__ import annotations

from bisect import bisect_right
import hashlib
import json
import os
import re
import struct
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tools.mwcc_retro.x86_cfg import RawCfg


INVENTORY_SCHEMA = "mwcc-ghidra-raw-crosscheck.v1"
CROSSCHECK_SCHEMA = "mwcc-retro-raw-ghidra-crosscheck.v1"
_HEX_64 = re.compile(r"[0-9a-f]{64}")


class GhidraInventoryError(ValueError):
    """Raised when transient cross-check evidence is malformed or conflicts."""


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


@dataclass(frozen=True, slots=True)
class OwnershipMismatch:
    address: int
    side: str


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
        retained_body_calls=tuple(retained_body_calls),
        computed_transfers=tuple(references["computed-transfer"]),
        data_references=tuple(references["data-reference"]),
        function_pointer_references=tuple(
            references["function-pointer-reference"]
        ),
    )


def _raw_function_addresses(cfg: RawCfg) -> set[int]:
    function_categories = {
        "entrypoint",
        "export",
        "audit-anchor",
        "explicit-seed",
        "direct-call-target",
        "function-pointer-initializer",
        "callback-table-entry",
    }
    return {
        row.address
        for row in cfg.seed_inventory.records
        if row.category in function_categories
    }


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
    flow_mismatches = tuple(
        [
            FlowMismatch(address, target, "raw-only")
            for address, target in sorted(raw_calls - ghidra_calls)
        ]
        + [
            FlowMismatch(address, target, "ghidra-only")
            for address, target in sorted(ghidra_calls - raw_calls)
        ]
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
    return CrosscheckReport(
        compiler_sha256=inventory.compiler_sha256,
        ghidra_inventory_sha256=inventory.canonical_sha256,
        raw_only_functions=tuple(sorted(raw_functions - ghidra_functions)),
        ghidra_only_functions=tuple(sorted(ghidra_functions - raw_functions)),
        byte_mismatches=byte_mismatches,
        flow_mismatches=flow_mismatches,
        ownership_mismatches=ownership_mismatches,
        unresolved_raw_addresses=unresolved,
        retained_regression_assertions=retained,
        formatoperands_dispatch=None,
    )


def _instruction_reaches(cfg: RawCfg, start: int, goal: int) -> bool:
    successors: dict[int, set[int]] = {}
    for block in cfg.blocks:
        for left, right in zip(
            block.instruction_addresses,
            block.instruction_addresses[1:],
        ):
            successors.setdefault(left, set()).add(right)
    for edge in cfg.edges:
        if edge.kind in {"direct-call", "indirect-call-table"}:
            continue
        successors.setdefault(edge.source, set()).add(edge.target)

    pending = [start]
    seen: set[int] = set()
    while pending:
        address = pending.pop()
        if address == goal:
            return True
        if address in seen:
            continue
        seen.add(address)
        pending.extend(sorted(successors.get(address, ()), reverse=True))
    return False


def validate_gc125n_formatoperands(cfg: RawCfg) -> dict[str, Any]:
    """Require the exact 466-entry real-opcode formatter dispatch closure."""
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
    payload = (
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _write_atomic(path, payload)
