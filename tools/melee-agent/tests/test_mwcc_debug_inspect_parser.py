"""Tests for parsing mwcc-inspect output into diff snapshots."""
from __future__ import annotations

from src.mwcc_debug.inspect_parser import parse_inspect_snapshots


def test_parse_inspect_snapshots_for_function() -> None:
    text = """
==== MWCC Inspector ====
FUNCTION: other_fn
STATEMENTS
  return;
FUNCTION: fn_test
LOCAL VARIABLES
  int i
STATEMENTS
  i = arg0 + 1
ENODES
  add(arg0, 1)
OPTIMIZED IR
  i = addi arg0, 1
FUNCTION: later_fn
STATEMENTS
  return;
""".strip()

    snapshots = parse_inspect_snapshots(text, function="fn_test")

    assert [s.name for s in snapshots] == [
        "Frontend: LOCAL VARIABLES",
        "Frontend: STATEMENTS",
        "Frontend: ENODES",
        "Mid-end: OPTIMIZED IR",
    ]
    assert "i = arg0 + 1" in snapshots[1].text
    assert all("later_fn" not in s.text for s in snapshots)


def test_parse_inspect_returns_empty_when_function_missing() -> None:
    text = "FUNCTION: other_fn\nSTATEMENTS\n  return;"

    assert parse_inspect_snapshots(text, function="fn_test") == []
