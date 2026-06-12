"""Tier 3 source mutators — tokenizer-based, no pycparser.

Each mutator takes a full source string + a function name + mutation
parameters, returns mutated source as a string. Raises
`MutationUnsupported` when the tokenizer can't unambiguously locate
the target — orchestrator skips that seed.
"""

from __future__ import annotations

import re
from typing import Optional

from .scope_path import is_nested_within
from .source_spans import StatementSpan, list_statement_spans
from .symbol_bridge import (
    _DECL_HEAD_RE,
    _extract_function_text,
    _strip_strings_and_comments,
    walk_local_decls,
)


class MutationUnsupported(Exception):
    """Raised when a mutator can't unambiguously locate its target."""


def _normalize_type(type_str: str) -> str:
    """Compact whitespace and `*` placement to the canonical form
    used by walk_local_decls (`HSD_JObj*`, not `HSD_JObj *`)."""
    return re.sub(r"\s*\*\s*", "*", re.sub(r"\s+", " ", type_str.strip()))


def _walk_function_local_decls(source: str, fn_name: str, body_text: str) -> list:
    try:
        from . import ast_walker
        decls = ast_walker.walk_function(source, fn_name, path=None)
        if decls:
            return list(decls)
    except Exception:
        pass
    return walk_local_decls(body_text)


def _find_decl_separator(text: str, start: int) -> int:
    """Return the next top-level comma or end-of-declaration."""
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and c in ",;":
            return i
        i += 1
    return i


def _split_combined_decl_type_change(
    stmt_text: str,
    var_name: str,
    new_type_norm: str,
) -> str | None:
    """Split a combined declaration and retype only ``var_name``.

    Handles common C89 forms like ``int i, j;`` and
    ``int i = 0, j;``. Pointer continuation declarators are deliberately
    left to the simple path because preserving exact C pointer binding
    requires a deeper C declarator model.
    """
    if "," not in stmt_text:
        return None

    leading_ws_len = len(stmt_text) - len(stmt_text.lstrip())
    indent = stmt_text[:leading_ws_len]
    stripped = stmt_text[leading_ws_len:].strip()
    if not stripped.endswith(";"):
        return None
    decl_body = stripped[:-1].strip()

    m = _DECL_HEAD_RE.match(decl_body)
    if m is None:
        return None

    old_type = _normalize_type(m.group("type"))
    if "*" in old_type:
        return None
    declarators: list[tuple[str, str]] = []
    i = m.start("name")
    while i < len(decl_body):
        while i < len(decl_body) and decl_body[i].isspace():
            i += 1
        if i >= len(decl_body):
            break
        end = _find_decl_separator(decl_body, i)
        declarator = decl_body[i:end].strip()
        if not declarator:
            return None
        if declarator.startswith("*"):
            return None
        name_m = re.match(r"(?P<name>[A-Za-z_][A-Za-z_0-9]*)", declarator)
        if name_m is None:
            return None
        declarators.append((name_m.group("name"), declarator))
        i = end
        if i < len(decl_body) and decl_body[i] == ",":
            i += 1
            continue
        break

    if len(declarators) < 2 or not any(name == var_name for name, _ in declarators):
        return None

    lines = []
    for name, declarator in declarators:
        type_str = new_type_norm if name == var_name else old_type
        lines.append(f"{indent}{type_str} {declarator};")
    return "\n".join(lines)


def mutate_type_change(
    source: str,
    fn_name: str,
    var_name: str,
    new_type: str,
) -> str:
    """Change `<old_type> <var_name>` to `<new_type> <var_name>` in
    `fn_name`'s body. Only touches the declaration; uses are left alone.
    """
    extracted = _extract_function_text(source, fn_name)
    if extracted is None:
        raise MutationUnsupported(f"function {fn_name!r} not found")
    _params_text, body_text, _start_line = extracted
    decls = _walk_function_local_decls(source, fn_name, body_text)
    target = next((d for d in decls if d.name == var_name), None)
    if target is None:
        raise MutationUnsupported(
            f"variable {var_name!r} not found in {fn_name!r}"
        )

    # Find the body's absolute offset in source. body_text is a slice of
    # source (per `_extract_function_text`), so `find` will locate it
    # unless the same body text appears multiple times — for v1 we
    # assume one definition per source.
    body_start_in_source = source.find(body_text)
    if body_start_in_source < 0:
        raise MutationUnsupported(
            "could not relocate function body in source"
        )

    # Pattern to match the declaration head:
    # one or more whitespace-separated tokens (type tokens) followed by
    # the variable name and either `=` or `;`. We anchor on the variable
    # name to avoid ambiguity. The `;` between statements blocks the
    # type-token group from spanning across statements.
    pattern = re.compile(
        r"((?:[A-Za-z_][A-Za-z_0-9]*\s*\**\s*)+)"
        r"(" + re.escape(var_name) + r")"
        r"(\s*(?:=|;))",
    )
    new_type_norm = _normalize_type(new_type)

    for stmt_start, stmt_end, stmt_text in _split_function_body_into_statements(body_text):
        replacement = _split_combined_decl_type_change(
            stmt_text, var_name, new_type_norm,
        )
        if replacement is not None:
            body_modified = (
                body_text[:stmt_start]
                + replacement
                + body_text[stmt_end:]
            )
            return (
                source[:body_start_in_source]
                + body_modified
                + source[body_start_in_source + len(body_text):]
            )

    body_modified, count = pattern.subn(
        lambda m: new_type_norm + " " + m.group(2) + m.group(3),
        body_text,
        count=1,
    )
    if count == 0:
        raise MutationUnsupported(
            f"declaration of {var_name!r} did not match the expected "
            f"`<type> <name> [=|;]` pattern"
        )

    return (
        source[:body_start_in_source]
        + body_modified
        + source[body_start_in_source + len(body_text):]
    )


def _get_var_type_in_fn(
    source: str, fn_name: str, var_name: str
) -> Optional[str]:
    """Return the type as declared in `fn_name` for `var_name`.
    Looks at locals first, then parameters."""
    from .symbol_bridge import _parse_params
    extracted = _extract_function_text(source, fn_name)
    if extracted is None:
        return None
    params_text, body_text, _ = extracted
    for d in _walk_function_local_decls(source, fn_name, body_text):
        if d.name == var_name:
            return d.type_str
    for p in _parse_params(params_text):
        if p.name == var_name:
            return p.type_str
    return None


def _split_function_body_into_statements(body_text: str) -> list[tuple[int, int, str]]:
    """Return (start_offset, end_offset, statement_text) per top-level
    statement in the body. Offsets are into `body_text`, with the
    end being just after the trailing `;` or `}`. Strings/comments
    are NOT stripped here — caller may need original text for
    rewriting.
    """
    cleaned = _strip_strings_and_comments(body_text)
    # Body starts with `{`, ends with `}`. Skip those.
    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx < 0 or end_idx <= start_idx:
        return []

    stmts: list[tuple[int, int, str]] = []
    depth_brace = 0
    depth_paren = 0
    stmt_start: Optional[int] = None
    i = start_idx + 1
    while i < end_idx:
        c = cleaned[i]
        if stmt_start is None and not c.isspace():
            line_start = body_text.rfind("\n", 0, i) + 1
            if body_text[line_start:i].strip() == "":
                stmt_start = line_start
            else:
                stmt_start = i
        if c == "{":
            depth_brace += 1
        elif c == "}":
            depth_brace -= 1
        elif c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        if c == ";" and depth_brace == 0 and depth_paren == 0:
            if stmt_start is not None:
                stmts.append((
                    stmt_start, i + 1, body_text[stmt_start:i + 1]
                ))
                stmt_start = None
        i += 1
    return stmts


def _statement_is_reading_use(
    stmt_text: str, var_name: str
) -> bool:
    """True if `stmt_text` reads `var_name` somewhere AND is NOT a
    simple `var_name = ...;` write or `<type> var_name [= ...];`
    declaration.

    v1 only checks the simple write case (LHS = single bare identifier)
    and bare-name declaration case (one-or-more type tokens, then name,
    then `;`, `=`, `[`, or `,`). Compound writes like
    `var_name->x = ...` are reads-of-var_name.
    """
    cleaned = _strip_strings_and_comments(stmt_text)
    word_re = re.compile(r"\b" + re.escape(var_name) + r"\b")
    if not word_re.search(cleaned):
        return False
    # If statement is `<var> = <expr>;` exactly, it's a write.
    write_re = re.compile(
        r"^\s*" + re.escape(var_name) + r"\s*=\s*[^=]"
    )
    if write_re.match(cleaned):
        return False
    return True


def _stmt_is_declaration(stmt_text: str) -> bool:
    """True if `stmt_text` looks like a variable declaration.

    Declarations have one or more type tokens (identifiers or `*`)
    before a variable name, then `=`, `;`, `[`, or `,`.  This is the
    same pattern used by `_statement_is_reading_use` to exclude decls,
    just stated affirmatively.
    """
    cleaned = _strip_strings_and_comments(stmt_text).strip()
    decl_re = re.compile(
        r"^\s*"
        r"(?:[A-Za-z_][A-Za-z_0-9]*\s*\**\s*)+"
        r"[A-Za-z_][A-Za-z_0-9]*"
        r"\s*(?:;|=|\[|,)"
    )
    return bool(decl_re.match(cleaned))


def _span_matches_scope(
    span: "StatementSpan",
    scope_filter: Optional[tuple[str, ...]],
    scope_filter_prefix: Optional[tuple[str, ...]],
) -> bool:
    if scope_filter is not None:
        return span.scope_path == scope_filter
    if scope_filter_prefix is not None:
        # Sentinel form ("fn", "block@") matches any nested scope inside fn.
        if len(scope_filter_prefix) == 2 and scope_filter_prefix[1] == "block@":
            return len(span.scope_path) > 1 and span.scope_path[0] == scope_filter_prefix[0]
        return is_nested_within(span.scope_path, scope_filter_prefix)
    return True


def _find_block_top_pos(source: str, scope_byte_range: tuple[int, int]) -> int:
    """Position immediately after the opening `{` and its trailing newline.
    Does NOT skip existing decls — the alias bare decl is intentionally
    inserted as the FIRST line inside the block so callers can rely on
    its position relative to other declarations in the block."""
    start, end = scope_byte_range
    open_brace = source.find("{", start, end)
    if open_brace < 0:
        return start
    pos = open_brace + 1
    # Consume the rest of the line containing `{` (whitespace then newline).
    while pos < end and source[pos] in " \t\r":
        pos += 1
    if pos < end and source[pos] == "\n":
        pos += 1
    return pos


def mutate_insert_alias_before_use(
    source: str,
    fn_name: str,
    var_name: str,
    at_stmt_index: int,
    new_name: Optional[str] = None,
    scope_filter: Optional[tuple[str, ...]] = None,
    scope_filter_prefix: Optional[tuple[str, ...]] = None,
) -> str:
    """Insert an alias declaration for the N-th reading use of `var_name`
    and rewrite that statement to use `new_name`.

    Form selection:
      - Function-top target with no non-decls before it in the same block
        → combined initializing form (`<type> <new_name> = <var>;`).
      - Otherwise → split form (bare `<type> <new_name>;` at the nearest
        enclosing block top + `<new_name> = <var>;` right before the use,
        moved after the first plain write of `<var>` when one exists in
        the same block before the use).
    """
    if new_name is None:
        new_name = var_name + "_alias"

    if _extract_function_text(source, fn_name) is None:
        raise MutationUnsupported(f"function {fn_name!r} not found")

    var_type = _get_var_type_in_fn(source, fn_name, var_name)
    if var_type is None:
        raise MutationUnsupported(
            f"variable {var_name!r} not found in {fn_name!r}"
        )

    span_statements = list_statement_spans(source, fn_name)
    target_span_candidates = [
        span for span in span_statements
        if _span_matches_scope(span, scope_filter, scope_filter_prefix)
        and span.kind != "declaration"
        and _statement_is_reading_use(span.text, var_name)
    ]
    if at_stmt_index >= len(target_span_candidates):
        raise MutationUnsupported(
            f"at_stmt_index={at_stmt_index} out of range "
            f"(only {len(target_span_candidates)} reading statements)"
        )
    target_span = target_span_candidates[at_stmt_index]
    target_start_abs, target_end_abs = target_span.byte_range
    target_text = source[target_start_abs:target_end_abs]

    # Rewrite the target: replace bare `var_name` tokens with `new_name`.
    word_re = re.compile(r"\b" + re.escape(var_name) + r"\b")
    rewritten = word_re.sub(new_name, target_text)

    # Struct-field guard: if the only occurrence is `->var` or `.var`, refuse.
    field_re = re.compile(r"(?:->|\.)" + re.escape(new_name) + r"\b")
    if field_re.search(rewritten):
        raise MutationUnsupported(
            f"[debug mutate search] skipping alias seed for '{var_name}': appears "
            f"to be a struct field access (found '{new_name}' after '->'/'.'), "
            f"not a bindable local. Use direct-mapping instead."
        )

    # Indentation of the target's line (spaces/tabs only).
    target_line_start_abs = source.rfind("\n", 0, target_start_abs) + 1
    indent = ""
    for ch in source[target_line_start_abs:target_start_abs]:
        if ch in " \t":
            indent += ch
        else:
            break

    # Spans in the same block as target, lying before it.
    same_block_before = [
        s for s in span_statements
        if s.scope_path == target_span.scope_path
        and s.byte_range[1] <= target_start_abs
    ]
    has_non_decl_before = any(s.kind != "declaration" for s in same_block_before)
    is_function_top = len(target_span.scope_path) == 1

    if is_function_top and not has_non_decl_before:
        # Combined form: decl+init at target line.
        combined_line = f"{indent}{var_type} {new_name} = {var_name};\n"
        return (
            source[:target_line_start_abs]
            + combined_line
            + source[target_line_start_abs:target_start_abs]
            + rewritten
            + source[target_end_abs:]
        )

    # Split form. Decl goes at nearest block top; assign goes either right
    # after `var`'s first plain write in the same block, or right before
    # the use when no such write exists.
    decl_insert_abs = _find_block_top_pos(source, target_span.scope_byte_range)
    decl_line = f"{indent}{var_type} {new_name};\n"

    write_re = re.compile(r"^\s*" + re.escape(var_name) + r"\s*=\s*[^=]")
    first_write_end_abs: Optional[int] = None
    for s in same_block_before:
        cleaned = _strip_strings_and_comments(s.text)
        if write_re.match(cleaned):
            first_write_end_abs = s.byte_range[1]
            break

    if first_write_end_abs is not None and first_write_end_abs < target_start_abs:
        nl = source.find("\n", first_write_end_abs)
        assign_insert_abs = (nl + 1) if nl >= 0 else first_write_end_abs
    else:
        assign_insert_abs = target_line_start_abs

    assign_line = f"{indent}{new_name} = {var_name};\n"

    edits: list[tuple[int, int, str]] = [
        (target_start_abs, target_end_abs, rewritten),
        (assign_insert_abs, assign_insert_abs, assign_line),
        (decl_insert_abs, decl_insert_abs, decl_line),
    ]
    out = source
    for start, end, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        out = out[:start] + replacement + out[end:]
    return out


def mutate_preserve_lifetime_after_use(
    source: str,
    fn_name: str,
    var_name: str,
    at_stmt_index: int,
    sink_name: Optional[str] = None,
    scope_filter: Optional[tuple[str, ...]] = None,
    scope_filter_prefix: Optional[tuple[str, ...]] = None,
) -> str:
    """Insert a volatile sink assignment after the N-th reading use.

    This gives simplify-order searches a source-level way to keep a holder
    live across a later statement without rewriting the statement that reads
    it. The resulting candidate is intended for compile-and-rank search, not
    as final checked-in decomp source.
    """
    if sink_name is None:
        sink_name = var_name + "_lifetime_sink"

    if _extract_function_text(source, fn_name) is None:
        raise MutationUnsupported(f"function {fn_name!r} not found")

    var_type = _get_var_type_in_fn(source, fn_name, var_name)
    if var_type is None:
        raise MutationUnsupported(
            f"variable {var_name!r} not found in {fn_name!r}"
        )
    if "[" in var_type or "(" in var_type:
        raise MutationUnsupported(
            f"variable {var_name!r} has unsupported lifetime-sink type {var_type!r}"
        )

    span_statements = list_statement_spans(source, fn_name)
    target_span_candidates = [
        span for span in span_statements
        if _span_matches_scope(span, scope_filter, scope_filter_prefix)
        and span.kind != "declaration"
        and _statement_is_reading_use(span.text, var_name)
    ]
    if at_stmt_index >= len(target_span_candidates):
        raise MutationUnsupported(
            f"at_stmt_index={at_stmt_index} out of range "
            f"(only {len(target_span_candidates)} reading statements)"
        )
    target_span = target_span_candidates[at_stmt_index]
    target_start_abs, target_end_abs = target_span.byte_range
    target_text = source[target_start_abs:target_end_abs]

    field_re = re.compile(r"(?:->|\.)" + re.escape(var_name) + r"\b")
    if field_re.search(target_text):
        raise MutationUnsupported(
            f"[debug mutate search] skipping lifetime seed for '{var_name}': "
            "appears to be a struct field access, not a bindable local."
        )

    target_line_start_abs = source.rfind("\n", 0, target_start_abs) + 1
    indent = ""
    for ch in source[target_line_start_abs:target_start_abs]:
        if ch in " \t":
            indent += ch
        else:
            break

    decl_insert_abs = _find_block_top_pos(source, target_span.scope_byte_range)
    decl_line = f"{indent}volatile {var_type} {sink_name};\n"

    nl = source.find("\n", target_end_abs)
    assign_insert_abs = (nl + 1) if nl >= 0 else target_end_abs
    assign_line = f"{indent}{sink_name} = {var_name};\n"

    edits: list[tuple[int, int, str]] = [
        (assign_insert_abs, assign_insert_abs, assign_line),
        (decl_insert_abs, decl_insert_abs, decl_line),
    ]
    out = source
    for start, end, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        out = out[:start] + replacement + out[end:]
    return out
