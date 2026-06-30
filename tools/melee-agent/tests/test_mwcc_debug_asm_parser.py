"""Tests for parsing build/GALE01/asm/*.s files."""

from __future__ import annotations

import textwrap

from src.mwcc_debug.asm_parser import (
    extract_function,
    find_first_def,
    parse_prologue_end,
)


SAMPLE_FN = textwrap.dedent("""\
    .include "macros.inc"
    .file "mnvibration.c"

    # 0x802474C4..0x802492CC | size: 0x1E08
    .text
    .balign 4

    # .text:0x4C | 0x80247510 | size: 0xB74
    .fn fn_80247510, global
    /* 80247510 002440F0  7C 08 02 A6 */\tmflr r0
    /* 80247514 002440F4  90 01 00 04 */\tstw r0, 0x4(r1)
    /* 80247518 002440F8  94 21 FE E8 */\tstwu r1, -0x118(r1)
    /* 8024751C 002440FC  DB E1 01 10 */\tstfd f31, 0x110(r1)
    /* 80247520 00244100  DB C1 01 08 */\tstfd f30, 0x108(r1)
    /* 80247524 00244104  BF 61 00 F4 */\tstmw r27, 0xf4(r1)
    /* 80247528 00244108  A0 6D B5 28 */\tlhz r3, mn_804D6BC8@sda21(r0)
    /* 8024752C 0024410C  80 8D B5 88 */\tlwz r4, mnVibration_804D6C28@sda21(r0)
    /* 80247530 00244110  28 03 00 00 */\tcmplwi r3, 0x0
    /* 80247534 00244114  83 C4 00 2C */\tlwz r30, 0x2c(r4)
    /* 80247538 00244118  41 82 00 20 */\tbeq .L_80247558
    /* 8024753C 0024411C  38 03 FF FF */\tsubi r0, r3, 0x1
    /* 80247540 00244120  3B C0 00 00 */\tli r30, 0x0
    /* 80247544 00244124  3B E0 00 00 */\tli r31, 0x0
    .endfn fn_80247510
""")


def test_extract_function_returns_body_instructions() -> None:
    fn = extract_function(SAMPLE_FN, "fn_80247510")
    assert fn is not None
    assert fn.name == "fn_80247510"
    # Body includes prologue lines (we don't drop them in extraction; that's
    # parse_prologue_end's job).
    assert len(fn.instructions) >= 13
    first = fn.instructions[0]
    assert first.opcode == "mflr"
    assert first.regs == [("r", 0)]


def test_extract_function_missing_returns_none() -> None:
    assert extract_function(SAMPLE_FN, "fn_nonexistent") is None


def test_parse_prologue_end_skips_save_block() -> None:
    fn = extract_function(SAMPLE_FN, "fn_80247510")
    assert fn is not None
    end = parse_prologue_end(fn.instructions)
    # Prologue covers mflr, stw r0, stwu, stfd, stfd, stmw -> 6 instructions
    assert end == 6
    assert fn.instructions[end].opcode == "lhz"


def test_find_first_def_r31_dest_register() -> None:
    fn = extract_function(SAMPLE_FN, "fn_80247510")
    assert fn is not None
    end = parse_prologue_end(fn.instructions)
    body = fn.instructions[end:]
    result = find_first_def(body, target_reg=31)
    assert result is not None
    pos, ist = result
    # First post-prologue def of r31 is `li r31, 0x0` (the last instr in
    # the sample).
    assert ist.opcode == "li"
    assert ist.regs[0] == ("r", 31)


def test_find_first_def_r30_dest_register() -> None:
    fn = extract_function(SAMPLE_FN, "fn_80247510")
    assert fn is not None
    end = parse_prologue_end(fn.instructions)
    body = fn.instructions[end:]
    result = find_first_def(body, target_reg=30)
    assert result is not None
    pos, ist = result
    # First post-prologue def of r30 is `lwz r30, 0x2c(r4)`.
    assert ist.opcode == "lwz"
    assert ist.regs[0] == ("r", 30)


def test_find_first_def_returns_none_when_unused() -> None:
    # r29 doesn't appear as a destination in the sample body.
    fn = extract_function(SAMPLE_FN, "fn_80247510")
    assert fn is not None
    end = parse_prologue_end(fn.instructions)
    body = fn.instructions[end:]
    result = find_first_def(body, target_reg=29)
    assert result is None
