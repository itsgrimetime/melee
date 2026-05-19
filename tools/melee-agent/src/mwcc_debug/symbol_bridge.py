"""Source variable ↔ MWCC virtual register bridge.

Uses the same brace-tokenizer pattern as `source_patch.py` (proven on
real Melee TUs full of HSD_ASSERT, PAD_STACK, statement-expression
macros). Does NOT use pycparser. The trade-off: v1 only recognizes
simple top-of-body local declarations; nested-block decls are skipped
(documented limitation).

The bridge's accuracy is "good enough to bias seed selection," not
"exact." Callers see a `confidence` label and can invoke the
self-verification step in the orchestrator when committing to a seed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class LocalDecl:
    """One local variable declaration extracted from a function body."""
    name: str          # variable name
    type_str: str      # canonical type as written in source (e.g., "HSD_JObj*")
    decl_index: int    # 0-indexed position in source order


# Matches a single declaration's leading pattern:
#   <type-tokens> <name> [= ...] ;
# where <type-tokens> is one or more identifier/pointer/qualifier
# tokens, followed by a single identifier that's the variable name.
#
# We tokenize statement-by-statement (splitting on top-level `;`),
# then run this on each statement-leading text to recognize decls.
#
# The type+name boundary requires a real separator (`*` or whitespace)
# so we don't greedily consume the first character of the variable
# name into the trailing type-token (e.g. `MnEventData* data` must
# split as type=`MnEventData*`, name=`data`).
_DECL_RE = re.compile(
    r"""
    ^\s*
    (?P<type>
        (?:const\s+|volatile\s+|static\s+)*    # qualifiers (rare)
        [A-Za-z_][A-Za-z_0-9]*                 # base type identifier
        (?:\s*\*+\s*|\s+[A-Za-z_][A-Za-z_0-9]*)*  # ptrs OR space-separated tokens
        (?:\s*\*+\s*|\s+)                      # REQUIRED separator before name
    )
    (?P<name>[A-Za-z_][A-Za-z_0-9]*)
    \s*
    (?:=|;|$)                                  # `=`, `;`, or end ends decl head
    """,
    re.VERBOSE,
)

# C keywords that LOOK like type identifiers but introduce control flow
# or other statements. If the first token of a statement is one of these,
# the statement is NOT a declaration.
_NON_DECL_LEADERS = {
    "if", "else", "for", "while", "do", "switch", "case", "default",
    "return", "break", "continue", "goto",
}


def _strip_strings_and_comments(text: str) -> str:
    """Replace string-literal and comment content with same-length
    whitespace so brace/semicolon tokenization isn't fooled by them.
    Newlines preserved so line numbers stay aligned.
    """
    out = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == '"' or c == "'":
            quote = c
            out.append(c)
            i += 1
            while i < len(text) and text[i] != quote:
                if text[i] == "\\" and i + 1 < len(text):
                    out.append(" ")  # don't expose `\\` quirks
                    out.append(" ")
                    i += 2
                    continue
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < len(text):
                out.append(text[i])
                i += 1
            continue
        if c == "/" and i + 1 < len(text) and text[i + 1] == "/":
            while i < len(text) and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < len(text) and text[i + 1] == "*":
            while i + 1 < len(text) and not (
                text[i] == "*" and text[i + 1] == "/"
            ):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i + 1 < len(text):
                out.append(" ")
                out.append(" ")
                i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _top_level_statements(body: str) -> list[str]:
    """Split a function body (the `{...}` block) into top-level statements
    by tracking brace + paren depth. Strings/comments stripped first.
    Returns each statement WITHOUT the trailing semicolon, in source
    order. Nested-block contents are returned as a single statement-
    sized chunk (we DON'T descend into them in v1).
    """
    # Trim outer braces if present
    stripped = _strip_strings_and_comments(body).strip()
    if stripped.startswith("{"):
        stripped = stripped[1:]
    if stripped.endswith("}"):
        stripped = stripped[:-1]

    stmts: list[str] = []
    buf: list[str] = []
    depth_brace = 0
    depth_paren = 0
    for c in stripped:
        # Track depth changes
        if c == "{":
            depth_brace += 1
            buf.append(c)
            continue
        if c == "}":
            depth_brace -= 1
            buf.append(c)
            # Closing a top-level nested block ends the surrounding
            # statement (e.g. `if (...) { ... } int z;` should split
            # into `if (...) { ... }` and `int z`). Otherwise the trailing
            # decl would never get its own statement chunk.
            if depth_brace == 0 and depth_paren == 0:
                stmts.append("".join(buf).strip())
                buf = []
            continue
        if c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        if c == ";" and depth_brace == 0 and depth_paren == 0:
            stmts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(c)
    remainder = "".join(buf).strip()
    if remainder:
        stmts.append(remainder)
    return stmts


def walk_local_decls(body: str) -> list[LocalDecl]:
    """Walk a function body, return one LocalDecl per top-level local
    variable declaration in source order.

    `body` may include or omit the outer braces.
    """
    out: list[LocalDecl] = []
    idx = 0
    for stmt in _top_level_statements(body):
        # Skip control-flow leaders
        first_token_m = re.match(r"^\s*([A-Za-z_][A-Za-z_0-9]*)", stmt)
        if first_token_m and first_token_m.group(1) in _NON_DECL_LEADERS:
            continue
        m = _DECL_RE.match(stmt)
        if not m:
            continue
        # Compact whitespace in the type
        type_str = re.sub(r"\s+", " ", m.group("type")).strip()
        # Move trailing pointer asterisks adjacent to type (canonical
        # "HSD_JObj*" rather than "HSD_JObj *")
        type_str = re.sub(r"\s*\*\s*", "*", type_str)
        out.append(LocalDecl(
            name=m.group("name"),
            type_str=type_str,
            decl_index=idx,
        ))
        idx += 1
    return out
