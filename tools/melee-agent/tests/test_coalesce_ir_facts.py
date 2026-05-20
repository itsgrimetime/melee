"""Tests for the coalesce-suggestion IR facts layer."""

from __future__ import annotations

import textwrap

from src.mwcc_debug.coalesce_ir_facts import IrFacts, VirtualFacts, collect, _blocks_defining, _common_successor
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


def test_collect_aggregates_use_sites_across_blocks() -> None:
    """A virtual used in multiple blocks gets all its use sites."""
    b0 = _make_block(0, [
        _make_ist("li", "r32,5", [("r", 32)]),
    ])
    b1 = _make_block(1, [
        _make_ist("addi", "r33,r32,1", [("r", 33), ("r", 32)]),
    ])
    b2 = _make_block(2, [
        _make_ist("stw", "r32,4(r34)", [("r", 32), ("r", 34)]),
    ])
    pre_pass = Pass(name="AFTER PEEPHOLE FORWARD")
    pre_pass.blocks.extend([b0, b1, b2])
    from src.mwcc_debug.parser import Function
    fn = Function(name="test_fn", passes=[pre_pass])
    facts = collect(fn, "void test_fn(void) {}")
    use_blocks = {b for (b, _) in facts.by_virtual[32].use_sites}
    assert use_blocks == {0, 1, 2}
    assert facts.by_virtual[32].use_sites_truncated is False


def test_collect_caps_use_sites_at_USE_SITES_CAP() -> None:
    """When use sites exceed the cap, truncated flag is True."""
    from src.mwcc_debug.coalesce_ir_facts import USE_SITES_CAP
    # 20 uses in one block — should be capped to 16
    instrs = [
        _make_ist("addi", f"r33,r32,{i}", [("r", 33), ("r", 32)])
        for i in range(20)
    ]
    block = _make_block(0, instrs)
    pre_pass = Pass(name="AFTER PEEPHOLE FORWARD")
    pre_pass.blocks.append(block)
    from src.mwcc_debug.parser import Function
    fn = Function(name="test_fn", passes=[pre_pass])
    facts = collect(fn, "void test_fn(void) {}")
    assert len(facts.by_virtual[32].use_sites) == USE_SITES_CAP
    assert facts.by_virtual[32].use_sites_truncated is True


def test_is_param_via_entry_block_abi_mr() -> None:
    """First-def `mr r32, r3` in block 0 → is_param=True."""
    block = _make_block(0, [
        _make_ist("mr", "r32,r3", [("r", 32), ("r", 3)]),
    ])
    pre_pass = Pass(name="AFTER PEEPHOLE FORWARD")
    pre_pass.blocks.append(block)
    from src.mwcc_debug.parser import Function
    fn = Function(name="f", passes=[pre_pass])
    facts = collect(fn, "void f(int x) {}")
    assert facts.by_virtual[32].is_param is True


def test_is_param_not_for_non_param_first_def() -> None:
    """First-def is `li r32, 0` (not from r3-r10) → is_param=False."""
    block = _make_block(0, [
        _make_ist("li", "r32,0", [("r", 32)]),
    ])
    pre_pass = Pass(name="AFTER PEEPHOLE FORWARD")
    pre_pass.blocks.append(block)
    from src.mwcc_debug.parser import Function
    fn = Function(name="f", passes=[pre_pass])
    facts = collect(fn, "void f(void) { int x = 0; }")
    assert facts.by_virtual[32].is_param is False


def test_is_param_fallback_via_bridge_prefix() -> None:
    """When no entry-block ABI-mr, use bridge's sorted observed_virtuals
    prefix to identify likely-param virtuals."""
    # No first-def is `mr` from r3-r10, but bridge says fn has 2 params.
    block = _make_block(0, [
        _make_ist("li", "r32,0", [("r", 32)]),
        _make_ist("li", "r33,0", [("r", 33)]),
        _make_ist("li", "r34,0", [("r", 34)]),
    ])
    pre_pass = Pass(name="AFTER PEEPHOLE FORWARD")
    pre_pass.blocks.append(block)
    from src.mwcc_debug.parser import Function
    fn = Function(name="f", passes=[pre_pass])
    # Two params → first two virtuals (32, 33) should be is_param
    facts = collect(fn, "void f(int a, int b) { int c = 0; }")
    # The bridge identifies a, b as params and c as local
    assert facts.by_virtual[32].is_param is True
    assert facts.by_virtual[33].is_param is True
    assert facts.by_virtual[34].is_param is False


def test_blocks_defining_finds_all_def_blocks() -> None:
    """A virtual defined in multiple blocks → list of those block indices."""
    b0 = _make_block(0, [
        _make_ist("li", "r32,0", [("r", 32)]),
    ])
    b1 = _make_block(1, [
        _make_ist("li", "r32,1", [("r", 32)]),
    ])
    b2 = _make_block(2, [
        _make_ist("addi", "r33,r32,1", [("r", 33), ("r", 32)]),  # use only
    ])
    pre_pass = Pass(name="X")
    pre_pass.blocks.extend([b0, b1, b2])
    result = _blocks_defining(pre_pass, 32)
    assert [b.index for b in result] == [0, 1]


def test_common_successor_returns_join_index() -> None:
    """If all blocks share exactly one successor → return its index."""
    b0 = _make_block(0, [], succ=[2])
    b1 = _make_block(1, [], succ=[2])
    assert _common_successor([b0, b1]) == 2


def test_common_successor_none_when_no_shared() -> None:
    """If blocks don't all converge → None."""
    b0 = _make_block(0, [], succ=[2])
    b1 = _make_block(1, [], succ=[3])
    assert _common_successor([b0, b1]) is None


def test_common_successor_none_when_multiple_shared() -> None:
    """If blocks share multiple successors → not a single join → None."""
    b0 = _make_block(0, [], succ=[2, 3])
    b1 = _make_block(1, [], succ=[2, 3])
    assert _common_successor([b0, b1]) is None
