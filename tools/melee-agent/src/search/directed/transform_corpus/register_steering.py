"""Source-transform family: register_steering."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _blank_literals_and_comments, _identifier_is_member_name, _identifier_mentions, _is_scalar_type, _is_supported_local_reuse_type, _line_depths_from_blanked_text, _line_has_label, _macro_like_statement, _normalize_local_reuse_type, _parse_signature_params, _split_top_level_csv, _text_line_records, _text_line_records_with_newline
from typing import Any, Mapping


_REGISTER_STEERING_DECL_RE = re.compile(
    r"^(?P<indent>[ \t]+)"
    r"(?P<type>(?:struct\s+|enum\s+)?[A-Za-z_]\w*"
    r"(?:(?:\s+|\s*\*)[A-Za-z_]\w*|\s*\*)*)"
    r"\s+"
    r"(?P<var>[A-Za-z_]\w*)"
    r"(?P<rest>\s*(?:=\s*(?P<init>[^;]+))?)"
    r"\s*;$"
)


_REGISTER_STEERING_COUNTER_RE = re.compile(r"\b(s16|s32)\b")


_NODE_SET_SPLIT_SYNTHETIC_NAME_RE = re.compile(r"_split_\d+_\d+$")


_GENERATED_FPR_PRODUCT_TEMP_RE = re.compile(r"_product(?:_reuse)?_fpr(?:_\d+)?$")


_REGISTER_STEERING_FPR_TYPES = frozenset({"float", "f32", "double", "f64"})


_REGISTER_STEERING_DECL_QUALIFIER_RE = r"(?:auto|const|extern|register|static|volatile)"


_REGISTER_STEERING_ASSIGN_RE = re.compile(
    r"^(?P<indent>[ \t]+)(?P<lhs>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.+?)\s*;\s*$"
)


_REGISTER_STEERING_GPR_INDEXED_ASSIGN_RE = re.compile(
    r"^(?P<indent>[ \t]+)"
    r"(?P<lhs>[A-Za-z_]\w*)"
    r"\s*=\s*"
    r"(?P<base>[A-Za-z_]\w*(?:(?:\.|->)[A-Za-z_]\w*)*)"
    r"\s*\[(?P<index>[^\]\n]+)\]\s*;\s*$"
)


_REGISTER_STEERING_GPR_FOR_OWNER_RE = re.compile(
    r"^(?P<indent>[ \t]+)for\s*\((?P<header>.*\b(?P<owner>[A-Za-z_]\w*)\+\+.*)\)\s*\{\s*$"
)


_REGISTER_STEERING_GPR_POINTER_STORE_RE = re.compile(
    r"^(?P<indent>[ \t]+)\*(?P<owner>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.+?)\s*;\s*$"
)


_REGISTER_STEERING_SUB_ASSIGN_RE = re.compile(
    r"^(?P<indent>[ \t]+)(?P<lhs>[A-Za-z_]\w*)\s*-=\s*(?P<rhs>.+?)\s*;\s*$"
)


_GPR_BOOL_MASK_CONST_ATOM_PATTERN = (
    r"(?:0x[0-9A-Fa-f]+(?:[uUlL]*)?|\d+(?:[uUlL]*)?|[A-Z_]\w*)"
)


_GPR_BOOL_MASK_CONST_BASE_PATTERN = (
    rf"{_GPR_BOOL_MASK_CONST_ATOM_PATTERN}"
    rf"(?:\s*(?:<<|\|)\s*{_GPR_BOOL_MASK_CONST_ATOM_PATTERN})*"
)


_GPR_BOOL_MASK_CONST_PATTERN = (
    rf"(?:\(\s*{_GPR_BOOL_MASK_CONST_BASE_PATTERN}\s*\)"
    rf"|{_GPR_BOOL_MASK_CONST_BASE_PATTERN})"
)


_GPR_BOOL_MASK_OPERAND_RE = re.compile(
    r"(?P<open>\(\s*)?"
    r"(?P<expr>[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)"
    r"\s*&\s*"
    rf"(?P<mask>{_GPR_BOOL_MASK_CONST_PATTERN})"
    r"(?P<close>\s*\))?"
)


_GPR_NEGATED_FIELD_MASK_RE = re.compile(
    r"!\s*\(\s*"
    r"(?P<expr>[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*(?:->|\.)flags)"
    r"\s*&\s*"
    rf"(?P<mask>{_GPR_BOOL_MASK_CONST_PATTERN})"
    r"\s*\)"
)


_HSD_JOBJ_TRANSLATE_CALL_RE = re.compile(
    r"^(?P<indent>[ \t]+)"
    r"(?P<callee>HSD_JObjSetTranslate(?P<axis>[XYZ]))"
    r"\s*\((?P<args>.*)\)\s*;\s*$"
)


_REGISTER_STEERING_DEPENDENT_RE = re.compile(
    r"^(?P<lhs>[A-Za-z_]\w*)\s*(?P<op>[+-])\s*(?P<const>(?:\d+(?:\.\d*)?|\.\d+)(?:f)?)$|"
    r"^(?P<const_left>(?:\d+(?:\.\d*)?|\.\d+)(?:f)?)\s*(?P<op_left>[+-])\s*(?P<lhs_right>[A-Za-z_]\w*)$"
)


_REGISTER_STEERING_RECOMPUTE_DECL_LINE_RE = re.compile(
    r"^[ \t]*"
    r"(?:" + _REGISTER_STEERING_DECL_QUALIFIER_RE + r"\s+)*"
    r"(?P<type>(?:(?:struct|enum|union)\s+[A-Za-z_]\w*\s*\**)|(?:[A-Za-z_]\w*\s*\**))"
    r"\s+"
    r"(?P<decls>\**\s*[A-Za-z_]\w*[^;]*)"
    r"\s*;$"
)


_REGISTER_STEERING_RECOMPUTE_NON_DECL_HEADS = frozenset({
    "break",
    "case",
    "continue",
    "default",
    "do",
    "else",
    "for",
    "goto",
    "if",
    "return",
    "sizeof",
    "switch",
    "while",
})


_REGISTER_STEERING_RECOMPUTE_DECL_STARTERS = frozenset({
    "auto",
    "char",
    "const",
    "double",
    "enum",
    "extern",
    "f32",
    "f64",
    "float",
    "int",
    "long",
    "register",
    "s16",
    "s32",
    "s8",
    "short",
    "signed",
    "static",
    "struct",
    "u16",
    "u32",
    "u8",
    "union",
    "unsigned",
    "void",
    "volatile",
})


_REGISTER_STEERING_REJECTED_TYPE_TOKENS = frozenset({
    "const",
    "extern",
    "inline",
    "register",
    "static",
    "volatile",
})


@dataclass(frozen=True)
class _RegisterSteeringDecl:
    idx: int
    start: int
    end: int
    end_with_newline: int
    line: str
    type_name: str
    name: str
    init: str
    depth: int
    name_span: tuple[int, int]


@dataclass(frozen=True)
class _RegisterSteeringFprProduct:
    idx: int
    start: int
    end: int
    line: str
    indent: str
    lhs: str
    product_expr: str
    operand_names: tuple[str, str]
    cast_operand_names: tuple[str, ...]


@dataclass(frozen=True)
class _RegisterSteeringDependentProduct:
    op: str
    const_text: str
    const_on_left: bool = False


@dataclass(frozen=True)
class _RegisterSteeringDependentProductCase:
    start: int
    next_end: int
    indent: str
    primary: str
    dependent: str
    product_expr: str
    dependent_parts: _RegisterSteeringDependentProduct
    primary_decl: _RegisterSteeringDecl
    alias_local: str | None = None


@dataclass(frozen=True)
class _RegisterSteeringCaseCFprSetup:
    idx: int
    start: int
    end: int
    indent: str
    target: str
    target_type: str
    call_expr: str
    rhs_local: str
    split_setup_text: str


@dataclass(frozen=True)
class _RegisterSteeringHsdReqAnimCallArg:
    idx: int
    start: int
    end: int
    line: str
    indent: str
    callee: str
    args: tuple[str, ...]
    arg_text: str
    call_arg_local: str | None
    call_arg_expr: str
    call_arg_operand: str
    call_arg_type: str
    assignment_start: int | None = None
    assignment_end: int | None = None
    assignment_line: str | None = None


@dataclass(frozen=True)
class _RegisterSteeringFprOwnerAssignment:
    idx: int
    start: int
    end: int
    line: str
    indent: str
    lhs: str
    rhs_expr: str
    kind: str
    decl_type: str
    operand_names: tuple[str, ...]


@dataclass(frozen=True)
class _RegisterSteeringGprIndexedAssignment:
    idx: int
    start: int
    end: int
    line: str
    indent: str
    lhs: str
    base: str
    index_expr: str
    element_type: str
    base_is_pointer_local: bool


@dataclass(frozen=True)
class _RegisterSteeringGprPointerCopyAssignment:
    idx: int
    start: int
    end: int
    line: str
    indent: str
    lhs: str
    rhs_expr: str


@dataclass(frozen=True)
class _RegisterSteeringGprCaseCCopyProduct:
    owner: str
    owner_type: str
    owner_decl: _RegisterSteeringDecl
    decl_indent: str
    case_c_target_local: str
    case_c_target_type: str
    copy: _RegisterSteeringGprPointerCopyAssignment | None
    loop_idx: int
    loop_start: int
    loop_end: int
    loop_line: str
    loop_indent: str
    store_idx: int
    store_start: int
    store_end: int
    store_line: str
    store_indent: str
    store_rhs: str


@dataclass(frozen=True)
class _RegisterSteeringTranslateYCall:
    idx: int
    start: int
    end: int
    line: str
    indent: str
    args: tuple[str, ...]
    value_arg: str


@dataclass(frozen=True)
class _RegisterSteeringMixedPcodeFprLifetimeCase:
    row_local: str
    row_adj_local: str
    row_adj_owner_local: str
    row_adj_decl_type: str
    owner_assignment: _RegisterSteeringFprOwnerAssignment
    row_adj_assignment_start: int
    row_adj_assignment_end: int
    row_adj_assignment_line: str
    digit_call: _RegisterSteeringHsdReqAnimCallArg
    row_translate_call: _RegisterSteeringTranslateYCall
    row_adj_translate_call: _RegisterSteeringTranslateYCall


@dataclass(frozen=True)
class _RegisterSteeringCallargLocalStructuralCase:
    digit_count_start: int
    digit_count_end: int
    digit_count_line: str
    digit_count_local: str
    product: _RegisterSteeringFprProduct
    product_handoff_start: int
    product_handoff_end: int
    product_handoff_line: str
    product_handoff_local: str
    row_cast_line: str
    row_local: str
    rowf_local: str
    row_scale_line: str
    row_adj_owner_assignment: _RegisterSteeringFprOwnerAssignment
    row_adj_start: int
    row_adj_end: int
    row_adj_line: str
    row_adj_local: str
    digit_call: _RegisterSteeringHsdReqAnimCallArg
    digit_assignment_start: int | None
    digit_assignment_end: int | None
    digit_assignment_line: str | None
    callarg_assignment_start: int | None
    callarg_assignment_end: int | None
    callarg_assignment_line: str | None
    callarg_local: str
    callarg_local_kind: str
    callarg_decl: _RegisterSteeringDecl | None
    loop_start: int
    loop_end: int


def _line_brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")


def _register_steering_decl_match(line: str):
    if not line or line.lstrip().startswith("#") or "(" in line or ")" in line:
        return None
    match = _REGISTER_STEERING_DECL_RE.match(line)
    if match is None:
        return None
    rest = match.group("rest") or ""
    if "," in rest or "[" in rest or "]" in rest:
        return None
    type_tokens = set(re.findall(r"\b[A-Za-z_]\w*\b", match.group("type")))
    if type_tokens & _REGISTER_STEERING_REJECTED_TYPE_TOKENS:
        return None
    return match


def _register_steering_reorder_safe(match) -> bool:
    return not (match.group("init") or "").strip()


def _register_steering_decl_records(body_text: str) -> tuple[_RegisterSteeringDecl, ...] | None:
    blanked = _blank_literals_and_comments(body_text)
    depths = _line_depths_from_blanked_text(blanked)
    records = _text_line_records_with_newline(body_text)
    decls: list[_RegisterSteeringDecl] = []
    for idx, (start, end, end_with_newline, line) in enumerate(records):
        depth = depths[idx] if idx < len(depths) else 0
        raw_match = _REGISTER_STEERING_DECL_RE.match(line)
        match = _register_steering_decl_match(line)
        if raw_match is not None and match is None and depth == 1:
            return None
        if match is None:
            continue
        type_name = _normalize_local_reuse_type(match.group("type").strip())
        decls.append(
            _RegisterSteeringDecl(
                idx=idx,
                start=start,
                end=end,
                end_with_newline=end_with_newline,
                line=line,
                type_name=type_name,
                name=match.group("var"),
                init=(match.group("init") or "").strip(),
                depth=depth,
                name_span=(start + match.start("var"), start + match.end("var")),
            )
        )
    return tuple(decls)


def _register_steering_concrete_type_supported(type_name: str) -> bool:
    return _is_supported_local_reuse_type(type_name)


def _register_steering_has_duplicate_top_level_names(
    decls: tuple[_RegisterSteeringDecl, ...],
) -> bool:
    names = [decl.name for decl in decls if decl.depth == 1]
    return len(names) != len(set(names))


def _node_set_split_synthetic_name(name: str) -> bool:
    return _NODE_SET_SPLIT_SYNTHETIC_NAME_RE.search(name) is not None


def _generated_fpr_product_temp_name(name: str) -> bool:
    return _GENERATED_FPR_PRODUCT_TEMP_RE.search(name) is not None


def _steering_first_use_allowed(line: str, name: str) -> bool:
    stripped = line.strip()
    if not stripped.endswith(";"):
        return False
    if _macro_like_statement(line) or _line_has_label(line):
        return False
    if re.search(r"\b(?:goto|case|default|return|break|continue)\b", stripped):
        return False
    if "++" in stripped or "--" in stripped:
        return False
    if re.search(r"&\s*" + re.escape(name) + r"\b", stripped):
        return False
    if re.search(r"\b" + re.escape(name) + r"\s*[+\-*/%&|^]=", stripped):
        return False
    if re.match(r"\s*" + re.escape(name) + r"\s*=\s*.+;\s*$", line):
        return True
    if re.match(r"\s*[A-Za-z_]\w*\s*\([^;]*\b" + re.escape(name) + r"\b[^;]*\)\s*;\s*$", line):
        return True
    return re.match(
        r"\s*[A-Za-z_]\w*\s*=\s*[^;]*\b" + re.escape(name) + r"\b[^;]*;\s*$",
        line,
    ) is not None


def _steering_crossed_region_has_barrier(region: str, name: str) -> bool:
    if "{" in region or "}" in region or "#" in region:
        return True
    for _start, _end, line in _text_line_records(region):
        if _line_has_label(line) or _macro_like_statement(line):
            return True
        if re.search(
            r"\b(?:if|for|while|do|switch|goto|case|default|break|continue)\b",
            line,
        ):
            return True
        if re.search(r"\b" + re.escape(name) + r"\b", line):
            return True
    return False


def _line_record_for_offset(
    records: list[tuple[int, int, int, str]],
    offset: int,
) -> tuple[int, int, int, str] | None:
    for record in records:
        start, end, end_with_newline, _line = record
        if start <= offset <= end_with_newline:
            return record
    return None


def _iter_decl_window_rotation_anchors(
    body_text: str,
    decls: tuple[_RegisterSteeringDecl, ...],
) -> list[Anchor]:
    anchors: list[Anchor] = []
    top = [
        decl for decl in decls
        if decl.depth == 1 and not _node_set_split_synthetic_name(decl.name)
    ]
    for a, b, c in zip(top, top[1:], top[2:]):
        if a.idx + 1 != b.idx or b.idx + 1 != c.idx:
            continue
        window = (a, b, c)
        if any(decl.init for decl in window):
            continue
        if any(not _register_steering_concrete_type_supported(decl.type_name) for decl in window):
            continue
        span_text = body_text[a.start:c.end]
        if body_text.count(span_text) != 1:
            continue
        replacement_text = "\n".join((c.line, a.line, b.line))
        anchors.append(
            Anchor(
                mutator_key="steer_rotate_local_decl_window",
                span=(a.start, c.end),
                payload={
                    "span_text": span_text,
                    "replacement_text": replacement_text,
                    "strategy": "decl-window-rotate",
                    "decl_names": (a.name, b.name, c.name),
                },
            )
        )
    return anchors


def _iter_uninitialized_decl_runs(
    decls: tuple[_RegisterSteeringDecl, ...],
) -> list[tuple[_RegisterSteeringDecl, ...]]:
    runs: list[tuple[_RegisterSteeringDecl, ...]] = []
    current: list[_RegisterSteeringDecl] = []
    for decl in (
        candidate for candidate in decls
        if candidate.depth == 1 and not _node_set_split_synthetic_name(candidate.name)
    ):
        is_supported = (
            not decl.init and _register_steering_concrete_type_supported(decl.type_name)
        )
        is_contiguous = bool(current) and decl.idx == current[-1].idx + 1
        if is_supported and (not current or is_contiguous):
            current.append(decl)
            continue
        if current:
            runs.append(tuple(current))
        current = [decl] if is_supported else []
    if current:
        runs.append(tuple(current))
    return runs


def _iter_decl_demote_anchors(
    body_text: str,
    decls: tuple[_RegisterSteeringDecl, ...],
) -> list[Anchor]:
    anchors: list[Anchor] = []
    for run in _iter_uninitialized_decl_runs(decls):
        if len(run) < 2:
            continue
        target = run[-1]
        for index, decl in enumerate(run[:-1]):
            moved = (*run[index + 1 :], decl)
            span_text = body_text[decl.start:target.end]
            if body_text.count(span_text) != 1:
                continue
            replacement_text = "\n".join(item.line for item in moved)
            anchors.append(
                Anchor(
                    mutator_key="steer_demote_local_decl_to_first_use",
                    span=(decl.start, target.end),
                    payload={
                        "span_text": span_text,
                        "replacement_text": replacement_text,
                        "strategy": "decl-demote-within-prologue",
                        "decl_name": decl.name,
                    },
                )
            )
    return anchors


@dataclass(frozen=True)
class _RegisterSteeringLoop:
    idx: int
    start: int
    end: int
    line: str
    counter: str
    indent: str
    depth: int


@dataclass(frozen=True)
class _RegisterSteeringDeadCounterLoop:
    idx: int
    start: int
    end: int
    counter: str
    kind: str
    prelude_start: int


_REGISTER_STEERING_FOR_RE = re.compile(
    r"^(?P<indent>[ \t]*)for\s*\(\s*(?P<counter>[A-Za-z_]\w*)\s*=\s*(?P<init>[^;]+);\s*"
    r"[^;]*\b(?P=counter)\b[^;]*;\s*(?:(?P=counter)\s*\+\+|\+\+\s*(?P=counter)|"
    r"(?P=counter)\s*\+=\s*1)\s*\)\s*{\s*$"
)


_REGISTER_STEERING_DO_RE = re.compile(r"^(?P<indent>[ \t]*)do\s*{\s*$")


_REGISTER_STEERING_COUNTER_ASSIGN_RE = re.compile(
    r"^[ \t]*(?P<counter>[A-Za-z_]\w*)\s*=\s*(?P<init>[^;]+);\s*$"
)


_REGISTER_STEERING_BYTE_DECL_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<from>u8|s8)\s+(?P<name>[A-Za-z_]\w*)\s*;$"
)


_REGISTER_STEERING_DECL_LINE_RE = re.compile(
    r"^[ \t]*"
    r"(?:" + _REGISTER_STEERING_DECL_QUALIFIER_RE + r"\s+)*"
    r"(?P<type>int|s32|u32|s16|u16)"
    r"(?:\s+" + _REGISTER_STEERING_DECL_QUALIFIER_RE + r")*"
    r"\s+"
    r"(?P<decls>[^;]+)"
    r"\s*;$"
)


def _register_steering_loop_blocks(body_text: str) -> tuple[_RegisterSteeringLoop, ...]:
    records = _text_line_records_with_newline(body_text)
    searchable = _blank_literals_and_comments(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    loops: list[_RegisterSteeringLoop] = []
    for idx, (start, _end, _end_with_newline, line) in enumerate(searchable_records):
        depth = depths[idx] if idx < len(depths) else 0
        if depth != 1:
            continue
        match = _REGISTER_STEERING_FOR_RE.match(line)
        if match is None:
            continue
        if _identifier_mentions(match.group("init"), match.group("counter")):
            continue
        brace_depth = depth
        block_end: int | None = None
        for next_idx in range(idx, len(searchable_records)):
            _s, end, _ewn, search_line = searchable_records[next_idx]
            brace_depth += search_line.count("{") - search_line.count("}")
            if next_idx > idx and brace_depth == depth:
                block_end = records[next_idx][1]
                break
        if block_end is None:
            continue
        loops.append(
            _RegisterSteeringLoop(
                idx=idx,
                start=records[idx][0],
                end=block_end,
                line=records[idx][3],
                counter=match.group("counter"),
                indent=match.group("indent"),
                depth=depth,
            )
        )
    return tuple(loops)


def _register_steering_counter_decl(
    decls: tuple[_RegisterSteeringDecl, ...],
    name: str,
) -> _RegisterSteeringDecl | None:
    matches = [
        decl
        for decl in decls
        if decl.name == name
        and decl.depth == 1
        and not decl.init
        and decl.type_name in {"int", "s32", "u32", "s16", "u16"}
    ]
    return matches[0] if len(matches) == 1 else None


def _register_steering_raw_decl_name_counts(
    body_text: str,
    *names: str,
) -> dict[str, int] | None:
    wanted = set(names)
    counts = {name: 0 for name in wanted}
    searchable = _blank_literals_and_comments(body_text)
    for _start, _end, line in _text_line_records(searchable):
        match = _REGISTER_STEERING_DECL_LINE_RE.match(line)
        if match is None:
            if any(
                _raw_identifier_spans(line, name)
                and re.search(
                    r"\b(?:auto|const|extern|register|static|volatile|int|s32|u32|s16|u16)\b",
                    line,
                )
                and line.strip().endswith(";")
                for name in wanted
            ):
                return None
            continue
        matched_names: set[str] = set()
        for declarator in match.group("decls").split(","):
            name_match = re.match(r"\s*\**\s*(?P<name>[A-Za-z_]\w*)\b", declarator)
            if name_match is None:
                continue
            name = name_match.group("name")
            if name in wanted:
                counts[name] += 1
                matched_names.add(name)
        if any(
            _raw_identifier_spans(line, name) and name not in matched_names
            for name in wanted
        ):
            return None
    return counts


def _register_steering_has_duplicate_or_nested_counter_decl(
    body_text: str,
    decls: tuple[_RegisterSteeringDecl, ...],
    *names: str,
) -> bool:
    wanted = set(names)
    raw_counts = _register_steering_raw_decl_name_counts(body_text, *names)
    if raw_counts is None:
        return True
    return any(
        sum(1 for decl in decls if decl.name == name) != 1
        or raw_counts.get(name, 0) != 1
        for name in wanted
    )


def _counter_address_take_rejects(searchable: str, name: str) -> bool:
    return re.search(
        r"&\s*(?:\(\s*)*" + re.escape(name) + r"\b",
        searchable,
    ) is not None


def _counter_identifier_region_rejects(searchable: str, raw: str, *names: str) -> bool:
    for name in names:
        if _counter_address_take_rejects(searchable, name):
            return True
        for start, _end in _identifier_mentions(searchable, name):
            if _identifier_is_member_name(searchable, start):
                return True
        if set(_raw_identifier_spans(raw, name)) != set(
            _identifier_mentions(searchable, name)
        ):
            return True
    return False


def _counter_region_rejects(searchable: str, raw: str, *names: str) -> bool:
    if "#" in searchable or re.search(
        r"\b(?:return|goto|switch|case|default|break|continue)\b",
        searchable,
    ):
        return True
    for _start, _end, line in _text_line_records(searchable):
        if _line_has_label(line) or _macro_like_statement(line):
            return True
    return _counter_identifier_region_rejects(searchable, raw, *names)


def _register_steering_for_dead_counter_later_loops(
    body_text: str,
) -> tuple[_RegisterSteeringDeadCounterLoop, ...]:
    return tuple(
        _RegisterSteeringDeadCounterLoop(
            idx=loop.idx,
            start=loop.start,
            end=loop.end,
            counter=loop.counter,
            kind="for",
            prelude_start=loop.start,
        )
        for loop in _register_steering_loop_blocks(body_text)
    )


def _register_steering_do_dead_counter_later_loops(
    body_text: str,
) -> tuple[_RegisterSteeringDeadCounterLoop, ...]:
    records = _text_line_records_with_newline(body_text)
    searchable = _blank_literals_and_comments(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    loops: list[_RegisterSteeringDeadCounterLoop] = []
    for idx, (start, _end, _end_with_newline, line) in enumerate(searchable_records):
        depth = depths[idx] if idx < len(depths) else 0
        if depth != 1 or _REGISTER_STEERING_DO_RE.match(line) is None:
            continue

        prelude_idx = idx - 1
        while prelude_idx >= 0 and not searchable_records[prelude_idx][3].strip():
            prelude_idx -= 1
        if prelude_idx < 0 or depths[prelude_idx] != depth:
            continue
        prelude_line = searchable_records[prelude_idx][3]
        prelude_match = _REGISTER_STEERING_COUNTER_ASSIGN_RE.match(prelude_line)
        if prelude_match is None:
            continue
        counter = prelude_match.group("counter")
        if _identifier_mentions(prelude_match.group("init"), counter):
            continue

        brace_depth = depth
        block_end: int | None = None
        close_line = ""
        for next_idx in range(idx, len(searchable_records)):
            _s, end, _ewn, search_line = searchable_records[next_idx]
            brace_depth += search_line.count("{") - search_line.count("}")
            if next_idx > idx and brace_depth == depth:
                block_end = records[next_idx][1]
                close_line = search_line
                break
        if block_end is None:
            continue
        if re.search(
            r"}\s*while\s*\([^)]*\b" + re.escape(counter) + r"\b[^)]*\)\s*;\s*$",
            close_line,
        ) is None:
            continue
        if not _identifier_mentions(searchable[records[prelude_idx][0]:block_end], counter):
            continue
        loops.append(
            _RegisterSteeringDeadCounterLoop(
                idx=idx,
                start=records[idx][0],
                end=block_end,
                counter=counter,
                kind="do",
                prelude_start=records[prelude_idx][0],
            )
        )
    return tuple(loops)


def _register_steering_dead_counter_later_loops(
    body_text: str,
) -> tuple[_RegisterSteeringDeadCounterLoop, ...]:
    loops = [
        *_register_steering_do_dead_counter_later_loops(body_text),
        *_register_steering_for_dead_counter_later_loops(body_text),
    ]
    return tuple(
        sorted(
            loops,
            key=lambda loop: (0 if loop.kind == "do" else 1, loop.start),
        )
    )


def _loop_counter_split_body_safe(searchable_loop: str, counter: str) -> bool:
    if "#" in searchable_loop or re.search(r"\b(?:break|continue|goto)\b", searchable_loop):
        return False
    if _line_has_label(searchable_loop):
        return False
    if re.search(r"&\s*" + re.escape(counter) + r"\b", searchable_loop):
        return False
    for start, _end in _identifier_mentions(searchable_loop, counter):
        if _identifier_is_member_name(searchable_loop, start):
            return False
    return True


def _replacement_spans_for_loop_counter(searchable_loop: str, counter: str):
    return tuple(_identifier_mentions(searchable_loop, counter))


def _raw_identifier_spans(text: str, name: str) -> tuple[tuple[int, int], ...]:
    return tuple(
        (match.start(), match.end())
        for match in re.finditer(r"\b" + re.escape(name) + r"\b", text)
    )


def _apply_ordered_text_edits(
    text: str,
    edits: list[tuple[int, int, str]],
) -> str | None:
    result = text
    cursor = len(text)
    for start, end, replacement in sorted(edits, reverse=True):
        if not (0 <= start <= end <= cursor):
            return None
        result = result[:start] + replacement + result[end:]
        cursor = start
    return result


def _iter_dead_top_level_loop_counter_reuse_anchors(
    body_text: str,
    decls: tuple[_RegisterSteeringDecl, ...],
) -> list[Anchor]:
    anchors: list[Anchor] = []
    searchable = _blank_literals_and_comments(body_text)
    earlier_loops = _register_steering_loop_blocks(body_text)
    later_loops = _register_steering_dead_counter_later_loops(body_text)
    for earlier in earlier_loops:
        old_decl = _register_steering_counter_decl(decls, earlier.counter)
        if old_decl is None:
            continue
        earlier_region = searchable[earlier.start:earlier.end]
        if _counter_region_rejects(
            earlier_region,
            body_text[earlier.start:earlier.end],
            earlier.counter,
        ):
            continue
        for later in later_loops:
            if later.start <= earlier.end or later.counter == earlier.counter:
                continue
            later_decl = _register_steering_counter_decl(decls, later.counter)
            if later_decl is None or later_decl.type_name != old_decl.type_name:
                continue
            if _register_steering_has_duplicate_or_nested_counter_decl(
                body_text,
                decls,
                earlier.counter,
                later.counter,
            ):
                continue
            if _counter_address_take_rejects(searchable, earlier.counter) or (
                _counter_address_take_rejects(searchable, later.counter)
            ):
                continue

            span_start = later_decl.start
            span_end = later.end
            if span_start >= span_end:
                continue
            span_text = body_text[span_start:span_end]
            if body_text.count(span_text) != 1:
                continue
            searchable_span = searchable[span_start:span_end]
            if _counter_identifier_region_rejects(
                searchable_span,
                span_text,
                earlier.counter,
                later.counter,
            ):
                continue

            selected_region = searchable[later.prelude_start:later.end]
            selected_raw = body_text[later.prelude_start:later.end]
            if _counter_region_rejects(
                selected_region,
                selected_raw,
                earlier.counter,
                later.counter,
            ):
                continue
            if _identifier_mentions(selected_region, earlier.counter):
                continue
            replacement_spans = _identifier_mentions(selected_region, later.counter)
            if not replacement_spans:
                continue

            between_earlier_and_later = searchable[earlier.end:later.prelude_start]
            if _counter_region_rejects(
                between_earlier_and_later,
                body_text[earlier.end:later.prelude_start],
                earlier.counter,
                later.counter,
            ):
                continue
            if _identifier_mentions(between_earlier_and_later, earlier.counter):
                continue

            before_later_region = searchable[later_decl.end_with_newline:later.prelude_start]
            if _identifier_mentions(before_later_region, later.counter):
                continue

            after_later = searchable[later.end:]
            if (
                _identifier_mentions(after_later, earlier.counter)
                or _identifier_mentions(after_later, later.counter)
            ):
                continue

            edits: list[tuple[int, int, str]] = [
                (
                    later_decl.start - span_start,
                    later_decl.end_with_newline - span_start,
                    "",
                )
            ]
            edits.extend(
                (
                    later.prelude_start + start - span_start,
                    later.prelude_start + end - span_start,
                    earlier.counter,
                )
                for start, end in replacement_spans
            )
            replacement_text = _apply_ordered_text_edits(span_text, edits)
            if replacement_text is None or replacement_text == span_text:
                continue
            anchors.append(
                Anchor(
                    mutator_key="steer_reuse_dead_top_level_loop_counter",
                    span=(span_start, span_end),
                    payload={
                        "span_text": span_text,
                        "replacement_text": replacement_text,
                        "strategy": f"reuse-dead-top-level-{later.kind}-counter",
                        "old_counter": earlier.counter,
                        "later_counter": later.counter,
                        "counter_type": old_decl.type_name,
                    },
                )
            )
    return anchors


def _iter_reused_loop_counter_split_anchors(
    body_text: str,
    decls: tuple[_RegisterSteeringDecl, ...],
) -> list[Anchor]:
    anchors: list[Anchor] = []
    searchable = _blank_literals_and_comments(body_text)
    loops = _register_steering_loop_blocks(body_text)
    decls_by_name: dict[str, _RegisterSteeringDecl] = {}
    for decl in decls:
        if decl.depth == 1 and not decl.init:
            decls_by_name.setdefault(decl.name, decl)
    for index, loop in enumerate(loops):
        previous = [candidate for candidate in loops[:index] if candidate.counter == loop.counter]
        if not previous:
            continue
        decl = decls_by_name.get(loop.counter)
        if decl is None or decl.type_name not in {"int", "s32", "u32", "s16", "u16"}:
            continue
        fresh = f"{loop.counter}_1"
        if _identifier_mentions(searchable, fresh):
            continue
        prev_end = previous[-1].end
        between = searchable[prev_end:loop.start]
        if _identifier_mentions(between, loop.counter):
            continue
        after = searchable[loop.end:]
        if _identifier_mentions(after, loop.counter):
            continue
        loop_text = body_text[loop.start:loop.end]
        searchable_loop = searchable[loop.start:loop.end]
        if not _loop_counter_split_body_safe(searchable_loop, loop.counter):
            continue
        replacement_spans = _replacement_spans_for_loop_counter(
            searchable_loop,
            loop.counter,
        )
        if not replacement_spans:
            continue
        if set(_raw_identifier_spans(loop_text, loop.counter)) != set(replacement_spans):
            continue
        replaced_loop = loop_text
        for start, end in reversed(replacement_spans):
            if loop_text[start:end] != loop.counter:
                continue
            replaced_loop = replaced_loop[:start] + fresh + replaced_loop[end:]
        decl_indent = re.match(r"\s*", decl.line).group(0)
        span_text = body_text[decl.start:loop.end]
        if body_text.count(span_text) != 1:
            continue
        replacement_text = (
            body_text[decl.start:decl.end_with_newline]
            + f"{decl_indent}{decl.type_name} {fresh};\n"
            + body_text[decl.end_with_newline:loop.start]
            + replaced_loop
        )
        anchors.append(
            Anchor(
                mutator_key="steer_split_reused_loop_counter",
                span=(decl.start, loop.end),
                payload={
                    "span_text": span_text,
                    "replacement_text": replacement_text,
                    "strategy": "split-reused-loop-counter",
                    "original_counter": loop.counter,
                    "fresh_counter": fresh,
                    "counter_type": decl.type_name,
                },
            )
        )
    return anchors


def _iter_byte_local_widen_anchors(body_text: str) -> list[Anchor]:
    anchors: list[Anchor] = []
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    for idx, (start, end, _end_with_newline, search_line) in enumerate(
        searchable_records
    ):
        if idx >= len(records):
            continue
        depth = depths[idx] if idx < len(depths) else 0
        if depth != 1:
            continue
        match = _REGISTER_STEERING_BYTE_DECL_RE.match(search_line)
        if match is None:
            continue
        name = match.group("name")
        from_type = match.group("from")
        raw_line = records[idx][3]
        span_text = body_text[start:end]
        if span_text != raw_line or body_text.count(span_text) != 1:
            continue
        if _counter_identifier_region_rejects(searchable, body_text, name):
            continue
        replacement_text = re.sub(
            r"\b" + re.escape(from_type) + r"\b",
            "int",
            span_text,
            count=1,
        )
        if replacement_text == span_text:
            continue
        anchors.append(
            Anchor(
                mutator_key="steer_widen_byte_local_type",
                span=(start, end),
                payload={
                    "span_text": span_text,
                    "replacement_text": replacement_text,
                    "strategy": "widen-byte-local-type",
                    "var": name,
                    "from": from_type,
                    "to": "int",
                },
            )
        )
    return anchors


def _split_top_level_product(rhs: str) -> tuple[str, str] | None:
    depth = 0
    star_indexes: list[int] = []
    for index, char in enumerate(rhs):
        if char == "(":
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth < 0:
                return None
            continue
        if char == "*" and depth == 0:
            star_indexes.append(index)
    if depth != 0 or len(star_indexes) != 1:
        return None
    left = rhs[: star_indexes[0]].strip()
    right = rhs[star_indexes[0] + 1 :].strip()
    if not left or not right:
        return None
    return left, right


def _register_steering_product_term(term: str) -> tuple[str, bool] | None:
    stripped = term.strip()
    if not stripped:
        return None
    if any(token in stripped for token in ("->", "++", "--", "||", "&&")):
        return None
    if re.search(r"[.\[\]&*?:,=]", stripped):
        return None
    bare = re.fullmatch(r"[A-Za-z_]\w*", stripped)
    if bare is not None:
        return stripped, False
    casted = re.fullmatch(
        r"\(\s*(?:float|f32|double|f64)\s*\)\s*(?P<name>[A-Za-z_]\w*)",
        stripped,
    )
    if casted is None:
        return None
    return casted.group("name"), True


def _register_steering_product_expr(
    rhs: str,
) -> tuple[str, tuple[str, str], tuple[str, ...]] | None:
    terms = _split_top_level_product(rhs)
    if terms is None:
        return None
    parsed_terms = tuple(_register_steering_product_term(term) for term in terms)
    if any(parsed is None for parsed in parsed_terms):
        return None
    names = tuple(parsed[0] for parsed in parsed_terms if parsed is not None)
    cast_operand_names = tuple(
        parsed[0] for parsed in parsed_terms if parsed is not None and parsed[1]
    )
    if len(names) != 2:
        return None
    return rhs.strip(), (names[0], names[1]), cast_operand_names


def _register_steering_fpr_parameter_names(header_text: str) -> set[str]:
    return {
        name
        for type_name, name in _parse_signature_params(header_text.strip())
        if type_name in _REGISTER_STEERING_FPR_TYPES
    }


def _register_steering_scalar_parameter_names(header_text: str) -> set[str]:
    return {
        name
        for type_name, name in _parse_signature_params(header_text.strip())
        if _is_scalar_type(type_name)
    }


def _register_steering_fpr_local_names(
    body_text: str,
    names: set[str],
) -> set[str]:
    decls = _register_steering_decl_records(body_text)
    if decls is None:
        decls = _register_steering_narrow_decl_records_for(body_text, names)
    if decls is None:
        return set()
    proven: set[str] = set()
    for name in names:
        matches = [
            decl for decl in decls
            if decl.name == name and decl.depth == 1 and not decl.init
        ]
        if len(matches) == 1 and matches[0].type_name in _REGISTER_STEERING_FPR_TYPES:
            proven.add(name)
    return proven


def _register_steering_safe_scalar_local_names(
    body_text: str,
    names: set[str],
) -> set[str]:
    decls = _register_steering_decl_records(body_text)
    if decls is None:
        decls = _register_steering_narrow_decl_records_for(body_text, names)
    if decls is None:
        return set()
    proven: set[str] = set()
    for name in names:
        matches = [
            decl for decl in decls
            if decl.name == name and decl.depth == 1 and _is_scalar_type(decl.type_name)
        ]
        if len(matches) == 1:
            proven.add(name)
    return proven


def _register_steering_safe_scalar_operand_names(
    body_text: str,
    function_header_text: str,
    names: set[str],
) -> set[str]:
    safe_names = _register_steering_safe_scalar_local_names(body_text, names)
    safe_names.update(
        _register_steering_scalar_parameter_names(function_header_text)
    )
    return safe_names


def _register_steering_product_has_fpr_operand_proof(
    body_text: str,
    function_header_text: str,
    operand_names: tuple[str, str],
    cast_operand_names: tuple[str, ...],
) -> bool:
    wanted = set(operand_names)
    safe_names = _register_steering_safe_scalar_operand_names(
        body_text,
        function_header_text,
        wanted,
    )
    if not wanted <= safe_names:
        return False
    if cast_operand_names:
        wanted_casts = set(cast_operand_names)
        return wanted_casts <= safe_names
    fpr_names = _register_steering_fpr_local_names(body_text, wanted)
    fpr_names.update(_register_steering_fpr_parameter_names(function_header_text))
    return any(name in fpr_names for name in operand_names)


def _preprocessor_depths_for_lines(
    records: list[tuple[int, int, int, str]],
) -> list[int]:
    depths: list[int] = []
    depth = 0
    for _start, _end, _end_with_newline, line in records:
        stripped = line.lstrip()
        if re.match(r"#\s*endif\b", stripped):
            depth = max(0, depth - 1)
            depths.append(depth)
            continue
        depths.append(depth)
        if re.match(r"#\s*if(?:def|ndef)?\b", stripped):
            depth += 1
    return depths


def _register_steering_narrow_decl_records_for(
    body_text: str,
    names: set[str],
) -> tuple[_RegisterSteeringDecl, ...] | None:
    blanked = _blank_literals_and_comments(body_text)
    depths = _line_depths_from_blanked_text(blanked)
    records = _text_line_records_with_newline(body_text)
    decls: list[_RegisterSteeringDecl] = []
    for idx, (start, end, end_with_newline, line) in enumerate(records):
        raw_match = _REGISTER_STEERING_DECL_RE.match(line)
        if raw_match is None or raw_match.group("var") not in names:
            continue
        match = _register_steering_decl_match(line)
        if match is None:
            return None
        type_name = _normalize_local_reuse_type(match.group("type").strip())
        decls.append(
            _RegisterSteeringDecl(
                idx=idx,
                start=start,
                end=end,
                end_with_newline=end_with_newline,
                line=line,
                type_name=type_name,
                name=match.group("var"),
                init=(match.group("init") or "").strip(),
                depth=depths[idx] if idx < len(depths) else 0,
                name_span=(start + match.start("var"), start + match.end("var")),
            )
        )
    return tuple(decls)


def _register_steering_recompute_decl_line_match(line: str):
    match = _REGISTER_STEERING_RECOMPUTE_DECL_LINE_RE.match(line)
    if match is None:
        return None
    head_match = re.match(r"\s*(?:[A-Za-z_]\w*\s+)*([A-Za-z_]\w*)", match.group("type"))
    if head_match is not None and head_match.group(1) in _REGISTER_STEERING_RECOMPUTE_NON_DECL_HEADS:
        return None
    return match


def _register_steering_recompute_normal_statement(line: str) -> bool:
    stripped = line.strip()
    if not stripped.endswith(";"):
        return True
    if re.match(r"[A-Za-z_]\w*\s*(?:[-+*/%&|^]?=|<<=|>>=)\s*.+;\s*$", stripped):
        return True
    call_match = re.match(r"(?P<callee>[A-Za-z_]\w*)\s*\([^;]*\)\s*;\s*$", stripped)
    if (
        call_match is not None
        and call_match.group("callee") not in _REGISTER_STEERING_RECOMPUTE_DECL_STARTERS
        and not _macro_like_statement(stripped)
    ):
        return True
    if re.match(r"(?:return|break|continue|goto)\b.*;\s*$", stripped):
        return True
    if re.match(r"(?:\+\+|--)?[A-Za-z_]\w*(?:\+\+|--)?\s*;\s*$", stripped):
        return True
    return False


def _register_steering_recompute_raw_decl_name_counts(
    body_text: str,
    *names: str,
) -> dict[str, int] | None:
    wanted = set(names)
    counts = {name: 0 for name in wanted}
    searchable = _blank_literals_and_comments(body_text)
    for _start, _end, line in _text_line_records(searchable):
        match = _register_steering_recompute_decl_line_match(line)
        if match is None:
            if (
                line.strip().endswith(";")
                and any(_raw_identifier_spans(line, name) for name in wanted)
                and not _register_steering_recompute_normal_statement(line)
            ):
                return None
            continue
        matched_names: set[str] = set()
        for declarator in match.group("decls").split(","):
            name_match = re.match(r"\s*\**\s*(?P<name>[A-Za-z_]\w*)\b", declarator)
            if name_match is None:
                continue
            name = name_match.group("name")
            if name in wanted:
                counts[name] += 1
                matched_names.add(name)
        if any(
            _raw_identifier_spans(line, name) and name not in matched_names
            for name in wanted
        ):
            return None
    return counts


def _register_steering_fpr_product_decls(
    body_text: str,
    primary: str,
    dependent: str,
) -> tuple[_RegisterSteeringDecl, _RegisterSteeringDecl] | None:
    wanted = {primary, dependent}
    raw_counts = _register_steering_recompute_raw_decl_name_counts(
        body_text,
        primary,
        dependent,
    )
    if raw_counts is None:
        return None
    decls = _register_steering_decl_records(body_text)
    if decls is None:
        decls = _register_steering_narrow_decl_records_for(body_text, wanted)
    if decls is None:
        return None
    found: dict[str, list[_RegisterSteeringDecl]] = {
        name: [decl for decl in decls if decl.name == name]
        for name in wanted
    }
    if any(len(records) != 1 for records in found.values()):
        return None
    if any(raw_counts.get(name, 0) != 1 for name in wanted):
        return None
    primary_decl = found[primary][0]
    dependent_decl = found[dependent][0]
    if primary_decl.depth != 1 or dependent_decl.depth != 1:
        return None
    if primary_decl.type_name not in _REGISTER_STEERING_FPR_TYPES:
        return None
    if dependent_decl.type_name not in _REGISTER_STEERING_FPR_TYPES:
        return None
    return primary_decl, dependent_decl


def _dependent_product_replacement(
    *,
    indent: str,
    dependent: str,
    product_expr: str,
    dependent_parts: _RegisterSteeringDependentProduct,
) -> str | None:
    return _dependent_source_replacement(
        indent=indent,
        dependent=dependent,
        source_expr=f"({product_expr})",
        dependent_parts=dependent_parts,
    )


def _dependent_source_replacement(
    *,
    indent: str,
    dependent: str,
    source_expr: str,
    dependent_parts: _RegisterSteeringDependentProduct,
) -> str | None:
    if dependent_parts.const_on_left:
        return (
            f"{indent}{dependent} = {dependent_parts.const_text} "
            f"{dependent_parts.op} {source_expr};"
        )
    return (
        f"{indent}{dependent} = {source_expr} "
        f"{dependent_parts.op} {dependent_parts.const_text};"
    )


def _dependent_expr_from_source(
    source_expr: str,
    dependent_parts: _RegisterSteeringDependentProduct,
) -> str:
    source = (
        source_expr
        if re.match(r"^[A-Za-z_]\w*$", source_expr.strip())
        else f"({source_expr})"
    )
    if dependent_parts.const_on_left:
        return (
            f"{dependent_parts.const_text} {dependent_parts.op} "
            f"{source}"
        )
    return f"{source} {dependent_parts.op} {dependent_parts.const_text}"


def _call_statement_uses_local(line: str, local: str) -> bool:
    stripped = line.strip()
    if not stripped.endswith(";") or "=" in stripped:
        return False
    if re.match(r"[A-Za-z_]\w*\s*\(", stripped) is None:
        return False
    return re.search(r"\b" + re.escape(local) + r"\b", stripped) is not None


def _replace_call_statement_local(line: str, local: str, replacement: str) -> str:
    return re.sub(
        r"\b" + re.escape(local) + r"\b",
        replacement,
        line,
        count=1,
    )


def _strip_wrapping_parens(text: str) -> str:
    stripped = text.strip()
    while stripped.startswith("(") and stripped.endswith(")"):
        balance = 0
        wraps = True
        for idx, char in enumerate(stripped):
            if char == "(":
                balance += 1
            elif char == ")":
                balance -= 1
                if balance == 0 and idx != len(stripped) - 1:
                    wraps = False
                    break
        if not wraps:
            break
        stripped = stripped[1:-1].strip()
    return stripped


def _canonical_product_expr(expr: str) -> str | None:
    product = _register_steering_product_expr(_strip_wrapping_parens(expr))
    if product is None:
        return None
    return re.sub(r"\s+", "", product[0])


def _dependent_product_parts(
    rhs: str,
    *,
    primary: str,
    product_expr: str,
) -> _RegisterSteeringDependentProduct | None:
    dependent_match = _REGISTER_STEERING_DEPENDENT_RE.match(rhs.strip())
    if dependent_match is not None:
        referenced_primary = (
            dependent_match.group("lhs") or dependent_match.group("lhs_right")
        )
        if referenced_primary == primary:
            if dependent_match.group("lhs") is not None:
                return _RegisterSteeringDependentProduct(
                    op=dependent_match.group("op"),
                    const_text=dependent_match.group("const"),
                )
            return _RegisterSteeringDependentProduct(
                op=dependent_match.group("op_left"),
                const_text=dependent_match.group("const_left"),
                const_on_left=True,
            )

    const_pattern = r"(?:\d+(?:\.\d*)?|\.\d+)(?:f)?"
    product_canonical = _canonical_product_expr(product_expr)
    if product_canonical is None:
        return None
    repeated_match = re.fullmatch(
        rf"(?P<expr>.+?)\s*(?P<op>[+-])\s*(?P<const>{const_pattern})",
        rhs.strip(),
    )
    if repeated_match is not None:
        repeated_canonical = _canonical_product_expr(repeated_match.group("expr"))
        if repeated_canonical == product_canonical:
            return _RegisterSteeringDependentProduct(
                op=repeated_match.group("op"),
                const_text=repeated_match.group("const"),
            )
    repeated_left_match = re.fullmatch(
        rf"(?P<const>{const_pattern})\s*(?P<op>[+-])\s*(?P<expr>.+)",
        rhs.strip(),
    )
    if repeated_left_match is not None:
        repeated_canonical = _canonical_product_expr(
            repeated_left_match.group("expr")
        )
        if repeated_canonical == product_canonical:
            return _RegisterSteeringDependentProduct(
                op=repeated_left_match.group("op"),
                const_text=repeated_left_match.group("const"),
                const_on_left=True,
            )
    return None


def _single_fpr_decl_for_name(
    body_text: str,
    name: str,
) -> _RegisterSteeringDecl | None:
    decls = _register_steering_decl_records(body_text)
    if decls is None:
        decls = _register_steering_narrow_decl_records_for(body_text, {name})
    if decls is None:
        return None
    matches = [
        decl for decl in decls
        if decl.name == name
        and decl.depth == 1
        and decl.type_name in _REGISTER_STEERING_FPR_TYPES
    ]
    return matches[0] if len(matches) == 1 else None


def _all_top_level_fpr_decls(
    body_text: str,
) -> tuple[_RegisterSteeringDecl, ...]:
    decls = _register_steering_decl_records(body_text)
    if decls is None:
        return ()
    return tuple(
        decl for decl in decls
        if decl.depth == 1 and decl.type_name in _REGISTER_STEERING_FPR_TYPES
    )


def _iter_fpr_product_assignments(
    body_text: str,
    function_header_text: str,
) -> tuple[_RegisterSteeringFprProduct, ...]:
    if re.search(r"(?m)^[ \t]*#", body_text):
        return ()
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    preprocessor_depths = _preprocessor_depths_for_lines(searchable_records)
    products: list[_RegisterSteeringFprProduct] = []
    for idx, (start, end, _end_with_newline, line) in enumerate(searchable_records):
        if idx >= len(records):
            continue
        if (depths[idx] if idx < len(depths) else 0) != 1:
            continue
        if preprocessor_depths[idx] != 0 or records[idx][3] != line:
            continue
        match = _REGISTER_STEERING_ASSIGN_RE.match(line)
        if match is None:
            continue
        lhs = match.group("lhs")
        product = _register_steering_product_expr(match.group("rhs"))
        if product is None:
            continue
        product_expr, operand_names, cast_operand_names = product
        if (
            lhs in operand_names
            or _node_set_split_synthetic_name(lhs)
            or _generated_fpr_product_temp_name(lhs)
            or any(_generated_fpr_product_temp_name(name) for name in operand_names)
        ):
            continue
        if _single_fpr_decl_for_name(body_text, lhs) is None:
            continue
        if not _register_steering_product_has_fpr_operand_proof(
            body_text,
            function_header_text,
            operand_names,
            cast_operand_names,
        ):
            continue
        if _counter_address_take_rejects(searchable, lhs):
            continue
        if body_text.count(records[idx][3]) != 1:
            continue
        products.append(
            _RegisterSteeringFprProduct(
                idx=idx,
                start=start,
                end=end,
                line=records[idx][3],
                indent=match.group("indent"),
                lhs=lhs,
                product_expr=product_expr,
                operand_names=operand_names,
                cast_operand_names=cast_operand_names,
            )
        )
    return tuple(products)


def _case_c_simple_call_expr(expr: str) -> str | None:
    stripped = expr.strip()
    if any(token in stripped for token in ("++", "--", "=", "?", ":", ";")):
        return None
    if re.fullmatch(r"[A-Za-z_]\w*\s*\([^(){}]*\)", stripped) is None:
        return None
    return stripped


def _case_c_simple_local_expr(expr: str) -> str | None:
    stripped = expr.strip()
    if re.fullmatch(r"[A-Za-z_]\w*", stripped) is None:
        return None
    return stripped


def _split_top_level_subtraction(rhs: str) -> tuple[str, str] | None:
    depth = 0
    minus_indexes: list[int] = []
    for index, char in enumerate(rhs):
        if char == "(":
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth < 0:
                return None
            continue
        if char == "-" and depth == 0:
            if index > 0 and rhs[index - 1] == ">":
                continue
            minus_indexes.append(index)
    if depth != 0 or len(minus_indexes) != 1:
        return None
    left = rhs[: minus_indexes[0]].strip()
    right = rhs[minus_indexes[0] + 1 :].strip()
    if not left or not right:
        return None
    return left, right


def _case_c_combined_setup_rhs(rhs: str) -> tuple[str, str] | None:
    parts = _split_top_level_subtraction(rhs)
    if parts is None:
        return None
    call_expr = _case_c_simple_call_expr(parts[0])
    rhs_local = _case_c_simple_local_expr(parts[1])
    if call_expr is None or rhs_local is None:
        return None
    return call_expr, rhs_local


def _iter_fpr_case_c_setups(
    body_text: str,
) -> tuple[_RegisterSteeringCaseCFprSetup, ...]:
    if re.search(r"(?m)^[ \t]*#", body_text):
        return ()
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    preprocessor_depths = _preprocessor_depths_for_lines(searchable_records)
    setups: list[_RegisterSteeringCaseCFprSetup] = []

    for idx, (start, end, _end_with_newline, line) in enumerate(searchable_records):
        if idx >= len(records):
            continue
        if (depths[idx] if idx < len(depths) else 0) != 1:
            continue
        if preprocessor_depths[idx] != 0 or records[idx][3] != line:
            continue
        assign = _REGISTER_STEERING_ASSIGN_RE.match(line)
        if assign is None:
            continue
        indent = assign.group("indent")
        target = assign.group("lhs")
        call_expr: str | None = None
        rhs_local: str | None = None
        setup_end = end
        split_setup_text: str | None = None

        combined = _case_c_combined_setup_rhs(assign.group("rhs"))
        if combined is not None:
            call_expr, rhs_local = combined
            split_setup_text = (
                f"{indent}{target} = {call_expr};\n"
                f"{indent}{target} -= {rhs_local};"
            )
        else:
            call_expr = _case_c_simple_call_expr(assign.group("rhs"))
            if call_expr is None or idx + 1 >= len(searchable_records):
                continue
            next_start, next_end, _next_ewn, next_line = searchable_records[idx + 1]
            if next_start != records[idx + 1][0]:
                continue
            if (depths[idx + 1] if idx + 1 < len(depths) else 0) != 1:
                continue
            if preprocessor_depths[idx + 1] != 0 or records[idx + 1][3] != next_line:
                continue
            split_assign = _REGISTER_STEERING_SUB_ASSIGN_RE.match(next_line)
            if split_assign is None:
                continue
            if (
                split_assign.group("indent") != indent
                or split_assign.group("lhs") != target
            ):
                continue
            rhs_local = _case_c_simple_local_expr(split_assign.group("rhs"))
            if rhs_local is None:
                continue
            setup_end = next_end
            split_setup_text = body_text[start:setup_end]

        if rhs_local == target:
            continue
        if (
            _node_set_split_synthetic_name(target)
            or _node_set_split_synthetic_name(rhs_local)
            or _generated_fpr_product_temp_name(target)
            or _generated_fpr_product_temp_name(rhs_local)
        ):
            continue
        target_decl = _single_fpr_decl_for_name(body_text, target)
        rhs_decl = _single_fpr_decl_for_name(body_text, rhs_local)
        if target_decl is None or rhs_decl is None:
            continue
        if target_decl.end_with_newline > start or rhs_decl.end_with_newline > start:
            continue
        if _counter_identifier_region_rejects(searchable, body_text, target, rhs_local):
            continue
        setups.append(
            _RegisterSteeringCaseCFprSetup(
                idx=idx,
                start=start,
                end=setup_end,
                indent=indent,
                target=target,
                target_type=target_decl.type_name,
                call_expr=call_expr,
                rhs_local=rhs_local,
                split_setup_text=split_setup_text,
            )
        )
    return tuple(setups)


def _replace_case_c_product_operand(
    product_expr: str,
    target: str,
    replacement: str,
) -> str | None:
    rewritten = re.sub(
        r"\b" + re.escape(target) + r"\b",
        replacement,
        product_expr,
        count=1,
    )
    return rewritten if rewritten != product_expr else None


def _case_c_identifier_names(text: str) -> set[str]:
    return {
        match.group(0)
        for match in re.finditer(r"\b[A-Za-z_]\w*\b", text)
    }


def _case_c_movable_assignment_block(
    *,
    body_text: str,
    function_header_text: str,
    block_text: str,
    forbidden_names: set[str],
) -> tuple[str, tuple[str, ...]] | None:
    if not block_text.strip():
        return None
    if re.search(r"(?m)^[ \t]*#", block_text):
        return None
    decls = _register_steering_decl_records(body_text)
    if decls is None:
        return None
    local_names = {
        decl.name for decl in decls
        if decl.depth == 1 and _is_scalar_type(decl.type_name)
    }
    allowed_names = (
        local_names
        | _register_steering_scalar_parameter_names(function_header_text)
        | _register_steering_fpr_parameter_names(function_header_text)
        | _REGISTER_STEERING_RECOMPUTE_DECL_STARTERS
    )
    allowed_names |= {"f32", "f64", "float", "double"}
    searchable = _blank_literals_and_comments(block_text)
    records = _text_line_records_with_newline(block_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    moved: list[str] = []
    for idx, (start, _end, _end_with_newline, search_line) in enumerate(
        searchable_records
    ):
        if idx >= len(records):
            return None
        line = records[idx][3]
        if not line.strip():
            continue
        if (
            line != search_line
            or (depths[idx] if idx < len(depths) else 0) != 0
            or _line_has_label(line)
            or _macro_like_statement(line)
        ):
            return None
        stripped = search_line.strip()
        head = stripped.split(None, 1)[0] if stripped else ""
        if head in _REGISTER_STEERING_RECOMPUTE_NON_DECL_HEADS:
            return None
        assign = _REGISTER_STEERING_ASSIGN_RE.match(search_line)
        if assign is None:
            return None
        lhs = assign.group("lhs")
        rhs = assign.group("rhs")
        if lhs in forbidden_names or lhs not in local_names:
            return None
        if (
            "volatile" in search_line
            or any(token in rhs for token in ("->", ".", "[", "]", "&", "++", "--", "?", ":", ","))
            or re.search(r"(?<![=!<>])=(?!=)", rhs)
            or re.search(r"\b[A-Za-z_]\w*\s*\(", rhs)
        ):
            return None
        identifiers = _case_c_identifier_names(rhs)
        if identifiers & forbidden_names:
            return None
        if not identifiers <= allowed_names:
            return None
        moved.append(lhs)
    if not moved:
        return None
    movable_body = block_text[1:] if block_text.startswith("\n") else block_text
    if not movable_body.endswith("\n"):
        movable_body += "\n"
    return movable_body, tuple(moved)


def _iter_fpr_case_c_temp_order_anchors(
    body_text: str,
    function_header_text: str = "",
) -> list[Anchor]:
    setups = _iter_fpr_case_c_setups(body_text)
    if not setups:
        return []
    products = _iter_fpr_product_assignments(body_text, function_header_text)
    if not products:
        return []
    dependent_cases = _iter_fpr_dependent_product_cases(
        body_text,
        function_header_text,
    )
    searchable = _blank_literals_and_comments(body_text)
    anchors: list[Anchor] = []

    for setup in setups:
        for product in products:
            if product.start <= setup.end:
                continue
            if setup.target not in product.operand_names:
                continue
            if setup.indent != product.indent:
                continue
            between = body_text[setup.end:product.start]
            between_searchable = searchable[setup.end:product.start]
            if _region_assigns_any(between_searchable, (setup.target,)):
                continue
            insert_after = _insert_after_top_level_fpr_decls(body_text, setup.start)
            if insert_after is None:
                continue
            span_text = body_text[insert_after:product.end]
            if body_text.count(span_text) != 1:
                continue
            prefix = body_text[insert_after:setup.start]
            setup_text = body_text[setup.start:setup.end]

            def append_anchor(
                *,
                strategy: str,
                temp_local: str,
                pre_between_text: str,
                replacement_product_line: str,
                post_between_text: str = "",
            ) -> None:
                replacement_text = (
                    f"{setup.indent}{setup.target_type} {temp_local};\n"
                    f"{prefix}"
                    f"{pre_between_text}"
                    f"{between}"
                    f"{post_between_text}"
                    f"{replacement_product_line}"
                )
                if replacement_text == span_text:
                    return
                anchors.append(
                    Anchor(
                        mutator_key="steer_fpr_case_c_temp_order",
                        span=(insert_after, product.end),
                        payload={
                            "span_text": span_text,
                            "replacement_text": replacement_text,
                            "strategy": strategy,
                            "target_local": setup.target,
                            "rhs_local": setup.rhs_local,
                            "product_local": product.lhs,
                            "product_expr": product.product_expr,
                            "call_expr": setup.call_expr,
                            "temp_local": temp_local,
                            "source_type": setup.target_type,
                        },
                    )
                )

            def append_cast_owner_anchors() -> None:
                for cast_operand in product.cast_operand_names:
                    if cast_operand == setup.target:
                        continue
                    if _region_assigns_any(between_searchable, (cast_operand,)):
                        continue
                    cast = _cast_term_for_operand(product.product_expr, cast_operand)
                    if cast is None:
                        continue
                    cast_text, cast_type = cast
                    cast_temp = _fresh_register_steering_name(
                        searchable,
                        f"{cast_operand}_cast_owner",
                    )
                    if cast_temp is None:
                        continue
                    replacement_product_expr = product.product_expr.replace(
                        cast_text,
                        cast_temp,
                        1,
                    )
                    if replacement_product_expr == product.product_expr:
                        continue
                    replacement_product_line = (
                        f"{product.indent}{product.lhs} = "
                        f"{replacement_product_expr};"
                    )
                    common_payload: dict[str, Any] = {
                        "span_text": span_text,
                        "target_local": setup.target,
                        "rhs_local": setup.rhs_local,
                        "product_local": product.lhs,
                        "product_expr": product.product_expr,
                        "call_expr": setup.call_expr,
                        "cast_operand": cast_operand,
                        "cast_text": cast_text,
                        "temp_local": cast_temp,
                        "source_type": cast_type,
                    }

                    before_replacement = (
                        f"{product.indent}{cast_type} {cast_temp};\n"
                        f"{prefix}"
                        f"{setup.indent}{cast_temp} = {cast_text};\n"
                        f"{setup_text}"
                        f"{between}"
                        f"{replacement_product_line}"
                    )
                    if before_replacement != span_text:
                        anchors.append(
                            Anchor(
                                mutator_key="steer_fpr_case_c_temp_order",
                                span=(insert_after, product.end),
                                payload={
                                    **common_payload,
                                    "replacement_text": before_replacement,
                                    "strategy": (
                                        "fpr-case-c-cast-owner-before-setup"
                                    ),
                                },
                            )
                        )

                    after_replacement = (
                        f"{product.indent}{cast_type} {cast_temp};\n"
                        f"{prefix}"
                        f"{setup_text}\n"
                        f"{setup.indent}{cast_temp} = {cast_text};"
                        f"{between}"
                        f"{replacement_product_line}"
                    )
                    if after_replacement != span_text:
                        anchors.append(
                            Anchor(
                                mutator_key="steer_fpr_case_c_temp_order",
                                span=(insert_after, product.end),
                                payload={
                                    **common_payload,
                                    "replacement_text": after_replacement,
                                    "strategy": (
                                        "fpr-case-c-cast-owner-after-setup"
                                    ),
                                },
                            )
                        )

                    dependent_case = next(
                        (
                            case for case in dependent_cases
                            if case.start == product.start
                            and case.primary == product.lhs
                            and case.indent == product.indent
                        ),
                        None,
                    )
                    if dependent_case is None:
                        continue
                    product_decl_type = _fpr_product_decl_type(body_text, product)
                    if product_decl_type is None:
                        continue
                    occupied = f"{searchable}\n{cast_temp}\n"
                    owner_temp = _fresh_register_steering_name(
                        occupied,
                        f"{product.lhs}_owner",
                    )
                    if owner_temp is None:
                        continue
                    dependent_line = _dependent_source_replacement(
                        indent=dependent_case.indent,
                        dependent=dependent_case.dependent,
                        source_expr=owner_temp,
                        dependent_parts=dependent_case.dependent_parts,
                    )
                    if dependent_line is None:
                        continue
                    dependent_span_text = body_text[
                        insert_after:dependent_case.next_end
                    ]
                    if body_text.count(dependent_span_text) != 1:
                        continue
                    dependent_replacement = (
                        f"{product.indent}{cast_type} {cast_temp};\n"
                        f"{product.indent}{product_decl_type} {owner_temp};\n"
                        f"{prefix}"
                        f"{setup.indent}{cast_temp} = {cast_text};\n"
                        f"{setup_text}"
                        f"{between}"
                        f"{replacement_product_line}\n"
                        f"{product.indent}{owner_temp} = {product.lhs};\n"
                        f"{dependent_line}"
                    )
                    if dependent_replacement == dependent_span_text:
                        continue
                    payload = {
                        **common_payload,
                        "span_text": dependent_span_text,
                        "replacement_text": dependent_replacement,
                        "strategy": "fpr-case-c-cast-plus-dependent-owner",
                        "dependent_local": dependent_case.dependent,
                        "owner_temp_local": owner_temp,
                    }
                    anchors.append(
                        Anchor(
                            mutator_key="steer_fpr_case_c_temp_order",
                            span=(insert_after, dependent_case.next_end),
                            payload=payload,
                        )
                    )

            def append_statement_motion_anchors() -> None:
                dependent_case = next(
                    (
                        case for case in dependent_cases
                        if case.start == product.start
                        and case.primary == product.lhs
                        and case.indent == product.indent
                    ),
                    None,
                )
                forbidden_names = {
                    setup.target,
                    setup.rhs_local,
                    product.lhs,
                }
                if dependent_case is not None:
                    forbidden_names.add(dependent_case.dependent)
                movable = _case_c_movable_assignment_block(
                    body_text=body_text,
                    function_header_text=function_header_text,
                    block_text=between,
                    forbidden_names=forbidden_names,
                )
                if movable is None:
                    return
                movable_body, moved_locals = movable
                setup_block = f"{setup_text}\n"
                before_replacement = (
                    f"{prefix}"
                    f"{movable_body}"
                    f"{setup_block}"
                    f"{product.line}"
                )
                if before_replacement != span_text:
                    anchors.append(
                        Anchor(
                            mutator_key="steer_fpr_case_c_temp_order",
                            span=(insert_after, product.end),
                            payload={
                                "span_text": span_text,
                                "replacement_text": before_replacement,
                                "strategy": (
                                    "fpr-case-c-upstream-block-before-setup"
                                ),
                                "target_local": setup.target,
                                "rhs_local": setup.rhs_local,
                                "product_local": product.lhs,
                                "product_expr": product.product_expr,
                                "call_expr": setup.call_expr,
                                "moved_locals": moved_locals,
                            },
                        )
                    )
                if dependent_case is None:
                    return
                if set(moved_locals) & set(product.operand_names):
                    return
                dependent_span_text = body_text[
                    insert_after:dependent_case.next_end
                ]
                if body_text.count(dependent_span_text) != 1:
                    return
                dependent_line = body_text[product.end + 1:dependent_case.next_end]
                if not dependent_line.strip():
                    return
                after_replacement = (
                    f"{prefix}"
                    f"{setup_block}"
                    f"{product.line}\n"
                    f"{dependent_line}\n"
                    f"{movable_body.rstrip(chr(10))}"
                )
                if after_replacement == dependent_span_text:
                    return
                anchors.append(
                    Anchor(
                        mutator_key="steer_fpr_case_c_temp_order",
                        span=(insert_after, dependent_case.next_end),
                        payload={
                            "span_text": dependent_span_text,
                            "replacement_text": after_replacement,
                            "strategy": (
                                "fpr-case-c-upstream-block-after-dependent"
                            ),
                            "target_local": setup.target,
                            "rhs_local": setup.rhs_local,
                            "product_local": product.lhs,
                            "dependent_local": dependent_case.dependent,
                            "product_expr": product.product_expr,
                            "call_expr": setup.call_expr,
                            "moved_locals": moved_locals,
                        },
                    )
                )

            left_temp = _fresh_register_steering_name(
                searchable,
                f"{setup.target}_left",
            )
            if left_temp is not None:
                append_anchor(
                    strategy="fpr-case-c-left-operand-temp",
                    temp_local=left_temp,
                    pre_between_text=(
                        f"{setup.indent}{left_temp} = {setup.call_expr};\n"
                        f"{setup.indent}{setup.target} = "
                        f"{left_temp} - {setup.rhs_local};"
                    ),
                    replacement_product_line=product.line,
                )

            rhs_temp = _fresh_register_steering_name(
                searchable,
                f"{setup.target}_rhs",
            )
            if rhs_temp is not None:
                append_anchor(
                    strategy="fpr-case-c-rhs-owner-temp",
                    temp_local=rhs_temp,
                    pre_between_text=(
                        f"{setup.indent}{rhs_temp} = "
                        f"{setup.call_expr} - {setup.rhs_local};\n"
                        f"{setup.indent}{setup.target} = {rhs_temp};"
                    ),
                    replacement_product_line=product.line,
                )

            owner_temp = _fresh_register_steering_name(
                searchable,
                f"{setup.target}_owner",
            )
            if owner_temp is None:
                break
            replacement_product_expr = _replace_case_c_product_operand(
                product.product_expr,
                setup.target,
                owner_temp,
            )
            if replacement_product_expr is None:
                break
            append_anchor(
                strategy="fpr-case-c-product-owner-temp",
                temp_local=owner_temp,
                pre_between_text=f"{setup.split_setup_text}",
                post_between_text=(
                    f"{setup.indent}{owner_temp} = {setup.target};\n"
                ),
                replacement_product_line=(
                    f"{product.indent}{product.lhs} = {replacement_product_expr};"
                ),
            )
            append_statement_motion_anchors()
            append_cast_owner_anchors()
            break
    return anchors


def _region_assigns_any(searchable: str, names: tuple[str, ...]) -> bool:
    return any(
        re.search(
            r"(?:\b" + re.escape(name) + r"\b\s*(?:[-+*/%&|^]?=|<<=|>>=|\+\+|--)"
            r"|(?:\+\+|--)\s*\b" + re.escape(name) + r"\b)",
            searchable,
        )
        for name in names
    )


def _fresh_register_steering_name(searchable: str, stem: str) -> str | None:
    base = re.sub(r"\W+", "_", stem).strip("_") or "tmp"
    for candidate in (f"{base}_fpr", *(f"{base}_fpr_{idx}" for idx in range(2, 8))):
        if not _identifier_mentions(searchable, candidate):
            return candidate
    return None


def _cast_term_for_operand(product_expr: str, operand: str) -> tuple[str, str] | None:
    pattern = re.compile(
        r"(?P<text>\(\s*(?P<type>float|f32|double|f64)\s*\)\s*"
        + re.escape(operand)
        + r"\b)"
    )
    match = pattern.search(product_expr)
    if match is None:
        return None
    cast_type = match.group("type")
    return match.group("text"), ("f32" if cast_type == "float" else cast_type)


def _iter_fpr_product_order_anchors(
    body_text: str,
    products: tuple[_RegisterSteeringFprProduct, ...],
) -> list[Anchor]:
    searchable = _blank_literals_and_comments(body_text)
    anchors: list[Anchor] = []
    for index, first in enumerate(products):
        for second in products[index + 1:]:
            if second.indent != first.indent or second.start <= first.end:
                continue
            between = searchable[first.end:second.start]
            if _identifier_mentions(between, second.lhs):
                continue
            if _region_assigns_any(between, second.operand_names):
                continue
            span_text = body_text[first.start:second.end]
            if body_text.count(span_text) != 1:
                continue
            prefix = body_text[first.start:second.start].rstrip("\n")
            replacement_text = f"{second.line}\n{prefix}"
            if replacement_text == span_text:
                continue
            anchors.append(
                Anchor(
                    mutator_key="steer_fpr_product_assignment_order",
                    span=(first.start, second.end),
                    payload={
                        "span_text": span_text,
                        "replacement_text": replacement_text,
                        "strategy": "fpr-product-assignment-order",
                        "first_product_local": first.lhs,
                        "moved_product_local": second.lhs,
                    },
                )
            )
            break
    return anchors


def _iter_fpr_product_cast_split_anchors(
    body_text: str,
    products: tuple[_RegisterSteeringFprProduct, ...],
) -> list[Anchor]:
    searchable = _blank_literals_and_comments(body_text)
    fpr_decls = _all_top_level_fpr_decls(body_text)
    anchors: list[Anchor] = []
    for product in products:
        if not product.cast_operand_names:
            continue
        decl_candidates = [
            decl for decl in fpr_decls
            if decl.end_with_newline <= product.start
        ]
        if not decl_candidates:
            continue
        insert_after = max(decl.end_with_newline for decl in decl_candidates)
        for operand in product.cast_operand_names:
            cast = _cast_term_for_operand(product.product_expr, operand)
            if cast is None:
                continue
            cast_text, cast_type = cast
            temp_name = _fresh_register_steering_name(searchable, operand)
            if temp_name is None:
                continue
            replacement_product = product.product_expr.replace(cast_text, temp_name, 1)
            span_text = body_text[insert_after:product.end]
            if body_text.count(span_text) != 1:
                continue
            prefix = body_text[insert_after:product.start]
            replacement_text = (
                f"{product.indent}{cast_type} {temp_name};\n"
                f"{prefix}"
                f"{product.indent}{temp_name} = {cast_text};\n"
                f"{product.indent}{product.lhs} = {replacement_product};"
            )
            anchors.append(
                Anchor(
                    mutator_key="steer_fpr_product_cast_temp_split",
                    span=(insert_after, product.end),
                    payload={
                        "span_text": span_text,
                        "replacement_text": replacement_text,
                        "strategy": "fpr-product-cast-temp-split",
                        "product_local": product.lhs,
                        "cast_operand": operand,
                        "temp_local": temp_name,
                        "product_expr": product.product_expr,
                    },
                )
            )
            break
    return anchors


def _iter_fpr_product_argument_duplicate_anchors(
    body_text: str,
    products: tuple[_RegisterSteeringFprProduct, ...],
) -> list[Anchor]:
    records = _text_line_records_with_newline(body_text)
    searchable = _blank_literals_and_comments(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    anchors: list[Anchor] = []
    for product in products:
        for idx, (start, end, _end_with_newline, search_line) in enumerate(searchable_records):
            if start <= product.end or idx >= len(records):
                continue
            if (depths[idx] if idx < len(depths) else 0) != 1:
                continue
            line = records[idx][3]
            stripped = search_line.strip()
            if not re.match(r"[A-Za-z_]\w*\s*\(.*\)\s*;\s*$", stripped):
                continue
            if not _identifier_mentions(search_line, product.lhs):
                continue
            if body_text.count(line) != 1:
                continue
            replacement_line = re.sub(
                r"\b" + re.escape(product.lhs) + r"\b",
                product.product_expr,
                line,
                count=1,
            )
            if replacement_line == line:
                continue
            anchors.append(
                Anchor(
                    mutator_key="steer_fpr_product_argument_duplicate",
                    span=(start, end),
                    payload={
                        "span_text": line,
                        "replacement_text": replacement_line,
                        "strategy": "fpr-product-argument-duplicate",
                        "product_local": product.lhs,
                        "product_expr": product.product_expr,
                    },
                )
            )
            break
    return anchors


def _fpr_product_decl_type(
    body_text: str,
    product: _RegisterSteeringFprProduct,
) -> str | None:
    decl = _single_fpr_decl_for_name(body_text, product.lhs)
    return decl.type_name if decl is not None else None


def _fpr_product_temp_name(
    searchable: str,
    product: _RegisterSteeringFprProduct,
) -> str | None:
    return _fresh_register_steering_name(searchable, f"{product.lhs}_product")


def _fpr_product_reuse_temp_name(searchable: str, primary: str) -> str | None:
    return _fresh_register_steering_name(searchable, f"{primary}_product_reuse")


def _fpr_lifetime_temp_name(searchable: str, primary: str) -> str | None:
    return _fresh_register_steering_name(searchable, f"{primary}_lifetime")


def _insert_after_top_level_fpr_decls(
    body_text: str,
    before_offset: int,
) -> int | None:
    decl_candidates = [
        decl for decl in _all_top_level_fpr_decls(body_text)
        if decl.end_with_newline <= before_offset
    ]
    if not decl_candidates:
        return None
    return max(decl.end_with_newline for decl in decl_candidates)


_HSD_JOBJ_REQ_ANIM_ALL_CALL_RE = re.compile(
    r"^(?P<indent>[ \t]*)"
    r"(?P<callee>HSD_JObjReqAnimAll)"
    r"\s*\((?P<args>.*)\)\s*;\s*$"
)

_HSD_JOBJ_SET_TRANSLATE_Y_CALL_RE = re.compile(
    r"^(?P<indent>[ \t]*)"
    r"HSD_JObjSetTranslateY"
    r"\s*\((?P<args>.*)\)\s*;\s*$"
)


def _normalized_fpr_cast_type(type_text: str) -> str:
    return {"float": "f32", "double": "f64"}.get(type_text, type_text)


def _simple_fpr_cast_expr(expr: str) -> tuple[str, str, str] | None:
    stripped = expr.strip()
    if not stripped or any(token in stripped for token in ("++", "--", "=", "?", ":", ";", ",")):
        return None
    match = re.fullmatch(
        r"\(\s*(?P<type>float|f32|double|f64)\s*\)\s*"
        r"(?P<name>[A-Za-z_]\w*)",
        stripped,
    )
    if match is None:
        return None
    operand = match.group("name")
    if _node_set_split_synthetic_name(operand) or _generated_fpr_product_temp_name(operand):
        return None
    return stripped, _normalized_fpr_cast_type(match.group("type")), operand


def _previous_nonempty_line_index(
    records: list[tuple[int, int, int, str]],
    idx: int,
) -> int | None:
    for candidate in range(idx - 1, -1, -1):
        if records[candidate][3].strip():
            return candidate
    return None


def _call_arg_operand_is_safe(
    body_text: str,
    function_header_text: str,
    operand: str,
) -> bool:
    safe = _register_steering_safe_scalar_operand_names(
        body_text,
        function_header_text,
        {operand},
    )
    return operand in safe


def _fpr_callarg_scan_barrier(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if "{" in line or "}" in line or line.lstrip().startswith("#"):
        return True
    if _line_has_label(line) or _macro_like_statement(line):
        return True
    return re.search(
        r"\b(?:if|for|while|do|switch|goto|case|default|break|continue|return)\b",
        stripped,
    ) is not None


def _find_dominating_fpr_callarg_assignment(
    body_text: str,
    function_header_text: str,
    *,
    arg_text: str,
    call_idx: int,
    call_start: int,
    call_depth: int,
    records: list[tuple[int, int, int, str]],
    searchable: str,
    searchable_records: list[tuple[int, int, int, str]],
    depths: list[int],
    preprocessor_depths: list[int],
) -> tuple[int, int, str, str, str, str] | None:
    for candidate_idx in range(call_idx - 1, -1, -1):
        if candidate_idx >= len(records):
            continue
        start, end, _end_with_newline, search_line = searchable_records[candidate_idx]
        line = records[candidate_idx][3]
        if not search_line.strip():
            continue
        if preprocessor_depths[candidate_idx] != 0:
            return None
        if (depths[candidate_idx] if candidate_idx < len(depths) else 0) != call_depth:
            return None
        if line != search_line:
            return None
        if _fpr_callarg_scan_barrier(search_line):
            return None
        assign = _REGISTER_STEERING_ASSIGN_RE.match(search_line)
        if assign is None:
            continue
        if assign.group("lhs") != arg_text:
            continue
        cast = _simple_fpr_cast_expr(assign.group("rhs"))
        if cast is None:
            return None
        cast_expr, cast_type, operand = cast
        if not _call_arg_operand_is_safe(body_text, function_header_text, operand):
            return None
        between = searchable[end:call_start]
        if _region_assigns_any(between, (arg_text, operand)):
            return None
        return start, end, line, cast_expr, cast_type, operand
    return None


def _iter_hsd_jobj_req_anim_all_call_args(
    body_text: str,
    function_header_text: str = "",
) -> tuple[_RegisterSteeringHsdReqAnimCallArg, ...]:
    if re.search(r"(?m)^[ \t]*#", body_text):
        return ()
    records = _text_line_records_with_newline(body_text)
    searchable = _blank_literals_and_comments(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    preprocessor_depths = _preprocessor_depths_for_lines(searchable_records)
    calls: list[_RegisterSteeringHsdReqAnimCallArg] = []

    for idx, (start, end, _end_with_newline, search_line) in enumerate(searchable_records):
        if idx >= len(records):
            continue
        if preprocessor_depths[idx] != 0 or records[idx][3] != search_line:
            continue
        depth = depths[idx] if idx < len(depths) else 0
        if depth < 1 or _line_has_label(search_line) or _macro_like_statement(search_line):
            continue
        match = _HSD_JOBJ_REQ_ANIM_ALL_CALL_RE.match(search_line)
        if match is None:
            continue
        args = _split_top_level_csv(match.group("args"))
        if args is None or len(args) < 2:
            continue
        arg_text = args[1]
        line = records[idx][3]
        if body_text.count(line) != 1:
            continue

        inline_cast = _simple_fpr_cast_expr(arg_text)
        if inline_cast is not None:
            cast_expr, cast_type, operand = inline_cast
            if not _call_arg_operand_is_safe(body_text, function_header_text, operand):
                continue
            calls.append(
                _RegisterSteeringHsdReqAnimCallArg(
                    idx=idx,
                    start=start,
                    end=end,
                    line=line,
                    indent=match.group("indent"),
                    callee=match.group("callee"),
                    args=tuple(args),
                    arg_text=arg_text,
                    call_arg_local=None,
                    call_arg_expr=cast_expr,
                    call_arg_operand=operand,
                    call_arg_type=cast_type,
                )
            )
            continue

        if re.fullmatch(r"[A-Za-z_]\w*", arg_text) is None:
            continue
        if _node_set_split_synthetic_name(arg_text) or _generated_fpr_product_temp_name(arg_text):
            continue
        arg_decl = _single_fpr_decl_for_name(body_text, arg_text)
        if arg_decl is None:
            continue
        recovered = _find_dominating_fpr_callarg_assignment(
            body_text,
            function_header_text,
            arg_text=arg_text,
            call_idx=idx,
            call_start=start,
            call_depth=depth,
            records=records,
            searchable=searchable,
            searchable_records=searchable_records,
            depths=depths,
            preprocessor_depths=preprocessor_depths,
        )
        if recovered is None:
            continue
        prev_start, prev_end, prev_line, cast_expr, cast_type, operand = recovered
        calls.append(
            _RegisterSteeringHsdReqAnimCallArg(
                idx=idx,
                start=start,
                end=end,
                line=line,
                indent=match.group("indent"),
                callee=match.group("callee"),
                args=tuple(args),
                arg_text=arg_text,
                call_arg_local=arg_text,
                call_arg_expr=cast_expr,
                call_arg_operand=operand,
                call_arg_type=arg_decl.type_name or cast_type,
                assignment_start=prev_start,
                assignment_end=prev_end,
                assignment_line=prev_line,
            )
        )
    return tuple(calls)


def _hsd_req_anim_call_line_with_arg(
    call: _RegisterSteeringHsdReqAnimCallArg,
    replacement_arg: str,
) -> str:
    args = list(call.args)
    args[1] = replacement_arg
    return f"{call.indent}{call.callee}({', '.join(args)});"


def _iter_hsd_jobj_set_translate_y_calls(
    body_text: str,
) -> tuple[_RegisterSteeringTranslateYCall, ...]:
    if re.search(r"(?m)^[ \t]*#", body_text):
        return ()
    records = _text_line_records_with_newline(body_text)
    searchable = _blank_literals_and_comments(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    preprocessor_depths = _preprocessor_depths_for_lines(searchable_records)
    calls: list[_RegisterSteeringTranslateYCall] = []
    for idx, (start, end, _end_with_newline, search_line) in enumerate(searchable_records):
        if idx >= len(records):
            continue
        if preprocessor_depths[idx] != 0 or records[idx][3] != search_line:
            continue
        if (depths[idx] if idx < len(depths) else 0) < 1:
            continue
        if _line_has_label(search_line) or _macro_like_statement(search_line):
            continue
        match = _HSD_JOBJ_SET_TRANSLATE_Y_CALL_RE.match(search_line)
        if match is None:
            continue
        args = _split_top_level_csv(match.group("args"))
        if args is None or len(args) < 2:
            continue
        value_arg = args[1].strip()
        if re.fullmatch(r"[A-Za-z_]\w*", value_arg) is None:
            continue
        line = records[idx][3]
        if body_text.count(line) != 1:
            continue
        calls.append(
            _RegisterSteeringTranslateYCall(
                idx=idx,
                start=start,
                end=end,
                line=line,
                indent=match.group("indent"),
                args=tuple(args),
                value_arg=value_arg,
            )
        )
    return tuple(calls)


def _hsd_set_translate_y_line_with_arg(
    call: _RegisterSteeringTranslateYCall,
    replacement_arg: str,
) -> str:
    args = list(call.args)
    args[1] = replacement_arg
    return f"{call.indent}HSD_JObjSetTranslateY({', '.join(args)});"


def _coupled_call_temp_assignment(
    call: _RegisterSteeringHsdReqAnimCallArg,
    call_temp: str,
    *,
    prefer_direct_cast: bool,
) -> str | None:
    if prefer_direct_cast:
        rhs = call.call_arg_expr
    elif call.call_arg_local is not None:
        rhs = call.call_arg_local
    else:
        rhs = call.call_arg_expr
    if not rhs:
        return None
    return (
        f"{call.indent}{call_temp} = {rhs};\n"
        f"{_hsd_req_anim_call_line_with_arg(call, call_temp)}"
    )


def _coupled_fpr_source_regions(
    product: _RegisterSteeringFprProduct,
    call: _RegisterSteeringHsdReqAnimCallArg,
) -> tuple[str, str]:
    call_source = (
        call.assignment_line.strip()
        if call.assignment_line is not None
        else call.arg_text
    )
    return (
        f"column product/conversion: {product.line.strip()}",
        f"digit call conversion: {call_source}",
    )


def _coupled_fpr_payload(
    *,
    strategy: str,
    span_text: str,
    replacement_text: str,
    product: _RegisterSteeringFprProduct,
    product_temp: str | None,
    cast_expr: str | None,
    cast_temp: str | None,
    call: _RegisterSteeringHsdReqAnimCallArg,
    call_temp: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "span_text": span_text,
        "replacement_text": replacement_text,
        "strategy": strategy,
        "product_local": product.lhs,
        "product_expr": product.product_expr,
        "product_temp_local": product_temp,
        "callee": call.callee,
        "call_arg_expr": call.call_arg_expr,
        "call_temp_local": call_temp,
        "target_virtuals_hint": (32, 33, 46),
        "source_regions": _coupled_fpr_source_regions(product, call),
    }
    if cast_expr is not None:
        payload["cast_expr"] = cast_expr
    if cast_temp is not None:
        payload["cast_temp_local"] = cast_temp
    if call.call_arg_local is not None:
        payload["call_arg_local"] = call.call_arg_local
    return payload


def _callarg_temp_payload(
    *,
    strategy: str,
    span_text: str,
    replacement_text: str,
    call: _RegisterSteeringHsdReqAnimCallArg,
    call_temp: str | None = None,
    reused_local: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "span_text": span_text,
        "replacement_text": replacement_text,
        "strategy": strategy,
        "callee": call.callee,
        "call_arg_expr": call.call_arg_expr,
        "call_arg_operand": call.call_arg_operand,
        "source_regions": (
            f"digit call conversion: {call.assignment_line.strip()}"
            if call.assignment_line is not None
            else f"digit call conversion: {call.arg_text}"
        ),
    }
    if call.call_arg_local is not None:
        payload["call_arg_local"] = call.call_arg_local
    if call_temp is not None:
        payload["call_temp_local"] = call_temp
    if reused_local is not None:
        payload["reused_local"] = reused_local
    return payload


def _identifier_used_after(body_text: str, offset: int, name: str) -> bool:
    searchable = _blank_literals_and_comments(body_text)
    return bool(_identifier_mentions(searchable[offset:], name))


def _iter_reusable_fpr_callarg_locals(
    body_text: str,
    call: _RegisterSteeringHsdReqAnimCallArg,
    *,
    max_locals: int = 2,
) -> tuple[str, ...]:
    if call.assignment_start is None:
        cutoff = call.start
    else:
        cutoff = call.assignment_start
    searchable = _blank_literals_and_comments(body_text)
    names: list[str] = []
    for decl in reversed(_all_top_level_fpr_decls(body_text)):
        if decl.end_with_newline > cutoff:
            continue
        if decl.name == call.call_arg_local:
            continue
        if _node_set_split_synthetic_name(decl.name) or _generated_fpr_product_temp_name(decl.name):
            continue
        if _counter_address_take_rejects(searchable, decl.name):
            continue
        between = searchable[decl.end_with_newline:cutoff]
        if not _identifier_mentions(between, decl.name):
            continue
        if _identifier_used_after(body_text, call.end, decl.name):
            continue
        names.append(decl.name)
        if len(names) >= max_locals:
            break
    return tuple(names)


def _callarg_between_text(body_text: str, call: _RegisterSteeringHsdReqAnimCallArg) -> str:
    if call.assignment_end is None:
        return ""
    between = body_text[call.assignment_end:call.start]
    return between[1:] if between.startswith("\n") else between


_FPR_OWNER_FLOAT_LITERAL_RE = (
    r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?[fF]?"
)


def _simple_fpr_subtraction_expr(expr: str) -> tuple[str, tuple[str, ...]] | None:
    stripped = expr.strip()
    if not stripped or any(token in stripped for token in ("++", "--", "=", "?", ":", ";", ",")):
        return None
    term = rf"(?:[A-Za-z_]\w*|{_FPR_OWNER_FLOAT_LITERAL_RE})"
    match = re.fullmatch(rf"(?P<left>{term})\s*-\s*(?P<right>{term})", stripped)
    if match is None:
        return None
    names = tuple(
        item for item in (match.group("left"), match.group("right"))
        if re.fullmatch(r"[A-Za-z_]\w*", item)
    )
    return stripped, names


def _iter_pcode_only_fpr_fsubs_cast_owner_assignments(
    body_text: str,
    function_header_text: str = "",
) -> tuple[_RegisterSteeringFprOwnerAssignment, ...]:
    if re.search(r"(?m)^[ \t]*#", body_text):
        return ()
    records = _text_line_records_with_newline(body_text)
    searchable = _blank_literals_and_comments(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    preprocessor_depths = _preprocessor_depths_for_lines(searchable_records)
    assignments: list[_RegisterSteeringFprOwnerAssignment] = []
    for idx, (start, end, _end_with_newline, search_line) in enumerate(searchable_records):
        if idx >= len(records):
            continue
        if preprocessor_depths[idx] != 0 or records[idx][3] != search_line:
            continue
        if (depths[idx] if idx < len(depths) else 0) != 1:
            continue
        if _line_has_label(search_line) or _macro_like_statement(search_line):
            continue
        match = _REGISTER_STEERING_ASSIGN_RE.match(search_line)
        if match is None:
            continue
        lhs = match.group("lhs")
        if _node_set_split_synthetic_name(lhs) or _generated_fpr_product_temp_name(lhs):
            continue
        decl = _single_fpr_decl_for_name(body_text, lhs)
        if decl is None:
            continue
        if _counter_address_take_rejects(searchable, lhs):
            continue
        line = records[idx][3]
        if body_text.count(line) != 1:
            continue
        rhs = match.group("rhs")
        cast = _simple_fpr_cast_expr(rhs)
        if cast is not None:
            rhs_expr, _cast_type, operand = cast
            if not _call_arg_operand_is_safe(body_text, function_header_text, operand):
                continue
            assignments.append(
                _RegisterSteeringFprOwnerAssignment(
                    idx=idx,
                    start=start,
                    end=end,
                    line=line,
                    indent=match.group("indent"),
                    lhs=lhs,
                    rhs_expr=rhs_expr,
                    kind="cast-owner",
                    decl_type=decl.type_name,
                    operand_names=(operand,),
                )
            )
            continue
        sub = _simple_fpr_subtraction_expr(rhs)
        if sub is None:
            continue
        rhs_expr, operands = sub
        if operands:
            safe_names = _register_steering_safe_scalar_operand_names(
                body_text,
                function_header_text,
                set(operands),
            )
            if set(operands) - safe_names:
                continue
        assignments.append(
            _RegisterSteeringFprOwnerAssignment(
                idx=idx,
                start=start,
                end=end,
                line=line,
                indent=match.group("indent"),
                lhs=lhs,
                rhs_expr=rhs_expr,
                kind="fsubs-owner",
                decl_type=decl.type_name,
                operand_names=operands,
            )
        )
    return tuple(assignments)


def _iter_pcode_only_fpr_fsubs_cast_owner_anchors(
    body_text: str,
    function_header_text: str = "",
) -> list[Anchor]:
    assignments = _iter_pcode_only_fpr_fsubs_cast_owner_assignments(
        body_text,
        function_header_text=function_header_text,
    )
    if not assignments:
        return []
    searchable = _blank_literals_and_comments(body_text)
    anchors: list[Anchor] = []
    for assignment in assignments:
        insert_after = _insert_after_top_level_fpr_decls(body_text, assignment.start)
        if insert_after is None:
            continue
        temp_name = _fresh_register_steering_name(searchable, f"{assignment.lhs}_owner")
        if temp_name is None:
            continue
        span_text = body_text[insert_after:assignment.end]
        if body_text.count(span_text) != 1:
            continue
        prefix = body_text[insert_after:assignment.start]
        replacement_text = (
            f"{assignment.indent}{assignment.decl_type} {temp_name};\n"
            f"{prefix}"
            f"{assignment.indent}{temp_name} = {assignment.rhs_expr};\n"
            f"{assignment.indent}{assignment.lhs} = {temp_name};"
        )
        if replacement_text == span_text:
            continue
        anchors.append(
            Anchor(
                mutator_key="steer_pcode_only_fpr_fsubs_cast_owner",
                span=(insert_after, assignment.end),
                payload={
                    "span_text": span_text,
                    "replacement_text": replacement_text,
                    "strategy": f"pcode-only-{assignment.kind}-local-temp-split",
                    "owner_local": assignment.lhs,
                    "owner_expr": assignment.rhs_expr,
                    "owner_kind": assignment.kind,
                    "temp_local": temp_name,
                    "operand_names": assignment.operand_names,
                    "source_regions": (
                        f"pcode FPR {assignment.kind}: {assignment.line.strip()}",
                    ),
                },
            )
        )
    return anchors


def _fresh_gpr_temp_name(searchable: str, stem: str) -> str | None:
    base = re.sub(r"\W+", "_", stem).strip("_") or "tmp"
    for candidate in (base, *(f"{base}_{idx}" for idx in range(2, 8))):
        if not _identifier_mentions(searchable, candidate):
            return candidate
    return None


def _gpr_base_leaf_name(base: str) -> str:
    return re.split(r"(?:->|\.)", base.strip())[-1]


def _gpr_pointer_element_type(type_name: str) -> str | None:
    compact = re.sub(r"\s+", "", type_name)
    if not compact.endswith("*"):
        return None
    element_type = compact[:-1]
    return element_type or None


def _gpr_top_level_decl_by_name(
    body_text: str,
) -> dict[str, _RegisterSteeringDecl] | None:
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    decls: dict[str, _RegisterSteeringDecl] = {}
    duplicate = False
    for idx, (start, end, end_with_newline, search_line) in enumerate(
        searchable_records
    ):
        if idx >= len(records) or (depths[idx] if idx < len(depths) else 0) != 1:
            continue
        match = _REGISTER_STEERING_RECOMPUTE_DECL_LINE_RE.match(search_line)
        if match is None:
            continue
        decls_text = match.group("decls")
        if "," in decls_text:
            continue
        name_match = re.match(
            r"\s*\**\s*(?P<name>[A-Za-z_]\w*)\b(?P<rest>.*)$",
            decls_text,
        )
        if name_match is None:
            continue
        rest = name_match.group("rest")
        if "[" in rest or "]" in rest:
            continue
        name = name_match.group("name")
        if name in decls:
            duplicate = True
            continue
        type_name = _normalize_local_reuse_type(match.group("type").strip())
        line = records[idx][3]
        name_start = start + line.find(name)
        decls[name] = _RegisterSteeringDecl(
            idx=idx,
            start=start,
            end=end,
            end_with_newline=end_with_newline,
            line=line,
            type_name=type_name,
            name=name,
            init=rest.strip(),
            depth=1,
            name_span=(name_start, name_start + len(name)),
        )
    return None if duplicate else decls


def _gpr_indexed_element_type(
    base: str,
    decls_by_name: Mapping[str, _RegisterSteeringDecl],
) -> tuple[str, bool] | None:
    decl = decls_by_name.get(base)
    if decl is not None:
        element_type = _gpr_pointer_element_type(decl.type_name)
        if element_type is not None:
            return element_type, True
    leaf = _gpr_base_leaf_name(base)
    if leaf in {"sorted_names", "sorted_fighters"}:
        return "u8", False
    return None


def _gpr_index_expr_is_safe(index_expr: str) -> bool:
    stripped = index_expr.strip()
    if not stripped:
        return False
    if any(token in stripped for token in ("[", "]", "=", "?", ":", ";")):
        return False
    return True


def _insert_after_top_level_gpr_decls(
    body_text: str,
    before_offset: int,
) -> int | None:
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    decl_ends = [
        records[idx][2]
        for idx, (_start, _end, _end_with_newline, search_line) in enumerate(
            searchable_records
        )
        if idx < len(records)
        and (depths[idx] if idx < len(depths) else 0) == 1
        and records[idx][2] <= before_offset
        and _REGISTER_STEERING_RECOMPUTE_DECL_LINE_RE.match(search_line) is not None
    ]
    if not decl_ends:
        return None
    return max(decl_ends)


def _iter_pcode_only_gpr_indexed_assignments(
    body_text: str,
) -> tuple[_RegisterSteeringGprIndexedAssignment, ...]:
    decls_by_name = _gpr_top_level_decl_by_name(body_text)
    if decls_by_name is None:
        return ()
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    assignments: list[_RegisterSteeringGprIndexedAssignment] = []
    for idx, (start, end, _end_with_newline, search_line) in enumerate(searchable_records):
        if idx >= len(records):
            continue
        if (depths[idx] if idx < len(depths) else 0) < 1:
            continue
        if _line_has_label(search_line) or _macro_like_statement(search_line):
            continue
        match = _REGISTER_STEERING_GPR_INDEXED_ASSIGN_RE.match(search_line)
        if match is None:
            continue
        line = records[idx][3]
        if body_text.count(line) != 1:
            continue
        base = match.group("base")
        index_expr = match.group("index").strip()
        if not _gpr_index_expr_is_safe(index_expr):
            continue
        element = _gpr_indexed_element_type(base, decls_by_name)
        if element is None:
            continue
        element_type, base_is_pointer_local = element
        assignments.append(
            _RegisterSteeringGprIndexedAssignment(
                idx=idx,
                start=start,
                end=end,
                line=line,
                indent=match.group("indent"),
                lhs=match.group("lhs"),
                base=base,
                index_expr=index_expr,
                element_type=element_type,
                base_is_pointer_local=base_is_pointer_local,
            )
        )
    return tuple(assignments)


def _previous_gpr_pointer_copy_assignment(
    body_text: str,
    assignment: _RegisterSteeringGprIndexedAssignment,
) -> _RegisterSteeringGprPointerCopyAssignment | None:
    if not assignment.base_is_pointer_local:
        return None
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    target_depth = depths[assignment.idx] if assignment.idx < len(depths) else 0
    for idx in range(assignment.idx - 1, -1, -1):
        start, end, _end_with_newline, search_line = searchable_records[idx]
        depth = depths[idx] if idx < len(depths) else 0
        stripped = search_line.strip()
        if not stripped:
            continue
        if depth < target_depth:
            return None
        if depth != target_depth:
            continue
        if (
            "{" in search_line
            or "}" in search_line
            or "#" in search_line
            or _line_has_label(search_line)
            or _macro_like_statement(search_line)
            or re.search(r"\b(?:if|for|while|do|switch|return|break|continue)\b", search_line)
        ):
            return None
        match = _REGISTER_STEERING_ASSIGN_RE.match(search_line)
        if match is None:
            if _identifier_mentions(search_line, assignment.base):
                return None
            continue
        if match.group("lhs") != assignment.base:
            if re.search(r"\b" + re.escape(assignment.base) + r"\b\s*=", search_line):
                return None
            continue
        rhs = match.group("rhs").strip()
        if any(token in rhs for token in ("[", "]", "?", ":", ";")):
            return None
        return _RegisterSteeringGprPointerCopyAssignment(
            idx=idx,
            start=start,
            end=end,
            line=records[idx][3],
            indent=match.group("indent"),
            lhs=assignment.base,
            rhs_expr=rhs,
        )
    return None


def _append_pcode_only_gpr_anchor(
    anchors: list[Anchor],
    *,
    body_text: str,
    span: tuple[int, int],
    replacement_text: str,
    payload: dict[str, Any],
) -> None:
    span_text = body_text[span[0]:span[1]]
    if not span_text or span_text == replacement_text or body_text.count(span_text) != 1:
        return
    stored_payload = dict(payload)
    stored_payload["span_text"] = span_text
    stored_payload["replacement_text"] = replacement_text
    anchors.append(
        Anchor(
            mutator_key="steer_pcode_only_gpr_address_temp",
            span=span,
            payload=stored_payload,
        )
    )


def _iter_pcode_only_gpr_address_temp_anchors(
    body_text: str,
    function_header_text: str = "",
) -> list[Anchor]:
    del function_header_text
    if re.search(r"(?m)^[ \t]*#", body_text):
        return []
    assignments = _iter_pcode_only_gpr_indexed_assignments(body_text)
    if not assignments:
        return []
    searchable = _blank_literals_and_comments(body_text)
    anchors: list[Anchor] = []
    seen: set[tuple[int, int, str]] = set()

    def append_unique(
        *,
        assignment: _RegisterSteeringGprIndexedAssignment,
        strategy: str,
        span: tuple[int, int],
        replacement_text: str,
        extra_payload: dict[str, Any] | None = None,
    ) -> None:
        key = (span[0], span[1], strategy)
        if key in seen:
            return
        seen.add(key)
        payload = {
            "strategy": strategy,
            "target_local": assignment.lhs,
            "array_base": assignment.base,
            "base_is_pointer_local": assignment.base_is_pointer_local,
            "index_expr": assignment.index_expr,
            "element_type": assignment.element_type,
            "source_regions": (
                f"GPR indexed address temp: {assignment.line.strip()}",
            ),
        }
        if extra_payload:
            payload.update(extra_payload)
        _append_pcode_only_gpr_anchor(
            anchors,
            body_text=body_text,
            span=span,
            replacement_text=replacement_text,
            payload=payload,
        )

    for assignment in assignments:
        insert_after = _insert_after_top_level_gpr_decls(body_text, assignment.start)
        if insert_after is None:
            continue
        prefix = body_text[insert_after:assignment.start]
        addr_temp = _fresh_gpr_temp_name(searchable, f"{assignment.lhs}_addr_gpr")
        if addr_temp is not None:
            replacement_text = (
                f"{assignment.indent}{assignment.element_type}* {addr_temp};\n"
                f"{prefix}"
                f"{assignment.indent}{addr_temp} = "
                f"&{assignment.base}[{assignment.index_expr}];\n"
                f"{assignment.indent}{assignment.lhs} = *{addr_temp};"
            )
            append_unique(
                assignment=assignment,
                strategy="gpr-indexed-address-temp",
                span=(insert_after, assignment.end),
                replacement_text=replacement_text,
                extra_payload={"address_temp_local": addr_temp},
            )

        base_leaf = _gpr_base_leaf_name(assignment.base)
        base_alias = _fresh_gpr_temp_name(searchable, f"{base_leaf}_base_gpr")
        alias_addr = _fresh_gpr_temp_name(searchable, f"{assignment.lhs}_addr_gpr")
        if (
            not assignment.base_is_pointer_local
            and base_alias is not None
            and alias_addr is not None
            and alias_addr != base_alias
        ):
            replacement_text = (
                f"{assignment.indent}{assignment.element_type}* {base_alias};\n"
                f"{assignment.indent}{assignment.element_type}* {alias_addr};\n"
                f"{prefix}"
                f"{assignment.indent}{base_alias} = {assignment.base};\n"
                f"{assignment.indent}{alias_addr} = "
                f"&{base_alias}[{assignment.index_expr}];\n"
                f"{assignment.indent}{assignment.lhs} = *{alias_addr};"
            )
            append_unique(
                assignment=assignment,
                strategy="gpr-indexed-base-alias-address-temp",
                span=(insert_after, assignment.end),
                replacement_text=replacement_text,
                extra_payload={
                    "base_alias_local": base_alias,
                    "address_temp_local": alias_addr,
                },
            )

        copy = _previous_gpr_pointer_copy_assignment(body_text, assignment)
        if copy is None:
            continue
        copy_temp = _fresh_gpr_temp_name(searchable, f"{assignment.base}_copy_gpr")
        if copy_temp is not None:
            copy_prefix = body_text[insert_after:copy.start]
            between = body_text[copy.end:assignment.start]
            replacement_text = (
                f"{assignment.indent}{assignment.element_type}* {copy_temp};\n"
                f"{copy_prefix}"
                f"{copy.indent}{copy_temp} = {copy.rhs_expr};\n"
                f"{copy.indent}{copy.lhs} = {copy_temp};"
                f"{between}"
                f"{assignment.line}"
            )
            append_unique(
                assignment=assignment,
                strategy="gpr-pointer-copy-owner-split",
                span=(insert_after, assignment.end),
                replacement_text=replacement_text,
                extra_payload={
                    "copy_owner_local": copy.lhs,
                    "copy_rhs_expr": copy.rhs_expr,
                    "copy_temp_local": copy_temp,
                    "source_regions": (
                        f"GPR pointer copy product: {copy.line.strip()}",
                        f"GPR indexed address temp: {assignment.line.strip()}",
                    ),
                },
            )
        copy_addr = _fresh_gpr_temp_name(searchable, f"{assignment.base}_addr_gpr")
        if copy_temp is not None and copy_addr is not None and copy_addr != copy_temp:
            copy_prefix = body_text[insert_after:copy.start]
            between = body_text[copy.end:assignment.start]
            replacement_text = (
                f"{assignment.indent}{assignment.element_type}* {copy_temp};\n"
                f"{assignment.indent}{assignment.element_type}* {copy_addr};\n"
                f"{copy_prefix}"
                f"{copy.indent}{copy_temp} = {copy.rhs_expr};\n"
                f"{copy.indent}{copy.lhs} = {copy_temp};"
                f"{between}"
                f"{assignment.indent}{copy_addr} = "
                f"&{assignment.base}[{assignment.index_expr}];\n"
                f"{assignment.indent}{assignment.lhs} = *{copy_addr};"
            )
            append_unique(
                assignment=assignment,
                strategy="gpr-pointer-copy-owner-address-temp",
                span=(insert_after, assignment.end),
                replacement_text=replacement_text,
                extra_payload={
                    "copy_owner_local": copy.lhs,
                    "copy_rhs_expr": copy.rhs_expr,
                    "copy_temp_local": copy_temp,
                    "address_temp_local": copy_addr,
                    "source_regions": (
                        f"GPR pointer copy product: {copy.line.strip()}",
                        f"GPR indexed address temp: {assignment.line.strip()}",
                    ),
                },
            )
    return anchors


def _pcode_only_gpr_address_temp_match_diagnostics(
    body_text: str,
    *,
    anchors: list[Anchor],
) -> dict[str, Any]:
    indexed = _iter_pcode_only_gpr_indexed_assignments(body_text)
    pointer_copy_chains = {
        (
            str(anchor.payload.get("copy_owner_local")),
            str(anchor.payload.get("copy_rhs_expr")),
        )
        for anchor in anchors
        if anchor.payload.get("copy_owner_local")
    }
    return {
        "indexed_gpr_address_expressions": len(indexed),
        "pointer_copy_owner_chains": len(pointer_copy_chains),
        "accepted_anchor_count": len(anchors),
        "base_locals": sorted(
            {
                assignment.base for assignment in indexed
                if assignment.base_is_pointer_local
            }
        ),
        "array_bases": sorted({assignment.base for assignment in indexed}),
        "index_exprs": sorted({assignment.index_expr for assignment in indexed}),
        "generated_strategies": sorted(
            {
                str(anchor.payload.get("strategy"))
                for anchor in anchors
                if anchor.payload.get("strategy")
            }
        ),
    }


def _gpr_pointer_decl_by_name(
    body_text: str,
) -> dict[str, _RegisterSteeringDecl] | None:
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    decls: dict[str, _RegisterSteeringDecl] = {}
    duplicate = False
    for idx, (start, end, end_with_newline, search_line) in enumerate(
        searchable_records
    ):
        if idx >= len(records) or (depths[idx] if idx < len(depths) else 0) < 1:
            continue
        match = _REGISTER_STEERING_RECOMPUTE_DECL_LINE_RE.match(search_line)
        if match is None:
            continue
        decls_text = match.group("decls")
        if "," in decls_text:
            continue
        name_match = re.match(
            r"\s*\**\s*(?P<name>[A-Za-z_]\w*)\b(?P<rest>.*)$",
            decls_text,
        )
        if name_match is None:
            continue
        rest = name_match.group("rest")
        if "[" in rest or "]" in rest:
            continue
        name = name_match.group("name")
        if name in decls:
            duplicate = True
            continue
        type_name = _normalize_local_reuse_type(match.group("type").strip())
        if _gpr_pointer_element_type(type_name) is None:
            continue
        line = records[idx][3]
        name_start = start + line.find(name)
        decls[name] = _RegisterSteeringDecl(
            idx=idx,
            start=start,
            end=end,
            end_with_newline=end_with_newline,
            line=line,
            type_name=type_name,
            name=name,
            init=rest.strip(),
            depth=depths[idx] if idx < len(depths) else 1,
            name_span=(name_start, name_start + len(name)),
        )
    return None if duplicate else decls


def _gpr_case_c_target_local(
    decls: Mapping[str, _RegisterSteeringDecl],
    owner: str,
) -> str:
    if "dst_iter" in decls:
        return "dst_iter"
    return owner


def _previous_gpr_owner_copy_assignment(
    body_text: str,
    *,
    owner: str,
    before_idx: int,
) -> _RegisterSteeringGprPointerCopyAssignment | None:
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    if before_idx >= len(depths):
        return None
    target_depth = depths[before_idx]
    for idx in range(before_idx - 1, -1, -1):
        start, end, _end_with_newline, search_line = searchable_records[idx]
        depth = depths[idx] if idx < len(depths) else 0
        stripped = search_line.strip()
        if not stripped:
            continue
        if depth < target_depth:
            return None
        if depth != target_depth:
            continue
        if (
            "{" in search_line
            or "}" in search_line
            or "#" in search_line
            or _line_has_label(search_line)
            or _macro_like_statement(search_line)
            or re.search(r"\b(?:if|for|while|do|switch|return|break|continue)\b", search_line)
        ):
            return None
        match = _REGISTER_STEERING_ASSIGN_RE.match(search_line)
        if match is None:
            if _identifier_mentions(search_line, owner):
                return None
            continue
        if match.group("lhs") != owner:
            if re.search(r"\b" + re.escape(owner) + r"\b\s*=", search_line):
                return None
            continue
        rhs = match.group("rhs").strip()
        if any(token in rhs for token in ("[", "]", "?", ":", ";")):
            return None
        return _RegisterSteeringGprPointerCopyAssignment(
            idx=idx,
            start=start,
            end=end,
            line=records[idx][3],
            indent=match.group("indent"),
            lhs=owner,
            rhs_expr=rhs,
        )
    return None


def _gpr_case_c_loop_end_idx(
    depths: list[int],
    records: list[tuple[int, int, int, str]],
    *,
    loop_idx: int,
) -> int:
    loop_depth = depths[loop_idx] if loop_idx < len(depths) else 0
    for idx in range(loop_idx + 1, len(records)):
        depth = depths[idx] if idx < len(depths) else 0
        if depth <= loop_depth and records[idx][3].lstrip().startswith("}"):
            return idx
    return len(records) - 1


def _insert_after_gpr_case_c_pointer_decls(
    body_text: str,
    before_offset: int,
) -> int | None:
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    before_idx = next(
        (
            idx for idx, (start, _end, _end_with_newline, _line) in enumerate(records)
            if start == before_offset
        ),
        None,
    )
    if before_idx is None or before_idx >= len(depths):
        return _insert_after_top_level_gpr_decls(body_text, before_offset)
    target_depth = depths[before_idx]
    decl_ends = []
    for idx, (_start, _end, _end_with_newline, search_line) in enumerate(
        searchable_records
    ):
        if idx >= len(records) or records[idx][2] > before_offset:
            continue
        if (depths[idx] if idx < len(depths) else 0) != target_depth:
            continue
        match = _REGISTER_STEERING_RECOMPUTE_DECL_LINE_RE.match(search_line)
        if match is None:
            continue
        if _gpr_pointer_element_type(
            _normalize_local_reuse_type(match.group("type").strip())
        ) is not None:
            decl_ends.append(records[idx][2])
    if decl_ends:
        return max(decl_ends)
    return _insert_after_top_level_gpr_decls(body_text, before_offset)


def _iter_gpr_case_c_copy_product_cases(
    body_text: str,
) -> tuple[_RegisterSteeringGprCaseCCopyProduct, ...]:
    decls = _gpr_pointer_decl_by_name(body_text)
    if decls is None:
        return ()
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    cases: list[_RegisterSteeringGprCaseCCopyProduct] = []
    for idx, (start, end, _end_with_newline, search_line) in enumerate(searchable_records):
        if idx >= len(records) or (depths[idx] if idx < len(depths) else 0) < 1:
            continue
        if _line_has_label(search_line) or _macro_like_statement(search_line):
            continue
        match = _REGISTER_STEERING_GPR_FOR_OWNER_RE.match(search_line)
        if match is None:
            continue
        owner = match.group("owner")
        decl = decls.get(owner)
        if decl is None or _counter_address_take_rejects(searchable, owner):
            continue
        if _gpr_pointer_element_type(decl.type_name) != "u8":
            continue
        loop_end_idx = _gpr_case_c_loop_end_idx(depths, records, loop_idx=idx)
        store = None
        for store_idx in range(idx + 1, loop_end_idx):
            store_line = searchable_records[store_idx][3]
            store_match = _REGISTER_STEERING_GPR_POINTER_STORE_RE.match(store_line)
            if store_match is None or store_match.group("owner") != owner:
                continue
            store = (
                store_idx,
                searchable_records[store_idx][0],
                searchable_records[store_idx][1],
                records[store_idx][3],
                store_match.group("indent"),
                store_match.group("rhs").strip(),
            )
            break
        if store is None:
            continue
        copy = _previous_gpr_owner_copy_assignment(
            body_text,
            owner=owner,
            before_idx=idx,
        )
        store_idx, store_start, store_end, store_line, store_indent, store_rhs = store
        target_local = _gpr_case_c_target_local(decls, owner)
        target_decl = decls.get(target_local)
        cases.append(
            _RegisterSteeringGprCaseCCopyProduct(
                owner=owner,
                owner_type=decl.type_name,
                owner_decl=decl,
                decl_indent=decl.line[: len(decl.line) - len(decl.line.lstrip())],
                case_c_target_local=target_local,
                case_c_target_type=(
                    target_decl.type_name if target_decl is not None else decl.type_name
                ),
                copy=copy,
                loop_idx=idx,
                loop_start=start,
                loop_end=end,
                loop_line=records[idx][3],
                loop_indent=match.group("indent"),
                store_idx=store_idx,
                store_start=store_start,
                store_end=store_end,
                store_line=store_line,
                store_indent=store_indent,
                store_rhs=store_rhs,
            )
        )
    return tuple(cases)


def _gpr_case_c_source_hunks(
    body_text: str,
    *,
    span: tuple[int, int],
    replacement_text: str,
    strategy: str,
) -> tuple[dict[str, Any], ...]:
    span_text = body_text[span[0]:span[1]]
    base_start = body_text.count("\n", 0, span[0]) + 1
    removed = span_text.splitlines()
    added = replacement_text.splitlines()
    return (
        {
            "kind": "gpr-copy-product-case-c",
            "strategy": strategy,
            "base_start": base_start,
            "base_end": base_start + len(removed),
            "removed": removed[:12],
            "added": added[:12],
            "removed_count": len(removed),
            "added_count": len(added),
        },
    )


def _append_pcode_only_gpr_copy_product_case_c_anchor(
    anchors: list[Anchor],
    *,
    body_text: str,
    span: tuple[int, int],
    replacement_text: str,
    payload: dict[str, Any],
) -> None:
    span_text = body_text[span[0]:span[1]]
    if not span_text or span_text == replacement_text or body_text.count(span_text) != 1:
        return
    stored_payload = dict(payload)
    stored_payload["span_text"] = span_text
    stored_payload["replacement_text"] = replacement_text
    stored_payload["source_hunks"] = _gpr_case_c_source_hunks(
        body_text,
        span=span,
        replacement_text=replacement_text,
        strategy=str(payload.get("strategy") or "gpr-case-c"),
    )
    anchors.append(
        Anchor(
            mutator_key="steer_pcode_only_gpr_copy_product_case_c",
            span=span,
            payload=stored_payload,
        )
    )


def _case_c_decl_init_expr(decl: _RegisterSteeringDecl) -> str | None:
    init = decl.init.strip()
    if init.startswith("="):
        init = init[1:].strip()
    return init or None


def _retained_case_c_sensitivity_payload(
    case: _RegisterSteeringGprCaseCCopyProduct,
    *,
    strategy: str,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "strategy": strategy,
        "case_c_target_local": case.case_c_target_local,
        "copy_product_owner_local": case.owner,
        "owner_type": case.owner_type,
        "store_rhs": case.store_rhs,
        "implicit_product_expression": f"{case.owner}++ / *{case.owner}",
        "first_divergence_objective": {
            "case": "C",
            "source": "retained-gpr-case-c-sensitivity",
            "low_confidence_local": case.case_c_target_local,
            "ranked_by": (
                "target_score.virtuals",
                "first_divergence_movement",
            ),
            "desired_effect": (
                "move the retained Case-C simplify/coloring outcome toward "
                "the requested force-phys target"
            ),
        },
        "source_regions": (
            f"Retained GPR Case-C pointer owner: {case.loop_line.strip()}",
            f"Retained GPR Case-C owner store: {case.store_line.strip()}",
        ),
    }
    if case.copy is not None:
        payload["copy_rhs_expr"] = case.copy.rhs_expr
        payload["source_regions"] = (
            f"Retained GPR Case-C pointer copy: {case.copy.line.strip()}",
            *payload["source_regions"],
        )
    if extra_payload:
        payload.update(extra_payload)
    return payload


def _append_retained_gpr_case_c_sensitivity_anchor(
    anchors: list[Anchor],
    *,
    body_text: str,
    span: tuple[int, int],
    replacement_text: str,
    payload: dict[str, Any],
) -> None:
    span_text = body_text[span[0]:span[1]]
    if not span_text or span_text == replacement_text or body_text.count(span_text) != 1:
        return
    stored_payload = dict(payload)
    strategy = str(payload.get("strategy") or "retained-gpr-case-c-sensitivity")
    stored_payload["span_text"] = span_text
    stored_payload["replacement_text"] = replacement_text
    stored_payload["source_hunks"] = _gpr_case_c_source_hunks(
        body_text,
        span=span,
        replacement_text=replacement_text,
        strategy=strategy,
    )
    anchors.append(
        Anchor(
            mutator_key="steer_retained_gpr_case_c_sensitivity",
            span=span,
            payload=stored_payload,
        )
    )


def _iter_pcode_only_gpr_copy_product_case_c_anchors(
    body_text: str,
    function_header_text: str = "",
) -> list[Anchor]:
    del function_header_text
    if re.search(r"(?m)^[ \t]*#", body_text):
        return []
    cases = _iter_gpr_case_c_copy_product_cases(body_text)
    if not cases:
        return []
    searchable = _blank_literals_and_comments(body_text)
    anchors: list[Anchor] = []
    seen: set[tuple[int, int, str]] = set()

    def append_unique(
        case: _RegisterSteeringGprCaseCCopyProduct,
        *,
        strategy: str,
        span: tuple[int, int],
        replacement_text: str,
        extra_payload: dict[str, Any] | None = None,
    ) -> None:
        key = (span[0], span[1], strategy)
        if key in seen:
            return
        seen.add(key)
        payload = {
            "strategy": strategy,
            "case_c_target_local": case.case_c_target_local,
            "copy_product_owner_local": case.owner,
            "owner_type": case.owner_type,
            "store_rhs": case.store_rhs,
            "implicit_product_expression": f"{case.owner}++ / *{case.owner}",
            "source_regions": (
                f"GPR Case-C pointer owner: {case.loop_line.strip()}",
                f"GPR Case-C owner store: {case.store_line.strip()}",
            ),
        }
        if case.copy is not None:
            payload["copy_rhs_expr"] = case.copy.rhs_expr
            payload["source_regions"] = (
                f"GPR Case-C pointer copy: {case.copy.line.strip()}",
                *payload["source_regions"],
            )
        if extra_payload:
            payload.update(extra_payload)
        _append_pcode_only_gpr_copy_product_case_c_anchor(
            anchors,
            body_text=body_text,
            span=span,
            replacement_text=replacement_text,
            payload=payload,
        )

    for case in cases:
        insert_after = _insert_after_gpr_case_c_pointer_decls(
            body_text,
            case.loop_start,
        )
        if insert_after is None:
            continue
        segment = body_text[insert_after:case.store_end]
        owner_temp = _fresh_gpr_temp_name(searchable, f"{case.owner}_case_c_owner_gpr")
        if owner_temp is not None:
            loop_rewrite = case.loop_line.replace(
                f"{case.owner}++",
                f"{owner_temp}++",
                1,
            )
            store_rewrite = case.store_line.replace(
                f"*{case.owner}",
                f"*{owner_temp}",
                1,
            )
            modified = segment.replace(
                case.loop_line,
                f"{case.loop_indent}{owner_temp} = {case.owner};\n{loop_rewrite}",
                1,
            ).replace(case.store_line, store_rewrite, 1)
            replacement_text = f"{case.decl_indent}{case.owner_type} {owner_temp};\n{modified}"
            append_unique(
                case,
                strategy="gpr-case-c-output-owner-copy-before-loop",
                span=(insert_after, case.store_end),
                replacement_text=replacement_text,
                extra_payload={"owner_temp_local": owner_temp},
            )

        store_temp = _fresh_gpr_temp_name(searchable, f"{case.owner}_store_owner_gpr")
        if store_temp is not None:
            store_rewrite = (
                f"{case.store_indent}{store_temp} = {case.owner};\n"
                f"{case.store_indent}*{store_temp} = {case.store_rhs};"
            )
            modified = segment.replace(case.store_line, store_rewrite, 1)
            replacement_text = f"{case.decl_indent}{case.owner_type} {store_temp};\n{modified}"
            append_unique(
                case,
                strategy="gpr-case-c-store-owner-temp",
                span=(insert_after, case.store_end),
                replacement_text=replacement_text,
                extra_payload={"store_owner_temp_local": store_temp},
            )

        if case.copy is None:
            continue
        copy_temp = _fresh_gpr_temp_name(searchable, f"{case.owner}_copy_product_gpr")
        if copy_temp is None:
            continue
        copy_segment = body_text[insert_after:case.copy.end]
        copy_rewrite = (
            f"{case.copy.indent}{copy_temp} = {case.copy.rhs_expr};\n"
            f"{case.copy.indent}{case.copy.lhs} = {copy_temp};"
        )
        modified = copy_segment.replace(case.copy.line, copy_rewrite, 1)
        replacement_text = f"{case.decl_indent}{case.owner_type} {copy_temp};\n{modified}"
        append_unique(
            case,
            strategy="gpr-case-c-output-owner-copy-after-init",
            span=(insert_after, case.copy.end),
            replacement_text=replacement_text,
            extra_payload={"copy_product_temp_local": copy_temp},
        )
    return anchors


def _iter_retained_gpr_case_c_sensitivity_anchors(
    body_text: str,
    function_header_text: str = "",
) -> list[Anchor]:
    del function_header_text
    if re.search(r"(?m)^[ \t]*#", body_text):
        return []
    cases = _iter_gpr_case_c_copy_product_cases(body_text)
    if not cases:
        return []
    anchors: list[Anchor] = []
    seen: set[tuple[int, int, str]] = set()

    def append_unique(
        case: _RegisterSteeringGprCaseCCopyProduct,
        *,
        strategy: str,
        span: tuple[int, int],
        replacement_text: str,
        extra_payload: dict[str, Any] | None = None,
    ) -> None:
        if case.case_c_target_local == case.owner:
            return
        key = (span[0], span[1], strategy)
        if key in seen:
            return
        seen.add(key)
        _append_retained_gpr_case_c_sensitivity_anchor(
            anchors,
            body_text=body_text,
            span=span,
            replacement_text=replacement_text,
            payload=_retained_case_c_sensitivity_payload(
                case,
                strategy=strategy,
                extra_payload=extra_payload,
            ),
        )

    for case in cases:
        if _gpr_pointer_element_type(case.case_c_target_type) != "u8":
            continue
        owner_init_expr = _case_c_decl_init_expr(case.owner_decl)
        if owner_init_expr is None:
            continue
        owner_span = (case.owner_decl.start, case.store_end)
        owner_segment = body_text[owner_span[0]:owner_span[1]]

        store_rewrite = (
            f"{case.store_indent}{case.case_c_target_local} = {case.owner};\n"
            f"{case.store_indent}*{case.case_c_target_local} = {case.store_rhs};"
        )
        append_unique(
            case,
            strategy="retained-gpr-case-c-store-through-low-confidence-local",
            span=(case.store_start, case.store_end),
            replacement_text=store_rewrite,
            extra_payload={"sensitivity_local": case.case_c_target_local},
        )

        loop_rewrite = case.loop_line.replace(
            f"{case.owner}++",
            f"{case.case_c_target_local}++",
            1,
        )
        loop_store_rewrite = case.store_line.replace(
            f"*{case.owner}",
            f"*{case.case_c_target_local}",
            1,
        )
        loop_segment = owner_segment.replace(
            case.owner_decl.line,
            f"{case.owner_decl.line[: len(case.owner_decl.line) - len(case.owner_decl.line.lstrip())]}"
            f"{case.case_c_target_local} = {owner_init_expr};",
            1,
        ).replace(case.loop_line, loop_rewrite, 1).replace(
            case.store_line,
            loop_store_rewrite,
            1,
        )
        append_unique(
            case,
            strategy="retained-gpr-case-c-loop-through-low-confidence-local",
            span=owner_span,
            replacement_text=loop_segment,
            extra_payload={
                "sensitivity_local": case.case_c_target_local,
                "owner_init_expr": owner_init_expr,
            },
        )

        bridge_decl = (
            f"{case.owner_decl.line[: len(case.owner_decl.line) - len(case.owner_decl.line.lstrip())]}"
            f"{case.owner_type} {case.owner};\n"
            f"{case.owner_decl.line[: len(case.owner_decl.line) - len(case.owner_decl.line.lstrip())]}"
            f"{case.case_c_target_local} = {owner_init_expr};\n"
            f"{case.owner_decl.line[: len(case.owner_decl.line) - len(case.owner_decl.line.lstrip())]}"
            f"{case.owner} = {case.case_c_target_local};"
        )
        bridge_segment = owner_segment.replace(case.owner_decl.line, bridge_decl, 1)
        append_unique(
            case,
            strategy="retained-gpr-case-c-owner-init-bridge",
            span=owner_span,
            replacement_text=bridge_segment,
            extra_payload={
                "sensitivity_local": case.case_c_target_local,
                "owner_init_expr": owner_init_expr,
            },
        )
    return anchors


def _pcode_only_gpr_copy_product_case_c_match_diagnostics(
    body_text: str,
    *,
    anchors: list[Anchor],
) -> dict[str, Any]:
    cases = _iter_gpr_case_c_copy_product_cases(body_text)
    anchored_owners = {
        str(anchor.payload.get("copy_product_owner_local"))
        for anchor in anchors
        if anchor.payload.get("copy_product_owner_local")
    }
    case_owners = {case.owner for case in cases}
    unsupported = sorted(case_owners - anchored_owners)
    return {
        "case_c_copy_product_pairs": len(cases),
        "low_confidence_pointer_locals": sorted(
            {
                case.case_c_target_local for case in cases
                if case.case_c_target_local != case.owner
            }
        ),
        "implicit_add_owner_candidates": sorted(case_owners),
        "accepted_anchor_count": len(anchors),
        "unsupported_copy_product_spans": unsupported,
        "generated_strategies": sorted(
            {
                str(anchor.payload.get("strategy"))
                for anchor in anchors
                if anchor.payload.get("strategy")
            }
        ),
    }


def _retained_gpr_case_c_sensitivity_match_diagnostics(
    body_text: str,
    *,
    anchors: list[Anchor],
) -> dict[str, Any]:
    base = _pcode_only_gpr_copy_product_case_c_match_diagnostics(
        body_text,
        anchors=anchors,
    )
    base["sensitivity_candidate_count"] = len(anchors)
    base["first_divergence_objectives"] = [
        anchor.payload.get("first_divergence_objective")
        for anchor in anchors
        if anchor.payload.get("first_divergence_objective")
    ]
    return base


def _if_condition_bounds(line: str) -> tuple[str, int, int, bool] | None:
    if_match = re.search(r"\bif\s*\(", line)
    if if_match is None or not line.rstrip().endswith("{"):
        return None
    open_idx = line.find("(", if_match.start())
    if open_idx < 0:
        return None
    depth = 0
    close_idx = None
    for idx in range(open_idx, len(line)):
        ch = line[idx]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                close_idx = idx
                break
    if close_idx is None:
        return None
    condition = line[open_idx + 1:close_idx]
    if not condition.strip():
        return None
    is_else_if = (
        re.match(r"^[ \t]*}\s*else\s+if\b", line) is not None
        or re.match(r"^[ \t]*else\s+if\b", line) is not None
    )
    return condition, open_idx + 1, close_idx, is_else_if


def _gpr_bool_mask_normalized_key(expr: str, mask: str) -> str:
    return re.sub(r"\s+", "", f"{expr}&{mask}")


def _gpr_bool_mask_source_expr_is_safe(expr: str) -> bool:
    return (
        re.fullmatch(
            r"[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*",
            expr.strip(),
        )
        is not None
    )


def _gpr_bool_mask_const_is_safe(mask: str) -> bool:
    return re.fullmatch(_GPR_BOOL_MASK_CONST_PATTERN, mask.strip()) is not None


def _gpr_bool_mask_temp_stem(expr: str, mask: str) -> str:
    expr_part = re.sub(r"(?:->|\.)", "_", expr.strip())
    mask_part = re.sub(r"\W+", "_", mask.strip()).strip("_")
    return f"{expr_part}_{mask_part}_mask_gpr"


def _gpr_bool_mask_temp_type(
    expr: str,
    *,
    decls: Mapping[str, _RegisterSteeringDecl] | None,
    params: Mapping[str, str],
) -> str:
    if re.search(r"(?:->|\.)flags$", expr):
        return "u32"
    base = re.match(r"(?P<base>[A-Za-z_]\w*)", expr)
    if base is None:
        return "u32"
    base_name = base.group("base")
    decl = decls.get(base_name) if decls is not None else None
    if decl is not None and _is_scalar_type(decl.type_name):
        return decl.type_name
    param_type = params.get(base_name)
    if param_type is not None and _is_scalar_type(param_type):
        return param_type
    return "u32"


def _gpr_bool_mask_source_hunks(
    body_text: str,
    *,
    span: tuple[int, int],
    replacement_text: str,
    strategy: str,
) -> tuple[dict[str, Any], ...]:
    span_text = body_text[span[0]:span[1]]
    base_start = body_text.count("\n", 0, span[0]) + 1
    removed = span_text.splitlines()
    added = replacement_text.splitlines()
    return (
        {
            "kind": "gpr-bool-mask-temp-repair",
            "strategy": strategy,
            "base_start": base_start,
            "base_end": base_start + len(removed),
            "removed": removed[:12],
            "added": added[:12],
            "removed_count": len(removed),
            "added_count": len(added),
        },
    )


def _append_pcode_only_gpr_bool_mask_anchor(
    anchors: list[Anchor],
    *,
    body_text: str,
    span: tuple[int, int],
    replacement_text: str,
    payload: dict[str, Any],
) -> None:
    span_text = body_text[span[0]:span[1]]
    if not span_text or span_text == replacement_text:
        return
    stored_payload = dict(payload)
    strategy = str(payload.get("strategy") or "gpr-bool-mask-temp")
    stored_payload["span_text"] = span_text
    stored_payload["replacement_text"] = replacement_text
    stored_payload["source_hunks"] = _gpr_bool_mask_source_hunks(
        body_text,
        span=span,
        replacement_text=replacement_text,
        strategy=strategy,
    )
    anchors.append(
        Anchor(
            mutator_key="steer_pcode_only_gpr_bool_mask_temp",
            span=span,
            payload=stored_payload,
        )
    )


def _gpr_bool_mask_matching_block_end_idx(
    body_text: str,
    *,
    line_idx: int,
) -> int | None:
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(searchable)
    if line_idx >= len(records):
        return None
    start, _end, _end_with_newline, line = records[line_idx]
    brace_idx = line.find("{")
    if brace_idx < 0:
        return None
    depth = 0
    absolute_start = start + brace_idx
    for idx in range(absolute_start, len(searchable)):
        ch = searchable[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                for rec_idx, (rec_start, rec_end, _rec_end_nl, _rec_line) in enumerate(records):
                    if rec_start <= idx <= rec_end:
                        return rec_idx
                return None
    return None


def _gpr_bool_mask_indent_line(line: str) -> str:
    return ("    " + line) if line.strip() else line


def _gpr_bool_mask_enclosing_block_decl_offset(
    body_text: str,
    *,
    records: list[tuple[int, int, int, str]],
    candidate_idx: int,
) -> int | None:
    if candidate_idx >= len(records):
        return None
    searchable = _blank_literals_and_comments(body_text)
    candidate_start = records[candidate_idx][0]
    stack: list[int] = []
    for idx, ch in enumerate(searchable[:candidate_start]):
        if ch == "{":
            stack.append(idx)
        elif ch == "}" and stack:
            stack.pop()
    if not stack:
        return None
    block_open = stack[-1]
    block_line_idx = None
    for idx, (start, end, _end_with_newline, _line) in enumerate(records):
        if start <= block_open <= end:
            block_line_idx = idx
            break
    if block_line_idx is None:
        return None
    insert_idx = block_line_idx + 1
    while insert_idx < len(records):
        line = records[insert_idx][3]
        stripped = line.strip()
        if not stripped:
            insert_idx += 1
            continue
        if _REGISTER_STEERING_DECL_RE.match(line):
            insert_idx += 1
            continue
        break
    if insert_idx >= len(records) or insert_idx > candidate_idx:
        return None
    return records[insert_idx][0]


def _gpr_bool_mask_predicate_replacement(
    body_text: str,
    *,
    records: list[tuple[int, int, int, str]],
    candidate: Mapping[str, Any],
    temp_name: str,
    temp_type: str,
    replacement_line: str,
) -> tuple[tuple[int, int], str] | None:
    idx = int(candidate["idx"])
    decl_offset = _gpr_bool_mask_enclosing_block_decl_offset(
        body_text,
        records=records,
        candidate_idx=idx,
    )
    if decl_offset is None:
        return None
    line_start = int(candidate["start"])
    line_end = int(candidate["end"])
    if decl_offset > line_start:
        return None
    indent = str(candidate["indent"])
    prefix = body_text[decl_offset:line_start]
    replacement_text = (
        f"{indent}{temp_type} {temp_name};\n"
        f"{prefix}"
        f"{indent}{temp_name} = {candidate['mask_expression']};\n"
        f"{replacement_line}"
    )
    return (decl_offset, line_end), replacement_text


def _gpr_bool_mask_else_if_replacement(
    body_text: str,
    *,
    records: list[tuple[int, int, int, str]],
    candidate: Mapping[str, Any],
    temp_name: str,
    temp_type: str,
) -> tuple[tuple[int, int], str] | None:
    idx = int(candidate["idx"])
    end_idx = _gpr_bool_mask_matching_block_end_idx(body_text, line_idx=idx)
    if end_idx is None or end_idx <= idx or end_idx >= len(records):
        return None
    line = str(candidate["line"])
    indent = str(candidate["indent"])
    mask_expr = str(candidate["mask_expression"])
    replacement_condition = str(candidate["replacement_condition"])
    original_lines = [record[3] for record in records[idx:end_idx + 1]]
    inner_lines = original_lines[1:-1]
    nested_indent = indent + "    "
    replacement_lines = [
        f"{indent}}} else {{",
        f"{nested_indent}{temp_type} {temp_name};",
        f"{nested_indent}{temp_name} = {mask_expr};",
        f"{nested_indent}if ({replacement_condition}) {{",
        *(_gpr_bool_mask_indent_line(inner) for inner in inner_lines),
        f"{nested_indent}}}",
        f"{indent}}}",
    ]
    span = (records[idx][0], records[end_idx][1])
    replacement_text = "\n".join(replacement_lines)
    if line not in body_text[span[0]:span[1]]:
        return None
    return span, replacement_text


def _source_function_body_from_definition(
    source_text: str,
    signature_start: int,
) -> str | None:
    searchable = _blank_literals_and_comments(source_text)
    open_idx = searchable.find("{", signature_start)
    semicolon_idx = searchable.find(";", signature_start)
    if open_idx < 0 or (semicolon_idx >= 0 and semicolon_idx < open_idx):
        return None
    depth = 0
    for idx in range(open_idx, len(searchable)):
        ch = searchable[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source_text[open_idx + 1:idx]
    return None


def _available_translate_dirty_wrappers(
    source_text: str,
    *,
    axis: str,
) -> tuple[str, ...]:
    local_pattern = re.compile(
        r"(?m)^[ \t]*(?:static\s+inline\s+)?void\s+"
        rf"(?P<name>(?!HSD_)[A-Za-z_]\w*_JObjSetTranslate{re.escape(axis)})"
        r"\s*\("
    )
    wrappers = []
    translate_field_pattern = re.compile(
        rf"\btranslate\s*\.\s*{re.escape(axis.lower())}\s*="
    )
    for match in local_pattern.finditer(source_text):
        body = _source_function_body_from_definition(source_text, match.start())
        if body is None:
            continue
        if "HSD_JObjSetMtxDirty" not in body:
            continue
        if translate_field_pattern.search(body) is None:
            continue
        wrappers.append(match.group("name"))
    hsd_wrapper = f"HSD_JObjSetTranslate{axis}WithMtxDirty"
    if re.search(r"\b" + re.escape(hsd_wrapper) + r"\b", source_text):
        wrappers.append(hsd_wrapper)
    return tuple(dict.fromkeys(wrappers))


def _iter_gpr_bool_mask_raw_candidates(
    body_text: str,
    function_header_text: str,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    decls = _gpr_top_level_decl_by_name(body_text)
    params = {name: type_name for type_name, name in _parse_signature_params(function_header_text)}
    candidates: list[dict[str, Any]] = []
    attempted_regions: list[str] = []
    rejection_reasons: list[str] = []

    for idx, (start, end, end_with_newline, search_line) in enumerate(searchable_records):
        if idx >= len(records):
            continue
        if (depths[idx] if idx < len(depths) else 0) < 1:
            continue
        if _line_has_label(search_line) or _macro_like_statement(search_line):
            continue
        condition_info = _if_condition_bounds(search_line)
        if condition_info is None:
            continue
        condition, condition_start, condition_end, is_else_if = condition_info
        line = records[idx][3]
        indent = line[: len(line) - len(line.lstrip(" \t}"))]
        dirty_matches = list(_GPR_NEGATED_FIELD_MASK_RE.finditer(condition))
        scalar_matches = [
            match for match in _GPR_BOOL_MASK_OPERAND_RE.finditer(condition)
            if not re.search(r"(?:->|\.)flags$", match.group("expr"))
        ]
        if dirty_matches:
            if len(dirty_matches) != 1:
                rejection_reasons.append("multi-mask-condition-unsupported")
                continue
            match = dirty_matches[0]
            expr = match.group("expr").strip()
            mask = match.group("mask").strip()
            if not (
                _gpr_bool_mask_source_expr_is_safe(expr)
                and _gpr_bool_mask_const_is_safe(mask)
            ):
                rejection_reasons.append("unsafe-mask-source-expression")
                continue
            mask_expression = f"{expr} & {mask}"
            attempted_regions.append(f"GPR negated field mask predicate: {line.strip()}")
            temp_type = _gpr_bool_mask_temp_type(expr, decls=decls, params=params)
            candidates.append({
                "idx": idx,
                "start": start,
                "end": end,
                "end_with_newline": end_with_newline,
                "line": line,
                "indent": line[: len(line) - len(line.lstrip(" \t"))],
                "is_else_if": is_else_if,
                "strategy": "gpr-negated-field-mask-temp",
                "expr": expr,
                "mask": mask,
                "mask_expression": mask_expression,
                "temp_type": temp_type,
                "replacement_condition": (
                    condition[:match.start()] + "__TEMP_NOT__" + condition[match.end():]
                ),
                "normalized_key": _gpr_bool_mask_normalized_key(expr, mask),
                "source_region": f"GPR negated field mask predicate: {line.strip()}",
            })
            continue
        if not scalar_matches:
            continue
        if len(scalar_matches) != 1:
            rejection_reasons.append("multi-mask-condition-unsupported")
            continue
        match = scalar_matches[0]
        expr = match.group("expr").strip()
        mask = match.group("mask").strip()
        if not (
            _gpr_bool_mask_source_expr_is_safe(expr)
            and _gpr_bool_mask_const_is_safe(mask)
        ):
            rejection_reasons.append("unsafe-mask-source-expression")
            continue
        mask_expression = f"{expr} & {mask}"
        attempted_regions.append(f"GPR bool/mask predicate: {line.strip()}")
        temp_type = _gpr_bool_mask_temp_type(expr, decls=decls, params=params)
        candidates.append({
            "idx": idx,
            "start": start,
            "end": end,
            "end_with_newline": end_with_newline,
            "line": line,
            "indent": line[: len(line) - len(line.lstrip(" \t"))],
            "is_else_if": is_else_if,
            "strategy": "gpr-bool-mask-predicate-temp",
            "expr": expr,
            "mask": mask,
            "mask_expression": mask_expression,
            "temp_type": temp_type,
            "replacement_condition": (
                condition[:match.start()] + "__TEMP__" + condition[match.end():]
            ),
            "normalized_key": _gpr_bool_mask_normalized_key(expr, mask),
            "source_region": f"GPR bool/mask predicate: {line.strip()}",
        })
    return candidates, attempted_regions, rejection_reasons


def _iter_gpr_bool_mask_call_substitution_anchors(
    body_text: str,
    *,
    source_text: str,
    rejection_reasons: list[str],
    attempted_regions: list[str],
) -> list[Anchor]:
    records = _text_line_records_with_newline(body_text)
    searchable = _blank_literals_and_comments(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    anchors: list[Anchor] = []
    for idx, (start, end, _end_with_newline, search_line) in enumerate(searchable_records):
        if idx >= len(records) or (depths[idx] if idx < len(depths) else 0) < 1:
            continue
        if _line_has_label(search_line) or _macro_like_statement(search_line):
            continue
        match = _HSD_JOBJ_TRANSLATE_CALL_RE.match(search_line)
        if match is None:
            continue
        line = records[idx][3]
        axis = match.group("axis")
        callee = match.group("callee")
        wrappers = _available_translate_dirty_wrappers(source_text, axis=axis)
        attempted_regions.append(f"JObj translate dirty-wrapper call: {line.strip()}")
        if not wrappers:
            rejection_reasons.append("dirty-wrapper-unavailable")
            continue
        for wrapper in wrappers:
            replacement_line = line.replace(callee, wrapper, 1)
            if replacement_line == line:
                continue
            _append_pcode_only_gpr_bool_mask_anchor(
                anchors,
                body_text=body_text,
                span=(start, end),
                replacement_text=replacement_line,
                payload={
                    "strategy": "jobj-translate-dirty-wrapper-call",
                    "source_regions": (
                        f"JObj translate dirty-wrapper call: {line.strip()}",
                    ),
                    "source_region_kind": "jobj-translate-dirty-wrapper-call",
                    "original_callee": callee,
                    "replacement_callee": wrapper,
                    "axis": axis,
                },
            )
    return anchors


def _iter_pcode_only_gpr_bool_mask_temp_anchors(
    body_text: str,
    function_header_text: str = "",
    *,
    source_text: str | None = None,
) -> list[Anchor]:
    if re.search(r"(?m)^[ \t]*#", body_text):
        return []
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    candidates, attempted_regions, rejection_reasons = (
        _iter_gpr_bool_mask_raw_candidates(body_text, function_header_text)
    )
    key_counts: dict[str, int] = {}
    for candidate in candidates:
        key = str(candidate["normalized_key"])
        key_counts[key] = key_counts.get(key, 0) + 1
    anchors: list[Anchor] = []
    seen: set[tuple[int, int, str]] = set()
    for candidate in candidates:
        key = str(candidate["normalized_key"])
        if key_counts.get(key, 0) != 1:
            rejection_reasons.append("ambiguous-source-region")
            continue
        temp_name = _fresh_gpr_temp_name(
            searchable,
            _gpr_bool_mask_temp_stem(str(candidate["expr"]), str(candidate["mask"])),
        )
        if temp_name is None:
            rejection_reasons.append("temp-name-exhausted")
            continue
        temp_type = str(candidate["temp_type"])
        replacement_condition = str(candidate["replacement_condition"])
        if "__TEMP_NOT__" in replacement_condition:
            replacement_condition = replacement_condition.replace(
                "__TEMP_NOT__",
                f"!{temp_name}",
                1,
            )
        else:
            replacement_condition = replacement_condition.replace(
                "__TEMP__",
                temp_name,
                1,
            )
        line = str(candidate["line"])
        condition_info = _if_condition_bounds(line)
        if condition_info is None:
            rejection_reasons.append("source-region-unresolved")
            continue
        _condition, condition_start, condition_end, is_else_if = condition_info
        replacement_line = (
            line[:condition_start] + replacement_condition + line[condition_end:]
        )
        if is_else_if:
            built = _gpr_bool_mask_else_if_replacement(
                body_text,
                records=records,
                candidate={**candidate, "replacement_condition": replacement_condition},
                temp_name=temp_name,
                temp_type=temp_type,
            )
            if built is None:
                rejection_reasons.append("else-if-source-region-unresolved")
                continue
            span, replacement_text = built
        else:
            built = _gpr_bool_mask_predicate_replacement(
                body_text,
                records=records,
                candidate=candidate,
                temp_name=temp_name,
                temp_type=temp_type,
                replacement_line=replacement_line,
            )
            if built is None:
                rejection_reasons.append("source-region-unresolved")
                continue
            span, replacement_text = built
        key_tuple = (span[0], span[1], str(candidate["strategy"]))
        if key_tuple in seen:
            continue
        seen.add(key_tuple)
        _append_pcode_only_gpr_bool_mask_anchor(
            anchors,
            body_text=body_text,
            span=span,
            replacement_text=replacement_text,
            payload={
                "strategy": candidate["strategy"],
                "source_regions": (candidate["source_region"],),
                "source_region_kind": "gpr-bool-mask-predicate",
                "mask_expression": candidate["mask_expression"],
                "mask_source_expr": candidate["expr"],
                "mask_const": candidate["mask"],
                "mask_temp_local": temp_name,
                "mask_temp_type": temp_type,
                "normalized_mask_expression": key,
            },
        )
    anchors.extend(
        _iter_gpr_bool_mask_call_substitution_anchors(
            body_text,
            source_text=source_text or body_text,
            rejection_reasons=rejection_reasons,
            attempted_regions=attempted_regions,
        )
    )
    return anchors


def _pcode_only_gpr_bool_mask_temp_match_diagnostics(
    body_text: str,
    *,
    anchors: list[Anchor],
    function_header_text: str = "",
    source_text: str | None = None,
) -> dict[str, Any]:
    candidates, attempted_regions, rejection_reasons = (
        _iter_gpr_bool_mask_raw_candidates(body_text, function_header_text)
    )
    key_counts: dict[str, int] = {}
    for candidate in candidates:
        key = str(candidate["normalized_key"])
        key_counts[key] = key_counts.get(key, 0) + 1
    duplicate_keys = sorted(key for key, count in key_counts.items() if count > 1)
    if duplicate_keys:
        rejection_reasons.append("ambiguous-source-region")
    call_anchors = _iter_gpr_bool_mask_call_substitution_anchors(
        body_text,
        source_text=source_text or body_text,
        rejection_reasons=rejection_reasons,
        attempted_regions=attempted_regions,
    )
    del call_anchors
    strategies = sorted(
        {
            str(anchor.payload.get("strategy"))
            for anchor in anchors
            if anchor.payload.get("strategy")
        }
    )
    zero_probe_reasons = []
    if not anchors:
        zero_probe_reasons = sorted(dict.fromkeys(rejection_reasons)) or [
            "source-pattern-not-found"
        ]
    return {
        "scalar_mask_predicate_count": sum(
            1 for candidate in candidates
            if candidate.get("strategy") == "gpr-bool-mask-predicate-temp"
        ),
        "negated_field_mask_predicate_count": sum(
            1 for candidate in candidates
            if candidate.get("strategy") == "gpr-negated-field-mask-temp"
        ),
        "translate_setter_call_count": len(
            re.findall(r"\bHSD_JObjSetTranslate[XYZ]\s*\(", body_text)
        ),
        "accepted_anchor_count": len(anchors),
        "generated_strategy_count": len(strategies),
        "generated_strategies": strategies,
        "attempted_source_regions": list(dict.fromkeys(attempted_regions))[:16],
        "accepted_source_regions": list(dict.fromkeys(
            str(region)
            for anchor in anchors
            for region in anchor.payload.get("source_regions", ())
        ))[:16],
        "duplicate_mask_expressions": duplicate_keys,
        "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
        "zero_probe_reasons": zero_probe_reasons,
    }


def _iter_pcode_only_fpr_callarg_temp_anchors(
    body_text: str,
    function_header_text: str = "",
) -> list[Anchor]:
    if re.search(r"(?m)^[ \t]*#", body_text):
        return []
    calls = _iter_hsd_jobj_req_anim_all_call_args(
        body_text,
        function_header_text,
    )
    if not calls:
        return []
    searchable = _blank_literals_and_comments(body_text)
    anchors: list[Anchor] = []

    for call in calls:
        call_stem = call.call_arg_local or call.call_arg_operand
        call_temp = _fresh_register_steering_name(searchable, f"{call_stem}_call")

        if call.call_arg_local is not None and call.assignment_start is not None:
            span_text = body_text[call.assignment_start:call.end]
            if body_text.count(span_text) != 1:
                continue
            if call.assignment_line is None or body_text.count(call.assignment_line) != 1:
                continue
            between_text = _callarg_between_text(body_text, call)
            if not _identifier_used_after(body_text, call.end, call.call_arg_local):
                direct_call = _hsd_req_anim_call_line_with_arg(call, call.call_arg_expr)
                anchors.append(
                    Anchor(
                        mutator_key="steer_pcode_only_fpr_callarg_temp",
                        span=(call.assignment_start, call.end),
                        payload=_callarg_temp_payload(
                            strategy="fpr-callarg-dematerialize-existing-local",
                            span_text=span_text,
                            replacement_text=f"{between_text}{direct_call}",
                            call=call,
                        ),
                    )
                )

            assignment_call = _hsd_req_anim_call_line_with_arg(
                call,
                f"({call.call_arg_local} = {call.call_arg_expr})",
            )
            anchors.append(
                Anchor(
                    mutator_key="steer_pcode_only_fpr_callarg_temp",
                    span=(call.assignment_start, call.end),
                    payload=_callarg_temp_payload(
                        strategy="fpr-callarg-assignment-expression",
                        span_text=span_text,
                        replacement_text=f"{between_text}{assignment_call}",
                        call=call,
                    ),
                )
            )

            preserve_local = (
                f"{call.assignment_line}\n"
                f"{between_text}"
                f"{_hsd_req_anim_call_line_with_arg(call, call.call_arg_expr)}"
            )
            anchors.append(
                Anchor(
                    mutator_key="steer_pcode_only_fpr_callarg_temp",
                    span=(call.assignment_start, call.end),
                    payload=_callarg_temp_payload(
                        strategy="fpr-callarg-duplicate-direct-cast-preserve-local",
                        span_text=span_text,
                        replacement_text=preserve_local,
                        call=call,
                    ),
                )
            )

            for reusable in _iter_reusable_fpr_callarg_locals(body_text, call):
                reuse_text = (
                    f"{call.indent}{reusable} = {call.call_arg_expr};\n"
                    f"{between_text}"
                    f"{_hsd_req_anim_call_line_with_arg(call, reusable)}"
                )
                anchors.append(
                    Anchor(
                        mutator_key="steer_pcode_only_fpr_callarg_temp",
                        span=(call.assignment_start, call.end),
                        payload=_callarg_temp_payload(
                            strategy="fpr-callarg-reuse-dead-fpr-local",
                            span_text=span_text,
                            replacement_text=reuse_text,
                            call=call,
                            reused_local=reusable,
                        ),
                    )
                )

        call_span_text = body_text[call.start:call.end]
        if body_text.count(call_span_text) != 1:
            continue
        if call_temp is not None:
            block_assign = (
                f"{call.indent}{{\n"
                f"{call.indent}    {call.call_arg_type} {call_temp};\n"
                f"{call.indent}    {call_temp} = {call.call_arg_expr};\n"
                f"{call.indent}    "
                f"{call.callee}({', '.join((call.args[0], call_temp, *call.args[2:]))});\n"
                f"{call.indent}}}"
            )
            anchors.append(
                Anchor(
                    mutator_key="steer_pcode_only_fpr_callarg_temp",
                    span=(call.start, call.end),
                    payload=_callarg_temp_payload(
                        strategy="fpr-callarg-block-local-assign-temp",
                        span_text=call_span_text,
                        replacement_text=block_assign,
                        call=call,
                        call_temp=call_temp,
                    ),
                )
            )

            block_init = (
                f"{call.indent}{{\n"
                f"{call.indent}    {call.call_arg_type} {call_temp} = "
                f"{call.call_arg_expr};\n"
                f"{call.indent}    "
                f"{call.callee}({', '.join((call.args[0], call_temp, *call.args[2:]))});\n"
                f"{call.indent}}}"
            )
            anchors.append(
                Anchor(
                    mutator_key="steer_pcode_only_fpr_callarg_temp",
                    span=(call.start, call.end),
                    payload=_callarg_temp_payload(
                        strategy="fpr-callarg-block-local-init-temp",
                        span_text=call_span_text,
                        replacement_text=block_init,
                        call=call,
                        call_temp=call_temp,
                    ),
                )
            )
    return anchors


def _mixed_pcode_source_regions(
    case: _RegisterSteeringMixedPcodeFprLifetimeCase,
) -> tuple[str, ...]:
    call_source = (
        case.digit_call.assignment_line.strip()
        if case.digit_call.assignment_line is not None
        else case.digit_call.arg_text
    )
    return (
        f"row owner fsubs: {case.owner_assignment.line.strip()}",
        f"row adjusted alias: {case.row_adj_assignment_line.strip()}",
        f"digit call conversion: {call_source}",
        f"row translate: {case.row_translate_call.line.strip()}",
        f"adjusted translate: {case.row_adj_translate_call.line.strip()}",
    )


def _mixed_pcode_payload(
    *,
    case: _RegisterSteeringMixedPcodeFprLifetimeCase,
    strategy: str,
    span_text: str,
    replacement_text: str,
    row_adj_temp: str | None = None,
    digit_call_temp: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "span_text": span_text,
        "replacement_text": replacement_text,
        "strategy": strategy,
        "row_local": case.row_local,
        "row_adj_local": case.row_adj_local,
        "row_adj_owner_local": case.row_adj_owner_local,
        "call_arg_local": case.digit_call.call_arg_local,
        "call_arg_operand": case.digit_call.call_arg_operand,
        "source_regions": _mixed_pcode_source_regions(case),
        "target_virtuals_hint": (32, 36, 39),
    }
    if row_adj_temp is not None:
        payload["row_adj_temp_local"] = row_adj_temp
    if digit_call_temp is not None:
        payload["digit_call_temp_local"] = digit_call_temp
    return payload


def _iter_mixed_pcode_fpr_lifetime_pressure_cases(
    body_text: str,
    function_header_text: str = "",
) -> tuple[_RegisterSteeringMixedPcodeFprLifetimeCase, ...]:
    if re.search(r"(?m)^[ \t]*#", body_text):
        return ()
    decls = _register_steering_decl_records(body_text)
    if decls is None:
        return ()
    top_decls = tuple(decl for decl in decls if decl.depth == 1)
    if _register_steering_has_duplicate_top_level_names(top_decls):
        return ()
    searchable = _blank_literals_and_comments(body_text)
    assignments = _iter_pcode_only_fpr_fsubs_cast_owner_assignments(
        body_text,
        function_header_text=function_header_text,
    )
    calls = _iter_hsd_jobj_req_anim_all_call_args(
        body_text,
        function_header_text=function_header_text,
    )
    translate_calls = _iter_hsd_jobj_set_translate_y_calls(body_text)
    if not assignments or not calls or len(translate_calls) < 2:
        return ()

    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    cases: list[_RegisterSteeringMixedPcodeFprLifetimeCase] = []
    for owner in assignments:
        if owner.kind != "fsubs-owner" or len(owner.operand_names) != 1:
            continue
        row_local = owner.operand_names[0]
        if (
            _single_fpr_decl_for_name(body_text, row_local) is None
            or _single_fpr_decl_for_name(body_text, owner.lhs) is None
            or _counter_address_take_rejects(searchable, row_local)
            or _counter_address_take_rejects(searchable, owner.lhs)
        ):
            continue
        row_adj_assignment: tuple[int, int, str, str] | None = None
        for idx in range(owner.idx + 1, len(searchable_records)):
            start, end, _end_with_newline, search_line = searchable_records[idx]
            if idx >= len(records):
                continue
            if not search_line.strip():
                continue
            if (depths[idx] if idx < len(depths) else 0) != 1:
                break
            assign = _REGISTER_STEERING_ASSIGN_RE.match(search_line)
            if assign is None:
                break
            if assign.group("rhs").strip() == owner.lhs:
                row_adj = assign.group("lhs")
                row_adj_assignment = (start, end, records[idx][3], row_adj)
                break
        if row_adj_assignment is None:
            continue
        row_adj_start, row_adj_end, row_adj_line, row_adj_local = row_adj_assignment
        row_adj_decl = _single_fpr_decl_for_name(body_text, row_adj_local)
        if (
            row_adj_decl is None
            or row_adj_local == owner.lhs
            or _counter_address_take_rejects(searchable, row_adj_local)
        ):
            continue
        if _region_assigns_any(
            searchable[row_adj_end:],
            (row_local, row_adj_local, owner.lhs),
        ):
            # Later mutations make it too easy to move the translate/callarg
            # windows across a semantic update.
            continue
        for call in calls:
            if (
                call.call_arg_local is None
                or call.assignment_start is None
                or call.assignment_end is None
                or call.assignment_start <= row_adj_end
                or _counter_address_take_rejects(searchable, call.call_arg_local)
                or _counter_address_take_rejects(searchable, call.call_arg_operand)
            ):
                continue
            between_owner_and_call = searchable[row_adj_end:call.assignment_start]
            if _region_assigns_any(
                between_owner_and_call,
                (row_local, row_adj_local, owner.lhs, call.call_arg_local),
            ):
                continue
            row_translate = next(
                (
                    candidate for candidate in translate_calls
                    if candidate.start > call.end and candidate.value_arg == row_local
                ),
                None,
            )
            if row_translate is None:
                continue
            row_adj_translate = next(
                (
                    candidate for candidate in translate_calls
                    if candidate.start > row_translate.end
                    and candidate.value_arg == row_adj_local
                ),
                None,
            )
            if row_adj_translate is None:
                continue
            cases.append(
                _RegisterSteeringMixedPcodeFprLifetimeCase(
                    row_local=row_local,
                    row_adj_local=row_adj_local,
                    row_adj_owner_local=owner.lhs,
                    row_adj_decl_type=row_adj_decl.type_name,
                    owner_assignment=owner,
                    row_adj_assignment_start=row_adj_start,
                    row_adj_assignment_end=row_adj_end,
                    row_adj_assignment_line=row_adj_line,
                    digit_call=call,
                    row_translate_call=row_translate,
                    row_adj_translate_call=row_adj_translate,
                )
            )
            break
    return tuple(cases)


def _mixed_digit_callarg_replacement(
    body_text: str,
    case: _RegisterSteeringMixedPcodeFprLifetimeCase,
    digit_temp: str,
) -> str:
    call = case.digit_call
    between = _callarg_between_text(body_text, call)
    return (
        f"{call.indent}{call.call_arg_type} {digit_temp};\n"
        f"{call.indent}{digit_temp} = {call.call_arg_expr};\n"
        f"{between}"
        f"{_hsd_req_anim_call_line_with_arg(call, digit_temp)}"
    )


def _mixed_row_adj_temp_replacement(
    case: _RegisterSteeringMixedPcodeFprLifetimeCase,
    row_adj_temp: str,
) -> str:
    call = case.row_adj_translate_call
    return (
        f"{call.indent}{case.row_adj_decl_type} {row_adj_temp};\n"
        f"{call.indent}{row_adj_temp} = {case.row_adj_owner_local};\n"
        f"{_hsd_set_translate_y_line_with_arg(call, row_adj_temp)}"
    )


def _iter_mixed_pcode_fpr_lifetime_pressure_anchors(
    body_text: str,
    function_header_text: str = "",
) -> list[Anchor]:
    cases = _iter_mixed_pcode_fpr_lifetime_pressure_cases(
        body_text,
        function_header_text=function_header_text,
    )
    if not cases:
        return []
    searchable = _blank_literals_and_comments(body_text)
    anchors: list[Anchor] = []
    seen_spans: set[tuple[int, int, str]] = set()

    def append_anchor(
        *,
        case: _RegisterSteeringMixedPcodeFprLifetimeCase,
        strategy: str,
        span: tuple[int, int],
        replacement_text: str,
        row_adj_temp: str | None = None,
        digit_call_temp: str | None = None,
    ) -> None:
        span_text = body_text[span[0]:span[1]]
        key = (span[0], span[1], strategy)
        if (
            not span_text
            or span_text == replacement_text
            or body_text.count(span_text) != 1
            or key in seen_spans
        ):
            return
        seen_spans.add(key)
        anchors.append(
            Anchor(
                mutator_key="steer_mixed_pcode_fpr_lifetime_pressure",
                span=span,
                payload=_mixed_pcode_payload(
                    case=case,
                    strategy=strategy,
                    span_text=span_text,
                    replacement_text=replacement_text,
                    row_adj_temp=row_adj_temp,
                    digit_call_temp=digit_call_temp,
                ),
            )
        )

    for case in cases:
        occupied = searchable
        row_adj_temp = _fresh_register_steering_name(
            occupied,
            f"{case.row_adj_local}_call",
        )
        if row_adj_temp is not None:
            occupied += f"\n{row_adj_temp}\n"
        digit_temp = _fresh_register_steering_name(
            occupied,
            f"{case.digit_call.call_arg_operand}_call",
        )

        direct_line = _hsd_set_translate_y_line_with_arg(
            case.row_adj_translate_call,
            case.row_adj_owner_local,
        )
        append_anchor(
            case=case,
            strategy="mixed-row-adj-direct-translate",
            span=(case.row_adj_translate_call.start, case.row_adj_translate_call.end),
            replacement_text=direct_line,
        )

        if row_adj_temp is not None:
            row_adj_replacement = _mixed_row_adj_temp_replacement(case, row_adj_temp)
            append_anchor(
                case=case,
                strategy="mixed-row-adj-call-temp-split",
                span=(case.row_adj_translate_call.start, case.row_adj_translate_call.end),
                replacement_text=row_adj_replacement,
                row_adj_temp=row_adj_temp,
            )

        if digit_temp is not None:
            digit_replacement = _mixed_digit_callarg_replacement(
                body_text,
                case,
                digit_temp,
            )
            append_anchor(
                case=case,
                strategy="mixed-digit-callarg-fresh-local",
                span=(case.digit_call.assignment_start or case.digit_call.start, case.digit_call.end),
                replacement_text=digit_replacement,
                digit_call_temp=digit_temp,
            )

        if row_adj_temp is not None and digit_temp is not None:
            span = (
                case.digit_call.assignment_start or case.digit_call.start,
                case.row_adj_translate_call.end,
            )
            span_text = body_text[span[0]:span[1]]
            call_span = body_text[
                case.digit_call.assignment_start or case.digit_call.start
                : case.digit_call.end
            ]
            row_adj_call_line = case.row_adj_translate_call.line
            if span_text.count(call_span) == 1 and span_text.count(row_adj_call_line) == 1:
                replacement_text = span_text.replace(call_span, digit_replacement, 1)
                replacement_text = replacement_text.replace(
                    row_adj_call_line,
                    _mixed_row_adj_temp_replacement(case, row_adj_temp),
                    1,
                )
                append_anchor(
                    case=case,
                    strategy="mixed-composed-row-adj-plus-digit-callarg",
                    span=span,
                    replacement_text=replacement_text,
                    row_adj_temp=row_adj_temp,
                    digit_call_temp=digit_temp,
                )
    return anchors


def _top_level_assignment_records(
    body_text: str,
) -> tuple[tuple[int, int, int, str, re.Match[str]], ...]:
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    result: list[tuple[int, int, int, str, re.Match[str]]] = []
    for idx, (start, end, _end_with_newline, search_line) in enumerate(searchable_records):
        if idx >= len(records):
            continue
        if (depths[idx] if idx < len(depths) else 0) != 1:
            continue
        if records[idx][3] != search_line:
            continue
        match = _REGISTER_STEERING_ASSIGN_RE.match(search_line)
        if match is None:
            continue
        result.append((idx, start, end, records[idx][3], match))
    return tuple(result)


def _callarg_structural_digit_count(
    body_text: str,
) -> tuple[int, int, str, str] | None:
    for _idx, start, end, line, match in _top_level_assignment_records(body_text):
        if re.fullmatch(r"mn_GetDigitCount\s*\([^;{}]*\)", match.group("rhs").strip()):
            return start, end, line, match.group("lhs")
    return None


def _iter_callarg_structural_products(
    body_text: str,
    function_header_text: str,
) -> tuple[_RegisterSteeringFprProduct, ...]:
    products: list[_RegisterSteeringFprProduct] = []
    for idx, start, end, line, match in _top_level_assignment_records(body_text):
        lhs = match.group("lhs")
        product = _register_steering_product_expr(match.group("rhs"))
        if product is None:
            continue
        product_expr, operand_names, cast_operand_names = product
        if lhs in operand_names or _node_set_split_synthetic_name(lhs):
            continue
        if _single_fpr_decl_for_name(body_text, lhs) is None:
            continue
        if not _register_steering_product_has_fpr_operand_proof(
            body_text,
            function_header_text,
            operand_names,
            cast_operand_names,
        ):
            continue
        products.append(
            _RegisterSteeringFprProduct(
                idx=idx,
                start=start,
                end=end,
                line=line,
                indent=match.group("indent"),
                lhs=lhs,
                product_expr=product_expr,
                operand_names=operand_names,
                cast_operand_names=cast_operand_names,
            )
        )
    return tuple(products)


def _callarg_structural_product_handoff(
    body_text: str,
    product: _RegisterSteeringFprProduct,
) -> tuple[int, int, str, str] | None:
    for _idx, start, end, line, match in _top_level_assignment_records(body_text):
        if start <= product.end:
            continue
        if match.group("rhs").strip() != product.lhs:
            continue
        lhs = match.group("lhs")
        if _single_fpr_decl_for_name(body_text, lhs) is None:
            continue
        return start, end, line, lhs
    return None


def _callarg_structural_row_shape(
    body_text: str,
    before_offset: int,
) -> tuple[str, str, str] | None:
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    for idx, (start, _end, _end_with_newline, search_line) in enumerate(searchable_records):
        if idx >= len(records) or start >= before_offset:
            continue
        if (depths[idx] if idx < len(depths) else 0) != 1:
            continue
        assign = _REGISTER_STEERING_ASSIGN_RE.match(search_line)
        if assign is None:
            continue
        cast = _simple_fpr_cast_expr(assign.group("rhs"))
        if cast is None:
            continue
        _cast_expr, _cast_type, row_local = cast
        rowf_local = assign.group("lhs")
        if _single_fpr_decl_for_name(body_text, rowf_local) is None:
            continue
        if _counter_address_take_rejects(searchable, rowf_local):
            continue
        for jdx in range(idx + 1, len(searchable_records)):
            row_start, _row_end, _row_ewn, row_line = searchable_records[jdx]
            if row_start >= before_offset:
                break
            if (depths[jdx] if jdx < len(depths) else 0) != 1:
                continue
            scale_match = re.match(
                r"^[ \t]*(?P<row_offset>[A-Za-z_]\w*)\s*\*=\s*"
                + re.escape(rowf_local)
                + r"\s*;\s*$",
                row_line,
            )
            if scale_match is not None:
                return row_local, rowf_local, records[jdx][3]
    return None


def _callarg_structural_row_adj_assignment(
    body_text: str,
    owner: _RegisterSteeringFprOwnerAssignment,
) -> tuple[int, int, str, str] | None:
    for _idx, start, end, line, match in _top_level_assignment_records(body_text):
        if start <= owner.end:
            continue
        if match.group("rhs").strip() != owner.lhs:
            continue
        lhs = match.group("lhs")
        if _single_fpr_decl_for_name(body_text, lhs) is None:
            continue
        return start, end, line, lhs
    return None


def _find_loop_digit_assignment(
    body_text: str,
    call: _RegisterSteeringHsdReqAnimCallArg,
) -> tuple[int, int, str] | None:
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    call_depth = depths[call.idx] if call.idx < len(depths) else 0
    for idx in range(call.idx - 1, -1, -1):
        if idx >= len(records):
            continue
        start, end, _end_with_newline, search_line = searchable_records[idx]
        if not search_line.strip():
            continue
        depth = depths[idx] if idx < len(depths) else 0
        if depth < call_depth:
            return None
        if depth != call_depth:
            continue
        if _fpr_callarg_scan_barrier(search_line):
            return None
        assign = _REGISTER_STEERING_ASSIGN_RE.match(search_line)
        if assign is None:
            continue
        if assign.group("lhs") == call.call_arg_operand and re.fullmatch(
            r"mn_GetDigitAt\s*\([^;{}]*\)",
            assign.group("rhs").strip(),
        ):
            return start, end, records[idx][3]
    return None


def _find_existing_digit_callarg_assignment(
    body_text: str,
    call: _RegisterSteeringHsdReqAnimCallArg,
) -> tuple[int, int, str, str] | None:
    if (
        call.call_arg_local is not None
        and call.assignment_start is not None
        and call.assignment_end is not None
        and call.assignment_line is not None
    ):
        return (
            call.assignment_start,
            call.assignment_end,
            call.assignment_line,
            call.call_arg_local,
        )
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    call_depth = depths[call.idx] if call.idx < len(depths) else 0
    for idx in range(call.idx - 1, -1, -1):
        if idx >= len(records):
            continue
        start, end, _end_with_newline, search_line = searchable_records[idx]
        if not search_line.strip():
            continue
        depth = depths[idx] if idx < len(depths) else 0
        if depth < call_depth:
            return None
        if depth != call_depth:
            continue
        if _fpr_callarg_scan_barrier(search_line):
            return None
        assign = _REGISTER_STEERING_ASSIGN_RE.match(search_line)
        if assign is None:
            continue
        cast = _simple_fpr_cast_expr(assign.group("rhs"))
        if cast is None:
            continue
        _cast_expr, _cast_type, operand = cast
        local = assign.group("lhs")
        if operand != call.call_arg_operand:
            continue
        if _single_fpr_decl_for_name(body_text, local) is None:
            return None
        if _counter_address_take_rejects(searchable, local):
            return None
        between = searchable[end:call.start]
        if _region_assigns_any(between, (local, operand)):
            return None
        return start, end, records[idx][3], local
    return None


def _line_end_with_newline(body_text: str, end: int) -> int:
    return end + 1 if end < len(body_text) and body_text[end:end + 1] == "\n" else end


def _callarg_loop_for_call(
    body_text: str,
    call: _RegisterSteeringHsdReqAnimCallArg,
) -> _RegisterSteeringLoop | None:
    for loop in _register_steering_loop_blocks(body_text):
        if loop.start <= call.start < loop.end:
            return loop
    return None


def _loop_body_insert_offset(
    body_text: str,
    *,
    loop_start: int,
    loop_end: int,
) -> int | None:
    line_end = body_text.find("\n", loop_start, loop_end)
    if line_end < 0:
        return None
    return line_end + 1


def _callarg_local_kind(
    call: _RegisterSteeringHsdReqAnimCallArg,
    *,
    rowf_local: str,
    callarg_local: str,
) -> str:
    if call.call_arg_local is None:
        return "inline-cast"
    if callarg_local == rowf_local:
        return "rowf-reuse"
    return "fresh-existing"


def _callarg_matching_assignment_records(
    body_text: str,
    call: _RegisterSteeringHsdReqAnimCallArg,
    *,
    callarg_local: str,
) -> tuple[tuple[int, int, str], ...]:
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    call_depth = depths[call.idx] if call.idx < len(depths) else 0
    matches: list[tuple[int, int, str]] = []
    for idx in range(call.idx - 1, -1, -1):
        if idx >= len(records):
            continue
        start, end, _end_with_newline, search_line = searchable_records[idx]
        if not search_line.strip():
            continue
        depth = depths[idx] if idx < len(depths) else 0
        if depth < call_depth:
            break
        if depth != call_depth:
            continue
        if _fpr_callarg_scan_barrier(search_line):
            break
        assign = _REGISTER_STEERING_ASSIGN_RE.match(search_line)
        if assign is None or assign.group("lhs") != callarg_local:
            continue
        cast = _simple_fpr_cast_expr(assign.group("rhs"))
        if cast is None:
            continue
        _cast_expr, _cast_type, operand = cast
        if operand == call.call_arg_operand:
            matches.append((start, end, records[idx][3]))
    return tuple(reversed(matches))


def _callarg_local_used_after_loop(
    body_text: str,
    *,
    callarg_local: str,
    loop_end: int,
) -> bool:
    searchable = _blank_literals_and_comments(body_text)
    return bool(_identifier_mentions(searchable[loop_end:], callarg_local))


def _callarg_line_independent_from_product_count(
    case: _RegisterSteeringCallargLocalStructuralCase,
) -> bool:
    product_block = "\n".join((
        case.product.line,
        case.product_handoff_line,
    ))
    count_line = case.digit_count_line
    return not (
        _identifier_mentions(product_block, case.digit_count_local)
        or _identifier_mentions(count_line, case.product.lhs)
        or _identifier_mentions(count_line, case.product_handoff_local)
    )


def _move_statement_before(
    body_text: str,
    *,
    span: tuple[int, int],
    moving: tuple[int, int],
    before_start: int,
) -> str | None:
    span_start, span_end = span
    moving_start, moving_end = moving
    moving_end = _line_end_with_newline(body_text, moving_end)
    span_end = _line_end_with_newline(body_text, span_end)
    if not (span_start <= moving_start < moving_end <= span_end):
        return None
    if not (span_start <= before_start <= span_end):
        return None
    if moving_start == before_start:
        return None
    segment = body_text[span_start:span_end]
    moving_text = body_text[moving_start:moving_end]
    rel_moving_start = moving_start - span_start
    rel_moving_end = moving_end - span_start
    rel_before = before_start - span_start
    without = segment[:rel_moving_start] + segment[rel_moving_end:]
    if rel_moving_start < rel_before:
        rel_before -= len(moving_text)
    replacement = without[:rel_before] + moving_text + without[rel_before:]
    return replacement if replacement != segment else None


def _prefix_nonblank_lines(text: str, prefix: str) -> str:
    return "".join(
        f"{prefix}{line}" if line.strip() else line
        for line in text.splitlines(keepends=True)
    )


def _callarg_structural_call_statement_spans(
    body_text: str,
    *,
    start: int,
    end: int,
    callee: str,
) -> tuple[tuple[int, int], ...]:
    searchable = _blank_literals_and_comments(body_text)
    segment = searchable[start:end]
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"\b" + re.escape(callee) + r"\s*\(", segment):
        line_start = segment.rfind("\n", 0, match.start()) + 1
        stmt_end = segment.find(";", match.end())
        if stmt_end < 0:
            return ()
        spans.append((start + line_start, start + stmt_end + 1))
    return tuple(spans)


def _callarg_structural_unique_call_statement(
    body_text: str,
    *,
    start: int,
    end: int,
    callee: str,
) -> tuple[int, int] | None:
    spans = _callarg_structural_call_statement_spans(
        body_text,
        start=start,
        end=end,
        callee=callee,
    )
    return spans[0] if len(spans) == 1 else None


def _callarg_fresh_existing_schedule_replacement(
    body_text: str,
    case: _RegisterSteeringCallargLocalStructuralCase,
    *,
    insert_assignment_after: int,
) -> str | None:
    decl = case.callarg_decl
    if (
        decl is None
        or case.callarg_assignment_start is None
        or case.callarg_assignment_end is None
    ):
        return None
    loop_insert = _loop_body_insert_offset(
        body_text,
        loop_start=case.loop_start,
        loop_end=case.loop_end,
    )
    if loop_insert is None or loop_insert > case.callarg_assignment_start:
        return None
    assignment_end = _line_end_with_newline(
        body_text,
        case.callarg_assignment_end,
    )
    insert_after = _line_end_with_newline(body_text, insert_assignment_after)
    if not (assignment_end <= insert_after <= case.digit_call.start):
        return None
    crossed_text = body_text[assignment_end:insert_after]
    if _identifier_mentions(_blank_literals_and_comments(crossed_text), case.callarg_local):
        return None
    before_assignment = body_text[loop_insert:case.callarg_assignment_start]
    between_assignment_and_call = body_text[assignment_end:case.digit_call.start]
    insert_rel = insert_after - assignment_end
    assignment_text = body_text[case.callarg_assignment_start:assignment_end]
    scheduled_between = (
        between_assignment_and_call[:insert_rel]
        + assignment_text
        + between_assignment_and_call[insert_rel:]
    )
    return (
        body_text[decl.end_with_newline:loop_insert]
        + f"{case.digit_call.indent}{decl.type_name} {case.callarg_local};\n"
        + before_assignment
        + scheduled_between
        + body_text[case.digit_call.start:case.digit_call.end]
    )


def _callarg_local_structural_analysis(
    body_text: str,
    function_header_text: str = "",
) -> tuple[tuple[_RegisterSteeringCallargLocalStructuralCase, ...], dict[str, Any]]:
    rowf_locals: set[str] = set()
    call_arg_locals: set[str] = set()
    call_arg_local_kinds: set[str] = set()
    rejection_reasons: set[str] = set()
    has_existing_fresh_callarg_local = False
    if re.search(r"(?m)^[ \t]*#", body_text):
        rejection_reasons.add("preprocessor-directive-in-span")
        return (), {
            "rowf_locals": (),
            "call_arg_locals": (),
            "call_arg_local_kinds": (),
            "has_existing_fresh_callarg_local": False,
            "rejection_reasons": tuple(sorted(rejection_reasons)),
        }
    searchable = _blank_literals_and_comments(body_text)
    calls = _iter_hsd_jobj_req_anim_all_call_args(
        body_text,
        function_header_text=function_header_text,
    )
    if len(calls) != 1:
        raw_call_count = len(re.findall(r"\bHSD_JObjReqAnimAll\s*\(", body_text))
        if raw_call_count > 1:
            rejection_reasons.add("ambiguous-hsd-jobj-req-anim-all-calls")
        elif raw_call_count == 1:
            rejection_reasons.add("fresh-callarg-local-continuation-unavailable")
        else:
            rejection_reasons.add("source-pattern-not-found")
        return (), {
            "rowf_locals": (),
            "call_arg_locals": (),
            "call_arg_local_kinds": (),
            "has_existing_fresh_callarg_local": False,
            "rejection_reasons": tuple(sorted(rejection_reasons)),
        }
    call = calls[0]
    digit_count = _callarg_structural_digit_count(body_text)
    if digit_count is None:
        rejection_reasons.add("source-pattern-not-found")
        return (), {
            "rowf_locals": (),
            "call_arg_locals": (),
            "call_arg_local_kinds": (),
            "has_existing_fresh_callarg_local": False,
            "rejection_reasons": tuple(sorted(rejection_reasons)),
        }
    digit_count_start, digit_count_end, digit_count_line, digit_count_local = digit_count
    products = _iter_callarg_structural_products(
        body_text,
        function_header_text,
    )
    assignments = _iter_pcode_only_fpr_fsubs_cast_owner_assignments(
        body_text,
        function_header_text=function_header_text,
    )
    digit_assignment = _find_loop_digit_assignment(body_text, call)
    callarg_assignment = _find_existing_digit_callarg_assignment(body_text, call)
    if digit_assignment is None or callarg_assignment is None:
        rejection_reasons.add("fresh-callarg-local-continuation-unavailable")
        return (), {
            "rowf_locals": (),
            "call_arg_locals": (),
            "call_arg_local_kinds": (),
            "has_existing_fresh_callarg_local": False,
            "rejection_reasons": tuple(sorted(rejection_reasons)),
        }
    callarg_start, callarg_end, callarg_line, callarg_local = callarg_assignment
    if _counter_address_take_rejects(searchable, callarg_local):
        rejection_reasons.add("callarg-local-address-taken")
        return (), {
            "rowf_locals": (),
            "call_arg_locals": (callarg_local,),
            "call_arg_local_kinds": (),
            "has_existing_fresh_callarg_local": False,
            "rejection_reasons": tuple(sorted(rejection_reasons)),
        }
    loop = _callarg_loop_for_call(body_text, call)
    if loop is None:
        rejection_reasons.add("fresh-callarg-local-continuation-unavailable")
        return (), {
            "rowf_locals": (),
            "call_arg_locals": (callarg_local,),
            "call_arg_local_kinds": (),
            "has_existing_fresh_callarg_local": False,
            "rejection_reasons": tuple(sorted(rejection_reasons)),
        }
    cases: list[_RegisterSteeringCallargLocalStructuralCase] = []
    for product in products:
        handoff = _callarg_structural_product_handoff(body_text, product)
        if handoff is None:
            continue
        (
            product_handoff_start,
            product_handoff_end,
            product_handoff_line,
            product_handoff_local,
        ) = handoff
        row_shape = _callarg_structural_row_shape(
            body_text,
            before_offset=call.start,
        )
        if row_shape is None:
            continue
        row_local, rowf_local, row_scale_line = row_shape
        rowf_locals.add(rowf_local)
        call_arg_kind = _callarg_local_kind(
            call,
            rowf_local=rowf_local,
            callarg_local=callarg_local,
        )
        call_arg_locals.add(callarg_local)
        call_arg_local_kinds.add(call_arg_kind)
        has_existing_fresh_callarg_local = (
            has_existing_fresh_callarg_local or call_arg_kind == "fresh-existing"
        )
        matching_assignments = _callarg_matching_assignment_records(
            body_text,
            call,
            callarg_local=callarg_local,
        )
        if len(matching_assignments) > 1:
            rejection_reasons.add("ambiguous-callarg-assignment")
            continue
        for owner in assignments:
            if owner.kind != "fsubs-owner" or owner.lhs in {rowf_local, callarg_local}:
                continue
            row_adj = _callarg_structural_row_adj_assignment(body_text, owner)
            if row_adj is None:
                continue
            row_adj_start, row_adj_end, row_adj_line, row_adj_local = row_adj
            if not (
                digit_count_end <= call.start
                and product.end <= call.start
                and product_handoff_end <= call.start
                and owner.end <= call.start
                and row_adj_end <= call.start
            ):
                continue
            if _region_assigns_any(
                searchable[row_adj_end:callarg_start],
                (
                    product.lhs,
                    row_local,
                    rowf_local,
                    owner.lhs,
                    row_adj_local,
                ),
            ):
                rejection_reasons.add("callarg-local-assigned-between")
                continue
            callarg_decl = _single_fpr_decl_for_name(body_text, callarg_local)
            cases.append(
                _RegisterSteeringCallargLocalStructuralCase(
                    digit_count_start=digit_count_start,
                    digit_count_end=digit_count_end,
                    digit_count_line=digit_count_line,
                    digit_count_local=digit_count_local,
                    product=product,
                    product_handoff_start=product_handoff_start,
                    product_handoff_end=product_handoff_end,
                    product_handoff_line=product_handoff_line,
                    product_handoff_local=product_handoff_local,
                    row_cast_line=next(
                        line
                        for _idx, _start, _end, line, match in _top_level_assignment_records(body_text)
                        if match.group("lhs") == rowf_local
                        and _simple_fpr_cast_expr(match.group("rhs")) is not None
                    ),
                    row_local=row_local,
                    rowf_local=rowf_local,
                    row_scale_line=row_scale_line,
                    row_adj_owner_assignment=owner,
                    row_adj_start=row_adj_start,
                    row_adj_end=row_adj_end,
                    row_adj_line=row_adj_line,
                    row_adj_local=row_adj_local,
                    digit_call=call,
                    digit_assignment_start=digit_assignment[0],
                    digit_assignment_end=digit_assignment[1],
                    digit_assignment_line=digit_assignment[2],
                    callarg_assignment_start=callarg_start,
                    callarg_assignment_end=callarg_end,
                    callarg_assignment_line=callarg_line,
                    callarg_local=callarg_local,
                    callarg_local_kind=call_arg_kind,
                    callarg_decl=callarg_decl,
                    loop_start=loop.start,
                    loop_end=loop.end,
                ),
            )
    if not cases and has_existing_fresh_callarg_local and not rejection_reasons:
        rejection_reasons.add("fresh-callarg-local-continuation-unavailable")
    return tuple(cases), {
        "rowf_locals": tuple(sorted(rowf_locals)),
        "call_arg_locals": tuple(sorted(call_arg_locals)),
        "call_arg_local_kinds": tuple(sorted(call_arg_local_kinds)),
        "has_existing_fresh_callarg_local": has_existing_fresh_callarg_local,
        "rejection_reasons": tuple(sorted(rejection_reasons)),
    }


def _callarg_local_structural_match_diagnostics(
    body_text: str,
    function_header_text: str = "",
) -> dict[str, Any]:
    _cases, diagnostics = _callarg_local_structural_analysis(
        body_text,
        function_header_text=function_header_text,
    )
    return diagnostics


def _iter_callarg_local_structural_cases(
    body_text: str,
    function_header_text: str = "",
) -> tuple[_RegisterSteeringCallargLocalStructuralCase, ...]:
    cases, _diagnostics = _callarg_local_structural_analysis(
        body_text,
        function_header_text=function_header_text,
    )
    return cases


def _callarg_local_structural_payload(
    *,
    case: _RegisterSteeringCallargLocalStructuralCase,
    strategy: str,
    span_text: str,
    replacement_text: str,
    uses_fresh_local: bool,
    call_arg_local: str,
    preserves_existing_callarg_local: bool,
    digit_assignment_schedule: str | None = None,
    handoff_local: str | None = None,
) -> dict[str, Any]:
    product_order = (
        "product-after-digit-count"
        if case.product.start > case.digit_count_start
        else "product-before-digit-count"
    )
    payload: dict[str, Any] = {
        "span_text": span_text,
        "replacement_text": replacement_text,
        "strategy": strategy,
        "call_arg_local": call_arg_local,
        "call_arg_local_kind": case.callarg_local_kind,
        "call_arg_operand": case.digit_call.call_arg_operand,
        "product_order": product_order,
        "digit_count_order": product_order,
        "preserves_existing_callarg_local": preserves_existing_callarg_local,
        "uses_fresh_local": uses_fresh_local,
        "product_local": case.product.lhs,
        "rowf_local": case.rowf_local,
        "row_adj_owner_local": case.row_adj_owner_assignment.lhs,
        "source_regions": (
            f"digit count: {case.digit_count_line.strip()}",
            f"column product: {case.product.line.strip()}",
            f"row owner fsubs: {case.row_adj_owner_assignment.line.strip()}",
            f"digit callarg: {case.callarg_assignment_line.strip() if case.callarg_assignment_line else case.digit_call.arg_text}",
        ),
    }
    if digit_assignment_schedule is not None:
        payload["digit_assignment_schedule"] = digit_assignment_schedule
    if handoff_local is not None:
        payload["handoff_local"] = handoff_local
    return payload


def _replace_line_once(text: str, old: str, new: str) -> str | None:
    if text.count(old) != 1:
        return None
    return text.replace(old, new, 1)


def _iter_callarg_local_structural_repair_anchors(
    body_text: str,
    function_header_text: str = "",
) -> list[Anchor]:
    cases = _iter_callarg_local_structural_cases(
        body_text,
        function_header_text=function_header_text,
    )
    if not cases:
        return []
    anchors: list[Anchor] = []
    searchable = _blank_literals_and_comments(body_text)
    seen: set[tuple[int, int, str]] = set()

    def append_anchor(
        *,
        case: _RegisterSteeringCallargLocalStructuralCase,
        strategy: str,
        span: tuple[int, int],
        replacement_text: str,
        uses_fresh_local: bool,
        call_arg_local: str,
        preserves_existing_callarg_local: bool,
        digit_assignment_schedule: str | None = None,
        handoff_local: str | None = None,
    ) -> None:
        span_text = body_text[span[0]:span[1]]
        key = (span[0], span[1], strategy)
        if (
            not span_text
            or span_text == replacement_text
            or body_text.count(span_text) != 1
            or key in seen
        ):
            return
        seen.add(key)
        anchors.append(
            Anchor(
                mutator_key="steer_callarg_local_preserving_structural_repair",
                span=span,
                payload=_callarg_local_structural_payload(
                    case=case,
                    strategy=strategy,
                    span_text=span_text,
                    replacement_text=replacement_text,
                    uses_fresh_local=uses_fresh_local,
                    call_arg_local=call_arg_local,
                    preserves_existing_callarg_local=preserves_existing_callarg_local,
                    digit_assignment_schedule=digit_assignment_schedule,
                    handoff_local=handoff_local,
                ),
            )
        )

    for case in cases:
        if case.callarg_local_kind == "fresh-existing":
            if (
                _callarg_line_independent_from_product_count(case)
                and case.callarg_assignment_start is not None
                and case.callarg_assignment_end is not None
                and case.callarg_decl is not None
            ):
                count_product_span = (
                    min(case.product.start, case.digit_count_start),
                    max(
                        _line_end_with_newline(body_text, case.product_handoff_end),
                        _line_end_with_newline(body_text, case.digit_count_end),
                    ),
                )
                count_before_handoff = _move_statement_before(
                    body_text,
                    span=count_product_span,
                    moving=(case.digit_count_start, case.digit_count_end),
                    before_start=case.product_handoff_start,
                )
                if count_before_handoff is not None:
                    append_anchor(
                        case=case,
                        strategy="continue-existing-fresh-callarg-local",
                        span=count_product_span,
                        replacement_text=count_before_handoff,
                        uses_fresh_local=True,
                        call_arg_local=case.callarg_local,
                        preserves_existing_callarg_local=True,
                    )

                count_before_product = _move_statement_before(
                    body_text,
                    span=count_product_span,
                    moving=(case.digit_count_start, case.digit_count_end),
                    before_start=case.product.start,
                )
                if count_before_product is not None:
                    append_anchor(
                        case=case,
                        strategy="fresh-local-product-count-order-swap",
                        span=count_product_span,
                        replacement_text=count_before_product,
                        uses_fresh_local=True,
                        call_arg_local=case.callarg_local,
                        preserves_existing_callarg_local=True,
                    )

                callarg_used_after_loop = _callarg_local_used_after_loop(
                    body_text,
                    callarg_local=case.callarg_local,
                    loop_end=case.loop_end,
                )
                assignment_end = _line_end_with_newline(
                    body_text,
                    case.callarg_assignment_end,
                )
                load_stmt = _callarg_structural_unique_call_statement(
                    body_text,
                    start=assignment_end,
                    end=case.digit_call.start,
                    callee="HSD_JObjLoadJoint",
                )
                add_stmt = _callarg_structural_unique_call_statement(
                    body_text,
                    start=assignment_end,
                    end=case.digit_call.start,
                    callee="HSD_JObjAddAnimAll",
                )
                if not callarg_used_after_loop:
                    decl = case.callarg_decl
                    decl_span_end = decl.end_with_newline
                    loop_insert = _loop_body_insert_offset(
                        body_text,
                        loop_start=case.loop_start,
                        loop_end=case.loop_end,
                    )
                    if (
                        loop_insert is not None
                        and loop_insert <= case.callarg_assignment_start
                    ):
                        demote_span = (decl.start, case.callarg_assignment_end)
                        demote_replacement = (
                            body_text[decl_span_end:loop_insert]
                            + f"{case.digit_call.indent}{decl.type_name} "
                            f"{case.callarg_local};\n"
                            f"{body_text[loop_insert:case.callarg_assignment_end]}"
                        )
                        append_anchor(
                            case=case,
                            strategy="fresh-local-decl-demote-to-loop",
                            span=demote_span,
                            replacement_text=demote_replacement,
                            uses_fresh_local=True,
                            call_arg_local=case.callarg_local,
                            preserves_existing_callarg_local=True,
                            digit_assignment_schedule=(
                                "before-load" if load_stmt is not None else None
                            ),
                        )

                    schedule_span = (decl.start, case.digit_call.end)
                    if load_stmt is not None:
                        after_load = _callarg_fresh_existing_schedule_replacement(
                            body_text,
                            case,
                            insert_assignment_after=load_stmt[1],
                        )
                        if after_load is not None:
                            append_anchor(
                                case=case,
                                strategy="fresh-local-call-schedule-after-load",
                                span=schedule_span,
                                replacement_text=after_load,
                                uses_fresh_local=True,
                                call_arg_local=case.callarg_local,
                                preserves_existing_callarg_local=True,
                                digit_assignment_schedule="after-load",
                            )
                    if add_stmt is not None:
                        after_add = _callarg_fresh_existing_schedule_replacement(
                            body_text,
                            case,
                            insert_assignment_after=add_stmt[1],
                        )
                        if after_add is not None:
                            append_anchor(
                                case=case,
                                strategy="fresh-local-call-schedule-after-add",
                                span=schedule_span,
                                replacement_text=after_add,
                                uses_fresh_local=True,
                                call_arg_local=case.callarg_local,
                                preserves_existing_callarg_local=True,
                                digit_assignment_schedule="after-add",
                            )

                    block = (
                        f"{case.digit_call.indent}{{\n"
                        f"{case.digit_call.indent}    {case.callarg_decl.type_name} {case.callarg_local};\n"
                        f"{case.digit_call.indent}    {case.callarg_local} = "
                        f"{case.digit_call.call_arg_expr};\n"
                        f"{_prefix_nonblank_lines(body_text[_line_end_with_newline(body_text, case.callarg_assignment_end):case.digit_call.start], '    ')}"
                        f"{case.digit_call.indent}    "
                        f"{case.digit_call.callee}({', '.join((case.digit_call.args[0], case.callarg_local, *case.digit_call.args[2:]))});\n"
                        f"{case.digit_call.indent}}}"
                    )
                    append_anchor(
                        case=case,
                        strategy="fresh-local-block-scope-equivalent",
                        span=(case.callarg_assignment_start, case.digit_call.end),
                        replacement_text=block,
                        uses_fresh_local=True,
                        call_arg_local=case.callarg_local,
                        preserves_existing_callarg_local=True,
                    )
                handoff_local = "digit_call_fpr"
                if not _identifier_mentions(searchable, handoff_local):
                    handoff_type = case.callarg_decl.type_name
                    top_insert = _insert_after_top_level_fpr_decls(
                        body_text,
                        min(case.product.start, case.digit_count_start),
                    )
                    handoff_call = _hsd_req_anim_call_line_with_arg(
                        case.digit_call,
                        handoff_local,
                    )
                    if top_insert is not None:
                        top_level = (
                            f"{case.digit_call.indent[:4]}{handoff_type} {handoff_local};\n"
                            f"{body_text[top_insert:case.digit_call.start]}"
                            f"{case.digit_call.indent}{handoff_local} = "
                            f"{case.callarg_local};\n"
                            f"{handoff_call}"
                        )
                        append_anchor(
                            case=case,
                            strategy="fresh-local-callarg-handoff-top",
                            span=(top_insert, case.digit_call.end),
                            replacement_text=top_level,
                            uses_fresh_local=True,
                            call_arg_local=case.callarg_local,
                            preserves_existing_callarg_local=True,
                            handoff_local=handoff_local,
                        )

                    block_handoff = (
                        f"{case.digit_call.indent}{{\n"
                        f"{case.digit_call.indent}    {handoff_type} {handoff_local};\n"
                        f"{case.digit_call.indent}    {handoff_local} = "
                        f"{case.callarg_local};\n"
                        f"{case.digit_call.indent}    {case.digit_call.callee}"
                        f"({', '.join((case.digit_call.args[0], handoff_local, *case.digit_call.args[2:]))});\n"
                        f"{case.digit_call.indent}}}"
                    )
                    append_anchor(
                        case=case,
                        strategy="fresh-local-callarg-handoff-block",
                        span=(case.digit_call.start, case.digit_call.end),
                        replacement_text=block_handoff,
                        uses_fresh_local=True,
                        call_arg_local=case.callarg_local,
                        preserves_existing_callarg_local=True,
                        handoff_local=handoff_local,
                    )
            continue

        region_start = min(case.digit_count_start, case.product.start)
        region_end = case.digit_call.end
        region_text = body_text[region_start:region_end]

        retain_line = _hsd_req_anim_call_line_with_arg(
            case.digit_call,
            case.callarg_local,
        )
        retain_region = _replace_line_once(
            region_text,
            case.digit_call.line,
            retain_line,
        )
        if retain_region is not None:
            append_anchor(
                case=case,
                strategy="retain-existing-rowf-callarg-h004-order",
                span=(region_start, region_end),
                replacement_text=retain_region,
                uses_fresh_local=False,
                call_arg_local=case.callarg_local,
                preserves_existing_callarg_local=True,
            )

        fresh_local = "digit_frame_fpr"
        if not _identifier_mentions(searchable, fresh_local):
            insert_after = _insert_after_top_level_fpr_decls(body_text, region_start)
            if insert_after is not None:
                fresh_start = insert_after
                fresh_region = body_text[fresh_start:region_end]
                fresh_assignment = (
                    f"{case.digit_call.indent}{fresh_local} = "
                    f"{case.digit_call.call_arg_expr};"
                )
                if case.callarg_assignment_line is not None:
                    fresh_region = fresh_region.replace(
                        case.callarg_assignment_line,
                        fresh_assignment,
                        1,
                    )
                else:
                    fresh_region = fresh_region.replace(
                        case.digit_call.line,
                        f"{fresh_assignment}\n{case.digit_call.line}",
                        1,
                    )
                fresh_region = fresh_region.replace(
                    case.digit_call.line,
                    _hsd_req_anim_call_line_with_arg(case.digit_call, fresh_local),
                    1,
                )
                fresh_region = (
                    f"{case.digit_call.indent[:4]}f32 {fresh_local};\n"
                    f"{fresh_region}"
                )
                append_anchor(
                    case=case,
                    strategy="fresh-loop-callarg-local",
                    span=(fresh_start, region_end),
                    replacement_text=fresh_region,
                    uses_fresh_local=True,
                    call_arg_local=fresh_local,
                    preserves_existing_callarg_local=False,
                )

            block = (
                f"{case.digit_call.indent}{{\n"
                f"{case.digit_call.indent}    f32 {fresh_local};\n"
                f"{case.digit_call.indent}    {fresh_local} = "
                f"{case.digit_call.call_arg_expr};\n"
                f"{case.digit_call.indent}    "
                f"{case.digit_call.callee}({', '.join((case.digit_call.args[0], fresh_local, *case.digit_call.args[2:]))});\n"
                f"{case.digit_call.indent}}}"
            )
            append_anchor(
                case=case,
                strategy="block-scoped-callarg-local",
                span=(case.digit_call.start, case.digit_call.end),
                replacement_text=block,
                uses_fresh_local=True,
                call_arg_local=fresh_local,
                preserves_existing_callarg_local=False,
            )
    return anchors


def _iter_coupled_fpr_product_callarg_repair_anchors(
    body_text: str,
    function_header_text: str = "",
) -> list[Anchor]:
    if re.search(r"(?m)^[ \t]*#", body_text):
        return []
    products = _iter_fpr_product_assignments(body_text, function_header_text)
    if not products:
        return []
    calls = _iter_hsd_jobj_req_anim_all_call_args(
        body_text,
        function_header_text,
    )
    if not calls:
        return []
    searchable = _blank_literals_and_comments(body_text)
    anchors: list[Anchor] = []

    for product in products:
        if not product.cast_operand_names:
            continue
        product_type = _fpr_product_decl_type(body_text, product)
        if product_type is None:
            continue
        cast_operand = product.cast_operand_names[0]
        cast = _cast_term_for_operand(product.product_expr, cast_operand)
        if cast is None:
            continue
        cast_expr, cast_type = cast
        replacement_product_expr = product.product_expr.replace(cast_expr, "{cast_temp}", 1)
        if replacement_product_expr == product.product_expr:
            continue
        for call in calls:
            if call.start <= product.end:
                continue
            insert_after = _insert_after_top_level_fpr_decls(
                body_text,
                product.start,
            )
            if insert_after is None:
                continue
            span_text = body_text[insert_after:call.end]
            if body_text.count(span_text) != 1:
                continue
            if body_text.count(product.line) != 1 or body_text.count(call.line) != 1:
                continue
            if call.assignment_line is not None and body_text.count(call.assignment_line) != 1:
                continue
            prefix = body_text[insert_after:product.start]
            between = body_text[product.end:call.start]

            occupied = searchable
            cast_temp = _fresh_register_steering_name(occupied, cast_operand)
            if cast_temp is not None:
                occupied += f"\n{cast_temp}\n"
            product_temp = _fresh_register_steering_name(occupied, f"{product.lhs}_product")
            if product_temp is not None:
                occupied += f"\n{product_temp}\n"
            call_stem = call.call_arg_local or call.call_arg_operand
            call_temp = _fresh_register_steering_name(occupied, f"{call_stem}_call")
            if call_temp is None:
                continue

            def append_variant(
                *,
                strategy_suffix: str,
                decls: tuple[tuple[str, str], ...],
                product_lines: tuple[str, ...],
                call_prefer_direct_cast: bool,
                product_temp_local: str | None,
                cast_temp_local: str | None,
            ) -> None:
                call_text = _coupled_call_temp_assignment(
                    call,
                    call_temp,
                    prefer_direct_cast=call_prefer_direct_cast,
                )
                if call_text is None:
                    return
                decl_text = "".join(
                    f"{product.indent}{decl_type} {decl_name};\n"
                    for decl_type, decl_name in decls
                )
                replacement_text = (
                    f"{decl_text}"
                    f"{prefix}"
                    f"{chr(10).join(product_lines)}"
                    f"{between}"
                    f"{call_text}"
                )
                if replacement_text == span_text:
                    return
                strategy = (
                    f"{product.lhs}-product-conversion-plus-"
                    f"{call.callee}-digit-conversion-{strategy_suffix}"
                )
                anchors.append(
                    Anchor(
                        mutator_key="steer_coupled_fpr_product_callarg_repair",
                        span=(insert_after, call.end),
                        payload=_coupled_fpr_payload(
                            strategy=strategy,
                            span_text=span_text,
                            replacement_text=replacement_text,
                            product=product,
                            product_temp=product_temp_local,
                            cast_expr=cast_expr if cast_temp_local is not None else None,
                            cast_temp=cast_temp_local,
                            call=call,
                            call_temp=call_temp,
                        ),
                    )
                )

            if cast_temp is not None and product_temp is not None:
                append_variant(
                    strategy_suffix="cast-product-call-temp",
                    decls=(
                        (cast_type, cast_temp),
                        (product_type, product_temp),
                        (call.call_arg_type, call_temp),
                    ),
                    product_lines=(
                        f"{product.indent}{cast_temp} = {cast_expr};",
                        f"{product.indent}{product_temp} = "
                        f"{replacement_product_expr.format(cast_temp=cast_temp)};",
                        f"{product.indent}{product.lhs} = {product_temp};",
                    ),
                    call_prefer_direct_cast=False,
                    product_temp_local=product_temp,
                    cast_temp_local=cast_temp,
                )

            if product_temp is not None:
                append_variant(
                    strategy_suffix="product-temp-call-copy",
                    decls=(
                        (product_type, product_temp),
                        (call.call_arg_type, call_temp),
                    ),
                    product_lines=(
                        f"{product.indent}{product_temp} = {product.product_expr};",
                        f"{product.indent}{product.lhs} = {product_temp};",
                    ),
                    call_prefer_direct_cast=False,
                    product_temp_local=product_temp,
                    cast_temp_local=None,
                )

            if cast_temp is not None:
                append_variant(
                    strategy_suffix="cast-temp-direct-call-cast",
                    decls=(
                        (cast_type, cast_temp),
                        (call.call_arg_type, call_temp),
                    ),
                    product_lines=(
                        f"{product.indent}{cast_temp} = {cast_expr};",
                        f"{product.indent}{product.lhs} = "
                        f"{replacement_product_expr.format(cast_temp=cast_temp)};",
                    ),
                    call_prefer_direct_cast=True,
                    product_temp_local=None,
                    cast_temp_local=cast_temp,
                )
            break
    return anchors


def _iter_fpr_product_temp_split_anchors(
    body_text: str,
    products: tuple[_RegisterSteeringFprProduct, ...],
) -> list[Anchor]:
    searchable = _blank_literals_and_comments(body_text)
    anchors: list[Anchor] = []
    for product in products:
        decl_type = _fpr_product_decl_type(body_text, product)
        if decl_type is None:
            continue
        insert_after = _insert_after_top_level_fpr_decls(body_text, product.start)
        if insert_after is None:
            continue
        temp_name = _fpr_product_temp_name(searchable, product)
        if temp_name is None:
            continue
        span_text = body_text[insert_after:product.end]
        if body_text.count(span_text) != 1:
            continue
        prefix = body_text[insert_after:product.start]
        replacement_text = (
            f"{product.indent}{decl_type} {temp_name};\n"
            f"{prefix}"
            f"{product.indent}{temp_name} = {product.product_expr};\n"
            f"{product.indent}{product.lhs} = {temp_name};"
        )
        anchors.append(
            Anchor(
                mutator_key="steer_fpr_product_temp_split",
                span=(insert_after, product.end),
                payload={
                    "span_text": span_text,
                    "replacement_text": replacement_text,
                    "strategy": "fpr-product-temp-split",
                    "product_local": product.lhs,
                    "product_expr": product.product_expr,
                    "temp_local": temp_name,
                },
            )
        )
    return anchors


def _iter_fpr_paired_product_temp_split_anchors(
    body_text: str,
    products: tuple[_RegisterSteeringFprProduct, ...],
) -> list[Anchor]:
    searchable = _blank_literals_and_comments(body_text)
    anchors: list[Anchor] = []
    for index, first in enumerate(products):
        for second in products[index + 1:]:
            if first.indent != second.indent or second.start <= first.end:
                continue
            first_type = _fpr_product_decl_type(body_text, first)
            second_type = _fpr_product_decl_type(body_text, second)
            if first_type is None or second_type is None:
                continue
            first_temp = _fpr_product_temp_name(searchable, first)
            if first_temp is None:
                continue
            searchable_with_first = searchable + f"\n{first_temp}\n"
            second_temp = _fpr_product_temp_name(searchable_with_first, second)
            if second_temp is None or second_temp == first_temp:
                continue
            insert_after = _insert_after_top_level_fpr_decls(
                body_text,
                first.start,
            )
            if insert_after is None:
                continue
            span_text = body_text[insert_after:second.end]
            if body_text.count(span_text) != 1:
                continue
            prefix = body_text[insert_after:first.start]
            between = body_text[first.end:second.start]
            replacement_text = (
                f"{first.indent}{first_type} {first_temp};\n"
                f"{first.indent}{second_type} {second_temp};\n"
                f"{prefix}"
                f"{first.indent}{first_temp} = {first.product_expr};\n"
                f"{first.indent}{first.lhs} = {first_temp};"
                f"{between}"
                f"{second.indent}{second_temp} = {second.product_expr};\n"
                f"{second.indent}{second.lhs} = {second_temp};"
            )
            anchors.append(
                Anchor(
                    mutator_key="steer_fpr_paired_product_temp_split",
                    span=(insert_after, second.end),
                    payload={
                        "span_text": span_text,
                        "replacement_text": replacement_text,
                        "strategy": "fpr-paired-product-temp-split",
                        "product_locals": (first.lhs, second.lhs),
                        "product_exprs": (
                            first.product_expr,
                            second.product_expr,
                        ),
                        "temp_locals": (first_temp, second_temp),
                    },
                )
            )
            break
    return anchors


def _iter_fpr_dependent_product_cases(
    body_text: str,
    function_header_text: str = "",
) -> tuple[_RegisterSteeringDependentProductCase, ...]:
    if re.search(r"(?m)^[ \t]*#", body_text):
        return ()
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    preprocessor_depths = _preprocessor_depths_for_lines(searchable_records)
    cases: list[_RegisterSteeringDependentProductCase] = []
    for idx, (start, _end, _end_with_newline, line) in enumerate(searchable_records[:-1]):
        _next_start, next_end, _next_end_with_newline, next_line = searchable_records[idx + 1]
        if idx >= len(records) or idx + 1 >= len(records):
            continue
        if (depths[idx] if idx < len(depths) else 0) != 1:
            continue
        if (depths[idx + 1] if idx + 1 < len(depths) else 0) != 1:
            continue
        if preprocessor_depths[idx] != 0 or preprocessor_depths[idx + 1] != 0:
            continue
        primary_match = _REGISTER_STEERING_ASSIGN_RE.match(line)
        dependent_assign = _REGISTER_STEERING_ASSIGN_RE.match(next_line)
        if primary_match is None or dependent_assign is None:
            continue
        if records[idx][3] != line or records[idx + 1][3] != next_line:
            continue
        indent = primary_match.group("indent")
        if dependent_assign.group("indent") != indent:
            continue
        primary = primary_match.group("lhs")
        product = _register_steering_product_expr(primary_match.group("rhs"))
        if product is None:
            continue
        product_expr, operand_names, cast_operand_names = product
        dependent = dependent_assign.group("lhs")
        if primary in operand_names or dependent in operand_names:
            continue
        if not _register_steering_product_has_fpr_operand_proof(
            body_text,
            function_header_text,
            operand_names,
            cast_operand_names,
        ):
            continue
        dependent_parts = _dependent_product_parts(
            dependent_assign.group("rhs").strip(),
            primary=primary,
            product_expr=product_expr,
        )
        if dependent_parts is None:
            continue
        if (
            _node_set_split_synthetic_name(primary)
            or _node_set_split_synthetic_name(dependent)
            or _generated_fpr_product_temp_name(primary)
            or _generated_fpr_product_temp_name(dependent)
            or any(_generated_fpr_product_temp_name(name) for name in operand_names)
        ):
            continue
        decls = _register_steering_fpr_product_decls(body_text, primary, dependent)
        if decls is None:
            continue
        primary_decl, _dependent_decl = decls
        if _counter_address_take_rejects(searchable, primary) or _counter_address_take_rejects(
            searchable,
            dependent,
        ):
            continue
        if _counter_identifier_region_rejects(searchable, body_text, primary, dependent):
            continue
        cases.append(
            _RegisterSteeringDependentProductCase(
                start=start,
                next_end=next_end,
                indent=indent,
                primary=primary,
                dependent=dependent,
                product_expr=product_expr,
                dependent_parts=dependent_parts,
                primary_decl=primary_decl,
            )
        )

    for idx, (start, _end, _end_with_newline, line) in enumerate(
        searchable_records[:-2]
    ):
        _alias_start, _alias_end, _alias_end_with_newline, alias_line = (
            searchable_records[idx + 1]
        )
        _dependent_start, dependent_end, _dependent_end_with_newline, dependent_line = (
            searchable_records[idx + 2]
        )
        if idx >= len(records) or idx + 2 >= len(records):
            continue
        if any(
            (depths[line_idx] if line_idx < len(depths) else 0) != 1
            for line_idx in (idx, idx + 1, idx + 2)
        ):
            continue
        if any(
            preprocessor_depths[line_idx] != 0
            for line_idx in (idx, idx + 1, idx + 2)
        ):
            continue
        primary_match = _REGISTER_STEERING_ASSIGN_RE.match(line)
        alias_assign = _REGISTER_STEERING_ASSIGN_RE.match(alias_line)
        dependent_assign = _REGISTER_STEERING_ASSIGN_RE.match(dependent_line)
        if (
            primary_match is None
            or alias_assign is None
            or dependent_assign is None
        ):
            continue
        if (
            records[idx][3] != line
            or records[idx + 1][3] != alias_line
            or records[idx + 2][3] != dependent_line
        ):
            continue
        indent = primary_match.group("indent")
        if (
            alias_assign.group("indent") != indent
            or dependent_assign.group("indent") != indent
        ):
            continue
        primary = primary_match.group("lhs")
        product = _register_steering_product_expr(primary_match.group("rhs"))
        if product is None:
            continue
        product_expr, operand_names, cast_operand_names = product
        alias_local = alias_assign.group("lhs")
        if alias_assign.group("rhs").strip() != primary:
            continue
        dependent = dependent_assign.group("lhs")
        if len({primary, alias_local, dependent}) != 3:
            continue
        if primary in operand_names or dependent in operand_names:
            continue
        if not _register_steering_product_has_fpr_operand_proof(
            body_text,
            function_header_text,
            operand_names,
            cast_operand_names,
        ):
            continue
        dependent_parts = _dependent_product_parts(
            dependent_assign.group("rhs").strip(),
            primary=alias_local,
            product_expr=product_expr,
        )
        if dependent_parts is None:
            continue
        if (
            _node_set_split_synthetic_name(primary)
            or _node_set_split_synthetic_name(dependent)
            or _node_set_split_synthetic_name(alias_local)
            or _generated_fpr_product_temp_name(primary)
            or _generated_fpr_product_temp_name(dependent)
            or any(_generated_fpr_product_temp_name(name) for name in operand_names)
        ):
            continue
        decls = _register_steering_fpr_product_decls(body_text, primary, dependent)
        if decls is None:
            continue
        primary_decl, _dependent_decl = decls
        all_decls = _register_steering_decl_records(body_text)
        if all_decls is None:
            all_decls = _register_steering_narrow_decl_records_for(
                body_text,
                {alias_local},
            )
        if all_decls is None:
            continue
        alias_decls = [decl for decl in all_decls if decl.name == alias_local]
        if (
            len(alias_decls) != 1
            or alias_decls[0].depth != 1
            or alias_decls[0].type_name not in _REGISTER_STEERING_FPR_TYPES
        ):
            continue
        if _counter_identifier_region_rejects(
            searchable,
            body_text,
            primary,
            dependent,
            alias_local,
        ):
            continue
        cases.append(
            _RegisterSteeringDependentProductCase(
                start=start,
                next_end=dependent_end,
                indent=indent,
                primary=primary,
                dependent=dependent,
                product_expr=product_expr,
                dependent_parts=dependent_parts,
                primary_decl=primary_decl,
                alias_local=alias_local,
            )
        )
    return tuple(cases)


def _iter_fpr_product_temp_plus_dependent_anchors(
    body_text: str,
    function_header_text: str = "",
) -> list[Anchor]:
    products = _iter_fpr_product_assignments(body_text, function_header_text)
    if not products:
        return []
    cases = _iter_fpr_dependent_product_cases(body_text, function_header_text)
    if not cases:
        return []
    searchable = _blank_literals_and_comments(body_text)
    anchors: list[Anchor] = []

    for case in cases:
        for fixed in products:
            if fixed.lhs in {case.primary, case.dependent}:
                continue
            if fixed.indent != case.indent:
                continue
            if not (fixed.end <= case.start or case.next_end <= fixed.start):
                continue
            fixed_type = _fpr_product_decl_type(body_text, fixed)
            if fixed_type is None:
                continue
            first_start = min(fixed.start, case.start)
            last_end = max(fixed.end, case.next_end)
            insert_after = _insert_after_top_level_fpr_decls(body_text, first_start)
            if insert_after is None:
                continue
            span_text = body_text[insert_after:last_end]
            if body_text.count(span_text) != 1:
                continue
            fixed_temp = _fpr_product_temp_name(searchable, fixed)
            if fixed_temp is None:
                continue
            occupied = searchable + f"\n{fixed_temp}\n"
            fixed_text = (
                f"{fixed.indent}{fixed_temp} = {fixed.product_expr};\n"
                f"{fixed.indent}{fixed.lhs} = {fixed_temp};"
            )

            def replacement_for(
                *,
                strategy: str,
                dependent_text: str,
                extra_decl: str = "",
                temp_local: str | None = None,
            ) -> Anchor:
                prefix = body_text[insert_after:first_start]
                decls = f"{fixed.indent}{fixed_type} {fixed_temp};\n{extra_decl}"
                if fixed.start < case.start:
                    between = body_text[fixed.end:case.start]
                    replacement_text = (
                        f"{decls}{prefix}{fixed_text}{between}{dependent_text}"
                    )
                else:
                    between = body_text[case.next_end:fixed.start]
                    replacement_text = (
                        f"{decls}{prefix}{dependent_text}{between}{fixed_text}"
                    )
                payload: dict[str, Any] = {
                    "span_text": span_text,
                    "replacement_text": replacement_text,
                    "strategy": strategy,
                    "fixed_product_local": fixed.lhs,
                    "fixed_product_expr": fixed.product_expr,
                    "fixed_temp_local": fixed_temp,
                    "product_local": case.primary,
                    "dependent_local": case.dependent,
                    "product_expr": case.product_expr,
                }
                if temp_local is not None:
                    payload["temp_local"] = temp_local
                return Anchor(
                    mutator_key="steer_fpr_product_temp_plus_dependent",
                    span=(insert_after, last_end),
                    payload=payload,
                )

            if case.alias_local is None:
                dependent_recompute = _dependent_product_replacement(
                    indent=case.indent,
                    dependent=case.dependent,
                    product_expr=case.product_expr,
                    dependent_parts=case.dependent_parts,
                )
                if dependent_recompute is not None:
                    anchors.append(
                        replacement_for(
                            strategy="fpr-product-temp-plus-dependent-recompute-first",
                            dependent_text=(
                                f"{dependent_recompute}\n"
                                f"{case.indent}{case.primary} = "
                                f"{case.product_expr};"
                            ),
                        )
                    )

                reuse_temp = _fpr_product_reuse_temp_name(occupied, case.primary)
                if reuse_temp is not None:
                    dependent_from_reuse = _dependent_source_replacement(
                        indent=case.indent,
                        dependent=case.dependent,
                        source_expr=reuse_temp,
                        dependent_parts=case.dependent_parts,
                    )
                    if dependent_from_reuse is not None:
                        anchors.append(
                            replacement_for(
                                strategy=(
                                    "fpr-product-temp-plus-dependent-"
                                    "product-reuse-temp"
                                ),
                                extra_decl=(
                                    f"{case.indent}{case.primary_decl.type_name} "
                                    f"{reuse_temp};\n"
                                ),
                                dependent_text=(
                                    f"{case.indent}{reuse_temp} = "
                                    f"{case.product_expr};\n"
                                    f"{case.indent}{case.primary} = "
                                    f"{reuse_temp};\n"
                                    f"{dependent_from_reuse}"
                                ),
                                temp_local=reuse_temp,
                            )
                        )

                lifetime_temp = _fpr_lifetime_temp_name(occupied, case.primary)
                if lifetime_temp is not None:
                    dependent_from_lifetime = _dependent_source_replacement(
                        indent=case.indent,
                        dependent=case.dependent,
                        source_expr=lifetime_temp,
                        dependent_parts=case.dependent_parts,
                    )
                    if dependent_from_lifetime is not None:
                        anchors.append(
                            replacement_for(
                                strategy=(
                                    "fpr-product-temp-plus-dependent-"
                                    "local-temp-split"
                                ),
                                extra_decl=(
                                    f"{case.indent}{case.primary_decl.type_name} "
                                    f"{lifetime_temp};\n"
                                ),
                                dependent_text=(
                                    f"{case.indent}{case.primary} = "
                                    f"{case.product_expr};\n"
                                    f"{case.indent}{lifetime_temp} = "
                                    f"{case.primary};\n"
                                    f"{dependent_from_lifetime}"
                                ),
                                temp_local=lifetime_temp,
                            )
                        )
            call_records: list[tuple[int, int, str, str]] = []
            records = _text_line_records_with_newline(body_text)
            searchable_records = _text_line_records_with_newline(searchable)
            for call_idx, (call_start, call_end, _call_end_with_newline, search_line) in enumerate(
                searchable_records
            ):
                if call_idx >= len(records) or call_start <= case.next_end:
                    continue
                if records[call_idx][3] != search_line:
                    continue
                line = records[call_idx][3]
                if _call_statement_uses_local(search_line, case.primary):
                    call_records.append((call_start, call_end, line, case.primary))
                elif _call_statement_uses_local(search_line, case.dependent):
                    call_records.append((call_start, call_end, line, case.dependent))
            if call_records:
                last_call_end = call_records[-1][1]
                call_span_text = body_text[insert_after:last_call_end]
                if body_text.count(call_span_text) == 1:
                    fixed_line_replacement = (
                        f"{fixed_text}\n" if fixed.line.endswith("\n") else fixed_text
                    )
                    call_expr_text = call_span_text.replace(
                        fixed.line,
                        fixed_line_replacement,
                        1,
                    )
                    for _call_start, _call_end, line, local in call_records:
                        if local == case.primary:
                            replacement_expr = case.product_expr
                        else:
                            replacement_expr = _dependent_expr_from_source(
                                case.product_expr,
                                case.dependent_parts,
                            )
                        call_expr_text = call_expr_text.replace(
                            line,
                            _replace_call_statement_local(
                                line,
                                local,
                                replacement_expr,
                            ),
                            1,
                        )
                    if call_expr_text != call_span_text:
                        anchors.append(
                            Anchor(
                                mutator_key="steer_fpr_product_temp_plus_dependent",
                                span=(insert_after, last_call_end),
                                payload={
                                    "span_text": call_span_text,
                                    "replacement_text": (
                                        f"{fixed.indent}{fixed_type} {fixed_temp};\n"
                                        f"{call_expr_text}"
                                    ),
                                    "strategy": (
                                        "fpr-product-temp-plus-dependent-"
                                        "call-expr-duplicate"
                                    ),
                                    "fixed_product_local": fixed.lhs,
                                    "fixed_product_expr": fixed.product_expr,
                                    "fixed_temp_local": fixed_temp,
                                    "product_local": case.primary,
                                    "dependent_local": case.dependent,
                                    "product_expr": case.product_expr,
                                },
                            )
                        )

                    primary_call_temp = _fresh_register_steering_name(
                        occupied,
                        f"{case.primary}_call",
                    )
                    temp_occupied = occupied
                    if primary_call_temp is not None:
                        temp_occupied += f"\n{primary_call_temp}\n"
                    dependent_call_temp = _fresh_register_steering_name(
                        temp_occupied,
                        f"{case.dependent}_call",
                    )
                    if primary_call_temp is not None and dependent_call_temp is not None:
                        call_temp_text = call_span_text.replace(
                            fixed.line,
                            fixed_line_replacement,
                            1,
                        )
                        for _call_start, _call_end, line, local in call_records:
                            indent_match = re.match(r"(?P<indent>[ \t]*)", line)
                            call_indent = (
                                indent_match.group("indent")
                                if indent_match is not None else ""
                            )
                            if local == case.primary:
                                temp_name = primary_call_temp
                                assignment_expr = case.product_expr
                            else:
                                temp_name = dependent_call_temp
                                assignment_expr = _dependent_expr_from_source(
                                    case.primary,
                                    case.dependent_parts,
                                )
                            call_temp_text = call_temp_text.replace(
                                line,
                                (
                                    f"{call_indent}{temp_name} = {assignment_expr};\n"
                                    f"{_replace_call_statement_local(line, local, temp_name)}"
                                ),
                                1,
                            )
                        if call_temp_text != call_span_text:
                            anchors.append(
                                Anchor(
                                    mutator_key=(
                                        "steer_fpr_product_temp_plus_dependent"
                                    ),
                                    span=(insert_after, last_call_end),
                                    payload={
                                        "span_text": call_span_text,
                                        "replacement_text": (
                                            f"{fixed.indent}{fixed_type} "
                                            f"{fixed_temp};\n"
                                            f"{fixed.indent}"
                                            f"{case.primary_decl.type_name} "
                                            f"{primary_call_temp};\n"
                                            f"{fixed.indent}"
                                            f"{case.primary_decl.type_name} "
                                            f"{dependent_call_temp};\n"
                                            f"{call_temp_text}"
                                        ),
                                        "strategy": (
                                            "fpr-product-temp-plus-dependent-"
                                            "call-temp-split"
                                        ),
                                        "fixed_product_local": fixed.lhs,
                                        "fixed_product_expr": fixed.product_expr,
                                        "fixed_temp_local": fixed_temp,
                                        "product_local": case.primary,
                                        "dependent_local": case.dependent,
                                        "product_expr": case.product_expr,
                                        "temp_locals": (
                                            primary_call_temp,
                                            dependent_call_temp,
                                        ),
                                    },
                                )
                            )
            break
    return anchors


def _iter_fpr_product_steering_anchors(
    body_text: str,
    function_header_text: str = "",
) -> list[Anchor]:
    products = _iter_fpr_product_assignments(body_text, function_header_text)
    if not products:
        return []
    return [
        *_iter_fpr_product_temp_split_anchors(body_text, products),
        *_iter_fpr_paired_product_temp_split_anchors(body_text, products),
        *_iter_fpr_product_order_anchors(body_text, products),
        *_iter_fpr_product_cast_split_anchors(body_text, products),
        *_iter_fpr_product_argument_duplicate_anchors(body_text, products),
    ]


def _iter_fpr_dependent_product_recompute_anchors(
    body_text: str,
    function_header_text: str = "",
) -> list[Anchor]:
    anchors: list[Anchor] = []
    if re.search(r"(?m)^[ \t]*#", body_text):
        return anchors
    searchable = _blank_literals_and_comments(body_text)
    records = _text_line_records_with_newline(body_text)
    searchable_records = _text_line_records_with_newline(searchable)
    depths = _line_depths_from_blanked_text(searchable)
    preprocessor_depths = _preprocessor_depths_for_lines(searchable_records)
    for idx, (start, _end, _end_with_newline, line) in enumerate(searchable_records[:-1]):
        next_start, next_end, _next_end_with_newline, next_line = searchable_records[idx + 1]
        if idx >= len(records) or idx + 1 >= len(records):
            continue
        if (depths[idx] if idx < len(depths) else 0) != 1:
            continue
        if (depths[idx + 1] if idx + 1 < len(depths) else 0) != 1:
            continue
        if preprocessor_depths[idx] != 0 or preprocessor_depths[idx + 1] != 0:
            continue
        primary_match = _REGISTER_STEERING_ASSIGN_RE.match(line)
        dependent_assign = _REGISTER_STEERING_ASSIGN_RE.match(next_line)
        if primary_match is None or dependent_assign is None:
            continue
        if records[idx][3] != line or records[idx + 1][3] != next_line:
            continue
        indent = primary_match.group("indent")
        if dependent_assign.group("indent") != indent:
            continue
        primary = primary_match.group("lhs")
        product = _register_steering_product_expr(primary_match.group("rhs"))
        if product is None:
            continue
        product_expr, operand_names, cast_operand_names = product
        dependent = dependent_assign.group("lhs")
        if primary in operand_names or dependent in operand_names:
            continue
        if not _register_steering_product_has_fpr_operand_proof(
            body_text,
            function_header_text,
            operand_names,
            cast_operand_names,
        ):
            continue
        dependent_parts = _dependent_product_parts(
            dependent_assign.group("rhs").strip(),
            primary=primary,
            product_expr=product_expr,
        )
        if dependent_parts is None:
            continue
        if (
            _node_set_split_synthetic_name(primary)
            or _node_set_split_synthetic_name(dependent)
            or _generated_fpr_product_temp_name(primary)
            or _generated_fpr_product_temp_name(dependent)
            or any(_generated_fpr_product_temp_name(name) for name in operand_names)
        ):
            continue
        if _register_steering_fpr_product_decls(body_text, primary, dependent) is None:
            continue
        if _counter_address_take_rejects(searchable, primary) or _counter_address_take_rejects(
            searchable,
            dependent,
        ):
            continue
        if _counter_identifier_region_rejects(searchable, body_text, primary, dependent):
            continue
        span_text = body_text[start:next_end]
        if body_text.count(span_text) != 1:
            continue
        dependent_replacement = _dependent_product_replacement(
            indent=indent,
            dependent=dependent,
            product_expr=product_expr,
            dependent_parts=dependent_parts,
        )
        if dependent_replacement is None:
            continue
        same_order_text = (
            f"{indent}{primary} = {product_expr};\n"
            f"{dependent_replacement}"
        )
        first_text = (
            f"{dependent_replacement}\n"
            f"{indent}{primary} = {product_expr};"
        )
        recompute_first_anchor = Anchor(
            mutator_key="steer_fpr_dependent_product_recompute",
            span=(start, next_end),
            payload={
                "span_text": span_text,
                "replacement_text": first_text,
                "strategy": "fpr-dependent-product-recompute-first",
                "product_local": primary,
                "dependent_local": dependent,
                "product_expr": product_expr,
            },
        )
        recompute_same_order_anchor = Anchor(
            mutator_key="steer_fpr_dependent_product_recompute",
            span=(start, next_end),
            payload={
                "span_text": span_text,
                "replacement_text": same_order_text,
                "strategy": "fpr-dependent-product-recompute-same-order",
                "product_local": primary,
                "dependent_local": dependent,
                "product_expr": product_expr,
            },
        )
        anchors.append(recompute_first_anchor)
        decls = _register_steering_fpr_product_decls(body_text, primary, dependent)
        if decls is None:
            anchors.append(recompute_same_order_anchor)
            continue
        primary_decl, _dependent_decl = decls
        insert_after = _insert_after_top_level_fpr_decls(body_text, start)
        if insert_after is None:
            anchors.append(recompute_same_order_anchor)
            continue
        span_with_decl_insertion = body_text[insert_after:next_end]
        if body_text.count(span_with_decl_insertion) != 1:
            anchors.append(recompute_same_order_anchor)
            continue
        prefix = body_text[insert_after:start]
        reuse_temp = _fpr_product_reuse_temp_name(searchable, primary)
        if reuse_temp is not None:
            dependent_from_reuse = _dependent_source_replacement(
                indent=indent,
                dependent=dependent,
                source_expr=reuse_temp,
                dependent_parts=dependent_parts,
            )
            if dependent_from_reuse is not None:
                anchors.append(
                    Anchor(
                        mutator_key="steer_fpr_dependent_product_reuse_temp",
                        span=(insert_after, next_end),
                        payload={
                            "span_text": span_with_decl_insertion,
                            "replacement_text": (
                                f"{indent}{primary_decl.type_name} {reuse_temp};\n"
                                f"{prefix}"
                                f"{indent}{reuse_temp} = {product_expr};\n"
                                f"{indent}{primary} = {reuse_temp};\n"
                                f"{dependent_from_reuse}"
                            ),
                            "strategy": "fpr-dependent-product-reuse-temp",
                            "product_local": primary,
                            "dependent_local": dependent,
                            "product_expr": product_expr,
                            "temp_local": reuse_temp,
                        },
                    )
                )
        lifetime_temp = _fpr_lifetime_temp_name(searchable, primary)
        if lifetime_temp is not None:
            dependent_from_lifetime = _dependent_source_replacement(
                indent=indent,
                dependent=dependent,
                source_expr=lifetime_temp,
                dependent_parts=dependent_parts,
            )
            if dependent_from_lifetime is not None:
                anchors.append(
                    Anchor(
                        mutator_key="steer_fpr_dependent_local_temp_split",
                        span=(insert_after, next_end),
                        payload={
                            "span_text": span_with_decl_insertion,
                            "replacement_text": (
                                f"{indent}{primary_decl.type_name} {lifetime_temp};\n"
                                f"{prefix}"
                                f"{indent}{primary} = {product_expr};\n"
                                f"{indent}{lifetime_temp} = {primary};\n"
                                f"{dependent_from_lifetime}"
                            ),
                            "strategy": "fpr-dependent-local-temp-split",
                            "product_local": primary,
                            "dependent_local": dependent,
                            "product_expr": product_expr,
                            "temp_local": lifetime_temp,
                        },
                    )
                )
        anchors.append(recompute_same_order_anchor)
    return anchors


def _iter_concrete_register_steering_body_anchors(
    body_text: str,
    function_header_text: str = "",
):
    case_c_temp_order = _iter_fpr_case_c_temp_order_anchors(
        body_text,
        function_header_text,
    )
    product_steering = _iter_fpr_product_steering_anchors(
        body_text,
        function_header_text,
    )
    recompute_product = _iter_fpr_dependent_product_recompute_anchors(
        body_text,
        function_header_text,
    )
    product_temp_plus_dependent = _iter_fpr_product_temp_plus_dependent_anchors(
        body_text,
        function_header_text,
    )
    if re.search(r"(?m)^[ \t]*#", body_text):
        return
    widen_byte = _iter_byte_local_widen_anchors(body_text)
    decls = _register_steering_decl_records(body_text)
    if decls is None:
        yield from case_c_temp_order
        yield from recompute_product
        yield from product_steering
        yield from product_temp_plus_dependent
        return
    top_decls = tuple(decl for decl in decls if decl.depth == 1)
    if _register_steering_has_duplicate_top_level_names(top_decls):
        yield from case_c_temp_order
        yield from recompute_product
        yield from product_steering
        yield from product_temp_plus_dependent
        return
    # #699: previously this bailed the WHOLE function when ANY top-level decl had
    # an unsupported type (e.g. an aggregate-by-value `Foo bar;`), suppressing the
    # entire demote/rotate/reuse/split/widen family even when the unsupported decl
    # sits OUTSIDE every candidate's exact-replaced span. That blocked a known
    # byte_match (mnDiagram2_GetAggregatedFighterRank: demote `res` past the
    # `i..m` run — the `res..m` span never touches the aggregate `temp`). Instead
    # of bailing, drop only anchors whose span OVERLAPS an unsupported top-level
    # decl, preserving the C89 guarantee (no candidate reorders across / mutates
    # an aggregate) while letting safe within-run reorders/demotes through.
    unsupported_spans = tuple(
        (decl.start, decl.end)
        for decl in top_decls
        if not _register_steering_concrete_type_supported(decl.type_name)
    )
    rotate = _iter_decl_window_rotation_anchors(body_text, decls)
    demote = _iter_decl_demote_anchors(body_text, decls)
    reuse_dead = _iter_dead_top_level_loop_counter_reuse_anchors(body_text, decls)
    split = _iter_reused_loop_counter_split_anchors(body_text, decls)

    def _span_clear(group: list) -> list:
        # Drop reorder anchors whose span crosses an unsupported decl (keeps the
        # C89 guarantee). recompute_product (FPR binding) and widen_byte (in-place
        # type widen) are not decl reorders, so they are not span-filtered.
        return [
            anchor for anchor in group
            if not any(
                anchor.span[0] < s1 and s0 < anchor.span[1]
                for (s0, s1) in unsupported_spans
            )
        ]

    priority_recompute = recompute_product[:3]
    recompute_rest = recompute_product[3:]
    legacy_steering = [
        *priority_recompute,
        *_interleave_anchor_groups(
        recompute_rest,
        _span_clear(rotate),
        _span_clear(demote),
        _span_clear(reuse_dead),
        _span_clear(split),
        widen_byte,
        ),
    ]
    product_insert_after = len(legacy_steering)
    if product_steering:
        wanted_recompute = min(3, len(recompute_product))
        need_rotate = bool(rotate)
        need_demote = bool(demote)
        seen_recompute = 0
        seen_rotate = False
        seen_demote = False
        for idx, anchor in enumerate(legacy_steering):
            if anchor.mutator_key in {
                "steer_fpr_dependent_product_recompute",
                "steer_fpr_dependent_product_reuse_temp",
                "steer_fpr_dependent_local_temp_split",
            }:
                seen_recompute += 1
            elif anchor.mutator_key == "steer_rotate_local_decl_window":
                seen_rotate = True
            elif anchor.mutator_key == "steer_demote_local_decl_to_first_use":
                seen_demote = True
            if (
                seen_recompute >= wanted_recompute
                and (not need_rotate or seen_rotate)
                and (not need_demote or seen_demote)
            ):
                product_insert_after = idx + 1
                break
    yield from case_c_temp_order
    yield from legacy_steering[:product_insert_after]
    yield from product_steering
    yield from product_temp_plus_dependent
    yield from legacy_steering[product_insert_after:]


def _next_nonempty_line(
    records: list[tuple[int, int, str]],
    idx: int,
) -> str | None:
    for _start, _end, line in records[idx + 1:]:
        if line.strip():
            return line
    return None


def _interleave_anchor_groups(*groups: list[Anchor]):
    max_len = max((len(group) for group in groups), default=0)
    for index in range(max_len):
        for group in groups:
            if index < len(group):
                yield group[index]


_NODE_SET_DELTA_MAX_REQUESTS = 4


def _desired_register_label(request) -> str:
    current = request.current_reg or "?"
    target = request.target_reg or "?"
    return f"ig{request.target_ig}:{current}->{target}"


def _merge_touched_ranges(
    ranges: tuple[tuple[int, int], ...],
    source_text: str,
) -> tuple[int, int]:
    valid = [
        (max(0, int(start)), min(len(source_text), int(end)))
        for start, end in ranges
        if int(start) <= int(end)
    ]
    if not valid:
        return (0, len(source_text))
    return (min(start for start, _end in valid), max(end for _start, end in valid))


def _missing_virtual_target_ig(entry: object) -> int | None:
    if not isinstance(entry, Mapping):
        return None
    try:
        return int(entry.get("target_ig"))
    except (TypeError, ValueError):
        return None


def _skipped_node_set_entries(delta: Mapping[str, Any], requests: list) -> list[dict]:
    bound = {request.target_ig for request in requests}
    skipped: list[dict] = []
    missing = delta.get("missing_virtuals")
    if not isinstance(missing, list):
        return skipped
    for entry in missing:
        target_ig = _missing_virtual_target_ig(entry)
        if target_ig is None or target_ig in bound:
            continue
        item = dict(entry) if isinstance(entry, Mapping) else {"raw": entry}
        item["blocked_reason"] = "no bindable source variable"
        skipped.append(item)
    return skipped


def _raw_node_set_entries_by_target(delta: Mapping[str, Any]) -> dict[int, list[dict]]:
    raw_by_target: dict[int, list[dict]] = {}
    missing = delta.get("missing_virtuals")
    if not isinstance(missing, list):
        return raw_by_target
    for entry in missing:
        target_ig = _missing_virtual_target_ig(entry)
        if target_ig is None or not isinstance(entry, Mapping):
            continue
        raw_by_target.setdefault(target_ig, []).append(dict(entry))
    return raw_by_target


def _node_set_raw_source_name(entry: Mapping[str, Any]) -> str | None:
    source = entry.get("source")
    if not isinstance(source, Mapping):
        return None
    expression = source.get("expression")
    base_var = source.get("base_var")
    name = source.get("name")
    expression_text = str(expression).strip() if expression is not None else None
    base_text = str(base_var).strip() if base_var is not None else None
    name_text = str(name).strip() if name is not None else None
    simple_identifier = r"^[A-Za-z_][A-Za-z_0-9]*$"

    if expression_text and re.match(simple_identifier, expression_text):
        return expression_text
    if base_text and re.match(simple_identifier, base_text):
        return base_text
    if (
        name_text
        and re.match(simple_identifier, name_text)
        and not (expression_text and ("." in expression_text or "->" in expression_text))
    ):
        return name_text
    return None


def _primary_raw_node_set_entry(request, raw_entries: list[dict]) -> dict | None:
    request_expression = getattr(request, "source_expression", None)
    if getattr(request, "var_name", None) is not None:
        for entry in raw_entries:
            if _node_set_raw_source_name(entry) == request.var_name:
                return entry
    if request_expression is not None:
        for entry in raw_entries:
            source = entry.get("source")
            if not isinstance(source, Mapping):
                continue
            expression = source.get("expression")
            if expression is not None and str(expression).strip() == request_expression:
                return entry
    return raw_entries[0] if raw_entries else None


def _capped_node_set_entries(
    requests: list,
    raw_entries_by_target: Mapping[int, list[dict]],
) -> list[dict]:
    capped: list[dict] = []
    for request in requests:
        raw_entries = raw_entries_by_target.get(request.target_ig, [])
        primary = _primary_raw_node_set_entry(request, raw_entries)
        item = dict(primary) if primary is not None else {"target_ig": request.target_ig}
        item["blocked_reason"] = "request cap exceeded"
        capped.append(item)
    return capped


def _node_set_request_payload(
    request,
    raw_entries_by_target: Mapping[int, list[dict]],
) -> dict:
    payload = asdict(request)
    raw_entries = raw_entries_by_target.get(request.target_ig, [])
    primary = _primary_raw_node_set_entry(request, raw_entries)
    if primary is None:
        return payload
    payload["raw_missing_virtual"] = primary
    payload["raw_missing_virtuals"] = raw_entries
    for key in (
        "source",
        "source_action",
        "desired_registers",
        "current_register",
        "target_register",
        "target_reg",
    ):
        if key in primary:
            payload[key] = primary[key]
    return payload


def _normalize_node_set_delta_for_transform(delta: Mapping[str, Any]) -> dict[str, Any]:
    nested = delta.get("node_set_delta")
    if isinstance(nested, Mapping):
        merged = dict(nested)
        for key in ("function", "class_id"):
            if key not in merged and key in delta:
                merged[key] = delta[key]
        return merged
    return dict(delta)


def _iter_node_set_delta_steering_probes(
    source_text: str,
    *,
    function: str,
    node_set_delta: Mapping[str, Any],
    remaining: int,
) -> list[tuple[Anchor, str, tuple[str, ...]]]:
    if remaining <= 0:
        return []
    from src.mwcc_debug.node_set_split import (
        generate_coupled_node_set_split_patches,
        generate_node_set_introduce_binding_patches,
        generate_node_set_split_patches,
        is_node_set_request_introducible,
        requests_from_node_set_delta,
    )

    normalized = _normalize_node_set_delta_for_transform(node_set_delta)
    raw_entries_by_target = _raw_node_set_entries_by_target(normalized)
    classification_limit = max(_NODE_SET_DELTA_MAX_REQUESTS, remaining) + 1
    all_requests = requests_from_node_set_delta(
        normalized,
        source_text=source_text,
        max_requests=classification_limit,
        include_introducible=True,
    )
    requests = all_requests[:_NODE_SET_DELTA_MAX_REQUESTS]
    skipped = _skipped_node_set_entries(normalized, all_requests)
    capped = _capped_node_set_entries(
        all_requests[len(requests):],
        raw_entries_by_target,
    )
    out: list[tuple[Anchor, str, tuple[str, ...]]] = []
    seen: set[str] = set()

    def append_patch(mutator_key: str, patch, reqs: list) -> None:
        if len(out) >= remaining or patch.patched_source in seen:
            return
        seen.add(patch.patched_source)
        span = _merge_touched_ranges(patch.touched_ranges, source_text)
        if span == (0, len(source_text)):
            replacement_text = patch.patched_source
        else:
            replacement_text = patch.patched_source[span[0]:span[1]]
        labels = tuple(_desired_register_label(req) for req in reqs)
        source_hunks = [
            {
                "hunk_id": patch.candidate_id,
                "unified_diff": patch.hunk,
            }
        ] if patch.hunk else []
        payload = {
            "span_text": source_text[span[0]:span[1]],
            "replacement_text": replacement_text,
            "strategy": mutator_key,
            "source_hunks": source_hunks,
            "node_set_delta": {
                "requests": [
                    _node_set_request_payload(req, raw_entries_by_target)
                    for req in reqs
                ],
                "skipped_missing_virtuals": skipped,
                "capped_missing_virtuals": capped,
                "patch_candidate_id": patch.candidate_id,
                "patch_summary": patch.summary,
                "hunk": patch.hunk,
                "touched_ranges": [list(item) for item in patch.touched_ranges],
            },
        }
        out.append((
            Anchor(mutator_key=mutator_key, span=span, payload=payload),
            patch.patched_source,
            labels,
        ))

    coupled_requests = requests[:3]
    coupled_budget = min(1, remaining - len(out))
    if len(coupled_requests) >= 2 and coupled_budget > 0:
        coupled_mutator_key = (
            "steer_node_set_delta_stack_array_base_split"
            if any(
                getattr(req, "source_kind", None) == "stack-array-base"
                for req in coupled_requests
            )
            else "steer_node_set_delta_coupled_split"
        )
        for patch in generate_coupled_node_set_split_patches(
            source_text,
            function,
            coupled_requests,
            max_read_sites=2,
            max_per_ig=3,
            max_candidates=coupled_budget,
        ):
            append_patch(
                coupled_mutator_key,
                patch,
                coupled_requests,
            )
            if len(out) >= remaining:
                return out

    for request in requests:
        budget = remaining - len(out)
        if budget <= 0:
            return out
        if is_node_set_request_introducible(request):
            mutator_key = "steer_node_set_delta_introduce_binding_split"
            patches = generate_node_set_introduce_binding_patches(
                source_text,
                function,
                request,
                max_bind_sites=2,
                max_read_sites=2,
                include_split_combos=False,
                max_candidates=budget,
            )
        else:
            mutator_key = "steer_node_set_delta_split"
            patches = generate_node_set_split_patches(
                source_text,
                function,
                request,
                max_read_sites=2,
                include_combos=False,
                max_candidates=budget,
            )
        for patch in patches:
            append_patch(mutator_key, patch, [request])
            if len(out) >= remaining:
                return out
    return out


def _iter_register_steering_body_anchors(body_text: str):
    if re.search(r"(?m)^[ \t]*#", body_text):
        return
    records = _text_line_records(body_text)
    decls: list[tuple[int, int, int, str, object]] = []
    depth = 0
    for idx, (start, end, line) in enumerate(records):
        current_depth = depth
        depth += _line_brace_delta(line)
        if current_depth != 1:
            continue
        match = _register_steering_decl_match(line)
        if match is None:
            continue
        decls.append((idx, start, end, line, match))

    reorder_anchors: list[Anchor] = []
    split_anchors: list[Anchor] = []
    width_anchors: list[Anchor] = []

    for (_idx_a, start_a, _end_a, line_a, match_a), (
        _idx_b,
        _start_b,
        end_b,
        line_b,
        match_b,
    ) in zip(
        decls,
        decls[1:],
    ):
        if (
            _node_set_split_synthetic_name(match_a.group("var"))
            or _node_set_split_synthetic_name(match_b.group("var"))
        ):
            continue
        if not _register_steering_reorder_safe(match_a):
            continue
        if not _register_steering_reorder_safe(match_b):
            continue
        original_block = line_a + "\n" + line_b
        if body_text.count(original_block) != 1:
            continue
        reorder_anchors.append(
            Anchor(
                mutator_key="reorder_local_decls",
                span=(start_a, end_b),
                payload={
                    "first_line": line_a,
                    "second_line": line_b,
                },
            )
        )

    for idx, start, end, line, match in decls:
        if body_text.count(line) != 1:
            continue
        if _node_set_split_synthetic_name(match.group("var")):
            continue
        init = (match.group("init") or "").strip()
        has_later_declaration = any(later_idx > idx for later_idx, *_rest in decls)
        if init:
            if has_later_declaration:
                continue
            split_anchors.append(
                Anchor(
                    mutator_key="split_decl_init",
                    span=(start, end),
                    payload={
                        "decl_line": line,
                        "var": match.group("var"),
                        "type": match.group("type").strip(),
                        "init": init,
                    },
                )
            )

    for idx, start, end, line, match in decls:
        if body_text.count(line) != 1:
            continue
        next_line = _next_nonempty_line(records, idx)
        var = match.group("var")
        if _node_set_split_synthetic_name(var):
            continue
        if next_line is None or re.match(
            rf"^[ \t]*for\s*\(\s*{re.escape(var)}\s*=",
            next_line,
        ) is None:
            continue
        width = _REGISTER_STEERING_COUNTER_RE.search(line)
        if width is not None:
            from_type = width.group(1)
            width_anchors.append(
                Anchor(
                    mutator_key="change_counter_width",
                    span=(start, end),
                    payload={
                        "decl_line": line,
                        "from": from_type,
                        "to": "s32" if from_type == "s16" else "s16",
                    },
                )
            )

    yield from _interleave_anchor_groups(reorder_anchors, split_anchors, width_anchors)
