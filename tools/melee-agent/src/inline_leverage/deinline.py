from __future__ import annotations

import re

from .types import CallSite, DeinlineResult, InlineDef


# Operators that, when adjacent to a substituted parameter, make it an operand
# whose compound argument must be parenthesized to preserve precedence.
_BEFORE_OPS = set("+-*/%&|^<>~!")
_AFTER_OPS = set("+-*/%&|^<>=")


def _substitute_params(text: str, inline_def: InlineDef, args: list[str]) -> str:
    out = text
    for (_type_text, name), arg in zip(inline_def.params, args):
        if not name:
            continue
        stripped = arg.strip()
        compound = _nontrivial_arg(stripped)

        def _repl(
            match: "re.Match[str]", stripped: str = stripped, compound: bool = compound
        ) -> str:
            src = match.string
            start, end = match.start(), match.end()
            # Do not substitute a struct/union field whose name equals the
            # parameter (e.g. `obj->a0` / `obj.a0` when the param is `a0`).
            if start > 0 and src[start - 1] == ".":
                return match.group(0)
            if start >= 2 and src[start - 2:start] == "->":
                return match.group(0)
            if not compound:
                return stripped
            # Parenthesize a compound argument only when the parameter is an
            # operand of a surrounding operator, so precedence is preserved
            # (`a0 * 2` -> `(x + 1) * 2`) without adding noise in delimited
            # contexts (`f(a0)`, `arr[a0]`, `x = a0`).
            i = start - 1
            while i >= 0 and src[i].isspace():
                i -= 1
            before = src[i] if i >= 0 else ""
            j = end
            while j < len(src) and src[j].isspace():
                j += 1
            after = src[j] if j < len(src) else ""
            if before in _BEFORE_OPS or after in _AFTER_OPS:
                return f"({stripped})"
            return stripped

        out = re.sub(rf"\b{re.escape(name)}\b", _repl, out)
    return out


def _nontrivial_arg(arg: str) -> bool:
    text = arg.strip()
    if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", text):
        return False
    if re.fullmatch(r"(0x[0-9A-Fa-f]+|\d+)", text):
        return False
    return True


def _has_unsafe_duplication(inline_def: InlineDef, args: list[str]) -> bool:
    for (_type_text, name), arg in zip(inline_def.params, args):
        if not name:
            continue
        uses = _param_use_count(inline_def.body_text, name)
        if uses > 1 and _nontrivial_arg(arg):
            return True
    return False


def _param_use_count(text: str, name: str) -> int:
    count = 0
    for match in re.finditer(rf"\b{re.escape(name)}\b", text):
        start = match.start()
        if start > 0 and text[start - 1] == ".":
            continue
        if start >= 2 and text[start - 2:start] == "->":
            continue
        count += 1
    return count


def _duplicated_nontrivial_arg_temps(
    source: str,
    inline_def: InlineDef,
    args: list[str],
) -> dict[str, tuple[str, str, str]]:
    temps: dict[str, tuple[str, str, str]] = {}
    used_names = set(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b", source))
    used_names.update(
        name for _type_text, name in inline_def.params if name
    )
    for (type_text, name), arg in zip(inline_def.params, args):
        if not name:
            continue
        uses = _param_use_count(inline_def.body_text, name)
        stripped = arg.strip()
        if uses <= 1 or not _nontrivial_arg(stripped):
            continue
        if not type_text.strip():
            continue
        base = f"inline_{name}_arg"
        temp_name = base
        suffix = 0
        while temp_name in used_names:
            suffix += 1
            temp_name = f"{base}_{suffix}"
        used_names.add(temp_name)
        temps[name] = (type_text.strip(), temp_name, stripped)
    return temps


def _has_unmaterialized_unsafe_duplication(
    inline_def: InlineDef,
    args: list[str],
    arg_temps: dict[str, tuple[str, str, str]],
) -> bool:
    for (_type_text, name), arg in zip(inline_def.params, args):
        if not name:
            continue
        uses = _param_use_count(inline_def.body_text, name)
        if uses > 1 and _nontrivial_arg(arg) and name not in arg_temps:
            return True
    return False


def _return_expression(body_text: str) -> str | None:
    match = re.fullmatch(r"\s*return\s+(?P<expr>.*);\s*", body_text, re.S)
    if match is None:
        return None
    return " ".join(match.group("expr").strip().split())


def _terminal_return_local(body_text: str) -> tuple[str | None, str | None]:
    returns = list(re.finditer(r"\breturn\b", body_text))
    if len(returns) > 1:
        return None, "scalar multi-statement inline has multiple returns"
    if not returns:
        return None, "scalar multi-statement inline does not end in return-local"
    match = re.search(
        r"\breturn\s+(?P<local>[A-Za-z_][A-Za-z_0-9]*)\s*;\s*$",
        body_text.strip(),
    )
    if match is None:
        return None, "scalar multi-statement inline does not end in return-local"
    return match.group("local"), None


def _body_without_terminal_return(body_text: str, return_local: str) -> str:
    pattern = rf"\breturn\s+{re.escape(return_local)}\s*;\s*$"
    return re.sub(pattern, "", body_text.strip()).rstrip()


def _standalone_statement_span(source: str, call: CallSite) -> tuple[int, int] | None:
    line_start = source.rfind("\n", 0, call.byte_start) + 1
    line_end = source.find("\n", call.byte_end)
    if line_end < 0:
        line_end = len(source)
    line = source[line_start:line_end]
    prefix = source[line_start:call.byte_start]
    suffix = source[call.byte_end:line_end]
    if prefix.strip() or suffix.strip() != ";":
        return None
    return line_start, line_end


def _statement_splice(
    body_text: str,
    inline_def: InlineDef,
    args: list[str],
    *,
    arg_temps: dict[str, tuple[str, str, str]] | None = None,
) -> str:
    arg_temps = arg_temps or {}
    substituted_args = [
        arg_temps[name][1]
        if name and name in arg_temps
        else arg
        for (_type_text, name), arg in zip(inline_def.params, args)
    ]
    substituted = _substitute_params(body_text, inline_def, substituted_args)
    lines = ["    {"]
    for _param_name, (type_text, temp_name, arg) in arg_temps.items():
        lines.append(f"        {type_text} {temp_name} = {arg};")
    for line in substituted.splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(f"        {stripped}")
    lines.append("    }")
    return "\n".join(lines)


def _has_compound_assignment(prefix: str) -> bool:
    stripped = prefix.rstrip()
    return bool(re.search(r"(\+\+|--|[!<>=+\-*/%&|^]=)\s*$", stripped))


def _lhs_has_side_effects(lhs: str) -> bool:
    if "++" in lhs or "--" in lhs:
        return True
    if "?" in lhs or "," in lhs or "&&" in lhs or "||" in lhs:
        return True
    if "=" in lhs:
        return True
    return bool(re.search(r"\b[A-Za-z_][A-Za-z_0-9]*\s*\(", lhs))


def _assignment_rhs_statement(
    source: str,
    call: CallSite,
) -> tuple[int, int, str] | str:
    line_start = source.rfind("\n", 0, call.byte_start) + 1
    line_end = source.find("\n", call.byte_end)
    if line_end < 0:
        line_end = len(source)
    suffix = source[call.byte_end:line_end]
    if suffix.strip() != ";":
        return "scalar multi-statement call is not whole assignment RHS"
    prefix = source[line_start:call.byte_start]
    if _has_compound_assignment(prefix):
        return "scalar multi-statement call is not whole assignment RHS"
    eq_index = prefix.rfind("=")
    if eq_index < 0:
        return "scalar multi-statement call is not whole assignment RHS"
    lhs = prefix[:eq_index].strip()
    if not lhs:
        return "scalar multi-statement call is not whole assignment RHS"
    if re.search(r"\b[A-Za-z_][A-Za-z_0-9\s*]*\s+[A-Za-z_][A-Za-z_0-9]*\s*$", lhs):
        return "scalar multi-statement declaration initializer is not supported"
    if _lhs_has_side_effects(lhs):
        return "scalar multi-statement assignment lhs may have side effects"
    return line_start, line_end, lhs


def _scalar_assignment_splice(
    body_text: str,
    inline_def: InlineDef,
    args: list[str],
    lhs: str,
    return_local: str,
) -> str:
    body = _body_without_terminal_return(body_text, return_local)
    substituted = _substitute_params(body, inline_def, args)
    lines = ["    {"]
    for line in substituted.splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(f"        {stripped}")
    lines.append(f"        {lhs.strip()} = {return_local};")
    lines.append("    }")
    return "\n".join(lines)


def build_deinline_patch(
    source: str,
    function: str,
    inline_def: InlineDef,
    call_sites: list[CallSite],
) -> DeinlineResult:
    _ = function
    if not call_sites:
        return DeinlineResult(
            ok=False,
            expansion_form=None,
            new_source=None,
            unsupported_reason="inline has no call sites in function",
        )

    if inline_def.body_kind == "single_return_expr" and inline_def.return_class != "void":
        expr = _return_expression(inline_def.body_text)
        if expr is None:
            return DeinlineResult(
                ok=False,
                expansion_form=None,
                new_source=None,
                unsupported_reason="single-return inline body could not be parsed",
            )
        new_source = source
        for call in sorted(call_sites, key=lambda item: item.byte_start, reverse=True):
            if _has_unsafe_duplication(inline_def, call.args):
                return DeinlineResult(
                    ok=False,
                    expansion_form=None,
                    new_source=None,
                    unsupported_reason="nontrivial argument would be duplicated",
                )
            replacement = f"({_substitute_params(expr, inline_def, call.args)})"
            new_source = (
                new_source[: call.byte_start]
                + replacement
                + new_source[call.byte_end:]
            )
        return DeinlineResult(
            ok=True,
            expansion_form="value_expr",
            new_source=new_source,
        )

    if inline_def.return_class == "scalar" and inline_def.body_kind == "multi_statement":
        return_local, error = _terminal_return_local(inline_def.body_text)
        if return_local is None:
            return DeinlineResult(
                ok=False,
                expansion_form=None,
                new_source=None,
                unsupported_reason=error,
            )
        replacements: list[tuple[int, int, str]] = []
        for call in call_sites:
            if _has_unsafe_duplication(inline_def, call.args):
                return DeinlineResult(
                    ok=False,
                    expansion_form=None,
                    new_source=None,
                    unsupported_reason="nontrivial argument would be duplicated",
                )
            assignment = _assignment_rhs_statement(source, call)
            if isinstance(assignment, str):
                return DeinlineResult(
                    ok=False,
                    expansion_form=None,
                    new_source=None,
                    unsupported_reason=assignment,
                )
            start, end, lhs = assignment
            replacements.append((start, end, _scalar_assignment_splice(
                inline_def.body_text,
                inline_def,
                call.args,
                lhs,
                return_local,
            )))
        new_source = source
        for start, end, replacement in sorted(replacements, reverse=True):
            new_source = new_source[:start] + replacement + new_source[end:]
        return DeinlineResult(
            ok=True,
            expansion_form="scalar_assignment_splice",
            new_source=new_source,
        )

    if inline_def.return_class == "void":
        replacements: list[tuple[int, int, str]] = []
        for call in call_sites:
            arg_temps = _duplicated_nontrivial_arg_temps(
                source,
                inline_def,
                call.args,
            )
            if _has_unmaterialized_unsafe_duplication(
                inline_def,
                call.args,
                arg_temps,
            ):
                return DeinlineResult(
                    ok=False,
                    expansion_form=None,
                    new_source=None,
                    unsupported_reason="nontrivial argument would be duplicated",
                )
            span = _standalone_statement_span(source, call)
            if span is None:
                return DeinlineResult(
                    ok=False,
                    expansion_form=None,
                    new_source=None,
                    unsupported_reason="void inline call is not a standalone statement",
                )
            replacements.append((span[0], span[1], _statement_splice(
                inline_def.body_text,
                inline_def,
                call.args,
                arg_temps=arg_temps,
            )))
        new_source = source
        for start, end, replacement in sorted(replacements, reverse=True):
            new_source = new_source[:start] + replacement + new_source[end:]
        return DeinlineResult(
            ok=True,
            expansion_form="statement_splice",
            new_source=new_source,
        )

    return DeinlineResult(
        ok=False,
        expansion_form=None,
        new_source=None,
        unsupported_reason="inline shape is not supported by first-slice de-inliner",
    )
