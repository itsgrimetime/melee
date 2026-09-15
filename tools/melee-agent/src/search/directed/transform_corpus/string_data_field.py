"""Source-transform family: string_data_field."""
from __future__ import annotations

import re
from src.mwcc_debug.source_patch import find_function_definitions
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _target_function_body


_STRING_LITERAL_RE = r'"(?:\\.|[^"\\])*"'


def _data_field_candidates(source_text: str, *, before_offset: int) -> dict[str, list[str]]:
    function_spans = tuple(find_function_definitions(source_text[:before_offset]))

    def inside_function(offset: int) -> bool:
        return any(span.sig_start <= offset < span.full_end for span in function_spans)

    pattern = re.compile(
        r"struct\s*{\s*char\s+(?P<field>[A-Za-z_]\w*)\s*\[[^\]]+\]\s*;\s*}\s*"
        r"(?P<symbol>[A-Za-z_]\w*)\s*=\s*{\s*(?P<literal>"
        + _STRING_LITERAL_RE
        + r")\s*}",
        re.DOTALL,
    )
    candidates: dict[str, list[str]] = {}
    for match in pattern.finditer(source_text[:before_offset]):
        if inside_function(match.start()):
            continue
        candidates.setdefault(match.group("literal"), []).append(
            f"{match.group('symbol')}.{match.group('field')}"
        )
    return candidates


def _iter_string_data_field_anchors(
    source_text: str,
    function: str,
):
    target = _target_function_body(source_text, function)
    if target is None:
        return
    span, body_text = target
    candidates = _data_field_candidates(source_text, before_offset=span.sig_start)
    for line in body_text.splitlines():
        if "(" not in line or ")" not in line:
            continue
        for literal in re.findall(_STRING_LITERAL_RE, line):
            replacements = candidates.get(literal, [])
            if len(replacements) != 1:
                continue
            yield Anchor(
                mutator_key="replace_string_literal_with_data_field",
                span=(0, 0),
                payload={
                    "line": line,
                    "literal": literal,
                    "replacement": replacements[0],
                },
            )
