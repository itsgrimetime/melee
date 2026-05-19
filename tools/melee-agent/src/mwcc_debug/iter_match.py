"""Match expected r28..r31 defs to BEFORE COLORING virtuals.

Given an expected `AsmInstruction` (extracted from build/GALE01/asm/*.s)
and a pre-coloring `Pass` (from the current pcdump), find the virtual
register that the current compile assigned to the "slot" that expected
gave to a specific physical register.

The mapping is positional + structural: we normalize each instruction to
`(opcode, operand_signature_with_regs_replaced_by_R)`, find instructions
in the pre-coloring pass with the matching signature, and pick the one
closest to the expected position.

In MWCC's IG, ig_idx is the virtual register number directly (verified
empirically against the COLORGRAPH DECISIONS interferer list, where
entries like `47=r29` mean "virtual r47 was colored r29"). So once we
identify the destination virtual, its ig_idx is just the virtual's
register number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .asm_parser import AsmInstruction
from .parser import Instruction, Pass


_REG_TOKEN_RE = re.compile(r"\b([rf])\d+\b")
_HEX_LITERAL_RE = re.compile(r"\b0x([0-9A-Fa-f]+)\b")
_RELOC_SUFFIX_RE = re.compile(r"@(sda21|ha|hi|l|lo)\b")
# pcdump wraps lis/addi symbol operands as `HA(sym)` / `LO(sym)`; the
# expected `.s` uses `sym@ha` / `sym@l` (handled by _RELOC_SUFFIX_RE).
# Strip the wrapper so both end up as plain `sym`.
_RELOC_WRAPPER_RE = re.compile(r"\b(HA|LO|HI|H|L)\s*\(\s*([^)]+?)\s*\)")
_ANNOTATION_RE = re.compile(r";.*$")
_CR_PREFIX_RE = re.compile(r"\bcr0\s*,\s*")
_WHITESPACE_RE = re.compile(r"\s+")


def instr_signature(opcode: str, operands: str) -> tuple[str, str]:
    """Normalize an instruction for cross-pass / cross-format comparison.

    The expected `.s` (from dtk's disassembler) and the pcdump (from
    mwcc's internal dump) use different conventions for the SAME
    underlying instruction:

      | aspect          | expected `.s`               | pcdump            |
      |-----------------|------------------------------|-------------------|
      | numeric literal | 0x2c, 0x0                    | 44, 0             |
      | symbol reloc    | sym@sda21, sym@ha            | sym (no suffix)   |
      | cr operand      | implicit ("cmplwi r3, 0x0")  | explicit ("cmpli cr0, r3, 0") |
      | annotations     | none                         | "; fIsPtrOp"      |
      | opcode aliases  | cmplwi                       | cmpli             |

    We normalize both sides to a canonical form:
      - registers → R/F placeholders
      - hex literals → decimal
      - relocation suffixes stripped
      - cr0 prefix stripped
      - annotations dropped
      - whitespace collapsed

    Opcode aliases aren't resolved here — callers should use canonical
    opcodes if needed. In practice, the first-def detection uses simple
    arithmetic/load opcodes (li, lwz, lhz, lbz, addi, mr, ...) which
    don't have aliasing issues.
    """

    def reg_repl(m: re.Match[str]) -> str:
        return "R" if m.group(1) == "r" else "F"

    def hex_repl(m: re.Match[str]) -> str:
        return str(int(m.group(1), 16))

    norm = operands
    norm = _ANNOTATION_RE.sub("", norm)
    norm = _RELOC_SUFFIX_RE.sub("", norm)
    # Unwrap HA(sym)/LO(sym)/HI(sym)/H(sym)/L(sym) → sym
    norm = _RELOC_WRAPPER_RE.sub(lambda m: m.group(2), norm)
    norm = _HEX_LITERAL_RE.sub(hex_repl, norm)
    norm = _REG_TOKEN_RE.sub(reg_repl, norm)
    norm = _CR_PREFIX_RE.sub("", norm)
    # Remove all whitespace — pcdump uses no spaces after commas
    # (`r124,mn_804D6BC8(r0)`) while expected uses `r4, mn_...(r0)`.
    # Collapsing avoids both inconsistencies.
    norm = re.sub(r"\s+", "", norm)
    return (opcode, norm)


@dataclass
class MatchResult:
    virtual: int  # the virtual register that occupied this slot
    ig_idx: int  # the virtual reg's ig_idx (identity mapping in MWCC)
    instruction_index: int  # position within the pre-pass linear instr list
    confidence: str  # "exact" (single match) | "ambiguous" (multiple, picked closest)


def _linear_instructions(pre_pass: Pass) -> list[Instruction]:
    out: list[Instruction] = []
    for block in pre_pass.blocks:
        out.extend(block.instructions)
    return out


def _destination_virtual(ist: Instruction) -> Optional[int]:
    """Return the destination virtual register number (the first reg
    token that's >= 32), or None if the instruction has no virtual
    destination.
    """
    if not ist.regs:
        return None
    kind, num = ist.regs[0]
    if kind != "r":
        return None
    if num < 32:
        return None
    return num


def match_virtual_for_expected_def(
    expected_ist: AsmInstruction,
    expected_position: int,
    pre_pass: Pass,
) -> Optional[MatchResult]:
    """Find the virtual register in `pre_pass` that occupies the position
    corresponding to `expected_ist` in the expected output.

    `expected_position` is the body-relative index in expected (post-
    prologue). We compare to the *linear* instruction list of `pre_pass`
    (we don't bother with block-relative positions because the
    pre-coloring pass and the final asm have the same block layout for
    high-match functions).

    Returns None if no signature match is found.
    """
    target_sig = instr_signature(expected_ist.opcode, expected_ist.operands)
    instructions = _linear_instructions(pre_pass)

    # Find candidates with matching signature AND a virtual destination.
    # We filter on virtual-dest BEFORE picking-closest, since a physical-
    # dest candidate (`li r3, 0` for argument passing) shouldn't shadow
    # a valid virtual-dest candidate further away.
    candidates: list[tuple[int, Instruction]] = []
    for i, ist in enumerate(instructions):
        if instr_signature(ist.opcode, ist.operands) != target_sig:
            continue
        if _destination_virtual(ist) is None:
            continue
        candidates.append((i, ist))

    if not candidates:
        return None

    # Pick the candidate whose position is closest to expected_position
    candidates.sort(key=lambda p: abs(p[0] - expected_position))
    best_i, best_ist = candidates[0]
    virt = _destination_virtual(best_ist)
    # virt is guaranteed non-None by the filter above
    assert virt is not None

    confidence = "exact" if len(candidates) == 1 else "ambiguous"

    return MatchResult(
        virtual=virt,
        ig_idx=virt,  # MWCC IG: ig_idx == virtual reg number
        instruction_index=best_i,
        confidence=confidence,
    )
