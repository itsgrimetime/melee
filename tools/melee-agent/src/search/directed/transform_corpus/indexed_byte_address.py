"""Source-transform family: indexed byte-array address temp steering."""
from __future__ import annotations

import re

from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import (
    _blank_literals_and_comments,
    _identifier_mentions,
    _line_depths_from_blanked_text,
    _text_line_records_with_newline,
)


_BYTE_DECL_RE = re.compile(
    r"^[ \t]*(?P<type>u8|s8)\s+(?P<name>[A-Za-z_]\w*)\s*;$"
)


_INDEXED_BYTE_ASSIGN_RE = re.compile(
    r"^(?P<indent>[ \t]+)"
    r"(?P<lhs>[A-Za-z_]\w*)\s*=\s*"
    r"(?P<base>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)"
    r"\[(?P<index>[^\]\n]+)\]\s*;\s*$"
)


def _byte_decl_lines(
    body_text: str,
) -> dict[str, tuple[str, int, int, int]]:
    records = _text_line_records_with_newline(body_text)
    searchable = _blank_literals_and_comments(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    result: dict[str, tuple[str, int, int, int]] = {}
    rejected: set[str] = set()
    for idx, (start, end, end_with_newline, line) in enumerate(searchable_records):
        depth = depths[idx] if idx < len(depths) else 0
        if depth != 0 or idx >= len(records):
            continue
        match = _BYTE_DECL_RE.match(line)
        if match is None:
            continue
        name = match.group("name")
        if name in result:
            rejected.add(name)
            continue
        result[name] = (match.group("type"), start, end, end_with_newline)
    for name in rejected:
        result.pop(name, None)
    return result


def _fresh_byte_temp(searchable: str, lhs: str) -> str | None:
    for candidate in (f"{lhs}_probe", *(f"{lhs}_probe_{idx}" for idx in range(2, 8))):
        if not _identifier_mentions(searchable, candidate):
            return candidate
    return None


def _index_is_parenthesized(index: str) -> bool:
    stripped = index.strip()
    return stripped.startswith("(") and stripped.endswith(")")


def _indexed_expr(base: str, index: str) -> str:
    return f"{base}[{index}]"


def _iter_indexed_byte_address_temp_anchors(source_text: str, _function: str, span):
    body_start = span.body_open + 1
    body_end = span.body_close
    body_text = source_text[body_start:body_end]
    if re.search(r"(?m)^[ \t]*#", body_text):
        return

    byte_decls = _byte_decl_lines(body_text)
    if not byte_decls:
        return

    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    for idx, (start, end, _end_with_newline, search_line) in enumerate(
        searchable_records
    ):
        if idx >= len(records):
            continue
        if (depths[idx] if idx < len(depths) else 0) != 0:
            continue
        match = _INDEXED_BYTE_ASSIGN_RE.match(search_line)
        if match is None:
            continue
        line = records[idx][3]
        if body_text.count(line) != 1:
            continue
        lhs = match.group("lhs")
        decl = byte_decls.get(lhs)
        if decl is None:
            continue
        base = match.group("base")
        index_expr = match.group("index").strip()
        if not base or "->" in base or "[" in index_expr or "]" in index_expr:
            continue
        if "&" in line or "*" in base:
            continue
        original_indexed = _indexed_expr(base, match.group("index"))

        if not _index_is_parenthesized(index_expr):
            replacement_line = line.replace(
                original_indexed,
                _indexed_expr(base, f"({index_expr})"),
                1,
            )
            if replacement_line != line:
                yield Anchor(
                    mutator_key="steer_indexed_byte_same_line_expr",
                    span=(body_start + start, body_start + end),
                    payload={
                        "span_text": line,
                        "replacement_text": replacement_line,
                        "strategy": "indexed-byte-parenthesize-index",
                        "array_base": base,
                        "index_expr": index_expr,
                        "target_local": lhs,
                    },
                )

        comma_line = line.replace(
            original_indexed,
            _indexed_expr(base, f"(0, {index_expr})"),
            1,
        )
        if comma_line != line:
            yield Anchor(
                mutator_key="steer_indexed_byte_same_line_expr",
                span=(body_start + start, body_start + end),
                payload={
                    "span_text": line,
                    "replacement_text": comma_line,
                    "strategy": "indexed-byte-comma-normalize",
                    "array_base": base,
                    "index_expr": index_expr,
                    "target_local": lhs,
                },
            )

        temp_name = _fresh_byte_temp(searchable, lhs)
        if temp_name is None:
            continue
        decl_type, _decl_start, _decl_end, decl_end_with_newline = decl
        if decl_end_with_newline > start:
            continue
        span_text = body_text[decl_end_with_newline:end]
        if body_text.count(span_text) != 1:
            continue
        prefix = body_text[decl_end_with_newline:start]
        replacement_text = (
            f"{match.group('indent')}{decl_type} {temp_name};\n"
            f"{prefix}"
            f"{match.group('indent')}{temp_name} = {original_indexed};\n"
            f"{match.group('indent')}{lhs} = {temp_name};"
        )
        yield Anchor(
            mutator_key="steer_indexed_byte_value_temp",
            span=(body_start + decl_end_with_newline, body_start + end),
            payload={
                "span_text": span_text,
                "replacement_text": replacement_text,
                "strategy": "indexed-byte-value-temp",
                "array_base": base,
                "index_expr": index_expr,
                "target_local": lhs,
                "temp_local": temp_name,
            },
        )
