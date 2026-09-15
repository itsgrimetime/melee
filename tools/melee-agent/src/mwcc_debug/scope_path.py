"""Utilities for working with scope_path tuples produced by ast_walker.

A scope_path is a tuple[str, ...] where:
  - Element 0 is the function name (always present in production paths).
  - Elements 1..N are nested block identifiers of the form
    "block@l{line}c{col}", where line is 1-indexed and col is 0-indexed
    byte column of the opening `{` token.

Empty tuples are reserved for default-constructed LocalDecl objects in
tests; production code always populates at least the function-name element.
"""
from __future__ import annotations


def is_nested_within(
    candidate: tuple[str, ...],
    ancestor: tuple[str, ...],
) -> bool:
    """Return True if `candidate` is the same scope as `ancestor` or
    is nested inside it. Two unrelated scopes (different function or
    sibling blocks) return False.
    """
    if len(candidate) < len(ancestor):
        return False
    return candidate[: len(ancestor)] == ancestor


def nearest_common_ancestor(
    a: tuple[str, ...],
    b: tuple[str, ...],
) -> tuple[str, ...]:
    """Return the longest shared prefix of two scope paths.
    Identical paths return that path. Cousin paths return their
    common prefix. Unrelated paths return ()."""
    out: list[str] = []
    for x, y in zip(a, b):
        if x != y:
            break
        out.append(x)
    return tuple(out)


def format_for_display(path: tuple[str, ...]) -> str:
    """Render a scope path as `fn/block@l10c4/block@l12c8` for CLI output."""
    return "/".join(path)


def parse_display(text: str) -> tuple[str, ...]:
    """Parse a `/`-separated scope path back into the tuple form."""
    if not text:
        return ()
    return tuple(text.split("/"))
