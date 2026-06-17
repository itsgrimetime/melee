"""Source-transform family: register_steering."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import _blank_literals_and_comments, _identifier_is_member_name, _identifier_mentions, _is_scalar_type, _is_supported_local_reuse_type, _line_depths_from_blanked_text, _line_has_label, _macro_like_statement, _normalize_local_reuse_type, _parse_signature_params, _text_line_records, _text_line_records_with_newline
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


def _region_assigns_any(searchable: str, names: tuple[str, ...]) -> bool:
    return any(
        re.search(r"\b" + re.escape(name) + r"\b\s*(?:[-+*/%&|^]?=|<<=|>>=)", searchable)
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
                            f"{case.indent}{case.primary} = {case.product_expr};"
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
                                "fpr-product-temp-plus-dependent-product-reuse-temp"
                            ),
                            extra_decl=(
                                f"{case.indent}{case.primary_decl.type_name} "
                                f"{reuse_temp};\n"
                            ),
                            dependent_text=(
                                f"{case.indent}{reuse_temp} = {case.product_expr};\n"
                                f"{case.indent}{case.primary} = {reuse_temp};\n"
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
                            strategy="fpr-product-temp-plus-dependent-local-temp-split",
                            extra_decl=(
                                f"{case.indent}{case.primary_decl.type_name} "
                                f"{lifetime_temp};\n"
                            ),
                            dependent_text=(
                                f"{case.indent}{case.primary} = {case.product_expr};\n"
                                f"{case.indent}{lifetime_temp} = {case.primary};\n"
                                f"{dependent_from_lifetime}"
                            ),
                            temp_local=lifetime_temp,
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
        yield from recompute_product
        yield from product_steering
        yield from product_temp_plus_dependent
        return
    top_decls = tuple(decl for decl in decls if decl.depth == 1)
    if _register_steering_has_duplicate_top_level_names(top_decls):
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
    all_requests = requests_from_node_set_delta(
        normalized,
        source_text=source_text,
        max_requests=0,
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
        payload = {
            "span_text": source_text[span[0]:span[1]],
            "replacement_text": replacement_text,
            "strategy": mutator_key,
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
    if len(coupled_requests) >= 2:
        coupled_budget = remaining if remaining == 1 else max(0, remaining - 1)
        for patch in generate_coupled_node_set_split_patches(
            source_text,
            function,
            coupled_requests,
            max_read_sites=2,
            max_per_ig=3,
            max_candidates=coupled_budget,
        ):
            append_patch(
                "steer_node_set_delta_coupled_split",
                patch,
                coupled_requests,
            )
            if len(out) >= remaining:
                return out

    for request in requests:
        if is_node_set_request_introducible(request):
            mutator_key = "steer_node_set_delta_introduce_binding_split"
            patches = generate_node_set_introduce_binding_patches(
                source_text,
                function,
                request,
                max_bind_sites=2,
                max_read_sites=2,
            )
        else:
            mutator_key = "steer_node_set_delta_split"
            patches = generate_node_set_split_patches(
                source_text,
                function,
                request,
                max_read_sites=2,
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
