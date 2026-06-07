"""Statement hoist/sink: relocate conservatively-safe movable units among a
function's top-level compound-block siblings. v1 does NOT recurse into nested
blocks; control/nested/declaration/non-classifiable statements are opaque,
immovable, unconditional barriers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from ..common import tree_sitter_c as _ts

# tree-sitter-c node types that are control/compound/declaration -> opaque barriers
_OPAQUE_KINDS = {
    "if_statement", "for_statement", "while_statement", "do_statement",
    "switch_statement", "compound_statement", "labeled_statement",
    "goto_statement", "declaration", "return_statement", "break_statement",
    "continue_statement",
}


@dataclass(frozen=True)
class SiblingStmt:
    text: str
    byte_range: tuple[int, int]
    line_range: tuple[int, int]
    kind: str  # "simple" (assignment-shaped candidate) | "opaque" (barrier)
    node_type: str


def _body_node(source: str, function: str):
    """Return (body_node, source_bytes) for the function's top-level compound
    block, or (None, source_bytes/None) if unavailable."""
    if not _ts.is_available():
        return None, None
    parser = _ts.get_parser()
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    fn = _ts.find_function_definition(tree.root_node, source_bytes, function)
    if fn is None:
        return None, source_bytes
    return fn.child_by_field_name("body"), source_bytes


def toplevel_siblings(source: str, function: str) -> Optional[list[SiblingStmt]]:
    body, source_bytes = _body_node(source, function)
    if body is None:
        return None
    sibs: list[SiblingStmt] = []
    for child in body.named_children:
        if child.type == "comment":
            continue
        text = _ts.node_text(source_bytes, child)
        kind = "opaque" if child.type in _OPAQUE_KINDS else "simple"
        # An opaque statement is a barrier: v1 never recurses into or moves its
        # contents, so represent multi-line constructs (if/for/while/...) by
        # their header line only. This keeps nested block bodies out of the
        # sibling model — they are NOT top-level movable units.
        if kind == "opaque":
            text = text.splitlines()[0] if text else text
        sibs.append(SiblingStmt(
            text=text,
            byte_range=(child.start_byte, child.end_byte),
            line_range=(child.start_point[0] + 1, child.end_point[0] + 1),
            kind=kind,
            node_type=child.type,
        ))
    return sibs
