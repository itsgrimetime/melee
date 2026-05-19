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


def mutate_insert_alias_before_use(
    source: str,
    fn_name: str,
    var_name: str,
    at_stmt_index: int,
    new_name: Optional[str] = None,
) -> str:
    """Insert `<type> <new_name> = <var_name>;` immediately before the
    N-th reading statement of `var_name`, and replace bare references
    to `var_name` in THAT statement with `new_name`. Other statements
    are unchanged.
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

    # Find leading indentation on the target line so the inserted
    # alias decl matches it.
    line_start = body_text.rfind("\n", 0, target_start) + 1
    indent = ""
    j = line_start
    while j < target_start and body_text[j] in " \t":
        indent += body_text[j]
        j += 1

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
