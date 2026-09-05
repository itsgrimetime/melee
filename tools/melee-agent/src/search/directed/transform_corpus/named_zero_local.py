"""Source-transform family: named_zero_local."""
from __future__ import annotations

import re
from dataclasses import dataclass
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _blank_disabled_preprocessor_regions, _blank_literals_and_comments, _inside_any_span, _normalize_c_type, _split_top_level_csv, _text_line_records_with_newline, _top_level_function_spans


def _function_body_insert_offset_and_indent(
    source_text: str,
    span,
) -> tuple[int, str]:
    insert_at = span.body_open + 1
    if source_text.startswith("\r\n", insert_at):
        insert_at += 2
    elif insert_at < len(source_text) and source_text[insert_at] == "\n":
        insert_at += 1
    body_inner = source_text[span.body_open + 1:span.body_close]
    indent_match = re.search(r"(?m)^[ \t]+(?=\S)", body_inner)
    indent = indent_match.group(0) if indent_match is not None else "    "
    return insert_at, indent


def _named_zero_candidate_name(expr_text: str) -> str | None:
    expr = re.sub(r"\[[^\]]*\]", "", expr_text)
    field_matches = re.findall(r"(?:->|\.)([A-Za-z_]\w*)", expr)
    if field_matches:
        base = field_matches[-1]
    else:
        names = re.findall(r"\b[A-Za-z_]\w*\b", expr)
        if not names:
            return None
        base = names[-1]
    return f"{base}_null"


def _named_zero_expr_supported(expr_text: str) -> bool:
    if any(token in expr_text for token in ("&&", "||", "?", ":")):
        return False
    return re.fullmatch(
        r"[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*|\[[^\]\n]+\])*",
        expr_text.strip(),
    ) is not None


@dataclass(frozen=True)
class _NamedZeroBinding:
    type_name: str
    is_array: bool


_NAMED_ZERO_POINTER_DECL_RE = re.compile(
    r"^[ \t]*(?P<type>(?:(?:const|volatile)\s+)*(?:struct\s+)?"
    r"[A-Za-z_]\w*(?:\s*\*)+)\s*"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"(?P<array>\[[^\]\n]*\])?\s*(?:=[^;]*)?;\s*$"
)


_NAMED_ZERO_SIMPLE_DECL_RE = re.compile(
    r"^[ \t]*(?:(?:const|volatile|static|register)\s+)*"
    r"(?:(?:struct|enum|union)\s+)?[A-Za-z_]\w*(?:\s*\*)*\s+"
    r"\**\s*(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:\[[^\]\n]*\])?\s*(?:=[^;]*)?;\s*$"
)


_NAMED_ZERO_FUNCTION_POINTER_DECL_RE = re.compile(
    r"^[ \t].*\(\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*\)\s*\([^;]*\)\s*;\s*$"
)


_NAMED_ZERO_DECL_HEAD_REJECTS = frozenset({
    "case",
    "do",
    "else",
    "for",
    "if",
    "return",
    "sizeof",
    "switch",
    "while",
})


def _named_zero_pointer_type(type_text: str) -> str | None:
    normalized = _normalize_c_type(type_text)
    if normalized.count("*") != 1 or not normalized.endswith("*"):
        return None
    base = normalized[:-1]
    if base == "void" or re.fullmatch(r"(?:struct )?[A-Za-z_]\w*", base):
        return normalized
    return None


def _named_zero_decay_pointer_type(type_text: str) -> str | None:
    normalized = _normalize_c_type(type_text)
    if not normalized.endswith("*") or normalized.count("*") < 2:
        return None
    element = normalized[:-1]
    return _named_zero_pointer_type(element)


def _named_zero_scope_stack_at(
    searchable_prefix: str,
    *,
    body_start: int,
    body_open: int,
    rel_offset: int,
) -> tuple[int, ...]:
    stack: list[int] = [body_open]
    for rel, ch in enumerate(searchable_prefix[:rel_offset]):
        if ch == "{":
            stack.append(body_start + rel)
        elif ch == "}" and len(stack) > 1:
            stack.pop()
    return tuple(stack)


def _named_zero_declared_names(line: str) -> set[str]:
    stripped = line.strip()
    if not stripped.endswith(";") or "(" in stripped or stripped.startswith("#"):
        return set()
    match = re.match(
        r"^(?P<type>(?:(?:const|volatile|static|register|signed|unsigned)\s+)*"
        r"(?:(?:struct|enum|union)\s+)?[A-Za-z_]\w*"
        r"(?:\s+[A-Za-z_]\w*)?(?:\s*\*)*)\s+"
        r"(?P<decls>.+);$",
        stripped,
    )
    if match is None:
        return set()
    first_type_token = match.group("type").split()[0]
    if first_type_token in _NAMED_ZERO_DECL_HEAD_REJECTS:
        return set()
    declarators = _split_top_level_csv(match.group("decls"))
    if declarators is None:
        return set()
    names: set[str] = set()
    for declarator in declarators:
        before_init = declarator.split("=", 1)[0].strip()
        name_match = re.match(r"\**\s*(?P<name>[A-Za-z_]\w*)\b", before_init)
        if name_match is not None:
            names.add(name_match.group("name"))
    return names


def _named_zero_visible_pointer_bindings(
    source_text: str,
    span,
    *,
    before_offset: int,
) -> dict[str, _NamedZeroBinding]:
    bindings: dict[str, _NamedZeroBinding | None] = {}
    header = source_text[span.sig_start:span.body_open]
    params_start = header.find("(")
    params_end = header.rfind(")")
    if 0 <= params_start < params_end:
        params = _split_top_level_csv(header[params_start + 1:params_end])
        if params is not None:
            for param in params:
                match = re.match(
                    r"^(?P<type>(?:(?:const|volatile)\s+)*(?:struct\s+)?"
                    r"[A-Za-z_]\w*(?:\s*\*)+)\s*"
                    r"(?P<name>[A-Za-z_]\w*)\s*(?P<array>\[[^\]]*\])?$",
                    param.strip(),
                )
                if match is None:
                    continue
                pointer_type = _named_zero_pointer_type(match.group("type"))
                if pointer_type is None:
                    continue
                bindings[match.group("name")] = _NamedZeroBinding(
                    type_name=pointer_type,
                    is_array=bool(match.group("array")),
                )

    body_start = span.body_open + 1
    body_prefix = source_text[body_start:before_offset]
    searchable_prefix = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(body_prefix)
    )
    active_scopes = set(
        _named_zero_scope_stack_at(
            searchable_prefix,
            body_start=body_start,
            body_open=span.body_open,
            rel_offset=len(searchable_prefix),
        )
    )
    for raw_line, search_line in zip(
        _text_line_records_with_newline(body_prefix),
        _text_line_records_with_newline(searchable_prefix),
    ):
        line_scope = _named_zero_scope_stack_at(
            searchable_prefix,
            body_start=body_start,
            body_open=span.body_open,
            rel_offset=raw_line[0],
        )[-1]
        if line_scope not in active_scopes:
            continue
        decl_line = search_line[3]
        match = _NAMED_ZERO_POINTER_DECL_RE.match(decl_line)
        if match is not None:
            pointer_type = _named_zero_pointer_type(match.group("type"))
            if pointer_type is not None:
                bindings[match.group("name")] = _NamedZeroBinding(
                    type_name=pointer_type,
                    is_array=bool(match.group("array")),
                )
            else:
                for name in _named_zero_declared_names(decl_line):
                    bindings[name] = None
            continue
        shadow = _NAMED_ZERO_SIMPLE_DECL_RE.match(decl_line)
        if shadow is None:
            shadow = _NAMED_ZERO_FUNCTION_POINTER_DECL_RE.match(decl_line)
        if shadow is not None:
            bindings[shadow.group("name")] = None
            continue
        for name in _named_zero_declared_names(decl_line):
            bindings[name] = None
    return {
        name: binding
        for name, binding in bindings.items()
        if binding is not None
    }


def _named_zero_struct_pointer_array_fields(
    source_text: str,
    *,
    before_offset: int,
) -> dict[tuple[str, str], str]:
    fields: dict[tuple[str, str], str] = {}
    prefix = source_text[:before_offset]
    searchable = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(prefix)
    )
    function_spans = _top_level_function_spans(prefix)
    pattern = re.compile(
        r"typedef\s+struct\s+(?P<tag>[A-Za-z_]\w*)\s*{\s*(?P<body>.*?)\s*}"
        r"\s*(?P<name>[A-Za-z_]\w*)\s*;",
        re.DOTALL,
    )
    for match in pattern.finditer(searchable):
        if _inside_any_span(match.start(), function_spans):
            continue
        type_names = {match.group("tag"), match.group("name")}
        body = source_text[match.start("body"):match.end("body")]
        for raw_field in body.split(";"):
            field = raw_field.strip()
            if not field or "," in field or "(" in field or ")" in field:
                continue
            field_match = re.match(
                r"^(?P<type>(?:(?:const|volatile)\s+)*(?:struct\s+)?"
                r"[A-Za-z_]\w*(?:\s*\*)+)\s*"
                r"(?P<name>[A-Za-z_]\w*)\s*\[[^\]\n]+\]$",
                field,
            )
            if field_match is None:
                continue
            pointer_type = _named_zero_pointer_type(field_match.group("type"))
            if pointer_type is None:
                continue
            for type_name in type_names:
                fields[(type_name, field_match.group("name"))] = pointer_type
    return fields


def _named_zero_expr_pointer_type(
    source_text: str,
    span,
    expr_text: str,
    *,
    before_offset: int,
) -> str | None:
    expr = expr_text.strip()
    bindings = _named_zero_visible_pointer_bindings(
        source_text,
        span,
        before_offset=before_offset,
    )

    direct = re.fullmatch(
        r"(?P<name>[A-Za-z_]\w*)(?P<index>\[[^\]\n]+\])?",
        expr,
    )
    if direct is not None:
        binding = bindings.get(direct.group("name"))
        if binding is None:
            return None
        if direct.group("index"):
            if binding.is_array:
                return binding.type_name
            return _named_zero_decay_pointer_type(binding.type_name)
        if not binding.is_array:
            return binding.type_name
        return None

    member = re.fullmatch(
        r"(?P<base>[A-Za-z_]\w*)->(?P<field>[A-Za-z_]\w*)"
        r"(?P<index>\[[^\]\n]+\])",
        expr,
    )
    if member is None:
        return None
    binding = bindings.get(member.group("base"))
    if binding is None or binding.is_array or not binding.type_name.endswith("*"):
        return None
    struct_type = binding.type_name[:-1].strip()
    return _named_zero_struct_pointer_array_fields(
        source_text,
        before_offset=before_offset,
    ).get((struct_type, member.group("field")))


def _named_zero_name_available(source_text: str, span, zero_name: str) -> bool:
    scope_text = source_text[span.sig_start:span.body_close]
    if re.search(r"\b" + re.escape(zero_name) + r"\b", scope_text):
        return False
    macro_re = re.compile(r"(?m)^[ \t]*#[ \t]*define[ \t]+" + re.escape(zero_name) + r"\b")
    return macro_re.search(source_text[:span.body_close]) is None


def _iter_named_zero_local_anchors(source_text: str, function: str, span):
    body_start = span.body_open + 1
    body_inner = source_text[body_start:span.body_close]
    searchable_body = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(body_inner)
    )
    records = _text_line_records_with_newline(body_inner)
    searchable_records = _text_line_records_with_newline(searchable_body)
    insert_at, indent = _function_body_insert_offset_and_indent(source_text, span)
    if_line_re = re.compile(
        r"^(?P<indent>[ \t]*)if\s*\(\s*(?P<expr>.+?)\s*!=\s*(?P<null>NULL)\s*\)\s*{\s*$"
    )
    for idx, (start, end, _end_with_newline, search_line) in enumerate(
        searchable_records
    ):
        if idx >= len(records):
            continue
        if_match = if_line_re.match(search_line)
        if if_match is None:
            continue
        raw_line = records[idx][3]
        if raw_line != search_line:
            continue
        expr_text = raw_line[if_match.start("expr"):if_match.end("expr")].strip()
        if not _named_zero_expr_supported(expr_text):
            continue
        zero_name = _named_zero_candidate_name(expr_text)
        if zero_name is None:
            continue
        if not _named_zero_name_available(source_text, span, zero_name):
            continue
        zero_type = _named_zero_expr_pointer_type(
            source_text,
            span,
            expr_text,
            before_offset=body_start + start,
        )
        if zero_type is None:
            continue

        block_depth = search_line.count("{") - search_line.count("}")
        assign_span: tuple[int, int] | None = None
        block_end_idx = idx
        for next_idx in range(idx + 1, len(searchable_records)):
            line_start, _line_end, _line_end_newline, next_search_line = (
                searchable_records[next_idx]
            )
            if next_idx >= len(records):
                break
            next_raw_line = records[next_idx][3]
            if next_raw_line == next_search_line and assign_span is None:
                assign_match = re.match(
                    r"^[ \t]*(?P<lhs>.+?)\s*=\s*(?P<null>NULL)\s*;\s*$",
                    next_search_line,
                )
                if (
                    assign_match is not None
                    and assign_match.group("lhs").strip() == expr_text
                ):
                    assign_span = (
                        body_start + line_start + assign_match.start("null"),
                        body_start + line_start + assign_match.end("null"),
                    )
            block_depth += next_search_line.count("{") - next_search_line.count("}")
            block_end_idx = next_idx
            if block_depth <= 0:
                break
        if block_depth > 0 or assign_span is None or block_end_idx == idx:
            continue

        decl_line = f"{indent}{zero_type} {zero_name} = NULL;\n"
        yield Anchor(
            mutator_key="introduce_named_zero_local",
            span=(body_start + start + if_match.start("null"), assign_span[1]),
            payload={
                "edits": [
                    {
                        "start": insert_at,
                        "end": insert_at,
                        "span_text": "",
                        "replacement_text": decl_line,
                    },
                    {
                        "start": assign_span[0],
                        "end": assign_span[1],
                        "span_text": "NULL",
                        "replacement_text": zero_name,
                    },
                ],
                "zero_name": zero_name,
                "zero_type": zero_type,
                "expr": expr_text,
                "declaration_text": decl_line.rstrip("\n"),
                "proof_source": "if-null-check-assignment-pair",
                "target_function": function,
            },
        )
