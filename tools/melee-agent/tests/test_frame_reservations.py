"""Tests for stack frame reservation diagnostics."""

from __future__ import annotations

import textwrap

from src.mwcc_debug.frame_reservations import analyze_frame_reservations


def test_frame_reservation_report_finds_extra_unused_low_frame_gap() -> None:
    pcdump = textwrap.dedent("""\
        Starting function grIceMt_801F9ACC
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        grIceMt_801F9ACC
        B0: Succ={} Pred={} Labels={}
            mflr r0
            stw r0,4(r1)
            stwu r1,-88(r1)
            stfd f31,80(r1)
            stfd f30,72(r1)
            stfd f29,64(r1)
            stmw r26,40(r1)
            mr r31,r3
            lmw r26,40(r1)
            lwz r0,92(r1)
            lfd f29,64(r1)
            lfd f30,72(r1)
            lfd f31,80(r1)
            addi r1,r1,88
    """)
    expected_asm = textwrap.dedent("""\
        .fn grIceMt_801F9ACC, global
        /* 801F9ACC */    mflr r0
        /* 801F9AD4 */    stw r0, 0x4(r1)
        /* 801F9AD8 */    stwu r1, -0x98(r1)
        /* 801F9ADC */    stfd f31, 0x90(r1)
        /* 801F9AE0 */    stfd f30, 0x88(r1)
        /* 801F9AE4 */    stfd f29, 0x80(r1)
        /* 801F9AE8 */    stmw r26, 0x68(r1)
        /* 801FA09C */    lmw r26, 0x68(r1)
        /* 801FA0A4 */    lfd f31, 0x90(r1)
        /* 801FA0A8 */    lfd f30, 0x88(r1)
        /* 801FA0AC */    lfd f29, 0x80(r1)
        /* 801FA0B0 */    addi r1, r1, 0x98
        .endfn grIceMt_801F9ACC
    """)

    report = analyze_frame_reservations(
        pcdump,
        "grIceMt_801F9ACC",
        expected_asm_text=expected_asm,
    )

    assert report["current"]["frame_size"] == 88
    assert report["expected"]["frame_size"] == 152
    assert report["frame_delta"] == 64
    assert report["current"]["unused_ranges"][0] == {
        "start": 8,
        "end": 40,
        "size": 32,
    }
    assert report["expected"]["unused_ranges"][0] == {
        "start": 8,
        "end": 104,
        "size": 96,
    }
    assert report["extra_low_frame_reservation"] == {
        "start": 40,
        "end": 104,
        "size": 64,
        "origin": "implicit-frame-reservation",
        "current_accesses_in_range": [],
    }
    assert "no current pcode stack access" in report["summary"]


def test_frame_reservation_report_labels_callee_save_access_ranges() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu r1,-56(r1)
            stmw r28,24(r1)
            stfd f31,48(r1)
            lfd f31,48(r1)
            lmw r28,24(r1)
            addi r1,r1,56
    """)

    report = analyze_frame_reservations(pcdump, "fn_80000000")

    access_ranges = report["current"]["access_ranges"]
    assert {
        "start": 24,
        "end": 40,
        "size": 16,
        "kind": "callee-save-gpr",
    } in access_ranges
    assert {
        "start": 48,
        "end": 56,
        "size": 8,
        "kind": "callee-save-fpr",
    } in access_ranges
    assert report["current"]["unused_ranges"] == [
        {"start": 8, "end": 24, "size": 16},
        {"start": 40, "end": 48, "size": 8},
    ]


def test_frame_reservation_resolves_symbolic_stack_homes_from_current_asm() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000001
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000001
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-168(r1)
            stfs    f0,@810(r1); fIsVolatile
            lfs     f31,@810(r1); fIsVolatile
            addi    r1,r1,168
    """)
    current_asm = textwrap.dedent("""\
        +000: 94 21 ff 58 \tstwu    r1,-168(r1)
        +004: d0 01 00 30 \tstfs    f0,48(r1)
        +008: c3 e1 00 30 \tlfs     f31,48(r1)
        +00c: 38 21 00 a8 \taddi    r1,r1,168
    """)

    report = analyze_frame_reservations(
        pcdump,
        "fn_80000001",
        current_asm_text=current_asm,
    )

    accesses = [
        item
        for item in report["current"]["accesses"]
        if item["opcode"] in {"stfs", "lfs"}
    ]
    assert [item["offset"] for item in accesses] == [0x30, 0x30]
    assert all(item["original_operands"].endswith("@810(r1)") for item in accesses)
    assert all(item["symbolic_home"] == "@810" for item in accesses)
    assert report["current"]["symbolic_home_map"] == [
        {"symbol": "@810", "offset": 0x30}
    ]
    assert report["current"]["unresolved_symbolic_homes"] == []
    assert {
        "start": 0x30,
        "end": 0x34,
        "size": 4,
        "kind": "local-or-temporary",
    } in report["current"]["access_ranges"]


def test_frame_reservation_reports_unresolved_symbolic_homes_without_offset() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000001
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000001
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-168(r1)
            stfs    f0,@810(r1); fIsVolatile
            addi    r1,r1,168
    """)

    report = analyze_frame_reservations(pcdump, "fn_80000001")

    assert report["current"]["access_ranges"] == []
    assert report["current"]["accesses"] == []
    assert report["current"]["unresolved_symbolic_homes"] == [
        {
            "symbol": "@810",
            "opcode": "stfs",
            "operands": "f0,@810(r1)",
            "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
            "block_idx": 0,
            "instr_idx": 1,
        }
    ]


def test_frame_reservation_resolves_named_local_stack_homes_from_current_asm() -> None:
    pcdump = textwrap.dedent("""\
        Starting function MatToQuat
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        MatToQuat
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-80(r1)
            stfs    f4,lenCol+8(r1)
            stfs    f5,lenCol+12(r1)
            stfs    f6,q3(r1)
            stfs    f7,nxt(r1)
            addi    r1,r1,80
    """)
    current_asm = textwrap.dedent("""\
        +000: 94 21 ff b0 \tstwu    r1,-80(r1)
        +004: d0 81 00 30 \tstfs    f4,48(r1)
        +008: d0 a1 00 34 \tstfs    f5,52(r1)
        +00c: d0 c1 00 28 \tstfs    f6,40(r1)
        +010: d0 e1 00 40 \tstfs    f7,64(r1)
        +014: 38 21 00 50 \taddi    r1,r1,80
    """)
    expected_asm = textwrap.dedent("""\
        .fn MatToQuat, global
        /* 80342360 */    stwu r1, -0x48(r1)
        /* 80342364 */    stfs f6, 0x24(r1)
        /* 80342368 */    stfs f4, 0x2c(r1)
        /* 8034236c */    stfs f5, 0x30(r1)
        /* 80342370 */    stfs f7, 0x3c(r1)
        /* 80342374 */    addi r1, r1, 0x48
        .endfn MatToQuat
    """)

    report = analyze_frame_reservations(
        pcdump,
        "MatToQuat",
        expected_asm_text=expected_asm,
        current_asm_text=current_asm,
    )

    assert report["current"]["symbolic_home_map"] == [
        {"symbol": "lenCol+12", "offset": 0x34},
        {"symbol": "lenCol+8", "offset": 0x30},
        {"symbol": "nxt", "offset": 0x40},
        {"symbol": "q3", "offset": 0x28},
    ]
    assert report["current"]["unresolved_symbolic_homes"] == []
    assert [
        item["offset"]
        for item in report["current"]["accesses"]
        if item["opcode"] == "stfs"
    ] == [0x30, 0x34, 0x28, 0x40]
    assert report["extra_low_frame_reservation"] is None
