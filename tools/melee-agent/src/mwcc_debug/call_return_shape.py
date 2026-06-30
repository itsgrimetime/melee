"""Source-shape probes for call-return copy-propagation residuals."""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .pressure_explorer import LifetimeLayoutProbe


CALL_RETURN_USE_SHAPE_OPERATOR = "call-return-use-shape"

_IDENT = r"[A-Za-z_]\w*"
_IDENT_RE = re.compile(rf"^{_IDENT}$")


@dataclass(frozen=True)
class _CallReturnTarget:
    expression: str
    assigned_local: str
    source_line: int | None
    source_file: str | None


@dataclass(frozen=True)
class _CopyAssignment:
    assigned_local: str
    copy_local: str
    copy_type: str
    indent: str
    assign_start: int
    assign_end: int
    assign_line_end: int
    decl_start: int | None
    decl_end: int | None
    decl_line_end: int | None
    decl_indent: str | None
    decl_initializer: str | None
    line_no: int


def generate_call_return_use_shape_probes(
    source_text: str,
    function: str,
    trace_target: Mapping[str, Any] | None,
    *,
    max_probes: int,
) -> list[LifetimeLayoutProbe]:
    """Generate C89-valid source-shape probes around a retained call return.

    The trace-copy report usually maps both virtuals back to the call-return
    assignment, not to the follow-on copied local. This generator finds that
    copied local in source and emits source variants that test direct use,
    duplicate call, declaration initializer, and scoped lifetime shapes.
    """
    if trace_target is None or max_probes <= 0:
        return []
    if not _trace_target_applies(trace_target):
        return []
    target = _call_return_target(trace_target)
    if target is None:
        return []
    span = _find_function_body_span(source_text, function)
    if span is None:
        return []
    body_start, body_end = span
    copies = _find_call_return_copy_assignments(
        source_text,
        body_start=body_start,
        body_end=body_end,
        target=target,
    )
    probes: list[LifetimeLayoutProbe] = []
    seen: set[str] = set()
    for index, copy in enumerate(copies):
        for probe in _copy_assignment_variants(
            source_text,
            body_end=body_end,
            copy=copy,
            target=target,
            index=index,
        ):
            if len(probes) >= max_probes:
                return probes
            if probe.source_text in seen:
                continue
            seen.add(probe.source_text)
            probes.append(probe)
    return probes


def summarize_call_return_use_shape_trace(
    trace_target: Mapping[str, Any] | None,
    *,
    function: str | None = None,
) -> dict[str, Any] | None:
    """Return a path-free summary for suggest/coalesce trace-copy mode."""
    if trace_target is None or not _trace_target_applies(trace_target):
        return None
    target = _call_return_target(trace_target)
    if target is None:
        return None
    prefix = "f" if trace_target.get("register_class") == "fpr" else "r"
    from_virtual = trace_target.get("from_virtual")
    to_virtual = trace_target.get("to_virtual")
    trace_path = _clean_str(trace_target.get("path")) or "<trace-copy.json>"
    function_arg = function or _clean_str(trace_target.get("function")) or "<function>"
    return {
        "kind": "call-return-use-shape-continuation",
        "status": "source-shape-probe-required",
        "target_pair": f"{prefix}{from_virtual}/{prefix}{to_virtual}",
        "from_virtual": from_virtual,
        "to_virtual": to_virtual,
        "source_expression": target.expression,
        "assigned_local": target.assigned_local,
        "source_file": target.source_file,
        "source_line": target.source_line,
        "candidate_families": [
            "direct-use",
            "direct-first-use",
            "duplicate-call",
            "declaration-initializer",
            "scoped-copy",
        ],
        "next_command": (
            "melee-agent debug coalesce-search "
            f"-f {shlex.quote(function_arg)} "
            f"--trace-copy-json {shlex.quote(trace_path)} "
            "--compile-probes --json"
        ),
        "retention_contract": (
            "coalesce-search retains generated call-return/use-shape source "
            "candidates and pcdumps under build/mwcc_debug_cache/probes/"
            "coalesce_search"
        ),
    }


def _trace_target_applies(trace_target: Mapping[str, Any]) -> bool:
    if trace_target.get("register_class") not in {None, "gpr"}:
        return False
    first_absent = str(trace_target.get("first_absent_pass") or "").upper()
    if first_absent == "AFTER COPY PROPAGATION":
        return True
    for key in ("likely_cause", "transform_category", "trace_status"):
        value = trace_target.get(key)
        if isinstance(value, str) and "copy-propagation" in value.lower():
            return True
    return False


def _call_return_target(
    trace_target: Mapping[str, Any],
) -> _CallReturnTarget | None:
    targets: list[_CallReturnTarget] = []
    for key in ("from_operand", "to_operand"):
        operand = trace_target.get(key)
        if not isinstance(operand, Mapping):
            continue
        origin = operand.get("call_return_origin")
        if not isinstance(origin, Mapping):
            continue
        expression = _clean_str(origin.get("expression")) or _clean_str(
            operand.get("expression")
        )
        assigned_local = _clean_str(origin.get("assigned_local")) or _clean_str(
            operand.get("source_local")
        )
        if not expression or not assigned_local:
            continue
        if not _simple_identifier(assigned_local):
            continue
        if "(" not in expression or ")" not in expression:
            continue
        if not (
            operand.get("mapped_to_source")
            or origin.get("source_file")
            or origin.get("source_line") is not None
        ):
            continue
        targets.append(_CallReturnTarget(
            expression=expression,
            assigned_local=assigned_local,
            source_line=_int_or_none(origin.get("source_line")),
            source_file=_clean_str(origin.get("source_file")),
        ))
    if not targets:
        return None
    first = targets[0]
    for target in targets[1:]:
        if (
            target.expression == first.expression
            and target.assigned_local == first.assigned_local
        ):
            continue
        return None
    return first


def _find_call_return_copy_assignments(
    source: str,
    *,
    body_start: int,
    body_end: int,
    target: _CallReturnTarget,
) -> list[_CopyAssignment]:
    body = source[body_start:body_end]
    assign_re = re.compile(
        rf"(?m)^(?P<indent>[ \t]*)(?P<copy>{_IDENT})\s*=\s*"
        rf"{re.escape(target.assigned_local)}\s*;\s*$"
    )
    copies: list[_CopyAssignment] = []
    for match in assign_re.finditer(body):
        copy_local = match.group("copy")
        if copy_local == target.assigned_local:
            continue
        abs_start = body_start + match.start()
        abs_end = body_start + match.end()
        line_end = _include_trailing_newline(source, abs_end)
        decl = _find_pointer_decl_before(
            source,
            body_start=body_start,
            limit=abs_start,
            name=copy_local,
        )
        copy_type = "char*"
        if decl is not None:
            copy_type = decl["type"]
        copies.append(_CopyAssignment(
            assigned_local=target.assigned_local,
            copy_local=copy_local,
            copy_type=copy_type,
            indent=match.group("indent"),
            assign_start=abs_start,
            assign_end=abs_end,
            assign_line_end=line_end,
            decl_start=None if decl is None else decl["start"],
            decl_end=None if decl is None else decl["end"],
            decl_line_end=None if decl is None else decl["line_end"],
            decl_indent=None if decl is None else decl["indent"],
            decl_initializer=None if decl is None else decl["initializer"],
            line_no=_line_no(source, abs_start),
        ))
    return copies


def _find_pointer_decl_before(
    source: str,
    *,
    body_start: int,
    limit: int,
    name: str,
) -> dict[str, Any] | None:
    text = source[body_start:limit]
    decl_re = re.compile(
        rf"(?m)^(?P<indent>[ \t]*)"
        rf"(?P<type>(?:const\s+|volatile\s+|static\s+|register\s+)*"
        rf"(?:struct\s+{_IDENT}|{_IDENT})(?:\s+{_IDENT})*\s*\*+)\s*"
        rf"{re.escape(name)}\s*(?:=\s*(?P<init>[^;\n]+))?\s*;\s*$"
    )
    last: re.Match[str] | None = None
    for match in decl_re.finditer(text):
        last = match
    if last is None:
        return None
    abs_start = body_start + last.start()
    abs_end = body_start + last.end()
    type_text = re.sub(r"\s+", " ", last.group("type")).strip()
    type_text = re.sub(r"\s*\*\s*", "*", type_text)
    return {
        "start": abs_start,
        "end": abs_end,
        "line_end": _include_trailing_newline(source, abs_end),
        "indent": last.group("indent"),
        "type": type_text,
        "initializer": (
            None if last.group("init") is None else last.group("init").strip()
        ),
    }


def _copy_assignment_variants(
    source: str,
    *,
    body_end: int,
    copy: _CopyAssignment,
    target: _CallReturnTarget,
    index: int,
) -> list[LifetimeLayoutProbe]:
    variants: list[LifetimeLayoutProbe] = []

    def append(
        *,
        variant: str,
        description: str,
        source_text: str,
        source_hunks: list[dict[str, Any]],
    ) -> None:
        variants.append(LifetimeLayoutProbe(
            label=f"call-return-use-shape-{variant}-{index}",
            operator=CALL_RETURN_USE_SHAPE_OPERATOR,
            description=description,
            source_text=source_text,
            provenance={
                "kind": CALL_RETURN_USE_SHAPE_OPERATOR,
                "variant": variant,
                "assigned_local": target.assigned_local,
                "copy_local": copy.copy_local,
                "copy_type": copy.copy_type,
                "call_expression": target.expression,
                "source_file": target.source_file,
                "source_line": target.source_line,
                "line": copy.line_no,
                "source_hunk": source_hunks[0],
                "source_hunks": source_hunks,
            },
        ))

    after_assignment = source[copy.assign_line_end:body_end]
    direct_after = _replace_identifier(
        after_assignment,
        copy.copy_local,
        target.assigned_local,
    )
    if direct_after != after_assignment:
        append(
            variant="direct-use",
            description=(
                f"Use `{target.assigned_local}` directly instead of copied local "
                f"`{copy.copy_local}` after the call-return assignment."
            ),
            source_text=(
                source[:copy.assign_start] + direct_after + source[body_end:]
            ),
            source_hunks=[
                _source_hunk(
                    source,
                    start=copy.assign_start,
                    end=copy.assign_line_end,
                    replacement="",
                ),
                {
                    "line_start": _line_no(source, copy.assign_line_end),
                    "line_end": _line_no(source, max(copy.assign_line_end, body_end - 1)),
                    "original": "replace later copy-local uses",
                    "replacement": (
                        f"{copy.copy_local} -> {target.assigned_local}"
                    ),
                },
            ],
        )

        first_after = _replace_identifier(
            after_assignment,
            copy.copy_local,
            target.assigned_local,
            count=1,
        )
        if first_after != after_assignment:
            append(
                variant="direct-first-use",
                description=(
                    f"Use `{target.assigned_local}` for the first post-copy read "
                    f"while retaining `{copy.copy_local}` for later reads."
                ),
                source_text=(
                    source[:copy.assign_line_end] + first_after + source[body_end:]
                ),
                source_hunks=[{
                    "line_start": _line_no(source, copy.assign_line_end),
                    "line_end": _line_no(source, copy.assign_line_end),
                    "original": f"first {copy.copy_local} use",
                    "replacement": target.assigned_local,
                }],
            )

    duplicate_replacement = (
        f"{copy.indent}{copy.copy_local} = {target.expression};\n"
    )
    append(
        variant="duplicate-call",
        description=(
            f"Populate `{copy.copy_local}` from a second `{target.expression}` "
            "call instead of copying the retained call-return local."
        ),
        source_text=_replace_span(
            source,
            start=copy.assign_start,
            end=copy.assign_line_end,
            replacement=duplicate_replacement,
        ),
        source_hunks=[
            _source_hunk(
                source,
                start=copy.assign_start,
                end=copy.assign_line_end,
                replacement=duplicate_replacement,
            ),
        ],
    )

    if (
        copy.decl_start is not None
        and copy.decl_line_end is not None
        and copy.decl_initializer is None
    ):
        decl_indent = copy.decl_indent or copy.indent
        decl_replacement = (
            f"{decl_indent}{copy.copy_type} {copy.copy_local} = "
            f"{target.expression};\n"
        )
        append(
            variant="declaration-initializer",
            description=(
                f"Initialize `{copy.copy_local}` at its declaration with "
                f"`{target.expression}` and remove the later copy assignment."
            ),
            source_text=(
                source[:copy.decl_start]
                + decl_replacement
                + source[copy.decl_line_end:copy.assign_start]
                + source[copy.assign_line_end:]
            ),
            source_hunks=[
                _source_hunk(
                    source,
                    start=copy.decl_start,
                    end=copy.decl_line_end,
                    replacement=decl_replacement,
                ),
                _source_hunk(
                    source,
                    start=copy.assign_start,
                    end=copy.assign_line_end,
                    replacement="",
                ),
            ],
        )

    alias = _fresh_alias_name(source, "ll_callret_copy", index)
    scoped_replacement = (
        f"{copy.indent}{{\n"
        f"{copy.indent}    {copy.copy_type} {alias} = {target.assigned_local};\n"
        f"{copy.indent}    {copy.copy_local} = {alias};\n"
        f"{copy.indent}}}\n"
    )
    append(
        variant="scoped-copy",
        description=(
            f"Split `{target.assigned_local}` -> `{copy.copy_local}` through "
            "a declaration-first scoped local."
        ),
        source_text=_replace_span(
            source,
            start=copy.assign_start,
            end=copy.assign_line_end,
            replacement=scoped_replacement,
        ),
        source_hunks=[
            _source_hunk(
                source,
                start=copy.assign_start,
                end=copy.assign_line_end,
                replacement=scoped_replacement,
            ),
        ],
    )
    return variants


def _find_matching(
    source: str,
    open_idx: int,
    *,
    open_char: str,
    close_char: str,
) -> int | None:
    depth = 0
    idx = open_idx
    while idx < len(source):
        char = source[idx]
        nxt = source[idx + 1] if idx + 1 < len(source) else ""
        if char == "/" and nxt == "/":
            newline = source.find("\n", idx + 2)
            if newline < 0:
                return None
            idx = newline + 1
            continue
        if char == "/" and nxt == "*":
            end = source.find("*/", idx + 2)
            if end < 0:
                return None
            idx = end + 2
            continue
        if char in {"'", '"'}:
            quote = char
            idx += 1
            escaped = False
            while idx < len(source):
                current = source[idx]
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    idx += 1
                    break
                idx += 1
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return idx
        idx += 1
    return None


def _find_function_body_span(
    source: str,
    function: str,
) -> tuple[int, int] | None:
    for match in re.finditer(rf"\b{re.escape(function)}\s*\(", source):
        open_paren = source.find("(", match.start())
        if open_paren < 0:
            continue
        close_paren = _find_matching(
            source,
            open_paren,
            open_char="(",
            close_char=")",
        )
        if close_paren is None:
            continue
        cursor = close_paren + 1
        while cursor < len(source) and source[cursor].isspace():
            cursor += 1
        if cursor >= len(source) or source[cursor] != "{":
            continue
        close_brace = _find_matching(
            source,
            cursor,
            open_char="{",
            close_char="}",
        )
        if close_brace is not None:
            return cursor + 1, close_brace
    return None


def _line_no(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _source_hunk(
    source: str,
    *,
    start: int,
    end: int,
    replacement: str,
) -> dict[str, Any]:
    return {
        "line_start": _line_no(source, start),
        "line_end": _line_no(source, max(start, end - 1)),
        "original": source[start:end],
        "replacement": replacement,
    }


def _replace_span(source: str, *, start: int, end: int, replacement: str) -> str:
    return source[:start] + replacement + source[end:]


def _replace_identifier(
    text: str,
    old: str,
    new: str,
    *,
    count: int = 0,
) -> str:
    return re.sub(rf"\b{re.escape(old)}\b", new, text, count=count)


def _include_trailing_newline(source: str, offset: int) -> int:
    if offset < len(source) and source[offset] == "\n":
        return offset + 1
    return offset


def _fresh_alias_name(source: str, prefix: str, index: int) -> str:
    candidate_idx = index
    while True:
        candidate = f"{prefix}_{candidate_idx}"
        if re.search(rf"\b{re.escape(candidate)}\b", source) is None:
            return candidate
        candidate_idx += 1


def _clean_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _simple_identifier(value: str) -> bool:
    return _IDENT_RE.match(value) is not None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None
