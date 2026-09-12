"""Source-transform family: pragma_codegen."""
from __future__ import annotations

import re
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _blank_literals_and_comments


_DONT_INLINE_PREFIX = "#pragma push\n#pragma dont_inline on\n"


_DONT_INLINE_SUFFIX = "#pragma pop\n"


def _previous_line_text(source_text: str, offset: int) -> str:
    prev_end = source_text.rfind("\n", 0, max(0, offset - 1))
    if prev_end == -1:
        return ""
    prev_start = source_text.rfind("\n", 0, prev_end)
    return source_text[prev_start + 1:prev_end]


def _next_line_text(source_text: str, offset: int) -> str:
    if offset < len(source_text) and source_text[offset] == "\n":
        offset += 1
    next_end = source_text.find("\n", offset)
    if next_end == -1:
        next_end = len(source_text)
    return source_text[offset:next_end]


def _pragma_target_body_allowed(source_text: str, span) -> bool:
    function_text = source_text[span.sig_start:span.full_end]
    searchable_function = _blank_literals_and_comments(function_text)
    if "#" in searchable_function:
        return False
    if re.search(r"(?m)^[ \t]*(?:case\b.*:|default:|[A-Za-z_]\w*\s*:)", searchable_function):
        return False
    body_inner = source_text[span.body_open + 1:span.body_close]
    nonempty_body_lines = [line for line in body_inner.splitlines() if line.strip()]
    if len(nonempty_body_lines) > 8:
        return False
    previous_line = _previous_line_text(source_text, span.sig_start).strip()
    next_line = _next_line_text(source_text, span.full_end).strip()
    if previous_line.startswith("#pragma") or next_line.startswith("#pragma"):
        return False
    return True


def _pragma_wrapped_header_is_exact(
    source_text: str,
    *,
    function: str,
    header_start: int,
    body_open: int,
) -> bool:
    header = source_text[header_start:body_open]
    searchable_header = _blank_literals_and_comments(header)
    if "#" in searchable_header:
        return False
    return re.search(r"\b" + re.escape(function) + r"\s*\(", searchable_header) is not None


def _iter_function_codegen_pragma_anchors(source_text: str, function: str, span):
    function_end = span.full_end
    if source_text.startswith("\n", function_end):
        function_end += 1
    function_text = source_text[span.sig_start:function_end]
    prefix_start = span.sig_start
    if function_text.startswith(_DONT_INLINE_PREFIX):
        header_start = span.sig_start + len(_DONT_INLINE_PREFIX)
        if not _pragma_wrapped_header_is_exact(
            source_text,
            function=function,
            header_start=header_start,
            body_open=span.body_open,
        ):
            return
        suffix_start = function_end
        replacement_text = function_text[len(_DONT_INLINE_PREFIX):]
        if source_text.startswith(_DONT_INLINE_SUFFIX, suffix_start):
            suffix_end = suffix_start + len(_DONT_INLINE_SUFFIX)
        else:
            suffix_end = -1
        if suffix_end != -1:
            span_text = source_text[prefix_start:suffix_end]
            yield Anchor(
                mutator_key="remove_dont_inline_pragma_pair",
                span=(prefix_start, suffix_end),
                payload={
                    "span_text": span_text,
                    "replacement_text": replacement_text,
                    "pragma_kind": "dont_inline",
                    "mode": "remove",
                    "target_function": function,
                    "removed_span": (prefix_start, suffix_end),
                    "function_span": (span.sig_start, span.full_end),
                },
            )
        return
    prefix_start = span.sig_start - len(_DONT_INLINE_PREFIX)
    if prefix_start >= 0 and source_text[prefix_start:span.sig_start] == _DONT_INLINE_PREFIX:
        suffix_start = function_end
        if source_text.startswith(_DONT_INLINE_SUFFIX, suffix_start):
            suffix_end = suffix_start + len(_DONT_INLINE_SUFFIX)
            span_text = source_text[prefix_start:suffix_end]
            yield Anchor(
                mutator_key="remove_dont_inline_pragma_pair",
                span=(prefix_start, suffix_end),
                payload={
                    "span_text": span_text,
                    "replacement_text": function_text,
                    "pragma_kind": "dont_inline",
                    "mode": "remove",
                    "target_function": function,
                    "removed_span": (prefix_start, suffix_end),
                    "function_span": (span.sig_start, function_end),
                },
            )
        return
    if not _pragma_target_body_allowed(source_text, span):
        return
    replacement_function_text = (
        function_text if function_text.endswith("\n") else f"{function_text}\n"
    )
    replacement_text = (
        _DONT_INLINE_PREFIX + replacement_function_text + _DONT_INLINE_SUFFIX
    )
    yield Anchor(
        mutator_key="add_dont_inline_pragma_pair",
        span=(span.sig_start, function_end),
        payload={
            "span_text": function_text,
            "replacement_text": replacement_text,
            "pragma_kind": "dont_inline",
            "mode": "add",
            "target_function": function,
            "inserted_span": (span.sig_start, function_end),
            "function_span": (span.sig_start, function_end),
        },
    )
