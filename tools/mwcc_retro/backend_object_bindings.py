"""Fail-closed validation for capture-local ObjObject ownership evidence."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .backend_instrumentation_proof import InstrumentationProof, proof_sha256

SCHEMA_VERSION = "mwcc-retro-object-bindings.v1"
LIFETIME_MODE = "allocation-generation"
CAPABILITIES = frozenset({"compiler-object-bindings"})

_TOP_FIELDS = frozenset(
    {
        "schema_version",
        "capture_identity",
        "capture_run_id",
        "lifetime_proof",
        "coverage",
        "lifecycle_events",
        "objects",
        "virtual_bindings",
        "frame_bindings",
        "pcode_instructions",
        "pcode_occurrences",
        "pcode_operand_lineage_events",
        "source_bindings",
        "source_capture",
    }
)
_CAPTURE_FIELDS = frozenset(
    {
        "nonce",
        "compiler_executable_sha256",
        "source_sha256",
        "mwcc_command_sha256",
        "environment_digest",
        "candidate_object_sha256",
        "function",
        "capture_run_id",
    }
)
_COVERAGE_FIELDS = frozenset(
    {
        "status",
        "ig_classes",
        "frame_areas",
        "spill_owned_ig_coverage",
        "pcode_instrumentation",
        "lifetime_identity",
        "allocator_stage",
        "frame_stage",
        "objects_seen",
        "virtual_bindings_seen",
        "frame_bindings_seen",
        "pcode_instructions_seen",
        "pcode_occurrences_seen",
        "caps",
        "truncated",
        "errors",
    }
)
_LIFETIME_COVERAGE_FIELDS = frozenset(
    {
        "mode",
        "status",
        "proof_id",
        "proof_sha256",
        "initialization_stage",
        "allocation_sites_expected",
        "allocation_sites_hooked",
        "free_sites_expected",
        "free_sites_hooked",
        "first_event_sequence",
        "last_event_sequence",
        "allocation_events",
        "free_events",
        "reuse_events",
        "generation_assignments",
        "event_cap",
        "dropped_events",
        "truncated",
        "errors",
    }
)
_CAP_FIELDS = frozenset(
    {
        "max_ig_nodes",
        "max_frame_objects_per_area",
        "max_pcode_instructions",
        "max_pcode_operands_per_instruction",
    }
)
_EVENT_FIELDS = frozenset(
    {
        "sequence",
        "event",
        "entity_kind",
        "runtime_address",
        "allocation_generation",
        "instrumented_site_id",
        "compiler_stage",
    }
)
_OBJECT_FIELDS = frozenset(
    {
        "object_id",
        "allocation_generation",
        "runtime_address",
        "name",
        "name_kind",
        "name_record_pointer",
        "type_pointer",
        "type_size",
        "areas",
        "stage_snapshots",
        "cross_stage_identity_confidence",
        "lifetime_identity_mode",
    }
)
_SNAPSHOT_FIELDS = frozenset(
    {
        "stage",
        "allocation_generation",
        "lifecycle_sequence_at_capture",
        "runtime_address",
        "name_record_pointer",
        "type_pointer",
        "type_size",
        "readable",
    }
)
_VIRTUAL_FIELDS = frozenset(
    {
        "object_id",
        "class_id",
        "class_name",
        "virtual_kind",
        "virtual",
        "ig_id",
        "ignode_runtime_address",
        "source_stage",
        "confidence",
        "provenance",
    }
)
_FRAME_FIELDS = frozenset(
    {
        "object_id",
        "area",
        "list_node_runtime_address",
        "raw_object_stack_offset",
        "frame_base_size",
        "frame_call_args_size",
        "final_r1_offset",
        "size",
        "source_stage",
        "confidence",
        "provenance",
    }
)

_ENTITY_KINDS = frozenset({"objobject", "pcode"})
_COMPILER_STAGES = frozenset(
    {
        "frontend",
        "optimizer",
        "backend-lowering",
        "colorgraph",
        "scheduler",
        "backend-finalize",
    }
)
_STAGE_ORDER = {"colorgraph_return": 0, "final_scheduler": 1}
_AREA_ORDER = {"arguments": 0, "locals": 1, "temps": 2, "spill-owned": 3}
_FRAME_AREAS = ("arguments", "locals", "temps")
_IG_CLASSES = ("gpr", "fpr")
_CLASS_FIELDS = {0: ("gpr", "r"), 1: ("fpr", "f")}
_NAME_KINDS = frozenset({"source-name", "compiler-synthetic", "observed-unnamed"})
_FRAME_PROVENANCE = (
    "retail-frame-layout-formula.v1",
    "retail-frame-list.object",
    "retail-objobject.stack-offset",
)
_HEX = frozenset("0123456789abcdef")
_MAX_SAFE_JSON_INT = (1 << 53) - 1


@dataclass(frozen=True)
class ObjectBindingValidation:
    normalized: Mapping[str, object]
    capabilities: frozenset[str]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class _LifecycleReplay:
    states: Mapping[int, Mapping[tuple[str, int], int]]
    allocation_events: int
    free_events: int
    reuse_events: int
    generation_assignments: int
    errors: tuple[str, ...]


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonnegative_int(value: object) -> bool:
    return _is_int(value) and value >= 0


def _is_positive_int(value: object) -> bool:
    return _is_int(value) and value > 0


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in _HEX for char in value)


def _closed(value: Mapping[str, object], expected: frozenset[str], label: str, errors: list[str]) -> bool:
    try:
        fields = set(value)
    except (TypeError, ValueError):
        errors.append(f"{label} fields are malformed")
        return False
    extra = sorted(fields - expected, key=repr)
    missing = sorted(expected - fields)
    if extra or missing:
        details: list[str] = []
        if extra:
            details.append(f"unexpected {extra!r}")
        if missing:
            details.append(f"missing {missing!r}")
        errors.append(f"{label} fields: {', '.join(details)}")
        return False
    return True


def _list(value: object, label: str, errors: list[str]) -> list[object]:
    if not isinstance(value, list):
        errors.append(f"{label} must be list")
        return []
    return value


def _empty_errors(value: object, label: str, errors: list[str]) -> None:
    rows = _list(value, f"{label} errors", errors)
    if any(not isinstance(row, str) for row in rows):
        errors.append(f"{label} errors must contain strings")
    if all(isinstance(row, str) for row in rows) and rows != sorted(rows):
        errors.append(f"{label} errors must be canonically ordered")
    if rows:
        errors.append(f"{label} errors must be empty")


def _validate_capture(payload: Mapping[str, object], errors: list[str]) -> None:
    capture = payload.get("capture_identity")
    if not isinstance(capture, Mapping):
        errors.append("capture_identity must be object")
        return
    _closed(capture, _CAPTURE_FIELDS, "capture_identity", errors)
    nonce = capture.get("nonce")
    if not (isinstance(nonce, str) and len(nonce) == 32 and all(char in _HEX for char in nonce)):
        errors.append("capture nonce must be 32 lowercase hex")
    for field in (
        "compiler_executable_sha256",
        "source_sha256",
        "mwcc_command_sha256",
        "environment_digest",
        "candidate_object_sha256",
        "capture_run_id",
    ):
        if not _is_sha256(capture.get(field)):
            errors.append(f"capture_identity {field} must be 64 lowercase hex")
    if not isinstance(capture.get("function"), str) or not capture.get("function"):
        errors.append("capture_identity function must be non-empty string")
    if not _is_sha256(payload.get("capture_run_id")):
        errors.append("capture_run_id must be 64 lowercase hex")
    if payload.get("capture_run_id") != capture.get("capture_run_id"):
        errors.append("capture_run_id does not match capture identity")


def _proof_sites(
    proof: object, errors: list[str]
) -> tuple[dict[str, Mapping[str, object]], dict[str, Mapping[str, object]]]:
    if not isinstance(proof, InstrumentationProof):
        errors.append("trusted proof must be InstrumentationProof")
        return {}, {}
    if not isinstance(proof.payload, Mapping):
        errors.append("trusted proof payload must be object")
        return {}, {}
    if proof.payload.get("proof_id") != proof.proof_id:
        errors.append("trusted proof_id does not match trusted proof payload")
    if proof.payload.get("compiler_executable_sha256") != proof.compiler_executable_sha256:
        errors.append("trusted proof compiler digest does not match proof payload")
    try:
        digest = proof_sha256(proof.payload)
    except (OverflowError, RecursionError, TypeError, ValueError):
        errors.append("trusted proof payload is not canonicalizable")
    else:
        if digest != proof.sha256:
            errors.append("trusted proof digest does not match trusted proof payload")

    def inventory(name: str) -> dict[str, Mapping[str, object]]:
        rows = proof.payload.get(name)
        if not isinstance(rows, list):
            errors.append(f"trusted proof {name} must be list")
            return {}
        result: dict[str, Mapping[str, object]] = {}
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping) or not isinstance(row.get("site_id"), str):
                errors.append(f"trusted proof {name} row {index} is malformed")
                continue
            site_id = row["site_id"]
            if site_id in result:
                errors.append(f"trusted proof has duplicate {name} site_id")
            result[site_id] = row
        return result

    return inventory("allocation_sites"), inventory("free_sites")


def _validate_proof_binding(payload: Mapping[str, object], proof: object, errors: list[str]) -> None:
    embedded = payload.get("lifetime_proof")
    if not isinstance(embedded, Mapping):
        errors.append("lifetime_proof must be object")
        return
    if not isinstance(proof, InstrumentationProof):
        return
    try:
        matches = embedded == proof.payload
    except (RecursionError, TypeError, ValueError):
        matches = False
    if not matches:
        errors.append("embedded lifetime_proof does not match trusted proof")
    capture = payload.get("capture_identity")
    if isinstance(capture, Mapping) and (capture.get("compiler_executable_sha256") != proof.compiler_executable_sha256):
        errors.append("capture compiler digest does not match trusted proof")


def _replay_lifecycle(
    raw_events: object,
    allocation_sites: Mapping[str, Mapping[str, object]],
    free_sites: Mapping[str, Mapping[str, object]],
) -> _LifecycleReplay:
    errors: list[str] = []
    events = _list(raw_events, "lifecycle_events", errors)
    active: dict[tuple[str, int], int] = {}
    last_generation: dict[tuple[str, int], int] = {}
    states: dict[int, Mapping[tuple[str, int], int]] = {-1: MappingProxyType({})}
    allocations = frees = reuse = assignments = 0

    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            errors.append(f"lifecycle event {index} must be object")
            continue
        _closed(event, _EVENT_FIELDS, f"lifecycle event {index}", errors)
        sequence = event.get("sequence")
        if not _is_nonnegative_int(sequence):
            errors.append(f"lifecycle event {index} sequence must be nonnegative integer")
        if sequence != index:
            errors.append(f"lifecycle sequence gap at index {index}")
        kind = event.get("entity_kind")
        if not isinstance(kind, str) or kind not in _ENTITY_KINDS:
            errors.append(f"lifecycle event {index} has unknown entity_kind {kind!r}")
        address = event.get("runtime_address")
        if not _is_positive_int(address):
            errors.append(f"lifecycle event {index} runtime_address must be positive integer")
        generation = event.get("allocation_generation")
        if not _is_positive_int(generation):
            errors.append(f"lifecycle event {index} allocation_generation must be positive integer")
        stage = event.get("compiler_stage")
        if not isinstance(stage, str) or stage not in _COMPILER_STAGES:
            errors.append(f"lifecycle event {index} has unknown compiler_stage {stage!r}")
        action = event.get("event")
        if action not in ("allocate", "free"):
            errors.append(f"lifecycle event {index} has unknown lifecycle event {action!r}")
        site_id = event.get("instrumented_site_id")
        if not isinstance(site_id, str) or not site_id:
            errors.append(f"lifecycle event {index} site id must be non-empty string")

        valid_identity = (
            isinstance(kind, str)
            and kind in _ENTITY_KINDS
            and _is_positive_int(address)
            and _is_positive_int(generation)
        )
        sites = allocation_sites if action == "allocate" else free_sites
        site = sites.get(site_id) if isinstance(site_id, str) else None
        if action in ("allocate", "free") and site is None:
            site_kind = "allocation" if action == "allocate" else "free"
            errors.append(f"lifecycle event {index} references unknown {site_kind} site")
        elif site is not None and (site.get("entity_kind") != kind or site.get("compiler_stage") != stage):
            errors.append(f"lifecycle event {index} does not match trusted site")

        if valid_identity and action == "allocate":
            key = (kind, address)
            expected = last_generation.get(key, 0) + 1
            if generation != expected:
                errors.append(f"lifecycle event {index} generation must increment from {expected - 1} to {expected}")
            if key in active:
                errors.append(f"lifecycle event {index} allocation occurred while prior generation is active")
            if key in last_generation and key not in active:
                reuse += 1
            active[key] = generation
            last_generation[key] = generation
            allocations += 1
            assignments += 1
        elif valid_identity and action == "free":
            key = (kind, address)
            if active.get(key) != generation:
                errors.append(f"lifecycle event {index} free has no matching active allocation")
            else:
                del active[key]
            frees += 1
        if sequence == index:
            states[index] = MappingProxyType(dict(active))

    return _LifecycleReplay(
        MappingProxyType(states),
        allocations,
        frees,
        reuse,
        assignments,
        tuple(errors),
    )


def _count_proof_rows(proof: object, field: str) -> int | None:
    if not isinstance(proof, InstrumentationProof) or not isinstance(proof.payload, Mapping):
        return None
    rows = proof.payload.get(field)
    return len(rows) if isinstance(rows, list) else None


def _validate_lifetime_coverage(
    value: object,
    proof: object,
    replay: _LifecycleReplay,
    event_count: int,
    errors: list[str],
) -> None:
    if not isinstance(value, Mapping):
        errors.append("lifetime_identity must be object")
        return
    _closed(value, _LIFETIME_COVERAGE_FIELDS, "lifetime_identity", errors)
    if value.get("mode") != LIFETIME_MODE:
        errors.append(f"lifetime identity mode must be {LIFETIME_MODE}")
    if value.get("status") != "complete":
        errors.append("lifetime identity status must be complete")
    if value.get("initialization_stage") != "compiler-process-entry-before-compile":
        errors.append("lifecycle tracing initialized too late")
    if isinstance(proof, InstrumentationProof):
        if value.get("proof_id") != proof.proof_id:
            errors.append("coverage proof_id does not match trusted proof")
        if value.get("proof_sha256") != proof.sha256:
            errors.append("coverage proof_sha256 does not match trusted proof")
    for prefix, proof_field in (
        ("allocation", "allocation_sites"),
        ("free", "free_sites"),
    ):
        expected = value.get(f"{prefix}_sites_expected")
        hooked = value.get(f"{prefix}_sites_hooked")
        if not _is_nonnegative_int(expected) or not _is_nonnegative_int(hooked):
            errors.append(f"{prefix} site counts must be nonnegative integers")
            continue
        proof_count = _count_proof_rows(proof, proof_field)
        if proof_count is not None and expected != proof_count:
            errors.append(f"{prefix} expected site count does not match trusted proof")
        if hooked != expected:
            errors.append(f"{prefix} site coverage is incomplete")

    expected_counts = {
        "allocation_events": replay.allocation_events,
        "free_events": replay.free_events,
        "reuse_events": replay.reuse_events,
        "generation_assignments": replay.generation_assignments,
    }
    for field, expected in expected_counts.items():
        actual = value.get(field)
        if not _is_nonnegative_int(actual):
            errors.append(f"lifetime {field} must be nonnegative integer")
        elif actual != expected:
            errors.append(f"{field} does not match lifecycle replay")
    expected_first = 0 if event_count else -1
    expected_last = event_count - 1
    first_sequence = value.get("first_event_sequence")
    last_sequence = value.get("last_event_sequence")
    if not _is_int(first_sequence):
        errors.append("lifetime first_event_sequence must be integer")
    elif first_sequence != expected_first:
        errors.append("lifetime first_event_sequence does not match lifecycle events")
    if not _is_int(last_sequence):
        errors.append("lifetime last_event_sequence must be integer")
    elif last_sequence != expected_last:
        errors.append("lifetime last_event_sequence does not match lifecycle events")
    event_cap = value.get("event_cap")
    if not _is_positive_int(event_cap):
        errors.append("lifetime event_cap must be positive integer")
    elif event_count >= event_cap:
        errors.append("lifecycle event cap was reached")
    dropped_events = value.get("dropped_events")
    if not _is_nonnegative_int(dropped_events):
        errors.append("lifetime dropped_events must be nonnegative integer")
    elif dropped_events != 0:
        errors.append("lifecycle events were dropped")
    if value.get("truncated") is not False:
        errors.append("lifecycle capture is truncated")
    _empty_errors(value.get("errors"), "lifetime identity", errors)


def _validate_coverage(
    payload: Mapping[str, object],
    proof: object,
    replay: _LifecycleReplay,
    errors: list[str],
) -> None:
    value = payload.get("coverage")
    if not isinstance(value, Mapping):
        errors.append("coverage must be object")
        return
    _closed(value, _COVERAGE_FIELDS, "coverage", errors)
    if value.get("status") != "complete":
        errors.append("coverage status must be complete")
    ig_classes = _list(value.get("ig_classes"), "ig_classes", errors)
    if ig_classes != list(_IG_CLASSES):
        errors.append("IG coverage must include gpr and fpr in canonical order")
    frame_areas = _list(value.get("frame_areas"), "frame_areas", errors)
    if set(frame_areas) == set(_FRAME_AREAS) and frame_areas != list(_FRAME_AREAS):
        errors.append("frame_areas must be canonically ordered")
    elif frame_areas != list(_FRAME_AREAS):
        errors.append("frame coverage must include arguments, locals, and temps")
    if value.get("spill_owned_ig_coverage") != "complete":
        errors.append("spill-owned IG coverage must be complete")
    if value.get("allocator_stage") != "colorgraph_return":
        errors.append("allocator_stage must be colorgraph_return")
    if value.get("frame_stage") != "final_scheduler":
        errors.append("frame_stage must be final_scheduler")
    if value.get("truncated") is not False:
        errors.append("coverage is truncated")
    _empty_errors(value.get("errors"), "coverage", errors)

    collection_counts = (
        ("objects_seen", "objects"),
        ("virtual_bindings_seen", "virtual_bindings"),
        ("frame_bindings_seen", "frame_bindings"),
        ("pcode_instructions_seen", "pcode_instructions"),
        ("pcode_occurrences_seen", "pcode_occurrences"),
    )
    for count_field, collection in collection_counts:
        rows = payload.get(collection)
        if not isinstance(rows, list):
            continue
        count = value.get(count_field)
        if not _is_nonnegative_int(count):
            errors.append(f"{count_field} must be nonnegative integer")
        elif count != len(rows):
            errors.append(f"{count_field} does not match {collection}")

    caps = value.get("caps")
    if not isinstance(caps, Mapping):
        errors.append("coverage caps must be object")
    else:
        _closed(caps, _CAP_FIELDS, "coverage caps", errors)
        for field in _CAP_FIELDS:
            if not _is_positive_int(caps.get(field)):
                errors.append(f"coverage cap {field} must be positive integer")
        bindings = payload.get("virtual_bindings")
        max_ig = caps.get("max_ig_nodes")
        if isinstance(bindings, list) and _is_positive_int(max_ig) and len(bindings) >= max_ig:
            errors.append("IG node cap was reached")
        frames = payload.get("frame_bindings")
        max_frames = caps.get("max_frame_objects_per_area")
        if isinstance(frames, list) and _is_positive_int(max_frames):
            counts = Counter(
                row.get("area") for row in frames if isinstance(row, Mapping) and isinstance(row.get("area"), str)
            )
            if any(count >= max_frames for count in counts.values()):
                errors.append("frame object cap was reached")
        pcodes = payload.get("pcode_instructions")
        max_pcodes = caps.get("max_pcode_instructions")
        if isinstance(pcodes, list) and _is_positive_int(max_pcodes) and len(pcodes) >= max_pcodes:
            errors.append("PCode instruction cap was reached")

    if not isinstance(value.get("pcode_instrumentation"), Mapping):
        errors.append("pcode_instrumentation must be object")
    event_rows = payload.get("lifecycle_events")
    _validate_lifetime_coverage(
        value.get("lifetime_identity"),
        proof,
        replay,
        len(event_rows) if isinstance(event_rows, list) else 0,
        errors,
    )


def _pointer_or_none(value: object) -> bool:
    return value is None or _is_positive_int(value)


def _validate_snapshot(
    snapshot: Mapping[str, object],
    label: str,
    replay: _LifecycleReplay,
    errors: list[str],
) -> None:
    _closed(snapshot, _SNAPSHOT_FIELDS, label, errors)
    stage = snapshot.get("stage")
    if not isinstance(stage, str) or stage not in _STAGE_ORDER:
        errors.append(f"{label} has unknown stage {stage!r}")
    address = snapshot.get("runtime_address")
    generation = snapshot.get("allocation_generation")
    if not _is_positive_int(address):
        errors.append(f"{label} runtime_address must be positive integer")
    if not _is_positive_int(generation):
        errors.append(f"{label} allocation_generation must be positive integer")
    sequence = snapshot.get("lifecycle_sequence_at_capture")
    if not _is_int(sequence) or sequence not in replay.states:
        errors.append(f"{label}: snapshot lifecycle sequence is out of range")
    elif _is_positive_int(address) and _is_positive_int(generation):
        active = replay.states[sequence]
        if active.get(("objobject", address)) != generation:
            errors.append(f"{label} snapshot generation is not active")
    for field in ("name_record_pointer", "type_pointer"):
        if not _pointer_or_none(snapshot.get(field)):
            errors.append(f"{label} {field} must be positive integer or null")
    if not _is_nonnegative_int(snapshot.get("type_size")):
        errors.append(f"{label} type_size must be nonnegative integer")
    if not isinstance(snapshot.get("readable"), bool):
        errors.append(f"{label} readable must be boolean")
    elif snapshot.get("readable") is False:
        errors.append(f"{label} snapshot is unreadable")


def _validate_objects(value: object, replay: _LifecycleReplay, errors: list[str]) -> dict[str, Mapping[str, object]]:
    rows = _list(value, "objects", errors)
    objects: dict[str, Mapping[str, object]] = {}
    sort_keys: list[tuple[int, int]] = []
    sortable = True
    for index, row in enumerate(rows):
        label = f"object {index}"
        if not isinstance(row, Mapping):
            errors.append(f"{label} must be object")
            sortable = False
            continue
        _closed(row, _OBJECT_FIELDS, label, errors)
        object_id = row.get("object_id")
        address = row.get("runtime_address")
        generation = row.get("allocation_generation")
        if not isinstance(object_id, str) or not object_id:
            errors.append(f"{label} object_id must be non-empty string")
        elif object_id in objects:
            errors.append("duplicate object_id")
        else:
            objects[object_id] = row
        if not _is_positive_int(address):
            errors.append(f"{label} runtime_address must be positive integer")
            sortable = False
        if not _is_positive_int(generation):
            errors.append(f"{label} allocation_generation must be positive integer")
            sortable = False
        if _is_positive_int(address) and _is_positive_int(generation):
            sort_keys.append((address, generation))
        if object_id != f"obj-{index}":
            errors.append(f"{label} object_id is not deterministic")
        name_kind = row.get("name_kind")
        if not isinstance(name_kind, str) or name_kind not in _NAME_KINDS:
            errors.append(f"{label} has unknown name_kind {name_kind!r}")
        name = row.get("name")
        if name_kind == "observed-unnamed":
            if name is not None:
                errors.append(f"{label} observed-unnamed name must be null")
        elif not isinstance(name, str) or not name:
            errors.append(f"{label} name must be non-empty string")
        for field in ("name_record_pointer", "type_pointer"):
            if not _pointer_or_none(row.get(field)):
                errors.append(f"{label} {field} must be positive integer or null")
        if not _is_nonnegative_int(row.get("type_size")):
            errors.append(f"{label} type_size must be nonnegative integer")
        if row.get("lifetime_identity_mode") != LIFETIME_MODE:
            errors.append(f"{label} lifetime_identity_mode must be {LIFETIME_MODE}")

        areas = _list(row.get("areas"), f"{label} areas", errors)
        if not areas:
            errors.append(f"{label} areas must not be empty")
        if any(not isinstance(area, str) or area not in _AREA_ORDER for area in areas):
            errors.append(f"{label} has unknown area")
        if len(areas) != len(set(area for area in areas if isinstance(area, str))):
            errors.append(f"{label} areas contain duplicates")
        valid_areas = [area for area in areas if isinstance(area, str) and area in _AREA_ORDER]
        if len(valid_areas) == len(areas) and valid_areas != sorted(valid_areas, key=_AREA_ORDER.__getitem__):
            errors.append(f"{label} areas must be canonically ordered")

        snapshots = _list(row.get("stage_snapshots"), f"{label} stage_snapshots", errors)
        if len(snapshots) not in (1, 2):
            errors.append(f"{label} stage_snapshots must contain one or two records")
        stages: list[str] = []
        lifecycle_sequences: list[int] = []
        fingerprints: list[tuple[object, object, object, object]] = []
        for snapshot_index, stage_row in enumerate(snapshots):
            snapshot_label = f"{label} snapshot {snapshot_index}"
            if not isinstance(stage_row, Mapping):
                errors.append(f"{snapshot_label} must be object")
                continue
            _validate_snapshot(stage_row, snapshot_label, replay, errors)
            stage = stage_row.get("stage")
            if isinstance(stage, str) and stage in _STAGE_ORDER:
                stages.append(stage)
            sequence = stage_row.get("lifecycle_sequence_at_capture")
            if _is_int(sequence):
                lifecycle_sequences.append(sequence)
            fingerprint = (
                stage_row.get("runtime_address"),
                stage_row.get("name_record_pointer"),
                stage_row.get("type_pointer"),
                stage_row.get("type_size"),
            )
            fingerprints.append(fingerprint)
            if stage_row.get("runtime_address") != address:
                errors.append(f"{snapshot_label} runtime_address does not match object")
            if stage_row.get("allocation_generation") != generation:
                errors.append(f"{snapshot_label} allocation_generation does not match object")
            for field in ("name_record_pointer", "type_pointer", "type_size"):
                if stage_row.get(field) != row.get(field):
                    errors.append(f"{snapshot_label} {field} does not match object")
        if len(stages) == len(snapshots):
            if len(stages) != len(set(stages)):
                errors.append(f"{label} has duplicate stage snapshot")
            if stages != sorted(stages, key=_STAGE_ORDER.__getitem__):
                errors.append(f"{label} stage_snapshots must be canonically ordered")
        if len(fingerprints) == 2 and fingerprints[0] != fingerprints[1]:
            errors.append(f"{label} object fingerprint changed across stages")
        if len(lifecycle_sequences) == 2 and lifecycle_sequences[1] < lifecycle_sequences[0]:
            errors.append(f"{label} snapshot lifecycle sequences must be monotonic")
        confidence = row.get("cross_stage_identity_confidence")
        if len(snapshots) == 2 and confidence != "derived-unique":
            errors.append(f"{label} two-stage object confidence must be derived-unique")
        if len(snapshots) == 1 and confidence is not None:
            errors.append(f"{label} one-stage object confidence must be null")
        stage_set = set(stages)
        if "final_scheduler" not in stage_set and areas != ["spill-owned"]:
            errors.append(f"{label} allocator-only object must be spill-owned")
        if "final_scheduler" in stage_set and "spill-owned" in areas:
            errors.append(f"{label} spill-owned object cannot have final-stage snapshot")

    if sortable and sort_keys != sorted(sort_keys):
        errors.append("objects must be canonically ordered")
    if len(sort_keys) != len(set(sort_keys)):
        errors.append("duplicate object runtime address/generation")
    return objects


def _has_stage(row: Mapping[str, object], stage: str) -> bool:
    snapshots = row.get("stage_snapshots")
    return isinstance(snapshots, list) and any(
        isinstance(item, Mapping) and item.get("stage") == stage for item in snapshots
    )


def _validate_virtual_bindings(
    value: object,
    objects: Mapping[str, Mapping[str, object]],
    errors: list[str],
) -> None:
    rows = _list(value, "virtual_bindings", errors)
    keys: list[tuple[object, ...]] = []
    seen_rows: set[tuple[object, ...]] = set()
    seen_virtual_identities: set[tuple[object, ...]] = set()
    seen_ig_identities: set[tuple[object, ...]] = set()
    seen_ignode_addresses: set[int] = set()
    virtual_owners: dict[tuple[object, ...], object] = {}
    ig_owners: dict[tuple[object, ...], object] = {}
    sortable = True
    for index, row in enumerate(rows):
        label = f"virtual binding {index}"
        if not isinstance(row, Mapping):
            errors.append(f"{label} must be object")
            sortable = False
            continue
        _closed(row, _VIRTUAL_FIELDS, label, errors)
        object_id = row.get("object_id")
        owner = objects.get(object_id) if isinstance(object_id, str) else None
        if owner is None:
            errors.append(f"{label} virtual binding references unknown object")
        elif not _has_stage(owner, "colorgraph_return"):
            errors.append(f"{label} object lacks allocator-stage snapshot")
        class_id = row.get("class_id")
        class_name = row.get("class_name")
        virtual_kind = row.get("virtual_kind")
        expected_class = _CLASS_FIELDS.get(class_id) if _is_nonnegative_int(class_id) else None
        if expected_class is None or (class_name, virtual_kind) != expected_class:
            errors.append(f"{label} virtual class fields disagree")
        for field in ("virtual", "ig_id"):
            if not _is_nonnegative_int(row.get(field)):
                errors.append(f"{label} {field} must be nonnegative integer")
        if _is_nonnegative_int(row.get("virtual")) and _is_nonnegative_int(row.get("ig_id")):
            if row.get("virtual") != row.get("ig_id"):
                errors.append(f"{label} virtual must equal ig_id")
        if not _is_positive_int(row.get("ignode_runtime_address")):
            errors.append(f"{label} ignode_runtime_address must be positive integer")
        if row.get("source_stage") != "colorgraph_return":
            errors.append(f"{label} source_stage must be colorgraph_return")
        if row.get("confidence") != "observed":
            errors.append(f"{label} confidence must be observed")
        if row.get("provenance") != "retail-ignode.obj_addr":
            errors.append(f"{label} provenance must be retail-ignode.obj_addr")

        key = (
            object_id,
            class_id,
            virtual_kind,
            row.get("virtual"),
            row.get("ig_id"),
            row.get("ignode_runtime_address"),
        )
        try:
            if key in seen_rows:
                errors.append("duplicate virtual binding")
            seen_rows.add(key)
            keys.append(key)
        except TypeError:
            sortable = False
        virtual_key = (class_id, virtual_kind, row.get("virtual"))
        ig_key = (class_id, row.get("ig_id"))
        try:
            if virtual_key in seen_virtual_identities:
                errors.append(f"{label} duplicate class/virtual binding")
            seen_virtual_identities.add(virtual_key)
            if ig_key in seen_ig_identities:
                errors.append(f"{label} duplicate class/IG binding")
            seen_ig_identities.add(ig_key)
        except TypeError:
            pass
        ignode_address = row.get("ignode_runtime_address")
        if _is_positive_int(ignode_address):
            if ignode_address in seen_ignode_addresses:
                errors.append(f"{label} duplicate IGNode runtime address")
            seen_ignode_addresses.add(ignode_address)
        for identity, owners in (
            (virtual_key, virtual_owners),
            (ig_key, ig_owners),
        ):
            try:
                prior = owners.get(identity)
                if prior is not None and prior != object_id:
                    errors.append(f"{label} virtual/IG identity has multiple objects")
                owners[identity] = object_id
            except TypeError:
                pass
    if sortable:
        try:
            if keys != sorted(keys):
                errors.append("virtual_bindings must be canonically ordered")
        except TypeError:
            errors.append("virtual_bindings contain non-sortable values")


def _validate_frame_bindings(
    value: object,
    objects: Mapping[str, Mapping[str, object]],
    errors: list[str],
) -> None:
    rows = _list(value, "frame_bindings", errors)
    keys: list[tuple[object, ...]] = []
    seen: set[tuple[object, ...]] = set()
    seen_list_nodes: set[int] = set()
    object_areas: Counter[tuple[str, str]] = Counter()
    sortable = True
    for index, row in enumerate(rows):
        label = f"frame binding {index}"
        if not isinstance(row, Mapping):
            errors.append(f"{label} must be object")
            sortable = False
            continue
        _closed(row, _FRAME_FIELDS, label, errors)
        object_id = row.get("object_id")
        owner = objects.get(object_id) if isinstance(object_id, str) else None
        area = row.get("area")
        if not isinstance(area, str) or area not in _FRAME_AREAS:
            errors.append(f"{label} has unknown frame area {area!r}")
        if not _is_positive_int(row.get("list_node_runtime_address")):
            errors.append(f"{label} list_node_runtime_address must be positive integer")
        else:
            list_node = row["list_node_runtime_address"]
            if list_node in seen_list_nodes:
                errors.append(f"{label} duplicate frame list node runtime address")
            seen_list_nodes.add(list_node)
        if not _is_int(row.get("raw_object_stack_offset")):
            errors.append(f"{label} raw_object_stack_offset must be integer")
        for field in ("frame_base_size", "frame_call_args_size", "size"):
            if not _is_nonnegative_int(row.get(field)):
                errors.append(f"{label} {field} must be nonnegative integer")
        if owner is None:
            errors.append(f"{label} frame binding references unknown object")
        else:
            if not _has_stage(owner, "final_scheduler"):
                errors.append(f"{label} object lacks final-stage snapshot")
            owner_areas = owner.get("areas")
            if isinstance(owner_areas, list) and "spill-owned" in owner_areas:
                errors.append(f"{label} spill-owned object cannot have frame binding")
            if not isinstance(owner_areas, list) or area not in owner_areas:
                errors.append(f"{label} frame binding area is absent from object areas")
            if row.get("size") != owner.get("type_size"):
                errors.append(f"{label} size does not match object type_size")
        inputs = (
            row.get("frame_base_size"),
            row.get("frame_call_args_size"),
            row.get("raw_object_stack_offset"),
        )
        if all(_is_int(item) for item in inputs):
            expected_offset = inputs[0] + inputs[1] + inputs[2]
            if not _is_int(row.get("final_r1_offset")):
                errors.append(f"{label} final_r1_offset must be integer")
            elif row.get("final_r1_offset") != expected_offset:
                errors.append(f"{label} final_r1_offset does not match frame layout formula")
        elif not _is_int(row.get("final_r1_offset")):
            errors.append(f"{label} final_r1_offset must be integer")
        if row.get("source_stage") != "final_scheduler":
            errors.append(f"{label} source_stage must be final_scheduler")
        if row.get("confidence") != "derived-unique":
            errors.append(f"{label} frame binding confidence must be derived-unique")
        provenance = _list(row.get("provenance"), f"{label} provenance", errors)
        if tuple(provenance) != _FRAME_PROVENANCE:
            errors.append(f"{label} provenance is incomplete or not canonically ordered")

        if isinstance(object_id, str) and isinstance(area, str):
            object_areas[(object_id, area)] += 1
        key = (
            object_id,
            _AREA_ORDER.get(area, 99),
            row.get("list_node_runtime_address"),
            row.get("final_r1_offset"),
        )
        try:
            if key in seen:
                errors.append("duplicate frame binding")
            seen.add(key)
            keys.append(key)
        except TypeError:
            sortable = False

    for object_id, owner in objects.items():
        areas = owner.get("areas")
        if not isinstance(areas, list):
            continue
        for area in areas:
            if area == "spill-owned":
                if any(key[0] == object_id for key in object_areas):
                    errors.append("spill-owned object cannot have frame binding")
                continue
            count = object_areas[(object_id, area)]
            if count == 0:
                errors.append(f"frame-list coverage missing {area} binding for {object_id}")
            elif count > 1:
                errors.append(f"duplicate frame-list membership for {object_id} in {area}")
    if sortable:
        try:
            if keys != sorted(keys):
                errors.append("frame_bindings must be canonically ordered")
        except TypeError:
            errors.append("frame_bindings contain non-sortable values")


def _freeze(value: object, active: set[int] | None = None) -> object:
    seen = set() if active is None else active
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen:
            raise ValueError("recursive value")
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        seen.add(identity)
        result = MappingProxyType({key: _freeze(item, seen) for key, item in value.items()})
        seen.remove(identity)
        return result
    if isinstance(value, list):
        identity = id(value)
        if identity in seen:
            raise ValueError("recursive value")
        seen.add(identity)
        result = tuple(_freeze(item, seen) for item in value)
        seen.remove(identity)
        return result
    if value is None or type(value) is bool:
        return value
    if type(value) is str:
        value.encode("utf-8")
        return value
    if type(value) is int:
        if not -_MAX_SAFE_JSON_INT <= value <= _MAX_SAFE_JSON_INT:
            raise ValueError("integer exceeds RFC 8785 safe domain")
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError(f"non-JSON value {type(value).__name__}")


def _validate(payload: object, proof: object) -> ObjectBindingValidation:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ObjectBindingValidation(MappingProxyType({}), frozenset(), ("object_bindings must be object",))
    _closed(payload, _TOP_FIELDS, "object_bindings", errors)
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    _validate_capture(payload, errors)
    _validate_proof_binding(payload, proof, errors)
    allocation_sites, free_sites = _proof_sites(proof, errors)
    replay = _replay_lifecycle(payload.get("lifecycle_events"), allocation_sites, free_sites)
    errors.extend(replay.errors)
    for field in (
        "objects",
        "virtual_bindings",
        "frame_bindings",
        "pcode_instructions",
        "pcode_occurrences",
        "pcode_operand_lineage_events",
        "source_bindings",
    ):
        if not isinstance(payload.get(field), list):
            errors.append(f"{field} must be list")
    if payload.get("source_bindings") != []:
        errors.append("source_bindings must be empty in v1")
    if payload.get("source_capture") is not None:
        errors.append("source_capture must be null in v1")

    objects = _validate_objects(payload.get("objects"), replay, errors)
    _validate_virtual_bindings(payload.get("virtual_bindings"), objects, errors)
    _validate_frame_bindings(payload.get("frame_bindings"), objects, errors)
    _validate_coverage(payload, proof, replay, errors)

    try:
        normalized = _freeze(payload)
    except (RecursionError, TypeError, ValueError) as exc:
        errors.append(f"object_bindings diagnostic normalization failed: {type(exc).__name__}")
        normalized = MappingProxyType({})
    if not isinstance(normalized, Mapping):  # pragma: no cover - payload is a mapping
        raise TypeError("normalized payload is not mapping")
    if errors:
        return ObjectBindingValidation(normalized, frozenset(), tuple(errors))
    return ObjectBindingValidation(normalized, CAPABILITIES, ())


def validate_object_bindings(payload: Mapping[str, object], proof: InstrumentationProof) -> ObjectBindingValidation:
    """Validate one v1 payload, returning controlled errors and no partial capability."""

    try:
        return _validate(payload, proof)
    except (OverflowError, RecursionError, TypeError, ValueError) as exc:
        return ObjectBindingValidation(
            MappingProxyType({}),
            frozenset(),
            (f"object_bindings contains malformed values: {type(exc).__name__}",),
        )


__all__ = ["ObjectBindingValidation", "validate_object_bindings"]
