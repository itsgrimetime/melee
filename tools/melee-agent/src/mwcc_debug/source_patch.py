"""Function-body replacement for transferring permuter candidates to real source.

The permuter preprocesses base.c (header merging, macro expansion) before
mutating, so its candidate `source.c` files don't textually overlap the
real source tree. To verify a candidate against the real build, we need
to extract just the changed FUNCTION and patch it into the real source
file.

This module provides that lift. Limitations:
- Assumes well-formed C with matched braces (no comments containing
  unmatched braces, no string literals containing unmatched braces inside
  comments, etc.). Practically robust enough for decompiled source.
- Replaces ONE function at a time. If permuter mutated a static helper,
  caller must invoke this once per changed function.
- Doesn't touch declarations outside the function body. If permuter
  added/removed a global, that's not handled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FunctionSpan:
    """Byte offsets bounding a function definition in a source file."""

    name: str
    sig_start: int  # first byte of return type
    body_open: int  # offset of '{'
    body_close: int  # offset of matching '}'

    @property
    def full_end(self) -> int:
        """Byte offset just past the closing '}'."""
        return self.body_close + 1


def _strip_c_comments(text: str) -> str:
    """Replace C/C++ comments AND string/char literal contents with spaces.

    Preserves byte offsets (newlines preserved, every other replaced char
    becomes ' '), which lets us reason about brace/paren positions in the
    original text from positions in the stripped version. String/char
    literal contents are also blanked so an in-string `{` doesn't confuse
    the brace counter — the surrounding quotes are kept as-is so we can
    still identify the string boundaries if needed.
    """
    out = list(text)
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"' or ch == "'":
            quote = ch
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\" and i + 1 < n:
                    if text[i] != "\n":
                        out[i] = " "
                    if text[i + 1] != "\n":
                        out[i + 1] = " "
                    i += 2
                else:
                    if text[i] != "\n":
                        out[i] = " "
                    i += 1
            if i < n:
                # the closing quote — leave as-is
                i += 1
            continue
        if ch == "/" and i + 1 < n:
            if text[i + 1] == "/":
                # // comment — kill to end of line
                while i < n and text[i] != "\n":
                    out[i] = " "
                    i += 1
                continue
            if text[i + 1] == "*":
                # /* */ comment
                start = i
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                end = min(n, i + 2)
                for k in range(start, end):
                    if text[k] != "\n":  # preserve newlines for line-number alignment
                        out[k] = " "
                i = end
                continue
        i += 1
    return "".join(out)


def find_function(text: str, name: str) -> Optional[FunctionSpan]:
    """Locate the function definition for `name` in `text`.

    Returns FunctionSpan or None if not found / ambiguous.

    Algorithm: regex-find `<name>(` candidates, then look BACKWARD for the
    return type (first non-whitespace before the name that's not a
    function-keyword like `static`), and FORWARD for the matching brace.
    Skips function PROTOTYPES (those end with `;` before `{`).
    """
    stripped = _strip_c_comments(text)

    # Match identifier-boundary occurrences of the name followed by '('.
    # The preceding character must NOT be an identifier char (otherwise
    # it's a substring like `mnVibration_802486` inside `mnVibration_80248644`).
    pattern = re.compile(r"\b" + re.escape(name) + r"\s*\(")

    for m in pattern.finditer(stripped):
        paren_open = m.end() - 1
        # Find the matching ')'
        depth = 1
        j = paren_open + 1
        while j < len(stripped) and depth > 0:
            c = stripped[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
        if depth != 0:
            continue
        paren_close = j - 1

        # After ')', skip whitespace + attribute keywords. If we hit ';',
        # it's a prototype, not a definition.
        k = paren_close + 1
        while k < len(stripped) and stripped[k] in " \t\n":
            k += 1
        if k >= len(stripped):
            continue
        if stripped[k] == ";":
            continue  # prototype
        if stripped[k] != "{":
            # Could be e.g. K&R-style declarators. Skip for now.
            continue

        body_open = k

        # Find the matching closing brace
        depth = 1
        j = body_open + 1
        while j < len(stripped) and depth > 0:
            c = stripped[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            j += 1
        if depth != 0:
            continue
        body_close = j - 1

        # Find signature start: walk backward from the name to the start of
        # the return type. A signature starts after a ';', '}', or beginning
        # of file. Skip backward over whitespace and qualifiers.
        sig_start = m.start()
        while sig_start > 0:
            prev = stripped[sig_start - 1]
            if prev == "\n" and sig_start - 2 >= 0 and stripped[sig_start - 2] == "\n":
                # Two consecutive newlines — boundary
                break
            if prev in ";}":
                break
            sig_start -= 1
        # Trim leading whitespace
        while sig_start < m.start() and stripped[sig_start] in " \t\n":
            sig_start += 1

        return FunctionSpan(
            name=name,
            sig_start=sig_start,
            body_open=body_open,
            body_close=body_close,
        )

    return None


def extract_function(text: str, name: str) -> Optional[str]:
    """Return the full source of function `name` (signature + body) from `text`."""
    span = find_function(text, name)
    if span is None:
        return None
    return text[span.sig_start : span.full_end]


def replace_function(text: str, name: str, replacement: str) -> Optional[str]:
    """Replace function `name` in `text` with `replacement`.

    Returns the patched text, or None if the function couldn't be located.
    `replacement` should be the FULL function (signature + body).
    """
    span = find_function(text, name)
    if span is None:
        return None
    return text[: span.sig_start] + replacement + text[span.full_end :]


def transfer_candidate(
    candidate_text: str,
    target_path: Path,
    function: str,
) -> Optional[str]:
    """Extract `function` from `candidate_text` and write it into
    `target_path`, replacing the existing definition.

    Returns the original (pre-patch) text of target_path so the caller can
    roll back via `target_path.write_text(orig)`. Returns None if either
    side doesn't contain the function.
    """
    candidate_fn = extract_function(candidate_text, function)
    if candidate_fn is None:
        return None
    orig = target_path.read_text()
    patched = replace_function(orig, function, candidate_fn)
    if patched is None:
        return None
    target_path.write_text(patched)
    return orig
