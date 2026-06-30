"""Source probes derived from register window-order fallback leads."""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.mwcc_debug.pressure_explorer import LifetimeLayoutProbe
from src.mwcc_debug.source_field_attribution import (
    build_source_field_context,
    source_for_field_offset,
)
from src.mwcc_debug.source_hunks import diff_line_hunks
from src.search import statement_move


_UNSAFE_LABEL_CHARS_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_SYNTHETIC_NO_SOURCE_KINDS = {"implicit-temp", "copy/coalesce-product"}
_VIRTUAL_OPERAND_RE = re.compile(r"(?<![A-Za-z0-9_])([rf])(\d+)\b")
_GPR_COPY_PRODUCT_RE = re.compile(
    r"^\s*mr\s+r(?P<dest>\d+)\s*,\s*r(?P<src>\d+)\s*$",
    re.IGNORECASE,
)
_SIMPLE_ASSIGN_RE = re.compile(
    r"^(?P<indent>\s*)(?P<lhs>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.+?)\s*;\s*(?://.*)?$",
    re.DOTALL,
)
_UNSAFE_SPLIT_RHS_RE = re.compile(r"\+\+|--|\?|,|\b[A-Za-z_]\w*\s*\(")
_SIMPLE_TERM_RE = re.compile(
    r"(?:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*|(?:\d+(?:\.\d*)?|\.\d+)[fF]?)"
)
_CASTED_SIMPLE_TERM_RE = re.compile(
    rf"\(\s*[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*\s*\)\s*{_SIMPLE_TERM_RE.pattern}"
)
_FLOAT_EXPR_TERM_RE = re.compile(
    rf"(?:{_CASTED_SIMPLE_TERM_RE.pattern}|{_SIMPLE_TERM_RE.pattern})"
)
_LOCAL_FLOAT_BINARY_EXPR_RE = re.compile(
    rf"\s*{_FLOAT_EXPR_TERM_RE.pattern}\s*(?:[+\-*])\s*"
    rf"{_FLOAT_EXPR_TERM_RE.pattern}\s*"
)
_LOCAL_FLOAT_FORBIDDEN_RHS_RE = re.compile(
    r"\+\+|--|->|\[|\]|&|\?|,|\b[A-Za-z_]\w*\s*\("
)
_CAST_TYPE_RE = re.compile(r"^\(\s*(?P<type>[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*)\s*\)")
_FLOAT_DECL_TYPES = {"f32", "float", "double"}
_TYPE_QUALIFIERS = {"const", "register", "restrict", "static", "volatile"}
_GOBJ_USER_DATA_OFFSET = 0x2C
_FIELD_AT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<base>[A-Za-z_]\w*)\s*(?P<op>->|\.)\s*"
    r"field_at_0x(?P<offset>[0-9A-Fa-f]+)(?![A-Za-z0-9_])"
)
_LI_EXPRESSION_RE = re.compile(
    r"\bli\b\s+r\d+\s*,\s*(?P<imm>-?(?:0x[0-9A-Fa-f]+|\d+))\s*$",
    re.IGNORECASE,
)
_LI_OPERANDS_RE = re.compile(
    r"^\s*r\d+\s*,\s*(?P<imm>-?(?:0x[0-9A-Fa-f]+|\d+))\s*$",
    re.IGNORECASE,
)
_INT_LITERAL_RE = re.compile(r"-?(?:0x[0-9A-Fa-f]+|\d+)")
_LI_DECL_INIT_RE = re.compile(
    r"^(?P<indent>\s*)(?P<type>(?:[A-Za-z_]\w*|\s|\*)+?)"
    r"\s+(?P<local>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.+?)\s*;\s*(?://.*)?$"
)
_POINTER_WALK_ADD_RE = re.compile(
    r"(?P<argument>"
    r"\(\s*(?P<cast_type>[^()]+?\*+)\s*\)\s*"
    r"\(\s*\(\s*(?P<byte_pointer_cast>u8|char|unsigned\s+char)\s*\*\s*\)"
    r"\s*(?P<base>[A-Za-z_]\w*)\s*\+\s*"
    r"\(\s*(?P<index>[^()]+?)\s*<<\s*(?P<shift>\d+)\s*\)"
    r"\s*\+\s*(?P<offset>-?(?:0x[0-9A-Fa-f]+|\d+))\s*\)"
    r")"
)
_SIMPLE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$")
_LOAD_OPCODE_PREFIXES = ("lb", "lh", "lw", "lf", "lmw")


@dataclass(frozen=True)
class _VirtualExpression:
    opcode: str
    dest: int | None
    sources: tuple[int, ...]


@dataclass(frozen=True)
class _CopyProductSource:
    source_ig: int
    parsed_source_ig: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _OwnerAssignment:
    group: statement_move.SiblingGroup
    sibling: statement_move.SiblingStmt
    local_name: str
    rhs: str
    indent: str
    split_expression: str | None = None


@dataclass(frozen=True)
class _SyntheticOwnerCandidate:
    owner: _OwnerAssignment | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _SyntheticOwnerResult:
    candidates: tuple[_SyntheticOwnerCandidate, ...]
    metadata: dict[str, Any]
    terminal_blocker: str | None


@dataclass(frozen=True)
class _LocalLifetimeProbeCandidate:
    source_text: str
    metadata: dict[str, Any]
    provenance_kind: str


@dataclass(frozen=True)
class _AlternateOwnerNode:
    source_expression: str
    current_source_expression: str
    relation: str
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class _AlternateOwnerCandidate:
    source_expression: str
    source_type: str
    relation: str
    score: int
    current_span: Mapping[str, Any]


@dataclass(frozen=True)
class _AlternateOwnerProof:
    inspected_owner_nodes: list[dict[str, Any]]
    rejected_owner_nodes: list[dict[str, Any]]


@dataclass(frozen=True)
class _IndexedRepairAddressMatch:
    array_base: str
    requested_index_expr: str
    source_index_expr: str
    canonical_index_expr: str
    value_index_expr: str
    requested_expression: str
    source_expression: str
    line_start: int
    line_end: int
    line: str
    expression_start: int
    expression_end: int


@dataclass(frozen=True)
class _FieldLoadSourceCandidate:
    base_var: str
    field_offset: int | None
    field_name: str | None
    expression: str
    source_span: tuple[int, int]
    source_line: int | None
    owner_local: str | None
    owner_type: str | None
    kind: str
    line_source_span: tuple[int, int]
    line_text: str


@dataclass(frozen=True)
class WindowOrderSourceProbePlan:
    probes: list[LifetimeLayoutProbe]
    lead_diagnostics: list[dict[str, Any]]


def _safe_label_part(value: object) -> str:
    cleaned = _UNSAFE_LABEL_CHARS_RE.sub("-", str(value).strip())
    return cleaned.strip("-") or "unknown"


def _attr_value(source_attr: Any, key: str) -> Any:
    if isinstance(source_attr, Mapping):
        return source_attr.get(key)
    return getattr(source_attr, key, None)


def _source_attr_jsonish(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _source_attr_jsonish(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_source_attr_jsonish(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _source_attr_jsonish(getattr(value, key, None))
            for key in value.__dataclass_fields__
        }
    if hasattr(value, "__dict__") and value.__class__.__module__.startswith("src."):
        return {
            key: _source_attr_jsonish(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return value


def _source_attr_dict(source_attr: Any) -> dict[str, Any]:
    if isinstance(source_attr, Mapping):
        return {
            str(key): _source_attr_jsonish(value)
            for key, value in source_attr.items()
        }
    payload = {
        key: getattr(source_attr, key, None)
        for key in (
            "kind",
            "name",
            "type",
            "source_file",
            "source_line",
            "source_col",
            "expression",
            "first_def",
            "base_virtual",
            "base_var",
            "field_offset",
            "field_name",
            "confidence",
            "base_confidence",
            "call_symbol",
            "copy_chain",
        )
        if hasattr(source_attr, key)
    }
    return {key: _source_attr_jsonish(value) for key, value in payload.items()}


def _source_attr_for_ig(
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None,
    target_ig: int,
) -> Any | None:
    if source_attributions is None:
        return None
    if target_ig in source_attributions:
        return source_attributions[target_ig]  # type: ignore[index]
    key = str(target_ig)
    if key in source_attributions:
        return source_attributions[key]  # type: ignore[index]
    return None


def _source_attr_first_def_operands(source_attr: Any) -> str | None:
    first_def = _attr_value(source_attr, "first_def")
    if isinstance(first_def, Mapping):
        operands = first_def.get("operands")
        return operands if isinstance(operands, str) else None
    operands = getattr(first_def, "operands", None)
    return operands if isinstance(operands, str) else None


def _virtual_operand_ids(text: str | None) -> tuple[int, ...]:
    if not isinstance(text, str):
        return ()
    return tuple(int(value) for _, value in _VIRTUAL_OPERAND_RE.findall(text))


def _lead_target_ig(lead: Mapping[str, Any]) -> int | None:
    try:
        return int(lead["target_ig"])
    except (KeyError, TypeError, ValueError):
        return None


def _lead_direction(lead: Mapping[str, Any]) -> str | None:
    order_move = lead.get("order_move")
    if (
        not isinstance(order_move, list | tuple)
        or len(order_move) < 2
        or order_move[0] not in {"before", "after"}
    ):
        return None
    return str(order_move[0])


def _candidate_destinations(
    *,
    direction: str,
    unit: statement_move.MoveUnit,
    legal: Iterable[int],
) -> list[int]:
    lo, hi = unit.index_range
    if direction == "before":
        return sorted((dest for dest in legal if dest < lo))
    if direction == "after":
        return sorted((dest for dest in legal if dest > hi + 1), reverse=True)
    return []


def _source_diff(before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="source",
            tofile="window-order-source-probe",
        )
    )


def _matching_brace_index(source_text: str, open_brace_index: int) -> int | None:
    depth = 0
    for index in range(open_brace_index, len(source_text)):
        char = source_text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _remove_increment_term(increment: str, local_name: str) -> tuple[str, str] | None:
    parts = [part.strip() for part in increment.split(",")]
    kept: list[str] = []
    removed: str | None = None
    local_re = re.escape(local_name)
    increment_re = re.compile(rf"(?:{local_re}\s*\+\+|\+\+\s*{local_re})$")
    for part in parts:
        if removed is None and increment_re.fullmatch(part):
            removed = part
            continue
        if part:
            kept.append(part)
    if removed is None:
        return None
    return ", ".join(kept), removed


def _line_indent_at(source_text: str, index: int) -> str:
    line_start = source_text.rfind("\n", 0, index) + 1
    match = re.match(r"[ \t]*", source_text[line_start:index])
    return match.group(0) if match is not None else ""


def _function_body_span(source_text: str, function: str) -> tuple[int, int] | None:
    body, source_bytes = statement_move._body_node(source_text, function)
    if body is None or source_bytes is None:
        return None
    start = len(source_bytes[:body.start_byte].decode("utf-8"))
    end = len(source_bytes[:body.end_byte].decode("utf-8"))
    return start, end


def _pointer_walk_increment_sink_candidates(
    source_text: str,
    local_name: str,
    *,
    search_span: tuple[int, int] | None = None,
) -> list[_LocalLifetimeProbeCandidate]:
    candidates: list[_LocalLifetimeProbeCandidate] = []
    search_start, search_end = search_span or (0, len(source_text))
    search_start = max(0, min(search_start, len(source_text)))
    search_end = max(search_start, min(search_end, len(source_text)))
    search_text = source_text[search_start:search_end]
    for match in re.finditer(
        r"for\s*\((?P<header>[^()]*)\)\s*\{",
        search_text,
        flags=re.MULTILINE,
    ):
        match_start = search_start + match.start()
        match_end = search_start + match.end()
        header = match.group("header")
        header_parts = header.split(";", 2)
        if len(header_parts) != 3:
            continue
        init, condition, increment = (part.strip() for part in header_parts)
        removed = _remove_increment_term(increment, local_name)
        if removed is None:
            continue
        new_increment, removed_increment = removed
        open_brace = source_text.find("{", match_start, match_end)
        if open_brace < 0:
            continue
        close_brace = _matching_brace_index(source_text, open_brace)
        if close_brace is None or close_brace > search_end:
            continue
        body_text = source_text[open_brace + 1:close_brace]
        if re.search(r"(?<![A-Za-z0-9_])continue\s*;", body_text):
            continue

        new_header = f"for ({init}; {condition}; {new_increment}) {{"
        index_match = re.search(
            r"(?:[A-Za-z_]\w*(?:\s*\*)?\s+)?(?P<index>[A-Za-z_]\w*)\s*=",
            init,
        )
        index_name = index_match.group("index") if index_match else None
        base_name = None
        assign_re = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(local_name)}\s*=\s*"
            rf"(?P<base>[A-Za-z_]\w*)\s*;"
        )
        for assign_match in assign_re.finditer(source_text, search_start, match_start):
            base_name = assign_match.group("base")
        close_line_start = source_text.rfind("\n", 0, close_brace) + 1
        close_indent = _line_indent_at(source_text, close_brace)
        body_indent = f"{close_indent}    "
        insertion = f"{body_indent}{local_name}++;\n"
        candidate_text = (
            source_text[:match_start]
            + new_header
            + source_text[match_end:close_line_start]
            + insertion
            + source_text[close_line_start:]
        )
        if candidate_text == source_text:
            continue
        candidates.append(
            _LocalLifetimeProbeCandidate(
                source_text=candidate_text,
                provenance_kind="window-order-local-pointer-walk-source-move",
                metadata={
                    "handler": "pointer-walk-increment-sink",
                    "local": local_name,
                    "removed_increment": removed_increment,
                    "rewritten_increment": new_increment,
                },
            )
        )
        if index_name is not None and base_name is not None:
            deref_re = re.compile(
                rf"(?<![A-Za-z0-9_])\*{re.escape(local_name)}\s*="
            )
            deref_match = deref_re.search(body_text)
            if deref_match is not None:
                deref_start = open_brace + 1 + deref_match.start()
                deref_end = open_brace + 1 + deref_match.end()
                indexed_lhs = f"{base_name}[{index_name}] ="
                indexed_text = (
                    source_text[:match_start]
                    + new_header
                    + source_text[match_end:deref_start]
                    + indexed_lhs
                    + source_text[deref_end:]
                )
                if indexed_text != source_text:
                    candidates.append(
                        _LocalLifetimeProbeCandidate(
                            source_text=indexed_text,
                            provenance_kind=(
                                "window-order-local-pointer-walk-indexed-write"
                            ),
                            metadata={
                                "handler": "pointer-walk-indexed-write",
                                "local": local_name,
                                "base": base_name,
                                "index": index_name,
                                "removed_increment": removed_increment,
                                "rewritten_increment": new_increment,
                            },
                        )
                    )

                body_insert = source_text.find("\n", match_end, close_brace)
                body_insert = body_insert + 1 if body_insert >= 0 else match_end
                rebind = f"{body_indent}{local_name} = &{base_name}[{index_name}];\n"
                rebind_text = (
                    source_text[:match_start]
                    + new_header
                    + source_text[match_end:body_insert]
                    + rebind
                    + source_text[body_insert:]
                )
                if rebind_text != source_text:
                    candidates.append(
                        _LocalLifetimeProbeCandidate(
                            source_text=rebind_text,
                            provenance_kind=(
                                "window-order-local-pointer-walk-indexed-rebind"
                            ),
                            metadata={
                                "handler": "pointer-walk-indexed-rebind",
                                "local": local_name,
                                "base": base_name,
                                "index": index_name,
                                "removed_increment": removed_increment,
                                "rewritten_increment": new_increment,
                            },
                        )
                    )
    return candidates


def _parse_virtual_expression(expression: object) -> _VirtualExpression | None:
    if not isinstance(expression, str):
        return None
    parts = expression.strip().split(None, 1)
    if len(parts) != 2:
        return None
    opcode = parts[0].lower()
    operands = [
        (kind, int(value))
        for kind, value in _VIRTUAL_OPERAND_RE.findall(parts[1])
    ]
    if not operands:
        return None
    dest = operands[0][1]
    sources = tuple(value for _, value in operands[1:])
    return _VirtualExpression(opcode=opcode, dest=dest, sources=sources)


def _source_attr_base_virtual(source_attr: Any) -> int | None:
    raw = _attr_value(source_attr, "base_virtual")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and raw >= 0:
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def _gpr_copy_product_source(
    source_attr: Any,
    *,
    target_ig: int,
) -> _CopyProductSource | None:
    expression = _attr_value(source_attr, "expression")
    if not isinstance(expression, str):
        return None
    match = _GPR_COPY_PRODUCT_RE.fullmatch(expression)
    if match is None:
        return None
    dest_ig = int(match.group("dest"))
    if dest_ig != target_ig:
        return None
    parsed_source_ig = int(match.group("src"))
    base_virtual = _source_attr_base_virtual(source_attr)
    source_ig = base_virtual if base_virtual is not None else parsed_source_ig
    metadata: dict[str, Any] = {
        "copy_product_handler": "copy-product-source-owner-discovery",
        "copy_product_expression": expression,
        "copy_product_target_ig": target_ig,
        "copy_product_parsed_source_ig": parsed_source_ig,
        "copy_product_source_ig": source_ig,
    }
    if base_virtual is not None:
        metadata["copy_product_base_virtual"] = base_virtual
    return _CopyProductSource(
        source_ig=source_ig,
        parsed_source_ig=parsed_source_ig,
        metadata=metadata,
    )


def _line_bounds(source_bytes: bytes, start: int, end: int) -> tuple[int, int]:
    line_start = source_bytes.rfind(b"\n", 0, start) + 1
    line_end = source_bytes.find(b"\n", end)
    if line_end == -1:
        line_end = len(source_bytes)
    else:
        line_end += 1
    return line_start, line_end


def _line_span_payload(
    source_text: str,
    start: int,
    end: int,
    *,
    kind: str,
    priority: int,
    **metadata: Any,
) -> dict[str, Any]:
    start = max(0, min(start, len(source_text)))
    end = max(start, min(end, len(source_text)))
    line_start_index = source_text.rfind("\n", 0, start) + 1
    line_end_index = source_text.find("\n", end)
    if line_end_index < 0:
        line_end_index = len(source_text)
    line_start = source_text.count("\n", 0, line_start_index) + 1
    line_end = source_text.count("\n", 0, line_end_index) + 1
    byte_start = len(source_text[:start].encode("utf-8"))
    byte_end = len(source_text[:end].encode("utf-8"))
    line_byte_start = len(source_text[:line_start_index].encode("utf-8"))
    line_byte_end = len(source_text[:line_end_index].encode("utf-8"))
    payload = {
        "kind": kind,
        "rank_priority": priority,
        "line_start": line_start,
        "line_end": line_end,
        "source_start": start,
        "source_end": end,
        "source_span": [start, end],
        "byte_start": byte_start,
        "byte_end": byte_end,
        "byte_span": [byte_start, byte_end],
        "line_source_start": line_start_index,
        "line_source_end": line_end_index,
        "line_source_span": [line_start_index, line_end_index],
        "line_byte_start": line_byte_start,
        "line_byte_end": line_byte_end,
        "line_byte_span": [line_byte_start, line_byte_end],
        "span_text": source_text[line_start_index:line_end_index].strip(),
    }
    payload.update(metadata)
    return payload


def _line_records_in_span(
    source_text: str,
    search_span: tuple[int, int],
) -> list[tuple[int, int, str]]:
    search_start, search_end = search_span
    search_start = max(0, min(search_start, len(source_text)))
    search_end = max(search_start, min(search_end, len(source_text)))
    records: list[tuple[int, int, str]] = []
    cursor = search_start
    while cursor < search_end:
        line_end = source_text.find("\n", cursor, search_end)
        if line_end < 0:
            line_end = search_end
            next_cursor = search_end
        else:
            next_cursor = line_end + 1
        records.append((cursor, line_end, source_text[cursor:line_end]))
        cursor = next_cursor
    return records


def _line_bounds_from_candidate(
    source_text: str,
    candidate: Mapping[str, Any],
) -> tuple[int, int, str] | None:
    try:
        start = int(candidate["line_source_start"])
        end = int(candidate["line_source_end"])
    except (KeyError, TypeError, ValueError):
        return None
    start = max(0, min(start, len(source_text)))
    end = max(start, min(end, len(source_text)))
    return start, end, source_text[start:end]


def _candidate_materialization_diagnostic(
    candidate: Mapping[str, Any],
    *,
    status: str,
    reason: str | None = None,
    probe_label: str | None = None,
    handler: str | None = None,
) -> dict[str, Any]:
    payload = {
        key: candidate.get(key)
        for key in (
            "rank",
            "kind",
            "rank_priority",
            "line_start",
            "line_end",
            "span_text",
            "source_start",
            "source_end",
            "source_span",
            "byte_start",
            "byte_end",
            "byte_span",
            "line_source_start",
            "line_source_end",
            "line_source_span",
            "line_byte_start",
            "line_byte_end",
            "line_byte_span",
            "array_base",
            "index_expr",
            "target_local",
            "local",
            "expression_text",
            "end_local",
            "iter_local",
            "owner_rhs",
            "base_expression",
            "offset_expression",
            "owner_assignment_text",
            "loop_header_text",
            "candidate_rejection_reason",
            "immediate_value",
            "literal_text",
            "literal_value",
            "owner_local",
            "paired_literal",
            "paired_assignment_text",
            "callee",
            "argument_index",
            "argument_text",
            "cast_type",
            "byte_pointer_cast",
            "shift",
            "scale_bytes",
            "offset_value",
        )
        if key in candidate
    }
    payload["status"] = status
    if reason:
        payload["reason"] = reason
    if probe_label:
        payload["probe_label"] = probe_label
    if handler:
        payload["handler"] = handler
    return payload


def _candidate_reason_counts(
    diagnostics: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for diagnostic in diagnostics:
        reason = diagnostic.get("reason")
        if isinstance(reason, str) and reason:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def _window_order_probe_local_name(source_text: str, stem: str) -> str:
    cleaned = _safe_label_part(stem).replace("-", "_").replace(".", "_")
    base = f"window_order_{cleaned}_probe"
    candidate = base
    index = 2
    while re.search(rf"\b{re.escape(candidate)}\b", source_text):
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _target_repair_probe_local_name(
    source_text: str,
    stem: str,
    *,
    reserved: set[str] | None = None,
) -> str:
    cleaned = _safe_label_part(stem).replace("-", "_").replace(".", "_")
    base = f"target_repair_{cleaned}_probe"
    candidate = base
    index = 2
    while (
        re.search(rf"\b{re.escape(candidate)}\b", source_text)
        or (reserved is not None and candidate in reserved)
    ):
        candidate = f"{base}_{index}"
        index += 1
    if reserved is not None:
        reserved.add(candidate)
    return candidate


def _function_decl_insertion(
    source_text: str,
    function: str,
) -> tuple[int, str] | None:
    body, source_bytes = statement_move._body_node(source_text, function)
    if body is None or source_bytes is None:
        return None
    last_decl_line_end: int | None = None
    decl_indent = "    "
    for child in body.named_children:
        if child.type == "comment":
            continue
        if child.type != "declaration":
            break
        line_start, line_end = _line_bounds(
            source_bytes,
            child.start_byte,
            child.end_byte,
        )
        line = source_bytes[line_start:line_end].decode("utf-8")
        indent_match = re.match(r"[ \t]*", line)
        if indent_match is not None:
            decl_indent = indent_match.group(0)
        last_decl_line_end = len(source_bytes[:line_end].decode("utf-8"))
    if last_decl_line_end is not None:
        return last_decl_line_end, decl_indent

    body_start = len(source_bytes[:body.start_byte].decode("utf-8"))
    body_end = len(source_bytes[:body.end_byte].decode("utf-8"))
    newline = source_text.find("\n", body_start, body_end)
    if newline >= 0:
        return newline + 1, f"{_line_indent_at(source_text, body_start)}    "
    return body_start + 1, f"{_line_indent_at(source_text, body_start)}    "


def _safe_decl_type_text(type_text: object) -> str | None:
    if not isinstance(type_text, str):
        return None
    normalized = " ".join(type_text.replace("\t", " ").split())
    if not normalized:
        return None
    if any(char in normalized for char in "[]();,{}"):
        return None
    if re.search(r"\bvolatile\b", normalized):
        return None
    return normalized


def _decl_type_from_ranked_candidates(
    local_name: str,
    candidates: Iterable[Mapping[str, Any]],
) -> str | None:
    local_re = re.escape(local_name)
    decl_re = re.compile(
        rf"^\s*(?P<type>.+?)(?<![A-Za-z0-9_]){local_re}"
        rf"\s*(?:=[^,;]+)?;\s*(?://.*)?$"
    )
    for candidate in candidates:
        if candidate.get("kind") != "loop-index-declaration":
            continue
        span_text = candidate.get("span_text")
        if not isinstance(span_text, str):
            continue
        match = decl_re.match(span_text)
        if match is None:
            continue
        type_text = _safe_decl_type_text(match.group("type"))
        if type_text is not None:
            return type_text
    return None


def _line_has_unsafe_label_or_preprocessor(stripped: str) -> bool:
    return (
        stripped.startswith("#")
        or re.match(r"^[A-Za-z_]\w*\s*:", stripped) is not None
    )


def _line_has_unsafe_function_call(stripped: str) -> bool:
    for call in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", stripped):
        if call.group(1) in {"if", "for", "while", "switch", "sizeof"}:
            continue
        return True
    return False


def _plain_assignment_to_local(stripped: str, local_name: str) -> bool:
    local_re = re.escape(local_name)
    return (
        re.match(rf"^{local_re}\s*(?:=|\+=|-=|\*=|/=|%=|&=|\|=|\^=)", stripped)
        is not None
    )


def _replace_local_reads_in_line(
    line: str,
    *,
    local_name: str,
    replacement: str,
) -> tuple[str, int]:
    local_re = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(local_name)}(?![A-Za-z0-9_])")
    return local_re.subn(replacement, line)


def _materialize_loop_index_read_anchor(
    source_text: str,
    *,
    function: str,
    local_name: str,
    decl_type: str,
    candidate: Mapping[str, Any],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "loop-index-read-anchor"
    kind = candidate.get("kind")
    if kind == "loop-index-declaration":
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="non-executable-declaration-span",
            handler=handler,
        )
    line_bounds = _line_bounds_from_candidate(source_text, candidate)
    if line_bounds is None:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="missing-source-span",
            handler=handler,
        )
    line_start, line_end, line = line_bounds
    stripped = line.strip()
    if not stripped:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="empty-source-span",
            handler=handler,
        )
    if _line_has_unsafe_label_or_preprocessor(stripped):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="unsafe-executable-line",
            handler=handler,
        )
    if stripped.startswith("for"):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="unsupported-loop-header-owner",
            handler=handler,
        )
    if kind != "loop-body-read":
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="diagnostic_only",
            reason="unsupported-ranked-local-owner-kind",
            handler=handler,
        )
    if "++" in stripped or "--" in stripped or _plain_assignment_to_local(
        stripped,
        local_name,
    ):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="local-write-or-mutation",
            handler=handler,
        )
    if _line_has_unsafe_function_call(stripped):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="unsafe-function-call-line",
            handler=handler,
        )
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="source-ast-unavailable",
            handler=handler,
        )
    decl_index, decl_indent = insertion
    if decl_index > line_start:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="declaration-anchor-after-use",
            handler=handler,
        )
    temp_name = _window_order_probe_local_name(source_text, local_name)
    rewritten_line, replacements = _replace_local_reads_in_line(
        line,
        local_name=local_name,
        replacement=temp_name,
    )
    if replacements <= 0 or rewritten_line == line:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="local-read-not-found",
            handler=handler,
        )
    indent = re.match(r"[ \t]*", line).group(0)
    edits = [
        (line_start, line_end, f"{indent}{temp_name} = {local_name};\n{rewritten_line}"),
        (decl_index, decl_index, f"{decl_indent}{decl_type} {temp_name};\n"),
    ]
    candidate_text = source_text
    for start, end, replacement in sorted(edits, reverse=True):
        candidate_text = candidate_text[:start] + replacement + candidate_text[end:]
    if candidate_text == source_text:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="source-unchanged",
            handler=handler,
        )
    metadata = {
        "handler": handler,
        "owner_local": local_name,
        "synthetic_local": temp_name,
        "type": decl_type,
        "line_range": [
            int(candidate.get("line_start") or 0),
            int(candidate.get("line_end") or 0),
        ],
        "ranked_source_owner_candidate": dict(candidate),
        "replacements": replacements,
    }
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="window-order-ranked-local-owner-source-probe",
            metadata=metadata,
        ),
        _candidate_materialization_diagnostic(
            candidate,
            status="materialized",
            handler=handler,
        ),
    )


def _matching_bracket_index(text: str, open_index: int) -> int | None:
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
    return None


def _indexed_expression_spans(line: str) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for bracket in [match.start() for match in re.finditer(r"\[", line)]:
        close = _matching_bracket_index(line, bracket)
        if close is None:
            continue
        base_match = re.search(
            r"(?P<base>[A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)*)\s*$",
            line[:bracket],
        )
        if base_match is None:
            continue
        start = base_match.start("base")
        base = re.sub(r"\s+", "", base_match.group("base"))
        index_expr = line[bracket + 1:close].strip()
        if not base or not index_expr:
            continue
        spans.append({
            "start": start,
            "end": close + 1,
            "array_base": base,
            "index_expr": index_expr,
            "expression_text": line[start:close + 1],
        })
    return spans


def _is_array_declarator_line(stripped: str, array_base: str) -> bool:
    if not stripped.endswith(";"):
        return False
    if "=" in stripped:
        return False
    base_re = re.escape(array_base.split("->")[-1].split(".")[-1])
    return re.match(
        rf"^(?:[A-Za-z_]\w*|\s|\*|const|static|unsigned|signed)+"
        rf"\b{base_re}\s*\[[^\]]+\]\s*;",
        stripped,
    ) is not None


def _safe_index_temp_expression(index_expr: str) -> bool:
    if not index_expr.strip():
        return False
    if re.search(r"=|\+\+|--|\?|,|;|\b[A-Za-z_]\w*\s*\(", index_expr):
        return False
    return True


def _line_can_host_index_temp_assignment(stripped: str) -> bool:
    if re.match(r"(?:if|while|return)\b", stripped):
        return True
    if re.match(r"[A-Za-z_]\w*\s*=", stripped):
        return True
    if re.match(r"[A-Za-z_]\w*\s*\[[^\]]+\]\s*=", stripped):
        return True
    if re.match(r"\*[A-Za-z_]\w*\s*=", stripped):
        return True
    return False


def _index_temp_assignment_line_blocker(stripped: str) -> str:
    if re.match(r"[A-Za-z_]\w*\s*\[", stripped):
        return "expression-context-indexed-expression"
    return "continuation-line-indexed-expression"


def _materialize_indexed_byte_candidate(
    source_text: str,
    *,
    function: str,
    candidate: Mapping[str, Any],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "indexed-byte-ranked-candidate"
    line_bounds = _line_bounds_from_candidate(source_text, candidate)
    if line_bounds is None:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="missing-source-span",
            handler=handler,
        )
    line_start, line_end, line = line_bounds
    stripped = line.strip()
    array_base = candidate.get("array_base")
    index_expr = candidate.get("index_expr")
    if not isinstance(array_base, str) or not isinstance(index_expr, str):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="missing-indexed-expression",
            handler=handler,
        )
    if (
        candidate.get("is_array_declarator") is True
        or _is_array_declarator_line(stripped, array_base)
    ):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="array-declarator-not-indexed-expression",
            handler=handler,
        )
    if candidate.get("kind") != "indexed-byte-address-temp":
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="diagnostic_only",
            reason="unsupported-ranked-indexed-byte-kind",
            handler=handler,
        )
    if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="unsafe-executable-line",
            handler=handler,
        )
    if stripped.startswith("for"):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="unsupported-loop-header-owner",
            handler=handler,
        )
    if not _line_can_host_index_temp_assignment(stripped):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason=_index_temp_assignment_line_blocker(stripped),
            handler=handler,
        )
    try:
        expr_start = int(candidate["source_start"])
        expr_end = int(candidate["source_end"])
    except (KeyError, TypeError, ValueError):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="missing-source-span",
            handler=handler,
        )
    expr_start = max(line_start, min(expr_start, line_end))
    expr_end = max(expr_start, min(expr_end, line_end))
    expression_text = source_text[expr_start:expr_end]
    expected_text = candidate.get("expression_text")
    if isinstance(expected_text, str) and expression_text != expected_text:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="stale-source-span",
            handler=handler,
        )
    prefix = source_text[line_start:expr_start]
    if prefix.rstrip().endswith("&"):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="address-of-indexed-expression-unsupported",
            handler=handler,
        )
    if not _safe_index_temp_expression(index_expr):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="unsafe-index-expression",
            handler=handler,
        )
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="source-ast-unavailable",
            handler=handler,
        )
    decl_index, decl_indent = insertion
    if decl_index > line_start:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="declaration-anchor-after-use",
            handler=handler,
        )
    temp_stem = f"{array_base.replace('->', '_').replace('.', '_')}_index"
    temp_name = _window_order_probe_local_name(source_text, temp_stem)
    rewritten_expr = f"{array_base}[{temp_name}]"
    rewritten_line = (
        source_text[line_start:expr_start]
        + rewritten_expr
        + source_text[expr_end:line_end]
    )
    if rewritten_line == line:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="source-unchanged",
            handler=handler,
        )
    indent = re.match(r"[ \t]*", line).group(0)
    edits = [
        (line_start, line_end, f"{indent}{temp_name} = {index_expr};\n{rewritten_line}"),
        (decl_index, decl_index, f"{decl_indent}int {temp_name};\n"),
    ]
    candidate_text = source_text
    for start, end, replacement in sorted(edits, reverse=True):
        candidate_text = candidate_text[:start] + replacement + candidate_text[end:]
    if candidate_text == source_text:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="source-unchanged",
            handler=handler,
        )
    metadata = {
        "handler": handler,
        "array_base": array_base,
        "index_expr": index_expr,
        "synthetic_local": temp_name,
        "rewritten_expression": rewritten_expr,
        "line_range": [
            int(candidate.get("line_start") or 0),
            int(candidate.get("line_end") or 0),
        ],
        "ranked_indexed_byte_source_candidate": dict(candidate),
    }
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="window-order-ranked-indexed-byte-source-probe",
            metadata=metadata,
        ),
        _candidate_materialization_diagnostic(
            candidate,
            status="materialized",
            handler=handler,
        ),
    )


def _materialize_end_pointer_candidate(
    source_text: str,
    *,
    function: str,
    candidate: Mapping[str, Any],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "pcode-addi-end-pointer-owner"
    rejection_reason = candidate.get("candidate_rejection_reason")
    if isinstance(rejection_reason, str) and rejection_reason:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason=rejection_reason,
            handler=handler,
        )
    line_bounds = _line_bounds_from_candidate(source_text, candidate)
    if line_bounds is None:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="missing-source-span",
            handler=handler,
        )
    line_start, line_end, line = line_bounds
    stripped = line.strip()
    if candidate.get("kind") != "pointer-loop-end-pointer":
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="diagnostic_only",
            reason="unsupported-ranked-end-pointer-kind",
            handler=handler,
        )
    if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="unsafe-executable-line",
            handler=handler,
        )
    end_local = candidate.get("end_local")
    owner_rhs = candidate.get("owner_rhs")
    declaration_type = candidate.get("declaration_type")
    if (
        not isinstance(end_local, str)
        or not isinstance(owner_rhs, str)
        or not isinstance(declaration_type, str)
    ):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="missing-end-pointer-owner",
            handler=handler,
        )
    if not _safe_end_pointer_expression(owner_rhs):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="unsafe-end-pointer-expression",
            handler=handler,
        )
    indent = re.match(r"[ \t]*", line).group(0)
    assignment_kind = candidate.get("assignment_kind")
    candidate_text: str | None = None
    synthetic_local: str | None = None
    rewritten_rhs = owner_rhs
    if assignment_kind == "declaration-init":
        expected = _POINTER_DECL_RE.match(line)
        if expected is None or expected.group("local") != end_local:
            return None, _candidate_materialization_diagnostic(
                candidate,
                status="rejected",
                reason="stale-source-span",
                handler=handler,
            )
        replacement = (
            f"{indent}{declaration_type} {end_local};\n"
            f"{indent}{end_local} = {owner_rhs};\n"
        )
        candidate_text = (
            source_text[:line_start] + replacement + source_text[line_end:]
        )
    elif assignment_kind == "assignment":
        split_rhs = _split_end_pointer_rhs(owner_rhs)
        if split_rhs is None:
            return None, _candidate_materialization_diagnostic(
                candidate,
                status="rejected",
                reason="unsafe-end-pointer-expression",
                handler=handler,
            )
        base_expression, offset_expression = split_rhs
        insertion = _function_decl_insertion(source_text, function)
        if insertion is None:
            return None, _candidate_materialization_diagnostic(
                candidate,
                status="rejected",
                reason="source-ast-unavailable",
                handler=handler,
            )
        decl_index, decl_indent = insertion
        if decl_index > line_start:
            return None, _candidate_materialization_diagnostic(
                candidate,
                status="rejected",
                reason="declaration-anchor-after-use",
                handler=handler,
            )
        synthetic_local = _window_order_probe_local_name(source_text, "end_base")
        rewritten_rhs = f"{synthetic_local} + {offset_expression}"
        replacement = (
            f"{indent}{synthetic_local} = {base_expression};\n"
            f"{indent}{end_local} = {rewritten_rhs};\n"
        )
        edits = [
            (line_start, line_end, replacement),
            (
                decl_index,
                decl_index,
                f"{decl_indent}{declaration_type} {synthetic_local};\n",
            ),
        ]
        candidate_text = source_text
        for start, end, replacement_text in sorted(edits, reverse=True):
            candidate_text = (
                candidate_text[:start] + replacement_text + candidate_text[end:]
            )
    else:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="diagnostic_only",
            reason="unsupported-end-pointer-assignment-kind",
            handler=handler,
        )
    if candidate_text == source_text:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="source-unchanged",
            handler=handler,
        )
    metadata = {
        "handler": handler,
        "end_local": end_local,
        "iter_local": candidate.get("iter_local"),
        "owner_rhs": owner_rhs,
        "rewritten_rhs": rewritten_rhs,
        "base_expression": candidate.get("base_expression"),
        "offset_expression": candidate.get("offset_expression"),
        "synthetic_local": synthetic_local,
        "line_range": [
            int(candidate.get("line_start") or 0),
            int(candidate.get("line_end") or 0),
        ],
        "ranked_end_pointer_source_candidate": dict(candidate),
    }
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="window-order-ranked-end-pointer-source-probe",
            metadata=metadata,
        ),
        _candidate_materialization_diagnostic(
            candidate,
            status="materialized",
            handler=handler,
        ),
    )


def _parse_field_offset(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            return int(text, 0)
        except ValueError:
            return None
    return None


def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _function_header_text(source_text: str, function: str) -> str | None:
    body, source_bytes = statement_move._body_node(source_text, function)
    if body is None or source_bytes is None:
        return None
    body_start = len(source_bytes[:body.start_byte].decode("utf-8"))
    name_pos = source_text.rfind(function, 0, body_start)
    if name_pos < 0:
        return None
    header_start = source_text.rfind("\n", 0, name_pos) + 1
    return source_text[header_start:body_start]


def _declaration_type_for_name(declaration: str, name: str) -> str | None:
    name_re = re.escape(name)
    match = re.search(
        rf"^(?P<type>.+?)(?<![A-Za-z0-9_]){name_re}"
        rf"(?![A-Za-z0-9_])(?:\s*(?:=[^,;]*)?)?$",
        declaration.strip(),
    )
    if match is None:
        return None
    type_text = match.group("type").strip()
    if "=" in type_text or "->" in type_text or "." in type_text:
        return None
    return type_text or None


def _function_param_type(source_text: str, function: str, name: str) -> str | None:
    header = _function_header_text(source_text, function)
    if header is None:
        return None
    open_paren = header.find("(")
    close_paren = header.rfind(")")
    if open_paren < 0 or close_paren < open_paren:
        return None
    for param in _split_top_level_commas(header[open_paren + 1:close_paren]):
        type_text = _declaration_type_for_name(param, name)
        if type_text is not None:
            return type_text
    return None


def _function_local_type(
    source_text: str,
    *,
    name: str,
    search_span: tuple[int, int] | None,
) -> str | None:
    if search_span is None:
        return None
    name_re = re.escape(name)
    local_decl_re = re.compile(
        rf"^\s*(?P<type>(?:struct\s+)?[A-Za-z_]\w*"
        rf"(?:\s+[A-Za-z_]\w*)*\s*\*+)\s*"
        rf"(?P<name>{name_re})(?![A-Za-z0-9_])"
        rf"(?:\s*=\s*[^;]+)?\s*;\s*(?://.*)?$"
    )
    for _line_start, _line_end, line in _line_records_in_span(
        source_text,
        search_span,
    ):
        match = local_decl_re.match(line)
        if match is not None:
            return match.group("type").strip()
    return None


def _function_declared_type(
    source_text: str,
    *,
    function: str,
    name: str,
    search_span: tuple[int, int] | None,
) -> str | None:
    param_type = _function_param_type(source_text, function, name)
    if param_type is not None:
        return _safe_decl_type_text(param_type)
    if search_span is None:
        return None
    name_re = re.escape(name)
    local_decl_re = re.compile(
        rf"^\s*(?P<type>(?:struct\s+)?[A-Za-z_]\w*"
        rf"(?:\s+[A-Za-z_]\w*)*(?:\s*\*+)?)\s+"
        rf"(?P<name>{name_re})(?![A-Za-z0-9_])"
        rf"(?:\s*=\s*[^;]+)?\s*;\s*(?://.*)?$"
    )
    for _line_start, _line_end, line in _line_records_in_span(
        source_text,
        search_span,
    ):
        match = local_decl_re.match(line)
        if match is not None:
            return _safe_decl_type_text(match.group("type"))
    return None


def _looks_like_gobj_pointer_type(type_text: str | None) -> bool:
    if not isinstance(type_text, str) or "*" not in type_text:
        return False
    normalized = " ".join(type_text.replace("\t", " ").split())
    for qualifier in _TYPE_QUALIFIERS:
        normalized = re.sub(rf"\b{qualifier}\b", "", normalized)
    base_type = normalized.replace("*", "").strip()
    compact = base_type.replace(" ", "")
    return compact in {"HSD_GObj", "structHSD_GObj"} or compact.endswith("_GObj")


def _base_type_in_function(
    source_text: str,
    *,
    function: str,
    base_var: str,
    search_span: tuple[int, int] | None,
) -> str | None:
    return (
        _function_param_type(source_text, function, base_var)
        or _function_local_type(source_text, name=base_var, search_span=search_span)
    )


def _field_load_base_and_offset(source_attr: Any) -> tuple[str | None, int | None]:
    base_var = _attr_value(source_attr, "base_var")
    if not isinstance(base_var, str) or not base_var:
        expression = _attr_value(source_attr, "expression")
        if isinstance(expression, str):
            match = _FIELD_AT_RE.search(expression)
            if match is not None:
                base_var = match.group("base")
            else:
                field_match = re.search(
                    r"(?<![A-Za-z0-9_])(?P<base>[A-Za-z_]\w*)\s*"
                    r"(?:->|\.)\s*(?P<field>[A-Za-z_]\w*)",
                    expression,
                )
                base_var = field_match.group("base") if field_match else None
    field_offset = _parse_field_offset(_attr_value(source_attr, "field_offset"))
    expression = _attr_value(source_attr, "expression")
    if field_offset is None and isinstance(expression, str):
        match = _FIELD_AT_RE.search(expression)
        if match is not None:
            field_offset = int(match.group("offset"), 16)
    return (base_var if isinstance(base_var, str) and base_var else None), field_offset


def _first_def_payload(source_attr: Any) -> Any:
    return _source_attr_jsonish(_attr_value(source_attr, "first_def"))


def _pcode_field_address_like(source_attr: Any) -> bool:
    if _parse_field_offset(_attr_value(source_attr, "field_offset")) is None:
        return False
    if _source_attr_base_virtual(source_attr) is None:
        return False
    source_kind = _attr_value(source_attr, "kind")
    confidence = _attr_value(source_attr, "confidence")
    if source_kind == "load/store-address":
        return True
    return source_kind == "first-def" and confidence == "pcode-first-def"


def _pcode_field_opcode(source_attr: Any) -> str | None:
    first_def = _attr_value(source_attr, "first_def")
    if isinstance(first_def, Mapping):
        opcode = first_def.get("opcode")
        if isinstance(opcode, str) and opcode.strip():
            return opcode.strip().lower()
        text = first_def.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip().split(maxsplit=1)[0].lower()
    expression = _attr_value(source_attr, "expression")
    if isinstance(expression, str) and expression.strip():
        return expression.strip().split(maxsplit=1)[0].lower()
    return None


def _pcode_field_load_like(source_attr: Any) -> bool:
    if not _pcode_field_address_like(source_attr):
        return False
    opcode = _pcode_field_opcode(source_attr)
    if not opcode:
        return False
    if opcode.startswith("st"):
        return False
    return opcode.startswith(_LOAD_OPCODE_PREFIXES)


def _pcode_field_address_blocker(source_attr: Any) -> str | None:
    if not _pcode_field_address_like(source_attr):
        return None
    opcode = _pcode_field_opcode(source_attr)
    if not opcode:
        return "pcode-field-load-opcode-unresolved"
    if opcode.startswith("st"):
        return "pcode-field-store-source-owner-unsupported-shape"
    return "pcode-field-load-opcode-unsupported"


def _bare_call_rhs_name(rhs: str) -> str | None:
    text = rhs.strip()
    match = re.match(r"(?P<name>[A-Za-z_]\w*)\s*\(", text)
    if match is None:
        return None
    depth = 0
    in_string: str | None = None
    escaped = False
    for index, char in enumerate(text[match.end("name"):], start=match.end("name")):
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue
        if char in {'"', "'"}:
            in_string = char
            continue
        if char == "(":
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth == 0:
                return match.group("name") if not text[index + 1:].strip() else None
            if depth < 0:
                return None
    return None


def _bare_call_rhs_matches_symbol(rhs: str, call_symbol: str | None) -> bool:
    call_name = _bare_call_rhs_name(rhs)
    if call_name is None:
        return False
    if call_symbol:
        return call_name == call_symbol
    return True


def _resolved_pcode_field_load_source_attr(
    source_text: str,
    *,
    function: str,
    source_attr: Any,
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None,
    search_span: tuple[int, int] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
    base_virtual = _source_attr_base_virtual(source_attr)
    field_offset = _parse_field_offset(_attr_value(source_attr, "field_offset"))
    metadata: dict[str, Any] = {
        "handler": "pcode-first-def-field-load-source-order",
        "pcode_first_def": _first_def_payload(source_attr),
        "base_virtual": base_virtual,
        "field_offset": field_offset,
        "source_attribution": _source_attr_dict(source_attr),
    }
    if base_virtual is None or field_offset is None:
        return None, metadata, "field-load-base-source-unresolved"

    base_attr = _source_attr_for_ig(source_attributions, base_virtual)
    metadata["base_source_attribution"] = (
        _source_attr_dict(base_attr) if base_attr is not None else None
    )
    if base_attr is None:
        return None, metadata, "field-load-base-source-unresolved"

    base_kind = _attr_value(base_attr, "kind")
    if base_kind not in {"local", "call-return", "copy/coalesce-source"}:
        return None, metadata, "field-load-base-source-unresolved"
    base_var = _attr_value(base_attr, "name")
    if not isinstance(base_var, str) or _SIMPLE_IDENTIFIER_RE.fullmatch(base_var) is None:
        return None, metadata, "field-load-base-source-unresolved"

    attr_type = _attr_value(base_attr, "type")
    function_type = _base_type_in_function(
        source_text,
        function=function,
        base_var=base_var,
        search_span=search_span,
    )
    if base_kind == "local":
        base_type = attr_type if isinstance(attr_type, str) else function_type
    else:
        base_type = function_type
    metadata["base_var"] = base_var
    metadata["base_type"] = base_type
    if not isinstance(base_type, str) or "*" not in base_type:
        return None, metadata, "field-load-base-type-unresolved"

    field_name, blocker = _field_name_from_attribution(
        source_attr,
        base_var=base_var,
        field_offset=field_offset,
        base_type=base_type,
    )
    metadata["field_name"] = field_name
    if field_name is None:
        return None, metadata, blocker or "field-load-field-name-unresolved"

    resolved = {
        **_source_attr_dict(source_attr),
        "kind": "field-load",
        "confidence": _attr_value(source_attr, "confidence") or "pcode-first-def",
        "base_virtual": base_virtual,
        "base_var": base_var,
        "base_type": base_type,
        "field_offset": field_offset,
        "field_name": field_name,
        "expression": f"{base_var}->{field_name}",
        "pcode_first_def": metadata["pcode_first_def"],
        "base_source_attribution": metadata["base_source_attribution"],
    }
    return resolved, metadata, None


def _is_copy_coalesce_source_field_load(source_attr: Any) -> bool:
    if _attr_value(source_attr, "kind") != "copy/coalesce-source":
        return False
    if _parse_field_offset(_attr_value(source_attr, "field_offset")) is not None:
        return True
    base_var = _attr_value(source_attr, "base_var")
    field_name = _attr_value(source_attr, "field_name")
    if isinstance(base_var, str) and base_var and isinstance(field_name, str):
        return bool(field_name)
    expression = _attr_value(source_attr, "expression")
    return isinstance(expression, str) and ("->" in expression or "." in expression)


def _field_load_like_source_kind(source_attr: Any) -> str | None:
    source_kind = _attr_value(source_attr, "kind")
    if source_kind == "field-load":
        return "field-load"
    if _is_copy_coalesce_source_field_load(source_attr):
        return "copy/coalesce-source"
    if _pcode_field_load_like(source_attr):
        return "pcode-first-def"
    return None


def _field_load_probe_provenance_kind(source_attr: Any) -> str:
    if _attr_value(source_attr, "kind") == "copy/coalesce-source":
        return "copy-coalesce-source-field-load-source-order"
    if _pcode_field_load_like(source_attr):
        return "pcode-first-def-field-load-source-order"
    return "field-load-source-order"


def _copy_coalesce_source_probe_metadata(source_attr: Any) -> dict[str, Any]:
    return {
        key: _source_attr_jsonish(_attr_value(source_attr, key))
        for key in (
            "copy_chain",
            "base_virtual",
            "base_var",
            "field_offset",
            "field_name",
            "expression",
        )
        if _attr_value(source_attr, key) is not None
    }


def _field_name_from_attribution(
    source_attr: Any,
    *,
    base_var: str,
    field_offset: int | None,
    base_type: str | None,
) -> tuple[str | None, str | None]:
    field_name = _attr_value(source_attr, "field_name")
    expression = _attr_value(source_attr, "expression")
    expression_is_synthetic = (
        isinstance(expression, str) and _FIELD_AT_RE.search(expression) is not None
    )
    if (
        isinstance(field_name, str)
        and field_name
        and not field_name.startswith("field_at_")
        and not expression_is_synthetic
    ):
        return field_name, None

    if isinstance(expression, str):
        concrete = re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(base_var)}\s*(?:->|\.)\s*"
            rf"(?P<field>[A-Za-z_]\w*)(?![A-Za-z0-9_])",
            expression,
        )
        if concrete is not None and not concrete.group("field").startswith(
            "field_at_"
        ):
            return concrete.group("field"), None

    if field_offset == _GOBJ_USER_DATA_OFFSET:
        if _looks_like_gobj_pointer_type(base_type):
            return "user_data", None
        return None, "field-load-base-type-unresolved"
    return None, "field-load-field-name-unresolved"


def _owner_for_field_load_line(
    line: str,
    *,
    expression_start: int,
) -> tuple[str | None, str | None]:
    prefix = line[:expression_start]
    assignment = re.match(
        r"^\s*(?P<local>[A-Za-z_]\w*)\s*=\s*(?:\([^;]*\)\s*)?$",
        prefix,
    )
    if assignment is not None:
        return assignment.group("local"), None
    declaration = re.match(
        r"^\s*(?P<type>.+?)(?<![A-Za-z0-9_])(?P<local>[A-Za-z_]\w*)"
        r"(?![A-Za-z0-9_])\s*=\s*(?:\([^;]*\)\s*)?$",
        prefix,
    )
    if declaration is not None:
        type_text = _safe_decl_type_text(declaration.group("type"))
        return declaration.group("local"), type_text
    nested_assignment = re.search(
        r"(?<![A-Za-z0-9_])(?P<local>[A-Za-z_]\w*)\s*="
        r"\s*(?:\([^;]*\)\s*)?$",
        prefix,
    )
    if nested_assignment is not None:
        return nested_assignment.group("local"), None
    return None, None


def _field_load_candidate_dict(candidate: _FieldLoadSourceCandidate) -> dict[str, Any]:
    return {
        "base_var": candidate.base_var,
        "field_offset": candidate.field_offset,
        "field_name": candidate.field_name,
        "expression": candidate.expression,
        "source_span": list(candidate.source_span),
        "source_line": candidate.source_line,
        "owner_local": candidate.owner_local,
        "owner_type": candidate.owner_type,
        "kind": candidate.kind,
        "line_source_span": list(candidate.line_source_span),
        "line_text": candidate.line_text.strip(),
    }


def _field_load_temp_type(candidate: _FieldLoadSourceCandidate) -> str | None:
    if candidate.field_name == "user_data":
        return "void*"
    return _safe_decl_type_text(candidate.owner_type)


def _field_load_line_can_host_temp(
    stripped: str,
    *,
    owner_local: str | None,
) -> bool:
    if owner_local:
        return True
    return (
        re.match(r"^(?:return|if|while)\b", stripped) is not None
        or re.match(r"^[A-Za-z_]\w*\s*\(", stripped) is not None
        or re.match(r"^[A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)?\s*=", stripped)
        is not None
    )


def _field_load_source_candidates(
    source_text: str,
    *,
    function: str,
    source_attr: Any,
    search_span: tuple[int, int] | None,
) -> tuple[list[_FieldLoadSourceCandidate], dict[str, Any], str | None]:
    base_var, field_offset = _field_load_base_and_offset(source_attr)
    metadata: dict[str, Any] = {
        "handler": "field-load-source-order",
        "base_var": base_var,
        "field_offset": field_offset,
    }
    if base_var is None:
        return [], metadata, "field-load-base-type-unresolved"

    attr_base_type = _attr_value(source_attr, "base_type")
    base_type = (
        attr_base_type if isinstance(attr_base_type, str)
        else _base_type_in_function(
            source_text,
            function=function,
            base_var=base_var,
            search_span=search_span,
        )
    )
    metadata["base_type"] = base_type
    field_name, blocker = _field_name_from_attribution(
        source_attr,
        base_var=base_var,
        field_offset=field_offset,
        base_type=base_type,
    )
    metadata["field_name"] = field_name

    if search_span is None:
        return [], metadata, "field-load-source-span-not-found"

    search_start, search_end = search_span
    candidates: list[_FieldLoadSourceCandidate] = []
    seen: set[tuple[int, int]] = set()

    def append_source_matches(
        *,
        candidate_base_var: str,
        candidate_field_name: str,
        kind: str,
    ) -> None:
        expression_re = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(candidate_base_var)}"
            rf"\s*(?P<op>->|\.)\s*"
            rf"{re.escape(candidate_field_name)}(?![A-Za-z0-9_])"
        )
        for match in expression_re.finditer(source_text, search_start, search_end):
            source_start, source_end = match.span()
            line_start = source_text.rfind("\n", 0, source_start) + 1
            line_end = source_text.find("\n", source_end)
            if line_end < 0:
                line_end = len(source_text)
            line = source_text[line_start:line_end]
            rel_start = source_start - line_start
            owner_local, owner_type = _owner_for_field_load_line(
                line,
                expression_start=rel_start,
            )
            if owner_local is not None and owner_type is None:
                owner_type = _function_declared_type(
                    source_text,
                    function=function,
                    name=owner_local,
                    search_span=search_span,
                )
            key = (source_start, source_end)
            if key in seen:
                continue
            seen.add(key)
            op = match.group("op")
            candidates.append(
                _FieldLoadSourceCandidate(
                    base_var=candidate_base_var,
                    field_offset=field_offset,
                    field_name=candidate_field_name,
                    expression=f"{candidate_base_var}{op}{candidate_field_name}",
                    source_span=(source_start, source_end),
                    source_line=source_text.count("\n", 0, line_start) + 1,
                    owner_local=owner_local,
                    owner_type=owner_type,
                    kind=kind,
                    line_source_span=(line_start, line_end),
                    line_text=line,
                )
            )

    if field_name is not None:
        append_source_matches(
            candidate_base_var=base_var,
            candidate_field_name=field_name,
            kind="inline-temp",
        )

    if not candidates and field_offset is not None:
        recovered: list[dict[str, Any]] = []
        try:
            context = build_source_field_context(source_text, function=function)
        except Exception:
            context = None
        if context is not None:
            for candidate_base_var, candidate_base_type in context.local_types.items():
                if (
                    _SIMPLE_IDENTIFIER_RE.fullmatch(candidate_base_var) is None
                    or not isinstance(candidate_base_type, str)
                ):
                    continue
                resolved = source_for_field_offset(
                    context,
                    base_expression=candidate_base_var,
                    base_type=candidate_base_type,
                    offset=field_offset,
                )
                if resolved is None or not resolved.field_name:
                    continue
                bases_to_scan = [candidate_base_var]
                if (
                    resolved.base_var
                    and resolved.base_var not in bases_to_scan
                    and _SIMPLE_IDENTIFIER_RE.fullmatch(resolved.base_var) is not None
                ):
                    bases_to_scan.append(resolved.base_var)
                before_count = len(candidates)
                for scan_base_var in bases_to_scan:
                    append_source_matches(
                        candidate_base_var=scan_base_var,
                        candidate_field_name=resolved.field_name,
                        kind="same-offset-source-field",
                    )
                if len(candidates) > before_count:
                    recovered.append({
                        "base_var": candidate_base_var,
                        "resolved_base_var": resolved.base_var,
                        "base_type": candidate_base_type,
                        "field_name": resolved.field_name,
                        "field_offset": field_offset,
                        "expression": resolved.expression,
                        "source_line": resolved.source_line,
                        "source_col": resolved.source_col,
                        "confidence": resolved.confidence,
                    })
        if recovered:
            metadata["resolution_fallback"] = "same-offset-source-field"
            metadata["original_field_load_blocker"] = (
                blocker or "field-load-source-span-not-found"
            )
            metadata["same_offset_field_load_source_candidates"] = recovered

    metadata["field_load_source_candidates"] = [
        _field_load_candidate_dict(candidate) for candidate in candidates
    ]
    if not candidates:
        if field_name is None:
            return [], metadata, blocker or "field-load-field-name-unresolved"
        return [], metadata, "field-load-source-span-not-found"
    return candidates, metadata, None


def _materialize_field_load_candidate(
    source_text: str,
    *,
    function: str,
    candidate: _FieldLoadSourceCandidate,
    provenance_kind: str = "field-load-source-order",
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "field-load-inline-temp"
    candidate_payload = _field_load_candidate_dict(candidate)
    line_start, line_end = candidate.line_source_span
    expr_start, expr_end = candidate.source_span
    line = source_text[line_start:line_end]
    stripped = line.strip()
    if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
        return None, {
            **candidate_payload,
            "status": "rejected",
            "reason": "field-load-no-safe-insertion-point",
            "handler": handler,
        }
    if not (line_start <= expr_start < expr_end <= line_end):
        return None, {
            **candidate_payload,
            "status": "rejected",
            "reason": "field-load-source-span-not-found",
            "handler": handler,
        }
    if source_text[expr_start:expr_end].replace(" ", "") != (
        candidate.expression.replace(" ", "")
    ):
        return None, {
            **candidate_payload,
            "status": "rejected",
            "reason": "field-load-source-span-not-found",
            "handler": handler,
        }
    if not _field_load_line_can_host_temp(
        stripped,
        owner_local=candidate.owner_local,
    ):
        return None, {
            **candidate_payload,
            "status": "rejected",
            "reason": "field-load-no-safe-insertion-point",
            "handler": handler,
        }
    temp_type = _field_load_temp_type(candidate)
    if temp_type is None:
        return None, {
            **candidate_payload,
            "status": "rejected",
            "reason": "field-load-owner-not-materializable",
            "handler": handler,
        }
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None, {
            **candidate_payload,
            "status": "rejected",
            "reason": "source-ast-unavailable",
            "handler": handler,
        }
    decl_index, decl_indent = insertion
    if decl_index > line_start:
        return None, {
            **candidate_payload,
            "status": "rejected",
            "reason": "field-load-no-safe-insertion-point",
            "handler": handler,
        }

    temp_stem = f"{candidate.base_var}_{candidate.field_name or 'field_load'}"
    temp_name = _window_order_probe_local_name(source_text, temp_stem)
    indent = re.match(r"[ \t]*", line).group(0)
    rewritten_line = (
        source_text[line_start:expr_start]
        + temp_name
        + source_text[expr_end:line_end]
    )
    replacement = f"{indent}{temp_name} = {candidate.expression};\n{rewritten_line}"
    edits = [
        (line_start, line_end, replacement),
        (decl_index, decl_index, f"{decl_indent}{temp_type} {temp_name};\n"),
    ]
    candidate_text = source_text
    for start, end, replacement_text in sorted(edits, reverse=True):
        candidate_text = (
            candidate_text[:start] + replacement_text + candidate_text[end:]
        )
    if candidate_text == source_text:
        return None, {
            **candidate_payload,
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
        }
    metadata = {
        "handler": handler,
        "field_load_source_candidate": candidate_payload,
        "synthetic_local": temp_name,
        "temp_type": temp_type,
        "rewritten_expression": temp_name,
    }
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind=provenance_kind,
            metadata=metadata,
        ),
        {
            **candidate_payload,
            "status": "materialized",
            "handler": handler,
        },
    )


def _loop_index_names(header: str) -> tuple[str, ...]:
    names: list[str] = []
    parts = header.split(";", 2)
    if len(parts) != 3:
        return ()
    init, condition, increment = parts
    for text in (init, condition, increment):
        for name in re.findall(r"\b[A-Za-z_]\w*\b", text):
            if name not in names and not name.isupper():
                names.append(name)
    return tuple(names)


def _primary_loop_index_name(header: str) -> str | None:
    parts = header.split(";", 2)
    if len(parts) != 3:
        return None
    init = parts[0].strip()
    match = re.search(
        r"(?:^|,)\s*(?:[A-Za-z_]\w*(?:\s+\*?|\s*\*)+)?"
        r"(?P<name>[A-Za-z_]\w*)\s*=",
        init,
    )
    return match.group("name") if match is not None else None


def _for_loop_spans(
    source_text: str,
    search_span: tuple[int, int],
) -> list[dict[str, Any]]:
    search_start, search_end = search_span
    search_text = source_text[search_start:search_end]
    loops: list[dict[str, Any]] = []
    for match in re.finditer(
        r"for\s*\((?P<header>[^()]*)\)\s*\{",
        search_text,
        flags=re.MULTILINE,
    ):
        header = match.group("header")
        loop_start = search_start + match.start()
        loop_header_end = search_start + match.end()
        open_brace = source_text.find("{", loop_start, loop_header_end)
        if open_brace < 0:
            continue
        close_brace = _matching_brace_index(source_text, open_brace)
        if close_brace is None or close_brace > search_end:
            continue
        loops.append({
            "start": loop_start,
            "header_end": loop_header_end,
            "body_start": open_brace + 1,
            "body_end": close_brace,
            "end": close_brace + 1,
            "header": header,
            "index_names": _loop_index_names(header),
            "primary_index_name": _primary_loop_index_name(header),
        })
    return loops


def _rank_local_owner_candidates(
    source_text: str,
    local_name: str,
    *,
    source_line: object = None,
    search_span: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    search_span = search_span or (0, len(source_text))
    local_re = re.escape(local_name)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()

    def add(candidate: dict[str, Any]) -> None:
        key = (
            str(candidate.get("kind")),
            int(candidate.get("line_start") or 0),
            str(candidate.get("span_text") or ""),
        )
        if key in seen:
            return
        seen.add(key)
        candidate["rank"] = len(candidates) + 1
        candidates.append(candidate)

    decl_re = re.compile(
        rf"^\s*(?P<type>[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*|\s*\*)*)"
        rf"\s+{local_re}\s*(?:=[^,;]+)?;\s*(?://.*)?$"
    )
    for line_start, line_end, line in _line_records_in_span(source_text, search_span):
        if decl_re.match(line):
            add(_line_span_payload(
                source_text,
                line_start,
                line_end,
                kind="loop-index-declaration",
                priority=0,
                local=local_name,
                action_families=[
                    "local-declaration-lifetime",
                    "loop-index-owner",
                ],
            ))

    loops = _for_loop_spans(source_text, search_span)
    for loop in loops:
        header = str(loop["header"])
        if loop.get("primary_index_name") != local_name:
            continue
        add(_line_span_payload(
            source_text,
            int(loop["start"]),
            int(loop["header_end"]),
            kind="loop-index-header",
            priority=1,
            local=local_name,
            primary_loop_index=loop.get("primary_index_name"),
            action_families=["loop-index-owner", "loop-header-lifetime"],
        ))
        body_span = (int(loop["body_start"]), int(loop["body_end"]))
        for line_start, line_end, line in _line_records_in_span(
            source_text,
            body_span,
        ):
            stripped = line.strip()
            if not stripped:
                continue
            if re.search(rf"\b{local_re}\b", stripped):
                lhs = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
                if not re.fullmatch(local_re, lhs):
                    add(_line_span_payload(
                        source_text,
                        line_start,
                        line_end,
                        kind="loop-body-read",
                        priority=2,
                        local=local_name,
                        action_families=[
                            "loop-index-owner",
                            "loop-body-read-lifetime",
                        ],
                    ))
            if re.search(r"\[[^\]]+\]|\*[A-Za-z_]\w*\s*=", stripped):
                add(_line_span_payload(
                    source_text,
                    line_start,
                    line_end,
                    kind="loop-indexed-byte-expression",
                    priority=3,
                    local=local_name,
                    action_families=[
                        "indexed-byte-address-temp",
                        "loop-index-owner",
                    ],
                ))

    candidates.sort(key=lambda item: (
        int(item.get("rank_priority") or 0),
        0 if item.get("line_start") == source_line else 1,
        int(item.get("line_start") or 0),
    ))
    for index, candidate in enumerate(candidates, start=1):
        candidate["rank"] = index
    return candidates[:12]


def _copy_chain_entry(virtual: int, source_attr: Any | None) -> dict[str, Any]:
    entry: dict[str, Any] = {"virtual": virtual}
    if source_attr is None:
        entry["missing"] = True
        entry["kind"] = None
        return entry
    for key in (
        "kind",
        "name",
        "type",
        "expression",
        "base_virtual",
        "base_var",
        "field_offset",
        "field_name",
        "confidence",
    ):
        value = _attr_value(source_attr, key)
        if value is not None:
            entry[key] = value
    return entry


def _copy_chain_base_virtuals(entry: Mapping[str, Any]) -> tuple[int, ...]:
    raw = entry.get("base_virtual")
    if isinstance(raw, bool):
        return ()
    if isinstance(raw, int):
        return (raw,)
    if isinstance(raw, str) and raw.lstrip("-").isdigit():
        return (int(raw),)
    return _virtual_operand_ids(entry.get("expression"))


def _bounded_copy_chain(
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None,
    *,
    target_ig: int,
    source_attr: Any,
    source_operands: Iterable[int],
    max_hops: int = 4,
) -> tuple[list[dict[str, Any]], bool]:
    chain = [_copy_chain_entry(target_ig, source_attr)]
    queue = list(source_operands)
    seen = {target_ig}
    truncated = False
    while queue:
        virtual = queue.pop(0)
        if virtual in seen:
            truncated = True
            chain.append({"virtual": virtual, "cycle": True})
            continue
        seen.add(virtual)
        attr = _source_attr_for_ig(source_attributions, virtual)
        entry = _copy_chain_entry(virtual, attr)
        chain.append(entry)
        if len(chain) > max_hops:
            truncated = True
            break
        for base_virtual in _copy_chain_base_virtuals(entry):
            if base_virtual not in seen:
                queue.append(base_virtual)
    return chain[:max_hops + 1], truncated or bool(queue)


def _copy_product_chain_metadata(
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None,
    *,
    target_ig: int,
    copy_attr: Any,
    copy_product_source: _CopyProductSource,
    resolved_source_attr: Any | None,
) -> dict[str, Any]:
    copy_chain, copy_chain_truncated = _bounded_copy_chain(
        source_attributions,
        target_ig=target_ig,
        source_attr=copy_attr,
        source_operands=(copy_product_source.source_ig,),
    )
    metadata = dict(copy_product_source.metadata)
    metadata.update({
        "copy_chain": copy_chain,
        "copy_chain_truncated": copy_chain_truncated,
    })
    if resolved_source_attr is None:
        metadata["copy_product_source_missing"] = True
    else:
        metadata["copy_product_source_attribution"] = _source_attr_dict(
            resolved_source_attr
        )
    return metadata


def _with_copy_product_metadata(
    synthetic: _SyntheticOwnerResult,
    copy_metadata: Mapping[str, Any],
) -> _SyntheticOwnerResult:
    def merged(metadata: Mapping[str, Any]) -> dict[str, Any]:
        output = dict(metadata)
        if "copy_chain" in output:
            output["resolved_source_copy_chain"] = output["copy_chain"]
        if "copy_chain_truncated" in output:
            output["resolved_source_copy_chain_truncated"] = output[
                "copy_chain_truncated"
            ]
        output.update(copy_metadata)
        return output

    return _SyntheticOwnerResult(
        tuple(
            _SyntheticOwnerCandidate(
                candidate.owner,
                merged(candidate.metadata),
            )
            for candidate in synthetic.candidates
        ),
        merged(synthetic.metadata),
        synthetic.terminal_blocker,
    )


def _rank_indexed_byte_source_candidates(
    source_text: str,
    *,
    search_span: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    search_span = search_span or (0, len(source_text))
    loops = _for_loop_spans(source_text, search_span)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str, str]] = set()

    def loop_for_line(line_start: int) -> Mapping[str, Any] | None:
        for loop in loops:
            if int(loop["body_start"]) <= line_start < int(loop["body_end"]):
                return loop
        return None

    def add(candidate: dict[str, Any]) -> None:
        key = (
            int(candidate.get("line_start") or 0),
            str(candidate.get("array_base") or ""),
            str(candidate.get("index_expr") or ""),
            str(candidate.get("span_text") or ""),
        )
        if key in seen:
            return
        seen.add(key)
        candidate["rank"] = len(candidates) + 1
        candidates.append(candidate)

    for line_start, line_end, line in _line_records_in_span(source_text, search_span):
        stripped = line.strip()
        if not stripped:
            continue
        loop = loop_for_line(line_start)
        loop_indexes = tuple(loop.get("index_names") or ()) if loop else ()
        pointer_store = re.search(r"\*(?P<base>[A-Za-z_]\w*)\s*=", stripped)
        if pointer_store is not None:
            index_expr = loop_indexes[0] if loop_indexes else None
            add(_line_span_payload(
                source_text,
                line_start,
                line_end,
                kind="pointer-walk-indexed-byte-store",
                priority=1,
                array_base=pointer_store.group("base"),
                index_expr=index_expr,
                target_local=pointer_store.group("base"),
                temp_local=None,
                mutator_keys=[
                    "steer_indexed_byte_implicit_init_loop_indexed_store",
                    "steer_indexed_byte_direct_global_dst",
                ],
                action_families=[
                    "indexed-byte-address-temp",
                    "pointer-walk-destination",
                ],
            ))
        for indexed in _indexed_expression_spans(line):
            array_base = str(indexed["array_base"])
            index_expr = str(indexed["index_expr"])
            lhs = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
            target_local = lhs if re.fullmatch(r"[A-Za-z_]\w*", lhs) else array_base
            add(_line_span_payload(
                source_text,
                line_start + int(indexed["start"]),
                line_start + int(indexed["end"]),
                kind="indexed-byte-address-temp",
                priority=0,
                array_base=array_base,
                index_expr=index_expr,
                expression_text=indexed.get("expression_text"),
                target_local=target_local,
                temp_local=None,
                is_array_declarator=_is_array_declarator_line(
                    stripped,
                    array_base,
                ),
                mutator_keys=[
                    "steer_indexed_byte_index_temp",
                    "steer_indexed_byte_base_alias",
                    "steer_indexed_byte_same_line_expr",
                    "steer_indexed_byte_implicit_store_index_temp",
                ],
                action_families=[
                    "indexed-byte-address-temp",
                    "synthetic-temp-owner",
                ],
            ))

    candidates.sort(key=lambda item: (
        int(item.get("rank_priority") or 0),
        int(item.get("line_start") or 0),
    ))
    for index, candidate in enumerate(candidates, start=1):
        candidate["rank"] = index
    return candidates[:12]


_POINTER_DECL_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"(?P<type>[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*\s*\*+\s*)"
    r"(?P<local>[A-Za-z_]\w*)"
    r"\s*(?:=\s*(?P<rhs>.+?))?\s*;\s*(?://.*)?$"
)
_END_POINTER_TERM_RE = re.compile(
    r"(?:0x[0-9A-Fa-f]+|\d+|"
    r"[A-Za-z_]\w*(?:(?:\.|->)[A-Za-z_]\w*)*)"
)


def _safe_end_pointer_expression(rhs: str) -> bool:
    stripped = rhs.strip()
    if not stripped or _UNSAFE_SPLIT_RHS_RE.search(stripped):
        return False
    if re.search(r"[=&|^*/%<>\[\]{}:]", stripped):
        return False
    parts = [part.strip() for part in stripped.split("+")]
    if len(parts) < 2:
        return False
    return all(_END_POINTER_TERM_RE.fullmatch(part) is not None for part in parts)


def _split_end_pointer_rhs(rhs: str) -> tuple[str, str] | None:
    if not _safe_end_pointer_expression(rhs):
        return None
    parts = [part.strip() for part in rhs.strip().split("+")]
    if len(parts) < 2:
        return None
    return " + ".join(parts[:-1]), parts[-1]


def _integer_literal_value(text: object) -> int | None:
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    try:
        if re.fullmatch(r"-?(?:0x[0-9A-Fa-f]+|\d+)", stripped):
            return int(stripped, 0)
    except ValueError:
        return None
    return None


def _li_first_def_immediate(source_attr: Any) -> int | None:
    for text in (
        _attr_value(source_attr, "expression"),
        _source_attr_first_def_operands(source_attr),
    ):
        if not isinstance(text, str):
            continue
        match = _LI_EXPRESSION_RE.search(text.strip())
        if match is None:
            match = _LI_OPERANDS_RE.search(text.strip())
        if match is None:
            continue
        try:
            return int(match.group("imm"), 0)
        except ValueError:
            continue
    return None


def _literal_assignment_record(
    source_text: str,
    line_start: int,
    line_end: int,
    line: str,
) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
        return None
    assignment_kind = "assignment"
    assignment_match = _SIMPLE_ASSIGN_RE.match(line)
    decl_type: str | None = None
    if assignment_match is not None:
        owner_local = assignment_match.group("lhs")
        literal_text = assignment_match.group("rhs").strip()
        indent = assignment_match.group("indent")
    else:
        decl_match = _LI_DECL_INIT_RE.match(line)
        if decl_match is None:
            return None
        assignment_kind = "declaration-init"
        owner_local = decl_match.group("local")
        literal_text = decl_match.group("rhs").strip()
        indent = decl_match.group("indent")
        decl_type = _safe_decl_type_text(decl_match.group("type"))
        if decl_type is None:
            return None
    if _INT_LITERAL_RE.fullmatch(literal_text) is None:
        return None
    literal_value = _integer_literal_value(literal_text)
    if literal_value is None:
        return None
    return _line_span_payload(
        source_text,
        line_start,
        line_end,
        kind="li-constant-threshold-owner",
        priority=0,
        handler="li-constant-threshold-owner",
        owner_local=owner_local,
        literal_text=literal_text,
        literal_value=literal_value,
        owner_assignment_text=stripped,
        assignment_kind=assignment_kind,
        declaration_type=decl_type,
        indent=indent,
        action_families=[
            "li-constant-threshold-owner",
            "synthetic-temp-owner",
        ],
    )


def _local_read_score(
    source_text: str,
    *,
    local_name: str,
    after_line_end: int,
    search_span: tuple[int, int],
) -> int:
    score = 0
    local_re = re.escape(local_name)
    for _line_start, _line_end, line in _line_records_in_span(
        source_text,
        (after_line_end, search_span[1]),
    ):
        stripped = line.strip()
        if not stripped or not re.search(rf"\b{local_re}\b", stripped):
            continue
        if re.search(rf"(?:>=|<=|>|<|==|!=)\s*{local_re}\b", stripped):
            score += 4
        if re.search(rf"\b{local_re}\s*(?:>=|<=|>|<|==|!=)", stripped):
            score += 4
        if re.search(rf"[-+]\s*{local_re}\b|\b{local_re}\s*[-+]", stripped):
            score += 3
        score += 1
    return score


def _paired_li_literal(
    records: Iterable[Mapping[str, Any]],
    candidate: Mapping[str, Any],
) -> dict[str, Any] | None:
    owner = candidate.get("owner_local")
    try:
        candidate_line = int(candidate.get("line_start") or 0)
    except (TypeError, ValueError):
        candidate_line = 0
    best: Mapping[str, Any] | None = None
    best_distance = 999999
    for record in records:
        if record is candidate:
            continue
        if record.get("owner_local") != owner:
            continue
        if record.get("literal_value") == candidate.get("literal_value"):
            continue
        try:
            distance = abs(int(record.get("line_start") or 0) - candidate_line)
        except (TypeError, ValueError):
            distance = 999999
        if distance < best_distance:
            best = record
            best_distance = distance
    if best is None or best_distance > 8:
        return None
    return {
        "literal_text": best.get("literal_text"),
        "literal_value": best.get("literal_value"),
        "owner_assignment_text": best.get("owner_assignment_text"),
        "line_start": best.get("line_start"),
        "line_end": best.get("line_end"),
    }


def _rank_li_constant_source_candidates(
    source_text: str,
    *,
    immediate: int,
    search_span: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    search_span = search_span or (0, len(source_text))
    records: list[dict[str, Any]] = []
    for line_start, line_end, line in _line_records_in_span(source_text, search_span):
        record = _literal_assignment_record(source_text, line_start, line_end, line)
        if record is not None:
            records.append(record)

    candidates = [
        dict(record)
        for record in records
        if record.get("literal_value") == immediate
    ]
    for candidate in candidates:
        owner = candidate.get("owner_local")
        owner_score = (
            _local_read_score(
                source_text,
                local_name=owner,
                after_line_end=int(candidate.get("line_source_end") or 0),
                search_span=search_span,
            )
            if isinstance(owner, str)
            else 0
        )
        candidate["immediate_value"] = immediate
        candidate["owner_read_score"] = owner_score
        paired = _paired_li_literal(records, candidate)
        if paired is not None:
            candidate["paired_literal"] = paired
            candidate["paired_assignment_text"] = paired.get(
                "owner_assignment_text"
            )
            candidate["rank_priority"] = int(candidate.get("rank_priority") or 0) - 1

    candidates.sort(key=lambda item: (
        int(item.get("rank_priority") or 0),
        -int(item.get("owner_read_score") or 0),
        int(item.get("line_start") or 0),
    ))
    for index, candidate in enumerate(candidates, start=1):
        candidate["rank"] = index
    return candidates[:12]


def _materialize_li_constant_candidate(
    source_text: str,
    *,
    function: str,
    candidate: Mapping[str, Any],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "li-constant-threshold-owner"
    rejection_reason = candidate.get("candidate_rejection_reason")
    if isinstance(rejection_reason, str) and rejection_reason:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason=rejection_reason,
            handler=handler,
        )
    line_bounds = _line_bounds_from_candidate(source_text, candidate)
    if line_bounds is None:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="missing-source-span",
            handler=handler,
        )
    line_start, line_end, line = line_bounds
    stripped = line.strip()
    if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="unsafe-executable-line",
            handler=handler,
        )
    owner_local = candidate.get("owner_local")
    literal_text = candidate.get("literal_text")
    immediate = candidate.get("immediate_value")
    if (
        not isinstance(owner_local, str)
        or not owner_local
        or not isinstance(literal_text, str)
        or _integer_literal_value(literal_text) != immediate
    ):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="missing-li-constant-owner",
            handler=handler,
        )
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="source-ast-unavailable",
            handler=handler,
        )
    decl_index, decl_indent = insertion
    temp_name = _window_order_probe_local_name(
        source_text,
        f"{owner_local}_{abs(int(immediate))}",
    )
    assignment_kind = candidate.get("assignment_kind")
    indent = re.match(r"[ \t]*", line).group(0)
    candidate_text = source_text
    if assignment_kind == "declaration-init":
        declaration_type = candidate.get("declaration_type")
        if not isinstance(declaration_type, str) or not declaration_type:
            return None, _candidate_materialization_diagnostic(
                candidate,
                status="rejected",
                reason="missing-safe-local-declaration-type",
                handler=handler,
            )
        replacement = f"{indent}{declaration_type} {owner_local};\n"
        insertion_text = (
            f"{decl_indent}int {temp_name};\n"
            f"{decl_indent}{temp_name} = {literal_text};\n"
            f"{decl_indent}{owner_local} = {temp_name};\n"
        )
        edits = [
            (line_start, line_end, replacement),
            (decl_index, decl_index, insertion_text),
        ]
    elif assignment_kind == "assignment":
        if decl_index > line_start:
            return None, _candidate_materialization_diagnostic(
                candidate,
                status="rejected",
                reason="declaration-anchor-after-use",
                handler=handler,
            )
        replacement = (
            f"{indent}{temp_name} = {literal_text};\n"
            f"{indent}{owner_local} = {temp_name};\n"
        )
        edits = [
            (line_start, line_end, replacement),
            (decl_index, decl_index, f"{decl_indent}int {temp_name};\n"),
        ]
    else:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="diagnostic_only",
            reason="unsupported-li-constant-assignment-kind",
            handler=handler,
        )
    for start, end, replacement_text in sorted(edits, reverse=True):
        candidate_text = (
            candidate_text[:start] + replacement_text + candidate_text[end:]
        )
    if candidate_text == source_text:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="source-unchanged",
            handler=handler,
        )
    metadata = {
        "handler": handler,
        "immediate_value": immediate,
        "literal_text": literal_text,
        "literal_value": candidate.get("literal_value"),
        "owner_local": owner_local,
        "owner_assignment_text": candidate.get("owner_assignment_text"),
        "paired_literal": candidate.get("paired_literal"),
        "paired_assignment_text": candidate.get("paired_assignment_text"),
        "synthetic_local": temp_name,
        "line_range": [
            int(candidate.get("line_start") or 0),
            int(candidate.get("line_end") or 0),
        ],
        "ranked_li_constant_source_candidate": dict(candidate),
    }
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="window-order-li-constant-source-probe",
            metadata=metadata,
        ),
        _candidate_materialization_diagnostic(
            candidate,
            status="materialized",
            handler=handler,
        ),
    )


def _top_level_comma_count(text: str) -> int:
    depth = 0
    count = 0
    for char in text:
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            count += 1
    return count


def _call_for_argument_prefix(prefix: str) -> tuple[str, int] | None:
    matches = list(re.finditer(r"(?P<callee>[A-Za-z_]\w*)\s*\(", prefix))
    if not matches:
        return None
    call = matches[-1]
    callee = call.group("callee")
    argument_prefix = prefix[call.end():]
    return callee, _top_level_comma_count(argument_prefix)


def _pointer_walk_cast_stem(cast_type: str) -> str:
    cleaned = re.sub(r"\b(?:struct|const|volatile|register)\b", " ", cast_type)
    cleaned = cleaned.replace("*", " ")
    names = re.findall(r"[A-Za-z_]\w*", cleaned)
    if not names:
        return "ptr"
    name = names[-1]
    if name.startswith("HSD_"):
        name = name[4:]
    return name.lower()


def _rank_pointer_walk_add_source_candidates(
    source_text: str,
    *,
    search_span: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    search_span = search_span or (0, len(source_text))
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str, str]] = set()
    for line_start, line_end, line in _line_records_in_span(source_text, search_span):
        stripped = line.strip()
        if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
            continue
        for match in _POINTER_WALK_ADD_RE.finditer(line):
            index_expr = match.group("index").strip()
            call = _call_for_argument_prefix(line[:match.start("argument")])
            if call is None:
                continue
            offset_value = _integer_literal_value(match.group("offset"))
            if offset_value is None:
                continue
            shift = int(match.group("shift"))
            scale_bytes = 1 << shift
            callee, argument_index = call
            key = (
                line_start,
                callee,
                match.group("base"),
                match.group("argument"),
            )
            if key in seen:
                continue
            seen.add(key)
            candidate = _line_span_payload(
                source_text,
                line_start + match.start("argument"),
                line_start + match.end("argument"),
                kind="pointer-walk-add-callarg",
                priority=0,
                handler="pointer-walk-add-temp-owner",
                callee=callee,
                argument_index=argument_index,
                argument_text=match.group("argument"),
                base_expression=match.group("base"),
                index_expr=index_expr,
                shift=shift,
                scale_bytes=scale_bytes,
                offset_expression=match.group("offset"),
                offset_value=offset_value,
                cast_type=" ".join(match.group("cast_type").split()),
                byte_pointer_cast=" ".join(
                    match.group("byte_pointer_cast").split()
                ),
                action_families=[
                    "pointer-walk-add-temp-owner",
                    "synthetic-temp-owner",
                ],
            )
            if not _safe_index_temp_expression(index_expr):
                candidate["candidate_rejection_reason"] = (
                    "unsafe-pointer-walk-add-expression"
                )
            candidate["rank"] = len(candidates) + 1
            candidates.append(candidate)
    candidates.sort(key=lambda item: (
        int(item.get("rank_priority") or 0),
        int(item.get("line_start") or 0),
        int(item.get("argument_index") or 0),
    ))
    for index, candidate in enumerate(candidates, start=1):
        candidate["rank"] = index
    return candidates[:12]


def _materialize_pointer_walk_add_candidate(
    source_text: str,
    *,
    function: str,
    candidate: Mapping[str, Any],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "pointer-walk-add-temp-owner"
    rejection_reason = candidate.get("candidate_rejection_reason")
    if isinstance(rejection_reason, str) and rejection_reason:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason=rejection_reason,
            handler=handler,
        )
    line_bounds = _line_bounds_from_candidate(source_text, candidate)
    if line_bounds is None:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="missing-source-span",
            handler=handler,
        )
    line_start, line_end, line = line_bounds
    stripped = line.strip()
    if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="unsafe-executable-line",
            handler=handler,
        )
    if candidate.get("kind") != "pointer-walk-add-callarg":
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="diagnostic_only",
            reason="unsupported-pointer-walk-add-kind",
            handler=handler,
        )
    try:
        expr_start = int(candidate["source_start"])
        expr_end = int(candidate["source_end"])
    except (KeyError, TypeError, ValueError):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="missing-source-span",
            handler=handler,
        )
    expr_start = max(line_start, min(expr_start, line_end))
    expr_end = max(expr_start, min(expr_end, line_end))
    argument_text = candidate.get("argument_text")
    if (
        not isinstance(argument_text, str)
        or source_text[expr_start:expr_end] != argument_text
    ):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="stale-source-span",
            handler=handler,
        )
    base_expression = candidate.get("base_expression")
    index_expr = candidate.get("index_expr")
    cast_type = candidate.get("cast_type")
    if (
        not isinstance(base_expression, str)
        or not isinstance(index_expr, str)
        or not isinstance(cast_type, str)
    ):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="missing-pointer-walk-owner",
            handler=handler,
        )
    if not _safe_index_temp_expression(index_expr):
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="unsafe-pointer-walk-add-expression",
            handler=handler,
        )
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="source-ast-unavailable",
            handler=handler,
        )
    decl_index, decl_indent = insertion
    if decl_index > line_start:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="declaration-anchor-after-use",
            handler=handler,
        )
    temp_name = _window_order_probe_local_name(
        source_text,
        f"{base_expression}_{_pointer_walk_cast_stem(cast_type)}",
    )
    rewritten_line = (
        source_text[line_start:expr_start]
        + temp_name
        + source_text[expr_end:line_end]
    )
    if rewritten_line == line:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="source-unchanged",
            handler=handler,
        )
    indent = re.match(r"[ \t]*", line).group(0)
    replacement = (
        f"{indent}{temp_name} = {argument_text};\n"
        f"{rewritten_line}"
    )
    edits = [
        (line_start, line_end, replacement),
        (decl_index, decl_index, f"{decl_indent}{cast_type} {temp_name};\n"),
    ]
    candidate_text = source_text
    for start, end, replacement_text in sorted(edits, reverse=True):
        candidate_text = (
            candidate_text[:start] + replacement_text + candidate_text[end:]
        )
    if candidate_text == source_text:
        return None, _candidate_materialization_diagnostic(
            candidate,
            status="rejected",
            reason="source-unchanged",
            handler=handler,
        )
    metadata = {
        "handler": handler,
        "base_expression": base_expression,
        "index_expr": index_expr,
        "shift": candidate.get("shift"),
        "scale_bytes": candidate.get("scale_bytes"),
        "offset_expression": candidate.get("offset_expression"),
        "offset_value": candidate.get("offset_value"),
        "callee": candidate.get("callee"),
        "argument_index": candidate.get("argument_index"),
        "argument_text": argument_text,
        "cast_type": cast_type,
        "byte_pointer_cast": candidate.get("byte_pointer_cast"),
        "synthetic_local": temp_name,
        "line_range": [
            int(candidate.get("line_start") or 0),
            int(candidate.get("line_end") or 0),
        ],
        "ranked_pointer_walk_add_source_candidate": dict(candidate),
    }
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="window-order-pointer-walk-add-source-probe",
            metadata=metadata,
        ),
        _candidate_materialization_diagnostic(
            candidate,
            status="materialized",
            handler=handler,
        ),
    )


def _pcode_addi_immediate(expression: object) -> int | None:
    if not isinstance(expression, str):
        return None
    match = re.search(r"\baddi\b\s+[^,]+,\s*[^,]+,\s*(?P<imm>-?\d+)\s*$", expression)
    if match is None:
        return None
    try:
        return int(match.group("imm"), 10)
    except ValueError:
        return None


def _rank_pointer_loop_end_pointer_candidates(
    source_text: str,
    *,
    search_span: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    search_span = search_span or (0, len(source_text))
    pointer_types: dict[str, str] = {}
    assignments: dict[str, list[dict[str, Any]]] = {}
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()

    def record_assignment(
        *,
        line_start: int,
        line_end: int,
        line: str,
        end_local: str,
        rhs: str,
        declaration_type: str | None,
        assignment_kind: str,
    ) -> None:
        rhs = rhs.strip()
        split_rhs = _split_end_pointer_rhs(rhs)
        rejection_reason = None if split_rhs is not None else (
            "unsafe-end-pointer-expression"
        )
        base_expression = split_rhs[0] if split_rhs is not None else None
        offset_expression = split_rhs[1] if split_rhs is not None else None
        assignments.setdefault(end_local, []).append({
            "line_start_index": line_start,
            "line_end_index": line_end,
            "line": line,
            "end_local": end_local,
            "rhs": rhs,
            "declaration_type": declaration_type or pointer_types.get(end_local),
            "assignment_kind": assignment_kind,
            "base_expression": base_expression,
            "offset_expression": offset_expression,
            "offset_value": _integer_literal_value(offset_expression),
            "candidate_rejection_reason": rejection_reason,
        })

    for line_start, line_end, line in _line_records_in_span(source_text, search_span):
        stripped = line.strip()
        if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
            continue
        decl_match = _POINTER_DECL_RE.match(line)
        if decl_match is not None:
            local = decl_match.group("local")
            declaration_type = " ".join(decl_match.group("type").strip().split())
            pointer_types[local] = declaration_type
            rhs = decl_match.group("rhs")
            if rhs is not None:
                record_assignment(
                    line_start=line_start,
                    line_end=line_end,
                    line=line,
                    end_local=local,
                    rhs=rhs,
                    declaration_type=declaration_type,
                    assignment_kind="declaration-init",
                )
            continue
        assign_match = _SIMPLE_ASSIGN_RE.match(line)
        if assign_match is None:
            continue
        lhs = assign_match.group("lhs")
        if (
            lhs not in pointer_types
            and not lhs.endswith("_end")
            and "_end_" not in lhs
        ):
            continue
        record_assignment(
            line_start=line_start,
            line_end=line_end,
            line=line,
            end_local=lhs,
            rhs=assign_match.group("rhs"),
            declaration_type=pointer_types.get(lhs),
            assignment_kind="assignment",
        )

    loops = _for_loop_spans(source_text, search_span)

    def add(candidate: dict[str, Any]) -> None:
        key = (
            int(candidate.get("line_start") or 0),
            str(candidate.get("end_local") or ""),
            str(candidate.get("loop_header_text") or ""),
        )
        if key in seen:
            return
        seen.add(key)
        candidate["rank"] = len(candidates) + 1
        candidates.append(candidate)

    for loop in loops:
        header = str(loop["header"])
        parts = header.split(";", 2)
        if len(parts) != 3:
            continue
        condition = parts[1].strip()
        relation_priority = 0
        relation_match = re.fullmatch(
            r"(?P<iter>[A-Za-z_]\w*)\s*<\s*(?P<end>[A-Za-z_]\w*)",
            condition,
        )
        if relation_match is None:
            relation_match = re.fullmatch(
                r"(?P<end>[A-Za-z_]\w*)\s*>\s*(?P<iter>[A-Za-z_]\w*)",
                condition,
            )
            relation_priority = 2
        if relation_match is None:
            continue
        iter_local = relation_match.group("iter")
        end_local = relation_match.group("end")
        end_assignments = [
            assignment for assignment in assignments.get(end_local, [])
            if int(assignment["line_end_index"]) <= int(loop["start"])
        ]
        if not end_assignments:
            continue
        assignment = end_assignments[-1]
        rank_priority = relation_priority
        if end_local.startswith("ll_probe_end_"):
            rank_priority -= 2
        elif end_local.endswith("_end") or "_end_" in end_local:
            rank_priority -= 1
        if assignment.get("candidate_rejection_reason") is not None:
            rank_priority += 10
        payload = _line_span_payload(
            source_text,
            int(assignment["line_start_index"]),
            int(assignment["line_end_index"]),
            kind="pointer-loop-end-pointer",
            priority=rank_priority,
            end_local=end_local,
            iter_local=iter_local,
            owner_rhs=assignment["rhs"],
            base_expression=assignment.get("base_expression"),
            offset_expression=assignment.get("offset_expression"),
            offset_value=assignment.get("offset_value"),
            declaration_type=assignment.get("declaration_type"),
            assignment_kind=assignment.get("assignment_kind"),
            owner_assignment_text=str(assignment["line"]).strip(),
            loop_header_text=source_text[
                int(loop["start"]):int(loop["header_end"])
            ].strip(),
            loop_header_source_span=[int(loop["start"]), int(loop["header_end"])],
            condition_relation="iter-before-end",
            candidate_rejection_reason=assignment.get("candidate_rejection_reason"),
            handler="pcode-addi-end-pointer-owner",
            action_families=[
                "pointer-loop-end-pointer",
                "synthetic-temp-owner",
            ],
        )
        add(payload)

    candidates.sort(key=lambda item: (
        int(item.get("rank_priority") or 0),
        int(item.get("line_start") or 0),
    ))
    for index, candidate in enumerate(candidates, start=1):
        candidate["rank"] = index
    return candidates[:12]


def _assignment_from_sibling(
    sibling: statement_move.SiblingStmt,
) -> tuple[str, str, str] | None:
    if sibling.kind != "simple":
        return None
    match = _SIMPLE_ASSIGN_RE.match(sibling.text)
    if match is None:
        return None
    lhs = match.group("lhs")
    rhs = match.group("rhs").strip()
    if "=" in rhs or _UNSAFE_SPLIT_RHS_RE.search(rhs):
        return None
    return lhs, rhs, match.group("indent")


def _decl_type_for_local(
    sibs: list[statement_move.SiblingStmt],
    local_name: str,
) -> tuple[str, statement_move.SiblingStmt] | None:
    name_re = re.escape(local_name)
    decl_re = re.compile(
        rf"^(?P<indent>\s*)(?P<type>.+?)(?<![A-Za-z0-9_])"
        rf"(?P<name>{name_re})\s*(?:=[^,;]+)?;\s*(?://.*)?$"
    )
    for sibling in sibs:
        if sibling.node_type != "declaration" or "\n" in sibling.text:
            continue
        match = decl_re.match(sibling.text)
        if match is None:
            continue
        type_text = " ".join(match.group("type").strip().split())
        if (
            not type_text
            or "," in type_text
            or "[" in sibling.text
            or "(" in type_text
            or ")" in type_text
        ):
            continue
        tokens = set(type_text.replace("*", " ").split())
        if "volatile" in tokens:
            continue
        return type_text, sibling
    return None


def _is_float_decl_type(type_text: str) -> bool:
    if "*" in type_text:
        return False
    tokens = {
        token
        for token in type_text.replace("*", " ").split()
        if token not in _TYPE_QUALIFIERS
    }
    return bool(_FLOAT_DECL_TYPES & tokens)


def _local_has_float_decl(
    groups: list[statement_move.SiblingGroup],
    local_name: str,
) -> bool:
    for group in groups:
        if local_name not in group.locals_:
            continue
        decl = _decl_type_for_local(group.siblings, local_name)
        if decl is None:
            continue
        type_text, _sibling = decl
        if _is_float_decl_type(type_text):
            return True
    return False


def _normalized_decl_type(type_text: str) -> str:
    tokens = [
        token
        for token in type_text.replace("*", " ").split()
        if token not in _TYPE_QUALIFIERS
    ]
    return " ".join(tokens)


def _is_type_compatible_split_expression(split_expression: str, type_text: str) -> bool:
    cast = _CAST_TYPE_RE.match(split_expression.strip())
    if cast is None:
        return True
    return _normalized_decl_type(cast.group("type")) == _normalized_decl_type(type_text)


def _unique_assignment_owner(
    groups: list[statement_move.SiblingGroup],
    local_name: str,
    *,
    source_line: object = None,
) -> _OwnerAssignment | None:
    matches: list[_OwnerAssignment] = []
    for group in groups:
        if local_name not in group.locals_:
            continue
        for sibling in group.siblings:
            assignment = _assignment_from_sibling(sibling)
            if assignment is None:
                continue
            lhs, rhs, indent = assignment
            if lhs != local_name:
                continue
            if isinstance(source_line, int):
                start, end = sibling.line_range
                if not start <= source_line <= end:
                    continue
            matches.append(
                _OwnerAssignment(
                    group=group,
                    sibling=sibling,
                    local_name=local_name,
                    rhs=rhs,
                    indent=indent,
                )
            )
    if len(matches) != 1:
        return None
    return matches[0]


def _fpr_split_expressions(rhs: str, opcode: str) -> list[str]:
    term = _FLOAT_EXPR_TERM_RE.pattern
    stripped = rhs.strip()
    if opcode in {"fsub", "fsubs"}:
        return [stripped] if re.fullmatch(rf"\s*{term}\s*-\s*{term}\s*", rhs) else []
    if opcode in {"fmul", "fmuls"}:
        return [stripped] if re.fullmatch(rf"\s*{term}\s*\*\s*{term}\s*", rhs) else []
    if opcode == "lfs":
        candidates: list[str] = []
        if (
            _SIMPLE_TERM_RE.fullmatch(stripped) is not None
            or _CASTED_SIMPLE_TERM_RE.fullmatch(stripped) is not None
        ):
            candidates.append(stripped)
        for match in _CASTED_SIMPLE_TERM_RE.finditer(rhs):
            expr = match.group(0).strip()
            if expr not in candidates:
                candidates.append(expr)
        return candidates
    return []


def _matching_assignment_owners(
    groups: list[statement_move.SiblingGroup],
    opcode: str,
    *,
    local_name: str | None = None,
    source_line: object = None,
) -> list[_OwnerAssignment]:
    matches: list[_OwnerAssignment] = []
    for group in groups:
        if local_name is not None and local_name not in group.locals_:
            continue
        for sibling in group.siblings:
            assignment = _assignment_from_sibling(sibling)
            if assignment is None:
                continue
            lhs, rhs, indent = assignment
            if local_name is not None and lhs != local_name:
                continue
            if isinstance(source_line, int):
                start, end = sibling.line_range
                if not start <= source_line <= end:
                    continue
            decl = _decl_type_for_local(group.siblings, lhs)
            if decl is None:
                continue
            type_text, _ = decl
            if not _is_float_decl_type(type_text):
                continue
            split_expressions = _fpr_split_expressions(rhs, opcode)
            if not split_expressions:
                continue
            for split_expression in split_expressions:
                if not _is_type_compatible_split_expression(split_expression, type_text):
                    continue
                matches.append(
                    _OwnerAssignment(
                        group=group,
                        sibling=sibling,
                        local_name=lhs,
                        rhs=rhs,
                        indent=indent,
                        split_expression=split_expression,
                    )
                )
    return matches


def _local_fpr_decl_type(
    group: statement_move.SiblingGroup,
    local_name: str,
) -> tuple[str, statement_move.SiblingStmt] | None:
    decl = _decl_type_for_local(group.siblings, local_name)
    if decl is None:
        return None
    type_text, sibling = decl
    tokens = set(type_text.replace("*", " ").split())
    if "*" in type_text or tokens & {"const", "static", "volatile"}:
        return None
    if _normalized_decl_type(type_text) not in _FLOAT_DECL_TYPES:
        return None
    return type_text, sibling


def _local_float_rhs_reads(rhs: str) -> set[str]:
    without_cast_types = re.sub(
        r"\(\s*[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*\s*\)",
        " ",
        rhs,
    )
    without_fields = re.sub(r"\.\s*[A-Za-z_]\w*", "", without_cast_types)
    without_numbers = re.sub(r"\b\d[\w.]*", "", without_fields)
    return set(re.findall(r"[A-Za-z_]\w*", without_numbers))


def _float_local_split_expression(rhs: str, locals_: set[str]) -> str | None:
    stripped = rhs.strip()
    if "=" in stripped or _LOCAL_FLOAT_FORBIDDEN_RHS_RE.search(stripped):
        return None
    if not _local_float_rhs_reads(stripped) <= locals_:
        return None
    if (
        _FLOAT_EXPR_TERM_RE.fullmatch(stripped) is not None
        or _LOCAL_FLOAT_BINARY_EXPR_RE.fullmatch(stripped) is not None
    ):
        return stripped
    return None


def _first_def_opcode(source_attr: Any) -> str | None:
    first_def = _attr_value(source_attr, "first_def")
    if isinstance(first_def, Mapping):
        opcode = first_def.get("opcode")
        return opcode if isinstance(opcode, str) else None
    opcode = getattr(first_def, "opcode", None)
    return opcode if isinstance(opcode, str) else None


def _row_fsubs_call_minus_local(rhs: str) -> tuple[str, str, str] | None:
    match = re.fullmatch(
        r"\s*(?P<call>HSD_JObjGetTranslationY\(\s*(?P<arg>[A-Za-z_]\w*)\s*\))"
        r"\s*-\s*(?P<base>[A-Za-z_]\w*)\s*",
        rhs,
    )
    if match is None:
        return None
    return match.group("call"), match.group("arg"), match.group("base")


def _local_row_fsubs_call_owner_candidates(
    owner: _OwnerAssignment,
    *,
    source_attr: Any,
    target_ig: int,
) -> _SyntheticOwnerResult:
    parsed = _row_fsubs_call_minus_local(owner.rhs)
    metadata = {
        "handler": "local-fpr-row-fsubs-owner-repair",
        "owner_local": owner.local_name,
        "original_rhs": owner.rhs,
        "target_ig": target_ig,
        "expected_phys": _attr_value(source_attr, "expected_phys"),
        "requires_expression_score_validation": True,
    }
    if parsed is None:
        return _SyntheticOwnerResult((), metadata, "row-fsubs-owner-no-safe-transform")
    first_def_opcode = _first_def_opcode(source_attr)
    if first_def_opcode is not None and first_def_opcode != "fsubs":
        return _SyntheticOwnerResult((), metadata, "row-fsubs-owner-no-safe-transform")
    call_expr, call_arg, base_local = parsed
    if call_expr.split("(", 1)[0] != "HSD_JObjGetTranslationY":
        return _SyntheticOwnerResult((), metadata, "row-fsubs-owner-no-safe-transform")
    if call_arg not in owner.group.locals_ or base_local not in owner.group.locals_:
        return _SyntheticOwnerResult((), metadata, "row-fsubs-owner-no-safe-transform")
    metadata.update({
        "call_expr": call_expr,
        "base_local": base_local,
    })
    call_owner_meta = dict(metadata)
    call_owner_meta.update({
        "candidate_id": "row-fsubs-call-result-owner",
        "split_expression": call_expr,
    })
    fsubs_owner_meta = dict(metadata)
    fsubs_owner_meta.update({
        "candidate_id": "row-fsubs-owner-temp",
        "split_expression": owner.rhs,
    })
    return _SyntheticOwnerResult(
        (
            _SyntheticOwnerCandidate(
                _OwnerAssignment(
                    group=owner.group,
                    sibling=owner.sibling,
                    local_name=owner.local_name,
                    rhs=owner.rhs,
                    indent=owner.indent,
                    split_expression=call_expr,
                ),
                call_owner_meta,
            ),
            _SyntheticOwnerCandidate(
                _OwnerAssignment(
                    group=owner.group,
                    sibling=owner.sibling,
                    local_name=owner.local_name,
                    rhs=owner.rhs,
                    indent=owner.indent,
                    split_expression=owner.rhs,
                ),
                fsubs_owner_meta,
            ),
        ),
        metadata,
        None,
    )


def _visible_local_assignment_owners(
    groups: list[statement_move.SiblingGroup],
    local_name: str,
    *,
    source_line: object = None,
) -> list[_OwnerAssignment]:
    matches: list[_OwnerAssignment] = []
    for group in groups:
        if local_name not in group.locals_:
            continue
        for sibling in group.siblings:
            if sibling.kind != "simple":
                continue
            match = _SIMPLE_ASSIGN_RE.match(sibling.text)
            if match is None or match.group("lhs") != local_name:
                continue
            if isinstance(source_line, int):
                start, end = sibling.line_range
                if not start <= source_line <= end:
                    continue
            matches.append(
                _OwnerAssignment(
                    group=group,
                    sibling=sibling,
                    local_name=local_name,
                    rhs=match.group("rhs").strip(),
                    indent=match.group("indent"),
                )
            )
    return matches


def _local_fpr_owner_split(
    groups: list[statement_move.SiblingGroup],
    local_name: str,
    source_attr: Any,
    *,
    target_ig: int,
) -> _SyntheticOwnerResult:
    source_line = _attr_value(source_attr, "source_line")
    owners = _visible_local_assignment_owners(
        groups,
        local_name,
        source_line=source_line,
    )
    if not owners and isinstance(source_line, int):
        owners = _visible_local_assignment_owners(groups, local_name)
    if len(owners) != 1:
        return _SyntheticOwnerResult(
            (),
            {"handler": "local-fpr-owner-split", "owner_local": local_name},
            "local-source-owner-no-unique-assignment",
        )
    owner = owners[0]
    decl = _local_fpr_decl_type(owner.group, owner.local_name)
    if decl is None:
        return _SyntheticOwnerResult(
            (),
            {"handler": "local-fpr-owner-split", "owner_local": local_name},
            "local-source-owner-nonfloat",
        )
    split_expression = _float_local_split_expression(
        owner.rhs,
        set(owner.group.locals_),
    )
    if split_expression is None:
        if (
            "HSD_JObjGetTranslationY" in owner.rhs
            or _first_def_opcode(source_attr) == "fsubs"
        ):
            row_fsubs = _local_row_fsubs_call_owner_candidates(
                owner,
                source_attr=source_attr,
                target_ig=target_ig,
            )
            if row_fsubs.candidates or row_fsubs.terminal_blocker is not None:
                return row_fsubs
        return _SyntheticOwnerResult(
            (),
            {
                "handler": "local-fpr-owner-split",
                "owner_local": local_name,
                "rhs": owner.rhs,
            },
            "local-source-owner-unsupported-rhs",
        )
    metadata = {
        "handler": "local-fpr-owner-split",
        "owner_local": owner.local_name,
        "split_expression": split_expression,
    }
    return _SyntheticOwnerResult(
        (
            _SyntheticOwnerCandidate(
                _OwnerAssignment(
                    group=owner.group,
                    sibling=owner.sibling,
                    local_name=owner.local_name,
                    rhs=owner.rhs,
                    indent=owner.indent,
                    split_expression=split_expression,
                ),
                metadata,
            ),
        ),
        metadata,
        None,
    )


def _fpr_assignment_owners(
    groups: list[statement_move.SiblingGroup],
    opcode: str,
) -> list[_OwnerAssignment]:
    return _matching_assignment_owners(groups, opcode)


def _fpr_conversion_consumer_owners(
    groups: list[statement_move.SiblingGroup],
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None,
    target_ig: int,
) -> list[_SyntheticOwnerCandidate]:
    candidates: list[_SyntheticOwnerCandidate] = []
    if source_attributions is None:
        return candidates
    seen_keys: set[tuple[str, str]] = set()
    for raw_key, attr in source_attributions.items():
        try:
            consumer_ig = int(raw_key)
        except (TypeError, ValueError):
            continue
        if consumer_ig == target_ig or _attr_value(attr, "kind") != "local":
            continue
        operands = _source_attr_first_def_operands(attr)
        if target_ig not in _virtual_operand_ids(operands):
            continue
        local_name = _attr_value(attr, "name")
        if not isinstance(local_name, str) or not local_name:
            continue
        owners = _matching_assignment_owners(
            groups,
            "lfs",
            local_name=local_name,
            source_line=_attr_value(attr, "source_line"),
        )
        for owner in owners:
            split_expression = owner.split_expression or owner.rhs
            key = (owner.local_name, split_expression)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            metadata = {
                "handler": "fpr-conversion-owner-split",
                "consumer_ig": consumer_ig,
                "operand_ig": target_ig,
                "owner_local": owner.local_name,
                "split_expression": split_expression,
                "expression": _attr_value(attr, "expression"),
            }
            candidates.append(_SyntheticOwnerCandidate(owner, metadata))
    return candidates


def _synthetic_local_name(source_text: str, local_name: str) -> str:
    base = f"window_order_synthetic_{_safe_label_part(local_name)}"
    candidate = base.replace("-", "_")
    index = 2
    while re.search(rf"\b{re.escape(candidate)}\b", source_text):
        candidate = f"{base}_{index}".replace("-", "_")
        index += 1
    return candidate


def _split_owner_assignment_source(
    source_text: str,
    owner: _OwnerAssignment,
) -> tuple[str, dict[str, Any]] | None:
    decl = _decl_type_for_local(owner.group.siblings, owner.local_name)
    if decl is None:
        return None
    type_text, decl_sibling = decl
    source_bytes = source_text.encode("utf-8")
    stmt_start, stmt_end = _line_bounds(
        source_bytes,
        owner.sibling.byte_range[0],
        owner.sibling.byte_range[1],
    )
    decl_start, decl_end = _line_bounds(
        source_bytes,
        decl_sibling.byte_range[0],
        decl_sibling.byte_range[1],
    )

    original_line = source_bytes[stmt_start:stmt_end].decode("utf-8")
    if not original_line.endswith("\n"):
        original_line = f"{original_line}\n"
    synth_name = _synthetic_local_name(source_text, owner.local_name)
    decl_line = source_bytes[decl_start:decl_end].decode("utf-8")
    decl_indent = re.match(r"\s*", decl_line).group(0)
    stmt_indent = re.match(r"\s*", original_line).group(0)
    inserted_decl = f"{decl_indent}{type_text} {synth_name};\n"
    split_expression = (owner.split_expression or owner.rhs).strip()
    if not split_expression:
        return None
    if split_expression == owner.rhs:
        rewritten_rhs = synth_name
    else:
        occurrence_count = owner.rhs.count(split_expression)
        if occurrence_count != 1:
            return None
        rewritten_rhs = owner.rhs.replace(split_expression, synth_name, 1)
    replacement = (
        f"{stmt_indent}{synth_name} = {split_expression};\n"
        + f"{stmt_indent}{owner.local_name} = {rewritten_rhs};\n"
    )

    edits = [
        (stmt_start, stmt_end, replacement.encode("utf-8")),
        (decl_end, decl_end, inserted_decl.encode("utf-8")),
    ]
    out = source_bytes
    for start, end, replacement_bytes in sorted(edits, reverse=True):
        out = out[:start] + replacement_bytes + out[end:]
    return out.decode("utf-8"), {
        "owner_local": owner.local_name,
        "synthetic_local": synth_name,
        "split_expression": split_expression,
        "rewritten_rhs": rewritten_rhs,
        "type": type_text,
        "line_range": [
            owner.sibling.line_range[0],
            owner.sibling.line_range[1],
        ],
        "scope_depth": owner.group.scope_depth,
        "block_start_line": owner.group.block_start_line,
    }


def _normalized_expression_text(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _call_return_rhs_matches(source_attr: Any, rhs: str) -> bool:
    expression = _attr_value(source_attr, "expression")
    call_symbol = _attr_value(source_attr, "call_symbol")
    rhs_call_name = _bare_call_rhs_name(rhs)
    if rhs_call_name is None:
        return False
    if isinstance(expression, str) and expression.strip():
        if (
            _bare_call_rhs_name(expression) is not None
            and _normalized_expression_text(expression)
            == _normalized_expression_text(rhs)
        ):
            return True
    if isinstance(call_symbol, str) and call_symbol:
        return _bare_call_rhs_matches_symbol(rhs, call_symbol)
    return False


def _call_return_owner_split(
    groups: list[statement_move.SiblingGroup],
    source_attr: Any,
) -> _SyntheticOwnerResult:
    local_name = _attr_value(source_attr, "name")
    metadata = {
        "handler": "call-return-owner-split",
        "assigned_local": local_name,
        "source_line": _attr_value(source_attr, "source_line"),
        "expression": _attr_value(source_attr, "expression"),
        "call_symbol": _attr_value(source_attr, "call_symbol"),
        "copy_chain": _source_attr_jsonish(_attr_value(source_attr, "copy_chain")),
        "variant": "synthetic-call-return-owner-copy",
    }
    if not isinstance(local_name, str) or not local_name:
        return _SyntheticOwnerResult((), metadata, "call-return-owner-copy-not-found")

    source_line = _attr_value(source_attr, "source_line")
    owners = _visible_local_assignment_owners(
        groups,
        local_name,
        source_line=source_line,
    )
    if not owners and isinstance(source_line, int):
        owners = _visible_local_assignment_owners(groups, local_name)
    owners = [
        owner for owner in owners
        if _call_return_rhs_matches(source_attr, owner.rhs)
    ]
    if len(owners) != 1:
        metadata["candidate_assignment_count"] = len(owners)
        return _SyntheticOwnerResult((), metadata, "call-return-owner-copy-not-found")

    owner = owners[0]
    metadata.update({
        "owner_local": owner.local_name,
        "split_expression": owner.rhs,
        "line_range": [
            owner.sibling.line_range[0],
            owner.sibling.line_range[1],
        ],
    })
    return _SyntheticOwnerResult(
        (
            _SyntheticOwnerCandidate(
                _OwnerAssignment(
                    group=owner.group,
                    sibling=owner.sibling,
                    local_name=owner.local_name,
                    rhs=owner.rhs,
                    indent=owner.indent,
                    split_expression=owner.rhs,
                ),
                metadata,
            ),
        ),
        metadata,
        None,
    )


def _split_owner_assignment_source_with_type(
    source_text: str,
    *,
    function: str,
    owner: _OwnerAssignment,
    type_text: str,
) -> tuple[str, dict[str, Any]] | None:
    type_text = _safe_decl_type_text(type_text) or ""
    if not type_text:
        return None
    source_bytes = source_text.encode("utf-8")
    stmt_start, stmt_end = _line_bounds(
        source_bytes,
        owner.sibling.byte_range[0],
        owner.sibling.byte_range[1],
    )
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None
    decl_index, decl_indent = insertion
    if decl_index > stmt_start:
        return None

    original_line = source_bytes[stmt_start:stmt_end].decode("utf-8")
    if not original_line.endswith("\n"):
        original_line = f"{original_line}\n"
    synth_name = _synthetic_local_name(source_text, owner.local_name)
    stmt_indent = re.match(r"\s*", original_line).group(0)
    split_expression = (owner.split_expression or owner.rhs).strip()
    if not split_expression:
        return None
    if split_expression == owner.rhs:
        rewritten_rhs = synth_name
    else:
        occurrence_count = owner.rhs.count(split_expression)
        if occurrence_count != 1:
            return None
        rewritten_rhs = owner.rhs.replace(split_expression, synth_name, 1)

    replacement = (
        f"{stmt_indent}{synth_name} = {split_expression};\n"
        + f"{stmt_indent}{owner.local_name} = {rewritten_rhs};\n"
    )
    inserted_decl = f"{decl_indent}{type_text} {synth_name};\n"
    edits = [
        (stmt_start, stmt_end, replacement.encode("utf-8")),
        (decl_index, decl_index, inserted_decl.encode("utf-8")),
    ]
    out = source_bytes
    for start, end, replacement_bytes in sorted(edits, reverse=True):
        out = out[:start] + replacement_bytes + out[end:]
    return out.decode("utf-8"), {
        "owner_local": owner.local_name,
        "synthetic_local": synth_name,
        "split_expression": split_expression,
        "rewritten_rhs": rewritten_rhs,
        "type": type_text,
        "line_range": [
            owner.sibling.line_range[0],
            owner.sibling.line_range[1],
        ],
        "scope_depth": owner.group.scope_depth,
        "block_start_line": owner.group.block_start_line,
        "declaration_insertion": "function-scope",
    }


def _implicit_add_owner(
    source_text: str,
    groups: list[statement_move.SiblingGroup],
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None,
    target_ig: int,
    source_attr: Any,
    *,
    search_span: tuple[int, int] | None = None,
) -> _SyntheticOwnerResult:
    virtual_expr = _parse_virtual_expression(_attr_value(source_attr, "expression"))
    if virtual_expr is None:
        return _SyntheticOwnerResult((), {}, "synthetic-temp-unsupported-shape")
    if virtual_expr.opcode not in {"add", "addi"}:
        return _SyntheticOwnerResult((), {}, "synthetic-temp-unsupported-shape")
    if virtual_expr.dest is not None and virtual_expr.dest != target_ig:
        return _SyntheticOwnerResult((), {}, "synthetic-temp-unsupported-shape")

    copy_chain, copy_chain_truncated = _bounded_copy_chain(
        source_attributions,
        target_ig=target_ig,
        source_attr=source_attr,
        source_operands=virtual_expr.sources,
    )
    indexed_candidates = _rank_indexed_byte_source_candidates(
        source_text,
        search_span=search_span,
    )
    end_pointer_candidates = _rank_pointer_loop_end_pointer_candidates(
        source_text,
        search_span=search_span,
    )
    pointer_walk_add_candidates = _rank_pointer_walk_add_source_candidates(
        source_text,
        search_span=search_span,
    )
    addi_immediate = _pcode_addi_immediate(_attr_value(source_attr, "expression"))
    prefer_end_pointer = (
        addi_immediate is not None
        and any(
            candidate.get("offset_value") == addi_immediate
            and candidate.get("candidate_rejection_reason") is None
            for candidate in end_pointer_candidates
        )
    )
    prefer_pointer_walk_add = (
        virtual_expr.opcode == "add"
        and bool(pointer_walk_add_candidates)
        and any(
            _attr_value(_source_attr_for_ig(source_attributions, operand_ig), "kind")
            in {"call-return", "implicit-temp"}
            for operand_ig in virtual_expr.sources
        )
    )
    if prefer_end_pointer:
        owner_order = ["end_pointer", "indexed_byte", "pointer_walk_add"]
    elif prefer_pointer_walk_add:
        owner_order = ["pointer_walk_add", "indexed_byte", "end_pointer"]
    else:
        owner_order = ["indexed_byte", "pointer_walk_add", "end_pointer"]
    base_metadata = {
        "expression": _attr_value(source_attr, "expression"),
        "copy_chain": copy_chain,
        "copy_chain_truncated": copy_chain_truncated,
        "ranked_indexed_byte_source_candidates": indexed_candidates,
        "ranked_end_pointer_source_candidates": end_pointer_candidates,
        "ranked_pointer_walk_add_source_candidates": pointer_walk_add_candidates,
        "pcode_addi_immediate": addi_immediate,
        "ranked_owner_candidate_order": owner_order,
    }

    local_operands: list[tuple[int, Any]] = []
    unattributed_operands: list[dict[str, Any]] = []
    for operand_ig in virtual_expr.sources:
        operand_attr = _source_attr_for_ig(source_attributions, operand_ig)
        operand_kind = _attr_value(operand_attr, "kind")
        if operand_kind != "local":
            if operand_attr is not None and operand_kind is not None:
                unattributed_operands.append({
                    "operand_ig": operand_ig,
                    "operand_source_attribution": _source_attr_dict(operand_attr),
                })
            continue
        local_name = _attr_value(operand_attr, "name")
        if not isinstance(local_name, str) or not local_name:
            continue
        local_operands.append((operand_ig, operand_attr))
    unattributed_add_blocker = (
        "pointer-walk-add-owner-not-materializable"
        if virtual_expr.opcode == "add" and pointer_walk_add_candidates
        else "synthetic-temp-operands-unattributed"
    )
    if unattributed_operands:
        metadata = dict(base_metadata)
        metadata["unattributed_operands"] = unattributed_operands
        if local_operands:
            metadata["local_operands"] = [
                {
                    "operand_ig": operand_ig,
                    "operand_source_attribution": _source_attr_dict(operand_attr),
                }
                for operand_ig, operand_attr in local_operands
            ]
        return _SyntheticOwnerResult(
            (),
            metadata,
            unattributed_add_blocker,
        )
    if not local_operands:
        return _SyntheticOwnerResult(
            (),
            base_metadata,
            unattributed_add_blocker,
        )
    if len(local_operands) != 1:
        return _SyntheticOwnerResult(
            (),
            base_metadata,
            "synthetic-temp-no-unique-owner",
        )

    operand_ig, operand_attr = local_operands[0]
    local_name = _attr_value(operand_attr, "name")
    owner = _unique_assignment_owner(
        groups,
        local_name,
        source_line=_attr_value(operand_attr, "source_line"),
    )
    if owner is None and isinstance(_attr_value(operand_attr, "source_line"), int):
        owner = _unique_assignment_owner(groups, local_name)
    if owner is None:
        metadata = dict(base_metadata)
        metadata.update({
            "operand_ig": operand_ig,
            "operand_source_attribution": _source_attr_dict(operand_attr),
        })
        return _SyntheticOwnerResult(
            (),
            metadata,
            "synthetic-temp-no-unique-owner",
        )
    metadata = dict(base_metadata)
    metadata.update({
        "handler": "implicit-add-owner-split",
        "operand_ig": operand_ig,
        "operand_source_attribution": _source_attr_dict(operand_attr),
    })
    return _SyntheticOwnerResult(
        (_SyntheticOwnerCandidate(owner, metadata),),
        metadata,
        None,
    )


def _fpr_temp_owner(
    groups: list[statement_move.SiblingGroup],
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None,
    target_ig: int,
    source_attr: Any,
) -> _SyntheticOwnerResult:
    virtual_expr = _parse_virtual_expression(_attr_value(source_attr, "expression"))
    if virtual_expr is None:
        return _SyntheticOwnerResult((), {}, "synthetic-temp-unsupported-shape")
    if virtual_expr.dest is not None and virtual_expr.dest != target_ig:
        return _SyntheticOwnerResult((), {}, "synthetic-temp-unsupported-shape")
    if virtual_expr.opcode not in {"fsub", "fsubs", "fmul", "fmuls", "lfs"}:
        return _SyntheticOwnerResult((), {}, "synthetic-temp-unsupported-shape")
    if virtual_expr.opcode in {"fsub", "fsubs"}:
        conversion_candidates = _fpr_conversion_consumer_owners(
            groups,
            source_attributions,
            target_ig,
        )
        if conversion_candidates:
            metadata = {
                "handler": "fpr-conversion-owner-split",
                "expression": _attr_value(source_attr, "expression"),
                "opcode": virtual_expr.opcode,
                "candidate_count": len(conversion_candidates),
            }
            return _SyntheticOwnerResult(
                tuple(conversion_candidates),
                metadata,
                None,
            )
    owners = _fpr_assignment_owners(groups, virtual_expr.opcode)
    if not owners:
        return _SyntheticOwnerResult(
            (),
            {
                "expression": _attr_value(source_attr, "expression"),
                "opcode": virtual_expr.opcode,
            },
            "fpr-first-def-source-owner-missing",
        )
    base_metadata = {
        "handler": (
                "fpr-load-owner-split"
                if virtual_expr.opcode == "lfs"
                else "fpr-arith-owner-split"
        ),
        "expression": _attr_value(source_attr, "expression"),
        "opcode": virtual_expr.opcode,
        "candidate_count": len(owners),
    }
    candidates: list[_SyntheticOwnerCandidate] = []
    for index, owner in enumerate(owners):
        metadata = dict(base_metadata)
        metadata.update({
            "candidate_index": index,
            "owner_local": owner.local_name,
            "split_expression": owner.split_expression or owner.rhs,
        })
        candidates.append(_SyntheticOwnerCandidate(owner, metadata))
    return _SyntheticOwnerResult(
        tuple(candidates),
        base_metadata,
        None,
    )


def _materialize_synthetic_owner_probe(
    source_text: str,
    *,
    lead: Mapping[str, Any],
    target_ig: int,
    direction: str,
    source_attr: Any,
    owner: _OwnerAssignment,
    synthetic_source_probe: dict[str, Any],
    existing_probe_count: int,
) -> LifetimeLayoutProbe | None:
    split = _split_owner_assignment_source(source_text, owner)
    if split is None:
        return None
    candidate_text, split_meta = split
    if candidate_text == source_text:
        return None

    label = (
        "window-order-synthetic-"
        f"ig{target_ig}-"
        f"{direction}-"
        f"{_safe_label_part(owner.local_name)}-"
        f"{existing_probe_count}"
    )
    synthetic_meta = dict(synthetic_source_probe)
    synthetic_meta.update(split_meta)
    return LifetimeLayoutProbe(
        label=label,
        operator="window-order-source-steering",
        description=(
            f"Split source owner {owner.local_name} for synthetic "
            "window-order fallback attribution."
        ),
        source_text=candidate_text,
        provenance={
            "kind": "window-order-fallback-synthetic-source-move",
            "lead": dict(lead),
            "source_attribution": _source_attr_dict(source_attr),
            "moved_local": owner.local_name,
            "synthetic_source_probe": synthetic_meta,
        },
    )


def _source_ast_unavailable_plan(
    fallback_leads: Iterable[Mapping[str, Any]],
) -> WindowOrderSourceProbePlan:
    diagnostics: list[dict[str, Any]] = []
    for lead in fallback_leads:
        target_ig = _lead_target_ig(lead)
        direction = _lead_direction(lead)
        diag: dict[str, Any] = {
            "lead": dict(lead),
            "status": "needs_context",
            "terminal_blocker": "source-ast-unavailable",
        }
        if target_ig is not None:
            diag["target_ig"] = target_ig
        if direction is not None:
            diag["direction"] = direction
        diagnostics.append(diag)
    return WindowOrderSourceProbePlan(probes=[], lead_diagnostics=diagnostics)


def plan_window_order_source_probes(
    source_text: str,
    *,
    function: str,
    fallback_leads: Iterable[Mapping[str, Any]],
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None = None,
    max_probes: int = 8,
    ranked_indexed_byte_candidates_per_target: int = 1,
    ranked_end_pointer_candidates_per_target: int = 1,
    ranked_li_constant_candidates_per_target: int = 1,
    ranked_pointer_walk_add_candidates_per_target: int = 1,
) -> WindowOrderSourceProbePlan:
    """Plan conservative source moves and explain each fallback lead.

    A lead is source-actionable only when its target IG has a unique local
    source attribution and exactly one movable statement unit writes that local.
    Ambiguous or missing source bindings intentionally produce diagnostics
    instead of probes.
    """

    limit = max(0, int(max_probes))
    ranked_indexed_byte_limit = max(
        0,
        int(ranked_indexed_byte_candidates_per_target),
    )
    ranked_end_pointer_limit = max(
        0,
        int(ranked_end_pointer_candidates_per_target),
    )
    ranked_li_constant_limit = max(
        0,
        int(ranked_li_constant_candidates_per_target),
    )
    ranked_pointer_walk_add_limit = max(
        0,
        int(ranked_pointer_walk_add_candidates_per_target),
    )
    leads = list(fallback_leads)

    groups = statement_move.sibling_groups(source_text, function)
    if groups is None:
        return _source_ast_unavailable_plan(leads)

    source_bytes = source_text.encode("utf-8")
    function_body_span = _function_body_span(source_text, function)
    escaped = statement_move.escaped_locals(source_text, function)
    movable_by_local: dict[str, list[tuple[
        statement_move.SiblingGroup,
        list[statement_move.SiblingStmt],
        statement_move.MoveUnit,
    ]]] = {}
    for group in groups:
        sibs = group.siblings
        locals_ = set(group.locals_)
        for unit in statement_move.extract_movable_units(sibs, locals_):
            if not statement_move._unit_owns_its_lines(unit, source_bytes):
                continue
            movable_by_local.setdefault(unit.write_base, []).append(
                (group, sibs, unit)
            )

    probes: list[LifetimeLayoutProbe] = []
    lead_diagnostics: list[dict[str, Any]] = []
    seen_source: set[str] = set()
    seen_synthetic_source_by_target: set[tuple[int, str]] = set()
    ranked_local_materialized_targets: set[int] = set()
    ranked_indexed_materialized_counts: dict[int, int] = {}
    ranked_end_pointer_materialized_counts: dict[int, int] = {}
    ranked_li_constant_materialized_counts: dict[int, int] = {}
    ranked_pointer_walk_add_materialized_counts: dict[int, int] = {}

    def materialize_ranked_indexed_byte_candidates(
        *,
        diag: dict[str, Any],
        lead: Mapping[str, Any],
        target_ig: int,
        direction: str,
        source_attr: Any,
        synthetic_metadata: Mapping[str, Any],
        default_blocker: str,
    ) -> bool:
        ranked_candidates = synthetic_metadata.get(
            "ranked_indexed_byte_source_candidates"
        )
        if not isinstance(ranked_candidates, list) or not ranked_candidates:
            return False

        synthetic_probe = dict(synthetic_metadata)
        diagnostics: list[dict[str, Any]] = []
        materialized_labels: list[str] = []
        materialized_meta: list[dict[str, Any]] = []
        first_source_diff: str | None = None
        remaining_target_slots = (
            ranked_indexed_byte_limit
            - ranked_indexed_materialized_counts.get(target_ig, 0)
        )
        if remaining_target_slots <= 0:
            diag["synthetic_source_probe"] = synthetic_probe
            diag["terminal_blocker"] = "duplicate-ranked-indexed-byte-target"
            return False
        for candidate in ranked_candidates:
            if not isinstance(candidate, Mapping):
                continue
            if len(probes) >= limit:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="probe-limit-reached",
                    handler="indexed-byte-ranked-candidate",
                ))
                continue
            lifetime_candidate, candidate_diag = (
                _materialize_indexed_byte_candidate(
                    source_text,
                    function=function,
                    candidate=candidate,
                )
            )
            if lifetime_candidate is None:
                diagnostics.append(candidate_diag)
                continue
            if len(materialized_labels) >= remaining_target_slots:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="duplicate-ranked-indexed-byte-target",
                    handler="indexed-byte-ranked-candidate",
                ))
                continue
            if lifetime_candidate.source_text in seen_source:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="duplicate-source-move",
                    handler="indexed-byte-ranked-candidate",
                ))
                continue
            label = (
                "window-order-ranked-indexed-byte-"
                f"ig{target_ig}-"
                f"{direction}-"
                f"{len(probes)}"
            )
            candidate_diag["probe_label"] = label
            metadata = dict(lifetime_candidate.metadata)
            metadata["probe_label"] = label
            seen_source.add(lifetime_candidate.source_text)
            probes.append(
                LifetimeLayoutProbe(
                    label=label,
                    operator="window-order-source-steering",
                    description=(
                        "Materialize ranked indexed-byte owner span for a "
                        "window-order fallback attribution."
                    ),
                    source_text=lifetime_candidate.source_text,
                    provenance={
                        "kind": lifetime_candidate.provenance_kind,
                        "lead": dict(lead),
                        "source_attribution": _source_attr_dict(source_attr),
                        "synthetic_source_probe": dict(synthetic_probe),
                        **metadata,
                    },
                )
            )
            materialized_labels.append(label)
            materialized_meta.append(metadata)
            diagnostics.append(candidate_diag)
            if first_source_diff is None:
                first_source_diff = _source_diff(
                    source_text,
                    lifetime_candidate.source_text,
                )

        summary = {
            "ranked_indexed_byte_candidates": len([
                item for item in ranked_candidates if isinstance(item, Mapping)
            ]),
            "materialized_indexed_byte_candidates": len(materialized_meta),
            "per_target_materialization_limit": ranked_indexed_byte_limit,
            "reasons": _candidate_reason_counts(diagnostics),
        }
        synthetic_probe["ranked_indexed_byte_candidate_diagnostics"] = diagnostics
        synthetic_probe[
            "materialized_ranked_indexed_byte_source_candidates"
        ] = materialized_meta
        synthetic_probe["ranked_indexed_byte_materialization_summary"] = summary
        diag["synthetic_source_probe"] = synthetic_probe
        diag["ranked_indexed_byte_candidate_diagnostics"] = diagnostics
        diag["ranked_indexed_byte_materialization_summary"] = summary
        if materialized_labels:
            ranked_indexed_materialized_counts[target_ig] = (
                ranked_indexed_materialized_counts.get(target_ig, 0)
                + len(materialized_labels)
            )
            diag["status"] = "materialized"
            diag["materialized_probe_labels"] = materialized_labels
            if first_source_diff is not None:
                diag["source_diff"] = first_source_diff
            diag.pop("terminal_blocker", None)
            return True
        diag["terminal_blocker"] = (
            "ranked-owner-candidates-not-materializable"
            if diagnostics else default_blocker
        )
        return False

    def materialize_ranked_end_pointer_candidates(
        *,
        diag: dict[str, Any],
        lead: Mapping[str, Any],
        target_ig: int,
        direction: str,
        source_attr: Any,
        synthetic_metadata: Mapping[str, Any],
        default_blocker: str,
    ) -> bool:
        ranked_candidates = synthetic_metadata.get(
            "ranked_end_pointer_source_candidates"
        )
        if not isinstance(ranked_candidates, list) or not ranked_candidates:
            return False

        synthetic_probe = dict(diag.get("synthetic_source_probe") or synthetic_metadata)
        diagnostics: list[dict[str, Any]] = []
        materialized_labels: list[str] = []
        materialized_meta: list[dict[str, Any]] = []
        first_source_diff: str | None = None
        remaining_target_slots = (
            ranked_end_pointer_limit
            - ranked_end_pointer_materialized_counts.get(target_ig, 0)
        )
        if remaining_target_slots <= 0:
            diag["synthetic_source_probe"] = synthetic_probe
            diag["terminal_blocker"] = "duplicate-ranked-end-pointer-target"
            return False
        for candidate in ranked_candidates:
            if not isinstance(candidate, Mapping):
                continue
            if len(probes) >= limit:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="probe-limit-reached",
                    handler="pcode-addi-end-pointer-owner",
                ))
                continue
            lifetime_candidate, candidate_diag = (
                _materialize_end_pointer_candidate(
                    source_text,
                    function=function,
                    candidate=candidate,
                )
            )
            if lifetime_candidate is None:
                diagnostics.append(candidate_diag)
                continue
            if len(materialized_labels) >= remaining_target_slots:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="duplicate-ranked-end-pointer-target",
                    handler="pcode-addi-end-pointer-owner",
                ))
                continue
            if lifetime_candidate.source_text in seen_source:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="duplicate-source-move",
                    handler="pcode-addi-end-pointer-owner",
                ))
                continue
            label = (
                "window-order-ranked-end-pointer-"
                f"ig{target_ig}-"
                f"{direction}-"
                f"{len(probes)}"
            )
            candidate_diag["probe_label"] = label
            metadata = dict(lifetime_candidate.metadata)
            metadata["probe_label"] = label
            source_diff = _source_diff(source_text, lifetime_candidate.source_text)
            seen_source.add(lifetime_candidate.source_text)
            probes.append(
                LifetimeLayoutProbe(
                    label=label,
                    operator="window-order-source-steering",
                    description=(
                        "Materialize ranked end-pointer owner span for a "
                        "pcode addi window-order fallback attribution."
                    ),
                    source_text=lifetime_candidate.source_text,
                    provenance={
                        "kind": lifetime_candidate.provenance_kind,
                        "lead": dict(lead),
                        "source_attribution": _source_attr_dict(source_attr),
                        "synthetic_source_probe": dict(synthetic_probe),
                        "source_diff": source_diff,
                        **metadata,
                    },
                )
            )
            materialized_labels.append(label)
            materialized_meta.append(metadata)
            diagnostics.append(candidate_diag)
            if first_source_diff is None:
                first_source_diff = source_diff

        summary = {
            "ranked_end_pointer_candidates": len([
                item for item in ranked_candidates if isinstance(item, Mapping)
            ]),
            "materialized_end_pointer_candidates": len(materialized_meta),
            "per_target_materialization_limit": ranked_end_pointer_limit,
            "reasons": _candidate_reason_counts(diagnostics),
        }
        synthetic_probe["ranked_end_pointer_candidate_diagnostics"] = diagnostics
        synthetic_probe[
            "materialized_ranked_end_pointer_source_candidates"
        ] = materialized_meta
        synthetic_probe["ranked_end_pointer_materialization_summary"] = summary
        diag["synthetic_source_probe"] = synthetic_probe
        diag["ranked_end_pointer_candidate_diagnostics"] = diagnostics
        diag["ranked_end_pointer_materialization_summary"] = summary
        if materialized_labels:
            ranked_end_pointer_materialized_counts[target_ig] = (
                ranked_end_pointer_materialized_counts.get(target_ig, 0)
                + len(materialized_labels)
            )
            diag["status"] = "materialized"
            diag["materialized_probe_labels"] = materialized_labels
            if first_source_diff is not None:
                diag["source_diff"] = first_source_diff
            diag.pop("terminal_blocker", None)
            return True
        diag["terminal_blocker"] = (
            "ranked-owner-candidates-not-materializable"
            if diagnostics else default_blocker
        )
        return False

    def materialize_ranked_li_constant_candidates(
        *,
        diag: dict[str, Any],
        lead: Mapping[str, Any],
        target_ig: int,
        direction: str,
        source_attr: Any,
        synthetic_metadata: Mapping[str, Any],
        default_blocker: str,
    ) -> bool:
        ranked_candidates = synthetic_metadata.get(
            "ranked_li_constant_source_candidates"
        )
        if not isinstance(ranked_candidates, list) or not ranked_candidates:
            return False

        synthetic_probe = dict(diag.get("synthetic_source_probe") or synthetic_metadata)
        diagnostics: list[dict[str, Any]] = []
        materialized_labels: list[str] = []
        materialized_meta: list[dict[str, Any]] = []
        first_source_diff: str | None = None
        first_source_hunks: list[dict[str, Any]] | None = None
        remaining_target_slots = (
            ranked_li_constant_limit
            - ranked_li_constant_materialized_counts.get(target_ig, 0)
        )
        if remaining_target_slots <= 0:
            diag["synthetic_source_probe"] = synthetic_probe
            diag["terminal_blocker"] = "duplicate-ranked-li-constant-target"
            return False
        for candidate in ranked_candidates:
            if not isinstance(candidate, Mapping):
                continue
            if len(probes) >= limit:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="probe-limit-reached",
                    handler="li-constant-threshold-owner",
                ))
                continue
            lifetime_candidate, candidate_diag = _materialize_li_constant_candidate(
                source_text,
                function=function,
                candidate=candidate,
            )
            if lifetime_candidate is None:
                diagnostics.append(candidate_diag)
                continue
            if len(materialized_labels) >= remaining_target_slots:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="duplicate-ranked-li-constant-target",
                    handler="li-constant-threshold-owner",
                ))
                continue
            if lifetime_candidate.source_text in seen_source:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="duplicate-source-move",
                    handler="li-constant-threshold-owner",
                ))
                continue
            label = (
                "window-order-li-constant-"
                f"ig{target_ig}-"
                f"{direction}-"
                f"{len(probes)}"
            )
            candidate_diag["probe_label"] = label
            metadata = dict(lifetime_candidate.metadata)
            metadata["probe_label"] = label
            source_diff = _source_diff(source_text, lifetime_candidate.source_text)
            source_hunks = [
                hunk.to_dict()
                for hunk in diff_line_hunks(
                    source_text,
                    lifetime_candidate.source_text,
                    hunk_prefix="li-constant",
                )
            ]
            metadata["source_diff"] = source_diff
            metadata["source_hunks"] = source_hunks
            seen_source.add(lifetime_candidate.source_text)
            probes.append(
                LifetimeLayoutProbe(
                    label=label,
                    operator="window-order-source-steering",
                    description=(
                        "Materialize a li-constant source owner for a "
                        "window-order fallback attribution."
                    ),
                    source_text=lifetime_candidate.source_text,
                    provenance={
                        "kind": lifetime_candidate.provenance_kind,
                        "lead": dict(lead),
                        "source_attribution": _source_attr_dict(source_attr),
                        "synthetic_source_probe": dict(synthetic_probe),
                        "source_diff": source_diff,
                        "source_hunks": source_hunks,
                        **metadata,
                    },
                )
            )
            materialized_labels.append(label)
            materialized_meta.append(metadata)
            diagnostics.append(candidate_diag)
            if first_source_diff is None:
                first_source_diff = source_diff
            if first_source_hunks is None:
                first_source_hunks = source_hunks

        summary = {
            "ranked_li_constant_candidates": len([
                item for item in ranked_candidates if isinstance(item, Mapping)
            ]),
            "materialized_li_constant_candidates": len(materialized_meta),
            "per_target_materialization_limit": ranked_li_constant_limit,
            "reasons": _candidate_reason_counts(diagnostics),
        }
        synthetic_probe["ranked_li_constant_candidate_diagnostics"] = diagnostics
        synthetic_probe[
            "materialized_ranked_li_constant_source_candidates"
        ] = materialized_meta
        synthetic_probe["ranked_li_constant_materialization_summary"] = summary
        diag["synthetic_source_probe"] = synthetic_probe
        diag["ranked_li_constant_candidate_diagnostics"] = diagnostics
        diag["ranked_li_constant_materialization_summary"] = summary
        if materialized_labels:
            ranked_li_constant_materialized_counts[target_ig] = (
                ranked_li_constant_materialized_counts.get(target_ig, 0)
                + len(materialized_labels)
            )
            diag["status"] = "materialized"
            diag["materialized_probe_labels"] = materialized_labels
            if first_source_diff is not None:
                diag["source_diff"] = first_source_diff
            if first_source_hunks is not None:
                diag["source_hunks"] = first_source_hunks
            diag.pop("terminal_blocker", None)
            return True
        diag["terminal_blocker"] = (
            "li-constant-owner-not-materializable"
            if diagnostics else default_blocker
        )
        return False

    def materialize_ranked_pointer_walk_add_candidates(
        *,
        diag: dict[str, Any],
        lead: Mapping[str, Any],
        target_ig: int,
        direction: str,
        source_attr: Any,
        synthetic_metadata: Mapping[str, Any],
        default_blocker: str,
    ) -> bool:
        ranked_candidates = synthetic_metadata.get(
            "ranked_pointer_walk_add_source_candidates"
        )
        if not isinstance(ranked_candidates, list) or not ranked_candidates:
            return False

        synthetic_probe = dict(diag.get("synthetic_source_probe") or synthetic_metadata)
        diagnostics: list[dict[str, Any]] = []
        materialized_labels: list[str] = []
        materialized_meta: list[dict[str, Any]] = []
        first_source_diff: str | None = None
        first_source_hunks: list[dict[str, Any]] | None = None
        remaining_target_slots = (
            ranked_pointer_walk_add_limit
            - ranked_pointer_walk_add_materialized_counts.get(target_ig, 0)
        )
        if remaining_target_slots <= 0:
            diag["synthetic_source_probe"] = synthetic_probe
            diag["terminal_blocker"] = "duplicate-ranked-pointer-walk-add-target"
            return False
        for candidate in ranked_candidates:
            if not isinstance(candidate, Mapping):
                continue
            if len(probes) >= limit:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="probe-limit-reached",
                    handler="pointer-walk-add-temp-owner",
                ))
                continue
            lifetime_candidate, candidate_diag = (
                _materialize_pointer_walk_add_candidate(
                    source_text,
                    function=function,
                    candidate=candidate,
                )
            )
            if lifetime_candidate is None:
                diagnostics.append(candidate_diag)
                continue
            if len(materialized_labels) >= remaining_target_slots:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="duplicate-ranked-pointer-walk-add-target",
                    handler="pointer-walk-add-temp-owner",
                ))
                continue
            if lifetime_candidate.source_text in seen_source:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="duplicate-source-move",
                    handler="pointer-walk-add-temp-owner",
                ))
                continue
            label = (
                "window-order-pointer-walk-add-"
                f"ig{target_ig}-"
                f"{direction}-"
                f"{len(probes)}"
            )
            candidate_diag["probe_label"] = label
            metadata = dict(lifetime_candidate.metadata)
            metadata["probe_label"] = label
            source_diff = _source_diff(source_text, lifetime_candidate.source_text)
            source_hunks = [
                hunk.to_dict()
                for hunk in diff_line_hunks(
                    source_text,
                    lifetime_candidate.source_text,
                    hunk_prefix="pointer-walk-add",
                )
            ]
            metadata["source_diff"] = source_diff
            metadata["source_hunks"] = source_hunks
            seen_source.add(lifetime_candidate.source_text)
            probes.append(
                LifetimeLayoutProbe(
                    label=label,
                    operator="window-order-source-steering",
                    description=(
                        "Materialize a pointer-walk add source owner for a "
                        "window-order fallback attribution."
                    ),
                    source_text=lifetime_candidate.source_text,
                    provenance={
                        "kind": lifetime_candidate.provenance_kind,
                        "lead": dict(lead),
                        "source_attribution": _source_attr_dict(source_attr),
                        "synthetic_source_probe": dict(synthetic_probe),
                        "source_diff": source_diff,
                        "source_hunks": source_hunks,
                        **metadata,
                    },
                )
            )
            materialized_labels.append(label)
            materialized_meta.append(metadata)
            diagnostics.append(candidate_diag)
            if first_source_diff is None:
                first_source_diff = source_diff
            if first_source_hunks is None:
                first_source_hunks = source_hunks

        summary = {
            "ranked_pointer_walk_add_candidates": len([
                item for item in ranked_candidates if isinstance(item, Mapping)
            ]),
            "materialized_pointer_walk_add_candidates": len(materialized_meta),
            "per_target_materialization_limit": ranked_pointer_walk_add_limit,
            "reasons": _candidate_reason_counts(diagnostics),
        }
        synthetic_probe["ranked_pointer_walk_add_candidate_diagnostics"] = (
            diagnostics
        )
        synthetic_probe[
            "materialized_ranked_pointer_walk_add_source_candidates"
        ] = materialized_meta
        synthetic_probe["ranked_pointer_walk_add_materialization_summary"] = (
            summary
        )
        diag["synthetic_source_probe"] = synthetic_probe
        diag["ranked_pointer_walk_add_candidate_diagnostics"] = diagnostics
        diag["ranked_pointer_walk_add_materialization_summary"] = summary
        if materialized_labels:
            ranked_pointer_walk_add_materialized_counts[target_ig] = (
                ranked_pointer_walk_add_materialized_counts.get(target_ig, 0)
                + len(materialized_labels)
            )
            diag["status"] = "materialized"
            diag["materialized_probe_labels"] = materialized_labels
            if first_source_diff is not None:
                diag["source_diff"] = first_source_diff
            if first_source_hunks is not None:
                diag["source_hunks"] = first_source_hunks
            diag.pop("terminal_blocker", None)
            return True
        diag["terminal_blocker"] = (
            "pointer-walk-add-owner-not-materializable"
            if diagnostics else default_blocker
        )
        return False

    def materialize_ranked_local_owner_candidates(
        *,
        diag: dict[str, Any],
        lead: Mapping[str, Any],
        target_ig: int,
        direction: str,
        source_attr: Any,
        local_name: str,
        owner_candidates: list[dict[str, Any]],
    ) -> bool:
        if not owner_candidates:
            return False
        decl_type = (
            _safe_decl_type_text(_attr_value(source_attr, "type"))
            or _decl_type_from_ranked_candidates(local_name, owner_candidates)
        )
        diagnostics: list[dict[str, Any]] = []
        materialized_labels: list[str] = []
        materialized_meta: list[dict[str, Any]] = []
        first_source_diff: str | None = None
        if target_ig in ranked_local_materialized_targets:
            diag["terminal_blocker"] = "duplicate-ranked-local-owner-target"
            return False
        if decl_type is None:
            for candidate in owner_candidates:
                diagnostics.append(_candidate_materialization_diagnostic(
                    candidate,
                    status="rejected",
                    reason="missing-safe-local-declaration-type",
                    handler="loop-index-read-anchor",
                ))
        else:
            for candidate in owner_candidates:
                if len(probes) >= limit:
                    diagnostics.append(_candidate_materialization_diagnostic(
                        candidate,
                        status="rejected",
                        reason="probe-limit-reached",
                        handler="loop-index-read-anchor",
                    ))
                    continue
                lifetime_candidate, candidate_diag = (
                    _materialize_loop_index_read_anchor(
                        source_text,
                        function=function,
                        local_name=local_name,
                        decl_type=decl_type,
                        candidate=candidate,
                    )
                )
                if lifetime_candidate is None:
                    diagnostics.append(candidate_diag)
                    continue
                if lifetime_candidate.source_text in seen_source:
                    diagnostics.append(_candidate_materialization_diagnostic(
                        candidate,
                        status="rejected",
                        reason="duplicate-source-move",
                        handler="loop-index-read-anchor",
                    ))
                    continue
                label = (
                    "window-order-ranked-local-owner-"
                    f"ig{target_ig}-"
                    f"{direction}-"
                    f"{_safe_label_part(local_name)}-"
                    f"{len(probes)}"
                )
                candidate_diag["probe_label"] = label
                metadata = dict(lifetime_candidate.metadata)
                metadata["probe_label"] = label
                seen_source.add(lifetime_candidate.source_text)
                probes.append(
                    LifetimeLayoutProbe(
                        label=label,
                        operator="window-order-source-steering",
                        description=(
                            f"Materialize ranked source owner read for local "
                            f"{local_name} near a window-order fallback anchor."
                        ),
                        source_text=lifetime_candidate.source_text,
                        provenance={
                            "kind": lifetime_candidate.provenance_kind,
                            "lead": dict(lead),
                            "source_attribution": _source_attr_dict(source_attr),
                            "ranked_source_owner_candidate": (
                                metadata.get("ranked_source_owner_candidate")
                            ),
                            **metadata,
                        },
                    )
                )
                materialized_labels.append(label)
                materialized_meta.append(metadata)
                diagnostics.append(candidate_diag)
                if first_source_diff is None:
                    first_source_diff = _source_diff(
                        source_text,
                        lifetime_candidate.source_text,
                    )
                break
        summary = {
            "ranked_local_candidates": len(owner_candidates),
            "materialized_local_candidates": len(materialized_meta),
            "reasons": _candidate_reason_counts(diagnostics),
        }
        diag["ranked_source_owner_candidate_diagnostics"] = diagnostics
        diag["materialized_ranked_source_owner_candidates"] = materialized_meta
        diag["ranked_source_owner_materialization_summary"] = summary
        if materialized_labels:
            ranked_local_materialized_targets.add(target_ig)
            diag["status"] = "materialized"
            diag["materialized_probe_labels"] = materialized_labels
            if first_source_diff is not None:
                diag["source_diff"] = first_source_diff
            diag.pop("terminal_blocker", None)
            return True
        diag["terminal_blocker"] = "ranked-owner-candidates-not-materializable"
        return False

    def materialize_field_load_source_candidates(
        *,
        diag: dict[str, Any],
        lead: Mapping[str, Any],
        target_ig: int,
        direction: str,
        source_attr: Any,
    ) -> None:
        provenance_attr = source_attr
        pcode_metadata: dict[str, Any] = {}
        if _pcode_field_load_like(source_attr):
            resolved_attr, pcode_metadata, pcode_blocker = (
                _resolved_pcode_field_load_source_attr(
                    source_text,
                    function=function,
                    source_attr=source_attr,
                    source_attributions=source_attributions,
                    search_span=function_body_span,
                )
            )
            diag.update({
                key: value for key, value in pcode_metadata.items()
                if key in {
                    "pcode_first_def",
                    "base_virtual",
                    "field_offset",
                    "base_source_attribution",
                    "base_var",
                    "base_type",
                    "field_name",
                }
            })
            if resolved_attr is None:
                diag["field_load_source_probe"] = pcode_metadata
                diag["field_load_materialization_summary"] = {
                    "field_load_source_candidates": 0,
                    "materialized_field_load_source_candidates": 0,
                    "reasons": {pcode_blocker or "field-load-source-span-not-found": 1},
                }
                diag["terminal_blocker"] = (
                    pcode_blocker or "field-load-source-span-not-found"
                )
                return
            source_attr = resolved_attr
        candidates, resolver_metadata, resolver_blocker = (
            _field_load_source_candidates(
                source_text,
                function=function,
                source_attr=source_attr,
                search_span=function_body_span,
            )
        )
        source_attr_kind = _attr_value(source_attr, "kind")
        probe_provenance_kind = _field_load_probe_provenance_kind(provenance_attr)
        if pcode_metadata:
            resolver_metadata.update(pcode_metadata)
        diag["field_load_source_probe"] = resolver_metadata
        diag["source_attribution_kind"] = source_attr_kind
        if source_attr_kind == "copy/coalesce-source":
            diag["copy_coalesce_source_probe"] = (
                _copy_coalesce_source_probe_metadata(source_attr)
            )
        diag["field_load_source_candidates"] = [
            _field_load_candidate_dict(candidate) for candidate in candidates
        ]
        diagnostics: list[dict[str, Any]] = []
        materialized_labels: list[str] = []
        materialized_meta: list[dict[str, Any]] = []
        first_source_diff: str | None = None
        first_source_hunks: list[dict[str, Any]] | None = None

        if not candidates:
            diag["field_load_candidate_diagnostics"] = diagnostics
            diag["field_load_materialization_summary"] = {
                "field_load_source_candidates": 0,
                "materialized_field_load_source_candidates": 0,
                "reasons": {resolver_blocker or "field-load-source-span-not-found": 1},
            }
            diag["terminal_blocker"] = (
                resolver_blocker or "field-load-source-span-not-found"
            )
            return

        for candidate in candidates:
            candidate_payload = _field_load_candidate_dict(candidate)
            if len(probes) >= limit:
                diagnostics.append({
                    **candidate_payload,
                    "status": "rejected",
                    "reason": "field-load-candidate-limit-exhausted",
                    "handler": "field-load-inline-temp",
                })
                continue
            lifetime_candidate, candidate_diag = _materialize_field_load_candidate(
                source_text,
                function=function,
                candidate=candidate,
                provenance_kind=probe_provenance_kind,
            )
            if lifetime_candidate is None:
                diagnostics.append(candidate_diag)
                continue
            if lifetime_candidate.source_text in seen_source:
                diagnostics.append({
                    **candidate_payload,
                    "status": "rejected",
                    "reason": "duplicate-source-move",
                    "handler": "field-load-inline-temp",
                })
                continue

            label = (
                "window-order-field-load-"
                f"ig{target_ig}-"
                f"{direction}-"
                f"{candidate.kind}-"
                f"{len(probes)}"
            )
            candidate_diag["probe_label"] = label
            source_diff = _source_diff(source_text, lifetime_candidate.source_text)
            source_hunks = [
                hunk.to_dict()
                for hunk in diff_line_hunks(
                    source_text,
                    lifetime_candidate.source_text,
                    hunk_prefix="field-load",
                )
            ]
            metadata = dict(lifetime_candidate.metadata)
            field_candidate = dict(metadata["field_load_source_candidate"])
            field_candidate.update({
                "probe_label": label,
                "materialization_kind": candidate.kind,
                "synthetic_local": metadata.get("synthetic_local"),
                "temp_type": metadata.get("temp_type"),
            })
            if pcode_metadata:
                field_candidate.update({
                    key: value for key, value in pcode_metadata.items()
                    if key in {
                        "pcode_first_def",
                        "base_virtual",
                        "field_offset",
                        "base_source_attribution",
                        "base_type",
                    }
                })
            metadata["field_load_source_candidate"] = field_candidate
            metadata["probe_label"] = label
            metadata["source_hunks"] = source_hunks
            metadata["source_diff"] = source_diff
            if pcode_metadata:
                metadata["pcode_first_def"] = pcode_metadata.get("pcode_first_def")
            seen_source.add(lifetime_candidate.source_text)
            probes.append(
                LifetimeLayoutProbe(
                    label=label,
                    operator="window-order-source-steering",
                    description=(
                        "Materialize a field-load source-order probe for a "
                        "window-order fallback attribution."
                    ),
                    source_text=lifetime_candidate.source_text,
                    provenance={
                        "kind": lifetime_candidate.provenance_kind,
                        "lead": dict(lead),
                        "source_attribution": _source_attr_dict(provenance_attr),
                        "field_load_source_candidate": field_candidate,
                        "source_hunks": source_hunks,
                        "source_diff": source_diff,
                        **({
                            "pcode_first_def": pcode_metadata.get("pcode_first_def"),
                            "base_virtual": pcode_metadata.get("base_virtual"),
                            "field_offset": pcode_metadata.get("field_offset"),
                            "base_source_attribution": pcode_metadata.get(
                                "base_source_attribution"
                            ),
                        } if pcode_metadata else {}),
                        **metadata,
                    },
                )
            )
            materialized_labels.append(label)
            materialized_meta.append(field_candidate)
            diagnostics.append(candidate_diag)
            if first_source_diff is None:
                first_source_diff = source_diff
            if first_source_hunks is None:
                first_source_hunks = source_hunks

        summary = {
            "field_load_source_candidates": len(candidates),
            "materialized_field_load_source_candidates": len(materialized_meta),
            "candidate_limit": limit,
            "reasons": _candidate_reason_counts(diagnostics),
        }
        diag["field_load_candidate_diagnostics"] = diagnostics
        diag["field_load_materialization_summary"] = summary
        if materialized_labels:
            diag["status"] = "materialized"
            diag["materialized_probe_labels"] = materialized_labels
            diag["field_load_source_candidate"] = materialized_meta[0]
            diag["materialized_field_load_source_candidates"] = materialized_meta
            if first_source_diff is not None:
                diag["source_diff"] = first_source_diff
            if first_source_hunks is not None:
                diag["source_hunks"] = first_source_hunks
            diag.pop("terminal_blocker", None)
            return
        reasons = summary["reasons"]
        if reasons.get("field-load-candidate-limit-exhausted"):
            diag["terminal_blocker"] = "field-load-candidate-limit-exhausted"
        elif reasons.get("field-load-no-safe-insertion-point"):
            diag["terminal_blocker"] = "field-load-no-safe-insertion-point"
        else:
            diag["terminal_blocker"] = "field-load-owner-not-materializable"

    def materialize_call_return_source_candidate(
        *,
        diag: dict[str, Any],
        lead: Mapping[str, Any],
        target_ig: int,
        direction: str,
        source_attr: Any,
    ) -> None:
        synthetic = _call_return_owner_split(groups, source_attr)
        diag["call_return_source_probe"] = dict(synthetic.metadata)
        diag["source_attribution_kind"] = _attr_value(source_attr, "kind")
        if not synthetic.candidates:
            diag["terminal_blocker"] = (
                synthetic.terminal_blocker or "call-return-owner-copy-not-found"
            )
            return
        if len(probes) >= limit:
            diag["terminal_blocker"] = "probe-limit-reached"
            return

        candidate = synthetic.candidates[0]
        owner = candidate.owner
        if owner is None:
            diag["terminal_blocker"] = "call-return-owner-copy-not-found"
            return
        split = _split_owner_assignment_source(source_text, owner)
        if split is None:
            local_type = _function_local_type(
                source_text,
                name=owner.local_name,
                search_span=function_body_span,
            )
            if local_type is not None:
                split = _split_owner_assignment_source_with_type(
                    source_text,
                    function=function,
                    owner=owner,
                    type_text=local_type,
                )
        if split is None:
            diag["terminal_blocker"] = "call-return-owner-type-unresolved"
            return
        candidate_text, split_meta = split
        if candidate_text == source_text:
            diag["terminal_blocker"] = "source-unchanged"
            return
        if candidate_text in seen_source:
            diag["terminal_blocker"] = "synthetic-temp-duplicate-source"
            return

        label = (
            "window-order-call-return-"
            f"ig{target_ig}-"
            f"{direction}-"
            f"{len(probes)}"
        )
        source_diff = _source_diff(source_text, candidate_text)
        source_hunks = [
            hunk.to_dict()
            for hunk in diff_line_hunks(
                source_text,
                candidate_text,
                hunk_prefix="call-return",
            )
        ]
        call_return_probe = dict(candidate.metadata)
        call_return_probe.update(split_meta)
        call_return_probe.update({
            "probe_label": label,
            "source_hunks": source_hunks,
            "source_diff": source_diff,
        })
        seen_source.add(candidate_text)
        probes.append(
            LifetimeLayoutProbe(
                label=label,
                operator="window-order-source-steering",
                description=(
                    "Split a named call-return owner into a synthetic local for "
                    "window-order source steering."
                ),
                source_text=candidate_text,
                provenance={
                    "kind": "window-order-call-return-source-order",
                    "lead": dict(lead),
                    "source_attribution": _source_attr_dict(source_attr),
                    "moved_local": owner.local_name,
                    "call_return_source_probe": call_return_probe,
                    "source_hunks": source_hunks,
                    "source_diff": source_diff,
                },
            )
        )
        diag["status"] = "materialized"
        diag["materialized_probe_labels"] = [label]
        diag["call_return_source_probe"] = call_return_probe
        diag["source_hunks"] = source_hunks
        diag["source_diff"] = source_diff
        diag.pop("terminal_blocker", None)

    def materialize_synthetic_result(
        *,
        diag: dict[str, Any],
        lead: Mapping[str, Any],
        target_ig: int,
        direction: str,
        source_attr: Any,
        synthetic: _SyntheticOwnerResult,
        default_blocker: str,
    ) -> None:
        if not synthetic.candidates:
            materializers = {
                "indexed_byte": materialize_ranked_indexed_byte_candidates,
                "end_pointer": materialize_ranked_end_pointer_candidates,
                "pointer_walk_add": materialize_ranked_pointer_walk_add_candidates,
            }
            owner_order = synthetic.metadata.get("ranked_owner_candidate_order")
            if not isinstance(owner_order, list):
                owner_order = ["indexed_byte", "end_pointer"]
            materialized = False
            for owner_kind in owner_order:
                materializer = materializers.get(str(owner_kind))
                if materializer is None:
                    continue
                materialized = materializer(
                    diag=diag,
                    lead=lead,
                    target_ig=target_ig,
                    direction=direction,
                    source_attr=source_attr,
                    synthetic_metadata=synthetic.metadata,
                    default_blocker=synthetic.terminal_blocker or default_blocker,
                )
                if materialized:
                    break
            if not materialized and "synthetic_source_probe" not in diag:
                diag["synthetic_source_probe"] = synthetic.metadata
                diag["terminal_blocker"] = (
                    synthetic.terminal_blocker or default_blocker
                )
            return

        materialized_labels: list[str] = []
        materialized_meta: list[dict[str, Any]] = []
        first_source_diff: str | None = None
        unsafe_count = 0
        duplicate_count = 0
        for candidate in synthetic.candidates:
            owner = candidate.owner
            if owner is None:
                unsafe_count += 1
                continue
            diag.setdefault("source_local", owner.local_name)
            if len(probes) >= limit:
                break
            probe = _materialize_synthetic_owner_probe(
                source_text,
                lead=lead,
                target_ig=target_ig,
                direction=direction,
                source_attr=source_attr,
                owner=owner,
                synthetic_source_probe=candidate.metadata,
                existing_probe_count=len(probes),
            )
            if probe is None:
                unsafe_count += 1
                continue
            target_source_key = (target_ig, probe.source_text)
            if target_source_key in seen_synthetic_source_by_target:
                duplicate_count += 1
                continue
            seen_source.add(probe.source_text)
            seen_synthetic_source_by_target.add(target_source_key)
            probes.append(probe)
            materialized_labels.append(probe.label)
            probe_meta = probe.provenance["synthetic_source_probe"]
            materialized_meta.append(probe_meta)
            if first_source_diff is None:
                first_source_diff = _source_diff(source_text, probe.source_text)

        if materialized_labels:
            diag["status"] = "materialized"
            diag["materialized_probe_labels"] = materialized_labels
            diag["synthetic_source_probe"] = materialized_meta[0]
            if len(materialized_meta) > 1:
                diag["synthetic_source_candidates"] = materialized_meta
            diag["source_diff"] = first_source_diff or ""
        elif len(probes) >= limit:
            diag["synthetic_source_probe"] = synthetic.metadata
            diag["terminal_blocker"] = "probe-limit-reached"
        elif unsafe_count:
            diag["synthetic_source_probe"] = synthetic.metadata
            diag["terminal_blocker"] = "source-owner-transform-unsafe"
        elif duplicate_count:
            diag["synthetic_source_probe"] = synthetic.metadata
            diag["terminal_blocker"] = "synthetic-temp-duplicate-source"
        else:
            diag["synthetic_source_probe"] = synthetic.metadata
            diag["terminal_blocker"] = synthetic.terminal_blocker or default_blocker

    for lead in leads:
        target_ig = _lead_target_ig(lead)
        diag: dict[str, Any] = {
            "lead": dict(lead),
            "status": "blocked",
        }
        if target_ig is None:
            diag["status"] = "needs_context"
            diag["terminal_blocker"] = "missing-target-ig"
            lead_diagnostics.append(diag)
            continue
        diag["target_ig"] = target_ig

        direction = _lead_direction(lead)
        if direction is None:
            diag["status"] = "needs_context"
            diag["terminal_blocker"] = "invalid-order-move"
            lead_diagnostics.append(diag)
            continue
        diag["direction"] = direction

        source_attr = _source_attr_for_ig(source_attributions, target_ig)
        if source_attr is None:
            diag["status"] = "needs_context"
            diag["terminal_blocker"] = "missing-source-attribution"
            lead_diagnostics.append(diag)
            continue
        source_attr_dict = _source_attr_dict(source_attr)
        diag["source_attribution"] = source_attr_dict
        source_kind = _attr_value(source_attr, "kind")
        provenance_source_attr = source_attr
        owner_target_ig = target_ig
        copy_product_metadata: dict[str, Any] | None = None
        if source_kind == "copy/coalesce-product":
            copy_product_source = _gpr_copy_product_source(
                source_attr,
                target_ig=target_ig,
            )
            if copy_product_source is not None:
                resolved_source_attr = _source_attr_for_ig(
                    source_attributions,
                    copy_product_source.source_ig,
                )
                copy_product_metadata = _copy_product_chain_metadata(
                    source_attributions,
                    target_ig=target_ig,
                    copy_attr=source_attr,
                    copy_product_source=copy_product_source,
                    resolved_source_attr=resolved_source_attr,
                )
                diag["copy_product_source"] = copy_product_metadata
                if resolved_source_attr is None:
                    synthetic = _SyntheticOwnerResult(
                        (),
                        copy_product_metadata,
                        "copy-product-source-unmapped",
                    )
                    materialize_synthetic_result(
                        diag=diag,
                        lead=lead,
                        target_ig=target_ig,
                        direction=direction,
                        source_attr=provenance_source_attr,
                        synthetic=synthetic,
                        default_blocker="implicit-temp-no-safe-source-move",
                    )
                    lead_diagnostics.append(diag)
                    continue
                source_attr = resolved_source_attr
                source_kind = _attr_value(source_attr, "kind")
                owner_target_ig = copy_product_source.source_ig
        if source_kind == "implicit-temp":
            synthetic = _implicit_add_owner(
                source_text,
                groups,
                source_attributions,
                owner_target_ig,
                source_attr,
                search_span=function_body_span,
            )
            if copy_product_metadata is not None:
                synthetic = _with_copy_product_metadata(
                    synthetic,
                    copy_product_metadata,
                )
            materialize_synthetic_result(
                diag=diag,
                lead=lead,
                target_ig=target_ig,
                direction=direction,
                source_attr=provenance_source_attr,
                synthetic=synthetic,
                default_blocker="implicit-temp-no-safe-source-move",
            )
            lead_diagnostics.append(diag)
            continue
        if source_kind == "fpr-temp":
            synthetic = _fpr_temp_owner(
                groups,
                source_attributions,
                owner_target_ig,
                source_attr,
            )
            if copy_product_metadata is not None:
                synthetic = _with_copy_product_metadata(
                    synthetic,
                    copy_product_metadata,
                )
            materialize_synthetic_result(
                diag=diag,
                lead=lead,
                target_ig=target_ig,
                direction=direction,
                source_attr=provenance_source_attr,
                synthetic=synthetic,
                default_blocker="unsupported-source-attribution-kind",
            )
            lead_diagnostics.append(diag)
            continue
        if _pcode_field_load_like(source_attr):
            materialize_field_load_source_candidates(
                diag=diag,
                lead=lead,
                target_ig=target_ig,
                direction=direction,
                source_attr=source_attr,
            )
            lead_diagnostics.append(diag)
            continue
        pcode_field_blocker = _pcode_field_address_blocker(source_attr)
        if pcode_field_blocker is not None:
            diag["terminal_blocker"] = pcode_field_blocker
            lead_diagnostics.append(diag)
            continue
        if source_kind == "first-def":
            immediate = _li_first_def_immediate(source_attr)
            if immediate is None:
                diag["terminal_blocker"] = "first-def-source-owner-unsupported-shape"
                lead_diagnostics.append(diag)
                continue
            ranked_candidates = _rank_li_constant_source_candidates(
                source_text,
                immediate=immediate,
                search_span=function_body_span,
            )
            synthetic_metadata = {
                "handler": "li-constant-threshold-owner",
                "expression": _attr_value(source_attr, "expression"),
                "immediate_value": immediate,
                "ranked_li_constant_source_candidates": ranked_candidates,
            }
            materialized = materialize_ranked_li_constant_candidates(
                diag=diag,
                lead=lead,
                target_ig=target_ig,
                direction=direction,
                source_attr=provenance_source_attr,
                synthetic_metadata=synthetic_metadata,
                default_blocker=(
                    "li-constant-source-owner-not-found"
                    if not ranked_candidates else "li-constant-owner-not-materializable"
                ),
            )
            if not materialized and "synthetic_source_probe" not in diag:
                diag["synthetic_source_probe"] = synthetic_metadata
                diag["terminal_blocker"] = "li-constant-source-owner-not-found"
            lead_diagnostics.append(diag)
            continue
        if source_kind in _SYNTHETIC_NO_SOURCE_KINDS:
            diag["terminal_blocker"] = "implicit-temp-no-safe-source-move"
            lead_diagnostics.append(diag)
            continue
        if source_kind == "call-return":
            materialize_call_return_source_candidate(
                diag=diag,
                lead=lead,
                target_ig=target_ig,
                direction=direction,
                source_attr=source_attr,
            )
            lead_diagnostics.append(diag)
            continue
        if _field_load_like_source_kind(source_attr) is not None:
            materialize_field_load_source_candidates(
                diag=diag,
                lead=lead,
                target_ig=target_ig,
                direction=direction,
                source_attr=source_attr,
            )
            lead_diagnostics.append(diag)
            continue
        if source_kind not in {None, "local"}:
            diag["terminal_blocker"] = "unsupported-source-attribution-kind"
            lead_diagnostics.append(diag)
            continue
        local_name = _attr_value(source_attr, "name")
        if not isinstance(local_name, str) or not local_name:
            diag["terminal_blocker"] = "missing-local-source-name"
            lead_diagnostics.append(diag)
            continue
        diag["source_local"] = local_name

        matches = movable_by_local.get(local_name, [])
        if len(matches) > 1:
            diag["movable_write_count"] = len(matches)
            diag["terminal_blocker"] = "ambiguous-movable-local-write"
            lead_diagnostics.append(diag)
            continue
        source_line = _attr_value(source_attr, "source_line")
        if isinstance(source_line, int):
            filtered_matches = [
                match for match in matches
                if (
                    match[2].index_range
                    and match[1][match[2].index_range[0]].line_range[0]
                    <= source_line
                    <= match[1][match[2].index_range[1]].line_range[1]
                )
            ]
            if filtered_matches:
                matches = filtered_matches
        diag["movable_write_count"] = len(matches)
        if len(matches) == 0:
            synthetic = _local_fpr_owner_split(
                groups,
                local_name,
                source_attr,
                target_ig=target_ig,
            )
            materialize_synthetic_result(
                diag=diag,
                lead=lead,
                target_ig=target_ig,
                direction=direction,
                source_attr=source_attr,
                synthetic=synthetic,
                default_blocker="local-source-owner-unsupported-rhs",
            )
            owner_candidates = _rank_local_owner_candidates(
                source_text,
                local_name,
                source_line=source_line,
                search_span=function_body_span,
            )
            if owner_candidates:
                diag["ranked_source_owner_candidates"] = owner_candidates
                has_loop_index_owner = any(
                    candidate.get("kind") == "loop-index-header"
                    for candidate in owner_candidates
                )
                if diag.get("status") != "materialized" and has_loop_index_owner:
                    materialize_ranked_local_owner_candidates(
                        diag=diag,
                        lead=lead,
                        target_ig=target_ig,
                        direction=direction,
                        source_attr=source_attr,
                        local_name=local_name,
                        owner_candidates=owner_candidates,
                    )
            lead_diagnostics.append(diag)
            continue
        if len(matches) > 1:
            diag["terminal_blocker"] = "ambiguous-movable-local-write"
            lead_diagnostics.append(diag)
            continue

        group, sibs, unit = matches[0]
        legal = statement_move.legal_destinations(
            sibs,
            unit,
            escaped=escaped,
            locals_=set(group.locals_),
        )
        destinations = _candidate_destinations(
            direction=direction,
            unit=unit,
            legal=legal,
        )
        diag["legal_destinations"] = legal
        diag["candidate_destinations"] = destinations
        if not destinations:
            materialized_labels: list[str] = []
            materialized_meta: list[dict[str, Any]] = []
            first_source_diff: str | None = None
            duplicate_count = 0
            float_owner_blocker: str | None = None
            if _local_has_float_decl(groups, local_name):
                synthetic = _local_fpr_owner_split(
                    groups,
                    local_name,
                    source_attr,
                    target_ig=target_ig,
                )
                materialize_synthetic_result(
                    diag=diag,
                    lead=lead,
                    target_ig=target_ig,
                    direction=direction,
                    source_attr=source_attr,
                    synthetic=synthetic,
                    default_blocker="local-source-owner-unsupported-rhs",
                )
                if diag.get("status") == "materialized":
                    lead_diagnostics.append(diag)
                    continue
                float_owner_blocker = synthetic.terminal_blocker
            lifetime_candidates = (
                _pointer_walk_increment_sink_candidates(
                    source_text,
                    local_name,
                    search_span=function_body_span,
                )
                if function_body_span is not None
                else []
            )
            for lifetime_candidate in lifetime_candidates:
                if len(probes) >= limit:
                    break
                if lifetime_candidate.source_text in seen_source:
                    duplicate_count += 1
                    continue
                seen_source.add(lifetime_candidate.source_text)
                label = (
                    "window-order-local-lifetime-"
                    f"ig{target_ig}-"
                    f"{direction}-"
                    f"{_safe_label_part(local_name)}-"
                    f"{len(probes)}"
                )
                probes.append(
                    LifetimeLayoutProbe(
                        label=label,
                        operator="window-order-source-steering",
                        description=(
                            f"Adjust pointer-walk lifetime for source local "
                            f"{local_name} near a window-order fallback anchor."
                        ),
                        source_text=lifetime_candidate.source_text,
                        provenance={
                            "kind": lifetime_candidate.provenance_kind,
                            "lead": dict(lead),
                            "source_attribution": _source_attr_dict(source_attr),
                            "moved_local": local_name,
                            "local_lifetime_probe": dict(
                                lifetime_candidate.metadata
                            ),
                        },
                    )
                )
                materialized_labels.append(label)
                materialized_meta.append(dict(lifetime_candidate.metadata))
                if first_source_diff is None:
                    first_source_diff = _source_diff(
                        source_text,
                        lifetime_candidate.source_text,
                    )
            if materialized_labels:
                diag["status"] = "materialized"
                diag["materialized_probe_labels"] = materialized_labels
                diag["local_lifetime_probe"] = materialized_meta[0]
                if len(materialized_meta) > 1:
                    diag["local_lifetime_probe_candidates"] = materialized_meta
                diag["source_diff"] = first_source_diff or ""
            elif len(probes) >= limit:
                diag["terminal_blocker"] = "probe-limit-reached"
            elif duplicate_count:
                diag["terminal_blocker"] = "duplicate-source-move"
            elif float_owner_blocker:
                diag["terminal_blocker"] = float_owner_blocker
            else:
                diag["terminal_blocker"] = "no-legal-destination"
            lead_diagnostics.append(diag)
            continue

        materialized_labels: list[str] = []
        first_source_diff: str | None = None
        for dest in destinations:
            if len(probes) >= limit:
                break
            candidate_text = statement_move.apply_move(
                source_text,
                sibs,
                unit,
                dest,
            )
            if candidate_text == source_text or candidate_text in seen_source:
                continue
            seen_source.add(candidate_text)
            label = (
                "window-order-"
                f"ig{target_ig}-"
                f"{direction}-"
                f"{_safe_label_part(local_name)}-"
                f"{len(probes)}"
            )
            lo, hi = unit.index_range
            line_range = [
                sibs[lo].line_range[0],
                sibs[hi].line_range[1],
            ]
            probes.append(
                LifetimeLayoutProbe(
                    label=label,
                    operator="window-order-source-steering",
                    description=(
                        f"Move source local {local_name} {direction} the "
                        "solver window-order fallback anchor."
                    ),
                    source_text=candidate_text,
                    provenance={
                        "kind": "window-order-fallback-source-move",
                        "lead": dict(lead),
                        "source_attribution": _source_attr_dict(source_attr),
                        "moved_local": local_name,
                        "scope_depth": group.scope_depth,
                        "block_start_line": group.block_start_line,
                        "destination": dest,
                        "line_range": line_range,
                    },
                )
            )
            materialized_labels.append(label)
            if first_source_diff is None:
                first_source_diff = _source_diff(source_text, candidate_text)
            if len(probes) >= limit:
                break

        if materialized_labels:
            diag["status"] = "materialized"
            diag["materialized_probe_labels"] = materialized_labels
            diag["source_diff"] = first_source_diff or ""
        elif len(probes) >= limit:
            diag["terminal_blocker"] = "probe-limit-reached"
        else:
            diag["terminal_blocker"] = "duplicate-source-move"
        lead_diagnostics.append(diag)

    return WindowOrderSourceProbePlan(
        probes=probes,
        lead_diagnostics=lead_diagnostics,
    )


def _repair_goal_int(goal: Mapping[str, Any], key: str) -> int | None:
    try:
        return int(goal[key])
    except (KeyError, TypeError, ValueError):
        return None


def _repair_goal_mapping(goal: Mapping[str, Any], key: str) -> dict[str, int]:
    value = goal.get(key)
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for map_key, map_value in value.items():
        try:
            result[str(map_key)] = int(map_value)
        except (TypeError, ValueError):
            continue
    return result


def _repair_source_expression(
    goal: Mapping[str, Any],
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None,
    interferer_ig: int,
) -> str | None:
    for key in ("source_expression", "source_local", "interferer_source"):
        value = goal.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    source_attr = _source_attr_for_ig(source_attributions, interferer_ig)
    for key in ("expression", "name", "var_name"):
        value = _attr_value(source_attr, key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _split_indexed_repair_expression(
    expression: str,
) -> tuple[str, str] | None:
    match = re.match(
        r"^(?P<base>[A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)*)"
        r"\s*\[\s*(?P<index>[^\]]+)\s*\]$",
        expression,
    )
    if match is None:
        return None
    array_base = re.sub(r"\s+", "", match.group("base"))
    index_expr = match.group("index").strip()
    if not array_base or not index_expr:
        return None
    return array_base, index_expr


def _strip_full_enclosing_parens(expression: str) -> str:
    text = expression.strip()
    while len(text) >= 2 and text[0] == "(" and text[-1] == ")":
        depth = 0
        encloses_full_expression = True
        for index, char in enumerate(text):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    return text
                if depth == 0 and index != len(text) - 1:
                    encloses_full_expression = False
                    break
        if not encloses_full_expression or depth != 0:
            break
        text = text[1:-1].strip()
    return text


def _canonical_index_expr(index_expr: str) -> str:
    return _strip_full_enclosing_parens(index_expr)


def _indexed_repair_expression(array_base: str, index_expr: str) -> str:
    return f"{array_base}[{index_expr}]"


def _safe_implicit_index_expr(index_expr: str) -> bool:
    canonical = _canonical_index_expr(index_expr)
    if not _safe_index_temp_expression(canonical):
        return False
    return re.fullmatch(
        r"[A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)*",
        canonical,
    ) is not None


def _repair_goal_source_index(goal: Mapping[str, Any], key: str) -> str | None:
    value = goal.get(key)
    if isinstance(value, str) and _safe_index_temp_expression(value):
        return value.strip()
    return None


def _first_expression_line_preferring_call(
    source_text: str,
    expression: str,
    *,
    call_name: str,
    search_span: tuple[int, int],
) -> tuple[int, int, str] | None:
    fallback: tuple[int, int, str] | None = None
    search_start, search_end = search_span
    call_pattern = re.compile(rf"\b{re.escape(call_name)}\s*\(")
    for line_start, line_end, line in _line_records_in_span(
        source_text,
        (search_start, search_end),
    ):
        if expression not in line:
            continue
        if fallback is None:
            fallback = (line_start, line_end, line)
        if call_pattern.search(line):
            return line_start, line_end, line
    return fallback


def _nearest_condition_start_line(
    source_text: str,
    line_start: int,
    *,
    search_span: tuple[int, int],
) -> int:
    search_start, search_end = search_span
    records = list(_line_records_in_span(source_text, (search_start, search_end)))
    for prev_start, _prev_end, prev_line in reversed(records):
        if prev_start > line_start:
            continue
        if re.match(r"\s*(?:if|while|for|switch)\s*\(", prev_line):
            return prev_start
        if prev_start < line_start and prev_line.strip().endswith(";"):
            break
    return line_start


def _repair_candidate_text_from_edits(
    source_text: str,
    edits: Iterable[tuple[int, int, str]],
) -> str:
    candidate_text = source_text
    for start, end, replacement in sorted(edits, reverse=True):
        candidate_text = (
            candidate_text[:start] + replacement + candidate_text[end:]
        )
    return candidate_text


def _safe_target_repair_expression(expression: str) -> bool:
    return (
        bool(expression)
        and re.search(r"=|\+\+|--|\?|,|;|\b[A-Za-z_]\w*\s*\(", expression)
        is None
    )


def _identifier_expression_declaration_or_lhs(line: str, expression: str) -> bool:
    if re.fullmatch(r"[A-Za-z_]\w*", expression) is None:
        return False
    stripped = line.strip()
    expression_re = re.escape(expression)
    if re.match(
        rf"(?:[A-Za-z_]\w*(?:\s+\*?|\s*\*)+){expression_re}\b",
        stripped,
    ):
        return True
    return (
        re.match(
            rf"{expression_re}\s*(?:=|\+=|-=|\*=|/=|%=|&=|\|=|\^=)",
            stripped,
        )
        is not None
    )


def _source_expression_line_match(line: str, expression: str) -> re.Match[str] | None:
    if re.fullmatch(r"[A-Za-z_]\w*", expression) is not None:
        return re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(expression)}(?![A-Za-z0-9_])",
            line,
        )
    return re.search(re.escape(expression), line)


def _replace_first_source_expression(
    line: str,
    expression: str,
    replacement: str,
) -> str | None:
    match = _source_expression_line_match(line, expression)
    if match is None:
        return None
    return line[:match.start()] + replacement + line[match.end():]


def _repair_search_span(
    source_text: str,
    function: str,
) -> tuple[int, int]:
    return _function_body_span(source_text, function) or (0, len(source_text))


def _first_expression_line(
    source_text: str,
    expression: str,
    *,
    search_span: tuple[int, int],
) -> tuple[int, int, str] | None:
    search_start, search_end = search_span
    for line_start, line_end, line in _line_records_in_span(
        source_text,
        (search_start, search_end),
    ):
        if _source_expression_line_match(line, expression) is None:
            continue
        if _identifier_expression_declaration_or_lhs(line, expression):
            continue
        return line_start, line_end, line
    return None


def _target_repair_metadata(
    *,
    goal: Mapping[str, Any],
    target_ig: int,
    target_phys: int | None,
    interferer_ig: int,
    interferer_phys: int | None,
    protected_targets: Mapping[str, int],
    required_delta: int | None,
    kind: str,
    strategy: str,
    source_expression: str,
    synthetic_local: str,
    line_start: int,
    line_end: int,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "repair_goal": dict(goal),
        "target_ig": target_ig,
        "target_phys": target_phys,
        "interferer_ig": interferer_ig,
        "interferer_phys": interferer_phys,
        "protected_targets": dict(protected_targets),
        "required_delta": required_delta,
        "ranked_repair_candidate": {
            "strategy": strategy,
            "source_expression": source_expression,
            "synthetic_local": synthetic_local,
            "line_source_span": [line_start, line_end],
        },
        "exhaustion_key": kind,
    }


_PCODE_SOURCE_OPCODE_RE = re.compile(
    r"^\s*(?:add|addi|addis|mr|lwz|lbz|stb|stw|rlwinm|slwi|clrlwi)\b",
    re.IGNORECASE,
)


def _alternate_span_key(span: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        span.get("family_id"),
        span.get("target_ig"),
        span.get("target_phys"),
        span.get("interferer_ig"),
        span.get("interferer_phys"),
        span.get("source_expression"),
    )


def _span_protected_targets(span: Mapping[str, Any]) -> dict[str, int]:
    protected = _repair_goal_mapping(span, "protected_targets")
    if protected:
        return protected
    target_ig = _repair_goal_int(span, "target_ig")
    attempted = {target_ig} if target_ig is not None else set()
    out: dict[str, int] = {}
    for key in ("force_phys_targets", "attempted_targets"):
        raw = span.get(key)
        if not isinstance(raw, Mapping):
            continue
        for map_key, map_value in raw.items():
            try:
                ig = int(map_key)
                phys = int(map_value)
            except (TypeError, ValueError):
                continue
            if ig not in attempted:
                out[str(ig)] = phys
    return out


def _is_pcode_source_expression(expression: str) -> bool:
    return (
        _PCODE_SOURCE_OPCODE_RE.search(expression) is not None
        or re.search(r"(?<![A-Za-z0-9_])[rf]\d+\b", expression) is not None
    )


def _alternate_owner_candidate_present(
    source_text: str,
    *,
    expression: str,
    search_span: tuple[int, int],
) -> tuple[bool, str | None]:
    if not _safe_target_repair_expression(expression):
        return False, "unsafe-source-expression"
    if _first_expression_line(source_text, expression, search_span=search_span) is None:
        return False, "source-expression-not-found"
    return True, None


def _alternate_owner_goal(
    candidate: _AlternateOwnerCandidate,
) -> dict[str, Any]:
    span = candidate.current_span
    target_ig = _repair_goal_int(span, "target_ig")
    target_phys = _repair_goal_int(span, "target_phys")
    interferer_ig = _repair_goal_int(span, "interferer_ig") or target_ig
    interferer_phys = _repair_goal_int(span, "interferer_phys") or target_phys
    source_type = candidate.source_type
    goal = {
        "kind": (
            "target-aware-fpr-live-range-interference"
            if source_type in {"f32", "float", "double"}
            else "target-aware-live-range-interference"
        ),
        "target_ig": target_ig,
        "target_phys": target_phys,
        "protected_targets": _span_protected_targets(span),
        "interferer_ig": interferer_ig,
        "interferer_phys": interferer_phys,
        "source_expression": candidate.source_expression,
        "source_type": source_type,
        "required_delta": _repair_goal_int(span, "required_delta") or 1,
        "source_probe_kind": "target-aware-alternate-source-owner",
        "source_owner_strategy": "alternate-source-owner-temp",
        "desired_effects": [
            "inspect-alternate-source-owner",
            "preserve-current-owner-negative-evidence",
            "materialize-retained-source-probe",
        ],
        "current_owner_span": dict(span),
        "alternate_source_owner": {
            "current_source_expression": span.get("source_expression"),
            "source_expression": candidate.source_expression,
            "relation": candidate.relation,
            "rank": candidate.score,
        },
        "evidence": {
            "kind": "current-owner-exhaustion-continuation",
            "summary": (
                "alternate source-owner discovered after current retained "
                "Case-C source owner probes exhausted"
            ),
        },
    }
    address_expression = span.get("address_source_expression")
    if isinstance(address_expression, str) and address_expression.strip():
        goal["address_source_expression"] = address_expression.strip()
    return {
        key: value
        for key, value in goal.items()
        if value not in (None, {}, [])
    }


def _alternate_owner_candidate_dict(
    candidate: _AlternateOwnerCandidate,
) -> dict[str, Any]:
    return {
        "source_expression": candidate.source_expression,
        "source_type": candidate.source_type,
        "relation": candidate.relation,
        "score": candidate.score,
        "current_source_expression": candidate.current_span.get(
            "source_expression"
        ),
        "current_span_key": list(_alternate_span_key(candidate.current_span)),
    }


def _alternate_owner_node_dict(node: _AlternateOwnerNode) -> dict[str, Any]:
    out = {
        "source_expression": node.source_expression,
        "current_source_expression": node.current_source_expression,
        "relation": node.relation,
        "status": node.status,
    }
    if node.reason:
        out["reason"] = node.reason
    return out


def _append_alternate_candidate(
    *,
    candidates: list[_AlternateOwnerCandidate],
    inspected: list[_AlternateOwnerNode],
    seen: set[tuple[str, tuple[Any, ...]]],
    source_text: str,
    search_span: tuple[int, int],
    current_span: Mapping[str, Any],
    excluded_expressions: set[str],
    expression: str,
    source_type: str,
    relation: str,
    score: int,
) -> None:
    expression = expression.strip()
    current_expression = str(current_span.get("source_expression") or "")
    if not expression:
        return
    if expression in excluded_expressions:
        inspected.append(
            _AlternateOwnerNode(
                source_expression=expression,
                current_source_expression=current_expression,
                relation=relation,
                status="rejected",
                reason="current-owner-already-exhausted",
            )
        )
        return
    key = (expression, _alternate_span_key(current_span))
    if key in seen:
        inspected.append(
            _AlternateOwnerNode(
                source_expression=expression,
                current_source_expression=current_expression,
                relation=relation,
                status="rejected",
                reason="duplicate-alternate-owner",
            )
        )
        return
    present, reason = _alternate_owner_candidate_present(
        source_text,
        expression=expression,
        search_span=search_span,
    )
    if not present:
        inspected.append(
            _AlternateOwnerNode(
                source_expression=expression,
                current_source_expression=current_expression,
                relation=relation,
                status="rejected",
                reason=reason,
            )
        )
        return
    seen.add(key)
    inspected.append(
        _AlternateOwnerNode(
            source_expression=expression,
            current_source_expression=current_expression,
            relation=relation,
            status="candidate",
        )
    )
    candidates.append(
        _AlternateOwnerCandidate(
            source_expression=expression,
            source_type=source_type,
            relation=relation,
            score=score,
            current_span=current_span,
        )
    )


def _alternate_source_owner_candidates(
    source_text: str,
    *,
    current_owner_spans: Iterable[Mapping[str, Any]],
    search_span: tuple[int, int],
) -> tuple[
    list[_AlternateOwnerCandidate],
    list[_AlternateOwnerNode],
    _AlternateOwnerProof,
    set[str],
]:
    candidates: list[_AlternateOwnerCandidate] = []
    inspected: list[_AlternateOwnerNode] = []
    seen: set[tuple[str, tuple[Any, ...]]] = set()
    spans = [span for span in current_owner_spans if isinstance(span, Mapping)]
    excluded_expressions = {
        str(span.get("source_expression")).strip()
        for span in spans
        if isinstance(span.get("source_expression"), str)
        and str(span.get("source_expression")).strip()
    }
    for span in spans:
        source_expression = str(span.get("source_expression") or "").strip()
        source_type = str(span.get("source_type") or "").lower()
        family_id = str(span.get("family_id") or "")
        is_fpr_span = (
            source_type in {"f32", "float", "double"}
            or "fpr" in family_id
        )
        if is_fpr_span:
            if "row_offset" in source_expression:
                _append_alternate_candidate(
                    candidates=candidates,
                    inspected=inspected,
                    seen=seen,
                    source_text=source_text,
                    search_span=search_span,
                    current_span=span,
                    excluded_expressions=excluded_expressions,
                    expression="row_offset",
                    source_type="f32",
                    relation="producer-local",
                    score=10,
                )
                for expression, relation, score in (
                    ("rowf", "producer-scale-local", 20),
                    ("(f32) row", "producer-conversion", 30),
                ):
                    _append_alternate_candidate(
                        candidates=candidates,
                        inspected=inspected,
                        seen=seen,
                        source_text=source_text,
                        search_span=search_span,
                        current_span=span,
                        excluded_expressions=excluded_expressions,
                        expression=expression,
                        source_type="f32",
                        relation=relation,
                        score=score,
                    )
            if "col_offset" in source_expression:
                for expression, relation, score in (
                    ("y_spacing", "producer-scale-local", 10),
                    ("(f32) col", "producer-conversion", 20),
                    ("col", "producer-index-local", 30),
                ):
                    _append_alternate_candidate(
                        candidates=candidates,
                        inspected=inspected,
                        seen=seen,
                        source_text=source_text,
                        search_span=search_span,
                        current_span=span,
                        excluded_expressions=excluded_expressions,
                        expression=expression,
                        source_type="f32",
                        relation=relation,
                        score=score,
                    )
            continue

        source_kind = str(span.get("source_owner_kind") or span.get("source_kind") or "")
        stack_symbol = span.get("stack_symbol")
        pcode_like = _is_pcode_source_expression(source_expression)
        if not pcode_like and not source_kind:
            continue
        if stack_symbol == "max_idx" or "max_idx" in source_expression:
            for expression, expression_type, relation, score in (
                ("max_idx", "int", "stack-reload-local", 10),
                (
                    "mnDiagram_804A076C.sorted_names[max_idx]",
                    "u8",
                    "stack-reload-indexed-value",
                    20,
                ),
                ("sorted_names[max_idx]", "u8", "stack-reload-indexed-value", 30),
            ):
                _append_alternate_candidate(
                    candidates=candidates,
                    inspected=inspected,
                    seen=seen,
                    source_text=source_text,
                    search_span=search_span,
                    current_span=span,
                    excluded_expressions=excluded_expressions,
                    expression=expression,
                    source_type=expression_type,
                    relation=relation,
                    score=score,
                )
        if pcode_like or source_kind in {
            "implicit-temp",
            "copy/coalesce-product",
            "load/store-address",
        }:
            for expression, expression_type, relation, score in (
                (
                    "mnDiagram_804A076C.sorted_names[j]",
                    "u8",
                    "value-load-owner",
                    10,
                ),
                ("sorted_names[j]", "u8", "value-load-owner", 20),
                (
                    "mnDiagram_804A076C.sorted_names",
                    "u8*",
                    "global-base-owner",
                    30,
                ),
                ("sorted_names", "u8*", "base-alias-owner", 40),
                ("dst", "u8*", "destination-base-owner", 50),
                ("dst_iter", "u8*", "destination-cursor-owner", 60),
            ):
                _append_alternate_candidate(
                    candidates=candidates,
                    inspected=inspected,
                    seen=seen,
                    source_text=source_text,
                    search_span=search_span,
                    current_span=span,
                    excluded_expressions=excluded_expressions,
                    expression=expression,
                    source_type=expression_type,
                    relation=relation,
                    score=score,
                )
    candidates.sort(key=lambda item: (item.score, item.source_expression))
    rejected = [
        _alternate_owner_node_dict(node)
        for node in inspected
        if node.status == "rejected"
    ]
    return (
        candidates,
        inspected,
        _AlternateOwnerProof(
            inspected_owner_nodes=[
                _alternate_owner_node_dict(node) for node in inspected
            ],
            rejected_owner_nodes=rejected,
        ),
        excluded_expressions,
    )


def _current_owner_span_update(
    span: Mapping[str, Any],
    *,
    next_status: str,
    proof: _AlternateOwnerProof,
    candidates: list[_AlternateOwnerCandidate],
    materialized_labels: list[str],
) -> dict[str, Any]:
    out = dict(span)
    out.setdefault("source_owner_status", "current-source-owner-probes-exhausted")
    out["next_source_owner_status"] = next_status
    out["inspected_owner_nodes"] = list(proof.inspected_owner_nodes)
    out["ranked_alternate_owner_candidates"] = [
        _alternate_owner_candidate_dict(candidate)
        for candidate in candidates
        if _alternate_span_key(candidate.current_span) == _alternate_span_key(span)
    ]
    if materialized_labels:
        out["alternate_source_owner_probe_labels"] = list(materialized_labels)
    if next_status == "terminal-next-source-owner-exhausted":
        out["terminal_blocker"] = "next-source-owner-exhausted"
    elif next_status == "materialized":
        out.pop("terminal_blocker", None)
    return {key: value for key, value in out.items() if value not in (None, [], {})}


def plan_alternate_source_owner_probes(
    source_text: str,
    *,
    function: str,
    current_owner_spans: Iterable[Mapping[str, Any]],
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None = None,
    max_probes: int = 8,
) -> WindowOrderSourceProbePlan:
    """Continue retained Case-C repair after current source owners exhaust."""

    spans = [span for span in current_owner_spans if isinstance(span, Mapping)]
    search_span = _repair_search_span(source_text, function)
    candidates, inspected, proof, excluded = _alternate_source_owner_candidates(
        source_text,
        current_owner_spans=spans,
        search_span=search_span,
    )
    goals = [_alternate_owner_goal(candidate) for candidate in candidates]
    nested_plan = plan_target_aware_live_range_repair_probes(
        source_text,
        function=function,
        repair_goals=goals,
        source_attributions=source_attributions,
        max_probes=max_probes,
    )
    probes: list[LifetimeLayoutProbe] = []
    materialized_by_span: dict[tuple[Any, ...], list[str]] = {}
    materialized_by_expression: dict[str, list[str]] = {}
    for index, probe in enumerate(nested_plan.probes):
        provenance = dict(probe.provenance or {})
        repair_goal = (
            provenance.get("repair_goal")
            if isinstance(provenance.get("repair_goal"), Mapping)
            else {}
        )
        span = (
            repair_goal.get("current_owner_span")
            if isinstance(repair_goal.get("current_owner_span"), Mapping)
            else {}
        )
        alternate = (
            repair_goal.get("alternate_source_owner")
            if isinstance(repair_goal.get("alternate_source_owner"), Mapping)
            else {}
        )
        label = (
            "alternate-source-owner-"
            f"{_safe_label_part(alternate.get('source_expression', index))}-"
            f"{index}"
        )
        provenance["current_owner_span"] = dict(span)
        provenance["alternate_source_owner"] = dict(alternate)
        provenance["owner_graph_path"] = [
            span.get("source_expression"),
            alternate.get("source_expression"),
        ]
        probes.append(
            LifetimeLayoutProbe(
                label=label,
                operator="target-aware-alternate-source-owner",
                description=(
                    "Materialize retained Case-C alternate source-owner "
                    "probe after current-owner exhaustion."
                ),
                source_text=probe.source_text,
                provenance=provenance,
            )
        )
        materialized_by_span.setdefault(_alternate_span_key(span), []).append(label)
        alternate_expression = alternate.get("source_expression")
        if isinstance(alternate_expression, str) and alternate_expression:
            materialized_by_expression.setdefault(alternate_expression, []).append(
                label
            )

    span_updates: list[dict[str, Any]] = []
    for span in spans:
        span_key = _alternate_span_key(span)
        materialized_labels = list(materialized_by_span.get(span_key, []))
        span_candidates = [
            candidate
            for candidate in candidates
            if _alternate_span_key(candidate.current_span) == span_key
        ]
        if not materialized_labels:
            shared_labels: list[str] = []
            for candidate in span_candidates:
                for label in materialized_by_expression.get(
                    candidate.source_expression,
                    [],
                ):
                    if label not in shared_labels:
                        shared_labels.append(label)
            materialized_labels = shared_labels
        span_updates.append(
            _current_owner_span_update(
                span,
                next_status=(
                    "materialized"
                    if materialized_labels
                    else "terminal-next-source-owner-exhausted"
                ),
                proof=proof,
                candidates=candidates,
                materialized_labels=materialized_labels,
            )
        )
    diagnostic = {
        "status": "materialized" if probes else "blocked",
        "current_owner_span_count": len(spans),
        "excluded_current_owner_expressions": sorted(excluded),
        "inspected_owner_nodes": proof.inspected_owner_nodes,
        "rejected_owner_nodes": proof.rejected_owner_nodes,
        "ranked_alternate_owner_candidates": [
            _alternate_owner_candidate_dict(candidate)
            for candidate in candidates
        ],
        "materialized_alternate_probe_count": len(probes),
        "current_owner_span_updates": span_updates,
        "repair_goal_diagnostics": nested_plan.lead_diagnostics,
    }
    if not probes:
        diagnostic["terminal_blocker"] = "next-source-owner-exhausted"
    return WindowOrderSourceProbePlan(
        probes=probes,
        lead_diagnostics=[diagnostic],
    )


def _materialize_target_live_range_expression_temp(
    source_text: str,
    *,
    function: str,
    goal: Mapping[str, Any],
    target_ig: int,
    target_phys: int | None,
    interferer_ig: int,
    interferer_phys: int | None,
    protected_targets: Mapping[str, int],
    required_delta: int | None,
    source_expression: str,
    search_span: tuple[int, int],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "target-aware-interferer-expression-temp"
    if not _safe_target_repair_expression(source_expression):
        return None, {
            "status": "rejected",
            "reason": "unsafe-source-expression",
            "handler": handler,
            "source_expression": source_expression,
        }
    line_record = _first_expression_line(
        source_text,
        source_expression,
        search_span=search_span,
    )
    if line_record is None:
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-found",
            "handler": handler,
            "source_expression": source_expression,
        }
    line_start, line_end, line = line_record
    stripped = line.strip()
    if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
        return None, {
            "status": "rejected",
            "reason": "unsafe-executable-line",
            "handler": handler,
            "source_expression": source_expression,
        }
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None, {
            "status": "rejected",
            "reason": "source-ast-unavailable",
            "handler": handler,
            "source_expression": source_expression,
        }
    decl_index, decl_indent = insertion
    if decl_index > line_start:
        return None, {
            "status": "rejected",
            "reason": "declaration-anchor-after-use",
            "handler": handler,
            "source_expression": source_expression,
        }
    temp_name = _target_repair_probe_local_name(
        source_text,
        f"live_range_ig{interferer_ig}",
    )
    rewritten_line = _replace_first_source_expression(
        line,
        source_expression,
        temp_name,
    )
    if rewritten_line is None or rewritten_line == line:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
        }
    indent = re.match(r"[ \t]*", line).group(0)
    decl_type = _safe_decl_type_text(goal.get("source_type")) or "u8"
    edits = [
        (
            line_start,
            line_end,
            f"{indent}{temp_name} = {source_expression};\n{rewritten_line}",
        ),
        (decl_index, decl_index, f"{decl_indent}{decl_type} {temp_name};\n"),
    ]
    candidate_text = source_text
    for start, end, replacement in sorted(edits, reverse=True):
        candidate_text = candidate_text[:start] + replacement + candidate_text[end:]
    if candidate_text == source_text:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
        }
    provenance_kind = (
        goal.get("source_probe_kind")
        if isinstance(goal.get("source_probe_kind"), str)
        and goal.get("source_probe_kind")
        else "target-aware-live-range-anchor"
    )
    strategy = (
        goal.get("source_owner_strategy")
        if isinstance(goal.get("source_owner_strategy"), str)
        and goal.get("source_owner_strategy")
        else "interferer-expression-temp"
    )
    metadata = _target_repair_metadata(
        goal=goal,
        target_ig=target_ig,
        target_phys=target_phys,
        interferer_ig=interferer_ig,
        interferer_phys=interferer_phys,
        protected_targets=protected_targets,
        required_delta=required_delta,
        kind=provenance_kind,
        strategy=strategy,
        source_expression=source_expression,
        synthetic_local=temp_name,
        line_start=line_start,
        line_end=line_end,
    )
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind=provenance_kind,
            metadata=metadata,
        ),
        {
            "status": "materialized",
            "handler": handler,
            "source_expression": source_expression,
            "strategy": strategy,
        },
    )


def _materialize_target_interference_index_temp(
    source_text: str,
    *,
    function: str,
    goal: Mapping[str, Any],
    target_ig: int,
    target_phys: int | None,
    interferer_ig: int,
    interferer_phys: int | None,
    protected_targets: Mapping[str, int],
    required_delta: int | None,
    source_expression: str,
    search_span: tuple[int, int],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "target-aware-index-temp"
    match = re.match(
        r"^(?P<base>[A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)*)"
        r"\s*\[\s*(?P<index>[^\]]+)\s*\]$",
        source_expression,
    )
    if match is None:
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-indexed-byte",
            "handler": handler,
            "source_expression": source_expression,
        }
    array_base = re.sub(r"\s+", "", match.group("base"))
    index_expr = match.group("index").strip()
    if not _safe_index_temp_expression(index_expr):
        return None, {
            "status": "rejected",
            "reason": "unsafe-index-expression",
            "handler": handler,
            "source_expression": source_expression,
        }
    line_record = _first_expression_line(
        source_text,
        source_expression,
        search_span=search_span,
    )
    if line_record is None:
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-found",
            "handler": handler,
            "source_expression": source_expression,
        }
    line_start, line_end, line = line_record
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None, {
            "status": "rejected",
            "reason": "source-ast-unavailable",
            "handler": handler,
            "source_expression": source_expression,
        }
    decl_index, decl_indent = insertion
    if decl_index > line_start:
        return None, {
            "status": "rejected",
            "reason": "declaration-anchor-after-use",
            "handler": handler,
            "source_expression": source_expression,
        }
    temp_name = _target_repair_probe_local_name(
        source_text,
        f"interference_ig{target_ig}_{_safe_label_part(index_expr)}",
    )
    rewritten_expression = f"{array_base}[{temp_name}]"
    rewritten_line = line.replace(source_expression, rewritten_expression, 1)
    if rewritten_line == line:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
        }
    indent = re.match(r"[ \t]*", line).group(0)
    edits = [
        (
            line_start,
            line_end,
            f"{indent}{temp_name} = {index_expr};\n{rewritten_line}",
        ),
        (decl_index, decl_index, f"{decl_indent}int {temp_name};\n"),
    ]
    candidate_text = source_text
    for start, end, replacement in sorted(edits, reverse=True):
        candidate_text = candidate_text[:start] + replacement + candidate_text[end:]
    if candidate_text == source_text:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
        }
    metadata = _target_repair_metadata(
        goal=goal,
        target_ig=target_ig,
        target_phys=target_phys,
        interferer_ig=interferer_ig,
        interferer_phys=interferer_phys,
        protected_targets=protected_targets,
        required_delta=required_delta,
        kind="target-aware-interference-shape",
        strategy="target-index-temp",
        source_expression=source_expression,
        synthetic_local=temp_name,
        line_start=line_start,
        line_end=line_end,
    )
    metadata["ranked_repair_candidate"]["array_base"] = array_base
    metadata["ranked_repair_candidate"]["index_expr"] = index_expr
    metadata["ranked_repair_candidate"]["rewritten_expression"] = rewritten_expression
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="target-aware-interference-shape",
            metadata=metadata,
        ),
        {
            "status": "materialized",
            "handler": handler,
            "source_expression": source_expression,
            "strategy": "target-index-temp",
        },
    )


def _is_fpr_scalar_repair_goal(
    goal: Mapping[str, Any],
    source_expression: str,
) -> bool:
    source_type = str(goal.get("source_type") or "").lower()
    kind = str(goal.get("kind") or "").lower()
    if source_type not in {"f32", "float", "double"} and "fpr" not in kind:
        return False
    return _split_indexed_repair_expression(source_expression) is None


def _materialize_target_scalar_duplicate_temp(
    source_text: str,
    *,
    function: str,
    goal: Mapping[str, Any],
    target_ig: int,
    target_phys: int | None,
    interferer_ig: int,
    interferer_phys: int | None,
    protected_targets: Mapping[str, int],
    required_delta: int | None,
    source_expression: str,
    search_span: tuple[int, int],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "target-aware-scalar-duplicate-temp"
    if not _is_fpr_scalar_repair_goal(goal, source_expression):
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-fpr-scalar",
            "handler": handler,
            "source_expression": source_expression,
        }
    if not _safe_target_repair_expression(source_expression):
        return None, {
            "status": "rejected",
            "reason": "unsafe-source-expression",
            "handler": handler,
            "source_expression": source_expression,
        }
    line_record = _first_expression_line(
        source_text,
        source_expression,
        search_span=search_span,
    )
    if line_record is None:
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-found",
            "handler": handler,
            "source_expression": source_expression,
        }
    line_start, line_end, line = line_record
    stripped = line.strip()
    if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
        return None, {
            "status": "rejected",
            "reason": "unsafe-executable-line",
            "handler": handler,
            "source_expression": source_expression,
        }
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None, {
            "status": "rejected",
            "reason": "source-ast-unavailable",
            "handler": handler,
            "source_expression": source_expression,
        }
    decl_index, decl_indent = insertion
    if decl_index > line_start:
        return None, {
            "status": "rejected",
            "reason": "declaration-anchor-after-use",
            "handler": handler,
            "source_expression": source_expression,
        }
    reserved_probe_names: set[str] = set()
    value_name = _target_repair_probe_local_name(
        source_text,
        f"scalar_ig{interferer_ig}",
        reserved=reserved_probe_names,
    )
    duplicate_name = _target_repair_probe_local_name(
        source_text,
        f"scalar_duplicate_ig{interferer_ig}",
        reserved=reserved_probe_names,
    )
    rewritten_line = _replace_first_source_expression(
        line,
        source_expression,
        duplicate_name,
    )
    if rewritten_line is None or rewritten_line == line:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
        }
    indent = re.match(r"[ \t]*", line).group(0)
    decl_type = _safe_decl_type_text(goal.get("source_type")) or "f32"
    candidate_text = _repair_candidate_text_from_edits(
        source_text,
        [
            (
                line_start,
                line_end,
                f"{indent}{value_name} = {source_expression};\n"
                f"{indent}{duplicate_name} = {value_name};\n"
                f"{rewritten_line}",
            ),
            (
                decl_index,
                decl_index,
                f"{decl_indent}{decl_type} {value_name};\n"
                f"{decl_indent}{decl_type} {duplicate_name};\n",
            ),
        ],
    )
    if candidate_text == source_text:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
        }
    metadata = _target_repair_metadata(
        goal=goal,
        target_ig=target_ig,
        target_phys=target_phys,
        interferer_ig=interferer_ig,
        interferer_phys=interferer_phys,
        protected_targets=protected_targets,
        required_delta=required_delta,
        kind="target-aware-scalar-interference-shape",
        strategy="scalar-duplicate-temp",
        source_expression=source_expression,
        synthetic_local=value_name,
        line_start=line_start,
        line_end=line_end,
    )
    metadata["ranked_repair_candidate"].update({
        "duplicate_scalar_temp": duplicate_name,
        "rewritten_expression": duplicate_name,
    })
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="target-aware-scalar-interference-shape",
            metadata=metadata,
        ),
        {
            "status": "materialized",
            "handler": handler,
            "source_expression": source_expression,
            "strategy": "scalar-duplicate-temp",
        },
    )


def _materialize_target_scalar_pair_overlap_temp(
    source_text: str,
    *,
    function: str,
    goal: Mapping[str, Any],
    target_ig: int,
    target_phys: int | None,
    interferer_ig: int,
    interferer_phys: int | None,
    protected_targets: Mapping[str, int],
    required_delta: int | None,
    source_expression: str,
    search_span: tuple[int, int],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "target-aware-scalar-pair-overlap-temp"
    paired_expression = goal.get("paired_source_expression")
    if not isinstance(paired_expression, str) or not paired_expression.strip():
        return None, {
            "status": "rejected",
            "reason": "missing-paired-scalar-expression",
            "handler": handler,
            "source_expression": source_expression,
        }
    paired_expression = paired_expression.strip()
    if (
        not _is_fpr_scalar_repair_goal(goal, source_expression)
        or _split_indexed_repair_expression(paired_expression) is not None
    ):
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-fpr-scalar",
            "handler": handler,
            "source_expression": source_expression,
            "paired_source_expression": paired_expression,
        }
    if (
        not _safe_target_repair_expression(source_expression)
        or not _safe_target_repair_expression(paired_expression)
    ):
        return None, {
            "status": "rejected",
            "reason": "unsafe-source-expression",
            "handler": handler,
            "source_expression": source_expression,
            "paired_source_expression": paired_expression,
        }
    source_record = _first_expression_line(
        source_text,
        source_expression,
        search_span=search_span,
    )
    pair_record = _first_expression_line(
        source_text,
        paired_expression,
        search_span=search_span,
    )
    if source_record is None or pair_record is None:
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-found",
            "handler": handler,
            "source_expression": source_expression,
            "paired_source_expression": paired_expression,
        }
    source_start, source_end, source_line = source_record
    pair_start, pair_end, pair_line = pair_record
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None, {
            "status": "rejected",
            "reason": "source-ast-unavailable",
            "handler": handler,
            "source_expression": source_expression,
            "paired_source_expression": paired_expression,
        }
    decl_index, decl_indent = insertion
    assignment_start = min(source_start, pair_start)
    if decl_index > assignment_start:
        return None, {
            "status": "rejected",
            "reason": "declaration-anchor-after-use",
            "handler": handler,
            "source_expression": source_expression,
            "paired_source_expression": paired_expression,
        }
    reserved_probe_names: set[str] = set()
    source_name = _target_repair_probe_local_name(
        source_text,
        f"scalar_pair_ig{interferer_ig}",
        reserved=reserved_probe_names,
    )
    paired_ig = _repair_goal_int(goal, "paired_interferer_ig") or target_ig
    pair_name = _target_repair_probe_local_name(
        source_text,
        f"scalar_pair_ig{paired_ig}",
        reserved=reserved_probe_names,
    )
    edits: list[tuple[int, int, str]] = []
    if source_start == pair_start:
        rewritten = _replace_first_source_expression(
            source_line,
            paired_expression,
            pair_name,
        )
        if rewritten is not None:
            rewritten = _replace_first_source_expression(
                rewritten,
                source_expression,
                source_name,
            )
        if rewritten is None or rewritten == source_line:
            return None, {
                "status": "rejected",
                "reason": "source-unchanged",
                "handler": handler,
                "source_expression": source_expression,
                "paired_source_expression": paired_expression,
            }
        edits.append((source_start, source_end, rewritten))
    else:
        rewritten_source = _replace_first_source_expression(
            source_line,
            source_expression,
            source_name,
        )
        rewritten_pair = _replace_first_source_expression(
            pair_line,
            paired_expression,
            pair_name,
        )
        if (
            rewritten_source is None
            or rewritten_pair is None
            or (rewritten_source == source_line and rewritten_pair == pair_line)
        ):
            return None, {
                "status": "rejected",
                "reason": "source-unchanged",
                "handler": handler,
                "source_expression": source_expression,
                "paired_source_expression": paired_expression,
            }
        edits.append((source_start, source_end, rewritten_source))
        edits.append((pair_start, pair_end, rewritten_pair))
    assignment_line_end = source_text.find("\n", assignment_start)
    if assignment_line_end < 0:
        assignment_line_end = len(source_text)
    assignment_indent_match = re.match(
        r"[ \t]*",
        source_text[assignment_start:assignment_line_end],
    )
    assignment_indent = (
        assignment_indent_match.group(0)
        if assignment_indent_match is not None
        else ""
    )
    decl_type = _safe_decl_type_text(goal.get("source_type")) or "f32"
    edits.extend([
        (
            assignment_start,
            assignment_start,
            f"{assignment_indent}{pair_name} = {paired_expression};\n"
            f"{assignment_indent}{source_name} = {source_expression};\n",
        ),
        (
            decl_index,
            decl_index,
            f"{decl_indent}{decl_type} {pair_name};\n"
            f"{decl_indent}{decl_type} {source_name};\n",
        ),
    ])
    candidate_text = _repair_candidate_text_from_edits(source_text, edits)
    if candidate_text == source_text:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
            "paired_source_expression": paired_expression,
        }
    metadata = _target_repair_metadata(
        goal=goal,
        target_ig=target_ig,
        target_phys=target_phys,
        interferer_ig=interferer_ig,
        interferer_phys=interferer_phys,
        protected_targets=protected_targets,
        required_delta=required_delta,
        kind="target-aware-scalar-pair-overlap",
        strategy="scalar-paired-overlap-temp",
        source_expression=source_expression,
        synthetic_local=source_name,
        line_start=source_start,
        line_end=source_end,
    )
    metadata["ranked_repair_candidate"].update({
        "paired_source_expression": paired_expression,
        "paired_interferer_ig": paired_ig,
        "paired_scalar_temp": pair_name,
        "rewritten_expression": source_name,
    })
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="target-aware-scalar-pair-overlap",
            metadata=metadata,
        ),
        {
            "status": "materialized",
            "handler": handler,
            "source_expression": source_expression,
            "paired_source_expression": paired_expression,
            "strategy": "scalar-paired-overlap-temp",
        },
    )


def _target_repair_address_expression(
    goal: Mapping[str, Any],
    source_expression: str,
) -> tuple[str, str, str, str] | None:
    split = _split_indexed_repair_expression(source_expression)
    if split is None:
        return None
    array_base, value_index_expr = split
    explicit = goal.get("address_source_expression")
    if isinstance(explicit, str) and explicit.strip():
        address_expression = explicit.strip()
        explicit_split = _split_indexed_repair_expression(address_expression)
        if explicit_split is None:
            return None
        address_base, address_index_expr = explicit_split
        return (
            address_base,
            address_index_expr,
            value_index_expr,
            address_expression,
        )
    address_index_expr = (
        _repair_goal_source_index(goal, "address_index")
        or _repair_goal_source_index(goal, "target_index")
        or "max_idx"
    )
    if not _safe_index_temp_expression(address_index_expr):
        return None
    return (
        array_base,
        address_index_expr,
        value_index_expr,
        f"{array_base}[{address_index_expr}]",
    )


def _target_repair_address_match(
    source_text: str,
    *,
    address: tuple[str, str, str, str],
    search_span: tuple[int, int],
) -> _IndexedRepairAddressMatch | None:
    array_base, address_index_expr, value_index_expr, address_expression = address
    canonical_index = _canonical_index_expr(address_index_expr)
    for line_start, line_end, line in _line_records_in_span(
        source_text,
        search_span,
    ):
        for indexed in _indexed_expression_spans(line):
            if indexed.get("array_base") != array_base:
                continue
            source_index_expr = str(indexed.get("index_expr") or "").strip()
            if _canonical_index_expr(source_index_expr) != canonical_index:
                continue
            expr_start = line_start + int(indexed["start"])
            expr_end = line_start + int(indexed["end"])
            source_expression = source_text[expr_start:expr_end]
            return _IndexedRepairAddressMatch(
                array_base=array_base,
                requested_index_expr=address_index_expr,
                source_index_expr=source_index_expr,
                canonical_index_expr=canonical_index,
                value_index_expr=value_index_expr,
                requested_expression=address_expression,
                source_expression=source_expression,
                line_start=line_start,
                line_end=line_end,
                line=line,
                expression_start=expr_start,
                expression_end=expr_end,
            )
    return None


def _replace_line_span(
    line: str,
    *,
    line_start: int,
    span_start: int,
    span_end: int,
    replacement: str,
) -> str:
    rel_start = max(0, span_start - line_start)
    rel_end = max(rel_start, span_end - line_start)
    return line[:rel_start] + replacement + line[rel_end:]


def _replace_line_spans(
    line: str,
    *,
    line_start: int,
    replacements: Iterable[tuple[int, int, str]],
) -> str:
    rewritten = line
    for span_start, span_end, replacement in sorted(
        replacements,
        key=lambda item: item[0],
        reverse=True,
    ):
        rewritten = _replace_line_span(
            rewritten,
            line_start=line_start,
            span_start=span_start,
            span_end=span_end,
            replacement=replacement,
        )
    return rewritten


def _target_repair_address_source_match(
    source_text: str,
    *,
    goal: Mapping[str, Any],
    source_expression: str,
    search_span: tuple[int, int],
    handler: str,
) -> tuple[_IndexedRepairAddressMatch | None, dict[str, Any] | None]:
    address = _target_repair_address_expression(goal, source_expression)
    if address is None:
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-indexed-byte",
            "handler": handler,
            "source_expression": source_expression,
        }
    requested_address_expression = address[3]
    if not _safe_target_repair_expression(requested_address_expression):
        return None, {
            "status": "rejected",
            "reason": "unsafe-address-expression",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": requested_address_expression,
        }
    address_match = _target_repair_address_match(
        source_text,
        address=address,
        search_span=search_span,
    )
    if address_match is None:
        return None, {
            "status": "rejected",
            "reason": "address-source-expression-not-found",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": requested_address_expression,
        }
    return address_match, None


def _address_match_executable_line_diagnostic(
    *,
    address_match: _IndexedRepairAddressMatch,
    handler: str,
    source_expression: str,
) -> dict[str, Any] | None:
    stripped = address_match.line.strip()
    if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
        return {
            "status": "rejected",
            "reason": "unsafe-executable-line",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
        }
    return None


def _target_repair_assignment_insertion(
    source_text: str,
    *,
    function: str,
    address_match: _IndexedRepairAddressMatch,
    search_span: tuple[int, int],
    handler: str,
    source_expression: str,
) -> tuple[int, str, int, str] | dict[str, Any]:
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return {
            "status": "rejected",
            "reason": "source-ast-unavailable",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
        }
    decl_index, decl_indent = insertion
    if decl_index > address_match.line_start:
        return {
            "status": "rejected",
            "reason": "declaration-anchor-after-use",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
        }
    stripped = address_match.line.strip()
    if _line_can_host_index_temp_assignment(stripped) and not stripped.startswith("for"):
        assignment_line_start = address_match.line_start
    else:
        assignment_line_start = _nearest_condition_start_line(
            source_text,
            address_match.line_start,
            search_span=search_span,
        )
    assignment_line_end = source_text.find("\n", assignment_line_start)
    if assignment_line_end < 0:
        assignment_line_end = len(source_text)
    indent_match = re.match(
        r"[ \t]*",
        source_text[assignment_line_start:assignment_line_end],
    )
    assignment_indent = indent_match.group(0) if indent_match is not None else ""
    return decl_index, decl_indent, assignment_line_start, assignment_indent


def _target_repair_hoistable_index_assignment(
    source_text: str,
    *,
    index_expr: str,
    after_start: int,
    before_start: int,
    search_span: tuple[int, int],
) -> tuple[int, int, str, str] | None:
    index_name = _canonical_index_expr(index_expr).strip()
    if re.fullmatch(r"[A-Za-z_]\w*", index_name) is None:
        return None
    if after_start >= before_start:
        return None
    span_start = max(search_span[0], after_start)
    span_end = min(search_span[1], before_start)
    for line_start, line_end, line in _line_records_in_span(
        source_text,
        (span_start, span_end),
    ):
        if line_start <= after_start:
            continue
        match = _SIMPLE_ASSIGN_RE.match(line)
        if match is None or match.group("lhs") != index_name:
            continue
        rhs = match.group("rhs").strip()
        if not _safe_index_temp_expression(rhs):
            continue
        return line_start, line_end, index_name, rhs
    return None


def _target_implicit_index_metadata(
    *,
    goal: Mapping[str, Any],
    target_ig: int,
    target_phys: int | None,
    interferer_ig: int,
    interferer_phys: int | None,
    protected_targets: Mapping[str, int],
    required_delta: int | None,
    address_match: _IndexedRepairAddressMatch,
    kind: str,
    strategy: str,
    synthetic_local: str,
    rewritten_expression: str,
) -> dict[str, Any]:
    metadata = _target_repair_metadata(
        goal=goal,
        target_ig=target_ig,
        target_phys=target_phys,
        interferer_ig=interferer_ig,
        interferer_phys=interferer_phys,
        protected_targets=protected_targets,
        required_delta=required_delta,
        kind=kind,
        strategy=strategy,
        source_expression=address_match.source_expression,
        synthetic_local=synthetic_local,
        line_start=address_match.line_start,
        line_end=address_match.line_end,
    )
    metadata["ranked_repair_candidate"].update({
        "array_base": address_match.array_base,
        "address_index_expr": address_match.canonical_index_expr,
        "source_index_expr": address_match.source_index_expr,
        "value_index_expr": address_match.value_index_expr,
        "requested_address_expression": address_match.requested_expression,
        "address_expression": address_match.source_expression,
        "rewritten_expression": rewritten_expression,
        "preserves_implicit_indexed_expression": True,
    })
    return metadata


def _materialize_target_implicit_index_normalize(
    source_text: str,
    *,
    goal: Mapping[str, Any],
    target_ig: int,
    target_phys: int | None,
    interferer_ig: int,
    interferer_phys: int | None,
    protected_targets: Mapping[str, int],
    required_delta: int | None,
    source_expression: str,
    search_span: tuple[int, int],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "target-aware-implicit-index-normalize"
    address_match, diag = _target_repair_address_source_match(
        source_text,
        goal=goal,
        source_expression=source_expression,
        search_span=search_span,
        handler=handler,
    )
    if diag is not None or address_match is None:
        return None, diag or {
            "status": "rejected",
            "reason": "address-source-expression-not-found",
            "handler": handler,
            "source_expression": source_expression,
        }
    executable_diag = _address_match_executable_line_diagnostic(
        address_match=address_match,
        handler=handler,
        source_expression=source_expression,
    )
    if executable_diag is not None:
        return None, executable_diag
    if address_match.source_index_expr == address_match.canonical_index_expr:
        return None, {
            "status": "rejected",
            "reason": "index-already-normalized",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
        }
    if not _safe_implicit_index_expr(address_match.source_index_expr):
        return None, {
            "status": "rejected",
            "reason": "unsafe-index-expression",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
        }
    rewritten_expression = _indexed_repair_expression(
        address_match.array_base,
        address_match.canonical_index_expr,
    )
    rewritten_line = _replace_line_span(
        address_match.line,
        line_start=address_match.line_start,
        span_start=address_match.expression_start,
        span_end=address_match.expression_end,
        replacement=rewritten_expression,
    )
    candidate_text = _repair_candidate_text_from_edits(
        source_text,
        [(address_match.line_start, address_match.line_end, rewritten_line)],
    )
    if candidate_text == source_text:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
        }
    metadata = _target_implicit_index_metadata(
        goal=goal,
        target_ig=target_ig,
        target_phys=target_phys,
        interferer_ig=interferer_ig,
        interferer_phys=interferer_phys,
        protected_targets=protected_targets,
        required_delta=required_delta,
        address_match=address_match,
        kind="target-aware-implicit-index-normalize",
        strategy="implicit-index-normalize",
        synthetic_local="none",
        rewritten_expression=rewritten_expression,
    )
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="target-aware-implicit-index-normalize",
            metadata=metadata,
        ),
        {
            "status": "materialized",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
            "strategy": "implicit-index-normalize",
        },
    )


def _materialize_target_implicit_index_alias(
    source_text: str,
    *,
    function: str,
    goal: Mapping[str, Any],
    target_ig: int,
    target_phys: int | None,
    interferer_ig: int,
    interferer_phys: int | None,
    protected_targets: Mapping[str, int],
    required_delta: int | None,
    source_expression: str,
    search_span: tuple[int, int],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "target-aware-implicit-index-alias"
    address_match, diag = _target_repair_address_source_match(
        source_text,
        goal=goal,
        source_expression=source_expression,
        search_span=search_span,
        handler=handler,
    )
    if diag is not None or address_match is None:
        return None, diag or {
            "status": "rejected",
            "reason": "address-source-expression-not-found",
            "handler": handler,
            "source_expression": source_expression,
        }
    executable_diag = _address_match_executable_line_diagnostic(
        address_match=address_match,
        handler=handler,
        source_expression=source_expression,
    )
    if executable_diag is not None:
        return None, executable_diag
    if not _safe_implicit_index_expr(address_match.source_index_expr):
        return None, {
            "status": "rejected",
            "reason": "unsafe-index-expression",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
        }
    insertion = _target_repair_assignment_insertion(
        source_text,
        function=function,
        address_match=address_match,
        search_span=search_span,
        handler=handler,
        source_expression=source_expression,
    )
    if isinstance(insertion, dict):
        return None, insertion
    decl_index, decl_indent, assignment_line_start, assignment_indent = insertion
    index_name = _target_repair_probe_local_name(
        source_text,
        f"index_ig{target_ig}_{_safe_label_part(address_match.canonical_index_expr)}",
    )
    rewritten_expression = _indexed_repair_expression(
        address_match.array_base,
        index_name,
    )
    rewritten_line = _replace_line_span(
        address_match.line,
        line_start=address_match.line_start,
        span_start=address_match.expression_start,
        span_end=address_match.expression_end,
        replacement=rewritten_expression,
    )
    candidate_text = _repair_candidate_text_from_edits(
        source_text,
        [
            (
                assignment_line_start,
                assignment_line_start,
                f"{assignment_indent}{index_name} = "
                f"{address_match.canonical_index_expr};\n",
            ),
            (address_match.line_start, address_match.line_end, rewritten_line),
            (decl_index, decl_index, f"{decl_indent}int {index_name};\n"),
        ],
    )
    if candidate_text == source_text:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
        }
    metadata = _target_implicit_index_metadata(
        goal=goal,
        target_ig=target_ig,
        target_phys=target_phys,
        interferer_ig=interferer_ig,
        interferer_phys=interferer_phys,
        protected_targets=protected_targets,
        required_delta=required_delta,
        address_match=address_match,
        kind="target-aware-implicit-index-alias",
        strategy="implicit-index-alias",
        synthetic_local=index_name,
        rewritten_expression=rewritten_expression,
    )
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="target-aware-implicit-index-alias",
            metadata=metadata,
        ),
        {
            "status": "materialized",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
            "strategy": "implicit-index-alias",
        },
    )


def _materialize_target_implicit_base_alias(
    source_text: str,
    *,
    function: str,
    goal: Mapping[str, Any],
    target_ig: int,
    target_phys: int | None,
    interferer_ig: int,
    interferer_phys: int | None,
    protected_targets: Mapping[str, int],
    required_delta: int | None,
    source_expression: str,
    search_span: tuple[int, int],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "target-aware-implicit-base-alias"
    address_match, diag = _target_repair_address_source_match(
        source_text,
        goal=goal,
        source_expression=source_expression,
        search_span=search_span,
        handler=handler,
    )
    if diag is not None or address_match is None:
        return None, diag or {
            "status": "rejected",
            "reason": "address-source-expression-not-found",
            "handler": handler,
            "source_expression": source_expression,
        }
    executable_diag = _address_match_executable_line_diagnostic(
        address_match=address_match,
        handler=handler,
        source_expression=source_expression,
    )
    if executable_diag is not None:
        return None, executable_diag
    if not _safe_implicit_index_expr(address_match.source_index_expr):
        return None, {
            "status": "rejected",
            "reason": "unsafe-index-expression",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
        }
    insertion = _target_repair_assignment_insertion(
        source_text,
        function=function,
        address_match=address_match,
        search_span=search_span,
        handler=handler,
        source_expression=source_expression,
    )
    if isinstance(insertion, dict):
        return None, insertion
    decl_index, decl_indent, assignment_line_start, assignment_indent = insertion
    base_name = _target_repair_probe_local_name(
        source_text,
        f"base_ig{target_ig}",
    )
    rewritten_expression = _indexed_repair_expression(
        base_name,
        address_match.source_index_expr,
    )
    rewritten_line = _replace_line_span(
        address_match.line,
        line_start=address_match.line_start,
        span_start=address_match.expression_start,
        span_end=address_match.expression_end,
        replacement=rewritten_expression,
    )
    decl_type = _safe_decl_type_text(goal.get("source_type")) or "u8"
    candidate_text = _repair_candidate_text_from_edits(
        source_text,
        [
            (
                assignment_line_start,
                assignment_line_start,
                f"{assignment_indent}{base_name} = "
                f"{address_match.array_base};\n",
            ),
            (address_match.line_start, address_match.line_end, rewritten_line),
            (decl_index, decl_index, f"{decl_indent}{decl_type}* {base_name};\n"),
        ],
    )
    if candidate_text == source_text:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
        }
    metadata = _target_implicit_index_metadata(
        goal=goal,
        target_ig=target_ig,
        target_phys=target_phys,
        interferer_ig=interferer_ig,
        interferer_phys=interferer_phys,
        protected_targets=protected_targets,
        required_delta=required_delta,
        address_match=address_match,
        kind="target-aware-implicit-base-alias",
        strategy="implicit-base-alias",
        synthetic_local=base_name,
        rewritten_expression=rewritten_expression,
    )
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="target-aware-implicit-base-alias",
            metadata=metadata,
        ),
        {
            "status": "materialized",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_match.source_expression,
            "strategy": "implicit-base-alias",
        },
    )


def _materialize_target_address_side_temp(
    source_text: str,
    *,
    function: str,
    goal: Mapping[str, Any],
    target_ig: int,
    target_phys: int | None,
    interferer_ig: int,
    interferer_phys: int | None,
    protected_targets: Mapping[str, int],
    required_delta: int | None,
    source_expression: str,
    search_span: tuple[int, int],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "target-aware-address-side-pointer-temp"
    address = _target_repair_address_expression(goal, source_expression)
    if address is None:
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-indexed-byte",
            "handler": handler,
            "source_expression": source_expression,
        }
    requested_address_expression = address[3]
    if not _safe_target_repair_expression(requested_address_expression):
        return None, {
            "status": "rejected",
            "reason": "unsafe-address-expression",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": requested_address_expression,
        }
    address_match = _target_repair_address_match(
        source_text,
        address=address,
        search_span=search_span,
    )
    if address_match is None:
        return None, {
            "status": "rejected",
            "reason": "address-source-expression-not-found",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": requested_address_expression,
        }
    array_base = address_match.array_base
    address_index_expr = address_match.canonical_index_expr
    value_index_expr = address_match.value_index_expr
    address_expression = address_match.source_expression
    line_start = address_match.line_start
    line_end = address_match.line_end
    line = address_match.line
    stripped = line.strip()
    if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
        return None, {
            "status": "rejected",
            "reason": "unsafe-executable-line",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_expression,
        }
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None, {
            "status": "rejected",
            "reason": "source-ast-unavailable",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_expression,
        }
    decl_index, decl_indent = insertion
    if decl_index > line_start:
        return None, {
            "status": "rejected",
            "reason": "declaration-anchor-after-use",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_expression,
        }
    pointer_name = _target_repair_probe_local_name(
        source_text,
        f"address_ig{target_ig}_{_safe_label_part(address_index_expr)}",
    )
    rewritten_line = _replace_line_span(
        line,
        line_start=line_start,
        span_start=address_match.expression_start,
        span_end=address_match.expression_end,
        replacement=f"*{pointer_name}",
    )
    if rewritten_line == line:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_expression,
        }
    if _line_can_host_index_temp_assignment(stripped) and not stripped.startswith("for"):
        assignment_line_start = line_start
    else:
        assignment_line_start = _nearest_condition_start_line(
            source_text,
            line_start,
            search_span=search_span,
        )
    assignment_line_end = source_text.find("\n", assignment_line_start)
    if assignment_line_end < 0:
        assignment_line_end = len(source_text)
    assignment_indent_match = re.match(
        r"[ \t]*",
        source_text[assignment_line_start:assignment_line_end],
    )
    assignment_indent = (
        assignment_indent_match.group(0)
        if assignment_indent_match is not None
        else ""
    )
    decl_type = _safe_decl_type_text(goal.get("source_type")) or "u8"
    candidate_text = _repair_candidate_text_from_edits(
        source_text,
        [
            (
                assignment_line_start,
                assignment_line_start,
                f"{assignment_indent}{pointer_name} = &{address_expression};\n",
            ),
            (
                line_start,
                line_end,
                rewritten_line,
            ),
            (decl_index, decl_index, f"{decl_indent}{decl_type}* {pointer_name};\n"),
        ],
    )
    if candidate_text == source_text:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_expression,
        }
    metadata = _target_repair_metadata(
        goal=goal,
        target_ig=target_ig,
        target_phys=target_phys,
        interferer_ig=interferer_ig,
        interferer_phys=interferer_phys,
        protected_targets=protected_targets,
        required_delta=required_delta,
        kind="target-aware-address-side-temp",
        strategy="address-side-pointer-temp",
        source_expression=address_expression,
        synthetic_local=pointer_name,
        line_start=line_start,
        line_end=line_end,
    )
    metadata["ranked_repair_candidate"].update({
        "array_base": array_base,
        "address_index_expr": address_index_expr,
        "source_index_expr": address_match.source_index_expr,
        "value_index_expr": value_index_expr,
        "requested_address_expression": address_match.requested_expression,
        "address_expression": address_expression,
        "rewritten_expression": f"*{pointer_name}",
        "semantic_warning": "source-visible-address-temp",
    })
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="target-aware-address-side-temp",
            metadata=metadata,
        ),
        {
            "status": "materialized",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_expression,
            "requested_address_expression": address_match.requested_expression,
            "strategy": "address-side-pointer-temp",
            "semantic_warning": "source-visible-address-temp",
        },
    )


def _materialize_target_value_side_temp(
    source_text: str,
    *,
    function: str,
    goal: Mapping[str, Any],
    target_ig: int,
    target_phys: int | None,
    interferer_ig: int,
    interferer_phys: int | None,
    protected_targets: Mapping[str, int],
    required_delta: int | None,
    source_expression: str,
    search_span: tuple[int, int],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "target-aware-value-side-duplicate-temp"
    split = _split_indexed_repair_expression(source_expression)
    if split is None:
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-indexed-byte",
            "handler": handler,
            "source_expression": source_expression,
        }
    array_base, value_index_expr = split
    line_record = _first_expression_line_preferring_call(
        source_text,
        source_expression,
        call_name="GetNameText",
        search_span=search_span,
    )
    if line_record is None:
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-found",
            "handler": handler,
            "source_expression": source_expression,
        }
    line_start, line_end, line = line_record
    stripped = line.strip()
    if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
        return None, {
            "status": "rejected",
            "reason": "unsafe-executable-line",
            "handler": handler,
            "source_expression": source_expression,
        }
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None, {
            "status": "rejected",
            "reason": "source-ast-unavailable",
            "handler": handler,
            "source_expression": source_expression,
        }
    decl_index, decl_indent = insertion
    if decl_index > line_start:
        return None, {
            "status": "rejected",
            "reason": "declaration-anchor-after-use",
            "handler": handler,
            "source_expression": source_expression,
        }
    reserved_probe_names: set[str] = set()
    value_name = _target_repair_probe_local_name(
        source_text,
        f"value_ig{interferer_ig}_{_safe_label_part(value_index_expr)}",
        reserved=reserved_probe_names,
    )
    duplicate_ig = _repair_goal_int(goal, "duplicate_value_ig") or 41
    duplicate_name = _target_repair_probe_local_name(
        source_text,
        f"value_ig{duplicate_ig}_{_safe_label_part(value_index_expr)}",
        reserved=reserved_probe_names,
    )
    rewritten_line = line.replace(source_expression, duplicate_name, 1)
    if rewritten_line == line:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
        }
    indent = re.match(r"[ \t]*", line).group(0)
    decl_type = _safe_decl_type_text(goal.get("source_type")) or "u8"
    candidate_text = _repair_candidate_text_from_edits(
        source_text,
        [
            (
                line_start,
                line_end,
                f"{indent}{value_name} = {source_expression};\n"
                f"{indent}{duplicate_name} = {value_name};\n"
                f"{rewritten_line}",
            ),
            (
                decl_index,
                decl_index,
                f"{decl_indent}{decl_type} {value_name};\n"
                f"{decl_indent}{decl_type} {duplicate_name};\n",
            ),
        ],
    )
    if candidate_text == source_text:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
        }
    metadata = _target_repair_metadata(
        goal=goal,
        target_ig=target_ig,
        target_phys=target_phys,
        interferer_ig=interferer_ig,
        interferer_phys=interferer_phys,
        protected_targets=protected_targets,
        required_delta=required_delta,
        kind="target-aware-value-side-temp",
        strategy="value-side-duplicate-temp",
        source_expression=source_expression,
        synthetic_local=value_name,
        line_start=line_start,
        line_end=line_end,
    )
    metadata["ranked_repair_candidate"].update({
        "array_base": array_base,
        "value_index_expr": value_index_expr,
        "duplicate_value_ig": duplicate_ig,
        "duplicate_value_temp": duplicate_name,
        "rewritten_expression": duplicate_name,
    })
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="target-aware-value-side-temp",
            metadata=metadata,
        ),
        {
            "status": "materialized",
            "handler": handler,
            "source_expression": source_expression,
            "strategy": "value-side-duplicate-temp",
        },
    )


def _materialize_target_coupled_address_value_temp(
    source_text: str,
    *,
    function: str,
    goal: Mapping[str, Any],
    target_ig: int,
    target_phys: int | None,
    interferer_ig: int,
    interferer_phys: int | None,
    protected_targets: Mapping[str, int],
    required_delta: int | None,
    source_expression: str,
    search_span: tuple[int, int],
) -> tuple[_LocalLifetimeProbeCandidate | None, dict[str, Any]]:
    handler = "target-aware-coupled-address-value-temp"
    address = _target_repair_address_expression(goal, source_expression)
    if address is None:
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-indexed-byte",
            "handler": handler,
            "source_expression": source_expression,
        }
    requested_address_expression = address[3]
    value_line_record = _first_expression_line_preferring_call(
        source_text,
        source_expression,
        call_name="GetNameText",
        search_span=search_span,
    )
    address_match = _target_repair_address_match(
        source_text,
        address=address,
        search_span=search_span,
    )
    if value_line_record is None or address_match is None:
        return None, {
            "status": "rejected",
            "reason": "coupled-source-expression-not-found",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": requested_address_expression,
            "missing_value_expression": value_line_record is None,
            "missing_address_expression": address_match is None,
        }
    array_base = address_match.array_base
    address_index_expr = address_match.canonical_index_expr
    value_index_expr = address_match.value_index_expr
    address_expression = address_match.source_expression
    value_line_start, value_line_end, value_line = value_line_record
    address_line_start = address_match.line_start
    address_line_end = address_match.line_end
    address_line = address_match.line
    for line in (value_line, address_line):
        stripped = line.strip()
        if not stripped or _line_has_unsafe_label_or_preprocessor(stripped):
            return None, {
                "status": "rejected",
                "reason": "unsafe-executable-line",
                "handler": handler,
                "source_expression": source_expression,
                "address_expression": address_expression,
            }
    insertion = _function_decl_insertion(source_text, function)
    if insertion is None:
        return None, {
            "status": "rejected",
            "reason": "source-ast-unavailable",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_expression,
        }
    decl_index, decl_indent = insertion
    first_use = min(value_line_start, address_line_start)
    if decl_index > first_use:
        return None, {
            "status": "rejected",
            "reason": "declaration-anchor-after-use",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_expression,
        }
    reserved_probe_names: set[str] = set()
    pointer_name = _target_repair_probe_local_name(
        source_text,
        f"address_ig{target_ig}_{_safe_label_part(address_index_expr)}",
        reserved=reserved_probe_names,
    )
    value_name = _target_repair_probe_local_name(
        source_text,
        f"value_ig{interferer_ig}_{_safe_label_part(value_index_expr)}",
        reserved=reserved_probe_names,
    )
    duplicate_ig = _repair_goal_int(goal, "duplicate_value_ig") or 41
    duplicate_name = _target_repair_probe_local_name(
        source_text,
        f"value_ig{duplicate_ig}_{_safe_label_part(value_index_expr)}",
        reserved=reserved_probe_names,
    )
    value_expr_start = value_line.find(source_expression)
    if value_expr_start < 0:
        return None, {
            "status": "rejected",
            "reason": "source-expression-not-found",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_expression,
        }
    value_expr_abs_start = value_line_start + value_expr_start
    value_expr_abs_end = value_expr_abs_start + len(source_expression)
    rewritten_value_line = _replace_line_span(
        value_line,
        line_start=value_line_start,
        span_start=value_expr_abs_start,
        span_end=value_expr_abs_end,
        replacement=duplicate_name,
    )
    rewritten_address_line = _replace_line_span(
        address_line,
        line_start=address_line_start,
        span_start=address_match.expression_start,
        span_end=address_match.expression_end,
        replacement=f"*{pointer_name}",
    )
    if rewritten_value_line == value_line or rewritten_address_line == address_line:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_expression,
        }

    insert_line = value_line if value_line_start <= address_line_start else address_line
    indent = re.match(r"[ \t]*", insert_line).group(0)
    decl_type = _safe_decl_type_text(goal.get("source_type")) or "u8"
    hoisted_index_assignment = _target_repair_hoistable_index_assignment(
        source_text,
        index_expr=value_index_expr,
        after_start=first_use,
        before_start=value_line_start,
        search_span=search_span,
    )
    hoisted_assignment_text = ""
    if hoisted_index_assignment is not None:
        (
            hoisted_assignment_start,
            hoisted_assignment_end,
            hoisted_index_name,
            hoisted_index_rhs,
        ) = hoisted_index_assignment
        hoisted_assignment_text = (
            f"{indent}{hoisted_index_name} = {hoisted_index_rhs};\n"
        )
    else:
        hoisted_assignment_start = hoisted_assignment_end = -1
    edits: list[tuple[int, int, str]] = [
        (
            first_use,
            first_use,
            f"{hoisted_assignment_text}"
            f"{indent}{pointer_name} = &{address_expression};\n"
            f"{indent}{value_name} = {source_expression};\n"
            f"{indent}{duplicate_name} = {value_name};\n",
        ),
        (
            decl_index,
            decl_index,
            f"{decl_indent}{decl_type}* {pointer_name};\n"
            f"{decl_indent}{decl_type} {value_name};\n"
            f"{decl_indent}{decl_type} {duplicate_name};\n",
        ),
    ]
    if hoisted_index_assignment is not None:
        edits.append((hoisted_assignment_start, hoisted_assignment_end, ""))
    if value_line_start == address_line_start:
        rewritten_line = _replace_line_spans(
            value_line,
            line_start=value_line_start,
            replacements=[
                (value_expr_abs_start, value_expr_abs_end, duplicate_name),
                (
                    address_match.expression_start,
                    address_match.expression_end,
                    f"*{pointer_name}",
                ),
            ],
        )
        edits.append((value_line_start, value_line_end, rewritten_line))
    else:
        edits.extend([
            (value_line_start, value_line_end, rewritten_value_line),
            (address_line_start, address_line_end, rewritten_address_line),
        ])
    candidate_text = _repair_candidate_text_from_edits(source_text, edits)
    if candidate_text == source_text:
        return None, {
            "status": "rejected",
            "reason": "source-unchanged",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_expression,
        }
    metadata = _target_repair_metadata(
        goal=goal,
        target_ig=target_ig,
        target_phys=target_phys,
        interferer_ig=interferer_ig,
        interferer_phys=interferer_phys,
        protected_targets=protected_targets,
        required_delta=required_delta,
        kind="target-aware-coupled-address-value",
        strategy="coupled-address-value-temps",
        source_expression=source_expression,
        synthetic_local=value_name,
        line_start=first_use,
        line_end=max(value_line_end, address_line_end),
    )
    metadata["ranked_repair_candidate"].update({
        "array_base": array_base,
        "address_index_expr": address_index_expr,
        "source_index_expr": address_match.source_index_expr,
        "value_index_expr": value_index_expr,
        "requested_address_expression": address_match.requested_expression,
        "address_expression": address_expression,
        "address_temp": pointer_name,
        "value_temp": value_name,
        "duplicate_value_ig": duplicate_ig,
        "duplicate_value_temp": duplicate_name,
        "semantic_warning": "source-visible-address-temp",
    })
    if hoisted_index_assignment is not None:
        metadata["ranked_repair_candidate"]["hoisted_value_index_assignment"] = {
            "index_temp": hoisted_index_name,
            "rhs": hoisted_index_rhs,
            "line_source_span": [
                hoisted_assignment_start,
                hoisted_assignment_end,
            ],
        }
    return (
        _LocalLifetimeProbeCandidate(
            source_text=candidate_text,
            provenance_kind="target-aware-coupled-address-value",
            metadata=metadata,
        ),
        {
            "status": "materialized",
            "handler": handler,
            "source_expression": source_expression,
            "address_expression": address_expression,
            "requested_address_expression": address_match.requested_expression,
            "strategy": "coupled-address-value-temps",
            "semantic_warning": "source-visible-address-temp",
        },
    )


def plan_target_aware_live_range_repair_probes(
    source_text: str,
    *,
    function: str,
    repair_goals: Iterable[Mapping[str, Any]],
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None = None,
    max_probes: int = 8,
) -> WindowOrderSourceProbePlan:
    """Plan target/interferer source probes for retained Case-C GPR frontiers."""

    limit = max(0, int(max_probes))
    probes: list[LifetimeLayoutProbe] = []
    diagnostics: list[dict[str, Any]] = []
    seen_source: set[str] = set()
    search_span = _repair_search_span(source_text, function)

    for goal in repair_goals:
        diag: dict[str, Any] = {
            "repair_goal": dict(goal),
            "status": "blocked",
        }
        target_ig = _repair_goal_int(goal, "target_ig")
        interferer_ig = _repair_goal_int(goal, "interferer_ig")
        if target_ig is None or interferer_ig is None:
            diag["status"] = "needs_context"
            diag["terminal_blocker"] = "missing-target-or-interferer-ig"
            diagnostics.append(diag)
            continue
        target_phys = _repair_goal_int(goal, "target_phys")
        interferer_phys = _repair_goal_int(goal, "interferer_phys")
        required_delta = _repair_goal_int(goal, "required_delta")
        protected_targets = _repair_goal_mapping(goal, "protected_targets")
        source_expression = _repair_source_expression(
            goal,
            source_attributions,
            interferer_ig,
        )
        diag.update({
            "target_ig": target_ig,
            "target_phys": target_phys,
            "interferer_ig": interferer_ig,
            "interferer_phys": interferer_phys,
            "protected_targets": protected_targets,
            "required_delta": required_delta,
        })
        if source_expression is None:
            diag["status"] = "needs_context"
            diag["terminal_blocker"] = "missing-interferer-source-binding"
            diagnostics.append(diag)
            continue
        diag["source_expression"] = source_expression

        candidate_results = [
            _materialize_target_live_range_expression_temp(
                source_text,
                function=function,
                goal=goal,
                target_ig=target_ig,
                target_phys=target_phys,
                interferer_ig=interferer_ig,
                interferer_phys=interferer_phys,
                protected_targets=protected_targets,
                required_delta=required_delta,
                source_expression=source_expression,
                search_span=search_span,
            ),
            _materialize_target_scalar_duplicate_temp(
                source_text,
                function=function,
                goal=goal,
                target_ig=target_ig,
                target_phys=target_phys,
                interferer_ig=interferer_ig,
                interferer_phys=interferer_phys,
                protected_targets=protected_targets,
                required_delta=required_delta,
                source_expression=source_expression,
                search_span=search_span,
            ),
            _materialize_target_scalar_pair_overlap_temp(
                source_text,
                function=function,
                goal=goal,
                target_ig=target_ig,
                target_phys=target_phys,
                interferer_ig=interferer_ig,
                interferer_phys=interferer_phys,
                protected_targets=protected_targets,
                required_delta=required_delta,
                source_expression=source_expression,
                search_span=search_span,
            ),
            _materialize_target_interference_index_temp(
                source_text,
                function=function,
                goal=goal,
                target_ig=target_ig,
                target_phys=target_phys,
                interferer_ig=interferer_ig,
                interferer_phys=interferer_phys,
                protected_targets=protected_targets,
                required_delta=required_delta,
                source_expression=source_expression,
                search_span=search_span,
            ),
            _materialize_target_implicit_index_normalize(
                source_text,
                goal=goal,
                target_ig=target_ig,
                target_phys=target_phys,
                interferer_ig=interferer_ig,
                interferer_phys=interferer_phys,
                protected_targets=protected_targets,
                required_delta=required_delta,
                source_expression=source_expression,
                search_span=search_span,
            ),
            _materialize_target_implicit_index_alias(
                source_text,
                function=function,
                goal=goal,
                target_ig=target_ig,
                target_phys=target_phys,
                interferer_ig=interferer_ig,
                interferer_phys=interferer_phys,
                protected_targets=protected_targets,
                required_delta=required_delta,
                source_expression=source_expression,
                search_span=search_span,
            ),
            _materialize_target_implicit_base_alias(
                source_text,
                function=function,
                goal=goal,
                target_ig=target_ig,
                target_phys=target_phys,
                interferer_ig=interferer_ig,
                interferer_phys=interferer_phys,
                protected_targets=protected_targets,
                required_delta=required_delta,
                source_expression=source_expression,
                search_span=search_span,
            ),
            _materialize_target_address_side_temp(
                source_text,
                function=function,
                goal=goal,
                target_ig=target_ig,
                target_phys=target_phys,
                interferer_ig=interferer_ig,
                interferer_phys=interferer_phys,
                protected_targets=protected_targets,
                required_delta=required_delta,
                source_expression=source_expression,
                search_span=search_span,
            ),
            _materialize_target_value_side_temp(
                source_text,
                function=function,
                goal=goal,
                target_ig=target_ig,
                target_phys=target_phys,
                interferer_ig=interferer_ig,
                interferer_phys=interferer_phys,
                protected_targets=protected_targets,
                required_delta=required_delta,
                source_expression=source_expression,
                search_span=search_span,
            ),
            _materialize_target_coupled_address_value_temp(
                source_text,
                function=function,
                goal=goal,
                target_ig=target_ig,
                target_phys=target_phys,
                interferer_ig=interferer_ig,
                interferer_phys=interferer_phys,
                protected_targets=protected_targets,
                required_delta=required_delta,
                source_expression=source_expression,
                search_span=search_span,
            ),
        ]
        materialized_labels: list[str] = []
        materialized_meta: list[dict[str, Any]] = []
        candidate_diagnostics: list[dict[str, Any]] = []
        first_source_diff: str | None = None
        for lifetime_candidate, candidate_diag in candidate_results:
            candidate_diagnostics.append(candidate_diag)
            if lifetime_candidate is None:
                continue
            if len(probes) >= limit:
                candidate_diag["status"] = "rejected"
                candidate_diag["reason"] = "probe-limit-reached"
                continue
            if lifetime_candidate.source_text in seen_source:
                candidate_diag["status"] = "rejected"
                candidate_diag["reason"] = "duplicate-source-move"
                continue
            seen_source.add(lifetime_candidate.source_text)
            label = (
                "target-live-range-"
                f"ig{target_ig}-r{target_phys or 'x'}-"
                f"interferer-ig{interferer_ig}-"
                f"{len(probes)}"
            )
            metadata = dict(lifetime_candidate.metadata)
            metadata["probe_label"] = label
            probes.append(
                LifetimeLayoutProbe(
                    label=label,
                    operator="target-aware-live-range-repair",
                    description=(
                        "Materialize target-aware retained Case-C "
                        "live-range/interference repair probe."
                    ),
                    source_text=lifetime_candidate.source_text,
                    provenance=metadata,
                )
            )
            materialized_labels.append(label)
            materialized_meta.append(metadata)
            candidate_diag["probe_label"] = label
            if first_source_diff is None:
                first_source_diff = _source_diff(
                    source_text,
                    lifetime_candidate.source_text,
                )
        diag["repair_candidate_diagnostics"] = candidate_diagnostics
        diag["repair_candidate_summary"] = {
            "candidate_count": len(candidate_results),
            "materialized_count": len(materialized_labels),
            "reasons": _candidate_reason_counts(candidate_diagnostics),
        }
        if materialized_labels:
            diag["status"] = "materialized"
            diag["materialized_probe_labels"] = materialized_labels
            diag["materialized_repair_candidates"] = materialized_meta
            if first_source_diff is not None:
                diag["source_diff"] = first_source_diff
            diag.pop("terminal_blocker", None)
        elif len(probes) >= limit:
            diag["terminal_blocker"] = "probe-limit-reached"
        else:
            diag["terminal_blocker"] = "target-aware-repair-source-span-not-found"
        diagnostics.append(diag)

    return WindowOrderSourceProbePlan(
        probes=probes,
        lead_diagnostics=diagnostics,
    )


def generate_window_order_source_probes(
    source_text: str,
    *,
    function: str,
    fallback_leads: Iterable[Mapping[str, Any]],
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None = None,
    max_probes: int = 8,
) -> list[LifetimeLayoutProbe]:
    """Generate conservative source moves for solver window-order fallback leads."""

    return plan_window_order_source_probes(
        source_text,
        function=function,
        fallback_leads=fallback_leads,
        source_attributions=source_attributions,
        max_probes=max_probes,
    ).probes
