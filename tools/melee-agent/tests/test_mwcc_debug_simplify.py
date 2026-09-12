"""Tests for the SIMPLIFY GRAPH event parser added by the Tier 2.5 hook."""

from __future__ import annotations

from src.mwcc_debug.colorgraph_parser import (
    parse_hook_events,
    find_function,
)


SAMPLE = """\
Starting function example_fn
some other output

IG CONSTRUCTED (class=0, n_nodes=14)

SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=39)
iter  ig_idx  degree  arraySize flags     notes
0     -1      0       0        0x2
1     -1      0       3        0x2
2     5       11      17       0x2
3     -1      0       3        0xa       SPILLED
4     7       4       8        0xb       SPILLED

COLORGRAPH DECISIONS (class=0, result=1, n_nodes=14)
iter  ig_idx  assignedReg degree  nIntfr  flags
0     -1      r0         0       0       0x02

Starting function other_fn

SIMPLIFY GRAPH (class=1, n_colors=32, n_class_regs=70)
iter  ig_idx  degree  arraySize flags     notes
0     32      0       0        0x2
"""


def test_simplify_basic_parse() -> None:
    fns = parse_hook_events(SAMPLE)
    assert len(fns) == 2
    fn = find_function(fns, "example_fn")
    assert fn is not None
    assert len(fn.simplify_sections) == 1
    sec = fn.simplify_sections[0]
    assert sec.class_id == 0
    assert sec.n_colors == 29
    assert sec.n_class_regs == 39
    assert len(sec.entries) == 5


def test_simplify_extracts_fields() -> None:
    fns = parse_hook_events(SAMPLE)
    fn = find_function(fns, "example_fn")
    assert fn is not None
    entries = fn.simplify_sections[0].entries

    # Header row (iter=0)
    assert entries[0].iter_idx == 0
    assert entries[0].ig_idx == -1
    assert entries[0].degree == 0
    assert entries[0].array_size == 0
    assert entries[0].flags == 0x02
    assert entries[0].spilled is False

    # ig_idx=5 entry
    assert entries[2].ig_idx == 5
    assert entries[2].degree == 11
    assert entries[2].array_size == 17

    # Spill entry (flags & 0x08)
    assert entries[3].iter_idx == 3
    assert entries[3].flags == 0x0a
    assert entries[3].spilled is True
    # And a SPILLED entry with a real ig_idx
    assert entries[4].iter_idx == 4
    assert entries[4].ig_idx == 7
    assert entries[4].flags == 0x0b
    assert entries[4].spilled is True


def test_simplify_only_associates_with_correct_function() -> None:
    """The class=1 SIMPLIFY GRAPH should land in other_fn, not example_fn."""
    fns = parse_hook_events(SAMPLE)
    example = find_function(fns, "example_fn")
    other = find_function(fns, "other_fn")
    assert example is not None and other is not None
    assert len(example.simplify_sections) == 1
    assert example.simplify_sections[0].class_id == 0
    assert len(other.simplify_sections) == 1
    assert other.simplify_sections[0].class_id == 1


def test_simplify_not_confused_by_colorgraph_rows() -> None:
    """The COLORGRAPH DECISIONS row immediately following SIMPLIFY GRAPH
    must not be parsed as a simplify entry."""
    fns = parse_hook_events(SAMPLE)
    fn = find_function(fns, "example_fn")
    assert fn is not None
    # Simplify has 5 entries (not 6 — the colorgraph iter=0 r0... row would be
    # parsed by a too-eager regex)
    assert len(fn.simplify_sections[0].entries) == 5
    # And the colorgraph section picked up its own row
    assert len(fn.colorgraph_sections) == 1
    assert len(fn.colorgraph_sections[0].decisions) == 1
