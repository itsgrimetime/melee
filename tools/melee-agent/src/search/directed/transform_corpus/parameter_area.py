"""Source-transform family: parameter_area."""
from __future__ import annotations

import re
from dataclasses import dataclass
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _blank_disabled_preprocessor_regions, _blank_literals_and_comments, _blank_preprocessor_directives, _contract_make_edit, _line_has_label, _macro_like_statement, _split_top_level_csv
from src.search.directed.transform_corpus.contract_signature import _ContractArg
from typing import Mapping


@dataclass(frozen=True)
class _CallShapeArg:
    text: str
    start: int
    end: int
    type_name: str
    temp_name: str


@dataclass(frozen=True)
class _CallShapeSite:
    ordinal: int
    callee: str
    span: tuple[int, int]
    name_span: tuple[int, int]
    open_paren: int
    close_paren: int
    statement_start: int
    statement_end: int
    indent: str
    arg_count: int
    args: tuple[_CallShapeArg, ...]


@dataclass(frozen=True)
class _CallShapeLocalDecl:
    type_name: str
    name: str
    init: str
    line_start: int
    line_end: int
    name_start: int
    name_end: int


_OUTGOING_PARAM_AREA_MIN_ARGS = 4


_OUTGOING_PARAM_CONTROL_NAMES = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
}


_OUTGOING_PARAM_SIMPLE_TYPES = {
    "bool",
    "BOOL",
    "char",
    "s8",
    "s16",
    "s32",
    "s64",
    "u8",
    "u16",
    "u32",
    "u64",
    "int",
    "short",
    "long",
    "f32",
    "f64",
    "float",
    "double",
}


def _find_matching_paren(text: str, open_paren: int, limit: int) -> int | None:
    depth = 0
    for idx in range(open_paren, min(len(text), limit)):
        ch = text[idx]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return idx
            if depth < 0:
                return None
    return None


def _split_top_level_arg_spans(
    source_text: str,
    searchable: str,
    *,
    start: int,
    end: int,
) -> tuple[_ContractArg, ...] | None:
    args: list[_ContractArg] = []
    depth = 0
    current = start
    for idx in range(start, end):
        ch = searchable[idx]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return None
        elif ch == "," and depth == 0:
            arg = _trimmed_arg_span(source_text, current, idx)
            if arg is None:
                return None
            args.append(arg)
            current = idx + 1
    if depth != 0:
        return None
    arg = _trimmed_arg_span(source_text, current, end)
    if arg is None:
        return None
    args.append(arg)
    return tuple(args)


def _trimmed_arg_span(
    source_text: str,
    start: int,
    end: int,
) -> _ContractArg | None:
    while start < end and source_text[start].isspace():
        start += 1
    while end > start and source_text[end - 1].isspace():
        end -= 1
    if start >= end:
        return None
    return _ContractArg(text=source_text[start:end], start=start, end=end)


def _normalize_call_shape_type(type_name: str) -> str | None:
    normalized = re.sub(r"\s+", " ", type_name.strip())
    normalized = normalized.replace(" *", "*").replace("* ", "*")
    normalized = normalized.replace("const ", "")
    normalized = normalized.strip()
    if not normalized or normalized == "void":
        return None
    if normalized in _OUTGOING_PARAM_SIMPLE_TYPES:
        return normalized
    if normalized.endswith("*") and normalized.count("*") == 1:
        base = normalized[:-1].strip()
        if re.fullmatch(r"(?:struct\s+)?[A-Za-z_]\w*", base):
            return f"{base}*"
    return None


def _parse_call_shape_decl_type_and_name(text: str) -> tuple[str, str] | None:
    text = text.strip()
    if not text or text == "void" or "..." in text:
        return None
    match = re.match(
        r"^(?P<type>(?:const\s+)?(?:struct\s+)?[A-Za-z_]\w*(?:\s*\*)?)\s*"
        r"(?P<name>[A-Za-z_]\w*)$",
        text,
    )
    if match is None:
        return None
    type_name = _normalize_call_shape_type(match.group("type"))
    if type_name is None:
        return None
    return type_name, match.group("name")


def _call_shape_identifier_types(
    source_text: str,
    span,
    *,
    before_offset: int,
) -> dict[str, str]:
    types: dict[str, str] = {}
    header = source_text[span.sig_start:span.body_open]
    params_start = header.find("(")
    params_end = header.rfind(")")
    if 0 <= params_start < params_end:
        params = _split_top_level_csv(header[params_start + 1:params_end])
        if params is not None:
            for param in params:
                parsed = _parse_call_shape_decl_type_and_name(param)
                if parsed is not None:
                    type_name, name = parsed
                    types[name] = type_name

    body_prefix = source_text[span.body_open + 1:before_offset]
    decl_re = re.compile(
        r"(?m)^[ \t]*(?P<type>(?:const\s+)?(?:struct\s+)?[A-Za-z_]\w*"
        r"(?:\s*\*)?)\s*(?P<name>[A-Za-z_]\w*)\s*(?:[=;,\[])"
    )
    for match in decl_re.finditer(body_prefix):
        parsed_type = _normalize_call_shape_type(match.group("type"))
        if parsed_type is not None:
            types[match.group("name")] = parsed_type
    return types


def _call_shape_cast_type(arg_text: str) -> str | None:
    match = re.match(
        r"^\(\s*(?P<type>(?:const\s+)?(?:struct\s+)?[A-Za-z_]\w*"
        r"(?:\s*\*)?)\s*\)",
        arg_text.strip(),
    )
    if match is None:
        return None
    return _normalize_call_shape_type(match.group("type"))


def _infer_call_shape_arg_type(
    arg_text: str,
    *,
    identifier_types: Mapping[str, str],
) -> str | None:
    stripped = arg_text.strip()
    cast_type = _call_shape_cast_type(stripped)
    if cast_type is not None:
        return cast_type
    if re.fullmatch(r"[A-Za-z_]\w*", stripped):
        return identifier_types.get(stripped)
    if re.fullmatch(r"(?:0x[0-9A-Fa-f]+|\d+)[ULul]*", stripped):
        return "int"

    names = re.findall(r"\b[A-Za-z_]\w*\b", stripped)
    name_types = [identifier_types[name] for name in names if name in identifier_types]
    if any(type_name in {"f32", "float"} for type_name in name_types):
        return "f32"
    if any(type_name in {"f64", "double"} for type_name in name_types):
        return "f64"
    if re.search(r"(?:\d+\.\d*|\d*\.\d+)F?\b", stripped):
        return "f32"
    if "." in stripped and "->" not in stripped:
        return "f32"
    if any(type_name.endswith("*") for type_name in name_types):
        pointer_types = [type_name for type_name in name_types if type_name.endswith("*")]
        if len(set(pointer_types)) == 1:
            return pointer_types[0]
    if name_types and all(
        type_name in _OUTGOING_PARAM_SIMPLE_TYPES
        and type_name not in {"f32", "f64", "float", "double"}
        for type_name in name_types
    ):
        return "int"
    return None


def _call_shape_arg_has_nested_call(searchable: str, arg: _ContractArg) -> bool:
    return re.search(r"\b[A-Za-z_]\w*\s*\(", searchable[arg.start:arg.end]) is not None


def _call_shape_arg_materialization_start(arg_count: int) -> int:
    return 1 if arg_count <= 4 else 2


def _call_shape_statement_bounds(
    source_text: str,
    searchable: str,
    *,
    body_start: int,
    body_end: int,
    name_start: int,
    close_paren: int,
) -> tuple[int, int, str] | None:
    line_start = source_text.rfind("\n", body_start, name_start) + 1
    line_start = max(line_start, body_start + 1)
    statement_end = searchable.find(";", close_paren, body_end)
    if statement_end < 0:
        return None
    if searchable[close_paren + 1:statement_end].strip():
        return None
    prefix = searchable[line_start:name_start]
    if "\n" in prefix:
        return None
    stripped = prefix.strip()
    if stripped:
        if not stripped.endswith("="):
            return None
        if re.search(r"\b(?:if|for|while|switch|return|sizeof)\b", stripped):
            return None
        if "," in stripped:
            return None
    line = source_text[line_start:statement_end + 1]
    if _line_has_label(line) or _macro_like_statement(line):
        return None
    indent = re.match(r"[ \t]*", source_text[line_start:name_start]).group(0)
    return line_start, statement_end + 1, indent


def _call_shape_temp_name(source_text: str, call_ordinal: int, arg_index: int) -> str:
    base = f"param_area_{call_ordinal}_{arg_index}"
    if re.search(r"\b" + re.escape(base) + r"\b", source_text) is None:
        return base
    suffix = 1
    while True:
        candidate = f"{base}_{suffix}"
        if re.search(r"\b" + re.escape(candidate) + r"\b", source_text) is None:
            return candidate
        suffix += 1


def _call_shape_site_from_match(
    source_text: str,
    searchable: str,
    span,
    *,
    ordinal: int,
    callee: str,
    name_start: int,
    name_end: int,
    open_paren: int,
    close_paren: int,
) -> _CallShapeSite | None:
    if callee in _OUTGOING_PARAM_CONTROL_NAMES:
        return None
    bounds = _call_shape_statement_bounds(
        source_text,
        searchable,
        body_start=span.body_open,
        body_end=span.body_close,
        name_start=name_start,
        close_paren=close_paren,
    )
    if bounds is None:
        return None
    statement_start, statement_end, indent = bounds
    args = _split_top_level_arg_spans(
        source_text,
        searchable,
        start=open_paren + 1,
        end=close_paren,
    )
    if args is None or len(args) < _OUTGOING_PARAM_AREA_MIN_ARGS:
        return None
    if any(_call_shape_arg_has_nested_call(searchable, arg) for arg in args):
        return None

    identifier_types = _call_shape_identifier_types(
        source_text,
        span,
        before_offset=statement_start,
    )
    selected: list[_CallShapeArg] = []
    first_index = _call_shape_arg_materialization_start(len(args))
    for arg_index, arg in enumerate(args):
        if arg_index < first_index:
            continue
        type_name = _infer_call_shape_arg_type(
            arg.text,
            identifier_types=identifier_types,
        )
        if type_name is None:
            continue
        temp_name = _call_shape_temp_name(source_text, ordinal, arg_index)
        selected.append(
            _CallShapeArg(
                text=arg.text,
                start=arg.start,
                end=arg.end,
                type_name=type_name,
                temp_name=temp_name,
            )
        )
    if not selected:
        return None
    return _CallShapeSite(
        ordinal=ordinal,
        callee=callee,
        span=(name_start, close_paren + 1),
        name_span=(name_start, name_end),
        open_paren=open_paren,
        close_paren=close_paren,
        statement_start=statement_start,
        statement_end=statement_end,
        indent=indent,
        arg_count=len(args),
        args=tuple(selected),
    )


def _outgoing_parameter_area_call_sites(
    source_text: str,
    function: str,
    span,
) -> tuple[_CallShapeSite, ...]:
    searchable = _blank_preprocessor_directives(
        _blank_disabled_preprocessor_regions(
            _blank_literals_and_comments(source_text)
        )
    )
    sites: list[_CallShapeSite] = []
    ordinal = 0
    body_start = span.body_open + 1
    body_end = span.body_close
    pattern = re.compile(r"\b(?P<callee>[A-Za-z_]\w*)\s*\(")
    for match in pattern.finditer(searchable, body_start, body_end):
        callee = match.group("callee")
        name_start = match.start("callee")
        name_end = match.end("callee")
        if name_start > 0 and searchable[name_start - 1] in ".>":
            continue
        open_paren = match.end() - 1
        close_paren = _find_matching_paren(searchable, open_paren, body_end)
        if close_paren is None:
            continue
        site = _call_shape_site_from_match(
            source_text,
            searchable,
            span,
            ordinal=ordinal,
            callee=callee,
            name_start=name_start,
            name_end=name_end,
            open_paren=open_paren,
            close_paren=close_paren,
        )
        if site is not None:
            sites.append(site)
            ordinal += 1
    return tuple(sites)


def _call_shape_edits(
    source_text: str,
    sites: tuple[_CallShapeSite, ...],
) -> list[dict[str, object]]:
    edits: list[dict[str, object]] = []
    for site in sites:
        declarations = "".join(
            f"{site.indent}{arg.type_name} {arg.temp_name} = {arg.text};\n"
            for arg in site.args
        )
        edits.append(
            _contract_make_edit(
                source_text,
                start=site.statement_start,
                end=site.statement_start,
                replacement_text=declarations,
                kind="call-argument-temp-declarations",
            )
        )
        for arg in site.args:
            edits.append(
                _contract_make_edit(
                    source_text,
                    start=arg.start,
                    end=arg.end,
                    replacement_text=arg.temp_name,
                    kind="call-argument-temp-use",
                )
            )
    return edits


def _call_shape_site_payload(site: _CallShapeSite) -> dict[str, object]:
    return {
        "callee": site.callee,
        "span": list(site.span),
        "statement_span": [site.statement_start, site.statement_end],
        "argument_count": site.arg_count,
        "tempized_argument_indices": [
            int(arg.temp_name.rsplit("_", 1)[-1])
            for arg in site.args
            if arg.temp_name.rsplit("_", 1)[-1].isdigit()
        ],
        "tempized_arguments": [
            {
                "index": int(arg.temp_name.rsplit("_", 1)[-1])
                if arg.temp_name.rsplit("_", 1)[-1].isdigit()
                else None,
                "type": arg.type_name,
                "expression": arg.text,
                "temp_name": arg.temp_name,
                "span": [arg.start, arg.end],
            }
            for arg in site.args
        ],
    }


def _parse_call_shape_local_decl_line(
    line: str,
    *,
    indent: str,
    line_start: int,
    line_end: int,
) -> _CallShapeLocalDecl | None:
    if not line.startswith(indent):
        return None
    if line[:len(indent)] != indent:
        return None
    if line[len(indent):].startswith((" ", "\t")):
        return None
    match = re.match(
        re.escape(indent)
        + r"(?P<type>(?:const\s+)?(?:struct\s+)?[A-Za-z_]\w*(?:\s*\*)?)\s+"
        r"(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<init>.+);\s*$",
        line,
    )
    if match is None:
        return None
    type_name = _normalize_call_shape_type(match.group("type"))
    if type_name is None:
        return None
    init = match.group("init").strip()
    if not _safe_call_shape_dematerialize_init(init):
        return None
    return _CallShapeLocalDecl(
        type_name=type_name,
        name=match.group("name"),
        init=init,
        line_start=line_start,
        line_end=line_end,
        name_start=line_start + match.start("name"),
        name_end=line_start + match.end("name"),
    )


def _safe_call_shape_dematerialize_init(init: str) -> bool:
    if not init or any(token in init for token in ("++", "--")):
        return False
    if any(ch in init for ch in "{}"):
        return False
    if "=" in init:
        return False
    if re.search(r"\b[A-Za-z_]\w*\s*\(", init):
        return False
    parts = _split_top_level_csv(init)
    return parts == [init.strip()]


def _call_shape_previous_decl_block(
    source_text: str,
    site: _CallShapeSite,
) -> tuple[_CallShapeLocalDecl, ...]:
    decls: list[_CallShapeLocalDecl] = []
    cursor = site.statement_start
    while cursor > 0:
        line_start = source_text.rfind("\n", 0, cursor - 1) + 1
        if line_start >= cursor:
            break
        line = source_text[line_start:cursor]
        line_without_newline = line[:-1] if line.endswith("\n") else line
        if not line_without_newline.strip():
            break
        decl = _parse_call_shape_local_decl_line(
            line_without_newline,
            indent=site.indent,
            line_start=line_start,
            line_end=cursor,
        )
        if decl is None:
            break
        decls.append(decl)
        cursor = line_start
    return tuple(reversed(decls))


def _call_shape_enclosing_scope_bounds(
    searchable: str,
    span,
    site: _CallShapeSite,
) -> tuple[int, int]:
    stack: list[int] = []
    for idx in range(span.body_open, site.statement_start):
        ch = searchable[idx]
        if ch == "{":
            stack.append(idx)
        elif ch == "}" and stack:
            stack.pop()
    scope_open = stack[-1] if stack else span.body_open
    depth = 0
    for idx in range(scope_open, span.body_close + 1):
        ch = searchable[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return scope_open + 1, idx
    return scope_open + 1, span.body_close


def _call_shape_dematerializable_args(
    source_text: str,
    searchable: str,
    span,
    site: _CallShapeSite,
) -> tuple[tuple[_ContractArg, _CallShapeLocalDecl], ...]:
    decls = {
        decl.name: decl
        for decl in _call_shape_previous_decl_block(source_text, site)
    }
    if not decls:
        return ()
    scope_start, scope_end = _call_shape_enclosing_scope_bounds(
        searchable,
        span,
        site,
    )
    scope_searchable = searchable[scope_start:scope_end]
    args = _split_top_level_arg_spans(
        source_text,
        searchable,
        start=site.open_paren + 1,
        end=site.close_paren,
    )
    if args is None:
        return ()
    selected: list[tuple[_ContractArg, _CallShapeLocalDecl]] = []
    first_index = _call_shape_arg_materialization_start(len(args))
    for arg_index, arg in enumerate(args):
        if arg_index < first_index:
            continue
        name = arg.text.strip()
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            continue
        decl = decls.get(name)
        if decl is None:
            continue
        if len(re.findall(r"\b" + re.escape(name) + r"\b", scope_searchable)) != 2:
            continue
        selected.append((arg, decl))
    return tuple(selected)


def _call_shape_dematerialize_edits(
    source_text: str,
    pairs: tuple[tuple[_ContractArg, _CallShapeLocalDecl], ...],
) -> list[dict[str, object]]:
    edits: list[dict[str, object]] = []
    removed_lines: set[tuple[int, int]] = set()
    for arg, decl in pairs:
        if (decl.line_start, decl.line_end) not in removed_lines:
            edits.append(
                _contract_make_edit(
                    source_text,
                    start=decl.line_start,
                    end=decl.line_end,
                    replacement_text="",
                    kind="call-argument-temp-declaration-removal",
                )
            )
            removed_lines.add((decl.line_start, decl.line_end))
        edits.append(
            _contract_make_edit(
                source_text,
                start=arg.start,
                end=arg.end,
                replacement_text=decl.init,
                kind="call-argument-temp-dematerialize-use",
            )
        )
    return edits


def _call_shape_dematerialize_payload(
    *,
    site: _CallShapeSite,
    pairs: tuple[tuple[_ContractArg, _CallShapeLocalDecl], ...],
    edits: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "mode": "call-site-dematerialize",
        "proof_source": "immediate-one-use-call-argument-local",
        "requires_full_unit_source": False,
        "callee": site.callee,
        "argument_count": site.arg_count,
        "call_site_count": 1,
        "dematerialized_locals": [decl.name for _arg, decl in pairs],
        "updated_call_sites": [
            {
                "callee": site.callee,
                "span": list(site.span),
                "statement_span": [site.statement_start, site.statement_end],
                "argument_count": site.arg_count,
                "dematerialized_arguments": [
                    {
                        "name": decl.name,
                        "type": decl.type_name,
                        "replacement_text": decl.init,
                        "argument_span": [arg.start, arg.end],
                        "declaration_span": [decl.line_start, decl.line_end],
                    }
                    for arg, decl in pairs
                ],
            }
        ],
        "edits": edits,
    }


def _call_shape_dematerialize_batch_payload(
    *,
    callee: str,
    items: tuple[tuple[_CallShapeSite, tuple[tuple[_ContractArg, _CallShapeLocalDecl], ...]], ...],
    edits: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "mode": "same-callee-dematerialize-batch",
        "proof_source": "immediate-one-use-call-argument-local",
        "requires_full_unit_source": False,
        "callee": callee,
        "argument_count": items[0][0].arg_count,
        "call_site_count": len(items),
        "dematerialized_locals": [
            decl.name
            for _site, pairs in items
            for _arg, decl in pairs
        ],
        "updated_call_sites": [
            {
                "callee": site.callee,
                "span": list(site.span),
                "statement_span": [site.statement_start, site.statement_end],
                "argument_count": site.arg_count,
                "dematerialized_arguments": [
                    {
                        "name": decl.name,
                        "type": decl.type_name,
                        "replacement_text": decl.init,
                        "argument_span": [arg.start, arg.end],
                        "declaration_span": [decl.line_start, decl.line_end],
                    }
                    for arg, decl in pairs
                ],
            }
            for site, pairs in items
        ],
        "edits": edits,
    }


def _call_shape_anchor_payload(
    *,
    mode: str,
    sites: tuple[_CallShapeSite, ...],
    edits: list[dict[str, object]],
) -> dict[str, object]:
    first = sites[0]
    payload = {
        "mode": mode,
        "proof_source": "target-function-call-site",
        "requires_full_unit_source": False,
        "callee": first.callee,
        "argument_count": first.arg_count,
        "call_site_count": len(sites),
        "tempized_argument_indices": [
            int(arg.temp_name.rsplit("_", 1)[-1])
            for arg in first.args
            if arg.temp_name.rsplit("_", 1)[-1].isdigit()
        ],
        "updated_call_sites": [_call_shape_site_payload(site) for site in sites],
        "edits": edits,
    }
    return payload


def _iter_outgoing_parameter_area_shape_anchors(
    source_text: str,
    function: str,
    span,
):
    sites = _outgoing_parameter_area_call_sites(source_text, function, span)
    searchable = _blank_preprocessor_directives(
        _blank_disabled_preprocessor_regions(
            _blank_literals_and_comments(source_text)
        )
    )
    dematerializable: list[
        tuple[_CallShapeSite, tuple[tuple[_ContractArg, _CallShapeLocalDecl], ...]]
    ] = []
    for site in sites:
        pairs = _call_shape_dematerializable_args(
            source_text,
            searchable,
            span,
            site,
        )
        if not pairs:
            continue
        dematerializable.append((site, pairs))
    by_dematerialize_callee: dict[
        str,
        list[tuple[_CallShapeSite, tuple[tuple[_ContractArg, _CallShapeLocalDecl], ...]]],
    ] = {}
    for site, pairs in dematerializable:
        by_dematerialize_callee.setdefault(site.callee, []).append((site, pairs))
    for callee, items_for_callee in by_dematerialize_callee.items():
        if len(items_for_callee) < 2:
            continue
        batch = tuple(items_for_callee[:3])
        edits = [
            edit
            for _site, pairs in batch
            for edit in _call_shape_dematerialize_edits(source_text, pairs)
        ]
        yield Anchor(
            mutator_key="materialize_outgoing_parameter_area_call_args",
            span=(
                min(int(edit["start"]) for edit in edits),
                max(int(edit["end"]) for edit in edits),
            ),
            payload=_call_shape_dematerialize_batch_payload(
                callee=callee,
                items=batch,
                edits=edits,
            ),
        )

    for site, pairs in dematerializable:
        edits = _call_shape_dematerialize_edits(source_text, pairs)
        yield Anchor(
            mutator_key="materialize_outgoing_parameter_area_call_args",
            span=(
                min(int(edit["start"]) for edit in edits),
                max(int(edit["end"]) for edit in edits),
            ),
            payload=_call_shape_dematerialize_payload(
                site=site,
                pairs=pairs,
                edits=edits,
            ),
        )

    for site in sites:
        edits = _call_shape_edits(source_text, (site,))
        yield Anchor(
            mutator_key="materialize_outgoing_parameter_area_call_args",
            span=(
                min(int(edit["start"]) for edit in edits),
                max(int(edit["end"]) for edit in edits),
            ),
            payload=_call_shape_anchor_payload(
                mode="call-site",
                sites=(site,),
                edits=edits,
            ),
        )

    by_callee: dict[str, list[_CallShapeSite]] = {}
    for site in sites:
        by_callee.setdefault(site.callee, []).append(site)
    for callee_sites in by_callee.values():
        if len(callee_sites) < 2:
            continue
        batch = tuple(callee_sites[:3])
        edits = _call_shape_edits(source_text, batch)
        yield Anchor(
            mutator_key="materialize_outgoing_parameter_area_call_args",
            span=(
                min(int(edit["start"]) for edit in edits),
                max(int(edit["end"]) for edit in edits),
            ),
            payload=_call_shape_anchor_payload(
                mode="same-callee-batch",
                sites=batch,
                edits=edits,
            ),
        )
