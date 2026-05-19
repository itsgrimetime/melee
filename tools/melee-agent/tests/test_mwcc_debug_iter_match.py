"""Tests for matching expected r28..r31 defs to BEFORE COLORING virtuals."""

from __future__ import annotations

from src.mwcc_debug.asm_parser import AsmInstruction
from src.mwcc_debug.iter_match import (
    instr_signature,
    match_virtual_for_expected_def,
)
from src.mwcc_debug.parser import (
    Block,
    Function,
    Instruction,
    Pass,
)


def _make_ist(
    opcode: str, operands: str, regs: list[tuple[str, int]]
) -> Instruction:
    return Instruction(
        opcode=opcode, operands=operands, annotations=[], regs=regs
    )


def test_instr_signature_replaces_registers() -> None:
    # Hex literals normalize to decimal; whitespace is stripped so pcdump's
    # `r124,mn_...(r0)` form matches expected's `r4, mn_...(r0)` form.
    assert instr_signature("lwz", "r30, 0x2c(r4)") == ("lwz", "R,44(R)")
    assert instr_signature("li", "r31, 0x0") == ("li", "R,0")
    assert instr_signature("addi", "r30, r4, 0x10") == ("addi", "R,R,16")


def test_instr_signature_keeps_symbol_names_strips_reloc_suffix() -> None:
    sig = instr_signature("lwz", "r4, mnVibration_804D6C28@sda21(r0)")
    # Symbol names are preserved; reloc suffix is stripped so pcdump's
    # `mnVibration_804D6C28(r0)` matches expected's `@sda21` form.
    assert sig == ("lwz", "R,mnVibration_804D6C28(R)")


def test_instr_signature_normalizes_hex_and_decimal() -> None:
    # Expected uses 0x2c, pcdump uses 44. Both normalize to the same.
    assert instr_signature("lwz", "r30, 0x2c(r4)") == \
           instr_signature("lwz", "r47,44(r123)")
    # 0x0 == 0
    assert instr_signature("li", "r30, 0x0") == \
           instr_signature("li", "r127,0")


def test_instr_signature_strips_annotations() -> None:
    # pcdump adds "; fIsPtrOp" annotations that aren't in expected
    assert instr_signature("lwz", "r4, 44(r123); fIsPtrOp") == \
           instr_signature("lwz", "r4,44(r123)")


def test_instr_signature_strips_cr0_prefix() -> None:
    # Expected: "cmplwi r3, 0x0"; pcdump: "cmpli cr0, r3, 0"
    sig_pcdump = instr_signature("cmpli", "cr0, r3, 0")
    # After stripping cr0 prefix and whitespace, signature is just "R,0"
    assert sig_pcdump == ("cmpli", "R,0")


def test_match_virtual_for_expected_def_simple() -> None:
    """Expected has `lwz r30, 0x2c(r4)` at position 0 of body. Current
    BEFORE COLORING has `lwz r33, 0x2c(r36)` at position 0. The matched
    virtual should be 33, ig_idx 33.
    """
    expected_ist = AsmInstruction(
        opcode="lwz", operands="r30, 0x2c(r4)", regs=[("r", 30), ("r", 4)]
    )
    pre = Pass(name="AFTER PEEPHOLE FORWARD")
    block = Block(index=0, succ=[], pred=[], labels=["L0"])
    block.instructions = [
        _make_ist("lwz", "r33, 0x2c(r36)", [("r", 33), ("r", 36)]),
        _make_ist("li", "r34, 0x0", [("r", 34)]),
    ]
    pre.blocks.append(block)
    result = match_virtual_for_expected_def(
        expected_ist=expected_ist,
        expected_position=0,
        pre_pass=pre,
    )
    assert result is not None
    assert result.virtual == 33
    assert result.ig_idx == 33
    assert result.instruction_index == 0
    assert result.confidence == "exact"


def test_match_virtual_prefers_closest_position() -> None:
    """When two BEFORE COLORING instructions share signature, pick the
    one closest to the expected position.
    """
    expected_ist = AsmInstruction(
        opcode="lwz", operands="r30, 0x2c(r4)", regs=[("r", 30), ("r", 4)]
    )
    pre = Pass(name="AFTER PEEPHOLE FORWARD")
    block = Block(index=0, succ=[], pred=[], labels=["L0"])
    block.instructions = [
        _make_ist("li", "r33, 0x0", [("r", 33)]),
        _make_ist("li", "r34, 0x0", [("r", 34)]),
        _make_ist("li", "r35, 0x0", [("r", 35)]),
        _make_ist("lwz", "r36, 0x2c(r4)", [("r", 36), ("r", 4)]),  # pos 3
        _make_ist("li", "r37, 0x0", [("r", 37)]),
        _make_ist("lwz", "r38, 0x2c(r4)", [("r", 38), ("r", 4)]),  # pos 5
    ]
    pre.blocks.append(block)
    result = match_virtual_for_expected_def(
        expected_ist=expected_ist,
        expected_position=5,  # exact match at pos 5
        pre_pass=pre,
    )
    assert result is not None
    assert result.virtual == 38
    assert result.ig_idx == 38
    assert result.confidence == "ambiguous"


def test_match_virtual_returns_none_when_no_signature_match() -> None:
    expected_ist = AsmInstruction(
        opcode="lwz", operands="r30, 0x2c(r4)", regs=[("r", 30), ("r", 4)]
    )
    pre = Pass(name="AFTER PEEPHOLE FORWARD")
    block = Block(index=0, succ=[], pred=[], labels=["L0"])
    block.instructions = [
        _make_ist("li", "r33, 0x0", [("r", 33)]),
    ]
    pre.blocks.append(block)
    result = match_virtual_for_expected_def(
        expected_ist=expected_ist,
        expected_position=0,
        pre_pass=pre,
    )
    assert result is None


def test_match_virtual_skips_non_virtual_destinations() -> None:
    """When the signature match lands on an instruction with a physical
    register destination (e.g. argument-passing `li r3, 0`), return None
    rather than reporting a meaningless physical match."""
    expected_ist = AsmInstruction(
        opcode="li", operands="r30, 0x0", regs=[("r", 30)]
    )
    pre = Pass(name="AFTER PEEPHOLE FORWARD")
    block = Block(index=0, succ=[], pred=[], labels=["L0"])
    block.instructions = [
        _make_ist("li", "r3, 0x0", [("r", 3)]),  # physical, not virtual
    ]
    pre.blocks.append(block)
    result = match_virtual_for_expected_def(
        expected_ist=expected_ist,
        expected_position=0,
        pre_pass=pre,
    )
    assert result is None


def test_integration_fn_80247510() -> None:
    """End-to-end: parse expected fn_80247510.s + pcdump fixture, verify
    we recommend r28..r31 → ig_idx mappings that align with the function's
    structure (first def of r31 lands at body position 17 in expected).

    This is the matching agent's actual stuck case from
    docs/mwcc-debug-force-iter-feedback.md.
    """
    import pathlib

    from src.mwcc_debug.asm_parser import (
        extract_function as asm_extract_function,
        find_first_def as asm_find_first_def,
        parse_prologue_end as asm_parse_prologue_end,
    )
    from src.mwcc_debug.parser import parse_pcdump

    fixtures = pathlib.Path(__file__).parent / "fixtures" / "mwcc_debug"
    asm_text = (fixtures / "fn_80247510.s").read_text()
    pcdump_text = (fixtures / "fn_80247510_pcdump.txt").read_text()

    asm_fn = asm_extract_function(asm_text, "fn_80247510")
    assert asm_fn is not None
    prologue_end = asm_parse_prologue_end(asm_fn.instructions)
    body = asm_fn.instructions[prologue_end:]

    # r31's first def is `li r31, 0x0` at body position 17 (verified
    # against build/GALE01/asm/melee/mn/mnvibration.s).
    expected_r31 = asm_find_first_def(body, target_reg=31)
    assert expected_r31 is not None
    pos31, ist31 = expected_r31
    assert pos31 == 17
    assert ist31.opcode == "li"

    # r30's first def is `lwz r30, 0x2c(r4)` at body position 3.
    expected_r30 = asm_find_first_def(body, target_reg=30)
    assert expected_r30 is not None
    pos30, ist30 = expected_r30
    assert pos30 == 3
    assert ist30.opcode == "lwz"

    # Pre-coloring pass parses cleanly
    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == "fn_80247510"), None)
    assert fn is not None
    pre_pass = fn.last_precolor_pass()
    assert pre_pass is not None

    # Each register's match yields a virtual >= 32
    for reg in (31, 30, 29, 28):
        expected_def = asm_find_first_def(body, target_reg=reg)
        if expected_def is None:
            continue
        pos, ist = expected_def
        match = match_virtual_for_expected_def(
            expected_ist=ist,
            expected_position=pos,
            pre_pass=pre_pass,
        )
        if match is not None:
            assert match.virtual >= 32, (
                f"r{reg} matched physical r{match.virtual}, expected virtual"
            )
            assert match.ig_idx == match.virtual
