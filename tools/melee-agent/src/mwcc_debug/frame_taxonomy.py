"""Normalize stack-frame divergence diagnostics into closability tiers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_LIFETIME_CAUSES = {
    "extra-current-stack-object",
    "extra-source-local-home",
    "missing-current-stack-object",
    "missing-source-local-home",
}

_SIZE_ALIGNMENT_CAUSES = {
    "stack-object-size-or-alignment",
    "type-size-or-alignment",
}

_VALID_VERDICTS = {
    "attributed-frame-unchanged",
    "ceiling",
    "internal-tiebreak-ceiling",
    "partial-source-reachable-validated",
    "source-reachable-candidate",
    "source-reachable-validated",
    "unresolved-source-attribution",
}


def classify_frame_taxonomy(
    function: str,
    classification: Mapping[str, Any] | None = None,
    source_path: str | None = None,
    frame_report: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return normalized frame taxonomy fields for stack-local residuals."""
    frame_result = _classify_frame_report(
        function,
        frame_report=frame_report,
        source_path=source_path,
    )
    if frame_result is not None:
        return frame_result
    return _classify_checkdiff(
        function,
        classification=classification,
        source_path=source_path,
    )


def _classify_checkdiff(
    function: str,
    *,
    classification: Mapping[str, Any] | None,
    source_path: str | None,
) -> dict[str, Any] | None:
    if not isinstance(classification, Mapping):
        return None

    reserved = _reserved_low_spill_marker(classification)
    if reserved is not None:
        raw_cause = _string(reserved.get("kind")) or "reserved-unused-low-spill-region"
        return _build_result(
            function,
            cause="reserved-unused-low-spill-region",
            raw_cause=raw_cause,
            verdict="ceiling",
            raw_verdict="checkdiff-only",
            closability_tier="ceiling",
            attribution_status="checkdiff-only",
            source_object=None,
            source_object_symbol=None,
            next_command=_ceiling_command(function),
            reason="checkdiff localized a reserved-but-unused low spill region",
            classification=classification,
        )

    primary = _string(classification.get("primary"))
    if primary == "stack-slot-layout":
        return _build_result(
            function,
            cause="stack-object-offset-shift",
            raw_cause="checkdiff.stack_slot_localizer",
            verdict="source-reachable-candidate",
            raw_verdict="checkdiff-only",
            closability_tier="reorder-gated-362",
            attribution_status="checkdiff-only",
            source_object=None,
            source_object_symbol=None,
            next_command=_lifetime_layout_command(function, source_path),
            reason="checkdiff reports same-frame stack-slot placement differences",
            classification=classification,
        )

    if primary != "stack-layout":
        return None

    if _same_frame_stack_layout(classification):
        return _build_result(
            function,
            cause="stack-object-offset-shift",
            raw_cause="checkdiff.same_frame_stack_layout",
            verdict="source-reachable-candidate",
            raw_verdict="checkdiff-only",
            closability_tier="reorder-gated-362",
            attribution_status="checkdiff-only",
            source_object=None,
            source_object_symbol=None,
            next_command=_lifetime_layout_command(function, source_path),
            reason=(
                "checkdiff reports a stack-layout residual, but current and "
                "expected frame sizes match; treat as same-frame stack-slot "
                "or lifetime placement"
            ),
            classification=classification,
        )

    missing = _missing_stack_bytes(classification)
    reason_text = _reason_text(classification)
    pad_bytes = missing if isinstance(missing, int) and missing > 0 else None
    if pad_bytes is None:
        pad_bytes = _pad_stack_bytes_from_reasons(reason_text)

    if isinstance(missing, int) and missing > 0:
        cause = "pure-reservation"
        tier = "current-tools-padstack"
        verdict = "source-reachable-candidate"
        command = _frame_transform_command(
            function,
            source_path,
            operators=("frame-reservation-pad-stack",),
            pad_stack_bytes=missing,
        )
        reason = (
            f"current frame is {missing} byte(s) smaller; probe the implicit "
            "reservation with frame-transform-search"
        )
    elif isinstance(missing, int) and missing < 0:
        cause = "frame-too-large"
        tier = "gen-gated-366"
        verdict = "unresolved-source-attribution"
        command = _frame_transform_command(function, source_path)
        reason = (
            f"current frame is {-missing} byte(s) larger; removing the "
            "over-reservation is generator-gated"
        )
    elif "too small" in reason_text or pad_bytes is not None:
        cause = "pure-reservation"
        tier = "current-tools-padstack"
        verdict = "source-reachable-candidate"
        command = _frame_transform_command(
            function,
            source_path,
            operators=("frame-reservation-pad-stack",),
            pad_stack_bytes=pad_bytes,
        )
        reason = (
            "checkdiff reports a current frame-size reservation shortfall; "
            "probe the implicit reservation with frame-transform-search"
        )
    elif "too large" in reason_text:
        cause = "frame-too-large"
        tier = "gen-gated-366"
        verdict = "unresolved-source-attribution"
        command = _frame_transform_command(function, source_path)
        reason = (
            "checkdiff reports a current frame-size over-reservation; "
            "removing the source-level slot is generator-gated"
        )
    else:
        cause = "lifetime-or-ordering-shift"
        tier = "gen-gated-366"
        verdict = "unresolved-source-attribution"
        command = _frame_transform_command(function, source_path)
        reason = (
            "checkdiff reports stack-layout differences without enough "
            "pcdump attribution to isolate a source object"
        )

    return _build_result(
        function,
        cause=cause,
        raw_cause="checkdiff.stack_frame_delta",
        verdict=verdict,
        raw_verdict="checkdiff-only",
        closability_tier=tier,
        attribution_status="checkdiff-only",
        source_object=None,
        source_object_symbol=None,
        next_command=command,
        reason=reason,
        classification=classification,
    )


def _classify_frame_report(
    function: str,
    *,
    frame_report: Mapping[str, Any] | None,
    source_path: str | None,
) -> dict[str, Any] | None:
    if not isinstance(frame_report, Mapping):
        return None
    first_divergence = frame_report.get("frame_first_divergence")
    if not isinstance(first_divergence, Mapping):
        return None

    cause_hypothesis = first_divergence.get("cause_hypothesis")
    if not isinstance(cause_hypothesis, Mapping):
        cause_hypothesis = {}
    raw_cause = (
        _string(cause_hypothesis.get("kind"))
        or _string(first_divergence.get("status"))
        or "frame_first_divergence"
    )
    frame_delta = _frame_delta(frame_report, first_divergence, cause_hypothesis)
    cause = _normalize_frame_report_cause(raw_cause, frame_delta)

    source_attribution = first_divergence.get("source_attribution")
    if not isinstance(source_attribution, Mapping):
        source_attribution = {}
    attribution_status = (
        _string(source_attribution.get("status")) or "unattributed"
    )
    source_object = _primary_source_object(source_attribution)
    source_object_symbol = _source_object_symbol(
        source_object,
        cause_hypothesis,
        first_divergence,
    )

    raw_verdict = _raw_frame_report_verdict(first_divergence)
    verdict = _normalize_verdict(raw_verdict)
    tier = _closability_tier(cause, verdict)
    command = _next_command(
        function,
        source_path=source_path,
        frame_report=frame_report,
        cause=cause,
        closability_tier=tier,
        pad_stack_bytes=frame_delta if frame_delta and frame_delta > 0 else None,
    )

    return _build_result(
        function,
        cause=cause,
        raw_cause=raw_cause,
        verdict=verdict,
        raw_verdict=raw_verdict,
        closability_tier=tier,
        attribution_status=attribution_status,
        source_object=source_object,
        source_object_symbol=source_object_symbol,
        next_command=command,
        reason=_frame_report_reason(first_divergence, cause_hypothesis),
        frame_delta=frame_delta,
    )


def _build_result(
    function: str,
    *,
    cause: str,
    raw_cause: str,
    verdict: str,
    raw_verdict: str,
    closability_tier: str,
    attribution_status: str,
    source_object: dict[str, Any] | None,
    source_object_symbol: str | None,
    next_command: str,
    reason: str,
    classification: Mapping[str, Any] | None = None,
    frame_delta: int | None = None,
) -> dict[str, Any]:
    match_relevance, match_relevance_reason = _frame_match_relevance(
        cause,
        verdict,
        classification=classification,
        frame_delta=frame_delta,
    )
    return {
        "function": function,
        "cause": cause,
        "raw_cause": raw_cause,
        "verdict": verdict,
        "raw_verdict": raw_verdict,
        "closability_tier": closability_tier,
        "attribution_status": attribution_status,
        "source_object": source_object,
        "source_object_symbol": source_object_symbol,
        "next_command": next_command,
        "reason": reason,
        "match_relevance": match_relevance,
        "match_relevance_reason": match_relevance_reason,
    }


def _reserved_low_spill_marker(
    classification: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    localizer = classification.get("stack_slot_localizer")
    if isinstance(localizer, Mapping):
        marker = localizer.get("reserved_low_spill_region")
        if isinstance(marker, Mapping):
            return marker
    cause = classification.get("stack_slot_layout_cause")
    if isinstance(cause, Mapping) and (
        cause.get("kind") == "reserved-unused-low-spill-region"
    ):
        return cause
    return None


def _missing_stack_bytes(classification: Mapping[str, Any]) -> int | None:
    delta = classification.get("stack_frame_delta")
    if not isinstance(delta, Mapping):
        return None
    missing = delta.get("missing_stack_bytes")
    if isinstance(missing, bool):
        return None
    if isinstance(missing, int):
        return missing
    return None


def _same_frame_stack_layout(classification: Mapping[str, Any]) -> bool:
    delta = classification.get("stack_frame_delta")
    if not isinstance(delta, Mapping):
        return False
    missing = delta.get("missing_stack_bytes")
    if isinstance(missing, int) and not isinstance(missing, bool) and missing == 0:
        return True
    expected = delta.get("expected_frame_size")
    current = delta.get("current_frame_size")
    return (
        isinstance(expected, int)
        and not isinstance(expected, bool)
        and isinstance(current, int)
        and not isinstance(current, bool)
        and expected == current
    )


def _normalize_frame_report_cause(raw_cause: str, frame_delta: int | None) -> str:
    if raw_cause == "extra-frame-reservation-or-alignment":
        if frame_delta is not None and frame_delta > 0:
            return "pure-reservation"
        if frame_delta is not None and frame_delta < 0:
            return "frame-too-large"
        return "lifetime-or-ordering-shift"
    if raw_cause in {
        "lifetime-or-ordering-shift",
        "stack-object-offset-shift",
    }:
        return raw_cause
    if raw_cause in _SIZE_ALIGNMENT_CAUSES:
        return raw_cause
    if raw_cause in _LIFETIME_CAUSES:
        return "lifetime-or-ordering-shift"
    if raw_cause == "reserved-unused-low-spill-region":
        return "reserved-unused-low-spill-region"
    if raw_cause == "frame-too-large":
        return "frame-too-large"
    return "unresolved-attribution"


def _raw_frame_report_verdict(first_divergence: Mapping[str, Any]) -> str:
    validated = first_divergence.get("validated_verdict")
    if isinstance(validated, Mapping):
        status = _string(validated.get("status"))
        if status:
            return status
    verdict = first_divergence.get("verdict")
    if isinstance(verdict, Mapping):
        status = _string(verdict.get("status"))
        if status:
            return status
    return "unknown"


def _normalize_verdict(raw_verdict: str) -> str:
    if raw_verdict in _VALID_VERDICTS:
        return raw_verdict
    if raw_verdict in {
        "source-reachable-frame-transform",
        "source-reachable-reorder",
    }:
        return "source-reachable-validated"
    if raw_verdict in {
        "partial-source-reachable-frame-transform",
        "partial-source-reachable-reorder",
    }:
        return "partial-source-reachable-validated"
    if raw_verdict in {
        "frame-transform-ceiling-candidate",
        "internal-tiebreak-ceiling-candidate",
    }:
        return "internal-tiebreak-ceiling"
    return "unresolved-source-attribution"


def _closability_tier(cause: str, verdict: str) -> str:
    if verdict in {"ceiling", "internal-tiebreak-ceiling"}:
        return "ceiling"
    if verdict == "attributed-frame-unchanged":
        return "gen-gated-366"
    if cause == "pure-reservation":
        return "current-tools-padstack"
    if cause == "stack-object-offset-shift":
        return "reorder-gated-362"
    if cause in {
        "frame-too-large",
        "lifetime-or-ordering-shift",
        "stack-object-size-or-alignment",
        "type-size-or-alignment",
    }:
        return "gen-gated-366"
    return "ceiling"


def _frame_match_relevance(
    cause: str,
    verdict: str,
    *,
    classification: Mapping[str, Any] | None,
    frame_delta: int | None,
) -> tuple[str, str]:
    if cause == "pure-reservation":
        return (
            "match-gating-candidate",
            "frame reservation changes emitted frame size; closing it is likely required before judging remaining byte-match residuals",
        )
    if cause == "stack-object-offset-shift" and _same_frame_relevance_evidence(
        classification,
        frame_delta,
    ):
        return (
            "match-neutral",
            "same-frame stack-slot offset-only residual; closing this frame residual should not be treated as the match gate",
        )
    if verdict in {
        "source-reachable-validated",
        "partial-source-reachable-validated",
    }:
        return (
            "unknown",
            "frame movement was validated, but match relevance needs match-percent evidence",
        )
    return (
        "unknown",
        "frame relevance is not proven by the current frame taxonomy evidence",
    )


def _same_frame_relevance_evidence(
    classification: Mapping[str, Any] | None,
    frame_delta: int | None,
) -> bool:
    if frame_delta == 0:
        return True
    if not isinstance(classification, Mapping):
        return False
    if _same_frame_stack_layout(classification):
        return True
    primary = _string(classification.get("primary"))
    if primary != "stack-slot-layout":
        return False
    localizer = classification.get("stack_slot_localizer")
    if not isinstance(localizer, Mapping):
        return False
    frame_size = localizer.get("frame_size")
    return isinstance(frame_size, int) and not isinstance(frame_size, bool)


def _next_command(
    function: str,
    *,
    source_path: str | None,
    frame_report: Mapping[str, Any],
    cause: str,
    closability_tier: str,
    pad_stack_bytes: int | None,
) -> str:
    if closability_tier == "current-tools-padstack":
        return _frame_transform_command(
            function,
            source_path,
            operators=("frame-reservation-pad-stack",),
            pad_stack_bytes=pad_stack_bytes,
        )
    if closability_tier == "reorder-gated-362":
        return _lifetime_layout_command(function, source_path)
    if closability_tier == "gen-gated-366":
        planned = _planned_frame_transform_command(frame_report, function)
        if planned is not None:
            return planned
        operators = (
            ("frame-local-dematerialize", "frame-magic-scratch-relocation")
            if cause == "frame-too-large"
            else None
        )
        return _frame_transform_command(function, source_path, operators=operators)
    return _ceiling_command(function)


def _planned_frame_transform_command(
    frame_report: Mapping[str, Any],
    function: str,
) -> str | None:
    first_divergence = frame_report.get("frame_first_divergence")
    if not isinstance(first_divergence, Mapping):
        return None
    plan = first_divergence.get("frame_transform_probe_plan")
    if not isinstance(plan, Mapping):
        return None
    for item in plan.get("suggested_commands") or ():
        if not isinstance(item, Mapping):
            continue
        command = _string(item.get("command"))
        if command and "frame-transform-search" in command:
            return command.replace("<function>", function)
    return None


def _frame_transform_command(
    function: str,
    source_path: str | None,
    *,
    operators: tuple[str, ...] | None = None,
    pad_stack_bytes: int | None = None,
) -> str:
    parts = ["melee-agent debug mutate frame-transform-search", "-f", function]
    if source_path:
        parts.extend(["--source-file", source_path])
    for operator in operators or ():
        parts.extend(["--operator", operator])
    if pad_stack_bytes is not None and pad_stack_bytes > 0:
        parts.extend(["--frame-reservation-bytes", str(pad_stack_bytes)])
    parts.extend(["--compile-probes", "--json"])
    return " ".join(parts)


def _lifetime_layout_command(function: str, source_path: str | None) -> str:
    parts = ["melee-agent debug mutate lifetime-layout", "-f", function]
    if source_path:
        parts.extend(["--source-file", source_path])
    parts.extend(["--compile-probes", "--json"])
    return " ".join(parts)


def _ceiling_command(function: str) -> str:
    return f"melee-agent debug inspect frame-reservations -f {function} --json"


def _frame_delta(
    frame_report: Mapping[str, Any],
    first_divergence: Mapping[str, Any],
    cause_hypothesis: Mapping[str, Any],
) -> int | None:
    for source in (cause_hypothesis, first_divergence, frame_report):
        value = source.get("frame_delta")
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    current = frame_report.get("current")
    expected = frame_report.get("expected")
    if isinstance(current, Mapping) and isinstance(expected, Mapping):
        current_size = current.get("frame_size")
        expected_size = expected.get("frame_size")
        if (
            isinstance(current_size, int)
            and not isinstance(current_size, bool)
            and isinstance(expected_size, int)
            and not isinstance(expected_size, bool)
        ):
            return expected_size - current_size
    return None


def _primary_source_object(
    source_attribution: Mapping[str, Any],
) -> dict[str, Any] | None:
    primary = source_attribution.get("primary_source_object")
    if isinstance(primary, Mapping):
        return dict(primary)
    objects = source_attribution.get("source_objects")
    if isinstance(objects, list):
        for item in objects:
            if isinstance(item, Mapping):
                return dict(item)
    return None


def _source_object_symbol(
    source_object: Mapping[str, Any] | None,
    cause_hypothesis: Mapping[str, Any],
    first_divergence: Mapping[str, Any],
) -> str | None:
    if isinstance(source_object, Mapping):
        symbol = _string(source_object.get("symbol"))
        if symbol:
            return symbol
    symbol = _string(cause_hypothesis.get("source_object_symbol"))
    if symbol:
        return symbol
    for key in ("validated_verdict", "verdict"):
        verdict = first_divergence.get(key)
        if isinstance(verdict, Mapping):
            symbol = _string(verdict.get("source_object_symbol"))
            if symbol:
                return symbol
    return None


def _frame_report_reason(
    first_divergence: Mapping[str, Any],
    cause_hypothesis: Mapping[str, Any],
) -> str:
    for key in ("validated_verdict", "verdict"):
        verdict = first_divergence.get(key)
        if isinstance(verdict, Mapping):
            reason = _string(verdict.get("reason"))
            if reason:
                return reason
    reason = _string(cause_hypothesis.get("reason"))
    if reason:
        return reason
    return "frame report contains a stack frame first-divergence diagnostic"


def _reason_text(classification: Mapping[str, Any]) -> str:
    reasons = classification.get("reasons")
    if not isinstance(reasons, list):
        return ""
    return "\n".join(str(reason).lower() for reason in reasons)


def _pad_stack_bytes_from_reasons(reason_text: str) -> int | None:
    match = re.search(r"pad_stack\((\d+)\)", reason_text, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
