"""Tests for the coalesce-suggestion IR facts layer."""

from __future__ import annotations

import textwrap

from src.mwcc_debug.coalesce_ir_facts import IrFacts, VirtualFacts, collect
from src.mwcc_debug.parser import Block, Function, Instruction, Pass


def test_virtual_facts_dataclass_shape() -> None:
    """VirtualFacts captures the fields the pattern checkers need."""
    vf = VirtualFacts(
        virtual=53,
        first_def=None,
        use_sites=[],
        use_sites_truncated=False,
        is_param=False,
        is_phys=False,
    )
    assert vf.virtual == 53
    assert vf.use_sites == []
    assert vf.use_sites_truncated is False


def test_ir_facts_dataclass_shape() -> None:
    """IrFacts has the expected top-level fields including cg_section."""
    facts = IrFacts(
        function_name="test_fn",
        pre_pass=None,  # type: ignore[arg-type]
        by_virtual={},
        bindings=[],
        basis=None,
        cg_section=None,
    )
    assert facts.function_name == "test_fn"
    assert facts.by_virtual == {}
    assert facts.cg_section is None


def _make_ist(opcode, operands, regs):
    return Instruction(
        opcode=opcode, operands=operands, annotations=[], regs=regs,
    )


def _make_block(idx, instrs, succ=None, pred=None):
    b = Block(index=idx, succ=succ or [], pred=pred or [], labels=[])
    b.instructions = instrs
    return b


def test_collect_populates_facts_for_single_block() -> None:
    """collect() builds a VirtualFacts entry for every virtual seen."""
    # A simple block: `mr r32, r3` (param init) then `li r33, 0`
    block = _make_block(0, [
        _make_ist("mr", "r32,r3", [("r", 32), ("r", 3)]),
        _make_ist("li", "r33,0", [("r", 33)]),
    ])
    pre_pass = Pass(name="AFTER PEEPHOLE FORWARD")
    pre_pass.blocks.append(block)

    # Synthetic Function — we only need pre_pass + name
    fn = Function(name="test_fn", passes=[pre_pass])

    source = "void test_fn(int x) { int y = 0; }"
    facts = collect(fn, source)

    assert facts.function_name == "test_fn"
    assert 32 in facts.by_virtual
    assert 33 in facts.by_virtual
    # r3 is a physical reg, still gets a slot
    assert 3 in facts.by_virtual
    assert facts.by_virtual[3].is_phys is True
    assert facts.by_virtual[32].is_phys is False
