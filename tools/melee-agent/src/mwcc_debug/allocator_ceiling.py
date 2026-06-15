from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


class EvidenceFunctionMismatch(ValueError):
    """Raised when evidence names a function different from the requested one."""


class EvidenceFormatError(ValueError):
    """Raised when an evidence payload is not a JSON object or list of objects."""


_BOUNDED_STOP_KINDS = {"candidate-limit", "budget-exhausted"}


def flatten_evidence_items(items: Iterable[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, list):
            out.extend(flatten_evidence_items(item))
        elif isinstance(item, Mapping):
            out.append(dict(item))
        else:
            raise EvidenceFormatError(
                "evidence must be a JSON object or a list of JSON objects"
            )
    return out


def classify_allocator_ceiling(
    evidence: Iterable[Mapping[str, Any]],
    *,
    function: str,
) -> dict[str, Any]:
    items = flatten_evidence_items(evidence)
    _validate_function_scope(items, function=function)

    positive = _positive_proofs(items)
    directed = _directed_summary(items)
    bounded = _dedupe([*_bounded_reasons(items), *directed["bounded_reasons"]])
    node_delta = _node_set_delta(items)
    force_vector = _force_vector_status(items)
    wrong_register = _wrong_register_exhausted(items)
    transform_exhausted = _transform_exhausted(items)
    skipped_count = _skipped_source_evidence_count(items)

    legacy_missing: list[str] = []
    if node_delta is None:
        legacy_missing.append(
            "solve-coloring structurally-different-virtual node_set_delta"
        )
    if not (
        force_vector.get("ran") is True
        and force_vector.get("union_status") == "match"
    ):
        legacy_missing.append("force-phys verification with union status match")
    if not wrong_register:
        legacy_missing.append("node-set-split exhaustive all-wrong-register evidence")
    if not transform_exhausted:
        legacy_missing.append("transform-corpus exhausted negative validation evidence")

    directed_complete = bool(directed["complete"])
    directed_missing = _directed_missing_evidence(directed)
    missing = directed_missing if directed["present"] and not directed_complete else legacy_missing

    if positive:
        status = "actionable"
        reason = "positive-proof"
        exit_code = 0
    elif bounded:
        status = "bounded"
        reason = "bounded-evidence"
        exit_code = 4
    elif directed_complete:
        status = "practical-ceiling"
        reason = "directed-source-exhausted"
        exit_code = 3
        missing = []
    elif not legacy_missing:
        status = "practical-ceiling"
        reason = "target-only-allocator-rotation"
        exit_code = 3
        missing = []
    else:
        status = "incomplete"
        reason = "missing-required-evidence"
        exit_code = 3

    directed_source_exhausted = (
        status == "practical-ceiling" and reason == "directed-source-exhausted"
    )
    backend_blockers = directed["backend_blockers"] if directed_source_exhausted else []

    return {
        "function": function,
        "status": status,
        "terminal_reason": reason,
        "exit_code": exit_code,
        "positive_proofs": positive,
        "source_shape_exhausted": bool(transform_exhausted or directed_source_exhausted),
        "directed_source_exhausted": directed_source_exhausted,
        "backend_blockers": backend_blockers,
        "node_set_delta": node_delta,
        "force_vector": force_vector,
        "wrong_register_exhausted": bool(wrong_register),
        "bounded_reasons": bounded,
        "missing_evidence": missing,
        "skipped_source_evidence_count": skipped_count,
        "evidence_count": len(items),
        "next_steps": _next_steps(
            function=function,
            status=status,
            bounded=bounded,
            missing=missing,
        ),
    }


def _validate_function_scope(items: list[dict[str, Any]], *, function: str) -> None:
    for idx, item in enumerate(items):
        names = _function_names(item)
        if not names:
            raise EvidenceFunctionMismatch(
                f"evidence item {idx} has no function scope for {function}"
            )
        for name in names:
            if name != function:
                raise EvidenceFunctionMismatch(
                    f"evidence item {idx} is for {name}, not {function}"
                )


def _function_names(item: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    value = item.get("function")
    if isinstance(value, str) and value:
        names.add(value)
    for key in (
        "node_set_delta",
        "plan",
        "request",
        "validation_summary",
        "node_set_delta_summary",
        "force_vector_verify",
        "validator_payload",
        "evidence",
    ):
        nested = item.get(key)
        if isinstance(nested, Mapping):
            names.update(_function_names(nested))
    for key in ("validation", "validation_results", "directed_telemetry"):
        nested_list = item.get(key)
        if isinstance(nested_list, list):
            for nested in nested_list:
                if isinstance(nested, Mapping):
                    names.update(_function_names(nested))
    return names


def _positive_proofs(items: list[dict[str, Any]]) -> list[str]:
    proofs: list[str] = []
    for item in items:
        if item.get("byte_match") is True:
            proofs.append("byte_match")
        if item.get("status") == "improved":
            proofs.append("status improved")
        delta = item.get("best_checkdiff_delta")
        if isinstance(delta, (int, float)) and not isinstance(delta, bool) and delta > 0:
            proofs.append(f"best_checkdiff_delta {delta:g}")
        validation = item.get("validation") or []
        if isinstance(validation, list):
            for result in validation:
                if (
                    isinstance(result, Mapping)
                    and result.get("outcome") == "retained-source-improvement"
                ):
                    proofs.append("validation retained-source-improvement")
                    break
        summary = item.get("validation_summary")
        if (
            isinstance(summary, Mapping)
            and summary.get("stop_condition") == "retained-source-improvement"
        ):
            proofs.append("validation_summary retained-source-improvement")
        telemetry = item.get("directed_telemetry")
        if isinstance(telemetry, list):
            for row in telemetry:
                if not isinstance(row, Mapping):
                    continue
                if row.get("checkdiff_gate") == "byte_match":
                    proofs.append("directed byte_match")
                    break
                byte_score = row.get("byte_score")
                if (
                    isinstance(byte_score, (int, float))
                    and not isinstance(byte_score, bool)
                    and byte_score == 0
                ):
                    proofs.append("directed byte_match")
                    break
        gate = item.get("gate")
        if isinstance(gate, Mapping) and gate.get("passed") is True:
            reason = gate.get("reason")
            if isinstance(reason, str) and reason:
                proofs.append(f"directed {reason}")
            else:
                proofs.append("directed gate passed")
    return proofs


def _directed_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "present": False,
        "complete": False,
        "source_rows": 0,
        "compiled": 0,
        "telemetry_rows": 0,
        "byte_mismatch_rows": 0,
        "unknown_byte_rows": 0,
        "source_shape_drained": False,
        "has_blocked_assignments": False,
        "has_no_smooth_gradient_gate": False,
        "bounded_reasons": [],
        "backend_blockers": [],
    }
    blockers: dict[tuple[Any, Any, Any, Any, Any], dict[str, Any]] = {}

    for item in items:
        run = _directed_item_summary(item)
        if not run["present"]:
            continue
        summary["present"] = True
        summary["source_rows"] += run["source_rows"]
        summary["compiled"] += run["compiled"]
        summary["telemetry_rows"] += run["telemetry_rows"]
        summary["byte_mismatch_rows"] += run["byte_mismatch_rows"]
        summary["unknown_byte_rows"] += run["unknown_byte_rows"]
        summary["source_shape_drained"] = (
            summary["source_shape_drained"] or run["source_shape_drained"]
        )
        summary["has_blocked_assignments"] = (
            summary["has_blocked_assignments"] or run["has_blocked_assignments"]
        )
        summary["has_no_smooth_gradient_gate"] = (
            summary["has_no_smooth_gradient_gate"]
            or run["has_no_smooth_gradient_gate"]
        )
        summary["bounded_reasons"].extend(run["bounded_reasons"])
        _merge_backend_blockers(blockers, run["backend_blockers"])
        if run["complete"]:
            summary["complete"] = True

    summary["bounded_reasons"] = _dedupe(summary["bounded_reasons"])
    summary["backend_blockers"] = list(blockers.values())
    return summary


def _directed_item_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    telemetry = item.get("directed_telemetry")
    if not isinstance(telemetry, list):
        return {
            "present": False,
            "complete": False,
            "source_rows": 0,
            "compiled": 0,
            "telemetry_rows": 0,
            "byte_mismatch_rows": 0,
            "unknown_byte_rows": 0,
            "source_shape_drained": False,
            "has_blocked_assignments": False,
            "has_no_smooth_gradient_gate": False,
            "bounded_reasons": [],
            "backend_blockers": [],
        }

    bounded_reasons = _directed_bounded_reasons(item)
    compiled = 0
    accounting = item.get("accounting")
    source_shape_drained = False
    if isinstance(accounting, Mapping):
        compiled = _nonnegative_int(accounting.get("compiled"))
        source_shape_drained = accounting.get("source_shape_drained") is True

    gate = item.get("gate")
    has_no_smooth_gradient_gate = (
        isinstance(gate, Mapping)
        and gate.get("passed") is False
        and gate.get("reason") == "no_smooth_gradient"
    )
    source_rows = 0
    byte_mismatch_rows = 0
    unknown_byte_rows = 0
    invalid_rows = 0
    blockers: dict[tuple[Any, Any, Any, Any, Any], dict[str, Any]] = {}
    telemetry_rows = 0
    for row in telemetry:
        if not isinstance(row, Mapping):
            continue
        telemetry_rows += 1
        if row.get("valid") is False:
            invalid_rows += 1
        if _has_byte_mismatch_outcome(row):
            byte_mismatch_rows += 1
        elif row.get("valid") is not False:
            unknown_byte_rows += 1
        if _is_source_transform_row(row):
            source_rows += 1
        _merge_backend_blockers(blockers, _directed_backend_blockers(row))

    if invalid_rows:
        bounded_reasons.append("directed search invalid directed telemetry")

    backend_blockers = list(blockers.values())
    complete = (
        telemetry_rows > 0
        and compiled > 0
        and source_rows > 0
        and byte_mismatch_rows > 0
        and unknown_byte_rows == 0
        and source_shape_drained
        and bool(backend_blockers)
        and has_no_smooth_gradient_gate
        and not bounded_reasons
    )
    return {
        "present": True,
        "complete": complete,
        "source_rows": source_rows,
        "compiled": compiled,
        "telemetry_rows": telemetry_rows,
        "byte_mismatch_rows": byte_mismatch_rows,
        "unknown_byte_rows": unknown_byte_rows,
        "source_shape_drained": source_shape_drained,
        "has_blocked_assignments": bool(backend_blockers),
        "has_no_smooth_gradient_gate": has_no_smooth_gradient_gate,
        "bounded_reasons": bounded_reasons,
        "backend_blockers": backend_blockers,
    }


def _directed_bounded_reasons(item: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    accounting = item.get("accounting")
    if not isinstance(accounting, Mapping):
        return reasons
    if accounting.get("budget_exhausted") is True:
        reasons.append("directed search budget exhausted")
    stop_reason = accounting.get("stop_reason")
    if stop_reason in _BOUNDED_STOP_KINDS:
        reasons.append(f"directed search {stop_reason}")
    stop_condition = accounting.get("stop_condition")
    if isinstance(stop_condition, Mapping):
        kind = stop_condition.get("kind")
        if kind in _BOUNDED_STOP_KINDS:
            reasons.append(f"directed search {kind}")
    producer_failed = _nonnegative_int(accounting.get("producer_failed"))
    producer_failures = accounting.get("producer_failures")
    if producer_failed or (
        isinstance(producer_failures, list) and len(producer_failures) > 0
    ):
        reasons.append("directed search producer failed")
    if _nonnegative_int(accounting.get("score_failed")):
        reasons.append("directed search score failed")
    if _nonnegative_int(accounting.get("directed_invalid")):
        reasons.append("directed search invalid directed telemetry")
    return _dedupe(reasons)


def _directed_backend_blockers(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    if row.get("valid") is False:
        return []
    assignments = row.get("proof_assignments")
    if not isinstance(assignments, Mapping):
        return []
    blocked = assignments.get("blocked")
    if not isinstance(blocked, list):
        return []
    mutator = row.get("applied_mutator")
    class_id = row.get("class_id")
    out: list[dict[str, Any]] = []
    for entry in blocked:
        if not isinstance(entry, Mapping):
            continue
        blocker = {
            "original_ig": entry.get("original_ig"),
            "new_ig": entry.get("new_ig"),
            "desired_phys": entry.get("desired_phys"),
            "assigned_phys": entry.get("assigned_phys"),
            "mutators": [],
        }
        if class_id is not None:
            blocker["class_id"] = class_id
        if isinstance(mutator, str) and mutator:
            blocker["mutators"].append(mutator)
        out.append(blocker)
    return out


def _merge_backend_blockers(
    target: dict[tuple[Any, Any, Any, Any, Any], dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    for blocker in blockers:
        key = (
            blocker.get("class_id"),
            blocker.get("original_ig"),
            blocker.get("new_ig"),
            blocker.get("desired_phys"),
            blocker.get("assigned_phys"),
        )
        merged_payload = {
            "original_ig": key[1],
            "new_ig": key[2],
            "desired_phys": key[3],
            "assigned_phys": key[4],
            "mutators": [],
        }
        if key[0] is not None:
            merged_payload["class_id"] = key[0]
        merged = target.setdefault(key, merged_payload)
        for mutator in blocker.get("mutators", []):
            if mutator not in merged["mutators"]:
                merged["mutators"].append(mutator)


def _is_source_transform_row(row: Mapping[str, Any]) -> bool:
    mutator = row.get("applied_mutator")
    return isinstance(mutator, str) and mutator.startswith("transform-corpus:")


def _has_byte_mismatch_outcome(row: Mapping[str, Any]) -> bool:
    if row.get("checkdiff_gate") == "byte_mismatch":
        return True
    byte_score = row.get("byte_score")
    return (
        isinstance(byte_score, (int, float))
        and not isinstance(byte_score, bool)
        and byte_score > 0
    )


def _directed_missing_evidence(summary: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    if not summary.get("telemetry_rows"):
        missing.append("directed telemetry rows")
    if not summary.get("compiled"):
        missing.append("directed telemetry with compiled candidates")
    if not summary.get("byte_mismatch_rows") or summary.get("unknown_byte_rows"):
        missing.append("directed byte-mismatch outcomes")
    if not summary.get("source_shape_drained"):
        missing.append("directed source-shape drained signal")
    if not summary.get("source_rows"):
        missing.append("directed telemetry from source-transform candidates")
    if not summary.get("has_blocked_assignments"):
        missing.append("directed telemetry with blocked proof assignments")
    if not summary.get("has_no_smooth_gradient_gate"):
        missing.append("directed no_smooth_gradient gate verdict")
    return missing


def _bounded_reasons(items: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for item in items:
        stop_reason = item.get("stop_reason")
        if stop_reason in _BOUNDED_STOP_KINDS:
            reasons.append(f"{stop_reason} stop_reason")

        stop_condition = item.get("stop_condition")
        if isinstance(stop_condition, Mapping):
            kind = stop_condition.get("kind")
            if kind in _BOUNDED_STOP_KINDS:
                reasons.append(f"{kind} stop_condition")

        validation_summary = item.get("validation_summary")
        if isinstance(validation_summary, Mapping):
            remaining = validation_summary.get("remaining_probe_ids")
            if isinstance(remaining, list) and remaining:
                reasons.append(
                    _count_reason(
                        "transform-corpus has",
                        len(remaining),
                        "remaining probe",
                    )
                )

        node_summary = item.get("node_set_delta_summary")
        if isinstance(node_summary, Mapping):
            omitted = _nonnegative_int(node_summary.get("omitted_count"))
            if omitted:
                reasons.append(
                    _count_reason(
                        "transform-corpus omitted",
                        omitted,
                        "node-set probe",
                    )
                )
            capped = _nonnegative_int(node_summary.get("capped_count"))
            if capped:
                reasons.append(
                    _count_reason(
                        "transform-corpus capped",
                        capped,
                        "node-set probe",
                    )
                )
    return reasons


def _node_set_delta(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        nested = item.get("node_set_delta")
        if isinstance(nested, Mapping) and _is_required_node_set_delta(nested):
            return dict(nested)
        if _is_required_node_set_delta(item):
            return dict(item)
    return None


def _is_required_node_set_delta(item: Mapping[str, Any]) -> bool:
    return (
        item.get("kind") == "node-set-delta"
        and item.get("blocker") == "structurally-different-virtual"
    )


def _force_vector_status(items: list[dict[str, Any]]) -> dict[str, Any]:
    fallback: dict[str, Any] | None = None
    for item in items:
        verify = item.get("force_vector_verify")
        if not isinstance(verify, Mapping):
            continue
        union = verify.get("union")
        union_status = union.get("status") if isinstance(union, Mapping) else None
        ran = verify.get("ran") is True
        result = {
            "ran": ran,
            "union_status": union_status,
            "returncode": union.get("returncode") if isinstance(union, Mapping) else None,
        }
        if ran and union_status == "match":
            return result
        if (
            fallback is None
            or (result["ran"] is True and fallback.get("ran") is not True)
        ):
            fallback = result
    if fallback is not None:
        return fallback
    return {"ran": False, "union_status": None, "returncode": None}


def _wrong_register_exhausted(items: list[dict[str, Any]]) -> bool:
    for item in items:
        if item.get("wrong_register_exhausted") is True:
            return True
    return False


def _transform_exhausted(items: list[dict[str, Any]]) -> bool:
    for item in items:
        summary = item.get("validation_summary")
        if not isinstance(summary, Mapping):
            continue
        if summary.get("stop_condition") != "exhausted-negative-evidence":
            continue
        remaining = summary.get("remaining_probe_ids")
        if remaining not in ([], ()):
            continue
        node_summary = item.get("node_set_delta_summary")
        if isinstance(node_summary, Mapping):
            if _nonnegative_int(node_summary.get("omitted_count")):
                continue
            if _nonnegative_int(node_summary.get("capped_count")):
                continue
        return True
    return False


def _skipped_source_evidence_count(items: list[dict[str, Any]]) -> int:
    count = 0
    for item in items:
        summary = item.get("node_set_delta_summary")
        if isinstance(summary, Mapping):
            count += _nonnegative_int(summary.get("skipped_count"))
    return count


def _next_steps(
    *,
    function: str,
    status: str,
    bounded: list[str],
    missing: list[str],
) -> list[str]:
    if status == "actionable":
        return [f"Inspect positive allocator evidence for {function}."]
    if status == "bounded":
        return [f"Resolve bounded evidence: {reason}." for reason in bounded]
    if status == "incomplete":
        return [f"Collect missing evidence: {entry}." for entry in missing]
    return [
        f"Treat {function} as a practical allocator-rotation ceiling unless new positive evidence appears."
    ]


def render_allocator_ceiling_text(result: Mapping[str, Any]) -> str:
    lines = [
        (
            f"allocator-ceiling {result.get('function')}: "
            f"{result.get('status')} ({result.get('terminal_reason')})"
        ),
        f"evidence: {result.get('evidence_count', 0)} item(s)",
    ]

    force_vector = result.get("force_vector")
    if isinstance(force_vector, Mapping):
        lines.append(
            "force-vector: "
            f"ran={force_vector.get('ran')} "
            f"union={force_vector.get('union_status')}"
        )
    lines.append(
        "source-shape exhausted: "
        f"{bool(result.get('source_shape_exhausted'))}"
    )
    lines.append(
        "wrong-register exhausted: "
        f"{bool(result.get('wrong_register_exhausted'))}"
    )
    skipped_count = result.get("skipped_source_evidence_count")
    if skipped_count:
        lines.append(f"skipped source evidence: {skipped_count}")

    _extend_section(lines, "positive proofs", result.get("positive_proofs"))
    _extend_backend_blockers(lines, result.get("backend_blockers"))
    _extend_section(lines, "bounded reasons", result.get("bounded_reasons"))
    _extend_section(lines, "missing evidence", result.get("missing_evidence"))
    _extend_section(lines, "next steps", result.get("next_steps"))
    return "\n".join(lines)


def _extend_section(lines: list[str], title: str, entries: Any) -> None:
    if not isinstance(entries, list) or not entries:
        return
    lines.append(f"{title}:")
    for entry in entries:
        lines.append(f"- {entry}")


def _extend_backend_blockers(lines: list[str], entries: Any) -> None:
    if not isinstance(entries, list) or not entries:
        return
    lines.append("backend blockers:")
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        text = (
            f"ig{entry.get('original_ig')}->ig{entry.get('new_ig')} "
            f"wants {entry.get('desired_phys')} got {entry.get('assigned_phys')}"
        )
        mutators = entry.get("mutators")
        if isinstance(mutators, list) and mutators:
            text += " via " + ", ".join(str(mutator) for mutator in mutators)
        lines.append(f"- {text}")


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value > 0:
        return value
    return 0


def _count_reason(prefix: str, count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{prefix} {count} {noun}{suffix}"


def _dedupe(entries: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        out.append(entry)
    return out
