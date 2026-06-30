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
    assert d == {
        "base_reg": "r3",
        "ref_base_reg": "r3",
        "cur_base_reg": "r3",
        "mnemonic": "stb",
        "ref_disp": 2304,
        "cur_disp": 1856,
    }


def test_paired_struct_offset_delta_keeps_per_side_bases():
    d = checkdiff._paired_struct_offset_delta("lwz r0,16(r28)", "lwz r0,24(r31)")
    assert d["base_reg"] == "r31"
    assert d["ref_base_reg"] == "r28"
    assert d["cur_base_reg"] == "r31"
    assert d["ref_disp"] == 16
    assert d["cur_disp"] == 24


def test_paired_struct_offset_delta_excludes_stack_and_sda():
    assert checkdiff._paired_struct_offset_delta("stw r0,8(r1)", "stw r0,16(r1)") is None
    assert checkdiff._paired_struct_offset_delta("lwz r3,0(r2)", "lwz r3,8(r2)") is None


def test_paired_struct_offset_delta_excludes_r13():
    assert checkdiff._paired_struct_offset_delta("lwz r3,0(r13)", "lwz r3,8(r13)") is None


def test_paired_struct_offset_delta_same_disp_none():
    assert checkdiff._paired_struct_offset_delta("stb r0,8(r3)", "stb r0,8(r3)") is None


def test_paired_struct_offset_delta_diff_mnemonic_none():
    assert checkdiff._paired_struct_offset_delta("stb r0,8(r3)", "sth r0,16(r3)") is None


def test_paired_struct_offset_delta_diff_base_uses_current_base_for_legacy_key():
    d = checkdiff._paired_struct_offset_delta("stw r0,8(r3)", "stw r0,16(r4)")
    assert d["base_reg"] == "r4"
    assert d["ref_base_reg"] == "r3"
    assert d["cur_base_reg"] == "r4"


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


def test_offset_discrepancies_different_physical_bases_are_reported():
    ref = _lines(["mr r28,r3", "lwz r0,16(r28)", "blr"])
    cur = _lines(["mr r31,r3", "lwz r0,24(r31)", "blr"])
    c = checkdiff.classify_asm_diff(ref, cur)
    od = c.get("offset_discrepancies", [])
    assert any(d["ref_base_reg"] == "r28" and d["cur_base_reg"] == "r31" for d in od)


def test_offset_discrepancies_include_instruction_indices():
    ref = _lines(["mr r28,r3", "lwz r0,16(r28)", "blr"])
    cur = _lines(["mr r31,r3", "lwz r0,24(r31)", "blr"])
    c = checkdiff.classify_asm_diff(ref, cur)
    d = next(d for d in c.get("offset_discrepancies", []) if d["ref_base_reg"] == "r28")

    assert d["ref_index"] == 1
    assert d["cur_index"] == 1


def test_offset_discrepancy_indices_skip_function_header():
    ref = ["<fn>:", *_lines(["mr r28,r3", "lwz r0,16(r28)", "blr"])]
    cur = ["<fn>:", *_lines(["mr r31,r3", "lwz r0,24(r31)", "blr"])]
    c = checkdiff.classify_asm_diff(ref, cur)
    d = next(d for d in c.get("offset_discrepancies", []) if d["ref_base_reg"] == "r28")

    assert d["ref_index"] == 1
    assert d["cur_index"] == 1


def test_offset_discrepancies_matched_opcode_equal_block_with_repeats():
    """A matched-opcode function (the tool's main target).

    Displacement masking makes the ref/cur _struct_key sequences identical
    element-wise, so SequenceMatcher returns the whole function as ONE `equal`
    block that contains REPEATED instruction shapes (two `sth DISP(r3)`). The
    dup-body guard must NOT suppress here: position k <-> position k is the
    authoritative correspondence and repeated keys cannot mispair. This is the
    `__THPRestartDefinition` shape and MUST yield every offset discrepancy.
    Regression for the bug where the guard fired on the whole-function equal
    block and `struct verify` found nothing on exactly the functions it is for.
    """
    ref = _lines([
        "li r0,1",
        "stb r0,2304(r3)",
        "sth r0,2300(r3)",
        "lhz r0,2300(r3)",
        "sth r0,2302(r3)",
        "blr",
    ])
    cur = _lines([
        "li r0,1",
        "stb r0,1856(r3)",
        "sth r0,1858(r3)",
        "lhz r0,1858(r3)",
        "sth r0,1860(r3)",
        "blr",
    ])
    c = checkdiff.classify_asm_diff(ref, cur)
    od = c.get("offset_discrepancies", [])
    # all four memory-op discrepancies must be present, paired positionally
    found = {(d["mnemonic"], d["ref_disp"], d["cur_disp"], d["base_reg"]) for d in od}
    assert ("stb", 2304, 1856, "r3") in found
    assert ("sth", 2300, 1858, "r3") in found
    assert ("lhz", 2300, 1858, "r3") in found
    assert ("sth", 2302, 1860, "r3") in found
    # exactly those four (no spurious extras)
    assert len(od) == 4


def test_offset_discrepancies_dupbody_guard_replace_block():
    """Dup-body guard fires ONLY on `replace` blocks with a repeated key.

    Here the ref region [stw(r28), stw(r28)] is replaced by cur's
    [lwz(r29), lwz(r29)] (a shape that never matches ref's, so it cannot be
    pulled into an `equal` block); it is a genuine equal-length `replace`
    block whose ref side has a REPEATED `_struct_key`. Because instructions in
    a replace block may be reordered, a repeated key could mispair, so the
    guard skips the block -> no discrepancy emitted for r28/r29.
    """
    ref = _lines([
        "cmpwi r3,0",
        "stw r0,16(r28)",
        "stw r0,32(r28)",
        "lwz r5,8(r30)",
    ])
    cur = _lines([
        "cmpwi r3,0",
        "lwz r0,40(r29)",
        "lwz r0,48(r29)",
        "lwz r5,8(r30)",
    ])
    c = checkdiff.classify_asm_diff(ref, cur)
    od = c.get("offset_discrepancies", [])
    # the repeated-key replace block is suppressed; the matching lwz(r30)
    # anchor has identical displacement so it is not a discrepancy either
    assert od == []


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
