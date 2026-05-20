"""Tests for the relocation-offset normalizer in ``tools/checkdiff.py``.

PowerPC SDA21 relocations target the 16-bit immediate field of an
instruction. Depending on which tool emitted the asm, the reloc may be
reported at the instruction's byte offset (e.g. ``+0xc0``) or at the
immediate-field's offset (+2 from instruction start, e.g. ``+0xc2``).
Without normalization, opcode-identical functions are reported as
mismatched purely on the reloc-line offsets.

These tests exercise the normalizer in isolation and as part of the
expected/current diff pipeline.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_checkdiff():
    """Dynamically load ``tools/checkdiff.py`` as a module.

    ``checkdiff.py`` lives outside the ``melee-agent`` package, so we can't
    use a plain ``import`` from these tests. Resolve it by walking up from
    this file to the repo root and loading the script directly.
    """
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "tools" / "checkdiff.py"
    assert script.is_file(), f"missing {script}"
    spec = importlib.util.spec_from_file_location("checkdiff", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checkdiff():
    return _load_checkdiff()


def test_normalize_rounds_sda21_plus_two_offset(checkdiff):
    """The +2 SDA21 quirk: reloc on immediate halfword folds into instr."""
    lines = [
        "+040: 80 84 00 2c \tlwz     r4,44(r4)",
        "+042: R_PPC_EMB_SDA21\t@470",
    ]
    result = checkdiff.normalize_reloc_line_offsets(lines)
    assert result == [
        "+040: 80 84 00 2c \tlwz     r4,44(r4)",
        "+040: R_PPC_EMB_SDA21\t@470",
    ]


def test_normalize_handles_all_unaligned_low_bits(checkdiff):
    """Any unaligned offset (low bits 1/2/3) rounds down to the 4-byte slot."""
    lines = [
        "+041: R_PPC_EMB_SDA21\tfoo",
        "+042: R_PPC_EMB_SDA21\tfoo",
        "+043: R_PPC_EMB_SDA21\tfoo",
    ]
    result = checkdiff.normalize_reloc_line_offsets(lines)
    assert result == [
        "+040: R_PPC_EMB_SDA21\tfoo",
        "+040: R_PPC_EMB_SDA21\tfoo",
        "+040: R_PPC_EMB_SDA21\tfoo",
    ]


def test_normalize_leaves_aligned_offsets_untouched(checkdiff):
    """Already-aligned offsets (multiples of 4) round-trip unchanged."""
    lines = [
        "+000: R_PPC_REL24\tsome_func",
        "+040: R_PPC_EMB_SDA21\tmnVibration_804D4FF4",
        "+0c0: R_PPC_EMB_SDA21\tmnVibration_804DC018",
    ]
    result = checkdiff.normalize_reloc_line_offsets(lines)
    assert result == lines


def test_normalize_leaves_instruction_lines_untouched(checkdiff):
    """Only reloc lines are rewritten; instruction lines pass through.

    Instruction lines at an unaligned offset would themselves be a bug in
    the disassembler — we don't want to silently mask that.
    """
    lines = [
        "+042: 80 84 00 2c \tlwz     r4,44(r4)",  # hypothetical (broken) instr line
        "+040: 7c 08 02 a6 \tmflr    r0",
    ]
    result = checkdiff.normalize_reloc_line_offsets(lines)
    assert result == lines


def test_normalize_preserves_function_header_and_blank_lines(checkdiff):
    """Header lines (`<func>:`) and empty lines are non-reloc; pass them through."""
    lines = [
        "<mnVibration_80248444>:",
        "",
        "+040: 7c 08 02 a6 \tmflr    r0",
        "+042: R_PPC_EMB_SDA21\t@470",
    ]
    result = checkdiff.normalize_reloc_line_offsets(lines)
    assert result == [
        "<mnVibration_80248444>:",
        "",
        "+040: 7c 08 02 a6 \tmflr    r0",
        "+040: R_PPC_EMB_SDA21\t@470",
    ]


def test_normalize_preserves_offset_width(checkdiff):
    """Hex-offset width is preserved so side-by-side alignment stays stable."""
    # 3-digit (default), 4-digit, and 5-digit widths all preserved.
    assert checkdiff.normalize_reloc_line_offsets(
        ["+0c2: R_PPC_EMB_SDA21\tfoo"]
    ) == ["+0c0: R_PPC_EMB_SDA21\tfoo"]
    assert checkdiff.normalize_reloc_line_offsets(
        ["+10c2: R_PPC_EMB_SDA21\tfoo"]
    ) == ["+10c0: R_PPC_EMB_SDA21\tfoo"]


def test_normalize_makes_plus_two_diff_disappear(checkdiff):
    """The motivating case: expected vs current differ only on +2 reloc offsets.

    After normalization, the two outputs are byte-identical. This is the
    behavior the `mnVibration_80248444` post-name-magic diff needs.
    """
    expected = [
        "<mnVibration_80248444>:",
        "+040: 80 7f 00 04 \tlwz     r3,4(r31)",
        "+040: R_PPC_EMB_SDA21\tmnVibration_804D4FF4",
        "+0c0: 80 1d 00 00 \tlwz     r0,0(r29)",
        "+0c0: R_PPC_EMB_SDA21\tmnVibration_804DC018",
    ]
    current = [
        "<mnVibration_80248444>:",
        "+040: 80 7f 00 04 \tlwz     r3,4(r31)",
        "+042: R_PPC_EMB_SDA21\tmnVibration_804D4FF4",
        "+0c0: 80 1d 00 00 \tlwz     r0,0(r29)",
        "+0c2: R_PPC_EMB_SDA21\tmnVibration_804DC018",
    ]
    assert expected != current  # pre-normalization differ on +2 reloc offsets
    assert checkdiff.normalize_reloc_line_offsets(
        expected
    ) == checkdiff.normalize_reloc_line_offsets(current)


def test_normalize_works_for_dot_reloc_directive_lines(checkdiff):
    """dtk emits ``.reloc`` directives; those are reloc lines too."""
    lines = [
        "+042: \t.reloc *, R_PPC_EMB_SDA21, foo",
    ]
    result = checkdiff.normalize_reloc_line_offsets(lines)
    assert result == [
        "+040: \t.reloc *, R_PPC_EMB_SDA21, foo",
    ]


def test_normalize_handles_unparseable_prefix(checkdiff):
    """Reloc lines without a parseable offset prefix pass through untouched.

    objdump's pre-normalization output places relocs on a line that starts
    with leading whitespace + decimal/hex address (no ``+`` prefix), e.g.
    ``\\t\\t\\t64: R_PPC_EMB_SDA21\\tfoo``. We only handle the normalized
    form (the input we see after ``get_asm_with_objdump``); other formats
    are passed through.
    """
    lines = [
        "\t\t\t64: R_PPC_EMB_SDA21\tfoo",
        "R_PPC_EMB_SDA21\tno_offset_at_all",
    ]
    result = checkdiff.normalize_reloc_line_offsets(lines)
    assert result == lines


def test_normalize_is_idempotent(checkdiff):
    """Running the normalizer twice gives the same result as once."""
    lines = [
        "+042: R_PPC_EMB_SDA21\tfoo",
        "+043: R_PPC_REL24\tbar",
        "+040: 80 84 00 2c \tlwz     r4,44(r4)",
    ]
    once = checkdiff.normalize_reloc_line_offsets(lines)
    twice = checkdiff.normalize_reloc_line_offsets(once)
    assert once == twice
