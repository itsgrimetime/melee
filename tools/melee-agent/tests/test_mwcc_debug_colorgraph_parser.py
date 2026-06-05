"""Tests for mwcc_debug hook-event parsing used by debug inspect diff."""
from __future__ import annotations

import src.mwcc_debug.colorgraph_parser as colorgraph_parser
from src.mwcc_debug.colorgraph_parser import parse_hook_events


class _RejectNonNumericRows:
    def __init__(self, real_pattern):
        self._real_pattern = real_pattern

    def match(self, line: str):
        stripped = line.lstrip()
        if stripped and not (stripped[0].isdigit() or stripped[0] == "-"):
            raise AssertionError(f"regex called for non-table row: {line!r}")
        return self._real_pattern.match(line)


def test_parse_natural_coalesce_mappings() -> None:
    text = """
Starting function fn_test

[COALESCE] enter class=1 n_virtuals=8
[COALESCE] natural mappings (virt -> root):
  5 -> 3
  6 -> 4
[COALESCE] exit class=1 n_virtuals=8 distinct_roots=6 forced=0

IG CONSTRUCTED (class=1, n_nodes=8)
""".strip()

    events = parse_hook_events(text)

    assert len(events) == 1
    assert events[0].coalesce_sections[0].class_id == 1
    assert events[0].coalesce_sections[0].n_virtuals == 8
    assert events[0].coalesce_sections[0].mappings == [(5, 3), (6, 4)]
    assert events[0].coalesce_sections[0].distinct_roots == 6
    assert events[0].coalesce_sections[0].forced_count == 0


def test_parse_force_coalesce_override_applications() -> None:
    text = """
Starting function fn_test

[COALESCE] enter class=0 n_virtuals=64
[COALESCE] natural mappings (virt -> root):
  43 -> 40
[FORCE_COALESCE] alias[43]: 40 -> 43
[COALESCE] exit class=0 n_virtuals=64 distinct_roots=64 forced=1
""".strip()

    events = parse_hook_events(text)

    section = events[0].coalesce_sections[0]
    assert section.mappings == [(43, 40)]
    assert section.forced_overrides == [(43, 40, 43)]
    assert section.forced_count == 1


def test_parse_empty_natural_coalesce_mappings() -> None:
    text = """
Starting function fn_test

[COALESCE] enter class=0 n_virtuals=4
[COALESCE] natural mappings (virt -> root):
  (none - no virtuals coalesced)
[COALESCE] exit class=0 n_virtuals=4 distinct_roots=4 forced=0
""".strip()

    events = parse_hook_events(text)

    assert events[0].coalesce_sections[0].class_id == 0
    assert events[0].coalesce_sections[0].mappings == []
    assert events[0].coalesce_sections[0].distinct_roots == 4


def test_parse_coalesced_aliases_after_colorgraph_section() -> None:
    text = """
Starting function fn_test

COLORGRAPH DECISIONS (class=1, result=1, n_nodes=8)
iter  ig_idx  reg  degree  nIntfr  flags
0     3       r3   0       0       0x08
1     4       r4   0       0       0x08

COALESCED ALIASES (alias_idx -> root_idx [root_phys]):
  5 -> 3 [r3]
  6 -> 4 [r4]
""".strip()

    events = parse_hook_events(text)

    assert len(events[0].coalesced_alias_sections) == 1
    aliases = events[0].coalesced_alias_sections[0]
    assert aliases.class_id == 1
    assert aliases.aliases == [(5, 3, 3), (6, 4, 4)]


def test_parser_skips_pcode_lines_before_table_row_regexes(monkeypatch) -> None:
    monkeypatch.setattr(
        colorgraph_parser,
        "_SIMPLIFY_ITER_RE",
        _RejectNonNumericRows(colorgraph_parser._SIMPLIFY_ITER_RE),
    )
    monkeypatch.setattr(
        colorgraph_parser,
        "_ITER_RE",
        _RejectNonNumericRows(colorgraph_parser._ITER_RE),
    )
    text = """
Starting function fn_test

COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
iter  ig_idx  reg  degree  nIntfr  flags
    lwz     r7,28(r4); fIsPtrOp
0     40      r3   0       0       0x00

SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)
iter ig_idx degree array_size flags
    lwz     r6,24(r4); fIsPtrOp
0    40     1      1          0x0
""".strip()

    events = parse_hook_events(text)

    assert events[0].colorgraph_sections[0].decisions[0].ig_idx == 40
    assert events[0].simplify_sections[0].entries[0].ig_idx == 40
