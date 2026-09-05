"""Tests for checkdiff stack-frame diagnostics."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


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


def test_read_pcdump_text_accepts_text_dump(tmp_path: Path) -> None:
    checkdiff = _load_checkdiff()
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text("Starting function fn_80000000\n", encoding="utf-8")

    assert checkdiff.read_pcdump_text_arg(pcdump) == "Starting function fn_80000000\n"


def test_read_pcdump_text_rejects_elf_object(tmp_path: Path) -> None:
    checkdiff = _load_checkdiff()
    obj = tmp_path / "kept.o"
    obj.write_bytes(b"\x7fELF\x01\x02\x01\x00\x00\x00\x00\x00")

    with pytest.raises(checkdiff.PcdumpInputError) as exc_info:
        checkdiff.read_pcdump_text_arg(obj)

    message = str(exc_info.value)
    assert "--pcdump expects mwcc_debug pcdump text" in message
    assert "not a compiled object" in message
    assert "melee-agent debug dump local" in message


@pytest.mark.parametrize(
    "payload",
    [
        b"\x7fELF\x01\x02\x01\x00\x00\x00\x00\x00",
        b"not text\x00still binary",
    ],
)
def test_checkdiff_cli_rejects_binary_pcdump(payload: bytes, tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    pcdump = tmp_path / "kept.o"
    pcdump.write_bytes(payload)

    result = subprocess.run(
        [
            "python",
            "tools/checkdiff.py",
            "fn_80000000",
            "--no-build",
            "--pcdump",
            str(pcdump),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--pcdump:" in result.stderr
    assert "--pcdump expects mwcc_debug pcdump text" in result.stderr


def test_summary_reports_expected_and_current_frame_sizes() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: stwu r1, -240(r1)",
        "+004: bl helper",
        "+008: addi r1, r1, 240",
    ]
    current = [
        "<fn_80000000>:",
        "+000: stwu r1, -248(r1)",
        "+004: bl helper",
        "+008: addi r1, r1, 248",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    summary = checkdiff.format_summary(
        "fn_80000000",
        matched=False,
        fuzzy_pct=99.5,
        classification=classification,
    )

    assert "expected_frame=240" in summary
    assert "current_frame=248" in summary
    assert "frame_delta=8" in summary


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


def test_make_progress_note_warns_when_match_rises_but_structure_crashes() -> None:
    checkdiff = _load_checkdiff()

    note = checkdiff.make_progress_note(
        52.9,
        {
            "opcode_similarity": 0.028,
            "line_delta": 115,
            "hunk_count": 18,
        },
        {
            "fuzzy_match_percent": 48.2,
            "opcode_similarity": 0.348,
            "line_delta": 23,
            "hunk_count": 6,
        },
    )

    assert note is not None
    assert "false progress" in note
    assert "opcode similarity" in note
    assert "authoritative structural signal" in note


def test_inline_boundary_artifact_exposes_current_larger_verdict() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: bl fn_80001234",
        "+004: bl fn_80005678",
        "+008: bl fn_80009ABC",
    ]
    current = [
        "<fn_80000000>:",
        "+000: lwz r3, 0(r31)",
        "+004: addi r4, r3, 1",
        "+008: stw r4, 0(r31)",
        "+00c: lwz r5, 4(r31)",
        "+010: addi r6, r5, 1",
        "+014: stw r6, 4(r31)",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] == "inline-boundary-toolchain-artifact"
    assert classification["inline_boundary_artifact"]["size_verdict"] == (
        "current-larger"
    )


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


def test_pad_stack_stack_slot_localizer_marks_reserved_low_spill_ceiling() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: stwu r1, -64(r1)",
        "+004: stw r0, 0x24(r1)",
        "+008: lwz r3, 0x24(r1)",
        "+00c: addi r1, r1, 64",
    ]
    current = [
        "<fn_80000000>:",
        "+000: stwu r1, -64(r1)",
        "+004: stw r0, 0x18(r1)",
        "+008: lwz r3, 0x18(r1)",
        "+00c: addi r1, r1, 64",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)
    checkdiff.add_pad_stack_probe_guidance(
        classification,
        {"pad_stack_bytes": [8], "total_pad_stack_bytes": 8},
    )

    candidate = classification["stack_slot_localizer"][
        "reserved_low_spill_region"
    ]
    assert candidate["kind"] == "reserved-unused-low-spill-region"
    assert candidate["closability_tier"] == "ceiling"
    assert candidate["deltas"] == [12]
    assert any(
        "reserved-but-unused low spill region" in reason
        for reason in classification["reasons"]
    )
    assert not any(
        "source-level stack reservation guidance" in reason
        for reason in classification["reasons"]
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
    assert "target vector already satisfied" in reason_text
    assert "source lifetime" in reason_text
    assert "loop-counter reuse" in reason_text


def test_register_only_diff_suppresses_indexed_pointer_shape_hint() -> None:
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
    assert "indexed_struct_pointer_materialization" not in classification
    guidance = classification["register_allocation_guidance"]
    assert guidance["callee_swap_pairs"] == [["r29", "r30"]]
    reason_text = "\n".join(classification["reasons"])
    assert "indexed pointer-shape hint" not in reason_text
    assert "register-allocation guidance" in reason_text


def test_unrelated_materialized_pointers_do_not_trigger_indexed_struct_hint() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: add r12, r12, r0",
        "+004: nop",
        "+008: lwz r7, 8(r12)",
        "+00c: lwz r8, 12(r12)",
        "+010: mr r9, r9",
        "+014: mr r10, r10",
        "+018: mr r11, r11",
        "+01c: mr r12, r12",
        "+020: lbzx r3, r3, r5",
    ]
    current = [
        "<fn_80000000>:",
        "+000: add r12, r12, r0",
        "+004: nop",
        "+008: lwz r7, 8(r12)",
        "+00c: lwz r8, 12(r12)",
        "+010: mr r9, r9",
        "+014: mr r10, r10",
        "+018: mr r11, r11",
        "+01c: mr r12, r12",
        "+020: lbz r3, 0(r3)",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] != "indexed-struct-pointer-materialization"
    assert "indexed_struct_pointer_materialization" not in classification
    reason_text = "\n".join(classification["reasons"])
    assert "indexed struct array pointer-shape hint" not in reason_text


def test_inline_boundary_requires_actual_call_multiplicity_delta() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: stmw r21, -0x2c(r1)",
        "+004: bl fn_A",
        "+008: bl fn_B",
        "+00c: bl fn_A",
        "+010: addi r21, r21, 1",
    ]
    current = [
        "<fn_80000000>:",
        "+000: stmw r22, -0x28(r1)",
        "+004: addi r22, r22, 1",
        "+008: bl fn_A",
        "+00c: bl fn_B",
        "+010: bl fn_A",
        "+014: addi r22, r22, 2",
        "+018: addi r22, r22, 3",
        "+01c: addi r22, r22, 4",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] != "inline-boundary-toolchain-artifact"
    assert "inline_boundary_artifact" not in classification
    assert not any("current omits that call" in r for r in classification["reasons"])


def test_inline_boundary_ignores_shifted_self_relative_call_labels() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: stmw r21, -0x2c(r1)",
        "+004: bl helper_fn",
        "+008: bl other_fn",
        "+00c: bl helper_fn",
        "+010: addi r21, r21, 1",
    ]
    current = [
        "<fn_80000000>:",
        "+000: stmw r22, -0x28(r1)",
        "+004: bl helper_fn+0x4",
        "+008: addi r22, r22, 1",
        "+00c: bl other_fn",
        "+010: bl helper_fn+0x8",
        "+014: addi r22, r22, 2",
        "+018: addi r22, r22, 3",
        "+01c: addi r22, r22, 4",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] != "inline-boundary-toolchain-artifact"
    assert "inline_boundary_artifact" not in classification
    assert not any("current omits that call" in r for r in classification["reasons"])


def test_inline_boundary_ignores_shifted_angle_self_relative_call_labels() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: stwu r1, -0x88(r1)",
        "+004: cmpwi r23, 18",
        "+008: bge <fn_80000000+0x18>",
        "+00c: cmpwi r23, 14",
        "+010: bge <fn_80000000+0x20>",
        "+014: b <fn_80000000+0x18>",
        "+018: li r3, 0",
        "+01c: bl <fn_80000000+0x1f4>",
        "+020: bl <fn_80000000+0x20c>",
        "+024: addi r1, r1, 0x88",
    ]
    current = [
        "<fn_80000000>:",
        "+000: stwu r1, -0x88(r1)",
        "+004: cmpwi r23, 18",
        "+008: blt <fn_80000000+0x1c>",
        "+00c: li r0, 0",
        "+010: b <fn_80000000+0x28>",
        "+014: cmpwi r23, 14",
        "+018: blt <fn_80000000+0x24>",
        "+01c: li r0, 1",
        "+020: b <fn_80000000+0x28>",
        "+024: li r0, 0",
        "+028: cmpwi r0, 0",
        "+02c: beq <fn_80000000+0x38>",
        "+030: bl <fn_80000000+0x200>",
        "+034: bl <fn_80000000+0x218>",
        "+038: addi r1, r1, 0x88",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] == "control-flow-source-shape"
    assert "inline_boundary_artifact" not in classification
    reason_text = "\n".join(classification["reasons"])
    assert "current omits that call" not in reason_text
    assert "inlined locally across an inline boundary" not in reason_text


def test_inline_boundary_prefers_rel24_multiset_over_rendered_call_labels() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: stmw r21, -0x2c(r1)",
        "+004: bl fn_A",
        "+008: R_PPC_REL24\tfn_A",
        "+00c: bl fn_B",
        "+010: R_PPC_REL24\tfn_B",
        "+014: addi r21, r21, 1",
    ]
    current = [
        "<fn_80000000>:",
        "+000: stmw r22, -0x28(r1)",
        "+004: li r28, 0",
        "+008: li r0, 0",
        "+00c: stb r0, 0(r31)",
        "+010: addi r22, r22, 1",
        "+014: bl fn_80000000+0x20",
        "+018: R_PPC_REL24\tfn_A",
        "+01c: addi r22, r22, 2",
        "+020: bl fn_80000000+0x24",
        "+024: R_PPC_REL24\tfn_B",
        "+028: addi r22, r22, 3",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] != "inline-boundary-toolchain-artifact"
    assert "inline_boundary_artifact" not in classification
    assert not any("current omits that call" in r for r in classification["reasons"])


def test_signature_type_mismatch_requires_call_target_multiplicity_delta() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: bl fn_A",
        "+004: mr r30, r3",
        "+008: bl fn_B",
        "+00c: mr r29, r3",
    ]
    current = [
        "<fn_80000000>:",
        "+000: bl fn_B",
        "+004: mr r29, r3",
        "+008: bl fn_A",
        "+00c: mr r30, r3",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] != "signature-type-mismatch"
    assert not any("call shape differs" in r for r in classification["reasons"])


def test_pad_stack_guidance_deemphasized_when_frame_already_matches() -> None:
    checkdiff = _load_checkdiff()
    classification = {
        "primary": "control-flow-source-shape",
        "reasons": ["control-flow/source shape differs"],
        "stack_frame_sizes": {
            "expected_frame_size": 136,
            "current_frame_size": 136,
            "frame_growth": 0,
        },
    }
    probe = checkdiff.detect_diagnostic_pad_stack("void f(void) { PAD_STACK(16); }")

    checkdiff.add_pad_stack_probe_guidance(classification, probe)

    assert classification["diagnostic_pad_stack"] == {
        "pad_stack_bytes": [16],
        "total_pad_stack_bytes": 16,
    }
    reason_text = "\n".join(classification["reasons"])
    assert "frame size already matches" in reason_text
    assert "natural C that reserves" not in reason_text
    summary = checkdiff.format_summary(
        "fn_80000000",
        matched=False,
        fuzzy_pct=88.54,
        classification=classification,
    )
    assert "source_guidance=natural-frame-reservation" not in summary
    assert "source_guidance=source-shape-not-frame-reservation" in summary


def test_signature_type_mismatch_prefers_rel24_multiset_over_call_position() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: lfs f0, 0x10(r31)",
        "+004: stfs f0, 0(r30)",
        "+008: lfs f1, 0x14(r31)",
        "+00c: stfs f1, 4(r30)",
        "+010: bl GetNameText",
        "+014: R_PPC_REL24\tGetNameText",
        "+018: mr r4, r3",
    ]
    current = [
        "<fn_80000000>:",
        "+000: bl fn_80000000+0xe8",
        "+004: R_PPC_REL24\tGetNameText",
        "+008: lfs f0, 0x10(r31)",
        "+00c: stfs f0, 0(r30)",
        "+010: lfs f1, 0x14(r31)",
        "+014: stfs f1, 4(r30)",
        "+018: mr r4, r3",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] != "signature-type-mismatch"
    assert not any("call shape differs" in r for r in classification["reasons"])


def test_classify_asm_diff_labels_register_rotation_as_source_steerable() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: fadds f3, f4, f5",
        "+004: fmuls f4, f3, f6",
        "+008: stfs f4, 0(r5)",
    ]
    current = [
        "<fn_80000000>:",
        "+000: fadds f5, f6, f3",
        "+004: fmuls f6, f5, f4",
        "+008: stfs f6, 0(r5)",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] == "register-allocation"
    assert "backend_ceiling" not in classification
    reason_text = "\n".join(classification["reasons"])
    assert "register-token-only" in reason_text
    assert "source-steerable" in reason_text


def test_tiny_structural_churn_with_same_save_window_routes_to_tiebreak() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: stwu r1, -128(r1)",
        "+004: stmw r23, 64(r1)",
        "+008: li r26, 0",
        "+00c: stw r26, 0(r31)",
        "+010: beq <fn_80000000+0x30>",
        "+014: lhzu r27, 2(r28)",
        "+018: srawi r26, r26, 1",
        "+01c: srawi r27, r27, 1",
        "+020: add r28, r26, r27",
        "+024: mr r23, r28",
        "+028: bl helper",
        "+028: R_PPC_REL24\thelper",
        "+02c: lmw r23, 64(r1)",
        "+030: addi r1, r1, 128",
        "+034: blr",
    ]
    current = [
        "<fn_80000000>:",
        "+000: stwu r1, -128(r1)",
        "+004: stmw r23, 64(r1)",
        "+008: li r27, 0",
        "+00c: stw r27, 0(r31)",
        "+010: beq <fn_80000000+0x34>",
        "+014: lhz r26, 2(r28)",
        "+018: srawi r27, r27, 1",
        "+01c: srawi r26, r26, 1",
        "+020: add r28, r26, r27",
        "+024: mr r25, r28",
        "+028: bl helper",
        "+028: R_PPC_REL24\thelper",
        "+030: lmw r23, 64(r1)",
        "+034: addi r1, r1, 128",
        "+038: blr",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] == "backend-ceiling"
    assert classification["backend_ceiling"]["subclass"] == (
        "register-window-rotation"
    )
    assert classification["register_window_rotation"]["saved_gpr_window"] == {
        "first_saved_reg": "r23",
        "last_saved_reg": "r31",
        "count": 9,
    }
    reason_text = "\n".join(classification["reasons"])
    assert "same callee-save save/restore window" in reason_text
    checkdiff.add_pad_stack_probe_guidance(
        classification,
        {"pad_stack_bytes": [64], "total_pad_stack_bytes": 64},
    )
    summary = checkdiff.format_summary(
        "fn_80000000",
        matched=False,
        fuzzy_pct=98.89,
        classification=classification,
    )
    assert "diagnostic_pad_stack" not in summary
    assert "natural-frame-reservation" not in summary
    assert "source_guidance=register-window-rotation" in summary


def test_classify_asm_diff_labels_coalesce_backend_ceiling_before_calls() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80175D34>:",
        "+000: mflr r0",
        "+004: bl fn_80175D34+0x20",
        "+008: stw r3, 0x14(r1)",
        "+00c: bl fn_80175D34+0x34",
        "+010: blr",
    ]
    current = [
        "<fn_80175D34>:",
        "+000: mflr r0",
        "+004: mr r30, r0",
        "+008: bl fn_80175D34+0x24",
        "+00c: stw r3, 0x14(r1)",
        "+010: bl fn_80175D34+0x38",
        "+014: blr",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] == "backend-ceiling"
    assert classification["backend_ceiling"] == {
        "subclass": "coalesce",
        "confidence": "medium",
    }
    assert not any(
        "check prototypes" in reason for reason in classification["reasons"]
    )


def test_classify_asm_diff_labels_array_store_addressing_mode_ceiling() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_803ADE4C>:",
        "+000: mulli r4, r4, 0x24",
        "+004: addi r5, r5, 1",
        "+008: srawi r0, r5, 7",
        "+00c: add r4, r26, r4",
        "+010: addze r0, r0",
        "+014: stw r19, 0x10(r4)",
    ]
    current = [
        "<fn_803ADE4C>:",
        "+000: mulli r4, r4, 0x24",
        "+004: addi r5, r5, 1",
        "+008: srawi r0, r5, 7",
        "+00c: addi r4, r4, 0x10",
        "+010: addze r0, r0",
        "+014: stwx r19, r26, r4",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] == "backend-ceiling"
    assert classification["backend_ceiling"] == {
        "subclass": "array-element-store-addressing-mode",
        "confidence": "medium",
    }
    reason_text = "\n".join(classification["reasons"])
    assert "addressing-mode instruction selection" in reason_text
    assert "not register coloring" in reason_text


def test_array_store_addressing_mode_does_not_match_indexed_store_swaps() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80000000>:",
        "+000: addi r4, r4, 0x10",
        "+004: stwx r19, r26, r4",
    ]
    current = [
        "<fn_80000000>:",
        "+000: addi r5, r5, 0x10",
        "+004: stwx r19, r26, r5",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] != "backend-ceiling"
    assert classification.get("backend_ceiling") != {
        "subclass": "array-element-store-addressing-mode",
        "confidence": "medium",
    }


def test_classify_asm_diff_labels_divide_rematerialization_backend_ceiling() -> None:
    checkdiff = _load_checkdiff()
    expected = [
        "<fn_80188910>:",
        "+000: 3c 60 51 ec \tlis r3, 0x51ec",
        "+004: 38 03 85 1f \tsubi r0, r3, 0x7ae1",
        "+008: 7c 80 f8 96 \tmulhw r4, r0, r31",
        "+00c: 7c 80 2e 70 \tsrawi r0, r4, 5",
        "+010: 54 03 0f fe \tsrwi r3, r0, 31",
        "+014: 7c 00 1a 15 \tadd. r0, r0, r3",
        "+018: 41 82 00 38 \tbeq <fn_80188910+0x50>",
        "+01c: 7c 80 2e 70 \tsrawi r0, r4, 5",
        "+020: c8 22 9b f0 \tlfd f1, lbl_804DA610@sda21(r0)",
        "+024: 54 04 0f fe \tsrwi r4, r0, 31",
        "+028: 7c 00 22 14 \tadd r0, r0, r4",
        "+02c: 6c 00 80 00 \txoris r0, r0, 32768",
        "+030: 48 00 00 01 \tbl HSD_JObjReqAnimAll",
    ]
    current = [
        "<fn_80188910>:",
        "+000: 3c 60 51 ec \tlis r3, 0x51ec",
        "+004: 38 03 85 1f \tsubi r0, r3, 0x7ae1",
        "+008: 7c 80 f8 96 \tmulhw r4, r0, r31",
        "+00c: 7c 80 2e 70 \tsrawi r0, r4, 5",
        "+010: 54 03 0f fe \tsrwi r3, r0, 31",
        "+014: 7c 00 1a 15 \tadd. r0, r0, r3",
        "+018: 41 82 00 2c \tbeq <fn_80188910+0x44>",
        "+01c: c8 22 9b f0 \tlfd f1, lbl_804DA610@sda21(r0)",
        "+020: 6c 00 80 00 \txoris r0, r0, 32768",
        "+024: 48 00 00 01 \tbl HSD_JObjReqAnimAll",
    ]

    classification = checkdiff.classify_asm_diff(expected, current)

    assert classification["primary"] == "backend-ceiling"
    assert classification["backend_ceiling"] == {
        "subclass": "cse-vs-rematerialized-divconst",
        "confidence": "high",
    }
    assert classification["value_numbering_ceiling"]["kind"] == (
        "signed-magic-divide-rematerialization"
    )
    assert any("value-numbering ceiling" in r for r in classification["reasons"])


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
