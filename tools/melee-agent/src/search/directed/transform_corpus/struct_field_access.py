"""Source-transform family: struct_field_access."""
from __future__ import annotations

import re
from dataclasses import dataclass
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _SIMPLE_IDENTIFIER_RE, _blank_disabled_preprocessor_regions, _blank_literals_and_comments, _function_name_for_span, _inside_any_span, _normalize_c_type, _split_top_level_csv, _target_shadows_symbol, _top_level_function_spans
from typing import Iterable, Mapping


@dataclass(frozen=True)
class _SimpleStructField:
    name: str
    type_name: str
    offset: int
    size: int


@dataclass(frozen=True)
class _SimpleStructLayout:
    type_name: str
    size: int
    fields: tuple[_SimpleStructField, ...]
    declaration_span: tuple[int, int]


_STRUCT_SCALAR_SIZES: Mapping[str, tuple[int, int]] = {
    "char": (1, 1),
    "signed char": (1, 1),
    "unsigned char": (1, 1),
    "s8": (1, 1),
    "u8": (1, 1),
    "bool": (1, 1),
    "BOOL": (4, 4),
    "short": (2, 2),
    "signed short": (2, 2),
    "unsigned short": (2, 2),
    "s16": (2, 2),
    "u16": (2, 2),
    "int": (4, 4),
    "signed int": (4, 4),
    "unsigned int": (4, 4),
    "long": (4, 4),
    "signed long": (4, 4),
    "unsigned long": (4, 4),
    "s32": (4, 4),
    "u32": (4, 4),
    "float": (4, 4),
    "f32": (4, 4),
    "double": (8, 8),
    "f64": (8, 8),
    "long long": (8, 8),
    "signed long long": (8, 8),
    "unsigned long long": (8, 8),
    "s64": (8, 8),
    "u64": (8, 8),
}


def _simple_type_size_and_align(
    type_name: str,
    known_types: Mapping[str, tuple[int, int]] | None = None,
) -> tuple[int, int] | None:
    normalized = _normalize_c_type(type_name)
    if "*" in normalized:
        return 4, 4
    if known_types is not None and normalized in known_types:
        return known_types[normalized]
    return _STRUCT_SCALAR_SIZES.get(normalized)


def _brace_depth_before(text: str, offset: int) -> int:
    depth = 0
    for char in text[:offset]:
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
    return depth


def _simple_struct_layouts(
    source_text: str,
    *,
    before_offset: int | None = None,
) -> dict[str, _SimpleStructLayout]:
    limit = len(source_text) if before_offset is None else before_offset
    prefix = source_text[:limit]
    searchable = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(prefix)
    )
    function_spans = _top_level_function_spans(prefix)
    pattern = re.compile(
        r"typedef\s+struct\s+(?P<tag>[A-Za-z_]\w*)\s*{\s*(?P<body>.*?)\s*}\s*(?P<name>[A-Za-z_]\w*)\s*;",
        re.DOTALL,
    )
    layouts_by_name: dict[str, list[_SimpleStructLayout]] = {}
    known_types: dict[str, tuple[int, int]] = dict(_STRUCT_SCALAR_SIZES)
    for match in pattern.finditer(searchable):
        if _inside_any_span(match.start(), function_spans):
            continue
        struct_name = match.group("name")
        offset = 0
        supported = True
        fields: list[_SimpleStructField] = []
        struct_align = 1
        for raw_field in source_text[match.start("body"):match.end("body")].split(";"):
            field = raw_field.strip()
            if not field:
                continue
            if any(token in field for token in (":", "(", ")", "union ", "struct ")):
                supported = False
                break
            pad = re.match(r"u8\s+[A-Za-z_]\w*\s*\[\s*(0x[0-9A-Fa-f]+|\d+)\s*\]$", field)
            if pad is not None:
                offset += int(pad.group(1), 0)
                continue
            if "[" in field or "]" in field or "," in field:
                supported = False
                break
            normal = re.match(
                r"(?P<type>(?:[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)?)(?:\s*\*)*)\s+"
                r"(?P<name>[A-Za-z_]\w*)$",
                field,
            )
            if normal is None:
                supported = False
                break
            field_type = _normalize_c_type(normal.group("type"))
            size_align = _simple_type_size_and_align(field_type, known_types)
            if size_align is None:
                supported = False
                break
            size, align = size_align
            struct_align = max(struct_align, align)
            if offset % align != 0:
                supported = False
                break
            fields.append(
                _SimpleStructField(
                    name=normal.group("name"),
                    type_name=field_type,
                    offset=offset,
                    size=size,
                )
            )
            offset += size
        if not supported:
            continue
        seen_keys: set[tuple[int, str]] = set()
        for field in fields:
            key = (field.offset, field.type_name)
            if key in seen_keys:
                supported = False
                break
            seen_keys.add(key)
        if not supported:
            continue
        if offset % struct_align != 0:
            offset += struct_align - (offset % struct_align)
        layout = _SimpleStructLayout(
            type_name=struct_name,
            size=offset,
            fields=tuple(fields),
            declaration_span=(match.start(), match.end()),
        )
        layouts_by_name.setdefault(struct_name, []).append(layout)
        if len(layouts_by_name[struct_name]) == 1:
            known_types[struct_name] = (offset, struct_align)
    return {
        name: layouts[0]
        for name, layouts in layouts_by_name.items()
        if len(layouts) == 1
    }


def _simple_struct_field_offsets(source_text: str) -> dict[tuple[str, int, str], str]:
    offsets: dict[tuple[str, int, str], str] = {}
    for layout in _simple_struct_layouts(source_text).values():
        for field in layout.fields:
            offsets[(layout.type_name, field.offset, field.type_name)] = field.name
    return offsets


def _function_pointer_params(source_text: str, span) -> dict[str, str]:
    header = source_text[span.sig_start:span.body_open]
    params_match = re.search(r"\((?P<params>.*)\)\s*$", header, re.DOTALL)
    if params_match is None:
        return {}
    params = _split_top_level_csv(params_match.group("params"))
    if params is None:
        return {}
    result: dict[str, str] = {}
    for param in params:
        match = re.match(r"(?P<type>[A-Za-z_]\w*)\s*\*\s*(?P<name>[A-Za-z_]\w*)$", param.strip())
        if match is not None:
            result[match.group("name")] = match.group("type")
    return result


_RAW_INDEX_EXPR_RE = re.compile(
    r"\*\s*\(\s*(?P<cast_type>(?:[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)?)(?:\s*\*)*)\s*\*\s*\)"
    r"\s*\(\s*\(\s*u8\s*\*\s*\)\s*(?P<base>[A-Za-z_]\w*)\s*"
    r"\+\s*(?P<index>[A-Za-z_]\w*|0x[0-9A-Fa-f]+|\d+)\s*\*\s*"
    r"(?P<scale>sizeof\s*\(\s*(?P<sizeof_type>[A-Za-z_]\w*)\s*\)|0x[0-9A-Fa-f]+|\d+)\s*"
    r"\+\s*(?P<offset>0x[0-9A-Fa-f]+|\d+)\s*\)"
)


def _assignment_operator_after(text: str, end: int) -> str | None:
    suffix = text[end:]
    match = re.match(r"\s*(?P<op>[+\-*/%&|^]?=)", suffix)
    if match is None:
        return None
    op = match.group("op")
    if op == "=" and suffix[match.end():].startswith("="):
        return None
    return op


def _raw_index_access_kind(text: str, end: int) -> str:
    if _assignment_operator_after(text, end) == "=":
        return "store"
    return "load"


def _iter_raw_index_struct_field_anchors(source_text: str, span):
    layouts = _simple_struct_layouts(source_text, before_offset=span.sig_start)
    if not layouts:
        return
    params = {
        name: _normalize_c_type(type_name)
        for name, type_name in _function_pointer_params(source_text, span).items()
    }
    body_start = span.body_open
    body_text = source_text[body_start:span.full_end]
    searchable_body = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(body_text)
    )
    for match in _RAW_INDEX_EXPR_RE.finditer(searchable_body):
        base = match.group("base")
        struct_type = params.get(base)
        if struct_type is None:
            continue
        layout = layouts.get(struct_type)
        if layout is None:
            continue
        sizeof_type = match.group("sizeof_type")
        scale = match.group("scale")
        if sizeof_type is not None:
            if sizeof_type != struct_type:
                continue
        elif int(scale, 0) != layout.size:
            continue
        offset = int(match.group("offset"), 0)
        cast_type = _normalize_c_type(match.group("cast_type"))
        field = next(
            (
                candidate
                for candidate in layout.fields
                if candidate.offset == offset and candidate.type_name == cast_type
            ),
            None,
        )
        if field is None:
            continue
        assignment_op = _assignment_operator_after(searchable_body, match.end())
        if assignment_op is not None and assignment_op != "=":
            continue
        index_expr = match.group("index")
        span_text = source_text[
            body_start + match.start():body_start + match.end()
        ]
        replacement_text = f"{base}[{index_expr}].{field.name}"
        yield Anchor(
            mutator_key="rewrite_raw_index_struct_field",
            span=(body_start + match.start(), body_start + match.end()),
            payload={
                "span_text": span_text,
                "replacement_text": replacement_text,
                "access_kind": _raw_index_access_kind(searchable_body, match.end()),
                "base": base,
                "index_expr": index_expr,
                "scale": scale,
                "field_offset": offset,
                "field_type": field.type_name,
                "field_name": field.name,
                "struct_type": layout.type_name,
                "struct_size": layout.size,
                "proof_source": "source-local-struct-layout",
                "target_function": _function_name_for_span(
                    source_text,
                    _blank_literals_and_comments(source_text),
                    span,
                ),
                "declaration_span": layout.declaration_span,
            },
        )


def _iter_raw_pointer_offset_anchors(source_text: str, span):
    offsets = _simple_struct_field_offsets(source_text)
    params = _function_pointer_params(source_text, span)
    body_text = source_text[span.body_open:span.full_end]
    line_re = re.compile(
        r"^(?P<indent>[ \t]*)\*\((?P<cast_type>[A-Za-z_]\w*)\*\)\s*"
        r"\(\(u8\*\)\s*(?P<base>[A-Za-z_]\w*)\s*\+\s*(?P<offset>0x[0-9A-Fa-f]+|\d+)\)\s*=\s*(?P<rhs>.+);\s*$"
    )
    for line in body_text.splitlines():
        match = line_re.match(line)
        if match is None:
            continue
        struct_type = _normalize_c_type(params.get(match.group("base"), ""))
        if not struct_type:
            continue
        field_name = offsets.get(
            (
                struct_type,
                int(match.group("offset"), 0),
                _normalize_c_type(match.group("cast_type")),
            )
        )
        if field_name is None:
            continue
        yield Anchor(
            mutator_key="rewrite_raw_pointer_offset_field",
            span=(0, 0),
            payload={
                "line": line,
                "replacement_line": (
                    f"{match.group('indent')}{match.group('base')}->{field_name} = {match.group('rhs')};"
                ),
            },
        )


@dataclass(frozen=True)
class _DataTableProof:
    table_symbol: str
    element_type: str
    elements: tuple[str, ...]
    declaration_span: tuple[int, int]


_DIRECT_TABLE_SYMBOL_DECL_RE = re.compile(
    r"(?m)^[ \t]*(?:extern|static)?[ \t]*(?P<type>[A-Za-z_]\w*(?:[ \t]+[A-Za-z_]\w*)?)"
    r"[ \t]+(?P<symbol>[A-Za-z_]\w*)[ \t]*\[[^\]]*\]"
    r"(?:[ \t]*=[ \t]*\{[^;]*\})?[ \t]*;[ \t]*$"
)


_IMMUTABLE_POINTER_TABLE_RE = re.compile(
    r"(?m)^[ \t]*(?:static[ \t]+)?(?:const[ \t]+)?"
    r"(?P<type>[A-Za-z_]\w*(?:[ \t]+[A-Za-z_]\w*)?)[ \t]*\*[ \t]*const[ \t]+"
    r"(?P<table>[A-Za-z_]\w*)[ \t]*\[[^\]]*\][ \t]*=[ \t]*"
    r"\{(?P<elements>[^{};]*)\}[ \t]*;[ \t]*$"
)


_DATA_TABLE_READ_RE = re.compile(
    r"\b(?P<element>[A-Za-z_]\w*)\s*\[\s*(?P<index>[A-Za-z_]\w*|0x[0-9A-Fa-f]+|\d+)\s*\]"
)


def _mask_spans(text: str, spans: Iterable[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        for idx in range(max(0, start), min(len(chars), end)):
            if chars[idx] != "\n":
                chars[idx] = " "
    return "".join(chars)


def _source_local_direct_table_decls(
    source_text: str,
    *,
    before_offset: int,
) -> dict[str, str]:
    prefix = source_text[:before_offset]
    searchable = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(prefix)
    )
    function_spans = _top_level_function_spans(prefix)
    decls: dict[str, str] = {}
    for match in _DIRECT_TABLE_SYMBOL_DECL_RE.finditer(searchable):
        if _inside_any_span(match.start(), function_spans):
            continue
        if _brace_depth_before(searchable, match.start()) != 0:
            continue
        symbol = match.group("symbol")
        type_name = _normalize_c_type(match.group("type"))
        if symbol in decls and decls[symbol] != type_name:
            decls.pop(symbol, None)
            continue
        decls[symbol] = type_name
    return decls


def _source_has_identity_mutation(
    source_text: str,
    *,
    table_symbol: str,
    element_symbols: Iterable[str],
    exclude_spans: Iterable[tuple[int, int]],
) -> bool:
    searchable = _mask_spans(
        _blank_disabled_preprocessor_regions(
            _blank_literals_and_comments(source_text)
        ),
        exclude_spans,
    )
    symbols = (table_symbol, *tuple(element_symbols))
    for symbol in symbols:
        if re.search(r"&\s*(?:\(\s*)*" + re.escape(symbol) + r"\b", searchable):
            return True
    table_pattern = re.escape(table_symbol)
    if re.search(r"\b" + table_pattern + r"\s*(?:\[[^\]]+\])?\s*=", searchable):
        return True
    for symbol in element_symbols:
        if re.search(r"\b" + re.escape(symbol) + r"\s*=", searchable):
            return True
    return False


def _source_local_data_tables(
    source_text: str,
    *,
    before_offset: int,
) -> tuple[_DataTableProof, ...]:
    prefix = source_text[:before_offset]
    searchable = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(prefix)
    )
    function_spans = _top_level_function_spans(prefix)
    direct_decls = _source_local_direct_table_decls(
        source_text,
        before_offset=before_offset,
    )
    proofs: list[_DataTableProof] = []
    for match in _IMMUTABLE_POINTER_TABLE_RE.finditer(searchable):
        if _inside_any_span(match.start(), function_spans):
            continue
        if _brace_depth_before(searchable, match.start()) != 0:
            continue
        table_symbol = match.group("table")
        element_type = _normalize_c_type(match.group("type"))
        elements = _split_top_level_csv(match.group("elements"))
        if elements is None or not elements:
            continue
        if not all(_SIMPLE_IDENTIFIER_RE.match(element or "") for element in elements):
            continue
        element_tuple = tuple(elements)
        if len(set(element_tuple)) != len(element_tuple):
            continue
        if any(direct_decls.get(element) != element_type for element in element_tuple):
            continue
        declaration_span = (match.start(), match.end())
        if _source_has_identity_mutation(
            source_text,
            table_symbol=table_symbol,
            element_symbols=element_tuple,
            exclude_spans=(declaration_span,),
        ):
            continue
        proofs.append(
            _DataTableProof(
                table_symbol=table_symbol,
                element_type=element_type,
                elements=element_tuple,
                declaration_span=declaration_span,
            )
        )
    return tuple(proofs)


def _iter_data_table_indirection_anchors(source_text: str, span):
    proofs = _source_local_data_tables(source_text, before_offset=span.sig_start)
    if not proofs:
        return
    by_element: dict[str, list[tuple[_DataTableProof, int]]] = {}
    for proof in proofs:
        if _target_shadows_symbol(source_text, span, proof.table_symbol):
            continue
        for index, element in enumerate(proof.elements):
            if _target_shadows_symbol(source_text, span, element):
                continue
            by_element.setdefault(element, []).append((proof, index))

    body_start = span.body_open
    body_text = source_text[body_start:span.full_end]
    searchable_body = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(body_text)
    )
    for match in _DATA_TABLE_READ_RE.finditer(searchable_body):
        element = match.group("element")
        candidates = by_element.get(element, ())
        if len(candidates) != 1:
            continue
        if _assignment_operator_after(searchable_body, match.end()) is not None:
            continue
        proof, table_index = candidates[0]
        index_expr = match.group("index")
        span_text = source_text[
            body_start + match.start():body_start + match.end()
        ]
        replacement_text = f"{proof.table_symbol}[{table_index}][{index_expr}]"
        yield Anchor(
            mutator_key="rewrite_data_table_indirection",
            span=(body_start + match.start(), body_start + match.end()),
            payload={
                "span_text": span_text,
                "replacement_text": replacement_text,
                "table_symbol": proof.table_symbol,
                "element_symbol": element,
                "table_index": table_index,
                "index_expr": index_expr,
                "element_type": proof.element_type,
                "proof_source": "source-local-immutable-table",
                "target_function": _function_name_for_span(
                    source_text,
                    _blank_literals_and_comments(source_text),
                    span,
                ),
                "declaration_span": proof.declaration_span,
            },
        )
