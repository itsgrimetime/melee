"""Assemble candidate backend traces from validated partial probe events."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.mwcc_retro import backend_events

FRAME_AREAS = ("locals", "arguments", "temps")


@dataclass(frozen=True, slots=True)
class BackendTraceV2Assembly:
    payload: dict[str, Any]
    capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class CorrelatedV2Sidecars:
    capture_attempt_id: str
    object_payload: dict[str, Any]
    pcode_payload: dict[str, Any]


def _load_sidecar(path: Path, *, schema_version: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} sidecar could not be read: {type(exc).__name__}") from exc
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
    if type(identity) is not dict:
        return False
    names = {
        identity.get(field)
        for field in ("requested", "canonical_name", "symbol_name", "source_name")
        if type(identity.get(field)) is str
    }
    aliases = identity.get("aliases")
    if type(aliases) is list:
        names.update(alias for alias in aliases if type(alias) is str)
    return function in names


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
    if object_attempt != pcode_attempt:
        raise ValueError("object/PCode capture attempt mismatch")
    attempt_id = object_attempt.get("capture_attempt_id")
    if not (
        type(attempt_id) is str
        and len(attempt_id) == 32
        and all(character in "0123456789abcdef" for character in attempt_id)
    ):
        raise ValueError("capture attempt ID must be 32 lowercase hex characters")
    if not _attempt_identifies_function(object_attempt, function):
        raise ValueError(f"capture attempt does not identify function {function!r}")
    return CorrelatedV2Sidecars(attempt_id, object_payload, pcode_payload)


def assemble_candidate_trace_v2(
    *,
    base_trace: dict[str, Any],
    object_bindings: dict[str, Any],
    candidate_object: Path,
    nonce: str,
    compiler_executable_sha256: str,
    source_sha256: str,
    mwcc_command_sha256: str,
    environment_digest: str,
    function: str,
    struct_map: object,
) -> BackendTraceV2Assembly:
    """Assemble one complete proof-bearing trace and independently validate it."""

    from tools.mwcc_retro import backend_schema
    from tools.mwcc_retro import struct_map as struct_map_validation
    from tools.mwcc_retro.backend_capture_identity import finalize_capture_identity
    from tools.mwcc_retro.backend_instrumentation_proof import trusted_proof_from_trace
    from tools.mwcc_retro.backend_object_bindings import validate_object_bindings
    from tools.mwcc_retro.backend_pcode_lineage import validate_pcode_lineage

    legacy_errors = backend_schema.validate_backend_trace(base_trace)
    if legacy_errors:
        raise ValueError("base backend trace validation failed: " + "; ".join(legacy_errors))
    if base_trace.get("schema_version") != backend_schema.SCHEMA_VERSION_V1:
        raise ValueError("v2 assembly requires a validated v1 base trace")
    candidate_path = Path(candidate_object)
    candidate_bytes = candidate_path.read_bytes()
    if not candidate_bytes:
        raise ValueError("candidate object is empty")

    # The run ID cannot exist until all compile pins and the exact raw object
    # bytes are final. No producer status field participates in this identity.
    identity = finalize_capture_identity(
        nonce=nonce,
        compiler_executable_sha256=compiler_executable_sha256,
        source_sha256=source_sha256,
        mwcc_command_sha256=mwcc_command_sha256,
        environment_digest=environment_digest,
        function=function,
        candidate_object=candidate_path,
    )
    bindings = copy.deepcopy(object_bindings)
    bindings["capture_identity"] = identity
    bindings["capture_run_id"] = identity["capture_run_id"]
    bindings = backend_events.canonicalize_v2_object_bindings(bindings)

    trace = copy.deepcopy(base_trace)
    trace["schema_version"] = backend_schema.SCHEMA_VERSION_V2
    trace["capabilities"] = []
    matches = [row for row in trace.get("functions", []) if isinstance(row, dict) and row.get("name") == function]
    if len(matches) != 1:
        raise ValueError(f"expected one function {function!r}, found {len(matches)}")
    matches[0]["object_bindings"] = bindings

    proof_payload = bindings.get("lifetime_proof")
    gate_errors = struct_map_validation.validate_pcode_instrumentation_capability(
        struct_map,
        proof=proof_payload if isinstance(proof_payload, dict) else None,
    )
    if gate_errors:
        raise ValueError("backend trace v2 proof gate failed: " + "; ".join(gate_errors))
    proof = trusted_proof_from_trace(trace, function, struct_map)

    object_result = validate_object_bindings(bindings, proof)
    if object_result.errors:
        raise ValueError("object binding validation failed: " + "; ".join(object_result.errors))
    lineage_result = validate_pcode_lineage(bindings, proof, candidate_path, function)
    if lineage_result.errors:
        raise ValueError("PCode lineage validation failed: " + "; ".join(lineage_result.errors))

    independently_verified = object_result.capabilities | lineage_result.capabilities
    supported = frozenset(
        {
            "compiler-object-bindings",
            "object-to-virtual",
            "object-to-frame",
            "pcode-to-code-range",
        }
    )
    capabilities = frozenset(independently_verified & supported)
    trace["capabilities"] = sorted(capabilities)
    schema_errors = backend_schema.validate_backend_trace(trace)
    if schema_errors:
        raise ValueError("backend trace v2 schema validation failed: " + "; ".join(schema_errors))
    return BackendTraceV2Assembly(trace, capabilities)


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
