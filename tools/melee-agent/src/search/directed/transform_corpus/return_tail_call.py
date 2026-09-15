"""Source-transform family: return_tail_call."""
from __future__ import annotations

import re
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _source_local_return_type


def _iter_return_tail_call_anchors(
    source_text: str,
    function: str,
    span,
):
    signature = source_text[span.sig_start:span.body_open].strip()
    if not re.match(r"^static\s+void\s+" + re.escape(function) + r"\s*\(", signature):
        return
    body_text = source_text[span.body_open:span.full_end]
    if re.search(r"\breturn\b", body_text):
        return
    body_inner = source_text[span.body_open + 1:span.body_close]
    lines = body_inner.splitlines()
    nonempty_indices = [idx for idx, line in enumerate(lines) if line.strip()]
    if not nonempty_indices:
        return
    final_idx = nonempty_indices[-1]
    final_line = lines[final_idx]
    if _leading_brace_depths(lines)[final_idx] != 0:
        return
    call = re.match(
        r"^(?P<indent>[ \t]*)(?P<callee>[A-Za-z_]\w*)\s*\((?P<args>[^;{}]*)\)\s*;\s*$",
        final_line,
    )
    if call is None:
        return
    if not call.group("args").strip() or call.group("args").strip() == "void":
        return
    helper_type = _source_local_return_type(source_text, call.group("callee"))
    if helper_type is None:
        return
    yield Anchor(
        mutator_key="return_tail_call_value",
        span=(span.sig_start, span.full_end),
        payload={
            "signature": signature,
            "replacement_signature": signature.replace("static void", f"static {helper_type}", 1),
            "line": final_line,
            "replacement_line": (
                f"{call.group('indent')}return {call.group('callee')}({call.group('args')});"
            ),
        },
    )


def _leading_brace_depths(lines: list[str]) -> list[int]:
    depths: list[int] = []
    depth = 0
    for line in lines:
        depths.append(depth)
        depth += line.count("{") - line.count("}")
        depth = max(0, depth)
    return depths
