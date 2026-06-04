"""Tests for stack frame reservation diagnostics."""

from __future__ import annotations

import textwrap

from src.mwcc_debug.frame_reservations import (
    analyze_frame_from_asm_text,
    analyze_frame_reservations,
    evaluate_frame_transform_probe_results,
    evaluate_stack_home_probe_results,
)


def test_analyze_frame_from_asm_text_accepts_checkdiff_lines() -> None:
    frame = analyze_frame_from_asm_text(textwrap.dedent("""\
        <gm_801A9DD0>:
        +014: 94 21 ff 70 \tstwu    r1,-144(r1)
        +060: 91 01 00 24 \tstw     r8,36(r1)
        +13c: 38 81 00 38 \taddi    r4,r1,56
        +1f0: 38 21 00 90 \taddi    r1,r1,144
    """))

    assert frame["frame_size"] == 144
    assert {
        "start": 36,
        "end": 40,
        "size": 4,
        "kind": "local-or-temporary",
    } in frame["access_ranges"]


def test_expected_frame_model_exposes_stack_objects_from_target_asm() -> None:
    frame = analyze_frame_from_asm_text(textwrap.dedent("""\
        .fn fn_80000000, global
        /* 80000000 */    stwu    r1,-0x38(r1)
        /* 80000004 */    stw     r0,0x4(r1)
        /* 80000008 */    stw     r8,0x18(r1)
        /* 8000000c */    lfs     f0,0x20(r1)
        /* 80000010 */    stmw    r28,0x28(r1)
        /* 80000014 */    addi    r1,r1,0x38
        .endfn fn_80000000
    """))

    assert frame["frame_size"] == 0x38
    assert frame["stack_object_map_status"] == "best-effort-from-r1-accesses"
    assert {
        "start": 0,
        "end": 8,
        "size": 8,
        "kind": "abi-header",
        "source": "implicit",
        "boundary_confidence": "implicit",
        "ambiguous": False,
    } in frame["stack_objects"]
    assert {
        "start": 0x18,
        "end": 0x1C,
        "size": 4,
        "kind": "local-or-temporary",
        "source": "r1-access",
        "boundary_confidence": "access-width",
        "ambiguous": False,
        "access_count": 1,
        "opcodes": ["stw"],
    } in frame["stack_objects"]
    assert {
        "start": 0x28,
        "end": 0x38,
        "size": 0x10,
        "kind": "callee-save-gpr",
        "source": "r1-access",
        "boundary_confidence": "access-width",
        "ambiguous": False,
        "access_count": 1,
        "opcodes": ["stmw"],
    } in frame["stack_objects"]
    assert {
        "start": 8,
        "end": 0x18,
        "size": 0x10,
        "kind": "unused",
        "source": "gap",
        "boundary_confidence": "unused-gap",
        "ambiguous": False,
    } in frame["stack_objects"]


def test_frame_reservation_report_exposes_pass_frame_timeline() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000000
        AFTER REGISTER COLORING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu r1,-72(r1)
            stw r8,24(r1)
            addi r1,r1,72
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu r1,-80(r1)
            stw r8,24(r1)
            stw r9,32(r1)
            addi r1,r1,80
    """)

    report = analyze_frame_reservations(pcdump, "fn_80000000")

    timeline = report["pass_frame_timeline"]
    assert timeline["status"] == "computed"
    assert timeline["pass_count"] == 2
    assert timeline["first_change"] == {
        "status": "changed",
        "pass_index": 1,
        "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
        "previous_pass": "AFTER REGISTER COLORING",
        "frame_size_before": 72,
        "frame_size_after": 80,
        "frame_size_delta": 8,
        "object_signature_changed": True,
        "reason": "frame-size-and-object-layout-changed",
    }
    assert timeline["passes"][0]["pass"] == "AFTER REGISTER COLORING"
    assert timeline["passes"][0]["frame_size"] == 72
    assert timeline["passes"][1]["pass"] == "FINAL CODE AFTER INSTRUCTION SCHEDULING"
    assert timeline["passes"][1]["frame_size"] == 80
    assert timeline["passes"][1]["frame_size_delta_from_previous"] == 8
    assert timeline["passes"][1]["object_signature_changed_from_previous"] is True


def test_frame_allocation_trace_realizes_symbolic_stack_homes() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu r1,-56(r1)
            stw r8,local_temp(r1)
            stmw r28,40(r1)
            addi r1,r1,56
    """)
    current_asm = textwrap.dedent("""\
        .fn fn_80000000, global
        /* 80000000 */    stwu r1, -0x38(r1)
        /* 80000004 */    stw r8, 0x18(r1)
        /* 80000008 */    stmw r28, 0x28(r1)
        /* 8000000c */    addi r1, r1, 0x38
        .endfn fn_80000000
    """)

    report = analyze_frame_reservations(
        pcdump,
        "fn_80000000",
        current_asm_text=current_asm,
    )

    trace = report["current"]["frame_allocation_trace"]
    assert trace["status"] == "computed"
    assert trace["instrumentation_source"] == (
        "pcdump-final-pass-and-emitted-r1-accesses"
    )
    assert trace["allocator_pass_status"] == "not-located"
    assert "reconstructed from final pcdump/asm r1 offsets" in (
        trace["allocator_pass_status_reason"]
    )
    assert trace["validation"]["frame_size_matches"] is True
    assert trace["validation"]["uncovered_access_count"] == 0
    assert trace["validation"]["r1_access_coverage_matches"] is True
    assert trace["validation"]["symbolic_stack_homes_present"] is True
    assert any(
        obj["origin_tag"] == "symbolic-stack-home"
        and obj["symbol"] == "local_temp"
        and obj["start"] == 0x18
        and obj["symbolic_assignment_order"] == 0
        and isinstance(obj["layout_order"], int)
        for obj in trace["objects"]
    )
    assert any(
        "MWCC stack-frame allocator pass/symbol was not located" in item
        for item in trace["limitations"]
    )


def test_frame_allocation_trace_preserves_aliased_symbolic_home_orders() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu r1,-40(r1)
            stw r8,b_home(r1)
            lwz r9,a_home(r1)
            addi r1,r1,40
    """)
    current_asm = textwrap.dedent("""\
        .fn fn_80000000, global
        /* 80000000 */    stwu r1, -0x28(r1)
        /* 80000004 */    stw r8, 0x18(r1)
        /* 80000008 */    lwz r9, 0x18(r1)
        /* 8000000c */    addi r1, r1, 0x28
        .endfn fn_80000000
    """)

    report = analyze_frame_reservations(
        pcdump,
        "fn_80000000",
        current_asm_text=current_asm,
    )

    symbolic_object = next(
        obj
        for obj in report["current"]["frame_allocation_trace"]["objects"]
        if obj["origin_tag"] == "symbolic-stack-home"
    )
    assert symbolic_object["symbol"] == "b_home"
    assert symbolic_object["symbolic_assignment_order"] == 0
    assert symbolic_object["symbolic_assignment_orders"] == {
        "b_home": 0,
        "a_home": 1,
    }


def test_frame_allocation_trace_covers_raw_asm_objects_and_gaps() -> None:
    frame = analyze_frame_from_asm_text(textwrap.dedent("""\
        .fn fn_80000000, global
        /* 80000000 */    stwu    r1,-0x38(r1)
        /* 80000004 */    stw     r8,0x18(r1)
        /* 80000008 */    stmw    r28,0x28(r1)
        /* 8000000c */    addi    r1,r1,0x38
        .endfn fn_80000000
    """))

    trace = frame["frame_allocation_trace"]
    assert trace["status"] == "computed"
    assert trace["instrumentation_source"] == "asm-r1-accesses"
    assert trace["validation"]["frame_size_matches"] is True
    assert trace["validation"]["uncovered_access_count"] == 0
    assert {
        "implicit-abi-header",
        "r1-access-local-or-temporary",
        "callee-save-gpr",
        "frame-gap-or-alignment-pad",
    } <= {obj["origin_tag"] for obj in trace["objects"]}


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


def test_frame_reservation_report_finds_current_low_home_realignment_growth() -> None:
    pcdump = textwrap.dedent("""\
        Starting function gm_801A9DD0
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        gm_801A9DD0
        B0: Succ={} Pred={} Labels={}
            stw r0,4(r1)
            stwu r1,-152(r1)
            stfd f31,144(r1)
            stfd f30,136(r1)
            stw r8,40(r1)
            stw r7,28(r1)
            stw r9,72(r1)
            lfd f0,72(r1)
            stw r9,80(r1)
            lfd f0,80(r1)
            lfd f30,136(r1)
            lfd f31,144(r1)
            addi r1,r1,152
    """)
    expected_asm = textwrap.dedent("""\
        .fn gm_801A9DD0, global
        /* 801A9DD8 */    stw r0, 0x4(r1)
        /* 801A9DDC */    stwu r1, -0x90(r1)
        /* 801A9DE0 */    stfd f31, 0x88(r1)
        /* 801A9DE4 */    stfd f30, 0x80(r1)
        /* 801A9DE8 */    stw r8, 0x24(r1)
        /* 801A9DEC */    stw r7, 0x18(r1)
        /* 801A9DF0 */    stw r9, 0x40(r1)
        /* 801A9DF4 */    lfd f0, 0x40(r1)
        /* 801A9DF8 */    stw r9, 0x48(r1)
        /* 801A9DFC */    lfd f0, 0x48(r1)
        /* 801A9E00 */    lfd f30, 0x80(r1)
        /* 801A9E04 */    lfd f31, 0x88(r1)
        /* 801A9E08 */    addi r1, r1, 0x90
        .endfn gm_801A9DD0
    """)

    report = analyze_frame_reservations(
        pcdump,
        "gm_801A9DD0",
        expected_asm_text=expected_asm,
    )

    signature = report["current_low_frame_expansion"]
    assert signature == {
        "start": 24,
        "end": 28,
        "size": 4,
        "origin": "implicit-current-low-local-home",
        "frame_growth_bytes": 8,
        "alignment_growth_bytes": 4,
        "first_non_abi_access_expected": 24,
        "first_non_abi_access_current": 28,
        "current_accesses_in_range": [],
    }
    assert "implicit unused low local home" in report["summary"]
    assert "plus 4 bytes of alignment growth" in report["summary"]


def test_frame_reservation_reports_first_occupied_object_divergence() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu r1,-56(r1)
            stw r8,local_temp(r1)
            stmw r28,40(r1)
            addi r1,r1,56
    """)
    current_asm = textwrap.dedent("""\
        .fn fn_80000000, global
        /* 80000000 */    stwu r1, -0x38(r1)
        /* 80000004 */    stw r8, 0x1c(r1)
        /* 80000008 */    stmw r28, 0x28(r1)
        /* 8000000c */    addi r1, r1, 0x38
        .endfn fn_80000000
    """)
    expected_asm = textwrap.dedent("""\
        .fn fn_80000000, global
        /* 80000000 */    stwu r1, -0x38(r1)
        /* 80000004 */    stw r8, 0x18(r1)
        /* 80000008 */    stmw r28, 0x28(r1)
        /* 8000000c */    addi r1, r1, 0x38
        .endfn fn_80000000
    """)

    report = analyze_frame_reservations(
        pcdump,
        "fn_80000000",
        current_asm_text=current_asm,
        expected_asm_text=expected_asm,
    )

    divergence = report["frame_first_divergence"]
    assert divergence["status"] == "diverged"
    assert divergence["index"] == 0
    assert divergence["reason"] == "start-differs"
    assert divergence["current"]["start"] == 28
    assert divergence["current"]["source_symbols"] == ["local_temp"]
    assert divergence["expected"]["start"] == 24
    assert divergence["cause_hypothesis"] == {
        "status": "heuristic",
        "kind": "lifetime-or-ordering-shift",
        "confidence": "medium",
        "reason": (
            "attributed stack object has the same shape but different offsets; "
            "inspect local lifetime, first-use order, address-taking, or alignment"
        ),
        "source_object_symbol": "local_temp",
        "current_expected_offset_delta": 4,
        "frame_delta": 0,
    }
    assert divergence["source_attribution"] == {
        "status": "source-object-attributed",
        "identity_kind": "symbolic-stack-home",
        "confidence": "medium",
        "current_symbols": ["local_temp"],
        "expected_symbols": ["local_temp"],
        "primary_source_object": {
            "symbol": "local_temp",
            "identity_kind": "symbolic-stack-home",
            "side": "both",
            "current_offset": 28,
            "expected_offset": 24,
            "offset_delta": 4,
            "size": 4,
            "kind": "local-or-temporary",
            "opcodes": ["stw"],
            "access_count": 1,
            "first_access": {
                "opcode": "stw",
                "operands": "r8,local_temp(r1)",
                "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                "block_idx": 0,
                "instr_idx": 1,
            },
        },
        "source_objects": [
            {
                "symbol": "local_temp",
                "identity_kind": "symbolic-stack-home",
                "side": "both",
                "current_offset": 28,
                "expected_offset": 24,
                "offset_delta": 4,
                "size": 4,
                "kind": "local-or-temporary",
                "opcodes": ["stw"],
                "access_count": 1,
                "first_access": {
                    "opcode": "stw",
                    "operands": "r8,local_temp(r1)",
                    "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                    "block_idx": 0,
                    "instr_idx": 1,
                },
            },
        ],
        "reason": (
            "diverging stack object maps to resolved symbolic stack-home identity"
        ),
    }
    assert divergence["verdict"] == {
        "status": "source-reachable-candidate",
        "reason": (
            "heuristic cause lifetime-or-ordering-shift for local_temp is "
            "addressable by targeted frame/lifetime source probes"
        ),
            "confidence": "medium",
        "source_object_symbol": "local_temp",
    }
    assert divergence["frame_transform_probe_plan"] == {
        "status": "ready",
        "objective": "reduce frame/local-area divergence toward expected",
        "cause_kind": "lifetime-or-ordering-shift",
        "operator_priority": [
            "declaration-use-distance",
            "block-scope",
            "frame-direct-literal-at-final-fp-call",
            "frame-split-fp-const-lifetime",
        ],
        "suggested_commands": [
            {
                "kind": "suggest-frame",
                "command": "melee-agent debug suggest frame -f fn_80000000 --json",
            },
            {
                "kind": "lifetime-layout",
                "command": (
                    "melee-agent debug mutate lifetime-layout -f fn_80000000 "
                    "--operator declaration-use-distance --operator block-scope "
                    "--operator frame-direct-literal-at-final-fp-call "
                    "--operator frame-split-fp-const-lifetime --compile-probes --json"
                ),
            },
            {
                "kind": "tier3-frame-search",
                "command": "melee-agent debug mutate search -f fn_80000000 --budget 5",
            },
        ],
        "validation": {
            "status": "required",
            "command": (
                "melee-agent debug inspect frame-reservations -f fn_80000000 "
                "--expected-asm <expected.s> --probe-results-json "
                "<lifetime-layout.json> --json"
            ),
        },
    }


def test_frame_reservation_reports_frame_size_only_divergence() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu r1,-64(r1)
            stw r8,24(r1)
            stmw r28,40(r1)
            addi r1,r1,64
    """)
    expected_asm = textwrap.dedent("""\
        .fn fn_80000000, global
        /* 80000000 */    stwu r1, -0x38(r1)
        /* 80000004 */    stw r8, 0x18(r1)
        /* 80000008 */    stmw r28, 0x28(r1)
        /* 8000000c */    addi r1, r1, 0x38
        .endfn fn_80000000
    """)

    report = analyze_frame_reservations(
        pcdump,
        "fn_80000000",
        expected_asm_text=expected_asm,
    )

    assert report["frame_delta"] == -8
    assert report["frame_first_divergence"] == {
        "status": "frame-size-only",
        "frame_delta": -8,
        "source_attribution": {
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
        },
        "cause_hypothesis": {
            "status": "heuristic",
            "kind": "extra-frame-reservation-or-alignment",
            "confidence": "medium",
            "reason": (
                "frame sizes differ without an occupied-object divergence; the "
                "delta is likely an implicit reservation, alignment gap, or "
                "unreferenced local home"
            ),
            "frame_delta": -8,
        },
        "verdict": {
            "status": "unresolved-source-attribution",
            "reason": (
                "heuristic cause extra-frame-reservation-or-alignment needs "
                "MWCC stack-home origin instrumentation or validating probe "
                "evidence before source-reachable vs ceiling can be decided"
            ),
            "confidence": "medium",
            "unresolved_dependency": "mwcc-stack-home-origin-tags",
        },
        "frame_transform_probe_plan": {
            "status": "ready",
            "objective": "reduce frame/local-area divergence toward expected",
            "cause_kind": "extra-frame-reservation-or-alignment",
            "operator_priority": [
                "frame-magic-scratch-relocation",
                "frame-split-fp-const-lifetime",
                "declaration-use-distance",
                "block-scope",
            ],
            "suggested_commands": [
                {
                    "kind": "suggest-frame",
                    "command": (
                        "melee-agent debug suggest frame -f fn_80000000 --json"
                    ),
                },
                {
                    "kind": "lifetime-layout",
                    "command": (
                        "melee-agent debug mutate lifetime-layout -f fn_80000000 "
                        "--operator frame-magic-scratch-relocation "
                        "--operator frame-split-fp-const-lifetime "
                        "--operator declaration-use-distance --operator block-scope "
                        "--compile-probes --json"
                    ),
                },
                {
                    "kind": "tier3-frame-search",
                    "command": (
                        "melee-agent debug mutate search -f fn_80000000 --budget 5"
                    ),
                },
            ],
            "validation": {
                "status": "required",
                "command": (
                    "melee-agent debug inspect frame-reservations -f fn_80000000 "
                    "--expected-asm <expected.s> --probe-results-json "
                    "<lifetime-layout.json> --json"
                ),
            },
        },
    }


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
    assert report["current"]["stack_home_assignments"] == [
        {
            "assignment_order": 0,
            "symbol": "lenCol+8",
            "offset": 0x30,
            "expected_offset": 0x2C,
            "offset_delta": 0x4,
            "size": 4,
            "kind": "local-or-temporary",
            "access_count": 1,
            "opcodes": ["stfs"],
            "first_access": {
                "opcode": "stfs",
                "operands": "f4,lenCol+8(r1)",
                "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                "block_idx": 0,
                "instr_idx": 1,
            },
        },
        {
            "assignment_order": 1,
            "symbol": "lenCol+12",
            "offset": 0x34,
            "expected_offset": 0x30,
            "offset_delta": 0x4,
            "size": 4,
            "kind": "local-or-temporary",
            "access_count": 1,
            "opcodes": ["stfs"],
            "first_access": {
                "opcode": "stfs",
                "operands": "f5,lenCol+12(r1)",
                "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                "block_idx": 0,
                "instr_idx": 2,
            },
        },
        {
            "assignment_order": 2,
            "symbol": "q3",
            "offset": 0x28,
            "expected_offset": 0x24,
            "offset_delta": 0x4,
            "size": 4,
            "kind": "local-or-temporary",
            "access_count": 1,
            "opcodes": ["stfs"],
            "first_access": {
                "opcode": "stfs",
                "operands": "f6,q3(r1)",
                "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                "block_idx": 0,
                "instr_idx": 3,
            },
        },
        {
            "assignment_order": 3,
            "symbol": "nxt",
            "offset": 0x40,
            "expected_offset": 0x3C,
            "offset_delta": 0x4,
            "size": 4,
            "kind": "local-or-temporary",
            "access_count": 1,
            "opcodes": ["stfs"],
            "first_access": {
                "opcode": "stfs",
                "operands": "f7,nxt(r1)",
                "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                "block_idx": 0,
                "instr_idx": 4,
            },
        },
    ]
    assert report["current"]["stack_home_order_summary"] == {
        "status": "computed",
        "has_order_mismatch": True,
        "assignment_count": 4,
        "max_abs_order_delta": 2,
        "assignments": [
            {
                "symbol": "lenCol+8",
                "assignment_order": 0,
                "offset_order": 1,
                "order_delta": 1,
                "offset": 0x30,
                "size": 4,
                "kind": "local-or-temporary",
            },
            {
                "symbol": "lenCol+12",
                "assignment_order": 1,
                "offset_order": 2,
                "order_delta": 1,
                "offset": 0x34,
                "size": 4,
                "kind": "local-or-temporary",
            },
            {
                "symbol": "q3",
                "assignment_order": 2,
                "offset_order": 0,
                "order_delta": -2,
                "offset": 0x28,
                "size": 4,
                "kind": "local-or-temporary",
            },
            {
                "symbol": "nxt",
                "assignment_order": 3,
                "offset_order": 3,
                "order_delta": 0,
                "offset": 0x40,
                "size": 4,
                "kind": "local-or-temporary",
            },
        ],
    }
    assert report["current"]["stack_home_reorder_guidance"] == {
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
                "target_symbols": ["q3", "lenCol+8", "lenCol+12", "nxt"],
            },
            {
                "kind": "lifetime-boundary",
                "description": (
                    "move declarations or use blocks to extend/shorten stack-home lifetimes"
                ),
                "target_symbols": ["q3", "lenCol+8", "lenCol+12", "nxt"],
            },
            {
                "kind": "decl-order-proxy",
                "description": (
                    "try declaration-order changes only as a proxy after first-use/lifetime probes"
                ),
                "target_symbols": ["q3", "lenCol+8", "lenCol+12", "nxt"],
            },
        ],
        "probe_plan": {
            "status": "ready",
            "objective": "move stack homes into expected target offset order",
            "target_symbols": ["q3", "lenCol+8", "lenCol+12", "nxt"],
            "current_offset_order": ["q3", "lenCol+8", "lenCol+12", "nxt"],
            "expected_offset_order": ["q3", "lenCol+8", "lenCol+12", "nxt"],
            "cycles": [],
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
                        "melee-agent debug mutate lifetime-layout -f MatToQuat "
                        "--operator declaration-use-distance --operator block-scope "
                        "--operator call-argument-tempization --compile-probes --json"
                    ),
                },
                {
                    "kind": "decl-orders",
                    "command": (
                        "melee-agent debug mutate decl-orders MatToQuat "
                        "--strategy all --json"
                    ),
                },
            ],
        },
        "next_steps": [
            "melee-agent debug mutate lifetime-layout -f MatToQuat --compile-probes",
            "melee-agent debug mutate decl-orders MatToQuat --strategy all --json",
        ],
    }
    assert report["extra_low_frame_reservation"] is None


def test_frame_reservation_infers_expected_symbolic_stack_home_order() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000002
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000002
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-80(r1)
            stfs    f4,a(r1)
            stfs    f5,b(r1)
            stfs    f6,c(r1)
            addi    r1,r1,80
    """)
    current_asm = textwrap.dedent("""\
        +000: 94 21 ff b0 \tstwu    r1,-80(r1)
        +004: d0 81 00 30 \tstfs    f4,48(r1)
        +008: d0 a1 00 34 \tstfs    f5,52(r1)
        +00c: d0 c1 00 28 \tstfs    f6,40(r1)
        +010: 38 21 00 50 \taddi    r1,r1,80
    """)
    expected_asm = textwrap.dedent("""\
        .fn fn_80000002, global
        /* 80000000 */    stwu r1, -80(r1)
        /* 80000004 */    stfs f4, 40(r1)
        /* 80000008 */    stfs f5, 52(r1)
        /* 8000000c */    stfs f6, 48(r1)
        /* 80000010 */    addi r1, r1, 80
        .endfn fn_80000002
    """)

    report = analyze_frame_reservations(
        pcdump,
        "fn_80000002",
        expected_asm_text=expected_asm,
        current_asm_text=current_asm,
    )

    assert report["current"]["expected_symbolic_home_map"] == [
        {"symbol": "a", "offset": 0x28},
        {"symbol": "b", "offset": 0x34},
        {"symbol": "c", "offset": 0x30},
    ]
    assert report["current"]["stack_home_assignments"] == [
        {
            "assignment_order": 0,
            "symbol": "a",
            "offset": 0x30,
            "expected_offset": 0x28,
            "offset_delta": 0x8,
            "size": 4,
            "kind": "local-or-temporary",
            "access_count": 1,
            "opcodes": ["stfs"],
            "first_access": {
                "opcode": "stfs",
                "operands": "f4,a(r1)",
                "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                "block_idx": 0,
                "instr_idx": 1,
            },
        },
        {
            "assignment_order": 1,
            "symbol": "b",
            "offset": 0x34,
            "expected_offset": 0x34,
            "offset_delta": 0,
            "size": 4,
            "kind": "local-or-temporary",
            "access_count": 1,
            "opcodes": ["stfs"],
            "first_access": {
                "opcode": "stfs",
                "operands": "f5,b(r1)",
                "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                "block_idx": 0,
                "instr_idx": 2,
            },
        },
        {
            "assignment_order": 2,
            "symbol": "c",
            "offset": 0x28,
            "expected_offset": 0x30,
            "offset_delta": -0x8,
            "size": 4,
            "kind": "local-or-temporary",
            "access_count": 1,
            "opcodes": ["stfs"],
            "first_access": {
                "opcode": "stfs",
                "operands": "f6,c(r1)",
                "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                "block_idx": 0,
                "instr_idx": 3,
            },
        },
    ]
    assert report["current"]["stack_home_expected_order_summary"] == {
        "status": "computed",
        "has_expected_offset_mismatch": True,
        "has_expected_order_mismatch": True,
        "assignment_count": 3,
        "max_abs_expected_order_delta": 1,
        "max_abs_offset_delta": 8,
        "assignments": [
            {
                "symbol": "a",
                "assignment_order": 0,
                "current_offset_order": 1,
                "expected_offset_order": 0,
                "expected_order_delta": 0,
                "offset": 0x30,
                "expected_offset": 0x28,
                "offset_delta": 0x8,
                "size": 4,
                "kind": "local-or-temporary",
            },
            {
                "symbol": "b",
                "assignment_order": 1,
                "current_offset_order": 2,
                "expected_offset_order": 2,
                "expected_order_delta": 1,
                "offset": 0x34,
                "expected_offset": 0x34,
                "offset_delta": 0,
                "size": 4,
                "kind": "local-or-temporary",
            },
            {
                "symbol": "c",
                "assignment_order": 2,
                "current_offset_order": 0,
                "expected_offset_order": 1,
                "expected_order_delta": -1,
                "offset": 0x28,
                "expected_offset": 0x30,
                "offset_delta": -0x8,
                "size": 4,
                "kind": "local-or-temporary",
            },
        ],
    }
    assert report["current"]["stack_home_target_permutation"] == {
        "status": "computed",
        "needs_permutation": True,
        "symbol_count": 3,
        "misplaced_count": 2,
        "current_offset_order": ["c", "a", "b"],
        "expected_offset_order": ["a", "c", "b"],
        "expected_to_current_positions": [1, 0, 2],
        "moves": [
            {
                "symbol": "a",
                "current_position": 1,
                "expected_position": 0,
                "position_delta": -1,
                "current_offset": 0x30,
                "expected_offset": 0x28,
                "offset_delta": 0x8,
            },
            {
                "symbol": "c",
                "current_position": 0,
                "expected_position": 1,
                "position_delta": 1,
                "current_offset": 0x28,
                "expected_offset": 0x30,
                "offset_delta": -0x8,
            },
            {
                "symbol": "b",
                "current_position": 2,
                "expected_position": 2,
                "position_delta": 0,
                "current_offset": 0x34,
                "expected_offset": 0x34,
                "offset_delta": 0,
            },
        ],
        "cycles": [
            {
                "symbols": ["c", "a"],
                "current_positions": [0, 1],
                "expected_positions": [1, 0],
            },
        ],
    }
    divergence = report["frame_first_divergence"]
    assert divergence["source_attribution"]["primary_source_object"] == {
        "symbol": "c",
        "identity_kind": "symbolic-stack-home",
        "side": "both",
        "current_offset": 0x28,
        "expected_offset": 0x30,
        "offset_delta": -0x8,
        "size": 4,
        "kind": "local-or-temporary",
        "opcodes": ["stfs"],
        "access_count": 1,
        "first_access": {
            "opcode": "stfs",
            "operands": "f6,c(r1)",
            "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
            "block_idx": 0,
            "instr_idx": 3,
        },
    }
    assert divergence["source_attribution"]["confidence"] == "medium"
    assert divergence["cause_hypothesis"]["source_object_symbol"] == "c"
    guidance = report["current"]["stack_home_reorder_guidance"]
    assert guidance["status"] == "source-reorder-probe-needed"
    assert guidance["verdict"] == "unknown-unvalidated"
    assert "target asm" in guidance["reason"]
    assert guidance["candidate_levers"][0]["target_symbols"] == ["c", "a"]
    assert guidance["probe_plan"] == {
        "status": "ready",
        "objective": "move stack homes into expected target offset order",
        "target_symbols": ["c", "a"],
        "current_offset_order": ["c", "a", "b"],
        "expected_offset_order": ["a", "c", "b"],
        "cycles": [
            {
                "symbols": ["c", "a"],
                "current_positions": [0, 1],
                "expected_positions": [1, 0],
            },
        ],
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
                    "melee-agent debug mutate lifetime-layout -f fn_80000002 "
                    "--operator declaration-use-distance --operator block-scope "
                    "--operator call-argument-tempization --compile-probes --json"
                ),
            },
            {
                "kind": "decl-orders",
                "command": (
                    "melee-agent debug mutate decl-orders fn_80000002 "
                    "--strategy all --json"
                ),
            },
        ],
    }


def test_stack_home_probe_evaluation_classifies_reachable_and_ceiling_candidates() -> None:
    report = {
        "current": {
            "stack_home_target_permutation": {
                "status": "computed",
                "moves": [
                    {
                        "symbol": "a",
                        "current_offset": 0x30,
                        "expected_offset": 0x28,
                        "offset_delta": 0x8,
                    },
                    {
                        "symbol": "c",
                        "current_offset": 0x28,
                        "expected_offset": 0x30,
                        "offset_delta": -0x8,
                    },
                ],
            }
        }
    }
    fixed = {
        "label": "swap-cycle",
        "operator": "declaration-use-distance",
        "status": "ok",
        "match_percent": 99.91,
        "stack_slot_localizer": {"mismatch_count": 0, "mismatches": []},
    }
    unchanged = {
        "label": "decl-order",
        "operator": "decl-orders",
        "status": "ok",
        "match_percent": 99.8,
        "stack_slot_localizer": {
            "mismatch_count": 2,
            "mismatches": [
                {
                    "opcode": "stfs",
                    "current_offset": 0x30,
                    "expected_offset": 0x28,
                },
                {
                    "opcode": "stfs",
                    "current_offset": 0x28,
                    "expected_offset": 0x30,
                },
            ],
        },
    }

    evaluation = evaluate_stack_home_probe_results(report, [unchanged, fixed])

    assert evaluation["status"] == "evaluated"
    assert evaluation["verdict"] == "source-reachable-reorder"
    assert evaluation["best_variant"]["label"] == "swap-cycle"
    assert evaluation["best_variant"]["target_fixed"] is True
    assert evaluation["best_variant"]["fixed_count"] == 2
    assert evaluation["stop_condition"] == {
        "status": "satisfied",
        "kind": "validated-source-reorder",
        "reason": (
            "probe swap-cycle moves all target stack homes to their expected offsets"
        ),
        "variant_label": "swap-cycle",
        "fixed_count": 2,
        "target_count": 2,
    }
    assert evaluation["variants"][1]["label"] == "decl-order"
    assert evaluation["variants"][1]["fixed_count"] == 0

    ceiling = evaluate_stack_home_probe_results(report, [unchanged])

    assert ceiling["verdict"] == "internal-tiebreak-ceiling-candidate"
    assert ceiling["best_variant"]["fixed_count"] == 0
    assert ceiling["stop_condition"] == {
        "status": "candidate",
        "kind": "internal-tiebreak-ceiling",
        "reason": (
            "1 measured probe(s) left all 2 target stack-home mismatches in place"
        ),
        "measured_probe_count": 1,
        "target_count": 2,
    }


def test_frame_transform_probe_evaluation_ranks_frame_delta_reducers() -> None:
    report = {
        "current": {"frame_size": 80},
        "expected": {"frame_size": 72},
        "frame_delta": -8,
    }
    neutral = {
        "label": "block-scope",
        "operator": "block-scope",
        "status": "ok",
        "match_percent": 98.5,
        "objective": {
            "frame_after": 80,
            "frame_delta": 0,
        },
    }
    fixed = {
        "label": "scratch-relocation",
        "operator": "frame-magic-scratch-relocation",
        "status": "ok",
        "match_percent": 99.1,
        "objective": {
            "frame_after": 72,
            "frame_delta": -8,
        },
    }

    evaluation = evaluate_frame_transform_probe_results(report, [neutral, fixed])

    assert evaluation["status"] == "evaluated"
    assert evaluation["verdict"] == "source-reachable-frame-transform"
    assert evaluation["stop_condition"] == {
        "status": "satisfied",
        "kind": "validated-frame-transform",
        "reason": (
            "probe scratch-relocation moves frame size to expected 72 bytes"
        ),
        "variant_label": "scratch-relocation",
        "remaining_frame_delta": 0,
    }
    assert evaluation["best_variant"]["label"] == "scratch-relocation"
    assert evaluation["best_variant"]["candidate_frame_size"] == 72
    assert evaluation["best_variant"]["remaining_frame_delta"] == 0
    assert evaluation["best_variant"]["frame_delta_improvement"] == 8
    assert evaluation["variants"][1]["label"] == "block-scope"
    assert evaluation["variants"][1]["frame_delta_improvement"] == 0


def test_frame_transform_probe_evaluation_flags_bounded_ceiling_candidate() -> None:
    report = {
        "current": {"frame_size": 80},
        "expected": {"frame_size": 72},
        "frame_delta": -8,
    }
    unchanged = {
        "label": "block-scope",
        "operator": "block-scope",
        "status": "ok",
        "objective": {
            "frame_after": 80,
        },
    }

    evaluation = evaluate_frame_transform_probe_results(report, [unchanged])

    assert evaluation["verdict"] == "frame-transform-ceiling-candidate"
    assert evaluation["stop_condition"] == {
        "status": "candidate",
        "kind": "bounded-frame-transform-ceiling",
        "reason": (
            "1 ok frame transform probe(s) left the 8-byte frame delta unchanged"
        ),
        "measured_probe_count": 1,
        "baseline_remaining_frame_delta": -8,
    }


def test_frame_reservation_stack_home_assignment_merges_repeated_accesses() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000001
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000001
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-80(r1)
            stfs    f0,tmp(r1)
            lfs     f1,tmp(r1)
            stw     r3,cursor(r1)
            addi    r1,r1,80
    """)
    current_asm = textwrap.dedent("""\
        +000: 94 21 ff b0 \tstwu    r1,-80(r1)
        +004: d0 01 00 30 \tstfs    f0,48(r1)
        +008: c0 21 00 30 \tlfs     f1,48(r1)
        +00c: 90 61 00 34 \tstw     r3,52(r1)
        +010: 38 21 00 50 \taddi    r1,r1,80
    """)

    report = analyze_frame_reservations(
        pcdump,
        "fn_80000001",
        current_asm_text=current_asm,
    )

    assert report["current"]["stack_home_assignment_status"] == "resolved-symbolic-homes"
    assert report["current"]["stack_home_assignments"] == [
        {
            "assignment_order": 0,
            "symbol": "tmp",
            "offset": 0x30,
            "size": 4,
            "kind": "local-or-temporary",
            "access_count": 2,
            "opcodes": ["lfs", "stfs"],
            "first_access": {
                "opcode": "stfs",
                "operands": "f0,tmp(r1)",
                "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                "block_idx": 0,
                "instr_idx": 1,
            },
        },
        {
            "assignment_order": 1,
            "symbol": "cursor",
            "offset": 0x34,
            "size": 4,
            "kind": "local-or-temporary",
            "access_count": 1,
            "opcodes": ["stw"],
            "first_access": {
                "opcode": "stw",
                "operands": "r3,cursor(r1)",
                "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                "block_idx": 0,
                "instr_idx": 3,
            },
        },
    ]
    assert report["current"]["stack_home_order_summary"] == {
        "status": "computed",
        "has_order_mismatch": False,
        "assignment_count": 2,
        "max_abs_order_delta": 0,
        "assignments": [
            {
                "symbol": "tmp",
                "assignment_order": 0,
                "offset_order": 0,
                "order_delta": 0,
                "offset": 0x30,
                "size": 4,
                "kind": "local-or-temporary",
            },
            {
                "symbol": "cursor",
                "assignment_order": 1,
                "offset_order": 1,
                "order_delta": 0,
                "offset": 0x34,
                "size": 4,
                "kind": "local-or-temporary",
            },
        ],
    }
    assert report["current"]["stack_home_reorder_guidance"] == {
        "status": "not-needed",
        "verdict": "assignment-order-matches-offset-order",
        "reason": "resolved stack-home assignment order already matches final offset order",
        "candidate_levers": [],
        "next_steps": [],
    }
