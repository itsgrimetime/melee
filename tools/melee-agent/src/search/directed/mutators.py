"""Select-order typed mutators for the directed search layer.

Each mutator takes a compiled Anchor (from anchors.py) and a source string,
applies one deterministic text transform, and returns the new source — or
``None`` if any cited payload text is absent (never emit broken source).

``ORDER_CHANGE_MUTATORS`` is re-exported here so Task 5's scorer can import it
from either ``scorer.py`` (where it is defined) or this module.
"""

from __future__ import annotations

import re
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


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _indent_unit(parent_indent: str, child_indent: str) -> str:
    if child_indent.startswith(parent_indent) and len(child_indent) > len(parent_indent):
        return child_indent[len(parent_indent):]
    return "    "


def _unindent_one(line: str, base_indent: str, unit: str) -> str:
    prefix = base_indent + unit
    if line.startswith(prefix):
        return base_indent + line[len(prefix):]
    if line.startswith(unit):
        return line[len(unit):]
    return line


def _indent_one(line: str, base_indent: str, unit: str) -> str:
    if line.startswith(base_indent):
        return base_indent + unit + line[len(base_indent):]
    return unit + line


def _remove_exact_line(text: str, line: str) -> Optional[str]:
    if line not in text:
        return None
    for needle in (line + "\n", "\n" + line):
        if needle in text:
            if needle.startswith("\n"):
                return text.replace(needle, "", 1)
            return text.replace(needle, "", 1)
    return text.replace(line, "", 1)


def _flatten_nested_if(anchor: Anchor, source_text: str) -> Optional[str]:
    """Flatten an exact ``} else { if (...) { ... } }`` block."""
    block = anchor.payload.get("block", "")
    if not block or block not in source_text:
        return None
    lines = block.splitlines()
    if len(lines) < 4:
        return None
    outer_match = re.match(r"^(?P<outer>[ \t]*)}\s*else\s*{\s*$", lines[0])
    inner_match = re.match(
        r"^(?P<inner>[ \t]*)if\s*(?P<cond>\([^{}]+\))\s*{\s*$",
        lines[1],
    )
    if outer_match is None or inner_match is None:
        return None
    if lines[-1].strip() != "}" or lines[-2].strip() != "}":
        return None
    outer = outer_match.group("outer")
    inner = inner_match.group("inner")
    unit = _indent_unit(outer, inner)
    cond = inner_match.group("cond")
    body = [_unindent_one(line, outer, unit) for line in lines[2:-2]]
    replacement = "\n".join([f"{outer}}} else if {cond} {{", *body, f"{outer}}}"])
    return source_text.replace(block, replacement, 1)


def _unflatten_else_if(anchor: Anchor, source_text: str) -> Optional[str]:
    """Expand an exact ``} else if (...) { ... }`` block into nested form."""
    block = anchor.payload.get("block", "")
    if not block or block not in source_text:
        return None
    lines = block.splitlines()
    if len(lines) < 2:
        return None
    first = re.match(
        r"^(?P<outer>[ \t]*)}\s*else\s+if\s*(?P<cond>\([^{}]+\))\s*{\s*$",
        lines[0],
    )
    if first is None or lines[-1].strip() != "}":
        return None
    outer = first.group("outer")
    cond = first.group("cond")
    unit = "    "
    body = [_indent_one(line, outer, unit) for line in lines[1:-1]]
    replacement = "\n".join(
        [
            f"{outer}}} else {{",
            f"{outer}{unit}if {cond} {{",
            *body,
            f"{outer}{unit}}}",
            f"{outer}}}",
        ]
    )
    return source_text.replace(block, replacement, 1)


def _remove_branch_scope(anchor: Anchor, source_text: str) -> Optional[str]:
    """Remove one exact brace-only nested block and unindent its body."""
    block = anchor.payload.get("block", "")
    if not block or block not in source_text:
        return None
    lines = block.splitlines()
    if len(lines) < 3:
        return None
    base = _leading_ws(lines[0])
    if lines[0].strip() != "{" or lines[-1].strip() != "}":
        return None
    first_body_indent = _leading_ws(next((line for line in lines[1:-1] if line.strip()), ""))
    unit = _indent_unit(base, first_body_indent)
    replacement = "\n".join(_unindent_one(line, base, unit) for line in lines[1:-1])
    return source_text.replace(block, replacement, 1)


def _add_branch_scope(anchor: Anchor, source_text: str) -> Optional[str]:
    """Wrap an exact branch body in a new brace-only nested scope."""
    body = anchor.payload.get("body", "")
    if not body or body not in source_text:
        return None
    lines = body.splitlines()
    first = next((line for line in lines if line.strip()), "")
    if not first:
        return None
    base = _leading_ws(first)
    unit = "    "
    replacement = "\n".join(
        [f"{base}{{", *(_indent_one(line, base, unit) for line in lines), f"{base}}}"]
    )
    return source_text.replace(body, replacement, 1)


def _widen_local_lifetime(anchor: Anchor, source_text: str) -> Optional[str]:
    """Move a cited local declaration before a cited outer line."""
    decl_line = anchor.payload.get("decl_line", "")
    insert_before = anchor.payload.get("insert_before_line", "")
    if not decl_line or not insert_before:
        return None
    if decl_line not in source_text or insert_before not in source_text:
        return None
    without_decl = _remove_exact_line(source_text, decl_line)
    if without_decl is None or insert_before not in without_decl:
        return None
    widened_decl = f"{_leading_ws(insert_before)}{decl_line.strip()}"
    return without_decl.replace(insert_before, f"{widened_decl}\n{insert_before}", 1)


def _narrow_local_lifetime(anchor: Anchor, source_text: str) -> Optional[str]:
    """Move a cited local declaration immediately inside a cited branch line."""
    decl_line = anchor.payload.get("decl_line", "")
    insert_after = anchor.payload.get("insert_after_line", "")
    if not decl_line or not insert_after:
        return None
    if decl_line not in source_text or insert_after not in source_text:
        return None
    without_decl = _remove_exact_line(source_text, decl_line)
    if without_decl is None or insert_after not in without_decl:
        return None
    narrowed_decl = f"{_leading_ws(insert_after)}    {decl_line.strip()}"
    return without_decl.replace(insert_after, f"{insert_after}\n{narrowed_decl}", 1)


def _reuse_loop_counter_scope(anchor: Anchor, source_text: str) -> Optional[str]:
    """Remove an inner loop-counter declaration so an outer counter is reused."""
    outer_decl = anchor.payload.get("outer_decl_line", "")
    block = anchor.payload.get("block", "")
    decl_line = anchor.payload.get("decl_line", "")
    if not outer_decl or not block or not decl_line:
        return None
    if outer_decl not in source_text or block not in source_text or decl_line not in block:
        return None
    new_block = _remove_exact_line(block, decl_line)
    if new_block is None or new_block == block:
        return None
    return source_text.replace(block, new_block, 1)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCH = {
    "reorder_local_decls": _reorder_local_decls,
    "change_counter_width": _change_counter_width,
    "split_decl_init": _split_decl_init,
    "flatten_nested_if": _flatten_nested_if,
    "unflatten_else_if": _unflatten_else_if,
    "remove_branch_scope": _remove_branch_scope,
    "add_branch_scope": _add_branch_scope,
    "widen_local_lifetime": _widen_local_lifetime,
    "narrow_local_lifetime": _narrow_local_lifetime,
    "reuse_loop_counter_scope": _reuse_loop_counter_scope,
}


def apply_mutator(key: str, anchor: Anchor, source_text: str) -> Optional[str]:
    """Apply the mutator identified by *key* to *source_text*.

    Parameters
    ----------
    key:
        One of the registered directed mutator keys. Any other value returns
        ``None``.
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
    base_key = key.split("@", 1)[0]
    fn = _DISPATCH.get(base_key)
    if fn is None:
        return None
    return fn(anchor, source_text)
