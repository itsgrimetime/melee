"""Tree-sitter source-span helpers for source-shape suggestions."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import ast_walker


@dataclass(frozen=True)
class StatementSpan:
    text: str
    byte_range: tuple[int, int]
    line_range: tuple[int, int]
    scope_path: tuple[str, ...]
    scope_byte_range: tuple[int, int]
    kind: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]


@dataclass(frozen=True)
class SpanGroup:
    spans: tuple[StatementSpan, ...]
    reason: str

    @property
    def byte_range(self) -> tuple[int, int]:
        return (self.spans[0].byte_range[0], self.spans[-1].byte_range[1])

    @property
    def line_range(self) -> tuple[int, int]:
        return (self.spans[0].line_range[0], self.spans[-1].line_range[1])

    @property
    def scope_path(self) -> tuple[str, ...]:
        return self.spans[0].scope_path


@dataclass(frozen=True)
class CallArgumentSpan:
    function_name: str
    call_name: str
    text: str
    byte_range: tuple[int, int]
    line_range: tuple[int, int]
    scope_path: tuple[str, ...]
    statement: StatementSpan


def _node_text(source_bytes: bytes, node) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _line_col(source_bytes: bytes, offset: int) -> tuple[int, int]:
    line = 1
    col = 0
    for b in source_bytes[:offset]:
        if b == 0x0A:
            line += 1
            col = 0
        else:
            col += 1
    return line, col


def _find_function_node(source: str, fn_name: str):
    ast_walker._check_ts()
    tree = ast_walker._parse_cached(source, path=None)
    source_bytes = source.encode("utf-8")
    return ast_walker._find_function_definition(tree.root_node, source_bytes, fn_name)


def _direct_statement_nodes(body_node) -> list:
    out = []
    stack: list[tuple[object, tuple[str, ...], tuple[int, int]]] = []
    stack.append((body_node, (), (body_node.start_byte, body_node.end_byte)))
    while stack:
        node, _scope, _scope_range = stack.pop()
        for child in reversed(node.children):
            if child.type == "compound_statement":
                stack.append((child, (), (child.start_byte, child.end_byte)))
                continue
            if child.type in {
                "declaration",
                "expression_statement",
                "return_statement",
                "goto_statement",
                "labeled_statement",
                "case_statement",
                "break_statement",
                "continue_statement",
            }:
                out.append(child)
            for grand in reversed(child.children):
                if grand.type == "compound_statement":
                    stack.append((grand, (), (grand.start_byte, grand.end_byte)))
    return sorted(out, key=lambda n: n.start_byte)


def _scope_for_node(source: str, fn_name: str, node) -> tuple[tuple[str, ...], tuple[int, int]]:
    decls = ast_walker.walk_function(source, fn_name, path=None)
    best_path = (fn_name,)
    best_range = (0, len(source.encode("utf-8")))
    for decl in decls:
        start, end = decl.scope_byte_range
        if start <= node.start_byte <= node.end_byte <= end:
            if len(decl.scope_path) >= len(best_path):
                best_path = decl.scope_path
                best_range = decl.scope_byte_range
    return best_path, best_range


def _identifier_names(node, source_bytes: bytes) -> list[str]:
    names: list[str] = []
    stack = [node]
    while stack:
        cur = stack.pop()
        if cur.type == "identifier":
            names.append(_node_text(source_bytes, cur))
        for child in reversed(cur.children):
            stack.append(child)
    return list(dict.fromkeys(names))


def _read_write_sets(node, source_bytes: bytes) -> tuple[tuple[str, ...], tuple[str, ...]]:
    names = _identifier_names(node, source_bytes)
    text = _node_text(source_bytes, node)
    writes: list[str] = []
    if node.type == "expression_statement" and "=" in text and "==" not in text:
        lhs = text.split("=", 1)[0]
        lhs_names = [name for name in names if name in lhs]
        if lhs_names:
            writes.append(lhs_names[0])
    reads = [name for name in names if name not in writes]
    return tuple(reads), tuple(writes)


def list_statement_spans(source: str, fn_name: str) -> list[StatementSpan]:
    fn_node = _find_function_node(source, fn_name)
    if fn_node is None:
        return []
    body = fn_node.child_by_field_name("body")
    if body is None:
        return []
    source_bytes = source.encode("utf-8")
    spans: list[StatementSpan] = []
    for node in _direct_statement_nodes(body):
        line_start, _ = _line_col(source_bytes, node.start_byte)
        line_end, _ = _line_col(source_bytes, node.end_byte)
        scope_path, scope_range = _scope_for_node(source, fn_name, node)
        reads, writes = _read_write_sets(node, source_bytes)
        spans.append(StatementSpan(
            text=_node_text(source_bytes, node).strip(),
            byte_range=(node.start_byte, node.end_byte),
            line_range=(line_start, line_end),
            scope_path=scope_path,
            scope_byte_range=scope_range,
            kind=node.type,
            reads=reads,
            writes=writes,
        ))
    return spans


def reject_reason_for_span_group(spans: list[StatementSpan]) -> Optional[str]:
    if not spans:
        return "span is empty"
    first_scope = spans[0].scope_path
    if any(span.scope_path != first_scope for span in spans):
        return "span crosses scope boundaries"
    text = "\n".join(span.text for span in spans)
    if "goto " in text:
        return "span contains goto"
    if any(span.kind in {"labeled_statement", "case_statement"} for span in spans):
        return "span contains label or case"
    return None


def _call_names(span: StatementSpan) -> tuple[str, ...]:
    names: list[str] = []
    text = span.text
    for name in span.reads:
        if re.search(r"\b" + re.escape(name) + r"\(", text):
            names.append(name)
    return tuple(names)


def find_repeated_call_groups(
    source: str,
    fn_name: str,
    max_span_statements: int = 6,
) -> list[SpanGroup]:
    spans = list_statement_spans(source, fn_name)
    groups: list[SpanGroup] = []
    seen_shapes: dict[tuple[str, ...], list[StatementSpan]] = {}
    for width in range(1, max_span_statements + 1):
        for idx in range(0, len(spans) - width + 1):
            chunk = spans[idx:idx + width]
            if reject_reason_for_span_group(chunk) is not None:
                continue
            shape = tuple(name for span in chunk for name in _call_names(span))
            if not shape:
                continue
            if shape in seen_shapes:
                prior = seen_shapes[shape]
                groups.append(SpanGroup(
                    spans=tuple(prior),
                    reason=f"repeated call shape: {', '.join(shape)}",
                ))
                groups.append(SpanGroup(
                    spans=tuple(chunk),
                    reason=f"repeated call shape: {', '.join(shape)}",
                ))
            else:
                seen_shapes[shape] = chunk
    unique: dict[tuple[int, int], SpanGroup] = {}
    for group in groups:
        unique[group.byte_range] = group
    return list(unique.values())


def find_call_argument_spans(
    source: str,
    fn_name: str,
    call_name: str,
) -> list[CallArgumentSpan]:
    fn_node = _find_function_node(source, fn_name)
    if fn_node is None:
        return []
    source_bytes = source.encode("utf-8")
    statements = list_statement_spans(source, fn_name)
    out: list[CallArgumentSpan] = []
    stack = [fn_node]
    while stack:
        node = stack.pop()
        if node.type == "call_expression":
            fn_child = node.child_by_field_name("function")
            args = node.child_by_field_name("arguments")
            if fn_child is not None and args is not None:
                if _node_text(source_bytes, fn_child) == call_name:
                    statement = next(
                        (s for s in statements if s.byte_range[0] <= node.start_byte <= node.end_byte <= s.byte_range[1]),
                        None,
                    )
                    if statement is not None:
                        for child in args.children:
                            if child.type in {"(", ")", ","}:
                                continue
                            line_start, _ = _line_col(source_bytes, child.start_byte)
                            line_end, _ = _line_col(source_bytes, child.end_byte)
                            out.append(CallArgumentSpan(
                                function_name=fn_name,
                                call_name=call_name,
                                text=_node_text(source_bytes, child).strip(),
                                byte_range=(child.start_byte, child.end_byte),
                                line_range=(line_start, line_end),
                                scope_path=statement.scope_path,
                                statement=statement,
                            ))
        for child in node.children:
            stack.append(child)
    return sorted(out, key=lambda a: a.byte_range)
