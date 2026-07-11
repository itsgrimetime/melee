from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import zip_longest

_INSTRUCTION_RE = re.compile(
    r"^\+(?P<offset>[0-9A-Fa-f]+):\s+"
    r"(?:[0-9A-Fa-f]{2}\s+){3}[0-9A-Fa-f]{2}\s+"
    r"(?P<opcode>[A-Za-z][A-Za-z0-9_.+-]*)"
    r"(?:\s+(?P<operands>.*?))?\s*$"
)
_SELF_RELATIVE_TARGET_RE = re.compile(r"<[^>]+\+0x(?P<offset>[0-9A-Fa-f]+)>")
_NUMERIC_TARGET_RE = re.compile(r"(?:^|,\s*)(?:0x)?(?P<offset>[0-9A-Fa-f]+)\s*$")
_TERMINALS = {"blr", "bctr", "rfi"}
_DIRECT_CONDITIONAL_BRANCH_BASES = frozenset(
    {
        "bc",
        "beq",
        "bf",
        "bge",
        "bgt",
        "ble",
        "blt",
        "bne",
        "bng",
        "bnl",
        "bns",
        "bnu",
        "bso",
        "bt",
        "bun",
        "bdnz",
        "bdnzf",
        "bdnzt",
        "bdz",
        "bdzf",
        "bdzt",
    }
)
_DIRECT_CONDITIONAL_CALLS = frozenset(
    f"{base}{suffix}" for base in _DIRECT_CONDITIONAL_BRANCH_BASES for suffix in ("l", "la")
)


@dataclass(frozen=True)
class OpcodeGraph:
    nodes: tuple[tuple[str, ...], ...]
    edges: frozenset[tuple[int, int]]


@dataclass(frozen=True)
class _Instruction:
    offset: int
    opcode: str
    operands: str


def _without_prediction_hint(opcode: str) -> str:
    if opcode.endswith(("+", "-")):
        return opcode[:-1]
    return opcode


def _is_branch_and_link(opcode: str) -> bool:
    if not opcode.startswith("b"):
        return False

    # Register-target forms encode LK as a final "l" after the target name.
    if opcode.endswith(("ctrl", "lrl")):
        return True
    if opcode.endswith(("ctr", "lr")):
        return False

    # Direct aliases add LK to a complete base mnemonic. Explicit composition
    # avoids treating bases such as `bnl` and absolute `bnla` as link forms.
    return opcode in {"bl", "bla"} or opcode in _DIRECT_CONDITIONAL_CALLS


def _branch_kind(opcode: str) -> str | None:
    unhinted = _without_prediction_hint(opcode)
    if _is_branch_and_link(unhinted):
        return None
    if unhinted in _TERMINALS:
        return "terminal"
    if unhinted in {"b", "ba"}:
        return "unconditional-direct"

    if unhinted.startswith("b") and unhinted.endswith(("lr", "ctr")):
        return "conditional-indirect"
    if unhinted.startswith("b"):
        return "conditional-direct"
    return None


def _branch_target(operands: str) -> int | None:
    match = _SELF_RELATIVE_TARGET_RE.search(operands)
    if match is None:
        match = _NUMERIC_TARGET_RE.search(operands)
    if match is None:
        return None
    return int(match.group("offset"), 16)


def _parse_instructions(lines: list[str]) -> list[_Instruction]:
    parsed: list[_Instruction] = []
    for line in lines:
        match = _INSTRUCTION_RE.match(line.strip())
        if match is None:
            continue
        opcode = match.group("opcode").lower()
        if opcode.startswith("r_ppc_") or opcode == ".reloc":
            continue
        parsed.append(
            _Instruction(
                offset=int(match.group("offset"), 16),
                opcode=opcode,
                operands=(match.group("operands") or "").strip(),
            )
        )

    by_offset: dict[int, _Instruction] = {}
    for instruction in sorted(parsed, key=lambda item: (item.offset, item.opcode, item.operands)):
        by_offset.setdefault(instruction.offset, instruction)
    return list(by_offset.values())


def parse_opcode_graph(lines: list[str]) -> OpcodeGraph:
    instructions = _parse_instructions(lines)
    if not instructions:
        return OpcodeGraph(nodes=(), edges=frozenset())

    offsets = {instruction.offset for instruction in instructions}
    leaders = {instructions[0].offset}
    for index, instruction in enumerate(instructions):
        branch_kind = _branch_kind(instruction.opcode)
        if branch_kind in {"conditional-direct", "unconditional-direct"}:
            target = _branch_target(instruction.operands)
            if target in offsets:
                leaders.add(target)
        if branch_kind is not None and index + 1 < len(instructions):
            leaders.add(instructions[index + 1].offset)

    block_starts = sorted(leaders)
    block_index_by_offset = {offset: index for index, offset in enumerate(block_starts)}
    instruction_blocks: list[list[_Instruction]] = [[] for _ in block_starts]
    block_index = 0
    for instruction in instructions:
        if instruction.offset in block_index_by_offset:
            block_index = block_index_by_offset[instruction.offset]
        instruction_blocks[block_index].append(instruction)

    edges: set[tuple[int, int]] = set()
    for source, block in enumerate(instruction_blocks):
        last = block[-1]
        branch_kind = _branch_kind(last.opcode)
        if branch_kind in {"conditional-direct", "unconditional-direct"}:
            target = _branch_target(last.operands)
            if target in block_index_by_offset:
                edges.add((source, block_index_by_offset[target]))
        if branch_kind in {None, "conditional-direct", "conditional-indirect"}:
            if source + 1 < len(instruction_blocks):
                edges.add((source, source + 1))

    return OpcodeGraph(
        nodes=tuple(tuple(instruction.opcode for instruction in block) for block in instruction_blocks),
        edges=frozenset(edges),
    )


def opcode_graph_distance(
    expected: OpcodeGraph,
    current: OpcodeGraph,
    *,
    structural_status: str,
) -> tuple[int, int]:
    changed_nodes = sum(
        expected_node != current_node
        for expected_node, current_node in zip_longest(expected.nodes, current.nodes, fillvalue=())
    )
    changed_edges = len(expected.edges.symmetric_difference(current.edges))
    if changed_nodes == changed_edges == 0 and structural_status != "structural-match":
        raise ValueError("opcode-structural-contradiction")
    return changed_nodes, changed_edges
