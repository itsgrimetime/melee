"""Proof-bound retail runtime hook installation and lifecycle tracking.

The loader is a trust boundary: it accepts only the two fixed GC/1.2.5n table
basenames, hashes the actual compiler, validates the independently registered
proof and its digest-bound hook manifest, and re-decodes every captured x86
instruction.  The gdb-side installer repeats the byte/decode checks against
the stopped inferior before creating any breakpoint.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import capstone
from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from capstone.x86 import X86_OP_MEM
from capstone.x86_const import X86_INS_CALL

from . import pe, struct_map
from .backend_instrumentation_proof import (
    classify_operand,
    expand_operand_descriptors,
    proof_sha256,
    resolve_operand_role,
    validate_embedded_proof,
)
from .backend_runtime_hook_manifest import (
    runtime_hook_manifest_sha256,
    validate_runtime_hook_manifest,
)

EXPECTED_COMPILER_SHA256 = (
    "ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c"
)

_SIBLINGS = {
    "gc_125n.json": (
        "gc_125n_lifetime_proof.json",
        "gc_125n_lifetime_hooks.json",
    ),
    "gc_125n.candidate.json": (
        "gc_125n_lifetime_proof.candidate.json",
        "gc_125n_lifetime_hooks.candidate.json",
    ),
}
_ENTITY_KINDS = frozenset({"pcode", "objobject"})


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    """One lifecycle event in the global gap-free sequence."""

    lifecycle_sequence: int
    kind: str
    entity_kind: str
    address: int
    site_id: str
    allocation_generation: int


class LifecycleTracker:
    """Track active identities and physical-address allocation generations."""

    def __init__(self) -> None:
        self._events: list[LifecycleEvent] = []
        self._generations: dict[tuple[str, int], int] = {}
        self._active: set[tuple[str, int]] = set()
        self._active_lengths: dict[tuple[str, int], int] = {}
        self._identity_by_generation: dict[tuple[str, int, int], str] = {}
        self._next_identity: dict[str, int] = {"pcode": 0, "objobject": 0}

    @property
    def events(self) -> tuple[LifecycleEvent, ...]:
        return tuple(self._events)

    def sequence_at_stop(self) -> int:
        return len(self._events) - 1

    def generation(self, entity_kind: str, address: int) -> int | None:
        key = self._key(entity_kind, address)
        return self._generations.get(key) if key in self._active else None

    def identity(self, entity_kind: str, address: int) -> str | None:
        generation = self.generation(entity_kind, address)
        if generation is None:
            return None
        return self._identity_by_generation.get(
            (entity_kind, address, generation)
        )

    def active_allocations(
        self, entity_kind: str
    ) -> tuple[tuple[int, int, int, str], ...]:
        """Return canonical active (base, length, generation, identity) rows."""

        if entity_kind not in _ENTITY_KINDS:
            raise ValueError(f"unknown lifecycle entity kind {entity_kind!r}")
        rows = []
        for kind, address in sorted(self._active):
            if kind != entity_kind:
                continue
            generation = self._generations[(kind, address)]
            identity = self._identity_by_generation[(kind, address, generation)]
            rows.append(
                (
                    address,
                    self._active_lengths.get((kind, address), 0),
                    generation,
                    identity,
                )
            )
        return tuple(rows)

    def resolve_containing(
        self, entity_kind: str, address: int, width: int = 1
    ) -> tuple[int, int, int, str]:
        if type(address) is not int or address <= 0:
            raise ValueError("contained address must be positive integer")
        if type(width) is not int or width <= 0:
            raise ValueError("contained width must be positive integer")
        matches = [
            row
            for row in self.active_allocations(entity_kind)
            if row[1] > 0 and row[0] <= address and address + width <= row[0] + row[1]
        ]
        if len(matches) != 1:
            raise ValueError(
                f"address {address:#x} has {len(matches)} active {entity_kind} extents"
            )
        return matches[0]

    @staticmethod
    def _key(entity_kind: str, address: int) -> tuple[str, int]:
        if entity_kind not in _ENTITY_KINDS:
            raise ValueError(f"unknown lifecycle entity kind {entity_kind!r}")
        if type(address) is not int or address <= 0:
            raise ValueError("lifecycle address must be a positive integer")
        return entity_kind, address

    def _append(
        self,
        kind: str,
        entity_kind: str,
        address: int,
        site_id: str,
        generation: int,
    ) -> LifecycleEvent:
        if type(site_id) is not str or not site_id:
            raise ValueError("lifecycle site ID must be a nonempty string")
        event = LifecycleEvent(
            lifecycle_sequence=len(self._events),
            kind=kind,
            entity_kind=entity_kind,
            address=address,
            site_id=site_id,
            allocation_generation=generation,
        )
        self._events.append(event)
        return event

    def record_allocation(
        self,
        entity_kind: str,
        address: int,
        site_id: str,
        allocation_length: int | None = None,
    ) -> LifecycleEvent:
        key = self._key(entity_kind, address)
        if key in self._active:
            raise ValueError("lifecycle address is already active")
        if allocation_length is not None and (
            type(allocation_length) is not int or allocation_length <= 0
        ):
            raise ValueError("allocation length must be positive integer")
        generation = self._generations.get(key, 0) + 1
        self._generations[key] = generation
        self._active.add(key)
        if allocation_length is not None:
            self._active_lengths[key] = allocation_length
        self._next_identity[entity_kind] += 1
        prefix = "pc" if entity_kind == "pcode" else "obj"
        self._identity_by_generation[(entity_kind, address, generation)] = (
            f"{prefix}-{self._next_identity[entity_kind]}"
        )
        return self._append(
            "allocation", entity_kind, address, site_id, generation
        )

    def _record_retirement(
        self, kind: str, entity_kind: str, address: int, site_id: str
    ) -> LifecycleEvent:
        key = self._key(entity_kind, address)
        if key not in self._active:
            raise ValueError("lifecycle address is not active")
        generation = self._generations[key]
        self._active.remove(key)
        self._active_lengths.pop(key, None)
        return self._append(kind, entity_kind, address, site_id, generation)

    def record_recycle(
        self, entity_kind: str, address: int, site_id: str
    ) -> LifecycleEvent:
        return self._record_retirement(
            "recycle", entity_kind, address, site_id
        )

    def record_rewind(
        self, entity_kind: str, address: int, site_id: str
    ) -> LifecycleEvent:
        return self._record_retirement("rewind", entity_kind, address, site_id)

    def record_release(
        self, entity_kind: str, address: int, site_id: str
    ) -> LifecycleEvent:
        return self._record_retirement(
            "release", entity_kind, address, site_id
        )


@dataclass(slots=True)
class Invocation:
    site_id: str
    thread_id: int
    stack_identity: int
    return_address: int
    captures: dict[str, object] = field(default_factory=dict)


class InvocationStack:
    """Per-site/per-thread LIFO state for recursive and nested hook calls."""

    def __init__(self) -> None:
        self._pending: dict[tuple[str, int], list[Invocation]] = {}

    def push(
        self,
        site_id: str,
        *,
        thread_id: int,
        stack_identity: int,
        return_address: int,
        captures: dict[str, object] | None = None,
    ) -> Invocation:
        if not site_id:
            raise ValueError("invocation site ID must be nonempty")
        row = Invocation(
            site_id,
            thread_id,
            stack_identity,
            return_address,
            dict(captures or {}),
        )
        self._pending.setdefault((site_id, thread_id), []).append(row)
        return row

    def complete(
        self,
        site_id: str,
        thread_id: int,
        stack_identity: int,
        return_address: int,
    ) -> Invocation:
        key = (site_id, thread_id)
        pending = self._pending.get(key)
        if not pending:
            raise ValueError("return has no matching pending invocation")
        row = pending[-1]
        if (
            row.stack_identity != stack_identity
            or row.return_address != return_address
        ):
            raise ValueError("return/stack identity mismatch")
        pending.pop()
        if not pending:
            self._pending.pop(key, None)
        return row

    def require_empty(self) -> None:
        if self._pending:
            raise ValueError("runtime hook invocation stack is incomplete")


@dataclass(slots=True)
class RuntimeBundle:
    """One exact validated bundle or the controlled installed unpromoted state."""

    table_path: Path
    compiler_path: Path
    compiler_sha256: str
    table: dict[str, object]
    proof: dict[str, object] | None
    manifest: dict[str, object] | None
    status: str
    expected_site_ids: frozenset[str] = frozenset()
    tracker: LifecycleTracker = field(default_factory=LifecycleTracker)
    installed_site_ids: set[str] = field(default_factory=set)
    hit_site_ids: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    invocation_stack: InvocationStack = field(default_factory=InvocationStack)
    breakpoints: list[object] = field(default_factory=list, repr=False)
    pcode_events: list[dict[str, object]] = field(default_factory=list)
    event_cap: int = 8192
    dropped_events: int = 0
    truncated: bool = False
    next_pcode_event_sequence: int = 0
    next_operand_lineage: int = 0
    operand_lineages: dict[tuple[str, int], str] = field(default_factory=dict)
    emission_offset: int = 0
    emitted_bytes: bytearray = field(default_factory=bytearray, repr=False)
    anchor_diagnostics: list[str] = field(default_factory=list)

    @property
    def validated(self) -> bool:
        return self.status == "validated"


def _reject_constant(token: str) -> object:
    raise ValueError(f"non-I-JSON numeric constant {token!r}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _load_ijson(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"missing {label}: {path}")
    try:
        text = path.read_bytes().decode("utf-8", "strict")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        value = struct_map.materialize_json_safe(value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is not strict I-JSON: {exc}") from exc
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    return value


def _controlled_unpromoted(
    table_path: Path,
    table: dict[str, object],
    compiler_path: Path,
    compiler_sha256: str,
) -> RuntimeBundle | None:
    if table_path.name != "gc_125n.json":
        return None
    rows = table.get("instrumentation_proofs")
    reader = table.get("backend_reader")
    gate = reader.get("pcode_instrumentation") if type(reader) is dict else None
    if rows != [] or type(gate) is not dict or gate.get("validated") is not False:
        return None
    if gate.get("compiler_executable_sha256") != compiler_sha256:
        raise ValueError("unpromoted gate compiler digest differs from executable")
    for field_name in ("proof_id", "proof_sha256"):
        if gate.get(field_name) is not None:
            raise ValueError(f"unpromoted gate {field_name} must be null")
    for field_name in (
        "operand_rewrite_site_ids",
        "operand_mutation_site_ids",
        "code_emission_site_ids",
    ):
        if gate.get(field_name) != []:
            raise ValueError(f"unpromoted gate {field_name} must be empty")
    return RuntimeBundle(
        table_path,
        compiler_path,
        compiler_sha256,
        table,
        None,
        None,
        "unpromoted",
    )


def _decoder() -> Cs:
    if capstone.__version__ != "5.0.7":
        raise ValueError(
            "runtime x86 decoder must be audited Capstone 5.0.7, got "
            f"{capstone.__version__}"
        )
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoder.detail = True
    return decoder


def _decode_exact(raw: bytes, address: int):
    instructions = list(_decoder().disasm(raw, address, count=2))
    if len(instructions) != 1 or instructions[0].size != len(raw):
        raise ValueError(
            f"breakpoint bytes at {address:#x} are not exactly one x86 instruction"
        )
    return instructions[0]


def _validate_runtime_plan_bytes(
    image: pe.Image, manifest: dict[str, object]
) -> None:
    seen_addresses: set[int] = set()
    for site in manifest["sites"]:
        site_id = site["site_id"]
        breakpoints = site["breakpoints"]
        decoded_by_phase: dict[str, object] = {}
        if breakpoints[0]["address"] != site["proof_address"]:
            raise ValueError(f"runtime site {site_id} proof/before address differs")
        for breakpoint in breakpoints:
            address = breakpoint["address"]
            if address in seen_addresses:
                raise ValueError(f"duplicate runtime breakpoint address {address:#x}")
            seen_addresses.add(address)
            expected = bytes.fromhex(breakpoint["instruction_bytes"])
            if not any(
                start <= address and address + len(expected) <= end
                for start, end in image.executable_ranges
            ):
                raise ValueError(
                    f"runtime breakpoint {address:#x} is outside executable bytes"
                )
            actual = image.read(address, len(expected))
            if actual != expected:
                raise ValueError(
                    f"runtime breakpoint bytes differ at {address:#x}: "
                    f"expected {expected.hex()}, got {actual.hex()}"
                )
            decoded_by_phase[breakpoint["phase"]] = _decode_exact(actual, address)
        pairing = site["pairing"]
        before = decoded_by_phase["before"]
        if pairing == "same-thread-call-return":
            if before.id != X86_INS_CALL:
                raise ValueError(f"call-return site {site_id} before instruction is not call")
            returned = next(row for row in breakpoints if row["phase"] == "return")
            if returned["address"] != before.address + before.size:
                raise ValueError(f"call-return site {site_id} return address differs")
        elif pairing == "same-thread-instruction":
            after = next(row for row in breakpoints if row["phase"] == "after")
            if after["address"] != before.address + before.size:
                raise ValueError(f"instruction site {site_id} after address differs")
        phases = set(decoded_by_phase)
        for source_index, source in enumerate(site["capture_sources"]):
            phase = source["phase"]
            if phase not in phases:
                raise ValueError(
                    f"runtime site {site_id} capture source {source_index} has no phase"
                )
            if source["source_kind"] == "effective-address":
                operand_index = source["operand_index"]
                instruction = decoded_by_phase[phase]
                if operand_index >= len(instruction.operands):
                    raise ValueError(
                        f"runtime site {site_id} effective-address operand index is absent"
                    )
                if instruction.operands[operand_index].type != X86_OP_MEM:
                    raise ValueError(
                        f"runtime site {site_id} effective-address operand is not memory"
                    )


def load_runtime_bundle(
    table_path: str | Path, compiler_path: str | Path
) -> RuntimeBundle:
    """Load one exact production/candidate bundle or controlled unpromoted default."""

    table_path = Path(table_path)
    compiler_path = Path(compiler_path)
    sibling_names = _SIBLINGS.get(table_path.name)
    if sibling_names is None:
        raise ValueError(
            "runtime instrumentation table basename must be gc_125n.json or "
            "gc_125n.candidate.json"
        )
    image = pe.load(
        compiler_path,
        expected_sha256=EXPECTED_COMPILER_SHA256,
        require_pe32_i386=True,
    )
    table = _load_ijson(table_path, "runtime instrumentation table")
    registry_errors = struct_map.validate_instrumentation_proof_registry(table)
    if registry_errors:
        raise ValueError("invalid instrumentation registry: " + "; ".join(registry_errors))
    unpromoted = _controlled_unpromoted(
        table_path, table, compiler_path, image.sha256
    )
    if unpromoted is not None:
        return unpromoted

    registry = table.get("instrumentation_proofs")
    if type(registry) is not list or len(registry) != 1:
        raise ValueError("runtime instrumentation requires exactly one registry tuple")
    row = registry[0]
    if type(row) is not dict or row.get("promoted") is not True:
        raise ValueError("runtime instrumentation registry tuple is not promoted")

    proof_path = table_path.parent / sibling_names[0]
    manifest_path = table_path.parent / sibling_names[1]
    proof = _load_ijson(proof_path, "lifetime proof sibling")
    try:
        manifest = _load_ijson(manifest_path, "runtime hook manifest sibling")
    except ValueError as exc:
        if not manifest_path.exists():
            raise ValueError(
                f"missing runtime hook manifest sibling: {manifest_path}"
            ) from exc
        raise

    digest = proof_sha256(proof)
    if row.get("proof_sha256") != digest:
        raise ValueError("proof digest differs from registry tuple")
    if row.get("proof_id") != proof.get("proof_id"):
        raise ValueError("proof ID differs from registry tuple")
    if row.get("compiler_executable_sha256") != image.sha256:
        raise ValueError("registry compiler digest differs from executable")
    embedded_errors = validate_embedded_proof(proof, table, image.sha256)
    if embedded_errors:
        raise ValueError("invalid proof registry binding: " + "; ".join(embedded_errors))
    gate_errors = struct_map.validate_pcode_instrumentation_capability(
        table, proof=proof
    )
    if gate_errors:
        raise ValueError("invalid PCode instrumentation gate: " + "; ".join(gate_errors))
    manifest_errors = validate_runtime_hook_manifest(manifest, proof)
    if manifest_errors:
        raise ValueError("invalid runtime hook manifest: " + "; ".join(manifest_errors))
    _validate_runtime_plan_bytes(image, manifest)
    expected_site_ids = frozenset(site["site_id"] for site in manifest["sites"])
    if len(expected_site_ids) != len(manifest["sites"]):
        raise ValueError("runtime hook manifest has duplicate site IDs")
    return RuntimeBundle(
        table_path,
        compiler_path,
        image.sha256,
        table,
        proof,
        manifest,
        "validated",
        expected_site_ids,
    )


def _thread_id(gdb: object) -> int:
    selected = getattr(gdb, "selected_thread", None)
    if not callable(selected):
        return 0
    thread = selected()
    for name in ("global_num", "num"):
        value = getattr(thread, name, None)
        if type(value) is int:
            return value
    return 0


def _effective_address(ctx: object, instruction: object, operand_index: int) -> int:
    operand = instruction.operands[operand_index]
    memory = operand.mem
    value = memory.disp
    if memory.base:
        value += ctx.reg(instruction.reg_name(memory.base))
    if memory.index:
        value += ctx.reg(instruction.reg_name(memory.index)) * memory.scale
    return value & 0xFFFFFFFF


def _capture_phase(ctx: object, site: dict[str, object], phase: str) -> dict[str, object]:
    breakpoint = next(row for row in site["breakpoints"] if row["phase"] == phase)
    raw = ctx.read(breakpoint["address"], len(bytes.fromhex(breakpoint["instruction_bytes"])))
    expected = bytes.fromhex(breakpoint["instruction_bytes"])
    if raw != expected:
        raise ValueError(f"runtime breakpoint bytes changed at {breakpoint['address']:#x}")
    instruction = _decode_exact(raw, breakpoint["address"])
    esp = ctx.reg("esp")
    captures: dict[str, object] = {}
    for source in site["capture_sources"]:
        if source["phase"] != phase:
            continue
        kind = source["source_kind"]
        if kind == "stack-argument":
            address = esp + 4 * (source["stack_argument_index"] + 1)
            value: object = int.from_bytes(ctx.read(address, source["byte_width"]), "little")
        elif kind in {"x86-register", "return-register"}:
            width = source["byte_width"]
            value = ctx.reg(source["register"]) & ((1 << (width * 8)) - 1)
        elif kind == "effective-address":
            value = (
                _effective_address(ctx, instruction, source["operand_index"])
                + source["byte_offset"]
            ) & 0xFFFFFFFF
        elif kind == "memory-at-source":
            address = (ctx.reg(source["register"]) + source["byte_offset"]) & 0xFFFFFFFF
            value = ctx.read(address, source["byte_width"])
        else:  # manifest validation makes this unreachable
            raise ValueError(f"unsupported capture source kind {kind!r}")
        captures[source["name"]] = value
    return captures


def _entity_kind(bundle: RuntimeBundle, site_id: str) -> str:
    assert bundle.proof is not None
    for family in ("allocation_sites", "free_sites"):
        for row in bundle.proof[family]:
            if row["site_id"] == site_id:
                return row["entity_kind"]
    raise ValueError(f"lifecycle site {site_id!r} has no entity kind")


def _append_pcode_event(
    bundle: RuntimeBundle, row: dict[str, object]
) -> dict[str, object]:
    """Publish one complete event or record an explicit cap failure."""

    if len(bundle.pcode_events) >= bundle.event_cap:
        bundle.dropped_events += 1
        bundle.truncated = True
        raise ValueError("runtime PCode event cap reached")
    event = {
        **row,
        "pcode_event_sequence": bundle.next_pcode_event_sequence,
    }
    bundle.pcode_events.append(event)
    bundle.next_pcode_event_sequence += 1
    return event


def _new_lineage(bundle: RuntimeBundle) -> str:
    bundle.next_operand_lineage += 1
    return f"ol-{bundle.next_operand_lineage}"


def _lineage(
    bundle: RuntimeBundle, pcode_id: str, operand_index: int
) -> str:
    key = (pcode_id, operand_index)
    lineage = bundle.operand_lineages.get(key)
    if lineage is None:
        lineage = _new_lineage(bundle)
        bundle.operand_lineages[key] = lineage
    return lineage


def _read_exact(read: object, address: int, size: int, label: str) -> bytes:
    reader = read if callable(read) else getattr(read, "read", None)
    if not callable(reader):
        raise ValueError(f"{label} reader is unavailable")
    raw = reader(address, size)
    if not isinstance(raw, (bytes, bytearray, memoryview)) or len(raw) != size:
        raise ValueError(f"{label} requires an exact {size}-byte read")
    return bytes(raw)


def _pcode_raw_state(
    bundle: RuntimeBundle, read: object, runtime_address: int
) -> dict[str, object]:
    generation = bundle.tracker.generation("pcode", runtime_address)
    pcode_id = bundle.tracker.identity("pcode", runtime_address)
    if generation is None or pcode_id is None:
        raise ValueError(
            f"PCode {runtime_address:#x} has no active allocation identity"
        )
    opcode_id = int.from_bytes(
        _read_exact(read, runtime_address + 0x14, 2, "PCode opcode"),
        "little",
        signed=True,
    )
    arg_count = int.from_bytes(
        _read_exact(read, runtime_address + 0x1A, 2, "PCode arg count"),
        "little",
        signed=True,
    )
    if opcode_id < 0 or arg_count < 0 or arg_count > 64:
        raise ValueError("PCode opcode/arg count is outside audited bounds")
    operands = [
        _read_exact(
            read,
            runtime_address + 0x1C + index * 0x0C,
            0x0C,
            f"PCodeArg[{index}]",
        )
        for index in range(arg_count)
    ]
    return {
        "pcode_id": pcode_id,
        "runtime_address": runtime_address,
        "allocation_generation": generation,
        "lifecycle_sequence_at_capture": bundle.tracker.sequence_at_stop(),
        "opcode_id": opcode_id,
        "arg_count": arg_count,
        "raw_operands": operands,
    }


def _opcode_name(bundle: RuntimeBundle, opcode_id: int) -> str:
    if bundle.proof is None:
        raise ValueError("runtime bundle has no proof")
    rows = bundle.proof.get("opcode_table")
    if type(rows) is not list:
        raise ValueError("proof opcode table is unavailable")
    matches = [
        row
        for row in rows
        if type(row) is dict and row.get("opcode_id") == opcode_id
    ]
    if len(matches) != 1 or type(matches[0].get("mnemonic")) is not str:
        raise ValueError(f"opcode {opcode_id} has no unique proof row")
    return str(matches[0]["mnemonic"])


def _materialize_state(
    bundle: RuntimeBundle,
    raw_state: dict[str, object],
    *,
    stage: str,
    lineage_overrides: dict[int, tuple[str, tuple[str, ...] | None]] | None = None,
    parse_registers: bool = True,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if bundle.proof is None:
        raise ValueError("runtime bundle has no proof")
    opcode_id = int(raw_state["opcode_id"])
    arg_count = int(raw_state["arg_count"])
    descriptors = expand_operand_descriptors(
        bundle.proof, opcode_id, arg_count
    )
    pcode_id = str(raw_state["pcode_id"])
    inventory: list[dict[str, object]] = []
    parsed: list[dict[str, object]] = []
    for index, (raw, descriptor) in enumerate(
        zip(raw_state["raw_operands"], descriptors, strict=True)
    ):
        assert isinstance(raw, bytes)
        lineage, parents = (
            lineage_overrides[index]
            if lineage_overrides is not None and index in lineage_overrides
            else (_lineage(bundle, pcode_id, index), None)
        )
        bundle.operand_lineages[(pcode_id, index)] = lineage
        operand = {
            "operand_index": index,
            "operand_lineage_id": lineage,
            "raw_arg_kind_id": raw[0],
            "raw_register_flags": raw[1],
            "raw_register_value": int.from_bytes(raw[2:4], "little"),
            "raw_payload_hex": raw.hex(),
            "raw_payload_sha256": hashlib.sha256(raw).hexdigest(),
        }
        if parents is not None:
            operand["parent_lineage_ids"] = list(parents)
        inventory.append(operand)
        if descriptor.raw_arg_kind_id != raw[0]:
            raise ValueError(
                f"PCodeArg[{index}] kind differs from proof descriptor"
            )
        if not parse_registers or not descriptor.state_rules:
            continue
        role = resolve_operand_role(descriptor, raw[1])
        state = classify_operand(
            descriptor,
            stage,
            raw[1],
            int.from_bytes(raw[2:4], "little"),
        )
        parsed.append(
            {
                "operand_index": index,
                "role": role,
                "class_id": descriptor.class_id,
                "raw_arg_kind_id": raw[0],
                "raw_register_flags": raw[1],
                "raw_register_value": int.from_bytes(raw[2:4], "little"),
                "allocation_state": state.allocation_state,
                "register_form": descriptor.register_form,
                "operand_lineage_id": lineage,
                "virtual_kind": (
                    descriptor.virtual_kind
                    if state.allocation_state == "virtual"
                    else None
                ),
                "virtual": state.virtual,
                "physical_register": state.physical_register,
            }
        )
    state_row = {
        key: raw_state[key]
        for key in (
            "pcode_id",
            "runtime_address",
            "allocation_generation",
            "lifecycle_sequence_at_capture",
            "opcode_id",
            "arg_count",
        )
    }
    state_row["operands"] = inventory
    return state_row, parsed


def _capture_range_raw_states(
    bundle: RuntimeBundle, read: object, pointer: int, length: int
) -> list[dict[str, object]]:
    if type(pointer) is not int or pointer <= 0:
        raise ValueError("mutation range pointer must be positive integer")
    if type(length) is not int or length < 0:
        raise ValueError("mutation range length must be nonnegative integer")
    end = pointer + max(length, 1)
    bases = [
        base
        for base, _size, _generation, _identity in bundle.tracker.active_allocations(
            "pcode"
        )
        if base == pointer or pointer <= base < end
    ]
    if not bases:
        raise ValueError("mutation range contains no active PCode allocation")
    return [_pcode_raw_state(bundle, read, base) for base in bases]


def capture_operand_rewrite(
    bundle: RuntimeBundle,
    read: object,
    *,
    site_id: str,
    operand_address: int,
    before: bytes,
) -> dict[str, object]:
    """Validate an exact 12-byte before/after rewrite and publish atomically."""

    if len(before) != 0x0C:
        raise ValueError("operand rewrite before state must be exactly 12 bytes")
    after = _read_exact(read, operand_address, 0x0C, "operand rewrite after state")
    if before[:2] != after[:2]:
        raise ValueError("operand rewrite changed PCodeArg kind or flags")
    base, _length, generation, pcode_id = bundle.tracker.resolve_containing(
        "pcode", operand_address, 0x0C
    )
    relative = operand_address - (base + 0x1C)
    if relative < 0 or relative % 0x0C:
        raise ValueError("operand rewrite address is not an inline PCodeArg")
    operand_index = relative // 0x0C
    raw_state = _pcode_raw_state(bundle, read, base)
    if operand_index >= raw_state["arg_count"]:
        raise ValueError("operand rewrite index lies outside PCode arg count")
    assert bundle.proof is not None
    descriptor = expand_operand_descriptors(
        bundle.proof, int(raw_state["opcode_id"]), int(raw_state["arg_count"])
    )[operand_index]
    if before[0] != descriptor.raw_arg_kind_id:
        raise ValueError("operand rewrite kind differs from proof descriptor")
    role = resolve_operand_role(descriptor, before[1])
    before_state = classify_operand(
        descriptor,
        "allocator_input",
        before[1],
        int.from_bytes(before[2:4], "little"),
    )
    after_state = classify_operand(
        descriptor,
        "code_emission",
        after[1],
        int.from_bytes(after[2:4], "little"),
    )
    if before_state.allocation_state != "virtual" or after_state.allocation_state != "physical":
        raise ValueError("operand rewrite is not virtual-to-physical")
    class_shapes = {0: "gpr", 1: "fpr", 9: "vector"}
    event = {
        "event": "operand_rewrite",
        "instrumented_site_id": site_id,
        "pcode_id": pcode_id,
        "operand_index": operand_index,
        "operand_lineage_id": _lineage(bundle, pcode_id, operand_index),
        "role": role,
        "class_id": descriptor.class_id,
        "class_name": class_shapes.get(descriptor.class_id),
        "virtual_kind": descriptor.virtual_kind,
        "virtual": before_state.virtual,
        "ig_id": before_state.virtual,
        "allocated_physical": after_state.physical_register,
        "runtime_address": base,
        "allocation_generation": generation,
        "lifecycle_sequence_at_capture": bundle.tracker.sequence_at_stop(),
        "source_stage": "allocator_operand_rewrite",
        "confidence": "observed",
    }
    return _append_pcode_event(bundle, event)


def _operand_signature(operand: dict[str, object]) -> tuple[object, ...]:
    return (
        operand.get("raw_arg_kind_id"),
        operand.get("raw_register_flags"),
        operand.get("raw_register_value"),
        operand.get("raw_payload_hex"),
    )


def capture_pcode_mutation(
    bundle: RuntimeBundle,
    *,
    site_id: str,
    mutation_kind: str,
    input_raw_states: list[dict[str, object]],
    output_raw_states: list[dict[str, object]],
) -> dict[str, object]:
    """Publish one complete paired mutation with deterministic lineage."""

    if mutation_kind not in {
        "create",
        "delete",
        "reorder",
        "clone",
        "replace",
        "spill",
        "coalesce",
    }:
        raise ValueError("unknown PCode mutation kind")
    if mutation_kind == "create" and (input_raw_states or not output_raw_states):
        raise ValueError("create requires no inputs and nonempty outputs")
    if mutation_kind == "delete" and (not input_raw_states or output_raw_states):
        raise ValueError("delete requires inputs and no outputs")
    if mutation_kind not in {"create", "delete"} and (
        not input_raw_states or not output_raw_states
    ):
        raise ValueError("paired mutation requires nonempty inputs and outputs")

    inputs = [
        _materialize_state(
            bundle,
            raw,
            stage="allocator_input",
            parse_registers=False,
        )[0]
        for raw in input_raw_states
    ]
    input_operands = [
        operand
        for state in inputs
        for operand in state["operands"]
        if type(operand) is dict
    ]
    input_by_signature: dict[tuple[object, ...], list[str]] = defaultdict(list)
    input_by_index: dict[int, list[str]] = defaultdict(list)
    for operand in input_operands:
        lineage = str(operand["operand_lineage_id"])
        input_by_signature[_operand_signature(operand)].append(lineage)
        input_by_index[int(operand["operand_index"])].append(lineage)

    outputs: list[dict[str, object]] = []
    output_ids: set[str] = set()
    for raw in output_raw_states:
        pcode_id = str(raw["pcode_id"])
        if pcode_id in output_ids:
            raise ValueError("PCode mutation has duplicate output identity")
        output_ids.add(pcode_id)
        overrides: dict[int, tuple[str, tuple[str, ...] | None]] = {}
        for index, raw_operand in enumerate(raw["raw_operands"]):
            assert isinstance(raw_operand, bytes)
            signature = (
                raw_operand[0],
                raw_operand[1],
                int.from_bytes(raw_operand[2:4], "little"),
                raw_operand.hex(),
            )
            exact_parents = sorted(set(input_by_signature.get(signature, ())))
            positional_parents = sorted(set(input_by_index.get(index, ())))
            parents = exact_parents or positional_parents
            if mutation_kind == "create":
                lineage = _new_lineage(bundle)
                parent_tuple: tuple[str, ...] | None = ()
            elif mutation_kind == "clone" and parents:
                lineage = parents[0]
                parent_tuple = None
            elif len(exact_parents) == 1:
                lineage = exact_parents[0]
                parent_tuple = None
            else:
                lineage = _new_lineage(bundle)
                parent_tuple = tuple(parents)
                if not parent_tuple:
                    raise ValueError(
                        "derived mutation operand has no input lineage parent"
                    )
            overrides[index] = (lineage, parent_tuple)
        outputs.append(
            _materialize_state(
                bundle,
                raw,
                stage="mutation_output",
                lineage_overrides=overrides,
                parse_registers=False,
            )[0]
        )
    inputs.sort(
        key=lambda row: (
            str(row["pcode_id"]),
            int(row["runtime_address"]),
            int(row["allocation_generation"]),
        )
    )
    outputs.sort(
        key=lambda row: (
            str(row["pcode_id"]),
            int(row["runtime_address"]),
            int(row["allocation_generation"]),
        )
    )
    return _append_pcode_event(
        bundle,
        {
            "event": "pcode_mutation",
            "instrumented_site_id": site_id,
            "mutation_kind": mutation_kind,
            "inputs": inputs,
            "outputs": outputs,
        },
    )


def _machine_mappings(
    code: bytes, parsed: list[dict[str, object]]
) -> list[dict[str, object]]:
    from .backend_pcode_lineage import _decode_registers

    decoded = _decode_registers(code, 0)
    result: list[dict[str, object]] = []
    for offset, position, key, class_id, physical in decoded:
        role = key.split(":", 1)[0]
        matches = [
            row
            for row in parsed
            if row.get("class_id") == class_id
            and row.get("physical_register") == physical
            and row.get("role") in {role, "use-def"}
        ]
        if len(matches) != 1:
            raise ValueError(
                f"emitted machine operand {key} has {len(matches)} PCode matches"
            )
        match = matches[0]
        result.append(
            {
                "instruction_offset_within_range": offset,
                "machine_operand_position": position,
                "machine_operand_key": key,
                "emission_pcode_operand_index": match["operand_index"],
                "operand_lineage_id": match["operand_lineage_id"],
                "physical_register": physical,
            }
        )
    return result


def capture_code_emission(
    bundle: RuntimeBundle,
    read: object,
    *,
    site_id: str,
    pcode_pointer: int,
    encoded_word: int,
) -> dict[str, object]:
    """Bind one encoder result to its exact final PCode and machine fields."""

    if type(encoded_word) is not int or not 0 <= encoded_word <= 0xFFFFFFFF:
        raise ValueError("encoded word must be unsigned 32-bit integer")
    raw = _pcode_raw_state(bundle, read, pcode_pointer)
    state, parsed = _materialize_state(
        bundle, raw, stage="code_emission"
    )
    code = encoded_word.to_bytes(4, "big")
    start = bundle.emission_offset
    try:
        mappings = _machine_mappings(code, parsed)
    except (OverflowError, TypeError, ValueError) as exc:
        if not any(row.get("class_id") == 9 for row in parsed):
            raise
        mappings = []
        bundle.anchor_diagnostics.append(
            f"vector anchor decode abstained at {start}: {exc}"
        )
    snapshot = {
        "stage": "code_emission",
        "lifecycle_sequence_at_capture": state[
            "lifecycle_sequence_at_capture"
        ],
        "runtime_address": state["runtime_address"],
        "allocation_generation": state["allocation_generation"],
        "opcode_id": state["opcode_id"],
        "opcode": _opcode_name(bundle, int(state["opcode_id"])),
        "arg_count": state["arg_count"],
        "parsed_register_operands": parsed,
        "operand_lineage_inventory": state["operands"],
    }
    event = _append_pcode_event(
        bundle,
        {
            "event": "code_emission",
            "instrumented_site_id": site_id,
            "pcode_id": state["pcode_id"],
            "runtime_address": state["runtime_address"],
            "allocation_generation": state["allocation_generation"],
            "lifecycle_sequence_at_capture": state[
                "lifecycle_sequence_at_capture"
            ],
            "emission_snapshot": snapshot,
            "code_ranges": [
                {
                    "start": start,
                    "end_exclusive": start + 4,
                    "bytes": code.hex(),
                    "relocations": [],
                    "machine_operand_mappings": mappings,
                }
            ],
        },
    )
    bundle.emission_offset += 4
    bundle.emitted_bytes.extend(code)
    return event


def _finish_site(
    bundle: RuntimeBundle,
    site: dict[str, object],
    captures: dict[str, object],
    ctx: object | None = None,
) -> None:
    site_id = site["site_id"]
    operation = site["operation"]
    if operation == "allocation":
        bundle.tracker.record_allocation(
            _entity_kind(bundle, site_id),
            int(captures["allocated_pointer"]),
            site_id,
            int(captures["allocation_length"]),
        )
    elif operation == "cache-acquire":
        bundle.tracker.record_allocation(
            _entity_kind(bundle, site_id),
            int(captures["entity_pointer"]),
            site_id,
        )
    elif operation == "cache-release":
        bundle.tracker.record_recycle(
            _entity_kind(bundle, site_id),
            int(captures["entity_pointer"]),
            site_id,
        )
    elif operation in {"recycle", "rewind", "release"}:
        method = getattr(bundle.tracker, f"record_{operation}")
        method(
            _entity_kind(bundle, site_id),
            int(captures["entity_pointer"]),
            site_id,
        )
    elif operation == "operand-rewrite":
        if ctx is None:
            raise ValueError("operand rewrite capture has no runtime context")
        capture_operand_rewrite(
            bundle,
            ctx,
            site_id=site_id,
            operand_address=int(captures["operand_address"]),
            before=bytes(captures["operand_before"]),
        )
    elif operation in {
        "create",
        "delete",
        "reorder",
        "clone",
        "replace",
        "spill",
        "coalesce",
    }:
        if ctx is None:
            raise ValueError("PCode mutation capture has no runtime context")
        inputs = captures.get("mutation_input_states", [])
        if type(inputs) is not list:
            raise ValueError("PCode mutation input capture is malformed")
        outputs = (
            []
            if operation == "delete"
            else _capture_range_raw_states(
                bundle,
                ctx,
                int(captures["output_pointer"]),
                int(captures["output_length"]),
            )
        )
        capture_pcode_mutation(
            bundle,
            site_id=site_id,
            mutation_kind=operation,
            input_raw_states=inputs,
            output_raw_states=outputs,
        )
    elif operation == "encode":
        if ctx is None:
            raise ValueError("PCode emission capture has no runtime context")
        capture_code_emission(
            bundle,
            ctx,
            site_id=site_id,
            pcode_pointer=int(captures["pcode_pointer"]),
            encoded_word=int(captures["encoded_word"]),
        )
    elif operation == "final-buffer-emission":
        if ctx is None:
            raise ValueError("final buffer capture has no runtime context")
        pointer = int(captures["buffer_pointer"])
        length = int(captures["buffer_length"])
        actual = _read_exact(ctx, pointer, length, "final emitted buffer")
        if actual != bytes(bundle.emitted_bytes):
            raise ValueError(
                "final emitted buffer differs from encoder event bytes"
            )
    else:
        raise ValueError(f"unsupported runtime operation {operation!r}")
    bundle.hit_site_ids.add(site_id)


def _handle_breakpoint(ctx: object, bundle: RuntimeBundle, site: dict[str, object], phase: str) -> None:
    captures = _capture_phase(ctx, site, phase)
    thread_id = _thread_id(ctx.gdb)
    esp = ctx.reg("esp")
    finish_phase = site["breakpoints"][1]["phase"]
    if phase == "before":
        operation = site["operation"]
        if operation == "operand-rewrite":
            operand_address = int(captures["operand_address"])
            captures["operand_before"] = _read_exact(
                ctx,
                operand_address,
                0x0C,
                "operand rewrite before state",
            )
        elif operation in {
            "delete",
            "reorder",
            "clone",
            "replace",
            "spill",
            "coalesce",
        }:
            captures["mutation_input_states"] = _capture_range_raw_states(
                bundle,
                ctx,
                int(captures["input_pointer"]),
                int(captures["input_length"]),
            )
        return_address = site["breakpoints"][1]["address"]
        bundle.invocation_stack.push(
            site["site_id"],
            thread_id=thread_id,
            stack_identity=esp,
            return_address=return_address,
            captures=captures,
        )
        return
    if phase != finish_phase:
        raise ValueError(f"unexpected hook phase {phase!r}")
    invocation = bundle.invocation_stack.complete(
        site["site_id"], thread_id, esp, int(ctx.reg("pc"))
    )
    invocation.captures.update(captures)
    _finish_site(bundle, site, invocation.captures, ctx)


def install_runtime_instrumentation(ctx: object) -> RuntimeBundle:
    """Install every bound plan exactly, or roll back the complete installation."""

    bundle = getattr(ctx, "runtime_bundle", None)
    if not isinstance(bundle, RuntimeBundle):
        raise ValueError("RetroContext has no RuntimeBundle")
    if not bundle.validated:
        ctx.lifecycle_capture = None
        return bundle
    if bundle.manifest is None:
        raise ValueError("validated RuntimeBundle has no manifest")
    if bundle.proof is None:
        raise ValueError("validated RuntimeBundle has no proof")
    binding_errors = [
        *validate_embedded_proof(
            bundle.proof, bundle.table, bundle.compiler_sha256
        ),
        *validate_runtime_hook_manifest(bundle.manifest, bundle.proof),
        *struct_map.validate_pcode_instrumentation_capability(
            bundle.table, proof=bundle.proof
        ),
    ]
    if binding_errors:
        raise ValueError(
            "runtime bundle changed after validation: "
            + "; ".join(binding_errors)
        )
    if {
        site["site_id"] for site in bundle.manifest["sites"]
    } != set(bundle.expected_site_ids):
        raise ValueError("runtime expected site inventory changed after validation")

    # Validate all live bytes and capture semantics before the first install.
    for site in bundle.manifest["sites"]:
        decoded_by_phase: dict[str, object] = {}
        for breakpoint in site["breakpoints"]:
            expected = bytes.fromhex(breakpoint["instruction_bytes"])
            actual = ctx.read(breakpoint["address"], len(expected))
            if actual != expected:
                raise ValueError(
                    f"live breakpoint bytes differ at {breakpoint['address']:#x}"
                )
            decoded_by_phase[breakpoint["phase"]] = _decode_exact(
                actual, breakpoint["address"]
            )
        for source_index, source in enumerate(site["capture_sources"]):
            if source["source_kind"] != "effective-address":
                continue
            instruction = decoded_by_phase[source["phase"]]
            operand_index = source["operand_index"]
            if (
                operand_index >= len(instruction.operands)
                or instruction.operands[operand_index].type != X86_OP_MEM
            ):
                raise ValueError(
                    f"live capture source {source_index} for {site['site_id']} "
                    "does not name a memory operand"
                )

    created: list[object] = []
    bundle.installed_site_ids.clear()
    bundle.hit_site_ids.clear()
    bundle.errors.clear()
    bundle.pcode_events.clear()
    bundle.dropped_events = 0
    bundle.truncated = False
    bundle.next_pcode_event_sequence = 0
    bundle.next_operand_lineage = 0
    bundle.operand_lineages.clear()
    bundle.emission_offset = 0
    bundle.emitted_bytes.clear()
    bundle.anchor_diagnostics.clear()

    class _RuntimeBreakpoint(ctx.gdb.Breakpoint):
        def __init__(self, site: dict[str, object], phase: str, address: int):
            self._site = site
            self._phase = phase
            super().__init__(f"*{address:#x}")

        def stop(self):
            try:
                _handle_breakpoint(ctx, bundle, self._site, self._phase)
            except Exception as exc:  # noqa: BLE001 - capture failures fail the run
                bundle.errors.append(
                    f"{self._site['site_id']}:{self._phase}: {exc}"
                )
            return False

    try:
        for site in bundle.manifest["sites"]:
            site_breakpoints = []
            for breakpoint in site["breakpoints"]:
                handler = _RuntimeBreakpoint(
                    site, breakpoint["phase"], breakpoint["address"]
                )
                site_breakpoints.append(handler)
                created.append(handler)
            if len(site_breakpoints) != len(site["breakpoints"]):
                raise ValueError(f"partial runtime plan installation for {site['site_id']}")
            bundle.installed_site_ids.add(site["site_id"])
        if bundle.installed_site_ids != set(bundle.expected_site_ids):
            raise ValueError("installed runtime site inventory differs from expected")
    except Exception:
        for breakpoint in reversed(created):
            delete = getattr(breakpoint, "delete", None)
            if callable(delete):
                delete()
        bundle.installed_site_ids.clear()
        bundle.breakpoints.clear()
        raise
    bundle.breakpoints[:] = created
    ctx.lifecycle_capture = bundle.tracker
    return bundle


def runtime_bundle_status(bundle: RuntimeBundle) -> dict[str, object]:
    """Return canonical Task 8 installation/hit/lifecycle evidence."""

    if bundle.validated:
        if bundle.installed_site_ids != set(bundle.expected_site_ids):
            message = "installed runtime site inventory differs from expected"
            if message not in bundle.errors:
                bundle.errors.append(message)
        try:
            bundle.invocation_stack.require_empty()
        except ValueError as exc:
            message = str(exc)
            if message not in bundle.errors:
                bundle.errors.append(message)
    status = bundle.status
    if bundle.validated and bundle.errors:
        status = "failed"
    return {
        "status": status,
        "compiler_executable_sha256": bundle.compiler_sha256,
        "proof_id": bundle.proof.get("proof_id") if bundle.proof else None,
        "proof_sha256": proof_sha256(bundle.proof) if bundle.proof else None,
        "manifest_sha256": (
            runtime_hook_manifest_sha256(bundle.manifest)
            if bundle.manifest
            else None
        ),
        "expected_site_ids": sorted(bundle.expected_site_ids),
        "installed_site_ids": sorted(bundle.installed_site_ids),
        "hit_site_ids": sorted(bundle.hit_site_ids),
        "lifecycle_events": runtime_lifecycle_events(bundle),
        "pcode_events": [dict(row) for row in bundle.pcode_events],
        "event_cap": bundle.event_cap,
        "dropped_events": bundle.dropped_events,
        "truncated": bundle.truncated,
        "anchor_diagnostics": list(bundle.anchor_diagnostics),
        "errors": list(bundle.errors),
        "capabilities": [],
    }


def runtime_lifecycle_events(bundle: RuntimeBundle) -> list[dict[str, object]]:
    """Serialize tracker rows into the closed lineage replay schema."""

    if bundle.proof is None:
        return []
    result: list[dict[str, object]] = []
    for event in bundle.tracker.events:
        action = "allocate" if event.kind == "allocation" else "free"
        family = "allocation_sites" if action == "allocate" else "free_sites"
        rows = bundle.proof.get(family)
        matches = [
            row
            for row in rows
            if type(row) is dict and row.get("site_id") == event.site_id
        ] if type(rows) is list else []
        if len(matches) != 1 or type(matches[0].get("compiler_stage")) is not str:
            raise ValueError(
                f"lifecycle site {event.site_id!r} has no unique proof stage"
            )
        result.append(
            {
                "sequence": event.lifecycle_sequence,
                "event": action,
                "entity_kind": event.entity_kind,
                "runtime_address": event.address,
                "allocation_generation": event.allocation_generation,
                "instrumented_site_id": event.site_id,
                "compiler_stage": matches[0]["compiler_stage"],
            }
        )
    return result


def bind_pcode_snapshot_lifecycle(
    events: list[dict[str, object]],
    tracker: LifecycleTracker | RuntimeBundle,
) -> list[dict[str, object]]:
    """Bind every PCode snapshot row to one stopped sequence and generation."""

    if type(events) is not list:
        raise ValueError("PCode snapshot events must be a list")
    bundle = tracker if isinstance(tracker, RuntimeBundle) else None
    lifecycle = bundle.tracker if bundle is not None else tracker
    sequence = lifecycle.sequence_at_stop()
    result: list[dict[str, object]] = []
    for index, event in enumerate(events):
        if type(event) is not dict:
            raise ValueError(f"PCode snapshot event {index} must be an object")
        row = dict(event)
        if row.get("event") == "pcode_instruction":
            address = row.get("runtime_address")
            if type(address) is not int or address <= 0:
                raise ValueError(
                    f"PCode snapshot event {index} has invalid runtime address"
                )
            generation = lifecycle.generation("pcode", address)
            if generation is None:
                raise ValueError(
                    f"PCode snapshot address {address:#x} has no active "
                    "allocation generation"
                )
            row["lifecycle_sequence_at_capture"] = sequence
            row["allocation_generation"] = generation
            if bundle is not None:
                pcode_id = lifecycle.identity("pcode", address)
                if pcode_id is None:
                    raise ValueError(
                        f"PCode snapshot address {address:#x} has no identity"
                    )
                row["pcode_id"] = pcode_id
                inventory = row.get("operand_lineage_inventory")
                if type(inventory) is not list:
                    raise ValueError(
                        f"PCode snapshot event {index} has no operand inventory"
                    )
                bound_inventory = []
                for operand in inventory:
                    if type(operand) is not dict or type(
                        operand.get("operand_index")
                    ) is not int:
                        raise ValueError(
                            f"PCode snapshot event {index} operand is malformed"
                        )
                    operand_row = dict(operand)
                    operand_row["operand_lineage_id"] = _lineage(
                        bundle,
                        pcode_id,
                        int(operand["operand_index"]),
                    )
                    bound_inventory.append(operand_row)
                row["operand_lineage_inventory"] = bound_inventory
        result.append(row)
    return result


__all__ = [
    "EXPECTED_COMPILER_SHA256",
    "InvocationStack",
    "LifecycleEvent",
    "LifecycleTracker",
    "RuntimeBundle",
    "bind_pcode_snapshot_lifecycle",
    "install_runtime_instrumentation",
    "load_runtime_bundle",
    "runtime_bundle_status",
    "runtime_lifecycle_events",
]
