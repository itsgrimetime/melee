"""Source-level field attribution from offset-commented C structs.

This module is intentionally lightweight: it extracts enough C shape to bind
MWCC pcode loads such as ``lwz r58,44(r106)`` back to expressions like
``gobj->user_data`` when the source tree carries the usual Melee offset
comments (``/* +2C */ void* user_data;``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from . import ast_walker
from .symbol_bridge import _extract_function_text, _parse_params, walk_local_decls


@dataclass(frozen=True)
class StructField:
    struct_name: str
    offset: int
    type: str
    name: str


@dataclass(frozen=True)
class ResolvedSourceExpression:
    expression: str
    type: str | None
    field_name: str | None = None
    source_line: int | None = None
    source_col: int | None = None
    base_var: str | None = None
    confidence: str = "source-expression"


@dataclass(frozen=True)
class StackArrayLocal:
    name: str
    element_type: str
    pointer_type: str
    array_size: str | None
    source_line: int | None = None
    source_col: int | None = None


@dataclass(frozen=True)
class SourceFieldContext:
    source_text: str
    function: str | None
    source_file: str | None
    function_text: str
    function_start: int
    texts: tuple[str, ...]
    local_types: Mapping[str, str]
    global_types: Mapping[str, str]
    struct_fields: Mapping[str, Mapping[int, StructField]]
    stack_arrays: Mapping[str, StackArrayLocal]


_INCLUDE_RE = re.compile(r'(?m)^\s*#\s*include\s+[<"](?P<path>[^>"]+)[>"]')
_STRUCT_RE = re.compile(
    r"\bstruct\s+(?P<name>[A-Za-z_][A-Za-z_0-9]*)\s*\{",
    re.MULTILINE,
)
_FIELD_RE = re.compile(
    r"/\*\s*(?:fp\+|\+)?(?P<offset>0x[0-9A-Fa-f]+|[0-9A-Fa-f]+)"
    r"(?::\d+)?\s*\*/\s*"
    r"(?P<type>[^;{}]+?)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z_0-9]*)(?:\[[^\]]*\])?\s*;",
    re.DOTALL,
)
_GLOBAL_DECL_RE = re.compile(
    r"(?m)^\s*"
    r"(?:(?:extern|static|SDATA|DATA|CONST|volatile|const|register)\s+)*"
    r"(?P<type>[A-Za-z_][A-Za-z_0-9]*(?:\s+[A-Za-z_][A-Za-z_0-9]*)*"
    r"(?:\s*\*+\s*)?)"
    r"\s+"
    r"(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"\s*(?:\[[^\]]*\])?\s*(?:=[^;]*)?;",
)
_ASSIGNMENT_RE = re.compile(
    r"(?m)^\s*(?P<lhs>[A-Za-z_][A-Za-z_0-9]*)\s*=\s*(?P<rhs>[^;\n]+);\s*$"
)
_DECL_ASSIGNMENT_RE = re.compile(
    r"(?m)^\s*"
    r"(?P<type>[A-Za-z_][A-Za-z_0-9]*(?:\s+[A-Za-z_][A-Za-z_0-9]*)*"
    r"(?:\s*\*+\s*)?)"
    r"\s+"
    r"(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"\s*=\s*(?P<rhs>[^;\n]+);\s*$"
)
_SIMPLE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")
_STACK_ADDI_RE = re.compile(
    r"\baddi\s+r(?P<dest>\d+)\s*,\s*r1\s*,\s*"
    r"(?P<name>[A-Za-z_][A-Za-z_0-9]*)\b",
    re.IGNORECASE,
)
_ARRAY_TYPE_RE = re.compile(r"^(?P<element>.+?)\s*\[(?P<size>[^\]]*)\]\s*$")


def build_source_field_context(
    source_text: str,
    *,
    function: str | None = None,
    source_file: str | Path | None = None,
    melee_root: str | Path | None = None,
) -> SourceFieldContext:
    """Build a small source/type lookup context for field attribution."""
    source_path = _coerce_existing_path(source_file)
    root = _find_melee_root(source_path, melee_root)
    texts = _collect_source_texts(source_text, source_path=source_path, melee_root=root)
    function_text, function_start = _cached_function_body(source_text, function)
    return SourceFieldContext(
        source_text=source_text,
        function=function,
        source_file=str(source_file) if source_file is not None else None,
        function_text=function_text,
        function_start=function_start,
        texts=tuple(texts),
        local_types=_local_types(source_text, function),
        global_types=_global_types(texts),
        struct_fields=_struct_fields(texts),
        stack_arrays=_stack_array_locals(source_text, function),
    )


def parse_pcode_load_expression(expression: str | None) -> tuple[int | None, int, int] | None:
    if not isinstance(expression, str):
        return None
    match = re.search(
        r"\b(?:lwz|lbz|lha|lhz|stw|stb|sth)\s+"
        r"r(?P<dest>\d+)\s*,\s*"
        r"(?P<offset>[-+]?(?:0x[0-9A-Fa-f]+|\d+))\s*"
        r"\(\s*r(?P<base>\d+)\s*\)",
        expression,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return (
        int(match.group("dest")),
        int(match.group("offset"), 0),
        int(match.group("base")),
    )


def parse_symbolic_global_load_expression(
    expression: str | None,
) -> tuple[int, str] | None:
    if not isinstance(expression, str):
        return None
    match = re.search(
        r"\b(?:lwz|lbz|lha|lhz)\s+r(?P<dest>\d+)\s*,\s*"
        r"(?P<symbol>[A-Za-z_][A-Za-z_0-9]*)\s*\(\s*r0\s*\)",
        expression,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return int(match.group("dest")), match.group("symbol")


def source_for_global_symbol(
    context: SourceFieldContext,
    symbol: str,
) -> ResolvedSourceExpression | None:
    type_name = context.global_types.get(symbol)
    if type_name is None:
        return None
    line, col = _first_function_occurrence(context, symbol)
    return ResolvedSourceExpression(
        expression=symbol,
        type=type_name,
        source_line=line,
        source_col=col,
        base_var=symbol,
        confidence="global-symbol",
    )


def parse_stack_array_base_expression(
    expression: str | None,
) -> tuple[int, str] | None:
    if not isinstance(expression, str):
        return None
    match = _STACK_ADDI_RE.search(expression)
    if match is None:
        return None
    return int(match.group("dest")), match.group("name")


def source_for_stack_array_base(
    context: SourceFieldContext,
    expression: str | None,
) -> ResolvedSourceExpression | None:
    parsed = parse_stack_array_base_expression(expression)
    if parsed is None:
        return None
    _dest, name = parsed
    local = context.stack_arrays.get(name)
    if local is None:
        return None
    return ResolvedSourceExpression(
        expression=local.name,
        type=local.pointer_type,
        source_line=local.source_line,
        source_col=local.source_col,
        base_var=local.name,
        confidence="stack-array-base",
    )


def source_for_stack_array_field_offset(
    context: SourceFieldContext,
    *,
    base_expression: str | None,
    base_type: str | None,
    offset: int,
) -> ResolvedSourceExpression | None:
    base = (base_expression or "").strip()
    local = context.stack_arrays.get(base)
    if local is None:
        return None
    if base_type is not None and _clean_type(base_type) != local.pointer_type:
        return None
    field = _field_for_type(context, local.pointer_type, offset)
    if field is None:
        return None
    occurrence = _first_stack_array_field_occurrence(context, local.name, field.name)
    if occurrence is None:
        return None
    expression, line, col = occurrence
    return ResolvedSourceExpression(
        expression=expression,
        type=_refined_field_type(context, expression, field.type),
        field_name=field.name,
        source_line=line,
        source_col=col,
        base_var=local.name,
        confidence="stack-array-field",
    )


def source_for_field_offset(
    context: SourceFieldContext,
    *,
    base_expression: str | None,
    base_type: str | None,
    offset: int,
) -> ResolvedSourceExpression | None:
    """Resolve ``base_expression + offset`` to a typed C field expression."""
    base_expr = (base_expression or "").strip()
    candidates: list[tuple[tuple[int, int, int], ResolvedSourceExpression]] = []
    for alias, alias_type, assignment_line in _aliases_for_expression(
        context,
        base_expr,
    ):
        alias_field = _field_for_type(context, alias_type, offset)
        if alias_field is None:
            continue
        resolved = _resolved_field_expression(
            context,
            base=alias,
            base_type=alias_type,
            field=alias_field,
            prefer_source_match=True,
        )
        if resolved is not None:
            candidates.append((
                _alias_field_resolution_rank(assignment_line, resolved),
                resolved,
            ))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    field = _field_for_type(context, base_type, offset)
    if field is None:
        return None

    if base_expr:
        resolved = _resolved_field_expression(
            context,
            base=base_expr,
            base_type=base_type,
            field=field,
            prefer_source_match=True,
        )
        if resolved is not None:
            return resolved
    return None


def _alias_field_resolution_rank(
    assignment_line: int | None,
    resolved: ResolvedSourceExpression,
) -> tuple[int, int, int]:
    source_line = resolved.source_line
    if source_line is None:
        return (1, 10**9, 10**9)
    if assignment_line is None:
        return (0, 10**8, source_line)
    distance = source_line - assignment_line
    if distance < 0:
        distance = 10**7 + abs(distance)
    return (0, distance, source_line)


def infer_global_field_source(
    context: SourceFieldContext,
    *,
    offset: int,
) -> ResolvedSourceExpression | None:
    """Infer a field load source when the pcode base temp is not attributed."""
    candidates: list[ResolvedSourceExpression] = []
    for symbol, type_name in context.global_types.items():
        if _field_for_type(context, type_name, offset) is None:
            continue
        resolved = source_for_field_offset(
            context,
            base_expression=symbol,
            base_type=type_name,
            offset=offset,
        )
        if resolved is not None and resolved.source_line is not None:
            candidates.append(resolved)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.source_line or 10**9, item.source_col or 0))
    return candidates[0]


def _coerce_existing_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        candidate = candidate.resolve()
    except OSError:
        return None
    return candidate if candidate.is_file() else None


def _find_melee_root(source_path: Path | None, melee_root: str | Path | None) -> Path | None:
    if melee_root is not None:
        root = Path(melee_root)
        if not root.is_absolute():
            root = Path.cwd() / root
        return root
    starts = []
    if source_path is not None:
        starts.append(source_path.parent)
    starts.append(Path.cwd())
    for start in starts:
        for parent in (start, *start.parents):
            if (parent / "configure.py").is_file() and (parent / "src").is_dir():
                return parent
    return None


def _collect_source_texts(
    source_text: str,
    *,
    source_path: Path | None,
    melee_root: Path | None,
    max_depth: int = 2,
) -> list[str]:
    texts = [source_text]
    seen: set[Path] = set()

    def visit(text: str, base_dir: Path | None, depth: int) -> None:
        if depth >= max_depth:
            return
        for include in _INCLUDE_RE.finditer(text):
            path = _resolve_include(
                include.group("path"),
                base_dir=base_dir,
                melee_root=melee_root,
            )
            if path is None or path in seen:
                continue
            seen.add(path)
            try:
                included = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            texts.append(included)
            visit(included, path.parent, depth + 1)

    visit(source_text, None if source_path is None else source_path.parent, 0)
    return texts


def _resolve_include(
    include: str,
    *,
    base_dir: Path | None,
    melee_root: Path | None,
) -> Path | None:
    candidates: list[Path] = []
    if base_dir is not None:
        candidates.append(base_dir / include)
    if melee_root is not None:
        candidates.extend([
            melee_root / include,
            melee_root / "src" / include,
            melee_root / "src" / "melee" / include,
            melee_root / "src" / "sysdolphin" / include,
        ])
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _local_types(source_text: str, function: str | None) -> dict[str, str]:
    if function is None:
        return {}
    extracted = _extract_function_text(source_text, function)
    if extracted is None:
        return {}
    params_text, body_text, _start_line = extracted
    types: dict[str, str] = {}
    for decl in [*_parse_params(params_text), *walk_local_decls(body_text)]:
        if decl.name not in types:
            types[decl.name] = _clean_type(decl.type_str)
    return types


def _stack_array_locals(
    source_text: str,
    function: str | None,
) -> dict[str, StackArrayLocal]:
    if function is None:
        return {}
    arrays: dict[str, StackArrayLocal] = {}
    try:
        decls = ast_walker.walk_function(source_text, function, path=None)
    except Exception:
        decls = []
    for decl in decls:
        local = _stack_array_from_type(
            decl.name,
            decl.type_str,
            source_text=source_text,
            byte_range=decl.byte_range,
        )
        if local is not None and local.name not in arrays:
            arrays[local.name] = local
    if arrays:
        return arrays

    extracted = _extract_function_text(source_text, function)
    if extracted is None:
        return {}
    _params_text, body_text, _start_line = extracted
    function_start = source_text.find(body_text)
    body_start = 0 if function_start < 0 else function_start
    pattern = re.compile(
        r"(?m)^[ \t]*"
        r"(?P<type>(?:struct\s+)?[A-Za-z_][A-Za-z_0-9]*"
        r"(?:\s+[A-Za-z_][A-Za-z_0-9]*)*(?:\s*\*+)?)"
        r"\s+(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
        r"\s*\[(?P<size>[^\]]*)\]\s*(?:=[^;]*)?;"
    )
    for match in pattern.finditer(body_text):
        type_str = f"{match.group('type')}[{match.group('size')}]"
        local = _stack_array_from_type(
            match.group("name"),
            type_str,
            source_text=source_text,
            char_offset=body_start + match.start("name"),
        )
        if local is not None and local.name not in arrays:
            arrays[local.name] = local
    return arrays


def _stack_array_from_type(
    name: str,
    type_str: str,
    *,
    source_text: str,
    byte_range: tuple[int, int] | None = None,
    char_offset: int | None = None,
) -> StackArrayLocal | None:
    match = _ARRAY_TYPE_RE.match(_clean_type(type_str))
    if match is None:
        return None
    element_type = _clean_type(match.group("element"))
    array_size = match.group("size").strip() or None
    if any(ch in element_type for ch in "[]{}(),="):
        return None
    pointer_type = _clean_type(f"{element_type}*")
    line = col = None
    if char_offset is None and byte_range is not None:
        char_offset = _char_offset_from_byte_offset(source_text, byte_range[0])
    if char_offset is not None:
        line, col = _line_col(source_text, char_offset)
    return StackArrayLocal(
        name=name,
        element_type=element_type,
        pointer_type=pointer_type,
        array_size=array_size,
        source_line=line,
        source_col=col,
    )


def _cached_function_body(
    source_text: str,
    function: str | None,
) -> tuple[str, int]:
    if function is None:
        return source_text, 0
    extracted = _extract_function_text(source_text, function)
    if extracted is None:
        return source_text, 0
    _params_text, body_text, _start_line = extracted
    start = source_text.find(body_text)
    return body_text, max(0, start)


def _global_types(texts: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for text in texts:
        stripped = _top_level_decl_text(_strip_comments_keep_newlines(text))
        for match in _GLOBAL_DECL_RE.finditer(stripped):
            name = match.group("name")
            if name not in out:
                out[name] = _clean_type(match.group("type"))
    return out


def _struct_fields(texts: list[str]) -> dict[str, dict[int, StructField]]:
    out: dict[str, dict[int, StructField]] = {}
    for text in texts:
        for match in _STRUCT_RE.finditer(text):
            name = match.group("name")
            body = _struct_body(text, match.end())
            if body is None:
                continue
            fields = out.setdefault(name, {})
            for field_match in _FIELD_RE.finditer(body):
                try:
                    offset = int(field_match.group("offset"), 16)
                except ValueError:
                    continue
                fields.setdefault(offset, StructField(
                    struct_name=name,
                    offset=offset,
                    type=_clean_type(field_match.group("type")),
                    name=field_match.group("name"),
                ))
    return out


def _struct_body(text: str, start: int) -> str | None:
    depth = 1
    idx = start
    while idx < len(text):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx]
        idx += 1
    return None


def _field_for_type(
    context: SourceFieldContext,
    type_name: str | None,
    offset: int,
) -> StructField | None:
    struct_name = _struct_name_from_type(type_name)
    if struct_name is None:
        return None
    return context.struct_fields.get(struct_name, {}).get(offset)


def _struct_name_from_type(type_name: str | None) -> str | None:
    if not type_name:
        return None
    text = _clean_type(type_name)
    text = re.sub(r"\b(?:const|volatile|register|static)\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("*", " ").strip()
    if text.startswith("struct "):
        text = text[len("struct "):].strip()
    if not _SIMPLE_IDENT_RE.match(text):
        return None
    if text == "void":
        return None
    return text


def _resolved_field_expression(
    context: SourceFieldContext,
    *,
    base: str,
    base_type: str | None,
    field: StructField,
    prefer_source_match: bool,
) -> ResolvedSourceExpression | None:
    operator = "->" if _looks_like_pointer_type(base_type) else "."
    expression = f"{base}{operator}{field.name}"
    line = col = None
    if prefer_source_match:
        line, col = _first_function_occurrence(context, expression)
        if line is None and not _SIMPLE_IDENT_RE.match(base):
            return None
    source_type = _refined_field_type(context, expression, field.type)
    return ResolvedSourceExpression(
        expression=expression,
        type=source_type,
        field_name=field.name,
        source_line=line,
        source_col=col,
        base_var=base if _SIMPLE_IDENT_RE.match(base) else None,
        confidence="source-expression" if line is not None else "field-offset",
    )


def _first_stack_array_field_occurrence(
    context: SourceFieldContext,
    array_name: str,
    field_name: str,
) -> tuple[str, int, int] | None:
    function_text = _function_text(context)
    if not function_text:
        return None
    pattern = re.compile(
        rf"\b{re.escape(array_name)}\s*\[[^\]]+\]\s*\.\s*"
        rf"{re.escape(field_name)}\b"
    )
    matches = list(pattern.finditer(function_text))
    if len(matches) != 1:
        return None
    match = matches[0]
    absolute = context.function_start + match.start()
    line, col = _line_col(context.source_text, absolute)
    return match.group(0).strip(), line, col


def _aliases_for_expression(
    context: SourceFieldContext,
    expression: str,
) -> list[tuple[str, str, int | None]]:
    if not expression:
        return []
    aliases: list[tuple[int, str, str, int | None]] = []
    function_text = _function_text(context)
    function_start = context.function_start
    for pattern in (_DECL_ASSIGNMENT_RE, _ASSIGNMENT_RE):
        for match in pattern.finditer(function_text):
            rhs = _compact_expr(match.group("rhs"))
            if rhs != _compact_expr(expression):
                continue
            name = match.group("name") if "name" in match.groupdict() else match.group("lhs")
            type_name = (
                _clean_type(match.group("type"))
                if "type" in match.groupdict()
                else context.local_types.get(name)
            )
            if type_name is None:
                continue
            absolute = (
                match.start()
                if function_start < 0
                else function_start + match.start()
            )
            assignment_line, _assignment_col = _line_col(context.source_text, absolute)
            aliases.append((match.start(), name, type_name, assignment_line))
    aliases.sort(key=lambda item: item[0])
    return [
        (name, type_name, assignment_line)
        for _start, name, type_name, assignment_line in aliases
    ]


def _refined_field_type(
    context: SourceFieldContext,
    expression: str,
    fallback_type: str | None,
) -> str | None:
    if fallback_type and _clean_type(fallback_type) != "void*":
        return _clean_type(fallback_type)
    compact = _compact_expr(expression)
    function_text = _function_text(context)
    for pattern in (_DECL_ASSIGNMENT_RE, _ASSIGNMENT_RE):
        for match in pattern.finditer(function_text):
            if _compact_expr(match.group("rhs")) != compact:
                continue
            if "type" in match.groupdict():
                return _clean_type(match.group("type"))
            lhs = match.group("lhs")
            if lhs in context.local_types:
                return _clean_type(context.local_types[lhs])
    return _clean_type(fallback_type) if fallback_type else None


def _first_function_occurrence(
    context: SourceFieldContext,
    expression: str,
) -> tuple[int | None, int | None]:
    function_text = _function_text(context)
    if not function_text:
        return None, None
    pattern = _expression_pattern(expression)
    match = pattern.search(function_text)
    if match is None:
        return None, None
    function_start = context.function_start
    absolute = function_start + match.start()
    return _line_col(context.source_text, absolute)


def _function_text(context: SourceFieldContext) -> str:
    return context.function_text


def _expression_pattern(expression: str) -> re.Pattern[str]:
    pieces = [
        r"\s*" if part.isspace() else re.escape(part)
        for part in re.split(r"(\s+)", expression.strip())
        if part
    ]
    text = "".join(pieces)
    text = text.replace(r"\-\>", r"\s*->\s*").replace(r"\.", r"\s*\.\s*")
    return re.compile(text)


def _line_col(source: str, offset: int) -> tuple[int, int]:
    line = source.count("\n", 0, offset) + 1
    prev = source.rfind("\n", 0, offset)
    col = offset + 1 if prev < 0 else offset - prev
    return line, col


def _char_offset_from_byte_offset(source: str, byte_offset: int) -> int:
    prefix = source.encode("utf-8")[:max(0, byte_offset)]
    return len(prefix.decode("utf-8", errors="ignore"))


def _compact_expr(expression: str) -> str:
    return re.sub(r"\s+", "", expression)


def _clean_type(type_name: str) -> str:
    text = re.sub(r"\s+", " ", type_name.strip())
    text = re.sub(r"\s*\*\s*", "*", text)
    return text


def _looks_like_pointer_type(type_name: str | None) -> bool:
    return bool(type_name and "*" in type_name)


def _strip_comments_keep_newlines(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("//", i):
            while i < len(text) and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if text.startswith("/*", i):
            while i + 1 < len(text) and not text.startswith("*/", i):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i + 1 < len(text):
                out.extend("  ")
                i += 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _top_level_decl_text(text: str) -> str:
    """Keep only text outside brace bodies for global declaration scanning."""
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
            out.append(" ")
            continue
        if ch == "}":
            if depth:
                depth -= 1
            out.append(" ")
            continue
        if depth:
            out.append("\n" if ch == "\n" else " ")
        else:
            out.append(ch)
    return "".join(out)
