"""Tests for checkdiff stack-frame diagnostics."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_checkdiff():
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "tools" / "checkdiff.py"
    spec = importlib.util.spec_from_file_location("checkdiff", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classify_asm_diff_reports_stack_frame_delta() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: stwu r1, -56(r1)",
        "+004: mflr r0",
        "+008: stw r0, 60(r1)",
        "+00c: lwz r3, 36(r1)",
        "+010: addi r1, r1, 56",
    ]
    current = [
        "<fn_80000000>:",
        "+000: stwu r1, -32(r1)",
        "+004: mflr r0",
        "+008: stw r0, 36(r1)",
        "+00c: lwz r3, 12(r1)",
        "+010: addi r1, r1, 32",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] == "stack-layout"
    assert classification["stack_frame_delta"] == {
        "expected_frame_size": 56,
        "current_frame_size": 32,
        "missing_stack_bytes": 24,
        "consistent_stack_slot_delta": 24,
        "stack_slot_delta_count": 3,
    }
    assert any("PAD_STACK(24)" in r for r in classification["reasons"])


def test_format_stack_frame_diagnostic_mentions_forced_schedule_composition() -> None:
    checkdiff = _load_checkdiff()
    message = checkdiff.format_stack_frame_diagnostic({
        "stack_frame_delta": {
            "expected_frame_size": 56,
            "current_frame_size": 32,
            "missing_stack_bytes": 24,
            "consistent_stack_slot_delta": 24,
            "stack_slot_delta_count": 3,
        }
    })

    assert message is not None
    assert "PAD_STACK(24)" in message
    assert "forced scheduler" in message
    assert "frame-reservation + schedule" in message


def test_format_stack_frame_diagnostic_suggests_natural_source_levers() -> None:
    checkdiff = _load_checkdiff()
    message = checkdiff.format_stack_frame_diagnostic({
        "stack_frame_delta": {
            "expected_frame_size": 56,
            "current_frame_size": 32,
            "missing_stack_bytes": 24,
            "consistent_stack_slot_delta": 24,
            "stack_slot_delta_count": 3,
        }
    })

    assert message is not None
    assert "source-level next steps" in message
    assert "address-taken local" in message
    assert "call-argument temporary" in message
    assert "3 paired r1 stack references shift by 24 bytes" in message
    assert "do not commit PAD_STACK" in message


def test_pad_stack_probe_guidance_marks_matched_summary_diagnostic_only() -> None:
    checkdiff = _load_checkdiff()
    classification = {
        "primary": "instruction-identical",
        "reasons": ["normalized disassembly is identical"],
    }
    probe = checkdiff.detect_diagnostic_pad_stack("void f(void) { PAD_STACK(24); }")

    checkdiff.add_pad_stack_probe_guidance(classification, probe)

    assert classification["diagnostic_pad_stack"] == {
        "pad_stack_bytes": [24],
        "total_pad_stack_bytes": 24,
    }
    assert any("diagnostic PAD_STACK(24)" in r for r in classification["reasons"])
    assert any("not shippable source" in r for r in classification["reasons"])
    summary = checkdiff.format_summary(
        "fn_80000000",
        matched=True,
        fuzzy_pct=100.0,
        classification=classification,
    )
    assert "diagnostic_pad_stack=24" in summary
    assert "source_guidance=natural-frame-reservation" in summary


def test_manual_unused_padding_array_guidance_is_diagnostic_only() -> None:
    checkdiff = _load_checkdiff()
    classification = {
        "primary": "instruction-identical",
        "reasons": ["normalized disassembly is identical"],
    }
    probe = checkdiff.detect_diagnostic_pad_stack(
        "void f(void) { UNUSED unsigned char natural_stack_probe[24]; }"
    )

    checkdiff.add_pad_stack_probe_guidance(classification, probe)

    assert classification["diagnostic_pad_stack"]["manual_padding"] == [
        {"name": "natural_stack_probe", "bytes": 24}
    ]
    assert classification["diagnostic_pad_stack"]["total_pad_stack_bytes"] == 24
    assert any("manual stack padding natural_stack_probe[24]" in r for r in classification["reasons"])
    assert any("not shippable source" in r for r in classification["reasons"])
    summary = checkdiff.format_summary(
        "fn_80000000",
        matched=True,
        fuzzy_pct=100.0,
        classification=classification,
    )
    assert "diagnostic_pad_stack=24" in summary
    assert "source_guidance=natural-frame-reservation" in summary
