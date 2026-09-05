"""Retained GPR Case-C simplify-order continuation probes."""
from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.search.directed.anchors import Anchor


MUTATOR_KEY = "steer_retained_gpr_case_c_simplify_order_continuation"


@dataclass(frozen=True)
class RetainedCaseCRegion:
    start: int
    end: int
    text: str
    indent: str
    if_start: int
    setup_text: str
    function_start: int
    function_end: int


@dataclass(frozen=True)
class RetainedCaseCReplacement:
    strategy: str
    replacement_text: str
    declaration_text: str = ""
    candidate_text: str | None = None
    source_span: dict[str, Any] | None = None


def _matching_brace_index(source_text: str, open_brace_index: int) -> int | None:
    depth = 0
    in_string: str | None = None
    escape = False
    for index in range(open_brace_index, len(source_text)):
        char = source_text[index]
        if in_string is not None:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = None
            continue
        if char in {'"', "'"}:
            in_string = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _line_start(source_text: str, offset: int) -> int:
    return source_text.rfind("\n", 0, offset) + 1


def _line_end_with_newline(source_text: str, offset: int) -> int:
    end = source_text.find("\n", offset)
    return len(source_text) if end < 0 else end + 1


def _line_number_for_offset(source_text: str, offset: int) -> int:
    return source_text.count("\n", 0, max(0, offset)) + 1


def _previous_line_span(source_text: str, line_start: int) -> tuple[int, int] | None:
    if line_start <= 0:
        return None
    previous_end = line_start - 1
    previous_start = source_text.rfind("\n", 0, previous_end) + 1
    return previous_start, previous_end


def _is_setup_assignment(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    if any(token in stripped for token in ("{", "}", "++", "--")):
        return False
    if re.match(r"(?:if|for|while|switch|return|break|continue)\b", stripped):
        return False
    return re.match(r"[A-Za-z_]\w*\s*=", stripped) is not None and stripped.endswith(";")


def _setup_start_for_if(source_text: str, if_line_start: int) -> int:
    setup_start = if_line_start
    cursor = if_line_start
    while True:
        span = _previous_line_span(source_text, cursor)
        if span is None:
            return setup_start
        start, end = span
        line = source_text[start:end]
        if not _is_setup_assignment(line):
            return setup_start
        setup_start = start
        cursor = start


def _iter_retained_case_c_regions(
    source_text: str,
    *,
    function_start: int,
    function_end: int,
) -> Iterable[RetainedCaseCRegion]:
    search_text = source_text[function_start:function_end]
    for match in re.finditer(r"\bif\s*\(", search_text):
        if_start = function_start + match.start()
        open_brace = source_text.find("{", if_start, function_end)
        if open_brace < 0:
            continue
        condition_text = source_text[if_start:open_brace]
        if "GetNameText" not in condition_text or "totals[" not in condition_text:
            continue
        close_brace = _matching_brace_index(source_text, open_brace)
        if close_brace is None or close_brace > function_end:
            continue
        if_body = source_text[open_brace:close_brace + 1]
        if "max_idx = j" not in if_body:
            continue
        if_line_start = _line_start(source_text, if_start)
        start = _setup_start_for_if(source_text, if_line_start)
        end = _line_end_with_newline(source_text, close_brace)
        line = source_text[if_line_start:source_text.find("\n", if_line_start)]
        indent = line[: len(line) - len(line.lstrip(" \t"))]
        yield RetainedCaseCRegion(
            start=start,
            end=end,
            text=source_text[start:end],
            indent=indent,
            if_start=if_line_start,
            setup_text=source_text[start:if_line_start],
            function_start=function_start,
            function_end=function_end,
        )


def _source_diff(before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="source",
            tofile="retained-case-c-simplify-order",
            n=3,
        )
    )


def _source_hunk(before: str, after: str, *, strategy: str) -> dict[str, Any]:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        return {
            "strategy": strategy,
            "tag": tag,
            "base_start": i1,
            "base_end": i2,
            "candidate_start": j1,
            "candidate_end": j2,
            "removed": before_lines[i1:i2],
            "added": after_lines[j1:j2],
        }
    return {
        "strategy": strategy,
        "tag": "equal",
        "base_start": 0,
        "base_end": 0,
        "candidate_start": 0,
        "candidate_end": 0,
        "removed": [],
        "added": [],
    }


def _replace_before_max_update(
    text: str,
    pattern: str,
    replacement: str | Callable[[re.Match[str]], str],
) -> str:
    marker = "max_idx = j"
    marker_index = text.find(marker)
    prefix = text if marker_index < 0 else text[:marker_index]
    suffix = "" if marker_index < 0 else text[marker_index:]
    return re.sub(pattern, replacement, prefix) + suffix


def _indexed_array_pattern(index_name: str) -> str:
    return (
        r"(?P<base>[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)*)"
        r"\s*\[\s*\(?\s*(?:0\s*,\s*)?"
        rf"{re.escape(index_name)}"
        r"\s*\)?\s*\]"
    )


def _first_indexed_array_expr_before_update(
    text: str,
    *,
    index_name: str,
) -> str | None:
    marker_index = text.find("max_idx = j")
    prefix = text if marker_index < 0 else text[:marker_index]
    match = re.search(_indexed_array_pattern(index_name), prefix)
    return match.group(0) if match is not None else None


def _replace_indexed_array_indices_before_update(
    text: str,
    *,
    index_name: str,
    replacement_index: str,
) -> str:
    pattern = _indexed_array_pattern(index_name)

    def replace_index(match: re.Match[str]) -> str:
        return f"{match.group('base')}[{replacement_index}]"

    return _replace_before_max_update(text, pattern, replace_index)


def _replace_array_expr_before_update(
    text: str,
    *,
    index_name: str,
    replacement: str,
) -> str:
    return _replace_before_max_update(
        text,
        _indexed_array_pattern(index_name),
        replacement,
    )


def _insert_prelude(region: RetainedCaseCRegion, prelude_lines: list[str]) -> str:
    return "".join(f"{region.indent}{line}\n" for line in prelude_lines) + region.text


def _prelude_text(region: RetainedCaseCRegion, prelude_lines: list[str]) -> str:
    return "".join(f"{region.indent}{line}\n" for line in prelude_lines)


def _function_declaration_insert_index(source_text: str, region: RetainedCaseCRegion) -> int | None:
    open_brace = source_text.find("{", region.function_start, region.function_end)
    if open_brace < 0:
        return None
    return open_brace + 1


def _block_scope(region: RetainedCaseCRegion) -> str:
    suffix = "" if region.text.endswith("\n") else "\n"
    return f"{region.indent}{{\n{region.text}{suffix}{region.indent}}}\n"


def _move_setup_line_near_if(region: RetainedCaseCRegion) -> str | None:
    if not region.setup_text:
        return None
    lines = region.setup_text.splitlines(keepends=True)
    target_index = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if "max_idx" in stripped and "=" in stripped and stripped.endswith(";"):
            target_index = index
            break
    if target_index is None or target_index == len(lines) - 1:
        return None
    moved = lines.pop(target_index)
    lines.append(moved)
    return "".join(lines) + region.text[len(region.setup_text):]


def _candidate_anchor(
    source_text: str,
    region: RetainedCaseCRegion,
    *,
    replacement: RetainedCaseCReplacement,
    candidate_text: str,
    goal: Mapping[str, Any],
    force_phys: Mapping[int, int],
) -> Anchor | None:
    if candidate_text == source_text:
        return None
    try:
        target_ig = int(goal.get("target_ig", 44))
    except (TypeError, ValueError):
        target_ig = 44
    target_phys = goal.get("target_phys")
    if target_phys is None:
        target_phys = force_phys.get(target_ig)
    try:
        target_phys = int(target_phys) if target_phys is not None else None
    except (TypeError, ValueError):
        target_phys = None
    protected_targets = goal.get("protected_targets")
    if not isinstance(protected_targets, Mapping):
        protected_targets = {
            str(ig): int(phys)
            for ig, phys in sorted(force_phys.items())
            if ig != target_ig
        }
    else:
        protected_targets = {
            str(key): int(value)
            for key, value in protected_targets.items()
            if str(value).lstrip("-").isdigit()
        }
    attempted_targets: dict[str, int] = {}
    try:
        if target_phys is not None:
            attempted_targets[str(target_ig)] = int(target_phys)
    except (TypeError, ValueError):
        attempted_targets = {}
    final_force_phys = goal.get("final_force_phys")
    if not isinstance(final_force_phys, Mapping):
        final_force_phys = force_phys
    final_force_phys = {
        str(key): int(value)
        for key, value in final_force_phys.items()
        if str(value).lstrip("-").isdigit()
    }
    source_span = replacement.source_span or {
        "kind": (
            "case-c-max-index-probe"
            if _goal_is_lower_drift_residual(goal)
            else "case-c-simplify-order"
        ),
        "start_line": _line_number_for_offset(source_text, region.start),
        "unsupported_reason": None,
    }
    return Anchor(
        mutator_key=MUTATOR_KEY,
        span=(region.start, region.end),
        payload={
            "span_text": region.text,
            "replacement_text": replacement.replacement_text,
            "candidate_text": candidate_text,
            "strategy": replacement.strategy,
            "source_hunk": _source_hunk(
                source_text,
                candidate_text,
                strategy=replacement.strategy,
            ),
            "source_diff": _source_diff(source_text, candidate_text),
            "goal_kind": goal.get("kind"),
            "target_ig": target_ig,
            "target_phys": target_phys,
            "protected_targets": protected_targets,
            "attempted_targets": attempted_targets,
            "final_force_phys": final_force_phys,
            "baseline_pcdump_path": goal.get("baseline_pcdump_path"),
            "baseline_first_divergence": goal.get("baseline_first_divergence", {
                "class_id": 0,
                "iter": 40,
                "ig_idx": 44,
                "case": "C",
            }),
            "baseline_score": goal.get("baseline_score"),
            "source_span": source_span,
            "source_probe_provenance_kind": (
                "retained-case-c-lower-drift-residual"
                if _goal_is_lower_drift_residual(goal)
                else "retained-case-c-simplify-order-continuation"
            ),
        },
    )


def _candidate_replacements(
    source_text: str,
    region: RetainedCaseCRegion,
) -> list[RetainedCaseCReplacement]:
    candidates: list[RetainedCaseCReplacement] = []

    max_alias = _prelude_text(
        region,
        ["case_c_max_idx_probe = max_idx;"],
    ) + _replace_indexed_array_indices_before_update(
        region.text,
        index_name="max_idx",
        replacement_index="case_c_max_idx_probe",
    )
    candidates.append(RetainedCaseCReplacement(
        "case-c-max-index-alias",
        max_alias,
        "int case_c_max_idx_probe;\n",
    ))

    max_expr = _first_indexed_array_expr_before_update(
        region.text,
        index_name="max_idx",
    )
    if max_expr is not None:
        max_reload = _prelude_text(
            region,
            [f"case_c_max_name_probe = {max_expr};"],
        ) + _replace_array_expr_before_update(
            region.text,
            index_name="max_idx",
            replacement="case_c_max_name_probe",
        )
        candidates.append(RetainedCaseCReplacement(
            "case-c-max-name-reload",
            max_reload,
            "u8 case_c_max_name_probe;\n",
        ))

    j_expr = _first_indexed_array_expr_before_update(region.text, index_name="j")
    if j_expr is not None:
        j_reload = _prelude_text(
            region,
            [f"case_c_j_name_probe = {j_expr};"],
        ) + _replace_array_expr_before_update(
            region.text,
            index_name="j",
            replacement="case_c_j_name_probe",
        )
        candidates.append(RetainedCaseCReplacement(
            "case-c-j-name-reload",
            j_reload,
            "u8 case_c_j_name_probe;\n",
        ))

    moved_setup = _move_setup_line_near_if(region)
    if moved_setup is not None:
        candidates.append(RetainedCaseCReplacement(
            "case-c-max-setup-near-if",
            moved_setup,
        ))

    scoped = _block_scope(region)
    candidates.append(RetainedCaseCReplacement("case-c-compare-block-scope", scoped))

    if "sorted_names[(max_idx)]" not in region.text:
        candidates.append(RetainedCaseCReplacement(
            "case-c-same-line-max-index-parens",
            region.text.replace("sorted_names[max_idx]", "sorted_names[(max_idx)]"),
            "",
        ))
    else:
        candidates.append(RetainedCaseCReplacement(
            "case-c-same-line-max-index-normalize",
            region.text.replace("sorted_names[(max_idx)]", "sorted_names[max_idx]"),
            "",
        ))
    return candidates


def _goal_is_lower_drift_residual(goal: Mapping[str, Any]) -> bool:
    kind = goal.get("kind")
    if kind == "retained-case-c-lower-drift-residual":
        return True
    try:
        target_ig = int(goal.get("target_ig"))
    except (TypeError, ValueError):
        return False
    protected = goal.get("protected_targets")
    if not isinstance(protected, Mapping):
        return False
    try:
        protected_ig44 = int(protected.get("44", protected.get(44)))
    except (TypeError, ValueError):
        return False
    return target_ig == 34 and protected_ig44 == 26


def _candidate_with_region_replacement(
    source_text: str,
    region: RetainedCaseCRegion,
    replacement_text: str,
    declaration_text: str = "",
) -> str:
    return _candidate_source_text(
        source_text,
        region,
        replacement_text=replacement_text,
        declaration_text=declaration_text,
    )


def _move_case_c_probe_decl_near_dst_iter(
    source_text: str,
    region: RetainedCaseCRegion,
) -> str | None:
    function_text = source_text[region.function_start:region.function_end]
    decl_match = re.search(
        r"(?m)^[ \t]*int\s+case_c_max_idx_probe\s*;\n",
        function_text,
    )
    dst_iter_match = re.search(
        r"(?m)^[ \t]*(?:u8\s*\*|[A-Za-z_]\w+\s*\*)\s*dst_iter\s*;\n",
        function_text,
    )
    if decl_match is None or dst_iter_match is None:
        return None
    decl_start = region.function_start + decl_match.start()
    decl_end = region.function_start + decl_match.end()
    dst_iter_start = region.function_start + dst_iter_match.start()
    if decl_start == dst_iter_start:
        return None
    decl_line = source_text[decl_start:decl_end]
    without_decl = source_text[:decl_start] + source_text[decl_end:]
    insert_at = dst_iter_start
    if decl_start < dst_iter_start:
        insert_at -= len(decl_line)
    candidate = without_decl[:insert_at] + decl_line + without_decl[insert_at:]
    return candidate if candidate != source_text else None


def _insert_case_c_probe_reload_before_next_use(
    region: RetainedCaseCRegion,
) -> str | None:
    assignment = re.search(r"\bcase_c_max_idx_probe\s*=\s*max_idx\s*;", region.text)
    if assignment is None:
        return None
    next_use = re.search(r"\bcase_c_max_idx_probe\b", region.text[assignment.end():])
    if next_use is None:
        return None
    use_offset = assignment.end() + next_use.start()
    use_line_start = _line_start(region.text, use_offset)
    return (
        region.text[:use_line_start]
        + f"{region.indent}case_c_max_idx_probe = max_idx;\n"
        + region.text[use_line_start:]
    )


def _insert_case_c_probe_reload_near_null_check(
    region: RetainedCaseCRegion,
) -> str | None:
    null_check = re.search(r"GetNameText\s*\([^)]*case_c_max_idx_probe", region.text)
    if null_check is None:
        return None
    enclosing_ifs = list(
        re.finditer(r"(?m)^[ \t]*if\s*\(", region.text[:null_check.start()])
    )
    line_start = (
        enclosing_ifs[-1].start()
        if enclosing_ifs
        else _line_start(region.text, null_check.start())
    )
    return (
        region.text[:line_start]
        + f"{region.indent}case_c_max_idx_probe = max_idx;\n"
        + region.text[line_start:]
    )


def _residual_candidate_replacements(
    source_text: str,
    region: RetainedCaseCRegion,
) -> list[RetainedCaseCReplacement]:
    if "case_c_max_idx_probe" not in source_text:
        return []

    line = _line_number_for_offset(source_text, region.start)
    source_span = {
        "kind": "case-c-max-index-probe",
        "start_line": line,
        "unsupported_reason": None,
    }
    candidates: list[RetainedCaseCReplacement] = []

    moved_decl = _move_case_c_probe_decl_near_dst_iter(source_text, region)
    if moved_decl is not None:
        candidates.append(RetainedCaseCReplacement(
            "case-c-max-index-probe-decl-before-dst-iter",
            region.text,
            candidate_text=moved_decl,
            source_span=source_span,
        ))

    candidates.append(RetainedCaseCReplacement(
        "case-c-max-index-probe-block-scope",
        _block_scope(region),
        source_span=source_span,
    ))

    reload_near_first_use = _insert_case_c_probe_reload_before_next_use(region)
    if reload_near_first_use is not None:
        candidates.append(RetainedCaseCReplacement(
            "case-c-max-index-probe-reload-near-first-use",
            reload_near_first_use,
            source_span=source_span,
        ))

    reload_near_null_check = _insert_case_c_probe_reload_near_null_check(region)
    if reload_near_null_check is not None:
        candidates.append(RetainedCaseCReplacement(
            "case-c-max-index-probe-reload-near-null-check",
            reload_near_null_check,
            source_span=source_span,
        ))

    anchored = re.sub(
        r"\bcase_c_max_idx_probe\s*=\s*max_idx\s*;",
        "case_c_max_idx_probe = (0, max_idx);",
        region.text,
        count=1,
    )
    if anchored != region.text:
        candidates.append(RetainedCaseCReplacement(
            "case-c-preserve-ig44-alias-window",
            anchored,
            source_span=source_span,
        ))

    if re.search(r"\bdst_iter\b", source_text):
        dst_iter_anchor = _prelude_text(
            region,
            ["case_c_dst_iter_anchor_probe = dst_iter;"],
        ) + region.text
        candidates.append(RetainedCaseCReplacement(
            "case-c-dst-iter-lifetime-anchor",
            dst_iter_anchor,
            "u8* case_c_dst_iter_anchor_probe;\n",
            source_span={
                "kind": "case-c-dst-iter-lifetime",
                "start_line": line,
                "unsupported_reason": None,
            },
        ))

    return candidates


def _candidate_source_text(
    source_text: str,
    region: RetainedCaseCRegion,
    *,
    replacement_text: str,
    declaration_text: str,
) -> str:
    result = source_text[:region.start] + replacement_text + source_text[region.end:]
    if not declaration_text:
        return result
    insert_at = _function_declaration_insert_index(result, region)
    if insert_at is None:
        return result
    decl_indent = "    " if len(region.indent) > 4 else region.indent or "    "
    indented = "".join(
        f"{decl_indent}{line}" for line in declaration_text.splitlines(keepends=True)
    )
    if result[insert_at:insert_at + len(indented)] == indented:
        return result
    return result[:insert_at] + "\n" + indented + result[insert_at:]


def iter_retained_case_c_simplify_order_anchors(
    source_text: str,
    *,
    function_span: tuple[int, int],
    goals: Iterable[Mapping[str, Any]],
    force_phys: Mapping[int, int],
    max_candidates: int,
) -> list[Anchor]:
    """Generate bounded retained-source Case-C simplify-order anchors."""

    function_start, function_end = function_span
    anchors: list[Anchor] = []
    seen: set[str] = set()
    goal_list = list(goals)
    for region in _iter_retained_case_c_regions(
        source_text,
        function_start=function_start,
        function_end=function_end,
    ):
        for goal in goal_list:
            replacements = (
                _residual_candidate_replacements(source_text, region)
                if _goal_is_lower_drift_residual(goal)
                else _candidate_replacements(source_text, region)
            )
            for replacement in replacements:
                candidate_text = replacement.candidate_text
                if candidate_text is None:
                    candidate_text = _candidate_with_region_replacement(
                        source_text,
                        region,
                        replacement.replacement_text,
                        replacement.declaration_text,
                    )
                anchor = _candidate_anchor(
                    source_text,
                    region,
                    replacement=replacement,
                    candidate_text=candidate_text,
                    goal=goal,
                    force_phys=force_phys,
                )
                if anchor is None:
                    continue
                key = anchor.payload["candidate_text"]
                if key in seen:
                    continue
                seen.add(key)
                anchors.append(anchor)
                if len(anchors) >= max_candidates:
                    return anchors
    return anchors


def retained_case_c_simplify_order_match_diagnostics(
    body_text: str,
    *,
    anchors: list[Anchor],
    goals: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    goal_list = list(goals)
    strategies = sorted(
        {
            str(anchor.payload.get("strategy"))
            for anchor in anchors
            if anchor.payload.get("strategy")
        }
    )
    blocked_spans: list[dict[str, Any]] = []
    rejection_reasons: list[str] = []
    if any(_goal_is_lower_drift_residual(goal) for goal in goal_list):
        if "case_c_max_idx_probe" not in body_text:
            rejection_reasons.append("blocked-missing-case-c-max-idx-probe")
            blocked_spans.append({
                "kind": "case-c-max-index-probe",
                "unsupported_reason": "blocked-missing-case-c-max-idx-probe",
            })
        if "dst_iter" not in body_text:
            blocked_spans.append({
                "kind": "case-c-dst-iter-lifetime",
                "unsupported_reason": "blocked-ambiguous-dst-iter-owner",
            })
    if not anchors and not rejection_reasons:
        rejection_reasons.append("source-pattern-not-found")
    return {
        "goals": [dict(goal) for goal in goal_list],
        "goal_count": len(goal_list),
        "case_c_if_count": len(re.findall(r"\bif\s*\([^{}]*GetNameText", body_text)),
        "materializable_anchor_count": len(anchors),
        "generated_strategies": strategies,
        "blocked_source_spans": blocked_spans,
        "rejection_reasons": rejection_reasons if not anchors else rejection_reasons,
    }
