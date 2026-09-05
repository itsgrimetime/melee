"""Source-transform family: helper_extract."""
from __future__ import annotations

import re
from src.mwcc_debug.source_patch import find_function_definitions
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _SIMPLE_ASSIGNMENT_RE, _SIMPLE_IDENTIFIER_RE, _blank_literals_and_comments, _is_scalar_type, _line_containing, _normalize_type_name, _parse_signature_params, _split_top_level_csv, _text_line_records
from typing import Mapping


_INTEGER_LITERAL_RE = re.compile(r"^(?:0x[0-9A-Fa-f]+|\d+)$")


_SIMPLE_HELPER_EXPR_CHARS_RE = re.compile(r"^[A-Za-z0-9_+\-*/%() \t]+$")


_SIMPLE_LOCAL_DECL_RE = re.compile(
    r"^[ \t]*(?P<type>bool|BOOL|s8|s16|s32|s64|u8|u16|u32|u64|int|short|long|f32|f64|float|double)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*;\s*$"
)


_HELPER_BODY_FORBIDDEN_WORD_RE = re.compile(
    r"\b(?:case|default|goto|if|for|while|do|switch)\b"
)


def _simple_value_arg(expr: str) -> bool:
    expr = expr.strip()
    return (
        _SIMPLE_IDENTIFIER_RE.match(expr) is not None
        or _INTEGER_LITERAL_RE.match(expr) is not None
    )


def _simple_helper_expr(expr: str, allowed_identifiers: set[str]) -> bool:
    expr = expr.strip()
    if not expr or _SIMPLE_HELPER_EXPR_CHARS_RE.match(expr) is None:
        return False
    forbidden = (
        "#",
        ".",
        "->",
        "[",
        "]",
        "&",
        "++",
        "--",
        "&&",
        "||",
        ",",
        "=",
        "!",
        "<",
        ">",
    )
    if any(token in expr for token in forbidden):
        return False
    if re.search(r"\b[A-Za-z_]\w*\s*\(", expr):
        return False
    identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", expr))
    return identifiers <= allowed_identifiers


def _identifier_order(expr: str) -> tuple[str, ...]:
    ordered: list[str] = []
    for name in re.findall(r"\b[A-Za-z_]\w*\b", expr):
        if name not in ordered:
            ordered.append(name)
    return tuple(ordered)


def _parse_scalar_signature(signature: str, *, require_static: bool = False):
    prefix = r"static\s+" if require_static else r"(?:static\s+)?"
    match = re.match(
        rf"^{prefix}(?P<type>bool|BOOL|s8|s16|s32|s64|u8|u16|u32|u64|int|short|long|f32|f64|float|double)\s+"
        r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>.*)\)\s*$",
        signature.strip(),
        re.DOTALL,
    )
    if match is None:
        return None
    params_text = match.group("params").strip()
    if not params_text or params_text == "void":
        params: tuple[tuple[str, str], ...] = ()
    else:
        raw_params = _split_top_level_csv(params_text)
        if raw_params is None:
            return None
        parsed: list[tuple[str, str]] = []
        for raw_param in raw_params:
            param_match = re.match(
                r"^(?P<type>bool|BOOL|s8|s16|s32|s64|u8|u16|u32|u64|int|short|long|f32|f64|float|double)\s+"
                r"(?P<name>[A-Za-z_]\w*)$",
                raw_param.strip(),
            )
            if param_match is None:
                return None
            parsed.append((
                _normalize_type_name(param_match.group("type")),
                param_match.group("name"),
            ))
        params = tuple(parsed)
    return _normalize_type_name(match.group("type")), match.group("name"), params


def _helper_body_has_forbidden_shape(body_inner: str) -> bool:
    searchable = _blank_literals_and_comments(body_inner)
    if "#" in searchable or "{" in searchable or "}" in searchable:
        return True
    if _HELPER_BODY_FORBIDDEN_WORD_RE.search(searchable):
        return True
    if re.search(r"(?m)^[ \t]*(?:[A-Za-z_]\w*\s*)?:\s*$", searchable):
        return True
    return False


def _extract_static_helper_expr(source_text: str, span):
    signature = source_text[span.sig_start:span.body_open].strip()
    parsed = _parse_scalar_signature(signature, require_static=True)
    if parsed is None:
        return None
    return_type, helper_name, params = parsed
    param_names = {name for _type, name in params}
    body_inner = source_text[span.body_open + 1:span.body_close]
    if _helper_body_has_forbidden_shape(body_inner):
        return None
    lines = [line.strip() for line in body_inner.splitlines() if line.strip()]
    if len([line for line in lines if line.startswith("return ")]) != 1:
        return None
    expr: str | None = None
    if len(lines) == 1:
        match = re.match(r"^return\s+(?P<expr>.+);\s*$", lines[0])
        if match is not None:
            expr = match.group("expr").strip()
    elif len(lines) == 3:
        decl = re.match(
            r"^(?P<type>bool|BOOL|s8|s16|s32|s64|u8|u16|u32|u64|int|short|long|f32|f64|float|double)\s+"
            r"(?P<var>[A-Za-z_]\w*)\s*;\s*$",
            lines[0],
        )
        assign = re.match(r"^(?P<var>[A-Za-z_]\w*)\s*=\s*(?P<expr>.+);\s*$", lines[1])
        ret = re.match(r"^return\s+(?P<var>[A-Za-z_]\w*)\s*;\s*$", lines[2])
        if (
            decl is not None
            and assign is not None
            and ret is not None
            and decl.group("var") == assign.group("var") == ret.group("var")
            and _is_scalar_type(decl.group("type"))
        ):
            expr = assign.group("expr").strip()
    if expr is None or not _simple_helper_expr(expr, param_names):
        return None
    param_types = {name: type_name for type_name, name in params}
    if any(param_types[name] != return_type for name in _identifier_order(expr)):
        return None
    return {
        "helper_name": helper_name,
        "return_type": return_type,
        "params": params,
        "expr": expr,
        "span": (span.sig_start, span.full_end),
    }


def _substitute_helper_expr(expr: str, parameter_map: tuple[tuple[str, str], ...]) -> str:
    out = expr
    for param_name, arg in parameter_map:
        out = re.sub(r"\b" + re.escape(param_name) + r"\b", arg, out)
    return out


def _iter_helper_inline_anchors(source_text: str, function: str, target_span):
    helpers = []
    for span in find_function_definitions(source_text):
        if span.name == function:
            continue
        helper = _extract_static_helper_expr(source_text, span)
        if helper is not None:
            helpers.append(helper)
    if not helpers:
        return
    body_text = source_text[target_span.body_open:target_span.full_end]
    if _target_body_has_helper_extraction_barrier(body_text):
        return
    body_start = target_span.body_open
    records = _text_line_records(body_text)
    searchable_records = _text_line_records(_blank_literals_and_comments(body_text))
    for helper in helpers:
        helper_name = str(helper["helper_name"])
        call_re = re.compile(r"\b" + re.escape(helper_name) + r"\s*\((?P<args>[^()]*)\)")
        params = tuple(helper["params"])
        for (start, end, line), (_search_start, _search_end, searchable) in zip(
            records, searchable_records
        ):
            matches = list(call_re.finditer(searchable))
            if len(matches) != 1:
                continue
            args = _split_top_level_csv(matches[0].group("args"))
            if args is None or len(args) != len(params):
                continue
            args = [arg.strip() for arg in args]
            if not all(_simple_value_arg(arg) for arg in args):
                continue
            parameter_map = tuple((param_name, arg) for (_type, param_name), arg in zip(params, args))
            replacement_expr = _substitute_helper_expr(str(helper["expr"]), parameter_map)
            replacement_line = (
                line[: matches[0].start()] + f"({replacement_expr})" + line[matches[0].end():]
            )
            if replacement_line == line:
                continue
            yield Anchor(
                mutator_key="inline_simple_helper_call",
                span=(body_start + start, body_start + end),
                payload={
                    "line": line,
                    "replacement_line": replacement_line,
                    "helper_name": helper_name,
                    "helper_span": helper["span"],
                    "return_expr": helper["expr"],
                    "parameter_map": parameter_map,
                },
            )


def _scalar_type_map_for_function(source_text: str, span) -> dict[str, str]:
    signature = source_text[span.sig_start:span.body_open].strip()
    type_map: dict[str, str] = {}
    type_map.update({name: type_name for type_name, name in _parse_signature_params(signature)})
    body_text = source_text[span.body_open:span.full_end]
    for line in body_text.splitlines():
        match = _SIMPLE_LOCAL_DECL_RE.match(line)
        if match is not None:
            type_map[match.group("name")] = _normalize_type_name(match.group("type"))
    return type_map


def _target_body_has_helper_extraction_barrier(body_text: str) -> bool:
    searchable = _blank_literals_and_comments(body_text)
    if "#" in searchable:
        return True
    if re.search(r"(?m)^[ \t]*(?:case\b.*:|default:|[A-Za-z_]\w*\s*:)", searchable):
        return True
    return False


def _rhs_operand_order(rhs: str, type_map: Mapping[str, str]) -> tuple[str, ...] | None:
    if not _simple_helper_expr(rhs, set(type_map)):
        return None
    ordered: list[str] = []
    for name in re.findall(r"\b[A-Za-z_]\w*\b", rhs):
        if name not in type_map:
            return None
        if name not in ordered:
            ordered.append(name)
    return tuple(ordered)


def _next_helper_shape_name(source_text: str, function: str, ordinal: int = 0) -> str:
    while True:
        candidate = f"{function}__helper_shape_{ordinal}"
        if re.search(r"\b" + re.escape(candidate) + r"\b", source_text) is None:
            return candidate
        ordinal += 1


def _iter_helper_extract_anchors(source_text: str, function: str, target_span):
    body_text = source_text[target_span.body_open:target_span.full_end]
    if _target_body_has_helper_extraction_barrier(body_text):
        return
    type_map = _scalar_type_map_for_function(source_text, target_span)
    if not type_map:
        return
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for line in body_text.splitlines():
        match = _SIMPLE_ASSIGNMENT_RE.match(line)
        if match is None:
            continue
        lhs = match.group("lhs")
        rhs = match.group("rhs").strip()
        if lhs not in type_map:
            continue
        if _rhs_operand_order(rhs, type_map) is None:
            continue
        groups.setdefault(rhs, []).append((line, lhs, match.group("indent")))
    ordinal = 0
    insert_before = _line_containing(source_text, target_span.body_open)
    for rhs, entries in groups.items():
        if len(entries) < 2:
            continue
        dest_types = {type_map[lhs] for _line, lhs, _indent in entries}
        if len(dest_types) != 1:
            continue
        operand_order = _rhs_operand_order(rhs, type_map)
        if operand_order is None:
            continue
        helper_name = _next_helper_shape_name(source_text, function, ordinal)
        ordinal += 1
        params = ", ".join(f"{type_map[name]} {name}" for name in operand_order)
        call_args = ", ".join(operand_order)
        if not params:
            params = "void"
        helper_text = (
            f"static {next(iter(dest_types))} {helper_name}({params}) {{\n"
            f"    return {rhs};\n"
            "}\n"
            "\n"
        )
        replacements = tuple(
            (
                line,
                f"{indent}{lhs} = {helper_name}({call_args});",
            )
            for line, lhs, indent in entries
        )
        yield Anchor(
            mutator_key="extract_repeated_assignment_helper",
            span=(target_span.sig_start, target_span.full_end),
            payload={
                "insert_before": insert_before,
                "helper_text": helper_text,
                "line_replacements": replacements,
                "helper_name": helper_name,
                "target_function": function,
                "rhs": rhs,
                "operand_order": operand_order,
                "operand_types": tuple((name, type_map[name]) for name in operand_order),
            },
        )


def _iter_helper_shape_anchors(source_text: str, function: str, span):
    yield from _iter_helper_inline_anchors(source_text, function, span)
    yield from _iter_helper_extract_anchors(source_text, function, span)
