"""Detect value-numbering ceilings in current-vs-target codegen."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .asm_parser import extract_function
from .parser import Function, Instruction, Pass, parse_pcdump


_REG_RE = re.compile(r"\b([rf])(\d+)\b")
_ASM_COMMENT_RE = re.compile(
    r"^\s*/\*\s*[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+"
    r"(?:[0-9A-Fa-f]{2}\s*)+\*/\s*"
)
_CHECKDIFF_PREFIX_RE = re.compile(r"^\s*\+?[0-9A-Fa-f]{3,}:\s*")
_CHECKDIFF_BYTES_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}\s+){4}")
_CHECKDIFF_WORD_BYTES_RE = re.compile(r"^[0-9A-Fa-f]{8}\s+")
_FULL_ASM_FN_RE = re.compile(r"(?m)^\s*\.fn\s+\S+")
_UNCONDITIONAL_BRANCH_OPCODES = {"b", "bl", "blr", "bctrl", "bdnz", "bdz"}


@dataclass(frozen=True)
class _Inst:
    opcode: str
    operands: str
    regs: tuple[tuple[str, int], ...]
    block_idx: int | None = None
    block_succ: tuple[int, ...] = ()
    instr_idx: int | None = None


@dataclass(frozen=True)
class _DivideCondition:
    mul_index: int
    mul_reg: tuple[str, int]
    quotient_reg: tuple[str, int]
    branch_index: int


def detect_divide_rematerialization_ceiling(
    *,
    function: str,
    expected_asm_text: str | None,
    current_pcdump_text: str | None = None,
    current_asm_lines: list[str] | None = None,
) -> dict | None:
    """Detect target rematerialization vs current CSE for signed magic divides.

    This intentionally recognizes a narrow class: the target reuses the
    `mulhw` result but recomputes the signed quotient in the branch body, while
    the current compile reuses the already value-numbered quotient at `xoris`.
    """
    expected_insts = _expected_instructions(function, expected_asm_text)
    target = _find_target_rematerialized_divide(expected_insts)
    if target is None:
        return None

    current_insts = _current_instructions(
        function=function,
        current_pcdump_text=current_pcdump_text,
        current_asm_lines=current_asm_lines,
    )
    current = _find_current_cse_divide(current_insts)
    if current is None:
        return None

    return {
        "status": "intrinsic-value-numbering-ceiling",
        "kind": "signed-magic-divide-rematerialization",
        "confidence": "high",
        "operator": "signed-magic-divide",
        "source_lever_status": "no-current-C-source-lever",
        "target": {
            "rematerialized_quotient": True,
            "mul_reg": _format_reg(target["mul_reg"]),
            "quotient_reg": _format_reg(target["quotient_reg"]),
        },
        "current": {
            "cse_quotient_reused": True,
            "mul_reg": _format_reg(current["mul_reg"]),
            "quotient_reg": _format_reg(current["quotient_reg"]),
        },
        "evidence": {
            "target_branch_index": target["branch_index"],
            "target_then_srawi_count": target["then_srawi_count"],
            "current_branch_index": current["branch_index"],
            "current_then_srawi_count": current["then_srawi_count"],
            "current_xoris_index": current["xoris_index"],
        },
        "recommendation": (
            "bank this as a value-numbering ceiling unless a new semantic "
            "source-transform family is added; allocator force-* probes cannot "
            "add the missing rematerialization instructions"
        ),
    }


def _expected_instructions(
    function: str,
    expected_asm_text: str | None,
) -> list[_Inst]:
    if not expected_asm_text:
        return []
    asm_function = extract_function(expected_asm_text, function)
    if asm_function is not None:
        return [
            _Inst(
                opcode=instr.opcode,
                operands=instr.operands,
                regs=tuple(instr.regs),
                instr_idx=index,
            )
            for index, instr in enumerate(asm_function.instructions)
        ]
    if _FULL_ASM_FN_RE.search(expected_asm_text):
        return []
    return _parse_loose_asm_lines(expected_asm_text.splitlines())


def _current_instructions(
    *,
    function: str,
    current_pcdump_text: str | None,
    current_asm_lines: list[str] | None,
) -> list[_Inst]:
    if current_pcdump_text:
        functions = parse_pcdump(current_pcdump_text, function=function)
        if functions:
            selected = _select_value_numbering_pass(functions[0])
            if selected is not None:
                return _from_pcdump_pass(selected)
    if current_asm_lines:
        return _parse_loose_asm_lines(current_asm_lines)
    return []


def _select_value_numbering_pass(fn: Function) -> Pass | None:
    for pass_ in fn.passes:
        if pass_.name == "BEFORE REGISTER COLORING":
            return pass_
    return fn.last_precolor_pass()


def _from_pcdump_pass(pass_: Pass) -> list[_Inst]:
    out: list[_Inst] = []
    ordinal = 0
    for block in pass_.blocks:
        for instr_idx, instr in enumerate(block.instructions):
            out.append(_from_pcdump_instruction(
                instr,
                block_idx=block.index,
                block_succ=tuple(block.succ),
                instr_idx=instr_idx,
                ordinal=ordinal,
            ))
            ordinal += 1
    return out


def _from_pcdump_instruction(
    instr: Instruction,
    *,
    block_idx: int,
    block_succ: tuple[int, ...],
    instr_idx: int,
    ordinal: int,
) -> _Inst:
    return _Inst(
        opcode=instr.opcode,
        operands=instr.operands,
        regs=tuple(instr.regs),
        block_idx=block_idx,
        block_succ=block_succ,
        instr_idx=ordinal if block_idx is None else instr_idx,
    )


def _parse_loose_asm_lines(lines: Iterable[str]) -> list[_Inst]:
    out: list[_Inst] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith(".") or line.startswith("<"):
            continue
        line = _ASM_COMMENT_RE.sub("", line).strip()
        line = _CHECKDIFF_PREFIX_RE.sub("", line).strip()
        line = _CHECKDIFF_BYTES_RE.sub("", line).strip()
        line = _CHECKDIFF_WORD_BYTES_RE.sub("", line).strip()
        if not line or line.startswith(".") or line.endswith(":"):
            continue
        parts = line.split(None, 1)
        if not parts:
            continue
        opcode = parts[0]
        operands = parts[1] if len(parts) > 1 else ""
        regs = tuple((kind, int(num)) for kind, num in _REG_RE.findall(operands))
        out.append(_Inst(opcode=opcode, operands=operands, regs=regs, instr_idx=len(out)))
    return out


def _find_target_rematerialized_divide(insts: list[_Inst]) -> dict | None:
    for condition in _iter_divide_conditions(insts):
        remat = _then_rematerialization_evidence(insts, condition)
        if remat is None:
            continue
        return {
            "mul_reg": condition.mul_reg,
            "quotient_reg": condition.quotient_reg,
            "branch_index": condition.branch_index,
            **remat,
        }
    return None


def _find_current_cse_divide(insts: list[_Inst]) -> dict | None:
    for condition in _iter_divide_conditions(insts):
        reuse = _then_cse_reuse_evidence(insts, condition)
        if reuse is None:
            continue
        return {
            "mul_reg": condition.mul_reg,
            "quotient_reg": condition.quotient_reg,
            "branch_index": condition.branch_index,
            **reuse,
        }
    return None


def _iter_divide_conditions(insts: list[_Inst]) -> Iterable[_DivideCondition]:
    for mul_index, instr in enumerate(insts):
        if instr.opcode != "mulhw":
            continue
        mul_reg = _dest_reg(instr)
        if mul_reg is None:
            continue
        condition = _find_divide_condition_after_mul(insts, mul_index, mul_reg)
        if condition is not None:
            yield condition


def _find_divide_condition_after_mul(
    insts: list[_Inst],
    mul_index: int,
    mul_reg: tuple[str, int],
) -> _DivideCondition | None:
    limit = min(len(insts), mul_index + 12)
    for srawi_index in range(mul_index + 1, limit):
        srawi = insts[srawi_index]
        if srawi.opcode != "srawi" or _source_reg(srawi) != mul_reg:
            continue
        quotient_part = _dest_reg(srawi)
        if quotient_part is None:
            continue
        sign_reg = _find_sign_adjust_reg(insts, srawi_index + 1, quotient_part)
        if sign_reg is None:
            continue
        add_index, quotient_reg = _find_quotient_add(
            insts,
            srawi_index + 1,
            quotient_part,
            sign_reg,
            require_condition_test=True,
        )
        if add_index is None or quotient_reg is None:
            continue
        branch_index = _find_branch(insts, add_index + 1, max_index=add_index + 5)
        if branch_index is None:
            continue
        return _DivideCondition(
            mul_index=mul_index,
            mul_reg=mul_reg,
            quotient_reg=quotient_reg,
            branch_index=branch_index,
        )
    return None


def _find_sign_adjust_reg(
    insts: list[_Inst],
    start: int,
    quotient_part: tuple[str, int],
) -> tuple[str, int] | None:
    for index in range(start, min(len(insts), start + 4)):
        instr = insts[index]
        if instr.opcode not in {"srwi", "rlwinm"}:
            continue
        if _source_reg(instr) != quotient_part:
            continue
        return _dest_reg(instr)
    return None


def _find_quotient_add(
    insts: list[_Inst],
    start: int,
    quotient_part: tuple[str, int],
    sign_reg: tuple[str, int],
    *,
    require_condition_test: bool = False,
) -> tuple[int | None, tuple[str, int] | None]:
    for index in range(start, min(len(insts), start + 5)):
        instr = insts[index]
        if instr.opcode not in {"add", "add."}:
            continue
        if require_condition_test and instr.opcode != "add.":
            if not (instr.opcode == "add" and instr.block_idx is not None):
                continue
        sources = set(_source_regs(instr))
        if quotient_part in sources and sign_reg in sources:
            return index, _dest_reg(instr)
    return None, None


def _then_rematerialization_evidence(
    insts: list[_Inst],
    condition: _DivideCondition,
) -> dict | None:
    start = condition.branch_index + 1
    limit = min(len(insts), start + 14)
    then_srawi_count = 0
    for index in range(start, limit):
        instr = insts[index]
        if not _is_branch_body_instr(insts, condition, index):
            continue
        if instr.opcode == "srawi" and _source_reg(instr) == condition.mul_reg:
            then_srawi_count += 1
            quotient_part = _dest_reg(instr)
            if quotient_part is None:
                continue
            sign_reg = _find_sign_adjust_reg(insts, index + 1, quotient_part)
            if sign_reg is None:
                continue
            add_index, quotient_reg = _find_quotient_add(
                insts,
                index + 1,
                quotient_part,
                sign_reg,
            )
            if add_index is None or quotient_reg is None:
                continue
            xoris_index = _find_xoris_using(
                insts,
                add_index + 1,
                quotient_reg,
                max_index=index + 10,
            )
            if xoris_index is not None:
                return {
                    "then_srawi_count": then_srawi_count,
                    "xoris_index": xoris_index,
                }
    return None


def _then_cse_reuse_evidence(
    insts: list[_Inst],
    condition: _DivideCondition,
) -> dict | None:
    start = condition.branch_index + 1
    limit = min(len(insts), start + 14)
    then_srawi_count = 0
    for index in range(start, limit):
        instr = insts[index]
        if not _is_branch_body_instr(insts, condition, index):
            continue
        if instr.opcode == "srawi" and _source_reg(instr) == condition.mul_reg:
            then_srawi_count += 1
        if not _is_xoris_float_bias(instr):
            continue
        if _source_reg(instr) != condition.quotient_reg:
            continue
        if then_srawi_count == 0:
            return {
                "then_srawi_count": 0,
                "xoris_index": index,
            }
    return None


def _find_xoris_using(
    insts: list[_Inst],
    start: int,
    reg: tuple[str, int],
    *,
    max_index: int,
) -> int | None:
    for index in range(start, min(len(insts), max_index)):
        instr = insts[index]
        if _is_xoris_float_bias(instr) and _source_reg(instr) == reg:
            return index
    return None


def _find_branch(insts: list[_Inst], start: int, *, max_index: int) -> int | None:
    for index in range(start, min(len(insts), max_index)):
        if _is_conditional_branch(insts[index]):
            return index
    return None


def _is_branch_body_instr(
    insts: list[_Inst],
    condition: _DivideCondition,
    index: int,
) -> bool:
    branch_block = insts[condition.branch_index].block_idx
    instr_block = insts[index].block_idx
    fallthrough_block = _pcdump_fallthrough_block(insts[condition.branch_index])
    if fallthrough_block is not None:
        return instr_block == fallthrough_block
    return branch_block is None or instr_block is None or instr_block != branch_block


def _pcdump_fallthrough_block(branch: _Inst) -> int | None:
    if branch.block_idx is None or not branch.block_succ:
        return None
    target_blocks = {
        int(block_num)
        for block_num in re.findall(r"\bB(\d+)\b", branch.operands)
    }
    if not target_blocks:
        return None
    fallthrough_blocks = [
        block_idx for block_idx in branch.block_succ
        if block_idx not in target_blocks
    ]
    if len(fallthrough_blocks) != 1:
        return None
    return fallthrough_blocks[0]


def _is_xoris_float_bias(instr: _Inst) -> bool:
    if instr.opcode != "xoris":
        return False
    operands = [part.strip().lower() for part in instr.operands.split(",")]
    return len(operands) >= 3 and operands[2] in {"0x8000", "32768"}


def _dest_reg(instr: _Inst) -> tuple[str, int] | None:
    if not instr.regs:
        return None
    if instr.opcode.startswith(("st", "psq_st", "b", "cmp")):
        return None
    return instr.regs[0]


def _source_reg(instr: _Inst) -> tuple[str, int] | None:
    regs = _source_regs(instr)
    return regs[0] if regs else None


def _source_regs(instr: _Inst) -> tuple[tuple[str, int], ...]:
    if len(instr.regs) < 2:
        return ()
    return instr.regs[1:]


def _is_conditional_branch(instr: _Inst) -> bool:
    return (
        instr.opcode.startswith("b")
        and instr.opcode not in _UNCONDITIONAL_BRANCH_OPCODES
    )


def _format_reg(reg: tuple[str, int]) -> str:
    return f"{reg[0]}{reg[1]}"
