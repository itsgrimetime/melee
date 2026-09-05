"""Classify backend-map probe payloads into promotable live evidence."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tools.mwcc_retro.struct_map import (
    REQUIRED_GC125N_BACKEND_KEYS,
    REQUIRED_STRUCT_FIELDS,
)

LIVE_CONFIDENCE = "live-invariant"

STAGE_ENTRY_KEYS = {
    "codegen_start",
    "codegen_end",
    "pcode_pass_boundary",
    "build_interference_matrix",
    "real_coalesce",
    "build_adjacency_vectors",
    "simplifygraph",
    "colorgraph",
    "final_scheduler",
}

GLOBAL_ENTRY_KEYS = {
    "pcbasicblocks",
    "interference_matrix",
    "coalesce_alias",
}

IG_BACKED_GLOBAL_KEYS = {
    "interferencegraph",
    "n_ignodes",
}

USED_VREG_CLASSES = {
    "used_vreg_gpr": 0,
    "used_vreg_fpr": 1,
}

IG_SAMPLE_STAGES = {
    "simplifygraph",
    "colorgraph",
    "final_scheduler",
    "codegen_end",
}

BLOCK_SAMPLE_STAGES = {
    "build_interference_graph_wrapper",
    "dataflow_marker",
    "build_interference_matrix",
    "real_coalesce",
    "build_adjacency_vectors",
    "simplifygraph",
    "colorgraph",
    "final_scheduler",
    "codegen_end",
}

POINTER_LIMIT_LOW = 0x600000
POINTER_LIMIT_HIGH = 0x2000000
IGNODE_LIMIT = 2048


def _block_all(reason: str) -> dict[str, Any]:
    return {
        "promotable_entries": {},
        "blocked_entries": {
            key: {"reason": reason} for key in REQUIRED_GC125N_BACKEND_KEYS
        },
        "promotable_structs": {},
        "blocked_structs": {
            name: {"reason": reason} for name in REQUIRED_STRUCT_FIELDS
        },
    }


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and value > 0


def _is_bounded_pointer(value: Any) -> bool:
    return isinstance(value, int) and POINTER_LIMIT_LOW <= value < POINTER_LIMIT_HIGH


def _event_globals(event: Mapping[str, Any]) -> Mapping[str, Any]:
    globals_ = event.get("globals")
    if isinstance(globals_, Mapping):
        return globals_
    return {}


def _matching_stage_hit(
    events: list[Mapping[str, Any]], candidates: Mapping[str, Any], key: str
) -> Mapping[str, Any] | None:
    candidate_pc = candidates.get(key)
    if not _is_positive_int(candidate_pc):
        return None
    for event in events:
        if event.get("stage") == key and event.get("pc") == candidate_pc:
            return event
    return None


def _promotable_entry(va: int, evidence: str) -> dict[str, Any]:
    return {
        "va": va,
        "confidence": LIVE_CONFIDENCE,
        "evidence": evidence,
    }


def _global_va(
    payload_globals: Mapping[str, Any], events: list[Mapping[str, Any]], key: str
) -> int | None:
    value = payload_globals.get(key)
    if _is_positive_int(value):
        return value
    for event in events:
        sample = _event_globals(event).get(key)
        if isinstance(sample, Mapping) and _is_positive_int(sample.get("va")):
            return sample["va"]
    return None


def _global_has_plausible_live_value(
    events: list[Mapping[str, Any]], key: str, va: int
) -> bool:
    for event in events:
        sample = _event_globals(event).get(key)
        if not isinstance(sample, Mapping):
            continue
        if sample.get("va") != va or "error" in sample:
            continue
        if _is_bounded_pointer(sample.get("u32")):
            return True
    return False


def _ig_sample_reason(event: Mapping[str, Any]) -> str | None:
    globals_ = _event_globals(event)
    graph = globals_.get("interferencegraph")
    count = globals_.get("n_ignodes")
    if not isinstance(graph, Mapping) or not isinstance(count, Mapping):
        return "missing IG globals"
    if not _is_bounded_pointer(graph.get("u32")):
        return "missing live interference graph pointer"
    n_ignodes = count.get("u32")
    if not isinstance(n_ignodes, int) or not 0 < n_ignodes < IGNODE_LIMIT:
        return "implausible n_ignodes"

    rows = event.get("ig_sample")
    if not isinstance(rows, list) or not rows:
        return "missing IG sample"
    for row in rows:
        if not isinstance(row, Mapping):
            return "malformed IG sample row"
        if "error" in row:
            return "IG sample read error"
        slot = row.get("slot")
        if not isinstance(slot, int) or not 0 <= slot < n_ignodes:
            return "implausible IG sample"
        if row.get("ig_idx") != slot:
            return "implausible IG sample"
        degree = row.get("degree")
        array_size = row.get("arraySize")
        if not isinstance(degree, int) or not isinstance(array_size, int):
            return "implausible IG sample"
        if (
            degree < 0
            or array_size < 0
            or degree > array_size
            or array_size >= IGNODE_LIMIT
        ):
            return "implausible IG sample"
        if not isinstance(row.get("assignedReg"), int) or not isinstance(
            row.get("flags"), int
        ):
            return "implausible IG sample"
        if not _is_bounded_pointer(row.get("ptr")):
            return "implausible IG sample"
        next_ptr = row.get("next")
        if not isinstance(next_ptr, int) or (
            next_ptr != 0 and not _is_bounded_pointer(next_ptr)
        ):
            return "IG sample missing next or inline array evidence"
        neighbors = row.get("neighbors_sample")
        if array_size > 0:
            if not isinstance(neighbors, list) or not neighbors:
                return "IG sample missing next or inline array evidence"
            if len(neighbors) > array_size:
                return "implausible IG sample"
            for neighbor in neighbors:
                if not isinstance(neighbor, int) or not 0 <= neighbor < n_ignodes:
                    return "implausible IG sample"
        elif neighbors not in (None, []):
            return "implausible IG sample"
    return None


def _classify_ig_samples(events: list[Mapping[str, Any]]) -> tuple[bool, str]:
    sample_events = [
        event
        for event in events
        if event.get("stage") in IG_SAMPLE_STAGES and "ig_sample" in event
    ]
    if not sample_events:
        return False, "missing IG sample"
    for event in sample_events:
        reason = _ig_sample_reason(event)
        if reason is not None:
            return False, reason
    return True, "IG sample proves expected IGNode offsets"


def _used_vreg_reason(
    events: list[Mapping[str, Any]], key: str, va: int, rclass: int
) -> str | None:
    for event in events:
        args = event.get("stage_args")
        if not isinstance(args, Mapping):
            continue
        if args.get("rclass") != rclass:
            continue
        n_virtuals = args.get("n_virtuals")
        if not isinstance(n_virtuals, int) or not 0 <= n_virtuals < IGNODE_LIMIT:
            continue
        sample = _event_globals(event).get(key)
        if not isinstance(sample, Mapping):
            continue
        if sample.get("va") != va or "error" in sample:
            continue
        if sample.get("s16") == n_virtuals:
            return None
    return "no class-stage n_virtuals match for used-vreg global"


def _block_sample_reason(events: list[Mapping[str, Any]]) -> str | None:
    sample_events = [
        event
        for event in events
        if event.get("stage") in BLOCK_SAMPLE_STAGES and "block_sample" in event
    ]
    if not sample_events:
        return "missing PCode block sample"
    saw_pcode = False
    for event in sample_events:
        globals_ = _event_globals(event)
        block_head = globals_.get("pcbasicblocks")
        if not isinstance(block_head, Mapping) or not _is_bounded_pointer(
            block_head.get("u32")
        ):
            return "missing live block-list pointer"
        rows = event.get("block_sample")
        if not isinstance(rows, list) or not rows:
            return "missing PCode block sample"
        for row in rows:
            if not isinstance(row, Mapping):
                return "malformed PCode block sample"
            if not _is_bounded_pointer(row.get("ptr")):
                return "implausible PCode block sample"
            next_ptr = row.get("next")
            if not isinstance(next_ptr, int) or (
                next_ptr != 0 and not _is_bounded_pointer(next_ptr)
            ):
                return "implausible PCode block sample"
            block_index = row.get("blockIndex")
            if not isinstance(block_index, int) or block_index < 0:
                return "implausible PCode block sample"
            first_pcode = row.get("firstPCode")
            last_pcode = row.get("lastPCode")
            if first_pcode != 0 and not _is_bounded_pointer(first_pcode):
                return "implausible PCode block sample"
            if last_pcode != 0 and not _is_bounded_pointer(last_pcode):
                return "implausible PCode block sample"
            pcode = row.get("first_pcode")
            if first_pcode == 0:
                continue
            if not isinstance(pcode, Mapping):
                return "missing PCode sample"
            if pcode.get("ptr") != first_pcode:
                return "implausible PCode sample"
            next_pcode = pcode.get("next")
            if not isinstance(next_pcode, int) or (
                next_pcode != 0 and not _is_bounded_pointer(next_pcode)
            ):
                return "implausible PCode sample"
            opcode = pcode.get("opcode")
            arg_count = pcode.get("arg_count")
            if not isinstance(opcode, int) or not 0 <= opcode < 4096:
                return "implausible PCode sample"
            if not isinstance(arg_count, int) or not 0 <= arg_count < 64:
                return "implausible PCode sample"
            saw_pcode = True
    if not saw_pcode:
        return "missing PCode sample"
    return None


def _frame_locals_evidence(events: list[Mapping[str, Any]]) -> tuple[int | None, str]:
    frame_events = [
        event
        for event in events
        if event.get("stage") in {"final_scheduler", "codegen_end"}
        and isinstance(event.get("frame_state"), Mapping)
    ]
    if not frame_events:
        return None, "missing frame locals sample"
    for event in frame_events:
        frame = event["frame_state"]
        locals_state = frame.get("locals")
        base_size = frame.get("frame_base_size")
        call_args_size = frame.get("frame_call_args_size")
        if not isinstance(locals_state, Mapping):
            continue
        va = locals_state.get("va")
        if not _is_positive_int(va):
            continue
        if not isinstance(base_size, Mapping) or not isinstance(
            base_size.get("s32"), int
        ):
            continue
        if not isinstance(call_args_size, Mapping) or not isinstance(
            call_args_size.get("s32"), int
        ):
            continue
        objects = locals_state.get("objects_sample")
        if not isinstance(objects, list) or not objects:
            continue
        for obj in objects:
            if not isinstance(obj, Mapping):
                return None, "implausible frame locals sample"
            node = obj.get("node")
            next_node = obj.get("next")
            obj_ptr = obj.get("object")
            if not _is_bounded_pointer(node) or not _is_bounded_pointer(obj_ptr):
                return None, "implausible frame locals sample"
            if not isinstance(next_node, int) or (
                next_node != 0 and not _is_bounded_pointer(next_node)
            ):
                return None, "implausible frame locals sample"
            if not isinstance(obj.get("name"), str):
                return None, "implausible frame locals sample"
            if not isinstance(obj.get("stack_offset"), int) or not isinstance(
                obj.get("size"), int
            ):
                return None, "implausible frame locals sample"
        return va, "frame locals list and frame-size globals sampled live"
    return None, "missing plausible frame locals sample"


def classify_probe_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return _block_all("payload must be object")
    if payload.get("requested_function_matched") is not True:
        return _block_all("requested function was not matched")
    errors = payload.get("errors")
    if errors:
        return _block_all("payload reported errors")

    candidates = payload.get("candidates")
    if not isinstance(candidates, Mapping):
        candidates = {}
    payload_globals = payload.get("globals")
    if not isinstance(payload_globals, Mapping):
        payload_globals = {}
    raw_events = payload.get("events")
    events = (
        [event for event in raw_events if isinstance(event, Mapping)]
        if isinstance(raw_events, list)
        else []
    )

    ig_sample_ok, ig_sample_reason = _classify_ig_samples(events)
    block_sample_reason = _block_sample_reason(events)
    frame_locals_va, frame_locals_reason = _frame_locals_evidence(events)

    result: dict[str, Any] = {
        "promotable_entries": {},
        "blocked_entries": {},
        "promotable_structs": {},
        "blocked_structs": {},
    }

    for key in REQUIRED_GC125N_BACKEND_KEYS:
        if key in STAGE_ENTRY_KEYS:
            hit = _matching_stage_hit(events, candidates, key)
            if hit is None:
                result["blocked_entries"][key] = {"reason": "missing matching stage hit"}
                continue
            result["promotable_entries"][key] = _promotable_entry(
                int(candidates[key]), f"candidate PC observed at {key}"
            )
            continue

        if key in GLOBAL_ENTRY_KEYS:
            va = _global_va(payload_globals, events, key)
            if va is None:
                result["blocked_entries"][key] = {"reason": "missing global address"}
                continue
            if not _global_has_plausible_live_value(events, key, va):
                result["blocked_entries"][key] = {
                    "reason": "missing plausible live global value"
                }
                continue
            result["promotable_entries"][key] = _promotable_entry(
                va, f"{key} global read produced a bounded live pointer"
            )
            continue

        if key in IG_BACKED_GLOBAL_KEYS:
            va = _global_va(payload_globals, events, key)
            if va is None:
                result["blocked_entries"][key] = {"reason": "missing global address"}
                continue
            if not ig_sample_ok:
                result["blocked_entries"][key] = {"reason": ig_sample_reason}
                continue
            result["promotable_entries"][key] = _promotable_entry(va, ig_sample_reason)
            continue

        if key in USED_VREG_CLASSES:
            va = _global_va(payload_globals, events, key)
            if va is None:
                result["blocked_entries"][key] = {"reason": "missing global address"}
                continue
            reason = _used_vreg_reason(events, key, va, USED_VREG_CLASSES[key])
            if reason is not None:
                result["blocked_entries"][key] = {"reason": reason}
                continue
            result["promotable_entries"][key] = _promotable_entry(
                va, f"{key} global matched live class n_virtuals"
            )
            continue

        if key == "backend_block_list":
            va = _global_va(payload_globals, events, "pcbasicblocks")
            if va is None:
                result["blocked_entries"][key] = {"reason": "missing global address"}
                continue
            if block_sample_reason is not None:
                result["blocked_entries"][key] = {"reason": block_sample_reason}
                continue
            result["promotable_entries"][key] = _promotable_entry(
                va, "block sample proves PCodeBlock list at pcbasicblocks"
            )
            continue

        if key == "frame_locals":
            if frame_locals_va is None:
                result["blocked_entries"][key] = {"reason": frame_locals_reason}
                continue
            result["promotable_entries"][key] = _promotable_entry(
                frame_locals_va, frame_locals_reason
            )
            continue

        result["blocked_entries"][key] = {"reason": "no direct live invariant in probe"}

    if ig_sample_ok:
        result["promotable_structs"]["IGNode"] = {
            "confidence": LIVE_CONFIDENCE,
            "fields": dict(REQUIRED_STRUCT_FIELDS["IGNode"]),
            "evidence": ig_sample_reason,
        }
    else:
        result["blocked_structs"]["IGNode"] = {"reason": ig_sample_reason}

    if block_sample_reason is None:
        result["promotable_structs"]["PCodeBlock"] = {
            "confidence": LIVE_CONFIDENCE,
            "fields": dict(REQUIRED_STRUCT_FIELDS["PCodeBlock"]),
            "evidence": "block sample proves PCodeBlock next/firstPCode/blockIndex fields",
        }
        result["promotable_structs"]["PCode"] = {
            "confidence": LIVE_CONFIDENCE,
            "fields": dict(REQUIRED_STRUCT_FIELDS["PCode"]),
            "evidence": "block sample proves PCode next/opcode/arg_count fields",
        }
    else:
        result["blocked_structs"]["PCodeBlock"] = {"reason": block_sample_reason}
        result["blocked_structs"]["PCode"] = {"reason": block_sample_reason}
    return result
