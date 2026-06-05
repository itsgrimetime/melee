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
from src.cli import debug


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


def build_framed_function(frame_size: int) -> Function:
    fn = build_simple_function()
    final = Pass(name="FINAL CODE AFTER INSTRUCTION SCHEDULING")
    final_block = Block(index=0, succ=[], pred=[], labels=["L0"])
    final_block.instructions = [
        Instruction("stwu", f"r1,-{frame_size}(r1)", [], []),
        Instruction("stw", "r31,40(r1)", [], [("r", 31)]),
        Instruction("addi", f"r1,r1,{frame_size}", [], []),
    ]
    final.blocks.append(final_block)
    fn.passes.append(final)
    return fn


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


def test_derive_target_includes_frame_and_scores_frame_distance() -> None:
    target_fn = build_framed_function(144)
    candidate_fn = build_framed_function(152)
    spec = derive_target_from_function(target_fn)

    assert spec["frame"]["frame_size"] == 144
    assert spec["frame"]["unused_ranges"][0] == {"start": 8, "end": 40, "size": 32}

    result = score_function(
        candidate_fn,
        {"function": "test_fn", "virtuals": {}, "frame": spec["frame"]},
        weights=ScoreWeights(
            byte=0.0,
            virtual=0.0,
            spill=0.0,
            interferer=0.0,
            frame_size=1.0,
            frame_unused=0.0,
        ),
    )

    assert result.frame_targeted
    assert result.frame_size_actual == 152
    assert result.frame_size_target == 144
    assert result.frame_size_distance == 8
    assert result.frame_penalty == 8.0
    assert result.total == 8.0


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


def test_suggest_param_iter_ceiling() -> None:
    """Detect: low-ig_idx virtual wants a physical held by higher-ig_idx
    virtual, with no direct interference between them. This is the
    parameter-loses-to-local-in-iter-order ceiling pattern.
    """
    # r32 (param-like, low ig_idx) wants r31, but actually got r0.
    # r33 (higher ig_idx, local) holds r31.
    # r32 and r33 don't interfere in the simple function above; they
    # only share an instruction at the move that gets coalesced.
    # Construct a Function where they explicitly don't interfere.
    pre = Pass(name="BEFORE REGISTER COLORING")
    pre_block = Block(index=0, succ=[], pred=[], labels=["L0"])
    pre_block.instructions = [
        make_ist("li", ("r", 33)),                   # r33 born
        make_ist("add", ("r", 0), ("r", 33), ("r", 33)),  # r33 used
        # r33 dies here. Now r32 can live without interference.
        make_ist("mr", ("r", 32), ("r", 3)),         # r32 born (would be param load)
        make_ist("add", ("r", 0), ("r", 32), ("r", 32)),  # r32 used
    ]
    pre.blocks.append(pre_block)
    post = Pass(name="AFTER REGISTER COLORING")
    post_block = Block(index=0, succ=[], pred=[], labels=["L0"])
    post_block.instructions = [
        make_ist("li", ("r", 31)),                   # r33 → r31
        make_ist("add", ("r", 0), ("r", 31), ("r", 31)),
        make_ist("mr", ("r", 0), ("r", 3)),          # r32 → r0
        make_ist("add", ("r", 0), ("r", 0), ("r", 0)),
    ]
    post.blocks.append(post_block)
    fn = Function(name="test_fn", passes=[pre, post])

    # Target wants r32 at r31 (would be the agent's hypothesized "natural"
    # allocation that force-phys can produce).
    target = {"function": "test_fn", "virtuals": {32: 31}}
    result = score_function(fn, target)
    suggestions = suggest(fn, result)

    # Should produce a high-severity param-iter-ceiling suggestion
    ceiling = next((s for s in suggestions
                    if s.category == "param-iter-ceiling"), None)
    assert ceiling is not None, (
        f"expected param-iter-ceiling category, got: "
        f"{[(s.virtual, s.category, s.severity) for s in suggestions]}"
    )
    assert ceiling.severity == "high"
    assert ceiling.virtual == 32
    assert "ig_idx" in ceiling.description.lower()
    assert "force-phys" in ceiling.description
    assert "Tier 6" in ceiling.description


def test_interference_guidance_explains_two_virtual_color_order() -> None:
    pre = Pass(name="BEFORE REGISTER COLORING")
    pre_block = Block(index=0, succ=[], pred=[], labels=["L0"])
    pre_block.instructions = [
        make_ist("li", ("r", 33)),
        make_ist("li", ("r", 46)),
        make_ist("add", ("r", 0), ("r", 33), ("r", 46)),
    ]
    pre.blocks.append(pre_block)
    post = Pass(name="AFTER REGISTER COLORING")
    post_block = Block(index=0, succ=[], pred=[], labels=["L0"])
    post_block.instructions = [
        make_ist("li", ("r", 30)),
        make_ist("li", ("r", 31)),
        make_ist("add", ("r", 0), ("r", 30), ("r", 31)),
    ]
    post.blocks.append(post_block)
    fn = Function(name="test_fn", passes=[pre, post])
    events = FunctionEvents(
        name="test_fn",
        simplify_sections=[
            SimplifySection(
                class_id=0,
                n_colors=18,
                n_class_regs=18,
                entries=[
                    SimplifyEntry(
                        iter_idx=5,
                        ig_idx=33,
                        degree=2,
                        array_size=6,
                        flags=0,
                        spilled=False,
                    ),
                    SimplifyEntry(
                        iter_idx=2,
                        ig_idx=46,
                        degree=1,
                        array_size=9,
                        flags=0,
                        spilled=False,
                    ),
                ],
            )
        ],
    )

    result = score_function(
        fn,
        {"function": "test_fn", "virtuals": {33: 31}},
        events=events,
    )
    suggestions = suggest(fn, result, events=events)

    interference = next(s for s in suggestions if s.category == "interference")
    assert "Color-order detail" in interference.description
    assert "r33 iter=5" in interference.description
    assert "r46 iter=2" in interference.description
    assert "reduce r46" in interference.description
    assert "increase r33" in interference.description
    assert "--force-iter-first 33,46" in interference.description


def test_custom_weights() -> None:
    fn = build_simple_function()
    target = {"function": "test_fn", "virtuals": {32: 99}}
    # With default weights: byte=100, virtual=10 -> total 110
    # With virtual=0: only byte penalty -> 100
    custom = ScoreWeights(byte=100.0, virtual=0.0, spill=0.0, interferer=0.0)
    result = score_function(fn, target, weights=custom)
    assert result.total == 100.0


def test_ceiling_recommendations_prefer_local_dump_before_remote_fallback() -> None:
    recs = debug._ceiling_recommendations(
        function="WriteCharactersForNameAtIndex",
        unit="melee/mn/mnnamenew",
    )

    joined = "\n".join(recs)
    local_idx = joined.index("melee-agent debug dump local")
    remote_idx = joined.index("melee-agent debug dump remote")
    assert local_idx < remote_idx
    assert "remote fallback" in joined


def test_ceiling_recommendations_use_actionable_taxonomy() -> None:
    recs = debug._ceiling_recommendations(
        function="WriteCharactersForNameAtIndex",
        unit="melee/mn/mnnamenew",
    )

    joined = "\n".join(recs)
    assert "no fast transform found" in joined.lower()
    assert "unresolved by current heuristics" in joined.lower()
    assert "requires source-shape search" in joined.lower()
    assert "true structural ceiling" not in joined.lower()
    assert "impossible" not in joined.lower()
    assert "unmatchable" not in joined.lower()


def test_ceiling_command_docstring_uses_current_tooling_language() -> None:
    doc = debug.ceiling.__doc__ or ""

    assert "Current-tooling diagnosis" in doc
    assert "NO FAST TRANSFORM FOUND" in doc
    assert "PROBABLE CEILING" not in doc
    assert "Structural-ceiling verdict" not in doc


def test_force_phys_class_scoped_value_passes_to_dll_without_iter_warning() -> None:
    dll_value, warnings = debug._normalize_force_phys("gpr:33:31")

    assert dll_value == "0:33:31"
    assert warnings == []
