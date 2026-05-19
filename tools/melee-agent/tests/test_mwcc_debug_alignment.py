"""Tests for the Needleman-Wunsch instruction alignment used by analyze_function.

The alignment recovers the virtual→physical register mapping by aligning
two pcdump passes (typically AFTER PEEPHOLE FORWARD and AFTER REGISTER
COLORING). Register coloring inserts spill/reload pairs and removes
coalesced moves, so the two passes don't have equal instruction counts —
the aligner needs to handle insertions and deletions correctly.
"""

from __future__ import annotations

from src.mwcc_debug.parser import (
    Block,
    Function,
    Instruction,
    Pass,
    _align_nw,
    _instruction_match_score,
    analyze_function,
)


def make_ist(opcode: str, *regs: tuple[str, int]) -> Instruction:
    """Build an Instruction with the given opcode and register tokens."""
    return Instruction(
        opcode=opcode,
        operands=", ".join(f"{k}{n}" for (k, n) in regs),
        annotations=[],
        regs=list(regs),
    )


def test_score_opcode_match_with_no_phys_agreement() -> None:
    pre = make_ist("lwz", ("r", 39), ("r", 32))
    post = make_ist("lwz", ("r", 28), ("r", 26))
    # All-virtual pre, all-physical post → base opcode-match score only.
    assert _instruction_match_score(pre, post) == 5


def test_score_phys_agreement_boosts() -> None:
    # `mr r3, r32` aligned with `mr r3, r26`: position 0 is physical agreement,
    # position 1 is virtual→physical (mapping signal, no score effect).
    pre = make_ist("mr", ("r", 3), ("r", 32))
    post = make_ist("mr", ("r", 3), ("r", 26))
    # 5 base + 2 (r3 == r3) = 7
    assert _instruction_match_score(pre, post) == 7


def test_score_phys_disagreement_penalizes() -> None:
    pre = make_ist("mr", ("r", 3), ("r", 32))
    post = make_ist("mr", ("r", 4), ("r", 26))
    # 5 base - 3 (r3 != r4) = 2
    assert _instruction_match_score(pre, post) == 2


def test_score_opcode_mismatch() -> None:
    pre = make_ist("lwz", ("r", 39), ("r", 32))
    post = make_ist("stw", ("r", 28), ("r", 26))
    assert _instruction_match_score(pre, post) == -100


def test_align_identical_sequences() -> None:
    insts_pre = [
        make_ist("mr", ("r", 32), ("r", 3)),
        make_ist("lwz", ("r", 39), ("r", 32)),
    ]
    insts_post = [
        make_ist("mr", ("r", 26), ("r", 3)),
        make_ist("lwz", ("r", 28), ("r", 26)),
    ]
    pairs = _align_nw(insts_pre, insts_post)
    assert pairs == [(0, 0), (1, 1)]


def test_align_deletion_in_post() -> None:
    """Pre has an extra `mr r3, r32` that was coalesced away in post."""
    insts_pre = [
        make_ist("mr", ("r", 32), ("r", 3)),
        make_ist("mr", ("r", 3), ("r", 32)),  # coalesced
        make_ist("lwz", ("r", 39), ("r", 32)),
    ]
    insts_post = [
        make_ist("mr", ("r", 26), ("r", 3)),
        make_ist("lwz", ("r", 28), ("r", 26)),
    ]
    pairs = _align_nw(insts_pre, insts_post)
    # The `mr r3,r32` (pre idx 1) is the deletion.
    assert pairs == [(0, 0), (1, None), (2, 1)]


def test_align_insertion_in_post() -> None:
    """Post has an extra spill `stw r0, 16(r1)` that pre didn't have."""
    insts_pre = [
        make_ist("li", ("r", 32)),
        make_ist("add", ("r", 33), ("r", 32), ("r", 3)),
    ]
    insts_post = [
        make_ist("li", ("r", 27)),
        make_ist("stw", ("r", 27), ("r", 1)),  # spill insert
        make_ist("add", ("r", 28), ("r", 27), ("r", 3)),
    ]
    pairs = _align_nw(insts_pre, insts_post)
    assert pairs == [(0, 0), (None, 1), (1, 2)]


def test_align_multiple_inserts_and_deletes() -> None:
    """Realistic worst case: spill bracket + coalesce."""
    insts_pre = [
        make_ist("li", ("r", 32)),
        make_ist("mr", ("r", 33), ("r", 32)),  # coalesced
        make_ist("add", ("r", 34), ("r", 32), ("r", 33)),
    ]
    insts_post = [
        make_ist("li", ("r", 5)),
        make_ist("stw", ("r", 5), ("r", 1)),  # spill insert
        # mr r33, r32 was coalesced (no entry)
        make_ist("lwz", ("r", 5), ("r", 1)),  # reload insert
        make_ist("add", ("r", 6), ("r", 5), ("r", 5)),
    ]
    pairs = _align_nw(insts_pre, insts_post)
    # The DP should pick: li↔li, gap+gap or gap+gap+coalesce, add↔add.
    # The exact path is one of a few near-optimal but the first and last must align.
    assert pairs[0] == (0, 0)
    assert pairs[-1] == (2, 3)
    # And total length covers all of both inputs
    pre_indices = [p for p, _ in pairs if p is not None]
    post_indices = [q for _, q in pairs if q is not None]
    assert pre_indices == [0, 1, 2]
    assert post_indices == [0, 1, 2, 3]


def test_align_empty_post() -> None:
    """All pre instructions were eliminated in post (e.g. dead block)."""
    insts_pre = [make_ist("mr", ("r", 3), ("r", 32))]
    insts_post: list[Instruction] = []
    pairs = _align_nw(insts_pre, insts_post)
    assert pairs == [(0, None)]


def test_align_empty_pre() -> None:
    """Post inserted instructions in an empty pre block (rare)."""
    insts_pre: list[Instruction] = []
    insts_post = [make_ist("stw", ("r", 0), ("r", 1))]
    pairs = _align_nw(insts_pre, insts_post)
    assert pairs == [(None, 0)]


def test_analyze_recovers_mapping_through_coalesce() -> None:
    """End-to-end: a block with a coalesced mr should still recover the
    virtual→physical mapping via other instructions touching the same virtual.
    """
    pre_block = Block(index=0, succ=[], pred=[], labels=["L0"])
    pre_block.instructions = [
        make_ist("li", ("r", 32)),                       # li r32, 0
        make_ist("mr", ("r", 3), ("r", 32)),             # COALESCED in post
        make_ist("bl", ),                                # bl foo  (no regs)
        make_ist("mr", ("r", 33), ("r", 3)),             # mr r33, r3 (capture ret)
        make_ist("add", ("r", 34), ("r", 32), ("r", 33)),  # add r34, r32, r33
    ]
    post_block = Block(index=0, succ=[], pred=[], labels=["L0"])
    post_block.instructions = [
        make_ist("li", ("r", 3)),                        # r32 → r3
        # mr r3, r32 — eliminated (coalesced)
        make_ist("bl", ),                                # bl foo
        make_ist("mr", ("r", 31), ("r", 3)),             # r33 → r31
        make_ist("add", ("r", 0), ("r", 3), ("r", 31)),  # r34 → r0, r32 → r3, r33 → r31
    ]

    pre_pass = Pass(name="BEFORE REGISTER COLORING", blocks=[pre_block])
    post_pass = Pass(name="AFTER REGISTER COLORING", blocks=[post_block])
    fn = Function(name="test_fn", passes=[pre_pass, post_pass])

    infos = {v.virtual: v for v in analyze_function(fn)}
    # r32 should map to r3 (from `li r32` → `li r3`, and `add r34,r32,r33` → `add r0,r3,r31`)
    assert infos[32].physical == 3
    # r33 should map to r31 (from `mr r33,r3` → `mr r31,r3`, and `add r34,r32,r33` → `add r0,r3,r31`)
    assert infos[33].physical == 31
    # r34 should map to r0 (from `add r34,...` → `add r0,...`)
    assert infos[34].physical == 0
