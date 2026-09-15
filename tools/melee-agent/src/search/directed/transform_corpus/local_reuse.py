"""Source-transform family: local_reuse."""
from __future__ import annotations

import re
from dataclasses import dataclass
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _blank_literals_and_comments, _identifier_mentions, _is_supported_local_reuse_type, _line_depths_from_blanked_text, _normalize_local_reuse_type, _text_line_records_with_newline


@dataclass(frozen=True)
class _LocalReuseDecl:
    type_name: str
    name: str
    line: str
    depth: int
    line_span: tuple[int, int]
    remove_span: tuple[int, int]
    name_span: tuple[int, int]


_LOCAL_REUSE_DECL_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<type>[A-Za-z_]\w*(?:\s*\*)?)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*;\s*$"
)


def _iter_local_reuse_decls(body_inner: str) -> tuple[_LocalReuseDecl, ...]:
    blanked = _blank_literals_and_comments(body_inner)
    depths = _line_depths_from_blanked_text(blanked)
    decls: list[_LocalReuseDecl] = []
    for idx, (start, end, end_with_newline, line) in enumerate(
        _text_line_records_with_newline(body_inner)
    ):
        if "//" in line or "/*" in line or "*/" in line:
            continue
        match = _LOCAL_REUSE_DECL_RE.match(line)
        if match is None:
            continue
        type_name = _normalize_local_reuse_type(match.group("type"))
        if not _is_supported_local_reuse_type(type_name):
            continue
        name_start = start + match.start("name")
        name_end = start + match.end("name")
        decls.append(
            _LocalReuseDecl(
                type_name=type_name,
                name=match.group("name"),
                line=line,
                depth=depths[idx] if idx < len(depths) else 0,
                line_span=(start, end),
                remove_span=(start, end_with_newline),
                name_span=(name_start, name_end),
            )
        )
    return tuple(decls)


def _local_reuse_body_has_barrier(searchable_body: str) -> bool:
    if "#" in searchable_body:
        return True
    if re.search(r"(?m)^[ \t]*(?:case\b.*:|default:|[A-Za-z_]\w*\s*:)", searchable_body):
        return True
    if re.search(r"\b(?:for|while|do)\b", searchable_body):
        return True
    return re.search(r"\bvolatile\b", searchable_body) is not None


def _local_reuse_address_taken(searchable_body: str, name: str) -> bool:
    return (
        re.search(
            r"&\s*(?:\(\s*)*" + re.escape(name) + r"\b",
            searchable_body,
        )
        is not None
    )


def _local_reuse_has_any_decl(searchable_body: str, name: str) -> bool:
    decl_re = re.compile(
        r"(?m)^[ \t]*(?:[A-Za-z_]\w*(?:\s*\*)?)\s+"
        + re.escape(name)
        + r"\b"
    )
    return decl_re.search(searchable_body) is not None


def _has_other_local_reuse_decl(
    decls: tuple[_LocalReuseDecl, ...],
    name: str,
    candidate_spans: set[tuple[int, int]],
) -> bool:
    return any(
        decl.name == name and decl.name_span not in candidate_spans
        for decl in decls
    )


def _replacement_scope_for_local_reuse(
    body_inner: str,
    *,
    later_decl: _LocalReuseDecl,
    replacement_spans: tuple[tuple[int, int], ...],
    replacement_name: str,
) -> str | None:
    edits: list[tuple[int, int, str]] = [
        (later_decl.remove_span[0], later_decl.remove_span[1], "")
    ]
    edits.extend((start, end, replacement_name) for start, end in replacement_spans)
    edits.sort(key=lambda item: item[0])
    pieces: list[str] = []
    cursor = 0
    for start, end, replacement in edits:
        if not (0 <= start <= end <= len(body_inner)):
            return None
        if start < cursor:
            return None
        pieces.append(body_inner[cursor:start])
        pieces.append(replacement)
        cursor = end
    pieces.append(body_inner[cursor:])
    rewritten = "".join(pieces)
    if rewritten == body_inner:
        return None
    return rewritten


def _mention_is_simple_assignment_lhs(body_inner: str, start: int, end: int) -> bool:
    line_start = body_inner.rfind("\n", 0, start) + 1
    line_end = body_inner.find("\n", end)
    if line_end == -1:
        line_end = len(body_inner)
    before = body_inner[line_start:start]
    after = body_inner[end:line_end]
    if before.strip():
        return False
    return re.match(r"\s*=(?!=)", after) is not None


def _iter_same_type_local_lifetime_reuse_anchors(source_text: str, span):
    body_start = span.body_open + 1
    body_end = span.body_close
    body_inner = source_text[body_start:body_end]
    searchable_body = _blank_literals_and_comments(body_inner)
    if _local_reuse_body_has_barrier(searchable_body):
        return
    decls = _iter_local_reuse_decls(body_inner)
    if len(decls) < 2:
        return
    for earlier_index, earlier in enumerate(decls):
        if earlier.depth != 0:
            continue
        earlier_mentions = _identifier_mentions(searchable_body, earlier.name)
        if any(start < earlier.name_span[0] for start, _end in earlier_mentions):
            continue
        if _local_reuse_address_taken(searchable_body, earlier.name):
            continue
        for later in decls[earlier_index + 1:]:
            if later.depth != 0 or later.type_name != earlier.type_name:
                continue
            if _local_reuse_address_taken(searchable_body, later.name):
                continue
            candidate_spans = {earlier.name_span, later.name_span}
            if _has_other_local_reuse_decl(decls, earlier.name, candidate_spans):
                continue
            if _has_other_local_reuse_decl(decls, later.name, candidate_spans):
                continue
            replacement_region = searchable_body[later.name_span[1]:]
            if _local_reuse_has_any_decl(replacement_region, earlier.name):
                continue
            if _local_reuse_has_any_decl(replacement_region, later.name):
                continue
            later_mentions = _identifier_mentions(searchable_body, later.name)
            if any(start < later.name_span[0] for start, _end in later_mentions):
                continue
            earlier_uses = tuple(
                (start, end)
                for start, end in earlier_mentions
                if start > earlier.name_span[1]
            )
            later_uses = tuple(
                (start, end)
                for start, end in later_mentions
                if start > later.name_span[1]
            )
            if not earlier_uses or not later_uses:
                continue
            last_earlier_use = max(start for start, _end in earlier_uses)
            first_later_use = min(start for start, _end in later_uses)
            if last_earlier_use >= first_later_use:
                continue
            first_later_span = min(later_uses, key=lambda item: item[0])
            if not _mention_is_simple_assignment_lhs(
                body_inner,
                first_later_span[0],
                first_later_span[1],
            ):
                continue
            replacement_scope = _replacement_scope_for_local_reuse(
                body_inner,
                later_decl=later,
                replacement_spans=later_uses,
                replacement_name=earlier.name,
            )
            if replacement_scope is None:
                continue
            yield Anchor(
                mutator_key="reuse_same_type_local_lifetime",
                span=(body_start, body_end),
                payload={
                    "scope_text": body_inner,
                    "replacement_scope_text": replacement_scope,
                    "reused_name": earlier.name,
                    "original_name": later.name,
                    "local_type": earlier.type_name,
                    "reused_decl_span": (
                        body_start + earlier.line_span[0],
                        body_start + earlier.line_span[1],
                    ),
                    "original_decl_span": (
                        body_start + later.line_span[0],
                        body_start + later.line_span[1],
                    ),
                    "replacement_spans": tuple(
                        (body_start + start, body_start + end, earlier.name)
                        for start, end in later_uses
                    ),
                    "first_original_use": body_start + first_later_use,
                    "last_reused_use": body_start + last_earlier_use,
                    "replacement_count": len(later_uses),
                    "removed_decl_line": later.line,
                },
            )
