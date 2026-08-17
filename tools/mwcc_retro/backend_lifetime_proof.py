"""Canonical lifetime-proof bundle generation and atomic publication.

The candidate proof, its runtime-hook manifest, and the candidate registry
table form one digest-bound unit.  Ready bundles are published as immutable,
same-filesystem generations and exposed only by a manifest-verifying CURRENT
pointer.  Unresolved inputs never publish a candidate proof generation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

BUNDLE_SCHEMA = "mwcc-retro-lifetime-bundle.v1"
CURRENT_SCHEMA = "mwcc-retro-lifetime-current.v1"

CANONICAL_MEMBERS = (
    "raw-pe-cfg.v1.jsonl",
    "raw-ghidra-crosscheck.v1.json",
    "backend-lifetime-sites.candidate.v1.json",
    "opcode-layouts.candidate.v1.json",
    "backend-lifetime-audit.v1.json",
    "gc_125n_lifetime_hooks.candidate.json",
    "gc_125n_lifetime_proof.candidate.json",
    "gc_125n.candidate.json",
    "REPORT.md",
)

_PROOF_MEMBER = "gc_125n_lifetime_proof.candidate.json"
_HOOK_MEMBER = "gc_125n_lifetime_hooks.candidate.json"
_CANDIDATE_MEMBER = "gc_125n.candidate.json"
_JSONL_MEMBERS = frozenset({"raw-pe-cfg.v1.jsonl"})
_JSON_MEMBERS = frozenset(CANONICAL_MEMBERS) - _JSONL_MEMBERS - {"REPORT.md"}
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_GENERATION_NAME = re.compile(r"gen-[0-9a-f]{64}")


class LifetimeBundleError(ValueError):
    """Raised when a lifetime bundle cannot be generated or trusted."""


@dataclass(frozen=True, slots=True)
class ExactLifetimeProofPlan:
    """Exact proof sites and their independently audited runtime hook rows."""

    allocation_sites: tuple[Mapping[str, object], ...]
    free_sites: tuple[Mapping[str, object], ...]
    operand_rewrite_sites: tuple[Mapping[str, object], ...]
    operand_mutation_sites: tuple[Mapping[str, object], ...]
    code_emission_sites: tuple[Mapping[str, object], ...]
    hook_sites: tuple[Mapping[str, object], ...]
    unresolved: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExactLifetimeBundleInputs:
    """Accepted Task 4-7 facts needed to construct the nine logical members."""

    compiler_sha256: str
    raw_cfg_jsonl: bytes
    ghidra_crosscheck_json: bytes
    value_analysis: object
    lifetime_site_inventory: object
    opcode_layout_inventory: object
    opcode_tables: Mapping[str, object]
    proof_plan: ExactLifetimeProofPlan
    candidate_table: object
    backend_map_candidates: object


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


def _json_value(value: object, *, path: str = "value") -> object:
    """Convert one finite analysis value to deterministic JSON data."""

    if value is None or type(value) in {bool, int, str}:
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            row.name: _json_value(getattr(value, row.name), path=f"{path}.{row.name}")
            for row in fields(value)
        }
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key in sorted(value, key=str):
            if type(key) is not str:
                raise LifetimeBundleError(f"{path} has a non-string object key")
            result[key] = _json_value(value[key], path=f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [
            _json_value(row, path=f"{path}[{index}]")
            for index, row in enumerate(value)
        ]
    if isinstance(value, (set, frozenset)):
        rows = [_json_value(row, path=f"{path}[]") for row in value]
        try:
            return sorted(
                rows,
                key=lambda row: json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        except (TypeError, ValueError) as exc:
            raise LifetimeBundleError(f"{path} set is not canonicalizable") from exc
    raise LifetimeBundleError(
        f"{path} has unsupported analysis type {type(value).__name__}"
    )


def _load_json(payload: bytes, label: str) -> object:
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LifetimeBundleError(f"{label} is invalid JSON") from exc


def _canonicalize_member(name: str, payload: bytes) -> bytes:
    if name in _JSON_MEMBERS:
        return _canonical_json(_load_json(payload, name))
    if name in _JSONL_MEMBERS:
        canonical = bytearray()
        for line_number, line in enumerate(payload.splitlines(), 1):
            if not line.strip():
                continue
            canonical.extend(
                _canonical_json(
                    _load_json(line, f"{name} line {line_number}")
                )
            )
        return bytes(canonical)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LifetimeBundleError(f"{name} is not UTF-8") from exc
    return (text.rstrip("\n") + "\n").encode("utf-8")


def _collect_unresolved(
    inputs: Mapping[str, bytes], compiler_sha256: str
) -> tuple[str, ...]:
    """Collect explicit fail-closed markers from upstream audit artifacts."""

    findings: list[str] = []
    raw_residue_reconciliation: str | None = None
    crosscheck_residue_reconciliation: str | None = None

    def visit(value: object, path: str) -> None:
        if isinstance(value, Mapping):
            for key in sorted(value, key=str):
                child = value[key]
                child_path = f"{path}.{key}"
                if key == "proof_ready" and child is False:
                    findings.append(child_path)
                elif (
                    key == "unresolved"
                    or key.startswith("unresolved_")
                    or key == "blockers"
                    or key.endswith("_blockers")
                ) and bool(child):
                    findings.append(child_path)
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    audit_names = (
        "raw-pe-cfg.v1.jsonl",
        "raw-ghidra-crosscheck.v1.json",
        "backend-lifetime-sites.candidate.v1.json",
        "opcode-layouts.candidate.v1.json",
        "backend-lifetime-audit.v1.json",
    )
    for name in audit_names:
        payload = inputs.get(name)
        if payload is None:
            continue
        if name in _JSONL_MEMBERS:
            rows = []
            for line_number, line in enumerate(payload.splitlines(), 1):
                if line.strip():
                    row = _load_json(line, f"{name} line {line_number}")
                    rows.append(row)
                    visit(row, name)
            if name == "raw-pe-cfg.v1.jsonl":
                metadata_rows = [
                    row
                    for row in rows
                    if isinstance(row, Mapping)
                    and row.get("record_kind") == "metadata"
                ]
                if (
                    len(metadata_rows) != 1
                    or metadata_rows[0].get("compiler_sha256")
                    != compiler_sha256
                ):
                    findings.append(f"{name}.compiler-binding")
                unresolved_rows = [
                    row
                    for row in rows
                    if isinstance(row, Mapping)
                    and row.get("record_kind") == "unresolved-control-target"
                ]
                if unresolved_rows:
                    findings.append(f"{name}.unresolved-control-target")
                residue_summaries = [
                    row
                    for row in rows
                    if isinstance(row, Mapping)
                    and row.get("record_kind")
                    == "unreachable-executable-residue-summary"
                ]
                if (
                    len(residue_summaries) != 1
                    or residue_summaries[0].get("accepted") is not True
                ):
                    findings.append(f"{name}.residue-not-accepted")
                elif (
                    not isinstance(
                        residue_summaries[0].get("reconciliation_sha256"),
                        str,
                    )
                    or not _HEX_64.fullmatch(
                        residue_summaries[0]["reconciliation_sha256"]
                    )
                ):
                    findings.append(f"{name}.residue-not-reconciled")
                else:
                    raw_residue_reconciliation = residue_summaries[0][
                        "reconciliation_sha256"
                    ]
        else:
            parsed = _load_json(payload, name)
            visit(parsed, name)
            if name == "raw-ghidra-crosscheck.v1.json":
                if not isinstance(parsed, Mapping):
                    findings.append(f"{name}.not-an-object")
                    continue
                if parsed.get("compiler_sha256") != compiler_sha256:
                    findings.append(f"{name}.compiler-binding")
                for key in (
                    "byte_mismatches",
                    "residue_conflicts",
                    "unresolved_raw_addresses",
                ):
                    if parsed.get(key):
                        findings.append(f"{name}.{key}")
                flow_mismatches = parsed.get("flow_mismatches")
                if not isinstance(flow_mismatches, list) or any(
                    isinstance(row, Mapping)
                    and row.get("side") == "ghidra-only"
                    for row in flow_mismatches
                ):
                    findings.append(f"{name}.ghidra-only-flow")
                reconciliation = parsed.get("residue_reconciliation_sha256")
                if not isinstance(reconciliation, str) or not _HEX_64.fullmatch(
                    reconciliation
                ):
                    findings.append(f"{name}.residue-not-reconciled")
                else:
                    crosscheck_residue_reconciliation = reconciliation
    if (
        raw_residue_reconciliation is not None
        and crosscheck_residue_reconciliation is not None
        and raw_residue_reconciliation != crosscheck_residue_reconciliation
    ):
        findings.append("raw-pe-cfg.v1.jsonl.residue-reconciliation-binding")
    return tuple(sorted(set(findings)))


def _site_ids(proof: Mapping[str, object], collection: str) -> list[str]:
    rows = proof.get(collection)
    if not isinstance(rows, list):
        raise LifetimeBundleError(f"proof {collection} must be a list")
    result: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not isinstance(row.get("site_id"), str):
            raise LifetimeBundleError(
                f"proof {collection} site {index} has no site_id"
            )
        result.append(row["site_id"])
    return result


def _bind_candidate_table(
    base: object,
    proof: Mapping[str, object],
    proof_digest: str,
) -> dict[str, object]:
    if not isinstance(base, Mapping):
        raise LifetimeBundleError("candidate table must be an object")
    candidate = dict(base)
    compiler_sha256 = proof["compiler_executable_sha256"]
    proof_id = proof["proof_id"]
    registry_row = {
        "compiler_executable_sha256": compiler_sha256,
        "proof_id": proof_id,
        "proof_sha256": proof_digest,
        "promoted": True,
    }
    candidate["instrumentation_proof_schema"] = (
        "mwcc-retro-lifetime-proof.v1"
    )
    candidate["instrumentation_proofs"] = [registry_row]
    reader = candidate.get("backend_reader")
    reader = dict(reader) if isinstance(reader, Mapping) else {}
    reader["pcode_instrumentation"] = {
        "validated": True,
        "compiler_executable_sha256": compiler_sha256,
        "proof_id": proof_id,
        "proof_sha256": proof_digest,
        "operand_rewrite_site_ids": _site_ids(
            proof, "operand_rewrite_sites"
        ),
        "operand_mutation_site_ids": _site_ids(
            proof, "operand_mutation_sites"
        ),
        "code_emission_site_ids": _site_ids(proof, "code_emission_sites"),
    }
    candidate["backend_reader"] = reader
    return candidate


def _validate_and_bind_exact_artifacts(
    members: dict[str, bytes], compiler_sha256: str
) -> tuple[str, str]:
    """Validate exact proof/hook bijection and assemble its candidate gate."""

    from .backend_instrumentation_proof import (
        proof_sha256,
        validate_proof_shape,
    )
    from .backend_runtime_hook_manifest import (
        runtime_hook_manifest_sha256,
        validate_runtime_hook_manifest,
    )
    from .struct_map import validate_pcode_instrumentation_capability

    proof = _load_json(members[_PROOF_MEMBER], _PROOF_MEMBER)
    hooks = _load_json(members[_HOOK_MEMBER], _HOOK_MEMBER)
    if not isinstance(proof, dict):
        raise LifetimeBundleError("candidate proof must be an object")
    if proof.get("compiler_executable_sha256") != compiler_sha256:
        raise LifetimeBundleError("candidate proof compiler SHA-256 differs")
    proof_errors = validate_proof_shape(proof)
    if proof_errors:
        raise LifetimeBundleError(
            "candidate proof is invalid: " + "; ".join(proof_errors)
        )
    manifest_errors = validate_runtime_hook_manifest(hooks, proof)
    if manifest_errors:
        raise LifetimeBundleError(
            "runtime hook manifest is invalid: "
            + "; ".join(manifest_errors)
        )

    proof_digest = proof_sha256(proof)
    hook_digest = runtime_hook_manifest_sha256(hooks)
    candidate_source = _load_json(
        members[_CANDIDATE_MEMBER], _CANDIDATE_MEMBER
    )
    candidate = _bind_candidate_table(candidate_source, proof, proof_digest)
    candidate_errors = validate_pcode_instrumentation_capability(
        candidate, proof=proof
    )
    if candidate_errors:
        raise LifetimeBundleError(
            "candidate proof registry/gate is invalid: "
            + "; ".join(candidate_errors)
        )
    members[_HOOK_MEMBER] = _canonical_json(hooks)
    members[_PROOF_MEMBER] = _canonical_json(proof)
    members[_CANDIDATE_MEMBER] = _canonical_json(candidate)
    return proof_digest, hook_digest


@dataclass(frozen=True, slots=True)
class PublishedLifetimeBundle:
    """One resolver-validated immutable generation."""

    generation_name: str
    manifest_sha256: str
    members: tuple[tuple[str, bytes], ...]
    output_root: Path
    compiler_sha256: str

    @property
    def generation_dir(self) -> Path:
        return self.output_root / "generations" / self.generation_name

    def path(self, name: str) -> Path:
        expected = dict(self.members).get(name)
        if expected is None:
            raise LifetimeBundleError(f"unknown lifetime bundle member: {name}")
        path = self.generation_dir / name
        _validate_regular_file(path, f"lifetime bundle member {name}")
        if path.read_bytes() != expected:
            raise LifetimeBundleError(f"member changed after resolution: {name}")
        return path

    def canonical_files(self) -> dict[str, bytes]:
        return dict(self.members)


@dataclass(frozen=True, slots=True)
class GeneratedLifetimeBundle:
    """Generated canonical members and their proof binding digests."""

    members: tuple[tuple[str, bytes], ...]
    proof_sha256: str = ""
    hook_manifest_sha256: str = ""
    audit_summary: dict[str, Any] = field(default_factory=dict)
    publication: PublishedLifetimeBundle | None = None

    def canonical_files(self) -> dict[str, bytes]:
        return dict(self.members)


_FAMILY_RANK = {
    "allocation_sites": 0,
    "free_sites": 1,
    "operand_rewrite_sites": 2,
    "operand_mutation_sites": 3,
    "code_emission_sites": 4,
}


def _capture_source(
    name: str,
    source_kind: str,
    phase: str,
    *,
    operand_index: int | None = None,
    register: str | None = None,
    stack_argument_index: int | None = None,
    byte_offset: int = 0,
    byte_width: int = 4,
) -> dict[str, object]:
    return {
        "name": name,
        "source_kind": source_kind,
        "phase": phase,
        "operand_index": operand_index,
        "register": register,
        "stack_argument_index": stack_argument_index,
        "byte_offset": byte_offset,
        "byte_width": byte_width,
    }


def _operation_contract(
    operation: str,
) -> tuple[str, list[dict[str, object]]]:
    if operation == "allocation":
        return (
            "same-thread-call-return",
            [
                _capture_source(
                    "allocation_length",
                    "stack-argument",
                    "before",
                    stack_argument_index=0,
                ),
                _capture_source(
                    "allocated_pointer",
                    "return-register",
                    "return",
                    register="eax",
                ),
            ],
        )
    if operation in {"cache-acquire", "cache-release"}:
        return (
            "same-thread-instruction",
            [
                _capture_source(
                    "entity_pointer",
                    "effective-address",
                    "before",
                    operand_index=0,
                    byte_offset=-0x2A,
                )
            ],
        )
    if operation in {"recycle", "rewind", "release"}:
        return (
            "same-thread-call-return",
            [
                _capture_source(
                    "entity_pointer",
                    "stack-argument",
                    "before",
                    stack_argument_index=0,
                )
            ],
        )
    if operation == "operand-rewrite":
        return (
            "same-thread-instruction",
            [
                _capture_source(
                    "operand_address",
                    "effective-address",
                    "before",
                    operand_index=0,
                    byte_offset=-2,
                    byte_width=12,
                )
            ],
        )
    if operation in {
        "create",
        "delete",
        "reorder",
        "clone",
        "replace",
        "spill",
        "coalesce",
    }:
        sources: list[dict[str, object]] = []
        if operation != "create":
            sources.extend(
                (
                    _capture_source(
                        "input_pointer", "x86-register", "before", register="eax"
                    ),
                    _capture_source(
                        "input_length", "x86-register", "before", register="ecx"
                    ),
                )
            )
        if operation != "delete":
            sources.extend(
                (
                    _capture_source(
                        "output_pointer", "x86-register", "after", register="eax"
                    ),
                    _capture_source(
                        "output_length", "x86-register", "after", register="ecx"
                    ),
                )
            )
        return "same-thread-function-entry-exit", sources
    if operation == "encode":
        return (
            "same-thread-call-return",
            [
                _capture_source(
                    "pcode_pointer",
                    "stack-argument",
                    "before",
                    stack_argument_index=0,
                ),
                _capture_source(
                    "encoded_word",
                    "return-register",
                    "return",
                    register="eax",
                ),
            ],
        )
    if operation == "final-buffer-emission":
        return (
            "same-thread-instruction",
            [
                _capture_source(
                    "buffer_pointer", "x86-register", "before", register="eax"
                ),
                _capture_source(
                    "buffer_length", "x86-register", "before", register="ecx"
                ),
            ],
        )
    raise LifetimeBundleError(f"runtime hook operation is unproved: {operation}")


def _breakpoint(instruction: object, phase: str) -> dict[str, object]:
    address = getattr(instruction, "address", None)
    raw_hex = getattr(instruction, "bytes_hex", None)
    size = getattr(instruction, "size", None)
    if (
        type(address) is not int
        or type(raw_hex) is not str
        or type(size) is not int
        or size <= 0
    ):
        raise LifetimeBundleError("runtime hook instruction evidence is malformed")
    try:
        raw = bytes.fromhex(raw_hex)
    except ValueError as exc:
        raise LifetimeBundleError(
            f"runtime hook instruction bytes are invalid at {address:#x}"
        ) from exc
    if len(raw) != size:
        raise LifetimeBundleError(
            f"runtime hook instruction size differs at {address:#x}"
        )
    return {
        "phase": phase,
        "address": address,
        "instruction_bytes": raw_hex,
        "instruction_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _mutation_operation(address: int, classification: str) -> str | None:
    lowered = classification.lower()
    for operation in (
        "create",
        "delete",
        "reorder",
        "clone",
        "replace",
        "spill",
        "coalesce",
    ):
        if operation in lowered:
            return operation
    return {
        0x004CE20B: "reorder",
        0x00530BA6: "coalesce",
        0x00531254: "coalesce",
        0x005311BD: "delete",
        0x004A32E0: "replace",
        0x00531800: "spill",
        0x0049D270: "clone",
    }.get(address)


def derive_exact_lifetime_proof_plan(
    cfg: object, inventory: object
) -> ExactLifetimeProofPlan:
    """Derive only instruction-bound hook plans; retain every gap explicitly."""

    instructions = tuple(getattr(cfg, "instructions", ()))
    by_address = {getattr(row, "address", None): row for row in instructions}
    if len(by_address) != len(instructions) or None in by_address:
        raise LifetimeBundleError("runtime hook CFG instruction inventory differs")
    function_entries = tuple(
        sorted(
            getattr(row, "address", -1)
            for row in getattr(cfg, "function_entries", ())
            if getattr(row, "is_function", False)
        )
    )
    unresolved: list[str] = []
    proof_rows: dict[str, list[dict[str, object]]] = {
        family: [] for family in _FAMILY_RANK
    }
    hook_rows: list[dict[str, object]] = []

    def instruction_pair(
        address: int, pairing: str
    ) -> list[dict[str, object]] | None:
        before = by_address.get(address)
        if before is None:
            unresolved.append(f"hook-instruction-missing:{address:#x}")
            return None
        if pairing == "same-thread-function-entry-exit":
            if address not in function_entries:
                unresolved.append(f"mutation-function-entry-unproved:{address:#x}")
                return None
            next_entries = [row for row in function_entries if row > address]
            upper = min(next_entries) if next_entries else 1 << 63
            exits = [
                row
                for row in instructions
                if address <= row.address < upper
                and str(getattr(row, "mnemonic", "")).lower().startswith("ret")
            ]
            if len(exits) != 1:
                unresolved.append(f"mutation-function-exit-unproved:{address:#x}")
                return None
            return [_breakpoint(before, "before"), _breakpoint(exits[0], "after")]
        size = getattr(before, "size", 0)
        after = by_address.get(address + size)
        if after is None:
            unresolved.append(f"hook-return-instruction-missing:{address:#x}")
            return None
        phase = "return" if pairing == "same-thread-call-return" else "after"
        return [_breakpoint(before, "before"), _breakpoint(after, phase)]

    def add_site(
        family: str,
        address: int,
        site_id: str,
        operation: str,
        stage: str,
        *,
        entity_kind: str | None = None,
    ) -> None:
        pairing, sources = _operation_contract(operation)
        breakpoints = instruction_pair(address, pairing)
        if breakpoints is None:
            return
        proof_row: dict[str, object] = {
            "site_id": site_id,
            "address": address,
            "compiler_stage": stage,
        }
        if entity_kind is not None:
            proof_row["entity_kind"] = entity_kind
        proof_rows[family].append(proof_row)
        hook_rows.append(
            {
                "site_id": site_id,
                "family": family,
                "proof_address": address,
                "operation": operation,
                "breakpoints": breakpoints,
                "capture_sources": sources,
                "pairing": pairing,
                "hit_policy": "probe-union",
            }
        )

    allocations = tuple(getattr(inventory, "allocations", ()))
    reachable_allocations = [
        row
        for row in allocations
        if getattr(row, "ownership", None) == "reachable-owned-call"
    ]
    for row in reachable_allocations:
        classification = str(getattr(row, "classification", ""))
        if classification.startswith("pcode"):
            entity = "pcode"
        elif classification.startswith("objobject"):
            entity = "objobject"
        else:
            unresolved.append(f"allocation-entity-unproved:{row.address:#x}")
            continue
        add_site(
            "allocation_sites",
            row.address,
            f"{entity}-alloc-{row.address:08x}",
            "allocation",
            "backend-lowering",
            entity_kind=entity,
        )

    reuse_writes: dict[int, list[object]] = {}
    for field_write in getattr(inventory, "field_writes", ()):
        reuse_writes.setdefault(getattr(field_write, "address", -1), []).append(
            field_write
        )
    for row in getattr(inventory, "reuses", ()):
        matches = [
            field_write
            for field_write in reuse_writes.get(row.address, ())
            if getattr(field_write, "object_type", None) == "objobject"
            and getattr(field_write, "field", None) == "cache-reuse-flag"
            and getattr(field_write, "operation", None) == "mov"
            and getattr(field_write, "width", None) == 4
        ]
        values = (
            getattr(getattr(matches[0], "value", None), "values", None)
            if len(matches) == 1
            and getattr(getattr(matches[0], "value", None), "kind", None)
            == "exact"
            else None
        )
        if values == frozenset({0}):
            family = "free_sites"
            operation = "cache-release"
        elif values == frozenset({1}):
            family = "allocation_sites"
            operation = "cache-acquire"
        else:
            unresolved.append(
                f"cache-reuse-transition-unproved:{row.address:#x}"
            )
            continue
        add_site(
            family,
            row.address,
            f"objobject-{operation}-{row.address:08x}",
            operation,
            "backend-object-cache",
            entity_kind="objobject",
        )
    for row in getattr(inventory, "releases", ()):
        affected = set(getattr(row, "affected_arenas", ()))
        entities = {
            (
                "pcode"
                if str(getattr(allocation, "classification", "")).startswith(
                    "pcode"
                )
                else "objobject"
            )
            for allocation in reachable_allocations
            if getattr(allocation, "allocator", None) in affected
            and str(getattr(allocation, "classification", "")).startswith(
                ("pcode", "objobject")
            )
        }
        if len(entities) != 1:
            unresolved.append(f"release-entity-domain-unproved:{row.address:#x}")
            continue
        operation = (
            "rewind"
            if "rewind" in str(getattr(row, "classification", "")).lower()
            else "release"
        )
        entity = next(iter(entities))
        add_site(
            "free_sites",
            row.address,
            f"{entity}-{operation}-{row.address:08x}",
            operation,
            "backend-finalize",
            entity_kind=entity,
        )

    rewrite_addresses = {
        getattr(row, "address", -1)
        for row in getattr(inventory, "rewrite_sites", ())
    }
    for row in getattr(inventory, "rewrite_sites", ()):
        add_site(
            "operand_rewrite_sites",
            row.address,
            f"pcode-rewrite-{row.address:08x}",
            "operand-rewrite",
            "colorgraph",
        )
    for row in getattr(inventory, "mutation_sites", ()):
        if row.address in rewrite_addresses:
            continue
        operation = _mutation_operation(
            row.address, str(getattr(row, "classification", ""))
        )
        if operation is None:
            unresolved.append(f"mutation-operation-unproved:{row.address:#x}")
            continue
        add_site(
            "operand_mutation_sites",
            row.address,
            f"pcode-{operation}-{row.address:08x}",
            operation,
            "optimizer",
        )
    for row in getattr(inventory, "emission_sites", ()):
        classification = str(getattr(row, "classification", ""))
        if classification == "per-pcode-encoder-call":
            operation = "encode"
        elif classification == "encoder-result-buffer-write":
            operation = "final-buffer-emission"
        else:
            continue
        add_site(
            "code_emission_sites",
            row.address,
            f"pcode-{operation}-{row.address:08x}",
            operation,
            "backend-finalize",
        )

    addresses = [row["proof_address"] for row in hook_rows]
    if len(addresses) != len(set(addresses)):
        unresolved.append("runtime-hook-site-addresses-not-unique")
    for family, rows in proof_rows.items():
        if not rows:
            unresolved.append(f"runtime-hook-family-empty:{family}")
        rows.sort(key=lambda row: (int(row["address"]), str(row["site_id"])))
    hook_rows.sort(
        key=lambda row: (
            _FAMILY_RANK[str(row["family"])],
            int(row["proof_address"]),
            str(row["site_id"]),
        )
    )
    return ExactLifetimeProofPlan(
        allocation_sites=tuple(proof_rows["allocation_sites"]),
        free_sites=tuple(proof_rows["free_sites"]),
        operand_rewrite_sites=tuple(proof_rows["operand_rewrite_sites"]),
        operand_mutation_sites=tuple(proof_rows["operand_mutation_sites"]),
        code_emission_sites=tuple(proof_rows["code_emission_sites"]),
        hook_sites=tuple(hook_rows),
        unresolved=tuple(sorted(set(unresolved))),
    )


def _source_field(source: object, name: str, default: object = None) -> object:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _structured_unresolved(inputs: ExactLifetimeBundleInputs) -> tuple[str, ...]:
    findings: list[str] = list(inputs.proof_plan.unresolved)
    for label, source in (
        ("task5-values", inputs.value_analysis),
        ("task6-lifetime-sites", inputs.lifetime_site_inventory),
        ("task7-opcode-layouts", inputs.opcode_layout_inventory),
    ):
        if _source_field(source, "proof_ready") is not True:
            findings.append(f"{label}:proof-not-ready")
        unresolved = _source_field(source, "unresolved", ())
        if unresolved:
            findings.append(f"{label}:unresolved")
        bound_compiler = _source_field(source, "compiler_sha256")
        if bound_compiler is not None and bound_compiler != inputs.compiler_sha256:
            findings.append(f"{label}:compiler-binding")
    tables = inputs.opcode_tables
    if set(tables) != {"opcode_table", "operand_rules"}:
        findings.append("task7-opcode-tables:fields-differ")
    return tuple(sorted(set(findings)))


def _source_summary(source: object) -> dict[str, object]:
    unresolved = _source_field(source, "unresolved", ())
    high_water = _source_field(source, "high_water_marks", ())
    return {
        "proof_ready": _source_field(source, "proof_ready") is True,
        "unresolved_count": len(unresolved) if isinstance(unresolved, (list, tuple)) else 1,
        "high_water_marks": _json_value(high_water, path="high_water_marks"),
    }


def _proof_plan_payload(
    plan: ExactLifetimeProofPlan,
) -> dict[str, list[object]]:
    return {
        "allocation_sites": [
            _json_value(row, path="allocation_sites") for row in plan.allocation_sites
        ],
        "free_sites": [
            _json_value(row, path="free_sites") for row in plan.free_sites
        ],
        "operand_rewrite_sites": [
            _json_value(row, path="operand_rewrite_sites")
            for row in plan.operand_rewrite_sites
        ],
        "operand_mutation_sites": [
            _json_value(row, path="operand_mutation_sites")
            for row in plan.operand_mutation_sites
        ],
        "code_emission_sites": [
            _json_value(row, path="code_emission_sites")
            for row in plan.code_emission_sites
        ],
    }


def _report_payload(
    members: Mapping[str, bytes],
    *,
    compiler_sha256: str,
    proof_sha256: str,
    hook_manifest_sha256: str,
) -> bytes:
    lines = [
        "# Exact GC/1.2.5n Retail PCode Lifetime Proof",
        "",
        f"- Compiler SHA-256: `{compiler_sha256}`",
        f"- Runtime-hook manifest SHA-256: `{hook_manifest_sha256}`",
        f"- Lifetime proof SHA-256: `{proof_sha256}`",
        "- Proof ready: `true`",
        "",
        "## Canonical artifact digests",
        "",
    ]
    lines.extend(
        f"- `{name}`: `{hashlib.sha256(members[name]).hexdigest()}`"
        for name in CANONICAL_MEMBERS[:-1]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_exact_lifetime_bundle(
    inputs: ExactLifetimeBundleInputs,
    out_dir: Path,
    *,
    failure_injector: Callable[[str], None] | None = None,
) -> GeneratedLifetimeBundle:
    """Construct the exact nine members in dependency order, then publish."""

    from .backend_instrumentation_proof import proof_sha256, validate_proof_shape
    from .backend_runtime_hook_manifest import (
        MANIFEST_SCHEMA,
        runtime_hook_manifest_sha256,
        validate_runtime_hook_manifest,
    )
    from .struct_map import validate_pcode_instrumentation_capability

    if not isinstance(inputs, ExactLifetimeBundleInputs):
        raise LifetimeBundleError("exact lifetime inputs have the wrong type")
    if not _HEX_64.fullmatch(inputs.compiler_sha256):
        raise LifetimeBundleError("compiler SHA-256 is malformed")

    lifetime_payload = _json_value(
        inputs.lifetime_site_inventory, path="lifetime_site_inventory"
    )
    opcode_payload = _json_value(
        inputs.opcode_layout_inventory, path="opcode_layout_inventory"
    )
    first_four = {
        "raw-pe-cfg.v1.jsonl": inputs.raw_cfg_jsonl,
        "raw-ghidra-crosscheck.v1.json": inputs.ghidra_crosscheck_json,
        "backend-lifetime-sites.candidate.v1.json": _canonical_json(
            lifetime_payload
        ),
        "opcode-layouts.candidate.v1.json": _canonical_json(opcode_payload),
    }
    unresolved = list(_structured_unresolved(inputs))
    preliminary = {
        **first_four,
        "backend-lifetime-audit.v1.json": _canonical_json(
            {
                "schema_version": "mwcc-retro-backend-lifetime-audit.v1",
                "compiler_sha256": inputs.compiler_sha256,
                "proof_ready": not unresolved,
                "unresolved": unresolved,
                "sources": {
                    "task5_values": _source_summary(inputs.value_analysis),
                    "task6_lifetime_sites": _source_summary(
                        inputs.lifetime_site_inventory
                    ),
                    "task7_opcode_layouts": _source_summary(
                        inputs.opcode_layout_inventory
                    ),
                },
                "backend_map_candidates": _json_value(
                    inputs.backend_map_candidates,
                    path="backend_map_candidates",
                ),
                "input_artifact_sha256": {
                    name: hashlib.sha256(payload).hexdigest()
                    for name, payload in first_four.items()
                },
            }
        ),
    }
    raw_findings = _collect_unresolved(preliminary, inputs.compiler_sha256)
    if raw_findings:
        unresolved = sorted(set((*unresolved, *raw_findings)))
        preliminary["backend-lifetime-audit.v1.json"] = _canonical_json(
            {
                **_load_json(
                    preliminary["backend-lifetime-audit.v1.json"],
                    "backend-lifetime-audit.v1.json",
                ),
                "proof_ready": False,
                "unresolved": unresolved,
            }
        )
    if unresolved:
        return generate_lifetime_bundle(
            preliminary,
            out_dir,
            proof_ready=False,
            compiler_sha256=inputs.compiler_sha256,
            failure_injector=failure_injector,
        )

    plan = _proof_plan_payload(inputs.proof_plan)
    hooks = {
        "schema_version": MANIFEST_SCHEMA,
        "compiler_executable_sha256": inputs.compiler_sha256,
        "proof_id": "gc-1.2.5n-backend-entity-allocation-trace.v1",
        "sites": [
            _json_value(row, path="hook_sites")
            for row in inputs.proof_plan.hook_sites
        ],
    }
    hook_digest = runtime_hook_manifest_sha256(hooks)
    proof = {
        "schema_version": "mwcc-retro-lifetime-proof.v1",
        "proof_id": "gc-1.2.5n-backend-entity-allocation-trace.v1",
        "compiler_executable_sha256": inputs.compiler_sha256,
        "runtime_hook_manifest_sha256": hook_digest,
        "mode": "allocation-generation",
        **plan,
        "operand_rules": _json_value(
            inputs.opcode_tables["operand_rules"], path="operand_rules"
        ),
        "opcode_table": _json_value(
            inputs.opcode_tables["opcode_table"], path="opcode_table"
        ),
        "initialization_address": 0x00401000,
        "proof_basis": "exhaustive-static-callgraph-and-disassembly",
    }
    proof_errors = validate_proof_shape(proof)
    if proof_errors:
        raise LifetimeBundleError(
            "constructed lifetime proof is invalid: " + "; ".join(proof_errors)
        )
    hook_errors = validate_runtime_hook_manifest(hooks, proof)
    if hook_errors:
        raise LifetimeBundleError(
            "constructed runtime hook manifest is invalid: "
            + "; ".join(hook_errors)
        )
    proof_digest = proof_sha256(proof)
    candidate = _bind_candidate_table(
        _json_value(inputs.candidate_table, path="candidate_table"),
        proof,
        proof_digest,
    )
    candidate_errors = validate_pcode_instrumentation_capability(
        candidate, proof=proof
    )
    if candidate_errors:
        raise LifetimeBundleError(
            "constructed candidate proof registry/gate is invalid: "
            + "; ".join(candidate_errors)
        )

    members = {
        **preliminary,
        _HOOK_MEMBER: _canonical_json(hooks),
        _PROOF_MEMBER: _canonical_json(proof),
        _CANDIDATE_MEMBER: _canonical_json(candidate),
    }
    members["REPORT.md"] = _report_payload(
        members,
        compiler_sha256=inputs.compiler_sha256,
        proof_sha256=proof_digest,
        hook_manifest_sha256=hook_digest,
    )
    return generate_lifetime_bundle(
        members,
        out_dir,
        proof_ready=True,
        compiler_sha256=inputs.compiler_sha256,
        failure_injector=failure_injector,
    )


def generate_lifetime_bundle(
    inputs: Mapping[str, bytes],
    out_dir: Path,
    *,
    proof_ready: bool = True,
    compiler_sha256: str = "",
    failure_injector: Callable[[str], None] | None = None,
) -> GeneratedLifetimeBundle:
    """Generate and, when ready, atomically publish the canonical bundle.

    Exact callers provide all nine members.  A ready generation validates the
    proof, hook, registry, and gate bindings before making CURRENT visible;
    missing members never acquire placeholders or compatibility attestations.
    """

    if not _HEX_64.fullmatch(compiler_sha256):
        raise LifetimeBundleError("compiler SHA-256 is malformed")
    if not isinstance(inputs, Mapping):
        raise LifetimeBundleError("lifetime bundle inputs must be a mapping")
    unexpected = set(inputs) - set(CANONICAL_MEMBERS)
    if unexpected:
        raise LifetimeBundleError(
            f"unexpected lifetime bundle inputs: {sorted(unexpected)!r}"
        )
    if any(not isinstance(payload, bytes) for payload in inputs.values()):
        raise LifetimeBundleError("lifetime bundle inputs must be bytes")

    unresolved = _collect_unresolved(inputs, compiler_sha256)
    ready = proof_ready and not unresolved
    if ready and set(inputs) != set(CANONICAL_MEMBERS):
        missing = sorted(set(CANONICAL_MEMBERS) - set(inputs))
        raise LifetimeBundleError(
            f"missing exact lifetime bundle members: {missing!r}"
        )
    members: dict[str, bytes] = {}
    for name in CANONICAL_MEMBERS:
        if name == _PROOF_MEMBER and not ready:
            continue
        if name in inputs:
            members[name] = _canonicalize_member(name, inputs[name])

    proof_digest = ""
    hook_digest = ""
    binding_validated = False
    if ready:
        proof_digest, hook_digest = _validate_and_bind_exact_artifacts(
            members, compiler_sha256
        )
        binding_validated = True

    publication = None
    if ready:
        publication = publish_lifetime_bundle(
            out_dir,
            members,
            compiler_sha256=compiler_sha256,
            failure_injector=failure_injector,
        )

    ordered = tuple(
        (name, members[name]) for name in CANONICAL_MEMBERS if name in members
    )
    return GeneratedLifetimeBundle(
        members=ordered,
        proof_sha256=proof_digest,
        hook_manifest_sha256=hook_digest,
        audit_summary={
            "binding_validated": binding_validated,
            "compiler_sha256": compiler_sha256,
            "hook_manifest_sha256": hook_digest,
            "proof_ready": ready,
            "proof_sha256": proof_digest,
            "unresolved_inputs": list(unresolved),
        },
        publication=publication,
    )


def _validate_regular_file(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise LifetimeBundleError(f"{label} is missing") from exc
    if not stat.S_ISREG(mode) or path.is_symlink():
        raise LifetimeBundleError(f"{label} must be a regular file")


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
) -> bytes:
    return _canonical_json(
        {
            "schema_version": BUNDLE_SCHEMA,
            "compiler_sha256": compiler_sha256,
            "members": [
                {
                    "name": name,
                    "size": len(members[name]),
                    "sha256": hashlib.sha256(members[name]).hexdigest(),
                }
                for name in CANONICAL_MEMBERS
            ],
        }
    )


def publish_lifetime_bundle(
    out_dir: Path,
    members: Mapping[str, bytes],
    *,
    compiler_sha256: str,
    schema: str = BUNDLE_SCHEMA,
    failure_injector: Callable[[str], None] | None = None,
) -> PublishedLifetimeBundle:
    """Publish exactly nine members through one atomic pointer switch."""

    output_root = Path(out_dir)
    if schema != BUNDLE_SCHEMA:
        raise LifetimeBundleError("lifetime bundle schema differs")
    if not _HEX_64.fullmatch(compiler_sha256):
        raise LifetimeBundleError("compiler SHA-256 is malformed")
    if set(members) != set(CANONICAL_MEMBERS) or any(
        not isinstance(payload, bytes) for payload in members.values()
    ):
        raise LifetimeBundleError("lifetime bundle member set differs")
    if output_root.exists() and (
        output_root.is_symlink() or not output_root.is_dir()
    ):
        raise LifetimeBundleError("output root must be a regular directory")
    output_root.mkdir(parents=True, exist_ok=True)
    generations = output_root / "generations"
    if generations.exists() and (
        generations.is_symlink() or not generations.is_dir()
    ):
        raise LifetimeBundleError("generations must be a regular directory")
    generations.mkdir(exist_ok=True)

    manifest_payload = _manifest_payload(members, compiler_sha256)
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    generation_name = f"gen-{manifest_sha256}"
    final_dir = generations / generation_name
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=generations))
    renamed = False
    try:
        for name in CANONICAL_MEMBERS:
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
            if final_dir.is_symlink() or not final_dir.is_dir():
                raise LifetimeBundleError(
                    "immutable generation must be a regular directory"
                )
            expected_names = set(CANONICAL_MEMBERS) | {"MANIFEST.json"}
            if {path.name for path in final_dir.iterdir()} != expected_names:
                raise LifetimeBundleError("immutable generation members differ")
            if (final_dir / "MANIFEST.json").read_bytes() != manifest_payload:
                raise LifetimeBundleError("immutable generation manifest differs")
            for name in CANONICAL_MEMBERS:
                _validate_regular_file(
                    final_dir / name, f"immutable generation member {name}"
                )
                if (final_dir / name).read_bytes() != members[name]:
                    raise LifetimeBundleError(
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
                "schema_version": CURRENT_SCHEMA,
                "generation": generation_name,
                "manifest_sha256": manifest_sha256,
            }
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".CURRENT.", suffix=".tmp", dir=output_root
        )
        os.close(descriptor)
        pointer_temp = Path(temporary_name)
        pointer_temp.unlink()
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
        if staging.exists():
            shutil.rmtree(staging)
        # A successfully renamed generation is immutable and may remain as an
        # orphan after failure.  CURRENT never exposes it until fully written.
        _ = renamed
    return resolve_lifetime_bundle(output_root)


def resolve_lifetime_bundle(out_dir: Path) -> PublishedLifetimeBundle:
    """Resolve CURRENT and validate its manifest and all nine members."""

    output_root = Path(out_dir)
    current_path = output_root / "CURRENT"
    _validate_regular_file(current_path, "CURRENT pointer")
    current_bytes = current_path.read_bytes()
    pointer = _load_json(current_bytes, "CURRENT pointer")
    if not isinstance(pointer, dict) or set(pointer) != {
        "schema_version",
        "generation",
        "manifest_sha256",
    }:
        raise LifetimeBundleError("CURRENT pointer fields differ")
    if current_bytes != _canonical_json(pointer):
        raise LifetimeBundleError("CURRENT pointer is not canonical JSON")
    if pointer["schema_version"] != CURRENT_SCHEMA:
        raise LifetimeBundleError("CURRENT pointer schema differs")
    generation_name = pointer["generation"]
    if not isinstance(generation_name, str) or not _GENERATION_NAME.fullmatch(
        generation_name
    ):
        raise LifetimeBundleError("CURRENT generation name is invalid")
    manifest_sha256 = pointer["manifest_sha256"]
    if not isinstance(manifest_sha256, str) or not _HEX_64.fullmatch(
        manifest_sha256
    ):
        raise LifetimeBundleError("CURRENT manifest SHA-256 is malformed")
    if generation_name != f"gen-{manifest_sha256}":
        raise LifetimeBundleError(
            "CURRENT generation name differs from manifest hash"
        )

    generation_dir = output_root / "generations" / generation_name
    if generation_dir.is_symlink() or not generation_dir.is_dir():
        raise LifetimeBundleError(
            "CURRENT generation must be a regular directory"
        )
    expected_names = set(CANONICAL_MEMBERS) | {"MANIFEST.json"}
    if {path.name for path in generation_dir.iterdir()} != expected_names:
        raise LifetimeBundleError("lifetime generation member set differs")
    manifest_path = generation_dir / "MANIFEST.json"
    _validate_regular_file(manifest_path, "lifetime bundle manifest")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
        raise LifetimeBundleError("manifest hash differs from CURRENT")
    manifest = _load_json(manifest_bytes, "lifetime bundle manifest")
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "compiler_sha256",
        "members",
    }:
        raise LifetimeBundleError("lifetime bundle manifest fields differ")
    if manifest_bytes != _canonical_json(manifest):
        raise LifetimeBundleError("lifetime bundle manifest is not canonical JSON")
    if manifest["schema_version"] != BUNDLE_SCHEMA:
        raise LifetimeBundleError("lifetime bundle manifest schema differs")
    compiler_sha256 = manifest["compiler_sha256"]
    if not isinstance(compiler_sha256, str) or not _HEX_64.fullmatch(
        compiler_sha256
    ):
        raise LifetimeBundleError("manifest compiler SHA-256 is malformed")
    rows = manifest["members"]
    if not isinstance(rows, list) or len(rows) != len(CANONICAL_MEMBERS):
        raise LifetimeBundleError("lifetime bundle manifest member set differs")

    members: list[tuple[str, bytes]] = []
    for index, name in enumerate(CANONICAL_MEMBERS):
        row = rows[index]
        if not isinstance(row, dict) or set(row) != {"name", "size", "sha256"}:
            raise LifetimeBundleError("lifetime bundle member metadata differs")
        if row["name"] != name:
            raise LifetimeBundleError(
                "lifetime bundle manifest members are not canonically ordered"
            )
        size = row["size"]
        digest = row["sha256"]
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or not _HEX_64.fullmatch(digest)
        ):
            raise LifetimeBundleError("lifetime bundle member metadata is invalid")
        member_path = generation_dir / name
        _validate_regular_file(member_path, f"lifetime bundle member {name}")
        payload = member_path.read_bytes()
        if len(payload) != size:
            raise LifetimeBundleError(f"member size differs: {name}")
        if hashlib.sha256(payload).hexdigest() != digest:
            raise LifetimeBundleError(f"member hash differs: {name}")
        members.append((name, payload))

    return PublishedLifetimeBundle(
        generation_name=generation_name,
        manifest_sha256=manifest_sha256,
        members=tuple(members),
        output_root=output_root,
        compiler_sha256=compiler_sha256,
    )


__all__ = [
    "BUNDLE_SCHEMA",
    "CANONICAL_MEMBERS",
    "CURRENT_SCHEMA",
    "ExactLifetimeBundleInputs",
    "ExactLifetimeProofPlan",
    "GeneratedLifetimeBundle",
    "LifetimeBundleError",
    "PublishedLifetimeBundle",
    "derive_exact_lifetime_proof_plan",
    "generate_lifetime_bundle",
    "generate_exact_lifetime_bundle",
    "publish_lifetime_bundle",
    "resolve_lifetime_bundle",
]
