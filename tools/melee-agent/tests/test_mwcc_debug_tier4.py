"""Tests for the Tier 4 scoring + guidance modules."""

from __future__ import annotations

from src.mwcc_debug.colorgraph_parser import (
    FunctionEvents,
    SimplifyEntry,
    SimplifySection,
)
from src.mwcc_debug.guidance import suggest
from src.mwcc_debug.parser import (
    Block,
    Function,
    Instruction,
    Pass,
)
from src.mwcc_debug.scoring import (
    ScoreWeights,
    derive_target_from_function,
    score_function,
)


def make_ist(opcode: str, *regs: tuple[str, int]) -> Instruction:
    return Instruction(
        opcode=opcode,
        operands=", ".join(f"{k}{n}" for (k, n) in regs),
        annotations=[],
        regs=list(regs),
    )


def build_simple_function() -> Function:
    """Build a Function with one block, pre-coloring (virtuals) and
    post-coloring (physicals) passes. r32 maps to r26.
    """
    pre = Pass(name="BEFORE REGISTER COLORING")
    pre_block = Block(index=0, succ=[], pred=[], labels=["L0"])
    pre_block.instructions = [
        make_ist("li", ("r", 32)),
        make_ist("mr", ("r", 33), ("r", 32)),
        make_ist("add", ("r", 34), ("r", 32), ("r", 33)),
    ]
    pre.blocks.append(pre_block)

    post = Pass(name="AFTER REGISTER COLORING")
    post_block = Block(index=0, succ=[], pred=[], labels=["L0"])
    post_block.instructions = [
        make_ist("li", ("r", 26)),
        make_ist("mr", ("r", 31), ("r", 26)),
        make_ist("add", ("r", 0), ("r", 26), ("r", 31)),
    ]
    post.blocks.append(post_block)

    return Function(name="test_fn", passes=[pre, post])


def test_score_perfect_match() -> None:
    fn = build_simple_function()
    target = {
        "function": "test_fn",
        "virtuals": {32: 26, 33: 31, 34: 0},
    }
    result = score_function(fn, target)
    assert result.total == 0.0
    assert result.matched == 3
    assert result.targeted == 3
    assert result.virtual_distance == 0
    assert result.wrong == []


def test_score_one_wrong() -> None:
    fn = build_simple_function()
    target = {
        "function": "test_fn",
        "virtuals": {32: 27, 33: 31, 34: 0},  # r32 target wrong (should be 26 actual)
    }
    result = score_function(fn, target)
    assert result.matched == 2
    assert result.targeted == 3
    assert result.virtual_distance == 1
    assert result.total > 0


def test_score_byte_distance_dominates() -> None:
    fn = build_simple_function()
    target_zero = {"function": "test_fn", "virtuals": {32: 26}}
    target_one_wrong = {"function": "test_fn", "virtuals": {32: 99}}
    r0 = score_function(fn, target_zero)
    r1 = score_function(fn, target_one_wrong)
    # Byte penalty for 100% miss (1/1) at weight 100 = 100.0
    # Virtual penalty for 1 wrong at weight 10 = 10.0
    assert r0.total == 0.0
    assert r1.total == 110.0


def test_score_spill_penalty() -> None:
    fn = build_simple_function()
    target = {"function": "test_fn", "virtuals": {32: 26}}
    events = FunctionEvents(name="test_fn")
    events.simplify_sections.append(SimplifySection(
        class_id=0, n_colors=29, n_class_regs=10,
        entries=[
            SimplifyEntry(iter_idx=0, ig_idx=32, degree=0, array_size=5,
                          flags=0x0a, spilled=True),
        ],
    ))
    r_no_spill_target = score_function(fn, target, events=events)
    # Score includes 5.0 spill penalty for the unexpected SPILLED on r32
    assert r_no_spill_target.spill_penalty == 5.0
    assert r_no_spill_target.total >= 5.0

    target_with_spill = {
        "function": "test_fn",
        "virtuals": {32: 26},
        "spilled": [32],
    }
    r_spill_expected = score_function(fn, target_with_spill, events=events)
    assert r_spill_expected.spill_penalty == 0.0


def test_derive_target_roundtrip() -> None:
    fn = build_simple_function()
    spec = derive_target_from_function(fn)
    assert spec["function"] == "test_fn"
    assert spec["virtuals"] == {32: 26, 33: 31, 34: 0}
    # Scoring against the derived target should give 0
    result = score_function(fn, spec)
    assert result.total == 0.0


def test_suggest_interference_blocker() -> None:
    """When a virtual's target physical is taken by an interfering virtual,
    the suggestion should name that interferer."""
    fn = build_simple_function()
    # r34 wants r31 instead of r0. r34 interferes with r33 (which got r31).
    target = {"function": "test_fn", "virtuals": {34: 31}}
    result = score_function(fn, target)
    suggestions = suggest(fn, result)
    assert len(suggestions) >= 1
    blocker_sugg = next((s for s in suggestions
                         if s.virtual == 34 and s.category == "interference"),
                        None)
    assert blocker_sugg is not None
    assert "r33" in blocker_sugg.description
    assert "r31" in blocker_sugg.description


def test_suggest_spill_warning() -> None:
    fn = build_simple_function()
    events = FunctionEvents(name="test_fn")
    events.simplify_sections.append(SimplifySection(
        class_id=0, n_colors=29, n_class_regs=10,
        entries=[
            SimplifyEntry(iter_idx=0, ig_idx=32, degree=0, array_size=15,
                          flags=0x0a, spilled=True),
        ],
    ))
    target = {"function": "test_fn", "virtuals": {32: 99}}  # wrong on purpose
    result = score_function(fn, target, events=events)
    suggestions = suggest(fn, result, events=events)
    spill_sugg = next((s for s in suggestions
                       if s.virtual == 32 and s.category == "spill"),
                      None)
    assert spill_sugg is not None
    assert "SPILLED" in spill_sugg.description


def test_suggest_severity_ordering() -> None:
    fn = build_simple_function()
    target = {"function": "test_fn", "virtuals": {32: 27, 34: 31}}
    result = score_function(fn, target)
    suggestions = suggest(fn, result)
    severities = [s.severity for s in suggestions]
    severity_order = {"high": 0, "medium": 1, "low": 2}
    # Ensure non-decreasing severity
    for a, b in zip(severities, severities[1:]):
        assert severity_order[a] <= severity_order[b]


def test_custom_weights() -> None:
    fn = build_simple_function()
    target = {"function": "test_fn", "virtuals": {32: 99}}
    # With default weights: byte=100, virtual=10 -> total 110
    # With virtual=0: only byte penalty -> 100
    custom = ScoreWeights(byte=100.0, virtual=0.0, spill=0.0, interferer=0.0)
    result = score_function(fn, target, weights=custom)
    assert result.total == 100.0
