"""Source-state fingerprinting for matched-function attempts.

Used by tools/checkdiff.py to detect when an agent has applied the same
source change to the same function on a previous attempt, and to
auto-record attempt outcomes in the ledger.

Public API:
    extract_function_body(source_path, function_name) -> str | None
    compute_fingerprint(function_body) -> (raw, normalized)
    fingerprint_for(source_path, function_name) -> Fingerprint | None
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.common import tree_sitter_c as _ts
from src.common.tree_sitter_c import find_function_definition, node_text


@dataclass(frozen=True)
class Fingerprint:
    raw: str
    normalized: str
    body: str  # the extracted body text (useful for debugging / tests)


def _trim_body(body: str) -> str:
    """Common normalization applied to BOTH extraction paths so they
    produce identical raw hashes for identical inputs.

    1. Strip a leading/trailing newline (cosmetic, tree-sitter often
       includes them inside the `compound_statement` extent)
    2. Do NOT collapse internal whitespace — that's the job of the
       normalized fingerprint.
    """
    return body.strip("\n")


def _extract_via_tree_sitter(source_bytes: bytes, function_name: str) -> Optional[str]:
    """Use tree-sitter-c to locate the function and return its body text."""
    if not _ts.is_available():
        return None
    parser = _ts.get_parser()
    tree = parser.parse(source_bytes)
    fn_node = find_function_definition(tree.root_node, source_bytes, function_name)
    if fn_node is None:
        return None

    body_node = fn_node.child_by_field_name("body")
    if body_node is None or body_node.type != "compound_statement":
        return None

    # Slice INSIDE the outermost braces by byte offset. The
    # compound_statement extent runs from '{' to '}' inclusive, so we
    # skip the first and last byte. Falls back to None on a degenerate
    # zero-byte body (which shouldn't happen but defends against
    # PARSE_SKIP_FUNCTION_BODIES-style anomalies).
    if body_node.end_byte - body_node.start_byte < 2:
        return None
    body_bytes = source_bytes[body_node.start_byte + 1:body_node.end_byte - 1]
    return _trim_body(body_bytes.decode("utf-8", errors="replace"))


# Signature head: <line start> + non-greedy stuff + name + '(' .
# We require the function name at a word boundary preceded by a return
# type or whitespace (anchored to line start to avoid matching the name
# inside a string literal or another function's body).
_SIG_HEAD = re.compile(
    rf"^[ \t]*(?:[\w\*\s]+?[\s\*])?{{NAME}}\s*\(",
    re.MULTILINE,
)


# C keywords that would otherwise satisfy the _SIG_HEAD pattern when they
# appear at the start of a line (e.g. `    for (...)`). The regex's
# leading `(?:[\w\s\*]+?[\s\*])?` group is optional, so a bare keyword at
# start-of-line plus `(` would be a false positive without this guard.
_C_KEYWORDS = frozenset({
    "if", "else", "for", "while", "do", "switch", "case", "default",
    "return", "break", "continue", "goto", "sizeof", "typedef",
})


def _extract_via_regex(source_text: str, function_name: str) -> Optional[str]:
    """Cheap fallback when tree-sitter isn't available.

    Matches the signature line `<return type> function_name (` at start
    of line, parenthesis-balances to the closing paren, then
    brace-balances to find the matching closing brace. Returns None on
    any ambiguity — a false negative is fine, but a false positive
    (wrong body) would silently corrupt the ledger.
    """
    if function_name in _C_KEYWORDS:
        return None
    pattern_src = _SIG_HEAD.pattern.replace("{NAME}", re.escape(function_name))
    pattern = re.compile(pattern_src, re.MULTILINE)
    match = pattern.search(source_text)
    if match is None:
        return None
    # Balance the parameter parens.
    paren_start = match.end() - 1  # position of the '('
    depth = 1
    i = paren_start + 1
    while i < len(source_text) and depth > 0:
        ch = source_text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    if depth != 0:
        return None
    # Skip whitespace, expect '{'.
    while i < len(source_text) and source_text[i].isspace():
        i += 1
    if i >= len(source_text) or source_text[i] != "{":
        return None
    brace_start = i + 1
    # Conservative fallback: if the body contains any string/char/comment
    # delimiter, we can't reliably brace-balance without a proper parser.
    # Return None (caller records without fingerprint) rather than risk a
    # wrong body.
    depth = 1
    i = brace_start
    while i < len(source_text) and depth > 0:
        ch = source_text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    if depth != 0:
        return None
    body_text = source_text[brace_start:i - 1]
    if any(d in body_text for d in ('"', "'", "/*", "//")):
        return None
    return _trim_body(body_text)


def extract_function_body(source_path: Path, function_name: str) -> Optional[str]:
    """Return the source text inside function_name's outermost braces.

    Tries tree-sitter first; falls back to a brace-balancing regex if
    tree-sitter is unavailable or fails. Returns None on total failure.

    Both extraction paths apply the same `_trim_body` normalization, so
    a successful tree-sitter run and a successful regex run on the same
    input produce identical body text (and thus identical raw
    fingerprints).
    """
    try:
        source_bytes = Path(source_path).read_bytes()
    except (OSError, FileNotFoundError):
        return None

    body = _extract_via_tree_sitter(source_bytes, function_name)
    if body is not None:
        return body

    try:
        source_text = source_bytes.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return None
    return _extract_via_regex(source_text, function_name)


def compute_fingerprint(function_body: str) -> tuple[str, str]:
    """Return (raw_fingerprint, normalized_fingerprint) — 12-char hex SHA1
    prefixes. raw = sha1 of body with comments stripped; normalized = sha1
    of word-boundary-aware whitespace-normalized comment-stripped body.

    The normalized hash treats two bodies that differ only in whitespace
    around operators and punctuation as the same (e.g. `int y=x+1;` and
    `int y = x + 1;`), but preserves whitespace between adjacent word
    characters so `int x` and `intx` stay distinct.
    """
    # Strip block comments first, then line comments
    no_block = re.sub(r"/\*.*?\*/", "", function_body, flags=re.DOTALL)
    no_comments = re.sub(r"//[^\n]*", "", no_block)
    raw = hashlib.sha1(no_comments.encode("utf-8", errors="replace")).hexdigest()[:12]

    # Strip whitespace adjacent to non-word, non-whitespace characters
    # (operators, punctuation) — but NOT whitespace bordered by other
    # whitespace, which would otherwise consume the entire run and merge
    # word tokens. Then collapse remaining word-bordered whitespace to a
    # single space. This makes "int y=x+1;" and "int y = x + 1;" hash
    # identically while keeping "int y" and "inty" distinct, and also
    # treats "static const\n    int FOO;" the same as
    # "static const int FOO;".
    stripped = re.sub(r"\s+(?=[^\w\s])|(?<=[^\w\s])\s+", "", no_comments)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    normalized = hashlib.sha1(stripped.encode("utf-8", errors="replace")).hexdigest()[:12]

    return raw, normalized


def fingerprint_for(source_path: Path, function_name: str) -> Optional[Fingerprint]:
    """Extract + compute. Returns None on extraction failure."""
    body = extract_function_body(source_path, function_name)
    if body is None:
        return None
    raw, norm = compute_fingerprint(body)
    return Fingerprint(raw=raw, normalized=norm, body=body)
