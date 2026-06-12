"""Robustness tests for parse_pcdump.

Covers two behaviors that the matching agent relies on for safe iteration:

1. A malformed block header (e.g. `Succ={B B7}` emitted when MWCC's
   list bookkeeping is in an intermediate state) does NOT abort the parse —
   the stray token is dropped with a stderr warning and the rest of the
   pcdump is still consumed.
2. Passing `function='fn_target'` slices the pcdump to that function's
   section, so malformed output in other functions cannot block downstream
   commands from analyzing the target.
"""

from __future__ import annotations

import textwrap

from src.mwcc_debug.parser import parse_pcdump, slice_pcdump_to_function


def test_parse_pcdump_recovers_from_malformed_block_header() -> None:
    """A stray 'B' token in Succ={...} doesn't abort the parse."""
    text = textwrap.dedent("""\
        Starting function fn_bad
        AFTER REGISTER COLORING
        fn_bad
        B5: Succ={B B7} Pred={B4} Labels={L5 }

            li r3, 0

        Starting function fn_good
        AFTER REGISTER COLORING
        fn_good
        B0: Succ={B1 } Pred={} Labels={L0 }

            li r4, 5
    """)
    fns = parse_pcdump(text)
    # Both functions should be present
    names = [f.name for f in fns]
    assert "fn_bad" in names
    assert "fn_good" in names


def test_parse_pcdump_function_slice_only_returns_target() -> None:
    """When `function='fn_target'` is given, only that function parses."""
    text = textwrap.dedent("""\
        Starting function fn_other
        AFTER REGISTER COLORING
        fn_other
        B0: Succ={B WHATEVER} Pred={} Labels={L0 }

            li r3, 0

        Starting function fn_target
        AFTER REGISTER COLORING
        fn_target
        B0: Succ={B1 } Pred={} Labels={L0 }

            li r4, 5
    """)
    fns = parse_pcdump(text, function="fn_target")
    assert len(fns) == 1
    assert fns[0].name == "fn_target"


def test_slice_pcdump_to_function_returns_only_target_section() -> None:
    text = textwrap.dedent("""\
        preamble
        Starting function fn_other
        BEFORE
            li r3, 0

        Starting function fn_target
        BEFORE
            li r4, 5
        AFTER
            blr

        Starting function fn_tail
        BEFORE
            li r5, 6
    """)

    sliced = slice_pcdump_to_function(text, "fn_target")

    assert sliced.startswith("Starting function fn_target\n")
    assert "li r4, 5" in sliced
    assert "fn_other" not in sliced
    assert "fn_tail" not in sliced


def test_slice_pcdump_to_function_keeps_repeated_target_markers() -> None:
    text = textwrap.dedent("""\
        Starting function fn_target
        chunk 0
        Starting function fn_target
        chunk 1
        Starting function fn_tail
        tail
    """)

    sliced = slice_pcdump_to_function(text, "fn_target")

    assert "chunk 0" in sliced
    assert "chunk 1" in sliced
    assert "fn_tail" not in sliced


def test_parse_pcdump_function_slice_missing_returns_empty() -> None:
    text = "Starting function fn_a\n"
    fns = parse_pcdump(text, function="not_present")
    assert fns == []


def test_parse_pcdump_recovers_bad_pred_token() -> None:
    """A stray token in Pred={...} also recovers without crashing."""
    text = textwrap.dedent("""\
        Starting function fn_bad_pred
        AFTER REGISTER COLORING
        fn_bad_pred
        B2: Succ={B3 } Pred={B B1} Labels={L2 }

            li r3, 0
    """)
    fns = parse_pcdump(text)
    assert len(fns) == 1
    fn = fns[0]
    assert fn.name == "fn_bad_pred"
    # The pass and block should still be present despite the malformed Pred
    p = fn.get_pass("AFTER REGISTER COLORING")
    assert p is not None
    assert len(p.blocks) == 1
    assert p.blocks[0].index == 2
    # The bad token 'B' was dropped; only the valid B1 remains.
    assert p.blocks[0].pred == [1]


def test_parse_pcdump_function_slice_extracts_passes() -> None:
    """The slice should preserve the entire target function section
    (multiple passes, multiple blocks) — not just the header.
    """
    text = textwrap.dedent("""\
        Starting function fn_other
        AFTER REGISTER COLORING
        fn_other
        B0: Succ={} Pred={} Labels={L0 }

            li r3, 0

        Starting function fn_target
        BEFORE REGISTER COLORING
        fn_target
        B0: Succ={B1 } Pred={} Labels={L0 }

            li r32, 5

        B1: Succ={} Pred={B0 } Labels={L1 }

            mr r3, r32

        AFTER REGISTER COLORING
        fn_target
        B0: Succ={B1 } Pred={} Labels={L0 }

            li r31, 5

        B1: Succ={} Pred={B0 } Labels={L1 }

            mr r3, r31
    """)
    fns = parse_pcdump(text, function="fn_target")
    assert len(fns) == 1
    fn = fns[0]
    assert fn.name == "fn_target"
    assert len(fn.passes) == 2
    pre = fn.get_pass("BEFORE REGISTER COLORING")
    post = fn.get_pass("AFTER REGISTER COLORING")
    assert pre is not None
    assert post is not None
    assert len(pre.blocks) == 2
    assert len(post.blocks) == 2
