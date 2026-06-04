from __future__ import annotations

import pytest

from src.mwcc_debug.frame_taxonomy import classify_frame_taxonomy


def test_checkdiff_pure_reservation_maps_to_current_tools_padstack() -> None:
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
    assert result["closability_tier"] == "current-tools-padstack"
    assert result["verdict"] == "source-reachable-candidate"
    assert result["attribution_status"] == "checkdiff-only"
    assert result["next_command"].startswith(
        "melee-agent debug mutate frame-transform-search -f demo_fn "
    )
    assert "--source-file src/melee/demo.c" in result["next_command"]
    assert "--operator frame-reservation-pad-stack" in result["next_command"]
    assert "--frame-reservation-bytes 16" in result["next_command"]
    assert "--compile-probes --json" in result["next_command"]
    assert "PAD_STACK(" not in result["next_command"]
    assert "commit" not in result["next_command"].lower()


def test_checkdiff_current_frame_too_large_maps_to_generator_gated() -> None:
    classification = {
        "primary": "stack-layout",
        "stack_frame_delta": {"missing_stack_bytes": -8},
    }

    result = classify_frame_taxonomy("demo_fn", classification=classification)

    assert result is not None
    assert result["cause"] == "frame-too-large"
    assert result["raw_cause"] == "checkdiff.stack_frame_delta"
    assert result["closability_tier"] == "gen-gated-366"
    assert result["attribution_status"] == "checkdiff-only"


def test_checkdiff_equal_frame_stack_layout_maps_to_lifetime_layout() -> None:
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
    assert result["closability_tier"] == "reorder-gated-362"
    assert result["verdict"] == "source-reachable-candidate"
    assert result["next_command"] == (
        "melee-agent debug mutate lifetime-layout -f demo_fn "
        "--compile-probes --json"
    )


def test_checkdiff_stack_slot_layout_maps_to_reorder_gated() -> None:
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
    assert result["closability_tier"] == "reorder-gated-362"
    assert result["next_command"] == (
        "melee-agent debug mutate lifetime-layout -f demo_fn "
        "--compile-probes --json"
    )


def test_checkdiff_reserved_low_spill_marker_maps_to_ceiling() -> None:
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
    assert result["verdict"] == "ceiling"
    assert result["closability_tier"] == "ceiling"
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
    assert result["closability_tier"] == "gen-gated-366"
    assert result["attribution_status"] == "source-object-attributed"
    assert result["source_object"] == source_object
    assert result["source_object_symbol"] == "local_temp"


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
    assert result["closability_tier"] == "current-tools-padstack"
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
    assert result["closability_tier"] == "gen-gated-366"


@pytest.mark.parametrize(
    ("validated_status", "expected_verdict", "expected_tier"),
    [
        ("source-reachable-validated", "source-reachable-validated", "gen-gated-366"),
        (
            "partial-source-reachable-validated",
            "partial-source-reachable-validated",
            "gen-gated-366",
        ),
        ("attributed-frame-unchanged", "attributed-frame-unchanged", "gen-gated-366"),
        ("internal-tiebreak-ceiling", "internal-tiebreak-ceiling", "ceiling"),
    ],
)
def test_frame_report_validated_verdict_overrides_base_verdict(
    validated_status: str,
    expected_verdict: str,
    expected_tier: str,
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
    assert result["closability_tier"] == expected_tier
