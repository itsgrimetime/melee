from __future__ import annotations

import re
from pathlib import Path

from .types import CallSite, InlineDef

_IDENT = r"[A-Za-z_][A-Za-z_0-9]*"
_INLINE_RE = re.compile(r"\binline\b")
_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)
_SCALAR_TYPES = {
    "BOOL",
    "bool",
    "char",
    "double",
    "f32",
    "f64",
    "float",
    "int",
    "long",
    "s8",
    "s16",
    "s32",
    "s64",
    "short",
    "u8",
    "u16",
    "u32",
    "u64",
}


def _find_matching(source: str, open_index: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    i = open_index
    while i < len(source):
        ch = source[i]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _signature_start(source: str, inline_index: int) -> int:
    start = source.rfind("\n", 0, inline_index) + 1
    while start > 0:
        prev_end = start - 1
        prev_start = source.rfind("\n", 0, prev_end) + 1
        line = source[prev_start:prev_end].strip()
        if not line or line.endswith(";") or line.endswith("}"):
            break
        if line.startswith("#"):
            break
        start = prev_start
    return start


def _split_params(param_text: str) -> list[tuple[str, str]]:
    text = param_text.strip()
    if not text or text == "void":
        return []
    params: list[tuple[str, str]] = []
    for raw in _split_args(text):
        part = raw.strip()
        if not part or part == "void":
            continue
        match = re.search(rf"({_IDENT})\s*(?:\[[^\]]*\])?\s*$", part)
        if match is None:
            params.append((part, ""))
            continue
        name = match.group(1)
        type_text = part[: match.start(1)].strip()
        type_text = re.sub(r"\s*\*\s*", "*", type_text)
        params.append((type_text, name))
    return params


def _split_args(arg_text: str) -> list[str]:
    args: list[str] = []
    start = 0
    depth = 0
    for idx, ch in enumerate(arg_text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            args.append(arg_text[start:idx].strip())
            start = idx + 1
    tail = arg_text[start:].strip()
    if tail:
        args.append(tail)
    return args


def _line_number(source: str, byte_index: int) -> int:
    return source.count("\n", 0, byte_index) + 1


def _statement_count(body: str) -> int:
    return len([part for part in body.split(";") if part.strip()])


def _return_class(signature_prefix: str) -> str:
    prefix = " ".join(signature_prefix.replace("\n", " ").split())
    if "*" in prefix:
        return "pointer"
    words = set(re.findall(_IDENT, prefix))
    if "void" in words:
        return "void"
    if "struct" in words:
        return "struct"
    if words & _SCALAR_TYPES:
        return "scalar"
    return "scalar"


def parse_inline_defs(
    source: str,
    path: str,
    *,
    def_location: str = "tu",
) -> list[InlineDef]:
    defs: list[InlineDef] = []
    for match in _INLINE_RE.finditer(source):
        brace = source.find("{", match.end())
        if brace < 0:
            continue
        sig_start = _signature_start(source, match.start())
        signature = source[sig_start:brace].strip()
        if ";" in signature:
            continue
        sig_flat = " ".join(signature.split())
        fn_match = re.search(rf"(?P<name>{_IDENT})\s*\((?P<params>.*)\)\s*$", sig_flat)
        if fn_match is None:
            continue
        close = _find_matching(source, brace, "{", "}")
        if close < 0:
            continue
        name = fn_match.group("name")
        prefix = sig_flat[: fn_match.start("name")]
        body = source[brace + 1:close].strip()
        returns = re.findall(r"\breturn\b", body)
        body_kind = (
            "single_return_expr"
            if len(returns) == 1 and re.fullmatch(r"\s*return\b.*;\s*", body, re.S)
            else "multi_statement"
        )
        defs.append(
            InlineDef(
                name=name,
                def_location="header" if def_location == "header" else "tu",
                def_file=f"{path}:{_line_number(source, sig_start)}",
                is_static=bool(re.search(r"\bstatic\b", prefix)),
                return_class=_return_class(prefix),
                body_kind=body_kind,
                params=_split_params(fn_match.group("params")),
                body_text=body,
                n_statements=_statement_count(body),
            )
        )
    return defs


def _find_function_body_span(source: str, function: str) -> tuple[int, int] | None:
    for match in re.finditer(rf"\b{re.escape(function)}\s*\(", source):
        paren = source.find("(", match.start())
        close_paren = _find_matching(source, paren, "(", ")")
        if close_paren < 0:
            continue
        brace = source.find("{", close_paren)
        semicolon = source.find(";", close_paren)
        if brace < 0 or (semicolon >= 0 and semicolon < brace):
            continue
        close = _find_matching(source, brace, "{", "}")
        if close < 0:
            continue
        return brace + 1, close
    return None


def find_call_sites(source: str, function: str, inline_name: str) -> list[CallSite]:
    span = _find_function_body_span(source, function)
    if span is None:
        return []
    body_start, body_end = span
    body = source[body_start:body_end]
    calls: list[CallSite] = []
    for match in re.finditer(rf"\b{re.escape(inline_name)}\s*\(", body):
        open_paren = body_start + body.find("(", match.start())
        close_paren = _find_matching(source, open_paren, "(", ")")
        if close_paren < 0 or close_paren > body_end:
            continue
        calls.append(
            CallSite(
                function=function,
                byte_start=body_start + match.start(),
                byte_end=close_paren + 1,
                args=_split_args(source[open_paren + 1:close_paren]),
            )
        )
    return calls


def _resolve_include(name: str, current_dir: Path, include_dirs: list[Path]) -> Path | None:
    candidates = [current_dir / name]
    candidates.extend(root / name for root in include_dirs)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def resolve_inline_defs(tu_path: Path, include_dirs: list[Path]) -> dict[str, InlineDef]:
    source = tu_path.read_text()
    defs = {item.name: item for item in parse_inline_defs(source, str(tu_path))}
    seen_headers: set[Path] = set()

    def visit_header(path: Path, depth: int) -> None:
        if depth > 3:
            return
        resolved = path.resolve()
        if resolved in seen_headers:
            return
        seen_headers.add(resolved)
        try:
            text = path.read_text()
        except OSError:
            return
        for item in parse_inline_defs(
            text,
            str(path),
            def_location="header",
        ):
            defs.setdefault(item.name, item)
        for include in _INCLUDE_RE.findall(text):
            child = _resolve_include(include, path.parent, include_dirs)
            if child is not None:
                visit_header(child, depth + 1)

    for include in _INCLUDE_RE.findall(source):
        header = _resolve_include(include, tu_path.parent, include_dirs)
        if header is not None:
            visit_header(header, 1)
    return defs


def classify_arg(arg: str) -> str:
    text = arg.strip()
    if re.fullmatch(rf"{_IDENT}", text):
        return "plain_id"
    if re.fullmatch(r"(0x[0-9A-Fa-f]+|\d+|'.'|\".*\")", text):
        return "literal"
    if "->" in text or "." in text:
        return "field_access"
    if text.startswith("&") or text.startswith("*"):
        return "pointer"
    return "expression"
