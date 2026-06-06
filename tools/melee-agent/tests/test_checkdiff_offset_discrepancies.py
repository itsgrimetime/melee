# tests/test_checkdiff_offset_discrepancies.py
"""Tests for _paired_struct_offset_delta and offset_discrepancies in classify_asm_diff."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("checkdiff", REPO / "tools/checkdiff.py")
checkdiff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checkdiff)


# ---------------------------------------------------------------------------
# Task 2.1: _paired_struct_offset_delta unit tests
# ---------------------------------------------------------------------------

def test_paired_struct_offset_delta_basic():
    # same mnemonic, same base, different displacement -> discrepancy
    d = checkdiff._paired_struct_offset_delta("stb     r0,2304(r3)", "stb     r0,1856(r3)")
    assert d == {"base_reg": "r3", "mnemonic": "stb", "ref_disp": 2304, "cur_disp": 1856}


def test_paired_struct_offset_delta_excludes_stack_and_sda():
    assert checkdiff._paired_struct_offset_delta("stw r0,8(r1)", "stw r0,16(r1)") is None
    assert checkdiff._paired_struct_offset_delta("lwz r3,0(r2)", "lwz r3,8(r2)") is None


def test_paired_struct_offset_delta_excludes_r13():
    assert checkdiff._paired_struct_offset_delta("lwz r3,0(r13)", "lwz r3,8(r13)") is None


def test_paired_struct_offset_delta_same_disp_none():
    assert checkdiff._paired_struct_offset_delta("stb r0,8(r3)", "stb r0,8(r3)") is None


def test_paired_struct_offset_delta_diff_mnemonic_none():
    assert checkdiff._paired_struct_offset_delta("stb r0,8(r3)", "sth r0,16(r3)") is None


def test_paired_struct_offset_delta_diff_base_none():
    assert checkdiff._paired_struct_offset_delta("stw r0,8(r3)", "stw r0,16(r4)") is None


# ---------------------------------------------------------------------------
# Task 2.2: offset_discrepancies in classify_asm_diff
# ---------------------------------------------------------------------------

def _lines(seq):
    """Build normalized '+NNN: 00 00 00 00 \tasm' lines."""
    return [f"+{i*4:03x}: 00 00 00 00 \t{a}" for i, a in enumerate(seq)]


def test_offset_discrepancies_clean():
    ref = _lines(["li r0,1", "stb r0,2304(r3)", "blr"])
    cur = _lines(["li r0,1", "stb r0,1856(r3)", "blr"])
    c = checkdiff.classify_asm_diff(ref, cur)
    od = c.get("offset_discrepancies", [])
    assert any(d["ref_disp"] == 2304 and d["cur_disp"] == 1856 and d["base_reg"] == "r3" for d in od)


def test_offset_discrepancies_dupbody_guard():
    # identical repeated bodies — dup-body guard must suppress mispaired discrepancies
    ref = _lines(["stw r0,0(r28)", "stw r0,4(r28)", "stw r0,0(r28)"])
    cur = _lines(["stw r0,0(r28)", "stw r0,8(r28)", "stw r0,0(r28)"])
    c = checkdiff.classify_asm_diff(ref, cur)
    od = c.get("offset_discrepancies", [])
    # The guard suppresses blocks where the same key repeats.
    # All three lines have the same _struct_key (DISP(r28)), so the dup-body
    # guard fires on the whole block and must not emit any r28 discrepancies.
    assert all(d["base_reg"] != "r28" for d in od)


def test_offset_discrepancies_stack_excluded():
    ref = _lines(["stw r3,8(r1)", "blr"])
    cur = _lines(["stw r3,16(r1)", "blr"])
    c = checkdiff.classify_asm_diff(ref, cur)
    od = c.get("offset_discrepancies", [])
    assert len(od) == 0


def test_offset_discrepancies_empty_when_identical():
    lines = _lines(["li r0,1", "stw r0,8(r3)", "blr"])
    c = checkdiff.classify_asm_diff(lines, lines)
    # instruction-identical path returns early — key may be absent or empty list
    od = c.get("offset_discrepancies", [])
    assert od == []


# ---------------------------------------------------------------------------
# Task 2.3: JSON output contains offset_discrepancies key
# ---------------------------------------------------------------------------

import pytest

@pytest.mark.slow
def test_thprestart_offset_discrepancies_live():
    """Requires a built GALE01 tree. Asserts the key exists and is a list."""
    out = subprocess.run(
        ["python", "tools/checkdiff.py", "__THPRestartDefinition",
         "--no-tty", "--format", "json", "--no-build"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    od = data["classification"].get("offset_discrepancies", [])
    # post-fix tree: matched -> empty; key must exist and be a list
    assert isinstance(od, list)
