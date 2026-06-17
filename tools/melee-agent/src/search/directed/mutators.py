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
ORDER_CHANGE_MUTATORS: frozenset = frozenset({
    "reorder_local_decls",
    "swap_independent_adjacent_statements",
})


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


def _add_explicit_zero_return(anchor: Anchor, source_text: str) -> Optional[str]:
    """Insert ``return 0;`` after a cited side-effect call line."""
    call_line = anchor.payload.get("call_line", "")
    return_line = anchor.payload.get("return_line", "")
    if not call_line or not return_line:
        return None
    start, end = anchor.span
    if 0 <= start < end <= len(source_text) and call_line in source_text[start:end]:
        idx = source_text.find(call_line, start, end)
    else:
        idx = source_text.find(call_line)
    if idx == -1:
        return None
    line_end = source_text.find("\n", idx + len(call_line))
    if line_end == -1:
        insert_at = idx + len(call_line)
        separator = "\n"
    else:
        insert_at = line_end + 1
        separator = ""
    following_line_end = source_text.find("\n", insert_at)
    if following_line_end == -1:
        following_line_end = len(source_text)
    if source_text[insert_at:following_line_end].strip().startswith("return "):
        return None
    return (
        source_text[:insert_at]
        + separator
        + return_line
        + "\n"
        + source_text[insert_at:]
    )


def _replace_exact_line(
    source_text: str,
    line: str,
    replacement_line: str,
) -> Optional[str]:
    if not line or not replacement_line or line not in source_text:
        return None
    if line == replacement_line:
        return None
    return source_text.replace(line, replacement_line, 1)


def _replace_exact_line_at_anchor(
    anchor: Anchor,
    source_text: str,
) -> Optional[str]:
    line = anchor.payload.get("line", "")
    replacement_line = anchor.payload.get("replacement_line", "")
    if not line or not replacement_line or line == replacement_line:
        return None
    start, end = anchor.span
    if 0 <= start < end <= len(source_text) and source_text[start:end] == line:
        return source_text[:start] + replacement_line + source_text[end:]
    if source_text.count(line) != 1:
        return None
    return _replace_exact_line(source_text, line, replacement_line)


def _wrap_comma_noop_assignment_rhs(anchor: Anchor, source_text: str) -> Optional[str]:
    """Wrap a cited assignment RHS as ``(0, rhs)``."""
    return _replace_exact_line(
        source_text,
        anchor.payload.get("line", ""),
        anchor.payload.get("replacement_line", ""),
    )


def _insert_empty_do_while_barrier(anchor: Anchor, source_text: str) -> Optional[str]:
    """Insert an exact empty ``do { } while (0);`` barrier after a line."""
    after_line = anchor.payload.get("after_line", "")
    barrier = anchor.payload.get("barrier", "")
    if not after_line or not barrier or after_line not in source_text:
        return None
    if barrier in source_text:
        return None
    idx = source_text.find(after_line)
    line_end = source_text.find("\n", idx + len(after_line))
    if line_end == -1:
        return source_text[: idx + len(after_line)] + "\n" + barrier + source_text[idx + len(after_line):]
    return source_text[: line_end + 1] + barrier + "\n" + source_text[line_end + 1:]


def _fold_assignment_expression_seed(anchor: Anchor, source_text: str) -> Optional[str]:
    """Fold an adjacent ``tmp = expr; if (tmp != NULL)`` seed into the condition."""
    assignment_line = anchor.payload.get("assignment_line", "")
    condition_line = anchor.payload.get("condition_line", "")
    replacement_line = anchor.payload.get("replacement_line", "")
    if not assignment_line or not condition_line or not replacement_line:
        return None
    original = assignment_line + "\n" + condition_line
    if original not in source_text:
        return None
    return source_text.replace(original, replacement_line, 1)


def _elide_numeric_cast(anchor: Anchor, source_text: str) -> Optional[str]:
    """Elide one proven redundant numeric cast in a cited line."""
    return _replace_exact_line(
        source_text,
        anchor.payload.get("line", ""),
        anchor.payload.get("replacement_line", ""),
    )


def _swap_simple_switch_cases(anchor: Anchor, source_text: str) -> Optional[str]:
    """Swap two exact adjacent self-contained switch arms."""
    first = anchor.payload.get("first_arm", "")
    second = anchor.payload.get("second_arm", "")
    if not first or not second:
        return None
    original = first + "\n" + second
    if original not in source_text:
        return None
    return source_text.replace(original, second + "\n" + first, 1)


def _collapse_hsd_assert(anchor: Anchor, source_text: str) -> Optional[str]:
    """Collapse a cited explicit assert block to an exact HSD_ASSERTMSG line."""
    block = anchor.payload.get("block", "")
    replacement = anchor.payload.get("replacement", "")
    if not block or not replacement or block not in source_text:
        return None
    return source_text.replace(block, replacement, 1)


def _return_tail_call_value(anchor: Anchor, source_text: str) -> Optional[str]:
    """Widen a static void wrapper signature and return its final helper call."""
    signature = anchor.payload.get("signature", "")
    replacement_signature = anchor.payload.get("replacement_signature", "")
    line = anchor.payload.get("line", "")
    replacement_line = anchor.payload.get("replacement_line", "")
    if not signature or not replacement_signature or not line or not replacement_line:
        return None
    if signature not in source_text or line not in source_text:
        return None
    if signature == replacement_signature or line == replacement_line:
        return None
    start, end = anchor.span
    if not (0 <= start < end <= len(source_text)):
        return None
    segment = source_text[start:end]
    if signature not in segment or line not in segment:
        return None
    segment = segment.replace(signature, replacement_signature, 1)
    segment = segment.replace(line, replacement_line, 1)
    return source_text[:start] + segment + source_text[end:]


def _replace_string_literal_with_data_field(
    anchor: Anchor,
    source_text: str,
) -> Optional[str]:
    """Replace one cited string literal argument with a proven data-field expression."""
    line = anchor.payload.get("line", "")
    literal = anchor.payload.get("literal", "")
    replacement = anchor.payload.get("replacement", "")
    if not line or not literal or not replacement or line not in source_text:
        return None
    if literal not in line:
        return None
    replacement_line = line.replace(literal, replacement, 1)
    if replacement_line == line:
        return None
    return source_text.replace(line, replacement_line, 1)


def _replace_float_literal_with_global_constant(
    anchor: Anchor,
    source_text: str,
) -> Optional[str]:
    """Replace one proven floating literal with a source-local constant symbol."""
    return _replace_validated_span(anchor, source_text)


def _replace_global_float_constant_with_literal(
    anchor: Anchor,
    source_text: str,
) -> Optional[str]:
    """Replace one proven source-local floating constant use with its literal."""
    return _replace_validated_span(anchor, source_text)


def _reassociate_fp_subtraction_operands(
    anchor: Anchor,
    source_text: str,
) -> Optional[str]:
    """Rewrite one exact ``-X - C`` RHS span as ``-C - X``."""
    return _replace_validated_span(anchor, source_text)


def _elide_redundant_pointer_cast(anchor: Anchor, source_text: str) -> Optional[str]:
    """Elide one locally proven redundant pointer cast."""
    return _replace_validated_span(anchor, source_text)


def _elide_callback_cast(anchor: Anchor, source_text: str) -> Optional[str]:
    """Elide one locally proven redundant callback/function-pointer cast."""
    return _replace_validated_span(anchor, source_text)


def _rewrite_vector_alias_type(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one local declaration type token between layout-identical aliases."""
    return _replace_validated_span(anchor, source_text)


def _introduce_global_pointer_alias(anchor: Anchor, source_text: str) -> Optional[str]:
    """Insert a local alias and rewrite cited global member accesses."""
    insert_after = anchor.payload.get("insert_after_line", "")
    alias_line = anchor.payload.get("alias_line", "")
    global_prefix = anchor.payload.get("global_prefix", "")
    alias_prefix = anchor.payload.get("alias_prefix", "")
    if not insert_after or not alias_line or not global_prefix or not alias_prefix:
        return None
    if insert_after not in source_text or global_prefix not in source_text:
        return None
    if alias_line in source_text:
        return None
    idx = source_text.find(insert_after)
    line_end = source_text.find("\n", idx + len(insert_after))
    if line_end == -1:
        return None
    before = source_text[: line_end + 1]
    after = source_text[line_end + 1:]
    scope_text = anchor.payload.get("scope_text")
    if scope_text:
        if scope_text not in after:
            return None
        access_spans = anchor.payload.get("access_spans", ())
        if access_spans:
            pieces: list[str] = []
            cursor = 0
            for start, end, replacement in sorted(access_spans):
                if not (0 <= start < end <= len(scope_text)):
                    return None
                pieces.append(scope_text[cursor:start])
                pieces.append(str(replacement))
                cursor = end
            pieces.append(scope_text[cursor:])
            rewritten_scope = "".join(pieces)
        else:
            rewritten_scope = scope_text.replace(global_prefix, alias_prefix)
        if rewritten_scope == scope_text:
            return None
        rewritten_after = after.replace(scope_text, alias_line + "\n" + rewritten_scope, 1)
        return before + rewritten_after
    rewritten_after = after.replace(global_prefix, alias_prefix)
    if rewritten_after == after:
        return None
    return before + alias_line + "\n" + rewritten_after


def _rewrite_raw_pointer_offset_field(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one proven raw byte-offset cast line to a field access line."""
    return _replace_exact_line(
        source_text,
        anchor.payload.get("line", ""),
        anchor.payload.get("replacement_line", ""),
    )


def _rewrite_raw_index_struct_field(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one proven raw indexed byte-offset expression to a field access."""
    return _replace_validated_span(anchor, source_text)


def _rewrite_data_table_indirection(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one proven direct table read through an immutable outer table."""
    return _replace_validated_span(anchor, source_text)


def _rewrite_bool_accumulator_as_int(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one proven bool/BOOL OR-accumulator body to an s32 accumulator."""
    scope_text = anchor.payload.get("scope_text", "")
    decl_line = anchor.payload.get("decl_line", "")
    replacement_decl_line = anchor.payload.get("replacement_decl_line", "")
    if not scope_text or not decl_line or not replacement_decl_line:
        return None
    start, end = anchor.span
    use_span = 0 <= start < end <= len(source_text) and source_text[start:end] == scope_text
    if not use_span and scope_text not in source_text:
        return None
    rewritten_scope = scope_text.replace(decl_line, replacement_decl_line, 1)
    for old_line, new_line in anchor.payload.get("compare_replacements", ()):
        if old_line and new_line:
            rewritten_scope = rewritten_scope.replace(old_line, new_line, 1)
    if rewritten_scope == scope_text:
        return None
    if use_span:
        return source_text[:start] + rewritten_scope + source_text[end:]
    return source_text.replace(scope_text, rewritten_scope, 1)


def _rewrite_zero_compare_logical_not(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one zero comparison condition to logical-not/direct spelling."""
    return _replace_exact_line_at_anchor(anchor, source_text)


def _rewrite_abs_ternary_to_macro(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one guarded absolute-value ternary spelling to ABS(expr)."""
    return _replace_exact_line_at_anchor(anchor, source_text)


def _rewrite_minmax_macro_to_ternary(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one guarded MIN/MAX macro call to explicit ternary spelling."""
    return _replace_exact_line_at_anchor(anchor, source_text)


def _inline_simple_helper_call(anchor: Anchor, source_text: str) -> Optional[str]:
    """Inline one proven simple helper call on its cited line."""
    return _replace_exact_line_at_anchor(anchor, source_text)


def _extract_repeated_assignment_helper(anchor: Anchor, source_text: str) -> Optional[str]:
    """Insert a generated helper and rewrite proven repeated assignment RHS lines."""
    insert_before = anchor.payload.get("insert_before", "")
    helper_text = anchor.payload.get("helper_text", "")
    replacements = anchor.payload.get("line_replacements", ())
    if not insert_before or not helper_text or not replacements:
        return None
    if helper_text in source_text or source_text.count(insert_before) != 1:
        return None
    rewritten = source_text.replace(insert_before, helper_text + insert_before, 1)
    changed = False
    for old_line, new_line in replacements:
        if not old_line or not new_line or old_line == new_line:
            return None
        if rewritten.count(old_line) != 1:
            return None
        rewritten = rewritten.replace(old_line, new_line, 1)
        changed = True
    if not changed or rewritten == source_text:
        return None
    return rewritten


def _reuse_same_type_local_lifetime(anchor: Anchor, source_text: str) -> Optional[str]:
    """Replace one validated target-body scope with a same-type local reuse form."""
    scope_text = anchor.payload.get("scope_text", "")
    replacement_scope_text = anchor.payload.get("replacement_scope_text", "")
    if not scope_text or not replacement_scope_text or scope_text == replacement_scope_text:
        return None
    start, end = anchor.span
    if not (0 <= start < end <= len(source_text)):
        return None
    if source_text[start:end] != scope_text:
        return None
    return source_text[:start] + replacement_scope_text + source_text[end:]


def _replace_validated_span(anchor: Anchor, source_text: str) -> Optional[str]:
    span_text = anchor.payload.get("span_text", "")
    replacement_text = anchor.payload.get("replacement_text", "")
    if not span_text or not replacement_text or span_text == replacement_text:
        return None
    start, end = anchor.span
    if not (0 <= start < end <= len(source_text)):
        return None
    if source_text[start:end] != span_text:
        return None
    return source_text[:start] + replacement_text + source_text[end:]


def _add_dont_inline_pragma_pair(anchor: Anchor, source_text: str) -> Optional[str]:
    """Add one exact push/dont_inline/pop wrapper around the cited function."""
    return _replace_validated_span(anchor, source_text)


def _remove_dont_inline_pragma_pair(anchor: Anchor, source_text: str) -> Optional[str]:
    """Remove one exact push/dont_inline/pop wrapper around the cited function."""
    return _replace_validated_span(anchor, source_text)


def _apply_exact_edits(anchor: Anchor, source_text: str) -> Optional[str]:
    """Apply a sequence of exact, non-overlapping source edits."""
    anchor_span_text = anchor.payload.get("anchor_span_text")
    if isinstance(anchor_span_text, str):
        start, end = anchor.span
        if not (0 <= start <= end <= len(source_text)):
            return None
        if source_text[start:end] != anchor_span_text:
            return None

    raw_edits = anchor.payload.get("edits")
    if not isinstance(raw_edits, list) or not raw_edits:
        return None

    edits: list[tuple[int, int, str, str]] = []
    for raw in raw_edits:
        if not isinstance(raw, dict):
            return None
        start = raw.get("start")
        end = raw.get("end")
        span_text = raw.get("span_text")
        replacement_text = raw.get("replacement_text")
        if not (
            isinstance(start, int)
            and isinstance(end, int)
            and isinstance(span_text, str)
            and isinstance(replacement_text, str)
        ):
            return None
        if start < 0 or end < start or end > len(source_text):
            return None
        if source_text[start:end] != span_text:
            return None
        edits.append((start, end, span_text, replacement_text))

    edits.sort(key=lambda item: item[0])
    previous_end = -1
    for start, end, _span_text, _replacement_text in edits:
        if start < previous_end:
            return None
        previous_end = end

    result = source_text
    for start, end, _span_text, replacement_text in reversed(edits):
        result = result[:start] + replacement_text + result[end:]
    return result


def _remove_unused_trailing_parameter(anchor: Anchor, source_text: str) -> Optional[str]:
    """Remove one locally proven trailing parameter plus matching call args."""
    return _apply_exact_edits(anchor, source_text)


def _add_unused_trailing_parameter(anchor: Anchor, source_text: str) -> Optional[str]:
    """Add one locally proven trailing parameter plus matching call args."""
    return _apply_exact_edits(anchor, source_text)


def _materialize_outgoing_parameter_area_call_args(
    anchor: Anchor,
    source_text: str,
) -> Optional[str]:
    """Introduce exact local temps for selected call arguments."""
    return _apply_exact_edits(anchor, source_text)


def _introduce_named_zero_local(anchor: Anchor, source_text: str) -> Optional[str]:
    """Introduce one named NULL sentinel and rewrite matching NULL uses."""
    return _apply_exact_edits(anchor, source_text)


def _unify_ranked_cursor_value_accumulator(
    anchor: Anchor,
    source_text: str,
) -> Optional[str]:
    """Rewrite one ranked selection loop to use/update the cursor value accumulator."""
    return _apply_exact_edits(anchor, source_text)


def _reuse_rank_pointer_return_field(
    anchor: Anchor,
    source_text: str,
) -> Optional[str]:
    """Rewrite one ranked tail return to use the already-materialized rank pointer."""
    return _apply_exact_edits(anchor, source_text)


def _swap_independent_adjacent_statements(anchor: Anchor, source_text: str) -> Optional[str]:
    """Swap one exact, dependency-proven adjacent statement pair."""
    return _replace_validated_span(anchor, source_text)


def _steer_rotate_local_decl_window(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rotate one exact declaration window for register-coloring steering."""
    return _replace_validated_span(anchor, source_text)


def _steer_demote_local_decl_to_first_use(anchor: Anchor, source_text: str) -> Optional[str]:
    """Move one exact local declaration to its first-use boundary."""
    return _replace_validated_span(anchor, source_text)


def _steer_reuse_dead_top_level_loop_counter(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one exact later loop region to reuse a dead earlier counter."""
    return _replace_validated_span(anchor, source_text)


def _steer_split_reused_loop_counter(anchor: Anchor, source_text: str) -> Optional[str]:
    """Split one exact reused loop-counter loop to a fresh counter."""
    return _replace_validated_span(anchor, source_text)


def _steer_widen_byte_local_type(anchor: Anchor, source_text: str) -> Optional[str]:
    """Widen one exact byte-sized local declaration for register steering."""
    return _replace_validated_span(anchor, source_text)


def _steer_fpr_dependent_product_recompute(anchor: Anchor, source_text: str) -> Optional[str]:
    """Duplicate one exact FPR product into a dependent local assignment."""
    return _replace_validated_span(anchor, source_text)


def _steer_fpr_dependent_product_reuse_temp(anchor: Anchor, source_text: str) -> Optional[str]:
    """Reuse one explicit FPR product temp across dependent assignments."""
    return _replace_validated_span(anchor, source_text)


def _steer_fpr_dependent_local_temp_split(anchor: Anchor, source_text: str) -> Optional[str]:
    """Split one FPR local lifetime before its dependent assignment."""
    return _replace_validated_span(anchor, source_text)


def _steer_fpr_product_assignment_order(anchor: Anchor, source_text: str) -> Optional[str]:
    """Move one independent FPR product assignment earlier in its local block."""
    return _replace_validated_span(anchor, source_text)


def _steer_fpr_product_cast_temp_split(anchor: Anchor, source_text: str) -> Optional[str]:
    """Split a cast operand of one FPR product into an explicit local temp."""
    return _replace_validated_span(anchor, source_text)


def _steer_fpr_product_argument_duplicate(anchor: Anchor, source_text: str) -> Optional[str]:
    """Duplicate one source-bound FPR product expression at a call argument."""
    return _replace_validated_span(anchor, source_text)


def _steer_fpr_product_temp_split(anchor: Anchor, source_text: str) -> Optional[str]:
    """Split one FPR product assignment through an explicit product temp."""
    return _replace_validated_span(anchor, source_text)


def _steer_fpr_paired_product_temp_split(anchor: Anchor, source_text: str) -> Optional[str]:
    """Split paired FPR product assignments through explicit product temps."""
    return _replace_validated_span(anchor, source_text)


def _steer_fpr_product_temp_plus_dependent(anchor: Anchor, source_text: str) -> Optional[str]:
    """Split one FPR product temp while steering another dependent product."""
    return _replace_validated_span(anchor, source_text)


def _steer_indexed_byte_same_line_expr(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one indexed byte-array access without materializing a pointer."""
    return _replace_validated_span(anchor, source_text)


def _steer_indexed_byte_value_temp(anchor: Anchor, source_text: str) -> Optional[str]:
    """Introduce a byte value temp for one indexed byte-array access."""
    return _replace_validated_span(anchor, source_text)


def _steer_indexed_byte_index_temp(anchor: Anchor, source_text: str) -> Optional[str]:
    """Introduce an integer index temp for one indexed byte-array access."""
    return _replace_validated_span(anchor, source_text)


def _steer_indexed_byte_base_alias(anchor: Anchor, source_text: str) -> Optional[str]:
    """Introduce a byte-array base alias for one indexed byte-array access."""
    return _replace_validated_span(anchor, source_text)


def _steer_indexed_byte_init_pointer_alias(anchor: Anchor, source_text: str) -> Optional[str]:
    """Introduce a pointer alias at an indexed-byte initialization boundary."""
    return _replace_validated_span(anchor, source_text)


def _steer_indexed_byte_condition_index_alias(anchor: Anchor, source_text: str) -> Optional[str]:
    """Introduce condition-scoped index aliases for indexed byte-array reads."""
    return _replace_validated_span(anchor, source_text)


def _steer_indexed_byte_totals_index_temp(anchor: Anchor, source_text: str) -> Optional[str]:
    """Introduce integer temps for byte values used as totals indexes."""
    return _replace_validated_span(anchor, source_text)


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
    "add_explicit_zero_return": _add_explicit_zero_return,
    "wrap_comma_noop_assignment_rhs": _wrap_comma_noop_assignment_rhs,
    "insert_empty_do_while_barrier": _insert_empty_do_while_barrier,
    "fold_assignment_expression_seed": _fold_assignment_expression_seed,
    "elide_numeric_cast": _elide_numeric_cast,
    "swap_simple_switch_cases": _swap_simple_switch_cases,
    "collapse_hsd_assert": _collapse_hsd_assert,
    "return_tail_call_value": _return_tail_call_value,
    "replace_string_literal_with_data_field": _replace_string_literal_with_data_field,
    "replace_float_literal_with_global_constant": _replace_float_literal_with_global_constant,
    "replace_global_float_constant_with_literal": _replace_global_float_constant_with_literal,
    "reassociate_fp_subtraction_operands": _reassociate_fp_subtraction_operands,
    "elide_redundant_pointer_cast": _elide_redundant_pointer_cast,
    "elide_callback_cast": _elide_callback_cast,
    "rewrite_vector_alias_type": _rewrite_vector_alias_type,
    "introduce_global_pointer_alias": _introduce_global_pointer_alias,
    "rewrite_raw_pointer_offset_field": _rewrite_raw_pointer_offset_field,
    "rewrite_raw_index_struct_field": _rewrite_raw_index_struct_field,
    "rewrite_data_table_indirection": _rewrite_data_table_indirection,
    "rewrite_bool_accumulator_as_int": _rewrite_bool_accumulator_as_int,
    "rewrite_zero_compare_logical_not": _rewrite_zero_compare_logical_not,
    "rewrite_abs_ternary_to_macro": _rewrite_abs_ternary_to_macro,
    "rewrite_minmax_macro_to_ternary": _rewrite_minmax_macro_to_ternary,
    "inline_simple_helper_call": _inline_simple_helper_call,
    "extract_repeated_assignment_helper": _extract_repeated_assignment_helper,
    "reuse_same_type_local_lifetime": _reuse_same_type_local_lifetime,
    "add_dont_inline_pragma_pair": _add_dont_inline_pragma_pair,
    "remove_dont_inline_pragma_pair": _remove_dont_inline_pragma_pair,
    "remove_unused_trailing_parameter": _remove_unused_trailing_parameter,
    "add_unused_trailing_parameter": _add_unused_trailing_parameter,
    "materialize_outgoing_parameter_area_call_args": (
        _materialize_outgoing_parameter_area_call_args
    ),
    "introduce_named_zero_local": _introduce_named_zero_local,
    "unify_ranked_cursor_value_accumulator": _unify_ranked_cursor_value_accumulator,
    "reuse_rank_pointer_return_field": _reuse_rank_pointer_return_field,
    "steer_reorder_local_decls": _reorder_local_decls,
    "steer_split_decl_init": _split_decl_init,
    "steer_reuse_loop_counter_scope": _reuse_loop_counter_scope,
    "steer_change_counter_width": _change_counter_width,
    "steer_reuse_same_type_local_lifetime": _reuse_same_type_local_lifetime,
    "steer_rotate_local_decl_window": _steer_rotate_local_decl_window,
    "steer_demote_local_decl_to_first_use": _steer_demote_local_decl_to_first_use,
    "steer_reuse_dead_top_level_loop_counter": _steer_reuse_dead_top_level_loop_counter,
    "steer_split_reused_loop_counter": _steer_split_reused_loop_counter,
    "steer_widen_byte_local_type": _steer_widen_byte_local_type,
    "steer_fpr_dependent_product_recompute": _steer_fpr_dependent_product_recompute,
    "steer_fpr_dependent_product_reuse_temp": _steer_fpr_dependent_product_reuse_temp,
    "steer_fpr_dependent_local_temp_split": _steer_fpr_dependent_local_temp_split,
    "steer_fpr_product_assignment_order": _steer_fpr_product_assignment_order,
    "steer_fpr_product_cast_temp_split": _steer_fpr_product_cast_temp_split,
    "steer_fpr_product_argument_duplicate": _steer_fpr_product_argument_duplicate,
    "steer_fpr_product_temp_split": _steer_fpr_product_temp_split,
    "steer_fpr_paired_product_temp_split": _steer_fpr_paired_product_temp_split,
    "steer_fpr_product_temp_plus_dependent": _steer_fpr_product_temp_plus_dependent,
    "steer_indexed_byte_same_line_expr": _steer_indexed_byte_same_line_expr,
    "steer_indexed_byte_value_temp": _steer_indexed_byte_value_temp,
    "steer_indexed_byte_index_temp": _steer_indexed_byte_index_temp,
    "steer_indexed_byte_base_alias": _steer_indexed_byte_base_alias,
    "steer_indexed_byte_init_pointer_alias": _steer_indexed_byte_init_pointer_alias,
    "steer_indexed_byte_condition_index_alias": _steer_indexed_byte_condition_index_alias,
    "steer_indexed_byte_totals_index_temp": _steer_indexed_byte_totals_index_temp,
    "swap_independent_adjacent_statements": _swap_independent_adjacent_statements,
    "scheduler_anchor_iv_init_before_bias": _replace_validated_span,
    "scheduler_split_float_cast_temp": _replace_validated_span,
    "scheduler_empty_barrier_before_float_cast": _replace_validated_span,
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
