"""Source-transform family: float_literal."""
from __future__ import annotations

import re
from dataclasses import dataclass
from src.mwcc_debug.source_patch import find_function_definitions
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _FLOAT_LITERAL_RE, _blank_disabled_preprocessor_regions, _blank_literals_and_comments, _float_bits, _target_shadows_symbol


@dataclass(frozen=True)
class _FloatConstant:
    symbol: str
    literal: str
    width: str
    bits: str
    declaration_span: tuple[int, int]


_FLOAT_DECL_RE = re.compile(
    r"(?m)^[ \t]*(?:static[ \t]+)?const[ \t]+"
    r"(?P<type>f32|float|f64|double)[ \t]+"
    r"(?P<symbol>[A-Za-z_]\w*)[ \t]*=[ \t]*"
    r"(?P<literal>" + _FLOAT_LITERAL_RE + r")[ \t]*;[ \t]*$"
)


_FLOAT_TOKEN_RE = re.compile(r"(?<![\w.])" + _FLOAT_LITERAL_RE + r"(?![\w.])")


def _float_width(type_name: str, literal: str) -> str | None:
    has_suffix = literal.lower().endswith("f")
    if type_name in {"f32", "float"}:
        return "f32" if has_suffix else None
    if type_name in {"f64", "double"}:
        return None if has_suffix else "f64"
    return None


def _source_local_float_constants(
    source_text: str,
    *,
    before_offset: int,
) -> dict[tuple[str, str], _FloatConstant]:
    prefix = source_text[:before_offset]
    searchable = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(prefix)
    )
    function_spans = tuple(find_function_definitions(prefix))

    def inside_function(offset: int) -> bool:
        return any(span.sig_start <= offset < span.full_end for span in function_spans)

    by_key: dict[tuple[str, str], list[_FloatConstant]] = {}
    for match in _FLOAT_DECL_RE.finditer(searchable):
        if inside_function(match.start()):
            continue
        literal = source_text[match.start("literal"):match.end("literal")]
        type_name = source_text[match.start("type"):match.end("type")]
        width = _float_width(type_name, literal)
        if width is None:
            continue
        bits = _float_bits(literal, width)
        if bits is None:
            continue
        symbol = source_text[match.start("symbol"):match.end("symbol")]
        by_key.setdefault((width, bits), []).append(
            _FloatConstant(
                symbol=symbol,
                literal=literal,
                width=width,
                bits=bits,
                declaration_span=(match.start(), match.end()),
            )
        )
    return {
        key: constants[0]
        for key, constants in by_key.items()
        if len(constants) == 1
    }


def _line_has_static_initializer_for_span(source_text: str, start: int, end: int) -> bool:
    statement_start = max(
        source_text.rfind(";", 0, start),
        source_text.rfind("{", 0, start),
        source_text.rfind("}", 0, start),
    ) + 1
    prefix = source_text[statement_start:start]
    if re.search(r"(?m)^[ \t]*static\b", prefix) is None:
        return False
    if "=" not in prefix:
        return False
    return source_text.find(";", start) != -1


def _is_address_taken_at(text: str, offset: int) -> bool:
    idx = offset - 1
    while idx >= 0 and text[idx].isspace():
        idx -= 1
    while idx >= 0 and text[idx] == "(":
        idx -= 1
        while idx >= 0 and text[idx].isspace():
            idx -= 1
    return idx >= 0 and text[idx] == "&"


def _iter_global_float_literal_anchors(source_text: str, function: str, span):
    constants_by_key = _source_local_float_constants(
        source_text,
        before_offset=span.sig_start,
    )
    if not constants_by_key:
        return
    constants_by_symbol = {constant.symbol: constant for constant in constants_by_key.values()}
    body_start = span.body_open
    body_text = source_text[body_start:span.full_end]
    searchable_body = _blank_disabled_preprocessor_regions(
        _blank_literals_and_comments(body_text)
    )
    shadowed_symbols = {
        symbol
        for symbol in constants_by_symbol
        if _target_shadows_symbol(source_text, span, symbol)
    }

    for match in _FLOAT_TOKEN_RE.finditer(searchable_body):
        literal = source_text[body_start + match.start():body_start + match.end()]
        width = "f32" if literal.lower().endswith("f") else "f64"
        bits = _float_bits(literal, width)
        if bits is None:
            continue
        constant = constants_by_key.get((width, bits))
        if constant is None or constant.symbol in shadowed_symbols:
            continue
        start = body_start + match.start()
        end = body_start + match.end()
        if _line_has_static_initializer_for_span(source_text, start, end):
            continue
        yield Anchor(
            mutator_key="replace_float_literal_with_global_constant",
            span=(start, end),
            payload={
                "span_text": literal,
                "replacement_text": constant.symbol,
                "symbol": constant.symbol,
                "literal": literal,
                "constant_literal": constant.literal,
                "width": width,
                "value_bits": bits,
                "proof_source": "source-local-global-constant",
                "mode": "literal_to_symbol",
                "target_function": function,
                "declaration_span": constant.declaration_span,
            },
        )

    for symbol, constant in constants_by_symbol.items():
        if symbol in shadowed_symbols:
            continue
        for match in re.finditer(r"\b" + re.escape(symbol) + r"\b", searchable_body):
            start = body_start + match.start()
            end = body_start + match.end()
            if _is_address_taken_at(searchable_body, match.start()):
                continue
            if _line_has_static_initializer_for_span(source_text, start, end):
                continue
            yield Anchor(
                mutator_key="replace_global_float_constant_with_literal",
                span=(start, end),
                payload={
                    "span_text": symbol,
                    "replacement_text": constant.literal,
                    "symbol": symbol,
                    "literal": constant.literal,
                    "width": constant.width,
                    "value_bits": constant.bits,
                    "proof_source": "source-local-global-constant",
                    "mode": "symbol_to_literal",
                    "target_function": function,
                    "declaration_span": constant.declaration_span,
                },
            )
