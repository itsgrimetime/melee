"""Source-transform family: type_cast."""
from __future__ import annotations

import re
from dataclasses import dataclass
from src.mwcc_debug.source_patch import find_function_definitions
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _SIMPLE_ASSIGNMENT_RE, _blank_disabled_preprocessor_regions, _blank_literals_and_comments, _blank_preprocessor_directives, _line_depths_from_blanked_text, _normalize_compat_type, _normalize_param_type_text, _source_function_like_macro_names, _split_top_level_csv, _split_top_level_csv_spans, _target_shadows_symbol, _text_line_records
from typing import Mapping


@dataclass(frozen=True)
class _FunctionPointerSignature:
    return_type: str
    param_types: tuple[str, ...]


@dataclass(frozen=True)
class _SourceParam:
    name: str | None
    type_name: str | None
    function_pointer: _FunctionPointerSignature | None = None


@dataclass(frozen=True)
class _SourceFunctionSignature:
    name: str
    return_type: str
    params: tuple[_SourceParam, ...]
    has_varargs: bool = False


@dataclass(frozen=True)
class _ScopedPointerType:
    name: str
    type_name: str | None
    visible_start: int
    visible_end: int
    depth: int


_POINTER_CAST_ARG_RE = re.compile(
    r"^\(\s*(?P<type>(?:(?:const|struct)\s+)*[A-Za-z_]\w*"
    r"(?:\s+const)?(?:\s*\*)+)\s*\)\s*(?P<expr>[A-Za-z_]\w*)\s*$"
)


_FUNCTION_POINTER_CAST_ARG_RE = re.compile(
    r"^\(\s*(?P<type>.+\(\s*\*\s*\)\s*\(.*\))\s*\)\s*"
    r"(?P<expr>[A-Za-z_]\w*)\s*$"
)


_TYPEDEF_FUNCTION_POINTER_CAST_ARG_RE = re.compile(
    r"^\(\s*(?P<type>[A-Za-z_]\w*)\s*\)\s*(?P<expr>[A-Za-z_]\w*)\s*$"
)


_FUNCTION_POINTER_TYPE_RE = re.compile(
    r"^(?P<ret>.+?)\(\s*\*\s*(?P<name>[A-Za-z_]\w*)?\s*\)\s*"
    r"\((?P<params>.*)\)$",
    re.DOTALL,
)


_SIMPLE_CALL_STATEMENT_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<callee>[A-Za-z_]\w*)\s*"
    r"\((?P<args>.*)\)\s*;\s*$"
)


_LOCAL_POINTER_DECL_RE = re.compile(
    r"^[ \t]*(?P<type>(?:(?:const|struct)\s+)*[A-Za-z_]\w*"
    r"(?:\s+const)?(?:\s*\*)+)\s*(?P<name>[A-Za-z_]\w*)"
    r"\s*(?:=[^;]*)?;\s*$"
)


_LOCAL_DECLARATION_RE = re.compile(
    r"^[ \t]*(?!(?:return|if|while|for|switch|case|default|goto|break|continue)\b)"
    r"(?:static[ \t]+|const[ \t]+|volatile[ \t]+|register[ \t]+|"
    r"signed[ \t]+|unsigned[ \t]+|long[ \t]+|short[ \t]+)*"
    r"(?:(?:struct|union|enum)[ \t]+[A-Za-z_]\w*|[A-Za-z_]\w*)\b"
    r"(?P<rest>.*);\s*$"
)


_LOCAL_ALIAS_DECL_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<type>[A-Za-z_]\w*)"
    r"(?P<rest>\s*(?:\*+\s*)?[A-Za-z_]\w*(?:\s*=[^;]*)?;\s*)$"
)


_TYPEDEF_ALIAS_RE = re.compile(
    r"(?m)^[ \t]*typedef\b.*\b(?P<name>[A-Za-z_]\w*)\s*;"
)


_TYPEDEF_STRUCT_RE = re.compile(
    r"typedef\s+struct(?:\s+[A-Za-z_]\w*)?\s*{\s*(?P<body>.*?)\s*}"
    r"\s*(?P<name>[A-Za-z_]\w*)\s*;",
    re.DOTALL,
)


def _normalize_pointer_type(type_text: str) -> str | None:
    normalized = _normalize_compat_type(type_text)
    if normalized is None or "(*" in normalized or not normalized.endswith("*"):
        return None
    return normalized


_TYPE_TOKEN_KEYWORDS = {
    "const",
    "double",
    "enum",
    "float",
    "int",
    "long",
    "register",
    "short",
    "signed",
    "static",
    "struct",
    "union",
    "unsigned",
    "void",
    "volatile",
}


def _type_tokens(type_text: str | None) -> tuple[str, ...]:
    if type_text is None:
        return ()
    return tuple(
        token
        for token in re.findall(r"\b[A-Za-z_]\w*\b", type_text)
        if token not in _TYPE_TOKEN_KEYWORDS
    )


def _type_uses_macro(type_text: str | None, macro_names: set[str]) -> bool:
    return any(token in macro_names for token in _type_tokens(type_text))


def _type_uses_target_shadow(source_text: str, span, type_text: str | None) -> bool:
    return any(
        _target_shadows_symbol(source_text, span, token)
        for token in _type_tokens(type_text)
    )


def _type_is_safe_in_target(
    source_text: str,
    span,
    type_text: str | None,
    macro_names: set[str],
) -> bool:
    if type_text is None:
        return False
    return not (
        _type_uses_macro(type_text, macro_names)
        or _type_uses_target_shadow(source_text, span, type_text)
    )


def _function_pointer_signature_uses_macro(
    signature: _FunctionPointerSignature | None,
    macro_names: set[str],
) -> bool:
    if signature is None:
        return False
    return _type_uses_macro(signature.return_type, macro_names) or any(
        _type_uses_macro(param_type, macro_names)
        for param_type in signature.param_types
    )


def _function_pointer_signature_uses_target_shadow(
    source_text: str,
    span,
    signature: _FunctionPointerSignature | None,
) -> bool:
    if signature is None:
        return False
    return _type_uses_target_shadow(
        source_text,
        span,
        signature.return_type,
    ) or any(
        _type_uses_target_shadow(source_text, span, param_type)
        for param_type in signature.param_types
    )


def _function_pointer_signature_is_safe_in_target(
    source_text: str,
    span,
    signature: _FunctionPointerSignature | None,
    macro_names: set[str],
) -> bool:
    if signature is None:
        return False
    return not (
        _function_pointer_signature_uses_macro(signature, macro_names)
        or _function_pointer_signature_uses_target_shadow(
            source_text,
            span,
            signature,
        )
    )


def _struct_layout_uses_macro(
    layout: tuple[tuple[str, str], ...],
    macro_names: set[str],
) -> bool:
    return any(_type_uses_macro(field_type, macro_names) for field_type, _name in layout)


def _parse_function_pointer_type(type_text: str) -> _FunctionPointerSignature | None:
    match = _FUNCTION_POINTER_TYPE_RE.match(type_text.strip())
    if match is None:
        return None
    return_type = _normalize_compat_type(match.group("ret"))
    if return_type is None:
        return None
    params_text = match.group("params").strip()
    if not params_text or params_text == "void":
        param_types: tuple[str, ...] = ()
    else:
        raw_params = _split_top_level_csv(params_text)
        if raw_params is None or any("..." in param for param in raw_params):
            return None
        parsed_params: list[str] = []
        for raw_param in raw_params:
            param_type = _normalize_param_type_text(raw_param)
            if param_type is None:
                return None
            parsed_params.append(param_type)
        param_types = tuple(parsed_params)
    return _FunctionPointerSignature(return_type=return_type, param_types=param_types)


def _source_local_function_pointer_typedefs(
    source_text: str,
) -> dict[str, _FunctionPointerSignature]:
    searchable = _blank_preprocessor_directives(
        _blank_disabled_preprocessor_regions(
            _blank_literals_and_comments(source_text)
        )
    )
    function_spans = tuple(find_function_definitions(source_text))

    def inside_function(offset: int) -> bool:
        return any(span.sig_start <= offset < span.full_end for span in function_spans)

    typedefs: dict[str, _FunctionPointerSignature] = {}
    for start, _end, line in _text_line_records(searchable):
        if inside_function(start) or "typedef" not in line or "(*" not in line:
            continue
        match = re.match(r"^[ \t]*typedef\s+(?P<type>.+)\s*;\s*$", line)
        if match is None:
            continue
        fp_match = _FUNCTION_POINTER_TYPE_RE.match(match.group("type").strip())
        if fp_match is None or fp_match.group("name") is None:
            continue
        signature = _parse_function_pointer_type(match.group("type"))
        if signature is not None:
            typedefs[fp_match.group("name")] = signature
    return typedefs


def _parse_source_param(
    param: str,
    fp_typedefs: Mapping[str, _FunctionPointerSignature],
) -> tuple[_SourceParam | None, bool]:
    param = param.strip()
    if not param or param == "void":
        return None, False
    if "..." in param:
        return None, True
    direct_fp = _parse_function_pointer_type(param)
    if direct_fp is not None:
        match = _FUNCTION_POINTER_TYPE_RE.match(param)
        name = match.group("name") if match is not None else None
        return _SourceParam(name=name, type_name=None, function_pointer=direct_fp), False
    type_name = _normalize_param_type_text(param)
    if type_name is None:
        return None, False
    name_match = re.search(r"\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*$", param)
    name = name_match.group(1) if name_match is not None else None
    return (
        _SourceParam(
            name=name,
            type_name=type_name,
            function_pointer=fp_typedefs.get(type_name),
        ),
        False,
    )


def _parse_function_signature_text(
    signature_text: str,
    fp_typedefs: Mapping[str, _FunctionPointerSignature],
) -> _SourceFunctionSignature | None:
    signature = re.sub(r"\s+", " ", signature_text.strip())
    match = re.match(
        r"^(?P<ret>[^(){};]+?)\s+(?P<name>[A-Za-z_]\w*)\s*"
        r"\((?P<params>.*)\)$",
        signature,
        re.DOTALL,
    )
    if match is None or "(" in match.group("ret"):
        return None
    return_type = _normalize_compat_type(match.group("ret"))
    if return_type is None:
        return None
    params_text = match.group("params").strip()
    if not params_text or params_text == "void":
        return _SourceFunctionSignature(
            name=match.group("name"),
            return_type=return_type,
            params=(),
            has_varargs=False,
        )
    raw_params = _split_top_level_csv(params_text)
    if raw_params is None:
        return None
    params: list[_SourceParam] = []
    has_varargs = False
    for raw_param in raw_params:
        param, is_varargs = _parse_source_param(raw_param, fp_typedefs)
        has_varargs = has_varargs or is_varargs
        if param is not None:
            params.append(param)
        elif not is_varargs:
            return None
    return _SourceFunctionSignature(
        name=match.group("name"),
        return_type=return_type,
        params=tuple(params),
        has_varargs=has_varargs,
    )


def _source_function_signatures(
    source_text: str,
) -> dict[str, _SourceFunctionSignature]:
    fp_typedefs = _source_local_function_pointer_typedefs(source_text)
    searchable = _blank_preprocessor_directives(
        _blank_disabled_preprocessor_regions(
            _blank_literals_and_comments(source_text)
        )
    )
    function_spans = tuple(find_function_definitions(source_text))
    signatures: dict[str, _SourceFunctionSignature] = {}
    for span in function_spans:
        if not searchable[span.sig_start:span.body_open].strip():
            continue
        signature = _parse_function_signature_text(
            source_text[span.sig_start:span.body_open],
            fp_typedefs,
        )
        if signature is not None:
            signatures[signature.name] = signature

    def inside_function(offset: int) -> bool:
        return any(span.sig_start <= offset < span.full_end for span in function_spans)

    for start, end, searchable_line in _text_line_records(searchable):
        if inside_function(start) or ";" not in searchable_line:
            continue
        line = source_text[start:end]
        if "typedef" in searchable_line or "(" not in searchable_line:
            continue
        candidate = line.strip()
        if not candidate.endswith(";"):
            continue
        signature = _parse_function_signature_text(candidate[:-1], fp_typedefs)
        if signature is not None:
            signatures[signature.name] = signature
    return signatures


def _scope_end_for_line(
    records: list[tuple[int, int, str]],
    depths: list[int],
    line_index: int,
    body_end: int,
) -> int:
    depth = depths[line_index] if line_index < len(depths) else 0
    if depth <= 0:
        return body_end
    for later_index in range(line_index + 1, len(records)):
        later_depth = depths[later_index] if later_index < len(depths) else 0
        if later_depth < depth:
            return records[later_index][0]
        current_depth = later_depth
        line_start, _line_end, line = records[later_index]
        for char_index, ch in enumerate(line):
            if ch == "}":
                current_depth -= 1
                if current_depth < depth:
                    return line_start + char_index
            elif ch == "{":
                current_depth += 1
    return body_end


def _local_declaration_shadow_names(line: str) -> tuple[str, ...]:
    match = _LOCAL_DECLARATION_RE.match(line)
    if match is None:
        return ()
    rest = match.group("rest").strip()
    if not rest or rest.startswith("="):
        return ()
    fp_match = re.match(r"^\(\s*\*\s*(?P<name>[A-Za-z_]\w*)\b", rest)
    if fp_match is not None:
        return (fp_match.group("name"),)
    if rest.startswith("("):
        return ()
    declarators = _split_top_level_csv(rest.rstrip(";"))
    if declarators is None:
        candidates = re.findall(r"(?:^|[,\s*])([A-Za-z_]\w*)\b", rest)
        return tuple(dict.fromkeys(candidates))
    names: list[str] = []
    for declarator in declarators:
        head = declarator.split("=", 1)[0].strip()
        if not head:
            continue
        if "(" in head or ")" in head:
            continue
        head = head.replace("*", " ")
        name_match = re.search(
            r"\b([A-Za-z_]\w*)\b(?:\s*\[[^\]]*\])?\s*$",
            head,
        )
        if name_match is not None:
            names.append(name_match.group(1))
    return tuple(dict.fromkeys(names))


def _target_pointer_type_proofs(
    source_text: str,
    span,
) -> tuple[_ScopedPointerType, ...]:
    macro_names = _source_function_like_macro_names(source_text)
    fp_typedefs = _source_local_function_pointer_typedefs(source_text)
    signature = _parse_function_signature_text(
        source_text[span.sig_start:span.body_open],
        fp_typedefs,
    )
    proofs: list[_ScopedPointerType] = []
    body_start = span.body_open + 1
    body_end = span.body_close
    if signature is not None:
        for param in signature.params:
            if param.name is None or param.type_name is None:
                continue
            pointer_type = _normalize_pointer_type(param.type_name)
            if pointer_type is not None:
                if not _type_is_safe_in_target(
                    source_text,
                    span,
                    pointer_type,
                    macro_names,
                ):
                    continue
                proofs.append(
                    _ScopedPointerType(
                        name=param.name,
                        type_name=pointer_type,
                        visible_start=body_start,
                        visible_end=body_end,
                        depth=-1,
                    )
                )

    body_inner = source_text[body_start:body_end]
    searchable_body = _blank_literals_and_comments(body_inner)
    records = _text_line_records(searchable_body)
    depths = _line_depths_from_blanked_text(searchable_body)
    for line_index, (start, end, line) in enumerate(records):
        match = _LOCAL_POINTER_DECL_RE.match(line)
        if match is not None:
            pointer_type = _normalize_pointer_type(match.group("type"))
            if pointer_type is None:
                continue
            if not _type_is_safe_in_target(
                source_text,
                span,
                pointer_type,
                macro_names,
            ):
                continue
            proofs.append(
                _ScopedPointerType(
                    name=match.group("name"),
                    type_name=pointer_type,
                    visible_start=body_start + end,
                    visible_end=body_start
                    + _scope_end_for_line(records, depths, line_index, len(body_inner)),
                    depth=depths[line_index] if line_index < len(depths) else 0,
                )
            )
            continue
        for shadow_name in _local_declaration_shadow_names(line):
            proofs.append(
                _ScopedPointerType(
                    name=shadow_name,
                    type_name=None,
                    visible_start=body_start + end,
                    visible_end=body_start
                    + _scope_end_for_line(records, depths, line_index, len(body_inner)),
                    depth=depths[line_index] if line_index < len(depths) else 0,
                )
            )
    return tuple(proofs)


def _target_takes_address_of_symbol(source_text: str, span, symbol: str) -> bool:
    body = _blank_literals_and_comments(source_text[span.body_open + 1:span.body_close])
    return re.search(r"&\s*(?:\(\s*)*" + re.escape(symbol) + r"\b", body) is not None


def _pointer_type_at(
    proofs: tuple[_ScopedPointerType, ...],
    name: str,
    offset: int,
) -> str | None:
    visible = [
        proof
        for proof in proofs
        if proof.name == name and proof.visible_start <= offset < proof.visible_end
    ]
    if not visible:
        return None
    visible.sort(key=lambda proof: (proof.depth, proof.visible_start), reverse=True)
    return visible[0].type_name


def _function_signature_as_pointer(
    signature: _SourceFunctionSignature | None,
) -> _FunctionPointerSignature | None:
    if signature is None or signature.has_varargs:
        return None
    param_types: list[str] = []
    for param in signature.params:
        if param.type_name is None or param.function_pointer is not None:
            return None
        normalized = _normalize_compat_type(param.type_name)
        if normalized is None:
            return None
        param_types.append(normalized)
    return _FunctionPointerSignature(
        return_type=signature.return_type,
        param_types=tuple(param_types),
    )


def _parse_pointer_cast_arg(arg_text: str) -> tuple[str, str] | None:
    match = _POINTER_CAST_ARG_RE.match(arg_text)
    if match is None:
        return None
    cast_type = _normalize_pointer_type(match.group("type"))
    if cast_type is None:
        return None
    return cast_type, match.group("expr")


def _parse_callback_cast_arg(
    arg_text: str,
    fp_typedefs: Mapping[str, _FunctionPointerSignature],
) -> tuple[_FunctionPointerSignature, str, str] | None:
    match = _FUNCTION_POINTER_CAST_ARG_RE.match(arg_text)
    if match is not None:
        cast_type = match.group("type")
        signature = _parse_function_pointer_type(cast_type)
        if signature is not None:
            return signature, match.group("expr"), cast_type
    typedef_match = _TYPEDEF_FUNCTION_POINTER_CAST_ARG_RE.match(arg_text)
    if typedef_match is None:
        return None
    signature = fp_typedefs.get(typedef_match.group("type"))
    if signature is None:
        return None
    return signature, typedef_match.group("expr"), typedef_match.group("type")


def _iter_pointer_assignment_cast_anchors(
    source_text: str,
    function: str,
    span,
    pointer_types: tuple[_ScopedPointerType, ...],
):
    body_start = span.body_open + 1
    body_inner = source_text[body_start:span.body_close]
    searchable_body = _blank_literals_and_comments(body_inner)
    macro_names = _source_function_like_macro_names(source_text)
    for (start, _end, line), (_s_start, _s_end, searchable_line) in zip(
        _text_line_records(body_inner),
        _text_line_records(searchable_body),
    ):
        match = _SIMPLE_ASSIGNMENT_RE.match(searchable_line)
        if match is None:
            continue
        lhs = match.group("lhs")
        if lhs in macro_names:
            continue
        destination_type = _pointer_type_at(
            pointer_types,
            lhs,
            body_start + start + match.start("lhs"),
        )
        if destination_type is None:
            continue
        rhs_start = match.start("rhs")
        rhs_end = match.end("rhs")
        while rhs_end > rhs_start and searchable_line[rhs_end - 1].isspace():
            rhs_end -= 1
        rhs = searchable_line[rhs_start:rhs_end]
        original_rhs = line[rhs_start:rhs_end]
        if rhs != original_rhs:
            continue
        parsed = _parse_pointer_cast_arg(rhs)
        if parsed is None:
            continue
        cast_type, expr = parsed
        if expr in macro_names:
            continue
        expression_type = _pointer_type_at(pointer_types, expr, body_start + start + rhs_start)
        if (
            not _type_is_safe_in_target(source_text, span, destination_type, macro_names)
            or not _type_is_safe_in_target(source_text, span, cast_type, macro_names)
            or not _type_is_safe_in_target(source_text, span, expression_type, macro_names)
        ):
            continue
        if not (destination_type == cast_type == expression_type):
            continue
        absolute_start = body_start + start + rhs_start
        absolute_end = body_start + start + rhs_end
        yield Anchor(
            mutator_key="elide_redundant_pointer_cast",
            span=(absolute_start, absolute_end),
            payload={
                "span_text": source_text[absolute_start:absolute_end],
                "replacement_text": expr,
                "cast_type": cast_type,
                "expression": expr,
                "expression_type": expression_type,
                "destination": lhs,
                "destination_type": destination_type,
                "proof_source": "source-local-pointer-compatibility",
                "target_function": function,
                "mode": "assignment",
            },
        )


def _iter_call_cast_anchors(
    source_text: str,
    function: str,
    span,
    signatures: Mapping[str, _SourceFunctionSignature],
    pointer_types: tuple[_ScopedPointerType, ...],
    fp_typedefs: Mapping[str, _FunctionPointerSignature],
):
    body_start = span.body_open + 1
    body_inner = source_text[body_start:span.body_close]
    searchable_body = _blank_literals_and_comments(body_inner)
    macro_names = _source_function_like_macro_names(source_text)
    for (start, _end, line), (_s_start, _s_end, searchable_line) in zip(
        _text_line_records(body_inner),
        _text_line_records(searchable_body),
    ):
        call = _SIMPLE_CALL_STATEMENT_RE.match(searchable_line)
        if call is None:
            continue
        callee = call.group("callee")
        if callee in macro_names or _target_shadows_symbol(source_text, span, callee):
            continue
        callee_signature = signatures.get(callee)
        if callee_signature is None or callee_signature.has_varargs:
            continue
        search_args = searchable_line[call.start("args"):call.end("args")]
        original_args = line[call.start("args"):call.end("args")]
        arg_spans = _split_top_level_csv_spans(search_args)
        if arg_spans is None:
            continue
        for arg_index, (arg_start, arg_end, arg_text) in enumerate(arg_spans):
            if arg_index >= len(callee_signature.params):
                continue
            original_arg = original_args[arg_start:arg_end]
            if original_arg != arg_text:
                continue
            absolute_start = body_start + start + call.start("args") + arg_start
            absolute_end = body_start + start + call.start("args") + arg_end
            formal = callee_signature.params[arg_index]

            callback_cast = _parse_callback_cast_arg(arg_text, fp_typedefs)
            if callback_cast is not None:
                cast_signature, expr, cast_type = callback_cast
                if (
                    expr in macro_names
                    or _target_shadows_symbol(source_text, span, expr)
                    or _target_takes_address_of_symbol(source_text, span, expr)
                    or not _type_is_safe_in_target(
                        source_text,
                        span,
                        cast_type,
                        macro_names,
                    )
                ):
                    continue
                formal_signature = formal.function_pointer
                expression_signature = _function_signature_as_pointer(
                    signatures.get(expr)
                )
                if (
                    not _function_pointer_signature_is_safe_in_target(
                        source_text,
                        span,
                        cast_signature,
                        macro_names,
                    )
                    or not _function_pointer_signature_is_safe_in_target(
                        source_text,
                        span,
                        formal_signature,
                        macro_names,
                    )
                    or not _function_pointer_signature_is_safe_in_target(
                        source_text,
                        span,
                        expression_signature,
                        macro_names,
                    )
                ):
                    continue
                if (
                    formal_signature is not None
                    and formal_signature == cast_signature == expression_signature
                ):
                    yield Anchor(
                        mutator_key="elide_callback_cast",
                        span=(absolute_start, absolute_end),
                        payload={
                            "span_text": source_text[absolute_start:absolute_end],
                            "replacement_text": expr,
                            "cast_type": cast_type,
                            "cast_signature": cast_signature,
                            "expression": expr,
                            "callee": callee,
                            "arg_index": arg_index,
                            "formal_signature": formal_signature,
                            "expression_signature": expression_signature,
                            "proof_source": "source-local-callback-signature",
                            "target_function": function,
                        },
                    )
                continue

            pointer_cast = _parse_pointer_cast_arg(arg_text)
            if pointer_cast is None:
                continue
            cast_type, expr = pointer_cast
            if expr in macro_names:
                continue
            formal_type = (
                _normalize_pointer_type(formal.type_name)
                if formal.type_name is not None
                else None
            )
            expression_type = _pointer_type_at(pointer_types, expr, absolute_start)
            if (
                not _type_is_safe_in_target(source_text, span, formal_type, macro_names)
                or not _type_is_safe_in_target(source_text, span, cast_type, macro_names)
                or not _type_is_safe_in_target(source_text, span, expression_type, macro_names)
            ):
                continue
            if not (formal_type == cast_type == expression_type):
                continue
            yield Anchor(
                mutator_key="elide_redundant_pointer_cast",
                span=(absolute_start, absolute_end),
                payload={
                    "span_text": source_text[absolute_start:absolute_end],
                    "replacement_text": expr,
                    "cast_type": cast_type,
                    "expression": expr,
                    "expression_type": expression_type,
                    "callee": callee,
                    "arg_index": arg_index,
                    "formal_type": formal_type,
                    "proof_source": "source-local-pointer-compatibility",
                    "target_function": function,
                    "mode": "call_argument",
                },
            )


def _simple_struct_alias_layouts(
    source_text: str,
) -> dict[str, tuple[tuple[str, str], ...]]:
    searchable = _blank_preprocessor_directives(
        _blank_disabled_preprocessor_regions(
            _blank_literals_and_comments(source_text)
        )
    )
    function_spans = tuple(find_function_definitions(source_text))

    def inside_function(offset: int) -> bool:
        return any(span.sig_start <= offset < span.full_end for span in function_spans)

    layouts: dict[str, tuple[tuple[str, str], ...]] = {}
    for match in _TYPEDEF_STRUCT_RE.finditer(searchable):
        if inside_function(match.start()):
            continue
        fields: list[tuple[str, str]] = []
        supported = True
        for raw_field in match.group("body").split(";"):
            field = raw_field.strip()
            if not field:
                continue
            field_match = re.match(
                r"^(?P<type>(?:struct\s+)?[A-Za-z_]\w*(?:\s*\*)?)\s+"
                r"(?P<name>[A-Za-z_]\w*)$",
                field,
            )
            if field_match is None:
                supported = False
                break
            field_type = _normalize_compat_type(field_match.group("type"))
            if field_type is None:
                supported = False
                break
            fields.append((field_type, field_match.group("name")))
        if supported and fields:
            layouts[match.group("name")] = tuple(fields)
    return layouts


def _body_typedef_aliases(searchable_body: str) -> set[str]:
    return {
        match.group("name")
        for match in _TYPEDEF_ALIAS_RE.finditer(searchable_body)
    }


def _iter_vector_alias_type_anchors(source_text: str, function: str, span):
    macro_names = _source_function_like_macro_names(source_text)
    layouts = _simple_struct_alias_layouts(source_text)
    layouts = {
        alias: layout
        for alias, layout in layouts.items()
        if alias not in macro_names and not _struct_layout_uses_macro(layout, macro_names)
    }
    if len(layouts) < 2:
        return
    aliases_by_layout: dict[tuple[tuple[str, str], ...], list[str]] = {}
    for alias, layout in layouts.items():
        aliases_by_layout.setdefault(layout, []).append(alias)
    equivalent_aliases = {
        alias: tuple(other for other in aliases if other != alias)
        for aliases in aliases_by_layout.values()
        if len(aliases) > 1
        for alias in aliases
    }
    if not equivalent_aliases:
        return

    body_start = span.body_open + 1
    body_inner = source_text[body_start:span.body_close]
    searchable_body = _blank_literals_and_comments(body_inner)
    if re.search(r"\btypedef\b", searchable_body) or re.search(
        r"\bstruct\b[^;{]*{",
        searchable_body,
    ):
        return
    shadowed_aliases = {
        alias
        for alias in equivalent_aliases
        if _target_shadows_symbol(source_text, span, alias)
    }
    shadowed_aliases.update(_body_typedef_aliases(searchable_body))
    for start, _end, searchable_line in _text_line_records(searchable_body):
        if "typedef" in searchable_line or "(" in searchable_line:
            continue
        match = _LOCAL_ALIAS_DECL_RE.match(searchable_line)
        if match is None:
            continue
        from_type = match.group("type")
        if from_type in shadowed_aliases or from_type in macro_names:
            continue
        replacements = equivalent_aliases.get(from_type)
        if not replacements:
            continue
        for to_type in replacements:
            if to_type in shadowed_aliases or to_type in macro_names:
                continue
            absolute_start = body_start + start + match.start("type")
            absolute_end = body_start + start + match.end("type")
            yield Anchor(
                mutator_key="rewrite_vector_alias_type",
                span=(absolute_start, absolute_end),
                payload={
                    "span_text": source_text[absolute_start:absolute_end],
                    "replacement_text": to_type,
                    "from_type": from_type,
                    "to_type": to_type,
                    "layout": layouts[from_type],
                    "proof_source": "source-local-identical-struct-alias",
                    "target_function": function,
                },
            )
            break


def _iter_type_cast_compatibility_anchors(source_text: str, function: str, span):
    body_inner = source_text[span.body_open + 1:span.body_close]
    if re.search(r"(?m)^[ \t]*#", body_inner):
        return
    searchable_body = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(body_inner)
    )
    if "#" in searchable_body:
        return
    fp_typedefs = _source_local_function_pointer_typedefs(source_text)
    signatures = _source_function_signatures(source_text)
    pointer_types = _target_pointer_type_proofs(source_text, span)
    yield from _iter_call_cast_anchors(
        source_text,
        function,
        span,
        signatures,
        pointer_types,
        fp_typedefs,
    )
    yield from _iter_pointer_assignment_cast_anchors(
        source_text,
        function,
        span,
        pointer_types,
    )
    yield from _iter_vector_alias_type_anchors(source_text, function, span)
