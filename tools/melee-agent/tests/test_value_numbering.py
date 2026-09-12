from __future__ import annotations

import textwrap

from src.mwcc_debug.value_numbering import (
    detect_divide_rematerialization_ceiling,
)


EXPECTED_REMATERIALIZED_DIVIDE = textwrap.dedent("""\
    .fn fn_test, global
    /* 80000000 00000000  3C 60 51 EC */ lis r3, 0x51ec
    /* 80000004 00000004  38 03 85 1F */ subi r0, r3, 0x7ae1
    /* 80000008 00000008  7C 80 F8 96 */ mulhw r4, r0, r31
    /* 8000000C 0000000C  7C 80 2E 70 */ srawi r0, r4, 5
    /* 80000010 00000010  54 03 0F FE */ srwi r3, r0, 31
    /* 80000014 00000014  7C 00 1A 15 */ add. r0, r0, r3
    /* 80000018 00000018  41 82 00 24 */ beq .L_else
    /* 8000001C 0000001C  7C 80 2E 70 */ srawi r0, r4, 5
    /* 80000020 00000020  54 04 0F FE */ srwi r4, r0, 31
    /* 80000024 00000024  7C 00 22 14 */ add r0, r0, r4
    /* 80000028 00000028  6C 00 80 00 */ xoris r0, r0, 0x8000
    /* 8000002C 0000002C  48 00 00 08 */ b .L_done
    .L_else:
    /* 80000030 00000030  38 00 00 00 */ li r0, 0
    .L_done:
    /* 80000034 00000034  4E 80 00 20 */ blr
    .endfn fn_test
""")


CURRENT_CSE_PCDUMP = textwrap.dedent("""\
    Starting function fn_test
    BEFORE REGISTER COLORING
    fn_test
    B0: Succ={B1 B2} Pred={} Labels={}
        lis r32, 0x51ec
        subi r33, r32, 0x7ae1
        mulhw r60, r33, r31
        srawi r64, r60, 5
        srwi r62, r64, 31
        add. r35, r64, r62
        beq B2
    B1: Succ={B3} Pred={B0} Labels={}
        xoris r65, r35, 0x8000
        b B3
    B2: Succ={B3} Pred={B0} Labels={}
        li r65, 0
    B3: Succ={} Pred={B1 B2} Labels={}
        blr
""")


CURRENT_CSE_PCDUMP_PLAIN_ADD_BT = textwrap.dedent("""\
    Starting function fn_test
    BEFORE REGISTER COLORING
    fn_test
    B0: Succ={B1 B2} Pred={} Labels={}
        lis r32, 0x51ec
        subi r33, r32, 0x7ae1
        mulhw r60, r33, r31
        srawi r64, r60, 5
        srwi r62, r64, 31
        add r35, r64, r62
        bt eq B2
    B1: Succ={B3} Pred={B0} Labels={}
        xoris r65, r35, 0x8000
        b B3
    B2: Succ={B3} Pred={B0} Labels={}
        li r65, 0
    B3: Succ={} Pred={B1 B2} Labels={}
        blr
""")


CURRENT_REMATERIALIZED_PCDUMP = textwrap.dedent("""\
    Starting function fn_test
    BEFORE REGISTER COLORING
    fn_test
    B0: Succ={B1 B2} Pred={} Labels={}
        lis r32, 0x51ec
        subi r33, r32, 0x7ae1
        mulhw r60, r33, r31
        srawi r64, r60, 5
        srwi r62, r64, 31
        add. r35, r64, r62
        beq B2
    B1: Succ={B3} Pred={B0} Labels={}
        srawi r70, r60, 5
        srwi r71, r70, 31
        add r72, r70, r71
        xoris r65, r72, 0x8000
        b B3
    B2: Succ={B3} Pred={B0} Labels={}
        li r65, 0
    B3: Succ={} Pred={B1 B2} Labels={}
        blr
""")


CURRENT_XORIS_IN_BRANCH_TARGET_PCDUMP = textwrap.dedent("""\
    Starting function fn_test
    BEFORE REGISTER COLORING
    fn_test
    B0: Succ={B1 B2} Pred={} Labels={}
        lis r32, 0x51ec
        subi r33, r32, 0x7ae1
        mulhw r60, r33, r31
        srawi r64, r60, 5
        srwi r62, r64, 31
        add. r35, r64, r62
        beq B2
    B1: Succ={B3} Pred={B0} Labels={}
        li r65, 0
        b B3
    B2: Succ={B3} Pred={B0} Labels={}
        xoris r65, r35, 0x8000
    B3: Succ={} Pred={B1 B2} Labels={}
        blr
""")


CURRENT_DIFFERENT_QUOTIENT_XORIS_PCDUMP = textwrap.dedent("""\
    Starting function fn_test
    BEFORE REGISTER COLORING
    fn_test
    B0: Succ={B1 B2} Pred={} Labels={}
        lis r32, 0x51ec
        subi r33, r32, 0x7ae1
        mulhw r60, r33, r31
        srawi r64, r60, 5
        srwi r62, r64, 31
        add. r35, r64, r62
        beq B2
    B1: Succ={B3} Pred={B0} Labels={}
        xoris r65, r99, 0x8000
        b B3
    B2: Succ={B3} Pred={B0} Labels={}
        li r65, 0
    B3: Succ={} Pred={B1 B2} Labels={}
        blr
""")


EXPECTED_THEN_SRAWI_FROM_DIFFERENT_MUL = textwrap.dedent("""\
    .fn fn_test, global
    /* 80000000 00000000  3C 60 51 EC */ lis r3, 0x51ec
    /* 80000004 00000004  38 03 85 1F */ subi r0, r3, 0x7ae1
    /* 80000008 00000008  7C 80 F8 96 */ mulhw r4, r0, r31
    /* 8000000C 0000000C  7C 80 2E 70 */ srawi r0, r4, 5
    /* 80000010 00000010  54 03 0F FE */ srwi r3, r0, 31
    /* 80000014 00000014  7C 00 1A 15 */ add. r0, r0, r3
    /* 80000018 00000018  41 82 00 28 */ beq .L_else
    /* 8000001C 0000001C  7D 01 F8 96 */ mulhw r8, r1, r31
    /* 80000020 00000020  7D 00 2E 70 */ srawi r0, r8, 5
    /* 80000024 00000024  54 04 0F FE */ srwi r4, r0, 31
    /* 80000028 00000028  7C 00 22 14 */ add r0, r0, r4
    /* 8000002C 0000002C  6C 00 80 00 */ xoris r0, r0, 0x8000
    .L_else:
    /* 80000030 00000030  4E 80 00 20 */ blr
    .endfn fn_test
""")


EXPECTED_UNSIGNED_MULHWU_DIVIDE = EXPECTED_REMATERIALIZED_DIVIDE.replace(
    "mulhw r4, r0, r31",
    "mulhwu r4, r0, r31",
)

EXPECTED_SINGLE_COMPUTE_DIVIDE = textwrap.dedent("""\
    .fn fn_test, global
    /* 80000000 00000000  3C 60 51 EC */ lis r3, 0x51ec
    /* 80000004 00000004  38 03 85 1F */ subi r0, r3, 0x7ae1
    /* 80000008 00000008  7C 80 F8 96 */ mulhw r4, r0, r31
    /* 8000000C 0000000C  7C 80 2E 70 */ srawi r0, r4, 5
    /* 80000010 00000010  54 03 0F FE */ srwi r3, r0, 31
    /* 80000014 00000014  7C 00 1A 15 */ add. r0, r0, r3
    /* 80000018 00000018  41 82 00 18 */ beq .L_else
    /* 8000001C 0000001C  6C 00 80 00 */ xoris r0, r0, 0x8000
    /* 80000020 00000020  48 00 00 08 */ b .L_done
    .L_else:
    /* 80000024 00000024  38 00 00 00 */ li r0, 0
    .L_done:
    /* 80000028 00000028  4E 80 00 20 */ blr
    .endfn fn_test
""")

EXPECTED_BRANCH_BODY_ADD_FEEDS_XORIS = EXPECTED_REMATERIALIZED_DIVIDE.replace(
    "add r0, r0, r4\n"
    "    /* 80000028 00000028  6C 00 80 00 */ xoris r0, r0, 0x8000",
    "add r8, r0, r4\n"
    "    /* 80000028 00000028  6C 00 80 00 */ xoris r0, r8, 0x8000",
)

EXPECTED_UNCONDITIONAL_BRANCH_SHAPE = (
    EXPECTED_REMATERIALIZED_DIVIDE
    .replace("add. r0, r0, r3", "add r0, r0, r3")
    .replace("beq .L_else", "b .L_else")
)

EXPECTED_BAD_XORIS_IMMEDIATE = EXPECTED_REMATERIALIZED_DIVIDE.replace(
    "xoris r0, r0, 0x8000",
    "xoris r0, r0, 0x4000",
)


CHECKDIFF_EXPECTED_REMATERIALIZED = [
    "<fn_test>:",
    "+000: lis r3, 0x51ec",
    "+004: subi r0, r3, 0x7ae1",
    "+008: mulhw r4, r0, r31",
    "+00c: srawi r0, r4, 5",
    "+010: srwi r3, r0, 31",
    "+014: add. r0, r0, r3",
    "+018: beq .L_else",
    "+01c: srawi r0, r4, 5",
    "+020: srwi r4, r0, 31",
    "+024: add r0, r0, r4",
    "+028: xoris r0, r0, 0x8000",
]


CHECKDIFF_CURRENT_CSE = [
    "<fn_test>:",
    "+000: lis r3, 0x51ec",
    "+004: subi r0, r3, 0x7ae1",
    "+008: mulhw r4, r0, r31",
    "+00c: srawi r0, r4, 5",
    "+010: srwi r3, r0, 31",
    "+014: add. r0, r0, r3",
    "+018: beq .L_else",
    "+01c: xoris r0, r0, 0x8000",
]


CHECKDIFF_EXPECTED_WITH_BYTES = [
    "<fn_test>:",
    "+000: 3c 60 51 ec \tlis r3, 0x51ec",
    "+004: 38 03 85 1f \tsubi r0, r3, 0x7ae1",
    "+008: 7c 80 f8 96 \tmulhw r4, r0, r31",
    "+00c: 7c 80 2e 70 \tsrawi r0, r4, 5",
    "+010: 54 03 0f fe \tsrwi r3, r0, 31",
    "+014: 7c 00 1a 15 \tadd. r0, r0, r3",
    "+018: 41 82 00 24 \tbeq .L_else",
    "+01c: 7c 80 2e 70 \tsrawi r0, r4, 5",
    "+020: 54 04 0f fe \tsrwi r4, r0, 31",
    "+024: 7c 00 22 14 \tadd r0, r0, r4",
    "+028: 6c 00 80 00 \txoris r0, r0, 0x8000",
]


CHECKDIFF_CURRENT_WITH_BYTES = [
    "<fn_test>:",
    "+000: 3c 60 51 ec \tlis r3, 0x51ec",
    "+004: 38 03 85 1f \tsubi r0, r3, 0x7ae1",
    "+008: 7c 80 f8 96 \tmulhw r4, r0, r31",
    "+00c: 7c 80 2e 70 \tsrawi r0, r4, 5",
    "+010: 54 03 0f fe \tsrwi r3, r0, 31",
    "+014: 7c 00 1a 15 \tadd. r0, r0, r3",
    "+018: 41 82 00 24 \tbeq .L_else",
    "+01c: 6c 00 80 00 \txoris r0, r0, 0x8000",
]


def test_detects_divide_rematerialization_ceiling_from_pcdump() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text=EXPECTED_REMATERIALIZED_DIVIDE,
        current_pcdump_text=CURRENT_CSE_PCDUMP,
    )

    assert finding is not None
    assert finding["status"] == "intrinsic-value-numbering-ceiling"
    assert finding["kind"] == "signed-magic-divide-rematerialization"
    assert finding["source_lever_status"] == "no-current-C-source-lever"
    assert finding["target"]["rematerialized_quotient"] is True
    assert finding["current"]["cse_quotient_reused"] is True
    assert finding["evidence"]["target_then_srawi_count"] == 1
    assert finding["evidence"]["current_then_srawi_count"] == 0


def test_detects_pcdump_plain_add_condition_followed_by_bt() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text=EXPECTED_REMATERIALIZED_DIVIDE,
        current_pcdump_text=CURRENT_CSE_PCDUMP_PLAIN_ADD_BT,
    )

    assert finding is not None
    assert finding["kind"] == "signed-magic-divide-rematerialization"


def test_detects_divide_rematerialization_when_branch_add_feeds_xoris() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text=EXPECTED_BRANCH_BODY_ADD_FEEDS_XORIS,
        current_pcdump_text=CURRENT_CSE_PCDUMP,
    )

    assert finding is not None
    assert finding["kind"] == "signed-magic-divide-rematerialization"


def test_abstains_when_current_already_rematerializes_divide() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text=EXPECTED_REMATERIALIZED_DIVIDE,
        current_pcdump_text=CURRENT_REMATERIALIZED_PCDUMP,
    )

    assert finding is None


def test_detects_divide_rematerialization_ceiling_from_checkdiff_lines() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text="\n".join(CHECKDIFF_EXPECTED_REMATERIALIZED),
        current_asm_lines=CHECKDIFF_CURRENT_CSE,
    )

    assert finding is not None
    assert finding["status"] == "intrinsic-value-numbering-ceiling"
    assert finding["evidence"]["target_then_srawi_count"] == 1
    assert finding["evidence"]["current_then_srawi_count"] == 0


def test_detects_divide_rematerialization_from_checkdiff_lines_with_bytes() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text="\n".join(CHECKDIFF_EXPECTED_WITH_BYTES),
        current_asm_lines=CHECKDIFF_CURRENT_WITH_BYTES,
    )

    assert finding is not None
    assert finding["kind"] == "signed-magic-divide-rematerialization"


def test_abstains_when_current_xoris_uses_different_quotient() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text=EXPECTED_REMATERIALIZED_DIVIDE,
        current_pcdump_text=CURRENT_DIFFERENT_QUOTIENT_XORIS_PCDUMP,
    )

    assert finding is None


def test_abstains_when_current_xoris_is_in_branch_target_successor() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text=EXPECTED_REMATERIALIZED_DIVIDE,
        current_pcdump_text=CURRENT_XORIS_IN_BRANCH_TARGET_PCDUMP,
    )

    assert finding is None


def test_abstains_when_expected_function_is_absent_from_full_asm() -> None:
    expected_full_asm = EXPECTED_REMATERIALIZED_DIVIDE.replace(
        ".fn fn_test, global",
        ".fn fn_other, global",
    ).replace(".endfn fn_test", ".endfn fn_other")

    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text=expected_full_asm,
        current_pcdump_text=CURRENT_CSE_PCDUMP,
    )

    assert finding is None


def test_abstains_when_target_also_single_computes_divide() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text=EXPECTED_SINGLE_COMPUTE_DIVIDE,
        current_pcdump_text=CURRENT_CSE_PCDUMP,
    )

    assert finding is None


def test_abstains_when_target_srawi_uses_different_mul_result() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text=EXPECTED_THEN_SRAWI_FROM_DIFFERENT_MUL,
        current_pcdump_text=CURRENT_CSE_PCDUMP,
    )

    assert finding is None


def test_abstains_when_condition_is_not_a_conditional_quotient_test() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text=EXPECTED_UNCONDITIONAL_BRANCH_SHAPE,
        current_pcdump_text=CURRENT_CSE_PCDUMP,
    )

    assert finding is None


def test_abstains_when_target_xoris_immediate_is_not_float_bias() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text=EXPECTED_BAD_XORIS_IMMEDIATE,
        current_pcdump_text=CURRENT_CSE_PCDUMP,
    )

    assert finding is None


def test_abstains_for_unsigned_magic_divide_shape() -> None:
    finding = detect_divide_rematerialization_ceiling(
        function="fn_test",
        expected_asm_text=EXPECTED_UNSIGNED_MULHWU_DIVIDE,
        current_pcdump_text=CURRENT_CSE_PCDUMP,
    )

    assert finding is None
