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


_INDEXED_BYTE_STORE_RE = re.compile(
    r"^(?P<indent>[ \t]+)"
    r"(?P<base>[A-Za-z_]\w*)"
    r"\[(?P<index>[^\]\n]+)\]\s*=\s*(?P<expr>.+?)\s*;\s*$"
)


_POINTER_ALIAS_ASSIGN_RE = re.compile(
    r"^(?P<indent>[ \t]+)(?P<lhs>[A-Za-z_]\w*)\s*=\s*"
    r"(?P<rhs>[A-Za-z_]\w*)\s*;\s*$"
)


_GLOBAL_ALIAS_DECL_RE = re.compile(
    r"^[ \t]*(?P<type>(?:struct\s+)?[A-Za-z_]\w*)\s*\*\s*"
    r"(?P<alias>[A-Za-z_]\w*)\s*=\s*"
    r"(?:\([^)]*\)\s*)?&\s*"
    r"(?P<global>[A-Za-z_]\w*)\s*;\s*$"
)


_BYTE_POINTER_FIELD_DECL_RE = re.compile(
    r"^(?P<indent>[ \t]+)(?P<type>u8|s8)\s*\*\s*"
    r"(?P<name>[A-Za-z_]\w*)\s*=\s*"
    r"(?P<alias>[A-Za-z_]\w*)->(?P<field>[A-Za-z_]\w*)\s*;\s*$"
)


_FOR_LOOP_RE = re.compile(
    r"^(?P<indent>[ \t]+)for\s*\(\s*"
    r"(?P<index>[A-Za-z_]\w*)\s*=\s*(?P<start>[^;]+?)\s*;\s*"
    r"(?P=index)\s*<\s*(?P<limit>[^;]+?)\s*;\s*"
    r"(?P<increments>[^)]*?)\s*\)\s*\{\s*$"
)


_POINTER_STORE_RE = re.compile(
    r"^(?P<indent>[ \t]+)\*(?P<pointer>[A-Za-z_]\w*)\s*=\s*(?P<expr>.+?)\s*;\s*$"
)


_TOTALS_INDEXED_BYTE_RE = re.compile(
    r"(?P<outer>[A-Za-z_]\w*)\s*\[\s*"
    r"(?P<base>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)"
    r"\[(?P<index>[^\[\]\n]+)\]\s*\]"
)


_BYTE_ARRAY_DECL_RE = re.compile(
    r"\b(?P<type>u8|s8)\s+(?P<name>[A-Za-z_]\w*)\s*\["
)


_BYTE_POINTER_DECL_RE = re.compile(
    r"\b(?P<type>u8|s8)\s*\*\s*(?P<name>[A-Za-z_]\w*)\b"
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
    searchable = _blank_literals_and_comments(source_text)
    for pattern in (_BYTE_ARRAY_DECL_RE, _BYTE_POINTER_DECL_RE):
        for match in pattern.finditer(searchable):
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


def _fresh_byte_temps(searchable: str, lhs: str, count: int) -> tuple[str, ...]:
    temps: list[str] = []
    occupied = searchable
    for idx in range(1, 16):
        candidate = f"{lhs}_probe" if idx == 1 else f"{lhs}_probe_{idx}"
        if _identifier_mentions(occupied, candidate):
            continue
        temps.append(candidate)
        occupied += f"\n{candidate}\n"
        if len(temps) == count:
            return tuple(temps)
    return ()


def _safe_temp_stem(text: str) -> str:
    stem = re.sub(r"\W+", "_", text.strip())
    stem = stem.strip("_")
    return stem or "expr"


def _fresh_named_temp(searchable: str, stem: str) -> str | None:
    for idx in range(1, 16):
        candidate = f"{stem}_probe" if idx == 1 else f"{stem}_probe_{idx}"
        if not _identifier_mentions(searchable, candidate):
            return candidate
    return None


def _fresh_named_temps(searchable: str, stem: str, count: int) -> tuple[str, ...]:
    temps: list[str] = []
    occupied = searchable
    for idx in range(1, 32):
        candidate = f"{stem}_probe" if idx == 1 else f"{stem}_probe_{idx}"
        if _identifier_mentions(occupied, candidate):
            continue
        temps.append(candidate)
        occupied += f"\n{candidate}\n"
        if len(temps) == count:
            return tuple(temps)
    return ()


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


def _canonical_index_expr(index_expr: str) -> str:
    stripped = index_expr.strip()
    while stripped.startswith("(") and stripped.endswith(")"):
        inner = stripped[1:-1].strip()
        if not inner:
            break
        stripped = inner
    return stripped


def _line_can_host_value_temp(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    if re.match(r"(?:if|while|switch)\s*\(", stripped):
        return True
    if re.match(r"(?:return|[A-Za-z_]\w+\s*\()", stripped):
        return True
    return re.match(r"[A-Za-z_]\w*\s*=", stripped) is not None


def _condition_span_from_line(
    records: list[tuple[int, int, int, str]],
    start_idx: int,
) -> tuple[int, int] | None:
    if start_idx >= len(records):
        return None
    start, _end, _end_with_newline, first_line = records[start_idx]
    if re.match(r"^[ \t]*(?:if|while)\s*\(", first_line) is None:
        return None
    balance = 0
    for idx in range(start_idx, len(records)):
        _line_start, line_end, _line_end_with_newline, line = records[idx]
        balance += line.count("(") - line.count(")")
        if balance <= 0 and "{" in line:
            return start, line_end
    return None


def _replace_indexed_base_references(
    *,
    region_text: str,
    region_searchable: str,
    base: str,
    alias: str,
) -> tuple[str, tuple[str, ...]]:
    pieces: list[str] = []
    indices: list[str] = []
    cursor = 0
    for match in _INDEXED_BYTE_EXPR_RE.finditer(region_searchable):
        if match.group("base") != base:
            continue
        index = match.group("index")
        index_expr = index.strip()
        if not _safe_indexed_expr(base, index_expr, region_text):
            continue
        pieces.append(region_text[cursor:match.start()])
        pieces.append(_indexed_expr(alias, index))
        cursor = match.end()
        indices.append(index_expr)
    if not pieces:
        return region_text, ()
    pieces.append(region_text[cursor:])
    return "".join(pieces), tuple(indices)


def _replace_indexed_value_references(
    *,
    region_text: str,
    region_searchable: str,
    base: str,
    temp_by_index: dict[str, str],
) -> tuple[str, tuple[str, ...]]:
    pieces: list[str] = []
    indices: list[str] = []
    cursor = 0
    for match in _INDEXED_BYTE_EXPR_RE.finditer(region_searchable):
        if match.group("base") != base:
            continue
        index = match.group("index")
        index_expr = index.strip()
        if not _safe_indexed_expr(base, index_expr, region_text):
            continue
        temp = temp_by_index.get(index_expr)
        if temp is None:
            continue
        pieces.append(region_text[cursor:match.start()])
        pieces.append(temp)
        cursor = match.end()
        indices.append(index_expr)
    if not pieces:
        return region_text, ()
    pieces.append(region_text[cursor:])
    return "".join(pieces), tuple(indices)


def _replace_indexed_index_references(
    *,
    region_text: str,
    region_searchable: str,
    base: str,
    temp_by_index: dict[str, str],
) -> tuple[str, tuple[str, ...]]:
    pieces: list[str] = []
    indices: list[str] = []
    cursor = 0
    for match in _INDEXED_BYTE_EXPR_RE.finditer(region_searchable):
        if match.group("base") != base:
            continue
        index = match.group("index")
        index_expr = index.strip()
        if not _safe_indexed_expr(base, index_expr, region_text):
            continue
        temp = temp_by_index.get(index_expr)
        if temp is None:
            continue
        pieces.append(region_text[cursor:match.start()])
        pieces.append(_indexed_expr(base, temp))
        cursor = match.end()
        indices.append(index_expr)
    if not pieces:
        return region_text, ()
    pieces.append(region_text[cursor:])
    return "".join(pieces), tuple(indices)


def _replace_totals_indexed_value_references(
    *,
    region_text: str,
    region_searchable: str,
    base: str,
    temp_by_index: dict[str, str],
) -> tuple[str, tuple[str, ...]]:
    pieces: list[str] = []
    indices: list[str] = []
    cursor = 0
    for match in _TOTALS_INDEXED_BYTE_RE.finditer(region_searchable):
        if match.group("base") != base:
            continue
        index_expr = match.group("index").strip()
        if not _safe_indexed_expr(base, index_expr, region_text):
            continue
        temp = temp_by_index.get(index_expr)
        if temp is None:
            continue
        pieces.append(region_text[cursor:match.start()])
        pieces.append(f"{match.group('outer')}[{temp}]")
        cursor = match.end()
        indices.append(index_expr)
    if not pieces:
        return region_text, ()
    pieces.append(region_text[cursor:])
    return "".join(pieces), tuple(indices)


def _prefix_with_inserted_decls(prefix: str, declarations: str) -> str:
    leading_len = len(prefix) - len(prefix.lstrip("\n"))
    return f"{prefix[:leading_len]}{declarations}{prefix[leading_len:]}"


def _global_aliases(body_text: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    searchable = _blank_literals_and_comments(body_text)
    for _start, _end, _end_with_newline, line in _text_line_records_with_newline(
        searchable
    ):
        match = _GLOBAL_ALIAS_DECL_RE.match(line)
        if match is not None:
            aliases[match.group("alias")] = match.group("global")
    return aliases


def _direct_global_base_for_field(
    source_text: str,
    global_name: str,
    field: str,
) -> str | None:
    searchable = _blank_literals_and_comments(source_text)
    exact = f"{global_name}.{field}"
    if re.search(r"\b" + re.escape(exact) + r"\b", searchable):
        return exact
    matches = {
        match.group("base")
        for match in re.finditer(
            r"\b(?P<base>[A-Za-z_]\w*\." + re.escape(field) + r")\b",
            searchable,
        )
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _byte_pointer_field_aliases(
    *,
    source_text: str,
    body_text: str,
) -> dict[str, tuple[str, str, str]]:
    byte_arrays = _byte_array_types(source_text)
    aliases = _global_aliases(body_text)
    if not byte_arrays or not aliases:
        return {}
    result: dict[str, tuple[str, str, str]] = {}
    rejected: set[str] = set()
    searchable = _blank_literals_and_comments(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    for idx, (_start, _end, _end_with_newline, search_line) in enumerate(
        searchable_records
    ):
        if (depths[idx] if idx < len(depths) else 0) != 0:
            continue
        match = _BYTE_POINTER_FIELD_DECL_RE.match(search_line)
        if match is None:
            continue
        global_name = aliases.get(match.group("alias"))
        field = match.group("field")
        if global_name is None or field not in byte_arrays:
            continue
        direct_base = (
            _direct_global_base_for_field(source_text, global_name, field)
            or f"{global_name}.{field}"
        )
        local = match.group("name")
        if local in result:
            rejected.add(local)
            continue
        result[local] = (match.group("type"), direct_base, field)
    for local in rejected:
        result.pop(local, None)
    return result


def _iter_direct_global_dst_anchors(
    *,
    source_text: str,
    body_text: str,
    body_start: int,
):
    byte_arrays = _byte_array_types(source_text)
    aliases = _global_aliases(body_text)
    if not byte_arrays or not aliases:
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
        match = _BYTE_POINTER_FIELD_DECL_RE.match(search_line)
        if match is None:
            continue
        global_name = aliases.get(match.group("alias"))
        field = match.group("field")
        if global_name is None or field not in byte_arrays:
            continue
        direct_base = _direct_global_base_for_field(source_text, global_name, field)
        if direct_base is None:
            continue
        line = records[idx][3]
        if body_text.count(line) != 1:
            continue
        replacement_line = (
            f"{match.group('indent')}{match.group('type')}* "
            f"{match.group('name')} = {direct_base};"
        )
        yield Anchor(
            mutator_key="steer_indexed_byte_direct_global_dst",
            span=(body_start + start, body_start + end),
            payload={
                "span_text": line,
                "replacement_text": replacement_line,
                "strategy": "indexed-byte-direct-global-dst",
                "array_base": direct_base,
                "target_local": match.group("name"),
                "source_local": match.group("alias"),
            },
        )


def _iter_implicit_indexed_store_anchors(
    *,
    source_text: str,
    body_text: str,
    body_start: int,
):
    pointer_fields = _byte_pointer_field_aliases(
        source_text=source_text,
        body_text=body_text,
    )
    if not pointer_fields:
        return
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    for idx, (start, end, _end_with_newline, search_line) in enumerate(
        searchable_records
    ):
        if idx >= len(records):
            continue
        match = _INDEXED_BYTE_STORE_RE.match(search_line)
        if match is None:
            continue
        pointer_local = match.group("base")
        pointer_info = pointer_fields.get(pointer_local)
        if pointer_info is None:
            continue
        _decl_type, direct_base, field = pointer_info
        index_expr = match.group("index").strip()
        line = records[idx][3]
        if (
            not _safe_indexed_expr(pointer_local, index_expr, line)
            or not _safe_index_temp_expr(index_expr)
            or body_text.count(line) != 1
        ):
            continue
        original_indexed = _indexed_expr(pointer_local, match.group("index"))
        direct_indexed = _indexed_expr(direct_base, match.group("index"))
        direct_line = line.replace(original_indexed, direct_indexed, 1)
        if direct_line != line:
            yield Anchor(
                mutator_key="steer_indexed_byte_implicit_direct_store_base",
                span=(body_start + start, body_start + end),
                payload={
                    "span_text": line,
                    "replacement_text": direct_line,
                    "strategy": "indexed-byte-implicit-direct-store-base",
                    "array_base": direct_base,
                    "index_expr": index_expr,
                    "target_local": pointer_local,
                },
            )

        index_temp_name = _fresh_named_temp(searchable, f"{field}_store_idx")
        if index_temp_name is None:
            continue
        indexed_with_temp = _indexed_expr(pointer_local, index_temp_name)
        temp_line = line.replace(original_indexed, indexed_with_temp, 1)
        if temp_line == line:
            continue
        span_text = body_text[:end]
        if body_text.count(span_text) != 1:
            continue
        declaration = f"    int {index_temp_name};\n"
        replacement_text = (
            f"{_prefix_with_inserted_decls(body_text[:start], declaration)}"
            f"{match.group('indent')}{index_temp_name} = {index_expr};\n"
            f"{temp_line}"
        )
        yield Anchor(
            mutator_key="steer_indexed_byte_implicit_store_index_temp",
            span=(body_start, body_start + end),
            payload={
                "span_text": span_text,
                "replacement_text": replacement_text,
                "strategy": "indexed-byte-implicit-store-index-temp",
                "array_base": pointer_local,
                "index_expr": index_expr,
                "target_local": pointer_local,
                "temp_local": index_temp_name,
            },
        )


def _increment_for_local(increments: tuple[str, ...], local: str) -> str | None:
    for increment in increments:
        if re.search(r"\b" + re.escape(local) + r"\b", increment):
            return increment
    return None


def _last_pointer_alias_assignment_before(
    *,
    searchable_records: list[tuple[int, int, int, str]],
    before_idx: int,
    pointer_local: str,
    byte_pointers: dict[str, str],
) -> tuple[int, int, int, str] | None:
    for idx in range(before_idx - 1, -1, -1):
        start, end, end_with_newline, search_line = searchable_records[idx]
        match = _POINTER_ALIAS_ASSIGN_RE.match(search_line)
        if match is None:
            continue
        if (
            match.group("lhs") == pointer_local
            and match.group("rhs") in byte_pointers
        ):
            return start, end, end_with_newline, match.group("rhs")
    return None


def _iter_implicit_init_loop_indexed_store_anchors(
    *,
    source_text: str,
    body_text: str,
    body_start: int,
):
    pointer_fields = _byte_pointer_field_aliases(
        source_text=source_text,
        body_text=body_text,
    )
    if not pointer_fields:
        return
    byte_pointers = _byte_array_types(source_text)
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    for idx, (start, _end, _end_with_newline, search_line) in enumerate(
        searchable_records[:-3]
    ):
        if idx + 3 >= len(records):
            continue
        header_match = _FOR_LOOP_RE.match(search_line)
        if header_match is None:
            continue
        first_store = _POINTER_STORE_RE.match(searchable_records[idx + 1][3])
        second_store = _POINTER_STORE_RE.match(searchable_records[idx + 2][3])
        if first_store is None or second_store is None:
            continue
        close_line = searchable_records[idx + 3][3]
        if re.match(r"^[ \t]*}\s*$", close_line) is None:
            continue
        first_pointer = first_store.group("pointer")
        second_pointer = second_store.group("pointer")
        pointer_init = _last_pointer_alias_assignment_before(
            searchable_records=searchable_records,
            before_idx=idx,
            pointer_local=first_pointer,
            byte_pointers=byte_pointers,
        )
        if pointer_init is None:
            continue
        init_start, _init_end, init_end_with_newline, base_local = pointer_init
        if base_local not in pointer_fields or first_pointer == second_pointer:
            continue
        increments = tuple(
            increment.strip()
            for increment in header_match.group("increments").split(",")
            if increment.strip()
        )
        loop_index = header_match.group("index")
        index_increment = _increment_for_local(increments, loop_index)
        first_increment = _increment_for_local(increments, first_pointer)
        second_increment = _increment_for_local(increments, second_pointer)
        if (
            index_increment is None
            or first_increment is None
            or second_increment is None
        ):
            continue
        start_expr = header_match.group("start").strip()
        limit_expr = header_match.group("limit").strip()
        indent = header_match.group("indent")
        span_end = searchable_records[idx + 3][1]
        span_text = body_text[init_start:span_end]
        if body_text.count(span_text) != 1:
            continue
        between_text = body_text[init_end_with_newline:start]
        first_store_indent = first_store.group("indent")
        first_store_line = (
            f"{first_store_indent}{base_local}[{loop_index}] = "
            f"{first_store.group('expr')};\n"
        )
        second_store_line = records[idx + 2][3]
        if not second_store_line.endswith("\n"):
            second_store_line += "\n"
        replacement_text = (
            f"{between_text}"
            f"{indent}for ({loop_index} = {start_expr}; "
            f"{loop_index} < {limit_expr}; {index_increment}, "
            f"{second_increment}) {{\n"
            f"{first_store_line}"
            f"{second_store_line}"
            f"{indent}}}"
        )
        yield Anchor(
            mutator_key="steer_indexed_byte_implicit_init_loop_indexed_store",
            span=(body_start + init_start, body_start + span_end),
            payload={
                "span_text": span_text,
                "replacement_text": replacement_text,
                "strategy": "indexed-byte-implicit-init-loop-indexed-store",
                "array_base": base_local,
                "index_expr": loop_index,
                "target_local": first_pointer,
                "totals_pointer_local": second_pointer,
            },
        )


def _iter_init_loop_split_anchors(
    *,
    body_text: str,
    body_start: int,
):
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    for idx, (start, _end, _end_with_newline, search_line) in enumerate(
        searchable_records[:-3]
    ):
        if idx + 3 >= len(records):
            continue
        header_match = _FOR_LOOP_RE.match(search_line)
        if header_match is None:
            continue
        first_store = _POINTER_STORE_RE.match(searchable_records[idx + 1][3])
        second_store = _POINTER_STORE_RE.match(searchable_records[idx + 2][3])
        if first_store is None or second_store is None:
            continue
        close_line = searchable_records[idx + 3][3]
        if re.match(r"^[ \t]*}\s*$", close_line) is None:
            continue
        first_pointer = first_store.group("pointer")
        second_pointer = second_store.group("pointer")
        if first_pointer == second_pointer:
            continue
        increments = tuple(
            increment.strip()
            for increment in header_match.group("increments").split(",")
            if increment.strip()
        )
        loop_index = header_match.group("index")
        index_increment = _increment_for_local(increments, loop_index)
        first_increment = _increment_for_local(increments, first_pointer)
        second_increment = _increment_for_local(increments, second_pointer)
        if (
            index_increment is None
            or first_increment is None
            or second_increment is None
        ):
            continue
        start_expr = header_match.group("start").strip()
        limit_expr = header_match.group("limit").strip()
        indent = header_match.group("indent")
        span_end = searchable_records[idx + 3][1]
        span_text = body_text[start:span_end]
        if body_text.count(span_text) != 1:
            continue
        first_header = (
            f"{indent}for ({loop_index} = {start_expr}; "
            f"{loop_index} < {limit_expr}; {index_increment}, "
            f"{first_increment}) {{\n"
        )
        second_header = (
            f"{indent}for ({loop_index} = {start_expr}; "
            f"{loop_index} < {limit_expr}; {index_increment}, "
            f"{second_increment}) {{\n"
        )
        first_store_line = records[idx + 1][3]
        if not first_store_line.endswith("\n"):
            first_store_line += "\n"
        second_store_line = records[idx + 2][3]
        if not second_store_line.endswith("\n"):
            second_store_line += "\n"
        replacement_text = (
            f"{first_header}"
            f"{first_store_line}"
            f"{indent}}}\n"
            f"{second_header}"
            f"{second_store_line}"
            f"{indent}}}"
        )
        yield Anchor(
            mutator_key="steer_indexed_byte_init_loop_split",
            span=(body_start + start, body_start + span_end),
            payload={
                "span_text": span_text,
                "replacement_text": replacement_text,
                "strategy": "indexed-byte-init-loop-split",
                "index_local": loop_index,
                "first_pointer_local": first_pointer,
                "second_pointer_local": second_pointer,
            },
        )


def _iter_init_pointer_alias_anchors(
    *,
    source_text: str,
    body_text: str,
    body_start: int,
):
    byte_pointers = _byte_array_types(source_text)
    if not byte_pointers:
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
        match = _POINTER_ALIAS_ASSIGN_RE.match(search_line)
        if match is None:
            continue
        lhs = match.group("lhs")
        rhs = match.group("rhs")
        decl_type = byte_pointers.get(lhs) or byte_pointers.get(rhs)
        if decl_type is None or rhs not in byte_pointers:
            continue
        line = records[idx][3]
        if body_text.count(line) != 1:
            continue
        temp_name = _fresh_named_temp(searchable, f"{lhs}_init")
        if temp_name is None:
            continue
        span_text = body_text[:end]
        if body_text.count(span_text) != 1:
            continue
        indent = match.group("indent")
        replacement_text = (
            f"{indent}{decl_type}* {temp_name};\n"
            f"{body_text[:start]}"
            f"{indent}{temp_name} = {rhs};\n"
            f"{indent}{lhs} = {temp_name};"
        )
        yield Anchor(
            mutator_key="steer_indexed_byte_init_pointer_alias",
            span=(body_start, body_start + end),
            payload={
                "span_text": span_text,
                "replacement_text": replacement_text,
                "strategy": "indexed-byte-init-pointer-alias",
                "target_local": lhs,
                "source_local": rhs,
                "temp_local": temp_name,
            },
        )


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
    emitted_condition_aliases: set[tuple[int, int, str]] = set()
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
            condition_span = _condition_span_from_line(searchable_records, idx)
            condition_key = (
                condition_span[0],
                condition_span[1],
                base,
            ) if condition_span is not None else None
            if condition_key is not None and condition_key not in emitted_condition_aliases:
                emitted_condition_aliases.add(condition_key)
                condition_start, condition_end = condition_span
                condition_text = body_text[condition_start:condition_end]
                condition_searchable = searchable[condition_start:condition_end]
                condition_indices: list[str] = []
                for condition_match in _INDEXED_BYTE_EXPR_RE.finditer(
                    condition_searchable
                ):
                    if condition_match.group("base") != base:
                        continue
                    condition_index = condition_match.group("index").strip()
                    if not _safe_indexed_expr(base, condition_index, condition_text):
                        continue
                    if condition_index not in condition_indices:
                        condition_indices.append(condition_index)
                if len(condition_indices) > 1 and all(
                    _safe_index_temp_expr(index_expr)
                    for index_expr in condition_indices
                ):
                    temp_by_index: dict[str, str] = {}
                    occupied = searchable
                    for condition_index in condition_indices:
                        stem = (
                            f"{_base_leaf_name(base)}_"
                            f"{_safe_temp_stem(condition_index)}_idx"
                        )
                        temp_name = _fresh_named_temp(occupied, stem)
                        if temp_name is None:
                            temp_by_index = {}
                            break
                        temp_by_index[condition_index] = temp_name
                        occupied += f"\n{temp_name}\n"
                    if len(temp_by_index) == len(condition_indices):
                        replaced_condition, replaced_indices = (
                            _replace_indexed_index_references(
                                region_text=condition_text,
                                region_searchable=condition_searchable,
                                base=base,
                                temp_by_index=temp_by_index,
                            )
                        )
                        if (
                            len(replaced_indices) > 1
                            and replaced_condition != condition_text
                        ):
                            indent_match = re.match(
                                r"(?P<indent>[ \t]*)",
                                condition_text,
                            )
                            indent = (
                                indent_match.group("indent")
                                if indent_match is not None else ""
                            )
                            span_text = body_text[:condition_end]
                            if body_text.count(span_text) == 1:
                                declarations = "".join(
                                    f"    int {temp_name};\n"
                                    for temp_name in temp_by_index.values()
                                )
                                assignments = "".join(
                                    f"{indent}{temp_name} = {index_expr};\n"
                                    for index_expr, temp_name in temp_by_index.items()
                                )
                                yield Anchor(
                                    mutator_key=(
                                        "steer_indexed_byte_condition_index_alias"
                                    ),
                                    span=(body_start, body_start + condition_end),
                                    payload={
                                        "span_text": span_text,
                                        "replacement_text": (
                                            f"{_prefix_with_inserted_decls(body_text[:condition_start], declarations)}"
                                            f"{assignments}"
                                            f"{replaced_condition}"
                                        ),
                                        "strategy": (
                                            "indexed-byte-condition-index-aliases"
                                        ),
                                        "array_base": base,
                                        "index_expr": replaced_indices[0],
                                        "index_exprs": replaced_indices,
                                        "target_local": _base_leaf_name(base),
                                        "temp_locals": tuple(temp_by_index.values()),
                                    },
                                )
                totals_indices: list[str] = []
                for totals_match in _TOTALS_INDEXED_BYTE_RE.finditer(
                    condition_searchable
                ):
                    if totals_match.group("base") != base:
                        continue
                    totals_index = totals_match.group("index").strip()
                    if not _safe_indexed_expr(base, totals_index, condition_text):
                        continue
                    if totals_index not in totals_indices:
                        totals_indices.append(totals_index)
                totals_temp_names = _fresh_named_temps(
                    searchable,
                    f"{_base_leaf_name(base)}_totals_idx",
                    len(totals_indices),
                )
                if len(totals_temp_names) == len(totals_indices) and len(
                    totals_indices
                ) > 1:
                    temp_by_index = dict(zip(totals_indices, totals_temp_names))
                    replaced_condition, replaced_indices = (
                        _replace_totals_indexed_value_references(
                            region_text=condition_text,
                            region_searchable=condition_searchable,
                            base=base,
                            temp_by_index=temp_by_index,
                        )
                    )
                    if len(replaced_indices) > 1 and replaced_condition != condition_text:
                        indent_match = re.match(r"(?P<indent>[ \t]*)", condition_text)
                        indent = (
                            indent_match.group("indent")
                            if indent_match is not None else ""
                        )
                        span_text = body_text[:condition_end]
                        if body_text.count(span_text) == 1:
                            declarations = "".join(
                                f"    int {temp_name};\n"
                                for temp_name in totals_temp_names
                            )
                            assignments = "".join(
                                f"{indent}{temp_name} = {base}[{index_expr}];\n"
                                for index_expr, temp_name in temp_by_index.items()
                            )
                            yield Anchor(
                                mutator_key="steer_indexed_byte_totals_index_temp",
                                span=(body_start, body_start + condition_end),
                                payload={
                                    "span_text": span_text,
                                    "replacement_text": (
                                        f"{_prefix_with_inserted_decls(body_text[:condition_start], declarations)}"
                                        f"{assignments}"
                                        f"{replaced_condition}"
                                    ),
                                    "strategy": "indexed-byte-totals-index-int-temps",
                                    "array_base": base,
                                    "index_expr": replaced_indices[0],
                                    "index_exprs": replaced_indices,
                                    "target_local": _base_leaf_name(base),
                                    "temp_locals": totals_temp_names,
                                },
                            )
                max_index_expr = next(
                    (
                        index_expr
                        for index_expr in totals_indices
                        if _canonical_index_expr(index_expr) == "max_idx"
                    ),
                    None,
                )
                if max_index_expr is not None:
                    max_value_temp = _fresh_named_temp(
                        searchable,
                        f"{_base_leaf_name(base)}_max_value",
                    )
                    if max_value_temp is not None:
                        replaced_condition, replaced_indices = (
                            _replace_indexed_value_references(
                                region_text=condition_text,
                                region_searchable=condition_searchable,
                                base=base,
                                temp_by_index={max_index_expr: max_value_temp},
                            )
                        )
                        if replaced_indices and replaced_condition != condition_text:
                            indent_match = re.match(
                                r"(?P<indent>[ \t]*)",
                                condition_text,
                            )
                            indent = (
                                indent_match.group("indent")
                                if indent_match is not None else ""
                            )
                            span_text = body_text[:condition_end]
                            if body_text.count(span_text) == 1:
                                declarations = f"    {decl_type} {max_value_temp};\n"
                                yield Anchor(
                                    mutator_key=(
                                        "steer_indexed_byte_max_current_value_temp"
                                    ),
                                    span=(body_start, body_start + condition_end),
                                    payload={
                                        "span_text": span_text,
                                        "replacement_text": (
                                            f"{_prefix_with_inserted_decls(body_text[:condition_start], declarations)}"
                                            f"{indent}{max_value_temp} = "
                                            f"{base}[{max_index_expr}];\n"
                                            f"{replaced_condition}"
                                        ),
                                        "strategy": (
                                            "indexed-byte-max-current-value-temp"
                                        ),
                                        "array_base": base,
                                        "index_expr": max_index_expr,
                                        "target_local": _base_leaf_name(base),
                                        "temp_local": max_value_temp,
                                    },
                                )
                value_temp_names = _fresh_byte_temps(
                    searchable,
                    _base_leaf_name(base),
                    len(condition_indices),
                )
                if len(value_temp_names) == len(condition_indices) and len(
                    condition_indices
                ) > 1:
                    temp_by_index = dict(zip(condition_indices, value_temp_names))
                    replaced_condition, replaced_indices = (
                        _replace_indexed_value_references(
                            region_text=condition_text,
                            region_searchable=condition_searchable,
                            base=base,
                            temp_by_index=temp_by_index,
                        )
                    )
                    if len(replaced_indices) > 1 and replaced_condition != condition_text:
                        indent_match = re.match(r"(?P<indent>[ \t]*)", condition_text)
                        indent = (
                            indent_match.group("indent")
                            if indent_match is not None else ""
                        )
                        span_text = body_text[:condition_end]
                        if body_text.count(span_text) == 1:
                            declarations = "".join(
                                f"    {decl_type} {temp_name};\n"
                                for temp_name in value_temp_names
                            )
                            assignments = "".join(
                                f"{indent}{temp_name} = {base}[{index_expr}];\n"
                                for index_expr, temp_name in temp_by_index.items()
                            )
                            yield Anchor(
                                mutator_key="steer_indexed_byte_value_temp",
                                span=(body_start, body_start + condition_end),
                                payload={
                                    "span_text": span_text,
                                    "replacement_text": (
                                        f"{_prefix_with_inserted_decls(body_text[:condition_start], declarations)}"
                                        f"{assignments}"
                                        f"{replaced_condition}"
                                    ),
                                    "strategy": (
                                        "indexed-byte-condition-all-read-value-temps"
                                    ),
                                    "array_base": base,
                                    "index_expr": replaced_indices[0],
                                    "index_exprs": replaced_indices,
                                    "target_local": _base_leaf_name(base),
                                    "temp_locals": value_temp_names,
                                },
                            )
                base_alias_name = _fresh_base_alias_temp(searchable, base)
                if base_alias_name is not None:
                    replaced_condition, replaced_indices = _replace_indexed_base_references(
                        region_text=condition_text,
                        region_searchable=condition_searchable,
                        base=base,
                        alias=base_alias_name,
                    )
                    if len(replaced_indices) > 1 and replaced_condition != condition_text:
                        indent_match = re.match(r"(?P<indent>[ \t]*)", condition_text)
                        indent = (
                            indent_match.group("indent")
                            if indent_match is not None else ""
                        )
                        span_text = body_text[:condition_end]
                        if body_text.count(span_text) == 1:
                            declarations = f"    {decl_type}* {base_alias_name};\n"
                            yield Anchor(
                                mutator_key="steer_indexed_byte_base_alias",
                                span=(body_start, body_start + condition_end),
                                payload={
                                    "span_text": span_text,
                                    "replacement_text": (
                                        f"{_prefix_with_inserted_decls(body_text[:condition_start], declarations)}"
                                        f"{indent}{base_alias_name} = {base};\n"
                                        f"{replaced_condition}"
                                    ),
                                    "strategy": (
                                        "indexed-byte-base-alias-condition-all-reads"
                                    ),
                                    "array_base": base,
                                    "index_expr": replaced_indices[0],
                                    "index_exprs": replaced_indices,
                                    "target_local": _base_leaf_name(base),
                                    "temp_local": base_alias_name,
                                },
                            )
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

    yield from _iter_implicit_indexed_store_anchors(
        source_text=source_text,
        body_text=body_text,
        body_start=body_start,
    )

    yield from _iter_implicit_init_loop_indexed_store_anchors(
        source_text=source_text,
        body_text=body_text,
        body_start=body_start,
    )

    yield from _iter_init_loop_split_anchors(
        body_text=body_text,
        body_start=body_start,
    )

    yield from _iter_direct_global_dst_anchors(
        source_text=source_text,
        body_text=body_text,
        body_start=body_start,
    )

    yield from _iter_init_pointer_alias_anchors(
        source_text=source_text,
        body_text=body_text,
        body_start=body_start,
    )

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
