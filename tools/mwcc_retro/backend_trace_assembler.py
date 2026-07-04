"""Assemble candidate backend traces from validated partial probe events."""
from __future__ import annotations

from typing import Any

from tools.mwcc_retro import backend_events


FRAME_AREAS = ("locals", "arguments", "temps")


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
