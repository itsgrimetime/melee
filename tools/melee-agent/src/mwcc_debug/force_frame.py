"""Diff-derived object patching for stack-frame diagnostics.

This is intentionally narrow: it only patches current object instruction bytes
when checkdiff shows the same instruction at the same function-local offset and
the only byte difference is the D-form immediate used for an r1 stack access.
It also supports direct anonymous-symbol renames from paired relocation lines,
which covers 4-byte float literals that value-based name-magic cannot resolve.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .o_rewriter import Mapping, globalize_symbols, rename_magic_symbols


DEFAULT_OBJCOPY = "/opt/devkitpro/devkitPPC/bin/powerpc-eabi-objcopy"

_INSN_LINE_RE = re.compile(
    r"^\+([0-9A-Fa-f]+):\s+"
    r"((?:[0-9A-Fa-f]{2}\s+){3}[0-9A-Fa-f]{2})\s+(.+)$"
)
_RELOC_LINE_RE = re.compile(
    r"^\+([0-9A-Fa-f]+):\s+(R_[A-Za-z0-9_]+)\s+(\S+)"
)
_STACK_OFFSET_OPS = {
    "lbz",
    "lha",
    "lhz",
    "lwz",
    "lfs",
    "lfd",
    "stb",
    "sth",
    "stw",
    "stfs",
    "stfd",
    "stwu",
}


@dataclass(frozen=True)
class ParsedInstructionLine:
    offset: int
    raw_bytes: bytes
    mnemonic: str
    operands: str


@dataclass(frozen=True)
class InstructionBytePatch:
    """A current-object instruction rewrite derived from paired checkdiff asm."""

    offset: int
    expected_bytes: bytes
    replacement_bytes: bytes
    mnemonic: str
    current_operands: str
    target_operands: str


@dataclass(frozen=True)
class SymbolRename:
    old_name: str
    new_name: str
    reloc_type: str
    offset: int


@dataclass(frozen=True)
class ForceFramePatchPlan:
    byte_patches: list[InstructionBytePatch]
    symbol_renames: list[SymbolRename]

    @property
    def is_empty(self) -> bool:
        return not self.byte_patches and not self.symbol_renames


@dataclass(frozen=True)
class ForceFrameApplyResult:
    byte_patches_applied: int
    symbol_renames: list[tuple[str, str]]
    globalized_symbols: list[str]


class ForceFramePatchError(RuntimeError):
    """Raised when a diff-derived patch cannot be safely applied."""


def _parse_instruction_line(line: str) -> ParsedInstructionLine | None:
    match = _INSN_LINE_RE.match(line)
    if match is None:
        return None
    asm = match.group(3).strip()
    if not asm:
        return None
    parts = asm.split(None, 1)
    mnemonic = parts[0]
    operands = parts[1].strip() if len(parts) > 1 else ""
    return ParsedInstructionLine(
        offset=int(match.group(1), 16),
        raw_bytes=bytes.fromhex(match.group(2)),
        mnemonic=mnemonic,
        operands=operands,
    )


def _parse_relocation_line(line: str) -> tuple[int, str, str] | None:
    match = _RELOC_LINE_RE.match(line)
    if match is None:
        return None
    return int(match.group(1), 16), match.group(2), match.group(3)


def _is_stack_instruction(line: ParsedInstructionLine) -> bool:
    if line.mnemonic in _STACK_OFFSET_OPS:
        return "(r1)" in line.operands.replace(" ", "")
    if line.mnemonic == "addi":
        operands = line.operands.replace(" ", "")
        return ",r1," in operands or operands.startswith("r1,r1,")
    return False


def _is_stack_immediate_pair(
    target: ParsedInstructionLine,
    current: ParsedInstructionLine,
) -> bool:
    if target.offset != current.offset:
        return False
    if target.mnemonic != current.mnemonic:
        return False
    if target.raw_bytes == current.raw_bytes:
        return False
    if len(target.raw_bytes) != 4 or len(current.raw_bytes) != 4:
        return False
    # D-form immediate changes preserve the high 16 bits of the instruction.
    if target.raw_bytes[:2] != current.raw_bytes[:2]:
        return False
    return _is_stack_instruction(target) and _is_stack_instruction(current)


def _paired_lines(payload: dict[str, Any]) -> Iterable[tuple[str, str]]:
    target_lines = payload.get("target_asm") or payload.get("reference_asm") or []
    current_lines = payload.get("current_asm") or []
    if not isinstance(target_lines, list) or not isinstance(current_lines, list):
        return []
    return zip(target_lines, current_lines)


def derive_force_frame_patch_plan(payload: dict[str, Any]) -> ForceFramePatchPlan:
    """Derive safe stack-frame object rewrites from a checkdiff JSON payload."""

    byte_patches: list[InstructionBytePatch] = []
    rename_by_old: dict[str, SymbolRename] = {}

    for target_line, current_line in _paired_lines(payload):
        if not isinstance(target_line, str) or not isinstance(current_line, str):
            continue

        target_insn = _parse_instruction_line(target_line)
        current_insn = _parse_instruction_line(current_line)
        if (
            target_insn is not None
            and current_insn is not None
            and _is_stack_immediate_pair(target_insn, current_insn)
        ):
            byte_patches.append(
                InstructionBytePatch(
                    offset=current_insn.offset,
                    expected_bytes=current_insn.raw_bytes,
                    replacement_bytes=target_insn.raw_bytes,
                    mnemonic=current_insn.mnemonic,
                    current_operands=current_insn.operands,
                    target_operands=target_insn.operands,
                )
            )
            continue

        target_reloc = _parse_relocation_line(target_line)
        current_reloc = _parse_relocation_line(current_line)
        if target_reloc is None or current_reloc is None:
            continue
        target_offset, target_type, target_name = target_reloc
        current_offset, current_type, current_name = current_reloc
        if target_offset != current_offset or target_type != current_type:
            continue
        if not current_name.startswith("@") or target_name.startswith("@"):
            continue
        rename_by_old.setdefault(
            current_name,
            SymbolRename(
                old_name=current_name,
                new_name=target_name,
                reloc_type=current_type,
                offset=current_offset,
            ),
        )

    return ForceFramePatchPlan(
        byte_patches=byte_patches,
        symbol_renames=list(rename_by_old.values()),
    )


def _function_section_file_offset(obj_path: Path, function: str) -> int:
    from elftools.elf.elffile import ELFFile

    with obj_path.open("rb") as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name(".symtab")
        if symtab is None:
            raise ForceFramePatchError(f"{obj_path} has no .symtab")

        candidates = [
            sym
            for sym in symtab.iter_symbols()
            if sym.name == function and isinstance(sym["st_shndx"], int)
        ]
        if not candidates:
            raise ForceFramePatchError(
                f"function symbol {function!r} not found in {obj_path}"
            )
        symbol = candidates[0]
        section = elf.get_section(symbol["st_shndx"])
        if section is None:
            raise ForceFramePatchError(
                f"section for function symbol {function!r} not found in {obj_path}"
            )
        return int(section["sh_offset"]) + int(symbol["st_value"])


def apply_function_byte_patches(
    obj_path: Path,
    function: str,
    patches: list[InstructionBytePatch],
) -> int:
    """Apply byte patches at function-local offsets in a relocatable ELF .o."""

    if not patches:
        return 0
    base_offset = _function_section_file_offset(obj_path, function)
    data = bytearray(obj_path.read_bytes())
    for patch in patches:
        start = base_offset + patch.offset
        end = start + len(patch.expected_bytes)
        if start < 0 or end > len(data):
            raise ForceFramePatchError(
                f"patch for {function}+0x{patch.offset:x} is outside {obj_path}"
            )
        actual = bytes(data[start:end])
        if actual != patch.expected_bytes:
            raise ForceFramePatchError(
                f"stale patch for {function}+0x{patch.offset:x}: expected "
                f"{patch.expected_bytes.hex()}, found {actual.hex()}"
            )
        data[start:end] = patch.replacement_bytes
    obj_path.write_bytes(data)
    return len(patches)


def _resolve_objcopy(objcopy: str = DEFAULT_OBJCOPY) -> str:
    if Path(objcopy).exists():
        return objcopy
    found = shutil.which("powerpc-eabi-objcopy")
    if found:
        return found
    return objcopy


def apply_force_frame_patch_plan(
    obj_path: Path,
    function: str,
    plan: ForceFramePatchPlan,
    *,
    objcopy: str = DEFAULT_OBJCOPY,
) -> ForceFrameApplyResult:
    """Apply a diff-derived force-frame plan to a compiled object in place."""

    byte_count = apply_function_byte_patches(obj_path, function, plan.byte_patches)
    renames: list[tuple[str, str]] = []
    globalized: list[str] = []
    if plan.symbol_renames:
        mapping = Mapping(
            by_value={},
            by_name={rename.old_name: rename.new_name for rename in plan.symbol_renames},
        )
        resolved_objcopy = _resolve_objcopy(objcopy)
        renames = rename_magic_symbols(obj_path, mapping, objcopy=resolved_objcopy)
        if renames:
            globalized = [new_name for _old_name, new_name in renames]
            globalize_symbols(obj_path, globalized, objcopy=resolved_objcopy)
    return ForceFrameApplyResult(
        byte_patches_applied=byte_count,
        symbol_renames=renames,
        globalized_symbols=globalized,
    )
