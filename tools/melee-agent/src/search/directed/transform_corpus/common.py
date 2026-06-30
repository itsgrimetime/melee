"""Shared text/type/signature helpers used by multiple transform families."""
from __future__ import annotations

import math
import re
import struct
from decimal import Decimal, InvalidOperation, localcontext
from src.mwcc_debug.source_patch import find_function, find_function_definitions
from typing import Iterable


def _source_file_for_unit(unit: str) -> str:
    if unit.startswith("src/"):
        return unit.replace("src/main/", "src/", 1)
    normalized = unit.removeprefix("main/")
    return f"src/{normalized}.c"


def _target_function_body(source_text: str, function: str):
    span = find_function(source_text, function)
    if span is None:
        return None
    return span, source_text[span.body_open:span.full_end]


def _macro_like_statement(line: str) -> bool:
    stripped = line.strip()
    return re.match(r"[A-Z][A-Z0-9_]*\s*\(", stripped) is not None


def _line_has_label(line: str) -> bool:
    return re.match(r"\s*[A-Za-z_]\w*\s*:", line) is not None


def _split_top_level_csv(text: str) -> list[str] | None:
    result: list[str] = []
    depth = 0
    start = 0
    in_string: str | None = None
    escape = False
    for idx, ch in enumerate(text):
        if in_string is not None:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in {'"', "'"}:
            in_string = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return None
        elif ch == "," and depth == 0:
            result.append(text[start:idx].strip())
            start = idx + 1
    if depth != 0 or in_string is not None:
        return None
    result.append(text[start:].strip())
    return result


def _normalize_type_name(type_name: str) -> str:
    return re.sub(r"\s+", " ", type_name.replace("const ", "").strip())


def _line_containing(text: str, offset: int) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end == -1:
        end = len(text)
    return text[start:end]


def _source_local_return_type(source_text: str, function_name: str) -> str | None:
    pattern = re.compile(
        r"(?m)^[ \t]*(?:static\s+)?(?P<type>bool|BOOL|s8|s16|s32|s64|u8|u16|u32|u64|int|short|long|f32|f64|float|double)\s+"
        + re.escape(function_name)
        + r"\s*\([^;{}]*\)\s*(?:;|{)"
    )
    match = pattern.search(source_text)
    if match is None:
        return None
    return _normalize_type_name(match.group("type"))


_FLOAT_LITERAL_RE = (
    r"[-+]?(?:(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?|"
    r"\d+[eE][-+]?\d+)[fF]?"
)


def _blank_disabled_preprocessor_regions(text: str) -> str:
    pieces: list[str] = []
    conditional_depth = 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        starts_conditional = re.match(r"#\s*if(?:def|ndef)?\b", stripped) is not None
        starts_branch = re.match(r"#\s*(?:else|elif)\b", stripped) is not None
        ends_conditional = re.match(r"#\s*endif\b", stripped) is not None
        if starts_conditional:
            conditional_depth += 1
            pieces.append("".join("\n" if ch == "\n" else " " for ch in line))
            continue
        if conditional_depth:
            pieces.append("".join("\n" if ch == "\n" else " " for ch in line))
            if starts_conditional:
                conditional_depth += 1
            elif ends_conditional:
                conditional_depth = max(0, conditional_depth - 1)
            elif starts_branch:
                conditional_depth = max(1, conditional_depth)
            continue
        pieces.append(line)
    return "".join(pieces)


def _blank_preprocessor_directives(text: str) -> str:
    pieces: list[str] = []
    in_continuation = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        is_directive = in_continuation or stripped.startswith("#")
        if is_directive:
            pieces.append("".join("\n" if ch == "\n" else " " for ch in line))
        else:
            pieces.append(line)
        content = line.rstrip("\r\n")
        in_continuation = is_directive and content.endswith("\\")
    return "".join(pieces)


def _float_bits(literal: str, width: str) -> str | None:
    if "x" in literal.lower():
        return None
    value_text = literal[:-1] if literal.lower().endswith("f") else literal
    if width == "f32":
        return _float32_bits_from_decimal(value_text)
    try:
        value = float(value_text)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    try:
        if width == "f32":
            return struct.pack(">f", value).hex()
        if width == "f64":
            return struct.pack(">d", value).hex()
    except OverflowError:
        return None
    return None


def _bits_to_ordered_float32(bits: int) -> int:
    return (~bits & 0xFFFFFFFF) if (bits & 0x80000000) else (bits ^ 0x80000000)


def _ordered_to_float32_bits(ordered: int) -> int:
    if ordered & 0x80000000:
        return ordered ^ 0x80000000
    return ~ordered & 0xFFFFFFFF


def _decimal_from_float32_bits(bits: int) -> Decimal | None:
    exponent = (bits >> 23) & 0xFF
    fraction = bits & 0x7FFFFF
    if exponent == 0xFF:
        return None
    sign = -1 if (bits & 0x80000000) else 1
    with localcontext() as ctx:
        ctx.prec = 120
        if exponent == 0:
            mantissa = fraction
            power = -149
        else:
            mantissa = (1 << 23) | fraction
            power = exponent - 150
        value = Decimal(mantissa) * (Decimal(2) ** power)
        return -value if sign < 0 else value


def _float32_bits_from_decimal(value_text: str) -> str | None:
    try:
        with localcontext() as ctx:
            ctx.prec = 120
            target = Decimal(value_text)
    except InvalidOperation:
        return None
    if not target.is_finite():
        return None
    if target.is_zero():
        return "80000000" if target.is_signed() else "00000000"
    try:
        approx = float(value_text)
        packed = struct.pack(">f", approx)
    except (OverflowError, ValueError):
        return None
    center = struct.unpack(">I", packed)[0]
    center_order = _bits_to_ordered_float32(center)
    best: tuple[Decimal, int, int] | None = None
    with localcontext() as ctx:
        ctx.prec = 160
        for ordered in range(
            max(0, center_order - 16),
            min(0xFFFFFFFF, center_order + 16) + 1,
        ):
            bits = _ordered_to_float32_bits(ordered)
            candidate = _decimal_from_float32_bits(bits)
            if candidate is None:
                continue
            distance = abs(candidate - target)
            key = (distance, bits & 1, bits)
            if best is None or key < best:
                best = key
    if best is None:
        return None
    return f"{best[2]:08x}"


def _function_parameter_names(source_text: str, span) -> set[str]:
    header = source_text[span.sig_start:span.body_open]
    params_start = header.find("(")
    params_end = header.rfind(")")
    if params_start == -1 or params_end == -1 or params_end <= params_start:
        return set()
    params = _split_top_level_csv(header[params_start + 1:params_end])
    if params is None:
        return set()
    names: set[str] = set()
    for param in params:
        if not param or param == "void" or "..." in param:
            continue
        match = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?$", param)
        if match is not None:
            names.add(match.group(1))
    return names


def _target_shadows_symbol(source_text: str, span, symbol: str) -> bool:
    if symbol in _function_parameter_names(source_text, span):
        return True
    body = _blank_literals_and_comments(source_text[span.body_open + 1:span.body_close])
    symbol_pattern = re.escape(symbol)
    if re.search(r"\(\s*\*\s*" + symbol_pattern + r"\s*\)", body, re.DOTALL):
        return True
    if re.search(r"\btypedef\b.*?\b" + symbol_pattern + r"\s*;", body, re.DOTALL):
        return True
    if re.search(
        r"\b(?:struct|union|enum)\s+" + symbol_pattern + r"\s*{",
        body,
        re.DOTALL,
    ):
        return True
    decl_re = re.compile(
        r"^[ \t]*(?!(?:return|if|while|for|switch|case|default|goto|break|continue)\b)"
        r"(?:static[ \t]+|const[ \t]+|volatile[ \t]+|register[ \t]+|"
        r"signed[ \t]+|unsigned[ \t]+|long[ \t]+|short[ \t]+)*"
        r"(?:(?:struct|union|enum)[ \t]+[A-Za-z_]\w*|[A-Za-z_]\w*)\b"
        r"(?P<rest>.*);[ \t]*$"
    )
    for line in body.splitlines():
        match = decl_re.match(line)
        if match is None:
            continue
        rest = match.group("rest").strip()
        if re.match(r"^\(\s*\*", rest) and re.search(
            r"\b" + re.escape(symbol) + r"\b",
            rest,
        ):
            return True
        if rest.startswith("("):
            continue
        declarators = _split_top_level_csv(rest.rstrip(";"))
        if declarators is None:
            if re.search(r"(?:^|[,\s*])" + re.escape(symbol) + r"\b", rest):
                return True
            continue
        for declarator in declarators:
            declarator_head = declarator.split("=", 1)[0].strip()
            declarator_head = declarator_head.replace("*", " ")
            name_match = re.search(
                r"\b([A-Za-z_]\w*)\b(?:\s*\[[^\]]*\])?\s*$",
                declarator_head,
            )
            if name_match is not None and name_match.group(1) == symbol:
                return True
    return False


def _blank_literals_and_comments(text: str) -> str:
    out = list(text)
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in {'"', "'"}:
            quote = ch
            i += 1
            while i < len(text):
                if text[i] == "\\" and i + 1 < len(text):
                    if text[i] != "\n":
                        out[i] = " "
                    if text[i + 1] != "\n":
                        out[i + 1] = " "
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            continue
        if ch == "/" and i + 1 < len(text):
            if text[i + 1] == "/":
                while i < len(text) and text[i] != "\n":
                    out[i] = " "
                    i += 1
                continue
            if text[i + 1] == "*":
                out[i] = " "
                out[i + 1] = " "
                i += 2
                while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                    if text[i] != "\n":
                        out[i] = " "
                    i += 1
                if i + 1 < len(text):
                    out[i] = " "
                    out[i + 1] = " "
                    i += 2
                continue
        i += 1
    return "".join(out)


def _normalize_c_type(type_name: str) -> str:
    normalized = re.sub(r"\s+", " ", type_name.strip())
    normalized = re.sub(r"\s*\*\s*", "*", normalized)
    normalized = re.sub(r"\bconst\b", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _top_level_function_spans(source_text: str) -> tuple[tuple[int, int], ...]:
    return tuple(
        (span.sig_start, span.full_end)
        for span in find_function_definitions(source_text)
    )


def _inside_any_span(offset: int, spans: Iterable[tuple[int, int]]) -> bool:
    return any(start <= offset < end for start, end in spans)


_SCALAR_TYPE_RE = re.compile(
    r"^(?:bool|BOOL|s8|s16|s32|s64|u8|u16|u32|u64|int|short|long|f32|f64|float|double)$"
)


_SIMPLE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$")


_SIMPLE_ASSIGNMENT_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<lhs>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.+);\s*$"
)


def _is_scalar_type(type_name: str) -> bool:
    return _SCALAR_TYPE_RE.match(_normalize_type_name(type_name)) is not None


def _text_line_records(text: str) -> list[tuple[int, int, str]]:
    records: list[tuple[int, int, str]] = []
    pos = 0
    for raw in text.splitlines(keepends=True):
        line = raw[:-1] if raw.endswith("\n") else raw
        records.append((pos, pos + len(line), line))
        pos += len(raw)
    return records


def _parse_signature_params(signature: str) -> tuple[tuple[str, str], ...]:
    match = re.match(
        r"^(?:static\s+)?(?:void|bool|BOOL|s8|s16|s32|s64|u8|u16|u32|u64|int|short|long|f32|f64|float|double)\s+"
        r"[A-Za-z_]\w*\s*\((?P<params>.*)\)\s*$",
        signature.strip(),
        re.DOTALL,
    )
    if match is None:
        return ()
    params_text = match.group("params").strip()
    if not params_text or params_text == "void":
        return ()
    raw_params = _split_top_level_csv(params_text)
    if raw_params is None:
        return ()
    parsed: list[tuple[str, str]] = []
    for raw_param in raw_params:
        param_match = re.match(
            r"^(?P<type>bool|BOOL|s8|s16|s32|s64|u8|u16|u32|u64|int|short|long|f32|f64|float|double)\s+"
            r"(?P<name>[A-Za-z_]\w*)$",
            raw_param.strip(),
        )
        if param_match is not None:
            parsed.append((
                _normalize_type_name(param_match.group("type")),
                param_match.group("name"),
            ))
    return tuple(parsed)


def _text_line_records_with_newline(text: str) -> list[tuple[int, int, int, str]]:
    records: list[tuple[int, int, int, str]] = []
    pos = 0
    for raw in text.splitlines(keepends=True):
        line = raw[:-1] if raw.endswith("\n") else raw
        records.append((pos, pos + len(line), pos + len(raw), line))
        pos += len(raw)
    return records


def _line_depths_from_blanked_text(blanked_text: str) -> list[int]:
    depths: list[int] = []
    depth = 0
    for raw in blanked_text.splitlines(keepends=True):
        line = raw[:-1] if raw.endswith("\n") else raw
        depths.append(depth)
        depth += line.count("{") - line.count("}")
        depth = max(0, depth)
    return depths


def _normalize_local_reuse_type(type_name: str) -> str:
    normalized = re.sub(r"\s+", " ", type_name.strip())
    normalized = re.sub(r"\s*\*\s*$", "*", normalized)
    normalized = normalized.replace(" *", "*")
    return normalized


def _is_supported_local_reuse_type(type_name: str) -> bool:
    if _is_scalar_type(type_name):
        return True
    if type_name.endswith("*") and type_name.count("*") == 1:
        base = type_name[:-1]
        return _SIMPLE_IDENTIFIER_RE.match(base) is not None
    return False


def _identifier_is_member_name(searchable: str, start: int) -> bool:
    if start > 0 and searchable[start - 1] == ".":
        return True
    return start >= 2 and searchable[start - 2:start] == "->"


def _identifier_mentions(searchable: str, name: str) -> tuple[tuple[int, int], ...]:
    mentions: list[tuple[int, int]] = []
    pattern = re.compile(r"\b" + re.escape(name) + r"\b")
    for match in pattern.finditer(searchable):
        if _identifier_is_member_name(searchable, match.start()):
            continue
        mentions.append((match.start(), match.end()))
    return tuple(mentions)


def _normalize_compat_type(type_text: str) -> str | None:
    if not type_text or re.search(r"\bvolatile\b", type_text):
        return None
    text = re.sub(r"\b(?:static|extern|inline|register)\b", " ", type_text)
    text = re.sub(r"\s+", " ", text.strip())
    text = re.sub(r"\s*\*\s*", "*", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _normalize_param_type_text(param: str) -> str | None:
    param = param.strip()
    if not param or param == "void" or "..." in param:
        return None
    if re.search(r"\bvolatile\b", param):
        return None
    if "*" in param:
        match = re.match(r"^(?P<type>.+\*)\s*(?:[A-Za-z_]\w*)?$", param)
        if match is not None:
            return _normalize_compat_type(match.group("type"))
    parts = param.split()
    if len(parts) >= 2 and re.match(r"^[A-Za-z_]\w*$", parts[-1]):
        return _normalize_compat_type(" ".join(parts[:-1]))
    return _normalize_compat_type(param)


def _split_top_level_csv_spans(text: str) -> list[tuple[int, int, str]] | None:
    result: list[tuple[int, int, str]] = []
    depth = 0
    start = 0
    in_string: str | None = None
    escape = False
    for idx, ch in enumerate(text):
        if in_string is not None:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in {'"', "'"}:
            in_string = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return None
        elif ch == "," and depth == 0:
            item_start = start
            item_end = idx
            while item_start < item_end and text[item_start].isspace():
                item_start += 1
            while item_end > item_start and text[item_end - 1].isspace():
                item_end -= 1
            result.append((item_start, item_end, text[item_start:item_end]))
            start = idx + 1
    if depth != 0 or in_string is not None:
        return None
    item_start = start
    item_end = len(text)
    while item_start < item_end and text[item_start].isspace():
        item_start += 1
    while item_end > item_start and text[item_end - 1].isspace():
        item_end -= 1
    result.append((item_start, item_end, text[item_start:item_end]))
    return result


def _source_function_like_macro_names(source_text: str) -> set[str]:
    searchable = _blank_literals_and_comments(source_text)
    return {
        match.group("name")
        for match in re.finditer(
            r"(?m)^[ \t]*#\s*define\s+(?P<name>[A-Za-z_]\w*)\b",
            searchable,
        )
    }


def _function_name_for_span(source_text: str, searchable: str, span) -> str | None:
    parsed_name = getattr(span, "name", None)
    if isinstance(parsed_name, str) and parsed_name:
        return parsed_name
    signature_text = searchable[span.sig_start:span.body_open]
    match = re.search(r"\b(?P<name>[A-Za-z_]\w*)\s*\(", signature_text)
    if match is None:
        return None
    return match.group("name")


def _contract_make_edit(
    source_text: str,
    *,
    start: int,
    end: int,
    replacement_text: str,
    kind: str,
) -> dict[str, object]:
    return {
        "kind": kind,
        "start": start,
        "end": end,
        "span_text": source_text[start:end],
        "replacement_text": replacement_text,
    }
