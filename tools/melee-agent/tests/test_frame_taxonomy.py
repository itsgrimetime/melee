from __future__ import annotations

import pytest

from src.mwcc_debug.frame_taxonomy import classify_frame_taxonomy


def _attributed_frame_report(*, frame_delta: int = -8) -> dict:
    return {
        "function": "demo_fn",
        "current": {"frame_size": 80},
        "expected": {"frame_size": 80 + frame_delta},
        "frame_delta": frame_delta,
        "frame_first_divergence": {
            "status": "diverged",
            "cause_hypothesis": {
                "kind": "extra-frame-reservation-or-alignment",
                "frame_delta": frame_delta,
            },
            "source_attribution": {
                "status": "source-object-attributed",
                "primary_source_object": {"symbol": "local_temp"},
            },
            "verdict": {"status": "source-reachable-candidate"},
            "frame_transform_probe_plan": {
                "status": "ready",
                "suggested_commands": [
                    {
                        "command": (
                            "melee-agent debug mutate frame-transform-search "
                            "-f <function> --compile-probes --json"
                        )
                    }
                ],
            },
        },
    }


def _same_frame_report() -> dict:
    report = _attributed_frame_report(frame_delta=0)
    report["frame_first_divergence"]["cause_hypothesis"]["kind"] = (
        "stack-object-offset-shift"
    )
    return report


def test_checkdiff_frame_size_needs_attribution_and_does_not_claim_match_gate() -> None:
    result = classify_frame_taxonomy(
        "demo_fn",
        classification={
            "primary": "stack-layout",
            "stack_frame_delta": {"missing_stack_bytes": -8},
        },
        source_path="src/melee/demo.c",
    )

    assert result is not None
    assert result["cause"] == "frame-too-large"
    assert result["evidence"] == "checkdiff-only"
    assert result["probe_status"] == "needs-attribution"
    assert result["match_relevance"] == "unknown"
    assert "closability_tier" not in result
    assert result["next_command"] == (
        "melee-agent debug dump local src/melee/demo.c --function demo_fn && "
        "melee-agent debug inspect frame-reservations -f demo_fn --json"
    )


def test_checkdiff_same_frame_is_neutral_but_still_needs_attribution() -> None:
    result = classify_frame_taxonomy(
        "demo_fn",
        classification={
            "primary": "stack-slot-layout",
            "stack_slot_localizer": {"frame_size": 64, "mismatch_count": 1},
        },
    )

    assert result is not None
    assert result["cause"] == "stack-object-offset-shift"
    assert result["evidence"] == "checkdiff-only"
    assert result["probe_status"] == "needs-attribution"
    assert result["match_relevance"] == "match-neutral"


@pytest.mark.parametrize(
    ("validated_status", "expected_probe_status"),
    [
        ("source-reachable-validated", "validated-improving"),
        ("partial-source-reachable-validated", "validated-improving"),
        ("attributed-frame-unchanged", "ceiling"),
        ("internal-tiebreak-ceiling", "ceiling"),
    ],
)
def test_frame_transform_validated_verdict_maps_to_probe_status(
    validated_status: str,
    expected_probe_status: str,
) -> None:
    report = _attributed_frame_report()
    report["frame_first_divergence"]["validated_verdict"] = {
        "status": validated_status,
        "stop_condition": {"status": "satisfied"},
    }

    result = classify_frame_taxonomy("demo_fn", frame_report=report)

    assert result is not None
    assert result["evidence"] == "probe-validated"
    assert result["probe_status"] == expected_probe_status
    assert result["match_relevance"] == "unknown"


def test_stack_home_guidance_validation_is_consumed() -> None:
    report = _same_frame_report()
    report["current"]["stack_home_reorder_guidance"] = {
        "validated_verdict": {"status": "source-reachable-reorder"},
    }

    result = classify_frame_taxonomy("demo_fn", frame_report=report)

    assert result is not None
    assert result["evidence"] == "probe-validated"
    assert result["probe_status"] == "validated-improving"
    assert result["match_relevance"] == "match-neutral"


def test_stack_home_ready_probe_uses_producer_targeted_command() -> None:
    report = _same_frame_report()
    report["frame_first_divergence"].pop("frame_transform_probe_plan")
    report["current"]["stack_home_reorder_guidance"] = {
        "status": "source-reachable-candidate",
        "probe_plan": {
            "status": "ready",
            "suggested_commands": [
                {
                    "kind": "targeted-stack-home-reorder",
                    "command": (
                        "melee-agent debug mutate lifetime-layout -f <function> "
                        "--source-file src/melee/demo.c --declaration-order local_b,local_a "
                        "--compile-probes --json"
                    ),
                }
            ],
        },
    }

    result = classify_frame_taxonomy("demo_fn", frame_report=report)

    assert result is not None
    assert result["probe_status"] == "materializable"
    assert result["next_command"] == (
        "melee-agent debug mutate lifetime-layout -f demo_fn "
        "--source-file src/melee/demo.c --declaration-order local_b,local_a "
        "--compile-probes --json"
    )


@pytest.mark.parametrize(
    "expected_probe_status",
    ["materializable", "validated-improving", "probe-inconclusive"],
)
def test_zero_delta_lifetime_divergence_uses_stack_home_command_family(
    expected_probe_status: str,
) -> None:
    report = {
        "function": "demo_fn",
        "current": {
            "frame_size": 80,
            "stack_home_reorder_guidance": {
                "status": "source-reorder-probe-needed",
                "verdict": "unknown-unvalidated",
                "reason": "stack homes have the same shape in a different order",
                "candidate_levers": ["declaration-use-distance", "block-scope"],
                "probe_plan": {
                    "status": "ready",
                    "objective": "move stack homes into expected target offset order",
                    "target_symbols": ["local_temp"],
                    "current_offset_order": ["local_temp", "other_local"],
                    "expected_offset_order": ["other_local", "local_temp"],
                    "cycles": [["local_temp", "other_local"]],
                    "operator_priority": [
                        "declaration-use-distance",
                        "block-scope",
                        "call-argument-tempization",
                    ],
                    "suggested_commands": [
                        {
                            "kind": "lifetime-layout",
                            "command": (
                                "melee-agent debug mutate lifetime-layout "
                                "-f <function> --operator declaration-use-distance "
                                "--operator block-scope "
                                "--operator call-argument-tempization "
                                "--compile-probes --json"
                            ),
                        }
                    ],
                },
            },
        },
        "expected": {"frame_size": 80},
        "frame_delta": 0,
        "frame_first_divergence": {
            "status": "diverged",
            "cause_hypothesis": {
                "status": "heuristic",
                "kind": "lifetime-or-ordering-shift",
                "confidence": "medium",
                "reason": (
                    "attributed stack object has the same shape but different offsets"
                ),
                "source_object_symbol": "local_temp",
                "current_expected_offset_delta": 4,
                "frame_delta": 0,
            },
            "source_attribution": {
                "status": "source-object-attributed",
                "primary_source_object": {
                    "symbol": "local_temp",
                    "current_offset": 24,
                    "expected_offset": 28,
                    "size": 4,
                    "kind": "local",
                },
            },
            "verdict": {
                "status": "source-reachable-candidate",
                "source_object_symbol": "local_temp",
            },
            "frame_transform_probe_plan": {
                "status": "ready",
                "suggested_commands": [
                    {
                        "command": (
                            "melee-agent debug mutate frame-transform-search "
                            "-f <function> --compile-probes --json"
                        )
                    }
                ],
            },
        },
    }
    if expected_probe_status == "validated-improving":
        report["frame_first_divergence"]["validated_verdict"] = {
            "status": "source-reachable-validated"
        }
    elif expected_probe_status == "probe-inconclusive":
        report["frame_transform_probe_evaluation"] = {
            "status": "no-probes",
            "verdict": "no-probes",
            "variant_count": 0,
        }

    result = classify_frame_taxonomy("demo_fn", frame_report=report)

    assert result is not None
    assert result["raw_cause"] == "lifetime-or-ordering-shift"
    assert result["probe_status"] == expected_probe_status
    assert result["next_command"] == (
        "melee-agent debug mutate lifetime-layout -f demo_fn "
        "--operator declaration-use-distance --operator block-scope "
        "--operator call-argument-tempization --compile-probes --json"
    )
    assert "frame-transform-search" not in result["next_command"]


def test_stack_home_ready_without_a_command_is_not_materializable() -> None:
    report = _same_frame_report()
    report["frame_first_divergence"].pop("frame_transform_probe_plan")
    report["current"]["stack_home_reorder_guidance"] = {
        "status": "source-reachable-candidate",
        "probe_plan": {"status": "ready", "suggested_commands": []},
    }

    result = classify_frame_taxonomy("demo_fn", frame_report=report)

    assert result is not None
    assert result["probe_status"] == "needs-attribution"
    assert result["next_command"].startswith("melee-agent debug dump local")


def test_no_safe_semantic_lever_is_terminal_not_ceiling() -> None:
    report = _attributed_frame_report()
    report["semantic_lever_status"] = {
        "status": "no-safe-semantic-lever",
        "reason": "no guarded one-use local can be dematerialized",
    }
    report["frame_transform_probe_evaluation"] = {
        "status": "no-probes",
        "verdict": "no-safe-semantic-lever",
        "variant_count": 0,
    }

    result = classify_frame_taxonomy("demo_fn", frame_report=report)

    assert result is not None
    assert result["evidence"] == "tool-evaluated"
    assert result["probe_status"] == "terminal-no-safe-lever"


@pytest.mark.parametrize(
    ("location", "expected_evidence"),
    [
        ("semantic-status", "tool-evaluated"),
        ("evaluation-verdict", "tool-evaluated"),
        ("evaluation-stop", "probe-validated"),
        ("validated-stop", "tool-evaluated"),
        ("verdict-stop", "tool-evaluated"),
    ],
)
def test_no_safe_terminal_has_highest_precedence_from_supported_locations(
    location: str,
    expected_evidence: str,
) -> None:
    report = _attributed_frame_report()
    first = report["frame_first_divergence"]
    if location == "semantic-status":
        report["semantic_lever_status"] = {
            "status": "no-safe-semantic-lever",
            "reason": "static source scan found no safe lever",
        }
    elif location == "evaluation-verdict":
        report["frame_transform_probe_evaluation"] = {
            "status": "no-probes",
            "verdict": "no-safe-semantic-lever",
            "variant_count": 0,
            "stop_condition": {
                "status": "not-satisfied",
                "kind": "no-probes",
            },
        }
    elif location == "evaluation-stop":
        report["frame_transform_probe_evaluation"] = {
            "status": "evaluated",
            "verdict": "frame-transform-results-inconclusive",
            "variant_count": 1,
            "best_variant": {"status": "ok", "target_frame_fixed": False},
            "stop_condition": {
                "status": "not-satisfied",
                "kind": "no-safe-semantic-lever",
            },
        }
    elif location == "validated-stop":
        first["validated_verdict"] = {
            "status": "unresolved-source-attribution",
            "stop_condition": {
                "status": "not-satisfied",
                "kind": "no-safe-semantic-lever",
            },
        }
    else:
        first["verdict"] = {
            "status": "source-reachable-candidate",
            "stop_condition": {
                "status": "not-satisfied",
                "kind": "no-safe-semantic-lever",
            },
        }

    result = classify_frame_taxonomy("demo_fn", frame_report=report)

    assert result is not None
    assert result["probe_status"] == "terminal-no-safe-lever"
    assert result["evidence"] == expected_evidence
    assert result["next_command"].startswith(
        "melee-agent debug inspect frame-reservations"
    )


@pytest.mark.parametrize(
    ("score_location", "target_fixed", "expected_relevance"),
    [
        ("evaluation", False, "unknown"),
        ("evaluation", True, "match-gating-candidate"),
        ("match-score-evidence", False, "unknown"),
        ("match-score-evidence", True, "match-gating-candidate"),
    ],
)
def test_match_improvement_requires_frame_target_attainment(
    score_location: str,
    target_fixed: bool,
    expected_relevance: str,
) -> None:
    report = _attributed_frame_report()
    if score_location == "evaluation":
        report["frame_transform_probe_evaluation"] = {
            "status": "evaluated",
            "verdict": "source-reachable-frame-transform",
            "variant_count": 1,
            "baseline_match_percent": 99.0,
            "best_variant": {
                "status": "ok",
                "match_percent": 99.5,
                "target_frame_fixed": target_fixed,
            },
        }
    else:
        report["match_score_evidence"] = {
            "before": 99.0,
            "after": 99.5,
            "target_frame_fixed": target_fixed,
        }

    result = classify_frame_taxonomy("demo_fn", frame_report=report)

    assert result is not None
    assert result["match_relevance"] == expected_relevance


@pytest.mark.parametrize(
    ("cause", "probe_status", "expected_command"),
    [
        ("same-frame", "materializable", "debug mutate lifetime-layout"),
        ("same-frame", "validated-improving", "debug mutate lifetime-layout"),
        ("same-frame", "probe-inconclusive", "debug mutate lifetime-layout"),
        ("same-frame", "terminal-no-safe-lever", "debug inspect frame-reservations"),
        ("same-frame", "ceiling", "debug inspect frame-reservations"),
        ("frame-size", "materializable", "debug mutate frame-transform-search"),
        ("frame-size", "validated-improving", "debug mutate frame-transform-search"),
        ("frame-size", "probe-inconclusive", "debug mutate frame-transform-search"),
        ("frame-size", "terminal-no-safe-lever", "debug inspect frame-reservations"),
        ("frame-size", "ceiling", "debug inspect frame-reservations"),
    ],
)
def test_frame_command_matrix_uses_cause_and_probe_status(
    cause: str,
    probe_status: str,
    expected_command: str,
) -> None:
    report = (
        _same_frame_report()
        if cause == "same-frame"
        else _attributed_frame_report()
    )
    first = report["frame_first_divergence"]
    if probe_status == "validated-improving":
        first["validated_verdict"] = {"status": "source-reachable-validated"}
    elif probe_status == "probe-inconclusive":
        report["frame_transform_probe_evaluation"] = {
            "status": "no-probes",
            "verdict": "no-probes",
            "variant_count": 0,
        }
    elif probe_status == "terminal-no-safe-lever":
        report["semantic_lever_status"] = {"status": "no-safe-semantic-lever"}
    elif probe_status == "ceiling":
        first["validated_verdict"] = {"status": "attributed-frame-unchanged"}

    result = classify_frame_taxonomy(
        "demo_fn",
        source_path="src/melee/demo.c",
        frame_report=report,
    )

    assert result is not None
    assert result["probe_status"] == probe_status
    assert expected_command in result["next_command"]
    if probe_status not in {"terminal-no-safe-lever", "ceiling"}:
        assert "debug inspect frame-reservations" not in result["next_command"]


def test_pcdump_candidate_is_materializable_only_with_probe_plan() -> None:
    result = classify_frame_taxonomy("demo_fn", frame_report=_attributed_frame_report())

    assert result is not None
    assert result["evidence"] == "pcdump-attributed"
    assert result["probe_status"] == "materializable"
    assert result["next_command"].startswith(
        "melee-agent debug mutate frame-transform-search"
    )


def test_unattributed_pcdump_still_needs_attribution() -> None:
    report = _attributed_frame_report()
    first = report["frame_first_divergence"]
    first["source_attribution"] = {"status": "unattributed"}
    first["verdict"] = {"status": "unresolved-source-attribution"}

    result = classify_frame_taxonomy("demo_fn", frame_report=report)

    assert result is not None
    assert result["evidence"] == "pcdump-attributed"
    assert result["probe_status"] == "needs-attribution"


@pytest.mark.parametrize(
    ("evaluation", "evidence"),
    [
        (
            {
                "status": "evaluated",
                "verdict": "frame-transform-results-inconclusive",
                "variant_count": 1,
                "variants": [{"status": "ok"}],
            },
            "probe-validated",
        ),
        (
            {"status": "no-probes", "verdict": "no-probes", "variant_count": 0},
            "tool-evaluated",
        ),
    ],
)
def test_inconclusive_probe_results_preserve_evidence_strength(
    evaluation: dict,
    evidence: str,
) -> None:
    report = _attributed_frame_report()
    report["frame_transform_probe_evaluation"] = evaluation

    result = classify_frame_taxonomy("demo_fn", frame_report=report)

    assert result is not None
    assert result["evidence"] == evidence
    assert result["probe_status"] == "probe-inconclusive"


def test_local_area_outgoing_floor_cause_is_preserved() -> None:
    report = _attributed_frame_report()
    report["frame_first_divergence"]["cause_hypothesis"]["kind"] = (
        "local-area-vs-outgoing-floor-divergence"
    )

    result = classify_frame_taxonomy("demo_fn", frame_report=report)

    assert result is not None
    assert result["cause"] == "local-area-vs-outgoing-floor-divergence"


def test_checkdiff_pure_reservation_requires_attribution() -> None:
    classification = {
        "primary": "stack-layout",
        "stack_frame_delta": {"missing_stack_bytes": 16},
    }

    result = classify_frame_taxonomy(
        "demo_fn",
        classification=classification,
        source_path="src/melee/demo.c",
    )

    assert result is not None
    assert result["cause"] == "pure-reservation"
    assert result["evidence"] == "checkdiff-only"
    assert result["probe_status"] == "needs-attribution"
    assert result["match_relevance"] == "unknown"
    assert result["verdict"] == "source-reachable-candidate"
    assert result["attribution_status"] == "checkdiff-only"
    assert result["next_command"].startswith(
        "melee-agent debug dump local src/melee/demo.c --function demo_fn"
    )
    assert "PAD_STACK(" not in result["next_command"]
    assert "commit" not in result["next_command"].lower()


def test_checkdiff_current_frame_too_large_requires_attribution() -> None:
    classification = {
        "primary": "stack-layout",
        "stack_frame_delta": {"missing_stack_bytes": -8},
    }

    result = classify_frame_taxonomy("demo_fn", classification=classification)

    assert result is not None
    assert result["cause"] == "frame-too-large"
    assert result["raw_cause"] == "checkdiff.stack_frame_delta"
    assert result["evidence"] == "checkdiff-only"
    assert result["probe_status"] == "needs-attribution"
    assert result["attribution_status"] == "checkdiff-only"


def test_checkdiff_equal_frame_stack_layout_is_neutral() -> None:
    classification = {
        "primary": "stack-layout",
        "stack_frame_delta": {
            "expected_frame_size": 64,
            "current_frame_size": 64,
            "missing_stack_bytes": 0,
        },
        "reasons": [
            "frame reservation gap is too large; stale checkdiff-only reason",
        ],
    }

    result = classify_frame_taxonomy("demo_fn", classification=classification)

    assert result is not None
    assert result["cause"] == "stack-object-offset-shift"
    assert result["raw_cause"] == "checkdiff.same_frame_stack_layout"
    assert result["evidence"] == "checkdiff-only"
    assert result["probe_status"] == "needs-attribution"
    assert result["match_relevance"] == "match-neutral"
    assert "same-frame stack-slot" in result["match_relevance_reason"]
    assert result["verdict"] == "source-reachable-candidate"
    assert result["next_command"].startswith("melee-agent debug dump local")


def test_checkdiff_stack_slot_layout_is_neutral() -> None:
    classification = {
        "primary": "stack-slot-layout",
        "stack_slot_localizer": {
            "frame_size": 64,
            "mismatch_count": 1,
            "mismatches": [
                {
                    "expected_offset": 52,
                    "current_offset": 48,
                    "delta": 4,
                    "opcode": "stfs",
                }
            ],
        },
    }

    result = classify_frame_taxonomy("demo_fn", classification=classification)

    assert result is not None
    assert result["cause"] == "stack-object-offset-shift"
    assert result["evidence"] == "checkdiff-only"
    assert result["probe_status"] == "needs-attribution"
    assert result["match_relevance"] == "match-neutral"
    assert "same-frame stack-slot" in result["match_relevance_reason"]
    assert result["next_command"].startswith("melee-agent debug dump local")


def test_checkdiff_reserved_low_spill_marker_needs_attribution() -> None:
    classification = {
        "primary": "stack-slot-layout",
        "stack_slot_localizer": {
            "frame_size": 64,
            "mismatch_count": 2,
            "reserved_low_spill_region": {
                "kind": "reserved-unused-low-spill-region",
                "closability_tier": "ceiling",
                "deltas": [12],
            },
        },
    }

    result = classify_frame_taxonomy("demo_fn", classification=classification)

    assert result is not None
    assert result["cause"] == "reserved-unused-low-spill-region"
    assert result["raw_cause"] == "reserved-unused-low-spill-region"
    assert result["verdict"] == "unresolved-source-attribution"
    assert result["evidence"] == "checkdiff-only"
    assert result["probe_status"] == "needs-attribution"
    assert result["attribution_status"] == "checkdiff-only"


def test_non_stack_classification_returns_none() -> None:
    assert classify_frame_taxonomy(
        "demo_fn",
        classification={"primary": "register-allocation"},
    ) is None


def test_frame_report_source_attributed_divergence_preserves_raw_fields() -> None:
    source_object = {
        "symbol": "local_temp",
        "identity_kind": "symbolic-stack-home",
        "current_offset": 28,
        "expected_offset": 24,
    }
    frame_report = {
        "function": "demo_fn",
        "frame_first_divergence": {
            "status": "diverged",
            "cause_hypothesis": {
                "kind": "lifetime-or-ordering-shift",
                "confidence": "medium",
                "source_object_symbol": "local_temp",
            },
            "source_attribution": {
                "status": "source-object-attributed",
                "primary_source_object": source_object,
            },
            "verdict": {
                "status": "source-reachable-candidate",
                "confidence": "medium",
                "source_object_symbol": "local_temp",
            },
        },
    }

    result = classify_frame_taxonomy("demo_fn", frame_report=frame_report)

    assert result is not None
    assert result["cause"] == "lifetime-or-ordering-shift"
    assert result["raw_cause"] == "lifetime-or-ordering-shift"
    assert result["verdict"] == "source-reachable-candidate"
    assert result["raw_verdict"] == "source-reachable-candidate"
    assert result["evidence"] == "pcdump-attributed"
    assert result["probe_status"] == "needs-attribution"
    assert result["attribution_status"] == "source-object-attributed"
    assert result["source_object"] == source_object
    assert result["source_object_symbol"] == "local_temp"


@pytest.mark.parametrize(
    "raw_cause",
    ["stack-object-size-or-alignment", "type-size-or-alignment"],
)
def test_frame_report_size_alignment_cause_is_not_lifetime_layout(
    raw_cause: str,
) -> None:
    frame_report = {
        "function": "demo_fn",
        "current": {"frame_size": 1216},
        "expected": {"frame_size": 1272},
        "frame_delta": 56,
        "frame_first_divergence": {
            "status": "diverged",
            "reason": "size-differs",
            "current": {
                "start": 0x60,
                "end": 0x84,
                "size": 36,
                "kind": "local-or-temporary",
            },
            "expected": {
                "start": 0x5C,
                "end": 0x84,
                "size": 40,
                "kind": "local-or-temporary",
            },
            "cause_hypothesis": {
                "kind": raw_cause,
                "confidence": "medium",
                "current_size": 36,
                "expected_size": 40,
                "frame_delta": 56,
                "reason": (
                    "corresponding stack objects differ in size; inspect type "
                    "size, array extent, struct layout, or alignment"
                ),
            },
            "source_attribution": {
                "status": "unattributed",
                "primary_source_object": None,
            },
            "verdict": {
                "status": "unresolved-source-attribution",
                "confidence": "medium",
            },
        },
    }

    result = classify_frame_taxonomy("demo_fn", frame_report=frame_report)

    assert result is not None
    assert result["cause"] == raw_cause
    assert result["raw_cause"] == raw_cause
    assert result["evidence"] == "pcdump-attributed"
    assert result["probe_status"] == "needs-attribution"
    assert result["match_relevance"] == "unknown"
    assert "lifetime-layout" not in result["next_command"]
    assert "differ in size" in result["reason"]


def test_frame_report_size_alignment_validated_frame_move_stays_relevance_unknown() -> None:
    frame_report = {
        "function": "demo_fn",
        "current": {"frame_size": 1216},
        "expected": {"frame_size": 1272},
        "frame_delta": 56,
        "frame_first_divergence": {
            "status": "diverged",
            "cause_hypothesis": {
                "kind": "stack-object-size-or-alignment",
                "confidence": "medium",
                "current_size": 36,
                "expected_size": 40,
                "frame_delta": 56,
            },
            "source_attribution": {
                "status": "unattributed",
                "primary_source_object": None,
            },
            "verdict": {
                "status": "unresolved-source-attribution",
            },
            "validated_verdict": {
                "status": "source-reachable-validated",
                "reason": "frame transform probe moved the frame size",
            },
        },
    }

    result = classify_frame_taxonomy("demo_fn", frame_report=frame_report)

    assert result is not None
    assert result["cause"] == "stack-object-size-or-alignment"
    assert result["verdict"] == "source-reachable-validated"
    assert result["match_relevance"] == "unknown"


def test_frame_report_frame_size_only_unattributed_divergence() -> None:
    frame_report = {
        "function": "demo_fn",
        "current": {"frame_size": 48},
        "expected": {"frame_size": 64},
        "frame_delta": 16,
        "frame_first_divergence": {
            "status": "frame-size-only",
            "frame_delta": 16,
            "cause_hypothesis": {
                "kind": "extra-frame-reservation-or-alignment",
                "confidence": "medium",
                "frame_delta": 16,
            },
            "source_attribution": {
                "status": "unattributed",
                "primary_source_object": None,
            },
            "verdict": {
                "status": "unresolved-source-attribution",
                "confidence": "medium",
            },
        },
    }

    result = classify_frame_taxonomy("demo_fn", frame_report=frame_report)

    assert result is not None
    assert result["cause"] == "pure-reservation"
    assert result["raw_cause"] == "extra-frame-reservation-or-alignment"
    assert result["verdict"] == "unresolved-source-attribution"
    assert result["raw_verdict"] == "unresolved-source-attribution"
    assert result["evidence"] == "pcdump-attributed"
    assert result["probe_status"] == "needs-attribution"
    assert result["attribution_status"] == "unattributed"


def test_frame_report_negative_reservation_delta_maps_to_frame_too_large() -> None:
    frame_report = {
        "function": "demo_fn",
        "current": {"frame_size": 80},
        "expected": {"frame_size": 72},
        "frame_delta": -8,
        "frame_first_divergence": {
            "status": "frame-size-only",
            "cause_hypothesis": {
                "kind": "extra-frame-reservation-or-alignment",
                "confidence": "medium",
                "frame_delta": -8,
            },
            "source_attribution": {
                "status": "unattributed",
                "primary_source_object": None,
            },
            "verdict": {
                "status": "unresolved-source-attribution",
                "confidence": "medium",
            },
        },
    }

    result = classify_frame_taxonomy("demo_fn", frame_report=frame_report)

    assert result is not None
    assert result["cause"] == "frame-too-large"
    assert result["raw_cause"] == "extra-frame-reservation-or-alignment"
    assert result["evidence"] == "pcdump-attributed"
    assert result["probe_status"] == "needs-attribution"


@pytest.mark.parametrize(
    ("validated_status", "expected_verdict", "expected_probe_status"),
    [
        ("source-reachable-validated", "source-reachable-validated", "validated-improving"),
        (
            "partial-source-reachable-validated",
            "partial-source-reachable-validated",
            "validated-improving",
        ),
        ("attributed-frame-unchanged", "attributed-frame-unchanged", "ceiling"),
        ("internal-tiebreak-ceiling", "internal-tiebreak-ceiling", "ceiling"),
    ],
)
def test_frame_report_validated_verdict_overrides_base_verdict(
    validated_status: str,
    expected_verdict: str,
    expected_probe_status: str,
) -> None:
    frame_report = {
        "function": "demo_fn",
        "frame_first_divergence": {
            "status": "diverged",
            "cause_hypothesis": {
                "kind": "lifetime-or-ordering-shift",
                "confidence": "medium",
                "source_object_symbol": "local_temp",
            },
            "source_attribution": {
                "status": "source-object-attributed",
                "primary_source_object": {"symbol": "local_temp"},
            },
            "verdict": {
                "status": "source-reachable-candidate",
                "confidence": "medium",
            },
            "validated_verdict": {
                "status": validated_status,
                "probe_verdict": "frame-transform-ceiling-candidate",
            },
        },
    }

    result = classify_frame_taxonomy("demo_fn", frame_report=frame_report)

    assert result is not None
    assert result["raw_cause"] == "lifetime-or-ordering-shift"
    assert result["raw_verdict"] == validated_status
    assert result["verdict"] == expected_verdict
    assert result["evidence"] == "probe-validated"
    assert result["probe_status"] == expected_probe_status
