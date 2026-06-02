"""Anchor resolver for the select-order directed search layer.

An Anchor locates a specific edit site in C source that a mutator can
transform.  The diagnosis resolver tries three levers in priority order:

  1. reorder_local_decls  — swap two adjacent local declarations
  2. change_counter_width — change s16↔s32 in a single decl line
  3. split_decl_init      — split "T v = E;" into "T v;\\nv = E;"

The ``payload`` dict is the exact contract consumed by ``apply_mutator`` in
``mutators.py``.  Every cited line in the payload is verified to exist in
``source_text`` before an Anchor is returned.

``iter_source_shape_anchors`` separately discovers conservative
control-flow/scope edit sites for directed search:

  * nested ``else { if (...)`` flatten/unflatten forms
  * brace-only branch scopes that can be added or removed
  * local declaration lifetime widening/narrowing around branch scopes
  * inner loop-counter declarations that can reuse an outer counter
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class Anchor:
    """A frozen, located edit site in C source.

    Attributes
    ----------
    mutator_key:
        A registered directed mutator key such as ``"reorder_local_decls"``
        or ``"flatten_nested_if"``.
    span:
        ``(start, end)`` character offsets in the source string.  For
        ``reorder_local_decls`` the span covers both lines (first through end
        of second line's newline).  For single-line mutators it covers just
        that line.
    payload:
        Exact dict consumed by ``apply_mutator``.  See module docstring for
        per-key contracts.
    """

    mutator_key: str
    span: tuple
    payload: dict


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_LOCAL_DECL_RE = re.compile(
    r"^(?P<indent>[ \t]+)"          # leading whitespace (required — not a param)
    r"(?P<type>[A-Za-z_][\w* ]*?)"  # type (permissive)
    r"[ \t]+"
    r"(?P<var>[A-Za-z_]\w*)"        # variable name
    r"(?P<rest>[^;]*);",            # optional initializer + semicolon
    re.MULTILINE,
)

_COUNTER_WIDTH_RE = re.compile(r"\b(s16|s32)\b")

_INIT_RE = re.compile(
    r"^(?P<indent>[ \t]+)"
    r"(?P<type>[A-Za-z_][\w* ]*?)"
    r"[ \t]+"
    r"(?P<var>[A-Za-z_]\w*)"
    r"[ \t]*=[ \t]*"
    r"(?P<init>[^;]+)"
    r";",
    re.MULTILINE,
)


def _find_decl_line(var_name: str, source_text: str) -> Optional[str]:
    """Return the exact text of the first local declaration line for *var_name*.

    Returns the line WITHOUT a trailing newline, or ``None`` if not found.
    """
    for m in _LOCAL_DECL_RE.finditer(source_text):
        if m.group("var") == var_name:
            # Extract the full line (from start of indent through semicolon)
            line_start = source_text.rfind("\n", 0, m.start()) + 1
            line_end = source_text.find("\n", m.end())
            if line_end == -1:
                line_end = len(source_text)
            return source_text[line_start:line_end]
    return None


def _find_adjacent_decl_line(decl_line: str, source_text: str) -> Optional[str]:
    """Return the exact text of the line immediately following *decl_line*.

    Returns the adjacent line WITHOUT trailing newline, or ``None`` if the
    following line is not a local variable declaration.
    """
    idx = source_text.find(decl_line)
    if idx == -1:
        return None
    # Jump past this line's newline
    after = idx + len(decl_line)
    if after >= len(source_text):
        return None
    if source_text[after] == "\n":
        after += 1
    line_end = source_text.find("\n", after)
    if line_end == -1:
        line_end = len(source_text)
    next_line = source_text[after:line_end]
    # Check it looks like a local decl (has leading whitespace + semicolon)
    stripped = next_line.strip()
    if stripped.endswith(";") and next_line and next_line[0] in (" ", "\t"):
        return next_line
    return None


def _span_for_two_lines(first_line: str, second_line: str, source_text: str) -> tuple:
    """Return (start, end) char span covering both adjacent lines including newlines."""
    idx = source_text.find(first_line)
    if idx == -1:
        return (0, 0)
    start = source_text.rfind("\n", 0, idx) + 1
    # end = after second line's newline
    second_start = source_text.find(second_line, idx + len(first_line))
    if second_start == -1:
        return (0, 0)
    end = source_text.find("\n", second_start + len(second_line))
    if end == -1:
        end = len(source_text)
    else:
        end += 1  # include the newline
    return (start, end)


def _span_for_line(line: str, source_text: str) -> tuple:
    """Return (start, end) covering *line* including its trailing newline."""
    idx = source_text.find(line)
    if idx == -1:
        return (0, 0)
    start = source_text.rfind("\n", 0, idx) + 1
    end = source_text.find("\n", idx + len(line))
    if end == -1:
        end = len(source_text)
    else:
        end += 1
    return (start, end)


def _line_records(source_text: str) -> list[tuple[int, int, str]]:
    records: list[tuple[int, int, str]] = []
    pos = 0
    for raw in source_text.splitlines(keepends=True):
        line = raw[:-1] if raw.endswith("\n") else raw
        records.append((pos, pos + len(line), line))
        pos += len(raw)
    return records


def _block_text(
    source_text: str,
    records: list[tuple[int, int, str]],
    start_idx: int,
    end_idx: int,
) -> str:
    return source_text[records[start_idx][0]:records[end_idx][1]]


def _brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")


def _find_block_end(
    records: list[tuple[int, int, str]],
    start_idx: int,
    *,
    initial_depth: int = 1,
) -> Optional[int]:
    depth = initial_depth
    for idx in range(start_idx + 1, len(records)):
        depth += _brace_delta(records[idx][2])
        if depth == 0:
            return idx
        if depth < 0:
            return None
    return None


def _source_shape_span(
    records: list[tuple[int, int, str]],
    start_idx: int,
    end_idx: int,
) -> tuple[int, int]:
    return (records[start_idx][0], records[end_idx][1])


def _iter_flatten_nested_if_anchors(source_text: str, records: list[tuple[int, int, str]]):
    for idx in range(len(records) - 1):
        line = records[idx][2]
        next_line = records[idx + 1][2]
        if re.match(r"^[ \t]*}\s*else\s*{\s*$", line) is None:
            continue
        if re.match(r"^[ \t]+if\s*\([^{}]+\)\s*{\s*$", next_line) is None:
            continue
        end_idx = _find_block_end(records, idx, initial_depth=1)
        if end_idx is None or end_idx <= idx + 2:
            continue
        block = _block_text(source_text, records, idx, end_idx)
        yield Anchor(
            mutator_key="flatten_nested_if",
            span=_source_shape_span(records, idx, end_idx),
            payload={"block": block},
        )


def _iter_unflatten_else_if_anchors(source_text: str, records: list[tuple[int, int, str]]):
    for idx, (_start, _end, line) in enumerate(records):
        if re.match(r"^[ \t]*}\s*else\s+if\s*\([^{}]+\)\s*{\s*$", line) is None:
            continue
        end_idx = _find_block_end(records, idx, initial_depth=1)
        if end_idx is None:
            continue
        block = _block_text(source_text, records, idx, end_idx)
        yield Anchor(
            mutator_key="unflatten_else_if",
            span=_source_shape_span(records, idx, end_idx),
            payload={"block": block},
        )


def _iter_remove_branch_scope_anchors(source_text: str, records: list[tuple[int, int, str]]):
    for idx, (_start, _end, line) in enumerate(records):
        if re.match(r"^[ \t]+{\s*$", line) is None:
            continue
        previous = next(
            (records[p][2] for p in range(idx - 1, -1, -1) if records[p][2].strip()),
            "",
        )
        if not previous.rstrip().endswith("{"):
            continue
        end_idx = _find_block_end(records, idx, initial_depth=1)
        if end_idx is None or end_idx <= idx + 1:
            continue
        block = _block_text(source_text, records, idx, end_idx)
        yield Anchor(
            mutator_key="remove_branch_scope",
            span=_source_shape_span(records, idx, end_idx),
            payload={"block": block},
        )


_BRANCH_OPEN_RE = re.compile(
    r"^[ \t]*(?:if|else\s+if|else|for|while|switch)\b.*{\s*$"
)


def _iter_add_branch_scope_anchors(source_text: str, records: list[tuple[int, int, str]]):
    for idx, (_start, _end, line) in enumerate(records):
        if _BRANCH_OPEN_RE.match(line) is None:
            continue
        end_idx = _find_block_end(records, idx, initial_depth=1)
        if end_idx is None or end_idx <= idx + 1:
            continue
        body_indices = [
            body_idx
            for body_idx in range(idx + 1, end_idx)
            if records[body_idx][2].strip()
        ]
        if not body_indices:
            continue
        first_body = records[body_indices[0]][2]
        if first_body.strip() == "{":
            continue
        if any(
            re.match(r"^[ \t]*}\s*else\b", records[body_idx][2]) is not None
            for body_idx in body_indices
        ):
            continue
        body = _block_text(source_text, records, idx + 1, end_idx - 1)
        yield Anchor(
            mutator_key="add_branch_scope",
            span=_source_shape_span(records, idx + 1, end_idx - 1),
            payload={"body": body},
        )


def _iter_lifetime_scope_anchors(source_text: str, records: list[tuple[int, int, str]]):
    for idx, (_start, _end, line) in enumerate(records):
        if _BRANCH_OPEN_RE.match(line) is None:
            continue
        end_idx = _find_block_end(records, idx, initial_depth=1)
        if end_idx is None:
            continue
        for inner_idx in range(idx + 1, end_idx):
            inner_line = records[inner_idx][2]
            if _LOCAL_DECL_RE.match(inner_line):
                yield Anchor(
                    mutator_key="widen_local_lifetime",
                    span=_span_for_line(inner_line, source_text),
                    payload={
                        "decl_line": inner_line,
                        "insert_before_line": line,
                    },
                )
                break
        previous_idx = next(
            (p for p in range(idx - 1, -1, -1) if records[p][2].strip()),
            None,
        )
        if previous_idx is not None:
            previous_line = records[previous_idx][2]
            if _LOCAL_DECL_RE.match(previous_line):
                yield Anchor(
                    mutator_key="narrow_local_lifetime",
                    span=_span_for_line(previous_line, source_text),
                    payload={
                        "decl_line": previous_line,
                        "insert_after_line": line,
                    },
                )


_LOOP_COUNTER_DECL_RE = re.compile(
    r"^[ \t]*(?:int|s32)\s+(?P<var>[A-Za-z_]\w*)\s*;\s*$"
)


def _iter_reuse_loop_counter_anchors(source_text: str, records: list[tuple[int, int, str]]):
    outer_decls: dict[str, str] = {}
    for idx, (_start, _end, line) in enumerate(records):
        match = _LOOP_COUNTER_DECL_RE.match(line)
        if match is None:
            continue
        var = match.group("var")
        if var not in outer_decls:
            outer_decls[var] = line
            continue
        next_idx = next(
            (p for p in range(idx + 1, len(records)) if records[p][2].strip()),
            None,
        )
        if next_idx is None:
            continue
        next_line = records[next_idx][2]
        if re.match(rf"^[ \t]*for\s*\(\s*{re.escape(var)}\s*=", next_line) is None:
            continue
        end_idx = _find_block_end(records, next_idx, initial_depth=1)
        if end_idx is None:
            continue
        block = _block_text(source_text, records, idx, end_idx)
        yield Anchor(
            mutator_key="reuse_loop_counter_scope",
            span=_source_shape_span(records, idx, end_idx),
            payload={
                "outer_decl_line": outer_decls[var],
                "block": block,
                "decl_line": line,
            },
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def iter_source_shape_anchors(source_text: str):
    """Yield conservative control-flow/scope anchors for directed search."""
    records = _line_records(source_text)
    yield from _iter_flatten_nested_if_anchors(source_text, records)
    yield from _iter_unflatten_else_if_anchors(source_text, records)
    yield from _iter_remove_branch_scope_anchors(source_text, records)
    yield from _iter_add_branch_scope_anchors(source_text, records)
    yield from _iter_lifetime_scope_anchors(source_text, records)
    yield from _iter_reuse_loop_counter_anchors(source_text, records)


def resolve_anchor(source_idea: Any, source_text: str) -> Optional[Anchor]:
    """Locate the first resolvable select-order edit site for *source_idea*.

    Parameters
    ----------
    source_idea:
        An object with ``.var_name`` (str) and ``.first_def`` (str | None).
        In production this is a ``SourceIdea``; in tests a fake with those
        two attributes is used.
    source_text:
        Full C source text to search.

    Returns
    -------
    Anchor | None
        The first Anchor that resolves, or ``None`` if no lever applies.
    """
    if source_idea is None:
        return None

    var_name: str = getattr(source_idea, "var_name", None)
    if not var_name:
        return None

    # Locate the actual declaration line in the source (ground-truth).
    decl_line = _find_decl_line(var_name, source_text)
    if decl_line is None:
        return None

    # ------------------------------------------------------------------
    # Lever 1: reorder_local_decls
    # ------------------------------------------------------------------
    adjacent = _find_adjacent_decl_line(decl_line, source_text)
    if adjacent is not None and adjacent in source_text and decl_line in source_text:
        span = _span_for_two_lines(decl_line, adjacent, source_text)
        return Anchor(
            mutator_key="reorder_local_decls",
            span=span,
            payload={
                "first_line": decl_line,
                "second_line": adjacent,
            },
        )

    # ------------------------------------------------------------------
    # Lever 2: change_counter_width
    # ------------------------------------------------------------------
    if _COUNTER_WIDTH_RE.search(decl_line) and decl_line in source_text:
        m = _COUNTER_WIDTH_RE.search(decl_line)
        from_type = m.group(1)
        to_type = "s32" if from_type == "s16" else "s16"
        span = _span_for_line(decl_line, source_text)
        return Anchor(
            mutator_key="change_counter_width",
            span=span,
            payload={
                "decl_line": decl_line,
                "from": from_type,
                "to": to_type,
            },
        )

    # ------------------------------------------------------------------
    # Lever 3: split_decl_init
    # ------------------------------------------------------------------
    m_init = _INIT_RE.match(decl_line.lstrip())
    # Re-match against the full (indented) line to capture indent
    m_init2 = _INIT_RE.match(decl_line) if decl_line and decl_line[0] in (" ", "\t") else None
    if m_init2 is None and decl_line.strip():
        # Try matching the stripped form to extract var/type/init
        m_init2 = _INIT_RE.match("    " + decl_line.strip())
    # Use the actual indented line for matching
    m_full = None
    for candidate in (decl_line, decl_line.rstrip()):
        test = _INIT_RE.match(candidate)
        if test:
            m_full = test
            break
    if m_full is None:
        # Try with normalised indent
        stripped = decl_line.strip()
        fake = "    " + stripped
        test = _INIT_RE.match(fake)
        if test and decl_line in source_text:
            var = test.group("var")
            typ = test.group("type").strip()
            init = test.group("init").strip()
            span = _span_for_line(decl_line, source_text)
            return Anchor(
                mutator_key="split_decl_init",
                span=span,
                payload={
                    "decl_line": decl_line,
                    "var": var,
                    "type": typ,
                    "init": init,
                },
            )
    else:
        if decl_line in source_text:
            var = m_full.group("var")
            typ = m_full.group("type").strip()
            init = m_full.group("init").strip()
            span = _span_for_line(decl_line, source_text)
            return Anchor(
                mutator_key="split_decl_init",
                span=span,
                payload={
                    "decl_line": decl_line,
                    "var": var,
                    "type": typ,
                    "init": init,
                },
            )

    return None
