"""Source-transform family: statement_order."""
from __future__ import annotations

import re
from dataclasses import dataclass
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _blank_literals_and_comments, _text_line_records_with_newline


@dataclass(frozen=True)
class _StatementOrderRecord:
    start: int
    end: int
    line_end: int
    line: str
    block_id: int
    reads: tuple[str, ...]
    writes: tuple[str, ...]


_STATEMENT_ORDER_DECL_RE = re.compile(
    r"^(?P<indent>[ \t]+)"
    r"(?P<type>(?:s8|s16|s32|s64|u8|u16|u32|u64|int|short|long|bool|BOOL|f32|f64|float|double))"
    r"\s+"
    r"(?P<name>[A-Za-z_]\w*)"
    r"\s*;\s*$"
)


_STATEMENT_ORDER_ASSIGN_RE = re.compile(
    r"^(?P<indent>[ \t]+)(?P<lhs>[A-Za-z_]\w*)\s*=\s*(?P<rhs>[^;]+);\s*$"
)


_STATEMENT_ORDER_FORBIDDEN_WORDS_RE = re.compile(
    r"\b(?:return|break|continue|goto|case|default|if|else|for|while|switch|do|asm|volatile|fallthrough|preserve\s+order)\b",
    re.IGNORECASE,
)


_STATEMENT_ORDER_LABEL_RE = re.compile(
    r"(?m)^[ \t]*(?:case\b[^:]*:|default\s*:|[A-Za-z_]\w*\s*:)"
)


_STATEMENT_ORDER_CONTROL_FLOW_RE = re.compile(
    r"\b(?:if|else|for|while|switch|do|return|break|continue|goto)\b"
)


_STATEMENT_ORDER_COMMENT_OR_ORDER_NOTE_RE = re.compile(
    r"//|/\*|\*/|\b(?:fallthrough|preserve\s+order)\b",
    re.IGNORECASE,
)


def _statement_order_line_forbidden(line: str) -> bool:
    stripped = line.strip()
    if (
        not stripped
        or stripped.startswith("#")
        or stripped.endswith(":")
        or "//" in line
        or "/*" in line
        or "*/" in line
        or "++" in line
        or "--" in line
        or _STATEMENT_ORDER_FORBIDDEN_WORDS_RE.search(line) is not None
    ):
        return True
    return False


def _statement_order_rhs_reads(rhs: str, locals_in_scope: set[str]) -> tuple[str, ...] | None:
    if any(token in rhs for token in ("->", ".", "[", "]", "*", "&")):
        return None
    reads: list[str] = []
    for name in re.findall(r"\b[A-Za-z_]\w*\b", rhs):
        if name in {"NULL", "true", "false"}:
            continue
        if name not in locals_in_scope:
            return None
        if name not in reads:
            reads.append(name)
    return tuple(reads)


def _statement_order_block_ids(blanked_text: str) -> list[int]:
    block_ids: list[int] = []
    block_stack = [0]
    next_block_id = 1

    for line in blanked_text.splitlines(keepends=True):
        block_ids.append(block_stack[-1])
        for char in line:
            if char == "{":
                block_stack.append(next_block_id)
                next_block_id += 1
            elif char == "}" and len(block_stack) > 1:
                block_stack.pop()

    return block_ids


def _iter_independent_statement_order_anchors(source_text: str, span):
    body_start = span.body_open + 1
    body_inner = source_text[body_start:span.body_close]
    if re.search(r"(?m)^[ \t]*#", body_inner):
        return
    if _STATEMENT_ORDER_LABEL_RE.search(body_inner):
        return
    if _STATEMENT_ORDER_CONTROL_FLOW_RE.search(
        _blank_literals_and_comments(body_inner)
    ):
        return
    blanked = _blank_literals_and_comments(body_inner)
    block_ids = _statement_order_block_ids(blanked)
    records = _text_line_records_with_newline(body_inner)
    locals_by_block: dict[int, set[str]] = {}
    blocked_blocks: set[int] = set()
    statements: list[_StatementOrderRecord] = []

    for index, (start, end, line_end, line) in enumerate(records):
        block_id = block_ids[index] if index < len(block_ids) else 0
        if _STATEMENT_ORDER_COMMENT_OR_ORDER_NOTE_RE.search(line) is not None:
            blocked_blocks.add(block_id)
            statements = [
                statement
                for statement in statements
                if statement.block_id != block_id
            ]
            continue
        if block_id in blocked_blocks:
            continue
        decl_match = _STATEMENT_ORDER_DECL_RE.match(line)
        if decl_match is not None:
            locals_by_block.setdefault(block_id, set()).add(decl_match.group("name"))
            continue
        if _statement_order_line_forbidden(line):
            continue
        match = _STATEMENT_ORDER_ASSIGN_RE.match(line)
        if match is None:
            continue
        lhs = match.group("lhs")
        locals_in_scope = locals_by_block.get(block_id, set())
        if lhs not in locals_in_scope:
            continue
        rhs = match.group("rhs").strip()
        if re.search(r"[*/%+\-&|^]?=", rhs) is not None or "(" in rhs or ")" in rhs:
            continue
        reads = _statement_order_rhs_reads(rhs, locals_in_scope)
        if reads is None:
            continue
        statements.append(
            _StatementOrderRecord(
                start=body_start + start,
                end=body_start + end,
                line_end=body_start + line_end,
                line=line,
                block_id=block_id,
                reads=tuple(read for read in reads if read != lhs),
                writes=(lhs,),
            )
        )

    for first, second in zip(statements, statements[1:]):
        if first.block_id != second.block_id or first.line_end != second.start:
            continue
        first_writes = set(first.writes)
        second_writes = set(second.writes)
        if first_writes & second_writes:
            continue
        if first_writes & set(second.reads):
            continue
        if second_writes & set(first.reads):
            continue
        span_text = source_text[first.start:second.line_end]
        replacement_text = second.line + "\n" + first.line + "\n"
        yield Anchor(
            mutator_key="swap_independent_adjacent_statements",
            span=(first.start, second.line_end),
            payload={
                "span_text": span_text,
                "replacement_text": replacement_text,
                "movement": "swap-adjacent",
                "first_span": [first.start, first.end],
                "second_span": [second.start, second.end],
                "first_reads": list(first.reads),
                "first_writes": list(first.writes),
                "second_reads": list(second.reads),
                "second_writes": list(second.writes),
            },
        )
