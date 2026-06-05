from __future__ import annotations

from src.mwcc_debug.suggest_control_flow_shape import (
    analyze_control_flow_shape,
)


def _classification(primary: str = "control-flow-source-shape") -> dict:
    return {
        "primary": primary,
        "reasons": [
            "control-flow/source shape differs between target and current",
        ],
    }


def _consumer_home_call(symbol: str, offset: int, call_offset: int) -> list[str]:
    return [
        f"/* {call_offset:04X} */ addi r3, r1, 0x{offset:X}",
        f"/* {call_offset + 4:04X} */ bl {symbol}",
        f"/* {call_offset + 4:04X} */ R_PPC_REL24 {symbol}",
    ]


def test_analyze_ranks_branch_idiom_and_pointer_walk() -> None:
    target_asm = [
        "/* 0000 */ cmpwi r3, 0",
        "/* 0004 */ bne lbl_true",
        "/* 0008 */ li r0, 0",
        "/* 000C */ b lbl_done",
        "lbl_true:",
        "/* 0010 */ li r0, 1",
        "lbl_done:",
        "/* 0014 */ mulli r5, r4, 0x24",
        "/* 0018 */ add r6, r3, r5",
        "/* 001C */ lwz r7, 0x10(r6)",
    ]
    current_asm = [
        "/* 0000 */ subfic r0, r3, 0",
        "/* 0004 */ cntlzw r0, r0",
        "/* 0008 */ srwi r0, r0, 5",
        "/* 000C */ bl fn_803AC168",
        "/* 0010 */ lwz r7, 0(r3)",
    ]
    report = analyze_control_flow_shape(
        function="fn_80000000",
        target_asm=target_asm,
        current_asm=current_asm,
        classification={
            "primary": "control-flow-source-shape",
            "indexed_struct_pointer_materialization": {
                "expected_indexed_ops": ["lwz r7, 0x10(r6)"],
                "current_materialized_pointers": ["lwz r7, 0(r3)"],
            },
        },
    )

    kinds = [suggestion["kind"] for suggestion in report["suggestions"]]
    assert kinds[:2] == ["branch-idiom", "pointer-walk-indexed-shape"]
    assert report["classification"]["primary"] == "control-flow-source-shape"
    assert report["applicability"]["is_control_flow_shape"] is True
    assert report["suggestions"][0]["rank"] == 1
    assert "explicit if/else" in report["suggestions"][0]["recommendation"]
    assert "target_branch_lines" in report["suggestions"][0]["evidence"]
    assert "current_boolean_cast_lines" in report["suggestions"][0]["evidence"]
    assert report["suggestions"][1]["evidence"]["classification"][
        "expected_indexed_ops"
    ] == ["lwz r7, 0x10(r6)"]


def test_analyze_detects_call_hoist_around_loop_markers() -> None:
    target_asm = [
        "/* 0000 */ bl fn_803AC7DC",
        "/* 0004 */ R_PPC_REL24 fn_803AC7DC",
        "/* 0008 */ mtctr r3",
        "lbl_loop:",
        "/* 000C */ lwz r4, 0(r5)",
        "/* 0010 */ bdnz lbl_loop",
    ]
    current_asm = [
        "/* 0000 */ mtctr r31",
        "lbl_loop:",
        "/* 0004 */ bl fn_803AC7DC",
        "/* 0008 */ R_PPC_REL24 fn_803AC7DC",
        "/* 000C */ lwz r4, 0(r5)",
        "/* 0010 */ bdnz lbl_loop",
    ]
    report = analyze_control_flow_shape(
        function="fn_803ADF90",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )

    suggestion = next(
        item for item in report["suggestions"] if item["kind"] == "call-hoist"
    )
    assert suggestion["evidence"]["symbol"] == "fn_803AC7DC"
    assert suggestion["evidence"]["target_placement"] == "before-loop"
    assert suggestion["evidence"]["current_placement"] == "inside-loop"
    assert suggestion["evidence"]["target_call_lines"]
    assert suggestion["evidence"]["current_call_lines"]
    assert "cache" in suggestion["recommendation"]


def test_analyze_detects_call_hoist_from_backward_branch_loop() -> None:
    target_asm = [
        "+000: 48 00 00 01 \tbl      <fn_80000000+0x0>",
        "+000: R_PPC_REL24\tfn_803AC7DC",
        "+004: 7c 69 03 a6 \tmtctr   r3",
        "+008: 80 83 00 00 \tlwz     r4,0(r3)",
        "+00c: 42 00 ff fc \tbdnz    <fn_80000000+0x8>",
    ]
    current_asm = [
        "+100: 38 80 00 00 \tli      r4,0",
        "+104: 80 a3 00 00 \tlwz     r5,0(r3)",
        "+108: 38 84 00 01 \taddi    r4,r4,1",
        "+10c: 48 00 00 01 \tbl      <fn_80000000+0x10c>",
        "+10c: R_PPC_REL24\tfn_803AC7DC",
        "+110: 7c 04 18 00 \tcmpw    r4,r3",
        "+114: 41 80 ff f0 \tblt     <fn_80000000+0x104>",
    ]
    report = analyze_control_flow_shape(
        function="fn_80000000",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )

    suggestion = next(
        item for item in report["suggestions"] if item["kind"] == "call-hoist"
    )
    assert suggestion["evidence"]["symbol"] == "fn_803AC7DC"
    assert suggestion["evidence"]["current_loop_bounds"]["kind"] == (
        "backward-branch"
    )


def test_analyze_prefers_call_hoist_used_by_loop_backedge_condition() -> None:
    target_asm = [
        "+000: 48 00 00 01 \tbl      <fn_80000000+0x0>",
        "+000: R_PPC_REL24\tA_retry_helper",
        "+004: 48 00 00 01 \tbl      <fn_80000000+0x4>",
        "+004: R_PPC_REL24\tZ_trip_count_helper",
        "+008: 7c 69 03 a6 \tmtctr   r3",
        "+00c: 80 83 00 00 \tlwz     r4,0(r3)",
        "+010: 42 00 ff fc \tbdnz    <fn_80000000+0xc>",
    ]
    current_asm = [
        "+100: 38 80 00 00 \tli      r4,0",
        "+104: 48 00 00 01 \tbl      <fn_80000000+0x104>",
        "+104: R_PPC_REL24\tA_retry_helper",
        "+108: 2c 03 ff ff \tcmpwi   r3,-1",
        "+10c: 40 82 00 08 \tbne     <fn_80000000+0x114>",
        "+110: 38 84 00 01 \taddi    r4,r4,1",
        "+114: 48 00 00 01 \tbl      <fn_80000000+0x114>",
        "+114: R_PPC_REL24\tZ_trip_count_helper",
        "+118: 7c 04 18 00 \tcmpw    r4,r3",
        "+11c: 41 80 ff e8 \tblt     <fn_80000000+0x104>",
    ]
    report = analyze_control_flow_shape(
        function="fn_80000000",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )

    suggestion = next(
        item for item in report["suggestions"] if item["kind"] == "call-hoist"
    )
    assert suggestion["evidence"]["symbol"] == "Z_trip_count_helper"
    assert suggestion["evidence"]["current_condition_lines"] == [
        "+118: 7c 04 18 00 \tcmpw    r4,r3",
        "+11c: 41 80 ff e8 \tblt     <fn_80000000+0x104>",
    ]


def test_analyze_detects_missing_extra_call_layer_from_classification() -> None:
    report = analyze_control_flow_shape(
        function="fn_803B1338",
        target_asm=["/* 0000 */ bl fn_803AC168"],
        current_asm=["/* 0000 */ bl fn_803AC7DC"],
        classification={
            "primary": "inline-boundary-toolchain-artifact",
            "reasons": [
                "call shape differs and control-flow/source shape differs",
            ],
            "inline_boundary_artifact": {
                "missing_ref_calls": [
                    "fn_803AC168",
                    "fn_803AC168",
                    "fn_803AC168",
                ],
                "extra_current_calls": ["fn_803AC7DC"],
            },
        },
    )

    suggestion = report["suggestions"][0]
    assert suggestion["kind"] == "missing-extra-call-layer"
    assert suggestion["evidence"]["missing_ref_calls"] == ["fn_803AC168"] * 3
    assert suggestion["evidence"]["extra_current_calls"] == ["fn_803AC7DC"]
    assert report["applicability"]["is_control_flow_shape"] is True


def test_analyze_accepts_nested_hyphenated_classification_metadata() -> None:
    report = analyze_control_flow_shape(
        function="fn_80000000",
        target_asm=["/* 0000 */ lwzx r4, r3, r5"],
        current_asm=["/* 0000 */ add r3, r3, r5", "/* 0004 */ lwz r4, 0(r3)"],
        classification={
            "primary": "inline-boundary-toolchain-artifact",
            "details": {
                "indexed-struct-pointer-materialization": {
                    "expected_indexed_ops": ["lwzx r4, r3, r5"],
                    "current_materialized_pointers": ["lwz r4, 0(r3)"],
                },
                "inline-boundary-artifact": {
                    "missing_ref_calls": ["fn_803AC168"],
                },
            },
        },
    )

    kinds = [suggestion["kind"] for suggestion in report["suggestions"]]
    assert "pointer-walk-indexed-shape" in kinds
    assert "missing-extra-call-layer" in kinds
    assert report["applicability"]["is_control_flow_shape"] is True


def test_analyze_detects_concurrent_buffer_lifetime_coalescing() -> None:
    target_asm = (
        _consumer_home_call("fn_803AC168", 0x120, 0)
        + _consumer_home_call("fn_803AC168", 0x148, 0x10)
        + _consumer_home_call("fn_803AC168", 0x170, 0x20)
        + _consumer_home_call("fn_803AC168", 0x198, 0x30)
    )
    current_asm = (
        _consumer_home_call("fn_803AC168", 0x110, 0)
        + _consumer_home_call("fn_803AC168", 0x110, 0x10)
        + _consumer_home_call("fn_803AC168", 0x138, 0x20)
        + _consumer_home_call("fn_803AC168", 0x138, 0x30)
    )

    report = analyze_control_flow_shape(
        function="fn_803B1338",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )

    suggestion = next(
        item
        for item in report["suggestions"]
        if item["kind"] == "concurrent-buffer-lifetime"
    )
    assert suggestion["evidence"]["consumer_symbol"] == "fn_803AC168"
    assert suggestion["evidence"]["target_call_count"] == 4
    assert suggestion["evidence"]["current_call_count"] == 4
    assert suggestion["evidence"]["target_unique_home_count"] == 4
    assert suggestion["evidence"]["current_unique_home_count"] == 2
    assert suggestion["evidence"]["target_stride_candidates"] == [40]
    assert suggestion["evidence"]["target_alignment"] == 8
    assert "concurrently live" in suggestion["recommendation"]
    assert all("frame-transform" not in cmd for cmd in suggestion["follow_up_commands"])
    assert suggestion["follow_up_commands"][1].startswith(
        "melee-agent debug inspect frame-reservations "
    )


def test_concurrent_buffer_lifetime_allows_partial_current_home_extraction() -> None:
    target_asm = (
        _consumer_home_call("fn_803AC168", 0x120, 0)
        + _consumer_home_call("fn_803AC168", 0x148, 0x10)
        + _consumer_home_call("fn_803AC168", 0x170, 0x20)
        + _consumer_home_call("fn_803AC168", 0x198, 0x30)
    )
    current_asm = [
        "/* 0000 */ addi r3, r1, 0x110",
        "/* 0004 */ bl fn_803AC168",
        "/* 0004 */ R_PPC_REL24 fn_803AC168",
        "/* 0010 */ addi r3, r1, 0x110",
        "/* 0014 */ bl fn_803AC168",
        "/* 0014 */ R_PPC_REL24 fn_803AC168",
        "/* 0020 */ lwz r6, 0(r31)",
        "/* 0024 */ add r3, r1, r6",
        "/* 0028 */ bl fn_803AC168",
        "/* 0028 */ R_PPC_REL24 fn_803AC168",
        "/* 0030 */ mr r3, r30",
        "/* 0034 */ bl fn_803AC168",
        "/* 0034 */ R_PPC_REL24 fn_803AC168",
    ]

    report = analyze_control_flow_shape(
        function="fn_803B1338",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )

    suggestion = next(
        item
        for item in report["suggestions"]
        if item["kind"] == "concurrent-buffer-lifetime"
    )
    assert suggestion["evidence"]["target_call_count"] == 4
    assert suggestion["evidence"]["current_call_count"] == 4
    assert suggestion["evidence"]["target_home_bearing_call_count"] == 4
    assert suggestion["evidence"]["current_home_bearing_call_count"] == 2
    assert suggestion["evidence"]["current_repeated_offsets"] == [0x110]


def test_concurrent_buffer_lifetime_suppresses_partial_without_repeated_offsets() -> None:
    target_asm = (
        _consumer_home_call("fn_803AC168", 0x120, 0)
        + _consumer_home_call("fn_803AC168", 0x148, 0x10)
        + _consumer_home_call("fn_803AC168", 0x170, 0x20)
        + _consumer_home_call("fn_803AC168", 0x198, 0x30)
    )
    current_asm = [
        "/* 0000 */ addi r3, r1, 0x110",
        "/* 0004 */ bl fn_803AC168",
        "/* 0004 */ R_PPC_REL24 fn_803AC168",
        "/* 0010 */ addi r3, r1, 0x138",
        "/* 0014 */ bl fn_803AC168",
        "/* 0014 */ R_PPC_REL24 fn_803AC168",
        "/* 0020 */ lwz r6, 0(r31)",
        "/* 0024 */ add r3, r1, r6",
        "/* 0028 */ bl fn_803AC168",
        "/* 0028 */ R_PPC_REL24 fn_803AC168",
        "/* 0030 */ mr r3, r30",
        "/* 0034 */ bl fn_803AC168",
        "/* 0034 */ R_PPC_REL24 fn_803AC168",
    ]

    report = analyze_control_flow_shape(
        function="fn_803B1338",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )

    assert "concurrent-buffer-lifetime" not in [
        item["kind"] for item in report["suggestions"]
    ]


def test_concurrent_buffer_lifetime_requires_repeated_current_offsets() -> None:
    target_asm = [
        "/* 0000 */ addi r3, r1, 0x120",
        "/* 0004 */ addi r4, r1, 0x148",
        "/* 0008 */ bl fn_803AC168",
        "/* 0008 */ R_PPC_REL24 fn_803AC168",
        "/* 0010 */ addi r3, r1, 0x170",
        "/* 0014 */ addi r4, r1, 0x198",
        "/* 0018 */ bl fn_803AC168",
        "/* 0018 */ R_PPC_REL24 fn_803AC168",
        "/* 0020 */ addi r3, r1, 0x1C0",
        "/* 0024 */ addi r4, r1, 0x1E8",
        "/* 0028 */ bl fn_803AC168",
        "/* 0028 */ R_PPC_REL24 fn_803AC168",
    ]
    current_asm = (
        _consumer_home_call("fn_803AC168", 0x110, 0)
        + _consumer_home_call("fn_803AC168", 0x138, 0x10)
        + _consumer_home_call("fn_803AC168", 0x160, 0x20)
    )

    report = analyze_control_flow_shape(
        function="fn_803B1338",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )

    assert "concurrent-buffer-lifetime" not in [
        item["kind"] for item in report["suggestions"]
    ]


def test_concurrent_buffer_lifetime_suppresses_cardstate_stride_only_delta() -> None:
    target_asm = (
        _consumer_home_call("fn_803AC168", 0x5C, 0)
        + _consumer_home_call("fn_803AC168", 0x84, 0x10)
        + _consumer_home_call("fn_803AC168", 0xAC, 0x20)
        + _consumer_home_call("fn_803AC168", 0xD4, 0x30)
        + _consumer_home_call("fn_803AC168", 0xFC, 0x40)
    )
    current_asm = (
        _consumer_home_call("fn_803AC168", 0x60, 0)
        + _consumer_home_call("fn_803AC168", 0x84, 0x10)
        + _consumer_home_call("fn_803AC168", 0xA8, 0x20)
        + _consumer_home_call("fn_803AC168", 0xCC, 0x30)
        + _consumer_home_call("fn_803AC168", 0xF0, 0x40)
    )

    report = analyze_control_flow_shape(
        function="fn_803AE7F8",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )

    assert "concurrent-buffer-lifetime" not in [
        item["kind"] for item in report["suggestions"]
    ]


def test_concurrent_buffer_lifetime_clears_argument_homes_across_calls() -> None:
    target_asm = (
        _consumer_home_call("fn_803AC168", 0x120, 0)
        + _consumer_home_call("fn_803AC168", 0x148, 0x10)
        + _consumer_home_call("fn_803AC168", 0x170, 0x20)
    )
    current_asm = [
        "/* 0000 */ addi r3, r1, 0x110",
        "/* 0004 */ bl fn_803AC168",
        "/* 0004 */ R_PPC_REL24 fn_803AC168",
        "/* 0008 */ mr r4, r4",
        "/* 000C */ bl fn_803AC168",
        "/* 000C */ R_PPC_REL24 fn_803AC168",
        "/* 0010 */ mr r5, r5",
        "/* 0014 */ bl fn_803AC168",
        "/* 0014 */ R_PPC_REL24 fn_803AC168",
    ]

    report = analyze_control_flow_shape(
        function="fn_803B1338",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )

    assert "concurrent-buffer-lifetime" not in [
        item["kind"] for item in report["suggestions"]
    ]


def test_concurrent_buffer_lifetime_suppresses_missing_call_layer() -> None:
    target_asm = (
        _consumer_home_call("fn_803AC168", 0x120, 0)
        + _consumer_home_call("fn_803AC168", 0x148, 0x10)
        + _consumer_home_call("fn_803AC168", 0x170, 0x20)
    )
    current_asm = [
        "/* 0000 */ addi r3, r1, 0x110",
        "/* 0004 */ bl fn_803AC7DC",
        "/* 0004 */ R_PPC_REL24 fn_803AC7DC",
    ]
    report = analyze_control_flow_shape(
        function="fn_803B1338",
        target_asm=target_asm,
        current_asm=current_asm,
        classification={
            "primary": "inline-boundary-toolchain-artifact",
            "reasons": ["control-flow/source shape differs"],
            "inline_boundary_artifact": {
                "missing_ref_calls": ["fn_803AC168"],
                "extra_current_calls": ["fn_803AC7DC"],
            },
        },
    )
    kinds = [item["kind"] for item in report["suggestions"]]
    assert "missing-extra-call-layer" in kinds
    assert "concurrent-buffer-lifetime" not in kinds


def test_concurrent_buffer_lifetime_suppresses_different_call_counts() -> None:
    target_asm = (
        _consumer_home_call("fn_803AC168", 0x120, 0)
        + _consumer_home_call("fn_803AC168", 0x148, 0x10)
        + _consumer_home_call("fn_803AC168", 0x170, 0x20)
    )
    current_asm = (
        _consumer_home_call("fn_803AC168", 0x110, 0)
        + _consumer_home_call("fn_803AC168", 0x110, 0x10)
    )
    report = analyze_control_flow_shape(
        function="fn_803B1338",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )
    assert "concurrent-buffer-lifetime" not in [
        item["kind"] for item in report["suggestions"]
    ]


def test_concurrent_buffer_lifetime_suppresses_alignment_only() -> None:
    target_asm = (
        _consumer_home_call("fn_803AC168", 0x120, 0)
        + _consumer_home_call("fn_803AC168", 0x148, 0x10)
        + _consumer_home_call("fn_803AC168", 0x170, 0x20)
    )
    current_asm = (
        _consumer_home_call("fn_803AC168", 0x124, 0)
        + _consumer_home_call("fn_803AC168", 0x14C, 0x10)
        + _consumer_home_call("fn_803AC168", 0x174, 0x20)
    )
    report = analyze_control_flow_shape(
        function="fn_803B1338",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )
    assert "concurrent-buffer-lifetime" not in [
        item["kind"] for item in report["suggestions"]
    ]


def test_concurrent_buffer_lifetime_extracts_alias_and_constant_add_homes() -> None:
    target_asm = [
        "/* 0000 */ li r6, 0x120",
        "/* 0004 */ add r5, r1, r6",
        "/* 0008 */ mr r3, r5",
        "/* 000C */ bl fn_803AC168",
        "/* 000C */ R_PPC_REL24 fn_803AC168",
        "/* 0010 */ addi r4, r0, 0x148",
        "/* 0014 */ add r3, r1, r4",
        "/* 0018 */ bl fn_803AC168",
        "/* 0018 */ R_PPC_REL24 fn_803AC168",
        "/* 001C */ addi r4, 0, 0x170",
        "/* 0020 */ add r3, r1, r4",
        "/* 0024 */ bl fn_803AC168",
        "/* 0024 */ R_PPC_REL24 fn_803AC168",
    ]
    current_asm = [
        "/* 0000 */ addi r3, r1, 0x110",
        "/* 0004 */ bl fn_803AC168",
        "/* 0004 */ R_PPC_REL24 fn_803AC168",
        "/* 0008 */ addi r3, r1, 0x110",
        "/* 000C */ bl fn_803AC168",
        "/* 000C */ R_PPC_REL24 fn_803AC168",
        "/* 0010 */ addi r3, r1, 0x138",
        "/* 0014 */ bl fn_803AC168",
        "/* 0014 */ R_PPC_REL24 fn_803AC168",
    ]
    report = analyze_control_flow_shape(
        function="fn_803B1338",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )
    assert any(
        item["kind"] == "concurrent-buffer-lifetime"
        for item in report["suggestions"]
    )


def test_concurrent_buffer_lifetime_extracts_decimal_offsets_with_stores_and_consumers() -> None:
    target_asm = [
        "/* 0000 */ addi r3, r1, 288",
        "/* 0004 */ stw r0, 0(r31)",
        "/* 0008 */ bl fn_803AC168",
        "/* 0008 */ R_PPC_REL24 fn_803AC168",
        "/* 0010 */ addi r3, r1, 328",
        "/* 0014 */ stw r0, 4(r31)",
        "/* 0018 */ bl fn_803AC168",
        "/* 0018 */ R_PPC_REL24 fn_803AC168",
        "/* 0020 */ addi r3, r1, 368",
        "/* 0024 */ bl fn_803AC168",
        "/* 0024 */ R_PPC_REL24 fn_803AC168",
        "/* 0030 */ addi r3, r1, 64",
        "/* 0034 */ bl fn_803AD000",
        "/* 0034 */ R_PPC_REL24 fn_803AD000",
        "/* 0040 */ addi r3, r1, 104",
        "/* 0044 */ bl fn_803AD000",
        "/* 0044 */ R_PPC_REL24 fn_803AD000",
        "/* 0050 */ addi r3, r1, 144",
        "/* 0054 */ bl fn_803AD000",
        "/* 0054 */ R_PPC_REL24 fn_803AD000",
    ]
    current_asm = [
        "/* 0000 */ addi r3, r1, 272",
        "/* 0004 */ stw r0, 0(r31)",
        "/* 0008 */ bl fn_803AC168",
        "/* 0008 */ R_PPC_REL24 fn_803AC168",
        "/* 0010 */ addi r3, r1, 272",
        "/* 0014 */ bl fn_803AC168",
        "/* 0014 */ R_PPC_REL24 fn_803AC168",
        "/* 0020 */ addi r3, r1, 312",
        "/* 0024 */ bl fn_803AC168",
        "/* 0024 */ R_PPC_REL24 fn_803AC168",
        "/* 0030 */ addi r3, r1, 80",
        "/* 0034 */ bl fn_803AD000",
        "/* 0034 */ R_PPC_REL24 fn_803AD000",
        "/* 0040 */ addi r3, r1, 120",
        "/* 0044 */ bl fn_803AD000",
        "/* 0044 */ R_PPC_REL24 fn_803AD000",
        "/* 0050 */ addi r3, r1, 160",
        "/* 0054 */ bl fn_803AD000",
        "/* 0054 */ R_PPC_REL24 fn_803AD000",
    ]

    report = analyze_control_flow_shape(
        function="fn_803B1338",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )

    suggestion = next(
        item
        for item in report["suggestions"]
        if item["kind"] == "concurrent-buffer-lifetime"
    )
    assert suggestion["evidence"]["consumer_symbol"] == "fn_803AC168"
    assert suggestion["evidence"]["target_stride_candidates"] == [40]
    assert "/* 0000 */ addi r3, r1, 288" in suggestion["evidence"][
        "target_home_lines"
    ]


def test_concurrent_buffer_lifetime_ignores_dynamic_or_non_stack_homes() -> None:
    target_asm = (
        _consumer_home_call("fn_803AC168", 0x120, 0)
        + _consumer_home_call("fn_803AC168", 0x148, 0x10)
        + _consumer_home_call("fn_803AC168", 0x170, 0x20)
    )
    current_asm = [
        "/* 0000 */ lwz r6, 0(r31)",
        "/* 0004 */ add r3, r1, r6",
        "/* 0008 */ bl fn_803AC168",
        "/* 0008 */ R_PPC_REL24 fn_803AC168",
        "/* 000C */ lis r3, global_buffer@ha",
        "/* 0010 */ bl fn_803AC168",
        "/* 0010 */ R_PPC_REL24 fn_803AC168",
        "/* 0014 */ mr r3, r30",
        "/* 0018 */ bl fn_803AC168",
        "/* 0018 */ R_PPC_REL24 fn_803AC168",
    ]
    report = analyze_control_flow_shape(
        function="fn_803B1338",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )
    assert "concurrent-buffer-lifetime" not in [
        item["kind"] for item in report["suggestions"]
    ]


def test_analyze_detects_loop_peel_unroll_repeated_body() -> None:
    target_asm = [
        "/* 0000 */ lwz r4, 0(r3)",
        "/* 0004 */ addi r3, r3, 0x24",
        "/* 0008 */ lwz r4, 0(r3)",
        "/* 000C */ addi r3, r3, 0x24",
        "/* 0010 */ mtctr r5",
        "lbl_loop:",
        "/* 0014 */ lwz r4, 0(r3)",
        "/* 0018 */ addi r3, r3, 0x24",
        "/* 001C */ bdnz lbl_loop",
    ]
    current_asm = [
        "/* 0000 */ mtctr r5",
        "lbl_loop:",
        "/* 0004 */ lwz r4, 0(r3)",
        "/* 0008 */ addi r3, r3, 0x24",
        "/* 000C */ bdnz lbl_loop",
    ]
    report = analyze_control_flow_shape(
        function="fn_80000000",
        target_asm=target_asm,
        current_asm=current_asm,
        classification=_classification(),
    )

    suggestion = next(
        item
        for item in report["suggestions"]
        if item["kind"] == "loop-peel-unroll"
    )
    assert suggestion["evidence"]["repeated_signature_count"] >= 2
    assert "peel" in suggestion["recommendation"]


def test_analyze_non_control_flow_classification_marks_not_applicable() -> None:
    report = analyze_control_flow_shape(
        function="fn_80000000",
        target_asm=["/* 0000 */ mr r3, r4"],
        current_asm=["/* 0000 */ mr r3, r4"],
        classification={"primary": "register-allocation", "reasons": []},
    )

    assert report["applicability"]["is_control_flow_shape"] is False
    assert report["suggestions"] == []
    assert "not classified" in report["summary"]


def test_analyze_top_clips_ranked_suggestions() -> None:
    report = analyze_control_flow_shape(
        function="fn_80000000",
        target_asm=[
            "/* 0000 */ cmpwi r3, 0",
            "/* 0004 */ bne lbl_true",
            "/* 0008 */ li r0, 0",
            "/* 000C */ b lbl_done",
            "lbl_true:",
            "/* 0010 */ li r0, 1",
            "/* 0014 */ bl helper",
            "/* 0018 */ R_PPC_REL24 helper",
            "/* 001C */ mtctr r5",
            "lbl_loop:",
            "/* 0020 */ lwz r4, 0(r3)",
            "/* 0024 */ addi r3, r3, 0x24",
            "/* 0028 */ bdnz lbl_loop",
        ],
        current_asm=[
            "/* 0000 */ subfic r0, r3, 0",
            "/* 0004 */ cntlzw r0, r0",
            "/* 0008 */ srwi r0, r0, 5",
            "/* 000C */ mtctr r5",
            "lbl_loop:",
            "/* 0010 */ bl helper",
            "/* 0014 */ R_PPC_REL24 helper",
            "/* 0018 */ lwz r4, 0(r3)",
            "/* 001C */ bdnz lbl_loop",
        ],
        classification=_classification(),
        top=1,
    )

    assert len(report["suggestions"]) == 1
    assert report["suggestions"][0]["rank"] == 1
