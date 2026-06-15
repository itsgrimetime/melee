"""Source-transform family: pointer_alias."""
from __future__ import annotations

import re
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _blank_literals_and_comments, _line_containing


def _global_type_decls(source_text: str) -> dict[str, str]:
    pattern = re.compile(
        r"(?m)^(?:static\s+)?(?P<type>[A-Za-z_]\w*)\s+"
        r"(?P<name>[A-Za-z_]\w*)\s*;\s*$"
    )
    return {match.group("name"): match.group("type") for match in pattern.finditer(source_text)}


def _iter_global_pointer_alias_anchors(source_text: str, function: str, span):
    decls = _global_type_decls(source_text)
    header_line = _line_containing(source_text, span.body_open)
    header_end = source_text.find("\n", span.body_open)
    if header_end == -1:
        return
    body_inner = source_text[header_end + 1:span.body_close]
    searchable_body = _blank_literals_and_comments(body_inner)
    for global_name, type_name in sorted(decls.items()):
        prefix = f"{global_name}."
        access_matches = list(
            re.finditer(
                r"(?<![A-Za-z0-9_\"'])" + re.escape(prefix) + r"(?P<field>[A-Za-z_]\w*)",
                searchable_body,
            )
        )
        if len(access_matches) < 2:
            continue
        alias_name = f"{global_name}_alias"
        if re.search(r"\b" + re.escape(alias_name) + r"\b", body_inner):
            continue
        access_spans = tuple(
            (match.start(), match.end(), f"{alias_name}->{match.group('field')}")
            for match in access_matches
        )
        yield Anchor(
            mutator_key="introduce_global_pointer_alias",
            span=(span.body_open, span.body_close),
            payload={
                "insert_after_line": header_line,
                "alias_line": f"    {type_name}* {alias_name} = &{global_name};",
                "global_prefix": prefix,
                "alias_prefix": f"{alias_name}->",
                "scope_text": body_inner,
                "access_spans": access_spans,
            },
        )
