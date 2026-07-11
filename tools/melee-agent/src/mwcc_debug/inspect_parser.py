"""Snapshot and conservative semantic parsing for mwcc-inspect output."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

_FUNCTION_RE = re.compile(r"^FUNCTION:\s+(\S+)\s*$")
_SECTION_NAMES = {
    "LOCAL VARIABLES": "Frontend",
    "STATEMENTS": "Frontend",
    "ENODES": "Frontend",
    "OBJOBJECTS": "Frontend",
    "OPTIMIZED IR": "Mid-end",
    "MID-END IR": "Mid-end",
}
_STATEMENT_RE = re.compile(r"^:(?P<meta>-?\d+)\s+(?P<expression>.+)$")
_ENODE_RE = re.compile(r"^(?P<indent>\s*)\[(?P<opcode>E[A-Z0-9_]+)\]\s*(?P<expression>.*)$")
_OBJOBJECT_RE = re.compile(
    r"^\s*-> ObjObject @ (?P<address>0x[0-9A-Fa-f]+):\s*"
    r"(?P<name>.*?)\s+\(DataType:\s*(?P<data_type>[^,]+),\s*Type:\s*(?P<type_text>.*)\)$"
)
_LOCAL_ORDER_RE = re.compile(r"^\s*\[(?P<order>\d+)\]\s+(?P<address>0x[0-9A-Fa-f]+)\s+(?P<name>\S+)\s*$")
_AUXILIARY_TREE_RE = re.compile(r"^(?:Function|Arg \d+|Constituent \d*|Condition|True branch|False branch):$")

# Names emitted by the inspected MWCC expression-node enum. Keeping an explicit
# vocabulary makes a new producer syntax fail closed instead of inventing a
# relationship for a node shape this parser has never handled.
_SUPPORTED_ENODE_OPCODES = frozenset(
    {
        "EADD",
        "EADDASS",
        "EADDV",
        "EAND",
        "EANDASS",
        "EASS",
        "EBCLR",
        "EBINNOT",
        "EBITFIELD",
        "EBSET",
        "EBTST",
        "ECOMMA",
        "ECOND",
        "ECONDASS",
        "EDEFINE",
        "EDIV",
        "EDIVASS",
        "EEQU",
        "EFLOATCONST",
        "EFORCELOAD",
        "EFUNCCALL",
        "EFUNCCALLP",
        "EGREATER",
        "EGREATEREQU",
        "EINDIRECT",
        "EINITTRYCATCH",
        "EINTCONST",
        "ELABEL",
        "ELAND",
        "ELESS",
        "ELESSEQU",
        "ELOGNOT",
        "ELOR",
        "EMODASS",
        "EMODULO",
        "EMONMIN",
        "EMUL",
        "EMULASS",
        "EMULV",
        "ENOTEQU",
        "ENULLCHECK",
        "EOBJREF",
        "EOR",
        "EORASS",
        "EPMODULO",
        "EPOSTDEC",
        "EPOSTINC",
        "EPRECOMP",
        "EPREDEC",
        "EPREINC",
        "EREUSE",
        "EROTL",
        "EROTR",
        "ESHL",
        "ESHLASS",
        "ESHR",
        "ESHRASS",
        "ESTRINGCONST",
        "ESUB",
        "ESUBASS",
        "ESUBV",
        "ETEMP",
        "ETYPCON",
        "EVECTORCONST",
        "EXOR",
        "EXORASS",
    }
)


@dataclass(frozen=True, slots=True)
class InspectSnapshot:
    name: str
    text: str


@dataclass(frozen=True, slots=True)
class InspectObjObject:
    address: str
    name: str
    data_type: str
    type_text: str
    first_appearance_order: int | None
    address_order: int | None
    raw_start: int
    raw_end: int


@dataclass(frozen=True, slots=True)
class InspectENode:
    node_id: str
    opcode: str
    expression: str
    depth: int
    parent_id: str | None
    referenced_object_addresses: tuple[str, ...]
    raw_start: int
    raw_end: int


@dataclass(frozen=True, slots=True)
class InspectStatement:
    statement_id: str
    source_line: int | None
    expression: str
    root_enode_id: str | None
    raw_start: int
    raw_end: int


@dataclass(frozen=True, slots=True)
class InspectFunction:
    name: str
    statements: tuple[InspectStatement, ...]
    enodes: tuple[InspectENode, ...]
    objobjects: Mapping[str, InspectObjObject]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _InspectLine:
    number: int
    content: str
    raw_start: int
    raw_end: int


@dataclass(slots=True)
class _StatementBuilder:
    statement_id: str
    source_line: int
    expression: str
    root_enode_id: str | None
    raw_start: int
    raw_end: int


@dataclass(slots=True)
class _ENodeBuilder:
    node_id: str
    opcode: str
    expression: str
    depth: int
    parent_id: str | None
    referenced_object_addresses: set[str]
    raw_start: int
    raw_end: int


def _inspect_lines(text: str) -> list[_InspectLine]:
    result: list[_InspectLine] = []
    byte_offset = 0
    for number, raw_line in enumerate(text.splitlines(keepends=True), start=1):
        content = raw_line.rstrip("\r\n")
        raw_size = len(raw_line.encode("utf-8"))
        content_size = len(content.encode("utf-8"))
        result.append(
            _InspectLine(
                number=number,
                content=content,
                raw_start=byte_offset,
                raw_end=byte_offset + content_size,
            )
        )
        byte_offset += raw_size
    return result


def _function_bounds(lines: list[_InspectLine], function: str) -> tuple[int, int] | None:
    start: int | None = None
    for idx, line in enumerate(lines):
        match = _FUNCTION_RE.match(line.content.strip())
        if match is None:
            continue
        if match.group(1) == function and start is None:
            start = idx + 1
            continue
        if start is not None:
            return start, idx
    if start is None:
        return None
    return start, len(lines)


def _slice_function(text: str, function: str) -> list[str]:
    lines = _inspect_lines(text)
    bounds = _function_bounds(lines, function)
    if bounds is None:
        return []
    start, end = bounds
    return [line.content for line in lines[start:end]]


def _merge_objobject(
    objobjects: dict[str, InspectObjObject],
    *,
    address: str,
    name: str,
    raw_start: int,
    raw_end: int,
    data_type: str = "",
    type_text: str = "",
    first_appearance_order: int | None = None,
    address_order: int | None = None,
) -> None:
    current = objobjects.get(address)
    if current is None:
        objobjects[address] = InspectObjObject(
            address=address,
            name=name,
            data_type=data_type,
            type_text=type_text,
            first_appearance_order=first_appearance_order,
            address_order=address_order,
            raw_start=raw_start,
            raw_end=raw_end,
        )
        return
    objobjects[address] = replace(
        current,
        name=current.name or name,
        data_type=current.data_type or data_type,
        type_text=current.type_text or type_text,
        first_appearance_order=(
            current.first_appearance_order if current.first_appearance_order is not None else first_appearance_order
        ),
        address_order=current.address_order if current.address_order is not None else address_order,
        raw_start=min(current.raw_start, raw_start),
        raw_end=max(current.raw_end, raw_end),
    )


def parse_inspect_function(text: str, function: str) -> InspectFunction | None:
    """Parse one inspector function without guessing at unsupported syntax."""

    lines = _inspect_lines(text)
    bounds = _function_bounds(lines, function)
    if bounds is None:
        return None
    start, end = bounds

    statements: list[_StatementBuilder] = []
    enodes: list[_ENodeBuilder] = []
    enode_by_id: dict[str, _ENodeBuilder] = {}
    objobjects: dict[str, InspectObjObject] = {}
    warnings: list[str] = []
    stack: list[tuple[int, str]] = []
    current_statement: _StatementBuilder | None = None
    in_statements = False
    table_kind: str | None = None
    unsupported_indent: int | None = None

    for line in lines[start:end]:
        stripped = line.content.strip()
        upper = stripped.upper()

        if upper == "STATEMENTS (IR):" or upper == "STATEMENTS":
            in_statements = True
            table_kind = None
            continue
        if upper.startswith("LOCAL VARIABLES (FIRST APPEARANCE ORDER"):
            in_statements = False
            table_kind = "first"
            stack.clear()
            unsupported_indent = None
            continue
        if upper.startswith("LOCAL VARIABLES (SORTED BY OBJOBJECT ADDRESS"):
            in_statements = False
            table_kind = "address"
            stack.clear()
            unsupported_indent = None
            continue

        if table_kind is not None:
            table_match = _LOCAL_ORDER_RE.match(line.content)
            if table_match is not None:
                order = int(table_match.group("order"))
                _merge_objobject(
                    objobjects,
                    address=table_match.group("address"),
                    name=table_match.group("name"),
                    raw_start=line.raw_start
                    + len(line.content[: len(line.content) - len(line.content.lstrip())].encode("utf-8")),
                    raw_end=line.raw_end,
                    first_appearance_order=order if table_kind == "first" else None,
                    address_order=order if table_kind == "address" else None,
                )
            continue

        if not in_statements:
            continue

        if not stripped or set(stripped) == {"-"}:
            continue

        statement_match = _STATEMENT_RE.match(line.content)
        if statement_match is not None:
            stack.clear()
            unsupported_indent = None
            current_statement = _StatementBuilder(
                statement_id=f"statement-{len(statements)}",
                source_line=int(statement_match.group("meta")),
                expression=statement_match.group("expression"),
                root_enode_id=None,
                raw_start=line.raw_start,
                raw_end=line.raw_end,
            )
            statements.append(current_statement)
            continue

        leading_text = line.content[: len(line.content) - len(line.content.lstrip())]
        line_indent = len(leading_text.expandtabs(8))
        if unsupported_indent is not None:
            if line_indent > unsupported_indent:
                continue
            unsupported_indent = None

        enode_match = _ENODE_RE.match(line.content)
        if enode_match is not None:
            indent_text = enode_match.group("indent")
            indent = len(indent_text.expandtabs(8))
            while stack and stack[-1][0] >= indent:
                stack.pop()

            opcode = enode_match.group("opcode")
            if opcode not in _SUPPORTED_ENODE_OPCODES:
                warnings.append(f"line {line.number}: unsupported inspector syntax: {stripped}")
                unsupported_indent = indent
                continue

            node_id = f"enode-{len(enodes)}"
            parent_id = stack[-1][1] if stack else None
            node = _ENodeBuilder(
                node_id=node_id,
                opcode=opcode,
                expression=enode_match.group("expression"),
                depth=len(stack),
                parent_id=parent_id,
                referenced_object_addresses=set(),
                raw_start=line.raw_start + len(indent_text.encode("utf-8")),
                raw_end=line.raw_end,
            )
            enodes.append(node)
            enode_by_id[node_id] = node
            stack.append((indent, node_id))
            if current_statement is not None:
                if current_statement.root_enode_id is None:
                    current_statement.root_enode_id = node_id
                current_statement.raw_end = line.raw_end
            continue

        objobject_match = _OBJOBJECT_RE.match(line.content)
        if objobject_match is not None:
            address = objobject_match.group("address")
            leading = len(line.content) - len(line.content.lstrip())
            syntax_start = line.raw_start + len(line.content[:leading].encode("utf-8"))
            _merge_objobject(
                objobjects,
                address=address,
                name=objobject_match.group("name"),
                data_type=objobject_match.group("data_type").strip(),
                type_text=objobject_match.group("type_text").strip(),
                raw_start=syntax_start,
                raw_end=line.raw_end,
            )
            owner = next(
                (
                    enode_by_id[node_id]
                    for _indent, node_id in reversed(stack)
                    if enode_by_id[node_id].opcode == "EOBJREF"
                ),
                None,
            )
            if owner is None:
                warnings.append(f"line {line.number}: ObjObject has no preceding EOBJREF: {stripped}")
            else:
                owner.referenced_object_addresses.add(address)
                owner.raw_end = max(owner.raw_end, line.raw_end)
            if current_statement is not None:
                current_statement.raw_end = line.raw_end
            continue

        if _AUXILIARY_TREE_RE.match(stripped):
            continue
        if stripped.startswith("Type:"):
            continue
        warnings.append(f"line {line.number}: unsupported inspector syntax: {stripped}")
        unsupported_indent = line_indent

    for node in reversed(enodes):
        if node.parent_id is None:
            continue
        parent = enode_by_id[node.parent_id]
        parent.referenced_object_addresses.update(node.referenced_object_addresses)
        parent.raw_end = max(parent.raw_end, node.raw_end)

    children_by_parent: dict[str | None, list[_ENodeBuilder]] = {}
    for node in enodes:
        children_by_parent.setdefault(node.parent_id, []).append(node)

    ordered_enodes: list[_ENodeBuilder] = []

    def append_postorder(node: _ENodeBuilder) -> None:
        for child in children_by_parent.get(node.node_id, ()):
            append_postorder(child)
        ordered_enodes.append(node)

    for root in children_by_parent.get(None, ()):
        append_postorder(root)

    immutable_enodes = tuple(
        InspectENode(
            node_id=node.node_id,
            opcode=node.opcode,
            expression=node.expression,
            depth=node.depth,
            parent_id=node.parent_id,
            referenced_object_addresses=tuple(sorted(node.referenced_object_addresses)),
            raw_start=node.raw_start,
            raw_end=node.raw_end,
        )
        for node in ordered_enodes
    )
    immutable_statements = tuple(
        InspectStatement(
            statement_id=statement.statement_id,
            source_line=statement.source_line,
            expression=statement.expression,
            root_enode_id=statement.root_enode_id,
            raw_start=statement.raw_start,
            raw_end=statement.raw_end,
        )
        for statement in statements
    )
    return InspectFunction(
        name=function,
        statements=immutable_statements,
        enodes=immutable_enodes,
        objobjects=MappingProxyType(dict(sorted(objobjects.items()))),
        warnings=tuple(warnings),
    )


def parse_inspect_snapshots(text: str, *, function: str) -> list[InspectSnapshot]:
    lines = _slice_function(text, function)
    snapshots: list[InspectSnapshot] = []
    current_name: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_name, current_lines
        if current_name is not None:
            snapshots.append(InspectSnapshot(current_name, "\n".join(current_lines).strip()))
        current_name = None
        current_lines = []

    for raw in lines:
        stripped = raw.strip()
        upper = stripped.upper()
        if upper in _SECTION_NAMES:
            flush()
            current_name = f"{_SECTION_NAMES[upper]}: {upper}"
            current_lines = [stripped]
            continue
        if current_name is not None:
            current_lines.append(raw.rstrip())
    flush()
    return [s for s in snapshots if s.text]
