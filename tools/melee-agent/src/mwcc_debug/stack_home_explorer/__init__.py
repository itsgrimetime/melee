from __future__ import annotations

from ._helpers import *  # noqa: F403

def explore_stack_homes(
    pcdump_text: str,
    function: str,
    localizer: dict[str, Any],
    *,
    source_text: str | None = None,
    source_file: str | None = None,
    neighbor_window: int = 16,
    max_suggestions: int = 5,
) -> dict[str, Any]:
    """Build source-shape guidance for stack-home-only spill mismatches."""
    bridge = explain_stack_slot_localizer(
        pcdump_text,
        function,
        localizer,
        source_text=source_text,
        source_file=source_file,
    )
    bridge_candidates = list(bridge.get("candidates") or [])
    candidates = [
        candidate
        for candidate in bridge_candidates
        if _is_stack_home_candidate(candidate)
    ]
    lifetimes = _explain_lifetimes(
        pcdump_text,
        function,
        candidates,
        source_text=source_text,
        source_file=source_file,
    )

    targets = [
        _target_report(
            candidate,
            all_candidates=bridge_candidates,
            lifetimes=lifetimes,
            neighbor_window=neighbor_window,
            max_suggestions=max_suggestions,
        )
        for candidate in candidates
    ]
    targets.sort(key=_target_sort_key, reverse=True)
    for rank, target in enumerate(targets, start=1):
        target["rank"] = rank

    status = "ok" if targets else bridge.get("status", "no-candidates")
    return {
        "status": status,
        "function": function,
        "target_count": len(targets),
        "targets": targets,
        "ranking": {
            "primary_objective": "target-stack-home-offset",
            "target_movement_measured": False,
            "overall_match_percent_used": False,
            "note": (
                "Suggestions are ranked by target offset evidence before "
                "overall match percent because no variants were compiled."
            ),
        },
        "bridge": {
            "status": bridge.get("status"),
            "candidate_count": bridge.get("candidate_count", 0),
        },
    }


def render_stack_home_report_text(report: dict[str, Any]) -> str:
    lines = [
        f"stack-home explorer - {report.get('function')}",
        f"status: {report.get('status')}",
    ]
    targets = report.get("targets") or []
    if not targets:
        lines.append("no final-only stack-home targets found")
        return "\n".join(lines)
    for target in targets:
        current = _format_offset(target.get("current_offset"))
        expected = _format_offset(target.get("expected_offset"))
        lines.append("")
        lines.append(
            f"target #{target.get('rank')}: {target.get('opcode')} "
            f"{target.get('virtual_token')} -> {target.get('assigned_reg')} "
            f"{target.get('register_class_name')} "
            f"{current} -> {expected}"
        )
        source = target.get("source_expression") or {}
        expression = source.get("expression")
        if expression:
            lines.append(f"  source: {expression}")
        lifetime = target.get("lifetime") or {}
        first = lifetime.get("first_occurrence") or {}
        last = lifetime.get("last_occurrence") or {}
        if first:
            lines.append(
                "  first: "
                f"B{first.get('block_idx')}:{first.get('instr_idx')} "
                f"{first.get('opcode')} {first.get('operands')}"
            )
        if last and last != first:
            lines.append(
                "  last:  "
                f"B{last.get('block_idx')}:{last.get('instr_idx')} "
                f"{last.get('opcode')} {last.get('operands')}"
            )
        aliases = target.get("aliases") or {}
        natural = aliases.get("natural") or []
        if natural:
            rendered = ", ".join(
                f"f{item.get('alias')}->f{item.get('root')}"
                for item in natural
            )
            lines.append(f"  natural aliases: {rendered}")
        neighbors = target.get("neighboring_stack_homes") or []
        if neighbors:
            rendered = ", ".join(
                f"{_format_offset(item.get('offset'))}:{item.get('role')}"
                for item in neighbors
            )
            lines.append(f"  neighboring homes: {rendered}")
        suggestions = target.get("suggestions") or []
        if suggestions:
            lines.append("  suggestions:")
            for suggestion in suggestions:
                lines.append(
                    f"    {suggestion.get('rank')}. {suggestion.get('kind')}: "
                    f"{suggestion.get('description')}"
                )
                sketch = suggestion.get("edit_sketch")
                if sketch:
                    lines.append(f"       sketch: {sketch}")
    rankings = report.get("variant_rankings") or []
    if rankings:
        lines.append("")
        lines.append("seeded variant rankings:")
        for variant in rankings:
            objective = variant.get("target_objective") or {}
            match = objective.get("overall_match_percent")
            match_text = "?" if match is None else f"{match:.5f}"
            lines.append(
                f"  {variant.get('rank')}. {variant.get('variant_id')} "
                f"target_fixed={objective.get('target_fixed')} "
                f"match={match_text}"
            )
            summary = variant.get("summary")
            if summary:
                lines.append(f"     {summary}")
    return "\n".join(lines)


def generate_local_array_sqrt_variants(
    source_text: str,
    function: str,
    *,
    max_variants: int | None = None,
) -> list[dict[str, Any]]:
    """Seed known sqrtf local-array stack-layout variants."""
    bounds = _find_function_bounds(source_text, function)
    if bounds is None:
        return []
    fn_start, fn_end = bounds
    function_text = source_text[fn_start:fn_end]
    assignment = _find_first_sqrt_assignment(function_text)
    if assignment is None:
        return []

    specs = [
        ("local-array-sqrt-slot-1-index-0", 1, 0, "function-top"),
        ("local-array-sqrt-slot-2-index-1", 2, 1, "function-top"),
        ("branch-local-array-sqrt-slot-1-index-0", 1, 0, "branch-local"),
        ("branch-local-array-sqrt-slot-2-index-1", 2, 1, "branch-local"),
    ]
    variants: list[dict[str, Any]] = []
    for variant_id, array_size, index, placement in specs:
        candidate_function = _apply_sqrt_array_variant(
            function_text,
            assignment,
            array_size=array_size,
            index=index,
            placement=placement,
        )
        if candidate_function is None:
            continue
        candidate_source = source_text[:fn_start] + candidate_function + source_text[fn_end:]
        variants.append({
            "id": variant_id,
            "kind": "local-array-sqrt-slot",
            "description": (
                f"local float array around sqrtf ({placement}, "
                f"f32 sqrt_slot[{array_size}], index {index})"
            ),
            "placement": placement,
            "array_size": array_size,
            "index": index,
            "candidate_source": candidate_source,
            "source_patch": "\n".join(difflib.unified_diff(
                source_text.splitlines(),
                candidate_source.splitlines(),
                fromfile="source.c",
                tofile=f"{variant_id}.c",
                lineterm="",
            )),
        })
        if max_variants is not None and len(variants) >= max_variants:
            break
    return variants


def attach_variant_rankings(
    report: dict[str, Any],
    variant_results: list[dict[str, Any]],
    *,
    source_text: str | None = None,
    function: str | None = None,
) -> dict[str, Any]:
    ranked = rank_stack_home_variant_results(
        report.get("targets") or [],
        variant_results,
        source_text=source_text,
        function=function or report.get("function"),
    )
    report["variant_rankings"] = ranked
    report["ranking"]["target_movement_measured"] = bool(ranked)
    report["ranking"]["overall_match_percent_used"] = bool(ranked)
    if ranked:
        report["ranking"]["note"] = (
            "Variants are ranked by target stack-slot movement first, then "
            "overall match percent."
        )
    return report


def rank_stack_home_variant_results(
    targets: list[dict[str, Any]],
    variant_results: list[dict[str, Any]],
    *,
    source_text: str | None = None,
    function: str | None = None,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for result in variant_results:
        objective = _variant_target_objective(targets, result)
        local_layout = _variant_local_layout_deltas(
            targets,
            result,
            source_text=source_text,
            function=function,
        )
        item = {
            "variant_id": result.get("variant_id") or result.get("id"),
            "kind": result.get("kind"),
            "description": result.get("description"),
            "target_objective": objective,
            "match_percent_error": result.get("match_percent_error"),
            "stack_slot_error": result.get("stack_slot_error"),
            "remaining_stack_slot_deltas": _remaining_stack_slot_deltas(
                result.get("stack_slot_localizer"),
            ),
            "raw_local_deltas": local_layout["raw"],
            "named_local_deltas": (
                result.get("named_local_deltas")
                or local_layout["named"]
            ),
            "source_patch": result.get("source_patch"),
        }
        item["summary"] = _variant_summary(item)
        ranked.append(item)

    ranked.sort(key=_variant_sort_key, reverse=True)
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    return ranked


def _variant_target_objective(
    targets: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, Any]:
    localizer = result.get("stack_slot_localizer")
    fixed = 0
    statuses: list[dict[str, Any]] = []
    for target in targets:
        current = _int_or_none(target.get("current_offset"))
        expected = _int_or_none(target.get("expected_offset"))
        opcode = target.get("opcode")
        # A target is fixed only when no remaining mismatch exists for its
        # (opcode, expected_offset) regardless of the variant's measured
        # current_offset. A localizer mismatch by construction means
        # current != expected, so the absence of any (opcode, expected)
        # mismatch means the slot reached the expected offset. Keying on the
        # baseline current_offset would miss a slot that merely moved to a
        # different still-wrong offset.
        observed = _find_matching_mismatch(localizer, opcode, expected)
        target_fixed = observed is None
        fixed += 1 if target_fixed else 0
        statuses.append({
            "opcode": opcode,
            "virtual_token": target.get("virtual_token"),
            "baseline_current_offset": current,
            "expected_offset": expected,
            "target_fixed": target_fixed,
            "observed_mismatch": observed,
        })
    target_count = len(targets)
    movement_score = fixed / target_count if target_count else 0.0
    return {
        "fixed_count": fixed,
        "target_count": target_count,
        "target_fixed": bool(target_count) and fixed == target_count,
        "movement_score": movement_score,
        "target_statuses": statuses,
        "overall_match_percent": result.get("match_percent"),
        "target_movement_measured": True,
    }


def _find_matching_mismatch(
    localizer: Any,
    opcode: Any,
    expected: int | None,
) -> dict[str, Any] | None:
    if not isinstance(localizer, dict):
        return None
    for mismatch in localizer.get("mismatches") or []:
        if not isinstance(mismatch, dict):
            continue
        if str(mismatch.get("opcode")).lower() != str(opcode).lower():
            continue
        if _int_or_none(mismatch.get("expected_offset")) != expected:
            continue
        return dict(mismatch)
    return None


def _remaining_stack_slot_deltas(localizer: Any) -> list[dict[str, Any]]:
    if not isinstance(localizer, dict):
        return []
    out: list[dict[str, Any]] = []
    for mismatch in localizer.get("mismatches") or []:
        if not isinstance(mismatch, dict):
            continue
        out.append({
            "opcode": mismatch.get("opcode"),
            "current_offset": mismatch.get("current_offset"),
            "expected_offset": mismatch.get("expected_offset"),
            "delta": mismatch.get("delta"),
        })
    return out


def _variant_local_layout_deltas(
    targets: list[dict[str, Any]],
    result: dict[str, Any],
    *,
    source_text: str | None,
    function: str | None,
) -> dict[str, list[dict[str, Any]]]:
    raw: list[dict[str, Any]] = []
    for mismatch in _variant_stack_mismatches(result):
        if _matches_target_stack_slot(targets, mismatch):
            continue
        expected = _int_or_none(mismatch.get("expected_offset"))
        current = _int_or_none(mismatch.get("current_offset"))
        if expected is None or current is None or expected == current:
            continue
        raw.append({
            "opcode": mismatch.get("opcode"),
            "expected_offset": expected,
            "current_offset": current,
            "delta": expected - current,
            "line_index": mismatch.get("line_index"),
        })

    named = _name_local_deltas_from_context(
        raw,
        result.get("checkdiff_payload"),
        source_text=source_text,
        function=function,
    )
    return {"raw": raw, "named": named}


def _variant_stack_mismatches(result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = result.get("checkdiff_payload")
    if isinstance(payload, dict):
        target_asm = payload.get("target_asm") or payload.get("reference_asm")
        current_asm = payload.get("current_asm")
        if isinstance(target_asm, list) and isinstance(current_asm, list):
            mismatches = _stack_mismatches_from_asm_lines(target_asm, current_asm)
            if mismatches:
                return mismatches
        localizer = _find_stack_slot_localizer_in_payload(payload)
        if localizer is not None:
            return [
                dict(item)
                for item in localizer.get("mismatches") or []
                if isinstance(item, dict)
            ]

    localizer = result.get("stack_slot_localizer")
    if isinstance(localizer, dict):
        return [
            dict(item)
            for item in localizer.get("mismatches") or []
            if isinstance(item, dict)
        ]
    return []


def _stack_mismatches_from_asm_lines(
    target_asm: list[Any],
    current_asm: list[Any],
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for line_index, (expected_line, current_line) in enumerate(
        zip(target_asm, current_asm)
    ):
        expected_body = _asm_instruction_body(expected_line)
        current_body = _asm_instruction_body(current_line)
        if expected_body == current_body:
            continue
        expected_slots = _ASM_STACK_SLOT_RE.findall(expected_body)
        current_slots = _ASM_STACK_SLOT_RE.findall(current_body)
        if len(expected_slots) != 1 or len(current_slots) != 1:
            continue
        expected_offset = _int_or_none(expected_slots[0])
        current_offset = _int_or_none(current_slots[0])
        if (
            expected_offset is None
            or current_offset is None
            or expected_offset < 0
            or current_offset < 0
            or expected_offset == current_offset
        ):
            continue
        expected_opcode = expected_body.split(None, 1)[0] if expected_body.split() else ""
        current_opcode = current_body.split(None, 1)[0] if current_body.split() else ""
        if expected_opcode != current_opcode:
            continue
        mismatches.append({
            "line_index": line_index,
            "expected_offset": expected_offset,
            "current_offset": current_offset,
            "delta": expected_offset - current_offset,
            "opcode": expected_opcode,
            "expected": expected_body,
            "current": current_body,
        })
    return mismatches


def _asm_instruction_body(line: Any) -> str:
    body = str(line).strip()
    return re.sub(
        r"^\+\w+:\s+(?:(?:[0-9A-Fa-f]{2})\s+){4}",
        "",
        body,
    ).strip()


def _find_stack_slot_localizer_in_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        localizer = value.get("stack_slot_localizer")
        if isinstance(localizer, dict):
            return localizer
        for child in value.values():
            found = _find_stack_slot_localizer_in_payload(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_stack_slot_localizer_in_payload(child)
            if found is not None:
                return found
    return None


def _matches_target_stack_slot(
    targets: list[dict[str, Any]],
    mismatch: dict[str, Any],
) -> bool:
    opcode = str(mismatch.get("opcode")).lower()
    expected = _int_or_none(mismatch.get("expected_offset"))
    current = _int_or_none(mismatch.get("current_offset"))
    return any(
        str(target.get("opcode")).lower() == opcode
        and _int_or_none(target.get("expected_offset")) == expected
        and _int_or_none(target.get("current_offset")) == current
        for target in targets
    )


def _name_local_deltas_from_context(
    raw_deltas: list[dict[str, Any]],
    checkdiff_payload: Any,
    *,
    source_text: str | None,
    function: str | None,
) -> list[dict[str, Any]]:
    if not raw_deltas or not source_text or not isinstance(checkdiff_payload, dict):
        return []
    target_asm = checkdiff_payload.get("target_asm") or checkdiff_payload.get("reference_asm")
    if not isinstance(target_asm, list):
        return []
    source_calls = _source_addressed_local_calls(source_text, function)
    if not source_calls:
        return []

    named: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for delta in raw_deltas:
        line_index = delta.get("line_index")
        if not isinstance(line_index, int):
            continue
        call = _nearest_source_backed_call(target_asm, line_index, source_calls)
        if call is None:
            continue
        names = source_calls.get(call) or []
        if not names:
            continue
        name = names[0]
        expected = _int_or_none(delta.get("expected_offset"))
        current = _int_or_none(delta.get("current_offset"))
        if expected is None or current is None:
            continue
        key = (name, expected, current)
        if key in seen:
            continue
        seen.add(key)
        named.append({
            "name": name,
            "delta": expected - current,
            "expected_offset": expected,
            "current_offset": current,
            "call": call,
        })
    return named


def _source_addressed_local_calls(
    source_text: str,
    function: str | None,
) -> dict[str, list[str]]:
    if function:
        bounds = _find_function_bounds(source_text, function)
        if bounds is not None:
            source_text = source_text[bounds[0]:bounds[1]]

    calls: dict[str, list[str]] = {}
    for match in re.finditer(
        r"\b(?P<call>[A-Za-z_]\w*)\s*\((?P<args>[^;{}]*)\)\s*;",
        source_text,
        flags=re.DOTALL,
    ):
        names = re.findall(r"&\s*([A-Za-z_]\w*)", match.group("args"))
        if not names:
            continue
        call = match.group("call")
        bucket = calls.setdefault(call, [])
        for name in names:
            if name not in bucket:
                bucket.append(name)
    return calls


def _nearest_source_backed_call(
    asm_lines: list[Any],
    line_index: int,
    source_calls: dict[str, list[str]],
    *,
    window: int = 6,
) -> str | None:
    for distance in range(0, window + 1):
        prev_idx = line_index - distance
        if 0 <= prev_idx < len(asm_lines):
            call = _asm_call_name(asm_lines[prev_idx])
            if call in source_calls:
                return call
        if distance == 0:
            continue
        next_idx = line_index + distance
        if 0 <= next_idx < len(asm_lines):
            call = _asm_call_name(asm_lines[next_idx])
            if call in source_calls:
                return call
    return None


def _asm_call_name(line: Any) -> str | None:
    text = str(line)
    match = _ASM_RELOC_CALL_RE.search(text)
    if match is None:
        match = _ASM_BRANCH_CALL_RE.search(text)
    if match is None:
        return None
    return match.group("call")


def _variant_summary(variant: dict[str, Any]) -> str:
    objective = variant.get("target_objective") or {}
    if objective.get("target_fixed"):
        parts = ["target fixed"]
    else:
        fixed = objective.get("fixed_count")
        total = objective.get("target_count")
        parts = [f"target partly fixed ({fixed}/{total})"]
    named = [
        f"{item.get('name')} {_format_signed(item.get('delta'))}"
        for item in variant.get("named_local_deltas") or []
        if item.get("name") is not None and item.get("delta") is not None
    ]
    if named:
        if objective.get("target_fixed"):
            parts.append("new local layout deltas remain")
        parts.append("; ".join(named))
    raw_local = variant.get("raw_local_deltas") or []
    if raw_local and not named:
        if objective.get("target_fixed"):
            parts.append("new local layout deltas remain")
        parts.append(f"{len(raw_local)} raw local stack delta(s)")
    remaining = variant.get("remaining_stack_slot_deltas") or []
    if remaining and not named and not raw_local:
        parts.append(f"{len(remaining)} remaining stack-slot delta(s)")
    return "; ".join(parts)


def _variant_sort_key(variant: dict[str, Any]) -> tuple[float, float, float]:
    objective = variant.get("target_objective") or {}
    target_fixed = 1.0 if objective.get("target_fixed") else 0.0
    movement = float(objective.get("movement_score") or 0.0)
    match = objective.get("overall_match_percent")
    match_score = float(match) if isinstance(match, (int, float)) else -1.0
    return target_fixed, movement, match_score


def _find_function_bounds(source_text: str, function: str) -> tuple[int, int] | None:
    # Iterate every 'name(' occurrence and pick the one that is a definition
    # (next non-space char after the closing paren is '{'), skipping
    # prototypes (next non-space char is ';'). Taking the first textual match
    # would otherwise capture an unrelated function body when a forward
    # declaration precedes the real definition.
    pattern = re.compile(rf"\b{re.escape(function)}\s*\(")
    for match in pattern.finditer(source_text):
        open_paren = source_text.find("(", match.end() - 1)
        if open_paren < 0:
            continue
        close_paren = _find_matching(source_text, open_paren, "(", ")")
        if close_paren is None:
            continue
        next_idx = close_paren + 1
        while next_idx < len(source_text) and source_text[next_idx].isspace():
            next_idx += 1
        if next_idx >= len(source_text) or source_text[next_idx] != "{":
            # Prototype (';') or some other non-definition use; keep scanning.
            continue
        open_brace = next_idx
        close_brace = _find_matching(source_text, open_brace, "{", "}")
        if close_brace is None:
            continue
        line_start = source_text.rfind("\n", 0, match.start()) + 1
        return line_start, close_brace + 1
    return None


def _find_first_sqrt_assignment(function_text: str) -> dict[str, Any] | None:
    sqrt_pos = function_text.find("sqrtf(")
    if sqrt_pos < 0:
        return None
    line_start = function_text.rfind("\n", 0, sqrt_pos) + 1
    prefix = function_text[line_start:sqrt_pos]
    match = re.search(
        r"(?P<indent>[ \t]*)(?P<lhs>[A-Za-z_]\w*)\s*=\s*$",
        prefix,
    )
    if match is None:
        return None
    open_paren = function_text.find("(", sqrt_pos)
    close_paren = _find_matching(function_text, open_paren, "(", ")")
    if close_paren is None:
        return None
    semicolon = function_text.find(";", close_paren)
    if semicolon < 0:
        return None
    return {
        "line_start": line_start,
        "end": semicolon + 1,
        "lhs": match.group("lhs"),
        "indent": match.group("indent"),
        "sqrt_call": function_text[sqrt_pos:semicolon].strip(),
    }


def _apply_sqrt_array_variant(
    function_text: str,
    assignment: dict[str, Any],
    *,
    array_size: int,
    index: int,
    placement: str,
) -> str | None:
    decl = f"f32 sqrt_slot[{array_size}];"
    assign = (
        f"{assignment['indent']}sqrt_slot[{index}] = {assignment['sqrt_call']};\n"
        f"{assignment['indent']}{assignment['lhs']} = sqrt_slot[{index}];"
    )
    replaced = (
        function_text[:assignment["line_start"]]
        + assign
        + function_text[assignment["end"]:]
    )
    if placement == "function-top":
        insert_at = _top_decl_insert_pos(replaced)
        if insert_at is None:
            return None
        indent = _line_indent_at(replaced, insert_at) or "    "
        return replaced[:insert_at] + f"{indent}{decl}\n" + replaced[insert_at:]
    if placement == "branch-local":
        return (
            function_text[:assignment["line_start"]]
            + f"{assignment['indent']}{decl}\n"
            + assign
            + function_text[assignment["end"]:]
        )
    return None


def _top_decl_insert_pos(function_text: str) -> int | None:
    open_brace = function_text.find("{")
    if open_brace < 0:
        return None
    body_start = open_brace + 1
    lines = list(re.finditer(r".*(?:\n|$)", function_text[body_start:]))
    last_decl_end: int | None = None
    in_decl_block = True
    for line_match in lines:
        raw = line_match.group(0)
        if raw == "":
            continue
        stripped = raw.strip()
        abs_end = body_start + line_match.end()
        if not stripped:
            if last_decl_end is not None:
                return body_start + line_match.start()
            continue
        if in_decl_block and _looks_like_local_decl(stripped):
            last_decl_end = abs_end
            continue
        in_decl_block = False
        break
    return last_decl_end


def _looks_like_local_decl(stripped_line: str) -> bool:
    if not stripped_line.endswith(";"):
        return False
    if stripped_line.startswith(("return ", "if ", "for ", "while ", "switch ")):
        return False
    return bool(re.match(
        r"(?:const\s+|volatile\s+|static\s+)?"
        r"(?:f32|float|double|s32|u32|int|Vec3|[A-Za-z_]\w*_t|[A-Za-z_]\w*)"
        r"(?:\s*\*|\s+)+[A-Za-z_]\w*",
        stripped_line,
    ))


def _line_indent_at(text: str, pos: int) -> str:
    line_start = text.rfind("\n", 0, pos) + 1
    match = re.match(r"[ \t]*", text[line_start:pos])
    return "" if match is None else match.group(0)


def _find_matching(text: str, open_idx: int, open_char: str, close_char: str) -> int | None:
    if open_idx < 0 or open_idx >= len(text) or text[open_idx] != open_char:
        return None
    depth = 0
    for idx in range(open_idx, len(text)):
        char = text[idx]
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return idx
    return None


def _format_signed(value: Any) -> str:
    number = _int_or_none(value)
    if number is None:
        return str(value)
    return f"{number:+d}"


def _is_stack_home_candidate(candidate: dict[str, Any]) -> bool:
    if candidate.get("site_kind") == "final-only-stack-home":
        return True
    opcode = str(candidate.get("opcode") or "")
    return (
        opcode in {"lfs", "lfd", "stfs", "stfd"}
        and candidate.get("current_offset") is not None
        and candidate.get("expected_offset") is not None
    )


def _explain_lifetimes(
    pcdump_text: str,
    function: str,
    candidates: list[dict[str, Any]],
    *,
    source_text: str | None,
    source_file: str | None,
) -> dict[tuple[int, int], dict[str, Any]]:
    by_class: dict[int, list[int]] = {}
    for candidate in candidates:
        class_id = _int_or_none(candidate.get("register_class"))
        virtual = _int_or_none(candidate.get("virtual"))
        if class_id is None or virtual is None:
            continue
        by_class.setdefault(class_id, []).append(virtual)

    out: dict[tuple[int, int], dict[str, Any]] = {}
    for class_id, virtuals in by_class.items():
        reg_class = "fpr" if class_id == 1 else "gpr"
        try:
            report = explain_virtuals(
                pcdump_text,
                function,
                virtuals=sorted(set(virtuals)),
                source_text=source_text,
                source_file=source_file,
                reg_class=reg_class,
            )
        except Exception as exc:
            for virtual in virtuals:
                out[(class_id, virtual)] = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            continue
        for entry in report.virtuals:
            out[(class_id, entry.virtual)] = asdict(entry)
    return out


def _target_report(
    candidate: dict[str, Any],
    *,
    all_candidates: list[dict[str, Any]],
    lifetimes: dict[tuple[int, int], dict[str, Any]],
    neighbor_window: int,
    max_suggestions: int,
) -> dict[str, Any]:
    class_id = _int_or_none(candidate.get("register_class"))
    virtual = _int_or_none(candidate.get("virtual"))
    lifetime = (
        lifetimes.get((class_id, virtual), {})
        if class_id is not None and virtual is not None
        else {}
    )
    target = {
        "opcode": candidate.get("opcode"),
        "current_offset": candidate.get("current_offset"),
        "expected_offset": candidate.get("expected_offset"),
        "delta": candidate.get("delta"),
        "register_class": class_id,
        "register_class_name": _class_name(class_id),
        "virtual": virtual,
        "virtual_token": candidate.get("virtual_token"),
        "spill_root": candidate.get("spill_root"),
        "assigned_reg": candidate.get("assigned_reg"),
        "site_kind": candidate.get("site_kind"),
        "mapping_status": candidate.get("mapping_status"),
        "simplify": candidate.get("simplify") or {},
        "aliases": {
            "natural": candidate.get("natural_coalesce_aliases") or [],
            "coalesced": candidate.get("coalesced_aliases") or [],
        },
        "source_expression": _source_expression(candidate, lifetime),
        "lifetime": _lifetime_summary(lifetime),
        "neighboring_stack_homes": _neighboring_stack_homes(
            candidate,
            all_candidates,
            neighbor_window=neighbor_window,
        ),
        "evidence": list(candidate.get("evidence") or []),
    }
    target["suggestions"] = _suggestions_for_target(
        target,
        lifetime,
        max_suggestions=max_suggestions,
    )
    return target


def _target_sort_key(target: dict[str, Any]) -> tuple[int, int, int]:
    class_score = 1 if target.get("register_class") == 1 else 0
    final_score = 1 if target.get("site_kind") == "final-only-stack-home" else 0
    delta = abs(_int_or_none(target.get("delta")) or 0)
    return (class_score, final_score, delta)


def _source_expression(
    candidate: dict[str, Any],
    lifetime: dict[str, Any],
) -> dict[str, Any] | None:
    source = candidate.get("nearest_source_expression")
    if source:
        return source
    source = lifetime.get("source")
    if not isinstance(source, dict):
        return None
    expression = source.get("expression") or source.get("name")
    if not expression:
        return None
    return {
        "expression": expression,
        "confidence": source.get("confidence"),
        "source_file": source.get("source_file"),
        "source_line": source.get("source_line"),
        "source_col": source.get("source_col"),
    }


def _lifetime_summary(lifetime: dict[str, Any]) -> dict[str, Any]:
    if not lifetime:
        return {}
    source = lifetime.get("source")
    return {
        "status": lifetime.get("status"),
        "live_range": lifetime.get("live_range"),
        "live_blocks": lifetime.get("live_blocks") or [],
        "use_count": lifetime.get("use_count"),
        "first_occurrence": lifetime.get("first_occurrence"),
        "last_occurrence": lifetime.get("last_occurrence"),
        "source_kind": source.get("kind") if isinstance(source, dict) else None,
    }


def _neighboring_stack_homes(
    candidate: dict[str, Any],
    all_candidates: list[dict[str, Any]],
    *,
    neighbor_window: int,
) -> list[dict[str, Any]]:
    current = _int_or_none(candidate.get("current_offset"))
    expected = _int_or_none(candidate.get("expected_offset"))
    class_id = _int_or_none(candidate.get("register_class"))
    anchors = [value for value in (current, expected) if value is not None]
    seen: set[tuple[int, str, str | None]] = set()
    out: list[dict[str, Any]] = []

    def add(offset: int, role: str, item: dict[str, Any] | None = None) -> None:
        key = (offset, role, None if item is None else item.get("virtual_token"))
        if key in seen:
            return
        seen.add(key)
        out.append({
            "offset": offset,
            "role": role,
            "virtual_token": None if item is None else item.get("virtual_token"),
            "opcode": None if item is None else item.get("opcode"),
            "assigned_reg": None if item is None else item.get("assigned_reg"),
            "site_kind": None if item is None else item.get("site_kind"),
        })

    for item in all_candidates:
        if _int_or_none(item.get("register_class")) != class_id:
            continue
        offset = _int_or_none(item.get("current_offset"))
        if offset is None or not _near_any(offset, anchors, neighbor_window):
            continue
        role = "current-target" if offset == current else "neighbor-current"
        add(offset, role, item)

    for item in candidate.get("stack_home_order") or []:
        offset = _int_or_none(item.get("offset"))
        if offset is None or not _near_any(offset, anchors, neighbor_window):
            continue
        role = "precolor-home"
        add(offset, role, item)

    if expected is not None:
        add(expected, "expected-target", None)
    if current is not None and current != expected:
        add(current, "current-offset", None)

    out.sort(key=lambda item: (item["offset"], item["role"]))
    return out


def _suggestions_for_target(
    target: dict[str, Any],
    lifetime: dict[str, Any],
    *,
    max_suggestions: int,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    first = lifetime.get("first_occurrence") or {}
    first_opcode = str(first.get("opcode") or "").lower()
    source = target.get("source_expression") or {}
    expression = source.get("expression") or (
        f"{first_opcode} {first.get('operands')}"
        if first_opcode
        else "target expression"
    )
    objective = _target_offset_objective(target)

    if first_opcode == "fmr":
        suggestions.append(_suggestion(
            "remove-or-inline-copy-temp",
            (
                "Inline the float copy into its single downstream use, or "
                "name the source-side value instead of the copy."
            ),
            (
                "replace the separate copied float temp with a direct use of "
                f"the C expression that produced `{expression}`"
            ),
            objective,
            target,
            boost=30,
        ))

    if first_opcode in {
        "fadd",
        "fadds",
        "fsub",
        "fsubs",
        "fmul",
        "fmuls",
        "fdiv",
        "fdivs",
    }:
        suggestions.append(_suggestion(
            "split-binary-float-expression",
            (
                "Split the binary float expression into one adjacent named "
                "operand temp and the final expression."
            ),
            (
                "float operand_tmp = <one C operand>; "
                "float target_tmp = operand_tmp <op> <other operand>; "
                f"/* `{expression}` */"
            ),
            objective,
            target,
            boost=28,
        ))

    if target.get("register_class") == 1:
        suggestions.append(_suggestion(
            "introduce-named-float-temp",
            (
                "Name the target FPR expression immediately before its use "
                "to perturb reusable stack-home pressure locally."
            ),
            (
                "float target_tmp = <C expression for "
                f"`{expression}`>; use target_tmp at the original use"
            ),
            objective,
            target,
            boost=24,
        ))

    aliases = (target.get("aliases") or {}).get("natural") or []
    if aliases:
        suggestions.append(_suggestion(
            "narrow-alias-lifetime",
            (
                "Shorten the source lifetime for the coalesced alias cluster "
                "so the stack home can be assigned after nearby FPR temps."
            ),
            "move the aliased temp declaration into the smallest enclosing block",
            objective,
            target,
            boost=18,
        ))

    simplify = target.get("simplify") or {}
    if simplify.get("spilled"):
        suggestions.append(_suggestion(
            "lifetime-shortening-scope-block",
            (
                "Introduce a tiny block around the target computation to end "
                "the spilled FPR temp before unrelated float work."
            ),
            "{ float tmp = <target expression>; <existing use>; }",
            objective,
            target,
            boost=14,
        ))

    suggestions.sort(key=lambda item: item["_score"], reverse=True)
    out = []
    for rank, item in enumerate(suggestions[:max_suggestions], start=1):
        item = dict(item)
        item.pop("_score", None)
        item["rank"] = rank
        out.append(item)
    return out


def _suggestion(
    kind: str,
    description: str,
    edit_sketch: str,
    objective: dict[str, Any],
    target: dict[str, Any],
    *,
    boost: int,
) -> dict[str, Any]:
    score = boost
    if target.get("site_kind") == "final-only-stack-home":
        score += 20
    if target.get("register_class") == 1:
        score += 20
    if target.get("delta") is not None:
        score += abs(_int_or_none(target.get("delta")) or 0)
    if (target.get("aliases") or {}).get("natural"):
        score += 5
    if (target.get("simplify") or {}).get("spilled"):
        score += 5
    return {
        "kind": kind,
        "description": description,
        "edit_sketch": edit_sketch,
        "target_offset_objective": dict(objective),
        "rank_basis": [
            (
                "final-only-stack-home"
                if target.get("site_kind") == "final-only-stack-home"
                else "stack-home"
            ),
            _class_name(target.get("register_class")),
            "target-offset-before-overall-score",
        ],
        "_score": score,
    }


def _target_offset_objective(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_offset": target.get("current_offset"),
        "expected_offset": target.get("expected_offset"),
        "desired_delta": target.get("delta"),
        "target_movement_measured": False,
        "target_moved": None,
        "movement_score": None,
        "overall_match_percent": None,
    }


def _near_any(offset: int, anchors: list[int], window: int) -> bool:
    return not anchors or any(abs(offset - anchor) <= window for anchor in anchors)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            return int(value, 0)
        return int(value)
    except (TypeError, ValueError):
        return None


def _class_name(class_id: Any) -> str:
    class_int = _int_or_none(class_id)
    if class_int == 1:
        return "fpr"
    if class_int == 0:
        return "gpr"
    return "unknown"


def _format_offset(value: Any) -> str:
    offset = _int_or_none(value)
    if offset is None:
        return "?"
    return f"0x{offset:X}"
