"""Assemble candidate backend traces from validated partial probe events."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.mwcc_retro import backend_events
from tools.mwcc_retro.backend_instrumentation_proof import (
    classify_operand,
    expand_operand_descriptors,
    resolve_operand_role,
)

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


def _opcode_name(proof: Mapping[str, object], opcode_id: int) -> str:
    rows = proof.get("opcode_table")
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping) and row.get("opcode_id") == opcode_id
    ] if isinstance(rows, list) else []
    if len(matches) != 1 or not isinstance(matches[0].get("mnemonic"), str):
        raise ValueError(f"opcode {opcode_id} has no unique proof mnemonic")
    return str(matches[0]["mnemonic"])


def _lineage_snapshot(
    state: Mapping[str, object],
    proof: Mapping[str, object],
    stage: str,
) -> dict[str, object]:
    opcode_id = state.get("opcode_id")
    arg_count = state.get("arg_count")
    inventory = state.get("operand_lineage_inventory", state.get("operands"))
    if type(opcode_id) is not int or type(arg_count) is not int:
        raise ValueError("PCode snapshot opcode/arg count is malformed")
    if not isinstance(inventory, list) or len(inventory) != arg_count:
        raise ValueError("PCode snapshot operand inventory is incomplete")
    descriptors = expand_operand_descriptors(proof, opcode_id, arg_count)
    parsed: list[dict[str, object]] = []
    for index, (operand, descriptor) in enumerate(
        zip(inventory, descriptors, strict=True)
    ):
        if not isinstance(operand, Mapping):
            raise ValueError(f"PCode operand {index} is malformed")
        if operand.get("raw_arg_kind_id") != descriptor.raw_arg_kind_id:
            raise ValueError(f"PCode operand {index} kind differs from proof")
        if not descriptor.state_rules:
            continue
        flags = operand.get("raw_register_flags")
        value = operand.get("raw_register_value")
        if type(flags) is not int or type(value) is not int:
            raise ValueError(f"PCode operand {index} register state is malformed")
        role = resolve_operand_role(descriptor, flags)
        classified = classify_operand(descriptor, stage, flags, value)
        parsed.append(
            {
                "operand_index": index,
                "role": role,
                "class_id": descriptor.class_id,
                "raw_arg_kind_id": operand["raw_arg_kind_id"],
                "raw_register_flags": flags,
                "raw_register_value": value,
                "allocation_state": classified.allocation_state,
                "register_form": descriptor.register_form,
                "operand_lineage_id": operand["operand_lineage_id"],
                "virtual_kind": (
                    descriptor.virtual_kind
                    if classified.allocation_state == "virtual"
                    else None
                ),
                "virtual": classified.virtual,
                "physical_register": classified.physical_register,
            }
        )
    return {
        "stage": stage,
        "lifecycle_sequence_at_capture": state[
            "lifecycle_sequence_at_capture"
        ],
        "runtime_address": state["runtime_address"],
        "allocation_generation": state["allocation_generation"],
        "opcode_id": opcode_id,
        "opcode": _opcode_name(proof, opcode_id),
        "arg_count": arg_count,
        "parsed_register_operands": parsed,
        "operand_lineage_inventory": copy.deepcopy(inventory),
    }


def _candidate_view(candidate_object: Path | None, function: str):
    if candidate_object is None:
        return None
    from tools.mwcc_retro.backend_pcode_lineage import _load_object

    return _load_object(Path(candidate_object), function)


def _bind_candidate_ranges(
    ranges: object,
    view: object | None,
) -> list[dict[str, object]]:
    if not isinstance(ranges, list):
        raise ValueError("emission code ranges must be list")
    result = copy.deepcopy(ranges)
    if view is None:
        return result
    for row in result:
        if not isinstance(row, dict):
            raise ValueError("emission code range is malformed")
        start = row.get("start")
        end = row.get("end_exclusive")
        if type(start) is not int or type(end) is not int or start >= end:
            raise ValueError("emission code range bounds are malformed")
        expected = view.section_data[
            view.symbol_start + start : view.symbol_start + end
        ]
        if row.get("bytes") != expected.hex():
            raise ValueError("runtime emission bytes differ from candidate object")
        row["relocations"] = [
            {
                "offset_within_range": offset - view.symbol_start - start,
                "relocation_type_id": kind,
                "target_symbol_table_index": symbol_index,
                "target_symbol": target,
                "addend": addend,
            }
            for offset, kind, symbol_index, target, addend in view.relocations
            if view.symbol_start + start <= offset < view.symbol_start + end
        ]
    return result


def assemble_pcode_lineage_payload(
    *,
    snapshot_events: list[dict[str, Any]],
    runtime_status: Mapping[str, object],
    proof: Mapping[str, object],
    function: str,
    candidate_object: Path | None = None,
    section_name: str = ".text",
    max_pcode_instructions: int = 4096,
    max_pcode_operands_per_instruction: int = 64,
) -> dict[str, object]:
    """Serialize proof-bound snapshot/runtime rows for closed lineage replay."""

    if runtime_status.get("status") != "validated":
        raise ValueError("runtime instrumentation is not validated")
    if runtime_status.get("errors") != []:
        raise ValueError("runtime instrumentation contains errors")
    if runtime_status.get("truncated") is not False or runtime_status.get(
        "dropped_events"
    ) != 0:
        raise ValueError("runtime instrumentation is truncated or dropped events")
    runtime_events = runtime_status.get("pcode_events")
    lifecycle_events = runtime_status.get("lifecycle_events")
    if not isinstance(runtime_events, list) or not isinstance(
        lifecycle_events, list
    ):
        raise ValueError("runtime event inventories are malformed")
    sequences = [
        row.get("pcode_event_sequence")
        for row in runtime_events
        if isinstance(row, Mapping)
    ]
    if len(sequences) != len(runtime_events) or sequences != list(
        range(len(runtime_events))
    ):
        raise ValueError("runtime PCode event sequence is not gap-free")
    if type(max_pcode_instructions) is not int or max_pcode_instructions <= 0:
        raise ValueError("max_pcode_instructions must be positive")
    if (
        type(max_pcode_operands_per_instruction) is not int
        or max_pcode_operands_per_instruction <= 0
    ):
        raise ValueError("max_pcode_operands_per_instruction must be positive")

    block_orders = {
        row.get("id"): row.get("order")
        for row in snapshot_events
        if row.get("event") == "block"
    }
    first_states: dict[str, tuple[dict[str, object], int, int, str]] = {}
    for row in snapshot_events:
        if row.get("event") != "pcode_instruction":
            continue
        pcode_id = row.get("pcode_id")
        if not isinstance(pcode_id, str) or not pcode_id:
            raise ValueError("snapshot PCode instruction has no bound pcode_id")
        state = {
            "runtime_address": row.get("runtime_address"),
            "allocation_generation": row.get("allocation_generation"),
            "lifecycle_sequence_at_capture": row.get(
                "lifecycle_sequence_at_capture"
            ),
            "opcode_id": row.get("opcode_id"),
            "arg_count": row.get("arg_count"),
            "operand_lineage_inventory": row.get(
                "operand_lineage_inventory"
            ),
        }
        first_states[pcode_id] = (
            state,
            int(block_orders.get(row.get("block_id"), 0)),
            int(row.get("order", 0)),
            "allocator_input",
        )
    for event in runtime_events:
        if not isinstance(event, Mapping) or event.get("event") != "pcode_mutation":
            continue
        for state in event.get("outputs", []):
            if not isinstance(state, dict):
                continue
            pcode_id = state.get("pcode_id")
            if isinstance(pcode_id, str) and pcode_id not in first_states:
                first_states[pcode_id] = (
                    state,
                    0,
                    len(first_states),
                    "mutation_output",
                )
    if len(first_states) >= max_pcode_instructions:
        raise ValueError("PCode instruction cap reached")

    emission_by_id = {
        event.get("pcode_id"): event
        for event in runtime_events
        if isinstance(event, Mapping) and event.get("event") == "code_emission"
    }
    view = _candidate_view(candidate_object, function)
    effective_section = view.section_name if view is not None else section_name
    instructions: list[dict[str, object]] = []
    first_parsed: list[dict[str, object]] = []
    for pcode_id, (state, block_order, order, stage) in sorted(
        first_states.items(), key=lambda item: (item[1][1], item[1][2], item[0])
    ):
        initial = _lineage_snapshot(state, proof, stage)
        if int(initial["arg_count"]) >= max_pcode_operands_per_instruction:
            raise ValueError("PCode operand cap reached")
        first_parsed.extend(initial["parsed_register_operands"])
        emission = emission_by_id.get(pcode_id)
        snapshots = [initial]
        if isinstance(emission, Mapping):
            snapshots.append(copy.deepcopy(emission["emission_snapshot"]))
            code_ranges = _bind_candidate_ranges(emission["code_ranges"], view)
            emission_sequence = emission["pcode_event_sequence"]
            emission_site = emission["instrumented_site_id"]
            emission_address = emission["runtime_address"]
            emission_generation = emission["allocation_generation"]
            emission_lifecycle = emission["lifecycle_sequence_at_capture"]
        else:
            code_ranges = []
            emission_sequence = None
            emission_site = None
            emission_address = None
            emission_generation = None
            emission_lifecycle = None
        instructions.append(
            {
                "pcode_id": pcode_id,
                "runtime_address": state["runtime_address"],
                "allocation_generation": state["allocation_generation"],
                "block_order": block_order,
                "instruction_order": order,
                "function_symbol": function,
                "section_name": effective_section,
                "coordinate_space": "function-relative-bytes",
                "stage_snapshots": snapshots,
                "emission_event_sequence": emission_sequence,
                "emission_site_id": emission_site,
                "emission_runtime_address": emission_address,
                "emission_allocation_generation": emission_generation,
                "emission_lifecycle_sequence_at_capture": emission_lifecycle,
                "code_ranges": code_ranges,
                "cross_stage_identity_confidence": "derived-unique",
            }
        )

    rewrites = [
        copy.deepcopy(row)
        for row in runtime_events
        if isinstance(row, Mapping) and row.get("event") == "operand_rewrite"
    ]
    mutations = [
        copy.deepcopy(row)
        for row in runtime_events
        if isinstance(row, Mapping) and row.get("event") == "pcode_mutation"
    ]
    for row in rewrites + mutations:
        row.pop("event", None)
    current = set(first_states)
    for mutation in mutations:
        current.difference_update(
            str(row.get("pcode_id"))
            for row in mutation.get("inputs", [])
            if isinstance(row, Mapping)
        )
        current.update(
            str(row.get("pcode_id"))
            for row in mutation.get("outputs", [])
            if isinstance(row, Mapping)
        )
    expected_ids = set(runtime_status.get("expected_site_ids", ()))
    installed_ids = set(runtime_status.get("installed_site_ids", ()))
    family_counts = {
        name: len(proof.get(name, []))
        for name in (
            "operand_rewrite_sites",
            "operand_mutation_sites",
            "code_emission_sites",
        )
    }
    first_sequence = 0 if runtime_events else -1
    pcode_coverage = {
        "status": "complete",
        "operand_rewrite_sites_expected": family_counts[
            "operand_rewrite_sites"
        ],
        "operand_rewrite_sites_hooked": len(
            installed_ids
            & {
                row["site_id"]
                for row in proof["operand_rewrite_sites"]
            }
        ),
        "operand_mutation_sites_expected": family_counts[
            "operand_mutation_sites"
        ],
        "operand_mutation_sites_hooked": len(
            installed_ids
            & {
                row["site_id"]
                for row in proof["operand_mutation_sites"]
            }
        ),
        "code_emission_sites_expected": family_counts["code_emission_sites"],
        "code_emission_sites_hooked": len(
            installed_ids
            & {row["site_id"] for row in proof["code_emission_sites"]}
        ),
        "first_event_sequence": first_sequence,
        "last_event_sequence": len(runtime_events) - 1,
        "parsed_register_operands": len(first_parsed),
        "virtual_register_operands": sum(
            row["allocation_state"] == "virtual" for row in first_parsed
        ),
        "physical_register_operands": sum(
            row["allocation_state"] == "physical" for row in first_parsed
        ),
        "non_allocator_register_operands": sum(
            row["allocation_state"] == "non-allocator" for row in first_parsed
        ),
        "rewrite_events": len(rewrites),
        "mutation_events": len(mutations),
        "final_pcodes": len(current),
        "emission_events": len(emission_by_id),
        "event_cap": runtime_status["event_cap"],
        "dropped_events": runtime_status["dropped_events"],
        "truncated": runtime_status["truncated"],
        "errors": [],
    }
    if expected_ids != installed_ids:
        raise ValueError("runtime expected/installed site inventories differ")
    return {
        "lifecycle_events": copy.deepcopy(lifecycle_events),
        "coverage": {
            "pcode_instrumentation": pcode_coverage,
            "pcode_instructions_seen": len(instructions),
            "pcode_occurrences_seen": len(rewrites),
            "caps": {
                "max_pcode_instructions": max_pcode_instructions,
                "max_pcode_operands_per_instruction": (
                    max_pcode_operands_per_instruction
                ),
            },
            "truncated": False,
            "errors": [],
        },
        "pcode_instructions": instructions,
        "pcode_occurrences": rewrites,
        "pcode_operand_lineage_events": mutations,
    }
