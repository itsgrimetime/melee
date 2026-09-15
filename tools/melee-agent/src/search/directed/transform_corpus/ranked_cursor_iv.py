"""Source-transform family: ranked_cursor_iv."""
from __future__ import annotations

import re
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _blank_literals_and_comments, _identifier_mentions, _line_depths_from_blanked_text, _text_line_records_with_newline


_RANKED_CURSOR_VALUE_RE = re.compile(
    r"(?P<base_assign>^[ \t]*baseVal\s*=\s*base->value;\s*\n)"
    r"(?P<while_line>[ \t]*while\s*\(\s*k\s*<\s*25\s*\)\s*\{\s*\n)"
    r"(?:(?:[ \t]*//[^\n]*\n)|[ \t]*\n)*"
    r"[ \t]*if\s*\(\s*curr->value\s*!=\s*\(u64\)\s*neg1\s*\)\s*\{\s*\n"
    r"(?:(?:[ \t]*//[^\n]*\n)|[ \t]*\n)*"
    r"(?P<condition_indent>[ \t]*)if\s*\(\s*curr->value\s*>\s*"
    r"(?P<indexed>entries\[maxIdx\]\.value)\s*\|\|\s*\n"
    r"[ \t]*baseVal\s*==\s*\(u64\)\s*neg1\s*\)\s*\n"
    r"[ \t]*\{\s*\n"
    r"(?P<update_indent>[ \t]*)maxIdx\s*=\s*k;",
    re.MULTILINE,
)


_RANKED_CURSOR_RETURN_RE = re.compile(
    r"^[ \t]*ptr\s*=\s*&entries\[rank\];\s*\n"
    r"[ \t]*if\s*\(\s*ptr->value\s*==\s*\(u64\)\s*-1\s*\)\s*\{\s*\n"
    r"[ \t]*return\s+25;\s*\n"
    r"[ \t]*\}\s*\n"
    r"(?P<return_indent>[ \t]*)(?P<return_stmt>return entries\[rank\]\.name;)",
    re.MULTILINE,
)


_RANKED_CURSOR_LOCAL_ENTRIES_RE = re.compile(
    r"(?m)^[ \t]*(?:(?:struct|union)\s+)?[A-Za-z_]\w*\s+entries\s*\[\s*25\s*\]\s*;"
)


def _matching_brace_end(searchable: str, open_brace: int, limit: int) -> int | None:
    if not (0 <= open_brace < limit <= len(searchable)):
        return None
    if searchable[open_brace] != "{":
        return None
    depth = 0
    for idx in range(open_brace, limit):
        ch = searchable[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return idx + 1
    return None


def _ranked_cursor_local_entries_decl_start(body_text: str) -> int | None:
    searchable = _blank_literals_and_comments(body_text)
    depths = _line_depths_from_blanked_text(searchable)
    records = _text_line_records_with_newline(body_text)
    matches: list[int] = []
    for index, (start, _end, _end_with_newline, line) in enumerate(records):
        depth = depths[index] if index < len(depths) else 0
        if depth != 0:
            continue
        if _RANKED_CURSOR_LOCAL_ENTRIES_RE.match(line):
            matches.append(start)
    return matches[0] if len(matches) == 1 else None


def _iter_ranked_cursor_iv_unification_anchors(
    source_text: str,
    function: str,
    span,
):
    body_start = span.body_open + 1
    body_end = span.body_close
    body_text = source_text[body_start:body_end]
    if re.search(r"(?m)^[ \t]*#", body_text):
        return
    local_entries_decl_start = _ranked_cursor_local_entries_decl_start(body_text)
    if local_entries_decl_start is None:
        return

    value_matches = list(_RANKED_CURSOR_VALUE_RE.finditer(body_text))
    if len(value_matches) > 1:
        return
    if not value_matches and "entries[maxIdx].value" in body_text:
        return
    return_matches = list(_RANKED_CURSOR_RETURN_RE.finditer(body_text))
    if len(return_matches) > 1:
        return
    if not value_matches and not return_matches:
        return
    if value_matches and local_entries_decl_start >= value_matches[0].start("base_assign"):
        return
    if return_matches and local_entries_decl_start >= return_matches[0].start():
        return

    searchable = _blank_literals_and_comments(source_text)
    value_anchors: list[Anchor] = []
    for match in value_matches:
        while_line_start = body_start + match.start("while_line")
        while_open = source_text.find(
            "{",
            while_line_start,
            body_start + match.end("while_line"),
        )
        if while_open == -1:
            continue
        while_end = _matching_brace_end(searchable, while_open, body_end)
        if while_end is None:
            continue
        if _identifier_mentions(searchable[while_end:body_end], "baseVal"):
            continue

        condition_start = body_start + match.start("condition_indent")
        update_end = body_start + match.end()
        indexed_start = body_start + match.start("indexed")
        indexed_end = body_start + match.end("indexed")
        update_indent = match.group("update_indent")
        replacement_text = (
            "\n"
            f"{update_indent}if (baseVal != (u64) neg1) {{\n"
            f"{update_indent}    baseVal = curr->value;\n"
            f"{update_indent}}}"
        )
        anchor = Anchor(
            mutator_key="unify_ranked_cursor_value_accumulator",
            span=(condition_start, update_end),
            payload={
                "strategy": "ranked-cursor-value-accumulator",
                "anchor_span_text": source_text[condition_start:update_end],
                "selection_loop_span": (while_open, while_end),
                "edits": [
                    {
                        "kind": "indexed-value-to-accumulator",
                        "start": indexed_start,
                        "end": indexed_end,
                        "span_text": source_text[indexed_start:indexed_end],
                        "replacement_text": "baseVal",
                    },
                    {
                        "kind": "update-accumulator-after-max",
                        "start": update_end,
                        "end": update_end,
                        "span_text": "",
                        "replacement_text": replacement_text,
                    },
                ],
            },
        )
        value_anchors.append(anchor)
        break

    if value_matches and not value_anchors:
        return

    yield from value_anchors

    for match in return_matches:
        return_start = body_start + match.start("return_stmt")
        return_end = body_start + match.end("return_stmt")
        yield Anchor(
            mutator_key="reuse_rank_pointer_return_field",
            span=(return_start, return_end),
            payload={
                "strategy": "ranked-rank-pointer-return-field",
                "anchor_span_text": source_text[return_start:return_end],
                "edits": [
                    {
                        "kind": "rank-return-field",
                        "start": return_start,
                        "end": return_end,
                        "span_text": "return entries[rank].name;",
                        "replacement_text": "return ptr->name;",
                    },
                ],
            },
        )
        break
