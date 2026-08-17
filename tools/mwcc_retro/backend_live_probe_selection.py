"""Bounded, evidence-only selection for the four retail live probes.

Source/build metadata is used only to seed a deterministic preflight corpus.
Every category claimed by the final selection is reconstructed from a current,
validated map/PCode probe pair and bound by the exact summary digest.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rfc8785

SCHEMA = "mwcc-retro-live-features.v1"
SELECTION_SCHEMA = "mwcc-retro-live-probe-selection.v1"
UNION_SCHEMA = "mwcc-retro-live-probe-union.v1"
COMPLEX_SOURCE = "src/melee/mn/mndiagram.c"
COMPLEX_FUNCTION = "mnDiagram_DrawFighterHeaders"
_CATEGORIES = (
    "complex-control",
    "named-local",
    "address-taken-multi-virtual",
    "fpr-and-spill",
)


class IncompleteSelectionError(ValueError):
    """The bounded observed corpus does not prove all four categories."""


@dataclass(frozen=True, slots=True)
class PreflightLimits:
    """Exclusive high-water bounds for deterministic preflight work."""

    max_candidates: int
    max_compile_attempts: int
    max_outputs: int

    def __post_init__(self) -> None:
        for name in (
            "max_candidates",
            "max_compile_attempts",
            "max_outputs",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_candidates": self.max_candidates,
            "max_compile_attempts": self.max_compile_attempts,
            "max_outputs": self.max_outputs,
        }


# Retained as small public value objects for callers that prefer typed rows.
@dataclass(frozen=True, slots=True)
class LiveProbeCandidate:
    source: str
    function: str
    category: str
    why: str


@dataclass(frozen=True, slots=True)
class LiveProbeSelection:
    candidates: tuple[LiveProbeCandidate, ...]
    candidate_table_sha256: str
    feature_summary_sha256s: tuple[str, ...]


def _json_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    return value


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return rfc8785.dumps(dict(payload))


def _digest_candidate(candidate_table: Mapping[str, object] | Path) -> str:
    if isinstance(candidate_table, Path):
        raw = candidate_table.read_bytes()
    elif isinstance(candidate_table, Mapping):
        raw = _canonical_bytes(candidate_table)
    else:
        raise ValueError("candidate table must be a mapping or path")
    return hashlib.sha256(raw).hexdigest()


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _int_from_report(value: object) -> int | None:
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value, 0)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def discover_live_probe_candidates(
    melee_root: Path,
    limits: PreflightLimits | None = None,
    *,
    max_candidates: int | None = None,
    max_compiles: int | None = None,
) -> tuple[dict[str, object], ...]:
    """Return a deterministic numeric corpus of real, fully matched functions.

    The bound is exclusive so shell-side counters can fail exactly when they
    reach the configured high-water value.  Candidate seed tags are hints only;
    no returned row claims that a live feature has been observed.
    """

    root = Path(melee_root).resolve()
    if limits is None:
        limits = PreflightLimits(
            max_candidates=max_candidates or 256,
            max_compile_attempts=max_compiles or 512,
            max_outputs=max_candidates or 256,
        )
    elif max_candidates is not None or max_compiles is not None:
        raise ValueError("pass PreflightLimits or legacy caps, not both")

    fixed: dict[str, object] = {
        "ordinal": 0,
        "address": 0,
        "size": 0,
        "source": COMPLEX_SOURCE,
        "function": COMPLEX_FUNCTION,
        "seed_tags": ["required-complex-control"],
        "claims_observed_features": False,
    }
    report_path = root / "build" / "GALE01" / "report.json"
    if not report_path.is_file():
        return (fixed,)
    report = _json_object(report_path, "GALE01 report")
    units = report.get("units")
    if type(units) is not list:
        raise ValueError("GALE01 report units must be a list")

    numeric: list[tuple[int, str, str, int]] = []
    for unit in units:
        if type(unit) is not dict:
            continue
        metadata = unit.get("metadata")
        source = metadata.get("source_path") if type(metadata) is dict else None
        if type(source) is not str or not source:
            continue
        if not (root / source).is_file():
            continue
        functions = unit.get("functions")
        if type(functions) is not list:
            continue
        for function in functions:
            if type(function) is not dict:
                continue
            if function.get("fuzzy_match_percent") != 100.0:
                continue
            name = function.get("name")
            fn_meta = function.get("metadata")
            address = (
                _int_from_report(fn_meta.get("virtual_address"))
                if type(fn_meta) is dict
                else None
            )
            size = _int_from_report(function.get("size"))
            if (
                type(name) is not str
                or not name
                or address is None
                or size is None
                or (source, name) == (COMPLEX_SOURCE, COMPLEX_FUNCTION)
            ):
                continue
            numeric.append((address, source, name, size))

    rows: list[dict[str, object]] = [fixed]
    seen = {(COMPLEX_SOURCE, COMPLEX_FUNCTION)}
    for address, source, function, size in sorted(numeric):
        key = (source, function)
        if key in seen:
            continue
        seen.add(key)
        tags = ["fully-matched", "numeric-symbol-order"]
        if size <= 96:
            tags.append("small-function-seed")
        if size >= 256:
            tags.append("high-pressure-seed")
        rows.append(
            {
                "ordinal": len(rows),
                "address": address,
                "size": size,
                "source": source,
                "function": function,
                "seed_tags": tags,
                "claims_observed_features": False,
            }
        )
        if len(rows) + 1 >= limits.max_candidates:
            break
    if len(rows) >= limits.max_candidates:
        raise ValueError("live probe candidate cap reached")
    return tuple(rows)


def _validated_runtime(payload: Mapping[str, object], label: str) -> dict[str, object]:
    runtime = payload.get("runtime_instrumentation")
    if type(runtime) is not dict:
        raise ValueError(f"{label} has no runtime instrumentation")
    if runtime.get("status") != "validated":
        raise ValueError(f"{label} runtime instrumentation is not validated")
    if runtime.get("errors") != []:
        raise ValueError(f"{label} runtime instrumentation has errors")
    if runtime.get("dropped_events") != 0:
        raise ValueError(f"{label} runtime instrumentation dropped events")
    if runtime.get("truncated") is not False:
        raise ValueError(f"{label} runtime instrumentation is truncated")
    event_cap = runtime.get("event_cap")
    if type(event_cap) is not int or event_cap <= 0:
        raise ValueError(f"{label} runtime event cap is invalid")
    expected = runtime.get("expected_site_ids")
    installed = runtime.get("installed_site_ids")
    if (
        type(expected) is not list
        or type(installed) is not list
        or expected != sorted(expected)
        or installed != expected
    ):
        raise ValueError(f"{label} installed site inventory differs")
    events = runtime.get("pcode_events")
    if type(events) is not list:
        raise ValueError(f"{label} runtime PCode events must be a list")
    sequences = [
        row.get("pcode_event_sequence")
        for row in events
        if type(row) is dict
    ]
    if len(sequences) != len(events) or sequences != list(range(len(events))):
        raise ValueError(f"{label} runtime PCode event sequence is not gap-free")
    return runtime


def _runtime_identity(runtime: Mapping[str, object]) -> tuple[object, ...]:
    return (
        runtime.get("compiler_executable_sha256"),
        runtime.get("proof_id"),
        runtime.get("proof_sha256"),
        runtime.get("manifest_sha256"),
        tuple(runtime.get("expected_site_ids", ())),
    )


def _named_locals(map_payload: Mapping[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    events = map_payload.get("events")
    if type(events) is not list:
        return result
    for event_index, event in enumerate(events):
        if type(event) is not dict:
            continue
        sequence = event.get("sequence")
        frame = event.get("frame_state")
        if type(frame) is not dict:
            continue
        locals_state = frame.get("locals")
        samples = (
            locals_state.get("objects_sample")
            if type(locals_state) is dict
            else None
        )
        if type(samples) is not list:
            continue
        for sample_index, sample in enumerate(samples):
            if type(sample) is not dict or "error" in sample:
                continue
            name = sample.get("name")
            pointer = sample.get("object")
            offset = sample.get("stack_offset")
            size = sample.get("size")
            if (
                type(name) is str
                and name
                and _positive_int(pointer)
                and type(offset) is int
                and type(size) is int
                and size >= 0
            ):
                result.append(
                    {
                        "event_id": f"map:{sequence if type(sequence) is int else event_index}:local:{sample_index}",
                        "objobject_ptr": pointer,
                        "name": name,
                        "stack_offset": offset,
                        "size": size,
                    }
                )
    return result


def _multi_virtuals(map_payload: Mapping[str, object]) -> list[dict[str, object]]:
    groups: dict[int, list[dict[str, object]]] = defaultdict(list)
    events = map_payload.get("events")
    if type(events) is not list:
        return []
    for event in events:
        if type(event) is not dict:
            continue
        rows = event.get("ig_object_bindings")
        if type(rows) is not list:
            continue
        for row in rows:
            if type(row) is not dict:
                continue
            event_id = row.get("event_id")
            pointer = row.get("objobject_ptr")
            virtual = row.get("virtual")
            if (
                type(event_id) is str
                and event_id
                and _positive_int(pointer)
                and type(virtual) is int
                and virtual >= 0
                and row.get("ig_id") == virtual
            ):
                groups[pointer].append(row)
    result: list[dict[str, object]] = []
    for pointer, rows in sorted(groups.items()):
        by_virtual = {int(row["virtual"]): row for row in rows}
        if len(by_virtual) < 2:
            continue
        ordered = [by_virtual[key] for key in sorted(by_virtual)]
        result.append(
            {
                "objobject_ptr": pointer,
                "virtuals": [row["virtual"] for row in ordered],
                "event_ids": [row["event_id"] for row in ordered],
                "raw_bindings": [
                    {
                        key: row.get(key)
                        for key in (
                            "class_id",
                            "virtual_kind",
                            "virtual",
                            "ig_id",
                        )
                    }
                    for row in ordered
                ],
            }
        )
    return result


def _allocator_features(
    runtime: Mapping[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    fpr: list[dict[str, object]] = []
    spills: list[dict[str, object]] = []
    for row in runtime["pcode_events"]:
        assert type(row) is dict
        sequence = row["pcode_event_sequence"]
        if (
            row.get("event") == "operand_rewrite"
            and row.get("class_id") == 1
            and row.get("class_name") == "fpr"
            and row.get("virtual_kind") == "f"
            and type(row.get("allocated_physical")) is int
        ):
            fpr.append(
                {
                    "event_id": f"pcode:{sequence}",
                    "instrumented_site_id": row.get("instrumented_site_id"),
                    "pcode_id": row.get("pcode_id"),
                    "operand_lineage_id": row.get("operand_lineage_id"),
                    "virtual": row.get("virtual"),
                    "ig_id": row.get("ig_id"),
                    "allocated_physical": row.get("allocated_physical"),
                }
            )
        if (
            row.get("event") == "pcode_mutation"
            and row.get("mutation_kind") == "spill"
            and type(row.get("inputs")) is list
            and type(row.get("outputs")) is list
        ):
            spills.append(
                {
                    "event_id": f"pcode:{sequence}",
                    "instrumented_site_id": row.get("instrumented_site_id"),
                    "input_pcode_ids": [
                        item.get("pcode_id")
                        for item in row["inputs"]
                        if type(item) is dict
                    ],
                    "output_pcode_ids": [
                        item.get("pcode_id")
                        for item in row["outputs"]
                        if type(item) is dict
                    ],
                }
            )
    return fpr, spills


def summarize_live_probe_features(
    map_dir: Path,
    pcode_dir: Path,
    out_path: Path,
    *,
    source: str | None = None,
    function: str | None = None,
) -> dict[str, Any]:
    """Write canonical observed features from one validated probe pair."""

    map_path = Path(map_dir) / "backend-map-probe.json"
    pcode_path = Path(pcode_dir) / "backend-pcode-snapshot.json"
    map_payload = _json_object(map_path, "map probe")
    pcode_payload = _json_object(pcode_path, "PCode probe")
    for label, payload in (("map probe", map_payload), ("PCode probe", pcode_payload)):
        if payload.get("requested_function_matched") is not True:
            raise ValueError(f"{label} did not match the requested function")
        if payload.get("errors") != []:
            raise ValueError(f"{label} contains errors")
    map_runtime = _validated_runtime(map_payload, "map probe")
    pcode_runtime = _validated_runtime(pcode_payload, "PCode probe")
    if _runtime_identity(map_runtime) != _runtime_identity(pcode_runtime):
        raise ValueError("map/PCode runtime identities differ")
    requested = pcode_payload.get("requested_function")
    if function is None:
        function = requested if type(requested) is str else None
    if type(function) is not str or not function:
        raise ValueError("live feature function must be non-empty string")
    if requested != function or map_payload.get("requested_function") != function:
        raise ValueError("map/PCode requested function differs from summary")
    if type(source) is not str or not source:
        raise ValueError("live feature source must be non-empty string")

    fpr, spills = _allocator_features(pcode_runtime)
    identity = _runtime_identity(pcode_runtime)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA,
        "trace_identity": {
            "source": source,
            "function": function,
            "compiler_executable_sha256": identity[0],
            "proof_id": identity[1],
            "proof_sha256": identity[2],
            "manifest_sha256": identity[3],
        },
        "input_sha256": {
            "backend-map-probe.json": hashlib.sha256(map_path.read_bytes()).hexdigest(),
            "backend-pcode-snapshot.json": hashlib.sha256(pcode_path.read_bytes()).hexdigest(),
        },
        "named_local_identities": _named_locals(map_payload),
        "address_taken_multi_virtual_bindings": _multi_virtuals(map_payload),
        "fpr_allocation_events": fpr,
        "spill_events": spills,
    }
    _write_atomic_json(payload, Path(out_path))
    return payload


def _has_citations(rows: object, *, plural: bool = False) -> bool:
    if type(rows) is not list or not rows:
        return False
    field = "event_ids" if plural else "event_id"
    return all(
        type(row) is dict
        and (
            type(row.get(field)) is list
            and len(row[field]) >= 2
            and all(type(item) is str and item for item in row[field])
            if plural
            else type(row.get(field)) is str and bool(row[field])
        )
        for row in rows
    )


def _selection_probe(
    category: str,
    summary: Mapping[str, object],
    path: Path,
    observed: Mapping[str, object],
) -> dict[str, object]:
    identity = summary["trace_identity"]
    assert type(identity) is dict
    why = {
        "complex-control": "required exact complex-control fixture",
        "named-local": "validated live frame row contains a named local identity",
        "address-taken-multi-virtual": (
            "validated live IG rows bind one ObjObject address to multiple virtuals"
        ),
        "fpr-and-spill": (
            "validated same-trace events contain both FPR allocation and spill"
        ),
    }[category]
    return {
        "category": category,
        "source": identity["source"],
        "function": identity["function"],
        "why": why,
        "observed_features": dict(observed),
        "feature_summary_path": str(path),
        "feature_summary_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def select_live_probe_set(
    preflight_outputs: Sequence[Path],
    candidate_table: Mapping[str, object] | Path,
) -> dict[str, object]:
    """Choose the first distinct numeric qualifying trace per category."""

    summaries: list[tuple[Path, dict[str, object]]] = []
    for path in sorted((Path(item) for item in preflight_outputs), key=str):
        payload = _json_object(path, "live feature summary")
        if payload.get("schema_version") != SCHEMA:
            continue
        summaries.append((path.resolve(), payload))

    chosen: list[dict[str, object]] = []
    used: set[tuple[object, object]] = set()
    for category in _CATEGORIES:
        found: dict[str, object] | None = None
        for path, summary in summaries:
            identity = summary.get("trace_identity")
            if type(identity) is not dict:
                continue
            key = (identity.get("source"), identity.get("function"))
            if key in used:
                continue
            observed: dict[str, object]
            if category == "complex-control":
                if key != (COMPLEX_SOURCE, COMPLEX_FUNCTION):
                    continue
                observed = {"required_fixture": True}
            elif category == "named-local":
                rows = summary.get("named_local_identities")
                if not _has_citations(rows):
                    continue
                observed = {"named_local_identities": rows}
            elif category == "address-taken-multi-virtual":
                rows = summary.get("address_taken_multi_virtual_bindings")
                if not _has_citations(rows, plural=True):
                    continue
                observed = {"address_taken_multi_virtual_bindings": rows}
            else:
                fpr = summary.get("fpr_allocation_events")
                spills = summary.get("spill_events")
                if not _has_citations(fpr) or not _has_citations(spills):
                    continue
                observed = {
                    "fpr_allocation_events": fpr,
                    "spill_events": spills,
                    "same_trace_identity": identity,
                }
            found = _selection_probe(category, summary, path, observed)
            used.add(key)
            break
        if found is None:
            raise IncompleteSelectionError(
                f"bounded preflight has no observed {category} candidate"
            )
        chosen.append(found)

    digest_rows = [
        {
            "path": row["feature_summary_path"],
            "sha256": row["feature_summary_sha256"],
        }
        for row in chosen
    ]
    return {
        "schema_version": SELECTION_SCHEMA,
        "candidate_table_sha256": _digest_candidate(candidate_table),
        "feature_summary_sha256s": digest_rows,
        "probes": chosen,
    }


def _write_atomic_json(payload: Mapping[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_bytes(payload) + b"\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_live_probe_selection(
    payload: Mapping[str, object], path: Path
) -> None:
    _write_atomic_json(payload, Path(path))


def validate_live_probe_selection(
    payload: Mapping[str, object],
    preflight_root: Path,
    candidate_table: Mapping[str, object] | Path,
    melee_root: Path | None = None,
) -> tuple[str, ...]:
    """Re-hash the candidate and every selected current preflight summary."""

    errors: list[str] = []
    if payload.get("schema_version") != SELECTION_SCHEMA:
        errors.append("live probe selection schema differs")
    if payload.get("candidate_table_sha256") != _digest_candidate(candidate_table):
        errors.append("candidate table SHA-256 mismatch")
    probes = payload.get("probes")
    if type(probes) is not list or [
        row.get("category") if type(row) is dict else None for row in probes
    ] != list(_CATEGORIES):
        errors.append("live probe categories/order differ")
        probes = []
    if probes and (
        probes[0].get("source"), probes[0].get("function")
    ) != (COMPLEX_SOURCE, COMPLEX_FUNCTION):
        errors.append("complex-control fixture differs")

    root = Path(preflight_root).resolve()
    seen_paths: set[Path] = set()
    for index, row in enumerate(probes):
        if type(row) is not dict:
            continue
        raw_path = row.get("feature_summary_path")
        if type(raw_path) is not str or not raw_path:
            errors.append(f"probe {index} feature summary path is invalid")
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if path != root and root not in path.parents:
            errors.append(f"probe {index} feature summary escapes preflight root")
            continue
        if path in seen_paths:
            errors.append(f"probe {index} reuses a feature summary")
        seen_paths.add(path)
        if not path.is_file():
            errors.append(f"probe {index} feature summary is missing")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if row.get("feature_summary_sha256") != digest:
            errors.append(f"probe {index} feature summary SHA-256 mismatch")
            continue
        try:
            summary = _json_object(path, f"probe {index} feature summary")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        identity = summary.get("trace_identity")
        if type(identity) is not dict or (
            identity.get("source"), identity.get("function")
        ) != (row.get("source"), row.get("function")):
            errors.append(f"probe {index} feature summary identity differs")
        if row.get("category") != "complex-control":
            observed = row.get("observed_features")
            if type(observed) is not dict or not observed:
                errors.append(f"probe {index} has no observed feature evidence")
    listed = payload.get("feature_summary_sha256s")
    expected_listed = [
        {
            "path": row.get("feature_summary_path"),
            "sha256": row.get("feature_summary_sha256"),
        }
        for row in probes
    ]
    if listed != expected_listed:
        errors.append("selected feature-summary digest inventory differs")
    if melee_root is not None:
        root_path = Path(melee_root)
        for index, row in enumerate(probes):
            source = row.get("source")
            if type(source) is not str or not (root_path / source).is_file():
                errors.append(f"probe {index} source file is missing")
    return tuple(errors)


def _candidate_tuple(candidate: Mapping[str, object]) -> tuple[tuple[str, ...], tuple[object, ...]]:
    reader = candidate.get("backend_reader")
    gate = reader.get("pcode_instrumentation") if type(reader) is dict else None
    if type(gate) is not dict:
        raise ValueError("candidate table has no PCode instrumentation gate")
    site_ids: list[str] = []
    for field in (
        "operand_rewrite_site_ids",
        "operand_mutation_site_ids",
        "code_emission_site_ids",
    ):
        rows = gate.get(field)
        if type(rows) is not list or any(type(item) is not str for item in rows):
            raise ValueError(f"candidate {field} is invalid")
        site_ids.extend(rows)
    if not site_ids or len(site_ids) != len(set(site_ids)):
        raise ValueError("candidate expected site inventory is empty or duplicated")
    return tuple(sorted(site_ids)), (
        gate.get("compiler_executable_sha256"),
        gate.get("proof_id"),
        gate.get("proof_sha256"),
    )


def _probe_runtime_paths(live_root: Path, function: str) -> tuple[Path, Path]:
    base = live_root / function
    return (
        base / "probe-backend-map" / "backend-map-probe.json",
        base / "probe-backend-pcode" / "backend-pcode-snapshot.json",
    )


def validate_live_probe_union(
    selection: Mapping[str, object] | LiveProbeSelection,
    live_root: Path,
    manifest: Mapping[str, object],
    candidate_table: Mapping[str, object] | Path,
) -> dict[str, object]:
    """Validate exact per-run installation/hits and the zero-exemption union."""

    errors: list[str] = []
    candidate = (
        _json_object(candidate_table, "candidate table")
        if isinstance(candidate_table, Path)
        else dict(candidate_table)
    )
    try:
        candidate_ids, candidate_identity = _candidate_tuple(candidate)
    except ValueError as exc:
        candidate_ids, candidate_identity = (), (None, None, None)
        errors.append(str(exc))
    sites = manifest.get("sites")
    if type(sites) is not list or not sites:
        errors.append("manifest has no sites")
        sites = []
    manifest_ids = tuple(
        sorted(
            row.get("site_id")
            for row in sites
            if type(row) is dict and type(row.get("site_id")) is str
        )
    )
    if len(manifest_ids) != len(sites) or len(manifest_ids) != len(set(manifest_ids)):
        errors.append("manifest site inventory is malformed or duplicated")
    if candidate_ids != manifest_ids:
        errors.append("candidate expected site inventory differs from manifest")
    if manifest.get("compiler_executable_sha256") != candidate_identity[0]:
        errors.append("candidate/manifest compiler tuple differs")
    if manifest.get("proof_id") != candidate_identity[1]:
        errors.append("candidate/manifest proof tuple differs")
    per_run = {
        row["site_id"]
        for row in sites
        if type(row) is dict and row.get("hit_policy") == "per-run"
    }

    if isinstance(selection, LiveProbeSelection):
        probes: object = [
            {"source": row.source, "function": row.function}
            for row in selection.candidates
        ]
    else:
        probes = selection.get("probes")
    if type(probes) is not list or len(probes) != 4:
        errors.append("live probe selection must contain exactly four probes")
        probes = []

    union_hits: set[str] = set()
    run_rows: list[dict[str, object]] = []
    for index, probe in enumerate(probes):
        if type(probe) is not dict or type(probe.get("function")) is not str:
            errors.append(f"live probe {index} identity is invalid")
            continue
        function = probe["function"]
        pair_statuses: list[dict[str, object]] = []
        pair_hits: set[str] = set()
        for path in _probe_runtime_paths(Path(live_root), function):
            try:
                payload = _json_object(path, f"live probe {function}")
                runtime = _validated_runtime(payload, f"live probe {function}")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            identity = (
                runtime.get("compiler_executable_sha256"),
                runtime.get("proof_id"),
                runtime.get("proof_sha256"),
            )
            if identity != candidate_identity:
                errors.append(f"live probe {function} candidate tuple differs")
            expected = tuple(runtime.get("expected_site_ids", ()))
            installed = tuple(runtime.get("installed_site_ids", ()))
            if expected != candidate_ids or installed != candidate_ids:
                errors.append(
                    f"live probe {function} installed site inventory differs"
                )
            hits = runtime.get("hit_site_ids")
            if type(hits) is not list or any(type(item) is not str for item in hits):
                errors.append(f"live probe {function} hit inventory is malformed")
                hits = []
            unexpected = set(hits) - set(manifest_ids)
            if unexpected:
                errors.append(f"live probe {function} has unexpected hits")
            missing_per_run = per_run - set(hits)
            if missing_per_run:
                errors.append(f"live probe {function} missed per-run sites")
            pair_hits.update(hits)
            pair_statuses.append(runtime)
        if len(pair_statuses) == 2 and _runtime_identity(pair_statuses[0]) != _runtime_identity(pair_statuses[1]):
            errors.append(f"live probe {function} map/PCode runtime identities differ")
        union_hits.update(pair_hits)
        run_rows.append(
            {
                "source": probe.get("source"),
                "function": function,
                "hit_site_ids": sorted(pair_hits),
            }
        )
    if union_hits != set(manifest_ids):
        errors.append("four-probe hit union differs from manifest inventory")
    return {
        "schema_version": UNION_SCHEMA,
        "candidate_table_sha256": _digest_candidate(candidate_table),
        "manifest_site_ids": list(manifest_ids),
        "per_run_site_ids": sorted(per_run),
        "union_hit_site_ids": sorted(union_hits),
        "runs": run_rows,
        "errors": errors,
    }


__all__ = [
    "IncompleteSelectionError",
    "LiveProbeCandidate",
    "LiveProbeSelection",
    "PreflightLimits",
    "discover_live_probe_candidates",
    "select_live_probe_set",
    "summarize_live_probe_features",
    "validate_live_probe_selection",
    "validate_live_probe_union",
    "write_live_probe_selection",
]
