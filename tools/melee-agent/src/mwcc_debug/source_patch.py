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

import difflib
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


def find_function_definitions(text: str) -> list[FunctionSpan]:
    """Locate top-level function definitions in `text`.

    This is intentionally conservative: it only considers identifier calls at
    top-level brace depth whose closing parameter list is immediately followed
    by a function body. It skips control-flow keywords so constructs such as
    `if (...) {` are not reported as definitions.
    """
    stripped = _strip_c_comments(text)
    brace_depth_at: list[int] = [0] * (len(stripped) + 1)
    depth = 0
    for idx, ch in enumerate(stripped):
        brace_depth_at[idx] = depth
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
    brace_depth_at[len(stripped)] = depth

    control_keywords = {
        "case",
        "do",
        "else",
        "for",
        "if",
        "return",
        "sizeof",
        "switch",
        "while",
    }
    spans: list[FunctionSpan] = []
    pattern = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

    for m in pattern.finditer(stripped):
        name = m.group(1)
        if name in control_keywords:
            continue
        if brace_depth_at[m.start()] != 0:
            continue

        paren_open = m.end() - 1
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

        k = paren_close + 1
        while k < len(stripped) and stripped[k] in " \t\n":
            k += 1
        if k >= len(stripped) or stripped[k] != "{":
            continue

        body_open = k
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

        sig_start = m.start()
        while sig_start > 0:
            prev = stripped[sig_start - 1]
            if prev == "\n" and sig_start - 2 >= 0 and stripped[sig_start - 2] == "\n":
                break
            if prev in ";}":
                break
            sig_start -= 1
        while sig_start < m.start() and stripped[sig_start] in " \t\n":
            sig_start += 1

        spans.append(FunctionSpan(
            name=name,
            sig_start=sig_start,
            body_open=body_open,
            body_close=body_close,
        ))

    return spans


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


# ----------------------------------------------------------------------------
# Declaration-block parsing + reordering (Tier 7b).
# ----------------------------------------------------------------------------

@dataclass
class DeclBlock:
    """The contiguous block of local declarations at the top of a function
    body. Lines are kept as raw strings (preserving their original
    formatting). Reordering shuffles whole lines.
    """

    # Byte offsets in the ORIGINAL function text (NOT the source file).
    # Use FunctionSpan offsets to translate to file offsets.
    start: int  # offset of first decl line (relative to function body_open)
    end: int  # offset just past the last decl line
    lines: list[str]  # one decl per element, includes the trailing newline


_DECL_LINE_RE = re.compile(
    r"""
    ^                       # start of line
    [ \t]*                  # leading indent
    (?:                     # optional storage / type qualifiers
        (?:static|extern|const|volatile|register|inline|auto)\s+
    )*
    [A-Za-z_]\w*            # type name
    (?:\s*\**)?             # optional pointer asterisks (attached to type)
    \s+
    \**                     # pointer asterisks attached to variable
    [A-Za-z_]\w*            # variable name
    (?:\s*\[[^\]]*\])*      # optional array dimensions
    (?:                     # optional initializer
        \s*=\s*[^;]+
    )?
    \s*;                    # terminator
    [ \t]*                  # trailing whitespace
    (?:\n|$)
    """,
    re.VERBOSE,
)


def find_decl_block(function_text: str) -> Optional[DeclBlock]:
    """Identify the contiguous block of local declarations at the start of
    the function body.

    `function_text` should be the body INCLUDING the opening `{` (e.g. from
    `text[span.body_open : span.full_end]`).

    Walks line-by-line starting just after the opening `{`. Includes lines
    matching the decl regex AND interspersed blank/comment-only lines (so
    decls separated by a blank line still count as one block). Stops at
    the first non-decl statement.
    """
    # Find the position right after the opening '{'
    open_idx = function_text.find("{")
    if open_idx < 0:
        return None
    pos = open_idx + 1
    # Skip a single newline immediately after '{' (typical formatting)
    if pos < len(function_text) and function_text[pos] == "\n":
        pos += 1

    start = pos
    lines: list[str] = []
    while pos < len(function_text):
        # Find the end of the current line
        nl = function_text.find("\n", pos)
        if nl < 0:
            line = function_text[pos:]
            line_end = len(function_text)
        else:
            line = function_text[pos : nl + 1]
            line_end = nl + 1

        stripped = line.strip()
        if stripped == "":
            # Blank line — keep walking but don't add to decl set
            pos = line_end
            continue
        if stripped.startswith("//") or stripped.startswith("/*"):
            # Comment line — keep walking but don't add
            pos = line_end
            continue
        if _DECL_LINE_RE.match(line):
            lines.append(line)
            pos = line_end
            continue
        # First non-decl line — end of decl block
        break

    if not lines:
        return None
    # `end` is the offset just past the LAST decl line we recorded.
    # (Trailing blank lines after the last decl aren't included.)
    last_line = lines[-1]
    last_line_idx = function_text.rfind(last_line, start, pos)
    if last_line_idx < 0:
        return None
    end = last_line_idx + len(last_line)
    return DeclBlock(start=start, end=end, lines=lines)


def reorder_decls_in_function(
    file_text: str,
    function: str,
    order: list[int],
) -> Optional[str]:
    """Return `file_text` with `function`'s declaration block reordered.

    `order` is a permutation of [0..N-1] where N is the number of decls.
    Returns None if function can't be found or the decl block is missing,
    or if `order` has the wrong length.
    """
    span = find_function(file_text, function)
    if span is None:
        return None
    fn_text = file_text[span.sig_start : span.full_end]
    # Translate body_open relative to fn_text
    body_open_rel = span.body_open - span.sig_start
    block = find_decl_block(fn_text[body_open_rel:])
    if block is None:
        return None
    if len(order) != len(block.lines):
        return None
    if sorted(order) != list(range(len(block.lines))):
        return None  # not a valid permutation

    # Build the new function text
    block_abs_start = body_open_rel + block.start
    block_abs_end = body_open_rel + block.end
    new_block = "".join(block.lines[i] for i in order)
    new_fn_text = (
        fn_text[:block_abs_start]
        + new_block
        + fn_text[block_abs_end:]
    )
    return file_text[: span.sig_start] + new_fn_text + file_text[span.full_end :]


def get_decl_names(file_text: str, function: str) -> Optional[list[str]]:
    """Extract just the variable names from each declaration line, in order.

    Useful for reporting which variable was promoted/demoted.
    """
    span = find_function(file_text, function)
    if span is None:
        return None
    fn_text = file_text[span.sig_start : span.full_end]
    body_open_rel = span.body_open - span.sig_start
    block = find_decl_block(fn_text[body_open_rel:])
    if block is None:
        return None
    names: list[str] = []
    for line in block.lines:
        # Find the LAST identifier before `;`, `[`, or `=`
        m = re.match(
            r"\s*(?:(?:static|extern|const|volatile|register|inline|auto)\s+)*"
            r"[A-Za-z_]\w*(?:\s*\**)?\s+\**([A-Za-z_]\w*)",
            line,
        )
        names.append(m.group(1) if m else "?")
    return names


def _line_bounds_for_range(file_text: str, byte_range: tuple[int, int]) -> tuple[int, int]:
    start, end = byte_range
    line_start = file_text.rfind("\n", 0, start) + 1
    line_end = file_text.find("\n", end)
    if line_end < 0:
        line_end = len(file_text)
    else:
        line_end += 1
    return line_start, line_end


def _decl_line_ranges_for_scope(
    file_text: str,
    function: str,
    scope_path: tuple[str, ...],
) -> list[tuple[str, int, int]]:
    from .ast_walker import walk_function

    decls = [
        decl for decl in walk_function(file_text, function, path=None)
        if decl.scope_path == scope_path
    ]
    out: list[tuple[str, int, int]] = []
    for decl in decls:
        start, end = _line_bounds_for_range(file_text, decl.byte_range)
        out.append((decl.name, start, end))
    return out


@dataclass(frozen=True)
class _DeclReorderItem:
    name: str
    text: str
    line_start: int
    line_end: int
    byte_range: tuple[int, int]
    initializer_text: str


@dataclass(frozen=True)
class DeclOrderCandidate:
    label: str
    order: list[int]


def _split_decl_items_for_scope(
    file_text: str,
    function: str,
    scope_path: tuple[str, ...],
) -> list[_DeclReorderItem]:
    from .ast_walker import walk_function

    decls = [
        decl for decl in walk_function(file_text, function, path=None)
        if decl.scope_path == scope_path
    ]
    if not decls:
        return []

    by_line: dict[tuple[int, int], list] = {}
    for decl in decls:
        by_line.setdefault(_line_bounds_for_range(file_text, decl.byte_range), []).append(decl)

    out: list[_DeclReorderItem] = []
    for line_bounds, line_decls in by_line.items():
        line_start, line_end = line_bounds
        line_text = file_text[line_start:line_end]
        ordered = sorted(line_decls, key=lambda decl: decl.byte_range[0])
        if len(ordered) == 1:
            decl = ordered[0]
            out.append(_DeclReorderItem(
                name=decl.name,
                text=line_text,
                line_start=line_start,
                line_end=line_end,
                byte_range=decl.byte_range,
                initializer_text=_initializer_text(file_text, decl.byte_range),
            ))
            continue

        first_rel = min(decl.byte_range[0] - line_start for decl in ordered)
        shared_prefix = line_text[:first_rel]
        newline = "\n" if line_text.endswith("\n") else ""
        for decl in ordered:
            decl_start, decl_end = decl.byte_range
            declarator = file_text[decl_start:decl_end].strip()
            out.append(_DeclReorderItem(
                name=decl.name,
                text=f"{shared_prefix}{declarator};{newline}",
                line_start=line_start,
                line_end=line_end,
                byte_range=decl.byte_range,
                initializer_text=_initializer_text(file_text, decl.byte_range),
            ))
    return out


def _initializer_text(file_text: str, byte_range: tuple[int, int]) -> str:
    text = file_text[byte_range[0]:byte_range[1]]
    stripped = _strip_c_comments(text)
    eq = stripped.find("=")
    if eq < 0:
        return ""
    return stripped[eq + 1:]


def _decl_type_key(item: _DeclReorderItem) -> str:
    text = item.text.strip()
    if text.endswith(";"):
        text = text[:-1].strip()
    match = re.search(rf"\b{re.escape(item.name)}\b", text)
    if match is None:
        return ""
    key = text[:match.start()].strip()
    return re.sub(r"\s+", " ", key)


def _is_scratch_like_decl(item: _DeclReorderItem) -> bool:
    if item.initializer_text:
        return False
    return bool(
        re.search(
            r"(?:result|ret|tmp|temp|scratch|work|value|val|accum|out)",
            item.name,
            re.IGNORECASE,
        )
    )


def build_decl_order_candidates_for_scope(
    file_text: str,
    function: str,
    scope_path: tuple[str, ...],
    strategy: str = "promote",
    *,
    pair_limit: int = 4,
) -> list[DeclOrderCandidate]:
    """Build bounded declaration-order candidate permutations for a scope."""
    items = _split_decl_items_for_scope(file_text, function, scope_path)
    n = len(items)
    if n < 2:
        return []

    candidates: list[DeclOrderCandidate] = []
    seen_orders: set[tuple[int, ...]] = set()

    def add(label: str, order: list[int]) -> None:
        if order == list(range(n)):
            return
        order_key = tuple(order)
        if order_key in seen_orders:
            return
        seen_orders.add(order_key)
        candidates.append(DeclOrderCandidate(label, order))

    def promote_indices(indices: list[int]) -> list[int]:
        selected = set(indices)
        return indices + [idx for idx in range(n) if idx not in selected]

    def add_group_and_pair_promotions() -> None:
        by_type: dict[str, list[int]] = {}
        for idx, item in enumerate(items):
            if item.initializer_text:
                continue
            key = _decl_type_key(item)
            if not key:
                continue
            by_type.setdefault(key, []).append(idx)
        for type_key, indices in by_type.items():
            if len(indices) < 2:
                continue
            names = "+".join(items[idx].name for idx in indices)
            add(
                f"promote-group {type_key} {names}",
                promote_indices(indices),
            )

        eligible = [
            idx for idx, item in enumerate(items)
            if idx != 0 and not item.initializer_text
        ]
        eligible.sort(
            key=lambda idx: (
                0 if _is_scratch_like_decl(items[idx]) else 1,
                idx,
            )
        )
        pair_indices = sorted(eligible[:max(0, pair_limit)])
        for left_pos, left in enumerate(pair_indices):
            for right in pair_indices[left_pos + 1:]:
                names = f"{items[left].name}+{items[right].name}"
                add(
                    f"promote-pair {names}",
                    promote_indices([left, right]),
                )

    if strategy in ("promote", "all"):
        for k in range(1, n):
            add(
                f"promote {items[k].name}",
                [k] + [i for i in range(n) if i != k],
            )
        if strategy == "promote":
            add_group_and_pair_promotions()

    if strategy in ("demote", "all"):
        for k in range(n - 1):
            add(
                f"demote {items[k].name}",
                [i for i in range(n) if i != k] + [k],
            )
    if strategy in ("swap", "all"):
        for k in range(n - 1):
            order = list(range(n))
            order[k], order[k + 1] = order[k + 1], order[k]
            add(
                f"swap {items[k].name} <-> {items[k + 1].name}",
                order,
            )
    if strategy == "all":
        add_group_and_pair_promotions()
    if strategy == "full":
        from itertools import permutations

        if n > 7:
            return []
        for order in permutations(range(n)):
            add(f"order {list(order)}", list(order))
    return candidates


def _decl_order_initializer_dependency_blocker(
    items: list[_DeclReorderItem],
    order: list[int],
) -> str:
    original_index = {item.name: idx for idx, item in enumerate(items)}
    new_index = {items[idx].name: pos for pos, idx in enumerate(order)}
    for idx in order:
        item = items[idx]
        if not item.initializer_text:
            continue
        for name, original_pos in original_index.items():
            if original_pos >= idx:
                continue
            if re.search(rf"\b{re.escape(name)}\b", item.initializer_text):
                if new_index[name] > new_index[item.name]:
                    return f"{item.name} depends on {name}"
    return ""


def explain_decl_reorder_skip(
    file_text: str,
    function: str,
    scope_path: tuple[str, ...],
    order: list[int],
) -> str:
    """Return a human-readable reason a declaration reorder is unsafe."""
    items = _split_decl_items_for_scope(file_text, function, scope_path)
    if not items:
        return "scope has no declarations"
    if len(order) != len(items):
        return "order length does not match declaration count"
    if sorted(order) != list(range(len(items))):
        return "order is not a valid permutation"
    return _decl_order_initializer_dependency_blocker(items, order)


def get_decl_names_by_scope(
    file_text: str,
    function: str,
) -> dict[tuple[str, ...], list[str]]:
    """Return a mapping from scope_path to list of declaration names.

    Each scope_path is a tuple: ``(function,)`` for the top-level function
    scope, or ``(function, "block@l{line}c{col}", ...)`` for nested blocks.
    """
    from .ast_walker import walk_function

    out: dict[tuple[str, ...], list[str]] = {}
    for decl in walk_function(file_text, function, path=None):
        out.setdefault(decl.scope_path, []).append(decl.name)
    return out


def reorder_decls_in_function_scope(
    file_text: str,
    function: str,
    scope_path: tuple[str, ...],
    order: list[int],
) -> Optional[str]:
    """Reorder declarations in a specific scope (top-level or nested block).

    Like ``reorder_decls_in_function`` but targets ``scope_path`` rather than
    always the function-top scope. Returns the patched source text, or None if
    the scope has no declarations or ``order`` is not a valid permutation.
    """
    decl_ranges = _decl_line_ranges_for_scope(file_text, function, scope_path)
    if not decl_ranges:
        return None
    if len(order) != len(decl_ranges):
        return None
    if sorted(order) != list(range(len(decl_ranges))):
        return None
    items = _split_decl_items_for_scope(file_text, function, scope_path)
    if len(items) != len(decl_ranges):
        return None
    if _decl_order_initializer_dependency_blocker(items, order):
        return None
    block_start = min(item.line_start for item in items)
    block_end = max(item.line_end for item in items)
    reordered = "".join(items[i].text for i in order)
    return file_text[:block_start] + reordered + file_text[block_end:]


def merge3_function(
    base: str,
    candidate: str,
    current: str,
) -> tuple[str, list[tuple[int, str]]]:
    """3-way merge of a single function body (as extracted strings).

    Treats `base` as the common ancestor (permuter's base.c function text),
    `candidate` as the permuter's mutated version (theirs), and `current` as
    the real source's current version (ours — may contain manual edits made
    after the permuter baseline was imported).

    Strategy (line-level):
    - Lines unchanged in candidate vs base AND unchanged in current vs base:
      keep current (no-op).
    - Lines changed in candidate but unchanged in current: take candidate.
    - Lines changed in current but unchanged in candidate: keep current.
    - Lines changed in BOTH candidate and current: CONFLICT. Conflicts are
      recorded as (approx_line_number, conflict_description) pairs.

    When a conflict is detected, the candidate version is used for the
    conflicting region (caller decides whether to abort or proceed).

    Returns (merged_text, conflicts) where conflicts is empty on clean merge.
    """
    import difflib

    base_lines = base.splitlines(keepends=True)
    cand_lines = candidate.splitlines(keepends=True)
    curr_lines = current.splitlines(keepends=True)

    # Compute opcodes for base→candidate and base→current
    sm_bc = difflib.SequenceMatcher(None, base_lines, cand_lines, autojunk=False)
    sm_bx = difflib.SequenceMatcher(None, base_lines, curr_lines, autojunk=False)

    # Build a set of base-line indices that are modified by each side.
    # "modified" = deleted or replaced (not just inserted after).
    def _modified_base_indices(opcodes, a_len: int) -> set[int]:
        modified: set[int] = set()
        for tag, i1, i2, j1, j2 in opcodes:
            if tag in ("replace", "delete"):
                modified.update(range(i1, i2))
        return modified

    cand_opcodes = sm_bc.get_opcodes()
    curr_opcodes = sm_bx.get_opcodes()
    cand_modified = _modified_base_indices(cand_opcodes, len(base_lines))
    curr_modified = _modified_base_indices(curr_opcodes, len(base_lines))

    # Conflict = both sides modified the same base line(s).
    conflict_base_indices = cand_modified & curr_modified

    conflicts: list[tuple[int, str]] = []
    if conflict_base_indices:
        for idx in sorted(conflict_base_indices):
            base_line = base_lines[idx].rstrip("\n")
            conflicts.append((
                idx + 1,
                f"base: {base_line!r}",
            ))

    # Build merged result: start from current, then apply candidate's changes
    # for lines that candidate touched but current didn't.
    # The simplest correct merge: use difflib.Differ on base→candidate hunks
    # and apply non-conflicting insertions/replacements onto current.
    #
    # Implementation: walk base→candidate opcodes. For each hunk:
    # - "equal": leave current unchanged (use current's corresponding lines).
    # - "replace"/"delete"/"insert": if NOT a conflict, apply the candidate
    #   change; if conflict, apply candidate (caller-decided).
    #
    # To build the output we need a mapping from base indices to current
    # indices (base→current opcodes give us that).
    # We'll build a "current-indexed" output by walking both opcode lists.

    # Simpler approach: rebuild from candidate, but for non-conflicting regions
    # that current changed (vs base), prefer current.
    # Walk base→candidate and base→current simultaneously.

    merged: list[str] = []
    # Map base indices to their current counterparts
    base_to_curr: dict[int, list[str]] = {}  # base idx → replacement lines in current
    base_deleted_by_curr: set[int] = set()

    for tag, i1, i2, j1, j2 in curr_opcodes:
        if tag == "equal":
            for k in range(i2 - i1):
                base_to_curr[i1 + k] = [curr_lines[j1 + k]]
        elif tag in ("replace",):
            # Map the whole replaced range
            curr_chunk = curr_lines[j1:j2]
            for k in range(i2 - i1):
                base_to_curr[i1 + k] = curr_chunk if k == 0 else []
        elif tag == "delete":
            for k in range(i2 - i1):
                base_deleted_by_curr.add(i1 + k)
                base_to_curr[i1 + k] = []
        elif tag == "insert":
            # Insertion before base[i1]: attach to the previous base line
            # We'll handle insertions by keying them to the preceding base idx.
            # For simplicity, attach inserted current lines to the next base idx.
            key = i1  # insert before base[i1]
            if key not in base_to_curr:
                base_to_curr[key] = []
            base_to_curr[key] = list(curr_lines[j1:j2]) + base_to_curr.get(key, [])

    pending_curr_inserts: dict[int, list[str]] = {}
    for tag, i1, i2, j1, j2 in curr_opcodes:
        if tag == "insert":
            pending_curr_inserts.setdefault(i1, []).extend(curr_lines[j1:j2])

    # Now walk candidate opcodes to build merged output
    curr_pos = 0  # position in curr_lines (for equal regions)
    # We'll re-index by rebuilding from scratch using base as anchor.
    # Emit lines for each base segment per candidate opcode.

    # Rebuild curr lookup: for each base index, what are the curr lines?
    # For "insert" in curr (before base[i1]), attach to i1 as prefix.
    curr_prefix: dict[int, list[str]] = {}  # extra curr lines inserted BEFORE base[i]
    for tag, i1, i2, j1, j2 in curr_opcodes:
        if tag == "insert":
            curr_prefix.setdefault(i1, []).extend(curr_lines[j1:j2])

    # Rebuild: for each base line index, what is the current version?
    # base_to_curr[i] = the lines that replaced base[i] in current (may be empty if deleted)
    base_to_curr2: dict[int, list[str]] = {}
    for tag, i1, i2, j1, j2 in curr_opcodes:
        if tag == "equal":
            for k in range(i2 - i1):
                base_to_curr2[i1 + k] = [curr_lines[j1 + k]]
        elif tag == "replace":
            # Split the replacement across the base indices evenly
            curr_chunk = curr_lines[j1:j2]
            for k in range(i2 - i1):
                base_to_curr2[i1 + k] = curr_chunk if k == 0 else []
        elif tag == "delete":
            for k in range(i2 - i1):
                base_to_curr2[i1 + k] = []
        # insert handled via curr_prefix

    # Walk candidate opcodes, building merged output
    for tag, i1, i2, j1, j2 in cand_opcodes:
        if tag == "equal":
            # Candidate kept these base lines: emit current's version
            for k in range(i2 - i1):
                base_idx = i1 + k
                merged.extend(curr_prefix.get(base_idx, []))
                merged.extend(base_to_curr2.get(base_idx, [base_lines[base_idx]]))
        elif tag in ("replace", "delete"):
            cand_chunk = cand_lines[j1:j2]
            # For each base line in this range: is it a conflict?
            for k in range(i2 - i1):
                base_idx = i1 + k
                merged.extend(curr_prefix.get(base_idx, []))
                if base_idx in conflict_base_indices:
                    # Conflict: take candidate version on first base idx, skip rest
                    if k == 0:
                        merged.extend(cand_chunk)
                else:
                    # Non-conflict: take candidate (it changed, current didn't)
                    if k == 0:
                        merged.extend(cand_chunk)
                    # else: cand replaced multiple base lines, emit chunk only once
        elif tag == "insert":
            # Candidate inserted lines before base[i1] — always take them
            merged.extend(cand_lines[j1:j2])

    # Emit any trailing curr_prefix for base lines beyond the last opcode
    for base_idx in sorted(curr_prefix):
        if base_idx >= len(base_lines):
            merged.extend(curr_prefix[base_idx])

    return "".join(merged), conflicts
