"""Assemble candidate backend traces from validated partial probe events."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.mwcc_retro import backend_events

FRAME_AREAS = ("locals", "arguments", "temps")
_MAX_SIDECAR_JSON_DEPTH = 256


@dataclass(frozen=True, slots=True)
class BackendTraceV2Assembly:
    payload: dict[str, Any]
    capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class BackendTraceV2Verification:
    payload: dict[str, Any]
    capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class CorrelatedV2Sidecars:
    capture_attempt_id: str
    object_payload: dict[str, Any]
    pcode_payload: dict[str, Any]


def _reject_excessive_json_nesting(payload: object, *, label: str) -> None:
    pending = [(payload, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > _MAX_SIDECAR_JSON_DEPTH:
            raise ValueError(f"{label} sidecar exceeds the JSON nesting limit")
        if type(value) is dict:
            pending.extend((child, depth + 1) for child in value.values())
        elif type(value) is list:
            pending.extend((child, depth + 1) for child in value)


def _load_sidecar(path: Path, *, schema_version: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except RecursionError as exc:
        raise ValueError(f"{label} sidecar exceeds the JSON nesting limit") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} sidecar could not be read: {type(exc).__name__}") from exc
    _reject_excessive_json_nesting(payload, label=label)
    if type(payload) is not dict:
        raise ValueError(f"{label} sidecar must be an object")
    expected = {
        "schema_version",
        "capture_attempt",
        "capture_status",
        "events",
        "publication_complete",
    }
    if set(payload) != expected:
        raise ValueError(f"{label} sidecar fields differ from exact schema")
    if payload.get("schema_version") != schema_version:
        raise ValueError(f"{label} sidecar schema_version mismatch")
    if payload.get("publication_complete") is not True:
        raise ValueError(f"{label} sidecar publication is incomplete")
    if type(payload.get("events")) is not list:
        raise ValueError(f"{label} sidecar events must be a list")
    if type(payload.get("capture_status")) is not dict:
        raise ValueError(f"{label} sidecar capture_status must be an object")
    if type(payload.get("capture_attempt")) is not dict:
        raise ValueError(f"{label} sidecar capture_attempt must be an object")
    return payload


def _attempt_identifies_function(attempt: dict[str, Any], function: str) -> bool:
    identity = attempt.get("function_identity")
    expected = {
        "requested",
        "canonical_name",
        "symbol_name",
        "source_name",
        "aliases",
        "source_file",
    }
    if type(identity) is not dict or set(identity) != expected:
        raise ValueError("capture function_identity fields differ from exact schema")
    for field in expected - {"aliases"}:
        if type(identity.get(field)) is not str:
            raise ValueError(f"capture function_identity {field} must be string")
    aliases = identity.get("aliases")
    if (
        type(aliases) is not list
        or any(type(alias) is not str or not alias for alias in aliases)
        or len(aliases) != len(set(aliases))
    ):
        raise ValueError(
            "capture function_identity aliases must be canonical unique strings"
        )
    if identity.get("requested") != function:
        raise ValueError(
            f"capture requested function mismatch: {identity.get('requested')!r} != {function!r}"
        )
    return True


def _validate_attempt(attempt: object, *, function: str) -> str:
    if type(attempt) is not dict:
        raise ValueError("capture_attempt must be an object")
    if set(attempt) != {"capture_attempt_id", "function_identity"}:
        raise ValueError("capture_attempt fields differ from exact schema")
    attempt_id = attempt.get("capture_attempt_id")
    if not (
        type(attempt_id) is str
        and len(attempt_id) == 32
        and all(character in "0123456789abcdef" for character in attempt_id)
    ):
        raise ValueError("capture attempt ID must be 32 lowercase hex characters")
    _attempt_identifies_function(attempt, function)
    return attempt_id


def load_correlated_v2_sidecars(
    object_path: Path,
    pcode_path: Path,
    *,
    function: str,
) -> CorrelatedV2Sidecars:
    """Load only atomically published object/PCode evidence from one attempt."""

    object_payload = _load_sidecar(
        object_path,
        schema_version="mwcc-retro-object-events.v1",
        label="object",
    )
    pcode_payload = _load_sidecar(
        pcode_path,
        schema_version="mwcc-retro-pcode-events.v1",
        label="PCode",
    )
    object_attempt = object_payload["capture_attempt"]
    pcode_attempt = pcode_payload["capture_attempt"]
    object_attempt_id = _validate_attempt(object_attempt, function=function)
    pcode_attempt_id = _validate_attempt(pcode_attempt, function=function)
    if object_attempt != pcode_attempt:
        raise ValueError("object/PCode capture attempt mismatch")
    if object_attempt_id != pcode_attempt_id:
        raise ValueError("object/PCode capture attempt ID mismatch")
    return CorrelatedV2Sidecars(
        object_attempt_id, object_payload, pcode_payload
    )


_OBJECT_RECORD_EVENTS = {
    "lifecycle_record": "lifecycle_events",
    "object_record": "objects",
    "virtual_binding_record": "virtual_bindings",
    "frame_binding_record": "frame_bindings",
}
_PCODE_RECORD_EVENTS = {
    "pcode_instruction_record": "pcode_instructions",
    "pcode_occurrence_record": "pcode_occurrences",
    "pcode_lineage_record": "pcode_operand_lineage_events",
}


def _derive_sidecar_object_bindings(
    sidecars: CorrelatedV2Sidecars,
) -> dict[str, Any]:
    proof: object | None = None
    coverage: object | None = None
    collections: dict[str, list[object]] = {
        "lifecycle_events": [],
        "objects": [],
        "virtual_bindings": [],
        "frame_bindings": [],
        "pcode_instructions": [],
        "pcode_occurrences": [],
        "pcode_operand_lineage_events": [],
    }

    for label, payload, record_events in (
        ("object", sidecars.object_payload, _OBJECT_RECORD_EVENTS),
        ("PCode", sidecars.pcode_payload, _PCODE_RECORD_EVENTS),
    ):
        for index, event in enumerate(payload["events"]):
            if type(event) is not dict:
                raise ValueError(f"{label} sidecar event {index} must be object")
            kind = event.get("event")
            if label == "object" and kind == "lifetime_proof":
                if set(event) != {"event", "proof"} or proof is not None:
                    raise ValueError("object sidecar lifetime_proof event is malformed or duplicated")
                proof = event["proof"]
                continue
            if label == "object" and kind == "coverage":
                if set(event) != {"event", "coverage"} or coverage is not None:
                    raise ValueError("object sidecar coverage event is malformed or duplicated")
                coverage = event["coverage"]
                continue
            collection = record_events.get(kind)
            if collection is None:
                raise ValueError(f"unsupported {label} v2 raw sidecar event {kind!r}")
            if set(event) != {"event", "record"} or type(event.get("record")) is not dict:
                raise ValueError(f"{label} sidecar {kind} event must contain one record")
            collections[collection].append(event["record"])

    if proof is None:
        raise ValueError("object sidecar missing lifetime_proof raw family")
    if coverage is None:
        raise ValueError("object sidecar missing coverage raw family")
    return {
        "schema_version": "mwcc-retro-object-bindings.v1",
        "lifetime_proof": proof,
        "coverage": coverage,
        **collections,
        "source_bindings": [],
        "source_capture": None,
    }


def _find_v2_bindings(trace: dict[str, Any], function: str) -> dict[str, Any]:
    functions = trace.get("functions")
    matches = [
        row
        for row in functions
        if type(row) is dict and row.get("name") == function
    ] if type(functions) is list else []
    if len(matches) != 1 or type(matches[0].get("object_bindings")) is not dict:
        raise ValueError(f"expected one v2 object_bindings function {function!r}")
    return matches[0]["object_bindings"]


def _verify_backend_trace_v2_components(
    trace: object,
    *,
    candidate_bytes: bytes,
    function: str,
    struct_map: object,
) -> tuple[dict[str, Any], frozenset[str]]:
    from tools.mwcc_retro import backend_schema
    from tools.mwcc_retro import struct_map as struct_map_validation
    from tools.mwcc_retro.backend_capture_identity import (
        finalize_capture_identity_from_bytes,
    )
    from tools.mwcc_retro.backend_instrumentation_proof import trusted_proof_from_trace
    from tools.mwcc_retro.backend_object_bindings import validate_object_bindings
    from tools.mwcc_retro.backend_pcode_lineage import validate_pcode_lineage

    try:
        detached = struct_map_validation.materialize_json_safe(trace)
        detached_struct_map = struct_map_validation.materialize_json_safe(struct_map)
    except Exception as exc:
        raise ValueError(f"backend trace v2 trust materialization failed: {exc}") from exc
    if type(detached) is not dict:
        raise ValueError("backend trace v2 must be object")
    if type(candidate_bytes) is not bytes or not candidate_bytes:
        raise ValueError("candidate bytes must be nonempty exact bytes")
    schema_errors = backend_schema.validate_backend_trace(detached)
    if schema_errors:
        raise ValueError("backend trace v2 schema errors: " + "; ".join(schema_errors))

    bindings = _find_v2_bindings(detached, function)
    identity = bindings["capture_identity"]
    recomputed_identity = finalize_capture_identity_from_bytes(
        nonce=identity["nonce"],
        compiler_executable_sha256=identity["compiler_executable_sha256"],
        source_sha256=identity["source_sha256"],
        mwcc_command_sha256=identity["mwcc_command_sha256"],
        environment_digest=identity["environment_digest"],
        function=function,
        candidate_object_bytes=candidate_bytes,
    )
    if identity != recomputed_identity or bindings.get("capture_run_id") != recomputed_identity["capture_run_id"]:
        raise ValueError("capture identity does not match exact candidate bytes and pins")

    object_gate_errors = struct_map_validation.validate_object_capture_capability(
        detached_struct_map
    )
    if object_gate_errors:
        raise ValueError(
            "object capture gate failed: " + "; ".join(object_gate_errors)
        )
    proof_payload = bindings.get("lifetime_proof")
    pcode_gate_errors = struct_map_validation.validate_pcode_instrumentation_capability(
        detached_struct_map,
        proof=proof_payload if type(proof_payload) is dict else None,
    )
    if pcode_gate_errors:
        raise ValueError(
            "backend trace v2 proof gate failed: " + "; ".join(pcode_gate_errors)
        )
    proof = trusted_proof_from_trace(detached, function, detached_struct_map)
    object_result = validate_object_bindings(bindings, proof)
    if object_result.errors:
        raise ValueError(
            "object binding validation failed: " + "; ".join(object_result.errors)
        )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".o", delete=False) as stream:
            temporary_path = Path(stream.name)
            stream.write(candidate_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        lineage_result = validate_pcode_lineage(
            bindings, proof, temporary_path, function
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    if lineage_result.errors:
        raise ValueError(
            "PCode lineage validation failed: " + "; ".join(lineage_result.errors)
        )
    supported = frozenset(
        {
            "compiler-object-bindings",
            "object-to-virtual",
            "object-to-frame",
            "pcode-to-code-range",
        }
    )
    return detached, frozenset(
        (object_result.capabilities | lineage_result.capabilities) & supported
    )


def verify_backend_trace_v2(
    trace: object,
    *,
    candidate_bytes: bytes,
    function: str,
    struct_map: object,
) -> BackendTraceV2Verification:
    """Independently revalidate one detached trace/candidate pair."""

    detached, capabilities = _verify_backend_trace_v2_components(
        trace,
        candidate_bytes=candidate_bytes,
        function=function,
        struct_map=struct_map,
    )
    if detached.get("capabilities") != sorted(capabilities):
        raise ValueError(
            "payload capabilities do not equal independently verified capabilities"
        )
    return BackendTraceV2Verification(detached, capabilities)


def assemble_candidate_trace_v2(
    *,
    base_trace: dict[str, Any],
    object_bindings: dict[str, Any],
    object_sidecar: Path,
    pcode_sidecar: Path,
    candidate_object: Path,
    compiler_executable_sha256: str,
    source_sha256: str,
    mwcc_command_sha256: str,
    environment_digest: str,
    function: str,
    struct_map: object,
) -> BackendTraceV2Assembly:
    """Assemble one complete proof-bearing trace and independently validate it."""

    from tools.mwcc_retro import backend_schema
    from tools.mwcc_retro.backend_capture_identity import (
        finalize_capture_identity_from_bytes,
    )

    legacy_errors = backend_schema.validate_backend_trace(base_trace)
    if legacy_errors:
        raise ValueError("base backend trace validation failed: " + "; ".join(legacy_errors))
    if base_trace.get("schema_version") != backend_schema.SCHEMA_VERSION_V1:
        raise ValueError("v2 assembly requires a validated v1 base trace")
    candidate_path = Path(candidate_object)
    candidate_bytes = candidate_path.read_bytes()
    if not candidate_bytes:
        raise ValueError("candidate object is empty")

    sidecars = load_correlated_v2_sidecars(
        object_sidecar, pcode_sidecar, function=function
    )
    try:
        derived = backend_events.canonicalize_v2_object_bindings(
            _derive_sidecar_object_bindings(sidecars)
        )
        supplied = copy.deepcopy(object_bindings)
        supplied.pop("capture_identity", None)
        supplied.pop("capture_run_id", None)
        supplied = backend_events.canonicalize_v2_object_bindings(supplied)
    except RecursionError as exc:
        raise ValueError(
            "sidecar binding derivation exceeds the supported nesting limit"
        ) from exc
    if supplied != derived:
        raise ValueError("sidecar-derived object_bindings mismatch")

    # The sidecar attempt is the capture nonce. Identity is finalized only
    # after one detached read of the exact candidate bytes and all outer pins.
    identity = finalize_capture_identity_from_bytes(
        nonce=sidecars.capture_attempt_id,
        compiler_executable_sha256=compiler_executable_sha256,
        source_sha256=source_sha256,
        mwcc_command_sha256=mwcc_command_sha256,
        environment_digest=environment_digest,
        function=function,
        candidate_object_bytes=candidate_bytes,
    )
    bindings = derived
    bindings["capture_identity"] = identity
    bindings["capture_run_id"] = identity["capture_run_id"]
    bindings = backend_events.canonicalize_v2_object_bindings(bindings)

    trace = copy.deepcopy(base_trace)
    trace["schema_version"] = backend_schema.SCHEMA_VERSION_V2
    trace["capabilities"] = []
    trace["compiler"]["executable_sha256"] = compiler_executable_sha256
    trace["source"].update(
        {
            "source_sha256": source_sha256,
            "mwcc_command_sha256": mwcc_command_sha256,
            "environment_digest": environment_digest,
        }
    )
    matches = [row for row in trace.get("functions", []) if isinstance(row, dict) and row.get("name") == function]
    if len(matches) != 1:
        raise ValueError(f"expected one function {function!r}, found {len(matches)}")
    matches[0]["object_bindings"] = bindings

    _detached, capabilities = _verify_backend_trace_v2_components(
        trace,
        candidate_bytes=candidate_bytes,
        function=function,
        struct_map=struct_map,
    )
    trace["capabilities"] = sorted(capabilities)
    verified = verify_backend_trace_v2(
        trace,
        candidate_bytes=candidate_bytes,
        function=function,
        struct_map=struct_map,
    )
    return BackendTraceV2Assembly(verified.payload, verified.capabilities)


def assemble_candidate_trace(
    *,
    pcode_events: list[dict[str, Any]],
    ig_events: list[dict[str, Any]],
    frame_events: list[dict[str, Any]],
    colorgraph_events: list[dict[str, Any]],
    compiler: dict[str, Any],
    source: dict[str, Any],
    tool_version: str,
) -> dict[str, Any]:
    """Return a schema-valid trace candidate from partial probe event families.

    This is an offline combiner for already-validated probe outputs. It is not
    the public retail backend tracer: leftover post-return partial color
    decisions are rejected so a candidate trace cannot masquerade as allocator
    replay when exact internal colorgraph facts are missing.
    """

    if not any(event.get("event") == "frame_state" for event in frame_events):
        raise ValueError("candidate trace requires frame_state")

    expected_function = _expected_function_name(source)
    _validate_function_starts(
        expected_function,
        pcode_events=pcode_events,
        ig_events=ig_events,
        colorgraph_events=colorgraph_events,
    )

    exact_by_key: dict[tuple[str, int, int], dict[str, Any]] = {}
    for event in colorgraph_events:
        if not _is_exact_color_decision(event):
            continue
        key = _decision_key(event)
        if key in exact_by_key:
            raise ValueError(f"duplicate exact color decision {key!r}")
        exact_by_key[key] = event

    merged_ig_events: list[dict[str, Any]] = []
    leftover_partials: list[tuple[str, int, int]] = []
    for event in ig_events:
        if _is_partial_color_decision(event):
            key = _decision_key(event)
            exact = exact_by_key.get(key)
            if exact is not None:
                if exact.get("assigned_phys") != event.get("assigned_phys"):
                    raise ValueError(
                        "exact/partial assigned_phys mismatch for "
                        f"{key!r}: {exact.get('assigned_phys')!r} != "
                        f"{event.get('assigned_phys')!r}"
                    )
                continue
            leftover_partials.append(key)
        merged_ig_events.append(event)
    if leftover_partials:
        pretty = ", ".join(
            f"{class_name}:{class_id}:{ig_id}"
            for class_name, class_id, ig_id in leftover_partials
        )
        raise ValueError(f"leftover partial color decisions: {pretty}")

    exact_decisions = list(exact_by_key.values())
    events = [
        *pcode_events,
        *merged_ig_events,
        *frame_events,
        *exact_decisions,
    ]
    return backend_events.normalize_events(
        events,
        compiler=compiler,
        source=source,
        tool_version=tool_version,
    )


def _expected_function_name(source: dict[str, Any]) -> str:
    function = source.get("function")
    if not isinstance(function, str) or not function:
        raise ValueError("source missing function")
    return function


def _validate_function_starts(
    expected: str,
    *,
    pcode_events: list[dict[str, Any]],
    ig_events: list[dict[str, Any]],
    colorgraph_events: list[dict[str, Any]],
) -> None:
    for label, events in (
        ("pcode", pcode_events),
        ("ig", ig_events),
        ("colorgraph", colorgraph_events),
    ):
        starts = [
            event.get("name")
            for event in events
            if event.get("event") == "function_start"
        ]
        if not starts:
            continue
        for name in starts:
            if name != expected:
                raise ValueError(
                    f"{label} function_start mismatch: {name!r} != {expected!r}"
                )


def frame_events_from_map_probe_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert ``backend-map-probe.json`` frame evidence into frame_state events."""

    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("map probe payload missing events")
    out: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        stage = event.get("stage")
        frame = event.get("frame_state")
        if stage not in {"final_scheduler", "codegen_end"} or not isinstance(frame, dict):
            continue
        out.append(_frame_event_from_probe_frame(frame, source_stage=str(stage)))
    if not out:
        raise ValueError("map probe payload contains no frame_state samples")
    return out


def _frame_event_from_probe_frame(
    frame: dict[str, Any], *, source_stage: str
) -> dict[str, Any]:
    base_size = _probe_s32(frame, "frame_base_size")
    call_args_size = _probe_s32(frame, "frame_call_args_size")
    objects: list[dict[str, Any]] = []
    for area in FRAME_AREAS:
        area_state = frame.get(area)
        if not isinstance(area_state, dict):
            continue
        samples = area_state.get("objects_sample")
        if not isinstance(samples, list):
            continue
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            if "error" in sample:
                raise ValueError(f"{area} frame object sample error: {sample['error']}")
            name = sample.get("name")
            stack_offset = sample.get("stack_offset")
            size = sample.get("size")
            if not isinstance(stack_offset, int):
                raise ValueError(f"{area} frame object missing stack_offset")
            if not isinstance(size, int):
                raise ValueError(f"{area} frame object missing size")
            confidence = "observed"
            if not isinstance(name, str) or not name:
                name = f"{area}_slot_{stack_offset}"
                confidence = "observed-unnamed"
            obj = {
                "area": area,
                "name": name,
                "stack_offset": stack_offset,
                "size": size,
                "confidence": confidence,
                "provenance": f"frame_{area}",
            }
            type_ptr = sample.get("type")
            if isinstance(type_ptr, int) and type_ptr > 0:
                obj["type"] = f"type@0x{type_ptr:x}"
            objects.append(obj)
    return {
        "event": "frame_state",
        "source_stage": source_stage,
        "provenance": "backend-map-probe-frame_state",
        "base_size_bytes": base_size,
        "call_args_size_bytes": call_args_size,
        "objects": objects,
    }


def _probe_s32(frame: dict[str, Any], key: str) -> int:
    value = frame.get(key)
    if not isinstance(value, dict) or not isinstance(value.get("s32"), int):
        raise ValueError(f"missing {key}")
    if value["s32"] < 0:
        raise ValueError(f"negative {key} {value['s32']}")
    return value["s32"]


def _decision_key(event: dict[str, Any]) -> tuple[str, int, int]:
    class_name = event.get("class_name")
    class_id = event.get("class_id")
    ig_id = event.get("ig_id")
    if not isinstance(class_name, str) or not isinstance(class_id, int) or not isinstance(ig_id, int):
        raise ValueError(f"malformed color decision identity: {event!r}")
    return class_name, class_id, ig_id


def _is_partial_color_decision(event: dict[str, Any]) -> bool:
    return (
        event.get("event") == "color_decision"
        and (
            event.get("confidence") == "observed-partial"
            or event.get("provenance") == "retail-colorgraph-return"
        )
    )


def _is_exact_color_decision(event: dict[str, Any]) -> bool:
    return (
        event.get("event") == "color_decision"
        and event.get("confidence") == "observed-internal"
        and event.get("provenance") == "retail-colorgraph-internal"
    )
