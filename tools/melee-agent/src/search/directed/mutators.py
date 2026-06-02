"""Select-order typed mutators for the directed search layer.

Each mutator takes a compiled Anchor (from anchors.py) and a source string,
applies one deterministic text transform, and returns the new source — or
``None`` if any cited payload text is absent (never emit broken source).

``ORDER_CHANGE_MUTATORS`` is re-exported here so Task 5's scorer can import it
from either ``scorer.py`` (where it is defined) or this module.
"""

from __future__ import annotations

from typing import Optional

from src.search.directed.anchors import Anchor

# ---------------------------------------------------------------------------
# Re-export — Task 5 / scorer.py defines the authoritative set; we mirror it
# here so callers can import from either location.
# ---------------------------------------------------------------------------
ORDER_CHANGE_MUTATORS: frozenset = frozenset({"reorder_local_decls"})


# ---------------------------------------------------------------------------
# Individual mutator implementations
# ---------------------------------------------------------------------------


def _reorder_local_decls(anchor: Anchor, source_text: str) -> Optional[str]:
    """Swap two adjacent local declaration lines in *source_text*.

    Both lines must be present exactly (as literal substrings) in the source;
    they must also be adjacent (first_line\\nsecond_line).  Returns ``None``
    if either line is missing or the pair is not adjacent.
    """
    first = anchor.payload.get("first_line", "")
    second = anchor.payload.get("second_line", "")
    if not first or not second:
        return None
    if first not in source_text or second not in source_text:
        return None
    # Build the two-line block and its replacement.
    original_block = first + "\n" + second
    if original_block not in source_text:
        return None
    swapped_block = second + "\n" + first
    # Replace only the FIRST occurrence to be safe.
    return source_text.replace(original_block, swapped_block, 1)


def _change_counter_width(anchor: Anchor, source_text: str) -> Optional[str]:
    """Replace ``from`` type with ``to`` type in the cited decl line only.

    Only the FIRST occurrence of the cited decl line in the source is touched.
    Within that line, only the first occurrence of the ``from`` type token is
    replaced (so ``s32 s32_count;`` → ``s16 s32_count;``, not a double-replace).
    """
    import re

    decl_line = anchor.payload.get("decl_line", "")
    from_type = anchor.payload.get("from", "")
    to_type = anchor.payload.get("to", "")
    if not decl_line or not from_type or not to_type:
        return None
    if decl_line not in source_text:
        return None
    # Replace the type token in the decl line (first occurrence only, whole-word).
    new_decl_line = re.sub(r"\b" + re.escape(from_type) + r"\b", to_type, decl_line, count=1)
    if new_decl_line == decl_line:
        # Nothing changed — from_type not present
        return None
    # Splice: replace first occurrence of the original decl line in source.
    return source_text.replace(decl_line, new_decl_line, 1)


def _split_decl_init(anchor: Anchor, source_text: str) -> Optional[str]:
    """Split ``T v = E;`` into ``T v;\\n<indent>v = E;``.

    The split preserves the original indentation by measuring the leading
    whitespace of the cited decl line.
    """
    decl_line = anchor.payload.get("decl_line", "")
    var = anchor.payload.get("var", "")
    typ = anchor.payload.get("type", "")
    init = anchor.payload.get("init", "")
    if not decl_line or not var or not typ:
        return None
    if decl_line not in source_text:
        return None
    # Measure leading whitespace from the actual decl_line.
    indent = ""
    for ch in decl_line:
        if ch in (" ", "\t"):
            indent += ch
        else:
            break
    decl_only = f"{indent}{typ} {var};"
    assign = f"{indent}{var} = {init};"
    replacement = decl_only + "\n" + assign
    return source_text.replace(decl_line, replacement, 1)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCH = {
    "reorder_local_decls": _reorder_local_decls,
    "change_counter_width": _change_counter_width,
    "split_decl_init": _split_decl_init,
}


def apply_mutator(key: str, anchor: Anchor, source_text: str) -> Optional[str]:
    """Apply the mutator identified by *key* to *source_text*.

    Parameters
    ----------
    key:
        One of ``"reorder_local_decls"``, ``"change_counter_width"``,
        ``"split_decl_init"``.  Any other value returns ``None``.
    anchor:
        The resolved Anchor whose ``payload`` supplies the exact edit
        parameters.
    source_text:
        Full C source string to transform.

    Returns
    -------
    str | None
        The transformed source, or ``None`` if the cited payload text is
        absent from *source_text* (safe: never emit broken source).
    """
    fn = _DISPATCH.get(key)
    if fn is None:
        return None
    return fn(anchor, source_text)
