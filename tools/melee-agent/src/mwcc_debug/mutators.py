"""Tier 3 source mutators — tokenizer-based, no pycparser.

Each mutator takes a full source string + a function name + mutation
parameters, returns mutated source as a string. Raises
`MutationUnsupported` when the tokenizer can't unambiguously locate
the target — orchestrator skips that seed.
"""

from __future__ import annotations

import re

from .symbol_bridge import (
    _extract_function_text,
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
