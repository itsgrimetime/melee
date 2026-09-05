"""Source probes for GPR common-subexpression coalesce leads."""
from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Mapping
from typing import Any

from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import (
    _normalize_type_name,
    _target_function_body,
)


MUTATOR_KEY = "steer_retained_gpr_common_subexpr_coalesce_source"


@dataclass(frozen=True)
class _WriteSite:
    var_name: str
    start: int
    end: int
    line_no: int
    line_text: str
    indent: str
    rhs: str
    type_name: str | None
    kind: str


@dataclass(frozen=True)
class _ImplicitSourceOwnerScan:
    groups: tuple[tuple[str, tuple[_WriteSite, ...]], ...]
    terminal_blocker: str | None


def iter_common_subexpr_coalesce_anchors(
    source_text: str,
    *,
    function: str,
    coalesce_suggestion: Mapping[str, Any] | None,
    force_phys: Mapping[int, int],
    max_candidates: int,
) -> tuple[Anchor, ...]:
    target = _target_function_body(source_text, function)
    if target is None or coalesce_suggestion is None:
        return ()
    span, _body_text = target
    pairs = _common_subexpr_pairs(coalesce_suggestion)
    bridge_by_virtual = _bridge_by_virtual(coalesce_suggestion)

    anchors: list[Anchor] = []
    seen_candidates: set[str] = set()
    for pair in pairs:
        if len(anchors) >= max_candidates:
            break
        pair_info = _pair_info(pair, bridge_by_virtual=bridge_by_virtual)
        if pair_info["terminal_blocker"] is not None:
            continue
        from_bridge = pair_info["from_bridge"]
        to_bridge = pair_info["to_bridge"]
        direct_materialized = False
        from_site = None
        if _has_bridge_var(from_bridge) and _has_bridge_var(to_bridge):
            from_var = str(from_bridge.get("var") or "")
            to_var = str(to_bridge.get("var") or "")
            from_site = _find_write_site(
                source_text,
                span.sig_start,
                span.full_end,
                from_var,
            )
            to_site = _find_write_site(
                source_text,
                span.sig_start,
                span.full_end,
                to_var,
            )
            if from_var == to_var or from_site is None or to_site is None:
                direct_candidate = None
            else:
                direct_candidate = _materialize_shared_rhs_probe(
                    source_text,
                    function_start=span.sig_start,
                    function_end=span.full_end,
                    from_site=from_site,
                    to_site=to_site,
                    pair_info=pair_info,
                    force_phys=force_phys,
                )
        else:
            direct_candidate = None
        if direct_candidate is not None:
            candidate_text, payload = direct_candidate
            if candidate_text not in seen_candidates:
                seen_candidates.add(candidate_text)
                anchors.append(Anchor(
                    mutator_key=MUTATOR_KEY,
                    span=(
                        min(from_site.start, to_site.start),
                        max(from_site.end, to_site.end),
                    ),
                    payload={
                        **payload,
                        "candidate_text": candidate_text,
                    },
                ))
                direct_materialized = True
        if direct_materialized:
            continue
        source_owner_candidates = _iter_common_source_owner_candidates(
            source_text,
            function_start=span.sig_start,
            function_end=span.full_end,
            from_site=from_site,
            pair_info=pair_info,
            force_phys=force_phys,
        )
        if not source_owner_candidates:
            source_owner_candidates = _iter_implicit_common_source_owner_candidates(
                source_text,
                function_start=span.sig_start,
                function_end=span.full_end,
                pair_info=pair_info,
                force_phys=force_phys,
            )
        for candidate_text, payload, candidate_span in source_owner_candidates:
            if len(anchors) >= max_candidates:
                break
            if candidate_text in seen_candidates:
                continue
            seen_candidates.add(candidate_text)
            anchors.append(Anchor(
                mutator_key=MUTATOR_KEY,
                span=candidate_span,
                payload={
                    **payload,
                    "candidate_text": candidate_text,
                },
            ))
    return tuple(anchors)


def common_subexpr_coalesce_match_diagnostics(
    source_text: str | None,
    *,
    function: str,
    coalesce_suggestion: Mapping[str, Any] | None,
    anchors: tuple[Anchor, ...],
) -> dict[str, Any]:
    if coalesce_suggestion is None:
        return {
            "status": "blocked",
            "terminal_blocker": "missing-coalesce-suggest-payload",
            "coalesce_pair_count": 0,
            "common_subexpr_pair_count": 0,
            "accepted_anchor_count": 0,
        }
    if source_text is None:
        return {
            "status": "blocked",
            "terminal_blocker": "source-unavailable",
            "coalesce_pair_count": 0,
            "common_subexpr_pair_count": 0,
            "accepted_anchor_count": 0,
        }
    pairs = _common_subexpr_pairs(coalesce_suggestion)
    bridge_by_virtual = _bridge_by_virtual(coalesce_suggestion)
    target = _target_function_body(source_text, function)
    pair_diagnostics = [
        _diagnose_pair(
            source_text,
            pair,
            bridge_by_virtual=bridge_by_virtual,
            function_span=None if target is None else (target[0].sig_start, target[0].full_end),
        )
        for pair in pairs
    ]
    blockers = [
        str(item["terminal_blocker"])
        for item in pair_diagnostics
        if item.get("terminal_blocker")
    ]
    if anchors:
        status = "materialized"
        terminal_blocker = None
    else:
        status = "blocked"
        terminal_blocker = _dominant_blocker(blockers)
    source_owner_fallback_count = sum(
        1 for anchor in anchors
        if anchor.payload.get("source_owner_strategy") is not None
    )
    implicit_source_owner_fallback_count = sum(
        1 for anchor in anchors
        if anchor.payload.get("source_owner_origin") == (
            "implicit-repeated-pointer-rhs"
        )
    )
    return {
        "status": status,
        "payload_path": coalesce_suggestion.get("payload_path"),
        "suggest_function": coalesce_suggestion.get("function"),
        "suggest_mode": coalesce_suggestion.get("mode"),
        "register_class": coalesce_suggestion.get("register_class"),
        "coalesce_pair_count": len(coalesce_suggestion.get("pairs") or []),
        "common_subexpr_pair_count": len(pairs),
        "accepted_anchor_count": len(anchors),
        "source_owner_fallback_count": source_owner_fallback_count,
        "implicit_source_owner_fallback_count": (
            implicit_source_owner_fallback_count
        ),
        "terminal_blocker": terminal_blocker,
        "pair_diagnostics": pair_diagnostics,
    }


def _common_subexpr_pairs(
    coalesce_suggestion: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    pairs = coalesce_suggestion.get("pairs")
    if not isinstance(pairs, list):
        return []
    result: list[Mapping[str, Any]] = []
    for pair in pairs:
        if not isinstance(pair, Mapping):
            continue
        register_class = str(pair.get("register_class") or "gpr").lower()
        if register_class not in {"gpr", "r", "int", "class0"}:
            continue
        suggestions = pair.get("suggestions")
        if not isinstance(suggestions, list):
            continue
        if any(
            isinstance(item, Mapping)
            and item.get("pattern") == "common-subexpr"
            for item in suggestions
        ):
            result.append(pair)
    return result


def _bridge_by_virtual(
    coalesce_suggestion: Mapping[str, Any],
) -> dict[int, Mapping[str, Any]]:
    bridges: dict[int, Mapping[str, Any]] = {}
    pairs = coalesce_suggestion.get("pairs")
    if not isinstance(pairs, list):
        return bridges
    for pair in pairs:
        if not isinstance(pair, Mapping):
            continue
        facts = pair.get("ir_facts")
        if not isinstance(facts, Mapping):
            continue
        for side in ("from", "to"):
            fact = facts.get(side)
            if not isinstance(fact, Mapping):
                continue
            bridge = fact.get("bridge")
            if not isinstance(bridge, Mapping) or not bridge.get("var"):
                continue
            try:
                virtual = int(fact.get("virtual"))
            except (TypeError, ValueError):
                continue
            bridges.setdefault(virtual, bridge)
    return bridges


def _pair_info(
    pair: Mapping[str, Any],
    *,
    bridge_by_virtual: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        from_virtual = int(pair.get("from"))
        to_virtual = int(pair.get("to"))
    except (TypeError, ValueError):
        return {"terminal_blocker": "invalid-coalesce-pair"}
    facts = pair.get("ir_facts")
    if not isinstance(facts, Mapping):
        return {"terminal_blocker": "missing-coalesce-ir-facts"}
    from_fact = facts.get("from")
    to_fact = facts.get("to")
    if not isinstance(from_fact, Mapping) or not isinstance(to_fact, Mapping):
        return {"terminal_blocker": "missing-coalesce-ir-facts"}
    from_def = from_fact.get("first_def")
    to_def = to_fact.get("first_def")
    if not isinstance(from_def, Mapping) or not isinstance(to_def, Mapping):
        return {"terminal_blocker": "missing-common-subexpr-first-def"}
    common_source_virtual = _common_source_virtual(
        from_virtual,
        to_virtual,
        from_def,
        to_def,
    )
    if common_source_virtual is None:
        return {"terminal_blocker": "common-subexpr-ir-source-mismatch"}
    from_bridge = from_fact.get("bridge")
    to_bridge = to_fact.get("bridge")
    suggestion = _first_common_subexpr_suggestion(pair)
    bridge_resolution = (
        "direct-source-bridge"
        if _has_bridge_var(from_bridge) and _has_bridge_var(to_bridge)
        else "pcode-shared-source"
    )
    return {
        "terminal_blocker": None,
        "from_virtual": from_virtual,
        "to_virtual": to_virtual,
        "common_source_virtual": common_source_virtual,
        "common_source_bridge": bridge_by_virtual.get(common_source_virtual),
        "from_bridge": _bridge_or_none(from_bridge),
        "to_bridge": _bridge_or_none(to_bridge),
        "from_first_def": dict(from_def),
        "to_first_def": dict(to_def),
        "suggestion": dict(suggestion) if isinstance(suggestion, Mapping) else None,
        "priority_class": pair.get("priority_class"),
        "preflight": pair.get("preflight"),
        "bridge_resolution": bridge_resolution,
    }


def _diagnose_pair(
    source_text: str,
    pair: Mapping[str, Any],
    *,
    bridge_by_virtual: Mapping[int, Mapping[str, Any]],
    function_span: tuple[int, int] | None,
) -> dict[str, Any]:
    info = _pair_info(pair, bridge_by_virtual=bridge_by_virtual)
    diag = {
        "from": pair.get("from"),
        "to": pair.get("to"),
        "priority_class": pair.get("priority_class"),
        "terminal_blocker": info.get("terminal_blocker"),
    }
    if diag["terminal_blocker"] is not None:
        return diag
    from_bridge = info["from_bridge"]
    to_bridge = info["to_bridge"]
    diag.update({
        "common_source_virtual": info.get("common_source_virtual"),
        "bridge_resolution": info.get("bridge_resolution"),
    })
    if function_span is None:
        diag["terminal_blocker"] = "source-function-not-found"
        return diag
    if not (_has_bridge_var(from_bridge) and _has_bridge_var(to_bridge)):
        scan = _scan_implicit_common_source_owner_groups(
            source_text,
            function_span[0],
            function_span[1],
        )
        diag["terminal_blocker"] = scan.terminal_blocker
        diag["implicit_source_owner_fallback"] = (
            scan.terminal_blocker is None
        )
        if scan.groups:
            diag["implicit_source_owner_groups"] = [
                {
                    "common_var": common_var,
                    "sites": [_site_payload(site) for site in sites],
                }
                for common_var, sites in scan.groups
            ]
        return diag
    from_var = str(from_bridge.get("var") or "")
    to_var = str(to_bridge.get("var") or "")
    diag.update({
        "from_var": from_var,
        "to_var": to_var,
    })
    from_site = _find_write_site(source_text, function_span[0], function_span[1], from_var)
    to_site = _find_write_site(source_text, function_span[0], function_span[1], to_var)
    if from_site is None or to_site is None:
        diag["terminal_blocker"] = "common-subexpr-source-span-not-found"
        diag["found_from_write"] = from_site is not None
        diag["found_to_write"] = to_site is not None
        return diag
    diag.update({
        "from_type": from_site.type_name,
        "to_type": to_site.type_name,
        "from_rhs": from_site.rhs,
        "to_rhs": to_site.rhs,
    })
    if _normalize_type_name(from_site.type_name or "") != _normalize_type_name(
        to_site.type_name or ""
    ):
        diag["terminal_blocker"] = "common-subexpr-bridge-type-mismatch"
    elif _normalize_expr(from_site.rhs) != _normalize_expr(to_site.rhs):
        diag["terminal_blocker"] = "common-subexpr-source-span-not-found"
    else:
        diag["terminal_blocker"] = None
    return diag


def _first_common_subexpr_suggestion(
    pair: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    suggestions = pair.get("suggestions")
    if not isinstance(suggestions, list):
        return None
    for suggestion in suggestions:
        if isinstance(suggestion, Mapping) and suggestion.get("pattern") == "common-subexpr":
            return suggestion
    return None


def _common_source_virtual(
    from_virtual: int,
    to_virtual: int,
    from_def: Mapping[str, Any],
    to_def: Mapping[str, Any],
) -> int | None:
    if from_def.get("opcode") != to_def.get("opcode"):
        return None
    from_operands = str(from_def.get("operands") or "")
    to_operands = str(to_def.get("operands") or "")
    from_tail = _operand_tail(from_operands, from_virtual)
    to_tail = _operand_tail(to_operands, to_virtual)
    if from_tail is None or to_tail is None or from_tail != to_tail:
        return None
    match = re.fullmatch(r"r(\d+)(?:\s*,\s*[-+]?(?:0x[0-9A-Fa-f]+|\d+))?", from_tail)
    if match is None:
        return None
    return int(match.group(1))


def _operand_tail(operands: str, dest_virtual: int) -> str | None:
    prefix = f"r{dest_virtual},"
    if not operands.startswith(prefix):
        return None
    return operands[len(prefix):].strip()


def _find_write_site(
    source_text: str,
    start: int,
    end: int,
    var_name: str,
) -> _WriteSite | None:
    declaration_type = _find_declaration_type(source_text, start, end, var_name)
    escaped = re.escape(var_name)
    decl_init = re.compile(
        rf"^(?P<indent>[ \t]*)(?P<type>(?:const\s+|volatile\s+)*"
        rf"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w*)(?:\s*\*)*)\s+"
        rf"{escaped}\s*=\s*(?P<rhs>.+);\s*$"
    )
    assignment = re.compile(
        rf"^(?P<indent>[ \t]*){escaped}\s*=\s*(?P<rhs>.+);\s*$"
    )
    for line_start, line_end, line in _iter_lines(source_text, start, end):
        stripped_line = line.rstrip("\r\n")
        match = decl_init.match(stripped_line)
        if match is not None:
            return _WriteSite(
                var_name=var_name,
                start=line_start,
                end=line_end,
                line_no=_line_no(source_text, line_start),
                line_text=line,
                indent=match.group("indent"),
                rhs=match.group("rhs").strip(),
                type_name=_normalize_type_name(match.group("type")),
                kind="decl-init",
            )
        match = assignment.match(stripped_line)
        if match is not None:
            return _WriteSite(
                var_name=var_name,
                start=line_start,
                end=line_end,
                line_no=_line_no(source_text, line_start),
                line_text=line,
                indent=match.group("indent"),
                rhs=match.group("rhs").strip(),
                type_name=declaration_type,
                kind="assignment",
            )
    return None


def _find_declaration_type(
    source_text: str,
    start: int,
    end: int,
    var_name: str,
) -> str | None:
    escaped = re.escape(var_name)
    decl = re.compile(
        rf"^[ \t]*(?P<type>(?:const\s+|volatile\s+)*"
        rf"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w*)(?:\s*\*)*)\s+"
        rf"{escaped}\s*(?:=|;|\[[^\]]*\]\s*;)\s*$"
    )
    for _line_start, _line_end, line in _iter_lines(source_text, start, end):
        match = decl.match(line.rstrip("\r\n"))
        if match is not None:
            return _normalize_type_name(match.group("type"))
    return None


_C89_DECLARATION_LINE = re.compile(
    r"^(?:const\s+|volatile\s+|static\s+|register\s+)*"
    r"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w*)"
    r"(?:\s+[A-Za-z_]\w*)*"
    r"(?:\s*\*)*\s+"
    r"[A-Za-z_]\w*"
    r"\s*(?:\[[^\]]*\]\s*)?(?:=|,|;)"
)


def _is_c89_declaration_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped.endswith(";"):
        return False
    if stripped.startswith((
        "break;",
        "continue;",
        "do ",
        "for ",
        "goto ",
        "if ",
        "return ",
        "switch ",
        "while ",
    )):
        return False
    return _C89_DECLARATION_LINE.match(stripped) is not None


def _line_after_opening_brace(
    source_text: str,
    scope_open: int,
    scope_end: int,
) -> int:
    line_end = source_text.find("\n", scope_open, scope_end)
    if line_end < 0:
        return scope_open + 1
    return line_end + 1


def _declaration_window(
    source_text: str,
    scope_open: int,
    scope_end: int,
) -> tuple[int, int]:
    start = _line_after_opening_brace(source_text, scope_open, scope_end)
    insert = start
    first_statement = scope_end
    for line_start, line_end, line in _iter_lines(source_text, start, scope_end):
        stripped = line.strip()
        if not stripped:
            continue
        if (
            stripped.startswith("//")
            or stripped.startswith("/*")
            or stripped.startswith("*")
            or stripped.startswith("#")
        ):
            continue
        if _is_c89_declaration_line(stripped):
            insert = line_end
            continue
        first_statement = line_start
        break
    return insert, first_statement


def _function_body_open(
    source_text: str,
    *,
    function_start: int,
    function_end: int,
) -> int | None:
    open_idx = source_text.find("{", function_start, function_end)
    return open_idx if open_idx >= 0 else None


def _scope_open_for_site(
    source_text: str,
    *,
    function_start: int,
    site: _WriteSite,
) -> int | None:
    open_idx = source_text.rfind("{", function_start, site.start)
    return open_idx if open_idx >= 0 else None


def _site_in_declaration_window(
    source_text: str,
    *,
    site: _WriteSite,
    scope_open: int,
    scope_end: int,
) -> bool:
    _insert, first_statement = _declaration_window(source_text, scope_open, scope_end)
    return (
        site.kind == "decl-init"
        and site.start < first_statement
        and _is_c89_declaration_line(site.line_text)
    )


def _scope_declaration_indent(
    source_text: str,
    *,
    scope_open: int,
    scope_end: int,
    default: str,
) -> str:
    start = _line_after_opening_brace(source_text, scope_open, scope_end)
    for _line_start, _line_end, line in _iter_lines(source_text, start, scope_end):
        if _is_c89_declaration_line(line):
            match = re.match(r"^[ \t]*", line)
            return match.group(0) if match is not None else default
    brace_line_start = source_text.rfind("\n", 0, scope_open) + 1
    match = re.match(r"^[ \t]*", source_text[brace_line_start:scope_open])
    brace_indent = match.group(0) if match is not None else ""
    return f"{brace_indent}    "


def _shared_temp_intro(
    source_text: str,
    *,
    function_start: int,
    function_end: int,
    first_site: _WriteSite,
    type_name: str,
    temp_name: str,
    rhs: str,
) -> dict[str, Any] | None:
    scope_open = _function_body_open(
        source_text,
        function_start=function_start,
        function_end=function_end,
    )
    if scope_open is None:
        return None
    declaration_insert, _first_statement = _declaration_window(
        source_text,
        scope_open,
        function_end,
    )
    decl_indent = _scope_declaration_indent(
        source_text,
        scope_open=scope_open,
        scope_end=function_end,
        default=first_site.indent,
    )
    inline_init = _site_in_declaration_window(
        source_text,
        site=first_site,
        scope_open=scope_open,
        scope_end=function_end,
    )
    if inline_init:
        declaration_text = f"{first_site.indent}{type_name} {temp_name} = {rhs};\n"
        return {
            "declaration_insert": None,
            "declaration_text": declaration_text,
            "declaration_line_no": first_site.line_no,
            "declaration_span_text": first_site.line_text.rstrip("\r\n"),
            "initializer_text": declaration_text,
            "first_site_prefix": declaration_text,
            "first_site_start": first_site.start,
            "first_site_line_no": first_site.line_no,
            "first_site_span_text": first_site.line_text.rstrip("\r\n"),
        }

    declaration_text = f"{decl_indent}{type_name} {temp_name};\n"
    initializer_text = f"{first_site.indent}{temp_name} = {rhs};\n"
    first_site_prefix = initializer_text
    insertion = declaration_insert
    if insertion == first_site.start:
        first_site_prefix = declaration_text + initializer_text
        insertion = None
    return {
        "declaration_insert": insertion,
        "declaration_text": declaration_text,
        "declaration_line_no": _line_no(source_text, declaration_insert),
        "declaration_span_text": "",
        "initializer_text": initializer_text,
        "first_site_prefix": first_site_prefix,
        "first_site_start": first_site.start,
        "first_site_line_no": first_site.line_no,
        "first_site_span_text": first_site.line_text.rstrip("\r\n"),
    }


def _materialize_shared_rhs_probe(
    source_text: str,
    *,
    function_start: int,
    function_end: int,
    from_site: _WriteSite,
    to_site: _WriteSite,
    pair_info: Mapping[str, Any],
    force_phys: Mapping[int, int],
) -> tuple[str, dict[str, Any]] | None:
    from_type = _normalize_type_name(from_site.type_name or "")
    to_type = _normalize_type_name(to_site.type_name or "")
    if not from_type or from_type != to_type:
        return None
    if _normalize_expr(from_site.rhs) != _normalize_expr(to_site.rhs):
        return None
    from_virtual = int(pair_info["from_virtual"])
    to_virtual = int(pair_info["to_virtual"])
    temp_name = f"common_subexpr_r{from_virtual}_r{to_virtual}_probe"
    temp = _shared_temp_intro(
        source_text,
        function_start=function_start,
        function_end=function_end,
        first_site=from_site if from_site.start <= to_site.start else to_site,
        type_name=from_type,
        temp_name=temp_name,
        rhs=from_site.rhs,
    )
    if temp is None:
        return None
    edits: list[tuple[int, int, str]] = []
    for site in (from_site, to_site):
        replacement_line = _replace_rhs(site.line_text, site.rhs, temp_name)
        if replacement_line is None:
            return None
        if site.start == temp["first_site_start"]:
            replacement_line = temp["first_site_prefix"] + replacement_line
        edits.append((site.start, site.end, replacement_line))
    if temp["declaration_insert"] is not None:
        edits.append((
            temp["declaration_insert"],
            temp["declaration_insert"],
            temp["declaration_text"],
        ))
    candidate_text = _apply_edits(source_text, edits)
    if candidate_text == source_text:
        return None
    source_hunks = [
        {
            "line_start": temp["declaration_line_no"],
            "line_end": temp["declaration_line_no"],
            "span_text": temp["declaration_span_text"],
            "replacement_text": temp["declaration_text"].rstrip("\n"),
            "kind": "common-subexpr-shared-temp-declaration",
        },
        {
            "line_start": temp["first_site_line_no"],
            "line_end": temp["first_site_line_no"],
            "span_text": temp["first_site_span_text"],
            "replacement_text": temp["initializer_text"].rstrip("\n"),
            "kind": "common-subexpr-shared-temp-initializer",
        },
        {
            "line_start": from_site.line_no,
            "line_end": from_site.line_no,
            "span_text": from_site.line_text.rstrip("\r\n"),
            "replacement_text": _replace_rhs(
                from_site.line_text,
                from_site.rhs,
                temp_name,
            ).rstrip("\r\n"),
            "kind": "common-subexpr-rewrite-from",
        },
        {
            "line_start": to_site.line_no,
            "line_end": to_site.line_no,
            "span_text": to_site.line_text.rstrip("\r\n"),
            "replacement_text": _replace_rhs(
                to_site.line_text,
                to_site.rhs,
                temp_name,
            ).rstrip("\r\n"),
            "kind": "common-subexpr-rewrite-to",
        },
    ]
    attempted_targets = {
        str(ig): int(force_phys[ig])
        for ig in (from_virtual, to_virtual)
        if ig in force_phys
    }
    protected_targets = {
        str(ig): int(phys)
        for ig, phys in sorted(force_phys.items())
        if ig not in {from_virtual, to_virtual}
    }
    payload = {
        "kind": "retained-gpr-common-subexpr-coalesce-source",
        "coalesce_pair": {"from": from_virtual, "to": to_virtual},
        "common_source_virtual": pair_info.get("common_source_virtual"),
        "common_source_bridge": _dict_or_none(pair_info.get("common_source_bridge")),
        "from_bridge": _dict_or_none(pair_info.get("from_bridge")),
        "to_bridge": _dict_or_none(pair_info.get("to_bridge")),
        "from_first_def": pair_info.get("from_first_def"),
        "to_first_def": pair_info.get("to_first_def"),
        "suggestion": pair_info.get("suggestion"),
        "preflight": pair_info.get("preflight"),
        "priority_class": pair_info.get("priority_class"),
        "shared_temp": temp_name,
        "shared_type": from_type,
        "shared_rhs": from_site.rhs,
        "attempted_targets": attempted_targets,
        "protected_targets": protected_targets,
        "source_hunks": source_hunks,
    }
    return candidate_text, payload


def _iter_common_source_owner_candidates(
    source_text: str,
    *,
    function_start: int,
    function_end: int,
    from_site: _WriteSite | None,
    pair_info: Mapping[str, Any],
    force_phys: Mapping[int, int],
) -> tuple[tuple[str, dict[str, Any], tuple[int, int]], ...]:
    common_bridge = pair_info.get("common_source_bridge")
    if not isinstance(common_bridge, Mapping):
        return ()
    common_var = str(common_bridge.get("var") or "")
    if not common_var:
        return ()
    common_source_virtual = pair_info.get("common_source_virtual")
    if common_source_virtual is None:
        return ()
    try:
        common_virtual = int(common_source_virtual)
    except (TypeError, ValueError):
        return ()
    sites = [
        site for site in _find_rhs_write_sites(
            source_text,
            function_start,
            function_end,
            common_var,
        )
        if _is_pointer_type(site.type_name)
    ]
    if len(sites) < 2:
        return ()
    candidates: list[tuple[str, dict[str, Any], tuple[int, int]]] = []
    shared_base = _materialize_common_source_shared_base_probe(
        source_text,
        function_start=function_start,
        function_end=function_end,
        sites=sites,
        common_var=common_var,
        common_virtual=common_virtual,
        pair_info=pair_info,
        force_phys=force_phys,
    )
    if shared_base is not None:
        candidates.append(shared_base)
    reuse_owner = _materialize_common_source_reuse_owner_probe(
        source_text,
        sites=sites,
        common_var=common_var,
        function_start=function_start,
        function_end=function_end,
        from_site=from_site,
        pair_info=pair_info,
        force_phys=force_phys,
    )
    if reuse_owner is not None:
        candidates.append(reuse_owner)
    return tuple(candidates)


def _iter_implicit_common_source_owner_candidates(
    source_text: str,
    *,
    function_start: int,
    function_end: int,
    pair_info: Mapping[str, Any],
    force_phys: Mapping[int, int],
) -> tuple[tuple[str, dict[str, Any], tuple[int, int]], ...]:
    common_source_virtual = pair_info.get("common_source_virtual")
    if common_source_virtual is None:
        return ()
    try:
        common_virtual = int(common_source_virtual)
    except (TypeError, ValueError):
        return ()
    scan = _scan_implicit_common_source_owner_groups(
        source_text,
        function_start,
        function_end,
    )
    if scan.terminal_blocker is not None:
        return ()
    candidates: list[tuple[str, dict[str, Any], tuple[int, int]]] = []
    for common_var, sites in scan.groups:
        site_list = list(sites)
        shared_base = _materialize_common_source_shared_base_probe(
            source_text,
            function_start=function_start,
            function_end=function_end,
            sites=site_list,
            common_var=common_var,
            common_virtual=common_virtual,
            pair_info=pair_info,
            force_phys=force_phys,
        )
        if shared_base is not None:
            candidates.append(_with_source_owner_resolution(shared_base))
        reuse_owner = _materialize_common_source_reuse_owner_probe(
            source_text,
            sites=site_list,
            common_var=common_var,
            function_start=function_start,
            function_end=function_end,
            from_site=None,
            pair_info=pair_info,
            force_phys=force_phys,
        )
        if reuse_owner is not None:
            candidates.append(_with_source_owner_resolution(reuse_owner))
    return tuple(candidates)


def _with_source_owner_resolution(
    candidate: tuple[str, dict[str, Any], tuple[int, int]],
) -> tuple[str, dict[str, Any], tuple[int, int]]:
    candidate_text, payload, span = candidate
    return (
        candidate_text,
        {
            **payload,
            "source_owner_origin": "implicit-repeated-pointer-rhs",
            "source_owner_resolution": "pcode-shared-source-repeated-rhs",
        },
        span,
    )


def _scan_implicit_common_source_owner_groups(
    source_text: str,
    start: int,
    end: int,
) -> _ImplicitSourceOwnerScan:
    by_rhs: dict[str, list[_WriteSite]] = {}
    common_var_by_rhs: dict[str, str] = {}
    for site in _find_all_write_sites(source_text, start, end):
        rhs = site.rhs.strip()
        if not _SIMPLE_IDENTIFIER.fullmatch(rhs):
            continue
        normalized = _normalize_expr(rhs)
        by_rhs.setdefault(normalized, []).append(site)
        common_var_by_rhs.setdefault(normalized, rhs)
    repeated_groups = [
        (common_var_by_rhs[rhs], sites)
        for rhs, sites in by_rhs.items()
        if len(sites) >= 2
    ]
    if not repeated_groups:
        return _ImplicitSourceOwnerScan(
            groups=(),
            terminal_blocker=(
                "common-subexpr-no-source-bridge-and-no-repeated-pointer-rhs"
            ),
        )
    compatible_groups: list[tuple[str, tuple[_WriteSite, ...]]] = []
    saw_type_mismatch = False
    for common_var, sites in repeated_groups:
        pointer_sites = [
            site for site in sites if _is_pointer_type(site.type_name)
        ]
        if len(pointer_sites) < 2:
            saw_type_mismatch = True
            continue
        by_type: dict[str, list[_WriteSite]] = {}
        for site in pointer_sites:
            type_name = _normalize_type_name(site.type_name or "")
            if not type_name:
                saw_type_mismatch = True
                continue
            by_type.setdefault(type_name, []).append(site)
        compatible_for_group = [
            typed_sites for typed_sites in by_type.values()
            if len(typed_sites) >= 2
        ]
        if not compatible_for_group:
            saw_type_mismatch = True
            continue
        compatible_for_group.sort(key=lambda group: group[0].start)
        compatible_groups.append((common_var, tuple(compatible_for_group[0])))
    if compatible_groups:
        compatible_groups.sort(key=lambda item: item[1][0].start)
        return _ImplicitSourceOwnerScan(
            groups=tuple(compatible_groups),
            terminal_blocker=None,
        )
    return _ImplicitSourceOwnerScan(
        groups=(),
        terminal_blocker=(
            "common-subexpr-repeated-rhs-type-mismatch"
            if saw_type_mismatch
            else "common-subexpr-no-source-bridge-and-no-repeated-pointer-rhs"
        ),
    )


def _find_rhs_write_sites(
    source_text: str,
    start: int,
    end: int,
    rhs_var_name: str,
) -> tuple[_WriteSite, ...]:
    decl_init = re.compile(
        r"^(?P<indent>[ \t]*)(?P<type>(?:const\s+|volatile\s+)*"
        r"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w*)(?:\s*\*)*)\s+"
        r"(?P<var>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.+);\s*$"
    )
    assignment = re.compile(
        r"^(?P<indent>[ \t]*)(?P<var>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.+);\s*$"
    )
    out: list[_WriteSite] = []
    rhs_normalized = _normalize_expr(rhs_var_name)
    for line_start, line_end, line in _iter_lines(source_text, start, end):
        stripped_line = line.rstrip("\r\n")
        match = decl_init.match(stripped_line)
        if match is not None and _normalize_expr(match.group("rhs")) == rhs_normalized:
            out.append(_WriteSite(
                var_name=match.group("var"),
                start=line_start,
                end=line_end,
                line_no=_line_no(source_text, line_start),
                line_text=line,
                indent=match.group("indent"),
                rhs=match.group("rhs").strip(),
                type_name=_normalize_type_name(match.group("type")),
                kind="decl-init",
            ))
            continue
        match = assignment.match(stripped_line)
        if match is not None and _normalize_expr(match.group("rhs")) == rhs_normalized:
            var_name = match.group("var")
            out.append(_WriteSite(
                var_name=var_name,
                start=line_start,
                end=line_end,
                line_no=_line_no(source_text, line_start),
                line_text=line,
                indent=match.group("indent"),
                rhs=match.group("rhs").strip(),
                type_name=_find_declaration_type(source_text, start, end, var_name),
                kind="assignment",
            ))
    return tuple(out)


_SIMPLE_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


def _find_all_write_sites(
    source_text: str,
    start: int,
    end: int,
) -> tuple[_WriteSite, ...]:
    decl_init = re.compile(
        r"^(?P<indent>[ \t]*)(?P<type>(?:const\s+|volatile\s+)*"
        r"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w*)(?:\s*\*)*)\s+"
        r"(?P<var>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.+);\s*$"
    )
    assignment = re.compile(
        r"^(?P<indent>[ \t]*)(?P<var>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.+);\s*$"
    )
    out: list[_WriteSite] = []
    for line_start, line_end, line in _iter_lines(source_text, start, end):
        stripped_line = line.rstrip("\r\n")
        match = decl_init.match(stripped_line)
        if match is not None:
            out.append(_WriteSite(
                var_name=match.group("var"),
                start=line_start,
                end=line_end,
                line_no=_line_no(source_text, line_start),
                line_text=line,
                indent=match.group("indent"),
                rhs=match.group("rhs").strip(),
                type_name=_normalize_type_name(match.group("type")),
                kind="decl-init",
            ))
            continue
        match = assignment.match(stripped_line)
        if match is not None:
            var_name = match.group("var")
            out.append(_WriteSite(
                var_name=var_name,
                start=line_start,
                end=line_end,
                line_no=_line_no(source_text, line_start),
                line_text=line,
                indent=match.group("indent"),
                rhs=match.group("rhs").strip(),
                type_name=_find_declaration_type(source_text, start, end, var_name),
                kind="assignment",
            ))
    return tuple(out)


def _materialize_common_source_shared_base_probe(
    source_text: str,
    *,
    function_start: int,
    function_end: int,
    sites: list[_WriteSite],
    common_var: str,
    common_virtual: int,
    pair_info: Mapping[str, Any],
    force_phys: Mapping[int, int],
) -> tuple[str, dict[str, Any], tuple[int, int]] | None:
    first_site = sites[0]
    shared_type = _normalize_type_name(first_site.type_name or "")
    if not shared_type:
        return None
    compatible_sites = [
        site for site in sites
        if _normalize_type_name(site.type_name or "") == shared_type
    ]
    if len(compatible_sites) < 2:
        return None
    temp_name = f"common_source_r{common_virtual}_probe"
    temp = _shared_temp_intro(
        source_text,
        function_start=function_start,
        function_end=function_end,
        first_site=first_site,
        type_name=shared_type,
        temp_name=temp_name,
        rhs=common_var,
    )
    if temp is None:
        return None
    edits: list[tuple[int, int, str]] = []
    for site in compatible_sites:
        replacement_line = _replace_rhs(site.line_text, site.rhs, temp_name)
        if replacement_line is None:
            return None
        if site.start == first_site.start:
            replacement_line = temp["first_site_prefix"] + replacement_line
        edits.append((site.start, site.end, replacement_line))
    if temp["declaration_insert"] is not None:
        edits.append((
            temp["declaration_insert"],
            temp["declaration_insert"],
            temp["declaration_text"],
        ))
    candidate_text = _apply_edits(source_text, edits)
    if candidate_text == source_text:
        return None
    source_hunks = [
        {
            "line_start": temp["declaration_line_no"],
            "line_end": temp["declaration_line_no"],
            "span_text": temp["declaration_span_text"],
            "replacement_text": temp["declaration_text"].rstrip("\n"),
            "kind": "common-subexpr-source-owner-shared-base",
        },
        {
            "line_start": temp["first_site_line_no"],
            "line_end": temp["first_site_line_no"],
            "span_text": temp["first_site_span_text"],
            "replacement_text": temp["initializer_text"].rstrip("\n"),
            "kind": "common-subexpr-source-owner-shared-base-init",
        },
    ]
    source_hunks.extend(
        _rewrite_hunk(site, temp_name, kind="common-subexpr-source-owner-rewrite")
        for site in compatible_sites
    )
    payload = _source_owner_payload(
        pair_info,
        force_phys=force_phys,
        strategy="common-source-shared-base-temp",
        common_var=common_var,
        source_hunks=source_hunks,
        source_owner_candidates=compatible_sites,
    )
    return (
        candidate_text,
        payload,
        (compatible_sites[0].start, compatible_sites[-1].end),
    )


def _materialize_common_source_reuse_owner_probe(
    source_text: str,
    *,
    sites: list[_WriteSite],
    common_var: str,
    function_start: int,
    function_end: int,
    from_site: _WriteSite | None,
    pair_info: Mapping[str, Any],
    force_phys: Mapping[int, int],
) -> tuple[str, dict[str, Any], tuple[int, int]] | None:
    owner_site = from_site if from_site in sites else sites[0]
    owner_type = _normalize_type_name(owner_site.type_name or "")
    if not owner_type:
        return None
    target_site = next(
        (
            site for site in sites
            if site.var_name != owner_site.var_name
            and site.kind == "decl-init"
            and site.start > owner_site.start
            and _normalize_type_name(site.type_name or "") == owner_type
        ),
        None,
    )
    if target_site is None:
        return None
    scope_open = _scope_open_for_site(
        source_text,
        function_start=function_start,
        site=target_site,
    )
    if scope_open is None:
        return None
    scope_end = _scope_end_for_site(
        source_text,
        function_start=function_start,
        function_end=function_end,
        site=target_site,
    )
    if not _site_in_declaration_window(
        source_text,
        site=target_site,
        scope_open=scope_open,
        scope_end=scope_end,
    ):
        return None
    assignment_line = (
        f"{target_site.indent}{owner_site.var_name} = {common_var};\n"
    )
    assignment_insert, _first_statement = _declaration_window(
        source_text,
        scope_open,
        scope_end,
    )
    if assignment_insert < target_site.end or assignment_insert > scope_end:
        return None
    pre_assignment_text = source_text[target_site.end:assignment_insert]
    target_name = re.escape(target_site.var_name)
    if re.search(rf"\b{target_name}\b", pre_assignment_text):
        return None
    post_assignment_text = source_text[assignment_insert:scope_end]
    rewritten_post_assignment_text = re.sub(
        rf"\b{re.escape(target_site.var_name)}\b",
        owner_site.var_name,
        post_assignment_text,
    )
    if rewritten_post_assignment_text == post_assignment_text:
        return None
    rewritten_scope = (
        pre_assignment_text
        + assignment_line
        + rewritten_post_assignment_text
    )
    candidate_text = _apply_edits(
        source_text,
        [
            (target_site.end, scope_end, rewritten_scope),
            (target_site.start, target_site.end, ""),
        ],
    )
    if candidate_text == source_text:
        return None
    source_hunks = [
        {
            "line_start": target_site.line_no,
            "line_end": target_site.line_no,
            "span_text": target_site.line_text.rstrip("\r\n"),
            "replacement_text": "",
            "kind": "common-subexpr-source-owner-remove-replaced-owner",
            "reused_owner": owner_site.var_name,
            "replaced_owner": target_site.var_name,
        },
        {
            "line_start": _line_no(source_text, assignment_insert),
            "line_end": _line_no(source_text, assignment_insert),
            "span_text": "",
            "replacement_text": assignment_line.rstrip("\n"),
            "kind": "common-subexpr-source-owner-reuse-existing-owner",
            "reused_owner": owner_site.var_name,
            "replaced_owner": target_site.var_name,
        },
    ]
    payload = _source_owner_payload(
        pair_info,
        force_phys=force_phys,
        strategy="common-source-reuse-existing-owner",
        common_var=common_var,
        source_hunks=source_hunks,
        source_owner_candidates=[owner_site, target_site],
    )
    return candidate_text, payload, (target_site.start, scope_end)


def _source_owner_payload(
    pair_info: Mapping[str, Any],
    *,
    force_phys: Mapping[int, int],
    strategy: str,
    common_var: str,
    source_hunks: list[dict[str, Any]],
    source_owner_candidates: list[_WriteSite],
) -> dict[str, Any]:
    from_virtual = int(pair_info["from_virtual"])
    to_virtual = int(pair_info["to_virtual"])
    attempted_targets = {
        str(ig): int(force_phys[ig])
        for ig in (from_virtual, to_virtual)
        if ig in force_phys
    }
    protected_targets = {
        str(ig): int(phys)
        for ig, phys in sorted(force_phys.items())
        if ig not in {from_virtual, to_virtual}
    }
    return {
        "kind": "retained-gpr-common-subexpr-coalesce-source",
        "coalesce_pair": {"from": from_virtual, "to": to_virtual},
        "common_source_virtual": pair_info.get("common_source_virtual"),
        "common_source_bridge": _dict_or_none(pair_info.get("common_source_bridge")),
        "from_bridge": _dict_or_none(pair_info.get("from_bridge")),
        "to_bridge": _dict_or_none(pair_info.get("to_bridge")),
        "from_first_def": pair_info.get("from_first_def"),
        "to_first_def": pair_info.get("to_first_def"),
        "suggestion": pair_info.get("suggestion"),
        "preflight": pair_info.get("preflight"),
        "priority_class": pair_info.get("priority_class"),
        "source_owner_strategy": strategy,
        "common_source_var": common_var,
        "attempted_targets": attempted_targets,
        "protected_targets": protected_targets,
        "source_owner_candidates": [
            _site_payload(site) for site in source_owner_candidates
        ],
        "source_hunks": source_hunks,
    }


def _rewrite_hunk(
    site: _WriteSite,
    replacement: str,
    *,
    kind: str,
) -> dict[str, Any]:
    rewritten = _replace_rhs(site.line_text, site.rhs, replacement)
    return {
        "line_start": site.line_no,
        "line_end": site.line_no,
        "span_text": site.line_text.rstrip("\r\n"),
        "replacement_text": (
            rewritten.rstrip("\r\n") if rewritten is not None else None
        ),
        "kind": kind,
        "var": site.var_name,
    }


def _site_payload(site: _WriteSite) -> dict[str, Any]:
    return {
        "var": site.var_name,
        "line": site.line_no,
        "type": site.type_name,
        "rhs": site.rhs,
        "kind": site.kind,
    }


def _is_pointer_type(type_name: str | None) -> bool:
    return "*" in _normalize_type_name(type_name or "")


def _scope_end_for_site(
    source_text: str,
    *,
    function_start: int,
    function_end: int,
    site: _WriteSite,
) -> int:
    open_idx = source_text.rfind("{", function_start, site.start)
    if open_idx < 0:
        return function_end
    depth = 0
    for idx in range(open_idx, function_end):
        char = source_text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return idx
    return function_end


def _replace_rhs(line_text: str, rhs: str, replacement: str) -> str | None:
    index = line_text.rfind(rhs)
    if index < 0:
        return None
    return line_text[:index] + replacement + line_text[index + len(rhs):]


def _apply_edits(source_text: str, edits: list[tuple[int, int, str]]) -> str:
    result = source_text
    for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def _iter_lines(
    text: str,
    start: int,
    end: int,
) -> list[tuple[int, int, str]]:
    lines: list[tuple[int, int, str]] = []
    offset = start
    for line in text[start:end].splitlines(keepends=True):
        line_end = offset + len(line)
        lines.append((offset, line_end, line))
        offset = line_end
    return lines


def _line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _normalize_expr(expr: str) -> str:
    return re.sub(r"\s+", "", expr)


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _bridge_or_none(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _has_bridge_var(value: Any) -> bool:
    return isinstance(value, Mapping) and bool(value.get("var"))


def _dominant_blocker(blockers: list[str]) -> str:
    if not blockers:
        return "common-subexpr-source-span-not-found"
    priority = (
        "common-subexpr-bridge-type-mismatch",
        "common-subexpr-repeated-rhs-type-mismatch",
        "common-subexpr-source-span-not-found",
        "common-subexpr-no-source-bridge-and-no-repeated-pointer-rhs",
        "common-subexpr-bridge-unavailable",
        "common-subexpr-ir-source-mismatch",
    )
    for item in priority:
        if item in blockers:
            return item
    return blockers[0]
