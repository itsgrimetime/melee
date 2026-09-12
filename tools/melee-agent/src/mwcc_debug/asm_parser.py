"""Parse build/GALE01/asm/*.s files produced by dtk's disassembler.

Each `.s` file has many functions in a flat layout: `.fn <name>, <scope>`
opens a function, `.endfn <name>` closes it. Inside, instructions are
formatted as:

    /* <addr> <fileoff>  <bytes> */\\t<opcode> <operands>

We parse just enough to:
- Locate one function by name.
- Walk its body line by line.
- Identify the prologue boundary so callers can skip save/restore code.
- Find the first instruction that defines (writes to) a target physical
  register.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# Matches "/* addr fileoff  bytes */\topcode operands" — the leading addr
# block disambiguates a real instruction line from a directive.
_INSTR_RE = re.compile(
    r"^\s*/\*\s*[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+(?:[0-9A-Fa-f]{2}\s*)+\*/\s*(.+)$"
)
# Register tokens: r0+/f0+ (we don't validate upper bounds).
_REG_RE = re.compile(r"\b([rf])(\d+)\b")
_FN_START_RE = re.compile(r"^\s*\.fn\s+(\S+)\s*(?:,\s*\w+)?\s*$")
_FN_END_RE = re.compile(r"^\s*\.endfn\b")
# Prologue opcodes (the typical PowerPC entry sequence emitted by mwcc).
_PROLOGUE_OPCODES = {"mflr", "stw", "stwu", "stfd", "stmw", "stwux"}


@dataclass
class AsmInstruction:
    opcode: str
    operands: str
    # Register tokens in order of appearance in the operand string.
    regs: list[tuple[str, int]]


@dataclass
class AsmFunction:
    name: str
    instructions: list[AsmInstruction]


def _parse_instr_line(line: str) -> Optional[AsmInstruction]:
    m = _INSTR_RE.match(line)
    if not m:
        return None
    rest = m.group(1).strip()
    parts = rest.split(None, 1)
    if not parts:
        return None
    opcode = parts[0]
    operands = parts[1] if len(parts) > 1 else ""
    regs = [(t, int(n)) for t, n in _REG_RE.findall(operands)]
    return AsmInstruction(opcode=opcode, operands=operands, regs=regs)


def extract_function(asm_text: str, function_name: str) -> Optional[AsmFunction]:
    """Find `function_name` in the .s text and return its instruction list.

    Returns None if not found.
    """
    in_fn = False
    instructions: list[AsmInstruction] = []
    for line in asm_text.splitlines():
        if not in_fn:
            m = _FN_START_RE.match(line)
            if m and m.group(1) == function_name:
                in_fn = True
            continue
        if _FN_END_RE.match(line):
            return AsmFunction(name=function_name, instructions=instructions)
        ist = _parse_instr_line(line)
        if ist is not None:
            instructions.append(ist)
    if in_fn:
        # `.endfn` never appeared but we found the start — return what we
        # have. dtk always emits .endfn but we don't want to error here.
        return AsmFunction(name=function_name, instructions=instructions)
    return None


def _is_prologue_instr(ist: AsmInstruction) -> bool:
    """True if the instruction looks like part of the function entry sequence.

    We accept:
      - mflr (always)
      - stw r0, X(r1)         (saved LR)
      - stwu r1, ...           (frame alloc)
      - stfd fN, X(r1)         (saved FPR)
      - stmw rN, X(r1)         (saved GPR group)
      - stwux r1, ...          (variable-size frame alloc; rare)
    """
    if ist.opcode not in _PROLOGUE_OPCODES:
        return False
    if ist.opcode == "mflr":
        return True
    # All other prologue opcodes touch r1 as base address. The cheapest
    # check is that "r1" appears in the operand string.
    return "r1" in ist.operands or "(r1)" in ist.operands


def parse_prologue_end(instructions: list[AsmInstruction]) -> int:
    """Return the index of the first non-prologue instruction.

    Walks the instruction list from the front and stops at the first
    instruction that doesn't look like a prologue save. Returns the
    index; for an empty list or one that's all prologue, returns
    len(instructions).
    """
    for i, ist in enumerate(instructions):
        if not _is_prologue_instr(ist):
            return i
    return len(instructions)


def find_first_def(
    instructions: list[AsmInstruction],
    target_reg: int,
    reg_kind: str = "r",
) -> Optional[tuple[int, AsmInstruction]]:
    """Find the first instruction in `instructions` where `target_reg`
    appears as the destination operand (the first register slot).

    The destination is conventionally the first register token in the
    operand string for arithmetic/load opcodes (`addi rD, rA, simm`,
    `lwz rD, X(rA)`, `li rD, simm`, `mr rD, rA`). For stores (`stw rS,
    X(rA)`) the first reg is the SOURCE, not the destination — those
    instructions don't *define* the target register, so we exclude
    store opcodes when checking for "def".

    Returns `(index, instruction)` or `None` if no def found.
    """
    for i, ist in enumerate(instructions):
        if not ist.regs:
            continue
        # Skip store opcodes — they don't define their first register.
        if ist.opcode.startswith("st") or ist.opcode.startswith("psq_st"):
            continue
        # Skip branches and compares (don't write a GPR-as-dest).
        if ist.opcode.startswith("b") or ist.opcode.startswith("cmp"):
            continue
        first_kind, first_num = ist.regs[0]
        if first_kind == reg_kind and first_num == target_reg:
            return (i, ist)
    return None
