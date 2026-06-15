"""Source-transform family: fp_reassoc."""
from __future__ import annotations

import re
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _FLOAT_LITERAL_RE, _blank_disabled_preprocessor_regions, _blank_literals_and_comments, _float_bits, _normalize_type_name, _parse_signature_params, _source_local_return_type, _split_top_level_csv
from typing import Mapping


def _previous_nonspace(text: str, idx: int) -> int:
    pos = idx - 1
    while pos >= 0 and text[pos].isspace():
        pos -= 1
    return pos


_FP_REASSOCIATION_TYPE_NAMES = frozenset({"f32", "f64", "float", "double"})


_FP_REASSOCIATION_CALLEE_RE = re.compile(
    r"^(?:"
    r"sqrtf|sinf|cosf|tanf|atan2f|fabsf|"
    r"HSD_JObjGet(?:Translation|Rotation|Scale)[XYZ]"
    r")$"
)


def _is_exponent_sign(text: str, idx: int) -> bool:
    prev_idx = idx - 1
    next_idx = idx + 1
    if (
        prev_idx < 0
        or next_idx >= len(text)
        or text[prev_idx] not in {"e", "E"}
        or not text[next_idx].isdigit()
    ):
        return False
    return prev_idx > 0 and (text[prev_idx - 1].isdigit() or text[prev_idx - 1] == ".")


def _is_unary_minus(text: str, idx: int) -> bool:
    prev_idx = _previous_nonspace(text, idx)
    if prev_idx < 0:
        return True
    return text[prev_idx] in "([{=,:?+-*/%&|^!~<>"


def _is_reassociation_start_boundary(text: str, idx: int) -> bool:
    prev_idx = _previous_nonspace(text, idx)
    if prev_idx < 0:
        return True
    if text[prev_idx] in "([{=,":
        return True
    return re.search(r"\breturn\s*$", text[:idx]) is not None


def _find_top_level_binary_minus(text: str) -> int | None:
    depth = 0
    for idx, ch in enumerate(text):
        if ch in "([{":
            depth += 1
            continue
        if ch in ")]}":
            depth = max(0, depth - 1)
            continue
        if ch != "-" or depth != 0:
            continue
        if idx + 1 < len(text) and text[idx + 1] == ">":
            continue
        if _is_exponent_sign(text, idx) or _is_unary_minus(text, idx):
            continue
        return idx
    return None


def _has_top_level_reassociation_hazard(text: str) -> bool:
    depth = 0
    for idx, ch in enumerate(text):
        if ch in "([{":
            depth += 1
            continue
        if ch in ")]}":
            depth = max(0, depth - 1)
            continue
        if depth != 0:
            continue
        if ch in {",", "?", ":", ";", "{", "}"}:
            return True
        if ch == "=":
            return True
        if ch == "+":
            return True
        if ch == "-" and not _is_exponent_sign(text, idx):
            return True
        if ch in {"&", "|"} and idx + 1 < len(text) and text[idx + 1] == ch:
            return True
    return False


def _fp_subtraction_reassociation_replacement(rhs_text: str) -> str | None:
    if not rhs_text.startswith("-"):
        return None
    minus_idx = _find_top_level_binary_minus(rhs_text)
    if minus_idx is None:
        return None
    left_operand = rhs_text[1:minus_idx].strip()
    right_literal = rhs_text[minus_idx + 1:].strip()
    if not left_operand or not right_literal:
        return None
    if right_literal.startswith(("+", "-")):
        return None
    if re.fullmatch(_FLOAT_LITERAL_RE, right_literal) is None:
        return None
    if _has_top_level_reassociation_hazard(left_operand):
        return None
    width = "f32" if right_literal.lower().endswith("f") else "f64"
    value_bits = _float_bits(right_literal, width)
    if value_bits is not None and int(value_bits, 16) & 0x7FFFFFFFFFFFFFFF == 0:
        return None
    return f"-{right_literal} - {left_operand}"


def _strip_outer_parens(text: str) -> str:
    expr = text.strip()
    changed = True
    while changed and expr.startswith("(") and expr.endswith(")"):
        changed = False
        depth = 0
        for idx, ch in enumerate(expr):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and idx != len(expr) - 1:
                    break
        else:
            expr = expr[1:-1].strip()
            changed = True
    return expr


def _fp_reassociation_type_map(source_text: str, span) -> dict[str, str]:
    type_map: dict[str, str] = {}
    header = source_text[span.sig_start:span.body_open]
    for type_name, name in _parse_signature_params(header):
        if type_name in _FP_REASSOCIATION_TYPE_NAMES:
            type_map[name] = type_name

    body_text = source_text[span.body_open + 1:span.body_close]
    searchable_body = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(body_text)
    )
    decl_re = re.compile(
        r"(?m)^[ \t]*(?P<type>f32|f64|float|double)[ \t]+(?P<decls>[^;]+);"
    )
    for match in decl_re.finditer(searchable_body):
        declarators = _split_top_level_csv(match.group("decls"))
        if declarators is None:
            continue
        type_name = _normalize_type_name(match.group("type"))
        for declarator in declarators:
            head = declarator.split("=", 1)[0].strip()
            if "*" in head:
                continue
            name_match = re.match(
                r"^(?P<name>[A-Za-z_]\w*)(?:\s*\[[^\]]+\])?\s*$",
                head,
            )
            if name_match is not None:
                type_map[name_match.group("name")] = type_name
    return type_map


def _fp_reassociation_operand_has_float_evidence(
    operand: str,
    *,
    source_text: str,
    type_map: Mapping[str, str],
) -> bool:
    expr = _strip_outer_parens(operand)
    if not expr:
        return False
    if re.match(r"^\(\s*(?:f32|f64|float|double)\s*\)", expr):
        return True
    if re.search(r"(?:\.|->)(?:x|y|z)\b", expr):
        return True
    identifier = re.fullmatch(r"[A-Za-z_]\w*", expr)
    if identifier is not None:
        return type_map.get(identifier.group(0)) in _FP_REASSOCIATION_TYPE_NAMES
    array_ref = re.match(r"^(?P<name>[A-Za-z_]\w*)\s*\[", expr)
    if array_ref is not None:
        return type_map.get(array_ref.group("name")) in _FP_REASSOCIATION_TYPE_NAMES
    call = re.match(r"^(?P<callee>[A-Za-z_]\w*)\s*\(", expr)
    if call is not None:
        callee = call.group("callee")
        return_type = _source_local_return_type(source_text, callee)
        if return_type in _FP_REASSOCIATION_TYPE_NAMES:
            return True
        return _FP_REASSOCIATION_CALLEE_RE.match(callee) is not None
    return False


def _find_unary_subtraction_expression_end(text: str, start: int) -> int | None:
    depth = 0
    idx = start + 1
    while idx < len(text):
        ch = text[idx]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth = max(0, depth - 1)
        elif depth == 0 and ch in ",;":
            break
        idx += 1
    end = idx
    while end > start and text[end - 1].isspace():
        end -= 1
    return end if end > start else None


def _iter_statement_spans_in_body(body_text: str, *, body_start: int):
    start = 0
    paren_depth = 0
    bracket_depth = 0
    for idx, ch in enumerate(body_text):
        if ch == "(":
            paren_depth += 1
            continue
        if ch == ")":
            paren_depth = max(0, paren_depth - 1)
            continue
        if ch == "[":
            bracket_depth += 1
            continue
        if ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
            continue
        if paren_depth == 0 and bracket_depth == 0 and ch in "{}":
            start = idx + 1
            continue
        if paren_depth == 0 and bracket_depth == 0 and ch == ";":
            if start < idx:
                yield body_start + start, body_start + idx
            start = idx + 1


def _iter_fp_subtraction_reassociation_anchors(source_text: str, function: str, span):
    body_start = span.body_open + 1
    body_text = source_text[body_start:span.body_close]
    searchable_body = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(body_text)
    )
    type_map = _fp_reassociation_type_map(source_text, span)
    for statement_start, statement_end in _iter_statement_spans_in_body(
        searchable_body,
        body_start=body_start,
    ):
        statement_text = source_text[statement_start:statement_end]
        searchable_statement = searchable_body[
            statement_start - body_start:statement_end - body_start
        ]
        for match in re.finditer("-", searchable_statement):
            expr_start = match.start()
            if _is_exponent_sign(searchable_statement, expr_start):
                continue
            if not _is_reassociation_start_boundary(searchable_statement, expr_start):
                continue
            expr_end = _find_unary_subtraction_expression_end(
                searchable_statement,
                expr_start,
            )
            if expr_end is None:
                continue
            expr_text = statement_text[expr_start:expr_end]
            if not expr_text or expr_text != searchable_statement[expr_start:expr_end]:
                continue
            replacement = _fp_subtraction_reassociation_replacement(expr_text)
            if replacement is None or replacement == expr_text:
                continue
            minus_idx = _find_top_level_binary_minus(expr_text)
            if minus_idx is None:
                continue
            left_operand = expr_text[1:minus_idx].strip()
            if not _fp_reassociation_operand_has_float_evidence(
                left_operand,
                source_text=source_text,
                type_map=type_map,
            ):
                continue
            yield Anchor(
                mutator_key="reassociate_fp_subtraction_operands",
                span=(statement_start + expr_start, statement_start + expr_end),
                payload={
                    "span_text": expr_text,
                    "replacement_text": replacement,
                    "left_operand": left_operand,
                    "right_literal": expr_text[minus_idx + 1:].strip(),
                    "proof_source": "unary-minus-fp-subtraction-literal",
                    "target_function": function,
                },
            )
            continue
