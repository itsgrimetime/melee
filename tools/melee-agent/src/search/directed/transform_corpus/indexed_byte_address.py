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


_INDEXED_BYTE_EXPR_RE = re.compile(
    r"(?P<base>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)"
    r"\[(?P<index>[^\[\]\n]+)\]"
)


_BYTE_ARRAY_DECL_RE = re.compile(
    r"\b(?P<type>u8|s8)\s+(?P<name>[A-Za-z_]\w*)\s*\["
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


def _byte_array_types(source_text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    rejected: set[str] = set()
    for match in _BYTE_ARRAY_DECL_RE.finditer(_blank_literals_and_comments(source_text)):
        name = match.group("name")
        decl_type = match.group("type")
        if name in result:
            if result[name] != decl_type:
                rejected.add(name)
            continue
        result[name] = decl_type
    for name in rejected:
        result.pop(name, None)
    return result


def _base_leaf_name(base: str) -> str:
    return base.rsplit(".", 1)[-1]


def _fresh_byte_temp(searchable: str, lhs: str) -> str | None:
    for candidate in (f"{lhs}_probe", *(f"{lhs}_probe_{idx}" for idx in range(2, 8))):
        if not _identifier_mentions(searchable, candidate):
            return candidate
    return None


def _fresh_indexed_expr_temp(searchable: str, base: str) -> str | None:
    return _fresh_byte_temp(searchable, _base_leaf_name(base))


def _fresh_index_temp(searchable: str, base: str) -> str | None:
    return _fresh_byte_temp(searchable, f"{_base_leaf_name(base)}_idx")


def _fresh_base_alias_temp(searchable: str, base: str) -> str | None:
    return _fresh_byte_temp(searchable, f"{_base_leaf_name(base)}_base")


def _index_is_parenthesized(index: str) -> bool:
    stripped = index.strip()
    return stripped.startswith("(") and stripped.endswith(")")


def _indexed_expr(base: str, index: str) -> str:
    return f"{base}[{index}]"


def _safe_indexed_expr(base: str, index_expr: str, line: str) -> bool:
    if not base or "->" in base or "*" in base:
        return False
    if "[" in index_expr or "]" in index_expr:
        return False
    return re.search(r"&\s*" + re.escape(base) + r"\s*\[", line) is None


def _safe_index_temp_expr(index_expr: str) -> bool:
    if "[" in index_expr or "]" in index_expr:
        return False
    if any(token in index_expr for token in ("++", "--", "?", ":", ",")):
        return False
    if re.search(r"(?<![=!<>])=(?!=)", index_expr):
        return False
    if re.search(r"\b[A-Za-z_]\w*\s*\(", index_expr):
        return False
    return bool(re.search(r"\b[A-Za-z_]\w*\b|\d", index_expr))


def _line_can_host_value_temp(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    if re.match(r"(?:if|while|switch)\s*\(", stripped):
        return True
    if re.match(r"(?:return|[A-Za-z_]\w+\s*\()", stripped):
        return True
    return re.match(r"[A-Za-z_]\w*\s*=", stripped) is not None


def _iter_general_indexed_byte_expr_anchors(
    *,
    source_text: str,
    body_text: str,
    body_start: int,
):
    byte_arrays = _byte_array_types(source_text)
    if not byte_arrays:
        return
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    for idx, (start, end, _end_with_newline, search_line) in enumerate(
        searchable_records
    ):
        if idx >= len(records):
            continue
        if _INDEXED_BYTE_ASSIGN_RE.match(search_line):
            continue
        line = records[idx][3]
        if body_text.count(line) != 1:
            continue
        for match in _INDEXED_BYTE_EXPR_RE.finditer(search_line):
            base = match.group("base")
            index_expr = match.group("index").strip()
            decl_type = byte_arrays.get(_base_leaf_name(base))
            if decl_type is None or not _safe_indexed_expr(base, index_expr, line):
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
                            "target_local": _base_leaf_name(base),
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
                        "target_local": _base_leaf_name(base),
                    },
                )
            if not _line_can_host_value_temp(line):
                continue
            temp_name = _fresh_indexed_expr_temp(searchable, base)
            if temp_name is None:
                continue
            indent_match = re.match(r"(?P<indent>[ \t]*)", line)
            indent = indent_match.group("indent") if indent_match is not None else ""
            span_text = body_text[:end]
            if body_text.count(span_text) != 1:
                continue
            replacement_line = line.replace(original_indexed, temp_name, 1)
            replacement_text = (
                f"    {decl_type} {temp_name};\n"
                f"{body_text[:start]}"
                f"{indent}{temp_name} = {original_indexed};\n"
                f"{replacement_line}"
            )
            yield Anchor(
                mutator_key="steer_indexed_byte_value_temp",
                span=(body_start, body_start + end),
                payload={
                    "span_text": span_text,
                    "replacement_text": replacement_text,
                    "strategy": "indexed-byte-value-temp",
                    "array_base": base,
                    "index_expr": index_expr,
                    "target_local": _base_leaf_name(base),
                    "temp_local": temp_name,
                },
            )
            base_alias_name = _fresh_base_alias_temp(searchable, base)
            if base_alias_name is not None:
                replacement_line = line.replace(
                    original_indexed,
                    _indexed_expr(base_alias_name, match.group("index")),
                    1,
                )
                if replacement_line != line:
                    yield Anchor(
                        mutator_key="steer_indexed_byte_base_alias",
                        span=(body_start, body_start + end),
                        payload={
                            "span_text": span_text,
                            "replacement_text": (
                                f"    {decl_type}* {base_alias_name};\n"
                                f"{body_text[:start]}"
                                f"{indent}{base_alias_name} = {base};\n"
                                f"{replacement_line}"
                            ),
                            "strategy": "indexed-byte-base-alias",
                            "array_base": base,
                            "index_expr": index_expr,
                            "target_local": _base_leaf_name(base),
                            "temp_local": base_alias_name,
                        },
                    )
            if not _safe_index_temp_expr(index_expr):
                continue
            index_temp_name = _fresh_index_temp(searchable, base)
            if index_temp_name is None:
                continue
            replacement_line = line.replace(
                original_indexed,
                _indexed_expr(base, index_temp_name),
                1,
            )
            if replacement_line == line:
                continue
            yield Anchor(
                mutator_key="steer_indexed_byte_index_temp",
                span=(body_start, body_start + end),
                payload={
                    "span_text": span_text,
                    "replacement_text": (
                        f"    int {index_temp_name};\n"
                        f"{body_text[:start]}"
                        f"{indent}{index_temp_name} = {index_expr};\n"
                        f"{replacement_line}"
                    ),
                    "strategy": "indexed-byte-index-temp",
                    "array_base": base,
                    "index_expr": index_expr,
                    "target_local": _base_leaf_name(base),
                    "temp_local": index_temp_name,
                },
            )


def _iter_indexed_byte_address_temp_anchors(source_text: str, _function: str, span):
    body_start = span.body_open + 1
    body_end = span.body_close
    body_text = source_text[body_start:body_end]
    if re.search(r"(?m)^[ \t]*#", body_text):
        return

    yield from _iter_general_indexed_byte_expr_anchors(
        source_text=source_text,
        body_text=body_text,
        body_start=body_start,
    )

    byte_decls = _byte_decl_lines(body_text)
    if not byte_decls:
        return
    byte_arrays = _byte_array_types(source_text)

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
        base_decl_type = byte_arrays.get(_base_leaf_name(base), decl[0])

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

        base_alias_name = _fresh_base_alias_temp(searchable, base)
        if base_alias_name is not None:
            replacement_indexed = _indexed_expr(base_alias_name, match.group("index"))
            span_text = body_text[decl_end_with_newline:end]
            if body_text.count(span_text) != 1:
                continue
            prefix = body_text[decl_end_with_newline:start]
            replacement_text = (
                f"{match.group('indent')}{base_decl_type}* {base_alias_name};\n"
                f"{prefix}"
                f"{match.group('indent')}{base_alias_name} = {base};\n"
                f"{match.group('indent')}{lhs} = {replacement_indexed};"
            )
            yield Anchor(
                mutator_key="steer_indexed_byte_base_alias",
                span=(body_start + decl_end_with_newline, body_start + end),
                payload={
                    "span_text": span_text,
                    "replacement_text": replacement_text,
                    "strategy": "indexed-byte-base-alias",
                    "array_base": base,
                    "index_expr": index_expr,
                    "target_local": lhs,
                    "temp_local": base_alias_name,
                },
            )

        if not _safe_index_temp_expr(index_expr):
            continue
        index_temp_name = _fresh_index_temp(searchable, base)
        if index_temp_name is None:
            continue
        replacement_indexed = _indexed_expr(base, index_temp_name)
        span_text = body_text[decl_end_with_newline:end]
        if body_text.count(span_text) != 1:
            continue
        prefix = body_text[decl_end_with_newline:start]
        replacement_text = (
            f"{match.group('indent')}int {index_temp_name};\n"
            f"{prefix}"
            f"{match.group('indent')}{index_temp_name} = {index_expr};\n"
            f"{match.group('indent')}{lhs} = {replacement_indexed};"
        )
        yield Anchor(
            mutator_key="steer_indexed_byte_index_temp",
            span=(body_start + decl_end_with_newline, body_start + end),
            payload={
                "span_text": span_text,
                "replacement_text": replacement_text,
                "strategy": "indexed-byte-index-temp",
                "array_base": base,
                "index_expr": index_expr,
                "target_local": lhs,
                "temp_local": index_temp_name,
            },
        )
