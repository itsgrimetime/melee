"""Tier 3 source mutators — tokenizer-based, no pycparser.

Each mutator takes a full source string + a function name + mutation
parameters, returns mutated source as a string. Raises
`MutationUnsupported` when the tokenizer can't unambiguously locate
the target — orchestrator skips that seed.
"""

from __future__ import annotations

import re
from typing import Optional

from .symbol_bridge import (
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
    decls = walk_local_decls(body_text)
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
    for d in walk_local_decls(body_text):
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
    # If statement is a declaration like `<type> var_name [= ...];` or
    # `<type> var_name[10];` or `<type> a, var_name;`, it's not a read.
    # A declaration has one or more type tokens (identifiers or `*`)
    # before the var name, then `;`, `=`, `[`, or `,`.
    decl_re = re.compile(
        r"^\s*"
        r"(?:[A-Za-z_][A-Za-z_0-9]*\s*\**\s*)+"
        + re.escape(var_name)
        + r"\s*(?:;|=|\[|,)"
    )
    if decl_re.match(cleaned):
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


def mutate_insert_alias_before_use(
    source: str,
    fn_name: str,
    var_name: str,
    at_stmt_index: int,
    new_name: Optional[str] = None,
) -> str:
    """Insert an alias declaration for the N-th reading use of `var_name`
    and rewrite that statement to use `new_name`.

    MWCC uses C89 rules: declarations must appear before any executable
    statements in a block.  If any non-declaration statement precedes the
    insertion point in the function body, we split the alias into:
      - ``<type> <new_name>;``  at the function body's opening brace (safe
        top-of-block position)
      - ``<new_name> = <var_name>;``  immediately before the target
        statement (the assignment is an executable statement, which is fine
        after the decl)

    If the target is already at the block top (all preceding statements are
    declarations or the target is the very first statement), we emit the
    combined initializing form:
      - ``<type> <new_name> = <var_name>;``
    """
    if new_name is None:
        new_name = var_name + "_alias"

    extracted = _extract_function_text(source, fn_name)
    if extracted is None:
        raise MutationUnsupported(f"function {fn_name!r} not found")
    _params_text, body_text, _ = extracted

    var_type = _get_var_type_in_fn(source, fn_name, var_name)
    if var_type is None:
        raise MutationUnsupported(
            f"variable {var_name!r} not found in {fn_name!r}"
        )

    statements = _split_function_body_into_statements(body_text)
    reading_stmts = [
        (start, end, text) for (start, end, text) in statements
        if _statement_is_reading_use(text, var_name)
    ]
    if at_stmt_index >= len(reading_stmts):
        raise MutationUnsupported(
            f"at_stmt_index={at_stmt_index} out of range "
            f"(only {len(reading_stmts)} reading statements)"
        )
    target_start, target_end, target_text = reading_stmts[at_stmt_index]

    # Rewrite the target statement: replace bare `var_name` tokens
    # with `new_name`. Use word-boundary regex to avoid touching
    # substrings.
    word_re = re.compile(r"\b" + re.escape(var_name) + r"\b")
    rewritten = word_re.sub(new_name, target_text)

    # Fix F: detect if the replacement introduced a struct-field alias,
    # e.g. `->jobjs` → `->jobjs_alias[23]`.  This happens when `var_name`
    # is actually a field name embedded in a member-access expression
    # (data->jobjs[i]) rather than a standalone local.  The word-boundary
    # regex correctly matches `jobjs` inside `->jobjs` and replaces it,
    # producing the invalid `->jobjs_alias` pattern.
    #
    # Detection: if the rewritten statement contains `->new_name` or
    # `.new_name` (where new_name starts with var_name), the alias
    # target is a field, not a bindable local.  Raise MutationUnsupported
    # so the seed is skipped.
    _field_re = re.compile(
        r"(?:->|\.)" + re.escape(new_name) + r"\b"
    )
    if _field_re.search(rewritten):
        raise MutationUnsupported(
            f"[tier3-search] skipping alias seed for '{var_name}': appears "
            f"to be a struct field access (found '{new_name}' after '->'/'.'), "
            f"not a bindable local. Use direct-mapping instead."
        )

    # Find leading indentation on the target line so inserted lines match it.
    line_start = body_text.rfind("\n", 0, target_start) + 1
    indent = ""
    j = line_start
    while j < target_start and body_text[j] in " \t":
        indent += body_text[j]
        j += 1

    # Determine whether any non-declaration statement precedes the target
    # in the function body.  If so we must split the alias into a bare
    # decl at block-top + an assignment at the use site (C89 compliance).
    stmts_before_target = [
        (s, e, t) for (s, e, t) in statements if e <= target_start
    ]
    has_non_decl_before = any(
        not _stmt_is_declaration(t) for (_, _, t) in stmts_before_target
    )

    if has_non_decl_before:
        # C89 split: bare decl at function body open brace, assignment
        # immediately before the target statement.
        open_brace = body_text.find("{")
        after_brace = open_brace + 1  # character after `{`
        # Determine indentation from the first existing body line, or use
        # the target's indentation as a reasonable default.
        body_indent = indent

        decl_line = f"\n{body_indent}{var_type} {new_name};"
        assign_line = f"{indent}{new_name} = {var_name};\n"

        # Fix E: place 'alias = local' AFTER local's first real assignment.
        # The target statement (at_stmt_index=0) may be the first USE of the
        # variable, but the variable itself may not have been written yet
        # (e.g. it's a pointer first set by `var_name = expr;` later in
        # the function, or a compound `var_name->field = x;` statement that
        # reads the uninitialized pointer).  If we place `alias = local`
        # immediately before the target without checking, we read an
        # uninitialized variable — MWCC may surface this as a compile error.
        #
        # Strategy: look for the first statement that is a plain write
        # (`var_name = <expr>;`) occurring BEFORE the target statement.
        # If found, insert the alias assignment right after that write.
        # Otherwise fall back to inserting immediately before the target
        # (the compile error from MWCC is the correct outcome and surfaces
        # the issue to the user rather than silently corrupting source).
        _first_write_end: Optional[int] = None
        _write_re = re.compile(
            r"^\s*" + re.escape(var_name) + r"\s*=\s*[^=]"
        )
        for _s, _e, _t in statements:
            if _e > target_start:
                break
            if _write_re.match(_strip_strings_and_comments(_t)):
                _first_write_end = _e
                break

        if _first_write_end is not None and _first_write_end < target_start:
            # Local has a real assignment before the target use.  Insert the
            # alias assignment immediately after that assignment statement.
            _nl = body_text.find("\n", _first_write_end)
            _insert_pos = (_nl + 1) if _nl >= 0 else _first_write_end
            new_body = (
                body_text[:after_brace]
                + decl_line
                + body_text[after_brace:_insert_pos]
                + assign_line
                + body_text[_insert_pos:target_start]
                + rewritten
                + body_text[target_end:]
            )
        else:
            # No prior write found — place alias assignment immediately before
            # the target statement (original behaviour).
            new_body = (
                body_text[:after_brace]
                + decl_line
                + body_text[after_brace:line_start]
                + assign_line
                + body_text[line_start:target_start]
                + rewritten
                + body_text[target_end:]
            )
    else:
        # Block top: safe to use the combined initializing form.
        insert = f"{indent}{var_type} {new_name} = {var_name};\n"
        new_body = (
            body_text[:line_start]
            + insert
            + body_text[line_start:target_start]
            + rewritten
            + body_text[target_end:]
        )

    body_start_in_source = source.find(body_text)
    if body_start_in_source < 0:
        raise MutationUnsupported(
            "could not relocate function body in source"
        )
    return (
        source[:body_start_in_source]
        + new_body
        + source[body_start_in_source + len(body_text):]
    )
