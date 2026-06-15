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
  * call-only wrappers that can make a zero return explicit
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


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


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

_CALL_ONLY_STATEMENT_RE = re.compile(
    r"^(?P<indent>[ \t]*)[A-Za-z_]\w*\s*\([^;{}]*\)\s*;\s*$"
)

_ASSIGNMENT_LINE_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<lhs>[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)"
    r"\s*=\s*(?P<rhs>.+);\s*$"
)

_IF_WHILE_NULL_CHECK_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<kw>if|while)\s*\(\s*(?P<var>[A-Za-z_]\w*)"
    r"\s*(?P<op>==|!=)\s*NULL\s*\)\s*{\s*$"
)

_CALL_STATEMENT_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<callee>[A-Za-z_]\w*)\s*\((?P<args>.*)\)\s*;\s*$"
)

_SIMPLE_SCALAR_OPERAND_RE = re.compile(
    r"^[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*$"
)

_SIMPLE_CALL_EXPR_RE = re.compile(
    r"^[A-Za-z_]\w*\s*\((?P<args>.*)\)$"
)

_NUMERIC_CAST_ARG_RE = re.compile(
    r"^\((?P<type>f32|f64|float|double|s8|s16|s32|s64|u8|u16|u32|u64|int|short|long)\)"
    r"\s*(?P<expr>[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)$"
)

_ASSERT_LINE_RE = re.compile(
    r'^(?P<indent>[ \t]*)__assert\("(?P<file>[^"]+)",\s*(?P<line>0x[0-9A-Fa-f]+|\d+),\s*(?P<msg>"(?:\\.|[^"])*")\);\s*$'
)

_IF_NULL_LINE_RE = re.compile(
    r"^(?P<indent>[ \t]*)if\s*\(\s*(?P<var>[A-Za-z_]\w*)\s*==\s*NULL\s*\)\s*(?P<brace>{)?\s*$"
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


def _ignored_call_wrapper_line(line: str) -> bool:
    stripped = line.strip()
    return (
        not stripped
        or stripped in {"{", "}"}
        or stripped.startswith("//")
        or stripped.startswith("/*")
        or stripped.startswith("*")
        or stripped.endswith("*/")
    )


def _iter_add_explicit_zero_return_anchors(
    source_text: str,
    records: list[tuple[int, int, str]],
):
    if re.search(r"\breturn\b", source_text):
        return
    if any(line.lstrip().startswith("#") for _start, _end, line in records):
        return

    statement_records = [
        record for record in records if not _ignored_call_wrapper_line(record[2])
    ]
    if len(statement_records) != 1:
        return

    _start, _end, line = statement_records[0]
    match = _CALL_ONLY_STATEMENT_RE.match(line)
    if match is None:
        return

    yield Anchor(
        mutator_key="add_explicit_zero_return",
        span=_span_for_line(line, source_text),
        payload={
            "call_line": line,
            "return_line": f"{match.group('indent')}return 0;",
        },
    )


def _has_top_level_comma(expr: str) -> bool:
    depth = 0
    in_string: str | None = None
    escape = False
    for ch in expr:
        if in_string is not None:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in {'"', "'"}:
            in_string = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            return True
    return False


def _expr_has_obvious_side_effect(expr: str) -> bool:
    if "++" in expr or "--" in expr:
        return True
    if re.search(r"(?<![=!<>])=(?!=)", expr):
        return True
    if re.search(r"\b[A-Za-z_]\w*\s*\(", expr):
        return True
    return _has_top_level_comma(expr)


def _scalar_expr_has_unsafe_operator(expr: str) -> bool:
    if "++" in expr or "--" in expr or "&&" in expr or "||" in expr:
        return True
    if _has_top_level_comma(expr):
        return True
    if re.search(r"(?<![=!<>])=(?!=)", expr):
        return True
    return re.search(r"==|!=|<=|>=|<|>", expr) is not None


def _simple_scalar_operand(expr: str) -> bool:
    return _SIMPLE_SCALAR_OPERAND_RE.match(expr.strip()) is not None


def _zero_compare_expr_safe(expr: str) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    if _simple_scalar_operand(expr):
        return True
    if _scalar_expr_has_unsafe_operator(expr):
        return False
    call = _SIMPLE_CALL_EXPR_RE.match(expr)
    if call is None:
        return False
    args = _split_top_level_args(call.group("args"))
    if args is None:
        return False
    return all(not _scalar_expr_has_unsafe_operator(arg) for arg in args)


def _iter_comma_noop_assignment_anchors(
    source_text: str,
    records: list[tuple[int, int, str]],
):
    for start, end, line in records:
        match = _ASSIGNMENT_LINE_RE.match(line)
        if match is None:
            continue
        rhs = match.group("rhs").strip()
        if rhs.startswith("(0,") or _has_top_level_comma(rhs):
            continue
        replacement = (
            f"{match.group('indent')}{match.group('lhs')} = (0, {rhs});"
        )
        yield Anchor(
            mutator_key="wrap_comma_noop_assignment_rhs",
            span=(start, end),
            payload={
                "line": line,
                "replacement_line": replacement,
            },
        )


def _statement_barrier_safe(line: str) -> bool:
    stripped = line.strip()
    if not stripped or not stripped.endswith(";"):
        return False
    if stripped.startswith("#"):
        return False
    if stripped.startswith(("return ", "break", "continue", "goto ", "case ", "default:")):
        return False
    if stripped.endswith(":"):
        return False
    if re.match(r"^(?:[A-Za-z_]\w*\s+)+[A-Za-z_]\w*(?:\s*=|;)", stripped):
        return False
    return True


def _label_like(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.endswith(":")
        or stripped.startswith("case ")
        or stripped.startswith("default:")
    )


def _iter_empty_do_while_barrier_anchors(
    source_text: str,
    records: list[tuple[int, int, str]],
):
    for idx in range(len(records) - 1):
        start, end, line = records[idx]
        next_line = records[idx + 1][2]
        previous_line = records[idx - 1][2] if idx > 0 else ""
        if not _statement_barrier_safe(line) or not _statement_barrier_safe(next_line):
            continue
        if _label_like(previous_line) or _label_like(line) or _label_like(next_line):
            continue
        indent = _leading_ws(line)
        yield Anchor(
            mutator_key="insert_empty_do_while_barrier",
            span=(start, end),
            payload={
                "after_line": line,
                "barrier": f"{indent}do {{\n{indent}}} while (0);",
            },
        )


def _iter_assignment_expression_seed_anchors(
    source_text: str,
    records: list[tuple[int, int, str]],
):
    for idx in range(len(records) - 1):
        start, _end, assignment_line = records[idx]
        next_start, next_end, condition_line = records[idx + 1]
        assignment = _ASSIGNMENT_LINE_RE.match(assignment_line)
        condition = _IF_WHILE_NULL_CHECK_RE.match(condition_line)
        if assignment is None or condition is None:
            continue
        var = assignment.group("lhs")
        rhs = assignment.group("rhs").strip()
        if var != condition.group("var") or _expr_has_obvious_side_effect(rhs):
            continue
        replacement = (
            f"{condition.group('indent')}{condition.group('kw')} "
            f"(({var} = {rhs}) {condition.group('op')} NULL) {{"
        )
        yield Anchor(
            mutator_key="fold_assignment_expression_seed",
            span=(start, next_end),
            payload={
                "assignment_line": assignment_line,
                "condition_line": condition_line,
                "replacement_line": replacement,
            },
        )


def _split_top_level_args(args: str) -> list[str] | None:
    result: list[str] = []
    depth = 0
    start = 0
    in_string: str | None = None
    escape = False
    for idx, ch in enumerate(args):
        if in_string is not None:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in {'"', "'"}:
            in_string = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return None
        elif ch == "," and depth == 0:
            result.append(args[start:idx].strip())
            start = idx + 1
    if depth != 0 or in_string is not None:
        return None
    result.append(args[start:].strip())
    return result


def _iter_numeric_cast_anchors(
    source_text: str,
    records: list[tuple[int, int, str]],
):
    for start, end, line in records:
        call = _CALL_STATEMENT_RE.match(line)
        if call is None:
            continue
        args = _split_top_level_args(call.group("args"))
        if args is None:
            continue
        for arg_index, arg in enumerate(args):
            cast = _NUMERIC_CAST_ARG_RE.match(arg)
            if cast is None:
                continue
            replacement_args = list(args)
            replacement_args[arg_index] = cast.group("expr")
            replacement = (
                f"{call.group('indent')}{call.group('callee')}("
                + ", ".join(replacement_args)
                + ");"
            )
            yield Anchor(
                mutator_key="elide_numeric_cast",
                span=(start, end),
                payload={
                    "line": line,
                    "replacement_line": replacement,
                    "callee": call.group("callee"),
                    "arg_index": arg_index,
                    "cast_type": cast.group("type"),
                },
            )


_ZERO_COMPARE_LINE_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<kw>if|while)\s*\(\s*(?P<expr>.+?)\s*"
    r"(?P<op>==|!=)\s*0\s*\)\s*{\s*$"
)

_ABS_TERNARY_RE = re.compile(
    r"\((?P<expr>[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)\s*<\s*"
    r"0(?:\.0(?:[Ff])?)?\)\s*\?\s*-\s*(?P=expr)\s*:\s*(?P=expr)"
)

_MINMAX_CALL_RE = re.compile(r"\b(?P<macro>MIN|MAX)\s*\((?P<args>[^()]*)\)")

_BOOL_ACCUM_DECL_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<type>bool|BOOL)\s+(?P<var>[A-Za-z_]\w*)\s*;\s*$"
)


def _line_code_prefix(line: str) -> str:
    out: list[str] = []
    in_string: str | None = None
    escape = False
    idx = 0
    while idx < len(line):
        ch = line[idx]
        if in_string is not None:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_string:
                in_string = None
            idx += 1
            continue
        if ch in {'"', "'"}:
            in_string = ch
            idx += 1
            continue
        if ch == "/" and idx + 1 < len(line) and line[idx + 1] == "/":
            break
        if ch == "/" and idx + 1 < len(line) and line[idx + 1] == "*":
            break
        out.append(ch)
        idx += 1
    return "".join(out)


def _iter_zero_compare_logical_not_anchors(
    source_text: str,
    records: list[tuple[int, int, str]],
):
    for start, end, line in records:
        match = _ZERO_COMPARE_LINE_RE.match(line)
        if match is None:
            continue
        expr = match.group("expr").strip()
        if not _zero_compare_expr_safe(expr):
            continue
        if match.group("op") == "==":
            replacement_expr = f"!{expr}"
        else:
            replacement_expr = expr
        yield Anchor(
            mutator_key="rewrite_zero_compare_logical_not",
            span=(start, end),
            payload={
                "line": line,
                "replacement_line": (
                    f"{match.group('indent')}{match.group('kw')} "
                    f"({replacement_expr}) {{"
                ),
            },
        )


def _iter_abs_ternary_to_macro_anchors(
    source_text: str,
    records: list[tuple[int, int, str]],
):
    for start, end, line in records:
        code_prefix = _line_code_prefix(line)
        match = _ABS_TERNARY_RE.search(code_prefix)
        if match is None:
            continue
        expr = match.group("expr")
        if not _simple_scalar_operand(expr):
            continue
        replacement_line = (
            line[: match.start()] + f"ABS({expr})" + line[match.end():]
        )
        yield Anchor(
            mutator_key="rewrite_abs_ternary_to_macro",
            span=(start, end),
            payload={
                "line": line,
                "replacement_line": replacement_line,
            },
        )


def _iter_minmax_macro_to_ternary_anchors(
    source_text: str,
    records: list[tuple[int, int, str]],
):
    for start, end, line in records:
        code_prefix = _line_code_prefix(line)
        match = _MINMAX_CALL_RE.search(code_prefix)
        if match is None:
            continue
        args = _split_top_level_args(match.group("args"))
        if args is None or len(args) != 2:
            continue
        left, right = (arg.strip() for arg in args)
        if not _simple_scalar_operand(left) or not _simple_scalar_operand(right):
            continue
        op = ">" if match.group("macro") == "MAX" else "<"
        replacement = f"(({left}) {op} ({right}) ? ({left}) : ({right}))"
        replacement_line = line[: match.start()] + replacement + line[match.end():]
        yield Anchor(
            mutator_key="rewrite_minmax_macro_to_ternary",
            span=(start, end),
            payload={
                "line": line,
                "replacement_line": replacement_line,
            },
        )


def _bool_accumulator_is_unsafe(source_text: str, var: str) -> bool:
    patterns = (
        rf"&\s*{re.escape(var)}\b",
        rf"\+\+\s*{re.escape(var)}\b",
        rf"\b{re.escape(var)}\s*\+\+",
        rf"--\s*{re.escape(var)}\b",
        rf"\b{re.escape(var)}\s*--",
    )
    return any(re.search(pattern, source_text) for pattern in patterns)


def _bool_compare_replacements(
    records: list[tuple[int, int, str]],
    var: str,
) -> tuple[tuple[str, str], ...]:
    pattern = re.compile(
        r"^(?P<prefix>[ \t]*(?:if|while)\s*\(\s*)"
        + re.escape(var)
        + r"\s*(?P<op>==|!=)\s*(?P<literal>false|true)"
        r"(?P<suffix>\s*\)\s*{\s*)$"
    )
    replacements: list[tuple[str, str]] = []
    for _start, _end, line in records:
        match = pattern.match(line)
        if match is None:
            continue
        integer_literal = "1" if match.group("literal") == "true" else "0"
        replacements.append((
            line,
            (
                f"{match.group('prefix')}{var} {match.group('op')} "
                f"{integer_literal}{match.group('suffix')}"
            ),
        ))
    return tuple(replacements)


def _iter_bool_accumulator_anchors(
    source_text: str,
    records: list[tuple[int, int, str]],
):
    for _start, _end, line in records:
        match = _BOOL_ACCUM_DECL_RE.match(line)
        if match is None:
            continue
        var = match.group("var")
        if _bool_accumulator_is_unsafe(source_text, var):
            continue
        if re.search(rf"(?m)^[ \t]*{re.escape(var)}\s*\|=", source_text) is None:
            continue
        if re.search(rf"(?m)^[ \t]*return\s+{re.escape(var)}\s*;", source_text) is None:
            continue
        yield Anchor(
            mutator_key="rewrite_bool_accumulator_as_int",
            span=(0, len(source_text)),
            payload={
                "scope_text": source_text,
                "decl_line": line,
                "replacement_decl_line": (
                    f"{match.group('indent')}s32 {var};"
                ),
                "compare_replacements": _bool_compare_replacements(records, var),
            },
        )
        return


def _switch_arm_safe(lines: list[str]) -> bool:
    if len(lines) < 3:
        return False
    if not re.match(r"^[ \t]*(?:case\b.*:|default:)\s*$", lines[0]):
        return False
    nonempty = [line for line in lines[1:] if line.strip()]
    if not nonempty or nonempty[-1].strip() != "break;":
        return False
    lowered = "\n".join(lines).lower()
    if "fall" in lowered or "goto" in lowered or "switch" in lowered:
        return False
    for body_line in nonempty[:-1]:
        stripped = body_line.strip()
        if _label_like(body_line) or stripped.endswith(":"):
            return False
        if re.match(
            r"^(?:[A-Za-z_]\w*\s+)*[A-Za-z_]\w*\s*\*?\s*[A-Za-z_]\w*(?:\s*\[[^\]]+\])?\s*(?:=|;)",
            stripped,
        ):
            return False
        if stripped.startswith(("if ", "for ", "while ", "do ", "return ")):
            return False
    return True


def _iter_switch_case_order_anchors(
    source_text: str,
    records: list[tuple[int, int, str]],
):
    for idx, (_start, _end, line) in enumerate(records):
        if re.match(r"^[ \t]*switch\s*\([^{}]+\)\s*{\s*$", line) is None:
            continue
        end_idx = _find_block_end(records, idx, initial_depth=1)
        if end_idx is None:
            continue
        label_indices = [
            arm_idx
            for arm_idx in range(idx + 1, end_idx)
            if re.match(r"^[ \t]*(?:case\b.*:|default:)\s*$", records[arm_idx][2])
        ]
        for left, right in zip(label_indices, label_indices[1:]):
            right_end = next(
                (candidate for candidate in label_indices if candidate > right),
                end_idx,
            )
            first_lines = [records[i][2] for i in range(left, right)]
            second_lines = [records[i][2] for i in range(right, right_end)]
            if not _switch_arm_safe(first_lines) or not _switch_arm_safe(second_lines):
                continue
            yield Anchor(
                mutator_key="swap_simple_switch_cases",
                span=(records[left][0], records[right_end - 1][1]),
                payload={
                    "first_arm": "\n".join(first_lines),
                    "second_arm": "\n".join(second_lines),
                },
            )


def _iter_assert_collapse_anchors(
    source_text: str,
    records: list[tuple[int, int, str]],
):
    for idx in range(len(records) - 1):
        start, _end, if_line = records[idx]
        match = _IF_NULL_LINE_RE.match(if_line)
        if match is None:
            continue
        assert_idx = idx + 1
        if match.group("brace"):
            if idx + 2 >= len(records) or records[idx + 2][2].strip() != "}":
                continue
        assert_match = _ASSERT_LINE_RE.match(records[assert_idx][2])
        if assert_match is None:
            continue
        var = match.group("var")
        line_no = assert_match.group("line")
        msg = assert_match.group("msg")
        if match.group("brace"):
            end_idx = idx + 2
            block = _block_text(source_text, records, idx, end_idx)
        else:
            end_idx = assert_idx
            block = _block_text(source_text, records, idx, end_idx)
        yield Anchor(
            mutator_key="collapse_hsd_assert",
            span=(start, records[end_idx][1]),
            payload={
                "block": block,
                "replacement": f'{match.group("indent")}HSD_ASSERTMSG({line_no}, {var}, {msg});',
                "file_name": assert_match.group("file"),
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
    yield from _iter_add_explicit_zero_return_anchors(source_text, records)
    yield from _iter_comma_noop_assignment_anchors(source_text, records)
    yield from _iter_empty_do_while_barrier_anchors(source_text, records)
    yield from _iter_assignment_expression_seed_anchors(source_text, records)
    yield from _iter_numeric_cast_anchors(source_text, records)
    yield from _iter_bool_accumulator_anchors(source_text, records)
    yield from _iter_zero_compare_logical_not_anchors(source_text, records)
    yield from _iter_abs_ternary_to_macro_anchors(source_text, records)
    yield from _iter_minmax_macro_to_ternary_anchors(source_text, records)
    yield from _iter_switch_case_order_anchors(source_text, records)
    yield from _iter_assert_collapse_anchors(source_text, records)


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
