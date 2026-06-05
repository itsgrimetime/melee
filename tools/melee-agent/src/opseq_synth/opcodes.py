"""
Opcode extraction and normalization.

Parses disassembly output from dtk and extracts opcode sequences
in multiple representations for flexible matching.
"""

import hashlib
import re
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class OpcodeSequence:
    """
    Multiple representations of an opcode sequence for different matching strategies.

    - raw: Full instructions as strings ["mr r3, r4", "addi r3, r3, 1", ...]
    - mnemonics: Just the opcodes ["mr", "addi", ...]
    - normalized: Instructions with positional register names ["mr rA, rB", "addi rA, rA, 1", ...]

    Different representations enable different query types:
    - mnemonics: "What C produces this sequence of operations?"
    - normalized: "What C produces this pattern with these register reuse patterns?"
    - raw: Exact match (unlikely to be useful across different contexts)
    """

    raw: list[str]
    mnemonics: list[str]
    normalized: list[str]

    @property
    def mnemonic_hash(self) -> str:
        """Hash of just the mnemonic sequence."""
        return _hash_list(self.mnemonics)

    @property
    def normalized_hash(self) -> str:
        """Hash including normalized register patterns."""
        return _hash_list(self.normalized)

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "mnemonics": self.mnemonics,
            "normalized": self.normalized,
        }

    def get_ngrams(self, n: int = 3) -> list[str]:
        """Extract n-gram subsequences of mnemonics for fuzzy matching."""
        if len(self.mnemonics) < n:
            return [",".join(self.mnemonics)]
        return [",".join(self.mnemonics[i : i + n]) for i in range(len(self.mnemonics) - n + 1)]

    def get_normalized_ngrams(self, n: int = 3) -> list[str]:
        """Extract n-gram subsequences of normalized instructions."""
        if len(self.normalized) < n:
            return [",".join(self.normalized)]
        return [",".join(self.normalized[i : i + n]) for i in range(len(self.normalized) - n + 1)]


def _hash_list(items: list[str], max_len: int = 30) -> str:
    """Hash a list of strings, truncating if too long."""
    content = ",".join(items[:max_len])
    return hashlib.md5(content.encode()).hexdigest()[:16]


def normalize_instruction(instruction: str) -> str:
    """
    Normalize register names to positional placeholders.

    "mr r3, r4" -> "mr rA, rB"

    This preserves register reuse patterns without caring about
    specific register numbers. First register seen becomes rA,
    second becomes rB, etc.

    Float registers (f0-f31) get their own namespace (fA, fB, ...).
    """
    register_map = {}
    next_gpr = 0
    next_fpr = 0

    def replace_reg(match: re.Match) -> str:
        nonlocal next_gpr, next_fpr
        reg = match.group(0)

        if reg not in register_map:
            if reg.startswith("f"):
                register_map[reg] = f"f{chr(ord('A') + next_fpr)}"
                next_fpr += 1
            else:
                register_map[reg] = f"r{chr(ord('A') + next_gpr)}"
                next_gpr += 1

        return register_map[reg]

    # Match r0-r31 and f0-f31
    # Be careful not to match things like "0x10" or hex immediates
    return re.sub(r"\b([rf])(\d{1,2})\b", replace_reg, instruction)


def extract_opcodes(asm: str, function_name: str = None) -> OpcodeSequence:
    """
    Parse disassembly from dtk and extract opcode sequence.

    Args:
        asm: Disassembly output from `dtk elf disasm`
        function_name: If provided, only extract opcodes for this function

    Returns:
        OpcodeSequence with raw, mnemonic, and normalized representations
    """
    raw = []
    mnemonics = []
    normalized = []

    in_target_function = function_name is None
    found_function = False

    for line in asm.splitlines():
        # Check for function start: ".fn target_func, global" or ".fn target_func, local"
        fn_match = re.match(r"^\.fn\s+(\w+)", line)
        if fn_match:
            if function_name is None or fn_match.group(1) == function_name:
                in_target_function = True
                found_function = True
            else:
                in_target_function = False
            continue

        # Check for function end
        if line.startswith(".endfn"):
            if in_target_function and found_function:
                break  # We got our function, done
            in_target_function = function_name is None
            continue

        if not in_target_function:
            continue

        # Parse instruction line
        # Format: "/* 00000000 00000034  2C 04 00 00 */	cmpwi r4, 0x0"
        # Or:     "/* 00000034 00000068  80 A6 00 00 */	lwz r5, 0x0(r6)"
        instr_match = re.match(r"^\s*/\*.*\*/\s+(\S+)\s*(.*)", line)
        if instr_match:
            mnemonic = instr_match.group(1)
            operands = instr_match.group(2).strip()

            # Skip labels (they look like .L_00000034:)
            if mnemonic.startswith("."):
                continue

            full_instr = f"{mnemonic} {operands}".strip() if operands else mnemonic
            raw.append(full_instr)
            mnemonics.append(mnemonic)
            normalized.append(normalize_instruction(full_instr))

    return OpcodeSequence(
        raw=raw,
        mnemonics=mnemonics,
        normalized=normalized,
    )


def parse_mnemonic_sequence(seq: str) -> list[str]:
    """
    Parse a comma-separated mnemonic sequence string.

    "beq,mr,lwz" -> ["beq", "mr", "lwz"]
    """
    return [m.strip() for m in seq.split(",") if m.strip()]


def opcodes_to_string(opcodes: OpcodeSequence, mode: str = "mnemonics") -> str:
    """Convert opcode sequence to string representation."""
    if mode == "raw":
        return "\n".join(opcodes.raw)
    elif mode == "normalized":
        return ",".join(opcodes.normalized)
    else:  # mnemonics
        return ",".join(opcodes.mnemonics)
