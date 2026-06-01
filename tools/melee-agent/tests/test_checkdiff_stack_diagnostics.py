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
    assert any(
        "manual stack padding natural_stack_probe[24]" in r
        for r in classification["reasons"]
    )
    assert any("not shippable source" in r for r in classification["reasons"])
    summary = checkdiff.format_summary(
        "fn_80000000",
        matched=True,
        fuzzy_pct=100.0,
        classification=classification,
    )
    assert "diagnostic_pad_stack=24" in summary
    assert "source_guidance=natural-frame-reservation" in summary


def test_classify_asm_diff_localizes_same_frame_compiler_temp_stack_slot() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: stwu r1, -64(r1)",
        "+004: stfs f1, 0x34(r1)",
        "+008: lfs f2, 0x38(r1)",
        "+00c: bl sqrtf",
        "+010: addi r1, r1, 64",
    ]
    current = [
        "<fn_80000000>:",
        "+000: stwu r1, -64(r1)",
        "+004: stfs f1, 0x30(r1)",
        "+008: lfs f2, 0x38(r1)",
        "+00c: bl sqrtf",
        "+010: addi r1, r1, 64",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] == "stack-slot-layout"
    assert classification["stack_slot_localizer"] == {
        "frame_size": 64,
        "mismatch_count": 1,
        "deltas": [4],
        "mismatches": [
            {
                "line_index": 2,
                "expected_offset": 52,
                "current_offset": 48,
                "delta": 4,
                "opcode": "stfs",
                "expected": "stfs f1, 0x34(r1)",
                "current": "stfs f1, 0x30(r1)",
            }
        ],
    }
    assert any("compiler-temp spill slot" in r for r in classification["reasons"])
    assert any(
        "PAD_STACK" not in r and "frame reservation" not in r
        for r in classification["reasons"]
    )


def test_classify_asm_diff_detects_indexed_struct_pointer_materialization() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: lwz r5, 4(r4)",
        "+004: lwzx r0, r5, r29",
        "+008: lwz r6, 8(r4)",
        "+00c: lwzx r3, r6, r29",
    ]
    current = [
        "<fn_80000000>:",
        "+000: lwz r5, 4(r4)",
        "+004: add r4, r5, r29",
        "+008: lwz r0, 0(r4)",
        "+00c: lwz r3, 8(r4)",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] == "indexed-struct-pointer-materialization"
    hint = "\n".join(classification["reasons"])
    assert "indexed struct array" in hint
    assert "materializes an element pointer" in hint
    assert "split the first field into a scalar local" in hint
    assert "avoid a live per-element pointer" in hint
    assert classification["indexed_struct_pointer_materialization"] == {
        "expected_indexed_ops": [
            {"line_index": 2, "opcode": "lwzx", "body": "lwzx r0, r5, r29"},
            {"line_index": 4, "opcode": "lwzx", "body": "lwzx r3, r6, r29"},
        ],
        "current_materialized_pointers": [
            {
                "line_index": 2,
                "add": "add r4, r5, r29",
                "pointer_register": "r4",
                "field_accesses": [
                    {"line_index": 3, "body": "lwz r0, 0(r4)"},
                    {"line_index": 4, "body": "lwz r3, 8(r4)"},
                ],
            }
        ],
    }


def test_classify_asm_diff_guides_volatile_and_loop_counter_reg_swaps() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: lbz r4, 0x2227(r31)",
        "+004: cmpwi r3, 0",
        "+008: lwz r30, 0x594(r31)",
        "+00c: addi r29, r29, 1",
        "+010: cmpw r29, r30",
    ]
    current = [
        "<fn_80000000>:",
        "+000: lbz r0, 0x2227(r31)",
        "+004: cmpwi r0, 0",
        "+008: lwz r29, 0x594(r31)",
        "+00c: addi r30, r30, 1",
        "+010: cmpw r30, r29",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] == "register-allocation"
    guidance = classification["register_allocation_guidance"]
    assert guidance["volatile_target_registers"] == ["r3", "r4"]
    assert guidance["callee_swap_pairs"] == [["r29", "r30"]]
    reason_text = "\n".join(classification["reasons"])
    assert "--regs gpr-volatile,r0" in reason_text
    assert "flag/reload predicate" in reason_text
    assert "loop-counter reuse" in reason_text


def test_register_only_diff_demotes_indexed_pointer_shape_hint() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: lwz r30, 0x594(r31)",
        "+004: lwzx r0, r5, r30",
        "+008: add r29, r6, r30",
        "+00c: lwz r4, 0(r29)",
        "+010: addi r30, r30, 1",
        "+014: cmpw r30, r29",
    ]
    current = [
        "<fn_80000000>:",
        "+000: lwz r29, 0x594(r31)",
        "+004: lwzx r0, r5, r29",
        "+008: add r30, r6, r29",
        "+00c: lwz r4, 0(r30)",
        "+010: addi r29, r29, 1",
        "+014: cmpw r29, r30",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] == "register-allocation"
    assert classification["indexed_struct_pointer_materialization"]
    guidance = classification["register_allocation_guidance"]
    assert guidance["callee_swap_pairs"] == [["r29", "r30"]]
    reason_text = "\n".join(classification["reasons"])
    assert "indexed pointer-shape hint demoted" in reason_text
    assert "register-allocation guidance" in reason_text


def test_stack_slot_localizer_accepts_pcdump_bridge() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: stwu r1, -168(r1)",
        "+004: stfs f1, 0x34(r1)",
    ]
    current = [
        "<fn_80000000>:",
        "+000: stwu r1, -168(r1)",
        "+004: stfs f1, 0x30(r1)",
    ]
    pcdump_text = """
Starting function fn_80000000
BEFORE REGISTER COLORING
fn_80000000
B0: Succ={} Pred={} Labels={}
    frsp    f50,f1
    stfs    f50,0x30(r1)
SIMPLIFY GRAPH (class=1, n_colors=32, n_class_regs=61)
  iter ig_idx degree arraySize flags notes
    0 50 1 1 0x08 SPILLED
COLORGRAPH DECISIONS (class=1, result=1, n_nodes=61)
  iter ig_idx phys degree nIntfr flags
    0 50 r1 1 1 0x08
      interferers:
FINAL CODE AFTER INSTRUCTION SCHEDULING
fn_80000000
B0: Succ={} Pred={} Labels={}
    stwu    r1,-168(r1)
    stfs    f1,0x30(r1)
"""

    classification = checkdiff.classify_asm_diff(expected, current)
    checkdiff.add_stack_slot_pcdump_bridge(
        classification,
        function="fn_80000000",
        pcdump_text=pcdump_text,
        source_text="void fn_80000000(void) { dist = sqrtf(dx * dx); }\n",
        source_file="src/melee/pl/plbonuslib.c",
    )

    bridge = classification["stack_slot_localizer"]["pcdump_bridge"]
    assert bridge["status"] == "ok"
    assert bridge["candidates"][0]["spill_root"] == "r50"
    assert any(
        "pcdump bridge: likely class 1 spill root r50" in reason
        for reason in classification["reasons"]
    )
