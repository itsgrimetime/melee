"""Source-transform family: contract_signature."""
from __future__ import annotations

import re
from dataclasses import dataclass
from src.mwcc_debug.source_patch import find_function_definitions
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _blank_disabled_preprocessor_regions, _blank_literals_and_comments, _blank_preprocessor_directives, _contract_make_edit, _function_name_for_span, _normalize_param_type_text, _source_function_like_macro_names, _split_top_level_csv_spans, _target_shadows_symbol, _text_line_records
from typing import Mapping


@dataclass(frozen=True)
class _ContractParam:
    text: str
    start: int
    end: int
    type_name: str
    name: str | None


@dataclass(frozen=True)
class _ContractSignature:
    kind: str
    span: tuple[int, int]
    name_span: tuple[int, int]
    open_paren: int
    close_paren: int
    params: tuple[_ContractParam, ...]
    zero_param_style: str | None
    is_static: bool
    has_extern: bool
    has_varargs: bool


@dataclass(frozen=True)
class _ContractArg:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _ContractCall:
    caller: str
    span: tuple[int, int]
    name_span: tuple[int, int]
    open_paren: int
    close_paren: int
    args: tuple[_ContractArg, ...]


def _matching_paren_index(text: str, open_index: int) -> int | None:
    if open_index < 0 or open_index >= len(text) or text[open_index] != "(":
        return None
    depth = 0
    for index in range(open_index, len(text)):
        ch = text[index]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return index
            if depth < 0:
                return None
    return None


def _contract_region_has_comments_or_directives(text: str) -> bool:
    return "#" in text or "//" in text or "/*" in text or "*/" in text


def _contract_param_from_span(
    source_text: str,
    *,
    start: int,
    end: int,
) -> _ContractParam | None:
    text = source_text[start:end]
    stripped = text.strip()
    type_name = _normalize_param_type_text(stripped)
    if type_name is None:
        return None

    name: str | None = None
    match = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)?$", stripped)
    if match is not None:
        candidate = match.group(1)
        prefix = stripped[:match.start(1)].rstrip()
        if prefix:
            name = candidate
    return _ContractParam(
        text=stripped,
        start=start,
        end=end,
        type_name=type_name,
        name=name,
    )


def _contract_params_between_parens(
    source_text: str,
    *,
    open_paren: int,
    close_paren: int,
) -> tuple[tuple[_ContractParam, ...], str | None, bool] | None:
    if close_paren <= open_paren:
        return None
    inner_start = open_paren + 1
    inner_end = close_paren
    inner_text = source_text[inner_start:inner_end]
    if _contract_region_has_comments_or_directives(inner_text):
        return None
    stripped = inner_text.strip()
    if not stripped:
        return (), "empty", False
    if stripped == "void":
        return (), "void", False
    raw_spans = _split_top_level_csv_spans(inner_text)
    if raw_spans is None:
        return None
    params: list[_ContractParam] = []
    has_varargs = False
    for rel_start, rel_end, raw_param in raw_spans:
        if raw_param == "...":
            has_varargs = True
            continue
        if "..." in raw_param:
            return None
        param = _contract_param_from_span(
            source_text,
            start=inner_start + rel_start,
            end=inner_start + rel_end,
        )
        if param is None:
            return None
        params.append(param)
    return tuple(params), None, has_varargs


def _parse_contract_signature(
    source_text: str,
    searchable: str,
    *,
    sig_start: int,
    sig_end: int,
    function: str,
    kind: str,
) -> _ContractSignature | None:
    signature_text = searchable[sig_start:sig_end]
    match = re.search(r"\b" + re.escape(function) + r"\s*\(", signature_text)
    if match is None:
        return None
    name_start = sig_start + match.start()
    name_end = name_start + len(function)
    open_paren = sig_start + match.end() - 1
    close_paren = _matching_paren_index(searchable, open_paren)
    if close_paren is None or close_paren >= sig_end:
        return None
    prefix = source_text[sig_start:name_start]
    if re.search(r"\btypedef\b", prefix):
        return None
    parsed_params = _contract_params_between_parens(
        source_text,
        open_paren=open_paren,
        close_paren=close_paren,
    )
    if parsed_params is None:
        return None
    params, zero_param_style, has_varargs = parsed_params
    return _ContractSignature(
        kind=kind,
        span=(sig_start, sig_end),
        name_span=(name_start, name_end),
        open_paren=open_paren,
        close_paren=close_paren,
        params=params,
        zero_param_style=zero_param_style,
        is_static=re.search(r"\bstatic\b", prefix) is not None,
        has_extern=re.search(r"\bextern\b", prefix) is not None,
        has_varargs=has_varargs,
    )


def _contract_prototype_signatures(
    source_text: str,
    searchable: str,
    *,
    function: str,
    function_spans: tuple,
) -> tuple[_ContractSignature, ...] | None:
    def inside_function(offset: int) -> bool:
        return any(span.sig_start <= offset < span.full_end for span in function_spans)

    prototypes: list[_ContractSignature] = []
    for start, end, searchable_line in _text_line_records(searchable):
        if inside_function(start) or ";" not in searchable_line:
            continue
        if not re.search(r"\b" + re.escape(function) + r"\s*\(", searchable_line):
            continue
        line = source_text[start:end]
        if "typedef" in searchable_line:
            return None
        line_no_newline = line.rstrip("\r\n")
        semicolon_rel = line_no_newline.rfind(";")
        if semicolon_rel < 0:
            continue
        trailing = line_no_newline[semicolon_rel + 1:].strip()
        if trailing:
            return None
        leading = len(line_no_newline) - len(line_no_newline.lstrip())
        signature = _parse_contract_signature(
            source_text,
            searchable,
            sig_start=start + leading,
            sig_end=start + semicolon_rel,
            function=function,
            kind="prototype",
        )
        if signature is None:
            return None
        prototypes.append(signature)
    return tuple(prototypes)


def _contract_args_between_parens(
    source_text: str,
    *,
    open_paren: int,
    close_paren: int,
) -> tuple[_ContractArg, ...] | None:
    inner_start = open_paren + 1
    inner_text = source_text[inner_start:close_paren]
    if _contract_region_has_comments_or_directives(inner_text):
        return None
    if not inner_text.strip():
        return ()
    raw_spans = _split_top_level_csv_spans(inner_text)
    if raw_spans is None:
        return None
    return tuple(
        _ContractArg(
            text=raw_arg,
            start=inner_start + rel_start,
            end=inner_start + rel_end,
        )
        for rel_start, rel_end, raw_arg in raw_spans
    )


def _contract_calls(
    source_text: str,
    searchable: str,
    *,
    function: str,
    function_spans: tuple,
) -> tuple[_ContractCall, ...] | None:
    calls: list[_ContractCall] = []
    pattern = re.compile(r"\b" + re.escape(function) + r"\s*\(")
    for span in function_spans:
        caller = _function_name_for_span(source_text, searchable, span)
        if caller is None:
            return None
        body_start = span.body_open + 1
        body_end = span.body_close
        body_text = searchable[body_start:body_end]
        for match in pattern.finditer(body_text):
            name_start = body_start + match.start()
            name_end = name_start + len(function)
            open_paren = body_start + match.end() - 1
            close_paren = _matching_paren_index(searchable, open_paren)
            if close_paren is None or close_paren > body_end:
                return None
            args = _contract_args_between_parens(
                source_text,
                open_paren=open_paren,
                close_paren=close_paren,
            )
            if args is None:
                return None
            calls.append(
                _ContractCall(
                    caller=caller,
                    span=(name_start, close_paren + 1),
                    name_span=(name_start, name_end),
                    open_paren=open_paren,
                    close_paren=close_paren,
                    args=args,
                )
            )
    return tuple(calls)


def _contract_preprocessor_mentions_target(source_text: str, function: str) -> bool:
    return _contract_preprocessor_mentions_symbol(source_text, function)


def _contract_preprocessor_mentions_symbol(source_text: str, symbol: str) -> bool:
    pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
    in_continuation = False
    for _start, _end, line in _text_line_records(source_text):
        stripped = line.lstrip()
        is_directive = in_continuation or stripped.startswith("#")
        if is_directive and pattern.search(_blank_literals_and_comments(line)):
            return True
        content = line.rstrip("\r\n")
        in_continuation = is_directive and content.endswith("\\")
    return False


def _contract_has_preprocessor_hidden_reference(
    source_text: str,
    searchable: str,
    *,
    function: str,
) -> bool:
    pattern = re.compile(r"\b" + re.escape(function) + r"\b")
    raw_visible = _blank_literals_and_comments(source_text)
    return len(tuple(pattern.finditer(raw_visible))) != len(
        tuple(pattern.finditer(searchable))
    )


def _contract_references_are_direct(
    searchable: str,
    *,
    function: str,
    signatures: tuple[_ContractSignature, ...],
    calls: tuple[_ContractCall, ...],
) -> bool:
    allowed = [signature.name_span for signature in signatures]
    allowed.extend(call.name_span for call in calls)

    def in_allowed(offset: int) -> bool:
        return any(start <= offset < end for start, end in allowed)

    for match in re.finditer(r"\b" + re.escape(function) + r"\b", searchable):
        if not in_allowed(match.start()):
            return False
    return True


def _contract_signatures_have_matching_params(
    signatures: tuple[_ContractSignature, ...],
    param_types: tuple[str, ...],
) -> bool:
    for signature in signatures:
        if signature.has_extern or signature.has_varargs:
            return False
        if signature.kind == "definition" and not signature.is_static:
            return False
        if signature.kind == "prototype" and not signature.is_static:
            return False
        if tuple(param.type_name for param in signature.params) != param_types:
            return False
    return True


def _remove_trailing_param_signature_edit(
    source_text: str,
    signature: _ContractSignature,
) -> dict[str, object]:
    if len(signature.params) == 1:
        return _contract_make_edit(
            source_text,
            start=signature.open_paren + 1,
            end=signature.close_paren,
            replacement_text="void",
            kind=f"{signature.kind}-params",
        )
    previous = signature.params[-2]
    trailing = signature.params[-1]
    return _contract_make_edit(
        source_text,
        start=previous.end,
        end=trailing.end,
        replacement_text="",
        kind=f"{signature.kind}-trailing-param",
    )


def _add_trailing_param_signature_edit(
    source_text: str,
    signature: _ContractSignature,
) -> dict[str, object]:
    if not signature.params:
        return _contract_make_edit(
            source_text,
            start=signature.open_paren + 1,
            end=signature.close_paren,
            replacement_text="int unused",
            kind=f"{signature.kind}-params",
        )
    return _contract_make_edit(
        source_text,
        start=signature.close_paren,
        end=signature.close_paren,
        replacement_text=", int unused",
        kind=f"{signature.kind}-trailing-param",
    )


def _remove_trailing_arg_edit(
    source_text: str,
    call: _ContractCall,
) -> dict[str, object]:
    if len(call.args) == 1:
        return _contract_make_edit(
            source_text,
            start=call.open_paren + 1,
            end=call.close_paren,
            replacement_text="",
            kind="call-args",
        )
    previous = call.args[-2]
    trailing = call.args[-1]
    return _contract_make_edit(
        source_text,
        start=previous.end,
        end=trailing.end,
        replacement_text="",
        kind="call-trailing-arg",
    )


def _add_trailing_arg_edit(
    source_text: str,
    call: _ContractCall,
) -> dict[str, object]:
    replacement = "0" if not call.args else ", 0"
    return _contract_make_edit(
        source_text,
        start=call.close_paren,
        end=call.close_paren,
        replacement_text=replacement,
        kind="call-trailing-arg",
    )


def _updated_signature_payload(
    signature: _ContractSignature,
    *,
    old_param_count: int,
    new_param_count: int,
) -> dict[str, object]:
    return {
        "kind": signature.kind,
        "span": list(signature.span),
        "old_param_count": old_param_count,
        "new_param_count": new_param_count,
    }


def _updated_call_site_payload(
    call: _ContractCall,
    edit: Mapping[str, object],
    *,
    old_arg_count: int,
    new_arg_count: int,
) -> dict[str, object]:
    return {
        "caller": call.caller,
        "span": list(call.span),
        "old_arg_count": old_arg_count,
        "new_arg_count": new_arg_count,
        "replacement_text": edit["replacement_text"],
    }


def _iter_unused_trailing_parameter_anchors(source_text: str, function: str, span):
    searchable = _blank_preprocessor_directives(
        _blank_disabled_preprocessor_regions(
            _blank_literals_and_comments(source_text)
        )
    )
    if _contract_has_preprocessor_hidden_reference(
        source_text,
        searchable,
        function=function,
    ):
        return
    if function in _source_function_like_macro_names(source_text):
        return
    if _contract_preprocessor_mentions_target(source_text, function):
        return
    if _target_shadows_symbol(source_text, span, function):
        return

    function_spans = tuple(find_function_definitions(source_text))
    target_defs = [
        candidate_span
        for candidate_span in function_spans
        if _function_name_for_span(source_text, searchable, candidate_span) == function
    ]
    if len(target_defs) != 1:
        return

    definition = _parse_contract_signature(
        source_text,
        searchable,
        sig_start=span.sig_start,
        sig_end=span.body_open,
        function=function,
        kind="definition",
    )
    if definition is None or not definition.is_static or definition.has_extern:
        return
    prototypes = _contract_prototype_signatures(
        source_text,
        searchable,
        function=function,
        function_spans=function_spans,
    )
    if prototypes is None:
        return
    signatures = (definition, *prototypes)
    param_types = tuple(param.type_name for param in definition.params)
    if not _contract_signatures_have_matching_params(signatures, param_types):
        return

    calls = _contract_calls(
        source_text,
        searchable,
        function=function,
        function_spans=function_spans,
    )
    if calls is None:
        return
    if not _contract_references_are_direct(
        searchable,
        function=function,
        signatures=signatures,
        calls=calls,
    ):
        return

    param_count = len(definition.params)
    if not all(len(call.args) == param_count for call in calls):
        return

    if param_count:
        trailing = definition.params[-1]
        if trailing.name is not None:
            if _contract_preprocessor_mentions_symbol(source_text, trailing.name):
                trailing = None
            body = searchable[span.body_open + 1:span.body_close]
            if trailing is not None and re.search(
                r"\b" + re.escape(trailing.name) + r"\b",
                body,
            ):
                trailing = None
        else:
            trailing = None
        if trailing is not None:
            signature_edits = [
                _remove_trailing_param_signature_edit(source_text, signature)
                for signature in signatures
            ]
            call_edits = [
                _remove_trailing_arg_edit(source_text, call)
                for call in calls
            ]
            edits = signature_edits + call_edits
            payload = {
                "mode": "remove",
                "proof_source": "self-contained-static-contract",
                "requires_full_unit_source": True,
                "parameter_name": trailing.name,
                "parameter_type": trailing.type_name,
                "parameter_index": param_count - 1,
                "target_function": function,
                "updated_signatures": [
                    _updated_signature_payload(
                        signature,
                        old_param_count=param_count,
                        new_param_count=param_count - 1,
                    )
                    for signature in signatures
                ],
                "updated_call_sites": [
                    _updated_call_site_payload(
                        call,
                        edit,
                        old_arg_count=param_count,
                        new_arg_count=param_count - 1,
                    )
                    for call, edit in zip(calls, call_edits)
                ],
                "edits": edits,
            }
            yield Anchor(
                mutator_key="remove_unused_trailing_parameter",
                span=(
                    min(int(edit["start"]) for edit in edits),
                    max(int(edit["end"]) for edit in edits),
                ),
                payload=payload,
            )

    if any(param.name == "unused" for param in definition.params):
        return
    if _contract_preprocessor_mentions_symbol(source_text, "unused"):
        return
    body = searchable[span.body_open + 1:span.body_close]
    if re.search(r"\bunused\b", body):
        return
    signature_edits = [
        _add_trailing_param_signature_edit(source_text, signature)
        for signature in signatures
    ]
    call_edits = [_add_trailing_arg_edit(source_text, call) for call in calls]
    edits = signature_edits + call_edits
    payload = {
        "mode": "add",
        "proof_source": "self-contained-static-contract",
        "requires_full_unit_source": True,
        "parameter_name": "unused",
        "parameter_type": "int",
        "parameter_index": param_count,
        "target_function": function,
        "updated_signatures": [
            _updated_signature_payload(
                signature,
                old_param_count=param_count,
                new_param_count=param_count + 1,
            )
            for signature in signatures
        ],
        "updated_call_sites": [
            _updated_call_site_payload(
                call,
                edit,
                old_arg_count=param_count,
                new_arg_count=param_count + 1,
            )
            for call, edit in zip(calls, call_edits)
        ],
        "edits": edits,
    }
    yield Anchor(
        mutator_key="add_unused_trailing_parameter",
        span=(
            min(int(edit["start"]) for edit in edits),
            max(int(edit["end"]) for edit in edits),
        ),
        payload=payload,
    )
