from __future__ import annotations

from ._helpers import *  # noqa: F403

@dataclass(frozen=True)
class _AsmInstruction:
    opcode: str
    operands: str
    pass_name: str
    block_idx: int | None
    instr_idx: int


def analyze_frame_reservations(
    pcdump_text: str,
    function: str,
    *,
    expected_asm_text: str | None = None,
    current_asm_text: str | None = None,
) -> dict:
    """Return a JSON-friendly stack frame reservation report.

    The current side comes from the final pcdump pass. The optional expected
    side may be target assembly from `extract get --full`. Ranges are expressed
    as half-open offsets from the post-prologue r1 value.
    """
    functions = parse_pcdump(pcdump_text, function=function)
    if not functions:
        raise ValueError(f"{function} not found in pcdump")
    fn = functions[0]
    current_instructions = _final_instructions(fn)
    symbolic_offsets = _resolve_symbolic_stack_homes(
        current_instructions,
        _parse_expected_asm(current_asm_text),
    )
    expected_symbolic_offsets = _resolve_symbolic_stack_homes(
        current_instructions,
        _parse_expected_asm(expected_asm_text),
    )
    current = _analyze_instructions(
        current_instructions,
        symbolic_offsets=symbolic_offsets,
        expected_symbolic_offsets=expected_symbolic_offsets,
    )
    expected = (
        _analyze_instructions(
            _parse_expected_asm(expected_asm_text),
            instrumentation_source="asm-r1-accesses",
        )
        if expected_asm_text
        else None
    )

    frame_delta = None
    if expected and expected["frame_size"] is not None and current["frame_size"] is not None:
        frame_delta = expected["frame_size"] - current["frame_size"]

    extra = (
        _extra_low_frame_reservation(current, expected)
        if expected is not None
        else None
    )
    current_low_expansion = (
        _current_low_frame_expansion(current, expected, frame_delta)
        if expected is not None
        else None
    )
    first_divergence = (
        _first_stack_object_divergence(current, expected, frame_delta)
        if expected is not None
        else None
    )
    summary = _summary(
        function,
        current,
        expected,
        frame_delta,
        extra,
        current_low_expansion,
    )
    report = {
        "function": function,
        "current": current,
        "expected": expected,
        "frame_delta": frame_delta,
        "extra_low_frame_reservation": extra,
        "current_low_frame_expansion": current_low_expansion,
        "frame_first_divergence": first_divergence,
        "pass_frame_timeline": _pass_frame_timeline(fn),
        "summary": summary,
    }
    _materialize_stack_home_probe_commands(report)
    return report


def analyze_frame_from_function(fn: Function) -> dict:
    """Return a JSON-friendly current-side frame model for a parsed function."""
    return _analyze_instructions(_final_instructions(fn))


def analyze_frame_from_asm_text(asm_text: str) -> dict:
    """Return a JSON-friendly frame model for raw target/checkdiff asm text."""
    return _analyze_instructions(
        _parse_expected_asm(asm_text),
        instrumentation_source="asm-r1-accesses",
    )


def evaluate_stack_home_probe_results(
    frame_report: dict,
    variant_results: list[dict[str, Any]],
) -> dict:
    """Score compiled source probes against target stack-home movement."""
    targets = _stack_home_probe_targets(frame_report)
    if not targets:
        return {
            "status": "unavailable-no-target-stack-home-moves",
            "verdict": "no-targets",
            "target_count": 0,
            "variant_count": len(variant_results),
            "best_variant": None,
            "variants": [],
        }

    variants = [
        _score_stack_home_probe_variant(targets, variant)
        for variant in variant_results
    ]
    variants.sort(
        key=lambda item: (
            int(item.get("target_fixed") is True),
            int(item.get("fixed_count") or 0),
            -int(item.get("remaining_target_mismatch_count") or 0),
            float(item.get("match_percent") or -1.0),
        ),
        reverse=True,
    )
    for rank, variant in enumerate(variants, start=1):
        variant["rank"] = rank
    best = variants[0] if variants else None

    if best is None:
        verdict = "no-probes"
    elif best.get("target_fixed"):
        verdict = "source-reachable-reorder"
    elif int(best.get("fixed_count") or 0) > 0:
        verdict = "partial-source-reachable-reorder"
    elif all(variant.get("status") == "ok" for variant in variants):
        verdict = "internal-tiebreak-ceiling-candidate"
    else:
        verdict = "probe-results-inconclusive"
    stop_condition = _stack_home_probe_stop_condition(
        verdict,
        best,
        variants,
        target_count=len(targets),
    )

    return {
        "status": "evaluated" if variants else "no-probes",
        "verdict": verdict,
        "stop_condition": stop_condition,
        "target_count": len(targets),
        "variant_count": len(variants),
        "targets": targets,
        "best_variant": best,
        "variants": variants,
    }


def evaluate_frame_transform_probe_results(
    frame_report: dict,
    variant_results: list[dict[str, Any]],
) -> dict:
    """Score compiled source probes against expected frame size."""
    expected = frame_report.get("expected")
    current = frame_report.get("current")
    if not isinstance(expected, dict) or not isinstance(current, dict):
        return {
            "status": "unavailable-no-current-or-expected-frame",
            "verdict": "no-target",
            "variant_count": len(variant_results),
            "best_variant": None,
            "variants": [],
        }
    expected_frame = expected.get("frame_size")
    current_frame = current.get("frame_size")
    if not isinstance(expected_frame, int) or not isinstance(current_frame, int):
        return {
            "status": "unavailable-no-frame-size",
            "verdict": "no-target",
            "variant_count": len(variant_results),
            "best_variant": None,
            "variants": [],
        }

    baseline_delta = expected_frame - current_frame
    variants = [
        _score_frame_transform_probe_variant(
            variant,
            expected_frame=expected_frame,
            baseline_delta=baseline_delta,
        )
        for variant in variant_results
    ]
    variants.sort(
        key=lambda item: (
            int(item.get("status") == "ok"),
            int(item.get("target_frame_fixed") is True),
            int(item.get("frame_delta_improvement") or 0),
            -abs(int(item.get("remaining_frame_delta") or baseline_delta)),
            float(item.get("match_percent") or -1.0),
        ),
        reverse=True,
    )
    for rank, variant in enumerate(variants, start=1):
        variant["rank"] = rank
    best = variants[0] if variants else None
    semantic_lever_status = frame_report.get("semantic_lever_status")
    no_safe_semantic_lever = _is_no_safe_semantic_lever_status(
        semantic_lever_status
    )

    if best is None:
        verdict = (
            "no-safe-semantic-lever"
            if no_safe_semantic_lever
            else "no-probes"
        )
    elif baseline_delta == 0:
        verdict = "frame-transform-already-at-target"
    elif (
        best.get("target_frame_fixed")
        and int(best.get("frame_delta_improvement") or 0) > 0
    ):
        verdict = "source-reachable-frame-transform"
    elif int(best.get("frame_delta_improvement") or 0) > 0:
        verdict = "partial-source-reachable-frame-transform"
    elif _all_ok_frame_transform_probes_measured(variants):
        verdict = "frame-transform-ceiling-candidate"
    else:
        verdict = "frame-transform-results-inconclusive"
    natural_source_attribution = _frame_transform_natural_source_attribution(
        verdict,
        variants,
        frame_report=frame_report,
        semantic_lever_status=semantic_lever_status,
    )
    stop_variant = best
    if best is not None and _is_diagnostic_frame_transform_operator(
        best.get("operator")
    ):
        if natural_source_attribution.get("status") == "validated-natural-source":
            verdict = "source-reachable-frame-transform"
            stop_variant = _best_natural_frame_transform_variant(
                variants,
                require_target_fixed=True,
            ) or best
        elif natural_source_attribution.get("status") == "partial-natural-source":
            verdict = "partial-source-reachable-frame-transform"
            stop_variant = _best_natural_frame_transform_variant(variants) or best
        elif int(best.get("frame_delta_improvement") or 0) > 0:
            verdict = "diagnostic-pad-stack-frame-transform"
            stop_variant = _best_diagnostic_frame_transform_variant(variants) or best
    elif natural_source_attribution.get("status") == "diagnostic-pad-stack-only":
        verdict = "diagnostic-pad-stack-frame-transform"
        stop_variant = _best_diagnostic_frame_transform_variant(variants) or best

    return {
        "status": "evaluated" if variants else "no-probes",
        "verdict": verdict,
        "stop_condition": _frame_transform_probe_stop_condition(
            verdict,
            stop_variant,
            variants,
            expected_frame=expected_frame,
            baseline_delta=baseline_delta,
            semantic_lever_status=semantic_lever_status,
            natural_source_attribution=natural_source_attribution,
        ),
        "natural_source_attribution": natural_source_attribution,
        "expected_frame_size": expected_frame,
        "current_frame_size": current_frame,
        "baseline_remaining_frame_delta": baseline_delta,
        "variant_count": len(variants),
        "best_variant": best,
        "variants": variants,
    }


def _score_frame_transform_probe_variant(
    variant: dict[str, Any],
    *,
    expected_frame: int,
    baseline_delta: int,
) -> dict:
    scored = dict(variant)
    candidate_frame = _variant_frame_size(variant)
    scored["candidate_frame_size"] = candidate_frame
    if isinstance(candidate_frame, int):
        remaining_delta = expected_frame - candidate_frame
        scored["remaining_frame_delta"] = remaining_delta
        scored["target_frame_fixed"] = remaining_delta == 0
        scored["frame_delta_improvement"] = (
            abs(baseline_delta) - abs(remaining_delta)
        )
    else:
        scored["remaining_frame_delta"] = None
        scored["target_frame_fixed"] = False
        scored["frame_delta_improvement"] = 0
    return scored


def _variant_frame_size(variant: dict[str, Any]) -> int | None:
    for key in ("frame_size", "frame_after", "candidate_frame_size"):
        value = variant.get(key)
        if isinstance(value, int):
            return value
    objective = variant.get("objective")
    if isinstance(objective, dict):
        for key in ("frame_after", "frame_size", "candidate_frame_size"):
            value = objective.get(key)
            if isinstance(value, int):
                return value
    signature = variant.get("signature")
    if isinstance(signature, dict):
        value = signature.get("frame_size")
        if isinstance(value, int):
            return value
    return None


def _all_ok_frame_transform_probes_measured(variants: list[dict]) -> bool:
    measured = [
        variant for variant in variants
        if variant.get("status") == "ok"
        and isinstance(variant.get("candidate_frame_size"), int)
    ]
    frame_size_capable = [
        variant for variant in measured
        if _is_frame_size_transform_operator(variant.get("operator"))
    ]
    return (
        bool(measured)
        and bool(frame_size_capable)
        and len(measured) == len(variants)
        and all(
            int(variant.get("frame_delta_improvement") or 0) == 0
            for variant in measured
        )
    )


_FRAME_SIZE_TRANSFORM_OPERATORS = {
    "frame-reservation-pad-stack",
    "frame-local-dematerialize",
    "frame-direct-literal-at-final-fp-call",
    "frame-split-fp-const-lifetime",
    "frame-magic-scratch-relocation",
}


def _is_frame_size_transform_operator(operator: Any) -> bool:
    return isinstance(operator, str) and operator in _FRAME_SIZE_TRANSFORM_OPERATORS


def _is_diagnostic_frame_transform_operator(operator: Any) -> bool:
    return operator == "frame-reservation-pad-stack"


def _is_natural_frame_transform_operator(operator: Any) -> bool:
    return _is_frame_size_transform_operator(
        operator
    ) and not _is_diagnostic_frame_transform_operator(operator)


def _best_natural_frame_transform_variant(
    variants: list[dict],
    *,
    require_target_fixed: bool = False,
) -> dict | None:
    for variant in variants:
        if not _is_natural_frame_transform_operator(variant.get("operator")):
            continue
        if variant.get("status") != "ok":
            continue
        if require_target_fixed and not variant.get("target_frame_fixed"):
            continue
        if int(variant.get("frame_delta_improvement") or 0) > 0:
            return variant
    return None


def _best_diagnostic_frame_transform_variant(variants: list[dict]) -> dict | None:
    for variant in variants:
        if not _is_diagnostic_frame_transform_operator(variant.get("operator")):
            continue
        if variant.get("status") == "ok":
            return variant
    return None


def _frame_transform_variant_summary(variant: dict | None) -> dict | None:
    if not isinstance(variant, dict):
        return None
    summary = {
        "label": variant.get("label"),
        "operator": variant.get("operator"),
        "status": variant.get("status"),
        "candidate_frame_size": variant.get("candidate_frame_size"),
        "remaining_frame_delta": variant.get("remaining_frame_delta"),
        "frame_delta_improvement": variant.get("frame_delta_improvement"),
    }
    if variant.get("match_percent") is not None:
        summary["match_percent"] = variant.get("match_percent")
    return summary


def _frame_transform_natural_source_attribution(
    verdict: str,
    variants: list[dict],
    *,
    frame_report: dict | None = None,
    semantic_lever_status: Any = None,
) -> dict:
    measured = [
        variant for variant in variants
        if variant.get("status") == "ok"
        and isinstance(variant.get("candidate_frame_size"), int)
    ]
    natural_measured = [
        variant for variant in measured
        if _is_natural_frame_transform_operator(variant.get("operator"))
    ]
    diagnostic_measured = [
        variant for variant in measured
        if _is_diagnostic_frame_transform_operator(variant.get("operator"))
    ]
    natural_improved = [
        variant for variant in natural_measured
        if int(variant.get("frame_delta_improvement") or 0) > 0
    ]
    diagnostic_improved = [
        variant for variant in diagnostic_measured
        if int(variant.get("frame_delta_improvement") or 0) > 0
    ]
    best_natural = natural_improved[0] if natural_improved else None
    best_diagnostic = diagnostic_improved[0] if diagnostic_improved else (
        diagnostic_measured[0] if diagnostic_measured else None
    )

    base = {
        "best_natural_variant": _frame_transform_variant_summary(best_natural),
        "best_diagnostic_variant": _frame_transform_variant_summary(best_diagnostic),
        "measured_natural_operator_count": len(natural_measured),
        "measured_diagnostic_operator_count": len(diagnostic_measured),
    }
    if best_natural and best_natural.get("target_frame_fixed"):
        return {
            **base,
            "status": "validated-natural-source",
            "verdict": "source-reachable",
            "missing_reason": None,
        }
    if best_natural is not None:
        return {
            **base,
            "status": "partial-natural-source",
            "verdict": "source-probe",
            "missing_reason": (
                "best non-PAD_STACK source transform improved the frame but "
                "did not reach the target frame size"
            ),
        }
    if diagnostic_improved:
        reason = (
            "best frame improvement is PAD_STACK diagnostic; no validated "
            "non-PAD_STACK source transform improved the frame"
        )
        unresolved_reason = _frame_transform_unresolved_attribution_reason(
            frame_report,
        )
        if unresolved_reason:
            reason = f"{reason}; unresolved source attribution: {unresolved_reason}"
        return {
            **base,
            "status": "diagnostic-pad-stack-only",
            "verdict": "diagnostic-only",
            "missing_reason": reason,
        }
    if _is_no_safe_semantic_lever_status(semantic_lever_status):
        return {
            **base,
            "status": "no-source-lever",
            "verdict": "diagnostic-only",
            "missing_reason": _semantic_lever_reason(semantic_lever_status),
        }
    if measured:
        return {
            **base,
            "status": "no-source-lever",
            "verdict": "diagnostic-only",
            "missing_reason": (
                "measured frame-transform probes did not validate a "
                "non-PAD_STACK source transform"
            ),
        }
    return {
        **base,
        "status": "inconclusive",
        "verdict": verdict,
        "missing_reason": "no measured frame-size-capable source probes",
    }


def _frame_transform_unresolved_attribution_reason(
    frame_report: dict | None,
) -> str | None:
    if not isinstance(frame_report, dict):
        return None
    first_divergence = frame_report.get("frame_first_divergence")
    if not isinstance(first_divergence, dict):
        return None
    verdict = first_divergence.get("verdict")
    if isinstance(verdict, dict) and isinstance(verdict.get("reason"), str):
        return verdict["reason"]
    source_attribution = first_divergence.get("source_attribution")
    if (
        isinstance(source_attribution, dict)
        and isinstance(source_attribution.get("reason"), str)
    ):
        return source_attribution["reason"]
    return None


def _is_no_safe_semantic_lever_status(status: Any) -> bool:
    return (
        isinstance(status, dict)
        and status.get("status") == "no-safe-semantic-lever"
    )


def _semantic_lever_reason(status: Any) -> str:
    if isinstance(status, dict) and isinstance(status.get("reason"), str):
        return status["reason"]
    return "source scan found no safe semantic local dematerialization"


def _frame_transform_probe_stop_condition(
    verdict: str,
    best: dict | None,
    variants: list[dict],
    *,
    expected_frame: int,
    baseline_delta: int,
    semantic_lever_status: Any = None,
    natural_source_attribution: dict | None = None,
) -> dict:
    if verdict == "source-reachable-frame-transform" and best is not None:
        label = str(best.get("label") or "<unknown>")
        condition = {
            "status": "satisfied",
            "kind": "validated-frame-transform",
            "reason": (
                f"probe {label} moves frame size to expected "
                f"{expected_frame} bytes"
            ),
            "variant_label": label,
            "remaining_frame_delta": best.get("remaining_frame_delta"),
        }
        _attach_natural_source_stop_condition(
            condition,
            natural_source_attribution,
        )
        return condition
    if verdict == "partial-source-reachable-frame-transform" and best is not None:
        label = str(best.get("label") or "<unknown>")
        improvement = int(best.get("frame_delta_improvement") or 0)
        condition = {
            "status": "partial",
            "kind": "partial-frame-transform",
            "reason": (
                f"probe {label} reduces absolute frame delta by "
                f"{improvement} byte(s)"
            ),
            "variant_label": label,
            "remaining_frame_delta": best.get("remaining_frame_delta"),
            "frame_delta_improvement": improvement,
        }
        _attach_natural_source_stop_condition(
            condition,
            natural_source_attribution,
        )
        return condition
    if verdict == "diagnostic-pad-stack-frame-transform" and best is not None:
        label = str(best.get("label") or "<unknown>")
        condition = {
            "status": "diagnostic",
            "kind": "diagnostic-pad-stack-only",
            "reason": (
                f"probe {label} changes frame size via PAD_STACK diagnostic; "
                "no validated non-PAD_STACK source transform improved the frame"
            ),
            "variant_label": label,
            "remaining_frame_delta": best.get("remaining_frame_delta"),
            "frame_delta_improvement": best.get("frame_delta_improvement"),
        }
        _attach_natural_source_stop_condition(
            condition,
            natural_source_attribution,
        )
        return condition
    if verdict == "frame-transform-ceiling-candidate":
        measured = [
            variant for variant in variants
            if variant.get("status") == "ok"
            and isinstance(variant.get("candidate_frame_size"), int)
        ]
        condition = {
            "status": "candidate",
            "kind": "bounded-frame-transform-ceiling",
            "reason": (
                f"{len(measured)} ok frame transform probe(s) left the "
                f"{abs(baseline_delta)}-byte frame delta unchanged"
            ),
            "measured_probe_count": len(measured),
            "baseline_remaining_frame_delta": baseline_delta,
        }
        _attach_natural_source_stop_condition(
            condition,
            natural_source_attribution,
        )
        return condition
    if verdict == "frame-transform-already-at-target":
        condition = {
            "status": "not-satisfied",
            "kind": "already-at-target-frame",
            "reason": (
                f"current frame size already matches expected {expected_frame} "
                "bytes; neutral probes do not validate a source transform"
            ),
            "baseline_remaining_frame_delta": baseline_delta,
        }
        _attach_natural_source_stop_condition(
            condition,
            natural_source_attribution,
        )
        return condition
    if verdict == "no-safe-semantic-lever":
        condition = {
            "status": "not-satisfied",
            "kind": "no-safe-semantic-lever",
            "reason": _semantic_lever_reason(semantic_lever_status),
            "baseline_remaining_frame_delta": baseline_delta,
        }
        _attach_natural_source_stop_condition(
            condition,
            natural_source_attribution,
        )
        return condition
    condition = {
        "status": "not-satisfied",
        "kind": verdict,
        "reason": "probe evidence is not sufficient for frame transform validation",
        "baseline_remaining_frame_delta": baseline_delta,
    }
    _attach_natural_source_stop_condition(condition, natural_source_attribution)
    return condition


def _attach_natural_source_stop_condition(
    condition: dict,
    attribution: dict | None,
) -> None:
    if not isinstance(attribution, dict):
        return
    if attribution.get("status") not in {
        "diagnostic-pad-stack-only",
        "no-source-lever",
    }:
        return
    if (
        attribution.get("status") == "no-source-lever"
        and condition.get("kind") not in {
            "no-safe-semantic-lever",
            "already-at-target-frame",
        }
    ):
        return
    condition["natural_source_attribution"] = attribution


def _materialize_stack_home_probe_commands(report: dict) -> None:
    function = report.get("function")
    if not isinstance(function, str) or not function:
        return
    first_divergence = report.get("frame_first_divergence")
    if isinstance(first_divergence, dict):
        plan = first_divergence.get("frame_transform_probe_plan")
        if isinstance(plan, dict):
            _materialize_probe_plan_commands(plan, function)

    current = report.get("current")
    if not isinstance(current, dict):
        return
    guidance = current.get("stack_home_reorder_guidance")
    if not isinstance(guidance, dict):
        return
    guidance["next_steps"] = [
        _materialize_function_placeholder(step, function)
        for step in guidance.get("next_steps") or []
        if isinstance(step, str)
    ]
    probe_plan = guidance.get("probe_plan")
    if not isinstance(probe_plan, dict):
        return
    _materialize_probe_plan_commands(probe_plan, function)


def _materialize_probe_plan_commands(probe_plan: dict, function: str) -> None:
    commands = []
    for item in probe_plan.get("suggested_commands") or []:
        if not isinstance(item, dict):
            continue
        command = item.get("command")
        if not isinstance(command, str):
            commands.append(item)
            continue
        updated = dict(item)
        updated["command"] = _materialize_function_placeholder(command, function)
        commands.append(updated)
    probe_plan["suggested_commands"] = commands
    validation = probe_plan.get("validation")
    if isinstance(validation, dict):
        command = validation.get("command")
        if isinstance(command, str):
            updated_validation = dict(validation)
            updated_validation["command"] = _materialize_function_placeholder(
                command,
                function,
            )
            probe_plan["validation"] = updated_validation


def _materialize_function_placeholder(command: str, function: str) -> str:
    return command.replace("<function>", function)


def _stack_home_probe_stop_condition(
    verdict: str,
    best: dict | None,
    variants: list[dict],
    *,
    target_count: int,
) -> dict:
    if verdict == "source-reachable-reorder" and best is not None:
        label = str(best.get("label") or "<unknown>")
        fixed_count = int(best.get("fixed_count") or 0)
        return {
            "status": "satisfied",
            "kind": "validated-source-reorder",
            "reason": (
                f"probe {label} moves all target stack homes to their expected offsets"
            ),
            "variant_label": label,
            "fixed_count": fixed_count,
            "target_count": target_count,
        }
    if verdict == "partial-source-reachable-reorder" and best is not None:
        label = str(best.get("label") or "<unknown>")
        fixed_count = int(best.get("fixed_count") or 0)
        return {
            "status": "partial",
            "kind": "partial-source-reorder",
            "reason": (
                f"probe {label} moves {fixed_count}/{target_count} target "
                "stack homes to their expected offsets"
            ),
            "variant_label": label,
            "fixed_count": fixed_count,
            "target_count": target_count,
        }
    if verdict == "internal-tiebreak-ceiling-candidate":
        measured = [
            variant for variant in variants
            if variant.get("target_movement_measured")
        ]
        return {
            "status": "candidate",
            "kind": "internal-tiebreak-ceiling",
            "reason": (
                f"{len(measured)} measured probe(s) left all {target_count} "
                "target stack-home mismatches in place"
            ),
            "measured_probe_count": len(measured),
            "target_count": target_count,
        }
    return {
        "status": "not-satisfied",
        "kind": verdict,
        "reason": "probe evidence is not sufficient for a source-reorder or ceiling stop condition",
        "target_count": target_count,
    }


def _select_final_pass(fn: Function) -> Pass | None:
    preferred = (
        "FINAL CODE AFTER INSTRUCTION SCHEDULING",
        "AFTER PEEPHOLE OPTIMIZATION",
        "AFTER MERGING EPILOGUE, PROLOGUE",
        "AFTER GENERATING EPILOGUE, PROLOGUE",
    )
    by_name = {p.name: p for p in fn.passes}
    for name in preferred:
        if name in by_name:
            return by_name[name]
    return fn.passes[-1] if fn.passes else None


def _pass_frame_timeline(fn: Function) -> dict:
    rows = []
    previous: dict | None = None
    first_change = None
    for pass_index, pass_ in enumerate(fn.passes):
        instructions = _instructions_for_pass(pass_)
        frame = _analyze_instructions(instructions)
        signature = _stack_object_signature(frame)
        row = {
            "pass_index": pass_index,
            "pass": pass_.name,
            "frame_size": frame.get("frame_size"),
            "stack_object_count": len(frame.get("stack_objects") or []),
            "occupied_stack_object_count": len(_occupied_stack_objects(frame)),
            "object_signature": signature,
        }
        if previous is not None:
            before = previous.get("frame_size")
            after = row.get("frame_size")
            if isinstance(before, int) and isinstance(after, int):
                row["frame_size_delta_from_previous"] = after - before
            signature_changed = signature != previous.get("object_signature")
            row["object_signature_changed_from_previous"] = signature_changed
            changed = (
                row.get("frame_size_delta_from_previous") not in (None, 0)
                or signature_changed
            )
            if changed and first_change is None:
                first_change = {
                    "status": "changed",
                    "pass_index": pass_index,
                    "pass": pass_.name,
                    "previous_pass": previous.get("pass"),
                    "frame_size_before": before,
                    "frame_size_after": after,
                    "frame_size_delta": row.get("frame_size_delta_from_previous"),
                    "object_signature_changed": signature_changed,
                    "reason": _pass_frame_change_reason(
                        row.get("frame_size_delta_from_previous"),
                        signature_changed,
                    ),
                }
        rows.append(row)
        previous = row
    return {
        "status": "computed" if rows else "unavailable-no-passes",
        "pass_count": len(rows),
        "first_change": first_change or {"status": "unchanged"},
        "passes": rows,
    }


def _instructions_for_pass(pass_: Pass) -> list[_AsmInstruction]:
    out: list[_AsmInstruction] = []
    ordinal = 0
    for block in pass_.blocks:
        for instr_idx, instr in enumerate(block.instructions):
            out.append(_from_parser_instruction(
                instr,
                pass_name=pass_.name,
                block_idx=block.index,
                instr_idx=instr_idx,
                ordinal=ordinal,
            ))
            ordinal += 1
    return out


def _stack_object_signature(frame: dict) -> list[dict]:
    return [
        {
            "start": item.get("start"),
            "end": item.get("end"),
            "size": item.get("size"),
            "kind": item.get("kind"),
            "source": item.get("source"),
        }
        for item in frame.get("stack_objects") or []
        if isinstance(item, dict)
    ]


def _pass_frame_change_reason(
    frame_delta: Any,
    object_signature_changed: bool,
) -> str:
    frame_changed = isinstance(frame_delta, int) and frame_delta != 0
    if frame_changed and object_signature_changed:
        return "frame-size-and-object-layout-changed"
    if frame_changed:
        return "frame-size-changed"
    if object_signature_changed:
        return "object-layout-changed"
    return "unchanged"


def _final_instructions(fn: Function) -> list[_AsmInstruction]:
    selected = _select_final_pass(fn)
    if selected is None:
        return []
    return _instructions_for_pass(selected)


def _from_parser_instruction(
    instr: Instruction,
    *,
    pass_name: str,
    block_idx: int | None,
    instr_idx: int,
    ordinal: int,
) -> _AsmInstruction:
    return _AsmInstruction(
        opcode=instr.opcode,
        operands=instr.operands,
        pass_name=pass_name,
        block_idx=block_idx,
        instr_idx=ordinal if block_idx is None else instr_idx,
    )


def _parse_expected_asm(text: str | None) -> list[_AsmInstruction]:
    if not text:
        return []
    out: list[_AsmInstruction] = []
    for line in text.splitlines():
        line = _ASM_COMMENT_RE.sub("", line).strip()
        line = _ASM_OFFSET_BYTES_RE.sub("", line).strip()
        if not line or line.startswith(".") or line.endswith(":"):
            continue
        parts = line.split(None, 1)
        if not parts:
            continue
        opcode = parts[0]
        operands = parts[1].strip() if len(parts) > 1 else ""
        if opcode.startswith("."):
            continue
        out.append(_AsmInstruction(
            opcode=opcode,
            operands=operands,
            pass_name="expected asm",
            block_idx=None,
            instr_idx=len(out),
        ))
    return out


def _analyze_instructions(
    instructions: list[_AsmInstruction],
    *,
    symbolic_offsets: dict[str, int] | None = None,
    expected_symbolic_offsets: dict[str, int] | None = None,
    instrumentation_source: str = "pcdump-final-pass-and-emitted-r1-accesses",
) -> dict:
    frame_size = _frame_size(instructions)
    access_ranges: dict[tuple[int, int, str], dict] = {}
    access_traces: list[dict] = []
    unresolved_symbolic_homes: list[dict] = []
    frame_seen = False
    symbolic_offsets = symbolic_offsets or {}
    expected_symbolic_offsets = expected_symbolic_offsets or {}

    for instr in instructions:
        if _is_frame_alloc(instr):
            frame_seen = True
            continue
        if _is_stack_pointer_restore(instr):
            continue
        symbolic_home = _symbolic_stack_home(instr.operands)
        original_operands = None
        if symbolic_home is not None:
            offset = symbolic_offsets.get(symbolic_home)
            if offset is None:
                unresolved_symbolic_homes.append({
                    "symbol": symbolic_home,
                    "opcode": instr.opcode,
                    "operands": instr.operands,
                    "pass": instr.pass_name,
                    "block_idx": instr.block_idx,
                    "instr_idx": instr.instr_idx,
                })
                continue
            original_operands = instr.operands
        else:
            offset = _stack_offset(instr.operands)
        if offset is None:
            continue
        size = _access_size(instr)
        if size is None:
            continue
        kind = _access_kind(instr)
        trace = {
            "offset": offset,
            "size": size,
            "kind": kind,
            "opcode": instr.opcode,
            "operands": instr.operands,
            "pass": instr.pass_name,
            "block_idx": instr.block_idx,
            "instr_idx": instr.instr_idx,
            "pre_frame": not frame_seen,
        }
        if original_operands is not None:
            trace["original_operands"] = original_operands
            trace["resolved_operands"] = _replace_symbolic_stack_home(
                original_operands,
                symbolic_home,
                offset,
            )
            trace["symbolic_home"] = symbolic_home
        access_traces.append(trace)
        if not frame_seen:
            continue
        if frame_size is not None and not (0 <= offset < frame_size):
            continue
        start = max(0, offset)
        end = offset + size
        if frame_size is not None:
            end = min(end, frame_size)
        if end <= start:
            continue
        access_ranges[(start, end, kind)] = {
            "start": start,
            "end": end,
            "size": end - start,
            "kind": kind,
        }

    used = list(access_ranges.values())
    implicit = []
    if frame_size is not None and frame_size >= 8:
        implicit.append({"start": 0, "end": 8, "size": 8, "kind": "abi-header"})
    unused = _unused_ranges(frame_size, [*used, *implicit])
    stack_objects = _stack_objects(
        frame_size=frame_size,
        access_ranges=used,
        implicit_ranges=implicit,
        unused_ranges=unused,
        access_traces=access_traces,
        expected_symbolic_offsets=expected_symbolic_offsets,
    )
    stack_home_assignments = _stack_home_assignments(
        access_traces,
        expected_symbolic_offsets=expected_symbolic_offsets,
    )
    stack_home_order_summary = _stack_home_order_summary(stack_home_assignments)
    stack_home_expected_order_summary = _stack_home_expected_order_summary(
        stack_home_assignments
    )
    stack_home_target_permutation = _stack_home_target_permutation(
        stack_home_expected_order_summary
    )

    frame = {
        "frame_size": frame_size,
        "access_ranges": sorted(
            used,
            key=lambda item: (item["start"], item["end"], item["kind"]),
        ),
        "accesses": access_traces,
        "unused_ranges": unused,
        "stack_objects": stack_objects,
        "stack_object_map_status": "best-effort-from-r1-accesses",
        "stack_home_assignments": stack_home_assignments,
        "stack_home_assignment_status": (
            "resolved-symbolic-homes"
            if stack_home_assignments
            else "unavailable-no-resolved-symbolic-homes"
        ),
        "stack_home_order_summary": stack_home_order_summary,
        "stack_home_expected_order_summary": stack_home_expected_order_summary,
        "stack_home_target_permutation": stack_home_target_permutation,
        "stack_home_reorder_guidance": _stack_home_reorder_guidance(
            stack_home_order_summary,
            expected_order_summary=stack_home_expected_order_summary,
            target_permutation=stack_home_target_permutation,
        ),
        "symbolic_home_map": [
            {"symbol": symbol, "offset": offset}
            for symbol, offset in sorted(symbolic_offsets.items())
        ],
        "expected_symbolic_home_map": [
            {"symbol": symbol, "offset": offset}
            for symbol, offset in sorted(expected_symbolic_offsets.items())
        ],
        "unresolved_symbolic_homes": unresolved_symbolic_homes,
    }
    frame["frame_allocation_trace"] = _frame_allocation_trace(
        frame,
        instrumentation_source=instrumentation_source,
    )
    return frame


def _stack_objects(
    *,
    frame_size: int | None,
    access_ranges: list[dict],
    implicit_ranges: list[dict],
    unused_ranges: list[dict],
    access_traces: list[dict],
    expected_symbolic_offsets: dict[str, int],
) -> list[dict]:
    objects: list[dict] = []
    access_count_by_range: dict[tuple[int, int, str], int] = {}
    opcodes_by_range: dict[tuple[int, int, str], set[str]] = {}
    symbols_by_range: dict[tuple[int, int, str], set[str]] = {}
    expected_symbols_by_range: dict[tuple[int, int, str], set[str]] = {}
    first_access_by_range: dict[tuple[int, int, str], dict] = {}
    for trace in access_traces:
        if trace.get("pre_frame"):
            continue
        offset = trace.get("offset")
        size = trace.get("size")
        kind = trace.get("kind")
        if offset is None or size is None or kind is None:
            continue
        start = max(0, offset)
        end = offset + size
        if frame_size is not None:
            if not (0 <= offset < frame_size):
                continue
            end = min(end, frame_size)
        if end <= start:
            continue
        key = (start, end, kind)
        access_count_by_range[key] = access_count_by_range.get(key, 0) + 1
        opcodes_by_range.setdefault(key, set()).add(str(trace.get("opcode") or ""))
        first_access_by_range.setdefault(key, {
            "opcode": trace.get("opcode"),
            "operands": trace.get("original_operands") or trace.get("operands"),
            "pass": trace.get("pass"),
            "block_idx": trace.get("block_idx"),
            "instr_idx": trace.get("instr_idx"),
        })
        symbol = trace.get("symbolic_home")
        if isinstance(symbol, str) and symbol:
            symbols_by_range.setdefault(key, set()).add(symbol)
            if symbol in expected_symbolic_offsets:
                expected_symbols_by_range.setdefault(key, set()).add(symbol)

    for item in implicit_ranges:
        objects.append({
            "start": item["start"],
            "end": item["end"],
            "size": item["size"],
            "kind": item["kind"],
            "source": "implicit",
            "boundary_confidence": "implicit",
            "ambiguous": False,
        })
    for item in access_ranges:
        key = (item["start"], item["end"], item["kind"])
        obj = {
            "start": item["start"],
            "end": item["end"],
            "size": item["size"],
            "kind": item["kind"],
            "source": "r1-access",
            "boundary_confidence": "access-width",
            "ambiguous": False,
            "access_count": access_count_by_range.get(key, 0),
            "opcodes": sorted(op for op in opcodes_by_range.get(key, set()) if op),
        }
        source_symbols = sorted(symbols_by_range.get(key, set()))
        if source_symbols:
            obj["source_symbols"] = source_symbols
            first_access = first_access_by_range.get(key)
            if first_access is not None:
                obj["first_access"] = first_access
        expected_source_symbols = sorted(expected_symbols_by_range.get(key, set()))
        if expected_source_symbols:
            obj["expected_source_symbols"] = expected_source_symbols
            obj["expected_source_offsets"] = {
                symbol: expected_symbolic_offsets[symbol]
                for symbol in expected_source_symbols
                if symbol in expected_symbolic_offsets
            }
        objects.append(obj)
    for item in unused_ranges:
        objects.append({
            "start": item["start"],
            "end": item["end"],
            "size": item["size"],
            "kind": "unused",
            "source": "gap",
            "boundary_confidence": "unused-gap",
            "ambiguous": False,
        })
    return sorted(
        objects,
        key=lambda item: (
            item["start"],
            item["end"],
            item["kind"] != "unused",
            item["kind"],
        ),
    )


def _frame_allocation_trace(
    frame: dict,
    *,
    instrumentation_source: str,
) -> dict:
    frame_size = frame.get("frame_size")
    if not isinstance(frame_size, int):
        return {
            "status": "unavailable-no-frame-size",
            "instrumentation_source": instrumentation_source,
            "allocator_pass_status": "not-located",
            "allocator_pass_status_reason": (
                "MWCC stack-frame allocator pass/symbol was not located; "
                "frame allocation trace could not be computed without a frame "
                "size"
            ),
            "object_count": 0,
            "objects": [],
            "validation": {
                "frame_size": frame_size,
                "covered_end": None,
                "frame_size_matches": False,
                "full_interval_coverage_matches": False,
                "object_overlap_count": 0,
                "object_non_overlap_matches": True,
                "emitted_access_count": len(frame.get("access_ranges") or []),
                "uncovered_accesses": [],
                "uncovered_access_count": 0,
                "r1_access_coverage_matches": False,
                "symbolic_stack_homes_present": bool(
                    frame.get("stack_home_assignments")
                ),
            },
            "limitations": _frame_allocation_trace_limitations(
                frame,
                instrumentation_source=instrumentation_source,
            ),
        }

    symbolic_order = {
        str(item["symbol"]): int(item["assignment_order"])
        for item in frame.get("stack_home_assignments") or []
        if isinstance(item, dict)
        and item.get("symbol")
        and isinstance(item.get("assignment_order"), int)
    }
    objects = [
        _frame_allocation_trace_object(item, symbolic_order)
        for item in frame.get("stack_objects") or []
        if isinstance(item, dict)
    ]
    objects = [
        item for item in objects
        if isinstance(item.get("start"), int)
        and isinstance(item.get("end"), int)
        and int(item["end"]) > int(item["start"])
    ]
    objects.sort(
        key=lambda item: (
            int(item["start"]),
            int(item["end"]),
            _allocation_origin_sort_key(str(item.get("origin_tag") or "")),
            str(item.get("symbol") or ""),
            str(item.get("kind") or ""),
        )
    )
    for index, item in enumerate(objects):
        item["layout_order"] = index

    validation = _frame_allocation_validation(frame, objects)
    return {
        "status": "computed",
        "instrumentation_source": instrumentation_source,
        "allocator_pass_status": "not-located",
        "allocator_pass_status_reason": (
            "MWCC stack-frame allocator pass/symbol was not located; this "
            "trace is reconstructed from final pcdump/asm r1 offsets"
        ),
        "object_count": len(objects),
        "objects": objects,
        "validation": validation,
        "limitations": _frame_allocation_trace_limitations(
            frame,
            instrumentation_source=instrumentation_source,
        ),
    }


def _frame_allocation_trace_object(
    obj: dict,
    symbolic_order: dict[str, int],
) -> dict:
    out = {
        "layout_order": None,
        "start": obj.get("start"),
        "end": obj.get("end"),
        "size": obj.get("size"),
        "kind": obj.get("kind"),
        "origin_tag": _allocation_origin_tag(obj),
        "source": obj.get("source"),
    }

    source_symbols = _object_source_symbols(obj)
    if source_symbols:
        out["source_symbols"] = source_symbols
        ordered_symbols = sorted(
            source_symbols,
            key=lambda symbol: (
                symbolic_order.get(symbol, 1_000_000),
                symbol,
            ),
        )
        out["symbol"] = ordered_symbols[0]
        symbolic_assignment_orders = {
            symbol: symbolic_order[symbol]
            for symbol in ordered_symbols
            if symbol in symbolic_order
        }
        if symbolic_assignment_orders:
            out["symbolic_assignment_order"] = next(
                iter(symbolic_assignment_orders.values())
            )
            out["symbolic_assignment_orders"] = symbolic_assignment_orders

    for key in (
        "expected_source_symbols",
        "expected_source_offsets",
        "access_count",
        "opcodes",
        "first_access",
        "boundary_confidence",
        "ambiguous",
    ):
        if key in obj:
            out[key] = obj[key]
    return out


def _allocation_origin_tag(obj: dict) -> str:
    kind = obj.get("kind")
    if kind == "abi-header":
        return "implicit-abi-header"
    if kind == "callee-save-gpr":
        return "callee-save-gpr"
    if kind == "callee-save-fpr":
        return "callee-save-fpr"
    if kind == "unused":
        return "frame-gap-or-alignment-pad"
    if _object_source_symbols(obj):
        return "symbolic-stack-home"
    if obj.get("source") == "r1-access":
        return "r1-access-local-or-temporary"
    return f"{obj.get('source') or 'unknown'}-{kind or 'stack-object'}"


def _allocation_origin_sort_key(origin_tag: str) -> int:
    order = {
        "implicit-abi-header": 0,
        "symbolic-stack-home": 1,
        "r1-access-local-or-temporary": 2,
        "callee-save-gpr": 3,
        "callee-save-fpr": 4,
        "frame-gap-or-alignment-pad": 5,
    }
    return order.get(origin_tag, 99)


def _frame_allocation_validation(frame: dict, objects: list[dict]) -> dict:
    frame_size = frame.get("frame_size")
    intervals = [
        (int(obj["start"]), int(obj["end"]), obj)
        for obj in objects
        if isinstance(obj.get("start"), int) and isinstance(obj.get("end"), int)
    ]
    intervals.sort(key=lambda item: (item[0], item[1]))
    gaps: list[dict] = []
    overlaps: list[dict] = []
    cursor = 0
    covered_end = 0
    if isinstance(frame_size, int):
        for start, end, obj in intervals:
            clipped_start = max(0, min(start, frame_size))
            clipped_end = max(0, min(end, frame_size))
            if clipped_end <= clipped_start:
                continue
            if clipped_start > cursor:
                gaps.append({
                    "start": cursor,
                    "end": clipped_start,
                    "size": clipped_start - cursor,
                })
                cursor = clipped_start
            elif clipped_start < cursor:
                overlaps.append({
                    "start": clipped_start,
                    "end": min(cursor, clipped_end),
                    "size": min(cursor, clipped_end) - clipped_start,
                    "object": {
                        "layout_order": obj.get("layout_order"),
                        "origin_tag": obj.get("origin_tag"),
                        "kind": obj.get("kind"),
                    },
                })
            cursor = max(cursor, clipped_end)
            covered_end = max(covered_end, clipped_end)
        if cursor < frame_size:
            gaps.append({"start": cursor, "end": frame_size, "size": frame_size - cursor})

    uncovered_accesses = [
        dict(access)
        for access in frame.get("access_ranges") or []
        if isinstance(access, dict)
        and not _access_range_covered_by_objects(access, objects)
    ]
    full_interval_coverage_matches = (
        isinstance(frame_size, int)
        and not gaps
        and covered_end == frame_size
    )
    return {
        "frame_size": frame_size,
        "covered_end": covered_end if isinstance(frame_size, int) else None,
        "frame_size_matches": full_interval_coverage_matches,
        "full_interval_coverage_matches": full_interval_coverage_matches,
        "coverage_gaps": gaps,
        "coverage_gap_count": len(gaps),
        "object_overlaps": overlaps,
        "object_overlap_count": len(overlaps),
        "object_non_overlap_matches": not overlaps,
        "emitted_access_count": len(frame.get("access_ranges") or []),
        "uncovered_accesses": uncovered_accesses,
        "uncovered_access_count": len(uncovered_accesses),
        "r1_access_coverage_matches": not uncovered_accesses,
        "symbolic_stack_homes_present": bool(frame.get("stack_home_assignments")),
    }


def _access_range_covered_by_objects(access: dict, objects: list[dict]) -> bool:
    start = access.get("start")
    end = access.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    for obj in objects:
        obj_start = obj.get("start")
        obj_end = obj.get("end")
        if (
            isinstance(obj_start, int)
            and isinstance(obj_end, int)
            and obj_start <= start
            and end <= obj_end
        ):
            return True
    return False


def _frame_allocation_trace_limitations(
    frame: dict,
    *,
    instrumentation_source: str,
) -> list[str]:
    limitations = [
        (
            "MWCC stack-frame allocator pass/symbol was not located; trace is "
            "reconstructed from final pcdump/asm artifacts"
        )
    ]
    if not frame.get("stack_home_assignments"):
        limitations.append(
            "No resolved symbolic stack homes were available; access-only "
            "objects keep conservative local-or-temporary origin tags"
        )
    if instrumentation_source == "asm-r1-accesses":
        limitations.append(
            "Raw asm input has final r1 offsets only; pcdump symbolic-home "
            "sequence is unavailable"
        )
    return limitations


def _stack_home_assignments(
    access_traces: list[dict],
    *,
    expected_symbolic_offsets: dict[str, int] | None = None,
) -> list[dict]:
    by_symbol: dict[str, dict] = {}
    expected_symbolic_offsets = expected_symbolic_offsets or {}
    for trace in access_traces:
        symbol = trace.get("symbolic_home")
        if not symbol or trace.get("pre_frame"):
            continue
        offset = trace.get("offset")
        size = trace.get("size")
        kind = trace.get("kind")
        if offset is None or size is None or kind is None:
            continue
        entry = by_symbol.get(symbol)
        if entry is None:
            entry = {
                "symbol": symbol,
                "offset": offset,
                "size": size,
                "kind": kind,
                "access_count": 0,
                "opcodes": set(),
                "first_access": {
                    "opcode": trace.get("opcode"),
                    "operands": trace.get("original_operands") or trace.get("operands"),
                    "pass": trace.get("pass"),
                    "block_idx": trace.get("block_idx"),
                    "instr_idx": trace.get("instr_idx"),
                },
                "_first_instr_idx": trace.get("instr_idx"),
            }
            by_symbol[symbol] = entry
        entry["access_count"] += 1
        opcode = trace.get("opcode")
        if opcode:
            entry["opcodes"].add(str(opcode))

    assignments = sorted(
        by_symbol.values(),
        key=lambda item: (
            item["first_access"].get("block_idx")
            if item["first_access"].get("block_idx") is not None
            else -1,
            item.get("_first_instr_idx")
            if item.get("_first_instr_idx") is not None
            else -1,
            item["symbol"],
        ),
    )
    out: list[dict] = []
    for order, item in enumerate(assignments):
        row = {
            "assignment_order": order,
            "symbol": item["symbol"],
            "offset": item["offset"],
            "size": item["size"],
            "kind": item["kind"],
            "access_count": item["access_count"],
            "opcodes": sorted(item["opcodes"]),
            "first_access": item["first_access"],
        }
        expected_offset = expected_symbolic_offsets.get(item["symbol"])
        if expected_offset is not None:
            row["expected_offset"] = expected_offset
            row["offset_delta"] = int(item["offset"]) - expected_offset
        out.append(row)
    return out


def _stack_home_order_summary(assignments: list[dict]) -> dict:
    if not assignments:
        return {
            "status": "unavailable-no-resolved-symbolic-homes",
            "has_order_mismatch": False,
            "assignment_count": 0,
            "max_abs_order_delta": 0,
            "assignments": [],
        }
    offset_order_by_symbol = {
        item["symbol"]: offset_order
        for offset_order, item in enumerate(sorted(
            assignments,
            key=lambda item: (
                item.get("offset"),
                item.get("size"),
                item.get("assignment_order"),
                item.get("symbol"),
            ),
        ))
    }
    rows: list[dict] = []
    max_abs_delta = 0
    for item in assignments:
        assignment_order = int(item["assignment_order"])
        offset_order = offset_order_by_symbol[item["symbol"]]
        order_delta = offset_order - assignment_order
        max_abs_delta = max(max_abs_delta, abs(order_delta))
        rows.append({
            "symbol": item["symbol"],
            "assignment_order": assignment_order,
            "offset_order": offset_order,
            "order_delta": order_delta,
            "offset": item["offset"],
            "size": item["size"],
            "kind": item["kind"],
        })
    return {
        "status": "computed",
        "has_order_mismatch": any(row["order_delta"] for row in rows),
        "assignment_count": len(rows),
        "max_abs_order_delta": max_abs_delta,
        "assignments": rows,
    }


def _stack_home_expected_order_summary(assignments: list[dict]) -> dict:
    expected_assignments = [
        item for item in assignments
        if item.get("expected_offset") is not None
    ]
    if not expected_assignments:
        return {
            "status": "unavailable-no-expected-symbolic-homes",
            "has_expected_offset_mismatch": False,
            "has_expected_order_mismatch": False,
            "assignment_count": 0,
            "max_abs_expected_order_delta": 0,
            "max_abs_offset_delta": 0,
            "assignments": [],
        }

    current_order_by_symbol = {
        item["symbol"]: offset_order
        for offset_order, item in enumerate(sorted(
            expected_assignments,
            key=lambda item: (
                item.get("offset"),
                item.get("size"),
                item.get("assignment_order"),
                item.get("symbol"),
            ),
        ))
    }
    expected_order_by_symbol = {
        item["symbol"]: offset_order
        for offset_order, item in enumerate(sorted(
            expected_assignments,
            key=lambda item: (
                item.get("expected_offset"),
                item.get("size"),
                item.get("assignment_order"),
                item.get("symbol"),
            ),
        ))
    }

    rows: list[dict] = []
    max_abs_order_delta = 0
    max_abs_offset_delta = 0
    for item in expected_assignments:
        assignment_order = int(item["assignment_order"])
        expected_offset_order = expected_order_by_symbol[item["symbol"]]
        expected_order_delta = expected_offset_order - assignment_order
        offset_delta = int(item["offset_delta"])
        max_abs_order_delta = max(max_abs_order_delta, abs(expected_order_delta))
        max_abs_offset_delta = max(max_abs_offset_delta, abs(offset_delta))
        rows.append({
            "symbol": item["symbol"],
            "assignment_order": assignment_order,
            "current_offset_order": current_order_by_symbol[item["symbol"]],
            "expected_offset_order": expected_offset_order,
            "expected_order_delta": expected_order_delta,
            "offset": item["offset"],
            "expected_offset": item["expected_offset"],
            "offset_delta": offset_delta,
            "size": item["size"],
            "kind": item["kind"],
        })

    return {
        "status": "computed",
        "has_expected_offset_mismatch": any(row["offset_delta"] for row in rows),
        "has_expected_order_mismatch": any(
            row["expected_order_delta"] for row in rows
        ),
        "assignment_count": len(rows),
        "max_abs_expected_order_delta": max_abs_order_delta,
        "max_abs_offset_delta": max_abs_offset_delta,
        "assignments": rows,
    }


def _stack_home_target_permutation(expected_order_summary: dict) -> dict:
    if expected_order_summary.get("status") != "computed":
        return {
            "status": "unavailable-no-expected-symbolic-homes",
            "needs_permutation": False,
            "symbol_count": 0,
            "misplaced_count": 0,
            "current_offset_order": [],
            "expected_offset_order": [],
            "expected_to_current_positions": [],
            "moves": [],
            "cycles": [],
        }

    rows = [
        row for row in expected_order_summary.get("assignments") or []
        if isinstance(row, dict)
    ]
    current_rows = sorted(
        rows,
        key=lambda row: (
            row.get("current_offset_order"),
            row.get("symbol"),
        ),
    )
    expected_rows = sorted(
        rows,
        key=lambda row: (
            row.get("expected_offset_order"),
            row.get("symbol"),
        ),
    )
    current_order = [str(row["symbol"]) for row in current_rows]
    expected_order = [str(row["symbol"]) for row in expected_rows]
    current_position_by_symbol = {
        symbol: position for position, symbol in enumerate(current_order)
    }
    expected_position_by_symbol = {
        symbol: position for position, symbol in enumerate(expected_order)
    }

    moves: list[dict] = []
    for row in expected_rows:
        symbol = str(row["symbol"])
        current_position = current_position_by_symbol[symbol]
        expected_position = expected_position_by_symbol[symbol]
        moves.append({
            "symbol": symbol,
            "current_position": current_position,
            "expected_position": expected_position,
            "position_delta": expected_position - current_position,
            "current_offset": row.get("offset"),
            "expected_offset": row.get("expected_offset"),
            "offset_delta": row.get("offset_delta"),
        })

    current_to_expected_position = {
        current_position_by_symbol[symbol]: expected_position_by_symbol[symbol]
        for symbol in current_order
    }
    cycles: list[dict] = []
    visited: set[int] = set()
    for start in range(len(current_order)):
        if start in visited:
            continue
        cycle_positions: list[int] = []
        position = start
        while position not in visited:
            visited.add(position)
            cycle_positions.append(position)
            position = current_to_expected_position[position]
        if len(cycle_positions) <= 1:
            continue
        cycles.append({
            "symbols": [current_order[position] for position in cycle_positions],
            "current_positions": cycle_positions,
            "expected_positions": [
                current_to_expected_position[position]
                for position in cycle_positions
            ],
        })

    return {
        "status": "computed",
        "needs_permutation": current_order != expected_order,
        "symbol_count": len(current_order),
        "misplaced_count": sum(
            1 for move in moves
            if move["current_position"] != move["expected_position"]
        ),
        "current_offset_order": current_order,
        "expected_offset_order": expected_order,
        "expected_to_current_positions": [
            current_position_by_symbol[symbol]
            for symbol in expected_order
        ],
        "moves": moves,
        "cycles": cycles,
    }


def _stack_home_reorder_guidance(
    order_summary: dict,
    *,
    expected_order_summary: dict | None = None,
    target_permutation: dict | None = None,
) -> dict:
    if order_summary.get("status") != "computed":
        return {
            "status": "unavailable",
            "verdict": "no-resolved-symbolic-homes",
            "reason": (
                "requires resolved symbolic stack homes before source reorder "
                "or ceiling evidence can be evaluated"
            ),
            "candidate_levers": [],
            "next_steps": [],
        }
    if (
        expected_order_summary
        and expected_order_summary.get("status") == "computed"
        and expected_order_summary.get("has_expected_offset_mismatch")
    ):
        displaced = [
            row for row in expected_order_summary.get("assignments") or []
            if row.get("offset_delta")
        ]
        displaced.sort(
            key=lambda row: (
                abs(int(row.get("offset_delta") or 0)),
                abs(int(row.get("expected_order_delta") or 0)),
                -int(row.get("assignment_order") or 0),
            ),
            reverse=True,
        )
        target_symbols = [str(row.get("symbol")) for row in displaced[:5]]
        probe_plan = _stack_home_probe_plan(
            target_symbols,
            target_permutation=target_permutation,
        )
        return {
            "status": "source-reorder-probe-needed",
            "verdict": "unknown-unvalidated",
            "reason": (
                "resolved stack-home offsets differ from target asm offsets; "
                "validate source reorder levers before declaring an internal ceiling"
            ),
            "candidate_levers": [
                {
                    "kind": "first-use-order",
                    "description": (
                        "reorder first materialized uses of displaced stack homes"
                    ),
                    "target_symbols": target_symbols,
                },
                {
                    "kind": "lifetime-boundary",
                    "description": (
                        "move declarations or use blocks to extend/shorten "
                        "stack-home lifetimes"
                    ),
                    "target_symbols": target_symbols,
                },
                {
                    "kind": "decl-order-proxy",
                    "description": (
                        "try declaration-order changes only as a proxy after "
                        "first-use/lifetime probes"
                    ),
                    "target_symbols": target_symbols,
                },
            ],
            "probe_plan": probe_plan,
            "next_steps": [
                "melee-agent debug mutate lifetime-layout -f <function> --compile-probes",
                "melee-agent debug mutate decl-orders <function> --strategy all --json",
            ],
        }
    if not order_summary.get("has_order_mismatch"):
        return {
            "status": "not-needed",
            "verdict": "assignment-order-matches-offset-order",
            "reason": "resolved stack-home assignment order already matches final offset order",
            "candidate_levers": [],
            "next_steps": [],
        }
    displaced = [
        row for row in order_summary.get("assignments") or []
        if row.get("order_delta")
    ]
    displaced.sort(
        key=lambda row: (
            abs(int(row.get("order_delta") or 0)),
            -int(row.get("assignment_order") or 0),
        ),
        reverse=True,
    )
    target_symbols = [str(row.get("symbol")) for row in displaced[:5]]
    return {
        "status": "source-reorder-probe-needed",
        "verdict": "unknown-unvalidated",
        "reason": (
            "stack-home assignment order differs from final offset order; "
            "validate source reorder levers before declaring an internal ceiling"
        ),
        "candidate_levers": [
            {
                "kind": "first-use-order",
                "description": "reorder first materialized uses of displaced stack homes",
                "target_symbols": target_symbols,
            },
            {
                "kind": "lifetime-boundary",
                "description": "move declarations or use blocks to extend/shorten stack-home lifetimes",
                "target_symbols": target_symbols,
            },
            {
                "kind": "decl-order-proxy",
                "description": "try declaration-order changes only as a proxy after first-use/lifetime probes",
                "target_symbols": target_symbols,
            },
        ],
        "probe_plan": _stack_home_probe_plan(target_symbols),
        "next_steps": [
            "melee-agent debug mutate lifetime-layout -f <function> --compile-probes",
            "melee-agent debug mutate decl-orders <function> --strategy all --json",
        ],
    }


def _stack_home_probe_plan(
    target_symbols: list[str],
    *,
    target_permutation: dict | None = None,
) -> dict:
    current_order: list[str] = []
    expected_order: list[str] = []
    cycles: list[dict] = []
    if target_permutation and target_permutation.get("status") == "computed":
        raw_current_order = target_permutation.get("current_offset_order")
        raw_expected_order = target_permutation.get("expected_offset_order")
        raw_cycles = target_permutation.get("cycles")
        if isinstance(raw_current_order, list):
            current_order = [str(symbol) for symbol in raw_current_order]
        if isinstance(raw_expected_order, list):
            expected_order = [str(symbol) for symbol in raw_expected_order]
        if isinstance(raw_cycles, list):
            cycles = [
                cycle for cycle in raw_cycles
                if isinstance(cycle, dict)
            ]

    return {
        "status": "ready",
        "objective": "move stack homes into expected target offset order",
        "target_symbols": target_symbols,
        "current_offset_order": current_order,
        "expected_offset_order": expected_order,
        "cycles": cycles,
        "operator_priority": [
            "declaration-use-distance",
            "block-scope",
            "call-argument-tempization",
            "decl-orders",
        ],
        "suggested_commands": [
            {
                "kind": "lifetime-layout",
                "command": (
                    "melee-agent debug mutate lifetime-layout -f <function> "
                    "--operator declaration-use-distance --operator block-scope "
                    "--operator call-argument-tempization --compile-probes --json"
                ),
            },
            {
                "kind": "decl-orders",
                "command": (
                    "melee-agent debug mutate decl-orders <function> "
                    "--strategy all --json"
                ),
            },
        ],
    }


def _stack_home_probe_targets(frame_report: dict) -> list[dict]:
    current = frame_report.get("current") if isinstance(frame_report, dict) else None
    if not isinstance(current, dict):
        return []
    permutation = current.get("stack_home_target_permutation")
    if not isinstance(permutation, dict) or permutation.get("status") != "computed":
        return []
    targets: list[dict] = []
    for move in permutation.get("moves") or []:
        if not isinstance(move, dict):
            continue
        current_offset = move.get("current_offset")
        expected_offset = move.get("expected_offset")
        if current_offset is None or expected_offset is None:
            continue
        if current_offset == expected_offset:
            continue
        targets.append({
            "symbol": move.get("symbol"),
            "current_offset": current_offset,
            "expected_offset": expected_offset,
            "offset_delta": move.get("offset_delta"),
            "current_position": move.get("current_position"),
            "expected_position": move.get("expected_position"),
        })
    return targets


def _score_stack_home_probe_variant(
    targets: list[dict],
    variant: dict[str, Any],
) -> dict:
    localizer = variant.get("stack_slot_localizer")
    status = str(variant.get("status", "unknown"))
    localizer_measured = isinstance(localizer, dict)
    statuses: list[dict] = []
    fixed_count = 0
    for target in targets:
        observed = _find_stack_home_probe_mismatch(localizer, target)
        target_fixed = localizer_measured and observed is None
        if target_fixed:
            fixed_count += 1
        statuses.append({
            "symbol": target.get("symbol"),
            "current_offset": target.get("current_offset"),
            "expected_offset": target.get("expected_offset"),
            "target_fixed": target_fixed,
            "observed_mismatch": observed,
        })

    remaining = len(targets) - fixed_count
    target_fixed = bool(targets) and fixed_count == len(targets)
    return {
        "label": variant.get("label") or variant.get("variant_id") or variant.get("id"),
        "operator": variant.get("operator") or variant.get("kind"),
        "status": status,
        "target_movement_measured": localizer_measured,
        "target_fixed": target_fixed,
        "fixed_count": fixed_count,
        "target_count": len(targets),
        "movement_score": fixed_count / len(targets) if targets else 0.0,
        "remaining_target_mismatch_count": remaining,
        "target_statuses": statuses,
        "match_percent": variant.get("match_percent")
        if variant.get("match_percent") is not None
        else variant.get("final_match_percent"),
        "stack_slot_mismatch_count": _stack_slot_mismatch_count(localizer),
        "stack_slot_error": variant.get("stack_slot_error"),
    }


def _find_stack_home_probe_mismatch(
    localizer: Any,
    target: dict,
) -> dict | None:
    if not isinstance(localizer, dict):
        return None
    current = target.get("current_offset")
    expected = target.get("expected_offset")
    for mismatch in localizer.get("mismatches") or []:
        if not isinstance(mismatch, dict):
            continue
        if mismatch.get("current_offset") != current:
            continue
        if mismatch.get("expected_offset") != expected:
            continue
        return dict(mismatch)
    return None


def _stack_slot_mismatch_count(localizer: Any) -> int | None:
    if not isinstance(localizer, dict):
        return None
    count = localizer.get("mismatch_count")
    if isinstance(count, int):
        return count
    mismatches = localizer.get("mismatches")
    if isinstance(mismatches, list):
        return len(mismatches)
    return None


def _first_stack_object_divergence(
    current: dict,
    expected: dict | None,
    frame_delta: int | None,
) -> dict:
    if expected is None:
        return {"status": "expected-unavailable"}
    current_objects = _occupied_stack_objects(current)
    expected_objects = _occupied_stack_objects(expected)
    max_len = max(len(current_objects), len(expected_objects))
    for index in range(max_len):
        cur = current_objects[index] if index < len(current_objects) else None
        exp = expected_objects[index] if index < len(expected_objects) else None
        if cur == exp:
            continue
        attribution = _source_attribution(cur, exp)
        cause = _frame_divergence_cause_hypothesis(
            cur,
            exp,
            frame_delta,
            attribution=attribution,
        )
        return {
            "status": "diverged",
            "index": index,
            "reason": _stack_object_divergence_reason(cur, exp),
            "current": cur,
            "expected": exp,
            "source_attribution": attribution,
            "cause_hypothesis": cause,
            "verdict": _frame_divergence_verdict(cause),
            "frame_transform_probe_plan": _frame_transform_probe_plan(cause),
        }
    if frame_delta:
        attribution = _source_attribution(None, None)
        cause = _frame_size_only_cause_hypothesis(frame_delta)
        return {
            "status": "frame-size-only",
            "frame_delta": frame_delta,
            "source_attribution": attribution,
            "cause_hypothesis": cause,
            "verdict": _frame_divergence_verdict(cause),
            "frame_transform_probe_plan": _frame_transform_probe_plan(cause),
        }
    return {"status": "matched"}


def _frame_divergence_cause_hypothesis(
    current: dict | None,
    expected: dict | None,
    frame_delta: int | None,
    *,
    attribution: dict | None = None,
) -> dict:
    source_object = _primary_source_object(attribution)
    source_symbol = (
        source_object.get("symbol")
        if isinstance(source_object, dict)
        else None
    )
    if current is None:
        if source_symbol:
            return {
                "status": "heuristic",
                "kind": "missing-source-local-home",
                "confidence": "medium",
                "reason": (
                    "expected has an attributed stack object with no current "
                    "counterpart; inspect missing local home, call-argument "
                    "temp, or saved range"
                ),
                "source_object_symbol": source_symbol,
                "frame_delta": frame_delta,
            }
        return {
            "status": "heuristic",
            "kind": "missing-current-stack-object",
            "confidence": "medium",
            "reason": (
                "expected has an occupied stack object with no current counterpart; "
                "look for a missing local home, call-argument temp, or saved range"
            ),
            "frame_delta": frame_delta,
        }
    if expected is None:
        if source_symbol:
            return {
                "status": "heuristic",
                "kind": "extra-source-local-home",
                "confidence": "medium",
                "reason": (
                    "current has an attributed stack object with no expected "
                    "counterpart; inspect extra local home, call-argument "
                    "temp, address-taking, or spill"
                ),
                "source_object_symbol": source_symbol,
                "frame_delta": frame_delta,
            }
        return {
            "status": "heuristic",
            "kind": "extra-current-stack-object",
            "confidence": "medium",
            "reason": (
                "current has an occupied stack object with no expected counterpart; "
                "look for an extra local home, call-argument temp, or spill"
            ),
            "frame_delta": frame_delta,
        }
    current_size = current.get("size")
    expected_size = expected.get("size")
    current_kind = current.get("kind")
    expected_kind = expected.get("kind")
    offset_delta = _object_offset_delta(current, expected)
    if current_size == expected_size and current_kind == expected_kind:
        if source_symbol:
            return {
                "status": "heuristic",
                "kind": "lifetime-or-ordering-shift",
                "confidence": str(attribution.get("confidence") or "medium")
                if isinstance(attribution, dict)
                else "medium",
                "reason": (
                    "attributed stack object has the same shape but different "
                    "offsets; inspect local lifetime, first-use order, "
                    "address-taking, or alignment"
                ),
                "source_object_symbol": source_symbol,
                "current_expected_offset_delta": offset_delta,
                "frame_delta": frame_delta,
            }
        return {
            "status": "heuristic",
            "kind": "stack-object-offset-shift",
            "confidence": "medium",
            "reason": (
                "current and expected stack objects have the same shape but "
                "different offsets; inspect local lifetime, ordering, or alignment"
            ),
            "current_expected_offset_delta": offset_delta,
            "frame_delta": frame_delta,
        }
    if current_size != expected_size:
        if source_symbol:
            return {
                "status": "heuristic",
                "kind": "type-size-or-alignment",
                "confidence": "medium",
                "reason": (
                    "attributed stack object differs in size; inspect type "
                    "size, array extent, struct layout, or alignment"
                ),
                "source_object_symbol": source_symbol,
                "current_size": current_size,
                "expected_size": expected_size,
                "frame_delta": frame_delta,
            }
        return {
            "status": "heuristic",
            "kind": "stack-object-size-or-alignment",
            "confidence": "medium",
            "reason": (
                "corresponding stack objects differ in size; inspect type size, "
                "array extent, struct layout, or alignment"
            ),
            "current_size": current_size,
            "expected_size": expected_size,
            "frame_delta": frame_delta,
        }
    return {
        "status": "heuristic",
        "kind": "stack-object-kind-change",
        "confidence": "low",
        "reason": (
            "corresponding stack objects differ in kind; inspect saved-register, "
            "spill, and local-home attribution"
        ),
        "current_kind": current_kind,
        "expected_kind": expected_kind,
        "frame_delta": frame_delta,
    }


def _frame_size_only_cause_hypothesis(frame_delta: int) -> dict:
    return {
        "status": "heuristic",
        "kind": "extra-frame-reservation-or-alignment",
        "confidence": "medium",
        "reason": (
            "frame sizes differ without an occupied-object divergence; the "
            "delta is likely an implicit reservation, alignment gap, or "
            "unreferenced local home"
        ),
        "frame_delta": frame_delta,
    }


def _frame_transform_probe_plan(cause: dict) -> dict:
    kind = str(cause.get("kind") or "unknown")
    if cause.get("status") != "heuristic":
        return {
            "status": "unavailable",
            "objective": "reduce frame/local-area divergence toward expected",
            "cause_kind": kind,
            "reason": "frame divergence cause has not been classified heuristically",
            "operator_priority": [],
            "suggested_commands": [],
        }

    operators = _frame_transform_operator_priority(kind)
    operator_flags = " ".join(f"--operator {operator}" for operator in operators)
    return {
        "status": "ready",
        "objective": "reduce frame/local-area divergence toward expected",
        "cause_kind": kind,
        "operator_priority": operators,
        "suggested_commands": [
            {
                "kind": "suggest-frame",
                "command": "melee-agent debug suggest frame -f <function> --json",
            },
            {
                "kind": "frame-transform-search",
                "command": (
                    "melee-agent debug mutate frame-transform-search -f <function> "
                    f"{operator_flags} --compile-probes --json"
                ),
            },
            {
                "kind": "tier3-frame-search",
                "command": "melee-agent debug mutate search -f <function> --budget 5",
            },
        ],
        "validation": {
            "status": "required",
            "command": (
                "melee-agent debug inspect frame-reservations -f <function> "
                "--expected-asm <expected.s> --probe-results-json "
                "<frame-transform-search.json> --json"
            ),
        },
    }


def _frame_transform_operator_priority(cause_kind: str) -> list[str]:
    if cause_kind in {"stack-object-offset-shift", "lifetime-or-ordering-shift"}:
        return [
            "frame-local-dematerialize",
            "declaration-use-distance",
            "block-scope",
            "frame-direct-literal-at-final-fp-call",
            "frame-split-fp-const-lifetime",
        ]
    if cause_kind == "extra-frame-reservation-or-alignment":
        return [
            "frame-reservation-pad-stack",
            "frame-local-dematerialize",
            "frame-magic-scratch-relocation",
            "frame-split-fp-const-lifetime",
            "declaration-use-distance",
            "block-scope",
        ]
    if cause_kind in {"stack-object-size-or-alignment", "type-size-or-alignment"}:
        return [
            "frame-local-dematerialize",
            "frame-split-fp-const-lifetime",
            "frame-direct-literal-at-final-fp-call",
            "declaration-use-distance",
            "block-scope",
        ]
    if cause_kind in {
        "extra-current-stack-object",
        "missing-current-stack-object",
        "extra-source-local-home",
        "missing-source-local-home",
    }:
        return [
            "frame-local-dematerialize",
            "declaration-use-distance",
            "block-scope",
            "call-argument-tempization",
            "frame-directed",
        ]
    return [
        "declaration-use-distance",
        "block-scope",
        "decl-orders",
    ]


def _source_attribution(
    current: dict | None,
    expected: dict | None,
) -> dict:
    current_symbols = _object_source_symbols(current)
    expected_symbols = (
        _object_expected_source_symbols(current) or _object_source_symbols(expected)
    )
    source_objects = _source_objects_from_divergence(
        current,
        expected,
        current_symbols=current_symbols,
        expected_symbols=expected_symbols,
    )
    if current_symbols or expected_symbols:
        primary = source_objects[0] if source_objects else None
        confidence = "medium"
        if isinstance(primary, dict):
            if (
                primary.get("current_offset") is not None
                and primary.get("current_offset") == primary.get("expected_offset")
            ):
                confidence = "high"
        return {
            "status": "source-object-attributed",
            "identity_kind": "symbolic-stack-home",
            "confidence": confidence,
            "current_symbols": current_symbols,
            "expected_symbols": expected_symbols,
            "primary_source_object": primary,
            "source_objects": source_objects,
            "reason": (
                "diverging stack object maps to resolved symbolic stack-home identity"
            ),
        }
    return {
        "status": "unattributed",
        "identity_kind": None,
        "confidence": "low",
        "current_symbols": [],
        "expected_symbols": [],
        "primary_source_object": None,
        "source_objects": [],
        "unresolved_dependency": "mwcc-stack-home-origin-tags",
        "reason": (
            "stack-object divergence is classified, but exact source object "
            "identity requires MWCC stack-home origin instrumentation"
        ),
    }


def _source_objects_from_divergence(
    current: dict | None,
    expected: dict | None,
    *,
    current_symbols: list[str],
    expected_symbols: list[str],
) -> list[dict]:
    symbols = list(dict.fromkeys([*current_symbols, *expected_symbols]))
    objects: list[dict] = []
    for symbol in symbols:
        in_current = symbol in current_symbols
        in_expected = symbol in expected_symbols
        side = "both" if in_current and in_expected else (
            "current" if in_current else "expected"
        )
        current_offset = current.get("start") if isinstance(current, dict) else None
        expected_offset = _expected_offset_for_source_symbol(
            symbol,
            current,
            expected,
        )
        if not isinstance(current_offset, int):
            current_offset = None
        if not isinstance(expected_offset, int):
            expected_offset = None
        obj = {
            "symbol": symbol,
            "identity_kind": "symbolic-stack-home",
            "side": side,
            "current_offset": current_offset,
            "expected_offset": expected_offset,
            "offset_delta": (
                current_offset - expected_offset
                if current_offset is not None and expected_offset is not None
                else None
            ),
            "size": _source_object_value(current, expected, "size"),
            "kind": _source_object_value(current, expected, "kind"),
            "opcodes": (
                current.get("opcodes")
                if isinstance(current, dict) and isinstance(current.get("opcodes"), list)
                else []
            ),
            "access_count": (
                current.get("access_count")
                if isinstance(current, dict) and isinstance(current.get("access_count"), int)
                else 0
            ),
            "first_access": (
                current.get("first_access")
                if isinstance(current, dict) and isinstance(current.get("first_access"), dict)
                else None
            ),
        }
        objects.append(obj)
    return objects


def _expected_offset_for_source_symbol(
    symbol: str,
    current: dict | None,
    expected: dict | None,
) -> int | None:
    if isinstance(current, dict):
        offsets = current.get("expected_source_offsets")
        if isinstance(offsets, dict):
            value = offsets.get(symbol)
            if isinstance(value, int):
                return value
    if isinstance(expected, dict):
        symbols = expected.get("source_symbols")
        if isinstance(symbols, list) and symbol in symbols:
            value = expected.get("start")
            if isinstance(value, int):
                return value
    return None


def _source_object_value(
    current: dict | None,
    expected: dict | None,
    key: str,
):
    if isinstance(current, dict) and current.get(key) is not None:
        return current.get(key)
    if isinstance(expected, dict):
        return expected.get(key)
    return None


def _primary_source_object(attribution: dict | None) -> dict | None:
    if not isinstance(attribution, dict):
        return None
    primary = attribution.get("primary_source_object")
    return primary if isinstance(primary, dict) else None


def _object_source_symbols(item: dict | None) -> list[str]:
    if not isinstance(item, dict):
        return []
    symbols = item.get("source_symbols")
    if not isinstance(symbols, list):
        return []
    return [str(symbol) for symbol in symbols if symbol]


def _object_expected_source_symbols(item: dict | None) -> list[str]:
    if not isinstance(item, dict):
        return []
    symbols = item.get("expected_source_symbols")
    if not isinstance(symbols, list):
        return []
    return [str(symbol) for symbol in symbols if symbol]


def _frame_divergence_verdict(cause: dict) -> dict:
    kind = cause.get("kind")
    confidence = cause.get("confidence", "low")
    if kind in {
        "stack-object-offset-shift",
        "stack-object-size-or-alignment",
        "extra-frame-reservation-or-alignment",
        "extra-current-stack-object",
        "missing-current-stack-object",
        "lifetime-or-ordering-shift",
        "type-size-or-alignment",
        "extra-source-local-home",
        "missing-source-local-home",
    }:
        source_symbol = cause.get("source_object_symbol")
        if not source_symbol:
            return {
                "status": "unresolved-source-attribution",
                "reason": (
                    f"heuristic cause {kind} needs MWCC stack-home origin "
                    "instrumentation or validating probe evidence before "
                    "source-reachable vs ceiling can be decided"
                ),
                "confidence": confidence,
                "unresolved_dependency": "mwcc-stack-home-origin-tags",
            }
        return {
            "status": "source-reachable-candidate",
            "reason": (
                f"heuristic cause {kind}"
                + f" for {source_symbol}"
                + " is addressable by targeted frame/lifetime source probes"
            ),
            "confidence": confidence,
            "source_object_symbol": source_symbol,
        }
    return {
        "status": "unknown",
        "reason": (
            f"heuristic cause {kind} needs source-object attribution before "
            "source-reachable vs ceiling can be decided"
        ),
        "confidence": confidence,
    }


def _object_offset_delta(current: dict, expected: dict) -> int | None:
    current_start = current.get("start")
    expected_start = expected.get("start")
    if not isinstance(current_start, int) or not isinstance(expected_start, int):
        return None
    return current_start - expected_start


def _occupied_stack_objects(frame: dict) -> list[dict]:
    return [
        {
            key: item[key]
            for key in (
                "start",
                "end",
                "size",
                "kind",
                "source",
                "boundary_confidence",
            "ambiguous",
            "source_symbols",
            "expected_source_symbols",
            "expected_source_offsets",
            "access_count",
            "opcodes",
            "first_access",
        )
            if key in item
        }
        for item in frame.get("stack_objects") or []
        if item.get("kind") not in {"unused", "abi-header"}
    ]


def _stack_object_divergence_reason(
    current: dict | None,
    expected: dict | None,
) -> str:
    if current is None:
        return "missing-current-object"
    if expected is None:
        return "extra-current-object"
    for key in ("start", "end", "size", "kind"):
        if current.get(key) != expected.get(key):
            return f"{key}-differs"
    return "metadata-differs"


def _resolve_symbolic_stack_homes(
    symbolic_instructions: list[_AsmInstruction],
    concrete_instructions: list[_AsmInstruction],
) -> dict[str, int]:
    if not concrete_instructions:
        return {}
    resolved: dict[str, int] = {}
    concrete_cursor = 0
    for instr in symbolic_instructions:
        symbol = _symbolic_stack_home(instr.operands)
        if symbol is None:
            continue
        match_idx = _find_concrete_stack_match(
            instr,
            concrete_instructions,
            start=concrete_cursor,
        )
        if match_idx is None:
            continue
        concrete_cursor = match_idx + 1
        offset = _stack_offset(concrete_instructions[match_idx].operands)
        if offset is None:
            continue
        prior = resolved.get(symbol)
        if prior is None:
            resolved[symbol] = offset
        elif prior != offset:
            resolved.pop(symbol, None)
    return resolved


def _find_concrete_stack_match(
    symbolic: _AsmInstruction,
    concrete_instructions: list[_AsmInstruction],
    *,
    start: int,
) -> int | None:
    signature = _stack_match_signature(symbolic)
    if signature is None:
        return None
    for idx in range(start, len(concrete_instructions)):
        concrete = concrete_instructions[idx]
        if _stack_offset(concrete.operands) is None:
            continue
        if _stack_match_signature(concrete) == signature:
            return idx
    for idx, concrete in enumerate(concrete_instructions):
        if _stack_offset(concrete.operands) is None:
            continue
        if _stack_match_signature(concrete) == signature:
            return idx
    return None


def _stack_match_signature(
    instr: _AsmInstruction,
) -> tuple[str, tuple[str, int] | None] | None:
    if _access_size(instr) is None:
        return None
    return instr.opcode, _first_reg(instr.operands)


def _frame_size(instructions: Iterable[_AsmInstruction]) -> int | None:
    for instr in instructions:
        if not _is_frame_alloc(instr):
            continue
        match = _FRAME_RE.search(instr.operands)
        if match:
            return abs(int(match.group(1), 0))
    return None


def _is_frame_alloc(instr: _AsmInstruction) -> bool:
    return instr.opcode == "stwu" and instr.operands.replace(" ", "").startswith("r1,")


def _is_stack_pointer_restore(instr: _AsmInstruction) -> bool:
    return instr.opcode == "addi" and instr.operands.replace(" ", "").startswith("r1,r1,")


def _stack_offset(operands: str) -> int | None:
    match = _STACK_REF_RE.search(operands)
    if match is None:
        return None
    return int(match.group("offset"), 0)


def _symbolic_stack_home(operands: str) -> str | None:
    match = _SYMBOLIC_STACK_REF_RE.search(operands)
    if match is None:
        return None
    return match.group("symbol")


def _replace_symbolic_stack_home(operands: str, symbol: str, offset: int) -> str:
    return operands.replace(f"{symbol}(r1)", f"{offset}(r1)", 1)


def _access_size(instr: _AsmInstruction) -> int | None:
    opcode = instr.opcode
    if opcode in {"lbz", "stb", "lha", "lhz", "sth"}:
        return 1 if opcode in {"lbz", "stb"} else 2
    if opcode in {"lwz", "stw", "lfs", "stfs"}:
        return 4
    if opcode in {"lfd", "stfd", "psq_l", "psq_st"}:
        return 8
    if opcode in {"lmw", "stmw"}:
        reg = _first_reg(instr.operands)
        if reg is None or reg[0] != "r":
            return None
        return max(0, 32 - reg[1]) * 4
    return None


def _access_kind(instr: _AsmInstruction) -> str:
    first = _first_reg(instr.operands)
    if instr.opcode in {"lmw", "stmw"}:
        return "callee-save-gpr"
    if instr.opcode in {"lfd", "stfd"} and first and first[0] == "f" and first[1] >= 14:
        return "callee-save-fpr"
    if instr.opcode in {"lwz", "stw"} and first == ("r", 0):
        return "link-register-save"
    return "local-or-temporary"


def _first_reg(operands: str) -> tuple[str, int] | None:
    match = _REG_OPERAND_RE.search(operands)
    if match is None:
        return None
    return (match.group("class"), int(match.group("num")))


def _unused_ranges(frame_size: int | None, ranges: list[dict]) -> list[dict]:
    if frame_size is None:
        return []
    intervals = sorted(
        (max(0, item["start"]), min(frame_size, item["end"]))
        for item in ranges
        if item["end"] > 0 and item["start"] < frame_size
    )
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    out: list[dict] = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            out.append({"start": cursor, "end": start, "size": start - cursor})
        cursor = max(cursor, end)
    if cursor < frame_size:
        out.append({"start": cursor, "end": frame_size, "size": frame_size - cursor})
    return out


def _first_non_abi_access_offset(side: dict) -> int | None:
    starts = [
        item["start"]
        for item in side.get("access_ranges", [])
        if item.get("start", 0) >= 8
    ]
    return min(starts) if starts else None


def _extra_low_frame_reservation(current: dict, expected: dict | None) -> dict | None:
    if expected is None:
        return None
    cur_first = _first_non_abi_access_offset(current)
    exp_first = _first_non_abi_access_offset(expected)
    if cur_first is None or exp_first is None or exp_first <= cur_first:
        return None
    accesses = [
        item
        for item in current.get("accesses", [])
        if not item.get("pre_frame") and cur_first <= item["offset"] < exp_first
        and (
            current.get("frame_size") is None
            or item["offset"] < current["frame_size"]
        )
        and item.get("kind") not in {
            "callee-save-gpr",
            "callee-save-fpr",
            "link-register-save",
        }
    ]
    return {
        "start": cur_first,
        "end": exp_first,
        "size": exp_first - cur_first,
        "origin": "implicit-frame-reservation",
        "current_accesses_in_range": accesses,
    }


def _current_low_frame_expansion(
    current: dict,
    expected: dict | None,
    frame_delta: int | None,
) -> dict | None:
    if expected is None or frame_delta is None or frame_delta >= 0:
        return None
    cur_first = _first_non_abi_access_offset(current)
    exp_first = _first_non_abi_access_offset(expected)
    if cur_first is None or exp_first is None or cur_first <= exp_first:
        return None
    frame_growth = -frame_delta
    low_home_size = cur_first - exp_first
    if low_home_size <= 0 or frame_growth < low_home_size:
        return None
    accesses = [
        item
        for item in current.get("accesses", [])
        if not item.get("pre_frame") and exp_first <= item["offset"] < cur_first
        and (
            current.get("frame_size") is None
            or item["offset"] < current["frame_size"]
        )
        and item.get("kind") not in {
            "callee-save-gpr",
            "callee-save-fpr",
            "link-register-save",
        }
    ]
    return {
        "start": exp_first,
        "end": cur_first,
        "size": low_home_size,
        "origin": "implicit-current-low-local-home",
        "frame_growth_bytes": frame_growth,
        "alignment_growth_bytes": frame_growth - low_home_size,
        "first_non_abi_access_expected": exp_first,
        "first_non_abi_access_current": cur_first,
        "current_accesses_in_range": accesses,
    }


def _summary(
    function: str,
    current: dict,
    expected: dict | None,
    frame_delta: int | None,
    extra: dict | None,
    current_low_expansion: dict | None,
) -> str:
    cur_frame = current.get("frame_size")
    if expected is None or expected.get("frame_size") is None:
        return f"{function}: current frame={cur_frame}; expected frame unavailable"
    exp_frame = expected.get("frame_size")
    if frame_delta == 0:
        return f"{function}: current and expected frames both reserve {cur_frame} bytes"
    if extra is not None and not extra["current_accesses_in_range"]:
        return (
            f"{function}: expected frame={exp_frame}, current frame={cur_frame}; "
            f"target reserves {extra['size']} extra low-frame bytes "
            f"(0x{extra['start']:x}-0x{extra['end']:x}) before the first "
            "callee/local stack access, with no current pcode stack access "
            "origin in that range"
        )
    if (
        current_low_expansion is not None
        and not current_low_expansion["current_accesses_in_range"]
    ):
        align = current_low_expansion["alignment_growth_bytes"]
        detail = (
            f"current has an implicit unused low local home "
            f"(0x{current_low_expansion['start']:x}-"
            f"0x{current_low_expansion['end']:x}, "
            f"{current_low_expansion['size']} bytes)"
        )
        if align:
            detail += f" plus {align} bytes of alignment growth"
        return (
            f"{function}: expected frame={exp_frame}, current frame={cur_frame}; "
            f"{detail}"
        )
    return (
        f"{function}: expected frame={exp_frame}, current frame={cur_frame}; "
        f"frame delta={frame_delta}"
    )
